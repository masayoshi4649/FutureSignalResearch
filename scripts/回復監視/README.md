# CCI突破の到達後回復

試行[35](../../study/00035_CCI突破の到達後回復/計画.md)。固定34E1の30秒指値、180秒指値、同じ180秒以内の到達→strict後key回復→市場要求を比較する。登録は固定31C0の価格構造＋現前CCI、出口は固定33XFの現在費用後strict正起動。売りは買いの鏡像。

`入口.py`は純15列と別の仮監視観測、仮新規後の125/250を扱う。`運用.py`はE1を固定34へ直結し、E2の局所寿命とE3の単一監視を実装する。`検証.py`が出典固定・正式再生・最小三gzip・Viewer形式へ接続する。`状態独立確認.py`は別の原列走査、`追尾独立確認.py`は現在費用起動と全追尾、`新規会計.py`と`独立監査.py`は絶対期限・最初適格BBO・全Decimal会計を扱う。`対応診断.py`と`レポート.py`は保存結果だけを読む。

Python 3.14.3、NumPy 2.5.3、orjson 3.13.0。リポジトリルートで実行する。正式結果は上書き禁止なので、再現の際は条件と参照を同じ内容で用意した別のstudy/work先を`--study`/`--work`へ指定する。旧31/33/34の共有work明細を保持する。原板や新しい場を自動列挙しない。

```powershell
C:/Python314/python.exe -X utf8 scripts/回復監視/検証.py --prepare
C:/Python314/python.exe -X utf8 scripts/回復監視/状態独立確認.py --prepare
C:/Python314/python.exe -X utf8 scripts/回復監視/合成検証.py --final
C:/Python314/python.exe -X utf8 scripts/回復監視/検証.py
C:/Python314/python.exe -X utf8 scripts/回復監視/状態独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/回復監視/追尾独立確認.py --実行許可
C:/Python314/python.exe -X utf8 scripts/回復監視/独立監査.py --api-base http://127.0.0.1:8092
C:/Python314/python.exe -X utf8 scripts/回復監視/対応診断.py
C:/Python314/python.exe -X utf8 scripts/回復監視/レポート.py
```

準備は技術的な到達/回復の観測までで、仮fill・先着・運用・損益は計算しない。最終人工のCLIと証明は同ファイルの仕様に従う。固定前に主・独立・人工の編集を終える。監視の将来snapshotをlive純信号へ渡さない。原要求bと回復時の新規要求b′、未発注監視と発注後取消、元期限と回復からの時間を区別する。

全66場は既使用で、この実装や計算の一致は将来の収益性を証明しない。価格時計は受信時計ではない。数量/指値キュー/実microの成立も別に確認が必要。
