# TranslateGemma構造化翻訳content 検証記録

## 検証

- patch単体テスト: TranslateGemma block保持と通常text fragmentの従来変換が成功。
- staged `oMLX.app` の埋込みPythonでpatch適用後のblock保持を確認。
- 正式build: `apps/omlx-mac/Scripts/build.sh release --no-rebuild-donor` 成功。
- `pytest -m 'not slow'`: 14,235 passed、60 skipped、79 deselected、8 failed。
- 失敗8件はDeepSeek v4.1/GLM native affine呼出しとHF XET環境変数に関する既存・環境依存テストで、追加patchのテストではない。
