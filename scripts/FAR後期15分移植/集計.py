"""80の実会計を独立に約定から照合し、小型の正式成果物へ集約する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import json
import math
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    """
    機能: UTF-8の小型JSONを新規保存する。
    引数: path (Path) は保存先、value (object) はJSON互換値。
    返り値: None。既存成果物は上書きしない。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def cash_check(book: dict) -> dict:
    """
    機能: 戦略の集計値を使わず約定所有・現金・費用・順序を照合する。
    引数: book (dict) は一場一案の実会計。
    返り値: dict は現金等の独立集計。不整合は例外にする。
    """
    positions = {}
    seen = set()
    cash = gross = costs = 0
    previous = 0
    closed = Counter()
    expected_pieces = Counter()
    expected_times = defaultdict(list)
    lot_net = Counter()
    entered = Counter()
    exited = Counter()
    expected_orders = Counter()
    expected_order_times = defaultdict(list)
    for trade in book["trades"]:
        ident = trade["id"]
        assert ident not in seen, f"約定重複:{ident}"
        seen.add(ident)
        at = datetime.fromisoformat(trade["timestamp"]).timestamp()
        assert at >= previous, "約定時計後退"
        previous = at
        qty, price, fee = trade["qty"], trade["price"], trade["fee_yen"]
        assert trade["type"] in ("LongN", "LongR", "ShortN", "ShortR")
        assert trade["method_id"] == book["mode"]
        assert type(qty) is int and qty > 0 and math.isfinite(price) and price > 0 and math.isfinite(fee) and fee == 61 * qty
        costs += fee
        cash -= fee
        pid = trade["position_id"]
        side = 1 if trade["type"].startswith("Long") else -1
        kind = "entry" if trade["type"].endswith("N") else "exit"
        order_key = (pid, kind, side, qty, price, trade["source_line"])
        expected_orders[order_key] += 1
        expected_order_times[order_key].append(at)
        if trade["type"].endswith("N"):
            assert pid not in positions, "新規所有ID重複"
            positions[pid] = {"side": side, "qty": qty, "entry": price}
            entered[pid] += qty
        else:
            assert pid in positions and positions[pid]["side"] == side, "返済所有不整合"
            p = positions[pid]
            assert p["qty"] >= qty, "過剰返済"
            pnl = side * (price - p["entry"]) * qty * 10
            cash += pnl
            gross += pnl
            p["qty"] -= qty
            closed[pid] += qty
            exited[pid] += qty
            lot_net[pid] += pnl - 122 * qty
            key = (pid, side, qty, p["entry"], price, trade["source_line"])
            expected_pieces[key] += 1
            expected_times[key].append(at)
        assert sum(p["qty"] for p in positions.values() if p["side"] == 1) <= 100
        assert sum(p["qty"] for p in positions.values() if p["side"] == -1) <= 100
    m = book["metrics"]
    assert abs(cash - m["cash_yen"]) < 1e-6
    assert abs(cash - m["net_pnl_yen"]) < 1e-6
    assert abs(gross - m["gross_pnl_yen"]) < 1e-6
    assert abs(costs - m["total_cost_yen"]) < 1e-6
    assert abs(sum(c["pnl5"] for c in book["closed"]) - cash) < 1e-6 or book["unresolved"]
    assert sum(p["qty"] for p in positions.values()) == m["open_quantity"]
    assert sum(entered.values()) == m["entry_quantity"]
    assert sum(exited.values()) == m["exit_quantity"]
    assert (sum(entered.values()) + sum(exited.values())) * 11 == m["commission_yen"]
    assert (sum(entered.values()) + sum(exited.values())) * 50 == m["slippage_yen"]
    actual_pieces = Counter()
    for piece in book["closed"]:
        n = piece["quantity"]
        g = piece["side"] * (piece["exit_price"] - piece["entry_price"]) * n * 10
        assert piece["gross_pnl"] == g
        assert piece["commission"] == 22 * n and piece["slippage"] == 100 * n
        assert piece["pnl0"] == g - 22 * n
        assert piece["pnl5"] == g - 122 * n
        assert piece["pnl10"] == g - 222 * n
        key = (piece["position_id"], piece["side"], n, piece["entry_price"], piece["exit_price"], piece["exit_line"])
        actual_pieces[key] += 1
        assert any(abs(piece["exit_time"] - at) < 1e-6 for at in expected_times[key]), "返済片時刻不一致"
    assert actual_pieces == expected_pieces, "返済片とViewer約定の不一致"
    lots = book["lots"]
    assert len(lots) == len(positions) and {p["id"] for p in lots} == set(positions), "全実玉の欠落又は重複"
    for p in lots:
        pid = p["id"]
        assert p["initial_quantity"] == entered[pid] and p["closed_quantity"] == exited[pid]
        assert p["quantity"] == positions[pid]["qty"]
        assert p["net_pnl"] == lot_net[pid]
    finished = [p for p in lots if p["quantity"] == 0]
    assert len(finished) == m["closed_lots"]
    assert sum(p["net_pnl"] > 0 for p in finished) == m["winning_lots"]
    assert sum(p["net_pnl"] < 0 for p in finished) == m["losing_lots"]
    assert sum(p["net_pnl"] == 0 for p in finished) == m["flat_lots"]
    assert sum(p["flag"] for p in lots) == m["profit_flags"]
    assert sum(c["flag"] and c["pnl5"] < 0 for c in book["closed"]) == m["flag_after_loss_pieces"]
    expected_grids = 25 if book["session"].endswith("Day") else 49
    assert len(book["decisions"]) == expected_grids
    grids = {d["at"] for d in book["decisions"]}
    actual_orders = Counter()
    order_ids = set()
    for order in book["orders"]:
        assert order["id"] not in order_ids
        order_ids.add(order["id"])
        assert order["kind"] in ("entry", "exit")
        assert order["quantity"] == order["remaining"] + order["filled_quantity"] + order["cancelled_quantity"]
        if order["kind"] == "entry":
            assert order["request_time"] in grids
        else:
            assert order["cancelled_quantity"] == 0, "受理返済の取消"
        if order["filled_quantity"]:
            assert order["fill_line"] > order["request_line"], "同原行の架空約定"
            assert order["fill_time"] >= order["request_time"] + book["fill_delay_seconds"]
            key = (order["position_id"], order["kind"], order["side"], order["filled_quantity"], order["fill_price"], order["fill_line"])
            actual_orders[key] += 1
            assert any(abs(order["fill_time"] - at) < 1e-6 for at in expected_order_times[key])
    assert actual_orders == expected_orders, "注文約定とViewer片の不一致"
    return {"約定数": len(seen), "現金円": cash, "粗損益円": gross, "費用円": costs, "残量": sum(p["qty"] for p in positions.values())}


