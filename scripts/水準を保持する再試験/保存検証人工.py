"""58保存監査を、人工価格経路と人工教師だけで検査する。"""

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


def lifetime_rows() -> list[dict]:
    """b10/r11/k12と60分等号を持つ人工SOURCEを作る。

    引数: なし。
    返り値: list[dict]は32本。期限足30は新突破候補でも登録禁止、31は次の新bになる。
    """
    rows = []
    for i in range(32):
        close, high, low = (100, 110, 90) if i < 10 else (115, 116, 114) if i == 10 else (115, 118, 110) if i == 11 else (120, 121, 119) if i == 12 else (125, 126, 124)
        if i == 30:
            close, high, low = 140, 141, 139
        if i == 31:
            close, high, low = 147, 148, 146
        rows.append({"session": "人工", "index": i, "minutes": 3, "start": i * 180, "end": (i + 1) * 180,
            "confirm": (i + 1) * 180 + 10, "confirm_line": i * 10, "publish": True, "missing": 0,
            "open": close, "close": close, "high": high, "low": low})
    return rows


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
    fixtures = load(HERE.parent / "再試験の価格経路/特徴の人工検査.py", "再試験人工の紙上SOURCE")
    learner = load(HERE / "学習.py", "再試験人工の新学習")
    recovery = load(HERE.parents[0] / "独立追尾回収/回収集計.py", "再試験人工の固定55集計")
    audit.check("全30metadata", feature.FEATURES, A.feature_metadata())
    rng = random.Random(58)
    for case in range(100):
        rows, close = [], 1000
        for i in range(80):
            close += rng.randrange(-15, 16)
            row = {"session": "人工", "index": i, "minutes": 3, "start": 180 * i, "end": 180 * (i + 1),
                "confirm": 180 * (i + 1) + 10, "confirm_line": 10 * i, "publish": True, "missing": 0,
                "open": close, "close": close, "high": close + rng.randrange(16), "low": close - rng.randrange(16)}
            if case % 4 == 0 and i == 25:
                row["publish"] = False
            if case % 4 == 1 and i == 40:
                row["missing"] = 1
            if case % 4 == 2 and i >= 35:
                row["index"] += 1
            rows.append(row)
        slot = {"session": "人工", "scheduled": rows[-1]["end"], "time": rows[-1]["confirm"] + 5, "line": 10000}
        audit.check("保持全prefixの四経路/履歴" + str(case), feature.reconstruct(slot, rows, 25), A.reconstruct(slot, rows, 25))
    # ----------------------------------------
    # 紙上の時刻・番号を期待値とし、TTL等号・次足置換・reset優先を検査する。
    lifetime = lifetime_rows()
    prefix = lifetime[:31]
    slot = {"session": "人工", "scheduled": prefix[-1]["end"], "time": prefix[-1]["confirm"] + 5, "line": 10000}
    paths, history = A.reconstruct(slot, prefix, 25)
    audit.check("期限等号の全辞書", feature.reconstruct(slot, prefix, 25), (paths, history))
    audit.check("期限足は新b禁止", (paths["1"]["T"]["stage"], paths["1"]["T"]["episode_id"]), (0, None))
    audit.check("期限はb公開から60分", paths["1"]["T"]["last_expired"]["expiry"], lifetime[10]["confirm"] + 3600)
    audit.check("期限公開足を出典へ保存", paths["1"]["T"]["last_expired"]["observed_at"]["index"], 30)
    later = {**slot, "scheduled": lifetime[-1]["end"], "time": lifetime[-1]["confirm"] + 5}
    restored, later_history = A.reconstruct(later, lifetime, 25)
    audit.check("次足から新bの全辞書", feature.reconstruct(later, lifetime, 25), (restored, later_history))
    audit.check("次足新bと旧失効記憶", (restored["1"]["T"]["b"]["index"], restored["1"]["T"]["last_expired"]["b"]["index"]), (31, 10))
    missing = deepcopy(prefix)
    missing[-1]["missing"] = 1
    reset_paths, reset_history = A.reconstruct(slot, missing, 25)
    audit.check("欠枠resetは同時TTLより先", feature.reconstruct(slot, missing, 25), (reset_paths, reset_history))
    audit.check("resetは失効を捏造しない", reset_paths["1"]["T"]["last_expired"], None)
    after_reset = deepcopy(lifetime)
    after_reset.append({**lifetime[-1], "index": 32, "start": 5760, "end": 5940, "confirm": 5950, "confirm_line": 320, "missing": 1})
    reset_slot = {**slot, "scheduled": 5940, "time": 5955}
    remembered, remembered_history = A.reconstruct(reset_slot, after_reset, 25)
    audit.check("reset後の直近失効記憶全辞書", feature.reconstruct(reset_slot, after_reset, 25), (remembered, remembered_history))
    audit.check("新episode resetでも以前の期限を保持", (remembered["1"]["T"]["stage"], remembered["1"]["T"]["last_expired"]["b"]["index"]), (0, 10))
    timer_slot = {**slot, "scheduled": lifetime[29]["end"], "time": lifetime[10]["confirm"] + 3600}
    timer_paths, timer_history = A.reconstruct(timer_slot, lifetime[:30], 25)
    audit.check("足なし判断timerの全辞書", feature.reconstruct(timer_slot, lifetime[:30], 25), (timer_paths, timer_history))
    audit.check("判断失効の区別", timer_paths["1"]["T"]["last_expired"]["observed_at"]["kind"], "判断時刻")
    future = {**lifetime[-1], "end": slot["scheduled"] + 180, "confirm": None, "confirm_line": None, "close": float("nan")}
    audit.check("未来不正価格/未確認clockを読まない", A.visible_sources(slot, prefix + [future]), A.visible_sources(slot, prefix))
    audit.check("未来prefix選別は主と同値", feature.visible_sources(slot, prefix + [future]), A.visible_sources(slot, prefix))
    absent = A.blank_path("人工", 1, "T", None)
    active = {**absent, "episode_id": "人工形成", "k": {"index": 12}, "k_valid": True, "last_expired": {"episode_id": "旧形成"}}
    audit.check("形成反復となしの分母", A.episode_counts([active, active, absent]),
        {"episode数": 1, "episode最大反復": 2, "episodeなし": 1, "k形成episode数": 1, "k有効episode数": 1, "期限失効観測": 2})
    for values in (fixtures.t_path(), fixtures.r_path(), [fixtures.candle(100)] * 5,
                   [fixtures.candle(115), fixtures.candle(115, 118, 110), fixtures.candle(120), fixtures.candle(118), fixtures.candle(125)]):
        slot, frames = fixtures.fixture(values)
        base = A.A.expected_feature(slot, frames)
        expected = A.expected_feature(base, slot, frames)
        audit.check("旧出典から全30辞書", feature.extract(slot, frames), expected)
        for side in ("1", "-1"):
            audit.check("旧18prefix完全維持", expected["vectors"][side][:18], base["vectors"][side])
    rows = artificial_rows(source)
    evaluation = max(r["recovery_end_time"] for r in rows) + 3600
    used, training = A.recovery_training(rows, evaluation)
    audit.check("全30教師とbase18指紋", learner.prepare_rows(rows, evaluation), (used, training))
    model = learner.fit(rows, A.feature_metadata(), "E0", "E0_人工", evaluation)
    digest = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    A.check_model(model, used, training, A.feature_metadata(), "E0_人工", digest, audit)
    audit.check("子29列で新経路が分岐可能", any(n["feature"] >= 18 for n in model["nodes"]), True)
    measurements = {(r["slot_id"], r["side"]): {"session": r["session"], "ready": True, "features": r["features"], "barrier": r,
        "status": "確定完結", "recovery_end_time": r["recovery_end_time"],
        "operation": {"closed": [{f"pnl{f}": float(Decimal(r[f"pnl{f}"])) for f in (0, 5, 10)}]}} for r in used}
    calibration = A.expected_calibration(model, measurements, evaluation)
    audit.check("30列到達葉の回収全属性", recovery.aggregate(model, measurements, evaluation, learner), calibration)
    for i in range(0, 100, 2):
        vectors = {"1": used[i]["features"], "-1": used[i + 1]["features"]}
        audit.check("full30独立walk採否", learner.predict(model, vectors), A.predict(model, vectors))
        for policy, legacy in (("E0", "C0"), ("E1", "R0")):
            audit.check("二候補の全予測", recovery.predict(model, calibration, vectors, learner, legacy), A.expected_prediction(model, calibration, vectors, policy))
    empty_rows = deepcopy(rows)
    for row in empty_rows:
        row["features"][17] = 0
    empty_used, empty_training = A.recovery_training(empty_rows, evaluation)
    empty = learner.fit(empty_rows, A.feature_metadata(), "E0", "E0_空人工", evaluation)
    A.check_model(empty, empty_used, empty_training, A.feature_metadata(), "E0_空人工", digest, audit)
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
