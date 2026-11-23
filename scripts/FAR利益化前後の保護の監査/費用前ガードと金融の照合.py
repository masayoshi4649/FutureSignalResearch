"""未採番100のE3S/P0・H0・HGを公開入力から独立再計算する人工用監査。"""

import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
import types


ROOT=Path(__file__).resolve().parents[2]
ENTRY_PATH=ROOT/"scripts/FAR背景と勢いと数量の監査/E3と金融の照合.py"
ENTRY_SHA="75dc5309c3e9c0b79d094df7941be4b2b5c206f0bb0d51740fd33a448cbcf834"
PURE_PATH=ROOT/"scripts/FAR背景と勢いと数量の監査/E3の純判定.py"
PURE_SHA="c84db9b29e2387429a8af9de81b2dfbbf6fd90d646dc1f66f3dc592f14ff4adf"
KEYS=tuple((exit_policy+"_" if exit_policy else "")+f"E3S_B5Q_P0_C{cost}_D{delay}"
           for exit_policy in ("","H0","HG") for cost in (0,5) for delay in (0,1))
HG_REASON="費用前順行を観測した名目建値ガード"
HG_COUNTERS={"gross_guard_exit_requests","gross_guard_exit_fills"}


def sha(path):
    """
    機能: 固定コード又は明示人工のSHAを読む。
    引数: path(Path)は対象。
    返り値: strは指紋。市場や原板を探索しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed(name,path,expected):
    """
    機能: 固定99独立金融と純E3式をSHAで再用する。
    引数: name/expected(str)、path(Path)は識別名・指紋・コード。
    返り値: moduleは独立Python部品。Go期待採否を呼ばない。
    """
    if sha(path)!=expected:raise ValueError("固定監査SHA差:"+str(path))
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value


ENTRY=fixed("固定99独立金融100",ENTRY_PATH,ENTRY_SHA)
PURE=fixed("固定99純E3S100",PURE_PATH,PURE_SHA)
FIN,TAPE,BASE,Audit=ENTRY.FIN,ENTRY.TAPE,ENTRY.BASE,ENTRY.Audit


class RecomputedGates(ENTRY.RecomputedGates):
    """固定99の全候補/全checkを本名E3Sの新12Keyへ結ぶ。"""

    def __init__(self,contexts,new100,audit):
        """
        機能: 固定constructorの許可Key集合だけを新12へ限定変更する。
        引数: contexts(list)、new100(dict)、audit(Audit)は当枠文脈と保存。
        返り値: None。純判断・候補量・Source出典の式は固定99そのまま。
        """
        namespace=dict(ENTRY.__dict__,KEYS=KEYS)
        constructor=types.FunctionType(ENTRY.RecomputedGates.__init__.__code__,namespace)
        constructor(self,contexts,new100,audit)
        audit.need(all(book["config"].get("gate_policy")=="E3S" for book in self.books.values()),"100入口は本名E3Sだけ")


class ProtectionPath(ENTRY.EntryPath):
    """固定P0/H0金融を継承し、HGの観測点・専用注文・計数だけを分ける。"""

    def __init__(self,actual,audit,gates):
        """
        機能: 新12設定と全tagを検査し、旧共通初期化へ最小型射影する。
        引数: actual(dict)、audit(Audit)、gatesは保存12口座・比較器・純判断供給器。
        返り値: None。新HG字段は後の全文比較から落とさない。
        """
        audit.need(actual["key"] in KEYS,"100全12key")
        cfg=actual["config"];harvest=cfg.get("harvest_policy","")
        audit.need(harvest in ("","H0","HG") and (("harvest_policy" in cfg)==bool(harvest)),"100出口/omitempty")
        expected={"policy","entry_timing","us_open","slip_pts","delay_seconds","gate_policy"}
        if harvest:expected.add("harvest_policy")
        audit.equal(set(cfg),expected,"100全config/risk空")
        audit.need(cfg["policy"]=="P0" and cfg["entry_timing"]=="B5Q" and cfg["gate_policy"]=="E3S","100共通P0/E3S/B5Q")
        audit.equal(set(actual),{"session","key","config","orders","fills","positions","source_events","metrics","totals","account",
                                 "finished","complete","failure","stream_scope","entry_opportunities","grid_traces","grid_metrics"},"100全金融top")
        audit.equal(actual["stream_scope"],"固定93と同じLast>0のSource受理行。Last0未供給数は共有qualityを参照。","100固定観測scope")
        base=f"B5Q_P0_C{cfg['slip_pts']:g}_D{cfg['delay_seconds']}"
        audit.equal(actual["key"],(harvest+"_" if harvest else "")+"E3S_"+base,"100本名key")
        metrics=actual["metrics"]
        audit.need(set(metrics)<=BASE.METRIC_FIELDS|HG_COUNTERS and BASE.METRIC_FIELDS<=set(metrics),"100全計数tag")
        for name in HG_COUNTERS&set(metrics):
            audit.need(harvest=="HG" and type(metrics[name]) is int and metrics[name]>0,"HG専用optional計数")
        common=copy.deepcopy(actual);common["key"]=base
        common["config"].pop("gate_policy");common["config"].pop("harvest_policy",None)
        for name in HG_COUNTERS:common["metrics"].pop(name,None)
        FIN.OLD.OLD.GridPath.__init__(self,common,audit)
        self.actual,self.extra_actual,self.key=actual,actual,actual["key"]
        self.policy,self.gates,self.harvest="E3S",gates,bool(harvest)
        self.exit_policy=harvest;self.hg_requests=self.hg_fills=0;self.hg_phase=None

    def request_gross(self,p,q,point):
        """
        機能: Source後の未予約残だけにHG専用point/reasonを付ける。
        引数: p/q/point(dict)は独立実玉・当原行・正常MTM。
        返り値: dictは新HG注文。共通注文の予約/ID/価格時計は変更しない。
        """
        free=p["quantity"]-p["reserved"]
        self.audit.need(self.exit_policy=="HG" and self.hg_phase=="after_source" and free>0
                        and point["gain_points"]<=0 and point["unit_net"]<=0,"HG要求の位相/未予約残/床0")
        order=super().request("exit",-p["side"],free,p["source"],q["time"],q,HG_REASON,p)
        # 共通constructorのpoint=nil分類からHG専用へ一度だけ移し、Sourceの要求数には混ぜない。
        self.metrics["source_exit_requests"]-=1;self.hg_requests+=1
        self.audit.need(self.metrics["source_exit_requests"]>=0,"HGでSource計数を負にしない")
        order["gross_guard_point"]=copy.deepcopy(point)
        return order

    def lock_atr(self,p,q,atr):
        """
        機能: 固定ATR処理後の正常MTMへHGだけを結ぶ。
        引数: p/q/atr(dict)は独立玉・原行・公開幅。
        返り値: None。MTMobserve後/旧H起動前の同一点であり、追加評価やfillを作らない。
        """
        super().lock_atr(p,q,atr)
        if self.exit_policy!="HG" or self.hg_phase is None:return
        point=BASE.mtm_point(p,q,self.hg_phase,self.cost)
        BASE.compare_tree(point,p["marks"].value["last"],self.audit,"HGは同正常MTM点")
        guard=p.get("gross_guard")
        if p["protection_active"]:
            self.audit.need(guard is None or guard["profit_transition"] is not None,"HGから旧Hへの不可逆移行")
            return
        if point["unit_net"]>0:
            if guard is not None:
                self.audit.need(guard["profit_transition"] is None,"HG利益移行は初回だけ")
                guard["profit_transition"]=copy.deepcopy(point)
            return
        if guard is None:
            if point["gain_points"]<=0:return
            guard=p["gross_guard"]={"activation":copy.deepcopy(point),"first_hit":None,"profit_transition":None}
        self.audit.need(guard["profit_transition"] is None,"利益移行後にHGへ戻らない")
        if point["gain_points"]<=0:
            if guard["first_hit"] is None:guard["first_hit"]=copy.deepcopy(point)
            if self.hg_phase=="after_source" and p["quantity"]>p["reserved"]:self.request_gross(p,q,point)

    def mark(self,q,phase,atr):
        """
        機能: 固定P0又はH0の全MTMを再用し、HGの同点hookだけを有効にする。
        引数: q/atr(dict)、phase(str)は当原行/公開幅/位相。
        返り値: None。profit_activeは旧strict u>0でのみ起動する。
        """
        self.hg_phase=phase if self.exit_policy=="HG" else None
        try:super().mark(q,phase,atr)
        finally:self.hg_phase=None
        for p in self.positions.values():
            guard=p.get("gross_guard")
            if guard is not None and guard["profit_transition"] is not None:
                self.audit.need(p["protection_active"] and p["activation"]==guard["profit_transition"],"HG利益移行と旧H起動点同値")

    def fill_pending(self,q,atr):
        """
        機能: 固定した後続適格行約定を再用し、HG約定だけ別counterへ分類する。
        引数: q/atr(dict)は当原行と公開幅。
        返り値: None。HGの予約/理由をH又はSourceへ付け替えない。
        """
        before=len(self.fills);super().fill_pending(q,atr)
        orders={order["id"]:order for order in self.orders}
        for fill in self.fills[before:]:
            order=orders[fill["order_id"]]
            if "gross_guard_point" in order:
                self.audit.need(fill["action"]=="close" and order["protection_point"] is None
                                and fill["reason"]==HG_REASON,"HG実約定の専用分類")
                self.hg_fills+=1

    def finish(self):
        """
        機能: HGのoptional計数を独立期待値へ加え、全字段を固定完結検査へ渡す。
        引数: なし。
        返り値: dictは一口座の検査範囲。0計数や未観測状態を架空出力しない。
        """
        for name,value in (("gross_guard_exit_requests",self.hg_requests),("gross_guard_exit_fills",self.hg_fills)):
            if value:self.metrics[name]=value
        result=super().finish()
        return dict(result,exit_policy=self.exit_policy or "P0",gross_guard_exit_requests=self.hg_requests,gross_guard_exit_fills=self.hg_fills)


def inspect_tape(tape,new100):
    """
    機能: 全Scalar/Source/Force/Gridを新12金融と固定E3S純式へ独立配送する。
    引数: tape/new100(dict)は公開Tapeと保存12口座。
    返り値: dictは独立結果。原板/Source/チャートを生成しない。
    """
    adapter=types.SimpleNamespace(**{**vars(FIN),"KEYS":KEYS,"HarvestPath":ProtectionPath})
    namespace={**vars(TAPE),"FIN":adapter,"RecomputedGates":RecomputedGates}
    driver=types.FunctionType(TAPE.inspect_tape.__code__,namespace)
    result=driver(tape,new100);result["会計数"]=len(result["details"])
    if result["会計数"]!=12:raise ValueError("100全12金融が不足")
    result["限定"]="公開Tapeの全金融と固定E3Sを独立計算。自然Source/指標形成/市場/原板は生成しない。"
    return result


def inspect_fixture(value):
    """
    機能: Go型API人工の全call順を新12と現在E3Sへ独立配送する。
    引数: value(dict)はsession/scope/steps/timers/grids/events/actors12と純文脈。
    返り値: dictは人工だけの全経路結果。Tape/自然Sourceを架空補完しない。
    """
    before=TAPE.canonical(value);audit=Audit()
    audit.need(type(value.get("scope")) is str and "人工" in value["scope"],"100は明示API人工のみ")
    books=value["actors"];audit.equal(set(books),set(KEYS),"100人工12口座")
    for key,book in books.items():
        audit.equal(book["key"],key,"100人工の金融key")
        BASE.compare_tree(book["session"],value["session"],audit,key+"/人工共通場")
    current={"books":books,"chart_grids":value["chart_grids"],"gate_assessments":value["gate_assessments"]}
    gates=RecomputedGates(value["chart_grids"],current,audit)
    contexts={row["at"]:row for row in value["chart_grids"]}
    audit.equal(len(contexts),len(value["chart_grids"]),"100人工全grid一意")
    models=[ProtectionPath(books[key],audit,gates) for key in KEYS];clocks=[];counts={}
    delivery=copy.deepcopy(value)
    for event in delivery["events"]:
        if event["kind"]=="force":event["kind"]="timer"
    for call in FIN.OLD.OLD.fixture_calls(delivery):
        kind=call["kind"];counts[kind]=counts.get(kind,0)+1
        if kind=="quote":
            q,atr=BASE.observation_quote(call["observation"],call["source_line"])
            for model in models:model.step(q,call["batches"],atr)
        elif kind=="timer":
            for model in models:model.timer(call["at"],call["batches"])
        elif kind=="grid":
            audit.need(call["at"] in contexts,"100人工の当枠文脈")
            gates.begin_grid(contexts[call["at"]],models[0].last)
            for model in models:model.grid(call["at"])
            clocks.append(call["at"])
        else:raise ValueError("100人工の未知call")
    details=[model.finish() for model in models];gate_counts=gates.finish(clocks)
    audit.equal(TAPE.canonical(value),before,"100人工の入力前後不変")
    return {"成功":True,"会計数":12,"非0会計数":sum(row["positions"]>0 for row in details),"照合項目数":audit.checks,"不一致数":0,
            "イベント":counts,"技法":gate_counts,"全経路金融MTM":True,"details":details,
            "限定":"手製Source/ATR/Chartの公開Go型人工だけ。自然Source/指標生成/原板/実市場ではない。"}


def compare_h0_99(new100,old99):
    """
    機能: H0四口座を旧99E3S/H0の同人工へ除外0全文比較する。
    引数: new100/old99(dict)は新保存と旧API基準。
    返り値: dictは四対照。P0/HGを旧H0と偽装しない。
    """
    audit=Audit();controls=[key for key in KEYS if key.startswith("H0_")]
    if "session" in old99:audit.equal(new100["session"],old99["session"],"100/99の場")
    for key in controls:BASE.compare_tree(new100["books"][key],old99["books"][key],audit,key+"/旧99H0全field")
    return {"成功":True,"対照会計":4,"除外":[],"照合項目数":audit.checks,"scope":old99.get("scope","同場保存の全文対照")}