def main() -> None:
    """
    機能: 固定66場の結果を照合しViewerと比較用JSONへ保存する。
    引数: --input/--out/--manifest (Path) は実行結果・新規出力・固定台帳。
    返り値: None。部分入力や重複、会計矛盾は明示停止する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    source = args.input.resolve()
    sessions = []
    for entry in manifest["sessions"]:
        path = source / (entry["id"] + ".json")
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["session"] == entry["id"]
        sessions.append(result)
    if args.out.exists():
        raise ValueError("正式出力先は新規である必要がある")
    args.out.mkdir(parents=True)
    modes = {}
    resources = []
    audits = []
    diagnostics = []
    per_session = []
    for mode in ("F0", "P1", "T1"):
        cum = peak = drawdown = 0
        day_values = defaultdict(float)
        actions = Counter()
        reasons = Counter()
        exit_net = Counter()
        flag_causes = Counter()
        sums = Counter()
        steps = []
        for result in sessions:
            book = result["books"][mode]
            assert book["mode"] == mode and book["session"] == result["session"]
            audit = cash_check(book)
            audits.append({"session": result["session"], "mode": mode, **audit})
            assert not book["unresolved"], f"未解決所有:{result['session']} {mode}"
            m = book["metrics"]
            drawdown = max(drawdown, m["max_drawdown_yen"], peak - (cum + m["min_equity_yen"]))
            peak = max(peak, cum + m["equity_peak_yen"])
            cum += m["net_pnl_yen"]
            day_values[result["session"].split("_")[0]] += m["net_pnl_yen"]
            for k in ("gross_pnl_yen", "total_cost_yen", "commission_yen", "slippage_yen", "entry_quantity", "exit_quantity", "closed_lots", "winning_lots", "losing_lots", "flat_lots", "profit_flags", "flag_after_loss_pieces", "request_before_floor_violations"):
                sums[k] += m[k]
            actions.update(d["action"] for d in book["decisions"])
            for c in book["closed"]:
                reasons[c["reason"]] += c["quantity"]
                exit_net[c["reason"]] += c["pnl5"]
                if c["flag"] and c["pnl5"] < 0:
                    flag_causes["赤字返済片"] += 1
                    if c["request_net_per_unit"] is not None and c["request_net_per_unit"] > 0:
                        flag_causes["要求時正益から約定悪化"] += 1
                    elif c["floor_jump"]:
                        flag_causes["利益床の飛越"] += 1
                    elif mode == "F0":
                        flag_causes["対照の利益保護なし"] += 1
                    else:
                        flag_causes["費用又は部分配分等"] += 1
            for lot in book["lots"]:
                if lot["quantity"] == 0:
                    diagnostics.append({"session": result["session"], "mode": mode, "lot": lot, "closed": [c for c in book["closed"] if c["position_id"] == lot["id"]]})
            name = f"約定/{mode}/{result['session']}.trades.jsonl"
            path = args.out / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                for trade in book["trades"]:
                    stream.write(json.dumps(trade, ensure_ascii=False, separators=(",", ":")) + "\n")
            resources.append({"id": f"80_{mode}_{result['session']}", "title": f"80 {mode} {result['session']}", "symbol": "NK225", "session": result["session"], "product": "NK225micro", "method_id": mode, "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": name, "market_path": f"NK225/{result['session']}/book.jsonl.gz"})
            step = {"session": result["session"], "mode": mode, **m, "累積損益円": cum, "入力品質": result["quality"], "警告": book["warnings"], "判断": dict(Counter(d["action"] for d in book["decisions"]))}
            steps.append(step)
            per_session.append(step)
        pnl_values = [s["net_pnl_yen"] for s in steps]
        flag_lots = [d["lot"] for d in diagnostics if d["mode"] == mode and d["lot"]["flag"]]
        modes[mode] = {**dict(sums), "費用後損益円": cum, "最大DD円": drawdown, "最大場内含み損円": min(s["worst_floating_yen"] for s in steps), "赤字場数": sum(v < 0 for v in pnl_values), "黒字場数": sum(v > 0 for v in pnl_values), "無取引又は同値場数": sum(v == 0 for v in pnl_values), "赤字日数": sum(v < 0 for v in day_values.values()), "日数": len(day_values), "最悪場円": min(pnl_values), "最大場円": max(pnl_values), "上位3場利益円": sum(sorted(pnl_values, reverse=True)[:3]), "判断": dict(actions), "返済理由別枚数": dict(reasons), "返済理由別損益円": dict(exit_net), "利益後赤字の内訳": dict(flag_causes), "利益観測済み完結玉": len(flag_lots), "利益観測後赤字玉": sum(p["net_pnl"] < 0 for p in flag_lots), "同約定費用0pt損益円": sum(c["pnl0"] for r in sessions for c in r["books"][mode]["closed"]), "同約定費用10pt損益円": sum(c["pnl10"] for r in sessions for c in r["books"][mode]["closed"]), "日別円": dict(day_values)}
        mode_lots = [d["lot"] for d in diagnostics if d["mode"] == mode]
        modes[mode]["残玉正益観測ありの損益円"] = sum(p["net_pnl"] for p in mode_lots if p["flag"])
        modes[mode]["残玉正益未観測の損益円"] = sum(p["net_pnl"] for p in mode_lots if not p["flag"])
        modes[mode]["残玉正益未観測の赤字玉"] = sum(p["net_pnl"] < 0 and not p["flag"] for p in mode_lots)
        modes[mode]["残玉正益観測後赤字の損益円"] = sum(p["net_pnl"] for p in mode_lots if p["flag"] and p["net_pnl"] < 0)
    decomposition = {}
    for mode in ("P1", "T1"):
        base = {(d["session"], d["lot"]["reference_id"]): d["lot"] for d in diagnostics if d["mode"] == "F0"}
        other = {(d["session"], d["lot"]["reference_id"]): d["lot"] for d in diagnostics if d["mode"] == mode}
        common = set(base) & set(other)
        exact = {key for key in common if all(base[key][k] == other[key][k] for k in ("side", "entry_price", "entry_time", "initial_quantity"))}
        decomposition[mode + "対F0"] = {"同じ参照ID": len(common), "同じ実新規": len(exact), "同参照だが新規時点又は枚数変更": len(common - exact), "F0だけ": len(set(base) - set(other)), "比較案だけ": len(set(other) - set(base)), "同じ実新規F0損益円": sum(base[k]["net_pnl"] for k in exact), "同じ実新規比較案損益円": sum(other[k]["net_pnl"] for k in exact), "同じ実新規出口差円": sum(other[k]["net_pnl"] - base[k]["net_pnl"] for k in exact), "F0だけ損益円": sum(base[k]["net_pnl"] for k in set(base) - set(other)), "比較案だけ損益円": sum(other[k]["net_pnl"] for k in set(other) - set(base))}
    by_method = {}
    for mode in ("F0", "P1", "T1"):
        groups = defaultdict(list)
        for d in diagnostics:
            if d["mode"] == mode:
                groups[d["lot"]["method"]].append(d["lot"])
        by_method[mode] = {key: {"完結玉": len(lots), "新規枚数": sum(p["initial_quantity"] for p in lots), "損益円": sum(p["net_pnl"] for p in lots), "費用円": sum(122 * p["initial_quantity"] for p in lots), "黒字玉": sum(p["net_pnl"] > 0 for p in lots), "利益観測玉": sum(p["flag"] for p in lots), "利益後赤字玉": sum(p["flag"] and p["net_pnl"] < 0 for p in lots)} for key, lots in groups.items()}
    write_json(args.out / "結果.json", {"場数": len(sessions), "全場既使用": True, "約定追加遅延秒": sessions[0]["books"]["F0"]["fill_delay_seconds"], "未計測欄の注意": "request_before_floor_violationsはエンジンに更新処理のない互換欄で、0を実測の証拠にしない。利益床と125pt到達後の返済要求は独立した原板照合の規範検査を参照。", "比較": modes, "入口と出口の分解": decomposition, "FAR時間帯別": by_method, "場別": per_session})
    write_json(args.out / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    write_json(args.out / "約定会計の独立照合.json", {"会計数": len(audits), "差分": 0, "項目": "所有ID・数量・順序・片費用・現金・返済取消なし・次原行・定時新規・25/49枠", "照合": audits})
    with (args.out / "取引診断.jsonl.gz").open("xb") as binary:
        with gzip.GzipFile(fileobj=binary, mode="wb", mtime=0) as stream:
            for value in diagnostics:
                stream.write((json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    print(json.dumps({"比較": {k: {name: value[name] for name in ("費用後損益円", "最大DD円", "赤字場数", "利益観測済み完結玉", "利益観測後赤字玉")} for k, value in modes.items()}, "会計照合": len(audits)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
