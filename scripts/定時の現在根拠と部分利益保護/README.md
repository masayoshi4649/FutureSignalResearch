# 定時の現在根拠と部分利益保護

[試行81](../../study/00081_定時の現在根拠と部分利益保護/README.md)専用。元FAR後期の公開特徴部品から定時に新規を直接判断し、入口B0/B1×保護G0/G1×価格時計遅延0/1秒を独立会計で比較する。元Sourceの保有・返済を写さない。売買の定義と固定指紋は[検証計画](../../study/00081_定時の現在根拠と部分利益保護/検証計画.md)と[条件](../../study/00081_定時の現在根拠と部分利益保護/条件.json)を参照する。

Go 1.24.2、Python 3.14.3、図示だけMatplotlib 3.11.2を使用。依存Goモジュールはgo.mod/go.sumで固定。`../FAR後期15分移植`と兄弟`SessionTradeExecuter`を指紋固定した読取依存とし、実アプリの起動・自動発注は行わない。

## 再現

ルートPowerShellから、正式結果とは別の空の作業出力へ再生する。既存出力を上書きしない。全66場は既使用であり、再生しても新しい期間の検証にはならない。

```powershell
go -C scripts/定時の現在根拠と部分利益保護 test ./...
go -C scripts/定時の現在根拠と部分利益保護 vet ./...
New-Item -ItemType Directory -Path work/81再現 -Force | Out-Null
go -C scripts/定時の現在根拠と部分利益保護 build -o ../../work/81再現/batch81.exe ./cmd/batch
& work/81再現/batch81.exe -manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json -out work/81再現/全66場 -workers 16
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/定時の現在根拠と部分利益保護/集計.py --input work/81再現/全66場 --out work/81再現/成果物 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json
& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/定時の現在根拠と部分利益保護/原板監査.py --results work/81再現/全66場 --manifest study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json --out work/81再現/原板監査.json --workers 16
```

Viewer監査は既存の数値APIが利用可能な時に別実行する。`表示監査.py --catalog <一覧.resources.json> --result <結果.json> --out <新規監査.json> --workers 8`。API通信未完と数値不一致を区別する。保存READMEの再生成・照合は試行README末尾の全入力明示コマンドに従う。

## コードと検査の範囲

| ファイル | 用途 |
| --- | --- |
| entry.go | FAR現在支持・帯構造の抽出、未知理由を含む複合入口 |
| actual.go | 実所有・未約定・部分確定、利益前後の追尾、確定予算床 |
| input.go／replay.go／batch.go | 原行と定時の順序、確定足carry、場単位16並列 |
| 集計.py | 保存約定の会計照合、小型正本・圧縮診断・Viewer資源 |
| 原板監査.py | 原板から次正常BBO・数量・費用・利益旗・保護要求・予算床を照合 |
| 表示監査.py | 全528資源のViewer所有イベント・純額・入力不変を照合 |
| 監査確認.py | 売買鏡像・部分返済・悪化・未決・metadata破壊等の独立人工 |
| レポート.py | 明示した小型正本だけからREADME／版5表の結果欄を生成・同値確認 |
| 図示.py | 場末の累積費用後損益をSVGへ図示 |
| 保存取引の局面診断.py | 結果後の群分け。条件を選び直した運用成績にはしない |

原板監査のATR幅は保存された入口ATRから再計算し、ATR系列自体の別実装照合は行っていない。全玉の初回正益・現在純額・口座DDは原板から再構築するが、保存全玉峰／谷の個別全値照合は範囲外。ラージ代理約定の流動性・mini/microの約定順位・証拠金制約は未実証である。CGO無効環境のためGoのrace検査は未実施。
