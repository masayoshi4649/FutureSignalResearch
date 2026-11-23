"""新終値突破の回帰方向と直線性を、全P・実参加・回収へ分ける。"""

import argparse
from collections import Counter
import importlib.util
import math
from fractions import Fraction
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00041_終値突破と回帰の方向と直線性"
WORK = ROOT/"work/回帰突破/00041"
HELPER = ROOT/"scripts/構造判別/対応診断.py"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("L0", "L1", "L2")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
PAIRS = (("R2定義追加", CANDIDATES[0], CANDIDATES[1]),
    ("R2半分選別追加", CANDIDATES[1], CANDIDATES[2]))
SOURCE_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing",
    "open", "high", "low", "close")
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr", "macd_hist")

spec = importlib.util.spec_from_file_location("回帰41の固定37保存集計", HELPER)
F = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = F
spec.loader.exec_module(F)
H, entry_summary = F.H, F.entry_summary
PURE_FIELDS, LABEL_FIELDS = F.PURE_FIELDS, F.LABEL_FIELDS


def finite(value: object) -> bool:
    """足/ATR保存値が有限の数値か検査する。

    引数: value(object)は保存された末端値。
    返り値: boolは真偽値・欠測を除く有限性。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def exact(value: Fraction | None) -> dict:
    """保存定義の分数を表示値と既約分子/分母へ写す。

    引数: value(Fraction|None)は精密値又は未準備。
    返り値: dictは値/分子/分母/有効。欠測を0にしない。
    """
    return {"値": None if value is None else float(value), "分子": None if value is None else value.numerator,
        "分母": None if value is None else value.denominator, "有効": value is not None}


def fraction(value: dict) -> Fraction | None:
    """保存済みの精密欄を有理数へ読む。

    引数: value(dict)は値/分子/分母/有効の保存欄。
    返り値: Fraction|Noneは保存された数値。価格窓や回帰を再計算しない。
    """
    return Fraction(value["分子"], value["分母"]) if value["有効"] else None


def direction_group(row: dict, mode: str) -> str:
    """保存された傾き又はヒスト差を実方向で四区分する。

    引数: row(dict)は新原P、mode(str)は傾き/MACD。
    返り値: strは正/0/負/未準備。
    """
    value = row["OLS20"]["傾き符号"] if mode == "傾き" else row["MACDヒスト変化"]
    if not finite(value):
        return "未準備"
    signed = row["side"]*value
    return "正" if signed > 0 else "負" if signed < 0 else "0"


def r2_group(row: dict) -> str:
    """未定義と半分境界の三状態を別に記録する。

    引数: row(dict)は新原PのOLS20欄を含む。
    返り値: strは未定義/半分未満/半分等号/半分超。
    """
    sign = row["OLS20"]["R2半分比較符号"]
    return "未定義" if sign is None else "半分未満" if sign < 0 else "半分超" if sign > 0 else "半分等号"


def analyze(cases: list[dict], decisions: list[dict], details: list[dict],
            result: dict | None = None,
            numeric_rows: list[dict] | None = None) -> dict:
    """新終値突破の回帰方向と直線性選別を、実参加・出口・回収から分ける。

    引数: cases/decisions/details(list[dict])は41保存明細、result(dict|None)は結果、
    numeric_rows(list[dict]|None)は固定29全指標の共有保存値。
    返り値: dictは照合と小型記述集計。保存分数の内部算術だけ確認し、銀行/先着/運用を再計算しない。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """保存値を厳密照合し、大明細の不一致は指紋へ縮約する。

        引数: name(str)は項目、actual/expected(object)は比較値。
        返り値: None。末端値・属性を除外しない。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            compact = [v if len(H.json.dumps(v, ensure_ascii=False, default=str)) <= 1500 else
                {"内容SHA256": H.canonical(v)} for v in (actual, expected)]
            errors.append({"項目": name, "実値": compact[0], "期待値": compact[1]})

    by_policy = {p: {r["元価格発動ID"]: r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    case_map = {r["イベントID"]: r for r in cases}
    by_policy = {p: {r["元価格発動ID"]: r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    by_origin = {r["発動ID"]: r for r in decisions}
    check("全新P一意", len(by_origin), len(decisions))
    check("新case一意", len(case_map), len(cases))
    check("L1数学的冗長・純集合", set(by_policy["L1"]), set(by_policy["L0"]))
    check("L2はL1部分集合", set(by_policy["L2"]) <= set(by_policy["L1"]), True)
    frames = {} if numeric_rows is None else {(r["場"], r["index"]): r for r in numeric_rows if r["minutes"] == 3}
    preselected = Counter()
    technical = {}
    for origin, row in by_origin.items():
        reg, side = row["OLS20"], row["side"]
        check(origin+":実side表示", row["方向"], "買い" if side == 1 else "売り")
        check(origin+":新原P役割", row["役割"], "順行")
        check(origin+":終値strict突破", row["close"] > row["直前最高H"] if side == 1 else row["close"] < row["直前最安L"], True)
        check(origin+":前20窓数", len(row["前20足番号"]), 20)
        check(origin+":回帰当足含20窓", row["回帰20足番号"], row["前20足番号"][1:]+[row["index"]])
        check(origin+":回帰20点準備", (reg["回帰準備"], reg["回帰点数"], reg["Dxx"]), (True, 20, 13300))
        for field in ("Dxy", "Dyy", "傾き", "切片", "全平方和", "残差平方和", "R2", "R2半分差"):
            check(origin+":保存分数表記:"+field, reg[field], exact(fraction(reg[field])))
        dxy, dyy = fraction(reg["Dxy"]), fraction(reg["Dyy"])
        slope = dxy/13300
        r2 = dxy*dxy/(13300*dyy) if dyy > 0 else None
        half = None if r2 is None else r2-Fraction(1, 2)
        for field, value in (("傾き", slope), ("全平方和", dyy/20),
                ("残差平方和", (dyy-dxy*dxy/13300)/20), ("R2", r2), ("R2半分差", half)):
            check(origin+":保存D値の内部算術:"+field, reg[field], exact(value))
        check(origin+":R2定義", reg["R2準備"], r2 is not None)
        check(origin+":傾き符号", reg["傾き符号"], (slope > 0)-(slope < 0))
        check(origin+":半分符号", reg["R2半分比較符号"], None if half is None else (half > 0)-(half < 0))
        if numeric_rows is not None:
            current = frames[row["場"], row["index"]]
            check(origin+":現15列正本", {k: row[k] for k in FRAME_FIELDS}, {k: current[k] for k in FRAME_FIELDS})
            previous = frames[row["場"], row["前20足番号"][-1]]
            check(origin+":前3分正本", row["前3分参照"], {k: previous[k] for k in FRAME_FIELDS})
            check(origin+":保存ヒスト差だけの算術", row["MACDヒスト変化"], current["macd_hist"]-previous["macd_hist"]
                if finite(current["macd_hist"]) and finite(previous["macd_hist"]) else None)
        base = bool(row["共通M準備"] and row["時間条件可"] and row["確認遅延条件可"] and
            direction_group(row, "傾き") == "正" and direction_group(row, "MACD") == "正")
        flags = {"L0": base, "L1": base and reg["R2準備"],
            "L2": base and reg["R2準備"] and reg["R2半分比較符号"] in (0, 1)}
        if base:
            check(origin+":strict傾きならR2定義", reg["R2準備"], True)
        for policy, value in flags.items():
            technical[origin, policy] = value
            if value:
                preselected[policy, row["場"], row["要求時計秒"], row["要求原板行"]] += 1
    for origin, row in by_origin.items():
        for policy in POLICIES:
            verdict = row["戦略判定"][policy]
            competing = technical[origin, policy] and preselected[policy, row["場"], row["要求時計秒"], row["要求原板行"]] > 1
            check(origin+policy+":同方向複数も全見送り", verdict["同時競合"], competing)
            check(origin+policy+":技術時間採否", verdict["採用"], technical[origin, policy] and not competing)
            check(origin+policy+":保存case集合", origin in by_policy[policy], verdict["採用"])
            if origin not in by_policy[policy]:
                continue
            case, base = by_policy[policy][origin], by_policy["L0"][origin]
            check(origin+policy+":新識別子", case["イベントID"], origin+"_"+policy)
            for field in (*PURE_FIELDS, "期間", "元価格side"):
                check(origin+policy+":原Pの現在値:"+field, case[field], row["side"] if field == "元価格side" else row.get(field))
            for field in (*PURE_FIELDS, *LABEL_FIELDS, "期間", "元価格side"):
                check(origin+policy+":同時計新先着の保持:"+field, case[field], base[field])

    # ----------------------------------------
    # 全新Pを残し、L0の準備確認とL1の半分選別を別分母にする。
    stages, classifications, subsets, definitions, r2_classes, descriptions = [], [], [], [], [], []
    for period in PERIODS:
        raw = [r for r in decisions if r["期間"] == period]
        stages.append({"期間": period, "新原P数": len(raw),
            "共通M準備数": sum(r["共通M準備"] for r in raw),
            "時間遅延可数": sum(r["時間条件可"] and r["確認遅延条件可"] for r in raw),
            "M時間遅延通過数": sum(r["共通M準備"] and r["時間条件可"] and r["確認遅延条件可"] for r in raw),
            **{p+"純入口数": sum(r["期間"] == period for r in by_policy[p].values()) for p in POLICIES},
            "候補別競合数": {p: sum(r["戦略判定"][p]["同時競合"] for r in raw) for p in POLICIES}})
        for slope in ("正", "0", "負", "未準備"):
            for momentum in ("正", "0", "負", "未準備"):
                own = [r for r in raw if direction_group(r, "傾き") == slope and direction_group(r, "MACD") == momentum]
                classifications.append({"期間": period, "実方向傾き": slope, "実方向ヒスト差": momentum,
                    "新原P数": len(own), "M時間可数": sum(r["共通M準備"] and r["時間条件可"] and r["確認遅延条件可"] for r in own),
                    **{p+"採用数": sum(r["戦略判定"][p]["採用"] for r in own) for p in POLICIES}})
        for title, left_id, right_id in PAIRS:
            lp, rp = left_id.split("_")[1], right_id.split("_")[1]
            left = {k:r for k,r in by_policy[lp].items() if r["期間"] == period}
            right = {k:r for k,r in by_policy[rp].items() if r["期間"] == period}
            subsets.append({"期間": period, "比較": title, "左入口": lp, "右入口": rp,
                "保持入口": entry_summary([left[k] for k in left.keys() & right.keys()]),
                "除外入口": entry_summary([left[k] for k in left.keys()-right.keys()]), "新規追加入口数": len(right.keys()-left.keys())})
        for ready in (True, False):
            own = [r for r in raw if r["戦略判定"]["L0"]["採用"] and r["OLS20"]["R2準備"] == ready]
            definitions.append({"期間": period, "分母": "L0純入口", "R2定義可能": ready,
                **entry_summary([by_policy["L0"][r["発動ID"]] for r in own])})
        for kind in ("未定義", "半分未満", "半分等号", "半分超"):
            own = [r for r in raw if r2_group(r) == kind]
            selected = [r for r in own if r["戦略判定"]["L1"]["採用"]]
            r2_classes.append({"期間": period, "R2区分": kind, "全新原P数": len(own), "分母": "L1純入口",
                **entry_summary([by_policy["L1"][r["発動ID"]] for r in selected])})
        for accepted in (True, False):
            own = [r for r in raw if r["戦略判定"]["L1"]["採用"] and r["戦略判定"]["L2"]["採用"] == accepted]
            descriptions.append({"期間": period, "分母": "L1純要求の当時値", "L2保持": accepted, "要求数": len(own),
                "R2": H.distribution([r["OLS20"]["R2"]["値"] for r in own]),
                "実方向傾きpt毎足": H.distribution([r["side"]*r["OLS20"]["傾き"]["値"] for r in own])})

    # ----------------------------------------
    # 純入口の部分集合と、一建玉で新たに参加できた実新規を分ける。
    trades = [{**t, "候補ID": d["候補ID"]} for d in details for t in d["取引"]]
    handling = {(d["候補ID"], s["イベントID"]): s["取扱"] for d in details for s in d["入口取扱"]}
    check("場候補一意", len({(d["候補ID"], d["場"]) for d in details}), len(details))
    for trade in trades:
        case = case_map[trade["入口イベントID"]]
        for field in ("新規時計秒", "新規原板行", "新規価格"):
            check("実新規と保存case:"+field, trade[field], case[field])
        check("実役割順行", trade["入口役割"], "順行")
        check("入口ATR保持", trade["入口ATR"], case["atr"])
    participation, recovery, qualities = [], [], []
    for period in PERIODS:
        own = {cid: [t for t in trades if t["候補ID"] == cid and t["期間"] == period] for cid in CANDIDATES}
        for cid in CANDIDATES:
            check(cid+period+":実新規一意", len({F.strict_identity(t) for t in own[cid]}), len(own[cid]))
        for title, left_id, right_id in PAIRS:
            left, right = ({F.strict_identity(t): t for t in own[cid]} for cid in (left_id, right_id))
            common, removed, added = left.keys() & right.keys(), left.keys()-right.keys(), right.keys()-left.keys()
            costs = []
            for fee in (0, 5, 10):
                field = f"追加滑り{fee}pt純損益円"
                difference = sum(right[k][field]-left[k][field] for k in common)
                removed_cash, added_cash = H.cash([left[k] for k in removed], fee), H.cash([right[k] for k in added], fee)
                total = H.cash(own[right_id], fee)-H.cash(own[left_id], fee)
                check(title+period+str(fee)+":全差分解", total, difference-removed_cash+added_cash)
                check(title+period+str(fee)+":共通XF費用差0", difference, 0)
                costs.append({"片道追加pt": fee, "総差円_右引く左": total, "共通出口差円": difference,
                    "左のみ損益円": removed_cash, "右のみ損益円": added_cash})

            def counterpart(rows: list[dict], cid: str) -> dict:
                """片側実参加の相手が純除外か、建玉・注文抑止かを区分する。

                引数: rows(list[dict])は片側完結、cid(str)は相手候補。
                返り値: dictは保存最終取扱数。取消時計を推定しない。
                """
                policy = cid.split("_")[1]
                values = []
                for trade in rows:
                    origin = case_map[trade["入口イベントID"]]["元価格発動ID"]
                    other = by_policy[policy].get(origin)
                    values.append("同元Pの純入口なし" if other is None else handling.get((cid, other["イベントID"]), "取扱記録なし"))
                return dict(Counter(values))

            exit_diff = sum(any(left[k][f] != right[k][f] for f in ("返済時計秒", "返済原板行", "返済価格", "返済理由")) for k in common)
            check(title+period+":共通XF出口属性同値", exit_diff, 0)
            left_origins = {case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[left_id]}
            right_origins = {case_map[t["入口イベントID"]]["元価格発動ID"] for t in own[right_id]}
            participation.append({"期間": period, "比較": title, "左": left_id, "右": right_id,
                "同元P両実参加数": len(left_origins & right_origins), "厳密共通実新規数": len(common),
                "共通出口属性差数": exit_diff, "左のみ": H.operation_summary([left[k] for k in removed]),
                "右のみ": H.operation_summary([right[k] for k in added]),
                "左のみの相手取扱": counterpart([left[k] for k in removed], right_id),
                "右のみの相手取扱": counterpart([right[k] for k in added], left_id), "費用別": costs})
        for cid in CANDIDATES:
            rows = own[cid]
            successes = [t for t in rows if case_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
            armed = [t for t in rows if t["追尾起動"]]
            reds = [t for t in armed if t["起動後純赤字"]]
            nominal = lambda t: (1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"])
            recovery.append({"候補ID": cid, "期間": period, **H.operation_summary(rows),
                "対応仮250数": len(successes), "仮250判定前返済数": sum((t["返済時計秒"], t["返済原板行"]) <
                    (case_map[t["入口イベントID"]]["判定時計秒"], case_map[t["入口イベントID"]]["判定原板行"]) for t in successes),
                "実保有MFE250数": sum(t["観測最大順行pt"] >= 250 for t in rows), "起動数": len(armed), "起動後基準赤字数": len(reds),
                "名目同値費用赤字数": sum(nominal(t) == 0 for t in reds), "不利返済赤字数": sum(nominal(t) < 0 for t in reds),
                "正名目利益の基準費用負け数": sum(nominal(t) > 0 for t in reds)})
    if result is not None:
        check("三運用順", [r["候補ID"] for r in result["結果"]], list(CANDIDATES))
        check("三入口順", [r["入口ID"] for r in result["入口評価"]], ["3分_"+p for p in POLICIES])
        check("順行三役割群", [(r["入口ID"], r["役割"]) for r in result["役割別入口評価"]], [("3分_"+p, "順行") for p in POLICIES])
        for source in (*result["入口評価"], *result["役割別入口評価"]):
            for period in PERIODS:
                summary = entry_summary([r for r in cases if r["入口ID"] == source["入口ID"] and r["期間"] == period])
                for field in ("候補数", "約定候補数", "順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "確認率"):
                    check(source["入口ID"]+period+field, source[period][field], summary[field])
        for row in result["結果"]:
            for period in PERIODS:
                op, own = row[period]["運用"], [t for t in trades if t["候補ID"] == row["候補ID"] and t["期間"] == period]
                check(row["候補ID"]+period+":完結数", op["完結取引数"], len(own))
                for fee in (0, 5, 10):
                    check(row["候補ID"]+period+str(fee)+":保存会計", op[f"追加{fee}pt純損益円"], H.cash(own, fee))
                qualities.append({"候補ID": row["候補ID"], "期間": period,
                    **{k: op[k] for k in ("品質注意場数", "未解消場数", "EOF期限未達場数")},
                    "観測純額円": {str(f): op[f"追加{f}pt純損益円"] for f in (0, 5, 10)},
                    "全体確定対象円": {str(f): op[f"追加{f}pt確定対象円"] for f in (0, 5, 10)}})
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "モデル再計算": False, "指標再計算": False, "先着再計算": False, "運用再生": False, "新閾値選別": False,
        "保存分数と差の算術照合": True, "新母集団": True, "旧対照使用": False, "旧label流用": False,
        "全新Pと三入口": stages, "方向と勢い全区分": classifications, "入口追加比較": subsets,
        "L0のR2定義区分": definitions, "R2半分区分": r2_classes, "保持除外の回帰記述": descriptions,
        "実参加比較": participation, "候補別回収": recovery, "品質と確定額": qualities,
        "責任分界": {"固定29": "共有3分ATR/中心化MACD/原OHLCと銀行の正本",
            "新41": "新終値P/OLS/全L採否/新case直接先着/実運用の正式proof",
            "保存診断": "保存D値の内部算術/出典/全P採否/同時計先着対応/実参加と回収。回帰窓や数値銀行を再計算しない"},
        "限界": ["L0は新母集団の基準。旧40との差をR2単独の効果とせず、旧全属性対照や旧labelを使わない。",
            "L1はstrict傾きから数学的に冗長。R2半分は標本内直線性で未来確率や有意水準ではない。",
            "純subsetでも実参加差は別。共通出口差と片側取引額を全費用で分ける。",
            "全66場既使用。重複窓を独立票や独立標本へ増幅しない。",
            "仮250は実返済後も追う反事実。実保有MFE/回収/名目床/費用資格を分ける。"]}



def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式完了後に新四明細と固定29数値だけを読取診断する。

    引数: study/work(Path)は41正式/作業先。
    返り値: dictは小型診断。rootの正式完了通知前は起動しない。
    """
    if not (study/"結果.json").is_file():
        raise ValueError("正式結果完成前に保存診断を実行しません")
    reference = H.read(study/"指標参照.json")
    shared = {Path(r["パス"]).name: ROOT/r["パス"] for r in reference["共有明細"]}
    for item in reference["共有明細"]:
        if H.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
            raise ValueError("共有数値の参照版差")
    decisions, cases, details, trace = (H.read(work/n) for n in ("回帰判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz"))
    output = analyze(cases, decisions, details, H.read(study/"結果.json"), numeric_rows=H.read(shared["全指標.jsonl.gz"]))
    # 同一試行内の冗長対照だけを比較し、旧40との完全同値対照は作らない。
    base = {d["場"]:d for d in details if d["候補ID"] == CANDIDATES[0]}
    redundant = {d["場"]:d for d in details if d["候補ID"] == CANDIDATES[1]}
    comparisons = []
    for scene in sorted(base.keys() | redundant.keys()):
        left = base.get(scene)
        right = F.rename(redundant.get(scene), "_L1", "_L0")
        left_trace = [r for r in trace if r["候補ID"] == CANDIDATES[0] and r["場"] == scene]
        right_trace = [F.rename(r, "_L1", "_L0") for r in trace if r["候補ID"] == CANDIDATES[1] and r["場"] == scene]
        comparisons.append({"場":scene, "全運用同値":left == right, "全追尾同値":left_trace == right_trace})
        for label, okay in (("L0L1全運用",left == right),("L0L1全追尾",left_trace == right_trace)):
            output["照合項目数"] += 1
            if not okay:
                output["不一致"].append({"項目":scene+label,"実値":False,"期待値":True})
    output["同一試行L0L1属性比較"] = comparisons
    output["不一致数"] = len(output["不一致"])
    output["全件一致"] = not output["不一致"]
    paths = [Path(__file__), HELPER, ROOT/"scripts/量比反転/対応診断.py", ROOT/"scripts/終値位置/対応診断.py", ROOT/"scripts/SAR追尾/対応診断.py",
        *[study/n for n in ("条件.json", "固定.json", "結果.json", "入力台帳.json", "指標参照.json")],
        *[work/n for n in ("診断予定.json", "回帰判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")], *shared.values()]
    output["全66場既使用"] = True
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix(): H.sha(p) for p in dict.fromkeys(paths)}
    output["参照SHA256"] = {n:H.sha(study/n) for n in ("結果.json", "指標参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if not output["全件一致"]:
        raise RuntimeError("回帰突破の保存対応に不一致")
    return output


def main() -> None:
    """保存明細だけの後段診断をCLIで起動する。

    引数: なし。--study/--workはPath。
    返り値: None。市場・指標・先着・運用を起動しない。
    """
    parser = argparse.ArgumentParser(description="新終値突破と回帰方向/直線性の保存対応診断")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    output = run(args.study.resolve(), args.work.resolve())
    print(H.json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
