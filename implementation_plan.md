# 進行中の実装計画：Gemma 4 の MTP を同時複数要求へ適用する

<!-- 完了した計画は docs/omlx/ へ移す。 -->

状態：承認済み（2026-09-26）・段階 0 実施中／作成 2026-09-26

## 1. 目的と成功条件

Gemma 4（26B-A4B qat 6bit、31B 6bit）で、同じモデルへの同時要求すべてに MTP（投機デコード）を効かせる。

成功条件（すべて満たしたら完了）:

1. 26B へ同時 3 要求を流したとき、3 行すべてが MTP で進む（`Lightning MTP batch activated for 3 sequences` 相当のログと行別の採択統計）。
2. 出力の正しさ：greedy（temperature 0）で、同時 3 要求の各出力が「MTP 無し・同じ要求を単独実行」の出力とトークン列で一致する。検証用 attention 近似（§4.3）は正しさ試験では無効化して比べる。
3. 処理量：Krisis 既存の「単発換算倍率」（`Krisis/docs/internal/session-gemma-concurrency-trial-20260924.md` の方法）で、26B 上限 3・31B 停止中の倍率が現行の 1.55 を 20% 以上上回る（目安 1.86 以上）。
4. 退行なし：単発（同時 1）の tok/s が現行 `vlm_mtp` の単発を 5% 超下回らない。`pytest -m "not slow"` と追加試験が通る。
5. Krisis・Navigator・Sidekicks の呼出し側からはモデル ID・API が変わらない。

## 2. 現状の事実（2026-09-26 にコードとログで確認）

- 本番の Gemma 4 は外付け MTP（`vlm_mtp_enabled`、補助モデル `gemma4_assistant` を別ロード）。`omlx/scheduler.py` の `_try_start_vlm_mtp` は、
  - drafter が要求固有の状態をモジュールに持つため 1 件しか担当できない（使用中なら通常生成へ）。
  - 同モデルに実行中・待機中・入力処理中の要求があると MTP を始めない。
  - 9/26 の `server.log` で前者 170 回、後者 2,919 回の切替。9/24 の実測で同時 2 以上の 26B 完了のうち MTP 経路は 1〜9%。
- 上流 oMLX には別経路「Gemma 4 Lightning MTP」がある（`omlx/patches/mlx_vlm_mtp/gemma4_vlm_runtime.py`）。補助モデルの重みを本体へ統合したチェックポイント（`language_model.mtp.*`＋`text_config.mtp_assistant_config`）を `mtp_enabled` で動かし、mlx-lm BatchGenerator 上の Lightning MTP サイクルに乗る。統合ツール `omlx/oq.py: combine_gemma4_assistant_mtp` も既存。
  - ただし単発専用：`_omlx_mtp_multi_request` を宣言しておらず、`mtp_forward` は最後の verify で退避した共有 K/V（`_omlx_mtp_shared_kv`）と位置（`_omlx_mtp_cache_ref`）をモデル属性 1 組で持つ。位置は左パディング 0 を前提にしている。
- Lightning MTP の複数要求機構は Qwen3.5/3.6・Qwen4-Exp・GLM・DeepSeek-V4.1 で稼働済み（`omlx/patches/mlx_lm_mtp/fused_batch.py`、`batched_head.py`）。同じ深さの行を 1 回の target forward で検証し、採択・下書き履歴・cache 境界は要求ごとに持つ。行ごとに採択数が違う（ragged）巻き戻しは、mlx-vlm の `SpeculativeCacheTransaction`（回転 cache は受理分を再生）でベクトル処理する。
- mlx-vlm の Gemma 4 drafter（`Gemma4AssistantDraftModel`）自体は複数行対応：行別 `position_ids`、行別 `kv_valid_len`、`left_padding` 正規化（`masks.normalize_batched_shared_kv_states`）を持つ。
- mlx-vlm の Gemma 4 `rollback_speculative_cache` は ragged 採択で例外を投げる（「uniform per-row acceptance が必要」）。Transaction 方式には未対応。
- `omlx/patches/gemma4_verify_attention.py`（verify 用高速 attention）は左パディング 0 の cache だけに適用され、mask 引数を無視する。
- 本 fork は `origin/main` から 89 コミット遅れ。その中に Gemma 4 Lightning MTP の修正（#3561：text-only 統合モデルの経路、head の dtype 揃え〔fp16 本体で head が 4 倍遅い問題〕、bind 時期）と Lightning MTP 全般の改修（#3797、#3895）がある。上流も Gemma の複数要求対応はまだ無い。
- 両モデルの sampling は temperature 1.0 / top_p 0.95 / top_k 64、penalty・grammar なし。Lightning の確率的（stochastic）複数行 verify 経路に乗れる。
- ディスク空き 674 GiB。統合チェックポイントは本体 shard を symlink し、head shard（0.7〜0.8 GB）と config・index だけ新規に書けばよい。

