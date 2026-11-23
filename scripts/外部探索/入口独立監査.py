"""00008の保存特徴・入口集計・先着事例を、探索実装をimportせず照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
WORK = ROOT / "work/外部研究/探索00008"
JST = timezone(timedelta(hours=9))
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


def read_json(path: Path) -> dict:
    """監査対象の小さなJSONを読む。

    引数: path (Path) は対象。
    返り値: dict は保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    """内容指紋を小分けに計算する。

    引数: path (Path) は対象。
    返り値: str はSHA256。
    """
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def finite(value: object) -> bool:
    """不足値を条件成立へ変換しない。

    引数: value (object) は指標等。
    返り値: bool は有限数値か。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class 照合:
    """照合件数と不一致を保存する。"""

    def __init__(self) -> None:
        """集計状態を初期化する。

        引数: なし。
        返り値: None。
        """
        self.count = self.errors = 0
        self.examples = []

    def check(self, label: str, actual: object, expected: object) -> None:
        """値を比較し、浮動小数の丸めだけを許容する。

        引数: label (str) は検査名、actual/expected (object) は対象と独立期待値。
        返り値: None。不一致例は最大100件。
        """
        self.count += 1
        same = actual == expected
        if finite(actual) and finite(expected):
            same = math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-11)
        if not same:
            self.errors += 1
            if len(self.examples) < 100:
                self.examples.append({"項目": label, "保存値": sorted(actual) if isinstance(actual, set) else actual,
                                      "独立値": sorted(expected) if isinstance(expected, set) else expected})


# ----------------------------------------
# 買いと売りを明示した別表現の条件判定。探索のallowedは呼ばない。

def candidates(config: dict) -> list[dict]:
    """条件JSONの直積から候補を独立に列挙する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は新32条件と旧対照。
    """
    values = [{"候補ID": f"{size}分_{family}_{parameter}_{extra}", "時間足分": size,
               "手法": family, "パラメータ": parameter, "補助": extra}
              for size in config["時間足分"] for family, params in config["手法"].items()
              for parameter in params for extra in config["補助"]]
    values.append({"候補ID": config["対照ID"], "時間足分": 3, "手法": "旧対照", "パラメータ": 15, "補助": "ADX環境"})
    return values


def qualifies(row: dict, candidate: dict) -> bool:
    """保存済み特徴から、現在の売買方向の条件を別に判定する。

    引数: row (dict) は保存特徴、candidate (dict) は固定規則。
    返り値: bool は発動と補助の成立。将来ラベルは使わない。
    """
    if row["時間足分"] != candidate["時間足分"]:
        return False
    buy = row["side"] == 1
    if candidate["手法"] == "旧対照":
        return bool(row.get(f"開始幅失敗復帰_15_{row['side']}", False)) and finite(row["adx"]) and row["adx"] < 20
    previous, family, parameter = row["前値"], candidate["手法"], candidate["パラメータ"]
    if not finite(previous["close"]) or not finite(row["close"]):
        return False
    if buy and row["close"] <= previous["close"] or not buy and row["close"] >= previous["close"]:
        return False
    trigger = False
    if family == "RSI回復":
        if finite(previous["rsi"]) and finite(row["rsi"]):
            trigger = previous["rsi"] <= parameter < row["rsi"] if buy else previous["rsi"] >= 100-parameter > row["rsi"]
    elif family == "RSI再加速":
        history = row["過去RSI"][-parameter:]
        if len(history) == parameter and all(finite(v) for v in [previous["rsi"], row["rsi"], row["ema20"], *history]):
            trigger = (previous["rsi"] <= 50 < row["rsi"] and min(history) <= 40 and row["close"] > row["ema20"]) if buy else (
                previous["rsi"] >= 50 > row["rsi"] and max(history) >= 60 and row["close"] < row["ema20"])
    elif family == "DMI方向発生":
        if all(finite(v) for v in (previous["plus_di"], previous["minus_di"], row["plus_di"], row["minus_di"], previous["adx"], row["adx"], row["ema20"])):
            crossed = previous["plus_di"] <= previous["minus_di"] and row["plus_di"] > row["minus_di"] if buy else (
                previous["minus_di"] <= previous["plus_di"] and row["minus_di"] > row["plus_di"])
            price_side = row["close"] > row["ema20"] if buy else row["close"] < row["ema20"]
            trigger = crossed and price_side and row["adx"] >= parameter and row["adx"] > previous["adx"]
    elif family == "BB復帰価格確認":
        if all(finite(v) for v in (previous["bb_mean"], previous["bb_sd"], row["bb_mean"], row["bb_sd"])):
            trigger = (previous["close"] < previous["bb_mean"]-parameter*previous["bb_sd"] and row["close"] >= row["bb_mean"]-parameter*row["bb_sd"]) if buy else (
                previous["close"] > previous["bb_mean"]+parameter*previous["bb_sd"] and row["close"] <= row["bb_mean"]+parameter*row["bb_sd"])
    else:
        raise ValueError("未知の入口系統")
    if not trigger or candidate["補助"] == "なし":
        return bool(trigger)
    low = finite(row["adx"]) and finite(previous["adx"]) and row["adx"] < 20 and previous["adx"] >= row["adx"]
    if family == "RSI回復":
        return low
    if not row["上位準備済"]:
        return False
    if family == "RSI再加速":
        return row["上位方向"] == (1 if buy else -1)
    if family == "DMI方向発生":
        return row["上位方向"] in ((0, 1) if buy else (-1, 0))
    return low and row["上位方向"] == 0


def basic(rows: list[dict]) -> dict:
    """五分類と開始日・場の支持範囲を別計算する。

    引数: rows (list[dict]) は一候補一期間。
    返り値: dict は基本集計。
    """
    labels = Counter(row["ラベル"] for row in rows)
    if set(labels) - set(LABELS):
        raise ValueError("未知のラベル")
    filled = [row for row in rows if row["ラベル"] != "未約定"]
    successes = [row for row in rows if row["ラベル"] == "順行先着"]
    days = Counter(row["場"][:10] for row in successes)
    return {"候補数": len(rows), "約定候補数": len(filled), **{label: labels[label] for label in LABELS},
            "確認率": len(successes)/len(filled) if filled else None,
            "候補場数": len({r["場"] for r in rows}), "約定場数": len({r["場"] for r in filled}),
            "候補開始日数": len({r["場"][:10] for r in rows}), "約定開始日数": len({r["場"][:10] for r in filled}),
            "成功開始日数": len(days), "最大成功日寄与率": max(days.values())/len(successes) if successes else None}


def metrics(rows: list[dict], phase: str) -> dict:
    """全約定分母・独立Wilson参考・要求だけの30分間引きを集計する。

    引数: rows (list[dict]) は一候補一期間、phase (str) は表示区分。
    返り値: dict は既存評価と照合する平坦な集計。
    """
    value = basic(rows)
    kept, previous = [], {}
    ordered = sorted(enumerate(rows), key=lambda pair: (Decimal(str(pair[1]["要求時計秒"])), int(pair[1].get("要求原板行", 0)), pair[0]))
    for _, row in ordered:
        key, now = (row["場"], row["side"]), Decimal(str(row["要求時計秒"]))
        if key not in previous or now-previous[key] >= Decimal(1800):
            kept.append(row)
            previous[key] = now
    thin = basic(kept)
    z, n, k = 1.959963984540054, value["約定候補数"], value["順行先着"]
    low = high = None
    if n:
        center = (k+z*z/2)/(n+z*z)
        radius = z*math.sqrt(k*(n-k)/n+z*z/4)/(n+z*z)
        low, high = max(0, center-radius), min(1, center+radius)
    return {**value, "分割": phase, "Wilson95下限_独立参考": low, "Wilson95上限_独立参考": high,
            **{f"30分間引き_{key}": thin[key] for key in ("候補数", "約定候補数", "順行先着", "確認率", "候補場数", "約定場数", "約定開始日数")}}


def selection(results: list[dict], independent: dict, config: dict) -> dict:
    """独立入口集計と保存運用集計から、支持・順位を別計算する。

    引数: results (list[dict]) は保存結果、independent (dict) は候補・期間別入口、config (dict) は資格。
    返り値: dict は再計算した選定。運用集計自体の独立会計は別監査に委ねる。
    """
    values = []
    for result in results:
        cid = result["候補ID"]
        if cid == config["対照ID"]:
            continue
        entries = [independent[cid][p] for p in ("学習", "条件選択")]
        support = all(all(independent[cid][phase][key] >= limit for key, limit in limits.items()) for phase, limits in config["入口支持"].items())
        seventy = support and all(independent[cid][phase]["確認率"] >= config["目標確認率"]
                and independent[cid][phase]["30分間引き_約定候補数"] >= config["間引き必要件数"][phase]
                and independent[cid][phase]["30分間引き_確認率"] >= config["目標確認率"] for phase in ("学習", "条件選択"))
        cost = all(all(result[phase]["運用"][key] >= limit for key, limit in limits.items())
                   and result[phase]["運用"]["品質注意場数"] == result[phase]["運用"]["未解消場数"] == result[phase]["運用"]["EOF期限未達場数"] == 0
                   and result[phase]["運用"]["追加5pt純損益円"] > 0 for phase, limits in config["費用支持"].items())
        values.append({"ID": cid, "支持": support, "70": seventy, "費用": cost, "保存": result,
                       "入口順位": (not support, -min(e["確認率"] or 0 for e in entries),
                       -min(e["30分間引き_確認率"] or 0 for e in entries), -entries[1]["約定候補数"], cid)})
    entry = sorted(values, key=lambda v: v["入口順位"])[0]
    qualified = [v for v in values if v["費用"]]
    profit = sorted(qualified, key=lambda v: (-min(v["保存"][p]["運用"]["追加5pt平均円"] for p in ("学習", "条件選択")),
                    -sum(v["保存"][p]["運用"]["追加5pt純損益円"] for p in ("学習", "条件選択")), v["ID"]))[0] if qualified else None
    return {"入口用ID": entry["ID"], "入口用支持": entry["支持"], "費用用ID": profit["ID"] if profit else None,
            "費用資格数": len(qualified), "70目標達成数": sum(v["70"] for v in values),
            "固定ID": list(dict.fromkeys([entry["ID"], *([profit["ID"]] if profit else []), config["対照ID"]])),
            "候補別資格": {v["ID"]: {"入口支持": v["支持"], "70目標": v["70"], "費用資格": v["費用"]} for v in values}}


# ----------------------------------------
# 正常キャッシュを原順に直接走査する。区間木・共有のevaluateは使わない。

def bounds(session: str) -> tuple[float, float, float, float]:
    """開始日からセッション時刻を独立に求める。

    引数: session (str) は場名。
    返り値: tuple[float, float, float, float] は開始・終了・新規停止・期限秒。
    """
    value = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("Day"):
        return tuple(value.replace(hour=h, minute=m).timestamp() for h, m in ((8, 45), (15, 40), (15, 25), (15, 35)))
    following = value+timedelta(days=1)
    return value.replace(hour=17).timestamp(), following.replace(hour=5, minute=55).timestamp(), following.replace(hour=5, minute=40).timestamp(), following.replace(hour=5, minute=50).timestamp()


def normal_quotes(path: Path, session: str) -> np.ndarray:
    """固定npzを読み、後退・場外を除いた正常板を原順に返す。

    引数: path (Path) はキャッシュ、session (str) は場名。
    返り値: np.ndarray は時計・原行・Bid・Askの4列。
    """
    begin, end, _, _ = bounds(session)
    rows, previous = [], -math.inf
    with np.load(path, allow_pickle=False) as archive:
        for now, line, bid, ask, valid in zip(*(archive[key] for key in ("now", "line", "bid", "ask", "valid"))):
            if not math.isfinite(now) or not begin <= now <= end or now < previous:
                continue
            previous = float(now)
            if valid:
                if not 0 < bid < ask:
                    raise ValueError("正常板フラグとBBO不一致")
                rows.append((float(now), int(line), float(bid), float(ask)))
    return np.asarray(rows, dtype=float).reshape(-1, 4)


def direct_label(quotes: np.ndarray, signal: float, cutoff: float, deadline: float, side: int,
                 adverse: float = 125, favorable: float = 250) -> dict:
    """正常気配を一行ずつ追い、新規と上下閾値・空白・期限を判定する。

    引数: quotes (np.ndarray) は4列、signal/cutoff/deadline (float) は時刻、side (int) は方向、
    adverse/favorable (float) は逆行・順行の固定幅。
    返り値: dict は原行と時計を含む先着結果。
    """
    empty = {"ラベル": "未約定", "理由": "30秒内に正常板なし", "新規価格": None, "新規時計秒": None,
             "新規原板行": None, "判定時計秒": None, "判定原板行": None, "判定気配": None,
             "最大順行pt": None, "最大逆行pt": None, "所要分": None}
    first = next((i for i, q in enumerate(quotes) if q[0] >= signal+1), None)
    if first is None or quotes[first, 0] > signal+30 or quotes[first, 0] >= cutoff:
        return empty
    entry = quotes[first, 3 if side == 1 else 2]
    last, distances, hit, gap = first, [], False, False
    for i in range(first, len(quotes)):
        q = quotes[i]
        if i > first and q[0]-quotes[i-1, 0] > 300 and quotes[i-1, 0]+300 < deadline:
            gap = True
            break
        if q[0] > deadline:
            break
        last = i
        distance = side*(q[2 if side == 1 else 3]-entry)
        distances.append(distance)
        if distance >= favorable or distance <= -adverse:
            label, reason, hit = ("順行先着" if distance >= favorable else "逆行先着"), "返済気配の閾値初着", True
            break
    if not hit:
        missing = gap or deadline-quotes[last, 0] > 300
        covered = len(quotes) > 0 and quotes[-1, 0] >= deadline
        label = "観測不足" if missing or not covered else "期限未達"
        reason = "正常板価格時計300秒超空白" if missing else ("入力末尾不足" if not covered else "期限内どちらも未到達")
    if not distances:
        raise ValueError("新規後に期限内の採用観測がない")
    return {"ラベル": label, "理由": reason, "新規価格": float(entry), "新規時計秒": float(quotes[first, 0]),
            "新規原板行": int(quotes[first, 1]), "判定時計秒": float(quotes[last, 0]), "判定原板行": int(quotes[last, 1]),
            "判定気配": float(quotes[last, 2 if side == 1 else 3]), "最大順行pt": max(0.0, float(max(distances))),
            "最大逆行pt": max(0.0, float(-min(distances))), "所要分": float((quotes[last, 0]-quotes[first, 0])/60)}


def sample_cases(grouped: dict, fixed_ids: list[str], phases: list[str]) -> list[tuple[str, dict]]:
    """各固定IDの最初の成功・失敗を取り、必要なら期間別の最初を補う。

    引数: grouped (dict) は候補の事例、fixed_ids (list[str]) は固定ID、phases (list[str]) は対象期間。
    返り値: list[tuple[str, dict]] は最大10件。後続も固定ID以外へ広げない。
    """
    result, used = [], set()
    for phase in [None, *phases]:
        for cid in fixed_ids:
            for label in ("順行先着", "逆行先着"):
                ordered = sorted((r for r in grouped[cid] if r["ラベル"] == label and (phase is None or r["期間"] == phase)),
                                 key=lambda r: (r["要求時計秒"], r["要求原板行"]))
                if ordered:
                    row = ordered[0]
                    key = (cid, row["イベントID"])
                    if key not in used:
                        result.append((cid, row))
                        used.add(key)
        if len(result) >= 6:
            break
    return result[:10]


def audit_phase(study: Path, phase: str, config: dict, audit: 照合) -> dict:
    """保存特徴の全候補・全集計と、固定候補の少数先着事例を照合する。

    引数: study (Path) は試行、phase (str) は探索/後続、config (dict) は条件、audit (照合) は集計器。
    返り値: dict は一段階の監査範囲。後続で再選定しない。
    """
    before_checks, before_errors = audit.count, audit.errors
    report = read_json(study / ("探索結果.json" if phase == "探索" else "後続結果.json"))
    locked = read_json(study / "選定固定.json")
    rules = candidates(config)
    fixed_ids = locked["選定"]["固定ID"]
    if phase == "後続":
        rules = [r for r in rules if r["候補ID"] in fixed_ids]
        phases = ["後続検査"]
    else:
        phases = ["学習", "条件選択"]
    by_id, seen = defaultdict(list), set()
    event_count = 0
    feature_path = WORK / f"{phase}_入口事例.jsonl.gz"
    with gzip.open(feature_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            future = row["場"][:10] >= config["分割"]["後続開始日"]
            if future != (phase == "後続"):
                raise ValueError("実行段階外の事例を検出。読み進めず停止")
            period = "後続検査" if future else ("学習" if row["場"][:10] < config["分割"]["選択開始日"] else "条件選択")
            audit.check(row["イベントID"]+":期間", row["期間"], period)
            audit.check(row["イベントID"]+":ID重複", row["イベントID"] in seen, False)
            seen.add(row["イベントID"])
            expected = [r["候補ID"] for r in rules if qualifies(row, r)]
            audit.check(row["イベントID"]+":候補集合", sorted(row["候補IDs"]), sorted(expected))
            audit.check(row["イベントID"]+":空集合でない", bool(expected), True)
            for cid in expected:
                by_id[cid].append(row)
            event_count += 1
    independent, report_by_id = {}, {r["候補ID"]: r for r in report["結果"]}
    audit.check(phase+":集計候補集合", sorted(report_by_id), sorted(r["候補ID"] for r in rules))
    for candidate in rules:
        cid = candidate["候補ID"]
        independent[cid] = {}
        for period in phases:
            value = metrics([r for r in by_id[cid] if r["期間"] == period], period)
            independent[cid][period] = value
            for key, expected in value.items():
                audit.check(f"{cid}:{period}:{key}", report_by_id[cid][period]["入口"].get(key), expected)
    selected = None
    if phase == "探索":
        selected = selection(report["結果"], independent, config)
        for key, expected in selected.items():
            if key == "候補別資格":
                for cid, flags in expected.items():
                    for flag, value in flags.items():
                        audit.check(cid+":"+flag, report_by_id[cid].get(flag), value)
            else:
                audit.check("探索選定:"+key, report["選定"].get(key), expected)
                audit.check("選定固定:"+key, locked["選定"].get(key), expected)
        audit.check("探索結果固定SHA", locked["探索結果SHA256"], digest(study / "探索結果.json"))
    else:
        audit.check("後続候補は固定内", set(report_by_id) <= set(fixed_ids), True)
        audit.check("後続の選定固定SHA", report["選定固定SHA256"], digest(study / "選定固定.json"))
    sample_rows = sample_cases(by_id, fixed_ids, phases)
    csv_path = study / ("固定候補_探索事例.csv" if phase == "探索" else "後続事例.csv")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        saved = {(r["候補ID"], r["イベントID"]): r for r in csv.DictReader(stream)}
    expected_saved = {(cid, row["イベントID"]) for cid in fixed_ids for row in by_id[cid]}
    audit.check(phase+":固定事例集合", set(saved), expected_saved)
    manifest = read_json(study / "入力台帳.json")
    entries = {e["session"]: e for e in manifest["entries"]}
    cache_bank, samples = {}, []
    for cid, row in sample_rows:
        session = row["場"]
        if phase == "探索" and session[:10] >= config["分割"]["後続開始日"]:
            raise ValueError("新1場のキャッシュ読取を拒否")
        if session not in cache_bank:
            entry = entries[session]
            cache = ROOT / "work/複合検証" / entry["cache_path"]
            audit.check(session+":cacheSHA", digest(cache), entry["sha256_cache"])
            cache_bank[session] = normal_quotes(cache, session)
        _, _, cutoff, deadline = bounds(session)
        expected = direct_label(cache_bank[session], row["要求時計秒"], cutoff, deadline, row["side"], config["逆行pt"], config["順行pt"])
        for key, value in expected.items():
            audit.check(f"事例:{cid}:{row['イベントID']}:{key}", row.get(key), value)
        audit.check("固定CSVラベル:"+row["イベントID"], saved[(cid, row["イベントID"])]["ラベル"], expected["ラベル"])
        samples.append({"候補ID": cid, "イベントID": row["イベントID"], "場": session, "期間": row["期間"],
                        "方向": row["方向"], "要求時計秒": row["要求時計秒"], **expected})
    return {"段階": phase, "保存特徴イベント数": event_count, "照合候補数": len(rules), "照合期間": phases,
            "照合項目数": audit.count-before_checks, "不一致数": audit.errors-before_errors,
            "独立入口集計": independent, "独立選定": selected, "先着直接走査事例": samples,
            "先着事例選択": "各固定IDの先頭成功/失敗。計6件未満なら期間別の先頭を補い最大10件。存在しない種類は作らない。",
            "後続の再順位付け": False,
            "入力特徴展開SHA256": hashlib.sha256(gzip.decompress(feature_path.read_bytes())).hexdigest()}


def self_test() -> dict:
    """独立走査と間引きの主要境界を小さな人工列で確認する。

    引数: なし。
    返り値: dict は合成検査数。不一致はAssertionError。
    """
    q = np.array([[11, 1, 1000, 1005], [12, 2, 1255, 1260], [13, 3, 800, 805]], float)
    assert direct_label(q, 10, 800, 900, 1)["ラベル"] == "順行先着"
    assert direct_label(q, 10, 800, 900, 1)["判定時計秒"] == 12
    q = np.array([[11, 1, 1000, 1005], [12, 2, 745, 750]], float)
    assert direct_label(q, 10, 800, 900, -1)["ラベル"] == "順行先着"
    q = np.array([[11, 1, 1000, 1005], [400, 2, 1255, 1260], [901, 3, 1255, 1260]], float)
    assert direct_label(q, 10, 800, 900, 1)["ラベル"] == "観測不足"
    q = np.array([[11, 1, 1000, 1005], [311, 2, 1255, 1260]], float)
    assert direct_label(q, 10, 800, 900, 1)["ラベル"] == "順行先着"
    q = np.array([[40, 1, 1000, 1005], [100, 2, 1255, 1260]], float)
    assert direct_label(q, 10, 800, 100, 1)["ラベル"] == "順行先着"
    assert direct_label(q, 10, 40, 100, 1)["ラベル"] == "未約定"
    q = np.array([[11, 1, 1000, 1005], [100, 2, 1000, 1005]], float)
    assert direct_label(q, 10, 800, 100, 1)["ラベル"] == "期限未達"
    assert direct_label(q, 10, 800, 101, 1)["ラベル"] == "観測不足"
    labels = ["未約定", "順行先着", "逆行先着", "観測不足"]
    rows = [{"場": "2026-10-01_Day", "side": 1, "要求時計秒": now, "要求原板行": i, "ラベル": label}
            for i, (now, label) in enumerate(zip((0, 1799, 1800, 3600), labels))]
    value = metrics(rows, "合成")
    assert value["確認率"] == 1/3 and value["30分間引き_確認率"] == 0
    return {"合成検査数": 10, "不一致数": 0, "実データ使用": False}


def main() -> None:
    """監査段階と新1場読取の明示許可を受け取る。

    引数: なし。--study/--phase/--allow-future/--self-testを読む。
    返り値: None。不一致時は終了コード1。
    """
    parser = argparse.ArgumentParser(description="00008の保存入口に対する独立監査")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--phase", choices=("探索", "後続", "全部"), default="探索")
    parser.add_argument("--allow-future", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False))
        return
    if args.phase != "探索" and not args.allow_future:
        raise ValueError("後続の監査は実行完了連絡後に--allow-futureを明示する")
    study = args.study.resolve()
    config, audit = read_json(study / "条件.json"), 照合()
    phases = ("探索", "後続") if args.phase == "全部" else (args.phase,)
    sections = [audit_phase(study, phase, config, audit) for phase in phases]
    output = study / "入口独立監査.json" if args.phase != "後続" else study / "追加確認/入口独立監査.json"
    result = {"確認日時": datetime.now(JST).isoformat(), "全件一致": audit.errors == 0, "照合項目数": audit.count,
              "不一致数": audit.errors, "不一致": audit.examples, "コードSHA256": digest(Path(__file__)),
              "合成自己検査": self_test(), "段階別": sections,
              "方法": "探索.py/allowed/評価.py/気配経路をimportせず、保存特徴から買売別条件・候補集合・入口集計・支持・選定を別計算。固定事例は正常cacheの直接順走査。",
              "限界": "保存された和集合イベントの条件整合を監査する。どの条件にも保存されなかった全frame生成漏れ、指標値自体の全面再計算、未観測経路は保証しない。先着経路の原板照合は列挙した少数事例。費用候補の順位は別会計監査対象である保存運用集計を入力にする。"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"全件一致": result["全件一致"], "照合項目数": audit.count, "不一致数": audit.errors,
                      "段階": list(phases), "出力": output.relative_to(ROOT).as_posix()}, ensure_ascii=False))
    if audit.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
