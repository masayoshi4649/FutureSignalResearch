"""固定95/94の表示比較で96の16Actor・32/864資源を照合する。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from urllib.parse import parse_qs, urlencode, urlparse


ROOT = Path(__file__).resolve().parents[2]
FIXED95 = ROOT / "scripts/FAR5分判断と出生一回の監査/表示監査.py"
FIXED95_SHA = "a8eac34c9ba1bfce1f27ff659fe66224452e254979a6cd294b72a29b6b7741b5"
if hashlib.sha256(FIXED95.read_bytes()).hexdigest() != FIXED95_SHA:
    raise ValueError("固定95表示のSHA差")
SPEC = importlib.util.spec_from_file_location("96が再用する固定95表示",FIXED95)
F95 = importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(F95)
OLD = F95.OLD
FIXED, FIXED_SHA = F95.FIXED, F95.FIXED_SHA
BASE, need, decimal, number = OLD.BASE, OLD.need, OLD.decimal, OLD.number
LEGACY, LEGACY_SHA = OLD.LEGACY, OLD.LEGACY_SHA
AGG_SHA = "32f7931f75f4b6241ced26e1f4b4014c332711c0948de104093762d01c73d750"
GATE_SHA = "b5d1af7fb85d4446a47573a4389abfa433177189cb01d901bdd53a8a38b8d5e6"
CONNECTION_GATE_SHA = "71363cfa968beb634e44eaa0851cedbcda0a9b985d3f34dcef31a275b0e49588"
PROOF95 = "b7df0d9f793fca1ee9fbb489e045b927f8cf4b46e0e81a6c199920f128e4d943"
POLICIES = ("G0","A","B","AB")
KEYS = tuple(("" if p == "G0" else p+"_")+f"B5Q_P0_C{c}_D{d}"
             for p in POLICIES for c in (0,5) for d in (0,1))


def key_config(key: str) -> tuple:
    """
    機能: 16Actorを表示gate名/費用/遅延へ分ける。
    引数: key(str)は定義済み96Actor。
    返り値: tuple[str,int,int]はG0/A/B/AB、滑り、遅延。
    """
    need(key in KEYS,"96表示Actor key")
    policy = "G0" if key.startswith("B5Q_") else key.split("_")[0]
    tail = key.split("_")
    return policy,int(tail[-2][1:]),int(tail[-1][1:])


def local_inputs(catalog_path: Path, result_path: Path, limit: int = 54, artificial: bool = False) -> dict:
    """
    機能: 96の保存16Actor/費用/所有を検査し、固定表示部品へ期待約定を渡す。
    引数: catalog_path/result_path(Path)、limit(int)は54又は接続2、artificial(bool)は通信代替だけ。
    返り値: dictは固定94 runnerの入力。API/原板は読まない。
    """
    need(type(limit) is int and limit in (2, 54), "場数")
    catalog_path, result_path = catalog_path.resolve(), result_path.resolve()
    cb, rb = catalog_path.read_bytes(), result_path.read_bytes(); catalog, result = json.loads(cb), json.loads(rb)
    need(result["試行"] == 96 and result["成功"] is True and result["場数"] == limit and result["Actor数"] == 16 and result["会計数"] == limit * 16, "96保存会計集合")
    need(result["scope"] == ("人工" if artificial else "正式" if limit == 54 else "接続"), "表示scope")
    if not artificial:
        need(result["入力前後不変"] is True and result["入力SHA256前"] == result["入力SHA256後"], "入力前後不変")
        accepted_gate_sha = (GATE_SHA,) if limit == 54 else (GATE_SHA, CONNECTION_GATE_SHA)
        need(result["集計コードSHA256"] == AGG_SHA and result["技法照合コードSHA256"] in accepted_gate_sha and result["基準95完了SHA256"] == PROOF95, "96保存/Python/旧95停止指紋")
        matches = result["G0四会計の固定95対照"]
        wanted = {key for key in KEYS if key_config(key)[0] == "G0"}
        need(len(matches) == limit and len({r["session"] for r in matches}) == limit and
             all(r["基準完了SHA256"] == PROOF95 and set(r["一致口座"]) == wanted and r["G0除外field"] == [] for r in matches), "G0四会計の旧95全文対照")
    rows = {(r["session"], r["key"]): r for r in result["場別"]}; sessions = {s for s, _ in rows}
    need(len(rows) == len(result["場別"]) == limit * 16 and len(sessions) == limit
         and set(rows) == {(s, k) for s in sessions for k in KEYS}, "全場Actor一意")
    days = {s[:-4] for s in sessions if s.endswith("_Day")}; nights = {s[:-6] for s in sessions if s.endswith("_Night")}
    need(days == nights and len(days) == limit // 2 and all("2026-09-21" <= d <= "2026-10-27" for d in days), "既使用昼夜の集合")
    need(set(result["集計"]) == set(result["Actor設定"]) == set(KEYS), "96 Actor設定集合")
    sums = {key: {field: Decimal(0) for field in OLD.TOTALS + ("positions", "fills")} for key in KEYS}
    expected = {}
    for (session, key), row in rows.items():
        policy, slip, delay = key_config(key); totals, counts = row["totals"], row["counts"]
        actual_policy = "" if policy == "G0" else policy
        need(row["gate_policy"] == actual_policy and row["gate_label"] == policy and result["Actor設定"][key] ==
             {"gate_policy": actual_policy, "gate_label": policy, "entry_timing": "B5Q", "policy": "P0", "slip_pts": slip, "delay_seconds": delay}, "96実空G0/表示名・config対応")
        qty = totals["entry_quantity"]
        need(type(qty) is int and qty >= 0 and type(totals["close_quantity"]) is int and totals["close_quantity"] == qty, "実新規/返済量")
        need(all(type(counts[n]) is int and counts[n] >= 0 for n in ("positions", "fills")), "実玉/約定数")
        need(all(decimal(totals[n]) == 0 for n in OLD.ZERO_FIELDS), "終所有/予約/未回収新規費用0")
        gross, fee, cost, net = (decimal(totals[n]) for n in ("gross_yen", "fee_yen", "slip_yen", "net_yen"))
        need(fee == 77 * qty and cost == 200 * slip * qty and decimal(totals["gross_minus_fee_yen"]) == gross - fee
             and net == gross - fee - cost and decimal(totals["closed_net_yen"]) == net, "96費用3列/半円")
        for field in OLD.TOTALS: sums[key][field] += decimal(totals[field])
        for field in ("positions", "fills"): sums[key][field] += counts[field]
        rid = "96_" + key + "_" + session
        expected[rid] = {"row": row, "key": key, "gate_label": policy, "unit_fee": Decimal("38.5") + 100 * slip, "net": number(net)}
    for key in KEYS:
        for field, amount in sums[key].items(): need(decimal(result["集計"][key][field]) == amount, "96場別/全体加算")
    resources = catalog["resources"]
    need(catalog["schema_version"] == 1 and catalog["path_base"] == "catalog"
         and len(resources) == len({r["id"] for r in resources}) == limit * 16
         and {r["id"] for r in resources} == set(expected), "96全Viewer資源")
    hashes = {str(catalog_path): hashlib.sha256(cb).hexdigest(), str(result_path): hashlib.sha256(rb).hexdigest(),
              str(Path(__file__).resolve()): BASE.sha(Path(__file__.strip())), str(FIXED): FIXED_SHA, str(FIXED95): FIXED95_SHA,
              str(OLD.LEGACY_PATH): OLD.LEGACY_SHA, str(OLD.LEGACY.FIXED): OLD.LEGACY.FIXED_SHA}
    trades, events = {}, {}
    for resource in resources:
        e = expected[resource["id"]]; row, key = e["row"], e["key"]
        need((resource["symbol"], resource["session"], resource["product"], resource["method_id"], resource["point_value"], resource["pnl_format"], resource["pnl_basis"])
             == ("NK225", row["session"], "NK225mini", key, 100, "trades", "net"), "96 resourceラベル")
        need(resource["title"] == "複合技法 " + e["gate_label"] + "/" + key + " " + row["session"], "資源Timing/key識別")
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


def _run_fixed(catalog_path: Path, result_path: Path, url: str = "http://127.0.0.1:8092", workers: int = 8,
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
        need(len(resolved) == len(loaded["resources"]) == limit * len(KEYS) and set(resolved) == set(local["expected"]), "API全資源集合")
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
                    print(f"表示監査 {len(rows)}/{limit * len(KEYS)}", flush=True)
    except BASE.ViewerError as error:
        errors.append({"種類": error.kind, "URL": error.url, "説明": str(error)[:1000]})
    except (ValueError, AssertionError, KeyError, TypeError) as error:
        errors.append({"種類": "一覧schema又は結合", "説明": str(error)[:1000]})
    rows.sort(key=lambda row: row["id"])
    before = local["入力SHA256"]; after = {p: BASE.sha(Path(p)) for p in before}
    audit.check("入力とコードの前後不変", after, before)
    errors += [{"id": row["id"], "詳細": row["APIエラー"]} for row in rows if row["APIエラー"]]
    differences = audit.bad + sum(row["不一致数"] for row in rows)
    complete = len(rows) == limit * len(KEYS) and all(row["完了"] for row in rows) and not errors
    return {"試行": 96, "成功": complete and differences == 0 and before == after, "成功の範囲": "Viewer保存会計一致",
            "scope": "人工" if artificial else "正式" if limit == 54 else "接続", "予定資源": limit * len(KEYS),
            "完了資源": sum(row["完了"] for row in rows), "全資源検証完了": complete,
            "照合項目数": audit.count + sum(row["照合項目数"] for row in rows), "不一致数": differences,
            "共通不一致": audit.examples, "APIエラー": errors, "資源": rows, "Viewer設定": info,
            "入力不変": before == after, "入力SHA256前": before, "入力SHA256後": after,
            "一覧SHA256": before[str(catalog_path)], "結果SHA256": before[str(result_path)],
            "監査コードSHA256": BASE.sha(Path(__file__)), "固定93部品SHA256": LEGACY_SHA, "固定80部品SHA256": LEGACY.FIXED_SHA,
            "Viewer停止/再起動/設定変更": 0, "新売買再生": 0, "原板直接読取": 0, "API本文複写": 0,
            "限定": "表示の全約定/所有/費用と保存純額の一致。MTM DD/Source生成/原板価格対応/mini実執行の証明ではない。"}


def run(catalog_path: Path, result_path: Path, url: str = "http://127.0.0.1:8092", workers: int = 8,
        transport=None, progress: bool = True, limit: int = 54, artificial: bool = False) -> dict:
    """
    機能: 固定94/95のAPI/数値比較を96の16集合へ結び直す。
    引数: catalog_path/result_path(Path)、url(str)、workers(int)、transport、progress/ artificial(bool)、limit(int)。
    返り値: dictは全約定と保存会計の表示証拠。Viewerプロセスは操作しない。
    """
    need(type(artificial) is bool,"人工scopeのbool型")
    result = _run_fixed(catalog_path,result_path,url,workers,transport,progress,limit,artificial)
    result["固定95部品SHA256"],result["固定94部品SHA256"] = FIXED95_SHA,FIXED_SHA
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    ids = {row["id"]:row["method_id"] for row in catalog["resources"]}
    for row in result["資源"]:
        key=ids[row["id"]];policy,cost,delay=key_config(key)
        row.update(Actor=key,GateLabel=policy,GatePolicy="" if policy=="G0" else policy,
                   EntryTiming="B5Q",費用基準="C"+str(cost),約定遅延秒=delay)
    return result


def self_test() -> dict:
    """
    機能: 32人工資源の非0/partial/空取引と費用・ラベル・枚数破損を検査する。
    引数: なし。HTTP/実市場/Native保存を読み込まない。
    返り値: dictは通信代替とローカル境界の証拠。
    """
    with tempfile.TemporaryDirectory(prefix="96表示人工_",dir=ROOT/"work") as name:
        temp=Path(name).resolve();need(temp.is_relative_to((ROOT/"work").resolve()),"人工保存先境界")
        resources,rows,trades=[],[],{}
        groups={key:{field:0 for field in OLD.TOTALS+("positions","fills")} for key in KEYS}
        for kind in ("Day","Night"):
            session="2026-09-21_"+kind
            for key in KEYS:
                policy,slip,delay=key_config(key);zero=kind=="Day" and key=="B5Q_P0_C5_D1"
                totals={"entry_quantity":0 if zero else 3,"close_quantity":0 if zero else 3,
                        "gross_yen":0 if zero else 5000,"fee_yen":0 if zero else 231,"slip_yen":0 if zero else 600*slip,
                        "gross_minus_fee_yen":0 if zero else 4769,"net_yen":0 if zero else 4769-600*slip,
                        **{field:0 for field in OLD.ZERO_FIELDS}}
                totals["closed_net_yen"]=totals["net_yen"]
                counts={"positions":0 if zero else 1,"fills":0 if zero else 3}
                rows.append({"session":session,"key":key,"gate_policy":"" if policy=="G0" else policy,"gate_label":policy,"totals":totals,"counts":counts})
                for field in OLD.TOTALS:groups[key][field]+=totals[field]
                for field in counts:groups[key][field]+=counts[field]
                rid="96_"+key+"_"+session;side=1 if kind=="Day" else -1
                at=datetime.fromisoformat("2026-09-21"+("T09:20:00+09:00" if kind=="Day" else "T18:00:00+09:00"))
                saved=[] if zero else [{"id":rid+"-F"+str(i),"timestamp":(at+timedelta(seconds=i)).isoformat(),
                    "type":("Long" if side==1 else "Short")+("N" if i==0 else "R"),"position_id":rid+"-P",
                    "price":price,"qty":qty,"fee_yen":(38.5+100*slip)*qty,"method_id":key,"source_line":10+i}
                    for i,(price,qty) in enumerate(((1000,3),(1000+side*30,1),(1000+side*10,2)))]
                (temp/(rid+".trades.jsonl")).write_text("".join(json.dumps(row)+"\n" for row in saved),encoding="utf-8")
                trades[rid]=saved
                resources.append({"id":rid,"title":"複合技法 "+policy+"/"+key+" "+session,"symbol":"NK225","product":"NK225mini","session":session,
                                  "method_id":key,"point_value":100,"pnl_format":"trades","pnl_basis":"net","pnl_path":rid+".trades.jsonl","market_path":"NK225/"+session+"/book.jsonl.gz"})
        result={"試行":96,"成功":True,"scope":"人工","場数":2,"Actor数":16,"会計数":32,"集計":groups,"場別":rows,
                "Actor設定":{key:{"gate_policy":"" if key_config(key)[0]=="G0" else key_config(key)[0],"gate_label":key_config(key)[0],"entry_timing":"B5Q","policy":"P0","slip_pts":key_config(key)[1],"delay_seconds":key_config(key)[2]} for key in KEYS}}
        catalog_path,result_path=temp/"一覧.resources.json",temp/"結果.json"
        catalog={"schema_version":1,"path_base":"catalog","resources":resources}
        catalog_path.write_text(json.dumps(catalog),encoding="utf-8");result_path.write_text(json.dumps(result),encoding="utf-8")
        resolved={r["id"]:{**r,"pnl_path":str(temp/r["pnl_path"]),"market_path":str(temp/"市場"/r["market_path"])} for r in resources}

        def fake(method,url,payload=None):
            """
            機能: 固定Viewer schemaの通信代替を返す。
            引数: method/url(str)、payload(dict|None)。
            返り値: tupleはJSON値/本文bytes/SHAヘッダ。実APIは使用しない。
            """
            if url.endswith("/api/info"):value={"resource_root":str(temp),"data_root":str(temp/"市場"),"listen":"127.0.0.1:8092"}
            elif url.endswith("/api/catalogs/load"):value={"catalog_id":"人工96","path":str(catalog_path),"resources":list(resolved.values())}
            else:
                rid=parse_qs(urlparse(url).query)["resource"][0]
                events=BASE.trade_expectations(trades[rid],100);net=sum(e["realized_delta_yen"] for e in events)
                value={"resource":resolved[rid],"summary":{"long_qty":0,"short_qty":0,"realized_pnl_yen":net,"unrealized_pnl_yen":0},
                       "state_columns":["long_qty","short_qty","realized_pnl_yen","unrealized_pnl_yen"],"states":[[0,0,net,0]],"events":events,
                       "files":{"pnl":resolved[rid]["pnl_path"],"market":resolved[rid]["market_path"],"catalog":str(catalog_path)}}
            raw=json.dumps(value).encode();return value,raw,{"x-chart-data-sha256":hashlib.sha256(raw).hexdigest()}

        prepared=local_inputs(catalog_path,result_path,limit=2,artificial=True)
        for marker,wanted in (("_C0_",[-115.5,2961.5,1923]),("_C5_",[-1615.5,2461.5,923])):
            rid=next(r["id"] for r in resources if marker in r["method_id"] and trades[r["id"]])
            need([e["realized_delta_yen"] for e in prepared["events"][rid]]==wanted,"partial/半円の手計算")
        good=run(catalog_path,result_path,transport=fake,workers=2,progress=False,limit=2,artificial=True)
        need(good["成功"] and good["完了資源"]==32,"32正常人工")
        checks=["16key/32資源/買売/partial/半円/0取引", "C0/C5全3片の手計算"]
        for corruption in ("fee半円","枚数","ラベル","終0未知","本文SHA","通信未完"):
            def bad(method,url,payload=None):
                """
                機能: APIの数値/ラベル/通信破損を一つだけ注入する。
                引数: method/url(str)、payload(dict|None)。
                返り値: tupleは破損応答。通信は固定例外。
                """
                if corruption=="通信未完" and "/api/data?" in url:raise BASE.ViewerError("通信",url,"人工未完")
                value,_,_=fake(method,url,payload)
                if "/api/data?" in url:
                    if corruption=="fee半円" and value["events"]:value["events"][0]["realized_delta_yen"]+=.5
                    elif corruption=="枚数" and value["events"]:value["events"][0]["qty"]+=1
                    elif corruption=="ラベル":value["resource"]={**value["resource"],"method_id":"異なる政策"}
                    elif corruption=="終0未知":value["summary"]["long_qty"]=None
                raw=json.dumps(value).encode()
                return value,raw,{"x-chart-data-sha256":"破損" if corruption=="本文SHA" else hashlib.sha256(raw).hexdigest()}
            need(not run(catalog_path,result_path,transport=bad,workers=2,progress=False,limit=2,artificial=True)["成功"],"API破損見逃し:"+corruption)
            checks.append("API "+corruption+"拒否")
        first=next(r for r in resources if trades[r["id"]]);path=temp/first["pnl_path"];original=path.read_bytes()
        for corruption in ("fee半円","枚数"):
            changed=[json.loads(line) for line in original.decode().splitlines()]
            changed[0]["fee_yen" if corruption=="fee半円" else "qty"]+=.5 if corruption=="fee半円" else 1
            path.write_text("".join(json.dumps(row)+"\n" for row in changed),encoding="utf-8")
            try:local_inputs(catalog_path,result_path,limit=2,artificial=True)
            except ValueError:checks.append("local "+corruption+"拒否")
            else:raise AssertionError("local破損を通過:"+corruption)
            path.write_bytes(original)
        for corruption in ("資源ラベル","G0実空Policy"):
            cb,rb=catalog_path.read_bytes(),result_path.read_bytes()
            if corruption=="資源ラベル":
                broken=json.loads(cb);broken["resources"][0]["title"]="不正ラベル";catalog_path.write_text(json.dumps(broken),encoding="utf-8")
            else:
                broken=json.loads(rb);broken["Actor設定"][KEYS[0]]["gate_policy"]="G0";result_path.write_text(json.dumps(broken),encoding="utf-8")
            try:local_inputs(catalog_path,result_path,limit=2,artificial=True)
            except ValueError:checks.append("local "+corruption+"拒否")
            else:raise AssertionError("localラベル破損を通過:"+corruption)
            catalog_path.write_bytes(cb);result_path.write_bytes(rb)
        return {"成功":True,"正常資源":32,"正常照合項目":good["照合項目数"],"人工項目":checks,
                "監査コードSHA256":BASE.sha(Path(__file__)),"固定95部品SHA256":FIXED95_SHA,"固定94部品SHA256":FIXED_SHA,
                "実API":0,"市場/原板":0}


def main() -> None:
    """
    機能: 通信代替人工又は許可済の既存Viewerで表示数値を検証する。
    引数: --self-test/--run、--catalog/--result/--out(Path)、--limit(2/54)、--workers(1..8)、--url(str)。
    返り値: None。成功以外は非0。プロセス起動/停止/再設定は行わない。
    """
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test",action="store_true");mode.add_argument("--run",action="store_true")
    for name in ("catalog","result","out"):parser.add_argument("--"+name,type=Path,required=name=="out")
    parser.add_argument("--limit",type=int,choices=(2,54),default=54);parser.add_argument("--workers",type=int,default=8)
    parser.add_argument("--url",default="http://127.0.0.1:8092");args=parser.parse_args();need(not args.out.exists(),"新規証拠先だけ")
    if args.self_test:
        need(args.catalog is None and args.result is None,"人工へ実入力を渡さない");proof=self_test()
    else:
        need(args.catalog is not None and args.result is not None,"一覧/結果を明示")
        proof=run(args.catalog,args.result,args.url,args.workers,limit=args.limit)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("x",encoding="utf-8",newline="\n") as stream:json.dump(proof,stream,ensure_ascii=False,indent=2);stream.write("\n")
    print(json.dumps({name:proof[name] for name in ("成功","正常資源","完了資源","照合項目数","不一致数") if name in proof},ensure_ascii=False))
    if not proof["成功"]:raise SystemExit(1)


if __name__=="__main__":main()
