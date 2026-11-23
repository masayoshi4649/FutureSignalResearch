# 第157試行の再現

[再現コード.zip](再現コード.zip)は元の`work/`相対配置を保持する。価格テープ・出口FSM・到達診断の3 Go module、Root集計/検算/CSV出力、固定入口抽出のschema補助、作者人工/停止票、集計と到達の独立票を含む。ZIP内`manifest.json`が全格納path/bytes/SHA/CRC・由来・依存の正本。[保存確認](../検査/再現コードの保存確認.json)にZIP物理SHAと復元検査を記録する。旧研究・入口・価格・固定Sourceを変更した保存ではない。

## 入力と環境

固定入口は[恒久入力](../../../inputs/00157_固定入口と価格経路/固定入口入力.json)（SHA `eabf9819351ef77fec44a7a132a8df13fd8a3aee7c3be6d87ac81dabe34ce279`）。153U15全93と152U0全831所属、共通87を含む837物理case/924所属で、別の152U1ではない。[共通価格テープ](../../../inputs/00157_固定入口と価格経路/価格テープ/価格テープの確認.json)を再利用する。各場の相対gzip/SHA/解凍SHA/CRC/品質/全取得Quoteはそのmanifestに束縛される。

元の153/152選択、148固定取得・保存観測、共用Rawは元恒久先を参照し、ZIPへ重複格納していない。旧入力の完全な指紋はZIP内の`入力を抽出する.py`と`schemaを確認する.py`にある。価格テープや成果物・CSV・exe・node_modules・cacheもコードZIPには含めない。固定入力を使えば抽出の再実行は不要。旧対照抽出時だけ148保存観測を使う。

- Go 1.24.2 windows/amd64。外部Goパッケージ不要。`exitreplay157`と`exitdistance157`は隣の`pricetape157`を相対replaceする。
- Root実行はPython 3.14.3/NumPy 2.5.4（`work/複合テクニカル学習環境/Scripts/python.exe`）。配列検算と場bootstrapがNumPyを使う。集計独立照合はPython標準ライブラリ/Fractionだけで、NumPyは使わない。調査shellに存在した2.5.3とは区別する。
- CSV作者の実行票はNode v24.22.1。調査shellのv24.14.0とは別。提供SDK `@oai/artifact-tool` 2.8.129（private、skia-canvasと@oai/walnut依存）をimport解決できる環境が必要。SDK/runtime/フォントをZIPへコピーせず、実環境のpackage metadata指紋をmanifestへ記録した。元環境はCSVコードの隣のnode_modules junctionから提供SDKを解決した。

## 再現手順

既存固定workを上書きせず、別checkoutのリポジトリルートへZIPを展開する。恒久`inputs/`・`study/`と共用Raw参照を解決する。ZIP内には固定時の実行条件と設定表を元相対位置で保存し、現在の結果追記後文書を事前固定へ読み替えない。

各moduleで`go test ./...`、`go vet ./...`を行い、価格テープは`./cmd/run`、出口は`./cmd/exits`、到達は`./cmd/diagnose`を新規先へbuildする。各作者の準備スクリプトは保存票への上書きを拒否するので、復元時は人工を直接実行し再現票を別先へ保存する。

既存の共通テープを使う最小再生：

```powershell
& '<出口exe>' --input '<固定入口.json>' --input-sha256 '<固定SHA>' `
  --manifest '<価格テープの確認.json>' --manifest-sha256 '<固定SHA>' `
  --spec '<固定時実行条件.md>' --spec-sha256 '<固定SHA>' --output '<新規出口結果.json.gz>'
& '<到達exe>' --fixed-input '<固定入口.json>' --fixed-input-sha256 '<固定SHA>' `
  --tape-manifest '<価格テープの確認.json>' --tape-manifest-sha256 '<固定SHA>' `
  --conditions '<固定時実行条件.md>' --conditions-sha256 '<固定SHA>' `
  --output-dir '<新規到達先>' --execute-after-root
