"""旧BOに限定して実側の回復を確認し、元の出口・再開条件で全注文を再生する。"""
from collections import Counter
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
R = runpy.run_path(str(HERE/"順行入口を再生する.py"))
ROOT,SOURCE = R["ROOT"],R["SOURCE"]
WORK = ROOT/"work/228回復入口"


def old_bo(part: int, folder: Path, arrays: dict) -> np.ndarray:
    """
    機能：元179のBO出生かつ199_02で独自に保留・確認した入口でないという純粋な来歴を特定する。
    引数：part（int）は入力群、folder（Path）は特徴量の場所、arrays（dict）は199の時系列。
    返り値：np.ndarray。旧BOの元来の方向で残った判断行。
    """
    if part < 4:
        labels = ("旧73","追加7","本日1")
        path = (ROOT/"work/199保留中の旧幹確認"/(labels[part]+"_純成立診断.json.gz") if part<3
                else ROOT/"work/199追加二場の固定診断/追加二場純診断.json.gz")
        data = SOURCE["read"](path)
        base,changed = data["E199_00"],data["E199_02"]
    else:
        import NK純接続194 as nk
        import rules195
        features,captures,_ = nk.common().P.B.P.R168.BASE.load_features(folder)
        clocks = SOURCE["COMPACT"](features,captures)
        assert np.array_equal(clocks["line"],arrays["line"])
        with np.load(folder.parent/"基準179.npz") as a:
            bundle = dict(birth={k:a[k] for k in ("core","branches","technical","tier")},
                          **{k:a[k] for k in ("mw","fw","hi","added")})
        variants = rules195.build(features,bundle,["E195_00","E195_05"])
        base,changed = [variants["diagnostics"][k] for k in ("E195_00","E195_05")]
        assert np.array_equal(variants["bundles"]["E195_05"]["birth"]["core"],arrays["core"])
    old = np.asarray(base["bo_setup"],bool)
    for k in ("guarded","reverse_confirmed","follow_confirmed"):
        old &= ~np.asarray(changed[k],bool)
    return old & (arrays["core"]!=0) & (arrays["branches"]==0) & ~arrays["added"]


def rule(allowed: tuple, bo: np.ndarray, features: dict, columns: list, code: str) -> tuple:
    """
    機能：その場での見送り又は新判断までの監視から、元注文を変更した1分判断の列を作る。
    引数：allowed（tuple）は待機済み原要求、bo（np.ndarray）は旧BO、features（dict）・columns（list）は
    当時値と列名、code（str）はK1〜K3。返り値：tuple。新しい予約入力、見送りと後刻の確認の原行番号。
    """
    keys,captures,a = allowed
    sides,recovery = {},{}
    for which,side in (("buy",1),("sell",-1)):
        sides[side] = R["vetoes"](features[which],columns)
        x = dict(zip(columns,features[which].T,strict=True))
        recovery[side] = ((x["q0_entry_prior3_percent_to_side"]>=.5) &
                          (x["m1_body_ratio_to_side"]>0) & (x["m1_close_delta_atr5_to_side"]>0))
    flag = 3 if code=="K1" else 1
    masks = [bo & sides[sign][flag] & (True if code=="K1" else ~recovery[sign]) for sign in (1,-1)]
    changed,hit = R["modified"](allowed,*masks,False)
    mark = {"見送り":a["line"][hit].tolist(),"新判断":{}}
    if code!="K2":
        return changed,mark
    # ----------------------------------------
    new = dict(changed[2])
    for k in ("mw","fw","hi","tier"):
        new[k] = new[k].copy()
    pending = -1
    for i,stamp in enumerate(a["time"]):
        if hit[i]:
            pending = i
            continue
        if pending<0:
            continue
        if stamp-a["time"][pending]>180 or a["core"][i]!=0 or a["technical"][i]!=0:
            pending = -1
            continue
        sign = int(a["core"][pending])
        if stamp>a["time"][pending] and recovery[sign][i]:
            for k in ("core","branches","mw","fw","hi","added","tier"):
                new[k][i] = a[k][pending]
            mark["新判断"][str(a["line"][i])] = int(a["line"][pending])
            pending = -1
    return (keys,captures,new),mark


