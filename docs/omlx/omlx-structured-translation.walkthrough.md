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