## 3. 方針と却下した案

**採用：Gemma 4 Lightning MTP（統合チェックポイント）を複数要求対応にする。** 同時 N 行の検証を 1 回の target forward にまとめられるので、decode がメモリ帯域律速である限り、N 行の MTP を単発とほぼ同じコストで回せる。

**却下：外付け `vlm_mtp` の drafter を要求ごとに複製する。** 各要求が別々の round loop で target forward を回すため、N 要求で N 回の forward になり、通常のバッチ decode（N 行で 1 回）より遅くなりうる。drafter の重み・状態も N 倍になる。9/24 の実測でも、同時 2 の標準バッチ（MTP なし）が同時 1 の MTP より 36% 多く処理しており、「バッチを保ったまま MTP」でなければ利得が出ない。

## 4. 作業段階

### 段階 0：Gemma Lightning の上流修正を取り込む（`omlx-update` 手順）

- `omlx-update` は上流の正式版タグだけを追う。2026-09-26 の `check` は `updateAvailable: false`（最新正式版 v0.6.4、稼働 0.7.0.dev4）で、#3561 は rc 版にしか無い。そこで上流全体は統合せず、次の 2 件だけを fork の `main` へ cherry-pick し、`prepare --current` で配備する。
  - `9acba360`（#3561）：text-only 統合モデルの経路、head の dtype 揃え、head の早期 bind 廃止（量子化前の埋め込みを掴んで 31B で 5.6 GB を余計に確保する不具合の修正）。
  - `b6c7721e`：text-only Gemma 4 への画像入力拒否。`omlx/engine/vlm.py` の競合は、fork に無い mimo_v2 の動画展開を除いて拒否部分だけ取り込んだ。
- 上流全体（#3797 などの Lightning 全般改修）の統合は、次の正式版タグで通常の更新として行う。本改造はそのときの衝突を抑えるため、patch モジュールと分岐追加に閉じる。
- 完了条件：配備後に現行 `vlm_mtp` の 26B/31B が従来どおり動く（ログで `vlm_mtp stats`、Krisis `/control/status` 正常）。

### 段階 1：統合チェックポイントを作り、単発 Lightning を実測する（可否判定）

1. `~/.omlx/models/` に統合モデルを 2 つ作る（例：`gemma-4-26B-A4B-it-qat-6bit-mtp`、`gemma-4-31b-it-6bit-mtp`）。本体 shard は HF cache の snapshot へ symlink し、`combine_gemma4_assistant_mtp` で head shard・index・config を書く。HF cache の元ファイルは書き換えない。
2. oMLX の model settings：統合モデルに `mtp_enabled: true`、`vlm_mtp_enabled: false`、sampling は現行と同値。
3. Krisis に**試験用の別カタログ項目**（新しい Krisis model id）として追加する。本番の 26B/31B 項目は変えない。ロード・推論はすべて Krisis 経由、計測は Sidekicks から通常の公開経路で行う（Krisis 内に試験入口を作らない）。
4. 同一プロンプト群（記事業務の実 prompt から短・中・長の 3 種、各 5 回）で、単発 `vlm_mtp`（本番項目）と単発 Lightning（試験項目）の decode tok/s、TTFT、採択率を比べる。

