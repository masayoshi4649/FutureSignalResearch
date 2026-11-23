"""同じ61列の条件教師を厳密列挙し、候補段階の約定支持だけを比較する。"""

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEGACY_PATH = HERE.parent / "取得位置と支持/学習.py"
LEGACY_SHA256 = "24263093b016fd35fdfb2c11de9cbb418e13cea31fe16f41c5c71dd4bb75deb2"


def load_fixed(path: Path, digest: str, name: str):
    """固定された旧純補助だけを固有名で読み込む。

    引数: path(Path)はコード、digest/name(str)は固定SHAと固有module名。
    返り値: ModuleTypeは読込結果。旧globalと本物入力を変更しない。
    """
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("固定71学習コードのSHA256差")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LEGACY = load_fixed(LEGACY_PATH, LEGACY_SHA256, "支持列挙72の固定71純補助")
BASE = LEGACY.BASE
POLICIES = {"C0": 4, "S0": 4}
FEATURE_COUNTS = {"C0": 61, "S0": 61}
POSITION_META = deepcopy(LEGACY.POSITION_META)
FIXED_NODES = deepcopy(LEGACY.FIXED_NODES)
SIDES, LABELS = LEGACY.SIDES, LEGACY.LABELS
MONEY_FIELDS, DECIMAL_PRECISION = LEGACY.MONEY_FIELDS, LEGACY.DECIMAL_PRECISION
CANONICAL_FIELDS, FINGERPRINT_FIELDS = LEGACY.CANONICAL_FIELDS, LEGACY.FINGERPRINT_FIELDS
NUMERIC_TOLERANCE = deepcopy(LEGACY.NUMERIC_TOLERANCE)
fingerprint, money, decimal_text = LEGACY.fingerprint, LEGACY.money, LEGACY.decimal_text
recovery_statistics, node_statistics = LEGACY.recovery_statistics, LEGACY.node_statistics
leaf_eligibility, support, descendants = LEGACY.leaf_eligibility, LEGACY.support, LEGACY.descendants
SHARED_SOURCE_PATHS = [*LEGACY.SHARED_SOURCE_PATHS, LEGACY_PATH]
ALGORITHM = "隣接float32境界の厳密MSE列挙"
TIE_RULE = "特徴index昇順、同特徴の閾値昇順。同じ厳密改善なら最初を保持"
THRESHOLD_RULE = "float32隣接異値のfloat64中点。等値は分けず、左<=/右>"
GAIN_RULE = "全行半重みの親MSEから行数加重子MSEを引く。金額整数と有理数で厳密比較、正改善のみ"
RULES = deepcopy(LEGACY.RULES)
RULES.update({"政策深さ": deepcopy(POLICIES), "政策特徴数": deepcopy(FEATURE_COUNTS),
    "random_state": None, "legacy_random_state": 51, "randomness_used": False, "子学習器": ALGORITHM,
    "教師": "固定69C条件教師の同一可知pair、71G0と同じ61特徴。追加情報・追加除外なし",
    "回収教師": "確定無取引0を含むpnl5。全行重み0.5、scoreと約定支持の分母は約定既知だけ",
    "追加指標": "旧71の61列をそのまま再用。F61も既存P01/priceで独立技法票にしない",
    "取得位置の限定": "旧71と同じg。欠測を補完せず、clip/mask/余分な符号gateなし",
    "未知": "旧71G0全61準備と共通可知pairを保持。入力欠落/不一致はpreflight停止し、0補完・mask・clip・余分なgateなし",
    "学習器": ALGORITHM, "候補閾値": THRESHOLD_RULE, "同改善": TIE_RULE, "改善": GAIN_RULE,
    "候補約定支持": {"C0": "分割候補へ約定支持制約なし", "S0": "両子がfilled unique枠60・日6・場10を満たす候補だけ"},
    "全行制約": "両子それぞれ全可知方向行60以上。重み後30を60と取り違えない",
    "学習回数": "各政策3木の四群へ独自学習を最大24回。sklearn.fit0、新分類器fit0",
    "比較の限定": "C0/S0は同じ列挙器で候補約定支持gateだけが違う。旧71G0のsklearn分割再現は要求しない"})
RULES["共通固定段"].update(子特徴数={policy: 59 for policy in POLICIES},
    子特徴列index={policy: LEGACY.child_indices("G0") for policy in POLICIES})
PRUNING_RULES = deepcopy(LEGACY.PRUNING_RULES)
PRUNING_RULES.update({"入力": "新72のC0/S0生木61列。同政策の派生木へ変換し剪定時学習0",
    "予測": "局所policy=G0射影で固定71の61列walk/predictを再用。旧globalと元辞書は変更しない"})


