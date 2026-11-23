"""0.85R・0.95Rで保護する各対照の発動後に、約定可能となるまでの秒数を変える。"""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ORIGINAL = runpy.run_path(str(HERE/"出口条件.py"))
ADDITIONAL = runpy.run_path(str(HERE/"失速の追試.py"))
prepare = ORIGINAL["prepare"]
POLICIES = [f"{base}L{delay}" for base in ("P06","P20") for delay in (3,5)]


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：元の出口コードを選び、保護発動から実返済までの最短3秒・5秒のみを変更する。
    引数：code・horizon（str）は候補と場末期限、context・term（dict）は完成足と不足打切、
    index（PriceIndex）は価格索引、entry・side（int）は新規原行・売買、width（float）は元片幅。
    返り値：dict。元と同一規則による遅延感度の決済。
    """
    assert code in POLICIES
    policy = ORIGINAL if code.startswith("P06") else ADDITIONAL
    return policy["decide"](code,context,index,entry,side,width,horizon,term)
