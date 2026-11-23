# 199の候補別CSV再現

[閲覧入口](../../../outputs/00199_日経の損失軽減候補/README.md)。金融正本・条件・順位は変更せず、全83場の旧基準/195_05同体/199_05を取り出した。[型付き入力](閲覧入力.json)・[照合](CSV確認.json)・[Source](閲覧Source.zip)・[Source索引](Source索引.json)。

ZIPを元の相対構造へ展開して `python -X utf8 work/199候補別CSV/入力を作る.py` を実行する。既存の `scripts/損益CSV/候補別に出力する.mjs` に `--input work/199候補別CSV/閲覧入力.json --output 新規出力先 --proof 新規確認先 --dependencies Codex提供node_modules` を渡す。既存CSVフォルダへ上書きしない。Pythonの入力生成は正式study資源だけを読み、金融を実行しない。Node24.14.0、Codex提供artifact-toolを使用。xlsxは生成しない。

累計未知と既知寄与を分け、保有区間の帯別重なりを正本時間合計へ照合している。15CSVをPython csvで再読し全6,300セル一致、利益−損失と既知収支・累計算術も確認した。元の金融検査は199の監査正本を参照。
