"""二足実体包みの二反転・一切替入口を、固定33の現在費用後起動へ渡す。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("実体包みの固定33運用", ROOT/"scripts/終値位置/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
PAIRS = (("B0", "XF"), ("B1", "XF"), ("B2", "XF"))


def pure_signal(row: dict) -> dict:
    """当時の執行に必要な純13列だけを深複写する。

    引数: row(dict)は実役割を持つ切替入口候補。
    返り値: dictは二実体/平均/指標の詳細と未来labelを含まない13列。
    """
    return {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}


def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """二反転・一切替XFだけを許し、旧固定の逐次運用を直呼出しする。

    引数: events(list[Any])は正常気配、signals/frames(list[dict])は純入口/公開足、
    session/method/role(str)は場/候補/集合役割、config/policy(dict)は運用/出口、bounds(tuple|None)は人工範囲。
    返り値: tuple[Any,dict]は固定33の状態と場品質。出口条件を追加しない。
    """
    allowed = {"3分_"+entry+"_"+exit_id: entry for entry, exit_id in PAIRS}
    if method not in allowed or policy != {"出口ID": "XF"}:
        raise ValueError("実体包みの三案は指定XFだけです")
    entry, clean = allowed[method], []
    actual_roles = ("順行", "反転") if entry == "B2" else ("反転",)
    if role != ("切替" if entry == "B2" else "反転"):
        raise ValueError("候補の集合役割が不一致")
    for row in signals:
        if (row["場"] != session or row["入口ID"] != "3分_"+entry or row["役割"] not in actual_roles
                or row["side"] not in (-1, 1) or not row["イベントID"].endswith("_"+entry)
                or row["方向"] != ("買い" if row["side"] == 1 else "売り")):
            raise ValueError("場/入口/役割/実方向/識別子が不一致")
        clean.append(pure_signal(row))
    return BASE.replay(events, clean, frames, session, method, config, policy, role, bounds)
