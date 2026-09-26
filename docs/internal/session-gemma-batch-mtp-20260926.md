# Gemma 4 Lightning MTP の複数要求対応（2026-09-26）

計画はルートの `implementation_plan.md`（完了時に `docs/omlx/` へ移す）。

## 背景

本番の Gemma 4（26B-A4B / 31B）は外付け `vlm_mtp` で、drafter が要求状態を 1 件分しか持てず、同じモデルに他の要求があると MTP を始めない。9/24 の実測では同時 2 以上の完了の 1〜9% しか MTP に乗っていなかった。統合チェックポイントで動く Gemma 4 Lightning MTP を、Qwen などと同じ共有検証の複数要求経路に乗せる。

## 変更

- 上流 cherry-pick：`9acba360`（#3561：統合 head の text-only 経路、head の dtype 揃え、早期 bind 廃止）、`b6c7721e`（text-only Gemma 4 の画像入力拒否）。`omlx/engine/vlm.py` の競合は mimo_v2 の動画展開を除き拒否部分だけ取り込んだ。
- `omlx/patches/mlx_vlm_mtp/gemma4_vlm_runtime.py`
  - 複数行の return_hidden forward は `start_speculative_cache` の transaction 内で実行し、gdn 位置で返す。`rollback_speculative_cache` は transaction を受けたら委譲する（行ごとに違う採択数を処理でき、回転 cache は採択分を再投入する）。単発は従来の trim＋undo のまま。
  - 共有 K/V の退避は全行分を保持し、検証時の行別位置を記録する。`mtp_forward` は `_omlx_mtp_draft_row` で示された行について、「検証時の位置 − 巻き戻し後の位置」から棄却分を求め、その行の確定区間だけを切り出す（単発の退避と同じ詰めた形）。
  - `_omlx_mtp_multi_request` と `_omlx_mtp_batch_rollback` を宣言。
- `omlx/patches/mlx_lm_mtp/fused_batch.py`：共有検証後、行ごとの下書きの直前に行番号を model へ設定する `_set_draft_row` を追加（群の処理後に解除）。
- 既存の潜在不具合 2 件の修正（複数要求化で表に出た）
  - `omlx/patches/mlx_lm_mtp/cache_rollback.py`：回転 cache の取り消しログを mlx-vlm の `RotatingKVCache` / `BatchRotatingKVCache` にも付ける。Gemma 4 VLM 経路は mlx-vlm のクラスを使うため、その場書き込みの verify を棄却すると枠の古い K が壊れていた。
  - `omlx/patches/gemma4_verify_attention.py`：mask を無視する近似経路を B=1 に限定し、左パディング 0 の判定メモを `left_padding` 配列ごとに取り直す。以前はメモを cache オブジェクトに一度だけ書いたため、途中参加で作り直した行 cache がこの経路に入ったり、後から左パディングが付いた cache を mask なしで読む余地があった。

## 判断

- 外付け drafter を要求ごとに複製する案は採らない。各要求が別々に target forward を回すため、通常のバッチ decode より遅くなりうる。
- 下書きは当面、行ごとに head を呼ぶ。head は状態を持たないため既存の `batched_head` は使えない。行まとめの下書きは実測で必要と分かってから追加する（計画 2.3）。
- verify 用の近似 attention は複数行 verify に使わない（mask を無視するため）。速度が足りなければ左パディング対応を別計画にする（計画 2.4）。

## 検証

- 同等性試験 `test_multi_request_mtp_or_singleton_only_matches_standard`：gemma を複数対応側へ移し、深さ不揃いを追加。全ファミリー 64 件成功。共有検証・行別巻き戻しの経路を通ることも確認する。
- 新規試験
  - `test_gemma_batched_draft_rows_match_singleton_drafts`：行別採択 [2,0]/[0,2]/[1,1] の共有検証後、各行の下書き logits が単独検証と一致する。
  - `test_vlm_rotating_caches_undo`：mlx-vlm 回転 cache の取り消しログ。
  - `test_multi_row_verify_stays_on_stock_path`、`test_padding_verdict_follows_rebound_padding`：近似経路の判定。
  - これらの新規試験は修正前のコードで失敗し、修正後に成功することを確認した。
- 関連 8 ファイル 619 件成功。全体の高速試験は下記に追記する。

## 観測（未対応）

- 近似経路の「1 トークンずつ」書き込みで sliding 層を検証すると、退避される K/V は回転枠の物理順になり、時間順を前提とする drafter には合わない。実機の Gemma 4（sliding head_dim 256、L≤8）はこの経路に入らず、mlx 標準の fused 経路を使うため影響しない。小型試験モデル（head_dim 8）でだけ起きる。

## 残作業

- 配備（`prepare --current` → `apply` → `verify` → `finalize`）。
- 段階 1：統合モデル（`~/.omlx/models/gemma-4-26B-A4B-it-qat-6bit-mtp`、`gemma-4-31b-it-6bit-mtp`）の単発速度を `vlm_mtp` と比べる。
- 段階 3〜4：複数要求での実機確認、本番切替、同時数の再調整。
