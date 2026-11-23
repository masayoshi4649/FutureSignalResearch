"""60の旧38特徴と波の区間8列・回収分岐・新運用を独立に照合する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
from urllib.parse import urlencode, urljoin

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00060_先行進行と再試験の区間分離"
WORK = ROOT / "work/波の区間分離/00060"
OLD = ROOT / "study/00059_保持水準への深さと速度"
OLDWORK = ROOT / "work/価格経路の深さと速度/00059"
COMPLETE = ROOT / "work/価格経路の深さと速度/59完了記録.json"
MEASUREMENTS = ROOT / "work/独立追尾回収/00055/独立測定.jsonl.gz"
FRAMES = ROOT / "work/一目基準線/00028/全指標.jsonl.gz"
SLOTS50 = ROOT / "work/局所再開/00050/定時判断と運用.jsonl.gz"
POLICIES, CONTROLS = ("S0", "S1"), ("V0", "V1")
PERIODS = ("学習", "条件選択", "後続検査")
BINDING = ("slot_id", "session", "scheduled", "time", "line")
CHILD_COLUMNS = [*range(17), *range(18, 46)]



def load(path: Path, name: str):
    """固定純補助を独自名で読み、旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。新主処理を正式監査でimportしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R59 = load(ROOT / "scripts/価格経路の深さと速度/保存検証.py", "波区間監査_固定59")
R58, R56, A, P, R55 = R59.R58, R59.R56, R59.A, R59.P, R59.R55
fingerprint = A.fingerprint
path_coverage = R59.path_coverage
episode_counts = R59.episode_counts



# ----------------------------------------
# 先行区間は隣接差を累積し、r前のpは順方向走査のstrict更新で固定する。

def feature_metadata() -> list[dict]:
    """旧38列に登録前・r前後の独立定義八列を加える。

    引数: なし。
    返り値: list[dict]は全46特徴。追加は価格の区間表現で独立票ではない。
    """
    result = deepcopy(R59.feature_metadata())
    for role, start in (("T", 39), ("R", 43)):
        for offset, name in enumerate(("登録へ至る十終値差分平均対ATR", "登録へ至る十差分の符号付き効率",
                "固定pからrへの一足当たり終値進行対ATR", "rから現在への一足当たり純進行対ATR")):
            result.append({"id": f"F{start + offset:02d}", "name": role + name, "method": "P05", "family": "price", "scale": "m03"})
    return result


def source_span(rows: dict, start: int, end: int, current: dict) -> list[dict]:
    """切り詰めずに当時完全公開の隣接区間を取り出す。

    引数: rows(dict)は可視番号別SOURCE、start/end(int)は含む両端、current(dict)は現在出典。
    返り値: list[dict]は欠落のない原出典。不正・未来・非隣接は拒否する。
    """
    selected = [rows.get(index) for index in range(start, end + 1)]
    if not selected or any(row is None for row in selected):
        raise ValueError("固定区間の終値出典不足")
    for row in selected:
        if A.source_reason(row, current["session"], 3, current["end"], (current["confirm"], current["confirm_line"])):
            raise ValueError("固定区間に不正又は未公開の足")
    if any(not A.adjacent(previous, row) for previous, row in zip(selected, selected[1:])):
        raise ValueError("固定区間の非隣接")
    return selected


def segments(path: dict, current: dict, rows: dict, atr: float) -> dict:
    """隣接終値差の和と先頭極値で、登録前・r前後を独立再構成する。

    引数: path/current(dict)は固定経路と現在、rows(dict)は可視SOURCE、atr(float)は現在正ATR。
    返り値: dictは新四値と区間出典/足数/net/mask。足内順や未来極値を使わない。
    """
    if not A.finite(atr) or atr <= 0:
        raise ValueError("現在ATR不正")
    result = {"episode_id": path["episode_id"], "b": deepcopy(path["b"]), "a": None, "p": None, "r": deepcopy(path["r"]),
        "current": R58.ref(current), "registration_start": None, "registration_steps": 0, "registration_net": None,
        "registration_total_abs": None, "approach_steps": None, "approach_net": None, "since_r_steps": None, "since_r_net": None,
        "masks": {"registration": False, "approach": False, "since_r": False}, "values": [0, 0, 0, 0]}
    if path["episode_id"] is None:
        if path["b"] is not None or path["r"] is not None or path["stage"] != 0:
            raise ValueError("未ID経路の不整合")
        return result
    b, side = path["b"], path["side"]
    if b is None or path["role"] not in ("T", "R") or side not in (-1, 1):
        raise ValueError("登録済み経路の種類/実方向不足")
    registration = source_span(rows, b["index"] - 10, b["index"], current)
    if path["reference_indices"] != [row["index"] for row in registration[:-1]] or path["reference_keys"] != [[row["confirm"], row["confirm_line"]] for row in registration[:-1]] or R58.ref(registration[-1]) != b:
        raise ValueError("旧Kの登録参照十本と区間が不一致")
    observed = source_span(rows, b["index"], current["index"], current)
    if observed[-1] != current:
        raise ValueError("旧現在足と区間現在が不一致")
    net = total = Fraction(0)
    for previous, row in zip(registration, registration[1:]):
        change = Fraction(row["close"]) - Fraction(previous["close"])
        net += side * change
        total += abs(change)
    scale = Fraction(atr)
    values = [net / (10 * scale), net / total if total else Fraction(0), Fraction(0), Fraction(0)]
    result.update(registration_start=R58.ref(registration[0]), registration_steps=10,
        registration_net=float(net), registration_total_abs=float(total))
    result["masks"]["registration"] = True
    anchor = b if path["role"] == "T" else path["f"]
    result["a"] = deepcopy(anchor)
    if path["r"] is not None:
        r = path["r"]
        if anchor is None or anchor["index"] < b["index"] or anchor["index"] >= r["index"] or r["index"] > current["index"]:
            raise ValueError("a/r/現在の別足順序不正")
        if R58.ref(rows.get(anchor["index"])) != anchor or R58.ref(rows.get(r["index"])) != r:
            raise ValueError("a/rの出典不一致")
        before = source_span(rows, anchor["index"], r["index"] - 1, current)
        peak = before[0]
        for row in before[1:]:
            if side * Fraction(row["close"]) > side * Fraction(peak["close"]):
                peak = row
        approach = source_span(rows, peak["index"], r["index"], current)
        since = source_span(rows, r["index"], current["index"], current)
        approach_net = sum((side * (Fraction(row["close"]) - Fraction(previous["close"])) for previous, row in zip(approach, approach[1:])), Fraction(0))
        since_net = sum((side * (Fraction(row["close"]) - Fraction(previous["close"])) for previous, row in zip(since, since[1:])), Fraction(0))
        approach_steps, since_steps = len(approach) - 1, len(since) - 1
        values[2] = approach_net / (scale * approach_steps)
        values[3] = since_net / (scale * since_steps) if since_steps else Fraction(0)
        result.update(p=R58.ref(peak), approach_steps=approach_steps, approach_net=float(approach_net),
            since_r_steps=since_steps, since_r_net=float(since_net))
        result["masks"].update(approach=True, since_r=True)
    result["values"] = [float(value) for value in values]
    if not all(math.isfinite(value) for value in [*result["values"], *[result[k] for k in ("registration_net", "registration_total_abs", "approach_net", "since_r_net") if result[k] is not None]]):
        raise ValueError("区間値のfloat表示範囲外")
    return result


