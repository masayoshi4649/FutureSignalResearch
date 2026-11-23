"""デイの対象時間中、実際に観察できた完成1分足と技術サインの分布を確認する。"""
import json
from pathlib import Path
import runpy

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RULE = runpy.run_path(str(HERE/"出口条件.py"))
TOOLS = runpy.run_path(str(HERE.parent/"出口を比較する.py"))


def main() -> None:
    """
    機能：45日の原板・当時の足参照・現物CSVを照合し、足の利用可否とサイン数を場別に計数する。
    引数：なし。参照する場と原板は単純IFDと同じ。
    返り値：なし。日別の件数、元CSVのSHA256を作業領域に出力する。
    """
    baseline = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    days = set(baseline["対象場"])
    seen = {}
    for folder,_,_,manifest in TOOLS["SOURCE"]["parts"]():
        scenes = TOOLS["SOURCE"]["read"](folder/"固定取得入力.json.gz")["scenes"]
        lookup = {d["session"]:d for d in TOOLS["SOURCE"]["read"](manifest)["scenes"]}
        for scene in scenes:
            day = scene["session"]
            if day not in days or day in seen:
                continue
            index = TOOLS["ENGINE"]["FINANCE"]["load_scene"](manifest.parent,lookup[day])
            ctx = RULE["prepare"](index,scene)
            summary = {"SHA256":ctx["csv_sha"]}
            for wait in (20,30):
                opened,cut = scene["start"]+60*wait,scene["end"]-900
                valid = (ctx["stamp"]>=opened) & (index.times<cut)
                obs = np.flatnonzero(valid)
                assert len(np.unique(ctx["stamp"][obs]))==len(obs)
                large = ctx["state"][0,3,obs]
                count = {"分数":(cut-opened)//60,"参照足":len(obs),"出来高急増":int(large.sum())}
                for j,label in enumerate(("買い","売り")):
                    opposite,broken,reject,_ = ctx["state"][j][:,obs]
                    follow = ctx["confirm"][j,1,obs]>=opened
                    count[label] = {"逆足":int(opposite.sum()),"逆足と量":int((opposite&large).sum()),
                                    "逆足と下抜けと量":int((opposite&broken&large).sum()),
                                    "試し失敗":int(reject.sum()),"試し失敗と量":int((reject&large).sum()),
                                    "二段確認と量":int(follow.sum())}
                summary[wait] = count
            seen[day] = summary
    # ----------------------------------------
    assert days==set(seen)
    output = ROOT/"work/223量/出来高の利用可能範囲.json"
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(seen,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
