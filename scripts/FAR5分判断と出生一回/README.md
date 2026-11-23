# 5分判断と出生一回の検証器

[試行95](../../study/00095_5分判断と開始30分見送り/README.md)の新規時計を比較する。固定93のmini Shadowは連続運転し、独立Actualは共通P0保護のままN/B5/B5Q×追加滑り0/5pt×要求後0/1価格秒の12口座とする。未参加や決済後の仮想利益を機会損失として評価しない。

Nは94と同じ出生時受理。B5は各new Signalを最初のstrict次5分格子へ一度割り当て、取得済み・残量正・返済予約0のSourceだけを、その時の残量と実側余力で制限して受理する。B5Qは同じ一枠に開始30分の見送りを追加する。失効を後の枠へ送らず、元source_addと実初参加も分ける。

`actual.go/actual_types.go`と金融人工は固定94から由来指紋付きで派生。`entry_grid.go`が新規受付だけを分離する。全Source取消/Fill/closeを連続で受け、Source側へ実退出や費用後損益を返さない。Nの既存金融fieldは94へ全比較し、除外はConfigのentry_timing/us_openと新しいentry_opportunities/grid_traces/grid_metricsだけである。

`input.go`は94と同じReader、`replay.go/grid_clock.go`が元Force→grid→後原行を実行する。gridは開始含む/終了含まない予定で、全受理board（TOPIX/NK・Last0を含む）の価格時計まで進める。Actor最新気配はLast正のNK原行だけで、gridで再時刻化・再投入・MTM・ATR・Fillを作らない。EOF後の未観測gridを呼ばず、未消費機会は失効とする。

`neutral_check.go`は94正式完了記録 `ccbc365b647c8225f5ef238f707778e9fbff01c5decba721c2843cb3f1972f80` と圧縮保存Nativeを照合し、N4口座の全既存金融fieldを比較する。Shadow全文は別に93へ照合する。元FAR全面同値=falseの留保を維持する。

Go 1.24.2・CGO無効、Python 3.14.3・標準ライブラリ。依存はgo.mod/go.sumと既存93/94・純戦略43の固定指紋を使う。実口座通信・注文APIの呼出しはない。出力は未作成フォルダだけとする。

```powershell
# 本moduleで実行する
go test ./...
go vet ./...
go build -o ../../work/95実行/95.exe ./cmd/batch
```

```powershell
# リポジトリルートで実行する。先頭接続だけは --limit 2 を明示する
& work/95実行/95.exe `
  --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json `
  --baseline study/00093_元三手法のmini連続再現と費用/成果物 `
  --baseline-proof study/00093_元三手法のmini連続再現と費用/完了記録.json `
  --protect-baseline study/00094_連続出生を固定した個別利益追尾/成果物 `
  --protect-proof study/00094_連続出生を固定した個別利益追尾/完了記録.json `
  --out work/95実行/正式54場
```

市場前の[固定条件](../../study/00095_5分判断と開始30分見送り/条件.json)と[設定と結果](../../study/00095_5分判断と開始30分見送り/設定と結果.md)を正本にする。3/15分の新しい現在チャートgate、反対方向の実新規、再参加、新しい損切り/追尾幅、事前有効な逆指値の執行モデルはこの版へ同時追加しない。
