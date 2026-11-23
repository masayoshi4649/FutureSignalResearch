"""大きな順行の後、初めて確定5分足が保有方向から反対方向に転じた時だけ利確する。"""
from functools import partial
from pathlib import Path
import runpy

import numpy as np


HERE = Path(__file__).resolve().parent
FIRST = runpy.run_path(str(HERE/"出口条件.py"))
PRICES = runpy.run_path(str(next(HERE.parents[1].glob("00223_*/価格構造で保護/出口条件.py"))))
RULES = {
    "W09":(.65,.45,False,"即時"), "W10":(.65,.45,False,"追尾"),
    "W11":(.80,.60,False,"即時"), "W12":(.80,.60,False,"追尾"),
    "W13":(.65,.45,True,"即時"), "W14":(.65,.45,True,"追尾"),
}
POLICIES = tuple(RULES)


def prepare_signals(index: object, scene: dict, signals: dict) -> dict:
    """
    機能：5分足が閉じた直後に分かる、連続2本の方向の転換と1分足の確認を用意する。
    引数：index（PriceIndex）は板、scene（dict）は場の開始・終了、signals（dict）は当時の主入口情報。
    返り値：dict。RCの元情報と、確定直後1分間だけ利用する売買側別の転換判定。
    """
    context = FIRST["prepare_signals"](index,scene,signals)
    _,_,close = PRICES["completed_prices"](index,scene,context["bar"])
    turns = np.zeros((2,len(close)),dtype=bool)
    for minute in range(15,len(close),5):
        if not np.isfinite(close[minute-15:minute]).all():
            continue
        past = close[minute-6]-close[minute-11]
        for side,sign in enumerate((1,-1)):
            turns[side,minute] = sign*past>0 and context["adverse"][side,minute]
    return dict(context,turns=turns)


def signal(context: dict, index: object, ids: np.ndarray, entry: int, side: int, width: float,
           move: np.ndarray, peak: np.ndarray, *, arm: float, remain: float, add_alert: bool) -> np.ndarray:
    """
    機能：順行が転換より先にあり、新しい完成足が逆向きとなった最初の1分に残る含み益を確認する。
    引数：context（dict）は確定足と主信号、index（PriceIndex）は原板、ids（np.ndarray）は観測原行、
    entry・side（int）は取得・方向、width（float）は元の幅、move・peak（np.ndarray）は清算側の順行、
    arm・remain（float）は必要な順行倍率、add_alert（bool）は単発反対の併用。
    返り値：np.ndarray。完成足判定と順行の時間順が揃った時点の真偽列。
    """
    minute = context["bar"][ids]
    boundary = context["start"]+minute*60
    row_before = index.times[ids].searchsorted(boundary,side="left")-1
    result = context["turns"][side,minute] & (row_before>=0) & (peak[row_before.clip(0)]>=arm*width)
    result &= move>=remain*width
    if add_alert:
        result &= FIRST["signal"](context,index,ids,entry,side,width,move,peak,rule="単発")
    return result


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：元のRCに、確定した方向転換による即時要求または追加追尾を重ねる。
    引数：code・horizon（str）は候補と期限、context・term（dict）は確定足・観測終端、
    index（PriceIndex）は板、entry・side（int）は取得位置と側、width（float）は元幅。
    返り値：dict。追加成立・約定を含む実際の返済原行と時刻。
    """
    arm,remain,alert,action = RULES[code]
    rule = partial(signal,arm=arm,remain=remain,add_alert=alert)
    return FIRST["COMMON"]["overlay"](context,index,entry,side,width,horizon,term,rule,action,min_peak=arm)
