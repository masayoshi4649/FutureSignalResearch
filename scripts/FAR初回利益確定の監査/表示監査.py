"""固定96の表示比較をSHA参照し、97の16口座・864資源を保存会計へ結ぶ。"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
FIXED96 = ROOT / "scripts/FAR5分枠の技法判定の監査/表示監査.py"
FIXED96_SHA = "4e2f937ee25267ae9ce39df35444f50a5aca7edb5faf7c7f45155539b127ce30"
if hashlib.sha256(FIXED96.read_bytes()).hexdigest() != FIXED96_SHA:
    raise ValueError("固定96表示部品のSHA差")
SPEC = importlib.util.spec_from_file_location("固定96表示比較97", FIXED96)
F96 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F96)
OLD, BASE, LEGACY = F96.OLD, F96.BASE, F96.LEGACY
need, decimal, number = F96.need, F96.decimal, F96.number
AGG_SHA = "09e93302080a740d3c2add85297f9530c32f6235dabe5f08e674551b556b3208"
CONDITION_SHA = "f7421f26a306eb0a49387b9dfa2104621350fac5c6ceba035a84bb3661d42c05"
COMPLETION_SHA = "ee4071decdc6bcab5af1b061b49d9a6aa74b53a901b9f3b878edc049112a384f"
INDEPENDENT_SHA = "96b2a29aa08c3a0ca4b97b57449a4f6d6b4fcf017d6306eabb5c57d1d42e1e4d"
PROOF96_SHA = "33deeae84c68de0ecce21023e95732db22a658c9a832cb456d446e221276d483"
KEYS = tuple(h + g + f"B5Q_P0_C{c}_D{d}" for g in ("", "AB_") for h in ("", "H0_") for c in (0, 5) for d in (0, 1))


def key_config(key: str) -> tuple:
    """明示16keyを入口・出口・費用・遅延へ分ける。

    引数: key(str)は97Actor名。
    返り値: tuple[str,str,int,int]はG0/AB、P0/H0、滑り、遅延。
    """
    need(key in KEYS, "97表示Actor key")
    harvest = "H0" if key.startswith("H0_") else "P0"
    base = key.removeprefix("H0_")
    gate = "AB" if base.startswith("AB_") else "G0"
    tail = key.split("_")
    return gate, harvest, int(tail[-2][1:]), int(tail[-1][1:])


def component_hashes() -> dict:
    """再用した表示比較部品の現物指紋を列挙する。

    引数: なし。
    返り値: dict[str,str]は新監査と固定96/95/94/93/共通部のSHA。
    """
    paths = [Path(__file__).resolve(), FIXED96, Path(F96.FIXED95), Path(F96.FIXED), Path(OLD.LEGACY_PATH), Path(BASE.__file__)]
    return {str(p.resolve()): BASE.sha(p) for p in paths}


def scene_set(limit: int) -> set:
    """固定54場又は人工の先頭2場を定義する。

    引数: limit(int)は2/54。
    返り値: set[str]は9/21〜10/27平日のDay/Night。原板は読まない。
    """
    days, current = [], date(2026, 9, 21)
    while current <= date(2026, 10, 27):
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    need(len(days) == 27, "固定27日")
    return {d + "_" + kind for d in days[:limit // 2] for kind in ("Day", "Night")}


def local_inputs(catalog_path: Path, result_path: Path, limit: int = 54, artificial: bool = False) -> dict:
    """保存16口座の費用・所有・全約定を固定表示比較へ渡す。

    引数: catalog_path/result_path(Path)は一覧/保存結果、limit(int)、artificial(bool)は通信代替専用。
    返り値: dictは期待資源・約定・純額・入力SHA。金融/Source/原板を再生しない。
    """
    need(type(limit) is int and limit in (2, 54) and type(artificial) is bool, "場数/人工型")
    need(artificial or limit == 54, "97正式表示は54場、2場は人工専用")
    catalog_path, result_path = catalog_path.resolve(), result_path.resolve()
    cb, rb = catalog_path.read_bytes(), result_path.read_bytes()
    catalog, result = json.loads(cb), json.loads(rb)
    need(result["試行"] == 97 and result["成功"] is True and result["場数"] == limit and result["Actor数"] == 16 and result["会計数"] == limit * 16, "97保存会計集合")
    need(result["scope"] == ("人工" if artificial else "正式"), "97保存scope")
    if not artificial:
        need((result["集計コードSHA256"], result["条件SHA256"], result["完了SHA256"], result["独立Tape金融監査SHA256"]) == (AGG_SHA, CONDITION_SHA, COMPLETION_SHA, INDEPENDENT_SHA), "97保存/条件/完了/独立指紋")
        dependencies = result["入力依存SHA256前後"]
        need(isinstance(dependencies, dict) and dependencies and all(isinstance(p, str) and isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v) for p, v in dependencies.items()), "保存入力依存指紋")
        need({AGG_SHA, CONDITION_SHA, COMPLETION_SHA, INDEPENDENT_SHA, PROOF96_SHA} <= set(dependencies.values()), "保存側の依存proof結合")
        matches = result["P0旧96全文対照"]
        need(len(matches) == limit and {r["session"] for r in matches} == scene_set(limit) and all(r["対照会計"] == 8 and r["除外"] == [] and isinstance(r["固定96保存SHA256"], str) and len(r["固定96保存SHA256"]) == 64 for r in matches), "P0固定96全8会計の保存証拠")
    rows = {(r["session"], r["key"]): r for r in result["場別"]}
    sessions = scene_set(limit)
    need(len(rows) == len(result["場別"]) == limit * 16 and set(rows) == {(s, k) for s in sessions for k in KEYS}, "97全場Actor一意")
    need(set(result["集計"]) == set(result["Actor設定"]) == set(KEYS), "97設定/集計key集合")
    sums = {key: {field: Decimal(0) for field in OLD.TOTALS + ("positions", "fills")} for key in KEYS}
    expected = {}
    for (session, key), row in rows.items():
        gate, exit_policy, slip, delay = key_config(key)
        need(result["Actor設定"][key] == {"入口": gate, "出口": exit_policy, "共通基本保護": "P0", "slip_pts": slip, "delay_seconds": delay}, "97入口/収穫/共通P0設定")
        totals, counts = row["totals"], row["counts"]
        qty = totals["entry_quantity"]
        need(type(qty) is int and qty >= 0 and type(totals["close_quantity"]) is int and totals["close_quantity"] == qty, "実新規/返済量")
        need(all(type(counts[n]) is int and counts[n] >= 0 for n in ("positions", "fills")), "実玉/約定数")
        need(all(decimal(totals[n]) == 0 for n in OLD.ZERO_FIELDS), "終所有/予約/未回収費用0")
        gross, fee, slip_yen, net = (decimal(totals[n]) for n in ("gross_yen", "fee_yen", "slip_yen", "net_yen"))
        need(fee == 77 * qty and slip_yen == 200 * slip * qty and decimal(totals["gross_minus_fee_yen"]) == gross - fee and net == gross - fee - slip_yen and decimal(totals["closed_net_yen"]) == net, "97指定手数料/仮定滑り/純額")
        for field in OLD.TOTALS:
            sums[key][field] += decimal(totals[field])
        for field in ("positions", "fills"):
            sums[key][field] += counts[field]
        rid = "97_" + key + "_" + session
        expected[rid] = {"row": row, "key": key, "unit_fee": Decimal("38.5") + 100 * slip, "net": number(net)}
    for key in KEYS:
        for field, amount in sums[key].items():
            need(decimal(result["集計"][key][field]) == amount, "97場別/全体加算")
    resources = catalog["resources"]
    need(catalog["schema_version"] == 1 and catalog["path_base"] == "catalog" and len(resources) == len({r["id"] for r in resources}) == limit * 16 and {r["id"] for r in resources} == set(expected), "97全資源集合")
    hashes = {str(catalog_path): hashlib.sha256(cb).hexdigest(), str(result_path): hashlib.sha256(rb).hexdigest(), **component_hashes()}
    trades, events = {}, {}
    for resource in resources:
        e = expected[resource["id"]]
        row, key = e["row"], e["key"]
        need((resource["symbol"], resource["session"], resource["product"], resource["method_id"], resource["point_value"], resource["pnl_format"], resource["pnl_basis"]) == ("NK225", row["session"], "NK225mini", key, 100, "trades", "net"), "97資源ラベル")
        need(resource["title"] == "初回利益確定 " + key + " " + row["session"], "97H0識別title")
        need(resource["market_path"] == "NK225/" + row["session"] + "/book.jsonl.gz", "市場参照ラベル")
        need(resource["pnl_path"] == resource["id"] + ".trades.jsonl", "約定ファイルID結合")
        path = (catalog_path.parent / resource["pnl_path"]).resolve()
        need(path.is_relative_to(catalog_path.parent), "約定参照境界")
        body = path.read_bytes()
        hashes[str(path)] = hashlib.sha256(body).hexdigest()
        saved = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
        seen, owners, entry, close, previous = set(), {}, 0, 0, None
        for trade in saved:
            need(isinstance(trade["id"], str) and trade["id"] and trade["id"] not in seen, "Fill ID一意")
            seen.add(trade["id"])
            need(trade["method_id"] == key and trade["type"] in ("LongN", "LongR", "ShortN", "ShortR"), "約定key/種類")
            pid, qty = trade["position_id"], trade["qty"]
            need(isinstance(pid, str) and pid and type(qty) is int and qty > 0 and decimal(trade["price"]) > 0, "実所有/数量/価格")
            need(type(trade["source_line"]) is int and trade["source_line"] > 0, "実物理行")
            stamp = datetime.fromisoformat(trade["timestamp"])
            point = stamp, trade["source_line"]
            need(stamp.utcoffset() == timedelta(hours=9) and (previous is None or previous <= point), "約定時計/同時刻物理行")
            previous = point
            need(decimal(trade["fee_yen"]) == e["unit_fee"] * qty, "C0/C5片道半円費用")
            side = 1 if trade["type"].startswith("Long") else -1
            if trade["type"].endswith("N"):
                need(pid not in owners, "実新規ID再利用")
                owners[pid] = [side, qty]
                entry += qty
            else:
                need(pid in owners and owners[pid][0] == side and qty <= owners[pid][1], "partial返済所有")
                owners[pid][1] -= qty
                close += qty
            need(all(sum(v[1] for v in owners.values() if v[0] == s) <= 10 for s in (-1, 1)), "表示実所有各側10")
        need(entry == close == row["totals"]["entry_quantity"] and len(owners) == row["counts"]["positions"] and len(saved) == row["counts"]["fills"] and all(v[1] == 0 for v in owners.values()), "表示量/件数/終0")
        calculated = BASE.trade_expectations(saved, 100)
        need(sum((decimal(v["realized_delta_yen"]) for v in calculated), Decimal(0)) == decimal(e["net"]), "Viewer全片の独立純額")
        trades[resource["id"]], events[resource["id"]] = saved, calculated
    return {"catalog": catalog, "result": result, "resources": resources, "expected": expected, "trades": trades, "events": events, "入力SHA256": hashes}


def run(catalog_path: Path, result_path: Path, url: str = "http://127.0.0.1:8092", workers: int = 8, transport=None, progress: bool = True, limit: int = 54, artificial: bool = False) -> dict:
    """固定96のAPI比較本文を独立した名前空間から再用する。

    引数: 一覧/保存結果(Path)、既存url(str)、workers(int)、transport(人工callable|None)、progress/人工(bool)、limit(int)。
    返り値: dictは全資源の表示差/通信失敗。プロセスや設定は操作しない。
    """
    need(type(artificial) is bool, "人工scope bool")
    namespace = dict(F96.__dict__, local_inputs=local_inputs, KEYS=KEYS)
    runner = types.FunctionType(F96._run_fixed.__code__, namespace, argdefs=F96._run_fixed.__defaults__)
    result = runner(catalog_path, result_path, url, workers, transport, progress, limit, artificial)
    result.update({"試行": 97, "監査コードSHA256": BASE.sha(Path(__file__)), "固定96部品SHA256": FIXED96_SHA, "固定95部品SHA256": F96.FIXED95_SHA, "固定94部品SHA256": F96.FIXED_SHA, "全再用部品SHA256": component_hashes(), "保存約定の会計検算": True, "実Source生成": 0})
    ids = {r["id"]: r["method_id"] for r in json.loads(catalog_path.read_text(encoding="utf-8"))["resources"]}
    for row in result["資源"]:
        key = ids[row["id"]]
        gate, exit_policy, slip, delay = key_config(key)
        row.update(Actor=key, EntryGate=gate, GatePolicy="" if gate == "G0" else gate, HarvestPolicy="H0" if exit_policy == "H0" else "", ExitPolicy=exit_policy, EntryTiming="B5Q", 費用基準="C" + str(slip), 約定遅延秒=delay)
    return result


def prepare_local(catalog_path: Path, result_path: Path) -> dict:
    """Viewer接続前に保存864資源だけを検査する。

    引数: catalog_path/result_path(Path)は正式97の一覧/結果。
    返り値: dictは準備範囲の入力不変証拠。API表示成功は含めない。
    """
    local = local_inputs(catalog_path, result_path)
    before = local["入力SHA256"]
    after = {path: BASE.sha(Path(path)) for path in before}
    return {"試行": 97, "成功": before == after, "scope": "保存準備・HTTPなし", "予定資源": 864,
            "保存準備資源": len(local["resources"]), "表示比較予定約定片数": sum(len(v) for v in local["trades"].values()),
            "入力不変": before == after, "入力SHA256前": before, "入力SHA256後": after,
            "一覧SHA256": before[str(catalog_path.resolve())], "結果SHA256": before[str(result_path.resolve())],
            "監査コードSHA256": BASE.sha(Path(__file__)), "実API": 0, "原板/Source/金融再生": 0,
            "限定": "保存値の事前結合。Viewer表示成功/864API回収を主張しない。"}


def self_test() -> dict:
    """人工約定の保存形式とAPI差検出だけを確認する。

    引数: なし。実API/Source/Native金融/原板は使わない。
    返り値: dictは32資源の通信代替と破損拒否。戦略成績ではない。
    """
    with tempfile.TemporaryDirectory(prefix="97表示人工_", dir=ROOT / "work") as name:
        temp = Path(name).resolve()
        resources, rows, trades = [], [], {}
        groups = {key: {field: 0 for field in OLD.TOTALS + ("positions", "fills")} for key in KEYS}
        for kind in ("Day", "Night"):
            session = "2026-09-21_" + kind
            for key in KEYS:
                gate, exit_policy, slip, delay = key_config(key)
                zero = kind == "Day" and key == "H0_AB_B5Q_P0_C5_D1"
                qty, gross = (0, 0) if zero else (3, 5000)
                totals = {"entry_quantity": qty, "close_quantity": qty, "gross_yen": gross, "fee_yen": qty * 77, "slip_yen": qty * 200 * slip, "gross_minus_fee_yen": gross - qty * 77, "net_yen": gross - qty * (77 + 200 * slip), **{field: 0 for field in OLD.ZERO_FIELDS}}
                totals["closed_net_yen"] = totals["net_yen"]
                counts = {"positions": int(not zero), "fills": 0 if zero else 3}
                rows.append({"session": session, "key": key, "totals": totals, "counts": counts})
                for field in OLD.TOTALS:
                    groups[key][field] += totals[field]
                for field in counts:
                    groups[key][field] += counts[field]
                rid, side = "97_" + key + "_" + session, 1 if kind == "Day" else -1
                at = datetime.fromisoformat("2026-09-21" + ("T09:20:00+09:00" if kind == "Day" else "T18:00:00+09:00"))
                saved = [] if zero else [{"id": rid + "-F" + str(i), "timestamp": (at + timedelta(seconds=i)).isoformat(), "type": ("Long" if side == 1 else "Short") + ("N" if i == 0 else "R"), "position_id": rid + "-P", "price": price, "qty": amount, "fee_yen": (38.5 + 100 * slip) * amount, "method_id": key, "source_line": 10 + i} for i, (price, amount) in enumerate(((1000, 3), (1000 + side * 30, 1), (1000 + side * 10, 2)))]
                (temp / (rid + ".trades.jsonl")).write_text("".join(json.dumps(r) + "\n" for r in saved), encoding="utf-8")
                trades[rid] = saved
                resources.append({"id": rid, "title": "初回利益確定 " + key + " " + session, "symbol": "NK225", "product": "NK225mini", "session": session, "method_id": key, "point_value": 100, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": rid + ".trades.jsonl", "market_path": "NK225/" + session + "/book.jsonl.gz"})
        result = {"試行": 97, "成功": True, "scope": "人工", "場数": 2, "Actor数": 16, "会計数": 32, "集計": groups, "場別": rows, "Actor設定": {key: {"入口": key_config(key)[0], "出口": key_config(key)[1], "共通基本保護": "P0", "slip_pts": key_config(key)[2], "delay_seconds": key_config(key)[3]} for key in KEYS}}
        catalog_path, result_path = temp / "一覧.resources.json", temp / "結果.json"
        catalog_path.write_text(json.dumps({"schema_version": 1, "path_base": "catalog", "resources": resources}), encoding="utf-8")
        result_path.write_text(json.dumps(result), encoding="utf-8")
        resolved = {r["id"]: {**r, "pnl_path": str(temp / r["pnl_path"]), "market_path": str(temp / "市場" / r["market_path"])} for r in resources}

        def fake(method, url, payload=None):
            """Viewerと同じ応答形を人工約定から返す。

            引数: method/url(str)、payload(dict|None)は固定runnerの通信引数。
            返り値: tupleはJSON/本文/SHAヘッダ。実HTTPは使わない。
            """
            if url.endswith("/api/info"):
                value = {"resource_root": str(temp), "data_root": str(temp / "市場"), "listen": "127.0.0.1:8092"}
            elif url.endswith("/api/catalogs/load"):
                value = {"catalog_id": "人工97", "path": str(catalog_path), "resources": list(resolved.values())}
            else:
                rid = parse_qs(urlparse(url).query)["resource"][0]
                events = BASE.trade_expectations(trades[rid], 100)
                net = sum(e["realized_delta_yen"] for e in events)
                value = {"resource": resolved[rid], "summary": {"long_qty": 0, "short_qty": 0, "realized_pnl_yen": net, "unrealized_pnl_yen": 0}, "state_columns": ["long_qty", "short_qty", "realized_pnl_yen", "unrealized_pnl_yen"], "states": [[0, 0, net, 0]], "events": events, "files": {"pnl": resolved[rid]["pnl_path"], "market": resolved[rid]["market_path"], "catalog": str(catalog_path)}}
            raw = json.dumps(value).encode()
            return value, raw, {"x-chart-data-sha256": hashlib.sha256(raw).hexdigest()}

        prepared = local_inputs(catalog_path, result_path, 2, True)
        for marker, wanted in (("_C0_", [-115.5, 2961.5, 1923]), ("_C5_", [-1615.5, 2461.5, 923])):
            rid = next(r["id"] for r in resources if "H0_" in r["id"] and marker in r["method_id"] and trades[r["id"]])
            need([e["realized_delta_yen"] for e in prepared["events"][rid]] == wanted, "partial/半円の手計算")
        good = run(catalog_path, result_path, transport=fake, workers=2, progress=False, limit=2, artificial=True)
        need(good["成功"] and good["完了資源"] == 32 and good["不一致数"] == 0, "32正常人工")
        detected = []
        for corruption in ("fee半円", "数量", "H0ラベル", "返済所有", "終0未知", "本文SHA", "通信未完", "約定欠落", "資源欠落"):
            def bad(method, url, payload=None):
                """APIへ一つだけ破損を注入する。

                引数: method/url(str)、payload(dict|None)は通信引数。
                返り値: tupleは破損応答。通信未完は固定例外。
                """
                if corruption == "通信未完" and "/api/data?" in url:
                    raise BASE.ViewerError("通信", url, "人工未完")
                value, _, _ = fake(method, url, payload)
                if "/api/data?" in url:
                    if corruption == "fee半円" and value["events"]:
                        value["events"][0]["realized_delta_yen"] += .5
                    elif corruption == "数量" and value["events"]:
                        value["events"][0]["qty"] += 1
                    elif corruption == "H0ラベル":
                        value["resource"] = {**value["resource"], "method_id": "不正P0"}
                    elif corruption == "返済所有" and len(value["events"]) > 1:
                        value["events"][1]["position_id"] = "別玉"
                    elif corruption == "終0未知":
                        value["summary"]["long_qty"] = None
                    elif corruption == "約定欠落" and value["events"]:
                        value["events"].pop()
                elif corruption == "資源欠落" and url.endswith("/api/catalogs/load"):
                    value["resources"].pop()
                raw = json.dumps(value).encode()
                return value, raw, {"x-chart-data-sha256": "破損" if corruption == "本文SHA" else hashlib.sha256(raw).hexdigest()}
            need(not run(catalog_path, result_path, transport=bad, workers=2, progress=False, limit=2, artificial=True)["成功"], "API破損見逃し:" + corruption)
            detected.append("API " + corruption)
        original_catalog, original_result = catalog_path.read_bytes(), result_path.read_bytes()
        resource = next(r for r in resources if trades[r["id"]])
        trade_path = temp / resource["pnl_path"]
        original_trade = trade_path.read_bytes()
        for corruption in ("fee半円", "数量", "返済所有", "qty真偽値", "非有限価格", "時計逆順", "H0title", "H0設定", "不明key", "scope不明", "資源重複", "終所有未知", "資源欠落"):
            broken_catalog, broken_result = json.loads(original_catalog), json.loads(original_result)
            changed = [json.loads(line) for line in original_trade.decode().splitlines()]
            if corruption == "fee半円": changed[0]["fee_yen"] += .5
            elif corruption == "数量": changed[0]["qty"] += 1
            elif corruption == "返済所有": changed[1]["position_id"] = "別玉"
            elif corruption == "qty真偽値": changed[0]["qty"] = True
            elif corruption == "非有限価格": changed[0]["price"] = float("nan")
            elif corruption == "時計逆順": changed[1]["timestamp"] = "2026-09-21T09:19:00+09:00"
            elif corruption == "H0title": broken_catalog["resources"][0]["title"] = "不正"
            elif corruption == "H0設定": broken_result["Actor設定"]["H0_B5Q_P0_C0_D0"]["出口"] = "P0"
            elif corruption == "不明key": broken_result["場別"][0]["key"] = "不明"
            elif corruption == "scope不明": broken_result["scope"] = None
            elif corruption == "資源重複": broken_catalog["resources"][1] = broken_catalog["resources"][0]
            elif corruption == "終所有未知": broken_result["場別"][0]["totals"]["open_buy"] = None
            elif corruption == "資源欠落": broken_catalog["resources"].pop()
            catalog_path.write_text(json.dumps(broken_catalog), encoding="utf-8")
            result_path.write_text(json.dumps(broken_result), encoding="utf-8")
            trade_path.write_text("".join(json.dumps(row) + "\n" for row in changed), encoding="utf-8")
            try:
                local_inputs(catalog_path, result_path, 2, True)
            except (ValueError, AssertionError, KeyError, TypeError):
                detected.append("local " + corruption)
            else:
                raise AssertionError("local破損通過:" + corruption)
            catalog_path.write_bytes(original_catalog)
            result_path.write_bytes(original_result)
            trade_path.write_bytes(original_trade)
        return {"試行": 97, "成功": True, "scope": "人工", "正常資源": 32, "正常照合項目": good["照合項目数"], "不一致数": good["不一致数"], "破損拒否": detected, "破損拒否数": len(detected), "入力不変": good["入力不変"], "監査コードSHA256": BASE.sha(Path(__file__)), "全再用部品SHA256": component_hashes(), "実API": 0, "原板/新日/金融再生/Source生成": 0, "限定": "手製約定の表示形式だけの人工。H0判断/金融生成/Source生成の正しさを成功化しない。"}


def main() -> None:
    """人工又は許可後の既存Viewer監査を新規証拠へ保存する。

    引数: CLIの--self-test/--local-only/--run、--catalog/--result/--out(Path)、--workers(int)、--url(str)。
    返り値: なし。成功以外は非0。Viewer起動/停止/設定変更はしない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--local-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    for name in ("catalog", "result", "out"):
        parser.add_argument("--" + name, type=Path, required=name == "out")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--url", default="http://127.0.0.1:8092")
    args = parser.parse_args()
    need(not args.out.exists(), "新規証拠先だけ")
    if args.self_test:
        need(args.catalog is None and args.result is None, "人工へ実入力を渡さない")
        proof = self_test()
    else:
        need(args.catalog is not None and args.result is not None, "一覧/結果を明示")
        proof = prepare_local(args.catalog, args.result) if args.local_only else run(args.catalog, args.result, args.url, args.workers)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(proof, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: proof[key] for key in ("成功", "正常資源", "完了資源", "照合項目数", "不一致数") if key in proof}, ensure_ascii=False))
    if not proof["成功"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
