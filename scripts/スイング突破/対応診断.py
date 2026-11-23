"""新スイングの保存状態・Fast選別・実参加と回収を分けて記録する。"""

import argparse
from collections import Counter,defaultdict
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
STUDY=ROOT/"study/00045_確定スイング突破と方向優勢"
WORK=ROOT/"work/スイング突破/00045"
HELPER=ROOT/"scripts/構造判別/対応診断.py"
SPEC=importlib.util.spec_from_file_location("スイング45の固定保存集計",HELPER)
F=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=F;SPEC.loader.exec_module(F)
H,entry_summary=F.H,F.entry_summary
PERIODS=("学習","条件選択","後続検査")
POLICIES,ROLES=("C0","C1","C2"),("順行","反転")
CANDIDATES=tuple("3分_"+p+"_XF" for p in POLICIES)
PAIRS=(("Fast準備追加",CANDIDATES[0],CANDIDATES[1]),("Fast値追加",CANDIDATES[1],CANDIDATES[2]))
PURE_FIELDS=("場","役割","side","方向","要求時計秒","要求原板行","確認遅延秒","low","high","atr","bb_mean")
LABEL_FIELDS=("ラベル","理由","新規価格","新規時計秒","新規原板行","判定時計秒","判定原板行","判定気配","最大順行pt","最大逆行pt","所要分")
META_FIELDS=("元価格side","判別種別","突破極値ID","構造方向","元極値中心番号")
SOURCE_FIELDS=("場","index","minutes","start","end","confirm","confirm_line","publish","missing","open","high","low","close")
FILES=("全指標.jsonl.gz","価格状態.jsonl.gz","発動判定.jsonl.gz","入口事例.jsonl.gz","全運用詳細.jsonl.gz","追尾.jsonl.gz")


def finite(value: object) -> bool:
    """保存値の有限性を判別する。

    引数: value(object)は保存値。
    返り値: boolは真偽値を除く有限実数であること。
    """
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def fraction(value: dict) -> Fraction | None:
    """保存された精密Fast値だけを復元する。

    引数: value(dict)は有効/分子/分母。
    返り値: Fraction|Noneは保存値。OHLC窓を新計算しない。
    """
    return Fraction(value["分子"],value["分母"]) if value["有効"] else None


def value_group(row: dict) -> str:
    """実方向の精密Fast差と未準備を分離する。

    引数: row(dict)は保存原P。
    返り値: strは未準備/正/0/負。
    """
    if not row["Fast準備"]:return "未準備"
    number=row["side"]*row["Fast差厳密符号"]
    return "正" if number > 0 else "負" if number < 0 else "0"


def readiness_group(row: dict) -> str:
    """Fastの保存窓本数と定義状態だけから除外を分ける。

    引数: row(dict)は保存原P。
    返り値: strは準備/14窓不足/生K未定義/K3不足。零幅を勝手に0へ補完しない。
    """
    if row["Fast準備"]:return "準備済み"
    if len(row["Fast価格窓足番号"]) < 14:return "当場14価格窓不足"
    if not row["FastK"]["有効"]:return "生K未定義"
    return "連続K3未準備"


