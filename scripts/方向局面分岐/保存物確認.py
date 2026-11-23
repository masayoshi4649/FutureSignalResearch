"""54の方向固定分岐・四群教師・保存運用を独立検算する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00054_方向と局所帯を先に分岐"
WORK = ROOT / "work/方向局面分岐/00054"
OLD = ROOT / "study/00053_局所帯の反応で先に分岐"
OLDWORK = ROOT / "work/局所帯分岐/00053"
BASEWORK = ROOT / "work/局所再開/00050"
BASESTUDY = ROOT / "study/00050_15分定時の局所再開"
FRAMES = ROOT / "work/一目基準線/00028/全指標.jsonl.gz"
LABELS = ROOT / "work/定時帯反応/00049/入口先着.jsonl.gz"
POLICIES = ("D0",)
CONTROLS = ("B0", "F0")
PERIODS = ("学習", "条件選択", "後続検査")
SOURCE = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
BINDING = ("slot_id", "session", "scheduled", "time", "line")
TARGETS = {"250": 1, "125": 0, "期限": 0}
FIXED_NODES = [{"id": 0, "feature": "F18", "index": 17, "threshold": .5},
               {"id": 1, "feature": "F01", "index": 0, "threshold": 0.},
               {"id": 2, "feature": "F01", "index": 0, "threshold": 0.}]


def load(path: Path, name: str):
    """固定純補助を固有名で読み、元の大域値を変更しない。

    引数: path(Path)はコード、name(str)は独自読込名。
    返り値: ModuleTypeはモジュール。正式では54の特徴・学習関数を呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(ROOT / "scripts/局所帯分岐/保存物確認.py", "方向局面監査_固定53")
fingerprint = A.fingerprint
walk = A.walk
predict = A.predict
finite = A.finite


# ----------------------------------------
# Zとfloat32方向の固定二段を、教師の全node所属から検算する。

def group_key(values: list) -> str:
    """変換前Zを検査し、float32化したF01で四群を決める。

    引数: values(list)は18個の有限特徴。Zは厳密な0又は1。
    返り値: strはZ0_a0等。極小正値がfloat32の0へ写ればa0となる。
    """
    converted = A.float32(values, 18)
    return f"Z{int(values[17])}_a{int(converted[0] > 0)}"


def expected_rules() -> dict:
    """54の構造以外も固定53と同じ採否資格へ結ぶ。

    引数: なし。
    返り値: dictは学習コードに依存しない規約期待値。
    """
    return {"政策深さ": {"D0": 4}, "政策特徴数": {"D0": 18}, "random_state": 51,
            "criterion": "gini", "splitter": "best", "min_samples_leaf": 60, "min_samples_split": 2,
            "class_weight": None, "ccp_alpha": 0., "max_features": None, "方向行重み": .5,
            "score下限": {"分子": 1, "分母": 3, "等号可": True}, "葉支持": {"unique枠": 60, "日": 6, "場": 10},
            "path異種family最低": 2, "path必須family候補": ["trend", "osc"], "方向差": "strict", "予測入力型": "float32",
            "未知leaf": "両方向のどちらか到達なら未学習枝WAIT。scoreを0補完しない",
            "D0固定段": {"root": "F18<=0.5 / >0.5", "次段": "float32 F01<=0 / >0", "固定node数": 3,
                "固定node空でも保持": True, "子深さ": 2, "子特徴数": 17, "F01子分岐可": True,
                "群分割前pair除外": True, "枝内pair再要求": False, "gini最適固定段ではない": True}}


