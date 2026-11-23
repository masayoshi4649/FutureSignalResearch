"""二実体・平均準備・符号分類と、実役割/実参加/回収を保存値で分離する。"""

import argparse
from collections import Counter
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00046_二足の実体包みと平均進行"
WORK = ROOT/"work/実体包み/00046"
HELPER = ROOT/"scripts/構造判別/対応診断.py"
SPEC = importlib.util.spec_from_file_location("実体46の固定保存集計",HELPER)
F = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = F
SPEC.loader.exec_module(F)
H,entry_summary = F.H,F.entry_summary
PERIODS = ("学習","条件選択","後続検査")
POLICIES = ("B0","B1","B2")
ACTIVE_ROLES = {"B0":("反転",),"B1":("反転",),"B2":("順行","反転")}
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
PAIRS = (("前平均準備追加",CANDIDATES[0],CANDIDATES[1]),("進行と位置の分類",CANDIDATES[1],CANDIDATES[2]))
PURE_FIELDS = ("場","side","方向","要求時計秒","要求原板行","確認遅延秒","low","high","atr","bb_mean")
LABEL_FIELDS = ("ラベル","理由","新規価格","新規時計秒","新規原板行","判定時計秒","判定原板行","判定気配","最大順行pt","最大逆行pt","所要分")
META_FIELDS = ("元価格side","前足番号","B2判別種別","B2役割")
SOURCE_FIELDS = ("場","index","minutes","start","end","confirm","confirm_line","publish","missing","open","high","low","close")
FRAME_FIELDS = (*SOURCE_FIELDS,"atr","macd_hist")
FILES = ("全指標.jsonl.gz","発動判定.jsonl.gz","入口事例.jsonl.gz","全運用詳細.jsonl.gz","追尾.jsonl.gz")


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


