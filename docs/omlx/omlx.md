# oMLX

oMLXはApple Silicon上でモデルを提供するローカル推論サーバーである。OpenAI互換API、
管理Web UI、ネイティブmacOSアプリを一つの実行層へ接続する。

人間がブラウザで使う管理sessionはBunrin Passportだけが発行・検証・失効する。
推論APIとネイティブアプリが使うAPI key、cluster enrollment token、CSRFや一時的な
処理状態は機械credentialまたはprotocol stateであり、ブラウザsessionとは別に扱う。

## 外部管制下のモデル退避

Krisisなどの外部管制がload/unloadを所有する構成では、
`POST /v1/models/{id}/unload?only_idle=true`を管制専用の条件付き退避入口とする。
oMLXはpool lock内でactive request、scheduler待ち、loading、in-useを再検証し、
仕事があれば退避を拒否する。管理UIの`is_pinned`はstandalone oMLXの常駐方針であり、
認証済み外部管制の退避判断は上書きしない。通常のprefill退避とTTL回収は引き続きpinを尊重する。