def expected_feature(old: dict, slot: dict, frames: list[dict]) -> dict:
    """旧59全辞書を保持し、独立区間8列だけを加える。

    引数: old(dict)は独立38特徴、slot(dict)は判断、frames(list[dict])はSOURCE銀行。
    返り値: dictは全46特徴。旧準備不足を新補完しない。
    """
    result = deepcopy(old)
    result.update(control_vectors38=deepcopy(old["vectors"]), segments={"1": {"T": None, "R": None}, "-1": {"T": None, "R": None}})
    if not old["ready"]:
        return result
    rows = {row["index"]: row for row in R58.visible_sources(slot, frames)}
    current = old["base"]["history"]["reaction_sources"][-1]
    for side in ("1", "-1"):
        additional = []
        for role in ("T", "R"):
            item = segments(old["paths"][side][role], current, rows, old["atr"])
            result["segments"][side][role] = item
            additional += item["values"]
        result["vectors"][side] = deepcopy(old["vectors"][side]) + additional
    return result


def float32(values: list) -> list[float]:
    """旧38を検査し、新区間8列を同じfloat32へ変換する。

    引数: values(list)は46有限特徴。
    返り値: list[float]は全46値。効率範囲/旧stageの適用外0を検査する。
    """
    if not isinstance(values, list) or len(values) != 46:
        raise ValueError("46特徴が必要")
    result = R59.float32(values[:38])
    for value in values[38:]:
        if not A.finite(value):
            raise ValueError("新区間列非有限")
        try:
            converted = struct.unpack(">f", struct.pack(">f", value))[0]
        except (OverflowError, struct.error) as exc:
            raise ValueError("新区間float32範囲外") from exc
        if not math.isfinite(converted):
            raise ValueError("新区間float32範囲外")
        result.append(converted)
    for start, stage, ready_r in ((38, 18, 2), (42, 24, 3)):
        if abs(values[start + 1]) > 1:
            raise ValueError("符号付き効率の範囲不正")
        if values[stage] == 0 and any(values[start:start + 4]):
            raise ValueError("未IDの区間値は既知0")
        if values[stage] < ready_r and any(values[start + 2:start + 4]):
            raise ValueError("r未形成の区間値は既知0")
    return result


def control_projection(feature: dict) -> dict:
    """新区間情報だけを除き、旧59全項目を復元する。

    引数: feature(dict)は46特徴。
    返り値: dictは旧59辞書。vectorsをcontrol_vectors38へ戻す。
    """
    keys = ("ready", "reason", "base", "control_vectors", "vectors", "atr", "D", "background_direction", "paths", "history", "control_vectors30", "geometry")
    result = {key: deepcopy(feature[key]) for key in keys}
    result["vectors"] = deepcopy(feature["control_vectors38"])
    return result


def prepare_features(old_slots: dict, features: dict, source, audit) -> dict:
    """固定59の38独立特徴へ当時の区間八列を追加する。

    引数: old_slots/features(dict)は検証済み予定/旧18、source(ModuleType)/audit(Audit)は純補助。
    返り値: dictは全2442の独立46辞書。新主/特徴/学習を期待値へ呼ばない。
    """
    previous = R59.prepare_features(old_slots, features, source, audit)
    frames = defaultdict(list)
    for row in source.json_rows(FRAMES):
        if row["minutes"] == 3:
            frames[row["場"]].append({"session": row["場"], **{k: row[k] for k in A.SOURCE if k != "session"}})
    prepared = {}
    for identity, old in previous.items():
        prepared[identity] = expected_feature(old, old_slots[identity], frames[old_slots[identity]["session"]])
        audit.check("旧38辞書の射影完全同値", control_projection(prepared[identity]), old)
    return prepared


def expected_rules() -> dict:
    """旧38の回帰規約を全46・子45列へ射影する。

    引数: なし。
    返り値: dictは独立学習規約。新学習を呼ばない。
    """
    rules = R59.expected_rules()
    fixed = rules.pop("V0固定段")
    fixed.update(子特徴数=45, 子特徴列index=CHILD_COLUMNS)
    text = rules.pop("V1")
    rules.update({"政策深さ": {"S0": 4}, "政策特徴数": {"S0": 46}, "S0固定段": fixed, "S1": text.replace("V0", "S0")})
    return rules


def recovery_training(rows: list[dict], evaluation_start: float) -> tuple:
    """旧38の過去pair検査を維持し、全46教師と追加指紋を別構成する。

    引数: rows(list[dict])は全46教師、evaluation_start(float)は評価開始。
    返り値: tuple[list[dict],dict]は同じ使用IDと18/30/38/46指紋。
    """
    projected = []
    for row in rows:
        float32(row["features"])
        projected.append({**row, "features": row["features"][:38]})
    previous, training = R59.recovery_training(projected, evaluation_start)
    ids = {(row["session"], row["slot_id"], row["side"]) for row in previous}
    canonical = []
    for original in rows:
        row = {key: deepcopy(original[key]) for key in A.TEACHER_FIELDS}
        row["features"] = [float(value) for value in row["features"]]
        row.update(entry_time=original.get("entry_time"), entry_line=original.get("entry_line"), recovery_end_time=original.get("recovery_end_time"))
        row.update({f"pnl{f}": R56.decimal_text(Decimal(str(original[f"pnl{f}"]))) if original.get(f"pnl{f}") is not None else None for f in (0, 5, 10)})
        canonical.append(row)
    used = [row for row in canonical if (row["session"], row["slot_id"], row["side"]) in ids]
    keys = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "target_rows_sha256", "period_sha256", "used_barrier_rows_sha256")
    training["base38_fingerprints"] = {key: training[key] for key in keys}
    training.update(input_rows_sha256=fingerprint(canonical), used_rows_sha256=fingerprint(used),
        used_barrier_rows_sha256=fingerprint([{key: row[key] for key in (*A.TEACHER_FIELDS, "entry_time", "entry_line")} for row in used]),
        feature_missing_handling="旧38準備の同一pair。未登録又は未rの区間値は既知0、追加除外なし")
    return used, training


