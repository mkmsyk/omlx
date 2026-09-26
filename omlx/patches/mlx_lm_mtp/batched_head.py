# SPDX-License-Identifier: Apache-2.0
"""Keep a Lightning MTP head cache batched between verify cycles."""

import time
from dataclasses import dataclass

import mlx.core as mx
from mlx_lm.models.cache import KVCache

from . import batch_generator as bg


@dataclass
class _HeadCache:
    states: tuple
    cache: list
    speculative: int


def flush(batch_state):
    """Return each row's full head cache before request-local code resumes."""
    owned = getattr(batch_state, "head", None)
    if owned is None:
        return
    for index, state in enumerate(owned.states):
        state.mtp_cache = [layer.extract(index) for layer in owned.cache]
    batch_state.head = None


def eligible(batch, rows):
    host = getattr(batch.model, "_language_model", None)
    states = tuple(state for _, _, state in rows)
    owner = getattr(batch, "_omlx_mtp_batch_state", None)
    owned = getattr(owner, "head", None)
    same = (
        owned is not None
        and len(states) == len(owned.states)
        and all(left is right for left, right in zip(states, owned.states))
    )
    if not same:
        flush(owner)
    return (
        owner is not None
        and len(rows) > 1
        and getattr(host, "_omlx_mtp_batch_rollback", False)
        and not getattr(batch.model, "_omlx_mtp_commit_align", 0)
        and len({state.depth for state in states}) == 1
        and all(
            state.depth > 0
            and state.controller is None
            and state.head_clone == states[0].head_clone
            and bg._proc_list(row) is None
            and (
                same
                or (
                    state.mtp_cache
                    and all(
                        type(c) is KVCache
                        or getattr(type(c), "_omlx_mtp_batched_head_cache", False)
                        for c in state.mtp_cache
                    )
                )
            )
            for _, row, state in rows
        )
    )


def _sample_rows(samplers, lp):
    key = getattr(samplers[0], "_mtp_batch_sampling_key", None)
    if (
        len(samplers) > 1
        and key is not None
        and all(
            getattr(sampler, "_mtp_batch_sampling_key", None) == key
            for sampler in samplers[1:]
        )
    ):
        return samplers[0].sample_with_logprobs(lp, rowwise=True)
    sampled = [
        bg._sample_draft_with_logprobs(sampler, lp[row : row + 1])
        for row, sampler in enumerate(samplers)
    ]
    return (
        mx.concatenate([token.reshape(1) for token, _ in sampled]),
        mx.concatenate([density for _, density in sampled]),
    )


def draft(batch, jobs):
    """Fold ragged accepted histories, then draft on the intact batch cache."""
    owner = batch._omlx_mtp_batch_state
    states = tuple(job[1] for job in jobs)
    depth = states[0].depth
    head_clone = states[0].head_clone
    started = time.perf_counter()
    sizes = [int(job[3].shape[0]) for job in jobs]
    width = max(sizes)
    hidden = mx.concatenate(
        [
            mx.pad(job[2], [(0, 0), (0, width - size), (0, 0)])
            for job, size in zip(jobs, sizes)
        ]
    )
    host = batch.model._language_model
    head_prenorm = getattr(host, "_omlx_mtp_head_prenorm", False)
    if bg._HEAD_HIDDEN_POST_NORM and not head_prenorm:
        hidden = bg._trunk_norm_module(batch.model)(hidden)
    tokens = mx.stack(
        [mx.pad(job[3], [(0, width - size)]) for job, size in zip(jobs, sizes)]
    )
    owned = owner.head
    if owned is None:
        if not head_clone:
            for state in states:
                bg._mtp_head_trim_to(state.mtp_cache, state.hist_offset)
        cache = bg._merge_row_caches([state.mtp_cache for state in states])
    else:
        cache = owned.cache
        # This is the preceding cycle's speculative suffix, not the new depth.
        if not head_clone:
            for layer in cache:
                layer.trim(owned.speculative)
    for layer in cache:
        padding = [width - size for size in sizes]
        if head_clone:
            layer.prepare(lengths=sizes, right_padding=padding)
        else:
            layer.prepare(right_padding=padding)
    positions = mx.array(sizes)[:, None, None] - 1
    if head_prenorm or head_clone:
        # HC heads return raw recurrent hidden separately from projected logits.
        all_logits, raw_hidden = batch.model.mtp_forward(
            hidden, tokens, cache, return_hidden=True
        )
        selected = mx.take_along_axis(raw_hidden, positions, axis=1)
        logits = mx.take_along_axis(all_logits, positions, axis=1)
    else:
        head = host.mtp(hidden, tokens, host.model.embed_tokens, cache)
        selected = mx.take_along_axis(head, positions, axis=1)
        logits = (
            host.model.embed_tokens.as_linear(selected)
            if host.args.tie_word_embeddings
            else host.lm_head(selected)
        )
    for layer in cache:
        layer.finalize()
    chain_cache = (
        bg._clone_mtp_head_cache(cache) if head_clone and depth > 1 else cache
    )
    samplers = [bg._resolve_draft_sampler(row, state) for row, state, *_ in jobs]
    greedy = all(bg._is_greedy(row) for row, *_ in jobs)
    drafted, probabilities, acceptance = [], [], []
    for index in range(depth):
        lp = bg._logprobs(logits[:, -1, :])
        if greedy:
            token = mx.argmax(lp, axis=-1).astype(mx.uint32)
            accept_lp = lp
        else:
            token, accept_lp = _sample_rows(samplers, lp)
            token = token.astype(mx.uint32)
        drafted.append(token)
        probabilities.append(lp)
        acceptance.append(accept_lp)
        if index + 1 < depth:
            logits, selected = batch.model.mtp_forward(
                selected, token[:, None], chain_cache, return_hidden=True
            )
    result = mx.stack(drafted, axis=1)
    mx.async_eval(result)
    owner.head = _HeadCache(states, cache, 0 if head_clone else depth - 1)
    elapsed = (time.perf_counter() - started) * 1000 / len(states)
    for index, state in enumerate(states):
        state.hist_offset += sizes[index]
        state.drafts = result[index]
        state.draft_lps = [lp[index] for lp in probabilities]
        state.draft_accept_lps = [lp[index] for lp in acceptance]
        state.stats.mtp_head_ms += elapsed
        # The authoritative cache is owner.head until flush restores rows.
        state.mtp_cache = None


