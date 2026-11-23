"""未採番99の12口座を独立再計算する。E3/E3SをA/ABの金融labelへ偽装しない。"""

from collections import Counter
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
import types


ROOT=Path(__file__).resolve().parents[2]
FIN_PATH=ROOT/"scripts/FAR初回利益確定の監査/初回利益確定の金融照合.py"
FIN_SHA="ab7e95e35514ae0aadf4a833f89a1422eaa53c82339d003bba13b9df4eaec5b0"
TAPE_PATH=ROOT/"scripts/FAR初回利益確定の監査/Tapeと金融の照合.py"
TAPE_SHA="31fdf1d566f3c117b2cb6c5ec64e3211e7c8ae33a9cab75d84c1e38af1f4dff7"
RISK_PATH=ROOT/"scripts/FAR利益前ATR追尾の監査/初期ATR追尾の金融照合.py"
RISK_SHA="ab8d6fd7245f6fe1d9528a4f81b1eeb532820bd80ea514d36c624d2c41839161"
PURE_PATH=Path(__file__).with_name("E3の純判定.py")
PURE_SHA="c84db9b29e2387429a8af9de81b2dfbbf6fd90d646dc1f66f3dc592f14ff4adf"
KEYS=tuple("H0_"+(gate+"_" if gate else "")+f"B5Q_P0_C{cost}_D{delay}" for gate in ("","E3","E3S") for cost in (0,5) for delay in (0,1))