# ----------------------------------------
def child_indices(policy: str) -> dict:
    """両政策に同じDI枝別59列を与える。

    引数: policy(str)はC0又はS0。
    返り値: dict[str,list[int]]はD0で0/25、D1で0/19を除く列。
    """
    if policy not in POLICIES:
        raise ValueError("政策はC0/S0が必要")
    return LEGACY.child_indices("G0")


def feature_metadata(feature_meta: list[dict], policy: str) -> list[dict]:
    """旧71G0の61metadataを同じ規約で検査する。

    引数: feature_meta(list[dict])は61項目、policy(str)はC0/S0。
    返り値: list[dict]は深いコピー。F61を別技法票へ変更しない。
    """
    child_indices(policy)
    return LEGACY.feature_metadata(feature_meta, "G0")


def float32(values: list, feature_count: int = 61) -> list[float]:
    """既存61値の有限性・値域・共同maskを旧規約で確認する。

    引数: values(list)は61値、feature_count(int)は61固定。
    返り値: list[float]はfloat32値。未知・bool・overflowを拒否する。
    """
    if type(feature_count) is not int or feature_count != 61:
        raise ValueError("新72は61特徴固定")
    return LEGACY.float32(values, 61)


def barrier_projection(row: dict) -> dict:
    """同61列の障壁canonicalを旧純関数で作る。

    引数: row(dict)は正規化教師。
    返り値: dictは回収3値と回収終了を除く列。
    """
    return LEGACY.barrier_projection(row)


def prepare_rows(rows: list[dict], evaluation_start: float, feature_count: int = 61) -> tuple:
    """旧71G0と同じ可知pair・厳密過去・61canonicalを保持する。

    引数: rows(list[dict])は教師、evaluation_start(float)は評価開始、feature_count(int)は61。
    返り値: tuple[list[dict],dict]は同順使用行と同じ六指紋・base60指紋。
    """
    if type(feature_count) is not int or feature_count != 61:
        raise ValueError("新72の教師は61列固定")
    used, training = LEGACY.prepare_rows(rows, evaluation_start, 61)
    training["feature_missing_handling"] = "旧71G0全61特徴・同じ条件教師pair。追加情報・追加除外なし"
    return used, training


def regressor_parameters(depth: int, policy: str = "C0") -> dict:
    """旧容量に独自列挙と候補支持の規約を付加する。

    引数: depth(int)は全体4又は子2、policy(str)はC0/S0。
    返り値: dictは保存用パラメータ。sklearnへ渡す引数ではない。
    """
    child_indices(policy)
    if depth not in (2, 4):
        raise ValueError("深さは全体4又は子2が必要")
    return {**LEGACY.regressor_parameters(depth), "random_state": None, "legacy_random_state": 51,
        "randomness_used": False, "algorithm": ALGORITHM,
        "support_required": policy == "S0", "threshold_rule": THRESHOLD_RULE,
        "tie_rule": TIE_RULE, "gain_rule": GAIN_RULE}


def fraction_record(value: Fraction) -> dict:
    """厳密有理数をJSONの十進整数文字列へ写す。

    引数: value(Fraction)はMSE改善の正本。
    返り値: dict[str,str]は既約numerator/正denominator。
    """
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def target_integers(rows: list[dict]) -> tuple:
    """Decimal金額を丸めず一つの10進整数単位へ変換する。

    引数: rows(list[dict])は正規化された全使用行。
    返り値: tuple[list[int],int]は金額整数と分母10の累乗。Decimalの既定精度に依存しない。
    """
    values = [money(row["pnl5"]) for row in rows]
    places = max((max(0, -value.as_tuple().exponent) for value in values), default=0)
    scale = 10 ** places
    integers = []
    for value in values:
        sign, digits, exponent = value.as_tuple()
        coefficient = int("".join(str(digit) for digit in digits))
        integers.append((-1 if sign else 1) * coefficient * 10 ** (exponent + places))
    return integers, scale


def support_counts(rows: list[dict], indexes: list[int]) -> dict:
    """所属行から約定既知のunique枠・日・場を独立に数える。

    引数: rows(list[dict])は全教師、indexes(list[int])は所属行番号。
    返り値: dictは全方向行数と約定支持三件数・supported。
    """
    filled = [rows[index] for index in indexes if rows[index]["filled"]]
    unique = len({(row["session"], row["slot_id"]) for row in filled})
    days = len({row["session"][:10] for row in filled})
    sessions = len({row["session"] for row in filled})
    return {"direction_rows": len(indexes), "unique_slots": unique, "days": days, "sessions": sessions,
        "supported": unique >= 60 and days >= 6 and sessions >= 10}


