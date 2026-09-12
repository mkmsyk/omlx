# 実装計画

## 目的

管理画面のAPIキー由来署名sessionを廃止し、Bunrin Passportが発行・検証・失効する
不透明service sessionだけを人間向けログインsessionとして使う。OpenAI互換APIの
Bearer API keyとcluster enrollment tokenは機械credentialとして分離したまま維持する。

## 手順

1. `http://localhost:8000` の厳密なloopback originをPassport clientとして登録する。
2. Passportのticket交換・session検証・失効を行う非永続clientを追加する。
3. `/admin`、callback、logoutをPassport導線へ置換し、API keyからbrowser sessionを
   発行するlogin・auto-loginを撤去する。
4. client secretを保護されたローカル設定へ配置し、導入済みoMLXを再起動する。

## 検証

- client/origin/secret/session不一致を拒否し、admin/sysopだけを許可する。
- 管理画面CookieはPassport tokenを中継するだけで、署名・TTL・ローカル保存を持たない。
- `pytest -m "not slow"`、導入済みGUIのlogin/callback/logout、API Bearer認証を確認する。
