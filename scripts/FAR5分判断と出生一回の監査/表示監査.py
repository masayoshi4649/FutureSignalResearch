"""固定94の表示比較を再用し、95のN/B5/B5Q・12Actorを照合する。"""

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
FIXED = ROOT / "scripts/FAR個別利益追尾の監査/表示監査.py"
FIXED_SHA = "c9d514d990bbc53df0a887b227dc19b6ee8109c639502823e3eb303959be10a1"
if hashlib.sha256(FIXED.read_bytes()).hexdigest() != FIXED_SHA:
    raise ValueError("固定94表示部品のSHA差")
SPEC = importlib.util.spec_from_file_location("固定94表示比較の再用", FIXED)
OLD = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(OLD)
BASE, need, decimal, number = OLD.BASE, OLD.need, OLD.decimal, OLD.number
KEYS = tuple(("" if t == "N" else t + "_") + f"P0_C{c}_D{d}" for t in ("N", "B5", "B5Q") for c in (0, 5) for d in (0, 1))
AGG_SHA = "193acf7f0ddcd6b532b52d7ac7a105e2a1f61905bb97368dfeb79c177c5f5395"
CONNECTION_AGG_SHA = "83fa8815f5115d7440f130fadf46f53e3e9976aa70b668c9a36d6340b619fbe2"
PROOF94 = "ccbc365b647c8225f5ef238f707778e9fbff01c5decba721c2843cb3f1972f80"
N_TARGET = {"P0_C0_D0": -525135, "P0_C0_D1": -111135, "P0_C5_D0": -800135, "P0_C5_D1": -481981}


def key_config(key: str) -> tuple:
    """
    機能: 明示12keyを入口/費用/遅延へ結ぶ。
    引数: key(str)は95表示名。
    返り値: tupleはtiming/cost/delay。
    """
    need(key in KEYS, "95 Actor key")
    timing = "B5Q" if key.startswith("B5Q_") else "B5" if key.startswith("B5_") else "N"
    tail = key if timing == "N" else key[len(timing) + 1:]
    return timing, int(tail.split("_")[1][1:]), int(tail.split("_")[2][1:])


