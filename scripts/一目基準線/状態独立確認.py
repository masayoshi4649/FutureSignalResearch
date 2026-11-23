"""00028の高安中点・現在雲・fastストキャス・入口を原OHLCから独立検算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00028_基準線復帰と上位一目の方向"
WORK = ROOT / "work/一目基準線/00028"
INPUT = STUDY / "入力台帳.json"
SOURCE_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing",
    "open", "high", "low", "close")


def helper(path: Path, name: str) -> Any:
    """固定済みの独立足構築・比較補助だけを読み込む。

    引数: path (Path) は補助ファイル、name (str) はモジュール識別名。
    返り値: Any は独立補助。28主指標・入口・運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


S = helper(ROOT / "scripts/収縮反転/状態独立確認.py", "一目基準線の独立OHLC")
V = helper(ROOT / "scripts/VWAP入力/独立確認.py", "一目基準線の独立比較")
P = helper(ROOT / "scripts/異種発動/状態独立確認.py", "一目基準線の固定独立Wilder")
LEGACY_FIELDS = ("atr", "stoch_raw", "stoch_k")
ICHI_NAMES = {"転換9": "ichimoku_tenkan", "基準26": "ichimoku_kijun", "先行A現在計算": "ichimoku_a",
    "先行B現在計算": "ichimoku_b", "現在雲A": "cloud_a", "現在雲B": "cloud_b",
    "現在雲上端": "cloud_upper", "現在雲下端": "cloud_lower"}
EXACT_FIELDS = ("Fast差厳密符号", "Fast差厳密分子", "Fast差厳密分母")
POLICIES = ("B0", "B1", "B2")


def midpoint(prefix: list[dict], width: int) -> float | None:
    """指定時点までの原高安窓を直接走査して中間値を求める。

    引数: prefix (list[dict]) は当時までの連続有効OHLC、width (int) は窓本数。
    返り値: float|None は最高値/最安値の中間値。本数不足を補完しない。
    """
    if len(prefix) < width:
        return None
    selected = prefix[-width:]
    return (max(row["high"] for row in selected) + min(row["low"] for row in selected)) / 2


def prefix_values(prefix: list[dict]) -> dict:
    """数値足26個前の履歴まで再走査し、現在位置の雲とrawK/Dを計算する。

    引数: prefix (list[dict]) は現在足を含む切断後の有効OHLC。
    返り値: dict は一目/fast数値。描画先の当時値を現在雲へ混ぜない。
    """
    conversion, baseline = midpoint(prefix, 9), midpoint(prefix, 26)
    a = (conversion + baseline) / 2 if conversion is not None and baseline is not None else None
    b = midpoint(prefix, 52)
    old = prefix[:-26] if len(prefix) > 26 else []
    old_conversion, old_baseline = midpoint(old, 9), midpoint(old, 26)
    cloud_a = (old_conversion + old_baseline) / 2 if old_conversion is not None and old_baseline is not None else None
    cloud_b = midpoint(old, 52)
    cloud_ready = cloud_a is not None and cloud_b is not None
    raw_values, exact_values = [], []
    for end in range(max(0, len(prefix) - 3), len(prefix)):
        span = prefix[max(0, end - 13):end + 1]
        high = max(row["high"] for row in span)
        low = min(row["low"] for row in span)
        raw_values.append(100 * (prefix[end]["close"] - low) / (high - low)
            if len(span) == 14 and high > low else None)
        exact_values.append(Fraction(100) * (Fraction(prefix[end]["close"]) - Fraction(low)) /
            (Fraction(high) - Fraction(low)) if len(span) == 14 and high > low else None)
    current_k = raw_values[-1] if raw_values else None
    fast_d = sum(raw_values) / 3 if len(raw_values) == 3 and all(value is not None for value in raw_values) else None
    exact_ready = len(exact_values) == 3 and all(value is not None for value in exact_values)
    difference = (3 * exact_values[-1] - sum(exact_values)) / 3 if exact_ready else None
    exact_direction = (int(difference > 0) - int(difference < 0)) if exact_ready else None
    return {"転換9": conversion, "基準26": baseline, "先行A現在計算": a, "先行B現在計算": b,
        "現在雲A": cloud_a, "現在雲B": cloud_b,
        "現在雲上端": max(cloud_a, cloud_b) if cloud_ready else None,
        "現在雲下端": min(cloud_a, cloud_b) if cloud_ready else None,
        "現在雲準備済": cloud_ready, "雲算出元": deepcopy(old[-1]) if old else None,
        "fastK14": current_k, "fastD3": fast_d, "Fast差厳密符号": exact_direction,
        "Fast差厳密分子": difference.numerator if exact_ready else None,
        "Fast差厳密分母": difference.denominator if exact_ready else None}


def valid_ohlc(frame: dict) -> bool:
    """原OHLCの有限・正値・足の包摂整合を確認する。

    引数: frame (dict) は原OHLCと出典。
    返り値: bool は補完なしで数値窓へ投入できるか。
    """
    values = [frame[key] for key in ("open", "high", "low", "close")]
    return all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0 for value in values) and (
        frame["high"] >= max(frame["open"], frame["close"]) and frame["low"] <= min(frame["open"], frame["close"]))


