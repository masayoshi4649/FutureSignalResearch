"""62の枝別44列・DI零化・継承六キー/61限定補足を人工で照合する。"""

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
    返り値: ModuleTypeは読込結果。実教師・実モデルは開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(HERE / "保存検証.py", "方向再開保存監査の人工対象")


def artificial_rows(source) -> list[dict]:
    """20人工場の800方向をDI/対象kへ分け、反対側kを子分岐に使わせる。

    引数: source(ModuleType)は固定暦の純補助。
    返り値: list[dict]は全46教師。実相場・回収測定は使わない。
    """
    old = load(HERE.parent / "波の区間分離/保存検証人工.py", "方向再開人工の固定60教師材料")
    rows = old.artificial_rows(source)
    for index, row in enumerate(rows):
        pair = index // 2
        d, k, other = int(row["side"] == 1), (pair // 20) % 2, (pair // 40) % 2
        t_flag, r_flag = (k, other) if d else (other, k)
        row["features"][0], row["features"][17] = 1. if d else -1., (pair // 80) % 2
        row["features"][18:30] = [3, t_flag, t_flag, .1, 0., 0., 4, r_flag, r_flag, .1, 0., 0.]
        row["features"][30:46] = [0.] * 16
        target = 2000 * other + 500 * row["features"][17] + row["side"] * 7.5
        row.update(pnl0=target + 100, pnl5=target, pnl10=target - 100)
    return rows


def self_test() -> dict:
    """紙上教師だけで枝別投影/未知と継承metadataの拒否境界を確認する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物fitは0。
    """
    source, _, _ = A.A.helpers()
    audit = source.Audit()
    learner = load(HERE / "学習.py", "方向再開人工の新学習")
    recovery = load(HERE.parent / "独立追尾回収/回収集計.py", "方向再開人工の固定回収")
    feature = load(HERE / "特徴.py", "方向再開人工の同46特徴")
    fixtures = load(HERE.parent / "価格経路の深さと速度/特徴の人工検査.py", "方向再開人工の紙上SOURCE")
    audit.check("同46metadata", feature.FEATURES, A.feature_metadata())
    for changes in (fixtures.t_changes(), fixtures.r_changes(), {}):
        slot, frames = fixtures.fixture(changes, 24)
        base = A.A.expected_feature(slot, frames)
        prior30 = A.R58.expected_feature(base, slot, frames)
        prior38 = A.R59.expected_feature(prior30, slot, frames)
        expected = A.R60.expected_feature(prior38, slot, frames)
        audit.check("固定60独立全46辞書と新shim", feature.extract(slot, frames), expected)
    rows = artificial_rows(source)
    evaluation = max(row["recovery_end_time"] for row in rows) + 3600
    used, training = A.recovery_training(rows, evaluation)
    audit.check("同46canonicalと全指紋維持", learner.prepare_rows(rows, evaluation), (used, training))
    model = learner.fit(rows, A.feature_metadata(), "K0", "K0_人工", evaluation)
    digest = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    A.check_model(model, used, training, A.feature_metadata(), "K0_人工", digest, audit)
    audit.check("四群に方向200行ずつ・枝内pair不要", {key: (part["direction_rows"], part["pair_unique"]) for key, part in model["training"]["partition"].items()},
        {"D0_K0": (200, 200), "D0_K1": (200, 200), "D1_K0": (200, 200), "D1_K1": (200, 200)})
    low = [n for n in model["nodes"][3:] if n["left"] != -1 and n["path"][0]["branch"] == "left"]
    high = [n for n in model["nodes"][3:] if n["left"] != -1 and n["path"][0]["branch"] == "right"]
    audit.check("低側はT旗index20を子へ戻す", any(n["feature"] == 20 for n in low), True)
    audit.check("高側はR旗index26を子へ戻す", any(n["feature"] == 26 for n in high), True)
    audit.check("固定DI/対応kだけを枝別除外", (all(n["feature"] not in (0, 26) for n in low), all(n["feature"] not in (0, 20) for n in high)), (True, True))
    audit.check("従来資格を緩和せず固定trend/priceが二系統", all(n["method_support"] for n in model["nodes"] if n["left"] == -1), True)
    prepared = {}
    for row in used:
        paths = prepared.setdefault(row["slot_id"], {"paths": {}})["paths"]
        paths[str(row["side"])] = {role: {"episode_id": role + row["slot_id"],
            "cancel": None if row["features"][index] else {"index": 1}, "r": {"index": 1}, "k": {"index": 2},
            "k_valid": bool(row["features"][index])} for role, index in (("T", 20), ("R", 26))}
    distribution = A.state_distribution(used, prepared)
    audit.check("方向枝と対象k経路を別記", {key: (v["方向枝"], v["対象経路"], v["k有効"], v["方向行"], v["unique枠"], v["日数"], v["場数"]) for key, v in distribution.items()},
        {"D0_K0": ("DI非正", "R", 0, 200, 200, 10, 20), "D0_K1": ("DI非正", "R", 1, 200, 200, 10, 20),
         "D1_K0": ("DI正", "T", 0, 200, 200, 10, 20), "D1_K1": ("DI正", "T", 1, 200, 200, 10, 20)})
    audit.check("k0を未登録へ置換しない", distribution["D0_K0"]["R"],
        {"形成あり": 200, "形成なし": 0, "取消あり": 200, "rあり": 200, "kあり": 200, "k有効": 0, "形成ID数": 200})
    audit.check("対応していない側も分布へ保持", distribution["D1_K1"]["R"]["k有効"], 100)
    measured = {(row["slot_id"], row["side"]): {"session": row["session"], "ready": True, "features": row["features"], "barrier": row,
        "status": "確定完結", "recovery_end_time": row["recovery_end_time"],
        "operation": {"closed": [{f"pnl{fee}": float(Decimal(row[f"pnl{fee}"])) for fee in (0, 5, 10)}]}} for row in used}
    calibration = A.expected_calibration(model, measured, evaluation)
    audit.check("枝別44子の葉回収を独立結合", recovery.aggregate(model, measured, evaluation, learner), calibration)
    for index in range(0, 100, 2):
        vectors = {"1": used[index]["features"], "-1": used[index + 1]["features"]}
        audit.check("両方向全予測", learner.predict(model, vectors), A.predict(model, vectors))
        for policy, mapped in (("K0", "C0"), ("K1", "R0")):
            audit.check("障壁最高側/回収後段/次点救済なし", recovery.predict(model, calibration, vectors, learner, mapped), A.expected_prediction(model, calibration, vectors, policy))
    # ----------------------------------------
    # 極小正DIのfloat32零化は低枝Rを選ぶが、rawによる運用roleを反転へ書き換えない。
    tiny = deepcopy(used[0]["features"])
    tiny[0] = 1e-50
    audit.check("微小正DIはfloat32で非正枝", (A.float32(tiny)[0], A.group_key(tiny)), (0., "D0_K" + str(int(tiny[26]))))
    audit.check("raw順行と低DI枝の例外を許容", (tiny[0] > 0, A.group_key(tiny).startswith("D0")), (True, True))
    # ----------------------------------------
    # 空の正DI枝にもT固定nodeと未知二葉を残す。
    empty_rows = deepcopy(rows)
    for row in empty_rows:
        row["features"][0] = -1.
    empty_used, empty_training = A.recovery_training(empty_rows, evaluation)
    empty = learner.fit(empty_rows, A.feature_metadata(), "K0", "K0_空人工", evaluation)
    A.check_model(empty, empty_used, empty_training, A.feature_metadata(), "K0_空人工", digest, audit)
    vectors = {"1": deepcopy(empty_used[0]["features"]), "-1": deepcopy(empty_used[1]["features"])}
    vectors["1"][0] = 1.
    audit.check("片側未知全予測", learner.predict(empty, vectors), A.predict(empty, vectors))
    audit.check("未知を0率で救済しない", A.predict(empty, vectors)["reason"], "未学習枝WAIT")
    # ----------------------------------------
    # 前巡の六キー漏れと、初回/補足経緯を人工で固定してから正式へ進む。
    inherited = {"測定特徴方向一致": 4884, "旧評価特徴完全一致": 3404, "旧18特徴完全一致": 2442,
        "旧38特徴保存一致": 3404, "旧46特徴保存一致": 3404, "同一新規完結一致": 240}
    audit.check("六カウンタ完全継承", A.expected_counts(inherited, 3404, 100), {**inherited, "同一新規完結一致": 100})
    missing = deepcopy(inherited)
    missing.pop("旧38特徴保存一致")
    denied = False
    try:
        A.expected_counts(missing, 3404, 100)
    except ValueError:
        denied = True
    audit.check("旧38キー漏れを人工で拒否", denied, True)
    prior = {"全件一致": True, "不一致数": 0, "照合項目数": 127119,
        "初回監査": {"全件一致": False, "照合項目数": 119952, "不一致数": 1, "他の初回成功項目数": 119951, "パス": "initial.json", "SHA256": "0" * 64},
        "限定補足": {"元不一致唯一": True, "元不一致数": 1, "補足解消数": 1, "残不一致数": 0, "旧60旧38保存カウンタ": 3404,
            "同46保存全辞書実数": 3404, "同38射影実数": 3404, "追加照合項目数": 7167, "初回参照SHA不変": True,
            "固定A変更": False, "主結果変更": False, "原監査再実行": False, "市場再生": False, "fit": False,
            "補足コード": {"パス": "supplement.py", "SHA256": "1" * 64}}}
    audit.check("旧61初回/補足二出典を保持", A.prior_supplement(prior), [("initial.json", "0" * 64), ("supplement.py", "1" * 64)])
    wrong = deepcopy(prior)
    wrong["限定補足"]["残不一致数"] = 1
    denied = False
    try:
        A.prior_supplement(wrong)
    except ValueError:
        denied = True
    audit.check("旧61未解消を成功へ昇格しない", denied, True)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "人工fitAPI回数": 2, "人工回帰器fit数": sum(part["fit_performed"] for m in (model, empty) for part in m["training"]["partition"].values()),
        "本物fit": 0, "実教師又はモデル読取": False, "市場戦略再生": False, "新主処理import": False}


if __name__ == "__main__":
    proof = self_test()
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    raise SystemExit(0 if proof["人工成功"] else 1)
