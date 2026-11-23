"""取得後の薄商いから逆方向の価格突破まで、出来高回復の寄与を順序付きで比較する。"""
import csv
from datetime import datetime
from functools import partial
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
FIRST = runpy.run_path(str(HERE/"出口条件.py"))
COMMON = FIRST["COMMON"]
POLICIES = ("D07","D08","D09","D10")
LABELS = {"D07":"逆足で直前値幅を突破","D08":"薄商い後の逆向き突破","D09":"薄商い後に量回復で利確",
          "D10":"薄商い後に量回復で追尾"}


def prepare_signals(index: object, scene: dict, signals: dict) -> dict:
    """
    機能：薄商い足の最初の公表を記録し、以後の完成1分足の価格突破・同時分出来高の回復を符号化する。
    引数：index（PriceIndex）は原板、scene・signals（dict）は場の時刻・限月と当時の入口判定。
    返り値：dict。RCおよび初回の量情報、価格突破に先行した一番新しい有効足の開始秒。
    """
    context = FIRST["prepare_signals"](index,scene,signals)
    flags = context["volume_flags"]
    day = scene["session"]
    folder = str(scene.get("量特徴の母集団",""))
    _,candles,_,_ = FIRST["candles"](day,folder)
    historic = FIRST["past_volume"](day,scene["contract"],folder)
    path = FIRST["PRICES"]/day/"candle_1min.csv"
    with path.open(encoding="utf-8-sig",newline="") as stream:
        bounds = {int(datetime.fromisoformat(r["time"]).timestamp()):(float(r["high"]),float(r["low"]))
                  for r in csv.DictReader(stream) if r["high"] and r["low"]}
    # ----------------------------------------
    observed = {}
    marks = np.full((3,len(index.times)),-1,dtype=np.int64)
    broken = np.zeros((2,len(index.times)),dtype=bool)
    for row in np.flatnonzero(flags["stamp"]>=0):
        at = int(flags["stamp"][row])
        assert at not in observed and at in candles
        observed[at] = row
        previous = at-60
        if previous not in observed or previous not in bounds or not (flags["local_known"][row] and flags["season_known"][row]):
            continue
        _,opening,close,quantity = candles[at]
        high,low = bounds[previous]
        broken[:,row] = [close<opening and close<low,close>opening and close>high]
        if not np.any(broken[:,row]):
            continue
        for age in (1,2,3):
            start = at-60*age
            if start not in observed:
                break
            prior = observed[start]
            if not (flags["local_known"][prior] and flags["season_known"][prior]):
                continue
            marks[0,row] = max(marks[0,row],start)
            if flags["local"][prior] and flags["season"][prior]:
                marks[1,row] = max(marks[1,row],start)
                if quantity>=1.5*candles[start][3] and quantity>=historic[at//60%1440][0]:
                    marks[2,row] = max(marks[2,row],start)
    return dict(context,preceding_stamp=marks,broken=broken)


def signal(code: str, context: dict, index: object, ids: np.ndarray, entry: int, side: int,
           width: float, move: np.ndarray, peak: np.ndarray) -> np.ndarray:
    """
    機能：確認足が建玉方向と逆に抜け、必要に応じて取得後の薄商いと後続の量回復を満たす原行を選ぶ。
    引数：code（str）は条件、context（dict）・index（PriceIndex）は確定資料と原板、entry・side（int）は
    新規行と側、width（float）は静的幅、ids・move・peak（np.ndarray）は判定行と順行経路。
    返り値：np.ndarray。追加判断に使う原行の真偽。最高順行の共通要件は呼び元で適用する。
    """
    level = {"D07":0,"D08":1,"D09":2,"D10":2}[code]
    after_entry = context["preceding_stamp"][level,ids]>=index.times[entry]
    return after_entry & context["broken"][side,ids] & (move>=.25*width)


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：半R順行後の価格と量の確認を、既存RCを維持した即時利確または狭い追尾に変換する。
    引数：code・horizon（str）は条件と期限、context・term（dict）は公表特徴と終端、
    index（PriceIndex）は原板、entry・side（int）は取得行と側、width（float）は元の片幅。
    返り値：dict。追加成立・実約定・決済原行を持つ元帳項目。
    """
    return COMMON["overlay"](context,index,entry,side,width,horizon,term,partial(signal,code),
                             "追尾" if code=="D10" else "即時",min_peak=.50)
