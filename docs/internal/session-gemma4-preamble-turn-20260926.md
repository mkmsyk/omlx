# Gemma 4のツール前本文によるthought漏れ（2026-09-26）

## 背景

AMENOYOMI（Sidekicks native engine → Krisis → oMLX）で`gemma-4-26b-a4b-it-qat-6bit`を使う会話で、
ツール結果の後の応答本文が`thought\nスミスさん、…`・`'\n`のように始まり、`reasoning_content`は`"\n"`だけになった
（`~/.amenoyomi/runs/run-b8dd7692d0fc4fdca8663dfb74015a71/worker.log`）。走行は`enable_thinking=false`。

## 実測

1. 単発の問い（ツール無し）は思考on/offとも正しく分割された。channel分割の出力パーサは正常。
2. 保存済みスレッド（`~/.amenoyomi/native/threads/ameno-chat-7bfa531a…/messages.jsonl`）の失敗直前までをKrisis経由で再送すると、
   `content:"thought\n"`が`reasoning`より先に届く形で再現した。
3. oMLXの`extract_gemma4_messages`とモデル同梱テンプレートで描画すると、プロンプト末尾が
   `…<tool_response|>スミスさん、承知いたしました。…<turn|>\n`となり、生成用の`<|turn>model\n`が無かった。
4. 描画済みプロンプトを`/v1/completions`へ送ると、生出力が`thought\n…`（`<|channel>`トークン無しの平文）で始まった。
   モデルがターン外から書き始め、channel markerをトークンではなく文字として綴っている。

## 原因

OpenAI形式はツール呼び出し前の本文を`tool_calls`と同じassistant messageの`content`に置く。
Gemma 4テンプレート（mlx-community同梱版、Google公式2026-07-09版とも）は、tool_responsesを持つmessageの`content`を
ツール応答の後ろへ描画して`<turn|>`で閉じる。最後のmessageが`tool_response`で終わるため生成プロンプトも付かず、
閉じたターンの外で生成が始まる。サーバーの分割処理でもSidekicksの組み立てでもなく、変換層の対応不足である。

## 変更

`omlx/adapter/gemma4.py`の`extract_gemma4_messages`で、tool_callsを持つassistantの本文（呼び出し前の前置き文）を
プロンプトへ描画しない。テンプレートには発話の途中へ本文を置く場所が無い。
ツール応答の後ろへ置くと発話が閉じ、独立した本文だけのmessageにしても、それ自体が`<turn|>`で閉じる。
そのため、後続のtool呼出しは`<|turn>model`無しで閉じた発話の外へ連結される。
前置き文を外すと、履歴の途中も末尾も`<|turn>model\n<|tool_call>…<tool_response|>`の正規形になる。
出力側の文字列除去（`thought`を消す等）は加えていない。ツール後の最終回答（tool_callsを持たない本文）はそのまま残る。

初版（2a5baa8c）は前置き文を直前のassistant messageへ分けていた。末尾の漏れは消えたが、上記の理由で履歴途中が崩れる。
Sidekicks側の同時調査で、実経路でも外す形が良いと実測されたので置き換えた。

## 検証

- 実会話の失敗ターン（prefix 4・6）を`/v1/completions`へ各4回送った。
  - 修正前は、prefix 6で4/4が`thought\n`平文で開始した。
  - 前置き文を外す形は、prefix 4・6とも4/4が正規の`<|channel>thought\n<channel|>`（パーサ出力`<think>\n</think>`）で開始した。
  - この生補完では、外す形で前置き（「承知いたしました」）を書き直す出力が見られた。
- Sidekicks側の調査（Sidekicks `docs/sidekicks/sidekicks-chat-format.walkthrough.md`）の結果。
  - 対象は事故時の履歴で、Krisis通常経路から各8回送った。
  - 前置き文ありは、正しいtool呼出し5/8・thought漏れ4/8・退化ループ1/8だった。
  - 外した形は8/8・0・0で、反復は0/8だった。
- テスト（修正を外すと3件が失敗する）:
  - `tests/test_gemma4_messages.py`へ、前置き文の除外・複数ステップ・最終回答の保持の3件を追加した。
  - `tests/test_gemma4_rendering.py`へ、2ステップの履歴で最後のmodel発話が閉じずtool呼出しを2件含むかの描画検査を追加した。
  - 描画検査は、`OMLX_GEMMA4_MODEL_PATH=<snapshot>`で実モデルのテンプレートを指定して実行した。

## 残TODO

- 空のthoughtでも`<think>\n`由来の`reasoning_content:"\n"`が出る。表示上の小さな雑音で、本件の修正対象外。
