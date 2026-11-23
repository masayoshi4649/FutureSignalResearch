"""00007の約定片からDecimal会計・費用感度・正常板参照を独立検算する。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import csv
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00007_固定入口の単一建玉と費用感度"
JST = timezone(timedelta(hours=9))


def sha(path: Path) -> str:
    """小型ファイルの内容を識別する。

    引数: path (Path) は入力。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table(path: Path) -> list[dict]:
    """正式CSVをUTF-8で読む。

    引数: path (Path) は入力。
    返り値: list[dict] は全行。
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def normalized(item: Any) -> Any:
    """空欄・真偽値・有限数値を比較用へ正規化する。

    引数: item (Any) はCSVまたはJSONセル。
    返り値: Any はNone、bool、Decimalまたは文字列。
    """
    if item is None or item == "":
        return None
    if isinstance(item, bool) or item in ("True", "False"):
        return item if isinstance(item, bool) else item == "True"
    try:
        number = Decimal(str(item))
        return number if number.is_finite() else item
    except InvalidOperation:
        return item


class Audit:
    """独立値と正本の比較だけを保持する。"""

    def __init__(self) -> None:
        """空の照合を作る。

        引数: なし。
        返り値: None。
        """
        self.count, self.errors = 0, []

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """金額・時計等を照合し差分を保存する。

        引数: name (str) は項目、actual/expected (Any) は独立値と正本。
        返り値: None。
        """
        self.count += 1
        a, b = normalized(actual), normalized(expected)
        equal = abs(a - b) <= Decimal("0.0000001") if isinstance(a, Decimal) and isinstance(b, Decimal) else a == b
        if not equal:
            self.errors.append({"項目": name, "独立値": actual, "正本": expected})


def bounds(session: str) -> tuple[float, float, float, float]:
    """場開始・終了・新規停止・期限を独立に求める。

    引数: session (str) は開始日基準の場名。
    返り値: tuple[float,float,float,float] はUnix秒。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("_Day"):
        stamps = [day.replace(hour=h, minute=m) for h, m in ((8, 45), (15, 40), (15, 25), (15, 35))]
    else:
        following = day + timedelta(days=1)
        stamps = [day.replace(hour=17), following.replace(hour=5, minute=55),
                  following.replace(hour=5, minute=40), following.replace(hour=5, minute=50)]
    return tuple(stamp.timestamp() for stamp in stamps)


# ----------------------------------------
# 運用検証.pyをimportせず、正常気配・約定・注文・取引を照合する。

