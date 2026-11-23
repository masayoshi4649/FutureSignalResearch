# 2026-11-16 Dayの固定適用入力

179全期J035の条件を変更せず本日一場へ適用するため、167と同じ非金融接続器で生成した。今日の損益で閾値を選び直していない。

前史は旧122の予定CSV/実公表を2026-11-10 Dayまで再生し、既存167七場の価格索引を参照して11/13 Nightまで進め、本日を八場目として生成した。CSVの由来path表現を保持し、既存七場の出生台帳・両側100特徴・取得対応・物理取得・固定取得入力の全件prefixが元167と一致した。今日だけをscene_index=0へ射影している。

本日の索引は171,162採用原行、特徴と物理caseは各353件。価格Clockの最終は15:39:59で、物理更新時刻15:45とは区別する。179のcut=15:30・submit=15:29に必要なBBOは存在し、要求1秒後以降の最初正常BBOは原物理行168679・15:29:03・Bid59790/Ask59800で独立原板監査と一致した。

入力factoryは全C/known=Falseの未評価tableを作る。金融値を作らず、固定179の早期終了金融 early179.evaluate_recordsへそのまま渡す。金融Sourceや179の既存正本は変更しない。

## 正本と指紋

[保存索引](保存索引.json)に全ファイルのサイズ/SHA、[生成完了](完了.json)に前史同体とSource指紋を記録する。原板は参照だけで複製しない。

|入力|bytes|SHA256|
|---|---:|---|
|raw|279,145,299|a8cb764a0667285461109b2d8c128e0e7d2e13af5e5bc642e634bb6c12b4d27d|
|csv_1m|26,259|75069c6dc60631cb04ac82d60a755aaf143df2e3bcbaad41093de400a82be5f1|
|csv_5m|5,364|6f31d14a9b696b389356cbceaa8797b82e47044d1e9b4bf64803439a7868a3e8|
|原板数値索引/manifest.json|1,821|b6dad8241ffe3875abe1c13f552b35c5f1f1e4d45de7c61510fd3920596249a7|
|原板数値索引/2026-11-16_Day.quotes.bin.gz|517,791|02a026047568e8f3ef58e95e13c72d924eaa96fdefbdff2e39c9653c4bb740b0|
|入口母集団/当時特徴.json.gz|161,425|7c85fde92bab428a16fbbd4c80bdcd95ac3664ca2bde57d6df5126e636c1674e|
|入口母集団/取得対応.json.gz|22,316|8802a968daff7e8b9f67818ded5bc5a07092f517c51f8ec38336ca5b70bdd39e|
|入口母集団/固定取得入力.json.gz|10,429|a661dfcd0d0956cedb3cc5cb00a8f959158dc9242760604666991dc1ba265cb4|

## 読込と再生成

`work/180本日デイ適用/入力180.py` の `load_context()` は `context/features/captures/records/index_ref/proof` を返す。caseの `entry_index/entry_line/entry_time/entry_price` と索引の原物理行を照合済み。

再生成は別の検証checkout等で出力先が未作成の状態にする。既存入力を上書きしない。必要な166観測器/非金融bridgeのSourceは[167正式Source](../../study/00167_固定した複合入口を追加七場へ適用する/再現資料/Source.zip)と停止票に由来し、各go.modのローカル依存も同じ版を復元する。Go 1.24.2系で `work/166可変場の観測` を `go build -o 可変場観測.exe .`、`work/未見入口の同体接続` を `go build -o 入口同体接続.exe ./cmd/run` で用意できる。

旧122前史計画/公表とinputs167の前史七場はpath/SHA参照する。新規に原板を読むのは本日一場の索引段だけであり、旧七場は既存48byte索引を使う。

```powershell
$env:PYTHONUTF8='1'
python 'work/180本日デイ適用/入力180.py' --generate
```

Source SHA256：`76b5cb151893960cfe04eb257aebb78181a7c395e18225cdc72f14dd6c7db7e1`。Python 3.14.3 / NumPy 2.5.4を使用。


## 既存生成器の正式Sourceと再ビルド

`INDEX_EXE` と `BRIDGE_EXE` はいずれもGoの実行ファイルであり、この前処理に新規C# Sourceは使っていない。実行ファイルを新180へコピーせず、次の正式資料から復元・再ビルドできる。

|用途|実行ファイル|正式Source.zip内の元member|
|---|---|---|
|原板→48byte索引|`work/166可変場の観測/可変場観測.exe`|`work/166可変場の観測/`（go.mod・main.go・index.go・停止票等24member）|
|索引/CSV→100特徴/q0→q1|`work/未見入口の同体接続/入口同体接続.exe`|`work/未見入口の同体接続/`（go.mod・cmd/run/main.go・停止票等28member）|

復元元は[167正式Source.zip](../../study/00167_固定した複合入口を追加七場へ適用する/再現資料/Source.zip)、全member指紋は[167保存索引](../../study/00167_固定した複合入口を追加七場へ適用する/再現資料/保存索引.json)。[167正式再現器](../../study/00167_固定した複合入口を追加七場へ適用する/再現資料/正式入力から再現する.py)にも元byte照合と安全な復元処理がある。

同ZIPにはbridgeのgo.modがreplace参照する次の全依存も収録されている。`work/148全1分知得の入口母集団/`、`work/118複数技法の入口条件/`、`work/148全1分候補の当時特徴/`、`work/三時間軸の公開器/`、`work/115三時間軸と方向性の公開/`、`work/三時間軸の市場入力口/`。各folderの相対配置を維持する。

```powershell
Push-Location 'work/166可変場の観測'
go build -o 可変場観測.exe .
Pop-Location
Push-Location 'work/未見入口の同体接続'
go build -o 入口同体接続.exe ./cmd/run
Pop-Location
```

前史の177MB公表結合ファイルも恒久資料から再構成できる。[122新規3場公表の説明](../00122_新規3場公表/README.md)と[122再現手順](../../study/00122_E0固定条件を全セッションで検証する/再現資料/再現手順.md)に従い、旧118公表＋恒久保存された122差分から `work/122全場入力/入力.json` を復元する。公表生成計画は[恒久入力](../00122_新規3場公表/公表生成計画.json)を参照する。新180でこの前史全体を重複保存しない。

本日の損益だけを再現するときは、保存済み今日入力から `入力180.load_context()` → 固定179の早期金融/口座再生へ進めばよく、Goの再ビルドや原板再解析は不要。
