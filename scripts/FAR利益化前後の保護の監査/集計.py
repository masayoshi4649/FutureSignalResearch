"""100のE3S固定P0/H0/HGを保存検算し、実現額・日別・Viewerへ変換する市場前試作。"""

import argparse
from collections import Counter, defaultdict
import copy
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import types


ROOT=Path(__file__).resolve().parents[2]
OLD_PATH=ROOT/"scripts/FAR背景と勢いと数量の監査/集計.py"
OLD_SHA="f5d6635e17e0e7bb3be8d5941e0adf7568f75251ce1a505b8090372289d2a69c"
INDEPENDENT_PATH=ROOT/"scripts/FAR利益化前後の保護の監査/費用前ガードと金融の照合.py"
INDEPENDENT_SHA="d6b2eb4dc18c082f3acf39dbc2f74553b127e0e1491bd601671c7e50c17aa6e7"
MARKET_PATH=ROOT/"scripts/FAR利益化前後の保護の監査/市場Tapeを照合する.py"
MARKET_SHA="b32a9be89b6c1ea6853126fba35b8ebc2b352be843b0ed723559624888f5b5c8"
CONDITION_SHA="e233bae9d36bbdf6b171a644cfba006bf0c4c157ff7f97dd086b52128c55fdbf"
PROOF99_SHA="8c2a30e1073126038e2a6a9c370f945ac258164877be6a250afb1c683fbbf5c8"
COMPLETION_SHA={"first2":"74b8904136516759bd97028084922aa0cd46f039dd8fbf447075bc1aa0a8d1a1","full54":"d44180708c6d7be949820ebf93401201242905aff7834a50104586bbe871b1e6"}
AUDIT_SHA={"first2":"8f4dbe2b58261897c306d90909d16414a34c056eba911ac1dea8eb63a258f452","full54":"4382cfd70f561c3323a2d6f7a4be453f02c3fa45cf851e8254b772e1d1fe9b00"}


