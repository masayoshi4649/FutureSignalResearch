"""当時参照された出来高と確定OHLCから利益床を上げる。"""
import csv
from datetime import datetime
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import runpy

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = runpy.run_path(str(next((ROOT/"study").glob("00217_*/日経/入口を再生する.py"))))
COMMON = runpy.run_path(str(HERE.parent/"価格構造で保護/出口条件.py"))
POLICIES = [f"Q{i:02d}" for i in range(14)]


@lru_cache(maxsize=6)
def references(folder: Path) -> dict:
    """
    機能：同じセッションの完成足が最初に参照された判断原行を、将来の金融ラベルを使わず読み取る。
    引数：folder（Path）は固定入口の母集団フォルダ。
    返り値：dict。日ごとの足開始秒を、最初の公表観測原行・足識別情報に対応づける。
    """
    raw = SOURCE["read"](folder/"当時特徴.json.gz")
    assert raw["financial_labels_used"] is False
    days = {}
    for r in raw["rows"]:
        day = r["session"]
        if not day.endswith("_Day"):
            continue
        q = r["metadata"]["q0"]
        point = (q["time"],q["index"],q["source_line"])
        found = days.setdefault(day,{})
        for ref in r["metadata"]["short_refs"]:
            if ref["session"]==day and ref["closed"]:
                assert ref["contract"]==r["contract"] and ref["end"]<=ref["available_at"]<=point[0]
                start = ref["start"]
                if start not in found or point<found[start][0]:
                    found[start] = point,ref
    return days


def prepare(index: object,scene: dict) -> dict:
    """
    機能：元の完成足と当時参照の時計・出来高品質を照合し、公表直後の正常板に価格・量の印を付ける。
    引数：index（PriceIndex）は当日の原板索引、scene（dict）は場情報。追加日には「量特徴の母集団」に
    当日の固定特徴フォルダを指定できる。
    返り値：dict。原行ごとの完成足開始秒と、両側の逆向き足・下抜け・高値拒否・出来高増加を保存。
    """
    day = scene["session"]
    folders = [Path(scene["量特徴の母集団"])] if "量特徴の母集団" in scene else [p[0] for p in SOURCE["parts"]()]
    arrived = next((d for f in folders if (d:=references(f).get(day)) is not None),None)
    if arrived is None:
        raise ValueError(f"{day} の当時の出来高公表資料がありません")
    path = ROOT.parent/"JP_OSE_Data/future/NK225"/day/"candle_1min.csv"
    fingerprint = sha256(path.read_bytes()).hexdigest()
    with path.open(encoding="utf-8-sig",newline="") as file:
        candles = {int(datetime.fromisoformat(r["time"]).timestamp()):r for r in csv.DictReader(file)}
    # ----------------------------------------
    usable,events = {},{}
    for at,(key,ref) in arrived.items():
        assert ref["id"]==f"csv1m:{fingerprint}:{at}" and ref["contract"]==scene["contract"]
        assert key[0]==index.times[key[1]] and key[2]==index.rows["source_line"][key[1]]
        events[key] = max(at,events.get(key,at))
        if ref["price_known"] and ref["volume_known"]:
            candle = candles[at]
            assert candle["closed"]=="true" and candle["volume_complete"]=="true" and ref["end"]==at+60
            usable[at] = key,np.array([float(candle[c]) for c in ("open","high","low","close","volume")])
    # ----------------------------------------
    n = len(index.times)
    stamps = np.full(n,-1,dtype="int64")
    states = np.zeros((2,4,n),dtype=bool)
    confirmed = np.full((2,2,n),-1,dtype="int64")
    past = [{},{}]
    latest = -1
    for key,at in sorted(events.items()):
        if at<=latest:
            continue
        latest = at
        publication,idx,_ = key
        prior = list(range(at-180,at+1,60))
        if publication-at-60>120 or any(t not in usable or usable[t][0]>key for t in prior):
            continue
        pos = index.normal.searchsorted(idx)
        if pos==len(index.normal):
            continue
        i = int(index.normal[pos])
        if index.times[i]-publication>15 or index.times[i]>=scene["end"]-900:
            continue
        values = np.array([usable[t][1] for t in prior])
        op,high,low,close,vol = values[-1]
        width = high-low
        mean = np.mean(values[:-1,4])
        if not np.isfinite(values).all() or width<=0 or mean<=0 or np.any(values[:,4]<0):
            continue
        stamps[i] = at
        for side,sign in ((0,1),(1,-1)):
            h,l = (high,low) if sign==1 else (-low,-high)
            hi,lo = (np.max(values[:-1,1]),np.min(values[:-1,2])) if sign==1 else (-np.min(values[:-1,2]),-np.max(values[:-1,1]))
            end,start = sign*close,sign*op
            opposite = (end-start)/width<=-.35 and (end-l)/width<=1/3
            broken = end<lo
            reject = h>hi and end<=hi and (h-max(end,start))/width>=.45
            states[side,:,i] = [opposite,broken,reject,vol>=1.5*mean]
            # ----------------------------------------
            history = past[side]
            for age in (1,2):
                first = at-age*60
                if first not in history:
                    continue
                old_high,old_low,old_volume = history[first]
                intervening = values[-age:,1] if sign==1 else -values[-age:,2]
                if np.max(intervening)<=old_high and end<old_low and end<sign*values[-2,3]:
                    confirmed[side,0,i] = max(first,confirmed[side,0,i])
                    if old_volume:
                        confirmed[side,1,i] = max(first,confirmed[side,1,i])
            if (opposite and broken) or reject:
                history[at] = h,l,states[side,3,i]
    return {"stamp":stamps,"state":states,"confirm":confirmed,"csv_sha":fingerprint}


