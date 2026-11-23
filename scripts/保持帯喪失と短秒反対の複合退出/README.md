# 保持帯喪失と短秒反対の複合退出

[試行86の計画](../../study/00086_保持帯喪失と短秒反対の複合退出/検証計画.md)を実行する独立Goモジュール。固定84C0の入口と85の共有定時snapshot・保持帯出典を維持し、金融内部は`S0G1`のまま使う。

外会計は`J0G1_D0`、`J1G1_D0`、`J0G1_D1`、`J1G1_D1`。`NewBook(...,false)`で旧保持帯床を無効にし、`SetConfirmEnabled`でJ1だけ複合退出を有効にする。費用・数量・15分時計・連続G1保護・原行順・足・強制返済は固定条件のまま。

退出の`OnQuote`へ当原行の`*CurrentEvidence`を必ず1引数明示する。Last不良行は`nil`、正常行は当行の源特徴を渡す。入口用に保持する`r.current`を退出で代用しない。Quote.Index、特徴のSourceIndex、物理SourceLineは別の番号である。現在特徴のTime/価格/物理行が同じqを指すことを検査する。

短秒は元`SelectedDay164Features.Short`で求めた気配中央のpt/秒。計算法を複製せず、保存された5/15秒窓のKnownと端点・実経過・速度を使う。正規の未知は旧G1保護を継続し、出典・既知窓の矛盾はerrorとする。新退出は全fill・旧保護・G1利確の後の未予約残量だけを要求し、次の適格正常原行で約定する。受理要求は回復後も撤回しない。

```powershell
cd scripts/保持帯喪失と短秒反対の複合退出
$env:CGO_ENABLED = '0'
go test ./...
go vet ./...
go build -o ../../work/86Go正式化/batch86.exe ./cmd/batch
```

人工保存は新規絶対パスを明示した場合だけ実行する。買売7状態の14場面に、新4会計、別運転の旧85H0二遅延、当行q/技法/currentを保存する。入口指標種・E08は手製であり、市場成果や独立原板監査の代替ではない。

```powershell
$env:FAR86_ARTIFICIAL_OUT = 'S:\GitHub\masayoshi4649\FutureSignalResearch\work\86人工の新規保存先'
go test -run '^TestExportArtificialSnapshots$' -count=1 -v
Remove-Item Env:FAR86_ARTIFICIAL_OUT
```

原板から短秒を再構成する接続人工は別に保存する。`TestExportRawArtificialSnapshots`は買売4状態の8場面と、`raw_quotes.json`の全28物理行を作る。11時計欠測行、8正常Source行、源へ渡さないLast0行1本、後続8行をすべて記録する。beforeは実Index8/SourceIndex7/物理20行で、以後も番号を区別する。短秒の手変更を含むAPI人工と用途を分ける。

```powershell
$env:FAR86_RAW_ARTIFICIAL_OUT = 'S:\GitHub\masayoshi4649\FutureSignalResearch\work\86原板人工の新規保存先'
go test -run '^TestExportRawArtificialSnapshots$' -count=1 -v
Remove-Item Env:FAR86_RAW_ARTIFICIAL_OUT
```

一括CLIは`--manifest`と`--out`が必須、`--workers`は1〜16（既定16）。出力根は新規である必要がある。全場の技法種を準備してから場単位で並列化する。市場再生は条件・依存・実行ファイルを固定し、前後指紋を残して行う。

## ネイティブ実行と保存後の照合

[ネイティブ実行.ps1](ネイティブ実行.ps1)は固定条件のexe/台帳/金融依存を確認し、非表示の別プロセスから終了コードを回収する。標準出力・標準エラーを非同期にファイルへ保存し、開始/終了PID・条件/exe/台帳の前後SHA・保存66件を作業領域へ残す。出力は本repoの新規work子領域だけに限定する。`-ValidateOnly`はプロセス起動・出力dir作成0の読取検査である。

```powershell
& scripts/保持帯喪失と短秒反対の複合退出/ネイティブ実行.ps1 -OutputRoot work/86再現の新規領域 -ValidateOnly
# 市場を再生する場合だけValidateOnlyを外す。既存の正式結果は上書きしない。
```

