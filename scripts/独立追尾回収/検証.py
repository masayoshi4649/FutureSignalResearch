"""全定時の独立回収を測定し、過去の回収支持と正額条件を比較する。"""

import argparse
from collections import Counter
from datetime import datetime
from copy import deepcopy
import gzip
import importlib.util
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00055_先着候補へ独立追尾回収を加える"
WORK = ROOT / "work/独立追尾回収/00055"
OLD = ROOT / "study/00054_方向と局所帯を先に分岐"
OLDWORK = ROOT / "work/方向局面分岐/00054"
POLICIES = ("C0", "R0")
PERIODS = ("学習", "条件選択", "後続検査")


def load(path: Path, name: str):
    """固定コードの純補助を固有名で読み、旧大域値を変更しない。

    引数: path(Path)はコード、name(str)は読込識別子。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P54 = load(ROOT / "scripts/方向局面分岐/検証.py", "独立追尾の固定54主")
P, C, O = P54.P, P54.C, P54.O
F = load(ROOT / "scripts/局所帯分岐/特徴.py", "独立追尾の固定53特徴")
L = load(ROOT / "scripts/方向局面分岐/学習.py", "独立追尾の固定54予測")
R = load(HERE / "回収集計.py", "独立追尾の回収集計")


def freeze() -> None:
    """実行前の計測・回収集計・運用・監査と全旧依存を固定する。

    引数: なし。
    返り値: None。既存固定又は旧固定変化は拒否する。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("55は固定済み")
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    for name, digest in pins.items():
        if C.sha(ROOT / name) != digest:
            raise ValueError("旧固定変更: " + name)
    files = [*HERE.glob("*.py"), *HERE.glob("*.md"), STUDY / "検証計画.md", STUDY / "条件.json",
        STUDY / "入力台帳.json", STUDY / "人工確認.json", OLD / "固定.json", OLD / "結果.json",
        OLD / "保存物確認.json", OLD / "一覧.resources.json", OLDWORK / "定時判断と運用.jsonl.gz",
        OLDWORK / "入口先着.jsonl.gz", OLDWORK / "方向分岐の診断.json",
        OLDWORK / "利益回収経路の診断.py", OLDWORK / "利益回収経路の診断.json",
        ROOT / "docs/議論/次の比較を価格経路と回収から設計する.md",
        ROOT / "docs/議論/外部再調査/追尾の距離と入口の押戻余地を分ける.md"]
    files += list((OLD / "models").glob("*.json")) + list((OLD / "viewer").glob("*.trades.jsonl"))
    for path in sorted(files):
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    C.write_json(STUDY / "固定.json", {"試行": 55, "固定日時": datetime.now(C.JST).isoformat(),
        "本物計測前": True, "全66場既使用": True, "Python": platform.python_version(),
        "NumPy": C.np.__version__, "新分類器fit": 0, "ファイルSHA256": pins})
    print("55の計測・回収条件を固定しました", flush=True)


def verify_lock() -> None:
    """実行する全保存依存の内容指紋を照合する。

    引数: なし。
    返り値: None。差があれば例外。
    """
    for name, digest in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / name) != digest:
            raise ValueError("固定後変更: " + name)


def equivalent_close(a: dict, b: dict) -> bool:
    """別候補の建玉ID以外の全完結値を型と値で比較する。

    引数: a/b(dict)は同じ新規の完結記録。
    返り値: boolはID以外の列集合・型・値が全て同じか。
    """
    keys = set(a) - {"id"}
    return keys == set(b) - {"id"} and all(type(a[k]) is type(b[k]) and a[k] == b[k] for k in keys)


