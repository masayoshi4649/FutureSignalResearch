"""固定69の条件教師木を支持だけでまとめ、同じ条件入口で比較する。"""

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
    """固定コードを固有名で読み、旧globalを変更しない。

    引数: path(Path)は対象、name(str)はmodule名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS = load(HERE.parent / "条件入口の教師/検証.py", "支持70の固定69主純関数")
I, C, P, O = PREVIOUS.I, PREVIOUS.C, PREVIOUS.P, PREVIOUS.O
STUDY = ROOT / "study/00070_約定支持を保つ粒度で技法を組み合わせる"
PARENT = ROOT / "work/支持を保つ技法群"
WORK = PARENT / "00070"
OLD, OLDWORK = PREVIOUS.STUDY, PREVIOUS.WORK
LEDGER = ROOT / "work/条件入口の教師/69完了記録.json"
LEDGER_SHA = "e0508f5171257e928194f631729e3e509d707c0feea2cd5fb9b5459cae25ac1f"
POLICIES, CONTROLS = ("P0", "P1"), ("C0", "C1")
PERIODS = PREVIOUS.PERIODS


def verify_previous() -> dict:
    """69成功証拠と完了台帳の全対象を検査する。

    引数: なし。
    返り値: dictは旧結果。市場・学習・特徴再構成を実行しない。
    """
    if C.sha(LEDGER) != LEDGER_SHA:
        raise ValueError("69完了台帳の変更")
    ledger = C.read_json(LEDGER)
    for relative, expected in ledger["成果物SHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("69完了物の変更:" + relative)
    proof = C.read_json(OLD / "保存物確認.json")
    done = C.read_json(OLDWORK / "実行完了.json")
    if not proof["全件一致"] or proof["不一致数"] or C.sha(OLD / "結果.json") != proof["結果SHA256"] or proof["結果SHA256"] != done["結果SHA256"]:
        raise ValueError("69の成功証拠が不一致")
    return C.read_json(OLD / "結果.json")


def freeze() -> None:
    """新剪定と市場実行の前に、条件・コード・旧成功証拠を固定する。

    引数: なし。
    返り値: None。既存固定は上書きしない。
    """
    if (STUDY / "固定.json").exists():
        raise FileExistsError("70は固定済み")
    verify_previous()
    artificial = C.read_json(STUDY / "人工確認.json")
    if not artificial["成功"]:
        raise ValueError("70の人工未成功")
    for relative, expected in artificial["コードSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("人工後コード変更:" + relative)
    pins = dict(C.read_json(OLD / "固定.json")["ファイルSHA256"])
    pins.update(C.read_json(LEDGER)["成果物SHA256"])
    files = [*HERE.glob("*.py"), *HERE.glob("*.md"), *STUDY.glob("*.json"), STUDY / "検証計画.md", LEDGER]
    files += [path for path in PARENT.iterdir() if path.is_file()]
    files += [ROOT / "docs/議論/条件入口の教師と約定支持をそろえる.md",
        ROOT / "docs/議論/外部再調査/継続の方向と取得位置と短期保護を分ける.md",
        ROOT / "docs/議論/外部再調査/技法群の細分化と約定支持を分ける.md"]
    for path in sorted(set(files)):
        pins[path.relative_to(ROOT).as_posix()] = C.sha(path)
    for relative, expected in pins.items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("固定前の参照不一致:" + relative)
    C.write_json(STUDY / "固定.json", {"試行": 70, "固定日時": datetime.now(C.JST).isoformat(),
        "派生木作成と市場実行前": True, "全66場既使用": True, "ファイルSHA256": pins,
        "Python": platform.python_version(), "NumPy": C.np.__version__, "新fit": 0})
    print("70を派生木作成と市場実行の前に固定しました", flush=True)


def verify_lock() -> None:
    """新旧固定依存の指紋を照合する。

    引数: なし。
    返り値: None。不一致は例外。
    """
    for relative, expected in C.read_json(STUDY / "固定.json")["ファイルSHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("70固定後変更:" + relative)


def verified_inputs() -> tuple:
    """既存算術で当時入力を再構成し、固定69の全特徴・全条件へ結合する。

    引数: なし。
    返り値: tupleはentries/blocks/prepared/conditions/旧69全独立/旧C運用/入力検査。
    """
    entries, blocks, prepared, _, conditions, _, checks = I.verified_inputs()
    prior = C.read_json(I.PREFLIGHT)
    if checks != prior["検査"] or I.fingerprint(prepared) != prior["全特徴SHA256"] or I.fingerprint(conditions) != prior["全条件SHA256"]:
        raise ValueError("69の全特徴又は条件線と不一致")
    records = P.read_rows(OLDWORK / "条件独立測定.jsonl.gz")
    measured = {(row["slot_id"], row["side"]): row for row in records}
    if len(records) != len(measured) or len(measured) != 4092:
        raise ValueError("69独立測定の件数又は重複")
    expected = {(slot["slot_id"], side) for block in blocks.values() for slot in block["slots"]
        if prepared[slot["slot_id"]]["ready"] for side in (1, -1)}
    if set(measured) != expected:
        raise ValueError("69のready全方向に対する保存測定が不一致")
    old_blocks = [row for row in P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz") if row["policy"] in CONTROLS]
    if len(old_blocks) != 92:
        raise ValueError("69C保存対照の件数不一致")
    for block in old_blocks:
        for slot in block["slots"]:
            if slot["feature"] != prepared[slot["slot_id"]]:
                raise ValueError("69評価時特徴と70当時特徴が不一致")
    return entries, blocks, prepared, conditions, measured, old_blocks, {**checks,
        "69全特徴SHA256": prior["全特徴SHA256"], "69全条件SHA256": prior["全条件SHA256"],
        "保存独立方向": len(measured), "保存C運用": len(old_blocks)}


def slots_for(block: dict, prepared: dict, model: dict, calibration: dict, learner, selector, policy: str, phase: str) -> list:
    """当時の複数技法特徴と剪定木で方向を選び、固定68入口へ渡す。

    引数: block/prepared/model/calibration(dict)は当時入力と過去モデル、learner/selector(ModuleType)は純予測、
        policy/phase(str)は政策と分割。
    返り値: list[dict]は全予定判断。将来の先着・約定有無を予測へ渡さない。
    """
    if policy not in POLICIES or model["policy"] != "P0":
        raise ValueError("P政策と派生木の不一致")
    result = []
    for source in block["slots"]:
        feature = prepared[source["slot_id"]]
        prediction = selector.predict(model, calibration, feature["vectors"], learner,
            "E0" if policy == "P0" else "E1") if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        result.append({**{key: source[key] for key in ("session", "slot_id", "scheduled", "time", "line")},
            "policy": policy, "phase": phase, "model_id": model["model_id"], "side": side,
            "role": "順行" if side and side == feature["background_direction"] else "反転" if side else "待機",
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
            "feature": feature, "prediction": prediction})
    return result


def run() -> None:
    """旧教師を再計測せず三派生木と新二政策を一回だけ実行する。

    引数: なし。
    返り値: None。開始済みは拒否し、旧対照・新fitを実行しない。
    """
    if (WORK / "実行開始.json").exists() or (STUDY / "結果.json").exists():
        raise FileExistsError("70は開始済み。実行handleの終端を確認すること")
    verify_lock()
    old_result = verify_previous()
    C.write_json(WORK / "実行開始.json", {"開始": datetime.now(C.JST).isoformat(), "固定SHA256": C.sha(STUDY / "固定.json")})
    learner = load(HERE / "剪定.py", "支持70本物の支持剪定")
    engine = load(HERE.parent / "条件発動前の否定/運用.py", "支持70固定68運用")
    label_module = load(HERE.parent / "条件発動前の否定/先着.py", "支持70固定68先着集計")
    selector = load(HERE.parent / "適格方向の選択/選択.py", "支持70固定66選択")
    entries, blocks, prepared, conditions, measured, old_blocks, input_checks = verified_inputs()
    operations = {policy: [row["operation"] for row in old_blocks if row["policy"] == policy] for policy in CONTROLS}
    old_labels = P.read_rows(OLDWORK / "入口先着.jsonl.gz")
    labels = {policy: [row for row in old_labels if row["policy"] == policy] for policy in CONTROLS}
    saved_slots = {policy: [slot for row in old_blocks if row["policy"] == policy for slot in row["slots"]] for policy in CONTROLS}
    for policy in POLICIES:
        operations[policy], labels[policy], saved_slots[policy] = [], [], []
    resources = [deepcopy(row) for row in C.read_json(OLD / "一覧.resources.json")["resources"] if row["method_id"] in CONTROLS]
    models, calibrations, summaries, pruning = [], [], [], {}
    checks = {"同一条件実仮新規一致": 0, "同一条件実独立完結一致": 0}
    # ----------------------------------------
    # 各評価開始より前の保存学習木だけを剪定し、新指標・新教師を作らない。
    with gzip.open(WORK / "定時判断と運用.jsonl.gz", "wt", encoding="utf-8") as stream:
        for phase in P.phases(entries):
            source_path = OLD / "models" / ("C0_" + phase["id"] + ".json")
            source = C.read_json(source_path)
            if source["training"]["evaluation_start"] != phase["evaluation_start"]:
                raise ValueError("旧モデルの評価開始に差")
            model = learner.prune(source, "P0_" + phase["id"], C.sha(source_path))
            path = STUDY / "models" / (model["model_id"] + ".json")
            C.write_json(path, model)
            meta = {"id": model["model_id"], "policy": "P0", "phase": phase["id"], "path": path.relative_to(ROOT).as_posix(),
                "SHA256": C.sha(path), "特徴数": 60, "元path": source_path.relative_to(ROOT).as_posix(), "元SHA256": C.sha(source_path),
                "学習場": [item["session"] for item in phase["train"]], "評価場": [item["session"] for item in phase["evaluation"]],
                "評価開始": phase["evaluation_start"]}
            models.append(meta)
            cal = PREVIOUS.calibration_for(model)
            cal_path = STUDY / "models" / ("回収_" + model["model_id"] + ".json")
            C.write_json(cal_path, cal)
            calibrations.append({"id": model["model_id"], "policy": "P0", "phase": phase["id"],
                "path": cal_path.relative_to(ROOT).as_posix(), "SHA256": C.sha(cal_path)})
            pruning[phase["id"]] = model["pruning"]
            for entry in phase["evaluation"]:
                session = entry["session"]
                events, quality = C.events_for(entry)
                for policy in POLICIES:
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
                        if order["kind"] == "entry" and order["status"] == "filled":
                            label = measured[order["slot"]["slot_id"], order["slot"]["side"]]["barrier"]
                            if not label["filled"] or any(order["fill_" + key] != label["entry_" + key] for key in ("time", "line", "price")):
                                raise ValueError("実新規と69独立入口に差")
                            checks["同一条件実仮新規一致"] += 1
                    for closed in operation["closed"]:
                        independent = measured[closed["slot_id"], closed["side"]]["operation"]["closed"]
                        if len(independent) != 1 or not I.P65.P55.equivalent_close(closed, independent[0]):
                            raise ValueError("実完結と69独立回収に差")
                        checks["同一条件実独立完結一致"] += 1
                    saved_slots[policy].extend(slots)
                    labels[policy].extend(local)
                    operations[policy].append(operation)
                    C.jsonline(stream, {"session": session, "phase": phase["id"], "policy": policy,
                        "slots": slots, "conditions": frozen, "input_quality": quality, "operation": operation})
                    trade_path = STUDY / "viewer" / (policy + "_" + session + ".trades.jsonl")
                    trade_path.parent.mkdir(parents=True, exist_ok=True)
                    with trade_path.open("w", encoding="utf-8") as trades:
                        for trade in operation["trades"]:
                            C.jsonline(trades, trade)
                    resources.append({"id": session + "_" + policy, "title": session + " " + policy + " 支持を保つ技法群",
                        "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": policy,
                        "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": trade_path.relative_to(ROOT).as_posix(),
                        "market_path": entry["source_path"]})
                    summaries.append({"場": session, "候補": policy, "期間": C.period(session), "入力品質": quality,
                        "運用品質": operation["quality"], "運用集計": operation["metrics"]})
                print(session + " 支持剪定2運用完了", flush=True)
    with gzip.open(WORK / "入口先着.jsonl.gz", "wt", encoding="utf-8") as stream:
        for policy in POLICIES:
            for label in labels[policy]:
                C.jsonline(stream, label)
    # ----------------------------------------
    # 入口・実一建玉・全予定枠を別分母で集計し、固定した目標で判定する。
    table = {}
    for policy in (*CONTROLS, *POLICIES):
        table[policy] = {}
        for period in PERIODS:
            entrance = label_module.entry_stats(labels[policy], period, C.period)
            operation = I.P68.operation_stats(operations[policy], period)
            table[policy][period] = {"入口": entrance, "運用": operation,
                "同時適格": entrance["70目標"] and operation["活動適格"] and operation["費用適格"]}
        if policy in CONTROLS and table[policy] != old_result["候補"][policy]:
            raise ValueError("69C保存対照の再集計差")
    result = {"試行": 70, "実行日時": datetime.now(C.JST).isoformat(), "全66場既使用": True,
        "固定SHA256": C.sha(STUDY / "固定.json"), "候補": table, "モデル": models, "回収集計": calibrations,
        "新回帰器fit": 0, "新分類器fit": 0, "新保存木数": 3, "新派生木数": 3, "参照モデル数": 3,
        "新独立計測": 0, "参照独立測定": 4092, "新条件入口評価": sum(len(labels[policy]) for policy in POLICIES),
        "新運用数": 92, "入力検査": input_checks, "検査": checks, "剪定": pruning,
        "評価場": [entry["session"] for entry in entries[20:]], "学習専用場": [entry["session"] for entry in entries[:20]],
        "学習参照": {"元試行": 69, "モデル政策": "C0", "同じ60特徴": True, "新fit": False,
            "共通教師": (OLD / "結果.json").relative_to(ROOT).as_posix(), "無取引": "回収0・障壁対象外"},
        "対照参照": {"候補": list(CONTROLS), "元試行": 69, "市場再生": False},
        "条件段階": {policy: {period: I.P68.stage_stats(saved_slots[policy], labels[policy], operations[policy], period)
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
    print(json.dumps({"採用": result["採用"], "新運用数": 92, "新派生木数": 3, "新fit": 0, "検査": checks}, ensure_ascii=False), flush=True)


def main() -> None:
    """固定と単一本物実行を排他的CLIで公開する。

    引数: CLIのfreeze/run(bool)は実行モード。
    返り値: None。未指定は説明だけ表示する。
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
