"""旧59全出力へ、登録前10差分・rへの進行・r後の進行を分けた八値を加える。"""

from copy import deepcopy
from fractions import Fraction
import importlib.util
import math
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("区間分離が固定参照する59特徴",
    Path(__file__).resolve().parents[1] / "価格経路の深さと速度/特徴.py")
F59 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F59)
F58 = F59.F58
SOURCE_FIELDS = F59.SOURCE_FIELDS
BASE_FEATURES = deepcopy(F59.FEATURES)
FEATURES = deepcopy(BASE_FEATURES)
for role, start in (("T", 39), ("R", 43)):
    for offset, name in enumerate(("登録へ至る十終値差分平均対ATR", "登録へ至る十差分の符号付き効率",
            "固定pからrへの一足当たり終値進行対ATR", "rから現在への一足当たり純進行対ATR")):
        FEATURES.append({"id": f"F{start + offset:02d}", "name": role + name,
            "method": "P05", "family": "price", "scale": "m03"})
CONTROL_FIELDS = (*F59.CONTROL_FIELDS, "control_vectors30", "geometry")
RULES = {"旧特徴": 38, "追加特徴": 8, "全特徴": 46, "旧価格機械": deepcopy(F59.RULES),
    "登録区間": "b-10..bの11終値/10差分。旧path.reference_indices/keysと完全隣接を照合",
    "登録平均": "実side*(Cb-C[b-10])/(10*現在ATR)",
    "登録効率": "同じ符号付きnet/隣接終値差の絶対値和。総変動0は0",
    "r区間": "Tはa=b、Rはa=f。r形成時[a,r-1]で実side*C最大の最初のpを固定",
    "r進行": "実side*(Cr-Cp)/(現在ATR*(r.index-p.index))。正値も許可",
    "r後進行": "r形成済みかつj>rなら実side*(Cj-Cr)/(現在ATR*(j.index-r.index))、j=rは既知0",
    "r未形成": "r進行/r後進行0。旧段階とsegments.masksで適用外を区別",
    "未ID": "四値0。registration_steps0、他の区間値/足数None、currentのみ保持",
    "取消後": "TTL/置換/resetまで旧IDの記述を継続。有効旗を復活させない",
    "未来": "pはrまでの情報で固定し後続峰へ更新しない。足内順/未来極値/実entryは不使用",
    "尺度": "平均はすべて現在判断ATR、足数尺度。瞬間速度又は実約定からの収益ではない",
    "旧出力": "全旧keys/geometry/paths/history不変。control_vectors38で旧vectorsを保持",
    "情報票": "追加は全price。既存の全期間平均・一足変化・k後進行との従属性を独立票としない"}


def control_projection(feature: dict) -> dict:
    """新項目を除き、固定59の返り値だけへ深い複写で射影する。

    引数: feature(dict)は新60特徴。
    返り値: dictは旧59全keys。vectorsをcontrol_vectors38へ置き換える。
    """
    result = {name: deepcopy(feature[name]) for name in CONTROL_FIELDS}
    result["vectors"] = deepcopy(feature["control_vectors38"])
    return result


def source_span(rows: dict[int, dict], start: int, end: int) -> list[dict]:
    """指定区間を短縮せず、公開済み完全隣接SOURCEだけで取り出す。

    引数: rows(dict[int,dict])は当時可視な銀行、start/end(int)は両端番号。
    返り値: list[dict]は区間の原出典。欠足/不正/非隣接は例外。
    """
    indices = list(range(start, end + 1))
    if not indices or any(index not in rows for index in indices):
        raise ValueError("区間の正本終値出典が不足")
    selected = [rows[index] for index in indices]
    if (any(not F58.I49.eligible_price(row) for row in selected)
            or any(not F58.I49.adjacent(p, c) for p, c in zip(selected, selected[1:]))):
        raise ValueError("区間の完全隣接又は価格が不正")
    return selected


def registration_statistics(closes: list, side: int, atr: float) -> tuple:
    """十一終値の十差分について、方向付き平均と効率を精密計算する。

    引数: closes(list[数値])はb-10..b、side(int)は実方向±1、atr(float)は現在正ATR。
    返り値: tuple[Fraction,Fraction,Fraction,Fraction]はnet/総変動/平均/効率。
    """
    if len(closes) != 11 or side not in (-1, 1) or not F58.I49.finite(atr) or atr <= 0:
        raise ValueError("登録前区間の本数/実方向/ATRが不正")
    values = [Fraction(value) for value in closes]
    net = side * (values[-1] - values[0])
    total = sum((abs(c - p) for p, c in zip(values, values[1:])), Fraction(0))
    return net, total, net / (10 * Fraction(atr)), net / total if total else Fraction(0)


