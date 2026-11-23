"""固定木の両方向資格を先に評価し、その中で障壁scoreが高い側を選ぶ。"""

from copy import deepcopy
import importlib.util
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
REFERENCE_PATH = HERE.parent / "独立追尾回収/回収集計.py"
SPEC = importlib.util.spec_from_file_location("適格方向66が固定参照する55回収予測", REFERENCE_PATH)
REFERENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REFERENCE)
SIDES = ("1", "-1")
POLICIES = ("E0", "E1")
REFERENCE_POLICIES = {"E0": "C0", "E1": "R0"}
RULES = {
    "参照": "固定65 U0木3本/cal3本と同じ60特徴。新fit0・新feature0",
    "候補": {"E0": "従来基本の両方向資格から選択", "E1": "同じ両方向資格に過去主回収strict正を追加"},
    "旧予測": "E0は旧R55 C0、E1は旧R55 R0を呼びreferenceへ全文保存",
    "先行WAIT": ["両空の特徴未準備", "片側でもscore未知", "raw両側score同点"],
    "資格": {"score下限": 1 / 3, "葉unique枠": 60, "葉日": 6, "葉場": 10,
        "複数技法": "従来の異種family2以上かつtrend又はosc", "回収unique枠": 60, "回収日": 6, "回収場": 10},
    "資格の再用": "葉資格は旧learner.predictの両側eligibility、回収支持と正額は固定calの保存boolを再用",
    "方向順位": "先行WAIT以外で全資格を満たす既知側のうちstrict高い障壁score。回収平均で順位を変えない",
    "変更": "元最高側が不適格でも他側が全資格適格なら選択できる。元最高側適格なら旧方向を保持",
    "E1とE0": "別々に資格判定するため方向が逆転し得る。同方向部分集合を要求しない",
    "未知": "学習葉score未知と回収支持不足を区別。既知側だけで片側未知の先行WAITを解除しない",
    "互換欄": "priorは旧reference.prior。採用時の回収欄は選択葉、WAIT時はreference値を保持",
    "救済件数": "rescuedはこの予測内の側変更。後段DIraw0WAIT後の純採用件数と区別",
    "維持": "DIraw0の最終WAIT・定時時計・O49・費用・支持・活動条件は呼出し側の従来規約",
}


# ----------------------------------------
def direction_eligibility(prior: dict, calibration: dict, side: str, policy: str, unprepared: bool) -> dict:
    """一方向の既存資格を読み、全ての不適格理由を順序付きで残す。

    引数: prior(dict)は旧learner予測、calibration(dict)は固定回収集計、side(str)は1/-1、
        policy(str)はE0/E1、unprepared(bool)は両空の未準備。
    返り値: dictは既知・葉・score・旧資格・回収・eligible・理由。再集計やfitをしない。
    """
    score, leaf = prior["scores"][side], prior["leafs"][side]
    if score is None:
        return {"known": False, "leaf": leaf, "score_value": None, "score": None, "leaf_support": None,
            "method_support": None, "families": None, "recovery_support": None, "recovery_positive": None,
            "recovery_mean5": None, "eligible": False, "reasons": ["特徴未準備" if unprepared else "未学習葉"]}
    if (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score)
            or not 0 <= score <= 1 or type(leaf) is not int):
        raise ValueError("既知側の障壁score又は葉IDが不正")
    old = prior["eligibility"][side]
    if not isinstance(old, dict) or any(type(old.get(name)) is not bool for name in ("score", "leaf_support", "method_support")):
        raise ValueError("旧両方向資格のboolが不正")
    if old["score"] != (score >= 1 / 3):
        raise ValueError("旧score資格と固定下限が不一致")
    recovery = calibration["leaves"].get(str(leaf))
    if (not isinstance(recovery, dict) or recovery.get("leaf") != leaf
            or type(recovery.get("support")) is not bool or type(recovery.get("positive")) is not bool):
        raise ValueError("既知葉に対応する回収集計が不正")
    mean = recovery["mean_yen"]["5"]
    if mean is not None and (isinstance(mean, bool) or not isinstance(mean, (int, float)) or not math.isfinite(mean)):
        raise ValueError("過去回収平均が非有限")
    reasons = [text for name, text in (("score", "score下限未達"), ("leaf_support", "葉支持不足"),
        ("method_support", "複数技法不足")) if not old[name]]
    if not recovery["support"]:
        reasons.append("回収支持不足")
    if policy == "E1" and not recovery["positive"]:
        reasons.append("過去回収平均未知" if mean is None else "過去回収平均非正")
    return {"known": True, "leaf": leaf, "score_value": score,
        "score": old["score"], "leaf_support": old["leaf_support"], "method_support": old["method_support"],
        "families": deepcopy(old["families"]), "recovery_support": recovery["support"],
        "recovery_positive": recovery["positive"], "recovery_mean5": mean,
        "eligible": not reasons, "reasons": reasons}


