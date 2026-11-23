"""大きく順行した後の押しと再回復、順行の定着時間で保護の開始を決める。"""
from pathlib import Path
import runpy

import numpy as np


FIRST = runpy.run_path(str(Path(__file__).with_name("出口条件.py")))
prepare = FIRST["prepare"]
POLICIES = [f"S{i}" for i in range(10,20)]


def second_test(code: str, context: dict, index: object, ids: np.ndarray, entry: int,
                side: int, width: float, move: np.ndarray, peak: np.ndarray) -> tuple:
    """
    機能：大きな順行・最初の押し戻し・再回復を、清算側気配の観測順に検出する。
    引数：code（str）は候補、context（dict）は場の技術、index（PriceIndex）は原板、ids・move・peak（np.ndarray）は
    観測原行・順行・最大順行、entry・side（int）は新規原行・側、width（float）は元片幅。
    返り値：tuple。早期保護の成立、全追尾の起動、非緩和にする前の各原行の候補床。
    """
    early = np.zeros(len(ids),dtype=bool)
    wide = {"S10":.85,"S18":.85 if width>=350 else .95,
            "S19":.95 if width>=350 else .85}.get(code,.95)
    if code in ("S12","S13","S14","S15","S16","S17"):
        required = {"S12":.60,"S14":.80}.get(code,.70)
        reached = peak>=required*width
        if code=="S17":
            early = reached
        else:
            pull = FIRST["TECH"]["first_true"](reached & (move<=.20*width))
            if pull>=0:
                enabled = True
                if code in ("S15","S16"):
                    times = index.times[ids[:pull+1]]
                    above = move[:pull+1]>=required*width
                    starts = np.r_[True,(~above[:-1]) | (np.diff(times)>10)]
                    latest = np.maximum.accumulate(np.where(starts,times,-np.inf))
                    held = bool(np.any(above & (times-latest>=20)))
                    enabled = held if code=="S15" else not held
                if enabled:
                    early[pull+1:] = move[pull+1:]>=.35*width
    # ----------------------------------------
    floor = np.maximum(20,peak-.80*width)
    floor = np.where(early,np.maximum(.15*width,floor),floor)
    return early,(peak>=wide*width)|early,floor


def decide(code: str, context: dict, index: object, entry: int, side: int, width: float,
           horizon: str, term: dict, delay_seconds: int=1) -> dict:
    """
    機能：指定した順序で利益保護を開始し、静的価格注文・場末・動的返済の先着原行を返す。
    引数：code・horizon（str）は候補と期限、context・term（dict）は当時状態と終端、
    index（PriceIndex）は原板、entry・side（int）は取得行・側、width（float）は元幅、delay_seconds（int）は執行遅延。
    返り値：dict。返済情報と保護の観測原行。
    """
    return FIRST["settle"](code,context,index,entry,side,width,horizon,term,second_test,delay_seconds)
