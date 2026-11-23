"""00042の原足・数量・固定再テスト監視とCMF方向を独立検算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00042_突破再テストと数量加重終値位置"
WORK = ROOT / "work/再テスト量方向/00042"
INDICATOR_STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
INDICATOR_WORK = ROOT / "work/OBV反転/00029"
EXIT_STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
POLICIES = ("A0", "A1", "A2")
OPERATIONS = tuple("3分_" + policy + "_XF" for policy in POLICIES)


def helper(path: Path, name: str) -> Any:
    """既固定の独立足・数値・数量・先着補助だけを読み込む。

    引数: path(Path)は固定独立コード、name(str)は読込名。
    返り値: Anyは補助。42主入口・主運用・主指標はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(ROOT / "scripts/回帰突破/状態独立確認.py", "再テスト量方向の固定独立原足と数値")
G, N, S, V = Y.G, Y.N, Y.S, Y.V
Audit = G.Audit
SIGNAL_FIELDS, LABEL_FIELDS, SOURCE_FIELDS = Y.SIGNAL_FIELDS, Y.LABEL_FIELDS, Y.SOURCE_FIELDS
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr", "macd_hist", "数量参照")
canonical_sha, decision_signal, finite, exact = Y.canonical_sha, Y.decision_signal, Y.finite, Y.exact
normal_columns, label_direct = Y.normal_columns, Y.label_direct


def frame_projection(row: dict | None) -> dict | None:
    """3分出典・ATR/H・監査済み数量属性だけを限定射影する。

    引数: row(dict|None)は原数値と数量属性。
    返り値: dict|Noneは16列。OBV/旧BB/旧case/未来jを含めない。
    """
    if row is not None and row["minutes"] != 3:
        raise ValueError("再テストは3分足だけです")
    return None if row is None else {key: deepcopy(row[key]) for key in FRAME_FIELDS}


class NumericHistory(Y.NumericHistory):
    """固定独立ATR/Hに、別走査の原数量属性を添付する最小銀行。"""

    def build(self, frames: list[dict], session: str, contract: tuple,
              tail_missing: int = 0, quantities: dict | None = None) -> tuple[list[dict], dict]:
        """原OHLCと原累積列から別算した数量を同じ出典番号へ結ぶ。

        引数: frames(list[dict])は原足、session(str)は場、contract(tuple)は限月、
        tail_missing(int)は尾部欠枠、quantities(dict|None)は固定14独立数量。
        返り値: tuple[list[dict],dict]は16列と数値銀行品質。量不完全でATR/Hを解除しない。
        """
        rows, quality = super().build(frames, session, contract, tail_missing)
        for row in rows:
            row["数量参照"] = deepcopy((quantities or {}).get(row["index"]))
        return rows, quality


def cmf_fraction(rows: list[dict]) -> Fraction | None:
    """21足を直接走査し、足内終値位置の量加重平均を分数で求める。

    引数: rows(list[dict])は古い順の21公開完全足と全数量属性。
    返り値: Fraction|NoneはCMF。零幅・量不完全・総量0・本数不足は未定義。
    """
    if len(rows) != 21:
        return None
    total, weighted = Fraction(0), Fraction(0)
    for row in rows:
        quantity = row.get("数量参照")
        q = quantity.get("観測差分量") if quantity is not None else None
        if (not row["publish"] or row["missing"] or not N.valid_ohlc(row)
                or row["end"] - row["start"] != 180 or row["confirm"] < row["end"]
                or quantity is None or not quantity.get("数量基準完全") or not finite(q) or q < 0):
            return None
        high, low, close = (Fraction(row[name]) for name in ("high", "low", "close"))
        if high == low:
            return None
        volume = Fraction(q)
        multiplier = ((close - low) - (high - close)) / (high - low)
        total += volume
        weighted += multiplier * volume
    return weighted / total if total > 0 else None


def source(row: dict) -> dict:
    """価格出典だけを深複写して数値銀行から分ける。

    引数: row(dict)は3分数値足。
    返り値: dictは場とSOURCE12列。
    """
    return {name: deepcopy(row[name]) for name in ("場", *SOURCE_FIELDS)}


def price_reasons(frame: dict) -> list[str]:
    """原数量と無関係に公開価格の利用不可理由を列挙する。

    引数: frame(dict)は3分足。
    返り値: list[str]は非公開/不正/欠枠/部分幅/早期公開の順の理由。
    """
    checks = ((frame["publish"], "非公開足"), (N.valid_ohlc(frame), "OHLC不正"),
        (frame["missing"] == 0, "欠枠あり"), (frame["end"] - frame["start"] == 180, "完全180秒不成立"),
        (frame["confirm"] >= frame["end"], "終了前公開"))
    return [reason for passed, reason in checks if not passed]


def adjacent(previous: dict | None, current: dict) -> bool:
    """当場隣接番号・半開区間と公開keyの連続性を確認する。

    引数: previous(dict|None)は前入力、current(dict)は現在入力。
    返り値: boolは初足又は全連続条件成立。
    """
    return previous is None or (current["index"] - previous["index"] == 1
        and previous["end"] == current["start"]
        and (current["confirm"], current["confirm_line"]) >= (previous["confirm"], previous["confirm_line"]))


