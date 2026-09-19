# TranslateGemma構造化translation content保持（2026-09-19）

## 背景

TranslateGemmaの翻訳言語コード付きuser contentを、oMLXのchat処理で文字列へ潰すとtemplateへ届かない。Sidekicksの内部評価入口から同じstructured blockを受け取れるよう、既存のmodel loading patch機構へ狭い補正を追加した。

## 決定

`source_lang_code`、`target_lang_code`、`text` を備えるTranslateGemma block listだけをそのまま保持し、通常のfragment listは従来処理へ委譲する。

今回の実走で、patch以前にOpenAI互換の`ContentPart`検証が翻訳固有フィールドを落としていることが判明した。そのため`ContentPart`へ明示的な任意フィールドを追加し、既存patch helperでPydantic modelをTranslateGemmaの5キー形式へ正規化してから`extract_text_content`で保持する。

## 検証結果

専用単体テストと関連テストは328 passed。非slow全体テストは14,215 passed、84 skipped、79 deselected、8 failedで、失敗はDeepSeek/GLM native affineおよびHF XET環境の既存・環境依存テストだった。最初の実走は400（入力メタデータ消失）で失敗し、公式test-mode stopで再試行を停止した。

## 残作業

修正を正式反映してoMLX runtimeを再読込し、Sidekicks経由の実TranslateGemma 4B/12B ticketで、oMLX runtime上の実応答とartifact receiptを確認する。
