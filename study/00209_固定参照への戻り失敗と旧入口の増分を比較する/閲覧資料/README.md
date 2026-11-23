# 209 閲覧CSVの再現

[閲覧入口](../../../outputs/00209_TOPIXの固定参照と旧入口の増分/README.md)。候補0/28/29/34をそれぞれ5CSVへ分離し、20CSV・8,400セルを再読照合した。全20表の描画を確認した。UTF-8 BOM/CRLF、未知は空欄。xlsxは作っていない。

[型付き入力](閲覧入力.json) / [CSV確認](CSV確認.json) / [Source](閲覧Source.zip) / [Source索引](Source索引.json)。入力生成は正式安定性と正式金融の保有区間だけを読み、workの金融や原板を必要としない。量・枠・金融の再探索はしない。

Sourceを元相対pathへ復元し、閲覧入力209.pyを実行。型付きJSONをscripts/損益CSV/候補別に出力する.mjsへ --input、--output 新規出力先、--proof 新規確認先、--dependencies Codex提供node_modulesで渡す。Node24.22.1・Codex提供artifact-tool。全セル設定とrecalculate後の値照合、別Python csv再読で確認する。
