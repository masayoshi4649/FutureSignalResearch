"""元の連続再現の保存台帳を独立に再集計し、費用の二条件とViewer形式へ変換する。"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    """
    機能: 保存済みJSONを読み、数値を十進数として扱う。
    引数: path(Path)は入力。
    返り値: dictは保存値。
    """
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def serial(value):
    """
    機能: 厳密な半円会計をJSONの数値へ直列化する。
    引数: value(any)は十進数等。
    返り値: int又はfloatは整数又は0.5円を保持した数値。
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: dict) -> None:
    """
    機能: 新しいJSONを上書きせず保存する。
    引数: path(Path)は保存先、value(dict)は保存値。
    返り値: None。
    """
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False, default=serial)
        stream.write("\n")


def verify_book(book: dict) -> dict:
    """
    機能: 独立会計で全約定・所有・半円費用を再構築する。
    引数: book(dict)は一つの商品と手法の元台帳。
    返り値: dictは再計算した総額と残量。不一致は例外。
    """
    assert book["complete"] and book["finished"] and not book["failure"] and not book["pending"]
    config = book["config"]
    point = Decimal(str(config["point_value"]))
    fee = Decimal(str(config["fee_yen_per_side"]))
    slip = Decimal(str(config["slippage_points"])) * point
    holds, seen = {}, set()
    gross = fees = slips = Decimal(0)
    entry_qty = close_qty = 0
    for record in book["fills"]:
        fill = record["fill"]
        assert fill["Fee"] == 0 and fill["ExecutionID"] not in seen
        seen.add(fill["ExecutionID"])
        qty = fill["Quantity"]
        assert isinstance(qty, int) and qty > 0
        quote = record["quote"]
        assert quote["quote_ok"] and quote["bid"] > 0 and quote["ask"] > quote["bid"] and quote["source_line"] > 0
        assert fill["Price"] == (quote["ask"] if record["side"] == 1 else quote["bid"])
        assert record["fee_yen"] == fee * qty and record["slippage_yen"] == slip * qty
        fees += fee * qty
        slips += slip * qty
        if record["action"] == "new":
            assert fill["HoldID"] and fill["HoldID"] not in holds and not fill["Closed"]
            holds[fill["HoldID"]] = {"q": qty, "initial": qty, "closed": 0, "entry": fill["Price"], "side": record["side"],
                                     "quote": quote, "gross": Decimal(0), "net": Decimal(0)}
            entry_qty += qty
            assert record["gross_yen"] == 0 and not record["allocations"]
        else:
            assert record["action"] == "close"
            allocations = record["allocations"]
            assert sum(a["quantity"] for a in allocations) == qty
            targets = [(target["id"], target["quantity"]) for target in fill["Closed"]]
            allocated = [(allocation["hold_id"], allocation["quantity"]) for allocation in allocations]
            assert len({identity for identity, _ in targets}) == len(targets)
            assert len({identity for identity, _ in allocated}) == len(allocated)
            assert sorted(targets) == sorted(allocated)
            piece_gross = Decimal(0)
            for allocation in allocations:
                hold = holds[allocation["hold_id"]]
                q = allocation["quantity"]
                assert 0 < q <= hold["q"] and record["side"] == -hold["side"]
                amount = hold["side"] * (fill["Price"] - hold["entry"]) * point * q
                assert allocation["gross_yen"] == amount
                assert allocation["entry_fee_yen"] == allocation["exit_fee_yen"] == fee * q
                assert allocation["entry_slippage_yen"] == allocation["exit_slippage_yen"] == slip * q
                assert allocation["net_yen"] == amount - 2 * (fee + slip) * q
                hold["q"] -= q
                hold["closed"] += q
                hold["gross"] += amount
                hold["net"] += allocation["net_yen"]
                piece_gross += amount
            assert record["gross_yen"] == piece_gross
            gross += piece_gross
            close_qty += qty
        assert record["net_contribution_yen"] == record["gross_yen"] - record["fee_yen"] - record["slippage_yen"]
        for side in (-1, 1):
            assert sum(h["q"] for h in holds.values() if h["side"] == side) <= config["cap"]
    assert all(h["q"] == 0 for h in holds.values()) and entry_qty == close_qty
    saved_holds = {hold["hold_id"]: hold for hold in book["holds"]}
    assert len(saved_holds) == len(book["holds"]) and set(saved_holds) == set(holds)
    for identity, hold in holds.items():
        saved = saved_holds[identity]
        assert (saved["quantity"], saved["initial_quantity"], saved["closed_quantity"]) == (hold["q"], hold["initial"], hold["closed"])
        assert (saved["entry_price"], saved["entry_quote"], saved["side"]) == (hold["entry"], hold["quote"], hold["side"])
        assert saved["gross_yen"] == hold["gross"] and saved["closed_net_yen"] == hold["net"]
    expected = {"entry_quantity": entry_qty, "close_quantity": close_qty, "gross_yen": gross, "fee_yen": fees, "slippage_yen": slips,
                "gross_minus_fee_yen": gross - fees, "net_yen": gross - fees - slips}
    for key, value in expected.items():
        assert book["totals"][key] == value, (book["method"], key)
    assert sum(h["closed_net_yen"] for h in book["holds"]) == gross - fees - slips
    return expected


