# 技法特徴の浅い分岐学習

[試行51](../../study/00051_技法特徴の浅い分岐学習/検証計画.md)の再利用コード。特徴は当時の50保存枠、教師は49B±、運用は49Oを使い、固定モジュールの大域値を変更しない。

`特徴.py`は価格/技法の15列、`学習.py`は同一木による方向正規化・JSON保存予測、`検証.py`は過去学習→後続評価の接続、`保存物確認.py`は保存物監査、`レポート.py`は正本からの表示を担当する。

Python 3.14.3。作業領域の専用venvを使う。NumPyは同じ2.5.3を共有し、他の依存版はrequirements.txtへ固定する。GPUは必要としない。

```powershell
C:/Python314/python.exe -m venv --system-site-packages work/venvs/technical-tree
work/venvs/technical-tree/Scripts/python.exe -m pip install -r scripts/技法分岐学習/requirements.txt
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/技法分岐学習/特徴の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/技法分岐学習/学習の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/技法分岐学習/接続の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/技法分岐学習/保存物確認.py --self-test
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/技法分岐学習/検証.py --freeze
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/技法分岐学習/検証.py --run
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/技法分岐学習/保存物確認.py --run --viewer-url http://127.0.0.1:8092
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/技法分岐学習/レポート.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/技法分岐学習/レポート.py --check
```

学習前固定・本物学習・運用は一度だけ。開始済みなら既存プロセスと成果物を確認し、成果物を消して再実行しない。過去の教師を同じ期間へ再評価した率を後続検査へ混ぜない。
