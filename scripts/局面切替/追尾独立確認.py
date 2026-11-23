"""00020全45運用の利益追尾と通常出口を、正常気配原順から別計算する。"""

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
STUDY = ROOT / "study/00020_テクニカル局面による順行反転の切替"
WORK = ROOT / "work/局面切替/00020"
INPUT = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
STATE_HELPER = Path(__file__).with_name("状態独立確認.py")
QUOTE_HELPER = ROOT / "scripts/利益回収/出口独立確認.py"
POSITION_FIELDS = ("id", "event_id", "side", "price", "time", "line", "entry_role", "native_entry",
    "native_level", "native_epoch", "native_updates", "atr_entry", "mfe", "mae", "armed", "trail_A",
    "trail_D", "trail_stop", "trail_arm_time", "trail_arm_line")


def helper(path: Path, name: str) -> Any:
    """既検証の独立読取/比較補助だけを読む。

    引数: path (Path) は補助、name (str) はモジュール識別名。
    返り値: Any は補助。20入口/運用classはimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


I = helper(STATE_HELPER, "必須追尾の独立状態")
B = helper(QUOTE_HELPER, "必須追尾の独立正常板")
V, S = I.V, I.S


def replay(detail: dict, quotes: list[dict], frames: list[dict], signals: dict[str, dict],
           audit: Any, bounds: tuple | None = None) -> tuple[list[dict], dict]:
    """実保有区間の全正常気配から、最初要求・追尾/通常線・役割固定を再構成する。

    引数: detail (dict) は保存一場詳細、quotes/frames (list[dict]) は正常板/検証済足、
    signals (dict[str,dict]) は検証済入口、audit (Any) は比較先、bounds (tuple|None) は合成時計。
    返り値: tuple[list[dict],dict] は独立全ログと件数。保存要求理由は条件に流用しない。
    """
    method, session = detail["候補ID"], detail["場"]
    policy = method.rsplit("_", 1)[1]
    start, finish, force = bounds if bounds is not None else B.bounds(session)
    new_fills = [f for f in detail["約定"] if f["type"].endswith("N")]
    exit_fills = {f["position_id"]: f for f in detail["約定"] if f["type"].endswith("R")}
    trades = {t["建玉ID"]: t for t in detail["取引"]}
    exit_orders = {o["入口イベントID"]: o for o in detail["注文"] if o["区分"] == "返済"}
    new_orders = [o for o in detail["注文"] if o["区分"] == "新規"]
    entries = {(f["price_clock"], f["source_line"]): f for f in new_fills}
    closings = {(f["price_clock"], f["source_line"]): f for f in exit_fills.values()}
    base = [(q["now"], q["line"], 0, q) for q in quotes]
    base += [(r["confirm"], r["confirm_line"], 1, r) for r in frames
             if r["publish"] and start <= r["confirm"] < finish]
    base.sort(key=lambda r: r[:3])
    keys, selected = [r[:3] for r in base], []
    for f in new_fills:
        closing = exit_fills.get(f["position_id"])
        left = f["price_clock"], f["source_line"], 0
        right = (closing["price_clock"], closing["source_line"], 1) if closing else (finish, 2**63 - 1, 1)
        selected.extend(base[bisect_left(keys, left):bisect_right(keys, right)])
    selected += [(o["要求時計秒"], o["要求原板行"], 2, o) for o in new_orders]
    selected.sort(key=lambda r: r[:3])
    position, pending, last_quote, force_done = None, None, None, False
    logs, counts = [], Counter()

    def log(action: str, now: float, line: int, **attributes: Any) -> None:
        """現在の独立建玉を不変snapshotとして保存する。

        引数: action (str) は動作、now/line (float/int) は根拠、attributes (Any) は補足。
        返り値: None。初期化前の追尾属性はNoneとする。
        """
        snapshot = {k: position.get(k) for k in POSITION_FIELDS} if position is not None else None
        logs.append({"場": session, "候補ID": method, "期間": detail["品質"]["期間"],
            "順序": len(logs) + 1, "動作": action, "時計秒": now, "原板行": line, "建玉": snapshot, **attributes})

    def request(now: float, line: int, reason: str) -> None:
        """独立に初着した返済要求を保存注文へ照合する。

        引数: now/line (float/int) は要求キー、reason (str) は独立理由。
        返り値: None。一度要求した後は追尾/通常線を変更しない。
        """
        nonlocal pending
        order = exit_orders.get(position["event_id"])
        audit.check(method + ":" + position["id"] + ":返済注文存在", order is not None, True)
        if order is not None:
            audit.check(method + ":" + position["id"] + ":最初返済要求",
                (order["要求時計秒"], order["要求原板行"], order["理由"]), (now, line, reason))
        pending = reason
        log("注文要求", now, line, 区分="返済", 理由=reason, 注文ID=order["注文ID"] if order else "保存注文なし")
        counts["最初要求数"] += 1

    def before(now: float) -> None:
        """観測処理前に期限予約を一度だけ適用する。

        引数: now (float) は次のイベント時計。
        返り値: None。既存返済要求を上書きしない。
        """
        nonlocal force_done
        if now >= force and not force_done:
            force_done = True
            if position is not None and pending is None:
                request(force, 0, "期限")

    def normal(now: float, line: int, q: dict, origin: str) -> None:
        """実約定信号の固定役割だけで通常線を判定する。

        引数: now/line (float/int) はキー、q (dict) は正常板、origin (str) は判定元。
        返り値: None。X0/既pending中には通常要求を作らない。
        """
        if policy == "X0" or position is None or pending is not None:
            return
        mark = q["bid"] if position["side"] == 1 else q["ask"]
        distance = position["side"] * (mark - position["native_level"])
        if (distance <= 0 if position["entry_role"] == "順行" else distance >= 0):
            reason = "VWAP通常逆抜け" if position["entry_role"] == "順行" else "VWAP通常到達"
            log("通常閾値到達", now, line, 返済気配=mark, 判定元=origin, 理由=reason)
            counts["通常出口要求数"] += 1
            request(now, line, reason)

    def trail(now: float, line: int, q: dict) -> None:
        """5pt起動・最低同値・呼値丸め・ratchetと最初の追尾閾値を別計算する。

        引数: now/line (float/int) は根拠、q (dict) は正常板。
        返り値: None。要求pending中は起動も設定更新もしない。
        """
        if position is None or pending is not None or position["mfe"] < 5:
            return
        if not position["armed"]:
            position.update(armed=True, trail_arm_time=now, trail_arm_line=line)
            counts["追尾起動取引数"] += 1
            log("追尾起動", now, line)
        raw = position["price"] + position["side"] * max(0, position["mfe"] - position["trail_D"])
        candidate = (math.ceil(raw / 5) if position["side"] == 1 else math.floor(raw / 5)) * 5
        old = position["trail_stop"]
        stop = candidate if old is None else (max(old, candidate) if position["side"] == 1 else min(old, candidate))
        if stop != old:
            position["trail_stop"] = stop
            counts["追尾線更新回数"] += 1
            log("追尾線更新", now, line, 旧追尾価格=old, 新追尾価格=stop, 丸め前価格=raw)
        audit.check(method + ":" + position["id"] + ":起動後最低同値",
            position["side"] * (position["trail_stop"] - position["price"]) >= 0, True)
        mark = q["bid"] if position["side"] == 1 else q["ask"]
        if position["side"] * (mark - stop) <= 0:
            counts["追尾要求数"] += 1
            log("追尾閾値初着", now, line, 返済気配=mark)
            request(now, line, "必須利益追尾")

    def mark(q: dict) -> None:
        """pending中と実返済行を含めてMFE/MAEだけを更新する。

        引数: q (dict) は正常BBO。
        返り値: None。MFEの増加を追尾起動と同一視しない。
        """
        if position is not None:
            distance = position["side"] * ((q["bid"] if position["side"] == 1 else q["ask"]) - position["price"])
            position["mfe"] = max(position["mfe"], distance)
            position["mae"] = max(position["mae"], -distance)

    for now, line, kind, value in selected:
        before(now)
        if kind == 2:
            audit.check(method + ":" + value["注文ID"] + ":新規要求時建玉なし", position is None, True)
            log("注文要求", now, line, 区分="新規", 理由=value["理由"], 注文ID=value["注文ID"])
            continue
        if kind == 0:
            last_quote = value
            mark(value)
            fill = entries.get((now, line))
            if fill is not None:
                audit.check(method + ":" + fill["position_id"] + ":新規重複なし", position is None, True)
                source = signals[fill["entry_event_id"]]
                side = 1 if fill["type"].startswith("Long") else -1
                position = {"id": fill["position_id"], "event_id": fill["entry_event_id"], "side": side,
                    "price": fill["price"], "time": now, "line": line, "mfe": 0.0, "mae": 0.0, "armed": False,
                    "atr_entry": float(source["atr"]), "native_entry": source["配信VWAP"], "native_level": source["配信VWAP"],
                    "native_epoch": source["補助epoch"], "native_updates": 0}
                pending = None
                log("通常線初期化", now, line, 入口要求時計=source["要求時計秒"], 入口要求原行=source["要求原板行"],
                    判断終値からnative方向距離pt=source.get("判断終値からnative方向距離pt"),
                    実新規から初期通常線方向距離pt=side * (source["配信VWAP"] - fill["price"]))
                position.update(entry_role=source["役割"], trail_A=5, trail_D=max(5, math.ceil(source["atr"] / 5) * 5),
                    trail_stop=None, trail_arm_time=None, trail_arm_line=None)
                log("追尾初期化", now, line)
            closing = closings.get((now, line))
            if closing is not None:
                audit.check(method + ":" + closing["position_id"] + ":返済要求済み", pending is not None, True)
                audit.check(method + ":" + closing["position_id"] + ":返済所有者",
                    position["id"] if position else None, closing["position_id"])
                t = trades[closing["position_id"]]
                if position is not None:
                    net = position["side"] * (closing["price"] - position["price"]) * 10 - 22
                    armed_loss = bool(position["armed"] and net < 0)
                    expected = {"入口役割": position["entry_role"], "入口ATR": position["atr_entry"],
                        "入口配信VWAP": position["native_entry"], "返済時通常線": position["native_level"],
                        "入口補助epoch": position["native_epoch"], "通常線更新数": position["native_updates"],
                        "固定利確使用": True, "利確価格": position["price"] + position["side"] * 250,
                        "必須追尾使用": True, "通常出口使用": policy != "X0", "追尾起動幅pt": 5,
                        "追尾距離pt": position["trail_D"], "追尾起動": position["armed"], "利益床起動": position["armed"],
                        "最終追尾価格": position["trail_stop"], "追尾起動時計秒": position["trail_arm_time"],
                        "追尾起動原板行": position["trail_arm_line"], "起動後純赤字": armed_loss,
                        "観測最大順行pt": position["mfe"], "観測最大逆行pt": position["mae"], "返済理由": pending,
                        "最終追尾から実返済方向差pt": position["side"] * (closing["price"] - position["trail_stop"]) if position["trail_stop"] is not None else None,
                        "判断終値からnative方向距離pt": signals[position["event_id"]].get("判断終値からnative方向距離pt"),
                        "実新規から初期通常線方向距離pt": position["side"] * (position["native_entry"] - position["price"])}
                    for field, expected_value in expected.items():
                        audit.check(method + ":" + position["id"] + ":" + field, t[field], expected_value)
                    log("通常建玉終了", now, line, 返済理由=pending)
                    if armed_loss:
                        log("起動済み純赤字約定", now, line, 純損益円=net)
                        counts["起動後純赤字取引数"] += 1
                position, pending = None, None
                counts["完結取引数"] += 1
            mark(value)
            if position is not None and pending is None:
                mark_price = value["bid"] if position["side"] == 1 else value["ask"]
                distance = position["side"] * (mark_price - position["price"])
                if distance <= -125:
                    request(now, line, "保護")
                elif distance >= 250:
                    request(now, line, "利確")
            trail(now, line, value)
            normal(now, line, value, "正常気配")
            continue
        if position is None or policy == "X0":
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
    for field in ("通常出口要求数", "起算失効要求数", "通常線更新回数", "通常参照不可据置回数",
                  "追尾起動取引数", "追尾線更新回数", "追尾要求数", "起動後純赤字取引数"):
        audit.check(method + ":" + session + ":" + field, detail["品質"][field], counts[field])
    audit.check(method + ":" + session + ":全完結数", counts["完結取引数"], len(detail["取引"]))
    return logs, dict(counts)


# ----------------------------------------
# 数値coreは呼ばず、全45×65の保存logと原正常板を接続する。

def run(study: Path, work: Path) -> dict:
    """正式再生/状態確認後だけ全45の追尾/通常出口を全件検算する。

    引数: study/work (Path) は正式/作業先。
    返り値: dict は明示合否・件数・指紋・独立範囲。
    """
    if not (study / "結果.json").exists() or not (work / "状態独立確認.json").exists():
        raise ValueError("正式結果と状態独立確認の完了が必要")
    audit, manifest, formal = V.Audit(), V.read(INPUT), V.read(study / "結果.json")
    state_proof = V.read(work / "状態独立確認.json")
    audit.check("状態独立確認成功", state_proof["全件一致"], True)
    audit.check("状態独立コード", state_proof["コードSHA256"], V.sha(STATE_HELPER))
    details, detail_sha = S.compressed_rows(work / "全運用詳細.jsonl.gz")
    logs, log_sha = S.compressed_rows(work / "通常線と追尾.jsonl.gz")
    cases, case_sha = S.compressed_rows(work / "入口事例.jsonl.gz")
    references, reference_sha = S.compressed_rows(work / "全足参照.jsonl.gz")
    audit.check("入口事例SHA", case_sha, state_proof["入口事例展開SHA256"])
    audit.check("全参照SHA", reference_sha, state_proof["全足参照展開SHA256"])
    signals = {r["イベントID"]: {k: r[k] for k in
        ("atr", "役割", "配信VWAP", "補助epoch", "要求時計秒", "要求原板行", "判断終値からnative方向距離pt")} for r in cases}
    detail_groups, frame_groups, saved = defaultdict(list), defaultdict(list), {}
    for d in details:
        detail_groups[d["場"]].append(d)
    for f in references:
        frame_groups[f["場"], f["時間足分"]].append(f)
    for r in logs:
        key = r["場"], r["候補ID"], r["順序"]
        if key in saved:
            raise ValueError("追尾通常ログ重複")
        saved[key] = r
    candidates = [r["候補ID"] for r in formal["結果"]]
    audit.check("全45候補", len(candidates), 45)
    pairs = [(d["場"], d["候補ID"]) for d in details]
    audit.check("全場候補一意", len(pairs), len(set(pairs)))
    S.compare_keys(audit, "全45×65場候補", set(pairs), {(e["session"], c) for e in manifest["entries"] for c in candidates})
    expected, totals, summary = {}, Counter(), []
    for entry in manifest["entries"]:
        loaded = B.load(entry)
        quotes = loaded[1]
        del loaded
        for detail in detail_groups[entry["session"]]:
            size = int(detail["候補ID"].split("分_", 1)[0])
            rows, counts = replay(detail, quotes, frame_groups[entry["session"], size], signals, audit)
            expected.update({(r["場"], r["候補ID"], r["順序"]): r for r in rows})
            totals.update(counts)
            summary.append({"場": entry["session"], "候補ID": detail["候補ID"],
                "対象完結取引数": len(detail["取引"]), "通常追尾行数": len(rows)})
        print(json.dumps({"場": entry["session"], "独立確認": "全45追尾初着・役割固定・通常線",
            "現時点不一致数": audit.mismatches}, ensure_ascii=False), flush=True)
    S.compare_keys(audit, "全通常追尾ログ原順集合", set(saved), set(expected))
    for key in saved.keys() & expected.keys():
        audit.check(f"通常追尾:{key}", saved[key], expected[key])
    count = sum(len(d["取引"]) for d in details)
    audit.check("全45完結数を対象化", count, sum(r[p]["運用"]["完結取引数"] for r in formal["結果"] for p in
        ("学習", "条件選択", "後続検査")))
    proof = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
        "対象場候補数": len(summary), "対象完結取引数": count, "保存通常線行数": len(logs),
        "保存通常追尾行数": len(logs), "独立通常追尾行数": len(expected), "独立動作数": dict(totals), "場候補別": summary,
        "コードSHA256": V.sha(Path(__file__)), "結果SHA256": V.sha(study / "結果.json"),
        "全運用詳細展開SHA256": detail_sha, "通常線更新展開SHA256": log_sha, "通常線と追尾展開SHA256": log_sha,
        "入口事例展開SHA256": case_sha, "全足参照展開SHA256": reference_sha,
        "状態独立確認SHA256": V.sha(work / "状態独立確認.json"), "入力台帳SHA256": V.sha(INPUT),
        "独立正常板補助SHA256": V.sha(QUOTE_HELPER),
        "検証範囲": "全X0/X1/X2の保存実新規・保有区間を固定し、原cacheの全正常返済BBOと検証済み公開足から期限/既pending約定→hard125→TP250→必須追尾→通常VWAPの最初要求を独立計算。A=5,D=入口ATR呼値切上、MFE/MAE、起動key・最低同値・非緩和・売買対称丸め、pending中更新停止、起動後純赤字fill、実fill信号の役割固定を検算。X1固定/X2更新・epoch・同原行限定checkと全通常/追尾log原順も照合。",
        "限界": "20運用classをimportしない。保存実新規/実返済区間を固定入力とするため、注文受入/一建玉/+1秒後BBO約定/会計はroot別監査へ分離。補助と公開足は状態独立確認を前提とする。MFEが5以上でもhard/期限/既pendingが先なら追尾未起動を認め、追尾起動後同値以上の実約定・純額を保証しない。原板全行再抽出/固有受信時計の補完はしない。"}
    (work / "追尾独立確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件一致", "照合項目数", "不一致数", "対象完結取引数", "保存通常線行数")}, ensure_ascii=False))
    return proof


def main() -> None:
    """正式完了/状態確認成功後だけ実データ監査を開始する。

    引数: なし。--study/--work/--実行許可を読む。
    返り値: None。不一致時は非0終了。
    """
    parser = argparse.ArgumentParser(description="00020追尾と通常出口の原気配独立確認")
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