def analyze(cases: list[dict], decisions: list[dict], price: list[dict], numeric: list[dict], details: list[dict], result: dict | None = None) -> dict:
    """保存六系列から価格機械・準備・値・実占有/回収を分離する。

    引数: cases/decisions/price/numeric/details(list[dict])は正式保存値、result(dict|None)は結果。
    返り値: dictは小型記述診断。原OHLCからの極値/DI/Fast/先着/運用は再計算しない。
    """
    errors,checks=[],0

    def check(label: str, actual: object, expected: object) -> None:
        """出典・参照・内部算術の一致を記録する。

        引数: label(str)は項目、actual/expected(object)は保存比較値。
        返り値: None。不一致だけ小型一覧へ保存する。
        """
        nonlocal checks
        checks+=1
        if actual != expected:errors.append({"項目":label,"実値":actual,"期待値":expected})

    raw_map={r["発動ID"]:r for r in decisions}
    case_map={r["イベントID"]:r for r in cases}
    by_policy={p:{r["元価格発動ID"]:r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    frames={(r["場"],r["index"]):r for r in numeric}
    pivots={r["極値ID"]:r for r in price if r["種別"] == "極値"}
    monitors=[r for r in price if r["種別"] == "監視"]
    check("新P一意",len(raw_map),len(decisions));check("case一意",len(case_map),len(cases))
    check("全足一意",len(frames),len(numeric));check("全監視一意",len({(r["場"],r["index"]) for r in monitors}),len(monitors))
    check("全足全監視対応",set(frames),{(r["場"],r["index"]) for r in monitors})
    check("極値一回保存",len(pivots),sum(r["種別"] == "極値" for r in price))
    check("C1subsetC0",set(by_policy["C1"]) <= set(by_policy["C0"]),True)
    check("C2subsetC1",set(by_policy["C2"]) <= set(by_policy["C1"]),True)
    for pid,point in pivots.items():
        center,current=point["中心出典"],point["確認出典"]
        check(pid+":右2確認",point["確認足番号"],point["中心番号"]+2)
        check(pid+":五足番号",point["五足番号"],list(range(point["中心番号"]-2,point["確認足番号"]+1)))
        for title,source in (("中心",center),("確認",current)):
            check(pid+title+":数値出典",source,{k:frames[point["場"],source["index"]][k] for k in SOURCE_FIELDS})
        check(pid+":価格",point["極値価格"],center["high"] if point["極値side"] == 1 else center["low"])
    consumption,registers=Counter(),Counter()
    stage_rows=[]
    for scene in sorted({r["場"] for r in monitors}):
        local=[r for r in monitors if r["場"] == scene]
        used=set();last=None
        for row in local:
            key=scene,row["index"];frame=frames[key]
            if last is not None:check(str(key)+":前後snapshot",row["監視前"],last)
            check(str(key)+":消費前数",row["監視前"]["使用済み数"],len(used))
            check(str(key)+":公開key",row["公開key"],[frame["confirm"],frame["confirm_line"]])
            check(str(key)+":足終了",row["足終了時計秒"],frame["end"])
            new_pivot_seen=False
            for action in row["動作"]:
                name=action["動作"]
                if name == "局所解除":used.clear()
                if name == "極値確定":
                    new_pivot_seen=True;pid=action["極値ID"];registers[pid]+=1
                    check(pid+":登録時計",pivots[pid]["確認足番号"],row["index"])
                if name in ("初回cross消費","使用済みcross見送り"):
                    check(str(key)+":新pivotより先に判断",new_pivot_seen,False)
                    marker=action["side"],action["極値ID"]
                    check(str(key)+name+":既消費",marker in used,name == "使用済みcross見送り")
                    if name == "初回cross消費":
                        used.add(marker);consumption[action["発動ID"]]+=1
                        raw=raw_map[action["発動ID"]]
                        check(action["発動ID"]+":消費の水準",(raw["side"],raw["突破極値ID"]),marker)
                        check(action["発動ID"]+":消費の足",raw["index"],row["index"])
            check(str(key)+":消費後数",row["監視後"]["使用済み数"],len(used))
            for state in ("監視前","監視後"):
                for field in ("高値ID","安値ID"):
                    check(str(key)+state+field+":最大2",len(row[state][field]) <= 2,True)
                    for pid in row[state][field]:
                        check(str(key)+state+pid+":出生時点",pivots[pid]["確認足番号"] < row["index"] if state == "監視前" else pivots[pid]["確認足番号"] <= row["index"],True)
            last=row["監視後"]
        period=local[0]["期間"]
        actions=Counter(a["動作"] for r in local for a in r["動作"])
        stage_rows.append({"期間":period,"場":scene,"数値足数":len(local),"極値数":sum(p["場"] == scene for p in pivots.values()),"動作別":dict(actions),"原P数":sum(r["場"] == scene for r in decisions)})
    check("全P一回消費",dict(consumption),{k:1 for k in raw_map})
    check("全極値一回登録",dict(registers),{k:1 for k in pivots})
    for origin,row in raw_map.items():
        frame=frames[row["場"],row["index"]]
        point=pivots[row["突破極値ID"]];prior=row["前3分参照"]
        for field,value in frame.items():
            if field != "期間":check(origin+":数値コピー:"+field,row[field],value)
        check(origin+":前出典",prior,{k:frames[row["場"],prior["index"]][k] for k in (*SOURCE_FIELDS,"atr")})
        check(origin+":相邻足",prior["index"]+1,row["index"])
        check(origin+":判断時点",row["end"] > prior["confirm"] and (row["confirm"],row["confirm_line"]) > (prior["confirm"],prior["confirm_line"]),True)
        check(origin+":生誕同足利用なし",point["確認足番号"] < row["index"] and (point["確認出典"]["confirm"],point["確認出典"]["confirm_line"]) <= (prior["confirm"],prior["confirm_line"]),True)
        highs=[pivots[k] for k in row["構造参照"]["高値ID"]];lows=[pivots[k] for k in row["構造参照"]["安値ID"]]
        ready=len(highs) == len(lows) == 2
        direction=None if not ready else 1 if highs[1]["極値価格"] > highs[0]["極値価格"] and lows[1]["極値価格"] > lows[0]["極値価格"] else -1 if highs[1]["極値価格"] < highs[0]["極値価格"] and lows[1]["極値価格"] < lows[0]["極値価格"] else 0
        check(origin+":構造準備",row["構造準備"],ready);check(origin+":保存構造内部算術",row["構造方向"],direction)
        side=row["side"];latest=(highs if side == 1 else lows)[-1]
        check(origin+":最新水準",row["突破極値ID"],latest["極値ID"])
        level=point["極値価格"]
        check(origin+":strict終値cross",prior["close"] <= level < row["close"] if side == 1 else prior["close"] >= level > row["close"],True)
        check(origin+":元価格方向",row["元価格side"],side)
        check(origin+":中心ID参照",row["元極値中心番号"],point["中心番号"])
        check(origin+":突破価格",row["突破価格"],level)
        check(origin+":共通M理由",row["共通M準備"],not row["M除外理由"])
        role="順行" if direction == side else "反転" if direction == -side else None
        check(origin+":実役割",row["役割"],role);check(origin+":T/R/WAIT",row["判別種別"],"T" if role == "順行" else "R" if role == "反転" else "WAIT")
        di=row["plus_di"]-row["minus_di"] if finite(row["plus_di"]) and finite(row["minus_di"]) else None
        check(origin+":保存DI差",row["DI差"],di);check(origin+":DI符号",row["DI優勢符号"],(di > 0)-(di < 0) if di is not None else None)
        raw,smooth,diff=(fraction(row[k]) for k in ("FastK","FastD","Fast差"))
        check(origin+":保存Fast内部算術",diff,raw-smooth if raw is not None and smooth is not None else None)
        check(origin+":Fast精密符号",row["Fast差厳密符号"],(diff > 0)-(diff < 0) if diff is not None else None)
        for policy in POLICIES:
            accepted=bool(row["共通M準備"] and row["時間条件可"] and row["確認遅延条件可"] and direction in (-1,1) and di is not None and side*di > 0 and (policy == "C0" or row["Fast準備"]) and (policy != "C2" or diff is not None and side*diff > 0) and not row["戦略判定"][policy]["同時競合"])
            check(origin+policy+":採否",row["戦略判定"][policy]["採用"],accepted);check(origin+policy+":純集合",origin in by_policy[policy],accepted)
            if accepted:
                own,base=by_policy[policy][origin],by_policy["C0"][origin]
                for field in (*PURE_FIELDS,*META_FIELDS,*LABEL_FIELDS,"期間"):
                    check(origin+policy+":同P属性:"+field,own[field],base[field])
                for field in (*META_FIELDS,"atr","役割","side","要求時計秒","要求原板行"):
                    check(origin+policy+":元判断:"+field,own[field],row[field])

    # ----------------------------------------
    # 新PとFast準備・値、構造役割・日夜・水準の古さを別分母で記述する。
    stages,subsets,fast_groups,composition,ages=[],[],[],[],[]
    for period in PERIODS:
        local=[r for r in stage_rows if r["期間"] == period]
        actions=Counter()
        for r in local:actions.update(r["動作別"])
        raw=[r for r in decisions if r["期間"] == period]
        stages.append({"期間":period,"数値足数":sum(r["数値足数"] for r in local),"極値数":sum(r["極値数"] for r in local),"動作別":dict(actions),"原P数":len(raw),"C0C1原P集合同値":{r["発動ID"] for r in raw if r["戦略判定"]["C0"]["採用"]} == {r["発動ID"] for r in raw if r["戦略判定"]["C1"]["採用"]},"構造別":dict(Counter(r["判別種別"] for r in raw)),"構造準備なし":sum(not r["構造準備"] for r in raw),"先着対象外P数":sum(not r["先着評価対象"] for r in raw),**{p+"純入口数":sum(r["戦略判定"][p]["採用"] for r in raw) for p in POLICIES}})
        for role in ("全体",*ROLES):
            eligible=[r for r in raw if role == "全体" or r["役割"] == role]
            for title,left_id,right_id in PAIRS:
                lp,rp=left_id.split("_")[1],right_id.split("_")[1]
                left={r["発動ID"]:by_policy[lp][r["発動ID"]] for r in eligible if r["戦略判定"][lp]["採用"]}
                right={r["発動ID"]:by_policy[rp][r["発動ID"]] for r in eligible if r["戦略判定"][rp]["採用"]}
                subsets.append({"期間":period,"役割":role,"比較":title,"左入口":lp,"右入口":rp,"保持入口":entry_summary([left[k] for k in left.keys() & right.keys()]),"除外入口":entry_summary([left[k] for k in left.keys()-right.keys()]),"新規追加入口数":len(right.keys()-left.keys()),"準備除外理由_重複あり":dict(Counter(readiness_group(raw_map[k]) for k in left.keys()-right.keys())) if lp == "C0" else {}})
            for sign in ("未準備","正","0","負"):
                selected=[r for r in eligible if r["戦略判定"]["C0"]["採用"] and value_group(r) == sign]
                fast_groups.append({"期間":period,"役割":role,"実方向Fast差":sign,**entry_summary([by_policy["C0"][r["発動ID"]] for r in selected])})
            for daynight in ("デイ","ナイト"):
                own=[r for r in eligible if ("デイ" if r["場"].endswith("_Day") else "ナイト") == daynight]
                composition.append({"期間":period,"役割":role,"日夜":daynight,"原P数":len(own),"構造別":dict(Counter(r["判別種別"] for r in own)),**{p+"純入口数":sum(r["戦略判定"][p]["採用"] for r in own) for p in POLICIES}})
            for policy in POLICIES:
                own=[r for r in eligible if r["戦略判定"][policy]["採用"]]
                ages.append({"期間":period,"役割":role,"入口":policy,"純要求数":len(own),"中心から判断までの本数":H.distribution([r["index"]-pivots[r["突破極値ID"]]["中心番号"] for r in own]),"確認から判断までの本数":H.distribution([r["index"]-pivots[r["突破極値ID"]]["確認足番号"] for r in own]),"確認後の待ち秒":H.distribution([r["要求時計秒"]-pivots[r["突破極値ID"]]["確認出典"]["confirm"] for r in own])})
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
                        records.append("同P純入口なし" if other is None else handling.get((cid,other["イベントID"]),"取扱記録なし"))
                    return dict(Counter(records))

                exit_diff=sum(any(left[k][f] != right[k][f] for f in ("返済時計秒","返済原板行","返済価格","返済理由")) for k in common)
                check(title+period+role+":共通出口属性",exit_diff,0)
                item={"期間":period,"役割":role,"比較":title,"左":left_id,"右":right_id,"厳密共通実新規数":len(common),"共通出口属性差数":exit_diff,
                    "同P両実参加数":len({case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[left_id]} & {case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[right_id]}),
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
        "モデル再計算":False,"指標再計算":False,"先着再計算":False,"運用再生":False,"新閾値選別":False,"新価格母集団":True,"旧完全対照なし":True,
        "C0C1保存case識別正規化同値":{k:F.rename(v,"_C1","_C0") for k,v in by_policy["C1"].items()} == by_policy["C0"],
        "価格状態と新P":stages,"入口追加比較":subsets,"C0のFast区分":fast_groups,"日夜と役割構成":composition,"極値の古さ":ages,
        "実参加比較":participation,"役割別実参加比較":role_participation,"候補別回収":recovery,"役割別回収":role_recovery,"品質と確定額":qualities,
        "責任分界":"保存極値ID/monitor/P/数値欄の参照・消費・内部算術だけ。原8列からの極値/DI/Fast/全採否と全新先着は45状態、全保有/最初要求は追尾、全Decimal/CSV/Viewerは財務。旧controlや旧label同値ではない",
        "限界":["rawの初cross消費と実一建玉の抑止は別機械。非採用Pを次の空き時計へ延期しない。","T/Rは構造に対する分類で、役割名だけの変更に出口改善効果を帰属しない。","新母集団・全NK66既使用。Fast準備/値と純subset/actual追加、仮250/回収を分ける。","DI正本定義hashと独立生数値の差/符号/採否strictは別保証。ATRは共有値で、Fastは精密差を使う。","古さ/日夜/符号区分は保存診断だけで新閾値へ戻さず、未保存群の先着を補算しない。"]}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """rootの正式後許可で保存六系列だけを一度集計する。

    引数: study/work(Path)は45保存先。
    返り値: dictは小型診断。市場/新指標/先着/運用/監査を起動しない。
    """
    if not (study/"結果.json").is_file():raise ValueError("正式結果完成前に保存診断を起動しません")
    numeric,price,decisions,cases,details,_=(H.read(work/n) for n in FILES)
    output=analyze(cases,decisions,price,numeric,details,H.read(study/"結果.json"))
    paths=[Path(__file__),HELPER,ROOT/"scripts/量比反転/対応診断.py",ROOT/"scripts/終値位置/対応診断.py",ROOT/"scripts/SAR追尾/対応診断.py",
        *[study/n for n in ("計画.md","条件.json","固定.json","結果.json","入力台帳.json","指標参照.json")],work/"診断予定.json",*[work/n for n in FILES]]
    output["ファイルSHA256"]={p.relative_to(ROOT).as_posix():H.sha(p) for p in dict.fromkeys(paths)}
    output["参照SHA256"]={n:H.sha(study/n) for n in ("結果.json","指標参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    if not output["全件一致"]:raise RuntimeError("新スイング保存診断に不一致")
    return output


def main() -> None:
    """正式許可後の保存診断を担当一人で一回だけ起動する。

    引数: なし。--study/--workはPath。
    返り値: None。市場/先着/モデル再生は起動しない。
    """
    parser=argparse.ArgumentParser(description="新スイング状態/Fast選別/実参加と回収の保存診断")
    parser.add_argument("--study",type=Path,default=STUDY);parser.add_argument("--work",type=Path,default=WORK)
    args=parser.parse_args();output=run(args.study.resolve(),args.work.resolve())
    print(H.json.dumps({k:output[k] for k in ("全件一致","照合項目数","不一致数")},ensure_ascii=False))


if __name__ == "__main__":main()