def segment_distribution(used: list[dict], prepared: dict) -> dict:
    """使用方向行を固定四群へ分け、未rを含めて新区間分布を数える。

    引数: used(list[dict])は同じ使用教師、prepared(dict)は独立特徴。
    返り値: dictは全方向行/形成/r/maskと全八列。支持gateは変えない。
    """
    groups = {}
    for z in (0, 1):
        for direction in (0, 1):
            selected = [row for row in used if int(float32(row["features"])[17]) == z and int(float32(row["features"])[0] > 0) == direction]
            result = {"方向行": len(selected)}
            for role, start in (("T", 38), ("R", 42)):
                paths = [prepared[row["slot_id"]]["paths"][str(row["side"])][role] for row in selected]
                items = [prepared[row["slot_id"]]["segments"][str(row["side"])][role] for row in selected]
                columns = {}
                for index in range(start, start + 4):
                    values = [row["features"][index] for row in selected]
                    columns[f"F{index + 1:02d}"] = {"数値数": len(values), "異なる値": len(set(values)), "最小": min(values) if values else None,
                        "最大": max(values) if values else None, "ゼロ": sum(value == 0 for value in values)}
                result[role] = {"形成あり": sum(path["episode_id"] is not None for path in paths), "形成なし": sum(path["episode_id"] is None for path in paths),
                    "取消あり": sum(path["cancel"] is not None for path in paths), "rあり": sum(path["r"] is not None for path in paths),
                    "rなし": sum(path["r"] is None for path in paths), "r当足": sum(path["r"] is not None and item["since_r_steps"] == 0 for path, item in zip(paths, items)),
                    "形成ID数": len({path["episode_id"] for path in paths if path["episode_id"] is not None}), "列": columns}
            groups[f"Z{z}_a{direction}"] = result
    return groups




def walk(model: dict, values: list) -> tuple:
    """全46列の番号で保存木を独立に走査する。

    引数: model(dict)は保存木、values(list)は46特徴。
    返り値: tupleは葉/path/全所属node。主walkを呼ばない。
    """
    values, index, path, visits = float32(values), 0, [], []
    while True:
        if type(index) is not int or not 0 <= index < len(model["nodes"]) or index in visits:
            raise ValueError("保存木の循環又は範囲外")
        node = model["nodes"][index]
        if node["id"] != index:
            raise ValueError("node ID不整合")
        visits.append(index)
        if node["left"] == node["right"] == -1:
            return index, path, visits
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < 46 or not A.finite(node["threshold"]):
            raise ValueError("分岐値不正")
        branch = "left" if values[feature] <= node["threshold"] else "right"
        meta = model["feature_meta"][feature]
        path.append({"node": index, "feature": feature, "feature_id": meta["id"], "method": meta["method"], "family": meta["family"],
            "threshold": node["threshold"], "comparison": "<=" if branch == "left" else ">", "branch": branch})
        index = node[branch]


