# 現在の価格応答と数量確認

[試行84](../../study/00084_現在の価格応答と数量確認/検証計画.md)のGo検証コード。固定82B1をA0とし、C0はfresh両気配帯維持と反対圧力解消、C1は更にfresh同価格数量支持を必要とする。MA/MACD/RSI/ATRと旧個別反対拒否・失速時確認を削らない。

金融実装を複写せず、全6会計で固定`far83.Book(S0G1)`を同じ型のまま使う。100micro、往復122円/枚、主0秒・追加価格時計1秒、初回除く15分新規と連続利益保護を維持する。数量は研究尺度であり推奨枚数ではない。

## 保存境界

外側のBookキーは`A0G1_D0/C0G1_D0/C1G1_D0`及びD1。内部の`book.mode`・注文/約定ID・`trades.method_id`は全てS0G1のまま保持する。照合や表示で外側キーを外すと複数会計を混同するため、利用側は外側入口も必ず結び付ける。

候補は旧B1の集約scalarだけを追加入口の採否へ写して、旧`Candidate`を呼ぶ。候補ID・Source・Ownerは旧B1の形式。A0の候補全値と会計全値は、別運転した旧83S0G1と同値を必要とする。

一予定時刻にGridを一つ保存する。旧83の全B1snapshotは`decision`へ一度だけ置く。旧`entry_policy=B1`、topの`candidate_accepted`はA0基準値を保持する。

- `policies.A0/C0/C1`：最終allowed/side/role/reason/required_unknown/directions/candidate_accepted。
- 各direction：side/allowed/role/reason/required_unknown/added_checks。旧全チェックや全Evidenceは再保存しない。
- A0のadded_checksは空。C0は現在価格帯・反対圧力、C1は末尾に同価格数量支持を加える。追加groupは「追加必須」。
- `structure_anchor`は旧83と同じ当時確定EMAのmetadataを保存するが、S0の金融床は構造inactiveのまま。

純入口が未知又は不成立なら空frameを固定Bookへ渡す。純未知/不成立はpolicies側に保存し、Bookの旧「待ち」等の分類を書き換えない。候補供給と、保有・処理中による実注文の不採用は区別する。

## 型・チェック検査

`Refine`は旧B1の公開型、二方向順序、全チェックのgroup/ID/順序、Known/Passed、補助との結合、旧採否と集約を検査する。欠落・重複・余剰・schema差・未知成立・論理破損はerror。旧公開型の再帰schema指紋は`4a252a43ee85ba459e526a3dcfcfea41f765bdb084af39af4483369474e53e9a`に固定した。

C1⊆C0⊆旧B1という方向の純包含を保つ。旧初動は元から三構造が必須なので保持する。旧両方向競合から、追加条件で片側だけ残っても新規へ復活させない。元のmap/slice/ポインターを変更しない。

型付き旧判定用のwrapperであり、任意JSONの欠落fieldを検出するdecoderではない。帯鮮度・数量・反対圧力の算術は既存82へ委ね、独自の近似式へ置き換えない。

## 接続と人工検査

Go1.24.2 windows/amd64。CGO=0のためrace検査は未実施。市場原板を複製せず、実アプリ・設定・注文APIへ接続しない。

input/replay/batchは固定83からSHA付きで派生した。定時→公開足→源特徴→実保護、Last不正/交差BBO、同時刻相手のstrict過去参照、全台帳からの逐次技法seed準備と16workerを維持する。input.goの本文はpackageと由来ヘッダーを除いて固定83と同値である。

人工では、型/チェック破損、17場面の売買鏡像、60秒/32更新・10pt境界、未知/未来/NaN、初動保存、全候補値、schema非重複、A0と固定83の非0会計全文同値、3場の種carry/reset、逐次・8worker保存JSON全文同値、旧時計・終端・連番を検査する。人工は実市場の利益や全66場の基準同値を証明しない。

```powershell
go -C scripts/現在の価格応答と数量確認 test -count=1 ./...
go -C scripts/現在の価格応答と数量確認 vet ./...
New-Item -ItemType Directory -Path work/84再現 -Force | Out-Null
go -C scripts/現在の価格応答と数量確認 build -o ../../work/84再現/batch84.exe ./cmd/batch
```

全市場の再生はRootの条件固定後に、正式結果を上書きしない新しい出力へ行う。

```powershell
& work/84再現/batch84.exe -manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json -out work/84再現/全66場 -workers 16
```

明示人工JSONを保存する場合は、新規の絶対workパスを環境変数へ渡す。

```powershell
$env:FAR84_ARTIFICIAL_OUT = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path 'work/84再現人工'))
go -C scripts/現在の価格応答と数量確認 test -count=1 -run TestExportArtificialSnapshots -v ./...
Remove-Item Env:FAR84_ARTIFICIAL_OUT
```

このexporterは6場面の手製チャート種・現在帯と観測を用い、別運転した旧83S0G1とA0の全値同値を確認する。実原板からEMA/源特徴を再構築した証明ではない。既存出力は拒否する。

## 集計・独立監査・資料

ルートPowerShellから新規出力へ実行する。全66場の条件・結果は[試行](../../study/00084_現在の価格応答と数量確認/README.md)、保存境界・図・事後診断は[閲覧補足](../../study/00084_現在の価格応答と数量確認/閲覧補足.md)を参照する。

```powershell
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/現在の価格応答と数量確認/集計.py --input work/84再現/全66場 --out work/84再現/成果物 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/現在の価格応答と数量確認/原板監査.py --results work/84再現/全66場 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --out work/84再現/原板監査.json --workers 16
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/現在の価格応答と数量確認/基準と保存判断の照合.py --input work/84再現/全66場 --baseline work/83構造配分/全66場 --out work/84再現/基準と保存判断の照合.json
```

保存判断照合は、明示した83保存根に加え、固定82の`work/82現在性/全66場`も読み、両世代の正式結果SHAへ結ぶ。保存根がなければ各固定試行の再現手順で作り、入力指紋を先に確認する。元EMA・ATR・FAR帯生成の別実装はしない。原板監査は固定83のPython規範へ6キーを渡し、内部S0G1を検査してから独立監査の識別ラベルだけを変える。

表示監査.pyは既存Viewer数値APIへ`--catalog <一覧.resources.json> --result <結果.json> --out <新規証拠.json> --workers 8`を明示する。全396資源と最終flat純額を照合し、通信未完と数値差を分ける。Rは試行README末尾の11明示入力で`--run`／`--check`を実行する。

入口差の診断.pyは`--input --manifest --result --out-json --out-md`を全て明示し、同実入口・取得変更・純選別・占有による不採用・役割別の保存金額を分ける。保存群の足し算を未実行の別戦略利益にはしない。

図示.pyは`--result --out --preview`を指定し、`--added-only`でC0/C1だけの独立尺度も作れる。PNGは作業領域、正式図は小型SVGを用いる。原板・大きな中間結果を正式資料へ複製しない。
