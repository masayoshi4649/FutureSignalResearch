"""旧29の価格失敗とMACD反転へ、現前の量比準備・方向変化を分けて加える。"""

from collections import deque
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("量比反転の固定29入口", ROOT/"scripts/OBV反転/入口.py")
OLD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OLD
SPEC.loader.exec_module(OLD)
PERIOD = 20
POLICIES = ("V0", "V1", "V2")
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")


def canonical_sha(value: object) -> str:
    """日本語JSONの保存値を固定表記で指紋化する。

    引数: value(object)はJSON化可能な値。
    返り値: strはSHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def pure_signal(row: dict, policy: str = "V0") -> dict:
    """旧R0を当時必要な13列へ射影し、候補識別子だけを写す。

    引数: row(dict)は旧29純入口又は保存case、policy(str)は三案。
    返り値: dictはラベル/量比観測を含まないlive純入口。
    """
    if policy not in POLICIES:
        raise ValueError("事前の三案だけです")
    item = {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}
    original = row["イベントID"]
    item.update(入口ID="3分_"+policy, イベントID=original[:-3]+"_"+policy)
    return item


def ratio(values: list[tuple]) -> tuple[Fraction | None, dict]:
    """20変化の方向別観測量から中心化VR2を厳密に計算する。

    引数: values(list[tuple])は足番号/方向/観測q(float)の順序列。
    返り値: tuple[Fraction|None,dict]はBと表示用方向別量。20未満・全0量は欠測。
    """
    amounts = {direction: sum((Fraction(float(q)) for _, side, q in values if side == direction), Fraction())
        for direction in (1, -1, 0)}
    total = sum(amounts.values(), Fraction())
    value = (amounts[1]-amounts[-1])/total if len(values) == PERIOD and total > 0 else None
    return value, {"上昇量": float(amounts[1]), "下落量": float(amounts[-1]),
        "同値量": float(amounts[0]), "合計量": float(total)}


# ----------------------------------------
# 価格比較の基準closeと、数量の連続変化窓を別々に解除する。

def volume_panels(frames: list[dict], session: str) -> list[dict]:
    """旧29の確定足と固定14観測qだけから現前B20を作る。

    引数: frames(list[dict])は旧29の3分数値足、session(str)は場。
    返り値: list[dict]は量比だけの小型全足列。旧OHLC/MACD/数量全contextを複製しない。
    """
    window, previous, previous_index = deque(maxlen=PERIOD+1), None, None
    segment, sequence, count = None, 0, 0
    output = []
    for frame in frames:
        if frame["場"] != session or frame["minutes"] != 3:
            raise ValueError("当場3分足だけ")
        reasons = []
        adjacent = previous_index is not None and frame["index"] == previous_index+1
        if previous_index is None:
            reasons.append("場開始")
        elif not adjacent:
            reasons.append("足番号欠枠")
        if not frame["publish"]:
            reasons.append("非公開足")
        if frame["missing"]:
            reasons.append("欠枠")
        if not frame["価格数値入力可"]:
            reasons.append("OHLC不正")
        price_ok = bool(frame["publish"] and frame["価格数値入力可"] and not frame["missing"])
        if not adjacent or not price_ok:
            previous = None
            window.clear()
            segment, count = None, 0
        quantity = frame.get("数量参照")
        q = quantity.get("観測差分量") if quantity is not None else None
        quantity_ok = bool(quantity is not None and quantity.get("数量基準完全") and OLD.finite(q) and q >= 0)
        if not quantity_ok:
            reasons.append("数量基準不完全又は不正")
            window.clear()
            segment, count = None, 0
        base = previous
        direction = None
        eligible = price_ok and base is not None and quantity_ok
        if eligible:
            if segment is None:
                sequence += 1
                segment = f"{session}_量比区間{sequence:04d}"
            change = frame["close"]-base["close"]
            direction = (change > 0)-(change < 0)
            window.append((frame["index"], direction, float(q)))
            count += 1
        current_values = list(window)[-PERIOD:] if eligible else []
        previous_values = list(window)[:-1] if len(window) == PERIOD+1 and eligible else []
        current, current_amounts = ratio(current_values)
        prior, prior_amounts = ratio(previous_values)
        difference = current-prior if current is not None and prior is not None else None
        row = {"場": session, "index": frame["index"], "公開時計秒": frame["confirm"], "公開原板行": frame["confirm_line"],
            "価格入力可": price_ok, "数量入力可": quantity_ok, "VR入力可": eligible,
            "比較元足番号": None if base is None else base["index"], "分類方向": direction,
            "観測差分量": float(q) if quantity_ok else None, "VR解除理由": reasons,
            "VR区間ID": segment, "VR区間変化数": count,
            "現窓足番号": [r[0] for r in current_values], "前窓足番号": [r[0] for r in previous_values],
            "現方向別量": current_amounts, "前方向別量": prior_amounts, "現前B準備": difference is not None}
        for name, value in (("B現", current), ("B前", prior), ("B差", difference)):
            row[name] = None if value is None else float(value)
            row[name+"分子"] = None if value is None else value.numerator
            row[name+"分母"] = None if value is None else value.denominator
        output.append(row)
        previous = frame if price_ok else None
        previous_index = frame["index"]
    return output


def select(block: dict) -> dict:
    """旧R0完全入口・量比準備後・方向改善後を別の三集合へ分ける。

    引数: block(dict)は固定29の非PnL場材料。
    返り値: dictは純三集合・小型量比/採否。旧価格Pの時計を取り直さない。
    """
    old_signals = block["signals"]["3分_R0"]
    session = block["input_quality"]["場"]
    panels = volume_panels(block["frames"][3], session)
    by_index = {row["index"]: row for row in panels}
    decisions = []
    for row in block["quality"]["全Q発動記録"]:
        panel = by_index[row["index"]]
        old = bool(row["戦略判定"]["R0"]["採用"])
        ready = bool(panel["現前B準備"])
        improved = ready and row["side"]*panel["B差分子"] > 0
        verdicts = {"V0": {"採用": old, "理由": list(row["戦略判定"]["R0"]["理由"])},
            "V1": {"採用": old and ready, "理由": (["旧R0採用・現前B20準備"] if old and ready else
                ["旧R0不採用"] if not old else ["現前B20未準備"])},
            "V2": {"採用": old and ready and improved, "理由": (["旧R0採用・量比実方向改善"] if old and ready and improved else
                ["旧R0不採用"] if not old else ["現前B20未準備"] if not ready else ["量比差実方向不成立"])}}
        decisions.append({"場": session, "発動ID": row["発動ID"], "index": row["index"], "side": row["side"],
            "要求時計秒": row["要求時計秒"], "要求原板行": row["要求原板行"],
            "旧R0採用": old, "現前B準備": ready, "B差分子": panel["B差分子"], "B差分母": panel["B差分母"], "戦略判定": verdicts})
    by_event = {row["発動ID"]: row for row in decisions}
    grouped = {"3分_"+p: [] for p in POLICIES}
    for row in old_signals:
        decision = by_event[row["発動ID"]]
        for policy in POLICIES:
            if decision["戦略判定"][policy]["採用"]:
                grouped["3分_"+policy].append(pure_signal(row, policy))
    block.update(signals=grouped, volume_panels=panels, decisions=decisions)
    return block
