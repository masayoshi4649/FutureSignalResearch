# 価格失敗と量比の方向変化

[試行36の計画](../../study/00036_価格失敗と量比の方向変化/計画.md)。旧29R0の価格失敗＋中心化MACD差を維持し、V0完全入口、V1現前B20準備、V2量比差実方向正の三入口を比較する。旧V0X0は歴史参考、V0/V1/V2XFが現在方針の三候補。売りと買いは鏡像。

`入口.py`にBの厳密比・数量欠測時の価格基準保持・純13列・全採否、`検証.py`に非損益準備/固定/正式集計、`運用.py`に固定33出口への限定接続がある。独立状態/追尾は別の元列走査と比計算、独立会計は最初BBOとDecimal損益、対応診断/帳票は保存結果だけを扱う。

Python 3.14.3、NumPy 2.5.3、orjson 3.13.0。ルートから実行する。既存正式結果は上書き禁止。主/状態/追尾の再現は条件・二参照を同内容で用意した別study/workへ`--study`/`--work`を指定する。共有旧29六明細と既存66場cacheを保持する。原板や新しい場は自動列挙しない。

```powershell
C:/Python314/python.exe -X utf8 scripts/量比反転/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/量比反転/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/量比反転/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/量比反転/検証.py
C:/Python314/python.exe -X utf8 scripts/量比反転/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/量比反転/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/量比反転/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/量比反転/対応診断.py
C:/Python314/python.exe -X utf8 scripts/量比反転/レポート.py
```

準備では新たな先着/保有/PnLを計算しない。正式集計の同時計先着11列だけを旧29から共有し、liveは純13列へ独立射影する。新4gzipは量比全足/最小case/全運用/追尾だけ。旧OHLC・context・原P・原板を複製しない。全66場既使用、観測数量と真の全出来高、名目同値と費用後同値、価格時計と実受信時計を区別する。
