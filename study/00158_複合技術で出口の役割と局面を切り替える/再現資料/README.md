# 第158試行の再現

[再現コード.zip](再現コード.zip)は小さいコード・人工・固定票だけを元の`work/`相対配置で保存する。[保存確認](../検査/再現コードの保存確認.json)とZIP内`manifest.json`が、全格納bytes/SHA/CRC・依存・由来の正本。Rootの集計器を含む停止済み158源だけを対象とし、159のコードやデータは含めない。

## 固定した入力と結果

|対象|SHA256|再利用先|
|---|---|---|
|実行条件|`f32efc55b5fc114534b601b981e3c961d12037e5b5462d71769634402789cc17`|[実行条件](../実行条件.md)|
|19政策book|`e7e8ef7fd2a714b145cbb7c0fe280a391804247ec5a88db872f88a1be45734c7`|[候補の固定](../候補の固定.json)|
|147 canonical OHLCV gzip|`b99c49f06fe7e2306e59733b1cff26e3bb351f64edee220c98bc30b62c016d77`|[147恒久入力](../../../inputs/00147_中位価格位置と実体回復/Sourceの出生と取得.json.gz)|
|122/118公表cache|`6a6cd13dfd00c9669b522e3c3c8e06a4066766f6075786f64d8c0feeb45513ec`|177,709,174 bytes。`work/122全場入力/入力.json`を[122正式再現手順](../../00122_E0固定条件を全セッションで検証する/再現資料/再現手順.md)から復元する|
|157固定入口|`eabf9819351ef77fec44a7a132a8df13fd8a3aee7c3be6d87ac81dabe34ce279`|[837物理case・924所属](../../../inputs/00157_固定入口と価格経路/固定入口入力.json)|
|157価格manifest|`05b703b99f4a444d0394aa40d5efd2c5ba9e7909f1a3261271143c239affb723`|[価格テープ](../../../inputs/00157_固定入口と価格経路/価格テープ/価格テープの確認.json)|
|158特徴manifest|`a6dce32eb35102d95f44647d0a10811bf13ed6e36f46b08ef0956c52bb783d11`|[73場の特徴](../../../inputs/00158_複合技術特徴/特徴/特徴の確認.json)|
|158金融前固定|`99566cb2df4ae53f733887da738947200e227edbafae134bfd119daae0678d7f`|[金融前固定](../検査/金融前固定.json)|
|158出口結果gzip|`70a4c3178206bbb3c8641901c7515f2121da11c28403b88c3f8e6f93cc0baa6c`|[結果正本](../成果物/出口結果.json.gz)。物理7,057,093 bytes・解凍337,535,982 bytes|
|Root型付き三表|`506c8465150673f6ecfeb6d1263d08b4c6809652bcfdcfd94e342db08e3736f1`|Root生成物`work/158集計と閲覧/型付き表.json`。結果正本と同梱コードから再生成する|
|157対照結果gzip|`58bf2b448c7ca465e3e9f20ab78f10106d6a2c7312784d939acd7ffff22d2338`|[157結果](../../00157_固定入口の到達距離と追尾退出を比較する/成果物/出口結果.json.gz)|

価格テープ、147/122の大入力、特徴約93MB、出口結果、型付き表、CSV、画像、exe、node_modules、cacheはZIPへ含めない。小さいmanifestとSHAだけを束縛する。原板をもう一度取得・複製する必要はない。147 gzipの解凍SHAは`d42d25ec0fe41e8358c1227fd71b4377ffa90c96a8cf582f1ee4537ebf455d63`。

## コードと環境

新`features158`・`technicalexit158`、旧依存`entryrules118`・`pricetape157`・`exitreplay157`のGo5モジュールを隣接する元配置で同梱する。`go.mod replace`を変えずにビルドできる。旧157/118の原本を編集したものではなく、格納bytesは作者停止票と照合する。

- Go 1.24.2 windows/amd64。特徴の当時exe SHAは`83014dc2470bbd0e85f3e9ef4b4027db9f8246ca809a30a5943efdc17d2db2de`、出口exeは`068659b96bd8818f7c81ff89fa94a2469737dd888eb709af415850a7b1a1be50`。exeは格納せず、新環境でのbuild SHAが違えば新しい実行物として記録する。
- Python 3.14.3。Root集計と結果独立確認は標準ライブラリのみ。特徴の別算術確認はNumPy 2.5.3を使った。同じGo特徴作者による別言語算術であり、人的独立とは呼ばない。旧157でRootが使用したNumPy 2.5.4と混同しない。
- CSV作者は提供SDK環境のNode v24.22.1、`@oai/artifact-tool` 2.8.129。調査shellのNode v24.14.0とは別。SDKはprivate提供物で、skia-canvas/`@oai/walnut`を含め実環境でimport可能にする。package metadataとSHAをmanifestへ記録し、SDK・runtime・フォントを複写しない。

ZIPを別checkoutのルートへ展開し、恒久`inputs/`と`study/`を元相対位置で利用する。元JSONに含まれる絶対pathは当時の由来であり、今回それを書き換えて同一物理SHAと称さない。再生成先・実行時計・環境が違う結果は、元bytes一致と値・状態一致を分けて扱う。

