"""同じ60特徴を、DIに対応する現在の経路有効性で先に分ける。"""

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
STUDY = ROOT / "study/00065_方向に対応する現在の有効状態を先に分ける"
WORK = ROOT / "work/状態と判断/00065"
OLD = ROOT / "study/00064_再試験の量と価格進行を別々に確認"
OLDWORK = ROOT / "work/量と価格進行/00064"
PREFLIGHT = ROOT / "work/状態と判断/教師接続確認.json"
POLICIES, CONTROLS = ("U0", "U1"), ("Q0", "Q1")
MODEL_POLICIES = {"U0": 60}
PERIODS = ("学習", "条件選択", "後続検査")
MEASUREMENTS = ROOT / "work/独立追尾回収/00055/独立測定.jsonl.gz"


def load(path: Path, name: str):
    """旧大域値を変更せず純補助を固有名で読む。

    引数: path(Path)はコード、name(str)は読込名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS = load(HERE.parent / "量と価格進行/検証.py", "現在状態の固定64主")
P55, P, C, O, R, F = PREVIOUS.P55, PREVIOUS.P, PREVIOUS.C, PREVIOUS.O, PREVIOUS.R, PREVIOUS.F
same_teacher_ids = PREVIOUS.same_teacher_ids
path_coverage, regime_coverage = PREVIOUS.path_coverage, PREVIOUS.regime_coverage
episode_support = PREVIOUS.episode_support


def verified_saved_inputs() -> tuple:
    """旧64の60特徴と教師を再用し、保存Q全辞書へ照合する。

    引数: なし。
    返り値: tupleはentries/blocks/prepared60/baseline/measured/旧Q92運用/14カウンタ。
    """
    entries, blocks, prepared, baseline, measured, _, inherited = PREVIOUS.verified_saved_inputs()
    proof = C.read_json(OLD / "保存物確認.json")
    ledger = C.read_json(ROOT / "work/量と価格進行/64完了記録.json")
    if not proof["全件一致"] or proof["不一致数"]:
        raise ValueError("64保存監査が未成功")
    for path in (OLD / "結果.json", OLD / "一覧.resources.json", OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz"):
        relative = path.relative_to(ROOT).as_posix()
        if C.sha(path) != proof["参照SHA256"][relative] or C.sha(path) != ledger["成果物SHA256"][relative]:
            raise ValueError("64成功証明と保存物に差")
    old_blocks = [row for row in P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz") if row["policy"] in CONTROLS]
    if len(old_blocks) != 92:
        raise ValueError("旧Q運用数の差")
    checks = deepcopy(inherited)
    checks["旧64特徴保存一致"] = 0
    for block in old_blocks:
        for slot in block["slots"]:
            if prepared[slot["slot_id"]] != slot["feature"]:
                raise ValueError("旧Q60特徴の全辞書に差")
            checks["旧64特徴保存一致"] += 1
    return entries, blocks, prepared, baseline, measured, old_blocks, checks


def joined_training(phase: dict, blocks: dict, prepared: dict, baseline: dict, measured: dict) -> tuple:
    """旧64と同じ60特徴・障壁・回収教師を接続する。

    引数: phase/blocks/prepared/baseline/measured(dict)は固定過去入力。
    返り値: tupleは教師行・旧教師一致数・旧使用ID。追加除外なし。
    """
    return PREVIOUS.joined_training(phase, blocks, prepared, baseline, measured)


def current_stage(path: dict) -> str:
    """現在の経路を、排他的な形成段階と取消へ分ける。

    引数: path(dict)は既存T又はRの当時状態。
    返り値: strは未ID又はb/f/r/kの有効・取消。価格機械を更新しない。
    """
    if path["episode_id"] is None:
        return "未ID又は失効"
    stage = next((key for key in ("k", "r", "f", "b") if path.get(key) is not None), "段階不明")
    return stage + ("取消" if path["cancel"] is not None else "有効" if path["episode_valid"] else "無効")


def state_distribution(used: list[dict], prepared: dict, learner) -> dict:
    """同じ過去教師をDIと対応する現在有効旗の四群へ分ける。

    引数: used(list[dict])は使用教師、prepared(dict)は当時状態、learner(ModuleType)はfloat32変換器。
    返り値: dictは四群の方向/枠/日/場・段階・取消・形成反復。採否に使用しない。
    """
    result = {}
    for direction in (0, 1):
        route, index = ("R", 25) if direction == 0 else ("T", 19)
        for active in (0, 1):
            selected = [row for row in used if int(learner.float32(row["features"])[0] > 0) == direction
                and int(learner.float32(row["features"])[index] > 0.5) == active]
            targets = [prepared[row["slot_id"]]["paths"][str(row["side"])][route] for row in selected]
            item = {"方向枝": "DI非正" if direction == 0 else "DI正", "対象経路": route, "episode有効": active,
                "方向行": len(selected), "unique枠": len({(row["session"], row["slot_id"]) for row in selected}),
                "日数": len({row["session"][:10] for row in selected}), "場数": len({row["session"] for row in selected}),
                "対象現在段階": dict(sorted(Counter(current_stage(path) for path in targets).items()))}
            for role in ("T", "R"):
                paths = [prepared[row["slot_id"]]["paths"][str(row["side"])][role] for row in selected]
                ids = Counter(path["episode_id"] for path in paths if path["episode_id"] is not None)
                item[role] = {"形成あり": sum(path["episode_id"] is not None for path in paths),
                    "形成なし": sum(path["episode_id"] is None for path in paths),
                    "取消あり": sum(path["cancel"] is not None for path in paths),
                    "episode有効": sum(path["episode_valid"] for path in paths),
                    **{key + "あり": sum(path.get(key) is not None for path in paths) for key in ("b", "f", "r", "k")},
                    "k有効": sum(path["k_valid"] for path in paths), "形成ID数": len(ids),
                    "最大反復": max(ids.values(), default=0),
                    "段階": dict(sorted(Counter(str(path["stage"]) for path in paths).items()))}
            result[f"D{direction}_V{active}"] = item
    return result


def preflight() -> None:
    """本物fit前に同教師の指紋と四群の分母を保存する。

    引数: なし。
    返り値: None。学習・市場運用・独立測定なし。
    """
    if PREFLIGHT.exists():
        raise FileExistsError("65接続確認は保存済み")
    learner = load(HERE / "学習.py", "現在状態65の学習前確認")
    entries, blocks, prepared, baseline, measured, _, checks = verified_saved_inputs()
    periods, distributions = {}, {}
    for phase in P.phases(entries):
        rows, matches, identities = joined_training(phase, blocks, prepared, baseline, measured)
        used, training = learner.prepare_rows(rows, phase["evaluation_start"])
        old = C.read_json(OLD / "models" / ("Q0_" + phase["id"] + ".json"))["training"]
        if training["row_ids"] != old["row_ids"] or not same_teacher_ids(phase, training["row_ids"], identities):
            raise ValueError("旧64同教師集合に差")
        if any(training[key] != old[key] or training["base60_fingerprints"][key] != old[key] for key in learner.FINGERPRINT_FIELDS):
            raise ValueError("旧64全60canonicalに差")
        for name in ("base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints", "base54_fingerprints"):
            if training[name] != old[name]:
                raise ValueError("既存prefix指紋に差:" + name)
        periods[phase["id"]] = {"U0": {"特徴数": 60, "使用方向行": training["direction_rows"],
            "旧教師一致": matches, "教師集合一致": True, "旧64教師指紋一致": True,
            "回収追加除外pair": training["recovery_excluded_pair_count"],
            **{key: training[key] for key in (*learner.FINGERPRINT_FIELDS, "base18_fingerprints", "base30_fingerprints",
                "base38_fingerprints", "base46_fingerprints", "base54_fingerprints", "base60_fingerprints")}}}
        distributions[phase["id"]] = state_distribution(used, prepared, learner)
    C.write_json(PREFLIGHT, {"試行": 65, "接続成功": True, "検査": checks, "期間": periods,
        "価格経路分布": path_coverage(entries, blocks, prepared), "局面分布": regime_coverage(entries, blocks, prepared),
        "数量分布": F.coverage(entries, blocks, prepared), "状態分布": distributions,
        "全特徴SHA256": learner.fingerprint(prepared), "本物fit": False, "市場再生": False, "独立計測": False})
    print(json.dumps({"接続成功": True, "期間": {key: value["U0"]["使用方向行"] for key, value in periods.items()},
        "四群方向数": {phase: {group: item["方向行"] for group, item in groups.items()} for phase, groups in distributions.items()}}, ensure_ascii=False), flush=True)


def slots_for(block: dict, prepared: dict, model: dict, calibration: dict, learner, policy: str, phase: str) -> list:
    """既存の先着最高側と回収条件で当時の純判断を作る。

    引数: block/prepared/model/calibration(dict)は入力、learner(ModuleType)は木走査、policy/phase(str)は識別。
    返り値: listは旧60全辞書付き判断。raw DI同値WAITと実roleは不変。
    """
    if policy not in POLICIES or model["policy"] != "U0":
        raise ValueError("65政策と木の対応が不正")
    result = []
    for old in block["slots"]:
        feature = prepared[old["slot_id"]]
        prediction = R.predict(model, calibration, feature["vectors"], learner, "C0" if policy == "U0" else "R0") if feature["ready"] else None
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
# 人工・入力固定・本物実行を分け、旧正式物を変更しない。

def freeze() -> None:
    """人工成功と全入力・コードを本物fit前に固定する。

    引数: なし。
    返り値: None。既存固定又は人工後のコード変更は拒否する。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("65は固定済み")
    artificial = C.read_json(STUDY / "人工確認.json")
    if not artificial["成功"] or not artificial["監査人工"]["人工成功"]:
        raise ValueError("65人工が未成功")
    for relative, expected in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("人工後コード変更:" + relative)
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    pins.update(C.read_json(ROOT / "work/量と価格進行/64完了記録.json")["成果物SHA256"])
    for relative, expected in pins.items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("旧固定物変更:" + relative)
    files = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"), STUDY / "検証計画.md", PREFLIGHT,
        ROOT / "work/量と価格進行/64完了記録.json",
        ROOT / "docs/議論/外部再調査/初動と現在の前提と再点火を分ける.md"]
    for path in sorted(set(files)):
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    import sklearn
    C.write_json(STUDY / "固定.json", {"試行": 65, "固定日時": datetime.now(C.JST).isoformat(),
        "本物fit前": True, "全66場既使用": True, "ファイルSHA256": pins,
        "Python": platform.python_version(), "NumPy": C.np.__version__, "scikit-learn": sklearn.__version__})
    print("65を本物fit前に固定しました", flush=True)