def _rows_host(model):
    for host in (model, getattr(model, "_language_model", None), getattr(model, "language_model", None)):
        if host is not None and callable(getattr(host, "mtp_forward_rows", None)):
            return host
    return None


def stateless_eligible(batch, rows):
    """Heads without a cache (Gemma 4 assistant) that can draft all rows at once."""
    if len(rows) < 2 or _rows_host(batch.model) is None:
        return False
    states = [state for _, _, state in rows]
    depth = states[0].depth
    return all(
        state.chain
        and state.controller is None
        and state.depth == depth
        and not state.mtp_cache
        and not state.head_clone
        and bg._proc_list(row) is None
        for _, row, state in rows
    )


def draft_stateless(batch, jobs):
    """Draft the next chain for every shared-verify row with one head call per step.

    ``jobs`` arrive in verify-row order (``(row, state, hidden_rows,
    committed, prev_buf)`` from ``_run_verify_cycle_chain``). The per-row
    path (``_chain_next_drafts``) calls the head ``rows x depth`` times and
    builds each call's graph on the host while the GPU waits; here each chain
    step is one call over all rows, with the same inputs, positions and
    sampling as the per-row path.
    """
    host = _rows_host(batch.model)
    states = [job[1] for job in jobs]
    depth = states[0].depth
    if depth == 0:
        # Mirrors _chain_next_drafts for a stateless head at depth 0.
        for state in states:
            state.drafts = mx.zeros((0,), dtype=mx.uint32)
            state.draft_lps = []
            state.draft_accept_lps = []
        return
    started = time.perf_counter()
    hidden = mx.concatenate([job[2][:, -1:, :] for job in jobs])
    head_prenorm = getattr(host, "_omlx_mtp_head_prenorm", False)
    if bg._HEAD_HIDDEN_POST_NORM and not head_prenorm:
        hidden = bg._trunk_norm_module(batch.model)(hidden)
    tokens = mx.stack([job[3][-1:] for job in jobs])
    rows = list(range(len(jobs)))
    logits, head_hidden = host.mtp_forward_rows(hidden, tokens, rows)
    samplers = [bg._resolve_draft_sampler(row, state) for row, state, *_ in jobs]
    greedy = all(bg._is_greedy(row) for row, *_ in jobs)
    drafted, probabilities, acceptance = [], [], []
    for index in range(depth):
        lp = bg._logprobs(logits[:, -1, :])
        if greedy:
            token = mx.argmax(lp, axis=-1).astype(mx.uint32)
            accept_lp = lp
        else:
            token, accept_lp = _sample_rows(samplers, lp)
            token = token.astype(mx.uint32)
        drafted.append(token)
        probabilities.append(lp)
        acceptance.append(accept_lp)
        if index + 1 < depth:
            logits, head_hidden = host.mtp_forward_rows(
                head_hidden[:, -1:], token[:, None], rows
            )
    result = mx.stack(drafted, axis=1)
    mx.async_eval(result)
    elapsed = (time.perf_counter() - started) * 1000 / len(states)
    for index, (job, state) in enumerate(zip(jobs, states)):
        state.hist_offset += int(job[3].shape[0])
        state.drafts = result[index]
        state.draft_lps = [lp[index] for lp in probabilities]
        state.draft_accept_lps = [lp[index] for lp in acceptance]
        state.stats.mtp_head_ms += elapsed
