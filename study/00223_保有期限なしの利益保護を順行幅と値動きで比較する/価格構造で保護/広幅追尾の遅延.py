"""広い追尾のS00と、元幅に応じて起動を分けるS19の執行遅延を比較する。"""
from pathlib import Path
import runpy


HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE/"出口条件.py"))
RETEST = runpy.run_path(str(HERE/"再度の押し戻し.py"))
prepare = BASE["prepare"]
POLICIES = [f"{code}D{delay}" for code in ("S00","S19") for delay in (3,5)]


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：元の静的指値・損切の約定時計を保ち、動的返済の遅延だけを3秒・5秒に変更する。
    引数：code・horizon（str）は候補と場末期限、context・term（dict）は技術・打切り、
    index（PriceIndex）は板、entry・side（int）は取得原行と方向、width（float）は元片幅。
    返り値：dict。返済原行と動的返済の履歴。
    """
    source,lag = code.split("D")
    module = BASE if source=="S00" else RETEST
    return module["decide"](source,context,index,entry,side,width,horizon,term,delay_seconds=int(lag))
