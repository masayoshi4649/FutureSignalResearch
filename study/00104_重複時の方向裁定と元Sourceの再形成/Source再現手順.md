# 104段階Aの再現

2026-11-09。ここではSourceを原板と確定足から再形成する。B5Q/LD10を適用する段階Bとは別である。先頭2場・全54場とも終了0。全54場の保存整理も成功した。AとBは別実績で確認し、Bの全54金融・保存も正常終了した。

## 固定したもの

- [Source条件](Source条件.json)：`05b8275a5c1abb60aab3402c617f62d5583852dacacce48e2b831430223ea266`。
- [Source実行前固定](Source実行前固定.json)：930コード/資料を指紋化。Go版・参照配置と実行物を固定。
- 実行物は `work/104Source再形成CLIの準備_版2/検査/Source準備.exe`、SHA256は `6b5f897e62f91a94fbe2e6b6a82e7d1855fe741f8a452753245c62672e1e5033`。
- [Source再現コード](Source再現コード.zip)：213コード/資料の本文、717のstdlib/toolchainの指紋参照、展開対応表。原板・確定足・旧Native・実行exeは重複収録しない。

ZIP内のrepo以下はrepoルートへ、外部以下は展開対応表の元位置へ対応する。Goはwindows/amd64の固定版と実体指紋を確認する。別配置や別Go版で再buildした実行物を同じ固定実行と呼ばず、新しいコード/実行物・条件で固定する。現在の実行物を無断で再buildして固定SHAを置き換えない。

固定80の入力台帳は原板・CSVへの共用参照。旧93の比較本文は条件内の元work位置を参照する。workを削除している場合は、旧93正式成果物の各場gzipを元位置へ同bytes展開できるか指紋で確認してから用いる。異なる内容で旧SHAを装わない。

[旧93参照の復元確認](検査/旧93参照の復元確認.json)では、正式gzip全54場をメモリ上で展開したbytesのSHAが、今回の比較本文参照と一致した。この復元確認作業自体では実際の復元書込や新Sourceの再実行は行っていない。今回Aのresult本文は別のserialized bytesで、旧93gzip展開SHAを今回Aの歴史出力SHAへ代用しない。[参照台帳](成果物/SourceA/旧93正式Native参照台帳.json)へ旧比較本文SHAと今回Aの3mode出力SHAを別々に残した。

## 実行順

repoルートで、既存成果物と重ならない新規出力先を使う。先頭2場と全54場は同じ条件・コード・実行物で実行する。

```powershell
& 'work/104Source再形成CLIの準備_版2/検査/Source準備.exe' `
  --condition 'study/00104_重複時の方向裁定と元Sourceの再形成/Source条件.json' `
  --condition-sha 05b8275a5c1abb60aab3402c617f62d5583852dacacce48e2b831430223ea266 `
  --stage first2 --out '<存在しない先頭2出力先>'

& 'work/104Source再形成CLIの準備_版2/検査/Source準備.exe' `
  --condition 'study/00104_重複時の方向裁定と元Sourceの再形成/Source条件.json' `
  --condition-sha 05b8275a5c1abb60aab3402c617f62d5583852dacacce48e2b831430223ea266 `
  --stage full54 --first2 '<同条件先頭2完了.jsonの絶対path>' `
  --first2-sha '<その実SHA256>' --out '<存在しない全54出力先>'
```

先頭2の本実績は[完了JSON](検査/Source先頭2場/完了.json)で、SHA256は `2dde982dc4c81ef45642ce110018657e5f7731317d6c01d053a4a28a1ef3dd3f`。全54実績は[完了JSON](検査/Source全54場/完了.json)、SHA256 `190719818d9a34f1cb1eb5836c5545d57cd581e468d168ae612bf1cf8b532fc9`。[保存確認](検査/Source全54場/保存会計の確認.json)はSHA256 `bea93cb50ca70eee6984515b742a0e3951ff1b77c1474674746bd6f4efca2b04`。出力先が違えば完了JSONに記録するpathも変わるため、再実行の完了SHAを古い値へ固定しない。

## 成功と確認範囲

先頭2では `success=true/sessions=2/cases=6/unchanged=true`、全54では `sessions=54/cases=162` を要求する。全caseの出力SHA、旧/既定両modeの旧93全構造一致、全Source LedgerのFinished/Complete・残/予約0、入力とコードの前後一致を確認する。Dayは2商品各D、Nightは2商品各P/Uなので、全54のSource会計は486である。

SourceRecordの圧縮JSONLは全Step/Forceを含む。Scalar11を元Source生成に代用しない。SourceRecordだけから重複条件の実評価回数や注文動機を観測したとは言えず、通知が同じでも重複域が無かったとは推定しない。

全54の保存集計は[結果](成果物/SourceA/結果.json)（SHA256 `a302ae2bd73ecb07fb1963424dc392f6aace0aec5c7915135c9bba2ca446021c`）と[要約](成果物/SourceA/要約.md)。legacy/defaultは旧93全構造108case/324会計で除外0一致。今回Aの各場の3mode result本文SHAとrecords圧縮SHAも同じだったが、重複条件の実評価回数は未計測、変更の影響未観測という範囲に留める。

段階Bの接続/金融/保存は[再現手順](再現手順.md)へ分離した。実先頭2結合はlegacy/defaultの全通知と103最終16冊×4case＝64Bookを全JSONで照合済み。全原行の全時点Snapshot比較へ言い換えず、Sourceの自然形成と金融保護の成功を混ぜない。主Bは全54金融・保存で432会計/旧対照216会計・除外0が成功。Aの元連続会計とBの定時LD10後の成績は別表とする。
