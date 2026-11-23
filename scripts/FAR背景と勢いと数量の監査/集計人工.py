# 由来: work/99保存集計案/集計人工.py
# 由来SHA256: 79cb4665b87e640f3880a94403f176c140f3ac5952f3ee8a03839d65233cce5c
"""99停止20人工を保存会計とViewer変換へ接続し、少数破損と市場拒否を検査する。"""

import argparse
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
import types


HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location("保存集計99人工",HERE/"集計.py")
AGG=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=AGG;SPEC.loader.exec_module(AGG)
ROOT=AGG.ROOT
VIEW_PATH=ROOT/"scripts/FAR利益前ATR追尾の監査/集計人工.py"
VIEW_SHA="45888af86bcca184e004e11a7249f8ccf70bd88b8c874e12c89adf2abcce990c"
VIEW=AGG.fixed("固定98表示行算術99",VIEW_PATH,VIEW_SHA)
verify_viewer=types.FunctionType(VIEW.verify_viewer.__code__,{**vars(VIEW),"AGG":AGG},"99表示行の独立配賦")


def reject(value: dict, key: str, mutate, label: str) -> dict:
    """
    機能: 保存一口座又は共有純式の単一破損を検出する。
    引数: value(dict)、key/label(str)、mutate(callable)は正常保存・対象・説明・変更です。
    返り値: dictは拒否証拠。正常値は深い複写で不変とする。
    """
    broken=copy.deepcopy(value);mutate(broken)
    try:AGG.verify_saved_book(broken["books"][key],key,AGG.SavedGates(broken),False)
    except (ValueError,AssertionError,KeyError,TypeError) as error:return {"破損":label,"拒否":True,"理由":str(error)}
    raise ValueError("破損を検出できません:"+label)


