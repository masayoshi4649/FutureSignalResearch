"""71の取得位置とraw学習・支持剪定を、独立監査APIへ人工だけで接続する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """新監査と既存の自己完結人工材料を固有名で読む。

    引数: path(Path)はコード、name(str)は固有module名。
    返り値: ModuleTypeは読込結果。本物保存モデル・教師・市場を開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rejected(function, *args) -> bool:
    """入力不整合が既知0へ補完されず拒否されたことを確認する。

    引数: function(Callable)は検査対象、args(tuple)は人工引数。
    返り値: boolはValueError又はTypeErrorによる明示拒否の有無。
    """
    try:
        function(*args)
    except (ValueError, TypeError):
        return True
    return False


def check_position(module, material, audit) -> None:
    """同時計5key・公開足・反射・気配の式と旧60射影を独立へ接続する。

    引数: module(ModuleType)は監査、material(ModuleType)は入力人工、audit(Audit)は比較器。
    返り値: None。実気配・本物判断を読まない。
    """
    slot, feature, quote = material.fixture()
    before = deepcopy((slot, feature, quote))
    actual = material.I.extend_position(slot, feature, quote)
    independent = module.extend_feature(slot, feature, quote)
    audit.check("取得位置全文", independent, actual)
    audit.check("手計算の両方向g", module.g_values(slot, feature, quote), {"1": 0.5, "-1": 1.0})
    audit.check("旧60全文射影", module.base_projection(independent), feature)
    audit.check("元辞書を変更しない", (slot, feature, quote), before)
    for amount in (0.0, 17.5):
        moved, moved_quote = deepcopy(feature), deepcopy(quote)
        upper = moved["base"]["base"]["sources"]["upper"]
        for key in ("open", "high", "low", "close"):
            upper[key] += amount
        moved["base"]["base"]["sources"]["current"]["close"] += amount
        moved_quote.update(bid=quote["bid"] + amount, ask=quote["ask"] + amount)
        audit.check("平行移動g:" + str(amount), module.g_values(slot, moved, moved_quote), {"1": 0.5, "-1": 1.0})
    mirror = deepcopy(feature)
    upper = mirror["base"]["base"]["sources"]["upper"]
    high, low = upper["high"], upper["low"]
    upper.update(open=300-upper["open"], close=300-upper["close"], high=300-low, low=300-high)
    mirror["base"]["base"]["sources"]["current"]["close"] = 190.0
    mirror_quote = {**quote, "bid": 185.0, "ask": 190.0}
    audit.check("反射で方向交換", module.g_values(slot, mirror, mirror_quote), {"1": 1.0, "-1": 0.5})
    audit.check("反射全文", module.extend_feature(slot, mirror, mirror_quote), material.I.extend_position(slot, mirror, mirror_quote))
    for offer, expected in ((120.0, 0.0), (125.0, -0.5)):
        q = {**quote, "ask": offer}
        audit.check("零と負を保持:" + str(offer), module.g_values(slot, feature, q)["1"], expected)
    equal = deepcopy(feature)
    equal["base"]["base"]["sources"]["upper"].update(confirm=slot["time"], confirm_line=slot["line"])
    audit.check("同秒同原行は可視", module.extend_feature(slot, equal, quote), material.I.extend_position(slot, equal, quote))
    for changes in ({"confirm": 901.0, "confirm_line": 11}, {"publish": False}, {"missing": 1},
            {"start": 900.0, "end": 1800.0, "confirm": 1800.0}):
        bad = deepcopy(feature)
        bad["base"]["base"]["sources"]["upper"].update(changes)
        audit.check("未来又は不完全拒否:" + repr(changes), rejected(module.g_values, slot, bad, quote), True)
    for changes in ({"line": True}, {"line": 11}, {"bid": True}, {"bid": 115.0}, {"ask": float("nan")}, {"valid": False}, {"now": 902.0}):
        audit.check("異常BBO拒否:" + repr(changes), rejected(module.g_values, slot, feature, {**quote, **changes}), True)
    absent = {"ready": False, "reason": "人工未準備", "vectors": {"1": [], "-1": []}}
    audit.check("旧未準備は復帰しない", module.extend_feature(slot, absent, None), absent)
    immediate = {(slot["slot_id"], side): {**slot, "side": side, "decision_bbo": deepcopy(quote), "将来結果": 999} for side in (1, -1)}
    audit.check("5keyと両方向気配", module.quotes_for(slot, immediate), material.I.quote_for(slot, immediate))
    for key, value in (("scheduled", 899.0), ("line", True), ("side", True)):
        broken = deepcopy(immediate)
        broken[slot["slot_id"], 1][key] = value
        audit.check("5key又は方向型拒否:" + key, rejected(module.quotes_for, slot, broken), True)
    changed = deepcopy(immediate)
    changed[slot["slot_id"], -1]["decision_bbo"]["bid"] = 109.0
    audit.check("両側異なる気配拒否", rejected(module.quotes_for, slot, changed), True)


