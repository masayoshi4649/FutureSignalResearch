"""技法特徴の浅い共通木を時系列で学習し、固定運用へ接続する。"""

import argparse
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00051_技法特徴の浅い分岐学習"
WORK = ROOT / "work/技法分岐学習/00051"
OLD = ROOT / "study/00050_15分定時の局所再開"
OLDWORK = ROOT / "work/局所再開/00050"
LABELS = ROOT / "work/定時帯反応/00049/入口先着.jsonl.gz"
POLICIES = ("Q0", "Q1")
PERIODS = ("学習", "条件選択", "後続検査")


def load(path: Path, name: str):
    """旧モジュールを変更せず、固有名で純関数を読む。

    引数: path(Path)はコード、name(str)は読込名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = load(ROOT / "scripts/定時帯反応/検証.py", "技法分岐_固定49検証")
O = load(ROOT / "scripts/定時帯反応/運用.py", "技法分岐_固定49運用")


def read_rows(path: Path) -> list[dict]:
    """圧縮保存行を順番どおり読む。

    引数: path(Path)はJSONL.gz。
    返り値: list[dict]は保存行。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def phases(entries: list[dict]) -> list[dict]:
    """場を割らない20→10、30→10、40→26の固定分割を作る。

    引数: entries(list[dict])は固定66場の台帳順。
    返り値: list[dict]は学習集合と評価集合。末尾26は選択24と既使用後続2。
    """
    if len(entries) != 66:
        raise ValueError("固定66場が必要")
    return [{"id": name, "train": entries[:n], "evaluation": entries[n:stop],
             "evaluation_start": C.bounds(entries[n]["session"])[0]}
            for name, n, stop in (("W20", 20, 30), ("W30", 30, 40), ("F40", 40, 66))]


def freeze() -> None:
    """学習前に設計・新旧コード・教師出典を固定する。

    引数: なし。
    返り値: None。既存固定は上書きしない。
    """
    destination = STUDY / "固定.json"
    if destination.exists():
        raise FileExistsError(destination)
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    for rel, digest in pins.items():
        if C.sha(ROOT / rel) != digest:
            raise ValueError("既存固定が変化: " + rel)
    files = [*sorted(Path(__file__).parent.glob("*.py")), *sorted(Path(__file__).parent.glob("*.md")),
        Path(__file__).with_name("requirements.txt"), STUDY / "検証計画.md", STUDY / "条件.json",
        STUDY / "人工確認.json", STUDY / "入力台帳.json", OLD / "固定.json", OLD / "結果.json",
        OLD / "保存物確認.json", OLD / "一覧.resources.json", OLDWORK / "定時判断と運用.jsonl.gz",
        OLDWORK / "入口先着.jsonl.gz", LABELS,
        ROOT / "docs/議論/外部再調査/調整の起点回復と失敗の見分け方.md"]
    files += sorted((OLD / "viewer").glob("P0_*.trades.jsonl"))
    for path in files:
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    import sklearn
    import scipy
    C.write_json(destination, {"固定日時": datetime.now(C.JST).isoformat(), "本物学習前": True,
        "全66場既使用": True, "ファイルSHA256": pins, "Python": platform.python_version(),
        "NumPy": C.np.__version__, "scikit-learn": sklearn.__version__, "SciPy": scipy.__version__})
    print("試行51の設計・教師・実装を学習前固定しました")


def verify_lock() -> None:
    """入力と実装が学習前固定から変わっていないか調べる。

    引数: なし。
    返り値: None。不一致は例外。
    """
    for rel, digest in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / rel) != digest:
            raise ValueError("固定後変更: " + rel)


