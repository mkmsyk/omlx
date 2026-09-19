# TranslateGemma構造化translation content保持（2026-09-19）

## 背景

TranslateGemmaの翻訳言語コード付きuser contentを、oMLXのchat処理で文字列へ潰すとtemplateへ届かない。Sidekicksの内部評価入口から同じstructured blockを受け取れるよう、既存のmodel loading patch機構へ狭い補正を追加した。

## 決定

`source_lang_code`、`target_lang_code`、`text` を備えるTranslateGemma block listだけをそのまま保持し、通常のfragment listは従来処理へ委譲する。

## 検証結果

専用単体テストとstaged appの埋込みPython smoke testは成功した。正式buildも成功した。非slow全体テストは14,235 passed、8 failedで、失敗はnative affineおよびHF XET環境の既存・環境依存テストだった。

## 残作業

正式反映後、Sidekicks経由の実TranslateGemma 4B/12B ticketで、oMLX runtime上の実応答とartifact receiptを確認する。
