"""保存済み同時点CLV選別を、入口集合・実参加・回収へ分けて対応する。"""

import argparse
from collections import Counter, defaultdict
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
WORK = ROOT/"work/終値位置/00033"
HELPER = ROOT/"scripts/SAR追尾/対応診断.py"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("T0", "T1")
CANDIDATES = ("3分_T0_X0", "3分_T0_XF", "3分_T1_XF")
PAIRS = (("費用起動変更", CANDIDATES[0], CANDIDATES[1]), ("CLV追加", CANDIDATES[1], CANDIDATES[2]))

spec = importlib.util.spec_from_file_location("終値位置の保存数値集計", HELPER)
H = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = H
spec.loader.exec_module(H)


def old_identity(value: object) -> object:
    """T0の識別文字列だけを固定31C0へ戻す。

    引数: value(object)は保存JSON値。
    返り値: objectは数値・属性を除外しない正規化値。主コードを呼ばない。
    """
    if isinstance(value, dict):
        return {k: old_identity(v) for k, v in value.items()}
    if isinstance(value, list):
        return [old_identity(v) for v in value]
    return value.replace("_T0", "_C0") if isinstance(value, str) else value


def old_event(event: str) -> str:
    """採用二案のイベントIDを共有caseのC0 IDへ対応させる。

    引数: event(str)は末尾T0/T1の新イベントID。
    返り値: strは旧C0 ID。不明な候補は拒否する。
    """
    if not event.endswith(("_T0", "_T1")):
        raise ValueError("二案のイベントID以外")
    return event[:-3]+"_C0"


def entry_summary(rows: list[dict]) -> dict:
    """仮約定全件を分母に、共有先着ラベルだけを集計する。

    引数: rows(list[dict])は旧C0の採用case。
    返り値: dictは要求・仮約定・先着・期限・不足・未約定。先着再計算は行わない。
    """
    labels = Counter(r["ラベル"] for r in rows)
    filled = sum(r["新規価格"] is not None for r in rows)
    return {"候補数": len(rows), "約定候補数": filled,
        **{k: labels[k] for k in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "対象外")},
        "確認率": labels["順行先着"]/filled if filled else None}


def group(row: dict) -> str:
    """保存済みの有効性と実方向符号を四区分へ対応させる。

    引数: row(dict)は形状記録。
    返り値: strは幅0無効/正/0/負。未定義をゼロへ補完しない。
    """
    sign = row["実方向CLV符号"]
    if not row["CLV"]["有効"]:
        if sign is not None:
            raise ValueError("CLV無効の符号がNoneでない")
        return "幅0無効"
    if sign not in (-1, 0, 1):
        raise ValueError("有効CLVの符号が不正")
    return {1: "正", 0: "0", -1: "負"}[sign]


