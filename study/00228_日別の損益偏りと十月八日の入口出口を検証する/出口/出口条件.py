"""取得時の逆向き背景と、含み益を得た後の失速を区別して保護を足す。"""
from functools import partial
from pathlib import Path
import runpy

import numpy as np

STUDIES = Path(__file__).resolve().parents[2]
PREVIOUS = runpy.run_path(str(next(STUDIES.glob("00227_*/弱い反転/出口条件.py"))))
PRICES = runpy.run_path(str(next(STUDIES.glob("00223_*/価格構造で保護/出口条件.py"))))
POLICIES = tuple(f"K{i:02d}" for i in range(1,9))


def prepare_signals(index: object, scene: dict, signals: dict) -> dict:
    """
    機能：各分の開始時点までの完成足で、寄りからの価格位置と複数時間の方向を用意する。
    引数：index（PriceIndex）は原板、scene・signals（dict）は場情報と当時発表された主信号。
    返り値：dict。RCの状態、持つ側に反する価格位置、完成足の方向・効率判定。
    """
    ctx = PREVIOUS["prepare_signals"](index,scene,signals)
    _,_,close = PRICES["completed_prices"](index,scene,ctx["bar"])
    opening_rows = index.normal[(index.times[index.normal]>=scene["start"]) &
                                (index.times[index.normal]<scene["start"]+60)]
    background = np.zeros((2,len(close)),dtype=bool)
    flowing = np.zeros_like(background)
    if len(opening_rows):
        first = opening_rows[0]
        opening = .5*(index.rows["ask"][first]+index.rows["bid"][first])
        for minute in range(1,len(close)):
            end5,end15 = minute//5*5,minute//15*15
            for side,sign in ((0,1),(1,-1)):
                if not np.isfinite(close[minute-1]) or sign*(close[minute-1]-opening)>=0:
                    continue
                if end15>=30 and np.isfinite(close[end15-30:minute]).all():
                    background[side,minute] = (sign*(close[end5-1]-close[end5-6])<0 and
                                               sign*(close[end15-1]-close[end15-16])<0)
                if end5>=35 and np.isfinite(close[end5-35:minute]).all():
                    changes = np.diff(close[end5-31:end5:5])
                    length = abs(changes).sum()
                    flowing[side,minute] = length>0 and sign*changes.sum()<=-.30*length
    return dict(ctx,background=background,flowing=flowing)


def signal(context: dict, index: object, ids: np.ndarray, entry: int, side: int, width: float,
           move: np.ndarray, peak: np.ndarray, *, code: str) -> np.ndarray:
    """
    機能：逆向きの初期状態または直近の値動きに応じ、保有中の失速から追加判断を得る。
    引数：context（dict）は確定特徴、index（PriceIndex）は原板、ids（np.ndarray）は判定原行、
    entry・side（int）は取得行・側、width（float）は片幅、move・peak（np.ndarray）は順行、
    code（str）は候補。返り値：np.ndarray。元のRC決済より前に成立する追加の判断。
    """
    minute = context["bar"][ids]
    against = context["background"][side,context["bar"][entry]]
    if code in ("K07","K08"):
        return against & PREVIOUS["signal"](context,index,ids,entry,side,width,move,peak,rule="単発")
    flags = (peak-move>=.25*width) & PREVIOUS["signal"](context,index,ids,entry,side,width,move,peak,rule="失速")
    if code in ("K03","K04"):
        flags &= context["flowing"][side,minute]
    elif code in ("K05","K06"):
        flags &= against
    return flags


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：元のRC決済を残したまま背景付きの追加返済または追尾を適用する。
    引数：code・horizon（str）は候補と場末期限、context・term（dict）は確定情報と終端、
    index（PriceIndex）は原板、entry・side（int）は取得行・側、width（float）は1R。
    返り値：dict。実際に先に約定した返済、追加判断と追尾の時計。
    """
    assert code in POLICIES
    early = .25 if code in ("K07","K08") else .50
    action = "即時" if code in ("K01","K03","K05","K07") else "追尾"
    return PREVIOUS["COMMON"]["overlay"](context,index,entry,side,width,horizon,term,
                                         partial(signal,code=code),action,min_peak=early)
