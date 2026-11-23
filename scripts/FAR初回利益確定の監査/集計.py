"""97の保存会計と閲覧形式。H0の全経路規範は独立Tape監査へ別に結ぶ。"""

import argparse
from collections import defaultdict
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


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT/"scripts/FAR5分枠の技法判定の監査/集計.py"
OLD_SHA = "32f7931f75f4b6241ced26e1f4b4014c332711c0948de104093762d01c73d750"
COUPLED_PATH = ROOT/"scripts/FAR初回利益確定の監査/Tapeと金融の照合.py"
COUPLED_SHA = "31fdf1d566f3c117b2cb6c5ec64e3211e7c8ae33a9cab75d84c1e38af1f4dff7"
PROOF96 = ROOT/"study/00096_5分枠の順行反転と現在数量/完了記録.json"
PROOF96_SHA = "33deeae84c68de0ecce21023e95732db22a658c9a832cb456d446e221276d483"
CONDITION_SHA = "f7421f26a306eb0a49387b9dfa2104621350fac5c6ceba035a84bb3661d42c05"


def digest(path: Path) -> str:
    """
    機能: 保存又は依存コードの指紋を取得する。
    引数: path(Path)は明示されたファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed_module(name: str, path: Path, expected: str):
    """
    機能: 停止した会計/純技法部品だけを読み込む。
    引数: name/expected(str)、path(Path)はmodule名・指紋・コード先。
    返り値: moduleは固定部品。市場/原板/Goは実行しない。
    """
    if digest(path) != expected:
        raise ValueError("固定保存部品SHA差:"+str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


OLD = fixed_module("固定96保存算術97", OLD_PATH, OLD_SHA)
COUPLED = fixed_module("固定97純候補と金融97保存", COUPLED_PATH, COUPLED_SHA)
BASE, DIAG = OLD.BASE, OLD.DIAG
need, equal, number, integer = OLD.need, OLD.equal, OLD.number, OLD.integer
KEYS = COUPLED.FIN.KEYS


def key_config(key: str) -> tuple:
    """
    機能: 16外Keyを入口/出口/旧共通会計名/費用/遅延に分ける。
    引数: key(str)は97Actor Key。
    返り値: tupleはgate,harvest,old95,old94,cost,delay。H0は独立の出口名を保つ。
    """
    need(key in KEYS, "97の16Actor Key")
    harvest = "H0" if key.startswith("H0_") else "P0"
    base = key.removeprefix("H0_")
    gate = "AB" if base.startswith("AB_") else "G0"
    old95 = base.removeprefix("AB_")
    old94 = old95.removeprefix("B5Q_")
    _, cost, delay = old94.split("_")
    return gate, harvest, old95, old94, int(cost[1:]), int(delay[1:])


def grid_key_config(key: str) -> tuple:
    """
    機能: 固定96の出生/枠算術にだけ外labelの対応を渡す。
    引数: key(str)は97Key。
    返り値: tupleは旧APIの5欄。H0の保護検査をP0へ代用する用途ではない。
    """
    gate, _, old95, old94, cost, delay = key_config(key)
    return gate, old95, old94, cost, delay


def accepted_entries_at_grid(book: dict, at, q) -> set:
    """
    機能: 旧95の同秒受理/取消規範へB5Q名だけを対応させる。
    引数: book(dict)、at(number)、q(dict|None)は元97保存と当枠原行。
    返り値: set[str]は実注文ID。H0の注文/時刻/量/traceを落とさない。
    """
    proxy = dict(book, key=key_config(book["key"])[2])
    return OLD.OLD.accepted_entries_at_grid(proxy, at, q)


# ----------------------------------------
class SavedGates:
    """保存枠の各現在候補から純式を再計算し、検査の巡回順を実適用順と混同しない。"""

    def __init__(self, value: dict):
        """
        機能: 停止済み共有文脈/候補の検査器を再用する。
        引数: value(dict)は新97保存。
        返り値: None。保存採否を期待値にしない。
        """
        self.audit = COUPLED.Audit()
        self.core = COUPLED.RecomputedGates(value["chart_grids"], value, self.audit)
        self.by_at = {g["at"]:g for g in value["chart_grids"]}
        need(len(self.by_at) == len(value["chart_grids"]), "共有枠の時計一意")
        ranks = {key:n for n,key in enumerate(KEYS)}
        order = [(r["candidate"]["at"], ranks[r["key"]], r["ordinal"]) for r in value["gate_assessments"]]
        equal(order, sorted(order), "保存callbackの時計/口座/機会順")

    def claim(self, key: str, p: dict) -> dict:
        """
        機能: 当機会の評価時計から公開文脈を選び純式へ結ぶ。
        引数: key(str)、p(dict)は保存Source/Timelineで検算した現在候補。
        返り値: dictは純再計算Decision。
        """
        need(p["evaluated_at"] in self.by_at, "機会の共有枠欠落")
        self.core.current = self.by_at[p["evaluated_at"]]
        return self.core.claim(key, p)

    def finish(self, clocks: list) -> dict:
        """
        機能: 全記録と適格callbackの集合・共有列を比較する。
        引数: clocks(list)は保存金融の全grid時計。
        返り値: dictは保存検算の件数。全Scalarからの出典は独立Tape監査へ分担する。
        """
        equal(self.core.used, set(self.core.records), "全適格/保存callback集合")
        equal([g["at"] for g in self.core.grids.values()], clocks, "全共有grid列")
        return {"共有枠":len(clocks), "適格出生判定":len(self.core.used), "口座別":dict(self.core.calls)}


def verify_saved_book(book: dict, key: str, gates: SavedGates, full_clock: bool) -> dict:
    """
    機能: 共通会計を固定94へ委ね、H0固有の保存床/理由と入口全量を明示検査する。
    引数: book(dict)、key(str)、gates(SavedGates)、full_clock(bool)は新正本と検査範囲。
    返り値: dictは会計/Timeline。Hの全原行要求義務を保存点だけから証明しない。
    """
    gate, harvest, _, old94, cost, delay = key_config(key)
    equal(book["key"], key, "97外Key")
    expected_config = {"policy":"P0", "entry_timing":"B5Q", "us_open":book["config"]["us_open"],
                       "slip_pts":cost, "delay_seconds":delay}
    if gate != "G0": expected_config["gate_policy"] = gate
    if harvest == "H0": expected_config["harvest_policy"] = harvest
    equal(book["config"], expected_config, "97全設定を出口別に検査")
    equal(set(book), {"session","key","config","orders","fills","positions","source_events","metrics","totals","account",
                     "finished","complete","failure","stream_scope","entry_opportunities","grid_traces","grid_metrics"}, "97金融全tag")
    proxy = {k:copy.deepcopy(v) for k,v in book.items() if k not in {"entry_opportunities","grid_traces","grid_metrics"}}
    # 会計APIのP0は共通のintrinsic policy。外H0は以下の専用検査と結果へ維持する。
    proxy["key"] = old94
    proxy["config"] = {"policy":"P0","slip_pts":cost,"delay_seconds":delay}

    def source_validator(projected, orders, timeline):
        """
        機能: Source出生を改時刻せず、B5Q実受付/返済の保存規範へ結ぶ。
        引数: projected/ orders(dict)、timeline(Timeline)は共通会計API。
        返り値: None。元97の全Source/機会を参照する。
        """
        OLD.OLD.verify_source_b(book, orders, timeline)

    def marks_validator(position: dict, timeline, intrinsic: str) -> None:
        """
        機能: 既存MTM算術にH0固有最低床/初hitを加え、外H0をP0で代用しない。
        引数: position(dict)、timeline(Timeline)、intrinsic(str)は実玉・共通会計・基本保護名。
        返り値: None。初回/極値の全経路完全性は独立Tape監査に分担する。
        """
        BASE.verify_marks(position, timeline, intrinsic)
        if harvest == "H0" and position["protection_active"]:
            first = position["activation"]
            need(first is not None and first["unit_net"] > 0, "H0 strict現在残玉正益")
            need(number(position["floor_gain"], "H0床") >= max(Decimal(0), number(first["gain_points"], "H0初gain")), "H0最低床")
            equal(position["first_floor_hit"], first, "H0初回正益と同原行の初hit")

    namespace = dict(vars(BASE))
    namespace["verify_source_events"], namespace["verify_marks"] = source_validator, marks_validator
    verifier = types.FunctionType(BASE.verify_book.__code__, namespace, "97共通会計とH0保存規範")
    checked = verifier(proxy, old94)
    for order in book["orders"]:
        if order["protection_point"] is not None:
            expected_reason = COUPLED.FIN.HARVEST_REASON if harvest == "H0" else "最低建値床と固定2ATR追尾"
            equal(order["reason"], expected_reason, "出口別の保護理由")
    grid_namespace = dict(vars(OLD))
    grid_namespace["key_config"] = grid_key_config
    grid_namespace["accepted_entries_at_grid"] = accepted_entries_at_grid
    grid_verifier = types.FunctionType(OLD.verify_grid.__code__, grid_namespace, "97現在出生/枠の保存規範")
    grid_verifier(book, checked["orders"], checked["timeline"], gates, full_clock)
    return checked


def realized_row(book: dict) -> dict:
    """
    機能: 実在Positionの実現額/正負/PF/uW赤字と保存DDを集計する。
    引数: book(dict)は検算済み97口座。
    返り値: dictは実現取引の診断。未参加/決済後の仮想利益は作らない。
    """
    row = DIAG.new_row()
    for position in book["positions"]:
        DIAG.OLD.add_position(row, position)
    DIAG.finish_row(row, key_config(book["key"])[2])
    account = book["account"]
    row.update({"場内最大DD円":account["max_drawdown"],
                "場内MTM最大円":account["max"]["equity"] if account["max"] else Decimal(0),
                "場内MTM最小円":account["min"]["equity"] if account["min"] else Decimal(0)})
    return row


def analyze_values(values, scope: str) -> dict:
    """
    機能: 全16の保存算術/純採否/Source joinsを検算し実現額をまとめる。
    引数: values(iterable[dict])、scope(str)は新保存と人工/接続/正式。
    返り値: dictは成績と同実入口/実参加差。全Scalar監査の代用ではない。
    """
    need(scope in ("人工","接続","正式"), "97保存集計scope")
    groups = {key:defaultdict(Decimal) for key in KEYS}
    diagnostics = {key:DIAG.new_row() for key in KEYS}
    session_diags = {key:[] for key in KEYS}
    rows, sessions, comparisons, gates_all = [], set(), defaultdict(list), []
    for value in values:
        session = value["session"]
        need(session not in sessions, "97場重複")
        sessions.add(session)
        equal(set(value["books"]), set(KEYS), "全16保存集合")
        clocks = [g["at"] for g in value["books"][KEYS[0]]["grid_traces"]]
        for key in KEYS:
            equal([g["at"] for g in value["books"][key]["grid_traces"]], clocks, "同場全16の時計列")
        gates = SavedGates(value)
        checked = {}
        for key in KEYS:
            book = value["books"][key]
            try:
                current = checked[key] = verify_saved_book(book, key, gates, scope != "人工")
            except (ValueError, AssertionError, KeyError) as error:
                raise ValueError(f"{session}/{key}: {error}") from error
            row = realized_row(book)
            equal(row["純額円"], current["totals"]["net_yen"], "実玉と会計純額")
            equal(row["玉数"], current["counts"]["positions"], "実玉分母")
            for name in DIAG.COUNTERS:
                diagnostics[key][name] += row[name]
            session_diags[key].append({"session":session, **row})
            rows.append({"session":session,"key":key,"totals":current["totals"],"counts":current["counts"],
                         "grid_metrics":book["grid_metrics"],"実現診断":row})
            for collection in (current["totals"], current["counts"]):
                for name,amount in collection.items(): groups[key][name] += amount
            for name,amount in book["grid_metrics"].items(): groups[key]["grid_"+name] += amount
            groups[key]["active_sessions"] += current["counts"]["positions"] > 0
            groups[key]["negative_sessions"] += current["totals"]["net_yen"] < 0
        gates_all.append({"session":session, **gates.finish(clocks)})
        for gate in ("", "AB_"):
            for cost in (0,5):
                for delay in (0,1):
                    old = gate+f"B5Q_P0_C{cost}_D{delay}"
                    new = "H0_"+old
                    comparisons[new+"対"+old].append({"session":session, **BASE.compare_positions(checked[old],checked[new])})
    if scope != "人工": equal(len(sessions), 54 if scope == "正式" else 2, "保存場数")
    for key,row in diagnostics.items():
        DIAG.finish_row(row, key_config(key)[2])
        ordered = sorted(session_diags[key],key=lambda r:r["session"])
        row["保存極値を連結した最大DD円"] = DIAG.joined_dd(ordered)
        row["場内最大DD円"] = max((r["場内最大DD円"] for r in ordered),default=Decimal(0))
    return {"試行":97,"成功":True,"scope":scope,"場数":len(sessions),"Actor数":16,"会計数":len(rows),
            "Actor設定":{key:{"入口":key_config(key)[0],"出口":key_config(key)[1],"共通基本保護":"P0",
                              "slip_pts":key_config(key)[4],"delay_seconds":key_config(key)[5]} for key in KEYS},
            "集計":{key:dict(row) for key,row in groups.items()},"実現診断":diagnostics,"場別":rows,
            "P0とH0の同実入口と実参加差":dict(comparisons),"純判定と共有枠":gates_all,
            "保存検算":"全注文/約定/配賦/半円/Source joins/TimelineのuW・極値算術・入口全枠・現在純採否。H0固有床/reasonを明示。",
            "独立監査への分担":"初回/極値/保護要求の全Scalar取り落としとSource後の全経路義務は、別の固定Tape金融監査へ入力SHAで結ぶ。",
            "未実施":{"原板/CSV/Go再生":0,"未参加/決済後仮想利益":0,"資本金ROI":None}}


def render(result: dict) -> str:
    """
    機能: 16独立運転の実現額だけを最小のMarkdown表へ出す。
    引数: result(dict)は検算済み集計。
    返り値: strは閲覧用。H0を旧P0の成績と混ぜない。
    """
    lines = ["# 97：初回費用後正益の全量確定・保存会計", "",
             f"{result['場数']}場/{result['会計数']}会計、scope={result['scope']}。H0の全経路規範と保存算術は別証拠。", "",
             "|入口/出口・Key|玉/枚|粗額円|fee円|slip円|純額円|正額/負額円|PF|u正益後赤字/正益玉|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key in KEYS:
        r,d = result["集計"][key],result["実現診断"][key]
        lines.append(f"|{key_config(key)[0]}/{key_config(key)[1]} {key}|{r['positions']}/{r['entry_quantity']}|{r['gross_yen']}|{r['fee_yen']}|{r['slip_yen']}|{r['net_yen']}|{d['正額円']}/{d['負額円']}|{d['PF']}|{r['unit_positive_closed_negative']}/{r['unit_positive_positions']}|")
    lines += ["", "各費用/遅延は別動的運転。差は同実入口と双方の実参加の実現額で比較し、機会損失・退出後価格・理想ピークを評価しない。", ""]
    return "\n".join(lines)


def main() -> int:
    """
    機能: 完了97保存と成功した独立Tape監査を読み、新規Viewer素材へ集計する。
    引数: --run/--audit/--condition/--out(Path)、--limit(int,2/54)は保存と監査と出力。
    返り値: intは全成功0。不整合は非0、既存出力は上書きしない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "audit", "condition", "out"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--limit",type=int,choices=(2,54),default=54)
    args = parser.parse_args()
    need(not args.out.exists(), "新規成果物dirだけ")
    completion_path = args.run/"完了.json"
    completion, audit, condition = BASE.read_json(completion_path), BASE.read_json(args.audit), BASE.read_json(args.condition)
    stage = "first2" if args.limit == 2 else "full54"
    need(completion["成功"] is True and completion["stage"] == stage and completion["場数"] == args.limit, "97完了stage")
    need(completion["口座/場"] == 16 and completion["P0対96全文比較/場"] == 8
         and completion["入力前後不変"] is True and completion["コード前後不変"] is True
         and completion["Source再運転"] is False and completion["チャート再計算"] is False
         and completion["Raw/CSV読取"] == 0, "97完了の16/8/固定通知範囲")
    equal(completion["入力前SHA256"], completion["入力後SHA256"], "Native入力前後辞書")
    equal(completion["コード前SHA256"], completion["コード後SHA256"], "Nativeコード前後辞書")
    need(audit["成功"] is True and audit["stage"] == stage and audit["場数"] == args.limit and audit["会計数"] == args.limit*16
         and audit["不一致数"] == 0 and audit["入力コード前後不変"] is True, "独立Tape金融の完了scope")
    equal(condition["試行"],97,"固定試行")
    equal(digest(args.condition),CONDITION_SHA,"97条件固定SHA")
    equal(condition["固定96完了SHA256"],PROOF96_SHA,"固定96完了")
    need(condition["市場損益を開く前の固定"] is True and bool(condition["コードSHA256"]),"固定条件")
    need(digest(PROOF96)==PROOF96_SHA,"固定96正本指紋")
    proof96 = BASE.read_json(PROOF96)
    catalog = {Path(n).name[:-8]:sha for n,sha in proof96["自己を除く正式指紋"].items()
               if re.fullmatch(r"成果物/\d{4}-\d{2}-\d{2}_(Day|Night)\.json\.gz",n.replace("\\","/"))}
    need(len(catalog)==54,"固定96の54許可")
    expected = {"2026-09-21_Day","2026-09-21_Night"} if args.limit==2 else set(catalog)
    outcomes = {r["session"]:r for r in completion["結果"]}
    equal(len(completion["結果"]),args.limit,"完了行の重複不可")
    equal(set(outcomes),expected,"完了場集合")
    aud_rows = {r["session"]:r for r in audit["details"]}
    equal(len(audit["details"]),args.limit,"監査行の重複不可")
    equal(set(aud_rows),expected,"監査場集合")
    code_paths = [Path(__file__),OLD_PATH,COUPLED_PATH,OLD.OLD_PATH,BASE.__file__,OLD.DIAG_PATH]
    before = {str(Path(p).resolve()):digest(Path(p)) for p in code_paths+[completion_path,args.audit,args.condition,PROOF96]}
    for name,sha in condition["コードSHA256"].items():
        path = (ROOT/name).resolve(); equal(digest(path),sha,"固定155等code")
        before[str(path)] = sha
    bodies, values, baselines = [], [], []
    for session in sorted(expected):
        paths = [p for p in (args.run/(session+".json"),args.run/(session+".json.gz")) if p.is_file()]
        need(len(paths)==1,"一場一保存形式")
        path = paths[0]; data=path.read_bytes(); before[str(path.resolve())]=hashlib.sha256(data).hexdigest()
        body=gzip.decompress(data) if path.suffix==".gz" else data
        equal(hashlib.sha256(body).hexdigest(),outcomes[session]["sha256"],"97元JSON指紋")
        need(any(Path(p).name==session+".json" and h==outcomes[session]["sha256"] for p,h in aud_rows[session]["入力SHA256前後"].items()),"H独立監査と同じ保存body")
        value=json.loads(body,parse_float=Decimal)
        equal(value["session"],session,"97場")
        oldpath=PROOF96.parent/"成果物"/(session+".json.gz");equal(digest(oldpath),catalog[session],"固定96 gzip")
        before[str(oldpath.resolve())]=catalog[session]
        old=json.loads(gzip.decompress(oldpath.read_bytes()),parse_float=Decimal)
        controls=[key for key in KEYS if not key.startswith("H0_")]
        for key in controls: equal(value["books"][key],old["books"][key],"P0旧96全金融全文")
        baselines.append({"session":session,"対照会計":8,"除外":[],"固定96保存SHA256":catalog[session]})
        bodies.append((session,body));values.append(value)
    result=analyze_values(values,"接続" if args.limit==2 else "正式")
    result.update({"P0旧96全文対照":baselines,"独立Tape金融監査SHA256":digest(args.audit),"条件SHA256":digest(args.condition),
                   "完了SHA256":digest(completion_path),"集計コードSHA256":digest(Path(__file__)),"入力依存SHA256前後":before})
    need(all(digest(Path(p))==h for p,h in before.items()),"保存集計の前後指紋差")
    args.out.mkdir(parents=True)
    resources=[]
    for value,(session,body) in zip(values,bodies):
        for key in KEYS:
            identity="97_"+key+"_"+session
            name=identity+".trades.jsonl"
            with (args.out/name).open("x",encoding="utf-8",newline="\n") as stream:
                for trade in BASE.viewer_trades(value["books"][key]):
                    stream.write(json.dumps(trade,ensure_ascii=False,default=BASE.serial,allow_nan=False)+"\n")
            resources.append({"id":identity,"title":"初回利益確定 "+key+" "+session,"symbol":"NK225","product":"NK225mini", "session":session,
                              "method_id":key,"point_value":100,"pnl_format":"trades","pnl_basis":"net","pnl_path":name,"market_path":"NK225/"+session+"/book.jsonl.gz"})
        with (args.out/(session+".json.gz")).open("xb") as file:
            with gzip.GzipFile(filename="",mode="wb",fileobj=file,mtime=0) as stream:stream.write(body)
    equal(len(resources),args.limit*16,"97全Viewer資源")
    BASE.write_json(args.out/"結果.json",result)
    BASE.write_json(args.out/"一覧.resources.json",{"schema_version":1,"path_base":"catalog","resources":resources})
    (args.out/"結果.md").write_text(render(result),encoding="utf-8",newline="\n")
    (args.out/"完了.json").write_bytes(completion_path.read_bytes())
    need(all(digest(Path(p))==h for p,h in before.items()),"成果物生成後の入力差")
    print(json.dumps({"成功":True,"場数":args.limit,"会計数":args.limit*16,"Viewer資源数":len(resources)},ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
