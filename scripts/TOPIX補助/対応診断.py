"""保存TOPIX全足とNK判定だけから、準備/複合方向/時計/実回収を分ける。"""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
STUDY=ROOT/"study/00044_TOPIX方向とNK再テスト"
WORK=ROOT/"work/TOPIX補助/00044"
HELPER=ROOT/"scripts/構造判別/対応診断.py"
SPEC=importlib.util.spec_from_file_location("TOPIX44の固定保存集計",HELPER)
F=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=F;SPEC.loader.exec_module(F)
H,entry_summary=F.H,F.entry_summary
PERIODS=("学習","条件選択","後続検査")
POLICIES,ROLES=("X0","X1","X2"),("順行","反転")
CANDIDATES=tuple("3分_"+p+"_XF" for p in POLICIES)
PAIRS=(("TOPIX準備追加",CANDIDATES[0],CANDIDATES[1]),("TOPIX方向勢い追加",CANDIDATES[1],CANDIDATES[2]))
PURE_FIELDS=("場","役割","side","方向","要求時計秒","要求原板行","確認遅延秒","low","high","atr","bb_mean")
LABEL_FIELDS=("ラベル","理由","新規価格","新規時計秒","新規原板行","判定時計秒","判定原板行","判定気配","最大順行pt","最大逆行pt","所要分")
META_FIELDS=("元登録ID","元価格side","元登録時計秒","元登録原板行","判別種別")
FILES=("TOPIX全指標.jsonl.gz","発動判定.jsonl.gz","入口事例.jsonl.gz","全運用詳細.jsonl.gz","追尾.jsonl.gz")
NO_VISIBLE="TOPIX同終了strict事前公開参照なし"


def finite(value: object) -> bool:
    """保存された有限数値を判別する。

    引数: value(object)は保存値。
    返り値: boolは真偽値でない有限数値であること。
    """
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def fraction(value: dict) -> Fraction | None:
    """保存傾きの精密分子分母を復元する。

    引数: value(dict)は値/分子/分母/有効。
    返り値: Fraction|Noneは保存分数。OLS窓を新計算しない。
    """
    return Fraction(value["分子"],value["分母"]) if value["有効"] else None


def signed_group(value: Fraction | float | int | None, side: int | None) -> str:
    """実NK注文方向に対する補助値の正/0/負を分ける。

    引数: value(Fraction|float|int|None)は保存TOPIX値、side(int|None)はNK実方向。
    返り値: strは符号。未準備を0へ補完しない。
    """
    if value is None or side not in (-1,1):return "未定義"
    return "正" if side*value > 0 else "負" if side*value < 0 else "0"


def clock_group(rows: list[dict], now: float) -> str:
    """全保存TOPIXを見た事後時計区分だけを返す。

    引数: rows(list[dict])は同場/同終了の全保存足、now(float)はNK要求時計。
    返り値: strは診断専用区分。live採否/理由や参照値へ使用しない。
    """
    if not rows:return "未収録"
    if len(rows) != 1:return "同終了複数"
    row=rows[0]
    if not row["publish"]:return "NP・非公開"
    if row["confirm"] == now:return "同秒・strict不可"
    if row["confirm"] > now:return "後公開"
    return "strict事前公開"


