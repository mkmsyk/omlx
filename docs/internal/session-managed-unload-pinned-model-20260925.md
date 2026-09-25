# 外部管制の条件付き退避とstandalone pinの分離（2026-09-25）

## 背景

Krisis管理下のoMLXで、仕事・待機・execution lease・予約・次工程需要がないQwenが常駐し続けた。
oMLXの実ログではQwenが保存済み`is_pinned`により起動時にpreloadされていた。

## 原因

Krisis専用の`only_idle=true`退避は、pool lock内の安全再検証に既存の
`_is_idle_for_prefill_eviction`を再利用していた。この共通判定はstandalone oMLXのpinを尊重するため、
外部管制が仕事なしと判断しても`model_busy_or_missing`を返した。Krisis側はこの拒否を成功へ読み替えず、
常駐を維持していた。

## 変更

- 共通のidle判定へ`allow_pinned`境界を追加した。
- `only_idle=true`の外部管制入口だけはpinを越える。
- active request、scheduler待ち、loading、in-useの確認とpool lockは維持した。
- prefill退避、TTL回収、standaloneの自動退避は従来どおりpinを尊重する。

## 検証

- pinされたidleモデルは通常のprefill退避候補にならないことを維持した。
- 同じpinされたidleモデルを外部管制入口からは条件付き退避できる回帰試験を追加した。
- `/Users/mkmsyk/.venvs/omlx/bin/python -m pytest -q tests/test_engine_pool.py -k 'conditional_control_unload'`は
  2件成功、失敗0だった。
- 条件付き退避commit `b25226db`と検証修正commit `3064102c`をforkの`main`へpushした。稼働venvの`omlx` import先が
  `/Users/mkmsyk/Repositories/omlx/omlx`であることを確認した。
- 保存済みのQwen設定は`is_pinned: false`へ戻し、最終commit反映ではNavigatorの
  `krisis-runtime-stop` barrier `runtime-stop-barrier-a7f7e092-f981-47ed-b99b-5d05219fb3a6`で
  oMLXを世代交代した。barrierは17:58:49 JSTに完了した。
- 新oMLX PID 5808の起動ログにはQwenの`Pinned model`、`Preloading pinned model`、
  `Loading model`がなく、実需要のあるGemma 26Bだけをloadした。
- Krisisの`/control/status`と導入済みKrisis.appの初期画面で、常駐はGemma 26Bのみ、
  Qwenはカタログにだけ存在することを確認した。

## 全体検証で検出した独立不整合

初回の標準fast suiteは14,222件成功、9件失敗だった。失敗を隔離再実行し、今回の
`EnginePool`変更とは独立した次の不整合と確認した。

- M5のNAX経路では意図的にstock `gather_qmm`へ倒す一方、pre-NAX block kernelの単体試験7件が
  実機の既定分岐を上書きしていなかった。試験内だけpre-NAX分岐を明示し、実運転のNAX選択は変えていない。
- `is_gemma4_model`がトップレベル`gemma4_text`をGemma 4として扱わず、DFlash parser試験が失敗した。
  TranslateGemmaの`gemma3`除外を維持したまま`gemma4_text`を現行Gemma 4型へ追加した。
- shellの`HF_HUB_DISABLE_XET=1`をdownloader importの副作用と誤認する試験を、環境変数を除いた
  子processでimport前後を検査する形へ直した。利用者の外部設定は変更していない。

失敗9件の隔離再試験は16件成功、`EnginePool`とtokenizerの関連試験は223件成功した。
標準fast suiteの再実行は14,232件成功、84件skip、79件deselect、失敗0だった。
