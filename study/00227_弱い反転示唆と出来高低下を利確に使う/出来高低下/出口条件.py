"""当時公表された薄商いを、場内の直近と過去デイの同じ時分から判定する。"""
import csv
from datetime import datetime
from functools import lru_cache, partial
from hashlib import sha256
from pathlib import Path
import runpy
from statistics import median

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VOLUME = runpy.run_path(str(next((ROOT/"study").glob("00223_*/量を通じた利益保護/出口条件.py"))))
COMMON = runpy.run_path(str(HERE.parent/"利確を重ねる.py"))
SOURCE = VOLUME["SOURCE"]
PRICES = ROOT.parent/"JP_OSE_Data/future/NK225"
POLICIES = ("D01","D02","D03","D04","D05","D06")
LABELS = {"D01":"直前三分より出来高減","D02":"過去同時分より出来高減","D03":"二基準の出来高減",
          "D04":"出来高減と逆足で利確","D05":"出来高減と逆足で追尾","D06":"出来高を問わず逆足で利確"}


@lru_cache(maxsize=96)
def candles(day: str, folder: str) -> tuple:
    """
    機能：日別の出来高と価格を当時参照された分足の指紋・利用可能時計・数量の完全性で検査する。
    引数：day（str）はセッション名、folder（str）は追加または当日指定の特徴フォルダ。
    返り値：tuple。観測された足、使用できる足、当日の限月とCSV指紋。資料がないときは空。
    """
    folders = list(dict.fromkeys(([Path(folder)] if folder else [])+[p[0] for p in SOURCE["parts"]()]))
    arrived = next((rows for f in folders if (rows:=VOLUME["references"](f).get(day))),{})
    if not arrived:
        return {},{},None,None
    path = PRICES/day/"candle_1min.csv"
    fingerprint = sha256(path.read_bytes()).hexdigest()
    with path.open(encoding="utf-8-sig",newline="") as stream:
        source = {int(datetime.fromisoformat(r["time"]).timestamp()):r for r in csv.DictReader(stream)}
    contracts = {ref["contract"] for _,ref in arrived.values()}
    assert len(contracts)==1
    valid = {}
    for at,(key,ref) in arrived.items():
        assert ref["id"]==f"csv1m:{fingerprint}:{at}" and ref["end"]==at+60
        assert at+60<=ref["available_at"]<=key[0]
        if not (ref["price_known"] and ref["volume_known"]):
            continue
        row = source[at]
        assert row["closed"]=="true" and row["volume_complete"]=="true"
        opening,close,quantity = (float(row[k]) for k in ("open","close","volume"))
        if np.isfinite((opening,close,quantity)).all() and quantity>=0:
            valid[at] = key,opening,close,quantity
    return arrived,valid,contracts.pop(),fingerprint