def viewer_trades(book: dict, basis: str, method: str) -> list[dict]:
    """
    機能: 実約定片から所有IDを保ったViewer行を生成する。
    引数: book(dict)は台帳、basis(str)はgross/fee/slip、method(str)は表示ID。
    返り値: list[dict]は時刻順の新規・返済片。
    """
    rows = []
    zone = timezone(timedelta(hours=9))
    for record in book["fills"]:
        fill = record["fill"]
        unit_fee = Decimal(0)
        if basis in ("fee", "slip"):
            unit_fee += book["config"]["fee_yen_per_side"]
        if basis == "slip":
            unit_fee += book["config"]["slippage_points"] * book["config"]["point_value"]
        parts = [(fill["HoldID"], fill["Quantity"])] if record["action"] == "new" else [(a["hold_id"], a["quantity"]) for a in record["allocations"]]
        for index, (hold, qty) in enumerate(parts):
            position_side = record["side"] if record["action"] == "new" else -record["side"]
            kind = ("Long" if position_side == 1 else "Short") + ("N" if record["action"] == "new" else "R")
            rows.append({"id": fill["ExecutionID"] + "_" + str(index), "timestamp": datetime.fromtimestamp(float(fill["Time"]), zone).isoformat(),
                         "type": kind, "position_id": hold, "price": fill["Price"], "qty": qty, "fee_yen": unit_fee * qty, "method_id": method,
                         "source_line": record["quote"]["source_line"]})
    return rows


def main() -> None:
    """
    機能: 保存54場を独立検算し、費用別集計と最小の閲覧資料を保存する。
    引数: --run/--out(Path)は完了した再生と新しい成果物フォルダ。
    返り値: None。旧gross不一致時は未一致の結果を保存して非0終了。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    completion = read_json(args.run / "完了.json")
    assert completion["場数"] == 54 and not args.out.exists()
    args.out.mkdir(parents=True)
    rows, resources = [], []
    combined = defaultdict(lambda: defaultdict(Decimal))
    for name, expected_sha in sorted(completion["結果SHA256"].items()):
        body = (args.run / name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == expected_sha
        value = json.loads(body, parse_float=Decimal)
        methods = ("D164_15",) if value["session"].endswith("_Day") else ("P164_06", "U165_03")
        assert set(value["books"]) == {product + "_" + method for product in ("micro", "mini") for method in methods}
        assert all(value["source_rows"].get(key, 0) > 0 for key in value["books"])
        for key, book in sorted(value["books"].items()):
            metrics = verify_book(book)
            rows.append({"session": value["session"], "key": key, "totals": metrics, "holds": len(book["holds"]), "fills": len(book["fills"])})
            for k, amount in metrics.items():
                combined[key][k] += amount
            # ----------------------------------------
            # 元gross対照とmini費用2条件だけを表示し、同じ台帳の全面転記を増やさない。
            bases = ("gross",) if key.startswith("micro_") else ("fee", "slip")
            for basis in bases:
                method = key + "_" + basis
                identity = "93_" + method + "_" + value["session"]
                trade_path = identity + ".trades.jsonl"
                with (args.out / trade_path).open("x", encoding="utf-8", newline="\n") as stream:
                    for trade in viewer_trades(book, basis, method):
                        stream.write(json.dumps(trade, ensure_ascii=False, allow_nan=False, default=serial) + "\n")
                resources.append({"id": identity, "title": "元連続 " + method + " " + value["session"], "symbol": "NK225", "session": value["session"],
                                  "product": book["config"]["product"], "method_id": method, "point_value": book["config"]["point_value"], "pnl_format": "trades",
                                  "pnl_basis": "net", "pnl_path": trade_path, "market_path": "NK225/" + value["session"] + "/book.jsonl.gz"})
        with (args.out / (name + ".gz")).open("xb") as compressed:
            with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as stream:
                stream.write(body)
    expected = {"micro_D164_15": 1248500, "micro_P164_06": 392000, "micro_U165_03": 1181000}
    comparison = {key: {"元報告gross": amount, "再現gross": combined[key]["gross_yen"], "差": combined[key]["gross_yen"] - amount} for key, amount in expected.items()}
    success = len(rows) == 162 and len(resources) == 243 and all(row["差"] == 0 for row in comparison.values())
    summary = {"試行": 93, "場数": 54, "手法場数": 81, "商品手法会計数": len(rows), "元gross一致": success,
               "対照照合": comparison, "集計": dict(combined), "場別": rows, "新5分": False, "新利益追尾": False, "外テクニカル": False,
               "費用": "grossは気配差込み。gross_minus_fee_yenは指定手数料のみ、net_yenは仮定5pt片道も控除。"}
    write_json(args.out / "結果.json", summary)
    write_json(args.out / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    print(json.dumps({"元gross一致": success, "対照照合": comparison, "集計": dict(combined), "閲覧資源数": len(resources)}, ensure_ascii=False, default=serial))
    if not success:
        raise SystemExit("元報告grossの不一致。原因確認までは元再現成功と扱わない。")


if __name__ == "__main__":
    main()
