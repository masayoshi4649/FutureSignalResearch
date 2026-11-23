"""53の固定帯反応・共通教師・合成木・保存運用を独立検査する。実学習は再実行しない。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00053_局所帯の反応で先に分岐"
WORK = ROOT / "work/局所帯分岐/00053"
OLD = ROOT / "study/00052_定時判断へ価格履歴を追加"
OLDWORK = ROOT / "work/定時履歴/00052"
BASEWORK = ROOT / "work/局所再開/00050"
BASESTUDY = ROOT / "study/00050_15分定時の局所再開"
FRAMES = ROOT / "work/一目基準線/00028/全指標.jsonl.gz"
LABELS = ROOT / "work/定時帯反応/00049/入口先着.jsonl.gz"
POLICIES = {"B0": 4, "F0": 4}
FEATURE_COUNTS = {"B0": 17, "F0": 18}
PERIODS = ("学習", "条件選択", "後続検査")
SOURCE = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
TEACHER_FIELDS = ("slot_id", "session", "scheduled", "time", "line", "side", "features", "outcome", "filled", "end_time", "end_line")
BINDING = ("slot_id", "session", "scheduled", "time", "line")
FAMILIES = ["trend", "osc", "osc", "vol", *(["price"] * 11)]
TARGETS = {"250": 1, "125": 0, "期限": 0}


def load(path: Path, name: str):
    """固定された純補助を固有名で読み、大域値を変更しない。

    引数: path(Path)はPython、name(str)は読込名。
    返り値: ModuleTypeは読込結果。主検証・学習器のfit/predictは読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def helpers() -> tuple:
    """板・現金・期限・期間の固定補助だけを集める。

    引数: なし。
    返り値: tupleは49監査、49期限補足、50監査。globalsは変更しない。
    """
    return (load(ROOT / "scripts/定時帯反応/保存物確認.py", "局所帯分岐監査_49"),
            load(ROOT / "scripts/定時帯反応/期限同秒確認.py", "局所帯分岐監査_期限49"),
            load(ROOT / "scripts/局所再開/保存物確認.py", "局所帯分岐監査_50"))


