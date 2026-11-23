"""94の12Actor/648Viewer資源を固定93/80の表示比較部品で照合する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
from urllib.parse import parse_qs, urlencode, urlparse


ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = ROOT / "scripts/FAR元連続再現の監査/表示監査.py"
LEGACY_SHA = "3f7922abe755711d4ff2847df05133b027bca025ca13976e9437bd074463b954"
if hashlib.sha256(LEGACY_PATH.read_bytes()).hexdigest() != LEGACY_SHA:
    raise ValueError("固定93表示部品の指紋差")
SPEC = importlib.util.spec_from_file_location("個別追尾表示の固定93部品", LEGACY_PATH)
LEGACY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEGACY)
BASE = LEGACY.BASE
KEYS = tuple(f"{p}_C{c}_D{d}" for p in ("S0", "P0", "P1") for c in (0, 5) for d in (0, 1))
TOTALS = ("entry_quantity", "close_quantity", "gross_yen", "fee_yen", "slip_yen", "gross_minus_fee_yen", "net_yen")
ZERO_FIELDS = ("open_buy", "open_sell", "pending_buy", "pending_sell", "open_entry_costs_yen")
AGGREGATOR_SHA = "5749a1095a63849d7c1b6d66f898c26b4a9ff4ecc4a593eb075ab4d587778522"
AGGREGATOR_COMMENT_SHA = "7c0c1d1b365226c74027405589099cb72382c7850090627a83788e1e2066c381"


def need(ok: bool, reason: str) -> None:
    """
    機能: 不足/未知/不一致を正常0で置き換えず拒否する。
    引数: ok(bool)は条件、reason(str)は説明。
    返り値: None。不成立はValueError。
    """
    if not ok:
        raise ValueError(reason)


def decimal(value) -> Decimal:
    """
    機能: bool/非有限を拒否して保存金額を十進数へ変換する。
    引数: value(any)はJSON数値。
    返り値: Decimalは有限値。
    """
    need(type(value) in (int, float) and math.isfinite(value), "有限数値の型差")
    return Decimal(str(value))


def number(value: Decimal):
    """
    機能: 半円を丸めずJSONへ渡す。
    引数: value(Decimal)は金額。
    返り値: int又はfloatは数値。
    """
    return int(value) if value == value.to_integral_value() else float(value)


def local_inputs(catalog_path: Path, result_path: Path, limit: int = 54, artificial: bool = False) -> dict:
    """
    機能: 全Actor/場別会計から資源と全約定の費用/所有期待値を構築する。
    引数: catalog_path/result_path(Path)、limit(int)は54又は接続2、artificial(bool)は純人工だけ。
    返り値: dictは表示期待値と入力指紋。API/原板は読まない。
    """
    need(type(limit) is int and limit in (2, 54) and type(artificial) is bool, "場数/人工指定")
    catalog_path, result_path = catalog_path.resolve(), result_path.resolve()
    raw_catalog, raw_result = catalog_path.read_bytes(), result_path.read_bytes()
    catalog, result = json.loads(raw_catalog), json.loads(raw_result)
    need(result["試行"] == 94 and result["成功"] is True and result["場数"] == limit
         and result["Actor数"] == 12 and result["会計数"] == limit * 12, "94/場/Actor/会計集合")
    need(result["scope"] == ("人工" if artificial else "正式" if limit == 54 else "接続"), "scope差")
    if not artificial:
        need(result["入力前後不変"] is True and result["入力SHA256前"] == result["入力SHA256後"], "保存入力前後差")
        need(result["集計コードSHA256"] in (AGGREGATOR_SHA, AGGREGATOR_COMMENT_SHA), "固定集計コード差")
        need(result["固定54場金額照合実施"] is (limit == 54), "54金額照合scope")
    rows = {(r["session"], r["key"]): r for r in result["場別"]}
    sessions = {s for s, _ in rows}
    need(len(rows) == len(result["場別"]) == limit * 12 and len(sessions) == limit, "場別重複/不足")
    days = {s[:-4] for s in sessions if s.endswith("_Day")}
    nights = {s[:-6] for s in sessions if s.endswith("_Night")}
    need(len(days) == len(nights) == limit // 2 and days == nights
         and all("2026-09-21" <= d <= "2026-10-27" for d in days), "昼夜/既使用期間差")
    need(set(rows) == {(s, key) for s in sessions for key in KEYS} and set(result["集計"]) == set(KEYS), "12Actor全場集合")
    sums = {key: {field: Decimal(0) for field in TOTALS + ("positions", "fills")} for key in KEYS}
    expected = {}
    for (session, key), row in rows.items():
        totals, counts = row["totals"], row["counts"]
        qty = totals["entry_quantity"]
        need(type(qty) is int and qty >= 0 and type(totals["close_quantity"]) is int and totals["close_quantity"] == qty, "新規/返済枚数")
        need(all(type(counts[k]) is int and counts[k] >= 0 for k in ("positions", "fills")), "実玉/約定数")
        need(all(decimal(totals[k]) == 0 for k in ZERO_FIELDS), "期末実残/予約/未回収新規費用")
        slip = int(key.split("_")[1][1:])
        gross, fee, cost, net = (decimal(totals[k]) for k in ("gross_yen", "fee_yen", "slip_yen", "net_yen"))
        need(fee == Decimal("77") * qty and cost == 200 * slip * qty, "Actor費用条件")
        need(decimal(totals["gross_minus_fee_yen"]) == gross - fee and net == gross - fee - cost
             and decimal(totals["closed_net_yen"]) == net, "Actor3金額列")
        for field in TOTALS:
            sums[key][field] += decimal(totals[field])
        for field in ("positions", "fills"):
            sums[key][field] += counts[field]
        identity = "94_" + key + "_" + session
        expected[identity] = {"row": row, "key": key, "slip": slip, "unit_fee": Decimal("38.5") + 100 * slip, "net": number(net)}
    for key in KEYS:
        for field, amount in sums[key].items():
            need(decimal(result["集計"][key][field]) == amount, "場別/全体集計差:" + key + ":" + field)
    if not artificial and limit == 54:
        need(sums["S0_C0_D0"]["gross_yen"] == sums["S0_C5_D0"]["gross_yen"] == 2898000
             and sums["S0_C0_D0"]["net_yen"] == 2839865 and sums["S0_C5_D0"]["net_yen"] == 2084865, "S0固定3額差")
    resources = catalog["resources"]
    need(catalog["schema_version"] == 1 and catalog["path_base"] == "catalog", "catalog形式")
    need(len(resources) == len({r["id"] for r in resources}) == limit * 12
         and {r["id"] for r in resources} == set(expected), "全資源集合")
    fingerprints = {str(catalog_path): hashlib.sha256(raw_catalog).hexdigest(), str(result_path): hashlib.sha256(raw_result).hexdigest(),
                    str(Path(__file__).resolve()): BASE.sha(Path(__file__).resolve()), str(LEGACY_PATH): LEGACY_SHA, str(LEGACY.FIXED): LEGACY.FIXED_SHA}
    trades, events = {}, {}
    for resource in resources:
        e = expected[resource["id"]]
        row, key = e["row"], e["key"]
        need((resource["symbol"], resource["session"], resource["product"], resource["point_value"], resource["method_id"], resource["pnl_format"], resource["pnl_basis"])
             == ("NK225", row["session"], "NK225mini", 100, key, "trades", "net"), "Actor/商品/倍率/費用ラベル")
        need(resource["market_path"] == "NK225/" + row["session"] + "/book.jsonl.gz", "原板参照ラベル")
        path = (catalog_path.parent / resource["pnl_path"]).resolve()
        need(path.is_relative_to(catalog_path.parent), "約定path境界")
        body = path.read_bytes(); fingerprints[str(path)] = hashlib.sha256(body).hexdigest()
        saved = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
        ids, owners, state = set(), set(), {}
        entry_qty = close_qty = 0
        previous = None
        for trade in saved:
            need(isinstance(trade["id"], str) and trade["id"] and trade["id"] not in ids, "Fill ID重複/空")
            ids.add(trade["id"])
            need(trade["method_id"] == key and trade["type"] in ("LongN", "LongR", "ShortN", "ShortR"), "約定Actor/種類")
            pid, qty = trade["position_id"], trade["qty"]
            need(isinstance(pid, str) and pid and type(qty) is int and qty > 0 and decimal(trade["price"]) > 0, "実所有/量/価格")
            need(type(trade["source_line"]) is int and trade["source_line"] > 0, "物理行")
            stamp = datetime.fromisoformat(trade["timestamp"])
            need(stamp.utcoffset() is not None and stamp.utcoffset() == timedelta(hours=9)
                 and (previous is None or stamp >= previous), "時差/時刻逆順")
            previous = stamp
            need(decimal(trade["fee_yen"]) == e["unit_fee"] * qty, "片道半円費用/滑り二重控除")
            side = 1 if trade["type"].startswith("Long") else -1
            if trade["type"].endswith("N"):
                need(pid not in owners, "新規所有再利用")
                owners.add(pid); state[pid] = [side, qty]; entry_qty += qty
            else:
                need(pid in state and state[pid][0] == side and qty <= state[pid][1], "返済所有/量")
                state[pid][1] -= qty; close_qty += qty
            need(all(sum(v[1] for v in state.values() if v[0] == s) <= 10 for s in (-1, 1)), "表示実所有の片側上限")
        need(all(v[1] == 0 for v in state.values()), "表示終了所有0")
        need(entry_qty == close_qty == row["totals"]["entry_quantity"] and len(owners) == row["counts"]["positions"]
             and len(saved) == row["counts"]["fills"], "保存約定/枚数/実玉数")
        calculated = BASE.trade_expectations(saved, 100)
        need(sum((decimal(t["realized_delta_yen"]) for t in calculated), Decimal(0)) == decimal(e["net"]), "表示独立純額")
        trades[resource["id"]], events[resource["id"]] = saved, calculated
    return {"catalog": catalog, "result": result, "resources": resources, "expected": expected,
            "trades": trades, "events": events, "入力SHA256": fingerprints}


def run(catalog_path: Path, result_path: Path, url: str = "http://127.0.0.1:8092", workers: int = 8,
        transport=None, progress: bool = True, limit: int = 54, artificial: bool = False) -> dict:
    """
    機能: 明示された既存Viewerへ全資源/全約定/最終所有0と半円純額を結合する。
    引数: catalog_path/result_path(Path)、url(str)、workers(int)、transport(callable|None)、progress(bool)、limit(int)、artificial(bool)。
    返り値: dictは差/未完/入力前後不変。プロセス起動/停止/設定変更はしない。
    """
    need(url.rstrip("/") in ("http://127.0.0.1:8092", "http://localhost:8092")
         and type(workers) is int and 1 <= workers <= 8, "既存8092/並列1〜8")
    need(not artificial or transport is not None, "人工に実HTTPを使わない")
    catalog_path, result_path = catalog_path.resolve(), result_path.resolve()
    local = local_inputs(catalog_path, result_path, limit, artificial)
    base, request = url.rstrip("/"), BASE.fetch_json if transport is None else transport
    audit, rows, errors, info = BASE.Audit(), [], [], None
    try:
        info, _, _ = request("GET", base + "/api/info")
        root = Path(info["resource_root"]).resolve()
        need(catalog_path.is_relative_to(root), "一覧はresource_root内")
        loaded, _, _ = request("POST", base + "/api/catalogs/load", {"path": str(catalog_path.relative_to(root))})
        resolved = {r["id"]: r for r in loaded["resources"]}
        need(len(resolved) == len(loaded["resources"]) == limit * 12 and set(resolved) == set(local["expected"]), "API全資源集合")
        need(Path(loaded["path"]).resolve() == catalog_path, "API一覧path")
        tasks = []
        for resource in local["resources"]:
            target = {**resource, "pnl_path": str((catalog_path.parent / resource["pnl_path"]).resolve()),
                      "market_path": str((Path(info["data_root"]) / resource["market_path"]).resolve())}
            need(resolved[resource["id"]] == target, "API資源メタ差:" + resource["id"])
            query = urlencode({"catalog": loaded["catalog_id"], "resource": resource["id"], "width": 1, "interval": "raw", "price": "last"})
            tasks.append((base + "/api/data?" + query, target, local["events"][resource["id"]], local["expected"][resource["id"]]["net"], catalog_path))
        with ThreadPoolExecutor(workers) as pool:
            pending = [pool.submit(LEGACY.check_one, task, request) for task in tasks]
            for future in as_completed(pending):
                row = future.result(); row["費用基準"] = row["id"].split("_")[2]
                rows.append(row)
                if progress and len(rows) % 54 == 0:
                    print(f"表示監査 {len(rows)}/{limit * 12}", flush=True)
    except BASE.ViewerError as error:
        errors.append({"種類": error.kind, "URL": error.url, "説明": str(error)[:1000]})
    except (ValueError, AssertionError, KeyError, TypeError) as error:
        errors.append({"種類": "一覧schema又は結合", "説明": str(error)[:1000]})
    rows.sort(key=lambda row: row["id"])
    before = local["入力SHA256"]; after = {p: BASE.sha(Path(p)) for p in before}
    audit.check("入力とコードの前後不変", after, before)
    errors += [{"id": row["id"], "詳細": row["APIエラー"]} for row in rows if row["APIエラー"]]
    differences = audit.bad + sum(row["不一致数"] for row in rows)
    complete = len(rows) == limit * 12 and all(row["完了"] for row in rows) and not errors
    return {"試行": 94, "成功": complete and differences == 0 and before == after, "成功の範囲": "Viewer保存会計一致",
            "scope": "人工" if artificial else "正式" if limit == 54 else "接続", "予定資源": limit * 12,
            "完了資源": sum(row["完了"] for row in rows), "全資源検証完了": complete,
            "照合項目数": audit.count + sum(row["照合項目数"] for row in rows), "不一致数": differences,
            "共通不一致": audit.examples, "APIエラー": errors, "資源": rows, "Viewer設定": info,
            "入力不変": before == after, "入力SHA256前": before, "入力SHA256後": after,
            "一覧SHA256": before[str(catalog_path)], "結果SHA256": before[str(result_path)],
            "監査コードSHA256": BASE.sha(Path(__file__)), "固定93部品SHA256": LEGACY_SHA, "固定80部品SHA256": LEGACY.FIXED_SHA,
            "Viewer停止/再起動/設定変更": 0, "新売買再生": 0, "原板直接読取": 0, "API本文複写": 0,
            "限定": "表示の全約定/所有/費用と保存純額の一致。MTM DD/Source生成/原板価格対応/mini実執行の証明ではない。"}


def self_test() -> dict:
    """
    機能: 架空54場648資源の買売/部分/半円とAPI破損を通信代替で検査する。
    引数: なし。実一覧/実市場/原板/Viewer APIは読まない。
    返り値: dictは純人工の証拠。
    """
    with tempfile.TemporaryDirectory(prefix="94表示人工_", dir=ROOT / "work") as directory:
        temp = Path(directory).resolve()
        need(temp.is_relative_to((ROOT / "work").resolve()), "人工保存先")
        rows, resources, by_resource = [], [], {}
        groups = {key: {field: 0 for field in TOTALS + ("positions", "fills")} for key in KEYS}
        for day in range(27):
            date = (datetime(2026, 9, 21) + timedelta(days=day)).date().isoformat()
            for kind in ("Day", "Night"):
                session = date + "_" + kind
                for key in KEYS:
                    slip = int(key.split("_")[1][1:]); fee = 38.5 + 100 * slip
                    empty = day == 0 and kind == "Day" and key == KEYS[0]
                    totals = {"entry_quantity": 0 if empty else 3, "close_quantity": 0 if empty else 3,
                              "gross_yen": 0 if empty else 5000, "fee_yen": 0 if empty else 231,
                              "slip_yen": 0 if empty else 600 * slip, "gross_minus_fee_yen": 0 if empty else 4769,
                              "net_yen": 0 if empty else 4769 - 600 * slip,
                              **{name: 0 for name in ZERO_FIELDS}}
                    totals["closed_net_yen"] = totals["net_yen"]
                    counts = {"positions": 0 if empty else 1, "fills": 0 if empty else 3}
                    rows.append({"session": session, "key": key, "totals": totals, "counts": counts})
                    for field in TOTALS: groups[key][field] += totals[field]
                    for field in counts: groups[key][field] += counts[field]
                    rid = "94_" + key + "_" + session
                    side = 1 if day % 2 == 0 else -1
                    at = datetime.fromisoformat(date + ("T09:00:00+09:00" if kind == "Day" else "T18:00:00+09:00"))
                    trades = [] if empty else [{"id": rid + "_F" + str(i), "timestamp": (at + timedelta(seconds=i)).isoformat(),
                              "type": ("Long" if side == 1 else "Short") + ("N" if i == 0 else "R"),
                              "position_id": rid + "_P", "price": price, "qty": qty, "fee_yen": fee * qty,
                              "method_id": key, "source_line": 10 + i}
                              for i, (price, qty) in enumerate(((1000, 3), (1000 + side * 30, 1), (1000 + side * 10, 2)))]
                    path = temp / (rid + ".trades.jsonl")
                    path.write_text("".join(json.dumps(t) + "\n" for t in trades), encoding="utf-8")
                    resources.append({"id": rid, "title": "人工", "symbol": "NK225", "session": session, "product": "NK225mini",
                                      "method_id": key, "point_value": 100, "pnl_format": "trades", "pnl_basis": "net",
                                      "pnl_path": path.name, "market_path": "NK225/" + session + "/book.jsonl.gz"})
                    by_resource[rid] = trades
        catalog_path, result_path = temp / "一覧.resources.json", temp / "結果.json"
        catalog = {"schema_version": 1, "path_base": "catalog", "resources": resources}
        result = {"試行": 94, "成功": True, "scope": "人工", "場数": 54, "Actor数": 12, "会計数": 648, "集計": groups, "場別": rows}
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        result_path.write_text(json.dumps(result), encoding="utf-8")
        resolved = {r["id"]: {**r, "pnl_path": str(temp / r["pnl_path"]), "market_path": str(temp / "市場" / r["market_path"])} for r in resources}

        def fake(method: str, url: str, payload=None):
            """
            機能: 固定80が期待するAPI応答を純人工で生成する。
            引数: method/url(str)、payload(dict|None)は通信形の依頼。
            返り値: tupleは値/bytes/ヘッダ。HTTPは使わない。
            """
            if url.endswith("/api/info"):
                value = {"resource_root": str(temp), "data_root": str(temp / "市場"), "listen": "127.0.0.1:8092"}
            elif url.endswith("/api/catalogs/load"):
                need(method == "POST" and payload == {"path": catalog_path.name}, "人工一覧依頼")
                value = {"catalog_id": "人工648", "path": str(catalog_path), "resources": list(resolved.values())}
            else:
                rid = parse_qs(urlparse(url).query)["resource"][0]
                events = BASE.trade_expectations(by_resource[rid], 100)
                net = number(sum((decimal(e["realized_delta_yen"]) for e in events), Decimal(0)))
                value = {"resource": resolved[rid], "summary": {"long_qty": 0, "short_qty": 0, "realized_pnl_yen": net, "unrealized_pnl_yen": 0},
                         "state_columns": ["long_qty", "short_qty", "realized_pnl_yen", "unrealized_pnl_yen"], "states": [[0, 0, net, 0]],
                         "events": events, "files": {"pnl": resolved[rid]["pnl_path"], "market": resolved[rid]["market_path"], "catalog": str(catalog_path)}}
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            return value, raw, {"x-chart-data-sha256": hashlib.sha256(raw).hexdigest()}

        prepared = local_inputs(catalog_path, result_path, artificial=True)
        for cost, wanted in (("C0", [-115.5, 2961.5, 1923]), ("C5", [-1615.5, 2461.5, 923])):
            rid = next(r["id"] for r in resources if cost in r["method_id"] and by_resource[r["id"]])
            need([e["realized_delta_yen"] for e in prepared["events"][rid]] == wanted, "半円/partial手計算:" + cost)
        good = run(catalog_path, result_path, transport=fake, workers=4, progress=False, artificial=True)
        need(good["成功"] and good["完了資源"] == 648, "648正常人工")
        checks = ["648資源/12Actor/買売/partial/半円/無取引0/最終所有0", "C0/C5半円片の手計算"]
        for corruption in ("半円増減", "最終所有未知", "終状態数量", "倍率", "本文SHA", "資源欠落", "通信未完"):
            def damaged(method: str, url: str, payload=None):
                """
                機能: 1種類のAPI破損だけを純人工へ注入する。
                引数: method/url(str)、payload(dict|None)は依頼。
                返り値: tupleは破損応答。通信未完は固定例外。
                """
                if corruption == "通信未完" and "/api/data?" in url:
                    raise BASE.ViewerError("通信", url, "人工未完")
                value, _, _ = fake(method, url, payload)
                if url.endswith("/api/catalogs/load") and corruption == "資源欠落": value["resources"] = value["resources"][:-1]
                if "/api/data?" in url:
                    if corruption == "半円増減" and value["events"]: value["events"][0]["realized_delta_yen"] += .5
                    elif corruption == "最終所有未知": value["summary"]["long_qty"] = None
                    elif corruption == "終状態数量": value["states"][-1][1] = 1
                    elif corruption == "倍率": value["resource"] = {**value["resource"], "point_value": 10}
                raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
                return value, raw, {"x-chart-data-sha256": "破損" if corruption == "本文SHA" else hashlib.sha256(raw).hexdigest()}
            bad = run(catalog_path, result_path, transport=damaged, workers=4, progress=False, artificial=True)
            need(not bad["成功"], "API破損の成功化:" + corruption)
            checks.append(corruption + "拒否")
        resource = next(r for r in resources if by_resource[r["id"]])
        path = temp / resource["pnl_path"]; original = path.read_bytes()
        trades = [json.loads(line) for line in original.decode().splitlines()]
        trades[0]["fee_yen"] += .5
        path.write_text("".join(json.dumps(t) + "\n" for t in trades), encoding="utf-8")
        try:
            local_inputs(catalog_path, result_path, artificial=True)
        except ValueError:
            checks.append("ローカル半円費用の破壊をAPI前に拒否")
        else:
            raise AssertionError("ローカル費用破損を受理")
        path.write_bytes(original)
        return {"成功": True, "正常資源": 648, "正常照合項目": good["照合項目数"], "人工項目": checks,
                "固定93部品SHA256": LEGACY_SHA, "固定80部品SHA256": LEGACY.FIXED_SHA,
                "監査コードSHA256": BASE.sha(Path(__file__)), "実API取得": 0, "実カタログ登録": 0, "市場/原板読取": 0}


def main() -> None:
    """
    機能: 人工又は明示されたViewer監査を実行し、新規証拠へ保存する。
    引数: --self-test/--run、--catalog/--result/--out(Path)、--limit(int)、--url(str)、--workers(int)。
    返り値: None。未完/不一致は非0。サーバの停止/再起動/設定変更はしない。
    """
    parser = argparse.ArgumentParser(description="94個別追尾の648Viewer保存数値照合")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true"); mode.add_argument("--run", action="store_true")
    for name in ("catalog", "result", "out"): parser.add_argument("--" + name, type=Path, required=name == "out")
    parser.add_argument("--limit", type=int, choices=(2, 54), default=54)
    parser.add_argument("--url", default="http://127.0.0.1:8092"); parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    need(not args.out.exists(), "出力先は新規")
    if args.self_test:
        need(args.catalog is None and args.result is None, "人工で実入力を指定しない")
        value = self_test()
    else:
        need(args.catalog is not None and args.result is not None, "一覧/結果を明示")
        value = run(args.catalog, args.result, args.url, args.workers, limit=args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "正常資源", "完了資源", "照合項目数", "不一致数") if k in value}, ensure_ascii=False))
    if not value["成功"]: raise SystemExit(1)


if __name__ == "__main__":
    main()
