# oMLX upstream 土台更新 作業ログ

## 背景

oMLXの更新が滞っていたため、`/Users/mkmsyk/Repositories/omlx` の `main` に対して、上流 `origin/main` の現行土台を取り込む。作業対象はoMLXのみで、Navigator側へ実装を複製しない。

## 実施内容

- `origin/main`をfetchし、forkとの差分とローカル固有コミットを確認した。
- 進行計画を作成してcommit/pushした後、`origin/main`を`--no-ff --no-commit`で統合した。
- Passport認証、Krisis managed prefill、memory pressure request defer、admin API key loopback制約をローカル契約として保持した。
- upstreamのnetwork auth hardening、image decode cache reclaim、cluster/admin/VLM/cache更新を統合した。
- `uv sync --dev`でMLX 0.32.2、mlx-lm 0.32.0、mlx-vlm 0.7.1、mlx-audio 0.4.8、transformers 5.15.1等を導入した。
- マージ後テストの失敗を原因別に修正した。schedulerではparser経路のstop判定を上流どおり維持し、literal think markerは明示tokenがある通常デコード経路だけで保護するようにした。

## 検証

- 主要テスト: 804 passed
- focusedテスト: 39 passed
- 標準全体: 14,091 passed / 197 skipped / 79 deselected / 14 failed
- `uv lock --check`: pass
- `uv run python -m compileall -q omlx tests`: pass
- `git diff --cached --check`: pass

全体14件のうち13件はcustom kernelの実行結果で、現行バイナリがMLX 0.32.2向けに再生成されていないことと整合する。残り1件は環境変数`HF_HUB_DISABLE_XET=1`によるテスト環境差で、環境変数を外すと単体passした。

## ブロッカーと残作業

`nanobind==2.15.0`を導入し、custom kernel再ビルドを試みたが、Xcode 27のMetal Toolchainが未導入だった。`xcodebuild -downloadComponent MetalToolchain`はApple asset取得が進まず中断した。既存のnative artifactは上書きしていない。Metal Toolchainを導入可能な環境で再ビルドし、native kernelテストと標準全体テストを再実行する。
