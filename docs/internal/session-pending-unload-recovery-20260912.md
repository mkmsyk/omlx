# メモリ圧力後の pending unload 回復

## 背景

hard/emergency memory pressure で使用中モデルを中断・退避対象にしたとき、当該時点で
pool がまだ quiescent でなければ、`pending_unload_reason` が残ったままになることがあった。
その後にすべてのリースと scheduler の作業が終了しても unload を再試行しないため、新規
取得が `ModelBusyError` (HTTP 409) で恒久的に拒否された。

## 変更

- memory enforcer が即時 unload できなかった pending モデルに、既存 EnginePool の待機
  watcher を登録するようにした。
- watcher は pool lock 下でリース数・アクティブ engine・scheduler queue がすべて空である
  ことを再確認してから一度だけ unload する。強制的な途中 unload は行わない。
- emergency pressure の busy モデル分岐に watcher 登録を要求する回帰テストを追加した。

## 設計判断

待機と安全な quiescence 判定は既存の EnginePool の実装を再利用した。enforcer に別の
ポーリングや unload 経路を増やさず、idle が直ちに成立する従来の経路も維持する。

## 検証

- `uv run --extra dev pytest tests/test_process_memory_enforcer.py -q`: 165件成功。
- `uv run --extra dev pytest -m 'not slow' -q`: 10,799件成功、32件skip、74件deselect。変更と
  無関係なネイティブ数値比較・Hugging Face環境設定の既存失敗15件を確認。
- `git diff --check`: 成功。

詳細は `docs/archive/omlx-pending-unload-recovery.walkthrough.md` を参照する。
