"""00033の二入口・旧A5一案と費用後起動二案を原正常BBOから独立確認する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from bisect import bisect_left, bisect_right
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00033_CCI突破と足内終値位置"
WORK = ROOT / "work/終値位置/00033"
STATE_CODE = Path(__file__).with_name("状態独立確認.py")
EXIT_HELPER = ROOT / "scripts/異種発動/追尾独立確認.py"


def helper(path: Path, name: str) -> Any:
    """同階層の独立状態コードと固定独立追尾補助だけを読む。

    引数: path (Path) は補助、name (str) はモジュール識別。
    返り値: Any はモジュール。33主の入口・運用はimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Y = helper(STATE_CODE, "終値位置追尾の独立状態")
X = Y.G.T
V, S, B = X.V, X.S, X.B


def net_value(mark: float, entry: float, side: int, config: dict) -> Fraction:
    """保存表示価格の正確十進値から現在の費用控除後含み円を別算する。

    引数: mark/entry (float) は返済側BBO/新規価格、side (int) は実方向、config (dict) は運用数値。
    返り値: Fraction は往復手数料と固定想定片道5pt控除後。スプレッドはBBO差へ既に含む。
    """
    observed, opened = Fraction(Decimal(str(mark))), Fraction(Decimal(str(entry)))
    distance = observed - opened if side == 1 else opened - observed
    quantity, multiple, fee = (Fraction(Decimal(str(config[key]))) for key in ("数量", "倍率", "片道手数料円"))
    return quantity * (distance * multiple - 2 * fee - 2 * 5 * multiple)


def current_net(mark: float, entry: float, side: int, config: dict) -> dict:
    """現在費用後円の独立分数から起動根拠の保存列を組み立てる。

    引数: mark/entry (float) は返済側BBO/新規価格、side (int) は売買、config (dict) は運用。
    返り値: dict は厳密円分数/strict正・表示・費用。CLVの元float分数契約とは別の十進表示契約。
    """
    if side not in (-1, 1) or not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0 for value in (mark, entry)):
        raise ValueError("有効な返済気配/新規価格/売買符号が必要です")
    quantity, multiple, fee = (Fraction(Decimal(str(config[key]))) for key in ("数量", "倍率", "片道手数料円"))
    if quantity <= 0 or multiple <= 0 or fee < 0:
        raise ValueError("数量/倍率/手数料が不正")
    point = (Fraction(Decimal(str(mark))) - Fraction(Decimal(str(entry)))) * side
    cost = quantity * 2 * (fee + 5 * multiple)
    value = net_value(mark, entry, side, config)
    return {"返済気配": mark, "新規価格": entry, "実side": side, "名目利益pt": float(point),
        "粗含み益円": float(point * quantity * multiple), "控除後含み益円": float(value),
        "控除後含み益円分子": value.numerator, "控除後含み益円分母": value.denominator,
        "strict正": value > 0, "起動参照費用円": float(cost), "起動参照片道滑りpt": 5,
        "境界pt": float(cost / (quantity * multiple))}



# ----------------------------------------
# XFは現在の費用後正から起動し、起動後のMFE-D線と最初要求を独立走査する。

