# 指数間純特徴206

金融ラベルを参照せず、NK225/TOPIXの同じ固定端点でのlog returnと差を生成する。[仕様](仕様.md)、[恒久入力](../../inputs/00206_両指数の固定端点相対変化/README.md)を参照する。

```powershell
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/指数間純特徴206/人工確認.py'
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/指数間純特徴206/抽出206.py' --prepare --run
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/指数間純特徴206/独立確認206.py'
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/指数間純特徴206/実prefix確認206.py'
& 'work/複合テクニカル学習環境/Scripts/python.exe' -X utf8 'scripts/指数間純特徴206/品質を要約する.py'
```

Python 3.14.3、NumPy 2.5.4、tzdata 2026.6を使用。原板再抽出やGPUは不要。既存成果物がある場合は一致確認し、異なる値で上書きしない。固定Source・元入力を変更せず再現する。独立確認は生産核を呼ばず、別の走査・二分探索・窓内最大差計算を使う。実prefix確認は生産核への未来切落し・未来価格変更であり、別の算術による独立検査とは区別する。

旧価格時計Sourceは[保存済みZIP](../../docs/データ監査/指数間の価格時計可用性/Source.zip)から読み、既存の同秒初回系列との同体対照だけを呼ぶ。新しい金融条件をここへ追加しない。
