"""価格だけの同構造対照と量価格ペア追加を、同教師・同出口で比較する。"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import gzip
import importlib.util
import json
from pathlib import Path
import platform
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00064_再試験の量と価格進行を別々に確認"
WORK = ROOT / "work/量と価格進行/00064"
OLD = ROOT / "study/00063_方向と再開確認へ局面の強弱を追加"
OLDWORK = ROOT / "work/局面強弱の複合確認/00063"
PREFLIGHT = ROOT / "work/量と価格進行/教師接続確認.json"
POLICIES = ("B0", "B1", "Q0", "Q1")
CONTROLS = ("J0", "J1")
MODEL_POLICIES = {"B0": 54, "Q0": 60}
PERIODS = ("学習", "条件選択", "後続検査")
MEASUREMENTS = ROOT / "work/独立追尾回収/00055/独立測定.jsonl.gz"


def load(path: Path, name: str):
    """固定純補助を固有名で読み、旧大域値を変更しない。

    引数: path(Path)はコード、name(str)は読込名。
    返り値: ModuleTypeは読取結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS = load(HERE.parent / "局面強弱の複合確認/検証.py", "量価格の固定63主")
P55, P, C, O, R = PREVIOUS.P55, PREVIOUS.P, PREVIOUS.C, PREVIOUS.O, PREVIOUS.R
F = load(HERE / "特徴.py", "量価格の64特徴")
same_teacher_ids = PREVIOUS.same_teacher_ids
path_coverage = PREVIOUS.path_coverage
regime_coverage = PREVIOUS.regime_coverage
episode_support = PREVIOUS.episode_support
state_distribution = PREVIOUS.state_distribution


