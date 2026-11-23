"""72の厳密分割候補・約定支持・保存木と実運用を独立照合する。"""

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
import platform
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00072_分割候補から約定支持を確保する"
WORK = ROOT / "work/支持を満たす技法分割/00072"
OLD = ROOT / "study/00071_技法の組み合わせへ取得位置を加える"
OLDWORK = ROOT / "work/取得位置と支持/00071"
LEDGER = ROOT / "work/取得位置と支持/71完了記録.json"
LEDGER_SHA = "c531d05db0e461f06a596882e6ae449c43fde8d712172e87072ef7650daf2c84"
POLICIES, CONTROLS = ("C0", "C1", "S0", "S1"), ("G0", "G1")
MODEL_POLICIES = ("C0", "S0")
COUNTS = {"C0": 61, "S0": 61}
PERIODS = ("学習", "条件選択", "後続検査")


def load_fixed(path: Path, name: str, digest: str | None = None):
    """固定純補助だけを固有名で読み、大域値を変更しない。

    引数: path(Path)は固定コード、name(str)はmodule名、digest(str|None)は必要なSHA。
    返り値: ModuleTypeは読込結果。新主・学習・Engineを正式期待値へ読み込まない。
    """
    if digest is not None and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("固定監査コードの変更:" + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R71 = load_fixed(HERE.parent / "取得位置と支持/保存検証.py", "支持候補72の固定71監査",
    "ff00114e24c905fb35f8c2d94e9a2b31ef4552a3d767f150321247e09866bfe9")
R70, R69, R68, R66, R65 = R71.R70, R71.R69, R71.R68, R71.R66, R71.R65
A, P, R55, R56 = R71.A, R71.P, R71.R55, R71.R56
fingerprint = R71.fingerprint
BINDING = R71.BINDING
TEACHER_STUDY, TEACHER_WORK = R71.TEACHER_STUDY, R71.TEACHER_WORK


# ----------------------------------------
def metadata() -> list[dict]:
    """固定71と同じ61特徴metadataを独立定数から作る。

    引数: なし。
    返り値: list[dict]は旧60とF61。新入力や学習器へ問い合わせない。
    """
    return R71.metadata("G0")


def support_of(rows: list[dict]) -> dict:
    """約定方向行だけで三種類の支持を数える。

    引数: rows(list[dict])は独立canonical教師の部分集合。
    返り値: dictは全方向行とfilled unique枠/日/場・支持旗。無取引は支持に足さない。
    """
    filled = [row for row in rows if row["filled"]]
    slots = len({(row["session"], row["slot_id"]) for row in filled})
    days = len({row["session"][:10] for row in filled})
    sessions = len({row["session"] for row in filled})
    return {"direction_rows": len(rows), "unique_slots": slots, "days": days, "sessions": sessions,
        "supported": slots >= 60 and days >= 6 and sessions >= 10}


def fraction_dict(value: Fraction) -> dict:
    """厳密なMSE改善をJSON用の整数文字列へ直す。

    引数: value(Fraction)は約分済み改善値。
    返り値: dict[str,str]はnumerator/denominator。epsilonや丸めを使わない。
    """
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def candidate_search(rows: list[dict], columns: list[int], required: bool, depth: int) -> dict:
    """float32水準別の別集計から全境界を独立列挙し、厳密最良分割を返す。

    引数: rows(list[dict])はnode所属、columns(list[int])は59子列、required(bool)は両子支持制約、depth(int)は子内深さ。
    返り値: dictは全候補数・適格数・停止理由・選択。新Lの列挙器又はfitを呼ばない。
    """
    result = {"candidate_count": 0, "row_eligible_count": 0, "support_eligible_count": 0,
        "selectable_count": 0, "support_required": required, "stop_reason": "", "selected": None}
    n = len(rows)
    targets = [Fraction(str(row["pnl5"])) for row in rows]
    # ----------------------------------------
    # 共通分母の整数化は候補のgain比較を厳密に保ち、全行の重み0.5は相殺する。
    if not rows:
        result["stop_reason"] = "空"
        return result
    if depth >= 2:
        result["stop_reason"] = "最大深さ"
        return result
    if n < 120:
        result["stop_reason"] = "全行例数不足"
        return result
    if len(set(targets)) == 1:
        result["stop_reason"] = "目的純粋"
        return result
    denominator = math.lcm(*(value.denominator for value in targets))
    values = [value.numerator * (denominator // value.denominator) for value in targets]
    total = sum(values)
    vectors = [R71.float32(row["features"], 61) for row in rows]
    filled = [row["filled"] for row in rows]
    keys = [[(row["session"], row["slot_id"]), row["session"][:10], row["session"]] for row in rows]
    best_gain = Fraction(0)
    for feature in sorted(columns):
        # 値別bucketを作り、同値方向行は同時に左右へ移す。行単位の候補は作らない。
        buckets = defaultdict(list)
        for index, vector in enumerate(vectors):
            buckets[vector[feature]].append(index)
        levels = sorted(buckets)
        result["candidate_count"] += max(0, len(levels) - 1)
        left_count = left_sum = 0
        left_support = [Counter(), Counter(), Counter()]
        right_support = [Counter(keys[i][part] for i in range(n) if filled[i]) for part in range(3)]
        for position, level in enumerate(levels[:-1]):
            for index in buckets[level]:
                left_count += 1
                left_sum += values[index]
                if filled[index]:
                    for part in range(3):
                        key = keys[index][part]
                        left_support[part][key] += 1
                        right_support[part][key] -= 1
                        if right_support[part][key] == 0:
                            del right_support[part][key]
            right_count = n - left_count
            if min(left_count, right_count) < 60:
                continue
            result["row_eligible_count"] += 1
            left_counts, right_counts = [len(c) for c in left_support], [len(c) for c in right_support]
            supported = all(counts[0] >= 60 and counts[1] >= 6 and counts[2] >= 10 for counts in (left_counts, right_counts))
            result["support_eligible_count"] += int(supported)
            if required and not supported:
                continue
            result["selectable_count"] += 1
            # Σy²は親子で相殺できる。正改善と同点を分数のまま比較する。
            improvement = (Fraction(left_sum * left_sum, left_count) + Fraction((total - left_sum) ** 2, right_count)
                - Fraction(total * total, n)) / (n * denominator * denominator)
            if improvement <= best_gain:
                continue
            threshold = (level + levels[position + 1]) / 2.0
            best_gain = improvement
            def description(count: int, counts: list[int]) -> dict:
                """現在の左右集計器から候補支持の保存形を作る。

                引数: count(int)は全方向行、counts(list[int])はfilled枠/日/場。
                返り値: dictは候補左右支持。統計を教師行として再生成しない。
                """
                return {"direction_rows": count, "unique_slots": counts[0], "days": counts[1], "sessions": counts[2],
                    "supported": counts[0] >= 60 and counts[1] >= 6 and counts[2] >= 10}
            result["selected"] = {"feature": feature, "feature_id": f"F{feature + 1:02d}", "threshold": threshold,
                "gain": fraction_dict(improvement), "left": description(left_count, left_counts), "right": description(right_count, right_counts)}
    if result["row_eligible_count"] == 0:
        result["stop_reason"] = "全行適格候補なし"
    elif required and result["support_eligible_count"] == 0:
        result["stop_reason"] = "支持適格候補なし"
    elif result["selected"] is None:
        result["stop_reason"] = "正改善なし"
    else:
        result["stop_reason"] = "分割採用"
    return result


def check_optimality(model: dict, used: list[dict], audit) -> dict:
    """全node所属を独立JSON走査し、全候補最適性と終端理由を照合する。

    引数: model(dict)は保存元木、used(list[dict])は独立教師、audit(Audit)は照合器。
    返り値: dictは小型の候補総数。全候補一覧はproofへ転記しない。
    """
    members = defaultdict(list)
    for row in used:
        _, _, visits = R71.walk(model, row["features"])
        for index in visits:
            members[index].append(row)
    total = Counter()
    for node in model["nodes"]:
        if node["id"] < 3:
            audit.check("固定段は候補探索なし", node["split_search"], None)
            continue
        branch = node["path"][0]["branch"]
        columns = [index for index in range(61) if index not in (0, 19 if branch == "right" else 25)]
        expected = candidate_search(members[node["id"]], columns, model["policy"] == "S0", len(node["path"]) - 2)
        audit.check(model["model_id"] + str(node["id"]) + ":全候補最良", node["split_search"], expected)
        if expected["selected"] is not None:
            audit.check("最良候補の実分割", (node["feature"], node["threshold"], node["left"] >= 0),
                (expected["selected"]["feature"], expected["selected"]["threshold"], True))
        else:
            audit.check("不成立候補は終端", (node["left"], node["right"]), (-1, -1))
        for key in ("candidate_count", "row_eligible_count", "support_eligible_count", "selectable_count"):
            total[key] += expected[key]
        total["検査node"] += 1
    return dict(total)


# ----------------------------------------
ALGORITHM = "隣接float32境界の厳密MSE列挙"
THRESHOLD_RULE = "float32隣接異値のfloat64中点。等値は分けず、左<=/右>"
TIE_RULE = "特徴index昇順、同特徴の閾値昇順。同じ厳密改善なら最初を保持"
GAIN_RULE = "全行半重みの親MSEから行数加重子MSEを引く。金額整数と有理数で厳密比較、正改善のみ"


def parameters(depth: int, policy: str) -> dict:
    """同容量の保存引数と独自列挙の差分を独立定義する。

    引数: depth(int)は全体4又は子2、policy(str)はC0/S0。
    返り値: dictは監査側の保存引数。実学習器を呼ばない。
    """
    return {**R56.regressor_parameters(depth), "random_state": None, "legacy_random_state": 51, "randomness_used": False,
        "algorithm": ALGORITHM, "support_required": policy == "S0",
        "threshold_rule": THRESHOLD_RULE, "tie_rule": TIE_RULE, "gain_rule": GAIN_RULE}


def expected_rules() -> dict:
    """同列挙器のC/S差と固定71からの継承規約を独立保存する。

    引数: なし。
    返り値: dictは正式木と比較する規約。新L.RULESを参照しない。
    """
    result = R71.expected_rules()
    result.update({"政策深さ": {policy: 4 for policy in MODEL_POLICIES}, "政策特徴数": {policy: 61 for policy in MODEL_POLICIES},
        "random_state": None, "legacy_random_state": 51, "randomness_used": False, "子学習器": ALGORITHM,
        "未知": "旧71G0全61準備と共通可知pairを保持。入力欠落/不一致はpreflight停止し、0補完・mask・clip・余分なgateなし",
        "教師": "固定69C条件教師の同一可知pair、71G0と同じ61特徴。追加情報・追加除外なし",
        "回収教師": "確定無取引0を含むpnl5。全行重み0.5、scoreと約定支持の分母は約定既知だけ",
        "追加指標": "旧71の61列をそのまま再用。F61も既存P01/priceで独立技法票にしない",
        "取得位置の限定": "旧71と同じg。欠測を補完せず、clip/mask/余分な符号gateなし",
        "学習器": ALGORITHM, "候補閾値": THRESHOLD_RULE, "同改善": TIE_RULE, "改善": GAIN_RULE,
        "候補約定支持": {"C0": "分割候補へ約定支持制約なし", "S0": "両子がfilled unique枠60・日6・場10を満たす候補だけ"},
        "全行制約": "両子それぞれ全可知方向行60以上。重み後30を60と取り違えない",
        "学習回数": "各政策3木の四群へ独自学習を最大24回。sklearn.fit0、新分類器fit0",
        "比較の限定": "C0/S0は同じ列挙器で候補約定支持gateだけが違う。旧71G0のsklearn分割再現は要求しない"})
    columns = {"D0": [index for index in range(61) if index not in (0, 25)], "D1": [index for index in range(61) if index not in (0, 19)]}
    result["共通固定段"].update(子特徴数={policy: 59 for policy in MODEL_POLICIES},
        子特徴列index={policy: deepcopy(columns) for policy in MODEL_POLICIES})
    return result


def canonical_rows(rows: list[dict], start: float) -> tuple:
    """同71の61canonicalを独立再構成し、72の欠測説明だけを付ける。

    引数: rows(list[dict])は共通可知条件教師、start(float)は評価開始。
    返り値: tuple[list,dict]は全使用行と同六指紋/base60。新L.prepareを呼ばない。
    """
    used, training = R71.canonical_rows(rows, start, "G0")
    training["feature_missing_handling"] = "旧71G0全61特徴・同じ条件教師pair。追加情報・追加除外なし"
    return used, training


def check_raw_model(model: dict, used: list[dict], training: dict, identity: str, learner_sha: str, audit) -> dict:
    """従来の所属・全統計を固定監査で確認し、独自分割の最適性を追加する。

    引数: model(dict)は元木、used/trainingは独立教師、identity/learner_sha(str)は版、audit(Audit)は記録。
    返り値: dictは探索候補総数。旧監査へは新アルゴリズムの説明属性だけ局所射影する。
    """
    policy = model["policy"]
    audit.check("新政策", policy in MODEL_POLICIES, True)
    audit.check(identity + ":規約", model["rules"], expected_rules())
    audit.check(identity + ":全体引数", model["parameters"], parameters(4, policy))
    audit.check(identity + ":子引数", model["subtree_parameters"], parameters(2, policy))
    audit.check(identity + ":版", model["versions"], {"Python": platform.python_version(), "学習器": ALGORITHM,
        "算術": "整数/既約有理数", "sklearn.fit": 0})
    shared = [ROOT / name for name in ("scripts/方向局面分岐/学習.py", "scripts/局所帯分岐/学習.py", "scripts/回収目的分岐/学習.py",
        "scripts/波の区間分離/学習.py", "scripts/現行経路の状態分岐/学習.py", "scripts/方向と再開確認/学習.py",
        "scripts/局面強弱の複合確認/学習.py", "scripts/量と価格進行/学習.py", "scripts/現在状態と量価格/学習.py",
        "scripts/条件入口の教師/学習.py", "scripts/支持を保つ技法群/剪定.py", "scripts/取得位置と支持/学習.py")]
    audit.check(identity + ":固定純補助", model["shared_source_sha256"], {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in shared})
    audit.check(identity + ":独自子学習数", model["training"]["independent_regression_count"], sum(group["fit_performed"] for group in model["training"]["partition"].values()))
    audit.check(identity + ":sklearnfit0", model["training"]["sklearn_fit_count"], 0)
    audit.check(identity + ":厳密金額dtype", model["training"]["target_dtype"], "Decimal金額の厳密10進整数")
    audit.check(identity + ":構造の学習器", model["structure"]["child_estimator"], ALGORITHM)
    # ----------------------------------------
    # 同じ所属/容量/統計の検算だけを旧71へ委ねる。説明属性は上で新規約として検査済み。
    projected = deepcopy(model)
    projected.update(rules=R71.expected_rules(), parameters=R56.regressor_parameters(4), subtree_parameters=R56.regressor_parameters(2),
        versions={"scikit-learn": "1.9.1"}, shared_source_sha256={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in shared[:-1]})
    projected["structure"]["child_estimator"] = "DecisionTreeRegressor"
    projected["training"].pop("independent_regression_count")
    projected["training"].pop("sklearn_fit_count")
    projected["training"]["target_dtype"] = "float64"
    for group in projected["training"]["partition"].values():
        audit.check(identity + ":群の独自引数", group["fit_parameters"], parameters(2, policy))
        group["fit_parameters"] = R56.regressor_parameters(2)
    R71.check_raw_model(projected, used, training, metadata(), identity, learner_sha, audit)
    return check_optimality(model, used, audit)


def expected_pruned(raw: dict, identity: str, digest: str) -> dict:
    """支持のみの独立DPを再用し、新政策の探索履歴も親のまま保持する。

    引数: raw(dict)はC0/S0元木、identity/digest(str)は派生IDと元byteSHA。
    返り値: dictは全派生木期待値。新L.pruneを呼ばない。
    """
    result = R71.expected_pruned(raw, identity, digest)
    result["pruning"]["rules"].update(入力="新72のC0/S0生木61列。同政策の派生木へ変換し剪定時学習0",
        予測="局所policy=G0射影で固定71の61列walk/predictを再用。旧globalと元辞書は変更しない")
    result["pruning"].update(code_sha256=hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest(),
        shared_source_sha256={"scripts/取得位置と支持/学習.py": "24263093b016fd35fdfb2c11de9cbb418e13cea31fe16f41c5c71dd4bb75deb2"})
    return result


def check_pruned(model: dict, raw: dict, identity: str, digest: str, audit) -> None:
    """全派生属性・元探索記録・親統計・ID対応を独立DPと比較する。

    引数: model/raw(dict)は派生/元木、identity/digest(str)は識別、audit(Audit)は記録。
    返り値: None。新しい分割や予測を作らず保存構造を検査する。
    """
    expected = expected_pruned(raw, identity, digest)
    audit.check("派生top集合", set(model), set(expected))
    for key in expected:
        if key != "nodes":
            audit.check("派生top:" + key, model[key], expected[key])
    audit.check("派生node数", len(model["nodes"]), len(expected["nodes"]))
    for node, value in zip(model["nodes"], expected["nodes"]):
        audit.check("派生node全属性", node, value)


def expected_prediction(model: dict, calibration: dict, vectors: dict, policy: str) -> dict:
    """固定71監査の独立JSON走査と66選択で新四政策の全採否を作る。

    引数: model/calibration(dict)は過去木、vectors(dict)は当時61列、policy(str)はC0/C1/S0/S1。
    返り値: dictは全prediction。回収で方向順位を変えず最高score適格側を選ぶ。
    """
    if policy not in POLICIES or model["policy"] != policy[0] + "0":
        raise ValueError("新政策と木の不一致")
    return R71.selection_prediction(model, calibration, vectors, "E0" if policy.endswith("0") else "E1")


def expected_slots(block: dict, prepared: dict, model: dict, calibration: dict, policy: str, phase: str) -> list[dict]:
    """保存予定枠と過去木から全純判断を独立に構成する。

    引数: block/prepared/model/calibration(dict)は元予定・当時特徴・過去木、policy/phase(str)は識別。
    返り値: list[dict]は全slot。rawDI0の役割WAITは従来どおり保持する。
    """
    rows = []
    for origin in block["slots"]:
        feature = prepared[origin["slot_id"]]
        prediction = expected_prediction(model, calibration, feature["vectors"], policy) if feature["ready"] else None
        side, reason = (prediction["side"], prediction["reason"]) if prediction else (0, feature["reason"])
        if side and feature["background_direction"] == 0:
            side, reason = 0, "上位DI同値の役割未確定WAIT"
        rows.append({**{key: origin[key] for key in BINDING}, "policy": policy, "phase": phase, "model_id": model["model_id"],
            "side": side, "role": "順行" if side and side == feature["background_direction"] else "反転" if side else "待機",
            "ready": feature["ready"], "reason": reason, "atr": feature["atr"], "D": feature["D"], "feature": feature, "prediction": prediction})
    return rows


# ----------------------------------------
def run(viewer_url: str | None = None) -> dict:
    """同可知教師・厳密全候補・新十二木と実184運用を独立照合する。

    引数: viewer_url(str|None)は任意のViewer API。
    返り値: dictは公式proof。新72入力/主/学習/Engineを期待値へ呼ばず、一度だけ保存する。
    """
    destination = STUDY / "保存物確認.json"
    if destination.exists():
        raise FileExistsError("72保存物確認は作成済み。再実行しません")
    source, _, summary = A.helpers()
    audit = source.Audit()
    result, fixed, inputs = [source.read(STUDY / name) for name in ("結果.json", "固定.json", "入力台帳.json")]
    previous, proof, ledger = [source.read(path) for path in (OLD / "結果.json", OLD / "保存物確認.json", LEDGER)]
    teacher_result, teacher_proof = [source.read(TEACHER_STUDY / name) for name in ("結果.json", "保存物確認.json")]
    preflight_path = WORK.parent / "入力接続確認.json"
    old_preflight_path = TEACHER_WORK.parent / "入力接続確認.json"
    preflight, old_preflight = source.read(preflight_path), source.read(old_preflight_path)
    files = [STUDY / name for name in ("結果.json", "固定.json", "条件.json", "入力台帳.json", "一覧.resources.json")]
    files += [WORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz")]
    files += [OLD / name for name in ("結果.json", "保存物確認.json", "固定.json", "一覧.resources.json")]
    files += [OLDWORK / name for name in ("定時判断と運用.jsonl.gz", "入口先着.jsonl.gz", "実行完了.json")]
    files += [TEACHER_STUDY / name for name in ("結果.json", "保存物確認.json")]
    files += [TEACHER_WORK / "条件独立測定.jsonl.gz", LEDGER, preflight_path, old_preflight_path, source.MANIFEST, Path(__file__)]
    for meta in [*result["モデル"], *result["元学習モデル"], *result["回収集計"]]:
        files.append(ROOT / meta["path"])
    before = {path.relative_to(ROOT).as_posix(): source.sha(path) for path in files}
    for name, digest in fixed["ファイルSHA256"].items():
        audit.check("72固定:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    for name, digest in inputs["ファイルSHA256"].items():
        audit.check("72入力台帳:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("71完了台帳指定SHA", source.sha(LEDGER), LEDGER_SHA)
    audit.check("71成功監査", (proof["全件一致"], proof["不一致数"], proof["結果SHA256"]), (True, 0, source.sha(OLD / "結果.json")))
    audit.check("69成功監査", (teacher_proof["全件一致"], teacher_proof["不一致数"], teacher_proof["結果SHA256"]), (True, 0, source.sha(TEACHER_STUDY / "結果.json")))
    audit.check("71単一完了", source.read(OLDWORK / "実行完了.json")["結果SHA256"], proof["結果SHA256"])
    audit.check("71完了対象数", len(ledger["成果物SHA256"]), 246)
    for name, digest in ledger["成果物SHA256"].items():
        audit.check("71完了不変:" + name, source.sha(ROOT / name), digest)
        before[name] = digest
    audit.check("72固定bind", (result["試行"], result["固定SHA256"], result["全66場既使用"]), (72, source.sha(STUDY / "固定.json"), True))
    audit.check("新六候補集合", set(result["候補"]), {*CONTROLS, *POLICIES})
    names = ("新独自回帰学習", "新sklearnfit", "新分類器fit", "新保存木数", "新元学習木数", "新派生木数", "参照モデル数", "新独立計測", "参照独立測定", "新運用数")
    audit.check("72新処理範囲", tuple(result[name] for name in names), (24, 0, 0, 12, 6, 6, 3, 0, 4092, 184))
    audit.check("72保存対照", result["対照参照"], {"候補": list(CONTROLS), "元試行": 71, "市場再生": False})
    audit.check("72学習参照", result["学習参照"], {"元試行": 69, "モデル政策": "C0", "同じ可知集合": True, "同じ条件教師": True,
        "同じ61特徴": True, "新独自学習": True, "sklearnfit": 0, "比較": "分割候補の約定支持制約だけ", "無取引": "回収0・障壁対象外"})
    # ----------------------------------------
    # 固定71の既存61算術と成功証拠を再用する。新72入力は期待値へ呼ばない。
    reader = load_fixed(HERE.parent / "取得位置と支持/入力.py", "支持候補72監査の固定71入力")
    entries, blocks, base, extended, immediate, conditions, measured, _, inherited = reader.verified_inputs()
    audit.check("固定71入力検査", inherited, source.read(reader.PREFLIGHT)["検査"])
    audit.check("既使用66場台帳", entries, source.read(source.MANIFEST)["entries"])
    evaluated = [entry["session"] for entry in entries[20:]]
    audit.check("同46評価場", result["評価場"], evaluated)
    audit.check("学習専用20場", result["学習専用場"], [entry["session"] for entry in entries[:20]])
    old_blocks = {(row["session"], row["policy"]): row for row in source.json_rows(OLDWORK / "定時判断と運用.jsonl.gz") if row["policy"] in CONTROLS}
    audit.check("旧G92集合", (len(old_blocks), set(old_blocks)), (92, {(session, policy) for session in evaluated for policy in CONTROLS}))
    features_compared = 0
    for block in old_blocks.values():
        for slot in block["slots"]:
            audit.check("旧G当時61特徴全文", slot["feature"], extended[slot["slot_id"]])
            features_compared += 1
    expected_keys = {(slot["slot_id"], side) for block in blocks.values() for slot in block["slots"] if extended[slot["slot_id"]]["ready"] for side in (1, -1)}
    audit.check("旧4092方向の集合", (len(measured), set(measured)), (4092, expected_keys))
    checks = {"71の入力検査": inherited, "旧G保存運用": len(old_blocks), "旧G保存特徴照合": features_compared,
        "全予定枠": len(extended), "準備済み枠": sum(item["ready"] for item in extended.values()), "特徴数": 61,
        "同一61特徴を両政策へ使用": True, "61特徴SHA256": fingerprint(extended), "条件SHA256": fingerprint(conditions), "参照独立方向": len(measured)}
    audit.check("旧G全3404特徴", features_compared, 3404)
    audit.check("72事前接続検査", preflight["検査"], checks)
    audit.check("72結果入力検査", result["入力検査"], checks)
    # ----------------------------------------
    # 可知pairを再構成し、全raw統計と支持だけの剪定・派生calを別々に確認する。
    models, calibrations, model_pins, searches = {}, {}, {}, {}
    model_meta = {(meta["policy"], meta["phase"]): meta for meta in result["モデル"]}
    raw_meta = {(meta["policy"], meta["phase"]): meta for meta in result["元学習モデル"]}
    cal_meta = {(meta["policy"], meta["phase"]): meta for meta in result["回収集計"]}
    expected_meta_keys = {(policy, phase) for policy in COUNTS for phase in ("W20", "W30", "F40")}
    audit.check("六元木/六派生/cal集合", (len(result["モデル"]), len(result["元学習モデル"]), len(result["回収集計"]), set(model_meta), set(raw_meta), set(cal_meta)),
        (6, 6, 6, expected_meta_keys, expected_meta_keys, expected_meta_keys))
    fit_count = 0
    for phase in R69.phases(entries, source):
        name = phase["id"]
        rows, common = R69.common_teachers(phase, blocks, base, immediate, measured)
        audit.check("69共通教師全文", common, teacher_result["共通教師"][name])
        fields = ("全予定枠", "共通可知枠", "共通方向行", "除外枠数", "使用分類", "共通ID同順序", "方向重み")
        audit.check("72同共通教師要約", result["共通教師"][name], {**{key: common[key] for key in fields},
            "旧69共通集合SHA256": fingerprint(common), "旧69結果path": (TEACHER_STUDY / "結果.json").relative_to(ROOT).as_posix()})
        teachers = {policy: [] for policy in MODEL_POLICIES}
        for row in rows["C0"]:
            new = deepcopy(row)
            new["features"] = deepcopy(extended[row["slot_id"]]["vectors"][str(row["side"])])
            audit.check("61教師旧60全射影", {**new, "features": new["features"][:60]}, row)
            for policy in MODEL_POLICIES:
                teachers[policy].append(deepcopy(new))
        trainings = {}
        for policy, count in COUNTS.items():
            identity, raw_identity = policy + "_" + name, policy + "_" + name + "_学習"
            meta, raw_info, cal_info = model_meta[policy, name], raw_meta[policy, name], cal_meta[policy, name]
            raw, model, calibration = [source.read(ROOT / item["path"]) for item in (raw_info, meta, cal_info)]
            for item in (raw_info, meta, cal_info):
                model_pins[item["path"]] = source.sha(ROOT / item["path"])
                audit.check("72木/calSHA", model_pins[item["path"]], item["SHA256"])
            used, training = canonical_rows(teachers[policy], phase["evaluation_start"])
            trainings[policy] = training
            searches[raw_identity] = check_raw_model(raw, used, training, raw_identity, source.sha(HERE / "学習.py"), audit)
            fit_count += sum(group["fit_performed"] for group in raw["training"]["partition"].values())
            check_pruned(model, raw, identity, model_pins[raw_info["path"]], audit)
            audit.check("72剪定全文", result["剪定"][name][policy], model["pruning"])
            audit.check("派生回収全葉", calibration, R69.expected_calibration(model))
            metadata_common = {"policy": policy, "phase": name, "特徴数": count,
                "学習場": [entry["session"] for entry in phase["train"]], "評価場": [entry["session"] for entry in phase["evaluation"]], "評価開始": phase["evaluation_start"]}
            expected_raw_meta = {**metadata_common, "id": raw_identity, "path": (STUDY / "models" / (raw_identity + ".json")).relative_to(ROOT).as_posix(), "SHA256": model_pins[raw_info["path"]]}
            audit.check("元木metadata全文", raw_info, expected_raw_meta)
            audit.check("派生metadata全文", meta, {**metadata_common, "id": identity,
                "path": (STUDY / "models" / (identity + ".json")).relative_to(ROOT).as_posix(), "SHA256": model_pins[meta["path"]],
                "元path": raw_info["path"], "元SHA256": model_pins[raw_info["path"]]})
            audit.check("calmetadata全文", cal_info, {"id": identity, "policy": policy, "phase": name,
                "path": (STUDY / "models" / ("回収_" + identity + ".json")).relative_to(ROOT).as_posix(), "SHA256": model_pins[cal_info["path"]]})
            models[policy, name], calibrations[policy, name] = model, calibration
        audit.check("C/S同61全教師", teachers["C0"], teachers["S0"])
        for key in (*R71.FINGERPRINT_FIELDS, "base60_fingerprints"):
            audit.check("C/S同61六指紋:" + key, trainings["C0"][key], trainings["S0"][key])
        old_raw_path = OLD / "models" / ("G0_" + name + "_学習.json")
        old_training = source.read(old_raw_path)["training"]
        model_pins[old_raw_path.relative_to(ROOT).as_posix()] = source.sha(old_raw_path)
        for key in (*R71.FINGERPRINT_FIELDS, "base60_fingerprints"):
            audit.check("旧71同61六指紋:" + key, trainings["C0"][key], old_training[key])
    audit.check("新独自回帰学習数", result["新独自回帰学習"], fit_count)
    # ----------------------------------------
    # 実184運用だけ原配列へ照合し、独立教師4092方向は69成功指紋で再用する。
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
    audit.check("276資源全集合", set(resource_map), {(session, policy) for session in evaluated for policy in (*CONTROLS, *POLICIES)})
    audit.check("276資源一意", (len(resources), len({row["id"] for row in resources})), (276, 276))
    for row in source.read(OLD / "一覧.resources.json")["resources"]:
        if row["method_id"] in CONTROLS:
            audit.check("旧G資源全文", resource_map[row["session"], row["method_id"]], row)
    accounts, summaries, cache_pins, viewer_pins = [], [], {}, {}
    entries_matched = closed_matched = 0
    for entry in entries[20:]:
        session, phase = entry["session"], phase_by_session[entry["session"]]
        tape, cache_path, digest, input_quality = R55.load_tape(entry, source, audit)
        cache_pins[cache_path] = digest
        audit.check("69成功cachebind", digest, teacher_proof["キャッシュSHA256"][cache_path])
        for control in CONTROLS:
            operation = old_blocks[session, control]["operation"]
            account = P.account(operation, source, audit)
            account["conditions"] = operation["conditions"]
            accounts.append(account)
        audit.check("新四政策順", [block["policy"] for block in detail[session]], list(POLICIES))
        for block in detail[session]:
            policy = block["policy"]
            model_policy = policy[0] + "0"
            prepared = extended
            slots = expected_slots(blocks[session], prepared, models[model_policy, phase], calibrations[model_policy, phase], policy, phase)
            audit.check("72純全辞書", block["slots"], slots)
            audit.check("72評価phase", block["phase"], phase)
            slots_by_policy[policy].extend(slots)
            expected_conditions = {slot["slot_id"]: conditions[slot["slot_id"]] for slot in slots if slot["side"]}
            audit.check("72採用条件全文", block["conditions"], expected_conditions)
            local_labels, observed = {}, {}
            for slot in slots:
                if not slot["side"]:
                    continue
                identity = slot["slot_id"]
                record = measured[identity, slot["side"]]
                value = deepcopy(record["barrier"])
                value.update(policy=policy, role=slot["role"])
                audit.check("再用先着条件出典", value["condition"], expected_conditions[identity])
                audit.check("再用先着元時計", value["origin_slot"], {key: slot[key] for key in BINDING})
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
        print(session + " 候補支持/厳密最良/剪定/新四運用照合", flush=True)
    audit.check("新全184場別", result["場別"], summaries)
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
            audit.check("旧G対照全期", result["候補"][policy], previous["候補"][policy])
    audit.check("新採用", result["採用"], [policy for policy in POLICIES if all(result["候補"][policy][period]["同時適格"] for period in PERIODS[:2])])
    audit.check("新詳細二系列", set(result["詳細"]), {"定時判断と運用.jsonl.gz", "入口先着.jsonl.gz"})
    for name, digest in result["詳細"].items():
        audit.check("新詳細SHA:" + name, source.sha(WORK / name), digest)
    api = check_api(viewer_url, resources, accounts, source, audit)
    for name, digest in {**before, **model_pins, **cache_pins, **viewer_pins}.items():
        audit.check("監査中参照不変:" + name, source.sha(ROOT / name), digest)
    payload = {"試行": 72, "確認日時": datetime.now(source.JST).isoformat(), "全件一致": audit.bad == 0,
        "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples, "結果SHA256": source.sha(STUDY / "結果.json"),
        "本物fit再実行": False, "新主処理import": False, "新入力import": False, "新学習import": False, "Engine期待値import": False, "市場戦略再生": False,
        "既存特徴算術再構成": True, "新特徴追加": False, "全候補最適性再列挙": True, "新元学習木数": 6, "新派生木数": 6, "新運用数": 184, "再用独立教師数": len(measured),
        "同一条件実仮新規数": entries_matched, "同一条件実独立完結数": closed_matched, "厳密候補探索": searches,
        "参照SHA256": before, "モデルSHA256": model_pins, "キャッシュSHA256": cache_pins, "新Viewer約定SHA256": viewer_pins, "ViewerAPI": api,
        "検証範囲": "旧71完了246対象/旧69成功証明、同61全特徴/同可知pair/六指紋と全候補の厳密最良、六raw全node統計、支持DP/六派生cal、全純JSON採否、新184原BBO条件/注文/保護/現金/品質、六候補集計とViewer276/新4代表。",
        "限定": "固定71入力の既存61特徴算術再構成あり、新特徴の独立算法監査ではない。旧4092独立教師は成功指紋で再用し再測定/全件再監査しない。同列挙器を期待値に呼ばず全分割候補の厳密最良を別算し、支持剪定と採否・会計を検査する。既存61入力での手法比較であり、旧sklearn木の再現・未知収益・心理因果を証明しない。"}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


# ----------------------------------------
def check_api(base: str | None, resources: list[dict], accounts: list[dict], source, audit) -> dict:
    """276資源と新C0/C1/S0/S1各一代表の約定・台帳をHTTP照合する。

    引数: base(str|None)はURL、resources/accounts(list[dict])は保存値、source/auditは固定補助。
    返り値: dictはAPI範囲。未指定は未検証とする。
    """
    if not base:
        return {'実行':False,'理由':'--viewer-url未指定。API未検証、新184保存約定は全件照合'}
    query={'catalog_path':(STUDY/'一覧.resources.json').relative_to(ROOT).as_posix()}
    listing,_,_=source.fetch_json(base+'/api/resources?'+urlencode(query))
    audit.check('API276資源全集合',{row['id'] for row in listing['resources']},{row['id'] for row in resources})
    audit.check('API276資源数',len(listing['resources']),276)
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
    return {'実行':True,'全資源数':276,'新政策代表':representatives,'代表規約':'政策別最大絶対台帳観測額・場順。採否不使用'}


# ----------------------------------------
def self_test() -> dict:
    """架空教師だけで全候補最良・支持境界・保存木と採否の接続を確認する。

    引数: なし。
    返り値: dictは人工成功/照合数/不一致。新Lの呼出しはこの人工内だけで、正式期待値には使わない。
    """
    source, _, _ = A.helpers()
    audit = source.Audit()
    fixture = load_fixed(HERE.parent / "取得位置と支持/学習の人工検査.py", "支持候補72監査の架空71材料")
    learner = load_fixed(HERE / "学習.py", "支持候補72監査の人工対象")
    selector = load_fixed(HERE.parent / "適格方向の選択/選択.py", "支持候補72監査の固定66人工接続")
    initial = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    test_groups = []
    # ----------------------------------------
    # 少数の架空境界では正しい最良候補と、支持制約で選べない理由を手で定める。
    template = fixture.training_rows(True)[0]
    toy = []
    for index in range(240):
        row = deepcopy(template)
        row.update(session=f"2026-01-{1 + index % 10:02d}_" + ("Day" if index % 20 < 10 else "Night"),
            slot_id="人工境界" + str(index), side=1, filled=True, pnl5="100" if index < 120 else "-100")
        row["features"][60] = 0.0 if index < 120 else 1.0
        toy.append(row)
    best = candidate_search(toy, [60], False, 0)
    audit.check("手計算の最良候補", (best["selected"]["feature"], best["selected"]["threshold"], best["selected"]["gain"]),
        (60, 0.5, {"numerator": "10000", "denominator": "1"}))
    audit.check("同全行と約定支持ならC/S一致", candidate_search(toy, [60], True, 0), {**best, "support_required": True})
    test_groups += ["厳密MSE黄金値", "両子支持等号"]
    tied = deepcopy(toy)
    for row in tied:
        row["features"][1] = row["features"][60]
    audit.check("同改善は特徴index順", candidate_search(tied, [60, 1], False, 0)["selected"]["feature"], 1)
    test_groups.append("同点順序")
    insufficient = deepcopy(toy)
    for index, row in enumerate(insufficient):
        if 47 <= index < 120:
            row.update(filled=False, pnl5="0")
    unconstrained = candidate_search(insufficient, [60], False, 0)
    constrained = candidate_search(insufficient, [60], True, 0)
    audit.check("全行適格でも約定47はCだけ選択", (unconstrained["stop_reason"], constrained["stop_reason"]), ("分割採用", "支持適格候補なし"))
    audit.check("無取引は約定支持に含めない", unconstrained["selected"]["left"]["unique_slots"], 47)
    test_groups.append("全行とfilled支持分離")
    for rows, depth, expected in (([], 0, "空"), (toy[:119], 2, "最大深さ"), (toy[:119], 0, "全行例数不足"),
            ([{**deepcopy(row), "pnl5": "-1"} for row in toy], 0, "目的純粋")):
        record = candidate_search(rows, [60], False, depth)
        audit.check("早期停止優先:" + expected, (record["stop_reason"], record["candidate_count"], record["selected"]), (expected, 0, None))
    test_groups.append("早期停止優先")
    indistinct = deepcopy(toy)
    for index, row in enumerate(indistinct):
        row["features"][60] = 1.0 if index < 120 else 1.0 + 1e-9
    audit.check("float32同値を分けない", candidate_search(indistinct, [60], False, 0)["stop_reason"], "全行適格候補なし")
    test_groups.append("float32境界")
    # ----------------------------------------
    # 同じ架空pairをC/Sで独自学習し、期待は別列挙・固定監査で全nodeを再構成する。
    rows = fixture.training_rows(True)
    used, training = canonical_rows(rows, fixture.EVALUATION)
    learned, independent_count = {}, 0
    for policy in MODEL_POLICIES:
        identity = policy + "_人工_学習"
        model = learner.fit(rows, metadata(), fixture.EVALUATION, policy, identity)
        search = check_raw_model(model, used, training, identity, initial, audit)
        audit.check("候補最適性の検査実施", search["検査node"] > 0, True)
        independent_count += model["training"]["independent_regression_count"]
        derived = learner.prune(model, policy + "_人工", "a" * 64)
        check_pruned(derived, model, policy + "_人工", "a" * 64, audit)
        calibration = R69.expected_calibration(derived)
        for index in (0, 2, 4, 6):
            vectors = {"1": rows[index]["features"], "-1": rows[index + 1]["features"]}
            for mode in ("0", "1"):
                actual = selector.predict(derived, calibration, vectors, learner, "E" + mode)
                audit.check("全独立採否:" + policy + mode, actual, expected_prediction(derived, calibration, vectors, policy[0] + mode))
        learned[policy] = model
    test_groups += ["C全node所属統計と最良", "S全node所属統計と最良", "全派生DP", "66全予測"]
    # ----------------------------------------
    # 保存説明を壊した反例は、実装側の再fitでなく独立監査が検出しなければならない。
    corrupt = deepcopy(learned["C0"])
    selected = next(node for node in corrupt["nodes"][3:] if node["split_search"]["selected"] is not None)
    selected["split_search"]["selected"]["gain"]["numerator"] = "0"
    rejection = source.Audit()
    check_optimality(corrupt, used, rejection)
    audit.check("最適性証拠の偽造を検出", rejection.bad > 0, True)
    corrupt = deepcopy(learned["C0"])
    selected = next(node for node in corrupt["nodes"][3:] if node["split_search"]["selected"] is not None)
    selected["split_search"]["selected"]["feature"] = 0
    rejection = source.Audit()
    check_optimality(corrupt, used, rejection)
    audit.check("同点順又は候補列の偽造を検出", rejection.bad > 0, True)
    test_groups += ["最良gain反例", "選択列反例"]
    audit.check("人工中の学習コード不変", hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest(), initial)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "テスト件数": len(test_groups), "テスト群": test_groups, "人工独自学習API": 2, "人工独自子学習": independent_count,
        "sklearnfit": 0, "分類器fit": 0, "本物入力読取": False, "本物fit": 0, "市場戦略再生": False}


def main() -> None:
    """正式監査と人工を排他CLIで公開する。

    引数: CLIのrun/self_test(bool)は動作、viewer_url(str|None)はViewer。
    返り値: None。正式本物監査はroot所有で一度だけ実行する。
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