def analyze(cases: list[dict], shapes: list[dict], details: list[dict], trace: list[dict],
            result: dict, control: dict, old_details: list[dict], old_trace: list[dict]) -> dict:
    """保存値だけから二案の集合差と費用・回収を分解する。

    引数: cases(list[dict])は旧31共有case、shapes/details/trace(list[dict])は33明細、result/control(dict)は33結果/対照証明、old_details/old_trace(list[dict])は31旧C0保存明細。
    返り値: dictは小型診断。入口・先着・運用は再生しない。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """相違を丸めずに記録する。

        引数: name(str)は項目、actual/expected(object)は保存値と期待値。
        返り値: None。巨大な差は内容指紋に置き換え、全明細を複製しない。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            small = []
            for value in (actual, expected):
                body = H.json.dumps(value, ensure_ascii=False, default=str)
                small.append(value if len(body) <= 1500 else {"内容SHA256": H.canonical(value), "型": type(value).__name__})
            errors.append({"項目": name, "実値": small[0], "期待値": small[1]})

    check("三運用順序", [r["候補ID"] for r in result["結果"]], list(CANDIDATES))
    check("二入口順序", [r["入口ID"] for r in result["入口評価"]], ["3分_T0", "3分_T1"])
    check("全66場既使用", result["全66場既使用"], True)
    case_map = {r["イベントID"]: r for r in cases if r["入口ID"] == "3分_C0"}
    shape_map = {r["旧イベントID"]: r for r in shapes}
    check("形状一意", len(shape_map), len(shapes))
    check("旧C0 case一意", len(case_map), sum(r["入口ID"] == "3分_C0" for r in cases))
    check("T0全純入口=旧C0", {k for k, r in shape_map.items() if r["T0採用"]} == set(case_map), True)
    for row in shapes:
        check("形状診断は採否不使用", row["診断"]["採否への使用"], False)
        check("T1値条件", row["T1採用"], row["T0採用"] and group(row) == "正")
        check("T0採否辞書", row["戦略判定"]["T0"]["採用"], row["T0採用"])
        check("T1採否辞書", row["戦略判定"]["T1"]["採用"], row["T1採用"])
    by_detail = {(d["候補ID"], d["場"]): d for d in details}
    check("運用場候補一意", len(by_detail), len(details))
    trades = [{**t, "候補ID": d["候補ID"]} for d in details for t in d["取引"]]
    handling = {(d["候補ID"], r["イベントID"]): r["取扱"] for d in details for r in d["入口取扱"]}
    for trade in trades:
        eid = old_event(trade["入口イベントID"])
        check("実新規は採用shape", shape_map[eid][trade["候補ID"].split("_")[1]+"採用"], True)
        own = case_map[eid]
        for field in ("新規価格", "新規時計秒", "新規原板行"):
            check("共有caseと実新規:"+field, trade[field], own[field])
        check("共有caseと実方向", trade["方向"], own["方向"])

    # ----------------------------------------
    # T0は識別子の置換だけで旧C0の全属性を直接比較する。
    old_map = {d["場"]: d for d in old_details if d["候補ID"] == "3分_C0_X0"}
    base_map = {d["場"]: d for d in details if d["候補ID"] == "3分_T0_X0"}
    new_logs, old_logs = defaultdict(list), defaultdict(list)
    for row in trace:
        if row["候補ID"] == "3分_T0_X0":
            new_logs[row["場"]].append(row)
    for row in old_trace:
        if row["候補ID"] == "3分_C0_X0":
            old_logs[row["場"]].append(row)
    check("T0旧C0全場集合", set(base_map) == set(old_map), True)
    check("主対照成功", control["全件一致"], True)
    control_map = {r["場"]: r for r in control["照合"]}
    check("主対照全場集合", set(control_map) == set(base_map), True)
    check("主対照場数", control["場候補数"], len(base_map))
    for session, row in base_map.items():
        normalized, logs = old_identity(row), old_identity(new_logs[session])
        check("T0全ledger:"+session, normalized, old_map[session])
        check("T0全trace:"+session, logs, old_logs[session])
        proof = control_map[session]
        check("主T0 ledger成功", proof["全運用同値"], True)
        check("主T0 trace成功", proof["全追尾同値"], True)
        check("主T0 ledgerSHA", proof["旧識別子全運用内容SHA256"], H.canonical(normalized))
        check("主T0 traceSHA", proof["旧識別子追尾内容SHA256"], H.canonical(logs))

    # ----------------------------------------
    # 同時点の純入口選別と、建玉占有で変わる実参加を分ける。
    stages, groups, entrances, positions, participation, recovery, qualities = [], [], [], [], [], [], []
    results = {r["候補ID"]: r for r in result["結果"]}
    entries = {r["入口ID"]: r for r in result["入口評価"]}
    for period in PERIODS:
        raw = [r for r in shapes if r["期間"] == period]
        base = {r["旧イベントID"]: r for r in raw if r["T0採用"]}
        kept = {k: r for k, r in base.items() if r["T1採用"]}
        removed = {k: r for k, r in base.items() if not r["T1採用"]}
        stages.append({"期間": period, "原価格発動数": len(raw), "共通M準備数": sum(r["共通M準備"] for r in raw),
            "時間遅延可数": sum(r["時間条件可"] and r["確認遅延条件可"] for r in raw),
            "先着評価対象数": sum(r["先着評価対象"] for r in raw),
            "T0純入口数": len(base), "T0幅有効数": sum(r["CLV"]["有効"] for r in base.values()),
            "T1純入口数": len(kept), "原PのCLV区分数": dict(Counter(group(r) for r in raw)),
            "M除外理由別": dict(Counter(k for r in raw for k in r["M除外理由"])),
            "DayNight原発動数": {s: sum(r["場"].endswith(s) for r in raw) for s in ("Day", "Night")}})
        for tag in ("幅0無効", "正", "0", "負"):
            own = [case_map[k] for k, r in base.items() if group(r) == tag]
            groups.append({"期間": period, "分母": "T0純入口", "実方向CLV区分": tag, **entry_summary(own)})
        check(period+"CLV四区分総数", sum(r["候補数"] for r in groups if r["期間"] == period), len(base))
        entrances.append({"期間": period, "保持入口": entry_summary([case_map[k] for k in kept]),
            "除外入口": entry_summary([case_map[k] for k in removed]), "新規追加入口数": 0})
        for policy, subset in (("T0", base), ("T1", kept)):
            summary = entry_summary([case_map[k] for k in subset])
            for key, value in summary.items():
                if key == "対象外":
                    check(period+policy+"純入口に対象外なし", value, 0)
                else:
                    check(period+policy+"入口集計:"+key, entries["3分_"+policy][period][key], value)
        for retained, subset in ((True, kept), (False, removed)):
            own = list(subset.values())
            def values(key: str) -> list:
                """同群の当時診断値を欠測補完せず取り出す。

                引数: key(str)は診断値名。
                返り値: listは有効な保存値だけ。
                """
                return [r["診断"][key] for r in own if r["診断"][key] is not None]
            positions.append({"期間": period, "T1保持": retained, "分母": "T0純入口の要求終値",
                "要求数": len(own), "仮約定数": sum(case_map[r["旧イベントID"]]["新規価格"] is not None for r in own),
                "突破距離pt": H.distribution(values("突破距離pt")),
                "前ATR有効数": sum(r["診断"]["前ATR"] is not None for r in own),
                "前ATR規格化突破距離": H.distribution([r["診断"]["前ATR規格化突破距離"]["値"] for r in own if r["診断"]["前ATR規格化突破距離"]["有効"]]),
                "直前範囲規格化突破距離": H.distribution([r["診断"]["直前範囲規格化突破距離"]["値"] for r in own if r["診断"]["直前範囲規格化突破距離"]["有効"]]),
                "仮新規の突破距離pt": H.distribution([r["side"]*(case_map[r["旧イベントID"]]["新規価格"]-r["診断"]["突破基準価格"]) for r in own if case_map[r["旧イベントID"]]["新規価格"] is not None]),
                "採否への使用": False})
        maps = {cid: {H.identity(t): t for t in trades if t["候補ID"] == cid and t["期間"] == period} for cid in CANDIDATES}
        for cid in CANDIDATES:
            own = [t for t in trades if t["候補ID"] == cid and t["期間"] == period]
            check(period+cid+"実新規一意", len(maps[cid]), len(own))
            op = results[cid][period]["運用"]
            check(period+cid+"実完結数", op["完結取引数"], len(own))
            for fee in (0, 5, 10):
                check(period+cid+str(fee)+"費用保存合計", op[f"追加{fee}pt純損益円"], H.cash(own, fee))
        for name, left_cid, right_cid in PAIRS:
            lm, rm = maps[left_cid], maps[right_cid]
            common, left, right = lm.keys() & rm.keys(), lm.keys()-rm.keys(), rm.keys()-lm.keys()
            decompose = []
            for fee in (0, 5, 10):
                field = f"追加滑り{fee}pt純損益円"
                same = sum(rm[k][field]-lm[k][field] for k in common)
                total = H.cash(list(rm.values()), fee)-H.cash(list(lm.values()), fee)
                check(period+name+str(fee)+"全費用分解", total, same-H.cash([lm[k] for k in left], fee)+H.cash([rm[k] for k in right], fee))
                decompose.append({"片道追加pt": fee, "総差円_右引く左": total, "共通出口差円": same,
                    "左のみ損益円": H.cash([lm[k] for k in left], fee), "右のみ損益円": H.cash([rm[k] for k in right], fee)})
            participation.append({"比較": name, "左": left_cid, "右": right_cid, "期間": period, "共通実新規数": len(common),
                "共通出口属性差数": sum(any(lm[k][field] != rm[k][field] for field in ("返済時計秒", "返済原板行", "返済価格", "返済理由")) for k in common),
                "共通費用別差": {str(fee): H.distribution([rm[k][f"追加滑り{fee}pt純損益円"]-lm[k][f"追加滑り{fee}pt純損益円"] for k in common]) for fee in (0, 5, 10)},
                "左のみ": H.operation_summary([lm[k] for k in left]), "右のみ": H.operation_summary([rm[k] for k in right]),
                "左のみの相手取扱": dict(Counter(handling.get((right_cid, lm[k]["入口イベントID"][:-3]+"_"+right_cid.split("_")[1]), "純入口不採用") for k in left)),
                "右のみの相手取扱": dict(Counter(handling.get((left_cid, rm[k]["入口イベントID"][:-3]+"_"+left_cid.split("_")[1]), "純入口不採用") for k in right)),
                "費用別": decompose})
    fee_activation = []
    for cid in CANDIDATES:
        for period in PERIODS:
            own = [t for t in trades if t["候補ID"] == cid and t["期間"] == period]
            favorable = [t for t in own if case_map[old_event(t["入口イベントID"])]["ラベル"] == "順行先着"]
            armed = [t for t in own if t["追尾起動"]]
            reds = [t for t in armed if t["起動後純赤字"]]
            same = sum(t["新規価格"] == t["返済価格"] for t in reds)
            adverse = sum((1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"]) < 0 for t in reds)
            check(cid+period+"起動後赤字内訳", len(reds), same+adverse)
            recovery.append({"候補ID": cid, "期間": period, **H.operation_summary(own),
                "仮250先着取引数": len(favorable),
                "仮250判定前返済数": sum((t["返済時計秒"], t["返済原板行"]) < (case_map[old_event(t["入口イベントID"])]["判定時計秒"], case_map[old_event(t["入口イベントID"])]["判定原板行"]) for t in favorable),
                "実保有MFE250取引数": sum(t["観測最大順行pt"] >= 250 for t in own),
                "追尾起動数": len(armed), "起動後純赤字数": len(reds),
                "同値返済費用赤字数": same, "不利返済赤字数": adverse})
            if cid.endswith("_XF"):
                source = []
                for trade in own:
                    check(cid+period+"XF起動参照費用", trade["起動参照費用円"], 122)
                    check(cid+period+"XF起動参照片道滑り", trade["起動参照片道滑りpt"], 5)
                    decision = trade["起動判定出典"]
                    check(cid+period+"起動出典の有無", decision is not None, trade["追尾起動"])
                    if decision is not None:
                        source.append(decision)
                        check(cid+period+"現在費用後strict正", decision["strict正"], True)
                        check(cid+period+"現在費用後分子正", decision["控除後含み益円分子"] > 0 and decision["控除後含み益円分母"] > 0, True)
                        check(cid+period+"起動出典時計", (decision["価格時計秒"], decision["原板行"]), (trade["追尾起動時計秒"], trade["追尾起動原板行"]))
                fee_activation.append({"候補ID": cid, "期間": period, "実完結数": len(own), "起動出典数": len(source),
                    "参照費用円": 122, "参照片道滑りpt": 5,
                    "現在名目利益pt": H.distribution([r["名目利益pt"] for r in source]),
                    "現在控除後含み益円": H.distribution([r["控除後含み益円"] for r in source]),
                    "分母": "完結取引の初回XF起動出典。未完建玉/全BBO試行とは別"})
            op = results[cid][period]["運用"]
            qualities.append({"候補ID": cid, "期間": period, **{key: op[key] for key in ("品質注意場数", "未解消場数", "EOF期限未達場数")},
                "観測純額円": {str(fee): op[f"追加{fee}pt純損益円"] for fee in (0, 5, 10)},
                "全体確定対象円": {str(fee): op[f"追加{fee}pt確定対象円"] for fee in (0, 5, 10)}})
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "全66場既使用": True, "モデル再計算": False, "先着再計算": False, "運用再生": False,
        "T0旧31C0対照": {"場候補数": len(base_map), "全明細直接比較": True, "全追尾直接比較": True,
            "識別子正規化": "文字列_T0→_C0のみ", "属性除外": []},
        "期間別原発動": stages, "T0純入口のCLV四区分": groups, "入口追加比較": entrances,
        "保持除外の当時位置": positions, "実参加比較": participation, "候補別回収": recovery,
        "XF起動判定の保存出典": fee_activation, "品質と確定額": qualities,
        "限界": ["既使用66場の同時点選別で、後足へ待って進んだ価格差ではない。",
            "CLV符号群はT0純入口の分割。幅0をT0の共通準備へ追加しない。",
            "T0旧A5→同入口XFの費用起動変更と、共通XFのT0→T1というCLV追加を分ける。",
            "純T1部分集合と実参加集合は別。各比較の共通出口差・片側参加の全費用分解を区別する。",
            "XF起動は現在正常返済BBOの名目利益円−122>0strict。費用感度0/5/10でも参照滑り5の起動定義を変えない。",
            "前ATR/前20高安幅で規格化した距離は記述診断だけで、欠測を採否へ使わない。",
            "仮先着は実返済後も観測する反事実。実保有MFEを回収済み利益へ変えない。",
            "名目同値床は同値約定や費用後非赤字を保証しない。品質注意期の確定額nullを維持する。"]}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式結果完成後だけ保存明細を読み、小型診断を保存する。

    引数: study/work(Path)は33正式/作業保存先。
    返り値: dictは診断。不一致は保存後に例外。市場入力・主処理を呼ばない。
    """
    if not (study/"結果.json").is_file():
        raise ValueError("正式結果完成前は診断を実行しません")
    pointer = H.read(study/"入口参照.json")
    shared = {Path(r["パス"]).name: ROOT/r["パス"] for r in pointer["共有明細"]}
    names = ("入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")
    for item in pointer["共有明細"]:
        if Path(item["パス"]).name in names and H.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
            raise ValueError("共有明細の保存版が不一致")
    output = analyze(H.read(shared[names[0]]), H.read(work/"形状選別.jsonl.gz"), H.read(work/names[1]),
        H.read(work/names[2]), H.read(study/"結果.json"), H.read(study/"T0対照同値.json"),
        H.read(shared[names[1]]), H.read(shared[names[2]]))
    paths = [Path(__file__), HELPER, study/"結果.json", study/"固定.json", study/"入口参照.json", study/"T0対照同値.json",
        work/"診断予定.json", *[work/n for n in ("形状選別.jsonl.gz", *names[1:])], *[shared[n] for n in names]]
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix(): H.sha(p) for p in paths}
    output["入口参照SHA256"] = H.sha(study/"入口参照.json")
    (work/"対応診断.json").write_text(H.json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if not output["全件一致"]:
        raise RuntimeError("保存物対応に不一致")
    return output


def main() -> None:
    """正式保存値の後段診断だけをCLI起動する。

    引数: なし。CLIは--study/--work。
    返り値: None。市場prepare/先着/運用の起動はしない。
    """
    parser = argparse.ArgumentParser(description="同時点CLV選別の保存対応診断")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    output = run(args.study.resolve(), args.work.resolve())
    print(H.json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
