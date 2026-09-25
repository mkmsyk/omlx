# VLM MTPの並行要求時ゼロ件化修復

## 背景

Gemma 4 26BでMTPを有効にしていても、Krisisから同時3件を入場させた実運用画面では
実MTPデコードが0件だった。oMLXログでは、各要求が`running`、`waiting`、`prefilling`の
いずれかの同居要求を見つけると、MTP drafterが空いていても全件をBatchGeneratorへ送っていた。

## 原因

VLM MTPのdrafterは要求固有状態を持つため、同時所有者を1件に制限する必要がある。
この排他は`_vlm_mtp_active`で既に実装されている。一方、後から追加されたscheduler全体の
混雑判定もMTP開始前に要求を拒否したため、同じschedule周回で複数要求が見えている場合は
最初の要求すら所有者になれず、MTPが0件になった。

## 変更

- `running`、`waiting`、`prefilling`の存在だけでMTPを無効にする混雑判定を撤去した。
- `_vlm_mtp_active`による単一所有は維持した。最初の適格要求だけがMTPを取得し、後続候補は
  従来どおりBatchGeneratorへ戻る。
- BatchGeneratorとMTP generatorを同じ`step()`で駆動する既存経路をそのまま再利用し、
  route、header、設定、試験専用入口は追加していない。

## 検証

- schedulerに待機・実行・prefill中の同居要求がすべてある条件でも、最初の適格要求が
  MTP generatorを作る回帰テストを追加した。
- そのMTPがactiveの間は2件目がtarget model forwardへ進まず、通常経路へ戻ることを確認した。
- `tests/test_scheduler.py`と`tests/test_vlm_mtp_chunked_prefill.py`の359件が成功した。
- `pytest -m "not slow"`は14,281件成功、60件skip、79件deselectで完走した。
- 正式配備、実運用の複数周回、Krisis.app実画面の結果は配備後に追記する。
