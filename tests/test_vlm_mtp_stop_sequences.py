# SPDX-License-Identifier: Apache-2.0
"""vlm_mtp decode ends a request on the request's StopSequences, stop strings included.

Before: the vlm_mtp loop checked only an EOS + stop_token_ids set, so a request
routed to MTP ran past its stop strings. On Gemma 4, ``stop: ["<channel|>"]``
(one special token, 101) stopped at the end of the thought on BatchGenerator but
ran through the whole answer on MTP (Krisis/Sidekicks thought resume, 2026-10-03).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from mlx_lm.generate import StopSequences

from omlx.request import Request, RequestStatus, SamplingParams
from omlx.scheduler import Scheduler, _VLMMTPDecodeState

EOS = 2


def _install(scheduler: Scheduler, tokens: list[int], sequences: list[list[int]], *, max_tokens=16):
    request = Request("req-stop", "prompt", SamplingParams(max_tokens=max_tokens))
    request.status = RequestStatus.RUNNING
    uid = -1
    scheduler.requests[request.request_id] = request
    scheduler.running[request.request_id] = request
    scheduler.request_id_to_uid[request.request_id] = uid
    scheduler.uid_to_request_id[uid] = request.request_id
    scheduler._vlm_mtp_active[uid] = _VLMMTPDecodeState(
        generator=iter(tokens),
        request=request,
        prompt_cache=[],
        sampler=MagicMock(),
        state_machine=StopSequences(sequences),
        max_tokens=max_tokens,
    )
    return uid


def _drain(scheduler: Scheduler) -> list:
    responses = []
    for _ in range(32):
        step = scheduler._step_vlm_mtp()
        responses.extend(step)
        if not scheduler._vlm_mtp_active:
            break
    return responses


def test_single_token_stop_string_ends_the_request(mock_model, mock_tokenizer):
    scheduler = Scheduler(model=mock_model, tokenizer=mock_tokenizer)
    _install(scheduler, [5, 6, 101, 7, 8], [[EOS], [101]])
    responses = _drain(scheduler)
    assert [r.token for r in responses] == [5, 6, 101]
    assert [r.finish_reason for r in responses] == [None, None, "stop"]
    assert not scheduler._vlm_mtp_active


def test_multi_token_stop_sequence_ends_on_its_last_token(mock_model, mock_tokenizer):
    scheduler = Scheduler(model=mock_model, tokenizer=mock_tokenizer)
    _install(scheduler, [5, 6, 5, 6, 7, 8], [[EOS], [6, 7]])
    responses = _drain(scheduler)
    assert [r.token for r in responses] == [5, 6, 5, 6, 7]
    assert responses[-1].finish_reason == "stop"


def test_eos_still_ends_and_max_tokens_still_caps(mock_model, mock_tokenizer):
    scheduler = Scheduler(model=mock_model, tokenizer=mock_tokenizer)
    _install(scheduler, [5, EOS, 6], [[EOS]])
    assert [r.finish_reason for r in _drain(scheduler)] == [None, "stop"]

    scheduler = Scheduler(model=mock_model, tokenizer=mock_tokenizer)
    _install(scheduler, [5, 6, 7, 8], [[EOS]], max_tokens=3)
    assert [r.finish_reason for r in _drain(scheduler)] == [None, None, "length"]