def cmf_window(rows: list[dict]) -> dict:
    """検査済み窓の部分和と21本時の精密平均を直接計算する。

    引数: rows(list[dict])は最大21本の有効価格/数量。
    返り値: dictは出典番号・準備理由・総量・加重和・CMF。零本の部分和は0である。
    """
    multipliers, amounts = [], []
    for row in rows:
        high, low, close = (Fraction(row[name]) for name in ("high", "low", "close"))
        multipliers.append(((close - low) - (high - close)) / (high - low))
        amounts.append(Fraction(row["数量参照"]["観測差分量"]))
    total = sum(amounts, Fraction(0))
    weighted = sum((amounts[index] * multipliers[index] for index in range(len(rows))), Fraction(0))
    ready = len(rows) == 21 and total > 0
    reasons = (["同場CMF21連続足未準備"] if len(rows) != 21 else []) + (["CMF観測総量正未準備"] if total <= 0 else [])
    value = weighted / total if ready else None
    return {"CMF窓足番号": [row["index"] for row in rows], "CMF準備": ready, "CMF除外理由": reasons,
        "観測量合計": exact(total), "加重CLV合計": exact(weighted),
        "単位量CLV平均": exact(sum(multipliers, Fraction(0)) / 21 if len(rows) == 21 else None),
        "CMF21": exact(value), "CMF符号": int(value > 0) - int(value < 0) if value is not None else None,
        "CMF全量正同値": len(rows) == 21 and len(set(amounts)) == 1 and total > 0}


def volume_panels(frames: list[dict], session: str) -> list[dict]:
    """数量有効区間を保持し、末尾21本を直接sliceして全CMFを作る。

    引数: frames(list[dict])は当場3分/Q、session(str)は場。
    返り値: list[dict]は全足panel。数量不完全で価格窓や親監視を解除しない。
    """
    panels, segment, previous = [], [], None
    for raw in frames:
        frame = frame_projection(raw)
        if frame["場"] != session or previous is not None and frame["index"] <= previous["index"]:
            raise ValueError("当場3分足のstrict番号順だけです")
        bad = price_reasons(frame)
        reasons = list(bad)
        if not adjacent(previous, frame):
            reasons.append("価格番号区間公開順非連続")
        quantity = frame["数量参照"]
        q = quantity.get("観測差分量") if isinstance(quantity, dict) else None
        quantity_ok = isinstance(quantity, dict) and quantity.get("数量基準完全") is True and finite(q) and q >= 0
        width_ok = N.valid_ohlc(frame) and frame["high"] > frame["low"]
        if not quantity_ok:
            reasons.append("数量基準完全非負未準備")
        if not width_ok:
            reasons.append("CLV幅正未準備")
        if reasons:
            segment = []
        if not bad and quantity_ok and width_ok:
            segment.append(frame)
        clv = None
        if width_ok:
            high, low, close = (Fraction(frame[name]) for name in ("high", "low", "close"))
            clv = ((close - low) - (high - close)) / (high - low)
        panels.append({"場": session, "index": frame["index"], "足出典": source(frame),
            "CLV現": exact(clv), "CMF窓解除理由": reasons, **cmf_window(segment[-21:])})
        previous = frame
    return panels


def pure_signal(row: dict, policy: str = "A0") -> dict:
    """最初再テストの実役割を保持し、執行用13列だけを返す。

    引数: row(dict)は採用T/R判定、policy(str)はA0/A1/A2。
    返り値: dictは当時jの純信号。登録時計へ差し戻さない。
    """
    if policy not in POLICIES or row["役割"] not in ("順行", "反転") or row["side"] not in (-1, 1):
        raise ValueError("三切替候補の実T/Rだけです")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示方向が不一致")
    value = {name: deepcopy(row[name]) for name in SIGNAL_FIELDS if name not in ("イベントID", "入口ID", "bb_mean")}
    return {**value, "イベントID": row["発動ID"] + "_" + policy, "入口ID": "3分_" + policy, "bb_mean": None}


def verdicts(context: dict) -> dict:
    """同じ価格イベントに勢い・数量準備・数量方向を順に加える。

    引数: context(dict)は一回消費されたjの当時値。
    返り値: dictは三採否。CMF不成立を反対注文へ置換しない。
    """
    side, delta = context["side"], context["MACDヒスト変化"]
    reasons = list(context["M除外理由"])
    if side not in (-1, 1):
        reasons.append("価格構造待機")
    if not context["時間条件可"]:
        reasons.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        reasons.append("確認遅延30秒超")
    if side not in (-1, 1) or not finite(delta) or side * delta <= 0:
        reasons.append("MACDヒスト一足差実方向strict正不成立")
    result = {}
    for policy in POLICIES:
        current = list(reasons)
        if policy != "A0" and not context["CMF準備"]:
            current.append("CMF21数値未準備")
        if policy == "A2" and (side not in (-1, 1) or context["CMF符号"] is None or side * context["CMF符号"] <= 0):
            current.append("CMF21実方向strict正不成立")
        result[policy] = {"採用": not current, "理由": current or ["最初再テストと複合採用"], "同時競合": False}
    return result


