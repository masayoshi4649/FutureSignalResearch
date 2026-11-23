"""固定42A0対照と、現前CMF準備/変化/I-Oを保存値だけで対応診断する。"""

import argparse
from collections import Counter
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
STUDY=ROOT/"study/00043_再テスト時のCMF変化方向"
WORK=ROOT/"work/CMF変化/00043"
HELPER=ROOT/"scripts/構造判別/対応診断.py"
SPEC=importlib.util.spec_from_file_location("CMF変化43の固定保存集計",HELPER)
F=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=F;SPEC.loader.exec_module(F)
H,entry_summary=F.H,F.entry_summary
PERIODS=("学習","条件選択","後続検査")
POLICIES,ROLES=("D0","D1","D2"),("順行","反転")
CANDIDATES=tuple("3分_"+p+"_XF" for p in POLICIES)
PAIRS=(("現前CMF準備追加",CANDIDATES[0],CANDIDATES[1]),("CMF変化方向追加",CANDIDATES[1],CANDIDATES[2]))
PURE_FIELDS=("場","役割","side","方向","要求時計秒","要求原板行","確認遅延秒","low","high","atr","bb_mean")
LABEL_FIELDS=("ラベル","理由","新規価格","新規時計秒","新規原板行","判定時計秒","判定原板行","判定気配","最大順行pt","最大逆行pt","所要分")
META_FIELDS=("元登録ID","元価格side","元登録時計秒","元登録原板行","判別種別")
FILES=("発動判定.jsonl.gz","入口事例.jsonl.gz","全運用詳細.jsonl.gz","追尾.jsonl.gz")
EXACT_FIELDS=("CMF現","CMF前","CMF差","現加重CLV合計","前加重CLV合計","現観測量合計","前観測量合計","CMF差交差積","当足寄与I","窓脱落寄与O","現単位量CLV平均","前単位量CLV平均")


def fraction(value: dict) -> Fraction | None:
    """保存された有効性と精密分子分母を復元する。

    引数: value(dict)は精密欄。
    返り値: Fraction|Noneは分数又は未定義。表示値を採否に使わない。
    """
    return Fraction(value["分子"],value["分母"]) if value["有効"] else None


def exact(value: Fraction | None) -> dict:
    """内部算術の期待値を同じ保存規約へ写す。

    引数: value(Fraction|None)は保存分数由来の値。
    返り値: dictは値/分子/分母/有効。数値窓を再計算しない。
    """
    return {"値":float(value) if value is not None else None,"分子":value.numerator if value is not None else None,"分母":value.denominator if value is not None else None,"有効":value is not None}


def signed_group(value: Fraction | None, side: int | None) -> str:
    """実注文方向の正/0/負を分類する。

    引数: value(Fraction|None)は保存値、side(int|None)は実方向。
    返り値: strは符号分類。未準備を0へ変換しない。
    """
    if value is None or side not in (-1,1):return "未定義"
    return "正" if side*value > 0 else "負" if side*value < 0 else "0"


