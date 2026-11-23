"""同じ技法特徴で、価格反応とDI方向を先に分ける構造を比較する。"""

import argparse
from collections import Counter
from datetime import datetime
import gzip
import importlib.util
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00054_方向と局所帯を先に分岐"
WORK = ROOT / "work/方向局面分岐/00054"
OLD = ROOT / "study/00053_局所帯の反応で先に分岐"
OLDWORK = ROOT / "work/局所帯分岐/00053"
POLICIES = ("D0",)
CONTROLS = ("B0", "F0")
PERIODS = ("学習", "条件選択", "後続検査")


def load(path: Path, name: str):
    """既存の純関数を固有名で読み、大域値を変更しない。

    引数: path(Path)はコード、name(str)は読込名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P53 = load(ROOT / "scripts/局所帯分岐/検証.py", "方向局面分岐の固定53主")
P, C, O = P53.P, P53.C, P53.O


def freeze() -> None:
    """54の設計・実装と旧53の同準備対照を学習前に固定する。

    引数: なし。
    返り値: None。既存固定は上書きしない。
    """
    destination = STUDY / "固定.json"
    if destination.exists():
        raise FileExistsError(destination)
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    for rel, digest in pins.items():
        if C.sha(ROOT / rel) != digest:
            raise ValueError("旧固定の変更: " + rel)
    files = [*Path(__file__).parent.glob("*.py"), *Path(__file__).parent.glob("*.md"),
        STUDY / "条件.json", STUDY / "検証計画.md", STUDY / "人工確認.json", STUDY / "入力台帳.json",
        OLD / "固定.json", OLD / "結果.json", OLD / "保存物確認.json", OLD / "一覧.resources.json",
        OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz",
        OLDWORK / "局面内訳の診断.py", OLDWORK / "局面内訳の診断.json",
        ROOT / "docs/議論/外部再調査/上位方向との逆向きと反転確認を分ける.md"]
    files += list((OLD / "viewer").glob("*.trades.jsonl")) + list((OLD / "models").glob("*.json"))
    for path in sorted(files):
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    import sklearn
    C.write_json(destination, {"固定日時": datetime.now(C.JST).isoformat(), "本物学習前": True,
        "全66場既使用": True, "ファイルSHA256": pins, "Python": platform.python_version(),
        "NumPy": C.np.__version__, "scikit-learn": sklearn.__version__})
    print("54の条件・実装・同準備対照を固定しました")


def verify_lock() -> None:
    """固定後の入力・コード変更を拒否する。

    引数: なし。
    返り値: None。不一致は例外。
    """
    for rel, digest in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / rel) != digest:
            raise ValueError("固定後変更: " + rel)


def policy_features(prepared: dict) -> dict:
    """同じ準備と18列だけを教師生成へ渡す。

    引数: prepared(dict)は53と同じ特徴。
    返り値: dictはready/reason/vectors。旧採否や将来結果は含めない。
    """
    return {identity: {"ready": f["ready"], "reason": f["reason"], "vectors": f["vectors"]} for identity, f in prepared.items()}


def new_slots(block: dict, prepared: dict, learner, model: dict, phase: str) -> list[dict]:
    """保存モデルの得点と従来の採用資格から全定時枠を作る。

    引数: block(dict)は保存50枠、prepared(dict)は特徴、learner(ModuleType)は54予測、model(dict)は当該過去モデル、phase(str)は評価区分。
    返り値: list[dict]は全予定枠。DI同値を反転へ付け替えず待機する。
    """
    rows = []
    for old in block["slots"]:
        feature = prepared[old["slot_id"]]
        prediction = learner.predict(model, feature["vectors"]) if feature["ready"] else None
        side = prediction["side"] if prediction else 0
        reason = prediction["reason"] if prediction else feature["reason"]
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        role = "順行" if side and side == feature["background_direction"] else "反転" if side else "待機"
        rows.append({**{k: old[k] for k in ("session", "slot_id", "scheduled", "time", "line")},
            "policy": "D0", "phase": phase, "model_id": model["model_id"], "side": side, "role": role,
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
            "feature": feature, "prediction": prediction})
    return rows


def context_statistics(contexts: dict, labels: dict, operations: dict) -> list[dict]:
    """新候補の採用方向Zごとに仮入口と実取引の帰属を記録する。

    引数: contexts(dict)は政策/枠からZ、labels/operations(dict)は保存結果。
    返り値: list[dict]はD0×3期×2局面の6行。局面だけの再運用ではない。
    """
    rows = []
    for period in PERIODS:
        period_ops = [b for b in operations["D0"] if C.period(b["session"]) == period]
        cautions = [b["session"] for b in period_ops if not b["quality"]["損益確定可能"]]
        for z in (0, 1):
            selected = [r for r in labels["D0"] if C.period(r["session"]) == period and contexts["D0", r["slot_id"]] == z]
            closed = [r for b in period_ops for r in b["closed"] if contexts["D0", r["slot_id"]] == z]
            rows.append({"policy": "D0", "period": period, "z": z, "入口": C.entry_stats(selected, period),
                "実完結": len(closed), "実観測純額5": sum(r["pnl5"] for r in closed), "品質注意場": cautions,
                "品質注意の範囲": "同じ候補の期間全体。局面への帰属ではない"})
    return rows


# ----------------------------------------
# 特徴・教師・執行を維持し、学習する構造だけを新しい候補へ変える。

def run() -> None:
    """新3合成モデルを過去だけで学習し、後続46場を一度だけ評価する。

    引数: なし。
    返り値: None。開始済みなら再実行を拒否する。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("開始済み。既存プロセスと成果物を確認してください")
    verify_lock()
    WORK.mkdir(parents=True, exist_ok=True)
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    manifest, sources = C.inputs()
    entries = manifest["entries"]
    feature_module = load(ROOT / "scripts/局所帯分岐/特徴.py", "方向局面の固定53特徴")
    learner = load(Path(__file__).with_name("学習.py"), "方向局面学習54")
    frames = {x["session"]: [{"session": x["session"], **r} for r in x["frames3"]] for x in sources}
    blocks = {b["session"]: b for b in P.read_rows(P53.SLOTS50) if b["policy"] == "P0"}
    prepared = {s["slot_id"]: feature_module.extract(s, frames[b["session"]]) for b in blocks.values() for s in b["slots"]}
    baseline = {(r["slot_id"], r["side"]): r for r in P.read_rows(P53.LABELS) if r["policy"] in ("B+", "B-")}
    old_result = C.read_json(OLD / "結果.json")
    old_blocks = P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz")
    for old in old_blocks:
        for slot in old["slots"]:
            if prepared[slot["slot_id"]] != slot["feature"]:
                raise ValueError("53と同じ特徴・準備にならない: " + slot["slot_id"])
    labels, operations = ({"D0": []} for _ in range(2))
    for policy in CONTROLS:
        labels[policy] = [r for r in P.read_rows(OLDWORK / "入口先着.jsonl.gz") if r["policy"] == policy]
        operations[policy] = [b["operation"] for b in old_blocks if b["policy"] == policy]
    evaluated = {entry["session"] for entry in entries[20:]}
    resources = [{**r, "title": r["session"] + " " + r["method_id"] + " 固定53対照"}
        for r in C.read_json(OLD / "一覧.resources.json")["resources"] if r["method_id"] in CONTROLS and r["session"] in evaluated]
    selected_features = policy_features(prepared)
    models, fitted_models, bindings, contexts, summaries, reasons, teacher_matches = [], {}, {}, {}, [], [], {}
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as detail:
        for phase in P.phases(entries):
            rows, preparation = P.training_rows(phase["train"], blocks, selected_features, baseline)
            model_id = "D0_" + phase["id"]
            model = learner.fit(rows, feature_module.FEATURES, "D0", model_id, phase["evaluation_start"])
            teacher_matches[phase["id"]] = {}
            for control in CONTROLS:
                prior = C.read_json(OLD / "models" / (control + "_" + phase["id"] + ".json"))
                keys = ["row_ids_sha256", "period_sha256"] + (["input_rows_sha256", "used_rows_sha256"] if control == "F0" else [])
                matches = {k: model["training"][k] == prior["training"][k] for k in keys}
                if not all(matches.values()):
                    raise ValueError("53と教師・時点が一致しない")
                teacher_matches[phase["id"]][control] = matches
            fitted_models[model_id] = model
            path = STUDY / "models" / (model_id + ".json")
            C.write_json(path, model)
            models.append({"id": model_id, "policy": "D0", "phase": phase["id"], "path": path.relative_to(ROOT).as_posix(),
                "SHA256": C.sha(path), "学習場": [e["session"] for e in phase["train"]], "評価場": [e["session"] for e in phase["evaluation"]],
                "特徴準備": preparation, "特徴数": 18, "評価開始": phase["evaluation_start"]})
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                slots = new_slots(blocks[session], prepared, learner, model, phase["id"])
                for slot in slots:
                    if slot["ready"] and slot["side"]:
                        bindings["D0", slot["slot_id"]] = model_id, slot["prediction"]["leafs"][str(slot["side"])]
                        contexts["D0", slot["slot_id"]] = slot["feature"]["history"]["contexts"][str(slot["side"])]["z"]
                        labels["D0"].append({**baseline[slot["slot_id"], slot["side"]], "policy": "D0", "role": slot["role"]})
                operation = O.replay(events, [{k: slot[k] for k in O.SLOT_FIELDS} for slot in slots], session, "D0")
                operations["D0"].append(operation)
                C.jsonline(detail, {"session": session, "policy": "D0", "phase": phase["id"], "input_quality": quality, "slots": slots, "operation": operation})
                path = STUDY / "viewer" / f"D0_{session}.trades.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as stream:
                    for trade in operation["trades"]:
                        C.jsonline(stream, trade)
                resources.append({"id": session + "_D0", "title": session + " D0 方向局面分岐", "symbol": "NK225", "session": session,
                    "product": "NK225micro", "method_id": "D0", "point_value": 10, "pnl_format": "trades", "pnl_basis": "net",
                    "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                summaries.append({"場": session, "候補": "D0", "期間": C.period(session), "phase": phase["id"],
                    "入力品質": quality, "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                reasons.extend({"policy": "D0", "session": session, "reason": s["reason"]} for s in slots)
                print(session + " 方向局面比較完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for label in labels["D0"]:
            C.jsonline(stream, label)
    table = {}
    for policy in (*CONTROLS, "D0"):
        table[policy] = {}
        for period in PERIODS:
            e, o = C.entry_stats(labels[policy], period), C.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": e, "運用": o, "同時適格": e["70目標"] and o["活動適格"] and o["費用適格"]}
        if policy in CONTROLS and table[policy] != old_result["候補"][policy]:
            raise ValueError("保存対照の再集計不一致")
    readiness = {}
    for period in PERIODS:
        subset = [prepared[s["slot_id"]] for session in evaluated if C.period(session) == period for s in blocks[session]["slots"]]
        readiness[period] = {"全予定枠": len(subset), "旧特徴準備": sum(f["base"]["ready"] for f in subset),
            "共通履歴準備": sum(f["ready"] for f in subset), "履歴追加で未準備": sum(f["base"]["ready"] and not f["ready"] for f in subset),
            "追加未準備理由": dict(Counter(f["reason"] for f in subset if f["base"]["ready"] and not f["ready"])),
            "買売Z分布": dict(Counter(str(f["history"]["contexts"]["1"]["z"]) + str(f["history"]["contexts"]["-1"]["z"]) for f in subset if f["ready"]))}
    if readiness != old_result["準備比較"]:
        raise ValueError("53から準備母集団が変化")
    result = {"試行": 54, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models, "対照モデル": old_result["モデル"],
        "準備比較": readiness, "教師一致": teacher_matches,
        "価格SOURCE": {s: {"足数": len(r), "SHA256": learner.fingerprint(r)} for s, r in frames.items()},
        "学習の意味": "初期20場は学習専用。学習欄は後半20場の時系列検査。選択24・後続2は40場fit固定。",
        "評価場": [e["session"] for e in entries[20:]], "学習専用場": [e["session"] for e in entries[:20]],
        "対照参照": {"候補": list(CONTROLS), "元試行": 53, "同じ評価46場に保存値を再集計": True, "市場再生": False},
        "役割別入口": {p: {s: {role: C.entry_stats([r for r in labels[p] if r["role"] == role], s) for role in ("順行", "反転")}
            for s in PERIODS} for p in (*CONTROLS, "D0")},
        "葉別評価": P.leaf_statistics(models, fitted_models, bindings, labels, operations),
        "局面別評価": context_statistics(contexts, labels, operations),
        "判断理由": {"D0": {s: dict(Counter(r["reason"] for r in reasons if C.period(r["session"]) == s)) for s in PERIODS}},
        "採用": ["D0"] if all(table["D0"][s]["同時適格"] for s in PERIODS[:2]) else [],
        "場別": summaries, "詳細": {p.name: C.sha(p) for p in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"新候補": table["D0"], "採用": result["採用"]}, ensure_ascii=False))


def main() -> None:
    """学習前固定又は一度の本物実行を選択する。

    引数: なし。CLIから操作を読む。
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
