# Passport Cookie更新の統一

## 背景

管理面はPassportでservice sessionを検証していたが、検証で更新されたrolling expiryを
ブラウザCookieへ再中継していなかった。

## 変更

- Passport検証済みsessionをrequest stateへ置く既存契約を利用する。
- FastAPIの共通応答middlewareが、検証済み応答だけでPassportのexpiryをCookieへ再中継する。
- callbackが既にCookieを発行したときは重複して発行しない。

## 検証

- 管理認証テストで、検証済みsessionのCookieに`Max-Age`が付くことを確認する。
