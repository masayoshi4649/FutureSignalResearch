"""80の集計を、架空会計・十進別算・評価列から独立に確認する。"""

import argparse
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MODES = ("F0", "P1", "T1")


def stamp(at: float) -> str:
    """架空価格秒をJSTの約定時計へ写す。

    引数: at(float)は架空epoch秒。
    返り値: strは時差付きISO8601。
    """
    return datetime.fromtimestamp(at, timezone(timedelta(hours=9))).isoformat()


def fake_book(session: str, mode: str, case: int) -> tuple[dict, list[int]]:
    """部分返済・黒字・赤字・空場の架空JSONを作る。

    引数: session/mode(str)は場と案、case(int)は0部分/1黒字/2赤字/その他空。
    返り値: tuple[dict,list[int]]はBookResult互換会計と独立の場内評価列。
    """
    date, kind = session.split("_")
    at = datetime.fromisoformat(date + ("T09:15:00+09:00" if kind == "Day" else "T17:30:00+09:00")).timestamp()
    exits = [(30, 1030), (35, 990), (35, 1005)] if case == 0 else [(100, 1105)] if case == 1 else [(1, 905)] if case == 2 else []
    qty = sum(n for n, _ in exits)
    flag = case in (0, 1)
    flag_time = at + 3 if flag else None
    pid, rid = session + "_" + mode + "_P1", session + "_R1"
    trades, orders, closed, lots = [], [], [], []
    gross = sum((price - 1005) * 10 * n for n, price in exits)
    net = gross - 122 * qty
    paths = {0: [0, -17200, 12800, -15200, -9950], 1: [0, -17200, 87800], 2: [0, -172, -1122]}
    path = paths.get(case, [0])
    peak = dd = 0
    for equity in path:
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    if qty:
        trades.append({"id": pid + "_T0", "timestamp": stamp(at + 1), "type": "LongN", "position_id": pid,
            "price": 1005, "qty": qty, "fee_yen": 61 * qty, "method_id": mode, "source_line": 2, "reason": "人工定時新規"})
        orders.append({"id": pid + "_O0", "kind": "entry", "reference_id": rid, "position_id": pid, "side": 1,
            "quantity": qty, "remaining": 0, "filled_quantity": qty, "cancelled_quantity": 0, "request_time": at,
            "request_index": 1, "request_line": 1, "fill_time": at + 1, "fill_price": 1005, "fill_line": 2,
            "reason": "人工定時新規", "status": "filled"})
        old_mark = 1005
        for i, (n, price) in enumerate(exits):
            when, line = at + 3 + i, 4 + i
            reason = "人工参照部分返済" if case == 0 else "人工参照返済"
            g = (price - 1005) * 10 * n
            floor = -125 if mode == "F0" or i == 0 else 20
            trades.append({"id": pid + "_T" + str(i + 1), "timestamp": stamp(when), "type": "LongR", "position_id": pid,
                "price": price, "qty": n, "fee_yen": 61 * n, "method_id": mode, "source_line": line, "reason": reason})
            orders.append({"id": pid + "_O" + str(i + 1), "kind": "exit", "reference_id": rid, "position_id": pid, "side": 1,
                "quantity": n, "remaining": 0, "filled_quantity": n, "cancelled_quantity": 0, "request_time": when - 1,
                "request_index": line - 1, "request_line": line - 1, "fill_time": when, "fill_price": price, "fill_line": line,
                "reason": reason, "status": "filled"})
            closed.append({"position_id": pid, "reference_id": rid, "side": 1, "quantity": n,
                "entry_price": 1005, "exit_price": price, "entry_time": at + 1, "exit_time": when, "exit_line": line,
                "reason": reason, "gross_pnl": g, "commission": 22 * n, "slippage": 100 * n,
                "pnl0": g - 22 * n, "pnl5": g - 122 * n, "pnl10": g - 222 * n, "flag": flag,
                "flag_time": flag_time, "flag_mark": exits[0][1] if flag else None, "flag_floor": -125 if flag else None,
                "flag_net_per_unit": (exits[0][1] - 1005) * 10 - 122 if flag else None,
                "request_time": when - 1, "request_mark": old_mark, "request_floor": floor,
                "request_net_per_unit": (old_mark - 1005) * 10 - 122,
                "request_to_fill_adverse_yen": (old_mark - price) * 10 * n, "floor_jump": old_mark - 1005 < floor,
                "cost_loss": g > 0 and g - 122 * n < 0, "nominal_flat": price == 1005})
            old_mark = price
        lots.append({"id": pid, "reference_id": rid, "method": "人工手法", "owner": "人工", "source_id": "人工源", "parent": "人工親", "role": "順行", "side": 1, "quantity": 0, "initial_quantity": qty,
            "reserved_exit": 0, "entry_price": 1005, "entry_time": at + 1, "entry_index": 2, "entry_line": 2,
            "entry_atr": None, "d": 125, "floor": -125 if mode == "F0" else 20 if flag else -125,
            "flag": flag, "flag_time": flag_time, "flag_index": 4 if flag else 0, "flag_mark": exits[0][1] if flag else None,
            "flag_net_per_unit": (exits[0][1] - 1005) * 10 - 122 if flag else None,
            "flag_floor": -125 if mode == "F0" else 20 if flag else None,
            "request_time": at + 2, "request_mark": 1005, "request_floor": -125, "net_pnl": net, "closed_quantity": qty})
    metrics = {"cash_yen": net, "net_pnl_yen": net, "gross_pnl_yen": gross, "commission_yen": 22 * qty,
        "slippage_yen": 100 * qty, "total_cost_yen": 122 * qty, "equity_yen": net, "floating_yen": 0,
        "equity_peak_yen": peak, "min_equity_yen": min(path), "max_drawdown_yen": dd,
        "worst_floating_yen": -19040 if case == 0 else -17200 if case == 1 else -1122 if case == 2 else 0,
        "entry_quantity": qty, "exit_quantity": qty, "open_quantity": 0, "pending_entry_quantity": 0,
        "reserved_exit_quantity": 0, "closed_pieces": len(exits), "winning_pieces": sum(c["pnl5"] > 0 for c in closed),
        "losing_pieces": sum(c["pnl5"] < 0 for c in closed), "flat_pieces": sum(c["pnl5"] == 0 for c in closed),
        "closed_lots": int(qty > 0), "winning_lots": int(qty > 0 and net > 0), "losing_lots": int(qty > 0 and net < 0),
        "flat_lots": int(qty > 0 and net == 0), "profit_flags": int(flag),
        "flag_after_loss_pieces": sum(c["flag"] and c["pnl5"] < 0 for c in closed),
        "request_before_floor_violations": 0, "mark_known": True, "unpriced_exposure_quotes": 0}
    decisions = [{"at": at + i * 900, "quote_time": at + i * 900, "quote_index": 100 + i,
        "action": "新規要求" if qty and i == 0 else "待ち", "reason": "人工", "candidates": []}
        for i in range(25 if kind == "Day" else 49)]
    return {"session": session, "mode": mode, "side_cap": 100, "fill_delay_seconds": 0, "trades": trades,
        "orders": orders, "decisions": decisions, "closed": closed, "positions": [], "lots": lots,
        "pending_entries": [], "quantity_by_side": {"-1": 0, "1": 0}, "metrics": metrics, "unresolved": False, "warnings": []}, path


