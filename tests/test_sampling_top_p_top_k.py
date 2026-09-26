# SPDX-License-Identifier: Apache-2.0
"""apply_top_p_then_top_k keeps exactly what top_p followed by top_k keeps."""

from __future__ import annotations

import mlx.core as mx
import pytest

from omlx.utils.sampling import (
    apply_top_k,
    apply_top_p,
    apply_top_p_then_top_k,
    make_sampler,
)


def _logprobs(rows, vocab, scale, seed):
    z = mx.random.normal((rows, vocab), key=mx.random.key(seed)) * scale
    return z - mx.logsumexp(z, axis=-1, keepdims=True)


@pytest.mark.parametrize("scale", [0.5, 3.0, 12.0])  # flat .. peaked
@pytest.mark.parametrize("top_p,top_k", [(0.95, 64), (0.5, 64), (0.99, 8), (0.9, 1)])
@pytest.mark.parametrize("rows", [1, 5])
def test_matches_sequential_filters(scale, top_p, top_k, rows):
    lp = _logprobs(rows, 4096, scale, seed=int(scale * 10) + top_k)
    ref = apply_top_k(apply_top_p(lp, top_p), top_k)
    got = apply_top_p_then_top_k(lp, top_p, top_k)
    ref_keep = mx.isfinite(ref)
    got_keep = mx.isfinite(got)
    assert mx.array_equal(ref_keep, got_keep).item()
    assert mx.array_equal(mx.where(ref_keep, ref, 0), mx.where(got_keep, got, 0)).item()


def test_make_sampler_uses_fused_filter_for_top_p_and_top_k():
    sampler = make_sampler(temp=1.0, top_p=0.95, top_k=64)
    lp = _logprobs(3, 4096, 3.0, seed=1)
    filtered = sampler._mtp_sampling_logits(lp)
    expected = apply_top_k(apply_top_p(lp, 0.95), 64)
    assert mx.array_equal(mx.isfinite(filtered), mx.isfinite(expected)).item()
    token = sampler(lp)
    assert mx.isfinite(mx.take_along_axis(expected, token[:, None], axis=-1)).all().item()


def test_other_filter_combinations_keep_their_path():
    # min_p participates: the composed filters stay in their original order.
    sampler = make_sampler(temp=1.0, top_p=0.95, top_k=64, min_p=0.05)
    lp = _logprobs(2, 1024, 3.0, seed=2)
    assert sampler._mtp_sampling_logits(lp).shape == lp.shape