@lru_cache(maxsize=96)
def past_volume(day: str, contract: str, folder: str) -> dict:
    """
    機能：当日より前に完結済みの直近10デイから同じ時分・限月の実出来高中央値と件数を求める。
    引数：day・contract・folder（str）は当日名、限月、追加の当時参照資料。
    返り値：dict[int,tuple]。当日内の時分ごとの中央値と支持日数。5日未満なら格納しない。
    """
    days = sorted(p.name for p in PRICES.glob("*_Day") if p.is_dir() and p.name<day)[-10:]
    volumes = {}
    for old in days:
        _,valid,other,_ = candles(old,folder)
        if other==contract:
            for at,(_,_,_,quantity) in valid.items():
                volumes.setdefault(at//60%1440,[]).append(quantity)
    return {minute:(median(history),len(history)) for minute,history in volumes.items() if len(history)>=5}


def volume_flags(index: object, day: str, contract: str, folder: str, cut: float) -> dict:
    """
    機能：完成足の値・過去時分基準・当時の公表原行から、最初に使える正常板に薄商いの印を付ける。
    引数：index（PriceIndex）は価格索引、day・contract・folder（str）は場・限月・入力、cut（float）は場末秒。
    返り値：dict。原行ごとの足の開始・基準の可否・低下印・側別の弱い逆向き印。
    """
    arrived,bars,actual,fingerprint = candles(day,folder)
    if actual!=contract:
        raise ValueError(f"{day}の限月または当時の出来高が一致しません")
    historic = past_volume(day,contract,folder)
    events = {}
    for at,(key,_) in arrived.items():
        time,row,line = key
        assert index.times[row]==time and index.rows["source_line"][row]==line
        events[key] = max(at,events.get(key,at))
    n = len(index.times)
    stamp = np.full(n,-1,dtype=np.int64)
    local_known,season_known,local_low,season_low,weak_buy,weak_sell = np.zeros((6,n),dtype=bool)
    latest = -1
    for key,at in sorted(events.items()):
        if at<=latest:
            continue
        latest = at
        if at not in bars or key[0]-at-60>120:
            continue
        pos = index.normal.searchsorted(key[1])
        if pos>=len(index.normal):
            continue
        row = index.normal[pos]
        if index.times[row]-key[0]>15 or index.times[row]>=cut:
            continue
        # 同じ正常原行に後から別の完成足が届いた場合は、常に最後の状態を使う。
        stamp[row] = at
        local_known[row] = season_known[row] = local_low[row] = season_low[row] = False
        weak_buy[row] = weak_sell[row] = False
        _,opening,close,quantity = bars[at]
        if (recent:=bars.get(at-60)) is not None and recent[0]<=key:
            weak_buy[row] = close<opening and close<recent[2]
            weak_sell[row] = close>opening and close>recent[2]
        history = [bars.get(at-minutes*60) for minutes in (1,2,3)]
        if all(v is not None and v[0]<=key for v in history):
            mean = sum(v[3] for v in history)/3
            local_known[row] = mean>0
            local_low[row] = mean>0 and quantity<=.60*mean
        same_clock,count = historic.get(at//60%1440,(0,0))
        season_known[row] = count>=5 and same_clock>0
        season_low[row] = season_known[row] and quantity<=.60*same_clock
    return {"stamp":stamp,"local_known":local_known,"season_known":season_known,"local":local_low,
            "season":season_low,"weak":(weak_buy,weak_sell),"csv_sha":fingerprint}


def prepare_signals(index: object, scene: dict, signals: dict) -> dict:
    """
    機能：元RCのシグナルを保存し、完成足で薄商いを判定した公表後の原行を追加する。
    引数：index（PriceIndex）は板、scene・signals（dict）は場情報と当時の主入口判断。
    返り値：dict。RC共通の要素に、追加利確のための出来高・価格を加えたもの。
    """
    context = COMMON["RC"]["prepare_signals"](index,scene,signals)
    flags = volume_flags(index,scene["session"],scene["contract"],str(scene.get("量特徴の母集団","")),scene["end"]-900)
    return dict(context,volume_flags=flags)


def signal(code: str, context: dict, index: object, ids: np.ndarray, entry: int, side: int,
           width: float, move: np.ndarray, peak: np.ndarray) -> np.ndarray:
    """
    機能：保有開始後に始まった足の出来高と価格反応を、元板の公表原行に限定して判定する。
    引数：code（str）は条件、context（dict）・index（PriceIndex）は公表資料と板、entry・side（int）は
    取得と側、width（float）は元片幅、ids・move・peak（np.ndarray）は判定原行と順行経路。
    返り値：np.ndarray。追加利確条件が当時の情報で成立する原行の真偽。
    """
    f = context["volume_flags"]
    published = f["stamp"][ids]>=index.times[entry]
    low = f["local"][ids]
    seasonal = f["season"][ids]
    if code=="D01":
        return published & low
    if code=="D02":
        return published & seasonal
    if code=="D03":
        return published & low & seasonal
    opposite = f["weak"][side][ids]
    if code=="D06":
        return published & opposite & f["local_known"][ids] & f["season_known"][ids]
    assert code in ("D04","D05")
    return published & opposite & low & seasonal


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：元RCの価格注文を残して、当時参照可能な薄商いに応じた追加利確を共通の執行条件で行う。
    引数：code・horizon（str）は方策と場末期限、context・term（dict）は公表状態と終端、
    index（PriceIndex）は板、entry・side（int）は取得と売買、width（float）は元片幅。
    返り値：dict。取得から実返済までの保護・決済の原行情報。
    """
    return COMMON["overlay"](context,index,entry,side,width,horizon,term,partial(signal,code),
                             "追尾" if code=="D05" else "即時")
