# SPDX-License-Identifier: Apache-2.0
"""Runtime MTP head attachment for the mlx-vlm Gemma 4 VLM path.

Gemma 4 ships its MTP head as a separate ``gemma4_assistant`` checkpoint
(mlx-vlm loads it via ``load_drafter`` for the vlm_mtp round-loop). This
patch instead supports **merged single-checkpoint** models: the assistant
weights live under ``language_model.mtp.*`` in the main checkpoint and the
assistant config is embedded at ``text_config.mtp_assistant_config``. With
``model_settings.mtp_enabled`` the model then runs through the Lightning
MTP cycle in ``mlx_lm_mtp.batch_generator`` — batched decode, paged /
prefix / SSD caches and rollback all unchanged.

How the assistant head differs from the Qwen3.5 MTPModule:

* It is **stateless** — no KV cache of its own (``make_mtp_cache`` returns
  ``[]``). Its four decoder layers attend over the backbone's last
  sliding-attention and last full-attention layers' K/V (Gemma 4 KV
  sharing, ``kv_shared_only=True``).
* Drafting holds the query position constant and feeds the head's
  ``post_projection`` output back as the next chain step's hidden input
  (mirrors HF ``SinglePositionMultiTokenCandidateGenerator``).

To feed it inside the Lightning cycle, the patched ``__call__`` captures
``shared_kv_sink`` during every ``return_hidden=True`` backbone forward
(the verify / post-init forwards) and stashes it with the live cache list;
``mtp_forward`` then reads the query position from the current cache
offset, so post-rollback folds automatically see the committed length and
mask the rejected tail via ``kv_valid_len``.

Known approximation: after a rejection, the stashed sliding-window bank
still contains the rejected draft rows. The full-attention bank masks them
exactly by index; a rotated sliding ring can mask up to ``depth`` wrong
slots out of ``sliding_window`` until the next verify refreshes the stash.
This only affects draft quality (accept rate), never output correctness —
the verify forward guarantees the output distribution.

Apply ordering: must run *before* ``mlx_vlm.utils.load(...)`` so the
patched ``LanguageModel.__init__`` attaches the head for weight binding.
``maybe_apply_pre_load_patches`` handles this for inference loads.
"""

from __future__ import annotations

import logging
from typing import Any

import mlx.core as mx

logger = logging.getLogger(__name__)

_APPLIED = False


def apply() -> bool:
    """Apply the mlx-vlm Gemma 4 runtime MTP patches. Idempotent."""
    global _APPLIED
    if _APPLIED:
        return True

    try:
        from mlx_vlm.models.gemma4 import config as g4_config
        from mlx_vlm.models.gemma4 import language as g4_lang
        from mlx_vlm.models.gemma4_unified import config as g4_unified_config
        from mlx_vlm.speculative.drafters.gemma4_assistant import (  # noqa: F401
            Gemma4AssistantDraftModel,
        )
    except Exception as e:
        logger.debug(f"mlx_vlm.gemma4 not importable for MTP runtime: {e}")
        return False

    from mlx_vlm.models.gemma4 import Model
    from mlx_vlm.models.gemma4_unified import Model as UnifiedModel

    def keep_head(original_sanitize):
        def sanitize(self, weights):
            head = {
                k: v for k, v in weights.items() if k.startswith("language_model.mtp.")
            }
            backbone = {k: v for k, v in weights.items() if k not in head}
            return {**original_sanitize(self, backbone), **head}

        return sanitize

    # Text-only gemma4 checkpoints load as gemma4_unified; see omlx.engine.vlm.
    Model.sanitize = keep_head(Model.sanitize)
    UnifiedModel.sanitize = keep_head(UnifiedModel.sanitize)
    _patch_text_config(g4_config)
    # Gemma4 unified reuses Gemma4's LanguageModel but declares its own
    # TextConfig subclass. Retain the embedded assistant config there too so
    # the shared language model can attach the head during loading.
    _patch_text_config(g4_unified_config)
    _patch_vlm_language_model(g4_lang)
    # VLMModelAdapter pass-throughs (mtp / mtp_forward / make_mtp_cache /
    # rollback_speculative_cache) are shared with the Qwen3.5 runtimes;
    # the helper is idempotent.
    from .qwen35_vlm_runtime import _patch_vlm_model_adapter

    _patch_vlm_model_adapter()

    # MLX 0.32.2 covers Gemma4's head-dim-256 small-L shapes natively. Global
    # head-dim-512 verify still needs the custom fused route to keep
    # shallow-depth speculation profitable.
    from ..gemma4_verify_attention import apply as apply_verify_attention

    apply_verify_attention()

    _APPLIED = True
    logger.info("mlx-vlm Gemma 4 runtime MTP patch applied")
    return True


