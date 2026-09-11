# メモリ圧力後の pending unload 回復の検証

2026-09-12。

- `process_memory_enforcer` の emergency busy 分岐で、即時の
  `_unload_pending_if_idle_locked` が false を返した場合だけ、既存の
  `_schedule_pending_unload_locked` を呼ぶことを確認した。
- watcher は既存の `EnginePool` にあり、0.1秒ごとの再確認でリース、active engine、
  scheduler queue が空になるまで unload しない。したがって中断中の work を強制解放しない。
- `uv run --extra dev pytest tests/test_process_memory_enforcer.py -q` は165件成功した。
- `uv run --extra dev pytest -m 'not slow' -q` は10,799件成功、32件skip、74件deselect、
  15件失敗だった。失敗はDeepSeek/Qwen/GLM/DFlashのネイティブ数値比較と
  Hugging Face Xet環境設定であり、対象の memory enforcer/EnginePool テストは通過した。
- 実行中の推論サーバーは、配布済みのコミットを管制の正規runtime経路で停止・通常起動し、
  Sidekicks の通常リクエストで別途確認する。
