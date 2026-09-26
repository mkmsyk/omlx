# SPDX-License-Identifier: Apache-2.0
"""In-place ragged commit of Gemma 4 shared-verify rotating caches.

``_commit_rotating_in_place`` must leave every BatchRotatingKVCache exactly
as mlx-vlm's transaction commit (restore + replay + finalize) would.
"""

from __future__ import annotations

import copy

import mlx.core as mx
import pytest

vlm_cache = pytest.importorskip("mlx_vlm.models.cache")
cache_state = pytest.importorskip("mlx_vlm.speculative.cache_state")

from omlx.patches.mlx_lm_mtp import cache_rollback  # noqa: E402
from omlx.patches.mlx_vlm_mtp import gemma4_vlm_runtime  # noqa: E402

WINDOW = 8
H, D = 2, 4


def _batch_cache(lengths, seed):
    singles = []
    for i, n in enumerate(lengths):
        c = vlm_cache.RotatingKVCache(max_size=WINDOW)
        key = mx.random.key(seed * 10 + i)
        kv = mx.random.normal((1, H, n, D), key=key)
        c.update_and_fetch(kv, kv * 2)
        singles.append(c)
    return vlm_cache.BatchRotatingKVCache.merge(singles)


def _verify(cache, length, seed, armed):
    block = mx.random.normal((cache.offset.shape[0], H, length, D), key=mx.random.key(seed))
    transaction = cache_state.start_speculative_cache([cache], length)
    cache_rollback.set_undo_armed(armed)
    try:
        cache.update_and_fetch(block, block + 1)
    finally:
        cache_rollback.set_undo_armed(False)
    return transaction


def _state(cache):
    mx.eval(cache.keys, cache.values, cache.offset, cache.left_padding)
    return (
        cache._idx,
        cache._offset,
        cache.rotated,
        cache.offset.tolist(),
        cache.left_padding.tolist(),
        cache.keys[..., : cache._idx, :],
        cache.values[..., : cache._idx, :],
    )


def _assert_same(a, b):
    sa, sb = _state(a), _state(b)
    assert sa[:5] == sb[:5]
    assert mx.array_equal(sa[5], sb[5]).item()
    assert mx.array_equal(sa[6], sb[6]).item()


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize(
    "lengths,accepted",
    [
        ([3, 5, 2], [2, 0, 1]),  # all rows shorter than the window
        ([12, 5, 20], [0, 3, 1]),  # mixed: two rows already wrapped
        ([12, 15, 20], [3, 3, 3]),  # uniform full accept
        ([12, 15, 20], [1, 1, 1]),  # uniform partial accept (no roll)
        ([9, 4], [3, 0]),
    ],
)
def test_matches_stock_transaction_commit(lengths, accepted, armed):
    cache_rollback.apply()
    length = 4
    stock = _batch_cache(lengths, seed=1)
    fast = copy.deepcopy(stock)
    t_stock = _verify(stock, length, seed=2, armed=armed)
    t_fast = _verify(fast, length, seed=2, armed=armed)

    cache_state.rollback_speculative_cache([stock], t_stock, accepted, length)
    gemma4_vlm_runtime._commit_rotating_in_place(t_fast, [a + 1 for a in accepted])
    fast_path = all(
        isinstance(entry, gemma4_vlm_runtime._CommittedRotating)
        for entry in t_fast._rotating.values()
    )
    full_accept = all(a + 1 == length for a in accepted)
    assert fast_path != full_accept, "ragged or partial accepts must take the in-place commit"
    cache_state.rollback_speculative_cache([fast], t_fast, accepted, length)
    assert "update_and_fetch" not in fast.__dict__
    _assert_same(stock, fast)

    # The next verify and a decode step read the same windows.
    for step, n in enumerate((3, 1)):
        nxt = mx.random.normal((len(lengths), H, n, D), key=mx.random.key(40 + step))
        ks, vs = stock.update_and_fetch(nxt, nxt)
        kf, vf = fast.update_and_fetch(nxt, nxt)
        assert mx.array_equal(ks, kf).item() and mx.array_equal(vs, vf).item()
        _assert_same(stock, fast)


def test_single_token_verify_keeps_stock_commit():
    # A depth-0 cycle updates in place; the helper must leave it alone.
    stock = _batch_cache([12, 5], seed=3)
    t = _verify(stock, 1, seed=4, armed=False)
    before = dict(t._rotating)
    gemma4_vlm_runtime._commit_rotating_in_place(t, [1, 1])
    assert dict(t._rotating) == before
