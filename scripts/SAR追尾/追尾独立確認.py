"""00032のX0/XSを、原正常BBOと独立精密SARから別計算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00032_最低同値床と公開SAR追尾"
WORK = ROOT / "work/SAR追尾/00032"
STATE_CODE = Path(__file__).with_name("状態独立確認.py")


def helper(path: Path, name: str) -> Any:
    """独立SAR/入力・既検証X0追尾補助だけを読む。

    引数: path (Path) は独立コード、name (str) は識別名。
    返り値: Any は補助。32主SAR/運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


A = helper(STATE_CODE, "SAR追尾の独立精密値と入力")
T, V, S = A.G.T, A.V, A.S
POSITION_FIELDS = (*T.POSITION_FIELDS, "sar_applied", "sar_updates")


def reference(row: dict) -> dict:
    """公開SARの小型出典と精密次足候補を固定する。

    引数: row (dict) は独立計算済みSAR行。
    返り値: dict は公開元/方向/有効性/精密値。全OHLC履歴は複製しない。
    """
    names = ("場", "index", "end", "confirm", "confirm_line", "publish", "missing", "SAR準備済", "SAR公開可",
        "SAR方向", "SAR次足線", "SAR精密次足線", "SAR_AF整数", "SAR解除理由")
    return deepcopy({name: row[name] for name in names})