def move_counter(left: Counter, right: Counter, key: object) -> None:
    """境界を一行進める際の集合多重度を更新する。

    引数: left/right(Counter)は左右多重集合、key(object)は枠・日・場の識別。
    返り値: None。0件となった右keyは消し、lenをunique数に保つ。
    """
    left[key] += 1
    right[key] -= 1
    if right[key] == 0:
        del right[key]


def choose_split(rows: list[dict], x: list[list[float]], targets: list[int], scale: int,
                 indexes: list[int], projection: list[int], depth: int, policy: str, metadata: list[dict]) -> tuple:
    """全隣接異値境界を列挙し、支持以外は同じ厳密MSE改善で選ぶ。

    引数: rows/x/targets(list)は全教師・float32・金額整数、scale(int)は金額分母、indexes/projection(list[int])は所属/子候補列、
        depth(int)は子内深さ、policy(str)はC0/S0、metadata(list[dict])は61列。
    返り値: tuple[dict,list[int],list[int]]は保存探索記録と選択左右の元順行番号。非分割は左右空。
    """
    record = {"candidate_count": 0, "row_eligible_count": 0, "support_eligible_count": 0,
        "selectable_count": 0, "support_required": policy == "S0", "stop_reason": None, "selected": None}
    count = len(indexes)
    reason = ("空" if not indexes else "最大深さ" if depth >= 2 else "全行例数不足" if count < 120
        else "目的純粋" if len({targets[index] for index in indexes}) == 1 else None)
    if reason:
        record["stop_reason"] = reason
        return record, [], []
    total = sum(targets[index] for index in indexes)
    best_num, best_den, best_feature, best_threshold = 0, 1, None, None
    for feature in projection:
        ordered = sorted(indexes, key=lambda index: (x[index][feature], index))
        left_sets = [Counter(), Counter(), Counter()]
        right_sets = [Counter(), Counter(), Counter()]
        for index in ordered:
            row = rows[index]
            if row["filled"]:
                for counter, key in zip(right_sets, ((row["session"], row["slot_id"]), row["session"][:10], row["session"])):
                    counter[key] += 1
        left_sum = 0
        for position, index in enumerate(ordered[:-1], 1):
            left_sum += targets[index]
            row = rows[index]
            if row["filled"]:
                for lc, rc, key in zip(left_sets, right_sets,
                        ((row["session"], row["slot_id"]), row["session"][:10], row["session"])):
                    move_counter(lc, rc, key)
            low, high = x[index][feature], x[ordered[position]][feature]
            if low == high:
                continue
            record["candidate_count"] += 1
            if min(position, count - position) < 60:
                continue
            record["row_eligible_count"] += 1
            supported = all(len(counters[0]) >= 60 and len(counters[1]) >= 6 and len(counters[2]) >= 10
                for counters in (left_sets, right_sets))
            record["support_eligible_count"] += int(supported)
            if policy == "S0" and not supported:
                continue
            record["selectable_count"] += 1
            numerator = (count * left_sum - position * total) ** 2
            denominator = count * count * position * (count - position)
            if numerator * best_den > best_num * denominator:
                best_num, best_den = numerator, denominator
                best_feature, best_threshold = feature, low / 2.0 + high / 2.0
    if best_feature is None:
        record["stop_reason"] = ("全行適格候補なし" if not record["row_eligible_count"] else
            "支持適格候補なし" if policy == "S0" and not record["support_eligible_count"] else "正改善なし")
        return record, [], []
    left = [index for index in indexes if x[index][best_feature] <= best_threshold]
    right = [index for index in indexes if x[index][best_feature] > best_threshold]
    record.update(stop_reason="分割採用", selected={"feature": best_feature, "feature_id": metadata[best_feature]["id"],
        "threshold": best_threshold, "gain": fraction_record(Fraction(best_num, best_den * scale * scale)),
        "left": support_counts(rows, left), "right": support_counts(rows, right)})
    return record, left, right


# ----------------------------------------
def walk(model: dict, values: list) -> tuple:
    """同61列の生木と派生木を固定71の純走査へ局所射影する。

    引数: model(dict)はC0/S0木、values(list)は61列。
    返り値: tuple[int,list[dict]]は葉と全path。旧globalとmodelは変更しない。
    """
    child_indices(model.get("policy"))
    return LEGACY.walk({**model, "policy": "G0"}, values)


def predict(model: dict, vectors: dict) -> dict:
    """従来の先着score・資格・未知/同点WAITをそのまま返す。

    引数: model(dict)はC0/S0木、vectors(dict)は両61列又は両空。
    返り値: dictは66選択と互換のprior。回帰値で方向を順位付けしない。
    """
    child_indices(model.get("policy"))
    return LEGACY.predict({**model, "policy": "G0"}, vectors)


