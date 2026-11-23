# 由来: work/99保存集計案/集計.py
# 由来SHA256: 0c410af795393f246e093ecd60e82bf22bfb3fc6211d556401bbc6a8fb9f13ab
"""99の12本名口座を保存検算・実現集約・Viewer変換する。stage証拠確定まで市場CLIを拒否する。"""

import argparse
from collections import Counter, defaultdict
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
OLD_PATH = ROOT/"scripts/FAR利益前ATR追尾の監査/集計.py"
OLD_SHA = "c7bd815c4157ef28e4d52d352207c1543a6dad3fcf474cf21be096ecf0fba340"
INDEPENDENT_PATH = ROOT/"scripts/FAR背景と勢いと数量の監査/E3と金融の照合.py"
INDEPENDENT_SHA = "75dc5309c3e9c0b79d094df7941be4b2b5c206f0bb0d51740fd33a448cbcf834"
MARKET_PATH = ROOT/"scripts/FAR背景と勢いと数量の監査/市場Tapeを照合する.py"
MARKET_SHA = "55abf75a6d8b924ad22a96b57d2399e524005c004e4ee77944fdd43addadad81"
CONDITION_SHA = "ba95b8c7df74f3b6f2f0f3cc349210ff284bdc64ed2fe79311d702ebff2b0f71"
PROOF98_SHA = "2ee9417d0cd1f8bef107712789d26e3f72c0f95a933e60b31bb3f11784ca0dfe"
COMPLETION_SHA = {"first2":"e8d069c9d71cd85bbd5407919d707f51579893e4bb3d823f2734a96996451ffd", "full54":"d945e5daf823d95e17eb897115d7dcbd96a94a2ac112a028267fb7ed7e847dcc"}
AUDIT_SHA = {"first2":"0cdb9a81f4868362d7b625f78734cc493eb55c33f468a252e3a1c611e87c9bfb", "full54":"592aff6b2a6b6eae4c3a10b4e5b7752e02972a7d489b04c73d92ab6654fedc2e"}


