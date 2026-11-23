"""実Go Marshal人工を読み96保存金融/技法を照合する。市場・原板を開かない。"""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def module(name: str, path: Path):
    """
    機能: 自分の検査案を読込。
    引数: name(str)/path(Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name,path)
    result = importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


AGG = module("96保存人工",HERE/"集計.py")
GATE = module("96純判断人工",HERE/"技法の保存照合.py")


def sha(path: Path) -> str:
    """
    機能: 指紋。
    引数: path(Path)。
    返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_fixture(value: dict) -> dict:
    """
    機能: 手製Sourceを含む実Go型16口座の保存/技法を結合する。
    引数: value(dict)はactors/chart_grids/gate_assessmentsを持つ人工。
    返り値: dictは人工の小型検算。自然Source/正式G0対照の成功を補完しない。
    """
    AGG.equal(set(value["actors"]),set(AGG.KEYS),"人工全16Actor")
    gate_index = GATE.GateIndex(value)
    checked, row = {},{}
    clocks = [t["at"] for t in value["actors"][AGG.KEYS[0]]["grid_traces"]]
    for key in AGG.KEYS:
        book = value["actors"][key]
        AGG.equal([t["at"] for t in book["grid_traces"]],clocks,"人工の共通時計列")
        c = checked[key] = AGG.verify_book(book,key,gate_index,full_clock=False)
        row[key] = {"玉数":c["counts"]["positions"],"枚数":c["totals"]["entry_quantity"],"純額円":c["totals"]["net_yen"],"機会":len(book["entry_opportunities"]),"Gate呼出":sum("gate" in p for p in book["entry_opportunities"])}
        if value.get("legacy_g0"):
            if AGG.key_config(key)[0] == "G0":
                AGG.equal(book,value["legacy_g0"][key],"人工G0旧95の実API全field")
    g = gate_index.finish(clocks)
    return {"会計":row,"技法":g,"旧95API全field":4 if value.get("legacy_g0") else 0,
            "限定":"Go型API人工。自然Source/実CSV指標/正式95対照は未計測。"}


def rejected(value: dict, modify, name: str) -> dict:
    """
    機能: 保存破損が拒否されることを確認。
    引数: value(dict)、mutate(callable(dict)->None)、name(str)。
    返り値: dictは破損拒否の証拠。
    """
    broken = copy.deepcopy(value);modify(broken)
    try:
        verify_fixture(broken)
    except (ValueError,KeyError,TypeError,AssertionError) as error:
        return {"反証":name,"拒否":True,"理由":str(error)[:250]}
    raise ValueError("破損を通過: "+name)


def financial_fixture_mutations(value: dict) -> list[dict]:
    """
    機能: 実Go出力にある項目だけへ破損を適用する。
    引数: value(dict)は正常確認済み人工。
    返り値: list[dict]は各反証。存在しない金融成功値は作らない。
    """
    answer = []
    if value["gate_assessments"]:
        def flip_check(v):
            """
            機能: check破損。
            引数: v(dict)。
            返り値: None。
            """
            c=v["gate_assessments"][0]["assessment"]["checks"][0];c["passed"]=not c["passed"]
        answer.append(rejected(value,flip_check,"個別checkの採否反転"))
        def nonbool(v):
            """
            機能: bool破損。
            引数: v(dict)。
            返り値: None。
            """
            v["gate_assessments"][0]["assessment"]["decision"]["known"]=0
        answer.append(rejected(value,nonbool,"knownへ数値0"))
        answer.append(rejected(value,lambda v:v["gate_assessments"].pop(0),"適格判定欠落"))
        answer.append(rejected(value,lambda v:v["gate_assessments"].append(copy.deepcopy(v["gate_assessments"][0])),"適格判定重複"))
        def orphan(v):
            """
            機能: 孤立判定。
            引数: v(dict)。
            返り値: None。
            """
            extra=copy.deepcopy(v["gate_assessments"][0]);extra["ordinal"]+=100000;v["gate_assessments"].append(extra)
        answer.append(rejected(value,orphan,"非候補の孤立判定"))
        sid = value["gate_assessments"][0]["assessment"]["decision"]["snapshot_id"]
        idx = next(i for i,g in enumerate(value["chart_grids"]) if g["snapshot_id"] == sid)
        def future(v):
            """
            機能: 共有時計破損。
            引数: v(dict)。
            返り値: None。
            """
            v["chart_grids"][idx]["chart"]["at"]+=1
        answer.append(rejected(value,future,"共有技法の未来時計"))
        def wrong_line(v):
            """
            機能: 特徴原行破損。
            引数: v(dict)。
            返り値: None。
            """
            v["chart_grids"][idx]["current"]["source_line"]+=1
        answer.append(rejected(value,wrong_line,"現在特徴と候補の原行不一致"))
    for key,book in value["actors"].items():
        if book["fills"]:
            def half_fee(v):
                """
                機能: 半円費用破損。
                引数: v(dict)。
                返り値: None。
                """
                v["actors"][key]["fills"][0]["fee_yen"]+=Decimal("0.5")
            answer.append(rejected(value,half_fee,"指定fee半円破損"));break
    for key,book in value["actors"].items():
        if book["entry_opportunities"]:
            def slot(v):
                """
                機能: 再評価枠破損。
                引数: v(dict)。
                返り値: None。
                """
                v["actors"][key]["entry_opportunities"][0]["assigned_at"]+=300
            answer.append(rejected(value,slot,"出生の一回slotを後枠へ変更"))
            def capacity(v):
                """
                機能: 空き破損。
                引数: v(dict)。
                返り値: None。
                """
                v["actors"][key]["entry_opportunities"][0]["available"]=11
            answer.append(rejected(value,capacity,"予約込み片側capを11へ変更"));break
    for key,book in value["actors"].items():
        gates = [i for i,p in enumerate(book["entry_opportunities"]) if "gate" in p]
        if gates:
            index=gates[0]
            def remove_gate(v):
                """
                機能: 機会gate欠落。
                引数: v(dict)。
                返り値: None。
                """
                v["actors"][key]["entry_opportunities"][index].pop("gate")
            answer.append(rejected(value,remove_gate,"適格機会のgate欠落"));break
    for key,book in value["actors"].items():
        notices = [i for i,e in enumerate(book["source_events"]) if e["kind"]=="close_notice"]
        if notices:
            index=notices[0]
            def source_close(v):
                """
                機能: 元返済作用破損。
                引数: v(dict)。
                返り値: None。
                """
                v["actors"][key]["source_events"][index]["actual_exit_requested"]+=1
            answer.append(rejected(value,source_close,"Source返済の比例量破損"));break
    return answer


