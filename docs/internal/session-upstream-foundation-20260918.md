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
- native対象テスト: 115 passed
- 標準全体: 14,242 passed / 60 skipped / 79 deselected
- `uv lock --check`: pass
- `uv run python -m compileall -q omlx tests`: pass
- `git diff --check`: pass

標準全体テストは、親shellから継承された`HF_HUB_DISABLE_XET=1`を外し、NAX stock routingを明示的に無効化して実行した。これらはテスト対象の不具合ではなく、実行環境と現行Apple GPUの経路選択を固定するための条件である。

## native kernel再ビルドと互換修正

- `xcodebuild -runFirstLaunch`を実行してXcode初回コンポーネントを導入した。Xcode 27.0のMetal Toolchain取得はGUIから開始したが、作業時点で`xcodebuild -showComponent MetalToolchain -json`は`uninstalled`を返した。
- macOSに既に存在するApple公式Metal Toolchainを一時的な`xcrun`ラッパーから利用し、`OMLX_WITH_CUSTOM_KERNEL=1 uv pip install -e . --no-build-isolation`相当でcustom kernelを再ビルドした。bonsai、decode_fast、glm_moe_dsa、minimax_m3、qwen35_prefillの全系統を確認した。
- MLX 0.32.2のreduction順差により、DSpark物理ringとFP16 affine blockのbitwise比較が崩れたため、通常経路をstock計算順へ合わせた。物理ringは`OMLX_DSPARK_RING_NATIVE=1`の明示時だけ使用し、FP16 affineはstock `mx.gather_qmm`へフォールバック、BF16はnativeを継続する。
- `env -u HF_HUB_DISABLE_XET OMLX_DEEPSEEK_MOE_NAX=0 uv run pytest -m "not slow"`で全体を再実行し、14,242 passed、60 skipped、79 deselectedを確認した。
