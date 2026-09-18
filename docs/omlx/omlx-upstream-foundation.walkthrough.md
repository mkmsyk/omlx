# oMLX upstream 土台更新 検証記録

## 対象

- 作業日: 2026-09-18
- 対象: `/Users/mkmsyk/Repositories/omlx`
- 上流: `origin/main` → `36dc7362`
- 更新前のローカル先頭: `feedd194`（更新計画のcommit）
- 更新後: `origin/main` を `main` へ `--no-ff` 統合
- push先: `fork/main`（`origin` へはpushしない）

## 変更

- upstreamの0.7.0.dev3土台、cache/VLM/cluster/admin/native-kernel関連の更新を統合した。
- 既存のPassport browser session／機械credential境界、Krisis managed prefill、メモリ圧力時request退避を保持した。
- `pyproject.toml`の依存をMLX 0.32.2、mlx-lm 0.32.0、mlx-vlm 0.7.1、mlx-audio 0.4.8、transformers 5.15.1、ddgs 9.16.0等へ更新した。
- `uv sync --dev`と`uv lock --check`は成功した。`uv.lock`はリポジトリのignore対象のためcommit対象外。
- マージ後の回帰として、API key setup、network bind時のno-auth無効化、画像decode cache回収順、scheduler parser／literal think markerの分岐を修正した。

## 検証結果

成功:

- `uv run pytest -m "not slow" tests/test_admin_auth.py tests/test_admin_api_key.py tests/test_api_auth.py tests/test_engine_pool.py tests/test_process_memory_enforcer.py tests/test_scheduler.py`
  - 804 passed
- focused scheduler/auth/memory tests
  - 39 passed
- `uv lock --check`
- `uv run python -m compileall -q omlx tests`
- `git diff --check`: pass
- `OMLX_DEEPSEEK_MOE_NAX=0 uv run pytest -q tests/test_deepseek_v41_affine.py tests/test_deepseek_v4_dspark.py tests/test_glm_moe_dsa_patch.py`
  - 115 passed

標準全体テスト:

- `env -u HF_HUB_DISABLE_XET OMLX_DEEPSEEK_MOE_NAX=0 uv run pytest -m "not slow"`
  - 14,242 passed、60 skipped、79 deselected

## native kernel再ビルドと互換修正

- `xcodebuild -runFirstLaunch`でXcodeの初回システムコンポーネント導入を完了した。
- Xcode 27.0のMetal ToolchainはGUIから取得を開始したが、`xcodebuild -showComponent MetalToolchain -json`では作業時点で`uninstalled`のままだった。
- macOSに既に存在するApple公式Metal Toolchain（`/var/run/com.apple.security.cryptexd/mnt`配下）を一時的な`xcrun`ラッパー経由で選択し、次のコマンドでMLX 0.32.2向けcustom kernelを再ビルドした。
  - `OMLX_WITH_CUSTOM_KERNEL=1 PATH=/tmp:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin uv pip install -e . --no-build-isolation`
- 再ビルド後、全5系統（bonsai、decode_fast、glm_moe_dsa、minimax_m3、qwen35_prefill）のnative artifactがimport可能であることを確認した。
- MLX 0.32.2でDSparkの物理ring kernelとstock verify GEMMのreduction順が一致しないため、`OMLX_DSPARK_RING_NATIVE=1`の明示時だけ物理ringを使い、既定値はmaterialized rowwise経路にした。現行Apple GPUではstock rowwiseと同じ計算順になる。
- MLX 0.32.2で差分が出るFP16 affine block kernelはstock `mx.gather_qmm`へフォールバックし、BF16はnative block kernelを継続利用するようにした。

## 残る環境差

- Xcode 27.0のMetal Toolchainコンポーネント自体は作業時点で`uninstalled`であり、GUIのダウンロード完了までは確認できていない。ただし、既存のApple公式toolchainで再ビルドし、native対象テストおよび標準全体テストは成功している。
- `OMLX_DSPARK_RING_NATIVE=1`はMLX 0.32.2でのreduction順差を意図的に再現する明示的なベンチマーク用経路であり、通常運用の既定値では使用しない。
