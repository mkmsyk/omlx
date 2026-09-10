# 管制管理下のprefill退避

背景: Sidekicks追加計画Aの承認。tool/利用者待ち中の仕事寿命を管制判断へ接続する。
変更: 管制管理下の通常prefillモデル退避をKrisisへ依頼。HTTP中はpool lockを保持しない。
管制指示のonly_idle unloadはlock内で状態を再検証。standaloneの経路は維持する。
検証: tests/test_engine_pool.py 143件、tests/test_server.py 55件通過。構文検査通過。管理下callback、通信断、候補再検証の3試験を追加。
残作業: 管制経由で更新起動、Sidekicks公開経路からの実GUI検証。
