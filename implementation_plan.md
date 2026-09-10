# 実装計画

2026-09-10 Sidekicks追加計画Aの利用者承認に基づく。
Krisis管理下ではprefillのモデル退避を管制へ依頼し、自律候補選択を行わない。
pool lockの外でHTTP要求し、管制指示の条件付きunloadはlock内でidleを最終確認する。
standaloneの既存動作は維持。管理下で管制不達/拒否なら別経路へ退避しない。
検証はfake controllerとpool lockの契約試験、対象pytest、構文検査、Sidekicks公開経路の実走行。
