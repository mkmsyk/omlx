# SPDX-License-Identifier: Apache-2.0
"""NAX quantized matmul for multi-row speculative verify (M = 5..32).

A Lightning MTP verify multiplies ``rows x (depth + 1)`` activations against
the model's quantized weights. MLX 0.32.2 serves up to four rows with one
vector pass and then adds a pass per four rows; the tiled matrix kernel only
takes over at larger M and has no K split, so narrow outputs starve. On M5
Max, 6-bit Gemma 4 31B projections measured (M=1 / 8 / 12 rows):
MLP down 21504->5376 0.18 / 0.32 / 0.47 ms, lm_head 5376->262144
2.1 / 9.4 / 12.8 ms. Batched verification lost the win it exists for.

This module instantiates MLX's own NAX tile path (``QuantizedBlockLoader``
dequantizing into threadgroup memory + ``tile_matmad_nax`` on the M5 neural
accelerators, the code behind ``affine_qmm_t_nax``) through
``mx.fast.metal_kernel`` with a 16- or 32-row block, the simdgroups spread along N,
and an explicit K split (grid z) whose fp32 partials are summed afterwards.
Measured on the same shapes at 12 rows: MLP down ~0.49 ms, lm_head ~4.6 ms,
roughly flat from 8 to 16 rows.

Constraints found while porting (both silently compute garbage otherwise,
so they are static_asserts in the kernel):

- ``tile_matmad_nax`` has no branch for a 16x16 per-simdgroup tile
  (TM == TN == 1): each simdgroup owns 16 rows x 32*k columns.
- ``QuantizedBlockLoader`` keeps one thread's reads inside one weight row,
  so the threadgroup needs at least ``BN`` threads.

The MLX headers ship with the wheel (``mlx/include``); they are inlined into
the kernel header so the JIT compile needs no include path.
"""

from __future__ import annotations

import logging
import re
import threading
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_ROWS = 5
MAX_ROWS = 32

_KERNEL_CACHE: dict = {}
_AVAILABLE: bool | None = None
_AVAILABLE_LOCK = threading.Lock()

_INCLUDE = re.compile(r'^\s*#include\s+"(mlx/[^"]+)"\s*$', re.MULTILINE)

_IMPL = r"""
template <typename T, typename O, int group_size, int bits, int BM, int BK, int BN, int WN>
METAL_FUNC void omlx_vqmm_nax_impl(
    const device uint32_t* w,
    const device T* scales,
    const device T* biases,
    const device T* x,
    device O* y,
    threadgroup T* Ws,
    const constant int& K,
    const constant int& N,
    const constant int& M,
    const constant int& K_eff,
    uint3 tid,
    uint simd_gid,
    uint simd_lid) {
  constexpr int WM = 1;
  constexpr int pack_factor = get_pack_factor<bits, 8>();
  constexpr int bytes_per_pack = get_bytes_per_pack<bits>();
  constexpr int BK_padded = (BK + 16 / sizeof(T));

  using loader_w_t = QuantizedBlockLoader<
      T, BN, BK, BK_padded, 1, WM * WN * SIMD_SIZE, group_size, bits>;

  constexpr short SM = BM / WM;
  constexpr short SN = BN / WN;
  constexpr short SK = 32;
  constexpr short TM = SM / 16;
  constexpr short TN = SN / 16;
  constexpr short TK = SK / 16;
  static_assert(TN % 2 == 0 || TM % 2 == 0, "NAX tile needs an even TN or TM");
  static_assert(WM * WN * SIMD_SIZE >= BN, "need at least one thread per weight row");

  const int K_w = K * bytes_per_pack / pack_factor;
  const int K_g = K / group_size;
  const int y_row = tid.y * BM;
  const int y_col = tid.x * BN;

  auto wl = (const device uint8_t*)w;
  x += y_row * static_cast<int64_t>(K);
  wl += y_col * K_w;
  scales += y_col * K_g;
  biases += y_col * K_g;
  y += y_row * static_cast<int64_t>(N) + y_col;

  loader_w_t loader_w(wl, scales, biases, K, Ws, simd_gid, simd_lid);

  const short tn = SN * simd_gid;
  const short sgp_sm = min(int(SM), M - y_row);

  NAXTile<float, TM, TN> Dtile;
  Dtile.clear();

  for (int k = 0; k < K_eff; k += BK) {
    threadgroup_barrier(mem_flags::mem_threadgroup);
    loader_w.load_unsafe();
    threadgroup_barrier(mem_flags::mem_threadgroup);
    STEEL_PRAGMA_NO_UNROLL
    for (int kk1 = 0; kk1 < BK; kk1 += SK) {
      NAXTile<T, TM, TK> Atile;
      NAXTile<T, TN, TK> Btile;
      volatile int compiler_barrier;
      Atile.load_safe(x + kk1, K, short2(SK, sgp_sm));
      Btile.template load<T, BK_padded, 1>(Ws + tn * BK_padded + kk1);
      tile_matmad_nax(
          Dtile, Atile, metal::bool_constant<false>{}, Btile,
          metal::bool_constant<true>{});
      (void)compiler_barrier;
    }
    x += BK;
    loader_w.next();
  }
  threadgroup_barrier(mem_flags::mem_threadgroup);
  Dtile.store_safe(y + tn, N, short2(SN, sgp_sm));
}
"""