def audit_reverse(index: object, arrays: dict, rows: list, hits: set) -> list:
    """
    機能：E4の実反転について生の板で元の方向、元と反対方向の取得側、経過秒、清算側、損益を検算する。
    引数：index（PriceIndex）は板、arrays（dict）は当場の元要求、rows（list）は当場元帳、
    hits（set）は当場の反転判断行。返り値：list。実反転の確認結果（正常BBOの行）。
    """
    confirmed = []
    for t in rows:
        if t["request_line"] not in hits:
            continue
        event, = np.flatnonzero(arrays["line"]==t["request_line"])
        entry,end,side = t["entry_index"],t["exit_index"],t["side"]
        assert arrays["q1_index"][event]==entry and arrays["core"][event]==(1 if side==1 else -1)
        q0 = arrays["time"][event]
        first = index.normal[np.searchsorted(index.times[index.normal],q0+1)]
        assert entry==first and index.rows["normal"][entry] and index.rows["normal"][end]
        assert q0+1<=t["entry_time"]<q0+30 and arrays["index"][event]<entry
        open_column,close_column,sign = ("ask","bid",1) if side==0 else ("bid","ask",-1)
        assert t["entry_price"]==index.rows[open_column][entry] and t["exit_price"]==index.rows[close_column][end]
        assert (t["exit_price"]-t["entry_price"])*100*sign-1077==t["net"]
        confirmed.append([t["request_line"],t["side"],t["entry_price"],t["exit_price"],t["net"]])
    return confirmed


def main() -> None:
    """
    機能：45デイの旧BO来歴を解決し、両出口・両待機のK案の元帳とE4の独立確認を記録する。
    引数：なし。変更前元資料とE0〜E4の元帳を使う。
    返り値：None。作業領域に口座元帳と変更判断を保存する。
    """
    original = SOURCE["read"](R["WORK"]/"口座元帳.json")
    hits = SOURCE["read"](R["WORK"]/"当時の変更判断原行.json")
    dates = original["対象場"]
    books,markers,audit,changed_types = {},{},{},Counter()
    for part,(folder,archive,member,manifest) in enumerate(SOURCE["parts"]()):
        scenes,arrays,values,columns,_ = SOURCE["inputs"](folder,archive,member)
        bo = old_bo(part,folder,arrays)
        pointers = {r["session"]:r for r in SOURCE["read"](manifest)["scenes"]}
        for number,scene in enumerate(scenes):
            name = scene["session"]
            if name not in dates or name in markers:
                continue
            markers[name],audit[name] = {},{}
            index = R["ENGINE"]["FINANCE"]["load_scene"](manifest.parent,pointers[name])
            stream = R["ENGINE"]["orders"](arrays,number,scene,index)
            active = (arrays["scene"]==number) & (arrays["time"]<scene["end"]-960)
            options = R["exit_options"](stream[2],scene,index)
            for wait in (20,30):
                allowed = R["BASE"]["after_open"](stream,scene["start"]+wait*60)
                selected = active & (arrays["time"]>=scene["start"]+wait*60)
                assert np.array_equal(allowed[2]["line"],arrays["line"][selected])
                features = {side:v[selected] for side,v in values.items()}
                for c in ("K1","K2","K3"):
                    adjusted,marks = rule(allowed,bo[selected],features,columns,c)
                    markers[name][f"{c}_{wait}"] = marks
                    rc,ifd = R["replay_pair"](adjusted,scene,index,options)
                    books.setdefault(f"{c}RC{wait}",[]).extend(rc)
                    books.setdefault(f"{c}I{wait}",[]).extend(ifd)
                for exit_ in ("RC","I"):
                    key = f"E4{exit_}{wait}"
                    rows = [t for t in original["口座再生"][key] if t["scene"]==name]
                    audit[name][key] = audit_reverse(index,stream[2],rows,set(hits[name]["E4"]))
            for t in original["口座再生"]["E0RC20"]:
                if t["scene"]!=name or t["request_line"] not in hits[name]["E3"]:
                    continue
                event, = np.flatnonzero(active & (arrays["line"]==t["request_line"]))
                changed_types["旧BO" if bo[event] else "他の出生"] += 1
    assert set(dates)==set(markers)
    WORK.mkdir(parents=True,exist_ok=True)
    for f,data in (("口座元帳",{"対象場":dates,"口座再生":books}),("回復判断",markers),
                   ("反転照合",{"元E3該当の取得":dict(changed_types),"実反転":audit})):
        (WORK/(f+".json")).write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
