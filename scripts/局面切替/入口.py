"""公開済み三尺度のEMAと同場RSIを用いてVWAP発動を選別する。"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def module(path: Path, name: str) -> Any:
    """変更しない既存処理を別名で読む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: Any はモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Q = module(ROOT/"scripts/VWAP復帰/入口.py", "局面切替の固定Q")
G = module(Path(__file__).with_name("局面.py"), "局面切替の固定15分分類")
POLICIES = G.POLICIES
RULES = {"傾き下限": 0.02, "収束間隔上限": 0.25, "収束傾き上限": 0.10,
         "必要収束尺度数": 2, "RSI履歴本数": 5, "RSI持続本数": 3, "RSI持続下限": 50,
         "急変現在下限": 70, "急変差下限": 12, "急変過去水準": 65, "急変過去本数上限": 1,
         "反転前RSI上限": 40, "反転現在RSI下限": 30, "反転現在RSI上限": 60}


def finite(*values: Any) -> bool:
    """欠測を補完せず有限値だけを認める。

    引数: values (Any) は候補値。
    返り値: bool は全て有限数値か。
    """
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def validate_config(config: dict) -> None:
    """複合条件・五戦略・三尺度の固定を検査する。

    引数: config (dict) は20条件。
    返り値: None。不一致は例外。
    """
    if config["時間足分"] != [1, 3, 5] or config["戦略"] != list(POLICIES):
        raise ValueError("固定三尺度・五戦略だけ")
    if config["局面条件"] != G.RULES or config["複合条件"] != RULES:
        raise ValueError("局面・複合閾値を変更しない")


def scale_feature(frame: dict | None) -> dict:
    """一尺度の公開出典とATR正規化特徴を作る。

    引数: frame (dict|None) は当時の最新公開足。
    返り値: dict は出典・準備・傾き・収束。
    """
    keys = ("index", "minutes", "end", "confirm", "confirm_line", "close", "ema10", "ema20", "ema20_previous", "atr")
    row = {k: frame.get(k) if frame else None for k in keys}
    ready = bool(frame is not None and frame["publish"] and finite(*(row[k] for k in ("ema10", "ema20", "ema20_previous", "atr"))) and row["atr"] > 0)
    slope = (row["ema20"]-row["ema20_previous"])/row["atr"] if ready else None
    gap = abs(row["ema10"]-row["ema20"])/row["atr"] if ready else None
    row.update(準備済=ready, 正規化傾き=slope, 正規化間隔=gap,
               収束=bool(ready and gap <= RULES["収束間隔上限"] and abs(slope) <= RULES["収束傾き上限"]))
    return row


# ----------------------------------------
# 局面は15分ごと一回だけ分類し、特徴は公開キーと足終了を両方制限する。

def contexts(lower: list[dict], higher15: list[dict], higher60: list[dict],
             regimes: list[dict], config: dict) -> tuple[dict, dict]:
    """各下位判断へ三尺度特徴と同場五本RSIを結合する。

    引数: lower/higher15/higher60/regimes (list[dict]) は価格足/局面、config (dict) は条件。
    返り値: tuple[dict,dict] は足番号別contextと件数。
    """
    validate_config(config)
    assigned = G.assign(lower, regimes)
    uppers = {15: [f for f in higher15 if f["publish"]], 60: [f for f in higher60 if f["publish"]]}
    pointers, current = {15: 0, 60: 0}, {15: None, 60: None}
    history, result, counts, previous = deque(maxlen=5), {}, Counter(), None
    for frame in lower:
        key = frame["confirm"], frame["confirm_line"]
        for size in (15, 60):
            rows = uppers[size]
            while pointers[size] < len(rows) and (rows[pointers[size]]["confirm"], rows[pointers[size]]["confirm_line"]) <= key and rows[pointers[size]]["end"] <= frame["end"]:
                current[size] = rows[pointers[size]]
                pointers[size] += 1
        if not frame["publish"] or frame["missing"] or previous is not None and frame["index"] != previous+1:
            history.clear()
        previous = frame["index"]
        if frame["publish"] and finite(frame.get("rsi")):
            history.append({"index": frame["index"], "confirm": frame["confirm"], "confirm_line": frame["confirm_line"], "rsi": frame["rsi"]})
        else:
            history.clear()
        base = assigned[frame["index"]]
        scales = {"入口": scale_feature(frame), "15分": scale_feature(current[15]), "60分": scale_feature(current[60])}
        reasons = list(base["局面準備不可理由"])
        reasons.extend(name+"EMA/ATR未準備" for name, feature in scales.items() if not feature["準備済"])
        if len(history) != 5:
            reasons.append("同場連続公開RSI五本未準備")
        row = {**base, "旧M準備": base["共通M準備"], "共通M準備": bool(base["共通M準備"] and not reasons),
               "M除外理由": reasons, "三尺度特徴": scales, "RSI五本": deepcopy(list(history)),
               "収束尺度数": sum(f["収束"] for f in scales.values())}
        result[frame["index"]] = row
        counts["足数"] += 1
        counts["共通M準備足数"] += row["共通M準備"]
    return result, dict(counts)


