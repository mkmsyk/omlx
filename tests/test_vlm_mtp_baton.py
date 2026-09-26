# SPDX-License-Identifier: Apache-2.0
"""Caller-assigned external MTP (the Krisis "MTP baton").

Covers the per-round emission of the vlm_mtp round loop, the claim/yield/off
routing gate, and the step-head hand-over of the drafter from a "yield"
holder to a waiting "claim" request.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import mlx.core as mx
import mlx_vlm.speculative.mtp as vlm_mtp_upstream
import pytest

import omlx.scheduler as scheduler_module
from omlx.request import Request, RequestStatus, SamplingParams
from omlx.scheduler import Scheduler, _VLMMTPDecodeState
from omlx.speculative import vlm_mtp

# ---------------------------------------------------------------------------
# Round loop: same token stream as mlx-vlm, emitted one list per round
# ---------------------------------------------------------------------------


class _FakeDraftModel:
    def __init__(self):
        self.config = SimpleNamespace(block_size=4)
        self.accept_lens: list[int] = []
        self.shared_kv_calls: list[tuple] = []
        self.draft_block = object()

    def reset(self, model):
        self.accept_lens = []

    def set_shared_kv(self, shared_kv, kv_offset, **kwargs):
        self.shared_kv_calls.append((kv_offset, kwargs.get("kv_valid_len")))


class _FakeSamplerRNG:
    def __init__(self, draft_model, enabled):
        self.draft_model = draft_model

    def draft_tokens(self, fn, b, hidden, _none, bs, sampler, token_dtype, **kwargs):
        return mx.array([[b + 1 + i for i in range(bs - 1)]], dtype=token_dtype)

    def draft_call(self, *args, **kwargs):
        return None

    def target_sampled(self, sync_draft):
        return None


class _FakeVerify:
    def __init__(self, bs):
        self.hidden = mx.zeros((1, bs, 4))
        self.shared_kv_states = {}
        self.committed = None

    def commit(self, lm, prompt_cache, accepted, bs):
        self.committed = (accepted, bs)

    def abort(self):
        pass


def _scripted_walk(accepts):
    state = {"round": 0, "next": 1000}

    def walk(lm, verify, draft_tokens, sampler, remaining, row_id, base_position):
        accepted = accepts[state["round"] % len(accepts)]
        state["round"] += 1
        drafts = [int(t) for t in draft_tokens[0].tolist()][:accepted]
        state["next"] += 1
        new_tokens = (drafts + [state["next"]])[:remaining]
        return accepted, new_tokens

    return walk


def _patched(module, accepts):
    record = lambda dm, accepted, n: dm.accept_lens.append(accepted)  # noqa: E731
    return [
        patch.object(module, "_SpeculativeSamplerRNG", _FakeSamplerRNG),
        patch.object(module, "_mtp_verify_target",
                     lambda lm, inp, cache, sampler, sample_target_tokens: _FakeVerify(inp.shape[1])),
        patch.object(module, "_mtp_acceptance_walk", _scripted_walk(accepts)),
        patch.object(module, "_record_speculative_round", record),
        patch.object(module, "_mtp_draft_hidden", lambda lm, h: h),
        patch.object(module, "_mtp_cache_offset_max", lambda cache: 10),
        patch.object(module, "_sampler_supports_positioned_target", lambda s: False),
    ]


def _run_upstream(accepts, max_tokens):
    draft = _FakeDraftModel()
    patches = _patched(vlm_mtp_upstream, accepts)
    for p in patches:
        p.start()
    try:
        tokens = [
            tok
            for tok, _ in vlm_mtp_upstream._mtp_rounds(
                SimpleNamespace(), draft, [], mx.zeros((1, 1, 4)), {},
                first_bonus=7, max_tokens=max_tokens, sampler=MagicMock(),
            )
        ]
    finally:
        for p in patches:
            p.stop()
    return tokens, draft


def _run_by_round(accepts, max_tokens):
    draft = _FakeDraftModel()
    patches = _patched(vlm_mtp, accepts)
    for p in patches:
        p.start()
    try:
        rounds = list(
            vlm_mtp._mtp_rounds_by_round(
                SimpleNamespace(), draft, [], mx.zeros((1, 1, 4)), {},
                first_bonus=7, max_tokens=max_tokens, sampler=MagicMock(),
            )
        )
    finally:
        for p in patches:
            p.stop()
    return rounds, draft


@pytest.mark.parametrize("max_tokens", [2, 5, 9, 17, 40])
@pytest.mark.parametrize("accepts", [[3, 0, 2, 1], [0], [3]])
def test_rounds_by_round_matches_mlx_vlm_token_stream(accepts, max_tokens):
    upstream, upstream_draft = _run_upstream(accepts, max_tokens)
    rounds, draft = _run_by_round(accepts, max_tokens)

    # The caller yields the first bonus, so the loops emit max_tokens - 1.
    assert len(upstream) == max_tokens - 1
    assert [tok for round_tokens in rounds for tok in round_tokens] == upstream
    assert all(round_tokens for round_tokens in rounds)
    # Same per-round acceptance bookkeeping and drafter re-binding.
    assert draft.accept_lens == upstream_draft.accept_lens
    assert draft.shared_kv_calls == upstream_draft.shared_kv_calls
    # One list per verify round.
    assert len(rounds) == len(draft.accept_lens)


def test_run_vlm_mtp_decode_per_round_yields_lists():
    drafter = vlm_mtp.VLMMTPDrafter(_FakeDraftModel(), "mtp", "/p")
    with (
        patch.object(vlm_mtp, "_mtp_rounds_by_round", return_value=iter([[11, 12], [13]])),
        patch.object(vlm_mtp, "_mtp_rounds") as m_single,
        patch.object(vlm_mtp, "_buffer_mtp_target_cache"),
    ):
        out = list(
            vlm_mtp.run_vlm_mtp_decode(
                target_language_model=MagicMock(),
                drafter=drafter,
                prompt_cache=[],
                hidden=mx.zeros((1, 1, 8)),
                shared_kv_states={},
                first_bonus=7,
                max_tokens=8,
                sampler=MagicMock(),
                per_round=True,
            )
        )
    assert out == [[7], [11, 12], [13]]
    m_single.assert_not_called()


def test_run_vlm_mtp_decode_per_round_rejects_batch():
    drafter = vlm_mtp.VLMMTPDrafter(_FakeDraftModel(), "mtp", "/p")
    with pytest.raises(ValueError):
        next(
            vlm_mtp.run_vlm_mtp_decode(
                target_language_model=MagicMock(),
                drafter=drafter,
                prompt_cache=[],
                hidden=mx.zeros((2, 1, 8)),
                shared_kv_states={},
                first_bonus=mx.array([1, 2]),
                max_tokens=8,
                sampler=MagicMock(),
                per_round=True,
            )
        )


# ---------------------------------------------------------------------------
# Scheduler: routing gate, per-round step, hand-over
# ---------------------------------------------------------------------------


class _FakeLanguageModel:
    def rollback_speculative_cache(self):
        pass

    def __call__(self, *args, **kwargs):
        return SimpleNamespace(
            logits=mx.array([[[0.0, 0.0, 5.0, 1.0]]]),
            hidden_states=mx.zeros((1, 1, 4)),
            shared_kv_states={},
        )


class _FakeVLMAdapter:
    def __init__(self):
        self._language_model = _FakeLanguageModel()

    def __call__(self, *args, **kwargs):
        return self._language_model(*args, **kwargs)


def _request(request_id, mtp_mode=None, **kwargs):
    request = Request(
        request_id=request_id,
        prompt=[1],
        sampling_params=SamplingParams(max_tokens=16),
        **kwargs,
    )
    request.prompt_token_ids = [1, 2, 3]
    request.num_prompt_tokens = 3
    request.mtp_mode = mtp_mode
    return request


def _route(scheduler, request):
    def fake_decode(**kwargs):
        def gen():
            yield [kwargs["first_bonus"]]

        return gen()

    with patch.object(scheduler_module, "run_vlm_mtp_decode", side_effect=fake_decode) as m:
        uid = scheduler._route_to_vlm_mtp(
            request,
            [SimpleNamespace(state=mx.array([0]))],
            [1],
            lambda logits: mx.argmax(logits, axis=-1),
            state_machine=object(),
        )
    return uid, m


@pytest.fixture
def mtp_scheduler(mock_model, mock_tokenizer):
    scheduler = Scheduler(model=mock_model, tokenizer=mock_tokenizer)
    scheduler._vlm_mtp_drafter = MagicMock()
    scheduler.model = _FakeVLMAdapter()
    return scheduler


def _add_peer(scheduler):
    peer = _request("req-peer")
    scheduler.running[peer.request_id] = peer
    return peer


def test_default_mode_keeps_contention_gate(mtp_scheduler):
    _add_peer(mtp_scheduler)
    uid, m = _route(mtp_scheduler, _request("req-default"))
    assert uid is None
    m.assert_not_called()


@pytest.mark.parametrize("mode", ["claim", "yield"])
def test_assigned_mode_takes_free_drafter_beside_peers(mtp_scheduler, mode):
    _add_peer(mtp_scheduler)
    uid, m = _route(mtp_scheduler, _request("req-assigned", mode))
    assert uid is not None
    assert m.call_args.kwargs["per_round"] is True
    state = mtp_scheduler._vlm_mtp_active[uid]
    assert state.mtp_mode == mode
    assert state.text_only is True


def test_off_mode_never_routes(mtp_scheduler):
    uid, m = _route(mtp_scheduler, _request("req-off", "off"))
    assert uid is None
    m.assert_not_called()


def test_busy_drafter_is_not_shared(mtp_scheduler):
    first, _ = _route(mtp_scheduler, _request("req-first", "yield"))
    assert first is not None
    uid, m = _route(mtp_scheduler, _request("req-second", "claim"))
    assert uid is None
    m.assert_not_called()


def _install_holder(scheduler, request, mode, *, text_only=True, rounds=None):
    class Gen:
        closed = False

        def __init__(self, items):
            self.items = iter(items)

        def __next__(self):
            return next(self.items)

        def close(self):
            self.closed = True

    generator = Gen(rounds or [])
    uid = -1
    request.status = RequestStatus.RUNNING
    scheduler.requests[request.request_id] = request
    scheduler.running[request.request_id] = request
    scheduler.request_id_to_uid[request.request_id] = uid
    scheduler.uid_to_request_id[uid] = request.request_id
    scheduler._vlm_mtp_active[uid] = _VLMMTPDecodeState(
        generator=generator,
        request=request,
        prompt_cache=[],
        sampler=MagicMock(),
        state_machine=MagicMock(),
        max_tokens=16,
        stop_token_ids={99},
        mtp_mode=mode,
        text_only=text_only,
    )
    return uid, generator


def test_step_emits_whole_round_and_drops_tokens_after_stop(mtp_scheduler):
    holder = _request("req-round", "claim")
    uid, _ = _install_holder(mtp_scheduler, holder, "claim", rounds=[[5, 6, 7], [8, 99, 9]])

    first = mtp_scheduler._step_vlm_mtp()
    assert [(r.uid, r.token, r.finish_reason) for r in first] == [
        (uid, 5, None), (uid, 6, None), (uid, 7, None),
    ]
    second = mtp_scheduler._step_vlm_mtp()
    assert [(r.token, r.finish_reason) for r in second] == [(8, None), (99, "stop")]
    assert uid not in mtp_scheduler._vlm_mtp_active


def test_yield_holder_hands_drafter_to_waiting_claimant(mtp_scheduler):
    holder = _request("req-translation", "yield")
    holder.output_token_ids = [40, 41]
    uid, generator = _install_holder(mtp_scheduler, holder, "yield")
    other = _request("req-other", "off")
    claimant = _request("req-article", "claim")
    mtp_scheduler.waiting.extend([other, claimant])

    assert mtp_scheduler._yield_vlm_mtp_to_claimant() is True

    assert uid not in mtp_scheduler._vlm_mtp_active
    assert generator.closed is True
    assert holder.request_id not in mtp_scheduler.running
    # Replayed first, without MTP, from prompt + emitted tokens.
    assert mtp_scheduler.waiting[0] is holder
    assert holder.mtp_mode == "off"
    assert holder.status == RequestStatus.WAITING
    assert holder.prompt_token_ids == [1, 2, 3, 40, 41]
    assert holder.memory_pressure_retries == 0
    # The claimant now finds the drafter free beside the replayed holder.
    claimant_uid, _ = _route(mtp_scheduler, claimant)
    assert claimant_uid is not None


def test_claim_holder_keeps_drafter(mtp_scheduler):
    holder = _request("req-article-1", "claim")
    uid, generator = _install_holder(mtp_scheduler, holder, "claim")
    mtp_scheduler.waiting.append(_request("req-article-2", "claim"))

    assert mtp_scheduler._yield_vlm_mtp_to_claimant() is False
    assert uid in mtp_scheduler._vlm_mtp_active
    assert generator.closed is False


def test_image_holder_keeps_drafter(mtp_scheduler):
    holder = _request("req-image", "yield", vlm_image_hash="abc")
    uid, _ = _install_holder(mtp_scheduler, holder, "yield", text_only=False)
    mtp_scheduler.waiting.append(_request("req-article", "claim"))

    assert mtp_scheduler._yield_vlm_mtp_to_claimant() is False
    assert uid in mtp_scheduler._vlm_mtp_active


def test_no_claimant_keeps_yield_holder(mtp_scheduler):
    holder = _request("req-translation", "yield")
    uid, _ = _install_holder(mtp_scheduler, holder, "yield")
    mtp_scheduler.waiting.append(_request("req-translation-2", "off"))

    assert mtp_scheduler._yield_vlm_mtp_to_claimant() is False
    assert uid in mtp_scheduler._vlm_mtp_active


def test_text_only_detection():
    assert scheduler_module._vlm_mtp_request_is_text_only(_request("t")) is True
    assert scheduler_module._vlm_mtp_request_is_text_only(
        _request("i", vlm_image_hash="h")
    ) is False


# ---------------------------------------------------------------------------
# Request plumbing
# ---------------------------------------------------------------------------


def test_vlm_engine_pops_mtp_mode():
    from omlx.engine.vlm import VLMBatchedEngine

    kwargs = {"mtp_mode": "claim", "stop": ["x"]}
    assert VLMBatchedEngine._pop_mtp_kwargs(kwargs) == {"mtp_mode": "claim"}
    assert kwargs == {"stop": ["x"]}
    assert VLMBatchedEngine._pop_mtp_kwargs({}) == {}


def test_chat_request_accepts_only_known_modes():
    from pydantic import ValidationError

    from omlx.api.openai_models import ChatCompletionRequest

    base = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    assert ChatCompletionRequest(**base, mtp_mode="yield").mtp_mode == "yield"
    assert ChatCompletionRequest(**base).mtp_mode is None
    with pytest.raises(ValidationError):
        ChatCompletionRequest(**base, mtp_mode="on")


def _post_chat_with_engine(engine, body):
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    import omlx.server as srv

    async def _get_engine_for_model(model_id, *, lease=None):
        return engine

    original_get_engine = srv.get_engine_for_model
    original_overrides = dict(srv.app.dependency_overrides)
    original_pool = srv._server_state.engine_pool
    fake_pool = MagicMock()
    fake_pool.get_entry = MagicMock(return_value=None)
    fake_pool.preload_pinned_models = AsyncMock()
    fake_pool.check_ttl_expirations = AsyncMock()
    fake_pool.shutdown = AsyncMock()
    try:
        srv.app.dependency_overrides[srv.verify_api_key] = lambda: True
        srv.get_engine_for_model = _get_engine_for_model
        srv._server_state.engine_pool = fake_pool
        with TestClient(srv.app, raise_server_exceptions=False) as client:
            with (
                patch.object(srv, "resolve_model_id", lambda name: name),
                patch.object(srv, "validate_context_window", lambda *a, **k: None),
            ):
                return client.post("/v1/chat/completions", json=body)
    finally:
        srv.get_engine_for_model = original_get_engine
        srv.app.dependency_overrides.clear()
        srv.app.dependency_overrides.update(original_overrides)
        srv._server_state.engine_pool = original_pool


def _chat_engine(drafter):
    from unittest.mock import AsyncMock

    from omlx.exceptions import PrefillMemoryExceededError

    engine = MagicMock()
    engine.vlm_mtp_drafter = drafter
    engine.start = AsyncMock()
    engine.count_chat_tokens = MagicMock(return_value=16)
    engine.preflight_chat = AsyncMock(
        side_effect=PrefillMemoryExceededError(message="stop here", request_id="r")
    )
    return engine


_CHAT_BODY = {
    "model": "test-model",
    "messages": [{"role": "user", "content": "hi"}],
    "stream": False,
}


def test_chat_refuses_mtp_mode_without_drafter():
    engine = _chat_engine(drafter=None)
    resp = _post_chat_with_engine(engine, {**_CHAT_BODY, "mtp_mode": "claim"})
    assert resp.status_code == 400, resp.text
    assert "external MTP drafter" in resp.text
    engine.preflight_chat.assert_not_called()


def test_chat_forwards_mtp_mode_to_engine():
    engine = _chat_engine(drafter=object())
    _post_chat_with_engine(engine, {**_CHAT_BODY, "mtp_mode": "yield"})
    assert engine.preflight_chat.call_args.kwargs["mtp_mode"] == "yield"


def test_chat_without_mtp_mode_forwards_nothing():
    engine = _chat_engine(drafter=object())
    _post_chat_with_engine(engine, _CHAT_BODY)
    assert "mtp_mode" not in engine.preflight_chat.call_args.kwargs
