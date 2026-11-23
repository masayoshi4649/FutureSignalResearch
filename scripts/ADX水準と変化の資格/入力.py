"""77の価格機械を保ち、Tの資格からADX変化符号だけを外す。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT / "scripts/押戻し再開の確認幅/入力.py"
OLD_SHA256 = "cc2f9814847c29c68ce57cd79065c6af2124b65fa133eb4224169363986bcbcf"
if hashlib.sha256(OLD_PATH.read_bytes()).hexdigest() != OLD_SHA256:
    raise ValueError("78が再用する固定77入力のSHA不一致")
SPEC = importlib.util.spec_from_file_location("ADX資格78の固定77純入力", OLD_PATH)
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)
POLICIES, LEGACY = ("S0", "S1"), {"S0": "E0", "S1": "E1"}
SOURCE_FIELDS, SLOT_FIELDS, VALUE_FIELDS = OLD.SOURCE_FIELDS, OLD.SLOT_FIELDS, OLD.VALUE_FIELDS
CONFIRMATION_FIELDS = OLD.CONFIRMATION_FIELDS
finite, exact, canonical = OLD.finite, OLD.exact, OLD.canonical
RULES = deepcopy(OLD.RULES)
RULES.update({"技法": "全候補F02>=0/F03>0/F07>0/F01非零/rawDI非同値。TはF01>0/F51=F52=1/F47>=.20、F48符号は不問",
    "反転": "R全資格は77辞書のまま。DI逆向きRのF52=1/F48<0/F15>0も変更しない",
    "政策": "同じ価格観測のS0はT限定/S1はT-R。旧E政策への対応は局所コピーのみ",
    "継承": "77extractの純出力を深く複写し資格と選択だけ再構成。旧globals/価格機械/形成/履歴/場所は変更しない"})


def qualification_t(candidate: dict, values: dict, quote: dict) -> dict:
    """Tの現在資格をADX差の符号なしで明示計算する。

    引数: candidate/values/quote(dict)は固定77が検証したT・旧float64値・正常気配。
    返り値: dictは元と同じ資格schema。F48は値として残し、採否条件へ使わない。
    """
    if candidate["kind"] != "T":
        raise ValueError("78の変更対象資格はTだけ")
    reasons, di = [], values["F01"]
    role = "上位同値" if di == 0 or values["raw_background_direction"] == 0 else "順行" if di > 0 else "反転"
    tests = ((values["F02"] < 0, "FastKの方向位置が負"), (values["F03"] <= 0, "FastKの方向進行が非正"),
        (values["F07"] <= 0, "現在価格の方向進行が非正"), (di == 0 or values["raw_background_direction"] == 0, "上位DIが同値"),
        (di <= 0, "継続Tは上位DI同方向が必要"), (values["F51"] != 1 or values["F52"] != 1, "継続TのADX現値又は変化が未知"),
        (values["F47"] < .20, "継続TのADX20未満"))
    for condition, reason in tests:
        if condition:
            reasons.append(reason)
    side = candidate["side"]
    entry = quote["ask"] if side == 1 else quote["bid"]
    last_distance = side * (exact(quote["last"]) - exact(candidate["premise_line"]))
    entry_distance = side * (exact(entry) - exact(candidate["premise_line"]))
    if last_distance <= 0:
        reasons.append("現在Lastが前提線を否定")
    if entry_distance <= 0:
        reasons.append("現在新規BBOが前提線を否定")
    return {"qualified": not reasons, "role": role, "reasons": reasons, "values": deepcopy(values),
        "price": {"last": quote["last"], "entry_proxy": entry, "premise_line": candidate["premise_line"],
            "last_distance": float(last_distance), "entry_distance": float(entry_distance)}}


# ----------------------------------------
def extract(slot: dict, history: list[dict], visible_birth_rows: list[dict], quote: dict | None, band: dict | None) -> dict:
    """固定77の不変価格観測からT資格とS0/S1選択だけを再構成する。

    引数: slot/history/visible_birth_rows/quote/bandは77と同じ当時入力。
    返り値: dictはS0/S1共通観測。R資格・現在SOURCE・readyは変更しない。
    """
    result = deepcopy(OLD.extract(slot, history, visible_birth_rows, quote, band))
    for candidate in result["candidates"]:
        if candidate["kind"] == "T" and candidate["id"] in result["qualifications"]:
            old = result["qualifications"][candidate["id"]]
            result["qualifications"][candidate["id"]] = qualification_t(candidate, old["values"], quote)
    reason = result["reason"]
    if result["candidates"] and result["qualifications"] and not any(q["qualified"] for q in result["qualifications"].values()):
        reason = "局所波の現在複合条件不適格"
    choices = {}
    for policy in POLICIES:
        policy_reason = "R形成はS0で採用対象外" if policy == "S0" and result["candidates"] and result["candidates"][0]["kind"] == "R" and result["ready"] else reason
        choices[policy] = OLD.policy_choice(result["candidates"], result["qualifications"], LEGACY[policy], result["ready"], policy_reason)
    result["selected_by_policy"] = choices
    result.update({k: deepcopy(choices["S1"][k]) for k in ("side", "role", "selected", "reason")})
    return result


def choose(slot: dict, observation: dict, policy: str) -> dict:
    """新政策名だけ局所対応し77の純射影を再用する。

    引数: slot/observation(dict)は元判断/新共通観測、policy(str)はS0/S1。
    返り値: dictは純10と由来。T確認3項目は維持し、R/WAITへ追加しない。
    """
    if policy not in LEGACY:
        raise ValueError("78政策はS0/S1")
    local = deepcopy(observation)
    local["selected_by_policy"] = {LEGACY[p]: deepcopy(v) for p, v in observation["selected_by_policy"].items()}
    result = OLD.choose(slot, local, LEGACY[policy])
    result["policy"] = policy
    return result


# ----------------------------------------
def self_test() -> dict:
    """架空入力でADX負/零/正・未知・水準・他資格・鏡像を検査する。

    引数: なし。
    返り値: dictは成功/テスト件数/照合項目数/不一致数。価格・教師・損益は読まない。
    """
    groups = checks = 0
    old_class, old_policies, old_rules = OLD.Machine, tuple(OLD.POLICIES), canonical(OLD.RULES)

    def check(actual: object, expected: object) -> None:
        """JSON型を含め人工期待へ照合する。

        引数: actual/expected(object)は実値/期待値。
        返り値: None。不一致はAssertionError。
        """
        nonlocal checks
        checks += 1
        assert canonical(actual, True) == canonical(expected, True), (actual, expected)

    def field(case: tuple, name: str, value: float | int) -> tuple:
        """人工の両側値を方向性に合わせて変更する。

        引数: case(tuple)は人工5引数、name(str)は保存特徴ID、valueは買い側の人工値。
        返り値: tupleは同じ人工入力。実データに使用しない。
        """
        for side in (1, -1):
            case[0]["feature"]["vectors"][str(side)][VALUE_FIELDS[name]] = side * value if name in ("F01", "F02", "F03", "F07", "F15") else value
        return case

    def observe(case: tuple) -> dict:
        """価格観測不変・R資格同値・元T包含と追加の一軸を検査する。

        引数: case(tuple)は架空の77同型5引数。
        返り値: dictは78新共通観測。
        """
        before = canonical(case, True)
        old, new = OLD.extract(*case), extract(*case)
        check(canonical(case, True), before)
        mutable = {"qualifications", "selected_by_policy", "side", "role", "selected", "reason"}
        check({k: v for k, v in old.items() if k not in mutable}, {k: v for k, v in new.items() if k not in mutable})
        for candidate in old["candidates"]:
            if candidate["kind"] == "R":
                check(old["qualifications"].get(candidate["id"]), new["qualifications"].get(candidate["id"]))
        for prior, current in (("E0", "S0"), ("E1", "S1")):
            a, b = OLD.choose(case[0], old, prior), choose(case[0], new, current)
            if a["side"]:
                check({k: v for k, v in a.items() if k != "policy"}, {k: v for k, v in b.items() if k != "policy"})
            elif b["side"]:
                selected = new["selected_by_policy"][current]["selected"]
                check(selected["kind"], "T")
                check(old["qualifications"][selected["id"]]["reasons"], ["継続TのADXが減速"])
                check(new["qualifications"][selected["id"]]["values"]["F48"] < 0, True)
            if b["formation"] != "T":
                check(any(k in b for k in CONFIRMATION_FIELDS), False)
        a, b = choose(case[0], new, "S0"), choose(case[0], new, "S1")
        if a["side"]:
            check({k: a[k] for k in SLOT_FIELDS}, {k: b[k] for k in SLOT_FIELDS})
        return new

    base = OLD.OLD.synthetic([100, 103, 106, 104, 105])
    for value in (-.01, 0.0, .01):
        case = field(deepcopy(base), "F48", value)
        got = observe(case)
        check(got["side"], 1)
        check(OLD.extract(*case)["side"], 0 if value < 0 else 1)
    groups += 1
    for name, value in (("F51", 0), ("F52", 0), ("F47", math.nextafter(.20, -math.inf)), ("F03", 0), ("F07", 0), ("F02", -.01)):
        case = field(field(deepcopy(base), "F48", -.01), name, value)
        check(observe(case)["side"], 0)
    check(observe(field(deepcopy(base), "F47", .20))["side"], 1)
    groups += 1
    check(observe(OLD.OLD.synthetic([100, 103, 106, 104, 105], 1, -1))["side"], 0)
    case = field(deepcopy(base), "F48", -.01)
    case[3]["last"] = 103
    check(observe(case)["side"], 0)
    groups += 1
    for value in (-.01, 0.0, .01):
        case = field(OLD.OLD.synthetic([100, 103, 106, 98, 96], -1, 1), "F48", value)
        observe(case)
    for background in (-1, 1):
        case = OLD.OLD.synthetic([100, 103, 106, 98, 96], -1, background)
        observe(case)
    groups += 1
    case = field(deepcopy(base), "F48", -.01)
    a, b = observe(case), observe(OLD.OLD.reflected(case))
    check((b["side"], b["role"], b["ready"]), (-a["side"], a["role"], a["ready"]))
    check(b["qualifications"][b["selected"]["id"]]["values"]["F48"], -.01)
    groups += 1
    future = deepcopy(case)
    row = deepcopy(future[1][-1])
    row.update(index=5, start=row["end"], end=row["end"] + 180, confirm=None, high=float("nan"))
    future[1].append(row)
    check(observe(future), extract(*case))
    unknown = deepcopy(base)
    unknown[0].update(ready=False, line=None)
    unknown[0]["feature"] = {"ready": False}
    got = observe((unknown[0], None, None, None, None))
    check((got["ready"], got["source_count"]), (False, 0))
    groups += 1
    check(hashlib.sha256(OLD_PATH.read_bytes()).hexdigest(), OLD_SHA256)
    check((OLD.Machine is old_class, tuple(OLD.POLICIES), canonical(OLD.RULES)), (True, old_policies, old_rules))
    return {"成功": True, "テスト件数": groups, "照合項目数": checks, "不一致数": 0,
        "旧77コードSHA256": OLD_SHA256, "本物入力読取": False, "fit": 0, "市場再生": False, "新計測": 0}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, allow_nan=False))
