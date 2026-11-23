"""00048のForce失敗f・後続価格kと上位禁止・全新先着を独立検算する。"""

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
STUDY = ROOT / "study/00048_Force失敗後の価格確認と上位禁止"
WORK = ROOT / "work/Force失敗確認/00048"
INDICATOR_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
INDICATOR_WORK = ROOT / "work/OBV反転/00029"
UPPER_STUDY = ROOT / "study/00028_基準線復帰と上位一目の方向"
UPPER_WORK = ROOT / "work/一目基準線/00028"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("S0", "S1")
OPERATIONS = tuple("3分_" + p + "_XF" for p in POLICIES)


def helper(path: Path, name: str) -> Any:
    """固定された独立足・数値・先着補助だけを読む。

    引数: path(Path)は固定独立コード、name(str)は読込名。
    返り値: Anyは補助。48主入口・主運用・主指標をimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value

OLD = helper(ROOT / "scripts/実体包み/状態独立確認.py", "Force波の固定独立原足と先着")
G, N, S, V, Y = OLD.G, OLD.N, OLD.S, OLD.V, OLD.Y
NumericHistory = OLD.NumericHistory
SIGNAL_FIELDS, LABEL_FIELDS, SOURCE_FIELDS = OLD.SIGNAL_FIELDS, OLD.LABEL_FIELDS, OLD.SOURCE_FIELDS
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr", "数量参照")
UPPER_FIELDS = ("場", *SOURCE_FIELDS, "macd_hist", "ema13_centered")
FORCE_FIELDS = ("数量入力可", "Force価格基準足番号", "Force価格基準終値", "Force入力可", "Force素",
    "Force2", "Force前", "Force符号", "Force前符号", "Force連続X数", "Force解除理由")
NUMERIC_FIELDS = (*FRAME_FIELDS, *FORCE_FIELDS)
finite, exact = OLD.finite, OLD.exact
canonical_sha, decision_signal = OLD.canonical_sha, OLD.decision_signal
normal_columns, label_direct = OLD.normal_columns, OLD.label_direct
saved_rows = OLD.saved_rows
ROLES = {"S0": "切替", "S1": "切替"}
ACTIVE_ROLES = {p: ("順行", "反転") for p in POLICIES}
ROLE_PAIRS = tuple((p, role) for p in POLICIES for role in ACTIVE_ROLES[p])
FAILURE_FIELDS = ("失敗足番号", "失敗時計秒", "失敗原板行", "失敗ID", "失敗段階", "失敗確認端")
METADATA_FIELDS = ("元登録ID", "元価格side", "元登録時計秒", "元登録原板行", "回復足番号", "回復時計秒", "判別種別", *FAILURE_FIELDS)
WATCH_FIELDS = ("登録ID", "元価格side", "登録足番号", "登録時計秒", "登録原板行", "初期逆端", "段階",
    "回復足番号", "回復時計秒", "回復原板行", "回復ID", "再開端", *FAILURE_FIELDS)


# ----------------------------------------
# 主のEMA逐次更新と分け、有限列の指数重み付き和からForceを計算する。


def force_value(values: list[Fraction]) -> Fraction | None:
    """最初二Xの算術種と指数重みの明示和からEMA2を別算する。

    引数: values(list[Fraction])は同場の連続有効Xを古い順に並べた列。
    返り値: Fraction|NoneはEMA2。二値未満は未準備で0としない。
    """
    if len(values) < 2:
        return None
    weighted = sum((Fraction(3) ** (index - 2)) * value for index, value in enumerate(values) if index >= 2)
    return (values[0] + values[1] + 4 * weighted) / (2 * Fraction(3) ** (len(values) - 2))


class Audit(N.Audit):
    """H/EMA水準の正負を新要件にせず、差のD/E方向を厳密検査する。"""

    def __init__(self) -> None:
        """値の限定許容と方向差の統計を空にする。

        引数: なし。
        返り値: None。
        """
        super().__init__()
        self.hist_stats, self.direction_differences, self.ema_direction_differences = {}, 0, 0

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """H/EMAとそれぞれの現前差だけ値の許容を適用し、差符号を別に比較する。

        引数: name(str)は経路、actual/expected(Any)は定義/独立値。
        返り値: None。ATRは固定比較器の正有効/D整数検査を継承する。
        """
        field = name.rsplit(":", 1)[-1]
        if field in ("macd_hist", "上位ヒスト現", "上位ヒスト前", "上位ヒスト差",
                "ema13_centered", "上位EMA現", "上位EMA前", "上位EMA差") and finite(actual) and finite(expected):
            stats = self.hist_stats.setdefault(field, {"比較leaf数": 0, "表現差leaf数": 0, "最大絶対差": 0.0})
            stats["比較leaf数"] += 1
            stats["表現差leaf数"] += int(actual != expected)
            stats["最大絶対差"] = max(stats["最大絶対差"], abs(actual - expected))
            self.leaf(name, actual, expected, math.isclose(actual, expected, abs_tol=1e-10, rel_tol=0))
            if field in ("上位ヒスト差", "上位EMA差"):
                left, right = (actual > 0) - (actual < 0), (expected > 0) - (expected < 0)
                if field == "上位ヒスト差":
                    self.direction_differences += int(left != right)
                else:
                    self.ema_direction_differences += int(left != right)
                self.leaf(name + ":方向strict", left, right, left == right)
            return
        return super().check(name, actual, expected)


def frame_projection(row: dict | None) -> dict | None:
    """下位の価格・ATR・観測数量だけを新辞書へ写す。

    引数: row(dict|None)は原足材料。
    返り値: dict|Noneは15列。3分H/CMF/旧入口を含めない。
    """
    return None if row is None else {name: deepcopy(row[name]) for name in FRAME_FIELDS}


def upper_projection(row: dict | None) -> dict | None:
    """上位の価格出典と新H/EMAだけを写す。

    引数: row(dict|None)は新15分数値。
    返り値: dict|Noneは15列。
    """
    return None if row is None else {name: deepcopy(row[name]) for name in UPPER_FIELDS}


def price_valid(row: dict, minutes: int = 3) -> bool:
    """完全幅の有限OHLCを公開状態と分けて検査する。

    引数: row(dict)は価格足、minutes(int)は3/15。
    返り値: boolは指定幅・尺度・OHLC整合の全成立。
    """
    return bool(row["minutes"] == minutes and row["end"] - row["start"] == minutes * 60 and N.valid_ohlc(row))


def build_local(frames: list[dict], session: str) -> tuple[list[dict], dict]:
    """連続した数量価格差の列を作り、指数重み和からForceを別構築する。

    引数: frames(list[dict])は下位15列、session(str)は場。
    返り値: tuple[list[dict],dict]はForce26列と品質。価格基準と数量解除を区別する。
    """
    rows, previous, baseline, public_key, values = [], None, None, None, []
    clears = 0
    for source in frames:
        row = frame_projection(source)
        if row["場"] != session or row["minutes"] != 3:
            raise ValueError("当場3分材料のみ")
        key = row["confirm"], row["confirm_line"]
        if previous is not None and row["index"] <= previous["index"]:
            raise ValueError("3分足番号重複又は後退")
        if row["publish"] and (row["confirm"] < row["end"] or public_key is not None and key <= public_key):
            raise ValueError("下位公開key同値/後退又は終了前公開")
        reasons = []
        if previous is None and row["index"] != 0 or previous is not None and (
                row["index"] != previous["index"] + 1 or row["start"] != previous["end"]):
            reasons.append("番号又は終了非連続")
        if row["missing"]:
            reasons.append("欠枠")
        if not row["publish"]:
            reasons.append("非公開")
        if not price_valid(row):
            reasons.append("完全3分価格不正")
        if reasons:
            baseline, values = None, []
        quantity = row["数量参照"]
        q = quantity.get("観測差分量") if isinstance(quantity, dict) else None
        quantity_ok = bool(isinstance(quantity, dict) and quantity.get("数量基準完全") is True and finite(q) and q >= 0)
        if not quantity_ok:
            reasons.append("数量基準完全非負未準備")
            values = []
        old_force = force_value(values)
        base_index = baseline["index"] if baseline is not None else None
        base_close = baseline["close"] if baseline is not None else None
        valid = bool(row["publish"] and not row["missing"] and price_valid(row))
        eligible = bool(valid and baseline is not None and quantity_ok)
        x = (Fraction(row["close"]) - Fraction(base_close)) * Fraction(q) if eligible else None
        if x is not None:
            values.append(x)
        current = force_value(values)
        rows.append({**row, "数量入力可": quantity_ok, "Force価格基準足番号": base_index,
            "Force価格基準終値": base_close, "Force入力可": eligible, "Force素": exact(x),
            "Force2": exact(current), "Force前": exact(old_force),
            "Force符号": (current > 0) - (current < 0) if current is not None else None,
            "Force前符号": (old_force > 0) - (old_force < 0) if old_force is not None else None,
            "Force連続X数": len(values), "Force解除理由": reasons})
        clears += bool(reasons)
        baseline = row if valid else None
        previous = row
        if row["publish"]:
            public_key = key
    return rows, {"場": session, "時間足分": 3, "入力足数": len(rows), "Force解除足数": clears,
        "Force入力足数": sum(row["Force入力可"] for row in rows), "Force準備足数": sum(row["Force2"]["有効"] for row in rows),
        "完全0量足数": sum(row["数量入力可"] and row["数量参照"]["観測差分量"] == 0 for row in rows)}


class UpperHistory:
    """元15分OHLCへ中心化MACDと独立13EMAを別経路で更新する。"""

    def __init__(self) -> None:
        """未契約の空中心化銀行を作る。

        引数: なし。
        返り値: None。下位ATR/Qとは状態を共有しない。
        """
        self.contract, self.center, self.ema = None, G.CenteredMACD(), G.P.Exponential(13)

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0) -> tuple[list[dict], dict]:
        """完全NPも内部更新し、価格欠測と契約変更で15分銀行を解除する。

        引数: frames(list[dict])は原15分、session(str)は場、contract(tuple)は限月、
        tail_missing(int)は完全尾部欠枠。
        返り値: tuple[list[dict],dict]は独立生15列と品質。主のupdateやAverageを呼ばない。
        """
        changed = self.contract is not None and self.contract != contract
        if changed:
            self.center, self.ema = G.CenteredMACD(), G.P.Exponential(13)
        self.contract = contract
        rows, previous, public_key, reason_counts = [], None, None, Counter()
        clears, inputs, np_updates = int(changed), 0, 0
        for frame in frames:
            if frame["minutes"] != 15 or previous is not None and frame["index"] <= previous["index"]:
                raise ValueError("15分足番号strict昇順のみ")
            key = frame["confirm"], frame["confirm_line"]
            if frame["publish"] and (frame["confirm"] < frame["end"] or public_key is not None and key < public_key):
                raise ValueError("上位公開key後退又は終了前公開")
            reasons = []
            if previous is None and frame["index"] != 0 or previous is not None and (
                    frame["index"] != previous["index"] + 1 or frame["start"] != previous["end"]):
                reasons.append("番号又は終了非連続")
            if frame["missing"]:
                reasons.append("欠枠")
            numeric = price_valid(frame, 15)
            if not numeric:
                reasons.append("完全15分価格不正")
            if reasons:
                self.center, self.ema, clears = G.CenteredMACD(), G.P.Exponential(13), clears + 1
                reason_counts.update(reasons)
            hist = self.center.add(frame["close"])["macd_hist"] if numeric else None
            ema = self.ema.add(frame["close"] - self.center.origin) if numeric else None
            inputs += numeric
            np_updates += bool(numeric and not frame["publish"])
            rows.append({"場": session, **N.source(frame), "macd_hist": hist, "ema13_centered": ema})
            previous = frame
            if frame["publish"]:
                public_key = key
        origin = self.center.origin
        if tail_missing:
            self.center, self.ema, clears = G.CenteredMACD(), G.P.Exponential(13), clears + 1
        return rows, {"場": session, "時間足分": 15, "入力足数": len(rows), "価格数値入力足数": inputs,
            "MACD準備足数": sum(finite(row["macd_hist"]) for row in rows),
            "EMA13準備足数": sum(finite(row["ema13_centered"]) for row in rows), "数値clear数": clears,
            "尾部完全欠枠": tail_missing, "非公開価格数値更新数": np_updates,
            "数値解除理由別": dict(reason_counts), "場末MACD原点": origin}


# ----------------------------------------
# 逐次pointerでなく可視集合を列挙し、監視は受理bごとの前進区間走査で組み立てる。


def key_of(row: dict) -> tuple:
    """価格公開の同秒原行を識別する。

    引数: row(dict)は価格足。
    返り値: tupleはconfirm/confirm_line。
    """
    return row["confirm"], row["confirm_line"]


def price_source(row: dict) -> dict:
    """価格出典13列だけを深写する。

    引数: row(dict)は当場価格足。
    返り値: dictは場/SOURCE12。
    """
    return {name: deepcopy(row[name]) for name in ("場", *SOURCE_FIELDS)}


def pair_state(current: dict | None, previous: dict | None, lower: dict) -> dict:
    """可視の最新上位と隣接前足を準備・方向へ別照合する。

    引数: current/previous(dict|None)は最新/前上位、lower(dict)は下位判断足。
    返り値: dictは出典・有限準備・ヒスト差方向。水準の正負で選別しない。
    """
    reasons = []
    if current is None:
        reasons.append("当場公開15分なし")
    elif previous is None:
        reasons.append("前上位公開参照なし")
    for label, row in (("現", current), ("前", previous)):
        if row is None:
            continue
        if not row["publish"]:
            reasons.append(label + "15分非公開")
        if not price_valid(row, 15):
            reasons.append(label + "15分完全価格不正")
        if row["missing"]:
            reasons.append(label + "15分欠枠")
        if row["confirm"] < row["end"]:
            reasons.append(label + "15分終了前公開")
        if row["end"] > lower["end"] or key_of(row) > key_of(lower):
            reasons.append(label + "15分asof不成立")
        if not finite(row["macd_hist"]):
            reasons.append(label + "15分MACDヒスト未準備")
    if current is not None and previous is not None:
        if previous["index"] + 1 != current["index"] or previous["end"] != current["start"]:
            reasons.append("上位現前番号又は終了非隣接")
        if key_of(previous) > key_of(current):
            reasons.append("上位前後公開順不整合")
    change = current["macd_hist"] - previous["macd_hist"] if not reasons else None
    if change is not None and not finite(change):
        reasons.append("上位MACDヒスト差非有限")
        change = None
    direction = (change > 0) - (change < 0) if change is not None else None
    ema_reasons = [reason for reason in reasons if "MACDヒスト" not in reason]
    for label, row in (("現", current), ("前", previous)):
        if row is not None and not finite(row["ema13_centered"]):
            ema_reasons.append(label + "15分EMA13未準備")
    ema_change = current["ema13_centered"] - previous["ema13_centered"] if not ema_reasons else None
    if ema_change is not None and not finite(ema_change):
        ema_reasons.append("上位EMA13差非有限")
        ema_change = None
    ema_direction = (ema_change > 0) - (ema_change < 0) if ema_change is not None else None
    impulse = None
    if not reasons and not ema_reasons:
        impulse = direction if direction == ema_direction and direction != 0 else 0
    return {"上位参照": upper_projection(current), "前上位参照": upper_projection(previous),
        "上位現前準備": not reasons, "上位除外理由": reasons,
        "上位ヒスト現": current["macd_hist"] if current is not None else None,
        "上位ヒスト前": previous["macd_hist"] if previous is not None else None,
        "上位ヒスト差": change, "上位ヒスト差符号": direction, "上位方向": direction,
        "上位EMA現": current["ema13_centered"] if current is not None else None,
        "上位EMA前": previous["ema13_centered"] if previous is not None else None,
        "上位EMA差": ema_change, "上位EMA差符号": ema_direction,
        "上位EMA現前準備": not ema_reasons, "上位EMA除外理由": ema_reasons,
        "上位Impulse方向": impulse}


def upper_state(higher15: list[dict], lower: dict) -> dict:
    """当時可視の集合の最大公開keyだけを上位参照にする。

    引数: higher15(list[dict])は当場15列、lower(dict)は下位足。
    返り値: dictは最新と当場index−1の状態。未来足の存在を理由へ漏らさない。
    """
    visible = {row["index"]: row for row in higher15
        if row["publish"] and row["end"] <= lower["end"] and key_of(row) <= key_of(lower)}
    latest = max(visible.values(), key=lambda row: (row["confirm"], row["confirm_line"], row["index"]), default=None)
    previous = visible.get(latest["index"] - 1) if latest is not None else None
    return pair_state(latest, previous, lower)


def pure_signal(row: dict, policy: str = "S0") -> dict:
    """初価格端の実方向・役割を13列へ固定する。

    引数: row(dict)は全P又は採用enriched、policy(str)はS0/S1。
    返り値: dictは純信号。登録/回復/上位/未来ラベルを含めない。
    """
    if policy not in POLICIES or row["side"] not in (-1, 1) or (policy, row["役割"]) not in ROLE_PAIRS:
        raise ValueError("候補の実方向又は役割に差")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("方向表示に差")
    return {**{name: deepcopy(row[name]) for name in SIGNAL_FIELDS},
            "イベントID": row["発動ID"] + "_" + policy, "入口ID": "3分_" + policy, "bb_mean": None}


def verdicts(row: dict) -> dict:
    """共通T又は新反転確認kを二切替の現在上位条件へ写す。

    引数: row(dict)は初端の構造/技術/時間判断。
    返り値: dictは二採否。初端の不成立を別端へ取り直さない。
    """
    common = list(row["M除外理由"])
    if not row["技術方向可"]:
        common.append("終端Force又は共通T上位実方向不一致")
    if not row["時間条件可"]:
        common.append("新要求時間条件外")
    if not row["確認遅延条件可"]:
        common.append("新要求確認遅延上限外")
    result = {}
    for policy in POLICIES:
        reasons = list(common)
        if row["価格区分"] == "R":
            if policy == "S0" and row["上位方向"] != row["side"]:
                reasons.append("反転確認kの上位D反転不一致")
            if policy == "S1" and (row["上位Impulse方向"] is None or row["上位Impulse方向"] == row["元価格side"]):
                reasons.append("反転確認kの旧方向Impulse禁止又は未準備")
        result[policy] = {"採用": not reasons, "理由": reasons or ["共通T又は失敗後初価格確認R採用"], "同時競合": False}
    return result


def event_row(frame: dict, watch: dict, upper: dict, kind: str, cutoff: float, deadline: float, config: dict) -> dict:
    """初端の価格T/Rと技術・時間によるWAITを分けて記録する。

    引数: frame/watch/upper(dict)は現足/監視/上位、kind(str)はT/R、cutoff/deadline(float)とconfig(dict)は時間条件。
    返り値: dictは初価格P。反転は元方向と逆のsideを新規に持つ。
    """
    side = watch["元価格side"] * (1 if kind == "T" else -1)
    now = frame["confirm"]
    time_ok = now < cutoff and now < deadline and deadline - now >= config["残り時間下限分"] * 60
    delay_ok = now - frame["end"] <= config["確認遅延上限秒"]
    missing = []
    if not upper["上位現前準備"]:
        missing.append("最新上位現前未準備")
    if kind == "R" and not upper["上位EMA現前準備"]:
        missing.append("反転確認kの共通EMA現前未準備")
    if not frame["Force2"]["有効"]:
        missing.append("Force2未準備")
    if not finite(frame["atr"]) or frame["atr"] <= 0:
        missing.append("現在ATR14有限正未準備")
    direction_ok = bool(frame["Force符号"] == side and (kind == "R" or upper["上位方向"] == side))
    event = watch["登録ID"] + f"_{'順行初端' if kind == 'T' else '反転確認'}_{frame['index']:04d}"
    row = {**{name: deepcopy(frame[name]) for name in NUMERIC_FIELDS}, "時間足分": 3, "入口系統": "Force失敗後の価格確認",
        "発動ID": event, "イベントID": event, "入口ID": "3分_Force失敗確認", "元登録ID": watch["登録ID"],
        "元価格side": watch["元価格side"], "元登録時計秒": watch["登録時計秒"], "元登録原板行": watch["登録原板行"],
        "登録足番号": watch["登録足番号"], "回復足番号": watch["回復足番号"], "回復時計秒": watch["回復時計秒"],
        "回復原板行": watch["回復原板行"], "回復ID": watch["回復ID"], "初期逆端": watch["初期逆端"], "再開端": watch["再開端"],
        **{name: deepcopy(watch[name]) for name in FAILURE_FIELDS},
        "年齢": frame["index"] - watch["登録足番号"], "価格区分": kind,
        "役割": "順行" if kind == "T" else "反転", "side": side, "方向": "買い" if side == 1 else "売り",
        **deepcopy(upper), "共通M準備": not missing, "M除外理由": missing, "技術方向可": direction_ok,
        "時間条件可": time_ok, "確認遅延条件可": delay_ok, "要求時計秒": now, "要求原板行": frame["confirm_line"],
        "足終了時計秒": frame["end"], "確認遅延秒": now - frame["end"], "期限時計秒": deadline,
        "残り分_判断時": (deadline - now) / 60, "先着評価対象": time_ok and delay_ok, "bb_mean": None}
    row["戦略判定"] = verdicts(row)
    row["判別種別"] = kind if any(value["採用"] for value in row["戦略判定"].values()) else "WAIT"
    return row


def fix_failure(frame: dict, watch: dict, upper: dict, stage: str, age: int) -> dict:
    """非注文の初回失敗fと後続確認に用いる端を一度だけ固定する。

    引数: frame/watch/upper(dict)は失敗足/区間監視/上位、stage(str)は回復前/後、age(int)はb年齢。
    返り値: dictは失敗出典を持つaction。watchの六属性と段階だけを更新する。
    """
    failure = watch["登録ID"] + f"_失敗_{frame['index']:04d}"
    data = (frame["index"], frame["confirm"], frame["confirm_line"], failure, stage,
        frame["low"] if watch["元価格side"] == 1 else frame["high"])
    watch.update(dict(zip(FAILURE_FIELDS, data, strict=True)))
    watch["段階"] = "反転確認待ち"
    return {"動作": "初回失敗固定", "登録ID": watch["登録ID"], "失敗ID": failure, "失敗段階": stage, "年齢": age,
        "失敗参照": {"足出典": price_source(frame), "Force2": deepcopy(frame["Force2"]), **deepcopy(upper)}}


def generate(frames: list[dict], higher15: list[dict], session: str,
             cutoff: float, deadline: float, config: dict) -> dict:
    """全cross候補を先に列挙し、受理bごとの先着区間走査で一監視を独立構築する。

    引数: frames(list[dict])は下位26列、higher15(list[dict])は上位15列、session(str)は場、
    cutoff/deadline(float)は停止/強制、config(dict)は終端時間条件。
    返り値: dictは全登録/監視/初端/二純候補。市場約定やPnLを計算しない。
    """
    rows = [{name: deepcopy(row[name]) for name in NUMERIC_FIELDS} for row in frames]
    uppers = [upper_projection(row) for row in higher15]
    if any(row["場"] != session or row["minutes"] != 15 for row in uppers) or len({row["index"] for row in uppers}) != len(uppers):
        raise ValueError("当場15分一意上位のみ")
    contexts, adjacent, valid, cancel = [], [], [], []
    key_before = None
    for index, row in enumerate(rows):
        previous = rows[index - 1] if index else None
        if row["場"] != session or row["minutes"] != 3 or previous is not None and row["index"] <= previous["index"]:
            raise ValueError("当場下位3分strict昇順のみ")
        if row["publish"] and (row["confirm"] < row["end"] or key_before is not None and key_of(row) <= key_before):
            raise ValueError("下位公開key同値/後退又は終了前公開")
        contexts.append(upper_state(uppers, row))
        adjacent.append(previous is None or previous["index"] + 1 == row["index"] and previous["end"] == row["start"])
        valid.append(bool(row["publish"] and not row["missing"] and price_valid(row)))
        reasons = []
        if not valid[-1]:
            reasons.append("完全公開3分価格不正")
        if not adjacent[-1]:
            reasons.append("価格番号又は終了非連続")
        if not row["Force2"]["有効"]:
            reasons.append("Force2未準備")
        if not contexts[-1]["上位現前準備"]:
            reasons.append("最新上位現前未準備")
        if row["confirm"] >= deadline:
            reasons.append("強制期限到達")
        cancel.append(reasons)
        if row["publish"]:
            key_before = key_of(row)
    actions = [[] for _ in rows]
    before, after = [None for _ in rows], [None for _ in rows]
    occupied = [False for _ in rows]
    registrations, records, ending = [], [], None
    for index, row in enumerate(rows):
        if not row["Force前"]["有効"] or not row["Force2"]["有効"]:
            continue
        current_force = Fraction(row["Force2"]["分子"], row["Force2"]["分母"])
        previous_force = Fraction(row["Force前"]["分子"], row["Force前"]["分母"])
        for side in (1, -1):
            if side * current_force >= 0 or side * previous_force < 0:
                continue
            reasons, previous = [], rows[index - 1] if index else None
            upper, prior = contexts[index], contexts[index - 1] if index else None
            if previous is None or not adjacent[index] or not valid[index]:
                reasons.append("登録の同場隣接価格未準備")
            if prior is None or not prior["上位現前準備"] or not upper["上位現前準備"]:
                reasons.append("登録p/b上位現前未準備")
            elif prior["上位方向"] != side or upper["上位方向"] != side:
                reasons.append("登録p/b背景D不一致")
            if occupied[index]:
                reasons.append("監視中又は同足で監視終了")
            if row["confirm"] >= deadline:
                reasons.append("登録強制期限以降")
            event = f"NK225_{session}_3分_Force失敗登録_{row['index']:04d}_{side}"
            registrations.append({"場": session, "登録ID": event, "元価格side": side, "登録足": frame_projection(row),
                "前足番号": previous["index"] if previous is not None else None, "前足Force": deepcopy(row["Force前"]),
                "登録Force": deepcopy(row["Force2"]), "前上位状態": deepcopy(prior), "登録上位状態": deepcopy(upper),
                "受理": not reasons, "登録除外理由": reasons})
            actions[index].append({"動作": "Force波登録不受理" if reasons else "Force波登録", "登録ID": event,
                "元価格side": side, "理由": list(reasons)})
            if reasons:
                continue
            watch = {"登録ID": event, "元価格side": side, "登録足番号": row["index"], "登録時計秒": row["confirm"],
                "登録原板行": row["confirm_line"], "初期逆端": row["low"] if side == 1 else row["high"],
                "段階": "回復待ち", "回復足番号": None, "回復時計秒": None, "回復原板行": None, "回復ID": None, "再開端": None,
                **{name: None for name in FAILURE_FIELDS}}
            after[index], occupied[index] = deepcopy(watch), True
            for offset in range(index + 1, len(rows)):
                frame, state = rows[offset], contexts[offset]
                occupied[offset], before[offset] = True, deepcopy(watch)
                age = frame["index"] - watch["登録足番号"]
                action = None
                if cancel[offset]:
                    action = {"動作": "監視取消", "登録ID": event, "年齢": age, "理由": deepcopy(cancel[offset])}
                elif age > 6:
                    action = {"動作": "寿命満了", "登録ID": event, "年齢": age, "理由": ["元bから6足超"]}
                else:
                    prefix = {"回復待ち": "登録", "価格待ち": "回復", "反転確認待ち": "失敗"}[watch["段階"]]
                    parent_time, parent_line = watch[prefix + "時計秒"], watch[prefix + "原板行"]
                    if frame["end"] <= parent_time or key_of(frame) <= (parent_time, parent_line):
                        actions[offset].append({"動作": "段階時点対象外", "登録ID": event, "年齢": age, "理由": ["親確認後の終了key未成立"]})
                    else:
                        failed = side * (Fraction(frame["close"]) - Fraction(watch["初期逆端"])) < 0
                        if watch["段階"] == "回復待ち":
                            if failed:
                                actions[offset].append(fix_failure(frame, watch, state, "回復前", age))
                            elif side * frame["Force符号"] > 0:
                                if state["上位方向"] != side:
                                    action = {"動作": "初回回復不一致WAIT", "登録ID": event, "年齢": age, "理由": ["初Force回復時の上位D不一致"]}
                                else:
                                    recovery = event + f"_回復_{frame['index']:04d}"
                                    watch.update(段階="価格待ち", 回復足番号=frame["index"], 回復時計秒=frame["confirm"],
                                        回復原板行=frame["confirm_line"], 回復ID=recovery, 再開端=frame["high"] if side == 1 else frame["low"])
                                    actions[offset].append({"動作": "初回回復固定", "登録ID": event, "回復ID": recovery, "年齢": age,
                                        "回復参照": {"足出典": price_source(frame), "Force2": deepcopy(frame["Force2"]), **deepcopy(state)}})
                        elif watch["段階"] == "価格待ち":
                            resumed = side * (Fraction(frame["close"]) - Fraction(watch["再開端"])) > 0
                            if failed:
                                actions[offset].append(fix_failure(frame, watch, state, "回復後", age))
                            elif resumed:
                                record = event_row(frame, watch, state, "T", cutoff, deadline, config)
                                records.append(record)
                                action = {"動作": "順行初端消費", "登録ID": event, "発動ID": record["発動ID"],
                                    "年齢": age, "価格区分": "T", "判別種別": record["判別種別"]}
                        else:
                            reclaimed = side * (Fraction(frame["close"]) - Fraction(watch["初期逆端"])) >= 0
                            confirmed = -side * (Fraction(frame["close"]) - Fraction(watch["失敗確認端"])) > 0
                            if reclaimed:
                                action = {"動作": "失敗後元逆端回復取消", "登録ID": event, "失敗ID": watch["失敗ID"],
                                    "年齢": age, "理由": ["失敗後に元逆端を終値回復又は等号"]}
                            elif confirmed:
                                record = event_row(frame, watch, state, "R", cutoff, deadline, config)
                                records.append(record)
                                action = {"動作": "反転初確認消費", "登録ID": event, "発動ID": record["発動ID"],
                                    "失敗ID": watch["失敗ID"], "年齢": age, "価格区分": "R", "判別種別": record["判別種別"]}
                if action is not None:
                    actions[offset].append(action)
                    watch = None
                    break
                after[offset] = deepcopy(watch)
            if watch is not None:
                ending = deepcopy(watch)
    if ending is not None:
        actions[-1].append({"動作": "場末監視取消", "登録ID": ending["登録ID"], "理由": ["場末"]})
        after[-1] = None
    trace = [{"場": session, "index": row["index"], "足出典": price_source(row), "Force2": deepcopy(row["Force2"]),
        "上位参照足番号": contexts[n]["上位参照"]["index"] if contexts[n]["上位参照"] is not None else None,
        "前上位参照足番号": contexts[n]["前上位参照"]["index"] if contexts[n]["前上位参照"] is not None else None,
        "上位現前準備": contexts[n]["上位現前準備"], "上位除外理由": deepcopy(contexts[n]["上位除外理由"]),
        "上位方向": contexts[n]["上位方向"], "上位EMA現前準備": contexts[n]["上位EMA現前準備"],
        "上位EMA差符号": contexts[n]["上位EMA差符号"], "上位Impulse方向": contexts[n]["上位Impulse方向"],
        "監視前": before[n], "動作": actions[n], "監視後": after[n]} for n, row in enumerate(rows)]
    competing = defaultdict(list)
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                competing[policy, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), same in competing.items():
        if len(same) > 1:
            for row in same:
                row["戦略判定"][policy] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    signals = {"3分_" + policy: [] for policy in POLICIES}
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                signals["3分_" + policy].append({**deepcopy(row), "イベントID": row["発動ID"] + "_" + policy,
                    "入口ID": "3分_" + policy, "戦略": policy, "複合判定": deepcopy(row["戦略判定"][policy])})
    counts = Counter(action["動作"] for item in trace for action in item["動作"])
    quality = {"場": session, "時間足分": 3, "入力足数": len(rows), "Force逆行cross候補数": len(registrations),
        "監視受理数": sum(row["受理"] for row in registrations), "初回回復数": counts["初回回復固定"],
        "初価格端数": len(records), "初回失敗数": counts["初回失敗固定"],
        "失敗段階別": dict(Counter(action["失敗段階"] for item in trace for action in item["動作"] if action["動作"] == "初回失敗固定")),
        "価格区分別": dict(Counter(row["価格区分"] for row in records)),
        "判別種別": dict(Counter(row["判別種別"] for row in records)), "監視動作別": dict(counts),
        "場末残監視取消数": int(ending is not None), "終了時監視残数": 0,
        "先着評価対象外数": sum(not row["先着評価対象"] for row in records),
        "戦略別発動数": {sid: len(items) for sid, items in signals.items()},
        "戦略採否理由別": {p: dict(Counter(reason for row in records for reason in row["戦略判定"][p]["理由"])) for p in POLICIES}}
    metadata = {row["発動ID"]: {name: deepcopy(row[name]) for name in METADATA_FIELDS} for row in records}
    return {"場": session, "frames": {3: rows, 15: uppers}, "signals": signals, "raw": records, "decisions": records,
        "registrations": registrations, "monitor_trace": trace, "metadata": metadata, "quality": quality}


# ----------------------------------------
# 出典/準備/正式の結合。市場CLIの起動はrootのみ。

def read_definition(work: Path, master: dict, audit: Audit) -> dict[str, dict[int, dict]]:
    """主準備が保存した上位H/EMAの四列定義を全行構造まで検査する。

    引数: work(Path)は48作業先、master(dict)は主準備、audit(Audit)は比較先。
    返り値: dictは場→index→4列定義。独立H/EMAをこれで計算し直さない。
    """
    info = master["上位数値定義"]
    audit.check("上位H/EMA定義参照keys", set(info), {"パス", "圧縮SHA256参考", "展開内容SHA256", "行数"})
    if set(info) != {"パス", "圧縮SHA256参考", "展開内容SHA256", "行数"}:
        raise ValueError("上位H/EMA定義参照keys不一致")
    path = (ROOT / info["パス"]).resolve()
    audit.check("上位H/EMA定義保存先", path, (work / "上位数値定義.jsonl.gz").resolve())
    if path != (work / "上位数値定義.jsonl.gz").resolve():
        raise ValueError("上位H/EMA定義の保存先範囲差")
    audit.check("上位H/EMA定義圧縮SHA", V.sha(path), info["圧縮SHA256参考"])
    if audit.mismatches:
        raise ValueError("上位H/EMA定義圧縮指紋に差があり展開前停止")
    rows, digest = [], hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            rows.append(json.loads(raw))
    audit.check("上位H/EMA定義展開SHA", digest.hexdigest(), info["展開内容SHA256"])
    audit.check("上位H/EMA定義行数", len(rows), info["行数"])
    sessions = [row["場"] for row in master["準備"]]
    output, order = defaultdict(dict), []
    for row in rows:
        valid = (isinstance(row, dict) and set(row) == {"場", "index", "macd_hist", "ema13_centered"} and row["場"] in sessions
                 and type(row["index"]) is int and row["index"] >= 0
                 and all(row[name] is None or finite(row[name]) for name in ("macd_hist", "ema13_centered")))
        audit.check("上位H/EMA定義行構造", valid, True)
        if not valid:
            raise ValueError("上位H/EMA定義に想定外の属性・数値がある")
        key = row["場"], row["index"]
        audit.check("上位H/EMA定義足一意:" + str(key), row["index"] not in output[row["場"]], True)
        output[row["場"]][row["index"]] = row
        order.append(key)
    audit.check("上位H/EMA定義全行昇順", order == sorted(order), True)
    expected = [(row["場"], row["上位足数"]) for row in master["準備"]]
    audit.check("上位H/EMA定義場別全足数", [(session, len(output[session])) for session in sessions], expected)
    if audit.mismatches:
        raise ValueError("小型上位H/EMA定義・主準備の出典に差がありcache前停止")
    return dict(output)


def dependency_pins() -> dict:
    """固定独立足・中心化MACD・直接先着・追尾の全依存を識別する。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathと現在SHA。48主コードを数式依存にしない。
    """
    paths = {"scripts/実体包み/状態独立確認.py", str(Path(G.Q.__file__).resolve().relative_to(ROOT)).replace(chr(92), "/"), "scripts/回帰突破/状態独立確認.py", "scripts/発動値幅継続/状態独立確認.py", "scripts/OBV反転/状態独立確認.py",
        "scripts/終値位置/追尾独立確認.py"}
    return dict(sorted({**Y.dependency_pins(), **{name: V.sha(ROOT / name) for name in paths}}.items()))


def shared_bundle(audit: Audit) -> dict:
    """下位ATR/Qと上位OHLCだけを二つの旧正本から共有する。

    引数: audit(Audit)は圧縮/展開の指紋照合先。
    返り値: dictは下位15列/上位13列と両出典SHA。旧H/入口/先着を共有しない。
    """
    lower_rows, lower_sha = saved_rows(INDICATOR_STUDY, INDICATOR_WORK, "全指標.jsonl.gz", audit)
    upper_rows, upper_sha = saved_rows(UPPER_STUDY, UPPER_WORK, "全指標.jsonl.gz", audit)
    lower, higher = defaultdict(list), defaultdict(list)
    for row in lower_rows:
        if row["minutes"] == 3:
            lower[row["場"]].append(frame_projection(row))
    for row in upper_rows:
        if row["minutes"] == 15:
            higher[row["場"]].append(price_source(row))
    return {"lower": dict(lower), "upper_source": dict(higher),
        "共有3分全指標展開SHA256": lower_sha, "共有15分価格元明細展開SHA256": upper_sha}


def references(study: Path, audit: Audit) -> None:
    """48の二参照を旧29数値と旧28価格へ、全正本証明まで固定する。

    引数: study(Path)は48、audit(Audit)は比較先。
    返り値: None。旧入口や旧labelの共有を要求しない。
    """
    for filename, source, anchor, trial in (
            ("指標参照.json", INDICATOR_STUDY, "353143ea3f7a626736bf44551d17ba6e22b8bfd76ee40e2f4f9b0c190736f48a", "00029"),
            ("上位参照.json", UPPER_STUDY, "24169522b4245c77c32a36e709322de841a7a6a7e8aa0faf0b21968676cf5801", "00028")):
        audit.check(filename + ":固定正本", V.sha(source / "固定.json"), anchor)
        for name, digest in V.read(source / "固定.json")["ファイルSHA256"].items():
            audit.check(filename + ":旧固定現在:" + name, V.sha(ROOT / name), digest)
        ref = V.read(study / filename)
        audit.check(filename + ":参照試行", ref["参照試行"], trial)
        audit.check(filename + ":旧固定", ref["旧固定SHA256"], anchor)
        audit.check(filename + ":複製なし", ref["大明細複製"], False)
        expected_names = {"固定.json", "条件.json", "結果.json", "作業成果物.json", "独立監査.json",
            "状態独立確認.json", "追尾独立確認.json", "入力台帳.json"}
        audit.check(filename + ":全証明集合", set(ref["文書と証明"]), expected_names)
        for name, item in ref["文書と証明"].items():
            audit.check(filename + ":正本path:" + name, (ROOT / item["パス"]).resolve(), (source / name).resolve())
            audit.check(filename + ":正本SHA:" + name, item["SHA256"], V.sha(source / name))
        for name in ("独立監査.json", "状態独立確認.json", "追尾独立確認.json"):
            proof = V.read(source / name)
            audit.check(filename + ":旧証明成功:" + name, (proof["全件一致"], proof["不一致数"]), (True, 0))
        expected = [row for row in V.read(source / "作業成果物.json")["ファイル"] if Path(row["パス"]).name == "全指標.jsonl.gz"]
        audit.check(filename + ":共有明細集合", ref["共有明細"], expected)
        for item in expected:
            audit.check(filename + ":明細圧縮SHA", V.sha(ROOT / item["パス"]), item["圧縮SHA256参考"])
            audit.check(filename + ":明細bytes", (ROOT / item["パス"]).stat().st_size, item["圧縮バイト"])


def define_lower(independent: list[dict], shared: list[dict]) -> list[dict]:
    """生の数量/SOURCEを残し、共有正本ATRだけを別配列へ置く。

    引数: independent/shared(list[dict])は独立/旧29の下位15列。
    返り値: list[dict]はATRだけの非改変overlay。場/index一対一を要求する。
    """
    original = {row["index"]: row for row in shared}
    indices = [row["index"] for row in independent]
    if len(original) != len(shared) or len(indices) != len(set(indices)) or set(indices) != set(original):
        raise ValueError("下位原足とATR定義の全足対応に差")
    if any(row["場"] != original[row["index"]]["場"] for row in independent):
        raise ValueError("下位定義の場に差")
    return [{**deepcopy(row), "atr": deepcopy(original[row["index"]]["atr"])} for row in independent]


def define_upper(independent: list[dict], definition: dict[int, dict]) -> list[dict]:
    """生の上位SOURCEを残し、新正本H/EMAだけを別配列へ置く。

    引数: independent(list[dict])は独立生15列、definition(dict[int,dict])は検査済み4列定義。
    返り値: list[dict]はH/EMAだけの非改変overlay。場/index一対一を要求する。
    """
    indices = [row["index"] for row in independent]
    if len(indices) != len(set(indices)) or set(indices) != set(definition):
        raise ValueError("上位原足と新H/EMA定義の全足対応に差")
    if any(row["場"] != definition[row["index"]]["場"] for row in independent):
        raise ValueError("上位定義の場に差")
    return [{**deepcopy(row), **{name: deepcopy(definition[row["index"]][name])
        for name in ("macd_hist", "ema13_centered")}} for row in independent]


def judgment_projection(value: Any) -> Any:
    """限定許容値を準備/方向へ射影し、Force/Q/全時計を厳密に残す。

    引数: value(Any)は全数値/全状態/純信号。
    返り値: Anyは厳密判断JSON。H水準正負を隠れた要件にしない。
    """
    if isinstance(value, dict):
        output = {}
        for name, item in value.items():
            if name == "atr":
                positive = finite(item) and item > 0
                output["ATR判断"] = {"正有効": positive, "D整数": max(5, math.ceil(item / 5) * 5) if positive else None}
            elif name in ("macd_hist", "上位ヒスト現", "上位ヒスト前", "ema13_centered", "上位EMA現", "上位EMA前"):
                output[name] = {"有限": True} if finite(item) else deepcopy(item)
            elif name in ("上位ヒスト差", "上位EMA差"):
                output[name] = {"有限": True, "方向": (item > 0) - (item < 0)} if finite(item) else deepcopy(item)
            else:
                output[name] = judgment_projection(item)
        return output
    if isinstance(value, list):
        return [judgment_projection(item) for item in value]
    return deepcopy(value)


def compare_numeric_scope(name: str, defined: Any, independent: Any, audit: Audit) -> bool:
    """値だけの限定許容と全非許容属性/方向/採否strictを別々に要求する。

    引数: name(str)は範囲、defined/independent(Any)は正本定義/生経路、audit(Audit)は比較先。
    返り値: boolは判断射影同値。値の許容超過も別に不一致へ残す。
    """
    audit.check(name + ":限定数値と全属性", defined, independent)
    same = canonical_sha(judgment_projection(defined)) == canonical_sha(judgment_projection(independent))
    audit.check(name + ":全方向準備採否/非許容値strict", same, True)
    return same


def reconstruct(manifest: dict, bundle: dict, config: dict) -> Any:
    """原8列から二尺度/Qを別算し、正本数値と生数値の二監視を構築する。

    引数: manifest/bundle/config(dict)は固定66入力/共有定義/事前条件。
    返り値: Anyは場別iterator。ラベル/実運用/PnLは計算しない。
    """
    lower_bank, upper_bank = NumericHistory(3), UpperHistory()
    for entry in manifest["entries"]:
        session, contract = entry["session"], tuple(entry["in_session_contract_codes"])
        start, finish, cutoff, deadline = S.G.times(session)
        data = G.observed(entry, manifest)
        formed3 = S.bars(data, session, 3, N.BareBars())
        formed15 = S.bars(data, session, 15, N.BareBars())
        quantity, quantity_quality = G.quantities(data, formed3, start, finish)
        tail3 = max(0, int((finish - start) // 180) - 1 - (formed3[-1]["index"] if formed3 else -1))
        tail15 = max(0, int((finish - start) // 900) - 1 - (formed15[-1]["index"] if formed15 else -1))
        numeric3, bank_quality = lower_bank.build(formed3, session, contract, tail3)
        raw_lower = [{"場": session, **{name: deepcopy(row[name]) for name in SOURCE_FIELDS},
            "atr": row["atr"], "数量参照": deepcopy(quantity.get(row["index"]))} for row in numeric3]
        raw_upper, upper_quality = upper_bank.build(formed15, session, contract, tail15)
        defined_lower = define_lower(raw_lower, bundle["lower"][session])
        defined_upper = define_upper(raw_upper, bundle["upper_definition"].get(session, {}))
        local_defined, quality = build_local(defined_lower, session)
        local_raw, raw_quality = build_local(raw_lower, session)
        selected = generate(local_defined, defined_upper, session, cutoff, deadline, config)
        alternate = generate(local_raw, raw_upper, session, cutoff, deadline, config)
        pure = [pure_signal(row, p) for p in POLICIES for row in selected["signals"]["3分_" + p]]
        period = "学習" if session[:10] < config["分割"]["選択開始日"] else ("条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in pure]),
            "判定": selected["decisions"], "判定SHA256": canonical_sha(selected["decisions"]), "判定判断SHA256": canonical_sha(selected["decisions"]),
            "全3分投影SHA256": canonical_sha(defined_lower), "3分投影足数": len(defined_lower), "入力品質": selected["quality"],
            "全指標内容SHA256": canonical_sha(local_defined), "全指標足数": len(local_defined), "数値品質": quality,
            "全15分価格投影SHA256": canonical_sha([price_source(row) for row in raw_upper]), "15分価格足数": len(raw_upper),
            "全上位内容SHA256": canonical_sha(defined_upper), "上位足数": len(defined_upper),
            "登録判定SHA256": canonical_sha(selected["registrations"]), "登録候補数": len(selected["registrations"]),
            "監視SHA256": canonical_sha(selected["monitor_trace"]), "監視足数": len(selected["monitor_trace"]), "上位数値品質": upper_quality,
            "_再算全3分": raw_lower, "_正本全3分": defined_lower, "_再算上位": raw_upper, "_正本上位": defined_upper,
            "_正本全指標": local_defined, "_再算全指標": local_raw, "_正本判断": selected, "_再算判断": alternate,
            "_局所生品質": raw_quality, "_数量品質": quantity_quality, "_原足銀行品質": bank_quality}


def compare_preparation(master: dict, block: dict, bundle: dict, audit: Audit) -> dict:
    """全二尺度・原数量・監視と全採否を正本整合/生数値影響で別照合する。

    引数: master/block/bundle(dict)は主場/独立場/共有、audit(Audit)は比較先。
    返り値: dictは全登録/初端/二集合と数値表現差。H生SHA差を採否差にしない。
    """
    session = block["場"]
    audit.check(session + ":原8列下位SOURCE/ATR/Q14", block["_再算全3分"], bundle["lower"][session])
    audit.check(session + ":原8列15分OHLC", [price_source(row) for row in block["_再算上位"]], bundle["upper_source"][session])
    expected = {name: value for name, value in block.items() if not name.startswith("_")}
    audit.check(session + ":主23keys正本定義", master, expected)
    audit.check(session + ":主全値厳密JSON", master == expected, True)
    valid = compare_numeric_scope(session + ":全Force26と原数量", block["_正本全指標"], block["_再算全指標"], audit)
    valid &= compare_numeric_scope(session + ":全上位15値", block["_正本上位"], block["_再算上位"], audit)
    selected, alternate = block["_正本判断"], block["_再算判断"]
    for name in ("decisions", "registrations", "monitor_trace", "metadata", "quality"):
        valid &= compare_numeric_scope(session + ":生数値による全状態:" + name, selected[name], alternate[name], audit)
    raw_pure = [pure_signal(row, p) for p in POLICIES for row in alternate["signals"]["3分_" + p]]
    valid &= compare_numeric_scope(session + ":生数値による全純13", block["純信号"], raw_pure, audit)
    audit.check(session + ":Force局所品質", block["_局所生品質"], block["数値品質"])
    ids = {p: {row["イベントID"][:-3] for row in block["純信号"] if row["入口ID"] == "3分_" + p} for p in POLICIES}
    originals = {row["発動ID"]: row for row in block["判定"]}
    for policy in POLICIES:
        audit.check(session + ":切替内T/R非交差:" + policy,
            not ({event for event in ids[policy] if originals[event]["価格区分"] == "T"} &
                 {event for event in ids[policy] if originals[event]["価格区分"] == "R"}), True)
    kinds = {(p, kind): {event for event in ids[p] if originals[event]["価格区分"] == kind}
        for p in POLICIES for kind in ("T", "R")}
    audit.check(session + ":二切替の純T同値", kinds["S0", "T"], kinds["S1", "T"])
    audit.check(session + ":上位D反転Rは禁止不在Rの部分集合", kinds["S0", "R"] <= kinds["S1", "R"], True)
    failures = {action["失敗ID"]: action for item in selected["monitor_trace"] for action in item["動作"]
        if action["動作"] == "初回失敗固定"}
    audit.check(session + ":失敗固定は非注文", not (set(failures) & set(originals)), True)
    for event, record in originals.items():
        audit.check(event + ":元b寿命内", 0 < record["年齢"] <= 6, True)
        audit.check(event + ":当足要求時計", (record["要求時計秒"], record["要求原板行"]),
            (record["confirm"], record["confirm_line"]))
        if record["価格区分"] == "T":
            audit.check(event + ":順行に失敗出典を転用しない", all(record[name] is None for name in FAILURE_FIELDS), True)
        else:
            audit.check(event + ":一意に保存済みの失敗f", record["失敗ID"] in failures, True)
            audit.check(event + ":kはf確認後終了key", record["end"] > record["失敗時計秒"] and
                (record["要求時計秒"], record["要求原板行"]) > (record["失敗時計秒"], record["失敗原板行"]), True)
            audit.check(event + ":kはfと別足", record["index"] > record["失敗足番号"], True)
    roles = Counter()
    for signal in block["純信号"]:
        p = signal["入口ID"].removeprefix("3分_")
        audit.check(signal["イベントID"] + ":純13列", set(signal), set(SIGNAL_FIELDS))
        audit.check(signal["イベントID"] + ":全純13値厳密", signal == pure_signal(originals[signal["イベントID"][:-3]], p), True)
        audit.check(signal["イベントID"] + ":実四役割", (p, signal["役割"]) in ROLE_PAIRS, True)
        roles[p, signal["役割"]] += 1
    differences = {}
    for name, raw, defined in (("atr", block["_再算全3分"], block["_正本全3分"]),
            ("macd_hist", block["_再算上位"], block["_正本上位"]),
            ("ema13_centered", block["_再算上位"], block["_正本上位"])):
        differences[name] = [abs(a[name] - b[name]) for a, b in zip(raw, defined, strict=True)
            if finite(a[name]) and finite(b[name]) and a[name] != b[name]]
    return {"場": session, "期間": block["期間"], **{p + "登録数": len(ids[p]) for p in POLICIES},
        "初価格端数": len(block["判定"]), "登録候補数": block["登録候補数"],
        "監視受理数": selected["quality"]["監視受理数"], "回復数": selected["quality"]["初回回復数"],
        "失敗固定数": len(failures), "回復前失敗数": selected["quality"]["失敗段階別"].get("回復前", 0),
        "回復後失敗数": selected["quality"]["失敗段階別"].get("回復後", 0),
        "順行初端数": sum(row["価格区分"] == "T" for row in block["判定"]),
        "反転初確認数": sum(row["価格区分"] == "R" for row in block["判定"]),
        "3分投影足数": block["3分投影足数"], "上位足数": block["上位足数"],
        "実役割別登録": [{"戦略": p, "役割": role, "件数": roles[p, role]} for p, role in ROLE_PAIRS],
        **{name + "表現差足数": len(values) for name, values in differences.items()},
        **{name + "最大絶対差": max(values, default=0.0) for name, values in differences.items()},
        "再算数値判断不一致場": int(not valid), "正本全上位内容SHA256": block["全上位内容SHA256"],
        "独立生全上位内容SHA256": canonical_sha(block["_再算上位"]), "独立生全監視内容SHA256": canonical_sha(alternate["monitor_trace"])}


def numeric_summary(stages: list[dict]) -> dict:
    """二尺度/全登録/初端と限定表現差・strict判断差を分離集計する。

    引数: stages(list[dict])は全場準備要約。
    返り値: dictは原足数/登録/回復/初端と生値の差分。
    """
    return {"新3分全数値照合足数": sum(row["3分投影足数"] for row in stages),
        "新15分全数値照合足数": sum(row["上位足数"] for row in stages),
        "初価格端数": sum(row["初価格端数"] for row in stages), "全Forcecross候補数": sum(row["登録候補数"] for row in stages),
        "全監視受理数": sum(row["監視受理数"] for row in stages), "全回復数": sum(row["回復数"] for row in stages),
        **{"全" + name: sum(row[name] for row in stages) for name in
            ("失敗固定数", "回復前失敗数", "回復後失敗数", "順行初端数", "反転初確認数")},
        "独立数値判断不一致場数": sum(row["再算数値判断不一致場"] for row in stages),
        **{"独立" + name + "表現差足数": sum(row[name + "表現差足数"] for row in stages) for name in ("atr", "macd_hist", "ema13_centered")},
        **{"独立" + name + "最大絶対差": max((row[name + "最大絶対差"] for row in stages), default=0.0) for name in ("atr", "macd_hist", "ema13_centered")}}


def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """非損益主準備と二案・費用・入力・使用数値版を市場入力前に照合する。

    引数: study/work(Path)は48保存先、audit(Audit)は比較先。
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
    audit.check("二入口", config["戦略"], list(POLICIES))
    audit.check("二XF", config["運用組合せ"], [{"戦略": p, "出口ID": "XF"} for p in POLICIES])
    master = V.read(work / "準備点検.json")
    expected = {"ラベル計算": False, "損益計算": False, "全66場既使用": True,
        "条件SHA256": V.sha(study / "条件.json"), "入力台帳SHA256": V.sha(study / "入力台帳.json"),
        "参照台帳SHA256": V.sha(resolved), "純信号whitelist": list(SIGNAL_FIELDS),
        "指標参照SHA256": V.sha(study / "指標参照.json"), "上位参照SHA256": V.sha(study / "上位参照.json")}
    for name, value in expected.items():
        audit.check("主準備:" + name, master[name], value)
    paths = {"scripts/Force失敗確認/" + name for name in ("検証.py", "入口.py", "指標.py", "運用.py")}
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
        "指標参照SHA256": V.sha(study / "指標参照.json"), "上位参照SHA256": V.sha(study / "上位参照.json"),
        "上位数値定義": deepcopy(master["上位数値定義"]),
        "厳密範囲": "原8列SOURCE/全Q14/Force全分数/全cross登録/一監視/全採否/時点/純13はstrict。3分ATRは値abs1e-10+正/D整数strict。新上位H/EMA水準は有限準備strictと値abs1e-10、水準符号を要件に足さず、差の方向D/E・ImpulseIと全採否はstrict。正本定義overlayの全SHAと生数値SHAは別責任。",
        "数値許容": {"対象": ["atr", "macd_hist", "上位ヒスト現", "上位ヒスト前", "上位ヒスト差",
                "ema13_centered", "上位EMA現", "上位EMA前", "上位EMA差"], "絶対許容": 1e-10, "相対許容": 0,
            "採否epsilon": False, "正本定義SHAと独立生数値SHAを区別": True},
        "上位数値照合統計": deepcopy(audit.hist_stats), "上位D厳密符号不一致数": audit.direction_differences,
        "上位E厳密符号不一致数": audit.ema_direction_differences}


