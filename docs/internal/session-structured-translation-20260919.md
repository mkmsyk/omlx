# TranslateGemma構造化translation content保持（2026-09-19）

## 背景

TranslateGemmaの翻訳言語コード付きuser contentを、oMLXのchat処理で文字列へ潰すとtemplateへ届かない。Sidekicksの内部評価入口から同じstructured blockを受け取れるよう、既存のmodel loading patch機構へ狭い補正を追加した。

## 決定

`source_lang_code`、`target_lang_code`、`text` を備えるTranslateGemma block listだけをそのまま保持し、通常のfragment listは従来処理へ委譲する。

今回の実走で、patch以前にOpenAI互換の`ContentPart`検証が翻訳固有フィールドを落としていることが判明した。そのため`ContentPart`へ明示的な任意フィールドを追加し、既存patch helperでPydantic modelをTranslateGemmaの5キー形式へ正規化してから`extract_text_content`で保持する。

## 検証結果

専用単体テストと関連テストは328 passed。非slow全体テストは14,215 passed、84 skipped、79 deselected、8 failedで、失敗はDeepSeek/GLM native affineおよびHF XET環境の既存・環境依存テストだった。最初の実走は400（入力メタデータ消失）で失敗し、公式test-mode stopで再試行を停止した。

追加で、TranslateGemmaをGemma 4として名前部分一致判定していたため、TranslateGemma専用経路へ入らない問題を修正した。さらに4B変換版の`generation_config.json`に`eos_token_id`がないため、`<end_of_turn>`を生成し続ける問題をモデル限定のstop token補完で修正した。修正後の対象テストは63 passedだった。

## 実モデル評価結果（2026-09-20 JST）

Navigator test-modeから4B Q8と12B Q6を各3ケース実行した。全6件が `status=completed`、`verificationState=passed`、`finalDisposition=complete`、`stopReason=end_turn` で、`productionApplied=false` だった。Sidekicksの実効設定は全件 `engine=native`、`think=none`、`max_tokens=8192`。呼出側でsamplingやcontextを上書きしていない。

- 4B Q8: 日本語→英語 12.893秒、英語→日本語 9.677秒、難しい特集 31.647秒。短文は実用的だが、日本語→英語で文断片が1か所、特集で軽微な表記崩れがあった。
- 12B Q6: 日本語→英語 27.233秒、英語→日本語 28.636秒、難しい特集 42.748秒。意味・構造・用語はより安定していたが、特集で「Sometimes that is true」の意味を反転させた文と「12つ」という表記不自然さがあった。
- 単一ticketの平均は4B Q8が18.072秒、12B Q6が32.872秒。これは評価ticketの経過時間であり、並行処理能力やdecode-only速度の測定ではない。

成果物は`~/.sidekicks/evaluations/translategemma/`配下の各ticketディレクトリに保存した。途中の失敗ticketは修復経路の証跡として残したが、品質評価には含めていない。評価完了後、Navigatorのtest-modeは公式stop経路で停止済みである。

## 残作業

今回の依頼範囲で必須の実走と評価は完了。追加で並行処理能力を測る場合は、品質評価とは別のベンチマークとして、同一入力・同時実行数・モデル常駐状態・拒否数を明示して実施する。