# ----------------------------------------
def independent_cash(book: dict) -> dict:
    """約定所有と十進演算だけから残量と費用後現金を別算する。

    引数: book(dict)は架空BookResult。
    返り値: dictはDecimal現金/粗利益/費用とintの残量。
    """
    owners = {}
    cash = gross = fee = Decimal(0)
    for row in book["trades"]:
        n, price = row["qty"], Decimal(str(row["price"]))
        cost = Decimal(str(row["fee_yen"]))
        cash -= cost
        fee += cost
        pid = row["position_id"]
        if row["type"] in ("LongN", "ShortN"):
            owners[pid] = [n, price, 1 if row["type"] == "LongN" else -1]
        else:
            state = owners[pid]
            value = Decimal(state[2] * n * 10) * (price - state[1])
            gross += value
            cash += value
            state[0] -= n
    return {"約定数": len(book["trades"]), "現金円": cash, "粗損益円": gross, "費用円": fee, "残量": sum(p[0] for p in owners.values())}


def direct_drawdown(paths: list[list[int]]) -> int:
    """場内の全評価点を累積残高へ直接つなぎ最大DDを別算する。

    引数: paths(list[list[int]])は初期0/最終場損益を持つ架空評価列。
    返り値: intは局所要約式を使わない連結最大DD円。
    """
    running = peak = dd = 0
    for path in paths:
        for local in path:
            now = running + local
            peak = max(peak, now)
            dd = max(dd, peak - now)
        running += path[-1]
    return dd


