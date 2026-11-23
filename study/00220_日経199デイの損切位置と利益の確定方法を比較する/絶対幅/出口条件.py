"""建値から一定ポイントの損切り、またはW31の初期損切幅に上限を置いた場合を比較する。"""
from pathlib import Path
import runpy

MAIN = runpy.run_path(str(Path(__file__).resolve().parents[1]/"主比較"/"出口条件.py"))
prepare = MAIN["prepare"]
LIMITS = {"A":(100,150,200,300,400),"B":(200,250,300,350,400)}
POLICIES = {f"{kind}{points}P{profit}":f"{points}pt{'固定' if kind=='A' else '上限'}とP{profit}"
            for kind,levels in LIMITS.items() for points in levels for profit in (0,3,4)}


def decide(code: str, context: dict, index, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：建てたときに初期損切の絶対幅だけを変更し、主比較と同じ利確規則で決済する。
    引数：code・horizon（str）は方策と保有期限、context・term（dict）は当時状態と観測限界、
    index（PriceIndex）は板、entry・side（int）は取得原行・方向、width（float）は元のR。
    返り値：dict。初期幅・追尾経路・決済原行と理由。
    """
    loss,profit = code.split("P")
    points = float(loss[1:])
    if loss.startswith("B"):
        points = min(points,MAIN["stop_size"]("S3",context,float(index.times[entry]),width))
    return MAIN["settle"]("P"+profit,points,context,index,entry,side,width,horizon,term)
