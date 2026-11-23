"""224の元の価格到達待ちを共通化し、シグナルの5条件を同じ133取得で比較する。"""
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LAST = runpy.run_path(str(next(HERE.parent.glob("00224_*/再エントリーを再生する.py"))))
POLICY = runpy.run_path(str(HERE/"出口条件.py"))
FIELDS = ("scene","side","width","request_line","request_time","entry_line","entry_time","entry_price")
EXIT = ("exit_line","exit_time","exit_price","status","net","confirmed_until","activated","activation_time","trigger_time")


def main() -> None:
    """
    機能：五つの対照を224の予約制御で実行し、元取得・原R02・広幅のみの履歴と照合する。
    引数：なし。222の単純IFD、224の本試行と反対信号の追試を読む。
    返り値：None。work/226方向時刻の口座元帳と各返済後の休止記録を保存する。
    """
    baseline = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    wide = json.loads((ROOT/"work/224再開/口座元帳.json").read_bytes())["口座再生"]
    original = json.loads((ROOT/"work/224反対追試/口座元帳.json").read_bytes())["口座再生"]
    dates = baseline["対象場"]
    accounts = {name+"C"+str(w):[] for name in POLICY["POLICIES"] for w in (20,30)}
    audits = {}
    source = LAST["SOURCE"]
    families = {code:(code,POLICY,"") for code in POLICY["POLICIES"]}
    for folder,archive,member,manifest in source["parts"]():
        scenes,arrays,*_ = source["inputs"](folder,archive,member)
        references = {r["session"]:r for r in source["read"](manifest)["scenes"]}
        for i,scene in enumerate(scenes):
            name = scene["session"]
            if name not in dates or name in audits:
                continue
            index = LAST["ENGINE"]["FINANCE"]["load_scene"](manifest.parent,references[name])
            result,audits[name] = LAST["day"](arrays,i,scene,index,families,("C",))
            for code,rows in result.items():
                accounts[code].extend(rows)
    # ----------------------------------------
    assert set(audits)==set(dates)
    for code,rows in accounts.items():
        w = code[-2:]
        base = baseline["口座再生"]["I"+w]
        assert len(rows)==len(base)==133 and all(r["net"] is not None for r in rows)
        assert all(all(a[k]==b[k] for k in FIELDS) for a,b in zip(rows,base,strict=True))
        if code[:2] in ("X1","X5"):
            comparison = original["RC"+w] if code[:2]=="X1" else wide["PC"+w]
            assert all(all(a[k]==b[k] for k in FIELDS+EXIT) for a,b in zip(rows,comparison,strict=True))
    work = ROOT/"work/226方向時刻"
    work.mkdir(parents=True,exist_ok=True)
    for name,data in (("口座元帳",{"対象場":dates,"口座再生":accounts}),("予約照合",audits)):
        (work/(name+".json")).write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
