"""上位中心三案の順行純信号を固定33の現在費用後起動へ直接渡す。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("上位中心継続の固定33運用", ROOT/"scripts/終値位置/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
PAIRS = (("J0", "XF"), ("J1", "XF"), ("J2", "XF"))


def pure_signal(row: dict) -> dict:
    """診断や未来先着を含めず当時必要な13列へ深複写する。

    引数: row(dict)は順行の純入口候補。
    返り値: dictは固定XFへ渡す13列。bb_mean未設定だけNoneを許す。
    """
    return {k: deepcopy(row.get(k)) if k == "bb_mean" else deepcopy(row[k]) for k in SIGNAL_FIELDS}


def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """事前三運用と順行役割を検査し、固定33XFを直呼出しする。

    引数: events(list[Any])は気配、signals/frames(list[dict])は入口/公開足、session/method/role(str)は場/候補/役割、
    config/policy(dict)は運用/出口、bounds(tuple|None)は人工時刻範囲。
    返り値: tuple[Any,dict]は固定状態と一場品質。新しい出口条件や記録を加えない。
    """
    allowed = {"3分_"+p+"_"+x: p for p, x in PAIRS}
    if method not in allowed or policy != {"出口ID": "XF"} or role != "順行":
        raise ValueError("上位中心三案は順行XFだけです")
    entry, clean = allowed[method], []
    for row in signals:
        if (row["場"] != session or row["入口ID"] != "3分_"+entry or row["役割"] != "順行"
                or row["side"] not in (-1, 1) or not row["イベントID"].endswith("_"+entry)
                or row["方向"] != ("買い" if row["side"] == 1 else "売り")):
            raise ValueError("場/入口/役割/実方向/識別子が不一致")
        clean.append(pure_signal(row))
    return BASE.replay(events, clean, frames, session, method, config, policy, role, bounds)
