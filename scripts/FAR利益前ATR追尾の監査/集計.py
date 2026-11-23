"""98の24口座の保存会計・初期リスク分類・Viewer変換。全経路義務は別Tape監査へ結ぶ。"""

import argparse
from collections import defaultdict
import copy
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT/"scripts/FAR初回利益確定の監査/集計.py"
OLD_SHA = "09e93302080a740d3c2add85297f9530c32f6235dabe5f08e674551b556b3208"
RISK_PATH = Path(__file__).with_name("初期ATR追尾の金融照合.py")
RISK_SHA = "ab8d6fd7245f6fe1d9528a4f81b1eeb532820bd80ea514d36c624d2c41839161"
MARKET_PATH = Path(__file__).with_name("市場Tapeを照合する.py")
MARKET_SHA = "2c60e08261cc06df30a55f819ce096abb8e9dcb32fb0394e7ffacbb5c500c694"
CONDITION_SHA = "719cee62e6c1be8bfccb81b87ae5f82412776433c00faa9272f16cb3302947cb"


def digest(path: Path) -> str:
    """
    機能: 明示した保存又はコードの指紋を取得する。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed_module(name: str, path: Path, expected: str):
    """
    機能: 停止した会計又は独立器だけをSHA確認して再用する。
    引数: name/expected(str)、path(Path)は識別名・指紋・コード先。
    返り値: moduleは読取部品。市場/原板/Goは実行しない。
    """
    if digest(path) != expected:
        raise ValueError("固定保存部品SHA差:"+str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


OLD = fixed_module("固定97保存算術98", OLD_PATH, OLD_SHA)
RISK = fixed_module("固定98金融と純技法保存98", RISK_PATH, RISK_SHA)
BASE, DIAG = OLD.BASE, OLD.DIAG
need, equal, number, integer = OLD.need, OLD.equal, OLD.number, OLD.integer
KEYS = RISK.KEYS
RISK_FIELDS = {"policy","multiplier","width","atr_known","atr_value","atr_available","atr_nominal",
               "entry_quote","peak_gain","has_mark","peak_updated","floor_gain","floor_updated","first_hit","profit_transition"}


def risk_floor(peak, width) -> Decimal:
    """
    機能: Go float64の減算順で初期リスク床だけを再計算する。
    引数: peak/width(Decimal|int)は観測Peakと固定幅。
    返り値: DecimalはJSONの最短十進表現に対応する床。円会計はDecimalを維持する。
    """
    return Decimal(str(max(-float(width),float(peak)-float(width))))


def key_config(key: str) -> tuple:
    """
    機能: 24外Keyを入口・初期リスク・旧名・費用・遅延へ分ける。
    引数: key(str)は98Actor Key。
    返り値: tupleはgate,risk,old97,old95,old94,cost,delay。出口は全H0。
    """
    need(key in KEYS, "98の24Actor Key")
    risk = "R05" if key.startswith("R05_") else "R10" if key.startswith("R10_") else ""
    old97 = key.removeprefix(risk+"_") if risk else key
    gate, harvest, old95, old94, cost, delay = OLD.key_config(old97)
    equal(harvest, "H0", "98共通H0")
    return gate, risk, old97, old95, old94, cost, delay


def grid_key_config(key: str) -> tuple:
    """
    機能: 旧96の出生・枠算術へ外labelの対応だけを渡す。
    引数: key(str)は98Key。
    返り値: tupleはgate,old95,old94,cost,delay。
    """
    gate, _, _, old95, old94, cost, delay = key_config(key)
    return gate, old95, old94, cost, delay


def accepted_entries_at_grid(book: dict, at, q) -> set:
    """
    機能: 同秒受理・取消規範へB5Q名だけを対応させる。
    引数: book(dict)、at(number)、q(dict|None)は保存と枠原行。
    返り値: set[str]は実注文ID。実時刻・量は変更しない。
    """
    return OLD.OLD.OLD.accepted_entries_at_grid(dict(book, key=key_config(book["key"])[3]), at, q)


class SavedGates(OLD.SavedGates):
    """24口座の現在候補から固定AB全式を再計算する保存索引。"""

    def __init__(self, value: dict):
        """
        機能: 固定純式のKey集合だけ24へ対応させる。
        引数: value(dict)は新98保存。
        返り値: None。保存採否を期待値にしない。
        """
        adapter = types.SimpleNamespace(**{**vars(RISK.FIN), "KEYS":KEYS})
        namespace = {**vars(RISK.TAPE), "FIN":adapter}
        constructor = types.FunctionType(RISK.TAPE.RecomputedGates.__init__.__code__, namespace, "98全24現在候補")
        gate_class = type("RecomputedGates98保存", (RISK.TAPE.RecomputedGates,), {"__init__":constructor})
        self.audit = RISK.Audit()
        self.core = gate_class(value["chart_grids"], value, self.audit)
        self.by_at = {g["at"]:g for g in value["chart_grids"]}
        equal(len(self.by_at), len(value["chart_grids"]), "共有枠時計一意")
        ranks = {key:n for n,key in enumerate(KEYS)}
        order = [(r["candidate"]["at"], ranks[r["key"]], r["ordinal"]) for r in value["gate_assessments"]]
        equal(order, sorted(order), "24callbackの時計/口座/機会順")


def risk_point(value: dict, position: dict, timeline) -> None:
    """
    機能: 初期リスク保存点を実Fill由来MTMと非緩和床の式へ結ぶ。
    引数: value/position(dict)、timeline(Timeline)は点・実玉・会計履歴。
    返り値: None。保存点間の全経路完全性は独立Tape監査へ分担する。
    """
    equal(set(value), {"mark","peak_gain","floor_gain"}, "RiskPoint全tag")
    mark, width = value["mark"], number(position["initial_risk"]["width"], "risk幅")
    timeline.verify_position_point(position["id"], mark)
    peak = number(value["peak_gain"], "RiskPoint.peak")
    floor = number(value["floor_gain"], "RiskPoint.floor")
    need(peak >= number(mark["gain_points"], "risk時gain"), "risk観測Peakの下限")
    equal(floor, risk_floor(peak,width), "RiskPoint非緩和床算術")


def verify_risk(position: dict, risk: str, timeline) -> None:
    """
    機能: 取得時固定幅と利益移行をHの保存点から分離して検査する。
    引数: position(dict)、risk(str)、timeline(Timeline)は実玉・政策・会計履歴。
    返り値: None。取得時ATR源と初回性の全Scalar検証は別監査へ結ぶ。
    """
    if not risk:
        need("initial_risk" not in position, "空riskに新状態なし")
        return
    state = position["initial_risk"]
    equal(set(state), RISK_FIELDS, "初期risk全tag")
    equal(state["policy"], risk, "初期risk政策")
    multiplier = Decimal("0.5") if risk == "R05" else Decimal(1)
    equal(state["multiplier"], multiplier, "risk倍率")
    equal(state["entry_quote"], position["entry_quote"], "要求でなく取得原行固定")
    need(type(state["atr_known"]) is bool and type(state["has_mark"]) is bool, "risk既知/観測型")
    atr = number(state["atr_value"], "取得risk ATR")
    width = number(state["width"], "risk幅")
    need(atr >= 0 and 20 <= width <= 125, "risk ATR/幅範囲")
    equal(state["atr_known"], atr > 0, "取得ATR既知")
    expected_width = Decimal(str(max(20.0,min(125.0,float(multiplier)*float(atr))))) if atr > 0 else Decimal(125)
    equal(width, expected_width, "取得時幅/fallback125")
    for name in ("atr_available","atr_nominal"):
        need(number(state[name], name) >= 0, "risk ATR出典時計")
    if atr > 0:
        need(0 < state["atr_available"] <= state["entry_quote"]["time"] and 0 < state["atr_nominal"] <= state["atr_available"], "取得時公開ATR")
    floor, peak = number(state["floor_gain"], "risk最終床"), number(state["peak_gain"], "risk最終Peak")
    if state["has_mark"]:
        need(state["peak_updated"] is not None, "観測riskPeak出典")
        timeline.verify_position_point(position["id"], state["peak_updated"])
        equal(peak, state["peak_updated"]["gain_points"], "riskPeak値")
        equal(floor, risk_floor(peak,width), "risk最終非緩和床")
    else:
        equal(peak, 0, "未観測Peak規定値")
        equal(floor, -width, "未観測初期床")
        need(state["peak_updated"] is None and state["floor_updated"] is None and state["first_hit"] is None, "未観測出典なし")
    for name in ("floor_updated","first_hit"):
        point = state[name]
        if point is not None:
            risk_point(point, position, timeline)
            need(point["peak_gain"] <= peak and point["floor_gain"] <= floor, "risk保存床の単調性")
            if name == "first_hit": need(point["mark"]["gain_points"] <= point["floor_gain"], "risk初hit成立")
            else: equal(point["floor_gain"], floor, "最新risk床更新値")
    transition = state["profit_transition"]
    equal(transition is not None, position["protection_active"], "risk/H利益移行別記")
    if transition is not None:
        timeline.verify_position_point(position["id"], transition)
        equal(transition, position["activation"], "H初回起動と移行時計")
        need(transition["unit_net"] > 0, "risk移行strict費用後正益")
        if state["peak_updated"] is not None:
            need(BASE.point_order(state["peak_updated"]) <= BASE.point_order(transition), "利益後riskPeak更新禁止")


def order_classes(book: dict) -> dict:
    """
    機能: 原注文のSource/H/Riskを互いに排他的に分類する。
    引数: book(dict)は実口座。
    返り値: dictは各分類の要求回数・枚数と実返済回数・枚数。
    """
    rows = {name:{"要求回数":0,"要求枚数":0,"約定回数":0,"約定枚数":0} for name in ("Source","H","Risk")}
    orders = {o["id"]:o for o in book["orders"]}
    for order in orders.values():
        if order["kind"] != "exit": continue
        need(not (order["protection_point"] is not None and order.get("initial_risk_point") is not None), "HとRisk同一注文偽装")
        name = "Risk" if order.get("initial_risk_point") is not None else "H" if order["protection_point"] is not None else "Source"
        rows[name]["要求回数"] += 1
        rows[name]["要求枚数"] += order["quantity"]
    for fill in book["fills"]:
        if fill["action"] != "close": continue
        order = orders[fill["order_id"]]
        name = "Risk" if order.get("initial_risk_point") is not None else "H" if order["protection_point"] is not None else "Source"
        rows[name]["約定回数"] += 1
        rows[name]["約定枚数"] += fill["quantity"]
    return rows


def verify_saved_book(book: dict, key: str, gates: SavedGates, full_clock: bool) -> dict:
    """
    機能: 共通約定会計・H0・初期リスク・出生枠をすべて検算する。
    引数: book(dict)、key(str)、gates(SavedGates)、full_clock(bool)は保存・Key・純式器・正式時計範囲。
    返り値: dictは原注文分類を維持した会計。RiskをSource/H成績へ合算しない。
    """
    gate, risk, _, _, old94, cost, delay = key_config(key)
    equal(book["key"], key, "98外Key")
    expected = {"policy":"P0","entry_timing":"B5Q","us_open":book["config"]["us_open"],"slip_pts":cost,"delay_seconds":delay,"harvest_policy":"H0"}
    if gate != "G0": expected["gate_policy"] = gate
    if risk: expected["risk_policy"] = risk
    equal(book["config"], expected, "98全政策/費用/遅延")
    equal(set(book), {"session","key","config","orders","fills","positions","source_events","metrics","totals","account","finished","complete","failure","stream_scope","entry_opportunities","grid_traces","grid_metrics"}, "98金融全tag")
    proxy = {k:copy.deepcopy(v) for k,v in book.items() if k not in {"entry_opportunities","grid_traces","grid_metrics"}}
    proxy["key"], proxy["config"] = old94, {"policy":"P0","slip_pts":cost,"delay_seconds":delay}
    classes = order_classes(book)
    # 共通会計器の「Source後に自己予約する保護」区分にRiskも属する。
    # 原注文・原metricsは別検査し、この会計内部対応をSource/Hの実分類へ転用しない。
    for order in proxy["orders"]:
        if order.get("initial_risk_point") is not None:
            order["protection_point"] = copy.deepcopy(order["initial_risk_point"]["mark"])
    proxy["metrics"].pop("initial_risk_exit_requests", None)
    proxy["metrics"]["protection_exit_requests"] += classes["Risk"]["要求回数"]
    proxy["metrics"]["protection_exit_fills"] += classes["Risk"]["約定回数"]

    def source_validator(projected, orders, timeline):
        """
        機能: 新旧全実注文を元Source出生・比例返済へ結ぶ。
        引数: projected/orders(dict)、timeline(Timeline)は共通会計の保存と履歴。
        返り値: None。Risk自己予約の時点はHと同じSource後とする。
        """
        OLD.OLD.OLD.verify_source_b(book, orders, timeline)

    def marks_validator(position: dict, timeline, intrinsic: str):
        """
        機能: 旧MTM/H最低床と新Riskの保存算術を別に検査する。
        引数: position(dict)、timeline(Timeline)、intrinsic(str)は実玉・履歴・基本保護。
        返り値: None。全経路の初回・極値完全性は別監査範囲。
        """
        BASE.verify_marks(position, timeline, intrinsic)
        if position["protection_active"]:
            first = position["activation"]
            need(first is not None and first["unit_net"] > 0, "H0 strict現在残玉正益")
            need(position["floor_gain"] >= max(Decimal(0),first["gain_points"]), "H0最低床")
            equal(position["first_floor_hit"], first, "H0初正益/初hit同原行")
        verify_risk(position, risk, timeline)

    namespace = {**vars(BASE), "verify_source_events":source_validator,"verify_marks":marks_validator}
    checked = types.FunctionType(BASE.verify_book.__code__, namespace, "98共通金融とリスク保存規範")(proxy, old94)
    positions = {p["id"]:p for p in book["positions"]}
    for order in book["orders"]:
        point = order.get("initial_risk_point")
        if point is not None:
            need(bool(risk) and order["kind"] == "exit" and order["protection_point"] is None, "risk専用要求")
            equal(order["reason"], RISK.RISK_REASON, "risk専用理由")
            risk_point(point, positions[order["position_id"]], checked["timeline"])
            need(point["mark"]["unit_net"] <= 0 and point["mark"]["gain_points"] <= point["floor_gain"], "利益前risk要求成立")
        elif order["protection_point"] is not None:
            equal(order["reason"], RISK.FIN.HARVEST_REASON, "H0要求理由")
        if not risk: need("initial_risk_point" not in order, "空risk注文に新tagなし")
    for name, actual in (("source_exit_requests",classes["Source"]["要求回数"]),("protection_exit_requests",classes["H"]["要求回数"]),("protection_exit_fills",classes["H"]["約定回数"])):
        equal(book["metrics"][name],actual,"原Metrics."+name)
        checked["counts"][name] = actual
    equal(book["metrics"].get("initial_risk_exit_requests",0), classes["Risk"]["要求回数"], "原Risk要求counter")
    need(bool(risk) or "initial_risk_exit_requests" not in book["metrics"], "空riskにcounter tagなし")
    checked["counts"]["initial_risk_exit_requests"] = classes["Risk"]["要求回数"]
    checked["orders"], checked["positions"], checked["注文別"] = {o["id"]:o for o in book["orders"]}, positions, classes
    grid_namespace = {**vars(OLD.OLD), "key_config":grid_key_config,"accepted_entries_at_grid":accepted_entries_at_grid}
    types.FunctionType(OLD.OLD.verify_grid.__code__, grid_namespace, "98現在出生と枠保存規範")(book, checked["orders"], checked["timeline"], gates, full_clock)
    return checked


def analyze_values(values, scope: str) -> dict:
    """
    機能: 24独立口座の保存算術と純採否を検算し実在取引のみ集計する。
    引数: values(iterable[dict])、scope(str)は新保存と人工/接続/正式。
    返り値: dictは実現額・参加差・注文分類。未参加仮想利益を作らない。
    """
    need(scope in ("人工","接続","正式"), "98集計scope")
    groups = {k:defaultdict(Decimal) for k in KEYS}
    diagnostics = {k:DIAG.new_row() for k in KEYS}
    session_diags = {k:[] for k in KEYS}
    orders_all = {k:{n:defaultdict(int) for n in ("Source","H","Risk")} for k in KEYS}
    rows, sessions, comparisons, gates_all = [], set(), defaultdict(list), []
    for value in values:
        session = value["session"]
        need(session not in sessions, "場の重複")
        sessions.add(session)
        equal(set(value["books"]),set(KEYS),"98全24保存集合")
        clocks = [g["at"] for g in value["books"][KEYS[0]]["grid_traces"]]
        gates, checked = SavedGates(value), {}
        for key in KEYS:
            book = value["books"][key]
            equal([g["at"] for g in book["grid_traces"]],clocks,"全24同時計列")
            try:
                current = checked[key] = verify_saved_book(book,key,gates,scope!="人工")
            except (ValueError,AssertionError,KeyError) as error:
                raise ValueError(f"{session}/{key}: {error}") from error
            row = OLD.realized_row(dict(book,key=key_config(key)[2]))
            equal(row["純額円"],current["totals"]["net_yen"],"実玉/会計純額")
            equal(row["玉数"],current["counts"]["positions"],"実玉分母")
            for name in DIAG.COUNTERS: diagnostics[key][name] += row[name]
            session_diags[key].append({"session":session,**row})
            rows.append({"session":session,"key":key,"totals":current["totals"],"counts":current["counts"],"grid_metrics":book["grid_metrics"],"実現診断":row,"注文別":current["注文別"]})
            for collection in (current["totals"],current["counts"]):
                for name,amount in collection.items(): groups[key][name] += amount
            for name,amount in book["grid_metrics"].items(): groups[key]["grid_"+name] += amount
            for name,collection in current["注文別"].items():
                for metric,amount in collection.items(): orders_all[key][name][metric] += amount
            groups[key]["active_sessions"] += current["counts"]["positions"] > 0
            groups[key]["negative_sessions"] += current["totals"]["net_yen"] < 0
        gates_all.append({"session":session,**gates.finish(clocks)})
        for key in KEYS:
            if key_config(key)[1]:
                control = key_config(key)[2]
                comparisons[key+"対"+control].append({"session":session,**BASE.compare_positions(checked[control],checked[key])})
    if scope != "人工": equal(len(sessions),54 if scope=="正式" else 2,"保存場数")
    for key,row in diagnostics.items():
        DIAG.finish_row(row,key_config(key)[3])
        ordered = sorted(session_diags[key],key=lambda r:r["session"])
        row["保存極値を連結した最大DD円"] = DIAG.joined_dd(ordered)
        row["場内最大DD円"] = max((r["場内最大DD円"] for r in ordered),default=Decimal(0))
    return {"試行":98,"成功":True,"scope":scope,"場数":len(sessions),"Actor数":24,"会計数":len(rows),
            "Actor設定":{k:{"入口":key_config(k)[0],"出口":"H0","初期risk":key_config(k)[1],"共通基本保護":"P0","slip_pts":key_config(k)[5],"delay_seconds":key_config(k)[6]} for k in KEYS},
            "集計":{k:dict(r) for k,r in groups.items()},"実現診断":diagnostics,"場別":rows,
            "注文別":{k:{n:dict(v) for n,v in r.items()} for k,r in orders_all.items()},
            "初期Riskと空Riskの同実入口と実参加差":dict(comparisons),"純判定と共有枠":gates_all,
            "保存検算":"全注文/約定/配賦/半円/Source joins/MTM保存点/入口全枠/現在純採否。Risk自己予約はSource後として共通会計へ対応し、原Source/H/Risk分類とcounterは別検査。",
            "独立監査への分担":"取得時ATR源・初回/極値・非緩和・全Scalarの要求義務/出典は別の停止Tape金融監査に同じ入力SHAで結ぶ。保存点だけの検算を全経路再計算とは呼ばない。",
            "未実施":{"原板/CSV/Go再生":0,"未参加/決済後仮想利益":0,"資本金ROI":None}}


def render(result: dict) -> str:
    """
    機能: 24独立運転の実現額と注文分類だけを表にする。
    引数: result(dict)は検算済み集計。
    返り値: strはMarkdown。0取引やPF未定義を安定利益としない。
    """
    lines = ["# 98：利益前ATR追尾の保存会計","",f"{result['場数']}場/{result['会計数']}会計、scope={result['scope']}。全Scalar規範は別監査。","",
             "|Key|玉/枚|粗額円|fee円|slip円|純額円|PF|u正益後赤字/正益玉|Source/H/Risk要求|","|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key in KEYS:
        r,d,o = result["集計"][key],result["実現診断"][key],result["注文別"][key]
        lines.append(f"|{key}|{r['positions']}/{r['entry_quantity']}|{r['gross_yen']}|{r['fee_yen']}|{r['slip_yen']}|{r['net_yen']}|{d['PF']}|{r['unit_positive_closed_negative']}/{r['unit_positive_positions']}|{o['Source']['要求回数']}/{o['H']['要求回数']}/{o['Risk']['要求回数']}|")
    return "\n".join(lines+["","各費用/遅延/リスク幅は別動的運転。DDは保存極値と場内DDを連結した値。未参加や退出後の仮想利益は計算しない。",""])


def write_viewer(out: Path, values: list) -> list:
    """
    機能: 検算済み実約定を既存mini倍率100のViewer形式へ変換する。
    引数: out(Path)、values(list[dict])は新規出力先と新保存。
    返り値: list[dict]は資源。基礎会計のfee/滑りは区別し、Viewer fee_yenへ合算する。
    """
    resources = []
    for value in values:
        session = value["session"]
        for key in KEYS:
            identity = "98_"+key+"_"+session
            name = identity+".trades.jsonl"
            with (out/name).open("x",encoding="utf-8",newline="\n") as stream:
                for trade in BASE.viewer_trades(value["books"][key]):
                    stream.write(json.dumps(trade,ensure_ascii=False,default=BASE.serial,allow_nan=False)+"\n")
            resources.append({"id":identity,"title":"利益前ATR追尾 "+key+" "+session,"symbol":"NK225","product":"NK225mini","session":session,"method_id":key,"point_value":100,"pnl_format":"trades","pnl_basis":"net","pnl_path":name,"market_path":"NK225/"+session+"/book.jsonl.gz"})
    return resources


def main() -> int:
    """
    機能: 成功した98 Nativeと独立Tape監査を読み新規24資源/場へ集計する。
    引数: --run/--audit/--condition/--index/--out(Path)、--limit(int,2/54)は明示保存と範囲。
    返り値: intは成功0。既存出力/未完/指紋差は非0。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run","audit","condition","index","out"): parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--limit",type=int,choices=(2,54),default=54)
    args = parser.parse_args()
    need(not args.out.exists(),"新規成果物dirだけ")
    equal(digest(args.condition),CONDITION_SHA,"固定98条件SHA")
    market = fixed_module("固定98市場guard保存",MARKET_PATH,MARKET_SHA)
    stage = "first2" if args.limit==2 else "full54"
    tasks,before = market.prepare(args.index.resolve(),args.run.resolve(),args.condition.resolve(),stage)
    audit = BASE.read_json(args.audit)
    need(audit["成功"] is True and audit["stage"]==stage and audit["場数"]==args.limit and audit["会計数"]==args.limit*24 and audit["空Risk対97H0全文会計"]==args.limit*8 and audit["不一致数"]==0 and audit["入力コード前後不変"] is True,"独立98全金融/旧H0八対照scope")
    audit_rows = {r["session"]:r for r in audit["details"]}
    equal(len(audit_rows),len(audit["details"]),"独立監査の場重複なし")
    equal(set(audit_rows),{t["session"] for t in tasks},"独立監査の全場")
    for path in (Path(__file__),OLD_PATH,RISK_PATH,MARKET_PATH,args.audit): before[str(path.resolve())] = digest(path)
    values,bodies,baselines = [],[],[]
    for task in tasks:
        path,oldpath = Path(task["result"]),Path(task["native97"])
        for name in ("result","native97","tape","native96"):
            p = Path(task[name]).resolve()
            equal(audit_rows[task["session"]]["入力SHA256前後"].get(str(p)),task[name+"_sha256"],"独立監査と同じ入力:"+name)
        body = path.read_bytes()
        equal(hashlib.sha256(body).hexdigest(),task["result_sha256"],"98元JSON指紋")
        value = json.loads(body,parse_float=Decimal)
        old97 = json.loads(gzip.decompress(oldpath.read_bytes()),parse_float=Decimal)
        RISK.compare_no_risk97(value,old97)
        equal(value["session"],task["session"],"Native場")
        need(value["actual_run_complete"] is True and value["source_reexecuted"] is False and value["charts_recomputed"] is False,"98実運転範囲")
        baselines.append({"session":task["session"],"対照会計":8,"除外":[],"固定97保存SHA256":task["native97_sha256"]})
        values.append(value);bodies.append((task["session"],body))
    result = analyze_values(values,"接続" if args.limit==2 else "正式")
    result.update({"空Risk旧97H0全文対照":baselines,"独立Tape金融監査SHA256":digest(args.audit),"条件SHA256":digest(args.condition),"完了SHA256":digest(args.run/"完了.json"),"集計コードSHA256":digest(Path(__file__)),"入力依存SHA256前後":before})
    need(all(digest(Path(p))==h for p,h in before.items()),"保存集計前後指紋差")
    args.out.mkdir(parents=True)
    resources = write_viewer(args.out,values)
    equal(len(resources),args.limit*24,"98全Viewer資源")
    for session,body in bodies:
        with (args.out/(session+".json.gz")).open("xb") as file:
            with gzip.GzipFile(filename="",mode="wb",fileobj=file,mtime=0) as stream: stream.write(body)
    BASE.write_json(args.out/"結果.json",result)
    BASE.write_json(args.out/"一覧.resources.json",{"schema_version":1,"path_base":"catalog","resources":resources})
    (args.out/"結果.md").write_text(render(result),encoding="utf-8",newline="\n")
    (args.out/"完了.json").write_bytes((args.run/"完了.json").read_bytes())
    need(all(digest(Path(p))==h for p,h in before.items()),"成果生成後入力差")
    print(json.dumps({"成功":True,"場数":args.limit,"会計数":args.limit*24,"Viewer資源数":len(resources)},ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
