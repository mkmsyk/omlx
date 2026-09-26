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

## 実機計測（2026-09-26、GPU 専有：本番 26B/31B を drain＋hold）

同一依頼（翻訳 2.3k 字、要約 6k 字）を Sidekicks 経由で同時数 1/2/3 × 2 回。統合版は Lightning MTP、sampling は本番同値（temp 1.0 / top_p 0.95 / top_k 64）。

| モデル | 依頼 | 同時1 | 同時2（1要求） | 同時3（1要求） | 合計 tok/s（1/2/3） |
|---|---|---:|---:|---:|---:|
| 26B-A4B | 翻訳 | 47 | 24〜26 | 18 | 47 / 約49 / 約54 |
| 31B | 翻訳 | 12 | 6〜7 | 5〜6 | 12 / 約12 / 15〜17 |

- 複数要求 MTP は起動し（`batch activated for N sequences`）、行ごとの採択率は単発と同水準（26B 翻訳 84〜86%、31B 翻訳 75〜78%）。同じ依頼の終了時刻差は 0.4〜3 秒で揃う。
- ただし合計はほとんど伸びず、MTP 側の制御が「通常のバッチ decode の方が速い」と判断して何度も `batch-parked` になる。
- 1 周の検証時間は行数にほぼ比例する（26B：1 行 63ms、2 行 136ms、3 行 164〜188ms。31B：1 行 245ms、2 行 443ms）。ログの `backbone` は行数で割った値なので注意。

### 原因の切り分け

- 初版は行ごと・下書きの段ごとにホスト同期があり、行の処理が直列化していた（`9902e95` で解消）。
- 26B 相当の 4 層切り出し（MoE・語彙 26 万・6bit）での 1 行あたり追加費用：下書き約 8.6ms、採択判定（全語彙 top-p ソート）約 3ms、巻き戻し約 0.7ms。
- 検証 forward 単体は複数行で得をする（26B 6 層・文脈 4k：1 行 19.6ms、2 行 28.5ms、3 行 36.8ms）。ただし 26B の通常 decode も同程度にバッチで伸びる（1 行 12.5ms → 3 行 16.2ms）ので、MoE では MTP を束ねる利得と通常バッチの利得が食い合う。
- 31B 6 層切り出しでは 3 行 × 4 トークン（M=12）で急に遅くなる（2 行 38ms → 3 行 72ms）。
- 主因は MLX の 6bit 量子化行列積で、M が数行〜十数行の範囲で M にほぼ比例して重くなる（31B MLP down 21504→5376：M=1 433μs、M=4 579μs、M=8 886μs、M=12 1,401μs、M=16 2,162μs）。重みを 1 回読めば済むはずの形になっていない。MLX 0.32.2 が最新で、上流にも改善は入っていない。
- Qwen には検証専用の量子化行列積 kernel（`qwen35_verify_qmm`、MTPLX 由来）があるが、4bit/8bit・M=3〜6 限定で、Gemma の 6bit と複数行の M=8〜16 に対応しない。

## 検証用 kernel と周回の改善（2026-09-26 夜）

| commit | 内容 | 効果（計測） |
|---|---|---|
| `f9eea41` | `verify_qmm_nax`：MLX の NAX tile 経路（`QuantizedBlockLoader`＋`tile_matmad_nax`）を `mx.fast.metal_kernel` で行ブロック 16・K 分割つきに実体化し、検証中の 6bit `QuantizedLinear` と tied 埋め込みの logits を振り分け | 31B 6 層切り出しの 3 行×4 トークン検証 31.0→18.4ms。31B 実機の同時 2 件合計 約 12→20 tok/s |
| `0fb49d4` | 行別に違う採択の確定を、回転 cache では「末尾カット＋不足行の右ずらし」だけで行う（mlx-vlm の restore＋replay＋finalize を省く） | 切り出しの巻き戻し 8.7→2.7ms／周（31B 換算 約 60ms 短縮） |
| `21deca7` | 状態を持たない head（Gemma 補助）の下書きを全行 1 回の呼び出しで行う | 1 段 3 行で 7.5→3.5ms |
| `efbcb2b` | 全行下書きの時点で退避内容が別の forward に置き換わっていたら、その周回の下書きを空にして警告（呼び出し経路つき） | 実機で 3 要求が例外で落ちた事象への防御 |
| `8e495b2` | NAX 振り分けを 32 行まで（17 行以上は K 分割が要る形だけ）。全行下書きは退避データをコピーせず mask で読む | 深い下書きでの標準経路落ちと、周回ごとの K/V コピー（文脈 2k で 3.6ms）を解消 |
| `f7c74d8` | 境界トークンの確定（1 行 forward）を、全行の下書きの後に回す | 警告ログで特定した上書き元。以前は境界行より後ろの行が誤った K/V で下書きしていた |

kernel 移植で踏んだ罠（どちらも黙って 0 か誤った値を返すため、kernel に static_assert を入れた）：`tile_matmad_nax` は 1 simdgroup あたり 16×16 の tile を扱う分岐を持たない。`QuantizedBlockLoader` は threadgroup のスレッド数が BN 以上でないと、1 スレッドの読み込みが重み行をまたぐ。

### 31B 実機の推移（翻訳、合計 tok/s、GPU 専有）

| 版 | 同時 1 | 同時 2 | 同時 3 |
|---|---:|---:|---:|
| 初版 | 12 | 約 12 | 15〜17 |
| `f9eea41` | 13〜16 | 約 20 | 約 21 |
| `21deca7` | 15 | 約 21 | 約 24 |

- 管制の見立てでは、31B の通常バッチ（MTP なし）は同時 3 件で約 31 tok/s（1 ステップ 95ms）。複数要求 MTP が上回るには、1 周をさらに約 2 割縮める必要がある（`batch-parked` が続く）。
- 計測環境の揺れ：Claude デスクトップアプリの描画プロセスが CPU 約 490%・GPU 使用率 60〜80% を使っていた時間帯があり、同じ版の周回時間が回ごとに ±30% 揺れた。本番の記事業務の速度にも影響する。
- 切り出し（6 層）の周回内訳（3 行、GPU 専有時）：検証 forward 約 20ms、下書き約 10〜15ms、採択判定（全語彙の top-p ソート）約 4〜10ms、巻き戻し約 3ms。通常デコード 3 行 1 ステップは約 16ms。

## 観測（未対応）

- 近似経路の「1 トークンずつ」書き込みで sliding 層を検証すると、退避される K/V は回転枠の物理順になり、時間順を前提とする drafter には合わない。実機の Gemma 4（sliding head_dim 256、L≤8）はこの経路に入らず、mlx 標準の fused 経路を使うため影響しない。小型試験モデル（head_dim 8）でだけ起きる。
- 境界確定を含む行は、行キャッシュの抽出と結合し直し（全 cache のコピー）を伴う。頻度はブロック長ごと（行ごとに 1 回）。

## 残作業

- `f7c74d8` の配備と、31B・26B の同時数計測（揺れを抑えるため回数を増やす）。
- 残りの周回コスト：採択判定の top-p（top_k=64 併用時は上位 64 語だけで同じ集合を出せる）、複数行時の attention、境界確定時の cache 結合。
- MoE の 26B は expert 行列積（`gather_qmm`）が NAX 振り分けの対象外。
- 本番切替（段階 3）は、合計が通常バッチを上回ることを確認してから判断する。
