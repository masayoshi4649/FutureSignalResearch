"""保存された帰還/外側/勢い判別を、方向・役割・混合占有へ分ける。"""

import argparse
from collections import Counter, defaultdict
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00037_高安帰還と外側継続の判別"
WORK = ROOT/"work/構造判別/00037"
HELPER = ROOT/"scripts/量比反転/対応診断.py"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("B0", "R1", "T1", "S1")
CANDIDATES = ("3分_B0_X0", "3分_B0_XF", "3分_R1_XF", "3分_T1_XF", "3分_S1_XF")
ROLE_PAIRS = (("B0", "反転"), ("R1", "反転"), ("T1", "順行"), ("S1", "反転"), ("S1", "順行"))
PAIRS = (("費用起動変更", CANDIDATES[0], CANDIDATES[1], None),
    ("帰還選別", CANDIDATES[1], CANDIDATES[2], None),
    ("混合反転占有", CANDIDATES[2], CANDIDATES[4], "反転"),
    ("混合順行占有", CANDIDATES[3], CANDIDATES[4], "順行"),
    ("混合全体", CANDIDATES[1], CANDIDATES[4], None))

spec = importlib.util.spec_from_file_location("構造37の固定36保存集計", HELPER)
F = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = F
spec.loader.exec_module(F)
H, entry_summary = F.H, F.entry_summary
PURE_FIELDS, LABEL_FIELDS = F.PURE_FIELDS, F.LABEL_FIELDS


