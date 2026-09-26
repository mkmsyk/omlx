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

`omlx/adapter/gemma4.py`の`extract_gemma4_messages`で、tool_callsに空白以外の本文が付くとき、本文を直前の
assistant messageとして分け、tool-calling messageの本文を空にする。本文は削らず、呼び出し前という時系列も保つ。
tool-calling messageは本文を持たないので、テンプレートはターンを開いたまま生成へ渡す。
出力側の文字列除去（`thought`を消す等）は加えていない。

## 検証

- 実会話の失敗ターン（prefix 6）を生補完で各4回: 修正前は4/4が`thought\n`平文で開始、
  分割後は4/4が正規の`<|channel>thought\n<channel|>`（パーサ出力`<think>\n</think>`）で開始。
  本文を捨てる案も漏れは消えたが、自分の前置きを見失い「承知いたしました」を繰り返したため不採用。
- テスト: `tests/test_gemma4_messages.py`へ分割・複数ステップ順序・空白本文の3件、
  `tests/test_gemma4_rendering.py`へ末尾ターンが開いたままかの描画検査を追加。修正を外すと3件が失敗する。
  描画検査は`OMLX_GEMMA4_MODEL_PATH=<snapshot>`で実モデルのテンプレートを指定して実行した。

## 残TODO

- 空のthoughtでも`<think>\n`由来の`reasoning_content:"\n"`が出る。表示上の小さな雑音で、本件の修正対象外。
