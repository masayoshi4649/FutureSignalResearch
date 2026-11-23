# RSIと価格の山谷の検証

[試行00015](../../study/00015_RSIの山谷と価格構造/README.md)の固定12案を再現する。反転乖離/押し戻り継続、1/3/5分、同足ネック位置の有無を比較し、入口の125/250先着と一建玉X0運用を別に評価する。全65場は既使用。

極値の中心足と右2足で確定する時点を区別する。後から選んだ山谷を過去の入口に置かない。詳細な条件・版・監査範囲・限界は試行の計画/固定/設定と結果を参照する。旧coreと正式結果を変更しない。

Python3.14.3、NumPy2.5.3を使用。全量再生前の合成、保存結果の再表示は次のとおり。

```powershell
python -X utf8 scripts/RSI構造/合成検証.py
python -X utf8 scripts/RSI構造/レポート.py
```

正式保存先は再実行で上書きできない。再現時は新しいGit外の先へ計画/条件だけをコピーし、同じ入力台帳・既存cacheを参照する。

```powershell
New-Item -ItemType Directory -Path work/RSI再現/試行
Copy-Item -LiteralPath study/00015_RSIの山谷と価格構造/計画.md,study/00015_RSIの山谷と価格構造/条件.json -Destination work/RSI再現/試行
python -X utf8 scripts/RSI構造/検証.py --study work/RSI再現/試行 --work work/RSI再現/明細
```

`状態独立確認.py --実行許可`は全極値/発動を原価格から別計算し、`独立監査.py`は保存先着・会計を確認する。後者と`補助対応診断.py`・`レポート.py`の既定対象は正式00015である。別再現先の検査には、対応する`--study/--work`に対応した状態側を使い、正式結果の検査と混同しない。Viewer照合付き主監査は`独立監査.py --api-base http://127.0.0.1:8092`。
