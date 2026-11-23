"""同じ条件教師・支持剪定で、取得位置の追加有無を比較する。"""

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


def load(path: Path, name: str):
    """固定コード又は当試行コードを固有名で読む。

    引数: path(Path)は対象、name(str)は読込名。
    返り値: ModuleTypeは読込結果。旧globalを変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


I = load(HERE / "入力.py", "取得71の主入力")
C, P, O = I.C, I.P, I.O
PREVIOUS = I.PREVIOUS
SOURCE_MAIN = PREVIOUS.PREVIOUS
T = SOURCE_MAIN.T
STUDY, PARENT, WORK = I.STUDY, I.PARENT, I.WORK
OLD, OLDWORK, SOURCE, SOURCEWORK = I.OLD, I.OLDWORK, I.SOURCE, I.SOURCEWORK
POLICIES, CONTROLS = ("B0", "B1", "G0", "G1"), ("P0", "P1")
MODEL_POLICIES = {"B0": 60, "G0": 61}
PERIODS = PREVIOUS.PERIODS
verify_previous = I.verify_previous
calibration_for = SOURCE_MAIN.calibration_for


def freeze() -> None:
    """入力・人工・条件・依存を本物学習と市場実行の前に固定する。

    引数: なし。
    返り値: None。既存固定は上書きしない。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("71は固定済み")
    verify_previous()
    artificial = C.read_json(STUDY / "人工確認.json")
    if not artificial["成功"]:
        raise ValueError("71公式人工が未成功")
    for relative, digest in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("公式人工後のコード変更:" + relative)
    preflight = C.read_json(I.PREFLIGHT)
    if not preflight["接続成功"] or preflight["入力コードSHA256"] != C.sha(HERE / "入力.py"):
        raise ValueError("入力接続確認とコードが不一致")
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    pins.update(C.read_json(I.LEDGER)["成果物SHA256"])
    files = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"), STUDY / "検証計画.md", I.PREFLIGHT, I.LEDGER]
    files += [path for path in PARENT.iterdir() if path.is_file()]
    files += [ROOT / "docs/議論/約定支持を保つ統合で増えた参加と回収.md",
        ROOT / "docs/議論/外部再調査/継続の方向と取得位置と短期保護を分ける.md",
        ROOT / "docs/議論/外部再調査/期待した進行の不発と取得保護の距離を分ける.md",
        ROOT / "docs/議論/外部再調査/取得前の距離と取得後の保護を分ける.md"]
    for path in sorted(set(files)):
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    for relative, digest in pins.items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("固定前の旧依存変更:" + relative)
    import sklearn
    C.write_json(STUDY / "固定.json", {"試行": 71, "固定日時": datetime.now(C.JST).isoformat(),
        "本物学習と市場実行前": True, "全66場既使用": True, "ファイルSHA256": pins,
        "Python": platform.python_version(), "NumPy": C.np.__version__, "scikit-learn": sklearn.__version__})
    print("71を本物学習・剪定・市場実行の前に固定しました", flush=True)


def verify_lock() -> None:
    """新旧固定依存の内容を照合する。

    引数: なし。
    返り値: None。不一致は例外。
    """
    for relative, digest in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != digest:
            raise ValueError("71固定後変更:" + relative)


def common_training(phase: dict, blocks: dict, base: dict, extended: dict, immediate: dict, measured: dict) -> tuple:
    """旧69の同じ可知pairと条件教師を、60列対照と61列へ写す。

    引数: phase/blocks/base/extended/immediate/measured(dict)は固定分割・入力・保存教師。
    返り値: tupleは政策別教師と旧共通集合の要約。追加の除外や0補完をしない。
    """
    original, common = T.prepare_common_pairs(phase, blocks, base, immediate, measured)
    expected = C.read_json(SOURCE / "結果.json")["共通教師"][phase["id"]]
    if common != expected:
        raise ValueError("旧69の共通教師集合と不一致")
    rows = {"B0": deepcopy(original["C0"]), "G0": []}
    for old in rows["B0"]:
        new = deepcopy(old)
        new["features"] = deepcopy(extended[old["slot_id"]]["vectors"][str(old["side"])])
        projection = {**new, "features": new["features"][:60]}
        if projection != old or len(new["features"]) != 61:
            raise ValueError("同教師への61列接続で旧行が変化")
        rows["G0"].append(new)
    summary = {key: deepcopy(common[key]) for key in ("全予定枠", "共通可知枠", "共通方向行", "除外枠数", "使用分類", "共通ID同順序", "方向重み")}
    summary.update(旧69共通集合SHA256=I.I69.fingerprint(common), 旧69結果path=(SOURCE / "結果.json").relative_to(ROOT).as_posix())
    return rows, summary


