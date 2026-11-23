"""69保存監査を、人工教師・二つの人工fit・少数の条件運用へ接続する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工対象と既存の人工工場だけを固有名で読む。

    引数: path(Path)はPython、name(str)はmodule名。
    返り値: ModuleTypeは読込結果。正式入力・保存モデルは読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rejected(function, *args, **kwargs) -> bool:
    """少数の不正入力が明示拒否されたことを確認する。

    引数: function(Callable)は対象、args/kwargsは人工引数。
    返り値: boolはValueError又はTypeErrorで拒否された場合True。
    """
    try:
        function(*args, **kwargs)
    except (ValueError, TypeError):
        return True
    return False


def check_teachers(audit_module, teacher_fixture, audit) -> None:
    """独立分類・共通pair・canonicalを主教師の人工辞書と照合する。

    引数: audit_module(ModuleType)は新監査、teacher_fixture(ModuleType)は人工工場、audit(Audit)は記録。
    返り値: None。正式測定やfitを呼ばない。
    """
    slot, feature = teacher_fixture.sample_inputs()
    target = teacher_fixture.T
    for source, outcome, filled in (("即時", "未約定", False), ("条件", "設定否定", False),
            ("条件", "前提否定", False), ("条件", "未発動", False), ("条件", "発動未約定", False),
            ("即時", "250", True), ("条件", "125", True), ("条件", "期限", True)):
        data = teacher_fixture.measurement(slot, filled, outcome)
        audit.check("分類全文:" + source + outcome,
            audit_module.teacher_description(slot, feature, 1, **data, source=source),
            target.describe(slot, feature, 1, **data, source=source))
    for mutation in ("不足", "品質", "未解消", "未終了"):
        data = teacher_fixture.measurement(slot)
        if mutation == "不足":
            data["barrier"]["outcome"] = "不足"
        elif mutation == "品質":
            data["operation"]["quality"]["損益確定可能"] = False
        elif mutation == "未解消":
            data["operation"]["final_state"]["pending"] = {"未解消": True}
        else:
            data["operation"]["conditions"][slot["slot_id"]]["status"] = "監視"
        result = audit_module.teacher_description(slot, feature, -1, **data, source="条件")
        audit.check("未知全文:" + mutation, result, target.describe(slot, feature, -1, **data, source="条件"))
        audit.check("未知は補完しない:" + mutation, (result["row"], result["known_end_time"]), (None, None))
    data = teacher_fixture.measurement(slot)
    data["barrier"].update(slot)
    data["barrier"].update(time=int(slot["time"]), scheduled=int(slot["scheduled"]))
    audit.check("時計int/float値同値", audit_module.teacher_description(slot, feature, 1, **data, source="条件"),
        target.describe(slot, feature, 1, **data, source="条件"))
    for source_index in (3, 4):
        for side in (1, -1):
            inputs = teacher_fixture.common_inputs(2)
            inputs[source_index]["人工69_000", side]["barrier"]["outcome"] = "不足"
            audit.check("一側未知の共通pair:" + str((source_index, side)), audit_module.common_teachers(*inputs), target.prepare_common_pairs(*inputs))
    for end in (999.0, 1000.0, 1001.0):
        inputs = teacher_fixture.common_inputs()
        inputs[4]["人工69_000", 1]["barrier"]["end_time"] = end
        audit.check("同秒/将来は共通除外:" + str(end), audit_module.common_teachers(*inputs), target.prepare_common_pairs(*inputs))
    inputs = teacher_fixture.common_inputs()
    expected = target.prepare_common_pairs(*inputs)
    audit.check("両無取引pairを保持", audit_module.common_teachers(*inputs), expected)
    audit.check("両無取引の回帰0と約定旗", [(r["filled"], r["pnl5"]) for r in expected[0]["C0"]], [(False, 0.0), (False, 0.0)])
    for field, value in (("entry_time", math.inf), ("entry_price", math.inf), ("entry_line", True)):
        data = teacher_fixture.measurement(slot, True, "250")
        data["barrier"][field] = value
        audit.check("不正入口拒否:" + field, rejected(audit_module.teacher_description, slot, feature, 1, **data, source="条件"), True)


def check_models(audit_module, learner_fixture, main, selector, audit, source) -> tuple:
    """架空二木だけをfitし全node・回収・予測を独立監査へ接続する。

    引数: audit_module/learner_fixture/main/selector(ModuleType)は人工対象と純API、audit/sourceは比較補助。
    返り値: tuple[int,int]は人工fit API回数と子回帰器回数。
    """
    learner = learner_fixture.M
    inputs = {"I0": learner_fixture.training_rows(), "C0": learner_fixture.training_rows(True)}
    for row in inputs["C0"]:
        if row["features"][0] <= 0 and row["features"][25] > 0.5:
            row.update(filled=False, outcome="無取引", pnl0="0", pnl5="0", pnl10="0")
    fits, regressors = 0, 0
    learner_sha = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    for policy, rows in inputs.items():
        used, training = audit_module.canonical_rows(rows, learner_fixture.EVALUATION)
        audit.check("canonical/指紋全文:" + policy, (used, training), learner.prepare_rows(rows, learner_fixture.EVALUATION))
        identity = policy + "_人工"
        model = learner.fit(rows, learner_fixture.METADATA, policy, identity, learner_fixture.EVALUATION)
        fits += 1
        regressors += sum(x["fit_performed"] for x in model["training"]["partition"].values())
        audit_module.check_model(model, used, training, learner_fixture.METADATA, identity, learner_sha, audit)
        calibration = main.calibration_for(model)
        audit.check("全回収葉全文:" + policy, calibration, audit_module.expected_calibration(model))
        for index in range(0, len(rows), 80):
            vectors = {"1": rows[index]["features"], "-1": rows[index + 1]["features"]}
            for suffix in ("0", "1"):
                actual = selector.predict(model, calibration, vectors, learner, "E" + suffix)
                expected = audit_module.expected_prediction(model, calibration, vectors, policy[0] + suffix)
                audit.check("両側資格/最終選択全文:" + str((policy, index, suffix)), actual, expected)
        empty = {"1": [], "-1": []}
        audit.check("未準備両空予測:" + policy, selector.predict(model, calibration, empty, learner, "E0"), audit_module.expected_prediction(model, calibration, empty, policy))
        if policy == "C0":
            unknown = [n for n in model["nodes"] if n["barrier_data_absent"] and not n["data_absent"]]
            audit.check("全無取引だが空回帰ではない葉あり", bool(unknown), True)
            for node in unknown:
                audit.check("全無取引scoreNone/平均0/MSE0", (node["score"], node["recovery"]["pnl5"]["mean"], float(node["recovery_mse_decimal"])), (None, 0.0, 0.0))
            bad_model = deepcopy(model)
            bad_model["nodes"][unknown[0]["id"]]["score"] = 0.0
            probe = source.Audit()
            audit_module.check_model(bad_model, used, training, learner_fixture.METADATA, identity, learner_sha, probe)
            audit.check("未知score0混同を検出", probe.bad > 0, True)
        for mutation in ("片側", "同秒", "無取引非0"):
            bad = deepcopy(rows)
            if mutation == "片側":
                bad.pop()
            elif mutation == "同秒":
                bad[0]["end_time"] = learner_fixture.EVALUATION
            else:
                bad[0].update(filled=False, outcome="無取引", pnl5="1")
            audit.check("canonical不整合拒否:" + policy + mutation, rejected(audit_module.canonical_rows, bad, learner_fixture.EVALUATION), True)
    return fits, regressors


def check_operations(audit_module, measure, material, audit, source, oracle) -> None:
    """少数の68条件運用と69一枠prefixを独立監査へ接続する。

    引数: audit_module/measure/material(ModuleType)は監査・計測・人工工場、audit/source/oracleは固定比較補助。
    返り値: None。Engineと新計測は実装側だけに呼ぶ。
    """
    proxy = SimpleNamespace(**vars(source))
    proxy.calendar = lambda session: (0.0, 1200.0, 1300.0, [180.0])
    cases = [
        [(180, 1000, 999, 1001, True), (181, 1011, 1010, 1012, True), (182, 1012, 1011, 1013, True), (200, 1264, 1263, 1265, True)],
        [(180, 990, 989, 991, True), (181, 1011, 1010, 1012, True)],
        [(180, 1000, 999, 1001, True), (181, 990, 989, 991, True), (182, 1011, 1010, 1012, True)],
        [(180, 1000, 999, 1001, True), (481, 990, 989, 991, True)],
    ]
    for number, values in enumerate(cases):
        events, slot, condition = material.fixture(values)
        slot["feature"] = {"background_direction": 1}
        slot["policy"] = "C0"
        raw = {key: source.np.array([row[key] for row in events]) for key in ("now", "line", "last", "bid", "ask", "valid")}
        mask = raw["valid"] & source.np.isfinite(raw["bid"]) & source.np.isfinite(raw["ask"]) & (raw["bid"] > 0) & (raw["bid"] < raw["ask"])
        quotes = {key: value[mask] for key, value in raw.items()}
        tape = {"events": raw, "normal": quotes, "normal_lines": {int(line): i for i, line in enumerate(quotes["line"])}}
        expected, observed = audit_module.R68.expected_label(tape, slot, condition, 1200.0, 1300.0, source, oracle)
        bank = measure.MeasurementBank(events, slot["session"], {"start": 0.0, "force": 1200.0, "end": 1300.0})
        singleton = bank.measure(slot, condition, "C0", background_direction=1)
        full = measure.O68.replay(events, [{key: slot[key] for key in measure.O68.SLOT_FIELDS}], {slot["slot_id"]: condition}, slot["session"], "C0", {"start": 0.0, "force": 1200.0, "end": 1300.0})
        audit.check("一枠/全日共通射影:" + str(number), measure.comparison_view(singleton), measure.comparison_view(full))
        audit.check("独立先着全文:" + str(number), singleton["measurement"]["独立先着"], expected)
        for is_singleton, operation in ((False, full), (True, singleton)):
            block = {"session": slot["session"], "policy": "C0", "slots": [slot], "conditions": {slot["slot_id"]: condition}, "operation": operation}
            audit_module.check_operation(block, {slot["slot_id"]: expected}, {slot["slot_id"]: observed}, tape, proxy, audit, singleton=is_singleton)
        audit_module.check_prefix(singleton, slot, tape, proxy, audit)


def self_test() -> dict:
    """正式入力なしで新監査の実APIをつなぎ成功記録を返す。

    引数: なし。
    返り値: dictは人工成功・照合数・不一致・人工fit API数と回帰器数。
    """
    module = load(HERE / "保存検証.py", "条件入口69保存監査の人工対象")
    teachers = load(HERE / "教師の人工検査.py", "条件入口69保存監査の教師材料")
    learners = load(HERE / "学習の人工検査.py", "条件入口69保存監査の学習材料")
    main = load(HERE / "検証.py", "条件入口69保存監査の純校正対象")
    measure = load(HERE / "計測.py", "条件入口69保存監査の人工計測対象")
    material = load(HERE.parent / "条件発動前の否定/先着の人工検査.py", "条件入口69保存監査の固定68材料")
    source, oracle, _ = module.A.helpers()
    audit = source.Audit()
    check_teachers(module, teachers, audit)
    fits, regressors = check_models(module, learners, main, learners.SELECTOR, audit, source)
    check_operations(module, measure, material, audit, source, oracle)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "fit API数": fits, "人工回帰器数": regressors, "分類器fit": 0, "本物入力読取": False,
        "本物fit": 0, "市場戦略再生": False, "Engineは人工実装側のみ": True}


if __name__ == "__main__":
    result = self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result["人工成功"] else 1)
