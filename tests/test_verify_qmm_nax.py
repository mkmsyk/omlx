# SPDX-License-Identifier: Apache-2.0
"""Tests for the multi-row 6-bit verify qmm on NAX (omlx.patches.verify_qmm_nax)."""

from __future__ import annotations

import mlx.core as mx
import mlx.nn as nn
import pytest

from omlx.patches import qwen35_verify_qmm, verify_qmm_nax

pytestmark = pytest.mark.skipif(
    not verify_qmm_nax.available(), reason="NAX verify qmm unavailable on this GPU"
)


def _quantized(n, k, group_size=64, seed=0):
    key = mx.random.key(seed)
    w = (mx.random.normal((n, k), key=key) * 0.02).astype(mx.bfloat16)
    return mx.quantize(w, group_size=group_size, bits=6)


def _close(got, ref):
    got = got.astype(mx.float32)
    ref = ref.astype(mx.float32)
    err = float(mx.abs(got - ref).max())
    return err <= 0.02 * float(mx.abs(ref).max()), err


@pytest.mark.parametrize("rows", [5, 8, 12, 16])
@pytest.mark.parametrize(
    "n,k",
    [
        (256, 1024),  # split 1
        (256, 8192),  # narrow N, K split 8
        (1024, 4096),  # K split 2
    ],
)
def test_matches_stock_qmm(rows, n, k):
    wq, s, b = _quantized(n, k)
    x = mx.random.normal((rows, k), key=mx.random.key(rows)).astype(mx.bfloat16)
    ref = mx.quantized_matmul(x, wq, s, b, transpose=True, group_size=64, bits=6)
    got = verify_qmm_nax.verify_qmm(x, wq, s, b, bits=6, group_size=64)
    assert got.shape == ref.shape and got.dtype == ref.dtype
    ok, err = _close(got, ref)
    assert ok, (rows, n, k, verify_qmm_nax.geometry(n, k, 64), err)


@pytest.mark.parametrize("rows", [17, 24, 32])
def test_deep_verify_rows_use_one_32_row_block(rows):
    # Narrow output + K split: the shape MLX's matrix path starves on.
    wq, s, b = _quantized(256, 8192)
    assert verify_qmm_nax.eligible(rows, 8192, 256, 6, 64, mx.bfloat16)
    x = mx.random.normal((rows, 8192), key=mx.random.key(rows)).astype(mx.bfloat16)
    ref = mx.quantized_matmul(x, wq, s, b, transpose=True, group_size=64, bits=6)
    got = verify_qmm_nax.verify_qmm(x, wq, s, b, bits=6, group_size=64)
    assert _close(got, ref)[0]
    assert verify_qmm_nax.row_block(rows) == 32


def test_group_size_32_uses_small_k_block():
    wq, s, b = _quantized(128, 2048, group_size=32)
    x = mx.random.normal((9, 2048)).astype(mx.bfloat16)
    ref = mx.quantized_matmul(x, wq, s, b, transpose=True, group_size=32, bits=6)
    got = verify_qmm_nax.verify_qmm(x, wq, s, b, bits=6, group_size=32)
    assert _close(got, ref)[0]


def test_eligibility_bounds():
    ok = verify_qmm_nax.eligible
    assert ok(5, 1024, 256, 6, 64, mx.bfloat16)
    assert ok(16, 1024, 256, 6, 64, mx.float16)
    assert not ok(4, 1024, 256, 6, 64, mx.bfloat16)  # stock is flat to M=4
    assert not ok(17, 1024, 256, 6, 64, mx.bfloat16)  # wide / no K split: stock NAX
    assert ok(24, 8192, 256, 6, 64, mx.bfloat16)  # narrow + K split keeps routing
    assert not ok(33, 8192, 256, 6, 64, mx.bfloat16)
    assert not ok(8, 1024, 256, 4, 64, mx.bfloat16)  # 4/8-bit keep their route
    assert not ok(8, 1000, 256, 6, 64, mx.bfloat16)
    assert not ok(8, 1024, 250, 6, 64, mx.bfloat16)
    assert not ok(8, 1024, 256, 6, 64, mx.float32)


def _quantized_linear(n, k):
    layer = nn.Linear(k, n, bias=False)
    layer.set_dtype(mx.bfloat16)
    return nn.QuantizedLinear.from_linear(layer, group_size=64, bits=6)


@pytest.mark.parametrize("shape", [(3, 4), (1, 8), (2, 5)])
def test_linear_routes_only_while_armed(shape, monkeypatch):
    assert qwen35_verify_qmm.apply_verify_qmm_patch()
    layer = _quantized_linear(256, 1024)
    x = mx.random.normal((*shape, 1024)).astype(mx.bfloat16)
    calls = []
    real = verify_qmm_nax.verify_qmm

    def spy(*args, **kwargs):
        calls.append(args[0].shape)
        return real(*args, **kwargs)

    monkeypatch.setattr(verify_qmm_nax, "verify_qmm", spy)
    stock = layer(x)
    assert not calls
    qwen35_verify_qmm.set_verify_qmm_armed(True)
    try:
        routed = layer(x)
    finally:
        qwen35_verify_qmm.set_verify_qmm_armed(False)
    assert calls == [(shape[0] * shape[1], 1024)]
    assert routed.shape == stock.shape
    assert _close(routed, stock)[0]


def test_small_verify_keeps_stock_path(monkeypatch):
    assert qwen35_verify_qmm.apply_verify_qmm_patch()
    layer = _quantized_linear(256, 1024)
    monkeypatch.setattr(
        verify_qmm_nax, "verify_qmm", lambda *a, **k: pytest.fail("rows <= 4 must stay stock")
    )
    qwen35_verify_qmm.set_verify_qmm_armed(True)
    try:
        layer(mx.random.normal((1, 4, 1024)).astype(mx.bfloat16))
    finally:
        qwen35_verify_qmm.set_verify_qmm_armed(False)


def test_tied_embedding_logits_route(monkeypatch):
    assert qwen35_verify_qmm.apply_verify_qmm_patch()
    emb = nn.Embedding(512, 1024)
    emb.set_dtype(mx.bfloat16)
    qemb = nn.QuantizedEmbedding.from_embedding(emb, group_size=64, bits=6)
    h = mx.random.normal((2, 4, 1024)).astype(mx.bfloat16)
    stock = qemb.as_linear(h)
    qwen35_verify_qmm.set_verify_qmm_armed(True)
    try:
        routed = qemb.as_linear(h)
    finally:
        qwen35_verify_qmm.set_verify_qmm_armed(False)
    assert routed.shape == stock.shape == (2, 4, 512)
    assert _close(routed, stock)[0]
