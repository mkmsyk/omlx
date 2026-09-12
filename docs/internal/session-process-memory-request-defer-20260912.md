# プロセスメモリ圧力時の個別request退避

## 背景

プロセス全体のhard/emergency memory pressureで、一つのモデルに属する全requestをabortすると、
圧力の原因と無関係な進行中streamも失われる。

## 変更

- enforcerからschedulerへのthread-safeなdefer要求を追加し、schedulerが一件だけを安全な
  step境界でwaiting tailへ戻すようにした。
- detach時にUID mapping、RoPE、prefill tracker、paged cache、batch rowを整理し、既出outputを
  replay contextへ入れて重複送信を防ぐ。
- requestごとのretry上限を設け、尽きたrequestだけを型付きerrorで終了する。
- replay時のprefill memory guardを実token長で見積もるよう補強した。

## 設計判断

候補の選択とlive batchの操作をenforcer側へ複製せず、既存のScheduler executorを唯一の操作面にした。
cache reclaimと通常のadmission順序は変更していない。

## 検証

対象215件は成功。full non-slow suiteは10,805成功・15失敗で、失敗は変更範囲外の
native数値比較とXet環境設定だった。詳細はarchive walkthroughを参照する。
