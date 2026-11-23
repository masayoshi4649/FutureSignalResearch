"""元の損切り直前の水準・丸め方を変えて、同じ4つの利益確定方法を比較する。"""
from math import ceil, floor
from pathlib import Path
import runpy

MAIN = runpy.run_path(str(Path(__file__).resolve().parents[1]/"主比較/出口条件.py"))
prepare = MAIN["prepare"]
POLICIES = [f"J{j}P{p}" for j in range(7) for p in (0,3,4,5)]


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：元の損切り付近で取得時の幅を定め、同じ主比較の利確・執行規則で決済する。
    引数：code（str）はJ/P番号、context・term（dict）は当時情報と期限、index（PriceIndex）は原板、
    entry・side（int）は取得行・売買側、width（float）は元幅、horizon（str）は元保有期限。
    返り値：dict。適用した初期幅、起動、返済要求、決済原行と事由。
    """
    j = int(code[1])
    points = width * (900,925,950,975,950,950,950)[j] / 1000
    if j==4:
        opened = float(index.times[entry])
        if MAIN["stop_size"]("S3",context,opened,width)>width:
            points = width*1.10
    if j==5:
        points = 5*floor(points/5)
    if j==6:
        points = 5*ceil(points/5)
    return MAIN["settle"](code[2:],points,context,index,entry,side,width,horizon,term)
