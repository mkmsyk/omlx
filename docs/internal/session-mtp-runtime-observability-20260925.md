# MTP実行状態のモデル別可観測性

## 背景

Krisisのモデル詳細でMTPの実使用を表示するには、同時数や設定値から推測せず、oMLXの実デコード状態を
正本として取得する必要がある。

## 変更

- scheduler統計へ、実際にVLM MTP drafterを使っている要求数を追加した。
- 既存の`GET /v1/models/status`の各モデルへ`mtp_active_requests`を追加した。
- 新しいroute、別port、認証例外は追加していない。

## 検証

- scheduler統計とモデル状態の対象テストで、0件と稼働中件数を確認する。
- Python構文検査を行う。