# ---------------------------------------------------------------------------
# TextConfig — retain the embedded assistant config across from_dict.
# ---------------------------------------------------------------------------


def _patch_text_config(g4_config: Any) -> None:
    """Wrap ``TextConfig.from_dict`` so ``mtp_assistant_config`` survives.

    mlx-vlm's ``BaseModelConfig.from_dict`` filters params by the dataclass
    signature, dropping the embedded assistant config dict. Without it the
    patched ``LanguageModel.__init__`` cannot size or attach the head.
    """
    cls = g4_config.TextConfig
    if getattr(cls, "_omlx_mtp_from_dict_patched", False):
        return

    original_from_dict = cls.from_dict.__func__  # unwrap classmethod

    def patched_from_dict(cls_inner, params):
        instance = original_from_dict(cls_inner, params)
        if params:
            instance.mtp_assistant_config = params.get("mtp_assistant_config")
        else:
            instance.mtp_assistant_config = None
        return instance

    cls.from_dict = classmethod(patched_from_dict)
    cls._omlx_mtp_from_dict_patched = True


# ---------------------------------------------------------------------------
# LanguageModel — attach head, stash shared K/V, add mtp_forward/cache.
# ---------------------------------------------------------------------------


def _align_drafter_dtype(drafter: Any, dtype: Any) -> None:
    """Match the head to its activation dtype so matmuls don't promote to float32."""
    from mlx.utils import tree_map

    def _cast(value: Any) -> Any:
        if (
            isinstance(value, mx.array)
            and value.dtype in (mx.float16, mx.bfloat16)
            and value.dtype != dtype
        ):
            return value.astype(dtype)
        return value

    drafter.update(tree_map(_cast, drafter.parameters()))
    logger.info("gemma4 vlm assistant head aligned to %s", dtype)


def _draft_forward(drafter: Any, inputs_embeds, shared_kv, position: int, kv_valid_len: int):
    """``Gemma4AssistantDraftModel.__call__`` for one row at a host position.

    The stock forward reads a single row's query position back with
    ``position_ids[0, 0].item()``, a host sync on the serial stream that
    waits for every queued verify and draft kernel. The Lightning cycle
    already holds the position as a host int, so build the same masks and
    layer calls from it and keep the draft chain asynchronous.
    """
    from mlx_vlm.speculative.drafters.gemma4_assistant.masks import make_drafter_masks

    text_cfg = drafter.config.text_config
    h = drafter.pre_projection(inputs_embeds)
    masks = make_drafter_masks(
        shared_kv,
        query_len=h.shape[1],
        query_offset=position,
        sliding_window=text_cfg.sliding_window,
        dtype=h.dtype,
        kv_valid_len=kv_valid_len,
    )
    offset = mx.array(position)
    for layer in drafter.model.layers:
        h, _, _ = layer(
            h,
            mask=masks[layer.layer_type],
            cache=None,
            per_layer_input=None,
            shared_kv=shared_kv[layer.layer_type],
            offset=offset,
        )
    h = drafter.model.norm(h)
    last_hidden = drafter.post_projection(h)
    logits = (
        drafter._lm_head_fn(h)
        if drafter._lm_head_fn is not None
        else drafter.model.embed_tokens.as_linear(h)
    )
    return last_hidden, logits