class RollingHistory:
    """主のdequeとは独立に、切断後の原足配列を保持して毎回窓を取り直す。"""

    def __init__(self) -> None:
        """数値carryと限月を未確定にする。

        引数: なし。
        返り値: None。
        """
        self.history, self.contract = [], None

    def build(self, frames: list[dict], session: str, contract: tuple, tail_missing: int = 0) -> list[dict]:
        """欠枠・不正・限月で切断し、NPを数値だけへ反映して全足値を返す。

        引数: frames (list[dict]) は独立原足、session (str) は当場、contract (tuple) は限月、
        tail_missing (int) は完全幅の末尾欠枠数。
        返り値: list[dict] は原足/数値/内部入力可/公開可。主schema投影は別関数で行う。
        """
        if self.contract is not None and self.contract != contract:
            self.history = []
        self.contract = contract
        output, previous_index = [], None
        for frame in frames:
            if frame["missing"] or frame["index"] != (0 if previous_index is None else previous_index + 1):
                self.history = []
            valid = valid_ohlc(frame)
            if valid:
                self.history.append({"場": session, **{key: frame[key] for key in SOURCE_FIELDS}})
                values = prefix_values(self.history)
            else:
                self.history = []
                values = prefix_values([])
            output.append({"原足": deepcopy(frame), "数値": values, "内部入力可": valid,
                "公開可": bool(valid and frame["publish"]), "数値連続本数": len(self.history)})
            previous_index = frame["index"]
        if tail_missing:
            self.history = []
        return output


# ----------------------------------------
# 正式投影は既存の独立Wilderを数値補助に限定し、一目/K/Dは原足窓の再走査で置き換える。

def source(frame: dict) -> dict:
    """保存出典の非有限OHLCだけを欠測へ正規化する。

    引数: frame (dict) は数値検査前の原足。
    返り値: dict はSOURCE_FIELDSのJSON安全な写し。不正値を計算へ投入しない。
    """
    return {key: None if key in ("open", "high", "low", "close") and isinstance(frame[key], float)
        and not math.isfinite(frame[key]) else frame[key] for key in SOURCE_FIELDS}


class NumericHistory:
    """固定28の保存形式へ別実装数値を投影する独立銀行。"""

    def __init__(self, minutes: int) -> None:
        """尺度と未確定限月を保持し、独立窓を空にする。

        引数: minutes (int) は3又は15。
        返り値: None。
        """
        if minutes not in (3, 15):
            raise ValueError("3分又は15分だけを独立検算します")
        self.minutes, self.contract = minutes, None
        self.clear()

    def clear(self) -> None:
        """切断後の履歴と既検証の独立Wilder系列を空にする。

        引数: なし。
        返り値: None。限月/尺度は保持する。
        """
        self.history, self.legacy = [], P.Indicators()

    def build(self, frames: list[dict], session: str, contract: tuple, tail_missing: int = 0) -> tuple[list[dict], dict]:
        """原足の切断を別判定し、全一目・Fastと品質を生成する。

        引数: frames (list[dict]) は独立完全幅足、session (str) は当場、contract (tuple) は限月、
        tail_missing (int) は末尾完全欠枠。
        返り値: tuple[list[dict],dict] は保存形式の数値足/場別品質。先着/損益は含まない。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.clear()
        self.contract = contract
        rows, prior_index, prior_key, clears = [], None, None, int(changed)
        for frame in frames:
            index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
            if frame["minutes"] != self.minutes or prior_index is not None and index <= prior_index:
                raise ValueError("独立入力の尺度/足番号順が不正")
            if frame["publish"] and (frame["confirm"] < frame["end"] or prior_key is not None and key < prior_key):
                raise ValueError("独立入力の公開時計/キー順が不正")
            reasons = ["限月変更"] if changed and prior_index is None else []
            if index != (0 if prior_index is None else prior_index + 1):
                reasons.append("足番号欠枠")
            if frame["missing"]:
                reasons.append("欠枠")
            valid = valid_ohlc(frame)
            if not valid:
                reasons.append("OHLC不正")
            if any(reason != "限月変更" for reason in reasons):
                self.clear()
                clears += 1
            if valid:
                self.history.append({"場": session, **source(frame)})
                values = prefix_values(self.history)
                legacy = self.legacy.add(frame)
                legacy = {name: legacy[name] for name in LEGACY_FIELDS}
                legacy["stoch_raw"], legacy["stoch_k"] = values["fastK14"], values["fastD3"]
            else:
                values, legacy = prefix_values([]), {name: None for name in LEGACY_FIELDS}
            ready = bool(valid and all(values[name] is not None for name in
                ("転換9", "基準26", "現在雲上端", "現在雲下端")))
            rows.append({"場": session, **source(frame), **legacy,
                **{name: values[key] for key, name in ICHI_NAMES.items()}, "雲計算元足": values["雲算出元"],
                **{key: values[key] for key in EXACT_FIELDS},
                "一目数値入力可": valid, "一目準備済": ready, "一目公開可": bool(ready and frame["publish"]),
                "一目窓本数": min(78, len(self.history)), "銀行解除理由": reasons})
            prior_index = index
            if frame["publish"]:
                prior_key = key
        if tail_missing:
            self.clear()
            clears += 1
        return rows, {"場": session, "時間足分": self.minutes, "入力足数": len(rows),
            "数値入力足数": sum(row["一目数値入力可"] for row in rows),
            "基準線準備足数": sum(row["ichimoku_kijun"] is not None for row in rows),
            "一目準備足数": sum(row["一目準備済"] for row in rows), "一目公開準備足数": sum(row["一目公開可"] for row in rows),
            "Fast準備足数": sum(row["stoch_raw"] is not None and row["stoch_k"] is not None for row in rows),
            "非公開数値更新数": sum(not row["publish"] and row["一目数値入力可"] for row in rows),
            "clear数": clears, "尾部完全欠枠": tail_missing, "場末窓本数": min(78, len(self.history))}


# ----------------------------------------
# 主の公開pointerや採否関数を用いず、同場の上位候補を毎足直接列挙する。

def finite(value: Any) -> bool:
    """真偽値を除いた有限数値か検査する。

    引数: value (Any) は任意の末端。
    返り値: bool は数値として利用可能か。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def reference(row: dict | None) -> dict | None:
    """当時参照した足の出典と使用数値だけを保存形式へ写す。

    引数: row (dict|None) は前足又は最新公開上位足。
    返り値: dict|None は参照値。保存後に書き換えない独立snapshot。
    """
    fields = ("場", *SOURCE_FIELDS, *LEGACY_FIELDS, *EXACT_FIELDS, *ICHI_NAMES.values(),
        "雲計算元足", "一目数値入力可", "一目準備済", "一目公開可")
    return deepcopy({key: row[key] for key in fields}) if row is not None else None


