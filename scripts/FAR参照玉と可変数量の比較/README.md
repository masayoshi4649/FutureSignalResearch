# FAR参照玉と可変数量の比較

[試行87の計画](../../study/00087_FAR参照玉と可変数量の比較/検証計画.md)に対応する独立Goモジュール。元D164/P164/U165の選定Portfolioを全源原行で進め、15分時点の生存参照玉と現在数量を取得する。

外キーは`R0G1_D0/D1`（S）と`R1G1_D0/D1`（SC）。金融内部は`S0G1`、旧保持帯床・複合確認退出はoff。SCだけ固定84C0の最終Allowedと同方向を追加する。SへC0の未知、不成立、fresh保持帯条件を課さない。各Bookが全poolをAt/ID順で読み、独立したseen・占有で一枠一参照IDを選ぶ。

Source参照のKind、参照初期量、現在量、元親初回量、実要求量、実取得量、初参加要求/実初参加を分ける。元親量を現在残量から逆算しない。親量の未知と対象外はnullable値に適用・既知・理由を添えて記録する。元選定参照のKindを、さらに一段下のShadow通知Kindと呼ばない。

`source.go/source_test.go`は80からpackageと由来headerだけを変えたdriver。追加metadataはその読取層で、Sourceの計算・数量・予約を変えない。Replayは別インスタンスの固定80.Referenceも同じStep/Forceへ進め、metadata投影、新Frame、旧Frameの全poolをStep/Force/全定時で厳密比較する。順次canonical SHAと件数を保存し、全原行Frameを重複保存しない。これは元driver互換の検査であり、FAR戦略の独立再実装ではない。

通常原行はtimer→公開足→源Features→Source→実旧予約fill→当行SourceClose→G1。境界は実Force→SourceForce→専用OnReferenceで一度通知し、timerではfillしない。Sourceイベントは共有に一度、実側の比率適用・0丸め・取消・予約は会計別source_effectsへ残す。Last0行は源へ渡さず、直近snapshotだけを参照する。

```powershell
cd scripts/FAR参照玉と可変数量の比較
$env:CGO_ENABLED = '0'
go test ./... -count=1
go vet ./...
go build -o ../../work/87Go正式化/87.exe ./cmd/batch
```

非0金融接続人工は、新規絶対保存先を明示した場合だけ出力する。買売7状態の14場面に、共有定時/Sourceイベント/4会計、全物理raw_quotes、当行観測、Source初期seedを保存する。生存17・参照初期32・元親初回50と通知は手製で、FAR自然発生の原板証明ではない。固定80の実driver比較とC0旧判断の同値は別のReplay人工で検査する。Source部分予約と初回正益が重なる原行の建値床・収穫延期、部分fill後に現在gain10ptへ戻り費用後unitが非正のときの収穫非適格も分けて検査する。

```powershell
$env:FAR87_ARTIFICIAL_OUT = 'S:\GitHub\masayoshi4649\FutureSignalResearch\work\87人工の新規保存先'
go test -run '^TestExportArtificialSnapshots$' -count=1 -v
Remove-Item Env:FAR87_ARTIFICIAL_OUT
```

一括CLIは`--manifest`、`--out`が必須、`--workers`は1〜16（既定16）。出力根は新規に限る。全場の技法種を用意してから、Source/実会計が共有されない場単位で並列化する。市場再生は固定条件・依存指紋を確認して新規出力へ行う。

## ネイティブ実行と二つの原板監査

[ネイティブ実行.ps1](ネイティブ実行.ps1)は条件に含む全Go/依存・exe・台帳を照合し、非表示の別プロセスでnative終了コードを回収する。引数はArgumentListで分離し、stdout/stderrを非同期保存する。出力は本repoの新規work子領域に限定し、exe/条件/台帳の前後SHAと66保存件数を記録する。

```powershell
& scripts/FAR参照玉と可変数量の比較/ネイティブ実行.ps1 -OutputRoot work/87再現の新規領域 -ValidateOnly
```

