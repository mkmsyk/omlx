# oMLX upstream 土台更新 実装計画

## 目的

`origin/main` の現行土台（0.7.0.dev3、mlx-lm/mlx-vlm の更新、cache/VLM/cluster/admin の更新）を、ユーザー側 `fork/main` に取り込む。Passport認証、Krisis経由のprefill、メモリ圧力時のrequest退避など、現在のローカル運用契約は保持する。

## 所有境界と不変条件

- 上流実装の正本は `origin/main`、ユーザー固有の運用契約の正本は `fork/main` とする。
- Navigator側へoMLX実装を複製しない。oMLXの変更は `/Users/mkmsyk/Repositories/omlx` のみで完結させる。
- Passportのbrowser sessionと機械credentialの境界を崩さない。
- Krisisが所有するモデルload/unload・推論admissionをoMLXから直接実装し直さない。
- カスタムkernelはMLX ABIと結合しているため、依存ピン更新時はビルド可能性とABI検査を確認する。
- 24時間連続稼働を前提とし、読み取り・管理系の変更でもqueue/request処理の回帰を検査する。

## 段階

1. upstream/forkの差分、依存ピン、ローカル固有コミットと関連テストを記録する。
2. `origin/main` を現在の `main` に統合し、衝突を所有境界に沿って解消する。
3. `pyproject.toml`/`uv.lock`、Passport認証、Krisis連携、メモリ圧力処理、既存のローカルテストを重点確認する。
4. Fastテスト、構文・差分検査、可能ならmacOSネイティブテストとcustom-kernel ABI検査を実行する。
5. 検証記録と内部作業ログを更新し、明示したパスだけをcommitして `fork` へpushする。

## 受入条件

- `main` が `origin/main` の更新を含み、ローカル固有の認証・運用契約が残っている。
- lockfileとpyprojectの依存解決が一致する。
- 変更箇所の対象テストと `pytest -m "not slow"` が成功する、または依存・ハードウェア不足を具体的に記録する。
- Pythonの構文検査と `git diff --check` が成功する。
- Passport/Krisis/メモリ圧力の境界に未確認の回帰がない。確認できない範囲は完了報告で明記する。

## 承認境界

削除、force push、秘密情報更新、公開範囲変更は行わない。上流統合、依存更新、commit、ユーザー側 `fork` へのpushはこの依頼の通常範囲として実施する。
