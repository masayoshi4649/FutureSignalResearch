"""84の追加AND・旧入口snapshot・A0全会計を固定83/82へ独立に結ぶ。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[2]
POLICIES = ("A0", "C0", "C1")
KEYS = tuple(f"{policy}G1_D{delay}" for delay in (0, 1) for policy in POLICIES)
REQUIRED = {"A0": (), "C0": ("現在価格帯", "反対圧力"), "C1": ("現在価格帯", "反対圧力", "同価格数量支持")}
BASE_PATH = ROOT / "scripts/構造否定と利益配分/基準と入口の照合.py"
BASE_SHA = "a527e9f369304e5969896388dc987f4a1c755b31a0fc8b09351a0edc6fbe65f4"


def sha(path: Path) -> str:
    """
    機能: 入力・読取依存・保存結果の指紋を計算する。
    引数: path (Path) は実ファイル。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def load_base() -> object:
    """
    機能: 固定83の厳密JSON比較・予定時計・旧必須schemaだけを読取再用する。
    引数: なし。既知SHAの停止コードを対象にする。
    返り値: object は比較helperを持つモジュール。市場・Goは実行しない。
    """
    assert sha(BASE_PATH) == BASE_SHA, "固定83比較helperが変わりました"
    spec = importlib.util.spec_from_file_location("固定83照合helper84",BASE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_base()


def checks(direction: dict, audit: object, where: str) -> dict[str, dict]:
    """
    機能: 旧方向から必要な三チェックを欠落・重複・型変化なく読む。
    引数: direction (dict)、audit (Audit)、where (str) は旧方向と検査場所。
    返り値: dict はID別チェック。未知をfalseの既知へ代入しない。
    """
    values = {}
    for index,row in enumerate(direction["checks"]):
        audit.check(set(row)=={"id","group","known","passed","reason"},"旧チェック必須フィールド",where+f"[{index}]",sorted(row),"5キー")
        audit.check(type(row["known"]) is bool and type(row["passed"]) is bool,"旧チェック真偽型",where+f"[{index}]")
        audit.check(not row["passed"] or row["known"],"未知を成立にしない",where+f"[{index}]")
        audit.check(row["id"] not in values,"旧チェック重複なし",where,row["id"],"一意")
        values[row["id"]]=row
    for name in REQUIRED["C1"]:
        audit.check(name in values,"必要チェック欠落なし",where,name,"存在")
        if name in values:
            audit.check(values[name]["group"]=="転換初動枝","旧構造チェックの群",where+name,values[name]["group"],"転換初動枝")
    return values


def resolve(directions: list[dict]) -> dict:
    """
    機能: 旧二方向と同じ唯一許可・未知・競合の規則を独立集約する。
    引数: directions (list[dict]) は買、売の順の二方向。
    返り値: dict はallowed/side/role/reason/required_unknown。
    """
    chosen=[d for d in directions if d["allowed"]]
    if len(chosen)==1:
        d=chosen[0]
        return {"allowed":True,"side":d["side"],"role":d["role"],"reason":d["reason"],"required_unknown":False}
    if len(chosen)>1:
        return {"allowed":False,"side":0,"role":"競合待機","reason":"両方向の現在根拠が競合","required_unknown":False}
    unknown=any(d["required_unknown"] for d in directions)
    return {"allowed":False,"side":0,"role":"判定不能" if unknown else "待機",
            "reason":"買:"+directions[0]["reason"]+"／売:"+directions[1]["reason"],"required_unknown":unknown}


def refined(base: dict, policy: str, audit: object, where: str) -> dict:
    """
    機能: 旧方向の三チェックだけから追加ANDと最終未知・競合保持を独立再計算する。
    引数: base (dict) は固定B1判定、policy (str)、audit (Audit)、where (str)。
    返り値: dict は候補供給前の政策保存値。元EMA・帯生成器は再実装しない。
    """
    audit.check(base["policy"]=="B1","旧入口政策B1",where,base["policy"],"B1")
    audit.check([d["side"] for d in base["directions"]]==[1,-1],"旧方向は買売順",where)
    old_top=resolve(base["directions"])
    BASE.compare({k:base[k] for k in old_top},old_top,audit,where+".base集約","旧二方向集約")
    directions=[]
    for old in base["directions"]:
        selected=checks(old,audit,where+f".side{old['side']}")
        d={k:deepcopy(old[k]) for k in ("side","allowed","role","reason","required_unknown")}
        d["added_checks"]=[]
        if policy!="A0":
            reasons=[] if old["allowed"] else ["旧B1不成立:"+old["reason"]]
            for name in REQUIRED[policy]:
                row=deepcopy(selected[name])
                row["group"]="追加必須"
                d["added_checks"].append(row)
                d["allowed"]=d["allowed"] and row["passed"]
                d["required_unknown"]=d["required_unknown"] or not row["known"]
                if not row["known"]:
                    reasons.append(name+"未知")
                elif not row["passed"]:
                    reasons.append(name+"不成立")
            d["role"]=old["role"] if d["allowed"] else "判定不能" if d["required_unknown"] else "待機"
            if d["allowed"]:
                d["required_unknown"]=False
                d["reason"]=old["role"]+"の現在価格応答成立"
            else:
                d["reason"]="／".join(reasons)
        directions.append(d)
    top=resolve(directions)
    if policy!="A0" and base["role"]=="競合待機":
        top={"allowed":False,"side":0,"role":"競合待機","reason":"旧B1の両方向競合を維持","required_unknown":False}
    return {**top,"directions":directions}


def candidate(session: str, grid: dict, policy: dict) -> dict | None:
    """
    機能: 純採否と時計・直前気配からB1のままの候補を独立構成する。
    引数: session (str)、grid/policy (dict) は当時の共有値と政策採否。
    返り値: dict | None は100枚の候補又は不供給。
    """
    q,at=grid["decision"]["quote"],grid["at"]
    valid=grid["clock_allowed"] and policy["allowed"] and policy["side"] in (-1,1) and bool(grid["window"]) and grid["window"]!="静観"
    valid=valid and all(BASE.finite(q[n]) for n in ("time","last","bid","ask")) and q["valid"] and q["index"]>=0 and q["line"]>0
    valid=valid and q["last"]>0 and q["bid"]>0 and q["ask"]>q["bid"] and 0<=at-q["time"]<=15
    if not valid:
        return None
    side=policy["side"]
    identity=f"{session}_B1_{at:.9f}_{side:+d}"
    return {"id":identity,"internal_id":identity,"parent":identity,"source_id":identity,"method":grid["window"],"owner":"B1",
            "kind":policy["role"],"side":side,"quantity":100,"entry":q["ask"] if side>0 else q["bid"],"at":at,"closing":False}


def bind_book(book: dict, policy: str, delay: int, grids: dict, audit: object, where: str, expected_keys: dict) -> None:
    """
    機能: 外部政策キーを内部S0G1へ結び、候補・定時記録・実新規・固定線を照合する。
    引数: book (dict)、policy (str)、delay (int)、grids (dict)、audit (Audit)、where (str)、expected_keys (dict)。
    返り値: None。占有全時系列・約定先着・出口規範は別原板監査に分担する。
    """
    BASE.validate_book(book,expected_keys,True,audit,where)
    audit.check(book["mode"]=="S0G1" and book["fill_delay_seconds"]==delay,"内部S0G1と外遅延",where,(book["mode"],book["fill_delay_seconds"]),("S0G1",delay))
    for trade in book["trades"]:
        audit.check(trade["method_id"]=="S0G1","約定method_idを保持",where,trade["method_id"],"S0G1")
    ds=book["decisions"]
    audit.check([d["at"] for d in ds]==list(grids),"全定時Book順序",where)
    by_time={d["at"]:d for d in ds}
    requests={}
    by_reference={}
    for order in book["orders"]:
        if order["kind"]!="entry":
            continue
        at=order["request_time"]
        audit.check(at in grids,"新規は予定枠のみ",where,at,"定時")
        audit.check(at not in requests,"同枠の新規一意",where,at,"一注文")
        requests[at]=order
        if at not in grids:
            continue
        g=grids[at]
        expected=candidate(book["session"],g,g["policies"][policy])
        audit.check(expected is not None,"政策拒否から新規を出さない",where+str(at))
        if expected is None:
            continue
        BASE.compare(order["source"],expected,audit,where+str(at)+".source","B1候補全文")
        audit.check(order["reference_id"]==expected["id"] and order["side"]==expected["side"] and order["quantity"]==100 and order["role"]==expected["kind"],"新規ID方向数量役割",where+str(at))
        q=g["decision"]["quote"]
        audit.check((order["request_index"],order["request_line"])==(q["index"],q["line"]),"新規要求の当時原行",where+str(at))
        audit.check(order["reference_id"] not in by_reference,"候補IDへの一度だけ新規",where)
        by_reference[order["reference_id"]]=g["structure_anchor"]
    for at,g in grids.items():
        if at not in by_time:
            continue
        actual=by_time[at]
        q=g["decision"]["quote"]
        audit.check((actual["quote_time"],actual["quote_index"])==(q["time"],q["index"]),"Book定時と共有気配",where+str(at))
        expected=candidate(book["session"],g,g["policies"][policy])
        rows=actual["candidates"]
        if expected is None:
            audit.check(rows==[] and at not in requests and actual["action"]!="新規要求","不供給時の新規なし",where+str(at))
            continue
        audit.check(len(rows)==1,"供給候補のBook記録",where+str(at),len(rows),1)
        if len(rows)!=1:
            continue
        row=rows[0]
        audit.check((row["reference_id"],row["source_quantity"],row["side"],row["role"])==(expected["id"],100,expected["side"],expected["kind"]),"供給候補の属性",where+str(at))
        requested=row["requested_quantity"]
        audit.check(requested in (0,100) and type(requested) is int,"候補要求は0又は100",where+str(at),requested,(0,100))
        audit.check((requested==100)==(at in requests)==(actual["action"]=="新規要求"),"候補要求と実新規注文の同値",where+str(at))
        if requested==0:
            audit.check(actual["action"] in ("保有継続","処理中") and row["reason"]=="実保有又は新規待機で占有","占有による不参加を分離",where+str(at))
        else:
            audit.check(row["reason"]=="定時の現在根拠","採用理由の保持",where+str(at))
    for container in BASE.CONTAINERS:
        for index,row in enumerate(book[container]):
            anchor=by_reference.get(row["reference_id"])
            audit.check(anchor is not None,"構造線の新規源",where+container+str(index))
            if anchor is not None:
                BASE.compare(row["structure_anchor"],anchor,audit,where+container+str(index),"要求時線固定")


def policy_action(financial: str, clock_allowed: bool, required_unknown: bool) -> str:
    """
    機能: 非占有で時計許可中の金融待ちだけを純必須未知へ結ぶ。
    引数: financial (str) は保存金融action、clock_allowed/required_unknown (bool) は当時の純判断。
    返り値: str は方針上の分類。保有・処理中・新規・気配不能を優先する。
    """
    return "判定不能" if financial=="待ち" and clock_allowed and required_unknown else financial


def audit_scene(current: dict, old83: dict, old82: dict, session: str, times: list[float], audit: object) -> dict:
    """
    機能: 一場の全保存判断、追加AND、三政策包含、旧二世代基準を検査する。
    引数: current/old83/old82 (dict)、session (str)、times (list[float])、audit (Audit)。
    返り値: dict は場別予定数・許可・候補・初動の小型計数。
    """
    expected_keys=BASE.schemas()
    for value,name in ((current,"84"),(old83,"83"),(old82,"82")):
        BASE.inspect_finite(value,audit,session+name)
        audit.check(set(value)=={"session","quality","books","grid_decisions"} and value["session"]==session,"場本文schema",session+name)
    audit.check(set(current["books"])==set(KEYS),"84六会計集合",session)
    audit.check(set(old83["books"])==set(BASE.KEYS),"旧83八会計集合",session)
    audit.check(set(old82["books"])==BASE.BASE_KEYS,"旧82四会計集合",session)
    BASE.compare(current["quality"],old83["quality"],audit,session,"83原板品質全文")
    BASE.compare(current["quality"],old82["quality"],audit,session,"82原板品質全文")
    grids=current["grid_decisions"]
    audit.check([g["at"] for g in grids]==times,"84全予定枠順序",session)
    audit.check([g["at"] for g in old83["grid_decisions"]]==times,"83全予定枠順序",session)
    old82_grids=[g for g in old82["grid_decisions"] if g["entry_policy"]=="B1"]
    audit.check([g["at"] for g in old82_grids]==times and len(old82["grid_decisions"])==2*len(times),"82全政策予定枠",session)
    count=Counter()
    by_time={}
    for index,g in enumerate(grids):
        where=f"{session}.grid[{index}]"
        at=g["at"]
        audit.check(at not in by_time,"定時重複なし",where)
        by_time[at]=g
        audit.check(set(g["policies"])==set(POLICIES),"政策集合A0C0C1",where)
        if index<len(old83["grid_decisions"]):
            BASE.compare({k:v for k,v in g.items() if k!="policies"},old83["grid_decisions"][index],audit,where,"83旧snapshot全文")
        if index<len(old82_grids):
            BASE.compare({k:v for k,v in g.items() if k not in ("policies","structure_anchor")},old82_grids[index],audit,where,"82旧snapshot全文")
        BASE.compare(g["structure_anchor"],BASE.expected_anchor(at,g["decision"]["technical"]),audit,where,"当時EMA線")
        audit.check(g["decision"]["at"]==at and g["entry_policy"]=="B1","旧B1時計保持",where)
        for policy in POLICIES:
            actual=g["policies"][policy]
            expected=refined(g["decision"],policy,audit,where+policy)
            expected["candidate_accepted"]=candidate(session,g,expected) is not None
            BASE.compare(actual,expected,audit,where+policy,"追加ANDと最終集約全文")
            count[policy+":許可"]+=expected["allowed"]
            count[policy+":候補"]+=expected["candidate_accepted"]
            count[policy+":必須未知"]+=expected["required_unknown"]
            count[policy+":既知不許可"]+=not expected["allowed"] and not expected["required_unknown"]
            count[policy+":許可初動"]+=expected["allowed"] and expected["role"]=="転換初動"
        audit.check(g["candidate_accepted"]==g["policies"]["A0"]["candidate_accepted"],"top供給はA0保持",where)
        a,c0,c1=(g["policies"][p] for p in POLICIES)
        for label,left,right in (("C0はA0に包含",c0,a),("C1はC0に包含",c1,c0)):
            audit.check(not left["allowed"] or (right["allowed"] and left["side"]==right["side"] and left["role"]==right["role"]),label,where)
            audit.check(not left["candidate_accepted"] or right["candidate_accepted"],label+"候補",where)
        for index_d,old in enumerate(g["decision"]["directions"]):
            directions=[g["policies"][p]["directions"][index_d] for p in POLICIES]
            audit.check(not directions[2]["allowed"] or directions[1]["allowed"],"C1片側包含",where)
            audit.check(not directions[1]["allowed"] or directions[0]["allowed"],"C0片側包含",where)
            if old["allowed"] and old["role"]=="転換初動":
                audit.check(all(d["allowed"] and d["role"]=="転換初動" for d in directions),"旧初動の全政策保持",where)
        if g["decision"]["role"]=="競合待機":
            audit.check(all(not g["policies"][p]["allowed"] and g["policies"][p]["role"]=="競合待機" for p in POLICIES),"旧競合からの復活禁止",where)
    for policy in POLICIES:
        for delay in (0,1):
            key=f"{policy}G1_D{delay}"
            bind_book(current["books"][key],policy,delay,by_time,audit,session+key,expected_keys)
    for delay in (0,1):
        book=current["books"][f"A0G1_D{delay}"]
        BASE.validate_book(old83["books"][f"S0G1_D{delay}"],expected_keys,True,audit,session+".83基準")
        BASE.compare(book,old83["books"][f"S0G1_D{delay}"],audit,session+f".A0D{delay}","A0対83全会計")
        BASE.validate_book(old82["books"][f"B1G1_D{delay}"],expected_keys,False,audit,session+".82基準")
        BASE.compare(BASE.project(book),old82["books"][f"B1G1_D{delay}"],audit,session+f".A0D{delay}","A0対82全旧会計")
    actions=[]
    for key in KEYS:
        policy=key[:2]
        book=current["books"][key]
        financial=Counter()
        interpreted=Counter()
        for d in book["decisions"]:
            financial[d["action"]]+=1
            g=by_time.get(d["at"])
            action=d["action"] if g is None else policy_action(d["action"],g["clock_allowed"],g["policies"][policy]["required_unknown"])
            interpreted[action]+=1
        audit.check(sum(financial.values())==sum(interpreted.values())==len(times),"方針判断は全枠を保持",session+key)
        actions.append({"session":session,"key":key,"金融判断":dict(financial),"方針判断":dict(interpreted)})
    return {"場":session,"予定枠":len(grids),"基準会計":2,"政策件数":dict(count),"方針判断":actions}


def audit_directories(source: Path, baseline: Path, previous: Path, sessions: list[str], pins83: dict | None, pins82: dict | None, audit: object) -> dict:
    """
    機能: 全66場2442枠を固定二世代の本文指紋へ結び、前後不変を検査する。
    引数: source/baseline/previous (Path) は84/83/82保存根、sessions (list[str])、pins83/pins82 (dict | None)、audit (Audit)。
    返り値: dict は完了・入力指紋・場別証拠。欠落・余剰・例外を成功にしない。
    """
    folders={"84":source,"83":baseline,"82":previous}
    before={name:BASE.inventory(folder) for name,folder in folders.items()}
    wanted={s+".json" for s in sessions}
    audit.check(len(sessions)==len(set(sessions))==66,"固定66場","全体")
    for name,values in before.items():
        audit.check(set(values)==wanted,"全保存場集合",name,sorted(values),sorted(wanted))
    for name,pins in (("83",pins83),("82",pins82)):
        if pins is not None:
            audit.check(before[name]==pins,"固定旧本文指紋",name)
    rows=[]
    complete=True
    try:
        for session in sessions:
            if any(session+".json" not in before[n] for n in folders):
                continue
            values=[BASE.read_json(folders[n]/(session+".json")) for n in ("84","83","82")]
            rows.append(audit_scene(*values,session,BASE.scheduled(session),audit))
    except Exception as error:
        complete=False
        audit.check(False,"読取処理未完","全体",type(error).__name__+":"+str(error),"全場完了")
    after={name:BASE.inventory(folder) for name,folder in folders.items()}
    audit.check(before==after,"入力集合と本文の前後不変","全体")
    frames=sum(r["予定枠"] for r in rows)
    audit.check(len(rows)==66 and frames==2442,"66場2442枠完了","全体",(len(rows),frames),(66,2442))
    totals=Counter()
    for row in rows:
        totals.update(row["政策件数"])
    return {"処理完了":complete and len(rows)==66 and frames==2442,"場数":len(rows),"予定枠":frames,"基準会計数":sum(r["基準会計"] for r in rows),
        "入力不変":before==after,"入力SHA256前":before,"入力SHA256後":after,"対象場":rows,
        "政策件数合計":dict(totals),"政策全予定枠":{p:frames for p in POLICIES},"方針判断":[a for r in rows for a in r["方針判断"]]}


def fixture(session: str, times: list[float], conditions: tuple[tuple[bool,bool],...] = ((True,True),(True,True),(True,True)), role: str = "順行", conflict: bool = False, clock_allowed: bool = True) -> tuple[dict,dict,dict]:
    """
    機能: 非0約定と全政策・全定時を持つ保存JSON人工を自己完結で組み立てる。
    引数: session (str)、times (list[float])、conditions (tuple) は帯/圧力/数量の既知成立、role (str)、conflict/clock_allowed (bool)。
    返り値: tuple[dict,dict,dict] は84/83/82人工。市場再生や実約定検証を意味しない。
    """
    expected_keys=BASE.schemas()
    old83,old82=BASE.fixture(session,times[0],expected_keys)
    grids=[]
    for index,at in enumerate(times):
        ds=[]
        for side in (1,-1):
            allowed=index==0 and (side==1 or conflict)
            selected=[]
            for name,(known,passed) in zip(REQUIRED["C1"],conditions):
                selected.append({"id":name,"group":"転換初動枝","known":known,"passed":passed,"reason":name+"の人工"})
            ds.append({"side":side,"allowed":allowed,"required_unknown":False,"role":role if allowed else "待機",
                "reason":role+"の現在根拠成立" if allowed else "人工不成立","checks":selected})
        top=resolve(ds)
        decision={"at":at,"policy":"B1",**top,"directions":ds,"quote":{"time":at,"last":1005,"bid":1000,"ask":1010,"valid":True,"index":10+index,"line":20+index},
            "technical":{"exit_known":True,"ema8_3":1000,"bar3_end":at},"chart_pair":{"previous3_known":True},"evidence":{"source_line":20+index}}
        g={"at":at,"window":"D164_15","entry_policy":"B1","decision":decision,"clock_allowed":clock_allowed,"block_reason":"" if clock_allowed else "人工時計拒否",
           "candidate_accepted":candidate(session,{"decision":decision,"at":at,"clock_allowed":clock_allowed,"window":"D164_15"},top) is not None,
           "structure_anchor":BASE.expected_anchor(at,decision["technical"])}
        grids.append(g)
    old83["grid_decisions"]=deepcopy(grids)
    old82["grid_decisions"]=[]
    for g in grids:
        for p in ("B0","B1"):
            v={k:deepcopy(x) for k,x in g.items() if k!="structure_anchor"}
            v["entry_policy"]=p
            v["decision"]["policy"]=p
            old82["grid_decisions"].append(v)
    current={"session":session,"quality":deepcopy(old83["quality"]),"books":{},"grid_decisions":deepcopy(grids)}
    scratch=BASE.Audit()
    for g in current["grid_decisions"]:
        g["policies"]={}
        for p in POLICIES:
            value=refined(g["decision"],p,scratch,"人工")
            value["candidate_accepted"]=candidate(session,g,value) is not None
            g["policies"][p]=value
    assert scratch.bad==0,scratch.examples
    for policy in POLICIES:
        for delay in (0,1):
            book=deepcopy(old83["books"][f"S0G1_D{delay}"])
            book["decisions"]=[]
            first=current["grid_decisions"][0]
            src=candidate(session,first,first["policies"][policy])
            if src is None:
                for name in ("trades","orders","closed","lots","positions","pending_entries"):
                    book[name]=[]
                book["metrics"]=dict.fromkeys(book["metrics"],0)
            else:
                entry=book["orders"][0]
                entry.update(reference_id=src["id"],source=src,request_time=times[0],request_index=10,request_line=20,quantity=100,role=role)
                for name in BASE.CONTAINERS:
                    for row in book[name]:
                        row["reference_id"]=src["id"]
                        row["structure_anchor"]=deepcopy(first["structure_anchor"])
                for row in book["trades"]:
                    row["method_id"]="S0G1"
            for g in current["grid_decisions"]:
                src=candidate(session,g,g["policies"][policy])
                cs=[] if src is None else [{"reference_id":src["id"],"source_quantity":100,"requested_quantity":100,"side":src["side"],"role":src["kind"],"reason":"定時の現在根拠"}]
                book["decisions"].append({"at":g["at"],"quote_time":g["decision"]["quote"]["time"],"quote_index":g["decision"]["quote"]["index"],
                    "action":"新規要求" if src is not None else "待ち","reason":"人工","candidates":cs})
            current["books"][f"{policy}G1_D{delay}"]=book
    for delay in (0,1):
        old83["books"][f"S0G1_D{delay}"]=deepcopy(current["books"][f"A0G1_D{delay}"])
        old82["books"][f"B1G1_D{delay}"]=BASE.project(current["books"][f"A0G1_D{delay}"])
    return current,old83,old82


def self_test() -> dict:
    """
    機能: 非0保存人工・三状態・初動・競合・一値破損・66場集合を検査する。
    引数: なし。新旧の本物保存結果は読まない。
    返り値: dict は全人工証拠。市場原板・Goを実行しない。
    """
    session="2026-11-02_Day"
    at=BASE.scheduled(session)[0]
    good=fixture(session,[at])
    results=[]
    cases=[("全既知成立",{}),("数量既知不成立",{"conditions":((True,True),(True,True),(True,False))}),
           ("帯既知不成立",{"conditions":((True,False),(True,True),(True,True))}),
           ("圧力未知",{"conditions":((True,True),(False,False),(True,True))}),
           ("初動保持",{"role":"転換初動"}),("旧競合保持",{"conflict":True}),("時計拒否は純許可と別",{"clock_allowed":False})]
    for label,options in cases:
        current,old83,old82=fixture(session,[at],**options)
        audit=BASE.Audit()
        row=audit_scene(current,old83,old82,session,[at],audit)
        assert audit.bad==0,(label,audit.examples)
        if label=="圧力未知":
            for action in row["方針判断"]:
                if action["key"].startswith("C"):
                    assert action["金融判断"]=={"待ち":1} and action["方針判断"]=={"判定不能":1}
        results.append({"人工":label,"照合":audit.count,"不一致":0})
    conflicted=list(fixture(session,[at],conflict=True))
    for container in conflicted:
        for g in container["grid_decisions"]:
            sell=g["decision"]["directions"][1]
            next(c for c in sell["checks"] if c["id"]=="現在価格帯")["passed"]=False
    scratch=BASE.Audit()
    g=conflicted[0]["grid_decisions"][0]
    for p in POLICIES:
        decision=refined(g["decision"],p,scratch,"競合人工")
        decision["candidate_accepted"]=candidate(session,g,decision) is not None
        g["policies"][p]=decision
    audit=BASE.Audit()
    audit_scene(*conflicted,session,[at],audit)
    assert audit.bad==0 and g["policies"]["C0"]["directions"][0]["allowed"] and not g["policies"]["C0"]["directions"][1]["allowed"] and not g["policies"]["C0"]["allowed"],audit.examples
    results.append({"人工":"旧競合から一方向だけ残っても新規復活しない","照合":audit.count,"不一致":0})
    for action in ("保有継続","処理中","新規要求","判定不能"):
        assert policy_action(action,True,True)==action
    assert policy_action("待ち",False,True)=="待ち" and policy_action("待ち",True,False)=="待ち" and policy_action("待ち",True,True)=="判定不能"
    results.append({"人工":"方針未知より保有処理中新規気配不能を優先","成功":True})
    mutations=(
        ("policy許可反転",lambda v:v["grid_decisions"][0]["policies"]["C0"].update(allowed=False)),
        ("policy未知反転",lambda v:v["grid_decisions"][0]["policies"]["C1"].update(required_unknown=True)),
        ("追加チェック改変",lambda v:v["grid_decisions"][0]["policies"]["C1"]["directions"][0]["added_checks"][0].update(passed=False)),
        ("追加チェック欠落",lambda v:v["grid_decisions"][0]["policies"]["C0"]["directions"][0]["added_checks"].pop()),
        ("既存snapshot改変",lambda v:v["grid_decisions"][0]["decision"]["evidence"].update(source_line=99)),
        ("新規source変化",lambda v:v["books"]["C0G1_D0"]["orders"][0]["source"].update(owner="C0")),
        ("B1候補ID不維持",lambda v:v["books"]["C1G1_D1"]["orders"][0].update(reference_id="C1候補")),
        ("A0金額1円",lambda v:v["books"]["A0G1_D0"]["metrics"].update(net_pnl_yen=2801)),
        ("A0価格1pt",lambda v:v["books"]["A0G1_D1"]["trades"][0].update(price=1011)),
        ("内部mode変更",lambda v:v["books"]["C1G1_D0"].update(mode="C1G1")),
        ("約定method変更",lambda v:v["books"]["C0G1_D0"]["trades"][0].update(method_id="C0G1")),
        ("候補要求0へ変更",lambda v:v["books"]["C1G1_D0"]["decisions"][0]["candidates"][0].update(requested_quantity=0)),
        ("構造線1pt",lambda v:v["books"]["C0G1_D1"]["lots"][0]["structure_anchor"].update(price=999)),
        ("余剰会計",lambda v:v["books"].update(S0G1_D0=deepcopy(v["books"]["A0G1_D0"]))),
        ("重複定時",lambda v:v["grid_decisions"].append(deepcopy(v["grid_decisions"][0]))),
    )
    for label,mutate in mutations:
        current,old83,old82=deepcopy(good)
        mutate(current)
        audit=BASE.Audit()
        audit_scene(current,old83,old82,session,[at],audit)
        assert audit.bad>0,label
        results.append({"人工":label,"検出":audit.bad})
    current,old83,old82=deepcopy(good)
    for book in (current["books"]["A0G1_D0"],old83["books"]["S0G1_D0"]):
        book["metrics"].pop("total_cost_yen")
    audit=BASE.Audit()
    audit_scene(current,old83,old82,session,[at],audit)
    assert audit.bad>0
    results.append({"人工":"両側同一旧必須欄削除","検出":audit.bad})
    with tempfile.TemporaryDirectory(prefix="84形式人工_",dir=ROOT/"work") as temp:
        path=Path(temp)/"不正.json"
        for text in ('{"x":1,"x":2}','{"x":NaN}'):
            path.write_text(text,encoding="utf-8")
            try:
                BASE.read_json(path)
            except ValueError:
                results.append({"人工":"重複又はNaNを形式拒否","成功":True})
            else:
                raise AssertionError("不正形式を許可しました")
    with tempfile.TemporaryDirectory(prefix="84保存人工_",dir=ROOT/"work") as temp:
        roots=[Path(temp)/name for name in ("84","83","82")]
        for folder in roots:
            folder.mkdir()
        sessions=[]
        for i in range(33):
            for kind in ("Day","Night"):
                name=(datetime(2026,1,1)+timedelta(days=i)).date().isoformat()+"_"+kind
                sessions.append(name)
                for folder,value in zip(roots,fixture(name,BASE.scheduled(name))):
                    (folder/(name+".json")).write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
        audit=BASE.Audit()
        data=audit_directories(*roots,sessions,BASE.inventory(roots[1]),BASE.inventory(roots[2]),audit)
        assert audit.bad==0 and data["処理完了"] and data["基準会計数"]==132,audit.examples
        results.append({"人工":"全66保存2442枠132基準会計","照合":audit.count,"不一致":0})
        (roots[0]/(sessions[0]+".json")).unlink()
        (roots[0]/"余剰.json").write_text("{}",encoding="utf-8")
        bad=BASE.Audit()
        data=audit_directories(*roots,sessions,None,None,bad)
        assert bad.bad>0 and not data["処理完了"]
        results.append({"人工":"欠落と余剰を未完として検出","検出":bad.bad})
    return {"成功":True,"人工系列":len(results),"人工":results,"正式新保存結果読取":0,"本物原板読取":0,"新売買再生":0}


def main() -> None:
    """
    機能: 全66保存結果を二世代へ照合し、未完・不一致も新規証拠に残す。
    引数: --input/--baseline/--out (Path) 又は --self-test (bool)。
    返り値: None。正式検査は失敗なら非0終了、人工は市場を読まない。
    """
    parser=argparse.ArgumentParser()
    for name in ("input","baseline","out"):
        parser.add_argument("--"+name,type=Path)
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        if any((args.input,args.baseline,args.out)):
            raise ValueError("人工と正式入力を混在させません")
        print(json.dumps(self_test(),ensure_ascii=False))
        return
    if not all((args.input,args.baseline,args.out)):
        raise ValueError("input/baseline/outを全て明示してください")
    if args.out.exists() or any(args.out.resolve().is_relative_to(p.resolve()) for p in (args.input,args.baseline)):
        raise ValueError("新規証拠を入力外へ保存してください")
    audit=BASE.Audit()
    small={}
    data={"処理完了":False,"場数":0,"予定枠":0,"基準会計数":0,"入力不変":False}
    try:
        manifest=ROOT/"study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
        result83=ROOT/"study/00083_構造否定と利益配分/成果物/結果.json"
        result82=ROOT/"study/00082_チャートの現在性と補助確認/成果物/結果.json"
        conditions=[ROOT/f"study/{name}/条件.json" for name in ("00083_構造否定と利益配分","00082_チャートの現在性と補助確認")]
        fixed_code=ROOT/"scripts/定時の現在根拠と部分利益保護/actual.go"
        small={p.relative_to(ROOT).as_posix():sha(p) for p in (manifest,result83,result82,BASE_PATH,fixed_code,*conditions)}
        sessions=[s["id"] for s in BASE.read_json(manifest)["sessions"]]
        for path in conditions:
            for name,wanted in BASE.read_json(path)["コードと依存SHA256"].items():
                audit.check(sha(ROOT/name)==wanted,"固定旧金融依存",name)
        data=audit_directories(args.input.resolve(),args.baseline.resolve(),ROOT/"work/82現在性/全66場",sessions,
            BASE.read_json(result83)["再生結果SHA256"],BASE.read_json(result82)["再生結果SHA256"],audit)
        audit.check({p:sha(ROOT/p) for p in small}==small,"小型固定依存の前後不変","全体")
    except Exception as error:
        audit.check(False,"全体処理未完","全体",type(error).__name__+":"+str(error),"完了")
    success=data["処理完了"] and audit.bad==0
    output={"試行":84,"成功":success,**data,"照合項目数":audit.count,"不一致数":audit.bad,"不一致":audit.examples,
        "項目別比較数":dict(audit.scope),"固定小型入力SHA256":small,"照合コードSHA256":sha(Path(__file__)),"読取helperSHA256":BASE_SHA,
        "新売買再生":0,"本物原板読取":0,"範囲外":["元EMA・ATR等の独立系列生成","元FAR帯・数量回復生成器の再実装","実占有全時系列・約定先着・出口床の再計算（別原板監査）"]}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")
    print(json.dumps({k:output[k] for k in ("成功","場数","予定枠","基準会計数","照合項目数","不一致数")},ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__=="__main__":
    main()
