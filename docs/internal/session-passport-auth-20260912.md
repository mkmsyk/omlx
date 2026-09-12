# oMLX人間sessionのPassport一元化

## 背景

管理Web UIはmain API keyを入力またはURL queryへ載せ、oMLX自身が署名したCookieを発行していた。
Passportを唯一の人間向けsession発行・検証・失効元とし、機械API keyとの境界を明確にした。

## 変更

- 共通`floated_claim.passport_exchange` clientを固定commitで再利用した。
- Passport login、ticket callback、各要求validate、logout revokeへ管理画面を切り替えた。
- API key login、auto-login、ローカル署名token、remember-meを削除した。
- ネイティブアプリとmenubar pollerはCookieを作らず、main API keyを機械Bearerとして直接送る。
- menubarのWeb Dashboard URLからAPI keyを除き、`/admin`のPassport入口だけを開く。
- main API key、sub key、cluster enrollment tokenは機械credentialとして維持した。

## 検証

- 認証・API key・accessibility・loggingの対象Python試験124件が成功した。
- 高速Python試験は10,781件成功、32件skip、74件deselectだった。変更前からの数値精度・
  モデル互換・Hugging Face環境試験15件は失敗した。旧login CSSを前提にした1件は試験を現画面へ
  更新し、対象試験で成功を再確認した。
- Swift全試験は297件を実行できたが、既存のLocalization smoke 40件がcatalog sentinel欠落で失敗した。
  変更対象のmenubar URL／pollerを含む選択試験28件は成功した。
- Release 0.6.4をbuildし、埋込PythonのMach-O 367件の署名を検査して`/Applications/oMLX.app`へ
  配置した。Passport client secretは`~/.omlx/passport-client.secret`へmode `0600`で配置した。
- main API keyを機械credentialとして生成・保存し、値を表示せず、`/api/status`が無認証401、
  Bearerと`x-api-key`の双方で200になることを確認した。
- 導入済みアプリが開く`http://127.0.0.1:8000/admin`で、旧API key loginではなく
  「Bunrin Passportでログイン」だけを表示することを確認した。秘密配置前から稼働していた
  backendは進行中推論の完了と資源解放を待って正常終了させ、導入済みアプリの`Start Server`から
  再起動した。再起動後は未構成警告が消え、`client=omlx`、登録loopback origin、
  `/admin/dashboard` callbackを持つPassport画面まで実操作で到達した。
- API key作成前から起動していたネイティブアプリは古い空設定のため統計取得が401になった。
  メニューバーの正式な`Quit oMLX`から正常終了して再起動し、機械Bearerを再読込させた。
  配信統計は実データ、active model、server uptime、cache情報を表示し、401が消えたことを確認した。
- 新規ブラウザに本人のPassport sessionが無いため、本人確認後のcallbackとlogoutの実入力確認は
  行っていない。
