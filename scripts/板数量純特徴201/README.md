# 板数量の純特徴201

[仕様版1](仕様.md)に従い、原板の最良板と深度10段を過去だけの特徴へ変換する。正式保存先は[201恒久入力](../../inputs/00201_両指数の板数量純特徴/README.md)。金融候補の選択と損益計算は含まない。

|Source|役割|
|---|---|
|[特徴核.py](特徴核.py)|原行順の状態更新と7特徴。実売買側を掛けない|
|[人工確認.py](人工確認.py)|鏡像、数量倍率、同値行、境界、未来同秒行、後退復帰等の9群を確認|
|[人工確認.json](人工確認.json)|人工確認とSource SHAの正本|
|[抽出201.py](抽出201.py)|純q0と166原板の固定、原行照合、純特徴の恒久保存|
|[独立監査201.py](独立監査201.py)|特徴核を呼ばず、原板prefixの変化位置と直前完了ブロックから全純値・原行端を検算|

リポジトリ直下から既存のPython環境で実行する。通常のPython環境を使う場合は固定票の依存版をpipで導入する。`work/pythonlibs`の探索は互換用であり、通常環境にorjsonがあれば同フォルダは不要。

```powershell
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/板数量純特徴201/人工確認.py'
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/板数量純特徴201/抽出201.py' --stage prepare
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/板数量純特徴201/抽出201.py' --stage extract --scope 追加2 --workers 2
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/板数量純特徴201/抽出201.py' --stage extract --scope 全83 --workers 2
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/板数量純特徴201/独立監査201.py'
```

抽出は既存ファイルへ異なる内容を上書きせず停止する。元の純q0、原板、原板8列、既存Sourceを変更しない。Source/仕様を変える場合は版と保存先を分け、元の固定票を改変しない。

201の新しい特徴は旧OFI30/E08の再命名ではない。最良板更新16/64回の尺度、4完了Last時計ブロック、独立した受信時計の欠如を区別する。[元の非金融調査](../../docs/technical-analysis/市場心理/板数量を価格時計と分けて入口へ使う.md)も参照。
