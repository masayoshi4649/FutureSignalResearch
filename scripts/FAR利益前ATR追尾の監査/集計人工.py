"""停止14人工だけを98保存算術とViewer変換へ渡し、会計破損を拒否する。"""

import argparse
import copy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
AGG_PATH = Path(__file__).with_name("集計.py")
SPEC = importlib.util.spec_from_file_location("保存集計98人工",AGG_PATH)
AGG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AGG
SPEC.loader.exec_module(AGG)


def verify_viewer(path: Path, book: dict) -> dict:
    """
    機能: 出力約定の所有・半円費用・実純額を表示行だけから別加算する。
    引数: path(Path)、book(dict)は新変換行と元実会計。
    返り値: dictは行数/純額/部分返済件数。Viewerサーバーを起動・操作しない。
    """
    positions, fees, gross, partial = {}, Decimal(0), Decimal(0), 0
    rows = [json.loads(line,parse_float=Decimal) for line in path.read_text(encoding="utf-8").splitlines()]
    AGG.equal(len(rows),len(book["fills"]),"変換全Fill")
    cost = Decimal("38.5")+Decimal(book["config"]["slip_pts"])*100
    for row,fill in zip(rows,book["fills"]):
        AGG.equal(row["method_id"],book["key"],"Viewer口座label")
        AGG.equal(row["id"],fill["id"],"Viewer Fill ID")
        AGG.equal(row["source_line"],fill["quote"]["source_line"],"Viewer物理行")
        qty = AGG.integer(row["qty"],"Viewer枚数",1)
        AGG.equal(row["fee_yen"],cost*qty,"片道半円費用/滑り")
        fees += row["fee_yen"]
        pid = row["position_id"]
        if row["type"] in ("LongN","ShortN"):
            AGG.need(pid not in positions,"Viewer新規所有重複")
            positions[pid] = {"side":1 if row["type"]=="LongN" else -1,"entry":row["price"],"quantity":qty}
        else:
            AGG.need(row["type"] in ("LongR","ShortR") and pid in positions,"Viewer返済所有")
            state = positions[pid]
            AGG.equal(row["type"],"LongR" if state["side"]==1 else "ShortR","Viewer建玉返済方向")
            AGG.need(0<qty<=state["quantity"],"Viewer過剰返済")
            partial += qty<state["quantity"]
            gross += state["side"]*(row["price"]-state["entry"])*qty*100
            state["quantity"] -= qty
    AGG.need(all(p["quantity"]==0 for p in positions.values()),"Viewer最終所有0")
    AGG.equal(gross,book["totals"]["gross_yen"],"Viewer粗額")
    AGG.equal(fees,book["totals"]["fee_yen"]+book["totals"]["slip_yen"],"Viewer全費用")
    AGG.equal(gross-fees,book["totals"]["net_yen"],"Viewer最終純額")
    return {"行数":len(rows),"純額円":gross-fees,"部分返済":partial}


def reject(value: dict, key: str, mutate, label: str) -> dict:
    """
    機能: 保存一口座の単一破損を新しい純判定器で検出する。
    引数: value(dict)、key/label(str)、mutate(callable)は正常保存・対象・破損操作・名称。
    返り値: dictは拒否証拠。正常入力は深い複写で保持する。
    """
    broken = copy.deepcopy(value)
    mutate(broken["books"][key])
    try:
        AGG.verify_saved_book(broken["books"][key],key,AGG.SavedGates(broken),False)
    except (ValueError,AssertionError,KeyError,TypeError) as error:
        return {"破損":label,"拒否":True,"理由":str(error)}
    raise ValueError("破損を検出できません:"+label)


