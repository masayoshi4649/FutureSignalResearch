# 208候補別CSVの再現

[閲覧入口](../../../outputs/00208_TOPIXの浅押戻し見送り比較/README.md)。旧0・全期有望主3・前48順位首位6を別々に保存した。[型付き入力](閲覧入力.json)・[対象保有区間](対象保有区間.json.gz)・[CSV照合](CSV確認.json)・[Source](閲覧Source.zip)・[索引](Source索引.json)。

入力を作る.pyは通常実行で正式の全83集計と対象保有区間だけを読み、workの金融に依存しない。`--保有を固定`は独立照合済み金融から最小の区間情報を保存する初回用で、通常は不要。型付きJSONを `scripts/損益CSV/候補別に出力する.mjs --input 型付き入力 --output 新規出力先 --proof 新規確認先 --dependencies Codex提供node_modules` へ渡す。既存CSVは上書きしない。

NodeとCodex提供artifact-toolで全セルを渡し、recalculate後にCSV出力、全15表の描画を確認した。Python csvで全6,300セルを再読照合し、未知空欄・累計・利益−損失を検査。CSVはUTF-8 BOM/CRLF。xlsxは作らず、条件・金融・固定選択も変更していない。
