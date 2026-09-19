# TranslateGemma構造化翻訳content 検証記録

## 検証

- `ContentPart` の検証段階でTranslateGemmaの言語コードを保持し、`extract_text_content`でstructured blockをdict listのまま渡す実経路へ修正。
- patch単体および関連テスト: `328 passed`。
- patch単体テスト: TranslateGemma block保持と通常text fragmentの従来変換が成功。
- staged `oMLX.app` の埋込みPythonでpatch適用後のblock保持を確認。
- 正式build: `apps/omlx-mac/Scripts/build.sh release --no-rebuild-donor` 成功。
- `pytest -m 'not slow'`: 14,215 passed、84 skipped、79 deselected、8 failed。
- 失敗8件はDeepSeek v4.1/GLM native affine呼出しとHF XET環境変数に関する既存・環境依存テストで、今回のstructured translation変更のテストではない。

## 実走前の状態

Navigatorの最初のTranslateGemma実走は、oMLXの入力モデルが言語コードを落としたため400で失敗した。公式test-mode stopで再試行を停止し、修正を反映してから実モデルの6ケースを再実行する。

## 実モデル評価（2026-09-20 JST）

次の条件で、Navigatorのtest-modeからSidekicksのnative経路を通して、4B Q8と12B Q6を各3ケース実行した。呼出側からsampling、context、max tokens、model以外の推論パラメータは指定していない。全件で `engine=native`、`think=none`、`max_tokens=8192`、`productionApplied=false` だった。

| モデル | ケース | elapsedSec | resultBytes | 終了・検証 |
| --- | --- | ---: | ---: | --- |
| 4B Q8 | 日本語→英語 | 12.893 | 2,673 | `end_turn` / passed / complete |
| 4B Q8 | 英語→日本語 | 9.677 | 3,733 | `end_turn` / passed / complete |
| 4B Q8 | 難しい特集・英語→日本語 | 31.647 | 6,186 | `end_turn` / passed / complete |
| 12B Q6 | 日本語→英語 | 27.233 | 2,928 | `end_turn` / passed / complete |
| 12B Q6 | 英語→日本語 | 28.636 | 4,249 | `end_turn` / passed / complete |
| 12B Q6 | 難しい特集・英語→日本語 | 42.748 | 6,932 | `end_turn` / passed / complete |

`elapsedSec`はNavigatorの評価ticketの経過時間であり、decode-onlyの速度や並行処理能力ではない。単一ticketの3件平均は4B Q8が18.072秒、12B Q6が32.872秒だった。

品質の目視評価では、12B Q6は3ケースとも意味、段落構造、専門用語の保持が安定しており、難しい特集でも高品質だった。12Bの特集には、原文の「Sometimes that is true」を「必ずしも当てはまるとは限りません」と反転させた文と、「12つ」という軽微な表記不自然さがあった。4B Q8も全ケースを完走し、短い記事は実用的だったが、日本語→英語で文断片（`By reading the errors ...`）が1か所、特集で「もう1一つ」などの軽微な崩れが見られた。したがって、今回の3題では12B Q6を品質優先、4B Q8を短文・速度優先と評価する。

完走した成果物は以下に保存されている。

- 4B Q8: `~/.sidekicks/evaluations/translategemma/task-6f9d2f1a-43d4-432a-b2e2-6a6a4ecec10b`、`task-fe00c3d0-cd08-4c41-ba68-c990ccd0fe55`、`task-559194e1-718b-4c2c-87f3-91bdda5f6f44`
- 12B Q6: `~/.sidekicks/evaluations/translategemma/task-b758487d-1561-4f50-92d9-a9029cb7f574`、`task-1d849786-4eef-43a6-9ffd-1d6c0d826f08`、`task-7036f73f-04e5-4a2f-96f9-ccc6a536c6cf`

途中の失敗ticketは品質評価に含めていない。入力メタデータ保持、TranslateGemmaのGemma 4誤判定、4Bの`<end_of_turn>`停止token補完を順に修復し、最終6件はすべて公式stopReason `end_turn` で完走した。評価終了後、Navigatorのtest-modeは公式stop経路で停止済みである。