```

Rawからの全再現が必要な場合だけ、価格テープexeの`--input/--sha256/--output-dir/--workers 8/--execute-after-root-freeze`で未作成出力先へ1回生成する。元Rawを改変せず、全CRC/SHA/stat/品質確認前のpartialを完成テープとして使わない。

型付き表は保存JSONから再生成でき、巨大な型付き表の副本をZIPへ入れる必要はない。以下はリポジトリルートで、新規の作業出力を指定する。

```powershell
python -X utf8 'work/157集計と閲覧/集計する.py' '<出口結果.json.gz>' '<新規出口型付き表.json>'
python -X utf8 'work/157集計と閲覧/四表をまとめる.py' '<出口型付き表.json>' '<到達距離の集計.json>' '<新規CSV四表入力.json>'
python -X utf8 'work/157独立検査/出口を配列で検算する.py' '<固定入口.json>' '<manifest.json>' '<出口結果.json.gz>' '<新規出口独立票.json>'
python -X utf8 'work/157独立検査/旧対照を抽出する.py' '<固定入口.json>' '<新規旧対照.json.gz>'
python -X utf8 'work/157独立検査/旧対照を経路で照合する.py' '<固定入口.json>' '<manifest.json>' '<旧対照.json.gz>' '<新規旧照合票.json>'
node 'work/157集計と閲覧/CSVへ出力する.mjs' '<CSV四表入力.json>' '<outputs内の新規出力先>'
python -X utf8 'work/157集計と閲覧/CSVを独立再読する.py' '<CSV四表入力.json>' '<CSV出力先>' '<新規再読票.json>'
```

作成器は既存CSVへ上書きせず、4CSV/支援PNGを作る。新しいCSV生成は上記の再現操作であり、元の作成marker回数を増やした履歴へ混ぜない。元と別pathで再生したJSONは由来の絶対pathメタデータが変わり得るので、その差を値/状態/型付き全セルの一致と分ける。保存済み正本同士の再確認にはZIP内の集計独立照合器を使用できる。同器は認証済み元2SHAを明示検査する仕様である。

## CSV作成時と表示修正後のコード

[初回作成票](../../../outputs/01a1889f-f2af-7943-a047-543275ee9ed2/00157_出口比較/作成確認.json)の出力器SHAは`e43cbfd9b25aa6f699f9c57d805449c66d309331de5388971eb52b60c1a69e13`。ZIPへ保存した現版は`5cdd2f4f32fe3f94665637f72fcd33ff8f1e5a997d4fd4dc3d8a97a031439383`であり、初回と同じbytesの作者コードだったとは記さない。現版には`--表示だけ修正`分岐があり、125後の伸長の列幅だけを修正し、CSV既存bytesと生成予定bytesのSHA一致を要求してPNGを再作成する。

[表示修正票](../../../outputs/01a1889f-f2af-7943-a047-543275ee9ed2/00157_出口比較/表示修正の確認.json)は現版SHAに一致し、[4CSV全セル独立再読](../../../outputs/01a1889f-f2af-7943-a047-543275ee9ed2/00157_出口比較/独立再読.json)は270,485セルを照合した。保存処理でも4CSVの物理SHAが初回作成票どおりであることを確認した。新たなCSVや金融結果の生成、入口選び直しではない。

## 検査の役割

[出口集計の独立確認](../検査/出口集計の独立確認.json)は元80,352出口状態から576要約/14,016場行、261,312セルをRoot集計関数なしで照合した。担当者は出口FSM作者なので、FSM自体の別算術を意味せず、Rootの[配列検算](../検査/出口の独立配列検算.json)と区別する。[到達の独立確認](../検査/到達距離と条件付き先着の独立確認.json)は837×2窓の12幅/24条件と前後集計、965,431末端を確認した。到達のOHLC/MFE/MAE数値はその独立票の対象外で、人工と作者実装の範囲を維持する。

未見2場・旧156・旧試行は変更せず、再現資料の保存後に新しい探索や政策を追加しない。
