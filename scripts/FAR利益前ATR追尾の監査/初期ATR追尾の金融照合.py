"""取得ATR固定の利益前床を独立計算し、固定97の金融/純技法へ結ぶ。市場CLIは設けない。"""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types


ROOT=Path(__file__).resolve().parents[2]
FIN_PATH=ROOT/"scripts/FAR初回利益確定の監査/初回利益確定の金融照合.py"
FIN_SHA="ab7e95e35514ae0aadf4a833f89a1422eaa53c82339d003bba13b9df4eaec5b0"
TAPE_PATH=ROOT/"scripts/FAR初回利益確定の監査/Tapeと金融の照合.py"
TAPE_SHA="31fdf1d566f3c117b2cb6c5ec64e3211e7c8ae33a9cab75d84c1e38af1f4dff7"
RISK_REASON="利益前の固定初期幅追尾"
KEYS=tuple((risk+"_" if risk else "")+"H0_"+(gate+"_" if gate else "")+f"B5Q_P0_C{cost}_D{delay}"
           for risk in ("","R05","R10") for gate in ("","AB") for cost in (0,5) for delay in (0,1))


def digest(path):
    """
    機能: 停止コード又は人工の内容指紋を計算する。
    引数: path(Path)は読取先。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed(name,path,expected):
    """
    機能: 停止済み金融/純技法接続のみをSHA確認して読み込む。
    引数: name/expected(str)、path(Path)は識別名・指紋・保存先。
    返り値: moduleは読取部品。原板やGoを実行しない。
    """
    if digest(path)!=expected:raise ValueError("固定97コードSHA差:"+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


FIN=fixed("固定97H金融98",FIN_PATH,FIN_SHA)
TAPE=fixed("固定97全Tape接続98",TAPE_PATH,TAPE_SHA)
BASE,Audit=FIN.BASE,FIN.Audit


def native_batches(batches):
    """
    機能: Go nil sliceの既知4配送列だけを空列へ明示対応する。
    引数: batches(list[dict])は保存のNativeBatch。値/時刻/未知fieldは保持する。
    返り値: list[dict]は旧Python配列API向けの独立複写。元JSONは不変。
    """
    if type(batches) is not list:raise ValueError("NativeBatch配列型")
    out=copy.deepcopy(batches)
    for batch in out:
        for field in ("signals","fills","cancellations","closes"):
            if batch["delta"][field] is None:batch["delta"][field]=[]
            elif type(batch["delta"][field]) is not list:raise ValueError("Native配送列型:"+field)
    return out


class RiskPath(FIN.HarvestPath):
    """Source/予約/約定/費用を固定97へ委ね、利益前riskの観測だけを追加する。"""

    def __init__(self,actual,audit,gates):
        """
        機能: 24政策と新設定/計数の集合を確認し、初期化だけ旧型へ対応させる。
        引数: actual(dict)、audit(Audit)、gatesは全公開金融と純採否の供給器。
        返り値: None。注文/玉/新risk fieldは最終全文比較から除去しない。
        """
        audit.need(actual["key"] in KEYS,"98の24Key")
        cfg=actual["config"];risk=cfg.get("risk_policy","")
        audit.need(risk in ("","R05","R10") and (("risk_policy" in cfg)==bool(risk)),"Risk設定/omitempty")
        audit.need(cfg.get("harvest_policy")=="H0","98はH0固定")
        if "initial_risk_exit_requests" in actual["metrics"]:
            n=actual["metrics"]["initial_risk_exit_requests"]
            audit.need(bool(risk) and type(n) is int and n>0,"専用counterのomitempty/型")
        prefix=(risk+"_") if risk else ""
        old=copy.deepcopy(actual)
        old["key"]=actual["key"].removeprefix(prefix) if prefix else actual["key"]
        old["config"].pop("risk_policy",None)
        old["metrics"].pop("initial_risk_exit_requests",None)
        # 旧初期化に必要な設定/計数だけを射影。全新fieldは自己actualへ戻して最後に照合する。
        super().__init__(old,audit,gates)
        audit.equal(actual["key"],prefix+old["key"],"risk最外Key")
        self.key,self.actual,self.extra_actual=actual["key"],actual,actual
        self.risk=risk

    def prepare(self,at,q,batches,timer):
        """
        機能: Goの既知nil sliceを空配送へ対応させ、固定97の全Source検査へ渡す。
        引数: at(float)、q(dict|None)、batches(list)、timer(bool)は同じ公開通知。
        返り値: listは旧監査が検査した手法/通知。未知fieldを捨てず元入力を変更しない。
        """
        return super().prepare(at,q,native_batches(batches),timer)

    def request(self,kind,side,quantity,source,at,q,reason,position=None,native_signal="",notice="",point=None,initial_risk=None):
        """
        機能: 共通予約算術へ専用riskの要求出典/計数を追加する。
        引数: 既存requestのstr/int/dict/float引数とinitial_risk(dict|None)は独立当時point。
        返り値: dictは生成した期待注文。理由文字だけでSourceをriskへ再分類しない。
        """
        if initial_risk is not None:
            self.audit.need(bool(self.risk) and kind=="exit" and position is not None and point is None
                            and reason==RISK_REASON,"risk要求の明示出典/既存H分離")
        order=super().request(kind,side,quantity,source,at,q,reason,position,native_signal,notice,point)
        if initial_risk is not None:
            order["initial_risk_point"]=copy.deepcopy(initial_risk)
            self.metrics["source_exit_requests"]-=1
            self.metrics["initial_risk_exit_requests"]=self.metrics.get("initial_risk_exit_requests",0)+1
        return order

    def fill_pending(self,q,atr):
        """
        機能: 固定97の適格fillを再用し、新実玉だけ取得原行のrisk幅を固定する。
        引数: q/atr(dict)は同じ全原行と公開済み幅。
        返り値: None。要求時ATR/後のATR/保存risk値を期待値へ読み戻さない。
        """
        before=set(self.positions)
        super().fill_pending(q,atr)
        if not self.risk:return
        for pid in self.positions.keys()-before:
            p=self.positions[pid]
            self.audit.need(all(BASE.finite(x) and x>=0 for x in atr.values()),"取得ATRの有限/非負")
            known=atr["value"]>0
            self.audit.need(not known or 0<atr["nominal"]<=atr["available"]<=q["time"],"取得時ATRの公開因果")
            multiplier=.5 if self.risk=="R05" else 1.0
            width=max(20.0,min(125.0,multiplier*atr["value"])) if known else 125.0
            p["initial_risk"]={"policy":self.risk,"multiplier":multiplier,"width":width,"atr_known":known,
                "atr_value":atr["value"],"atr_available":atr["available"],"atr_nominal":atr["nominal"],
                "entry_quote":copy.deepcopy(q),"peak_gain":0.0,"has_mark":False,"peak_updated":None,
                "floor_gain":-width,"floor_updated":None,"first_hit":None,"profit_transition":None}

    def observe_risk(self,p,point):
        """
        機能: 利益前だけの非緩和床と初hitを更新し、Source後の未予約残へ要求する。
        引数: p/point(dict)は独立実玉と現在MTM。
        返り値: None。利益移行後は旧risk注文を撤回せず新観測も行わない。
        """
        risk=p["initial_risk"]
        if p["protection_active"]:
            if risk["profit_transition"] is None:risk["profit_transition"]=copy.deepcopy(point)
            return
        self.audit.need(risk["profit_transition"] is None,"H移行後のrisk復活禁止")
        if not risk["has_mark"] or point["gain_points"]>risk["peak_gain"]:
            risk["peak_gain"]=point["gain_points"]
            risk["peak_updated"]=copy.deepcopy(point)
        risk["has_mark"]=True
        floor=max(-risk["width"],risk["peak_gain"]-risk["width"],risk["floor_gain"])
        trigger={"mark":copy.deepcopy(point),"peak_gain":risk["peak_gain"],"floor_gain":floor}
        if floor>risk["floor_gain"]:
            risk["floor_gain"],risk["floor_updated"]=floor,copy.deepcopy(trigger)
        if point["gain_points"]<=floor:
            if risk["first_hit"] is None:risk["first_hit"]=copy.deepcopy(trigger)
            free=p["quantity"]-p["reserved"]
            if point["phase"]=="after_source" and free>0:
                self.request("exit",-p["side"],free,p["source"],point["quote"]["time"],point["quote"],
                             RISK_REASON,p,initial_risk=trigger)

    def mark(self,q,phase,atr):
        """
        機能: 固定97のH順序へ利益前risk観測を挿入し、全正常点を評価する。
        引数: q/atr(dict)、phase(str)は当原行とpre_fill/after_source。
        返り値: None。空riskは固定97 markを直接呼び、全旧式を保つ。
        """
        if not self.risk:return super().mark(q,phase,atr)
        for p in self.positions.values():
            if p["quantity"]==0:continue
            point=BASE.mtm_point(p,q,phase,self.cost)
            p["marks"].observe(point)
            gain=point["gain_points"]
            if not p["has_mark"] or gain>p["peak_gain"]:p["peak_gain"]=gain
            p["has_mark"]=True
            self.lock_atr(p,q,atr)
            if not p["protection_active"] and point["unit_net"]>0:
                p["protection_active"],p["activation"]=True,point
            self.observe_risk(p,point)
            if not p["protection_active"]:continue
            first=p["activation"]
            self.audit.need(first is not None and all(BASE.finite(first[n]) for n in ("gain_points","unit_net"))
                            and first["unit_net"]>0,"H0初回strict u正益の根拠")
            floor=max(0.0,first["gain_points"])
            if p["atr"] is not None:floor=max(floor,p["peak_gain"]-p["atr"]["width"])
            if p["floor_gain"] is not None:floor=max(floor,p["floor_gain"])
            if p["floor_gain"] is None or floor>p["floor_gain"]:p["floor_gain"],p["floor_updated"]=floor,point
            if gain<=floor:
                if p["first_floor_hit"] is None:p["first_floor_hit"]=point
                free=p["quantity"]-p["reserved"]
                if phase=="after_source" and free>0:
                    self.request("exit",-p["side"],free,p["source"],q["time"],q,FIN.HARVEST_REASON,p,point=point)
        self.account.observe(q,phase,self.cash,self.positions,self.side_cost)
        whole=sum(p["realized_net"]+p["quantity"]*(p["side"]*((q["bid"] if p["side"]==1 else q["ask"])-p["entry_price"])*100-self.cost)
                  for p in self.positions.values())
        self.audit.need(abs(whole-self.account.value["last"]["equity"])<=1e-7,"risk全HoldWと現金の独立一致")


def inspect_fixture(value):
    """
    機能: Go型手製Source/ATR/常時AB人工24口座を全calls順に独立照合する。
    引数: value(dict)はsteps/timers/grids/events/actorsを持つ人工。
    返り値: dictは全金融結果。自然指標/Source生成や市場有効性を主張しない。
    """
    audit=Audit();before=TAPE.canonical(value)
    audit.need(type(value.get("scope")) is str and "人工" in value["scope"],"手製人工scope")
    audit.equal(set(value["actors"]),set(KEYS),"人工24口座集合")
    gates=FIN.ArtificialAllowGates(value["actors"],audit)
    models=[]
    for key in KEYS:
        book=value["actors"][key]
        audit.equal(book["key"],key,"外map/Actor Key")
        BASE.compare_tree(book["session"],value["session"],audit,key+"/共通場")
        models.append(RiskPath(book,audit,gates))
    # Go人工のforceという配送名を、旧監査APIのtimerへだけ明示対応する。
    calls_value=dict(value,events=[dict(e,kind="timer") if e["kind"]=="force" else e for e in value["events"]])
    for call in FIN.OLD.OLD.fixture_calls(calls_value):
        if call["kind"]=="quote":
            q,atr=BASE.observation_quote(call["observation"],call["source_line"])
            batches=native_batches(call["batches"])
            for model in models:model.step(q,batches,atr)
        elif call["kind"]=="timer":
            batches=native_batches(call["batches"])
            for model in models:model.timer(call["at"],batches)
        elif call["kind"]=="grid":
            for model in models:model.grid(call["at"])
        else:raise ValueError("未定義calls")
    details=[m.finish() for m in models];gate_counts=gates.finish()
    audit.equal(TAPE.canonical(value),before,"Go人工の前後不変")
    return {"成功":True,"会計数":len(details),"非0会計数":sum(d["positions"]>0 for d in details),
            "照合項目数":audit.checks,"不一致数":0,"人工gate":gate_counts,"details":details,
            "scope":"手製API全金融/Source/費用/phase/初期幅/観測床/H移行。純技法は定数allow、自然Source/ATR/原板生成は未検査。"}


def inspect_tape(tape,new98):
    """
    機能: 固定97のTape/純技法配送を再用し、24金融をRiskPathへ渡す。
    引数: tape/new98(dict)は完成Tapeと新保存。市場許可は別の呼出側が限定する。
    返り値: dictは全Scalar/Source/Force/Grid・24金融・全現在採否の結果。
    """
    adapter=types.SimpleNamespace(**{**vars(FIN),"KEYS":KEYS,"HarvestPath":RiskPath})
    gate_namespace={**vars(TAPE),"FIN":adapter}
    gate_init=types.FunctionType(TAPE.RecomputedGates.__init__.__code__,gate_namespace,"98全24現在候補")
    gate_class=type("RecomputedGates98",(TAPE.RecomputedGates,),{"__init__":gate_init})
    namespace={**vars(TAPE),"FIN":adapter,"RecomputedGates":gate_class}
    run=types.FunctionType(TAPE.inspect_tape.__code__,namespace,"98全Tape金融")
    result=run(tape,new98)
    if len(result["details"])!=len(KEYS):raise ValueError("98全24結果の件数")
    # 固定97関数の返却metadataだけは16 literalであるため、実検査detailsの件数へ明示対応する。
    result["会計数"]=len(result["details"])
    result["限定"]="固定Tapeの全24金融を独立Pythonへ配送。risk/H/Sourceと現在純判定を分離。Source/チャートの原板再生成は行わない。"
    return result


def compare_no_risk97(new98,old97):
    """
    機能: risk空8口座だけを正式97H0へ除外0で全文比較する。
    引数: new98/old97(dict)は同場の実保存。疑似baselineは生成しない。
    返り値: dictは独立の8口座対照。人工scopeで未提供の97正本へ成功を補完しない。
    """
    audit=Audit()
    if "session" in old97:audit.equal(new98["session"],old97["session"],"空riskと旧97の場")
    controls=[k for k in KEYS if not k.startswith(("R05_","R10_"))]
    for key in controls:
        audit.equal(old97["books"][key]["session"]["id"],new98["session"],key+"/旧金融の場")
        BASE.compare_tree(new98["books"][key],old97["books"][key],audit,key+"/97全文除外0")
    return {"成功":True,"対照会計":len(controls),"除外":[],"照合項目数":audit.checks,
            "scope":old97.get("scope","同場保存金融の全文対照。元金融生成は別証拠。")}


def main():
    """
    機能: 停止14人工だけを全金融独立照合し、新規work証拠を出す。
    引数: --fixtures/--out(Path)は手製人工根と出力。市場/原板CLIは設けない。
    返り値: None。差/未完/既存出力は非0。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();paths=sorted(args.fixtures.glob("*.json"))
    expected={f"方向{s}_{n}.json" for s in (-1,1) for n in ("risk要求後正益","Source全予約","Source部分","利益移行","幅と次板悪化","未知後既知","非緩和")}
    if args.out.exists() or {p.name for p in paths}!=expected:raise ValueError("新規出力/停止手製14人工だけ")
    before={str(p.resolve()):digest(p) for p in paths+[Path(__file__),FIN_PATH,TAPE_PATH]}
    rows=[{"fixture":p.name,**inspect_fixture(BASE.load(p))} for p in paths]
    if any(digest(Path(p))!=h for p,h in before.items()):raise ValueError("人工/コード前後差")
    proof={"成功":True,"人工場面":len(rows),"会計数":sum(r["会計数"] for r in rows),
           "非0会計数":sum(r["非0会計数"] for r in rows),"照合項目数":sum(r["照合項目数"] for r in rows),
           "不一致数":0,"details":rows,"入力コードSHA256前後":before,"前後不変":True,"市場/原板/Go再生":0}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({n:proof[n] for n in ("成功","会計数","非0会計数","照合項目数")},ensure_ascii=False))


if __name__=="__main__":main()
