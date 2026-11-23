"""元のIFD二注文、分期限の延長、完成足による利益保護を同じ口座で組み合わせる。"""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ORIGINAL = runpy.run_path(str(HERE/"分期限を延長する.py"))
ROOT, ENGINE, STATIC = ORIGINAL["ROOT"], ORIGINAL["ENGINE"], ORIGINAL["POLICY"]
EXISTING = runpy.run_path(str(next((ROOT/"study").glob("00220_*/主比較/出口条件.py"))))
CODES = ["T01","T02","T03","T04","T05","T06"]
DELAYS = [1,3,5]


def after_sixty(code: str, context: dict, index: object, entry: int, side: int, width: float,
                horizon: str, term: dict) -> dict:
    """
    機能：予定60分以後の最初の正常板から順行を測り、失速すれば実側気配で追尾返済する。
    引数：code・horizon（str）は設定と延長期限、context・term（dict）は当時の完成足と価格終端、
    index（PriceIndex）は原板、entry・side（int）は取得行と向き、width（float）は元片幅。
    返り値：dict。決済行、起動・発動、静的注文幅、保護床。
    """
    strategy,delay = code.split("_")
    if strategy in ("T01","T02"):
        return EXISTING["settle"]("P2",width,context,index,entry,side,width,horizon,term,int(delay))
    result = STATIC["decide"]("D00",context,index,entry,side,width,horizon,term)
    result.update(activated=False,activation_time=None,activation_index=-1,trigger_time=None,
                  trigger_index=-1,trigger_reason=None,floor_points=None)
    if strategy=="T06":
        return result
    end = result["exit_index"] if result["exit_index"]>=0 else term["touch_end"]
    due = index.times[entry]+3600
    first = int(index.times.searchsorted(due,side="left"))
    left,right = np.searchsorted(index.normal,[first,min(end,term["touch_end"])])
    ids = index.normal[left:right]
    if not len(ids):
        return result
    # ----------------------------------------
    times = index.times[ids]
    sign = 1 if side==0 else -1
    opened = float(index.rows["ask" if side==0 else "bid"][entry])
    move = sign*(index.rows["bid" if side==0 else "ask"][ids]-opened)
    peak = np.maximum.accumulate(move)
    active = peak>=.45*width
    if not np.any(active):
        return result
    gap = np.where(context["squeeze"][side,context["bar"][ids]],.35,.65)*width
    floors = np.maximum.accumulate(np.where(active,np.maximum(20.0,peak-gap),-np.inf))
    start = int(active.argmax())
    result.update(activated=True,activation_time=float(times[start]),activation_index=int(ids[start]),
                  floor_points=float(floors[-1]))
    crossed = (move<=floors) & np.r_[False,active[:-1]]
    if np.any(crossed):
        trigger = int(crossed.argmax())
        result.update(trigger_time=float(times[trigger]),trigger_index=int(ids[trigger]),
                      trigger_reason="延長後の利益保護",floor_points=float(floors[trigger]))
        fill = int(np.searchsorted(times,times[trigger]+int(delay)))
        if fill<len(ids):
            result.update(exit_index=int(ids[fill]),status=5,reason="延長後の利益保護")
    return result


def survives(index: object, entry: int, side: int, width: float, due: float, closing_request: float) -> bool:
    """
    機能：予定60分直前までの情報で、静的先着・既発生の観測中断・場末返済要求のない建玉を判別する。
    引数：index（PriceIndex）は原板、entry・side（int）は新規行と向き、width・due・closing_request（float）は
    元片幅、予定60分の時計と場末の強制返済を要求する時計。
    返り値：bool。予定時刻ちょうどの板やその後の返済可否は評価しない。
    """
    if due>=closing_request:
        return False
    end = int(index.times.searchsorted(due,side="left"))
    last = index.last_normal(entry,end)
    allowed_gap = ENGINE["FINANCE"]["early179"].CONFIG["価格BBO最大gap秒"]
    if due-index.times[last]>allowed_gap:
        return False
    for gaps in (index.price_gaps,index.bbo_gaps):
        pos = int(gaps.searchsorted(entry,side="right"))
        if pos<len(gaps) and gaps[pos]<end:
            return False
    price = float(index.rows["ask" if side==0 else "bid"][entry])
    return index.first_outside(entry+1,end,price-width,price+width,side)<0