def main() -> None:
    """
    機能: Go人工と純三値表を検査。
    引数: --fixtures/--out(Path)。
    返り値: None。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    paths=sorted(args.fixtures.glob("*.json"));AGG.need(paths,"実Go人工が必要")
    before={str(p.resolve()):sha(p) for p in [*paths,*HERE.glob("*.py")]}
    rows,mutations={},[]
    pure_count = 0
    for p in paths:
        value=AGG.read_json(p)
        if "cases" in value:
            for case in value["cases"]:
                result = GATE.assess(case["input"],case["candidate"],case["policy"])
                AGG.equal(result,case["assessment"],"純Go型の全field採否")
                pure_count += 1
        if not {"actors","chart_grids","gate_assessments"} <= set(value):continue
        rows[p.name]=verify_fixture(value)
        first = value["actors"][AGG.KEYS[0]]
        replay = {"session":first["session"]["id"],"books":value["actors"],"chart_grids":value["chart_grids"],"gate_assessments":value["gate_assessments"]}
        summary = AGG.analyze_saved([replay],None,"人工")
        AGG.equal(summary["会計数"],16,"人工も集約経路を通す")
        AGG.need("# 96" in AGG.render(summary),"人工Markdown描画")
        mutations.extend({"場面":p.name,**item} for item in financial_fixture_mutations(value))
    AGG.need(rows,"16Actor Go Marshal場面が必要")
    coverage = {key:sum(scene["会計"][key]["玉数"] for scene in rows.values()) for key in AGG.KEYS}
    AGG.need(all(coverage.values()),"全16口座で実取得非0の人工coverageが必要")
    truth=0
    for a in ((True,True),(True,False),(False,False)):
        for b in ((True,True),(True,False),(False,False)):
            result=GATE.conjunction([GATE.check("a",*a,"人工"),GATE.check("b",*b,"人工")])
            expected=(True,False) if a==(True,False) or b==(True,False) else (False,False) if not a[0] or not b[0] else (True,True)
            AGG.equal(result,expected,"三値AND手計算");truth+=1
    after={name:sha(Path(name)) for name in before};AGG.equal(before,after,"人工/コード前後不変")
    proof={"成功":True,"scope":"実Go型APIの金融/技法保存人工。自然Source/実CSV技法/市場未検査", "場面":rows,"純Go全field":pure_count,"全16非0coverage":coverage,"手計算三値":truth,"破損拒否":mutations,"入力SHA256前":before,"入力SHA256後":after,"入力前後不変":True,"金融再生":0,"原板本文読取":0,"95実績の新評価":0}
    AGG.write_json(args.out,proof)
    print(json.dumps({"成功":True,"場面":len(rows),"会計":len(rows)*16,"純Go":pure_count,"破損拒否":len(mutations),"手計算":truth},ensure_ascii=False))


if __name__=="__main__":main()