def replay_xs(detail: dict, quotes: list[dict], signals: dict[str, dict], sar_rows: list[dict],
              audit: Any, bounds: tuple | None = None) -> tuple[list[dict], dict]:
    """全正常BBOと公開イベントからXSの最初要求・全線・状態を再構成する。

    引数: detail (dict) は実保有と注文の保存詳細、quotes (list[dict]) は全正常板、signals (dict) は検証済み純信号、
    sar_rows (list[dict]) は独立精密全足、audit (Any) は照合先、bounds (tuple|None) は人工の開始/終了/新規停止/期限。
    返り値: tuple[list[dict],dict] は全ログ/件数。新規受入は保存注文を入力とし別会計監査へ分ける。
    """
    method, session = detail["候補ID"], detail["場"]
    start, finish, cutoff, force = bounds if bounds is not None else S.G.times(session)
    fills = detail["約定"]
    entries = {(row["price_clock"], row["source_line"]): row for row in fills if row["type"].endswith("N")}
    closings = {(row["price_clock"], row["source_line"]): row for row in fills if row["type"].endswith("R")}
    trades = {row["建玉ID"]: row for row in detail["取引"]}
    exit_orders = {row["入口イベントID"]: row for row in detail["注文"] if row["区分"] == "返済"}
    timeline = [(row["now"], row["line"], 0, row) for row in quotes if start <= row["now"] < finish]
    timeline.extend((row["confirm"], row["confirm_line"], 1, row) for row in sar_rows
        if row["publish"] and start <= row["confirm"] < finish)
    timeline.extend((row["要求時計秒"], row["要求原板行"], 2, row) for row in detail["注文"] if row["区分"] == "新規")
    timeline.sort(key=lambda row: row[:3])
    logs, counts, reasons = [], Counter(), Counter()
    position, pending, latest, force_done = None, None, None, False

    def log(action: str, now: float, line: int, **extra: Any) -> None:
        """建玉snapshotと動作を当時の値で固定保存する。

        引数: action (str) は動作、now/line (float/int) は根拠、extra (Any) は補足。
        返り値: None。後の公開や更新で過去ログを変えない。
        """
        logs.append(deepcopy({"場": session, "候補ID": method, "期間": detail["品質"]["期間"],
            "順序": len(logs) + 1, "動作": action, "時計秒": now, "原板行": line,
            "建玉": {name: position.get(name) for name in POSITION_FIELDS} if position is not None else None, **extra}))

    def request(now: float, line: int, reason: str) -> None:
        """独立条件が作る最初返済要求を保存台帳へ照合する。

        引数: now/line (float/int) は根拠、reason (str) は独立理由。
        返り値: None。保存要求を以後の閾値判定の正解として使わない。
        """
        nonlocal pending
        order = exit_orders.get(position["event_id"])
        audit.check(method + position["id"] + ":返済注文存在", order is not None, True)
        if order is not None:
            audit.check(method + position["id"] + ":初回返済要求",
                (order["要求時計秒"], order["要求原板行"], order["理由"]), (now, line, reason))
        pending = {"kind": "返済", "time": now, "reason": reason}
        counts["最初要求数"] += 1
        log("注文要求", now, line, 区分="返済", 理由=reason, 注文ID=order["注文ID"] if order else "保存注文なし")

    def before(now: float) -> None:
        """当イベント前に新規失効と期限予約を適用する。

        引数: now (float) はイベント価格時計。
        返り値: None。新規TTLは30秒を超えた時、停止時刻は等号から失効する。
        """
        nonlocal pending, force_done
        if pending is not None and pending["kind"] == "新規" and (now >= cutoff or now > pending["time"] + 30):
            pending = None
        if not force_done and now >= force:
            force_done = True
            if pending is not None and pending["kind"] == "新規":
                pending = None
            if position is not None and pending is None:
                request(force, 0, "期限")

    def mark(quote: dict) -> None:
        """実返済原行までMFE/MAEを観測する。

        引数: quote (dict) は正常BBO。
        返り値: None。pending中のMFEでarm/設定線を遡及更新しない。
        """
        if position is not None:
            distance = position["side"] * ((quote["bid"] if position["side"] > 0 else quote["ask"]) - position["price"])
            position["mfe"], position["mae"] = max(position["mfe"], distance), max(position["mae"], -distance)

    for now, line, kind, value in timeline:
        before(now)
        if kind == 1:
            audit.check(method + ":SAR当場公開", value["場"] == session and value["confirm"] >= value["end"], True)
            if latest is not None:
                audit.check(method + ":SAR公開key非後退", (now, line) >= (latest["confirm"], latest["confirm_line"]), True)
            latest = reference(value)
            log("SAR公開参照更新", now, line, 最新SAR参照=latest, SAR候補有効=latest["SAR公開可"], 建玉設定凍結=pending is not None)
            continue
        if kind == 2:
            audit.check(method + value["注文ID"] + ":新規受付時建玉なし", position is None and pending is None, True)
            pending = {"kind": "新規", "time": now, "reason": value["理由"]}
            log("注文要求", now, line, 区分="新規", 理由=value["理由"], 注文ID=value["注文ID"])
            continue
        quote = value
        mark(quote)
        entry, closing = entries.get((now, line)), closings.get((now, line))
        if entry is not None:
            audit.check(method + entry["position_id"] + ":新規待機と新規約定", pending is not None and pending["kind"] == "新規" and position is None, True)
            source = signals[entry["entry_event_id"]]
            position = {"id": entry["position_id"], "event_id": entry["entry_event_id"], "side": 1 if entry["type"].startswith("Long") else -1,
                "price": entry["price"], "time": now, "line": line, "entry_role": source["役割"], "atr_entry": float(source["atr"]),
                "mfe": 0.0, "mae": 0.0, "armed": False, "trail_A": 5, "trail_D": None, "trail_stop": None,
                "trail_arm_time": None, "trail_arm_line": None, "sar_applied": None, "sar_updates": 0}
            pending = None
            log("追尾初期化", now, line, 追尾方式="公開SAR", ATR距離使用=False)
        if closing is not None:
            audit.check(method + closing["position_id"] + ":返済要求済み", pending is not None and pending["kind"] == "返済", True)
            audit.check(method + closing["position_id"] + ":返済建玉所有者", position["id"] if position else None, closing["position_id"])
            if position is not None:
                trade = trades[closing["position_id"]]
                net = position["side"] * (closing["price"] - position["price"]) * 10 - 22
                expected = {"入口役割": position["entry_role"], "入口ATR": position["atr_entry"], "固定利確使用": True,
                    "通常出口使用": False, "必須追尾使用": True, "利確価格": position["price"] + position["side"] * 250,
                    "追尾起動幅pt": 5, "追尾距離pt": None, "追尾起動": position["armed"], "利益床起動": position["armed"],
                    "最終追尾価格": position["trail_stop"], "追尾起動時計秒": position["trail_arm_time"], "追尾起動原板行": position["trail_arm_line"],
                    "起動後純赤字": bool(position["armed"] and net < 0), "観測最大順行pt": position["mfe"], "観測最大逆行pt": position["mae"],
                    "返済理由": pending["reason"] if pending else None,
                    "最終追尾から実返済方向差pt": position["side"] * (closing["price"] - position["trail_stop"]) if position["trail_stop"] is not None else None,
                    "追尾方式": "公開SAR", "ATR距離使用": False, "SAR締上げ回数": position["sar_updates"], "最終SAR適用参照": position["sar_applied"]}
                for field, target in expected.items():
                    audit.check(method + position["id"] + ":" + field, trade[field], target)
                log("追尾建玉終了", now, line, 返済理由=expected["返済理由"])
                if expected["起動後純赤字"]:
                    log("起動済み純赤字約定", now, line, 純損益円=net)
                    counts["起動後純赤字取引数"] += 1
            position, pending = None, None
            counts["完結取引数"] += 1
        mark(quote)
        if position is None or pending is not None:
            continue
        mark_price = quote["bid"] if position["side"] > 0 else quote["ask"]
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
            position["trail_stop"] = position["price"]
            counts["追尾線更新回数"] += 1
            log("追尾線更新", now, line, 旧追尾価格=None, 新追尾価格=position["price"], 丸め前価格=position["price"], 更新根拠="初回同値床")
        reason = "当場公開SAR未準備"
        if latest is not None and latest["SAR公開可"]:
            if (now, line) <= (latest["confirm"], latest["confirm_line"]):
                reason = "SAR公開key後でない"
            elif latest["SAR方向"] != position["side"]:
                reason = "SAR方向不一致"
            else:
                exact = A.unpack(latest["SAR精密次足線"])
                if exact is None:
                    raise ValueError("有効SARの精密次足線なし")
                if position["side"] * (exact - A.Fraction(position["price"])) <= 0:
                    reason = "SAR名目利益strict正でない"
                else:
                    candidate = A.round_tick(exact, position["side"])
                    old = position["trail_stop"]
                    new = max(old, candidate) if position["side"] > 0 else min(old, candidate)
                    reason = "SAR候補非緩和維持"
                    if new != old:
                        position.update(trail_stop=new, sar_applied=deepcopy(latest), sar_updates=position["sar_updates"] + 1)
                        counts["追尾線更新回数"] += 1
                        counts["SAR締上げ回数"] += 1
                        reason = "SAR上締上げ"
                        log("追尾線更新", now, line, 旧追尾価格=old, 新追尾価格=new, 丸め前価格=float(exact),
                            精密候補=A.pack(exact), 呼値候補=candidate, 更新根拠="公開SAR次足線", SAR適用参照=latest)
        reasons[reason] += 1
        audit.check(method + position["id"] + ":名目最低同値", position["side"] * (position["trail_stop"] - position["price"]) >= 0, True)
        if position["side"] * (mark_price - position["trail_stop"]) <= 0:
            counts["追尾要求数"] += 1
            log("追尾閾値初着", now, line, 返済気配=mark_price)
            request(now, line, "必須利益追尾")
    before(finish)
    for field in ("追尾起動取引数", "追尾線更新回数", "追尾要求数", "起動後純赤字取引数", "SAR締上げ回数"):
        audit.check(method + session + ":" + field, detail["品質"][field], counts[field])
    audit.check(method + session + ":SAR評価理由別", detail["品質"]["SAR評価理由別"], dict(reasons))
    audit.check(method + session + ":完結数", len(detail["取引"]), counts["完結取引数"])
    return logs, dict(counts)


