"""単発の反対主入口、確定足の短期失速、複数足の逆向きによる利確を比較する。"""
from functools import partial
from pathlib import Path
import runpy

import numpy as np


COMMON = runpy.run_path(str(Path(__file__).resolve().parents[1]/"利確を重ねる.py"))
prepare_signals = COMMON["RC"]["prepare_signals"]
RULES = {
    "W01":("単発","即時"),"W02":("単発","追尾"),
    "W03":("失速","即時"),"W04":("失速","追尾"),
    "W05":("二尺度","即時"),"W06":("二尺度","追尾"),
    "W07":("単発と失速","即時"),"W08":("単発と失速","追尾"),
}
POLICIES = tuple(RULES)


def signal(context: dict, index: object, ids: np.ndarray, entry: int, side: int, width: float,
           move: np.ndarray, peak: np.ndarray, *, rule: str) -> np.ndarray:
    """
    機能：保有中の各正常気配で、最新の反対主入口、または完成足が示す逆方向の判断を得る。
    引数：context（dict）はRCの完成足・主信号、index（PriceIndex）は板、ids（np.ndarray）は観測原行、
    entry・side（int）は取得位置・方向、width（float）は元幅、move・peak（np.ndarray）は順行と最高順行、
    rule（str）は比較する判定種別。
    返り値：np.ndarray。該当する気配原行の真偽列。利幅条件と返済の競合処理は共通関数が扱う。
    """
    if rule in ("失速","二尺度","単発と失速"):
        minute = context["bar"][ids]
        formed = context["start"]+minute*60>index.times[entry]
        feature = "adverse" if rule=="二尺度" else "squeeze"
        bars = formed & context[feature][side,minute]
        if rule!="単発と失速":
            return bars
    # ----------------------------------------
    signals = context["signal_rows"]
    if not len(signals):
        return np.zeros(len(ids),dtype=bool)
    position = signals.searchsorted(ids,side="right")-1
    last = position.clip(0)
    opposite = (position>=0) & (signals[last]>entry) & (context["signal_sides"][last]==(-1 if side==0 else 1))
    opposite &= index.times[ids]-context["signal_times"][last]<=90
    return opposite & bars if rule=="単発と失速" else opposite


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：各比較条件の返済要求または追加追尾を元のRCより先に約定できた場合に重ねる。
    引数：code・horizon（str）は条件と場末期限、context・term（dict）は確定情報と観測終端、
    index（PriceIndex）は原板、entry・side（int）は取得と側、width（float）は元の価格片幅。
    返り値：dict。取得時点後の情報だけで決めた追尾・決済原行と理由。
    """
    rule,action = RULES[code]
    return COMMON["overlay"](context,index,entry,side,width,horizon,term,partial(signal,rule=rule),action)
