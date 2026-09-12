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
- 導入済みアプリからのbrowser login・callback・logout、機械Bearer動作、配備版は配備後に追記する。
