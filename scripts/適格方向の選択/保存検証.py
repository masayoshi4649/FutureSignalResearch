"""66の保存木再用と適格方向選択・新92運用を独立に照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode, urljoin

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00066_複数手法の適格方向から優先側を選ぶ"
WORK = ROOT / "work/適格方向の選択/00066"
OLD = ROOT / "study/00065_方向に対応する現在の有効状態を先に分ける"
OLDWORK = ROOT / "work/状態と判断/00065"
COMPLETE = ROOT / "work/状態と判断/65完了記録.json"
PREFLIGHT = ROOT / "work/適格方向の選択/保存接続確認.json"
BASELINE = ROOT / "work/定時帯反応/00049/入口先着.jsonl.gz"
POLICIES, CONTROLS = ("E0", "E1"), ("U0", "U1")
BINDING = ("slot_id", "session", "scheduled", "time", "line")
PERIODS = ("学習", "条件選択", "後続検査")


def load(path: Path, name: str):
    """固定補助を固有名で読み旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。新主・新選択を期待値に呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R65 = load(ROOT / "scripts/現在状態と量価格/保存検証.py", "適格方向66の固定65監査")
A, P, R55, R56 = R65.A, R65.P, R65.R55, R65.R56
fingerprint = A.fingerprint

# ----------------------------------------
# 65の成功証明を再用し、新しい特徴計算・学習・独立追尾計測を行わない。


