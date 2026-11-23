# 構造否定と利益配分

[試行83](../../study/00083_構造否定と利益配分/README.md)の検証コード。入口は固定82B1を共用し、構造否定S0/S1と利益配分G1/G2の2×2、価格時計遅延0/1秒で8会計を再生する。定義は[検証計画](../../study/00083_構造否定と利益配分/検証計画.md)、指紋は[条件](../../study/00083_構造否定と利益配分/条件.json)を参照する。

Go 1.24.2、Python 3.14.3、図示はMatplotlib 3.11.2。go.mod/go.sumの依存版と、80/81/82・兄弟SessionTradeExecuterの純戦略コードを固定参照する。実アプリ・自動発注は起動しない。

## 再現

ルートPowerShellから新規の空出力へ実行する。正式結果を上書きしない。全66場は既使用である。

```powershell
go -C scripts/構造否定と利益配分 test ./...
go -C scripts/構造否定と利益配分 vet ./...
New-Item -ItemType Directory -Path work/83再現 -Force | Out-Null
go -C scripts/構造否定と利益配分 build -o ../../work/83再現/batch83.exe ./cmd/batch
& work/83再現/batch83.exe -manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json -out work/83再現/全66場 -workers 16
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/構造否定と利益配分/集計.py --input work/83再現/全66場 --out work/83再現/成果物 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/構造否定と利益配分/原板監査.py --results work/83再現/全66場 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --out work/83再現/原板監査.json --workers 16
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/構造否定と利益配分/基準と入口の照合.py --input work/83再現/全66場 --baseline work/82現在性/全66場 --out work/83再現/基準と入口の照合.json
```

Viewer APIが利用可能なら、表示監査.pyへ`--catalog <一覧.resources.json> --result <結果.json> --out <新規監査.json> --workers 8`を明示する。READMEと設定結果の生成・照合は試行README末尾の10入力明示コマンドに従う。

保存結果の追加診断は[閲覧補足](../../study/00083_構造否定と利益配分/閲覧補足.md)から参照する。出口差の診断.pyは同実新規の黒赤変化と参加差、正益後赤字の診断.pyはG1全旗後赤字の初回要求・部分約定・残量床を原板へ結ぶ。後者の6必須入力と再現コマンドは[診断資料](../../study/00083_構造否定と利益配分/正益後赤字の診断.md)に保存する。これらは金融コードを変えない事後診断である。

## コードと限定

actual.goは固定81から派生し、要求時のEMA価格線を注文→実玉→返済片へ値保存する。S1は実新規価格との差を床へ重ね、線を後から動かさない。G2は正益時から最低建値とATRを追尾し、部分返済・確定益予算は使わない。建値返済は費用後黒字を保証しない。

入口・特徴抽出・ChartBankは固定82、技法種と時計は固定80を再用する。基準と入口の照合.pyは、83B1の全snapshotとS0G1の旧全項目を82に対応させ、mode名と宣言済み追加構造欄だけを除いて数値・順序の同値を確認する。

原板監査.pyは価格・所有・初回益・ATR/構造/G1G2床・同原行の返済予約・確定予算を原板から再構築する。構造価格は保存した当時EMAへ結ぶが、EMA/ATR系列自体の独立実装と保存全玉峰／谷の個別全値比較は範囲外。closedの構造hitは返済片の当時値として検査し、最終lot値へ単純同値にしない。

人工は`go -C scripts/構造否定と利益配分 run ./cmd/fixture -out <新規作業根>`で5場面×売買鏡像＝10場面・80会計を手計算端点へ結び、監査確認.pyの`--fixtures <同作業根>`で原板・表示・保存破損を検査する。`-out`は同コードフォルダからの相対パスまたは絶対パスを指定する。本物原板と実APIは使わない。

ラージBBOをmicro全量の代理約定とし、板深さ消費・実通信・約定順位・証拠金は未実証。CGO無効環境のためrace検査は未実施。原板・大きな中間結果・人工出力はworkへ置く。
