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

## 残TODO

- `tools/omlx-update.mjs prepare --current` → apply → verify → finalize で配備する（Krisis の手順）。