def analyze(cases: list[dict], decisions: list[dict], details: list[dict], old_cases: list[dict], old_decisions: list[dict], result: dict | None = None) -> dict:
    """旧A0対照・現前準備・変化/水準/I-O・実回収を保存値で分ける。

    引数: cases/decisions/details(list[dict])は43、old_cases/old_decisions(list[dict])は共有42、result(dict|None)は正式集計。
    返り値: dictは小型診断。原板/数値銀行/22足窓/先着/運用を起動しない。
    """
    errors,checks=[],0

    def check(label: str, actual: object, expected: object) -> None:
        """出典・集合・保存分数内部算術の一致を記録する。

        引数: label(str)は項目、actual/expected(object)は比較値。
        返り値: None。不一致を一覧へ追加する。
        """
        nonlocal checks
        checks+=1
        if actual != expected:errors.append({"項目":label,"実値":actual,"期待値":expected})

    raw_map={r["発動ID"]:r for r in decisions}
    old_raw={r["発動ID"]:r for r in old_decisions}
    old_a0={r["イベントID"]:r for r in old_cases if r["入口ID"] == "3分_A0"}
    old_a2={r["元価格発動ID"] for r in old_cases if r["入口ID"] == "3分_A2"}
    case_map={r["イベントID"]:r for r in cases}
    by_policy={p:{r["元価格発動ID"]:r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    check("全旧j保持",set(raw_map),set(old_raw))
    check("jID一意",len(raw_map),len(decisions))
    check("caseID一意",len(case_map),len(cases))
    check("D0旧全A0保持",{r["旧A0イベントID"] for r in by_policy["D0"].values()},set(old_a0))
    check("D1subsetD0",set(by_policy["D1"]) <= set(by_policy["D0"]),True)
    check("D2subsetD1",set(by_policy["D2"]) <= set(by_policy["D1"]),True)
    for row in decisions:
        origin=row["発動ID"];old=old_raw[origin];panel=row["CMF現前参照"];side=row["side"]
        check(origin+":旧jID",row["元42j発動ID"],origin)
        old_selected=old["戦略判定"]["A0"]["採用"]
        check(origin+":旧A0採否保持",row["旧A0採用"],old_selected)
        check(origin+":旧A0IDnullable",row["元42A0イベントID"],origin+"_A0" if old_selected else None)
        for field in ("場","index","side","役割","要求時計秒","要求原板行"):
            check(origin+":旧構造時計:"+field,row[field],old[field])
        check(origin+":当時panel出典",(panel["場"],panel["index"],panel["足出典"]["confirm"],panel["足出典"]["confirm_line"]),(row["場"],row["index"],row["要求時計秒"],row["要求原板行"]))
        for field in EXACT_FIELDS:
            check(origin+":精密欄:"+field,panel[field],exact(fraction(panel[field])))
        cur,prev=(fraction(panel[k]) for k in ("CMF現","CMF前"))
        nc,np,qc,qp=(fraction(panel[k]) for k in ("現加重CLV合計","前加重CLV合計","現観測量合計","前観測量合計"))
        for name,value,numerator,denominator,indices in (("現",cur,nc,qc,panel["現窓足番号"]),("前",prev,np,qp,panel["前窓足番号"])):
            wanted=numerator/denominator if len(indices) == 21 and denominator > 0 else None
            check(origin+name+":保存比",value,wanted)
        ready=cur is not None and prev is not None and len(panel["現窓足番号"]) == len(panel["前窓足番号"]) == 21
        check(origin+":現前準備",panel["CMF現前準備"],ready)
        delta,cross,inc,out=(fraction(panel[k]) for k in ("CMF差","CMF差交差積","当足寄与I","窓脱落寄与O"))
        if ready:
            check(origin+":共通20足",panel["現窓足番号"][:-1],panel["前窓足番号"][1:])
            check(origin+":現前隣接",panel["現窓足番号"][-1],panel["前窓足番号"][-1]+1)
            check(origin+":現在j",panel["現窓足番号"][-1],row["index"])
            incoming,outgoing=panel["入足参照"],panel["落足参照"]
            mn,mo,qn,qo=(fraction(v) for v in (incoming["CLV"],outgoing["CLV"],incoming["観測q"],outgoing["観測q"]))
            for label,source,index in (("入",incoming,row["index"]),("落",outgoing,panel["前窓足番号"][0])):
                check(origin+label+":場番号",(source["足出典"]["場"],source["足出典"]["index"]),(row["場"],index))
                check(origin+label+":公開asof",(source["足出典"]["confirm"],source["足出典"]["confirm_line"]) <= (row["要求時計秒"],row["要求原板行"]),True)
                check(origin+label+":q非負",fraction(source["観測q"]) >= 0,True)
            check(origin+":CMF直接差",delta,cur-prev)
            check(origin+":交差積",cross,nc*qp-np*qc)
            check(origin+":交差積差",delta,cross/(qc*qp))
            check(origin+":N入替え",nc,np+mn*qn-mo*qo)
            check(origin+":Q入替え",qc,qp+qn-qo)
            check(origin+":I",inc,qn*(mn-prev)/qc)
            check(origin+":O",out,-qo*(mo-prev)/qc)
            check(origin+":I+O",delta,inc+out)
            check(origin+":分解一致旗",panel["分解一致"],True)
        else:
            check(origin+":無効差寄与",[delta,cross,inc,out],[None]*4)
            check(origin+":無効出典",[panel["入足参照"],panel["落足参照"]],[None,None])
        sign=(delta > 0)-(delta < 0) if delta is not None else None
        check(origin+":精密差符号",panel["CMF差符号"],sign)
        for policy in POLICIES:
            accepted=old_selected and (policy == "D0" or ready) and (policy != "D2" or side*sign > 0)
            check(origin+policy+":採否",row["戦略判定"][policy]["採用"],accepted)
            check(origin+policy+":純集合",origin in by_policy[policy],accepted)
            if accepted:
                case=by_policy[policy][origin];old_case=old_a0[origin+"_A0"]
                check(origin+policy+":旧caseID",case["旧A0イベントID"],old_case["イベントID"])
                for field in (*PURE_FIELDS,*META_FIELDS,*LABEL_FIELDS,"期間"):
                    check(origin+policy+":旧同時計保持:"+field,case[field],old_case[field])

    # ----------------------------------------
    # 現前準備を揃えた水準/差と、同じ差の当足/脱落の機序を別の小表へ置く。
    stages,subsets,quadrants,overlaps,contributions,mechanisms=[],[],[],[],[],[]
    for period in PERIODS:
        raw=[r for r in decisions if r["期間"] == period]
        stages.append({"期間":period,"旧全j数":len(raw),"旧A0純数":sum(r["旧A0採用"] for r in raw),"全j現前準備数":sum(r["CMF現前参照"]["CMF現前準備"] for r in raw),**{p+"純入口数":sum(r["戦略判定"][p]["採用"] for r in raw) for p in POLICIES}})
        for role in ("全体",*ROLES):
            eligible=[r for r in raw if role == "全体" or r["役割"] == role]
            for title,left_id,right_id in PAIRS:
                lp,rp=left_id.split("_")[1],right_id.split("_")[1]
                left={r["発動ID"]:by_policy[lp][r["発動ID"]] for r in eligible if r["戦略判定"][lp]["採用"]}
                right={r["発動ID"]:by_policy[rp][r["発動ID"]] for r in eligible if r["戦略判定"][rp]["採用"]}
                removed=left.keys()-right.keys()
                subsets.append({"期間":period,"役割":role,"比較":title,"左入口":lp,"右入口":rp,"保持入口":entry_summary([left[k] for k in left.keys() & right.keys()]),"除外入口":entry_summary([left[k] for k in removed]),"新規追加入口数":len(right.keys()-left.keys()),
                    "現前準備除外理由_重複あり":dict(Counter(reason for k in removed for field in ("現前準備除外理由","CMF窓解除理由") for reason in raw_map[k]["CMF現前参照"].get(field,[]))) if lp == "D0" else {}})
            d1=[r for r in eligible if r["戦略判定"]["D1"]["採用"]]
            for level in ("正","0","負"):
                for change in ("正","0","負"):
                    own=[r for r in d1 if signed_group(fraction(r["CMF現前参照"]["CMF現"]),r["side"]) == level and signed_group(fraction(r["CMF現前参照"]["CMF差"]),r["side"]) == change]
                    quadrants.append({"期間":period,"役割":role,"分母":"同じ現前準備のD1純要求","実方向現水準":level,"実方向差":change,**entry_summary([by_policy["D1"][r["発動ID"]] for r in own])})
            for level_yes,change_yes,title in ((True,True,"両方正"),(True,False,"水準だけ正"),(False,True,"変化だけ正"),(False,False,"双方非正")):
                own=[r for r in d1 if (r["side"]*fraction(r["CMF現前参照"]["CMF現"]) > 0) == level_yes and r["戦略判定"]["D2"]["採用"] == change_yes]
                overlaps.append({"期間":period,"役割":role,"区分":title,"分母":"D1共通準備内のshadow",**entry_summary([by_policy["D1"][r["発動ID"]] for r in own])})
            level_origins={r["発動ID"] for r in d1 if r["side"]*fraction(r["CMF現前参照"]["CMF現"]) > 0}
            check(period+role+":共通準備内の旧水準群",level_origins,{r["発動ID"] for r in d1 if r["発動ID"] in old_a2})
            for isig in ("正","0","負"):
                for osig in ("正","0","負"):
                    own=[r for r in d1 if signed_group(fraction(r["CMF現前参照"]["当足寄与I"]),r["side"]) == isig and signed_group(fraction(r["CMF現前参照"]["窓脱落寄与O"]),r["side"]) == osig]
                    if own:
                        contributions.append({"期間":period,"役割":role,"実方向I":isig,"実方向O":osig,"実方向差別":dict(Counter(signed_group(fraction(r["CMF現前参照"]["CMF差"]),r["side"]) for r in own)),**entry_summary([by_policy["D1"][r["発動ID"]] for r in own])})
            mechanisms.append({"期間":period,"役割":role,"D1純要求数":len(d1),"D2純要求数":sum(r["戦略判定"]["D2"]["採用"] for r in d1),
                "当足q0数":sum(fraction(r["CMF現前参照"]["入足参照"]["観測q"]) == 0 for r in d1),"落足q0数":sum(fraction(r["CMF現前参照"]["落足参照"]["観測q"]) == 0 for r in d1),
                "I0数":sum(fraction(r["CMF現前参照"]["当足寄与I"]) == 0 for r in d1),"O0数":sum(fraction(r["CMF現前参照"]["窓脱落寄与O"]) == 0 for r in d1),
                "I0脱落だけ実方向改善数":sum(fraction(r["CMF現前参照"]["当足寄与I"]) == 0 and r["side"]*fraction(r["CMF現前参照"]["窓脱落寄与O"]) > 0 for r in d1)})

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
        "モデル再計算":False,"指標再計算":False,"先着再計算":False,"運用再生":False,"新閾値選別":False,"保存分数と差の算術照合":True,
        "新価格母集団":False,"旧42A0完全対照":True,"旧同時計先着を直接監査の代用にしない":True,
        "旧jと三入口":stages,"入口追加比較":subsets,"現水準と変化":quadrants,"水準と差の保持重複":overlaps,"IとOの寄与区分":contributions,"寄与機序":mechanisms,
        "実参加比較":participation,"役割別実参加比較":role_participation,"候補別回収":recovery,"役割別回収":role_recovery,"品質と確定額":qualities,
        "責任分界":{"固定42":"価格b/j/T-R/MACD/旧A0純245/旧同時計先着と全66運用追尾の完全対照","新43":"現前CMF/差/I-O/三採否・全新case直接先着/運用の独立proof","保存診断":"保存424j/現前NQとI-Oの内部算術/旧同時計対照/純subsetとactual差/会計だけ。22足窓や数値銀行を再計算しない"},
        "限界":["D0は固定42A0全保持。D1は22足両窓準備、D2は同時刻の変化符号。新h待機や水準/I正ANDは加えない。","水準対差は同じD1内のshadow比較。旧42A2全体や新水準戦略の運用効果ではない。","I/Oは前CMF基準と分母希釈を含む代数分解で、I正は当足CLV正や新買圧力を意味せず、Oは投資家退出でない。","純subsetでもactual追加が起こり得る。全差/平均/役割構成と共通出口/片側参加を別にする。","全66場既使用、未予約11/5Day未読。支持/70/費用を緩めず、仮250と実回収/名目床を混ぜない。"]}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式完了後に新四明細と共有旧42だけを一度読取診断する。

    引数: study/work(Path)は正式/作業先。
    返り値: dictは小型診断。root正式実行許可前は起動しない。
    """
    if not (study/"結果.json").is_file():raise ValueError("正式結果完成前に保存診断を実行しません")
    refs={name:H.read(study/name) for name in ("入口参照.json","対照参照.json","指標参照.json")}
    shared={name:{Path(r["パス"]).name:ROOT/r["パス"] for r in ref["共有明細"]} for name,ref in refs.items()}
    for ref in refs.values():
        for r in ref["共有明細"]:
            if H.sha(ROOT/r["パス"]) != r["圧縮SHA256参考"]:raise ValueError("共有明細参照版に差")
    old_cases,old_decisions=(H.read(shared["入口参照.json"][n]) for n in ("入口事例.jsonl.gz","発動判定.jsonl.gz"))
    decisions,cases,details,trace=(H.read(work/n) for n in FILES)
    output=analyze(cases,decisions,details,old_cases,old_decisions,H.read(study/"結果.json"))
    controls=H.read(study/"D0対照同値.json")
    new={d["場"]:d for d in details if d["候補ID"] == CANDIDATES[0]}
    old={d["場"]:d for d in H.read(shared["対照参照.json"]["全運用詳細.jsonl.gz"]) if d["候補ID"] == "3分_A0_XF"}
    old_trace=H.read(shared["対照参照.json"]["追尾.jsonl.gz"])
    control_rows={r["場"]:r for r in controls["照合"]}
    compare=[]
    for scene in sorted(new.keys() | old.keys()):
        adapted=F.rename(new.get(scene),"_D0","_A0")
        logs=[F.rename(r,"_D0","_A0") for r in trace if r["候補ID"] == CANDIDATES[0] and r["場"] == scene]
        previous=[r for r in old_trace if r["候補ID"] == "3分_A0_XF" and r["場"] == scene]
        verdict=adapted == old.get(scene) and logs == previous
        checks={"全運用":adapted == old.get(scene),"全追尾":logs == previous,
            "主対照運用hash":H.canonical(adapted) == control_rows[scene]["旧識別子全運用内容SHA256"],"主対照追尾hash":H.canonical(logs) == control_rows[scene]["旧識別子追尾内容SHA256"]}
        for label,okay in checks.items():
            output["照合項目数"]+=1
            if not okay:output["不一致"].append({"項目":scene+label,"実値":False,"期待値":True})
        compare.append({"場":scene,"全運用同値":checks["全運用"],"全追尾同値":checks["全追尾"],"主対照hash一致":checks["主対照運用hash"] and checks["主対照追尾hash"]})
    output["旧42A0全属性対照"]={"全件一致":all(r["全運用同値"] and r["全追尾同値"] and r["主対照hash一致"] for r in compare),"場候補数":len(compare),"照合":compare}
    output["不一致数"]=len(output["不一致"]);output["全件一致"]=not output["不一致"]
    paths=[Path(__file__),HELPER,ROOT/"scripts/量比反転/対応診断.py",ROOT/"scripts/終値位置/対応診断.py",ROOT/"scripts/SAR追尾/対応診断.py",
        *[study/n for n in ("条件.json","固定.json","結果.json","入力台帳.json","入口参照.json","対照参照.json","指標参照.json","D0対照同値.json")],work/"診断予定.json",*[work/n for n in FILES],*[p for v in shared.values() for p in v.values()]]
    output["全66場既使用"]=True
    output["ファイルSHA256"]={p.relative_to(ROOT).as_posix():H.sha(p) for p in dict.fromkeys(paths)}
    output["参照SHA256"]={n:H.sha(study/n) for n in ("結果.json","入口参照.json","対照参照.json","指標参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    if not output["全件一致"]:raise RuntimeError("CMF変化の保存対応に不一致")
    return output


def main() -> None:
    """保存明細だけの後段診断をCLIで起動する。

    引数: なし。--study/--workはPath。
    返り値: None。原相場/数値窓/先着/運用を起動しない。
    """
    parser=argparse.ArgumentParser(description="旧A0完全対照と現前CMF/差/I-Oの保存診断")
    parser.add_argument("--study",type=Path,default=STUDY);parser.add_argument("--work",type=Path,default=WORK)
    args=parser.parse_args();output=run(args.study.resolve(),args.work.resolve())
    print(H.json.dumps({k:output[k] for k in ("全件一致","照合項目数","不一致数")},ensure_ascii=False))


if __name__ == "__main__":main()
