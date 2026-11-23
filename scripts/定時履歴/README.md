# 定時判断へ価格履歴を追加する比較

[52の固定前計画](../../study/00052_定時判断へ価格履歴を追加/検証計画.md)。旧51の現在特徴に、当時既知のOR両端への最大10本3分の内外切替を追加する。未発生と履歴不足を区別し、共通準備の15特徴C0と25特徴H0を比較する。

Python3.14.3、NumPy2.5.3、scikit-learn1.9.1。依存は[51のrequirements](../技法分岐学習/requirements.txt)と同じで、既存の専用venvを使う。GPUは使わない。履歴・学習の人工検査と監査人工を先に実行し、人工確認JSONを保存してから固定する。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時履歴/履歴の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時履歴/学習の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時履歴/接続の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時履歴/保存物確認.py --self-test
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時履歴/検証.py --freeze
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時履歴/検証.py --run
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時履歴/保存物確認.py --run --viewer-url http://127.0.0.1:8092
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時履歴/レポート.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/定時履歴/レポート.py --check
```

開始済みなら既存プロセスを確認し、再実行しない。旧51/50/49の実装・正本・指紋は変更しない。表の「学習」は初期20場を除いた後半20場の時系列検査を意味する。