def digest(path: Path) -> str:
    """
    機能: 明示ファイルの指紋を計算する。
    引数: path(Path)はコード又は許可保存。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed(name: str,path: Path,expected: str):
    """
    機能: 停止した保存共通規範と独立E3S部品を再用する。
    引数: name/expected(str)、path(Path)は識別・指紋・部品先。
    返り値: moduleは固定読取部品。市場やSourceを動かさない。
    """
    if digest(path)!=expected:raise ValueError("固定保存部品SHA差:"+str(path))
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value


OLD=fixed("固定99保存算術100",OLD_PATH,OLD_SHA)
INDEPENDENT=fixed("独立100HGと純式保存100",INDEPENDENT_PATH,INDEPENDENT_SHA)
BASE,DIAG=OLD.BASE,OLD.DIAG
BIRTH,GRID=OLD.OLD.OLD.OLD.OLD,OLD.OLD.OLD.OLD
need,equal,number,integer=OLD.need,OLD.equal,OLD.number,OLD.integer
KEYS=INDEPENDENT.KEYS
POSITION_FIELDS={"id","entry_order_id","source","source_hold_id","side","initial_quantity","quantity","reserved","closed_quantity","entry_price","entry_quote","closed_quote","gross_yen","realized_net","peak_gain","has_mark","protection_active","activation","floor_gain","floor_updated","first_floor_hit","atr","marks"}
ORDER_FIELDS={"id","kind","side","quantity","position_id","source","source_hold_id","native_close_signal_id","native_close_notice_id","request_time","request_quote","reason","status","fill_id","cancel_time","cancel_reason","protection_point"}
FILL_FIELDS={"id","order_id","position_id","action","side","quantity","price","quote","source","source_hold_id","native_close_signal_id","native_close_notice_id","reason","fee_yen","slip_yen","gross_yen","net_contribution_yen","allocations"}
HG_METRICS={"gross_guard_exit_requests","gross_guard_exit_fills"}


def exit_policy(key: str) -> str:
    """
    機能: 12本名KeyからP0/H0/HGを区別する。
    引数: key(str)はActor外名。
    返り値: strは出口名。P0は空Harvestの既存表現を保つ。
    """
    need(key in KEYS,"100の12Key")
    return "H0" if key.startswith("H0_") else "HG" if key.startswith("HG_") else "P0"


def key_config(key: str) -> tuple:
    """
    機能: 本名を保ったまま共通金融の名前と費用を対応させる。
    引数: key(str)は100Key。
    返り値: tupleはE3S,risk空,newKey,old95,old94,cost,delay。
    """
    exit_policy(key);tail=key.split("_");cost,delay=int(tail[-2][1:]),int(tail[-1][1:]);common=f"P0_C{cost}_D{delay}"
    return "E3S","",key,"B5Q_"+common,common,cost,delay


def grid_key_config(key: str) -> tuple:
    """
    機能: 固定出生枠算術へ本名E3Sと共通会計名を渡す。
    引数: key(str)は100Key。
    返り値: tupleはgate,old95,old94,cost,delay。
    """
    gate,_,_,old95,old94,cost,delay=key_config(key);return gate,old95,old94,cost,delay


def accepted_entries_at_grid(book: dict,at,q) -> set:
    """
    機能: 実受理済み新規だけを同秒の容量算術へ渡す。
    引数: book(dict)、at(number)、q(dict|None)は原保存と当枠。
    返り値: set[str]は元実注文ID。架空受理・再時刻化は行わない。
    """
    return BIRTH.accepted_entries_at_grid(dict(book,key=key_config(book["key"])[3]),at,q)


class SavedGates(OLD.SavedGates):
    """固定E3Sの現在候補を100の全12Keyへ結ぶ保存索引。"""

    def __init__(self,value: dict):
        """
        機能: 新100独立constructorへ共有文脈と本名5tagを渡す。
        引数: value(dict)は100保存。
        返り値: None。金融Decimalと元Go純式floatを分離する。
        """
        self.audit=INDEPENDENT.Audit();contexts=OLD.pure_values(value["chart_grids"])
        pure_record={**value,"chart_grids":contexts,"gate_assessments":OLD.pure_values(value["gate_assessments"])}
        self.core=INDEPENDENT.RecomputedGates(contexts,pure_record,self.audit)
        self.by_at={g["at"]:g for g in contexts};equal(len(self.by_at),len(contexts),"100共有枠一意")
        ranks={key:n for n,key in enumerate(KEYS)}
        order=[(r["candidate"]["at"],ranks[r["key"]],r["ordinal"]) for r in value["gate_assessments"]]
        equal(order,sorted(order),"100純式の時計/12Key/ordinal順")


def order_classes(book: dict) -> dict:
    """
    機能: 原注文と実返済をSource/H/HGへ排他的に数える。
    引数: book(dict)は100口座。
    返り値: dictは常に三原因と要求/約定の回数・枚数を持つ。
    """
    rows={n:{"要求回数":0,"要求枚数":0,"約定回数":0,"約定枚数":0} for n in ("Source","H","HG")}
    orders={o["id"]:o for o in book["orders"]}
    for o in orders.values():
        if o["kind"]!="exit":continue
        need(not(o.get("gross_guard_point") is not None and o["protection_point"] is not None),"HG/H混在禁止")
        cause="HG" if "gross_guard_point" in o else "H" if o["protection_point"] is not None else "Source"
        rows[cause]["要求回数"]+=1;rows[cause]["要求枚数"]+=o["quantity"]
    for f in book["fills"]:
        if f["action"]!="close":continue
        o=orders[f["order_id"]];cause="HG" if "gross_guard_point" in o else "H" if o["protection_point"] is not None else "Source"
        rows[cause]["約定回数"]+=1;rows[cause]["約定枚数"]+=f["quantity"]
    return rows


def verify_hg_state(position: dict,policy: str,timeline) -> None:
    """
    機能: HG optional三点を落とさず当時FillのMTM・符号・時系列へ結ぶ。
    引数: position(dict)、policy(str)、timeline(Timeline)は実玉・出口・共通会計履歴。
    返り値: None。初回点の取り落としや全経路の不存在は別独立監査へ分担する。
    """
    expected=POSITION_FIELDS|({"gross_guard"} if "gross_guard" in position else set())
    equal(set(position),expected,"100Position全tag/未知field拒否")
    if "gross_guard" not in position:return
    need(policy=="HG" and type(position["gross_guard"]) is dict,"HGだけに実観測状態")
    state=position["gross_guard"];equal(set(state),{"activation","first_hit","profit_transition"},"HG三点全tag")
    need(type(state["activation"]) is dict,"HG起動は非null実MTM")
    first,last=position["marks"]["first"],position["marks"]["last"]
    need(first is not None and last is not None,"HG観測の範囲")
    for name,point in state.items():
        if point is None:continue
        timeline.verify_position_point(position["id"],point)
        need(BASE.point_order(first)<=BASE.point_order(point)<=BASE.point_order(last),"HG点は実MTM範囲内:"+name)
    activation=state["activation"]
    need(activation["gain_points"]>0 and activation["unit_net"]<=0,"HG起動は費用前進行かつ費用未回収")
    hit=state["first_hit"]
    if hit is not None:
        need(hit["gain_points"]<=0 and hit["unit_net"]<=0,"HG first_hitの正常床0成立")
        need(BASE.point_order(activation)<BASE.point_order(hit),"HG起動後の初hit")
    transition=state["profit_transition"]
    equal(transition is not None,position["protection_active"],"HGから旧利益flagへの移行")
    if transition is not None:
        need(transition["unit_net"]>0 and BASE.point_order(activation)<BASE.point_order(transition),"HGの不可逆strictu移行")
        equal(transition,position["activation"],"HG移行と旧H0起動点同値")
        if hit is not None:need(BASE.point_order(hit)<BASE.point_order(transition),"利益後のHG hit禁止")


def verify_saved_book(book: dict,key: str,gates: SavedGates,full_clock: bool) -> dict:
    """
    機能: 共通金融/H0/P0とHGの新全field・自己予約・原因別計数を明示検算する。
    引数: book(dict)、key(str)、gates(SavedGates)、full_clock(bool)は保存と範囲。
    返り値: dictは原注文分類を維持する会計。HGをSource/Hへ成績上混ぜない。
    """
    policy=exit_policy(key);_,_,_,_,common,cost,delay=key_config(key)
    equal(book["key"],key,"100本名Key")
    expected={"policy":"P0","entry_timing":"B5Q","us_open":book["config"]["us_open"],"gate_policy":"E3S","slip_pts":cost,"delay_seconds":delay}
    if policy!="P0":expected["harvest_policy"]=policy
    equal(book["config"],expected,"100全設定/P0空Harvest/H0/HG")
    equal(set(book),{"session","key","config","orders","fills","positions","source_events","metrics","totals","account","finished","complete","failure","stream_scope","entry_opportunities","grid_traces","grid_metrics"},"100金融top全tag")
    equal(book["stream_scope"],"固定93と同じLast>0のSource受理行。Last0未供給数は共有qualityを参照。","100観測scope")
    equal(set(book["metrics"])-HG_METRICS,INDEPENDENT.BASE.METRIC_FIELDS,"100共通metrics全tag")
    for name in HG_METRICS&set(book["metrics"]):need(policy=="HG" and integer(book["metrics"][name],name,1)>0,"HGだけの非0optional計数")
    for o in book["orders"]:
        equal(set(o),ORDER_FIELDS|({"gross_guard_point"} if "gross_guard_point" in o else set()),"100Order全tag")
        if "gross_guard_point" in o:need(policy=="HG" and type(o["gross_guard_point"]) is dict,"HG専用非nullpoint")
    for fill in book["fills"]:equal(set(fill),FILL_FIELDS,"100実Fill全tag")
    classes=order_classes(book)
    proxy={n:copy.deepcopy(v) for n,v in book.items() if n not in {"entry_opportunities","grid_traces","grid_metrics"}}
    proxy["key"],proxy["config"]=common,{"policy":"P0","slip_pts":cost,"delay_seconds":delay}
    # 共通Timelineの自己保護はSource後予約。HGも同位相なので内部会計だけ明示対応する。
    # 原HG三点・原注文・原counterは下の専用検査と出力へ保持し、旧H0扱いの採否は行わない。
    for o in proxy["orders"]:
        if "gross_guard_point" in o:o["protection_point"]=copy.deepcopy(o["gross_guard_point"])
    for name in HG_METRICS:proxy["metrics"].pop(name,None)
    proxy["metrics"]["protection_exit_requests"]+=classes["HG"]["要求回数"]
    proxy["metrics"]["protection_exit_fills"]+=classes["HG"]["約定回数"]

    def source_validator(projected,orders,timeline):
        """
        機能: 元Source出生/量/返済/取消を固定B5Q規範へ結ぶ。
        引数: projected/orders(dict)、timeline(Timeline)は共通金融の当時履歴。
        返り値: None。HGのSource後自己予約をSource予約と誤計上しない。
        """
        BIRTH.verify_source_b(book,orders,timeline)

    def marks_validator(p: dict,timeline,intrinsic: str):
        """
        機能: 旧MTMとP0固定幅/H0最低床を保ち、HG三点を別に検査する。
        引数: p(dict)、timeline(Timeline)、intrinsic(str)は実玉と共通Policy。
        返り値: None。全Scalarの初回・極値完全性は独立d6b2へ分担する。
        """
        BASE.verify_marks(p,timeline,intrinsic);verify_hg_state(p,policy,timeline)
        if p["protection_active"]:
            floor=number(p["floor_gain"],"保護床");minimum=Decimal(0)
            if policy in ("H0","HG"):
                minimum=max(Decimal(0),p["activation"]["gain_points"])
                equal(p["first_floor_hit"],p["activation"],"H0/HG利益後の初回即時床hit")
            candidate=max(minimum,p["peak_gain"]-p["atr"]["width"]) if p["atr"] is not None else minimum
            equal(floor,candidate,"旧固定2ATRと非緩和最終床")
            if p["first_floor_hit"] is not None:need(BASE.point_order(p["activation"])<=BASE.point_order(p["first_floor_hit"]),"利益起動後の共通床hit")

    namespace={**vars(BASE),"verify_source_events":source_validator,"verify_marks":marks_validator}
    checked=types.FunctionType(BASE.verify_book.__code__,namespace,"100共通金融とHG保存規範")(proxy,common)
    positions={p["id"]:p for p in book["positions"]}
    for o in book["orders"]:
        if "gross_guard_point" in o:
            point=o["gross_guard_point"];p=positions[o["position_id"]];state=p.get("gross_guard")
            need(state is not None and state["first_hit"] is not None,"HG注文の起動/床hit出典")
            need(o["kind"]=="exit" and o["protection_point"] is None and not o["native_close_signal_id"] and not o["native_close_notice_id"],"Source/HとHGの排他")
            equal(o["reason"],INDEPENDENT.HG_REASON,"HG専用理由")
            checked["timeline"].verify_position_point(o["position_id"],point)
            need(point["phase"]=="after_source" and point["gain_points"]<=0 and point["unit_net"]<=0,"HG Source後/床0/利益前")
            equal(o["request_quote"],point["quote"],"HG要求quote");equal(o["request_time"],point["quote"]["time"],"HG要求時計")
            equal(o["quantity"],point["quantity"]-point["reserved"],"HG未予約全残")
            need(BASE.point_order(state["first_hit"])<=BASE.point_order(point),"HG hit後要求")
            if state["profit_transition"] is not None:need(BASE.point_order(point)<BASE.point_order(state["profit_transition"]),"移行後HG再要求禁止")
        elif o["protection_point"] is not None:
            equal(o["reason"],"最低建値床と固定2ATR追尾" if policy=="P0" else "初回費用後残玉正益の全量確定","出口別の共通保護理由")
    for name,actual in (("source_exit_requests",classes["Source"]["要求回数"]),("protection_exit_requests",classes["H"]["要求回数"]),("protection_exit_fills",classes["H"]["約定回数"]),("gross_guard_exit_requests",classes["HG"]["要求回数"]),("gross_guard_exit_fills",classes["HG"]["約定回数"])):
        equal(book["metrics"].get(name,0),actual,"原counter排他:"+name);checked["counts"][name]=actual
    for name,field in (("gross_guard_activated_positions","activation"),("gross_guard_hit_positions","first_hit"),("gross_guard_transition_positions","profit_transition")):
        checked["counts"][name]=sum(p.get("gross_guard") is not None and p["gross_guard"][field] is not None for p in positions.values())
    checked["orders"],checked["positions"],checked["注文別"]={o["id"]:o for o in book["orders"]},positions,classes
    grid_space={**vars(GRID),"key_config":grid_key_config,"accepted_entries_at_grid":accepted_entries_at_grid}
    types.FunctionType(GRID.verify_grid.__code__,grid_space,"100現在E3S出生/枠規範")(book,checked["orders"],checked["timeline"],gates,full_clock)
    return checked


def comparisons() -> list:
    """
    機能: P0→H0/P0→HG/H0→HGと費用遅延の12比較を固定列挙する。
    引数: なし。
    返り値: list[tuple[str,str]]はbefore/afterの実運転Key。
    """
    result=[]
    for cost in (0,5):
        for delay in (0,1):
            base=f"E3S_B5Q_P0_C{cost}_D{delay}";result.extend(((base,"H0_"+base),(base,"HG_"+base),("H0_"+base,"HG_"+base)))
    return result


def entry_fingerprint(position: dict,orders: dict) -> tuple:
    """
    機能: 同Source出生の要求と実取得を価格・枚数・原行まで比較する。
    引数: position(dict)、orders(dict)は実玉とID索引。
    返り値: tupleは要求時計/Index/物理行、売買、取得時計/Index/物理行/価格/初期量。
    """
    order=orders[position["entry_order_id"]];request=order["request_quote"];q=position["entry_quote"]
    return (order["request_time"],request["index"],request["source_line"],position["side"],q["time"],q["index"],q["source_line"],position["entry_price"],position["initial_quantity"])


def compare_positions(before: dict,after: dict) -> dict:
    """
    機能: 固定参加差分解へ要求原行の厳密比較と双方の実参加額を追加する。
    引数: before/after(dict)は保存検算の返り値。
    返り値: dictは同実退出差と取得変更・片側参加額。未運転の戦略損益を作らない。
    """
    row=types.FunctionType(BASE.compare_positions.__code__,{**vars(BASE),"entry_fingerprint":entry_fingerprint})(before,after)
    aa={BASE.source_identity(p["source"]):p for p in before["positions"].values()}
    bb={BASE.source_identity(p["source"]):p for p in after["positions"].values()}
    amounts={name:Decimal(0) for name in ("同実入口A実参加額円","同実入口B実参加額円","取得変更A実参加額円","取得変更B実参加額円")}
    for source in aa.keys()&bb.keys():
        pa,pb=aa[source],bb[source]
        group="同実入口" if entry_fingerprint(pa,before["orders"])==entry_fingerprint(pb,after["orders"]) else "取得変更"
        amounts[group+"A実参加額円"]+=pa["realized_net"];amounts[group+"B実参加額円"]+=pb["realized_net"]
    for group in ("同実入口","取得変更"):equal(amounts[group+"B実参加額円"]-amounts[group+"A実参加額円"],row[group+"差円"],"双方実参加額の差:"+group)
    return {**row,**amounts,"限定":"同Source出生に対し要求時計/Index/物理行と取得時計/Index/物理行/価格/初期量が全一致する場合だけ退出差。双方額は各運転の既存実参加額。"}


def realized_row(book: dict) -> dict:
    """
    機能: 固定99の実現粗純・PF・uW実損失・保存極値を再用する。
    引数: book(dict)は100検算済み口座。
    返り値: dictは実在玉だけの集計。新fieldを先に専用検査してから使う。
    """
    return types.FunctionType(OLD.realized_row.__code__,{**vars(OLD),"key_config":key_config})(book)


def judgment_counts(value: dict) -> dict:
    """
    機能: 固定99の枠/技法三値/check/Source段階計数を全12出口へ再用する。
    引数: value(dict)は100保存。
    返り値: dictは判断分類。入口は全E3Sとして本名を保つ。
    """
    return types.FunctionType(OLD.judgment_counts.__code__,{**vars(OLD),"key_config":key_config})(value)


def daily_rows(rows: list) -> list:
    """
    機能: 開始日が同じDay/Nightの実現額と保存極値DDをまとめる。
    引数: rows(list[dict])は場別保存検算済み行。
    返り値: list[dict]は日/Key別。各場flatを前提に連結し全Raw再計算とは呼ばない。
    """
    groups=defaultdict(list)
    for row in rows:groups[(row["session"].split("_")[0],row["key"])].append(row)
    result=[]
    for (date,key),scenes in sorted(groups.items()):
        diagnostic=DIAG.new_row();totals=defaultdict(Decimal);counts=defaultdict(int)
        for scene in scenes:
            for name in DIAG.COUNTERS:diagnostic[name]+=scene["実現診断"][name]
            for name,amount in scene["totals"].items():totals[name]+=amount
            for name,amount in scene["counts"].items():counts[name]+=amount
        DIAG.finish_row(diagnostic,key_config(key)[3])
        diagnostic["保存極値を連結した最大DD円"]=DIAG.joined_dd([{ "session":r["session"],**r["実現診断"]} for r in sorted(scenes,key=lambda r:r["session"])])
        result.append({"日":date,"key":key,"場数":len(scenes),"totals":dict(totals),"counts":dict(counts),"実現診断":diagnostic})
    return result


def analyze_values(values,scope: str) -> dict:
    """
    機能: 12出口の保存金融と純式を検算し実現額/日別/参加差を集約する。
    引数: values(iterable[dict])、scope(str)は保存値と人工/接続/正式。
    返り値: dictは実現損益のみ。機会損失/MFE/退出後価格は算出しない。
    """
    need(scope in ("人工","接続","正式"),"100保存scope")
    groups={k:defaultdict(Decimal) for k in KEYS};diags={k:DIAG.new_row() for k in KEYS};per_scene={k:[] for k in KEYS}
    orders={k:{n:defaultdict(int) for n in ("Source","H","HG")} for k in KEYS}
    rows,sessions,pairs,gates_all,judgments=[],set(),defaultdict(list),[],{}
    for value in values:
        session=value["session"];need(session not in sessions,"100場重複");sessions.add(session);equal(value["trial"],100,"100識別")
        equal(set(value["books"]),set(KEYS),"100全12保存")
        clocks=[g["at"] for g in value["books"][KEYS[0]]["grid_traces"]];gates=SavedGates(value);checked={}
        for key in KEYS:
            book=value["books"][key];equal([g["at"] for g in book["grid_traces"]],clocks,"100同12時計")
            try:current=checked[key]=verify_saved_book(book,key,gates,scope!="人工")
            except (ValueError,AssertionError,KeyError) as error:raise ValueError(f"{session}/{key}: {error}") from error
            row=realized_row(book);equal(row["純額円"],current["totals"]["net_yen"],"実玉/会計純額");equal(row["玉数"],current["counts"]["positions"],"実玉分母")
            for name in DIAG.COUNTERS:diags[key][name]+=row[name]
            per_scene[key].append({"session":session,**row})
            rows.append({"session":session,"key":key,"totals":current["totals"],"counts":current["counts"],"grid_metrics":book["grid_metrics"],"実現診断":row,"注文別":current["注文別"]})
            for collection in (current["totals"],current["counts"]):
                for name,amount in collection.items():groups[key][name]+=amount
            for name,amount in book["grid_metrics"].items():groups[key]["grid_"+name]+=amount
            for name,collection in current["注文別"].items():
                for metric,amount in collection.items():orders[key][name][metric]+=amount
            groups[key]["active_sessions"]+=current["counts"]["positions"]>0;groups[key]["negative_sessions"]+=current["totals"]["net_yen"]<0
        gates_all.append({"session":session,**gates.finish(clocks)})
        for before,after in comparisons():pairs[after+"対"+before].append({"session":session,**compare_positions(checked[before],checked[after])})
        OLD.merge_judgments(judgments,judgment_counts(value))
    if scope!="人工":equal(len(sessions),54 if scope=="正式" else 2,"100保存場数")
    for key,row in diags.items():
        DIAG.finish_row(row,key_config(key)[3]);ordered=sorted(per_scene[key],key=lambda r:r["session"])
        row["保存極値を連結した最大DD円"]=DIAG.joined_dd(ordered);row["場内最大DD円"]=max((r["場内最大DD円"] for r in ordered),default=Decimal(0))
    return {"試行":100,"成功":True,"scope":scope,"場数":len(sessions),"Actor数":12,"会計数":len(rows),
            "Actor設定":{k:{"入口":"E3S","出口":exit_policy(k),"初期risk":"","共通基本保護":"P0","slip_pts":key_config(k)[5],"delay_seconds":key_config(k)[6]} for k in KEYS},
            "集計":{k:dict(v) for k,v in groups.items()},"実現診断":diags,"場別":rows,"日別":daily_rows(rows),
            "注文別":{k:{n:dict(v) for n,v in d.items()} for k,d in orders.items()},"出口間の同実入口と実参加差":dict(pairs),"判断分類":judgments,"純判定と共有枠":gates_all,
            "保存検算":"固定金融/Source/出生枠/半円/全実約定/残0にHG三点/注文point/counterの全tag検算を追加。内部Timelineの自己予約はSource後保護として対応し、原Source/H/HGを別分類する。",
            "独立監査への分担":"初回/極値/非緩和更新の全経路完全性と要求義務/最新Scalar出典は独立d6b2の別証拠へ同入力SHAで結ぶ。保存点だけを全経路再計算とは呼ばない。",
            "未実施":{"原板/CSV/Go再生":0,"機会損失/MFE回収/未参加や退出後価格":0,"資本金ROI":None}}


def render(result: dict) -> str:
    """
    機能: P0/H0/HGの実現額と分母を短いMarkdownへ出す。
    引数: result(dict)は検算済み結果。
    返り値: strは閲覧用。無取引/PF未定義を黒字安定としない。
    """
    lines=["# 100候補：利益化前後の保護・保存会計","",f"scope={result['scope']}、{result['場数']}場/{result['会計数']}会計。","","|Key|玉/枚|粗額円|fee円|slip円|純額円|PF|u正益後赤字/正益玉|HG起動/hit/移行|","|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key in KEYS:
        r,d=result["集計"][key],result["実現診断"][key]
        lines.append(f"|{key}|{r['positions']}/{r['entry_quantity']}|{r['gross_yen']}|{r['fee_yen']}|{r['slip_yen']}|{r['net_yen']}|{d['PF']}|{r['unit_positive_closed_negative']}/{r['unit_positive_positions']}|{r['gross_guard_activated_positions']}/{r['gross_guard_hit_positions']}/{r['gross_guard_transition_positions']}|")
    return "\n".join(lines+["","同実入口は同Source出生に対し要求時刻/取得時刻Index物理行/価格/初期量が全一致する場合だけ。取得変更と片側参加は別帰属。DDは保存極値の連結。仮想利益や回収率は算出しない。",""])


def write_viewer(out: Path,values: list) -> list:
    """
    機能: 12×場の実約定を100namespace/schema1/倍率100へ変換する。
    引数: out(Path)、values(list[dict])は新規先と検算済み保存。
    返り値: list[dict]は一覧資源。半円/部分返済を保持し0取引は空ファイル。
    """
    resources=[]
    for value in values:
        session=value["session"]
        for key in KEYS:
            identity="100_"+key+"_"+session;name=identity+".trades.jsonl"
            with (out/name).open("x",encoding="utf-8",newline="\n") as stream:
                for trade in BASE.viewer_trades(value["books"][key]):stream.write(json.dumps(trade,ensure_ascii=False,default=BASE.serial,allow_nan=False)+"\n")
            resources.append({"id":identity,"title":"利益化前後の保護 "+key+" "+session,"symbol":"NK225","product":"NK225mini","session":session,"method_id":key,"point_value":100,"pnl_format":"trades","pnl_basis":"net","pnl_path":name,"market_path":"NK225/"+session+"/book.jsonl.gz"})
    return resources


def require_market_fixed(stage: str) -> None:
    """
    機能: 条件/99完了/金融/独立stageとmetadata部品の未固定を入力前に拒否する。
    引数: stage(str)はfirst2/full54。
    返り値: None。試作は未設定なので市場CLIを必ず拒否する。
    """
    need(stage in ("first2","full54"),"100stage")
    need(all(re.fullmatch(r"[0-9a-f]{64}",v or "") for v in (CONDITION_SHA,PROOF99_SHA,COMPLETION_SHA[stage],AUDIT_SHA[stage],MARKET_SHA)),"100条件/基準/金融/独立/metadataのSHAが未固定のため市場保存は禁止")


def main() -> int:
    """
    機能: 後段固定されたNativeと独立証拠だけを保存集計するCLI口を用意する。
    引数: --run/--audit/--condition/--proof99/--index/--out(Path)、--limit(int,2/54)は明示入力。
    返り値: intは成功0。現在はplaceholderで最初のファイル読取前に拒否する。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("run","audit","condition","proof99","index","out"):parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--limit",type=int,choices=(2,54),default=54)
    args=parser.parse_args();stage="first2" if args.limit==2 else "full54";require_market_fixed(stage)
    need(not args.out.exists(),"新規保存先だけ")
    for path,expected in ((args.condition,CONDITION_SHA),(args.proof99,PROOF99_SHA),(args.run/"完了.json",COMPLETION_SHA[stage]),(args.audit,AUDIT_SHA[stage])):equal(digest(path),expected,"100固定入力SHA")
    market=fixed("100市場metadataの保存接続",MARKET_PATH,MARKET_SHA)
    equal(args.proof99.resolve(),market.PROOF99.resolve(),"固定99証拠先")
    tasks,before,groups=market.prepare(args.index.resolve(),args.run.resolve(),args.condition.resolve(),stage)
    audit=BASE.read_json(args.audit)
    need(audit["成功"] is True and audit["stage"]==stage and audit["場数"]==args.limit and audit["会計数"]==args.limit*12 and audit["不一致数"]==0 and audit["入力コード前後不変"] is True,"100独立金融成功scope")
    audits={r["session"]:r for r in audit["details"]};equal(len(audits),len(audit["details"]),"監査場重複なし");equal(set(audits),{t["session"] for t in tasks},"同監査場")
    for p in (Path(__file__),OLD_PATH,INDEPENDENT_PATH,MARKET_PATH,args.audit):before[str(p.resolve())]=digest(p)
    values,bodies,baselines=[],[],[]
    for task in tasks:
        session=task["session"]
        for name in ("tape","result","native99","native98","native97","native96"):
            p=Path(task[name]).resolve();equal(audits[session]["入力SHA256前後"].get(str(p)),task[name+"_sha256"],"独立と同入力:"+name)
        body=Path(task["result"]).read_bytes();equal(hashlib.sha256(body).hexdigest(),task["result_sha256"],"100元bodySHA")
        value=json.loads(body,parse_float=Decimal);equal(value["session"],session,"100場")
        old=json.loads(gzip.decompress(Path(task["native99"]).read_bytes()),parse_float=Decimal);INDEPENDENT.compare_h0_99(value,old)
        baselines.append({"session":session,"対照会計":4,"除外":[],"固定99保存SHA256":task["native99_sha256"]});values.append(value);bodies.append((session,body))
    result=analyze_values(values,"接続" if args.limit==2 else "正式")
    result.update({"H0旧99E3S全文対照":baselines,"条件SHA256":digest(args.condition),"完了SHA256":digest(args.run/"完了.json"),"独立Tape金融監査SHA256":digest(args.audit),"集計コードSHA256":digest(Path(__file__)),"入力依存SHA256前後":before,**groups})
    need(all(digest(Path(p))==h for p,h in before.items()),"100保存前後差")
    args.out.mkdir(parents=True);resources=write_viewer(args.out,values);equal(len(resources),args.limit*12,"100表示資源")
    for session,body in bodies:
        with (args.out/(session+".json.gz")).open("xb") as file:
            with gzip.GzipFile(filename="",mode="wb",fileobj=file,mtime=0) as stream:stream.write(body)
    BASE.write_json(args.out/"結果.json",result);BASE.write_json(args.out/"一覧.resources.json",{"schema_version":1,"path_base":"catalog","resources":resources})
    (args.out/"結果.md").write_text(render(result),encoding="utf-8",newline="\n");(args.out/"完了.json").write_bytes((args.run/"完了.json").read_bytes())
    need(all(digest(Path(p))==h for p,h in before.items()),"100成果生成後差")
    return 0


if __name__=="__main__":raise SystemExit(main())