def fit(rows: list[dict], feature_meta: list[dict], evaluation_start: float, policy: str, model_id: str) -> dict:
    """同四群へ厳密列挙を適用し、候補の約定支持制約だけを比較する。

    引数: rows(list[dict])は過去教師、feature_meta(list[dict])は61metadata、evaluation_start(float)は評価開始、
        policy(str)はC0/S0、model_id(str)は生木ID。
    返り値: dictはschema1の全node/探索記録/支持/回収/同教師指紋。sklearn.fitは呼ばない。
    """
    if policy not in POLICIES or not isinstance(model_id, str) or not model_id:
        raise ValueError("政策又はmodel_idが不正")
    meta = feature_metadata(feature_meta, policy)
    used, training = prepare_rows(rows, evaluation_start)
    x = [float32(row["features"]) for row in used]
    targets, scale = target_integers(used)
    nodes = [{"id": item["id"], "feature": item["index"], "feature_id": item["feature"],
        "family": meta[item["index"]]["family"], "threshold": item["threshold"],
        "left": 1 if item["id"] == 0 else None, "right": 2 if item["id"] == 0 else None,
        "split_search": None} for item in FIXED_NODES]
    membership = {0: list(range(len(used))), 1: [], 2: []}

    def build(indexes: list[int], projection: list[int], depth: int) -> int:
        """一つの学習子を深さ優先で作り、各停止理由も保存する。

        引数: indexes/projection(list[int])は所属行/候補列、depth(int)は子内深さ。
        返り値: intは追加した子木の根ID。元行順と同点順を保持する。
        """
        index = len(nodes)
        search, left, right = choose_split(used, x, targets, scale, indexes, projection, depth, policy, meta)
        node = {"id": index, "feature": -2, "feature_id": None, "family": None,
            "threshold": -2.0, "left": -1, "right": -1, "split_search": search}
        nodes.append(node)
        membership[index] = indexes
        if search["selected"] is not None:
            selected = search["selected"]
            feature = selected["feature"]
            node.update(feature=feature, feature_id=meta[feature]["id"], family=meta[feature]["family"], threshold=selected["threshold"])
            node.update(left=build(left, projection, depth + 1), right=build(right, projection, depth + 1))
        return index

    training["partition"] = {}
    child_parameters = regressor_parameters(2, policy)
    for d in (0, 1):
        route, flag = ("R", 25) if d == 0 else ("T", 19)
        projection = child_indices(policy)[f"D{d}"]
        membership[1 + d] = [i for i in range(len(used)) if int(x[i][0] > 0.0) == d]
        for v in (0, 1):
            indexes = [i for i in membership[1 + d] if int(x[i][flag] > 0.5) == v]
            offset = build(indexes, projection, 0)
            nodes[1 + d]["left" if v == 0 else "right"] = offset
            ids = [{key: used[i][key] for key in ("session", "slot_id", "side")} for i in indexes]
            training["partition"][f"D{d}_V{v}"] = {"d": d, "v": v, "route": route, "policy": policy,
                "excluded_feature_indices": [0, flag], "child_feature_indices": list(projection),
                "direction_rows": len(indexes), "pair_unique": len({(used[i]["session"], used[i]["slot_id"]) for i in indexes}),
                "days": len({used[i]["session"][:10] for i in indexes}), "sessions": len({used[i]["session"] for i in indexes}),
                "row_ids_sha256": fingerprint(ids), "fit_performed": bool(indexes), "root": offset,
                "node_count": len(nodes) - offset, "fit_parameters": deepcopy(child_parameters)}
    paths = LEGACY.paths_for(nodes, meta)
    for node in nodes:
        selected = [used[i] for i in membership[node["id"]]]
        path = paths[node["id"]]
        ids = [{key: row[key] for key in ("session", "slot_id", "side")} for row in selected]
        node.update(path=path, methods=sorted({part["method"] for part in path}), families=sorted({part["family"] for part in path}),
            training_ids_sha256=fingerprint(ids), impurity_kind="squared_error", **node_statistics(selected, path))
    structure = {"kind": "fixed_direction_current_episode", "fixed_nodes": deepcopy(FIXED_NODES), "child_depth": 2,
        "child_features": 59, "child_feature_indices": child_indices(policy),
        "excluded_feature_indices": {"D0": [0, 25], "D1": [0, 19]}, "feature_count": 61,
        "max_depth": 4, "fixed_mse_optimized": False, "child_estimator": ALGORITHM, "target": "pnl5"}
    training.update(target_dtype="Decimal金額の厳密10進整数", independent_regression_count=sum(bool(g["fit_performed"]) for g in training["partition"].values()),
        sklearn_fit_count=0)
    result = {"schema_version": 1, "policy": policy, "model_id": model_id, "feature_meta": meta,
        "feature_meta_sha256": fingerprint(meta), "parameters": regressor_parameters(4, policy),
        "subtree_parameters": child_parameters, "structure": structure, "rules": deepcopy(RULES),
        "versions": {"Python": platform.python_version(), "学習器": ALGORITHM, "算術": "整数/既約有理数", "sklearn.fit": 0},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "shared_source_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in SHARED_SOURCE_PATHS},
        "training": training, "nodes": nodes,
        "interpretation": "同61情報・同可知pair・同容量。独自列挙C0/S0の違いは候補両子の約定支持制約だけ。旧71sklearn再現や費用後改善は主張しない"}
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