# ----------------------------------------
# 登録単位の後続区間を別に走査し、その占有区間から時系列traceを復元する。


def watch_interval(frames: list[dict], invalids: list[list[str]], position: int,
                   watch: dict, deadline: float) -> tuple[dict, bool]:
    """登録bから最初の終了までを価格だけで直接走査する。

    引数: frames(list[dict])は当場足、invalids(list[list[str]])は価格解除理由、
    position(int)はb配列位置、watch(dict)は固定登録、deadline(float)は返済期限。
    返り値: tuple[dict,bool]は各足の動作/終了区分と、場末取消の要否。数値採否は参照しない。
    """
    result = {}
    for cursor in range(position + 1, len(frames)):
        row = frames[cursor]
        age = row["index"] - watch["登録足"]["index"]
        common = {"登録ID": watch["登録ID"], "年齢": age}
        ending = list(invalids[cursor]) + (["返済期限"] if row["confirm"] >= deadline else [])
        if ending:
            result[cursor] = {"動作": "監視取消", **common, "理由": ending}
            return result, False
        if age > 6:
            result[cursor] = {"動作": "監視満了", **common, "理由": ["六足満了"]}
            return result, False
        if row["start"] <= watch["登録足"]["confirm"] or (row["confirm"], row["confirm_line"]) <= (watch["登録足"]["confirm"], watch["登録足"]["confirm_line"]):
            result[cursor] = {"動作": "対象時点外", **common, "理由": ["登録後に始まる後続公開足ではない"]}
            continue
        side, boundary = watch["元価格side"], watch["固定境界B"]
        if row["close"] <= watch["旧L"] if side == 1 else row["close"] >= watch["旧R"]:
            result[cursor] = {"動作": "反対端終値取消", **common, "理由": ["反対端終値到達又は飛越"]}
            return result, False
        touch = row["low"] <= boundary if side == 1 else row["high"] >= boundary
        if touch:
            kind = "T" if side * (row["close"] - boundary) > 0 else "R" if watch["旧L"] < row["close"] < watch["旧R"] else "WAIT"
            identifier = watch["登録ID"] + f"_再テスト_{row['index']:04d}_{kind}"
            result[cursor] = {"動作": "再テスト消費", **common, "発動ID": identifier, "構造区分": kind}
            return result, False
    return result, True


def event_record(frame: dict, previous: dict | None, panel: dict, watch: dict,
                 action: dict, cutoff: float, deadline: float, config: dict) -> dict:
    """最初再テストの構造・勢いとCMFを現在公開keyへ結ぶ。

    引数: frame/previous/panel/watch/action(dict|None)は当時足/前足/数量/登録/消費、
    cutoff/deadline(float)は停止/返済、config(dict)は固定条件。
    返り値: dictはWAITも残す全j判定。価格役割を後から変更しない。
    """
    kind, parent_side = action["構造区分"], watch["元価格side"]
    side = parent_side if kind == "T" else -parent_side if kind == "R" else None
    delta = frame["macd_hist"] - previous["macd_hist"] if previous is not None and finite(frame["macd_hist"]) and finite(previous["macd_hist"]) else None
    reasons = []
    if previous is None or not finite(delta):
        reasons.append("当場隣接公開ヒスト未準備")
    if not finite(frame["atr"]) or frame["atr"] <= 0:
        reasons.append("現在ATR14有限正未準備")
    time_ok = frame["confirm"] < cutoff and deadline - frame["confirm"] >= config["残り時間下限分"] * 60
    delay_ok = frame["confirm"] - frame["end"] <= config["確認遅延上限秒"]
    identifier = action["発動ID"]
    value = {**deepcopy(frame), **deepcopy(panel), "時間足分": 3, "入口系統": "再テスト構造判定",
        "登録参照": deepcopy(watch), "登録ID": watch["登録ID"], "元価格side": parent_side, "構造区分": kind,
        "年齢": action["年齢"], "前3分参照": frame_projection(previous), "MACDヒスト変化": delta,
        "共通M準備": not reasons, "M除外理由": reasons, "時間条件可": time_ok, "確認遅延条件可": delay_ok,
        "役割": "順行" if kind == "T" else "反転" if kind == "R" else "待機", "side": side,
        "方向": "買い" if side == 1 else "売り" if side == -1 else "待機",
        "発動ID": identifier, "イベントID": identifier, "QイベントID": identifier, "入口ID": "3分_再テスト構造判定",
        "要求時計秒": frame["confirm"], "要求原板行": frame["confirm_line"], "足終了時計秒": frame["end"],
        "確認遅延秒": frame["confirm"] - frame["end"], "期限時計秒": deadline,
        "残り分_判断時": (deadline - frame["confirm"]) / 60,
        "先着評価対象": bool(time_ok and delay_ok and side in (-1, 1)), "bb_mean": None}
    value["戦略判定"] = verdicts(value)
    return value


