# 外側継続と発動足の相対値幅

[試行40の計画](../../study/00040_外側継続と発動足の相対値幅/計画.md)。固定39J0＝元37T1全継続をW0、同場の隣接現前3分/TR/正本前ATR14の準備だけをW1、精密TR≤保存正本前ATRをW2にする。全三案順行XF。倍率1は平均非超過であり、統計的な異常・過熱の基準ではない。

`入口.py`は純13列、下位出典、旧29保存の3分を使う。現足を元indexで特定し、当場index−1だけを前足へ取る。公開/有効OHLC/幅180秒/missing0/隣接end-index/前key≤現keyを要求し、不在/NP/未来の前足は同じ理由でsnapshotを出さない。古い正常足に戻らない。TR三候補はH−L、abs(H−prevC)、abs(L−prevC)。各価格と正本前ATRをFraction化して差/比の分子分母と採否を保存し、epsilonを足さない。

`検証.py`は固定39共有束の旧H0純13列をJ0へ識別子だけ変換し、固定39保存J0caseの全188純列へ厳密照合する。旧P/MACD/元P数量M/純ATR発動の検算は既存証明へ接続。旧29の全3分を指標参照で共有し、新しい全数値・原板・contextの複製を避ける。共有束の内部では旧15分参照を読取するが、40の採否/新計算/出力に使わない。

独立は元8列→全3分OHLC/ATR14の別算を数値abs1e−10/rel0・D整数厳密で確認し、検算済正本ATRによる精密TR/差比/全判定/rawSHAを別算する。さらに再算ATRを使っても比較符号/準備/全採否がstrict一致することを要求する。数値許容を採否へ使わず、独立ATRの生全内容SHAが正本と完全同一と主張しない。

各caseの正常BBO直接125/250先着と、旧J0同時計11ラベルを照合。W0の全台帳/追尾はID以外を旧39J0XFと同値照合する。新しい全三XF追尾・最初新規・Decimal会計/CSV/Viewerを別証明にする。先着は実返済後まで追う経路で、実回収とは分ける。

Python3.14.3、NumPy2.5.3、orjson3.13.0。ルートでの実行順は以下。正式結果/明細の上書きを拒否する。再現用は同条件/参照を備える別study/workを主/独立の`--study`/`--work`へ指定し、財務/帳票パス定数も対象へ明示的に合わせる。

```powershell
C:/Python314/python.exe -X utf8 scripts/発動値幅継続/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/発動値幅継続/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/発動値幅継続/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/発動値幅継続/検証.py
C:/Python314/python.exe -X utf8 scripts/発動値幅継続/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/発動値幅継続/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/発動値幅継続/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/発動値幅継続/対応診断.py
C:/Python314/python.exe -X utf8 scripts/発動値幅継続/レポート.py
```

準備は先着/運用/PnLを呼ばない。新4gzipは値幅判定/最小case/全運用/追尾。準備と値の除外、30分間引き/支持、純subsetと実追加、共通出口/片側参加、0/5/10総額と平均、仮250前退出/実MFE250/起動後費用赤字、観測額/品質nullを分ける。全66場は既使用で、新しい未見検証とは呼ばない。

旧5分のTR前ATR比/当足拡大の再利用で、P12形状・33CLV・13BB遷移とは役割と時点が異なる。Wilder式の実数上のATR非拡大との同値を別の確認票に数えず、保存現ATR比較へ置換しない。前ATRを入口に使っても、出口Dは純入口の現ATRのまま。XFは現在費用後含み益strict正で起動し、最低名目entry床/MFE−D/非緩和を保つ。名目床は費用後同値や遅延後同値約定を保証しない。
