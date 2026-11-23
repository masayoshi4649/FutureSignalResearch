# 局所帯の反応で先に分岐する比較

[53の計画](../../study/00053_局所帯の反応で先に分岐/検証計画.md)。前10本の3分足で固定した帯へ、後5本の終値がどう反応したかを使う。共通準備で17列自由木B0と、反応旗を根に固定する18列F0を比較する。F0の子木は17列の深さ3である。

Python3.14.3、NumPy2.5.3、scikit-learn1.9.1。[既存requirements](../技法分岐学習/requirements.txt)と専用venvを再利用する。GPUは使わない。人工成功の記録を保存し、設計・実装・入力を固定してから本物学習・市場再生を一度だけ実行する。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/局所帯分岐/特徴の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/局所帯分岐/学習の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/局所帯分岐/接続の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/局所帯分岐/保存物確認.py --self-test
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/局所帯分岐/検証.py --freeze
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/局所帯分岐/検証.py --run
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/局所帯分岐/保存物確認.py --run --viewer-url http://127.0.0.1:8092
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/局所帯分岐/レポート.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/局所帯分岐/レポート.py --check
```

開始済みなら既存プロセスと保存物を確認し、再実行しない。旧52/51/50/49の固定保存物は変更しない。全66場が既使用で、結果の「学習」は初期20場を除く後半20場の時系列検査を指す。
