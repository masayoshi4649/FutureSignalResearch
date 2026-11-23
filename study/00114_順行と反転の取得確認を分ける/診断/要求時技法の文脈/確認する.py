"""Root解禁済み114全70正本を独立な小演算で照合しRの当時値を記述する。"""
from collections import Counter,defaultdict
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import gzip
import hashlib
import json

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
REQUEST=ROOT/"work/114進行/full70_同入口診断要求.json"
REQUEST_SHA="b4c47a33e578b08d81159cb73d69f5f432d41dbb7588341d5c3f2bafa1aa96f0"
RESULT=ROOT/"work/114同入口と要求時技法の実現差/全70の実現差/結果.json"
RESULT_SHA="775b5f29349fa8e8d43caee63b094fe7edd247ae2fdb32342c9d730fdabd5843"
MODES=("A0","T","TR");COSTS=((0,0),(0,1),(5,0),(5,1));PAIRS=(("A0","T"),("A0","TR"),("T","TR"));PERIODS=("全70","元54","追加16","11月06");OWNERS=("全枝","core","addon","episode","不明");GROUPS=("同実入口","取得変更","前のみ","後のみ");CLASSES=("T真","R真","双方偽","TR未知")
BEFORE={};CHECKS=Counter();ZERO=Decimal(0)


def need(value: bool,label: str) -> None:
    """
    機能: 事実の不一致を推測で補正せず拒否する。
    引数: value(bool)、label(str)。返り値: None。不成立はValueError。
    """
    if not value:raise ValueError(label)
    CHECKS[label]+=1


