# oMLX

oMLXはApple Silicon上でモデルを提供するローカル推論サーバーである。OpenAI互換API、
管理Web UI、ネイティブmacOSアプリを一つの実行層へ接続する。

人間がブラウザで使う管理sessionはBunrin Passportだけが発行・検証・失効する。
推論APIとネイティブアプリが使うAPI key、cluster enrollment token、CSRFや一時的な
処理状態は機械credentialまたはprotocol stateであり、ブラウザsessionとは別に扱う。
