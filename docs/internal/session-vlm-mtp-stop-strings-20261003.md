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

## 検証

- `tests/test_vlm_mtp_stop_sequences.py`・`test_vlm_mtp_thinking_budget.py`・`test_scheduler.py`・`test_vlm_mtp_chunked_prefill.py`
  の 423 件成功（fork の作業ツリー、稼働 release の venv）。全体の `pytest -m "not slow"` は `omlx-update prepare` が流す。
- 配備（`omlx-update prepare --current` → `apply` → `verify` → `finalize`）と実機の確認は下に追記する。

## 残 TODO

- 上流へ同じ修正を提案するかは別途判断する。
