"""同じ技法と教師で回収を分割目的にし、先着と正額条件を後続で比較する。"""

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
STUDY = ROOT / "study/00062_方向に対応する再開確認を先に分ける"
WORK = ROOT / "work/方向と再開確認/00062"
OLD = ROOT / "study/00061_現在有効な経路を先に分ける"
OLDWORK = ROOT / "work/現行経路の状態分岐/00061"
POLICIES = ("K0", "K1")
CONTROLS = ("A0", "A1")
PERIODS = ("学習", "条件選択", "後続検査")
MEASUREMENTS = ROOT / "work/独立追尾回収/00055/独立測定.jsonl.gz"


def load(path: Path, name: str):
    """旧大域値を変更せず固有名で純補助を読む。

    引数：path(Path)はコード、name(str)は読込名。
    返り値：ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P55 = load(ROOT / "scripts/独立追尾回収/検証.py", "回収分岐の固定55主")
P, C, O, R = P55.P, P55.C, P55.O, P55.R
PREVIOUS = load(ROOT / "scripts/現行経路の状態分岐/検証.py", "方向再開確認の固定61主")
F = load(HERE / "特徴.py", "方向再開確認の特徴62")


def verified_saved_inputs() -> tuple:
    """固定61の同46入力を再用し、保存した全評価辞書へ照合する。

    引数: なし。
    返り値: tupleはentries/blocks/prepared46/baseline/測定/旧61運用/検査数。
    """
    entries, blocks, prepared, baseline, measurements, _, inherited = PREVIOUS.verified_saved_inputs()
    checks = deepcopy(inherited)
    proof = C.read_json(OLD / "保存物確認.json")
    ledger = C.read_json(ROOT / "work/現行経路の状態分岐/61完了記録.json")
    if not proof["全件一致"] or proof["不一致数"]:
        raise ValueError("61保存監査が未成功")
    for path in [OLD / "結果.json", OLD / "一覧.resources.json", OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz"]:
        relative = path.relative_to(ROOT).as_posix()
        if C.sha(path) != proof["参照SHA256"][relative] or C.sha(path) != ledger["成果物SHA256"][relative]:
            raise ValueError("61成功proofと保存物が不一致")
    if F.FEATURES != PREVIOUS.F.FEATURES or F.RULES != PREVIOUS.F.RULES:
        raise ValueError("旧61から特徴metadata又は価格規約が変化")
    old_blocks = P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz")
    if len(old_blocks) != 92:
        raise ValueError("旧61運用数差")
    checks["旧46特徴保存一致"] = 0
    for block in old_blocks:
        for old_slot in block["slots"]:
            if prepared[old_slot["slot_id"]] != old_slot["feature"]:
                raise ValueError("旧61の全46特徴と付随状態が不一致")
            checks["旧46特徴保存一致"] += 1
    return entries, blocks, prepared, baseline, measurements, old_blocks, checks


def joined_training(phase: dict, blocks: dict, prepared: dict, baseline: dict, measurements: dict) -> tuple:
    """固定61の同46教師をそのまま使う。

    引数: phase/blocks/prepared/baseline/measurements(dict)は過去区分と同一入力。
    返り値: tupleは旧61と同じ46列教師・旧54一致・使用ID。目的値やpair集合を変えない。
    """
    return PREVIOUS.joined_training(phase, blocks, prepared, baseline, measurements)


def same_teacher_ids(phase: dict, identities: list, old_ids: list) -> bool:
    """固定55と旧54の同一教師検査を再用する。

    引数：phase(dict)、identities/old_ids(list)は使用ID。
    返り値：boolは全使用集合の一致。
    """
    return PREVIOUS.same_teacher_ids(phase, identities, old_ids)


def episode_counts(paths: list[dict]) -> dict:
    """同じ形成を複数定時で観測した重複を数える。

    引数: paths(list[dict])は一つのT/R役割の保存状態。
    返り値: dictは現episodeのunique/反復/不在とk識別。Noneを独立episodeに数えない。
    """
    ids = Counter(p["episode_id"] for p in paths if p["episode_id"] is not None)
    return {"episode数": len(ids), "episode最大反復": max(ids.values(), default=0),
        "episodeなし": sum(p["episode_id"] is None for p in paths),
        "k形成episode数": len({p["episode_id"] for p in paths if p["k"] is not None}),
        "k有効episode数": len({p["episode_id"] for p in paths if p["k_valid"]}),
        "期限失効観測": sum(p["last_expired"] is not None for p in paths)}


def episode_support(model: dict, prepared: dict, learner) -> dict:
    """過去の各葉で、方向枠と形成IDの違いを記述する。

    引数: model/prepared(dict)は使用IDと当時特徴、learner(ModuleType)は同じ保存木の走査。
    返り値: dictは全葉T/R別の反復統計。支持gateや重みへ使用しない。
    """
    selected = {n["id"]: [] for n in model["nodes"] if n["left"] == -1}
    for row in model["training"]["row_ids"]:
        feature = prepared[row["slot_id"]]
        side = str(row["side"])
        leaf, _ = learner.walk(model, feature["vectors"][side])
        selected[leaf].append(feature["paths"][side])
    return {str(leaf): {"方向行": len(rows), **{role: episode_counts([p[role] for p in rows]) for role in ("T", "R")}}
        for leaf, rows in selected.items()}


def path_coverage(entries: list, blocks: dict, prepared: dict) -> dict:
    """成績を使わず全定時の価格経路の出現数を数える。

    引数：entries(list)、blocks/prepared(dict)は全66場と当時特徴。
    返り値：dictは分母・段階・取消・経過。完成例だけを抽出しない。
    """
    ranges = {"全66場": entries, "学習専用20場": entries[:20], "時系列20場": entries[20:40],
        "条件選択24場": entries[40:64], "既使用2場": entries[64:]}
    result = {}
    for name, group in ranges.items():
        features = [prepared[s["slot_id"]] for e in group for s in blocks[e["session"]]["slots"]]
        ready = [f for f in features if f["ready"]]
        row = {"全枠": len(features), "準備枠": len(ready), "未準備枠": len(features) - len(ready), "準備方向行": len(ready) * 2}
        for role in ("T", "R"):
            paths = [f["paths"][side][role] for f in ready for side in ("1", "-1")]
            ages = [p["age"] for p in paths if p["k"] is not None]
            row[role] = {"方向行": len(paths), "段階": dict(sorted(Counter(str(p["stage"]) for p in paths).items())),
                "episode有効": sum(p["episode_valid"] for p in paths), "k形成": len(ages),
                "k有効": sum(p["k_valid"] for p in paths), "取消": sum(p["cancel"] is not None for p in paths),
                "k経過最小": min(ages) if ages else None, "k経過最大": max(ages) if ages else None,
                **episode_counts(paths)}
        result[name] = row
    return result


def state_distribution(used: list[dict], prepared: dict, learner) -> dict:
    """同じ過去教師を方向と対応経路k有効の四群へ分ける。

    引数: used(list[dict])はpair除外後教師、prepared(dict)は当時特徴、learner(ModuleType)はfloat32変換器。
    返り値: dictは四群の方向/枠/日/場とT/R状態。枝内pairを要求せず支持gateへ使わない。
    """
    result = {}
    for direction in (0, 1):
        route, index = ("R", 26) if direction == 0 else ("T", 20)
        for active in (0, 1):
            selected = [row for row in used if int(learner.float32(row["features"])[0] > 0) == direction
                and int(learner.float32(row["features"])[index] > 0.5) == active]
            item = {"方向枝": "DI非正" if direction == 0 else "DI正", "対象経路": route, "k有効": active,
                "方向行": len(selected), "unique枠": len({(row["session"], row["slot_id"]) for row in selected}),
                "日数": len({row["session"][:10] for row in selected}), "場数": len({row["session"] for row in selected})}
            for role in ("T", "R"):
                paths = [prepared[row["slot_id"]]["paths"][str(row["side"])][role] for row in selected]
                item[role] = {"形成あり": sum(p["episode_id"] is not None for p in paths),
                    "形成なし": sum(p["episode_id"] is None for p in paths),
                    "取消あり": sum(p["cancel"] is not None for p in paths),
                    "rあり": sum(p["r"] is not None for p in paths),
                    "kあり": sum(p["k"] is not None for p in paths), "k有効": sum(p["k_valid"] for p in paths),
                    "形成ID数": len({p["episode_id"] for p in paths if p["episode_id"] is not None})}
            result[f"D{direction}_K{active}"] = item
    return result


def preflight() -> None:
    """本物fit前に同教師と特徴分布だけを一度保存する。

    引数：なし。
    返り値：None。市場運用・独立計測・モデル学習をしない。
    """
    path = ROOT / "work/方向と再開確認/教師接続確認.json"
    if path.exists():
        raise FileExistsError("62接続確認は保存済み")
    learner = load(HERE / "学習.py", "方向再開62の学習前確認")
    entries, blocks, prepared, baseline, measured, _, checks = verified_saved_inputs()
    periods, distribution = {}, {}
    for phase in P.phases(entries):
        rows, matches, old_ids = joined_training(phase, blocks, prepared, baseline, measured)
        used, training = learner.prepare_rows(rows, phase["evaluation_start"])
        distribution[phase["id"]] = state_distribution(used, prepared, learner)
        old = C.read_json(ROOT / "study/00056_追尾回収を目的に技法を分岐/models" / ("G0_" + phase["id"] + ".json"))["training"]
        old61 = C.read_json(OLD / "models" / ("A0_" + phase["id"] + ".json"))["training"]
        if (training["base18_fingerprints"] != old61["base18_fingerprints"] or training["base30_fingerprints"] != old61["base30_fingerprints"] or training["base38_fingerprints"] != old61["base38_fingerprints"] or training["row_ids"] != old61["row_ids"]):
            raise ValueError("旧61と同じ過去教師/目的ではない")
        matched46 = all(value == old61[key] for key, value in training["base46_fingerprints"].items())
        if not matched46:
            raise ValueError("旧61の46特徴教師/回収と同一でない")
        matched = all(value == old[key] for key, value in training["base18_fingerprints"].items())
        same = same_teacher_ids(phase, training["row_ids"], old_ids)
        if not matched or not same:
            raise ValueError("旧56の18特徴教師/回収と同一でない")
        periods[phase["id"]] = {"旧教師一致": matches, "教師集合一致": same, "旧56教師指紋一致": matched, "旧61教師指紋一致": matched46,
            "使用方向行": training["direction_rows"], "回収追加除外pair": training["recovery_excluded_pair_count"],
            **{key: training[key] for key in ("input_rows_sha256", "used_rows_sha256", "target_rows_sha256", "base18_fingerprints", "base30_fingerprints", "base38_fingerprints", "base46_fingerprints")}}
    C.write_json(path, {"試行": 62, "接続成功": True, "検査": checks, "期間": periods,
        "価格経路分布": path_coverage(entries, blocks, prepared), "全特徴SHA256": learner.fingerprint(prepared),
        "状態分布": distribution, "本物fit": False, "市場再生": False, "独立計測": False})
    print(json.dumps({"接続成功": True, "期間": periods, "価格経路分布": path_coverage(entries, blocks, prepared)}, ensure_ascii=False), flush=True)



def slots_for(block: dict, prepared: dict, model: dict, calibration: dict, learner, policy: str, phase: str) -> list:
    """当時特徴・固定過去木だけからK0/K1を判断する。

    引数：block/prepared/model/calibration(dict)、learner(ModuleType)、policy/phase(str)は入力と識別。
    返り値：listは全予定の純判断。評価期間の回収は引数に渡さない。
    """
    mapped = {"K0": "C0", "K1": "R0"}[policy]
    result = []
    for old in block["slots"]:
        feature = prepared[old["slot_id"]]
        prediction = R.predict(model, calibration, feature["vectors"], learner, mapped) if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        role = "順行" if side and side == feature["background_direction"] else "反転" if side else "待機"
        result.append({**{k: old[k] for k in ("session", "slot_id", "scheduled", "time", "line")},
            "policy": policy, "phase": phase, "model_id": model["model_id"], "side": side, "role": role,
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
            "feature": feature, "prediction": prediction})
    return result


# ----------------------------------------
# 学習前固定、人工確認、主実行を別にする。

def freeze() -> None:
    """旧依存と新コード・条件を本物fit前に一度だけ固定する。

    引数：なし。
    返り値：None。既存固定又は依存変更を拒否する。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("62は固定済み")
    artificial = C.read_json(STUDY / "人工確認.json")
    if not artificial["成功"] or not artificial["監査人工"]["人工成功"]:
        raise ValueError("人工検査が未成功")
    for relative, expected in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("人工検査後のコード変更: " + relative)
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    for relative, expected in pins.items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("旧固定変化: " + relative)
    files = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"), STUDY / "検証計画.md"]
    files += [p for p in OLD.rglob("*") if p.is_file()]
    files += [OLDWORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [ROOT / "work/独立追尾回収/55完了記録.json", MEASUREMENTS, ROOT / "work/回収目的分岐/56完了記録.json", ROOT / "work/現行経路の状態分岐/61完了記録.json", ROOT / "work/方向と再開確認/教師接続確認.json",
              ROOT / "docs/議論/先着の技法群へ過去の追尾回収を加えた比較.md"]
    for path in sorted(set(files)):
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    import sklearn
    C.write_json(STUDY / "固定.json", {"試行": 62, "固定日時": datetime.now(C.JST).isoformat(),
        "本物fit前": True, "全66場既使用": True, "ファイルSHA256": pins,
        "Python": platform.python_version(), "NumPy": C.np.__version__, "scikit-learn": sklearn.__version__})
    print("62を本物fit前に固定しました", flush=True)


def verify_lock() -> None:
    """全固定出典の内容を照合する。

    引数：なし。
    返り値：None。不一致は例外。
    """
    for relative, expected in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("固定後変更: " + relative)


def run() -> None:
    """新回帰3木と二候補92運用を一度だけ実行する。

    引数：なし。
    返り値：None。既存実行・結果は上書きしない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("62は開始済み。既存実行の終了を確認すること")
    verify_lock()
    WORK.mkdir(parents=True, exist_ok=True)
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    learner = load(HERE / "学習.py", "方向再開確認の学習62")
    entries, blocks, prepared, baseline, measured, old_blocks, checks = verified_saved_inputs()
    preflight_record = C.read_json(ROOT / "work/方向と再開確認/教師接続確認.json")
    if learner.fingerprint(prepared) != preflight_record["全特徴SHA256"] or path_coverage(entries, blocks, prepared) != preflight_record["価格経路分布"]:
        raise ValueError("固定前接続と全当時特徴又は出現分母が不一致")
    old_result = C.read_json(OLD / "結果.json")
    operations = {p: [b["operation"] for b in old_blocks if b["policy"] == p] for p in CONTROLS}
    old_labels = P.read_rows(OLDWORK / "入口先着.jsonl.gz")
    labels = {p: [r for r in old_labels if r["policy"] == p] for p in CONTROLS}
    for policy in POLICIES:
        operations[policy], labels[policy] = [], []
    resources = [deepcopy(r) for r in C.read_json(OLD / "一覧.resources.json")["resources"] if r["method_id"] in CONTROLS]
    models, calibrations, summaries, reasons, episode_summaries = [], [], [], [], {}
    teacher_matches, same_teachers, fit_count, distribution = {}, {}, 0, {}
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for phase in P.phases(entries):
            rows, teacher_matches[phase["id"]], old_ids = joined_training(phase, blocks, prepared, baseline, measured)
            used, training_proof = learner.prepare_rows(rows, phase["evaluation_start"])
            distribution[phase["id"]] = state_distribution(used, prepared, learner)
            if distribution[phase["id"]] != preflight_record["状態分布"][phase["id"]]:
                raise ValueError("固定前と状態分布が不一致")
            prior_preparation = C.read_json(ROOT / "work/方向と再開確認/教師接続確認.json")["期間"][phase["id"]]
            if any(training_proof[k] != prior_preparation[k] for k in ("input_rows_sha256", "used_rows_sha256", "target_rows_sha256")):
                raise ValueError("固定前接続と本物教師の回収値が不一致")
            same_teachers[phase["id"]] = same_teacher_ids(phase, training_proof["row_ids"], old_ids)
            if not same_teachers[phase["id"]]:
                raise ValueError("同教師比較の使用集合が不一致")
            model = learner.fit(rows, F.FEATURES, "K0", "K0_" + phase["id"], phase["evaluation_start"])
            if model["training"]["row_ids"] != training_proof["row_ids"]:
                raise ValueError("fit前後で教師集合が不一致")
            episode_summaries[phase["id"]] = episode_support(model, prepared, learner)
            fit_count += sum(p["fit_performed"] for p in model["training"]["partition"].values())
            path = STUDY / "models" / (model["model_id"] + ".json")
            C.write_json(path, model)
            meta = {"id": model["model_id"], "policy": "K0", "phase": phase["id"], "path": path.relative_to(ROOT).as_posix(),
                "SHA256": C.sha(path), "学習場": [e["session"] for e in phase["train"]], "評価場": [e["session"] for e in phase["evaluation"]],
                "特徴数": 46, "評価開始": phase["evaluation_start"]}
            models.append(meta)
            calibration = R.aggregate(model, measured, phase["evaluation_start"], learner)
            calibration.update(phase=phase["id"], base_model_path=meta["path"], base_model_sha256=meta["SHA256"])
            for leaf in calibration["leaves"].values():
                node = model["nodes"][leaf["leaf"]]
                if (node["recovery_positive"] if node["direction_rows"] else False) != leaf["positive"]:
                    raise ValueError("回帰木と過去回収の正額判定が不一致")
                for cost in (0, 5, 10):
                    if node["recovery"][f"pnl{cost}"]["mean"] != leaf["mean_yen"][str(cost)]:
                        raise ValueError("回帰木と過去回収の平均が不一致")
            cal_path = STUDY / "models" / ("回収_" + phase["id"] + ".json")
            C.write_json(cal_path, calibration)
            calibrations.append({"id": model["model_id"], "phase": phase["id"], "path": cal_path.relative_to(ROOT).as_posix(), "SHA256": C.sha(cal_path)})
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                choices = {}
                for policy in POLICIES:
                    slots = slots_for(blocks[session], prepared, model, calibration, learner, policy, phase["id"])
                    choices[policy] = {s["slot_id"]: s["side"] for s in slots}
                    for slot in slots:
                        if slot["side"]:
                            labels[policy].append({**baseline[slot["slot_id"], slot["side"]], "policy": policy, "role": slot["role"]})
                    operation = O.replay(events, [{k: s[k] for k in O.SLOT_FIELDS} for s in slots], session, policy)
                    for close in operation["closed"]:
                        expected = measured[close["slot_id"], close["side"]]["operation"]["closed"]
                        if len(expected) != 1 or not P55.equivalent_close(close, expected[0]):
                            raise ValueError("新運用の完結と保存独立回収が不一致")
                        checks["同一新規完結一致"] += 1
                    operations[policy].append(operation)
                    C.jsonline(stream, {"session": session, "policy": policy, "phase": phase["id"], "input_quality": quality,
                        "slots": slots, "operation": operation})
                    path = STUDY / "viewer" / (policy + "_" + session + ".trades.jsonl")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8") as trades:
                        for trade in operation["trades"]:
                            C.jsonline(trades, trade)
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 方向に対応する再開確認を先に分ける",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy,
                        "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": path.relative_to(ROOT).as_posix(), "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality,
                        "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                    reasons.extend({"policy": policy, "session": session, "reason": s["reason"]} for s in slots)
                if any(side and choices["K0"][key] != side for key, side in choices["K1"].items()):
                    raise ValueError("純K1がK0の同方向部分集合でない")
                print(session + " 回収分岐2運用完了", flush=True)
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
            raise ValueError("61保存対照の再集計が不一致")
    result = {"試行": 62, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models, "回収集計": calibrations,
        "対照モデル": old_result["モデル"], "新回帰器fit": fit_count, "新分類器fit": 0, "新独立計測": 0, "新運用数": 92,
        "評価場": [e["session"] for e in entries[20:]], "学習専用場": [e["session"] for e in entries[:20]],
        "準備比較": old_result["準備比較"], "検査": checks, "旧教師一致": teacher_matches, "教師集合一致": same_teachers,
        "独立測定": old_result["独立測定"], "価格経路分布": path_coverage(entries, blocks, prepared), "経路支持": episode_summaries, "状態分布": distribution,
        "独立測定参照": {"元試行": 55, "path": MEASUREMENTS.relative_to(ROOT).as_posix(), "sha256": C.sha(MEASUREMENTS), "再計測": False},
        "対照参照": {"候補": list(CONTROLS), "元試行": 61, "同じ評価46場": True, "市場再生": False},
        "役割別入口": {p: {s: {role: C.entry_stats([r for r in labels[p] if r["role"] == role], s) for role in ("順行", "反転")} for s in PERIODS} for p in (*CONTROLS, *POLICIES)},
        "判断理由": {p: {s: dict(Counter(r["reason"] for r in reasons if r["policy"] == p and C.period(r["session"]) == s)) for s in PERIODS} for p in POLICIES},
        "場別": summaries, "採用": [p for p in POLICIES if all(table[p][s]["同時適格"] for s in PERIODS[:2])],
        "詳細": {p.name: C.sha(p) for p in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新回帰器fit": fit_count, "新運用数": 92, "検査": checks}, ensure_ascii=False), flush=True)


def main() -> None:
    """固定と単一本物実行をCLIで選択する。

    引数：なし。CLIを読み取る。
    返り値：None。
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
