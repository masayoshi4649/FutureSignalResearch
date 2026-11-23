"""旧29価格Pを、旧高安の全範囲帰還・元方向外側・勢い不一致へ分ける。"""

from collections import defaultdict
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("構造判別の固定36純射影", ROOT/"scripts/量比反転/入口.py")
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
OLD = PREVIOUS.OLD
canonical_sha = PREVIOUS.canonical_sha
SIGNAL_FIELDS = PREVIOUS.SIGNAL_FIELDS
POLICIES = ("B0", "R1", "T1", "S1")
ROLES = {"B0": "反転", "R1": "反転", "T1": "順行", "S1": "切替"}


def pure_signal(row: dict, policy: str, actual_side: int | None = None, role: str | None = None) -> dict:
    """元価格Pを実方向・役割が明示された純13列へ写す。

    引数: row(dict)は元P又は旧R0、policy(str)は四案、actual_side(int|None)/role(str|None)は実注文の方向/役割。
    返り値: dictは構造判定や未来ラベルを含まない純入口。元PのOHLC/ATRは変えない。
    """
    if policy not in POLICIES:
        raise ValueError("事前の四案だけです")
    transformed = {"イベントID", "入口ID", "役割", "side", "方向"}
    item = {k: deepcopy(row.get(k)) if k == "bb_mean" else deepcopy(row[k]) for k in SIGNAL_FIELDS if k not in transformed}
    origin = row["発動ID"] if "発動ID" in row else row["イベントID"][:-3]
    side = row["side"] if actual_side is None else actual_side
    actual_role = ROLES[policy] if role is None else role
    if side not in (-1, 1) or actual_role not in ("順行", "反転"):
        raise ValueError("純入口は実方向と固定役割だけ")
    item.update(入口ID="3分_"+policy, イベントID=origin+"_"+policy, side=side,
        方向="買い" if side == 1 else "売り", 役割=actual_role)
    return item


def select(block: dict) -> dict:
    """全旧Pの位置とMACD差を同時計判別し、四候補の競合を別々に処理する。

    引数: block(dict)は旧29の非損益場材料。
    返り値: dictは純四集合と小型の全原P判定。Tを旧R0純集合の補数から作らない。
    """
    decisions, origins, selected = [], {}, defaultdict(list)
    for row in block["quality"]["全Q発動記録"]:
        side = row["side"]
        low_source = row["方向別準備"]["1"]["OBV_k参照"]
        high_source = row["方向別準備"]["-1"]["OBV_k参照"]
        lower, upper = low_source["low"], high_source["high"]
        level = lower if side == 1 else upper
        close, delta = row["close"], row["MACDヒスト変化"]
        inside = lower < close < upper
        outside = side*(close-level) < 0
        common = bool(row["共通M準備"] and row["時間条件可"] and row["確認遅延条件可"])
        old = bool(row["戦略判定"]["R0"]["採用"])
        trend = bool(common and outside and OLD.finite(delta) and -side*delta > 0)
        reversal = old and inside
        kind = "旧範囲内" if inside else "境界等号" if close in (lower, upper) else "元方向外側" if outside else "反対端外側"
        verdicts = {
            "B0": {"採用": old, "実side": side, "役割": "反転", "同時競合": False},
            "R1": {"採用": reversal, "実side": side, "役割": "反転", "同時競合": False},
            "T1": {"採用": trend, "実side": -side, "役割": "順行", "同時競合": False},
            "S1": {"採用": reversal or trend, "実side": side if reversal else -side if trend else None,
                "役割": "反転" if reversal else "順行" if trend else None, "同時競合": False}}
        decision = {"場": row["場"], "発動ID": row["発動ID"], "index": row["index"], "元価格side": side,
            "要求時計秒": row["要求時計秒"], "要求原板行": row["要求原板行"],
            "旧L": lower, "旧H": upper, "旧L足番号": low_source["index"], "旧H足番号": high_source["index"],
            "元境界K": level, "終値": close, "構造区分": kind,
            "MACDヒスト変化": delta, "共通M準備": row["共通M準備"],
            "時間条件可": row["時間条件可"], "確認遅延条件可": row["確認遅延条件可"],
            "旧R0採用": old, "戦略判定": verdicts}
        decisions.append(decision)
        origins[row["発動ID"]] = row
        for policy, verdict in verdicts.items():
            if verdict["採用"]:
                selected[policy, row["要求時計秒"], row["要求原板行"]].append(decision)
    for (policy, _, _), values in selected.items():
        if len(values) > 1:
            for value in values:
                value["戦略判定"][policy].update(採用=False, 同時競合=True)
    grouped = {"3分_"+p: [] for p in POLICIES}
    for decision in decisions:
        for policy, verdict in decision["戦略判定"].items():
            if verdict["採用"]:
                grouped["3分_"+policy].append(pure_signal(origins[decision["発動ID"]], policy, verdict["実side"], verdict["役割"]))
    block.update(signals=grouped, decisions=decisions)
    return block