@lru_cache(maxsize=1)
def _header() -> str:
    """MLX's NAX quantized tile sources with their includes inlined."""
    import mlx.core as mx

    # ``mlx`` is a namespace package; the compiled core sits in the wheel root.
    root = Path(mx.__file__).parent / "include"
    seen: set[str] = set()

    def expand(rel: str) -> str:
        if rel in seen:
            return ""
        seen.add(rel)
        text = (root / rel).read_text().replace("#pragma once", "")
        return _INCLUDE.sub(lambda m: expand(m.group(1)), text)

    # mx.fast.metal_kernel already includes utils.h and its dependencies;
    # expand it once only to mark those files as seen.
    expand("mlx/backend/metal/kernels/utils.h")
    return "\n".join(
        [
            expand("mlx/backend/metal/kernels/steel/gemm/gemm_nax.h"),
            expand("mlx/backend/metal/kernels/quantized_nax.h"),
            _IMPL,
        ]
    )


def row_block(m: int) -> int:
    """Smallest 16/32-row block holding every verify row in one tile.

    A second row block re-reads every weight tile, which doubled the cost at
    17 rows with a fixed 16-row block.
    """
    return 16 if m <= 16 else 32


def _build_kernel(bits: int, group_size: int, dtype, out_dtype, bm: int, bn: int, bk: int, wn: int):
    import mlx.core as mx

    key = (bits, group_size, dtype, out_dtype, bm, bn, bk, wn)
    kernel = _KERNEL_CACHE.get(key)
    if kernel is not None:
        return kernel
    source = f"""
        constexpr int BN_ = {bn};
        constexpr int BK_ = {bk};
        constexpr int BK_padded = (BK_ + 16 / sizeof(T));
        constexpr int pack_factor = get_pack_factor<{bits}, 8>();
        constexpr int bytes_per_pack = get_bytes_per_pack<{bits}>();
        threadgroup T Ws[BN_ * BK_padded];

        const int N = int(N_size);
        const int M = int(M_size);
        const int part = int(threadgroup_position_in_grid.z);
        const int k_start = part * int(k_part_size);

        auto wl = (const device uint8_t*)w_q;
        wl += k_start * bytes_per_pack / pack_factor;
        omlx_vqmm_nax_impl<T, O, {group_size}, {bits}, {bm}, BK_, BN_, {wn}>(
            (const device uint32_t*)wl,
            scales + k_start / {group_size},
            biases + k_start / {group_size},
            x + k_start,
            y + int64_t(part) * M * N,
            Ws, K_size, N_size, M_size, k_part_size,
            threadgroup_position_in_grid,
            simdgroup_index_in_threadgroup,
            thread_index_in_simdgroup);
    """
    tags = {mx.bfloat16: "bf16", mx.float16: "fp16", mx.float32: "f32"}
    kernel = mx.fast.metal_kernel(
        name=(
            f"omlx_vqmm_nax_q{bits}_gs{group_size}_m{bm}n{bn}k{bk}w{wn}_"
            f"{tags.get(dtype, 'unk')}_{tags.get(out_dtype, 'unk')}"
        ),
        input_names=["x", "w_q", "scales", "biases", "K_size", "N_size", "M_size", "k_part_size"],
        output_names=["y"],
        source=source,
        header=_header(),
    )
    _KERNEL_CACHE[key] = kernel
    return kernel


