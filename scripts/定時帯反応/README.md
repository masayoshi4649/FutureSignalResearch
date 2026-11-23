# 序盤帯反応の定時検証

[試行49](../../study/00049_15分定時の序盤帯反応/検証計画.md)専用の実装。旧試行の多段継承から分離し、固定済みSOURCE価格足と8列キャッシュを入力にする。新規判断15分と、価格更新ごとの損失/利益追尾を分ける。

- `入口.py`：当場30分の高安、3分FastK14/ATR14、15分DMI14を因果的に計算し、順行・反転・待機・判定不能へ分ける。
- `運用.py`：[運用仕様](運用仕様.md)の一建玉・定時分類・連続追尾・約定台帳。
- `検証.py`：固定入力照合、定時キー、仮想125/250、同時条件の集計、Viewer資料を作る。
- `レポート.py`：結果JSONを読み、READMEと55手法×9尺度の設定表を生成する。
- `保存物確認.py`：保存済みの判断・先着・実約定・集計を独立に検査する。

Python 3.14.3、NumPy 2.5.3を使用。NumPyは共有npz入力だけに使い、入口・運用は標準ライブラリ。GPUは不要。原板の複製・新データの列挙・注文送信は行わない。

```powershell
C:/Python314/python.exe -X utf8 scripts/定時帯反応/入口人工テスト.py
C:/Python314/python.exe -X utf8 scripts/定時帯反応/運用人工テスト.py
C:/Python314/python.exe -X utf8 scripts/定時帯反応/先着人工テスト.py
C:/Python314/python.exe -X utf8 scripts/定時帯反応/検証.py --freeze
C:/Python314/python.exe -X utf8 scripts/定時帯反応/検証.py --run
C:/Python314/python.exe -X utf8 scripts/定時帯反応/保存物確認.py --run
C:/Python314/python.exe -X utf8 scripts/定時帯反応/レポート.py
```

固定と市場実行は上書きを拒否する。再現時は同じ入力指紋を持つ別作業コピーへ配置し、正本の固定・開始・結果を削除して再実行しない。人工テスト・保存物の読取確認と、市場の戦略再生を区別する。ローカルViewerは`http://127.0.0.1:8092`、一覧は試行内の`一覧.resources.json`を指定する。
