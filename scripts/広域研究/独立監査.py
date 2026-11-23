"""固定された3分・開始幅失敗復帰15分・ADX環境だけを別実装で監査する。"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00006_外部手法を1分3分5分で比較"
WORK = ROOT / "work/広域研究"
JST = timezone(timedelta(hours=9))
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


def sha(path: Path) -> str:
    """小型入力・キャッシュのSHA256を計算する。

    引数: path (Path) は対象。
    返り値: str は16進ハッシュ。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    """UTF-8の成果物表を読む。

    引数: path (Path) はCSV。
    返り値: list[dict] は文字列セルの行。
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def times(session: str) -> tuple[float, float, float, float]:
    """場開始・ザラバ終了・新規停止・評価期限を独立に定義する。

    引数: session (str) は開始日基準の場名。
    返り値: tuple[float, float, float, float] は四つのUnix秒。
    """
    date = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        values = (date.replace(hour=8, minute=45), date.replace(hour=15, minute=40),
                  date.replace(hour=15, minute=25), date.replace(hour=15, minute=35))
    else:
        following = date + timedelta(days=1)
        values = (date.replace(hour=17), following.replace(hour=5, minute=55),
                  following.replace(hour=5, minute=40), following.replace(hour=5, minute=50))
    return tuple(item.timestamp() for item in values)


class Wilder:
    """差分14個の算術平均を種とする独立Wilder平均。"""

    def __init__(self) -> None:
        """未準備の平均を作る。

        引数: なし。
        返り値: None。
        """
        self.samples, self.value = [], None

    def add(self, value: float) -> float | None:
        """一差分を追加し、初期化後は1/14で更新する。

        引数: value (float) はTR・DM・DXの一観測。
        返り値: float | None は更新値または未準備。
        """
        if self.value is None:
            self.samples.append(value)
            if len(self.samples) == 14:
                self.value = sum(self.samples) / 14
        else:
            self.value += (value - self.value) / 14
        return self.value


class Indicator:
    """固定規則に必要なATR/DMI/ADXだけを独立に計算する。"""

    def __init__(self) -> None:
        """差分前足と平滑化を未準備へ戻す。

        引数: なし。
        返り値: None。
        """
        self.previous = None
        self.tr, self.plus, self.minus, self.adx = (Wilder() for _ in range(4))

    def add(self, item: dict) -> dict:
        """確定OHLCの差分から固定規則の指標を計算する。

        引数: item (dict) は今回の確定足。
        返り値: dict はATR・DI・ADX。未準備はNone。
        """
        result = dict.fromkeys(("atr", "plus_di", "minus_di", "adx"))
        if self.previous is not None:
            previous = self.previous
            true_range = max(item["high"] - item["low"], abs(item["high"] - previous["close"]), abs(item["low"] - previous["close"]))
            up, down = item["high"] - previous["high"], previous["low"] - item["low"]
            atr = self.tr.add(true_range)
            positive = self.plus.add(up if up > 0 and up > down else 0.)
            negative = self.minus.add(down if down > 0 and down > up else 0.)
            result["atr"] = atr
            if atr is not None:
                pdi, mdi = (100 * positive / atr, 100 * negative / atr) if atr > 0 else (0., 0.)
                dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi > 0 else 0.
                result.update(plus_di=pdi, minus_di=mdi, adx=self.adx.add(dx))
        self.previous = item
        return result


# ----------------------------------------
# キャッシュの固定検査と、3分の確定OHLC・利用可能時刻の独立再構成。

def load_session(entry: dict) -> tuple[dict[str, np.ndarray], list[dict]]:
    """価格時計の場内非後退列から、3分足と正常気配を直接形成する。

    引数: entry (dict) は64場台帳の一行。
    返り値: tuple は正常気配4列と、同時計原順・半開3分足の列。
    """
    begin, finish, _, _ = times(entry["session"])
    source = ROOT.parent / "JP_OSE_Data/future" / entry["source_path"]
    status = source.stat()
    if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
        raise ValueError("固定原板statが不一致")
    path = ROOT / "work/複合検証" / entry["cache_path"]
    if sha(path) != entry["sha256_cache"]:
        raise ValueError("固定キャッシュSHAが不一致")
    with np.load(path, allow_pickle=False) as archive:
        data = {key: archive[key] for key in ("now", "line", "last", "bid", "ask", "valid")}
    positions = np.flatnonzero(np.isfinite(data["now"]) & (data["now"] >= begin) & (data["now"] <= finish))
    now = data["now"][positions]
    positions = positions[np.r_[True, now[1:] >= np.maximum.accumulate(now[:-1])]]
    observed = {key: values[positions] for key, values in data.items()}
    normal = observed["valid"].astype(bool)
    quotes = {key: observed[key][normal] for key in ("now", "line", "bid", "ask")}
    positive = np.isfinite(observed["last"]) & (observed["last"] > 0) & (observed["now"] < finish)
    price_now, prices = observed["now"][positive], observed["last"][positive]
    indices = ((price_now - begin) // 180).astype(int)
    heads = np.flatnonzero(np.r_[True, indices[1:] != indices[:-1]])
    tails = np.r_[heads[1:], len(prices)]
    bars, previous = [], None
    for head, tail in zip(heads, tails):
        index = int(indices[head])
        end = begin + (index + 1) * 180
        if end > finish:
            continue
        confirm_index = int(np.searchsorted(observed["now"], end, side="left"))
        known = confirm_index < len(observed["now"])
        values = prices[head:tail]
        bars.append({"index": index, "start": begin + index * 180, "end": end,
                     "open": float(values[0]), "high": float(np.max(values)), "low": float(np.min(values)), "close": float(values[-1]),
                     "missing": index if previous is None else index - previous - 1,
                     "confirm": float(observed["now"][confirm_index]) if known else finish,
                     "confirm_line": int(observed["line"][confirm_index]) if known else 0, "publish": known})
        previous = index
    return quotes, bars


def select_from_bars(entry: dict, bars: list[dict], state: Indicator) -> list[dict]:
    """開始15分幅・失敗復帰・ADX<20を未来ラベルを見ずに選ぶ。

    引数: entry (dict) は場情報、bars (list[dict]) は独立3分足、state (Indicator) は同限月の履歴。
    返り値: list[dict] は固定規則だけの独立入口。新規後続の他候補ラベルは作らない。
    """
    session = entry["session"]
    begin, finish, cutoff, deadline = times(session)
    previous = None
    opening, opening_valid, opening_bars = None, True, []
    result = []
    for item in bars:
        if item["missing"]:
            state.__init__()
            previous, opening_valid = None, False
        indicator = state.add(item)
        if item["start"] < begin + 900:
            opening_bars.append(item)
        if opening_valid and item["end"] == begin + 900:
            opening = max(frame["high"] for frame in opening_bars), min(frame["low"] for frame in opening_bars)
        if (item["publish"] and previous is not None and opening is not None and item["start"] >= begin + 900
                and indicator["atr"] is not None and indicator["atr"] > 0 and indicator["adx"] is not None and indicator["adx"] < 20
                and item["confirm"] < cutoff and deadline - item["confirm"] >= 3600):
            high, low = opening
            for side in (1, -1):
                triggered = previous["close"] < low <= item["close"] <= high if side == 1 else previous["close"] > high >= item["close"] >= low
                if triggered:
                    result.append({**item, **indicator, "場": session, "時間足分": 3, "side": side,
                                   "方向": "買い" if side == 1 else "売り", "開始幅高値": high, "開始幅安値": low,
                                   "前終値": previous["close"], "要求時計秒": item["confirm"], "要求原板行": item["confirm_line"],
                                   "確認遅延秒": item["confirm"] - item["end"], "新規停止時計秒": cutoff, "期限時計秒": deadline,
                                   "イベントID": f"NK225_{session}_3分_{item['index']:04d}_{side}"})
        previous = item
    complete = int((finish - begin) // 180)
    if not bars or bars[-1]["index"] < complete - 1:
        state.__init__()
    return result


def direct_label(quotes: dict[str, np.ndarray], row: dict) -> dict:
    """区間木を使わず、固定入口の最初の閾値到達を気配配列で検算する。

    引数: quotes (dict[str,np.ndarray]) は正常気配、row (dict) は固定入口。
    返り値: dict はラベル・原行・時計・MFE/MAE。到達後の経路は使わない。
    """
    numeric_keys = ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")
    empty = {"ラベル": "未約定", "理由": "30秒内に正常板なし", **dict.fromkeys(numeric_keys)}
    if row["確認遅延秒"] > 30:
        return {**empty, "理由": "足確定確認遅延30秒超"}
    now = quotes["now"]
    first = int(np.searchsorted(now, row["要求時計秒"] + 1, side="left"))
    if first >= len(now) or now[first] > row["要求時計秒"] + 30 or now[first] >= row["新規停止時計秒"]:
        return empty
    side = row["side"]
    entry = float(quotes["ask"][first] if side == 1 else quotes["bid"][first])
    mark = quotes["bid"] if side == 1 else quotes["ask"]
    deadline = row["期限時計秒"]
    last = int(np.searchsorted(now, deadline, side="right")) - 1
    distances = side * (mark[first:last + 1] - entry)
    crossings = np.flatnonzero((distances <= -125) | (distances >= 250))
    hit = first + int(crossings[0]) if len(crossings) else None
    gaps = np.flatnonzero((np.diff(now[first:]) > 300) & (now[first:-1] + 300 < deadline))
    gap_left = first + int(gaps[0]) if len(gaps) else None
    if hit is not None and (gap_left is None or hit <= gap_left):
        last = hit
        label = "順行先着" if side * (mark[last] - entry) >= 250 else "逆行先着"
        reason = "返済気配の閾値初着"
    else:
        if gap_left is not None:
            last = gap_left
        if gap_left is not None or deadline - now[last] > 300:
            label, reason = "観測不足", "正常板価格時計300秒超空白"
        elif now[-1] < deadline:
            label, reason = "観測不足", "入力末尾不足"
        else:
            label, reason = "期限未達", "期限内どちらも未到達"
    distances = side * (mark[first:last + 1] - entry)
    return {"ラベル": label, "理由": reason, "新規価格": entry,
            "新規時計秒": float(now[first]), "新規原板行": int(quotes["line"][first]),
            "判定時計秒": float(now[last]), "判定原板行": int(quotes["line"][last]),
            "判定気配": float(mark[last]), "最大順行pt": float(max(0., np.max(distances))),
            "最大逆行pt": float(max(0., -np.min(distances))), "所要分": float((now[last] - now[first]) / 60)}


# ----------------------------------------
# 集計・間引き・対照の別計算。評価.pyは読み込まない。

def summarize(rows: list[dict], phase: str) -> tuple[dict, list[str]]:
    """五分類、日数、Wilson参考区間、要求時計30分間引きを別集計する。

    引数: rows (list[dict]) は固定候補、phase (str) は分割。
    返り値: tuple[dict,list[str]] は集計と間引き採用イベントID。
    """
    counts = Counter(row["ラベル"] for row in rows)
    filled = [row for row in rows if row["ラベル"] != "未約定"]
    successes = [row for row in rows if row["ラベル"] == "順行先着"]
    days = Counter(row["場"][:10] for row in successes)
    n, k = len(filled), len(successes)
    if n:
        z = NormalDist().inv_cdf(.975)
        center = (k + z * z / 2) / (n + z * z)
        radius = z * math.sqrt(k * (n - k) / n + z * z / 4) / (n + z * z)
        interval = max(0., center - radius), min(1., center + radius)
    else:
        interval = None, None
    result = {"候補数": len(rows), "約定候補数": n, **{label: counts[label] for label in LABELS},
              "確認率": k / n if n else None, "候補場数": len({row["場"] for row in rows}),
              "約定場数": len({row["場"] for row in filled}), "候補開始日数": len({row["場"][:10] for row in rows}),
              "約定開始日数": len({row["場"][:10] for row in filled}), "成功開始日数": len(days),
              "最大成功日寄与率": max(days.values()) / k if k else None, "分割": phase,
              "Wilson95下限_独立参考": interval[0], "Wilson95上限_独立参考": interval[1]}
    kept, latest = [], {}
    for row in sorted(rows, key=lambda item: (Decimal(str(item["要求時計秒"])), item["要求原板行"], item["イベントID"])):
        key = row["場"], row["時間足分"], row["side"]
        now = Decimal(str(row["要求時計秒"]))
        if key not in latest or now - latest[key] >= 1800:
            kept.append(row)
            latest[key] = now
    reduced = [row for row in kept if row["ラベル"] != "未約定"]
    winners = sum(row["ラベル"] == "順行先着" for row in kept)
    result.update({"30分間引き_候補数": len(kept), "30分間引き_約定候補数": len(reduced),
                   "30分間引き_順行先着": winners, "30分間引き_確認率": winners / len(reduced) if reduced else None,
                   "30分間引き_候補場数": len({row["場"] for row in kept}),
                   "30分間引き_約定場数": len({row["場"] for row in reduced}),
                   "30分間引き_約定開始日数": len({row["場"][:10] for row in reduced})})
    return result, [row["イベントID"] for row in kept]


def run() -> dict:
    """固定候補の旧60と新4だけを独立再構成し、正式監査JSONを保存する。

    引数: なし。00006の固定された入力・候補だけを使用する。
    返り値: dict は照合件数・集計・少数旧入口と新14入口の検証記録。
    """
    config = json.loads((STUDY / "条件.json").read_text(encoding="utf-8"))
    lock = json.loads((STUDY / "選択固定.json").read_text(encoding="utf-8"))
    follow = json.loads((STUDY / "後続結果.json").read_text(encoding="utf-8"))
    manifest = json.loads((STUDY / "入力台帳.json").read_text(encoding="utf-8"))
    if lock["候補ID"] != "3分_開始幅失敗復帰_15_ADX環境":
        raise ValueError("この監査は固定された3分開始幅失敗復帰15/ADXだけを対象とする")
    source_rows = {}
    for path in (WORK / "00006_探索事例.jsonl.gz", WORK / "00006_後続事例.jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for raw in stream:
                row = json.loads(raw)
                if row["時間足分"] == 3:
                    source_rows[row["イベントID"]] = row
    old_selected = [row for row in source_rows.values() if row["場"][:10] < "2026-11-02" and
                    row[f"開始幅失敗復帰_15_{row['side']}"] and row["adx"] is not None and row["adx"] < 20]
    post_selected = [row for row in source_rows.values() if row["場"][:10] >= "2026-11-02"]
    reference = old_selected + post_selected
    reference_by_id = {row["イベントID"]: row for row in reference}
    expected_rule = {"候補ID": lock["候補ID"], "時間足分": 3, "手法": "開始幅失敗復帰", "パラメータ": 15, "補助": "ADX環境"}
    report = {"確認日時": datetime.now(JST).isoformat(), "候補ID": lock["候補ID"], "全件一致": False,
              "照合項目数": 0, "不一致": [], "独立集計": {}, "間引き採用ID": {}, "入口先着確認": [],
              "方法": "検証.py/評価.pyをimportせず、固定cacheの3分OHLC・確認原行・Wilder ATR/DMI/ADX・開始15分幅から固定規則だけのマスクを別実装で再構成。原板本文を再読しない。",
              "制約": "新4はこの固定規則の特徴と選択だけを再構成し、他候補のラベル計算・比較・再順位付けをしない。運用損益は計算しない。"}

    def check(name: str, actual: Any, expected: Any) -> None:
        """照合を記録し、不一致を漏らさず保存する。

        引数: name (str) は項目、actual/expected (Any) は独立値と正本値。
        返り値: None。浮動小数は絶対許容差1e-8で比較する。
        """
        report["照合項目数"] += 1
        equal = math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=1e-8) if isinstance(actual, (int, float)) and isinstance(expected, (int, float)) else actual == expected
        if not equal:
            report["不一致"].append({"項目": name, "独立値": actual, "正本値": expected})

    check("固定規則", lock["規則"], expected_rule)
    check("後続の固定参照SHA", follow["選択固定SHA256"], sha(STUDY / "選択固定.json"))
    for relative, expected in lock["ファイルSHA256"].items():
        check("固定SHA:" + relative, sha(ROOT / relative), expected)
    representatives = []
    for label in LABELS:
        part = sorted((row for row in old_selected if row["ラベル"] == label), key=lambda item: (item["要求時計秒"], item["要求原板行"], item["イベントID"]))
        if part:
            representatives.append(part[0]["イベントID"])
    for side in (1, -1):
        part = sorted((row for row in old_selected if row["side"] == side), key=lambda item: item["要求時計秒"])
        if part:
            representatives.append(part[0]["イベントID"])
    audit_ids = set(representatives) | {row["イベントID"] for row in post_selected}
    state, previous_contract, independent_rows = Indicator(), None, []
    for entry in manifest["entries"]:
        contract = tuple(entry["in_session_contract_codes"])
        if previous_contract is not None and contract != previous_contract:
            state = Indicator()
        previous_contract = contract
        quotes, bars = load_session(entry)
        selected = select_from_bars(entry, bars, state)
        independent_rows.extend(selected)
        for row in selected:
            identity = row["イベントID"]
            if identity not in reference_by_id:
                continue
            original = reference_by_id[identity]
            for key in ("open", "high", "low", "close", "atr", "plus_di", "minus_di", "adx", "start", "end", "confirm", "confirm_line", "missing", "要求時計秒", "要求原板行", "確認遅延秒"):
                check(identity + ":" + key, row[key], original[key])
            if identity in audit_ids:
                outcome = direct_label(quotes, row)
                for key, value in outcome.items():
                    check(identity + ":先着:" + key, value, original[key])
                report["入口先着確認"].append({"イベントID": identity, "範囲": "既使用代表" if row["場"][:10] < "2026-11-02" else "新4固定候補",
                                               "開始幅高値": row["開始幅高値"], "開始幅安値": row["開始幅安値"], "前終値": row["前終値"],
                                               "今終値": row["close"], "ADX": row["adx"], "独立判定": outcome})
    check("全固定入口ID集合", sorted(row["イベントID"] for row in independent_rows), sorted(reference_by_id))
    phases = {"学習": [row for row in reference if row["場"][:10] < "2026-10-19"],
              "条件選択": [row for row in reference if "2026-10-19" <= row["場"][:10] < "2026-11-02"],
              "後続検査": [row for row in reference if row["場"][:10] >= "2026-11-02"]}
    candidate_table = read_csv(STUDY / "全候補_探索.csv")
    candidate = next(row for row in candidate_table if row["候補ID"] == lock["候補ID"])
    for phase, rows in phases.items():
        stats, kept = summarize(rows, phase)
        if phase != "後続検査":
            opposite = {(row["場"], row["index"], row["side"]): row for row in source_rows.values() if row["場"][:10] < "2026-11-02"}
            control = [other for row in rows for other in (row, opposite[(row["場"], row["index"], -row["side"])])]
            numerator = sum(row["ラベル"] == "順行先着" for row in control)
            denominator = sum(row["ラベル"] != "未約定" for row in control)
            stats["同時刻両方向対照率"] = numerator / denominator
            stats["同時刻差pp"] = 100 * (stats["確認率"] - stats["同時刻両方向対照率"])
        expected = follow["結果"] if phase == "後続検査" else lock["探索結果"][phase]
        for key, value in stats.items():
            check(phase + ":集計:" + key, value, expected[key])
            if phase != "後続検査" and key != "分割":
                stored = candidate[phase + "_" + key]
                check(phase + ":全候補CSV:" + key, value, None if stored == "" else float(stored))
        report["独立集計"][phase], report["間引き採用ID"][phase] = stats, kept
    post_csv = read_csv(STUDY / "後続事例.csv")
    check("新4正式事例のID集合", sorted(row["イベントID"] for row in post_csv), sorted(row["イベントID"] for row in post_selected))
    old_csv = read_csv(STUDY / "固定候補_探索事例.csv")
    check("旧60正式事例のID集合", sorted(row["イベントID"] for row in old_csv), sorted(row["イベントID"] for row in old_selected))
    for table in (old_csv, post_csv):
        for row in table:
            original = reference_by_id[row["イベントID"]]
            for key, stored in row.items():
                expected = original[key]
                actual = None if stored == "" else float(stored) if isinstance(expected, (int, float)) else stored
                check("正式CSV:" + row["イベントID"] + ":" + key, actual, expected)
    for phase in ("学習", "条件選択"):
        limits = config["支持条件"][phase]
        check(phase + ":最低支持", all(report["独立集計"][phase][key] >= value for key, value in limits.items()), True)
    exploration_target = all(report["独立集計"][phase]["確認率"] >= config["目標率"]
                             and report["独立集計"][phase]["30分間引き_約定候補数"] >= config["間引き支持"][phase]
                             and report["独立集計"][phase]["30分間引き_確認率"] >= config["目標率"] for phase in ("学習", "条件選択"))
    check("固定候補の探索70条件", exploration_target, candidate["探索70条件"] == "True")
    post = report["独立集計"]["後続検査"]
    support = {key: {"独立値": post[key], "下限": value, "合格": post[key] >= value} for key, value in config["支持条件"]["後続検査"].items()}
    check("後続支持", all(item["合格"] for item in support.values()), follow["支持条件"])
    reached = bool(lock["探索70候補数"] and all(item["合格"] for item in support.values()) and post["確認率"] >= .7
                   and post["30分間引き_約定候補数"] >= 10 and post["30分間引き_確認率"] >= .7)
    check("探索後続70条件", reached, follow["探索後続70条件"])
    report.update(全件一致=not report["不一致"], 固定入口数=len(independent_rows), 既使用代表先着数=len(set(representatives)), 新4先着照合数=len(post_selected), 後続支持内訳=support)
    paths = [Path(__file__), STUDY / "条件.json", STUDY / "入力台帳.json", STUDY / "選択固定.json", STUDY / "全候補_探索.csv",
             STUDY / "後続結果.json", STUDY / "後続事例.csv", STUDY / "固定候補_探索事例.csv",
             WORK / "00006_探索事例.jsonl.gz", WORK / "00006_後続事例.jsonl.gz"]
    report["ファイルSHA256"] = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    for path in (STUDY / "独立監査.json", WORK / "独立監査.json"):
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("全件一致", "照合項目数", "固定入口数", "既使用代表先着数", "新4先着照合数", "独立集計", "不一致")}, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    if not run()["全件一致"]:
        raise SystemExit(1)
