"""局所帯への反応で最初に分岐する木と自由な木を同じ準備で比較する。"""

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
STUDY = ROOT / "study/00053_局所帯の反応で先に分岐"
WORK = ROOT / "work/局所帯分岐/00053"
OLD = ROOT / "study/00052_定時判断へ価格履歴を追加"
OLDWORK = ROOT / "work/定時履歴/00052"
SLOTS50 = ROOT / "work/局所再開/00050/定時判断と運用.jsonl.gz"
LABELS = ROOT / "work/定時帯反応/00049/入口先着.jsonl.gz"
POLICIES = ("B0", "F0")
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


P = load(ROOT / "scripts/技法分岐学習/検証.py", "局所帯分岐の固定51主")
C, O = P.C, P.O


def freeze() -> None:
    """設計・履歴・学習と固定済み対照を本物実行前に固定する。

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
        OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz", SLOTS50, LABELS, C.FRAMES,
        ROOT / "docs/議論/外部再調査/価格の履歴と一時点の指標を区別する.md",
        ROOT / "docs/議論/外部再調査/突破の失敗と再突破の呼び方を分ける.md",
        ROOT / "docs/議論/外部再調査/直前の価格帯と反応期間を分ける.md"]
    files += list((OLD / "viewer").glob("H0_*.trades.jsonl"))
    files += list((OLD / "models").glob("H0_*.json"))
    for path in sorted(files):
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    import sklearn
    C.write_json(destination, {"固定日時": datetime.now(C.JST).isoformat(), "本物学習前": True,
        "全66場既使用": True, "ファイルSHA256": pins, "Python": platform.python_version(),
        "NumPy": C.np.__version__, "scikit-learn": sklearn.__version__})
    print("53の設計・実装・入力を学習前固定しました")


def verify_lock() -> None:
    """実装と出典が固定時から変わっていないことを確認する。

    引数: なし。
    返り値: None。不一致は例外。
    """
    for rel, digest in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / rel) != digest:
            raise ValueError("固定後変更: " + rel)


def policy_features(prepared: dict, policy: str) -> dict:
    """共通準備を維持し、比較する特徴列だけを選ぶ。

    引数: prepared(dict)は枠別履歴特徴、policy(str)はB0/F0。
    返り値: dictは51純接続へ渡すready/reason/vectorsだけ。旧採否と教師は使わない。
    """
    if policy not in POLICIES:
        raise ValueError("政策不正")
    key = "control_vectors" if policy == "B0" else "vectors"
    return {identity: {"ready": f["ready"], "reason": f["reason"], "vectors": f[key]} for identity, f in prepared.items()}


def new_slots(block: dict, prepared: dict, learner, model: dict, policy: str, phase: str) -> list[dict]:
    """共通履歴準備の上で、保存木の最高側だけを採用する。

    引数: block(dict)は50保存枠、prepared(dict)は新特徴、learner(ModuleType)は予測、model(dict)は過去学習木、policy/phase(str)は識別。
    返り値: list[dict]は全予定枠。履歴未発生は正常な値で、未来結果は入力しない。
    """
    result = []
    key = "control_vectors" if policy == "B0" else "vectors"
    for old in block["slots"]:
        feature = prepared[old["slot_id"]]
        prediction = learner.predict(model, feature[key]) if feature["ready"] else None
        side = prediction["side"] if prediction else 0
        reason = prediction["reason"] if prediction else feature["reason"]
        background = feature["background_direction"]
        if side and background == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        role = "順行" if side and side == background else "反転" if side else "待機"
        result.append({**{k: old[k] for k in ("session", "slot_id", "scheduled", "time", "line")},
            "policy": policy, "phase": phase, "model_id": model["model_id"], "side": side, "role": role,
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
            "feature": feature, "prediction": prediction})
    return result


def context_statistics(contexts: dict, labels: dict, operations: dict) -> list[dict]:
    """採用方向の局面別に仮入口と実損益の帰属を集計する。

    引数: contexts(dict)は政策/枠からZ、labels/operations(dict)は保存結果。
    返り値: list[dict]は新候補×3期間×2局面の12行。局面限定の再運用ではない。
    """
    result = []
    for policy in POLICIES:
        for period in PERIODS:
            period_ops = [b for b in operations[policy] if C.period(b["session"]) == period]
            cautions = [b["session"] for b in period_ops if not b["quality"]["損益確定可能"]]
            for z in (0, 1):
                selected = [r for r in labels[policy] if C.period(r["session"]) == period and contexts[policy, r["slot_id"]] == z]
                closed = [r for b in period_ops for r in b["closed"] if contexts[policy, r["slot_id"]] == z]
                result.append({"policy": policy, "period": period, "z": z, "入口": C.entry_stats(selected, period),
                    "実完結": len(closed), "実観測純額5": sum(r["pnl5"] for r in closed), "品質注意場": cautions,
                    "品質注意の範囲": "同じ候補の期間全体。局面への帰属ではない"})
    return result


# ----------------------------------------
# 指標銀行は再計算せず、保存された価格SOURCEだけを履歴へ追加する。

def run() -> None:
    """自由木と局面を先に分ける木を同じ過去教師で一度だけ学習・評価する。

    引数: なし。
    返り値: None。開始済みの場合は再実行を拒否する。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("開始済み。既存プロセスと成果物を確認してください")
    verify_lock()
    WORK.mkdir(parents=True, exist_ok=True)
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    manifest, sources = C.inputs()
    entries = manifest["entries"]
    history = load(Path(__file__).with_name("特徴.py"), "局所帯分岐特徴53")
    learner = load(Path(__file__).with_name("学習.py"), "局所帯分岐学習53")
    frames = {x["session"]: [{"session": x["session"], **r} for r in x["frames3"]] for x in sources}
    blocks = {b["session"]: b for b in P.read_rows(SLOTS50) if b["policy"] == "P0"}
    prepared = {s["slot_id"]: history.extract(s, frames[b["session"]]) for b in blocks.values() for s in b["slots"]}
    baseline = {(r["slot_id"], r["side"]): r for r in P.read_rows(LABELS) if r["policy"] in ("B+", "B-")}
    selected_features = {policy: policy_features(prepared, policy) for policy in POLICIES}
    labels, operations = ({policy: [] for policy in POLICIES} for _ in range(2))
    models, fitted_models, bindings, contexts, resources, summaries, reasons = [], {}, {}, {}, [], [], []
    evaluated = {entry["session"] for entry in entries[20:]}
    for resource in C.read_json(OLD / "一覧.resources.json")["resources"]:
        if resource["method_id"] == "H0" and resource["session"] in evaluated:
            resources.append({**resource, "title": resource["session"] + " H0 固定52対照"})
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as detail:
        for phase in P.phases(entries):
            fitted = {}
            for policy in POLICIES:
                rows, preparation = P.training_rows(phase["train"], blocks, selected_features[policy], baseline)
                model_id = policy + "_" + phase["id"]
                meta = history.FEATURES[:17] if policy == "B0" else history.FEATURES
                model = learner.fit(rows, meta, policy, model_id, phase["evaluation_start"])
                fitted[policy], fitted_models[model_id] = model, model
                path = STUDY / "models" / (model_id + ".json")
                C.write_json(path, model)
                models.append({"id": model_id, "policy": policy, "phase": phase["id"], "path": path.relative_to(ROOT).as_posix(),
                    "SHA256": C.sha(path), "学習場": [e["session"] for e in phase["train"]],
                    "評価場": [e["session"] for e in phase["evaluation"]], "特徴準備": preparation,
                    "特徴数": len(meta), "評価開始": phase["evaluation_start"]})
            if fitted["B0"]["training"]["row_ids_sha256"] != fitted["F0"]["training"]["row_ids_sha256"]:
                raise ValueError("同じ準備で教師pairが一致しない")
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                for policy in POLICIES:
                    slots = new_slots(blocks[session], prepared, learner, fitted[policy], policy, phase["id"])
                    for slot in slots:
                        if slot["ready"] and slot["side"]:
                            bindings[policy, slot["slot_id"]] = slot["model_id"], slot["prediction"]["leafs"][str(slot["side"])]
                            contexts[policy, slot["slot_id"]] = slot["feature"]["history"]["contexts"][str(slot["side"])]["z"]
                            labels[policy].append({**baseline[slot["slot_id"], slot["side"]], "policy": policy, "role": slot["role"]})
                    operation = O.replay(events, [{k: slot[k] for k in O.SLOT_FIELDS} for slot in slots], session, policy)
                    operations[policy].append(operation)
                    C.jsonline(detail, {"session": session, "policy": policy, "phase": phase["id"],
                        "input_quality": quality, "slots": slots, "operation": operation})
                    path = STUDY / "viewer" / f"{policy}_{session}.trades.jsonl"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8") as stream:
                        for trade in operation["trades"]:
                            C.jsonline(stream, trade)
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 局所帯分岐",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy,
                        "point_value": 10, "pnl_format": "trades", "pnl_basis": "net",
                        "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "phase": phase["id"],
                        "入力品質": quality, "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                    reasons.extend({"policy": policy, "session": session, "reason": slot["reason"]} for slot in slots)
                print(session + " 履歴比較完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for label in labels[policy]:
                C.jsonline(stream, label)
    labels["H0"] = [r for r in P.read_rows(OLDWORK / "入口先着.jsonl.gz") if r["policy"] == "H0" and r["session"] in evaluated]
    old_blocks = {b["session"]: b for b in P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz") if b["policy"] == "H0"}
    operations["H0"] = [old_blocks[e["session"]]["operation"] for e in entries[20:]]
    table = {}
    for policy in ("H0", *POLICIES):
        table[policy] = {}
        for period in PERIODS:
            e, o = C.entry_stats(labels[policy], period), C.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": e, "運用": o, "同時適格": e["70目標"] and o["活動適格"] and o["費用適格"]}
    readiness = {}
    for period in PERIODS:
        subset = [prepared[s["slot_id"]] for session in evaluated if C.period(session) == period for s in blocks[session]["slots"]]
        readiness[period] = {"全予定枠": len(subset), "旧特徴準備": sum(f["base"]["ready"] for f in subset),
            "共通履歴準備": sum(f["ready"] for f in subset),
            "履歴追加で未準備": sum(f["base"]["ready"] and not f["ready"] for f in subset),
            "追加未準備理由": dict(Counter(f["reason"] for f in subset if f["base"]["ready"] and not f["ready"])),
            "買売Z分布": dict(Counter(str(f["history"]["contexts"]["1"]["z"]) + str(f["history"]["contexts"]["-1"]["z"])
                for f in subset if f["ready"]))}
    result = {"試行": 53, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models, "準備比較": readiness,
        "価格SOURCE": {session: {"足数": len(rows), "SHA256": learner.fingerprint(rows)} for session, rows in frames.items()},
        "学習の意味": "初期20場は学習専用。学習欄は後半20場の時系列検査。選択24・後続2は40場fit固定。",
        "評価場": [e["session"] for e in entries[20:]], "学習専用場": [e["session"] for e in entries[:20]],
        "対照参照": {"候補": "H0", "元試行": 52, "同じ評価46場に保存値を再集計": True, "市場再生": False},
        "役割別入口": {p: {s: {role: C.entry_stats([r for r in labels[p] if r["role"] == role], s)
            for role in ("順行", "反転")} for s in PERIODS} for p in ("H0", *POLICIES)},
        "葉別評価": P.leaf_statistics(models, fitted_models, bindings, labels, operations),
        "局面別評価": context_statistics(contexts, labels, operations),
        "判断理由": {p: {s: dict(Counter(r["reason"] for r in reasons if r["policy"] == p and C.period(r["session"]) == s))
            for s in PERIODS} for p in POLICIES},
        "採用": [p for p in POLICIES if all(table[p][s]["同時適格"] for s in PERIODS[:2])],
        "場別": summaries, "詳細": {p.name: C.sha(p) for p in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"候補": table, "準備比較": readiness, "採用": result["採用"]}, ensure_ascii=False))


def main() -> None:
    """学習前固定又は一度の本物実行を選ぶ。

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
