# 固定B候補の状態照合

固定97の主実取得302候補について、要求時の公開Contextを固定96の `AssessTechnicalGate(input,candidate,"B")` へ渡す後段診断。金融・Source更新・損益計算は行わない。正式成果物は[共通知見](../../docs/議論/反転候補の不成立を距離と鮮度へ分ける.md)と[3 JSON](../../docs/議論/検討資料/反転Bの2候補/計画.json)にある。

## 由来と版

2026-11-08に `work/99B不成立の内訳` の4ファイルを本文同体で保存した。相対依存の解決先は同じで、go.modも書き換えていない。査定数学は固定96をimport再用し、複写していない。

|ファイル|SHA256|
|---|---|
|main.go|a3035094f74a70dcfa85c2965f3e8d45d37c1c7a616f7de80ed012fafaf34611|
|main_test.go|01d353c199095f27cc87a4fa7d8d8da0ac02c8bac364fc62a4a535fae79f9523|
|go.mod|2ba1ec4247a821efbca0c5224ab9928ebaa0b039a24f47d2b74313482b0872e8|
|go.sum|34914b5514bc74e18646c8237e64c9dbe985dd2dade86bbfe399bf749685a074|
|固定96 technical_gate.go|3ba3c2c8d5b67635b9f2edab076ec9cce9785fea090e8ba87191a65142985fbf|
|追加 cmd/project-index/main.go|07c6e72d6804cd8f50e15fc1bd045fdc79d5860c18e538510fde381f0eaf8bd9|
|追加 projection_test.go|7194c849e2490b2b2553821c2506bf416ea390bd336c97933bf1c80458831fe8|

元の計画SHAは `0332fb19ee61091fcd9d7126d0224dbca9c0654b8669960b38c6dea4e3005fa3`。54 gzipとコード、既存索引を先固定した後に純査定している。入力型は損益・marks・u群・退出値を持たない。他口座の本体はデコードせず、主実入口に対応する要求機会・ChartGrid・保存AB査定だけを解釈する。

追加の `cmd/project-index/main.go` は、元372613版のJSONから再現に必要な小型索引だけを作る。`projection_test.go` はそのGo型・302一意・版を確認し、Nativeを読まない。査定本体4ファイルの同体性は維持する。

## 再現CLI

リポジトリルートのPowerShellから実行する。検査は人工JSONだけを使い、市場を読まない。Go/module版はgo.modとgo.sumを参照する。

```powershell
New-Item -ItemType Directory -Force -Path 'work/99B正式化' | Out-Null
Push-Location 'scripts/FAR反転候補の状態照合'
go test -mod=readonly ./...
go vet -mod=readonly ./...
go build -mod=readonly -o '../../work/99B正式化/B純査定.exe' .
Pop-Location
```

以下は元の保存54場に対する**純査定を再度行うときだけ**のCLI。正式化時には実行していない。出力先は既存ファイルを拒否するため、新規フォルダを用意する。元実行の計画とは別の[再現用計画](../../docs/議論/検討資料/反転Bの2候補/再現用計画.json)を使う。

```powershell
New-Item -ItemType Directory -Path 'work/99B再照合' -ErrorAction Stop
& 'work/99B正式化/B純査定.exe' `
  --plan 'docs/議論/検討資料/反転Bの2候補/再現用計画.json' `
  --out 'work/99B再照合/結果.json'
```

## 元実行と再現用計画の区別

元の計画・結果・確認3 JSONは当時の本文同体で保存した。元計画をそのまま実行するには当時のwork索引/helper/exeが必要であり、この履歴は変更しない。

別途[再現用入口索引](../../docs/議論/検討資料/反転Bの2候補/再現用入口索引.json)に、302件のID/時刻/Snapshot/20文字のcheck状態、check順、54本文SHAだけを保存した。損益・u群・check本文は含まない。元JSON全体のSHA `37261350b06e5abe86622d7ec3d05b7bfaea3c11372be7817d62102b0a505676` を確認して抽出し、小型索引のSHAは `18d04d4970950e519aa00d9f02720d94cec4b5845ad4446682deb81bb7322b1d` となる。射影のため元ファイルとは異なる指紋であり、同体と偽装しない。

再現用計画は、この小型索引と正式codeを明示参照するので、元work本体の復元は不要。索引中の `work/97実行/正式54場/*.json` は元本文SHAの検索キーで、実際にそのファイルを開く処理ではない。正式54 gzipを読み、その解凍本文へ結ぶ。既存の査定本体・母集合選択・式は同じだが、**この再現用計画でのNative純走査は未実行**であり、元実行の成功証拠とは区別する。Go型への構文確認と302 ID/時刻/状態の一意性だけを確認した。

当時の絶対rootとSource/moduleの相対配置は留保する。別場所で使う場合は再現用計画の複製へroot等の版変更を明示し、元計画や過去の実行証拠を書き換えない。全302のContext・check本文や元508KB索引の複製は追加していない。

結果は302の母集合指紋と対象2件の全17check・必要な当時値に限定する。旧Bの本名・既知否定優先/未知の規則を維持し、閾値緩和、新戦略成績、機会損失、退出後価格を評価しない。
