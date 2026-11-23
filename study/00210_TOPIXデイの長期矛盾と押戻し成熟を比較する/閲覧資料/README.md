# 210候補別CSVの再現

[閲覧入口](../../../outputs/00210_TOPIXデイの長期矛盾と成熟待ち比較/README.md)。旧0・Day有望主3・成熟待ち比較5を分離。[型付き入力](閲覧入力.json)・[最小保有区間](対象保有区間.json.gz)・[照合](CSV確認.json)・[Source](閲覧Source.zip)・[索引](Source索引.json)。

入力を作る.pyは通常、正式の全13組全83安定性.json.gzと対象保有区間.json.gzだけを参照する。初回の`--保有を固定`以外はwork金融に依存しない。型付きJSONを共通の`候補別に出力する.mjs --input 入力 --output 新規先 --proof 新規確認先 --dependencies Codex提供node_modules`へ渡す。既存CSVは上書きしない。

Codex提供artifact-toolへ全セルを渡し、再計算後CSVを出力。全15表のプレビューを目視し、Python csvで6,300セルを再読、累計・未知空欄・利益−損失を独立確認。UTF-8 BOM/CRLF。PNGは作業確認用だけとし正式には複製しない。