def decisions(context: dict, side: int) -> dict:
    """全案同じ数値/時間準備と厳密Fast符号に、雲と高安中心の方向を段階追加する。

    引数: context (dict) は当時参照、side (int) は買1/売−1。
    返り値: dict は全Bの採否と理由。独立した分岐から全案分を先に確定する。
    """
    common = list(context["M除外理由"])
    if not context["時間条件可"]:
        common.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        common.append("確認遅延30秒超")
    upper = context["上位参照"]
    fast = context["Fast差厳密符号"] == side
    cloud = bool(upper is not None and upper["一目公開可"] and (
        upper["close"] > upper["cloud_upper"] if side > 0 else upper["close"] < upper["cloud_lower"]))
    ordered = bool(upper is not None and finite(upper["ichimoku_tenkan"]) and finite(upper["ichimoku_kijun"]) and (
        upper["ichimoku_tenkan"] > upper["ichimoku_kijun"] if side > 0 else upper["ichimoku_tenkan"] < upper["ichimoku_kijun"]))
    output = {}
    for policy in POLICIES:
        reasons = common + ([] if fast else ["Fast実方向上下関係不成立"])
        if policy != "B0" and not cloud:
            reasons.append("上位現在雲外実方向不成立")
        if policy == "B2" and not ordered:
            reasons.append("上位転換基準実方向不成立")
        output[policy] = {"採用": not reasons, "理由": reasons or ["基準線価格復帰と複合条件採用"], "同時競合": False}
    return output


