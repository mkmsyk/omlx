# vlm_mtp の要求を stop の文字列で止める（2026-10-03）

## 背景

Sidekicks が管制の制御再起動で切れた推論を続きから再開する作業（Krisis `implementation_plan.md` 案 A）で、Gemma 4 の
思考の続きを `/v1/completions` に `stop: ["<channel|>"]` を付けて生成させ、思考の終わりで止める。26B の実測で、
同じ要求が BatchGenerator では思考の終わりで止まり（16:05、2.8 tok/s、`finish_reason: stop`、1,991 トークン）、vlm_mtp で
生成された回は止まらずに答えまで書き切った（17:58、49.6 tok/s、2,812 トークン。ログ `vlm_mtp decode started` →
`vlm_mtp stats ... finish=stop` は EOS）。

## 原因

`_build_state_machine` は要求ごとに EOS・`stop_token_ids`・`stop` の文字列をトークン列にした `StopSequences` を作り、
BatchGenerator はそれで終端する。`_route_to_vlm_mtp` もその `StopSequences` を `_VLMMTPDecodeState.state_machine` に
受け取っていたが、`_step_vlm_mtp` は別に写した EOS と `stop_token_ids` の集合（`stop_token_ids` 欄）だけで判定していた。
写しを持った理由（「StopSequences に最後のトークンで終わったかを返す手段が無い」）は、mlx-lm の現行版では
`StopSequences.matcher()` と `Matcher.advance(token)` があるので成り立たない。応答の後処理の文字列照合も、特殊トークンの
文字が出力から消えるので `<channel|>` には当たらない。上流 `origin/main`（`5dcfe243`）も同じ形。

## 変更

- `omlx/scheduler.py`: `_VLMMTPDecodeState` は `state_machine` から `matcher()` を1つ持ち（`stop_matcher`）、`_step_vlm_mtp` は
  1トークンごとに `advance` で終端を決める。EOS だけの写し（`stop_token_ids` 欄）を撤去した。生成器
  （`run_vlm_mtp_decode`）へ渡す EOS の集合は、下書きを止めるためにそのまま渡す。
- 試験: `tests/test_vlm_mtp_stop_sequences.py`（1トークンの stop、複数トークンの stop の最後のトークン、EOS と生成上限）。
  `state_machine` に `object()`・`None` を渡していた試験2件と1件を、本物の `StopSequences` に揃えた。

## 配備の試験で落ちた子 process の待ち時間（別 commit）

`omlx-update prepare --current`（`0.7.0-ab80d9d`）の `pytest -m "not slow"` は 16,843 件成功・5件失敗で止まった（33分。前回 `78ac54b`
は全件成功で23分）。5件はすべて子 process を固定の秒数で待つ試験の時間切れで、修正とは別の箇所だった。

| 試験 | 待ち方 | 実際 |
|---|---|---|
| `test_engine_teardown.py::test_watchdog_terminates_stalled_or_over_budget_process`（2件） | `subprocess.run(timeout=30)` | 子の `import omlx.engine_core` だけで 31.4 秒（負荷平均 94〜160） |
| `test_cluster_cli.py::test_cluster_status_json_is_runnable`・`..._pipeline_smoke_json_is_runnable` | CLI 全体を 30・40 秒、pipeline-smoke 内部の集団通信 30 秒 | omlx の読み込みで枠を使い切る |
| `test_eval_worker_pool.py::test_real_code_scoring_subprocess_cleanup` | 採点の子 process が目印を書くまで 2 秒 | Python の起動で超える |

どの枠も確かめたい性質の判定ではなく、止まったままを防ぐ上限だった（watchdog が壊れていれば子は10秒の sleep の後に
正常終了して判定で落ちる）。上限を `tests/subprocess_limits.py` の `SUBPROCESS_HANG_GUARD_SEC`（600秒）にそろえ、CLI の
worker-smoke・pipeline-smoke の内部の期限はその半分を渡す。負荷平均 147 で対象 58 件が成功した。

## 検証

- `tests/test_vlm_mtp_stop_sequences.py`・`test_vlm_mtp_thinking_budget.py`・`test_scheduler.py`・`test_vlm_mtp_chunked_prefill.py`
  の 423 件成功（fork の作業ツリー、稼働 release の venv）。全体の `pytest -m "not slow"` は `omlx-update prepare` が流す。
- 配備: `omlx-update prepare --current` で release `0.7.0-b88fa65`（全体の `pytest -m "not slow"` 成功）→ `apply`
  （10:48:29Z に 26B を退避、中断した推論 0 件、10:48:46Z 完了）→ `verify`（推論チケット `r-cead84e1-7334-4f05-9668-79f48689c381`、
  26B・sidekick）→ `finalize`（fork `main` = `b88fa657`）。試験で止まった `0.7.0-ab80d9d` の worktree・ブランチ・venv は撤去した。
- 実機（19:52〜19:53 JST、管制経由・特急、Sidekicks の `resume_completion`）: 思考の途中を渡して `stop: ["<channel|>"]` で続けさせた
  ①が、26B・31B とも vlm_mtp（`vlm_mtp decode started` → `finish=stop`）で思考だけを返して止まった（26B 72 トークン・emitted 73、
  31B 57 トークン・emitted 58。最後の1つが `<channel|>`）。②は閉じた思考の後ろから答えの1文（13 トークン）を書いた。
  修正前は同じ経路で①が答えまで書き切っていた。

## 残 TODO

- 上流へ同じ修正を提案するかは別途判断する。
