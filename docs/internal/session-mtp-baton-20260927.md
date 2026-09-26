# 外付けMTPの要求ごとの割当（Krisis の MTP バトン、2026-09-27）

計画の正本は Krisis の `implementation_plan.md`（26BのMTPバトン）。

## 背景

Gemma 4 の外付けMTP（`vlm_mtp`）は drafter が1件分の状態しか持てない。現行の scheduler は
「同じモデルに他の要求がいれば MTP を始めない」ため、同時3件で翻訳が流れ続けると記事作成にMTPが付かない。
Krisis が開始時に「誰がMTPを持つか」を決め、oMLX がそれを要求単位で履行する。

## 変更

- 要求ごとの `mtp_mode`（`claim` / `yield` / `off`、無指定は従来どおり）。
  - `ChatCompletionRequest.mtp_mode`（閉じた値）→ `chat_kwargs` → `VLMBatchedEngine._pop_mtp_kwargs`
    → `EngineCore.add_request(mtp_mode=)` → `Request.mtp_mode`。
  - drafter の無いモデルへ指定されたら 400 で拒否する（黙って無視しない）。
  - `/v1/models/status` の各モデルに `mtp_request_modes`（drafter 付きでロード済みなら true）を出す。
- `_route_to_vlm_mtp`: `off` は MTP へ入れない。`claim` / `yield` は他の要求が走っていても空いた drafter を取る
  （無指定の要求だけが従来の混雑判定を通る）。drafter の同時1件は従来どおり。
- 1周まとめ出力: `run_vlm_mtp_decode(per_round=True)` と `_mtp_rounds_by_round`。mlx-vlm の単発ループと
  同じ本体で、検証1周で確定したトークンを1回の yield で返す。`_step_vlm_mtp` はそれを同じ step で全部出す。
  以前は1 step に1トークンだったため、通常バッチと同居すると MTP 側の速度が step 周期で頭打ちになっていた。
  停止トークン以降は捨てる。
- 仮持ちの受け渡し: step 先頭（メモリ逼迫時の退避と同じ位置）の `_yield_vlm_mtp_to_claimant`。
  待機・prefill 中に `claim` がいて、drafter を `yield` が持っていれば、その要求を待機列の先頭へ戻し
  `mtp_mode=off` で再開させる（出力済みトークンを文脈に含めて再prefill。クライアントへの重複出力なし）。
  既存のメモリ逼迫退避の本体を `_return_running_request_to_waiting` に切り出して共用した。
  画像を含む要求はトークン列から再現できないため譲らない。

## 検証

- `tests/test_vlm_mtp_baton.py`（33件）: mlx-vlm `_mtp_rounds` とのトークン列一致（受理パターン×上限の15通り。
  出力を1周1トークンに削る変異で8件失敗することを確認）、振り分けの各モード、1周まとめ出力と停止、
  受け渡し（仮持ち→待機先頭・MTPなし・出力済み文脈、本持ち・画像・claim不在では譲らない）、
  HTTP入口（drafterなしで400、指定のエンジンまでの到達）。
- `tests/test_engine_pool.py`: `mtp_request_modes` の申告。
- 既存の MTP・scheduler 試験 435 件成功。
- `pytest -m "not slow"`（開発 venv）: 14,394件成功、8件失敗。失敗は `test_deepseek_v41_affine.py`（5件）、
  `test_glm_moe_dsa_patch.py`（2件）、`test_hf_downloader.py`（1件）で、変更を stash した基底 commit でも
  同じ8件が失敗する（開発 venv の native kernel・環境変数の状態による既存の不一致）。

## 配備と本番での結果

- release `0.7.0.dev4-38f9e3c` として配備（prepare の全試験合格、apply 中断0件、finalize 済み）。
- 本番で Krisis のバトンを12分有効にしたところ、`claim` の要求が通常バッチ2件の横で MTP を始めた後、
  26B の3件すべてが毎秒約1.2トークンへ落ち、26B の生成量は無効時の約5分の1、31B も約4割減った
  （Krisis `docs/internal/session-mtp-baton-20260927.md`）。バトンは無効に戻した。`mtp_mode` 無指定の
  既定動作（単独のときだけMTP）は変わらない。

## 残作業

- 混在時の低下要因の切り分け。仮説（未検証）: `run_vlm_mtp_decode` が周回ごとに呼ぶ
  `_sync_and_clear_cache` がプロセス全体のMetalバッファ再利用領域を毎stepで空にし、同居する通常バッチと
  他モデルのengineにも再確保と同期待ちを課している。周回ごとの解放を間引いた版で短時間の再計測をする。