def training_rows(training: list[dict], blocks: dict, features: dict, baseline: dict) -> tuple[list[dict], dict]:
    """特徴準備だけで学習候補を作り、将来不足の除外は学習器へ委ねる。

    引数: training(list[dict])は過去台帳、blocks(dict)は50P0保存場、features(dict)は当時特徴、baseline(dict)は49両方向先着。
    返り値: tuple[list[dict],dict]は両方向の教師候補と特徴準備の件数。
    """
    rows, reasons, total = [], Counter(), 0
    for entry in training:
        for slot in blocks[entry["session"]]["slots"]:
            total += 1
            prepared = features[slot["slot_id"]]
            if not prepared["ready"]:
                reasons[prepared["reason"]] += 1
                continue
            for side in (1, -1):
                label = baseline[slot["slot_id"], side]
                if (label["time"], label["line"], label["scheduled"]) != (slot["time"], slot["line"], slot["scheduled"]):
                    raise ValueError("教師の要求時計不一致")
                rows.append({**label, "features": prepared["vectors"][str(side)]})
    return rows, {"全枠": total, "特徴未準備枠": sum(reasons.values()), "特徴未準備理由": dict(reasons),
                  "特徴準備枠": len(rows) // 2, "方向行数": len(rows)}


def new_slots(block: dict, prepared: dict, learner, model: dict, policy: str, phase: str) -> list[dict]:
    """固定木の両方向得点から一つの定時判断を作る。

    引数: block(dict)は50P0の保存枠、prepared(dict)は特徴、learner(ModuleType)は予測、model(dict)は当該過去学習木、policy/phase(str)は識別子。
    返り値: list[dict]は全予定枠。先着・保有・旧sideを判断へ渡さない。
    """
    result = []
    for old in block["slots"]:
        feature = prepared[old["slot_id"]]
        scored = learner.predict(model, feature["vectors"]) if feature["ready"] else None
        side = scored["side"] if scored else 0
        reason = scored["reason"] if scored else feature["reason"]
        background = feature["background_direction"]
        if side and background == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        role = "順行" if side and side == background else "反転" if side else "待機"
        base = {k: old[k] for k in ("session", "slot_id", "scheduled", "time", "line")}
        result.append({**base, "policy": policy, "phase": phase, "model_id": model["model_id"],
            "side": side, "role": role, "ready": feature["ready"], "reason": reason,
            "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": scored})
    return result


def leaf_statistics(models: list[dict], fitted_models: dict, bindings: dict, labels: dict, operations: dict) -> list[dict]:
    """採用された入口と実取引を、学習木の到達葉ごとに対応させる。

    引数: models(list[dict])はモデル台帳、fitted_models(dict)は全木、bindings(dict)は政策/枠とモデル/葉の対応、labels/operations(dict)は政策別保存結果。
    返り値: list[dict]は全葉×対象期間の集計。全方向の確率校正又は葉だけの再運用ではない。
    """
    result = []
    for meta in models:
        policy, model_id = meta["policy"], meta["id"]
        sessions = set(meta["評価場"])
        for period in PERIODS:
            if not any(C.period(s) == period for s in sessions):
                continue
            phase_ops = [b for b in operations[policy] if b["session"] in sessions and C.period(b["session"]) == period]
            cautions = [b["session"] for b in phase_ops if not b["quality"]["損益確定可能"]]
            for node in fitted_models[model_id]["nodes"]:
                if node["left"] != -1:
                    continue
                identity = model_id, node["id"]
                selected = [r for r in labels[policy] if bindings[policy, r["slot_id"]] == identity and C.period(r["session"]) == period]
                closed = [r for b in phase_ops for r in b["closed"] if bindings[policy, r["slot_id"]] == identity]
                result.append({"model_id": model_id, "policy": policy, "phase": meta["phase"], "leaf": node["id"], "period": period,
                    "入口": C.entry_stats(selected, period), "実完結": len(closed), "実観測純額5": sum(r["pnl5"] for r in closed),
                    "品質注意場": cautions, "品質注意の範囲": "同じモデル評価期間全体。葉への帰属ではない"})
    return result


# ----------------------------------------
# 過去教師で固定した木だけを次の場へ適用する。

def run() -> None:
    """本物の学習6木と、後続46場2運用を一度だけ実行する。

    引数: なし。
    返り値: None。開始・結果がある場合は再実行を拒否する。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("開始済みです。プロセスと成果物を確認してください")
    verify_lock()
    manifest = C.read_json(C.MANIFEST)
    entries = manifest["entries"]
    feature_module = load(Path(__file__).with_name("特徴.py"), "技法分岐_特徴")
    learner = load(Path(__file__).with_name("学習.py"), "技法分岐_学習")
    blocks = {b["session"]: b for b in read_rows(OLDWORK / "定時判断と運用.jsonl.gz") if b["policy"] == "P0"}
    prepared = {s["slot_id"]: feature_module.extract(s) for b in blocks.values() for s in b["slots"]}
    baseline = {(r["slot_id"], r["side"]): r for r in read_rows(LABELS) if r["policy"] in ("B+", "B-")}
    WORK.mkdir(parents=True, exist_ok=True)
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    labels, operations = ({p: [] for p in POLICIES} for _ in range(2))
    resources, models, summaries, features_summary = [], [], [], []
    fitted_models, bindings = {}, {}
    evaluated = {e["session"] for e in entries[20:]}
    for resource in C.read_json(OLD / "一覧.resources.json")["resources"]:
        if resource["method_id"] == "P0" and resource["session"] in evaluated:
            resources.append({**resource, "title": resource["session"] + " P0 固定50対照"})
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as detail:
        for phase in phases(entries):
            rows, preparation = training_rows(phase["train"], blocks, prepared, baseline)
            fitted = {}
            for policy in POLICIES:
                model_id = policy + "_" + phase["id"]
                model = learner.fit(rows, feature_module.FEATURES, policy, model_id, phase["evaluation_start"])
                path = STUDY / "models" / (model_id + ".json")
                C.write_json(path, model)
                fitted[policy] = model
                fitted_models[model_id] = model
                models.append({"id": model_id, "policy": policy, "phase": phase["id"],
                    "path": path.relative_to(ROOT).as_posix(), "SHA256": C.sha(path),
                    "学習場": [e["session"] for e in phase["train"]],
                    "評価場": [e["session"] for e in phase["evaluation"]], "特徴準備": preparation,
                    "評価開始": phase["evaluation_start"]})
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                for policy in POLICIES:
                    slots = new_slots(blocks[session], prepared, learner, fitted[policy], policy, phase["id"])
                    for slot in slots:
                        if slot["ready"] and slot["side"]:
                            bindings[policy, slot["slot_id"]] = slot["model_id"], slot["prediction"]["leafs"][str(slot["side"])]
                            label = baseline[slot["slot_id"], slot["side"]]
                            labels[policy].append({**label, "policy": policy, "role": slot["role"]})
                    operation = O.replay(events, [{k: s[k] for k in O.SLOT_FIELDS} for s in slots], session, policy)
                    operations[policy].append(operation)
                    C.jsonline(detail, {"session": session, "policy": policy, "phase": phase["id"],
                        "input_quality": quality, "slots": slots, "operation": operation})
                    path = STUDY / "viewer" / f"{policy}_{session}.trades.jsonl"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8") as stream:
                        for trade in operation["trades"]:
                            C.jsonline(stream, trade)
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 技法分岐",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy,
                        "point_value": 10, "pnl_format": "trades", "pnl_basis": "net",
                        "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "phase": phase["id"],
                        "入力品質": quality, "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                    features_summary.extend({"policy": policy, "session": session, "side": s["side"],
                        "ready": s["ready"], "reason": s["reason"]} for s in slots)
                print(session + " 後続評価完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for row in labels[policy]:
                C.jsonline(stream, row)
    labels["P0"] = [r for r in read_rows(OLDWORK / "入口先着.jsonl.gz") if r["policy"] == "P0" and r["session"] in evaluated]
    operations["P0"] = [blocks[e["session"]]["operation"] for e in entries[20:]]
    table = {}
    for policy in ("P0", *POLICIES):
        table[policy] = {}
        for period in PERIODS:
            e, o = C.entry_stats(labels[policy], period), C.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": e, "運用": o, "同時適格": e["70目標"] and o["活動適格"] and o["費用適格"]}
    result = {"試行": 51, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models,
        "学習の意味": "初期20場は学習専用。学習欄は後半20場の拡大学習による時系列検査。選択24場で再fitせず、後続2場も40場fit固定。",
        "評価場": [e["session"] for e in entries[20:]], "学習専用場": [e["session"] for e in entries[:20]],
        "対照参照": {"候補": "P0", "元試行": 50, "同じ評価46場に保存値を再集計": True, "市場再生": False},
        "役割別入口": {p: {s: {role: C.entry_stats([r for r in labels[p] if r["role"] == role], s)
            for role in ("順行", "反転")} for s in PERIODS} for p in ("P0", *POLICIES)},
        "葉別評価": leaf_statistics(models, fitted_models, bindings, labels, operations),
        "判断理由": {p: {s: dict(Counter(r["reason"] for r in features_summary if r["policy"] == p and C.period(r["session"]) == s))
                         for s in PERIODS} for p in POLICIES},
        "採用": [p for p in POLICIES if all(table[p][s]["同時適格"] for s in PERIODS[:2])],
        "場別": summaries, "詳細": {p.name: C.sha(p) for p in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"候補": table, "採用": result["採用"]}, ensure_ascii=False))


def main() -> None:
    """学習前固定又は一度の実行を選ぶ。

    引数: なし。CLIから操作を取得。
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
