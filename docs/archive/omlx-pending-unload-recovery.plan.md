# 実装計画

2026-09-12。hard/emergency memory pressure でモデルを pending unload にした後、直ちに
quiescent でなければ EnginePool の既存 watcher を登録する。watcher は全リース、active
engine、scheduler queue の drain を待ち、pool lock 下で再確認してから unload する。

1. pending marker を登録した後の即時 unload 結果を確認する。
2. 即時 unload できなければ既存 watcher を登録する。
3. busy モデルの emergency 分岐で watcher 登録を検証する回帰テストを追加する。
4. 対象テストと非低速回帰を実行する。
