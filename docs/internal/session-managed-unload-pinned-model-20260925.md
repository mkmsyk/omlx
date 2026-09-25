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

実機反映とKrisisからの退避確認はcommit・push後に追記する。
