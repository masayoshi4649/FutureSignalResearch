"""同時点のPSY選別、実参加集合、先着と利益回収を対応比較する。"""

from collections import Counter
import gzip
import hashlib
import json
from statistics import median
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00030_価格突破とBB幅と方向頻度"
WORK = ROOT / "work/PSY突破/00030"
PERIODS = ("学習", "条件選択", "後続検査")
POLICIES = ("P0", "P1")


def read(path: Path) -> dict | list:
    """保存正本を読み、圧縮明細は行ごとに展開する。

    引数: path(Path)はJSON又はJSONL.gz。
    返り値: dict | listは復号した値。新しい売買判断はしない。
    """
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream]
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """参照した保存版の内容指紋を求める。

    引数: path(Path)は実在ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry_summary(rows: list[dict]) -> dict:
    """先着の分母を仮約定全体に保ち、小集計を作る。

    引数: rows(list[dict])は価格発動又は採用case。
    返り値: dictは件数・先着率。観測不足や期限を成功分母から除かない。
    """
    labels = Counter(r["ラベル"] for r in rows)
    filled = sum(r["新規価格"] is not None for r in rows)
    return {"候補数": len(rows), "約定候補数": filled,
            **{name: labels[name] for name in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "対象外")},
            "確認率": labels["順行先着"] / filled if filled else None}


def operation_summary(rows: list[dict]) -> dict:
    """対応する実取引の件数と費用後金額を合計する。

    引数: rows(list[dict])は完結取引。
    返り値: dictは同一の約定列に対する費用感度。将来の実約定予測ではない。
    """
    result = {"完結取引数": len(rows)}
    for fee in (0, 5, 10):
        total = sum(r[f"追加滑り{fee}pt純損益円"] for r in rows)
        result[f"追加{fee}pt純損益円"] = total
        result[f"追加{fee}pt平均円"] = total / len(rows) if rows else None
    return result


def identity(trade: dict) -> tuple:
    """同じ実新規を候補名と独立に識別する。

    引数: trade(dict)は完結取引。
    返り値: tupleは場・方向・新規時計・原行・価格。
    """
    return tuple(trade[k] for k in ("場", "方向", "新規時計秒", "新規原板行", "新規価格"))


def amplitude(row: dict, numeric: dict) -> dict:
    """現PSYと同じ12終値変化の値幅集中を求める。

    引数: row(dict)はP0採用case、numeric(dict)は場/番号別の保存数値。
    返り値: dictは一足比率・方向差。比率を採否へ使わない。
    """
    frames = [numeric[row["場"], i] for i in row["PSY現"]["足番号"]]
    changes = [b["close"]-a["close"] for a, b in zip(frames, frames[1:])]
    total = sum(abs(v) for v in changes)
    return {"最大一足比率": max(abs(v) for v in changes)/total if total else None,
            "現一足比率": abs(changes[-1])/total if total else None,
            "現一足変化pt": row["side"]*changes[-1],
            "前方向差整数": row["side"]*row["PSY前"]["方向差整数"],
            "現方向差整数": row["side"]*row["PSY現"]["方向差整数"]}


def run() -> dict:
    """全二案の同時点選別と実参加差を、正本へ対応して診断する。

    引数: なし。
    返り値: dictは一致件数・入口差・会計差・回収診断。固定条件は変更しない。
    """
    cases = read(WORK / "入口事例.jsonl.gz")
    shadows = read(WORK / "全複合shadow.jsonl.gz")
    details = read(WORK / "全運用詳細.jsonl.gz")
    result = read(STUDY / "結果.json")
    numeric = {(r["場"], r["index"]): r for r in read(WORK / "全指標.jsonl.gz")}
    count, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """対応する値を照合し、不一致を消さずに数える。

        引数: name(str)は名称、actual/expected(object)は実値と期待値。
        返り値: None。差があれば最終成功扱いを拒否する。
        """
        nonlocal count
        count += 1
        if actual != expected:
            errors.append({"項目": name, "実値": actual, "期待値": expected})

    case_ids = {r["イベントID"]: r for r in cases}
    check("採用case一意", len(case_ids), len(cases))
    check("全二案", [r["候補ID"] for r in result["結果"]], [f"3分_{p}_X0" for p in POLICIES])
    raw = {r["発動ID"]: r for r in shadows}
    check("原価格発動一意", len(raw), len(shadows))
    all_trades = [{**t, "候補ID": d["候補ID"]} for d in details for t in d["取引"]]
    actual_rows, recovery = [], []
    for trade in all_trades:
        case = case_ids[trade["入口イベントID"]]
        for field in ("新規時計秒", "新規原板行", "新規価格"):
            check(trade["候補ID"] + trade["建玉ID"] + field, trade[field], case[field])
        actual_rows.append({"候補ID": trade["候補ID"], "期間": trade["期間"],
            "入口イベントID": trade["入口イベントID"], "入口ラベル": case["ラベル"],
            "実保有250到達": trade["観測最大順行pt"] >= 250,
            "仮先着判定前返済": (trade["返済時計秒"], trade["返済原板行"]) < (case["判定時計秒"], case["判定原板行"]) if case["判定時計秒"] is not None else None,
            "基準純損益円": trade["基準純損益円"], "追尾起動": trade["追尾起動"],
            "起動後純赤字": trade["起動後純赤字"],
            "設定同値床から返済不足pt": max(0, (1 if trade["方向"] == "買い" else -1) * (trade["新規価格"] - trade["返済価格"])) if trade["追尾起動"] else None})
    for policy in POLICIES:
        cid = f"3分_{policy}_X0"
        for period in PERIODS:
            own = [r for r in actual_rows if r["候補ID"] == cid and r["期間"] == period]
            favorable = [r for r in own if r["入口ラベル"] == "順行先着"]
            armed = [r for r in own if r["追尾起動"]]
            recovery.append({"候補ID": cid, "期間": period, "完結取引数": len(own),
                "仮250先着取引数": len(favorable), "仮250判定前返済数": sum(r["仮先着判定前返済"] is True for r in favorable),
                "実保有250到達取引数": sum(r["実保有250到達"] for r in own),
                "追尾起動数": len(armed), "起動後純赤字数": sum(r["起動後純赤字"] for r in armed),
                "起動後最大返済不足pt": max((r["設定同値床から返済不足pt"] for r in armed), default=None)})

    # ----------------------------------------
    entrance, participation, groups, stages, widths, concentrations = [], [], [], [], [], []
    for period in PERIODS:
        origin = [r for r in shadows if r["期間"] == period]
        stages.append({"期間": period, "原価格発動数": len(origin),
            "共通M準備数": sum(r["共通M準備"] for r in origin),
            "先着評価対象数": sum(r["先着評価対象"] for r in origin),
            "全案採用数": {p: sum(r["戦略判定"][p]["採用"] for r in origin) for p in POLICIES}})
        base = [r for r in cases if r["戦略"] == "P0" and r["期間"] == period]
        tags = {r["イベントID"]: amplitude(r, numeric) for r in base}
        for level in sorted({v["前方向差整数"] for v in tags.values()}):
            own = [r for r in base if tags[r["イベントID"]]["前方向差整数"] == level]
            groups.append({"期間": period, "前PSY実方向差整数": level, **entry_summary(own)})
        for adopted in (True, False):
            own = [r for r in base if r["戦略判定"]["P1"]["採用"] == adopted]
            values = [tags[r["イベントID"]] for r in own]
            concentrations.append({"期間": period, "P1保持": adopted, **entry_summary(own),
                **{name+"中央値": median(v[name] for v in values if v[name] is not None) if any(v[name] is not None for v in values) else None for name in ("最大一足比率", "現一足比率", "現一足変化pt")}})
        for expanding in (True, False):
            own = [r for r in origin if r["先着評価対象"] and r["共通M準備"] and (r["BB幅比較厳密符号"] == 1) == expanding]
            widths.append({"期間": period, "BB拡大": expanding, **entry_summary(own)})
        for row in origin:
            old, current, previous = row["前3分参照"], row["PSY現"], row["PSY前"]
            check(row["発動ID"] + "突破現一足方向", row["side"]*(row["close"]-old["close"]) > 0, True)
            if current is not None and previous is not None:
                change = row["side"]*(current["方向差整数"]-previous["方向差整数"])
                check(row["発動ID"] + "PSY方向差恒等範囲", change in (0, 1, 2), True)
                check(row["発動ID"] + "PSY前正なら現正", not (row["side"]*previous["方向差整数"] > 0 and row["side"]*current["方向差整数"] <= 0), True)
        for left, right in (("P0", "P1"),):
            lcases = {r["発動ID"]: r for r in cases if r["戦略"] == left and r["期間"] == period}
            rcases = {r["発動ID"]: r for r in cases if r["戦略"] == right and r["期間"] == period}
            check(period + left + right + "純入口部分集合", set(rcases) <= set(lcases), True)
            for key in rcases:
                for field in ("要求時計秒", "要求原板行", "side", "新規価格", "新規時計秒", "新規原板行", "ラベル", "判定時計秒", "判定原板行"):
                    check(period + left + right + key + field, rcases[key][field], lcases[key][field])
            entrance.append({"期間": period, "左": left, "右": right,
                "保持入口": entry_summary(list(rcases.values())),
                "除外入口": entry_summary([r for k, r in lcases.items() if k not in rcases]),
                "新規追加入口数": len(set(rcases) - set(lcases))})
            lt = [t for t in all_trades if t["候補ID"] == f"3分_{left}_X0" and t["期間"] == period]
            rt = [t for t in all_trades if t["候補ID"] == f"3分_{right}_X0" and t["期間"] == period]
            lm, rm = {identity(t): t for t in lt}, {identity(t): t for t in rt}
            check(period + left + "実新規一意", len(lm), len(lt))
            check(period + right + "実新規一意", len(rm), len(rt))
            common, lost, added = lm.keys() & rm.keys(), lm.keys() - rm.keys(), rm.keys() - lm.keys()
            exit_delta = 0
            for key in common:
                for field in ("返済時計秒", "返済原板行", "返済価格", "返済理由", "基準純損益円"):
                    check(period + left + right + str(key) + field, lm[key][field], rm[key][field])
                exit_delta += rm[key]["基準純損益円"] - lm[key]["基準純損益円"]
            delta = sum(t["基準純損益円"] for t in rt) - sum(t["基準純損益円"] for t in lt)
            removed = sum(lm[k]["基準純損益円"] for k in lost)
            additional = sum(rm[k]["基準純損益円"] for k in added)
            check(period + left + right + "総損益差分解", delta, exit_delta - removed + additional)
            participation.append({"期間": period, "左": left, "右": right, "共通実新規数": len(common),
                "共通出口差円": exit_delta, "左のみ": operation_summary([lm[k] for k in lost]),
                "右のみ": operation_summary([rm[k] for k in added]), "総基準損益差円": delta})

    warnings = [{"候補ID": d["候補ID"], "場": d["場"], "期間": d["品質"]["期間"],
        **{key: d["品質"][key] for key in ("観測現金増減円", "完結取引数", "観測経路注意取引数", "経路注意取引純損益円", "保有中空白区間数", "新規待機中空白区間数", "最長正常板間隔秒")}}
        for d in details if d["品質"]["観測経路注意"]]
    clean_reference = []
    for period in PERIODS:
        period_sessions = {d["場"] for d in details if d["品質"]["期間"] == period}
        bad = {v["場"] for v in warnings if v["期間"] == period}
        for policy in POLICIES:
            own = [r for r in all_trades if r["候補ID"] == f"3分_{policy}_X0" and r["期間"] == period and r["場"] not in bad]
            clean_reference.append({"候補ID": f"3分_{policy}_X0", "期間": period, "共通場数": len(period_sessions-bad), "除外場": sorted(bad), **operation_summary(own)})
    output = {"全件一致": not errors, "照合項目数": count, "不一致数": len(errors), "不一致": errors,
        "全66場既使用": True, "期間別原発動": stages, "入口追加比較": entrance,
        "実参加比較": participation, "P0の前PSY整数別": groups, "幅拡大の価格原発動": widths, "保持除外の値幅集中": concentrations, "候補別回収": recovery,
        "品質注意の実参加": warnings, "共通無注意場の結果後参考": clean_reference,
        "品質参考の位置付け": "正式全期間額の確定不能を置き換えない。結果後に両案注意場の和集合を同じく外した参考であり、事前にその場を見送る規則や新しい資格を採用していない。",
        "限界": "既使用資料の記述的対応比較。純入口部分集合と実新規集合は異なる。頻度/値幅区分別の成績は新しい切替規則の未見性能ではなく、反転注文の根拠にも直結しない。仮250先着は実保有・実利益と区別する。",
        "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in (Path(__file__), STUDY / "結果.json", STUDY / "固定.json",
            STUDY / "独立監査.json", WORK / "診断予定.json", WORK / "全指標.jsonl.gz", WORK / "入口事例.jsonl.gz", WORK / "全複合shadow.jsonl.gz", WORK / "全運用詳細.jsonl.gz")}}
    (WORK / "対応診断.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise RuntimeError("対応診断に不一致があります")
    return output


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: result[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))