ValidateOnlyはプロセス起動/出力dir作成0の読取確認。実再生を行う場合だけ外す。研究時の実行記録は`work/87実行/全66場_起動.json`と`全66場_完了.json`。固定87.exe/条件/台帳の前後一致とnative0/66保存を確認する。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR参照玉と可変数量の比較/集計.py --input work/87実行/全66場 --out work/87再現/成果物 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR参照玉と可変数量の比較/原板監査.py --results work/87実行/全66場 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --out work/87再現/原板監査.json --workers 16
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR参照玉と可変数量の比較/Source通知監査.py --results work/87実行/全66場 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --out work/87再現/Source通知監査.json --workers 16
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR参照玉と可変数量の比較/基準と保存判断の照合.py --input work/87実行/全66場 --baseline work/86実行/全66場 --out work/87再現/基準と保存判断の照合.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR参照玉と可変数量の比較/表示監査.py --catalog study/00087_FAR参照玉と可変数量の比較/成果物/一覧.resources.json --result study/00087_FAR参照玉と可変数量の比較/成果物/結果.json --out work/87再現/Viewer監査.json
```

全て新規先を指定する。G1原板は価格/所有/旧保護を一走査、Source通知はbadBBO/Last不良/timerを含む通知・取消・予約・0丸めを別の一走査で照合する。計二走査であり、元FAR生成器をPythonで独立再実装したものではない。保存監査のbaseline86は2442枠のC0/当時足気配だけで、132金融会計の全文同値を主張しない。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR参照玉と可変数量の比較/基準と保存判断の照合.py --self-test
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR参照玉と可変数量の比較/レポート.py --self-test
```

保存人工66場/2442枠/264会計は合成値。非0原板接続用人工の最新根は`work/87Go正式化/非0原板人工_最終2`で、14場面56会計・手製Source初期状態/通知を含み、自然発生を証明しない。保存非0人工のC0旧形逆投影も自己整合に限定し、固定86を別入力に取る正式監査と区別する。

## 13正本からの帳票

Rは13入力を全て明示し、費用・変数量・全pool/Source出典・三種gz canonical・二原板監査・Viewerを結ぶ。`--run`はREADME/設定結果専用領域/生成証拠を更新し、`--check`は保存値との同値だけを確認する。市場/売買/API利用は0。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR参照玉と可変数量の比較/レポート.py --check `
  --study study/00087_FAR参照玉と可変数量の比較 `
  --result study/00087_FAR参照玉と可変数量の比較/成果物/結果.json `
  --catalog study/00087_FAR参照玉と可変数量の比較/成果物/一覧.resources.json `
  --cash-audit study/00087_FAR参照玉と可変数量の比較/成果物/約定会計照合.json `
  --raw-audit study/00087_FAR参照玉と可変数量の比較/原板監査.json `
  --source-audit study/00087_FAR参照玉と可変数量の比較/Source通知監査.json `
  --viewer-audit study/00087_FAR参照玉と可変数量の比較/Viewer監査.json `
  --condition study/00087_FAR参照玉と可変数量の比較/条件.json `
  --input-reference study/00087_FAR参照玉と可変数量の比較/入力参照.json `
  --trades study/00087_FAR参照玉と可変数量の比較/成果物/取引診断.jsonl.gz `
  --grids study/00087_FAR参照玉と可変数量の比較/成果物/定時判断.jsonl.gz `
  --source-decisions study/00087_FAR参照玉と可変数量の比較/成果物/参照判断と通知効果.jsonl.gz `
  --entry-audit study/00087_FAR参照玉と可変数量の比較/基準と保存判断の照合.json `
  --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json
```

[再現補足](../../study/00087_FAR参照玉と可変数量の比較/再現補足.md)へ停止証拠・分類訂正・限界をまとめる。13入力に出口差診断を追加せず、既存玉/注文/Source出典からD02を直接導出する。別の全玉診断は[出口差診断](../../study/00087_FAR参照玉と可変数量の比較/出口差診断.md)と[小型JSON](../../study/00087_FAR参照玉と可変数量の比較/出口差診断.json)へ分ける。

## 出口差診断の再現

4入力・2新規出力の6Pathを全て明示する。Source予約を読むためsource-decisionsも必須。既存正式結果を上書きせず、新規work先へ再現する。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/FAR参照玉と可変数量の比較/出口差診断.py `
  --result study/00087_FAR参照玉と可変数量の比較/成果物/結果.json `
  --diagnostics study/00087_FAR参照玉と可変数量の比較/成果物/取引診断.jsonl.gz `
  --decisions study/00087_FAR参照玉と可変数量の比較/成果物/定時判断.jsonl.gz `
  --source-decisions study/00087_FAR参照玉と可変数量の比較/成果物/参照判断と通知効果.jsonl.gz `
  --out-json work/87出口差再現/出口差診断.json `
  --out-md work/87出口差再現/出口差診断.md
```

元参照の生存、現在取得の遅れ、元Kind/量/親small_initial、正益前後赤字、Source予約時の観測を全503玉で追える。原板/Source/G1/Viewerの完了証拠とは別で、市場・売買・閾値変更を実行しない。