def early_volume(code: str,context: dict,index: object,ids: np.ndarray,entry: int,
                 side: int,width: float,move: np.ndarray,peak: np.ndarray) -> tuple:
    """
    機能：取得以降の完成・公表済み足による出来高と価格の条件から初期・通常の追尾床を計算する。
    引数：code（str）は比較ID、context（dict）・index（PriceIndex）は公表記録と当日板、
    ids・move・peak（np.ndarray）は評価原行・建値比・それまでの最高順行、entry・side（int）は取得行・側、
    width（float）は静的両注文の片幅。
    返り値：tuple。早期保護の合図・起動条件・各原行で選ぶ保護床候補。
    """
    opposite,broken,reject,high = context["state"][side][:,ids]
    strict = high & ((opposite & broken) | reject)
    entry_time = index.times[entry]
    price_follow,volume_follow = context["confirm"][side][:,ids]>=entry_time
    patterns = {"Q00":False,"Q01":opposite,"Q02":opposite & high,"Q03":opposite & broken & high,
                "Q04":reject,"Q05":reject & high,"Q06":strict,"Q07":strict,"Q08":opposite & broken,
                "Q09":price_follow,"Q10":volume_follow,"Q11":volume_follow & (peak-move>=.20*width),
                "Q12":volume_follow,"Q13":volume_follow & high & opposite}
    eligible = context["stamp"][ids]>=entry_time
    threshold = .55 if code in ("Q07","Q11","Q12") else .20
    early = patterns[code] & eligible & (peak>=threshold*width) & (move>=20)
    return early,(peak>=.90*width)|early,np.maximum(20,peak-np.where(early,.40,.80)*width)


def decide(code: str,context: dict,index: object,entry: int,side: int,width: float,
           horizon: str,term: dict,delay_seconds: int=1) -> dict:
    """
    機能：元の両注文・場末返済を優先し、出来高と価格による床を付けた実際の返済を再生する。
    引数：code・horizon（str）は候補・場末期限、context・term（dict）は公表資料・打切、
    index（PriceIndex）は原板、entry・side（int）は取得原行・側、width（float）は元片幅、
    delay_seconds（int）は動的返済までの最短秒。
    返り値：dict。実返済・保護の発動原行を含む取引情報。
    """
    return COMMON["settle"](code,context,index,entry,side,width,horizon,term,early_volume,delay_seconds)
