"""保存した発動足TRを、準備・非拡大選別・実参加・回収へ分ける。"""

import argparse
from collections import Counter
import importlib.util
import math
from fractions import Fraction
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00040_外側継続と発動足の相対値幅"
WORK = ROOT/"work/発動値幅継続/00040"
HELPER = ROOT/"scripts/構造判別/対応診断.py"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("W0", "W1", "W2")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
PAIRS = (("発動値幅準備追加", CANDIDATES[0], CANDIDATES[1]),
    ("非拡大選別追加", CANDIDATES[1], CANDIDATES[2]))
SOURCE_FIELDS = ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing",
    "open", "high", "low", "close")
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr")

spec = importlib.util.spec_from_file_location("値幅40の固定37保存集計", HELPER)
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


def range_values(current: dict, previous: dict | None) -> dict:
    """保存OHLCと正本前ATRだけの局所算術を照合する。

    引数: current(dict)は保存発動足、previous(dict|None)は当場隣接前足。
    返り値: dictは準備/理由/TR三距離/差/比/符号。ATR銀行・原板・価格発動を再計算しない。
    """
    price_reasons = ["前3分公開参照なし"] if previous is None else []
    for name, row in (("現", current), ("前", previous)):
        if row is None:
            continue
        valid = (all(isinstance(row.get(k), (float, int)) and math.isfinite(row[k]) and row[k] > 0
            for k in ("open", "high", "low", "close")) and
            row["high"] >= max(row["open"], row["close"]) >= min(row["open"], row["close"]) >= row["low"])
        for condition, reason in ((not row["publish"], "3分非公開"), (not valid, "3分OHLC不正"),
                (row["missing"] != 0, "3分欠枠あり"), (row["end"]-row["start"] != 180, "3分完全幅180秒不成立"),
                (row["confirm"] < row["end"], "3分終了前公開")):
            if condition:
                price_reasons.append(name+reason)
    if previous is not None:
        for condition, reason in ((previous["index"]+1 != current["index"], "現前3分足番号非隣接"),
                (previous["end"] != current["start"], "現前3分終了開始非隣接"),
                ((previous["confirm"], previous["confirm_line"]) > (current["confirm"], current["confirm_line"]), "現前3分公開順不整合")):
            if condition:
                price_reasons.append(reason)
    distances = {k: None for k in ("高安幅", "高値と前終値の距離", "安値と前終値の距離")}
    tr = None
    if not price_reasons:
        high, low, close = (Fraction(v) for v in (current["high"], current["low"], previous["close"]))
        distances = {"高安幅": high-low, "高値と前終値の距離": abs(high-close), "安値と前終値の距離": abs(low-close)}
        tr = max(distances.values())
    atr = previous["atr"] if previous is not None and finite(previous["atr"]) else None
    reasons = price_reasons+(["前3分ATR14有限正未準備"] if atr is None or atr <= 0 else [])
    difference, ratio = (None, None) if reasons else (tr-Fraction(atr), tr/Fraction(atr))
    sign = None if difference is None else (1 if difference > 0 else -1 if difference < 0 else 0)
    return {"値幅準備": not reasons, "準備除外理由": reasons, "TR準備": not price_reasons,
        "TR三距離": {k: exact(v) for k, v in distances.items()}, "TR": exact(tr), "前ATR14": atr,
        "TR前ATR差": exact(difference), "TR前ATR比": exact(ratio), "TR前ATR差符号": sign,
        "値幅区分": "未準備" if reasons else "非拡大" if sign <= 0 else "拡大"}


def preparation_group(row: dict) -> str:
    """値幅準備不可を、価格ペアと前ATRに分ける。

    引数: row(dict)は保存判定。
    返り値: strは相互排他的な大区分。
    """
    return "準備済み" if row["値幅準備"] else "当場前足参照なし" if row["前足参照"] is None else (
        "価格ペア/TR不可" if not row["TR準備"] else "前ATR有限正不可")


