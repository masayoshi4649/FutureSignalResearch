"""R02の追尾起動・発動・決済を、候補定義を呼ばずに一つずつ正常気配を進めて検算する。"""
from collections import deque
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENGINE = runpy.run_path(str(HERE.parent/"出口を比較する.py"))


def inspect(index: object, alerts: list, trade: dict, term: dict, original: dict) -> tuple:
    """
    機能：まだ発生していないシグナルを読まず、直近二つとその後の清算側気配から返済を照合する。
    引数：index（PriceIndex）は原板、alerts（list）は主入口の原行と符号、trade・term・original（dict）
    は検算対象・観測限界・元IFD。返り値：tuple。最初の起動・発動・実返済の行番号。
    """
    first = trade["entry_index"]
    end = min(term["touch_end"],original["exit_index"])
    pos = 0
    while pos<len(alerts) and alerts[pos][0]<=first:
        pos += 1
    recent = deque(maxlen=2)
    normal = index.normal
    begin,stop = normal.searchsorted([first+1,end])
    side = 1 if trade["side"]==0 else -1
    price = index.rows["bid" if side==1 else "ask"]
    width,entry = trade["width"],trade["entry_price"]
    peak = narrow_peak = floor = float("-inf")
    armed = triggered = None
    narrow = False
    exit_row = original["exit_index"]
    for row in normal[begin:stop]:
        now = index.times[row]
        while pos<len(alerts) and alerts[pos][0]<=row:
            recent.append(alerts[pos])
            pos += 1
        if triggered is not None:
            if now>=index.times[triggered]+1:
                exit_row = int(row)
                break
            continue
        move = side*(price[row]-entry)
        peak = max(peak,move)
        was_armed = armed is not None
        if len(recent)==2 and recent[0][1]==recent[1][1]==-side:
            fresh = now-index.times[recent[0][0]]<=180 and now-index.times[recent[1][0]]<=90
            narrow = narrow or (fresh and peak>=.25*width and move>=20)
        if narrow:
            narrow_peak = max(narrow_peak,move)
            floor = max(floor,20,narrow_peak-.25*width)
        if peak>=.95*width:
            floor = max(floor,20,peak-.80*width)
        if armed is None and floor>float("-inf"):
            armed = int(row)
        if was_armed and move<=floor:
            triggered = int(row)
    expected = (trade["activation_index"],trade["trigger_index"],trade["exit_index"])
    found = (-1 if armed is None else armed,-1 if triggered is None else triggered,exit_row)
    assert found==expected,(trade["scene"],first,found,expected)
    return armed,triggered,exit_row


def main() -> None:
    """
    機能：45日の単純IFDで取った全建玉とR02で追加取得した建玉を原行順の別計算で照合する。
    引数：なし。試行223の反対信号の比較元帳を使う。
    返り値：None。重複を除く照合数と発動数を作業領域に記録する。
    """
    source,engine = ENGINE["SOURCE"],ENGINE["ENGINE"]
    data = json.loads((ROOT/"work/223反対/比較元帳.json").read_bytes())
    unique = {}
    for books in data.values():
        for wait in (20,30):
            for trade in books[f"R02_{wait}"]:
                key = tuple(trade[k] for k in ("scene","entry_index","side","width"))
                unique[key] = trade
    checked = set()
    for folder,archive,member,manifest in source["parts"]():
        scenes,arrays,*_ = source["inputs"](folder,archive,member)
        meta = {s["session"]:s for s in source["read"](manifest)["scenes"]}
        for i,scene in enumerate(scenes):
            sample = [(k,t) for k,t in unique.items() if k[0]==scene["session"] and k not in checked]
            if not sample:
                continue
            index = engine["FINANCE"]["load_scene"](manifest.parent,meta[scene["session"]])
            s = engine["orders"](arrays,i,scene,index)[2]
            alerts = [(int(r),int(d)) for r,d,b,m,f in zip(s["index"],s["core"],s["branches"],s["mw"],s["fw"],strict=True)
                      if d!=0 and (m if b==0 else f)>0]
            cut = scene["end"]-900
            force = engine["FINANCE"]["closing"](index,cut)
            for key,t in sample:
                ent = t["entry_index"]
                term = engine["FINANCE"]["early179"].terminal(index,ent,float("inf"),cut,force)
                orig = engine["FINANCE"]["settle"](index,ent,t["side"],t["width"],"SESSION",cut,force,"NK225")
                assert orig["exit_index"]>=0
                inspect(index,alerts,t,term,orig)
                checked.add(key)
    assert set(checked)==unique.keys()
    counts = {"固有取得":len(checked),"追尾起動":sum(t["activation_index"]>=0 for t in unique.values()),
              "追尾発動":sum(t["trigger_index"]>=0 for t in unique.values()),
              "追尾返済":sum(t["status"]==5 for t in unique.values())}
    print(json.dumps(counts,ensure_ascii=False))


if __name__=="__main__":
    main()
