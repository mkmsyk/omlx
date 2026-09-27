# 管制からのバッファプール返却要求（2026-09-27）

## 背景

2026-09-27 に Krisis の SCRAM（回収可能量 < 12GB でモデルを降ろす最終防衛線）が6回あった。oMLX は解放済みの
Metal バッファを MLX のプールに 20〜29GB 溜め、自分の使用量が soft 線 88GB を越えたときだけ返す。oMLX 以外の
使用量が大きいと、oMLX がプールを返す前に Krisis がモデルを降ろしていた（17:04 は oMLX 87.4GB で soft に届かず、
Krisis が 26B を降ろして Sidekicks 実行63件が `model_evicted`）。システム全体の空きを見ている判定者は管制だけ
なので、プールを返す時機を管制が決められるようにする。計画は Krisis の `implementation_plan.md`。

## 変更

- `POST /v1/memory/reclaim`：enforcer の `_request_scheduler_cache_reclaim` を管制から要求する。各スケジューラの
  step 境界で同期してから clear する既存経路で、推論中でも安全。`{ok, requested, poolBytes}` を返し、enforcer が
  無効なら `{ok:false, skipped:"memory_enforcer_disabled"}`。
- `unload_idle_for_control`：管制の SCRAM が同じモデルを降ろしている最中の `ModelBusyError` を未処理の500に
  していた（16:41・17:04 に各5回）。見送り `{ok:false, skipped:"model_busy_or_missing"}` として返す。

## 検証

- `tests/test_engine_pool.py`・`tests/test_server.py`・`tests/test_process_memory_enforcer.py`（`-m "not slow"`）
  408件成功。追加：teardown 中の条件付き回収が見送りになること、reclaim が enforcer の既存経路を1回呼ぶこと。

## 配備

release `0.7.0.dev4-5f19dde` を Krisis の `tools/omlx-update.mjs` で配備した（apply 20:37〜20:42、verify は
26B の推論で確認、finalize で本番線を `5f19dde5` に確定）。1回目の prepare 試験で
`test_cluster_supervisor.py::test_run_worker_smoke_returns_complete_receipt` が本番推論と同時の全件試験の負荷で
5秒の応答待ちを超えて落ち、単体3回成功・`--continue` の再試験で全件成功した。管制側の記録は Krisis の
`docs/internal/session-scram-pool-reclaim-20260927.md`。

## 残TODO

- 次に回収可能量が20GBを割ったとき、管制の要求とこのエンドポイントの返却が対応し、SCRAM が起きないことを観測する。
