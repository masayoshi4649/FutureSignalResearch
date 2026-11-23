"""反転・順行・混合の純信号を固定33のX0/XFへそのまま接続する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("構造判別の固定33運用", ROOT/"scripts/終値位置/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
PAIRS = (("B0", "X0"), ("B0", "XF"), ("R1", "XF"), ("T1", "XF"), ("S1", "XF"))
ROLES = {"B0": "反転", "R1": "反転", "T1": "順行", "S1": "切替"}


def pure_signal(row: dict) -> dict:
    """元Pや未来先着を運用へ渡さず当時必要な13列へ写す。

    引数: row(dict)は実方向と役割を持つ純入口候補。
    返り値: dictはdeepcopyされた13列。bb_mean未設定だけNoneを許可する。
    """
    return {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}


# ----------------------------------------
# 混合集合の名称と、fillで固定する建玉ごとの役割を区別する。

def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """事前五運用の実役割を検査し、固定33replayを直接呼び出す。

    引数: events(list[Any])は気配、signals/frames(list[dict])は当時の入口/公開足、
    session/method/role(str)は場/候補/集合役割、config/policy(dict)は運用/出口、
    bounds(tuple|None)は人工時刻範囲。
    返り値: tuple[Any,dict]は固定状態と一場品質。新しい退出や追尾記録は加えない。
    """
    pairs = {"3分_"+entry+"_"+exit_id: (entry, exit_id) for entry, exit_id in PAIRS}
    if method not in pairs:
        raise ValueError("事前の五運用だけです")
    entry, exit_id = pairs[method]
    if role != ROLES[entry] or policy != {"出口ID": exit_id}:
        raise ValueError("候補と集合役割又は出口の対応が不正")
    allowed_roles = ("反転", "順行") if entry == "S1" else (ROLES[entry],)
    clean = []
    for row in signals:
        if (row["場"] != session or row["入口ID"] != "3分_"+entry or row["役割"] not in allowed_roles
                or row["side"] not in (-1, 1) or not row["イベントID"].endswith("_"+entry)):
            raise ValueError("場/入口/実役割/方向/識別子が不正")
        clean.append(pure_signal(row))
    return BASE.replay(events, clean, frames, session, method, config, policy, role, bounds)