def segments(path: dict, current: dict, rows: dict[int, dict], atr: float) -> dict:
    """登録区間とr前後を分離し、固定pと小型診断を作る。

    引数: path(dict)は旧58の保持経路、current(dict)は旧最新j、rows(dict[int,dict])は可視銀行、
        atr(float)は現在判断ATR。
    返り値: dictは追加四値/各区間足数/net/maskとindex/key参照。SOURCE全文は転記しない。
    """
    result = {"episode_id": path["episode_id"], "b": deepcopy(path["b"]),
        "a": None, "p": None, "r": deepcopy(path["r"]), "current": F58.source_ref(current),
        "registration_start": None, "registration_steps": 0, "registration_net": None,
        "registration_total_abs": None, "approach_steps": None, "approach_net": None,
        "since_r_steps": None, "since_r_net": None,
        "masks": {"registration": False, "approach": False, "since_r": False}, "values": [0, 0, 0, 0]}
    if path["episode_id"] is None:
        if path["b"] is not None or path["r"] is not None or path["stage"] != 0:
            raise ValueError("未IDの旧保持状態が不整合")
        return result
    if path["b"] is None or path["role"] not in ("T", "R") or path["side"] not in (-1, 1):
        raise ValueError("登録済み経路のb/種類/実方向が不正")
    b, side = path["b"], path["side"]
    registration = source_span(rows, b["index"] - 10, b["index"])
    if (path["reference_indices"] != list(range(b["index"] - 10, b["index"]))
            or path["reference_keys"] != [[row["confirm"], row["confirm_line"]] for row in registration[:-1]]
            or F58.source_ref(registration[-1]) != b):
        raise ValueError("登録十本と旧固定Kの参照出典が不一致")
    span = source_span(rows, b["index"], current["index"])
    if span[-1] != current:
        raise ValueError("区間分離の現在足と旧jが不一致")
    net, total, mean, efficiency = registration_statistics([row["close"] for row in registration], side, atr)
    result.update(registration_start=F58.source_ref(registration[0]), registration_steps=10,
        registration_net=float(net), registration_total_abs=float(total))
    result["masks"]["registration"] = True
    values = [mean, efficiency, Fraction(0), Fraction(0)]
    # ----------------------------------------
    # aはTのb又はRのf。rが未形成でも、既知のa出典だけは診断へ残す。
    a = b if path["role"] == "T" else path["f"]
    result["a"] = deepcopy(a)
    if path["r"] is not None:
        r = path["r"]
        if a is None or a["index"] < b["index"] or a["index"] >= r["index"]:
            raise ValueError("r形成に必要な別足aが不正又はRのfがない")
        if r["index"] > current["index"] or F58.source_ref(rows.get(r["index"])) != r:
            raise ValueError("rの出典又は時点が不一致")
        if F58.source_ref(rows.get(a["index"])) != a:
            raise ValueError("aの出典が不一致")
        before_r = source_span(rows, a["index"], r["index"] - 1)
        signed = [side * Fraction(row["close"]) for row in before_r]
        p = before_r[signed.index(max(signed))]
        approach_steps = r["index"] - p["index"]
        approach_net = side * (Fraction(rows[r["index"]]["close"]) - Fraction(p["close"]))
        since_steps = current["index"] - r["index"]
        since_net = side * (Fraction(current["close"]) - Fraction(rows[r["index"]]["close"]))
        values[2] = approach_net / (Fraction(atr) * approach_steps)
        values[3] = since_net / (Fraction(atr) * since_steps) if since_steps else Fraction(0)
        result.update(p=F58.source_ref(p), approach_steps=approach_steps, approach_net=float(approach_net),
            since_r_steps=since_steps, since_r_net=float(since_net))
        result["masks"].update(approach=True, since_r=True)
    additional = [float(value) for value in values]
    diagnostics = [result[name] for name in ("registration_net", "registration_total_abs", "approach_net", "since_r_net")
        if result[name] is not None]
    if not all(math.isfinite(value) for value in (*additional, *diagnostics)):
        raise ValueError("区間分離の表示値が非有限又は範囲外")
    result["values"] = additional
    return result


def extract(slot: dict, frames3: list[dict]) -> dict:
    """旧59辞書を不変保持し、T/R各四列の区間情報だけを加える。

    引数: slot(dict)は既存定時判断、frames3(list[dict])は旧正本SOURCE銀行。
    返り値: dictは旧59全項目とcontrol_vectors38/segments、vectors46。旧準備不足は両空。
        旧global/入力/出力、教師、費用、保有、採否を変更しない。
    """
    old = F59.extract(slot, frames3)
    result = deepcopy(old)
    result.update(control_vectors38=deepcopy(old["vectors"]),
        segments={"1": {"T": None, "R": None}, "-1": {"T": None, "R": None}})
    if not old["ready"]:
        return result
    rows = {row["index"]: row for row in F58.visible_sources(slot, frames3)}
    current = old["base"]["history"]["reaction_sources"][-1]
    for side in ("1", "-1"):
        additional = []
        for role in ("T", "R"):
            item = segments(old["paths"][side][role], current, rows, old["atr"])
            result["segments"][side][role] = item
            additional.extend(item["values"])
        result["vectors"][side] = deepcopy(old["vectors"][side]) + additional
    return result