def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict, dict]:
    """前J固定の価格crossを別列挙し、準備や値で消さず全集合へ残す。

    引数: frames/higher (list[dict]) は独立3/15分数値、session (str) は場、
    cutoff/deadline (float) は新規停止/返済期限、config (dict) は固定28条件。
    返り値: tuple[dict,dict] は全B純採用とラベルなし全context/原発動/品質。
    """
    if any(row["場"] != session or row["minutes"] != size for size, rows in ((3, frames), (15, higher)) for row in rows):
        raise ValueError("異なる場/尺度の公開足を当場の参照へ混ぜません")
    contexts, raw, groups, counts, exclusions = [], [], defaultdict(list), Counter(), Counter()
    for position, current in enumerate(frames):
        prior = frames[position - 1] if position else None
        if not (prior and prior["publish"] and prior["一目数値入力可"] and current["publish"] and
                current["一目数値入力可"] and not current["missing"] and prior["index"] + 1 == current["index"]):
            prior = None
        candidates = [row for row in higher if row["publish"] and row["end"] <= current["end"] and
            (row["confirm"], row["confirm_line"]) <= (current["confirm"], current["confirm_line"])]
        upper = candidates[-1] if candidates else None
        price_ready = bool(prior and all(finite(value) for value in
            (prior["ichimoku_kijun"], prior["close"], current["close"])))
        reasons = []
        if not price_ready:
            reasons.append("同場隣接公開価格前基準線未準備")
        if not finite(current["atr"]) or current["atr"] <= 0:
            reasons.append("現在ATR正未準備")
        if not all(finite(current[key]) for key in ("stoch_raw", "stoch_k")) or current["Fast差厳密符号"] is None:
            reasons.append("現在FastK_D未準備")
        if upper is None or not upper["一目公開可"]:
            reasons.append("当場最新公開15分一目未準備")
        context = {**deepcopy(current), "時間足分": 3, "前3分参照": reference(prior), "上位参照": reference(upper),
            "価格準備": price_ready, "共通M準備": not reasons, "M除外理由": reasons,
            "時間条件可": current["confirm"] < cutoff and deadline - current["confirm"] >= config["残り時間下限分"] * 60,
            "確認遅延条件可": current["confirm"] - current["end"] <= config["確認遅延上限秒"]}
        contexts.append(context)
        exclusions.update(reasons)
        counts["足数"] += 1
        counts["共通M準備足数"] += int(not reasons)
        if not price_ready:
            continue
        level = prior["ichimoku_kijun"]
        sides = ([1] if prior["close"] <= level < current["close"] else []) + (
            [-1] if prior["close"] >= level > current["close"] else [])
        for side in sides:
            event = f"NK225_{session}_3分_基準線復帰_{current['index']:04d}_{side}"
            row = {**deepcopy(context), "入口系統": "T基準線復帰", "役割": "順行", "side": side,
                "方向": "買い" if side == 1 else "売り", "発動ID": event, "QイベントID": event, "イベントID": event,
                "入口ID": "3分_T基準線復帰", "要求時計秒": current["confirm"], "要求原板行": current["confirm_line"],
                "足終了時計秒": current["end"], "確認遅延秒": current["confirm"] - current["end"], "期限時計秒": deadline,
                "残り分_判断時": (deadline - current["confirm"]) / 60, "固定基準線": level,
                "先着評価対象": context["時間条件可"] and context["確認遅延条件可"], "戦略判定": decisions(context, side)}
            raw.append(row)
            for policy in POLICIES:
                if row["戦略判定"][policy]["採用"]:
                    groups[policy, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), same_key in groups.items():
        if len(same_key) > 1:
            for row in same_key:
                row["戦略判定"][policy] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    selected = {"3分_" + policy: [] for policy in POLICIES}
    for row in raw:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                selected["3分_" + policy].append({**deepcopy(row), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": row["発動ID"] + "_" + policy})
    return selected, {"場": session, "時間足分": 3, **dict(counts), "M除外理由別": dict(exclusions),
        "全Q発動記録": raw, "複合context記録": contexts, "原価格発動数": len(raw),
        "先着評価対象外数": sum(not row["先着評価対象"] for row in raw),
        "戦略別発動数": {key: len(rows) for key, rows in selected.items()},
        "戦略採否理由別": {policy: dict(Counter(reason for row in raw for reason in row["戦略判定"][policy]["理由"])) for policy in POLICIES}}


class BareBars:
    """既検証の半開OHLC構築へ、指標を計算しない受け口だけを渡す。"""

    def __init__(self) -> None:
        """足構築からの欠枠resetを何も保持せず受け取る。

        引数: なし。
        返り値: None。
        """

    def add(self, bar: dict) -> dict:
        """原足を副作用なく写す。

        引数: bar (dict) は独立半開OHLC。
        返り値: dict は指標を含まない足。
        """
        return deepcopy(bar)


def reconstruct(manifest: dict, config: dict) -> Any:
    """固定66cacheから数値をcarryし、場内前足と入口を毎場独立に作る。

    引数: manifest/config (dict) は固定入力/28条件。
    返り値: Any は場別iterator。正常気配による先着・運用は呼ばない。
    """
    banks = {size: NumericHistory(size) for size in (3, 15)}
    for entry in manifest["entries"]:
        session, contract = entry["session"], tuple(entry["in_session_contract_codes"])
        start, finish, cutoff, deadline = S.G.times(session)
        data, frames, qualities = S.observed(entry), {}, {}
        for size in (3, 15):
            formed = S.bars(data, session, size, BareBars())
            tail = max(0, int((finish - start) // (size * 60)) - 1 - (formed[-1]["index"] if formed else -1))
            frames[size], qualities[size] = banks[size].build(formed, session, contract, tail)
        signals, quality = generate(frames[3], frames[15], session, cutoff, deadline, config)
        phase = "学習" if session[:10] < config["分割"]["選択開始日"] else (
            "条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": phase, "価格足": frames, "指標品質": qualities, "入口品質": quality,
            "純入口": signals, "新規停止": cutoff, "期限": deadline}


# ----------------------------------------
# ATRだけ既定許容と追尾整数を別照合し、新一目/Fast/価格/key/採否は厳密比較する。

class Audit:
    """新使用列の厳密一致とATRの許容/整数判断を分けて記録する。"""

    def __init__(self) -> None:
        """比較数・差分・ATR表現差の集計を空にする。

        引数: なし。
        返り値: None。
        """
        self.count, self.mismatches, self.errors = 0, 0, []
        self.atr_count, self.atr_repr_diff, self.atr_max_abs, self.atr_tick_diff = 0, 0, 0.0, 0

    def leaf(self, name: str, actual: Any, expected: Any, equal: bool) -> None:
        """末端の比較を一項目として記録する。

        引数: name (str) は経路、actual/expected (Any) は保存/独立、equal (bool) は明示合否。
        返り値: None。先頭100差分は原値を保持する。
        """
        self.count += 1
        if not equal:
            self.mismatches += 1
            if len(self.errors) < 100:
                self.errors.append({"項目": name, "保存": sorted(actual) if isinstance(actual, set) else actual,
                    "独立": sorted(expected) if isinstance(expected, set) else expected})

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """構造と数値を再帰比較し、atr経路だけ絶対1e−10/相対0を許す。

        引数: name (str) は経路、actual/expected (Any) は保存/独立値。
        返り値: None。ATRの正有効性と5pt追尾幅は許容なしで別検査する。
        """
        if isinstance(actual, dict) and isinstance(expected, dict):
            self.check(name + ":キー", set(actual), set(expected))
            for key in sorted(actual.keys() & expected.keys()):
                self.check(name + ":" + str(key), actual[key], expected[key])
            return
        if isinstance(actual, list) and isinstance(expected, list):
            self.check(name + ":長さ", len(actual), len(expected))
            for index, (left, right) in enumerate(zip(actual, expected)):
                self.check(name + ":" + str(index), left, right)
            return
        if name.endswith(":atr"):
            self.atr_count += 1
            numeric = finite(actual) and finite(expected)
            equal = math.isclose(actual, expected, rel_tol=0, abs_tol=1e-10) if numeric else actual == expected
            self.leaf(name, actual, expected, equal)
            if numeric:
                self.atr_max_abs = max(self.atr_max_abs, abs(actual - expected))
                self.atr_repr_diff += int(actual != expected)
            left_positive, right_positive = finite(actual) and actual > 0, finite(expected) and expected > 0
            self.leaf(name + ":正有効", left_positive, right_positive, left_positive == right_positive)
            left_tick = max(5, math.ceil(actual / 5) * 5) if left_positive else None
            right_tick = max(5, math.ceil(expected / 5) * 5) if right_positive else None
            self.atr_tick_diff += int(left_tick != right_tick)
            self.leaf(name + ":追尾Dpt整数", left_tick, right_tick, left_tick == right_tick)
            return
        if isinstance(expected, bool):
            equal = isinstance(actual, bool) and actual == expected
        elif isinstance(expected, int):
            equal = isinstance(actual, int) and not isinstance(actual, bool) and actual == expected
        elif isinstance(expected, float):
            equal = finite(actual) and actual == expected
        else:
            equal = actual == expected
        self.leaf(name, actual, expected, equal)


def input_quality(entry: dict, block: dict) -> dict:
    """正常板数・公開足数・完全幅尾部欠枠を原cacheから独立集計する。

    引数: entry/block (dict) は固定台帳/独立場。
    返り値: dict は主と比較する入力品質。原板本文は開かない。
    """
    np = S.np
    start, finish, _, _ = S.G.times(entry["session"])
    with np.load(ROOT / "work/複合検証" / entry["cache_path"], allow_pickle=False) as archive:
        now, valid = archive["now"], archive["valid"]
    positions = np.flatnonzero(np.isfinite(now) & (start <= now) & (now <= finish))
    selected = now[positions]
    if len(selected):
        positions = positions[np.r_[True, selected[1:] >= np.maximum.accumulate(selected[:-1])]]
    return {"場": entry["session"], "正常板数": int(valid[positions].sum()),
        "確定足数": {str(size): sum(row["publish"] for row in rows) for size, rows in block["価格足"].items()},
        "尾部欠枠": {str(size): max(0, int((finish - start) // (size * 60)) - 1 - (rows[-1]["index"] if rows else -1))
            for size, rows in block["価格足"].items()}}


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict]:
    """主準備と固定入力のメタデータをcacheへ進む前に照合する。

    引数: study/work (Path) は正式/作業先、audit (Audit) は比較先。
    返り値: tuple[dict,dict,dict] は条件/66台帳/ラベルなし主準備。不一致なら入力を開かない。
    """
    config, manifest = V.read(study / "条件.json"), V.read(study / "入力台帳.json")
    previous = V.read(ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json")
    latest = V.read(ROOT / "study/00027_試行00026の新Night固定後確認/入力台帳.json")
    audit.check("既使用66入力正本", manifest["entries"], previous["entries"] + latest["entries"])
    audit.check("既使用66入力場数", len(manifest["entries"]), 66)
    audit.check("既使用入力場一意", len({entry["session"] for entry in manifest["entries"]}), 66)
    audit.check("共通原板root", manifest["source_root"], previous["source_root"])
    audit.check("事前三候補", config["戦略"], list(POLICIES))
    old_config = V.read(ROOT / "study/00026_反転のSAR確認時刻と順行持続/条件.json")
    for key in ("対象", "時間足分", "出口", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "運用",
            "必須追尾", "入口支持", "費用支持", "目標確認率", "間引き必要件数"):
        audit.check("固定26の尺度/保護/費用/支持:" + key, config[key], old_config[key])
    source = V.read(work / "準備点検.json")
    audit.check("主準備ラベルなし", source["ラベル計算"], False)
    audit.check("主準備損益なし", source["損益計算"], False)
    audit.check("主準備条件版", source["条件SHA256"], V.sha(study / "条件.json"))
    audit.check("主準備入力版", source["入力台帳SHA256"], V.sha(study / "入力台帳.json"))
    allowed = {"scripts/一目基準線/" + name for name in ("検証.py", "入口.py", "指標.py")}
    audit.check("主準備は3主コード", set(source["コードSHA256"]), allowed)
    if set(source["コードSHA256"]) == allowed:
        for path, digest in source["コードSHA256"].items():
            audit.check("主準備code現在:" + path, digest, V.sha(ROOT / path))
    audit.check("主準備66場順", [row["場"] for row in source["準備"]], [entry["session"] for entry in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("28主準備/条件/入力メタデータ不一致のためcache前停止")
    return config, manifest, source


def prepare(study: Path, work: Path) -> dict:
    """全66場のラベルなし数値・原価格・採否を独立再構成して主準備へ照合する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は主準備/数式/時点/原集合/採否の合否。先着と損益は計算しない。
    """
    audit = Audit()
    config, manifest, master = guarded_inputs(study, work, audit)
    totals, counts, stages = Counter(), [], []
    for saved, entry, block in zip(master["準備"], manifest["entries"], reconstruct(manifest, config), strict=True):
        session, phase = block["場"], block["期間"]
        expected = {"場": session, "期間": phase, "指標": {str(size): rows for size, rows in block["価格足"].items()},
            "入口品質": block["入口品質"], "指標品質": list(block["指標品質"].values()), "入力品質": input_quality(entry, block)}
        audit.check(session + ":全純数値と原発動", saved, expected)
        for policy in POLICIES:
            signals = block["純入口"]["3分_" + policy]
            counts.append({"場": session, "期間": phase, "入口ID": "3分_" + policy, "発動数": len(signals),
                "買い発動数": sum(row["side"] == 1 for row in signals), "売り発動数": sum(row["side"] == -1 for row in signals)})
            totals[policy] += len(signals)
        for index, size in enumerate((3, 15)):
            totals[str(size) + "分足"] += len(block["価格足"][size])
        raw = block["入口品質"]["全Q発動記録"]
        for row in raw:
            adopted = [row["戦略判定"][policy]["採用"] for policy in POLICIES]
            audit.check(row["発動ID"] + ":B2はB1/B0部分集合", not adopted[2] or adopted[1] and adopted[0], True)
            audit.check(row["発動ID"] + ":B1はB0部分集合", not adopted[1] or adopted[0], True)
        totals["原価格発動"] += len(raw)
        stages.append({"期間": phase, **{key: value for key, value in block["入口品質"].items()
            if key not in ("複合context記録", "全Q発動記録")}})
        print(json.dumps({"場": session, "独立準備": "全一目/精密Fast/前J原発動/全B採否", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全場三案件数", master["場別発動"], counts)
    by_period = []
    for policy in POLICIES:
        for phase in ("学習", "条件選択", "後続検査"):
            local = [row for row in counts if row["入口ID"] == "3分_" + policy and row["期間"] == phase]
            active = [row for row in local if row["発動数"]]
            by_period.append({"入口ID": "3分_" + policy, "期間": phase, "発動数": sum(row["発動数"] for row in local),
                "発動場数": len(active), "発動開始日数": len({row["場"][:10] for row in active}),
                "買い発動数": sum(row["買い発動数"] for row in local), "売り発動数": sum(row["売り発動数"] for row in local)})
    audit.check("全期間三案件数", master["期間別発動"], by_period)
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "ラベル計算": False, "損益計算": False, "入力場数": len(manifest["entries"]), "全66場既使用": True,
        "全数": dict(totals), "場別発動": counts, "期間別発動": by_period, "監視段階": stages,
        "ATR照合": {"全leaf数": audit.atr_count, "浮動表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0、正有効と追尾Dpt整数は厳密"},
        "コードSHA256": V.sha(Path(__file__)), "条件SHA256": V.sha(study / "条件.json"),
        "入力台帳SHA256": V.sha(study / "入力台帳.json"), "主準備SHA256": V.sha(work / "準備点検.json"),
        "主コードSHA256": master["コードSHA256"], "独立OHLC補助SHA256": V.sha(ROOT / "scripts/収縮反転/状態独立確認.py"),
        "独立Wilder補助SHA256": V.sha(ROOT / "scripts/異種発動/状態独立確認.py"),
        "検証範囲": "原cacheから半開原OHLCを再構成し、原高安prefix別走査で9/26/52と26shift雲・rawK14/FastD3、Fraction差分の厳密符号/既約分子分母を再計算。全指標/出典/当場公開/end-key asof/前J価格rawP/M/全B採否/同時競合/全期間件数を比較。28主指標・入口・運用をimportしない。",
        "限界": "ATRのみ固定済み独立Wilder補助の浮動許容。他の新使用数値/時計/価格/採否は厳密。原板本文を別readerで再抽出せず固定cacheを共通入力にする。先着・新規受入・運用・損益の証明ではない。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "入力場数", "ラベル計算", "損益計算")}, ensure_ascii=False))
    return proof


def compressed_rows(path: Path) -> tuple[list[dict], str]:
    """正式保存物の全行と展開本文指紋を読む。

    引数: path (Path) はJSONL gzip。
    返り値: tuple[list[dict],str] は全行とSHA256。正式完了通知後のrunだけが呼ぶ。
    """
    rows, digest = [], hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for line in stream:
            digest.update(line)
            if line.strip():
                rows.append(json.loads(line))
    return rows, digest.hexdigest()


LABEL_NUMBERS = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")


def compare_signal(audit: Audit, actual: dict, expected: dict, case: bool) -> None:
    """先着の数値計算と分けて、技術列と対象外の欠測を全件照合する。

    引数: audit (Audit) は照合先、actual/expected (dict) は保存/独立発動、case (bool) は採用入口か。
    返り値: None。通常先着の数値本体はroot財務監査へ分離して本文SHAにbindする。
    """
    name = expected["イベントID"]
    allowed = set(expected) | {"ラベル", "理由", *LABEL_NUMBERS} | ({"要求時計JST"} if case else set())
    audit.check(name + ":保存列集合", set(actual), allowed)
    audit.check(name + ":全技術採否", {key: actual.get(key) for key in expected}, expected)
    eligible = expected["先着評価対象"]
    if case:
        audit.check(name + ":caseは時間遅延対象内", eligible, True)
        audit.check(name + ":要求時計JST", actual.get("要求時計JST"),
            datetime.fromtimestamp(expected["要求時計秒"], timezone(timedelta(hours=9))).isoformat())
    if not eligible:
        audit.check(name + ":対象外ラベル", actual["ラベル"], "対象外")
        audit.check(name + ":対象外理由", actual["理由"],
            "要求時間条件外" if not expected["時間条件可"] else "足確定確認遅延30秒超")
        audit.check(name + ":通常先着9数値None", {key: actual[key] for key in LABEL_NUMBERS}, {key: None for key in LABEL_NUMBERS})
    else:
        audit.check(name + ":通常先着ラベル種別", actual["ラベル"] in
            ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定"), True)


def run(study: Path, work: Path) -> dict:
    """主正式完了後だけ全66場の数値・原発動・採否・保存物を検算する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は状態proof。先着数値/会計/追尾本体はそれぞれ別監査へ分ける。
    """
    if not (study / "結果.json").exists() or not (study / "固定.json").exists():
        raise ValueError("root固定と正式完了後だけ全状態監査を実行します")
    audit = Audit()
    config, manifest, master = guarded_inputs(study, work, audit)
    prepared = V.read(work / "独立準備点検.json")
    audit.check("独立準備成功", prepared["全件一致"], True)
    audit.check("独立準備code版", prepared["コードSHA256"], V.sha(Path(__file__)))
    audit.check("独立準備主SHA", prepared["主準備SHA256"], V.sha(work / "準備点検.json"))
    audit.check("独立準備条件", prepared["条件SHA256"], V.sha(study / "条件.json"))
    audit.check("独立準備入力", prepared["入力台帳SHA256"], V.sha(study / "入力台帳.json"))
    fixed, formal = V.read(study / "固定.json"), V.read(study / "結果.json")
    for path, digest in fixed["ファイルSHA256"].items():
        audit.check("正式固定現在:" + path, V.sha(ROOT / path), digest)
    audit.check("正式の三候補", [row["候補ID"] for row in formal["結果"]], ["3分_" + policy + "_X0" for policy in POLICIES])
    if audit.mismatches:
        raise ValueError("固定/独立準備の版不一致でcache前停止")
    names = ("全指標", "全複合context", "全複合shadow", "入口事例", "全運用詳細", "追尾")
    rows, hashes, by_session = {}, {}, {}
    artifacts = {Path(row["パス"]).name: row for row in V.read(study / "作業成果物.json")["ファイル"]}
    sessions = {entry["session"] for entry in manifest["entries"]}
    for name in names:
        rows[name], hashes[name] = compressed_rows(work / (name + ".jsonl.gz"))
        audit.check("正式成果物全文SHA:" + name, hashes[name], artifacts[name + ".jsonl.gz"]["展開内容SHA256"])
        grouped = defaultdict(list)
        for row in rows[name]:
            audit.check("保存場は固定66内:" + name, row["場"] in sessions, True)
            grouped[row["場"]].append(row)
        by_session[name] = grouped
    input_saved, entry_saved, numeric_saved = (V.read(study / name) for name in ("入力品質.json", "入口品質.json", "指標品質.json"))
    audit.check("入力品質66件", len(input_saved), 66)
    audit.check("入口品質66件", len(entry_saved), 66)
    audit.check("指標品質132件", len(numeric_saved), 132)
    input_saved = {row["場"]: row for row in input_saved}
    entry_saved = {row["場"]: row for row in entry_saved}
    numeric_saved = {(row["場"], row["時間足分"]): row for row in numeric_saved}
    stages, cases_expected, raw_expected = [], {}, {}
    for entry, block in zip(manifest["entries"], reconstruct(manifest, config), strict=True):
        session, phase = block["場"], block["期間"]
        expected_numeric = [{"期間": phase, **row} for local in block["価格足"].values() for row in local]
        audit.check(session + ":全指標/出典/厳密Fast", by_session["全指標"][session], expected_numeric)
        expected_context = [{"期間": phase, **row} for row in block["入口品質"]["複合context記録"]]
        audit.check(session + ":全公開参照/M/時点", by_session["全複合context"][session], expected_context)
        expected_raw = [{"期間": phase, **row} for row in block["入口品質"]["全Q発動記録"]]
        actual_raw = by_session["全複合shadow"][session]
        audit.check(session + ":原価格発動全件数", len(actual_raw), len(expected_raw))
        for actual, expected in zip(actual_raw, expected_raw):
            compare_signal(audit, actual, expected, False)
            raw_expected[expected["発動ID"]] = expected
        local_cases = [{"期間": phase, **row} for local in block["純入口"].values() for row in local]
        actual_cases = by_session["入口事例"][session]
        audit.check(session + ":純採用全B数", len(actual_cases), len(local_cases))
        for actual, expected in zip(actual_cases, local_cases):
            compare_signal(audit, actual, expected, True)
            cases_expected[expected["イベントID"]] = expected
        small = {key: value for key, value in block["入口品質"].items() if key not in ("全Q発動記録", "複合context記録")}
        stage = {"期間": phase, **small}
        stages.append(stage)
        audit.check(session + ":入口品質", entry_saved[session], stage)
        audit.check(session + ":入力品質", input_saved[session], {"期間": phase, **input_quality(entry, block)})
        for size, quality in block["指標品質"].items():
            audit.check(session + ":指標品質:" + str(size), numeric_saved[session, size], {"期間": phase, **quality})
        actual_details = by_session["全運用詳細"][session]
        audit.check(session + ":全三案運用の保存", {row["候補ID"] for row in actual_details}, {"3分_" + policy + "_X0" for policy in POLICIES})
        audit.check(session + ":運用一意3件", len(actual_details), 3)
        for detail in actual_details:
            audit.check(session + ":運用品質の期間", detail["品質"]["期間"], phase)
        print(json.dumps({"場": session, "独立確認": "全数値/精密Fast/前J原集合/全B採否", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全case原順集合", {row["イベントID"] for row in rows["入口事例"]}, set(cases_expected))
    audit.check("全原発動一意集合", {row["発動ID"] for row in rows["全複合shadow"]}, set(raw_expected))
    canonical_diffs = 0
    for row in rows["入口事例"]:
        canonical = raw_expected.get(row["発動ID"])
        if canonical is not None:
            same = row["戦略判定"] == canonical["戦略判定"]
            audit.check(row["イベントID"] + ":全B採否canonical", same, True)
            canonical_diffs += int(not same)
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "入力場数": 66, "期間場数": {phase: sum(row["期間"] == phase for row in stages) for phase in ("学習", "条件選択", "後続検査")},
        "全66場既使用": True, "表示属性注意": canonical_diffs != 0, "case内canonical判定不一致数": canonical_diffs,
        "保存指標数": len(rows["全指標"]), "保存context数": len(rows["全複合context"]), "保存shadow数": len(rows["全複合shadow"]),
        "保存発動候補数": len(rows["全複合shadow"]), "保存入口数": len(rows["入口事例"]),
        "保存運用詳細数": len(rows["全運用詳細"]), "保存追尾数": len(rows["追尾"]), "監視段階": stages,
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(rows[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()}, "発動候補展開SHA256": hashes["全複合shadow"],
        "ATR照合": {"全leaf数": audit.atr_count, "浮動表現差数": audit.atr_repr_diff, "最大絶対差": audit.atr_max_abs,
            "追尾整数差数": audit.atr_tick_diff, "許容": "abs1e-10/rel0、正有効と追尾Dpt整数は厳密"},
        "コードSHA256": V.sha(Path(__file__)), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "条件SHA256": V.sha(study / "条件.json"), "結果SHA256": V.sha(study / "結果.json"),
        "固定SHA256": V.sha(study / "固定.json"), "主準備SHA256": V.sha(work / "準備点検.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "独立OHLC補助SHA256": V.sha(ROOT / "scripts/収縮反転/状態独立確認.py"),
        "独立Wilder補助SHA256": V.sha(ROOT / "scripts/異種発動/状態独立確認.py"),
        "検証範囲": "全66原cacheを同限月carry/切断し半開OHLCから全一目/Fast/精密Fraction符号/既約分子分母を別計算。全保存指標・上位参照・原P・全B採否・競合snapshot・品質・先着の時間遅延対象外/9Noneを全件照合し、6gzip全行の展開SHAをbind。",
        "限界": "通常先着の数値・実新規受入・約定会計・一建玉・全追尾は別監査。原板本文の独立再抽出なし。ATRだけ既定許容、他の新使用値/価格/時計/採否は厳密。既使用66場を未見検証としない。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "入力場数", "保存shadow数", "保存入口数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """固定前の準備と正式完了後の状態を明示指定で分ける。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。不一致は非0終了。無指定で実入口先着/PnLを開かない。
    """
    parser = argparse.ArgumentParser(description="28一目基準線の独立準備")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        proof = prepare(args.study.resolve(), args.work.resolve())
    elif args.実行許可:
        proof = run(args.study.resolve(), args.work.resolve())
    else:
        parser.error("--prepare 又はroot正式完了通知後の --実行許可 が必要です")
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
