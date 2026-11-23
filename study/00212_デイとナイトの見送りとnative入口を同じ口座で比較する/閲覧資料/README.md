# 212候補別CSVの再現

[閲覧入口](../../../outputs/00212_TOPIXの帯別入口と損失安定性/README.md)。0/5/6/7の4候補を各5CSVへ分離。[型付き入力](閲覧入力.json)・[照合](CSV確認.json)・[Source](閲覧Source.zip)・[索引](Source索引.json)。

閲覧入力212.pyは正式安定性と正式金融の保有区間だけを読み、売買条件や金融を再探索しない。型付きJSONをscripts/損益CSV/候補別に出力する.mjsへ --input、--output 新規出力先、--proof 新規確認先、--dependencies Codex提供node_modulesで渡す。Node24.22.1とCodex提供artifact-tool、全セル設定・recalculate・描画確認後に出力。別Python csvで20CSV8,400セル・未知空欄・累計・利益損失を照合した。UTF-8 BOM/CRLF。xlsxは作成しない。
