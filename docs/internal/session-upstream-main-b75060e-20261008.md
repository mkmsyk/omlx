# oMLX 上流 main（未リリース）b75060e の統合 作業ログ（2026-10-08）

## 背景

上流に `v0.7.0` より新しい正式版タグが無いまま、`v0.7.0` 以降の 140 commit（Gemma 4 / Qwen の MTP・decode 高速化、メモリガード、アンロード待ちの検知、scheduler のエラー回復など）が `main` に入った。利用者の明示依頼で、Krisis の `omlx-update` に `prepare --ref <commit>` を足して取り込んだ。

## 変更

- release `0.7.0-d41a27b`（統合 commit `d41a27b2`）。`main` と `fork/main` は `d41a27b2`。版は `0.7.0` のままなので、新旧は release ID と installLink で区別する。
- 競合した 6 ファイルの解消方針:

| ファイル | 方針 |
|---|---|
| `omlx/engine_pool.py` | fork の `unload_idle_for_control` を残し、上流の `_unload_engine(..., local_only=False)` の署名を採った |
| `omlx/process_memory_enforcer.py` | 上流の `emergency_limit`（中止の閾値）で判定し、fork の `recovered`（回収要求件数と、モデルを残す旨のログ）を残した |
| `tests/test_scheduler.py` | fork の `StopSequences` と上流の `BatchKVCache` の両方を import |
| `tests/test_distributed_engine.py` | 上流の試験を採った |
| `tests/test_mlx_lm_mtp_patch.py` | fork の Gemma 行別 draft 試験と上流の context_copy 試験を併存 |
| `tests/test_server.py` | fork の管制プール返却試験と上流の Anthropic thinking・本文サイズ上限の試験を併存 |

## 検証

- 前回（v0.7.0 の統合）に自動統合で壊れた型の確認として、両側が変えた 26 の `.py` に `ruff --select F821,F822,F823,F811` を通した（指摘なし）。
- `pytest -m "not slow" -n 4`: 17785 passed, 219 skipped（6 分 40 秒）。
- `apply` completed（実行中の推論 0 件、中断なし）、`verify` は sidekick のチケット `r-793f7116-cea5-42b4-82bf-a2fbf9c1a335`（`qwen3.8-flash-next-oq4e-mtp`）。
- 未確認: 実機での MTP・decode の速度。

## 残 TODO

- 前回の記録の TODO（`sampling.py` の到達不能な分岐の整理）は未着手。
