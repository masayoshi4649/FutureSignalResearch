"""元利確を残しやすい期限末の追尾条件を、元と同じ注文時計で比較する。"""
from functools import partial
from pathlib import Path
import runpy

import numpy as np

FIRST = runpy.run_path(str(Path(__file__).with_name("出口条件.py")))
prepare = FIRST["prepare"]
POLICIES = [f"A{i}" for i in range(20,28)]


def locks(code: str, time: np.ndarray, move: np.ndarray, opened: float, left: np.ndarray, width: float,
          weak: np.ndarray, twice: np.ndarray, session: bool) -> tuple:
    """
    機能：残り時間・完成足・最高順行からの経過に応じて利益床を計算する。
    引数：code（str）は候補、time・move・left（np.ndarray）は価格時計・順行・残り時間、
    opened・width（float）は取得秒・元幅、weak・twice（np.ndarray）は確定足判定、session（bool）は場末期限。
    返り値：tuple。時間順の起動状態・床。
    """
    peak = np.maximum.accumulate(move)
    early = .85 if not session and code in ("A26","A27") else .95
    arm = move>=early*width
    floor = np.maximum(20.,peak-.80*width)
    if not (session and code in ("A22","A26","A27")):
        minutes = {"A20":8,"A21":12,"A25":5}.get(code,10)
        late = left<=minutes*60
        arm |= late & (move>=.45*width)
        stalled = np.zeros(len(time),dtype=bool)
        if code in ("A23","A24","A27"):
            last = np.maximum.accumulate(np.where(np.diff(np.r_[-np.inf,peak])>0,time,opened))
            stalled = time-last>=120
        if code=="A24":
            arm |= late & (peak>=.45*width) & (move>=.25*width) & weak & stalled
        shrink = late if code=="A25" else late & weak
        if code in ("A23","A24","A27"):
            shrink = shrink & stalled
        gap = .35 if code=="A27" else .25+.40*np.clip(left/(minutes*60),0,1)
        floor = np.maximum(floor,np.where(shrink,peak-gap*width,0))
    active = np.logical_or.accumulate(arm)
    return active,np.maximum.accumulate(np.where(active,floor,-np.inf))


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：期限に応じた追尾床を、共通の静的注文・実約定時計と組み合わせる。
    引数：code・horizon（str）は候補と期限、context・term（dict）は当時状態・打切り、
    index（PriceIndex）は正常板、entry・side（int）は新規原行・方向、width（float）は元幅。
    返り値：dict。決済・追尾判断の原行と時刻。
    """
    rule = partial(locks,session=horizon=="SESSION")
    return FIRST["apply_rule"](code,context,index,entry,side,width,horizon,term,rule)