def check_models(module, material, main, audit, audit_type, metadata60: list) -> tuple:
    """架空B/Gを二回fitし、全raw nodeと独立DP・cal・採否を接続する。

    引数: module/material/main(ModuleType)は監査・人工材料・主の純cal、auditは比較器、audit_type(type)は局所不正検査用、metadata60(list)は固定F64の正本metadata定数。
    返り値: tuple[int,int]は人工fit API数と子回帰器数。本物fitを呼ばない。
    """
    learner, fits, regressors = material.M, 0, 0
    source_sha = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    for policy, count in (("B0", 60), ("G0", 61)):
        rows = material.training_rows(count == 61)
        # ----------------------------------------
        # 一群を確定無取引0にし、回帰既知と障壁未知の違いも含める。
        for row in rows:
            if row["features"][0] <= 0 and row["features"][25] > 0.5:
                row.update(filled=False, outcome="無取引", pnl0="0", pnl5="0", pnl10="0")
        used, training = module.canonical_rows(rows, material.EVALUATION, policy)
        audit.check("canonical/六指紋:" + policy, (used, training), learner.prepare_rows(rows, material.EVALUATION, count))
        meta = module.metadata(policy)
        audit.check("固定F64正本metadata:" + policy, meta, [*deepcopy(metadata60), *([deepcopy(material.M.POSITION_META)] if count == 61 else [])])
        identity = policy + "_人工_学習"
        raw = learner.fit(rows, meta, material.EVALUATION, policy, identity)
        fits += 1
        regressors += sum(p["fit_performed"] for p in raw["training"]["partition"].values())
        module.check_raw_model(raw, used, training, meta, identity, source_sha, audit)
        digest, derived_id = "a" * 64, policy + "_人工"
        derived = learner.prune(raw, derived_id, digest)
        module.check_pruned(derived, raw, derived_id, digest, audit)
        audit.check("DP全辞書:" + policy, derived, module.expected_pruned(raw, derived_id, digest))
        cal = main.calibration_for(derived)
        audit.check("全派生葉回収:" + policy, cal, module.R69.expected_calibration(derived))
        for index in range(0, len(rows), 40):
            vectors = {"1": rows[index]["features"], "-1": rows[index + 1]["features"]}
            for model in (raw, derived):
                leaf, path, _ = module.walk(model, vectors["1"])
                audit.check("独立walk:" + str((policy, model["model_id"], index)), (leaf, path), learner.walk(model, vectors["1"]))
                audit.check("独立prior:" + str((policy, model["model_id"], index)), module.prior_prediction(model, vectors), learner.predict(model, vectors))
            for suffix in ("0", "1"):
                expected = module.expected_prediction(derived, cal, vectors, policy[0] + suffix)
                actual = material.SELECTOR.predict(derived, cal, vectors, learner, "E" + suffix)
                audit.check("両側資格と最終採否全文:" + str((policy, index, suffix)), actual, expected)
        empty = {"1": [], "-1": []}
        audit.check("両空未準備:" + policy, module.expected_prediction(derived, cal, empty, policy), material.SELECTOR.predict(derived, cal, empty, learner, "E0"))
        unknown = next(n for n in derived["nodes"] if n["barrier_data_absent"] and n["direction_rows"] > 0)
        mutated = deepcopy(derived)
        mutated["nodes"][unknown["id"]]["score"] = 0.0
        target = next(row for row in used if module.walk(derived, row["features"])[0] == unknown["id"])
        vectors = {"1": target["features"], "-1": target["features"]}
        audit.check("障壁未知のscore0補完拒否:" + policy, rejected(module.prior_prediction, mutated, vectors), True)
        wrong = deepcopy(derived)
        wrong["nodes"][3]["recovery"]["pnl5"]["sum"] = "999999"
        local = audit_type()
        module.check_pruned(wrong, raw, derived_id, digest, local)
        audit.check("元親統計改変の検出:" + policy, local.bad > 0, True)
        if count == 61:
            for value in (True, None, float("inf"), float("nan"), 1e100):
                audit.check("g非有限又は型拒否:" + repr(value), rejected(module.float32, [*rows[0]["features"][:60], value], count), True)
    return fits, regressors


