"""境界28案の元帳を診断と照合し、実際に区別できた損切価格と成績を表にまとめる。"""
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = next((ROOT/"study").glob("00219_*"))


def main() -> None:
    """
    機能：原板全正常行の価格格子と28案の損切距離・決済、固定入口と1枠口座の成績を照合する。
    引数：なし。220境界の元帳、先に作成した初回到達小計、各場の原板索引を利用する。
    返り値：None。各案の照合済みの結果をMarkdown表へ書き出す。
    """
    groups = json.loads((ROOT/"work/220境界/比較元帳.json").read_bytes())
    summary = runpy.run_path(str(OLD/"出口を集計する.py"))
    prices = runpy.run_path(str(OLD/"経路診断/元の保有経路を測る.py"))
    diagnostics = json.loads((ROOT/"work/220経路診断/集計.json").read_bytes())
    base = groups["口座再生"]["IFD"]
    days = sorted({r["scene"] for r in base})
    files = prices["archives"]()
    for day in days:
        records = prices["load_records"](*files[day])
        valid = records[records["normal"]==1]
        for field in ("ask","bid"):
            assert np.all(valid[field]%10==0)
    # ----------------------------------------
    for mode, books in groups.items():
        for profit in ("P0","P3","P4","P5"):
            near,far = books["J2"+profit],books["J6"+profit]
            for unrounded, rounded in zip(near,far,strict=True):
                for field in ("scene","side","entry_line","entry_price","exit_line","exit_price","net","exit_reason"):
                    assert unrounded[field]==rounded[field]
                r = unrounded["width"]
                assert unrounded["initial_stop_points"]==.95*r
                assert rounded["initial_stop_points"]==5*np.ceil(.95*r/5)
        if mode=="入口固定":
            for j,percent in ((0,90),(2,95)):
                net = sum(t["net"] for t in books[f"J{j}P0"])
                assert net-1020063==diagnostics["全体"]["逆行"][str(percent)]["差"]
    cases = {}
    for code, ledger in groups["口座再生"].items():
        cases[code],_ = summary["evaluate"](days,base,groups["入口固定"][code],ledger)
    choice = summary["front_choice"](cases,[k for k in cases if k!="IFD"])
    lines = ["# 損切り境界28案の全成績","",
             "費用後の円。損失・日末最大下落額は正の額。全候補とも45日取得、損益不明0件。幅別の理論値と最初に満たし得る板価格は[結果の説明](境界の結果.md)を参照。","",
             "|候補|固定181収支|固定181損失|口座建玉|口座利益|口座損失|口座収支|最大1件損失|日末最大下落額|赤字日|前24日収支|後21日収支|末3日収支|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for code, case in cases.items():
        fixed, a = case["入口固定"],case["期間"]["全45日"]
        assert a["未知"]==0 and fixed["未知"]==0 and a["参加場"]==45
        fields = [fixed["収支"],fixed["損失"],a["取得"],a["利益"],a["損失"],a["収支"],
                  -case["最悪の確定建玉"][1],a["場末DD既知"],a["赤字場"]]
        fields += [case["期間"][k]["収支"] for k in ("前24日","後21日","直近3日")]
        lines.append("|"+code+"|"+"|".join(f"{v:,.0f}" for v in fields)+"|")
    lines += ["",f"前24日での選抜は{choice['選抜']}。適格な順は{'、'.join(choice['適格順位'])}。"]
    (HERE/"境界28案の全成績.md").write_text("\n".join(lines)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