def phase_audit(base: Path, phase: str, entries: dict, audit: Audit) -> dict:
    """一段階の全約定を単一建玉で会計し、場別・期間別感度を復元する。

    引数: base (Path) は成果物、phase (str) は段階、entries (dict) は入力台帳、audit (Audit) は照合先。
    返り値: dict は独立会計とViewer照合用の場別出所。
    """
    catalog = json.loads((base / "一覧.resources.json").read_text(encoding="utf-8"))
    session_rows, trades = table(base / "セッション集計.csv"), table(base / "取引集計.csv")
    orders, signals = table(base / "注文台帳.csv"), table(base / "入口取扱.csv")
    result = json.loads((base / "結果.json").read_text(encoding="utf-8"))
    info = json.loads((base / "実行情報.json").read_text(encoding="utf-8"))
    audit.check(phase + ":資源数", len(catalog["resources"]), 60 if phase == "探索" else 4)
    for relative, expected in info["ファイルSHA256"].items():
        audit.check(phase + ":固定SHA:" + relative, sha(ROOT / relative), expected)
    digest = hashlib.sha256()
    with gzip.open(ROOT / info["入口事例"], "rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    audit.check(phase + ":入口展開SHA", digest.hexdigest(), info["入口事例展開SHA256"])
    baselines, sensitive, fill_total = [], [], 0
    for resource in catalog["resources"]:
        session = resource["session"]
        start, end, cutoff, force = bounds(session)
        entry = entries[session]
        raw_status = (ROOT.parent / "JP_OSE_Data/future" / entry["source_path"]).stat()
        audit.check(session + ":原板stat", (raw_status.st_size, raw_status.st_mtime_ns), (entry["source_size"], entry["source_mtime_ns"]))
        audit.check(session + ":倍率", resource["point_value"], 10)
        audit.check(session + ":net", resource["pnl_basis"], "net")
        audit.check(session + ":原板参照", resource["market_path"], entry["source_path"])
        cache = ROOT / "work/複合検証" / entry["cache_path"]
        audit.check(session + ":cacheSHA", sha(cache), entry["sha256_cache"])
        with np.load(cache, allow_pickle=False) as archive:
            a = {key: archive[key] for key in ("now", "line", "bid", "ask", "valid")}
        indices = np.flatnonzero(np.isfinite(a["now"]) & (a["now"] >= start) & (a["now"] < end))
        clocks = a["now"][indices]
        keep = np.r_[True, clocks[1:] >= np.maximum.accumulate(clocks[:-1])]
        backwards = int(np.count_nonzero(~keep))
        indices = indices[keep]
        indices = indices[a["valid"][indices]]
        q = {key: a[key][indices] for key in ("now", "line", "bid", "ask")}
        at = {int(line): index for index, line in enumerate(q["line"])}
        clocks = np.r_[start, q["now"]]
        gaps = [(float(left), float(right)) for left, right in zip(clocks[:-1], clocks[1:]) if right - left > 300]
        fill_path = base / resource["pnl_path"]
        fills = [json.loads(line) for line in fill_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        own_orders = {row["注文ID"]: row for row in orders if row["場"] == session}
        own_signals = [row for row in signals if row["場"] == session]
        state_counts = Counter(row["取扱"] for row in own_signals)
        positions, completed, cash, fees, ids = {}, [], Decimal(0), Decimal(0), set()
        previous = None
        for number, fill in enumerate(fills, 1):
            label = session + f":約定{number}"
            clock, line = float(fill["price_clock"]), int(fill["source_line"])
            key, opening = fill["position_id"], fill["type"].endswith("N")
            side = 1 if fill["type"].startswith("Long") else -1
            audit.check(label + ":ID一意", fill["id"] not in ids, True)
            ids.add(fill["id"])
            audit.check(label + ":非後退", previous is None or (clock, line) >= previous, True)
            previous = clock, line
            index = at[line]
            audit.check(label + ":原行時計", float(q["now"][index]), clock)
            audit.check(label + ":ISO時計", datetime.fromisoformat(fill["timestamp"]).timestamp(), clock)
            expected_price = q["ask"][index] if (opening and side == 1) or (not opening and side == -1) else q["bid"][index]
            audit.check(label + ":BBO", fill["price"], float(expected_price))
            audit.check(label + ":1秒後最初", index, int(np.searchsorted(q["now"], fill["request_clock"] + 1, side="left")))
            audit.check(label + ":場内", start <= clock < end, True)
            audit.check(label + ":枚数", fill["qty"], 1)
            audit.check(label + ":費用", fill["fee_yen"], 11)
            order = own_orders[fill["order_id"]]
            for column, field in (("要求時計秒", "request_clock"), ("要求原板行", "request_source_line"),
                                  ("約定時計秒", "price_clock"), ("約定原板行", "source_line"), ("約定価格", "price")):
                audit.check(label + ":注文:" + column, order[column], fill[field])
            audit.check(label + ":注文状態", order["状態"], "約定")
            price, fee = Decimal(str(fill["price"])), Decimal(str(fill["fee_yen"]))
            cash -= fee
            fees += fee
            if opening:
                audit.check(label + ":単一建玉", sum(item["qty"] for item in positions.values()), 0)
                audit.check(label + ":有効期限", clock <= fill["request_clock"] + 30 and clock < cutoff, True)
                positions[key] = {"qty": 1, "side": side, "price": price, "fill": fill}
                continue
            position = positions[key]
            audit.check(label + ":返済方向", position["side"], side)
            audit.check(label + ":返済数量", position["qty"], 1)
            entry_fill = position["fill"]
            gross = side * (price - position["price"]) * 10
            cash += gross
            net = gross - Decimal(str(entry_fill["fee_yen"])) - fee
            trade = next(row for row in trades if row["場"] == session and row["建玉ID"] == key)
            for column, expected in (("新規価格", position["price"]), ("返済価格", price), ("粗損益円", gross),
                                     ("手数料円", 22), ("基準純損益円", net),
                                     ("利確価格", position["price"] + side * 250), ("保護価格", position["price"] - side * 125)):
                audit.check(label + ":取引:" + column, trade[column], expected)
            for slip in (0, 5, 10):
                audit.check(label + f":滑り{slip}", trade[f"追加滑り{slip}pt純損益円"], net - 2 * slip * 10)
            entered = float(entry_fill["price_clock"])
            entry_gap = any(entry_fill["request_clock"] < right <= entered for left, right in gaps)
            held_gap = any(entered < right <= clock for left, right in gaps)
            audit.check(label + ":待機空白", trade["新規待機空白"], entry_gap)
            audit.check(label + ":保有空白", trade["保有経路空白"], held_gap)
            audit.check(label + ":取引注意", trade["観測経路注意"], entry_gap or held_gap)
            completed.append({"entry": entered, "exit": clock, "net": net, "attention": entry_gap or held_gap})
            position["qty"] = 0
        held_gaps = sum(any(float(item["fill"]["price_clock"]) < right and
                           (item["qty"] or any(t["entry"] == item["fill"]["price_clock"] and t["exit"] >= right for t in completed))
                           for item in positions.values()) for left, right in gaps)
        waiting_gaps = sum(float(order["要求時計秒"]) < right and
                           (float(order["約定時計秒"]) if order["約定時計秒"] else min(float(order["要求時計秒"]) + 30, cutoff, force)) > left
                           for left, right in gaps for order in own_orders.values() if order["区分"] == "新規")
        unresolved = sum(item["qty"] for item in positions.values())
        flagged = [item for item in completed if item["attention"]]
        tail = not len(q["now"]) or float(q["now"][-1]) < force
        attention = bool(flagged or unresolved or held_gaps or waiting_gaps or tail)
        period = "後続検査" if phase != "探索" else "学習" if session[:10] < "2026-10-19" else "条件選択"
        baseline = {"銘柄": "NK225", "場": session, "手法": resource["method_id"], "期間": period,
                    "候補要求数": len(own_signals), "新規約定数": sum(fill["type"].endswith("N") for fill in fills),
                    "完結取引数": len(completed), "建玉中抑止数": state_counts["建玉中抑止"],
                    "注文待機中抑止数": state_counts["注文待機中抑止"], "両方向見送り数": state_counts["同時両方向見送り"],
                    "確認遅延不可数": state_counts["足確定確認遅延30秒超"],
                    "新規取消数": sum(order["区分"] == "新規" and order["状態"] not in ("約定", "待機") for order in own_orders.values()),
                    "終了建玉": unresolved, "終了返済待機": sum(order["状態"] == "待機" for order in own_orders.values()),
                    "観測現金増減円": cash, "観測完結取引純損益円": sum((item["net"] for item in completed), Decimal(0)),
                    "手数料円": fees, "観測経路注意取引数": len(flagged),
                    "経路注意取引純損益円": sum((item["net"] for item in flagged), Decimal(0)),
                    "場内正常板空白区間数": len(gaps), "保有中空白区間数": held_gaps, "新規待機中空白区間数": waiting_gaps,
                    "最長正常板間隔秒": float(np.max(np.diff(clocks))) if len(q["now"]) else 0.,
                    "正常板数": len(q["now"]), "正常板最終時計秒": float(q["now"][-1]) if len(q["now"]) else None,
                    "EOF期限未達": tail, "期限まで300秒超尾部": not len(q["now"]) or force - float(q["now"][-1]) > 300,
                    "観測経路注意": attention, "確定対象純損益円": None if attention else cash, "時計後退除外数": backwards}
        for slip in (0, 5, 10):
            extra = Decimal(2 * slip * 10 * len(completed))
            expected = {**baseline, "片道追加滑りpt": slip, "追加費用円": extra,
                        "観測現金増減円": cash - extra,
                        "観測完結取引純損益円": baseline["観測完結取引純損益円"] - extra,
                        "経路注意取引純損益円": baseline["経路注意取引純損益円"] - 2 * slip * 10 * len(flagged),
                        "確定対象純損益円": None if attention else cash - extra}
            stored = next(row for row in session_rows if row["場"] == session and int(row["片道追加滑りpt"]) == slip)
            for column, item in expected.items():
                audit.check(session + f":場別{slip}:" + column, stored[column], item)
            sensitive.append(expected)
        baselines.append({**baseline, "約定片数": len(fills), "資源ID": resource["id"], "約定SHA256": sha(fill_path)})
        fill_total += len(fills)

    # ----------------------------------------
    # 注意ありの場を含む総額はNoneを保ち、事後の部分集計は別に検算する。
    comparisons, period_rows = [], table(base / "期間比較.csv")
    for stored in result["集計"]:
        period, slip = stored["期間"], stored["片道追加滑りpt"]
        rows = [row for row in sensitive if row["片道追加滑りpt"] == slip and (period == "全対象" or row["期間"] == period)]
        clean = [row for row in rows if not row["観測経路注意"]]
        keys = ("候補要求数", "新規約定数", "建玉中抑止数", "注文待機中抑止数", "両方向見送り数", "確認遅延不可数", "新規取消数",
                "完結取引数", "観測経路注意取引数", "観測現金増減円", "観測完結取引純損益円", "経路注意取引純損益円", "手数料円", "追加費用円")
        expected = {"期間": period, "片道追加滑りpt": slip, "場数": len(rows),
                    **{key: sum(row[key] for row in rows) for key in keys},
                    "終了未解消場数": sum(bool(row["終了建玉"]) for row in rows),
                    "観測経路注意場数": sum(row["観測経路注意"] for row in rows), "EOF期限未達場数": sum(row["EOF期限未達"] for row in rows),
                    "確定対象純損益円": sum(row["確定対象純損益円"] for row in rows) if len(clean) == len(rows) else None,
                    "注意なし場数": len(clean), "注意なし場のみ純損益円": sum(row["確定対象純損益円"] for row in clean)}
        other = next(row for row in period_rows if row["期間"] == period and int(row["片道追加滑りpt"]) == slip)
        for key, item in expected.items():
            audit.check(phase + f":期間{period}/{slip}:" + key, stored[key], item)
            audit.check(phase + f":期間CSV{period}/{slip}:" + key, other[key], item)
        comparisons.append(expected)
    audit.check(phase + ":完結行数", len(trades), sum(row["完結取引数"] for row in baselines))
    return {"段階": phase, "資源数": len(catalog["resources"]), "全約定片数": fill_total,
            "場別": baselines, "期間比較": comparisons, "成果物ルート": str(base), "Viewer照合": []}


# ----------------------------------------
# 既存の読取専用Viewer照合を再利用する。運用の数値コードは読み込まない。

def verify_viewer(phases: list[dict], api: str, audit: Audit) -> None:
    """代表4資源の数値を照合し、PNGは新最大観測損益場の1枚だけ保存する。

    引数: phases (list[dict]) は独立会計、api (str) は接続先、audit (Audit) は照合先。
    返り値: None。追加滑り感度はViewerへ混ぜない。
    """
    path = ROOT / "scripts/複合検証/Viewer照合.py"
    spec = importlib.util.spec_from_file_location("運用の表示照合", path)
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    for phase in phases:
        base = Path(phase["成果物ルート"])
        resources = json.loads((base / "一覧.resources.json").read_text(encoding="utf-8"))["resources"]
        by_session = {item["session"]: item for item in resources}
        if phase["段階"] == "探索":
            attention = [row for row in phase["場別"] if row["観測経路注意"]]
            first = max(attention, key=lambda row: abs(row["観測現金増減円"]))
            selected = [(first, "経路注意場"), (min(phase["場別"], key=lambda row: row["観測現金増減円"]), "最小観測損益場")]
        else:
            selected = [(max(phase["場別"], key=lambda row: row["観測現金増減円"]), "最大観測損益場"),
                        (min(phase["場別"], key=lambda row: row["観測現金増減円"]), "最小観測損益場")]
        body, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": (base / "一覧.resources.json").relative_to(ROOT).as_posix()}))
        audit.check(phase["段階"] + ":API資源一覧", sorted(item["id"] for item in json.loads(body)["resources"]), sorted(item["id"] for item in resources))
        for row, reason in selected:
            adapted = {"銘柄": "NK225", "場": row["場"], "手法": row["手法"],
                       "純損益円": float(row["観測現金増減円"]), "取引数": row["完結取引数"]}
            image = (phase["段階"] == "追加確認" and reason == "最大観測損益場") or (len(phases) == 1 and reason == "経路注意場")
            checked = helper.check_one(api, base, adapted, by_session[row["場"]], reason, image)
            checked["観測経路注意"] = row["観測経路注意"]
            checked["確定対象純損益円"] = row["確定対象純損益円"]
            checked["意味"] = "追加滑り0ptの観測代理会計。注意場のAPI金額は確定収益を意味しない。"
            phase["Viewer照合"].append(checked)


def run(include_future: bool, api: str | None) -> dict:
    """許可された段階だけ独立監査し、結果を保存する。

    引数: include_future (bool) は新4の実行許可、api (str | None) はViewer接続先。
    返り値: dict は監査結果。運用検証.pyはimportしない。
    """
    config = json.loads((STUDY / "条件.json").read_text(encoding="utf-8"))
    source = (STUDY / config["入口元試行"]).resolve()
    manifest = json.loads((source / "入力台帳.json").read_text(encoding="utf-8"))
    entries = {item["session"]: item for item in manifest["entries"]}
    audit = Audit()
    phases = [phase_audit(STUDY, "探索", entries, audit)]
    if include_future:
        phases.append(phase_audit(STUDY / "追加確認", "追加確認", entries, audit))
    if api:
        verify_viewer(phases, api, audit)
    result = {"確認日時": datetime.now(JST).isoformat(), "全件一致": not audit.errors,
              "照合項目数": audit.count, "不一致": audit.errors, "新4照合の許可": include_future,
              "コードSHA256": sha(Path(__file__)), "段階別": phases,
              "方法": "運用検証.pyをimportせず、Decimal約定片台帳、cache正常BBO原行、待機後最初の正常板、gap交差、注文・取引・場別/期間別費用感度を照合。",
              "限界": "入口受付と返済要求の全逐次遷移は本監査で全面再生しない。追加滑りは完結往復だけの費用感度。観測経路注意を含む現金を確定収益としない。"}
    if api:
        with urlopen(api + "/api/info", timeout=10) as response:
            api_info = json.load(response)
        binary = ROOT / "work/viewer/session-trade-viewer.exe"
        distribution = ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"
        pid_file = ROOT / "work/viewer/process-id.txt"
        view_record = {"確認日時": datetime.now(JST).isoformat(), "接続先": api, "API情報": api_info,
                       "設定": "work/viewer/conf/viewer.toml",
                       "起動": {"実行コピー": binary.relative_to(ROOT).as_posix(), "WindowStyle": "Hidden",
                                "PID_記録ファイル": pid_file.read_text(encoding="utf-8-sig").strip() if pid_file.exists() else None,
                                "実行コピーSHA256": sha(binary), "指定配布版SHA256": sha(distribution)},
                       "パス解決": "market_pathはAPI情報のdata_root基準。pnl_pathはpath_base=catalogにより各resources.jsonの親基準。市場ファイルを一覧の親から解決しない。",
                       "読込例": "/?catalog=study/00007_固定入口の単一建玉と費用感度/追加確認/一覧.resources.json&resource=00007_2026-11-03_Day&interval=5&price=last",
                       "代表選択": "旧60は経路注意場の最大絶対観測損益と最小観測損益、新4は最大・最小観測損益。同値は一覧順。画像は新最大の1枚だけ。",
                       "照合": [{"段階": phase["段階"], **checked} for phase in phases for checked in phase["Viewer照合"]],
                       "表示コードSHA256": sha(ROOT / "scripts/複合検証/Viewer照合.py"),
                       "注意": "全代表は追加滑り0pt・手数料11円の観測代理会計。注意場の金額は確定収益でない。5/10ptの感度をViewerへ混ぜない。"}
        (STUDY / "Viewer照合.json").write_text(json.dumps(view_record, ensure_ascii=False, indent=2, allow_nan=False, default=float) + "\n", encoding="utf-8")
        result["Viewer記録"] = "Viewer照合.json"
    target = STUDY / "独立監査.json" if include_future else ROOT / "work/広域研究/00007独立監査_探索.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"全件一致": result["全件一致"], "照合項目数": audit.count, "不一致": audit.errors,
                      "段階別": [{"段階": item["段階"], "資源数": item["資源数"], "約定片数": item["全約定片数"],
                                 "全対象": [row for row in item["期間比較"] if row["期間"] == "全対象"]} for item in phases]}, ensure_ascii=False, default=float))
    return result


def main() -> None:
    """新4許可とViewer接続先をCLIで受け付ける。

    引数: なし。--include-future/--api-baseを取得する。
    返り値: None。不一致は保存後に終了コード1とする。
    """
    parser = argparse.ArgumentParser(description="00007独立会計・Viewer監査")
    parser.add_argument("--include-future", action="store_true")
    parser.add_argument("--api-base")
    arguments = parser.parse_args()
    if not run(arguments.include_future, arguments.api_base.rstrip("/") if arguments.api_base else None)["全件一致"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