def self_test() -> dict:
    """架空66場のCLI出力と変異拒否を独立に確認する。

    引数: なし。
    返り値: dictは成功/群数/照合数/コードSHA。本物入力と市場は読まない。
    """
    source = HERE / "集計.py"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("FAR80人工出力側集計", source)
    implementation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(implementation)
    count = 0

    def check(actual: object, expected: object, name: str) -> None:
        """人工の実値と独立期待値を比較する。

        引数: actual/expected(object)は値、name(str)は検査名。
        返り値: None。差はAssertionError。
        """
        nonlocal count
        count += 1
        if actual != expected:
            raise AssertionError(name + ":" + repr(actual)[:200] + " != " + repr(expected)[:200])

    books = [fake_book("2026-10-01_Day", "F0", case)[0] for case in range(4)]
    for book in books:
        check(implementation.cash_check(book), independent_cash(book), "十進約定会計の別算")
    base = books[0]
    mutations = [
        (("closed", 0, "commission"), 1), (("closed", 0, "slippage"), 1),
        (("closed", 0, "gross_pnl"), 1), (("closed", 0, "pnl0"), 1), (("closed", 0, "pnl5"), 1), (("closed", 0, "pnl10"), 1),
        (("metrics", "entry_quantity"), 1), (("metrics", "exit_quantity"), 1), (("metrics", "commission_yen"), 1),
        (("metrics", "slippage_yen"), 1), (("metrics", "winning_lots"), 1), (("metrics", "profit_flags"), 1),
        (("lots", 0, "net_pnl"), 1), (("lots", 0, "initial_quantity"), 1), (("lots", 0, "closed_quantity"), 1),
        (("orders", 1, "fill_line"), -1), (("orders", 1, "fill_time"), -2), (("orders", 0, "request_time"), 1),
        (("trades", 1, "fee_yen"), 1), (("trades", 1, "type"), "LongX"), (("trades", 1, "position_id"), "存在しない玉"),
        (("lots",), []), (("decisions",), []),
    ]
    for path, value in mutations:
        changed = deepcopy(base)
        parent = changed
        for part in path[:-1]:
            parent = parent[part]
        last = path[-1]
        parent[last] = parent[last] + value if isinstance(value, int) else value
        rejected = False
        try:
            implementation.cash_check(changed)
        except (AssertionError, KeyError, TypeError, ValueError):
            rejected = True
        check(rejected, True, "破損拒否:" + str(path))
    rejected = False
    changed = deepcopy(base)
    changed["orders"][1]["quantity"] += 1
    changed["orders"][1]["cancelled_quantity"] = 1
    try:
        implementation.cash_check(changed)
    except (AssertionError, KeyError, TypeError, ValueError):
        rejected = True
    check(rejected, True, "受理返済取消の拒否")
    # ----------------------------------------
    # 一時領域の絶対位置を確認し、架空JSONだけで正式と同じCLIを通す。
    temporary_parent = (ROOT / "work").resolve()
    with tempfile.TemporaryDirectory(prefix="FAR80集計人工_", dir=temporary_parent) as folder:
        temp = Path(folder).resolve()
        assert temp.is_relative_to(temporary_parent)
        input_dir, output_dir = temp / "架空入力", temp / "架空出力"
        input_dir.mkdir()
        entries, sessions, paths = [], [], []
        for day in range(33):
            date = (datetime(2026, 10, 1) + timedelta(days=day)).date().isoformat()
            for kind in ("Day", "Night"):
                session = date + "_" + kind
                entries.append({"id": session})
                index = len(entries) - 1
                material = {mode: fake_book(session, mode, index)[0] for mode in MODES}
                paths.append(fake_book(session, "F0", index)[1])
                result = {"session": session, "books": material, "quality": {"人工": True, "市場読取": 0}}
                sessions.append(result)
                (input_dir / (session + ".json")).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        manifest = temp / "架空台帳.json"
        manifest.write_text(json.dumps({"sessions": entries}), encoding="utf-8")
        argv = sys.argv
        try:
            sys.argv = [str(source), "--input", str(input_dir), "--out", str(output_dir), "--manifest", str(manifest)]
            with redirect_stdout(io.StringIO()):
                implementation.main()
        finally:
            sys.argv = argv
        result = json.loads((output_dir / "結果.json").read_text(encoding="utf-8"))
        check(result["場数"], 66, "架空66場")
        check(direct_drawdown(paths), 39950, "評価列を直接つないだ期待DD")
        for mode in MODES:
            found = result["比較"][mode]
            for key, expected in {"費用後損益円": 76728, "最大DD円": direct_drawdown(paths), "最大場内含み損円": -19040,
                    "赤字場数": 2, "黒字場数": 1, "無取引又は同値場数": 63, "利益観測済み完結玉": 2, "利益観測後赤字玉": 1,
                    "同約定費用0pt損益円": 96828, "同約定費用10pt損益円": 56628, "entry_quantity": 201,
                    "exit_quantity": 201, "total_cost_yen": 24522, "closed_lots": 3, "flag_after_loss_pieces": 2,
                    "赤字日数": 1, "日数": 33}.items():
                check(found[key], expected, mode + ":" + key)
            check(found["利益後赤字の内訳"]["赤字返済片"], 2, "赤字片と赤字玉の分母分離")
            group = result["FAR時間帯別"][mode]["人工手法"]
            check((group["完結玉"], group["新規枚数"], group["損益円"], group["費用円"], group["利益後赤字玉"]),
                (3, 201, 76728, 24522, 1), "時間帯帰属の枚数費用と全玉赤字")
        for mode in ("P1", "T1"):
            split = result["入口と出口の分解"][mode + "対F0"]
            check((split["同じ実新規"], split["同じ実新規出口差円"], split["F0だけ"], split["比較案だけ"]),
                (3, 0, 0, 0), "同参照と同新規の出口差")
        catalog = json.loads((output_dir / "一覧.resources.json").read_text(encoding="utf-8"))
        resources = catalog["resources"]
        check((len(resources), len({row["id"] for row in resources}), catalog["path_base"]), (198, 198, "catalog"), "Viewer198全集合")
        lookup = {(row["session"], mode): row["books"][mode] for row in sessions for mode in MODES}
        for resource in resources:
            rows = [json.loads(line) for line in (output_dir / resource["pnl_path"]).read_text(encoding="utf-8").splitlines()]
            book = lookup[resource["session"], resource["method_id"]]
            check(rows, book["trades"], "Viewer全約定と空ファイル")
            check(independent_cash({**book, "trades": rows}), independent_cash(book), "Viewer所有と現金")
            check((resource["point_value"], resource["product"], resource["pnl_basis"]), (10, "NK225micro", "net"), "Viewer単位と費用基準")
        proof = json.loads((output_dir / "約定会計の独立照合.json").read_text(encoding="utf-8"))
        check((proof["会計数"], proof["差分"]), (198, 0), "全会計proof")
        with gzip.open(output_dir / "取引診断.jsonl.gz", "rt", encoding="utf-8") as stream:
            diagnostics = [json.loads(line) for line in stream]
        check(len(diagnostics), 9, "全完結玉の小型診断")
        check(sum(row["lot"]["flag"] and row["lot"]["net_pnl"] < 0 for row in diagnostics), 3, "全案の利益後赤字玉")
    check(hashlib.sha256(source.read_bytes()).hexdigest(), before, "人工中の主集計コード不変")
    return {"成功": True, "不一致数": 0, "テスト件数": 8 + len(mutations), "照合項目数": count,
        "架空場数": 66, "架空会計数": 198, "市場読取": 0, "市場再生": 0,
        "集計コードSHA256": before, "本物結果読取": False, "人工一時JSON保存": "専用work一時領域だけ。終了時削除"}


