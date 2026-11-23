"""上位方向・Force波の登録/回復/初価格端と、実役割/実参加/回収を保存値で分離する。"""

import argparse
from collections import Counter
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00048_Force失敗後の価格確認と上位禁止"
WORK = ROOT/"work/Force失敗確認/00048"
HELPER = ROOT/"scripts/構造判別/対応診断.py"
SPEC = importlib.util.spec_from_file_location("Force失敗48の固定保存集計",HELPER)
F = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = F
SPEC.loader.exec_module(F)
H,entry_summary = F.H,F.entry_summary
PERIODS = ("学習","条件選択","後続検査")
POLICIES = ("S0","S1")
ACTIVE_ROLES = {"S0":("順行","反転"),"S1":("順行","反転")}
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
PAIRS = (("切替全体",CANDIDATES[0],CANDIDATES[1],None),("共通Tの実占有",CANDIDATES[0],CANDIDATES[1],"順行"),("新Rの上位条件",CANDIDATES[0],CANDIDATES[1],"反転"))
PURE_FIELDS = ("場","side","方向","要求時計秒","要求原板行","確認遅延秒","low","high","atr","bb_mean")
LABEL_FIELDS = ("ラベル","理由","新規価格","新規時計秒","新規原板行","判定時計秒","判定原板行","判定気配","最大順行pt","最大逆行pt","所要分")
FAILURE_FIELDS = ("失敗足番号","失敗時計秒","失敗原板行","失敗ID","失敗段階","失敗確認端")
META_FIELDS = ("元登録ID","元価格side","元登録時計秒","元登録原板行","回復足番号","回復時計秒","判別種別",*FAILURE_FIELDS)
SOURCE_FIELDS = ("場","index","minutes","start","end","confirm","confirm_line","publish","missing","open","high","low","close")
FRAME_FIELDS = (*SOURCE_FIELDS,"atr","数量参照")
FILES = ("全指標.jsonl.gz","上位15分.jsonl.gz","価格状態.jsonl.gz","発動判定.jsonl.gz","入口事例.jsonl.gz","全運用詳細.jsonl.gz","追尾.jsonl.gz")


def finite(value: object) -> bool:
    """保存値が有限実数かを判別する。

    引数: value(object)は保存値。
    返り値: boolは真偽値を除く有限実数であること。
    """
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def fraction(value: dict) -> Fraction | None:
    """保存した精密値を復元する。

    引数: value(dict)は有効/分子/分母。
    返り値: Fraction|Noneは保存値。過去窓から指標を再計算しない。
    """
    return Fraction(value["分子"],value["分母"]) if value["有効"] else None


def sign(value: Fraction | float | None) -> int | None:
    """保存差のstrict符号を返す。

    引数: value(Fraction|float|None)は保存差。
    返り値: int|Noneは負/同値/正の符号。
    """
    return None if value is None else (value > 0)-(value < 0)


def economic_identity(trade: dict) -> tuple:
    """役割ラベルを除いた同経済的新規の対応keyを返す。

    引数: trade(dict)は保存完結。
    返り値: tupleは場/side/新規key/価格/入口ATR/D。役割変更を独立機会にしない。
    """
    return (*H.identity(trade),trade["入口ATR"],trade["追尾距離pt"])


