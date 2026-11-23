"""81の独立監査を、市場に依存しない自作gzipと保存会計で確認する。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def load(name: str) -> object:
    """
    機能: 同フォルダの監査コードを独立名で読み込む。
    引数: name (str) はPythonファイル名。
    返り値: object は市場やAPIを実行しないモジュール。
    """
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location("人工81_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(folder: Path, side: int = 1, scenario: str = "成功") -> tuple[dict, dict]:
    """
    機能: 100枚の全量保護又は75/25分割の期待会計を手計算で作る。
    引数: folder (Path) は人工根、side (int) は方向、scenario (str) は成功/悪化/pending。
    返り値: tuple[dict,dict] は入力台帳一場と8会計。
    """
    session = "2026-09-21_Day"
    start = datetime(2026, 9, 21, 9, 15, tzinfo=timezone(timedelta(hours=9)))
    times = {i: (start + timedelta(seconds=(i - 1) * 2)).timestamp() for i in range(1, 8)}
    quote = {1: (9990, 10000), 2: (9990, 10000), 3: (10020, 10030), 4: (10020, 10030), 5: (10040, 10050), 6: (10000, 10010), 7: (10000, 10010)}
    if scenario in ("悪化", "pending"):
        for line in range(4, 8):
            quote[line] = (10010, 10020)
    if scenario == "pending":
        times[4] = times[3]
    if scenario not in ("成功", "悪化", "pending"):
        raise ValueError("人工シナリオ不明")
    if side < 0:
        quote = {i: (20000 - ask, 20000 - bid) for i, (bid, ask) in quote.items()}
    path = folder / "市場/NK225" / session / "book.jsonl.gz"
    path.parent.mkdir(parents=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for line, (bid, ask) in quote.items():
            row = {"Symbol": "人工限月", "CurrentPriceTime": datetime.fromtimestamp(times[line], start.tzinfo).isoformat(), "CurrentPrice": (bid + ask) / 2}
            for level in range(1, 11):
                row[f"Buy{level}"] = {"Price": bid - 10 * (level - 1), "Qty": 10}
                row[f"Sell{level}"] = {"Price": ask + 10 * (level - 1), "Qty": 10}
            stream.write(json.dumps(row) + "\n")
    books = {}
    for delay in (0, 1):
        for mode in ("B0G0", "B0G1", "B1G0", "B1G1"):
            pid = mode + "玉"
            plans = [("entry", 100, 1, 2, False)]
            first_fill = 5 if scenario == "pending" and delay == 1 else 4
            if mode.endswith("G0"):
                plans += [("exit", 100, 3, first_fill, False)]
            elif scenario == "成功":
                plans += [("exit", 75, 3, 4, True), ("exit", 25, 6, 7, False)]
            else:
                plans += [("exit", 75, 3, first_fill, True), ("exit", 25, first_fill, first_fill + 1, False)]
            orders, trades, closed = [], [], []
            realized = 0
            for serial, (kind, quantity, requested, filled, harvest) in enumerate(plans, 1):
                bid, ask = quote[filled]
                price = (ask if side > 0 else bid) if kind == "entry" else (bid if side > 0 else ask)
                order = {"id": mode + f"注文{serial}", "kind": kind, "side": side, "quantity": quantity, "remaining": 0, "filled_quantity": quantity, "cancelled_quantity": 0, "request_line": requested, "request_index": requested - 1, "request_time": times[requested], "fill_line": filled, "fill_time": times[filled], "fill_price": price, "position_id": pid, "reference_id": mode + "候補", "status": "filled", "reason": "人工", "harvest": harvest, "harvest_needed": 75 if harvest else 0, "harvest_feasible": harvest}
                orders.append(order)
                trades.append({"id": mode + f"約定{serial}", "timestamp": datetime.fromtimestamp(times[filled], start.tzinfo).isoformat(), "type": ("Long" if side > 0 else "Short") + ("N" if kind == "entry" else "R"), "position_id": pid, "price": price, "qty": quantity, "fee_yen": 61 * quantity, "method_id": mode, "source_line": filled})
                if kind == "exit":
                    gross = side * (price - 10000) * quantity * 10
                    net = gross - 122 * quantity
                    realized += net
                    closed.append({"position_id": pid, "side": side, "quantity": quantity, "entry_price": 10000, "exit_price": price, "entry_time": times[2], "exit_time": times[filled], "exit_line": filled, "gross_pnl": gross, "commission": 22 * quantity, "slippage": 100 * quantity, "pnl0": gross - 22 * quantity, "pnl5": net, "pnl10": gross - 222 * quantity, "flag": True, "reason": "人工"})
            flag_mark = quote[3][0 if side > 0 else 1]
            lot = {"id": pid, "reference_id": mode + "候補", "quantity": 0, "initial_quantity": 100, "closed_quantity": 100, "side": side, "net_pnl": realized, "flag": True, "flag_index": 2, "flag_time": times[3], "flag_mark": flag_mark, "flag_net_per_unit": 78, "whole_flag": True, "whole_flag_index": 2, "whole_flag_line": 3, "whole_flag_time": times[3], "entry_atr": 40, "d": 40}
            partial = mode.endswith("G1")
            lot.update({"harvest_order_id": orders[1]["id"] if partial else "", "harvest_target": 75 if partial else 0, "harvest_filled": 75 if partial else 0, "harvest_needed": 75 if partial else 0, "harvest_feasible": partial, "harvest_at": times[3] if partial else None, "harvest_done_at": times[first_fill] if partial else None, "cash_floor_active": partial, "cash_floor": (0 if scenario == "成功" else 30) if partial else None, "cash_floor_at": times[first_fill] if partial else None, "funding_failed": partial and scenario != "成功"})
            metric = {"equity_peak_yen": 12800 if scenario == "成功" and mode.endswith("G1") else 7800, "min_equity_yen": -22200, "max_drawdown_yen": 22200, "worst_floating_yen": -22200,
                "cash_yen": realized, "net_pnl_yen": realized, "gross_pnl_yen": realized + 12200, "total_cost_yen": 12200, "entry_quantity": 100, "exit_quantity": 100, "commission_yen": 2200, "slippage_yen": 10000, "open_quantity": 0, "closed_lots": 1, "winning_lots": int(realized > 0), "losing_lots": int(realized < 0), "flat_lots": 0, "profit_flags": 1, "flag_after_loss_pieces": sum(c["pnl5"] < 0 for c in closed)}
            metric.update({"whole_profit_flags": 1, "whole_flag_after_loss_lots": int(realized < 0), "harvest_orders": int(partial), "harvest_quantity": 75 if partial else 0, "harvest_filled_quantity": 75 if partial else 0, "harvest_done_lots": int(partial), "cash_floor_activated_lots": int(partial), "funding_failure_lots": int(partial and scenario != "成功")})
            first_grid = times[1]
            decisions = [{"at": first_grid + n * 900, "action": "新規要求" if n == 0 else "待ち"} for n in range(25)]
            books[f"{mode}_D{delay}"] = {"mode": mode, "session": session, "fill_delay_seconds": delay, "side_cap": 100, "orders": orders, "trades": trades, "closed": closed, "lots": [lot], "metrics": metric, "decisions": decisions, "unresolved": False, "warnings": []}
    entry = {"id": session, "contract": "人工限月", "files": {"NK225_book": {"path": path.relative_to(folder / "市場").as_posix(), "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}}
    return entry, {"session": session, "books": books, "grid_decisions": [], "quality": {}}


def raw_check(module: object, folder: Path, entry: dict, result: dict) -> dict:
    """
    機能: 自作一場を実際のgzip読取とmode正規化へ通す。
    引数: module (object)、folder (Path)、entry/result (dict) は人工入力。
    返り値: dict は原板独立監査の結果。売買再生はしない。
    """
    saved = deepcopy(result)
    saved.pop("quality", None)
    results = folder / "保存"
    results.mkdir(exist_ok=True)
    (results / f"{entry['id']}.json").write_text(json.dumps(saved), encoding="utf-8")
    return module.inspect_one((str(results), str(folder / "市場"), entry))


def pending_end(folder: Path, side: int) -> tuple[dict, dict]:
    """
    機能: 初回正益で返済を要求した直後に原板が終わる人工を作る。
    引数: folder (Path)、side (int) は人工根と売買方向。
    返り値: tuple[dict,dict] は未約定利確を確定益にしない期待値。
    """
    entry, result = fixture(folder, side)
    info = entry["files"]["NK225_book"]
    path = folder / "市場" / info["path"]
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        lines = list(stream)[:3]
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        stream.writelines(lines)
    info.update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    for key, book in result["books"].items():
        partial = book["mode"].endswith("G1")
        book["orders"] = book["orders"][:2]
        order = book["orders"][1]
        order.update(status="pending", remaining=order["quantity"], filled_quantity=0, fill_time=None, fill_price=None, fill_line=0)
        book["trades"] = book["trades"][:1]
        book["closed"] = []
        book["unresolved"] = True
        lot = book["lots"][0]
        lot.update(quantity=100, closed_quantity=0, net_pnl=0, harvest_filled=0, harvest_done_at=None, cash_floor_active=False, cash_floor=None, cash_floor_at=None, funding_failed=False)
        metric = book["metrics"]
        metric.update(equity_peak_yen=7800, cash_yen=-6100, net_pnl_yen=0, gross_pnl_yen=0, total_cost_yen=6100, exit_quantity=0, commission_yen=1100, slippage_yen=5000, open_quantity=100, closed_lots=0, winning_lots=0, losing_lots=0, flag_after_loss_pieces=0, whole_flag_after_loss_lots=0, harvest_filled_quantity=0, harvest_done_lots=0, cash_floor_activated_lots=0, funding_failure_lots=0)
        assert metric["harvest_quantity"] == (75 if partial else 0)
    return entry, result


def viewer_fake(module: object, folder: Path, book: dict) -> list[dict]:
    """
    機能: 実APIなしで表示監査の旧Audit結合と数値差・通信分離を確認する。
    引数: module (object)、folder (Path)、book (dict) は表示監査と人工保存値。
    返り値: list[dict] は正常・数値破損・通信失敗の3判定。
    """
    resource = {"id": "人工", "pnl_path": str(folder / "約定.jsonl"), "market_path": str(folder / "原板.gz"), "point_value": 10, "product": "NK225micro"}
    catalog = folder / "一覧.json"
    net = book["metrics"]["net_pnl_yen"]
    events = []
    for number, trade in enumerate(book["trades"], 1):
        side = 1 if trade["type"].startswith("Long") else -1
        delta = -61 * trade["qty"]
        if trade["type"].endswith("R"):
            delta += side * (trade["price"] - 10000) * trade["qty"] * 10
        events.append({"timestamp_ms": datetime.fromisoformat(trade["timestamp"]).timestamp() * 1000, "sequence": number, "type": trade["type"], "qty": trade["qty"], "price": trade["price"], "position_id": trade["position_id"], "method_id": trade["method_id"], "realized_delta_yen": delta})
    data = {"resource": resource, "files": {"pnl": resource["pnl_path"], "market": resource["market_path"], "catalog": str(catalog)}, "summary": {"long_qty": 0, "short_qty": 0, "realized_pnl_yen": net, "unrealized_pnl_yen": 0}, "state_columns": ["long_qty", "short_qty", "realized_pnl_yen", "unrealized_pnl_yen"], "states": [[0, 0, net, 0]], "events": events, "quality": {"warnings": []}}
    original = module.BASE.fetch_json
    results = []
    try:
        for broken in (False, True):
            reply = deepcopy(data)
            if broken:
                reply["summary"]["realized_pnl_yen"] += 1
            raw = json.dumps(reply).encode()
            module.BASE.fetch_json = lambda *args, value=reply, body=raw: (value, body, {"x-chart-data-sha256": hashlib.sha256(body).hexdigest()})
            checked = module.check_one(("人工URL", resource, book["trades"], net, catalog))
            assert checked["完了"] and checked["APIエラー"] is None
            assert (checked["不一致数"] > 0) == broken
            results.append({"表示数値破損": broken, "照合": checked["照合項目数"], "差": checked["不一致数"]})
        def disconnected(*args) -> None:
            """
            機能: 通信例外を人工的に送出する。
            引数: args (tuple) は利用しない呼出し値。
            返り値: None。常にConnectionErrorを送出する。
            """
            raise ConnectionError("人工通信停止")
        module.BASE.fetch_json = disconnected
        checked = module.check_one(("人工URL", resource, book["trades"], net, catalog))
        assert not checked["完了"] and checked["APIエラー"] is not None
        results.append({"表示通信失敗": True, "完了": False})
    finally:
        module.BASE.fetch_json = original
    return results


def main() -> None:
    """
    機能: 方向・全量/部分保護・遅延と破損拒否を人工で確認する。
    引数: なし。
    返り値: None。差分があればassertで終了し、小型要約だけ表示する。
    """
    raw = load("原板監査.py")
    summary = load("集計.py")
    viewer = load("表示監査.py")
    summaries = []
    with tempfile.TemporaryDirectory(prefix="81独立監査人工_", dir=ROOT / "work") as temp:
        for side in (1, -1):
            folder = Path(temp) / str(side)
            entry, result = fixture(folder, side)
            good = raw_check(raw, folder, entry, result)
            assert good["不一致数"] == 0, good["不一致"]
            summaries.append({"方向": side, "照合": good["照合項目数"], "差": 0})
            for key, book in result["books"].items():
                checked = summary.load_base().cash_check(book)
                assert checked["現金円"] == (7800 if book["mode"].endswith("G0") else 2800)
            summaries.append({"8会計の旧cash_check結合": True, "方向": side})
            summaries += viewer_fake(viewer, folder, result["books"]["B0G1_D0"])
            # ----------------------------------------
            # 保存値や要求を変えた場合、独立期待値との不一致を必ず残します。
            mutations = (
                ("fee", lambda b: b["trades"][0].update(fee_yen=6099)),
                ("flag", lambda b: b["lots"][0].update(flag_index=3, flag_time=b["lots"][0]["flag_time"] + 2)),
                ("whole", lambda b: b["lots"][0].update(whole_flag=False)),
                ("dd", lambda b: b["metrics"].update(max_drawdown_yen=22201)),
                ("late", lambda b: b["orders"][-1].update(request_line=7, request_index=6, request_time=b["orders"][-1]["request_time"] + 2)),
                ("budget", lambda b: b["orders"][1].update(harvest_needed=74)),
                ("harvest_metadata", lambda b: b["lots"][0].update(harvest_filled=0, harvest_target=1)),
                ("cash_metadata", lambda b: b["lots"][0].update(cash_floor_active=False, cash_floor=999, cash_floor_at=b["lots"][0]["flag_time"])),
                ("cash_metrics", lambda b: b["metrics"].update(harvest_orders=999, harvest_filled_quantity=0, cash_floor_activated_lots=0)),
            )
            for name, mutate in mutations:
                altered = deepcopy(result)
                mutate(altered["books"]["B0G1_D0"])
                bad = raw_check(raw, folder, entry, altered)
                assert bad["不一致数"] > 0, name
                summaries.append({"破損": name, "方向": side, "検出": bad["不一致数"]})
            for scenario in ("悪化", "pending"):
                case = Path(temp) / (str(side) + scenario)
                e, v = fixture(case, side, scenario)
                checked = raw_check(raw, case, e, v)
                assert checked["不一致数"] == 0, (scenario, checked["不一致"])
                summaries.append({"シナリオ": scenario, "方向": side, "照合": checked["照合項目数"], "差": 0})
            eof = Path(temp) / (str(side) + "終端未約定")
            e, v = pending_end(eof, side)
            checked = raw_check(raw, eof, e, v)
            assert checked["不一致数"] == 0, checked["不一致"]
            summaries.append({"シナリオ": "終端未約定", "方向": side, "照合": checked["照合項目数"], "差": 0})
            v["books"]["B0G1_D0"]["lots"][0].update(harvest_filled=75, harvest_done_at=v["books"]["B0G1_D0"]["lots"][0]["flag_time"], cash_floor_active=True, cash_floor=0)
            bad = raw_check(raw, eof, e, v)
            assert bad["不一致数"] > 0
            summaries.append({"破損": "未約定予算先取り", "方向": side, "検出": bad["不一致数"]})
    print(json.dumps({"成功": True, "系列": len(summaries), "人工": summaries, "本物原板": 0, "新再生": 0, "API": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
