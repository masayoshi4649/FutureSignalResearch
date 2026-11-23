"""新しい登録/最初再テスト/CMF三案を、保存明細だけで対応診断する。"""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00042_突破再テストと数量加重終値位置"
WORK = ROOT/"work/再テスト量方向/00042"
HELPER = ROOT/"scripts/構造判別/対応診断.py"
SPEC = importlib.util.spec_from_file_location("再テスト42の固定保存集計", HELPER)
F = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = F
SPEC.loader.exec_module(F)
H, entry_summary = F.H, F.entry_summary
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("A0", "A1", "A2")
ROLES = ("順行", "反転")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
PAIRS = (("CMF準備追加", CANDIDATES[0], CANDIDATES[1]), ("CMF方向追加", CANDIDATES[1], CANDIDATES[2]))
PURE_FIELDS = ("場", "役割", "side", "方向", "要求時計秒", "要求原板行", "確認遅延秒", "low", "high", "atr", "bb_mean")
LABEL_FIELDS = ("ラベル", "理由", "新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")
FILES = ("登録監視.jsonl.gz", "発動判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")
TERMINALS = ("監視取消", "監視満了", "反対端終値取消", "再テスト消費", "場末監視取消")


def finite(value: object) -> bool:
    """欠測と非有限を除いて保存数値の有効性を調べる。

    引数: value(object)は保存値。
    返り値: boolは有限数値であり真偽値でないこと。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fraction(value: dict) -> Fraction | None:
    """保存された精密欄を分数へ復元する。

    引数: value(dict)は値/分子/分母/有効。
    返り値: Fraction|Noneは定義済み分数又は未定義。窓は再計算しない。
    """
    return Fraction(value["分子"], value["分母"]) if value["有効"] else None


def exact(value: Fraction | None) -> dict:
    """分数の規約通りの保存形を内部算術照合用に作る。

    引数: value(Fraction|None)は保存値由来の分数。
    返り値: dictは精密欄と表示値。未定義を0へ補完しない。
    """
    return {"値": float(value) if value is not None else None,
        "分子": value.numerator if value is not None else None,
        "分母": value.denominator if value is not None else None, "有効": value is not None}


def signed_group(value: Fraction | float | int | None, side: int | None) -> str:
    """保存値を実注文方向の正/0/負へ分類する。

    引数: value(Fraction|float|int|None)は保存値、side(int|None)は実方向。
    返り値: strは正/0/負/未定義。WAITに仮のsideを付けない。
    """
    if value is None or side not in (-1, 1):
        return "未定義"
    return "正" if side*value > 0 else "負" if side*value < 0 else "0"


def analyze(cases: list[dict], decisions: list[dict], monitor: list[dict], details: list[dict], result: dict | None = None) -> dict:
    """全登録から最初j、数量準備/値、実参加と回収を保存値で分離する。

    引数: cases/decisions/monitor/details(list[dict])は五系列の保存値、result(dict|None)は正式集計。
    返り値: dictは小型診断。市場/CMF窓/先着/運用は再計算しない。
    """
    errors, checks = [], 0

    def check(label: str, actual: object, expected: object) -> None:
        """保存対応・集合・分数内部算術の一致を一項目記録する。

        引数: label(str)は項目、actual/expected(object)は比較値。
        返り値: None。不一致を例外で隠さず一覧へ追加する。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            errors.append({"項目": label, "実値": actual, "期待値": expected})

    raw_map = {r["発動ID"]: r for r in decisions}
    case_map = {r["イベントID"]: r for r in cases}
    by_policy = {p: {r["元価格発動ID"]: r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    check("jID一意", len(raw_map), len(decisions))
    check("caseID一意", len(case_map), len(cases))
    check("A1subsetA0", set(by_policy["A1"]) <= set(by_policy["A0"]), True)
    check("A2subsetA1", set(by_policy["A2"]) <= set(by_policy["A1"]), True)

    # ----------------------------------------
    # 親は正式traceの登録行から辿り、数量不成立で取り直さないことを対応照合する。
    registrations, terminals, actions = {}, defaultdict(list), []
    previous, used_count = {}, Counter()
    for row in monitor:
        scene = row["場"]
        check(scene+str(row["index"])+":監視連鎖", row["監視前"], previous.get(scene))
        for action in row["動作"]:
            item = {"期間": row["期間"], "場": scene, "index": row["index"], **action}
            actions.append(item)
            rid = action.get("登録ID")
            if action["動作"] == "突破登録":
                parent = action.get("登録参照")
                check(rid+":登録snapshotあり", parent is not None, True)
                if parent is not None:
                    check(rid+":親ID", parent["登録ID"], rid)
                    check(rid+":登録足出典", parent["登録足"], row["足出典"])
                    check(rid+":元方向", parent["元価格side"], action["元価格side"])
                    check(rid+":B固定", parent["固定境界B"], action["固定境界B"])
                    registrations[rid] = {"期間": row["期間"], **parent}
                used_count[scene] += 1
            if action["動作"] in TERMINALS:
                terminals[rid].append(item)
        check(scene+str(row["index"])+":used件数", row["使用済み水準数"], used_count[scene])
        previous[scene] = row["監視後"]
    check("全場監視終了", all(v is None for v in previous.values()), True)
    check("親登録ID一意", len(registrations), sum(a["動作"] == "突破登録" for a in actions))
    for rid, parent in registrations.items():
        check(rid+":一回終了", len(terminals[rid]), 1)
        frame, side = parent["登録足"], parent["元価格side"]
        check(rid+":R>L", parent["旧R"] > parent["旧L"], True)
        check(rid+":固定B", parent["固定境界B"], parent["旧R"] if side == 1 else parent["旧L"])
        check(rid+":b終値突破", side*(frame["close"]-parent["固定境界B"]) > 0, True)
        check(rid+":旧20足", len(parent["旧20足番号"]), 20)
        check(rid+":現在を旧窓に入れない", all(i < frame["index"] for i in parent["旧20足番号"]), True)
    check("未登録親の終了なし", set(terminals) <= set(registrations), True)
    check("同場used水準を再受理しない", len({(p["登録足"]["場"],p["元価格side"],p["固定境界B"]) for p in registrations.values()}), len(registrations))
    consumed = {a["発動ID"]: a for a in actions if a["動作"] == "再テスト消費"}
    check("消費j全集合", set(consumed), set(raw_map))
    check("親からj一回", len({r["登録ID"] for r in decisions}), len(decisions))

    for row in decisions:
        origin, rid, side = row["発動ID"], row["登録ID"], row["side"]
        parent = registrations[rid]
        b, s, boundary = parent["登録足"], parent["元価格side"], parent["固定境界B"]
        check(origin+":親固定出典", row["登録参照"], {k:v for k,v in parent.items() if k != "期間"})
        check(origin+":同場", row["場"], b["場"])
        check(origin+":対象startstrict", row["start"] > b["confirm"], True)
        check(origin+":対象keystrict", (row["confirm"], row["confirm_line"]) > (b["confirm"], b["confirm_line"]), True)
        check(origin+":寿命", 1 <= row["年齢"] <= 6, True)
        check(origin+":年齢", row["年齢"], row["index"]-b["index"])
        check(origin+":初touch", row["low"] <= boundary if s == 1 else row["high"] >= boundary, True)
        check(origin+":反対端取消優先", row["close"] > parent["旧L"] if s == 1 else row["close"] < parent["旧R"], True)
        kind = "T" if s*(row["close"]-boundary) > 0 else "R" if parent["旧L"] < row["close"] < parent["旧R"] else "WAIT"
        check(origin+":構造", row["構造区分"], kind)
        check(origin+":実side", side, s if kind == "T" else -s if kind == "R" else None)
        check(origin+":実役割", row["役割"], "順行" if kind == "T" else "反転" if kind == "R" else "待機")
        check(origin+":j要求key", (row["要求時計秒"], row["要求原板行"]), (row["confirm"], row["confirm_line"]))
        check(origin+":消費親", consumed[origin]["登録ID"], rid)
        for field in ("CLV現", "観測量合計", "加重CLV合計", "単位量CLV平均", "CMF21"):
            check(origin+":精密保存:"+field, row[field], exact(fraction(row[field])))
        total, weighted, cmf = (fraction(row[k]) for k in ("観測量合計", "加重CLV合計", "CMF21"))
        check(origin+":CMF準備", row["CMF準備"], len(row["CMF窓足番号"]) == 21 and total is not None and total > 0)
        check(origin+":加重比算術", cmf, weighted/total if row["CMF準備"] else None)
        check(origin+":CMF符号", row["CMF符号"], (cmf > 0)-(cmf < 0) if cmf is not None else None)
        check(origin+":CMF範囲", cmf is None or -1 <= cmf <= 1, True)
        if row.get("CMF全量正同値"):
            check(origin+":等量十分条件", cmf, fraction(row["単位量CLV平均"]))
        prev = row["前3分参照"]
        delta = row["macd_hist"]-prev["macd_hist"] if prev is not None and finite(row["macd_hist"]) and finite(prev["macd_hist"]) else None
        check(origin+":保存hist差", row["MACDヒスト変化"], delta)
        base = row["共通M準備"] and row["時間条件可"] and row["確認遅延条件可"] and side in (-1, 1) and finite(delta) and side*delta > 0
        for policy in POLICIES:
            wanted = base and (policy == "A0" or row["CMF準備"]) and (policy != "A2" or row["CMF符号"] is not None and side*row["CMF符号"] > 0)
            wanted = wanted and not row["戦略判定"][policy]["同時競合"]
            check(origin+policy+":採否", row["戦略判定"][policy]["採用"], wanted)
            check(origin+policy+":純集合", origin in by_policy[policy], wanted)
            if wanted:
                case = by_policy[policy][origin]
                check(origin+policy+":親metadata", [case[k] for k in ("元登録ID", "元価格side", "元登録時計秒", "元登録原板行", "判別種別")], [rid, s, b["confirm"], b["confirm_line"], kind])
                for field in PURE_FIELDS:
                    check(origin+policy+":純値:"+field, case[field], row[field])
                for field in (*PURE_FIELDS, *LABEL_FIELDS):
                    check(origin+policy+":同j新先着:"+field, case[field], by_policy["A0"][origin][field])

    # ----------------------------------------
    # 登録/消費、構造、数量準備、数量値は別分母の小表へまとめる。
    monitor_summary, stages, subsets, cmf_classes, equal_volume, waiting = [], [], [], [], [], []
    for period in PERIODS:
        local_actions = [a for a in actions if a["期間"] == period]
        parents = [p for p in registrations.values() if p["期間"] == period]
        raw = [r for r in decisions if r["期間"] == period]
        monitor_summary.append({"期間":period, "監視足数":sum(r["期間"] == period for r in monitor), "登録候補数":sum(a["動作"] in ("突破登録", "突破登録見送り") for a in local_actions), "登録受理数":len(parents),
            "動作別":dict(Counter(a["動作"] for a in local_actions)), "見送り理由別_重複あり":dict(Counter(v for a in local_actions if a["動作"] == "突破登録見送り" for v in a.get("理由",[]))),
            "終了理由別_重複あり":dict(Counter(v for a in local_actions if a["動作"] in TERMINALS for v in a.get("理由",[]))), "最初j数":len(raw)})
        for kind in ("T", "R", "WAIT"):
            own = [r for r in raw if r["構造区分"] == kind]
            stages.append({"期間":period,"構造区分":kind,"最初j数":len(own),"M準備数":sum(r["共通M準備"] for r in own),"時間遅延可数":sum(r["時間条件可"] and r["確認遅延条件可"] for r in own),
                **{p+"純入口数":sum(r["戦略判定"][p]["採用"] for r in own) for p in POLICIES}})
            waiting.append({"期間":period,"構造区分":kind,"最初j数":len(own),"bからj秒":H.distribution([r["confirm"]-r["登録参照"]["登録足"]["confirm"] for r in own]),
                "経過足数":H.distribution([r["年齢"] for r in own]),"元s方向終値差pt":H.distribution([r["元価格side"]*(r["close"]-r["登録参照"]["登録足"]["close"]) for r in own])})
        for role in ("全体", *ROLES):
            eligible = [r for r in raw if role == "全体" or r["役割"] == role]
            for title, left_id, right_id in PAIRS:
                lp, rp = left_id.split("_")[1], right_id.split("_")[1]
                left = {r["発動ID"]: by_policy[lp][r["発動ID"]] for r in eligible if r["戦略判定"][lp]["採用"]}
                right = {r["発動ID"]: by_policy[rp][r["発動ID"]] for r in eligible if r["戦略判定"][rp]["採用"]}
                removed = left.keys()-right.keys()
                subsets.append({"期間":period,"役割":role,"比較":title,"左入口":lp,"右入口":rp,"保持入口":entry_summary([left[k] for k in left.keys() & right.keys()]),
                    "除外入口":entry_summary([left[k] for k in removed]),"新規追加入口数":len(right.keys()-left.keys()),
                    "除外CMF理由別_重複あり":dict(Counter(reason for k in removed for field in ("CMF除外理由","CMF窓解除理由") for reason in raw_map[k].get(field,[]))) if title == "CMF準備追加" else {}})
            a1 = [r for r in eligible if r["戦略判定"]["A1"]["採用"]]
            for weighted_sign in ("正", "0", "負"):
                for unit_sign in ("正", "0", "負"):
                    own = [r for r in a1 if signed_group(fraction(r["CMF21"]),r["side"]) == weighted_sign and signed_group(fraction(r["単位量CLV平均"]),r["side"]) == unit_sign]
                    cmf_classes.append({"期間":period,"役割":role,"分母":"A1純要求","実量CMF実方向":weighted_sign,"単位量CLV実方向":unit_sign,
                        **entry_summary([by_policy["A1"][r["発動ID"]] for r in own])})
            equal_volume.append({"期間":period,"役割":role,"A1要求数":len(a1),"全21量正同値数":sum(r.get("CMF全量正同値") is True for r in a1),"等量旗未保存数":sum("CMF全量正同値" not in r for r in a1)})

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
    return {"全件一致":not errors,"照合項目数":checks,"不一致数":len(errors),"不一致":errors,"モデル再計算":False,"指標再計算":False,"先着再計算":False,"運用再生":False,"新閾値選別":False,"保存分数と差の算術照合":True,
        "新母集団":True,"旧対照使用":False,"旧label流用":False,"登録と監視":monitor_summary,"構造と三入口":stages,"入口追加比較":subsets,"CMFと単位量CLV符号":cmf_classes,"等量十分条件":equal_volume,"登録から消費の時計":waiting,
        "実参加比較":participation,"役割別実参加比較":role_participation,"候補別回収":recovery,"役割別回収":role_recovery,"品質と確定額":qualities,
        "責任分界":{"固定29":"共有OHLC/ATR/中心化MACD/数量参照の出典","新42":"登録一監視/最初対象j/精密CMF/全採否/新case直接先着/全XFの正式proof","保存診断":"trace登録/終了とj/case/運用の対応・保存加重和/総量の内部算術のみ。CMF窓や旧数値銀行を再計算しない"},
        "限界":["A0は新母集団。旧41のcase/label/全運用対照を流用しない。","bからjの終値差は未計算のb仮約定価格差や待機の収益効果ではない。未発動親の250取り逃しは未検証。","全21q正同値はCMF=単位量CLV平均の十分条件で必要ではない。数量を真の売買側flowと呼ばない。","A0->A1は準備除外、A1->A2は同じjの符号選別。混合率と役割別支持/回収を分ける。","純subsetでも実占有差は別。共通出口差と片側参加を全費用で分解し、共通0を出口改善としない。","全66場既使用。仮250は実返済後も追う経路で、MFE/実回収/名目床/費用資格と分ける。"]}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式完了後に保存五系列だけを一度読取診断する。

    引数: study/work(Path)は42正式/作業先。
    返り値: dictは小型診断。rootの正式通知前は起動しない。
    """
    if not (study/"結果.json").is_file():
        raise ValueError("正式結果完成前に保存診断を実行しません")
    reference=H.read(study/"指標参照.json")
    for item in reference["共有明細"]:
        if H.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
            raise ValueError("共有数値の参照版差")
    monitor,decisions,cases,details,_=(H.read(work/n) for n in FILES)
    output=analyze(cases,decisions,monitor,details,H.read(study/"結果.json"))
    paths=[Path(__file__),HELPER,ROOT/"scripts/量比反転/対応診断.py",ROOT/"scripts/終値位置/対応診断.py",ROOT/"scripts/SAR追尾/対応診断.py",
        *[study/n for n in ("条件.json","固定.json","結果.json","入力台帳.json","指標参照.json")],work/"診断予定.json",*[work/n for n in FILES],*[ROOT/r["パス"] for r in reference["共有明細"]]]
    output["全66場既使用"]=True
    output["ファイルSHA256"]={p.relative_to(ROOT).as_posix():H.sha(p) for p in dict.fromkeys(paths)}
    output["参照SHA256"]={n:H.sha(study/n) for n in ("結果.json","指標参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    if not output["全件一致"]:
        raise RuntimeError("再テスト量方向の保存対応に不一致")
    return output


def main() -> None:
    """保存明細だけの後段診断をCLIで起動する。

    引数: なし。--study/--workはPath。
    返り値: None。新相場/指標/先着/運用を起動しない。
    """
    parser=argparse.ArgumentParser(description="突破登録と最初再テスト/CMFの保存対応診断")
    parser.add_argument("--study",type=Path,default=STUDY)
    parser.add_argument("--work",type=Path,default=WORK)
    args=parser.parse_args()
    output=run(args.study.resolve(),args.work.resolve())
    print(H.json.dumps({k:output[k] for k in ("全件一致","照合項目数","不一致数")},ensure_ascii=False))


if __name__ == "__main__":
    main()