def main() -> int:
    """
    機能: 停止production14場面の336口座を保存/表示変換へ接続する。
    引数: --fixtures/--out(Path)は停止人工根と新規証拠先。
    返り値: intは成功0。実市場/原板/金融新運転は行わない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fixtures","out"): parser.add_argument("--"+name,type=Path,required=True)
    args = parser.parse_args()
    AGG.need(not args.out.exists(),"新規人工出力だけ")
    paths = sorted(args.fixtures.glob("*.json"))
    expected = {f"方向{s}_{n}.json" for s in (-1,1) for n in ("risk要求後正益","Source全予約","Source部分","利益移行","幅と次板悪化","未知後既知","非緩和")}
    AGG.equal({p.name for p in paths},expected,"停止production14集合")
    code_paths = [Path(__file__),AGG_PATH,AGG.OLD_PATH,AGG.RISK_PATH,AGG.MARKET_PATH,
                  Path(AGG.BASE.__file__),Path(AGG.DIAG.__file__),AGG.OLD.OLD_PATH,AGG.OLD.COUPLED_PATH]
    before = {str(p.resolve()):AGG.digest(p) for p in paths+code_paths}
    args.out.mkdir(parents=True)
    rows, breaks, viewer_count, partial_count = [],[],0,0
    for path in paths:
        fixture = AGG.BASE.read_json(path)
        value = fixture["output"]
        old = fixture["baseline97_api"]
        AGG.RISK.compare_no_risk97(value,old)
        result = AGG.analyze_values([value],"人工")
        out = args.out/path.stem
        out.mkdir()
        resources = AGG.write_viewer(out,[value])
        AGG.equal(len(resources),24,"人工24表示資源")
        expected_classes = {"Source":0,"H":0,"Risk":0}
        for key,book in value["books"].items():
            converted = verify_viewer(out/("98_"+key+"_"+value["session"]+".trades.jsonl"),book)
            viewer_count += 1
            partial_count += converted["部分返済"]
            for name in expected_classes: expected_classes[name] += result["注文別"][key][name]["要求回数"]
            row = result["集計"][key]
            AGG.equal(row["source_exit_requests"],result["注文別"][key]["Source"]["要求回数"],"Source原counter")
            AGG.equal(row["protection_exit_requests"],result["注文別"][key]["H"]["要求回数"],"H原counter")
            AGG.equal(row["initial_risk_exit_requests"],result["注文別"][key]["Risk"]["要求回数"],"Risk原counter")
        AGG.BASE.write_json(out/"結果.json",result)
        AGG.BASE.write_json(out/"一覧.resources.json",{"schema_version":1,"path_base":"catalog","resources":resources})
        (out/"結果.md").write_text(AGG.render(result),encoding="utf-8",newline="\n")
        rows.append({"人工":path.name,"会計数":24,"空Risk旧97H0API全文":8,"比較系列":len(result["初期Riskと空Riskの同実入口と実参加差"]),"注文別要求":expected_classes})
    fixture = AGG.BASE.read_json(paths[0]);value=fixture["output"]
    key = next(k for k in AGG.KEYS if k.startswith("R05_") and any(o.get("initial_risk_point") for o in value["books"][k]["orders"]))
    breaks.append(reject(value,key,lambda b:b["config"].__setitem__("risk_policy","R10"),"risk label"))
    breaks.append(reject(value,key,lambda b:b["fills"][0].__setitem__("fee_yen",b["fills"][0]["fee_yen"]+Decimal("0.5")),"半円fee"))
    breaks.append(reject(value,key,lambda b:b["fills"][0].__setitem__("quantity",b["fills"][0]["quantity"]+1),"実枚数"))
    breaks.append(reject(value,key,lambda b:b["metrics"].__setitem__("initial_risk_exit_requests",b["metrics"].get("initial_risk_exit_requests",0)+1),"risk counter"))
    breaks.append(reject(value,key,lambda b:b["positions"][0]["initial_risk"].__setitem__("width",126),"risk幅"))
    breaks.append(reject(value,key,lambda b:next(o for o in b["orders"] if o.get("initial_risk_point")).__setitem__("reason","元Source返済"),"risk理由偽装"))
    breaks.append(reject(value,key,lambda b:next(o for o in b["orders"] if o.get("initial_risk_point"))["initial_risk_point"]["mark"].__setitem__("reserved",1),"自己予約先取り"))
    control = next(k for k in AGG.KEYS if not k.startswith(("R05_","R10_")))
    broken = copy.deepcopy(value)
    broken["books"][control]["totals"]["net_yen"] += Decimal(1)
    try: AGG.RISK.compare_no_risk97(broken,fixture["baseline97_api"])
    except (ValueError,AssertionError) as error: breaks.append({"破損":"空Risk旧97H0対照1円","拒否":True,"理由":str(error)})
    else: raise ValueError("空risk対照破損を拒否できません")
    AGG.need(all(AGG.digest(Path(p))==h for p,h in before.items()),"人工/旧依存コード前後不変")
    proof = {"成功":True,"人工場面":len(rows),"会計数":len(rows)*24,"Viewer変換":viewer_count,"空Risk旧97H0API全文":len(rows)*8,
             "部分返済表示":partial_count,"破損拒否":len(breaks),"details":rows,"破損":breaks,"入力コードSHA256前後":before,"前後不変":True,
             "scope":"停止production14の手製Source/ATR＋現在純技法。保存会計/変換限定。市場Source生成/CSV由来/実APIは未検査。",
             "市場/原板/CSV/Go金融新運転/API":0}
    AGG.BASE.write_json(args.out/"検査.json",proof)
    print(json.dumps({k:proof[k] for k in ("成功","会計数","Viewer変換","破損拒否")},ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