def prepare(study: Path, work: Path) -> dict:
    """root起動の非損益準備で全原足/数値/非注文fとT-k要求の二切替を検算する。

    引数: study/work(Path)は48保存先。
    返り値: dictはラベル・運用・PnL計算を呼ばない独立準備証明。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    bundle, stages = shared_bundle(audit), []
    bundle["upper_definition"] = read_definition(work, master, audit)
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        print(json.dumps({"場": block["場"], "独立準備": "原3/15分ATR/Q/H/EMA・精密Force・失敗後確認の区間走査", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "全66場既使用": True, "場別準備": stages, **numeric_summary(stages),
        "方針別登録数": {p: sum(r[p + "登録数"] for r in stages) for p in POLICIES},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "検証範囲": "原8列から3分OHLC/ATR/Q14と15分OHLC/中心化H/EMA13を別算。Forceの指数重み和と受理bの区間走査で全cross/全監視/全初端/二純13を構築。正本floatのSHA整合と生値の上位差方向D/E/ImpulseI/Force符号/全準備採否strictを分け、H水準符号の一致を追加要求しない。",
        "限界": "非先着/非運用/非PnL。旧29は下位ATR/Q、旧28は15分OHLCだけを共有し、旧H/旧入口/旧先着/旧全属性対照は流用しない。全66場既使用。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "初価格端数", "方針別登録数")}, ensure_ascii=False))
    return proof


def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """成功した独立準備と全固定指紋を正式市場入力前に要求する。

    引数: study/work/resolved(Path)は保存/台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: None。古版・未完・差ありは停止する。
    """
    prepared, expected = V.read(work / "独立準備点検.json"), proof_base(study, work, resolved, master, audit)
    for key in ("コードSHA256", "追尾コードSHA256", "依存コードSHA256", "主準備SHA256", "主コードSHA256",
            "条件SHA256", "入力台帳SHA256", "参照入力台帳SHA256", "指標参照SHA256", "上位参照SHA256", "上位数値定義"):
        audit.check("準備bind:" + key, prepared[key], expected[key])
    for key, value in {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False}.items():
        audit.check("準備成功:" + key, prepared[key], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("準備/固定/現版に差があり正式市場入力前停止")


def run(study: Path, work: Path) -> dict:
    """正式後だけ原二尺度と精密Force波・全採否と全caseのT端/k要求後の直接先着を照合する。

    引数: study/work(Path)は48正式/作業先。
    返り値: dictは七系列の状態証明。受付/約定/Decimalと全実保有は別証明へ結ぶ。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    bundle = shared_bundle(audit)
    bundle["upper_definition"] = read_definition(work, master, audit)
    names = ("全指標", "上位15分", "価格状態", "発動判定", "入口事例", "全運用詳細", "追尾")
    saved, hashes, grouped = {}, {}, {name: defaultdict(list) for name in names}
    for name in names:
        saved[name], hashes[name] = saved_rows(study, work, name + ".jsonl.gz", audit)
        for row in saved[name]:
            grouped[name][row["場"]].append(row)
    artifact_names = {Path(row["パス"]).name for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新七成果物集合", artifact_names, {name + ".jsonl.gz" for name in names})
    pairs = [(row["場"], row["候補ID"]) for row in saved["全運用詳細"]]
    audit.check("全場候補一意", len(pairs), len(set(pairs)))
    audit.check("全2x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in OPERATIONS})
    audit.check("全case一意", len(saved["入口事例"]), len({row["イベントID"] for row in saved["入口事例"]}))
    if audit.mismatches:
        raise ValueError("正式保存物の集合/指紋に差があり原足入力前停止")
    stages, counts, role_counts = [], Counter({p: 0 for p in POLICIES}), Counter()
    entries = {entry["session"]: entry for entry in manifest["entries"]}
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        session, period, selected = block["場"], block["期間"], block["_正本判断"]
        expected_numeric = [{"期間": period, **row} for row in block["_正本全指標"]]
        expected_upper = [{"期間": period, **row} for row in block["_正本上位"]]
        expected_states = [{"種別": kind, "期間": period, **row} for kind, rows in
            (("登録", selected["registrations"]), ("監視", selected["monitor_trace"])) for row in rows]
        expected_decisions = [{"期間": period, **row} for row in block["判定"]]
        for name, expected in (("全指標", expected_numeric), ("上位15分", expected_upper), ("価格状態", expected_states), ("発動判定", expected_decisions)):
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
        print(json.dumps({"場": session, "独立状態": "原8列3/15/Q・精密Force・全監視・全新case直接先着",
                          "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 2, "運用候補数": 2, "現方針運用候補数": 2,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    audit.check("正式二候補順", [row["候補ID"] for row in result["結果"]], list(OPERATIONS))
    audit.check("全case数", len(saved["入口事例"]), sum(counts.values()))
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages, **numeric_summary(stages),
        "方針別case数": dict(counts), "全先着直接照合件数": sum(counts.values()), "方針別先着直接照合件数": dict(counts),
        "役割別先着直接照合件数": [{"戦略": p, "役割": role, "件数": role_counts[(p, role)]}
            for p, role in ROLE_PAIRS],
        "保存全指標数": len(saved["全指標"]), "保存上位15分数": len(saved["上位15分"]),
        "保存価格状態数": len(saved["価格状態"]),
        "保存発動判定数": len(saved["発動判定"]), "保存入口事例数": len(saved["入口事例"]),
        "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "上位数値照合統計": audit.hist_stats, "上位D厳密符号不一致数": audit.direction_differences,
        "上位E厳密符号不一致数": audit.ema_direction_differences,
        "検証範囲": "原8列から下位OHLC/ATR/観測Q14と上位OHLC/新中心化H/EMA13を別算し、Force指数重み和と受理bの区間走査で全登録/監視/失敗f/後続k/二採否/純13を別構築。全新caseはT端/反転確認k要求後の最初+1秒正常BBOから125/250/空白/期限を実sideで直接走査。定義数値の全SHA整合と独立生数値の全準備/符号/採否strictを分離。",
        "限界": "旧29は下位ATR/Q、旧28は15分OHLCのみ。旧上位Hは流用しない。旧入口/旧先着/旧全属性対照は流用しない。実新規受付/最初BBO/Decimalは別会計、全保有と最初返済要求は別追尾。全66場既使用。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "方針別case数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root許可による非損益準備又は固定後正式検算を明示起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定・不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00048上位方向と精密Force波の独立検算")
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
