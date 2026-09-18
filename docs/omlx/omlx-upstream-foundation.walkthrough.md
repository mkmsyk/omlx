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
- `git diff --cached --check`: pass

標準全体テスト:

- `uv run pytest -m "not slow"`
- 14,091 passed、197 skipped、79 deselected、14 failed
- 失敗内訳は、native custom kernel由来13件と、実行環境の `HF_HUB_DISABLE_XET=1` に依存した1件。
- `env -u HF_HUB_DISABLE_XET` ではXetテスト単体がpassした。
- `OMLX_DEEPSEEK_MOE_NAX=0` でNAXのstock routingを外しても、旧metallibが未収録のaffine bit/variantとDSpark ringの不一致が残った。

## 未完了・ブロッカー

MLXのpin更新に伴い、同梱custom kernel binaryの再ビルドが必要。`nanobind==2.15.0`導入後に `OMLX_WITH_CUSTOM_KERNEL=1 uv pip install -e . --no-build-isolation` を実行したが、Xcode 27のMetal Toolchain未導入で `xcrun ... metal` が失敗した。`xcodebuild -downloadComponent MetalToolchain`もApple asset取得が進まず中断した。

このため、Python側の同期と主要回帰は検証済みだが、MLX 0.32.2向けnative `.so/.metallib`の再生成と、それを使った全体テスト成功は未確認である。Metal Toolchainを導入できる環境でcustom kernelを再ビルドし、上記14件を再実行する必要がある。
