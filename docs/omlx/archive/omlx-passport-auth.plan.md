# oMLX Passport認証移行計画（完了）

## 目的

管理画面のAPI key由来署名sessionを廃止し、Bunrin Passportが発行・検証・失効する
不透明service sessionだけを人間向けログインsessionとして使う。OpenAI互換APIの
Bearer API keyとcluster enrollment tokenは機械credentialとして分離したまま維持する。

## 実施内容

1. `http://localhost:8000`の厳密なloopback originをPassport clientとして登録した。
2. 固定revisionの共有clientでticket交換・session検証・失効を実装した。
3. `/admin`、callback、logoutをPassport導線へ置換し、API keyからbrowser sessionを
   発行するlogin・auto-loginを撤去した。
4. client secretをmode `0600`のローカル設定へ配置し、Release 0.6.4を導入した。

## 完了条件

- client/origin/secret/session不一致を拒否し、admin/sysopだけを許可する。
- 管理画面CookieはPassport tokenを中継するだけで、署名・TTL・ローカル保存を持たない。
- Python対象試験、Swift対象試験、導入済みGUI、機械Bearer認証を確認する。