# ----------------------------------------
def verify_saved(folder: Path, expected_sessions: int | None = None) -> dict:
    """保存済み実会計JSONだけを十進演算と所有数量から照合する。

    引数: folder(Path)は許可済みの実行結果、expected_sessions(int|None)は予定場数。
    返り値: dictはコード/入力前後指紋と案別照合。市場や売買を再実行しない。
    """
    source = HERE / "集計.py"
    spec = importlib.util.spec_from_file_location("FAR80保存結果の集計側", source)
    implementation = importlib.util.module_from_spec(spec)
    source_before = hashlib.sha256(source.read_bytes()).hexdigest()
    spec.loader.exec_module(implementation)
    paths = sorted(path for path in folder.resolve().glob("*.json")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}_(Day|Night)\.json", path.name))
    assert paths and (expected_sessions is None or len(paths) == expected_sessions), "保存場数の差"
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    totals = {mode: Counter() for mode in MODES}
    records = []
    count = 0
    for path in paths:
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["session"] == path.stem and set(result["books"]) == set(MODES)
        for mode in MODES:
            book = result["books"][mode]
            assert book["mode"] == mode and book["session"] == path.stem and book["unresolved"] is False
            output = implementation.cash_check(book)
            expected = independent_cash(book)
            assert output == expected, "十進会計と集計側の差"
            count += len(expected)
            owners = {}
            for trade in book["trades"]:
                pid, n, price = trade["position_id"], trade["qty"], Decimal(str(trade["price"]))
                if trade["type"] in ("LongN", "ShortN"):
                    owners[pid] = {"initial": n, "quantity": n, "closed": 0, "net": Decimal(0), "entry": price,
                        "side": 1 if trade["type"] == "LongN" else -1}
                else:
                    owner = owners[pid]
                    owner["quantity"] -= n
                    owner["closed"] += n
                    owner["net"] += Decimal(owner["side"] * n * 10) * (price - owner["entry"]) - Decimal(122 * n)
            assert len(owners) == len(book["lots"])
            for lot in book["lots"]:
                own = owners[lot["id"]]
                assert (lot["initial_quantity"], lot["quantity"], lot["closed_quantity"], Decimal(str(lot["net_pnl"]))) \
                    == (own["initial"], 0, own["closed"], own["net"])
                assert own["quantity"] == 0
                totals[mode]["完結玉"] += 1
                totals[mode]["新規枚数"] += own["initial"]
                totals[mode]["利益観測玉"] += bool(lot["flag"])
                totals[mode]["利益後赤字玉"] += bool(lot["flag"] and own["net"] < 0)
                count += 5
            p0 = p5 = p10 = Decimal(0)
            for piece in book["closed"]:
                n = piece["quantity"]
                gross = Decimal(piece["side"] * n * 10) * (Decimal(str(piece["exit_price"])) - Decimal(str(piece["entry_price"])))
                assert Decimal(str(piece["commission"])) == 22 * n and Decimal(str(piece["slippage"])) == 100 * n
                assert tuple(Decimal(str(piece[name])) for name in ("pnl0", "pnl5", "pnl10")) \
                    == (gross - 22 * n, gross - 122 * n, gross - 222 * n)
                p0 += gross - 22 * n
                p5 += gross - 122 * n
                p10 += gross - 222 * n
                count += 5
            assert p5 == expected["現金円"]
            total = totals[mode]
            total["費用後損益円"] += p5
            total["同約定0pt円"] += p0
            total["同約定10pt円"] += p10
            total["片費用合計円"] += expected["費用円"]
            total["約定片"] += len(book["trades"])
            records.append({"場": path.stem, "案": mode, "約定片": len(book["trades"]),
                "費用後損益円": float(p5), "片費用合計円": float(expected["費用円"]), "完結玉": len(owners)})
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert before == after and source_before == hashlib.sha256(source.read_bytes()).hexdigest(), "読取中の入力変更"
    summaries = {mode: {key: float(value) if isinstance(value, Decimal) else value for key, value in row.items()}
        for mode, row in totals.items()}
    return {"成功": True, "不一致数": 0, "場数": len(paths), "会計数": len(records), "照合項目数": count,
        "集計コードSHA256": source_before, "入力SHA256前": before, "入力SHA256後": after, "入力不変": True,
        "独立案別": summaries, "場別": records, "市場原板読取": 0, "新売買再生": 0,
        "限定": "保存約定の数量・現金・費用・全完結玉を照合。利益旗の原tick再構成、原BBO約定、局所DDの原tick再構成は別工程"}


def main() -> None:
    """人工又は明示指定された保存結果の読取照合を選ぶ。

    引数: CLIの--input(Path|None)は保存JSON、--expect-sessions(int|None)は予定場数。
    返り値: None。保存値や既存証拠を変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--expect-sessions", type=int)
    args = parser.parse_args()
    value = verify_saved(args.input, args.expect_sessions) if args.input is not None else self_test()
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