def measured_row(slot: dict, feature: dict, side: int, operation: dict | None, barrier: dict | None,
                 quote: dict | None, group: str) -> dict:
    """独立計測と障壁教師を別欄へ置き、未知を損益0へ補完しない。

    引数: slot/feature(dict)は当時情報、side(int)は実方向、operation(dict|None)は独立結果、
        barrier(dict|None)は既存先着、quote(dict|None)は当時気配、group(str)は期間用途。
    返り値: dictは一つの枠・方向の測定行。
    """
    background = feature["background_direction"]
    role = "未準備" if not feature["ready"] else "上位同値" if background == 0 else "順行" if side == background else "反転"
    if not feature["ready"]:
        status = "技法未準備"
    elif operation["closed"]:
        status = "確定完結" if operation["quality"]["損益確定可能"] else "品質注意完結"
    elif operation["final_state"]["position"] is not None or operation["final_state"]["pending"] is not None:
        status = "未解消"
    else:
        status = "未約定"
    end = operation["closed"][0]["exit_time"] if status == "確定完結" else O.session_bounds(slot["session"])["end"]
    display_quote = None if not feature["ready"] or quote is None else {
        k: None if k in ("now", "last", "bid", "ask") and not O.finite(v) else v for k, v in quote.items()}
    return {**{k: slot[k] for k in ("session", "slot_id", "scheduled", "time", "line")},
        "side": side, "ready": feature["ready"], "feature_reason": feature["reason"],
        "features": feature["vectors"][str(side)], "background_direction": background,
        "atr": feature["atr"], "D": feature["D"], "role": role, "measurement_group": group,
        "barrier": barrier, "operation": operation, "status": status,
        "recovery_end_time": end, "decision_bbo": display_quote}


def slots_for(block: dict, prepared: dict, model: dict, calibration: dict, policy: str, phase: str) -> list[dict]:
    """評価の将来回収を渡さず、過去の葉内回収から純判断を作る。

    引数: block/prepared(dict)は50枠と特徴、model/calibration(dict)は過去固定物、
        policy/phase(str)は候補と区分。
    返り値: list[dict]は全予定枠。旧DI同値WAITを維持する。
    """
    result = []
    for slot in block["slots"]:
        feature = prepared[slot["slot_id"]]
        prediction = R.predict(model, calibration, feature["vectors"], L, policy) if feature["ready"] else None
        side = prediction["side"] if prediction else 0
        reason = prediction["reason"] if prediction else feature["reason"]
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        role = "順行" if side and side == feature["background_direction"] else "反転" if side else "待機"
        result.append({**{k: slot[k] for k in ("session", "slot_id", "scheduled", "time", "line")},
            "policy": policy, "phase": phase, "model_id": model["model_id"], "side": side, "role": role,
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
            "feature": feature, "prediction": prediction})
    return result


# ----------------------------------------
# 独立教師の計測と、占有のある実候補の運用を別の出力へ保存する。

