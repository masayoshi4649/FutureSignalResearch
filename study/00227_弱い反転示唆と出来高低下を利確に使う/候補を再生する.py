"""固定した入口と保護後の再開規則で、利確条件群を1枠口座に適用する。"""
from argparse import ArgumentParser
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LAST = runpy.run_path(str(next(HERE.parent.glob("00224_*/再エントリーを再生する.py"))))
FIELDS = ("scene","request_time","request_line","side","entry_time","entry_line","entry_price","width")


def main() -> None:
    """
    機能：当日の全判断から各条件を再生し、元の133取得・RCの決済タイミングと照合する。
    引数：CLIの定義（Path）は候補群、出力（Path）は元帳の保存先、候補（list[str]）は省略時に全件、
    執行秒（int）はRCと追加返済の最短遅延。
    返り値：None。金額と追加発動原行を含む口座元帳を書き出す。
    """
    parser = ArgumentParser()
    parser.add_argument("--定義",type=Path,required=True)
    parser.add_argument("--出力",type=Path,required=True)
    parser.add_argument("--候補",nargs="+")
    parser.add_argument("--執行秒",type=int,choices=(1,3,5),default=1)
    args = parser.parse_args()
    rules = runpy.run_path(str(args.定義))
    codes = args.候補 or rules["POLICIES"]
    assert set(codes)<=set(rules["POLICIES"])
    source = LAST["SOURCE"]
    reference = json.loads((ROOT/"work/224反対追試/口座元帳.json").read_bytes())
    dates = reference["対象場"]
    ref_books = reference["口座再生"]
    if args.執行秒!=1:
        delayed = json.loads((ROOT/"work/223反対追試/比較元帳.json").read_bytes())["入口固定"]
        ref_books = {f"RC{w}":delayed[f"R02L{args.執行秒}_{w}"] for w in (20,30)}
    books = {f"{code}C{w}":[] for code in codes for w in (20,30)}
    seen = set()
    for folder,archive,member,manifest in source["parts"]():
        scenes,arrays,*_ = source["inputs"](folder,archive,member)
        meta = {s["session"]:s for s in source["read"](manifest)["scenes"]}
        for i,scene in enumerate(scenes):
            name = scene["session"]
            if name not in dates or name in seen:
                continue
            seen.add(name)
            index = LAST["ENGINE"]["FINANCE"]["load_scene"](manifest.parent,meta[name])
            scene = dict(scene,量特徴の母集団=str(folder))
            orders = LAST["ENGINE"]["orders"](arrays,i,scene,index)
            fields = ("index","line","time","core","branches","mw","fw")
            ctx = rules["prepare_signals"](index,scene,{k:orders[2][k] for k in fields})
            ctx["執行秒"] = args.執行秒
            # 同じ群の全候補は当日の確定特徴を共用する。判断時には原行までの値だけを参照する。
            policy = {"prepare":lambda _index,_scene:ctx,"decide":rules["decide"]}
            policies = {code:(code,policy,"") for code in codes}
            accounts,_ = LAST["day"](arrays,i,scene,index,policies,("C",))
            for code,rows in accounts.items():
                ref = [t for t in ref_books["RC"+code[-2:]] if t["scene"]==name]
                for orig,t in zip(ref,rows,strict=True):
                    assert all(orig[k]==t[k] for k in FIELDS)
                    assert t["exit_index"]<=orig["exit_index"] and t["net"] is not None
                    assert t["extra_fill"]==(t["exit_index"]<orig["exit_index"])
                    if not t["extra_fill"]:
                        assert (t["net"],t["status"])==(orig["net"],orig["status"])
                books[code].extend(rows)
    assert seen==set(dates) and all(len(b)==133 for b in books.values())
    args.出力.mkdir(parents=True,exist_ok=True)
    (args.出力/"口座元帳.json").write_text(json.dumps({"対象場":dates,"執行秒":args.執行秒,"口座再生":books},ensure_ascii=False,
                                             allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
