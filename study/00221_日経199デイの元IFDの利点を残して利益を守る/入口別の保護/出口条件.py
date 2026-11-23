"""元のIFD片幅と期限を変えず、どの建玉に利益保護を追加するかを比較する。"""
from pathlib import Path
import runpy

MAIN = runpy.run_path(str(next(Path(__file__).resolve().parents[2].glob("00220_*/主比較/出口条件.py"))))
prepare = MAIN["prepare"]
POLICIES = ["F00","F01","F02","F03","F04","F05"]


def decide(code: str, context: dict, index, entry: int, side: int, width: float, horizon: str, term: dict) -> dict:
    """
    機能：元の新規時点で与えられる幅と期限から追尾の対象を決め、元の±1R注文で再生する。
    引数：code・horizon（str）は候補ID・期限、context・term（dict）は確定足特徴・決済限界、
    index（PriceIndex）は板索引、entry・side（int）は新規原行・方向、width（float）は元の片幅。
    返り値：dict。実決済・追尾の時刻と初期注文の水準。
    """
    central = horizon=="H60" and width==350
    closing = horizon=="SESSION"
    apply = {"F00":True, "F01":central, "F02":horizon=="H60" and width in (150,200),
             "F03":closing, "F04":not closing, "F05":central or closing}[code]
    return MAIN["settle"]("P2" if apply else "P0",width,context,index,entry,side,width,horizon,term)