def run() -> None:
    """独立計測、過去3回収集計、後続92運用を固定後一度だけ実行する。

    引数: なし。
    返り値: None。開始済みの再実行は拒否する。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("55は開始済み。既存実行を確認してください")
    verify_lock()
    WORK.mkdir(parents=True, exist_ok=True)
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    M = load(HERE / "計測.py", "独立追尾の計測55")
    manifest, sources = C.inputs()
    entries = manifest["entries"]
    blocks = {b["session"]: b for b in P.read_rows(P54.P53.SLOTS50) if b["policy"] == "P0"}
    frames = {b["session"]: [{"session": b["session"], **r} for r in b["frames3"]] for b in sources}
    prepared = {s["slot_id"]: F.extract(s, frames[b["session"]]) for b in blocks.values() for s in b["slots"]}
    baseline = {(r["slot_id"], r["side"]): r for r in P.read_rows(P54.P53.LABELS) if r["policy"] in ("B+", "B-")}
    old_blocks = P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz")
    for block in old_blocks:
        for slot in block["slots"]:
            if prepared[slot["slot_id"]] != slot["feature"]:
                raise ValueError("54の特徴準備と不一致")
    independent, measurements, checks = {}, Counter(), {"全日単独比較": 0, "旧D0実完結一致": 0, "先着新規一致": 0}
    with gzip.open(WORK / "独立測定.jsonl.gz", "wt", encoding="utf-8") as stream:
        for index, entry in enumerate(entries):
            session = entry["session"]
            group = "初期20学習専用" if index < 20 else "時系列20" if index < 40 else C.period(session)
            events, _ = C.events_for(entry)
            by_line = {e["line"]: e for e in events}
            bank, sampled = M.MeasurementBank(events, session), False
            for slot in blocks[session]["slots"]:
                feature = prepared[slot["slot_id"]]
                for side in (1, -1):
                    operation = None
                    if feature["ready"]:
                        quote = by_line[slot["line"]]
                        if not O.normal_bbo(quote) or quote["now"] != slot["time"]:
                            raise ValueError("準備済み判断の正常気配が不一致")
                        role = "順行" if feature["background_direction"] in (0, side) else "反転"
                        pure = {k: slot[k] for k in ("scheduled", "time", "line", "slot_id")}
                        pure.update(side=side, role=role, atr=feature["atr"], D=feature["D"], ready=True, reason="全定時独立計測")
                        identity = "I55_" + str(int(slot["scheduled"])) + ("買" if side == 1 else "売")
                        operation = bank.measure(pure, identity, background_direction=feature["background_direction"])
                        if not sampled:
                            full = O.replay(events, [pure], session, identity)
                            if M.comparison_view(operation) != M.comparison_view(full):
                                raise ValueError("全日単独と高速測定が不一致")
                            checks["全日単独比較"] += 1
                        barrier = baseline[slot["slot_id"], side]
                        opened = [r for r in operation["trades"] if r["type"] in ("LongN", "ShortN")]
                        if bool(opened) != barrier["filled"]:
                            raise ValueError("先着と独立回収の新規有無が不一致")
                        if opened:
                            order = next(r for r in operation["orders"] if r["kind"] == "entry")
                            if any(type(order["fill_" + k]) is not type(barrier["entry_" + k]) or order["fill_" + k] != barrier["entry_" + k] for k in ("time", "line", "price")):
                                raise ValueError("先着と独立回収の新規が不一致")
                            checks["先着新規一致"] += 1
                    row = measured_row(slot, feature, side, operation, baseline.get((slot["slot_id"], side)), by_line.get(slot["line"]), group)
                    independent[slot["slot_id"], side] = row
                    measurements[group, row["status"]] += 1
                    C.jsonline(stream, row)
                if feature["ready"]:
                    sampled = True
            print(session + " 独立計測完了", flush=True)
    if len(independent) != 4884:
        raise ValueError("全2442枠両側の記録数が不一致")
    for block in old_blocks:
        for closed in block["operation"]["closed"]:
            row = independent[closed["slot_id"], closed["side"]]
            if len(row["operation"]["closed"]) != 1 or not equivalent_close(row["operation"]["closed"][0], closed):
                raise ValueError("旧D0実新規と独立回収が不一致")
            checks["旧D0実完結一致"] += 1
    old_result = C.read_json(OLD / "結果.json")
    operations = {"D0": [b["operation"] for b in old_blocks], **{p: [] for p in POLICIES}}
    labels = {"D0": P.read_rows(OLDWORK / "入口先着.jsonl.gz"), **{p: [] for p in POLICIES}}
    models, summaries, reason_rows, teacher_matches = [], [], [], {}
    resources = deepcopy(C.read_json(OLD / "一覧.resources.json")["resources"])
    resources = [r for r in resources if r["method_id"] == "D0"]
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for phase in P.phases(entries):
            model_path = OLD / "models" / ("D0_" + phase["id"] + ".json")
            model = C.read_json(model_path)
            feature_rows = {key: {"ready": value["ready"], "reason": value["reason"], "vectors": value["vectors"]} for key, value in prepared.items()}
            old_training, _ = P.training_rows(phase["train"], blocks, feature_rows, baseline)
            _, old_training_proof = L.prepare_rows(old_training, phase["evaluation_start"], 18)
            teacher_matches[phase["id"]] = {key: old_training_proof[key] == model["training"][key]
                for key in ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256")}
            if not all(teacher_matches[phase["id"]].values()):
                raise ValueError("旧D0の教師・特徴・過去期間が不一致")
            calibration = R.aggregate(model, independent, phase["evaluation_start"], L)
            calibration.update(phase=phase["id"], base_model_path=model_path.relative_to(ROOT).as_posix(), base_model_sha256=C.sha(model_path))
            path = STUDY / "models" / ("回収_" + phase["id"] + ".json")
            C.write_json(path, calibration)
            models.append({"id": model["model_id"], "phase": phase["id"], "path": path.relative_to(ROOT).as_posix(),
                "SHA256": C.sha(path), "学習場": [e["session"] for e in phase["train"]], "評価場": [e["session"] for e in phase["evaluation"]]})
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                choices = {}
                for policy in POLICIES:
                    slots = slots_for(blocks[session], prepared, model, calibration, policy, phase["id"])
                    choices[policy] = {s["slot_id"]: s["side"] for s in slots}
                    for slot in slots:
                        if slot["side"]:
                            labels[policy].append({**baseline[slot["slot_id"], slot["side"]], "policy": policy, "role": slot["role"]})
                    operation = O.replay(events, [{k: slot[k] for k in O.SLOT_FIELDS} for slot in slots], session, policy)
                    operations[policy].append(operation)
                    C.jsonline(stream, {"session": session, "policy": policy, "phase": phase["id"], "input_quality": quality, "slots": slots, "operation": operation})
                    path = STUDY / "viewer" / (policy + "_" + session + ".trades.jsonl")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8") as trades:
                        for trade in operation["trades"]:
                            C.jsonline(trades, trade)
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 過去回収条件",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy,
                        "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality,
                        "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                    reason_rows.extend({"policy": policy, "session": session, "reason": s["reason"]} for s in slots)
                if any(side and choices["C0"][key] != side for key, side in choices["R0"].items()):
                    raise ValueError("純R0がC0の同方向subsetでない")
                print(session + " 回収条件2運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for row in labels[policy]:
                C.jsonline(stream, row)
    table = {}
    for policy in ("D0", *POLICIES):
        table[policy] = {}
        for period in PERIODS:
            entrance, operation = C.entry_stats(labels[policy], period), C.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": entrance, "運用": operation,
                "同時適格": entrance["70目標"] and operation["活動適格"] and operation["費用適格"]}
    if table["D0"] != old_result["候補"]["D0"]:
        raise ValueError("旧D0保存対照の再集計が不一致")
    result = {"試行": 55, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models,
        "対照モデル": old_result["モデル"], "新分類器fit": 0, "新運用数": 92,
        "評価場": [e["session"] for e in entries[20:]], "学習専用場": [e["session"] for e in entries[:20]],
        "準備比較": old_result["準備比較"], "検査": checks, "旧教師一致": teacher_matches,
        "独立測定": [{"区間": k[0], "状態": k[1], "方向行数": n} for k, n in sorted(measurements.items())],
        "独立測定の意味": "全枠両方向の別々の一建玉。行数は独立標本数でも同時実行可能な売買数でもない",
        "対照参照": {"候補": ["D0"], "元試行": 54, "同じ評価46場": True, "市場再生": False},
        "役割別入口": {p: {s: {role: C.entry_stats([r for r in labels[p] if r["role"] == role], s) for role in ("順行", "反転")} for s in PERIODS} for p in ("D0", *POLICIES)},
        "判断理由": {p: {s: dict(Counter(r["reason"] for r in reason_rows if r["policy"] == p and C.period(r["session"]) == s)) for s in PERIODS} for p in POLICIES},
        "場別": summaries, "採用": [p for p in POLICIES if all(table[p][s]["同時適格"] for s in PERIODS[:2])],
        "詳細": {p.name: C.sha(p) for p in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"検査": checks, "採用": result["採用"], "新分類器fit": 0, "新運用": 92}, ensure_ascii=False), flush=True)


def main() -> None:
    """固定又は本物実行をコマンド引数で選択する。

    引数: なし。CLIを読む。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    freeze() if args.freeze else run()


if __name__ == "__main__":
    main()
