"""順行後に値動きの失速が持続した場合、両注文を維持して利益床を追加する。"""
from functools import partial
from pathlib import Path
import runpy

import numpy as np

FIRST = runpy.run_path(str(Path(__file__).with_name("出口条件.py")))
prepare = FIRST["prepare"]
POLICIES = [f"P{i}" for i in range(20,30)]


def protection(code: str, context: dict, ids: np.ndarray, side: int, width: float,
               move: np.ndarray, times: np.ndarray) -> tuple:
    """
    機能：単調な順行後の押し、繰り返す失速、押し後の再試行から保護開始を決める。
    引数：code（str）は候補、context（dict）は完成足、ids・move・times（np.ndarray）は原行・順行幅・秒、
    side（int）は方向、width（float）は元片幅。
    返り値：tuple[np.ndarray, np.ndarray]。各原行の起動状態と不利に緩めない保護床。
    """
    assert code in POLICIES
    peak = np.maximum.accumulate(move)
    arm = peak>=.95*width
    if code!="P20":
        bars = context["bar"][ids]
        squeeze = context["squeeze"][side]
        weak = squeeze[bars] & squeeze[np.maximum(bars-1,0)]
        if code=="P23":
            weak = squeeze[bars] & context["broken"][side,bars]
        elif code in ("P24","P25","P27","P29"):
            weak = context["adverse"][side,bars]
            if code=="P25":
                weak = weak & context["broken"][side,bars]
        # ----------------------------------------
        minimum = .75 if code in ("P28","P29") else .60
        drawdown = peak-move
        reached = peak>=minimum*width
        pulled = reached & (drawdown>=.20*width)
        if code in ("P26","P27"):
            recovery = np.logical_or.accumulate(pulled) & (drawdown<=.08*width)
            setup = np.logical_or.accumulate(recovery) & (drawdown>=.15*width)
        else:
            records = np.r_[True,peak[1:]>peak[:-1]]
            last_record = np.maximum.accumulate(np.where(records,times,-np.inf))
            setup = pulled & (times-last_record >= (600 if code=="P22" else 300))
        arm = arm | (setup & weak & (move>=20))
    active = np.logical_or.accumulate(arm)
    floor = np.maximum(20.0,peak-.80*width)
    return active,np.maximum.accumulate(np.where(active,floor,-np.inf))


decide = partial(FIRST["settle"],protection_rule=protection)
