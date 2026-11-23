"""00021全X0の最初要求・利益追尾・役割固定を正常気配から別計算する。"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00021_BBとMACDとストキャスの発動切替"
WORK = ROOT / "work/異種発動/00021"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
STATE_HELPER = Path(__file__).with_name("状態独立確認.py")
QUOTE_HELPER = ROOT / "scripts/利益回収/出口独立確認.py"
POSITION_FIELDS = ("id", "event_id", "side", "price", "time", "line", "entry_role", "atr_entry",
    "mfe", "mae", "armed", "trail_A", "trail_D", "trail_stop", "trail_arm_time", "trail_arm_line")


def helper(path: Path, name: str) -> Any:
    """独立価格/比較/正常板読取補助だけを読む。

    引数: path (Path) は補助、name (str) はモジュール名。
    返り値: Any は補助。21運用classをimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


I = helper(STATE_HELPER, "異種発動追尾の独立状態")
B = helper(QUOTE_HELPER, "異種発動追尾の独立正常板")
V, S = I.V, I.S


def replay(detail: dict, quotes: list[dict], signals: dict[str, dict],
           audit: Any, bounds: tuple | None = None) -> tuple[list[dict], dict]:
    """保存実保有区間の全正常板から、hard/追尾/期限の最初要求を再構成する。

    引数: detail (dict) は一場詳細、quotes (list[dict]) は正常板、signals (dict) は検証済入口、
    audit (Any) は比較先、bounds (tuple|None) は合成用開始/終端/期限時計。
    返り値: tuple[list[dict],dict] は全独立追尾ログと件数。VWAP/局面変更による出口は作らない。
    """
    method, session = detail["候補ID"], detail["場"]
    start, finish, force = bounds if bounds is not None else B.bounds(session)
    new_fills = [f for f in detail["約定"] if f["type"].endswith("N")]
    exit_fills = {f["position_id"]: f for f in detail["約定"] if f["type"].endswith("R")}
    trades = {t["建玉ID"]: t for t in detail["取引"]}
    orders = {o["入口イベントID"]: o for o in detail["注文"] if o["区分"] == "返済"}
    entries = {(f["price_clock"], f["source_line"]): f for f in new_fills}
    closings = {(f["price_clock"], f["source_line"]): f for f in exit_fills.values()}
    keys = [(q["now"], q["line"]) for q in quotes]
    selected = []
    for f in new_fills:
        closing = exit_fills.get(f["position_id"])
        left = f["price_clock"], f["source_line"]
        right = (closing["price_clock"], closing["source_line"]) if closing else (finish, 2**63 - 1)
        selected.extend((q["now"], q["line"], 0, q) for q in quotes[bisect_left(keys, left):bisect_right(keys, right)])
    selected += [(o["要求時計秒"], o["要求原板行"], 2, o) for o in detail["注文"] if o["区分"] == "新規"]
    selected.sort(key=lambda r: r[:3])
    logs, counts = [], Counter()
    position, pending, force_done = None, None, False

    def log(action: str, now: float, line: int, **attributes: Any) -> None:
        """独立建玉の現在snapshotをログへ固定保存する。

        引数: action (str) は動作、now/line (float/int) は根拠、attributes (Any) は補足。
        返り値: None。未来の更新で過去snapshotを変えない。
        """
        snapshot = {k: position.get(k) for k in POSITION_FIELDS} if position is not None else None
        logs.append({"場": session, "候補ID": method, "期間": detail["品質"]["期間"], "順序": len(logs) + 1,
            "動作": action, "時計秒": now, "原板行": line, "建玉": snapshot, **attributes})

    def request(now: float, line: int, reason: str) -> None:
        """条件から導いた初回返済要求を保存注文へ比較する。

        引数: now/line (float/int) は要求キー、reason (str) は独立理由。
        返り値: None。保存要求を以後の判定基準へ使わない。
        """
        nonlocal pending
        order = orders.get(position["event_id"])
        audit.check(method + ":" + position["id"] + ":返済注文存在", order is not None, True)
        if order:
            audit.check(method + ":" + position["id"] + ":初回要求",
                (order["要求時計秒"], order["要求原板行"], order["理由"]), (now, line, reason))
        pending = reason
        log("注文要求", now, line, 区分="返済", 理由=reason, 注文ID=order["注文ID"] if order else "保存注文なし")
        counts["最初要求数"] += 1

    def before(now: float) -> None:
        """次イベント前に期限予約を一度だけ差し込む。

        引数: now (float) は次観測時計。
        返り値: None。barでは価格/追尾が変化しないため期限予約を同時計で代数的に適用する。
        """
        nonlocal force_done
        if not force_done and now >= force:
            force_done = True
            if position is not None and pending is None:
                request(force, 0, "期限")

    def mark(q: dict) -> None:
        """待機中/実返済原行も含むMFE/MAEを更新する。

        引数: q (dict) は正常BBO。
        返り値: None。待機中のMFE増加から過去の追尾起動を補わない。
        """
        if position is not None:
            p = position["side"] * ((q["bid"] if position["side"] == 1 else q["ask"]) - position["price"])
            position["mfe"], position["mae"] = max(position["mfe"], p), max(position["mae"], -p)

    for now, line, kind, q in selected:
        before(now)
        if kind == 2:
            audit.check(method + ":" + q["注文ID"] + ":新規要求時建玉なし", position is None, True)
            log("注文要求", now, line, 区分="新規", 理由=q["理由"], 注文ID=q["注文ID"])
            continue
        mark(q)
        entry = entries.get((now, line))
        if entry is not None:
            audit.check(method + ":" + entry["position_id"] + ":新規重複なし", position is None, True)
            source = signals[entry["entry_event_id"]]
            side = 1 if entry["type"].startswith("Long") else -1
            position = {"id": entry["position_id"], "event_id": entry["entry_event_id"], "side": side,
                "price": entry["price"], "time": now, "line": line, "entry_role": source["役割"],
                "atr_entry": float(source["atr"]), "mfe": 0.0, "mae": 0.0, "armed": False,
                "trail_A": 5, "trail_D": max(5, math.ceil(source["atr"] / 5) * 5),
                "trail_stop": None, "trail_arm_time": None, "trail_arm_line": None}
            pending = None
            log("追尾初期化", now, line)
        closing = closings.get((now, line))
        if closing is not None:
            audit.check(method + ":" + closing["position_id"] + ":返済要求済", pending is not None, True)
            audit.check(method + ":" + closing["position_id"] + ":返済所有者",
                position["id"] if position else None, closing["position_id"])
            if position is not None:
                trade = trades[closing["position_id"]]
                net = position["side"] * (closing["price"] - position["price"]) * 10 - 22
                armed_loss = bool(position["armed"] and net < 0)
                expected = {"入口役割": position["entry_role"], "入口ATR": position["atr_entry"], "固定利確使用": True,
                    "通常出口使用": False, "必須追尾使用": True, "利確価格": position["price"] + position["side"] * 250,
                    "追尾起動幅pt": 5, "追尾距離pt": position["trail_D"], "追尾起動": position["armed"],
                    "利益床起動": position["armed"], "最終追尾価格": position["trail_stop"],
                    "追尾起動時計秒": position["trail_arm_time"], "追尾起動原板行": position["trail_arm_line"],
                    "起動後純赤字": armed_loss, "観測最大順行pt": position["mfe"], "観測最大逆行pt": position["mae"],
                    "返済理由": pending, "最終追尾から実返済方向差pt": position["side"] * (closing["price"] - position["trail_stop"]) if position["trail_stop"] is not None else None}
                for field, value in expected.items():
                    audit.check(method + ":" + position["id"] + ":" + field, trade[field], value)
                log("追尾建玉終了", now, line, 返済理由=pending)
                if armed_loss:
                    log("起動済み純赤字約定", now, line, 純損益円=net)
                    counts["起動後純赤字取引数"] += 1
            position, pending = None, None
            counts["完結取引数"] += 1
        mark(q)
        if position is None or pending is not None:
            continue
        mark_price = q["bid"] if position["side"] == 1 else q["ask"]
        profit = position["side"] * (mark_price - position["price"])
        if profit <= -125 or profit >= 250:
            request(now, line, "保護" if profit <= -125 else "利確")
            continue
        if position["mfe"] < 5:
            continue
        if not position["armed"]:
            position.update(armed=True, trail_arm_time=now, trail_arm_line=line)
            counts["追尾起動取引数"] += 1
            log("追尾起動", now, line)
        raw = position["price"] + position["side"] * max(0, position["mfe"] - position["trail_D"])
        candidate = (math.ceil(raw / 5) if position["side"] == 1 else math.floor(raw / 5)) * 5
        old = position["trail_stop"]
        new = candidate if old is None else max(old, candidate) if position["side"] == 1 else min(old, candidate)
        if new != old:
            position["trail_stop"] = new
            counts["追尾線更新回数"] += 1
            log("追尾線更新", now, line, 旧追尾価格=old, 新追尾価格=new, 丸め前価格=raw)
        audit.check(method + ":" + position["id"] + ":最低同値", position["side"] * (new - position["price"]) >= 0, True)
        if position["side"] * (mark_price - new) <= 0:
            counts["追尾要求数"] += 1
            log("追尾閾値初着", now, line, 返済気配=mark_price)
            request(now, line, "必須利益追尾")
    before(finish)
    for field in ("追尾起動取引数", "追尾線更新回数", "追尾要求数", "起動後純赤字取引数"):
        audit.check(method + ":" + session + ":" + field, detail["品質"][field], counts[field])
    audit.check(method + ":" + session + ":全完結数", counts["完結取引数"], len(detail["取引"]))
    return logs, dict(counts)


