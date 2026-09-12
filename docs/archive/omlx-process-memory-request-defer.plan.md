# プロセスメモリ圧力時の個別request退避 — 完了計画

## 目的

hard/emergency memory pressureで、同一モデルの全requestをabortする経路を廃止する。Schedulerが
安全なstep境界で一件だけを待機列の末尾へ戻し、同じstreamを再開する。

## 実装

- ProcessMemoryEnforcerはSchedulerを持つengineへ一件のpressure deferだけを要求する。
- Schedulerは新しくadmitされたrunning requestを選び、UID、RoPE、paged cache、一時prefill状態を
  executor thread上で外す。見えている出力はreplay contextへ加え、consumer / parser / detokenizerは維持する。
- deferしたrequestはcold prefillへ戻し、retry上限を2回にする。上限に達したそのrequestだけが
  `process_memory_retry_exhausted`で終了する。
- replay contextのtoken数でprefill memory guardを再評価し、元のprompt token数だけを使ってKVを
  過少見積りしない。

## 検証条件

- Scheduler / ProcessMemoryEnforcerの対象テスト。
- `uv run --extra dev pytest -m 'not slow'`。
- 実機で安全に再現可能な場合のみ、既存requestのstream継続を確認する。
