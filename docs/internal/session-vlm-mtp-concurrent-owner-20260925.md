# VLM MTPの並行混在試行と撤回

## 背景

Gemma 4 26BでMTPを有効にしていても、Krisisから同時3件を入場させた実運用画面では
実MTPデコードが0件だった。oMLXログでは、各要求が`running`、`waiting`、`prefilling`の
いずれかの同居要求を見つけると、MTP drafterが空いていても全件をBatchGeneratorへ送っていた。

## 原因

VLM MTPのdrafterは要求固有状態を持つため、同時所有者を1件に制限する必要がある。
この排他は`_vlm_mtp_active`で既に実装されている。一方、後から追加されたscheduler全体の
混雑判定もMTP開始前に要求を拒否したため、同じschedule周回で複数要求が見えている場合は
最初の要求すら所有者になれず、MTPが0件になった。

## 試行

- `running`、`waiting`、`prefilling`の存在だけでMTPを無効にする混雑判定を一時的に撤去した。
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

## 実運用結果と撤回

- 正式配備後、26Bを3件実行中に実MTPは常に1件となり、Krisis.appでも該当チケット行だけに
  「使用中」が表示された。表示相関と単一所有は正しく動いた。
- しかし翻訳3件の混在では、MTP要求598 tokenのdecodeに約114秒かかり約5.2 tok/sとなった。
  同居した通常要求も約73秒、約103秒かかり、既往の翻訳3件中央値16.36秒を大きく下回った。
- 次の3件は約16分後のモデル切替まで完走せず中断された。混在MTPを速度改善として採用できない。
- 混雑判定を元へ戻し、MTPは単独入場、翻訳などのelastic処理は3件BatchGeneratorという
  Krisis側の実行形状選択で実現する。並行混在版は本番から撤回した。

## 次回の事前手順

1. MTP所有テストが通っても速度改善とは判定しない。変更前に同一モデル・同一入力種別・同一同時数の
   baselineを正規のSidekicks → Krisis → oMLX経路で採る。
2. 混在を試す場合はMTP要求だけでなく、同居する通常要求全件と直後のbatchまで、wall time、token/s、
   完走・中断・stallを記録する。acceptance rate単独を採否根拠にしない。
3. MTP使用は設定値や行順から推測せず、oMLXの実観測IDとKrisis推論ticket IDの一致で確認する。
4. 同居群または直後群が大幅に悪化した場合は、混在範囲を広げず変更を撤回する。MTPはcaller側で
   単独入場、elastic処理は純BatchGeneratorを既定に戻す。
5. 上記の実運用比較を通すまでは、schedulerの混雑判定撤去を性能修正として配備しない。