def analyze(cases: list[dict], decisions: list[dict], details: list[dict], topix: list[dict], result: dict | None = None) -> dict:
    """保存五系列から、当時可視性と事後時計区分・実参加を分離する。

    引数: cases/decisions/details/topix(list[dict])は保存値、result(dict|None)は正式集計。
    返り値: dictは小型診断。原板・TOPIX OLS/MACD・NK監視・先着・運用は再計算しない。
    """
    errors,checks=[],0

    def check(label: str, actual: object, expected: object) -> None:
        """保存出典/集合/内部差の整合を一項目記録する。

        引数: label(str)は項目、actual/expected(object)は比較値。
        返り値: None。不一致を一覧へ記録する。
        """
        nonlocal checks
        checks+=1
        if actual != expected:errors.append({"項目":label,"実値":actual,"期待値":expected})

    raw_map={r["発動ID"]:r for r in decisions}
    case_map={r["イベントID"]:r for r in cases}
    by_policy={p:{r["元価格発動ID"]:r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    aux_by_index={(r["場"],r["index"]):{k:v for k,v in r.items() if k != "期間"} for r in topix}
    aux_by_end=defaultdict(list)
    for row in topix:aux_by_end[row["場"],row["end"]].append(row)
    check("全j一意",len(raw_map),len(decisions))
    check("case一意",len(case_map),len(cases))
    check("TOPIX場足一意",len(aux_by_index),len(topix))
    check("X1subsetX0",set(by_policy["X1"]) <= set(by_policy["X0"]),True)
    check("X2subsetX1",set(by_policy["X2"]) <= set(by_policy["X1"]),True)
    clock_rows=[]
    for row in decisions:
        origin,now,side=row["発動ID"],row["要求時計秒"],row["side"]
        same_end=aux_by_end[row["場"],row["足終了時計秒"]]
        visible=[r for r in same_end if r["publish"] and r["confirm"] < now]
        check(origin+":strict可視一意",len(visible) <= 1,True)
        upper=row["補助参照"]
        check(origin+":元jID",row["元42j発動ID"],origin)
        check(origin+":旧A0ID",row["元42A0イベントID"],origin+"_A0" if row["旧A0採用"] else None)
        check(origin+":可視None保持",upper is None,not visible)
        reasons=[]
        if not row["商品照合"]:reasons.append("NKとTOPIXの限月年月不一致")
        if upper is None:
            reasons.append(NO_VISIBLE)
        else:
            source=upper["足出典"]
            check(origin+":保存TOPIX出典",source,aux_by_index[row["場"],source["index"]])
            check(origin+":同終了",source["end"],row["足終了時計秒"])
            check(origin+":事前strict",source["confirm"] < now,True)
            check(origin+":窓公開asof",upper["窓最遅公開key"] is None or upper["窓最遅公開key"][0] < now,True)
            prior=upper["前足出典"]
            if prior is not None:
                check(origin+":前TOPIX出典",prior,aux_by_index[row["場"],source["index"]-1])
                check(origin+":前公開asof",prior["confirm"] < now,True)
            check(origin+":現ヒスト保持",upper["MACDヒスト現"],source["macd_hist"])
            check(origin+":前ヒスト保持",upper["MACDヒスト前"],prior["macd_hist"] if prior else None)
            delta=source["macd_hist"]-prior["macd_hist"] if prior is not None and finite(source["macd_hist"]) and finite(prior["macd_hist"]) else None
            check(origin+":保存ヒスト差内部算術",upper["MACDヒスト変化"],delta)
            slope=fraction(upper["OLS20傾き"])
            check(origin+":傾き符号",upper["OLS20傾き符号"],(slope > 0)-(slope < 0) if slope is not None else None)
            if upper["補助数値準備"]:
                check(origin+":OLS20本",len(upper["OLS20窓足番号"]),20)
                check(origin+":OLS現在含む",upper["OLS20窓足番号"][-1],source["index"])
            reasons.extend(upper["補助準備除外理由"])
        check(origin+":準備理由",row["準備除外理由"],reasons)
        ready=not reasons
        check(origin+":補助準備",row["補助準備"],ready)
        check(origin+":NK確認遅延非負",now >= row["足終了時計秒"],True)
        if now == row["足終了時計秒"]:check(origin+":NK遅延0は構造上不可",ready,False)
        direction=ready and side in (-1,1) and side*upper["OLS20傾き符号"] > 0 and side*upper["MACDヒスト変化"] > 0
        for policy in POLICIES:
            accepted=row["旧A0採用"] and (policy == "X0" or ready) and (policy != "X2" or bool(direction))
            check(origin+policy+":採否",row["戦略判定"][policy]["採用"],accepted)
            check(origin+policy+":純集合",origin in by_policy[policy],accepted)
            if accepted:
                case,base=by_policy[policy][origin],by_policy["X0"][origin]
                for field in (*PURE_FIELDS,*META_FIELDS,*LABEL_FIELDS,"期間","旧A0イベントID"):
                    check(origin+policy+":同j保持:"+field,case[field],base[field])
                check(origin+policy+":旧ID対応",case["旧A0イベントID"],origin+"_A0")
                check(origin+policy+":j要求",(case["要求時計秒"],case["要求原板行"]),(now,row["要求原板行"]))
        # この区分は全保存入力を知った後の診断だけ。row/liveへ書き戻さない。
        clock_rows.append({"期間":row["期間"],"役割":row["役割"],"日夜":"デイ" if row["場"].endswith("_Day") else "ナイト","発動ID":origin,"旧A0採用":row["旧A0採用"],"NK遅延秒":now-row["足終了時計秒"],"事後時計区分":clock_group(same_end,now)})

    # ----------------------------------------
    # 全j/旧純245と、準備/値/日夜/役割/時計による構成差を別分母にする。
    stages,subsets,shadows,clocks,composition=[],[],[],[],[]
    for period in PERIODS:
        raw=[r for r in decisions if r["期間"] == period]
        stages.append({"期間":period,"旧全j数":len(raw),"旧A0純数":sum(r["旧A0採用"] for r in raw),"旧A0_NK遅延0数":sum(r["旧A0採用"] and r["要求時計秒"] == r["足終了時計秒"] for r in raw),"時計だけのX1登録上限":sum(r["旧A0採用"] and r["要求時計秒"] > r["足終了時計秒"] for r in raw),"全jstrict可視数":sum(r["補助参照"] is not None for r in raw),"全j補助準備数":sum(r["補助準備"] for r in raw),**{p+"純入口数":sum(r["戦略判定"][p]["採用"] for r in raw) for p in POLICIES}})
        for role in ("全体",*ROLES):
            eligible=[r for r in raw if role == "全体" or r["役割"] == role]
            for title,left_id,right_id in PAIRS:
                lp,rp=left_id.split("_")[1],right_id.split("_")[1]
                left={r["発動ID"]:by_policy[lp][r["発動ID"]] for r in eligible if r["戦略判定"][lp]["採用"]}
                right={r["発動ID"]:by_policy[rp][r["発動ID"]] for r in eligible if r["戦略判定"][rp]["採用"]}
                subsets.append({"期間":period,"役割":role,"比較":title,"左入口":lp,"右入口":rp,"保持入口":entry_summary([left[k] for k in left.keys() & right.keys()]),"除外入口":entry_summary([left[k] for k in left.keys()-right.keys()]),"新規追加入口数":len(right.keys()-left.keys()),"準備除外理由_重複あり":dict(Counter(v for k in left.keys()-right.keys() for v in raw_map[k]["準備除外理由"])) if lp == "X0" else {}})
            x1=[r for r in eligible if r["戦略判定"]["X1"]["採用"]]
            for slope_sign in ("正","0","負"):
                for momentum_sign in ("正","0","負"):
                    own=[r for r in x1 if signed_group(fraction(r["補助参照"]["OLS20傾き"]),r["side"]) == slope_sign and signed_group(r["補助参照"]["MACDヒスト変化"],r["side"]) == momentum_sign]
                    shadows.append({"期間":period,"役割":role,"分母":"同じX1準備のshadow","実方向TOPIX傾き":slope_sign,"実方向TOPIXヒスト差":momentum_sign,**entry_summary([by_policy["X1"][r["発動ID"]] for r in own])})
            local_clocks=[r for r in clock_rows if r["期間"] == period and (role == "全体" or r["役割"] == role)]
            for category in ("未収録","NP・非公開","同秒・strict不可","後公開","strict事前公開","同終了複数"):
                own=[r for r in local_clocks if r["事後時計区分"] == category]
                ids=[r["発動ID"] for r in own if r["旧A0採用"]]
                clocks.append({"期間":period,"役割":role,"用途":"事後時計診断専用・live理由でない","事後時計区分":category,"全j数":len(own),"NK遅延0の全j数":sum(r["NK遅延秒"] == 0 for r in own),**entry_summary([by_policy["X0"][k] for k in ids])})
            for daynight in ("デイ","ナイト"):
                for delay_kind in ("0秒","正の遅延"):
                    own=[r for r in eligible if r["旧A0採用"] and ("デイ" if r["場"].endswith("_Day") else "ナイト") == daynight and ((r["要求時計秒"] == r["足終了時計秒"]) == (delay_kind == "0秒"))]
                    composition.append({"期間":period,"役割":role,"日夜":daynight,"NK確認遅延":delay_kind,"X0純要求数":len(own),"X1純要求数":sum(r["戦略判定"]["X1"]["採用"] for r in own),"X2純要求数":sum(r["戦略判定"]["X2"]["採用"] for r in own),"X0先着":entry_summary([by_policy["X0"][r["発動ID"]] for r in own])})

    # ----------------------------------------
    # 同じ実新規だけの出口差と、pending/保有占有が変えた片側参加を分ける。
    trades = [{**t,"候補ID":d["候補ID"]} for d in details for t in d["取引"]]
    handling = {(d["候補ID"],s["イベントID"]):s["取扱"] for d in details for s in d["入口取扱"]}
    for trade in trades:
        case = case_map[trade["入口イベントID"]]
        for field in ("新規時計秒","新規原板行","新規価格"):
            check("実新規と保存case:"+field,trade[field],case[field])
        check("実役割保持",trade["入口役割"],case["役割"])
        check("入口jATR保持",trade["入口ATR"],case["atr"])
    participation, role_participation, recovery, role_recovery, qualities = [], [], [], [], []
    for period in PERIODS:
        for role in ("全体", *ROLES):
            own = {cid:[t for t in trades if t["候補ID"] == cid and t["期間"] == period and (role == "全体" or t["入口役割"] == role)] for cid in CANDIDATES}
            for cid in CANDIDATES:
                check(cid+period+role+":厳密実新規一意",len({F.strict_identity(t) for t in own[cid]}),len(own[cid]))
            for title,left_id,right_id in PAIRS:
                left,right = ({F.strict_identity(t):t for t in own[cid]} for cid in (left_id,right_id))
                common,removed,added = left.keys() & right.keys(),left.keys()-right.keys(),right.keys()-left.keys()
                costs=[]
                for fee in (0,5,10):
                    field=f"追加滑り{fee}pt純損益円"
                    diff=sum(right[k][field]-left[k][field] for k in common)
                    total=H.cash(own[right_id],fee)-H.cash(own[left_id],fee)
                    removed_cash,added_cash=H.cash([left[k] for k in removed],fee),H.cash([right[k] for k in added],fee)
                    check(title+period+role+str(fee)+":全差分解",total,diff-removed_cash+added_cash)
                    check(title+period+role+str(fee)+":共通XF差0",diff,0)
                    costs.append({"片道追加pt":fee,"総差円_右引く左":total,"共通出口差円":diff,"左のみ損益円":removed_cash,"右のみ損益円":added_cash})

                def counterpart(rows: list[dict], cid: str) -> dict:
                    """片側実参加の相手を、純除外と実占有抑止へ分ける。

                    引数: rows(list[dict])は片側完結、cid(str)は相手候補。
                    返り値: dictは保存取扱別件数。後の空き時計へ延期しない。
                    """
                    policy=cid.split("_")[1]
                    records=[]
                    for trade in rows:
                        origin=case_map[trade["入口イベントID"]]["元価格発動ID"]
                        other=by_policy[policy].get(origin)
                        records.append("同j純入口なし" if other is None else handling.get((cid,other["イベントID"]),"取扱記録なし"))
                    return dict(Counter(records))

                exit_diff=sum(any(left[k][f] != right[k][f] for f in ("返済時計秒","返済原板行","返済価格","返済理由")) for k in common)
                check(title+period+role+":共通出口属性",exit_diff,0)
                item={"期間":period,"役割":role,"比較":title,"左":left_id,"右":right_id,"厳密共通実新規数":len(common),"共通出口属性差数":exit_diff,
                    "同j両実参加数":len({case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[left_id]} & {case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[right_id]}),
                    "左のみ":H.operation_summary([left[k] for k in removed]),"右のみ":H.operation_summary([right[k] for k in added]),
                    "左のみの相手取扱":counterpart([left[k] for k in removed],right_id),"右のみの相手取扱":counterpart([right[k] for k in added],left_id),"費用別":costs}
                (participation if role == "全体" else role_participation).append(item)
            for cid in CANDIDATES:
                rows=own[cid]
                successes=[t for t in rows if case_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
                armed=[t for t in rows if t["追尾起動"]]
                reds=[t for t in armed if t["起動後純赤字"]]
                nominal=lambda t:(1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"])
                item={"候補ID":cid,"期間":period,"役割":role,**H.operation_summary(rows),"対応仮250数":len(successes),
                    "仮250判定前返済数":sum((t["返済時計秒"],t["返済原板行"]) < (case_map[t["入口イベントID"]]["判定時計秒"],case_map[t["入口イベントID"]]["判定原板行"]) for t in successes),
                    "実保有MFE250数":sum(t["観測最大順行pt"] >= 250 for t in rows),"起動数":len(armed),"起動後基準赤字数":len(reds),
                    "名目同値費用赤字数":sum(nominal(t) == 0 for t in reds),"不利返済赤字数":sum(nominal(t) < 0 for t in reds),"正名目利益の基準費用負け数":sum(nominal(t) > 0 for t in reds)}
                (recovery if role == "全体" else role_recovery).append(item)
    if result is not None:
        check("三運用順",[r["候補ID"] for r in result["結果"]],list(CANDIDATES))
        check("六実役割群",[(r["入口ID"],r["役割"]) for r in result["役割別入口評価"]],[("3分_"+p,role) for p in POLICIES for role in ROLES])
        for source in (*result["入口評価"],*result["役割別入口評価"]):
            for period in PERIODS:
                own=[r for r in cases if r["入口ID"] == source["入口ID"] and r["期間"] == period and (source["役割"] == "切替" or r["役割"] == source["役割"])]
                summary=entry_summary(own)
                for field in ("候補数","約定候補数","順行先着","逆行先着","期限未達","観測不足","未約定","確認率"):
                    check(source["入口ID"]+source["役割"]+period+field,source[period][field],summary[field])
        for row in result["結果"]:
            for period in PERIODS:
                op=row[period]["運用"]
                own=[t for t in trades if t["候補ID"] == row["候補ID"] and t["期間"] == period]
                check(row["候補ID"]+period+":完結",op["完結取引数"],len(own))
                for fee in (0,5,10):
                    check(row["候補ID"]+period+str(fee)+":会計",op[f"追加{fee}pt純損益円"],H.cash(own,fee))
                qualities.append({"候補ID":row["候補ID"],"期間":period,**{k:op[k] for k in ("品質注意場数","未解消場数","EOF期限未達場数")},"観測純額円":{str(f):op[f"追加{f}pt純損益円"] for f in (0,5,10)},"全体確定対象円":{str(f):op[f"追加{f}pt確定対象円"] for f in (0,5,10)}})
    return {"全件一致":not errors,"照合項目数":checks,"不一致数":len(errors),"不一致":errors,
        "モデル再計算":False,"指標再計算":False,"先着再計算":False,"運用再生":False,"新閾値選別":False,"保存ヒスト差と精密欄の内部照合":True,
        "新価格母集団":False,"初TOPIX結合を未知データ実証としない":True,"当時不可の一理由":NO_VISIBLE,
        "旧jと三入口":stages,"入口追加比較":subsets,"X1内の傾きと勢い":shadows,"事後時計診断専用":clocks,"準備の日夜役割遅延構成":composition,
        "実参加比較":participation,"役割別実参加比較":role_participation,"候補別回収":recovery,"役割別回収":role_recovery,"品質と確定額":qualities,
        "責任分界":{"旧42/43":"NK原数値/母監視/純基準の独立証明を共有。X0の旧完全対照は主/状態/財務proofへ接続","新44":"TOPIX数値/OLS/跨時点/限月/三採否・新caseNK直接先着と全会計/追尾は主独立proof","保存診断":"新5gzipの出典/当時strict参照/事後時計専用区分/内部差と集合/回収だけ。原板/OLS窓/ヒスト/母監視を再計算しない"},
        "限界":["TOPIX/NKのlineを跨いで比較しない。同秒/後公開/NP等は事後時計診断で、live理由へ戻さない。","NK確認遅延0は同終了かつTOPIX確認>=endとstrict事前公開から構造上準備不可。準備は時計/活動/役割選別も含む。","X1内の傾き×ヒスト差は複合条件のshadow。別運用/新閾値/相関係数/NT倍率/価格リターン/CMFではない。","全NK66は既使用。初TOPIX結合は未知データ実証や実WebSocket受信先行の証明ではない。","純subsetと実参加、共通出口と片側額、仮250と実保有MFE/回収/名目床を分ける。"]}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式許可後に保存五系列と小型正本だけを一度診断する。

    引数: study/work(Path)は44正式/作業先。
    返り値: dictは小型診断。主/独立/原板/数値窓/先着/運用は起動しない。
    """
    if not (study/"結果.json").is_file():raise ValueError("正式結果完成前に保存診断を実行しません")
    topix,decisions,cases,details,_=(H.read(work/n) for n in FILES)
    output=analyze(cases,decisions,details,topix,H.read(study/"結果.json"))
    control=H.read(study/"X0対照同値.json")
    for field,expected in (("全件一致",True),("旧先着全件同値",True),("場候補数",66)):
        output["照合項目数"]+=1
        if control[field] != expected:output["不一致"].append({"項目":"X0旧対照:"+field,"実値":control[field],"期待値":expected})
    output["X0旧完全対照証明"]={"パス":(study/"X0対照同値.json").relative_to(ROOT).as_posix(),"SHA256":H.sha(study/"X0対照同値.json"),"全件一致":control["全件一致"],"場候補数":control["場候補数"]}
    output["不一致数"]=len(output["不一致"]);output["全件一致"]=not output["不一致"]
    paths=[Path(__file__),HELPER,ROOT/"scripts/量比反転/対応診断.py",ROOT/"scripts/終値位置/対応診断.py",ROOT/"scripts/SAR追尾/対応診断.py",
        *[study/n for n in ("条件.json","固定.json","結果.json","入力台帳.json","入口参照.json","対照参照.json","指標参照.json","TOPIX入力参照.json","X0対照同値.json")],work/"診断予定.json",*[work/n for n in FILES]]
    ref=H.read(study/"TOPIX入力参照.json")
    paths.extend(ROOT/ref[n]["パス"] for n in ("入力台帳","入力監査","入力予約"))
    output["全NK66場既使用"]=True
    output["ファイルSHA256"]={p.relative_to(ROOT).as_posix():H.sha(p) for p in dict.fromkeys(paths)}
    output["参照SHA256"]={n:H.sha(study/n) for n in ("結果.json","入口参照.json","対照参照.json","指標参照.json","TOPIX入力参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    if not output["全件一致"]:raise RuntimeError("TOPIX補助の保存対応に不一致")
    return output


def main() -> None:
    """root又は担当の一方による正式後一回の保存診断を起動する。

    引数: なし。--study/--workはPath。
    返り値: None。実行許可前は起動しない。
    """
    parser=argparse.ArgumentParser(description="TOPIX同終了参照/準備と複合方向/事後時計の保存診断")
    parser.add_argument("--study",type=Path,default=STUDY);parser.add_argument("--work",type=Path,default=WORK)
    args=parser.parse_args();output=run(args.study.resolve(),args.work.resolve())
    print(H.json.dumps({k:output[k] for k in ("全件一致","照合項目数","不一致数")},ensure_ascii=False))


if __name__ == "__main__":main()
