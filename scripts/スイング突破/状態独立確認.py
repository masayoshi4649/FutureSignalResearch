"""00045の原8列・確定山谷・独立DMI/Fastと全新先着を検算する。"""

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
STUDY = ROOT / "study/00045_確定スイング突破と方向優勢"
WORK = ROOT / "work/スイング突破/00045"
INDICATOR_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
INDICATOR_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("C0", "C1", "C2")
OPERATIONS = tuple("3分_" + value + "_XF" for value in POLICIES)


def helper(path: Path, name: str) -> Any:
    """固定独立足・ATR・先着の補助だけをCLI起動せず読む。

    引数: path(Path)は固定補助、name(str)は識別。
    返り値: Anyは補助。45主の指標・入口・運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


OLD = helper(ROOT / "scripts/回帰突破/状態独立確認.py", "スイング突破の固定独立足と先着")
G, N, S, V = OLD.G, OLD.N, OLD.S, OLD.V
Y = OLD.Y
SIGNAL_FIELDS, LABEL_FIELDS, SOURCE_FIELDS = OLD.SIGNAL_FIELDS, OLD.LABEL_FIELDS, OLD.SOURCE_FIELDS
finite, exact = OLD.finite, OLD.exact
canonical_sha, decision_signal = OLD.canonical_sha, OLD.decision_signal
normal_columns, label_direct = OLD.normal_columns, OLD.label_direct
saved_rows = Y.saved_rows
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr")
DMI_FIELDS = ("plus_di", "minus_di", "DMI数値入力可", "DMI差分数", "DMI準備", "DMI解除理由")
FAST_FIELDS = ("FastK", "FastD", "Fast差", "Fast差厳密符号", "Fast準備",
               "Fast価格窓足番号", "FastK窓足番号", "Fast解除理由")
NUMERIC_FIELDS = (*FRAME_FIELDS, *DMI_FIELDS, *FAST_FIELDS)
METADATA_FIELDS = ("元価格side", "判別種別", "突破極値ID", "構造方向", "元極値中心番号")


class Audit(N.Audit):
    """ATRとDI値の限定許容、全準備/優勢/採否の厳密比較を分ける。"""

    def __init__(self) -> None:
        """比較数とDI表現差統計を空にする。

        引数: なし。
        返り値: None。
        """
        super().__init__()
        self.di_stats, self.di_sign_diffs = {}, 0

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """DI末端だけabs1e-10/rel0で比較し、DI差符号は別に厳密照合する。

        引数: name(str)は経路、actual/expected(Any)は定義値/独立値。
        返り値: None。ATRは固定独立比較器の正有効/D整数検査を継承する。
        """
        field = name.rsplit(":", 1)[-1]
        if field in ("plus_di", "minus_di", "DI差") and finite(actual) and finite(expected):
            stat = self.di_stats.setdefault(field, {"比較leaf数": 0, "表現差leaf数": 0, "最大絶対差": 0.0})
            stat["比較leaf数"] += 1
            stat["表現差leaf数"] += int(actual != expected)
            stat["最大絶対差"] = max(stat["最大絶対差"], abs(actual - expected))
            self.leaf(name, actual, expected, math.isclose(actual, expected, abs_tol=1e-10, rel_tol=0))
            if field == "DI差":
                left, right = (actual > 0) - (actual < 0), (expected > 0) - (expected < 0)
                self.di_sign_diffs += int(left != right)
                self.leaf(name + ":厳密優勢符号", left, right, left == right)
            return
        super().check(name, actual, expected)


def judgment_projection(value: Any) -> Any:
    """数値の許容対象だけを判断へ射影し、全残余属性を厳密に保持する。

    引数: value(Any)は全数値/全P/純信号。
    返り値: AnyはATR正/D整数・DI全有限/優勢を含むJSON。
    """
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if key == "atr":
                positive = finite(item) and item > 0
                output["ATR判断"] = {"正有効": positive, "D整数": max(5, math.ceil(item / 5) * 5) if positive else None}
            elif key in ("plus_di", "minus_di"):
                output[key] = {"有限": True} if finite(item) else deepcopy(item)
            elif key == "DI差":
                output[key] = {"有限": True, "符号": (item > 0) - (item < 0)} if finite(item) else deepcopy(item)
            else:
                output[key] = judgment_projection(item)
        if "plus_di" in value and "minus_di" in value:
            ready = finite(value["plus_di"]) and finite(value["minus_di"])
            output["DI判断"] = {"準備": ready,
                "優勢符号": (value["plus_di"] > value["minus_di"]) - (value["plus_di"] < value["minus_di"]) if ready else None}
        return output
    if isinstance(value, list):
        return [judgment_projection(item) for item in value]
    return deepcopy(value)


def compare_numeric_scope(name: str, defined: Any, independent: Any, audit: Audit) -> bool:
    """全数値の限定許容と全非数値/準備/優勢/採否の厳密一致を併せて要求する。

    引数: name(str)は範囲、defined/independent(Any)は定義/生値、audit(Audit)は比較先。
    返り値: boolは判断射影の厳密一致。数値許容超過もauditへ別記録する。
    """
    audit.check(name + ":全数値", defined, independent)
    same = canonical_sha(judgment_projection(defined)) == canonical_sha(judgment_projection(independent))
    audit.check(name + ":準備優勢採否/全非許容値厳密", same, True)
    return same


def frame_projection(row: dict | None) -> dict | None:
    """3分SOURCEとATRだけを深複写する。

    引数: row(dict|None)は共有又は独立足。
    返り値: dict|Noneは14列。未使用MACD/数量を持ち込まない。
    """
    return None if row is None else {name: deepcopy(row[name]) for name in FRAME_FIELDS}


def numeric_projection(row: dict) -> dict:
    """独立数値28列だけを深複写する。

    引数: row(dict)は使用数値足。
    返り値: dictは出典/ATR/DI/Fast。
    """
    return {name: deepcopy(row[name]) for name in NUMERIC_FIELDS}


def price_valid(row: dict) -> bool:
    """公開状態とは分けて完全3分OHLCの数値投入可否を確認する。

    引数: row(dict)は原足。
    返り値: boolは完全180秒・3分・有効OHLC。
    """
    return bool(row["minutes"] == 3 and row["end"] - row["start"] == 180 and N.valid_ohlc(row))


# ----------------------------------------
# ATRとDMIの種を分ける。DMIは初有効足の次から14変化を数える。

class DirectionalState:
    """差分列の独立Wilder平均でDMIを計算する。"""

    def __init__(self) -> None:
        """前OHLCと14変化の種を解除する。

        引数: なし。
        返り値: None。
        """
        self.previous = None
        self.seeds = {"up": [], "down": [], "tr": []}
        self.means = None
        self.count = 0

    def add(self, frame: dict) -> dict:
        """元高安・前終値からDM/TRを作り、増分形の平均更新を行う。

        引数: frame(dict)は有効OHLC。
        返り値: dictはplus_di/minus_diと差分数。TR0では未定義のまま銀行を保つ。
        """
        if not N.valid_ohlc(frame):
            raise ValueError("有効OHLCだけをDMIへ投入する")
        plus = minus = None
        if self.previous is not None:
            prior = self.previous
            increase, decrease = frame["high"] - prior["high"], prior["low"] - frame["low"]
            values = {"up": increase if increase > 0 and increase > decrease else 0.0,
                      "down": decrease if decrease > 0 and decrease > increase else 0.0,
                      "tr": max(frame["high"] - frame["low"], abs(frame["high"] - prior["close"]),
                                abs(frame["low"] - prior["close"]))}
            self.count += 1
            if self.means is None:
                for key, value in values.items():
                    self.seeds[key].append(value)
                if self.count == 14:
                    self.means = {key: sum(values) / 14 for key, values in self.seeds.items()}
            else:
                for key, value in values.items():
                    self.means[key] += (value - self.means[key]) / 14
            if self.means is not None and self.means["tr"] > 0:
                plus = self.means["up"] / self.means["tr"] * 100
                minus = self.means["down"] / self.means["tr"] * 100
        self.previous = {key: frame[key] for key in ("high", "low", "close")}
        return {"plus_di": plus, "minus_di": minus, "差分数": self.count}


class ATRState:
    """既固定の独立Wilderを用い、前終値種の後のATR14を別計算する。"""

    def __init__(self) -> None:
        """前終値とATR平均を解除する。

        引数: なし。
        返り値: None。
        """
        self.previous = None
        self.average = S.G.Wilder()

    def add(self, frame: dict) -> float | None:
        """初足は前終値種とし、後続で前終値を含むTRを投入する。

        引数: frame(dict)は有効OHLC。
        返り値: float|Noneは独立ATR。
        """
        if not N.valid_ohlc(frame):
            raise ValueError("有効OHLCだけをATRへ投入する")
        value = None
        if self.previous is not None:
            value = self.average.add(max(frame["high"] - frame["low"],
                abs(frame["high"] - self.previous), abs(frame["low"] - self.previous)))
        self.previous = frame["close"]
        return value


def fast_value(prices: list[dict], values: list[tuple[int, Fraction]]) -> dict:
    """元14本高安のFraction位置と直近有効3Kの差を計算する。

    引数: prices(list[dict])は局所公開価格履歴、values(list[tuple])は直前までの有効K履歴。
    返り値: dictはrawK/FastD/差の精密値と、更新後のK履歴。幅0はK履歴だけ解除する。
    """
    window = prices[-14:]
    raw = average = difference = None
    updated = list(values) if len(window) == 14 else []
    if len(window) == 14:
        high, low = max(row["high"] for row in window), min(row["low"] for row in window)
        if high > low:
            raw = 100 * (Fraction(window[-1]["close"]) - Fraction(low)) / (Fraction(high) - Fraction(low))
            updated = [*updated, (window[-1]["index"], raw)][-3:]
            if len(updated) == 3:
                average = sum(value for _, value in updated) / 3
                difference = raw - average
        else:
            updated = []
    return {"K": raw, "D": average, "差": difference, "K履歴": updated,
            "価格窓足番号": [row["index"] for row in window]}


class NumericHistory:
    """元OHLCから独立ATR/DIと場内slice Fastを別計算する。"""

    def __init__(self) -> None:
        """未契約の空DI/ATR銀行を作る。

        引数: なし。
        返り値: None。Fastはbuildごとに作り直す。
        """
        self.contract = None
        self.clear()

    def clear(self) -> None:
        """価格数値のDI/ATRを同時に解除する。

        引数: なし。
        返り値: None。契約識別は保持する。
        """
        self.dmi, self.atr = DirectionalState(), ATRState()

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """完全NPも価格数値へ投入し、公開Fastは同場の連続履歴から再計算する。

        引数: frames(list[dict])は原3分OHLC、session(str)は場、contract(tuple)は限月、
        tail_missing(int)は完全尾部欠枠。
        返り値: tuple[list[dict],dict]は独立生28列とDI/Fast品質。入力atrを転記せず別計算する。
        """
        changed = self.contract is not None and self.contract != tuple(contract)
        self.contract = tuple(contract)
        if changed:
            self.clear()
        prices, ks, rows, previous, public_key = [], [], [], None, None
        counts = Counter({"DMIclear数": int(changed), "Fastclear数": 0})
        for raw in frames:
            if raw.get("場", session) != session or raw["minutes"] != 3:
                raise ValueError("当場3分足だけ")
            key = raw["confirm"], raw["confirm_line"]
            if previous is not None and raw["index"] <= previous["index"]:
                raise ValueError("足番号重複又は後退")
            if raw["publish"] and (raw["confirm"] < raw["end"] or public_key is not None and key <= public_key):
                raise ValueError("公開key重複/後退又は終了前公開")
            reasons = ["限月変更"] if changed and previous is None else []
            if raw["index"] != (0 if previous is None else previous["index"] + 1) or previous is not None and raw["start"] != previous["end"]:
                reasons.append("番号又は終了非連続")
            if raw["missing"]:
                reasons.append("欠枠")
            valid = price_valid(raw)
            if not valid:
                reasons.append("完全3分価格不正")
            if any(reason != "限月変更" for reason in reasons):
                self.clear()
                counts["DMIclear数"] += 1
            di = self.dmi.add(raw) if valid else {"plus_di": None, "minus_di": None, "差分数": self.dmi.count}
            row = {"場": session, **N.source(raw), "atr": self.atr.add(raw) if valid else None}
            fast_reasons = [reason for reason in reasons if reason != "限月変更"]
            if not raw["publish"]:
                fast_reasons.append("非公開")
            if fast_reasons:
                prices, ks = [], []
                counts["Fastclear数"] += 1
            values = {"K": None, "D": None, "差": None}
            if valid and raw["publish"] and not raw["missing"]:
                prices.append(row)
                values = fast_value(prices, ks)
                ks = values["K履歴"]
            difference = values["差"]
            rows.append({**row, "plus_di": di["plus_di"], "minus_di": di["minus_di"],
                "DMI数値入力可": valid, "DMI差分数": di["差分数"],
                "DMI準備": finite(di["plus_di"]) and finite(di["minus_di"]), "DMI解除理由": reasons,
                "FastK": exact(values["K"]), "FastD": exact(values["D"]), "Fast差": exact(difference),
                "Fast差厳密符号": (difference > 0) - (difference < 0) if difference is not None else None,
                "Fast準備": difference is not None, "Fast価格窓足番号": [f["index"] for f in prices[-14:]],
                "FastK窓足番号": [i for i, _ in ks], "Fast解除理由": fast_reasons})
            previous = raw
            if raw["publish"]:
                public_key = key
        if tail_missing:
            self.clear()
            counts["DMIclear数"] += 1
        return rows, {"場": session, "時間足分": 3, "入力足数": len(rows), **dict(counts),
            "DMI準備足数": sum(row["DMI準備"] for row in rows), "Fast準備足数": sum(row["Fast準備"] for row in rows),
            "非公開DMI更新数": sum(not row["publish"] and row["DMI数値入力可"] for row in rows),
            "尾部完全欠枠": tail_missing}


# ----------------------------------------
# 主の逐次dequeと分け、中心候補を五足区間から検査し確認足でだけ公開する。

def pivot(five: list[dict], side: int, session: str) -> dict:
    """中心・右2確認足を別出典として一回の極値記録を作る。

    引数: five(list[dict])は公開連続5足、side(int)は高1/低-1、session(str)は場。
    返り値: dictは一意の極値と二つのSOURCE。
    """
    center, right = five[2], five[4]
    kind = "高値" if side == 1 else "安値"
    return {"場": session, "極値ID": f"NK225_{session}_3分_確定{kind}_{center['index']:04d}",
        "極値種別": kind, "極値side": side, "極値価格": center["high" if side == 1 else "low"],
        "中心番号": center["index"], "確認足番号": right["index"],
        "中心出典": {name: deepcopy(center[name]) for name in ("場", *SOURCE_FIELDS)},
        "確認出典": {name: deepcopy(right[name]) for name in ("場", *SOURCE_FIELDS)},
        "五足番号": [row["index"] for row in five]}


def structure(highs: list[dict], lows: list[dict]) -> tuple[bool, int | None]:
    """最新2高と2安の差の符号から構造を別式で分類する。

    引数: highs/lows(list[dict])は古い順の直近2極値。
    返り値: tuple[bool,int|None]は準備/方向。同値混在と履歴不足を分ける。
    """
    if len(highs) != 2 or len(lows) != 2:
        return False, None
    differences = [values[1]["極値価格"] - values[0]["極値価格"] for values in (highs, lows)]
    signs = tuple((value > 0) - (value < 0) for value in differences)
    return True, 1 if signs == (1, 1) else -1 if signs == (-1, -1) else 0


def verdicts(row: dict) -> dict:
    """固定した構造/DI基準へFast準備と精密方向だけを追加する。

    引数: row(dict)は消費済み原Pの当時判断。
    返り値: dictは三案の全採否・理由。
    """
    baseline = list(row["M除外理由"])
    if not row["時間条件可"]:
        baseline.append("要求時間条件外")
    if not row["確認遅延条件可"]:
        baseline.append("確認遅延30秒超")
    if row["構造方向"] == 0:
        baseline.append("構造方向同値又は混在WAIT")
    if row["DI優勢符号"] is None or row["side"] * row["DI優勢符号"] <= 0:
        baseline.append("DI実方向優勢strict正不成立")
    output = {}
    for policy in POLICIES:
        reasons = list(baseline)
        if policy != "C0" and not row["Fast準備"]:
            reasons.append("Fast14_3精密差未準備")
        if policy == "C2" and (row["Fast差厳密符号"] is None or row["side"] * row["Fast差厳密符号"] <= 0):
            reasons.append("Fast実方向strict正不成立")
        output[policy] = {"採用": not reasons, "理由": reasons or ["確定スイング突破と構造DI複合採用"], "同時競合": False}
    return output


def pure_signal(row: dict, policy: str = "C0") -> dict:
    """採用原Pから実役割・実方向を保持した純13列だけを写す。

    引数: row(dict)は当時の原P、policy(str)はC0/C1/C2。
    返り値: dictは新j要求の執行信号。WAITと不整合方向は拒否する。
    """
    if policy not in POLICIES or row["side"] not in (-1, 1) or row["役割"] not in ("順行", "反転"):
        raise ValueError("実方向/実役割の三案だけ")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示不一致")
    output = {name: deepcopy(row[name]) for name in SIGNAL_FIELDS if name not in ("イベントID", "入口ID", "bb_mean")}
    return {**output, "イベントID": row["発動ID"] + "_" + policy, "入口ID": "3分_" + policy, "bb_mean": None}


def local_reasons(row: dict, previous: dict | None) -> list[str]:
    """公開価格の局所区間を切る理由だけを抽出する。

    引数: row(dict)は当足、previous(dict|None)は直前入力足。
    返り値: list[str]は構造履歴/usedの解除理由。
    """
    reasons = []
    if previous is not None and (row["index"] != previous["index"] + 1 or row["start"] != previous["end"]):
        reasons.append("番号又は終了非連続")
    if row["missing"]:
        reasons.append("欠枠")
    if not row["publish"]:
        reasons.append("非公開")
    if not price_valid(row):
        reasons.append("完全3分価格不正")
    if "限月変更" in row["DMI解除理由"]:
        reasons.append("限月変更")
    return reasons


def center_table(frames: list[dict], session: str) -> dict[int, list[dict]]:
    """全中心候補を区間走査し、確認番号ごとの公開予約表を別構築する。

    引数: frames(list[dict])は当場28列、session(str)は場。
    返り値: dictは確認足index→極値。generateは確認足のP判断後にだけ公開する。
    """
    epochs, valid, epoch, previous, public_key = [], [], 0, None, None
    for row in frames:
        if row["場"] != session or row["minutes"] != 3:
            raise ValueError("当場3分の数値だけ")
        key = row["confirm"], row["confirm_line"]
        if previous is not None and row["index"] <= previous["index"]:
            raise ValueError("足番号重複又は後退")
        if row["publish"] and (row["confirm"] < row["end"] or public_key is not None and key <= public_key):
            raise ValueError("公開key同値/後退又は終了前公開")
        if local_reasons(row, previous):
            epoch += 1
        epochs.append(epoch)
        valid.append(bool(row["publish"] and not row["missing"] and price_valid(row)))
        previous = row
        if row["publish"]:
            public_key = key
    released = defaultdict(list)
    for middle in range(2, len(frames) - 2):
        left, right = middle - 2, middle + 3
        if not all(valid[left:right]) or len(set(epochs[left:right])) != 1:
            continue
        five = frames[left:right]
        for side, field in ((1, "high"), (-1, "low")):
            center = five[2][field]
            prior_extreme = max(part[field] for part in five[:2]) if side == 1 else min(part[field] for part in five[:2])
            next_extreme = max(part[field] for part in five[3:]) if side == 1 else min(part[field] for part in five[3:])
            if side * (center - prior_extreme) > 0 and side * (center - next_extreme) >= 0:
                released[five[-1]["index"]].append(pivot(five, side, session))
    return dict(released)


def event_row(row: dict, previous: dict, latest: dict, highs: list[dict], lows: list[dict],
              side: int, cutoff: float, deadline: float, config: dict) -> dict:
    """消費した原Pへ当時の構造・使用数値・時計だけを付ける。

    引数: row/previous/latest(dict)は当足/前足/突破極値、highs/lows(list)は最新2履歴、
    side(int)は実方向、cutoff/deadline(float)は時刻境界、config(dict)は固定時間条件。
    返り値: dictは未来先着を含まない原発動判定。
    """
    ready, direction = structure(highs[-2:], lows[-2:])
    role = "順行" if ready and direction == side else "反転" if ready and direction == -side else None
    branch = "T" if role == "順行" else "R" if role == "反転" else "WAIT"
    change = row["plus_di"] - row["minus_di"] if finite(row["plus_di"]) and finite(row["minus_di"]) else None
    missing = []
    if not ready:
        missing.append("最新2高2安未準備")
    if not row["DMI準備"] or change is None:
        missing.append("DMI14有限未準備")
    if not finite(row["atr"]) or row["atr"] <= 0:
        missing.append("現在ATR14有限正未準備")
    event = f"NK225_{row['場']}_3分_スイング突破_{row['index']:04d}_{side}_{latest['中心番号']:04d}"
    result = {**deepcopy(row), "発動ID": event, "イベントID": event, "入口ID": "3分_スイング突破",
        "入口系統": "確定スイング突破", "時間足分": 3, "side": side, "元価格side": side,
        "方向": "買い" if side == 1 else "売り", "役割": role, "判別種別": branch,
        "突破極値ID": latest["極値ID"], "突破価格": latest["極値価格"], "元極値中心番号": latest["中心番号"],
        "構造準備": ready, "構造方向": direction,
        "構造参照": {"高値ID": [p["極値ID"] for p in highs[-2:]], "安値ID": [p["極値ID"] for p in lows[-2:]]},
        "前3分参照": frame_projection(previous), "DI差": change,
        "DI優勢符号": (change > 0) - (change < 0) if change is not None else None,
        "共通M準備": not missing, "M除外理由": missing,
        "時間条件可": row["confirm"] < cutoff and deadline - row["confirm"] >= config["残り時間下限分"] * 60,
        "確認遅延条件可": row["confirm"] - row["end"] <= config["確認遅延上限秒"],
        "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"], "足終了時計秒": row["end"],
        "確認遅延秒": row["confirm"] - row["end"], "期限時計秒": deadline,
        "残り分_判断時": (deadline - row["confirm"]) / 60, "bb_mean": None}
    result["先着評価対象"] = result["時間条件可"] and result["確認遅延条件可"]
    result["戦略判定"] = verdicts(result)
    return result


def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> dict:
    """中心候補の公開予約表から、前足までの水準だけで全Pを作る。

    引数: frames(list[dict])は28列、session(str)は場、cutoff/deadline(float)は停止/期限、
    config(dict)は固定時間条件。
    返り値: dictは全極値/監視/原P/全採否/三信号。先着・PnLは計算しない。
    """
    frames = [numeric_projection(row) for row in frames]
    releases = center_table(frames, session)
    highs, lows, history, used = [], [], [], set()
    pivots, traces, records, metadata, previous_input = [], [], [], {}, None
    counts = Counter({"局所解除足数": 0, "対象時点外足数": 0, "再cross消費済み数": 0})

    def snapshot() -> dict:
        """既知の極値ID・局所足番号・消費数だけを複写する。

        引数: なし。当場状態を参照する。
        返り値: dictは全値の重複転記をしない状態。
        """
        return {"高値ID": [row["極値ID"] for row in highs[-2:]],
                "安値ID": [row["極値ID"] for row in lows[-2:]],
                "局所五足番号": [row["index"] for row in history[-5:]], "使用済み数": len(used)}

    for row in frames:
        before, actions = snapshot(), []
        reasons = local_reasons(row, previous_input)
        if reasons:
            highs, lows, history, used = [], [], [], set()
            counts["局所解除足数"] += 1
            actions.append({"動作": "局所解除", "理由": reasons})
        eligible = bool(row["publish"] and not row["missing"] and price_valid(row))
        previous = history[-1] if history else None
        if eligible and previous is not None:
            if row["end"] <= previous["confirm"]:
                counts["対象時点外足数"] += 1
                actions.append({"動作": "価格観測対象外", "理由": ["当足終了が前足公開以前"],
                                "前足番号": previous["index"]})
            else:
                choices = [(1, highs[-1] if highs else None), (-1, lows[-1] if lows else None)]
                for side, point in choices:
                    if point is None:
                        continue
                    level = point["極値価格"]
                    happened = (previous["close"] <= level < row["close"]) if side == 1 else (previous["close"] >= level > row["close"])
                    if not happened:
                        continue
                    marker = side, point["極値ID"]
                    if marker in used:
                        counts["再cross消費済み数"] += 1
                        actions.append({"動作": "使用済みcross見送り", "side": side, "極値ID": point["極値ID"]})
                        continue
                    used.add(marker)
                    record = event_row(row, previous, point, highs, lows, side, cutoff, deadline, config)
                    records.append(record)
                    metadata[record["発動ID"]] = {name: deepcopy(record[name]) for name in METADATA_FIELDS}
                    actions.append({"動作": "初回cross消費", "発動ID": record["発動ID"],
                                    "side": side, "極値ID": point["極値ID"]})
        if eligible:
            history.append(row)
            for point in releases.get(row["index"], []):
                pivots.append(point)
                (highs if point["極値side"] == 1 else lows).append(point)
                actions.append({"動作": "極値確定", "極値ID": point["極値ID"]})
        traces.append({"場": session, "index": row["index"], "公開key": [row["confirm"], row["confirm_line"]],
            "足終了時計秒": row["end"], "監視前": before, "動作": actions, "監視後": snapshot()})
        previous_input = row
    selected = defaultdict(list)
    for record in records:
        for policy in POLICIES:
            if record["戦略判定"][policy]["採用"]:
                selected[policy, record["要求時計秒"], record["要求原板行"]].append(record)
    for (policy, _, _), group in selected.items():
        if len(group) > 1:
            for record in group:
                record["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
    signals = {"3分_" + policy: [] for policy in POLICIES}
    for record in records:
        for policy in POLICIES:
            if record["戦略判定"][policy]["採用"]:
                signals["3分_" + policy].append({**deepcopy(record), "イベントID": record["発動ID"] + "_" + policy,
                    "入口ID": "3分_" + policy, "戦略": policy, "複合判定": deepcopy(record["戦略判定"][policy])})
    quality = {"場": session, "時間足分": 3, "入力足数": len(frames), **dict(counts),
        "確定極値数": len(pivots), "高値極値数": sum(p["極値side"] == 1 for p in pivots),
        "安値極値数": sum(p["極値side"] == -1 for p in pivots), "原価格発動数": len(records),
        "先着評価対象外数": sum(not r["先着評価対象"] for r in records),
        "戦略別発動数": {name: len(values) for name, values in signals.items()},
        "構造判別数": dict(Counter(row["判別種別"] for row in records)),
        "戦略採否理由別": {p: dict(Counter(reason for row in records for reason in row["戦略判定"][p]["理由"]))
                        for p in POLICIES}}
    return {"場": session, "frames": {3: frames}, "signals": signals, "raw": records, "decisions": records,
            "pivots": pivots, "monitor_trace": traces, "metadata": metadata, "quality": quality}


# ----------------------------------------
# 共通台帳・準備・正式の結合。市場CLIのownerはrootのみ。

def dependency_pins() -> dict:
    """固定独立足・中心化MACD・直接先着・追尾の全依存を識別する。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathと現在SHA。45主コードを数式依存にしない。
    """
    paths = {"scripts/回帰突破/状態独立確認.py", "scripts/発動値幅継続/状態独立確認.py", "scripts/OBV反転/状態独立確認.py",
        "scripts/終値位置/追尾独立確認.py"}
    return dict(sorted({**Y.dependency_pins(), **{name: V.sha(ROOT / name) for name in paths}}.items()))



def shared_bundle(audit: Audit) -> dict:
    """29の保存全数値を出典照合し、3分14列だけを研究入力へ渡す。

    引数: audit(Audit)は圧縮・展開SHAとサイズの比較先。
    返り値: dictはlowerと元数値展開SHA。旧P/旧case/旧取引を読み込まない。
    """
    rows, digest = saved_rows(INDICATOR_STUDY, INDICATOR_WORK, "全指標.jsonl.gz", audit)
    lower = defaultdict(list)
    for row in rows:
        if row["minutes"] == 3:
            lower[row["場"]].append(frame_projection(row))
    return {"lower": lower, "共有3分全指標展開SHA256": digest}



def references(study: Path, audit: Audit) -> None:
    """指標参照だけを固定29正本へ結び、旧入口を新発動の正本にしない。

    引数: study(Path)は45、audit(Audit)は比較先。
    返り値: None。各証明と全数値明細の現在指紋を検査する。
    """
    anchor = "353143ea3f7a626736bf44551d17ba6e22b8bfd76ee40e2f4f9b0c190736f48a"
    audit.check("29固定正本", V.sha(INDICATOR_STUDY / "固定.json"), anchor)
    for name, digest in V.read(INDICATOR_STUDY / "固定.json")["ファイルSHA256"].items():
        audit.check("29固定現在:" + name, V.sha(ROOT / name), digest)
    ref = V.read(study / "指標参照.json")
    audit.check("数値参照試行", ref["参照試行"], "00029")
    audit.check("数値参照固定", ref["旧固定SHA256"], anchor)
    audit.check("数値複製なし", ref["大明細複製"], False)
    expected_names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json",
        "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
    audit.check("数値参照証明集合", set(ref["文書と証明"]), expected_names)
    for name, item in ref["文書と証明"].items():
        audit.check("数値参照正本:" + name, (ROOT / item["パス"]).resolve(), (INDICATOR_STUDY / name).resolve())
        audit.check("数値参照SHA:" + name, item["SHA256"], V.sha(INDICATOR_STUDY / name))
    for name in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
        proof = V.read(INDICATOR_STUDY / name)
        audit.check("数値旧証明成功:" + name, (proof["全件一致"], proof["不一致数"]), (True, 0))
    expected = [row for row in V.read(INDICATOR_STUDY / "作業成果物.json")["ファイル"]
        if Path(row["パス"]).name == "全指標.jsonl.gz"]
    audit.check("数値共有集合", ref["共有明細"], expected)
    for item in expected:
        path = ROOT / item["パス"]
        audit.check("数値圧縮SHA", V.sha(path), item["圧縮SHA256参考"])
        audit.check("数値圧縮bytes", path.stat().st_size, item["圧縮バイト"])




def read_definition(work: Path, master: dict, audit: Audit) -> dict[str, dict[int, dict]]:
    """主準備が保存した小型DI定義を圧縮・展開指紋と全行構造まで検査する。

    引数: work(Path)は45作業先、master(dict)は主準備、audit(Audit)は比較先。
    返り値: dictは場→index→4列定義。独立DIをこれで計算し直さない。
    """
    info = master["DMI数値定義"]
    audit.check("DI定義参照keys", set(info), {"パス", "圧縮SHA256参考", "展開内容SHA256", "行数"})
    if set(info) != {"パス", "圧縮SHA256参考", "展開内容SHA256", "行数"}:
        raise ValueError("DI定義参照keys不一致")
    path = (ROOT / info["パス"]).resolve()
    audit.check("DI定義保存先", path, (work / "DMI数値定義.jsonl.gz").resolve())
    if path != (work / "DMI数値定義.jsonl.gz").resolve():
        raise ValueError("DI定義の保存先範囲差")
    audit.check("DI定義圧縮SHA", V.sha(path), info["圧縮SHA256参考"])
    if audit.mismatches:
        raise ValueError("DI定義圧縮指紋に差があり展開前停止")
    rows, digest = [], hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            rows.append(json.loads(raw))
    audit.check("DI定義展開SHA", digest.hexdigest(), info["展開内容SHA256"])
    audit.check("DI定義行数", len(rows), info["行数"])
    sessions = [row["場"] for row in master["準備"]]
    output, order = defaultdict(dict), []
    for row in rows:
        valid = (isinstance(row, dict) and set(row) == {"場", "index", "plus_di", "minus_di"} and row["場"] in sessions
                 and type(row["index"]) is int and row["index"] >= 0
                 and ((row["plus_di"] is None and row["minus_di"] is None) or (finite(row["plus_di"]) and finite(row["minus_di"]) and row["plus_di"] >= 0 and row["minus_di"] >= 0)))
        audit.check("DI定義行構造", valid, True)
        if not valid:
            raise ValueError("DI定義に想定外の属性・数値がある")
        key = row["場"], row["index"]
        audit.check("DI定義足一意:" + str(key), row["index"] not in output[row["場"]], True)
        output[row["場"]][row["index"]] = row
        order.append(key)
    audit.check("DI定義全行昇順", order == sorted(order), True)
    expected = [(row["場"], row["全指標足数"]) for row in master["準備"]]
    audit.check("DI定義場別全足数", [(session, len(output[session])) for session in sessions], expected)
    if audit.mismatches:
        raise ValueError("小型DI定義・主準備の出典に差がありcache前停止")
    return dict(output)


def define_rows(independent: list[dict], shared: list[dict], definition: dict[int, dict]) -> list[dict]:
    """独立計算を保持し、検査対象となる正本ATR/DI定義の28列を別配列に作る。

    引数: independent(list[dict])は原8列別算、shared(list[dict])は29の14列、
    definition(dict[int,dict])は保存済み4列DI定義。
    返り値: list[dict]はATR/DI値だけを正本へ置いた定義列。銀行や生配列を変更しない。
    """
    original = {row["index"]: row for row in shared}
    indices = [row["index"] for row in independent]
    if len(original) != len(shared) or len(indices) != len(set(indices)) or set(indices) != set(original) or set(indices) != set(definition):
        raise ValueError("原足/共有ATR/DI定義の全足一対一対応に差")
    output = []
    for row in independent:
        source, values = original[row["index"]], definition[row["index"]]
        if row["場"] != source["場"] or row["場"] != values["場"]:
            raise ValueError("定義の場対応に差")
        output.append({**deepcopy(row), "atr": deepcopy(source["atr"]),
                       "plus_di": deepcopy(values["plus_di"]), "minus_di": deepcopy(values["minus_di"])})
    return output


def reconstruct(manifest: dict, bundle: dict, config: dict) -> Any:
    """原8列から足・ATR・DI/Fast・確定山谷と全初回crossを別構築する。

    引数: manifest/bundle/config(dict)は固定台帳/共有ATRとDI定義/条件。
    返り値: Anyは場別iterator。正本定義と独立生数値の二つの判断を保存する。
    """
    bank = NumericHistory()
    for entry in manifest["entries"]:
        session = entry["session"]
        start, finish, cutoff, deadline = S.G.times(session)
        data = G.observed(entry, manifest)
        formed = S.bars(data, session, 3, N.BareBars())
        tail = max(0, int((finish - start) // 180) - 1 - (formed[-1]["index"] if formed else -1))
        independent, quality = bank.build(formed, session, tuple(entry["in_session_contract_codes"]), tail)
        defined = define_rows(independent, bundle["lower"][session], bundle["di_definition"].get(session, {}))
        selected = generate(defined, session, cutoff, deadline, config)
        alternate = generate(independent, session, cutoff, deadline, config)
        pure = [pure_signal(row, policy) for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        period = "学習" if session[:10] < config["分割"]["選択開始日"] else ("条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in pure]),
            "判定": selected["decisions"], "判定SHA256": canonical_sha(selected["decisions"]),
            "判定判断SHA256": canonical_sha(selected["decisions"]),
            "全3分投影SHA256": canonical_sha([frame_projection(row) for row in defined]), "3分投影足数": len(defined),
            "入力品質": selected["quality"], "全指標内容SHA256": canonical_sha(defined), "全指標足数": len(defined),
            "極値SHA256": canonical_sha(selected["pivots"]), "極値数": len(selected["pivots"]),
            "監視SHA256": canonical_sha(selected["monitor_trace"]), "監視足数": len(selected["monitor_trace"]),
            "数値品質": quality, "_再算全3分": independent, "_正本数値定義全3分": defined,
            "_正本判断": selected, "_再算判断": alternate}


def compare_preparation(main_record: dict, block: dict, bundle: dict, audit: Audit) -> dict:
    """全足の限定数値比較、判断同値、正本定義SHAの三段階を個別に検査する。

    引数: main_record/block(dict)は主/独立場別準備、bundle(dict)は共有ATRとDI定義、
    audit(Audit)は比較先。
    返り値: dictは表現差・全山谷・初回cross・三集合の要約。
    """
    session, independent, defined = block["場"], block["_再算全3分"], block["_正本数値定義全3分"]
    audit.check(session + ":原8列SOURCEと全ATR", [frame_projection(row) for row in independent], bundle["lower"][session])
    numeric_same = compare_numeric_scope(session + ":全28列独立DI/Fast", defined, independent, audit)
    expected = {key: value for key, value in block.items() if not key.startswith("_")}
    audit.check(session + ":全正本定義と主準備", main_record, expected)
    audit.check(session + ":正本定義全値厳密JSON", main_record == expected, True)
    selected, alternate = block["_正本判断"], block["_再算判断"]
    decision_same = compare_numeric_scope(session + ":生数値による全P", selected["decisions"], alternate["decisions"], audit)
    alternate_pure = [pure_signal(row, policy) for policy in POLICIES for row in alternate["signals"]["3分_" + policy]]
    pure_same = compare_numeric_scope(session + ":生数値による全純13", block["純信号"], alternate_pure, audit)
    for name in ("pivots", "monitor_trace", "metadata", "quality"):
        audit.check(session + ":生数値価格機械と品質:" + name, selected[name], alternate[name])
        audit.check(session + ":生数値残余厳密:" + name, selected[name] == alternate[name], True)
    ids = {policy: {row["イベントID"][:-3] for row in main_record["純信号"] if row["入口ID"] == "3分_" + policy} for policy in POLICIES}
    audit.check(session + ":C1subsetC0", ids["C1"] <= ids["C0"], True)
    audit.check(session + ":C2subsetC1", ids["C2"] <= ids["C1"], True)
    originals = {row["発動ID"]: row for row in block["判定"]}
    for signal in block["純信号"]:
        policy = signal["入口ID"].removeprefix("3分_")
        audit.check(signal["イベントID"] + ":純13列", set(signal), set(SIGNAL_FIELDS))
        audit.check(signal["イベントID"] + ":元P純射影", signal == pure_signal(originals[signal["イベントID"][:-3]], policy), True)
        audit.check(signal["イベントID"] + ":実T/R固定", signal["役割"] in ("順行", "反転"), True)
    differences = {name: [abs(a[name] - b[name]) for a, b in zip(independent, defined, strict=True)
        if finite(a[name]) and finite(b[name]) and a[name] != b[name]] for name in ("atr", "plus_di", "minus_di")}
    return {"場": session, "期間": block["期間"], **{p + "登録数": len(ids[p]) for p in POLICIES},
        "原価格発動数": len(block["判定"]), "3分投影足数": len(independent),
        "極値数": block["極値数"], "監視足数": block["監視足数"],
        **{name + "表現差足数": len(values) for name, values in differences.items()},
        **{name + "最大絶対差": max(values, default=0.0) for name, values in differences.items()},
        "再算数値判断不一致場": int(not (numeric_same and decision_same and pure_same)),
        "全3分投影SHA256": block["全3分投影SHA256"], "正本定義全指標内容SHA256": block["全指標内容SHA256"],
        "独立生全指標内容SHA256": canonical_sha(independent), "生全指標SHA同値": canonical_sha(independent) == block["全指標内容SHA256"],
        "全判定SHA256": block["判定SHA256"], "独立生全判定SHA256": canonical_sha(alternate["decisions"])}


def numeric_summary(stages: list[dict]) -> dict:
    """正本整合と生数値表現差・全厳密判断影響を分離集計する。

    引数: stages(list[dict])は場別準備要約。
    返り値: dictは足/山谷/全P件数と限定数値差。生SHA差を判断差と呼ばない。
    """
    return {"新3分全数値照合足数": sum(row["3分投影足数"] for row in stages),
        "原価格発動数": sum(row["原価格発動数"] for row in stages),
        "確定極値数": sum(row["極値数"] for row in stages), "全監視足数": sum(row["監視足数"] for row in stages),
        "独立数値判断不一致場数": sum(row["再算数値判断不一致場"] for row in stages),
        "独立生全指標SHA差場数": sum(not row["生全指標SHA同値"] for row in stages),
        **{"独立" + name + "表現差足数": sum(row[name + "表現差足数"] for row in stages) for name in ("atr", "plus_di", "minus_di")},
        **{"独立" + name + "最大絶対差": max((row[name + "最大絶対差"] for row in stages), default=0.0) for name in ("atr", "plus_di", "minus_di")}}



def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """非損益主準備と三案・費用・入力・使用数値版を市場入力前に照合する。

    引数: study/work(Path)は45保存先、audit(Audit)は比較先。
    返り値: tupleは条件/解決台帳/主準備/台帳path。差があればcache前に停止する。
    """
    config, (manifest, resolved) = V.read(study / "条件.json"), G.resolved_manifest(study)
    references(study, audit)
    old, fee = V.read(INDICATOR_STUDY / "条件.json"), V.read(EXIT_STUDY / "条件.json")
    for key in ("対象", "時間足分", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒",
            "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割"):
        audit.check("固定評価尺度:" + key, config[key], old[key])
    for key in ("運用", "必須追尾"):
        audit.check("固定33費用出口:" + key, config[key], fee[key])
    audit.check("三入口", config["戦略"], list(POLICIES))
    audit.check("三XF", config["運用組合せ"], [{"戦略": p, "出口ID": "XF"} for p in POLICIES])
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "純信号whitelist": list(SIGNAL_FIELDS),
        "指標参照SHA256": V.sha(study / "指標参照.json")}
    for name, value in expected.items():
        audit.check("主準備:" + name, master[name], value)
    paths = {"scripts/スイング突破/" + name for name in ("検証.py", "入口.py", "指標.py", "運用.py")}
    audit.check("主四コード集合", set(master["コードSHA256"]), paths)
    for name, digest in master["コードSHA256"].items():
        audit.check("主準備現在:" + name, V.sha(ROOT / name), digest)
    audit.check("主66場順", [row["場"] for row in master["準備"]], [entry["session"] for entry in manifest["entries"]])
    if audit.mismatches:
        raise ValueError("入力/主準備/数値参照に差があり市場入力前停止")
    return config, manifest, master, resolved



def proof_base(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> dict:
    """主版・入力・独立依存と数値責任の三段階を結ぶ。

    引数: study/work/resolved(Path)は保存/台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: dictは準備/正式共通proof。旧入口証明に新Pの責務を委ねない。
    """
    return {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches,
        "不一致": audit.errors, "コードSHA256": V.sha(Path(__file__)),
        "追尾コードSHA256": V.sha(Path(__file__).with_name("追尾独立確認.py")), "依存コードSHA256": dependency_pins(),
        "主準備SHA256": V.sha(work / "準備点検.json"), "主コードSHA256": master["コードSHA256"],
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        "指標参照SHA256": V.sha(study / "指標参照.json"),
        "DMI数値定義": deepcopy(master["DMI数値定義"]),
        "厳密範囲": "原8列SOURCE/全山谷/全消費/Fast全分数/準備/DI優勢/時点/採否は厳密。ATRとplus_di/minus_di/DI差の値だけabs1e-10/rel0、ATR正有効/D整数はstrict。検算済み正本ATR/DIで定義した全数値/全PのSHAと独立生数値SHAを分離し、生DI優勢/準備/採否の全一致を要求。epsilonなし。",
        "数値許容": {"対象": ["atr", "plus_di", "minus_di", "DI差"], "絶対許容": 1e-10, "相対許容": 0,
            "採否epsilon": False, "正本定義SHAと独立生数値SHAを区別": True}}



def prepare(study: Path, work: Path) -> dict:
    """root起動の非損益準備で原足/DI/Fastと全スイング/消費を検算する。

    引数: study/work(Path)は45保存先。
    返り値: dictはラベル・運用・PnL計算を呼ばない独立準備証明。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    bundle, stages = shared_bundle(audit), []
    bundle["di_definition"] = read_definition(work, master, audit)
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        print(json.dumps({"場": block["場"], "独立準備": "原8列ATR/DI/Fast・全極値/消費/三C", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "全66場既使用": True, "場別準備": stages, **numeric_summary(stages),
        "方針別登録数": {p: sum(r[p + "登録数"] for r in stages) for p in POLICIES},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "検証範囲": "原8列から3分OHLC/ATR/DIと局所Fastを別算。中心候補予約表で全山谷/状態/消費/全新P/三採否を独立構築。正本DIとATR定義SHAは生数値の限定許容と全優勢/準備/採否strictから分離する。",
        "限界": "非先着/非運用/非PnL。旧29は数値出典だけ、旧188入口/旧case/旧全属性対照を流用しない。全66場既使用。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "原価格発動数", "方針別登録数")}, ensure_ascii=False))
    return proof



def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """成功した独立準備と全固定指紋を正式市場入力前に要求する。

    引数: study/work/resolved(Path)は保存/台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: None。古版・未完・差ありは停止する。
    """
    prepared, expected = V.read(work / "独立準備点検.json"), proof_base(study, work, resolved, master, audit)
    for key in ("コードSHA256", "追尾コードSHA256", "依存コードSHA256", "主準備SHA256", "主コードSHA256",
            "条件SHA256", "入力台帳SHA256", "参照入力台帳SHA256", "指標参照SHA256", "DMI数値定義"):
        audit.check("準備bind:" + key, prepared[key], expected[key])
    for key, value in {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False}.items():
        audit.check("準備成功:" + key, prepared[key], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("準備/固定/現版に差があり正式市場入力前停止")


def run(study: Path, work: Path) -> dict:
    """正式後だけ全山谷・全初回cross・全採否と全case直接先着を照合する。

    引数: study/work(Path)は45正式/作業先。
    返り値: dictは六系列の状態証明。受付/約定/Decimalと全実保有は別証明へ結ぶ。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    bundle = shared_bundle(audit)
    bundle["di_definition"] = read_definition(work, master, audit)
    names = ("全指標", "価格状態", "発動判定", "入口事例", "全運用詳細", "追尾")
    saved, hashes, grouped = {}, {}, {name: defaultdict(list) for name in names}
    for name in names:
        saved[name], hashes[name] = saved_rows(study, work, name + ".jsonl.gz", audit)
        for row in saved[name]:
            grouped[name][row["場"]].append(row)
    artifact_names = {Path(row["パス"]).name for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新六成果物集合", artifact_names, {name + ".jsonl.gz" for name in names})
    pairs = [(row["場"], row["候補ID"]) for row in saved["全運用詳細"]]
    audit.check("全場候補一意", len(pairs), len(set(pairs)))
    audit.check("全3x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in OPERATIONS})
    audit.check("全case一意", len(saved["入口事例"]), len({row["イベントID"] for row in saved["入口事例"]}))
    if audit.mismatches:
        raise ValueError("正式保存物の集合/指紋に差があり原足入力前停止")
    stages, counts, role_counts = [], Counter({p: 0 for p in POLICIES}), Counter()
    entries = {entry["session"]: entry for entry in manifest["entries"]}
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        session, period, selected = block["場"], block["期間"], block["_正本判断"]
        expected_numeric = [{"期間": period, **row} for row in block["_正本数値定義全3分"]]
        expected_state = [{"種別": kind, "期間": period, **row} for kind, rows in
            (("極値", selected["pivots"]), ("監視", selected["monitor_trace"])) for row in rows]
        expected_decisions = [{"期間": period, **row} for row in block["判定"]]
        for name, expected in (("全指標", expected_numeric), ("価格状態", expected_state), ("発動判定", expected_decisions)):
            audit.check(session + ":正式全値:" + name, grouped[name][session], expected)
            audit.check(session + ":正式厳密JSON:" + name, grouped[name][session] == expected, True)
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":全case純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(entries[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for signal in block["純信号"]:
            origin = signal["イベントID"][:-3]
            direct = label_direct(quotes, signal, cutoff, deadline)
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": datetime.fromtimestamp(signal["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "元価格発動ID": origin, **deepcopy(selected["metadata"][origin]), **direct}
            audit.check(signal["イベントID"] + ":全新case直接BBO先着", cases.get(signal["イベントID"]), expected)
            audit.check(signal["イベントID"] + ":全新case厳密値", cases.get(signal["イベントID"]) == expected, True)
            policy = signal["入口ID"].removeprefix("3分_")
            counts[policy] += 1
            role_counts[(policy, signal["役割"])] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
        print(json.dumps({"場": session, "独立状態": "原8列ATR/DI/Fast・全山谷/消費・全新case直接先着",
                          "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    audit.check("正式三候補順", [row["候補ID"] for row in result["結果"]], list(OPERATIONS))
    audit.check("全case数", len(saved["入口事例"]), sum(counts.values()))
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages, **numeric_summary(stages),
        "方針別case数": dict(counts), "全先着直接照合件数": sum(counts.values()), "方針別先着直接照合件数": dict(counts),
        "役割別先着直接照合件数": [{"戦略": p, "役割": role, "件数": role_counts[(p, role)]}
            for p in POLICIES for role in ("順行", "反転")],
        "保存全指標数": len(saved["全指標"]), "保存価格状態数": len(saved["価格状態"]),
        "保存発動判定数": len(saved["発動判定"]), "保存入口事例数": len(saved["入口事例"]),
        "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "DI数値照合統計": audit.di_stats, "DI差厳密符号不一致数": audit.di_sign_diffs,
        "検証範囲": "原8列OHLC/独立ATR/DI/局所精密Fast、全確定山谷/公開時計/初回cross/used/構造/三採否/純13を別構築。全新caseの最初+1秒正常BBOから125/250/空白/期限を実sideで直接走査。定義数値の全SHA整合と独立生数値の全準備/優勢/採否strictを分離。",
        "限界": "旧29は足/ATR出典のみ。旧入口/旧先着/旧全属性対照は流用しない。実新規受付/最初BBO/Decimalは別会計、全保有と最初返済要求は別追尾。全66場既使用。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "方針別case数")}, ensure_ascii=False))
    return proof



def main() -> None:
    """root許可による非損益準備又は固定後正式検算を明示起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定・不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00045確定スイングとDMI/Fastの独立検算")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    proof = prepare(args.study.resolve(), args.work.resolve()) if args.prepare else run(args.study.resolve(), args.work.resolve())
    if not proof["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
