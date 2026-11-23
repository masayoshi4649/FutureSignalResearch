"""全定時の条件入口教師を作り、同じ可知集合の即時教師対照と比較する。"""

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
    """依存コードを固有名で読み、旧globalへの変更を避ける。

    引数: path(Path)は対象、name(str)はmodule名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


I = load(HERE / "入力.py", "条件教師69の主入力")
T = load(HERE / "教師.py", "条件教師69の三分類")
C, P, O, F = I.C, I.P, I.O, I.F
STUDY, WORK = I.STUDY, I.WORK
OLD = ROOT / "study/00068_発動前の反対端否定で条件を取り消す"
OLDWORK = ROOT / "work/条件発動前の否定/00068"
POLICIES, CONTROLS = ("I0", "I1", "C0", "C1"), ("N0", "N1")
PERIODS = ("学習", "条件選択", "後続検査")


def freeze() -> None:
    """人工・全コード・旧成功証明を新計測と学習より前に固定する。

    引数: なし。
    返り値: None。既存固定の上書きはしない。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("69は固定済み")
    artificial = C.read_json(STUDY / "人工確認.json")
    if not artificial["成功"]:
        raise ValueError("69の公式人工が未成功")
    for relative, expected in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("人工後コード変更:" + relative)
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    pins.update(C.read_json(I.LEDGER)["成果物SHA256"])
    for relative, expected in pins.items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("旧固定物変更:" + relative)
    files = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"), STUDY / "検証計画.md",
        I.PREFLIGHT, I.LEDGER, ROOT / "docs/議論/局所の否定で取り消した入口と失った成功.md",
        ROOT / "docs/議論/外部再調査/反転の確認と取得時点と教師をそろえる.md"]
    for path in sorted(set(files)):
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    import sklearn
    C.write_json(STUDY / "固定.json", {"試行": 69, "固定日時": datetime.now(C.JST).isoformat(),
        "本物計測学習前": True, "全66場既使用": True, "ファイルSHA256": pins,
        "Python": platform.python_version(), "NumPy": C.np.__version__, "scikit-learn": sklearn.__version__})
    print("69を新教師計測と学習の前に固定しました", flush=True)


def verify_lock() -> None:
    """固定した全依存の内容を検査する。

    引数: なし。
    返り値: None。不一致は例外。
    """
    for relative, expected in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("69固定後変更:" + relative)


def calibration_for(model: dict) -> dict:
    """新しい木の約定支持と約定当たり回収を選択器へ接続する。

    引数: model(dict)はI0又はC0の新しい保存木。
    返り値: dictは66選択器互換の葉集計。無取引0込みの枠平均も別欄に残す。
    """
    leaves = {}
    for node in model["nodes"]:
        if node["left"] != -1:
            continue
        leaves[str(node["id"])] = {"leaf": node["id"], "support": node["leaf_support"],
            "positive": bool(node["recovery_positive"]), "direction_rows": node["filled_direction_rows"],
            "all_direction_rows": node["direction_rows"], "unique_slots": node["unique_slots"],
            "days": node["days"], "sessions": node["sessions"], "fill_rate": node["fill_rate"],
            "sum_yen": {str(cost): node["recovery_filled"]["pnl" + str(cost)]["sum"] for cost in (0, 5, 10)},
            "mean_yen": {str(cost): node["recovery_filled"]["pnl" + str(cost)]["mean"] for cost in (0, 5, 10)},
            "mean_all_yen": {str(cost): node["recovery"]["pnl" + str(cost)]["mean"] for cost in (0, 5, 10)}}
        if any(node["recovery"]["pnl" + str(cost)]["sum"] != leaves[str(node["id"])]["sum_yen"][str(cost)] for cost in (0, 5, 10)):
            raise ValueError("無取引0以外の回収が混入")
    return {"model_id": model["model_id"], "policy": model["policy"],
        "evaluation_start": model["training"]["evaluation_start"], "leaves": leaves,
        "meaning": "共通可知教師。支持とmean_yenは約定既知のみ、mean_all_yenは確定無取引0込み"}


