"""共有入口と四運用の保存値だけから、出口差・参加差・回収を分解する。"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00032_最低同値床と公開SAR追尾"
WORK = ROOT / "work/SAR追尾/00032"
PERIODS = ("学習", "条件選択", "後続検査")
ENTRIES = ("C0", "C1")
EXITS = ("X0", "XS")


def read(path: Path) -> object:
    """既存のJSON又は圧縮明細だけを読む。

    引数: path(Path)は保存済み成果物。
    返り値: objectはJSON値又は行配列。市場入力・主処理は呼ばない。
    """
    if path.name.endswith(".jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream]
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """ファイル内容を指紋化する。

    引数: path(Path)は既存成果物。
    返り値: strはSHA256。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: object) -> str:
    """保存値の正規JSON内容を指紋化する。

    引数: value(object)はJSON化可能な保存値。
    返り値: strはSHA256。精密SARを再計算しない。
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def identity(trade: dict) -> tuple:
    """出口に依存しない実新規を識別する。

    引数: trade(dict)は完結取引。
    返り値: tupleは場/side/新規時計/原行/価格。
    """
    return (trade["場"], 1 if trade["方向"] == "買い" else -1,
        trade["新規時計秒"], trade["新規原板行"], trade["新規価格"])


def cash(rows: list[dict], extra: int) -> float:
    """保存された同じ約定列の費用別純額を合計する。

    引数: rows(list[dict])は取引、extra(int)は片道追加pt。
    返り値: floatは保存値の合計円。
    """
    return sum(t[f"追加滑り{extra}pt純損益円"] for t in rows)


def distribution(values: list[float]) -> dict:
    """保存数値の小さな記述統計を求める。

    引数: values(list[float])は欠測なしの群。
    返り値: dictは件数/合計/平均/中央値/最小/最大。空群はNone。
    """
    return {"件数": len(values), "合計": sum(values), "平均": sum(values) / len(values) if values else None,
        "中央値": median(values) if values else None, "最小": min(values) if values else None,
        "最大": max(values) if values else None}


def operation_summary(rows: list[dict]) -> dict:
    """完結取引の費用・保有・観測値幅・実回収を要約する。

    引数: rows(list[dict])は完結取引。
    返り値: dictは記述統計。入口の採用や新しい売買判断に使わない。
    """
    return {"完結取引数": len(rows), **{f"追加{n}pt純損益円": cash(rows, n) for n in (0, 5, 10)},
        **{f"追加{n}pt平均円": cash(rows, n) / len(rows) if rows else None for n in (0, 5, 10)},
        "返済理由別": dict(Counter(t["返済理由"] for t in rows)),
        "保有分": distribution([t["保有分"] for t in rows]),
        "観測MFEpt": distribution([t["観測最大順行pt"] for t in rows]),
        "観測MAEpt": distribution([t["観測最大逆行pt"] for t in rows]),
        "実回収pt": distribution([(1 if t["方向"] == "買い" else -1) * (t["返済価格"] - t["新規価格"]) for t in rows])}


def analyze(cases: list[dict], details: list[dict], trace: list[dict], result: dict,
            control: dict, old_details: list[dict], old_trace: list[dict]) -> dict:
    """保存済み二入口四運用を対応し、全費用差を分解する。

    引数: cases(list[dict])は旧31共有case、details/trace(list[dict])は新保存物、result/control(dict)は新結果/主X0同値証拠、old_details/old_trace(list[dict])は旧X0保存物。
    返り値: dictは照合・共通出口差・片側参加・利益回収・品質の小型診断。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """不一致を小さく記録する。

        引数: name(str)は項目、actual/expected(object)は保存値/期待値。
        返り値: None。大明細の不一致は全文を複製せず指紋を残す。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            values = []
            for value in (actual, expected):
                text = json.dumps(value, ensure_ascii=False, default=str)
                values.append(value if len(text) <= 1500 else {"内容SHA256": canonical(value), "型": type(value).__name__})
            errors.append({"項目": name, "実値": values[0], "期待値": values[1]})

    cids = [f"3分_{entry}_{exit_id}" for entry in ENTRIES for exit_id in EXITS]
    check("四運用固定順", [r["候補ID"] for r in result["結果"]], cids)
    check("入口二案", [r["入口ID"] for r in result["入口評価"]], ["3分_C0", "3分_C1"])
    check("125250不変", result["入口125250評価の変更"], False)
    case_map = {r["イベントID"]: r for r in cases}
    check("共有case一意", len(case_map), len(cases))
    trade_rows = [{**trade, "候補ID": d["候補ID"]} for d in details for trade in d["取引"]]
    by_detail = {(d["候補ID"], d["場"]): d for d in details}
    check("場候補一意", len(by_detail), len(details))
    handling = {(d["候補ID"], r["イベントID"]): r["取扱"] for d in details for r in d["入口取扱"]}
    for trade in trade_rows:
        case = case_map[trade["入口イベントID"]]
        for key in ("新規価格", "新規時計秒", "新規原板行"):
            check("共有仮新規と実新規:" + key, trade[key], case[key])
        check("新規方向", trade["方向"], case["方向"])

    # ----------------------------------------
    # X0全明細・全追尾を直接照合し、主のcontrol証拠へもbindする。

    check("主X0対照成功", control["全件一致"], True)
    old_map = {(d["候補ID"], d["場"]): d for d in old_details}
    new_control = {key: d for key, d in by_detail.items() if key[0].endswith("_X0")}
    check("X0全場候補集合", set(new_control) == set(old_map), True)
    control_map = {(r["候補ID"], r["場"]): r for r in control["照合"]}
    check("主control集合", set(control_map) == set(new_control), True)
    new_log, old_log = defaultdict(list), defaultdict(list)
    for row in trace:
        if row["候補ID"].endswith("_X0"):
            new_log[row["候補ID"], row["場"]].append(row)
    for row in old_trace:
        old_log[row["候補ID"], row["場"]].append(row)
    for key, detail in new_control.items():
        check("X0全ledger:" + str(key), detail, old_map[key])
        check("X0全trace:" + str(key), new_log[key], old_log[key])
        proof = control_map[key]
        check("主control ledger SHA", canonical([detail]), proof["全運用内容SHA256"])
        check("主control trace SHA", canonical(new_log[key]), proof["追尾内容SHA256"])
    x0_control = {"場候補数": len(new_control), "全明細直接比較": True,
        "全追尾直接比較": True, "属性除外": [], "主対照証拠参照": "X0対照同値.json"}

    # ----------------------------------------
    # 共通実新規の出口差を0と仮定せず、片側参加と全額分解する。

    participation, common_rows, recovery, xs_groups, quality_rows = [], [], [], [], []
    for entry in ENTRIES:
        for period in PERIODS:
            maps = {}
            for exit_id in EXITS:
                cid = f"3分_{entry}_{exit_id}"
                rows = [t for t in trade_rows if t["候補ID"] == cid and t["期間"] == period]
                maps[exit_id] = {identity(t): t for t in rows}
                check(cid + period + "実新規一意", len(maps[exit_id]), len(rows))
            left, right = maps["X0"], maps["XS"]
            common = left.keys() & right.keys()
            left_only, right_only = left.keys() - right.keys(), right.keys() - left.keys()
            common_deltas = {extra: [right[key][f"追加滑り{extra}pt純損益円"] - left[key][f"追加滑り{extra}pt純損益円"] for key in common] for extra in (0, 5, 10)}
            earlier = Counter()
            reasons, source_differences = Counter(), 0
            for key in common:
                l, r = left[key], right[key]
                lk, rk = (l["返済時計秒"], l["返済原板行"]), (r["返済時計秒"], r["返済原板行"])
                earlier["XS先" if rk < lk else "X0先" if rk > lk else "同key"] += 1
                reasons[l["返済理由"] + "→" + r["返済理由"]] += 1
                source_differences += l["入口イベントID"] != r["入口イベントID"]
            common_row = {"入口": entry, "期間": period, "共通実新規数": len(common), "出口先後": dict(earlier),
                "返済理由の対応": dict(reasons), "同新規で要求元IDが異なる数": source_differences,
                "XS引くX0": {"保有分": distribution([right[k]["保有分"] - left[k]["保有分"] for k in common]),
                    "返済時計秒": distribution([right[k]["返済時計秒"] - left[k]["返済時計秒"] for k in common]),
                    "実方向返済価格pt": distribution([(1 if right[k]["方向"] == "買い" else -1) * (right[k]["返済価格"] - left[k]["返済価格"]) for k in common]),
                    "観測MFEpt": distribution([right[k]["観測最大順行pt"] - left[k]["観測最大順行pt"] for k in common]),
                    "観測MAEpt": distribution([right[k]["観測最大逆行pt"] - left[k]["観測最大逆行pt"] for k in common])},
                "費用別": [{"片道追加pt": extra, "純損益差円": distribution(delta),
                    "改善数": sum(v > 0 for v in delta), "同額数": sum(v == 0 for v in delta),
                    "悪化数": sum(v < 0 for v in delta)} for extra, delta in common_deltas.items()]}
            common_rows.append(common_row)
            own = {"入口": entry, "期間": period, "共通実新規数": len(common),
                "X0のみ": operation_summary([left[k] for k in left_only]),
                "XSのみ": operation_summary([right[k] for k in right_only]), "片側参加の相手取扱": {}, "費用別": []}
            for name, own_map, keys, other in (("X0のみ", left, left_only, "XS"), ("XSのみ", right, right_only, "X0")):
                categories = Counter()
                for key in keys:
                    trade = own_map[key]
                    other_key = (f"3分_{entry}_{other}", trade["入口イベントID"])
                    check("相手の保存入口取扱あり", other_key in handling, True)
                    categories[handling.get(other_key, "保存取扱なし")] += 1
                own["片側参加の相手取扱"][name] = dict(categories)
            for extra in (0, 5, 10):
                delta = cash(list(right.values()), extra) - cash(list(left.values()), extra)
                same = sum(common_deltas[extra])
                lost, added = cash([left[k] for k in left_only], extra), cash([right[k] for k in right_only], extra)
                check(entry + period + str(extra) + "総額分解", delta, same - lost + added)
                own["費用別"].append({"片道追加pt": extra, "総差円_XS引くX0": delta,
                    "共通出口差円": same, "X0のみ損益円": lost, "XSのみ損益円": added})
            participation.append(own)

            # ----------------------------------------
            # 仮250と実保有の回収、起動後赤字、結果後SAR適用群を分ける。

            for exit_id, trade_map in maps.items():
                cid = f"3分_{entry}_{exit_id}"
                rows = list(trade_map.values())
                favorable = [t for t in rows if case_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
                early = [t for t in favorable if (t["返済時計秒"], t["返済原板行"]) <
                    (case_map[t["入口イベントID"]]["判定時計秒"], case_map[t["入口イベントID"]]["判定原板行"])]
                armed = [t for t in rows if t["追尾起動"]]
                reds = [t for t in armed if t["基準純損益円"] < 0]
                scratch = sum(t["返済価格"] == t["新規価格"] for t in reds)
                adverse = sum((1 if t["方向"] == "買い" else -1) * (t["返済価格"] - t["新規価格"]) < 0 for t in reds)
                check(cid + period + "起動後赤字分解", len(reds), scratch + adverse)
                for trade in armed:
                    side = 1 if trade["方向"] == "買い" else -1
                    check("最低同値の最終設定線", side * (trade["最終追尾価格"] - trade["新規価格"]) >= 0, True)
                recovery.append({"候補ID": cid, "期間": period, **operation_summary(rows),
                    "仮250先着取引数": len(favorable), "仮250判定前返済数": len(early),
                    "仮250判定前の返済理由": dict(Counter(t["返済理由"] for t in early)),
                    "実保有MFE250取引数": sum(t["観測最大順行pt"] >= 250 for t in rows),
                    "仮250群の実回収pt": distribution([(1 if t["方向"] == "買い" else -1) * (t["返済価格"] - t["新規価格"]) for t in favorable]),
                    "追尾起動数": len(armed), "起動後純赤字数": len(reds),
                    "同値返済費用赤字数": scratch, "不利返済赤字数": adverse,
                    "赤字内訳の分母": "追尾起動済みかつ基準純損益が負の完結取引"})
                metric = next(r for r in result["結果"] if r["候補ID"] == cid)[period]["運用"]
                own_details = [d for d in details if d["候補ID"] == cid and d["品質"]["期間"] == period]
                warnings = [d for d in own_details if d["品質"]["観測経路注意"]]
                check(cid + period + "正式取引数", len(rows), metric["完結取引数"])
                for extra in (0, 5, 10):
                    check(cid + period + "正式純額", cash(rows, extra), metric[f"追加{extra}pt純損益円"])
                    if metric["品質注意場数"] or metric["未解消場数"] or metric["EOF期限未達場数"]:
                        check(cid + period + "注意期null維持", metric[f"追加{extra}pt確定対象円"], None)
                quality_rows.append({"候補ID": cid, "期間": period, "入力場数": metric["入力場数"],
                    "活動場数": metric["活動場数"], "無取引場数": metric["無取引場数"],
                    "買い取引数": metric["買い取引数"], "売り取引数": metric["売り取引数"],
                    "品質注意場数": metric["品質注意場数"], "未解消場数": metric["未解消場数"], "EOF期限未達場数": metric["EOF期限未達場数"],
                    "品質注意場": [d["場"] for d in warnings],
                    "観測純額円": {str(n): metric[f"追加{n}pt純損益円"] for n in (0, 5, 10)},
                    "全体確定対象円": {str(n): metric[f"追加{n}pt確定対象円"] for n in (0, 5, 10)}})
                if exit_id == "XS":
                    for trade in rows:
                        check("XS距離未使用", trade["追尾距離pt"], None)
                        check("XSのATR距離未使用", trade["ATR距離使用"], False)
                        check("SAR回数非負整数", isinstance(trade["SAR締上げ回数"], int) and trade["SAR締上げ回数"] >= 0, True)
                        if not trade["追尾起動"]:
                            check("未起動SAR締上げなし", trade["SAR締上げ回数"], 0)
                    for group in ("未起動", "同値床のみ", "SAR締上げ済"):
                        selected = [t for t in rows if ("未起動" if not t["追尾起動"] else "SAR締上げ済" if t["SAR締上げ回数"] > 0 else "同値床のみ") == group]
                        xs_groups.append({"候補ID": cid, "期間": period, "事後区分": group, **operation_summary(selected)})

    sar_usage = []
    for cid in ("3分_C0_XS", "3分_C1_XS"):
        for period in PERIODS:
            info = [d["品質"] for d in details if d["候補ID"] == cid and d["品質"]["期間"] == period]
            logs = [r for r in trace if r["候補ID"] == cid and r["期間"] == period]
            reasons = Counter()
            for value in info:
                reasons.update(value["SAR評価理由別"])
            tightened = sum(r["動作"] == "追尾線更新" and r.get("更新根拠") == "公開SAR次足線" for r in logs)
            check(cid + period + "SAR更新trace対品質", tightened, sum(r["SAR締上げ回数"] for r in info))
            check(cid + period + "SAR更新評価対trace", reasons["SAR上締上げ"], tightened)
            allowed = {"当場公開SAR未準備", "SAR公開key後でない", "SAR方向不一致",
                "SAR名目利益strict正でない", "SAR候補非緩和維持", "SAR上締上げ"}
            check("SAR評価理由の既知集合", set(reasons) <= allowed, True)
            ready = sum(reasons.values()) - reasons["当場公開SAR未準備"]
            after = ready - reasons["SAR公開key後でない"]
            direction = after - reasons["SAR方向不一致"]
            sar_usage.append({"候補ID": cid, "期間": period, "SAR締上げ回数": tightened,
                "SAR評価理由別_BBO試行数": dict(reasons), "SAR公開参照更新数": sum(r["動作"] == "SAR公開参照更新" for r in logs),
                "評価分母": "追尾起動済み・pendingなしの正常BBO試行。固有足数や固有建玉数ではない",
                "有効公開参照あり試行数": ready, "公開key後試行数": after,
                "方向一致試行数": direction, "精密名目利益正試行数": direction - reasons["SAR名目利益strict正でない"],
                "同値床設定数": sum(r["動作"] == "追尾線更新" and r.get("更新根拠") == "初回同値床" for r in logs)})
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "全66場既使用": True, "モデル再計算": False, "先着再計算": False, "運用再生": False,
        "共有case数": len(cases), "実完結取引数": len(trade_rows), "X0旧31対照": x0_control,
        "共通実新規の出口差": common_rows, "実参加の全費用分解": participation,
        "候補別回収": recovery, "XSの事後適用群": xs_groups, "SAR適用記録": sar_usage, "品質と確定額": quality_rows,
        "限界": ["全66場は既使用。入口評価2案と運用4案を区別し、入口先着は31を共有する。",
            "共通新規の出口差と片側参加の差を分ける。共通出口差を0とは仮定しない。",
            "共通新規・SAR締上げ済/床のみ等は結果後の群。新しい入口/運用フィルターとして採用しない。",
            "仮250は保有継続の反事実で、実保有で250利益を得た証拠ではない。",
            "同値設定線は同値約定/費用後非赤字を保証しない。価格時計待機を実注文遅延と断定しない。",
            "品質注意期の確定額nullを観測額や結果後の場除外で置き換えない。"]}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式完了後の保存物だけを読み、対応診断を作業先へ保存する。

    引数: study/work(Path)は32正式/作業先。
    返り値: dictは診断。不一致でも小JSONを保存後に例外とする。
    """
    if not (study / "結果.json").exists():
        raise ValueError("正式結果完成前は対応診断を実行しません")
    pointer = read(study / "入口参照.json")
    entries = {Path(r["パス"]).name: ROOT / r["パス"] for r in pointer["共有明細"]}
    for item in pointer["共有明細"]:
        if Path(item["パス"]).name in ("入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz") and sha(ROOT / item["パス"]) != item["圧縮SHA256参考"]:
            raise ValueError("共有入口の保存指紋が不一致")
    paths = [study / "結果.json", study / "固定.json", study / "入口参照.json", study / "X0対照同値.json",
        work / "診断予定.json", work / "全運用詳細.jsonl.gz", work / "追尾.jsonl.gz",
        entries["入口事例.jsonl.gz"], entries["全運用詳細.jsonl.gz"], entries["追尾.jsonl.gz"]]
    output = analyze(read(entries["入口事例.jsonl.gz"]), read(work / "全運用詳細.jsonl.gz"),
        read(work / "追尾.jsonl.gz"), read(study / "結果.json"), read(study / "X0対照同値.json"),
        read(entries["全運用詳細.jsonl.gz"]), read(entries["追尾.jsonl.gz"]))
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix(): sha(p) for p in [Path(__file__), *paths]}
    output["入口参照SHA256"] = sha(study / "入口参照.json")
    (work / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if not output["全件一致"]:
        raise RuntimeError("保存物対応の不一致を確認してください")
    return output


def main() -> None:
    """正式完了後の後段診断だけを起動する。

    引数: なし。CLIは--study/--work。
    返り値: None。主/指標/先着/運用をimport又は実行しない。
    """
    parser = argparse.ArgumentParser(description="公開SAR追尾の保存値対応診断")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    output = run(args.study.resolve(), args.work.resolve())
    print(json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
