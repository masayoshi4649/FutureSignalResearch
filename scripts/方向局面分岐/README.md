# 方向と局所帯を先に分ける比較

[54の検証計画](../../study/00054_方向と局所帯を先に分岐/検証計画.md)。固定53の18特徴・教師・準備を維持し、ZとDI候補方向の符号を先に分け、4群それぞれで17列深さ2を学習する。全体深さ4、新D0だけを旧53B0/F0と比較する。

Python3.14.3、NumPy2.5.3、scikit-learn1.9.1。[既存requirements](../技法分岐学習/requirements.txt)と専用venvを再利用し、GPUは使わない。既存の[53特徴](../局所帯分岐/特徴仕様.md)を変更しない。人工記録を保存してから条件・実装・入力を固定する。

```powershell
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/方向局面分岐/学習の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/方向局面分岐/接続の人工検査.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/方向局面分岐/保存物確認.py --self-test
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/方向局面分岐/検証.py --freeze
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/方向局面分岐/検証.py --run
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/方向局面分岐/保存物確認.py --run --viewer-url http://127.0.0.1:8092
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/方向局面分岐/レポート.py
work/venvs/technical-tree/Scripts/python.exe -X utf8 scripts/方向局面分岐/レポート.py --check
```

開始後は同じ本物学習/市場実行を繰り返さず、プロセスと保存物を確認する。新3保存モデルは最大12分類器fitを内包する。旧6モデル・旧92運用は保存参照であり、新規実行数へ足さない。