def by_scene(index: object, scene: dict, static: object) -> object:
    """
    機能：60分時点直前の実側気配と既発表の経路効率を取得し、延長の判断を返済と接続する。
    引数：index（PriceIndex）・scene（dict）は場の原板・定義、static（callable）は元IFDの再生関数。
    返り値：callable。口座エンジンに渡す当日の期限選択・保護関数。
    """
    context = EXISTING["prepare"](index,scene)
    dynamic = ENGINE["exits"](index,scene,{"prepare":lambda _i,_s:context,"decide":after_sixty})
    normal_times = index.times[index.normal]

    @lru_cache(maxsize=None)
    def at(code: str, entry: int, side: int, width: float, horizon: str) -> dict:
        """
        機能：保持期限とその延長の判断に応じて返済し、元の期限と判断時刻も記録する。
        引数：code・horizon（str）は条件と元期限、entry・side（int）は取得行と側、width（float）は片幅。
        返り値：dict。返済結果と延長理由。分岐には60分直前までに記録された板だけを用いる。
        """
        strategy = code.split("_")[0]
        chosen,extended,eligible,quote_time,mark_r,eff = horizon,False,False,None,None,None
        if strategy in ("T01","T02"):
            chosen = horizon if strategy=="T01" else "SESSION"
            trade = dynamic(code,entry,side,width,chosen)
            extended = chosen!=horizon
        else:
            due = float(index.times[entry]+3600)
            eligible = horizon=="H60" and survives(index,entry,side,width,due,scene["end"]-960)
            if eligible:
                prior = int(normal_times.searchsorted(due,side="left"))-1
                if prior>=0 and due-normal_times[prior]<=30:
                    row = int(index.normal[prior])
                    sign = 1 if side==0 else -1
                    price = index.rows["bid" if side==0 else "ask"][row]
                    entry_price = index.rows["ask" if side==0 else "bid"][entry]
                    mark_r = float(sign*(price-entry_price)/width)
                    quote_time = float(normal_times[prior])
                    minute = int((due-context["start"])//60)
                    efficiency = float(sign*context["er"][minute])
                    eff = efficiency if np.isfinite(efficiency) else None
                    assert quote_time<due
                permissive = mark_r is not None and mark_r>=-.25
                confirmed = permissive and (mark_r>=.25 or (eff is not None and eff>=.15))
                extended = strategy=="T03" or (strategy in ("T04","T06") and permissive) or (strategy=="T05" and confirmed)
            if extended:
                chosen = "SESSION"
                trade = dynamic(code,entry,side,width,chosen)
            else:
                trade = static("D00",entry,side,width,horizon)
        return dict(trade,horizon=horizon,exit_horizon=chosen,exit_strategy=code,
                    extended=extended,eligible_for_extension=eligible,extension_quote_time=quote_time,
                    extension_mark_r=mark_r,extension_efficiency=eff)
    return at


def main() -> None:
    """
    機能：6候補を1・3・5秒で同じ原板から再生し、同じ入口に固定した診断と単一口座を照合する。
    引数：なし。D04と元IFDの元帳および219と同一の入力を利用する。
    返り値：None。主結果・遅延の元帳と再現指紋を作業領域に書き出す。
    """
    control = ROOT/"work/221期限寄与/比較元帳.json"
    old = json.loads(control.read_bytes())
    keys = [f"{code}_{lag}" for code in CODES for lag in DELAYS]
    books = {mode:{"IFD":group["IFD"],**{code:[] for code in keys}} for mode,group in old.items()}
    base = old["口座再生"]["IFD"]
    days = {t["scene"] for t in base}
    done = set()
    source = ENGINE["SOURCE"]
    for folder,archive,member,manifest in source["parts"]():
        scenes,arrays,*_ = source["inputs"](folder,archive,member)
        lookup = {row["session"]:row for row in source["read"](manifest)["scenes"]}
        for i,scene in enumerate(scenes):
            day = scene["session"]
            if day not in days or day in done:
                continue
            done.add(day)
            index = ENGINE["FINANCE"]["load_scene"](manifest.parent,lookup[day])
            stream = ENGINE["orders"](arrays,i,scene,index)
            static = ENGINE["exits"](index,scene,STATIC)
            refs = [t for t in base if t["scene"]==day]
            rows,_ = ENGINE["replay"](stream,scene,"IFD",static)
            assert all(all(a[k]==b[k] for k in ORIGINAL["KEYS"]) for a,b in zip(rows,refs,strict=True))
            settle = by_scene(index,scene,static)
            for code in keys:
                rows,_ = ENGINE["replay"](stream,scene,code,settle)
                books["口座再生"][code].extend(rows)
                for t in refs:
                    changed = settle(code,t["entry_index"],t["side"],t["width"],t["horizon"])
                    books["入口固定"][code].append(dict(t,**changed))
    assert done==days and len(done)==45
    # ----------------------------------------
    prior_file = ROOT/"work/220主比較/比較元帳.json"
    if prior_file.exists():
        previous = json.loads(prior_file.read_bytes())
    else:
        previous,_ = ENGINE["calculate"](EXISTING,["S1P2"])
    for mode,group in books.items():
        assert all(all(a[k]==b[k] for k in ORIGINAL["KEYS"])
                   for a,b in zip(group["T01_1"],previous[mode]["S1P2"],strict=True))
        for code in keys:
            assert len(books["入口固定"][code])==181
            for r in group[code]:
                if r["status"]==5:
                    assert r["exit_time"]-r["trigger_time"]>=int(code.split("_")[1])
                    if code.startswith(("T03","T04","T05")):
                        assert r["extended"] and r["activation_time"]>=r["entry_time"]+3600
    main_books = {mode:{"IFD":group["IFD"],**{code:[dict(row,exit_strategy=code) for row in group[code+"_1"]]
                                              for code in CODES}} for mode,group in books.items()}
    out = ROOT/"work/221期限保護"
    out.mkdir(parents=True,exist_ok=True)
    for name,obj in (("比較元帳",main_books),("遅延比較元帳",books),
                     ("再生照合",{"元件数":len(base),"場":sorted(done),"T01":"S1P2と両モード全件照合",
                              "再生SHA256":sha256(Path(__file__).read_bytes()).hexdigest(),
                              "基準元帳SHA256":sha256(control.read_bytes()).hexdigest()})):
        (out/(name+".json")).write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