def replay_cost(detail: dict, quotes: list[dict], signals: dict[str, dict],
                audit: Any, bounds: tuple | None = None, config: dict | None = None) -> tuple[list[dict], dict]:
    """保存実保有区間を独立走査し、現在費用後strict正から起動するXFを検算する。

    引数: detail (dict) は一場詳細、quotes (list[dict]) は正常板、signals (dict) は検証済入口、
    audit (Any) は比較先、bounds (tuple|None) は人工時計、config (dict|None) は運用数値。
    返り値: tuple[list[dict],dict] は独立全ログ/件数。旧21独立の走査を再用し、新起動・出典を別算する。
    """
    config = config if config is not None else {"数量": 1, "倍率": 10, "片道手数料円": 11}
    metadata = current_net(1000.0, 1000.0, 1, config)
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
        snapshot = {k: position.get(k) for k in (*X.POSITION_FIELDS, "cost_arm")} if position is not None else None
        logs.append(deepcopy({"場": session, "候補ID": method, "期間": detail["品質"]["期間"], "順序": len(logs) + 1,
            "動作": action, "時計秒": now, "原板行": line, "建玉": snapshot, **attributes}))

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
                "trail_A": metadata["境界pt"], "trail_D": max(5, math.ceil(source["atr"] / 5) * 5),
                "trail_stop": None, "trail_arm_time": None, "trail_arm_line": None, "cost_arm": None}
            pending = None
            log("追尾初期化", now, line, 起動定義="現在費用控除後strict正",
                起動参照費用円=metadata["起動参照費用円"], 起動参照片道滑りpt=5, 起動境界strict=True)
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
                    "追尾起動幅pt": metadata["境界pt"], "追尾距離pt": position["trail_D"], "追尾起動": position["armed"],
                    "利益床起動": position["armed"], "最終追尾価格": position["trail_stop"],
                    "追尾起動時計秒": position["trail_arm_time"], "追尾起動原板行": position["trail_arm_line"],
                    "起動後純赤字": armed_loss, "観測最大順行pt": position["mfe"], "観測最大逆行pt": position["mae"],
                    "返済理由": pending, "最終追尾から実返済方向差pt": position["side"] * (closing["price"] - position["trail_stop"]) if position["trail_stop"] is not None else None}
                expected.update(起動定義="現在費用控除後strict正", 起動境界strict=True,
                    起動参照費用円=metadata["起動参照費用円"], 起動参照片道滑りpt=5,
                    起動判定出典=deepcopy(position["cost_arm"]))
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
        if not position["armed"]:
            decision = current_net(mark_price, position["price"], position["side"], config)
            if not decision["strict正"]:
                continue
            decision.update(価格時計秒=now, 原板行=line, 元bid=q["bid"], 元ask=q["ask"])
            position.update(armed=True, trail_arm_time=now, trail_arm_line=line, cost_arm=decision)
            counts["追尾起動取引数"] += 1
            log("追尾起動", now, line, 起動定義="現在費用控除後strict正", 起動判定出典=deepcopy(decision))
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
    for field, value in {"起動定義": "現在費用控除後strict正", "起動境界strict": True,
            "起動参照費用円": metadata["起動参照費用円"], "起動参照片道滑りpt": 5}.items():
        audit.check(method + ":" + session + ":" + field, detail["品質"][field], value)
    for field in ("追尾起動取引数", "追尾線更新回数", "追尾要求数", "起動後純赤字取引数"):
        audit.check(method + ":" + session + ":" + field, detail["品質"][field], counts[field])
    audit.check(method + ":" + session + ":全完結数", counts["完結取引数"], len(detail["取引"]))
    return logs, dict(counts)


# ----------------------------------------
# 正式全三運用だけを、状態proofと固定指紋へ結び付けて検算する。

