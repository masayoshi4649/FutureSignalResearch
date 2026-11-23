"""固定98表示と96API rendererを再用し、本名G0/E3/E3Sの12口座を照合する。"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime,timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
from urllib.parse import parse_qs,urlparse

ROOT=Path(__file__).resolve().parents[2]
FIXED98=ROOT/"scripts/FAR利益前ATR追尾の監査/表示監査.py"
FIXED98_SHA="93a3d9a6ea6b3c164f08c2c97c8e6cb50216c506ab6a4c1e1bf544b262a36913"
if hashlib.sha256(FIXED98.read_bytes()).hexdigest()!=FIXED98_SHA:raise ValueError("固定98表示SHA差")
SPEC=importlib.util.spec_from_file_location("固定98表示比較99",FIXED98)
F98=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(F98)
F96,F97,OLD,BASE,LEGACY=F98.F96,F98.F97,F98.OLD,F98.BASE,F98.LEGACY
need,decimal,number=F98.need,F98.decimal,F98.number
PROOF98_SHA="2ee9417d0cd1f8bef107712789d26e3f72c0f95a933e60b31bb3f11784ca0dfe"
# Rootの実成功通知までは未設定。実API/実保存本文の読取を拒否する。
AGG_SHA="f5d6635e17e0e7bb3be8d5941e0adf7568f75251ce1a505b8090372289d2a69c"
CONDITION_SHA="ba95b8c7df74f3b6f2f0f3cc349210ff284bdc64ed2fe79311d702ebff2b0f71"
COMPLETION_SHA="d945e5daf823d95e17eb897115d7dcbd96a94a2ac112a028267fb7ed7e847dcc"
INDEPENDENT_SHA="592aff6b2a6b6eae4c3a10b4e5b7752e02972a7d489b04c73d92ab6654fedc2e"
AGG_PROTO_SHA="0c410af795393f246e093ecd60e82bf22bfb3fc6211d556401bbc6a8fb9f13ab"
KEYS=tuple("H0_"+(gate+"_" if gate else "")+f"B5Q_P0_C{c}_D{d}" for gate in ("","E3","E3S") for c in (0,5) for d in (0,1))


def key_config(key):
    """
    機能: 本名12keyを空Risk/入口/H0/費用/遅延へ分ける。
    引数: key(str)はG0/E3/E3S口座名。
    返り値: tupleは空Risk、G0/E3/E3S、H0、滑りpt、追加遅延秒。
    """
    need(key in KEYS,"99表示Actor key")
    gate="E3S" if key.startswith("H0_E3S_") else "E3" if key.startswith("H0_E3_") else "G0"
    return "",gate,"H0",int(key.split("_")[-2][1:]),int(key.split("_")[-1][1:])


def require_fixed():
    """
    機能: 実金融/独立監査/条件/保存の停止指紋未確定を読取前に拒否する。
    引数: なし。
    返り値: None。placeholderならValueError。
    """
    need(all(isinstance(h,str) and len(h)==64 and all(c in "0123456789abcdef" for c in h) for h in (AGG_SHA,CONDITION_SHA,COMPLETION_SHA,INDEPENDENT_SHA)),"99実金融/条件/独立/保存SHAが未固定")


def component_hashes():
    """
    機能: 新表示と固定98以下の再用コード指紋を列挙する。
    引数: なし。
    返り値: dict[str,str]は共通表示コードのSHA。
    """
    return {**F98.component_hashes(),str(FIXED98.resolve()):FIXED98_SHA,str(Path(__file__).resolve()):BASE.sha(Path(__file__))}


def scene_set(limit):
    """
    機能: 正式54又は独立人工一場の許可場名を返す。
    引数: limit(int)は54又は1。
    返り値: set[str]は場名。独立人工二根を同一catalogへ混合しない。
    """
    if limit==1:return {"2026-09-21_Day"}
    return F98.scene_set(limit)


def saved_header(result,limit,pins=None):
    """
    機能: 99保存/条件/金融完了/独立監査と旧98G0H0四全文を結ぶ。
    引数: result(dict)、limit(int)、pins(tuple|None)は明示metadata。
    返り値: None。pinsは人工metadata専用で、実runのplaceholderを解除しない。
    """
    pins=(AGG_SHA,CONDITION_SHA,COMPLETION_SHA,INDEPENDENT_SHA) if pins is None else pins
    need(len(pins)==4 and all(isinstance(h,str) and len(h)==64 and all(c in "0123456789abcdef" for c in h) for h in pins),"99保存停止指紋未結合")
    need(tuple(result[n] for n in ("集計コードSHA256","条件SHA256","完了SHA256","独立Tape金融監査SHA256"))==pins,"99保存/条件/金融/独立結合")
    deps=result["入力依存SHA256前後"]
    need(isinstance(deps,dict) and deps and all(isinstance(p,str) and isinstance(h,str) and len(h)==64 and all(c in "0123456789abcdef" for c in h) for p,h in deps.items()),"99保存依存SHA")
    need(set(pins)|{PROOF98_SHA}<=set(deps.values()),"99保存の固定98完了依存")
    rows=result["空Gate旧98H0全文対照"]
    need(len(rows)==limit and len({r["session"] for r in rows})==limit and {r["session"] for r in rows}==scene_set(limit)
         and all(type(r["対照会計"]) is int and r["対照会計"]==4 and r["除外"]==[] and isinstance(r["固定98保存SHA256"],str) and len(r["固定98保存SHA256"])==64 and all(c in "0123456789abcdef" for c in r["固定98保存SHA256"]) for r in rows),"99空Gate旧98H0四全文")


def local_inputs(catalog_path: Path, result_path: Path, limit: int = 54, artificial: bool = False) -> dict:
    """保存12口座の費用・所有・全約定を固定表示比較へ渡す。

    引数: catalog_path/result_path(Path)は一覧/保存結果、limit(int)、artificial(bool)は通信代替専用。
    返り値: dictは期待資源・約定・純額・入力SHA。金融/Source/原板を再生しない。
    """
    if not artificial:
        require_fixed()
    need(type(limit) is int and limit in (1, 54) and type(artificial) is bool, "場数/人工型")
    need(artificial or limit == 54, "99正式表示は54場、1場は人工専用")
    catalog_path, result_path = catalog_path.resolve(), result_path.resolve()
    cb, rb = catalog_path.read_bytes(), result_path.read_bytes()
    catalog, result = json.loads(cb), json.loads(rb)
    need(result["試行"] == 99 and result["成功"] is True and result["場数"] == limit and result["Actor数"] == 12 and result["会計数"] == limit * 12, "99保存会計集合")
    need(result["scope"] == ("人工" if artificial else "正式"), "99保存scope")
    if not artificial:
        saved_header(result, limit)
    rows = {(r["session"], r["key"]): r for r in result["場別"]}
    sessions = scene_set(limit)
    need(len(rows) == len(result["場別"]) == limit * 12 and set(rows) == {(s, k) for s in sessions for k in KEYS}, "99全場Actor一意")
    need(set(result["集計"]) == set(result["Actor設定"]) == set(KEYS), "99設定/集計key集合")
    sums = {key: {field: Decimal(0) for field in OLD.TOTALS + ("positions", "fills")} for key in KEYS}
    expected = {}
    for (session, key), row in rows.items():
        risk, gate, exit_policy, slip, delay = key_config(key)
        need(result["Actor設定"][key] == {"入口": gate, "出口": exit_policy, "初期risk": risk, "共通基本保護": "P0", "slip_pts": slip, "delay_seconds": delay}, "99入口/収穫/共通P0設定")
        totals, counts = row["totals"], row["counts"]
        qty = totals["entry_quantity"]
        need(type(qty) is int and qty >= 0 and type(totals["close_quantity"]) is int and totals["close_quantity"] == qty, "実新規/返済量")
        need(all(type(counts[n]) is int and counts[n] >= 0 for n in ("positions", "fills")), "実玉/約定数")
        need(all(decimal(totals[n]) == 0 for n in OLD.ZERO_FIELDS), "終所有/予約/未回収費用0")
        gross, fee, slip_yen, net = (decimal(totals[n]) for n in ("gross_yen", "fee_yen", "slip_yen", "net_yen"))
        need(fee == 77 * qty and slip_yen == 200 * slip * qty and decimal(totals["gross_minus_fee_yen"]) == gross - fee and net == gross - fee - slip_yen and decimal(totals["closed_net_yen"]) == net, "99指定手数料/仮定滑り/純額")
        for field in OLD.TOTALS:
            sums[key][field] += decimal(totals[field])
        for field in ("positions", "fills"):
            sums[key][field] += counts[field]
        rid = "99_" + key + "_" + session
        expected[rid] = {"row": row, "key": key, "unit_fee": Decimal("38.5") + 100 * slip, "net": number(net)}
    for key in KEYS:
        for field, amount in sums[key].items():
            need(decimal(result["集計"][key][field]) == amount, "99場別/全体加算")
    resources = catalog["resources"]
    need(catalog["schema_version"] == 1 and catalog["path_base"] == "catalog" and len(resources) == len({r["id"] for r in resources}) == limit * 12 and {r["id"] for r in resources} == set(expected), "99全資源集合")
    hashes = {str(catalog_path): hashlib.sha256(cb).hexdigest(), str(result_path): hashlib.sha256(rb).hexdigest(), **component_hashes()}
    trades, events = {}, {}
    for resource in resources:
        e = expected[resource["id"]]
        row, key = e["row"], e["key"]
        need((resource["symbol"], resource["session"], resource["product"], resource["method_id"], resource["point_value"], resource["pnl_format"], resource["pnl_basis"]) == ("NK225", row["session"], "NK225mini", key, 100, "trades", "net"), "99資源ラベル")
        need(resource["title"] == "背景と勢いと数量 " + key + " " + row["session"], "99H0識別title")
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


def run(catalog_path,result_path,url="http://127.0.0.1:8092",workers=8,transport=None,progress=True,limit=54,artificial=False):
    """
    機能: 固定96 rendererの全API比較本文をそのまま新12資源集合へ渡す。
    引数: catalog_path/result_path(Path)、url(str)、workers(int)、transport(callable|None)、progress/artificial(bool)、limit(int)。
    返り値: dictはViewer約定/純額/所有/本文SHA/未完照合。実runは未設定SHAで拒否する。
    """
    need(type(artificial) is bool,"人工scope bool")
    if not artificial:require_fixed()
    namespace=dict(F96.__dict__,local_inputs=local_inputs,KEYS=KEYS)
    runner=types.FunctionType(F96._run_fixed.__code__,namespace,argdefs=F96._run_fixed.__defaults__)
    result=runner(catalog_path,result_path,url,workers,transport,progress,limit,artificial)
    result.update({"試行":99,"監査コードSHA256":BASE.sha(Path(__file__)),"固定98部品SHA256":FIXED98_SHA,
                   "固定96部品SHA256":F97.FIXED96_SHA,"全再用部品SHA256":component_hashes(),"保存約定の会計検算":True,"実Source生成":0})
    ids={row["id"]:row["method_id"] for row in json.loads(catalog_path.read_text(encoding="utf-8"))["resources"]}
    for row in result["資源"]:
        key=ids[row["id"]];risk,gate,exit_policy,slip,delay=key_config(key)
        row.update(Actor=key,EntryGate=gate,GatePolicy="" if gate=="G0" else gate,HarvestPolicy="H0",ExitPolicy=exit_policy,
                   InitialRiskPolicy=risk,EntryTiming="B5Q",費用基準="C"+str(slip),約定遅延秒=delay)
    return result


def self_test():
    """
    機能: 独立2人工根を混合せず12ずつ表示比較し、partial/empty/半円/本名を検査する。
    引数: なし。停止保存artifactだけを読む。
    返り値: dictは24人工資源と狭い破損拒否。実API/市場/金融再生は0。
    """
    roots=[ROOT/"work/99保存集計案/人工/停止版"/name for name in ("方向1_Source部分","方向-1_API同時スパイク")]
    results=[];detected=[];empty=partial=half=0;all_inputs={}
    for ordinal,root in enumerate(roots):
        catalog_path,result_path=root/"一覧.resources.json",root/"結果.json"
        local=local_inputs(catalog_path,result_path,1,True)
        all_inputs.update(local["入力SHA256"])
        resolved={r["id"]:{**r,"pnl_path":str(root/r["pnl_path"]),"market_path":str(root/"市場"/r["market_path"])} for r in local["resources"]}
        empty+=sum(not rows for rows in local["trades"].values())
        half+=sum(decimal(t["fee_yen"])%1!=0 for rows in local["trades"].values() for t in rows)
        for rows in local["trades"].values():
            counts={}
            for t in rows:
                if t["type"].endswith("R"):counts[t["position_id"]]=counts.get(t["position_id"],0)+1
            partial+=sum(v>1 for v in counts.values())

        def fake(method,url,payload=None):
            """
            機能: 停止保存約定からViewerと同じ応答形を返す。
            引数: method/url(str)、payload(dict|None)は通信代替引数。
            返り値: tupleはJSON/本文/SHAヘッダ。HTTPは呼ばない。
            """
            if url.endswith("/api/info"):
                value={"resource_root":str(ROOT/"work"),"data_root":str(root/"市場"),"listen":"127.0.0.1:8092"}
            elif url.endswith("/api/catalogs/load"):
                value={"catalog_id":"人工99","path":str(catalog_path),"resources":list(resolved.values())}
            else:
                identity=parse_qs(urlparse(url).query)["resource"][0];events=local["events"][identity]
                net=sum(e["realized_delta_yen"] for e in events)
                value={"resource":resolved[identity],"summary":{"long_qty":0,"short_qty":0,"realized_pnl_yen":net,"unrealized_pnl_yen":0},
                       "state_columns":["long_qty","short_qty","realized_pnl_yen","unrealized_pnl_yen"],"states":[[0,0,net,0]],"events":events,
                       "files":{"pnl":resolved[identity]["pnl_path"],"market":resolved[identity]["market_path"],"catalog":str(catalog_path)}}
            raw=json.dumps(value).encode();return value,raw,{"x-chart-data-sha256":hashlib.sha256(raw).hexdigest()}

        good=run(catalog_path,result_path,transport=fake,workers=2,progress=False,limit=1,artificial=True)
        need(good["成功"] and good["完了資源"]==12 and good["不一致数"]==0,"99正常12人工")
        results.append({"人工根":str(root),"資源数":12,"照合項目数":good["照合項目数"],"入力不変":good["入力不変"]})
        if ordinal:continue
        for corruption in ("半円","数量","E3ラベル","所有","本文SHA","資源欠落","通信未完"):
            def bad(method,url,payload=None):
                """
                機能: Viewer応答の一項目を破損させる。
                引数: method/url(str)、payload(dict|None)は通信代替引数。
                返り値: tupleは破損JSON/本文/SHA。実APIは0。
                """
                if corruption=="通信未完" and "/api/data?" in url:raise BASE.ViewerError("通信",url,"人工未完")
                value,_,_=fake(method,url,payload);value=copy.deepcopy(value)
                if "/api/data?" in url:
                    if corruption=="半円" and value["events"]:value["events"][0]["realized_delta_yen"]+=.5
                    elif corruption=="数量" and value["events"]:value["events"][0]["qty"]+=1
                    elif corruption=="E3ラベル":value["resource"]["method_id"]="H0_AB_B5Q_P0_C0_D0"
                    elif corruption=="所有" and len(value["events"])>1:value["events"][1]["position_id"]="別玉"
                elif corruption=="資源欠落" and url.endswith("/api/catalogs/load"):value["resources"].pop()
                raw=json.dumps(value).encode();return value,raw,{"x-chart-data-sha256":"破損" if corruption=="本文SHA" else hashlib.sha256(raw).hexdigest()}
            need(not run(catalog_path,result_path,transport=bad,workers=2,progress=False,limit=1,artificial=True)["成功"],"API破損通過:"+corruption)
            detected.append(corruption)
    need(empty>0 and partial>0 and half>0,"空取引/部分返済/半円coverage")
    try:run(Path("未読一覧"),Path("未読結果"))
    except ValueError as error:detected.append("実run未設定読取前拒否:"+str(error))
    else:raise AssertionError("未設定実runを通過")
    need(all(BASE.sha(Path(path))==h for path,h in all_inputs.items()),"人工入力前後差")
    return {"試行":99,"成功":True,"scope":"人工","正常資源":24,"独立人工根":results,"正常照合項目":sum(r["照合項目数"] for r in results),
            "不一致数":0,"empty資源":empty,"partial実玉":partial,"半円片":half,"破損拒否":detected,
            "入力SHA256前後":all_inputs,"入力不変":True,"全再用部品SHA256":component_hashes(),"実API/原板/市場/金融再生":0,
            "限定":"独立2人工根は同じsession名を持つ別ケースであり、市場例や同一catalogへ合算しない。技法・自然Source生成の成功ではない。"}


def main():
    """
    機能: 人工表示照合又は指紋結合後だけ実648資源を検証する。
    引数: --self-test/--run、--catalog/--result/--out(Path)、--workers(int)、--url(str)。
    返り値: None。未確定/差/既存出力は非0。
    """
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test",action="store_true");mode.add_argument("--run",action="store_true")
    for name in ("catalog","result","out"):parser.add_argument("--"+name,type=Path,required=name=="out")
    parser.add_argument("--workers",type=int,choices=range(1,9),default=8);parser.add_argument("--url",default="http://127.0.0.1:8092")
    args=parser.parse_args();need(not args.out.exists(),"新規表示証拠だけ")
    if args.self_test:
        need(args.catalog is None and args.result is None,"人工へ市場入力を渡さない");result=self_test()
    else:
        require_fixed();need(args.catalog is not None and args.result is not None,"一覧/結果を明示")
        result=run(args.catalog,args.result,args.url,args.workers)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("x",encoding="utf-8",newline="\n") as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write("\n")
    print(json.dumps({n:result[n] for n in ("成功","正常資源","完了資源","照合項目数","不一致数") if n in result},ensure_ascii=False))
    if not result["成功"]:raise SystemExit(1)


if __name__=="__main__":main()