def verify_baseline(raw: dict, derived: dict, phase: str) -> None:
    """再fitした60列側の統計と剪定構造が旧69・70を再現することを確認する。

    引数: raw/derived(dict)はB0の元木と派生木、phase(str)は分割ID。
    返り値: None。識別・説明・provenance以外の保存学習統計を比較する。
    """
    source = C.read_json(SOURCE / "models" / ("C0_" + phase + ".json"))
    previous = C.read_json(OLD / "models" / ("P0_" + phase + ".json"))
    for key in ("nodes", "feature_meta", "parameters", "subtree_parameters", "versions"):
        if raw[key] != source[key]:
            raise ValueError("60列対照の元69再現差:" + key)
    keys = ("evaluation_start", "input_pairs", "used_pairs", "direction_rows", "filled_direction_rows", "unfilled_direction_rows",
        "row_ids", "input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "used_barrier_rows_sha256",
        "period", "period_sha256", "weight_per_direction", "total_weight")
    if any(raw["training"][key] != source["training"][key] for key in keys):
        raise ValueError("60列対照の訓練集合・目標が不一致")
    partition = deepcopy(raw["training"]["partition"])
    for item in partition.values():
        item["policy"] = "C0"
    if partition != source["training"]["partition"] or derived["nodes"] != previous["nodes"]:
        raise ValueError("60列対照の配置又は派生nodeが不一致")


def model_meta(model: dict, phase: dict, path: Path) -> dict:
    """保存木の参照情報と分割をまとめる。

    引数: model/phase(dict)は保存木と分割、path(Path)は保存先。
    返り値: dictは結果へ置く参照metadata。
    """
    return {"id": model["model_id"], "policy": model["policy"], "phase": phase["id"],
        "path": path.relative_to(ROOT).as_posix(), "SHA256": C.sha(path), "特徴数": len(model["feature_meta"]),
        "学習場": [row["session"] for row in phase["train"]], "評価場": [row["session"] for row in phase["evaluation"]],
        "評価開始": phase["evaluation_start"]}


def slots_for(block: dict, prepared: dict, model: dict, calibration: dict, learner, selector, policy: str, phase: str) -> list:
    """当時情報と過去木だけで両方向の適格候補を選ぶ。

    引数: block/prepared/model/calibration(dict)は当時情報と過去木、learner/selector(ModuleType)は純予測、
        policy/phase(str)は政策と分割。
    返り値: list[dict]は全予定判断。未来ラベルを予測へ渡さない。
    """
    if policy not in POLICIES or model["policy"] != policy[0] + "0":
        raise ValueError("政策と木の不一致")
    result = []
    for source in block["slots"]:
        feature = prepared[source["slot_id"]]
        prediction = selector.predict(model, calibration, feature["vectors"], learner,
            "E0" if policy.endswith("0") else "E1") if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        result.append({**{key: source[key] for key in I.IDENTITY}, "policy": policy, "phase": phase,
            "model_id": model["model_id"], "side": side,
            "role": "順行" if side and side == feature["background_direction"] else "反転" if side else "待機",
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
            "feature": feature, "prediction": prediction})
    return result


def verify_control_operation(slots: list, operation: dict, old: dict) -> None:
    """新Bと旧Pの判断・運用経済が同じであることを照合する。

    引数: slots(list)とoperation(dict)は新B、old(dict)は同場・対応旧P保存物。
    返り値: None。政策IDや注文識別子を経済差としない。
    """
    fields = (*I.IDENTITY, "side", "role", "ready", "reason", "atr", "D", "feature", "prediction")
    if len(slots) != len(old["slots"]) or any(any(new[key] != prior[key] for key in fields) for new, prior in zip(slots, old["slots"])):
        raise ValueError("60列再現対照の定時判断が旧Pと異なる")
    previous = old["operation"]
    if operation["metrics"] != previous["metrics"] or operation["quality"] != previous["quality"]:
        raise ValueError("60列再現対照の運用集計が旧Pと異なる")
    if len(operation["closed"]) != len(previous["closed"]) or any(not I.I69.P65.P55.equivalent_close(a, b) for a, b in zip(operation["closed"], previous["closed"])):
        raise ValueError("60列再現対照の実完結が旧Pと異なる")