**可否判定**：Lightning 単発が `vlm_mtp` 単発の 95% 未満なら、段階 2 へ進まず原因（head 実行時間、verify attention、dtype）を調べて報告する。複数行で得をしても、単発が大きく落ちれば全体利得が相殺されるため。

### 段階 2：oMLX fork の改造（本体）

2.1 **共有 K/V 退避を行対応にする**（`gemma4_vlm_runtime.py`）

- verify forward で退避する共有 K/V を、バッチ全体の配列＋行別の左パディング・確定長として持つ。
- `mtp_forward` を B 行入力対応にする：行別 `position_ids`（各行の確定長−1）、行別 `kv_valid_len`、ragged 棄却分の行別切り詰め。drafter 既存の `left_padding` 正規化を使う。
- 単発経路（B=1）の挙動とトークン列は現状と同一に保つ。

2.2 **ragged 巻き戻しを Transaction 方式にする**

- Gemma 4 の複数行 verify forward で `start_speculative_cache` を開始し、`SpeculativeCacheTransaction` を gdn 位置で返す。`fused_batch._advance_group` の vector rollback 経路（`isinstance(gdn, SpeculativeCacheTransaction)`）へ乗せる。sliding 層の `BatchRotatingKVCache` は Transaction の受理分再生で扱う。
- mlx-vlm の Gemma 4 `rollback_speculative_cache` は Transaction を受けたら委譲し、従来の例外は Transaction が無い経路にだけ残す。mlx-vlm は vendor 側を直接直さず、oMLX の runtime patch で差し替える（既存の Qwen patch と同じ流儀）。
- 上記が揃った時点で `_omlx_mtp_multi_request = True`、`_omlx_mtp_batch_rollback = True` を宣言する。

2.3 **下書きを行まとめで実行する**

- head は状態を持たない（`make_mtp_cache() == []`）ため、既存の `batched_head`（head cache 前提）はそのまま使えない。状態なし head 用の分岐を `batched_head.draft` に足し、共有 verify 直後に全行の fold と chain 下書きを 1 回の head 呼び出しで行う。
- 採択数・深さが揃わない行は、既存の group 分け（同じ深さごとに検証）に従う。

2.4 **verify 用 attention 近似の扱い**（`gemma4_verify_attention.py`）

- 現状は左パディング 0 に限定、mask 無視。複数行では左パディングが出るため、まず**適用対象外のまま**（stock attention）で正しさと速度を測る。
- 速度が成功条件に届かない場合だけ、左パディング対応（行別開始位置を kernel に渡す）を追加課題として別途計画する。mask を無視したまま適用範囲を広げることはしない。

2.5 **途中参加・離脱**

- 走行中のバッチへ新要求が合流する／行が終了する場合は、既存の park・再突入機構（`_allows_new_mtp_activation`、`_reconcile_mtp_batch_to_standard`）をそのまま使う。Gemma 固有の退避（共有 K/V、行別長）が filter・extend・merge 後も行と対応したままになることを試験で確かめる。

2.6 **試験**（`tests/` に追加。モデル不要の合成試験を主にする）

- 行対応 `mtp_forward`：B 行の出力が各行を単独で流した出力と一致（小型の合成 drafter）。
- ragged 巻き戻し：採択数 [0, 2, 3] などの後、各行の cache が単独実行と同じ内容・長さになる。sliding window 境界をまたぐ場合を含む。
- 左パディングあり・途中参加・途中終了・深さ違いの group 分け。
- 既存の Gemma 単発試験（`test_mtp_*`、`test_vlm_mtp_*`、`test_gemma4_*`）が不変。
- 実モデル（slow 印）：26B 統合モデルで greedy の同時 3 要求を流し、MTP 無し単独実行とトークン列一致（成功条件 2）。

### 段階 3：配備と本番切替

