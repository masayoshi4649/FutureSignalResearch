"""61の同46教師・T/R固定四群・44子列・資格維持を人工だけで照合する。"""

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
    返り値: ModuleTypeは読込結果。実教師・モデルは開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(HERE / "保存検証.py", "現行状態保存監査の人工対象")


def artificial_rows(source) -> list[dict]:
    """固定人工800方向をT/R四群へ分け、DIと旧Zを子候補へ戻す。

    引数: source(ModuleType)は固定暦の純補助。
    返り値: list[dict]は全46の20人工場。実データを使用しない。
    """
    old = load(HERE.parent / "波の区間分離/保存検証人工.py", "現行状態人工の固定60教師材料")
    rows = old.artificial_rows(source)
    for index, row in enumerate(rows):
        pair = index // 2
        row["features"][19], row["features"][25] = (pair // 40) % 2, (pair // 20) % 2
        row["features"][17] = (pair // 80) % 2
        row["features"][30:46] = [0.] * 16
        target = 500 * row["features"][17] + 2000 * row["features"][0]
        row.update(pnl0=target + 100, pnl5=target, pnl10=target - 100)
    return rows


def self_test() -> dict:
    """全所属・未知群・旧Z子分岐・priceだけの資格不充足を別算で照合する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物fit・市場は0。
    """
    source, _, _ = A.A.helpers()
    audit = source.Audit()
    learner = load(HERE / "学習.py", "現行状態人工の新学習")
    recovery = load(HERE.parent / "独立追尾回収/回収集計.py", "現行状態人工の固定回収")
    feature = load(HERE / "特徴.py", "現行状態人工の特徴複写")
    fixtures = load(HERE.parent / "価格経路の深さと速度/特徴の人工検査.py", "現行状態人工の紙上SOURCE")
    audit.check("全46metadata不変", feature.FEATURES, A.feature_metadata())
    for changes in (fixtures.t_changes(), fixtures.r_changes(), {}):
        slot, frames = fixtures.fixture(changes, 24)
        base = A.A.expected_feature(slot, frames)
        prior30 = A.R58.expected_feature(base, slot, frames)
        prior38 = A.R59.expected_feature(prior30, slot, frames)
        expected = A.R60.expected_feature(prior38, slot, frames)
        audit.check("同46全辞書の独立再構成", feature.extract(slot, frames), expected)
    rows = artificial_rows(source)
    evaluation = max(row["recovery_end_time"] for row in rows) + 3600
    used, training = A.recovery_training(rows, evaluation)
    audit.check("同46教師と追加base46指紋", learner.prepare_rows(rows, evaluation), (used, training))
    model = learner.fit(rows, A.feature_metadata(), "A0", "A0_人工", evaluation)
    digest = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    A.check_model(model, used, training, A.feature_metadata(), "A0_人工", digest, audit)
    audit.check("四群を方向行で等分", {key: part["direction_rows"] for key, part in model["training"]["partition"].items()},
        {"T0_R0": 200, "T0_R1": 200, "T1_R0": 200, "T1_R1": 200})
    # ----------------------------------------
    # 同じ枠の両方向と同じ形成の反復を、方向行/unique枠/IDへ分ける。
    prepared = {}
    for row in used:
        paths = prepared.setdefault(row["slot_id"], {"paths": {}})["paths"]
        paths[str(row["side"])] = {role: {"episode_id": role + row["slot_id"],
            "cancel": None if row["features"][index] else {"index": 1}, "r": {"index": 1}, "k": None, "k_valid": False}
            for role, index in (("T", 19), ("R", 25))}
    distribution = A.state_distribution(used, prepared)
    audit.check("狭い群でも方向とunique枠を別に数える", {key: {k: value[k] for k in ("方向行", "unique枠", "日数", "場数")} for key, value in distribution.items()},
        {key: {"方向行": 200, "unique枠": 100, "日数": 10, "場数": 20} for key in ("T0_R0", "T0_R1", "T1_R0", "T1_R1")})
    audit.check("取消0群も形成済み/rありを保持", distribution["T0_R0"]["T"],
        {"形成あり": 200, "形成なし": 0, "取消あり": 200, "rあり": 200, "kあり": 0, "k有効": 0, "形成ID数": 100})
    audit.check("有効1群を完成kと数えない", distribution["T1_R1"]["R"],
        {"形成あり": 200, "形成なし": 0, "取消あり": 0, "rあり": 200, "kあり": 0, "k有効": 0, "形成ID数": 100})
    audit.check("固定flagを子へ再投入しない", all(n["feature"] not in (19, 25) for n in model["nodes"][3:]), True)
    audit.check("DIは子の候補へ戻る", any(n["feature"] == 0 for n in model["nodes"][3:]), True)
    measured = {(row["slot_id"], row["side"]): {"session": row["session"], "ready": True, "features": row["features"], "barrier": row,
        "status": "確定完結", "recovery_end_time": row["recovery_end_time"],
        "operation": {"closed": [{f"pnl{fee}": float(Decimal(row[f"pnl{fee}"])) for fee in (0, 5, 10)}]}} for row in used}
    calibration = A.expected_calibration(model, measured, evaluation)
    audit.check("現在状態四群の回収を独立集計", recovery.aggregate(model, measured, evaluation, learner), calibration)
    for index in range(0, 100, 2):
        vectors = {"1": used[index]["features"], "-1": used[index + 1]["features"]}
        audit.check("両方向JSON予測", learner.predict(model, vectors), A.predict(model, vectors))
        for policy, mapped in (("A0", "C0"), ("A1", "R0")):
            audit.check("回収条件とno-rescue採否", recovery.predict(model, calibration, vectors, learner, mapped), A.expected_prediction(model, calibration, vectors, policy))
    # ----------------------------------------
    # 空T1群でも固定R内部nodeと二未知leafを維持し、片側未知から救済しない。
    empty_rows = deepcopy(rows)
    for row in empty_rows:
        row["features"][19], row["features"][25] = 0, 0
    empty_used, empty_training = A.recovery_training(empty_rows, evaluation)
    empty = learner.fit(empty_rows, A.feature_metadata(), "A0", "A0_空人工", evaluation)
    A.check_model(empty, empty_used, empty_training, A.feature_metadata(), "A0_空人工", digest, audit)
    audit.check("旧Zが子に選べる", any(n["feature"] == 17 for n in empty["nodes"][3:]), True)
    vectors = {"1": deepcopy(empty_used[0]["features"]), "-1": deepcopy(empty_used[1]["features"])}
    vectors["-1"][19] = 1
    audit.check("片側未知の全予測", learner.predict(empty, vectors), A.predict(empty, vectors))
    audit.check("未知を0率補完しない", A.predict(empty, vectors)["reason"], "未学習枝WAIT")
    # ----------------------------------------
    # scoreと支持が十分でもpriceしか通らない場合は従来gateでWAITにする。
    price_rows = deepcopy(rows)
    for row in price_rows:
        row.update(pnl0=101, pnl5=1, pnl10=-99)
        row["outcome"] = "250" if A.group_key(row["features"]) == "T0_R0" else "125"
    price_used, price_training = A.recovery_training(price_rows, evaluation)
    price = learner.fit(price_rows, A.feature_metadata(), "A0", "A0_price人工", evaluation)
    A.check_model(price, price_used, price_training, A.feature_metadata(), "A0_price人工", digest, audit)
    audit.check("両固定priceは複数技法を自動充足しない", all(not n["method_support"] for n in price["nodes"] if n["left"] == -1), True)
    plus = next(row["features"] for row in price_used if A.group_key(row["features"]) == "T0_R0")
    minus = next(row["features"] for row in price_used if A.group_key(row["features"]) == "T1_R1")
    prediction = A.predict(price, {"1": plus, "-1": minus})
    audit.check("支持とscoreがあっても技法不足WAIT", (prediction["winner_side"], prediction["side"], prediction["reason"]), (1, 0, "最高側複数技法不足"))
    invalids = [("片側教師抜け", deepcopy(rows[1:]), evaluation),
        ("未来回収終了等号", deepcopy(rows), max(row["recovery_end_time"] for row in rows))]
    for name, sample, boundary in invalids:
        for function in (A.recovery_training, learner.prepare_rows):
            failed = False
            try:
                function(sample, boundary)
            except ValueError:
                failed = True
            audit.check(name + function.__name__, failed, True)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "人工fitAPI回数": 3, "人工回帰器fit数": sum(part["fit_performed"] for m in (model, empty, price) for part in m["training"]["partition"].values()),
        "本物fit": 0, "実教師又はモデル読取": False, "市場戦略再生": False, "新主処理import": False}


if __name__ == "__main__":
    proof = self_test()
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    raise SystemExit(0 if proof["人工成功"] else 1)
