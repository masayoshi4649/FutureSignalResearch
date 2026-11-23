"""00012の全構造注文を、正常板の原順と設定足から独立に確認する。"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00012_BB反転の確認と構造リスク"
WORK = ROOT / "work/反転確認/00012"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
HELPER = ROOT / "scripts/利益回収/出口独立確認.py"


def helper() -> Any:
    """独立監査の正常板読取補助だけを読み込む。

    引数: なし。
    返り値: Any は固定cache読取と場内時刻の補助。運用・入口・検証は読み込まない。
    """
    spec = importlib.util.spec_from_file_location("構造確認の独立正常板", HELPER)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


B = helper()


class Audit:
    """照合数と不一致を保持する。"""

    def __init__(self) -> None:
        """空の照合を作る。

        引数: なし。
        返り値: None。
        """
        self.count, self.error_count, self.errors = 0, 0, []

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """独立値と保存値を照合する。

        引数: name (str) は項目、actual/expected (Any) は値。
        返り値: None。不一致の先頭100件と総数を記録する。
        """
        self.count += 1
        same = abs(float(actual) - float(expected)) <= 1e-7 if isinstance(actual, (int, float)) and isinstance(expected, (int, float)) else actual == expected
        if not same:
            self.error_count += 1
            if len(self.errors) < 100:
                self.errors.append({"項目": name, "独立": actual, "保存": expected})


def read_gzip(path: Path) -> tuple[list[dict], str]:
    """gzip本文を指紋化してJSON行を読む。

    引数: path (Path) は入力。
    返り値: tuple[list[dict],str] は行と展開内容SHA256。
    """
    rows, digest = [], hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for raw in stream:
            digest.update(raw)
            rows.append(json.loads(raw))
    return rows, digest.hexdigest()


def quote_point(row: dict | None) -> dict | None:
    """正常板の少数点だけを報告へ残す。

    引数: row (dict|None) は正常板。
    返り値: dict|None は時計・原行・Bid・Ask。
    """
    return None if row is None else {k: row[k] for k in ("now", "line", "bid", "ask")}


# ----------------------------------------
# 要求時に既知の板と、設定足の原価格から構造価格を独立に確認する。

def settings(signals: list[dict], raw: list[dict], audit: Audit) -> None:
    """設定足の高安・終値とL−5/H＋5、当時既知の固定情報を照合する。

    引数: signals (list[dict]) は同場の4入口、raw (list[dict]) は場内非後退状態、
    audit (Audit) は照合先。
    返り値: None。入口のBB/ADX発動条件自体は再実装しない。
    """
    times = [row["now"] for row in raw]
    cached = {}
    for signal in signals:
        prefix = signal["イベントID"]
        setup, side = signal["設定足"], signal["side"]
        expected = setup["low"] - 5 if side == 1 else setup["high"] + 5
        audit.check(prefix + ":設定構造", signal["構造価格"], expected)
        audit.check(prefix + ":設定中心固定", signal["bb_mean"], setup["bb_mean"])
        audit.check(prefix + ":設定は要求時に既知",
                    (setup["confirm"], setup["confirm_line"]) <= (signal["要求時計秒"], signal["要求原板行"]), True)
        audit.check(prefix + ":設定終了は要求以下", setup["end"] <= signal["要求時計秒"], True)
        key = signal["時間足分"], setup["end"]
        if key not in cached:
            left = setup["end"] - signal["時間足分"] * 60
            a, b = bisect_left(times, left), bisect_left(times, setup["end"])
            values = [row["last"] for row in raw[a:b] if math.isfinite(row["last"]) and row["last"] > 0]
            cached[key] = (max(values), min(values), values[-1]) if values else (None, None, None)
        for field, actual in zip(("high", "low", "close"), cached[key]):
            audit.check(prefix + ":原価格設定足:" + field, setup[field], actual)


def exit_request(quotes: list[dict], first: int, entry: float, side: int, stop: float,
                 force: float) -> tuple[float, int, str]:
    """実新規からhard125→構造→TP、期限の最初の要求を求める。

    引数: quotes (list[dict]) は正常板、first (int) は新規位置、entry (float) は新規価格、
    side (int) は方向、stop (float) は固定chartstop、force (float) は期限。
    返り値: tuple[float,int,str] は要求時計・原行・理由。
    """
    for row in quotes[first:]:
        if row["now"] >= force:
            return force, 0, "期限"
        mark = row["bid"] if side == 1 else row["ask"]
        distance = side * (mark - entry)
        if distance <= -125:
            return row["now"], row["line"], "保護"
        if side * (mark - stop) <= 0:
            return row["now"], row["line"], "構造保護"
        if distance >= 250:
            return row["now"], row["line"], "利確"
    return force, 0, "期限"


def dispatch(detail: dict, cases: dict[str, dict], audit: Audit) -> None:
    """入口取扱の抑止根拠と送信候補の欠落がないことを確認する。

    引数: detail (dict) は一候補一場、cases (dict[str,dict]) は同場の入口、
    audit (Audit) は照合先。
    返り値: None。建玉状態は保存された実約定の時点だけから復元する。
    """
    source = detail["候補ID"].removesuffix("_構造")
    rows = detail["入口取扱"]
    selected = [s for s in cases.values() if s["入口ID"] == source]
    prefix = detail["候補ID"] + "/" + detail["場"]
    audit.check(prefix + ":入口取扱全件", {r["イベントID"] for r in rows}, {s["イベントID"] for s in selected})
    orders = [o for o in detail["注文"] if o["区分"] == "新規"]
    entries = {f["entry_event_id"]: f for f in detail["約定"] if f["type"].endswith("N")}
    returns = {f["entry_event_id"]: f for f in detail["約定"] if f["type"].endswith("R")}
    _, end, _ = B.bounds(detail["場"])
    cutoff = end - 900
    groups = defaultdict(set)
    for row in rows:
        groups[(row["要求時計秒"], row["要求原板行"])].add(row["side"])
    for row in rows:
        signal, key = cases[row["イベントID"]], (row["要求時計秒"], row["要求原板行"])
        held = any((f["price_clock"], f["source_line"]) <= key < (
                    returns[event]["price_clock"], returns[event]["source_line"]) if event in returns else
                    (f["price_clock"], f["source_line"]) <= key
                   for event, f in entries.items())
        waiting = False
        for order in orders:
            if order["入口イベントID"] == row["イベントID"] or order.get("送信前取消"):
                continue
            request = order["要求時計秒"], order["要求原板行"]
            if request > key or key[0] > request[0] + 30 or key[0] >= cutoff:
                continue
            fill = entries.get(order["入口イベントID"])
            waiting |= fill is None or key < (fill["price_clock"], fill["source_line"])
        expected = "同時両方向見送り" if groups[key] == {1, -1} else (
            "足確定確認遅延30秒超" if signal["確認遅延秒"] > 30 else (
            "新規停止時刻外" if key[0] >= cutoff else (
            "建玉中抑止" if held else "注文待機中抑止" if waiting else None)))
        if expected is not None:
            audit.check(prefix + ":抑止:" + row["イベントID"], row["取扱"], expected)
        else:
            own = [o for o in orders if o["入口イベントID"] == row["イベントID"]]
            audit.check(prefix + ":送信候補記録:" + row["イベントID"], len(own), 1)


# ----------------------------------------
# 全構造注文の新規審査・送信後の実約定・最初の保護要求・返済を直接確認する。

def audit_detail(detail: dict, cases: dict[str, dict], quotes: list[dict],
                 audit: Audit, examples: dict, counters: Counter) -> None:
    """一候補一場の全注文を正常板へ照合する。

    引数: detail/cases (dict) は運用と入口正本、quotes (list[dict]) は正常板、
    audit (Audit) は比較先、examples (dict) は時刻順先頭の例、counters (Counter) は件数。
    返り値: None。運用coreと純入口ラベルは呼ばない。
    """
    cid, session = detail["候補ID"], detail["場"]
    keys, times = [(q["now"], q["line"]) for q in quotes], [q["now"] for q in quotes]
    _, end, force = B.bounds(session)
    cutoff = end - 900
    fills_by_order = defaultdict(list)
    for fill in detail["約定"]:
        fills_by_order[fill["order_id"]].append(fill)
    trades = {t["入口イベントID"]: t for t in detail["取引"]}
    counters["構造候補場数"] += 1
    dispatch(detail, cases, audit)
    own_counts, covered_returns = Counter(), set()
    for order in detail["注文"]:
        if order["区分"] != "新規":
            continue
        counters["新規注文数"] += 1
        event, name = order["入口イベントID"], cid + "/" + session + "/" + order["注文ID"]
        signal, side = cases[event], cases[event]["side"]
        structure, now, line = signal["構造価格"], order["要求時計秒"], order["要求原板行"]
        audit.check(name + ":元要求時計", now, signal["要求時計秒"])
        audit.check(name + ":元要求原行", line, signal["要求原板行"])
        index = bisect_right(keys, (now, line)) - 1
        known = quotes[index] if index >= 0 else None
        stale = known is None or now - known["now"] > 30
        mark = None if stale else known["bid"] if side == 1 else known["ask"]
        invalid = not stale and side * (mark - structure) <= 0
        for key, expected in (("構造価格", structure), ("構造参照時計秒", None if known is None else known["now"]),
                              ("構造参照原板行", None if known is None else known["line"]),
                              ("構造参照Bid", None if known is None else known["bid"]),
                              ("構造参照Ask", None if known is None else known["ask"]),
                              ("構造参照板の古さ秒", None if known is None else now-known["now"])):
            audit.check(name + ":" + key, order.get(key), expected)
        if stale or invalid:
            reason = "構造未確認で送信前取消" if stale else "構造無効で送信前取消"
            for key, expected in (("状態", reason), ("取消理由", reason), ("送信前取消", True),
                                  ("取消時計秒", now), ("取消原板行", line), ("取消判定気配", mark)):
                audit.check(name + ":" + key, order.get(key), expected)
            audit.check(name + ":無約定", len(fills_by_order[order["注文ID"]]), 0)
            audit.check(name + ":無費用", order.get("手数料円", 0), 0)
            own_counts["未確認取消" if stale else "無効取消"] += 1
            counters["未確認取消" if stale else "無効取消"] += 1
            category = "未確認送信前取消" if stale else "無効送信前取消"
            candidate = {"種類": category, "候補ID": cid, "場": session, "入口ID": event,
                         "要求時計": now, "要求原行": line, "構造価格": structure,
                         "要求時既知板": quote_point(known), "鮮度秒": None if known is None else now-known["now"],
                         "取消理由": reason, "約定片数": 0, "手数料円": 0}
        else:
            audit.check(name + ":送信前確認", order.get("送信前構造確認"), True)
            audit.check(name + ":無償取消なし", bool(order.get("送信前取消")), False)
            first = bisect_left(times, now + 1)
            executable = first < len(quotes) and times[first] <= now + 30 and times[first] < cutoff
            if not executable:
                audit.check(name + ":失効状態", order["状態"], "新規停止または30秒失効")
                audit.check(name + ":失効無約定", len(fills_by_order[order["注文ID"]]), 0)
                counters["送信後未約定失効"] += 1
                continue
            entry_quote = quotes[first]
            entry_price = entry_quote["ask"] if side == 1 else entry_quote["bid"]
            opening = fills_by_order[order["注文ID"]]
            audit.check(name + ":新規1片", len(opening), 1)
            if len(opening) != 1:
                continue
            fill = opening[0]
            for key, expected in (("状態", "約定"), ("約定時計秒", entry_quote["now"]), ("約定原板行", entry_quote["line"]),
                                  ("約定価格", entry_price), ("手数料円", 11)):
                audit.check(name + ":" + key, order[key], expected)
            for key, expected in (("price_clock", entry_quote["now"]), ("source_line", entry_quote["line"]),
                                  ("price", entry_price), ("fee_yen", 11), ("qty", 1)):
                audit.check(name + ":新規片:" + key, fill[key], expected)
            counters["実新規数"] += 1
            entry_mark = entry_quote["bid"] if side == 1 else entry_quote["ask"]
            broken_after_send = side * (entry_mark - structure) <= 0
            counters["送信後の約定板で構造無効"] += int(broken_after_send)
            hard = entry_price - side * 125
            stop = max(hard, structure) if side == 1 else min(hard, structure)
            request_time, request_line, reason = exit_request(quotes, first, entry_price, side, stop, force)
            returns = [o for o in detail["注文"] if o["区分"] == "返済" and o["入口イベントID"] == event]
            audit.check(name + ":返済要求1件", len(returns), 1)
            if len(returns) != 1:
                continue
            returned = returns[0]
            covered_returns.add(returned["注文ID"])
            for key, expected in (("要求時計秒", request_time), ("要求原板行", request_line), ("理由", reason)):
                audit.check(name + ":最初要求:" + key, returned[key], expected)
            final = bisect_left(times, request_time + 1)
            trade = trades.get(event)
            if final < len(quotes):
                q = quotes[final]
                exit_price = q["bid"] if side == 1 else q["ask"]
                actual_return = fills_by_order[returned["注文ID"]]
                audit.check(name + ":返済1片", len(actual_return), 1)
                if actual_return:
                    for key, expected in (("price_clock", q["now"]), ("source_line", q["line"]), ("price", exit_price), ("fee_yen", 11)):
                        audit.check(name + ":返済片:" + key, actual_return[0][key], expected)
                audit.check(name + ":完結取引あり", trade is not None, True)
                if trade is not None:
                    expected_fields = {"初期125保護価格": hard, "保護価格": stop, "構造価格": structure,
                                       "設定足": signal["設定足"], "確認方式": signal["確認方式"],
                                       "返済要求時計秒": request_time, "返済要求原板行": request_line, "返済理由": reason,
                                       "返済時計秒": q["now"], "返済原板行": q["line"], "返済価格": exit_price,
                                       "固定利確使用": True, "利確価格": entry_price + side * 250}
                    for key, expected in expected_fields.items():
                        audit.check(name + ":構造固定:" + key, trade[key], expected)
                    own_counts["構造返済"] += int(reason == "構造保護")
                    counters["完結取引数"] += 1
            else:
                audit.check(name + ":未解消待機", returned["状態"], "待機")
                audit.check(name + ":未解消無返済", len(fills_by_order[returned["注文ID"]]), 0)
                counters["未解消数"] += 1
            category = "送信後構造破れでも実約定" if broken_after_send else "通常構造保護返済" if reason == "構造保護" else "その他実約定"
            candidate = {"種類": category, "候補ID": cid, "場": session, "入口ID": event, "方向": signal["方向"],
                         "要求時計": now, "要求原行": line, "要求時既知板": quote_point(known),
                         "構造価格": structure, "初期125保護価格": hard, "chartstop": stop,
                         "実新規板": quote_point(entry_quote), "実新規価格": entry_price,
                         "最初返済要求": {"時計": request_time, "原行": request_line, "理由": reason},
                         "実返済板": quote_point(quotes[final]) if final < len(quotes) else None,
                         "往復費用円": 22 if trade is not None else None}
        key = candidate["要求時計"], candidate["要求原行"], cid
        if category not in examples or key < examples[category][0]:
            examples[category] = key, candidate
    audit.check(cid + session + ":全返済注文照合", covered_returns, {o["注文ID"] for o in detail["注文"] if o["区分"] == "返済"})
    for field, expected in (("構造未確認新規取消数", own_counts["未確認取消"]),
                            ("構造無効新規取消数", own_counts["無効取消"]),
                            ("構造保護返済数", own_counts["構造返済"])):
        audit.check(cid + session + ":" + field, detail["品質"][field], expected)


def run() -> dict:
    """完了後の全4構造候補について因果・保護・返済を独立確認する。

    引数: なし。実行許可後に呼ぶ。固定入力と完成した作業成果物だけを読む。
    返り値: dict は明示合否・全件数・少数例・版指紋。
    """
    if not (STUDY / "結果.json").is_file():
        raise ValueError("正式再生完了前には実行しない")
    artifacts = json.loads((STUDY / "作業成果物.json").read_text(encoding="utf-8"))["ファイル"]
    details, detail_sha = read_gzip(WORK / "全運用詳細.jsonl.gz")
    signals, signal_sha = read_gzip(WORK / "入口事例.jsonl.gz")
    for name, actual in (("全運用詳細.jsonl.gz", detail_sha), ("入口事例.jsonl.gz", signal_sha)):
        expected = next(f["展開内容SHA256"] for f in artifacts if Path(f["パス"]).name == name)
        if expected != actual:
            raise ValueError("作業成果物の展開指紋不一致: " + name)
    audit, counters, examples = Audit(), Counter(), {}
    grouped_signals, grouped_details = defaultdict(dict), defaultdict(list)
    for signal in signals:
        if signal["イベントID"] in grouped_signals[signal["場"]]:
            raise ValueError("入口イベント重複")
        grouped_signals[signal["場"]][signal["イベントID"]] = signal
    for detail in details:
        if detail["候補ID"].endswith("_構造"):
            grouped_details[detail["場"]].append(detail)
    manifest = json.loads(INPUT.read_text(encoding="utf-8"))
    fingerprints = []
    for entry in manifest["entries"]:
        session = entry["session"]
        raw, quotes = B.load(entry)
        settings(list(grouped_signals[session].values()), raw, audit)
        audit.check(session + ":構造4候補", len(grouped_details[session]), 4)
        for detail in grouped_details[session]:
            audit_detail(detail, grouped_signals[session], quotes, audit, examples, counters)
        fingerprints.append({"場": session, "cacheSHA256": entry["sha256_cache"]})
    chosen = [examples[k][1] for k in ("未確認送信前取消", "無効送信前取消", "送信後構造破れでも実約定", "通常構造保護返済") if k in examples]
    result = {"全件一致": audit.error_count == 0, "照合項目数": audit.count, "不一致数": audit.error_count, "不一致": audit.errors,
              "全件数": dict(counters), "代表例": chosen,
              "代表欠落理由": [k + "に該当する実注文がない" for k in ("未確認送信前取消", "無効送信前取消", "送信後構造破れでも実約定", "通常構造保護返済") if k not in examples],
              "コードSHA256": B.sha(Path(__file__)), "正常板補助SHA256": B.sha(HELPER),
              "対象運用SHA256": B.sha(ROOT / "scripts/反転確認/運用.py"), "入力台帳SHA256": B.sha(INPUT),
              "詳細展開内容SHA256": detail_sha, "入口展開内容SHA256": signal_sha, "入力cache": fingerprints,
              "方法": "運用・入口・検証の数値処理をimportせず、全構造注文の要求キー以下の最後正常板、設定足の原価格、高安±5、実新規、最初の保護要求、+1秒最初BBOを直接確認。旧独立監査の読取補助だけを再利用。",
              "限界": "BB/ADX発動と純入口先着や会計全体の監査は別担当。正常板空白内の価格と実注文遅延は復元しない。全65場は既使用で、独立な未見評価ではない。"}
    target = WORK / "構造独立確認.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"全件一致": result["全件一致"], "照合項目数": audit.count, "不一致数": audit.error_count,
                      "不一致": audit.errors[:10], "全件数": dict(counters)}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00012構造注文の独立確認")
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        raise SystemExit("正式再生完了と監査許可を確認して --実行許可 を指定してください")
    if not run()["全件一致"]:
        raise SystemExit(1)
