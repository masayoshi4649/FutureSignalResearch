"""反転の純三入口を固定済みX0/XFへ渡し、旧運用の全属性を保つ。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("量比反転の固定33運用", ROOT/"scripts/終値位置/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
PAIRS = (("V0", "X0"), ("V0", "XF"), ("V1", "XF"), ("V2", "XF"))


def pure_signal(row: dict) -> dict:
    """当時の運用に必要な13列だけを新しい辞書へ写す。

    引数: row(dict)は当時の入口。余分な将来ラベルや量比観測は運用へ渡さない。
    返り値: dictは純信号。bb_meanの未設定だけNoneとして許可する。
    """
    return {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}


# ----------------------------------------
# 新しい退出や追尾状態を作らず、固定33のX0/XFを直接使う。

def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """事前の四運用だけを許可し、固定済み反転運用へ純信号を渡す。

    引数: events(list[Any])は気配、signals/frames(list[dict])は入口/公開足、
    session/method/role(str)は場/候補/役割、config/policy(dict)は運用/出口、
    bounds(tuple|None)は人工時計。
    返り値: tuple[Any,dict]は固定33再生の状態と一場会計。余分な記録を加えない。
    """
    pairs = {"3分_"+entry+"_"+exit_id: (entry, exit_id) for entry, exit_id in PAIRS}
    if method not in pairs:
        raise ValueError("事前に定めた反転四運用だけです")
    entry, exit_id = pairs[method]
    if role != "反転" or policy != {"出口ID": exit_id}:
        raise ValueError("反転役割又は候補と出口の対応が不正")
    clean = []
    for row in signals:
        if (row["場"] != session or row["入口ID"] != "3分_"+entry or row["役割"] != "反転"
                or row["side"] not in (-1, 1) or not row["イベントID"].endswith("_"+entry)):
            raise ValueError("反転の場/入口/役割/方向/識別子が不正")
        clean.append(pure_signal(row))
    return BASE.replay(events, clean, frames, session, method, config, policy, role, bounds)
