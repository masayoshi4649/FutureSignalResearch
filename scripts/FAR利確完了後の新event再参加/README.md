# FAR利確完了後の新event再参加

[試行91](../../study/00091_利確完了後の新しい再開へ再参加/README.md)のオフライン比較。固定89のE1/G1を共通に、R0は恒久seenを維持、R1は直近の実参加が費用後利確完了した後の新しいp/r/k・別eventへ再参加する。初回除く15分新規と全原行の利益/損失保護を維持する。各D0/D1・264会計で、実注文は行わない。

## 実装と観測

- `opportunity.go`：公開済みE1の全pointを元Recordへ結ぶ。元参照とeventの機会を、実参加serialから分ける。
- `reentry_finance.go`・金融4本体：R1だけ現在参照索引/全実玉履歴/最新実参加/機会消費を持つ。全fill後の実全返済を記録し、前回利益を新玉のG1予算へ流用しない。R0は旧constructor/APIと全JSONを維持する。
- `types.go`・`replay.go`・`input.go`・`batch.go`：固定88入口と元FAR後期三手法を再用し、時計・種・Source・機会sidecar・受理結合を保存する。
- `集計.py`・`参加差の分解.py`：実玉/注文を一意に保持し、同参照の複数実参加を多重集合で対応する。同実出口差・同ref未一致・ref片側を全額へ足し戻す。役割は受理時assessmentから取得する。
- `原板監査.py`：各positionIDの価格・所有・G1・現在益・費用を独立に検査する。
- `Source通知監査.py`：別の原板一走査でSourceを現在世代だけへ作用させ、実fillから前回純額/完結Indexを再構成し、p/r/kの公開順へ結ぶ。CLIの市場監査は元Source全面同値の計測を必須とする。
- `基準と保存判断の照合.py`：旧89 E1G1全132Book、共有E1、元公開出典、受理履歴と機会消費を検査する。
- `再参加と初参加の機会差.py`：結果/取引診断/共有判断の3正本から、再参加の額と初参加差・前回実完了・占有の分母を記述する後段診断。
- `表示監査.py`・`図示.py`・`記録反映.py`：Viewer264資源、場末損益、13正本からの帳票を検査する。

両政策の金融内部modeはS0G1、Source政策はS、外入口はE1、利益配分はG1。R1専用状態を有効にしても、旧Bookの新tagは作らない。元Reference.Kind/Roleと、実役割の初参加/利確後再参加を区別する。

## 再生

Go 1.24.2 windows/amd64、CGO=0、Python 3.14.3。依存は`go.mod`と試行の条件指紋を参照する。

```powershell
Push-Location 'scripts/FAR利確完了後の新event再参加'
go test -count=1 ./...
go vet ./...
go build -trimpath -o '../../work/再現91.exe' ./cmd/batch
Pop-Location

& 'scripts/FAR利確完了後の新event再参加/ネイティブ実行.ps1' -OutputRoot 'work/91再現' -ValidateOnly
& 'scripts/FAR利確完了後の新event再参加/ネイティブ実行.ps1' -OutputRoot 'work/91再現'
```

buildはコンパイル確認。再生CLIは条件に指定した停止exeを使う。再build版を使う場合は条件と同じSHA256であることを確認し、両CLIへ`-ExecutablePath 'work/再現91.exe'`を追加する。出力先は新しいwork子領域にする。

帳票の13入力と証拠範囲は[再現補足](../../study/00091_利確完了後の新しい再開へ再参加/再現補足.md)へ記す。

## 保護と限界

現在単価の費用後含み益がstrict正なら、最低新規価格の床を即起動する。G1部分収穫・実確定益予算・ATR/125pt・確定3分失敗・Source/場末返済は共通。次板の約定や費用後黒字を保証する条件とは区別する。

全66場は既使用。ラージBBOによるmicro代理で、実通信・順番・板深さは再現しない。Source生成と指標前史は固定依存へ依拠し、原板監査による独立生成の再実装とは呼ばない。
