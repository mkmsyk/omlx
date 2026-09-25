# MTP実行状態のモデル別可観測性

## 背景

Krisisのモデル詳細でMTPの実使用を表示するには、同時数や設定値から推測せず、oMLXの実デコード状態を
正本として取得する必要がある。

## 変更

- scheduler統計へ、実際にVLM MTP drafterを使っている要求数を追加した。
- 既存の`GET /v1/models/status`の各モデルへ`mtp_active_requests`を追加した。
- Krisisが発行するboundedな推論チケットIDを、内部request IDとは別の観測IDとしてrequestへ保持する。
- scheduler統計と既存モデル状態APIへ、実際にVLM MTP drafterを使っているrequestの観測IDだけを
  `vlm_mtp_active_observation_ids` / `mtp_active_observation_ids`として追加した。
- 観測IDは取消・collectorのkeyに使わず、task ticket、本文、予約tokenもoMLXへ渡さない。
- 新しいroute、別port、認証例外は追加していない。

## 検証

- Batched/VLM両engineからrequestへ観測IDが伝播することを確認した。
- scheduler統計はMTP状態に入ったrequestの観測IDだけを安定順で返し、観測IDなしの既存要求も
  件数には含めることを確認した。
- モデル状態APIへのID投影とheaderのcanonical検証を含む対象80件が成功した。
