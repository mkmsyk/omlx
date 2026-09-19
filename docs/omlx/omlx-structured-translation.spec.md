# TranslateGemma構造化翻訳content仕様

oMLXの既存chat completion経路で、TranslateGemma形式のcontent blockだけをtokenizerまで保持する。

- 翻訳blockは `type=text`、`source_lang_code`、`target_lang_code`、`text` を持つ。
- 通常のtext fragment listは従来どおり文字列化する。
- runtimeへの直接回避経路や未知形式の無制限fallbackは追加しない。
- patchはモデルロード前に既存patch機構から一度だけ適用する。