def decision(policy: str, family: str, side: int, context: dict) -> tuple[bool, dict]:
    """当時の特徴だけから一戦略の採否と全段階を返す。

    引数: policy/family (str) は戦略/Q系統、side (int) は買1売−1、context (dict) は公開特徴。
    返り値: tuple[bool,dict] は採否・理由/方向側RSI等。将来ラベルは参照しない。
    """
    accepted, base_reason = G.allowed(policy, family, side, context)
    rsi = [p["rsi"] if side == 1 else 100-p["rsi"] for p in context["RSI五本"]]
    ready = len(rsi) == 5 and context["共通M準備"]
    spike = bool(ready and rsi[-1] >= 70 and rsi[-1]-rsi[-2] >= 12 and sum(v >= 65 for v in rsi[:-1]) <= 1)
    trend_ema = bool(ready and all(side*f["正規化傾き"] >= 0.02 for f in context["三尺度特徴"].values())
                     and side*(context["三尺度特徴"]["入口"]["close"]-context["三尺度特徴"]["入口"]["ema20"]) > 0)
    sustained = bool(ready and all(v >= 50 for v in rsi[-3:]))
    convergence = bool(ready and context["収束尺度数"] >= 2)
    rebound = bool(ready and rsi[-2] <= 40 and 30 <= rsi[-1] <= 60 and rsi[-1] > rsi[-2])
    reasons = []
    if not accepted:
        reasons.append(base_reason)
    if policy in ("S1", "S2") and context["共通M準備"]:
        if spike:
            reasons.append("RSI急変警戒")
        if family == "Q1":
            if not trend_ema:
                reasons.append("三尺度EMA順行不一致")
            if not sustained:
                reasons.append("RSI三本持続不成立")
        elif family == "Q2":
            if not convergence:
                reasons.append("二尺度収束不成立")
            if not rebound:
                reasons.append("RSI戻り不成立")
    ok = accepted and not reasons
    return bool(ok), {"採用": bool(ok), "理由": reasons or [base_reason], "局面段階採用": bool(accepted),
                     "方向側RSI五本": rsi, "RSI急変警戒": spike, "三尺度EMA順行": trend_ema,
                     "RSI三本持続": sustained, "二尺度収束": convergence, "RSI戻り": rebound,
                     "同時競合": False}


def generate(frames: list[dict], higher15: list[dict], higher60: list[dict], session: str,
             cutoff: float, deadline: float, config: dict, references: dict,
             regimes: list[dict] | None = None) -> tuple[dict, dict]:
    """固定Qの全発動を残し、五戦略の採用集合を作る。

    引数: frames/higher15/higher60 (list[dict]) は三尺度、session (str) は場、cutoff/deadline (float) は時間、
    config/references (dict) は条件/固定18参照、regimes (list[dict]|None) は一回分類済み局面。
    返り値: tuple[dict,dict] は戦略別信号・全shadow/準備。競合はshadowに残し全件見送る。
    """
    validate_config(config)
    if not frames:
        raise ValueError("空足はdriver側で入口尺度を指定")
    size = frames[0]["minutes"]
    if regimes is None:
        regimes, _ = G.build(higher15, session, config)
    context_by_index, quality = contexts(frames, higher15, higher60, regimes, config)
    old_config = {**config, "入口系統": ["Q1", "Q2"], "補助": ["なし", "15分方向一致"]}
    generated, _ = Q.generate(frames, higher15, session, cutoff, deadline, old_config, references)
    original = sorted([r for family in ("Q1", "Q2") for r in generated[f"{size}分_{family}_なし"]], key=lambda r: (r["要求時計秒"], r["要求原板行"], r["イベントID"]))
    output = {f"{size}分_{p}": [] for p in POLICIES}
    shadow, selected = [], defaultdict(list)
    for signal in original:
        context = context_by_index[signal["index"]]
        verdicts = {p: decision(p, signal["入口系統"], signal["side"], context)[1] for p in POLICIES}
        snapshot = {**signal, **context, "戦略判定": verdicts}
        shadow.append(snapshot)
        for policy in POLICIES:
            if verdicts[policy]["採用"]:
                selected[(policy, signal["要求時計秒"], signal["要求原板行"])].append(snapshot)
    for (policy, _, _), rows in selected.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
            continue
        row = rows[0]
        source = f"{size}分_{policy}"
        output[source].append({**deepcopy(row), "元Q入口ID": row["入口ID"], "入口ID": source,
                               "戦略": policy, "複合判定": deepcopy(row["戦略判定"][policy]),
                               "イベントID": f"{row['QイベントID']}_{policy}"})
    return output, {"場": session, "時間足分": size, **quality, "全Q発動記録": shadow,
                    "複合context記録": [{"場": session, "時間足分": size, "index": index, **row} for index, row in context_by_index.items()],
                    "戦略別発動数": {key: len(value) for key, value in output.items()}}