def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> dict:
    """事前の価格窓と登録後区間を別走査し、同じ一監視traceを組み立てる。

    引数: frames(list[dict])は当場3分/Q、session(str)は場、cutoff/deadline(float)は停止/期限、config(dict)は固定条件。
    返り値: dictは全登録/監視/j/CMF/三採否。未来の監視結果を登録やlive純信号へ渡さない。
    """
    if any(row["場"] != session or row["minutes"] != 3 for row in frames):
        raise ValueError("当場の3分足だけです")
    rows = [frame_projection(row) for row in frames]
    panels = volume_panels(rows, session)
    invalids, priors, windows, segment = [], [], [], []
    for position, frame in enumerate(rows):
        before = rows[position - 1] if position else None
        bad = price_reasons(frame)
        invalid = list(bad) + ([] if adjacent(before, frame) else ["価格番号区間公開順非連続"])
        invalids.append(invalid)
        if invalid:
            segment = []
        priors.append(segment[-1] if segment else None)
        windows.append(segment[-20:] if not bad and len(segment) >= 20 else [])
        if not bad:
            segment.append(frame)
    registrations, trace, records, used = [], [], [], set()
    active_before, active_after, interval_actions = {}, {}, {}
    ending_watch = None
    for position, frame in enumerate(rows):
        watch = active_before.get(position)
        actions = [deepcopy(interval_actions[position])] if position in interval_actions else []
        if actions and actions[0]["動作"] == "再テスト消費":
            records.append(event_record(frame, priors[position], panels[position], watch, actions[0], cutoff, deadline, config))
        before = windows[position]
        if before:
            lower, upper = min(row["low"] for row in before), max(row["high"] for row in before)
            for side in (1, -1):
                if not (frame["close"] > upper if side == 1 else frame["close"] < lower):
                    continue
                boundary = upper if side == 1 else lower
                reasons = []
                if watch is not None:
                    reasons.append("監視中又は同足で監視終了")
                if not upper > lower:
                    reasons.append("旧高安幅正未準備")
                if not (frame["confirm"] < cutoff and deadline - frame["confirm"] >= config["残り時間下限分"] * 60):
                    reasons.append("登録時間条件外")
                if frame["confirm"] - frame["end"] > config["確認遅延上限秒"]:
                    reasons.append("登録確認遅延30秒超")
                if (side, boundary) in used:
                    reasons.append("同方向固定水準使用済み")
                identifier = f"NK225_{session}_3分_突破登録_{frame['index']:04d}_{side}"
                actions.append({"動作": "突破登録見送り" if reasons else "突破登録", "登録ID": identifier,
                    "元価格side": side, "固定境界B": boundary, "理由": reasons})
                if reasons:
                    continue
                used.add((side, boundary))
                parent = {"登録ID": identifier, "登録足": source(frame), "元価格side": side,
                    "旧L": lower, "旧R": upper, "固定境界B": boundary, "旧20足番号": [row["index"] for row in before],
                    "旧L足番号": max(row["index"] for row in before if row["low"] == lower),
                    "旧R足番号": max(row["index"] for row in before if row["high"] == upper)}
                actions[-1]["登録参照"] = deepcopy(parent)
                registrations.append(deepcopy(parent))
                future, at_eof = watch_interval(rows, invalids, position, parent, deadline)
                stop = max(future) if future and not at_eof else len(rows) - 1
                for cursor in range(position + 1, stop + 1):
                    active_before[cursor] = parent
                for cursor in range(position, stop + int(at_eof)):
                    active_after[cursor] = parent
                interval_actions.update(future)
                if at_eof:
                    ending_watch = parent
        trace.append({"場": session, "index": frame["index"], "足出典": source(frame),
            "監視前": deepcopy(watch), "動作": actions, "監視後": deepcopy(active_after.get(position)),
            "使用済み水準数": len(used)})
    if ending_watch is not None:
        trace[-1]["動作"].append({"動作": "場末監視取消", "登録ID": ending_watch["登録ID"], "理由": ["場末"]})
        trace[-1]["監視後"] = None
    for policy in POLICIES:
        groups = defaultdict(list)
        for row in records:
            if row["戦略判定"][policy]["採用"]:
                groups[row["要求時計秒"], row["要求原板行"]].append(row)
        for values in groups.values():
            if len(values) > 1:
                for row in values:
                    row["戦略判定"][policy] = {"採用": False, "同時競合": True, "理由": ["同判断複数信号見送り"]}
    signals = {"3分_" + policy: [] for policy in POLICIES}
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                signals["3分_" + policy].append({**deepcopy(row), "入口ID": "3分_" + policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": row["発動ID"] + "_" + policy})
    counts = {"足数": len(rows), "価格20窓準備足数": sum(bool(window) for window in windows),
        "CMF準備足数": sum(panel["CMF準備"] for panel in panels)}
    quality = {"場": session, "時間足分": 3, **counts, "突破登録数": len(registrations), "最初再テスト消費数": len(records),
        "構造区分別": dict(Counter(row["構造区分"] for row in records)),
        "監視動作別": dict(Counter(action["動作"] for item in trace for action in item["動作"])),
        "場末残監視取消数": int(ending_watch is not None), "終了時監視残数": 0,
        "先着評価対象外数": sum(not row["先着評価対象"] for row in records),
        "戦略別発動数": {key: len(value) for key, value in signals.items()},
        "戦略採否理由別": {policy: dict(Counter(reason for row in records for reason in row["戦略判定"][policy]["理由"])) for policy in POLICIES}}
    metadata = {row["発動ID"]: {"元登録ID": row["登録ID"], "元価格side": row["元価格side"],
        "元登録時計秒": row["登録参照"]["登録足"]["confirm"],
        "元登録原板行": row["登録参照"]["登録足"]["confirm_line"], "判別種別": row["構造区分"]} for row in records}
    return {"場": session, "signals": signals, "raw": records, "decisions": records, "volume_panels": panels,
        "monitor_trace": trace, "registrations": registrations, "quality": quality, "metadata": metadata}


# ----------------------------------------
# 主準備と固定29指標だけを正本へ結ぶ。旧case・旧対照は要求しない。


saved_rows = Y.Y.saved_rows


def dependency_pins() -> dict:
    """固定独立足・中心化MACD・直接先着・追尾の全依存を識別する。

    引数: なし。
    返り値: dict[str,str]はROOT相対pathと現在SHA。42主コードを数式依存にしない。
    """
    paths = {"scripts/回帰突破/状態独立確認.py", "scripts/OBV反転/状態独立確認.py",
        "scripts/終値位置/追尾独立確認.py"}
    return dict(sorted({**Y.dependency_pins(), **{name: V.sha(ROOT / name) for name in paths}}.items()))



def shared_bundle(audit: Audit) -> dict:
    """29の保存全数値を出典照合し、3分16列だけを研究入力へ渡す。

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

    引数: study(Path)は42、audit(Audit)は比較先。
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



def guarded_inputs(study: Path, work: Path, audit: Audit) -> tuple[dict, dict, dict, Path]:
    """非損益主準備と三案・費用・入力・使用数値版を市場入力前に照合する。

    引数: study/work(Path)は42保存先、audit(Audit)は比較先。
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
    paths = {"scripts/再テスト量方向/" + name for name in ("検証.py", "入口.py", "運用.py")}
    audit.check("主三コード集合", set(master["コードSHA256"]), paths)
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
        "厳密範囲": "原8列由来SOURCE/全数量Q属性/CMF全分数/固定登録・監視・最初再テスト/時点/全採否/純13原値は厳密。全ATR/Hの別算値はabs1e-10/rel0、ATR正有効/D整数・H符号と全jのδH符号/M/採否はstrict。検算済み保存正本floatを定義とする全3分/判定SHAと、独立再算値の生SHAは区別する。",
        "数値許容": {"対象": ["atr", "macd_hist", "MACDヒスト変化"], "絶対許容": 1e-10, "相対許容": 0,
            "採否epsilon": False, "正本定義SHAと独立生数値SHAを区別": True}}



def check_prepared(study: Path, work: Path, resolved: Path, master: dict, audit: Audit) -> None:
    """成功した独立準備と全固定指紋を正式市場入力前に要求する。

    引数: study/work/resolved(Path)は保存/台帳、master(dict)は主準備、audit(Audit)は比較先。
    返り値: None。古版・未完・差ありは停止する。
    """
    prepared, expected = V.read(work / "独立準備点検.json"), proof_base(study, work, resolved, master, audit)
    for key in ("コードSHA256", "追尾コードSHA256", "依存コードSHA256", "主準備SHA256", "主コードSHA256",
            "条件SHA256", "入力台帳SHA256", "参照入力台帳SHA256", "指標参照SHA256"):
        audit.check("準備bind:" + key, prepared[key], expected[key])
    for key, value in {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False}.items():
        audit.check("準備成功:" + key, prepared[key], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("正式固定現在:" + name, V.sha(ROOT / name), digest)
    if audit.mismatches:
        raise ValueError("準備/固定/現版に差があり正式市場入力前停止")


def reconstruct(manifest: dict, bundle: dict, config: dict) -> Any:
    """原8列の価格と累積数量から監視・CMF・三採否を別算する。

    引数: manifest/bundle/config(dict)は予約台帳/29保存数値/固定条件。
    返り値: Anyは非先着・非運用の場別iterator。正本float定義と再算判断を分ける。
    """
    bank = NumericHistory(3)
    for entry in manifest["entries"]:
        session = entry["session"]
        start, finish, cutoff, deadline = S.G.times(session)
        data = G.observed(entry, manifest)
        formed = S.bars(data, session, 3, N.BareBars())
        quantity, quantity_quality = G.quantities(data, formed, start, finish)
        tail = max(0, int((finish - start) // 180) - 1 - (formed[-1]["index"] if formed else -1))
        independent, quality = bank.build(formed, session, tuple(entry["in_session_contract_codes"]), tail, quantity)
        original = {row["index"]: row for row in bundle["lower"][session]}
        defined = [{**deepcopy(row), **{name: original[row["index"]][name] for name in ("atr", "macd_hist")}} for row in independent]
        selected = generate(defined, session, cutoff, deadline, config)
        alternate = generate(independent, session, cutoff, deadline, config)
        pure = [pure_signal(row, policy) for policy in POLICIES for row in selected["signals"]["3分_" + policy]]
        period = "学習" if session[:10] < config["分割"]["選択開始日"] else ("条件選択" if session[:10] < config["分割"]["後続開始日"] else "後続検査")
        yield {"場": session, "期間": period, "純信号": pure, "純信号内容SHA256": canonical_sha(pure),
            "純信号判断SHA256": canonical_sha([decision_signal(row) for row in pure]),
            "判定": selected["decisions"], "判定SHA256": canonical_sha(selected["decisions"]),
            "判定判断SHA256": canonical_sha(selected["decisions"]),
            "全3分投影SHA256": canonical_sha(defined), "3分投影足数": len(defined), "入力品質": selected["quality"],
            "登録": selected["registrations"], "登録SHA256": canonical_sha(selected["registrations"]),
            "監視": selected["monitor_trace"], "監視SHA256": canonical_sha(selected["monitor_trace"]),
            "全CMF投影SHA256": canonical_sha(selected["volume_panels"]), "CMF足数": len(selected["volume_panels"]),
            "_再算全3分": independent, "_正本数値定義全3分": defined, "_再算判断": alternate, "_正本判断": selected,
            "_銀行品質": quality, "_数量品質": quantity_quality, "_metadata": selected["metadata"]}


def numerical_judgment(value: Any) -> Any:
    """限定許容の生floatだけを判断へ投影し、全監視と採否を厳密に残す。

    引数: value(Any)は全登録/監視/発動/純信号を含む独立結果。
    返り値: AnyはATR正有効/D整数とヒスト符号を分けた値。CMF/数量/時計に許容を広げない。
    """
    if isinstance(value, list):
        return [numerical_judgment(item) for item in value]
    if isinstance(value, dict):
        output = {}
        for name, item in value.items():
            if name == "atr":
                positive = finite(item) and item > 0
                output[name] = {"正有効": positive, "D整数": max(5, math.ceil(item / 5) * 5) if positive else None}
            elif name in ("macd_hist", "MACDヒスト変化"):
                output[name] = {"有限": finite(item), "符号": int(item > 0) - int(item < 0) if finite(item) else None}
            else:
                output[name] = numerical_judgment(item)
        return output
    return value


def compare_preparation(main: dict, block: dict, bundle: dict, audit: Audit) -> dict:
    """全原数量/価格/CMFと、数値表現差・厳密監視/採否影響を分けて比較する。

    引数: main/block(dict)は主/独立場、bundle(dict)は旧数値出典、audit(Audit)は比較先。
    返り値: dictは全足・登録・T/R/WAIT・三集合と数値差の要約。
    """
    session = block["場"]
    independent, original = block["_再算全3分"], bundle["lower"][session]
    audit.check(session + ":原8列SOURCE/全Q/ATR/H", independent, original)
    expected_record = {key: value for key, value in block.items() if not key.startswith("_")}
    audit.check(session + ":正本数値定義全登録監視/CMF/全A", main, expected_record)
    audit.check(session + ":正本数値定義全JSON厳密", main == expected_record, True)
    original_judgment = numerical_judgment(block["_正本判断"])
    rebuilt_judgment = numerical_judgment(block["_再算判断"])
    audit.check(session + ":再算数値全監視/CMF/採否strict", rebuilt_judgment, original_judgment)
    same = rebuilt_judgment == original_judgment
    audit.check(session + ":再算数値判断影響なし", same, True)
    for actual, alternative in zip(block["判定"], block["_再算判断"]["decisions"]):
        audit.check(actual["発動ID"] + ":再算数値差:MACDヒスト変化", alternative["MACDヒスト変化"], actual["MACDヒスト変化"])
    ids = {p: {row["イベントID"][:-3] for row in main["純信号"] if row["入口ID"] == "3分_" + p} for p in POLICIES}
    audit.check(session + ":A1準備subsetA0", ids["A1"] <= ids["A0"], True)
    audit.check(session + ":A2値subsetA1", ids["A2"] <= ids["A1"], True)
    raw = {row["発動ID"]: row for row in main["判定"]}
    for signal in main["純信号"]:
        policy, identifier = signal["入口ID"].removeprefix("3分_"), signal["イベントID"][:-3]
        audit.check(signal["イベントID"] + ":純13列集合", set(signal), set(SIGNAL_FIELDS))
        audit.check(signal["イベントID"] + ":実方向役割現ATR厳密", signal == pure_signal(raw[identifier], policy), True)
    differences = {name: [abs(a[name] - b[name]) for a, b in zip(independent, original, strict=True)
        if finite(a[name]) and finite(b[name]) and a[name] != b[name]] for name in ("atr", "macd_hist")}
    return {"場": session, "期間": block["期間"], **{p + "登録数": len(ids[p]) for p in POLICIES},
        "突破登録数": len(block["登録"]), "最初再テスト消費数": len(main["判定"]),
        "構造区分別": dict(Counter(row["構造区分"] for row in main["判定"])), "監視足数": len(main["監視"]),
        "3分投影足数": len(original), "CMF足数": block["CMF足数"], "CMF準備足数": block["入力品質"]["CMF準備足数"],
        **{name + "表現差足数": len(values) for name, values in differences.items()},
        **{name + "最大絶対差": max(values, default=0.0) for name, values in differences.items()},
        "再算数値判断不一致場": int(not same), "全3分投影SHA256": block["全3分投影SHA256"],
        "独立再算全3分内容SHA256": canonical_sha(independent), "全判定SHA256": block["判定SHA256"],
        "全CMF投影SHA256": block["全CMF投影SHA256"], "全監視SHA256": block["監視SHA256"],
        "方針実役割別": {p: {role: sum(row["入口ID"] == "3分_" + p and row["役割"] == role for row in main["純信号"])
            for role in ("順行", "反転")} for p in POLICIES}}


def numeric_summary(stages: list[dict]) -> dict:
    """全足数量と数値、全登録・最初j・CMFの検算範囲を集計する。

    引数: stages(list[dict])は場別検算要約。
    返り値: dictは対象件数・表現差と判断影響。監査件数を収益標本数にしない。
    """
    return {"新3分全数値照合足数": sum(r["3分投影足数"] for r in stages),
        "全数量属性照合足数": sum(r["3分投影足数"] for r in stages),
        "全CMF照合足数": sum(r["CMF足数"] for r in stages),
        "全突破登録数": sum(r["突破登録数"] for r in stages),
        "全最初再テスト消費数": sum(r["最初再テスト消費数"] for r in stages),
        "全監視照合足数": sum(r["監視足数"] for r in stages),
        "独立数値判断不一致場数": sum(r["再算数値判断不一致場"] for r in stages),
        **{"独立" + name + "表現差足数": sum(r[name + "表現差足数"] for r in stages) for name in ("atr", "macd_hist")},
        **{"独立" + name + "最大絶対差": max((r[name + "最大絶対差"] for r in stages), default=0.0) for name in ("atr", "macd_hist")}}


def prepare(study: Path, work: Path) -> dict:
    """root起動で原8列数量・価格・監視・CMF・三採否を非損益検算する。

    引数: study/work(Path)は42保存先。
    返り値: dictはラベル・運用・PnLを呼ばない独立準備証明。
    """
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    bundle, stages = shared_bundle(audit), []
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        print(json.dumps({"場": block["場"], "独立準備": "原8列価格/Q/ATR/H・登録区間走査・CMF・全A", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "ラベル計算": False, "損益計算": False,
        "全66場既使用": True, "場別準備": stages, **numeric_summary(stages),
        "方針別登録数": {p: sum(r[p + "登録数"] for r in stages) for p in POLICIES},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "検証範囲": "全原8列から半開3分/Q全属性/ATR14/中心化Hを再算。各登録の後続区間走査で全監視/T/R/WAIT/初回消費を別構築し、CMF21は末尾sliceの精密加重和から計算。正本float定義SHAと再算数値の監視/採否影響を分ける。",
        "限界": "非先着/非運用/非PnL。旧29は数値出典だけで旧P/k量M/旧caseを流用しない。観測差分量は真の全約定量ではない。全66場既使用。"}
    (work / "独立準備点検.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "全突破登録数", "方針別登録数")}, ensure_ascii=False))
    return proof


def run(study: Path, work: Path) -> dict:
    """正式後に全監視/全jと全実方向caseの新規後先着を直接検算する。

    引数: study/work(Path)は42保存先。
    返り値: dictは新五系列へbindした状態証明。実会計・全追尾は別証明へ結ぶ。
    """
    if not (study / "固定.json").exists() or not (study / "結果.json").exists():
        raise ValueError("root固定・正式完了後だけです")
    audit, initial = Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved = guarded_inputs(study, work, audit)
    check_prepared(study, work, resolved, master, audit)
    bundle = shared_bundle(audit)
    names = ("登録監視", "発動判定", "入口事例", "全運用詳細", "追尾")
    saved, hashes, grouped = {}, {}, {name: defaultdict(list) for name in names}
    for name in names:
        saved[name], hashes[name] = saved_rows(study, work, name + ".jsonl.gz", audit)
        for row in saved[name]:
            grouped[name][row["場"]].append(row)
    artifact_names = {Path(row["パス"]).name for row in V.read(study / "作業成果物.json")["ファイル"]}
    audit.check("新五成果物集合", artifact_names, {name + ".jsonl.gz" for name in names})
    pairs = [(row["場"], row["候補ID"]) for row in saved["全運用詳細"]]
    audit.check("全場候補一意", len(pairs), len(set(pairs)))
    audit.check("全3x66", set(pairs), {(entry["session"], cid) for entry in manifest["entries"] for cid in OPERATIONS})
    audit.check("全case一意", len(saved["入口事例"]), len({row["イベントID"] for row in saved["入口事例"]}))
    stages, counts = [], {p: 0 for p in POLICIES}
    role_counts = {p: {role: 0 for role in ("順行", "反転")} for p in POLICIES}
    entries = {row["session"]: row for row in manifest["entries"]}
    for main_record, block in zip(master["準備"], reconstruct(manifest, bundle, config), strict=True):
        stages.append(compare_preparation(main_record, block, bundle, audit))
        session, period = block["場"], block["期間"]
        for key, field in (("登録監視", "監視"), ("発動判定", "判定")):
            expected_rows = [{"期間": period, **row} for row in block[field]]
            audit.check(session + ":正式全" + key, grouped[key][session], expected_rows)
            audit.check(session + ":正式厳密全" + key, grouped[key][session] == expected_rows, True)
        registered = [deepcopy(action["登録参照"]) for row in grouped["登録監視"][session]
            for action in row["動作"] if action["動作"] == "突破登録"]
        audit.check(session + ":正式登録actionから全b復元", registered, block["登録"])
        audit.check(session + ":正式登録ID一意", len(registered), len({row["登録ID"] for row in registered}))
        cases = {row["イベントID"]: row for row in grouped["入口事例"][session]}
        audit.check(session + ":全case純集合", set(cases), {row["イベントID"] for row in block["純信号"]})
        quotes = normal_columns(entries[session], manifest)
        _, _, cutoff, deadline = S.G.times(session)
        for signal in block["純信号"]:
            origin = signal["イベントID"][:-3]
            direct = label_direct(quotes, signal, cutoff, deadline)
            expected = {**deepcopy(signal), "期間": period,
                "要求時計JST": datetime.fromtimestamp(signal["要求時計秒"], timezone(timedelta(hours=9))).isoformat(),
                "元価格発動ID": origin, **deepcopy(block["_metadata"][origin]), **direct}
            audit.check(signal["イベントID"] + ":全実方向case直接BBO先着", cases.get(signal["イベントID"]), expected)
            audit.check(signal["イベントID"] + ":全case厳密値", cases.get(signal["イベントID"]) == expected, True)
            policy = signal["入口ID"].removeprefix("3分_")
            counts[policy] += 1
            role_counts[policy][signal["役割"]] += 1
        for detail in grouped["全運用詳細"][session]:
            audit.check(detail["候補ID"] + session + ":期間", detail["品質"]["期間"], period)
        print(json.dumps({"場": session, "独立状態": "原8列/Q・全登録監視・最初T/R/WAIT・CMF・全case直接先着", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    result = V.read(study / "結果.json")
    for key, expected in {"全66場既使用": True, "入口評価数": 3, "運用候補数": 3, "現方針運用候補数": 3,
            "入口125250評価の変更": False, "表示固定ID": list(OPERATIONS)}.items():
        audit.check("正式結果:" + key, result[key], expected)
    for row in result["入口評価"]:
        audit.check(row["入口ID"] + ":集合役割", row["役割"], "切替")
    role_groups = [(row["入口ID"], row["役割"]) for row in result["役割別入口評価"]]
    audit.check("全三案実二役割6群", set(role_groups), {("3分_" + p, role) for p in POLICIES for role in ("順行", "反転")})
    audit.check("役割群一意", len(role_groups), len(set(role_groups)))
    audit.check("全case数", len(saved["入口事例"]), sum(counts.values()))
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {**proof_base(study, work, resolved, master, audit), "場別準備": stages, **numeric_summary(stages),
        "方針別case数": counts, "方針実役割別case数": role_counts,
        "全先着直接照合件数": sum(counts.values()), "方針別先着直接照合件数": counts,
        "保存登録監視数": len(saved["登録監視"]), "保存発動判定数": len(saved["発動判定"]),
        "正式登録action抽出数": sum(action["動作"] == "突破登録" for row in saved["登録監視"] for action in row["動作"]),
        "保存入口事例数": len(saved["入口事例"]), "保存運用詳細数": len(saved["全運用詳細"]), "保存追尾数": len(saved["追尾"]),
        "成果物照合": {name + ".jsonl.gz": {"展開内容SHA256": hashes[name], "行数": len(saved[name])} for name in names},
        **{name + "展開SHA256": digest for name, digest in hashes.items()},
        "共有3分全指標展開SHA256": bundle["共有3分全指標展開SHA256"],
        "結果SHA256": V.sha(study / "結果.json"), "固定SHA256": V.sha(study / "固定.json"),
        "独立準備SHA256": V.sha(work / "独立準備点検.json"),
        "検証範囲": "原8列3分OHLC/Q全属性/ATR14/中心化H、全b・used水準・六足監視・初回T/R/WAIT消費・CMF21・全三採否/純13を独立構築。全新caseをj要求後の原正常BBO最初+1秒新規から実side125/250/空白/期限へ直接走査。保存五明細の全行へbind。",
        "限界": "元登録bの価格や旧labelをjの新規/先着へ流用しない。純監視と実pending/建玉は別。実運用受付/最初約定/Decimalは別会計、全保有と最初返済要求は別追尾。観測qは真の全約定量を保証しない。全66場既使用。"}
    (work / "状態独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "全突破登録数", "方針別case数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """rootの準備許可又は正式完了後だけ明示CLIを起動する。

    引数: なし。--study/--work/--prepare/--実行許可を読む。
    返り値: None。無指定又は不一致は非0終了する。
    """
    parser = argparse.ArgumentParser(description="00042原数量と最初再テスト/CMFの独立検算")
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

