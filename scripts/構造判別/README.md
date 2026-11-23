# 高安帰還と外側継続の判別

[試行37](../../study/00037_高安帰還と外側継続の判別/計画.md)。旧29価格P/MACD/元P数量Mを維持し、B0完全基準、R1旧高安のstrict全範囲内帰還、T1元方向外側＋継続方向MACD、S1反転/継続切替を比較する。旧B0X0は歴史参考、四XFが現在方針候補。Tの実sideは元Pの反対で、新方向BBOから125/250を計算する。

`入口.py`は当時の旧両端・位置/勢い/全採否と純13列、`検証.py`は非損益準備/固定/正式の全新先着と五運用、`運用.py`は固定33への限定接続。Sの純roleは反転/順行、新規fillで固定し、保有中に書き換えない。単独候補の競合前技術候補からSを組み、同key複数は同方向も全見送り。自動ドテンはない。

独立状態は元8列から旧数値/Q/構造/実方向を別再構成し、全caseの原BBO直接先着を確認する。追尾は最初返済要求と全線、財務は即時最初BBO/全Decimal会計/CSV/Viewer、診断/帳票は保存物だけを扱う。

Python3.14.3、NumPy2.5.3、orjson3.13.0。ルートから実行。正式結果は上書き禁止。主/独立状態/追尾を再現する場合は、同条件/二参照を持つ別study/workを`--study`/`--work`へ指定する。旧29六明細と66場cacheは共有参照し、新しい原板を自動列挙しない。

```powershell
C:/Python314/python.exe -X utf8 scripts/構造判別/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/構造判別/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/構造判別/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/構造判別/検証.py
C:/Python314/python.exe -X utf8 scripts/構造判別/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/構造判別/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/構造判別/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/構造判別/対応診断.py
C:/Python314/python.exe -X utf8 scripts/構造判別/レポート.py
```

準備は先着/運用/PnLを呼ばない。旧反転11labelは正式の同時計比較だけに使い、Tへ転記/補数化しない。新4gzipは全原Pの小型構造判定/最小case/ledger/trace。旧全指標/context/原P/原板を複製しない。全66場既使用、価格時計と受信時計、名目同値床と費用後同値、純subsetと混合占有を区別する。混合の入口率と役割別支持は別に報告する。