def replay_x0(detail: dict, quotes: list[dict], signals: dict[str, dict], audit: Any,
              bounds: tuple | None = None) -> tuple[list[dict], dict]:
    """固定31と同じ既検証X0の独立追尾だけを再利用する。

    引数: detail/quotes/signals/audit は保存詳細/正常板/純信号/照合先、bounds (tuple|None) は人工四時計。
    返り値: tuple[list[dict],dict] は全ログと件数。32主運用は呼ばない。
    """
    old_bounds = (bounds[0], bounds[1], bounds[3]) if bounds is not None else None
    return T.replay(detail, quotes, signals, audit, old_bounds)


# ----------------------------------------
# 正式状態proofと共有31を確認してから全四運用の原正常BBOへ進む。

def run(study: Path, work: Path) -> dict:
    """root正式完了後だけ全X0/XSの追尾と最初要求を独立検算する。

    引数: study/work (Path) は32正式/作業先。
    返り値: dict は状態/SAR/共有入口/結果へbindした追尾proof。市場モデルは呼ばない。
    """
    if not (study / "結果.json").exists() or not (work / "状態独立確認.json").exists():
        raise ValueError("root正式完了と状態監査完了後に実行します")
    audit, initial = A.Audit(), V.sha(Path(__file__))
    config, manifest, master, resolved, pointer = A.guarded_inputs(study, work, audit)
    A.check_prepared(study, work, resolved, master, audit)
    state = V.read(work / "状態独立確認.json")
    for name, expected in (("全件一致", True), ("不一致数", 0), ("コードSHA256", V.sha(STATE_CODE)),
            ("追尾コードSHA256", initial), ("条件SHA256", V.sha(study / "条件.json")),
            ("入力台帳SHA256", V.sha(study / "入力台帳.json")), ("参照入力台帳SHA256", V.sha(resolved)),
            ("入口参照SHA256", V.sha(study / "入口参照.json")), ("結果SHA256", V.sha(study / "結果.json"))):
        audit.check("状態proof現在:" + name, state[name], expected)
    details, detail_sha = A.B.compressed_rows(work / "全運用詳細.jsonl.gz")
    logs, log_sha = A.B.compressed_rows(work / "追尾.jsonl.gz")
    sar, sar_sha = A.B.compressed_rows(work / "SAR全足.jsonl.gz")
    for name, expected in (("全運用詳細展開SHA256", detail_sha), ("追尾展開SHA256", log_sha), ("SAR全足展開SHA256", sar_sha)):
        audit.check("状態保存物出典:" + name, state[name], expected)
    raw_signals = A.shared_signals()
    signals = {row["イベントID"]: row for row in raw_signals}
    audit.check("共有live一意", len(signals), len(raw_signals))
    formal = V.read(study / "結果.json")
    candidates = ["3分_" + policy + "_" + exit_name for policy in A.POLICIES for exit_name in A.EXITS]
    audit.check("32四運用", [row["候補ID"] for row in formal["結果"]], candidates)
    by_session, sar_by_session, saved = defaultdict(list), defaultdict(list), {}
    for detail in details:
        by_session[detail["場"]].append(detail)
    for row in sar:
        sar_by_session[row["場"]].append(row)
    for row in logs:
        key = row["場"], row["候補ID"], row["順序"]
        if key in saved:
            raise ValueError("追尾原順keyが重複")
        saved[key] = row
    pairs = {(row["場"], row["候補ID"]) for row in details}
    audit.check("四運用一意", len(pairs), len(details))
    audit.check("全4×66運用", pairs, {(entry["session"], candidate) for entry in manifest["entries"] for candidate in candidates})
    if audit.mismatches:
        raise ValueError("状態/参照/保存物の不一致により正常BBO前停止")
    expected, totals, summaries = {}, Counter(), []
    for entry in manifest["entries"]:
        loaded = T.B.load(entry)
        quotes = loaded[1]
        del loaded
        for detail in by_session[entry["session"]]:
            if detail["候補ID"].endswith("_X0"):
                current, counts = replay_x0(detail, quotes, signals, audit)
            else:
                current, counts = replay_xs(detail, quotes, signals, sar_by_session[entry["session"]], audit)
            expected.update({(row["場"], row["候補ID"], row["順序"]): row for row in current})
            totals.update(counts)
            summaries.append({"場": entry["session"], "候補ID": detail["候補ID"],
                "対象完結取引数": len(detail["取引"]), "追尾行数": len(current)})
        print(json.dumps({"場": entry["session"], "独立確認": "X0/精密XS全最初要求/床/公開/線", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    audit.check("全追尾原順key集合", set(saved), set(expected))
    for key in saved.keys() & expected.keys():
        audit.check("追尾:" + str(key), saved[key], expected[key])
    count = sum(len(detail["取引"]) for detail in details)
    audit.check("正式全完結数", count, sum(row[phase]["運用"]["完結取引数"] for row in formal["結果"] for phase in ("学習", "条件選択", "後続検査")))
    audit.check("独立実行中code不変", V.sha(Path(__file__)), initial)
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "対象場候補数": len(details), "対象完結取引数": count, "保存追尾行数": len(logs), "独立追尾行数": len(expected),
        "独立動作数": dict(totals), "場候補別": summaries, "コードSHA256": initial, "依存コードSHA256": A.dependency_pins(),
        "結果SHA256": V.sha(study / "結果.json"), "条件SHA256": V.sha(study / "条件.json"),
        "入力台帳SHA256": V.sha(study / "入力台帳.json"), "参照入力台帳SHA256": V.sha(resolved), "解決入力台帳SHA256": V.sha(resolved),
        "入口参照SHA256": V.sha(study / "入口参照.json"), "全運用詳細展開SHA256": detail_sha,
        "追尾展開SHA256": log_sha, "SAR全足展開SHA256": sar_sha, "入口事例展開SHA256": state["入口事例展開SHA256"],
        "共有入口事例展開SHA256": state["入口事例展開SHA256"],
        "状態独立確認SHA256": V.sha(work / "状態独立確認.json"),
        "検証範囲": "状態proofで独立全再構成済みのSAR全足/共有31liveを入力とし、全X0は旧独立追尾を再用、全XSは原正常BBOと全SAR公開を別走査。初回A5床/精密ceil/方向/strict公開key/非緩和/旧床維持/全global公開/新規pendingTTL/返済pending凍結/期限hardTP優先/全最初要求/全snapshot/起動後赤字を比較。",
        "限界": "32主SAR/運用classをimportしない。保存新規受入と保有区間を入力としており、注文/約定/費用/集計は会計監査へ分離。SAR再計算は状態proofへbindして重複せず、先着は固定31の証明を共有。名目床は実価格/費用後非赤字を保証しない。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({name: proof[name] for name in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存追尾行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root正式完了後の全量追尾監査を明示起動する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不一致は非0終了。無指定で実観測へ進まない。
    """
    parser = argparse.ArgumentParser(description="00032の全X0/XS独立追尾監査")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("root正式完了後に --実行許可 を指定します")
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
