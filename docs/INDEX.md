# oMLX documentation index

## 現行文書

| [omlx-structured-translation.spec.md](omlx/omlx-structured-translation.spec.md) | TranslateGemmaのstructured content block保持契約 |
| [omlx-structured-translation.walkthrough.md](omlx/omlx-structured-translation.walkthrough.md) | patch、staged app、全体テストの検証結果 |

| 文書 | 内容 |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | 開発参加、テスト、コード構成の案内 |
| [oMLX総則](omlx/omlx.md) | 製品境界と認証区分 |
| [Passport認証仕様](omlx/omlx-passport-auth.spec.md) | browser sessionと機械credentialの境界 |

## 内部作業ログ

| [session-structured-translation-20260919.md](internal/session-structured-translation-20260919.md) | TranslateGemma structured content保持の実装判断と検証 |

| 文書 | 内容 |
|---|---|
| [管理画面アクティブモデル一覧の未コミット変更](internal/session-active-model-visibility-20260906.md) | 非表示モデルの一覧除外修正と検証結果 |
| [oMLX人間sessionのPassport一元化](internal/session-passport-auth-20260912.md) | 管理画面とネイティブアプリの認証経路変更 |
| [Passport Cookie更新の統一](internal/session-passport-cookie-renewal-20260913.md) | Passportのrolling expiryを管理面Cookieへ共通middlewareで再中継 |
| [oMLX upstream土台更新](internal/session-upstream-foundation-20260918.md) | upstream統合、依存更新、native kernel再ビルド、全体テスト |
| [Gemma 4のツール前本文によるthought漏れ](internal/session-gemma4-preamble-turn-20260926.md) | tool_calls付き本文がターンを閉じ、生成が`thought`平文で始まる原因の実測と変換層での修正 |
| [Gemma 4 Lightning MTPの複数要求対応](internal/session-gemma-batch-mtp-20260926.md) | 共有検証・行別巻き戻し・行別下書き区間の実装、回転cache取り消しと近似attention判定の潜在不具合修正 |
| [外付けMTPの要求ごとの割当](internal/session-mtp-baton-20260927.md) | Krisis の MTP バトン用の `mtp_mode`（claim / yield / off）、1周まとめ出力、仮持ちの受け渡し |

[管制管理下のprefill退避](internal/session-managed-prefill-20260910.md)。

[メモリ圧力後のpending unload回復](internal/session-pending-unload-recovery-20260912.md)。

[プロセスメモリ圧力時の個別request退避と実機反映](internal/session-process-memory-request-defer-20260912.md)。

## アーカイブ

oMLX upstream土台更新の計画・検証・タスクは、[計画](omlx/omlx-upstream-foundation.plan.md)、[検証記録](omlx/omlx-upstream-foundation.walkthrough.md)、[タスク](omlx/omlx-upstream-foundation.tasks.md)を参照する。native kernelのtoolchain環境差と互換修正も検証記録に記載する。

Passport認証移行の実装・配備を確認する場合は、[移行計画](omlx/archive/omlx-passport-auth.plan.md)と[検証記録](omlx/archive/omlx-passport-auth.walkthrough.md)を参照する。

導入手順と当日の実機検証を確認する場合は、[完了計画](archive/omlx-managed-prefill.plan.md)と[検証記録](archive/omlx-managed-prefill.walkthrough.md)を参照する。

緊急メモリ回収後に新規リクエストが409で停滞した場合は、[完了計画](archive/omlx-pending-unload-recovery.plan.md)と[検証記録](archive/omlx-pending-unload-recovery.walkthrough.md)を参照する。

hard/emergency pressureで同一モデルのstreamが一斉abortした事象を再調査する場合は、[完了計画](archive/omlx-process-memory-request-defer.plan.md)と[検証記録](archive/omlx-process-memory-request-defer.walkthrough.md)を参照する。