def slots_for(block: dict, prepared: dict, model: dict, calibration: dict, learner, selector, policy: str, phase: str) -> list:
    """当時の技法特徴だけから方向を選び、条件の発動は後段へ委ねる。

    引数: block/prepared/model/calibration(dict)は入力、learner/selector(ModuleType)は純予測、
        policy/phase(str)は新政策と分割名。
    返り値: list[dict]は全予定枠の判断。将来の約定有無を選択へ渡さない。
    """
    if policy not in POLICIES or model["policy"] != policy[0] + "0":
        raise ValueError("新政策とモデルが不一致")
    result = []
    for source in block["slots"]:
        feature = prepared[source["slot_id"]]
        prediction = selector.predict(model, calibration, feature["vectors"], learner,
            "E0" if policy.endswith("0") else "E1") if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        result.append({**{key: source[key] for key in ("session", "slot_id", "scheduled", "time", "line")},
            "policy": policy, "phase": phase, "model_id": model["model_id"], "side": side,
            "role": "順行" if side and side == feature["background_direction"] else "反転" if side else "待機",
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
            "feature": feature, "prediction": prediction})
    return result


def measure_all(entries: list, blocks: dict, prepared: dict, conditions: dict, bank_module, engine_module) -> tuple:
    """採用とは独立に全ready方向の条件先着と回収を一度ずつ測る。

    引数: entries(list)とblocks/prepared/conditions(dict)は固定入力、bank_module/engine_module(ModuleType)は計測と68運用。
    返り値: tupleは独立方向辞書・検査数・確定性分類。全日照合は各場の最初readyの両側。
    """
    measured, counts = {}, Counter()
    checks = {"独立方向数": 0, "全日単独比較": 0, "先着新規一致": 0}
    with gzip.open(WORK / "条件独立測定.jsonl.gz", "wt", encoding="utf-8") as stream:
        for entry in entries:
            session = entry["session"]
            events, quality = C.events_for(entry)
            bank, sampled = bank_module.MeasurementBank(events, session), False
            for slot in blocks[session]["slots"]:
                feature = prepared[slot["slot_id"]]
                if not feature["ready"]:
                    continue
                for side in (1, -1):
                    pure = I.pure_for(slot, feature, side)
                    identity = "M69_" + str(int(slot["scheduled"])) + ("買" if side == 1 else "売")
                    operation = bank.measure(pure, conditions[slot["slot_id"]], identity,
                        background_direction=feature["background_direction"])
                    barrier = operation["measurement"]["独立先着"]
                    if not sampled:
                        full = engine_module.replay(events, [{key: pure[key] for key in O.SLOT_FIELDS}],
                            {slot["slot_id"]: conditions[slot["slot_id"]]}, session, identity)
                        if bank_module.comparison_view(operation) != bank_module.comparison_view(full):
                            raise ValueError("条件独立測定と全日単独運用に差")
                        checks["全日単独比較"] += 1
                    descriptor = T.describe(slot, feature, side, barrier, operation, "条件")
                    record = {**{key: slot[key] for key in ("session", "slot_id", "scheduled", "time", "line")},
                        "side": side, "barrier": barrier, "operation": operation, "status": descriptor["status"],
                        "reason": descriptor["reason"], "known_end_time": descriptor["known_end_time"]}
                    measured[slot["slot_id"], side] = record
                    C.jsonline(stream, record)
                    checks["独立方向数"] += 1
                    checks["先着新規一致"] += int(barrier["filled"])
                    counts[descriptor["status"]] += 1
                sampled = True
            print(session + " 全ready条件教師計測完了", flush=True)
    return measured, checks, dict(counts)


