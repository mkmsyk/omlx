# 管制への退避要求に runtime の資格を付ける（2026-10-09）

Krisis の交通整理の再設計（Krisis `docs/traffic-control-authority.plan.md` 段階2）で、管制は要求ごとに「どの主体の要求か」を
`Authorization: Bearer` の資格から照合して記録する。oMLX が管制へ送る `POST /control/prefill/relieve` の送り手は主体 `runtime`。

## 変更

- `omlx/engine_pool.py` の `_krisis_credential_headers`: Krisis が起動時に渡す `KRISIS_CREDENTIAL_FILE` から資格を読み、退避要求に付ける。
  - 要求ごとに読むので、資格の差し替えに再起動は要らない。
  - 渡されていない・未発行なら何も付けない。段階2の Krisis は照合を記録するだけで、資格の有無で断らない。
  - 値はログへ出さない。
- Krisis 側（起動時に `KRISIS_CREDENTIAL_FILE` を渡す）は Krisis のブランチ `feat/subject-credentials`。

## 検証

- `tests/test_engine_pool.py` を全件流し、200 件成功。新しい試験 `test_managed_prefill_sends_the_runtime_credential_krisis_passed` で、渡された資格が退避要求に載ることを確かめた。
- 配備は Krisis の管制モード「oMLX 更新による再起動」（`omlx-update` スキル）で、Krisis の段階2の配備と合わせて行う。まだしていない。
