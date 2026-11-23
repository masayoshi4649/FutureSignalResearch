"""70の支持剪定・保存条件運用を新剪定器や市場戦略再生なしで独立検査する。"""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode, urljoin

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00070_約定支持を保つ粒度で技法を組み合わせる"
WORK = ROOT / "work/支持を保つ技法群/00070"
OLD = ROOT / "study/00069_条件入口に合わせて技法群の教師を作る"
OLDWORK = ROOT / "work/条件入口の教師/00069"
LEDGER = ROOT / "work/条件入口の教師/69完了記録.json"
PREFLIGHT = ROOT / "work/条件入口の教師/入力接続確認.json"
POLICIES, CONTROLS = ("P0", "P1"), ("C0", "C1")
PERIODS = ("学習", "条件選択", "後続検査")


def load(path: Path, name: str):
    """固定純補助を固有名で読み、大域値は変更しない。

    引数: path(Path)はコード、name(str)は固有名。
    返り値: ModuleTypeは読取補助。新70主・剪定器を正式期待値へ呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R69 = load(HERE.parent / "条件入口の教師/保存検証.py", "支持粒度70の固定69監査")
R68, R66, R65, A, P, R55 = R69.R68, R69.R66, R69.R65, R69.A, R69.P, R69.R55
fingerprint = R69.fingerprint
BINDING, SLOT_FIELDS = R69.BINDING, R69.SLOT_FIELDS


# ----------------------------------------
def supported(node: dict) -> bool:
    """約定既知の三支持だけを比較し、scoreや回収を参照しない。

    引数: node(dict)は成功監査へ結んだ旧69node。
    返り値: boolはunique60枠/6日/10場を全て満たすか。
    """
    for key in ("unique_slots", "days", "sessions"):
        if type(node[key]) is not int or node[key] < 0:
            raise ValueError("旧nodeの約定支持が不正")
    return node["unique_slots"] >= 60 and node["days"] >= 6 and node["sessions"] >= 10


def pruning_geometry(model: dict) -> dict:
    """旧IDの逆順動的計画で支持剪定集合を独立に求める。

    引数: model(dict)は旧69C0保存木。
    返り値: dictは残存旧ID/全新旧対応/候補終端・統合後終端/元四群と新四群のサイズ。
    """
    nodes = model["nodes"]
    if model["policy"] != "C0" or len(nodes) < 7:
        raise ValueError("固定3nodeと四群を持つ旧C0木が必要")
    terminals, retained, decisions = {}, {}, {}
    for index in range(len(nodes) - 1, -1, -1):
        node = nodes[index]
        if node["id"] != index:
            raise ValueError("旧IDは配列順の連番が必要")
        supported(node)
        if node["left"] == node["right"] == -1:
            if index < 3:
                raise ValueError("固定3nodeは内部のまま必要")
            terminals[index], retained[index] = [index], {index}
            continue
        left, right = node["left"], node["right"]
        if not all(type(child) is int and index < child < len(nodes) and child in terminals for child in (left, right)) or left == right:
            raise ValueError("旧木の子順・範囲・共有が不正")
        candidates = sorted(terminals[left] + terminals[right])
        weak = [identity for identity in candidates if not supported(nodes[identity])]
        collapse = index >= 3 and bool(weak)
        terminals[index] = [index] if collapse else candidates
        retained[index] = {index} if collapse else {index} | retained[left] | retained[right]
        if index >= 3:
            decisions[index] = {"candidate_terminals": list(candidates), "unsupported_terminals": weak,
                "collapsed": collapse, "result_terminals": list(terminals[index])}
    keep = sorted(retained[0])
    old_to_new = {str(index): keep.index(index) if index in retained[0] else None for index in range(len(nodes))}
    new_to_old = {str(index): old for index, old in enumerate(keep)}
    partitions = {}
    for name, part in model["training"]["partition"].items():
        source_root = part["root"]
        subtree = retained[source_root]
        partitions[name] = {"source_root": source_root, "source_node_count": part["node_count"],
            "new_root": old_to_new[str(source_root)], "new_node_count": len(subtree)}
    return {"retained": keep, "source_to_new": old_to_new, "new_to_source": new_to_old,
        "decisions": decisions, "partitions": partitions}


def expected_nodes(model: dict, geometry: dict) -> list[dict]:
    """旧親統計を保持し、葉記号と残存ID/pathだけを別組立する。

    引数: model(dict)は旧C0、geometry(dict)は独立剪定結果。
    返り値: list[dict]は新全node。score・回収・支持・methods/familiesを再学習しない。
    """
    result, mapping = [], geometry["source_to_new"]
    for source_id in geometry["retained"]:
        node = deepcopy(model["nodes"][source_id])
        node.update(id=mapping[str(source_id)], source_node_id=source_id)
        collapse = geometry["decisions"].get(source_id, {}).get("collapsed", False)
        if collapse:
            node.update(feature=-2, feature_id=None, family=None, threshold=-2.0, left=-1, right=-1)
        elif node["left"] != -1:
            node.update(left=mapping[str(node["left"])], right=mapping[str(node["right"])])
        node["path"] = [{**deepcopy(part), "node": mapping[str(part["node"])]} for part in node["path"]]
        if any(part["node"] is None for part in node["path"]):
            raise ValueError("残存nodeの祖先が除去された")
        result.append(node)
    return result


def expected_rules() -> dict:
    """支持剪定の監査側literalを保存し、新剪定器へ問い合わせない。

    引数: なし。
    返り値: dictは支持/固定段/下からの順序/統合/不使用値/元証拠の契約。
    """
    return {"入力": "固定69のC0保存木だけ。全60特徴・教師・親統計を保持し、新fit0",
        "約定支持": {"unique枠": 60, "日": 6, "場": 10},
        "固定段": "旧node0/1/2は分割を維持。四つのDI×対応episode群を統合しない",
        "順序": "各子木を下から先に剪定し、その結果の全終端葉を判定する",
        "保持": "剪定後の両側すべての終端葉が約定支持を満たす場合だけ学習分割を保持",
        "統合": "一つでも約定支持不足なら両側を親へ統合。片側だけ残さず、祖先でも再判定する",
        "固定群不足": "四群の親自身が支持不足でも固定段を越えて統合しない。従来の支持不足WAITを維持",
        "決定へ不使用": ["score", "回収額", "回収平均", "MSE", "評価到達", "評価成績", "技法資格"],
        "統計": "統合先の旧親統計を再用。子葉平均の平均や教師再生成を行わない",
        "新ID": "残存旧IDの昇順を0から連番。旧0/1/2は新0/1/2を維持",
        "旧学習証拠": "trainingとparameters/structureは元の学習証拠。新配置はpruning.partitionsと対応表を参照",
        "予測": "局所policy=C0の複写で固定69walk/predictへ委譲。旧globalや元辞書を変更しない",
        "維持": "先着1/3・約定60枠6日10場・複数技法・過去主回収strict正・66選択・68入口・O49出口を緩めない"}


def expected_model(original: dict, identity: str, source_sha256: str) -> dict:
    """独立剪定集合と旧親全文から派生モデルの全辞書を再構成する。

    引数: original(dict)は旧C0、identity(str)は新ID、source_sha256(str)は旧モデルbyte指紋。
    返り値: dictは全派生木と対応表/統合履歴。逆ID順の計算を旧ID昇順に整列する。
    """
    geometry = pruning_geometry(original)
    decisions = []
    for source_id, item in sorted(geometry["decisions"].items()):
        support = [{"source_node_id": terminal, **{key: original["nodes"][terminal][key] for key in ("unique_slots", "days", "sessions")},
            "supported": supported(original["nodes"][terminal])} for terminal in item["candidate_terminals"]]
        decisions.append({"source_node_id": source_id, "action": "両側統合" if item["collapsed"] else "保持",
            "terminal_source_ids": item["candidate_terminals"], "terminal_support": support, "result_terminal_source_ids": item["result_terminals"],
            "reason": "剪定後の終端に約定支持不足があるため両側を親へ統合" if item["collapsed"] else "剪定後の両側全終端が約定支持を満たす",
            "retained_in_final": source_id in geometry["retained"], "split_retained_in_final": source_id in geometry["retained"] and not item["collapsed"]})
    nodes = expected_nodes(original, geometry)
    result = deepcopy(original)
    result.update(model_id=identity, policy="P0", source_model_id=original["model_id"], source_model_sha256=source_sha256, nodes=nodes,
        pruning={"rules": expected_rules(), "source_model_id": original["model_id"], "source_model_sha256": source_sha256,
            "source_model_content_sha256": fingerprint(original), "source_node_count": len(original["nodes"]), "new_node_count": len(nodes),
            "source_to_new": geometry["source_to_new"], "new_to_source": geometry["new_to_source"], "decisions": decisions,
            "partitions": geometry["partitions"], "fit_count": 0, "code_sha256": hashlib.sha256((HERE / "剪定.py").read_bytes()).hexdigest(),
            "shared_source_sha256": {"scripts/条件入口の教師/学習.py": "f0569e4d25834b038caba57929f941367e22e397a64d8306a14406f41fef77de"}})
    return result


def check_model(model: dict, original: dict, identity: str, source_sha256: str, audit) -> None:
    """新剪定器を呼ばず全派生辞書・node同値・経路対応を検査する。

    引数: model/original(dict)は新旧保存木、identity/source_sha256(str)は元情報、audit(Audit)は記録。
    返り値: None。全統計の同値を要求し、新教師や回帰器を作らない。
    """
    expected = expected_model(original, identity, source_sha256)
    audit.check("派生top項目集合", set(model), set(expected))
    for key in expected:
        if key != "nodes":
            audit.check("派生top:" + key, model[key], expected[key])
    audit.check("派生node数", len(model["nodes"]), len(expected["nodes"]))
    for node, value in zip(model["nodes"], expected["nodes"]):
        audit.check("派生node全属性:" + str(value["id"]), node, value)
        source_node = original["nodes"][value["source_node_id"]]
        audit.check("支持と旧支持旗", (node["leaf_support"], supported(node)), (source_node["leaf_support"], supported(source_node)))
        audit.check("元/現methods families", (node["methods"], node["families"]), (source_node["methods"], source_node["families"]))
    audit.check("固定三node元ID", [node["source_node_id"] for node in model["nodes"][:3]], [0, 1, 2])
    audit.check("元training全文", model["training"], original["training"])
    audit.check("元教師strict境界", (model["training"]["period"]["max_label_end_time"] < model["training"]["evaluation_start"],
        model["training"]["period"]["max_recovery_end_time"] < model["training"]["evaluation_start"]), (True, True))


def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """新剪定器の予測を呼ばず、旧69約定分母と66両側資格式を再用する。

    引数: model/calibration(dict)は検算済み派生木、vectors(dict)は当時60値、policy(str)はP0/P1。
    返り値: dictは全prediction。政策名を局所C0/C1へ写すだけで旧globalを変更しない。
    """
    if policy not in POLICIES or model["policy"] != "P0":
        raise ValueError("派生木又は政策が不正")
    return R69.expected_prediction({**model, "policy": "C0"}, calibration, vectors, "C0" if policy == "P0" else "C1")


def expected_slots(block: dict, model: dict, calibration: dict, policy: str, phase: str) -> list[dict]:
    """旧69C0当時特徴と派生木のJSON走査から純判断を別算する。

    引数: block(dict)は旧C0全予定、model/calibration(dict)は過去派生値、policy/phase(str)は識別。
    返り値: list[dict]は新純slot全文。DI0WAITと実方向役割は旧通り。
    """
    result = []
    for origin in block["slots"]:
        feature = origin["feature"]
        prediction = expected_prediction(model, calibration, feature["vectors"], policy) if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        result.append({**{key: origin[key] for key in BINDING}, "policy": policy, "phase": phase, "model_id": model["model_id"],
            "side": side, "role": "順行" if side and side == feature["background_direction"] else "反転" if side else "待機",
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": prediction})
    return result


# ----------------------------------------
def run(viewer_url: str | None = None) -> dict:
    """支持剪定三木と新92条件運用を保存証拠・原BBOから一度検査する。

    引数: viewer_url(str|None)は任意Viewer API。
    返り値: dictは公式proof。新剪定器/主/Engineを期待値へ呼ばず、旧4092教師は再測定しない。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("70保存物確認は作成済み。再実行しません")
    source, _, summary = A.helpers()
    audit = source.Audit()
    result, fixed, inputs = [source.read(STUDY / name) for name in ("結果.json", "固定.json", "入力台帳.json")]
    previous, proof, ledger, preflight = [source.read(path) for path in (OLD / "結果.json", OLD / "保存物確認.json", LEDGER, PREFLIGHT)]
    files = [STUDY / name for name in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    files += [WORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [OLD / name for name in ("結果.json", "保存物確認.json", "固定.json", "一覧.resources.json")]
    files += [OLDWORK / name for name in ("条件独立測定.jsonl.gz", "定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [LEDGER, PREFLIGHT, source.MANIFEST, Path(__file__), HERE / "保存検証の人工検査.py", HERE / "監査仕様.md"]
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in files}
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("70固定:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    for name, digest in inputs["ファイルSHA256"].items():
        audit.check("70入力台帳:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("69完了台帳指定SHA", source.sha(LEDGER), "e0508f5171257e928194f631729e3e509d707c0feea2cd5fb9b5459cae25ac1f")
    audit.check("69成功監査", (proof["全件一致"], proof["不一致数"], proof["結果SHA256"]), (True, 0, source.sha(OLD / "結果.json")))
    audit.check("69単一完了", source.read(OLDWORK / "実行完了.json")["結果SHA256"], proof["結果SHA256"])
    audit.check("69完了対象数", len(ledger["成果物SHA256"]), 248)
    for name, digest in ledger["成果物SHA256"].items():
        audit.check("69完了不変:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("70固定bind", (result["試行"], result["固定SHA256"], result["全66場既使用"]), (70, source.sha(STUDY / "固定.json"), True))
    audit.check("新四候補集合", set(result["候補"]), {*CONTROLS, *POLICIES})
    names = ("新回帰器fit", "新分類器fit", "新保存木数", "新派生木数", "参照モデル数", "新独立計測", "参照独立測定", "新運用数")
    audit.check("70新処理範囲", tuple(result[name] for name in names), (0, 0, 3, 3, 3, 0, 4092, 92))
    audit.check("70保存対照", result["対照参照"], {"候補": list(CONTROLS), "元試行": 69, "市場再生": False})
    audit.check("70学習参照", result["学習参照"], {"元試行": 69, "モデル政策": "C0", "同じ60特徴": True, "新fit": False,
        "共通教師": (OLD / "結果.json").relative_to(ROOT).as_posix(), "無取引": "回収0・障壁対象外"})
    # ----------------------------------------
    # 旧69の固定入力読取だけを再用する。既存特徴算術再構成あり、新独立特徴監査ではない。
    reader = load(HERE.parent / "条件入口の教師/入力.py", "支持70監査の固定69入力")
    entries, blocks, prepared, _, conditions, _, input_checks = reader.verified_inputs()
    audit.check("旧69入力検査", input_checks, preflight["検査"])
    audit.check("旧69全特徴SHA", fingerprint(prepared), preflight["全特徴SHA256"])
    audit.check("旧69全条件SHA", fingerprint(conditions), preflight["全条件SHA256"])
    audit.check("旧69全予定判断SHA", fingerprint({name: block["slots"] for name, block in blocks.items()}), preflight["全予定判断SHA256"])
    audit.check("既使用66場台帳", entries, source.read(source.MANIFEST)["entries"])
    evaluated = [entry["session"] for entry in entries[20:]]
    audit.check("同46評価場", result["評価場"], evaluated)
    audit.check("学習専用20場", result["学習専用場"], [entry["session"] for entry in entries[:20]])
    old_blocks = {(block["session"], block["policy"]): block for block in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz") if block["policy"] in CONTROLS}
    audit.check("旧C92集合", set(old_blocks), {(session, policy) for session in evaluated for policy in CONTROLS})
    features_compared = 0
    for block in old_blocks.values():
        for slot in block["slots"]:
            audit.check("69C当時全60辞書", slot["feature"], prepared[slot["slot_id"]])
            features_compared += 1
    audit.check("旧C全3404特徴", features_compared, 3404)
    measured = {}
    for row in source.json_rows(OLDWORK / "条件独立測定.jsonl.gz"):
        key = row["slot_id"], row["side"]
        if key in measured:
            raise ValueError("旧独立方向の重複")
        measured[key] = row
    expected_keys = {(slot["slot_id"], side) for block in blocks.values() for slot in block["slots"] if prepared[slot["slot_id"]]["ready"] for side in (1, -1)}
    audit.check("旧4092方向の集合", (len(measured), set(measured)), (4092, expected_keys))
    audit.check("全入力検査", result["入力検査"], {**input_checks, "69全特徴SHA256": preflight["全特徴SHA256"],
        "69全条件SHA256": preflight["全条件SHA256"], "保存独立方向": len(measured), "保存C運用": len(old_blocks)})
    # ----------------------------------------
    # 学習済み親統計から独立剪定し、同時に新旧対応と六つのmodel/cal指紋を確認する。
    models, calibrations, model_pins = {}, {}, {}
    model_meta = {meta["phase"]: meta for meta in result["モデル"]}
    cal_meta = {meta["phase"]: meta for meta in result["回収集計"]}
    audit.check("新三モデル/三cal集合", (len(result["モデル"]), len(result["回収集計"]), set(model_meta), set(cal_meta)), (3, 3, {"W20", "W30", "F40"}, {"W20", "W30", "F40"}))
    for phase in R69.phases(entries, source):
        name, identity = phase["id"], "P0_" + phase["id"]
        meta, cal_info = model_meta[name], cal_meta[name]
        original_path = OLD / "models" / ("C0_" + name + ".json")
        original, digest = source.read(original_path), source.sha(original_path)
        audit.check("69元木成功SHA", digest, proof["モデルSHA256"][original_path.relative_to(ROOT).as_posix()])
        model, calibration = source.read(ROOT / meta["path"]), source.read(ROOT / cal_info["path"])
        for item in (meta, cal_info):
            model_pins[item["path"]] = source.sha(ROOT / item["path"])
            audit.check("新派生model/calSHA", model_pins[item["path"]], item["SHA256"])
        model_pins[original_path.relative_to(ROOT).as_posix()] = digest
        check_model(model, original, identity, digest, audit)
        audit.check("結果剪定全文", result["剪定"][name], model["pruning"])
        audit.check("派生回収全葉", calibration, R69.expected_calibration(model))
        expected_meta = {"id": identity, "policy": "P0", "phase": name, "path": (STUDY / "models" / (identity + ".json")).relative_to(ROOT).as_posix(),
            "SHA256": source.sha(ROOT / meta["path"]), "特徴数": 60, "元path": original_path.relative_to(ROOT).as_posix(), "元SHA256": digest,
            "学習場": [entry["session"] for entry in phase["train"]], "評価場": [entry["session"] for entry in phase["evaluation"]], "評価開始": phase["evaluation_start"]}
        audit.check("派生metadata全文", meta, expected_meta)
        audit.check("calmetadata全文", cal_info, {"id": identity, "policy": "P0", "phase": name,
            "path": (STUDY / "models" / ("回収_" + identity + ".json")).relative_to(ROOT).as_posix(), "SHA256": source.sha(ROOT / cal_info["path"])})
        audit.check("元教師strict境界", original["training"]["evaluation_start"], phase["evaluation_start"])
        models[name], calibrations[name] = model, calibration
    # ----------------------------------------
    # 新92運用だけ原配列へ照合する。独立先着/回収は69成功証明の保存値を再用する。
    detail = defaultdict(list)
    for block in source.json_rows(WORK / "定時判断と運用.jsonl.gz"):
        detail[block["session"]].append(block)
    audit.check("新詳細46場", set(detail), set(evaluated))
    phase_by_session = {entry["session"]: phase["id"] for phase in R69.phases(entries, source) for entry in phase["evaluation"]}
    labels = {policy: [] for policy in (*CONTROLS, *POLICIES)}
    slots_by_policy = {policy: [] for policy in POLICIES}
    for row in source.json_rows(OLDWORK / "入口先着.jsonl.gz"):
        if row["policy"] in CONTROLS:
            labels[row["policy"]].append(row)
    resources = source.read(STUDY / "一覧.resources.json")["resources"]
    resource_map = {(row["session"], row["method_id"]): row for row in resources}
    audit.check("184資源全集合", set(resource_map), {(session, policy) for session in evaluated for policy in (*CONTROLS, *POLICIES)})
    audit.check("184資源一意", (len(resources), len({row["id"] for row in resources})), (184, 184))
    for row in source.read(OLD / "一覧.resources.json")["resources"]:
        if row["method_id"] in CONTROLS:
            audit.check("旧C資源全文", resource_map[row["session"], row["method_id"]], row)
    accounts, summaries, cache_pins, viewer_pins = [], [], {}, {}
    entries_matched = closed_matched = 0
    for entry in entries[20:]:
        session, phase = entry["session"], phase_by_session[entry["session"]]
        tape, cache_path, digest, input_quality = R55.load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        audit.check("69成功cachebind", digest, proof["キャッシュSHA256"][cache_path])
        for control in CONTROLS:
            operation = old_blocks[session, control]["operation"]
            account = P.account(operation, source, audit)
            account["conditions"] = operation["conditions"]
            accounts.append(account)
        audit.check("新二政策順", [block["policy"] for block in detail[session]], list(POLICIES))
        for block in detail[session]:
            policy = block["policy"]
            slots = expected_slots(old_blocks[session, "C0"], models[phase], calibrations[phase], policy, phase)
            audit.check("新純全辞書", block["slots"], slots)
            audit.check("新評価phase", block["phase"], phase)
            slots_by_policy[policy].extend(slots)
            expected_conditions = {slot["slot_id"]: conditions[slot["slot_id"]] for slot in slots if slot["side"]}
            audit.check("新採用条件全文", block["conditions"], expected_conditions)
            local_labels, observed = {}, {}
            for slot in slots:
                if not slot["side"]:
                    continue
                identity = slot["slot_id"]
                record = measured[identity, slot["side"]]
                value = deepcopy(record["barrier"])
                value.update(policy=policy, role=slot["role"])
                audit.check("再用先着の条件出典", value["condition"], expected_conditions[identity])
                audit.check("再用先着の元時計", value["origin_slot"], {key: slot[key] for key in BINDING})
                local_labels[identity] = value
                observed[identity] = record["operation"]["conditions"][identity]["last_observation_time"]
                labels[policy].append(value)
            operation = block["operation"]
            audit.check("新実運用識別", (operation["session"], operation["candidate_id"]), (session, policy))
            audit.check("新入力品質", block["input_quality"], input_quality)
            account = R69.check_operation(block, local_labels, observed, tape, source, audit)
            accounts.append(account)
            for order in operation["orders"]:
                if order["kind"] == "entry" and order["status"] == "filled":
                    prior = measured[order["slot"]["slot_id"], order["slot"]["side"]]["barrier"]
                    audit.check("新実独立入口一致", prior["filled"], True)
                    audit.check("新実独立新規三属性", tuple(order["fill_" + key] for key in ("time", "line", "price")), tuple(prior["entry_" + key] for key in ("time", "line", "price")))
                    entries_matched += 1
            for closed in operation["closed"]:
                single = measured[closed["slot_id"], closed["side"]]["operation"]["closed"]
                audit.check("新実独立完結件数", len(single), 1)
                if single:
                    audit.check("新実独立完結非ID全文", R55.strict_close_equal(closed, single[0]), True)
                closed_matched += 1
            path = ROOT / resource_map[session, policy]["pnl_path"]
            audit.check("新Viewer正規パス", path.resolve(), (STUDY / "viewer" / f"{policy}_{session}.trades.jsonl").resolve())
            audit.check("新Viewer全約定", list(source.json_rows(path)), operation["trades"])
            viewer_pins[path.relative_to(ROOT).as_posix()] = source.sha(path)
            summaries.append({"場": session, "候補": policy, "期間": source.span(session), "入力品質": input_quality, "運用品質": operation["quality"], "運用集計": operation["metrics"]})
        print(session + " 支持剪定/保存先着/新二運用照合", flush=True)
    audit.check("新全92場別", result["場別"], summaries)
    audit.check("主二検査", result["検査"], {"同一条件実仮新規一致": entries_matched, "同一条件実独立完結一致": closed_matched})
    sequence = list(source.json_rows(WORK / "入口先着.jsonl.gz"))
    audit.check("先着全文と保存順", sequence, [row for policy in POLICIES for row in labels[policy]])
    audit.check("新条件入口評価数", result["新条件入口評価"], len(sequence))
    for policy in (*CONTROLS, *POLICIES):
        selected = [account for account in accounts if account["candidate"] == policy]
        for period in PERIODS:
            entrance = R68.entry_summary(labels[policy], period, source)
            operation = R68.operation_summary(selected, period, source, summary)
            audit.check(policy + period + "入口", result["候補"][policy][period]["入口"], entrance)
            audit.check(policy + period + "運用", result["候補"][policy][period]["運用"], operation)
            audit.check(policy + period + "同時適格", result["候補"][policy][period]["同時適格"], entrance["70目標"] and operation["活動適格"] and operation["費用適格"])
            for role in ("順行", "反転"):
                audit.check(policy + period + role, result["役割別入口"][policy][period][role], R68.entry_summary([row for row in labels[policy] if row["role"] == role], period, source))
            if policy in POLICIES:
                audit.check(policy + period + "段階", result["条件段階"][policy][period], R68.stage_summary(slots_by_policy[policy], labels[policy], selected, period, source))
                audit.check(policy + period + "理由", result["判断理由"][policy][period], dict(Counter(row["reason"] for row in slots_by_policy[policy] if source.span(row["session"]) == period)))
        if policy in CONTROLS:
            audit.check("旧C対照全期", result["候補"][policy], previous["候補"][policy])
    audit.check("新採用", result["採用"], [policy for policy in POLICIES if all(result["候補"][policy][period]["同時適格"] for period in PERIODS[:2])])
    audit.check("新詳細二系列", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("新詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins, **cache_pins, **viewer_pins}.items():
        audit.check("監査中参照不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 70, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0,
        "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples, "結果SHA256": source.sha(STUDY / "結果.json"),
        "本物fit再実行": False, "新主処理import": False, "新剪定import": False, "Engine期待値import": False, "市場戦略再生": False,
        "新派生木数": 3, "新運用数": 92, "再用独立教師数": len(measured), "同一条件実仮新規数": entries_matched, "同一条件実独立完結数": closed_matched,
        "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api,
        "検証範囲": "旧69完了248対象/成功証明、独立支持剪定集合・source node統計/path/新旧ID/三派生cal、全純JSON採否、新92原BBO条件/注文/保護/現金/品質、四候補集計とViewer184/新2代表。",
        "限定": "固定69入力の既存特徴算術再構成あり、新特徴の独立算法監査ではない。旧4092独立教師は成功指紋で再用し再測定/全件再監査しない。支持粒度の変更と採否の同値を検査し、学習分岐の最適性・未知収益・心理因果は証明しない。"}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """184資源と新P0/P1各一代表の約定・台帳をHTTP照合する。

    引数: base(str|None)はURL、resources/accounts(list[dict])は保存値、source/auditは固定補助。
    返り値: dictはAPI範囲。未指定は未検証とする。
    """
    if not base:
        return {'実行':False,'理由':'--viewer-url未指定。API未検証、新92保存約定は全件照合'}
    query={'catalog_path':(STUDY/'一覧.resources.json').relative_to(ROOT).as_posix()}
    listing,_,_=source.fetch_json(base+'/api/resources?'+urlencode(query))
    audit.check('API184資源全集合',{row['id'] for row in listing['resources']},{row['id'] for row in resources})
    audit.check('API184資源数',len(listing['resources']),184)
    representatives=[]
    for policy in POLICIES:
        account=sorted([row for row in accounts if row['candidate']==policy],key=lambda row:(-abs(row['ledger']['5']),row['session']))[0]
        resource=next(row for row in resources if row['method_id']==policy and row['session']==account['session'])
        parameters={**query,'resource':resource['id'],'interval':'5','price':'last','width':1000,'height':700}
        meta,_,_=source.fetch_json(base+'/api/chart?'+urlencode(parameters))
        data,raw,headers=source.fetch_json(urljoin(base+'/',meta['data_url']))
        audit.check('API本文SHA',hashlib.sha256(raw).hexdigest(),meta['data_sha256'])
        audit.check('APIヘッダSHA',headers.get('x-chart-data-sha256'),meta['data_sha256'])
        audit.check('API集計alias',data['summary'],meta['summary'])
        audit.check('API台帳純額5',Decimal(str(data['summary']['realized_pnl_yen'])),Decimal(str(account['ledger']['5'])))
        trades=list(source.json_rows(ROOT/resource['pnl_path']))
        audit.check('API約定片数',len(data['events']),len(trades))
        for sequence,(trade,event) in enumerate(zip(trades,data['events']),1):
            for key in ('type','qty','position_id','method_id','price'):
                audit.check('API約定:'+key,event[key],trade[key])
            audit.check('API順',event['sequence'],sequence)
            audit.check('API時計',abs(event['timestamp_ms']-datetime.fromisoformat(trade['timestamp']).timestamp()*1000)<=.001,True)
        representatives.append({'候補':policy,'場':account['session'],'資源ID':resource['id'],'台帳観測5円':account['ledger']['5'],'数値SHA256':meta['data_sha256']})
    return {'実行':True,'全資源数':184,'新政策代表':representatives,'代表規約':'政策別最大絶対台帳観測額・場順。採否不使用'}


def self_test() -> dict:
    """支持剪定と保存監査を、架空木・架空価格だけで検査する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致。新fit・本物入力・公式proofは生成しない。
    """
    fixture = load(HERE / "保存検証の人工検査.py", "支持70保存監査の人工")
    return fixture.self_test()


def main() -> None:
    """人工と正式照合を排他CLIで公開する。

    引数: CLIのrun/self_test(bool)はモード、viewer_url(str|None)はHTTP。
    返り値: None。正式runはroot所有で一度だけ実行する。
    """
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--run", action="store_true")
    modes.add_argument("--self-test", action="store_true")
    parser.add_argument("--viewer-url")
    args = parser.parse_args()
    if args.run or args.self_test:
        result = run(args.viewer_url) if args.run else self_test()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
        if not result.get("全件一致", result.get("人工成功", False)):
            raise SystemExit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
