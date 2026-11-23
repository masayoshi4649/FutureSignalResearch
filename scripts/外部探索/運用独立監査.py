"""00008のDecimal会計・注文と原行・旧対照・Viewerを独立に照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from datetime import datetime
import gzip
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
WORK = ROOT / "work/外部研究/探索00008"
OLD = ROOT / "study/00007_固定入口の単一建玉と費用感度"


def load(path: Path, name: str) -> Any:
    """独立監査または表示補助を読み込む。

    引数: path (Path) は補助コード、name (str) はモジュール名。
    返り値: Any は読込結果。運用・入口・選定コードは読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


HELPER = load(ROOT / "scripts/広域研究/運用独立監査.py", "共通独立監査補助")
Audit, sha, table, bounds = HELPER.Audit, HELPER.sha, HELPER.table, HELPER.bounds


def read(path: Path) -> Any:
    """日本語JSONを読む。

    引数: path (Path) は入力。
    返り値: Any はJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def quotes(entry: dict, allow_future: bool) -> dict:
    """固定cacheを場内・非後退・正常BBOへ絞る。

    引数: entry (dict) は台帳行、allow_future (bool) は新1読取許可。
    返り値: dict は気配列・原行索引・空白・時計後退数。
    """
    if entry["session"] >= "2026-11-04" and not allow_future:
        raise ValueError("新1場は読取許可前")
    source = ROOT.parent / "JP_OSE_Data/future" / entry["source_path"]
    status = source.stat()
    if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
        raise ValueError("原板stat不一致")
    path = ROOT / "work/複合検証" / entry["cache_path"]
    if sha(path) != entry["sha256_cache"] or path.stat().st_size != entry["cache_size"]:
        raise ValueError("cache指紋不一致")
    with np.load(path, allow_pickle=False) as archive:
        a = {k: archive[k] for k in ("now", "line", "bid", "ask", "valid")}
    begin, end, cutoff, force = bounds(entry["session"])
    indices = np.flatnonzero(np.isfinite(a["now"]) & (a["now"] >= begin) & (a["now"] < end))
    times = a["now"][indices]
    keep = np.r_[True, times[1:] >= np.maximum.accumulate(times[:-1])]
    backwards = int(np.count_nonzero(~keep))
    indices = indices[keep]
    indices = indices[a["valid"][indices]]
    q = {k: a[k][indices] for k in ("now", "line", "bid", "ask")}
    clocks = np.r_[begin, q["now"]]
    gaps = [(float(l), float(r)) for l, r in zip(clocks[:-1], clocks[1:]) if r - l > 300]
    return {**q, "at": {int(line): i for i, line in enumerate(q["line"])}, "gaps": gaps,
            "backwards": backwards, "bounds": (begin, end, cutoff, force),
            "maximum_gap": float(np.max(np.diff(clocks))) if len(q["now"]) else 0.}


# ----------------------------------------
# 保存片から独立に会計する。所有の単位は候補・場・建玉IDの組。

def audit_session(detail: dict, q: dict, audit: Any) -> dict:
    """一候補・一場の約定、注文、取引、品質を照合する。

    引数: detail (dict) は作業正本、q (dict) は正常板、audit (Any) は比較先。
    返り値: dict は独立場別会計と照合済み取引。要求生成は再実装しない。
    """
    cid, session = detail["候補ID"], detail["場"]
    prefix = cid + "/" + session
    fills, info = detail["約定"], detail["品質"]
    orders = {v["注文ID"]: v for v in detail["注文"]}
    signals = {v["イベントID"]: v for v in detail["入口取扱"]}
    trades = {v["建玉ID"]: v for v in detail["取引"]}
    for name, keyed, raw in (("注文", orders, detail["注文"]), ("入口", signals, detail["入口取扱"]), ("取引", trades, detail["取引"])):
        audit.check(prefix + ":" + name + "一意", len(keyed), len(raw))
    begin, end, cutoff, force = q["bounds"]
    positions, completed, ids = {}, [], set()
    cash, fees, previous = Decimal(0), Decimal(0), None
    for fill in fills:
        name = prefix + "/" + fill["id"]
        opening = fill["type"].endswith("N")
        side = 1 if fill["type"].startswith("Long") else -1
        clock, line = float(fill["price_clock"]), int(fill["source_line"])
        index = q["at"][line]
        checks = {"手法所有": (fill["method_id"], cid), "ID一意": (fill["id"] not in ids, True),
                  "非後退": (previous is None or (clock, line) >= previous, True),
                  "場内": (begin <= clock < end, True), "原行時計": (q["now"][index], clock),
                  "ISO時計": (datetime.fromisoformat(fill["timestamp"]).timestamp(), clock),
                  "1秒後最初": (index, int(np.searchsorted(q["now"], fill["request_clock"] + 1, side="left"))),
                  "BBO": (fill["price"], q["ask"][index] if (opening and side == 1) or (not opening and side == -1) else q["bid"][index]),
                  "数量": (fill["qty"], 1), "費用": (fill["fee_yen"], 11)}
        for key, values in checks.items():
            audit.check(name + ":" + key, *values)
        ids.add(fill["id"])
        previous = clock, line
        order = orders[fill["order_id"]]
        for key, actual, expected in (("注文場", order["場"], session), ("注文入口", order["入口イベントID"], fill["entry_event_id"]),
                                      ("入口存在", fill["entry_event_id"] in signals, True), ("注文状態", order["状態"], "約定")):
            audit.check(name + ":" + key, actual, expected)
        for column, field in (("要求時計秒", "request_clock"), ("要求原板行", "request_source_line"),
                              ("約定時計秒", "price_clock"), ("約定原板行", "source_line"), ("約定価格", "price")):
            audit.check(name + ":注文:" + column, order[column], fill[field])
        price, fee = Decimal(str(fill["price"])), Decimal(str(fill["fee_yen"]))
        cash -= fee
        fees += fee
        identity = fill["position_id"]
        if opening:
            audit.check(name + ":一建玉", sum(v["qty"] for v in positions.values()), 0)
            audit.check(name + ":新規期限", clock <= fill["request_clock"] + 30 and clock < cutoff, True)
            positions[identity] = {"qty": 1, "side": side, "price": price, "fill": fill}
            continue
        position = positions[identity]
        entry = position["fill"]
        audit.check(name + ":返済数量", position["qty"], 1)
        audit.check(name + ":返済方向", position["side"], side)
        audit.check(name + ":返済入口所有", fill["entry_event_id"], entry["entry_event_id"])
        gross = side * (price - position["price"]) * 10
        cash += gross
        net = gross - Decimal(str(entry["fee_yen"])) - fee
        trade = trades[identity]
        expected = {"手法": cid, "入口イベントID": fill["entry_event_id"], "枚数": 1,
                    "新規価格": position["price"], "返済価格": price, "粗損益円": gross, "手数料円": 22,
                    "基準純損益円": net, "利確価格": position["price"] + side * 250,
                    "保護価格": position["price"] - side * 125, "新規時計秒": entry["price_clock"],
                    "新規原板行": entry["source_line"], "返済時計秒": clock, "返済原板行": line}
        for key, value in expected.items():
            audit.check(name + ":取引:" + key, trade[key], value)
        for slip in (0, 5, 10):
            audit.check(name + f":追加{slip}", trade[f"追加滑り{slip}pt純損益円"], net - 20 * slip)
        entered = float(entry["price_clock"])
        waiting_gap = any(entry["request_clock"] < r <= entered for l, r in q["gaps"])
        held_gap = any(entered < r <= clock for l, r in q["gaps"])
        for key, value in (("新規待機空白", waiting_gap), ("保有経路空白", held_gap), ("観測経路注意", waiting_gap or held_gap)):
            audit.check(name + ":" + key, trade[key], value)
        completed.append({"entry": entered, "exit": clock, "net": net, "attention": waiting_gap or held_gap})
        position["qty"] = 0
    held_gaps = sum(any(float(p["fill"]["price_clock"]) < r and (p["qty"] or any(t["entry"] == p["fill"]["price_clock"] and t["exit"] >= r for t in completed)) for p in positions.values()) for l, r in q["gaps"])
    waiting_gaps = sum(float(o["要求時計秒"]) < r and (float(o["約定時計秒"]) if o["約定時計秒"] is not None else min(float(o["要求時計秒"]) + 30, cutoff, force)) > l for l, r in q["gaps"] for o in orders.values() if o["区分"] == "新規")
    unresolved = sum(p["qty"] for p in positions.values())
    tail = not len(q["now"]) or bool(q["now"][-1] < force)
    flagged = [t for t in completed if t["attention"]]
    attention = bool(unresolved or flagged or held_gaps or waiting_gaps or tail)
    states = Counter(s["取扱"] for s in signals.values())
    expected = {"候補要求数": len(signals), "新規約定数": sum(f["type"].endswith("N") for f in fills),
                "完結取引数": len(completed), "終了建玉": unresolved, "終了返済待機": sum(o["状態"] == "待機" for o in orders.values()),
                "観測現金増減円": cash, "観測完結取引純損益円": sum((t["net"] for t in completed), Decimal(0)),
                "手数料円": fees, "観測経路注意取引数": len(flagged),
                "経路注意取引純損益円": sum((t["net"] for t in flagged), Decimal(0)),
                "場内正常板空白区間数": len(q["gaps"]), "保有中空白区間数": held_gaps, "新規待機中空白区間数": waiting_gaps,
                "正常板数": len(q["now"]), "正常板最終時計秒": float(q["now"][-1]) if len(q["now"]) else None,
                "最長正常板間隔秒": q["maximum_gap"], "時計後退除外数": q["backwards"],
                "EOF期限未達": tail, "期限まで300秒超尾部": not len(q["now"]) or bool(force - q["now"][-1] > 300),
                "観測経路注意": attention, "確定対象純損益円": None if attention else cash,
                "新規取消数": sum(o["区分"] == "新規" and o["状態"] not in ("約定", "待機") for o in orders.values()),
                "建玉中抑止数": states["建玉中抑止"], "注文待機中抑止数": states["注文待機中抑止"],
                "両方向見送り数": states["同時両方向見送り"], "確認遅延不可数": states["足確定確認遅延30秒超"]}
    for key, value in expected.items():
        audit.check(prefix + ":品質:" + key, info[key], value)
    audit.check(prefix + ":取引全件", len(completed), len(trades))
    return {"候補ID": cid, "場": session, "期間": info["期間"], **expected, "約定片数": len(fills),
            "場時間分": (end - begin) / 60, "取引": detail["取引"]}


def aggregate(rows: list[dict]) -> dict:
    """独立会計の期間別活動と費用感度を集約する。

    引数: rows (list[dict]) は一候補・一期間の場別値。
    返り値: dict は運用列の検算値。
    """
    trades = [t for row in rows for t in row["取引"]]
    active = {t["場"] for t in trades}
    daily = defaultdict(Decimal)
    for t in trades:
        daily[t["場"]] += Decimal(str(t["基準純損益円"]))
    positive = sum(max(Decimal(0), v) for v in daily.values())
    attention = sum(r["観測経路注意"] for r in rows)
    held = sum(Decimal(str(t["保有分"])) for t in trades)
    result = {"入力場数": len(rows), "完結取引数": len(trades), "活動場数": len(active),
              "活動開始日数": len({s[:10] for s in active}), "無取引場数": len(rows) - len(active),
              "買い取引数": sum(t["方向"] == "買い" for t in trades), "売り取引数": sum(t["方向"] == "売り" for t in trades),
              "黒字取引数": sum(Decimal(str(t["基準純損益円"])) > 0 for t in trades), "保有分合計": held,
              "保有時間率_観測": held / sum(Decimal(str(r["場時間分"])) for r in rows) if rows else None,
              "赤字場数": sum(v < 0 for v in daily.values()), "品質注意場数": attention,
              "未解消場数": sum(r["終了建玉"] for r in rows), "EOF期限未達場数": sum(r["EOF期限未達"] for r in rows),
              "黒字場利益の最大場寄与": max((max(Decimal(0), v) for v in daily.values()), default=Decimal(0)) / positive if positive else None}
    for slip in (0, 5, 10):
        net = sum(Decimal(str(t["基準純損益円"])) - 20 * slip for t in trades)
        result.update({f"追加{slip}pt純損益円": net, f"追加{slip}pt平均円": net / len(trades) if trades else None,
                       f"追加{slip}pt確定対象円": None if attention else net})
    return result


# ----------------------------------------
# 正式資源とCSVの所有・相対パス、旧00007の84取引を照合する。

def artifacts(base: Path, details: dict, fixed: list[str], entries: dict, audit: Any) -> dict:
    """固定候補の資源とJSONL・CSVを作業正本へ照合する。

    引数: base (Path) は成果物先、details/entries (dict) は正本と台帳、
    fixed (list[str]) は固定ID、audit (Any) は比較先。
    返り値: dict は資源数・片数・取引数・指紋。
    """
    catalog = read(base / "一覧.resources.json")
    resources = catalog["resources"]
    audit.check(str(base) + ":相対基準", catalog["path_base"], "catalog")
    audit.check(str(base) + ":資源集合", {(r["method_id"], r["session"]) for r in resources}, {k for k in details if k[0] in fixed})
    audit.check(str(base) + ":資源ID一意", len({r["id"] for r in resources}), len(resources))
    total, fingerprints = 0, []
    for r in resources:
        cid, session = r["method_id"], r["session"]
        relative = Path(r["pnl_path"])
        path = (base / relative).resolve()
        audit.check(cid + session + ":相対約定", not relative.is_absolute() and path.is_relative_to(base.resolve()), True)
        audit.check(cid + session + ":相対市場", not Path(r["market_path"]).is_absolute() and r["market_path"] == entries[session]["source_path"], True)
        for key, value in (("entry_method_id", cid), ("point_value", 10), ("pnl_basis", "net"), ("pnl_format", "trades"), ("product", "NK225micro")):
            audit.check(cid + session + ":" + key, r[key], value)
        fills = [json.loads(v) for v in path.read_text(encoding="utf-8").splitlines() if v.strip()]
        audit.check(cid + session + ":JSONL", fills, details[(cid, session)]["約定"])
        audit.check(cid + session + ":全片所有", all(f["method_id"] == cid for f in fills), True)
        total += len(fills)
        fingerprints.append({"資源ID": r["id"], "SHA256": sha(path)})
    actual_trades, actual_orders = table(base / "固定候補_取引.csv"), table(base / "固定候補_注文.csv")
    trades = {(v["手法"], v["場"], v["建玉ID"]): v for v in actual_trades}
    orders = {(v["候補ID"], v["場"], v["注文ID"]): v for v in actual_orders}
    audit.check(str(base) + ":取引CSV一意", len(trades), len(actual_trades))
    audit.check(str(base) + ":注文CSV一意", len(orders), len(actual_orders))
    counts = Counter()
    for (cid, session), d in details.items():
        if cid not in fixed:
            continue
        for kind, source, index, id_column in (("取引", d["取引"], trades, "建玉ID"), ("注文", d["注文"], orders, "注文ID")):
            for expected in source:
                counts[kind] += 1
                actual = index[(cid, session, expected[id_column])]
                for key, value in expected.items():
                    audit.check(cid + session + ":CSV:" + kind + key, actual[key], value)
    audit.check(str(base) + ":CSV取引全行", len(actual_trades), counts["取引"])
    audit.check(str(base) + ":CSV注文全行", len(actual_orders), counts["注文"])
    return {"資源数": len(resources), "約定片数": total, "取引数": counts["取引"], "注文数": counts["注文"],
            "一覧SHA256": sha(base / "一覧.resources.json"), "約定SHA256": fingerprints}


def old_control(details: dict, cid: str, audit: Any) -> dict:
    """旧対照の64場84取引と全約定を00007へ接合する。

    引数: details (dict) は探索正本、cid (str) は対照ID、audit (Any) は比較先。
    返り値: dict は比較件数。手法名と期間の再分類だけ除く。
    """
    count = fills = 0
    for base in (OLD, OLD / "追加確認"):
        previous = table(base / "取引集計.csv")
        for r in read(base / "一覧.resources.json")["resources"]:
            session = r["session"]
            current = details[(cid, session)]
            old_fills = [json.loads(v) for v in (base / r["pnl_path"]).read_text(encoding="utf-8").splitlines() if v.strip()]
            audit.check(session + ":旧対照片数", len(current["約定"]), len(old_fills))
            for now, old in zip(current["約定"], old_fills):
                for key, value in old.items():
                    if key != "method_id":
                        audit.check(session + ":旧対照約定:" + key, now[key], value)
                fills += 1
            old_trades = {v["建玉ID"]: v for v in previous if v["場"] == session}
            audit.check(session + ":旧対照取引数", len(current["取引"]), len(old_trades))
            for trade in current["取引"]:
                for key, value in old_trades[trade["建玉ID"]].items():
                    if key not in ("手法", "期間"):
                        audit.check(session + ":旧対照取引:" + key, trade[key], value)
                count += 1
    audit.check("旧対照84取引", count, 84)
    return {"比較場数": 64, "完結取引数": count, "約定片数": fills, "比較除外": "手法名、旧追加4場を条件選択へ含めた期間表記。"}


def phase_audit(phase: str, entries: dict, fixed: list[str], allow_future: bool, audit: Any) -> tuple[dict, dict]:
    """許可された段階だけ全約定会計と固定成果物を照合する。

    引数: phase (str) は探索/後続、entries (dict) は台帳、fixed (list[str]) は固定ID、
    allow_future (bool) は新1許可、audit (Any) は比較先。
    返り値: tuple[dict,dict] は段階監査と作業正本。
    """
    if phase == "後続" and not allow_future:
        raise ValueError("新1場読取の許可がない")
    path = WORK / (phase + "_運用詳細.jsonl.gz")
    details, cached, rows = {}, {}, []
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            d = json.loads(line)
            cid, session = d["候補ID"], d["場"]
            if (phase == "探索" and session >= "2026-11-04") or (phase == "後続" and (session != "2026-11-04_Day" or cid not in fixed)):
                raise ValueError("固定した読取境界を越えている")
            if (cid, session) in details:
                raise ValueError("候補・場が重複")
            if session not in cached:
                cached[session] = quotes(entries[session], allow_future)
            details[(cid, session)] = d
            rows.append(audit_session(d, cached[session], audit))
    result = read(STUDY / (phase + "結果.json"))
    periods = ("学習", "条件選択") if phase == "探索" else ("後続検査",)
    aggregates = []
    for candidate in result["結果"]:
        for period in periods:
            cid = candidate["候補ID"]
            expected = aggregate([r for r in rows if r["候補ID"] == cid and r["期間"] == period])
            for key, value in expected.items():
                audit.check(phase + cid + period + ":集計:" + key, candidate[period]["運用"][key], value)
            aggregates.append({"候補ID": cid, "期間": period, **expected})
    output = STUDY if phase == "探索" else STUDY / "追加確認"
    files = artifacts(output, details, fixed, entries, audit)
    return {"段階": phase, "候補数": len(result["結果"]), "候補場数": len(rows), "運用詳細SHA256": sha(path),
            "資源": files, "期間別": aggregates, "固定候補場別": [{k: v for k, v in r.items() if k != "取引"} for r in rows if r["候補ID"] in fixed],
            "成果物ルート": str(output)}, details


# ----------------------------------------
# Viewerは後続の固定候補だけ、図は有取引候補の1枚まで。

def viewer(phases: list[dict], api: str, audit: Any) -> dict:
    """後続の固定候補をAPI数値・帰属・指紋・最大1枚の画像で照合する。

    引数: phases (list[dict]) は会計結果、api (str) は接続先、audit (Any) は比較先。
    返り値: dict は設定・API・画像の記録。
    """
    helper_path = ROOT / "scripts/複合検証/Viewer照合.py"
    helper = load(helper_path, "外部研究表示補助")
    phase = next(p for p in phases if p["段階"] == "後続")
    base = Path(phase["成果物ルート"])
    resources = {(r["method_id"], r["session"]): r for r in read(base / "一覧.resources.json")["resources"]}
    raw, _ = helper.fetch(api + "/api/resources?" + helper.urlencode({"catalog_path": (base / "一覧.resources.json").relative_to(ROOT).as_posix()}))
    audit.check("Viewer:資源集合", {v["id"] for v in json.loads(raw)["resources"]}, {v["id"] for v in resources.values()})
    checked, image_saved = [], False
    for row in phase["固定候補場別"]:
        adapted = {"銘柄": "NK225", "場": row["場"], "手法": row["候補ID"],
                   "純損益円": float(row["観測現金増減円"]), "取引数": row["完結取引数"]}
        image = bool(row["完結取引数"] and not image_saved)
        item = helper.check_one(api, base, adapted, resources[(row["候補ID"], row["場"])], "固定新候補の後続例", image)
        item.update(観測経路注意=row["観測経路注意"], 確定対象純損益円=row["確定対象純損益円"])
        checked.append(item)
        image_saved |= image
    with urlopen(api + "/api/info", timeout=10) as response:
        info = json.load(response)
    binary = ROOT / "work/viewer/session-trade-viewer.exe"
    supplied = ROOT.parent / "SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"
    return {"確認日時": datetime.now(HELPER.JST).isoformat(), "接続先": api, "API情報": info,
            "設定": "work/viewer/conf/viewer.toml", "起動": {"WindowStyle": "Hidden", "実行コピー": binary.relative_to(ROOT).as_posix(),
                    "実行コピーSHA256": sha(binary), "指定配布版SHA256": sha(supplied)},
            "パス解決": "market_pathは設定の市場data_root基準。pnl_pathはpath_base=catalogで各一覧の親基準。",
            "読込例": "/?catalog=" + (base / "一覧.resources.json").relative_to(ROOT).as_posix() + "&resource=" + checked[0]["資源ID"] + "&interval=5&price=last",
            "表示コードSHA256": sha(helper_path), "照合": checked,
            "意味": "micro1枚代理・片道11円・追加滑り0ptの観測会計。後続1場を安定性の証拠としない。"}


def run(include_future: bool, api: str | None) -> dict:
    """許可された運用会計と任意のViewerを照合して正式監査を保存する。

    引数: include_future (bool) は新1許可、api (str|None) はViewer接続先。
    返り値: dict は明示合否・照合数・独立集計。原板と旧コードは変更しない。
    """
    audit = Audit()
    locked = read(STUDY / "選定固定.json")
    fixed = locked["選定"]["固定ID"]
    for path, expected in locked["ファイルSHA256"].items():
        audit.check("固定SHA:" + path, sha(ROOT / path), expected)
    audit.check("探索結果固定SHA", sha(STUDY / "探索結果.json"), locked["探索結果SHA256"])
    entries = {e["session"]: e for e in read(STUDY / "入力台帳.json")["entries"]}
    first, details = phase_audit("探索", entries, fixed, include_future, audit)
    old = old_control(details, read(STUDY / "条件.json")["対照ID"], audit)
    phases = [first]
    if include_future:
        second, _ = phase_audit("後続", entries, fixed, True, audit)
        phases.append(second)
    view = viewer(phases, api, audit) if api and include_future else None
    if view:
        (STUDY / "Viewer照合.json").write_text(json.dumps(view, ensure_ascii=False, indent=2, allow_nan=False, default=float) + "\n", encoding="utf-8")
    result = {"確認日時": datetime.now(HELPER.JST).isoformat(), "全件一致": not audit.errors,
              "照合項目数": audit.count, "不一致数": len(audit.errors), "不一致": audit.errors,
              "新1読取許可": include_future, "コードSHA256": sha(Path(__file__)),
              "会計補助コードSHA256": sha(ROOT / "scripts/広域研究/運用独立監査.py"),
              "選定固定SHA256": sha(STUDY / "選定固定.json"), "旧対照一致": old, "段階別": phases,
              "Viewer記録": "Viewer照合.json" if view else None,
              "方法": "運用・指標・入口・選定コードをimportせず、全33候補旧64場の約定からDecimal会計・正常BBO原行を再検算。新1は固定IDだけ。",
              "限界": "全要求生成・全逐次遷移の独立再実装ではない。保存片・注文・取引・品質・期間運用の検算。注意場を含む全体確定額はNoneを保持。"}
    (STUDY / "運用独立監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"全件一致": result["全件一致"], "照合項目数": audit.count, "不一致数": len(audit.errors),
                      "不一致": audit.errors[:10], "旧対照": old}, ensure_ascii=False, default=float))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="00008運用・Viewer独立監査")
    parser.add_argument("--include-future", action="store_true")
    parser.add_argument("--api-base")
    args = parser.parse_args()
    outcome = run(args.include_future, args.api_base.rstrip("/") if args.api_base else None)
    if not outcome["全件一致"]:
        raise SystemExit(1)
