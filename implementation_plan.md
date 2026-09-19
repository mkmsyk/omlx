# 進行中の実装計画

## TranslateGemma structured content の実経路修正

### 成功条件

- TranslateGemma の `source_lang_code`、`target_lang_code`、`text`、`image` を OpenAI 互換入力の検証後も保持する。
- oMLX の通常テキスト推論経路で、TranslateGemma の構造化 block だけを list のまま tokenizer/chat template へ渡す。
- 通常の text content 配列、Pydantic `ContentPart`、tool message の既存変換を壊さない。
- 単体テストで入力モデルの保持と抽出結果を検証し、実ランタイム経路で翻訳評価を再開する。

### 範囲

- `ContentPart` に TranslateGemma の明示的な任意フィールドを追加する。
- 構造化 block の認識・Pydantic model から dict への正規化を既存の oMLX patch helper に集約する。
- `extract_text_content` を正本の変換点として、認識した block のみ保持する。
- Gemma 4 の名前部分一致による TranslateGemma 誤検出を止める。
- 失敗した評価 ticket は公式 test-mode stop 経路で停止し、修正後に同じ3ケースを6実行する。

### 検証

- 対象単体テスト、`pytest -m "not slow"`、`git diff --check`。
- oMLX を正規の Krisis stop queue 経路で再読込し、Navigator の Sidekicks 経路から4B/12Bを一件ずつ評価する。
- 各成果物の `summary.json` で status、verificationState、finalDisposition、result を確認する。
