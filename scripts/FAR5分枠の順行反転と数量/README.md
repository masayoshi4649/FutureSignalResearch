# 5分枠で現在の順行・反転と数量を判定する

[試行96](../../study/00096_5分枠の順行反転と現在数量/README.md)の再生コード。固定95の出生一枠・Source連続運転・P0金融を継承し、Source実取得/非closing・quiet・気配・片側余力を満たした候補だけを当枠の複合テクニカルへ渡す。旧95・純戦略・Sourceを変更しない。

`actual.go / actual_types.go / entry_grid.go / entry_gate.go`が金融境界、`technical_gate.go`が順行A・反転B・ABの純粋な採否、`chart_seeds.go / chart_context.go / replay.go`が独立した指標履歴と公開時計の接続である。G0は追加採否を使わない旧B5Q対照。全16口座は共通P0・mini各側10枚上限・指定手数料38.5円片道。新規と連続損益保護を別時計で進める。

`PrepareChartSeeds`は呼出側で選択済みの1〜54場だけを開始順に処理する。独立チャートは[複数尺度チャートの助走](../複数尺度チャートの助走/README.md)の公開APIを使用し、同限月の数値種だけを継承する。全QuoteはLast可用性とBBO品質を区別し、NativeのFeatures Indexと全NK受理Indexを混同しない。場間やEOF後に価格足を補完しない。

Rootは当原行の時計を上限にチャートのtimer/gridを先計算するが、各gridにはその時刻のsnapshotと、それまでに公開された最後3足だけを渡す。Currentは同時計rawより前の最後のNK実特徴であり、TOPIX更新や未来原行から自己特徴を作らない。Source Force→grid→原行の順は95のまま。`observed_clock`は公開をdrainした原行時計上限で、独立受信時刻を表さない。

G0四口座は完了指紋`b7df0d9f…`の旧95B5Q全文へ比較する。フィールド除外や時刻の投影は行わない。共通Shadowは固定93へ、場末チャートは助走側の同じ入力から得た公開snapshotへ比較する。

Go 1.24.2、CGO無効。リポジトリルートから以下を実行する。出力先は新規にする。

```powershell
Push-Location scripts/FAR5分枠の順行反転と数量
$env:CGO_ENABLED = '0'
go test ./...
go vet ./...
go build -o ../../work/96再現/96.exe ./cmd/batch
Pop-Location

& work/96再現/96.exe `
  --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json `
  --baseline study/00093_元三手法のmini連続再現と費用/成果物 `
  --baseline-proof study/00093_元三手法のmini連続再現と費用/完了記録.json `
  --clock-baseline study/00095_5分判断と開始30分見送り/成果物 `
  --clock-proof study/00095_5分判断と開始30分見送り/完了記録.json `
  --out work/96再現/Native
```

`--limit 2`は固定先頭2場の接続用。全54場の成功へ読み替えない。市場実行の前後は`固定入力監査.py --out ...`、後だけさらに`--before ...`を使い、324入力/純戦略/旧93〜95正本/新金融と助走コードを検査する。実口座の通信や注文APIは持たない。

評価は成立取引の実現収支、利益化前後の実損失、費用、DD・回数・数量。機会損失は計算しない。ラージBBOによるmini代理約定であり、真の受信順・実mini板流動性・未知期間安定性は未証明。今回の入口ATRは3分Wilder14、P0の追尾幅は旧native5分TR指数ATR12で、両者を混同しない。