# ----------------------------------------
def prune(model: dict, model_id: str, source_sha256: str) -> dict:
    """旧71の支持のみの両側統合を同政策の61列へ適用する。

    引数: model(dict)はC0/S0生木、model_id(str)は派生ID、source_sha256(str)は元JSON byte SHA。
    返り値: dictは親統計・探索記録を保つ派生木。剪定時は新学習0、旧global変更0。
    """
    child_indices(model.get("policy"))
    result = LEGACY.prune({**model, "policy": "G0"}, model_id, source_sha256)
    result["policy"] = model["policy"]
    result["pruning"].update(rules=deepcopy(PRUNING_RULES), source_model_content_sha256=fingerprint(model),
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        shared_source_sha256={LEGACY_PATH.relative_to(ROOT).as_posix(): LEGACY_SHA256})
    return result


def synthetic_inputs() -> tuple:
    """固定71の架空材料だけから同61列の検査入力を作る。

    引数: なし。
    返り値: tuple[list[dict],list[dict],float,ModuleType]は800方向行・metadata・評価開始・人工純補助。
        実市場・実モデル・実教師を開かず、旧人工のfitも起動しない。
    """
    path = HERE.parent / "取得位置と支持/学習の人工検査.py"
    module = load_fixed(path, "15964a47d5937890c7174a74f0b4cbea8be511c0b10e6f4f1017cca0b3c70aa7", "支持72の固定71架空材料")
    return module.training_rows(True), deepcopy(module.META61), module.EVALUATION, module


