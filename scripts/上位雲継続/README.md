# 外側継続と上位の現在雲

[試行38の計画](../../study/00038_外側継続と上位の現在雲/計画.md)。固定37T1をそのままH0にし、当場の最新公開15分一目準備だけのH1、さらに上位終値の実方向雲外を求めるH2を比較する。全3入口/3運用は順行XF。転換/基準の整列は診断だけで、採否に追加しない。

主の`入口.py`は固定37caseから即射影した純13列と、29保存の下位出典、28保存の上位27列だけを結ぶ。上位はendと公開keyの両方が当時までの最新足。現在雲は26本前の計算値で、現在計算の先行線と分ける。最新不準備なら古い正常足へ戻らない。H0は既に競合後の旧T1集合を維持し、重複入力を拒否する。

`検証.py`は共有参照・非損益準備・固定・3案の正式を扱う。旧P/MACD/数量Mは再計算せず、固定37の状態証明と指紋へ接続する。主は15分数値も固定28から共有し、大きい旧足/context/原板を複製しない。新しい先着は各案の正常BBOから計算し、同時計の旧T1全11ラベルとも比較する。H0の全台帳・全追尾は識別子以外を旧37T1XFと同値照合する。

独立状態は元8列から3/15分の原足、15分の全高安窓・現在雲・公開出典を別算し、asofを全候補列挙で照合する。純13列のATRも今回は旧37を写すため原値strict。旧指標を38で再計算したと表現しない。追尾は全3XFの最初返済要求・全線、会計は最初正常新規/全Decimal/MFE/MAE/DD/CSV/Viewerを検査する。

Python3.14.3、NumPy2.5.3、orjson3.13.0。ルートでの手順は以下。正式の既存結果・gzipは上書きしない。再現用主/独立は同条件・同参照を備えた別study/workを`--study`/`--work`へ指定し、過去の固定成果物を保持する。財務・帳票のパス定数は対象置場へ明示的に合わせる必要がある。

```powershell
C:/Python314/python.exe -X utf8 scripts/上位雲継続/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/上位雲継続/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/上位雲継続/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/上位雲継続/検証.py
C:/Python314/python.exe -X utf8 scripts/上位雲継続/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/上位雲継続/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/上位雲継続/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/上位雲継続/対応診断.py
C:/Python314/python.exe -X utf8 scripts/上位雲継続/レポート.py
```

`--prepare`は先着・新規/返済・損益を呼ばない。新4gzipは上位判定/最小case/全運用/追尾。正式の小型JSON/Markdown、Viewer一覧と約定をstudyへ置き、共有正本と入力の指紋を残す。全66場は既使用であり、今後の安定収益を確立したとは呼ばない。

XFは現在正常返済BBOによる費用後含み益strict正で起動し、入口ATR固定D・MFE−D・最低名目新規床・非緩和を保つ。0/5/10pt感度は同約定の費用負荷。名目同値床は費用後同値・遅延後の同値約定を保証しない。純subsetと実追加参加、仮250先着と追尾後回収、観測額と品質nullを区別する。
