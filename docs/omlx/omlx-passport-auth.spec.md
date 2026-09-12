# oMLX Passport認証仕様

## ブラウザ管理面

- `/admin`はBunrin Passportへのログイン入口だけを表示する。
- Passport clientは`omlx`、既定originは`http://localhost:8000`、callbackは
  `/admin/auth/passport/callback`とする。
- HTTPを許すのはportを明示した`localhost`、`127.0.0.1`、`::1`だけである。
- callbackは一回限りticketをserver-only client secretで交換し、Passportが発行した
  不透明tokenをhost-only、HttpOnly、SameSite=Lax、Path=/のCookieで中継する。
- 保護された全要求でPassportのvalidate APIを呼び、`authorized=true`だけを許可する。
  oMLXはtokenを署名、解釈、延長、ローカル保存しない。validateが返すexpiryを共通応答middlewareが
  host-only Cookieの`Max-Age`へ再中継し、Passportのrolling TTLとブラウザ保持期限を一致させる。
- logoutはPassportでtokenを失効してからoMLX hostのCookieを削除する。
- client credentialは既定で`~/.omlx/passport-client.secret`から読み、groupまたはotherに
  権限があるファイルを拒否する。環境変数でpath、Passport origin、client ID、client originを
  明示できるが、secret値自体は環境変数へ置かない。

## 機械credential

- `/v1`互換API、ネイティブmacOSアプリ、cluster処理のAPI key／Bearerは維持する。
- ネイティブアプリはmain API keyをBearerとして各要求へ直接付け、browser Cookieを持たず、
  API keyからsessionを発行しない。
- sub keyは推論APIと明示的に対応する機械経路だけで使い、Passport browser権限には昇格しない。
- `skip_api_key_verification`は機械API検証だけに作用し、Passport管理面を迂回しない。

## 廃止する入口

`POST /admin/api/login`、`GET /admin/auto-login`、oMLX署名session、remember-me TTLは存在しない。
main API keyをURL、HTML login form、browser session発行へ使わない。
