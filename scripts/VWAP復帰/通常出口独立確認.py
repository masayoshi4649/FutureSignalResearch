"""00019の全X1/X2について、保存実新規後の最初要求と通常線遷移を別に再構成する。"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00019_VWAP復帰の入口と通常出口"
WORK = ROOT / "work/VWAP復帰/00019"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
ENTRY_HELPER = Path(__file__).with_name("状態独立確認.py")
QUOTE_HELPER = ROOT / "scripts/利益回収/出口独立確認.py"


def helper(path: Path, name: str) -> Any:
    """独立した読取/比較補助だけを読む。

    引数: path (Path) は補助、name (str) はモジュール名。
    返り値: Any は補助。新通常出口classやdriverはimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


I = helper(ENTRY_HELPER, "通常出口の独立状態補助")
B = helper(QUOTE_HELPER, "通常出口の独立原気配")
V, S = I.V, I.S
POSITION_FIELDS = ("id", "event_id", "side", "price", "time", "line", "native_entry", "native_level", "native_epoch", "native_updates")


def replay(detail: dict, quotes: list[dict], frames: list[dict], signals: dict[str, dict],
           audit: Any) -> tuple[list[dict], dict]:
    """保存実新規を固定し、保有区間の全quote/barから返済要求と線ログを独立計算する。

    引数: detail (dict) は一候補一場の保存詳細、quotes/frames (list[dict]) は正常板/検証済み公開足、
    signals (dict[str,dict]) は独立確認済みの入口、audit (Any) は比較先。
    返り値: tuple[list[dict],dict] は独立通常ログと動作数。注文受入/約定会計は親監査へ分ける。
    """
    method, session = detail["候補ID"], detail["場"]
    policy, role = method.rsplit("_", 1)[1], detail["品質"]["入口役割"]
    start, finish, force = B.bounds(session)
    new_fills = [f for f in detail["約定"] if f["type"].endswith("N")]
    exit_fills = {f["position_id"]: f for f in detail["約定"] if f["type"].endswith("R")}
    trades = {t["建玉ID"]: t for t in detail["取引"]}
    exit_orders = {o["入口イベントID"]: o for o in detail["注文"] if o["区分"] == "返済"}
    new_orders = [o for o in detail["注文"] if o["区分"] == "新規"]
    entries = {(f["price_clock"], f["source_line"]): f for f in new_fills}
    closings = {(f["price_clock"], f["source_line"]): f for f in exit_fills.values()}
    # 実保有外では通常線の動作がない。正常板初期値は新規約定のquote自身から始められる。
    base = [(q["now"], q["line"], 0, q) for q in quotes]
    base += [(r["confirm"], r["confirm_line"], 1, r) for r in frames
             if r["publish"] and start <= r["confirm"] < finish]
    base.sort(key=lambda row: row[:3])
    keys = [row[:3] for row in base]
    selected = []
    for fill in new_fills:
        closing = exit_fills.get(fill["position_id"])
        left = (fill["price_clock"], fill["source_line"], 0)
        right = (closing["price_clock"], closing["source_line"], 1) if closing else (finish, 2**63 - 1, 1)
        selected.extend(base[bisect_left(keys, left):bisect_right(keys, right)])
    selected += [(o["要求時計秒"], o["要求原板行"], 2, o) for o in new_orders]
    selected.sort(key=lambda row: row[:3])
    logs, counts, position, pending, last_quote, force_done = [], Counter(), None, None, None, False

    def log(action: str, now: float, line: int, **attributes: Any) -> None:
        """不変の独立通常線snapshotを追加する。

        引数: action (str) は動作、now/line (float/int) はキー、attributes (Any) は動作属性。
        返り値: None。保有中の値だけをコピーする。
        """
        snapshot = {k: position[k] for k in POSITION_FIELDS} if position is not None else None
        logs.append({"場": session, "候補ID": method, "期間": detail["品質"]["期間"],
            "順序": len(logs) + 1, "動作": action, "時計秒": now, "原板行": line, "建玉": snapshot, **attributes})

    def request(now: float, line: int, reason: str) -> None:
        """最初に導いた返済要求を保存注文と比較し、後続更新を抑止する。

        引数: now/line (float/int) は要求キー、reason (str) は独立理由。
        返り値: None。保存要求時刻・理由を判定へ流用しない。
        """
        nonlocal pending
        order = exit_orders.get(position["event_id"])
        audit.check(method + ":" + position["id"] + ":返済注文が存在", order is not None, True)
        if order is not None:
            audit.check(method + ":" + position["id"] + ":最初返済要求",
                        (order["要求時計秒"], order["要求原板行"], order["理由"]), (now, line, reason))
        pending = reason
        log("注文要求", now, line, 区分="返済", 理由=reason, 注文ID=order["注文ID"] if order else "保存注文なし")
        counts["最初要求数"] += 1

    def before(now: float) -> None:
        """価格イベントより先に一度だけ期限予約を適用する。

        引数: now (float) は次の観測時計。
        返り値: None。既存の返済要求は置き換えない。
        """
        nonlocal force_done
        if now >= force and not force_done:
            force_done = True
            if position is not None and pending is None:
                request(force, 0, "期限")

    def normal(now: float, line: int, quote: dict, origin: str) -> None:
        """現在気配と通常線の等号込み条件を独立判定する。

        引数: now/line (float/int) はキー、quote (dict) は正常板、origin (str) は判定元。
        返り値: None。価格到達なら通常ログ後に返済要求する。
        """
        if position is None or pending is not None:
            return
        mark = quote["bid"] if position["side"] == 1 else quote["ask"]
        distance = position["side"] * (mark - position["native_level"])
        if (distance <= 0 if role == "順行" else distance >= 0):
            reason = "VWAP通常逆抜け" if role == "順行" else "VWAP通常到達"
            log("通常閾値到達", now, line, 返済気配=mark, 判定元=origin, 理由=reason)
            counts["通常出口要求数"] += 1
            request(now, line, reason)

    for now, line, kind, value in selected:
        before(now)
        if kind == 2:
            audit.check(method + ":" + value["注文ID"] + ":新規要求時は建玉なし", position is None, True)
            log("注文要求", now, line, 区分="新規", 理由=value["理由"], 注文ID=value["注文ID"])
            continue
        if kind == 0:
            last_quote = value
            fill = entries.get((now, line))
            if fill is not None:
                source = signals[fill["entry_event_id"]]
                audit.check(method + ":" + fill["position_id"] + ":新規重複なし", position is None, True)
                side = 1 if fill["type"].startswith("Long") else -1
                position = {"id": fill["position_id"], "event_id": fill["entry_event_id"], "side": side,
                    "price": fill["price"], "time": now, "line": line, "native_entry": source["配信VWAP"],
                    "native_level": source["配信VWAP"], "native_epoch": source["補助epoch"], "native_updates": 0}
                pending = None
                log("通常線初期化", now, line, 入口要求時計=source["要求時計秒"], 入口要求原行=source["要求原板行"],
                    判断終値からnative方向距離pt=source.get("判断終値からnative方向距離pt"),
                    実新規から初期通常線方向距離pt=side * (source["配信VWAP"] - fill["price"]))
            closing = closings.get((now, line))
            if closing is not None:
                audit.check(method + ":" + closing["position_id"] + ":返済要求済み", pending is not None, True)
                audit.check(method + ":" + closing["position_id"] + ":閉鎖所有者", position["id"] if position else None, closing["position_id"])
                trade = trades[closing["position_id"]]
                if position is not None:
                    for field, expected in (("入口配信VWAP", position["native_entry"]), ("返済時通常線", position["native_level"]),
                        ("入口補助epoch", position["native_epoch"]), ("通常線更新数", position["native_updates"]),
                        ("固定利確使用", True), ("利確価格", position["price"] + position["side"] * 250),
                        ("判断終値からnative方向距離pt", signals[position["event_id"]].get("判断終値からnative方向距離pt")),
                        ("実新規から初期通常線方向距離pt", position["side"] * (position["native_entry"] - position["price"]))):
                        audit.check(method + ":" + position["id"] + ":" + field, trade[field], expected)
                    audit.check(method + ":" + position["id"] + ":返済理由", trade["返済理由"], pending)
                    log("通常建玉終了", now, line, 返済理由=pending)
                position, pending = None, None
                counts["完結取引数"] += 1
            if position is not None and pending is None:
                mark = value["bid"] if position["side"] == 1 else value["ask"]
                profit = position["side"] * (mark - position["price"])
                if profit <= -125:
                    request(now, line, "保護")
                elif profit >= 250:
                    request(now, line, "利確")
                else:
                    normal(now, line, value, "正常気配")
            continue
        if position is None:
            continue
        if pending is not None:
            log("通常足判定抑止", now, line, 理由="既存注文待機", 注文理由=pending)
            continue
        if not value["publish"] or now - value["end"] > 30 or not value["native有効"]:
            log("通常線据置", now, line, 理由="有効公開native参照でない", 公開=value["publish"], native有効=value["native有効"])
            counts["通常参照不可据置回数"] += 1
            continue
        if value["補助epoch"] != position["native_epoch"]:
            log("起算不一致", now, line, 現epoch=value["補助epoch"])
            counts["起算失効要求数"] += 1
            request(now, line, "VWAP起算失効")
            continue
        if policy == "X1":
            log("通常線据置", now, line, 理由="入口native固定")
            continue
        if value["end"] <= position["time"]:
            log("通常更新抑止", now, line, 理由="足終了が新規約定後でない")
            continue
        old = position["native_level"]
        position["native_level"] = value["配信VWAP"]
        position["native_updates"] += 1
        counts["通常線更新回数"] += 1
        log("通常線更新", now, line, 旧通常線=old, 新通常線=position["native_level"])
        if last_quote is not None and (last_quote["now"], last_quote["line"]) == (now, line):
            normal(now, line, last_quote, "同原行更新直後")
        else:
            log("通常価格判定待機", now, line, 理由="最新正常BBOが確認キーと異なる",
                最新正常キー=[last_quote["now"], last_quote["line"]] if last_quote else None)
    before(finish)
    for field in ("通常出口要求数", "起算失効要求数", "通常線更新回数", "通常参照不可据置回数"):
        audit.check(method + ":" + session + ":" + field, detail["品質"][field], counts[field])
    audit.check(method + ":" + session + ":全完結取引", counts["完結取引数"], len(detail["取引"]))
    return logs, dict(counts)


