"""建てる直前の値幅から早い利益確定・追尾を使い分ける仮説を比較する。"""
from functools import partial
from pathlib import Path
import runpy

import numpy as np

LOCAL = runpy.run_path(str(Path(__file__).with_name("出口条件.py")))
PREVIOUS = LOCAL["PREVIOUS"]
POLICIES = ("V01","V02","V03","V04","V05")


def prepare_signals(index: object, scene: dict, signals: dict) -> dict:
    """
    機能：原行が属する分より前の連続20本だけで、気配中値の高安幅を求める。
    引数：index（PriceIndex）は原板、scene・signals（dict）は対象場と当時のシグナル。
    返り値：dict。RCの準備結果と各時点で既知の20分高安幅。
    """
    ctx = PREVIOUS["prepare_signals"](index,scene,signals)
    high,low,_ = LOCAL["PRICES"]["completed_prices"](index,scene,ctx["bar"])
    width = np.full(len(high),np.nan)
    for minute in range(20,len(high)):
        width[minute] = high[minute-20:minute].max()-low[minute-20:minute].min()
    return dict(ctx,prior_range=width)


def signal(context: dict, index: object, ids: np.ndarray, entry: int, side: int, width: float,
           move: np.ndarray, peak: np.ndarray, *, code: str) -> np.ndarray:
    """
    機能：取得直前の値幅対元の片幅の比を固定し、当時の順行・失速の成立を照合する。
    引数：context（dict）は確定特徴、index（PriceIndex）は板、ids（np.ndarray）は原行、entry・side（int）
    は取得行と側、width（float）は元の片幅、move・peak（np.ndarray）は順行、code（str）は候補。
    返り値：np.ndarray。保有中の各正常気配で追加条件が成立したか。
    """
    observed = context["prior_range"][context["bar"][entry]]
    use = code=="V01" or observed<=(.75 if code=="V05" else .50)*width
    if code in ("V04","V05"):
        return use & (move>=.25*width) & PREVIOUS["signal"](context,index,ids,entry,side,width,move,peak,rule="失速")
    return use & (move>=.50*width)


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：小値幅と判定された建玉だけに早期利確を加え、元の出口との先着を記録する。
    引数：code・horizon（str）は候補と期限、context・term（dict）は当時特徴と場末、
    index（PriceIndex）は原板、entry・side（int）は取得行・側、width（float）は元価格幅。
    返り値：dict。実際の決済と当時の20分高安差。
    """
    assert code in POLICIES
    result = PREVIOUS["COMMON"]["overlay"](context,index,entry,side,width,horizon,term,
                 partial(signal,code=code),"追尾" if code=="V03" else "即時",min_peak=.50)
    observed = context["prior_range"][context["bar"][entry]]
    return dict(result,prior_range=float(observed) if np.isfinite(observed) else None)