def analyze(cases: list[dict], decisions: list[dict], details: list[dict],
            result: dict | None = None, old_cases: list[dict] | None = None,
            numeric_rows: list[dict] | None = None) -> dict:
    """発動足TRの準備と非拡大選別を、実参加・出口・回収から分ける。

    引数: cases/decisions/details(list[dict])は40保存明細、result(dict|None)は結果、
    old_cases/numeric_rows(list[dict]|None)は固定39J0と固定29全指標の共有保存値。
    返り値: dictは照合と小型記述集計。保存正本の局所TR算術だけ確認し、銀行/先着/運用を再計算しない。
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

    by_policy = {p: {r["旧J0イベントID"]: r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    case_map = {r["イベントID"]: r for r in cases}
    decision_map = {r["元39J0イベントID"]: r for r in decisions}
    check("新case一意", len(case_map), len(cases))
    check("元J0判定一意", len(decision_map), len(decisions))
    check("W0は元J0判定全件", set(by_policy["W0"]), set(decision_map))
    check("W1はW0部分集合", set(by_policy["W1"]) <= set(by_policy["W0"]), True)
    check("W2はW1部分集合", set(by_policy["W2"]) <= set(by_policy["W1"]), True)
    frame_map = {} if numeric_rows is None else {(r["場"], r["index"]): r for r in numeric_rows if r["minutes"] == 3}
    for origin, decision in decision_map.items():
        current, previous = decision["当足参照"], decision["前足参照"]
        state = range_values(current, previous)
        ready = state["値幅準備"]
        for field, expected in (*state.items(), ("役割", "順行")):
            check(origin+":"+field, decision[field], expected)
        if numeric_rows is not None:
            source = frame_map[decision["場"], decision["元index"]]
            projected = {k: source[k] for k in FRAME_FIELDS}
            check(origin+":現3分正本14列", current, projected)
            before = frame_map.get((decision["場"], decision["元index"]-1))
            if before is not None and (not before["publish"] or before["end"] > current["end"] or
                    (before["confirm"], before["confirm_line"]) > (decision["要求時計秒"], decision["要求原板行"])):
                before = None
            check(origin+":当場前足・未来非公開マスク後", previous, None if before is None else {k: before[k] for k in FRAME_FIELDS})
        for field, expected in (("場", decision["場"]), ("minutes", 3), ("index", decision["元index"]),
                ("end", decision["足終了時計秒"]), ("confirm", decision["要求時計秒"]), ("confirm_line", decision["要求原板行"])):
            check(origin+":現出典:"+field, current[field], expected)
        expected_votes = {"W0": True, "W1": ready, "W2": ready and state["TR前ATR差符号"] <= 0}
        for policy in POLICIES:
            verdict = decision["戦略判定"][policy]
            check(origin+policy+":同時点採否", verdict["採用"], expected_votes[policy])
            check(origin+policy+":競合復活なし", verdict["同時競合"], False)
            check(origin+policy+":case集合", origin in by_policy[policy], expected_votes[policy])
            if origin not in by_policy[policy]:
                continue
            case, base = by_policy[policy][origin], by_policy["W0"][origin]
            check(origin+policy+":識別子", case["イベントID"], origin[:-3]+"_"+policy)
            check(origin+policy+":実side", case["side"], decision["実side"])
            check(origin+policy+":純役割", case["役割"], "順行")
            check(origin+policy+":出口の現ATR/高安不変", (case["atr"], case["high"], case["low"]),
                (current["atr"], current["high"], current["low"]))
            for field in (*PURE_FIELDS, *LABEL_FIELDS, "期間", "元価格発動ID", "元価格side"):
                check(origin+policy+":同時計同新規先着:"+field, case[field], base[field])
            for field in ("場", "要求時計秒", "要求原板行", "期間"):
                check(origin+policy+":判定とcase:"+field, case[field], decision[field])
    if old_cases is not None:
        old = {r["イベントID"]: r for r in old_cases if r["入口ID"] == "3分_J0"}
        check("W0旧J0全集合", set(by_policy["W0"]), set(old))
        for origin, case in by_policy["W0"].items():
            for field in (*PURE_FIELDS, *LABEL_FIELDS, "期間", "元価格発動ID", "元価格side"):
                check(origin+":旧39純射影と先着:"+field, case[field], old[origin].get(field) if field == "bb_mean" else old[origin][field])

    # ----------------------------------------
    # 準備不可と値の大小を分け、等号採用を独立の行で残す。
    stages, subsets, readiness, widths, descriptions = [], [], [], [], []
    for period in PERIODS:
        own = [r for r in decisions if r["期間"] == period]
        stages.append({"期間": period, "旧J0登録数": len(own),
            **{p+"純入口数": sum(r["期間"] == period for r in by_policy[p].values()) for p in POLICIES}})
        for title, left_id, right_id in PAIRS:
            lp, rp = left_id.split("_")[1], right_id.split("_")[1]
            left = {k: r for k, r in by_policy[lp].items() if r["期間"] == period}
            right = {k: r for k, r in by_policy[rp].items() if r["期間"] == period}
            subsets.append({"期間": period, "比較": title, "左入口": lp, "右入口": rp,
                "保持入口": entry_summary([left[k] for k in left.keys() & right.keys()]),
                "除外入口": entry_summary([left[k] for k in left.keys()-right.keys()]),
                "新規追加入口数": len(right.keys()-left.keys())})
        for kind in ("当場前足参照なし", "価格ペア/TR不可", "前ATR有限正不可", "準備済み"):
            selected = [r for r in own if preparation_group(r) == kind]
            readiness.append({"期間": period, "準備区分": kind,
                "詳細理由数": dict(Counter(reason for r in selected for reason in r["準備除外理由"])),
                **entry_summary([by_policy["W0"][r["元39J0イベントID"]] for r in selected])})
        for sign, kind in ((-1, "平均未満"), (0, "平均同値"), (1, "平均超")):
            selected = [r for r in own if r["値幅準備"] and r["TR前ATR差符号"] == sign]
            widths.append({"期間": period, "分母": "W1純入口", "TR前ATR区分": kind, "W2採用": sign <= 0,
                **entry_summary([by_policy["W0"][r["元39J0イベントID"]] for r in selected])})
        for accepted in (True, False):
            selected = [r for r in own if r["値幅準備"] and r["戦略判定"]["W2"]["採用"] == accepted]
            descriptions.append({"期間": period, "分母": "W1純入口の当時値", "W2保持": accepted,
                "要求数": len(selected), "TRpt": H.distribution([r["TR"]["値"] for r in selected]),
                "前ATR14": H.distribution([r["前ATR14"] for r in selected]),
                "TR前ATR比": H.distribution([r["TR前ATR比"]["値"] for r in selected]),
                "TR0数": sum(r["TR"]["分子"] == 0 for r in selected),
                "TR三距離最大の組合せ数": dict(Counter("/".join(k for k, v in r["TR三距離"].items() if
                    Fraction(v["分子"], v["分母"]) == Fraction(r["TR"]["分子"], r["TR"]["分母"])) for r in selected))})

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
                    origin = case_map[trade["入口イベントID"]]["旧J0イベントID"]
                    other = by_policy[policy].get(origin)
                    values.append("同元J0の純入口なし" if other is None else handling.get((cid, other["イベントID"]), "取扱記録なし"))
                return dict(Counter(values))

            exit_diff = sum(any(left[k][f] != right[k][f] for f in ("返済時計秒", "返済原板行", "返済価格", "返済理由")) for k in common)
            check(title+period+":共通XF出口属性同値", exit_diff, 0)
            left_origins = {case_map[t["入口イベントID"]]["旧J0イベントID"] for t in own[left_id]}
            right_origins = {case_map[t["入口イベントID"]]["旧J0イベントID"] for t in own[right_id]}
            participation.append({"期間": period, "比較": title, "左": left_id, "右": right_id,
                "同元J0両実参加数": len(left_origins & right_origins), "厳密共通実新規数": len(common),
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
        "旧J0と三入口": stages, "入口追加比較": subsets, "W0の値幅準備区分": readiness,
        "W1の相対値幅区分": widths, "保持除外の値幅記述": descriptions,
        "実参加比較": participation, "候補別回収": recovery, "品質と確定額": qualities,
        "責任分界": {"固定39以前": "元P/MACD/元Pのkと数量M/実sideT1/現ATRコピーの既存照合",
            "固定29": "共有3分OHLC/前ATR/銀行の正本",
            "40保存診断": "共有正本の局所TR算術/現前出典/準備と非拡大採否/同時計case/実参加/費用分解。ATR銀行を再計算しない"},
        "限界": ["W0→W1は準備差、W1→W2はTR<=前ATRの値選別。境界1は平均非超過で異常値判定でない。",
            "Wilder実数代数の境界1同値を保存floatの判定同値と混同せず、出口Dは現ATRのまま。",
            "純subsetでも一建玉占有の変化で実参加追加がある。共通出口0と片側損益を分ける。",
            "全66場既使用。価格派生の票数や計算一致を独立した収益標本へ換算しない。",
            "仮250先着は実返済後まで追う反事実。実保有MFE/回収/最低名目床と別の分母。"]}


def compare_control(details: list[dict], trace: list[dict], control: dict,
                    old_details: list[dict], old_trace: list[dict]) -> dict:
    """W0の識別子だけを旧39J0へ戻し、全属性と追尾順序を照合する。

    引数: details/trace(list[dict])は40、control(dict)は主対照、old_details/old_trace(list[dict])は旧39。
    返り値: dictは全場直接比較。属性除外・数値丸めを行わない。
    """
    current = {d["場"]: F.rename(d, "_W0", "_J0") for d in details if d["候補ID"] == CANDIDATES[0]}
    previous = {d["場"]: d for d in old_details if d["候補ID"] == "3分_J0_XF"}
    errors, checks = [], 0
    records = {r["場"]: r for r in control["照合"]}
    for scene in sorted(current.keys() | previous.keys()):
        left, right = current.get(scene), previous.get(scene)
        logs = [F.rename(r, "_W0", "_J0") for r in trace if r["候補ID"] == CANDIDATES[0] and r["場"] == scene]
        old_logs = [r for r in old_trace if r["候補ID"] == "3分_J0_XF" and r["場"] == scene]
        expected = {"全運用同値": left == right, "全追尾同値": logs == old_logs,
            "旧識別子全運用内容SHA256": H.canonical(left), "旧識別子追尾内容SHA256": H.canonical(logs)}
        for name, actual in (("全運用直接比較", left == right), ("全追尾直接比較", logs == old_logs)):
            checks += 1
            if not actual:
                errors.append({"項目": scene+name, "実値": False, "期待値": True})
        for name, value in expected.items():
            checks += 1
            if records.get(scene, {}).get(name) != value:
                errors.append({"項目": scene+name, "実値": records.get(scene, {}).get(name), "期待値": value})
    checks += 2
    for name, actual, expected in (("対照場集合", set(records), set(previous)), ("主対照場数", control["場候補数"], len(previous))):
        if actual != expected:
            errors.append({"項目": name, "実値": sorted(actual) if isinstance(actual, set) else actual,
                "期待値": sorted(expected) if isinstance(expected, set) else expected})
    return {"全件一致": not errors, "照合項目数": checks, "不一致": errors, "場候補数": len(previous),
        "全明細直接比較": True, "全追尾直接比較": True, "識別子正規化": "W0を旧39J0へ。数値/属性全保持"}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式完了後に共有保存値と新四明細だけを診断する。

    引数: study/work(Path)は40正式/作業先。
    返り値: dictは小型診断。実行はrootの正式完了通知後だけ。
    """
    if not (study/"結果.json").is_file():
        raise ValueError("正式結果完成前に保存診断を実行しません")
    references = {n: H.read(study/n) for n in ("入口参照.json", "対照参照.json", "指標参照.json")}
    shared = {}
    for name, reference in references.items():
        shared[name] = {Path(r["パス"]).name: ROOT/r["パス"] for r in reference["共有明細"]}
        for item in reference["共有明細"]:
            if H.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
                raise ValueError("共有明細の参照版差")
    decisions, cases, details, trace = (H.read(work/n) for n in ("値幅判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz"))
    result, control = H.read(study/"結果.json"), H.read(study/"W0対照同値.json")
    for name in ("入口参照.json", "対照参照.json"):
        if control[name[:-5]+"SHA256"] != H.sha(study/name):
            raise ValueError("W0対照の参照版差")
    output = analyze(cases, decisions, details, result, H.read(shared["入口参照.json"]["入口事例.jsonl.gz"]),
        H.read(shared["指標参照.json"]["全指標.jsonl.gz"]))
    comparison = compare_control(details, trace, control, H.read(shared["対照参照.json"]["全運用詳細.jsonl.gz"]), H.read(shared["対照参照.json"]["追尾.jsonl.gz"]))
    output["旧39J0全属性対照"] = {k: v for k, v in comparison.items() if k not in ("全件一致", "不一致")}
    output["照合項目数"] += comparison["照合項目数"]
    output["不一致"] += comparison["不一致"]
    output["不一致数"] = len(output["不一致"])
    output["全件一致"] = not output["不一致"]
    output["全66場既使用"] = True
    paths = [Path(__file__), HELPER, ROOT/"scripts/量比反転/対応診断.py", ROOT/"scripts/終値位置/対応診断.py", ROOT/"scripts/SAR追尾/対応診断.py",
        *[study/n for n in ("条件.json", "固定.json", "結果.json", "入力台帳.json", "入口参照.json", "対照参照.json", "指標参照.json", "W0対照同値.json")],
        *[work/n for n in ("診断予定.json", "値幅判定.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")],
        *[p for values in shared.values() for p in values.values()]]
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix(): H.sha(p) for p in dict.fromkeys(paths)}
    output["参照SHA256"] = {n: H.sha(study/n) for n in ("結果.json", "入口参照.json", "対照参照.json", "指標参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if not output["全件一致"]:
        raise RuntimeError("発動値幅継続の保存対応に不一致")
    return output


def main() -> None:
    """保存明細だけの後段診断をCLIで起動する。

    引数: なし。--study/--workはPath。
    返り値: None。市場・指標・先着・運用を起動しない。
    """
    parser = argparse.ArgumentParser(description="発動TRと前ATRの保存対応診断")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    output = run(args.study.resolve(), args.work.resolve())
    print(H.json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