def digest(path: Path) -> str:
    """
    機能: 解禁済み正本と停止所有コードの指紋を求める。
    引数: path(Path)。返り値: strはSHA256。Rawは対象外。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(ref: dict) -> dict:
    """
    機能: 明示SHAを認証したJSON/gzipJSONだけを十進数で読む。
    引数: ref(dict)。返り値: dictは原値。前後指紋にも追加する。
    """
    p=Path(ref["path"]).resolve();sha=digest(p);need(sha==ref["sha256"],"参照SHA");BEFORE[str(p)]=sha
    opener=gzip.open if p.suffix==".gz" else open
    with opener(p,"rt",encoding="utf-8-sig") as f:return json.load(f,parse_float=Decimal)


def serial(value):
    """
    機能: 記述結果の有限十進数をJSON数値へ写す。
    引数: value(object)。返り値: int/float。対応外はTypeError。
    """
    if isinstance(value,Decimal) and value.is_finite():return int(value) if value==value.to_integral_value() else float(value)
    raise TypeError(type(value).__name__)


def save(name: str,value: dict) -> dict:
    """
    機能: 新規の小要約だけをUTF-8保存する。
    引数: name(str)、value(dict)。返り値: dictはFileRef。
    """
    p=HERE/name
    with p.open("x",encoding="utf-8",newline="\n") as f:f.write(json.dumps(value,ensure_ascii=False,indent=2,default=serial,allow_nan=False)+"\n")
    return {"path":str(p),"sha256":digest(p)}


def choose(row: dict,period: str,owner: str) -> bool:
    """
    機能: 結果と無関係な固定期間・保存ownerを選ぶ。
    引数: row(dict)、period/owner(str)。返り値: bool。
    """
    sid=row["session"]
    return (owner=="全枝" or row["owner"]==owner) and (period=="全70" or period=="元54" and sid[:10]<="2026-10-27" or period=="追加16" and sid[:10]>="2026-10-28" or period=="11月06" and sid.startswith("2026-11-06"))


def category(d: dict) -> str:
    """
    機能: 三値T/Rを元意図の推測なしで4分類する。
    引数: d(dict)。返り値: strは要求時の分類名。
    """
    t,r=d["trend"],d["reversal"];need(t!=2 or r!=2,"T/R排他")
    return "T真" if t==2 else "R真" if r==2 else "双方偽" if t==r==1 else "TR未知"


def stats(rows: list[dict]) -> dict:
    """
    機能: 実pos/実fillから枚数・正負純額・正益後赤字・cash DDを独立集計する。
    引数: rows(list[dict])。返り値: dict。未取得の仮額はない。
    """
    out={"玉":len(rows),"枚":sum(x["qty"] for x in rows),"実現円":sum((x["net"] for x in rows),ZERO),"利益総額円":sum((max(ZERO,x["net"]) for x in rows),ZERO),"損失総額円":sum((min(ZERO,x["net"]) for x in rows),ZERO),"正益後赤字玉":sum(x["positive"] and x["net"]<0 for x in rows),"起動後赤字玉":sum(x["active"] and x["net"]<0 for x in rows)}
    cash=peak=dd=ZERO
    for event in sorted((e for x in rows for e in x["cash"]),key=lambda e:e[:3]):cash+=event[-1];peak=max(peak,cash);dd=max(dd,peak-cash)
    need(cash==out["実現円"],"実fill cash加法");out["実約定cash列DD円"]=dd;return out


def same_stats(expected: dict,rows: list[dict]) -> None:
    """
    機能: 保存診断統計を独立な実pos/fill算術へ照合する。
    引数: expected(dict)、rows(list[dict])。返り値: None。
    """
    for key,value in stats(rows).items():need(expected[key]==value,"正本統計一致:"+key)


def normalize(value,mapping: dict):
    """
    機能: 実保護注文を所有検査後にordinal化する。
    引数: value(JSON値)、mapping(dict)。返り値: JSON値。金融値を除外しない。
    """
    if isinstance(value,list):return [normalize(v,mapping) for v in value]
    if isinstance(value,dict):
        out={}
        for key,item in value.items():
            if key=="exit_order_id" and item:need(item in mapping,"保護注文所有");out[key]=mapping[item]
            else:out[key]=normalize(item,mapping)
        return out
    return value


def exit_value(book: dict,p: dict) -> dict:
    """
    機能: 同入口のP100初期・全返済要求/fill/保護/終端を直接比較へ写す。
    引数: book/p(dict)。返り値: dictは実IDだけを分離した金融全値。
    """
    orders=[o for o in book["orders"] if o["position_id"]==p["id"] and o["kind"]=="exit"];mapping={o["id"]:i for i,o in enumerate(orders)}
    result={"orders":[{k:v for k,v in o.items() if k not in ("id","position_id","fill_id")} for o in orders],"fills":[],"audit":normalize(p["protection113"],mapping),"final":{k:p[k] for k in ("closed_quantity","closed_quote","gross_yen","realized_net","marks","protection_active","activation","floor_gain","floor_updated","first_floor_hit","atr")}}
    for f in book["fills"]:
        if f["position_id"]!=p["id"] or f["action"]!="close":continue
        need(f["order_id"] in mapping,"返済fill所有");v={k:v for k,v in f.items() if k not in ("id","order_id","position_id","allocations")};v["ordinal"]=mapping[f["order_id"]];v["allocations"]=[{k:v for k,v in a.items() if k!="position_id"} for a in f["allocations"]];result["fills"].append(v)
    return result


def sign(value) -> str:
    """
    機能: 未知と正/非正を固定の零境界で分ける。
    引数: value(Decimal/int/None)。返り値: str。
    """
    return "不明" if value is None else "正" if value>0 else "非正"


def r_context(actual: dict,record: dict,p: dict,owner: str) -> dict:
    """
    機能: R実玉の要求時固定Frameと同じ公表だけから追加背景を読む。
    引数: actual/record/p(dict)、owner(str)。返り値: dictは記述観測。効果推定ではない。
    """
    d=record["decision"];cur=d["current"];frame=cur["frame"];side=p["side"];at=record["request"]["at"]
    publications=[x for x in actual["publications"] if x["frame"]["id"]==frame["id"]];need(len(publications)==1,"R同ID公表一意");pub=publications[0]
    need(pub["frame"]==frame and pub["at"]==cur["delivered"]["time"]<=at["time"],"R当時配送Frame一致")
    need(cur["delivered"]["index"]<=at["index"] and cur["delivered"]["source_line"]<=at["source_line"] and frame["available_at"]<=at["time"],"R要求前配送済")
    own,opposite=("buy","sell") if side==1 else ("sell","buy");my=pub[own];opp=pub[opposite];pivot=opp["prior_pivot"]
    gap=None;through="不明"
    if pivot is not None:
        need(pivot["published_at"]<=frame["end"] and pivot["confirm_end"]<=pivot["published_at"] and pivot["kind"]==("high" if side==1 else "low"),"R反対側pivotの当時性")
        gap=side*(frame["close"]-pivot["price"]);through="真" if gap>0 else "偽"
    latest=pivot;new_same_publication=False
    for candidate in pub["result"]["new_pivots"] or []:
        if candidate["kind"]!=("high" if side==1 else "low"):continue
        need(candidate["published_at"]<=frame["end"] and candidate["confirm_end"]<=candidate["published_at"],"R同公表新pivotの当時性")
        if latest is None or candidate["published_at"]>latest["published_at"]:latest=candidate;new_same_publication=True
    latestgap=None if latest is None else side*(frame["close"]-latest["price"])
    v=d["values"];need(abs(v["hist_level"]-side*frame["hist"])<=Decimal("1e-10"),"R符号Hist水準")
    need(d["previous"] is not None and abs(v["a21"]-side*(frame["ema21"]-d["previous"]["frame"]["ema21"]))<=Decimal("1e-10"),"R符号slow傾き")
    flags={"C":my["c"],"M":my["m"],"P":0 if not pub["result"][own]["P"]["known"] else 2 if pub["result"][own]["P"]["passed"] else 1,"B":0 if my["bb"] is None else my["bb"]["contraction"]}
    return {"session":record["decision"]["scope"]["session"],"method":record["request"]["method"],"signal_id":record["request"]["signal_id"],"side":side,"owner":owner,"要求原行":at,"実取得原行":p["entry_quote"],"実枚":p["initial_quantity"],"公表ID":frame["id"],"実配送":cur["delivered"],"確定足終端":frame["end"],"7値":v,"Hist水準分類":sign(v["hist_level"]),"slow傾き分類":sign(v["a21"]),"反対側pivot":pivot,"確定Close突破差pt":gap,"反対側pivot突破":through,"最新公表反対側pivot":latest,"最新pivotは同公表で新確認":new_same_publication,"最新公表pivot突破差pt":latestgap,"最新公表反対側pivot突破":"不明" if latestgap is None else "真" if latestgap>0 else "偽","保存技法三値":flags,"公表FrameSHA256":pub["frame_sha256"],"公表ResultSHA256":pub["result_sha256"],"費用別":{}}


def main() -> None:
    """
    機能: Root明示全70参照を認証して正本レビューとR記述診断を保存する。
    引数: なし。返り値: None。Raw/金融再走/最適化は実施しない。
    """
    request=load({"path":str(REQUEST),"sha256":REQUEST_SHA});r=load({"path":str(RESULT),"sha256":RESULT_SHA})
    need(request["market_native_read_authorized"] and request["stage"]=="full70" and r["成功"] and r["金融条件SHA256"]==request["condition"]["sha256"] and r["Root要求"]["sha256"]==REQUEST_SHA,"Root全70解禁と同体")
    refs={k:load(request[k]) for k in ("comparison_stop","condition","completion","saved_result","saved_check","entry_check")}
    for p,sha in refs["comparison_stop"]["所有ファイルSHA256"].items():need(digest(Path(p))==sha,"停止所有不変");BEFORE[p]=sha
    complete,saved=refs["completion"],refs["saved_result"];need(complete["success"] and complete["sessions"]==70 and complete["books"]==840 and r["前後不変"] and r["入力SHA256前"]==r["入力SHA256後"],"全成功不変")
    matchref=r["対応台帳"];p=Path(matchref["path"]);need(digest(p)==matchref["sha256"],"対応台帳SHA");BEFORE[str(p)]=matchref["sha256"]
    with gzip.open(p,"rt",encoding="utf-8") as f:matches=[json.loads(x,parse_float=Decimal) for x in f]
    need(len(matches)==matchref["件数"]==5060,"対応台帳全件");matchmap={(x["session"],x["対照"],tuple(x["base"])):x for x in matches};need(len(matchmap)==len(matches),"対応台帳重複なし")
    allrows=defaultdict(list);allgates=defaultdict(list);pairgroups=defaultdict(lambda:{g:{s:[] for s in ("前","後")} for g in GROUPS});common=Counter();rrows={}
    scene_index={(x["session"],x["対照"]):x for x in r["場別"]}
    for scene in complete["results"]:
        sid=scene["session"];native=load(scene["native"]);actual=native["actual"];owners={}
        for src in native["source"]["sources"].values():
            if src["config"]["product"]!="NK225mini":continue
            for x in src["signals"]:
                s=x["signal"]
                if s["action"]=="new":owners[(src["method"],s["side"],s["id"])]=s.get("owner") or "不明"
        books=actual["books"];rows={}
        for key,b in books.items():
            positions={p["id"]:p for p in b["positions"]};local=[];seen=set()
            for rec in b["entry_gate"]["records"] or []:
                q=rec["request"];base=(sid,q["product"],q["method"],q["side"],q["signal_id"]);owner=owners[(q["method"],q["side"],q["signal_id"])];cl=category(rec["decision"])
                g={"session":sid,"owner":owner,"class":cl,"missing":bool(rec["decision"]["missing_inputs"]),"selected":rec["selected"],"actual":rec["actual_quantity"],"accepted":rec["accepted_quantity"],"frame":None if rec["decision"]["current"] is None else rec["decision"]["current"]["frame"]["id"]};allgates[key].append(g)
                if rec["actual_quantity"]==0:continue
                p=positions[rec["actual_position_id"]];need(base not in seen and p["initial_quantity"]==rec["actual_quantity"],"実玉出生と量");seen.add(base)
                ownfills=[(i,f) for i,f in enumerate(b["fills"]) if f["position_id"]==p["id"]];parts=[a for _,f in ownfills if f["action"]=="close" for a in f["allocations"]]
                need(sum(x["net_yen"] for x in parts)==p["realized_net"] and sum(x["quantity"] for x in parts)==p["initial_quantity"],"返済片純額と量")
                row={"base":base,"id":p["id"],"session":sid,"owner":owner,"class":cl,"missing":g["missing"],"net":p["realized_net"],"qty":p["initial_quantity"],"entry":(p["source"],p["source_hold_id"],p["entry_quote"],p["entry_price"],p["initial_quantity"]),"cash":[(sid,f["quote"]["index"],i,f["net_contribution_yen"]) for i,f in ownfills],"positive":p["marks"]["first_whole_positive"] is not None,"active":p["protection_active"],"exit":exit_value(b,p)};local.append(row)
                if key.startswith("TR_") and cl=="R真":
                    if base not in rrows:rrows[base]=r_context(actual,rec,p,owner)
                    need(rrows[base]["公表ID"]==rec["decision"]["current"]["frame"]["id"],"R費用間公表一致");rrows[base]["費用別"][key.removeprefix("TR_")]={"net_yen":row["net"],"正益後赤字":row["positive"] and row["net"]<0,"起動":row["active"],"枚":row["qty"]}
            need(len(local)==len(positions) and sum(x["net"] for x in local)==b["totals"]["net_yen"],"全実玉実現へ一致");rows[key]={x["base"]:x for x in local};allrows[key].extend(local)
        for a,b in PAIRS:
            for c,d in COSTS:
                name=f"{a}→{b}_C{c}_D{d}";left,right=rows[f"{a}_C{c}_D{d}"],rows[f"{b}_C{c}_D{d}"];count=Counter()
                for base in left.keys()|right.keys():
                    l,z=left.get(base),right.get(base);group="後のみ" if l is None else "前のみ" if z is None else "同実入口" if l["entry"]==z["entry"] else "取得変更"
                    m=matchmap[(sid,name,base)];need(m["群"]==group,"独立入口四群一致");count[group]+=1
                    if l is not None:pairgroups[name][group]["前"].append(l)
                    if z is not None:pairgroups[name][group]["後"].append(z)
                    if group=="同実入口":need(l["exit"]==z["exit"] and l["net"]==z["net"],"共通入口の全返済保護同体");common[name]+=1
                sc=scene_index[(sid,name)];need(sc["共通返済"]["共通入口数"]==count["同実入口"] and sc["共通返済"]["返済差あり"]==0,"場別共通入口数")
    for x in r["集計"]:
        pg=pairgroups[x["対照"]];p,o=x["期間"],x["owner"];delta=ZERO;allside={s:[] for s in ("前","後")}
        for group in GROUPS:
            amounts={}
            for s in ("前","後"):
                picked=[v for v in pg[group][s] if choose(v,p,o)];same_stats(x["四群"][group][s],picked);allside[s].extend(picked);amounts[s]=sum((v["net"] for v in picked),ZERO)
            need(x["四群"][group]["実現差円"]==amounts["後"]-amounts["前"],"四群実現差一致");delta+=amounts["後"]-amounts["前"]
        need(delta==x["全体"]["実現差円"],"全差の四群加法")
        for s in ("前","後"):
            same_stats(x["全体"][s],allside[s]);need(x["全体"][s]["要求時input_missing玉"]==sum(v["missing"] for v in allside[s]),"成立玉不足集計")
            for cl in CLASSES:same_stats(x["成立玉の要求時技法別"][cl][s],[v for v in allside[s] if v["class"]==cl])
        n=len([v for v in pg["同実入口"]["前"] if choose(v,p,o)]);need(x["共通入口の同保護確認"]["全返済と保存保護同体"]==n,"集計共通入口数")
    for x in r["全Source要求時技法"]:
        gs=[v for v in allgates[x["key"]] if choose(v,x["期間"],x["owner"])];need(x["Source出生数"]==len(gs),"全要求分母一致")
        for sel,name in ((2,"selected_true"),(1,"selected_false"),(0,"selected_unknown")):need(x[name]==sum(v["selected"]==sel for v in gs),"選別三値分母一致")
        need(x["input_missing"]==sum(v["missing"] for v in gs),"全要求不足一致")
        for cl in CLASSES:
            vs=[v for v in gs if v["class"]==cl];expected=x["要求時技法"][cl];need(expected["Source出生数"]==len(vs) and expected["実取得数"]==sum(v["actual"]>0 for v in vs) and expected["実取得枚"]==sum(v["actual"] for v in vs) and expected["distinct公表ID数"]==len({(v["session"],v["frame"]) for v in vs if v["frame"] is not None}),"分類出生取得公表数一致")
    need(len(rrows)==25 and len({(v["session"],v["公表ID"]) for v in rrows.values()})==23,"R25玉23公表")
    rlist=sorted(rrows.values(),key=lambda v:(v["session"],v["要求原行"]["index"],v["signal_id"]));description={}
    for axis in ("Hist水準分類","slow傾き分類","反対側pivot突破","最新公表反対側pivot突破","保存技法三値.C","保存技法三値.M","保存技法三値.P","保存技法三値.B"):
        groups=defaultdict(list)
        for row in rlist:
            value=row[axis] if "." not in axis else row["保存技法三値"][axis.split(".")[1]];groups[str(value)].append(row)
        description[axis]={}
        for value,group in sorted(groups.items()):
            description[axis][value]={"実玉":len(group),"distinct公表ID":len({(v["session"],v["公表ID"]) for v in group}),"費用別":{f"C{c}_D{d}":{"実現円":sum(v["費用別"][f"C{c}_D{d}"]["net_yen"] for v in group),"正益玉":sum(v["費用別"][f"C{c}_D{d}"]["net_yen"]>0 for v in group),"赤字玉":sum(v["費用別"][f"C{c}_D{d}"]["net_yen"]<0 for v in group),"利益総額円":sum(max(0,v["費用別"][f"C{c}_D{d}"]["net_yen"]) for v in group),"損失総額円":sum(min(0,v["費用別"][f"C{c}_D{d}"]["net_yen"]) for v in group)} for c,d in COSTS}}
    after={p:digest(Path(p)) for p in BEFORE};need(after==BEFORE,"全入力停止前後不変")
    summary={"試行":114,"成功":True,"正本":{"path":str(RESULT),"sha256":RESULT_SHA},"Root要求":{"path":str(REQUEST),"sha256":REQUEST_SHA},"独立検査":dict(CHECKS),"共通入口数":dict(common),"同体を確認した対照延べ共通入口":sum(common.values()),"全Native":70,"四群/技法の検算対象集計":len(r["集計"]),"全要求の検算対象集計":len(r["全Source要求時技法"]),"検算コード":{"path":str(Path(__file__).resolve()),"sha256":digest(Path(__file__))},"派生指標照合":"IEEE754計算値をJSON化した丸め差は1e-10pt以内。真偽・金融純額・入口同体は完全一致。","入力SHA256前":BEFORE,"入力SHA256後":after,"前後不変":True,"未実施":{"Raw/価格CSV/11月09/新金融再走/退出後仮利益":0,"新閾値最適化":0}}
    review=save("正本の独立確認.json",summary);context=save("R25玉の要求時文脈.json",{"試行":114,"成功":True,"記述診断のみ":True,"対象":"TR実R真25玉、費用4は同出生の感度で独立標本にしない","定義":{"反対側pivot突破":"要求時固定Frameと同じ公表の反対側prior_pivot（買いhigh/売りlow）を確定Closeが厳密に順方向へ越えたか。当足新pivotや現在板は使わない。","最新公表反対側pivot突破":"同公表で新確認した反対側pivotも含め、要求前に配送済みの最新反対側pivotを用いる別記述。後続公表は使わない。","P":"当該sideの既知支持否定。反対側pivot突破とは別。","三値":"0不明/1偽/2真","15分当時値":"未保存のため未使用。場末snapshotの遡及なし。"},"記述集計":description,"実玉":rlist,"正本確認":review,"限界":["25実玉23公表は少数で同場・同Frameの重複を含む。各軸は相関し、単独因果や追加条件の効果を証明しない。","要求票は実fillまで不変。費用後収支は保存実現値であり、追加gateを実行した成績ではない。","ownerから反転/順行等の元意図を推定しない。","Raw・退出後価格・未取得仮損益・15分当時値を追加しない。"]})
    print(json.dumps({"成功":True,"正本確認":review,"R文脈":context},ensure_ascii=False))


if __name__=="__main__":main()