def analyze(cases: list[dict], decisions: list[dict], price: list[dict], numeric: list[dict], higher: list[dict], details: list[dict], result: dict | None = None) -> dict:
    """保存七系列の参照と内部算術、段階/純和集合/実占有を記述する。

    引数: cases/decisions/price/numeric/higher/details(list[dict])は保存値、result(dict|None)は結果。
    返り値: dictは診断。原板・Force/上位銀行・先着・運用を再計算しない。
    """
    errors,checks = [],0

    def check(label: str, actual: object, expected: object) -> None:
        """保存された参照・算術・集合の一致を記録する。

        引数: label(str)は項目、actual/expected(object)は保存比較値。
        返り値: None。不一致のみ小型一覧へ保存する。
        """
        nonlocal checks
        checks += 1
        if actual != expected:errors.append({"項目":label,"実値":actual,"期待値":expected})

    raw_map = {r["発動ID"]:r for r in decisions}
    case_map = {r["イベントID"]:r for r in cases}
    frames = {(r["場"],r["index"]):r for r in numeric}
    upper_frames = {(r["場"],r["index"]):r for r in higher}
    registrations = {r["登録ID"]:r for r in price if r["種別"] == "登録"}
    monitors = [r for r in price if r["種別"] == "監視"]
    by_policy = {p:{r["元価格発動ID"]:r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    check("原P一意",len(raw_map),len(decisions));check("case一意",len(case_map),len(cases))
    check("全3分一意",len(frames),len(numeric));check("全上位一意",len(upper_frames),len(higher))
    check("全監視一意",len({(r["場"],r["index"]) for r in monitors}),len(monitors))
    check("全3分全監視対応",set(frames),{(r["場"],r["index"]) for r in monitors})
    check("純S0subsetS1",by_policy["S0"].keys() <= by_policy["S1"].keys(),True)
    check("純T両案同値",{k for k,r in by_policy["S0"].items() if r["役割"] == "順行"},{k for k,r in by_policy["S1"].items() if r["役割"] == "順行"})
    recoveries,failures,ends = {},{},Counter()
    for row in monitors:
        frame = frames[row["場"],row["index"]]
        check(str((row["場"],row["index"]))+":監視価格出典",row["足出典"],{k:frame[k] for k in SOURCE_FIELDS})
        check(str((row["場"],row["index"]))+":監視Force",row["Force2"],frame["Force2"])
        for state in ("監視前","監視後"):
            if row[state] is not None:check(str(row["index"])+state+":受理親",registrations[row[state]["登録ID"]]["受理"],True)
        for action in row["動作"]:
            parent = action["登録ID"]
            check(parent+action["動作"]+":登録出典存在",parent in registrations,True)
            if action["動作"] == "初回回復固定":
                check(parent+":回復一回",parent not in recoveries,True)
                recoveries[parent] = {"index":row["index"],**action["回復参照"]}
            if action["動作"] == "初回失敗固定":
                check(parent+":失敗一回",parent not in failures,True)
                failures[parent] = {"index":row["index"],"失敗段階":action["失敗段階"],**action["失敗参照"]}
            if action["動作"] in ("監視取消","寿命満了","初回回復不一致WAIT","順行初端消費","反転初確認消費","失敗後元逆端回復取消","場末監視取消"):
                ends[parent] += 1
            if action["動作"] in ("順行初端消費","反転初確認消費"):
                check(parent+":終端P参照",action["発動ID"] in raw_map,True)
    accepted = {k:r for k,r in registrations.items() if r["受理"]}
    check("受理bは一回終了",dict(ends),{k:1 for k in accepted})
    for origin,row in registrations.items():
        source = row["登録足"]
        check(origin+":b出典",source,{k:frames[source["場"],source["index"]][k] for k in FRAME_FIELDS})
        side = row["元価格side"]
        check(origin+":逆行cross",side*fraction(row["前足Force"]) >= 0 and side*fraction(row["登録Force"]) < 0,True)
        check(origin+":受理理由",row["受理"],not row["登録除外理由"])
        if row["受理"]:
            for field in ("前上位状態","登録上位状態"):
                check(origin+field+":背景既知",row[field]["上位現前準備"] and row[field]["上位方向"] == side,True)
    for origin,row in raw_map.items():
        frame = frames[row["場"],row["index"]]
        for field,value in frame.items():
            if field != "期間":check(origin+":数値コピー:"+field,row[field],value)
        parent = accepted[row["元登録ID"]]
        recovery = recoveries.get(row["元登録ID"])
        failure = failures.get(row["元登録ID"])
        b = parent["登録足"]
        side,kind = row["元価格side"],row["価格区分"]
        check(origin+":年齢",row["年齢"],row["index"]-b["index"])
        check(origin+":固定逆端",row["初期逆端"],b["low"] if side == 1 else b["high"])
        check(origin+":寿命",1 <= row["年齢"] <= 6,True)
        if kind == "T":
            j = recovery["足出典"]
            check(origin+":回復後時点",b["index"] < j["index"] < row["index"] and row["end"] > j["confirm"] and (row["confirm"],row["confirm_line"]) > (j["confirm"],j["confirm_line"]),True)
            check(origin+":固定再開端",row["再開端"],j["high"] if side == 1 else j["low"])
            check(origin+":Tstrict終値端",side*(Fraction(row["close"])-Fraction(row["再開端"])) > 0,True)
            check(origin+":T失敗列なし",[row[k] for k in FAILURE_FIELDS],[None]*6)
        else:
            f = failure["足出典"]
            check(origin+":f後別足k",b["index"] < f["index"] < row["index"] and row["end"] > f["confirm"] and (row["confirm"],row["confirm_line"]) > (f["confirm"],f["confirm_line"]),True)
            check(origin+":失敗参照",(row["失敗足番号"],row["失敗時計秒"],row["失敗原板行"],row["失敗段階"]),(f["index"],f["confirm"],f["confirm_line"],failure["失敗段階"]))
            check(origin+":fは元端strict失敗",side*(Fraction(f["close"])-Fraction(row["初期逆端"])) < 0,True)
            check(origin+":固定確認端",row["失敗確認端"],f["low"] if side == 1 else f["high"])
            check(origin+":Rstrict確認",-side*(Fraction(row["close"])-Fraction(row["失敗確認端"])) > 0,True)
            check(origin+":元端回復取消なし",side*(Fraction(row["close"])-Fraction(row["初期逆端"])) < 0,True)
            if failure["失敗段階"] == "回復前":check(origin+":前fは回復無し",(row["回復足番号"],row["回復時計秒"]),(None,None))
            else:check(origin+":後fは回復を先行",recovery["index"] < f["index"],True)
        actual_side,role = (side,"順行") if kind == "T" else (-side,"反転")
        check(origin+":実方向/役割",(row["side"],row["役割"]),(actual_side,role))
        upper = row["上位参照"];previous = row["前上位参照"]
        for value in (upper,previous):
            check(origin+":上位出典",value,{k:upper_frames[row["場"],value["index"]][k] for k in value})
            check(origin+":当時asof",value["publish"] and value["end"] <= row["end"] and (value["confirm"],value["confirm_line"]) <= (row["confirm"],row["confirm_line"]),True)
        delta = upper["macd_hist"]-previous["macd_hist"]
        check(origin+":保存上位差",row["上位ヒスト差"],delta)
        check(origin+":上位方向",row["上位方向"],sign(delta))
        force = fraction(row["Force2"])
        ema_values = upper["ema13_centered"],previous["ema13_centered"]
        ema_delta = ema_values[0]-ema_values[1] if all(finite(v) for v in ema_values) else None
        check(origin+":保存EMA差",row["上位EMA差"],ema_delta)
        check(origin+":EMA進行E",row["上位EMA差符号"],sign(ema_delta))
        impulse = row["上位方向"] if ema_delta is not None and sign(ema_delta) == row["上位方向"] != 0 else 0 if ema_delta is not None else None
        check(origin+":ImpulseI",row["上位Impulse方向"],impulse)
        direction_ok = sign(force) == actual_side and (kind == "R" or row["上位方向"] == actual_side)
        check(origin+":技術方向",row["技術方向可"],direction_ok)
        check(origin+":共通M",row["共通M準備"],not row["M除外理由"])
        eligible = bool(row["共通M準備"] and row["技術方向可"] and row["時間条件可"] and row["確認遅延条件可"])
        expected = {}
        for policy in POLICIES:
            value_ok = kind == "T" or row["上位方向"] == actual_side if policy == "S0" else kind == "T" or impulse is not None and impulse != side
            adopted = eligible and value_ok and not row["戦略判定"][policy]["同時競合"]
            expected[policy] = adopted
            check(origin+policy+":採否",row["戦略判定"][policy]["採用"],adopted)
            check(origin+policy+":純集合",origin in by_policy[policy],adopted)
            if adopted:
                own,base = by_policy[policy][origin],by_policy["S1"][origin]
                for field in (*PURE_FIELDS,*META_FIELDS,*LABEL_FIELDS,"役割","期間"):check(origin+policy+":同P属性:"+field,own[field],base[field])
                check(origin+policy+":実役割",own["役割"],role)
                check(origin+policy+":実side",own["side"],actual_side)
                for field in META_FIELDS:check(origin+policy+":元判断:"+field,own[field],row[field])
        check(origin+":共通判別",row["判別種別"],kind if any(expected.values()) else "WAIT")

    # ----------------------------------------
    # 全cross候補/受理b/回復j/初価格端と、純T-R-Sを別分母で集約する。
    stages,composition,timing,force_groups,distances,subsets,upper_groups = [],[],[],[],[],[],[]
    for period in PERIODS:
        regs = [r for r in registrations.values() if r["期間"] == period]
        traces = [r for r in monitors if r["期間"] == period]
        raw = [r for r in decisions if r["期間"] == period]
        actions = Counter(a["動作"] for r in traces for a in r["動作"])
        stages.append({"期間":period,"下位数値足数":sum(r["期間"] == period for r in numeric),"上位数値足数":sum(r["期間"] == period for r in higher),"逆行cross候補数":len(regs),"受理b数":sum(r["受理"] for r in regs),"登録不受理理由_重複":dict(Counter(reason for r in regs for reason in r["登録除外理由"])),"監視動作別":dict(actions),"初回回復j数":actions["初回回復固定"],"初回失敗f数":actions["初回失敗固定"],"失敗前後別":dict(Counter(f["失敗段階"] for k,f in failures.items() if accepted[k]["期間"] == period)),"f年齢6数":sum(f["index"]-accepted[k]["登録足"]["index"] == 6 for k,f in failures.items() if accepted[k]["期間"] == period),"初価格端数":len(raw),"構造T-R別":dict(Counter(r["価格区分"] for r in raw)),"最終T-R-WAIT別":dict(Counter(r["判別種別"] for r in raw)),**{p+"純入口数":sum(r["戦略判定"][p]["採用"] for r in raw) for p in POLICIES}})
        for daynight in ("デイ","ナイト"):
            own = [r for r in raw if ("デイ" if r["場"].endswith("_Day") else "ナイト") == daynight]
            composition.append({"期間":period,"日夜":daynight,"初価格端数":len(own),"構造T-R別":dict(Counter(r["価格区分"] for r in own)),"最終T-R-WAIT別":dict(Counter(r["判別種別"] for r in own)),**{p+"純入口数":sum(r["戦略判定"][p]["採用"] for r in own) for p in POLICIES}})
        for policy in POLICIES:
            for role in ACTIVE_ROLES[policy]:
                own = [r for r in cases if r["期間"] == period and r["入口ID"] == "3分_"+policy and r["役割"] == role]
                values = [raw_map[r["元価格発動ID"]] for r in own]
                timing.append({"期間":period,"入口":policy,"役割":role,"純要求数":len(own),"元bからの本数":H.distribution([r["年齢"] for r in values]),"bから回復まで秒":H.distribution([r["回復時計秒"]-r["元登録時計秒"] for r in values if r["回復時計秒"] is not None]),"回復から価格端まで秒":H.distribution([r["要求時計秒"]-r["回復時計秒"] for r in values if r["回復時計秒"] is not None]),"bから失敗fまで秒":H.distribution([r["失敗時計秒"]-r["元登録時計秒"] for r in values if r["失敗時計秒"] is not None]),"失敗fから確認kまで秒":H.distribution([r["要求時計秒"]-r["失敗時計秒"] for r in values if r["失敗時計秒"] is not None]),"失敗前後別":dict(Counter(r["失敗段階"] for r in values if r["失敗段階"] is not None))})
                targets = [(c,raw_map[c["元価格発動ID"]]) for c in own]
                close_distance = [c["side"]*((r["再開端"] if r["価格区分"] == "T" else r["失敗確認端"])-r["close"]) for c,r in targets]
                fill_distance = [c["side"]*((r["再開端"] if r["価格区分"] == "T" else r["失敗確認端"])-c["新規価格"]) for c,r in targets if c["新規価格"] is not None]
                distances.append({"期間":period,"入口":policy,"役割":role,"純要求数":len(own),"要求終値から発動端まで実方向距離pt":H.distribution(close_distance),"仮新規から発動端まで実方向距離pt":H.distribution(fill_distance)})
        for role in ("全体","順行","反転"):
            left={k:r for k,r in by_policy["S0"].items() if r["期間"] == period and (role == "全体" or r["役割"] == role)}
            right={k:r for k,r in by_policy["S1"].items() if r["期間"] == period and (role == "全体" or r["役割"] == role)}
            subsets.append({"期間":period,"役割":role,"保持入口":entry_summary([left[k] for k in left.keys() & right.keys()]),"S1追加入口":entry_summary([right[k] for k in right.keys()-left.keys()]),"S0除外入口数":len(left.keys()-right.keys())})
        for ds in (-1,0,1):
            for es in (-1,0,1):
                own=[r for r in raw if r["価格区分"] == "R" and r["上位EMA現前準備"] and r["元価格side"]*r["上位方向"] == ds and r["元価格side"]*r["上位EMA差符号"] == es]
                selected=[by_policy["S1"][r["発動ID"]] for r in own if r["戦略判定"]["S1"]["採用"]]
                added=[by_policy["S1"][r["発動ID"]] for r in own if r["戦略判定"]["S1"]["採用"] and not r["戦略判定"]["S0"]["採用"]]
                upper_groups.append({"期間":period,"元方向D":ds,"元方向E":es,"元方向I":ds if ds == es != 0 else 0,"新Rk数":len(own),"共通M時間Force可数":sum(r["共通M準備"] and r["技術方向可"] and r["時間条件可"] and r["確認遅延条件可"] for r in own),"S0採用数":sum(r["戦略判定"]["S0"]["採用"] for r in own),"S1採用":entry_summary(selected),"S1追加R":entry_summary(added)})
        for title,group in (("受理b",[r for r in regs if r["受理"]]),("全cross",regs)):
            repeated = sum(r["前上位状態"] is not None and r["前上位状態"]["上位参照"] is not None and r["登録上位状態"]["上位参照"] is not None and r["前上位状態"]["上位参照"]["index"] == r["登録上位状態"]["上位参照"]["index"] for r in group)
            force_groups.append({"期間":period,"分母":title,"件数":len(group),"pとbの上位u同一数":repeated,"登録当足q0数":sum(r["登録足"]["数量参照"]["観測差分量"] == 0 for r in group)})
        for role in ("順行","反転"):
            own = [r for r in raw if r["役割"] == role]
            force_groups.append({"期間":period,"分母":"初価格端"+role,"件数":len(own),"当足q0数":sum(r["数量参照"]["観測差分量"] == 0 for r in own),"現在Force実方向一致数":sum(r["Force符号"] == r["side"] for r in own)})
    # ----------------------------------------
    # 役割を除く経済的新規を対応し、役割変更と出口・占有効果を分ける。
    trades = [{**t,"候補ID":d["候補ID"]} for d in details for t in d["取引"]]
    handling = {(d["候補ID"],s["イベントID"]):s["取扱"] for d in details for s in d["入口取扱"]}
    for trade in trades:
        case = case_map[trade["入口イベントID"]]
        for field in ("新規時計秒","新規原板行","新規価格"):
            check("実新規と保存case:"+field,trade[field],case[field])
        check("実役割保持",trade["入口役割"],case["役割"])
        check("入口jATR保持",trade["入口ATR"],case["atr"])
    participation,role_links,recovery,role_recovery,qualities = [],[],[],[],[]
    for period in PERIODS:
        own = {cid:[t for t in trades if t["候補ID"] == cid and t["期間"] == period] for cid in CANDIDATES}
        for cid in CANDIDATES:
            check(cid+period+":経済的新規一意",len({economic_identity(t) for t in own[cid]}),len(own[cid]))
        for title,left_id,right_id,compare_role in PAIRS:
            left,right = ({F.strict_identity(t):t for t in own[cid] if compare_role is None or t["入口役割"] == compare_role} for cid in (left_id,right_id))
            common,removed,added = left.keys() & right.keys(),left.keys()-right.keys(),right.keys()-left.keys()
            costs = []
            for fee in (0,5,10):
                field = f"追加滑り{fee}pt純損益円"
                diff = sum(right[k][field]-left[k][field] for k in common)
                total = H.cash(list(right.values()),fee)-H.cash(list(left.values()),fee)
                minus,plus = H.cash([left[k] for k in removed],fee),H.cash([right[k] for k in added],fee)
                check(title+period+str(fee)+":全差分解",total,diff-minus+plus)
                check(title+period+str(fee)+":同XF共通差0",diff,0)
                costs.append({"片道追加pt":fee,"総差円_右引く左":total,"共通出口差円":diff,"左のみ損益円":minus,"右のみ損益円":plus})

            def counterpart(rows: list[dict], cid: str) -> dict:
                """片側参加の相手を純除外と保存された実抑止へ分ける。

                引数: rows(list[dict])は完結、cid(str)は相手候補。
                返り値: dictは取扱別件数。役割違いを純入口なしにしない。
                """
                policy = cid.split("_")[1]
                records = []
                for trade in rows:
                    origin = case_map[trade["入口イベントID"]]["元価格発動ID"]
                    other = by_policy[policy].get(origin)
                    records.append("同P純入口なし" if other is None else handling.get((cid,other["イベントID"]),"取扱記録なし"))
                return dict(Counter(records))

            exit_diff = sum(any(left[k][f] != right[k][f] for f in ("返済時計秒","返済原板行","返済価格","返済理由")) for k in common)
            check(title+period+":共通出口属性",exit_diff,0)
            same_role = sum(left[k]["入口役割"] == right[k]["入口役割"] for k in common)
            participation.append({"期間":period,"比較":title,"役割":compare_role or "全体","左":left_id,"右":right_id,"経済的共通実新規数":len(common),"同役割共通数":same_role,"役割だけ違う共通数":len(common)-same_role,"共通出口属性差数":exit_diff,"同P両実参加数":len({case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[left_id]} & {case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[right_id]}),"左のみ":H.operation_summary([left[k] for k in removed]),"右のみ":H.operation_summary([right[k] for k in added]),"左のみの相手取扱":counterpart([left[k] for k in removed],right_id),"右のみの相手取扱":counterpart([right[k] for k in added],left_id),"費用別":costs})
            for left_role in ACTIVE_ROLES[left_id.split("_")[1]]:
                for right_role in ACTIVE_ROLES[right_id.split("_")[1]]:
                    keys = [k for k in common if left[k]["入口役割"] == left_role and right[k]["入口役割"] == right_role]
                    role_links.append({"期間":period,"比較":title,"左役割":left_role,"右役割":right_role,"共通数":len(keys),"共通出口差円":{str(f):sum(right[k][f"追加滑り{f}pt純損益円"]-left[k][f"追加滑り{f}pt純損益円"] for k in keys) for f in (0,5,10)}})
        for cid in CANDIDATES:
            for role in ("全体",*ACTIVE_ROLES[cid.split("_")[1]]):
                rows = [t for t in own[cid] if role == "全体" or t["入口役割"] == role]
                successes = [t for t in rows if case_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
                armed = [t for t in rows if t["追尾起動"]]
                reds = [t for t in armed if t["起動後純赤字"]]
                nominal = lambda t:(1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"])
                item = {"候補ID":cid,"期間":period,"役割":role,**H.operation_summary(rows),"対応仮250数":len(successes),"仮250判定前返済数":sum((t["返済時計秒"],t["返済原板行"]) < (case_map[t["入口イベントID"]]["判定時計秒"],case_map[t["入口イベントID"]]["判定原板行"]) for t in successes),"実保有MFE250数":sum(t["観測最大順行pt"] >= 250 for t in rows),"起動数":len(armed),"起動後基準赤字数":len(reds),"名目同値費用赤字数":sum(nominal(t) == 0 for t in reds),"不利返済赤字数":sum(nominal(t) < 0 for t in reds),"正名目利益の基準費用負け数":sum(nominal(t) > 0 for t in reds)}
                (recovery if role == "全体" else role_recovery).append(item)
    if result is not None:
        check("二運用順",[r["候補ID"] for r in result["結果"]],list(CANDIDATES))
        check("実四役割群",[(r["入口ID"],r["役割"]) for r in result["役割別入口評価"]],[("3分_"+p,role) for p in POLICIES for role in ACTIVE_ROLES[p]])
        for source in (*result["入口評価"],*result["役割別入口評価"]):
            for period in PERIODS:
                local = [r for r in cases if r["入口ID"] == source["入口ID"] and r["期間"] == period and (source["役割"] == "切替" or r["役割"] == source["役割"])]
                summary = entry_summary(local)
                for field in ("候補数","約定候補数","順行先着","逆行先着","期限未達","観測不足","未約定","確認率"):
                    check(source["入口ID"]+source["役割"]+period+field,source[period][field],summary[field])
        for row in result["結果"]:
            for period in PERIODS:
                op = row[period]["運用"]
                local = own_rows = [t for t in trades if t["候補ID"] == row["候補ID"] and t["期間"] == period]
                check(row["候補ID"]+period+":完結",op["完結取引数"],len(own_rows))
                for fee in (0,5,10):check(row["候補ID"]+period+str(fee)+":会計",op[f"追加{fee}pt純損益円"],H.cash(local,fee))
                qualities.append({"候補ID":row["候補ID"],"期間":period,**{k:op[k] for k in ("品質注意場数","未解消場数","EOF期限未達場数")},"観測純額円":{str(f):op[f"追加{f}pt純損益円"] for f in (0,5,10)},"全体確定対象円":{str(f):op[f"追加{f}pt確定対象円"] for f in (0,5,10)}})
    return {"全件一致":not errors,"照合項目数":checks,"不一致数":len(errors),"不一致":errors,
        "モデル再計算":False,"指標再計算":False,"先着再計算":False,"運用再生":False,"新閾値選別":False,"新価格母集団":True,"旧完全対照なし":True,
        "登録と監視の段階":stages,"日夜と構造区分":composition,"診断専用の時間":timing,"診断専用の端距離":distances,"Forceと背景の構成":force_groups,
        "純保持と追加":subsets,"反転上位区分":upper_groups,"実参加比較":participation,"共通新規の役割対応":role_links,"候補別回収":recovery,"役割別回収":role_recovery,"品質と確定額":qualities,"実役割群数":4,
        "責任分界":"保存下位26列/上位15列/登録・回復・前後f・新T端又はkの参照と内部算術・集合だけ。原8列/Q/Force/HとEMA/当時asof/全監視優先・全採否・全新先着は48状態、全保有/最初要求は追尾、Decimal/CSV/Viewerは財務。旧47全期T/旧label/旧運用control無し。",
        "限界":["同じ新母機械のS0/S1で純T同値/R包含を比べ、旧47の全期T同値は要求しない。全66場既使用。",
            "fは観測だけで注文/先着分母ではない。T端/反転確認kが新要求、前fRでは回復j無しを保持する。",
            "共通EMA準備と値を分け、I0/禁止不在を上位転換や解除遷移の証明としない。",
            "純包含でも実一建玉の追加R保有が後続T/Rを抑止し得る。実参加・損益包含は保証しない。",
            "時間/年齢/端距離は記述だけで新gateへ戻さず、未保存f/見送り群の先着を補算しない。",
            "起動後基準赤字は追加0pt手数料込み。起動参照5pt122円や追加5pt損益と別尺度。品質注意の観測額は全体確定nullと分離する。"]}



def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式許可後に保存七系列だけを一度集計する。

    引数: study/work(Path)は48保存先。
    返り値: dictは小型診断。市場/数値/先着/運用を起動しない。
    """
    if not (study/"結果.json").is_file():raise ValueError("正式結果完成前に保存診断を起動しません")
    if (work/"対応診断.json").exists():raise ValueError("既存の正式保存診断を上書きしません")
    numeric,higher,price,decisions,cases,details,_ = (H.read(work/n) for n in FILES)
    output = analyze(cases,decisions,price,numeric,higher,details,H.read(study/"結果.json"))
    paths = [Path(__file__),HELPER,ROOT/"scripts/量比反転/対応診断.py",ROOT/"scripts/終値位置/対応診断.py",ROOT/"scripts/SAR追尾/対応診断.py",*[study/n for n in ("計画.md","条件.json","固定.json","結果.json","入力台帳.json","指標参照.json","上位参照.json")],work/"診断予定.json",*[work/n for n in FILES]]
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix():H.sha(p) for p in dict.fromkeys(paths)}
    output["参照SHA256"] = {n:H.sha(study/n) for n in ("結果.json","指標参照.json","上位参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    if not output["全件一致"]:raise RuntimeError("Force失敗f/新価格確認kの保存診断に不一致")
    return output


def main() -> None:
    """正式許可後の保存診断を担当一人で一回だけ起動する。

    引数: なし。--study/--workはPath。
    返り値: None。市場/先着/運用再生は呼ばない。
    """
    parser = argparse.ArgumentParser(description="Force失敗f/新価格確認kの保存診断")
    parser.add_argument("--study",type=Path,default=STUDY)
    parser.add_argument("--work",type=Path,default=WORK)
    args = parser.parse_args()
    output = run(args.study.resolve(),args.work.resolve())
    print(H.json.dumps({k:output[k] for k in ("全件一致","照合項目数","不一致数")},ensure_ascii=False))


if __name__ == "__main__":main()
