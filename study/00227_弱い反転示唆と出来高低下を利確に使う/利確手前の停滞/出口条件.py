"""元の利確目標に近づいて新しい有利な価格を試せなくなったときの利益保護を比較する。"""
from functools import partial
from pathlib import Path
import runpy

import numpy as np

COMMON = runpy.run_path(str(Path(__file__).resolve().parents[1]/"利確を重ねる.py"))
POLICIES = tuple(f"Z{i:02d}" for i in range(1,7))
prepare_signals = COMMON["RC"]["prepare_signals"]


def stalled(context: dict, index: object, ids: np.ndarray, entry: int, side: int, width: float,
            move: np.ndarray, peak: np.ndarray, *, code: str) -> np.ndarray:
    """
    機能：取得後に観測した清算側の最高順行を最後に試した時刻から停滞時間を測る。
    引数：context（dict）は完成足の状態、index（PriceIndex）は原板、ids（np.ndarray）は判断原行、
    entry・side（int）は取得原行と側、width（float）は1R、move・peak（np.ndarray）は清算側の順行、
    code（str）は候補。返り値：np.ndarray。各原行でその時までの停滞と逆向きの兆候が揃ったか。
    """
    times = index.times[ids]
    last_touch = np.maximum.accumulate(np.where(move==peak,times,-np.inf))
    result = (times-last_touch>=300) & (move>=.50*width)
    if code in ("Z03","Z04","Z05","Z06"):
        minute = context["bar"][ids]
        result &= (context["start"]+60*minute>index.times[entry]) & context["squeeze"][side,minute]
    if code in ("Z05","Z06"):
        result &= times>=context["deadline"]-1800
    return result


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict) -> dict:
    """
    機能：利確まで75%以上進んだ後に、価格停滞に応じた追加利確または追尾を要求する。
    引数：code・horizon（str）は候補と観測期限、context・term（dict）は市場状態と場末、
    index（PriceIndex）は板、entry・side（int）は取得原行と方向、width（float）は元の片幅。
    返り値：dict。RCと追加の要求のうち実際に先に約定した返済を含む。
    """
    assert code in POLICIES
    action = "即時" if code in ("Z01","Z03","Z05") else "追尾"
    return COMMON["overlay"](context,index,entry,side,width,horizon,term,partial(stalled,code=code),action,min_peak=.75)