def check_reused_proof(source, audit) -> tuple:
    """59完了/監査と55測定の版連鎖を検査する。

    引数: source(ModuleType)は固定読取、audit(Audit)は照合記録。
    返り値: tupleは旧59結果/監査/完了。旧本物計測を再生しない。
    """
    R59.check_reused_proof(source, audit)
    previous, proof, done = source.read(OLD / "結果.json"), source.read(OLD / "保存物確認.json"), source.read(COMPLETE)
    audit.check("59完了単一実行", (done["試行"], done["市場実行終了"], done["本物実行回数"]), (59, True, 1))
    audit.check("59保存監査成功", (proof["全件一致"], proof["不一致数"]), (True, 0))
    audit.check("59結果の監査bind", source.sha(OLD / "結果.json"), proof["結果SHA256"])
    paths = [OLD / name for name in ("結果.json", "固定.json", "保存物確認.json", "一覧.resources.json")]
    paths += [OLDWORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    paths += [ROOT / m["path"] for m in previous["モデル"] + previous["回収集計"]]
    for path in paths:
        name, digest = path.relative_to(ROOT).as_posix(), source.sha(path)
        audit.check("59完了SHA:" + name, digest, done["成果物SHA256"][name])
        if path != OLD / "保存物確認.json":
            audit.check("59成功監査SHA:" + name, digest, {**proof["参照SHA256"], **proof["モデルSHA256"]}[name])
    name = MEASUREMENTS.relative_to(ROOT).as_posix()
    audit.check("55検証済み測定の59bind", source.sha(MEASUREMENTS), proof["参照SHA256"][name])
    return previous, proof, done


def check_model(model: dict, used: list[dict], training: dict, meta: list[dict], identity: str, learner_sha: str, audit) -> None:
    """新回帰木の全所属・4群・先着率と回収統計を独立再構成する。

    引数: model(dict)は保存木、used/trainingは独立教師、meta(list[dict])は46列、
        identity/learner_sha(str)はID/版、audit(Audit)は記録。
    返り値: None。最良閾値の探索や別fitはせず、固定段の最適性を要求しない。
    """
    audit.check(identity + ":schema", (model["schema_version"], model["model_id"], model["policy"]), (1, identity, "S0"))
    audit.check(identity + ":metadata", model["feature_meta"], meta)
    audit.check(identity + ":metadata指紋", model["feature_meta_sha256"], fingerprint(meta))
    audit.check(identity + ":学習code", model["source_sha256"], learner_sha)
    audit.check(identity + ":library", model["versions"]["scikit-learn"], "1.9.1")
    audit.check(identity + ":本体引数", model["parameters"], R56.regressor_parameters(4))
    audit.check(identity + ":子引数", model["subtree_parameters"], R56.regressor_parameters(2))
    audit.check(identity + ":構造", model["structure"], {"kind": "fixed_root_and_direction", "fixed_nodes": P.FIXED_NODES,
        "child_depth": 2, "child_features": 45, "child_feature_indices": CHILD_COLUMNS, "feature_count": 46, "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": "DecisionTreeRegressor", "target": "pnl5"})
    audit.check(identity + ":規約", model["rules"], expected_rules())
    shared = [ROOT / "scripts/方向局面分岐/学習.py", ROOT / "scripts/局所帯分岐/学習.py", ROOT / "scripts/回収目的分岐/学習.py", ROOT / "scripts/価格経路の深さと速度/学習.py"]
    audit.check(identity + ":旧純補助bind", model["shared_source_sha256"], {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in shared})
    nodes, paths = model["nodes"], {0: []}
    audit.check(identity + ":固定根両子", (nodes[0]["left"], nodes[0]["right"]), (1, 2))
    for index, node in enumerate(nodes):
        if index not in paths:
            raise ValueError("到達不能node")
        audit.check(identity + ":node順", node["id"], index)
        audit.check(identity + ":depth4", len(paths[index]) <= 4, True)
        audit.check(identity + ":path", node["path"], paths[index])
        if index < 3:
            fixed = P.FIXED_NODES[index]
            audit.check(identity + ":固定node", (node["feature"], node["feature_id"], node["threshold"]), (fixed["index"], fixed["feature"], fixed["threshold"]))
            audit.check(identity + ":固定内部保持", node["left"] >= 0 and node["right"] >= 0, True)
        if node["left"] == node["right"] == -1:
            audit.check(identity + ":葉記号", (node["feature"], node["feature_id"], node["family"], node["threshold"]), (-2, None, None, -2.))
            continue
        feature = node["feature"]
        if type(feature) is not int or not 0 <= feature < 46 or not A.finite(node["threshold"]):
            raise ValueError("分岐値不正")
        if index >= 3:
            audit.check(identity + ":子45列", feature in CHILD_COLUMNS, True)
        audit.check(identity + ":分岐metadata", (node["feature_id"], node["family"]), (meta[feature]["id"], meta[feature]["family"]))
        for branch, comparison in (("left", "<="), ("right", ">")):
            child = node[branch]
            if type(child) is not int or not index < child < len(nodes) or child in paths:
                raise ValueError("子ID又は重複親不正")
            paths[child] = paths[index] + [{"node": index, "feature": feature, "feature_id": meta[feature]["id"], "method": meta[feature]["method"],
                "family": meta[feature]["family"], "threshold": node["threshold"], "comparison": comparison, "branch": branch}]
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
            selected = [row for row in used if P.group_key(row["features"][:18]) == key]
            root = nodes[z + 1]["right" if direction else "left"]
            descendants = [i for i, path in paths.items() if len(path) >= 2 and path[0]["branch"] == ("right" if z else "left") and path[1]["branch"] == ("right" if direction else "left")]
            audit.check(identity + key + ":子offset", root, offset)
            audit.check(identity + key + ":連続ID", sorted(descendants), list(range(offset, offset + len(descendants))))
            audit.check(identity + key + ":子depth2", all(len(paths[i]) - 2 <= 2 for i in descendants), True)
            audit.check(identity + key + ":所属", membership[root], selected)
            if not selected:
                audit.check(identity + key + ":空群一未知leaf", (len(descendants), nodes[root]["left"], nodes[root]["right"], nodes[root]["data_absent"]), (1, -1, -1, True))
            ids = [{k: r[k] for k in ("session", "slot_id", "side")} for r in selected]
            partition[key] = {"z": z, "a": direction, "policy": "S0", "direction_rows": len(selected), "pair_unique": len({(r["session"], r["slot_id"]) for r in selected}),
                "days": len({r["session"][:10] for r in selected}), "sessions": len({r["session"] for r in selected}), "row_ids_sha256": fingerprint(ids),
                "fit_performed": bool(selected), "root": root, "node_count": len(descendants), "fit_parameters": R56.regressor_parameters(2)}
            offset += len(descendants)
    audit.check(identity + ":四群全方向", sum(p["direction_rows"] for p in partition.values()), len(used))
    audit.check(identity + ":全training", model["training"], {**deepcopy(training), "partition": partition})
    roots = {p["root"] for p in partition.values()}
    for index, node in enumerate(nodes):
        rows = membership[index]
        successes = sum(A.TARGETS[r["outcome"]] for r in rows)
        score = successes / len(rows) if rows else None
        expected = {"direction_rows": len(rows), "weighted_rows": len(rows) / 2, "success_weight": successes / 2, "total_weight": len(rows) / 2,
            "score": score, "barrier_gini": 2 * score * (1 - score) if score is not None else None, "impurity_kind": "squared_error",
            "unique_slots": len({(r["session"], r["slot_id"]) for r in rows}), "days": len({r["session"][:10] for r in rows}), "sessions": len({r["session"] for r in rows}),
            "methods": sorted({p["method"] for p in paths[index]}), "families": sorted({p["family"] for p in paths[index]}), "data_absent": not bool(rows),
            "training_ids_sha256": fingerprint([{k: r[k] for k in ("session", "slot_id", "side")} for r in rows])}
        statistics = R56.decimal_statistics(rows)
        second = statistics.pop("second_moment")
        for key in ("regression_value", "impurity"):
            value = statistics.pop(key)
            if index < 3:
                audit.check(identity + str(index) + ":固定段" + key, node[key], value)
            else:
                audit.check(identity + str(index) + ":生回帰器" + key, R56.numeric_match(node[key], value, "mean" if key == "regression_value" else "mse", second), True)
        for key, value in {**expected, **statistics}.items():
            audit.check(identity + str(index) + ":" + key, node[key], value)
        audit.check(identity + ":data_absent型", type(node["data_absent"]) is bool, True)
        eligibility = A.eligibility(node, paths[index])
        audit.check(identity + ":支持旗", (node["leaf_support"], node["method_support"]), (eligibility["leaf_support"], eligibility["method_support"]))
        if index >= 3 and node["left"] != -1:
            audit.check(identity + ":通常子minleaf60", min(len(membership[node["left"]]), len(membership[node["right"]])) >= 60, True)
        if not rows and index >= 3:
            audit.check(identity + ":空は群root一葉", index in roots and node["left"] == node["right"] == -1, True)


def predict(model: dict, vectors: dict) -> dict:
    """保存木の両方向を独立採点し、未知枝では既知側への救済も行わない。

    引数: model(dict)は検算済みS0木、vectors(dict)は46列×両方向。
    返り値: dictは全予測。未知側だけscore/eligibilityをNoneとしraw既知値を保持する。
    """
    if not isinstance(vectors, dict) or set(vectors) != {"1", "-1"}:
        raise ValueError("両方向特徴が必要")
    if vectors["1"] == vectors["-1"] == []:
        return {"scores": {side: None for side in ("1", "-1")}, "leafs": {side: None for side in ("1", "-1")},
                "side": 0, "winner_side": 0, "reason": "特徴未準備WAIT", "eligibility": {side: None for side in ("1", "-1")}}
    scores, leafs, qualifications = {}, {}, {}
    for side in ("1", "-1"):
        leaf, path, _ = walk(model, vectors[side])
        node = model["nodes"][leaf]
        if node["path"] != path:
            raise ValueError("保存pathとwalk不一致")
        absent = node.get("data_absent") is True
        if absent and (node["score"] is not None or node["direction_rows"] != 0):
            raise ValueError("未知枝のscore0補完又は行数不整合")
        if not absent and (not A.finite(node["score"]) or not 0 <= node["score"] <= 1):
            raise ValueError("既知枝のscore不正")
        scores[side], leafs[side] = node["score"], leaf
        qualifications[side] = None if absent else A.eligibility(node, path)
    result = {"scores": scores, "leafs": leafs, "side": 0, "winner_side": 0, "reason": "同点WAIT", "eligibility": qualifications}
    if any(value is None for value in scores.values()):
        result["reason"] = "未学習枝WAIT"
        return result
    if scores["1"] != scores["-1"]:
        winner = "1" if scores["1"] > scores["-1"] else "-1"
        failures = [label for key, label in (("score", "最高側score下限未達"), ("leaf_support", "最高側葉支持不足"),
                    ("method_support", "最高側複数技法不足")) if not qualifications[winner][key]]
        result.update(winner_side=int(winner), side=0 if failures else int(winner), reason="/".join(failures) if failures else "採用")
    return result


def expected_calibration(model: dict, measurements: dict, evaluation_start: float) -> dict:
    """新S0の使用教師へ確定回収pairを結び、全葉を独立集計する。

    引数: model(dict)は新S0木、measurements(dict)は枠/side→測定、evaluation_start(float)は後続開始。
    返り値: dictは全葉の支持・十進純額・平均・採否符号・教師指紋。新fitをしない。
    """
    identities = model["training"]["row_ids"]
    pairs = {}
    for identity in identities:
        key = identity["slot_id"], identity["side"]
        row = measurements[key]
        if row["session"] != identity["session"] or row["ready"] is not True:
            raise ValueError("旧教師の準備又は場が不一致")
        barrier = row["barrier"]
        if barrier is None or barrier["outcome"] not in ("250", "125", "期限"):
            raise ValueError("旧使用教師の障壁結果が未知")
        if not A.finite(barrier["end_time"]) or not A.finite(row["recovery_end_time"]) or max(barrier["end_time"], row["recovery_end_time"]) >= evaluation_start:
            raise ValueError("障壁又は回収が評価開始よりstrict前ではない")
        pair = pairs.setdefault(identity["slot_id"], {})
        if identity["side"] in pair:
            raise ValueError("過去教師の重複")
        pair[identity["side"]] = row
    if any(set(pair) != {-1, 1} for pair in pairs.values()):
        raise ValueError("過去教師の片側抜け")
    excluded = [{"slot_id": key, "states": {str(s): pair[s]["status"] for s in (1, -1)}}
                for key, pair in pairs.items() if any(pair[s]["status"] != "確定完結" for s in (1, -1))]
    blocked = {row["slot_id"] for row in excluded}
    leaf_rows = {node["id"]: [] for node in model["nodes"] if node["left"] == -1}
    used = []
    for identity in identities:
        if identity["slot_id"] in blocked:
            continue
        row = measurements[identity["slot_id"], identity["side"]]
        if len(row["operation"]["closed"]) != 1:
            raise ValueError("確定回収は単独一完結が必要")
        leaf, _, _ = walk(model, row["features"])
        closed = row["operation"]["closed"][0]
        value = {**identity, "leaf": leaf, "recovery_end_time": row["recovery_end_time"], "barrier_end_time": row["barrier"]["end_time"],
                 **{f"pnl{fee}": closed[f"pnl{fee}"] for fee in (0, 5, 10)}}
        leaf_rows[leaf].append(value)
        used.append(value)
    leaves = {}
    for leaf, selected in leaf_rows.items():
        sums = {str(f): sum((Decimal(str(r[f"pnl{f}"])) for r in selected), Decimal(0)) for f in (0, 5, 10)}
        unique, days, sessions = len({r["slot_id"] for r in selected}), len({r["session"][:10] for r in selected}), len({r["session"] for r in selected})
        leaves[str(leaf)] = {"leaf": leaf, "direction_rows": len(selected), "unique_slots": unique, "days": days, "sessions": sessions,
            "sum_yen": {f: str(v) for f, v in sums.items()}, "mean_yen": {f: float(v / len(selected)) if selected else None for f, v in sums.items()},
            "support": unique >= 60 and days >= 6 and sessions >= 10, "positive": bool(selected) and sums["5"] > 0, "rows": selected,
            "max_teacher_end": max((max(r["barrier_end_time"], r["recovery_end_time"]) for r in selected), default=None)}
    return {"model_id": model["model_id"], "evaluation_start": evaluation_start, "old_teacher_direction_rows": len(identities),
        "old_teacher_ids_sha256": fingerprint(identities), "input_pairs": len(pairs), "used_pairs": len(pairs) - len(excluded),
        "excluded_pairs": excluded, "used_direction_rows": len(used), "weight_per_direction": .5, "used_rows_sha256": fingerprint(used),
        "leaves": leaves, "classifier_fit_count": 0,
        "meaning": "旧木の全過去教師と回収確定pairの共通部分による葉内記述。未来確率の校正ではない"}


def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """新回帰木の先着最高側へ支持と回収正額だけを追加する。

    引数: model/calibration(dict)は過去木・過去葉、vectors(dict)は当時特徴、policy(str)はS0/S1。
    返り値: dictは旧55同型の全予測。回帰平均で順位を変えず次点へ救済しない。
    """
    if policy not in POLICIES or calibration["model_id"] != model["model_id"]:
        raise ValueError("候補又は回収木の対応不正")
    prior = predict(model, vectors)
    side, reason, leaf = prior["side"], prior["reason"], None
    if side:
        leaf = calibration["leaves"][str(prior["leafs"][str(side)])]
        if not leaf["support"]:
            side, reason = 0, "回収支持不足WAIT"
        elif policy == "S1" and not leaf["positive"]:
            side, reason = 0, "過去回収平均非正WAIT"
    return {"side": side, "reason": reason, "prior": prior, "recovery_leaf": leaf["leaf"] if leaf else None,
            "recovery_support": leaf["support"] if leaf else None, "recovery_mean5": leaf["mean_yen"]["5"] if leaf else None}


def check_periods(accounts: list[dict], labels: dict, result: dict, source, summary, audit) -> None:
    """旧二対照と新二候補の先着・費用・活動を別集計する。

    引数: accounts/labelsは会計と先着、result(dict)は保存結果、source/summary(ModuleType)/audit(Audit)は純補助。
    返り値: None。単独測定の重複利益や分母1を活動へ流用しない。
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
            if policy in POLICIES:
                reasons = Counter(d["reason"] for row in selected if source.span(row["session"]) == period for d in row["decisions"])
                audit.check(policy + period + ":判断理由", result["判断理由"][policy][period], dict(reasons))
    audit.check("新二候補だけの採用", result["採用"], [p for p in POLICIES if all(result["候補"][p][s]["同時適格"] for s in PERIODS[:2])])


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """184資源と新二候補一代表のAPI約定・台帳を照合する。

    引数: base(str|None)はAPI、resources/accounts(list[dict])は保存値、source(ModuleType)/audit(Audit)は純補助。
    返り値: dictはAPI実行範囲。未指定なら未検証を明記する。
    """
    if not base:
        return {"実行": False, "理由": "--viewer-url未指定。API未検証、新92保存約定は全件照合"}
    query = {"catalog_path": (STUDY / "一覧.resources.json").relative_to(ROOT).as_posix()}
    listing, _, _ = source.fetch_json(base + "/api/resources?" + urlencode(query))
    audit.check("API184全集合", {r["id"] for r in listing["resources"]}, {r["id"] for r in resources})
    audit.check("API資源数", len(listing["resources"]), 184)
    representatives = []
    for policy in POLICIES:
        account = sorted([a for a in accounts if a["candidate"] == policy], key=lambda a: (-abs(a["ledger"]["5"]), a["session"]))[0]
        resource = next(r for r in resources if r["method_id"] == policy and r["session"] == account["session"])
        parameters = {**query, "resource": resource["id"], "interval": "5", "price": "last", "width": 1000, "height": 700}
        meta, _, _ = source.fetch_json(base + "/api/chart?" + urlencode(parameters))
        data, raw, headers = source.fetch_json(urljoin(base + "/", meta["data_url"]))
        audit.check("API本文SHA", hashlib.sha256(raw).hexdigest(), meta["data_sha256"])
        audit.check("APIヘッダSHA", headers.get("x-chart-data-sha256"), meta["data_sha256"])
        audit.check("API集計alias", data["summary"], meta["summary"])
        audit.check("API台帳純額5", Decimal(str(data["summary"]["realized_pnl_yen"])), Decimal(str(account["ledger"]["5"])))
        trades = list(source.json_rows(ROOT / resource["pnl_path"]))
        audit.check("API約定片数", len(data["events"]), len(trades))
        for sequence, (trade, event) in enumerate(zip(trades, data["events"]), 1):
            for key in ("type", "qty", "position_id", "method_id", "price"):
                audit.check("API約定" + key, event[key], trade[key])
            audit.check("API順", event["sequence"], sequence)
            audit.check("API時刻", abs(event["timestamp_ms"] - datetime.fromisoformat(trade["timestamp"]).timestamp() * 1000) <= .001, True)
        representatives.append({"候補": policy, "場": account["session"], "資源ID": resource["id"], "台帳観測5円": account["ledger"]["5"], "数値SHA256": meta["data_sha256"]})
    return {"実行": True, "全資源数": 184, "新政策代表": representatives, "代表規約": "候補別最大絶対台帳観測額。採否へ不使用"}


def episode_support(model: dict, used: list[dict], prepared: dict) -> dict:
    """全教師を独立walkし、各葉のT/R反復統計を再構成する。

    引数: model(dict)は保存木、used(list[dict])は独立教師、prepared(dict)は当時経路。
    返り値: dictは全葉の方向行と形成ID。支持gateや重みは変更しない。
    """
    selected = {node["id"]: [] for node in model["nodes"] if node["left"] == -1}
    for row in used:
        feature, side = prepared[row["slot_id"]], str(row["side"])
        leaf, _, _ = walk(model, feature["vectors"][side])
        selected[leaf].append(feature["paths"][side])
    return {str(leaf): {"方向行": len(paths), **{role: episode_counts([path[role] for path in paths]) for role in ("T", "R")}}
        for leaf, paths in selected.items()}


def run(viewer_url: str | None = None) -> dict:
    """保存された新木と92運用だけを、再fit・再生せず監査する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは全差と版結合。旧55の計測監査は繰り返さない。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("保存物確認.jsonを上書きしません")
    source, label_helper, summary = A.helpers()
    audit = source.Audit()
    files = [STUDY / n for n in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    files += [WORK / n for n in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [ROOT / "work/波の区間分離/教師接続確認.json"]
    files += [OLD / "結果.json", OLD / "保存物確認.json", OLD / "固定.json", OLD / "一覧.resources.json", COMPLETE,
              MEASUREMENTS, OLDWORK / "定時判断と運用.jsonl.gz", OLDWORK / "入口先着.jsonl.gz",
              source.MANIFEST, FRAMES, SLOTS50, Path(__file__), Path(__file__).with_name("学習.py")]
    before = {p.relative_to(ROOT).as_posix(): source.sha(p) for p in files}
    fixed, result = source.read(STUDY / "固定.json"), source.read(STUDY / "結果.json")
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("固定出典:" + name, source.sha(ROOT / name), digest)
    audit.check("監査自己の固定包含", Path(__file__).relative_to(ROOT).as_posix() in fixed["ファイルSHA256"], True)
    audit.check("試行・固定bind", (result["試行"], result["固定SHA256"]), (60, source.sha(STUDY / "固定.json")))
    audit.check("候補集合", set(result["候補"]), {*CONTROLS, *POLICIES})
    audit.check("新分類器/新独立計測/新運用数", (result["新分類器fit"], result["新独立計測"], result["新運用数"]), (0, 0, 92))
    previous, previous_proof, _ = check_reused_proof(source, audit)
    entries = source.read(source.MANIFEST)["entries"]
    phases = A.phases(entries, source)
    evaluated = [e["session"] for e in entries[20:]]
    audit.check("評価46場順", result["評価場"], evaluated)
    audit.check("初期20場は学習専用", result["学習専用場"], [e["session"] for e in entries[:20]])
    audit.check("旧59回収metadata", result["対照モデル"], previous["モデル"])
    audit.check("準備比較は旧59全dict", result["準備比較"], previous["準備比較"])
    audit.check("独立測定状態の再用", result["独立測定"], previous["独立測定"])
    audit.check("旧59保存対照", result["対照参照"], {"候補": list(CONTROLS), "元試行": 59, "同じ評価46場": True, "市場再生": False})
    audit.check("独立測定参照", result["独立測定参照"], {"元試行": 55, "path": (MEASUREMENTS).relative_to(ROOT).as_posix(),
                                                   "sha256": source.sha(MEASUREMENTS), "再計測": False})
    measurements, old_slots, features, baseline = R56.saved_measurements(source, audit)
    prepared = prepare_features(old_slots, features, source, audit)
    measurements = {key: {**row, "features": prepared[row["slot_id"]]["vectors"][str(row["side"])]} for key, row in measurements.items()}
    teacher_blocks = {e["session"]: {"slots": [s for s in old_slots.values() if s["session"] == e["session"]]} for e in entries}
    preflight = source.read(ROOT / "work/波の区間分離/教師接続確認.json")
    audit.check("fit前全特徴指紋", fingerprint(prepared), preflight["全特徴SHA256"])
    audit.check("fit前価格経路被覆", path_coverage(entries, teacher_blocks, prepared), preflight["価格経路分布"])
    old_blocks, saved_features, old38_matches = {}, {}, 0
    for block in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz"):
        key = block["session"], block["policy"]
        if key in old_blocks or block["policy"] not in CONTROLS:
            raise ValueError("旧59場候補の重複又は範囲外")
        old_blocks[key] = block
        for slot in block["slots"]:
            identity, feature = slot["slot_id"], slot["feature"]["base"]
            audit.check("旧59保存38辞書完全同値", control_projection(prepared[identity]), slot["feature"])
            old38_matches += 1
            slim = features[identity]
            audit.check("56検証済み特徴の必要項目", {k: feature[k] for k in slim}, slim)
            if identity in saved_features:
                audit.check("56二候補の特徴全dict同値", feature, saved_features[identity])
            saved_features[identity] = feature
    audit.check("旧92運用集合", set(old_blocks), {(s, p) for s in evaluated for p in CONTROLS})
    detail = defaultdict(list)
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        detail[block["session"]].append(block)
    audit.check("新詳細46場", set(detail), set(evaluated))
    labels = {p: [] for p in (*CONTROLS, *POLICIES)}
    for row in source.json_rows(OLDWORK / "入口先着.jsonl.gz"):
        labels[row["policy"]].append(row)
    sequence = list(source.json_rows(WORK / "入口先着.jsonl.gz"))
    labels_by_session = defaultdict(list)
    for row in sequence:
        labels_by_session[row["session"]].append(row)
    resources = source.read(STUDY / "一覧.resources.json")["resources"]
    resource_map = {(r["session"], r["method_id"]): r for r in resources}
    audit.check("184資源全集合", set(resource_map), {(s, p) for s in evaluated for p in (*CONTROLS, *POLICIES)})
    audit.check("184資源一意", (len(resources), len({r["id"] for r in resources})), (184, 184))
    for row in source.read(OLD / "一覧.resources.json")["resources"]:
        if row["method_id"] in CONTROLS:
            audit.check("旧92資源全属性", resource_map[row["session"], row["method_id"]], row)
            audit.check("旧Viewer固定包含", row["pnl_path"] in fixed["ファイルSHA256"], True)
    model_pins, models, calibrations, teacher_matches, set_matches = {}, {}, {}, {}, {}
    for manifest in previous["モデル"] + previous["対照モデル"] + previous["回収集計"]:
        model_pins[manifest["path"]] = source.sha(ROOT / manifest["path"])
    manifests, cal_manifests = ({m["phase"]: m for m in result[key]} for key in ("モデル", "回収集計"))
    audit.check("新三木順", [m["phase"] for m in result["モデル"]], [p["id"] for p in phases])
    audit.check("新三回収順", [m["phase"] for m in result["回収集計"]], [p["id"] for p in phases])
    fits = 0
    for phase in phases:
        phase_id, identity = phase["id"], "S0_" + phase["id"]
        base_path = OLD / "models" / ("V0_" + phase_id + ".json")
        old_model = source.read(base_path)
        relative = base_path.relative_to(ROOT).as_posix()
        model_pins[relative] = source.sha(base_path)
        audit.check("59旧木の成功監査bind", model_pins[relative], previous_proof["モデルSHA256"][relative])
        barrier_used, barrier_training, _ = A.training_rows(phase["train"], teacher_blocks, features, baseline, phase["evaluation_start"], 18)
        keys = ("input_rows_sha256", "used_rows_sha256", "row_ids_sha256", "period_sha256")
        teacher_matches[phase_id] = {k: barrier_training[k] == old_model["training"]["barrier_fingerprints"][k] for k in keys}
        audit.check("旧教師四指紋:" + phase_id, teacher_matches[phase_id], dict.fromkeys(keys, True))
        raw_rows = R56.recovery_input(phase["train"], teacher_blocks, prepared, measurements)
        used, training = recovery_training(raw_rows, phase["evaluation_start"])
        for key in ("input_rows_sha256", "used_rows_sha256", "target_rows_sha256", "base18_fingerprints", "base30_fingerprints", "base38_fingerprints"):
            audit.check("fit前教師接続:" + phase_id + key, training[key], preflight["期間"][phase_id][key])
        old_cal = source.read(OLD / "models" / ("回収_" + phase_id + ".json"))
        cal_ids = [{k: r[k] for k in ("session", "slot_id", "side")} for leaf in old_cal["leaves"].values() for r in leaf["rows"]]
        ids = [{k: r[k] for k in ("session", "slot_id", "side")} for r in used]
        set_matches[phase_id] = {"旧D0使用ID": ids == old_model["training"]["row_ids"],
                                 "56回収使用ID集合": sorted(ids, key=lambda r: (r["slot_id"], r["side"])) == sorted(cal_ids, key=lambda r: (r["slot_id"], r["side"]))}
        audit.check("同一使用教師集合:" + phase_id, all(set_matches[phase_id].values()), True)
        path = STUDY / "models" / (identity + ".json")
        model = source.read(path)
        digest = source.sha(path)
        model_pins[path.relative_to(ROOT).as_posix()] = digest
        audit.check("旧18教師全指紋:" + phase_id, training["base18_fingerprints"], old_model["training"]["base18_fingerprints"])
        audit.check("旧30教師全指紋:" + phase_id, training["base30_fingerprints"], old_model["training"]["base30_fingerprints"])
        audit.check("旧38教師全指紋:" + phase_id, training["base38_fingerprints"], {k: old_model["training"][k] for k in training["base38_fingerprints"]})
        distribution = segment_distribution(used, prepared)
        audit.check("fit前追加区間分布:" + phase_id, distribution, preflight["追加特徴分布"][phase_id])
        audit.check("結果追加区間分布:" + phase_id, distribution, result["追加特徴分布"][phase_id])
        check_model(model, used, training, feature_metadata(), identity, source.sha(Path(__file__).with_name("学習.py")), audit)
        audit.check("全葉episode反復統計:" + phase_id, result["経路支持"][phase_id], episode_support(model, used, prepared))
        audit.check("新木metadata", manifests[phase_id], {"id": identity, "policy": "S0", "phase": phase_id, "path": path.relative_to(ROOT).as_posix(), "SHA256": digest,
                    "学習場": [e["session"] for e in phase["train"]], "評価場": [e["session"] for e in phase["evaluation"]], "特徴数": 46, "評価開始": phase["evaluation_start"]})
        fits += sum(part["fit_performed"] for part in model["training"]["partition"].values())
        cal_path = STUDY / "models" / ("回収_" + phase_id + ".json")
        calibration = expected_calibration(model, measurements, phase["evaluation_start"])
        calibration.update(phase=phase_id, base_model_path=path.relative_to(ROOT).as_posix(), base_model_sha256=digest)
        audit.check("新全葉回収集計", source.read(cal_path), calibration)
        cal_digest = source.sha(cal_path)
        model_pins[cal_path.relative_to(ROOT).as_posix()] = cal_digest
        audit.check("回収metadata", cal_manifests[phase_id], {"id": identity, "phase": phase_id, "path": cal_path.relative_to(ROOT).as_posix(), "SHA256": cal_digest})
        models[phase_id], calibrations[phase_id] = model, calibration
    audit.check("回帰器の実fit数", result["新回帰器fit"], fits)
    audit.check("旧教師一致表示", result["旧教師一致"], teacher_matches)
    R56.check_teacher_sets(result["教師集合一致"], set_matches, audit)
    accounts, summaries, cache_pins, viewer_pins, mixed_slots, closed_matches = [], [], {}, {}, 0, 0
    for entry in entries[20:]:
        session = entry["session"]
        phase = next(p for p in phases if session in {e["session"] for e in p["evaluation"]})
        phase_id, model, calibration = phase["id"], models[phase["id"]], calibrations[phase["id"]]
        tape, cache_path, digest, input_quality = R55.load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        audit.check("新運用原tapeの59監査bind", digest, previous_proof["キャッシュSHA256"][cache_path])
        for policy in CONTROLS:
            accounts.append(P.account(old_blocks[session, policy]["operation"], source, audit))
        audit.check("新二候補順", [b["policy"] for b in detail[session]], list(POLICIES))
        choices = {}
        for block in detail[session]:
            policy, operation = block["policy"], block["operation"]
            audit.check("新運用ID/場/phase", (operation["candidate_id"], operation["session"], block["phase"]), (policy, session, phase_id))
            audit.check("入力品質", block["input_quality"], input_quality)
            source.check_decisions(block, tape, audit)
            source.check_orders(operation, tape, audit)
            source.check_trail(operation, tape, audit)
            for closed in operation["closed"]:
                counterpart = measurements[closed["slot_id"], closed["side"]]["operation"]["closed"]
                audit.check("新mixed単独一完結対応", len(counterpart), 1)
                if counterpart:
                    audit.check("新mixedの同一新規完結型値", R55.strict_close_equal(closed, counterpart[0]), True)
                closed_matches += 1
            path = ROOT / resource_map[session, policy]["pnl_path"]
            audit.check("新Viewer正規保存先", path.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            accounts.append(source.check_cash(operation, list(source.json_rows(path)), tape, audit))
            summaries.append({"場": session, "候補": policy, "期間": source.span(session), "入力品質": input_quality,
                              "運用品質": operation["quality"], "運用集計": operation["metrics"]})
            choices[policy] = {}
            for slot in block["slots"]:
                mixed_slots += 1
                identity = slot["slot_id"]
                feature, old = prepared[identity], old_slots[identity]
                predicted = expected_prediction(model, calibration, feature["vectors"], policy) if feature["ready"] else None
                side, reason = (predicted["side"], predicted["reason"]) if predicted else (0, feature["reason"])
                if side and feature["background_direction"] == 0:
                    side, reason = 0, "上位DI同値の役割未確定WAIT"
                role = "待機" if not side else "順行" if side == feature["background_direction"] else "反転"
                expected = {**{k: old[k] for k in BINDING}, "policy": policy, "phase": phase_id, "model_id": model["model_id"],
                            "side": side, "role": role, "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": predicted}
                audit.check("新slot全内容/採否", slot, expected)
                if side:
                    labels[policy].append({**baseline[identity, side], "policy": policy, "role": role})
                choices[policy][identity] = side
        audit.check("純S1はS0同方向subset", all(not side or choices["S0"][key] == side for key, side in choices["S1"].items()), True)
        for row in labels_by_session[session]:
            _, force, _, _ = source.calendar(session)
            expected = {**{k: row[k] for k in (*BINDING, "policy", "side", "role")}, **label_helper.first_force_expected(tape, row, force, source)}
            audit.check("新先着の原BBO全属性", row, expected)
        print(session + " 回帰木・新二運用保存照合", flush=True)
    audit.check("新3404予定枠", mixed_slots, 3404)
    audit.check("全価格経路被覆", result["価格経路分布"], path_coverage(entries, teacher_blocks, prepared))
    audit.check("主内保存照合数", result["検査"], {"測定特徴方向一致": 4884, "旧評価特徴完全一致": 3404, "旧18特徴完全一致": 2442, "旧38特徴保存一致": old38_matches, "同一新規完結一致": closed_matches})
    audit.check("先着全属性コピー/保存順", sequence, [r for p in POLICIES for r in labels[p]])
    audit.check("全場別表示", result["場別"], summaries)
    check_periods(accounts, labels, result, source, summary, audit)
    for policy in CONTROLS:
        audit.check("旧保存対照の全期間", result["候補"][policy], previous["候補"][policy])
        audit.check("旧保存役割対照", result["役割別入口"][policy], previous["役割別入口"][policy])
    audit.check("新詳細は二系列", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins, **viewer_pins}.items():
        audit.check("実行中不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 60, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0, "照合項目数": audit.count,
               "不一致数": audit.bad, "不一致": audit.examples, "結果SHA256": source.sha(STUDY / "結果.json"),
               "本物fit再実行": False, "市場戦略再生": False, "新独立計測": False, "新主処理import": False,
               "55測定再監査": False, "再用方向行数": len(measurements), "新運用数": 92, "新予定比較数": mixed_slots,
               "価格経路分布": path_coverage(entries, teacher_blocks, prepared), "回帰木数": len(models), "回収集計数": len(calibrations), "回帰器保存fit数": fits,
               "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api,
               "検証範囲": "59完了/Aと55測定の版連鎖、旧38辞書と保持経路の独立再構成、登録前とr前後の終値差累積/最初pによる新8列/出典と区間分布の別算、保存教師のstrict過去・pair交差・18/30/38/46指紋、新全node所属/先着率/回収統計/MSE/支持/4群/JSON採否、新92運用のBBO・注文・現金・保存追尾・先着・費用・全予定活動。",
               "限定": "55の検証済み独立計測を再生しない。別fit/最良閾値探索/全tick戦略再生なし。全66既使用で、葉内平均や一致から未見利益・心理因果を証明しない。"}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def self_test() -> dict:
    """別ファイルの人工を主処理から独立して起動する。

    引数: なし。
    返り値: dictは人工成功/差数。実教師・本物fit・市場は読まない。
    """
    artificial = load(Path(__file__).with_name("保存検証人工.py"), "再試験保存監査の独立人工")
    return artificial.self_test()


def main() -> None:
    """人工又はroot正式保存監査を上書きせず起動する。

    引数: CLIの--self-test/--run、任意--viewer-url。
    返り値: None。不一致は終了1、既存正式proofは拒否する。
    """
    parser = argparse.ArgumentParser(description="60の先行進行・区間分離8列・46列回収分岐・保存運用の独立監査")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    proof = self_test() if args.self_test else run(args.viewer_url)
    print(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False))
    if proof["不一致数"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
