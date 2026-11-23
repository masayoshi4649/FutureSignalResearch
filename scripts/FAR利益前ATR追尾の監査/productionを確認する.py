"""手製production Tape14場面の24金融・純技法結合と少数の破損を照合する。"""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys


ROOT=Path(__file__).resolve().parents[2]
CODE=Path(__file__).with_name("初期ATR追尾の金融照合.py")
spec=importlib.util.spec_from_file_location("独立risk98production",CODE)
M=importlib.util.module_from_spec(spec);sys.modules[spec.name]=M;spec.loader.exec_module(M)


def rejected(name,value,change,baseline=False):
    """
    機能: 手製Tape又は保存新結果の一箇所破損を拒否する。
    引数: name(str)、value(dict)、change(callable)、baseline(bool)は名称/元値/破損/旧対照側。
    返り値: dictは拒否の結果。市場金融又は新しいGo期待値は生成しない。
    """
    broken=copy.deepcopy(value);change(broken)
    try:
        if baseline:M.compare_no_risk97(broken["output"],broken["baseline97_api"])
        else:M.inspect_tape(broken["tape"],broken["output"])
    except (ValueError,KeyError,AssertionError) as error:return {"種類":name,"拒否":True,"理由":str(error)[:350]}
    raise AssertionError("破損を受理:"+name)


def main():
    """
    機能: 固定手製14件を全24金融/純技法へ通し、112旧97API対照を別計数する。
    引数: --fixtures/--out(Path)はproduction人工根と新規出力。
    返り値: None。原板/市場/新Goを実行しない。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();paths=sorted(args.fixtures.glob("*.json"))
    expected={f"方向{s}_{n}.json" for s in (-1,1) for n in ("risk要求後正益","Source全予約","Source部分","利益移行","幅と次板悪化","未知後既知","非緩和")}
    if args.out.exists() or {p.name for p in paths}!=expected:raise ValueError("手製14件/新規出力のみ")
    code_paths=[CODE,Path(__file__),M.FIN_PATH,M.TAPE_PATH,M.FIN.OLD_PATH,M.FIN.TECH_PATH,
                M.FIN.OLD.OLD_PATH,M.FIN.OLD.OLD.BASE_PATH,M.BASE.BASE_PATH]
    before={str(p.resolve()):M.digest(p) for p in paths+code_paths}
    rows=[];original=None
    for path in paths:
        value=M.BASE.load(path)
        if not value["tape"]["scope"].startswith("固定98Go型人工") or value["tape"].get("provenance"):
            raise ValueError("市場Tapeはこの人工CLI対象外")
        result=M.inspect_tape(value["tape"],value["output"])
        controls=M.compare_no_risk97(value["output"],value["baseline97_api"])
        rows.append({"fixture":path.name,**result,"空risk旧97API全文":controls})
        if path.name=="方向1_幅と次板悪化.json":original=value
    assert original is not None
    key="R05_H0_AB_B5Q_P0_C0_D0"
    gi=next(i for i,r in enumerate(original["output"]["gate_assessments"]) if r["key"]==key)
    qi=next(i for i,e in enumerate(original["tape"]["events"]) if e["kind"]=="quote" and e["quote"]["atr"]>0)
    ti=next(i for i,e in enumerate(original["tape"]["events"]) if e["kind"]=="force" and e.get("non_empty"))
    changes=[
        ("callback現在候補数量を+1",lambda v:v["output"]["gate_assessments"][gi]["candidate"].__setitem__("quantity",999)),
        ("純判断Allowed反転",lambda v:v["output"]["gate_assessments"][gi]["assessment"]["decision"].__setitem__("allowed",False)),
        ("callback保存順を反転",lambda v:v["output"]["gate_assessments"].reverse()),
        ("取得ATRに未来公開",lambda v:v["tape"]["events"][qi]["quote"].__setitem__("atr_available",v["tape"]["events"][qi]["at"]+1)),
        ("Forceをquote位相へ",lambda v:v["tape"]["events"][ti]["non_empty"][0]["delta"].__setitem__("origin","quote")),
        ("未定義risk field",lambda v:v["output"]["books"][key]["positions"][0]["initial_risk"].__setitem__("unknown",0)),
        ("24金融の欠落",lambda v:v["output"]["books"].pop(key)),
    ]
    bad=[rejected(name,original,change) for name,change in changes]
    oldkey="H0_B5Q_P0_C0_D0"
    bad.append(rejected("NoRisk旧97本文差",original,lambda v:v["baseline97_api"]["books"][oldkey]["totals"].__setitem__("net_yen",1),True))
    normalized=copy.deepcopy(original)
    for event in normalized["tape"]["events"]:
        for batch in event.get("non_empty",[]):
            for field in ("signals","fills","cancellations","closes"):
                if batch["delta"][field] is None:batch["delta"][field]=[]
    same=M.inspect_tape(normalized["tape"],normalized["output"])
    assert same["成功"] and same["会計数"]==24
    if any(M.digest(Path(p))!=h for p,h in before.items()):raise ValueError("人工/依存の前後差")
    proof={"成功":True,"人工場面":14,"会計数":sum(r["会計数"] for r in rows),"非0会計数":sum(r["非0会計数"] for r in rows),
           "照合項目数":sum(r["照合項目数"] for r in rows),"不一致数":0,"全Force配送":sum(r["イベント"].get("force",0) for r in rows),
           "現在純判定":sum(r["技法"]["新callback"] for r in rows),"空risk旧97API全文会計":sum(r["空risk旧97API全文"]["対照会計"] for r in rows),
           "破損拒否":bad,"Go既知nil列と空列の意味同値":True,"details":rows,"入力コードSHA256前後":before,"前後不変":True,
           "scope":"Go型手製Source/ATR/Chartのproduction Tape。純技法は現在候補から独立再計算。自然Source/指標形成/市場の成功を補完しない。",
           "市場/原板/新Go再生":0}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({n:proof[n] for n in ("成功","会計数","非0会計数","照合項目数","現在純判定","空risk旧97API全文会計")},ensure_ascii=False))


if __name__=="__main__":main()
