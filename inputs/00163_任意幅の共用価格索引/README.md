# 任意幅の共用価格索引と金融入力

2026-11-14。163で生成し163/164以後が再用する共有入力を、この一組だけ恒久保存する。各試行の正本ZIPへ同じデータを重複させない。

- `価格索引/`：73場の48byte原行順数値をgzipで保存。manifestのindex.pathは同じdirectory基準の相対名。
- `Raw観測/`：12幅×H30/H60/H120/SESSIONのGo観測。manifestのfile.pathは同じdirectory基準。独立Raw照合の入力として再用する。
- `数値表/`：探索用NPZと識別・入力確認。load_table(directory,expected)はdirectory基準で復元する。

[保存索引](保存索引.json)に由来work path、元と同じSHA・サイズ・保存Sourceを記録。元manifestの絶対raw.pathは由来であり、保存時に書き換えていない。各gzip/NPZの全CRCと物理SHA、manifest内の相対参照を確認した。原板本体、161の作業cache、各試行の統計出力はここへ複製していない。

研究再現時は各試行のSourceを別checkoutへ展開し、必要なら保存索引のorigin相対位置へこの一組を作業用に復元する。元Sourceとmanifest bytesを変更しない。後続が実行中の元workは移動せず残したが、正式な閲覧・保存は本directoryを参照する。
