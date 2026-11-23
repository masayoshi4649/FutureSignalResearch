"""上位雲三案の順行純信号だけを、固定33の費用後正益起動へ渡す。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("上位雲継続の固定33運用", ROOT/"scripts/終値位置/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
PAIRS = (("H0", "XF"), ("H1", "XF"), ("H2", "XF"))


def pure_signal(row: dict) -> dict:
    """上位の診断や未来ラベルを除いて13列を深複写する。

    引数: row(dict)は当時の純入口候補。
    返り値: dictは運用に必要な13列。bb_mean未設定だけNoneを許す。
    """
    return {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}


def replay(events: list[Any], signals: list[dict], frames: list[dict], session: str,
           method: str, config: dict, policy: dict, role: str,
           bounds: tuple | None = None) -> tuple[Any, dict]:
    """事前三案の純信号と役割を検査し、固定XFを直接呼び出す。

    引数: events(list[Any])は気配、signals/frames(list[dict])は入口/公開足、
    session/method/role(str)は場/候補/役割、config/policy(dict)は運用/出口、bounds(tuple|None)は人工範囲。
    返り値: tuple[Any,dict]は固定33の状態と品質。新しい退出や追尾条件は追加しない。
    """
    allowed = {"3分_"+entry+"_"+exit_id: entry for entry, exit_id in PAIRS}
    if method not in allowed or policy != {"出口ID": "XF"} or role != "順行":
        raise ValueError("上位雲三案は順行XFだけです")
    entry, clean = allowed[method], []
    for row in signals:
        if (row["場"] != session or row["入口ID"] != "3分_"+entry or row["役割"] != "順行"
                or row["side"] not in (-1, 1) or not row["イベントID"].endswith("_"+entry)
                or row["方向"] != ("買い" if row["side"] == 1 else "売り")):
            raise ValueError("場/入口/役割/実方向/識別子が不一致")
        clean.append(pure_signal(row))
    return BASE.replay(events, clean, frames, session, method, config, policy, role, bounds)
