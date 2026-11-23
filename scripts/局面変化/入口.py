"""固定21の全発動を保持し、同場15分現前ペアで局面を改訂する。"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("局面変化の固定21発動", ROOT/"scripts/異種発動/入口.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
OLD_CONFIG = json.loads((ROOT/"study/00021_BBとMACDとストキャスの発動切替/条件.json").read_text(encoding="utf-8"))
POLICIES = ("A0", "S1", "S2")
FAMILIES, ROLES, RULES, finite = BASE.FAMILIES, BASE.ROLES, BASE.RULES, BASE.finite
PAIR_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing",
               "adx", "plus_di", "minus_di", "bb_mean", "bb_sd", "bandwidth")


def validate_config(config: dict) -> None:
    """三尺度・三規則・固定21発動を検査する。

    引数: config (dict) は22条件。
    返り値: None。不一致は例外。
    """
    if config["時間足分"] != [1, 3, 5] or config["戦略"] != list(POLICIES) or config["発動条件"] != RULES:
        raise ValueError("固定三尺度・三規則だけ")
    if config["局面改訂"] != {"上位分": 15, "ADX弱境界": 20, "ADX強境界": 25, "現前同場隣接公開": True}:
        raise ValueError("固定15分現前ペア・閾値だけ")


def point_ready(frame: dict) -> bool:
    """15分の現/前候補に必要な値だけを検査する。

    引数: frame (dict) は15分足。
    返り値: bool は公開/ADXDI有限/BB正幅の準備。
    """
    return bool(frame["publish"] and finite(*(frame.get(k) for k in ("adx", "plus_di", "minus_di", "bb_mean", "bb_sd", "bandwidth")))
                and min(frame["bb_mean"], frame["bb_sd"], frame["bandwidth"]) > 0)


def dx(frame: dict) -> tuple[float | None, bool]:
    """DI由来DXを診断用に計算し、ゼロ和規約を区別する。

    引数: frame (dict) は15分足。
    返り値: tuple[float|None,bool] はDXとゼロ和flag。欠測はNone。
    """
    plus, minus = frame.get("plus_di"), frame.get("minus_di")
    if not finite(plus, minus):
        return None, False
    total = plus+minus
    return (100*abs(plus-minus)/total, False) if total > 0 else (0.0, True)


def revised(adx: float, change: float, width_change: float, direction: int) -> tuple[str, int, str]:
    """単一S2の分岐と固定理由を返す。

    引数: adx/change/width_change (float) は現ADX/現前差/幅差、direction (int) はDI方向。
    返り値: tuple[str,int,str] は局面・方向・理由。DXを二重gateにしない。
    """
    if direction and change > 0 and (adx >= 25 or width_change > 0):
        return "トレンド", direction, "強ADX上昇継続" if adx >= 25 else "低ADX上昇・幅拡大"
    if adx <= 20 and change <= 0 and width_change <= 0:
        return "レンジ", 0, "低ADX非上昇・幅非拡大"
    return "待機", 0, "高ADX失速待機" if adx >= 25 and change <= 0 else "条件不一致待機"


def classify(higher: list[dict], session: str, config: dict) -> tuple[list[dict], dict]:
    """場内隣接公開ペアを作り、新旧局面を一回ずつ分類する。

    引数: higher (list[dict]) は15分足、session (str) は場、config (dict) は固定条件。
    返り値: tuple[list[dict],dict] は全分類と品質。場を跨ぐ前値や古い正常pairへ戻さない。
    """
    validate_config(config)
    old_rows, _ = BASE.classify(higher, session, OLD_CONFIG)
    records, counts, previous, previous_index = [], Counter(), None, None
    for frame, old in zip(higher, old_rows):
        reasons = []
        if previous_index is not None and frame["index"] != previous_index+1:
            reasons.append("15分番号飛越")
        if frame["missing"]:
            reasons.append("15分欠枠")
        if not frame["publish"]:
            reasons.append("非公開15分")
        if not point_ready(frame):
            reasons.append("15分単点未準備")
        if reasons:
            previous = None
        current = {k: frame.get(k) for k in PAIR_FIELDS}
        prior = deepcopy(previous)
        ready = bool(point_ready(frame) and prior is not None and prior["index"]+1 == frame["index"])
        if not ready and not reasons:
            reasons.append("同場隣接公開15分前値なし")
        current_dx, zero = dx(frame)
        prior_dx, prior_zero = dx(prior) if prior else (None, False)
        change = frame["adx"]-prior["adx"] if ready else None
        width_change = frame["bandwidth"]-prior["bandwidth"] if ready else None
        state, direction, reason = revised(frame["adx"], change, width_change, old["DI方向"]) if ready else ("未準備", 0, "未準備")
        row = {**old, "旧上位準備済": old["上位準備済"], "上位準備済": ready, "ペア準備済": ready,
               "ペア不可理由": reasons, "上位現足": current, "上位前足": prior,
               "S1局面": old["局面"], "S1方向": old["DI方向"] if old["局面"] == "トレンド" else 0,
               "S2局面": state, "S2方向": direction, "S2理由": reason,
               "ADX変化": change, "上位帯幅変化": width_change, "現DX": current_dx, "前DX": prior_dx,
               "DI和ゼロ": zero, "前DI和ゼロ": prior_zero,
               "DX差": current_dx-prior_dx if ready else None,
               "DX_ADX差": current_dx-frame["adx"] if ready else None,
               "平滑恒等残差": current_dx-frame["adx"]-13*change if ready else None}
        records.append(row)
        counts["15分足数"] += 1
        counts["ペア準備足数"] += ready
        counts["S2_"+state] += 1
        previous = current if point_ready(frame) else None
        previous_index = frame["index"]
    return records, dict(counts)


def assign(frames: list[dict], states: list[dict]) -> dict[int, dict]:
    """最新公開curのpair可否を下位へ渡す。

    引数: frames/states (list[dict]) は下位足/15分分類。
    返り値: dict[int,dict] は上位出典と新準備。最新cur不可で古正常へfallbackしない。
    """
    published = [s for s in states if s["publish"]]
    result, current, pointer = {}, None, 0
    fields = ("旧上位準備済", "ペア準備済", "ペア不可理由", "上位現足", "上位前足", "局面", "DI方向",
              "ADX14", "+DI14", "-DI14", "S1局面", "S1方向", "S2局面", "S2方向", "S2理由",
              "ADX変化", "上位帯幅変化", "現DX", "前DX", "DI和ゼロ", "前DI和ゼロ", "DX差", "DX_ADX差", "平滑恒等残差")
    for frame in frames:
        while pointer < len(published) and (published[pointer]["confirm"], published[pointer]["confirm_line"]) <= (frame["confirm"], frame["confirm_line"]) and published[pointer]["end"] <= frame["end"]:
            current = published[pointer]
            pointer += 1
        result[frame["index"]] = {"上位準備済": bool(current and current["ペア準備済"]),
            "局面参照ID": current["局面ID"] if current else None,
            "局面公開秒": current["confirm"] if current else None,
            "局面公開原行": current["confirm_line"] if current else None,
            "局面足終了秒": current["end"] if current else None,
            **{k: deepcopy(current[k]) if current else ["15分参照なし"] if k == "ペア不可理由"
               else "未準備" if k in ("局面", "S1局面", "S2局面", "S2理由") else False if k in ("旧上位準備済", "ペア準備済", "DI和ゼロ", "前DI和ゼロ")
               else 0 if k.endswith("方向") else None for k in fields}}
    return result


def decision(policy: str, family: str, side: int, context: dict) -> tuple[bool, str]:
    """同じ新Mから旧S1・改訂S2・混合を選ぶ。

    引数: policy/family (str) は戦略/発動、side (int) は買1売−1、context (dict) は当時値。
    返り値: tuple[bool,str] は採否と理由。
    """
    if policy not in POLICIES or family not in FAMILIES or side not in (1, -1):
        raise ValueError("戦略/発動/方向が不正")
    if not context["共通M準備"]:
        return False, "共通M22未準備"
    if policy == "A0":
        return True, "常時混合"
    state, direction = context[policy+"局面"], context[policy+"方向"]
    if state == "トレンド":
        ok = family == "T1" and side == direction
        return ok, "トレンド同DI方向の継続" if ok else "トレンドで対象外発動"
    if state == "レンジ":
        return family == "R1", "レンジの反転" if family == "R1" else "レンジで継続見送り"
    return False, "転換待機"


# ----------------------------------------
# 旧発動を新pairで作り直さず保持し、全競合確定後にだけcaseを複写する。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float, deadline: float,
             config: dict, states: list[dict] | None = None) -> tuple[dict, dict]:
    """旧全発動shadowと新M22後の三入口を作る。

    引数: frames/higher (list[dict]) は下位/15分、session (str) は場、cutoff/deadline (float) は時計、
    config (dict) は条件、states (list[dict]|None) は新分類済上位。
    返り値: tuple[dict,dict] は三集合/全旧発動/全context。将来ラベルは参照しない。
    """
    validate_config(config)
    _, old_quality = BASE.generate(frames, higher, session, cutoff, deadline, OLD_CONFIG)
    if states is None:
        states, _ = classify(higher, session, config)
    assigned = assign(frames, states)
    contexts, by_index, counts = [], {}, Counter()
    for old in old_quality["複合context記録"]:
        context = assigned[old["index"]]
        reasons = list(old["M除外理由"])
        if not context["ペア準備済"]:
            reasons.append("同場隣接公開15分ペア未準備")
        ready = bool(old["共通M準備"] and context["ペア準備済"])
        row = {**old, **context, "旧M21準備": old["共通M準備"], "旧M21除外理由": old["M除外理由"],
               "共通M準備": ready, "共通M22準備": ready, "M除外理由": reasons}
        contexts.append(row)
        by_index[row["index"]] = row
        counts["足数"] += 1
        counts["旧M21準備足数"] += old["共通M準備"]
        counts["共通M準備足数"] += ready
    records, selected = [], defaultdict(list)
    size = frames[0]["minutes"]
    output = {f"{size}分_{p}": [] for p in POLICIES}
    for original in old_quality["全Q発動記録"]:
        context = by_index[original["index"]]
        verdicts = {p: {"採用": decision(p, original["入口系統"], original["side"], context)[0],
                        "理由": [decision(p, original["入口系統"], original["side"], context)[1]], "同時競合": False} for p in POLICIES}
        row = {**deepcopy(original), **{k: deepcopy(v) for k, v in context.items() if k not in original or k in ("上位準備済", "共通M準備", "M除外理由")},
               "旧21戦略判定": deepcopy(original["戦略判定"]), "戦略判定": verdicts}
        records.append(row)
        for p in POLICIES:
            if verdicts[p]["採用"]:
                selected[p, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), rows in selected.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
    for (policy, _, _), rows in selected.items():
        if len(rows) != 1:
            continue
        row = rows[0]
        source = f"{size}分_{policy}"
        output[source].append({**deepcopy(row), "入口ID": source, "戦略": policy,
            "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": f"{row['発動ID']}_{policy}"})
    return output, {"場": session, "時間足分": size, **dict(counts), "全Q発動記録": records,
                   "複合context記録": contexts, "旧M21発動数": len(records),
                   "新M22発動数": sum(r["共通M22準備"] for r in records),
                   "戦略別発動数": {k: len(v) for k, v in output.items()}}
