# oMLX 上流 v0.7.0 統合 作業ログ（2026-10-02）

## 背景

稼働版 `0.7.0.dev4` に対し、上流に正式版 `v0.7.0` が出た。Krisis の `omlx-update` 手順（check → prepare → apply → verify → finalize）で統合・配備した。

## 変更

- release `0.7.0-78ac54b`（worktree `~/Repositories/omlx-releases/v0.7.0-3e08cd0`）。統合 commit `c140f02f`、整合修正 `78ac54bf`。`main` と `fork/main` は `78ac54bf`。
- 競合した 9 ファイルの解消方針:

| ファイル | 方針 |
|---|---|
| `README.md` | fork の管理画面認証（Bunrin Passport）の説明を残し、上流の SSD キャッシュ `auto` 上限とキーなし推論の段落を足した |
| `omlx/process_memory_enforcer.py` | 上流の汎用化された猶予ブロック（`new_level != "ok"`）を採った |
| `omlx/engine/vlm.py` | 上流（mimo 動画展開）を採った |
| `omlx/patches/mlx_lm_mtp/batch_generator.py` | top-p→top-k は fork の `apply_top_p_then_top_k`（`make_sampler` と同じ関数で、draft と acceptance の候補集合を揃える）。`finish()` は上流の再構成を採り、fork の `defer_boundary` 条件を戻した |
| `omlx/patches/mlx_lm_mtp/fused_batch.py` | fork の Gemma 4 行一括 draft（`use_rows_draft`）に、上流のブロックドラフター（`drafter`）の分岐を併置した |
| `omlx/patches/qwen35_verify_qmm.py` | 上流の row-exact 経路を先頭に置き、fork の NAX 経路を後ろに置いた。上流の 3 つの verify パッチと fork の `QuantizedEmbedding.as_linear` パッチを併用した |
| `omlx/patches/mlx_vlm_mtp/gemma4_vlm_runtime.py` | fork 独自の追加（回転キャッシュのその場 commit、行一括 draft）を残した |
| `tests/test_gemma4_vlm_mtp_runtime.py`, `tests/test_scheduler_prefill_memory_guard.py` | fork 側の署名を維持し、独立した試験は両方残した |

## 設計判断

競合マーカーが出なかった箇所に意味の衝突が 2 つあり、試験で見つかった（`prepare` の初回は 243 件失敗）。

- `omlx/api/thinking.py`: fork の literal think tag guard が `extract_thinking` を `_extract_thinking_impl` に分け、上流が `truncated` 引数を足した。結合後は `truncated` が実装側へ渡らず `NameError` になった（221 件）。引数を渡すようにした。
- `omlx/process_memory_enforcer.py`: 上流側の梯子は `new_level == "hard"` だけが縮小段に入る。fork の「soft でも縮小してからアンロード」を `new_level in ("soft", "hard")` で戻した。

## 検証

- `pytest -m "not slow"` 全件合格（再実行後）。
- `apply` 完了、`verify` は sidekick の推論チケット `r-0c902068-b8ad-4dfb-87dc-aa3e0bfe6607`（`gemma-4-26b-a4b-it-qat-6bit`）で確認した。
- 未確認: 実機での MTP（Gemma 4 / Qwen）の速度。上流の verify パッチと fork の NAX 経路の併用は、試験では動作の正しさだけを見ている。

## 残 TODO

- `sampling.py` の `make_sampler` に、fork の高速経路の後ろへ上流の同条件分岐が到達不能なまま残っている。次回の統合で整理する。
