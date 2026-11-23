"""利益側をM34に固定し、構造距離を上下限に寄せる作用を個別に外す。"""
from pathlib import Path
import runpy

BASE = runpy.run_path(str(Path(__file__).with_name("出口定義.py")))
prepare = BASE["prepare"]
POLICIES = ["S51","S61","S71"]


def stop_model(group: int, ctx: dict, minute: int, side: int, price: float, width: float) -> tuple:
    """
    機能：S21の生の構造距離と上下限に照らして補助対照の初期逆指値を固定する。
    引数：group・minute・side（int）は群・分・側、ctx（dict）は場情報、price・width（float）は建値・元幅。
    返り値：tuple。初期損切距離、生距離またはNone、適用理由。
    """
    final,raw,why = BASE["stop_distance"](2,ctx,minute,side,price,width)
    if raw is None:
        return final,raw,why
    if group==5:
        return .85*width,raw,"固定0.85R"
    if group==6:
        return (raw,raw,"範囲内の実水準") if .85*width<=raw<=1.10*width else (width,raw,"範囲外は元幅")
    if raw>1.10*width:
        return width,raw,"遠い構造は元幅"
    return final,raw,why


def decide(code: str, ctx: dict, index: object, entry: int, side: int, width: float, horizon: str,
           term: dict) -> dict:
    """
    機能：初期損切りだけを置き換え、初回と同じ返済時計・追尾・静的利確で再生する。
    引数：code・horizon（str）は候補・期限、ctx・term（dict）は場・終端、index（PriceIndex）は板、
        entry・side（int）は新規行・側、width（float）は元幅。
    返り値：dict。決済原行、理由、初期損切り・保護床の情報。
    """
    return BASE["decide"](code,ctx,index,entry,side,width,horizon,term,stop_model=stop_model)