def check_model(model: dict, used: list[dict], training: dict, meta: list[dict], identity: str, learner_sha: str, audit) -> None:
    """固定三nodeと四子木の全教師所属・統計・未知状態を再構築する。

    引数: model(dict)は保存木、used(list[dict])/training(dict)は独立教師、meta(list[dict])は18列、
        identity/learner_sha(str)は識別子・版、audit(Audit)は検査記録。
    返り値: None。最良閾値の全探索や再fitはせず、固定段にgini最適性を要求しない。
    """
    audit.check(identity + ":schema", (model["schema_version"], model["model_id"], model["policy"]), (1, identity, "D0"))
    audit.check(identity + ":metadata", model["feature_meta"], meta)
    audit.check(identity + ":metadata指紋", model["feature_meta_sha256"], fingerprint(meta))
    audit.check(identity + ":学習code", model["source_sha256"], learner_sha)
    audit.check(identity + ":library", model["versions"]["scikit-learn"], "1.9.1")
    audit.check(identity + ":本体引数", model["parameters"], A.classifier_parameters(4))
    audit.check(identity + ":子引数", model["subtree_parameters"], A.classifier_parameters(2))
    structure = {"kind": "fixed_root_and_direction", "fixed_nodes": FIXED_NODES, "child_depth": 2,
                 "child_features": 17, "max_depth": 4, "fixed_gini_optimized": False}
    audit.check(identity + ":構造", model["structure"], structure)
    audit.check(identity + ":全規約", model["rules"], expected_rules())
    shared = ROOT / "scripts/局所帯分岐/学習.py"
    audit.check(identity + ":旧学習純補助bind", model["shared_source_sha256"],
                {shared.relative_to(ROOT).as_posix(): hashlib.sha256(shared.read_bytes()).hexdigest()})
    nodes, paths = model["nodes"], {0: []}
    audit.check(identity + ":固定根両子", (nodes[0]["left"], nodes[0]["right"]), (1, 2))
    for index, node in enumerate(nodes):
        audit.check(identity + ":node順", node["id"], index)
        audit.check(identity + ":全depth4", len(paths[index]) <= 4, True)
        audit.check(identity + ":path", node["path"], paths[index])
        if index in (0, 1, 2):
            rule = FIXED_NODES[index]
            audit.check(identity + ":固定node" + str(index), (node["feature"], node["feature_id"], node["threshold"]),
                        (rule["index"], rule["feature"], rule["threshold"]))
            audit.check(identity + ":固定内部node保持", node["left"] >= 0 and node["right"] >= 0, True)
        if node["left"] == node["right"] == -1:
            audit.check(identity + ":葉記号", (node["feature"], node["feature_id"], node["family"], node["threshold"]), (-2, None, None, -2.))
            continue
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < 18 or not finite(node["threshold"]):
            raise ValueError("分岐特徴又は閾値不正")
        if index >= 3:
            audit.check(identity + ":子17列", feature < 17, True)
        audit.check(identity + ":分岐metadata", (node["feature_id"], node["family"]), (meta[feature]["id"], meta[feature]["family"]))
        for branch, comparison in (("left", "<="), ("right", ">")):
            child = node[branch]
            if type(child) is not int or not index < child < len(nodes) or child in paths:
                raise ValueError("子ID・重複親不正")
            paths[child] = paths[index] + [{"node": index, "feature": feature, "feature_id": meta[feature]["id"],
                "method": meta[feature]["method"], "family": meta[feature]["family"], "threshold": node["threshold"],
                "comparison": comparison, "branch": branch}]
    audit.check(identity + ":全node到達可能", set(paths), set(range(len(nodes))))
    membership = defaultdict(list)
    for row in used:
        leaf, path, visits = walk(model, row["features"])
        audit.check(identity + ":方向行path", path, nodes[leaf]["path"])
        for index in visits:
            membership[index].append(row)
    partition, offset = {}, 3
    for z in (0, 1):
        for direction in (0, 1):
            key = f"Z{z}_a{direction}"
            selected = [row for row in used if group_key(row["features"]) == key]
            root = nodes[z + 1]["right" if direction else "left"]
            descendants = [i for i, path in paths.items() if len(path) >= 2 and path[0]["branch"] == ("right" if z else "left")
                           and path[1]["branch"] == ("right" if direction else "left")]
            audit.check(identity + key + ":子offset", root, offset)
            audit.check(identity + key + ":子ID連続", sorted(descendants), list(range(offset, offset + len(descendants))))
            audit.check(identity + key + ":子depth2", all(len(paths[i]) - 2 <= 2 for i in descendants), True)
            audit.check(identity + key + ":全教師所属", membership[root], selected)
            if not selected:
                audit.check(identity + key + ":空枝一未知leaf", (len(descendants), nodes[root]["left"], nodes[root]["right"], nodes[root]["data_absent"]), (1, -1, -1, True))
            ids = [{k: row[k] for k in ("session", "slot_id", "side")} for row in selected]
            partition[key] = {"z": z, "a": direction, "policy": "D0", "direction_rows": len(selected),
                "pair_unique": len({(row["session"], row["slot_id"]) for row in selected}), "days": len({row["session"][:10] for row in selected}),
                "sessions": len({row["session"] for row in selected}), "row_ids_sha256": fingerprint(ids), "fit_performed": bool(selected),
                "root": root, "node_count": len(descendants), "fit_parameters": A.classifier_parameters(2)}
            offset += len(descendants)
    audit.check(identity + ":四群で全方向行", sum(p["direction_rows"] for p in partition.values()), len(used))
    expected_training = {**deepcopy(training), "partition": partition}
    audit.check(identity + ":全training", model["training"], expected_training)
    group_roots = {p["root"] for p in partition.values()}
    for index, node in enumerate(nodes):
        rows = membership[index]
        successes = sum(TARGETS[row["outcome"]] for row in rows)
        score = successes / len(rows) if rows else None
        expected = {"direction_rows": len(rows), "weighted_rows": len(rows) / 2, "success_weight": successes / 2,
            "total_weight": len(rows) / 2, "score": score, "impurity": 2 * score * (1 - score) if score is not None else None,
            "unique_slots": len({(row["session"], row["slot_id"]) for row in rows}), "days": len({row["session"][:10] for row in rows}),
            "sessions": len({row["session"] for row in rows}), "methods": sorted({step["method"] for step in paths[index]}),
            "families": sorted({step["family"] for step in paths[index]}), "data_absent": not bool(rows),
            "training_ids_sha256": fingerprint([{k: row[k] for k in ("session", "slot_id", "side")} for row in rows])}
        for key, value in expected.items():
            audit.check(identity + str(index) + ":" + key, node[key], value)
        audit.check(identity + ":data_absent型", type(node["data_absent"]) is bool, True)
        eligibility = A.eligibility(node, paths[index])
        audit.check(identity + ":支持旗", (node["leaf_support"], node["method_support"]), (eligibility["leaf_support"], eligibility["method_support"]))
        if index >= 3 and node["left"] != -1:
            audit.check(identity + ":通常子minleaf60", min(len(membership[node["left"]]), len(membership[node["right"]])) >= 60, True)
        if not rows and index >= 3:
            audit.check(identity + ":空は群root一葉", index in group_roots and node["left"] == node["right"] == -1, True)


# ----------------------------------------
# 旧二候補は保存参照、新一候補だけを全予定・会計・実帰属へ結ぶ。

def account(op: dict, source, audit) -> dict:
    """旧二候補の保存完結を別式の現金へ集計する。

    引数: op(dict)は保存運用、source(ModuleType)/audit(Audit)は固定純補助。
    返り値: dictは候補名を維持する会計。市場の保護判断は再生しない。
    """
    observed = {str(f): Decimal(0) for f in (0, 5, 10)}
    for position in op["closed"]:
        for fee in (0, 5, 10):
            value = source.cash_pair(position["entry_price"], position["exit_price"], position["side"], fee)
            audit.check("旧保存完結現金", Decimal(str(position["pnl" + str(fee)])), value)
            observed[str(fee)] += value
    unresolved = int(op["final_state"]["position"] is not None)
    return {"session": op["session"], "candidate": op["candidate_id"], "observed": {k: float(v) for k, v in observed.items()},
        "ledger": {str(f): float(observed[str(f)] - unresolved * (11 + f * 10)) for f in (0, 5, 10)}, "unresolved": unresolved,
        "closed": op["closed"], "decisions": op["decisions"], "caution": bool(op["quality"]["損益注意理由"])}