def digest(path):
    """
    機能: 明示コード/人工の指紋を取得する。
    引数: path(Path)は読取先。
    返り値: strはSHA256。原板や市場を検索しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed(name,path,expected):
    """
    機能: 固定した独立金融/配送/純check部品をSHAで読み込む。
    引数: name/expected(str)、path(Path)は名前・指紋・保存先。
    返り値: moduleは保存再計算部品。Goは実行しない。
    """
    if digest(path)!=expected:raise ValueError("固定監査SHA差:"+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


FIN=fixed("固定97H金融99",FIN_PATH,FIN_SHA)
TAPE=fixed("固定97Tape配送99",TAPE_PATH,TAPE_SHA)
RISK=fixed("固定98nil配送表現99",RISK_PATH,RISK_SHA)
PURE=fixed("E3独立純判定99",PURE_PATH,PURE_SHA)
BASE,Audit,TECH=FIN.BASE,FIN.Audit,FIN.TECH


class EntryPath(FIN.HarvestPath):
    """旧共通Grid初期化とH0式を直接使い、新しい政策名だけを正面から受ける。"""

    def __init__(self,actual,audit,gates):
        """
        機能: G0/E3/E3Sの12設定を検査し、共通会計の初期化だけを旧APIへ渡す。
        引数: actual(dict)、audit(Audit)、gatesは保存金融・比較器・独立採否供給器。
        返り値: None。原orders/positions/新gate/入力を最終全field比較から落とさない。
        """
        audit.need(actual["key"] in KEYS,"99の12key")
        cfg=actual["config"];policy=cfg.get("gate_policy","")
        audit.need(policy in ("","E3","E3S") and (("gate_policy" in cfg)==bool(policy)),"99 Gate政策/omitempty")
        expected={"policy","entry_timing","us_open","slip_pts","delay_seconds","harvest_policy"}
        if policy:expected.add("gate_policy")
        audit.equal(set(cfg),expected,"99全config/risk空")
        audit.need(cfg["policy"]=="P0" and cfg["entry_timing"]=="B5Q" and cfg["harvest_policy"]=="H0","99固定H0/B5Q/P0")
        audit.equal(set(actual),{"session","key","config","orders","fills","positions","source_events","metrics","totals","account",
                                 "finished","complete","failure","stream_scope","entry_opportunities","grid_traces","grid_metrics"},"99金融全top")
        audit.equal(actual["stream_scope"],"固定93と同じLast>0のSource受理行。Last0未供給数は共有qualityを参照。","固定観測scope")
        basic=f"B5Q_P0_C{cfg['slip_pts']:g}_D{cfg['delay_seconds']}"
        audit.equal(actual["key"],"H0_"+(policy+"_" if policy else "")+basic,"99の本名key")
        common=copy.deepcopy(actual);common["key"]=basic
        common["config"].pop("gate_policy",None);common["config"].pop("harvest_policy")
        # 固定95の共通初期化を直接使う。GatePath/HarvestPathのA/AB限定constructorは偽装して通さない。
        FIN.OLD.OLD.GridPath.__init__(self,common,audit)
        self.actual,self.extra_actual,self.key=actual,actual,actual["key"]
        self.policy,self.gates,self.harvest=policy,gates,True

    def prepare(self,at,q,batches,timer):
        """
        機能: 既知nil列だけのGo表現対応を再用し、固定Source検査へ渡す。
        引数: at(float)、q(dict|None)、batches(list)、timer(bool)は当時公開配送。
        返り値: listはSource検査済み通知。元入力を変更しない。
        """
        return super().prepare(at,q,RISK.native_batches(batches),timer)


class RecomputedGates:
    """当枠文脈と独立金融候補からE3/E3Sを再計算する。保存Allowedは期待値にしない。"""

    def __init__(self,contexts,new99,audit):
        """
        機能: 共有公開入力を固定validatorへ通し、本名5tag記録を索引化する。
        引数: contexts(list)、new99(dict)、audit(Audit)はTapeの文脈・新保存・比較器。
        返り値: None。旧A/ABの判断recordを新政策へ読み替えない。
        """
        self.audit,self.books,self.current=audit,new99["books"],None
        fixed_context=TECH.GateIndex({"chart_grids":contexts,"gate_assessments":[]})
        self.grids=fixed_context.grids
        BASE.compare_tree(new99["chart_grids"],contexts,audit,"99共有全grid入力")
        self.records,self.used,self.claim_order={},set(),[]
        self.calls=Counter({key:0 for key in KEYS})
        for record in new99["gate_assessments"]:
            audit.equal(set(record),{"key","ordinal","source","candidate","assessment"},"99判定全5tag")
            key,ordinal=record["key"],record["ordinal"]
            audit.need(key in KEYS and type(ordinal) is int and ordinal>0,"99判定key/ordinal")
            audit.need(self.books[key]["config"].get("gate_policy") in ("E3","E3S"),"99純判定はE3/E3S本名だけ")
            identity=key,ordinal;audit.need(identity not in self.records,"99callback重複")
            self.records[identity]=record

    def begin_grid(self,context,q):
        """
        機能: 同じ枠だけを公開し、Current出典を直前Scalarへ結ぶ。
        引数: context(dict)、q(dict|None)は当枠公開値と直前NK原行。
        返り値: None。Chart数値の原板再生成ではない。
        """
        self.audit.need(context["snapshot_id"] in self.grids,"99当枠文脈")
        self.current=context;FIN.OLD.bind_grid_current(self,context["at"],q,self.audit)

    def claim(self,key,p):
        """
        機能: 旧金融前資格/min量の後に、本名E3/E3Sを独立計算する。
        引数: key(str)、p(dict)は独立口座と当時候補。
        返り値: dictは新Decision。原source/quote/数量/時計は変更しない。
        """
        self.audit.need(self.current is not None and self.current["at"]==p["evaluated_at"],"99現在枠だけ")
        candidate={"ordinal":p["ordinal"],"at":p["evaluated_at"],"side":p["side"],"source":copy.deepcopy(p["source"]),
                   "quote":copy.deepcopy(p["quote"]),"available":p["available"],"quantity":min(p["source"]["birth_quantity"],p["source_quantity"],p["available"])}
        policy=self.books[key]["config"]["gate_policy"]
        before=TAPE.canonical({"input":self.current,"candidate":candidate})
        result=PURE.assess(self.current,candidate,policy)
        self.audit.equal(TAPE.canonical({"input":self.current,"candidate":candidate}),before,"99純入力の前後不変")
        identity=key,p["ordinal"]
        self.audit.need(identity in self.records and identity not in self.used,"99独立callback一回/保存結合")
        saved=self.records[identity]
        for field,expected in (("source",candidate["source"]),("candidate",candidate),("assessment",result)):
            BASE.compare_tree(saved[field],expected,self.audit,key+"/"+field)
        self.used.add(identity);self.claim_order.append(identity);self.calls[key]+=1
        return result["decision"]

    def finish(self,clocks):
        """
        機能: 判定欠落/余剰/適用順と候補なしを含む全枠を閉じる。
        引数: clocks(list[number])はTapeで実配送した枠。
        返り値: dictは新判定と全枠の計数。
        """
        self.audit.equal(self.used,set(self.records),"99callback全集合")
        self.audit.equal(self.claim_order,list(self.records),"99callback実順")
        self.audit.equal([g["at"] for g in self.grids.values()],clocks,"99全共有枠")
        expected={(key,p["ordinal"]) for key,book in self.books.items() for p in book["entry_opportunities"] if p.get("gate") is not None}
        self.audit.equal(self.used,expected,"99金融機会と純callback")
        return {"共有枠":len(clocks),"新callback":len(self.used),"口座別":dict(self.calls)}


def inspect_tape(tape,new99):
    """
    機能: 固定97全配送を12金融へ結び、E3/E3Sの全checkを現在候補から検査する。
    引数: tape/new99(dict)は手製Tapeと12保存。市場許可は現段階でない。
    返り値: dictは全金融/純採否の結果。新市場CLIは設けない。
    """
    adapter=types.SimpleNamespace(**{**vars(FIN),"KEYS":KEYS,"HarvestPath":EntryPath})
    namespace={**vars(TAPE),"FIN":adapter,"RecomputedGates":RecomputedGates}
    run=types.FunctionType(TAPE.inspect_tape.__code__,namespace,"99全Tape金融")
    result=run(tape,new99)
    if len(result["details"])!=12:raise ValueError("99全12金融の結果数")
    result["会計数"]=len(result["details"])
    result["限定"]="固定公開Tapeの12金融と本名E3/E3Sの必要8/9checkを独立計算。Source/指標形成/原板/実市場は再生成しない。"
    return result


def compare_empty_gate98(new99,old98):
    """
    機能: G0四会計を旧98の空Gate/空risk/H0へ除外0全文比較する。
    引数: new99/old98(dict)は同場保存。人工と正式のbaseline scopeを保持する。
    返り値: dictは四対照。旧P0/A/ABへ名前を偽装しない。
    """
    audit=Audit();controls=[k for k in KEYS if k.startswith("H0_B5Q_")]
    if "session" in old98:audit.equal(new99["session"],old98["session"],"99/旧98の場")
    for key in controls:
        audit.equal(old98["books"][key]["session"]["id"],new99["session"],key+"/旧98場")
        BASE.compare_tree(new99["books"][key],old98["books"][key],audit,key+"/旧98全文除外0")
    return {"成功":True,"対照会計":4,"除外":[],"照合項目数":audit.checks,"scope":old98.get("scope","同場保存金融の全文対照")}