# ----------------------------------------
# 全12×65の正式完了後だけ保存明細を読む。指標準備段階で本処理を呼ばない。

def run(study: Path, work: Path) -> dict:
    """全X0の原順気配・最初要求・追尾ログを独立に照合する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は明示合否・対象数・指紋。会計の主監査と件数を合算しない。
    """
    if not (study / "結果.json").exists() or not (work / "状態独立確認.json").exists():
        raise ValueError("正式完了と状態確認が必要")
    audit, manifest, formal = V.Audit(), V.read(INPUT), V.read(study / "結果.json")
    state = V.read(work / "状態独立確認.json")
    audit.check("状態確認成功", state["全件一致"], True)
    audit.check("状態コード", state["コードSHA256"], V.sha(STATE_HELPER))
    details, detail_sha = S.compressed_rows(work / "全運用詳細.jsonl.gz")
    logs, log_sha = S.compressed_rows(work / "追尾.jsonl.gz")
    cases, case_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    audit.check("入口事例SHA", case_sha, state["入口事例展開SHA256"])
    signals = {r["イベントID"]: {"atr": r["atr"], "役割": r["役割"]} for r in cases}
    grouped, saved = defaultdict(list), {}
    for d in details:
        grouped[d["場"]].append(d)
    for r in logs:
        key = r["場"], r["候補ID"], r["順序"]
        if key in saved:
            raise ValueError("追尾logキー重複")
        saved[key] = r
    candidates = [r["候補ID"] for r in formal["結果"]]
    audit.check("全12候補", len(candidates), 12)
    pairs = [(d["場"], d["候補ID"]) for d in details]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    S.compare_keys(audit, "全12×65", set(pairs), {(e["session"], cid) for e in manifest["entries"] for cid in candidates})
    expected, totals, summaries = {}, Counter(), []
    for entry in manifest["entries"]:
        loaded = B.load(entry)
        quotes = loaded[1]
        del loaded
        for detail in grouped[entry["session"]]:
            rows, counts = replay(detail, quotes, signals, audit)
            expected.update({(r["場"], r["候補ID"], r["順序"]): r for r in rows})
            totals.update(counts)
            summaries.append({"場": entry["session"], "候補ID": detail["候補ID"],
                "対象完結取引数": len(detail["取引"]), "追尾行数": len(rows)})
        print(json.dumps({"場": entry["session"], "独立確認": "全X0最初要求・追尾・役割固定",
            "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    S.compare_keys(audit, "全追尾log原順集合", set(saved), set(expected))
    for key in saved.keys() & expected.keys():
        audit.check(f"追尾{key}", saved[key], expected[key])
    count = sum(len(d["取引"]) for d in details)
    audit.check("正式完結数", count, sum(r[p]["運用"]["完結取引数"] for r in formal["結果"] for p in ("学習", "条件選択", "後続検査")))
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "対象場候補数": len(details), "対象完結取引数": count, "保存追尾行数": len(logs), "独立追尾行数": len(expected),
        "保存通常線行数": len(logs), "独立動作数": dict(totals), "場候補別": summaries,
        "コードSHA256": V.sha(Path(__file__)), "結果SHA256": V.sha(study / "結果.json"), "入力台帳SHA256": V.sha(INPUT),
        "全運用詳細展開SHA256": detail_sha, "追尾展開SHA256": log_sha, "通常線更新展開SHA256": log_sha,
        "入口事例展開SHA256": case_sha, "状態独立確認SHA256": V.sha(work / "状態独立確認.json"),
        "独立正常板補助SHA256": V.sha(QUOTE_HELPER),
        "検証範囲": "全12X0の保存実新規・保有区間を固定し、原cacheの全正常BBOと期限時点から最初のhard125/TP250/追尾/期限要求を独立再構成。A5/D入口ATRceil5、起動key/MFE/MAE・最低同値/ratchet/鏡像丸め、pending中更新停止、返済側気配・起動後赤字・実fill時role固定、全追尾ログ/順序を検算。barは期限予約のみなので価格状態を変えず、同じ期限時計で予約を代数的に適用。",
        "限界": "21運用classをimportして再実行しない。保存実保有区間は入力であり新規受入/+1秒BBO約定/会計/先着は主監査へ分離。指標発動は状態独立確認を前提とする。MFE>=5でも先に返済要求があれば未起動可。最低同値設定は実同値約定/費用後非赤字を保証しない。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存追尾行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """正式完了通知後だけ全量監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不一致時は非0終了。
    """
    parser = argparse.ArgumentParser(description="00021追尾原気配独立確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("正式再生完了通知後に --実行許可 を指定してください")
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