def check_periods(accounts: list[dict], labels: dict, result: dict, source, summary, audit) -> None:
    """旧二候補と新D0の先着・会計・活動・役割を照合する。

    引数: accounts(list[dict])/labels(dict)は会計・先着、result(dict)は結果、source/summary(ModuleType)は純補助、audit(Audit)は記録。
    返り値: None。評価対象46場だけを集計し、旧候補へ新fitを行わない。
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
                audit.check(policy + period + role, result["役割別入口"][policy][period][role], source.entry_summary([r for r in labels[policy] if r["role"] == role], period))
            if policy == "D0":
                reasons = Counter(d["reason"] for r in selected if source.span(r["session"]) == period for d in r["decisions"])
                audit.check(period + ":全理由", result["判断理由"][policy][period], dict(reasons))
    audit.check("新D0のみ採用", result["採用"], [p for p in POLICIES if all(result["候補"][p][s]["同時適格"] for s in PERIODS[:2])])


def attributed_statistics(manifests: list[dict], models: dict, bindings: dict, contexts: dict, labels: list[dict], accounts: list[dict], source) -> tuple:
    """D0の全葉と採用方向Zへ元運用の完結を別々に帰属する。

    引数: manifests/models/bindings/contextsは保存木と独立対応、labels/accounts(list[dict])は検算済み先着・会計、source(ModuleType)は集計補助。
    返り値: tuple[list[dict],list[dict]]は全葉×phase内期間と局面6行。部分群で運用は再生しない。
    """
    leaves, situations = [], []
    for manifest in manifests:
        identity, sessions = manifest["id"], set(manifest["評価場"])
        for period in PERIODS:
            if not any(source.span(s) == period for s in sessions):
                continue
            selected_accounts = [a for a in accounts if a["candidate"] == "D0" and a["session"] in sessions and source.span(a["session"]) == period]
            cautions = [a["session"] for a in selected_accounts if a["caution"]]
            for node in models[identity]["nodes"]:
                if node["left"] != -1:
                    continue
                key = (identity, node["id"])
                selected = [r for r in labels if source.span(r["session"]) == period and bindings[r["slot_id"]] == key]
                closed = [r for a in selected_accounts for r in a["closed"] if bindings[r["slot_id"]] == key]
                leaves.append({"model_id": identity, "policy": "D0", "phase": manifest["phase"], "leaf": node["id"], "period": period,
                    "入口": source.entry_summary(selected, period), "実完結": len(closed), "実観測純額5": float(sum((Decimal(str(r["pnl5"])) for r in closed), Decimal(0))),
                    "品質注意場": cautions, "品質注意の範囲": "同じモデル評価期間全体。葉への帰属ではない"})
    for period in PERIODS:
        selected_accounts = [a for a in accounts if a["candidate"] == "D0" and source.span(a["session"]) == period]
        cautions = [a["session"] for a in selected_accounts if a["caution"]]
        for z in (0, 1):
            selected = [r for r in labels if source.span(r["session"]) == period and contexts[r["slot_id"]] == z]
            closed = [r for a in selected_accounts for r in a["closed"] if contexts[r["slot_id"]] == z]
            situations.append({"policy": "D0", "period": period, "z": z, "入口": source.entry_summary(selected, period),
                "実完結": len(closed), "実観測純額5": float(sum((Decimal(str(r["pnl5"])) for r in closed), Decimal(0))),
                "品質注意場": cautions, "品質注意の範囲": "同じ候補の期間全体。局面への帰属ではない"})
    return leaves, situations


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """138資源と新D0一代表のAPI約定・台帳額を照合する。

    引数: base(str|None)はAPI、resources/accounts(list[dict])は資源と会計、source(ModuleType)/audit(Audit)は補助。
    返り値: dictは実行範囲。未指定ならAPI未検証と記録する。
    """
    if not base:
        return {"実行": False, "理由": "--viewer-url未指定。API未検証、新46保存約定は全件照合"}
    query = {"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}
    listing, _, _ = source.fetch_json(base + "/api/resources?" + urlencode(query))
    audit.check("API138全集合", {r["id"] for r in listing["resources"]}, {r["id"] for r in resources})
    audit.check("API資源一意", len(listing["resources"]), 138)
    selected = sorted([r for r in accounts if r["candidate"] == "D0"], key=lambda r: (-abs(r["ledger"]["5"]), r["session"]))[0]
    resource = next(r for r in resources if r["method_id"] == "D0" and r["session"] == selected["session"])
    parameters = {**query, "resource": resource["id"], "interval": "5", "price": "last", "width": 1000, "height": 700}
    meta, _, _ = source.fetch_json(base + "/api/chart?" + urlencode(parameters))
    data, raw, headers = source.fetch_json(urljoin(base + "/", meta["data_url"]))
    audit.check("API本文SHA", hashlib.sha256(raw).hexdigest(), meta["data_sha256"])
    audit.check("APIヘッダSHA", headers.get("x-chart-data-sha256"), meta["data_sha256"])
    audit.check("API集計alias", data["summary"], meta["summary"])
    audit.check("API台帳観測5", Decimal(str(data["summary"]["realized_pnl_yen"])), Decimal(str(selected["ledger"]["5"])))
    trades = list(source.json_rows(ROOT / resource["pnl_path"]))
    audit.check("API約定片数", len(data["events"]), len(trades))
    for sequence, (trade, event) in enumerate(zip(trades, data["events"]), 1):
        for key in ("type", "qty", "position_id", "method_id", "price"):
            audit.check("API約定" + key, event[key], trade[key])
        audit.check("API順", event["sequence"], sequence)
        audit.check("API時計", abs(event["timestamp_ms"] - datetime.fromisoformat(trade["timestamp"]).timestamp() * 1000) <= .001, True)
    return {"実行": True, "全資源数": 138, "新政策代表": [{"候補": "D0", "場": selected["session"], "資源ID": resource["id"],
        "台帳観測5円": selected["ledger"]["5"], "数値SHA256": meta["data_sha256"]}], "代表規約": "最大絶対台帳観測額。採否へ不使用"}


# ----------------------------------------
# 正式保存物の読取はrootの本物実行後に限り、一度だけ行う。

def run(viewer_url: str | None = None) -> dict:
    """新46運用・三合成木と旧二候補の同準備対照を一度だけ監査する。

    引数: viewer_url(str|None)は任意のViewer接続先。
    返り値: dictは全比較・差・指紋・保証範囲。既存証明は上書きしない。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    source, label_helper, summary = A.helpers()
    audit = source.Audit()
    paths = [STUDY / n for n in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    paths += [WORK / "定時判断と運用.jsonl.gz", WORK / "入口先着.jsonl.gz", LABELS, source.MANIFEST, FRAMES,
              BASEWORK / "定時判断と運用.jsonl.gz", BASESTUDY / "保存物確認.json",
              OLD / "結果.json", OLD / "保存物確認.json", OLD / "一覧.resources.json",
              OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz", Path(__file__),
              Path(__file__).with_name("学習.py"), ROOT / "scripts/局所帯分岐/保存物確認.py",
              ROOT / "scripts/局所帯分岐/特徴.py", ROOT / "scripts/局所帯分岐/学習.py"]
    before = {p.relative_to(ROOT).as_posix(): source.sha(p) for p in paths}
    fixed, result, old_result = source.read(STUDY / "固定.json"), source.read(STUDY / "結果.json"), source.read(OLD / "結果.json")
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典:" + name, source.sha(ROOT / name), digest)
    audit.check("監査自身の固定包含", Path(__file__).relative_to(ROOT).as_posix() in fixed["ファイルSHA256"], True)
    audit.check("試行と固定bind", (result["試行"], result["固定SHA256"]), (54, source.sha(STUDY / "固定.json")))
    audit.check("候補集合", set(result["候補"]), {*CONTROLS, *POLICIES})
    old_proof = source.read(OLD / "保存物確認.json")
    audit.check("保存53監査成功", (old_proof["全件一致"], old_proof["不一致数"]), (True, 0))
    for filename in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"):
        rel = (OLDWORK / filename).relative_to(ROOT).as_posix()
        audit.check("旧正本監査bind:" + filename, source.sha(ROOT / rel), old_proof["参照SHA256"][rel])
    entries = source.read(source.MANIFEST)["entries"]
    phase_list = A.phases(entries, source)
    evaluated = [e["session"] for e in entries[20:]]
    audit.check("評価46場順", result["評価場"], evaluated)
    audit.check("初期20場は学習専用", result["学習専用場"], [e["session"] for e in entries[:20]])
    audit.check("対照参照", result["対照参照"], {"候補": list(CONTROLS), "元試行": 53, "同じ評価46場に保存値を再集計": True, "市場再生": False})
    audit.check("旧六モデルmetadata", result["対照モデル"], old_result["モデル"])
    frames = defaultdict(list)
    for row in source.json_rows(FRAMES):
        if row["minutes"] == 3:
            frames[row["場"]].append({"session": row["場"], **{k: row[k] for k in SOURCE if k != "session"}})
    audit.check("価格SOURCE66場", set(frames), {e["session"] for e in entries})
    expected_source = {s: {"足数": len(rows), "SHA256": fingerprint(rows)} for s, rows in frames.items()}
    audit.check("全価格SOURCE指紋", result["価格SOURCE"], expected_source)
    audit.check("価格SOURCE旧53同値", result["価格SOURCE"], old_result["価格SOURCE"])
    blocks = {}
    for block in source.json_rows(BASEWORK / "定時判断と運用.jsonl.gz"):
        if block["policy"] == "P0":
            audit.check("50P0場一意", block["session"] not in blocks, True)
            blocks[block["session"]] = block
    audit.check("特徴材料66場", set(blocks), {e["session"] for e in entries})
    features, source_slots = {}, {}
    for block in blocks.values():
        audit.check("50P0全予定順", [s["scheduled"] for s in block["slots"]], source.calendar(block["session"])[3])
        for slot in block["slots"]:
            if slot["slot_id"] in source_slots:
                raise ValueError("保存slot ID重複")
            source_slots[slot["slot_id"]] = slot
            features[slot["slot_id"]] = A.expected_feature(slot, frames[block["session"]])
    audit.check("50全2442予定枠", len(source_slots), 2442)
    control_blocks, old_slot_count = {}, 0
    for block in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz"):
        key = block["session"], block["policy"]
        audit.check("旧53二候補一意", key not in control_blocks, True)
        control_blocks[key] = block
        audit.check("旧53全予定順", [s["slot_id"] for s in block["slots"]], [s["slot_id"] for s in blocks[block["session"]]["slots"]])
        for slot in block["slots"]:
            old_slot_count += 1
            audit.check("53二候補と全特徴厳密同値", slot["feature"], features[slot["slot_id"]])
            audit.check("53定時clock継承", {k: slot[k] for k in BINDING}, {k: source_slots[slot["slot_id"]][k] for k in BINDING})
    audit.check("旧二候補92集合", set(control_blocks), {(s, p) for s in evaluated for p in CONTROLS})
    audit.check("旧全3404slot特徴同値", old_slot_count, 3404)
    baseline = {}
    for row in source.json_rows(LABELS):
        if row["policy"] in ("B+", "B-"):
            key = row["slot_id"], row["side"]
            audit.check("教師方向一意", key not in baseline, True)
            baseline[key] = row
    prepared = {k: {"ready": f["ready"], "reason": f["reason"], "vectors": f["vectors"]} for k, f in features.items()}
    preparation = {}
    for period in PERIODS:
        subset = [features[s["slot_id"]] for session in evaluated if source.span(session) == period for s in blocks[session]["slots"]]
        preparation[period] = {"全予定枠": len(subset), "旧特徴準備": sum(f["base"]["ready"] for f in subset),
            "共通履歴準備": sum(f["ready"] for f in subset), "履歴追加で未準備": sum(f["base"]["ready"] and not f["ready"] for f in subset),
            "追加未準備理由": dict(Counter(f["reason"] for f in subset if f["base"]["ready"] and not f["ready"])),
            "買売Z分布": dict(Counter(str(f["history"]["contexts"]["1"]["z"]) + str(f["history"]["contexts"]["-1"]["z"]) for f in subset if f["ready"]))}
    audit.check("全準備分母", result["準備比較"], preparation)
    audit.check("準備53全dict同値", result["準備比較"], old_result["準備比較"])
    models, by_session, model_pins, teacher_matches, phase_details = {}, {}, {}, {}, []
    manifests = {m["id"]: m for m in result["モデル"]}
    audit.check("新三モデル完全順", [m["id"] for m in result["モデル"]], ["D0_" + p["id"] for p in phase_list])
    audit.check("新三モデル一意", len(manifests), 3)
    meta = A.feature_metadata()
    for phase in phase_list:
        used, training, counts = A.training_rows(phase["train"], blocks, prepared, baseline, phase["evaluation_start"], 18)
        identity = "D0_" + phase["id"]
        path = STUDY / "models" / (identity + ".json")
        model, digest = source.read(path), source.sha(path)
        model_pins[path.relative_to(ROOT).as_posix()] = digest
        expected_manifest = {"id": identity, "policy": "D0", "phase": phase["id"], "path": path.relative_to(ROOT).as_posix(), "SHA256": digest,
            "学習場": [e["session"] for e in phase["train"]], "評価場": [e["session"] for e in phase["evaluation"]],
            "特徴準備": counts, "特徴数": 18, "評価開始": phase["evaluation_start"]}
        audit.check(identity + ":manifest", manifests[identity], expected_manifest)
        check_model(model, used, training, meta, identity, source.sha(Path(__file__).with_name("学習.py")), audit)
        for name in ("Python", "NumPy", "scikit-learn"):
            audit.check(identity + ":環境" + name, model["versions"][name], fixed[name])
        teacher_matches[phase["id"]] = {}
        for policy in CONTROLS:
            old_path = OLD / "models" / (policy + "_" + phase["id"] + ".json")
            prior = source.read(old_path)
            model_pins[old_path.relative_to(ROOT).as_posix()] = source.sha(old_path)
            keys = ["row_ids_sha256", "period_sha256"] + (["input_rows_sha256", "used_rows_sha256"] if policy == "F0" else [])
            teacher_matches[phase["id"]][policy] = {k: training[k] == prior["training"][k] for k in keys}
            audit.check(identity + policy + ":同過去教師", teacher_matches[phase["id"]][policy], dict.fromkeys(keys, True))
        models[identity] = model
        for entry in phase["evaluation"]:
            by_session[entry["session"]] = identity
        phase_details.append({"phase": phase["id"], "使用pair": training["used_pairs"], "除外pair": training["excluded_pair_count"],
            "方向行数": len(used), "最終教師終了key": training["period"]["max_input_label_end_key"], "評価開始": phase["evaluation_start"],
            "群方向行数": {k: p["direction_rows"] for k, p in model["training"]["partition"].items()}})
    audit.check("旧53教師一致表", result["教師一致"], teacher_matches)
    detail = list(source.json_rows(WORK / "定時判断と運用.jsonl.gz"))
    audit.check("新D0全46場順", [(b["session"], b["policy"]) for b in detail], [(s, "D0") for s in evaluated])
    labels = {p: [] for p in (*CONTROLS, "D0")}
    for row in source.json_rows(OLDWORK / "入口先着.jsonl.gz"):
        if row["policy"] in CONTROLS:
            labels[row["policy"]].append(row)
    actual_labels = list(source.json_rows(WORK / "入口先着.jsonl.gz"))
    labels_by_session = defaultdict(list)
    for row in actual_labels:
        labels_by_session[row["session"]].append(row)
    resources = source.read(STUDY / "一覧.resources.json")["resources"]
    resource_map = {(r["session"], r["method_id"]): r for r in resources}
    audit.check("138資源全集合", set(resource_map), {(s, p) for s in evaluated for p in (*CONTROLS, "D0")})
    audit.check("138資源一意", len(resources), 138)
    audit.check("138ID一意", len({r["id"] for r in resources}), 138)
    for resource in source.read(OLD / "一覧.resources.json")["resources"]:
        if resource["method_id"] in CONTROLS and resource["session"] in evaluated:
            expected = {**resource, "title": resource["session"] + " " + resource["method_id"] + " 固定53対照"}
            audit.check("旧92Viewer保存参照", resource_map[resource["session"], resource["method_id"]], expected)
            audit.check("旧Viewer固定包含", expected["pnl_path"] in fixed["ファイルSHA256"], True)
    accounts, cache_pins, viewer_pins, bindings, contexts, summaries = [], {}, {}, {}, {}, []
    slot_count = 0
    for block in detail:
        session, op = block["session"], block["operation"]
        identity = by_session[session]
        entry = next(e for e in entries if e["session"] == session)
        tape, cache_path, digest = source.load_tape(entry, audit)
        cache_pins[cache_path] = digest
        audit.check("運用ID場", (op["session"], op["candidate_id"]), (session, "D0"))
        audit.check("保存phase", block["phase"], identity.split("_")[1])
        audit.check("品質確定旗", op["quality"]["損益確定可能"], not bool(op["quality"]["損益注意理由"]))
        audit.check("全定時順", [s["slot_id"] for s in block["slots"]], [s["slot_id"] for s in blocks[session]["slots"]])
        source.check_decisions(block, tape, audit)
        source.check_orders(op, tape, audit)
        source.check_trail(op, tape, audit)
        resource = resource_map[session, "D0"]
        path = ROOT / resource["pnl_path"]
        audit.check("新Viewer正規保存先", path.resolve(), (STUDY / "viewer" / f"D0_{session}.trades.jsonl").resolve())
        viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
        accounts.append(source.check_cash(op, list(source.json_rows(path)), tape, audit))
        for policy in CONTROLS:
            accounts.append(account(control_blocks[session, policy]["operation"], source, audit))
        summaries.append({"場": session, "候補": "D0", "期間": source.span(session), "phase": block["phase"],
            "入力品質": block["input_quality"], "運用品質": op["quality"], "運用集計": op["metrics"]})
        for slot in block["slots"]:
            slot_count += 1
            old = source_slots[slot["slot_id"]]
            feature = features[slot["slot_id"]]
            predicted = predict(models[identity], feature["vectors"]) if feature["ready"] else None
            side, reason = (predicted["side"], predicted["reason"]) if predicted else (0, feature["reason"])
            if side and feature["background_direction"] == 0:
                side, reason = 0, "上位DI同値の役割未確定WAIT"
            role = "待機" if not side else "順行" if side == feature["background_direction"] else "反転"
            expected = {**{k: old[k] for k in BINDING}, "policy": "D0", "phase": identity.split("_")[1], "model_id": identity,
                "side": side, "role": role, "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": predicted}
            audit.check("全slot属性と全方向予測", slot, expected)
            if feature["ready"] and side:
                original = baseline[slot["slot_id"], side]
                audit.check("同時計B±join", {k: original[k] for k in BINDING}, {k: slot[k] for k in BINDING})
                labels["D0"].append({**original, "policy": "D0", "role": role})
                bindings[slot["slot_id"]] = identity, predicted["leafs"][str(side)]
                contexts[slot["slot_id"]] = feature["history"]["contexts"][str(side)]["z"]
        _, force, _, _ = source.calendar(session)
        for row in labels_by_session[session]:
            expected = {**{k: row[k] for k in (*BINDING, "policy", "side", "role")}, **label_helper.first_force_expected(tape, row, force, source)}
            audit.check("原BBO先着全属性", row, expected)
        print(session + " 四群木・全先着・保存運用確認", flush=True)
    audit.check("D0全先着順と全属性", actual_labels, labels["D0"])
    audit.check("全場別表示", result["場別"], summaries)
    check_periods(accounts, labels, result, source, summary, audit)
    for policy in CONTROLS:
        audit.check("旧候補全属性同値:" + policy, result["候補"][policy], old_result["候補"][policy])
        audit.check("旧役割入口同値:" + policy, result["役割別入口"][policy], old_result["役割別入口"][policy])
    leaves, situations = attributed_statistics(result["モデル"], models, bindings, contexts, labels["D0"], accounts, source)
    audit.check("全葉期間空群", result["葉別評価"], leaves)
    audit.check("局面6行全属性", result["局面別評価"], situations)
    audit.check("局面6行", len(situations), 6)
    audit.check("D0新46運用", sum(a["candidate"] == "D0" for a in accounts), 46)
    audit.check("全予定1702枠", slot_count, 1702)
    audit.check("詳細二系列", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins}.items():
        audit.check("実行中不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 54, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0, "照合項目数": audit.count,
        "不一致数": audit.bad, "不一致": audit.examples, "本物fit再実行": False, "市場戦略再生": False,
        "主モデルimport": False, "指標bank再計算": False, "新特徴学習関数を期待値に使用": False,
        "検証範囲": "保存50/固定28から53純補助で独立18特徴、旧B0/F0全3404slot特徴と同一準備、過去教師pair/四群/全node所属・score・gini・支持・未知/全方向予測、D0新46運用・全先着・会計・追尾変化点・全予定分母・局面6行。",
        "限定": "最良greedy閾値の全探索・再fit、実時間のモデル保存順、変化しない全tick保護の再生は行わない。固定price+trend段でfamily条件が成立することを子木の追加技法選択や心理・収益の証明とはしない。",
        "評価場数": 46, "学習専用場数": 20, "新運用数": 46, "全予定比較数": slot_count,
        "先着件数": {p: len(r) for p, r in labels.items()}, "phase検算": phase_details, "全葉別評価行数": len(leaves), "全局面別評価行数": len(situations),
        "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


# ----------------------------------------
# 市場・実教師・実モデルを読まず、固定段と旧純補助の接続を人工で確かめる。

def artificial_material(rows: list[dict]) -> tuple:
    """人工方向行を保存slotと教師の接続形へ変換する。

    引数: rows(list[dict])は人工の両方向教師。
    返り値: tupleはentries/blocks/prepared/baseline。入出力ファイルは読まない。
    """
    entries, blocks, prepared, baseline = [], {}, {}, {}
    for row in rows:
        if row["session"] not in blocks:
            entries.append({"session": row["session"]})
            blocks[row["session"]] = {"slots": []}
        if row["slot_id"] not in prepared:
            blocks[row["session"]]["slots"].append({k: row[k] for k in BINDING})
            prepared[row["slot_id"]] = {"ready": True, "reason": "", "vectors": {}}
        prepared[row["slot_id"]]["vectors"][str(row["side"])] = row["features"]
        baseline[row["slot_id"], row["side"]] = row
    return entries, blocks, prepared, baseline


def self_test() -> dict:
    """人工の全四群・空Z・float32符号・未知・帰属・期限境界を検査する。

    引数: なし。人工factoryだけを読み、実データを使わない。
    返り値: dictは人工比較数・不一致とfit回数。正式監査の期待値に新学習器は使わない。
    """
    source, label_helper, _ = A.helpers()
    audit = source.Audit()
    learner = load(Path(__file__).with_name("学習.py"), "方向局面監査_人工fitのみ")
    factory = load(ROOT / "scripts/局所帯分岐/学習の人工検査.py", "方向局面監査_固定53人工材料")
    feature_factory = load(ROOT / "scripts/局所帯分岐/特徴の人工検査.py", "方向局面監査_固定53価格材料")
    audit.check("独立18列metadata接続", learner.feature_metadata(A.feature_metadata(), "D0"), A.feature_metadata())
    slot, frames = feature_factory.fixture([85, 95, 115, 105, 115])
    feature = A.expected_feature(slot, frames)
    audit.check("価格準備と両論理和", (feature["ready"], feature["history"]["contexts"]["1"]),
                (True, {"own_continuation": True, "opposite_return": True, "z": 1}))
    reflected = A.expected_feature(*feature_factory.reflect(slot, frames))
    audit.check("18列鏡像", feature["vectors"]["1"], reflected["vectors"]["-1"])
    zero = A.expected_feature(*feature_factory.fixture([110] * 5))
    audit.check("Z0はready", (zero["ready"], zero["vectors"]["1"][17]), (True, 0))
    future = feature_factory.OLD.source(25)
    future.update(publish=False, close=float("nan"))
    audit.check("未来SOURCE追加不変", A.expected_feature(slot, frames + [future]), feature)
    rows = factory.training_rows(18)
    entries, blocks, prepared, baseline = artificial_material(rows)
    rows = [{**baseline[slot["slot_id"], side], "features": prepared[slot["slot_id"]]["vectors"][str(side)]}
            for entry in entries for slot in blocks[entry["session"]]["slots"] for side in (1, -1)]
    used, training, counts = A.training_rows(entries, blocks, prepared, baseline, factory.EVALUATION, 18)
    meta, learner_sha = A.feature_metadata(), hashlib.sha256(Path(__file__).with_name("学習.py").read_bytes()).hexdigest()
    model = learner.fit(rows, meta, "D0", "人工D0", factory.EVALUATION)
    check_model(model, used, training, meta, "人工D0", learner_sha, audit)
    audit.check("400pair800行各0.5", (training["used_pairs"], training["direction_rows"], training["total_weight"]), (400, 800, 400.))
    audit.check("準備分母400", counts["特徴準備枠"], 400)
    audit.check("全四群非空", all(p["fit_performed"] for p in model["training"]["partition"].values()), True)
    for row in used:
        leaf, path, _ = walk(model, row["features"])
        audit.check("全方向JSONwalk", (leaf, path), learner.walk(model, row["features"]))
    for f in prepared.values():
        audit.check("全400両方向予測", predict(model, f["vectors"]), learner.predict(model, f["vectors"]))
    audit.check("群内片側も残す", any(p["direction_rows"] == p["pair_unique"] for p in model["training"]["partition"].values()), True)
    old_used, old_training = factory.M.prepare_rows(rows, factory.EVALUATION, 18)
    audit.check("旧53F0全教師数値指紋", (used, training), (old_used, old_training))
    future_teacher = deepcopy(baseline)
    first = next(iter(future_teacher))
    future_teacher[first]["end_time"] = factory.EVALUATION
    audit.check("評価開始同秒教師拒否", A.rejects(A.training_rows, entries, blocks, prepared, future_teacher, factory.EVALUATION, 18), True)
    absent = deepcopy(baseline)
    del absent[first]
    audit.check("片側教師拒否", A.rejects(A.training_rows, entries, blocks, prepared, absent, factory.EVALUATION, 18), True)
    insufficient = deepcopy(baseline)
    insufficient[first]["outcome"] = "不足"
    remaining, excluded, _ = A.training_rows(entries, blocks, prepared, insufficient, factory.EVALUATION, 18)
    audit.check("群分割前のpair除外", (len(remaining), excluded["used_pairs"], excluded["excluded_pair_count"]), (798, 399, 1))
    groups = [group_key(row["features"]) for row in remaining]
    audit.check("方向行四群で完全被覆", sum(Counter(groups).values()), 798)
    for value, direction in ((0., 0), (-0., 0), (1e-46, 0), (-1e-46, 0), (2 ** -149, 1), (-2 ** -149, 0)):
        vector = [0.] * 18
        vector[0], vector[17] = value, 1
        audit.check("float32符号境界", group_key(vector), f"Z1_a{direction}")
    vector = [0.] * 18
    vector[17] = math.nextafter(0., 1.)
    audit.check("変換前Z二値拒否", A.rejects(group_key, vector), True)
    audit.check("17列拒否", A.rejects(group_key, [0.] * 17), True)
    for index, value in ((0, .4), (1, .001), (2, -.001)):
        broken = deepcopy(model)
        broken["nodes"][index]["threshold"] = value
        damaged = source.Audit()
        check_model(broken, used, training, meta, "人工D0", learner_sha, damaged)
        audit.check("固定閾値変更検出", damaged.bad > 0, True)
    broken = deepcopy(model)
    broken["nodes"][0]["score"] = 0.
    damaged = source.Audit()
    check_model(broken, used, training, meta, "人工D0", learner_sha, damaged)
    audit.check("固定内部統計も検査", damaged.bad > 0, True)

    # ----------------------------------------
    # Z全体が空でもDI固定nodeを残し、その両子を未知のまま保つ。
    empty_rows = deepcopy(rows)
    for row in empty_rows:
        row["features"][17] = 0
    material = artificial_material(empty_rows)
    empty_used, empty_training, _ = A.training_rows(*material, factory.EVALUATION, 18)
    empty_model = learner.fit(empty_rows, meta, "D0", "人工空Z", factory.EVALUATION)
    check_model(empty_model, empty_used, empty_training, meta, "人工空Z", learner_sha, audit)
    empty_node = empty_model["nodes"][2]
    audit.check("空Zも固定DI内部保持", (empty_node["feature"], empty_node["data_absent"], empty_node["score"], empty_node["impurity"]), (0, True, None, None))
    for branch in ("left", "right"):
        unknown = empty_model["nodes"][empty_node[branch]]
        audit.check("空Z両未知leaf", (unknown["left"], unknown["right"], unknown["data_absent"], unknown["score"]), (-1, -1, True, None))
    vectors = {"1": deepcopy(empty_rows[0]["features"]), "-1": deepcopy(empty_rows[1]["features"])}
    vectors["-1"][17] = 1
    output = predict(empty_model, vectors)
    audit.check("未知側で両WAIT", (output["side"], output["winner_side"], output["reason"]), (0, 0, "未学習枝WAIT"))
    audit.check("既知rawscore保持", (output["scores"]["1"] is not None, output["scores"]["-1"]), (True, None))
    audit.check("未知両方向全予測", output, learner.predict(empty_model, vectors))
    leaf = output["leafs"]["-1"]
    broken = deepcopy(empty_model)
    broken["nodes"][leaf]["score"] = 0.
    audit.check("未知score0補完拒否", A.rejects(predict, broken, vectors), True)
    known_zero = deepcopy(empty_model)
    selected = predict(known_zero, {"1": vectors["1"], "-1": vectors["1"]})["leafs"]["1"]
    known_zero["nodes"][selected]["score"] = 0.
    zero_output = predict(known_zero, {"1": vectors["1"], "-1": vectors["1"]})
    audit.check("既知0と未知区別", (zero_output["scores"]["1"], zero_output["reason"]), (0., "同点WAIT"))

    # ----------------------------------------
    # 葉の単独資格と最高側選択、局面6行を明示値で検査する。
    hand = deepcopy(model)
    samples = list(prepared.values())
    sample_vectors = next(f["vectors"] for f in samples if predict(hand, f["vectors"])["leafs"]["1"] != predict(hand, f["vectors"])["leafs"]["-1"])
    sample_output = predict(hand, sample_vectors)
    buy_leaf, sell_leaf = sample_output["leafs"]["1"], sample_output["leafs"]["-1"]
    for i in (buy_leaf, sell_leaf):
        hand["nodes"][i].update(unique_slots=60, days=6, sessions=10)
    for high, low, side in ((1 / 3, .2, 1), (math.nextafter(1 / 3, -math.inf), .2, 0), (.5, .5, 0)):
        hand["nodes"][buy_leaf]["score"], hand["nodes"][sell_leaf]["score"] = high, low
        audit.check("等号下限直下同点", predict(hand, sample_vectors)["side"], side)
    hand["nodes"][buy_leaf]["score"], hand["nodes"][sell_leaf]["score"] = .8, .7
    hand["nodes"][buy_leaf]["unique_slots"] = 59
    audit.check("最高側不足でも次点救済なし", (predict(hand, sample_vectors)["side"], predict(hand, sample_vectors)["winner_side"]), (0, 1))
    for node in model["nodes"]:
        if node["left"] == -1:
            audit.check("固定price+trendで技法資格", node["method_support"], True)
    manifest = [{"id": "D0_F40", "policy": "D0", "phase": "F40", "評価場": ["2026-10-20_Day", "2026-11-04_Day"]}]
    label = {"policy": "D0", "session": "2026-10-20_Day", "slot_id": "人工帰属枠", "filled": True,
             "outcome": "250", "entry_time": 10., "entry_line": 1, "end_time": 20., "end_line": 2}
    accounts = [{"candidate": "D0", "session": "2026-10-20_Day", "caution": True,
                 "closed": [{"slot_id": "人工帰属枠", "pnl5": -122.}]}]
    leaves, situations = attributed_statistics(manifest, {"D0_F40": model}, {"人工帰属枠": ("D0_F40", buy_leaf)}, {"人工帰属枠": 1}, [label], accounts, source)
    audit.check("全葉2期間空群", len(leaves), sum(n["left"] == -1 for n in model["nodes"]) * 2)
    audit.check("局面6行", len(situations), 6)
    audit.check("元帰属集計", (sum(r["入口"]["候補"] for r in situations), sum(r["実完結"] for r in situations), sum(r["実観測純額5"] for r in situations)), (1, 1, -122.))
    audit.check("品質注意は両局面共通", [r["品質注意場"] for r in situations if r["period"] == "条件選択"], [["2026-10-20_Day"]] * 2)
    boundary, cases = label_helper.self_test(source)
    audit.check("force同秒先頭原行", (boundary.bad, len(cases)), (0, 4))
    fits = sum(p["fit_performed"] for m in (model, empty_model) for p in m["training"]["partition"].values())
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
            "人工fit数": 2, "人工学習器fit数": fits, "本物教師読取": False, "市場戦略再生": False}


def main() -> None:
    """人工又はroot本物実行後の一度の保存監査を選択する。

    引数: なし。CLIの--self-test/--run/--viewer-urlを読む。
    返り値: None。不一致時は非零終了し、正式監査証明は上書きしない。
    """
    parser = argparse.ArgumentParser(description="54の方向固定段・四群合成木・保存運用を独立検査")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    result = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps({k: result[k] for k in ("全件一致", "人工成功", "照合項目数", "不一致数", "人工fit数", "人工学習器fit数") if k in result}, ensure_ascii=False))
    if not result.get("全件一致", result.get("人工成功")):
        print(json.dumps(result["不一致"], ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