def rename(value: object, old: str, new: str) -> object:
    """識別文字列だけを深い保存値まで対応させる。

    引数: value(object)は保存JSON、old/new(str)は識別片。
    返り値: objectは属性/数値を除外しない変換値。
    """
    if isinstance(value, dict):
        return {k: rename(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [rename(v, old, new) for v in value]
    return value.replace(old, new) if isinstance(value, str) else value


def exposure(trade: dict) -> tuple:
    """実side/key/価格/ATR/Dが同じ経済的な新規を識別する。

    引数: trade(dict)は保存完結取引。
    返り値: tupleは役割を含まない新規対応。
    """
    return (*H.identity(trade), trade["入口ATR"], trade["追尾距離pt"])


def strict_identity(trade: dict) -> tuple:
    """同じ新規でも役割が違う取引を厳密共通から分ける。

    引数: trade(dict)は保存完結取引。
    返り値: tupleは実新規と実入口役割。
    """
    return (*exposure(trade), trade["入口役割"])


def momentum_group(row: dict) -> str:
    """元P側に対する保存MACD差を区分する。

    引数: row(dict)は構造判定。
    返り値: strは元向き/0/継続向き/未準備。MACDを再計算しない。
    """
    delta = row["MACDヒスト変化"]
    if delta is None or not math.isfinite(delta):
        return "未準備"
    value = row["元価格side"]*delta
    return "元向き" if value > 0 else "継続向き" if value < 0 else "0"


def analyze(cases: list[dict], decisions: list[dict], details: list[dict],
            result: dict | None = None, old_cases: list[dict] | None = None) -> dict:
    """四入口・五運用の保存物を同時点選別と混合占有へ分ける。

    引数: cases/decisions/details(list[dict])は37明細、result(dict|None)は正式結果、old_cases(list[dict]|None)は旧29共有case。
    返り値: dictは小型照合/記述診断。新指標・先着・運用・閾値を計算しない。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """相違を丸めず、巨大な値だけを内容指紋へ置き換える。

        引数: name(str)は項目、actual/expected(object)は保存値。
        返り値: None。属性欠落を一致扱いしない。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            small = []
            for value in (actual, expected):
                text = H.json.dumps(value, ensure_ascii=False, default=str)
                small.append(value if len(text) <= 1500 else {"内容SHA256": H.canonical(value)})
            errors.append({"項目": name, "実値": small[0], "期待値": small[1]})

    case_map = {r["イベントID"]: r for r in cases}
    by_policy = {p: {r["元価格発動ID"]: r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    by_origin = {r["発動ID"]: r for r in decisions}
    check("新case一意", len(case_map), len(cases))
    check("全元P一意", len(by_origin), len(decisions))
    check("R1はB0部分集合", set(by_policy["R1"]) <= set(by_policy["B0"]), True)
    check("単独R/Tは元P排他", bool(set(by_policy["R1"]) & set(by_policy["T1"])), False)
    preselected = defaultdict(list)
    for origin, row in by_origin.items():
        s, close, lower, upper = row["元価格side"], row["終値"], row["旧L"], row["旧H"]
        check(origin+":元端K不変", row["元境界K"], lower if s == 1 else upper)
        inside, outside = lower < close < upper, s*(close-row["元境界K"]) < 0
        kind = "旧範囲内" if inside else "境界等号" if close in (lower, upper) else "元方向外側" if outside else "反対端外側"
        check(origin+":構造区分", row["構造区分"], kind)
        ready = row["共通M準備"] and row["時間条件可"] and row["確認遅延条件可"]
        reverse, trend = bool(row["旧R0採用"] and inside), bool(ready and outside and momentum_group(row) == "継続向き")
        technical = {"B0": row["旧R0採用"], "R1": reverse, "T1": trend, "S1": reverse or trend}
        for policy in POLICIES:
            v = row["戦略判定"][policy]
            check(origin+policy+":競合と技術採否", v["採用"], technical[policy] and not v["同時競合"])
            if technical[policy]:
                preselected[policy, row["場"], row["要求時計秒"], row["要求原板行"]].append(row)
        if row["旧R0採用"]:
            check(origin+":旧R0は元方向MACD", ready and momentum_group(row) == "元向き", True)
    for origin, row in by_origin.items():
        for policy in POLICIES:
            v = row["戦略判定"][policy]
            group = preselected[policy, row["場"], row["要求時計秒"], row["要求原板行"]]
            check(origin+policy+":複数同方向も全見送り", v["同時競合"], len(group) > 1 and row in group)
            check(origin+policy+":保存case集合", origin in by_policy[policy], v["採用"])
            if not v["採用"]:
                continue
            case = by_policy[policy][origin]
            for field, value in (("イベントID", origin+"_"+policy), ("場", row["場"]), ("期間", row["期間"]),
                    ("元価格side", row["元価格side"]), ("side", v["実side"]), ("役割", v["役割"]),
                    ("要求時計秒", row["要求時計秒"]), ("要求原板行", row["要求原板行"])):
                check(origin+policy+":同時計純射影:"+field, case[field], value)
            check(origin+policy+":売買鏡像方向", case["方向"], "買い" if case["side"] == 1 else "売り")
            check(origin+policy+":旧R0参照の役割分離", case["旧R0イベントID"], origin+"_R0" if case["役割"] == "反転" else None)
            if policy in ("B0", "R1"):
                check(origin+policy+":反転は元side", case["side"], row["元価格side"])
            if policy == "T1":
                check(origin+":順行は逆実side", case["side"], -row["元価格side"])
            if policy == "R1":
                for field in (*PURE_FIELDS, *LABEL_FIELDS, "期間"):
                    check(origin+":B0/R1同時点先着:"+field, case[field], by_policy["B0"][origin][field])
            if policy == "S1":
                leg = "R1" if case["役割"] == "反転" else "T1"
                check(origin+":混合の単独脚が存在", origin in by_policy[leg], True)
                if origin in by_policy[leg]:
                    for field in (*PURE_FIELDS, *LABEL_FIELDS, "期間"):
                        check(origin+":単独/混合同時計先着:"+field, case[field], by_policy[leg][origin][field])
    if old_cases is not None:
        old = {r["イベントID"]: r for r in old_cases if r["入口ID"] == "3分_R0"}
        check("B0旧R0全集合", {k+"_R0" for k in by_policy["B0"]}, set(old))
        for origin, case in by_policy["B0"].items():
            source = old[origin+"_R0"]
            for field in (*PURE_FIELDS, *LABEL_FIELDS, "期間"):
                expected = source.get(field) if field == "bb_mean" else source[field]
                check(origin+":旧R0共通射影:"+field, case[field], expected)

    # ----------------------------------------
    # 構造/勢いの全Pと、B0帰還保持/除去、単独と混合の純集合を分ける。
    stages, classifications, subsets, mixing, role_entrances = [], [], [], [], []
    for period in PERIODS:
        raw = [r for r in decisions if r["期間"] == period]
        stages.append({"期間": period, "原P数": len(raw), "元M時間遅延通過数": sum(r["共通M準備"] and r["時間条件可"] and r["確認遅延条件可"] for r in raw),
            **{p+"純入口数": sum(r["期間"] == period for r in by_policy[p].values()) for p in POLICIES},
            "構造区分数": dict(Counter(r["構造区分"] for r in raw)),
            "候補別同時競合数": {p: sum(r["戦略判定"][p]["同時競合"] for r in raw) for p in POLICIES}})
        for kind in ("旧範囲内", "境界等号", "元方向外側", "反対端外側"):
            for momentum in ("元向き", "0", "継続向き", "未準備"):
                own = [r for r in raw if r["構造区分"] == kind and momentum_group(r) == momentum]
                classifications.append({"期間": period, "構造区分": kind, "元Pに対するMACD": momentum,
                    "原P数": len(own), "元M時間遅延通過数": sum(r["共通M準備"] and r["時間条件可"] and r["確認遅延条件可"] for r in own),
                    **{p+"採用数": sum(r["戦略判定"][p]["採用"] for r in own) for p in POLICIES}})
        bm = {k: r for k, r in by_policy["B0"].items() if r["期間"] == period}
        rm = {k: r for k, r in by_policy["R1"].items() if r["期間"] == period}
        subsets.append({"期間": period, "保持入口": entry_summary([bm[k] for k in bm.keys() & rm.keys()]),
            "除外入口": entry_summary([bm[k] for k in bm.keys()-rm.keys()]), "新規追加入口数": len(rm.keys()-bm.keys()),
            "除外した構造区分": dict(Counter(by_origin[k]["構造区分"] for k in bm.keys()-rm.keys()))})
        for leg, role in (("R1", "反転"), ("T1", "順行")):
            left = {k: r for k, r in by_policy[leg].items() if r["期間"] == period}
            right = {k: r for k, r in by_policy["S1"].items() if r["期間"] == period and r["役割"] == role}
            mixing.append({"期間": period, "単独入口": leg, "混合役割": role, "単独純入口数": len(left),
                "混合純入口数": len(right), "共通元P数": len(left.keys() & right.keys()),
                "単独のみ数": len(left.keys()-right.keys()), "混合のみ数": len(right.keys()-left.keys())})
        for policy, role in ROLE_PAIRS:
            own = [r for r in by_policy[policy].values() if r["期間"] == period and r["役割"] == role]
            role_entrances.append({"期間": period, "入口ID": "3分_"+policy, "役割": role, **entry_summary(own)})

    # ----------------------------------------
    # 実sideと役割はfill時の値を使い、同元Pだけで共通新規にしない。
    trades = [{**t, "候補ID": d["候補ID"]} for d in details for t in d["取引"]]
    check("場候補一意", len({(d["候補ID"], d["場"]) for d in details}), len(details))
    handling = {(d["候補ID"], s["イベントID"]): s["取扱"] for d in details for s in d["入口取扱"]}
    for trade in trades:
        case = case_map[trade["入口イベントID"]]
        for field in ("新規時計秒", "新規原板行", "新規価格"):
            check("実新規と各方向case:"+field, trade[field], case[field])
        check("実役割は入口で固定", trade["入口役割"], case["役割"])
        check("実入口ATR不変", trade["入口ATR"], case["atr"])
    participation, cross_role, role_ops, recovery, qualities = [], [], [], [], []
    for period in PERIODS:
        own_trades = {cid: [t for t in trades if t["候補ID"] == cid and t["期間"] == period] for cid in CANDIDATES}
        for cid in CANDIDATES:
            check(cid+period+":実新規一意", len({exposure(t) for t in own_trades[cid]}), len(own_trades[cid]))
        for title, left_id, right_id, role in PAIRS:
            left_rows = [t for t in own_trades[left_id] if role is None or t["入口役割"] == role]
            right_rows = [t for t in own_trades[right_id] if role is None or t["入口役割"] == role]
            left, right = ({strict_identity(t): t for t in rows} for rows in (left_rows, right_rows))
            common, removed, added = left.keys() & right.keys(), left.keys()-right.keys(), right.keys()-left.keys()
            costs = []
            for fee in (0, 5, 10):
                field = f"追加滑り{fee}pt純損益円"
                difference = sum(right[k][field]-left[k][field] for k in common)
                removed_cash, added_cash = H.cash([left[k] for k in removed], fee), H.cash([right[k] for k in added], fee)
                total = H.cash(right_rows, fee)-H.cash(left_rows, fee)
                check(title+period+str(fee)+":全額差分解", total, difference-removed_cash+added_cash)
                costs.append({"片道追加pt": fee, "総差円_右引く左": total, "同役割共通出口差円": difference,
                    "左のみ損益円": removed_cash, "右のみ損益円": added_cash})
            def counterpart(rows: list[dict], cid: str) -> dict:
                """同元Pが純不採用/役割違いか、実抑止かを保存値で分ける。

                引数: rows(list[dict])は片側取引、cid(str)は相手候補。
                返り値: dictは最終取扱。現在情報での新しい採否は作らない。
                """
                policy = cid.split("_")[1]
                values = []
                for trade in rows:
                    origin = case_map[trade["入口イベントID"]]["元価格発動ID"]
                    case = by_policy[policy].get(origin)
                    values.append("同元Pの純入口なし" if case is None else "同元Pの役割が異なる" if case["役割"] != trade["入口役割"] else handling.get((cid, case["イベントID"]), "取扱記録なし"))
                return dict(Counter(values))
            exit_diff = sum(any(left[k][f] != right[k][f] for f in ("返済時計秒", "返済原板行", "返済価格", "返済理由")) for k in common)
            if title != "費用起動変更":
                check(title+period+":共通XF出口同値", exit_diff, 0)
                for row in costs:
                    check(title+period+str(row["片道追加pt"])+":共通XF費用差0", row["同役割共通出口差円"], 0)
            lo = {(case_map[t["入口イベントID"]]["元価格発動ID"], t["入口役割"]): t for t in left_rows}
            ro = {(case_map[t["入口イベントID"]]["元価格発動ID"], t["入口役割"]): t for t in right_rows}
            participation.append({"期間": period, "比較": title, "左": left_id, "右": right_id, "対象役割": role or "全役割",
                "同元P同役割の両実参加数": len(lo.keys() & ro.keys()), "同役割厳密共通数": len(common),
                "厳密共通の元P相違数": sum(case_map[left[k]["入口イベントID"]]["元価格発動ID"] != case_map[right[k]["入口イベントID"]]["元価格発動ID"] for k in common),
                "共通出口属性差数": exit_diff, "左のみ": H.operation_summary([left[k] for k in removed]),
                "右のみ": H.operation_summary([right[k] for k in added]), "左のみの相手取扱": counterpart([left[k] for k in removed], right_id),
                "右のみの相手取扱": counterpart([right[k] for k in added], left_id), "費用別": costs})
        for left_id, right_id in ((CANDIDATES[1], CANDIDATES[3]), (CANDIDATES[1], CANDIDATES[4])):
            left, right = ({exposure(t): t for t in own_trades[cid]} for cid in (left_id, right_id))
            shared = [k for k in left.keys() & right.keys() if left[k]["入口役割"] != right[k]["入口役割"]]
            cross_role.append({"期間": period, "左": left_id, "右": right_id, "同新規異役割数": len(shared),
                "同元P数": sum(case_map[left[k]["入口イベントID"]]["元価格発動ID"] == case_map[right[k]["入口イベントID"]]["元価格発動ID"] for k in shared),
                "元P相違数": sum(case_map[left[k]["入口イベントID"]]["元価格発動ID"] != case_map[right[k]["入口イベントID"]]["元価格発動ID"] for k in shared),
                "役割対応": dict(Counter(left[k]["入口役割"]+"→"+right[k]["入口役割"] for k in shared)),
                "出口属性差数": sum(any(left[k][f] != right[k][f] for f in ("返済時計秒", "返済原板行", "返済価格", "返済理由")) for k in shared),
                "同新規異役割の費用差円": {str(f): sum(right[k][f"追加滑り{f}pt純損益円"]-left[k][f"追加滑り{f}pt純損益円"] for k in shared) for f in (0, 5, 10)}})
        for cid in CANDIDATES:
            rows = own_trades[cid]
            for role in (("反転", "順行") if cid == CANDIDATES[4] else ("順行",) if cid == CANDIDATES[3] else ("反転",)):
                own = [t for t in rows if t["入口役割"] == role]
                role_ops.append({"候補ID": cid, "期間": period, "役割": role, **H.operation_summary(own),
                    "活動日数": len({t["場"][:10] for t in own}), "活動場数": len({t["場"] for t in own}),
                    "買い数": sum(t["方向"] == "買い" for t in own), "売り数": sum(t["方向"] == "売り" for t in own)})
            successes = [t for t in rows if case_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
            armed = [t for t in rows if t["追尾起動"]]
            reds = [t for t in armed if t["起動後純赤字"]]
            nominal = lambda t: (1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"])
            recovery.append({"候補ID": cid, "期間": period, **H.operation_summary(rows),
                "対応仮250数": len(successes), "仮250判定前返済数": sum((t["返済時計秒"], t["返済原板行"]) < (case_map[t["入口イベントID"]]["判定時計秒"], case_map[t["入口イベントID"]]["判定原板行"]) for t in successes),
                "実保有MFE250数": sum(t["観測最大順行pt"] >= 250 for t in rows), "起動数": len(armed), "起動後基準赤字数": len(reds),
                "名目同値費用赤字数": sum(nominal(t) == 0 for t in reds), "不利返済赤字数": sum(nominal(t) < 0 for t in reds),
                "正名目利益の基準費用負け数": sum(nominal(t) > 0 for t in reds)})
    sequence = []
    for period in PERIODS:
        own_details = [d for d in details if d["候補ID"] == CANDIDATES[4] and d["品質"]["期間"] == period]
        pairs, blocks = [], Counter()
        for detail in own_details:
            ordered = sorted(detail["取引"], key=lambda t: (t["新規時計秒"], t["新規原板行"]))
            pairs += [(a, b) for a, b in zip(ordered, ordered[1:])]
            for signal in detail["入口取扱"]:
                case = case_map[signal["イベントID"]]
                key = signal["要求時計秒"], signal["要求原板行"]
                owners = [t for t in ordered if (t["新規時計秒"], t["新規原板行"]) <= key < (t["返済時計秒"], t["返済原板行"])]
                # 約定済み注文の要求〜約定keyだけを参照し、取消時刻の欠落を推定で補わない。
                pending = [o for o in detail["注文"] if o["約定時計秒"] is not None and (o["要求時計秒"], o["要求原板行"]) <= key < (o["約定時計秒"], o["約定原板行"])]
                if signal["取扱"] in ("建玉中抑止", "注文待機中抑止"):
                    owner_role = case_map[pending[0]["入口イベントID"]]["役割"] if pending else owners[0]["入口役割"] if len(owners) == 1 else "役割未確定"
                    kind = "返済pending" if any(o["区分"] == "返済" for o in pending) else "新規pending" if any(o["区分"] == "新規" for o in pending) else "保有" if owners else "待機種未確定"
                    blocks[case["役割"]+"候補/"+kind+"/"+owner_role] += 1
        sequence.append({"期間": period, "S実完結数": sum(len(d["取引"]) for d in own_details),
            "連続実役割": dict(Counter(a["入口役割"]+"→"+b["入口役割"] for a, b in pairs)),
            "役割変更かつ実方向同じ数": sum(a["入口役割"] != b["入口役割"] and a["方向"] == b["方向"] for a, b in pairs),
            "役割変更かつ実方向反対数": sum(a["入口役割"] != b["入口役割"] and a["方向"] != b["方向"] for a, b in pairs),
            "前返済から次新規秒": H.distribution([b["新規時計秒"]-a["返済時計秒"] for a, b in pairs]),
            "抑止の候補役割と保有待機": dict(blocks), "全入口取扱": dict(Counter(s["取扱"] for d in own_details for s in d["入口取扱"]))})
    if result is not None:
        check("五運用順", [r["候補ID"] for r in result["結果"]], list(CANDIDATES))
        check("四入口順", [r["入口ID"] for r in result["入口評価"]], ["3分_"+p for p in POLICIES])
        for source in result["入口評価"]:
            for period in PERIODS:
                summary = entry_summary([r for r in cases if r["入口ID"] == source["入口ID"] and r["期間"] == period])
                for field in ("候補数", "約定候補数", "順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "確認率"):
                    check(source["入口ID"]+period+field, source[period][field], summary[field])
        expected_roles = [("3分_"+p, role) for p, role in ROLE_PAIRS]
        check("役割別入口評価の五群", [(r["入口ID"], r["役割"]) for r in result["役割別入口評価"]], expected_roles)
        for role_row in result["役割別入口評価"]:
            for period in PERIODS:
                own = next(r for r in role_entrances if r["入口ID"] == role_row["入口ID"] and r["役割"] == role_row["役割"] and r["期間"] == period)
                for field in ("候補数", "約定候補数", "順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "確認率"):
                    check(role_row["入口ID"]+role_row["役割"]+period+field, role_row[period][field], own[field])
        for row in result["結果"]:
            for period in PERIODS:
                op = row[period]["運用"]
                own = [t for t in trades if t["候補ID"] == row["候補ID"] and t["期間"] == period]
                check(row["候補ID"]+period+":完結数", op["完結取引数"], len(own))
                for fee in (0, 5, 10):
                    check(row["候補ID"]+period+str(fee)+":保存会計", op[f"追加{fee}pt純損益円"], H.cash(own, fee))
                qualities.append({"候補ID": row["候補ID"], "期間": period,
                    **{k: op[k] for k in ("品質注意場数", "未解消場数", "EOF期限未達場数")},
                    "観測純額円": {str(f): op[f"追加{f}pt純損益円"] for f in (0, 5, 10)},
                    "全体確定対象円": {str(f): op[f"追加{f}pt確定対象円"] for f in (0, 5, 10)}})
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "モデル再計算": False, "指標再計算": False, "先着再計算": False, "運用再生": False, "新閾値選別": False,
        "原発動と四入口": stages, "構造と勢いの全区分": classifications, "B0の帰還保持除外": subsets,
        "単独と混合の純役割": mixing, "役割別入口集計": role_entrances,
        "役割別実運用": role_ops, "実参加比較": participation, "同新規異役割": cross_role,
        "Sの役割順序と抑止": sequence, "候補別回収": recovery, "品質と確定額": qualities,
        "限界": ["Tは全元Pから逆実sideへ判別し、旧R0の補数/旧先着反転ではない。",
            "元P/役割一致と、同実新規key/価格/ATR/D一致を分ける。異役割の同新規は別表。",
            "単独R/Tの損益和は一建玉Sの実装可能損益ではない。役割変更は自動ドテンではない。",
            "取消注文は終了key未保存なら待機種未確定。ここで取消時計を推定して補完しない。",
            "混合合算の支持を薄い役割へ代用せず、品質null・仮先着と実回収を分ける。"]}


def compare_control(details: list[dict], trace: list[dict], control: dict,
                    old_details: list[dict], old_trace: list[dict]) -> dict:
    """固定36の全属性比較を、B0識別子の読取変換だけで再用する。

    引数: details/trace(list[dict])は37、control(dict)は主B0証明、old_details/old_trace(list[dict])は旧29。
    返り値: dictは旧R0全ledger/trace比較。旧global・数値・属性を変えない。
    """
    output = F.compare_control(rename(details, "_B0", "_V0"), rename(trace, "_B0", "_V0"), control, old_details, old_trace)
    output["識別子正規化"] = "B0を旧R0へ。既存V0比較APIへ読取射影して数値/属性は全保持"
    return output


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式完了後に新四明細と旧共有case/対照を読取診断する。

    引数: study/work(Path)は37正式/作業先。
    返り値: dictは小型診断。市場・指標・先着・運用は再計算しない。
    """
    if not (study/"結果.json").is_file():
        raise ValueError("正式結果完成前に保存診断を実行しません")
    reference, control_ref = (H.read(study/n) for n in ("入口参照.json", "対照参照.json"))
    shared = {Path(r["パス"]).name: ROOT/r["パス"] for r in reference["共有明細"]}
    for ref in (reference, control_ref):
        for item in ref["共有明細"]:
            if H.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
                raise ValueError("旧29共有参照の版差")
    decisions, cases, details, trace = (H.read(work/n) for n in ("構造判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz"))
    result, control = H.read(study/"結果.json"), H.read(study/"B0対照同値.json")
    for name in ("入口参照.json", "対照参照.json"):
        if control[name[:-5]+"SHA256"] != H.sha(study/name):
            raise ValueError("B0対照の参照版差")
    output = analyze(cases, decisions, details, result, H.read(shared["入口事例.jsonl.gz"]))
    comparison = compare_control(details, trace, control, H.read(shared["全運用詳細.jsonl.gz"]), H.read(shared["追尾.jsonl.gz"]))
    output["旧29B0X0全属性対照"] = {k: v for k, v in comparison.items() if k not in ("全件一致", "不一致")}
    output["照合項目数"] += comparison["照合項目数"]
    output["不一致"] += comparison["不一致"]
    output["不一致数"] = len(output["不一致"])
    output["全件一致"] = not output["不一致"]
    output["全66場既使用"] = True
    paths = [Path(__file__), HELPER, ROOT/"scripts/終値位置/対応診断.py", ROOT/"scripts/SAR追尾/対応診断.py",
        *[study/n for n in ("条件.json", "固定.json", "結果.json", "入力台帳.json", "入口参照.json", "対照参照.json", "B0対照同値.json")],
        *[work/n for n in ("診断予定.json", "構造判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")], *shared.values()]
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix(): H.sha(p) for p in paths}
    output["参照SHA256"] = {n: H.sha(study/n) for n in ("結果.json", "入口参照.json", "対照参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if not output["全件一致"]:
        raise RuntimeError("構造判別保存物の対応に不一致")
    return output


def main() -> None:
    """保存された構造判別の後段診断だけをCLIで起動する。

    引数: なし。--study/--workはPath。
    返り値: None。実行はrootの正式完了後だけ。
    """
    parser = argparse.ArgumentParser(description="高安帰還と外側継続・保存対応診断")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    data = run(args.study.resolve(), args.work.resolve())
    print(H.json.dumps({k: data[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