def main() -> int:
    """
    機能: 停止20場面×12口座とschema1変換を検算する。
    引数: --fixtures/--out(Path)は停止API人工根と新規証拠先。
    返り値: intは成功0。市場/原板/API/Go金融を実行しない。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("fixtures","out"):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args();AGG.need(not args.out.exists(),"新規人工先だけ")
    stop_path=ROOT/"work/99再生接続案/停止.json"
    AGG.equal(AGG.digest(stop_path),"97a567aed620f8288305acc8fb6fb3753d8aa18caa29d3c714ef8975977d962c","停止99再生")
    stop=AGG.BASE.read_json(stop_path)
    paths=sorted(args.fixtures.glob("*.json"))
    AGG.equal({p.name:AGG.digest(p) for p in paths},stop["停止人工SHA256"],"停止20本文")
    before={str(p.resolve()):AGG.digest(p) for p in paths+[Path(__file__),HERE/"集計.py",VIEW_PATH,AGG.OLD_PATH,AGG.INDEPENDENT_PATH,AGG.MARKET_PATH,stop_path]}
    args.out.mkdir(parents=True)
    rows,breaks,zero,nonzero,partial,resources_all=[],[],0,0,0,0
    for path in paths:
        fixture=AGG.BASE.read_json(path);value=fixture["output"]
        baseline=AGG.INDEPENDENT.compare_empty_gate98(value,fixture["baseline98_api"])
        result=AGG.analyze_values([value],"人工")
        AGG.equal(len(result["入口間の同実入口と実参加差"]),12,"12実参加比較")
        for old,new in AGG.comparisons():
            pair=result["入口間の同実入口と実参加差"][new+"対"+old][0]
            AGG.equal(pair["全差円"],result["集計"][new]["net_yen"]-result["集計"][old]["net_yen"],"二実運転の全差")
            AGG.equal(pair["全差円"],pair["同実入口差円"]+pair["取得変更差円"]-pair["Aのみ円"]+pair["Bのみ円"],"保存群寄与の算術")
        out=args.out/path.stem;out.mkdir()
        resources=AGG.write_viewer(out,[value]);AGG.equal(len(resources),12,"人工12表示資源")
        for resource in resources:
            key=resource["method_id"];book=value["books"][key]
            converted=verify_viewer(out/resource["pnl_path"],book)
            partial+=converted["部分返済"];resources_all+=1
            nonzero+=bool(book["positions"]);zero+=not book["positions"]
            AGG.equal(resource["id"],"99_"+key+"_"+value["session"],"99表示ID")
            AGG.equal(resource["title"],"背景と勢いと数量 "+key+" "+value["session"],"99表示label")
            orders=result["注文別"][key]
            AGG.equal(orders["Source"]["要求回数"],book["metrics"]["source_exit_requests"],"Source要求分類")
            AGG.equal(orders["H"]["要求回数"],book["metrics"]["protection_exit_requests"],"H要求分類")
            AGG.equal(sum(v["約定枚数"] for v in orders.values()),book["totals"]["close_quantity"],"全実返済分類")
            AGG.equal(sum(result["判断分類"][key]["枠"].values()),book["grid_metrics"]["grid_calls"],"判断枠分母")
            if not book["positions"]:AGG.need(result["実現診断"][key]["PF"] is None,"無取引PF未定義")
        AGG.BASE.write_json(out/"結果.json",result)
        AGG.BASE.write_json(out/"一覧.resources.json",{"schema_version":1,"path_base":"catalog","resources":resources})
        (out/"結果.md").write_text(AGG.render(result),encoding="utf-8",newline="\n")
        rows.append({"人工":path.name,"会計数":12,"空Gate旧98API全文":baseline["対照会計"],"比較系列":12,"純式":len(value["gate_assessments"])})
    value=AGG.BASE.read_json(args.fixtures/"方向1_Source部分.json")["output"]
    key="H0_E3_B5Q_P0_C0_D0"
    breaks.append(reject(value,key,lambda v:v["books"][key]["config"].__setitem__("gate_policy","AB"),"旧政策名偽装"))
    breaks.append(reject(value,key,lambda v:v["books"][key]["fills"][0].__setitem__("fee_yen",v["books"][key]["fills"][0]["fee_yen"]+Decimal("0.5")),"半円fee"))
    breaks.append(reject(value,key,lambda v:v["books"][key]["fills"][0].__setitem__("quantity",v["books"][key]["fills"][0]["quantity"]+1),"実枚数"))
    breaks.append(reject(value,key,lambda v:v["books"][key]["totals"].__setitem__("net_yen",v["books"][key]["totals"]["net_yen"]+1),"純額1円"))
    breaks.append(reject(value,key,lambda v:next(r for r in v["gate_assessments"] if r["key"]==key)["assessment"]["decision"].__setitem__("policy","A"),"純判断の本名"))
    breaks.append(reject(value,key,lambda v:next(r for r in v["gate_assessments"] if r["key"]==key)["assessment"]["checks"][0].__setitem__("passed",False),"全check破損"))
    breaks.append(reject(value,key,lambda v:v["books"][key]["grid_traces"][0].__setitem__("action","待機"),"判断分類の偽装"))
    original=AGG.BASE.read_json(args.fixtures/"方向1_Source部分.json")
    broken=copy.deepcopy(original["output"]);control="H0_B5Q_P0_C0_D0";broken["books"][control]["totals"]["net_yen"]+=Decimal("0.5")
    try:AGG.INDEPENDENT.compare_empty_gate98(broken,original["baseline98_api"])
    except (ValueError,AssertionError) as error:breaks.append({"破損":"旧98四対照の半円","拒否":True,"理由":str(error)})
    else:raise ValueError("旧四対照破損を許可")
    for stage in ("first2","full54"):
        try:AGG.require_market_fixed(stage)
        except ValueError as error:breaks.append({"破損":"未固定市場"+stage,"拒否":True,"理由":str(error)})
        else:raise ValueError("placeholder市場を許可")
    AGG.equal((len(rows),resources_all,nonzero,zero),(20,240,184,56),"全人工/非0/0表示範囲")
    AGG.need(all(AGG.digest(Path(p))==h for p,h in before.items()),"新旧code/人工前後不変")
    proof={"成功":True,"人工場面":20,"会計数":240,"非0会計数":nonzero,"0取引会計":zero,"Viewer変換":resources_all,"部分返済表示":partial,
           "空Gate旧98API全文":80,"比較系列/場面":12,"全比較レコード":sum(r["比較系列"] for r in rows),"破損拒否":len(breaks),"details":rows,"破損":breaks,
           "入力コードSHA256前後":before,"前後不変":True,"限定":"20手製APIの保存/実現算術/本名純式/Viewer変換。市場の全経路・98正式本文・実APIは未検査。",
           "市場Native/原板/CSV/API/Go新運転":0}
    AGG.BASE.write_json(args.out/"検査.json",proof)
    print(json.dumps({n:proof[n] for n in ("成功","会計数","非0会計数","0取引会計","Viewer変換","破損拒否")},ensure_ascii=False))
    return 0


if __name__=="__main__":raise SystemExit(main())