def _patch_vlm_language_model(g4_lang: Any) -> None:
    cls = g4_lang.LanguageModel
    if "_omlx_mtp_runtime_patched" in cls.__dict__:
        return

    from mlx_vlm.models.base import LanguageModelOutput
    from mlx_vlm.speculative.cache_state import (
        SpeculativeCacheTransaction,
        start_speculative_cache,
    )
    from mlx_vlm.speculative.cache_state import (
        rollback_speculative_cache as rollback_cache_transaction,
    )
    from mlx_vlm.speculative.drafters.gemma4_assistant import (
        Gemma4AssistantDraftModel,
        ModelConfig as Gemma4AssistantConfig,
    )
    from mlx_vlm.speculative.mtp import _slice_shared_kv_after_reject  # noqa: SLF001

    original_init = cls.__init__
    original_call = cls.__call__
    original_rollback = cls.rollback_speculative_cache

    def __init__(self, config):
        from . import is_mtp_attach_enabled
        from ..mlx_lm_mtp import get_mtp_depth, is_mtp_active

        original_init(self, config)
        asst_cfg = getattr(config, "mtp_assistant_config", None)
        attach = bool(asst_cfg) and bool(is_mtp_attach_enabled())
        self._omlx_mtp_decode_enabled = bool(attach and is_mtp_active())
        if attach:
            drafter_config = Gemma4AssistantConfig.from_dict(asst_cfg)
            self.mtp = Gemma4AssistantDraftModel(drafter_config)
            # Defer binding until quantization replaces the initial embedding.
        if self._omlx_mtp_decode_enabled:
            # The chain cycle applies the backbone's final RMSNorm to the
            # verify hidden rows (HEAD_HIDDEN_POST_NORM) — exactly the
            # ``speculative_draft_hidden`` variant this drafter consumes.
            self._omlx_mtp_chain = True
            self._omlx_mtp_depth = get_mtp_depth()

    def __call__(self, inputs, inputs_embeds=None, mask=None, cache=None, **kwargs):
        """Backbone forward with MTP-cycle shared-K/V capture.

        For ``return_hidden=True`` forwards on an MTP-enabled instance
        (the Lightning verify / post-init calls), capture the shared K/V
        banks the assistant head drafts against and remember the live
        cache list for position bookkeeping. ``gdn_states=[]`` (Gemma 4
        has no SSM state) routes ``_chain_rollback`` to the stock
        ``rollback_speculative_cache``.
        """
        return_hidden = bool(kwargs.get("return_hidden", False))
        if not (return_hidden and getattr(self, "_omlx_mtp_decode_enabled", False)):
            return original_call(self, inputs, inputs_embeds, mask, cache, **kwargs)

        kwargs.pop("n_confirmed", None)  # mlx-vlm rollback is post-hoc
        sink = kwargs.pop("shared_kv_sink", None)
        if sink is None:
            sink = {}
        # Multi-row verify blocks end with a different accepted count per
        # row. The stock trim rejects ragged accepts (mlx-vlm #1962), so the
        # shared verify runs inside a cache transaction that keeps each
        # row's accepted prefix (rotating windows replay accepted K/V).
        # Singleton forwards keep the stock trim + undo path unchanged.
        batched = int(inputs.shape[0]) > 1
        transaction = start_speculative_cache(cache or [], inputs.shape[1]) if batched else None
        try:
            out = original_call(
                self,
                inputs,
                inputs_embeds,
                mask,
                cache,
                shared_kv_sink=sink,
                **kwargs,
            )
        except BaseException:
            if transaction is not None:
                transaction.abort()
            raise
        self._omlx_mtp_shared_kv = sink
        self._omlx_mtp_cache_ref = cache
        self._omlx_mtp_row_spans = None
        if batched:
            # Per-row processed lengths at capture. Every row of a stashed
            # bank ends at the same (right-aligned) slot, so a row's
            # committed span is located by comparing these with the
            # post-rollback lengths (see _row_shared_kv). Kept lazy (the
            # ``+ 0`` detaches from in-place trims) so capture adds no sync.
            self._omlx_mtp_row_offsets = _row_offset_array(cache) + 0
            self._omlx_mtp_kv_offset = None
        else:
            self._omlx_mtp_row_offsets = None
            # Committed length at capture time. A later rollback lowers the
            # live cache counters below this, and mtp_forward slices the
            # rejected tail off the stashed banks by the difference.
            self._omlx_mtp_kv_offset = _mtp_query_position(self)
        return LanguageModelOutput(
            logits=out.logits,
            hidden_states=out.hidden_states,
            gdn_states=transaction if batched else [],
            shared_kv_states=sink,
        )

    def rollback_speculative_cache(self, caches, gdn_states, accepted, block_size):
        """Commit ragged accepts through the verify transaction when present."""
        if isinstance(gdn_states, SpeculativeCacheTransaction):
            return rollback_cache_transaction(caches, gdn_states, accepted, block_size)
        return original_rollback(self, caches, gdn_states, accepted, block_size)

    def _row_offset_array(cache):
        """Per-row processed token counts of a batched cache list."""
        for c in cache or []:
            offset = getattr(c, "offset", None)
            if isinstance(offset, mx.array) and offset.ndim == 1:
                return offset
        raise RuntimeError("gemma4 batched MTP: no per-row cache offset available")

    def _row_shared_kv(self, row: int):
        """Row ``row``'s committed shared K/V from a batched verify capture.

        Each stashed bank is right-aligned: every row's newest verify slot
        sits at the bank's last index. A row that accepted fewer drafts
        than the verify depth ends ``capture - committed`` slots earlier.
        The span is sliced to the row's committed tokens (bounded by the
        bank's length for the sliding window), which is exactly the compact
        layout of a singleton capture.

        The first draft after the shared rollback reads every row's lengths
        in one host sync; the other rows and chain steps reuse the spans so
        each request's draft chain queues without waiting for the previous
        row's GPU work.
        """
        spans = self._omlx_mtp_row_spans
        if spans is None:
            captured, committed = mx.stack(
                [
                    self._omlx_mtp_row_offsets,
                    _row_offset_array(self._omlx_mtp_cache_ref),
                ]
            ).tolist()
            spans = self._omlx_mtp_row_spans = {
                "captured": [int(v) for v in captured],
                "committed": [int(v) for v in committed],
                "banks": {},
            }
        banks = spans["banks"].get(row)
        committed = spans["committed"][row]
        if banks is not None:
            return banks, committed
        rejected = spans["captured"][row] - committed
        if rejected < 0:
            raise RuntimeError(
                f"gemma4 batched MTP: row {row} grew after capture "
                f"({spans['captured'][row]} -> {committed})"
            )
        banks = {}
        for layer_type, (keys, values) in self._omlx_mtp_shared_kv.items():
            end = int(keys.shape[-2]) - rejected
            start = max(end - committed, 0)
            if end <= start:
                raise RuntimeError(
                    f"gemma4 batched MTP: empty {layer_type} span for row {row}"
                )
            banks[layer_type] = (
                keys[row : row + 1, :, start:end, :],
                values[row : row + 1, :, start:end, :],
            )
        spans["banks"][row] = banks
        return banks, committed

    def _mtp_query_position(self) -> int:
        """Current committed length = the drafter's constant query position.

        Read from the live cache list (stashed at the last verify forward)
        so post-rollback folds see the committed offset, not the verify
        length. Uses the caches' host-side int counters — never the
        per-row ``offset`` mx.array — to keep the chain cycle sync-free:
        ``BatchRotatingKVCache._offset`` is the absolute processed length
        (its ``_idx`` is a ring index), ``BatchKVCache._idx`` is the
        storage length (== committed length; singleton MTP activation
        guarantees zero left padding), and plain caches keep an int
        ``offset``. All three are adjusted by ``trim`` / the rollback
        undo, so post-rollback reads are committed-only.
        """
        for c in self._omlx_mtp_cache_ref or []:
            rotating_offset = getattr(c, "_offset", None)
            if isinstance(rotating_offset, int):
                return rotating_offset
            offset = getattr(c, "offset", None)
            if isinstance(offset, int):
                return offset
            idx = getattr(c, "_idx", None)
            if isinstance(idx, int):
                return idx
        raise RuntimeError("gemma4 mtp_forward: no cache offset available")

    def mtp_forward(
        self,
        hidden_states,
        next_token_ids,
        mtp_cache,
        return_hidden: bool = False,
        logits_keep: int = 0,
    ):
        """Assistant-head forward under the Lightning chain contract.

        The head is single-position (no history fold): only the last
        (hidden, token) pair matters, so multi-row history folds slice to
        the final position. ``hidden_states`` is either the trunk-normed
        backbone hidden (first fold call) or the head's own
        ``post_projection`` output (chain steps) — both 5376-dim, matching
        ``draft_block``'s ``h_prev`` feedback. ``mtp_cache`` is unused
        (stateless head).
        """
        del mtp_cache, logits_keep  # stateless head; output is 1 position
        drafter = self.mtp
        # Rebind if quantization replaced the backbone embedding.
        if drafter._input_embed is not self.model.embed_tokens:
            drafter.bind(self)
        shared_kv = getattr(self, "_omlx_mtp_shared_kv", None)
        if not shared_kv:
            raise RuntimeError(
                "gemma4 mtp_forward called without a prior "
                "return_hidden backbone forward (no shared K/V stash)"
            )

        h = hidden_states[:, -1:, :]
        # Compare strings because MLX dtype comparison with None raises TypeError.
        want_dtype = str(h.dtype)
        if getattr(drafter, "_omlx_head_dtype", None) != want_dtype:
            _align_drafter_dtype(drafter, h.dtype)
            drafter._omlx_head_dtype = want_dtype
        ids = next_token_ids[:, -1:]
        tok_embed = drafter._input_embed(ids) * drafter._input_embed_scale
        inputs_embeds = mx.concatenate([tok_embed.astype(h.dtype), h], axis=-1)

        if getattr(self, "_omlx_mtp_row_offsets", None) is not None:
            # Batched capture: the Lightning batch loop names the verify row
            # this draft belongs to (``_omlx_mtp_draft_row``).
            row = getattr(self, "_omlx_mtp_draft_row", None)
            if row is None or h.shape[0] != 1:
                raise RuntimeError(
                    "gemma4 mtp_forward: batched shared K/V needs one draft "
                    f"row (row={row}, hidden rows={h.shape[0]})"
                )
            shared_kv, valid_len = _row_shared_kv(self, row)
        else:
            # Committed length (post-rollback). The stash was captured at the
            # verify forward, so on a rejection it still carries the rejected
            # draft rows in the tail — slice them off (verify captures are
            # temporal-ordered, mirrors _mtp_rounds' post-reject slicing).
            valid_len = _mtp_query_position(self)
            rejected = getattr(self, "_omlx_mtp_kv_offset", valid_len) - valid_len
            if rejected > 0:
                shared_kv = _slice_shared_kv_after_reject(shared_kv, rejected)

        # The drafter's constant query position is the position of the
        # hidden's token — the last committed slot, not the next one
        # (mirrors _mtp_draft_position).
        drafter._kv_valid_len = valid_len
        head_hidden, logits = _draft_forward(
            drafter, inputs_embeds, shared_kv, max(valid_len - 1, 0), valid_len
        )
        if return_hidden:
            return logits, head_hidden
        return logits

    def make_mtp_cache(self):
        """The assistant head keeps no state — nothing to clone or trim."""
        return []

    cls.__init__ = __init__
    cls.__call__ = __call__
    cls.rollback_speculative_cache = rollback_speculative_cache
    cls.mtp_forward = mtp_forward
    cls.make_mtp_cache = make_mtp_cache
    # Shared verification: rows keep request-local acceptance and draft
    # context; the verify transaction commits ragged accepts per row.
    cls._omlx_mtp_multi_request = True
    cls._omlx_mtp_batch_rollback = True
    cls._omlx_mtp_runtime_patched = True