def geometry(n: int, k: int, group_size: int) -> tuple[int, int, int, int]:
    """(BN, BK, WN, SPLIT) tuned on M5 Max for 6-bit Gemma 4 shapes."""
    bn, wn = 64, 2
    bk = 64 if group_size >= 64 else 32
    tiles = n // bn
    split = 1
    # Fill the GPU on narrow N (MLP down, attention o): 5376 / 64 = 84 tiles.
    while tiles * split < 512 and k // (split * 2) >= 1024 and split < 8:
        split *= 2
    while split > 1 and (k % (split * group_size) or (k // split) % bk):
        split //= 2
    return bn, bk, wn, split


def eligible(rows: int, k: int, n: int, bits: int, group_size: int, dtype) -> bool:
    import mlx.core as mx

    if not (
        int(bits) == 6
        and int(group_size) in (32, 64, 128)
        and dtype in (mx.bfloat16, mx.float16)
        and MIN_ROWS <= int(rows) <= MAX_ROWS
        and int(k) % 64 == 0
        and int(n) % 64 == 0
    ):
        return False
    # Past 16 rows MLX's own NAX matrix path serves wide outputs as well as
    # this kernel; it still lacks a K split, so narrow outputs keep routing.
    return int(rows) <= 16 or geometry(int(n), int(k), int(group_size))[3] > 1


def _run(x2, w_q, scales, biases, *, bits: int, group_size: int):
    import mlx.core as mx

    m, k = int(x2.shape[0]), int(x2.shape[1])
    n = int(w_q.shape[0])
    bn, bk, wn, split = geometry(n, k, group_size)
    bm = row_block(m)
    out_dtype = x2.dtype if split == 1 else mx.float32
    kernel = _build_kernel(bits, group_size, x2.dtype, out_dtype, bm, bn, bk, wn)
    (y,) = kernel(
        inputs=[mx.contiguous(x2), w_q, scales, biases, k, n, m, k // split],
        template=[("T", x2.dtype), ("O", out_dtype)],
        grid=(32 * wn * (n // bn), (m + bm - 1) // bm, split),
        threadgroup=(32 * wn, 1, 1),
        output_shapes=[(split, m, n)],
        output_dtypes=[out_dtype],
    )
    return y[0] if split == 1 else y.sum(axis=0).astype(x2.dtype)


def available() -> bool:
    """Whether the NAX kernel compiles here and matches stock qmm (checked once)."""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    with _AVAILABLE_LOCK:
        if _AVAILABLE is not None:
            return _AVAILABLE
        try:
            import mlx.core as mx

            key = mx.random.key(0)
            w = (mx.random.normal((128, 2048), key=key) * 0.02).astype(mx.bfloat16)
            wq, s, b = mx.quantize(w, group_size=64, bits=6)
            x = mx.random.normal((8, 2048), key=key).astype(mx.bfloat16)
            ref = mx.quantized_matmul(x, wq, s, b, transpose=True, group_size=64, bits=6)
            got = _run(x, wq, s, b, bits=6, group_size=64)
            err = mx.abs(got.astype(mx.float32) - ref.astype(mx.float32)).max()
            scale = mx.abs(ref.astype(mx.float32)).max()
            _AVAILABLE = bool((err <= 0.02 * scale).item())
            if not _AVAILABLE:
                logger.warning("verify qmm NAX kernel disagrees with stock qmm; disabled")
        except Exception as exc:  # noqa: BLE001 - no NAX / JIT failure
            logger.info("verify qmm NAX kernel unavailable: %s", exc)
            _AVAILABLE = False
        return _AVAILABLE


def verify_qmm(x2, w_q, scales, biases, *, bits: int, group_size: int):
    """(M, K) x (N, K)^T -> (M, N) for 6-bit affine weights, M in 5..32."""
    return _run(x2, w_q, scales, biases, bits=bits, group_size=group_size)