保存後のPython処理はrepoルートから実行する。下記は新規workへの再現例で、正式保存時の条件を変えない。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯喪失と短秒反対の複合退出/集計.py --input work/86実行/全66場 --out work/86再現/成果物 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯喪失と短秒反対の複合退出/原板監査.py --results work/86実行/全66場 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --out work/86再現/原板監査.json --workers 16
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯喪失と短秒反対の複合退出/基準と保存判断の照合.py --input work/86実行/全66場 --baseline work/85実行/全66場 --out work/86再現/基準と保存判断の照合.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯喪失と短秒反対の複合退出/表示監査.py --catalog study/00086_保持帯喪失と短秒反対の複合退出/成果物/一覧.resources.json --result study/00086_保持帯喪失と短秒反対の複合退出/成果物/結果.json --out work/86再現/Viewer監査.json
```

`表示監査.py`は明示したcatalog/resultとViewer APIを読む。再現先の別成果物を監査する場合は両パスも新規workへ合わせる。Viewerの実取引発注は行わない。各CLIの全必須引数は`--help`でも確認できる。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯喪失と短秒反対の複合退出/基準と保存判断の照合.py --self-test
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯喪失と短秒反対の複合退出/監査確認.py --fixtures work/86Go正式化/原板接続人工_最終 --out work/86再現/原板人工確認.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯喪失と短秒反対の複合退出/レポート.py --self-test
```

API境界人工14場面56会計（48実玉）は手製特徴と意図的未知/中立を含む。全物理行を持つ原板接続人工8場面32会計（24実玉）は別根へ保存し、短秒を手変更しない。どちらも市場の全25/49定時に対するcash_check完了ではない。保存監査の全66/2442/132人工も合成データであり、本物66場の完成検査と区別する。

## 11入力からの帳票

[レポート.py](レポート.py)は`--study`と`--result`、`--catalog`、`--cash-audit`、`--raw-audit`、`--viewer-audit`、`--condition`、`--input-reference`、`--manifest`、`--trades`、`--grids`、`--entry-audit`を全て明示する。生成前に全会計・原板・表示・保存canonical・停止依存を結ぶ。`--run`はREADME/設定結果専用マーカー/生成証拠を更新し、`--check`は同値だけを確認する。帳票自体の市場原板読取・新売買再生・API利用は0。

11入力の完全なPowerShell例と停止指紋は[試行86の再現補足](../../study/00086_保持帯喪失と短秒反対の複合退出/再現補足.md)に置く。J0の金融counter0/nullは観測offであり、両案の原板独立shadowと混ぜない。原板は短秒履歴準備＋旧規範/新複合退出の2走査で、巨大な全原行系列を正式保存しない。入口Shortは85共有snapshot全文同値、新退出のpostfill短秒だけ全正常残玉原行で独立再構成する。元FAR帯出生/EMA/ATR生成の独立再実装とはしない。

## 出口差診断の再現

[全玉の出口差診断](../../study/00086_保持帯喪失と短秒反対の複合退出/出口差診断.md)・[小型JSON正本](../../study/00086_保持帯喪失と短秒反対の複合退出/出口差診断.json)は完成済みの結果/gzを読む保存後診断。6個のPath引数を全て明示し、新規work出力へ再現する。既存正式正本は上書きしない。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/保持帯喪失と短秒反対の複合退出/出口差診断.py `
  --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json `
  --result study/00086_保持帯喪失と短秒反対の複合退出/成果物/結果.json `
  --trades study/00086_保持帯喪失と短秒反対の複合退出/成果物/取引診断.jsonl.gz `
  --grids study/00086_保持帯喪失と短秒反対の複合退出/成果物/定時判断.jsonl.gz `
  --out-json work/86出口差再現/出口差診断.json `
  --out-md work/86出口差再現/出口差診断.md
```

同実新規/取得変更/片側参加を正式集計へ結び、救った損失・失った勝ち・両赤字悪化・差0の全玉と正益前後を分ける。複合退出の実返済枚数は保存closed理由から数え、初回成立や旗・損益符号だけで推測しない。原板/保存判断/Viewer完成証拠を代替するものではなく、新売買・市場再生・閾値変更は0。