def verified_saved_inputs() -> tuple:
    """旧54の完全射影を保ち、固定数量と当時ペアを接続する。

    引数: なし。
    返り値: tupleはentries/blocks/prepared60/baseline/measured/旧63運用/検査数。
    """
    entries, blocks, previous, baseline, measurements, _, inherited = PREVIOUS.verified_saved_inputs()
    proof = C.read_json(OLD / "保存物確認.json")
    ledger = C.read_json(ROOT / "work/局面強弱の複合確認/63完了記録.json")
    if not proof["全件一致"] or proof["不一致数"]:
        raise ValueError("63保存監査が未成功")
    for path in [OLD / "結果.json", OLD / "一覧.resources.json", OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz"]:
        relative = path.relative_to(ROOT).as_posix()
        if C.sha(path) != proof["参照SHA256"][relative] or C.sha(path) != ledger["成果物SHA256"][relative]:
            raise ValueError("63成功証明と保存物の不一致")
    if F.FEATURES[:54] != PREVIOUS.F.FEATURES or any(F.RULES[k] != v for k, v in PREVIOUS.F.RULES.items()):
        raise ValueError("旧54のmetadata又は規約が変化")
    _, sources = C.inputs()
    quantity = F.load_quantity(sources)
    context = F.build_context(sources, quantity)
    prepared = {s["slot_id"]: F.extend(s, previous[s["slot_id"]], context[b["session"]])
        for b in blocks.values() for s in b["slots"]}
    checks = deepcopy(inherited)
    checks.update(旧54射影一致=0, 旧63特徴保存一致=0,
        数量出典接続足数=sum(len(rows) for rows in context.values()),
        公開完全数量足数=sum(row["quantity_reason"] is None for rows in context.values() for row in rows),
        同時刻量既知足数=sum(row["rvol"] is not None for rows in context.values() for row in rows))
    for identity, feature in prepared.items():
        if F.control_projection(feature) != previous[identity]:
            raise ValueError("旧54全辞書の射影に差")
        checks["旧54射影一致"] += 1
    measured = {key: {**row, "base54_features": row["features"],
        "features": prepared[row["slot_id"]]["vectors"][str(row["side"])]} for key, row in measurements.items()}
    old_blocks = P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz")
    if len(old_blocks) != 92:
        raise ValueError("旧63運用数の差")
    for block in old_blocks:
        for slot in block["slots"]:
            if F.control_projection(prepared[slot["slot_id"]]) != slot["feature"]:
                raise ValueError("旧63保存54特徴に差")
            checks["旧63特徴保存一致"] += 1
    return entries, blocks, prepared, baseline, measured, old_blocks, checks


def joined_training(phase: dict, blocks: dict, prepared: dict, baseline: dict, measurements: dict) -> tuple:
    """旧63と同じ教師pairへ当時量価格6列を接続する。

    引数: phase/blocks/prepared/baseline/measurements(dict)は固定過去入力。
    返り値: tupleは60列教師、旧対照数、旧ID。教師目的や可用集合を変えない。
    """
    old_prepared = {key: F.control_projection(feature) for key, feature in prepared.items()}
    old_measured = {key: {**row, "features": row["base54_features"]} for key, row in measurements.items()}
    rows, matches, identities = PREVIOUS.joined_training(phase, blocks, old_prepared, baseline, old_measured)
    return [{**row, "features": prepared[row["slot_id"]]["vectors"][str(row["side"])]}
        for row in rows], matches, identities


def rows_for(rows: list[dict], count: int) -> list[dict]:
    """B/Qへ同じ教師の必要列だけを投影する。

    引数: rows(list[dict])は60列教師、count(int)は54又は60。
    返り値: list[dict]は投影済みコピー。
    """
    if count not in (54, 60):
        raise ValueError("B54又はQ60だけ")
    return [{**row, "features": row["features"][:count]} for row in rows]


def preflight() -> None:
    """本物fit前に教師指紋と量準備の分母だけを保存する。

    引数: なし。
    返り値: None。市場再生・独立計測・学習をしない。
    """
    if PREFLIGHT.exists():
        raise FileExistsError("64接続確認は保存済み")
    learner = load(HERE / "学習.py", "量価格64の学習前確認")
    entries, blocks, prepared, baseline, measured, _, checks = verified_saved_inputs()
    periods, distributions = {}, {}
    for phase in P.phases(entries):
        rows, matches, identities = joined_training(phase, blocks, prepared, baseline, measured)
        old = C.read_json(OLD / "models" / ("J0_" + phase["id"] + ".json"))["training"]
        records = {}
        for policy, count in MODEL_POLICIES.items():
            used, training = learner.prepare_rows(rows_for(rows, count), phase["evaluation_start"], count)
            if training["row_ids"] != old["row_ids"] or not same_teacher_ids(phase, training["row_ids"], identities):
                raise ValueError("旧63の同教師集合に差")
            if any(training["base54_fingerprints"][k] != old[k] for k in learner.FINGERPRINT_FIELDS):
                raise ValueError("旧63全54のcanonical指紋に差")
            for name in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints"):
                if training[name] != old[name]:
                    raise ValueError("既存prefix指紋に差:" + name)
            records[policy] = {"特徴数": count, "使用方向行": training["direction_rows"],
                "旧教師一致": matches, "教師集合一致": True, "旧63教師指紋一致": True,
                "回収追加除外pair": training["recovery_excluded_pair_count"],
                **{key: training[key] for key in (*learner.FINGERPRINT_FIELDS, "base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints", "base54_fingerprints")}}
            if policy == "Q0":
                distributions[phase["id"]] = state_distribution(used, prepared, learner)
        periods[phase["id"]] = records
    C.write_json(PREFLIGHT, {"試行": 64, "接続成功": True, "検査": checks, "期間": periods,
        "価格経路分布": path_coverage(entries, blocks, prepared), "局面分布": regime_coverage(entries, blocks, prepared),
        "数量分布": F.coverage(entries, blocks, prepared), "状態分布": distributions,
        "全特徴SHA256": learner.fingerprint(prepared), "本物fit": False, "市場再生": False, "独立計測": False})
    print(json.dumps({"接続成功": True, "使用方向行": {phase: {p: r["使用方向行"] for p, r in items.items()} for phase, items in periods.items()},
        "数量分布": F.coverage(entries, blocks, prepared)}, ensure_ascii=False), flush=True)


def slots_for(block: dict, prepared: dict, model: dict, calibration: dict, learner, policy: str, phase: str) -> list:
    """当時特徴と固定木でB/Qの新規判断を作る。

    引数: block/prepared/model/calibration(dict)は入力、learner(ModuleType)は学習器、policy/phase(str)は識別。
    返り値: listは予定枠の純判断。実roleと旧DI同値WAITを維持する。
    """
    if policy not in POLICIES or model["policy"] != policy[0] + "0":
        raise ValueError("政策とモデル群が不一致")
    mapped = "C0" if policy.endswith("0") else "R0"
    result = []
    for old in block["slots"]:
        feature = prepared[old["slot_id"]]
        prediction = R.predict(model, calibration, feature["vectors"], learner, mapped) if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        role = "順行" if side and side == feature["background_direction"] else "反転" if side else "待機"
        result.append({**{key: old[key] for key in ("session", "slot_id", "scheduled", "time", "line")},
            "policy": policy, "phase": phase, "model_id": model["model_id"], "side": side, "role": role,
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
            "feature": feature, "prediction": prediction})
    return result


# ----------------------------------------
# 凍結・人工・実市場実行を分け、既存試行の保存物を変更しない。

def freeze() -> None:
    """人工成功と旧固定を検査し、全新入力をfit前に固定する。

    引数: なし。
    返り値: None。既存固定・人工後コード変更は拒否する。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("64は固定済み")
    artificial = C.read_json(STUDY / "人工確認.json")
    if not artificial["成功"] or not artificial["監査人工"]["人工成功"]:
        raise ValueError("人工確認が未成功")
    for relative, expected in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("人工後コード変更:" + relative)
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    for relative, expected in pins.items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("旧固定変化:" + relative)
    files = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"), STUDY / "検証計画.md"]
    files += [p for p in OLD.rglob("*") if p.is_file()]
    files += [OLDWORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz", "保存検証_実行.log")]
    files += [ROOT / name for name in F.INPUT_PINS]
    files += [ROOT / "work/独立追尾回収/55完了記録.json", MEASUREMENTS,
        ROOT / "work/局面強弱の複合確認/63完了記録.json", PREFLIGHT,
        ROOT / "scripts/局面強弱の複合確認/接続を補足する.py",
        ROOT / "scripts/局面強弱の複合確認/接続補足人工.py", ROOT / "scripts/局面強弱の複合確認/補足仕様.md",
        ROOT / "docs/議論/外部再調査/再試験の量と価格進行を段階で分ける.md"]
    for path in sorted(set(files)):
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    import sklearn
    C.write_json(STUDY / "固定.json", {"試行": 64, "固定日時": datetime.now(C.JST).isoformat(),
        "本物fit前": True, "全66場既使用": True, "ファイルSHA256": pins,
        "Python": platform.python_version(), "NumPy": C.np.__version__, "scikit-learn": sklearn.__version__})
    print("64を本物fit前に固定しました", flush=True)


def verify_lock() -> None:
    """全固定出典の指紋を確認する。

    引数: なし。
    返り値: None。不一致は例外。
    """
    for relative, expected in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("固定後変更:" + relative)


def run() -> None:
    """新6木・4政策184運用を一度だけ実行する。

    引数: なし。
    返り値: None。開始記録・結果が既存なら再実行しない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("64は開始済み。既存handleの終了を確認すること")
    verify_lock()
    WORK.mkdir(parents=True, exist_ok=True)
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    learner = load(HERE / "学習.py", "量価格64の本物学習")
    entries, blocks, prepared, baseline, measured, old_blocks, checks = verified_saved_inputs()
    prior = C.read_json(PREFLIGHT)
    if learner.fingerprint(prepared) != prior["全特徴SHA256"]:
        raise ValueError("本物前後の全特徴が不一致")
    for key, value in (("価格経路分布", path_coverage(entries, blocks, prepared)),
            ("局面分布", regime_coverage(entries, blocks, prepared)), ("数量分布", F.coverage(entries, blocks, prepared))):
        if value != prior[key]:
            raise ValueError("本物前後の入力分母差:" + key)
    variants = {"B0": {key: F.control_projection(value) for key, value in prepared.items()}, "Q0": prepared}
    measurements = {policy: {key: {**row, "features": row["features"][:count]} for key, row in measured.items()}
        for policy, count in MODEL_POLICIES.items()}
    old_result = C.read_json(OLD / "結果.json")
    operations = {p: [b["operation"] for b in old_blocks if b["policy"] == p] for p in CONTROLS}
    old_labels = P.read_rows(OLDWORK / "入口先着.jsonl.gz")
    labels = {p: [r for r in old_labels if r["policy"] == p] for p in CONTROLS}
    for policy in POLICIES:
        operations[policy], labels[policy] = [], []
    resources = [deepcopy(r) for r in C.read_json(OLD / "一覧.resources.json")["resources"] if r["method_id"] in CONTROLS]
    models, calibrations, summaries, reasons = [], [], [], []
    episode_summaries, teacher_matches, same_teachers, distribution = {}, {}, {}, {}
    fit_count = 0
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for phase in P.phases(entries):
            rows, teacher_matches[phase["id"]], old_ids = joined_training(phase, blocks, prepared, baseline, measured)
            phase_models, phase_calibrations = {}, {}
            for policy, count in MODEL_POLICIES.items():
                training_rows = rows_for(rows, count)
                used, training = learner.prepare_rows(training_rows, phase["evaluation_start"], count)
                expected = prior["期間"][phase["id"]][policy]
                if any(training[key] != expected[key] for key in learner.FINGERPRINT_FIELDS):
                    raise ValueError("固定前後の教師canonicalに差")
                same = same_teacher_ids(phase, training["row_ids"], old_ids)
                if not same:
                    raise ValueError("旧教師集合に差")
                same_teachers[phase["id"]] = same
                if policy == "Q0":
                    distribution[phase["id"]] = state_distribution(used, prepared, learner)
                    if distribution[phase["id"]] != prior["状態分布"][phase["id"]]:
                        raise ValueError("固定前後の状態分布に差")
                model = learner.fit(training_rows, F.FEATURES[:count], policy, policy + "_" + phase["id"], phase["evaluation_start"])
                if model["training"]["row_ids"] != training["row_ids"]:
                    raise ValueError("fit前後の教師差")
                fit_count += sum(p["fit_performed"] for p in model["training"]["partition"].values())
                episode_summaries[model["model_id"]] = episode_support(model, variants[policy], learner)
                path = STUDY / "models" / (model["model_id"] + ".json")
                C.write_json(path, model)
                meta = {"id": model["model_id"], "policy": policy, "phase": phase["id"], "path": path.relative_to(ROOT).as_posix(),
                    "SHA256": C.sha(path), "学習場": [e["session"] for e in phase["train"]],
                    "評価場": [e["session"] for e in phase["evaluation"]], "特徴数": count, "評価開始": phase["evaluation_start"]}
                models.append(meta)
                calibration = R.aggregate(model, measurements[policy], phase["evaluation_start"], learner)
                calibration.update(policy=policy, phase=phase["id"], base_model_path=meta["path"], base_model_sha256=meta["SHA256"])
                for leaf in calibration["leaves"].values():
                    node = model["nodes"][leaf["leaf"]]
                    if (node["recovery_positive"] if node["direction_rows"] else False) != leaf["positive"]:
                        raise ValueError("回帰と回収の正額に差")
                    if any(node["recovery"][f"pnl{cost}"]["mean"] != leaf["mean_yen"][str(cost)] for cost in (0, 5, 10)):
                        raise ValueError("回帰と回収の平均に差")
                cal_path = STUDY / "models" / ("回収_" + model["model_id"] + ".json")
                C.write_json(cal_path, calibration)
                calibrations.append({"id": model["model_id"], "policy": policy, "phase": phase["id"],
                    "path": cal_path.relative_to(ROOT).as_posix(), "SHA256": C.sha(cal_path)})
                phase_models[policy], phase_calibrations[policy] = model, calibration
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                choices = {}
                for policy in POLICIES:
                    parent = policy[0] + "0"
                    slots = slots_for(blocks[session], variants[parent], phase_models[parent], phase_calibrations[parent], learner, policy, phase["id"])
                    choices[policy] = {s["slot_id"]: s["side"] for s in slots}
                    for slot in slots:
                        if slot["side"]:
                            labels[policy].append({**baseline[slot["slot_id"], slot["side"]], "policy": policy, "role": slot["role"]})
                    operation = O.replay(events, [{key: s[key] for key in O.SLOT_FIELDS} for s in slots], session, policy)
                    for close in operation["closed"]:
                        expected = measured[close["slot_id"], close["side"]]["operation"]["closed"]
                        if len(expected) != 1 or not P55.equivalent_close(close, expected[0]):
                            raise ValueError("新運用と独立保存回収に差")
                        checks["同一新規完結一致"] += 1
                    operations[policy].append(operation)
                    C.jsonline(stream, {"session": session, "policy": policy, "phase": phase["id"],
                        "input_quality": quality, "slots": slots, "operation": operation})
                    path = STUDY / "viewer" / (policy + "_" + session + ".trades.jsonl")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8") as trades:
                        for trade in operation["trades"]:
                            C.jsonline(trades, trade)
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 再試験の量と価格進行を別々に確認",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy, "point_value": 10,
                        "pnl_format": "trades", "pnl_basis": "net", "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality,
                        "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                    reasons.extend({"policy": policy, "session": session, "reason": s["reason"]} for s in slots)
                for parent, child in (("B0", "B1"), ("Q0", "Q1")):
                    if any(side and choices[parent][key] != side for key, side in choices[child].items()):
                        raise ValueError("正回収の純判断が基本候補の同方向部分集合でない")
                print(session + " 量価格4運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for row in labels[policy]:
                C.jsonline(stream, row)
    table = {}
    for policy in (*CONTROLS, *POLICIES):
        table[policy] = {}
        for period in PERIODS:
            entrance, operation = C.entry_stats(labels[policy], period), C.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": entrance, "運用": operation,
                "同時適格": entrance["70目標"] and operation["活動適格"] and operation["費用適格"]}
        if policy in CONTROLS and table[policy] != old_result["候補"][policy]:
            raise ValueError("旧63保存対照の再集計に差")
    if fit_count > 12 or sum(len(operations[p]) for p in POLICIES) != 184:
        raise ValueError("事前のfit又は運用数規約に差")
    result = {"試行": 64, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models, "回収集計": calibrations,
        "対照モデル": old_result["モデル"], "新回帰器fit": fit_count, "新分類器fit": 0, "新独立計測": 0, "新運用数": 184,
        "評価場": [e["session"] for e in entries[20:]], "学習専用場": [e["session"] for e in entries[:20]],
        "準備比較": old_result["準備比較"], "検査": checks, "旧教師一致": teacher_matches, "教師集合一致": same_teachers,
        "独立測定": old_result["独立測定"], "価格経路分布": path_coverage(entries, blocks, prepared),
        "経路支持": episode_summaries, "状態分布": distribution, "局面分布": regime_coverage(entries, blocks, prepared),
        "数量分布": F.coverage(entries, blocks, prepared),
        "独立測定参照": {"元試行": 55, "path": MEASUREMENTS.relative_to(ROOT).as_posix(), "sha256": C.sha(MEASUREMENTS), "再計測": False},
        "対照参照": {"候補": list(CONTROLS), "元試行": 63, "同じ評価46場": True, "市場再生": False},
        "役割別入口": {p: {s: {role: C.entry_stats([r for r in labels[p] if r["role"] == role], s) for role in ("順行", "反転")} for s in PERIODS} for p in (*CONTROLS, *POLICIES)},
        "判断理由": {p: {s: dict(Counter(r["reason"] for r in reasons if r["policy"] == p and C.period(r["session"]) == s)) for s in PERIODS} for p in POLICIES},
        "場別": summaries, "採用": [p for p in POLICIES if all(table[p][s]["同時適格"] for s in PERIODS[:2])],
        "詳細": {p.name: C.sha(p) for p in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新回帰器fit": fit_count, "新運用数": 184, "検査": checks}, ensure_ascii=False), flush=True)


def main() -> None:
    """接続確認・固定・単一本物実行をCLIで区別する。

    引数: CLIの--preflight/--freeze/--run。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    preflight() if args.preflight else freeze() if args.freeze else run()


if __name__ == "__main__":
    main()
