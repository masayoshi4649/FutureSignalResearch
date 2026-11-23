"""70監査を架空木の独立DPと固定価格人工へ接続する。fitと本物入力は使わない。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工対象と固定人工工場だけを固有名で読む。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは人工用。保存モデル・原板・教師を開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_model(factory, case: str = "nested", overrides: dict | None = None) -> dict:
    """fit0の手作り木へstrict過去境界だけを明示して付加する。

    引数: factory(ModuleType)は剪定人工、case(str)/overrides(dict|None)は架空支持設定。
    返り値: dictは監査全属性照合用のC0木。旧固定物を変更しない。
    """
    model = factory.source_factory(case, overrides)
    model["training"]["period"] = {"max_label_end_time": 9000.0, "max_recovery_end_time": 9001.0}
    return model


def check_pruning(module, factory, audit, source) -> None:
    """再帰剪定を実装側、逆ID順DPを期待側として全派生辞書を照合する。

    引数: module(ModuleType)は新監査、factory(ModuleType)は人工工場、audit/sourceは記録補助。
    返り値: None。source支持等号・個別不足・連鎖統合・不使用値・未知を確認する。
    """
    cases = [(case, None) for case in ("nested", "keep", "local_merge", "fixed_insufficient", "all_no_trade", "empty_group")]
    cases += [("keep", {5: {"filled": count, "days": days, "sessions": sessions}})
        for count, days, sessions in ((60, 6, 10), (59, 6, 10), (60, 5, 10), (60, 6, 9))]
    for number, (case, overrides) in enumerate(cases):
        old = source_model(factory, case, overrides)
        snapshot, digest = deepcopy(old), module.fingerprint(old)
        identity = "P0_人工" + str(number)
        actual = factory.P.prune(old, identity, digest)
        module.check_model(actual, old, identity, digest, audit)
        audit.check("人工元モデル不変", old, snapshot)
        geometry = module.pruning_geometry(old)
        audit.check("全新旧逆写像", {str(value): int(key) for key, value in geometry["source_to_new"].items() if value is not None}, geometry["new_to_source"])
        audit.check("人工の3固定node", [node["source_node_id"] for node in actual["nodes"][:3]], [0, 1, 2])
        if case == "nested":
            audit.check("明示の連鎖統合旧ID", geometry["retained"], [0, 1, 2, 3, 10, 11, 12])
            audit.check("不残存の判定履歴", actual["pruning"]["decisions"][1]["retained_in_final"], False)
        if case == "all_no_trade":
            audit.check("無取引既知と障壁未知", all(not node["data_absent"] and node["barrier_data_absent"] and node["score"] is None for node in actual["nodes"]), True)
        poisoned = deepcopy(old)
        for node in poisoned["nodes"]:
            node.update(score=0.0 if node["score"] is not None else None, method_support=False, impurity=999.0)
            node["recovery"]["pnl5"]["sum"] = "-999999"
        audit.check("score回収MSE技法は剪定へ不使用", module.pruning_geometry(poisoned), geometry)
    # ----------------------------------------
    # 保存物の不正は、入力支持とは別に監査が検出する。
    old = source_model(factory)
    identity, digest = "P0_破壊人工", module.fingerprint(old)
    good = factory.P.prune(old, identity, digest)
    for mutate in ("score", "mapping", "training", "path"):
        broken = deepcopy(good)
        if mutate == "score":
            broken["nodes"][3]["score"] = 0.123
        elif mutate == "mapping":
            broken["pruning"]["source_to_new"]["3"] = None
        elif mutate == "training":
            broken["training"]["partition"]["D0_V0"]["root"] = 99
        else:
            broken["nodes"][3]["path"][0]["node"] = 99
        check = source.Audit()
        module.check_model(broken, old, identity, digest, check)
        audit.check("保存改変検出:" + mutate, check.bad > 0, True)


def check_predictions(module, factory, audit) -> None:
    """派生木とcal・66適格選択・当時slotを実APIへ結合する。

    引数: module(ModuleType)は新監査、factory(ModuleType)は人工木と対象剪定器、audit(Audit)は記録。
    返り値: None。float32・鏡像・未知・未準備と全prediction辞書を検査する。
    """
    fixed = load(HERE.parent / "条件入口の教師/検証.py", "支持70監査人工の固定69校正")
    selector = load(HERE.parent / "適格方向の選択/選択.py", "支持70監査人工の固定66選択")
    main = load(HERE / "検証.py", "支持70監査人工の主接続対象")
    for case in ("nested", "keep", "fixed_insufficient", "all_no_trade", "empty_group"):
        old = source_model(factory, case)
        model = factory.P.prune(old, "P0_予測人工", module.fingerprint(old))
        cal = fixed.calibration_for(model)
        audit.check("独立cal全文", module.R69.expected_calibration(model), cal)
        vector_sets = [{"1": factory.vector(1, v), "-1": factory.vector(-1, v)} for v in (0, 1)]
        vector_sets.append({"1": [], "-1": []})
        tiny = {"1": factory.vector(1), "-1": factory.vector(-1)}
        tiny["1"][0] = 1e-50
        vector_sets.append(tiny)
        for vectors in vector_sets:
            for policy, selected in (("P0", "E0"), ("P1", "E1")):
                expected = module.expected_prediction(model, cal, vectors, policy)
                actual = selector.predict(model, cal, vectors, factory.P, selected)
                audit.check("固定66への全採否接続", actual, expected)
                mirror = {"1": deepcopy(vectors["-1"]), "-1": deepcopy(vectors["1"])}
                swapped = module.expected_prediction(model, cal, mirror, policy)
                audit.check("両方向交換の選択反転", swapped["side"], -expected["side"])
            feature = {"ready": bool(vectors["1"]), "reason": "人工未準備" if not vectors["1"] else "", "vectors": vectors,
                "background_direction": 1, "atr": 20.0, "D": 20.0}
            origin = {"session": "2026-01-01_Day", "slot_id": "人工枠", "scheduled": 100.0, "time": 100.0, "line": 1, "feature": feature}
            for policy in ("P0", "P1"):
                audit.check("主slotと監査slot全文", main.slots_for({"slots": [origin]}, {origin["slot_id"]: feature}, model, cal, factory.P, selector, policy, "人工"),
                    module.expected_slots({"slots": [origin]}, model, cal, policy, "人工"))
        valid = {"ready": True, "reason": "", "vectors": vector_sets[0], "background_direction": 0, "atr": 20.0, "D": 20.0}
        origin = {"session": "2026-01-01_Day", "slot_id": "同値枠", "scheduled": 100.0, "time": 100.0, "line": 1, "feature": valid}
        for policy in ("P0", "P1"):
            slots = module.expected_slots({"slots": [origin]}, model, cal, policy, "人工")
            audit.check("rawDI0最終WAIT", (slots[0]["side"], slots[0]["role"]), (0, "待機"))


def self_test() -> dict:
    """新70監査の実APIを架空木と固定条件価格人工だけで検査する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致、fit0・本物0の範囲。
    """
    module = load(HERE / "保存検証.py", "支持70保存監査の人工対象")
    factory = load(HERE / "剪定の人工検査.py", "支持70保存監査の架空木工場")
    source, oracle, _ = module.A.helpers()
    audit = source.Audit()
    check_pruning(module, factory, audit, source)
    check_predictions(module, factory, audit)
    # ----------------------------------------
    # 70で直接再用する条件/現金/追尾helperの入力を、架空4経路で接続する。
    material = load(HERE.parent / "条件発動前の否定/先着の人工検査.py", "支持70監査の固定68価格工場")
    measure = load(HERE.parent / "条件入口の教師/計測.py", "支持70監査の実装側架空測定")
    previous_tests = load(HERE.parent / "条件入口の教師/保存検証の人工検査.py", "支持70監査の固定69価格接続")
    previous_tests.check_operations(module.R69, measure, material, audit, source, oracle)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "人工fit": 0, "本物fit": 0, "本物入力読取": False, "実モデル剪定": 0, "市場戦略再生": False,
        "新主は人工接続だけ": True, "新剪定器は人工実装側だけ": True}


if __name__ == "__main__":
    result = self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result["人工成功"] else 1)
