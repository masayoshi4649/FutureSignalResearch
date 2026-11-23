# 元三手法のmini連続再現

[試行93](../../study/00093_元三手法のmini連続再現と費用/README.md)の再現コード。元のD164_15/P164_06/U165_03を純戦略の公開APIから連続運転し、miniの整数配分と外費用を記録する。元判断は費用0を維持する対照で、新しい5分制限・外側技法・全玉利益追尾はまだ追加しない。

`adapter.go`・`types.go`・`adapter_test.go`はwork人工版と同じ本文。`input.go`は固定80の入力・SHA・CSV公開時刻・場時計の6関数を機械派生し、金融本文は複写しない。`replay.go`は同時刻の定時境界を後原行より先に処理し、Pの返済完了後だけUを生成する。Day2/Night4会計と各窓の原行が揃わなければ不完了にする。

miniは5+5尺度・各方向上限10・点価100円、microのgross対照は50+50・各方向上限100・点価10円。新規予約を含めて上限を検査する。旧Pが完全にflatになった後でUを作り、別adapter間の二重保有を防ぐ。

全元Signal/Targetsと、その次正常原行の全Fillを保存する。返済は実HoldIDに結び、`OnFill(Fee=0)`→`OnOrderDone`を一度だけ元会計へ通知する。返済予約分母を別実玉へ掛けるpool方式は使わない。StepResultの補助CloseNoticeを全件保存する代わりに、元Signal/Targets・実所有・配賦を正本とする。

外台帳はgross、片道手数料、仮定滑りを分ける。miniの主表示はgross−手数料38.5円/枚片道、別表示はさらに5pt/片道を費用控除する。約定値を二重に滑らせず、半円を保持する。正常BBO、次原行、所有、部分返済、終了残は独立に検査する。

実行環境はGo1.24.2/windows-amd64/CGO=0とPython3.14.3。Goの外部依存はgo.mod/go.sum、純戦略43項目は固定80台帳と試行93条件に記録する。兄弟SessionTradeExecuterを変更しない。

```powershell
Set-Location scripts/FAR元三手法のmini連続再現
go test -json ./...
go vet ./...
go build -o ../../work/93元連続再現/93.exe ./cmd/batch
Set-Location ../..
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR元三手法のmini連続再現/固定入力監査.py --out work/93元連続再現/入力前.json
& work/93元連続再現/93.exe --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --out work/93元連続再現/全54場
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR元三手法のmini連続再現/固定入力監査.py --before work/93元連続再現/入力前.json --out work/93元連続再現/入力後.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR元三手法のmini連続再現/集計と閲覧形式.py --run work/93元連続再現/全54場 --out work/93元連続再現/集計
```

保存先は新規フォルダを要求する。既存結果を上書きするコマンドはない。`--limit 2`は同じ固定54場の先頭2場を接続確認する用途で、総額照合の成功を意味しない。54場未満を最終集計へ渡すと拒否する。本文が欠けた窓、残玉・未約定を架空約定で補完しない。
