"""57保存監査を、人工価格経路と人工教師だけで検査する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import random


HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工対象を固有名で読み、旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込対象。実教師・本物モデルは読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(HERE / "保存検証.py", "再試験保存監査の人工対象")


def artificial_rows(source) -> list[dict]:
    """20人工場の800方向へ、有効な30列と回収を紙上で作る。

    引数: source(ModuleType)は固定暦の純補助。
    返り値: list[dict]は人工教師。新12列により子投影29の分岐も検査する。
    """
    rows = A.R56.artificial_rows(source)
    for index, row in enumerate(rows):
        pair = index // 2
        t = [3, 1, 1, (pair % 3) / 5, (pair % 7 - 3) / 4, (pair % 5) / 4] if pair % 2 else [0, 0, 0, -1., 0., 0.]
        r = [4, 0, 0, (pair % 2) / 5, (pair % 4 - 2) / 3, 1.] if pair % 3 else [2, 1, 0, -1., 0., 0.]
        row["features"] += t + r
        target = 700 * int(t[0] == 3) - 300 * int(r[0] == 4) + (pair % 5) * 25 + row["side"] * 7.5
        row.update(pnl0=target + 100, pnl5=target, pnl10=target - 100)
    return rows


def self_test() -> dict:
    """区間走査・全30列教師/木/採否・未来境界を人工で照合する。

    引数: なし。
    返り値: dictは人工成功/照合数/差と人工fit数。市場・本物教師/モデルは未読。
    """
    source, _, _ = A.A.helpers()
    audit = source.Audit()
    feature = load(HERE / "特徴.py", "再試験人工の新特徴")
    fixtures = load(HERE / "特徴の人工検査.py", "再試験人工の紙上SOURCE")
    learner = load(HERE / "学習.py", "再試験人工の新学習")
    recovery = load(HERE.parents[0] / "独立追尾回収/回収集計.py", "再試験人工の固定55集計")
    audit.check("全30metadata", feature.FEATURES, A.feature_metadata())
    reference = [{"index": i, "confirm": 180 * (i + 1), "confirm_line": i, "open": 100, "high": 110, "low": 90, "close": 100} for i in range(10)]
    rng = random.Random(57)
    for case in range(250):
        rows = []
        for i in range(10, 15):
            close = rng.randrange(75, 126)
            rows.append({"index": i, "confirm": 180 * (i + 1), "confirm_line": i, "open": close,
                "close": close, "high": close + rng.randrange(16), "low": close - rng.randrange(16)})
        for direction, level in ((1, 110), (-1, 90)):
            for role in ("T", "R"):
                expected = A.episode(reference, rows, level, direction, role, 20, 2800)
                audit.check("人工経路全属性" + str(case), feature.episode(reference, rows, level, direction, role, 20, 2800), expected)
    for values in (fixtures.t_path(), fixtures.r_path(), [fixtures.candle(100)] * 5,
                   [fixtures.candle(115), fixtures.candle(115, 118, 110), fixtures.candle(120), fixtures.candle(118), fixtures.candle(125)]):
        slot, frames = fixtures.fixture(values)
        base = A.A.expected_feature(slot, frames)
        expected = A.expected_feature(base, slot)
        audit.check("旧出典から全30辞書", feature.extract(slot, frames), expected)
        for side in ("1", "-1"):
            audit.check("旧18prefix完全維持", expected["vectors"][side][:18], base["vectors"][side])
    rows = artificial_rows(source)
    evaluation = max(r["recovery_end_time"] for r in rows) + 3600
    used, training = A.recovery_training(rows, evaluation)
    audit.check("全30教師とbase18指紋", learner.prepare_rows(rows, evaluation), (used, training))
    model = learner.fit(rows, A.feature_metadata(), "N0", "N0_人工", evaluation)
    digest = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    A.check_model(model, used, training, A.feature_metadata(), "N0_人工", digest, audit)
    audit.check("子29列で新経路が分岐可能", any(n["feature"] >= 18 for n in model["nodes"]), True)
    measurements = {(r["slot_id"], r["side"]): {"session": r["session"], "ready": True, "features": r["features"], "barrier": r,
        "status": "確定完結", "recovery_end_time": r["recovery_end_time"],
        "operation": {"closed": [{f"pnl{f}": float(Decimal(r[f"pnl{f}"])) for f in (0, 5, 10)}]}} for r in used}
    calibration = A.expected_calibration(model, measurements, evaluation)
    audit.check("30列到達葉の回収全属性", recovery.aggregate(model, measurements, evaluation, learner), calibration)
    for i in range(0, 100, 2):
        vectors = {"1": used[i]["features"], "-1": used[i + 1]["features"]}
        audit.check("full30独立walk採否", learner.predict(model, vectors), A.predict(model, vectors))
        for policy, legacy in (("N0", "C0"), ("N1", "R0")):
            audit.check("二候補の全予測", recovery.predict(model, calibration, vectors, learner, legacy), A.expected_prediction(model, calibration, vectors, policy))
    empty_rows = deepcopy(rows)
    for row in empty_rows:
        row["features"][17] = 0
    empty_used, empty_training = A.recovery_training(empty_rows, evaluation)
    empty = learner.fit(empty_rows, A.feature_metadata(), "N0", "N0_空人工", evaluation)
    A.check_model(empty, empty_used, empty_training, A.feature_metadata(), "N0_空人工", digest, audit)
    invalids = []
    wrong = deepcopy(rows)
    wrong[0]["features"][18] = 4
    invalids.append(("T段階範囲", wrong, evaluation))
    wrong = deepcopy(rows)
    wrong[0]["features"][21] = 0
    invalids.append(("未形成kの経過", wrong, evaluation))
    invalids.append(("片側抜け", deepcopy(rows[1:]), evaluation))
    invalids.append(("未来終了同秒", deepcopy(rows), max(r["recovery_end_time"] for r in rows)))
    for name, sample, boundary in invalids:
        for function in (A.recovery_training, learner.prepare_rows):
            failed = False
            try:
                function(sample, boundary)
            except ValueError:
                failed = True
            audit.check(name + function.__name__, failed, True)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "人工fitAPI回数": 2, "人工回帰器fit数": sum(p["fit_performed"] for m in (model, empty) for p in m["training"]["partition"].values()),
        "本物fit": 0, "実教師又はモデル読取": False, "市場戦略再生": False, "新主処理import": False}


if __name__ == "__main__":
    proof = self_test()
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    raise SystemExit(0 if proof["人工成功"] else 1)
