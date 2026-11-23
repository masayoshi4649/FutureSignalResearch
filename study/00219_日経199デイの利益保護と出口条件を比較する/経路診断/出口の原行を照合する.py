"""出口定義を実行せず、採用された決済と含み損益の金額・時計を正常原行から独立に照合する。"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = runpy.run_path(str(HERE/"元の保有経路を測る.py"))


def verify(records: np.ndarray, trade: dict) -> None:
    """
    機能：新規・返済・極値の最初の日時・純損益・動的発動から約定までの原行を突き合わせる。
    引数：records（np.ndarray）は価格原行、trade（dict）は候補とモードの単一の建玉。
    返り値：None。未知は実現費用・決済が空であることを確認し、推定約定を補わない。
    """
    t = trade
    first = t["entry_index"]
    side = t["side"]
    assert records["normal"][first] == 1
    assert records["time"][first] == t["entry_time"] and records["source_line"][first] == t["entry_line"]
    assert records["ask" if side==0 else "bid"][first] == t["entry_price"]
    if t["net"] is None:
        assert t["exit_index"] == t["exit_line"] == -1 and t["exit_time"] is None and t["exit_price"] is None
        return
    end = t["exit_index"]
    assert records["normal"][end] == 1 and records["time"][end] == t["exit_time"] and records["source_line"][end] == t["exit_line"]
    sample = records[first:end+1]
    path = sample[sample["normal"]==1]
    price = path["bid" if side==0 else "ask"]
    score = (price-t["entry_price"])*(100 if side==0 else -100)-1077
    assert price[-1] == t["exit_price"] and score[-1]==t["net"] and t["gross"]-1077==t["net"]
    for typ,i in (("max",int(np.argmax(score))),("min",int(np.argmin(score)))):
        assert score[i]==t[typ+"_unrealized_net"] and path["time"][i]==t[typ+"_unrealized_time"]
    if t["status"]==5:
        signal = t.get("trigger_index")
        if signal is not None:
            assert first<signal<end and records["normal"][signal]==1 and records["time"][signal]==t["trigger_time"]
        else:
            assert np.any((path["time"]==t["trigger_time"]) & (path["source_line"]>t["entry_line"]))
        valid = path[path["time"]>=t["trigger_time"]+1]
        assert len(valid) and valid["source_line"][0] == t["exit_line"]


def main() -> None:
    """
    機能：指定する元帳と方策IDの全建玉を2モードで検算する。
    引数：CLIの組（str列）は作業領域名/候補ID、例 219遅延長/L10。
    返り値：None。照合数と既知・未知・動的返済数を指定ファイルへ書く。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("組",nargs="+")
    parser.add_argument("--出力",type=Path,default=ROOT/"work/219経路/出口照合.json")
    args = parser.parse_args()
    by_scene = defaultdict(list)
    counts = {}
    cache = {}
    for spec in args.組:
        folder,policy = spec.split("/")
        if folder not in cache:
            cache[folder] = json.loads((ROOT/"work"/folder/"比較元帳.json").read_bytes())
        for mode,options in cache[folder].items():
            policies = options.keys() if policy == "全案" else [policy]
            for code in policies:
                book = options[code]
                counts[folder+"/"+code+"/"+mode] = {"建玉":len(book),"未知":sum(t["net"] is None for t in book),
                                                  "動的返済":sum(t["status"]==5 for t in book)}
                for t in book:
                    by_scene[t["scene"]].append(t)
    archives = SOURCE["archives"]()
    for scene,rows in by_scene.items():
        records = SOURCE["load_records"](*archives[scene])
        checked = set()
        for t in rows:
            # 原行、時刻、気配、極値、発動原行がすべて同一の記録は1回照合する。
            fields = ("entry_index","entry_line","side","entry_price","entry_time","exit_index","exit_line",
                      "exit_price","exit_time","net","gross","status","trigger_time","trigger_index",
                      "max_unrealized_net","min_unrealized_net","max_unrealized_time","min_unrealized_time")
            fingerprint = tuple(t.get(name) for name in fields)
            if fingerprint not in checked:
                verify(records,t)
                checked.add(fingerprint)
    args.出力.parent.mkdir(parents=True,exist_ok=True)
    args.出力.write_text(json.dumps(counts,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("検算した建玉",sum(a["建玉"] for a in counts.values()))


if __name__=="__main__":
    main()
