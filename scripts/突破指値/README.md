# CCI突破の水準指値

[試行00034](../../study/00034_CCI突破の水準指値/README.md)。同じ価格突破＋現前CCI持続を、E0即時対E1登録時20高安の固定指値で比較する。両方の現在費用後起動XFを維持し、指値価格・登録ATR・30秒TTLを後続で取り直さない。

仮約定は各登録独立、実運用は単一pending/単一建玉。正常BBOを用い、OHLC接触や過去の有利価格で約定にしない。E1の成立後はその新規価格から125/250を再計算する。純約定機会の選別、価格と時計の変更、実参加、同実新規だけの出口差を分ける。

旧31の六明細と旧33の対照運用・追尾は共有参照し、新大明細は入口事例・全運用詳細・追尾の三系列だけ。原板は複製しない。Python3.14.3・NumPy2.5.3で、準備は先着/運用/PnLを呼ばない。

```powershell
C:/Python314/python.exe -X utf8 scripts/突破指値/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/突破指値/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/突破指値/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/突破指値/検証.py
C:/Python314/python.exe -X utf8 scripts/突破指値/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/突破指値/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/突破指値/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/突破指値/対応診断.py
C:/Python314/python.exe -X utf8 scripts/突破指値/レポート.py
```

正式出力は上書きしない。全66場は既使用。指値の数量/キュー、実mini/micro約定、価格時計を実受信時計とした経過秒は未確認。追加0/5/10ptは同約定費用負荷であり、指値上限を越えた約定の仮定ではない。