def run(study: Path, work: Path) -> dict:
    """全X1/X2のログと最初返済要求を原気配/確認済み公開足から独立照合する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は明示合否・全対象件数・指紋。約定会計の独立検算とは区別する。
    """
    if not (study / "結果.json").exists() or not (work / "状態独立確認.json").exists():
        raise ValueError("正式結果と状態独立確認の完了が必要")
    audit, manifest, formal = V.Audit(), V.read(INPUT), V.read(study / "結果.json")
    state_proof = V.read(work / "状態独立確認.json")
    audit.check("入口状態確認成功", state_proof["全件一致"], True)
    audit.check("入口状態コード指紋", state_proof["コードSHA256"], V.sha(ENTRY_HELPER))
    details, detail_sha = S.compressed_rows(work / "全運用詳細.jsonl.gz")
    normal_rows, normal_sha = S.compressed_rows(work / "通常線更新.jsonl.gz")
    cases, case_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    references, reference_sha = S.compressed_rows(work / "全足参照.jsonl.gz")
    audit.check("入口事例同一", case_sha, state_proof["入口事例展開SHA256"])
    audit.check("全参照同一", reference_sha, state_proof["全足参照展開SHA256"])
    signal_map = {r["イベントID"]: {k: r[k] for k in ("配信VWAP", "補助epoch", "要求時計秒", "要求原板行",
        "判断終値からnative方向距離pt")} for r in cases}
    grouped, logs_by_key = defaultdict(list), {}
    for detail in details:
        if detail["候補ID"].endswith(("_X1", "_X2")):
            grouped[detail["場"]].append(detail)
    expected_candidates = [r for r in formal["結果"] if r["候補ID"].endswith(("_X1", "_X2"))]
    expected_pairs = {(e["session"], r["候補ID"]) for e in manifest["entries"] for r in expected_candidates}
    actual_pairs = [(d["場"], d["候補ID"]) for rows in grouped.values() for d in rows]
    audit.check("全X1/X2の24候補", len(expected_candidates), 24)
    audit.check("場候補詳細の一意性", len(set(actual_pairs)), len(actual_pairs))
    S.compare_keys(audit, "全X1/X2の65場候補集合", set(actual_pairs), expected_pairs)
    for row in normal_rows:
        key = row["場"], row["候補ID"], row["順序"]
        if key in logs_by_key:
            raise ValueError("通常線ログのキー重複")
        logs_by_key[key] = row
    frame_groups = defaultdict(list)
    for row in references:
        frame_groups[row["場"], row["時間足分"]].append(row)
    expected_logs, totals, summary = {}, Counter(), []
    for entry in manifest["entries"]:
        loaded = B.load(entry)
        quotes = loaded[1]
        del loaded
        for detail in grouped[entry["session"]]:
            size = int(detail["候補ID"].split("分_", 1)[0])
            logs, counts = replay(detail, quotes, frame_groups[entry["session"], size], signal_map, audit)
            expected_logs.update({(r["場"], r["候補ID"], r["順序"]): r for r in logs})
            totals.update(counts)
            summary.append({"場": entry["session"], "候補ID": detail["候補ID"], "対象完結取引数": len(detail["取引"]), "通常線行数": len(logs)})
        print(json.dumps({"場": entry["session"], "独立確認": "X1/X2最初要求・通常線全遷移", "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    S.compare_keys(audit, "通常線全原順ログ集合", set(logs_by_key), set(expected_logs))
    for key in logs_by_key.keys() & expected_logs.keys():
        audit.check(f"通常線{key}", logs_by_key[key], expected_logs[key])
    target_count = sum(len(d["取引"]) for rows in grouped.values() for d in rows)
    audit.check("正式全X1/X2完結取引を対象化", target_count,
        sum(r[p]["運用"]["完結取引数"] for r in expected_candidates for p in ("学習", "条件選択", "後続検査")))
    result = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "対象場候補数": len(summary), "対象完結取引数": target_count,
        "保存通常線行数": len(normal_rows), "独立通常線行数": len(expected_logs), "独立動作数": dict(totals), "場候補別": summary,
        "コードSHA256": V.sha(Path(__file__)), "結果SHA256": V.sha(study / "結果.json"),
        "全運用詳細展開SHA256": detail_sha, "通常線更新展開SHA256": normal_sha,
        "入口事例展開SHA256": case_sha, "全足参照展開SHA256": reference_sha,
        "状態独立確認SHA256": V.sha(work / "状態独立確認.json"),
        "入力台帳SHA256": V.sha(INPUT), "独立正常板補助SHA256": V.sha(QUOTE_HELPER),
        "検証範囲": "全X1/X2の保存実新規と実保有区間を固定し、旧cacheの全正常quoteと独立確認済み公開足をquote→bar→新規要求の順へ再結合。入口signal native固定からhard125→TP250→通常閾値、期限/既pending優先、有効epoch失効、X2保有後更新/同値回数、確認key完全一致時だけ更新直後判定を別計算。全完結の最初要求・返済時線/更新数と、未約定新規要求を含む全通常線ログ/原順/抑止を照合。",
        "限界": "新19通常状態や元運用classをimportして再実行しない。保存実新規/実返済区間は入力とし、注文受入・一秒後BBO約定・会計はrootの別監査へ分ける。公開足/補助は19状態独立確認と固定18全参照の検査を前提に、ここで原板全行を再抽出しない。通常線は実発注可能価格の約定を意味せず、未観測価格空白や固有受信時計欠如は解消しない。"}
    (work / "通常出口独立確認.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存通常線行数")}, ensure_ascii=False))
    if audit.errors:
        print(json.dumps(audit.errors[:5], ensure_ascii=False))
    return result


def main() -> None:
    """正式再生/状態確認完了後だけ通常出口の独立検算を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不許可時は実データを開かない。
    """
    parser = argparse.ArgumentParser(description="00019通常出口の原気配独立確認")
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
