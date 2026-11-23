# FAR価格帯奪還と保持後再開

[試行92の計画](../../study/00092_価格帯奪還と保持後の独立再開/検証計画.md)に対応するオフライン研究コード。現在E0と独立i/p・H奪還・P更新・h保持・v再開の入口を、固定89E1/G1と比較する。新規は初回を除く15分、利益保護は原行ごと。売買は符号反転の同条件。

金融は`research89.Book`を直接importする。G1部分収穫・実確定益予算・費用後strict正での最低建値床、ATR等の共通保護を変更しない。元FAR参照は全原行運転し、その時点の方向・数量・親metadataを使う。90の床追加、91の再参加、逆方向変換は含めない。

## 構成

- `price.go`：公開済みの旧Recordから独立価格構造だけを計算する。旧k期限へ依存せず、v期限は供給可否だけへ適用する。
- `price_entry.go`：H0旧E1/H1現在E0＋独立vの全候補、三順位、受理根拠を別に保存する。
- `replay.go`、`input.go`、`batch.go`：固定89から接続だけを派生。旧Source・指標・金融の呼出順と種を維持する。
- `価格構造.py`：別実装の純価格器。全Record・定時snapshot・counterを照合する。
- `基準と保存判断の照合.py`：旧89H0全文、新全候補・供給・受理binding・利益出典を保存値から照合する。
- `原板監査.py`：固定89のG1・所有・費用・約定規範を一走査で再用する。
- `Source通知監査.py`：別の同一一走査で通知・所有・公開Close/TR・全callと新価格を照合する。
- `集計.py`：固定80の会計照合と旧玉診断を再用し、4会計・Viewer形式を保存する。
- `ネイティブ実行.ps1`：固定exe/入力/依存を確認し、別プロセスの終了コードと指紋を保存する。

新価格の成立と現在E0、旧E1、元Source、金融受理を別に記録する。H1が旧E1=falseでも成立する場合はそのまま保存し、旧E1への追加ANDと呼ばない。未知と既知不成立を分け、保有/処理中/新規を外側の未知分類へ上書きしない。

## 実行

Go 1.24.2、Python 3.14.3、PowerShell 7、CGO無効で確認する。実注文APIは使わない。リポジトリルートから実行する例：

```powershell
$env:CGO_ENABLED = '0'
go -C 'scripts/FAR価格帯奪還と保持後再開' test ./...
go -C 'scripts/FAR価格帯奪還と保持後再開' vet ./...
go -C 'scripts/FAR価格帯奪還と保持後再開' build -o '../../work/92Go正式化/92.exe' ./cmd/batch
pwsh -NoProfile -File 'scripts/FAR価格帯奪還と保持後再開/ネイティブ実行.ps1' -OutputRoot 'work/92実行'
```

Native wrapperは試行の`条件.json`に固定したexe/台帳/コード指紋を要求する。条件固定前には起動しない。再実行は既存の出力を上書きせず新しいwork領域を使う。

```powershell
& 'work/venvs/technical-tree/Scripts/python.exe' -B -X utf8 'scripts/FAR価格帯奪還と保持後再開/集計.py' --input 'work/92実行/全66場' --out 'work/92集計/成果物' --manifest 'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json'
& 'work/venvs/technical-tree/Scripts/python.exe' -B -X utf8 'scripts/FAR価格帯奪還と保持後再開/基準と保存判断の照合.py' --input 'work/92実行/全66場' --baseline 'work/89実行/全66場' --out 'work/92集計/保存照合.json'
& 'work/venvs/technical-tree/Scripts/python.exe' -B -X utf8 'scripts/FAR価格帯奪還と保持後再開/原板監査.py' --results 'work/92実行/全66場' --manifest 'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json' --out 'work/92集計/金融原板.json'
& 'work/venvs/technical-tree/Scripts/python.exe' -B -X utf8 'scripts/FAR価格帯奪還と保持後再開/Source通知監査.py' --results 'work/92実行/全66場' --manifest 'study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json' --out 'work/92集計/Source価格原板.json'
```

旧89の比較用JSONがなければ、旧89の固定コードと条件から別work領域へ再生成し、`--baseline`をその根へ向ける。原板は共用入力を参照し、複製しない。市場の原板監査は金融一走査＋Source/価格一走査の計二走査。

## 検査の範囲

Go人工は、鏡像・Pとbの違い・同値・最初v・p更新・H否定・継承i・900秒等号・未知/欠足/窓/EOF・深い保存コピー・全候補順位・永久seen・未来根拠の拒否を検査する。非0の買売を実TechnicalBank/eventBankと合成前史で通し、金融G1と全返済を確認する。

自然Sourceの全時計人工と、実指標＋手製Sourceの非0人工を分ける。後者のSource生成同値は0/空の未計測表示を維持する。原板の独立Close/TR検算を、全EMA/MACD/RSI/ATR前史の別実装とは呼ばない。指標の前史と元Source生成は固定数値器・種・全frame同値へ依存する。

`Source通知監査.inspect_one`の正式既定値とCLIは独立価格の全予定枠を必須にする。限定された旧監査器具の明示`require_price=False`だけは未計測表示とし、市場CLIへ露出しない。bool以外は拒否する。