def check_nested_pruning(module, material, main, audit) -> None:
    """手製の二段統合と局所統合保持を、独立DPと全採否へ接続する。

    引数: module/material/main(ModuleType)は独立監査・架空木・純cal、audit(Audit)は比較器。
    返り値: None。追加fitを行わず、統合が実際に起こる例を残す。
    """
    for policy in ("B0", "G0"):
        for case in ("nested", "local_merge"):
            source = material.projected_source(policy, case)
            before = deepcopy(source)
            identity, digest = policy + "_人工_" + case, "b" * 64
            model = material.M.prune(source, identity, digest)
            module.check_pruned(model, source, identity, digest, audit)
            audit.check("元辞書非改変:" + str((policy, case)), source, before)
            audit.check("実際に両側統合あり:" + str((policy, case)), len(model["nodes"]) < len(source["nodes"]), True)
            audit.check("固定3node保持:" + str((policy, case)), [n["feature"] for n in model["nodes"][:3]], [0, 25, 19])
            calibration = main.calibration_for(model)
            audit.check("統合親の回収葉:" + str((policy, case)), calibration, module.R69.expected_calibration(model))
            for valid in (0, 1):
                vectors = {str(side): material.P70.vector(side, valid) + ([0.0] if policy == "G0" else []) for side in (1, -1)}
                for suffix in ("0", "1"):
                    audit.check("統合後の最終選択:" + str((policy, case, valid, suffix)),
                        material.SELECTOR.predict(model, calibration, vectors, material.M, "E" + suffix),
                        module.expected_prediction(model, calibration, vectors, policy[0] + suffix))


def self_test() -> dict:
    """実入力なしで新監査の位置・全node・剪定・採否APIを検査する。

    引数: なし。
    返り値: dictは人工成功・照合数・不一致・人工fitと子回帰器数。
    """
    module = load(HERE / "保存検証.py", "取得71の独立監査人工対象")
    position = load(HERE / "入力の人工検査.py", "取得71監査の架空気配")
    models = load(HERE / "学習の人工検査.py", "取得71監査の架空教師")
    main = load(HERE / "検証.py", "取得71監査の純回収集計")
    source, _, _ = module.A.helpers()
    audit = source.Audit()
    check_position(module, position, audit)
    fits, regressors = check_models(module, models, main, audit, source.Audit, position.I.F.FEATURES)
    check_nested_pruning(module, models, main, audit)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "fit API数": fits, "人工回帰器数": regressors, "分類器fit": 0, "本物入力読取": False,
        "本物fit": 0, "市場再生": False}


if __name__ == "__main__":
    result = self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result["人工成功"] else 1)