1. `$omlx-update` の fork 修正配備手順で導入する（管制モード経由の再起動）。
2. 試験用カタログ項目で成功条件 1・2・4 を実機確認する（Sidekicks 経由）。
3. Krisis profile（`config/profiles/mac-m5max.json`）の本番 26B/31B 項目の `omlx.repo` を統合モデルへ切り替える。**Krisis の model id は変えない**ので Navigator・Sidekicks・FC 側の呼出しは不変。切替前に、この 2 モデルへ画像入力を送る呼出し元が無いか全利用側を確認する（統合モデルは VLM として読むが、画像経路は単発 `vlm_mtp` 時と同等か確認が要る）。メモリ見積り（headroom 判定に使う値）も統合モデルの実測に合わせる。
4. 反映は Krisis の正式配備手順。試験用カタログ項目はこの時点で削除する。

**切り戻し**：Krisis profile の `omlx.repo` を元の repo へ戻し、元モデルの `vlm_mtp_enabled` 設定はそのまま残しておく（段階 3 では元モデルの設定を消さない）。oMLX 本体は Lightning の複数行宣言（`_omlx_mtp_multi_request`）を外すだけで単発へ戻る。

### 段階 4：同時数の再調整（Krisis）

- 26B の上限を 1/2/3/4/6、31B を 1/2 で段階的に切り替え、単発換算倍率を 9/24 と同じ方法で測る（`POST /control/limits/reload`）。成功条件 3 を判定し、最良の上限を profile に確定する。
- 結果は Krisis の `docs/internal/` に記録する。

## 5. 触るリポジトリと契約

| リポジトリ | 変更 | 契約への影響 |
|---|---|---|
| omlx（fork） | 段階 0 の上流統合、段階 2 の runtime patch・batch 経路・試験 | 公開 API 変更なし。model settings の既存項目 `mtp_enabled` を使うだけ |
| Krisis | 段階 1 の試験用カタログ項目（一時）、段階 3 の `omlx.repo` 切替、段階 4 の上限 | model id 不変。試験項目は段階 3 で削除 |
| Sidekicks | 変更なし（計測で通常経路を使うだけ） | なし |
| Navigator / FC | 変更なし | なし（model id 不変のため） |

## 6. 危険と対処

- **出力の正しさ**：ragged 巻き戻しの誤りは「棄却トークンの K/V が残る」形で出力を静かに汚す（mlx-vlm issue #1962 と同型）。段階 2.6 の cache 内容一致試験と、実モデル greedy 一致を必須条件にする。
- **メモリ**：統合 head は現行の別ロード drafter と同じ重み量で、増えない見込み（段階 1 で Krisis の計器で実測する）。Transaction が sliding 窓の受理分を保持する分だけ一時的に増える。ロードは必ず Krisis 経由。
- **速度が伸びない**：verify attention 近似を外す分、単発より 1 行あたりの verify が遅くなりうる。段階 1 の可否判定と段階 4 の実測で判断し、届かなければ 2.4 の kernel 拡張を別計画にする。
- **上流との乖離**：改造は patch モジュールと `batched_head`・`fused_batch` の分岐追加に閉じ、上流ファイルの書き換えを最小にする。上流への提案（PR）はユーザー判断で別途。

## 7. 将来の検討事項（本計画の範囲外）

- MTP と DFlash の併用（2 系統の下書きを同じ verify で検証、または周回ごとに選択）。上流は `mtp_enabled` と `dflash_enabled` の同時有効を禁止している。1 要求時は得をしうるが、複数行 verify では検証トークン数の増加がバッチ利得を食い合う。26B/31B 用 DFlash 下書きモデルの有無も未確認。本計画の段階 4 の実測後に検討する（2026-09-26 ユーザー合意）。

## 8. 付随：Qwen3.8 Flash-Next

2026-09-26、`Jundot--Qwen3.8-Flash-Next-oQ4e-mtp` の `mtp_enabled` を true にした（管理 API、検証は 200 で通過）。`qwen4_exp` は Lightning 複数要求に対応済み。次回ロードから有効になり、動作確認は未実施（非常駐のため）。
