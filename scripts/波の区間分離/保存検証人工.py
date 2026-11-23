"""60の区間8列・旧38射影・全46回帰木と採否を人工だけで確認する。"""

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工の対象を固有名で読み、旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。実教師・モデルは開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(HERE / "保存検証.py", "区間保存監査の人工対象")


def artificial_rows(source) -> list[dict]:
    """固定人工800方向へ新八値を加え、追加列を選ぶ子木を作る。

    引数: source(ModuleType)は固定暦の純補助。
    返り値: list[dict]は20人工場の全46教師。本物教師を使わない。
    """
    old = load(HERE.parent / "価格経路の深さと速度/保存検証人工.py", "区間人工の固定59教師材料")
    rows = old.artificial_rows(source)
    for index, row in enumerate(rows):
        pair = index // 2
        row["features"][18], row["features"][24] = 2, 3
        row["features"][30:38] = [0.] * 8
        tail = [(pair % 7 - 3) / 8, (pair // 2 % 7 - 3) / 4, (pair % 5 - 2) / 5, row["side"] * .2,
                (pair // 3 % 9 - 4) / 7, (pair // 5 % 5 - 2) / 3, (pair // 7 % 7 - 3) / 6, row["side"] * (pair // 11 % 5 - 2) / 2]
        row["features"] += tail
        target = 2000 * tail[6] + 100 * tail[5] + row["side"] * 7.5
        row.update(pnl0=target + 100, pnl5=target, pnl10=target - 100)
    return rows


def self_test() -> dict:
    """黄金SOURCEと人工回帰だけで区間・出典・全所属と拒否境界を照合する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物fitと市場再生は0。
    """
    source, _, _ = A.A.helpers()
    audit = source.Audit()
    feature = load(HERE / "特徴.py", "区間人工の新特徴")
    fixtures = load(HERE.parent / "価格経路の深さと速度/特徴の人工検査.py", "区間人工の紙上SOURCE")
    learner = load(HERE / "学習.py", "区間人工の新学習")
    recovery = load(HERE.parent / "独立追尾回収/回収集計.py", "区間人工の固定回収")
    audit.check("46metadataの独立定義", feature.FEATURES, A.feature_metadata())
    samples = [(fixtures.t_changes(), 24), (fixtures.r_changes(), 24), ({}, 24),
               ({24: fixtures.candle(115)}, 24), (fixtures.t_changes(), 14), (fixtures.r_changes(), 14), ({}, 10)]
    cache = {}
    for changes, current in samples:
        slot, frames = fixtures.fixture({index: row for index, row in changes.items() if index <= current}, current)
        base = A.A.expected_feature(slot, frames)
        old30 = A.R58.expected_feature(base, slot, frames)
        old38 = A.R59.expected_feature(old30, slot, frames)
        expected = A.expected_feature(old38, slot, frames)
        actual = feature.extract(slot, frames)
        audit.check("全46辞書と固定区間出典", actual, expected)
        audit.check("旧59全辞書復元", feature.control_projection(actual), old38)
        for side in ("1", "-1"):
            audit.check("旧38prefix不変", actual["vectors"][side][:38], old38["vectors"][side])
        if current == 24 and changes == fixtures.t_changes():
            cache["T"] = expected
        if current == 24 and changes == fixtures.r_changes():
            cache["R"] = expected
        if current == 14 and changes == fixtures.t_changes():
            cache["r当足"] = expected
        if current == 24 and not changes:
            cache["未ID"] = expected
        if current == 24 and changes == {24: fixtures.candle(115)}:
            cache["未r"] = expected
    audit.check("先行10差分とT前後の黄金値", cache["T"]["segments"]["1"]["T"]["values"], [.06, 1., .02, .02])
    audit.check("Rはfを起点に正のr進行も許す", cache["R"]["segments"]["-1"]["R"]["values"], [-.06, -1., .04, .012])
    audit.check("r前から選んだpを後の極値で更新しない", cache["R"]["segments"]["-1"]["R"]["p"]["index"], 13)
    audit.check("r当足は適用あり既知0", (cache["r当足"]["segments"]["1"]["T"]["masks"], cache["r当足"]["segments"]["1"]["T"]["since_r_steps"], cache["r当足"]["segments"]["1"]["T"]["values"][3]),
        ({"registration": True, "approach": True, "since_r": True}, 0, 0.))
    audit.check("未rは区間maskを付けない", cache["未r"]["segments"]["1"]["T"]["masks"], {"registration": True, "approach": False, "since_r": False})
    audit.check("未IDの四値0は準備不足ではない", (cache["未ID"]["ready"], cache["未ID"]["segments"]["1"]["T"]["values"]), (True, [0, 0, 0, 0]))
    audit.check("総変動0の一般算術を登録成績へ混ぜない", feature.registration_statistics([100] * 11, 1, 25), (Fraction(0),) * 4)
    tied = fixtures.t_changes()
    tied[13] = fixtures.candle(115)
    slot, frames = fixtures.fixture(tied, 24)
    old38 = A.R59.expected_feature(A.R58.expected_feature(A.A.expected_feature(slot, frames), slot, frames), slot, frames)
    expected = A.expected_feature(old38, slot, frames)
    audit.check("同値pの全辞書独立照合", feature.extract(slot, frames), expected)
    audit.check("p同値はr前最初のbを保持", expected["segments"]["1"]["T"]["p"]["index"], 10)
    for changes in (fixtures.t_changes(), fixtures.r_changes(), {}, {24: fixtures.candle(115)}):
        slot, frames = fixtures.fixture(changes, 24)
        normal = feature.extract(slot, frames)
        mirrored_slot, mirrored_frames = fixtures.OLD.OLD.reflect(slot, frames)
        mirrored_base = A.A.expected_feature(mirrored_slot, mirrored_frames)
        mirrored_old = A.R59.expected_feature(A.R58.expected_feature(mirrored_base, mirrored_slot, mirrored_frames), mirrored_slot, mirrored_frames)
        mirrored = A.expected_feature(mirrored_old, mirrored_slot, mirrored_frames)
        audit.check("鏡像の区間全出典独立一致", feature.extract(mirrored_slot, mirrored_frames), mirrored)
        for side in ("1", "-1"):
            audit.check("売買符号交換で全46同値", normal["vectors"][side], mirrored["vectors"][str(-int(side))])
    # ----------------------------------------
    # 分布は全方向行を分母に、形成とrの有無を別に数える。
    distribution_rows = []
    for identity in ("T", "r当足", "未r", "未ID"):
        value = cache[identity]
        value["vectors"]["1"][0], value["vectors"]["1"][17] = 1., 0
        distribution_rows.append({"slot_id": identity, "side": 1, "features": value["vectors"]["1"]})
    distribution = A.segment_distribution(distribution_rows, cache)
    row = distribution["Z0_a1"]
    audit.check("分布の全方向行分母", row["方向行"], 4)
    audit.check("形成とrの排他的分母", {k: v for k, v in row["T"].items() if k != "列"},
        {"形成あり": 3, "形成なし": 1, "取消あり": 1, "rあり": 2, "rなし": 2, "r当足": 1, "形成ID数": 2})
    audit.check("未r定義0を含む第三列", row["T"]["列"]["F41"], {"数値数": 4, "異なる値": 2, "最小": 0, "最大": .02, "ゼロ": 2})
    audit.check("空群だけ最小最大None", distribution["Z1_a0"]["T"]["列"]["F39"],
        {"数値数": 0, "異なる値": 0, "最小": None, "最大": None, "ゼロ": 0})
    # ----------------------------------------
    # 新八列を分岐に使う紙上木を、独立所属/Decimal/全方向予測で検算する。
    rows = artificial_rows(source)
    evaluation = max(row["recovery_end_time"] for row in rows) + 3600
    used, training = A.recovery_training(rows, evaluation)
    audit.check("全46教師とbase38指紋", learner.prepare_rows(rows, evaluation), (used, training))
    model = learner.fit(rows, A.feature_metadata(), "S0", "S0_人工", evaluation)
    digest = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    A.check_model(model, used, training, A.feature_metadata(), "S0_人工", digest, audit)
    audit.check("新8列の分岐を元46番号へ復元", any(node["feature"] >= 38 for node in model["nodes"]), True)
    measured = {(row["slot_id"], row["side"]): {"session": row["session"], "ready": True, "features": row["features"], "barrier": row,
        "status": "確定完結", "recovery_end_time": row["recovery_end_time"],
        "operation": {"closed": [{f"pnl{fee}": float(Decimal(row[f"pnl{fee}"])) for fee in (0, 5, 10)}]}} for row in used}
    calibration = A.expected_calibration(model, measured, evaluation)
    audit.check("全46到達葉の回収集計", recovery.aggregate(model, measured, evaluation, learner), calibration)
    for index in range(0, 100, 2):
        vectors = {"1": used[index]["features"], "-1": used[index + 1]["features"]}
        audit.check("障壁scoreによる最高側と未知", learner.predict(model, vectors), A.predict(model, vectors))
        for policy, mapped in (("S0", "C0"), ("S1", "R0")):
            audit.check("二案採否の全属性", recovery.predict(model, calibration, vectors, learner, mapped), A.expected_prediction(model, calibration, vectors, policy))
    empty_rows = deepcopy(rows)
    for row in empty_rows:
        row["features"][17] = 0
    empty_used, empty_training = A.recovery_training(empty_rows, evaluation)
    empty = learner.fit(empty_rows, A.feature_metadata(), "S0", "S0_空人工", evaluation)
    A.check_model(empty, empty_used, empty_training, A.feature_metadata(), "S0_空人工", digest, audit)
    invalids = []
    sample = deepcopy(rows)
    sample[0]["features"][39] = 1.01
    invalids.append(("効率範囲外", sample, evaluation))
    sample = deepcopy(rows)
    sample[0]["features"][18:24] = [0, 0, 0, -1., 0., 0.]
    sample[0]["features"][38:42] = [1., 0., 0., 0.]
    invalids.append(("未IDの非零区間", sample, evaluation))
    sample = deepcopy(rows)
    sample[0]["features"][18] = 1
    sample[0]["features"][40] = 1.
    invalids.append(("未rの非零進行", sample, evaluation))
    invalids.append(("片側教師欠落", deepcopy(rows[1:]), evaluation))
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
