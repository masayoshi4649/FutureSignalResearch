# 外側継続と上位基準線の進行

[試行39の計画](../../study/00039_外側継続と上位基準線の進行/計画.md)。固定38H0＝37T1の全継続をJ0とし、最新公開15分uと当場隣接前pの基準26準備だけをJ1、実side×(J26(u)−J26(p))>0strictをJ2にする。全3入口/3運用は順行XFで、雲外・TJ整列は診断だけ。

`入口.py`は当時の純13列・下位出典・上位27列を結ぶ。まず38と同じ公開key優先で最新uを決め、その当場index−1だけをpへ取る。両足の公開/数値入力可/有限J/900秒/missing0/隣接end-index/両asofを要求し、古い良好ペアへ戻らない。未来/NP/不在pはsnapshotを保存せず、同じ『前上位公開参照なし』として未来prefixで判断理由も変えない。雲78本を含む一目公開可はJ準備に使わず、新銀行の現前Jは最短27本。

`検証.py`は固定38共有束の旧37T1をH0へ識別子だけ変換し、39自身が参照する固定38H0caseの全188純13列と厳密照合する。旧P/MACD/数量M/ATRは38/37の証明へ接続し、新たに再算したと表現しない。旧29下位足、旧28上位数値、原板は共有参照し、複製しない。新caseは正常BBOから直接計算し、旧H0同時計11ラベルとも照合する。J0の全台帳・追尾はID以外を旧38H0XFと同値照合する。

独立状態は元8列から下位OHLCと全15分数値を再形成し、全候補列挙によるasof/pairと、交差積からの厳密ΔJで検算する。追尾は固定33独立XF、会計は最初正常新規/Decimal全属性/MFE/MAE/DD/CSV/Viewerへ接続する。HH/LLの窓脱落でもJは動く。人工例で機序を点検するが、実相場寄与panelを新計算したり採否へ足したりしていない。

Python3.14.3、NumPy2.5.3、orjson3.13.0。ルートでの手順は以下。正式結果と明細を上書きしない。再現は同条件・参照を備えた別study/workを主/独立の`--study`/`--work`へ指定し、財務・帳票のパス定数も対象へ明示的に合わせる。

```powershell
C:/Python314/python.exe -X utf8 scripts/上位中心継続/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/上位中心継続/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/上位中心継続/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/上位中心継続/検証.py
C:/Python314/python.exe -X utf8 scripts/上位中心継続/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/上位中心継続/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/上位中心継続/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/上位中心継続/対応診断.py
C:/Python314/python.exe -X utf8 scripts/上位中心継続/レポート.py
```

準備は先着/運用/PnLを呼ばない。新4gzipは上位判定/最小case/全運用/追尾だけ。準備除外と値除外、原要求の30分間引き/支持、共通新規出口と実参加、仮250先着と実回収、観測額と品質nullを分ける。全66場は既使用で、未来の安定性を確立したとは呼ばない。

XFは現在返済BBOの費用後含み益strict正で起動し、入口ATR固定D・MFE−D・最低名目新規床・非緩和を保つ。起動参照5ptのまま、0/5/10ptは同約定の費用負荷。名目床は費用後同値や遅延後同値約定を保証しない。支持付き125/250の70%目標を、小幅利確の売買勝率へ読み替えない。
