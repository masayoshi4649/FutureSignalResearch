"""同じ登録からの即時/指値を、約定群選別・取得方法・実参加へ分ける。"""

import argparse
from collections import Counter, defaultdict
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00034_CCI突破の水準指値"
WORK = ROOT/"work/突破指値/00034"
HELPER = ROOT/"scripts/SAR追尾/対応診断.py"
POLICIES = ("E0", "E1")
CANDIDATES = ("3分_E0_XF", "3分_E1_XF")
PERIODS = ("学習", "条件選択", "後続検査")

spec = importlib.util.spec_from_file_location("突破指値の保存統計補助", HELPER)
H = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = H
spec.loader.exec_module(H)


def entry_summary(rows: list[dict]) -> dict:
    """全仮約定を分母に、未約定を別記した先着保存値をまとめる。

    引数: rows(list[dict])は34の新規先着case。
    返り値: dictは要求・約定・五分類・率。先着経路を再計算しない。
    """
    labels = Counter(r["ラベル"] for r in rows)
    n = sum(r["新規価格"] is not None for r in rows)
    return {"候補数": len(rows), "約定候補数": n,
        **{k: labels[k] for k in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "対象外")},
        "確認率": labels["順行先着"]/n if n else None,
        "登録あたり約定率": n/len(rows) if rows else None,
        "登録あたり250先着率": labels["順行先着"]/len(rows) if rows else None}


def fill_key(row: dict) -> tuple:
    """同時/待機の比較に価格時計と原行をともに使う。

    引数: row(dict)は約定済みcase。
    返り値: tupleは新規時計/原行。未約定へ仮のkeyを補わない。
    """
    if row["新規価格"] is None:
        raise ValueError("未約定に新規keyはない")
    return row["新規時計秒"], row["新規原板行"]


def strict_identity(trade: dict) -> tuple:
    """同じ実新規・同じATR/Dだけを共通出口の比較対象にする。

    引数: trade(dict)は完結取引。
    返り値: tupleは場/side/key/価格/入口ATR/D。元登録一致とは別の条件。
    """
    return (*H.identity(trade), trade["入口ATR"], trade["追尾距離pt"])