def local_inputs(catalog_path: Path, result_path: Path, limit: int = 54, artificial: bool = False) -> dict:
    """
    機能: 95の保存12Actor/費用/所有を検査し、固定表示部品へ期待約定を渡す。
    引数: catalog_path/result_path(Path)、limit(int)は54又は接続2、artificial(bool)は通信代替だけ。
    返り値: dictは固定94 runnerの入力。API/原板は読まない。
    """
    need(type(limit) is int and limit in (2, 54), "場数")
    catalog_path, result_path = catalog_path.resolve(), result_path.resolve()
    cb, rb = catalog_path.read_bytes(), result_path.read_bytes(); catalog, result = json.loads(cb), json.loads(rb)
    need(result["試行"] == 95 and result["成功"] is True and result["場数"] == limit and result["Actor数"] == 12 and result["会計数"] == limit * 12, "95保存会計集合")
    need(result["scope"] == ("人工" if artificial else "正式" if limit == 54 else "接続"), "表示scope")
    if not artificial:
        need(result["入力前後不変"] is True and result["入力SHA256前"] == result["入力SHA256後"], "入力前後不変")
        allowed_aggregators = (AGG_SHA,) if limit == 54 else (AGG_SHA, CONNECTION_AGG_SHA)
        need(result["集計コードSHA256"] in allowed_aggregators and result["基準94完了SHA256"] == PROOF94, "95集計/旧94完了の指紋")
        need(result["固定54場金額照合実施"] is (limit == 54), "54金額の照合範囲")
        matches = result["N4基準照合"]
        need(len(matches) == limit and len({r["session"] for r in matches}) == limit
             and all(r["基準完了SHA256"] == PROOF94 and set(r["一致口座"]) == set(N_TARGET) for r in matches), "N4全文比較の保存証拠")
    rows = {(r["session"], r["key"]): r for r in result["場別"]}; sessions = {s for s, _ in rows}
    need(len(rows) == len(result["場別"]) == limit * 12 and len(sessions) == limit
         and set(rows) == {(s, k) for s in sessions for k in KEYS}, "全場Actor一意")
    days = {s[:-4] for s in sessions if s.endswith("_Day")}; nights = {s[:-6] for s in sessions if s.endswith("_Night")}
    need(days == nights and len(days) == limit // 2 and all("2026-09-21" <= d <= "2026-10-27" for d in days), "既使用昼夜の集合")
    need(set(result["集計"]) == set(result["Actor設定"]) == set(KEYS), "95 Actor設定集合")
    sums = {key: {field: Decimal(0) for field in OLD.TOTALS + ("positions", "fills")} for key in KEYS}
    expected = {}
    for (session, key), row in rows.items():
        timing, slip, delay = key_config(key); totals, counts = row["totals"], row["counts"]
        need(row["entry_timing"] == timing and result["Actor設定"][key] ==
             {"entry_timing": timing, "key": key, "policy": "P0", "slip_pts": slip, "delay_seconds": delay}, "N/B/BQ・config対応")
        qty = totals["entry_quantity"]
        need(type(qty) is int and qty >= 0 and type(totals["close_quantity"]) is int and totals["close_quantity"] == qty, "実新規/返済量")
        need(all(type(counts[n]) is int and counts[n] >= 0 for n in ("positions", "fills")), "実玉/約定数")
        need(all(decimal(totals[n]) == 0 for n in OLD.ZERO_FIELDS), "終所有/予約/未回収新規費用0")
        gross, fee, cost, net = (decimal(totals[n]) for n in ("gross_yen", "fee_yen", "slip_yen", "net_yen"))
        need(fee == 77 * qty and cost == 200 * slip * qty and decimal(totals["gross_minus_fee_yen"]) == gross - fee
             and net == gross - fee - cost and decimal(totals["closed_net_yen"]) == net, "95費用3列/半円")
        for field in OLD.TOTALS: sums[key][field] += decimal(totals[field])
        for field in ("positions", "fills"): sums[key][field] += counts[field]
        rid = "95_" + key + "_" + session
        expected[rid] = {"row": row, "key": key, "timing": timing, "unit_fee": Decimal("38.5") + 100 * slip, "net": number(net)}
    for key in KEYS:
        for field, amount in sums[key].items(): need(decimal(result["集計"][key][field]) == amount, "95場別/全体加算")
    if not artificial and limit == 54:
        need(all(sums[key]["net_yen"] == value for key, value in N_TARGET.items()), "N4の固定実現額")
    resources = catalog["resources"]
    need(catalog["schema_version"] == 1 and catalog["path_base"] == "catalog"
         and len(resources) == len({r["id"] for r in resources}) == limit * 12
         and {r["id"] for r in resources} == set(expected), "95全Viewer資源")
    hashes = {str(catalog_path): hashlib.sha256(cb).hexdigest(), str(result_path): hashlib.sha256(rb).hexdigest(),
              str(Path(__file__).resolve()): BASE.sha(Path(__file__.strip())), str(FIXED): FIXED_SHA,
              str(OLD.LEGACY_PATH): OLD.LEGACY_SHA, str(OLD.LEGACY.FIXED): OLD.LEGACY.FIXED_SHA}
    trades, events = {}, {}
    for resource in resources:
        e = expected[resource["id"]]; row, key = e["row"], e["key"]
        need((resource["symbol"], resource["session"], resource["product"], resource["method_id"], resource["point_value"], resource["pnl_format"], resource["pnl_basis"])
             == ("NK225", row["session"], "NK225mini", key, 100, "trades", "net"), "95 resourceラベル")
        need(resource["title"] == "出生一回 " + e["timing"] + "/" + key + " " + row["session"], "資源Timing/key識別")
        need(resource["market_path"] == "NK225/" + row["session"] + "/book.jsonl.gz", "市場参照ラベル")
        path = (catalog_path.parent / resource["pnl_path"]).resolve(); need(path.is_relative_to(catalog_path.parent), "約定参照境界")
        body = path.read_bytes(); hashes[str(path)] = hashlib.sha256(body).hexdigest()
        saved = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
        seen, owners = set(), {}; entry = close = 0; previous = None
        for trade in saved:
            need(isinstance(trade["id"], str) and trade["id"] and trade["id"] not in seen, "Fill ID一意")
            seen.add(trade["id"])
            need(trade["method_id"] == key and trade["type"] in ("LongN", "LongR", "ShortN", "ShortR"), "約定key/種類")
            pid, qty = trade["position_id"], trade["qty"]
            need(isinstance(pid, str) and pid and type(qty) is int and qty > 0 and decimal(trade["price"]) > 0, "実所有/数量/価格")
            need(type(trade["source_line"]) is int and trade["source_line"] > 0, "実物理行")
            stamp = datetime.fromisoformat(trade["timestamp"])
            need(stamp.utcoffset() == timedelta(hours=9) and (previous is None or previous <= stamp), "約定時計")
            previous = stamp
            need(decimal(trade["fee_yen"]) == e["unit_fee"] * qty, "C0/C5片道半円費用")
            side = 1 if trade["type"].startswith("Long") else -1
            if trade["type"].endswith("N"):
                need(pid not in owners, "実新規ID再利用"); owners[pid] = [side, qty]; entry += qty
            else:
                need(pid in owners and owners[pid][0] == side and qty <= owners[pid][1], "partial返済所有")
                owners[pid][1] -= qty; close += qty
            need(all(sum(v[1] for v in owners.values() if v[0] == s) <= 10 for s in (-1, 1)), "表示実所有各側10")
        need(entry == close == row["totals"]["entry_quantity"] and len(owners) == row["counts"]["positions"]
             and len(saved) == row["counts"]["fills"] and all(v[1] == 0 for v in owners.values()), "表示量/件数/終0")
        calculated = BASE.trade_expectations(saved, 100)
        need(sum((decimal(v["realized_delta_yen"]) for v in calculated), Decimal(0)) == decimal(e["net"]), "Viewer全片の独立純額")
        trades[resource["id"]], events[resource["id"]] = saved, calculated
    return {"catalog": catalog, "result": result, "resources": resources, "expected": expected,
            "trades": trades, "events": events, "入力SHA256": hashes}


def run(catalog_path: Path, result_path: Path, url: str = "http://127.0.0.1:8092", workers: int = 8,
        transport=None, progress: bool = True, limit: int = 54, artificial: bool = False) -> dict:
    """
    機能: 固定94の全約定/API本文SHA/未完/終0比較を95へ直接再用する。
    引数: catalog_path/result_path(Path)、url(str)、workers(int)、transport(callable|None)、progress(bool)、limit(int)、artificial(bool)。
    返り値: dictは95監査証拠。import済み94のglobalやViewerプロセスを変更しない。
    """
    namespace = dict(vars(OLD)); namespace.update(local_inputs=local_inputs, __file__=__file__)
    runner = types.FunctionType(OLD.run.__code__, namespace, "固定94表示runnerと95入力", OLD.run.__defaults__)
    result = runner(catalog_path, result_path, url, workers, transport, progress, limit, artificial)
    result["試行"] = 95; result["固定94部品SHA256"] = FIXED_SHA
    catalog = json.loads(catalog_path.read_text(encoding="utf-8")); by_id = {r["id"]: r["method_id"] for r in catalog["resources"]}
    for row in result["資源"]:
        key = by_id[row["id"]]; timing, cost, delay = key_config(key)
        row.update(Actor=key, EntryTiming=timing, 費用基準="C" + str(cost), 約定遅延秒=delay)
    return result


def self_test() -> dict:
    """
    機能: 2場24資源のN/B/BQ・C0/C5・partial/半円/0取引だけを狭く検査する。
    引数: なし。実市場/原板/実APIは使わない。
    返り値: dictは差分人工の証拠。
    """
    with tempfile.TemporaryDirectory(prefix="95表示差分_", dir=ROOT / "work") as name:
        temp = Path(name); resources, rows, trades = [], [], {}
        groups = {k: {n: 0 for n in OLD.TOTALS + ("positions", "fills")} for k in KEYS}
        for kind in ("Day", "Night"):
            session = "2026-09-21_" + kind
            for key in KEYS:
                timing, cost, delay = key_config(key); zero = kind == "Day" and key == "B5Q_P0_C5_D1"
                totals = {"entry_quantity": 0 if zero else 3, "close_quantity": 0 if zero else 3,
                    "gross_yen": 0 if zero else 5000, "fee_yen": 0 if zero else 231, "slip_yen": 0 if zero else cost * 600,
                    "gross_minus_fee_yen": 0 if zero else 4769, "net_yen": 0 if zero else 4769 - cost * 600,
                    **{field: 0 for field in OLD.ZERO_FIELDS}}
                totals["closed_net_yen"] = totals["net_yen"]; counts = {"positions": 0 if zero else 1, "fills": 0 if zero else 3}
                rows.append({"session": session, "key": key, "entry_timing": timing, "totals": totals, "counts": counts})
                for field in OLD.TOTALS: groups[key][field] += totals[field]
                for field in counts: groups[key][field] += counts[field]
                rid = "95_" + key + "_" + session; side = 1 if kind == "Day" else -1
                at = datetime.fromisoformat("2026-09-21" + ("T09:20:00+09:00" if kind == "Day" else "T18:00:00+09:00"))
                saved = [] if zero else [{"id": rid + str(i), "timestamp": (at + timedelta(seconds=i)).isoformat(),
                    "type": ("Long" if side == 1 else "Short") + ("N" if i == 0 else "R"), "position_id": rid,
                    "price": price, "qty": qty, "fee_yen": (38.5 + cost * 100) * qty, "method_id": key, "source_line": 10 + i}
                    for i, (price, qty) in enumerate(((1000, 3), (1000 + side * 30, 1), (1000 + side * 10, 2)))]
                (temp / (rid + ".trades.jsonl")).write_text("".join(json.dumps(r) + "\n" for r in saved), encoding="utf-8")
                trades[rid] = saved
                resources.append({"id": rid, "title": "出生一回 " + timing + "/" + key + " " + session, "symbol": "NK225", "product": "NK225mini",
                    "session": session, "method_id": key, "point_value": 100, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": rid + ".trades.jsonl", "market_path": "NK225/" + session + "/book.jsonl.gz"})
        result = {"試行": 95, "成功": True, "scope": "人工", "場数": 2, "Actor数": 12, "会計数": 24, "集計": groups, "場別": rows,
            "Actor設定": {k: {"key": k, "entry_timing": key_config(k)[0], "policy": "P0", "slip_pts": key_config(k)[1], "delay_seconds": key_config(k)[2]} for k in KEYS}}
        catalog_path, result_path = temp / "一覧.resources.json", temp / "結果.json"
        catalog_path.write_text(json.dumps({"schema_version": 1, "path_base": "catalog", "resources": resources}), encoding="utf-8")
        result_path.write_text(json.dumps(result), encoding="utf-8")
        resolved = {r["id"]: {**r, "pnl_path": str(temp / r["pnl_path"]), "market_path": str(temp / "市場" / r["market_path"])} for r in resources}
        def fake(method, url, payload=None):
            """
            機能: 固定API schemaの通信代替を返す。
            引数: method/url(str)、payload(dict|None)は人工依頼。
            返り値: tupleは本文/bytes/SHAヘッダ。
            """
            if url.endswith("/api/info"): value = {"resource_root": str(temp), "data_root": str(temp / "市場"), "listen": "127.0.0.1:8092"}
            elif url.endswith("/api/catalogs/load"): value = {"catalog_id": "人工95", "path": str(catalog_path), "resources": list(resolved.values())}
            else:
                rid = parse_qs(urlparse(url).query)["resource"][0]; events = BASE.trade_expectations(trades[rid], 100)
                net = sum(e["realized_delta_yen"] for e in events)
                value = {"resource": resolved[rid], "summary": {"long_qty": 0, "short_qty": 0, "realized_pnl_yen": net, "unrealized_pnl_yen": 0},
                    "state_columns": ["long_qty", "short_qty", "realized_pnl_yen", "unrealized_pnl_yen"], "states": [[0, 0, net, 0]], "events": events,
                    "files": {"pnl": resolved[rid]["pnl_path"], "market": resolved[rid]["market_path"], "catalog": str(catalog_path)}}
            body = json.dumps(value).encode(); return value, body, {"x-chart-data-sha256": hashlib.sha256(body).hexdigest()}
        good = run(catalog_path, result_path, transport=fake, workers=2, progress=False, limit=2, artificial=True)
        need(good["成功"] and good["完了資源"] == 24, "95狭い正常人工")
        checks = ["N/B5/B5Q各4key・C0/C5半円・partial/買売・無取引0"]
        for corruption in ("本文SHA", "終0未知", "通信未完"):
            def bad(method, url, payload=None):
                """
                機能: 重要な通信/本文/終数量破損だけを注入する。
                引数: method/url(str)、payload(dict|None)。
                返り値: tupleは破損応答又は固定通信例外。
                """
                if corruption == "通信未完" and "/api/data?" in url: raise BASE.ViewerError("通信", url, "人工未完")
                value, _, _ = fake(method, url, payload)
                if corruption == "終0未知" and "/api/data?" in url: value["summary"]["long_qty"] = None
                body = json.dumps(value).encode(); return value, body, {"x-chart-data-sha256": "破損" if corruption == "本文SHA" else hashlib.sha256(body).hexdigest()}
            need(not run(catalog_path, result_path, transport=bad, workers=2, progress=False, limit=2, artificial=True)["成功"], "95差分人工の破損見逃し")
            checks.append(corruption + "拒否")
        first = next(r for r in resources if trades[r["id"]]); path = temp / first["pnl_path"]; original = path.read_bytes()
        changed = [json.loads(r) for r in original.decode().splitlines()]; changed[0]["fee_yen"] += .5
        path.write_text("".join(json.dumps(r) + "\n" for r in changed), encoding="utf-8")
        try: local_inputs(catalog_path, result_path, limit=2, artificial=True)
        except ValueError: checks.append("local半円費用拒否")
        else: raise AssertionError("local半円破損を受理")
        return {"成功": True, "正常資源": 24, "人工項目": checks, "正常照合項目": good["照合項目数"],
            "固定94部品SHA256": FIXED_SHA, "監査コードSHA256": BASE.sha(Path(__file__)), "実API": 0, "市場/原板": 0}


def main() -> None:
    """
    機能: 差分人工又は明示された既存8092の保存数値を照合し、新規証拠を保存する。
    引数: --self-test/--run、--catalog/--result/--out(Path)、--limit(int)、--url(str)、--workers(int)。
    返り値: None。未完/不一致は非0。サーバ起動停止/再設定なし。
    """
    parser = argparse.ArgumentParser(description=__doc__); mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true"); mode.add_argument("--run", action="store_true")
    for name in ("catalog", "result", "out"): parser.add_argument("--" + name, type=Path, required=name == "out")
    parser.add_argument("--limit", type=int, choices=(2, 54), default=54); parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--url", default="http://127.0.0.1:8092"); args = parser.parse_args(); need(not args.out.exists(), "新規証拠先だけ")
    if args.self_test:
        need(args.catalog is None and args.result is None, "人工に実入力を渡さない"); proof = self_test()
    else:
        need(args.catalog is not None and args.result is not None, "一覧/結果を明示")
        proof = run(args.catalog, args.result, args.url, args.workers, limit=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream: json.dump(proof, stream, ensure_ascii=False, indent=2); stream.write("\n")
    print(json.dumps({k: proof[k] for k in ("成功", "正常資源", "完了資源", "照合項目数", "不一致数") if k in proof}, ensure_ascii=False))
    if not proof["成功"]: raise SystemExit(1)


if __name__ == "__main__": main()