def digest(path: Path) -> str:
    """
    機能: 明示保存又はコードの指紋を計算する。
    引数: path(Path)は読取先。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed(name: str, path: Path, expected: str):
    """
    機能: 停止した保存金融又は新独立純式部品を再用する。
    引数: name/expected(str)、path(Path)は識別・指紋・コード先。
    返り値: moduleは固定部品。市場・原板・Sourceを実行しない。
    """
    if digest(path)!=expected: raise ValueError("固定保存部品SHA差:"+str(path))
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


OLD = fixed("固定98保存算術99",OLD_PATH,OLD_SHA)
INDEPENDENT = fixed("独立E3金融保存99",INDEPENDENT_PATH,INDEPENDENT_SHA)
BASE, DIAG = OLD.BASE, OLD.DIAG
need,equal,number,integer = OLD.need,OLD.equal,OLD.number,OLD.integer
KEYS = INDEPENDENT.KEYS


def pure_values(value):
    """
    機能: 純技法のJSON由来Decimalだけを元のGo float64表現へ戻す。
    引数: value(JSON互換値)は公開文脈又は候補。整数/未知/nullは維持する。
    返り値: JSON互換値は独立純式が元々受けるfloat表現。金融円会計はDecimalのまま別検査する。
    """
    return json.loads(json.dumps(value,ensure_ascii=False,default=BASE.serial,allow_nan=False))


def key_config(key: str) -> tuple:
    """
    機能: 本名12Keyを入口・共通金融名・費用・遅延へ分ける。
    引数: key(str)は99外Key。
    返り値: tupleはgate,risk空,newKey,old95,old94,cost,delay。技法名は旧A/ABに置き換えない。
    """
    need(key in KEYS,"99の12Actor Key")
    policy="E3S" if key.startswith("H0_E3S_") else "E3" if key.startswith("H0_E3_") else "G0"
    tail=key.split("_");cost,delay=int(tail[-2][1:]),int(tail[-1][1:])
    common=f"P0_C{cost}_D{delay}"
    return policy,"",key,"B5Q_"+common,common,cost,delay


def grid_key_config(key: str) -> tuple:
    """
    機能: 固定96の政策非限定の枠算術へ本名と共通会計名を渡す。
    引数: key(str)は99Key。
    返り値: tupleはgate,old95,old94,cost,delay。E3の採否は新独立器が計算する。
    """
    gate,_,_,old95,old94,cost,delay=key_config(key)
    return gate,old95,old94,cost,delay


def accepted_entries_at_grid(book: dict, at, q) -> set:
    """
    機能: 共通B5Qの同秒受理・取消・予約算術だけを再用する。
    引数: book(dict)、at(number)、q(dict|None)は原99保存と枠の気配。
    返り値: set[str]は原実注文ID。技法や金融の受理を捏造しない。
    """
    return OLD.OLD.OLD.OLD.accepted_entries_at_grid(dict(book,key=key_config(book["key"])[3]),at,q)


class SavedGates:
    """停止99の独立E3/E3S式を現在候補へ結ぶ保存索引。"""

    def __init__(self, value: dict):
        """
        機能: 全共有公開文脈と本名5tag記録を索引化する。
        引数: value(dict)は新99保存。
        返り値: None。保存採否を期待値にしない。
        """
        self.audit=INDEPENDENT.Audit()
        contexts=pure_values(value["chart_grids"])
        pure_record={**value,"chart_grids":contexts,"gate_assessments":pure_values(value["gate_assessments"])}
        self.core=INDEPENDENT.RecomputedGates(contexts,pure_record,self.audit)
        self.by_at={g["at"]:g for g in contexts}
        equal(len(self.by_at),len(value["chart_grids"]),"共有枠時計一意")
        ranks={key:n for n,key in enumerate(KEYS)}
        order=[(r["candidate"]["at"],ranks[r["key"]],r["ordinal"]) for r in value["gate_assessments"]]
        equal(order,sorted(order),"99保存純式の時計/12Key/ordinal順")

    def claim(self, key: str, candidate: dict) -> dict:
        """
        機能: 金融前資格/min量を満たした当候補だけを独立純式へ渡す。
        引数: key(str)、candidate(dict)は保存Source/注文で検算した現在候補。
        返り値: dictは新E3/E3S Decision。Source/数量/Quoteは変えない。
        """
        need(candidate["evaluated_at"] in self.by_at,"99当枠文脈欠落")
        self.core.current=self.by_at[candidate["evaluated_at"]]
        return self.core.claim(key,pure_values(candidate))

    def finish(self, clocks: list) -> dict:
        """
        機能: 口座別保存検査の巡回順と実配送順を分けて全集合を閉じる。
        引数: clocks(list[number])は金融の共有全枠。
        返り値: dictは件数。最新Scalarへの結合と全経路は別Tape独立監査が担当する。
        """
        equal(self.core.used,set(self.core.records),"99全適格/保存callback集合")
        equal([g["at"] for g in self.core.grids.values()],clocks,"99全共有枠")
        return {"共有枠":len(clocks),"適格出生判定":len(self.core.used),"口座別":dict(self.core.calls)}


def verify_saved_book(book: dict, key: str, gates: SavedGates, full_clock: bool) -> dict:
    """
    機能: 固定98の金融/H0/Source保存検算を、本名12Keyへ直接対応する。
    引数: book(dict)、key(str)、gates(SavedGates)、full_clock(bool)は保存と検査範囲。
    返り値: dictは原会計。旧の技法判断や偽の受理イベントを渡さない。
    """
    space={**vars(OLD),"key_config":key_config,"grid_key_config":grid_key_config,"accepted_entries_at_grid":accepted_entries_at_grid}
    run=types.FunctionType(OLD.verify_saved_book.__code__,space,"99共通金融と本名E3保存規範")
    checked=run(book,key,gates,full_clock)
    equal(checked["注文別"]["Risk"],{"要求回数":0,"要求枚数":0,"約定回数":0,"約定枚数":0},"99はRisk空固定")
    checked["注文別"]={n:checked["注文別"][n] for n in ("Source","H")}
    return checked


def realized_row(book: dict) -> dict:
    """
    機能: 実完結玉のPF/uW後赤字/未観測赤字と保存MTM/DDを集計する。
    引数: book(dict)は検算済み99口座。
    返り値: dictは実現取引の診断。仮想利益は計算しない。
    """
    row=DIAG.new_row()
    for p in book["positions"]:DIAG.OLD.add_position(row,p)
    DIAG.finish_row(row,key_config(book["key"])[3])
    account=book["account"]
    row.update({"場内最大DD円":account["max_drawdown"],"場内MTM最大円":account["max"]["equity"] if account["max"] else Decimal(0),"場内MTM最小円":account["min"]["equity"] if account["min"] else Decimal(0)})
    return row


def comparisons() -> list:
    """
    機能: G0対E3/E3SとE3対E3Sの12系列を固定列挙する。
    引数: なし。
    返り値: list[tuple[str,str]]は旧入口/新入口の実参加比較である。
    """
    output=[]
    for cost in (0,5):
        for delay in (0,1):
            keys=["H0_"+g+f"B5Q_P0_C{cost}_D{delay}" for g in ("","E3_","E3S_")]
            output.extend(((keys[0],keys[1]),(keys[0],keys[2]),(keys[1],keys[2])))
    return output


def judgment_counts(value: dict) -> dict:
    """
    機能: 新規/保有/待機/判定不能と本名checkの三値を別集計する。
    引数: value(dict)は純判断まで検算した新99保存。
    返り値: dictは各Keyの枠・技法・Source段階。G0の技法未使用を明示する。
    """
    output={}
    for key,book in value["books"].items():
        rows={"枠":Counter({s:0 for s in ("新規","保有","待機","判定不能")}),"技法機会":Counter({s:0 for s in ("成立","既知拒否","必要未知")}),"check":{},"Source段階":{},"技法未使用":key_config(key)[0]=="G0"}
        for trace in book["grid_traces"]:rows["枠"][trace["action"]]+=1
        for p in book["entry_opportunities"]:
            kind=p["source"]["kind"]
            k=rows["Source段階"].setdefault(kind,{"出生":0,"受理":0,"実取得":0,"枚数":0})
            k["出生"]+=1;k["受理"]+=p["status"]=="accepted"
        for p in book["positions"]:
            k=rows["Source段階"][p["source"]["kind"]];k["実取得"]+=1;k["枚数"]+=p["initial_quantity"]
        output[key]=rows
    for record in value["gate_assessments"]:
        rows=output[record["key"]];d=record["assessment"]["decision"]
        rows["技法機会"]["成立" if d["known"] and d["allowed"] else "既知拒否" if d["known"] else "必要未知"]+=1
        for check in record["assessment"]["checks"]:
            row=rows["check"].setdefault(check["id"],Counter({s:0 for s in ("既知成立","既知不成立","未知")}))
            row["未知" if not check["known"] else "既知成立" if check["passed"] else "既知不成立"]+=1
    return output


def merge_judgments(target: dict, source: dict) -> None:
    """
    機能: 判断分類の件数だけを場間で加算する。
    引数: target/source(dict)は同一Key構造の累積と当場分類。
    返り値: None。boolの未使用意味を数値へ変えない。
    """
    for key,row in source.items():
        if key not in target:target[key]={"枠":Counter(),"技法機会":Counter(),"check":{},"Source段階":{},"技法未使用":row["技法未使用"]}
        out=target[key];equal(out["技法未使用"],row["技法未使用"],"技法使用区分")
        for name in ("枠","技法機会"):out[name].update(row[name])
        for name in ("check","Source段階"):
            for label,counts in row[name].items():out[name].setdefault(label,Counter()).update(counts)


def analyze_values(values, scope: str) -> dict:
    """
    機能: 全12の保存金融・本名純式を検算し実現額と12比較を集約する。
    引数: values(iterable[dict])、scope(str)は新保存と人工/接続/正式。
    返り値: dictは成績・参加差・判断分類。未参加/退出後仮想利益は作らない。
    """
    need(scope in ("人工","接続","正式"),"99保存scope")
    groups={k:defaultdict(Decimal) for k in KEYS};diagnostics={k:DIAG.new_row() for k in KEYS};session_rows={k:[] for k in KEYS}
    orders={k:{n:defaultdict(int) for n in ("Source","H")} for k in KEYS}
    rows,sessions,pairs,gates_all,judgments=[],set(),defaultdict(list),[],{}
    for value in values:
        session=value["session"];need(session not in sessions,"99場重複");sessions.add(session)
        equal(value["trial"],99,"99新envelope識別");equal(set(value["books"]),set(KEYS),"99全12")
        clocks=[r["at"] for r in value["books"][KEYS[0]]["grid_traces"]]
        gates,checked=SavedGates(value),{}
        for key in KEYS:
            book=value["books"][key]
            equal([r["at"] for r in book["grid_traces"]],clocks,"99同場12時計")
            try:current=checked[key]=verify_saved_book(book,key,gates,scope!="人工")
            except (ValueError,AssertionError,KeyError) as error:raise ValueError(f"{session}/{key}: {error}") from error
            row=realized_row(book);equal(row["純額円"],current["totals"]["net_yen"],"実玉/会計純額");equal(row["玉数"],current["counts"]["positions"],"実玉分母")
            for name in DIAG.COUNTERS:diagnostics[key][name]+=row[name]
            session_rows[key].append({"session":session,**row})
            rows.append({"session":session,"key":key,"totals":current["totals"],"counts":current["counts"],"grid_metrics":book["grid_metrics"],"実現診断":row,"注文別":current["注文別"]})
            for collection in (current["totals"],current["counts"]):
                for name,amount in collection.items():groups[key][name]+=amount
            for name,amount in book["grid_metrics"].items():groups[key]["grid_"+name]+=amount
            for name,collection in current["注文別"].items():
                for metric,amount in collection.items():orders[key][name][metric]+=amount
            groups[key]["active_sessions"]+=current["counts"]["positions"]>0;groups[key]["negative_sessions"]+=current["totals"]["net_yen"]<0
        gates_all.append({"session":session,**gates.finish(clocks)})
        for before,after in comparisons():pairs[after+"対"+before].append({"session":session,**BASE.compare_positions(checked[before],checked[after])})
        merge_judgments(judgments,judgment_counts(value))
    if scope!="人工":equal(len(sessions),54 if scope=="正式" else 2,"99保存場数")
    for key,row in diagnostics.items():
        DIAG.finish_row(row,key_config(key)[3]);ordered=sorted(session_rows[key],key=lambda r:r["session"])
        row["保存極値を連結した最大DD円"]=DIAG.joined_dd(ordered);row["場内最大DD円"]=max((r["場内最大DD円"] for r in ordered),default=Decimal(0))
    return {"試行":99,"成功":True,"scope":scope,"場数":len(sessions),"Actor数":12,"会計数":len(rows),
            "Actor設定":{k:{"入口":key_config(k)[0],"出口":"H0","初期risk":"","共通基本保護":"P0","slip_pts":key_config(k)[5],"delay_seconds":key_config(k)[6]} for k in KEYS},
            "集計":{k:dict(v) for k,v in groups.items()},"実現診断":diagnostics,"場別":rows,
            "注文別":{k:{n:dict(v) for n,v in d.items()} for k,d in orders.items()},"入口間の同実入口と実参加差":dict(pairs),"判断分類":judgments,"純判定と共有枠":gates_all,
            "保存検算":"固定98の全注文/約定/配賦/半円/MTM点/H0/Sourceと出生一回枠算術を直接再用。本名E3/E3S全checkは新独立純式へ結ぶ。Riskは空。",
            "独立監査への分担":"全Scalarの初回/極値/適格fill/Source作用/現在文脈の出典・callback順は別Tape金融監査に同じ入力SHAで結ぶ。保存点だけを全経路再計算とは呼ばない。",
            "未実施":{"原板/CSV/Go再生":0,"未参加/決済後仮想利益":0,"資本金ROI":None}}


def render(result: dict) -> str:
    """
    機能: 12本名口座の実現額と分母を簡潔なMarkdownへ出す。
    引数: result(dict)は検算済み結果。
    返り値: strは閲覧用表。0取引/PF未定義を安定利益としない。
    """
    lines=["# 99候補：背景と勢いと数量の保存会計","",f"scope={result['scope']}、{result['場数']}場/{result['会計数']}会計。","","|Key|玉/枚|粗額円|fee円|slip円|純額円|PF|u正益後赤字/正益玉|","|---|---:|---:|---:|---:|---:|---:|---:|"]
    for key in KEYS:
        r,d=result["集計"][key],result["実現診断"][key]
        lines.append(f"|{key}|{r['positions']}/{r['entry_quantity']}|{r['gross_yen']}|{r['fee_yen']}|{r['slip_yen']}|{r['net_yen']}|{d['PF']}|{r['unit_positive_closed_negative']}/{r['unit_positive_positions']}|")
    return "\n".join(lines+["","比較は実在Source出生→同実入口/取得変更/双方片側参加の実現額だけ。費用/遅延は別運転、DDは保存極値の連結。",""])


def write_viewer(out: Path, values: list) -> list:
    """
    機能: 12×場の実約定をschema1/mini倍率100のViewer形式へ変換する。
    引数: out(Path)、values(list[dict])は新規出力と検算済み保存。
    返り値: list[dict]は資源。半円費用を維持し、空取引の行を捏造しない。
    """
    resources=[]
    for value in values:
        session=value["session"]
        for key in KEYS:
            identity="99_"+key+"_"+session;name=identity+".trades.jsonl"
            with (out/name).open("x",encoding="utf-8",newline="\n") as stream:
                for trade in BASE.viewer_trades(value["books"][key]):stream.write(json.dumps(trade,ensure_ascii=False,default=BASE.serial,allow_nan=False)+"\n")
            resources.append({"id":identity,"title":"背景と勢いと数量 "+key+" "+session,"symbol":"NK225","product":"NK225mini","session":session,"method_id":key,"point_value":100,"pnl_format":"trades","pnl_basis":"net","pnl_path":name,"market_path":"NK225/"+session+"/book.jsonl.gz"})
    return resources


def require_market_fixed(stage: str) -> None:
    """
    機能: 条件・98完了・99実金融・99独立証拠の未確定を入力読取前に拒否する。
    引数: stage(str)はfirst2/full54。
    返り値: None。未設定/不正指紋はValueError。
    """
    need(stage in ("first2","full54"),"99保存stage")
    need(all(re.fullmatch(r"[0-9a-f]{64}",v or "") for v in (CONDITION_SHA,PROOF98_SHA,COMPLETION_SHA[stage],AUDIT_SHA[stage])),"99条件/98完了/99実金融/99独立SHAが未固定のため市場保存CLIは禁止")


def main() -> int:
    """
    機能: 固定後だけ99保存と独立証拠を同じ入力指紋へ結び12資源/場を作る。
    引数: --run/--audit/--condition/--proof98/--index/--out(Path)、--limit(int,2/54)は明示保存と範囲。
    返り値: intは成功0。現試作では全placeholderが未設定なので市場は必ず拒否する。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("run","audit","condition","proof98","index","out"):parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--limit",type=int,choices=(2,54),default=54)
    args=parser.parse_args();stage="first2" if args.limit==2 else "full54"
    require_market_fixed(stage)
    need(not args.out.exists(),"新規成果物先だけ")
    files=(args.condition,args.proof98,args.run/"完了.json",args.audit)
    expected=(CONDITION_SHA,PROOF98_SHA,COMPLETION_SHA[stage],AUDIT_SHA[stage])
    for p,h in zip(files,expected):equal(digest(p),h,"99固定入力SHA")
    market=fixed("固定99市場の保存guard",MARKET_PATH,MARKET_SHA)
    equal(args.proof98.resolve(),market.PROOF98.resolve(),"固定98証拠の明示先")
    tasks,before,input_groups=market.prepare(args.index.resolve(),args.run.resolve(),args.condition.resolve(),stage)
    audit=BASE.read_json(args.audit)
    need(audit["成功"] is True and audit["stage"]==stage and audit["場数"]==args.limit and audit["会計数"]==args.limit*12
         and audit["空Gate対98H0全文会計"]==args.limit*4 and audit["不一致数"]==0 and audit["入力コード前後不変"] is True,"99独立全金融/G0四対照完了")
    audit_rows={r["session"]:r for r in audit["details"]}
    equal(len(audit_rows),len(audit["details"]),"監査場重複なし")
    equal(set(audit_rows),{t["session"] for t in tasks},"独立監査の同場集合")
    for p in (Path(__file__),OLD_PATH,INDEPENDENT_PATH,MARKET_PATH,args.audit):before[str(p.resolve())]=digest(p)
    values,bodies,baselines=[],[],[]
    for task in tasks:
        session=task["session"]
        for name in ("tape","result","native98","native97","native96"):
            path=Path(task[name]).resolve()
            equal(audit_rows[session]["入力SHA256前後"].get(str(path)),task[name+"_sha256"],"独立全金融と同じ入力:"+name)
        path=Path(task["result"]);body=path.read_bytes()
        equal(hashlib.sha256(body).hexdigest(),task["result_sha256"],"99元bodySHA")
        value=json.loads(body,parse_float=Decimal);equal(value["session"],session,"99場")
        need(value["actual_run_complete"] is True and value["source_reexecuted"] is False and value["charts_recomputed"] is False,"99新運転の完了範囲")
        oldpath=Path(task["native98"])
        old=json.loads(gzip.decompress(oldpath.read_bytes()),parse_float=Decimal)
        INDEPENDENT.compare_empty_gate98(value,old)
        baselines.append({"session":session,"対照会計":4,"除外":[],"固定98保存SHA256":task["native98_sha256"]})
        values.append(value);bodies.append((session,body))
    result=analyze_values(values,"接続" if args.limit==2 else "正式")
    result.update({"空Gate旧98H0全文対照":baselines,"独立Tape金融監査SHA256":digest(args.audit),"条件SHA256":digest(args.condition),"完了SHA256":digest(args.run/"完了.json"),"集計コードSHA256":digest(Path(__file__)),"入力依存SHA256前後":before,**input_groups})
    need(all(digest(Path(p))==h for p,h in before.items()),"保存集計前後差")
    args.out.mkdir(parents=True);resources=write_viewer(args.out,values);equal(len(resources),args.limit*12,"99表示資源")
    for session,body in bodies:
        with (args.out/(session+".json.gz")).open("xb") as file:
            with gzip.GzipFile(filename="",mode="wb",fileobj=file,mtime=0) as stream:stream.write(body)
    BASE.write_json(args.out/"結果.json",result);BASE.write_json(args.out/"一覧.resources.json",{"schema_version":1,"path_base":"catalog","resources":resources})
    (args.out/"結果.md").write_text(render(result),encoding="utf-8",newline="\n");(args.out/"完了.json").write_bytes((args.run/"完了.json").read_bytes())
    need(all(digest(Path(p))==h for p,h in before.items()),"成果生成後入力差")
    print(json.dumps({"成功":True,"場数":args.limit,"会計数":args.limit*12,"Viewer資源数":len(resources)},ensure_ascii=False))
    return 0


if __name__=="__main__":raise SystemExit(main())