def analyze(cases: list[dict], details: list[dict], result: dict | None = None) -> dict:
    """保存caseの登録対応と、実新規の費用差を別々に分解する。

    引数: cases/details(list[dict])は34新case/運用詳細、result(dict|None)は正式結果又は人工時の未指定。
    返り値: dictは照合・三群先着・待機/未約定・実参加・回収の小診断。市場/運用を再生しない。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """保存対応の相違を消さずに残す。

        引数: name(str)は項目、actual/expected(object)は保存値と期待値。
        返り値: None。巨大な相違は内容指紋へ置き換える。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            small = []
            for value in (actual, expected):
                body = H.json.dumps(value, ensure_ascii=False, default=str)
                small.append(value if len(body) <= 1500 else {"内容SHA256": H.canonical(value)})
            errors.append({"項目": name, "実値": small[0], "期待値": small[1]})

    maps = {p: {r["旧C0イベントID"]: r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    for policy in POLICIES:
        check(policy+"登録一意", len(maps[policy]), sum(r["入口ID"] == "3分_"+policy for r in cases))
    check("両案の元登録全集合", set(maps["E0"]) == set(maps["E1"]), True)
    all_cases = {r["イベントID"]: r for r in cases}
    check("新caseイベント一意", len(all_cases), len(cases))
    for origin in maps["E0"].keys() & maps["E1"].keys():
        left, right = maps["E0"][origin], maps["E1"][origin]
        for field in ("場", "期間", "side", "要求時計秒", "要求原板行", "atr"):
            check(origin+":共通登録:"+field, left[field], right[field])
        check(origin+":共通登録出典", left["登録出典"], right["登録出典"])
        check(origin+":指値根拠固定", right["指値根拠"], right["登録出典"])
        target = right["登録出典"]["前20最高H"] if right["side"] == 1 else right["登録出典"]["前20最安L"]
        check(origin+":登録時の旧高安指値", right["新規指値価格"], target)
        check(origin+":E0に指値なし", "新規指値価格" not in left and "指値根拠" not in left, True)
        check(origin+":指値約定なら即時も仮約定", right["新規価格"] is None or left["新規価格"] is not None, True)
        if left["新規価格"] is not None and right["新規価格"] is not None:
            check(origin+":指値上限内のBBO価格", right["side"]*(right["新規価格"]-target) <= 0, True)
            check(origin+":指値の時計順", fill_key(right) >= fill_key(left), True)
            if fill_key(right) == fill_key(left):
                check(origin+":同keyは同価格", left["新規価格"], right["新規価格"])
    if result is not None:
        check("二運用順", [r["候補ID"] for r in result["結果"]], list(CANDIDATES))
        check("二入口順", [r["入口ID"] for r in result["入口評価"]], ["3分_E0", "3分_E1"])
        check("全66場既使用", result["全66場既使用"], True)
        for source in result["入口評価"]:
            for period in PERIODS:
                summary = entry_summary([r for r in cases if r["入口ID"] == source["入口ID"] and r["期間"] == period])
                for field in ("候補数", "約定候補数", "順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "確認率"):
                    check(source["入口ID"]+period+":先着保存集計:"+field, source[period][field], summary[field])
                check(source["入口ID"]+period+":純登録対象外なし", summary["対象外"], 0)

    # ----------------------------------------
    # A即時全体→B指値約定集合の即時→C同集合の指値、を同登録で対応する。
    three_groups, fill_groups, missed, paired_observation = [], [], [], []
    for period in PERIODS:
        left = {k: r for k, r in maps["E0"].items() if r["期間"] == period}
        right = {k: r for k, r in maps["E1"].items() if r["期間"] == period}
        available = [k for k in left if right[k]["新規価格"] is not None]
        for tag, own in (("A_E0全登録", list(left.values())),
                         ("B_E1約定集合のE0", [left[k] for k in available]),
                         ("C_同集合のE1", [right[k] for k in available])):
            three_groups.append({"期間": period, "群": tag, **entry_summary(own)})
        tags = {"同時約定": [], "待機約定": [], "E0のみ約定": [], "両未約定": []}
        for origin, lrow in left.items():
            rrow = right[origin]
            if rrow["新規価格"] is None:
                tags["両未約定" if lrow["新規価格"] is None else "E0のみ約定"].append(origin)
            elif fill_key(lrow) == fill_key(rrow) and lrow["新規価格"] == rrow["新規価格"]:
                tags["同時約定"].append(origin)
            else:
                tags["待機約定"].append(origin)
        check(period+":約定四区分総数", sum(map(len, tags.values())), len(left))
        for tag, origins in tags.items():
            fill_groups.append({"期間": period, "約定対応": tag, "元登録数": len(origins),
                "E0": entry_summary([left[k] for k in origins]), "E1": entry_summary([right[k] for k in origins])})
        unfilled = [k for k in left if right[k]["新規価格"] is None]
        missed.append({"期間": period, "E1未約定登録数": len(unfilled),
            "同登録E0の先着": entry_summary([left[k] for k in unfilled]),
            "E1未約定理由": dict(Counter(right[k]["理由"] for k in unfilled)),
            "未約定の観測区分": dict(Counter("観測正常BBOあり・指値不成立" if left[k]["新規価格"] is not None else "共通期間内の正常BBOなし" for k in unfilled)),
            "解釈": "旧即時の仮250は参加を断った機会。指値の実現損失/実現可能利益とはしない"})
        paired_observation.append({"期間": period, "両仮約定元登録数": len(available),
            "最初適格BBOの指値条件": dict(Counter("正常BBOなし" if r["新規価格"] is None else "成立" if r["side"]*(r["新規価格"]-right[k]["新規指値価格"]) <= 0 else "不成立" for k, r in left.items())),
            "同秒別行待機数": sum(fill_key(right[k]) > fill_key(left[k]) and right[k]["新規時計秒"] == left[k]["新規時計秒"] for k in available),
            "登録からE1仮約定秒": H.distribution([right[k]["新規時計秒"]-right[k]["要求時計秒"] for k in available]),
            "E0からE1仮約定秒": H.distribution([right[k]["新規時計秒"]-left[k]["新規時計秒"] for k in available]),
            "実方向の取得価格改善pt": H.distribution([left[k]["side"]*(left[k]["新規価格"]-right[k]["新規価格"]) for k in available]),
            "先着ラベル対応": dict(Counter(left[k]["ラベル"]+"→"+right[k]["ラベル"] for k in available))})

    # ----------------------------------------
    # 同じ元登録の別約定と、同じ実新規/ATR/Dの出口比較を混同しない。
    trades = [{**t, "候補ID": d["候補ID"]} for d in details for t in d["取引"]]
    by_detail = {(d["候補ID"], d["場"]): d for d in details}
    check("運用場候補一意", len(by_detail), len(details))
    handling = {(d["候補ID"], s["イベントID"]): s["取扱"] for d in details for s in d["入口取扱"]}
    for trade in trades:
        own = all_cases[trade["入口イベントID"]]
        for field in ("新規時計秒", "新規原板行", "新規価格"):
            check("実新規と仮case:"+field, trade[field], own[field])
        check("実新規ATRと登録ATR", trade["入口ATR"], own["atr"])
        if trade["候補ID"] == "3分_E1_XF":
            check("実指値価格とcase", trade["新規指値価格"], own["新規指値価格"])
            check("実指値根拠とcase", trade["指値根拠"], own["指値根拠"])
        else:
            check("即時対照へ指値属性を混ぜない", "新規指値価格" not in trade and "指値根拠" not in trade, True)
    qualities = []
    if result is not None:
        for candidate in result["結果"]:
            for period in PERIODS:
                op = candidate[period]["運用"]
                own = [t for t in trades if t["候補ID"] == candidate["候補ID"] and t["期間"] == period]
                check(candidate["候補ID"]+period+":保存完結数", op["完結取引数"], len(own))
                for fee in (0, 5, 10):
                    check(candidate["候補ID"]+period+str(fee)+":保存会計合計", op[f"追加{fee}pt純損益円"], H.cash(own, fee))
                qualities.append({"候補ID": candidate["候補ID"], "期間": period,
                    **{k: op[k] for k in ("品質注意場数", "未解消場数", "EOF期限未達場数")},
                    "観測純額円": {str(f): op[f"追加{f}pt純損益円"] for f in (0, 5, 10)},
                    "全体確定対象円": {str(f): op[f"追加{f}pt確定対象円"] for f in (0, 5, 10)}})
    participation, real_episodes, recovery = [], [], []
    for period in PERIODS:
        own = {p: [t for t in trades if t["候補ID"] == cid and t["期間"] == period] for p, cid in zip(POLICIES, CANDIDATES)}
        actual = {p: {strict_identity(t): t for t in own[p]} for p in POLICIES}
        episodes = {p: {all_cases[t["入口イベントID"]]["旧C0イベントID"]: t for t in own[p]} for p in POLICIES}
        for policy in POLICIES:
            check(period+policy+":実新規一意", len(actual[policy]), len(own[policy]))
            check(period+policy+":実元登録一意", len(episodes[policy]), len(own[policy]))
        lm, rm = actual["E0"], actual["E1"]
        common, left_only, right_only = lm.keys() & rm.keys(), lm.keys()-rm.keys(), rm.keys()-lm.keys()
        cost_rows = []
        for fee in (0, 5, 10):
            field = f"追加滑り{fee}pt純損益円"
            same = sum(rm[k][field]-lm[k][field] for k in common)
            total = H.cash(own["E1"], fee)-H.cash(own["E0"], fee)
            lcash, rcash = H.cash([lm[k] for k in left_only], fee), H.cash([rm[k] for k in right_only], fee)
            check(period+str(fee)+":全費用差分解", total, same-lcash+rcash)
            cost_rows.append({"片道追加pt": fee, "総差円_E1引くE0": total, "同約定ATR共通出口差円": same,
                "E0のみ損益円": lcash, "E1のみ損益円": rcash})
        def other_handling(rows: list[dict], policy: str, cid: str) -> dict:
            """片側取引の元登録に対応する相手の取扱を要約する。

            引数: rows(list[dict])は片側取引、policy/cid(str)は相手案と運用ID。
            返り値: dictは抑止/未約定等の件数。注文待機を建玉と混ぜない。
            """
            return dict(Counter(handling.get((cid, maps[policy][all_cases[t["入口イベントID"]]["旧C0イベントID"]]["イベントID"]), "取扱記録なし") for t in rows))
        participation.append({"期間": period, "同約定ATR共通実新規数": len(common),
            "共通の元登録相違数": sum(all_cases[lm[k]["入口イベントID"]]["旧C0イベントID"] != all_cases[rm[k]["入口イベントID"]]["旧C0イベントID"] for k in common),
            "共通出口属性差数": sum(any(lm[k][field] != rm[k][field] for field in ("返済時計秒", "返済原板行", "返済価格", "返済理由")) for k in common),
            "E0のみ": H.operation_summary([lm[k] for k in left_only]), "E1のみ": H.operation_summary([rm[k] for k in right_only]),
            "E0のみの相手取扱": other_handling([lm[k] for k in left_only], "E1", CANDIDATES[1]),
            "E1のみの相手取扱": other_handling([rm[k] for k in right_only], "E0", CANDIDATES[0]), "費用別": cost_rows})
        le, re = episodes["E0"], episodes["E1"]
        shared = le.keys() & re.keys()
        real_episodes.append({"期間": period, "両実参加元登録数": len(shared),
            "同約定ATR数": sum(strict_identity(le[k]) == strict_identity(re[k]) for k in shared),
            "異約定ATR数": sum(strict_identity(le[k]) != strict_identity(re[k]) for k in shared),
            "E0のみ元登録数": len(le.keys()-re.keys()), "E1のみ元登録数": len(re.keys()-le.keys()),
            "同元登録の実方向取得価格改善pt": H.distribution([(1 if le[k]["方向"] == "買い" else -1)*(le[k]["新規価格"]-re[k]["新規価格"]) for k in shared]),
            "同元登録の新規待機秒": H.distribution([re[k]["新規時計秒"]-le[k]["新規時計秒"] for k in shared]),
            "同元登録の追加5pt純額差円": H.distribution([re[k]["追加滑り5pt純損益円"]-le[k]["追加滑り5pt純損益円"] for k in shared]),
            "解釈": "別価格/時計の同episode差は取得方法と待機を含む方針差。価格だけ/出口だけの効果ではない"})
        for policy, cid in zip(POLICIES, CANDIDATES):
            rows = own[policy]
            success = [t for t in rows if all_cases[t["入口イベントID"]]["ラベル"] == "順行先着"]
            armed = [t for t in rows if t["追尾起動"]]
            red = [t for t in armed if t["起動後純赤字"]]
            zero = sum(t["返済価格"] == t["新規価格"] for t in red)
            adverse = sum((1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"]) < 0 for t in red)
            check(cid+period+":起動後基準赤字内訳", len(red), zero+adverse)
            recovery.append({"候補ID": cid, "期間": period, **H.operation_summary(rows),
                "対応仮250数": len(success), "仮250判定前返済数": sum((t["返済時計秒"], t["返済原板行"]) < (all_cases[t["入口イベントID"]]["判定時計秒"], all_cases[t["入口イベントID"]]["判定原板行"]) for t in success),
                "実保有MFE250数": sum(t["観測最大順行pt"] >= 250 for t in rows), "起動数": len(armed),
                "起動後基準赤字数": len(red), "名目同値費用赤字数": zero, "不利返済赤字数": adverse})
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "モデル再計算": False, "先着再計算": False, "運用再生": False, "新閾値選別": False,
        "先着三群": three_groups, "元登録の約定四区分": fill_groups, "指値未約定の即時機会": missed,
        "両仮約定の待機と取得価格": paired_observation, "実参加比較": participation,
        "同元登録の実参加対応": real_episodes, "候補別回収": recovery, "品質と確定額": qualities,
        "限界": ["A→Bは結果後の指値約定群選別、B→Cは同集合の別取得方法。単独の価格効果としない。",
            "未約定時のE0仮250は取り逃した機会の記述で、E1が実現できた利益とはしない。",
            "全仮約定率と登録あたり約定/250を併記し、期限/不足を率の分母から除かない。",
            "純先着は建玉抑止と独立、実参加は建玉/新規待機/返済待機等を別記する。",
            "同実約定key/価格かつ同ATR/Dだけを共通出口比較とする。異約定同episodeの差を出口効果にしない。",
            "追加5/10ptは同約定の費用ストレス。指値上限を越える新規価格へ変更して成立させた意味ではない。",
            "ラージBBO指値代理で、mini/microのキュー/部分約定/実約定可能性は未確認。"]}


def rename(value: object) -> object:
    """E0識別文字列だけを旧33T0へ戻す。

    引数: value(object)は新保存JSON値。
    返り値: objectは価格・時点・会計・属性を除外しない正規化値。
    """
    if isinstance(value, dict):
        return {k: rename(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rename(v) for v in value]
    return value.replace("_E0", "_T0") if isinstance(value, str) else value


def compare_control(details: list[dict], trace: list[dict], control: dict,
                    old_details: list[dict], old_trace: list[dict]) -> dict:
    """新E0の全属性を旧33T0_XFへ直接照合する。

    引数: details/trace(list[dict])は新保存物、control(dict)は主対照証明、old_details/old_trace(list[dict])は旧33保存物。
    返り値: dictは照合と不一致。モデル再生は呼ばない。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """大明細を複製せず合否を記録する。

        引数: name(str)は項目、actual/expected(object)は保存値。
        返り値: None。不一致が大きい場合は内容指紋だけを残す。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            errors.append({"項目": name, "実値内容SHA256": H.canonical(actual), "期待値内容SHA256": H.canonical(expected)})

    left = {r["場"]: r for r in details if r["候補ID"] == "3分_E0_XF"}
    right = {r["場"]: r for r in old_details if r["候補ID"] == "3分_T0_XF"}
    nl, ol = defaultdict(list), defaultdict(list)
    for row in trace:
        if row["候補ID"] == "3分_E0_XF":
            nl[row["場"]].append(row)
    for row in old_trace:
        if row["候補ID"] == "3分_T0_XF":
            ol[row["場"]].append(row)
    proofs = {r["場"]: r for r in control["照合"]}
    check("E0旧33全場集合", sorted(left), sorted(right))
    check("主E0対照全場集合", sorted(proofs), sorted(left))
    check("主E0対照成功", control["全件一致"], True)
    check("主E0旧先着同値", control["旧先着全件同値"], True)
    check("主E0対照場数", control["場候補数"], len(left))
    for session in left.keys() & right.keys() & proofs.keys():
        detail, log = rename(left[session]), rename(nl[session])
        check(session+":E0全ledger", detail, right[session])
        check(session+":E0全trace", log, ol[session])
        check(session+":主E0 ledgerSHA", proofs[session]["旧識別子全運用内容SHA256"], H.canonical(detail))
        check(session+":主E0 traceSHA", proofs[session]["旧識別子追尾内容SHA256"], H.canonical(log))
        check(session+":主E0 ledger成功", proofs[session]["全運用同値"], True)
        check(session+":主E0 trace成功", proofs[session]["全追尾同値"], True)
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "場候補数": len(left), "識別子正規化": "文字列_E0→_T0のみ", "属性除外": [], "全明細直接比較": True, "全追尾直接比較": True}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式完了通知後に保存物だけを読み、診断を保存する。

    引数: study/work(Path)は34正式/作業保存先。
    返り値: dictは診断。不一致は小JSONを保存してから例外にする。
    """
    if not (study/"結果.json").is_file():
        raise ValueError("正式結果完成前に対応診断を実行しません")
    reference = H.read(study/"対照参照.json")
    shared = {Path(r["パス"]).name: ROOT/r["パス"] for r in reference["共有明細"]}
    for item in reference["共有明細"]:
        if H.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
            raise ValueError("旧33対照の保存版に差")
    cases, details, trace = (H.read(work/n) for n in ("入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz"))
    control_path = study/"E0対照同値.json"
    control = H.read(control_path)
    if control["対照参照SHA256"] != H.sha(study/"対照参照.json"):
        raise ValueError("E0主対照の参照版差")
    output = analyze(cases, details, H.read(study/"結果.json"))
    counterpart = compare_control(details, trace, control, H.read(shared["全運用詳細.jsonl.gz"]), H.read(shared["追尾.jsonl.gz"]))
    output["E0旧33対照"] = {k: v for k, v in counterpart.items() if k not in ("不一致", "全件一致")}
    output["照合項目数"] += counterpart["照合項目数"]
    output["不一致"] += counterpart["不一致"]
    output["不一致数"] = len(output["不一致"])
    output["全件一致"] = not output["不一致"]
    output["全66場既使用"] = True
    paths = [Path(__file__), HELPER, *[study/n for n in ("条件.json", "固定.json", "結果.json", "入力台帳.json", "入口参照.json", "対照参照.json", "E0対照同値.json")],
        *[work/n for n in ("診断予定.json", "入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")], *shared.values()]
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix(): H.sha(p) for p in paths}
    output["入口参照SHA256"] = H.sha(study/"入口参照.json")
    output["対照参照SHA256"] = H.sha(study/"対照参照.json")
    (work/"対応診断.json").write_text(H.json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if not output["全件一致"]:
        raise RuntimeError("保存物の対応に不一致")
    return output


def main() -> None:
    """正式保存物の後段診断だけをCLI起動する。

    引数: なし。CLIは--study/--work。
    返り値: None。市場prepare/先着/運用は実行しない。
    """
    parser = argparse.ArgumentParser(description="CCI突破の水準指値・保存対応診断")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    output = run(args.study.resolve(), args.work.resolve())
    print(H.json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
