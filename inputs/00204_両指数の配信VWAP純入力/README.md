# 204 配信VWAPの純入力

2026-11-18。現在はTOPIX83場・35,361 q0のみ。新金融・売買候補は未実行。201の原板指紋・判断原行を使い、原板の複製をせず、同原行のnative VWAP/代金/数量/時計/起算を保存した。

- [抽出前固定票](抽出前固定_TOPIX.json.gz)：201への参照、全83場・q0・原板指紋、抽出Sourceの実行前固定。
- [完了台帳](完了_TOPIX.json)：原板展開SHA、物理SHA、全q0数、出力の容量・SHA。
- [可用性集計](TOPIX可用性集計.json)：場・三帯別の可用性、時計、nativeと当場差分の違い。
- [独立原行照合](TOPIX独立原行照合.json)：全q0 728,535属性一致。区間変更状態全体の別実装とは区別。
- `TOPIX/*.json.gz`：当時q0だけの純入力。合計2,133,746 bytes。`*.検査.json`の場末診断は入口特徴に使わない。
- [研究の入口](../../study/00204_VWAPと価格構造の両指数入口/README.md)。

## 再現

Python3.14.3、orjson3.13.0。`work/pythonlibs`のorjsonと既存研究用Pythonを使用。抽出器は金融コードをimportしない。raw原板と201固定票は共用入力として参照する。

```powershell
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/VWAP純入力204/人工確認.py'
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/VWAP純入力204/抽出204.py' --stage prepare --symbol TOPIX
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/VWAP純入力204/抽出204.py' --stage extract --symbol TOPIX --workers 3
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/VWAP純入力204/独立原行照合.py'
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/VWAP純入力204/可用性集計.py'
```

既存結果があれば同じバイトか照合し、異なる結果で上書きしない。固定票のmtime・絶対pathは実行時環境の指紋であり、別環境へ展開した場合は既存票を改変せず、移設先を明記した別の再現票で照合する。Sourceは[204の保存索引](../../study/00204_VWAPと価格構造の両指数入口/保存索引.json)から確認する。

nativeと当場差分を混同せず、HLC3×観測数量を真の取引VWAPと呼ばない。細かな判定仕様は実行前に固定した[仕様](../../scripts/VWAP純入力204/仕様.md)を参照する。