def qualified_sides(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """両方向の旧資格と回収条件を独立に導き選択候補を確定する。

    引数: model/calibration(dict)は旧U0保存値、vectors(dict)は同60列、policy(str)はE0/E1。
    返り値: dictは旧両側予測・各資格・適格集合・選択側。未知と同点は集合選択より優先する。
    """
    if policy not in POLICIES or model.get("policy") != "U0" or calibration["model_id"] != model["model_id"]:
        raise ValueError("政策又は旧木と回収の対応不正")
    prior = R65.predict(model, vectors)
    sides = {}
    for side in ("1", "-1"):
        leaf_id = prior["leafs"][side]
        if leaf_id is None or prior["scores"][side] is None:
            sides[side] = None
            continue
        leaf = calibration["leaves"][str(leaf_id)]
        if leaf["leaf"] != leaf_id:
            raise ValueError("回収葉ID不一致")
        support = leaf["unique_slots"] >= 60 and leaf["days"] >= 6 and leaf["sessions"] >= 10
        positive = leaf["direction_rows"] > 0 and Decimal(leaf["sum_yen"]["5"]) > 0
        if (leaf["support"], leaf["positive"]) != (support, positive):
            raise ValueError("回収支持又は十進符号に差")
        qualifications = prior["eligibility"][side]
        flags = {key: qualifications[key] for key in ("score", "leaf_support", "method_support")}
        flags.update(recovery_support=support, recovery_positive=positive)
        valid = all(flags[key] for key in ("score", "leaf_support", "method_support", "recovery_support"))
        if policy == "E1":
            valid = valid and positive
        sides[side] = {**flags, "eligible": bool(valid), "leaf": leaf_id, "mean5": leaf["mean_yen"]["5"]}
    selected = 0
    eligible = sorted((int(side) for side in ("1", "-1") if sides[side] is not None and sides[side]["eligible"]),
        key=lambda side: -prior["scores"][str(side)])
    if any(prior["scores"][side] is None for side in ("1", "-1")):
        boundary = "unknown"
    elif prior["scores"]["1"] == prior["scores"]["-1"]:
        boundary = "tie"
    elif eligible:
        boundary = "selected"
        selected = max(eligible, key=lambda side: prior["scores"][str(side)])
    else:
        boundary = "empty"
    return {"prior": prior, "sides": sides, "eligible": eligible, "side": selected, "boundary": boundary}


def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """新選択器を呼ばず互換旧予測と両方向資格の保存辞書を構成する。

    引数: model/calibration(dict)は旧U0正本、vectors(dict)は両60列、policy(str)はE0/E1。
    返り値: dictは新prediction全文。WAIT時は旧回収欄、採用時は選択葉へ結ぶ。
    """
    chosen = qualified_sides(model, calibration, vectors, policy)
    prior, directions = chosen["prior"], {}
    unprepared = vectors["1"] == vectors["-1"] == []
    for side in ("1", "-1"):
        flags = chosen["sides"][side]
        if flags is None:
            directions[side] = {"known": False, "leaf": prior["leafs"][side], "score_value": None, "score": None,
                "leaf_support": None, "method_support": None, "families": None, "recovery_support": None,
                "recovery_positive": None, "recovery_mean5": None, "eligible": False,
                "reasons": ["特徴未準備" if unprepared else "未学習葉"]}
            continue
        reasons = [text for name, text in (("score", "score下限未達"), ("leaf_support", "葉支持不足"),
            ("method_support", "複数技法不足"), ("recovery_support", "回収支持不足")) if not flags[name]]
        if policy == "E1" and not flags["recovery_positive"]:
            reasons.append("過去回収平均未知" if flags["mean5"] is None else "過去回収平均非正")
        directions[side] = {"known": True, "leaf": flags["leaf"], "score_value": prior["scores"][side],
            **{name: flags[name] for name in ("score", "leaf_support", "method_support", "recovery_support", "recovery_positive")},
            "families": prior["eligibility"][side]["families"], "recovery_mean5": flags["mean5"],
            "eligible": flags["eligible"], "reasons": reasons}
    block = "特徴未準備WAIT" if unprepared else {"unknown": "未学習枝WAIT", "tie": "同点WAIT"}.get(chosen["boundary"])
    winner = 0 if block else 1 if prior["scores"]["1"] > prior["scores"]["-1"] else -1
    reference = R65.expected_prediction(model, calibration, vectors, "U0" if policy == "E0" else "U1")
    side = chosen["side"]
    rescued = bool(side and side != winner)
    reason = block or ("両方向不適格WAIT" if not side else "適格な他方向を採用" if rescued else "採用")
    result = {"side": side, "reason": reason, "prior": deepcopy(prior),
        **{key: reference[key] for key in ("recovery_leaf", "recovery_support", "recovery_mean5")},
        "policy": policy, "reference_policy": "C0" if policy == "E0" else "R0", "original_winner_side": winner,
        "selected_side": side, "rescued": rescued, "rescue_reasons": directions[str(winner)]["reasons"] if rescued else [],
        "direction_eligibility": directions, "eligible_sides": chosen["eligible"], "ranking_block_reason": block, "reference": reference}
    if side:
        leaf = directions[str(side)]
        result.update(recovery_leaf=leaf["leaf"], recovery_support=leaf["recovery_support"], recovery_mean5=leaf["recovery_mean5"])
    return result


def selection_statistics(new: list[dict], old: list[dict]) -> dict:
    """同時計の旧純判断との参加差を識別子ごとに数える。

    引数: new/old(list[dict])は同期間の新旧slots。
    返り値: dictは同方向共通・追加・除外・反対変更・救済とDI拒否。実参加とは別。
    """
    before = {row["slot_id"]: row for row in old}
    if len(before) != len(new) or {row["slot_id"] for row in new} != set(before):
        raise ValueError("選択比較の枠集合不一致")
    pairs = [(row, before[row["slot_id"]]) for row in new]
    added = [(after, prior) for after, prior in pairs if after["side"] and not prior["side"]]
    return {"全予定枠": len(new), "特徴準備枠": sum(row["ready"] for row in new),
        "旧純採用": sum(bool(row["side"]) for row in old), "新純採用": sum(bool(row["side"]) for row in new),
        "共通同方向": sum(bool(after["side"]) and after["side"] == prior["side"] for after, prior in pairs),
        "追加純候補": len(added), "除外純候補": sum(bool(prior["side"]) and not after["side"] for after, prior in pairs),
        "反対変更": sum(bool(after["side"] and prior["side"]) and after["side"] != prior["side"] for after, prior in pairs),
        "追加時旧理由": dict(Counter(prior["reason"] for _, prior in added)),
        "予測救済": sum(bool(row["prediction"] and row["prediction"]["rescued"]) for row in new),
        "DI同値で拒否": sum(bool(row["prediction"] and row["prediction"]["side"] and not row["side"]) for row in new)}


def direction_comparison(slots: dict, period: str, source) -> dict:
    """E0とE1の同方向・逆方向・片側採用を排他的に数える。

    引数: slots(dict)は新二政策の保存slots、period(str)は期、source(ModuleType)は固定暦。
    返り値: dictは全予定枠と四分類。E1同方向subsetを仮定しない。
    """
    pair = {policy: {row["slot_id"]: row["side"] for row in slots[policy] if source.span(row["session"]) == period} for policy in POLICIES}
    if set(pair["E0"]) != set(pair["E1"]):
        raise ValueError("新二政策の枠集合不一致")
    return {"全予定枠": len(pair["E0"]),
        "両採用同方向": sum(bool(side) and side == pair["E1"][key] for key, side in pair["E0"].items()),
        "両採用逆方向": sum(bool(side and pair["E1"][key]) and side != pair["E1"][key] for key, side in pair["E0"].items()),
        "E0のみ採用": sum(bool(side) and not pair["E1"][key] for key, side in pair["E0"].items()),
        "E1のみ採用": sum(not side and bool(pair["E1"][key]) for key, side in pair["E0"].items())}


def expected_counts(features: int, decisions: int, closed: int) -> dict:
    """今回実際に行う特徴・旧純判断・同一新規完結の三照合を定義する。

    引数: features/decisions/closed(int)は実照合数。
    返り値: dictは全3項目。旧14件の再計算はせず別の旧証明検査に結ぶ。
    """
    if any(type(value) is not int for value in (features, decisions, closed)) or features != 3404 or decisions != 3404 or closed < 0:
        raise ValueError("今回保存照合数の不一致")
    return {"旧65特徴保存一致": features, "旧65純判断一致": decisions, "同一新規完結一致": closed}


def check_reference(source, audit) -> tuple:
    """65の監査成功・完了台帳と今回再用する保存正本を結ぶ。

    引数: source(ModuleType)は固定読取、audit(Audit)は照合記録。
    返り値: tupleは旧結果・旧監査・完了台帳。旧監査runを再実行しない。
    """
    previous, proof, done = [source.read(path) for path in (OLD / "結果.json", OLD / "保存物確認.json", COMPLETE)]
    audit.check("65単一市場完了", (done["試行"], done["市場実行終了"], done["本物実行回数"], done["不一致"]), (65, True, 1, 0))
    audit.check("65成功監査", (proof["試行"], proof["全件一致"], proof["不一致数"]), (65, True, 0))
    audit.check("65結果証明bind", source.sha(OLD / "結果.json"), proof["結果SHA256"])
    paths = [OLD / name for name in ("結果.json", "固定.json", "保存物確認.json", "一覧.resources.json")]
    paths += [OLDWORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    paths += [ROOT / meta["path"] for meta in previous["モデル"] + previous["回収集計"]]
    pins = {**proof["参照SHA256"], **proof["モデルSHA256"]}
    for path in paths:
        name, digest = path.relative_to(ROOT).as_posix(), source.sha(path)
        audit.check("65完了SHA:" + name, digest, done["成果物SHA256"][name])
        if path != OLD / "保存物確認.json":
            audit.check("65成功監査SHA:" + name, digest, pins[name])
    for path in (R65.MEASUREMENTS, source.MANIFEST):
        name = path.relative_to(ROOT).as_posix()
        audit.check("65検証済み入力:" + name, source.sha(path), pins[name])
    return previous, proof, done


def saved_inputs(previous: dict, proof: dict, entries: list[dict], source, audit) -> tuple:
    """65の保存3木・回収・特徴と全旧純判断を再生せず接続する。

    引数: previous/proof(dict)は65正本、entries(list[dict])は固定66場、source/auditは読取補助。
    返り値: tupleは旧blocks/1702特徴/3木/3回収/純照合数/モデルSHA。
    """
    phases = A.phases(entries, source)
    models, calibrations, pins = {}, {}, {}
    for phase in phases:
        meta = next(row for row in previous["モデル"] if row["phase"] == phase["id"] and row["policy"] == "U0")
        cm = next(row for row in previous["回収集計"] if row["phase"] == phase["id"] and row["policy"] == "U0")
        for row in (meta, cm):
            pins[row["path"]] = source.sha(ROOT / row["path"])
            audit.check("65モデル回収metadataSHA", pins[row["path"]], row["SHA256"])
            audit.check("65モデル回収proofSHA", pins[row["path"]], proof["モデルSHA256"][row["path"]])
        model, cal = source.read(ROOT / meta["path"]), source.read(ROOT / cm["path"])
        audit.check("旧保存木policy/ID", (model["policy"], model["model_id"]), ("U0", meta["id"]))
        audit.check("旧回収phase木bind", (cal["phase"], cal["base_model_path"], cal["base_model_sha256"], cal["evaluation_start"]),
            (phase["id"], meta["path"], meta["SHA256"], phase["evaluation_start"]))
        audit.check("旧教師順の回収bind", cal["old_teacher_ids_sha256"], fingerprint(model["training"]["row_ids"]))
        for leaf in cal["leaves"].values():
            audit.check("全旧回収教師strict過去", all(max(row["barrier_end_time"], row["recovery_end_time"]) < phase["evaluation_start"] for row in leaf["rows"]), True)
        models[phase["id"]], calibrations[phase["id"]] = model, cal
    blocks, prepared, matches = {}, {}, 0
    for block in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz"):
        key = block["session"], block["policy"]
        if block["policy"] not in CONTROLS or key in blocks:
            raise ValueError("65保存場候補の重複又は未知政策")
        blocks[key] = block
        model, cal = models[block["phase"]], calibrations[block["phase"]]
        for slot in block["slots"]:
            feature = slot["feature"]
            identity = slot["slot_id"]
            if identity in prepared:
                audit.check("旧U0/U1の全60特徴辞書", R65.S63.strict_equal(feature, prepared[identity]), True)
            else:
                prepared[identity] = feature
            predicted = R65.expected_prediction(model, cal, feature["vectors"], block["policy"]) if feature["ready"] else None
            side, reason = (predicted["side"], predicted["reason"]) if predicted else (0, feature["reason"])
            if side and feature["background_direction"] == 0:
                side, reason = 0, "上位DI同値の役割未確定WAIT"
            role = "待機" if not side else "順行" if side == feature["background_direction"] else "反転"
            expected = {**{key: slot[key] for key in BINDING}, "policy": block["policy"], "phase": block["phase"],
                "model_id": model["model_id"], "side": side, "role": role, "ready": feature["ready"], "reason": reason,
                "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": predicted}
            audit.check("旧65保存純判断全辞書", R65.S63.strict_equal(slot, expected), True)
            matches += 1
    evaluated = [entry["session"] for entry in entries[20:]]
    audit.check("旧92場候補集合", set(blocks), {(session, policy) for session in evaluated for policy in CONTROLS})
    audit.check("旧特徴1702・純3404", (len(prepared), matches), (1702, 3404))
    return blocks, prepared, models, calibrations, matches, pins


def check_periods(accounts: list[dict], labels: dict, result: dict, source, summary, audit) -> None:
    """四候補の先着・費用・全予定活動と役割を独立集計する。

    引数: accounts(list[dict])/labels(dict)は保存台帳、result(dict)は今回結果、各補助は固定純関数。
    返り値: None。単独測定の利益と混合参加を同一視しない。
    """
    for policy in (*CONTROLS, *POLICIES):
        selected = [row for row in accounts if row["candidate"] == policy]
        for period in PERIODS:
            entry = source.entry_summary(labels[policy], period)
            operation = summary.operation_summary(selected, period, source)
            audit.check(policy + period + ":入口", result["候補"][policy][period]["入口"], entry)
            audit.check(policy + period + ":運用", result["候補"][policy][period]["運用"], operation)
            audit.check(policy + period + ":同時適格", result["候補"][policy][period]["同時適格"], entry["70目標"] and operation["活動適格"] and operation["費用適格"])
            for role in ("順行", "反転"):
                audit.check(policy + period + role, result["役割別入口"][policy][period][role], source.entry_summary([row for row in labels[policy] if row["role"] == role], period))
            if policy in POLICIES:
                reasons = Counter(row["reason"] for account in selected if source.span(account["session"]) == period for row in account["decisions"])
                audit.check(policy + period + ":理由", result["判断理由"][policy][period], dict(reasons))
    audit.check("新二政策の採用", result["採用"], [policy for policy in POLICIES if all(result["候補"][policy][period]["同時適格"] for period in PERIODS[:2])])


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """184資源とE0/E1一代表ずつのHTTP約定・台帳を照合する。

    引数: base(str|None)はURL、resources/accounts(list[dict])は保存値、source/auditは固定補助。
    返り値: dictはAPI範囲。未指定なら未検証と明記する。
    """
    if not base:
        return {"実行": False, "理由": "--viewer-url未指定。API未検証、新92保存約定は全件照合"}
    query = {"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}
    listing, _, _ = source.fetch_json(base + "/api/resources?" + urlencode(query))
    audit.check("API184全集合", {row["id"] for row in listing["resources"]}, {row["id"] for row in resources})
    audit.check("API資源数", len(listing["resources"]), 184)
    representatives = []
    for policy in POLICIES:
        account = sorted([row for row in accounts if row["candidate"] == policy], key=lambda row: (-abs(row["ledger"]["5"]), row["session"]))[0]
        resource = next(row for row in resources if row["method_id"] == policy and row["session"] == account["session"])
        parameters = {**query, "resource": resource["id"], "interval": "5", "price": "last", "width": 1000, "height": 700}
        meta, _, _ = source.fetch_json(base + "/api/chart?" + urlencode(parameters))
        data, raw, headers = source.fetch_json(urljoin(base + "/", meta["data_url"]))
        audit.check("API本文SHA", hashlib.sha256(raw).hexdigest(), meta["data_sha256"])
        audit.check("APIヘッダSHA", headers.get("x-chart-data-sha256"), meta["data_sha256"])
        audit.check("API集計alias", data["summary"], meta["summary"])
        audit.check("API台帳5", Decimal(str(data["summary"]["realized_pnl_yen"])), Decimal(str(account["ledger"]["5"])))
        trades = list(source.json_rows(ROOT / resource["pnl_path"]))
        audit.check("API約定数", len(data["events"]), len(trades))
        for sequence, (trade, event) in enumerate(zip(trades, data["events"]), 1):
            for key in ("type", "qty", "position_id", "method_id", "price"):
                audit.check("API約定:" + key, event[key], trade[key])
            audit.check("API約定順", event["sequence"], sequence)
            audit.check("API時刻", abs(event["timestamp_ms"] - datetime.fromisoformat(trade["timestamp"]).timestamp() * 1000) <= .001, True)
        representatives.append({"候補": policy, "場": account["session"], "資源ID": resource["id"], "台帳観測5円": account["ledger"]["5"], "数値SHA256": meta["data_sha256"]})
    return {"実行": True, "全資源数": 184, "新政策代表": representatives, "代表規約": "候補別最大絶対台帳観測額。採否へ不使用"}


# ----------------------------------------
# 原tapeは新92運用の保存約定・保護・先着だけに使い、戦略を再生しない。


def run(viewer_url: str | None = None) -> dict:
    """参照木の両側資格と新92保存運用を正式に一度だけ照合する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは全差・参照SHA・Viewer範囲。既存proofは上書きしない。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    source, label_helper, summary = A.helpers()
    audit = source.Audit()
    files = [STUDY / name for name in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    files += [WORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [OLD / name for name in ("結果.json", "固定.json", "保存物確認.json", "一覧.resources.json")]
    files += [OLDWORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [Path(__file__), Path(__file__).with_name("監査人工.py"), Path(__file__).with_name("監査仕様.md"),
        PREFLIGHT, COMPLETE, R65.MEASUREMENTS, BASELINE, source.MANIFEST]
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in files}
    fixed, result = source.read(STUDY / "固定.json"), source.read(STUDY / "結果.json")
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典:" + name, source.sha(ROOT / name), digest)
        if name.startswith("scripts/適格方向の選択/"):
            before[name] = digest
    for path in (Path(__file__), COMPLETE, OLD / "保存物確認.json", BASELINE):
        name = path.relative_to(ROOT).as_posix()
        audit.check("必要固定包含:" + name, fixed["ファイルSHA256"][name], source.sha(path))
    previous, previous_proof, done = check_reference(source, audit)
    for name, digest in done["成果物SHA256"].items():
        audit.check("65完了対象不変:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("試行/固定bind", (result["試行"], result["固定SHA256"]), (66, source.sha(STUDY / "固定.json")))
    audit.check("全四候補", set(result["候補"]), {*CONTROLS, *POLICIES})
    audit.check("新fit/木/計測/運用", tuple(result[key] for key in ("新回帰器fit", "新分類器fit", "新保存木数", "参照モデル数", "新独立計測", "新運用数")), (0, 0, 0, 3, 0, 92))
    reference_keys = ("評価場", "学習専用場", "準備比較", "旧教師一致", "教師集合一致", "独立測定",
        "価格経路分布", "経路支持", "状態分布", "局面分布", "数量分布", "独立測定参照")
    for key in reference_keys:
        audit.check("65参照全辞書:" + key, result[key], previous[key])
    audit.check("旧証明14検査参照", result["旧証明検査"], previous["検査"])
    audit.check("モデル参照全metadata", result["モデル"], previous["モデル"])
    audit.check("対照モデル参照全metadata", result["対照モデル"], previous["モデル"])
    audit.check("回収参照全metadata", result["回収集計"], previous["回収集計"])
    audit.check("学習参照", result["学習参照"], {"元試行": 65, "新fit": False, "教師再生成": False, "特徴再計算": False, "モデル同一": True, "回収集計同一": True})
    audit.check("旧保存対照参照", result["対照参照"], {"候補": list(CONTROLS), "元試行": 65, "同じ評価46場": True, "市場再生": False})
    entries = source.read(source.MANIFEST)["entries"]
    phases = A.phases(entries, source)
    evaluated = [entry["session"] for entry in entries[20:]]
    audit.check("評価46順", result["評価場"], evaluated)
    audit.check("学習専用20順", result["学習専用場"], [entry["session"] for entry in entries[:20]])
    old_blocks, prepared, models, calibrations, old_decisions, model_pins = saved_inputs(previous, previous_proof, entries, source, audit)
    preflight = source.read(PREFLIGHT)
    audit.check("接続成功", (preflight["試行"], preflight["接続成功"]), (66, True))
    audit.check("接続時全特徴指紋", fingerprint(prepared), preflight["評価全特徴SHA256"])
    audit.check("接続時3木全内容", {key: fingerprint(value) for key, value in models.items()}, preflight["モデル指紋"])
    audit.check("接続時3回収全内容", {key: fingerprint(value) for key, value in calibrations.items()}, preflight["回収集計指紋"])
    audit.check("接続時三検査", preflight["検査"], expected_counts(old_decisions, old_decisions, 0))
    measurements, measurement_slots, _, _ = R56.saved_measurements(source, audit)
    baseline = {}
    for row in source.json_rows(BASELINE):
        if row["policy"] not in ("B+", "B-"):
            continue
        key = row["slot_id"], row["side"]
        if key in baseline:
            raise ValueError("49両方向先着の重複")
        baseline[key] = row
    audit.check("49 B両方向4366", len(baseline), 4366)
    for identity, feature in prepared.items():
        old = next(row for row in old_blocks[measurement_slots[identity]["session"], "U0"]["slots"] if row["slot_id"] == identity)
        audit.check("55計測と同時計", {key: old[key] for key in BINDING}, measurement_slots[identity])
        if feature["ready"]:
            for side in (1, -1):
                audit.check("当時readyの両先着存在", (identity, side) in baseline, True)
    detail = defaultdict(list)
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        detail[block["session"]].append(block)
    audit.check("新詳細46場", set(detail), set(evaluated))
    labels = {policy: [] for policy in (*CONTROLS, *POLICIES)}
    saved_slots = {policy: [] for policy in (*CONTROLS, *POLICIES)}
    for block in old_blocks.values():
        saved_slots[block["policy"]].extend(block["slots"])
    for row in source.json_rows(OLDWORK / "入口先着.jsonl.gz"):
        if row["policy"] not in CONTROLS:
            raise ValueError("旧先着の未知政策")
        labels[row["policy"]].append(row)
    sequence = list(source.json_rows(WORK / "入口先着.jsonl.gz"))
    labels_by_session = defaultdict(list)
    for row in sequence:
        if row["policy"] not in POLICIES:
            raise ValueError("新先着の未知政策")
        labels_by_session[row["session"]].append(row)
    resources = source.read(STUDY / "一覧.resources.json")["resources"]
    resource_map = {(row["session"], row["method_id"]): row for row in resources}
    audit.check("資源全集合", set(resource_map), {(session, policy) for session in evaluated for policy in (*CONTROLS, *POLICIES)})
    audit.check("184資源一意", (len(resources), len({row["id"] for row in resources})), (184, 184))
    for row in source.read(OLD / "一覧.resources.json")["resources"]:
        if row["method_id"] in CONTROLS:
            audit.check("旧92資源全属性", resource_map[row["session"], row["method_id"]], row)
            audit.check("旧Viewer固定包含", fixed["ファイルSHA256"][row["pnl_path"]], source.sha(ROOT / row["pnl_path"]))
    accounts, summaries, cache_pins, viewer_pins = [], [], {}, {}
    mixed_slots = closed_matches = 0
    for entry in entries[20:]:
        session = entry["session"]
        phase = next(item for item in phases if session in {row["session"] for row in item["evaluation"]})
        model, cal = models[phase["id"]], calibrations[phase["id"]]
        tape, cache_path, digest, input_quality = R55.load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        audit.check("65成功tapeSHA", digest, previous_proof["キャッシュSHA256"][cache_path])
        for policy in CONTROLS:
            accounts.append(P.account(old_blocks[session, policy]["operation"], source, audit))
        audit.check("新二政策順", [block["policy"] for block in detail[session]], list(POLICIES))
        for block in detail[session]:
            policy, operation = block["policy"], block["operation"]
            audit.check("新運用識別", (operation["candidate_id"], operation["session"], block["phase"]), (policy, session, phase["id"]))
            audit.check("入力品質", block["input_quality"], input_quality)
            audit.check("新予定枠の順序と全公開時計", [{key: row[key] for key in BINDING} for row in block["slots"]],
                [{key: row[key] for key in BINDING} for row in old_blocks[session, "U0"]["slots"]])
            source.check_decisions(block, tape, audit)
            source.check_orders(operation, tape, audit)
            source.check_trail(operation, tape, audit)
            for closed in operation["closed"]:
                counterpart = measurements[closed["slot_id"], closed["side"]]["operation"]["closed"]
                audit.check("同一新規独立一完結", len(counterpart), 1)
                if counterpart:
                    audit.check("同一新規完結の型値", R55.strict_close_equal(closed, counterpart[0]), True)
                closed_matches += 1
            path = ROOT / resource_map[session, policy]["pnl_path"]
            audit.check("新Viewer正規保存先", path.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            accounts.append(source.check_cash(operation, list(source.json_rows(path)), tape, audit))
            summaries.append({"場": session, "候補": policy, "期間": source.span(session), "入力品質": input_quality,
                "運用品質": operation["quality"], "運用集計": operation["metrics"]})
            old_map = {row["slot_id"]: row for row in old_blocks[session, "U0"]["slots"]}
            for slot in block["slots"]:
                mixed_slots += 1
                identity, feature = slot["slot_id"], prepared[slot["slot_id"]]
                old = old_map[identity]
                predicted = expected_prediction(model, cal, feature["vectors"], policy) if feature["ready"] else None
                side, reason = (predicted["side"], predicted["reason"]) if predicted else (0, feature["reason"])
                if side and feature["background_direction"] == 0:
                    side, reason = 0, "上位DI同値の役割未確定WAIT"
                role = "待機" if not side else "順行" if side == feature["background_direction"] else "反転"
                expected = {**{key: old[key] for key in BINDING}, "policy": policy, "phase": phase["id"], "model_id": model["model_id"],
                    "side": side, "role": role, "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"],
                    "feature": feature, "prediction": predicted}
                audit.check("旧65全60特徴の同値", R65.S63.strict_equal(slot["feature"], feature), True)
                audit.check("新slotと両側資格の全内容", R65.S63.strict_equal(slot, expected), True)
                if predicted:
                    previous_slot = next(row for row in old_blocks[session, "U0" if policy == "E0" else "U1"]["slots"] if row["slot_id"] == identity)
                    audit.check("旧policyのreference全辞書", predicted["reference"], previous_slot["prediction"])
                    if previous_slot["side"]:
                        audit.check("旧純採用方向を維持", side, previous_slot["side"])
                if side:
                    labels[policy].append({**baseline[identity, side], "policy": policy, "role": role})
                saved_slots[policy].append(slot)
        for row in labels_by_session[session]:
            _, force, _, _ = source.calendar(session)
            expected = {**{key: row[key] for key in (*BINDING, "policy", "side", "role")}, **label_helper.first_force_expected(tape, row, force, source)}
            audit.check("先着の原BBO全属性", row, expected)
        print(session + " 適格方向2運用の保存照合", flush=True)
    audit.check("新3404枠", mixed_slots, 3404)
    audit.check("今回三検査", result["検査"], expected_counts(mixed_slots, old_decisions, closed_matches))
    audit.check("先着コピーの全属性と順序", sequence, [row for policy in POLICIES for row in labels[policy]])
    audit.check("場別全辞書", result["場別"], summaries)
    check_periods(accounts, labels, result, source, summary, audit)
    for policy in CONTROLS:
        audit.check("旧候補全期間", result["候補"][policy], previous["候補"][policy])
        audit.check("旧役割全期間", result["役割別入口"][policy], previous["役割別入口"][policy])
    for policy, control in zip(POLICIES, CONTROLS):
        for period in PERIODS:
            new = [row for row in saved_slots[policy] if source.span(row["session"]) == period]
            old = [row for row in saved_slots[control] if source.span(row["session"]) == period]
            audit.check("選択差:" + policy + period, result["選択比較"][policy][period], selection_statistics(new, old))
    for period in PERIODS:
        audit.check("E0/E1逆方向を含む差:" + period, result["新候補方向差"][period], direction_comparison(saved_slots, period, source))
    audit.check("新詳細二系列", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("新詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins, **cache_pins, **viewer_pins}.items():
        audit.check("実行中不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 66, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0,
        "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples, "結果SHA256": source.sha(STUDY / "結果.json"),
        "本物fit再実行": False, "市場戦略再生": False, "新独立計測": False, "新主処理import": False, "新選択器期待値呼出": False,
        "特徴算術再計算": False, "教師再生成": False, "65証明参照": {"path": (OLD / "保存物確認.json").relative_to(ROOT).as_posix(), "SHA256": source.sha(OLD / "保存物確認.json")},
        "新運用数": 92, "新予定比較数": mixed_slots, "旧純判断比較数": old_decisions, "参照モデル数": len(models), "新保存木数": 0,
        "旧完了台帳対象数": len(done["成果物SHA256"]),
        "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api,
        "検証範囲": "65成功proof/完了台帳、保存全60辞書・3木/cal・教師参照、旧3404純判断、両側のscore/葉支持/複数技法/回収支持・正符号、未知同点優先、新3404採否と新92保存運用の原BBO/注文/現金/追尾/先着/全予定活動、Viewer184。",
        "限定": "新fit・特徴算術・教師生成・独立計測・市場戦略再生なし。E1は適格集合が狭くてもE0と逆側になり得る。純追加と実参加・先着と実回収を分け、技法・心理・未見利益の有効性を証明しない。"}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def self_test() -> dict:
    """別ファイルの独立人工だけを起動する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。実入力は読まない。
    """
    return load(Path(__file__).with_name("監査人工.py"), "適格方向保存監査の独立人工").self_test()


def main() -> None:
    """人工又はroot通知後の正式保存監査をCLIで選ぶ。

    引数: CLIの--self-test/--run、任意--viewer-url。
    返り値: None。既存proofは拒否し、不一致で終了1とする。
    """
    parser = argparse.ArgumentParser(description="66の適格方向選択と新92保存運用の独立監査")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    proof = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(1 if proof["不一致数"] else 0)


if __name__ == "__main__":
    main()
