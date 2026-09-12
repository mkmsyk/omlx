# oMLX Passport認証移行の検証記録

## 実装検証

- 認証・API key・accessibility・loggingのPython対象試験124件成功。
- 高速Python試験10,781件成功、32件skip、74件deselect。変更前からの数値精度・
  モデル互換・Hugging Face環境試験15件は失敗し、変更対象外であることを分離した。
- Swift全297件のうち既存Localization smoke 40件がcatalog sentinel欠落で失敗。
  変更対象のmenubar URL／pollerを含む選択試験28件は成功した。
- Release 0.6.4をbuildし、埋込PythonのMach-O 367件の署名を検査して導入した。

## 実経路検証

- `~/.omlx/passport-client.secret`はmode `0600`、Passport側の対応secretは
  `root:bunrin-passport`、mode `0640`であり、値は出力・文書・gitへ残していない。
- `/api/status`は無認証401、保存済みmain API keyによるBearerと`x-api-key`は200。
- 導入済みアプリの`Start Server`からbackendを起動し、loopback管理画面がPassport専用ログインを
  表示することを確認した。CTAを実際に押し、`client=omlx`、登録origin、callback先を持つ
  Passportのprovider選択画面へ到達した。
- 新規ブラウザに本人のPassport sessionが無いため、本人確認後のcallbackとlogoutは未実施。