def search_fixture(count: int = 240) -> tuple:
    """候補支持の境界を検査する、実入力と無関係な所属材料を作る。

    引数: count(int)は行数。
    返り値: tuple[list[dict],list[list[float]],list[int]]は約定行・61列・整数金額の架空材料。
    """
    rows, x, targets = [], [], []
    for index in range(count):
        category = index % 10
        day = 1 + (category if category < 6 else category - 6)
        session = f"2026-01-{day:02d}_" + ("Day" if category < 6 else "Night")
        rows.append({"session": session, "slot_id": "人工" + str(index), "side": 1, "filled": True})
        values = [0.0] * 61
        values[10] = values[60] = float(index >= count // 2)
        x.append(values)
        targets.append(-100 if index < count // 2 else 100)
    return rows, x, targets


def _self_test() -> dict:
    """人工の期待式と旧純補助接続で各契約を確認する。

    引数: なし。
    返り値: dictは照合件数と差の一覧。対象の独自fitだけを架空データへ実行しsklearn.fitは0。
    """
    rows, metadata, evaluation, material = synthetic_inputs()
    failures, checks, cases = [], 0, []
    old_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (LEGACY_PATH, LEGACY.LEGACY_PATH, LEGACY.PRUNING_PATH)}

    def check(value: bool, name: str) -> None:
        """人工の真偽を積み上げ、失敗を短い識別名で保存する。

        引数: value(bool)は期待との一致、name(str)は照合名。
        返り値: None。
        """
        nonlocal checks
        checks += 1
        if not value:
            failures.append(name)

    def rejects(function, name: str) -> None:
        """不正な人工入力がValueErrorで拒否されることを確認する。

        引数: function(Callable)は引数なし呼出し、name(str)は照合名。
        返り値: None。
        """
        try:
            function()
        except ValueError:
            check(True, name)
        else:
            check(False, name)

    def shape(model: dict) -> list:
        """識別・回収統計を除いた分岐構造だけを取り出す。

        引数: model(dict)は人工木。
        返り値: list[tuple]はnode ID・特徴・閾値・左右の順序付き値。
        """
        return [(node["id"], node["feature"], node["threshold"], node["left"], node["right"]) for node in model["nodes"]]

    cases.append("政策と61metadata")
    check(RULES["random_state"] is None and RULES["legacy_random_state"] == 51 and RULES["randomness_used"] is False,
        "top規約も乱数不使用")
    check(RULES["子学習器"] == ALGORITHM, "旧sklearn学習器名を残さない")
    for policy in POLICIES:
        check(regressor_parameters(2, policy)["random_state"] is None, policy + "子引数乱数不使用")
        check(feature_metadata(metadata, policy) == metadata, policy + "metadata")
        check(len(child_indices(policy)["D0"]) == len(child_indices(policy)["D1"]) == 59, policy + "子59")
    rejects(lambda: feature_metadata(metadata[:60], "C0"), "metadata60拒否")
    rejects(lambda: feature_metadata(metadata, "G0"), "旧policy拒否")
    rejects(lambda: float32(rows[0]["features"], 60), "60列指定拒否")
    for bad in (None, True, float("nan"), float("inf"), 1e100):
        vector = deepcopy(rows[0]["features"]); vector[60] = bad
        rejects(lambda vector=vector: float32(vector), "g不正拒否:" + str(bad))
    cases.append("同canonical六指紋と未来pair")
    used, training = prepare_rows(rows, evaluation)
    old_used, old_training = LEGACY.prepare_rows(rows, evaluation, 61)
    check(used == old_used, "全61canonical同値")
    for key in FINGERPRINT_FIELDS:
        check(training[key] == old_training[key], "教師指紋:" + key)
    check(training["base60_fingerprints"] == old_training["base60_fingerprints"], "base60保持")
    rejects(lambda: prepare_rows(rows[:-1], evaluation), "片側欠落拒否")
    future = deepcopy(rows); future[0]["recovery_end_time"] = evaluation
    rejects(lambda: prepare_rows(future, evaluation), "評価開始等号拒否")

    cases.append("同値候補と正改善")
    sample, x, target = search_fixture()
    selected, left, right = choose_split(sample, x, target, 1, list(range(240)), [10, 60], 0, "C0", metadata)
    check(selected["selected"]["feature"] == 10, "同改善の小index")
    check(selected["selected"]["gain"] == {"numerator": "10000", "denominator": "1"}, "厳密MSE改善")
    check(selected["candidate_count"] == selected["row_eligible_count"] == selected["support_eligible_count"] == 2, "全候補数")
    check(left == list(range(120)) and right == list(range(120, 240)), "元順左右")
    constant_x = [[0.0] * 61 for _ in sample]
    stopped, _, _ = choose_split(sample, constant_x, target, 1, list(range(240)), [10, 60], 0, "C0", metadata)
    check(stopped["candidate_count"] == 0 and stopped["stop_reason"] == "全行適格候補なし", "全特徴同値は分けない")
    cases.append("近接float32と中点")
    low = float32([*rows[0]["features"][:60], 1.0])[60]
    collapsed = float32([*rows[0]["features"][:60], 1.0 + 2 ** -25])[60]
    high = float32([*rows[0]["features"][:60], 1.0 + 2 ** -23])[60]
    check(low == collapsed < high, "float32同値と隣接")
    for index, vector in enumerate(x):
        vector[60] = low if index < 120 else high
    adjacent, _, _ = choose_split(sample, x, target, 1, list(range(240)), [60], 0, "S0", metadata)
    check(adjacent["selected"]["threshold"] == 1.0 + 2 ** -24, "中点はfloat64")
    check(adjacent["candidate_count"] == 1, "近接境界一つ")
    cases.append("全行60と支持60境界")
    s120, x120, y120 = search_fixture(120)
    boundary, _, _ = choose_split(s120, x120, y120, 1, list(range(120)), [60], 0, "S0", metadata)
    check(boundary["selected"] is not None and boundary["selected"]["left"]["unique_slots"] == 60, "両子60可")
    short, _, _ = choose_split(s120[:119], x120[:119], y120[:119], 1, list(range(119)), [60], 0, "C0", metadata)
    check(short["stop_reason"] == "全行例数不足" and short["candidate_count"] == 0, "119行stop")
    cases.append("unique重複と日場境界")
    duplicate = deepcopy(s120)
    for row in duplicate[:60]:
        row["slot_id"] = "重複"; row["session"] = "2026-01-01_Day"
    bad_support, _, _ = choose_split(duplicate, x120, y120, 1, list(range(120)), [60], 0, "S0", metadata)
    check(bad_support["stop_reason"] == "支持適格候補なし", "60方向行を60枠としない")
    support60 = support_counts(s120, list(range(60)))
    check(support60 == {"direction_rows": 60, "unique_slots": 60, "days": 6, "sessions": 10, "supported": True}, "6日10場境界")
    for mode in ("日", "場"):
        limited = deepcopy(s120)
        for i, row in enumerate(limited):
            row["session"] = f"2026-01-{1 + i % 5:02d}_" + ("Day" if i % 2 else "Night") if mode == "日" else f"2026-01-{1 + min(i % 9, 5):02d}_場{i % 9}"
        check(not support_counts(limited, list(range(60)))["supported"], mode + "不足")
    cases.append("支持制約で次善候補")
    alternative, ax, ay = search_fixture()
    for i, row in enumerate(alternative):
        row["filled"] = not 30 <= i < 80
        ax[i][60] = float(i >= 80)
        ay[i] = 1000 if i < 30 else 0 if i < 80 else -100
    unrestricted, _, _ = choose_split(alternative, ax, ay, 1, list(range(240)), [10, 60], 0, "C0", metadata)
    constrained, _, _ = choose_split(alternative, ax, ay, 1, list(range(240)), [10, 60], 0, "S0", metadata)
    check(unrestricted["selected"]["feature"] == 60 and constrained["selected"]["feature"] == 10, "不適格最良を除き次善採用")
    check(unrestricted["row_eligible_count"] == 2 and unrestricted["support_eligible_count"] == 1, "制約別候補件数")
    cases.append("111約定方向行では両子60不可")
    only111 = deepcopy(sample)
    for i, row in enumerate(only111):
        row["filled"] = i < 111
    no_split, _, _ = choose_split(only111, x, target, 1, list(range(240)), [60], 0, "S0", metadata)
    check(no_split["selected"] is None and no_split["stop_reason"] == "支持適格候補なし", "111約定stop")
    cases.append("空純粋深さと改善なし")
    for indexes, depth, values, reason in (([], 0, target, "空"), (list(range(240)), 2, target, "最大深さ"),
            (list(range(240)), 0, [0] * 240, "目的純粋")):
        result, _, _ = choose_split(sample, x, values, 1, indexes, [60], depth, "C0", metadata)
        check(result["stop_reason"] == reason and result["candidate_count"] == 0, reason)
    alternating = [1 if i % 2 else -1 for i in range(240)]
    zero_gain, _, _ = choose_split(sample, x, alternating, 1, list(range(240)), [60], 0, "C0", metadata)
    check(zero_gain["stop_reason"] == "正改善なし", "同平均は分割しない")
    cases.append("微小金額と厳密改善")
    tiny_rows = [{"pnl5": "1e-35"}, {"pnl5": "-1e-35"}, {"pnl5": "1e30"}]
    integers, unit = target_integers(tiny_rows)
    check([Fraction(value, unit) for value in integers] == [Fraction(money(row["pnl5"])) for row in tiny_rows], "金額桁落ちなし")
    tiny, _, _ = choose_split(sample, x, [-1 if i < 120 else 1 for i in range(240)], 10 ** 35,
        list(range(240)), [60], 0, "C0", metadata)
    check(tiny["selected"]["gain"] == fraction_record(Fraction(1, 10 ** 70)), "正の微小改善を丸めない")

    cases.append("全木学習と全node所属")
    original = fingerprint(rows)
    models = {policy: fit(rows, metadata, evaluation, policy, policy + "_人工_学習") for policy in POLICIES}
    for policy, model in models.items():
        check(model["training"]["sklearn_fit_count"] == 0 and model["training"]["independent_regression_count"] == 4, policy + "独自四群")
        for key in FINGERPRINT_FIELDS:
            check(model["training"][key] == old_training[key], policy + "全教師同値:" + key)
        counts = Counter()
        for row in rows:
            leaf, path = walk(model, row["features"])
            for node_id in [part["node"] for part in path] + [leaf]:
                counts[node_id] += 1
            check(model["nodes"][leaf]["path"] == path, policy + "保存path")
        for node in model["nodes"]:
            check(node["direction_rows"] == counts[node["id"]], policy + "全node所属")
            check((node["split_search"] is None) == (node["id"] < 3), policy + "固定探索なし")
            if node["split_search"] is not None and node["split_search"]["selected"]:
                picked = node["split_search"]["selected"]
                check(picked["threshold"] == node["threshold"] and picked["feature"] == node["feature"], policy + "採用記録")
    check(shape(models["C0"]) == shape(models["S0"]), "全候補支持ありなら同じ構造")
    check(fingerprint(rows) == original, "入力非変更")
    cases.append("売買鏡像と目的反転")
    mirrored = deepcopy(rows)
    for row in mirrored:
        row["side"] = -row["side"]
    mirror = fit(mirrored, metadata, evaluation, "S0", "S0_鏡像")
    check(shape(mirror) == shape(models["S0"]), "符号正規化鏡像")
    reversed_targets = [-value for value in target]
    opposite, _, _ = choose_split(sample, x, reversed_targets, 1, list(range(240)), [60], 0, "S0", metadata)
    check(opposite["selected"]["gain"] == adjacent["selected"]["gain"], "金額符号反転の改善不変")
    cases.append("無取引と空四群")
    unfilled = deepcopy(rows)
    for row in unfilled:
        row.update(filled=False, outcome="無取引", pnl0="0", pnl5="0", pnl10="0")
        row["features"][19] = row["features"][25] = 0.0
    empty = fit(unfilled, metadata, evaluation, "S0", "S0_無取引")
    check(len(empty["nodes"]) == 7 and empty["training"]["independent_regression_count"] == 2, "空でも固定四群")
    check(all(node["score"] is None for node in empty["nodes"]), "無約定score未知")
    empty_prediction = predict(empty, {"1": unfilled[0]["features"], "-1": unfilled[1]["features"]})
    check(empty_prediction["side"] == 0 and empty_prediction["reason"] == "未学習枝WAIT", "未約定未知WAIT")
    check(predict(empty, {"1": [], "-1": []})["reason"] == "特徴未準備WAIT", "未準備と無取引分離")
    cases.append("支持剪定と親統計")
    pruned = {}
    for policy, model in models.items():
        before = fingerprint(model)
        derived = prune(model, policy + "_人工", "a" * 64)
        pruned[policy] = derived
        check(derived["policy"] == policy and derived["pruning"]["fit_count"] == 0, policy + "同政策剪定")
        check(derived["pruning"]["source_model_content_sha256"] == before and fingerprint(model) == before, policy + "元非変更")
        for node in derived["nodes"]:
            source = model["nodes"][node["source_node_id"]]
            for key in ("recovery", "recovery_filled", "score", "leaf_support", "regression_value", "impurity", "split_search"):
                check(node[key] == source[key], policy + "親統計保持:" + key)
        rejects(lambda derived=derived: prune(derived, "二重", "a" * 64), policy + "二重剪定拒否")
    for case in ("nested", "local_merge", "fixed_insufficient"):
        source = material.projected_source("G0", case)
        source.update(policy="C0")
        for group in source["training"]["partition"].values():
            group["policy"] = "C0"
        expected = LEGACY.prune({**source, "policy": "G0"}, "C0_手作り", "b" * 64)
        actual = prune(source, "C0_手作り", "b" * 64)
        check(actual["nodes"] == expected["nodes"], "両側祖先統合:" + case)
        check(actual["training"] == source["training"], "学習partition保持:" + case)
    cases.append("純予測と66選択と主接続")
    main_path = HERE / "検証.py"
    main = load_fixed(main_path, hashlib.sha256(main_path.read_bytes()).hexdigest(), "支持72の人工主接続")
    source_slot = {"session": "2026-01-01_Day", "slot_id": "人工予定", "scheduled": 100.0, "time": 100.0, "line": 1}
    for policy, model in pruned.items():
        vectors = {"1": rows[0]["features"], "-1": rows[1]["features"]}
        prior = predict(model, vectors)
        check(prior == LEGACY.predict({**model, "policy": "G0"}, vectors), policy + "旧purepredict同値")
        calibration = material.CAL.calibration_for(model)
        feature = {"ready": True, "reason": "準備", "vectors": vectors, "background_direction": 1, "atr": 50.0, "D": 50}
        for suffix in ("0", "1"):
            selection = material.SELECTOR.predict(model, calibration, vectors, sys.modules[__name__], "E" + suffix)
            slots = main.slots_for({"slots": [source_slot]}, {"人工予定": feature}, model, calibration,
                sys.modules[__name__], material.SELECTOR, policy[0] + suffix, "人工")
            check(slots[0]["prediction"] == selection, policy + suffix + "主prediction接続")
            check(slots[0]["model_id"] == model["model_id"] and slots[0]["phase"] == "人工", policy + suffix + "metadata")
    cases.append("旧固定とsklearnfit非使用")
    for path, digest in old_hashes.items():
        check(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, "旧固定不変:" + Path(path).name)
    return {"成功": not failures, "人工成功": not failures, "照合項目数": checks, "不一致数": len(failures), "不一致": failures,
        "テスト件数": len(cases), "テスト": cases, "実入力読取": False, "sklearnfit": 0, "市場再生": False}


def self_test() -> dict:
    """架空教師と手作り所属だけで厳密分割・支持境界・剪定を確認する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致/テスト件数。実入力・sklearn.fit・市場再生は0。
    """
    return _self_test()


if __name__ == "__main__":
    artificial = self_test()
    print(json.dumps(artificial, ensure_ascii=False, indent=2, allow_nan=False))
    if not artificial["人工成功"]:
        raise SystemExit(1)