def run() -> None:
    """同集合の60/61列を新fit・支持剪定し、四政策を一度だけ評価する。

    引数: なし。
    返り値: None。開始済みは拒否し、保存対照・独立教師を再計測しない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("71開始済み。既存handleの終端を確認すること")
    verify_lock()
    old_result = verify_previous()
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    learner = load(HERE / "学習.py", "取得71本物学習")
    engine = load(HERE.parent / "条件発動前の否定/運用.py", "取得71固定68運用")
    label_module = load(HERE.parent / "条件発動前の否定/先着.py", "取得71固定68集計")
    selector = load(HERE.parent / "適格方向の選択/選択.py", "取得71固定66選択")
    entries, blocks, base, extended, immediate, conditions, measured, old_blocks, input_checks = I.verified_inputs()
    if input_checks != C.read_json(I.PREFLIGHT)["検査"]:
        raise ValueError("71固定前後の入力が不一致")
    by_policy = {"B0": base, "G0": extended}
    old_index = {(block["session"], block["policy"]): block for block in old_blocks}
    operations = {policy: [row["operation"] for row in old_blocks if row["policy"] == policy] for policy in CONTROLS}
    prior_labels = P.read_rows(OLDWORK / "入口先着.jsonl.gz")
    labels = {policy: [row for row in prior_labels if row["policy"] == policy] for policy in CONTROLS}
    saved_slots = {policy: [slot for row in old_blocks if row["policy"] == policy for slot in row["slots"]] for policy in CONTROLS}
    for policy in POLICIES:
        operations[policy], labels[policy], saved_slots[policy] = [], [], []
    resources = [deepcopy(row) for row in C.read_json(OLD / "一覧.resources.json")["resources"] if row["method_id"] in CONTROLS]
    models, raw_models, calibrations, summaries, common_sets, pruning = [], [], [], [], {}, {}
    checks = {"同一条件実仮新規一致": 0, "同一条件実独立完結一致": 0, "旧69元木再現": 0, "旧70派生木再現": 0, "旧70運用再現": 0}
    fit_count = 0
    # ----------------------------------------
    # 教師は評価開始より前に確定した共通pairだけ。二政策の情報追加以外をそろえる。
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for phase in P.phases(entries):
            training, common_sets[phase["id"]] = common_training(phase, blocks, base, extended, immediate, measured)
            fitted, pruning[phase["id"]] = {}, {}
            for model_policy, count in MODEL_POLICIES.items():
                raw_id = model_policy + "_" + phase["id"] + "_学習"
                raw = learner.fit(training[model_policy], I.F.FEATURES if count == 60 else I.FEATURES,
                    phase["evaluation_start"], model_policy, raw_id)
                fit_count += sum(item["fit_performed"] for item in raw["training"]["partition"].values())
                raw_path = STUDY / "models" / (raw_id + ".json")
                C.write_json(raw_path, raw)
                raw_models.append(model_meta(raw, phase, raw_path))
                model = learner.prune(raw, model_policy + "_" + phase["id"], C.sha(raw_path))
                path = STUDY / "models" / (model["model_id"] + ".json")
                C.write_json(path, model)
                meta = model_meta(model, phase, path)
                meta.update(元path=raw_path.relative_to(ROOT).as_posix(), 元SHA256=C.sha(raw_path))
                models.append(meta)
                if model_policy == "B0":
                    verify_baseline(raw, model, phase["id"])
                    checks["旧69元木再現"] += 1
                    checks["旧70派生木再現"] += 1
                cal = calibration_for(model)
                cal_path = STUDY / "models" / ("回収_" + model["model_id"] + ".json")
                C.write_json(cal_path, cal)
                calibrations.append({"id": model["model_id"], "policy": model_policy, "phase": phase["id"],
                    "path": cal_path.relative_to(ROOT).as_posix(), "SHA256": C.sha(cal_path)})
                fitted[model_policy] = model, cal
                pruning[phase["id"]][model_policy] = model["pruning"]
            if fitted["B0"][0]["training"]["row_ids"] != fitted["G0"][0]["training"]["row_ids"]:
                raise ValueError("60/61列の共通教師IDが異なる")
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                for policy in POLICIES:
                    model_policy = policy[0] + "0"
                    model, cal = fitted[model_policy]
                    slots = slots_for(blocks[session], by_policy[model_policy], model, cal, learner, selector, policy, phase["id"])
                    frozen = {slot["slot_id"]: conditions[slot["slot_id"]] for slot in slots if slot["side"]}
                    local = []
                    for slot in slots:
                        if slot["side"]:
                            label = deepcopy(measured[slot["slot_id"], slot["side"]]["barrier"])
                            label.update(policy=policy, role=slot["role"])
                            local.append(label)
                    operation = engine.replay(events, [{key: slot[key] for key in O.SLOT_FIELDS} for slot in slots], frozen, session, policy)
                    for order in operation["orders"]:
                        if order["kind"] == "entry" and order["status"] == "filled":
                            label = measured[order["slot"]["slot_id"], order["slot"]["side"]]["barrier"]
                            if not label["filled"] or any(order["fill_" + key] != label["entry_" + key] for key in ("time", "line", "price")):
                                raise ValueError("一建玉の新規と旧69独立入口に差")
                            checks["同一条件実仮新規一致"] += 1
                    for closed in operation["closed"]:
                        independent = measured[closed["slot_id"], closed["side"]]["operation"]["closed"]
                        if len(independent) != 1 or not I.I69.P65.P55.equivalent_close(closed, independent[0]):
                            raise ValueError("一建玉完結と旧69独立完結に差")
                        checks["同一条件実独立完結一致"] += 1
                    if policy.startswith("B"):
                        verify_control_operation(slots, operation, old_index[session, "P" + policy[1]])
                        checks["旧70運用再現"] += 1
                    saved_slots[policy].extend(slots)
                    labels[policy].extend(local)
                    operations[policy].append(operation)
                    C.jsonline(stream, {"session": session, "phase": phase["id"], "policy": policy,
                        "slots": slots, "conditions": frozen, "input_quality": quality, "operation": operation})
                    path = STUDY / "viewer" / (policy + "_" + session + ".trades.jsonl")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8") as trades:
                        for trade in operation["trades"]:
                            C.jsonline(trades, trade)
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 取得位置と支持",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy,
                        "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": path.relative_to(ROOT).as_posix(),
                        "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality,
                        "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                print(session + " 取得位置の有無4運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for label in labels[policy]:
                C.jsonline(stream, label)
    # ----------------------------------------
    # 全予定・純候補・仮約定と実完結の分母を別々に保つ。
    table = {}
    for policy in (*CONTROLS, *POLICIES):
        table[policy] = {}
        for period in PERIODS:
            entrance = label_module.entry_stats(labels[policy], period, C.period)
            operation = I.I69.P68.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": entrance, "運用": operation,
                "同時適格": entrance["70目標"] and operation["活動適格"] and operation["費用適格"]}
        if policy in CONTROLS and table[policy] != old_result["候補"][policy]:
            raise ValueError("70保存対照の再集計差")
        if policy.startswith("B") and table[policy] != table["P" + policy[1]]:
            raise ValueError("新60列対照と旧70の全体集計差")
    if fit_count != 24 or len(summaries) != 184 or len(models) != 6:
        raise ValueError("予定した学習・木・運用の件数に差")
    result = {"試行": 71, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models, "元学習モデル": raw_models,
        "回収集計": calibrations, "新回帰器fit": fit_count, "新分類器fit": 0, "新保存木数": 12,
        "新元学習木数": 6, "新派生木数": 6, "参照モデル数": 3, "新独立計測": 0, "参照独立測定": 4092,
        "新条件入口評価": sum(len(labels[policy]) for policy in POLICIES), "新運用数": 184,
        "入力検査": input_checks, "検査": checks, "剪定": pruning, "共通教師": common_sets,
        "評価場": [entry["session"] for entry in entries[20:]], "学習専用場": [entry["session"] for entry in entries[:20]],
        "学習参照": {"元試行": 69, "モデル政策": "C0", "同じ可知集合": True, "同じ条件教師": True,
            "基礎60投影同値": True, "新fit": True, "追加": I.POSITION_META, "無取引": "回収0・障壁対象外"},
        "対照参照": {"候補": list(CONTROLS), "元試行": 70, "市場再生": False},
        "条件段階": {policy: {period: I.I69.P68.stage_stats(saved_slots[policy], labels[policy], operations[policy], period)
            for period in PERIODS} for policy in POLICIES},
        "役割別入口": {policy: {period: {role: label_module.entry_stats([row for row in labels[policy] if row["role"] == role], period, C.period)
            for role in ("順行", "反転")} for period in PERIODS} for policy in (*CONTROLS, *POLICIES)},
        "判断理由": {policy: {period: dict(Counter(slot["reason"] for slot in saved_slots[policy] if C.period(slot["session"]) == period))
            for period in PERIODS} for policy in POLICIES},
        "場別": summaries, "採用": [policy for policy in POLICIES if all(table[policy][period]["同時適格"] for period in PERIODS[:2])],
        "詳細": {path.name: C.sha(path) for path in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新運用数": 184, "新元学習木数": 6, "新派生木数": 6,
        "新回帰器fit": fit_count, "検査": checks}, ensure_ascii=False), flush=True)


def main() -> None:
    """固定と単一本物実行を排他的CLIへ公開する。

    引数: CLIのfreeze/run(bool)はモード。
    返り値: None。指定なしは説明だけ表示する。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.run:
        run()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