def fingerprint(value: object) -> str:
    """配列順と全値をJSONの指紋に結ぶ。

    引数: value(object)は有限JSON。
    返り値: strはsort_keys付きUTF-8内容SHA256。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def finite(value: object) -> bool:
    """JSON数値の有限性を確認する。

    引数: value(object)は候補値。
    返り値: boolはboolを除く有限int/floatか。
    """
    return type(value) in (int, float) and math.isfinite(value)


def exact(value: object) -> Fraction | None:
    """Fast保存分数と表示値の算術一致を検査する。

    引数: value(object)は精密辞書。
    返り値: Fraction|Noneは有効な値。欠測を0へ置換しない。
    """
    if not isinstance(value, dict) or value.get("valid") is not True:
        return None
    n, d = value.get("numerator"), value.get("denominator")
    if type(n) is not int or type(d) is not int or d <= 0 or not finite(value.get("value")):
        return None
    result = Fraction(n, d)
    try:
        return result if float(result) == value["value"] else None
    except OverflowError:
        return None


def source_reason(row: object, session: str, minutes: int, scheduled: float, limit: tuple) -> str:
    """足出典を独自に検査し、特徴準備の基準を得る。

    引数: row(object)はSOURCE、session(str)/minutes(int)は必要場・幅、scheduled(float)/limit(tuple)は可視境界。
    返り値: strは不備理由。正常なら空文字。
    """
    if not isinstance(row, dict) or not set(SOURCE) <= set(row):
        return "出典なし又はフィールド不足"
    if row["session"] != session or row["minutes"] != minutes:
        return "当場又は足幅不一致"
    if type(row["index"]) is not int or row["index"] < 0:
        return "足番号不正"
    if type(row["confirm_line"]) is not int or row["confirm_line"] < 0:
        return "公開原行不正"
    if any(not finite(row[k]) for k in ("start", "end", "confirm")):
        return "出典時計不正"
    prices = [row[k] for k in ("open", "high", "low", "close")]
    good = all(finite(v) and v > 0 for v in prices)
    good = good and row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]
    if not (good and row["publish"] and row["missing"] == 0 and row["end"] - row["start"] == 60 * minutes and row["confirm"] >= row["end"]):
        return "非公開又は価格不正・欠枠・不完全"
    if row["end"] > scheduled or (row["confirm"], row["confirm_line"]) > limit:
        return "当時公開参照なし"
    return ""


def adjacent(previous: dict, current: dict) -> bool:
    """場・番号・終了開始・公開keyの完全隣接を確認する。

    引数: previous/current(dict)は有効SOURCE。
    返り値: boolは局所二足として隣接するか。
    """
    return (previous["session"] == current["session"] and previous["index"] + 1 == current["index"]
            and previous["end"] == current["start"]
            and (previous["confirm"], previous["confirm_line"]) < (current["confirm"], current["confirm_line"]))


def clv(row: dict) -> Fraction:
    """上下距離比の差から足内位置を別式で得る。

    引数: row(dict)は完全OHLC。
    返り値: Fractionは零幅なら0、他は下からの距離比と上からの距離比の差。
    """
    high, low, close = (Fraction(row[k]) for k in ("high", "low", "close"))
    return (close - low) / (high - low) - (high - close) / (high - low) if high != low else Fraction(0)


def expected_base(slot: dict) -> dict:
    """保存出典と旧指標から15特徴を独立に組み立てる。

    引数: slot(dict)は固定50P0の保存判断。旧side/role/ready・教師・保有は使わない。
    返り値: dictは新extractの全出力期待値。指標銀行を再計算せず、原板も読まない。
    """
    result = {"ready": False, "reason": "", "vectors": {"1": [], "-1": []}, "atr": None, "D": None,
              "background_direction": None, "sources": {"current": None, "previous": None, "upper": None, "OR": None}, "diagnostic": {}}
    session, scheduled, time, line = (slot.get(k) for k in ("session", "scheduled", "time", "line"))
    if not isinstance(session, str) or not session or not finite(scheduled) or not finite(time) or not scheduled <= time <= scheduled + 30 or type(line) is not int or line < 0:
        result["reason"] = "判断時計又は原行なし・不正"
        return result
    if slot.get("reason") == "判断BBO不正":
        result["reason"] = "判断BBO不正"
        return result
    limit = (time, line)
    for name, prefix in (("current", "現3分"), ("previous", "前3分")):
        reason = source_reason(slot.get(name), session, 3, scheduled, limit)
        if reason:
            result["reason"] = prefix + ": " + reason
            return result
        result["sources"][name] = {k: slot[name][k] for k in SOURCE}
    current, previous = slot["current"], slot["previous"]
    if not adjacent(previous, current):
        result["reason"] = "現前3分の完全隣接不一致"
        return result
    if scheduled - current["end"] > 180:
        result["reason"] = "現3分足が180秒超過"
        return result
    band = slot.get("OR")
    reason = ""
    if not isinstance(band, dict) or band.get("ready") is not True:
        reason = "開始30分OR未準備"
    elif any(not finite(band.get(k)) for k in ("low", "high")):
        reason = "開始帯価格不正"
    elif not isinstance(band.get("sources"), list) or len(band["sources"]) != 10:
        reason = "開始帯10本出典不足"
    else:
        rows = band["sources"]
        if any(source_reason(row, session, 3, scheduled, limit) or row["index"] != i for i, row in enumerate(rows)):
            reason = "開始帯10本の公開完全出典不一致"
        elif not all(adjacent(p, c) for p, c in zip(rows, rows[1:])):
            reason = "開始帯10本の隣接不一致"
        elif Fraction(band["low"]) != min(Fraction(r["low"]) for r in rows) or Fraction(band["high"]) != max(Fraction(r["high"]) for r in rows):
            reason = "開始帯価格と出典不一致"
    if reason:
        result["reason"] = reason
        return result
    result["sources"]["OR"] = {"low": band["low"], "high": band["high"], "indices": [r["index"] for r in band["sources"]], "latest_key": list(max((r["confirm"], r["confirm_line"]) for r in band["sources"]))}
    upper = slot.get("upper")
    if not isinstance(upper, dict) or upper.get("ready") is not True:
        result["reason"] = "当場15分DMI未準備"
        return result
    upper_source = upper.get("source")
    reason = source_reason(upper_source, session, 15, scheduled, limit)
    if reason:
        result["reason"] = "上位15分: " + reason
        return result
    if scheduled - upper_source["end"] > 900:
        result["reason"] = "上位15分足が900秒超過"
        return result
    if any(not finite(upper.get(k)) for k in ("plus_di", "minus_di")):
        result["reason"] = "上位DI数値不正"
        return result
    result["sources"]["upper"] = {k: upper_source[k] for k in SOURCE}
    atr = slot.get("atr")
    if not finite(atr) or atr <= 0:
        result["reason"] = "現ATR正値未準備"
        return result
    a = Fraction(atr)
    units = a / 5
    result.update(atr=atr, D=float(min(125, max(5, -(-units.numerator // units.denominator) * 5))))
    old = slot.get("diagnostic", {}).get("old_R")
    if not isinstance(old, dict):
        result["reason"] = "Fast保存参照なし"
        return result
    old_source = old.get("current")
    if not isinstance(old_source, dict) or not set(SOURCE) <= set(old_source) or {k: old_source[k] for k in SOURCE} != {k: current[k] for k in SOURCE}:
        result["reason"] = "Fastと現3分出典不一致"
        return result
    k, change = exact(old.get("fast_k")), exact(old.get("fast_change"))
    if k is None or change is None:
        result["reason"] = "FastK又は現前差の精密値未準備"
        return result
    c, pc = Fraction(current["close"]), Fraction(previous["close"])
    midpoint = (Fraction(band["high"]) + Fraction(band["low"])) / 2
    di = Fraction(upper["plus_di"]) - Fraction(upper["minus_di"])
    result["background_direction"] = int(di > 0) - int(di < 0)
    for side in (1, -1):
        direction_edge = "high" if side == 1 else "low"
        opposite_edge = "low" if side == 1 else "high"
        values = [side * di / 100, side * (k / 50 - 1), side * change / 100, a / 125,
                  (Fraction(band["high"]) - Fraction(band["low"])) / a, side * (c - midpoint) / a,
                  side * (c - pc) / a, side * (c - Fraction(current["open"])) / a,
                  (Fraction(current["high"]) - Fraction(current["low"])) / a, side * clv(current),
                  side * (Fraction(current[direction_edge]) - Fraction(previous[direction_edge])) / a,
                  side * (Fraction(current[opposite_edge]) - Fraction(previous[opposite_edge])) / a,
                  side * (Fraction(upper_source["close"]) - Fraction(upper_source["open"])) / a,
                  (Fraction(upper_source["high"]) - Fraction(upper_source["low"])) / a, side * clv(upper_source)]
        try:
            result["vectors"][str(side)] = [float(v) for v in values]
        except OverflowError:
            result.update(reason="特徴のfloat表示範囲外", vectors={"1": [], "-1": []})
            return result
        if not all(finite(v) for v in result["vectors"][str(side)]):
            result.update(reason="特徴の有限値不成立", vectors={"1": [], "-1": []})
            return result
    result["diagnostic"] = {"fast_k": float(k), "fast_change": float(change), "plus_di": upper["plus_di"], "minus_di": upper["minus_di"],
                            "current_age_seconds": scheduled - current["end"], "upper_age_seconds": scheduled - upper_source["end"],
                            "zero_width_current": current["high"] == current["low"], "zero_width_upper": upper_source["high"] == upper_source["low"]}
    result.update(ready=True, reason="")
    return result


# ----------------------------------------
# 実学習を呼ばず、過去教師とJSON構造から全nodeを検算する。

def reaction_state(rows: list[dict], level: float, direction: int) -> dict:
    """反応5足の明瞭側を列挙し、内側アンカーからの区間変化を別算する。

    引数: rows(list[dict])は検算済み反応5足、level(float)は固定端、direction(int)は外向き±1。
    返り値: dictは全states/eventsと回数。主の逐行状態更新を呼ばない。
    """
    if len(rows) != 5 or direction not in (-1, 1):
        raise ValueError("反応は5足と端方向±1が必要")
    zones = [int(direction * (Fraction(row["close"]) - Fraction(level)) >= 5)
             - int(direction * (Fraction(row["close"]) - Fraction(level)) <= -5) for row in rows]
    clear = [(position, zone) for position, zone in enumerate(zones) if zone]
    events = []
    for (old_position, before), (position, after) in zip([(-1, -1)] + clear, clear):
        if before != after:
            row = rows[position]
            events.append({"index": row["index"], "from": before, "to": after, "sign": after,
                           "key": [row["confirm"], row["confirm_line"]]})
    states = []
    for position, row in enumerate(rows):
        prefix = [zone for i, zone in clear if i <= position]
        states.append({"index": row["index"], "zone": zones[position], "state": prefix[-1] if prefix else -1})
    last = events[-1] if events else None
    return {"direction": direction, "level": level, "initial_state": -1,
            "states": states, "events": events, "final_state": states[-1]["state"],
            "out_count": sum(event["sign"] == 1 for event in events),
            "in_count": sum(event["sign"] == -1 for event in events),
            "last_change_sign": last["sign"] if last else 0,
            "last_change_index": last["index"] if last else None,
            "age_bars": rows[-1]["index"] - last["index"] if last else None}


def expected_feature(slot: dict, frames: list[dict]) -> dict:
    """旧15特徴と非重複の参照10/反応5SOURCEから17/18列を独立再構成する。

    引数: slot(dict)は保存50P0枠、frames(list[dict])は固定28SOURCE13。
    返り値: dictは新extractの全出力。未来教師・保有・主特徴計算を参照しない。
    """
    base = expected_base(slot)
    result = {"ready": False, "reason": "", "base": base,
              "control_vectors": {"1": [], "-1": []}, "vectors": {"1": [], "-1": []},
              "atr": base["atr"], "D": base["D"], "background_direction": base["background_direction"],
              "history": {"reference_sources": [], "reaction_sources": [], "band": None,
                          "upper": None, "lower": None, "contexts": {"1": None, "-1": None}}}
    if not base["ready"]:
        result["reason"] = "基礎特徴未準備: " + base["reason"]
        return result
    current = base["sources"]["current"]
    j = current["index"]
    if j < 14:
        result["reason"] = "局所参照と反応にはindex14以降が必要"
        return result
    reference_indices, reaction_indices = list(range(j - 14, j - 4)), list(range(j - 4, j + 1))
    result["history"].update(reference_indices=reference_indices, reaction_indices=reaction_indices)
    required = set(range(10)) | set(reference_indices + reaction_indices)
    if not isinstance(frames, list):
        result["reason"] = "正本3分SOURCE配列なし"
        return result
    groups = defaultdict(list)
    for row in frames:
        if isinstance(row, dict) and type(row.get("index")) is int and row["index"] in required:
            groups[row["index"]].append(row)
    if any(len(group) > 1 for group in groups.values()):
        result["reason"] = "必要な正本3分足番号が重複"
        return result
    if set(groups) != required:
        result["reason"] = "局所帯又はORの正本3分出典不足"
        return result
    canonical = {}
    for index in sorted(required):
        row = groups[index][0]
        reason = source_reason(row, current["session"], 3, slot["scheduled"], (slot["time"], slot["line"]))
        if reason:
            result["reason"] = "正本3分: " + reason
            return result
        canonical[index] = {name: deepcopy(row[name]) for name in SOURCE}
    if canonical[j] != current:
        result["reason"] = "現3分と正本SOURCE不一致"
        return result
    if any(canonical[index] != {name: row[name] for name in SOURCE} for index, row in enumerate(slot["OR"]["sources"])):
        result["reason"] = "OR10本と正本SOURCE不一致"
        return result
    ordered = [canonical[index] for index in reference_indices + reaction_indices]
    if not all(adjacent(previous, row) for previous, row in zip(ordered, ordered[1:])):
        result["reason"] = "局所15本の番号・終了・公開順不連続"
        return result
    reference, reaction = ordered[:10], ordered[10:]
    high = max(Fraction(row["high"]) for row in reference)
    low = min(Fraction(row["low"]) for row in reference)
    midpoint, width = (high + low) / 2, high - low
    if not low <= Fraction(reference[-1]["close"]) <= high:
        raise ValueError("参照末終値の帯内不一致")
    upper, lower = reaction_state(reaction, float(high), 1), reaction_state(reaction, float(low), -1)
    controls, vectors, contexts = {}, {}, {}
    for side in (1, -1):
        own, opposite = (upper, lower) if side == 1 else (lower, upper)
        continued = own["out_count"] > 0 and own["final_state"] == 1
        returned = opposite["in_count"] > 0 and opposite["final_state"] == -1
        contexts[str(side)] = {"own_continuation": continued, "opposite_return": returned, "z": int(continued or returned)}
        try:
            controls[str(side)] = base["vectors"][str(side)] + [float(width / Fraction(base["atr"])),
                float(side * (Fraction(current["close"]) - midpoint) / Fraction(base["atr"]))]
        except OverflowError:
            result["reason"] = "局所帯特徴のfloat表示範囲外"
            return result
        if not all(finite(value) for value in controls[str(side)]):
            result["reason"] = "局所帯特徴の有限値不成立"
            return result
        vectors[str(side)] = controls[str(side)] + [contexts[str(side)]["z"]]
    result["history"].update(reference_sources=reference, reaction_sources=reaction,
        band={"low": float(low), "high": float(high), "mid": float(midpoint), "width": float(width),
              "reference_close": reference[-1]["close"], "initial_inside": True,
              "fixed_at_key": [reference[-1]["confirm"], reference[-1]["confirm_line"]],
              "first_reaction_key": [reaction[0]["confirm"], reaction[0]["confirm_line"]]},
        upper=upper, lower=lower, contexts=contexts)
    result.update(control_vectors=controls, vectors=vectors, ready=True, reason="")
    return result


def feature_metadata() -> list[dict]:
    """固定51の15列へ局所帯幅・位置・Zの3列契約を明示して足す。

    引数: なし。新特徴関数や市場入力を呼ばない。
    返り値: list[dict]は18列の独立期待metadata。
    """
    old = load(ROOT / "scripts/技法分岐学習/特徴.py", "局所帯分岐監査_旧列名契約")
    return deepcopy(old.FEATURES) + [
        {"id": "F16", "name": "局所参照帯幅対ATR", "method": "P03", "family": "price", "scale": "m03"},
        {"id": "F17", "name": "実方向の局所帯中央距離", "method": "P06", "family": "price", "scale": "m03"},
        {"id": "F18", "name": "局所帯の自方向継続又は反対端内復帰", "method": "P10", "family": "price", "scale": "m03"}]


def policy_features(prepared: dict, policy: str) -> dict:
    """同じ履歴準備で、B0の17列又はF0の18列だけを教師へ選ぶ。

    引数: prepared(dict)は枠IDから全履歴特徴への写像、policy(str)はB0/F0。
    返り値: dictはready/reason/vectorsのみの写像。履歴未知を0へ補完しない。
    """
    if policy not in POLICIES:
        raise ValueError("候補不正")
    key = "control_vectors" if policy == "B0" else "vectors"
    return {identity: {"ready": value["ready"], "reason": value["reason"], "vectors": deepcopy(value[key])}
            for identity, value in prepared.items()}


# ----------------------------------------
# 17/18列を区別し、モデルの全node・経路・教師所属を再構成する。

def float32(values: list, count: int | None = None) -> list[float]:
    """明示した17/18列を独立した向きのpackでfloat32へ変換する。

    引数: values(list)は有限特徴、count(int|None)は必要列数。省略時は配列長を使う。
    返り値: list[float]は正確なfloat32表現。欠測・片側を補完しない。
    """
    if not isinstance(values, list):
        raise ValueError("方向特徴はlistが必要")
    count = len(values) if count is None else count
    if count not in (17, 18) or len(values) != count or not all(finite(v) for v in values):
        raise ValueError("方向特徴は17又は18有限値が必要")
    if count == 18 and values[17] not in (0, 1):
        raise ValueError("Zはfloat32化前から0又は1が必要")
    result = [struct.unpack(">f", struct.pack(">f", value))[0] for value in values]
    if not all(finite(v) for v in result):
        raise ValueError("float32範囲外")
    return result


def walk(model: dict, values: list) -> tuple:
    """保存閾値をfloat32特徴へ適用して葉と経路を独立に得る。

    引数: model(dict)はJSON木、values(list)は17又は18特徴。
    返り値: tupleは葉ID・経路・通過nodeID。学習器のwalk/predictは使わない。
    """
    converted, node_id, path, visits = float32(values, len(model["feature_meta"])), 0, [], []
    while True:
        if type(node_id) is not int or not 0 <= node_id < len(model["nodes"]) or node_id in visits:
            raise ValueError("木の子ID又は循環")
        visits.append(node_id)
        node = model["nodes"][node_id]
        if node["id"] != node_id:
            raise ValueError("node ID不一致")
        if node["left"] == node["right"] == -1:
            return node_id, path, visits
        feature, threshold = node["feature"], node["threshold"]
        if type(feature) is not int or not 0 <= feature < len(model["feature_meta"]) or not finite(threshold):
            raise ValueError("木の特徴又は閾値不正")
        branch = "right" if converted[feature] > threshold else "left"
        meta = model["feature_meta"][feature]
        path.append({"node": node_id, "feature": feature, "feature_id": meta["id"], "method": meta["method"], "family": meta["family"],
                     "threshold": threshold, "comparison": ">" if branch == "right" else "<=", "branch": branch})
        node_id = node[branch]


def eligibility(node: dict, path: list) -> dict:
    """方向選択後に適用する支持・異種技法・率を分離する。

    引数: node(dict)は葉、path(list)は実際の経路。
    返り値: dictはscore/leaf_support/method_support/families。
    """
    families = sorted({step["family"] for step in path})
    return {"score": node["score"] is not None and node["score"] >= 1 / 3,
            "leaf_support": node["unique_slots"] >= 60 and node["days"] >= 6 and node["sessions"] >= 10,
            "method_support": len(families) >= 2 and bool(set(families) & {"trend", "osc"}), "families": families}


def predict(model: dict, vectors: dict) -> dict:
    """保存木の両方向を独立採点し、未知枝では既知側への救済も行わない。

    引数: model(dict)は検算済みB0/F0木、vectors(dict)は17/18列×両方向。
    返り値: dictは全予測。未知側だけscore/eligibilityをNoneとしraw既知値を保持する。
    """
    if not isinstance(vectors, dict) or set(vectors) != {"1", "-1"}:
        raise ValueError("両方向特徴が必要")
    if vectors["1"] == vectors["-1"] == []:
        return {"scores": {side: None for side in ("1", "-1")}, "leafs": {side: None for side in ("1", "-1")},
                "side": 0, "winner_side": 0, "reason": "特徴未準備WAIT", "eligibility": {side: None for side in ("1", "-1")}}
    scores, leafs, qualifications = {}, {}, {}
    for side in ("1", "-1"):
        leaf, path, _ = walk(model, vectors[side])
        node = model["nodes"][leaf]
        if node["path"] != path:
            raise ValueError("保存pathとwalk不一致")
        absent = node.get("data_absent") is True
        if absent and (node["score"] is not None or node["direction_rows"] != 0):
            raise ValueError("未知枝のscore0補完又は行数不整合")
        if not absent and (not finite(node["score"]) or not 0 <= node["score"] <= 1):
            raise ValueError("既知枝のscore不正")
        scores[side], leafs[side] = node["score"], leaf
        qualifications[side] = None if absent else eligibility(node, path)
    result = {"scores": scores, "leafs": leafs, "side": 0, "winner_side": 0, "reason": "同点WAIT", "eligibility": qualifications}
    if any(value is None for value in scores.values()):
        result["reason"] = "未学習枝WAIT"
        return result
    if scores["1"] != scores["-1"]:
        winner = "1" if scores["1"] > scores["-1"] else "-1"
        failures = [label for key, label in (("score", "最高側score下限未達"), ("leaf_support", "最高側葉支持不足"),
                    ("method_support", "最高側複数技法不足")) if not qualifications[winner][key]]
        result.update(winner_side=int(winner), side=0 if failures else int(winner), reason="/".join(failures) if failures else "採用")
    return result


def training_rows(entries: list[dict], blocks: dict, features: dict, baseline: dict, evaluation_start: float, count: int = 17) -> tuple:
    """保存B±の両方向を過去時点だけで構成し、未知pairを除外する。

    引数: entries(list[dict])は当phaseの過去場、blocks/features/baseline(dict)は保存出典、
        evaluation_start(float)は評価開始、count(int)は17又は18列数。
    返り値: tupleは使用方向行・training期待値・特徴準備件数。将来・片側・不足の0化は拒否する。
    """
    rows, reasons, total = [], Counter(), 0
    for entry in entries:
        for slot in blocks[entry["session"]]["slots"]:
            total += 1
            feature = features[slot["slot_id"]]
            if not feature["ready"]:
                reasons[feature["reason"]] += 1
                continue
            for side in (1, -1):
                key = (slot["slot_id"], side)
                if key not in baseline:
                    raise ValueError("教師の片側抜け")
                label = baseline[key]
                if any(label[k] != slot[k] for k in BINDING):
                    raise ValueError("教師の同時計出典不一致")
                row = {k: deepcopy(label[k]) for k in TEACHER_FIELDS if k != "features"}
                row["features"] = feature["vectors"][str(side)]
                row.update(entry_time=label.get("entry_time"), entry_line=label.get("entry_line"))
                if not finite(row["end_time"]) or not row["time"] <= row["end_time"] < evaluation_start:
                    raise ValueError("未来教師又は逆順時計")
                if type(row["filled"]) is not bool or row["outcome"] not in {*TARGETS, "不足", "未約定"}:
                    raise ValueError("教師結果の定義外")
                if row["outcome"] in TARGETS and (not row["filled"] or not finite(row["entry_time"]) or type(row["entry_line"]) is not int):
                    raise ValueError("使用教師の仮約定不足")
                if row["outcome"] == "未約定" and row["filled"]:
                    raise ValueError("未約定の不整合")
                float32(row["features"], count)
                row["features"] = [float(value) for value in row["features"]]
                rows.append(row)
    pairs = {}
    for row in rows:
        pair = pairs.setdefault((row["session"], row["slot_id"]), {})
        if row["side"] in pair:
            raise ValueError("教師方向重複")
        pair[row["side"]] = row
    eligible, excluded = set(), []
    for identity, pair in pairs.items():
        if set(pair) != {-1, 1}:
            raise ValueError("片側教師")
        if all(pair[side]["outcome"] in TARGETS for side in (1, -1)):
            eligible.add(identity)
        else:
            excluded.append({"session": identity[0], "slot_id": identity[1], "reason": "未約定又は不足を含むpair全体除外",
                             "outcomes": {str(s): pair[s]["outcome"] for s in (1, -1)}, "filled": {str(s): pair[s]["filled"] for s in (1, -1)}})
    used = [row for row in rows if (row["session"], row["slot_id"]) in eligible]
    if not used:
        raise ValueError("使用教師なし")
    ids = [{k: row[k] for k in ("session", "slot_id", "side")} for row in used]
    period = {"sessions": list(dict.fromkeys(row["session"] for row in used)), "first_scheduled": min(r["scheduled"] for r in used),
              "last_scheduled": max(r["scheduled"] for r in used), "max_label_end_key": list(max((r["end_time"], r["end_line"]) for r in used)),
              "max_input_label_end_key": list(max((r["end_time"], r["end_line"]) for r in rows)), "evaluation_start": float(evaluation_start), "same_second_allowed": False}
    training = {"input_pairs": len(pairs), "used_pairs": len(eligible), "excluded_pair_count": len(excluded), "excluded_pairs": excluded,
                "excluded_outcome_counts": dict(Counter("1=" + p["outcomes"]["1"] + ";-1=" + p["outcomes"]["-1"] for p in excluded)),
                "direction_rows": len(used), "weight_per_direction": .5, "total_weight": len(used) * .5,
                "row_ids": ids, "input_rows_sha256": fingerprint(rows), "used_rows_sha256": fingerprint(used), "row_ids_sha256": fingerprint(ids),
                "period": period, "period_sha256": fingerprint(period), "feature_missing_handling": "rootが同一局所帯readyなpairのみ入力。ここでは補完しない"}
    preparation = {"全枠": total, "特徴未準備枠": sum(reasons.values()), "特徴未準備理由": dict(reasons), "特徴準備枠": len(rows) // 2, "方向行数": len(rows)}
    return used, training, preparation


def classifier_parameters(depth: int) -> dict:
    """保存木又は17列子木の固定引数を独立に定義する。

    引数: depth(int)は自由木4又は子木3。
    返り値: dictは固定scikit-learn引数。fitそのものは呼ばない。
    """
    return {"criterion": "gini", "splitter": "best", "max_depth": depth, "min_samples_split": 2,
            "min_samples_leaf": 60, "min_weight_fraction_leaf": 0., "max_features": None, "random_state": 51,
            "max_leaf_nodes": None, "min_impurity_decrease": 0., "class_weight": None, "ccp_alpha": 0., "monotonic_cst": None}


def check_model(model: dict, used: list[dict], training: dict, meta: list[dict], policy: str, model_id: str, learner_sha: str, audit) -> None:
    """自由木又は固定根合成木の全教師所属・空枝・gini・支持を再構成する。

    引数: model(dict)は保存木、used(list[dict])/training(dict)は独立教師、meta(list[dict])は列契約、
        policy/model_id/learner_sha(str)は候補・識別子・版、audit(Audit)は記録。
    返り値: None。根のgini最適性、最良閾値全探索、再fitは要求しない。
    """
    audit.check(model_id + ":schema", (model["schema_version"], model["model_id"], model["policy"]), (1, model_id, policy))
    audit.check(model_id + ":metadata全属性", model["feature_meta"], meta)
    audit.check(model_id + ":metadata指紋", model["feature_meta_sha256"], fingerprint(meta))
    audit.check(model_id + ":学習code", model["source_sha256"], learner_sha)
    audit.check(model_id + ":library", model["versions"]["scikit-learn"], "1.9.1")
    audit.check(model_id + ":本体引数", model["parameters"], classifier_parameters(4))
    audit.check(model_id + ":子引数", model["subtree_parameters"], classifier_parameters(3) if policy == "F0" else None)
    fixed_rule = {"feature": "F18", "index": 17, "threshold": .5, "child_depth": 3, "child_features": 17,
                  "Z定義域": [0, 1], "gini最適分割ではない": True}
    rules = {"政策深さ": POLICIES, "政策特徴数": FEATURE_COUNTS, "random_state": 51, "criterion": "gini", "splitter": "best",
             "min_samples_leaf": 60, "min_samples_split": 2, "class_weight": None, "ccp_alpha": 0., "max_features": None,
             "方向行重み": .5, "score下限": {"分子": 1, "分母": 3, "等号可": True},
             "葉支持": {"unique枠": 60, "日": 6, "場": 10}, "path異種family最低": 2,
             "path必須family候補": ["trend", "osc"], "方向差": "strict", "予測入力型": "float32",
             "F0強制root": fixed_rule, "未知leaf": "両方向のどちらか到達なら未学習枝WAIT。scoreを0補完しない"}
    audit.check(model_id + ":全規約", model["rules"], rules)
    structure = ({"kind": "free", "max_depth": 4, "features": 17} if policy == "B0" else
                 {"kind": "fixed_root", "feature": "F18", "index": 17, "threshold": .5, "child_depth": 3,
                  "child_features": 17, "max_depth": 4, "root_gini_optimized": False})
    audit.check(model_id + ":構造", model["structure"], structure)
    nodes, paths = model["nodes"], {0: []}
    for index, node in enumerate(nodes):
        audit.check(model_id + ":node順", node["id"], index)
        audit.check(model_id + ":depth", len(paths[index]) <= 4, True)
        audit.check(model_id + ":path", node["path"], paths[index])
        if node["left"] == node["right"] == -1:
            audit.check(model_id + ":葉記号", (node["feature"], node["feature_id"], node["family"], node["threshold"]), (-2, None, None, -2.))
            continue
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < len(meta) or not finite(node["threshold"]):
            raise ValueError("分岐特徴又は閾値不正")
        if policy == "F0" and index == 0:
            audit.check(model_id + ":固定根", (feature, node["feature_id"], node["family"], node["threshold"], node["left"]), (17, "F18", "price", .5, 1))
        else:
            audit.check(model_id + ":子/自由分岐17列", feature < 17, True)
        audit.check(model_id + ":分岐metadata", (node["feature_id"], node["family"]), (meta[feature]["id"], meta[feature]["family"]))
        for branch, comparison in (("left", "<="), ("right", ">")):
            child = node[branch]
            if type(child) is not int or not index < child < len(nodes) or child in paths:
                raise ValueError("子ID・重複親不正")
            paths[child] = paths[index] + [{"node": index, "feature": feature, "feature_id": meta[feature]["id"],
                "method": meta[feature]["method"], "family": meta[feature]["family"], "threshold": node["threshold"],
                "comparison": comparison, "branch": branch}]
    audit.check(model_id + ":到達可能全node", set(paths), set(range(len(nodes))))
    membership = defaultdict(list)
    for row in used:
        leaf, path, visits = walk(model, row["features"])
        audit.check(model_id + ":全方向leaf経路", path, nodes[leaf]["path"])
        for index in visits:
            membership[index].append(row)
    expected_training = deepcopy(training)
    expected_training["partition"] = None
    if policy == "F0":
        partition = {}
        for z, branch in ((0, "left"), (1, "right")):
            selected = [row for row in used if row["features"][17] == z]
            child_ids = [index for index in paths if paths[index] and paths[index][0]["branch"] == branch]
            root = nodes[0][branch]
            audit.check(model_id + branch + ":子ID連続", sorted(child_ids), list(range(root, root + len(child_ids))))
            audit.check(model_id + branch + ":全branch教師一対一", membership[root], selected)
            audit.check(model_id + branch + ":子depth3", all(len(paths[index]) - 1 <= 3 for index in child_ids), True)
            if not selected:
                audit.check(model_id + branch + ":空枝一葉", len(child_ids), 1)
                audit.check(model_id + branch + ":空枝未学習葉", (nodes[root]["left"], nodes[root]["right"], nodes[root]["data_absent"]), (-1, -1, True))
            identities = [{key: row[key] for key in ("session", "slot_id", "side")} for row in selected]
            partition[str(z)] = {"direction_rows": len(selected), "pair_unique": len({(row["session"], row["slot_id"]) for row in selected}),
                "days": len({row["session"][:10] for row in selected}), "sessions": len({row["session"] for row in selected}),
                "row_ids_sha256": fingerprint(identities), "fit_performed": bool(selected), "root": root,
                "node_count": len(child_ids), "fit_parameters": classifier_parameters(3)}
        audit.check(model_id + ":右子offset", nodes[0]["right"], 1 + partition["0"]["node_count"])
        audit.check(model_id + ":枝分割は全方向行", sum(item["direction_rows"] for item in partition.values()), len(used))
        expected_training["partition"] = partition
    audit.check(model_id + ":教師とpartition全属性", model["training"], expected_training)
    for index, node in enumerate(nodes):
        rows = membership[index]
        successes = sum(TARGETS[row["outcome"]] for row in rows)
        score = successes / len(rows) if rows else None
        expected = {"direction_rows": len(rows), "weighted_rows": len(rows) / 2, "success_weight": successes / 2,
                    "total_weight": len(rows) / 2, "score": score,
                    "unique_slots": len({(row["session"], row["slot_id"]) for row in rows}),
                    "days": len({row["session"][:10] for row in rows}), "sessions": len({row["session"] for row in rows}),
                    "methods": sorted({step["method"] for step in paths[index]}), "families": sorted({step["family"] for step in paths[index]}),
                    "training_ids_sha256": fingerprint([{key: row[key] for key in ("session", "slot_id", "side")} for row in rows]),
                    "impurity": 2 * score * (1 - score) if score is not None else None, "data_absent": not bool(rows)}
        for key, value in expected.items():
            audit.check(model_id + str(index) + ":" + key, node[key], value)
        audit.check(model_id + ":data_absent型", type(node["data_absent"]) is bool, True)
        qualified = eligibility(node, paths[index])
        audit.check(model_id + str(index) + ":支持旗", (node["leaf_support"], node["method_support"]), (qualified["leaf_support"], qualified["method_support"]))
        if node["left"] != -1 and not (policy == "F0" and index == 0):
            audit.check(model_id + ":通常分岐minleaf60", min(len(membership[node["left"]]), len(membership[node["right"]])) >= 60, True)
        if not rows:
            audit.check(model_id + ":未知はF0の空直子だけ", policy == "F0" and index in (nodes[0]["left"], nodes[0]["right"]), True)




# ----------------------------------------
# 保存46場・92運用を照合する。初期20場の実運用評価は作らない。

def phases(entries: list[dict], source) -> list[dict]:
    """台帳を場単位の三つの拡大学習へ固定する。

    引数: entries(list[dict])は66場、source(ModuleType)は固定暦。
    返り値: list[dict]は学習20/30/40と評価10/10/26の排他的な構成。
    """
    if len(entries) != 66:
        raise ValueError("固定66場が必要")
    return [{"id": name, "train": entries[:start], "evaluation": entries[start:stop],
             "evaluation_start": source.calendar(entries[start]["session"])[0]}
            for name, start, stop in (("W20", 20, 30), ("W30", 30, 40), ("F40", 40, 66))]


def control_account(op: dict, source, audit) -> dict:
    """旧H0の同46場を、保存完結価格の別式現金で集計する。

    引数: op(dict)は固定50の保存運用、source(ModuleType)はDecimal現金補助、audit(Audit)は記録。
    返り値: dictは期間集計用の会計。旧戦略や未対象20場の運用は再生しない。
    """
    observed = {str(fee): Decimal(0) for fee in (0, 5, 10)}
    for position in op["closed"]:
        for fee in (0, 5, 10):
            value = source.cash_pair(position["entry_price"], position["exit_price"], position["side"], fee)
            audit.check("旧H0保存完結現金", Decimal(str(position["pnl" + str(fee)])), value)
            observed[str(fee)] += value
    unresolved = int(op["final_state"]["position"] is not None)
    ledger = {str(fee): float(observed[str(fee)] - unresolved * (11 + fee * 10)) for fee in (0, 5, 10)}
    return {"session": op["session"], "candidate": "H0", "observed": {key: float(value) for key, value in observed.items()},
            "ledger": ledger, "unresolved": unresolved, "closed": op["closed"], "decisions": op["decisions"],
            "caution": bool(op["quality"]["損益注意理由"])}


def check_periods(accounts: list[dict], labels: dict, result: dict, source, summary_helper, audit) -> None:
    """評価46場だけの先着・薄化・費用・活動・役割を照合する。

    引数: accounts(list[dict])/labels(dict)は独立会計と保存先着、result(dict)は新結果、source/summary_helper(ModuleType)は固定純集計、audit(Audit)は記録。
    返り値: None。学習専用20場の成績や未来fitは追加しない。
    """
    for policy in ("H0", *POLICIES):
        selected = [row for row in accounts if row["candidate"] == policy]
        for period in PERIODS:
            expected_entry = source.entry_summary(labels[policy], period)
            expected_operation = summary_helper.operation_summary(selected, period, source)
            actual = result["候補"][policy][period]
            audit.check(policy + period + ":入口全属性", actual["入口"], expected_entry)
            audit.check(policy + period + ":運用全属性", actual["運用"], expected_operation)
            audit.check(policy + period + ":同時適格", actual["同時適格"], expected_entry["70目標"] and expected_operation["活動適格"] and expected_operation["費用適格"])
            for role in ("順行", "反転"):
                role_entry = source.entry_summary([row for row in labels[policy] if row["role"] == role], period)
                audit.check(policy + period + role + ":役割入口", result["役割別入口"][policy][period][role], role_entry)
            if policy in POLICIES:
                reasons = Counter(decision["reason"] for row in selected if source.span(row["session"]) == period for decision in row["decisions"])
                audit.check(policy + period + ":全判断理由", result["判断理由"][policy][period], dict(reasons))
    audit.check("新政策だけの採用", result["採用"], [p for p in POLICIES if all(result["候補"][p][period]["同時適格"] for period in PERIODS[:2])])


def leaf_statistics(manifests: list[dict], models: dict, bindings: dict, labels: dict, accounts: list[dict], source) -> list[dict]:
    """検算済み採用枠を固定木の葉へ対応し、空群を含め別集計する。

    引数: manifests(list[dict])/models(dict)は六木、bindings(dict)は政策/枠→モデル/葉、labels(dict)は先着、accounts(list[dict])は独立会計、source(ModuleType)は期間集計。
    返り値: list[dict]は全leaf×phase内期間。注意はモデル期間全体であり葉に帰属させない。
    """
    entries, completions = defaultdict(list), defaultdict(list)
    for policy in POLICIES:
        for label in labels[policy]:
            identity, leaf = bindings[policy, label["slot_id"]]
            entries[identity, leaf, source.span(label["session"])].append(label)
    for account in accounts:
        if account["candidate"] not in POLICIES:
            continue
        for position in account["closed"]:
            identity, leaf = bindings[account["candidate"], position["slot_id"]]
            completions[identity, leaf, source.span(account["session"])].append(position)
    result = []
    for manifest in manifests:
        identity, policy, sessions = manifest["id"], manifest["policy"], set(manifest["評価場"])
        for period in PERIODS:
            if not any(source.span(session) == period for session in sessions):
                continue
            cautions = [account["session"] for account in accounts if account["candidate"] == policy and account["session"] in sessions
                        and source.span(account["session"]) == period and account["caution"]]
            for node in models[identity]["nodes"]:
                if node["left"] != -1:
                    continue
                key = (identity, node["id"], period)
                closed = completions[key]
                amount = sum(Decimal(str(row["pnl5"])) for row in closed)
                result.append({"model_id": identity, "policy": policy, "phase": manifest["phase"], "leaf": node["id"], "period": period,
                               "入口": source.entry_summary(entries[key], period), "実完結": len(closed), "実観測純額5": float(amount),
                               "品質注意場": cautions, "品質注意の範囲": "同じモデル評価期間全体。葉への帰属ではない"})
    return result


def context_statistics(contexts: dict, labels: dict, accounts: list[dict], source) -> list[dict]:
    """検算した採用方向Zを入口と実完結へ別々に結び、12行を再集計する。

    引数: contexts(dict)は政策/枠→Z、labels(dict)は検算済み先着、accounts(list[dict])は保存会計、source(ModuleType)は純期間集計。
    返り値: list[dict]は候補2×期間3×Z2。品質注意は候補期間全体で、局面限定の再運用ではない。
    """
    result = []
    for policy in POLICIES:
        for period in PERIODS:
            selected_accounts = [row for row in accounts if row["candidate"] == policy and source.span(row["session"]) == period]
            cautions = [row["session"] for row in selected_accounts if row["caution"]]
            for z in (0, 1):
                chosen = [row for row in labels[policy] if source.span(row["session"]) == period and contexts[policy, row["slot_id"]] == z]
                closed = [row for account in selected_accounts for row in account["closed"] if contexts[policy, row["slot_id"]] == z]
                amount = sum((Decimal(str(row["pnl5"])) for row in closed), Decimal(0))
                result.append({"policy": policy, "period": period, "z": z, "入口": source.entry_summary(chosen, period),
                               "実完結": len(closed), "実観測純額5": float(amount), "品質注意場": cautions,
                               "品質注意の範囲": "同じ候補の期間全体。局面への帰属ではない"})
    return result


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """138資源と新二政策各一代表のAPI数値を照合する。

    引数: base(str|None)は任意接続先、resources(list[dict])は全資源、accounts(list[dict])は会計、source(ModuleType)/audit(Audit)は補助。
    返り値: dictは接続範囲。旧H0の市場再生や画像取得はしない。
    """
    if not base:
        return {"実行": False, "理由": "--viewer-url未指定。API未検証、新92保存約定は全件照合"}
    query = {"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}
    listed, _, _ = source.fetch_json(base + "/api/resources?" + urlencode(query))
    audit.check("API138全集合", {r["id"] for r in listed["resources"]}, {r["id"] for r in resources})
    audit.check("API138一意", len(listed["resources"]), 138)
    representatives = []
    for policy in POLICIES:
        account = sorted([r for r in accounts if r["candidate"] == policy], key=lambda r: (-abs(r["ledger"]["5"]), r["session"]))[0]
        resource = next(r for r in resources if r["session"] == account["session"] and r["method_id"] == policy)
        parameters = {**query, "resource": resource["id"], "interval": "5", "price": "last", "width": 1000, "height": 700}
        meta, _, _ = source.fetch_json(base + "/api/chart?" + urlencode(parameters))
        data, raw, headers = source.fetch_json(urljoin(base + "/", meta["data_url"]))
        audit.check("API本文SHA", hashlib.sha256(raw).hexdigest(), meta["data_sha256"])
        audit.check("APIヘッダSHA", headers.get("x-chart-data-sha256"), meta["data_sha256"])
        audit.check("API集計alias", data["summary"], meta["summary"])
        audit.check("API台帳観測5円", Decimal(str(data["summary"]["realized_pnl_yen"])), Decimal(str(account["ledger"]["5"])))
        saved = list(source.json_rows(ROOT / resource["pnl_path"]))
        audit.check("API約定片数", len(data["events"]), len(saved))
        for seq, (trade, event) in enumerate(zip(saved, data["events"]), 1):
            for key in ("type", "qty", "position_id", "method_id", "price"):
                audit.check("API約定" + key, event[key], trade[key])
            audit.check("API原順", event["sequence"], seq)
            audit.check("APIミリ秒", abs(event["timestamp_ms"] - datetime.fromisoformat(trade["timestamp"]).timestamp() * 1000) <= .001, True)
        representatives.append({"候補": policy, "場": account["session"], "資源ID": resource["id"], "台帳観測5円": account["ledger"]["5"], "数値SHA256": meta["data_sha256"]})
    return {"実行": True, "全資源数": len(listed["resources"]), "新政策代表": representatives, "代表規約": "候補別最大絶対台帳観測額。採否へ不使用"}


def run(viewer_url: str | None = None) -> dict:
    """rootの一回実行後に、過去教師・六木・92運用の保存証明を一度作る。

    引数: viewer_url(str|None)は任意Viewer。
    返り値: dictは合否と範囲。不一致でも保存し、既存証明の上書きは禁止する。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    source, label_helper, summary_helper = helpers()
    audit = source.Audit()
    paths = [STUDY / name for name in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    paths += [WORK / "定時判断と運用.jsonl.gz", WORK / "入口先着.jsonl.gz", LABELS, source.MANIFEST, FRAMES,
              BASEWORK / "定時判断と運用.jsonl.gz", BASESTUDY / "保存物確認.json",
              OLD / "結果.json", OLD / "保存物確認.json", OLD / "一覧.resources.json", OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz",
              Path(__file__), Path(__file__).with_name("特徴.py"), Path(__file__).with_name("学習.py"),
              ROOT / "scripts/定時帯反応/保存物確認.py", ROOT / "scripts/定時帯反応/期限同秒確認.py", ROOT / "scripts/局所再開/保存物確認.py"]
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in paths}
    fixed, result = source.read(STUDY / "固定.json"), source.read(STUDY / "結果.json")
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典:" + name, source.sha(ROOT / name), digest)
    audit.check("監査自身の固定包含", Path(__file__).relative_to(ROOT).as_posix() in fixed["ファイルSHA256"], True)
    audit.check("試行と固定bind", (result["試行"], result["固定SHA256"]), (53, source.sha(STUDY / "固定.json")))
    audit.check("新旧候補集合", set(result["候補"]), {"H0", *POLICIES})
    old_proof = source.read(OLD / "保存物確認.json")
    audit.check("保存52の成功証明", (old_proof["全件一致"], old_proof["不一致数"]), (True, 0))
    for name in ((OLDWORK / "定時判断と運用.jsonl.gz").relative_to(ROOT).as_posix(), (OLDWORK / "入口先着.jsonl.gz").relative_to(ROOT).as_posix()):
        audit.check("旧正本証明SHA:" + name, source.sha(ROOT / name), old_proof["参照SHA256"][name])
    entries = source.read(source.MANIFEST)["entries"]
    phase_list = phases(entries, source)
    evaluated = [entry["session"] for entry in entries[20:]]
    audit.check("評価46場の完全順", result["評価場"], evaluated)
    audit.check("初期20場は学習専用", result["学習専用場"], [e["session"] for e in entries[:20]])
    audit.check("対照は同46場の保存再集計", result["対照参照"], {"候補": "H0", "元試行": 52, "同じ評価46場に保存値を再集計": True, "市場再生": False})
    control_blocks = {}
    for block in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz"):
        if block["policy"] == "H0":
            audit.check("旧H0運用一意", block["session"] not in control_blocks, True)
            control_blocks[block["session"]] = block
    audit.check("旧H0評価46場", set(control_blocks), set(evaluated))
    frames = defaultdict(list)
    for row in source.json_rows(FRAMES):
        if row["minutes"] == 3:
            frames[row["場"]].append({"session": row["場"], **{key: row[key] for key in SOURCE if key != "session"}})
    audit.check("価格SOURCE66場", set(frames), {entry["session"] for entry in entries})
    audit.check("全価格SOURCEの保存数と指紋", result["価格SOURCE"],
                {session: {"足数": len(rows), "SHA256": fingerprint(rows)} for session, rows in frames.items()})
    blocks = {}
    for block in source.json_rows(BASEWORK / "定時判断と運用.jsonl.gz"):
        if block["policy"] == "P0":
            audit.check("旧P0場の一意", block["session"] not in blocks, True)
            blocks[block["session"]] = block
    audit.check("特徴材料66場", set(blocks), {e["session"] for e in entries})
    features, source_slots = {}, {}
    for block in blocks.values():
        audit.check("旧P0全予定順", [s["scheduled"] for s in block["slots"]], source.calendar(block["session"])[3])
        for slot in block["slots"]:
            if slot["slot_id"] in source_slots:
                raise ValueError("保存slot ID重複")
            source_slots[slot["slot_id"]] = slot
            features[slot["slot_id"]] = expected_feature(slot, frames[block["session"]])
    audit.check("基礎全66場2442予定枠", len(source_slots), 2442)
    baseline = {}
    for row in source.json_rows(LABELS):
        if row["policy"] in ("B+", "B-"):
            identity = (row["slot_id"], row["side"])
            audit.check("教師方向の一意", identity not in baseline, True)
            baseline[identity] = row
    all_meta = feature_metadata()
    audit.check("独立18列metadata", len(all_meta), 18)
    selected_features = {policy: policy_features(features, policy) for policy in POLICIES}
    expected_preparation = {}
    for period in PERIODS:
        subset = [features[s["slot_id"]] for session in evaluated if source.span(session) == period for s in blocks[session]["slots"]]
        expected_preparation[period] = {"全予定枠": len(subset), "旧特徴準備": sum(f["base"]["ready"] for f in subset),
            "共通履歴準備": sum(f["ready"] for f in subset),
            "履歴追加で未準備": sum(f["base"]["ready"] and not f["ready"] for f in subset),
            "追加未準備理由": dict(Counter(f["reason"] for f in subset if f["base"]["ready"] and not f["ready"])),
            "買売Z分布": dict(Counter(str(f["history"]["contexts"]["1"]["z"]) + str(f["history"]["contexts"]["-1"]["z"])
                                     for f in subset if f["ready"]))}
    audit.check("全期間の共通準備分母", result["準備比較"], expected_preparation)
    models, by_session_model, model_pins, phase_details = {}, {}, {}, []
    audit.check("全6学習モデル", len(result["モデル"]), 6)
    manifests = {record["id"]: record for record in result["モデル"]}
    audit.check("モデルID一意", len(manifests), 6)
    audit.check("モデル台帳のphase政策順", [r["id"] for r in result["モデル"]], [policy + "_" + phase["id"] for phase in phase_list for policy in POLICIES])
    for phase in phase_list:
        phase_ids = {}
        for policy in POLICIES:
            used, training, preparation = training_rows(phase["train"], blocks, selected_features[policy], baseline,
                                                       phase["evaluation_start"], FEATURE_COUNTS[policy])
            phase_ids[policy] = training["row_ids_sha256"]
            meta = all_meta[:FEATURE_COUNTS[policy]]
            identity = policy + "_" + phase["id"]
            path = STUDY / "models" / (identity + ".json")
            model, digest = source.read(path), source.sha(path)
            model_pins[path.relative_to(ROOT).as_posix()] = digest
            expected_manifest = {"id": identity, "policy": policy, "phase": phase["id"], "path": path.relative_to(ROOT).as_posix(), "SHA256": digest,
                                 "学習場": [e["session"] for e in phase["train"]], "評価場": [e["session"] for e in phase["evaluation"]], "特徴準備": preparation, "特徴数": len(meta), "評価開始": phase["evaluation_start"]}
            audit.check(identity + ":モデルmanifest全属性", manifests[identity], expected_manifest)
            check_model(model, used, training, meta, policy, identity, source.sha(Path(__file__).with_name("学習.py")), audit)
            for name in ("Python", "NumPy", "scikit-learn"):
                audit.check(identity + ":固定環境" + name, model["versions"][name], fixed[name])
            models[identity] = model
            for entry in phase["evaluation"]:
                by_session_model[entry["session"], policy] = identity
        audit.check(phase["id"] + ":B0F0共通教師全rowID", phase_ids["B0"], phase_ids["F0"])
        phase_details.append({"共通教師ID指紋": phase_ids, "phase": phase["id"], "学習場数": len(phase["train"]), "評価場数": len(phase["evaluation"]),
                              "使用pair数": training["used_pairs"], "除外pair数": training["excluded_pair_count"], "方向行数": len(used),
                              "最終教師終了key": training["period"]["max_input_label_end_key"], "評価開始": phase["evaluation_start"]})
    detail = defaultdict(list)
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        detail[block["session"]].append(block)
    audit.check("新詳細は46場のみ", set(detail), set(evaluated))
    labels = {p: [] for p in POLICIES}
    by_label_session = defaultdict(list)
    for row in source.json_rows(WORK / "入口先着.jsonl.gz"):
        if row["policy"] not in POLICIES:
            raise ValueError("新先着へ旧対照又は未知政策が混入")
        labels[row["policy"]].append(row)
        by_label_session[row["session"]].append(row)
    audit.check("新先着も評価場のみ", set(by_label_session) <= set(evaluated), True)
    resources = source.read(STUDY / "一覧.resources.json")["resources"]
    resource_map = {(row["session"], row["method_id"]): row for row in resources}
    audit.check("資源138集合", set(resource_map), {(s, p) for s in evaluated for p in ("H0", *POLICIES)})
    audit.check("資源138一意", len(resources), 138)
    audit.check("資源ID一意", len({row["id"] for row in resources}), 138)
    old_resources = source.read(OLD / "一覧.resources.json")["resources"]
    for resource in old_resources:
        if resource["method_id"] == "H0" and resource["session"] in evaluated:
            expected = {**resource, "title": resource["session"] + " H0 固定52対照"}
            audit.check("旧H0資源strict参照", resource_map[resource["session"], "H0"], expected)
            audit.check("旧H0約定固定包含", expected["pnl_path"] in fixed["ファイルSHA256"], True)
    accounts, cache_pins, viewer_pins, slot_count = [], {}, {}, 0
    adopted_bindings, expected_label_order, expected_session_rows = {}, {p: [] for p in POLICIES}, []
    adopted_contexts = {}
    evaluated_entries = {e["session"]: e for e in entries[20:]}
    for session in evaluated:
        tape, name, digest = source.load_tape(evaluated_entries[session], audit)
        cache_pins[name] = digest
        new_blocks = detail[session]
        audit.check(session + ":新二政策順", [b["policy"] for b in new_blocks], list(POLICIES))
        expected_labels = {}
        for block in new_blocks:
            policy, op = block["policy"], block["operation"]
            identity = by_session_model[session, policy]
            audit.check("運用IDと場", (op["session"], op["candidate_id"]), (session, policy))
            audit.check("block phase", block["phase"], identity.split("_")[1])
            audit.check("品質確定旗", op["quality"]["損益確定可能"], not bool(op["quality"]["損益注意理由"]))
            source.check_decisions(block, tape, audit)
            source.check_orders(op, tape, audit)
            source.check_trail(op, tape, audit)
            resource = resource_map[session, policy]
            path = ROOT / resource["pnl_path"]
            audit.check("新Viewer保存先", path.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            accounts.append(source.check_cash(op, list(source.json_rows(path)), tape, audit))
            expected_session_rows.append({"場": session, "候補": policy, "期間": source.span(session), "phase": block["phase"],
                                          "入力品質": block["input_quality"], "運用品質": op["quality"], "運用集計": op["metrics"]})
            for slot in block["slots"]:
                slot_count += 1
                old = source_slots[slot["slot_id"]]
                audit.check("定時価格key完全継承", {k: slot[k] for k in BINDING}, {k: old[k] for k in BINDING})
                feature = features[slot["slot_id"]]
                audit.check("独立局所帯17/18特徴全属性", slot["feature"], feature)
                expected_prediction = predict(models[identity], feature["control_vectors" if policy == "B0" else "vectors"]) if feature["ready"] else None
                audit.check("JSON木の全予測属性", slot["prediction"], expected_prediction)
                side = expected_prediction["side"] if expected_prediction else 0
                reason = expected_prediction["reason"] if expected_prediction else feature["reason"]
                if side and feature["background_direction"] == 0:
                    side, reason = 0, "上位DI同値の役割未確定WAIT"
                role = "待機" if not side else "順行" if side == feature["background_direction"] else "反転"
                expected_slot = {**{k: old[k] for k in BINDING}, "policy": policy, "phase": identity.split("_")[1], "model_id": identity,
                                 "side": side, "role": role, "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
                                 "feature": feature, "prediction": expected_prediction}
                audit.check("新slot全属性", slot, expected_slot)
                if feature["ready"] and side:
                    baseline_row = baseline[slot["slot_id"], side]
                    audit.check("先着コピー元同時計", {k: baseline_row[k] for k in BINDING}, {k: slot[k] for k in BINDING})
                    expected_labels[policy, slot["slot_id"]] = {**baseline_row, "policy": policy, "role": role}
                    expected_label_order[policy].append(expected_labels[policy, slot["slot_id"]])
                    adopted_bindings[policy, slot["slot_id"]] = identity, expected_prediction["leafs"][str(side)]
                    adopted_contexts[policy, slot["slot_id"]] = feature["history"]["contexts"][str(side)]["z"]
        actual_labels = by_label_session[session]
        audit.check("全新先着集合", {(r["policy"], r["slot_id"]) for r in actual_labels}, set(expected_labels))
        audit.check("全新先着一意", len(actual_labels), len(expected_labels))
        for row in actual_labels:
            audit.check("保存B±全属性コピー", row, expected_labels[row["policy"], row["slot_id"]])
            _, force, _, _ = source.calendar(session)
            expected = {**{k: row[k] for k in (*BINDING, "policy", "side", "role")}, **label_helper.first_force_expected(tape, row, force, source)}
            audit.check("原BBO直接先着全属性", row, expected)
        accounts.append(control_account(control_blocks[session]["operation"], source, audit))
        print(session + " 木・先着・保存運用確認", flush=True)
    labels["H0"] = [row for row in source.json_rows(OLDWORK / "入口先着.jsonl.gz") if row["policy"] == "H0" and row["session"] in set(evaluated)]
    for policy in POLICIES:
        audit.check("先着の全保存順:" + policy, labels[policy], expected_label_order[policy])
    audit.check("新92場別表示全属性", result["場別"], expected_session_rows)
    check_periods(accounts, labels, result, source, summary_helper, audit)
    old_result = source.read(OLD / "結果.json")
    audit.check("旧H0候補全属性保存同値", result["候補"]["H0"], old_result["候補"]["H0"])
    audit.check("旧H0役割別入口保存同値", result["役割別入口"]["H0"], old_result["役割別入口"]["H0"])
    expected_leaf_rows = leaf_statistics(result["モデル"], models, adopted_bindings, labels, accounts, source)
    audit.check("全葉別評価と空群の独立join", result["葉別評価"], expected_leaf_rows)
    expected_context_rows = context_statistics(adopted_contexts, labels, accounts, source)
    audit.check("局面別12行の独立join", result["局面別評価"], expected_context_rows)
    audit.check("局面別は全12行", len(expected_context_rows), 12)
    audit.check("新92運用", sum(row["candidate"] in POLICIES for row in accounts), 92)
    expected_slot_count = sum(len(source.calendar(s)[3]) for s in evaluated) * 2
    audit.check("46場2政策の全予定", slot_count, expected_slot_count)
    audit.check("新詳細2系列", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins}.items():
        audit.check("実行中不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 53, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0,
               "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
               "本物fit再実行": False, "市場戦略再生": False, "主モデルimport": False, "指標bank再計算": False,
               "検証範囲": "保存50全slotと固定28SOURCEから独立局所帯17/18特徴、過去B±pair・除外・.5重み・全training指紋、B0自由木/F0固定根合成木各三JSON、全node所属/score/gini/支持/空枝/経路/全予測・局面別12行、評価46場新92運用/正常BBO/現金/追尾変化点/先着/全予定分母。",
               "限定": "最適なgreedy分岐の独立再学習、実時間のモデル保存順の再現、変化のない全tick保護の再生はしない。固定学習コードとJSON版を結び、各教師終了秒は評価開始よりstrict前、評価slotは所定phaseモデルだけを参照する。葉の学習率は未来確率でない。",
               "評価場数": len(evaluated), "学習専用場数": 20, "新運用数": 92, "全予定比較数": slot_count,
               "先着件数": {p: len(rows) for p, rows in labels.items()}, "phase検算": phase_details, "全葉別評価行数": len(expected_leaf_rows), "全局面別評価行数": len(expected_context_rows),
               "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload



# ----------------------------------------
# 人工だけを使い、履歴・共通教師・木の寸法と保存集計を検査する。

def rejects(function, *args) -> bool:
    """不正な人工入力が例外で拒否されるか確かめる。

    引数: function(Callable)は純検査、args(tuple)は人工引数。
    返り値: boolはValueError等が発生したか。
    """
    try:
        function(*args)
    except (ValueError, KeyError, TypeError, OverflowError):
        return True
    return False


def self_test() -> dict:
    """人工の参照/反応と自由・固定根・空枝を全属性で結合検査する。

    引数: なし。本物入力を開かず、B0/F0/空枝F0の人工fit APIを各1回呼ぶ。
    返り値: dictは人工比較結果。正式モデル・保存監査証明は作らない。
    """
    source, label_helper, _ = helpers()
    audit = source.Audit()
    tests = load(Path(__file__).with_name("特徴の人工検査.py"), "局所帯監査_人工材料")
    feature_module = load(Path(__file__).with_name("特徴.py"), "局所帯監査_人工対象")
    patterns = ([115, 112, 114, 116, 115], [85, 90, 95, 97, 100], [85, 95, 115, 105, 115],
                [85, 95, 115, 105, 100], [110] * 5, [100] * 5)
    fixtures = []
    for values in patterns:
        material = tests.fixture(list(values))
        fixtures.extend((material, tests.reflect(*material)))
    for j in (9, 13, 14, 29):
        fixtures.append(tests.fixture(j=j))
    import random
    randomizer = random.Random(53)
    for _ in range(30):
        material = tests.fixture([randomizer.choice((85, 90, 95, 100, 105, 110, 115, 120)) for _ in range(5)])
        fixtures.extend((material, tests.reflect(*material)))
    slot, frames = tests.fixture([85, 95, 115, 105, 115])
    for name, value in (("publish", False), ("missing", 1), ("confirm_line", 9999), ("end", 5000)):
        broken = deepcopy(frames)
        broken[15][name] = value
        fixtures.append((slot, broken))
    fixtures.extend(((slot, frames[:15] + frames[16:]), (slot, frames + [deepcopy(frames[15])]), (slot, None)))
    mismatch = deepcopy(frames)
    mismatch[-1]["open"] += .5
    fixtures.append((slot, mismatch))
    mismatch = deepcopy(frames)
    mismatch[0]["open"] += .5
    fixtures.append((slot, mismatch))
    for material, values in fixtures:
        audit.check("独立17/18全返却属性", expected_feature(material, values), feature_module.extract(material, values))
    audit.check("独立18列metadata", feature_module.FEATURES, feature_metadata())
    result = expected_feature(slot, frames)
    audit.check("反対復帰と自継続の両旗", result["history"]["contexts"]["1"],
                {"own_continuation": True, "opposite_return": True, "z": 1})
    both = expected_feature(*tests.fixture([85, 95, 115, 105, 100]))
    audit.check("両方向Z1が有効", [both["vectors"][side][-1] for side in ("1", "-1")], [1, 1])
    zero = expected_feature(*tests.fixture([110] * 5))
    audit.check("Z0と未知は別", (zero["ready"], zero["vectors"]["1"][-1]), (True, 0))
    reflected = expected_feature(*tests.reflect(slot, frames))
    audit.check("全18列鏡像", result["vectors"]["1"], reflected["vectors"]["-1"])
    audit.check("参照末公開後の終値で固定", result["history"]["band"]["fixed_at_key"] < result["history"]["band"]["first_reaction_key"], True)
    audit.check("参照と反応の番号重複なし", set(result["history"]["reference_indices"]) & set(result["history"]["reaction_indices"]), set())
    future = tests.OLD.source(25)
    future.update(publish=False, close=float("nan"), missing=9)
    audit.check("未来追加prefix不変", expected_feature(slot, frames + [future, deepcopy(future)]), result)
    for close, outside in ((115., 1), (math.nextafter(115., -math.inf), 0)):
        artificial = [tests.OLD.source(index) for index in range(20, 25)]
        for row in artificial:
            row["close"] = close
        audit.check("5pt等号とULP内側", reaction_state(artificial, 110., 1)["out_count"], outside)
    changed = deepcopy(slot)
    changed.update(side=-1, role="反転", ready=False, holding=True, outcome="250")
    audit.check("旧採否保有教師を使わない", expected_feature(changed, frames), result)

    # ----------------------------------------
    # 全pairの除外後に方向行をZへ分け、枝内pairを再要求しない。
    learner = load(Path(__file__).with_name("学習.py"), "局所帯監査_人工fit対象")
    learning = load(Path(__file__).with_name("学習の人工検査.py"), "局所帯監査_学習人工材料")
    artificial_rows = learning.training_rows(18)
    entries, blocks, prepared, baseline = [], {}, {}, {}
    for row in artificial_rows:
        if row["session"] not in blocks:
            entries.append({"session": row["session"]})
            blocks[row["session"]] = {"slots": []}
        if row["slot_id"] not in prepared:
            blocks[row["session"]]["slots"].append({key: row[key] for key in BINDING})
            prepared[row["slot_id"]] = {"ready": True, "reason": "", "vectors": {}, "control_vectors": {}}
        prepared[row["slot_id"]]["vectors"][str(row["side"])] = row["features"]
        prepared[row["slot_id"]]["control_vectors"][str(row["side"])] = row["features"][:17]
        baseline[row["slot_id"], row["side"]] = row
    pair_ids, fitted = {}, {}
    for policy in POLICIES:
        selected = policy_features(prepared, policy)
        used, training, preparation = training_rows(entries, blocks, selected, baseline, learning.EVALUATION, FEATURE_COUNTS[policy])
        ordered = [{**baseline[item["slot_id"], side], "features": selected[item["slot_id"]]["vectors"][str(side)]}
                   for entry in entries for item in blocks[entry["session"]]["slots"] for side in (1, -1)]
        pair_ids[policy] = training["row_ids_sha256"]
        audit.check("同じ400pairと0.5重み", (training["used_pairs"], training["direction_rows"], training["total_weight"]), (400, 800, 400.))
        audit.check("共通準備の分母", preparation["特徴準備枠"], 400)
        meta = learning.metadata(FEATURE_COUNTS[policy])
        model_id = "人工_" + policy
        model = learner.fit(ordered, meta, policy, model_id, learning.EVALUATION)
        fitted[policy] = model
        check_model(model, used, training, meta, policy, model_id, hashlib.sha256(Path(__file__).with_name("学習.py").read_bytes()).hexdigest(), audit)
        for row in used:
            leaf, path, _ = walk(model, row["features"])
            audit.check("全方向JSONwalk", (leaf, path), learner.walk(model, row["features"]))
        future_teacher = deepcopy(baseline)
        first = next(iter(baseline))
        future_teacher[first]["end_time"] = learning.EVALUATION
        audit.check("同秒未来教師拒否", rejects(training_rows, entries, blocks, selected, future_teacher, learning.EVALUATION, FEATURE_COUNTS[policy]), True)
        absent = deepcopy(baseline)
        del absent[first]
        audit.check("片側教師拒否", rejects(training_rows, entries, blocks, selected, absent, learning.EVALUATION, FEATURE_COUNTS[policy]), True)
        unknown_pair = deepcopy(baseline)
        unknown_pair[first]["outcome"] = "不足"
        remaining, excluded, _ = training_rows(entries, blocks, selected, unknown_pair, learning.EVALUATION, FEATURE_COUNTS[policy])
        audit.check("Z分割より先にpair除外", (len(remaining), excluded["used_pairs"], excluded["excluded_pair_count"]), (798, 399, 1))
    audit.check("B0F0教師ID同一", pair_ids["B0"], pair_ids["F0"])
    fixed = fitted["F0"]
    audit.check("片方向ずつの枝でも学習", [fixed["training"]["partition"][str(z)]["direction_rows"] for z in (0, 1)], [400, 400])
    audit.check("両枝で400枠ずつ", [fixed["training"]["partition"][str(z)]["pair_unique"] for z in (0, 1)], [400, 400])
    corrupt = deepcopy(fixed)
    corrupt["nodes"][0]["threshold"] = .4
    broken_audit = source.Audit()
    features = policy_features(prepared, "F0")
    used, training, _ = training_rows(entries, blocks, features, baseline, learning.EVALUATION, 18)
    check_model(corrupt, used, training, learning.metadata(18), "F0", "人工_F0", hashlib.sha256(Path(__file__).with_name("学習.py").read_bytes()).hexdigest(), broken_audit)
    audit.check("根閾値変更を拒否", broken_audit.bad > 0, True)

    # ----------------------------------------
    # 片方のZ枝を学習0件にし、未知と既知score0を混同しない。
    empty_prepared = deepcopy(prepared)
    for feature in empty_prepared.values():
        for values in feature["vectors"].values():
            values[17] = 0
    selected = policy_features(empty_prepared, "F0")
    used, training, _ = training_rows(entries, blocks, selected, baseline, learning.EVALUATION, 18)
    ordered = [{**baseline[item["slot_id"], side], "features": selected[item["slot_id"]]["vectors"][str(side)]}
               for entry in entries for item in blocks[entry["session"]]["slots"] for side in (1, -1)]
    empty_model = learner.fit(ordered, learning.metadata(18), "F0", "人工空枝_F0", learning.EVALUATION)
    check_model(empty_model, used, training, learning.metadata(18), "F0", "人工空枝_F0", hashlib.sha256(Path(__file__).with_name("学習.py").read_bytes()).hexdigest(), audit)
    values = deepcopy(next(iter(selected.values()))["vectors"])
    values["-1"][17] = 1
    predicted = predict(empty_model, values)
    audit.check("未知側で両方向WAIT", (predicted["side"], predicted["winner_side"], predicted["reason"]), (0, 0, "未学習枝WAIT"))
    audit.check("既知側rawscore保持・未知だけNone", (predicted["scores"]["1"] is not None, predicted["scores"]["-1"], predicted["eligibility"]["-1"]), (True, None, None))
    audit.check("未知枝の全予測属性", predicted, learner.predict(empty_model, values))
    corrupt = deepcopy(empty_model)
    corrupt["nodes"][corrupt["nodes"][0]["right"]]["score"] = 0.
    audit.check("未知score0補完を拒否", rejects(predict, corrupt, values), True)
    values["1"][17] = math.nextafter(0., 1.)
    audit.check("float32前のZ非二値拒否", rejects(predict, empty_model, values), True)
    hand, vectors = learning.hand_model(), learning.vectors()
    audit.check("既知最高側全属性", predict(hand, vectors), learner.predict(hand, vectors))
    audit.check("売買方向交換", predict(hand, {"1": vectors["-1"], "-1": vectors["1"]})["side"], -1)
    for score, side in ((1 / 3, 1), (math.nextafter(1 / 3, -math.inf), 0)):
        sample = learning.hand_model(high=score, low=.2)
        audit.check("score下限等号/直下", predict(sample, vectors)["side"], side)
    audit.check("同点WAIT", predict(learning.hand_model(high=.5, low=.5), vectors)["side"], 0)
    price_only, price_vectors = learning.hand_model(first=4), learning.vectors(first=4)
    for node in price_only["nodes"]:
        if node["feature"] == 1:
            node["feature"] = 5
        for step in node["path"]:
            if step["feature"] == 1:
                step.update(feature=5, feature_id="F06", method="P06", family="price")
    price_vectors["1"][5], price_vectors["-1"][5] = 1., -1.
    audit.check("同family二列では不足", predict(price_only, price_vectors)["side"], 0)
    for name, value in (("unique_slots", 59), ("days", 5), ("sessions", 9)):
        sample = deepcopy(hand)
        sample["nodes"][6][name] = value
        audit.check("最高側支持不足で下位側救済なし", (predict(sample, vectors)["side"], predict(sample, vectors)["winner_side"]), (0, 1))
    audit.check("17木へ18列拒否", rejects(walk, hand, vectors["1"] + [0]), True)
    audit.check("18木へ17列拒否", rejects(walk, fixed, vectors["1"]), True)
    audit.check("片側空拒否", rejects(predict, hand, {"1": [], "-1": vectors["-1"]}), True)
    converted = [1.] * 17
    converted[0] = 1e-46
    audit.check("float32等号左", walk(hand, converted)[1][0]["branch"], "left")
    converted[0] = struct.unpack(">f", b"\x00\x00\x00\x01")[0]
    audit.check("float32最小正右", walk(hand, converted)[1][0]["branch"], "right")
    manifests = [{"id": "B0_F40", "policy": "B0", "phase": "F40", "評価場": ["2026-10-20_Day", "2026-11-04_Day"]}]
    label = {"policy": "B0", "session": "2026-10-20_Day", "slot_id": "人工葉枠", "filled": True, "outcome": "250",
             "entry_time": 10., "entry_line": 1, "end_time": 20., "end_line": 2}
    bindings = {("B0", "人工葉枠"): ("B0_F40", 6)}
    accounts = [{"candidate": "B0", "session": "2026-10-20_Day", "caution": True,
                 "closed": [{"slot_id": "人工葉枠", "pnl5": -122.}]}]
    labels = {"B0": [label], "F0": []}
    leaves = leaf_statistics(manifests, {"B0_F40": hand}, bindings, labels, accounts, source)
    audit.check("4葉2期間の空群", len(leaves), 8)
    audit.check("葉別帰属", (sum(row["入口"]["候補"] for row in leaves), sum(row["実完結"] for row in leaves), sum(row["実観測純額5"] for row in leaves)), (1, 1, -122.))
    contexts = context_statistics({("B0", "人工葉枠"): 1}, labels, accounts, source)
    audit.check("局面別12行空群", len(contexts), 12)
    audit.check("局面別帰属", (sum(row["入口"]["候補"] for row in contexts), sum(row["実完結"] for row in contexts), sum(row["実観測純額5"] for row in contexts)), (1, 1, -122.))
    audit.check("局面品質は候補期間全体", [row["品質注意場"] for row in contexts if row["policy"] == "B0" and row["period"] == "条件選択"], [["2026-10-20_Day"]] * 2)
    boundary, cases = label_helper.self_test(source)
    audit.check("期限同秒初行補足", (boundary.bad, len(cases)), (0, 4))
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
            "人工fit数": 3, "人工学習器fit数": 4, "本物教師読取": False, "市場戦略再生": False}


def main() -> None:
    """人工又はroot市場実行後の一度の保存監査を選ぶ。

    引数: なし。CLIの--self-test/--run/--viewer-urlを読む。
    返り値: None。不一致は非零終了し、正式保存証明は上書きしない。
    """
    parser = argparse.ArgumentParser(description="53の局所帯・固定根合成木・保存運用を独立検査")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    result = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps({key: result[key] for key in ("全件一致", "人工成功", "照合項目数", "不一致数", "人工fit数", "人工学習器fit数") if key in result}, ensure_ascii=False))
    if result.get("全件一致", result.get("人工成功")) is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()


