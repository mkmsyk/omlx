# プロセスメモリ圧力時の個別request退避 — 検証

2026-09-12。

- 新しいpressure deferはScheduler executor上の次のstep境界でのみ実行される。最も新しいrunning
  requestだけをtail requeueし、先行requestをabortしない。
- replay prefillはoriginal promptと既出outputを合算したtoken数でmemory guardへ渡す。metricsと
  generation limit用の`num_prompt_tokens`は元の値を保持する。
- `uv run --extra dev pytest tests/test_scheduler.py::TestProcessMemoryPressureDefer tests/test_scheduler_prefill_memory_guard.py -q`: 41件成功。
- `uv run --extra dev pytest tests/test_process_memory_enforcer.py -q`: 167件成功。
- `uv run --extra dev pytest -m 'not slow'`: 10,805件成功、32件skip、74件deselect、15件失敗。
  失敗はDeepSeek/Qwen/GLM/DFlashのネイティブ数値比較とHugging Face Xet環境設定であり、
  Scheduler / ProcessMemoryEnforcer対象テストは成功した。
- `git diff --check`: 成功。

## 実機反映

Krisisの実APIで`activeRequests=0`、推論待ち0、execution lease 0を確認してから、
`POST /control/unload`と`POST /control/runtime/mlx/stop`の正規経路で旧processを終了した。
oMLXは`~/.venvs/omlx`から本checkoutをeditable importする構成であり、停止後の明示loadによって
main `d6acd402`から新processを起動した。Gemma 4 26B-A4Bのloadは11.04秒で成功し、
Krisisからruntime up、active request / 推論待ち / execution leaseが全て0であることを確認した。

実機でhard/emergency pressureを人為的に起こす検証は、稼働中requestを危険に晒すため実施していない。