def verify_lock() -> None:
    """全固定出典の内容指紋を確認する。

    引数: なし。
    返り値: None。不一致なら例外。
    """
    for relative, expected in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("固定後変更:" + relative)


def run() -> None:
    """新3木・2政策92運用を一度だけ実行する。

    引数: なし。
    返り値: None。開始記録が既存なら再起動しない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("65開始済み。既存handleを確認すること")
    verify_lock()
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    learner = load(HERE / "学習.py", "現在状態65の本物学習")
    entries, blocks, prepared, baseline, measured, old_blocks, checks = verified_saved_inputs()
    prior = C.read_json(PREFLIGHT)
    if learner.fingerprint(prepared) != prior["全特徴SHA256"]:
        raise ValueError("固定前後の60特徴に差")
    for key, value in (("価格経路分布", path_coverage(entries, blocks, prepared)),
            ("局面分布", regime_coverage(entries, blocks, prepared)), ("数量分布", F.coverage(entries, blocks, prepared))):
        if value != prior[key]:
            raise ValueError("固定前後の分母に差:" + key)
    old_result = C.read_json(OLD / "結果.json")
    operations = {p: [b["operation"] for b in old_blocks if b["policy"] == p] for p in CONTROLS}
    old_labels = P.read_rows(OLDWORK / "入口先着.jsonl.gz")
    labels = {p: [row for row in old_labels if row["policy"] == p] for p in CONTROLS}
    for policy in POLICIES:
        operations[policy], labels[policy] = [], []
    resources = [deepcopy(r) for r in C.read_json(OLD / "一覧.resources.json")["resources"] if r["method_id"] in CONTROLS]
    models, calibrations, summaries, reasons = [], [], [], []
    episode_summaries, teacher_matches, same_teachers, distribution = {}, {}, {}, {}
    fit_count = 0
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for phase in P.phases(entries):
            rows, teacher_matches[phase["id"]], old_ids = joined_training(phase, blocks, prepared, baseline, measured)
            used, training = learner.prepare_rows(rows, phase["evaluation_start"])
            expected = prior["期間"][phase["id"]]["U0"]
            if any(training[key] != expected[key] for key in learner.FINGERPRINT_FIELDS):
                raise ValueError("固定前後の教師指紋に差")
            same_teachers[phase["id"]] = same_teacher_ids(phase, training["row_ids"], old_ids)
            if not same_teachers[phase["id"]]:
                raise ValueError("旧使用教師集合に差")
            distribution[phase["id"]] = state_distribution(used, prepared, learner)
            if distribution[phase["id"]] != prior["状態分布"][phase["id"]]:
                raise ValueError("固定前後の四群に差")
            model = learner.fit(rows, F.FEATURES, "U0", "U0_" + phase["id"], phase["evaluation_start"])
            if model["training"]["row_ids"] != training["row_ids"]:
                raise ValueError("fit前後の教師集合に差")
            fit_count += sum(p["fit_performed"] for p in model["training"]["partition"].values())
            episode_summaries[model["model_id"]] = episode_support(model, prepared, learner)
            path = STUDY / "models" / (model["model_id"] + ".json")
            C.write_json(path, model)
            meta = {"id": model["model_id"], "policy": "U0", "phase": phase["id"], "path": path.relative_to(ROOT).as_posix(),
                "SHA256": C.sha(path), "学習場": [e["session"] for e in phase["train"]], "評価場": [e["session"] for e in phase["evaluation"]],
                "特徴数": 60, "評価開始": phase["evaluation_start"]}
            models.append(meta)
            calibration = R.aggregate(model, measured, phase["evaluation_start"], learner)
            calibration.update(policy="U0", phase=phase["id"], base_model_path=meta["path"], base_model_sha256=meta["SHA256"])
            for leaf in calibration["leaves"].values():
                node = model["nodes"][leaf["leaf"]]
                if (node["recovery_positive"] if node["direction_rows"] else False) != leaf["positive"]:
                    raise ValueError("回帰と回収の正額に差")
                if any(node["recovery"][f"pnl{cost}"]["mean"] != leaf["mean_yen"][str(cost)] for cost in (0, 5, 10)):
                    raise ValueError("回帰と回収の平均に差")
            cal_path = STUDY / "models" / ("回収_" + model["model_id"] + ".json")
            C.write_json(cal_path, calibration)
            calibrations.append({"id": model["model_id"], "policy": "U0", "phase": phase["id"],
                "path": cal_path.relative_to(ROOT).as_posix(), "SHA256": C.sha(cal_path)})
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                choices = {}
                for policy in POLICIES:
                    slots = slots_for(blocks[session], prepared, model, calibration, learner, policy, phase["id"])
                    choices[policy] = {slot["slot_id"]: slot["side"] for slot in slots}
                    for slot in slots:
                        if slot["side"]:
                            labels[policy].append({**baseline[slot["slot_id"], slot["side"]], "policy": policy, "role": slot["role"]})
                    operation = O.replay(events, [{key: slot[key] for key in O.SLOT_FIELDS} for slot in slots], session, policy)
                    for close in operation["closed"]:
                        expected = measured[close["slot_id"], close["side"]]["operation"]["closed"]
                        if len(expected) != 1 or not P55.equivalent_close(close, expected[0]):
                            raise ValueError("新運用と独立保存回収に差")
                        checks["同一新規完結一致"] += 1
                    operations[policy].append(operation)
                    C.jsonline(stream, {"session": session, "policy": policy, "phase": phase["id"],
                        "input_quality": quality, "slots": slots, "operation": operation})
                    trade_path = STUDY / "viewer" / (policy + "_" + session + ".trades.jsonl")
                    trade_path.parent.mkdir(parents=True, exist_ok=True)
                    with trade_path.open("w", encoding="utf-8") as trades:
                        for trade in operation["trades"]:
                            C.jsonline(trades, trade)
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 方向に対応する現在の有効状態を先に分ける",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy, "point_value": 10,
                        "pnl_format": "trades", "pnl_basis": "net", "pnl_path": trade_path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality,
                        "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                    reasons.extend({"policy": policy, "session": session, "reason": slot["reason"]} for slot in slots)
                if any(side and choices["U0"][key] != side for key, side in choices["U1"].items()):
                    raise ValueError("正回収候補が純U0同方向の部分集合でない")
                print(session + " 現在状態2運用完了", flush=True)
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
            raise ValueError("旧64Q保存対照の集計に差")
    if fit_count > 12 or sum(len(operations[policy]) for policy in POLICIES) != 92:
        raise ValueError("事前fit又は運用数規約に差")
    result = {"試行": 65, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models, "回収集計": calibrations,
        "対照モデル": [m for m in old_result["モデル"] if m["policy"] == "Q0"],
        "新回帰器fit": fit_count, "新分類器fit": 0, "新独立計測": 0, "新運用数": 92,
        "評価場": [e["session"] for e in entries[20:]], "学習専用場": [e["session"] for e in entries[:20]],
        "準備比較": old_result["準備比較"], "検査": checks, "旧教師一致": teacher_matches, "教師集合一致": same_teachers,
        "独立測定": old_result["独立測定"], "価格経路分布": path_coverage(entries, blocks, prepared),
        "経路支持": episode_summaries, "状態分布": distribution, "局面分布": regime_coverage(entries, blocks, prepared),
        "数量分布": F.coverage(entries, blocks, prepared),
        "独立測定参照": {"元試行": 55, "path": MEASUREMENTS.relative_to(ROOT).as_posix(), "sha256": C.sha(MEASUREMENTS), "再計測": False},
        "対照参照": {"候補": list(CONTROLS), "元試行": 64, "同じ評価46場": True, "市場再生": False},
        "役割別入口": {p: {s: {role: C.entry_stats([row for row in labels[p] if row["role"] == role], s) for role in ("順行", "反転")} for s in PERIODS} for p in (*CONTROLS, *POLICIES)},
        "判断理由": {p: {s: dict(Counter(row["reason"] for row in reasons if row["policy"] == p and C.period(row["session"]) == s)) for s in PERIODS} for p in POLICIES},
        "場別": summaries, "採用": [p for p in POLICIES if all(table[p][s]["同時適格"] for s in PERIODS[:2])],
        "詳細": {path.name: C.sha(path) for path in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新回帰器fit": fit_count, "新運用数": 92, "検査": checks}, ensure_ascii=False), flush=True)


def main() -> None:
    """接続・固定・単一本物実行をCLIで分ける。

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