def run(study: Path, work: Path) -> dict:
    """正式状態完了後に三運用の全保有BBO・最初要求・全追尾線を検算する。

    引数: study/work (Path) は33正式/作業先。
    返り値: dict は追尾証明。実約定・費用と未解消確定額は別会計へ分ける。
    """
    if not (study / "結果.json").exists() or not (work / "状態独立確認.json").exists():
        raise ValueError("正式結果と完了状態証明が必要です")
    initial, audit = V.sha(Path(__file__)), V.Audit()
    manifest, resolved = Y.G.resolved_manifest(study)
    formal, state, master = (V.read(path) for path in (study / "結果.json", work / "状態独立確認.json", work / "準備点検.json"))
    expected_state = {"全件一致": True, "不一致数": 0, "コードSHA256": V.sha(STATE_CODE),
        "追尾コードSHA256": initial, "主準備SHA256": V.sha(work / "準備点検.json"),
        "入力台帳SHA256": V.sha(study / "入力台帳.json"), "参照入力台帳SHA256": V.sha(resolved),
        "条件SHA256": V.sha(study / "条件.json"), "結果SHA256": V.sha(study / "結果.json"),
        "入口参照SHA256": V.sha(study / "入口参照.json"), "依存コードSHA256": Y.dependency_pins()}
    for name, value in expected_state.items():
        audit.check("状態接続:" + name, state[name], value)
    for name, digest in V.read(study / "固定.json")["ファイルSHA256"].items():
        audit.check("追尾固定現在:" + name, V.sha(ROOT / name), digest)
    details, detail_sha = S.compressed_rows(work / "全運用詳細.jsonl.gz")
    logs, log_sha = S.compressed_rows(work / "追尾.jsonl.gz")
    audit.check("全運用詳細展開SHA", detail_sha, state["全運用詳細展開SHA256"])
    audit.check("追尾展開SHA", log_sha, state["追尾展開SHA256"])
    signals = {}
    total_signals = 0
    for block in master["準備"]:
        audit.check(block["場"] + ":純信号生SHA", block["純信号内容SHA256"], Y.canonical_sha(block["純信号"]))
        for row in block["純信号"]:
            total_signals += 1
            signals[row["イベントID"]] = {"atr": row["atr"], "役割": row["役割"]}
    audit.check("純信号全ID一意", len(signals), total_signals)
    audit.check("状態純信号数", total_signals, state["T0純信号数"] + state["T1純信号数"])
    grouped, saved = defaultdict(list), {}
    for row in details:
        grouped[row["場"]].append(row)
    for row in logs:
        key = row["場"], row["候補ID"], row["順序"]
        if key in saved:
            raise ValueError("追尾logキー重複")
        saved[key] = row
    candidates = list(Y.OPERATIONS)
    audit.check("正式三候補", [row["候補ID"] for row in formal["結果"]], candidates)
    pairs = [(row["場"], row["候補ID"]) for row in details]
    audit.check("場候補一意", len(pairs), len(set(pairs)))
    S.compare_keys(audit, "全3x66", set(pairs), {(row["session"], cid) for row in manifest["entries"] for cid in candidates})
    if audit.mismatches:
        raise ValueError("状態/入力/純信号/固定の不一致によりcache前停止")
    expected, totals, summaries = {}, Counter(), []
    config = V.read(study / "条件.json")["運用"]
    for entry in manifest["entries"]:
        loaded = B.load(entry)
        quotes = loaded[1]
        del loaded
        for detail in grouped[entry["session"]]:
            rows, counts = X.replay(detail, quotes, signals, audit) if detail["候補ID"] == "3分_T0_X0" else replay_cost(
                detail, quotes, signals, audit, config=config)
            expected.update({(row["場"], row["候補ID"], row["順序"]): row for row in rows})
            totals.update(counts)
            summaries.append({"場": entry["session"], "候補ID": detail["候補ID"],
                "対象新規約定建玉数": sum(row["type"].endswith("N") for row in detail["約定"]),
                "対象完結取引数": len(detail["取引"]), "追尾行数": len(rows),
                "保存終了建玉": detail["品質"]["終了建玉"], "保存終了返済待機": detail["品質"]["終了返済待機"]})
        print(json.dumps({"場": entry["session"], "独立追尾": "全3最初要求/旧A5対照/現在費用後strict正/ATR全線", "不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    S.compare_keys(audit, "全追尾原順集合", set(saved), set(expected))
    for key in sorted(saved.keys() & expected.keys()):
        audit.check("追尾:" + str(key), saved[key], expected[key])
    count = sum(len(row["取引"]) for row in details)
    audit.check("正式全完結数", count, sum(row[period]["運用"]["完結取引数"] for row in formal["結果"]
        for period in ("学習", "条件選択", "後続検査")))
    audit.check("独立実行中コード不変", V.sha(Path(__file__)), initial)
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "対象場候補数": len(details), "対象完結取引数": count, "保存追尾行数": len(logs), "独立追尾行数": len(expected),
        "保存通常線行数": len(logs), "独立動作数": dict(totals), "場候補別": summaries,
        "対象新規約定建玉数": sum(row["対象新規約定建玉数"] for row in summaries),
        "保存未解消候補場数": sum(bool(row["保存終了建玉"] or row["保存終了返済待機"]) for row in summaries),
        "コードSHA256": initial, "独立追尾補助SHA256": V.sha(EXIT_HELPER),
        "依存コードSHA256": Y.dependency_pins(), "結果SHA256": V.sha(study / "結果.json"),
        "入力台帳SHA256": V.sha(study / "入力台帳.json"), "参照入力台帳SHA256": V.sha(resolved),
        "解決入力台帳SHA256": V.sha(resolved), "入口参照SHA256": V.sha(study / "入口参照.json"),
        "主準備SHA256": V.sha(work / "準備点検.json"), "全運用詳細展開SHA256": detail_sha, "追尾展開SHA256": log_sha,
        "通常線更新展開SHA256": log_sha, "入口事例展開SHA256": state["入口事例展開SHA256"],
        "共有入口事例展開SHA256": state["共有入口事例展開SHA256"],
        "状態独立確認SHA256": V.sha(work / "状態独立確認.json"),
        "検証範囲": "旧A5対照T0_X0は固定21独立走査をread再用。二XFは別走査の現在返済BBO十進表示価格から費用後円を分数化しstrict正で起動、出典122円/12.2pt境界と全cost_armを照合。全3運用の実新規から実返済又は場末までのhard125/TP250/期限/入口ATR距離/呼値/非緩和/最初要求/全追尾snapshotを検算。完結属性の対象数と全新規保有区間数は別記。",
        "限界": "保存実新規/返済区間は入力。新規受入/一秒後正常BBO代理約定/会計/先着は別監査。未解消があればEOF要求までの線を対象とするが完結取引属性や確定損益を作らず、保存未解消数と品質/確定額は会計証明へ委ねる。最低同値設定は実同値約定や費用後非赤字を保証しない。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存追尾行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """root正式完了通知後の明示起動だけを受け付ける。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。無許可と不一致は非0終了。
    """
    parser = argparse.ArgumentParser(description="00033固定A5追尾の独立確認")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--実行許可", action="store_true")
    args = parser.parse_args()
    if not args.実行許可:
        parser.error("root正式完了通知後に --実行許可 を指定してください")
    if not run(args.study.resolve(), args.work.resolve())["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
