# 管制管理下のprefill退避の検証

2026-09-10。Sidekicks追加計画Aの承認に基づく。

- b62e4f50を利用者fork/mainへpush。管制経由で旧runtimeを停止し、通常業務による起動で反映した。
- Engine pool 143件、server 55件の対象試験と構文検査が通過。
- 管制への通信はpool lock外、only_idleの最終判定はlock内。拒否・通信断を別経路の退避へ変換しない。
- Sidekicks.appの実Qwenderで質問待ち→「進む」→Read→回答を確認。
  16:14:20のKrisis記録はownerPid=94702、phase=user_wait、protected=true。
  run 20260910-161249-10ba7f。行根拠を足した同スレッドの続行20260910-161636-6f96b8はcomplete。
- 上記GUIは保護契約と回答後の継続を確認する。実メモリ逼迫を起こす強制退避試験はしていない。

この追加実装の残作業なし。Krisisの仕事配分全体の見直しは別タスクが担当する。
