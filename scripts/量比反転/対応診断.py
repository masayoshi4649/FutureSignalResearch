"""保存済みの量比準備・値選別・費用起動を、同時点の入口と実参加へ分ける。"""

import argparse
from collections import Counter, defaultdict
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00036_価格失敗と量比の方向変化"
WORK = ROOT/"work/量比反転/00036"
HELPER = ROOT/"scripts/終値位置/対応診断.py"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("V0", "V1", "V2")
CANDIDATES = ("3分_V0_X0", "3分_V0_XF", "3分_V1_XF", "3分_V2_XF")
PAIRS = (("費用起動変更", CANDIDATES[0], CANDIDATES[1]),
    ("量比準備追加", CANDIDATES[1], CANDIDATES[2]), ("量比値追加", CANDIDATES[2], CANDIDATES[3]))
LABEL_FIELDS = ("ラベル", "理由", "新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")
PURE_FIELDS = ("場", "役割", "side", "方向", "要求時計秒", "要求原板行", "確認遅延秒", "low", "high", "atr", "bb_mean")

spec = importlib.util.spec_from_file_location("量比36の固定33保存表示", HELPER)
F = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = F
spec.loader.exec_module(F)
H = F.H
entry_summary = F.entry_summary


def old_identity(value: object) -> object:
    """新V0の識別文字列だけを旧29R0へ対応させる。

    引数: value(object)は保存JSON値。
    返り値: objectは属性除外なしの正規化値。旧数式・主コードを呼ばない。
    """
    if isinstance(value, dict):
        return {k: old_identity(v) for k, v in value.items()}
    if isinstance(value, list):
        return [old_identity(v) for v in value]
    return value.replace("_V0", "_R0") if isinstance(value, str) else value


def strict_identity(trade: dict) -> tuple:
    """同新規key/価格と入口ATR/Dだけを共通出口の対応にする。

    引数: trade(dict)は保存完結取引。
    返り値: tupleは場/side/新規key/価格/ATR/D。
    """
    return (*H.identity(trade), trade["入口ATR"], trade["追尾距離pt"])


def value_group(decision: dict) -> str:
    """量比未準備と準備後の実方向符号を別の四群にする。

    引数: decision(dict)は保存された原P採否。
    返り値: strは未準備/正/0/負。欠測を同値へ補完しない。
    """
    if not decision["現前B準備"]:
        return "未準備"
    value = decision["side"]*decision["B差分子"]
    return "正" if value > 0 else "負" if value < 0 else "0"


def readiness_group(panel: dict) -> str:
    """保存足の新準備不可を、入力・窓・0分母の順で分ける。

    引数: panel(dict)は量比全足の保存値。
    返り値: strは相互排他的な準備区分。量比を再計算しない。
    """
    if panel["現前B準備"]:
        return "準備済み"
    if not panel["価格入力可"]:
        return "公開価格入力不可"
    if not panel["数量入力可"]:
        return "当足数量入力不可"
    if not panel["VR入力可"]:
        return "比較元終値なし"
    if len(panel["現窓足番号"]) != 20 or len(panel["前窓足番号"]) != 20:
        return "現前20変化窓未充足"
    current, previous = panel["現方向別量"]["合計量"], panel["前方向別量"]["合計量"]
    return "現前とも合計0" if current == previous == 0 else "現在合計0" if current == 0 else "前合計0" if previous == 0 else "その他準備不可"