def analyze(cases: list[dict], decisions: list[dict], numeric: list[dict], details: list[dict], result: dict | None = None) -> dict:
    """保存五系列の参照・内部算術・集合と回収を記述する。

    引数: cases/decisions/numeric/details(list[dict])は保存値、result(dict|None)は正式結果。
    返り値: dictは診断。市場・ローリング指標・先着・運用は再計算しない。
    """
    errors,checks = [],0

    def check(label: str, actual: object, expected: object) -> None:
        """保存比較の一致と不一致を記録する。

        引数: label(str)は項目、actual/expected(object)は比較値。
        返り値: None。不一致だけ小型一覧へ保存する。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            errors.append({"項目":label,"実値":actual,"期待値":expected})

    raw_map = {r["発動ID"]:r for r in decisions}
    case_map = {r["イベントID"]:r for r in cases}
    frames = {(r["場"],r["index"]):r for r in numeric}
    by_policy = {p:{r["元価格発動ID"]:r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    check("原P一意",len(raw_map),len(decisions))
    check("case一意",len(case_map),len(cases))
    check("数値足一意",len(frames),len(numeric))
    for left,right in (("B0","B1"),("B1","B2")):
        check(left+right+":元P部分集合",by_policy[right].keys() <= by_policy[left].keys(),True)
    for origin,row in raw_map.items():
        own = frames[row["場"],row["index"]]
        prior = row["前3分参照"]
        for field,value in own.items():
            if field != "期間":check(origin+":数値コピー:"+field,row[field],value)
        check(origin+":前出典",prior,{k:frames[row["場"],prior["index"]][k] for k in FRAME_FIELDS})
        check(origin+":隣接",(prior["index"]+1,prior["end"]),(row["index"],row["start"]))
        check(origin+":公開時点",(prior["confirm"],prior["confirm_line"]) < (row["confirm"],row["confirm_line"]) and prior["confirm"] >= prior["end"] and row["confirm"] >= row["end"],True)
        check(origin+":完全公開二足",all(r["publish"] and r["missing"] == 0 and r["minutes"] == 3 and r["end"]-r["start"] == 180 for r in (prior,row)),True)
        side = row["side"]
        op,cp,oj,cj = (Fraction(v) for v in (prior["open"],prior["close"],row["open"],row["close"]))
        body_values = (cp-op,cj-oj,oj-cp,cj-op)
        for field,value in zip(("前実体","現実体","始値対前終値","終値対前始値"),body_values):
            check(origin+":保存二実体算術:"+field,fraction(row[field]),value)
        check(origin+":実体包み境界",side*body_values[0] < 0 and side*body_values[1] > 0 and side*body_values[2] <= 0 and side*body_values[3] > 0,True)
        check(origin+":価格差自動正",side*(cj-cp) > 0,True)
        hp,hj = prior["macd_hist"],row["macd_hist"]
        change = hj-hp if finite(hj) and finite(hp) else None
        for field,value in (("MACDヒスト現",hj),("MACDヒスト前",hp),("MACDヒスト変化",change),("MACDヒスト変化符号",sign(change))):
            check(origin+":保存H:"+field,row[field],value)
        mp,mpp,dm,dp = (fraction(row[k]) for k in ("SMA前","SMA前々","SMA進行","終値対前SMA"))
        check(origin+":保存平均差",dm,mp-mpp if mp is not None and mpp is not None else None)
        check(origin+":保存位置差",dp,cj-mp if mp is not None else None)
        check(origin+":平均準備",row["SMA準備"],dm is not None and dp is not None)
        check(origin+":平均進行符号",row["SMA進行符号"],sign(dm))
        check(origin+":平均位置符号",row["SMA位置符号"],sign(dp))
        if row["SMA準備"]:
            check(origin+":過去21本",row["SMA過去足数"],21)
            check(origin+":前平均20本",len(row["SMA前20足番号"]),20)
            check(origin+":前々平均20本",len(row["SMA前々20足番号"]),20)
            check(origin+":当足除外",max(row["SMA前20足番号"]) < row["index"] and max(row["SMA前々20足番号"]) < prior["index"],True)
            check(origin+":最遅公開key",row["SMA最遅公開key"],[prior["confirm"],prior["confirm_line"]])
        classification = "未準備" if not row["SMA準備"] else "T" if side*dm > 0 and side*dp > 0 else "R" if side*dm < 0 and side*dp < 0 else "WAIT"
        role = "順行" if classification == "T" else "反転" if classification == "R" else None
        check(origin+":分類",row["B2判別種別"],classification)
        check(origin+":B2役割",row["B2役割"],role)
        check(origin+":共通準備",row["共通M準備"],not row["M除外理由"])
        for policy in POLICIES:
            accepted = bool(row["共通M準備"] and row["時間条件可"] and row["確認遅延条件可"] and change is not None and side*change > 0 and (policy == "B0" or row["SMA準備"]) and (policy != "B2" or role is not None) and not row["戦略判定"][policy]["同時競合"])
            check(origin+policy+":採否",row["戦略判定"][policy]["採用"],accepted)
            check(origin+policy+":純集合",origin in by_policy[policy],accepted)
            if accepted:
                current,base = by_policy[policy][origin],by_policy["B0"][origin]
                for field in (*PURE_FIELDS,*META_FIELDS,*LABEL_FIELDS,"期間"):
                    check(origin+policy+":同P属性:"+field,current[field],base[field])
                check(origin+policy+":実役割",current["役割"],role if policy == "B2" else "反転")
                check(origin+policy+":元side保持",current["side"],side)
                for field in META_FIELDS:
                    check(origin+policy+":元判断:"+field,current[field],row[field])

    # ----------------------------------------
    # 二実体母集団、平均の準備と値、日夜/買売/役割と位置を分ける。
    stages,subsets,sign_groups,composition,positions = [],[],[],[],[]
    for period in PERIODS:
        raw = [r for r in decisions if r["期間"] == period]
        stages.append({"期間":period,"数値足数":sum(r["期間"] == period for r in numeric),"原P数":len(raw),"共通M準備数":sum(r["共通M準備"] for r in raw),"M時間遅延可数":sum(r["共通M準備"] and r["時間条件可"] and r["確認遅延条件可"] for r in raw),"先着対象外P数":sum(not r["先着評価対象"] for r in raw),"B2分類別":dict(Counter(r["B2判別種別"] for r in raw)),**{p+"純入口数":sum(r["戦略判定"][p]["採用"] for r in raw) for p in POLICIES}})
        for title,left_id,right_id in PAIRS:
            lp,rp = left_id.split("_")[1],right_id.split("_")[1]
            left = {k:v for k,v in by_policy[lp].items() if v["期間"] == period}
            right = {k:v for k,v in by_policy[rp].items() if v["期間"] == period}
            retained,removed = left.keys() & right.keys(),left.keys()-right.keys()
            subsets.append({"期間":period,"比較":title,"左入口":lp,"右入口":rp,"保持入口":entry_summary([left[k] for k in retained]),"除外入口":entry_summary([left[k] for k in removed]),"新規追加入口数":len(right.keys()-left.keys()),"保持内役割変更数":sum(left[k]["役割"] != right[k]["役割"] for k in retained),"除外分類別":dict(Counter(raw_map[k]["B2判別種別"] for k in removed))})
        for sm in (-1,0,1):
            for sp in (-1,0,1):
                selected = [r for r in raw if r["戦略判定"]["B1"]["採用"] and r["side"]*r["SMA進行符号"] == sm and r["side"]*r["SMA位置符号"] == sp]
                sign_groups.append({"期間":period,"実方向平均進行":sm,"実方向終値位置":sp,"分類":"T" if sm == sp == 1 else "R" if sm == sp == -1 else "WAIT",**entry_summary([by_policy["B1"][r["発動ID"]] for r in selected])})
        for daynight in ("デイ","ナイト"):
            for direction in ("買い","売り"):
                own = [r for r in raw if ("デイ" if r["場"].endswith("_Day") else "ナイト") == daynight and r["方向"] == direction]
                composition.append({"期間":period,"日夜":daynight,"方向":direction,"原P数":len(own),**{p+"純入口数":sum(r["戦略判定"][p]["採用"] for r in own) for p in POLICIES},"B2分類別":dict(Counter(r["B2判別種別"] for r in own))})
        for policy in POLICIES:
            for role in ACTIVE_ROLES[policy]:
                own = [r for r in cases if r["期間"] == period and r["入口ID"] == "3分_"+policy and r["役割"] == role]
                source = [(r,raw_map[r["元価格発動ID"]]) for r in own]
                close_position = [float(r["side"]*(fraction(d["SMA前"])-Fraction(d["close"]))) for r,d in source if d["SMA前"]["有効"]]
                fill_position = [float(r["side"]*(fraction(d["SMA前"])-Fraction(r["新規価格"]))) for r,d in source if d["SMA前"]["有効"] and r["新規価格"] is not None]
                previous_extreme = [d["前3分参照"]["high"]-d["close"] if r["side"] == 1 else d["close"]-d["前3分参照"]["low"] for r,d in source]
                positions.append({"期間":period,"入口":policy,"役割":role,"純要求数":len(own),"現実体絶対長pt":H.distribution([abs(float(fraction(d["現実体"]))) for _,d in source]),"前実体絶対長pt":H.distribution([abs(float(fraction(d["前実体"]))) for _,d in source]),"要求終値から前SMA実方向距離pt":H.distribution(close_position),"仮新規から前SMA実方向距離pt":H.distribution(fill_position),"要求終値から前足実方向端までpt":H.distribution(previous_extreme)})

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
        for title,left_id,right_id in PAIRS:
            left,right = ({economic_identity(t):t for t in own[cid]} for cid in (left_id,right_id))
            common,removed,added = left.keys() & right.keys(),left.keys()-right.keys(),right.keys()-left.keys()
            costs = []
            for fee in (0,5,10):
                field = f"追加滑り{fee}pt純損益円"
                diff = sum(right[k][field]-left[k][field] for k in common)
                total = H.cash(own[right_id],fee)-H.cash(own[left_id],fee)
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
            participation.append({"期間":period,"比較":title,"左":left_id,"右":right_id,"経済的共通実新規数":len(common),"同役割共通数":same_role,"役割だけ違う共通数":len(common)-same_role,"共通出口属性差数":exit_diff,"同P両実参加数":len({case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[left_id]} & {case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[right_id]}),"左のみ":H.operation_summary([left[k] for k in removed]),"右のみ":H.operation_summary([right[k] for k in added]),"左のみの相手取扱":counterpart([left[k] for k in removed],right_id),"右のみの相手取扱":counterpart([right[k] for k in added],left_id),"費用別":costs})
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
        check("三運用順",[r["候補ID"] for r in result["結果"]],list(CANDIDATES))
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
    return {"全件一致":not errors,"照合項目数":checks,"不一致数":len(errors),"不一致":errors,"モデル再計算":False,"指標再計算":False,"先着再計算":False,"運用再生":False,"新閾値選別":False,"新価格母集団":True,"旧完全対照なし":True,"価格と平均の段階":stages,"入口追加比較":subsets,"B1の進行と位置区分":sign_groups,"日夜と買売構成":composition,"診断専用の位置":positions,"実参加比較":participation,"共通新規の役割対応":role_links,"候補別回収":recovery,"役割別回収":role_recovery,"品質と確定額":qualities,"実役割群数":4,"責任分界":"保存27列/前足参照/二実体差/SMA精密値の内部算術と集合だけ。原8列からの新P/局所窓/全SMA/ATR/H/全採否と新先着は46状態、全保有/最初要求は追尾、Decimal/CSV/Viewerは財務。旧入口/旧label/旧運用の完全対照なし。","限界":["全NK66既使用の新母集団。重なる二足/21終値を独立標本としない。","B0/B1反転からB2順行への役割名変更を独立機会や出口の効果としない。経済的新規対応と役割対応を分ける。","純subsetでも実一建玉の占有変化で追加参加が起こり得る。実観測数を別記する。","要求終値から平均/前足端への距離は未約定を含む純要求、仮新規距離はその仮約定だけ。負距離を丸めず閾値へ戻さない。","古終値脱落を含むSMA進行を注文圧力とせず、実体/MACD/SMAを独立三票としない。","起動後基準赤字は追加0pt手数料込み。起動参照5pt122円や追加5pt損益とは別尺度。"]}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式許可後に保存五系列だけを一度集計する。

    引数: study/work(Path)は46保存先。
    返り値: dictは小型診断。市場/数値/先着/運用を起動しない。
    """
    if not (study/"結果.json").is_file():raise ValueError("正式結果完成前に保存診断を起動しません")
    if (work/"対応診断.json").exists():raise ValueError("既存の正式保存診断を上書きしません")
    numeric,decisions,cases,details,_ = (H.read(work/n) for n in FILES)
    output = analyze(cases,decisions,numeric,details,H.read(study/"結果.json"))
    paths = [Path(__file__),HELPER,ROOT/"scripts/量比反転/対応診断.py",ROOT/"scripts/終値位置/対応診断.py",ROOT/"scripts/SAR追尾/対応診断.py",*[study/n for n in ("計画.md","条件.json","固定.json","結果.json","入力台帳.json","指標参照.json")],work/"診断予定.json",*[work/n for n in FILES]]
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix():H.sha(p) for p in dict.fromkeys(paths)}
    output["参照SHA256"] = {n:H.sha(study/n) for n in ("結果.json","指標参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    if not output["全件一致"]:raise RuntimeError("二実体/平均の保存診断に不一致")
    return output


def main() -> None:
    """正式許可後の保存診断を担当一人で一回だけ起動する。

    引数: なし。--study/--workはPath。
    返り値: None。市場/先着/運用再生は呼ばない。
    """
    parser = argparse.ArgumentParser(description="二実体と前平均の保存診断")
    parser.add_argument("--study",type=Path,default=STUDY)
    parser.add_argument("--work",type=Path,default=WORK)
    args = parser.parse_args()
    output = run(args.study.resolve(),args.work.resolve())
    print(H.json.dumps({k:output[k] for k in ("全件一致","照合項目数","不一致数")},ensure_ascii=False))


if __name__ == "__main__":main()