def run() -> None:
    """新独立教師・共通集合の6木・184運用を単一の実行で保存する。

    引数: なし。
    返り値: None。開始済みは再起動せず、旧保存対照は再生しない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("69は開始済み。既存handleの終端を確認すること")
    verify_lock()
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    bank_module = load(HERE / "計測.py", "条件教師69本物計測")
    learner = load(HERE / "学習.py", "条件教師69本物学習")
    engine = load(HERE.parent / "条件発動前の否定/運用.py", "条件教師69固定68運用")
    label_module = load(HERE.parent / "条件発動前の否定/先着.py", "条件教師69固定68集計")
    selector = load(HERE.parent / "適格方向の選択/選択.py", "条件教師69固定66選択")
    entries, blocks, prepared, immediate, conditions, old_blocks, input_checks = I.verified_inputs()
    prior = C.read_json(I.PREFLIGHT)
    if input_checks != prior["検査"] or I.fingerprint(prepared) != prior["全特徴SHA256"] or I.fingerprint(conditions) != prior["全条件SHA256"]:
        raise ValueError("固定前後の入力が不一致")
    measured, checks, classification = measure_all(entries, blocks, prepared, conditions, bank_module, engine)
    if len(measured) != prior["新独立測定予定方向"]:
        raise ValueError("全準備済み方向の計測数が不一致")
    if checks["全日単独比較"] != 132:
        raise ValueError("66場の各最初ready両側132件を全日と照合する必要がある")
    old_result = C.read_json(OLD / "結果.json")
    operations = {policy: [block["operation"] for block in old_blocks if block["policy"] == policy] for policy in CONTROLS}
    labels = {policy: [row for row in P.read_rows(OLDWORK / "入口先着.jsonl.gz") if row["policy"] == policy] for policy in CONTROLS}
    saved_slots = {policy: [slot for block in old_blocks if block["policy"] == policy for slot in block["slots"]] for policy in CONTROLS}
    for policy in POLICIES:
        operations[policy], labels[policy], saved_slots[policy] = [], [], []
    resources = [deepcopy(row) for row in C.read_json(OLD / "一覧.resources.json")["resources"] if row["method_id"] in CONTROLS]
    models, calibrations, summaries, common_sets = [], [], [], {}
    fit_count = 0
    checks.update(同一条件実仮新規一致=0, 同一条件実独立完結一致=0)
    # ----------------------------------------
    # 教師の共通集合は未来の結果を保持するが、予測へ渡すのは過去木と当時特徴だけ。
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for phase in P.phases(entries):
            training_rows, common = T.prepare_common_pairs(phase, blocks, prepared, immediate, measured)
            common_sets[phase["id"]] = common
            C.write_json(WORK / ("共通教師_" + phase["id"] + ".json"), common)
            fitted = {}
            for model_policy in ("I0", "C0"):
                model = learner.fit(training_rows[model_policy], F.FEATURES, model_policy,
                    model_policy + "_" + phase["id"], phase["evaluation_start"])
                fit_count += sum(part["fit_performed"] for part in model["training"]["partition"].values())
                path = STUDY / "models" / (model["model_id"] + ".json")
                C.write_json(path, model)
                meta = {"id": model["model_id"], "policy": model_policy, "phase": phase["id"],
                    "path": path.relative_to(ROOT).as_posix(), "SHA256": C.sha(path), "特徴数": 60,
                    "学習場": [item["session"] for item in phase["train"]],
                    "評価場": [item["session"] for item in phase["evaluation"]], "評価開始": phase["evaluation_start"]}
                models.append(meta)
                cal = calibration_for(model)
                cal_path = STUDY / "models" / ("回収_" + model["model_id"] + ".json")
                C.write_json(cal_path, cal)
                calibrations.append({"id": model["model_id"], "policy": model_policy, "phase": phase["id"],
                    "path": cal_path.relative_to(ROOT).as_posix(), "SHA256": C.sha(cal_path)})
                fitted[model_policy] = model, cal
            if fitted["I0"][0]["training"]["row_ids"] != fitted["C0"][0]["training"]["row_ids"]:
                raise ValueError("対照と新条件の学習IDが異なる")
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                for policy in POLICIES:
                    model, cal = fitted[policy[0] + "0"]
                    slots = slots_for(blocks[session], prepared, model, cal, learner, selector, policy, phase["id"])
                    frozen = {slot["slot_id"]: conditions[slot["slot_id"]] for slot in slots if slot["side"]}
                    local = []
                    for slot in slots:
                        if slot["side"]:
                            label = deepcopy(measured[slot["slot_id"], slot["side"]]["barrier"])
                            label.update(policy=policy, role=slot["role"])
                            local.append(label)
                    operation = engine.replay(events, [{key: slot[key] for key in O.SLOT_FIELDS} for slot in slots], frozen, session, policy)
                    for order in operation["orders"]:
                        if order["kind"] != "entry" or order["status"] != "filled":
                            continue
                        record = measured[order["slot"]["slot_id"], order["slot"]["side"]]
                        label = record["barrier"]
                        if not label["filled"] or any(order["fill_" + key] != label["entry_" + key] for key in ("time", "line", "price")):
                            raise ValueError("一建玉の新規と独立入口に差")
                        checks["同一条件実仮新規一致"] += 1
                    for closed in operation["closed"]:
                        independent = measured[closed["slot_id"], closed["side"]]["operation"]["closed"]
                        if len(independent) != 1 or not I.P65.P55.equivalent_close(closed, independent[0]):
                            raise ValueError("一建玉完結と独立完結の経済属性に差")
                        checks["同一条件実独立完結一致"] += 1
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
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 条件入口の教師",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy,
                        "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": path.relative_to(ROOT).as_posix(),
                        "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality,
                        "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                print(session + " 共通教師4運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for label in labels[policy]:
                C.jsonline(stream, label)
    # ----------------------------------------
    # 独立教材の合算を戦略損益にせず、実一建玉と予定枠の分母で採否を判定する。
    table = {}
    for policy in (*CONTROLS, *POLICIES):
        table[policy] = {}
        for period in PERIODS:
            entrance = label_module.entry_stats(labels[policy], period, C.period)
            operation = I.P68.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": entrance, "運用": operation,
                "同時適格": entrance["70目標"] and operation["活動適格"] and operation["費用適格"]}
        if policy in CONTROLS and table[policy] != old_result["候補"][policy]:
            raise ValueError("保存68対照の再集計差")
    result = {"試行": 69, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models, "回収集計": calibrations,
        "新回帰器fit": fit_count, "新分類器fit": 0, "新保存木数": len(models), "参照モデル数": 3,
        "新独立計測": len(measured), "新条件入口評価": sum(len(labels[policy]) for policy in POLICIES), "新運用数": 184,
        "入力検査": input_checks, "検査": checks, "独立教師分類": classification, "共通教師": common_sets,
        "評価場": [entry["session"] for entry in entries[20:]], "学習専用場": [entry["session"] for entry in entries[:20]],
        "学習参照": {"元構造": 65, "同じ60特徴": True, "同じ可知集合": True,
            "I教師": "旧即時49/55", "C教師": "新68条件入口の独立先着とO49回収", "無取引": "回収0・障壁対象外"},
        "対照参照": {"候補": list(CONTROLS), "元試行": 68, "市場再生": False},
        "条件段階": {policy: {period: I.P68.stage_stats(saved_slots[policy], labels[policy], operations[policy], period)
            for period in PERIODS} for policy in POLICIES},
        "役割別入口": {policy: {period: {role: label_module.entry_stats([r for r in labels[policy] if r["role"] == role], period, C.period)
            for role in ("順行", "反転")} for period in PERIODS} for policy in (*CONTROLS, *POLICIES)},
        "判断理由": {policy: {period: dict(Counter(slot["reason"] for slot in saved_slots[policy] if C.period(slot["session"]) == period))
            for period in PERIODS} for policy in POLICIES},
        "場別": summaries, "採用": [policy for policy in POLICIES if all(table[policy][period]["同時適格"] for period in PERIODS[:2])],
        "詳細": {path.name: C.sha(path) for path in WORK.glob("*.jsonl.gz")}}
    C.write_json(STUDY / "結果.json", result)
    C.write_json(STUDY / "一覧.resources.json", {"schema_version": 1, "resources": resources})
    C.write_json(WORK / "実行完了.json", {"完了": datetime.now(C.JST).isoformat(), "結果SHA256": C.sha(STUDY / "結果.json")})
    print(json.dumps({"採用": result["採用"], "新運用数": 184, "新独立計測": len(measured), "新fit": fit_count, "検査": checks}, ensure_ascii=False), flush=True)


def main() -> None:
    """固定と本物実行を明示的な別操作として公開する。

    引数: CLIのfreeze/run(bool)は排他的な実行モード。
    返り値: None。未指定なら使い方を表示する。
    """
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--freeze", action="store_true")
    modes.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.run:
        run()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