def analyze(cases: list[dict], decisions: list[dict], panels: list[dict], details: list[dict],
            result: dict | None = None, old_cases: list[dict] | None = None) -> dict:
    """同時計の三入口と四運用を、準備・値・実参加・利益保護へ分ける。

    引数: cases/decisions/panels/details(list[dict])は36保存明細/準備採否、result(dict|None)は正式結果、old_cases(list[dict]|None)は旧29共有case。
    返り値: dictは小型照合と記述集計。市場・数値指標・先着・運用を再計算しない。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """不一致を丸めず、小さい値又は内容指紋で保存する。

        引数: name(str)は項目、actual/expected(object)は保存値と期待値。
        返り値: None。大明細の重複転記をしない。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            values = []
            for value in (actual, expected):
                text = H.json.dumps(value, ensure_ascii=False, default=str)
                values.append(value if len(text) <= 1500 else {"内容SHA256": H.canonical(value)})
            errors.append({"項目": name, "実値": values[0], "期待値": values[1]})

    case_map = {r["イベントID"]: r for r in cases}
    by_policy = {p: {r["旧R0イベントID"]: r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    panel_map = {(r["場"], r["index"]): r for r in panels}
    decision_map = {r["発動ID"]+"_R0": r for r in decisions}
    check("新case一意", len(case_map), len(cases))
    check("量比足一意", len(panel_map), len(panels))
    check("原P採否一意", len(decision_map), len(decisions))
    check("V1はV0のsubset", set(by_policy["V1"]) <= set(by_policy["V0"]), True)
    check("V2はV1のsubset", set(by_policy["V2"]) <= set(by_policy["V1"]), True)
    for policy in POLICIES:
        selected = {key for key, d in decision_map.items() if d["戦略判定"][policy]["採用"]}
        check(policy+":採否と保存case集合", set(by_policy[policy]), selected)
    for origin, decision in decision_map.items():
        panel = panel_map[decision["場"], decision["index"]]
        check(origin+":当時公開key", (decision["要求時計秒"], decision["要求原板行"]), (panel["公開時計秒"], panel["公開原板行"]))
        for field in ("現前B準備", "B差分子", "B差分母"):
            check(origin+":保存量比参照:"+field, decision[field], panel[field])
        check(origin+":V0旧R0採用", decision["戦略判定"]["V0"]["採用"], decision["旧R0採用"])
        ready = decision["旧R0採用"] and decision["現前B準備"]
        check(origin+":V1準備だけ追加", decision["戦略判定"]["V1"]["採用"], ready)
        check(origin+":V2厳密符号だけ追加", decision["戦略判定"]["V2"]["採用"], ready and value_group(decision) == "正")
        if decision["現前B準備"]:
            check(origin+":有効分母正", decision["B差分母"] > 0, True)
        for policy in POLICIES:
            if origin in by_policy[policy]:
                row = by_policy[policy][origin]
                check(origin+policy+":純入口識別子", row["イベントID"], decision["発動ID"]+"_"+policy)
                check(origin+policy+":期間は元発動", row["期間"], decision["期間"])
                check(origin+policy+":要求keyを取り直さない", (row["要求時計秒"], row["要求原板行"]), (decision["要求時計秒"], decision["要求原板行"]))
                check(origin+policy+":方向不変", row["side"], decision["side"])
                base = by_policy["V0"][origin]
                for field in ("期間", *PURE_FIELDS, *LABEL_FIELDS):
                    check(origin+policy+":同時点共通値:"+field, row[field], base[field])
    if old_cases is not None:
        old_map = {r["イベントID"]: r for r in old_cases if r["入口ID"] == "3分_R0"}
        check("旧29R0全入口集合", set(by_policy["V0"]), set(old_map))
        for origin in by_policy["V0"].keys() & old_map.keys():
            for field in ("期間", *PURE_FIELDS, *LABEL_FIELDS):
                expected = old_map[origin].get(field) if field == "bb_mean" else old_map[origin][field]
                check(origin+":旧29共通射影:"+field, by_policy["V0"][origin][field], expected)

    # ----------------------------------------
    # 旧R0純入口の準備除外と、準備後の値除外を別の分母で集計する。
    stages, preparation, signs, subsets, panel_quality = [], [], [], [], []
    for period in PERIODS:
        raw = [r for r in decisions if r["期間"] == period]
        base = [r for r in raw if r["旧R0採用"]]
        stages.append({"期間": period, "原P数": len(raw), "原P量比準備数": sum(r["現前B準備"] for r in raw),
            "V0純入口数": len(base), "V1純入口数": sum(r["戦略判定"]["V1"]["採用"] for r in raw),
            "V2純入口数": sum(r["戦略判定"]["V2"]["採用"] for r in raw),
            "V0内量比区分": dict(Counter(value_group(r) for r in base)),
            "V0不採用理由別_重複": dict(Counter(reason for r in raw if not r["旧R0採用"] for reason in r["戦略判定"]["V0"]["理由"]))})
        for ready in (True, False):
            own = [by_policy["V0"][r["発動ID"]+"_R0"] for r in base if r["現前B準備"] == ready]
            preparation.append({"期間": period, "分母": "V0純入口", "B現前準備": ready, **entry_summary(own)})
        for group in ("正", "0", "負"):
            own = [by_policy["V0"][r["発動ID"]+"_R0"] for r in base if value_group(r) == group]
            signs.append({"期間": period, "分母": "V1純入口", "実方向B差区分": group, **entry_summary(own)})
        for title, left, right in (("量比準備追加", "V0", "V1"), ("量比値追加", "V1", "V2")):
            lm = {k: v for k, v in by_policy[left].items() if v["期間"] == period}
            rm = {k: v for k, v in by_policy[right].items() if v["期間"] == period}
            subsets.append({"期間": period, "比較": title, "左": "3分_"+left, "右": "3分_"+right,
                "保持入口": entry_summary([lm[k] for k in lm.keys() & rm.keys()]),
                "除外入口": entry_summary([lm[k] for k in lm.keys()-rm.keys()]), "新規追加入口数": len(rm.keys()-lm.keys())})
        own_panels = [r for r in panels if r["期間"] == period]
        panel_quality.append({"期間": period, "全足数": len(own_panels),
            "準備区分_相互排他": dict(Counter(readiness_group(r) for r in own_panels)),
            "解除理由別_重複": dict(Counter(reason for r in own_panels for reason in r["VR解除理由"])),
            "完全0量足数": sum(r["数量入力可"] and r["観測差分量"] == 0 for r in own_panels)})
        check(period+":準備二群の合計", sum(r["候補数"] for r in preparation if r["期間"] == period), len(base))
        check(period+":値三群の合計", sum(r["候補数"] for r in signs if r["期間"] == period), sum(r["戦略判定"]["V1"]["採用"] for r in raw))

    # ----------------------------------------
    # 保存分類だけで当足と窓落ちを分け、20量/21量の回数退化を混同しない。
    mechanism = []
    for policy in ("V1", "V2"):
        tagged = []
        for origin, case in by_policy[policy].items():
            decision = decision_map[origin]
            current = panel_map[case["場"], decision["index"]]
            current_indices, previous_indices = current["現窓足番号"], current["前窓足番号"]
            union = sorted(set(current_indices) | set(previous_indices))
            dropped = set(previous_indices)-set(current_indices)
            check(origin+policy+":現前各20変化", (len(current_indices), len(previous_indices)), (20, 20))
            check(origin+policy+":現前和集合21変化", len(union), 21)
            check(origin+policy+":脱落は一足", len(dropped), 1)
            present = all((case["場"], index) in panel_map for index in union)
            check(origin+policy+":機序出典が全保存", present, True)
            if not present or len(dropped) != 1:
                continue
            rows = {index: panel_map[case["場"], index] for index in union}
            valid = all(r["数量入力可"] and r["分類方向"] in (-1, 0, 1)
                and isinstance(r["観測差分量"], (int, float)) and math.isfinite(r["観測差分量"]) and r["観測差分量"] >= 0 for r in rows.values())
            check(origin+policy+":分類と量が利用可能", valid, True)
            if not valid:
                continue
            old = rows[next(iter(dropped))]
            side = case["side"]
            def same_positive(indices: list[int]) -> bool:
                """保存qの完全な正同値だけを数え、許容幅を足さない。

                引数: indices(list[int])は現20又は和集合21の足番号。
                返り値: boolは全qが同じ正量。BやΔBを再計算しない。
                """
                values = [rows[i]["観測差分量"] for i in indices]
                return bool(values and values[0] > 0 and all(v == values[0] for v in values))
            signs_map = {1: "正", 0: "0", -1: "負"}
            tags = {"当足分類の実方向": signs_map[side*current["分類方向"]],
                "窓落ち分類の実方向": signs_map[side*old["分類方向"]],
                "当足q0": current["観測差分量"] == 0, "窓落ちq0": old["観測差分量"] == 0,
                "現20が同じ正量": same_positive(current_indices), "両窓21が同じ正量": same_positive(union)}
            tagged.append((case, tags))
        for period in PERIODS:
            for axis in ("当足分類の実方向", "窓落ち分類の実方向", "当足q0", "窓落ちq0", "現20が同じ正量", "両窓21が同じ正量"):
                groups = ("正", "0", "負") if axis.endswith("実方向") else (True, False)
                for group in groups:
                    own = [r for r, tags in tagged if r["期間"] == period and tags[axis] == group]
                    mechanism.append({"期間": period, "入口": policy, "分母": policy+"純入口", "区分軸": axis, "当時区分": group, **entry_summary(own)})
                check(policy+period+axis+":各軸は純入口を分割", sum(r["候補数"] for r in mechanism if r["入口"] == policy and r["期間"] == period and r["区分軸"] == axis), sum(r["期間"] == period for r in by_policy[policy].values()))

    # ----------------------------------------
    # 同じ純入口でも、費用後起動による再参加と選別後の追加参加は別に残す。
    trades = [{**t, "候補ID": d["候補ID"]} for d in details for t in d["取引"]]
    check("場候補一意", len({(d["候補ID"], d["場"]) for d in details}), len(details))
    handling = {(d["候補ID"], s["イベントID"]): s["取扱"] for d in details for s in d["入口取扱"]}
    for trade in trades:
        row = case_map[trade["入口イベントID"]]
        for field in ("新規時計秒", "新規原板行", "新規価格"):
            check("実新規と同時点case:"+field, trade[field], row[field])
        check("実入口ATRとcase", trade["入口ATR"], row["atr"])
    participation, episodes, recovery, qualities = [], [], [], []
    for period in PERIODS:
        own_trades = {cid: [t for t in trades if t["候補ID"] == cid and t["期間"] == period] for cid in CANDIDATES}
        strict = {cid: {strict_identity(t): t for t in own_trades[cid]} for cid in CANDIDATES}
        origins = {cid: {case_map[t["入口イベントID"]]["旧R0イベントID"]: t for t in own_trades[cid]} for cid in CANDIDATES}
        for cid in CANDIDATES:
            check(cid+period+":厳密新規一意", len(strict[cid]), len(own_trades[cid]))
            check(cid+period+":元登録一意", len(origins[cid]), len(own_trades[cid]))
        for title, left_id, right_id in PAIRS:
            left, right = strict[left_id], strict[right_id]
            common, removed, added = left.keys() & right.keys(), left.keys()-right.keys(), right.keys()-left.keys()
            costs = []
            for fee in (0, 5, 10):
                field = f"追加滑り{fee}pt純損益円"
                difference = sum(right[k][field]-left[k][field] for k in common)
                left_cash, right_cash = H.cash([left[k] for k in removed], fee), H.cash([right[k] for k in added], fee)
                total = H.cash(own_trades[right_id], fee)-H.cash(own_trades[left_id], fee)
                check(period+title+str(fee)+":全費用差分解", total, difference-left_cash+right_cash)
                costs.append({"片道追加pt": fee, "総差円_右引く左": total,
                    "同約定ATR共通出口差円": difference, "左のみ損益円": left_cash, "右のみ損益円": right_cash})
            def counterpart(rows: list[dict], cid: str) -> dict:
                """純不採用と実建玉抑止を相手側の保存取扱から分ける。

                引数: rows(list[dict])は片側取引、cid(str)は相手候補。
                返り値: dictは取扱件数。取扱記録のない純非採用も明示する。
                """
                policy = cid.split("_")[1]
                values = []
                for trade in rows:
                    origin = case_map[trade["入口イベントID"]]["旧R0イベントID"]
                    if origin not in by_policy[policy]:
                        values.append("純入口不採用")
                    else:
                        values.append(handling.get((cid, by_policy[policy][origin]["イベントID"]), "取扱記録なし"))
                return dict(Counter(values))
            exit_diff = sum(any(left[k][f] != right[k][f] for f in ("返済時計秒", "返済原板行", "返済価格", "返済理由")) for k in common)
            if title != "費用起動変更":
                check(period+title+":共通XF出口属性同値", exit_diff, 0)
                for item in costs:
                    check(period+title+str(item["片道追加pt"])+":共通XF費用差0", item["同約定ATR共通出口差円"], 0)
            participation.append({"期間": period, "比較": title, "左": left_id, "右": right_id,
                "同約定ATR共通実新規数": len(common), "共通出口属性差数": exit_diff,
                "左のみ": H.operation_summary([left[k] for k in removed]), "右のみ": H.operation_summary([right[k] for k in added]),
                "左のみの相手取扱": counterpart([left[k] for k in removed], right_id),
                "右のみの相手取扱": counterpart([right[k] for k in added], left_id), "費用別": costs})
            lm, rm = origins[left_id], origins[right_id]
            shared = lm.keys() & rm.keys()
            episodes.append({"期間": period, "比較": title, "左": left_id, "右": right_id,
                "両実参加元登録数": len(shared), "同約定ATR数": sum(strict_identity(lm[k]) == strict_identity(rm[k]) for k in shared),
                "左のみ元登録数": len(lm.keys()-rm.keys()), "右のみ元登録数": len(rm.keys()-lm.keys()),
                "新規価格差pt_右引く左": H.distribution([(1 if lm[k]["方向"] == "買い" else -1)*(rm[k]["新規価格"]-lm[k]["新規価格"]) for k in shared]),
                "新規時計差秒_右引く左": H.distribution([rm[k]["新規時計秒"]-lm[k]["新規時計秒"] for k in shared])})
        for cid in CANDIDATES:
            rows = own_trades[cid]
            successes = [t for t in rows if case_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
            armed = [t for t in rows if t["追尾起動"]]
            reds = [t for t in armed if t["起動後純赤字"]]
            nominal = lambda t: (1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"])
            zero, adverse, positive = (sum(test(nominal(t)) for t in reds) for test in (lambda v: v == 0, lambda v: v < 0, lambda v: v > 0))
            check(cid+period+":起動後基準赤字内訳", len(reds), zero+adverse+positive)
            recovery.append({"候補ID": cid, "期間": period, "現在方針": cid != CANDIDATES[0], **H.operation_summary(rows),
                "対応仮250数": len(successes), "仮250判定前返済数": sum((t["返済時計秒"], t["返済原板行"]) < (case_map[t["入口イベントID"]]["判定時計秒"], case_map[t["入口イベントID"]]["判定原板行"]) for t in successes),
                "実保有MFE250数": sum(t["観測最大順行pt"] >= 250 for t in rows), "起動数": len(armed),
                "起動後基準赤字数": len(reds), "名目同値費用赤字数": zero, "不利返済赤字数": adverse,
                "正名目利益の基準費用負け数": positive,
                "起動後正名目利益の追加5費用負け数": sum(nominal(t) > 0 and t["追加滑り5pt純損益円"] < 0 for t in armed)})
    if result is not None:
        check("四運用順", [r["候補ID"] for r in result["結果"]], list(CANDIDATES))
        check("三入口順", [r["入口ID"] for r in result["入口評価"]], ["3分_"+p for p in POLICIES])
        for row in result["入口評価"]:
            for period in PERIODS:
                summary = entry_summary([r for r in cases if r["入口ID"] == row["入口ID"] and r["期間"] == period])
                for field in ("候補数", "約定候補数", "順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "確認率"):
                    check(row["入口ID"]+period+field, row[period][field], summary[field])
        for row in result["結果"]:
            for period in PERIODS:
                op = row[period]["運用"]
                own = [t for t in trades if t["候補ID"] == row["候補ID"] and t["期間"] == period]
                check(row["候補ID"]+period+":実完結数", op["完結取引数"], len(own))
                for fee in (0, 5, 10):
                    check(row["候補ID"]+period+str(fee)+":保存会計合計", op[f"追加{fee}pt純損益円"], H.cash(own, fee))
                qualities.append({"候補ID": row["候補ID"], "期間": period,
                    **{k: op[k] for k in ("品質注意場数", "未解消場数", "EOF期限未達場数")},
                    "観測純額円": {str(f): op[f"追加{f}pt純損益円"] for f in (0, 5, 10)},
                    "全体確定対象円": {str(f): op[f"追加{f}pt確定対象円"] for f in (0, 5, 10)}})
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "モデル再計算": False, "指標再計算": False, "先着再計算": False, "運用再生": False, "新閾値選別": False,
        "原発動と三入口": stages, "V0の量比準備二群": preparation, "V1の量比差三群": signs,
        "入口追加比較": subsets, "量比全足品質": panel_quality, "当足と窓落ちの機序": mechanism, "実参加比較": participation,
        "同元登録の実参加対応": episodes, "候補別回収": recovery, "品質と確定額": qualities,
        "限界": ["V0は旧29の数量準備を含む旧R0。量なし価格基準ではない。",
            "旧参考→V0XFは起動方針、V0XF→V1XFは準備、V1XF→V2XFは値選別。",
            "同時点の純subsetと、実建玉が空いて追加される実参加を分ける。",
            "ΔBは古い分類の脱落でも変わり、当足量増勢/新規参加者/純資金流入を実測しない。",
            "現20同正量は現在Bの方向回数化、和集合21同正量はΔBの回数変化への退化で、別の旗。",
            "仮125/250と実返済・費用後勝率は別。未約定/期限/観測不足を残す。",
            "取消理由は保存取扱の対応。ここで全気配から再生成していない。"]}


def compare_control(details: list[dict], trace: list[dict], control: dict,
                    old_details: list[dict], old_trace: list[dict]) -> dict:
    """V0X0の全属性を識別文字列だけ戻して旧29R0X0へ照合する。

    引数: details/trace(list[dict])は36保存物、control(dict)は主対照証明、old_details/old_trace(list[dict])は旧29保存物。
    返り値: dictは全ledger/trace直接比較。数値や属性を除外しない。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """全件相違を内容指紋で小さく記録する。

        引数: name(str)は項目、actual/expected(object)は保存値。
        返り値: None。属性を消して一致させない。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            errors.append({"項目": name, "実値内容SHA256": H.canonical(actual), "期待値内容SHA256": H.canonical(expected)})

    new = {r["場"]: r for r in details if r["候補ID"] == CANDIDATES[0]}
    old = {r["場"]: r for r in old_details if r["候補ID"] == "3分_R0_X0"}
    nl, ol = defaultdict(list), defaultdict(list)
    for row in trace:
        if row["候補ID"] == CANDIDATES[0]:
            nl[row["場"]].append(row)
    for row in old_trace:
        if row["候補ID"] == "3分_R0_X0":
            ol[row["場"]].append(row)
    proofs = {r["場"]: r for r in control["照合"]}
    check("旧X0全場集合", sorted(new), sorted(old))
    check("主対照全場集合", sorted(new), sorted(proofs))
    check("主対照成功", control["全件一致"], True)
    check("主旧先着同値", control["旧先着全件同値"], True)
    check("主対照場数", control["場候補数"], len(new))
    for session in new.keys() & old.keys() & proofs.keys():
        detail, log = old_identity(new[session]), old_identity(nl[session])
        check(session+":全ledger", detail, old[session])
        check(session+":全trace", log, ol[session])
        check(session+":主ledger成功", proofs[session]["全運用同値"], True)
        check(session+":主trace成功", proofs[session]["全追尾同値"], True)
        check(session+":主ledger指紋", proofs[session]["旧識別子全運用内容SHA256"], H.canonical(detail))
        check(session+":主trace指紋", proofs[session]["旧識別子追尾内容SHA256"], H.canonical(log))
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "場候補数": len(new), "全ledger直接比較": True, "全追尾直接比較": True,
        "識別子正規化": "文字列_V0を_R0へ", "属性除外": []}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式結果完成後に限り、共有先着と四明細の保存値を診断する。

    引数: study/work(Path)は36正式/作業先。
    返り値: dictは診断。準備の採否だけを読み、旧原P/contextを転記しない。
    """
    if not (study/"結果.json").is_file():
        raise ValueError("正式結果完成前に保存診断を実行しません")
    reference, control_ref = (H.read(study/n) for n in ("入口参照.json", "対照参照.json"))
    shared = {Path(r["パス"]).name: ROOT/r["パス"] for r in reference["共有明細"]}
    for ref in (reference, control_ref):
        for item in ref["共有明細"]:
            if H.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
                raise ValueError("旧29共有参照の版差")
    prepare = H.read(work/"準備点検.json")
    if prepare["ラベル計算"] is not False or prepare["損益計算"] is not False or prepare["旧29R0純登録同値"] is not True:
        raise ValueError("旧R0非損益準備が未完")
    decisions = [{"期間": r["期間"], **d} for r in prepare["準備"] for d in r["採否"]]
    panels, cases, details, trace = (H.read(work/n) for n in ("量比.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz"))
    result, control = H.read(study/"結果.json"), H.read(study/"V0対照同値.json")
    for name in ("入口参照.json", "対照参照.json"):
        if control[name[:-5]+"SHA256"] != H.sha(study/name):
            raise ValueError("主V0対照の参照版差")
    output = analyze(cases, decisions, panels, details, result, H.read(shared["入口事例.jsonl.gz"]))
    comparison = compare_control(details, trace, control, H.read(shared["全運用詳細.jsonl.gz"]), H.read(shared["追尾.jsonl.gz"]))
    output["旧29V0X0全属性対照"] = {k: v for k, v in comparison.items() if k not in ("全件一致", "不一致")}
    output["照合項目数"] += comparison["照合項目数"]
    output["不一致"] += comparison["不一致"]
    output["不一致数"] = len(output["不一致"])
    output["全件一致"] = not output["不一致"]
    output["全66場既使用"] = True
    paths = [Path(__file__), HELPER, ROOT/"scripts/SAR追尾/対応診断.py",
        *[study/n for n in ("条件.json", "固定.json", "結果.json", "入力台帳.json", "入口参照.json", "対照参照.json", "V0対照同値.json")],
        *[work/n for n in ("準備点検.json", "診断予定.json", "量比.jsonl.gz", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")], *shared.values()]
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix(): H.sha(p) for p in paths}
    output["参照SHA256"] = {n: H.sha(study/n) for n in ("結果.json", "入口参照.json", "対照参照.json")}
    (work/"対応診断.json").write_text(H.json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if not output["全件一致"]:
        raise RuntimeError("量比保存物の対応に不一致")
    return output


def main() -> None:
    """保存値の後段診断だけをCLIから起動する。

    引数: なし。--study/--workはPath。
    返り値: None。市場prepare/数値/先着/運用を起動しない。
    """
    parser = argparse.ArgumentParser(description="価格失敗と量比の方向変化・保存対応診断")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    data = run(args.study.resolve(), args.work.resolve())
    print(H.json.dumps({k: data[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
