# oMLX documentation index

## 現行文書

| 文書 | 内容 |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | 開発参加、テスト、コード構成の案内 |
| [oMLX総則](omlx/omlx.md) | 製品境界と認証区分 |
| [Passport認証仕様](omlx/omlx-passport-auth.spec.md) | browser sessionと機械credentialの境界 |

## 内部作業ログ

| 文書 | 内容 |
|---|---|
| [管理画面アクティブモデル一覧の未コミット変更](internal/session-active-model-visibility-20260906.md) | 非表示モデルの一覧除外修正と検証結果 |
| [oMLX人間sessionのPassport一元化](internal/session-passport-auth-20260912.md) | 管理画面とネイティブアプリの認証経路変更 |

[管制管理下のprefill退避](internal/session-managed-prefill-20260910.md)。

[メモリ圧力後のpending unload回復](internal/session-pending-unload-recovery-20260912.md)。

[プロセスメモリ圧力時の個別request退避と実機反映](internal/session-process-memory-request-defer-20260912.md)。

## アーカイブ

Passport認証移行の実装・配備を確認する場合は、[移行計画](omlx/archive/omlx-passport-auth.plan.md)と[検証記録](omlx/archive/omlx-passport-auth.walkthrough.md)を参照する。

導入手順と当日の実機検証を確認する場合は、[完了計画](archive/omlx-managed-prefill.plan.md)と[検証記録](archive/omlx-managed-prefill.walkthrough.md)を参照する。

緊急メモリ回収後に新規リクエストが409で停滞した場合は、[完了計画](archive/omlx-pending-unload-recovery.plan.md)と[検証記録](archive/omlx-pending-unload-recovery.walkthrough.md)を参照する。

hard/emergency pressureで同一モデルのstreamが一斉abortした事象を再調査する場合は、[完了計画](archive/omlx-process-memory-request-defer.plan.md)と[検証記録](archive/omlx-process-memory-request-defer.walkthrough.md)を参照する。
