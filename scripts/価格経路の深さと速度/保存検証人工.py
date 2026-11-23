"""59の独立幾何8値・38列教師/木/採否を人工だけで検査する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工対象を固有名で読み、旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。実教師・本物モデルは開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(HERE / "保存検証.py", "深さ速度保存監査の人工対象")


def artificial_rows(source) -> list[dict]:
    """旧30の人工形式へ独立8値を付け、新列による子分岐を必ず検査する。

    引数: source(ModuleType)は固定暦の純補助。
    返り値: list[dict]は20人工場/800方向。実データの代理として保存しない。
    """
    rows = A.R56.artificial_rows(source)
    for index, row in enumerate(rows):
        pair = index // 2
        row["features"][1:17] = [0.] * 16
        row["features"] += [1, 1, 0, -1., 0., 0., 1, 1, 0, -1., 0., 0.]
        tail = [(pair // 3 % 9) / 8, (pair // 7 % 5) / 4, (pair % 7 - 3) / 6, row["side"] * .2,
                (pair // 5 % 7) / 6, (pair // 13 % 9) / 8, (pair // 3 % 9 - 4) / 8, row["side"] * (pair // 11 % 5 - 2) / 2]
        row["features"] += tail
        target = 2000 * tail[4] + 100 * tail[5] + row["side"] * 7.5
        row.update(pnl0=target + 100, pnl5=target, pnl10=target - 100)
    return rows


def self_test() -> dict:
    """紙上SOURCEと人工回帰木で新算術・旧射影・未知境界を検査する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物fitと市場読取は0。
    """
    source, _, _ = A.A.helpers()
    audit = source.Audit()
    feature = load(HERE / "特徴.py", "深さ速度人工の新特徴")
    fixtures = load(HERE / "特徴の人工検査.py", "深さ速度人工の紙上材料")
    learner = load(HERE / "学習.py", "深さ速度人工の新学習")
    recovery = load(HERE.parent / "独立追尾回収/回収集計.py", "深さ速度人工の固定回収")
    audit.check("全38metadata", feature.FEATURES, A.feature_metadata())
    samples = [fixtures.t_changes(), fixtures.r_changes(), {}, {24: fixtures.candle(115)}]
    for changes in samples:
        slot, frames = fixtures.fixture(changes, 24)
        base = A.A.expected_feature(slot, frames)
        old = A.R58.expected_feature(base, slot, frames)
        expected = A.expected_feature(old, slot, frames)
        actual = feature.extract(slot, frames)
        audit.check("全38辞書/旧30/幾何出典", actual, expected)
        audit.check("旧58全文を保持する射影", feature.control_projection(actual), old)
        for side in ("1", "-1"):
            audit.check("旧30prefix保持", expected["vectors"][side][:30], old["vectors"][side])
    slot, frames = fixtures.fixture(fixtures.t_changes(), 24)
    old = A.R58.expected_feature(A.A.expected_feature(slot, frames), slot, frames)
    value = A.expected_feature(old, slot, frames)
    audit.check("紙上T四値", value["geometry"]["1"]["T"]["values"], [.28, .12, .02, .48])
    audit.check("最初極値出典", (value["geometry"]["1"]["T"]["u_min_source"]["index"], value["geometry"]["1"]["T"]["u_max_source"]["index"]), (12, 16))
    slot, frames = fixtures.fixture(fixtures.r_changes(), 24)
    old = A.R58.expected_feature(A.A.expected_feature(slot, frames), slot, frames)
    value = A.expected_feature(old, slot, frames)
    audit.check("紙上R四値と実方向", value["geometry"]["-1"]["R"]["values"], [.2, .12, .04, .36])
    # ----------------------------------------
    # 継続観測、出生n0、未IDの定義0を同じ使用方向行分母で数える。
    examples, group_rows = {}, []
    changes = fixtures.t_changes(25)
    changes[25] = fixtures.candle(140)
    for identity, sample, current in (("継続", fixtures.t_changes(), 24), ("出生", changes, 25), ("未ID", {}, 24)):
        slot, frames = fixtures.fixture(sample, current)
        old = A.R58.expected_feature(A.A.expected_feature(slot, frames), slot, frames)
        item = A.expected_feature(old, slot, frames)
        item["vectors"]["1"][0], item["vectors"]["1"][17] = 1., 0
        examples[identity] = item
        group_rows.append({"slot_id": identity, "side": 1, "features": item["vectors"]["1"]})
    distribution = A.geometry_distribution(group_rows, examples)
    observed = distribution["Z0_a1"]
    audit.check("追加分布の全方向分母", observed["方向行"], 3)
    audit.check("形成/未ID/取消/出生/uniqueID分母", {k: v for k, v in observed["T"].items() if k != "列"},
        {"形成あり": 2, "形成なし": 1, "取消あり": 1, "出生足": 1, "形成ID数": 2})
    audit.check("未IDの0を含む深さ列", observed["T"]["列"]["F31"],
        {"数値数": 3, "異なる値": 2, "最小": 0, "最大": .28, "ゼロ": 2})
    audit.check("出生n0の速度を既知0とする", examples["出生"]["geometry"]["1"]["T"]["values"], [0, 0, 0, .56])
    for key in ("Z0_a0", "Z1_a0", "Z1_a1"):
        audit.check("空四群の分母", distribution[key]["方向行"], 0)
        audit.check("空群だけ最小最大None", distribution[key]["T"]["列"]["F31"],
            {"数値数": 0, "異なる値": 0, "最小": None, "最大": None, "ゼロ": 0})
    slot, frames = fixtures.fixture({**fixtures.t_changes(), 13: fixtures.candle(108), 18: fixtures.candle(125)}, 24)
    old = A.R58.expected_feature(A.A.expected_feature(slot, frames), slot, frames)
    tied = A.expected_feature(old, slot, frames)["geometry"]["1"]["T"]
    audit.check("同値極値は先頭の出典を保持", (tied["u_min_source"]["index"], tied["u_max_source"]["index"]), (12, 16))
    # ----------------------------------------
    # 本物教師を使わず、新8列を分岐に含む回帰木を別所属で検算する。
    rows = artificial_rows(source)
    evaluation = max(row["recovery_end_time"] for row in rows) + 3600
    used, training = A.recovery_training(rows, evaluation)
    audit.check("全38教師/base30/base18指紋", learner.prepare_rows(rows, evaluation), (used, training))
    model = learner.fit(rows, A.feature_metadata(), "V0", "V0_人工", evaluation)
    digest = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    A.check_model(model, used, training, A.feature_metadata(), "V0_人工", digest, audit)
    audit.check("新8列の分岐番号を全38へ復元", any(node["feature"] >= 30 for node in model["nodes"]), True)
    measured = {(row["slot_id"], row["side"]): {"session": row["session"], "ready": True, "features": row["features"], "barrier": row,
        "status": "確定完結", "recovery_end_time": row["recovery_end_time"],
        "operation": {"closed": [{f"pnl{f}": float(Decimal(row[f"pnl{f}"])) for f in (0, 5, 10)}]}} for row in used}
    calibration = A.expected_calibration(model, measured, evaluation)
    audit.check("全38到達葉の回収集計", recovery.aggregate(model, measured, evaluation, learner), calibration)
    for i in range(0, 100, 2):
        vectors = {"1": used[i]["features"], "-1": used[i + 1]["features"]}
        audit.check("回帰値と障壁scoreを分離した予測", learner.predict(model, vectors), A.predict(model, vectors))
        for policy, mapped in (("V0", "C0"), ("V1", "R0")):
            audit.check("二案採否の全属性", recovery.predict(model, calibration, vectors, learner, mapped), A.expected_prediction(model, calibration, vectors, policy))
    empty_rows = deepcopy(rows)
    for row in empty_rows:
        row["features"][17] = 0
    empty_used, empty_training = A.recovery_training(empty_rows, evaluation)
    empty = learner.fit(empty_rows, A.feature_metadata(), "V0", "V0_空人工", evaluation)
    A.check_model(empty, empty_used, empty_training, A.feature_metadata(), "V0_空人工", digest, audit)
    invalids = []
    wrong = deepcopy(rows)
    wrong[0]["features"][30] = -.1
    invalids.append(("負の最大逆行", wrong, evaluation))
    wrong = deepcopy(rows)
    wrong[0]["features"][18:24] = [0, 0, 0, -1., 0., 0.]
    wrong[0]["features"][30:34] = [0, 0, 0, 1.]
    invalids.append(("未IDの非零追加値", wrong, evaluation))
    invalids.append(("片側教師抜け", deepcopy(rows[1:]), evaluation))
    invalids.append(("未来回収終了等号", deepcopy(rows), max(row["recovery_end_time"] for row in rows)))
    for name, sample, boundary in invalids:
        for function in (A.recovery_training, learner.prepare_rows):
            failed = False
            try:
                function(sample, boundary)
            except ValueError:
                failed = True
            audit.check(name + function.__name__, failed, True)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "人工fitAPI回数": 2, "人工回帰器fit数": sum(part["fit_performed"] for m in (model, empty) for part in m["training"]["partition"].values()),
        "本物fit": 0, "実教師又はモデル読取": False, "市場戦略再生": False, "新主処理import": False}


if __name__ == "__main__":
    proof = self_test()
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    raise SystemExit(0 if proof["人工成功"] else 1)