# ----------------------------------------
def predict(model: dict, calibration: dict, vectors: dict, learner, policy: str) -> dict:
    """旧予測を保存し、同点・未知を保ってから全資格適格側を優先する。

    引数: model(dict)は固定65 U0木、calibration(dict)は同じ固定回収、vectors(dict)は両方向又は両空、
        learner(ModuleType等)は旧predictを持つ純学習器、policy(str)はE0/E1。
    返り値: dictは互換予測・両側資格・元最高側・選択側・救済・旧reference。新fit/新予測木を作らない。
    """
    if policy not in POLICIES:
        raise ValueError("選択候補はE0又はE1が必要")
    reference_policy = REFERENCE_POLICIES[policy]
    reference = REFERENCE.predict(model, calibration, vectors, learner, reference_policy)
    prior = reference["prior"]
    if any(set(prior[name]) != set(SIDES) for name in ("scores", "leafs", "eligibility")):
        raise ValueError("旧予測の両側フィールドが不一致")
    unprepared = vectors["1"] == [] and vectors["-1"] == []
    directions = {side: direction_eligibility(prior, calibration, side, policy, unprepared) for side in SIDES}
    scores = prior["scores"]
    if unprepared:
        block = "特徴未準備WAIT"
    elif any(scores[side] is None for side in SIDES):
        block = "未学習枝WAIT"
    elif scores["1"] == scores["-1"]:
        block = "同点WAIT"
    else:
        block = None
    expected_winner = 0 if block else 1 if scores["1"] > scores["-1"] else -1
    if prior["winner_side"] != expected_winner:
        raise ValueError("旧元最高側とraw両側scoreが不一致")
    eligible = sorted((int(side) for side in SIDES if directions[side]["eligible"]),
        key=lambda side: -scores[str(side)])
    selected = 0 if block or not eligible else eligible[0]
    rescued = bool(selected and selected != expected_winner)
    reason = block or ("両方向不適格WAIT" if not selected else "適格な他方向を採用" if rescued else "採用")
    result = {"side": selected, "reason": reason, "prior": deepcopy(prior),
        "recovery_leaf": reference["recovery_leaf"], "recovery_support": reference["recovery_support"],
        "recovery_mean5": reference["recovery_mean5"], "policy": policy, "reference_policy": reference_policy,
        "original_winner_side": expected_winner, "selected_side": selected, "rescued": rescued,
        "rescue_reasons": deepcopy(directions[str(expected_winner)]["reasons"]) if rescued else [],
        "direction_eligibility": directions, "eligible_sides": eligible, "ranking_block_reason": block,
        "reference": deepcopy(reference)}
    if selected:
        chosen = directions[str(selected)]
        result.update(recovery_leaf=chosen["leaf"], recovery_support=chosen["recovery_support"],
            recovery_mean5=chosen["recovery_mean5"])
    return result
