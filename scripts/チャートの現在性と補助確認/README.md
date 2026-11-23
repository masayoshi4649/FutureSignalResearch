# チャートの現在性と補助確認

[試行82](../../study/00082_チャートの現在性と補助確認/README.md)の検証コード。入口B0/B1×価格時計遅延0/1秒の4会計。会計・連続利益保護は固定81G1を変更せず参照する。3／15分足とその数値種は固定80を用い、直前3分足の結合だけwrapperで追加する。

数式・時計・費用の正本は[検証計画](../../study/00082_チャートの現在性と補助確認/検証計画.md)、コード指紋は[条件](../../study/00082_チャートの現在性と補助確認/条件.json)。元FAR三手法の部品を使った別の複合仮説で、元の売買列の再現ではない。

Go 1.24.2、Python 3.14.3。Go依存版はgo.mod/go.sumで固定。兄弟SessionTradeExecuterの純strategyと80／81モジュールは読取依存。実アプリ・自動発注は起動しない。

## 実行

ルートPowerShellから別の空出力へ再生する。既存結果を上書きせず、正式結果とは別の保存先で行う。全66場は既使用である。

```powershell
go -C scripts/チャートの現在性と補助確認 test ./...
go -C scripts/チャートの現在性と補助確認 vet ./...
New-Item -ItemType Directory -Path work/82再現 -Force | Out-Null
go -C scripts/チャートの現在性と補助確認 build -o ../../work/82再現/batch82.exe ./cmd/batch
& work/82再現/batch82.exe -manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json -out work/82再現/全66場 -workers 16
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/チャートの現在性と補助確認/集計.py --input work/82再現/全66場 --out work/82再現/成果物 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/チャートの現在性と補助確認/原板監査.py --results work/82再現/全66場 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --out work/82再現/原板監査.json --workers 16
```

Viewerの数値APIが利用可能なら、表示監査.pyへ`--catalog <一覧.resources.json> --result <結果.json> --out <新規監査.json> --workers 8`を指定する。帳票の全入力明示コマンドは試行README末尾を参照する。

## 保存と検査範囲

entry.goは当時のチャートと個別補助状態、chart.goは連続180秒の前足結合、replay.goは原行と定時の順序、batch.goは場単位16並列を担う。actual.goは複製せず81のBookを使う。原板監査.pyは固定81の独立所有・追尾・確定予算規範を4会計へ絞り、対象欠落・余計な会計も拒否する。

集計.pyは66保存結果から264会計・Viewer資源・圧縮診断を作る。入口間の同実新規は、policy接頭辞が異なるIDではなく、同一定時と方向で対応させ、実時刻・価格・枚数の一致を別検査する。短秒・OFIの4状態と失速別の件数は圧縮定時判断を正本としてレポート.pyが算出する。

原板監査は保存入口ATRから幅を再計算するが、ATR系列自体の独立実装照合、保存全玉峰／谷の個別全値照合は範囲外。ラージBBO代理価格でmicro全量が約定する仮定と、実通信・板深さ消費・約定順位・証拠金の未実証を区別する。CGO無効環境のためrace検査は未実施。