## 最小再現

まず各モジュールで`go test -count=1 ./...`、`go vet ./...`、`go build ./...`を実行する。ZIP復元時の保存確認でも人工とbuildだけを実行し、自然生成・金融・CSVは再実行していない。

```powershell
Set-Location work/158技術特徴
go build -o '<新規feature158.exe>' ./cmd/run
Set-Location ../158技術出口
go build -o '<新規技術出口.exe>' ./cmd/replay
```

既存73場特徴を使う場合、特徴生成は不要。特徴から作り直す場合だけ、122正式手順でcacheを復元し、以下をリポジトリルートで新規先へ実行する。

```powershell
& '<feature158.exe>' --allow-natural `
  --parent 'inputs/00147_中位価格位置と実体回復/Sourceの出生と取得.json.gz' `
  --background 'work/122全場入力/入力.json' `
  --spec 'study/00158_複合技術で出口の役割と局面を切り替える/実行条件.md' `
  --source-dir '<復元したwork/158技術特徴の絶対path>' --output-dir '<未作成特徴先>'
```

このCLIは親の物理/解凍SHA、cache/条件SHAを既定値へ束縛し、全gzipのCRC/末尾/前後statを確認する。再生成したmanifestはSourceの絶対pathが違うため物理SHAが変わり得る。既存正本と同じSHAを仮定して後段へ渡さない。

保存特徴と157テープを使う出口再生：

```powershell
& '<技術出口.exe>' `
  --input 'inputs/00157_固定入口と価格経路/固定入口入力.json' --input-sha256 '<固定入口SHA>' `
  --manifest 'inputs/00157_固定入口と価格経路/価格テープ/価格テープの確認.json' --manifest-sha256 '<価格manifestSHA>' `
  --features 'inputs/00158_複合技術特徴/特徴/特徴の確認.json' --features-sha256 '<特徴manifestSHA>' `
  --spec 'study/00158_複合技術で出口の役割と局面を切り替える/実行条件.md' --spec-sha256 '<条件SHA>' `
  --policies 'study/00158_複合技術で出口の役割と局面を切り替える/候補の固定.json' --policies-sha256 '<bookSHA>' `
  --execute-after-f0 'study/00158_複合技術で出口の役割と局面を切り替える/検査/金融前固定.json' --f0-sha256 '<金融前固定SHA>' `
  --output '<未作成出口結果.json.gz>'
```

結果JSONから三表と事後の対照差内訳を再生成する。型付き表自体をコードZIPへ重複保存しない。

```powershell
python -X utf8 'work/158集計と閲覧/集計する.py' '<出口結果.json.gz>' '<新規型付き表.json>'
python -X utf8 'work/158集計と閲覧/対照差を分解する.py' '<出口結果.json.gz>' '<新規内訳.json>'
node 'work/158集計と閲覧/CSVへ出力する.mjs' '<型付き表.json>' '<outputs内の未作成先>'
python -X utf8 'work/158集計と閲覧/CSVを独立再読する.py' '<型付き表.json>' '<CSV出力先>' '<新規再読票.json>'
```

CSV生成は提供SDKが必要で、既存CSVへの上書きを拒否する。CSV作成用現版Sourceを格納し、元CSV出力やmarker回数を再現作業によって書き換えない。現在のSource SHAはZIP内manifestを参照する。

## 検査と文書の境界

[出口結果と集計の独立確認](../検査/出口結果と集計の独立確認.json)はSHA `eb34222e5e8e86f8cc7c829f36f831b5426716698b9f75bea78a87eb2f1fbb50`。127,224状態の保存Quote算術、固定3対照20,088状態の全旧key、912要約/22,192場/38順位の439,280セルをRoot集計関数なしで一致確認した。原テープの「最初正常fill」や全gap、技術式を全原行で別再生した証明とは区別する。

[特徴の別算術検算](../検査/特徴の別算術検算.json)はSHA `84575410f20bf8d521b87a4f4fc3b74ce68bc9862992dad50b443521fdf78e2f`。主要68列の2,931,412セルと全149列6,038,821値の時計・TTL・refsを確認した。同一作者のGo対Python算術で、ST/SAR/CK自然数式6列・MTF保存値の再計算は対象外。別の作者人工・静的修正確認の範囲を維持する。NumPy scalar保存型の初回停止履歴も小票として保持する。

設定表はV8の63手法×9尺度＝567セル。今回保存時にまだ「準備中」だった[設定表](../設定と結果.md)の原文をZIP内の元相対pathへ退避した（SHA `ae74b8a87342a3bf14d24c83369bcf3aa7c1a49a759cac08b801acf58e55bc0a`）。これは結果追記前の保存時現物であり、そのSHAがF0へ事前固定されていたと遡及しない。現在の正式設定表はRootが結果を追記する版で、退避原文と区別する。元の条件生成器も保存するが、既存正式V8/book/設定表へ再実行して上書きしない。

教材7文書と外部調査は[調査と候補](../調査と候補.md)および正式`docs/technical-analysis/`へ保存済みなので、コードZIPへ全件転記しない。旧研究・追加2場・159・新条件探索を今回の保存へ混ぜない。
