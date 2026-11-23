"""82の保存判断を独立数式で監査する。原板・実売買・Go判定器は実行しない。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICIES = ("B0", "B1")
JST = timezone(timedelta(hours=9))


class Audit:
    """比較数と実際の不一致を保持し、例の上限だけを制限する。"""

    def __init__(self) -> None:
        """
        機能: 未実行の監査器を初期化する。
        引数: なし。
        返り値: None。件数と限定した差分例を保持する。
        """
        self.count = 0
        self.bad = 0
        self.details = []
        self.scope = Counter()

    def check(self, condition: bool, label: str, where: str, actual=None, expected=None) -> None:
        """
        機能: 比較の成功・不一致を独立に数え、失敗を保存する。
        引数: condition (bool)、label/where (str)、actual/expected (JSON互換値)。
        返り値: None。差分例が上限でも不一致総数は省略しない。
        """
        self.count += 1
        self.scope[label] += 1
        if not condition:
            self.bad += 1
            if len(self.details) < 200:
                self.details.append({"場所": where, "項目": label, "実際": actual, "期待": expected})


def finite(*values) -> bool:
    """
    機能: JSON数値が有限であり、真偽値を数値として使っていないか確認する。
    引数: values (float又はintの可変長引数)。
    返り値: bool。未知の代入値を既知へ変更しない。
    """
    return all(type(value) in (int, float) and math.isfinite(value) for value in values)


def digest(path: Path) -> str:
    """
    機能: 保存再生と固定小型入力の指紋を計算する。
    引数: path (Path) はJSON又はコード。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reject_nonfinite(value: str) -> None:
    """
    機能: 保存JSONの非標準NaN/Infinityを差分保存可能な形式例外へ変える。
    引数: value (str) はJSONデコーダが検出した非有限定数。
    返り値: None。常にValueErrorを送出する。
    """
    raise ValueError("JSON非有限定数:" + value)


def scheduled(session: str) -> list[float]:
    """
    機能: 初回除外後の予定定時をJSTから独立生成する。
    引数: session (str) はYYYY-MM-DD_Day又はNight。
    返り値: list[float] はDay25枠又はNight49枠のUnix秒。
    """
    date, kind = session.split("_")
    if kind not in ("Day", "Night"):
        raise ValueError("場種はDay/Nightです")
    start = datetime.fromisoformat(date).replace(tzinfo=JST)
    start += timedelta(hours=9, minutes=15) if kind == "Day" else timedelta(hours=17, minutes=30)
    return [(start + timedelta(minutes=15 * i)).timestamp() for i in range(25 if kind == "Day" else 49)]


def classify(known: bool, value: float) -> dict:
    """
    機能: 個別の観測値を4状態へ変換し、未知の数値を削除する。
    引数: known (bool)、value (float) は既知性と実方向の値。
    返り値: dict はknown/stateと、既知時だけvalueを持つ。
    """
    if not known:
        return {"known": False, "state": "未知"}
    return {"known": True, "state": "支持" if value > 0 else "反対" if value < 0 else "中立", "value": value}


def short_state(window: dict, source: dict, evidence: dict, seconds: int, side: int) -> dict:
    """
    機能: 保存した元Shortの単位と両端を検査し、実方向pt/秒を再分類する。
    引数: window/source/evidence (dict)、seconds/side (int) は対象窓と方向。
    返り値: dict は元Knownだけに依存しない補助状態。
    """
    move, speed, elapsed = (window[name] for name in ("move", "speed", "elapsed"))
    endpoint, delay = window["endpoint"], window["delay"]
    known = window["known"] and finite(move, speed, elapsed, endpoint, delay, source["time"], source["mid"])
    if known:
        known = source["time"] == evidence["time"] and source["mid"] > 0 and source["mid"] == evidence["bid"] + (evidence["ask"] - evidence["bid"]) / 2
        known = known and elapsed >= seconds and elapsed == source["time"] - endpoint and endpoint <= source["time"] - seconds and delay == elapsed - seconds and 0 <= delay <= 15
        known = known and abs(speed - move / elapsed) <= 1e-12 * max(1, abs(speed))
    return classify(bool(known), side * speed)


def core_conditions(at: float, q: dict, t: dict, pair: dict, evidence: dict, side: int) -> dict[str, bool]:
    """
    機能: 許可に必要な当時性・主軸の各数式を保存値から独立計算する。
    引数: at (float)、q/t/pair/evidence (dict)、side (int) は片側の当時値。
    返り値: dict[str,bool] は比較範囲を明示した必須条件。
    """
    quote = finite(at, q["time"], q["last"], q["bid"], q["ask"], evidence["time"], evidence["received"], evidence["last"], evidence["bid"], evidence["ask"])
    quote = quote and q["valid"] and q["index"] >= 0 and q["last"] > 0 and q["bid"] > 0 and q["ask"] > q["bid"] and 0 <= at - q["time"] <= 15
    quote = quote and evidence["reference"] == "NK225" and evidence["time"] == q["time"] and evidence["time"] <= evidence["received"] <= at and evidence["source_line"] == q["line"] and evidence["source_line"] > 0 and evidence["source_index"] >= 0
    quote = quote and (evidence["last"], evidence["bid"], evidence["ask"]) == (q["last"], q["bid"], q["ask"])
    clock = finite(at, t["bar3_end"]) and t["bar3_end"] > 0 and 0 <= at - t["bar3_end"] <= 180
    previous = pair["previous3_known"] and finite(pair["previous_close3"], pair["previous_ema8_3"], pair["previous_bar3_end"])
    previous = previous and pair["previous_close3"] > 0 and pair["previous_ema8_3"] > 0 and pair["previous_bar3_end"] > 0 and t["bar3_end"] - pair["previous_bar3_end"] == 180
    progress = t["exit_known"] and finite(t["close3"], t["ema8_3"], t["histogram3"], t["previous_histogram3"]) and t["close3"] > 0 and t["ema8_3"] > 0
    progress = progress and side * (t["histogram3"] - t["previous_histogram3"]) > 0
    close = finite(t["close3"], t["ema8_3"]) and side * (t["close3"] - t["ema8_3"]) > 0
    price = q["ask"] if side > 0 else q["bid"]
    placement = t["atr_known"] and finite(price, t["ema8_3"], t["atr3"]) and t["ema8_3"] > 0 and t["atr3"] > 0 and 0 <= side * (price - t["ema8_3"]) <= t["atr3"]
    spike = t["spike_known"] and finite(t["tr3"], t["previous_atr3"], t["rsi3"], t["previous_rsi3"])
    spike = spike and t["tr3"] >= 0 and t["previous_atr3"] >= 0 and 0 <= t["rsi3"] <= 100 and 0 <= t["previous_rsi3"] <= 100
    spike = spike and not (t["tr3"] > 2 * t["previous_atr3"] and abs(t["rsi3"] - t["previous_rsi3"]) > 15)
    return {"自己当時値": bool(quote), "3分鮮度": bool(clock), "前足180秒結合": bool(previous), "MACD増分": bool(progress), "終値平均位置": bool(close), "0..1ATR取得": bool(placement), "同時急変除外": bool(spike)}


def trend_condition(at: float, t: dict, side: int) -> bool:
    """
    機能: 順行の複数時間軸方向と15分鮮度だけを独立確認する。
    引数: at (float)、t (dict)、side (int) は当時の確定足。
    返り値: bool は既知の3/15分方向が一致する場合に真。
    """
    values = [t[name] for name in ("ema8_3", "ema21_3", "ema8_15", "ema21_15", "bar15_end")]
    return bool(t["trend_known"] and finite(*values) and all(value > 0 for value in values) and 0 <= at - t["bar15_end"] <= 900 and side * (t["ema8_3"] - t["ema21_3"]) > 0 and side * (t["ema8_15"] - t["ema21_15"]) > 0)


def check_direction(audit: Audit, decision: dict, direction: dict, where: str, statistics: Counter) -> None:
    """
    機能: 個別補助の全状態と、許可時の主軸・順行・初動の必要条件を確認する。
    引数: audit (Audit)、decision/direction (dict)、where (str)、statistics (Counter)。
    返り値: None。全枝の未知分類・指標系列そのものの再実装は行わない。
    """
    side = direction["side"]
    audit.check(side in (-1, 1), "方向は売買符号", where, side, [-1, 1])
    if side not in (-1, 1):
        return
    at, q, t, pair, evidence = (decision[name] for name in ("at", "quote", "technical", "chart_pair", "evidence"))
    auxiliary = direction["auxiliary"]
    support = evidence["buy" if side > 0 else "sell"]
    expected = {name: short_state(evidence["short"][name], evidence["short"], evidence, seconds, side) for name, seconds in (("five", 5), ("fifteen", 15))}
    ofi_known = support["ofi_known"] and finite(support["ofi30"], support["own_at"]) and support["own_at"] == evidence["time"]
    expected["ofi"] = classify(bool(ofi_known), side * support["ofi30"])
    for name, value in expected.items():
        actual = auxiliary[name]
        selected = {key: actual[key] for key in ("known", "state", "value") if key in actual}
        audit.check(selected == value, "個別補助4状態・単位時計", where + "/" + name, selected, value)
        statistics[decision["policy"] + ":" + name + ":" + value["state"]] += 1
    known = expected["five"]["known"] and expected["fifteen"]["known"]
    slowed = known and expected["fifteen"]["value"] > 0 and expected["five"]["value"] <= .5 * expected["fifteen"]["value"]
    audit.check(auxiliary["slowdown_known"] == known and auxiliary["slowdown"] == bool(slowed), "失速は既知pt毎秒", where, [auxiliary["slowdown_known"], auxiliary["slowdown"]], [known, bool(slowed)])
    opposite = any(value["state"] == "反対" for value in expected.values())
    core = core_conditions(at, q, t, pair, evidence, side)
    trend = trend_condition(at, t, side)
    for check in direction["checks"]:
        audit.check(not check["passed"] or check["known"], "成立項目は既知", where + "/" + check["id"], [check["known"], check["passed"]], "PassedならKnown")
    if direction["allowed"]:
        for label, passed in core.items():
            audit.check(passed, "許可時主軸:" + label, where, passed, True)
        audit.check(not opposite, "許可時に既知反対なし", where, opposite, False)
        audit.check(not direction["required_unknown"], "許可時必須未知なし", where, direction["required_unknown"], False)
        if direction["role"] == "順行":
            audit.check(trend, "許可順行は3分15分方向と鮮度", where, trend, True)
        else:
            recross = pair["previous3_known"] and side * (pair["previous_close3"] - pair["previous_ema8_3"]) <= 0 and side * (t["close3"] - t["ema8_3"]) > 0
            turn = direction["role"] == "転換初動" and not trend and recross and side * (t["rsi3"] - t["previous_rsi3"]) > 0
            audit.check(bool(turn), "許可初動は実際の前足平均回復", where, [direction["role"], trend, bool(recross)], "非順行・RSI増分・同足平均回復")
            audit.check(auxiliary["structure_known"] and auxiliary["structure_support"] and auxiliary["pressure_clear"], "許可初動の保存構造支持", where, [auxiliary["structure_known"], auxiliary["structure_support"], auxiliary["pressure_clear"]], [True, True, True])
        if decision["policy"] == "B1" and slowed:
            has_support = expected["ofi"]["state"] == "支持" or (auxiliary["structure_known"] and auxiliary["structure_support"])
            audit.check(bool(has_support), "B1失速時の追加支持", where, bool(has_support), True)
    # ----------------------------------------
    # 十分条件が既知成立する順行では、不採用も隠さず検出する。
    if decision["policy"] == "B0" and all(core.values()) and trend and not opposite:
        audit.check(direction["allowed"], "B0既知順行の過剰拒否なし", where, direction["allowed"], True)
        if any(value["state"] == "未知" for value in expected.values()):
            statistics["B0:補助未知を含む十分条件順行"] += 1


def inspect_session(audit: Audit, result: dict, expected_times: list[float], statistics: Counter) -> dict:
    """
    機能: 保存1場の全予定枠・共有snapshot・政策間包含を確認する。
    引数: audit (Audit)、result (dict)、expected_times (list[float])、statistics (Counter)。
    返り値: dict は各政策の枠数と許可数。実会計の採用数とは区別する。
    """
    session = result["session"]
    grids = result["grid_decisions"]
    groups = {}
    counts = Counter()
    allowed_counts = Counter()
    audit.check(len(grids) == 2 * len(expected_times), "全予定枠の件数", session, len(grids), 2 * len(expected_times))
    for grid in grids:
        policy, at, decision = grid["entry_policy"], grid["at"], grid["decision"]
        where = session + "/" + str(at) + "/" + policy
        audit.check(policy in POLICIES, "政策集合", where, policy, list(POLICIES))
        audit.check((at, policy) not in groups, "定時政策の重複なし", where, [at, policy], "一意")
        groups[at, policy] = grid
        counts[policy] += 1
        allowed_counts[policy] += decision["allowed"]
        audit.check(at in expected_times and at == decision["at"] and decision["policy"] == policy, "判断時計と政策の結合", where, [at, decision["at"], decision["policy"]], policy)
        audit.check(grid["candidate_accepted"] == bool(grid["clock_allowed"] and decision["allowed"]), "候補供給と時計許可", where, grid["candidate_accepted"], bool(grid["clock_allowed"] and decision["allowed"]))
        audit.check(not grid["clock_allowed"] or (grid["window"] != "静観" and not grid["block_reason"]), "時計許可の保存状態", where, [grid["clock_allowed"], grid["window"], grid["block_reason"]], "許可時に静観・拒否理由なし")
        directions = decision["directions"]
        audit.check(len(directions) == 2 and {d["side"] for d in directions} == {-1, 1}, "両方向を1回ずつ評価", where, [d["side"] for d in directions], [1, -1])
        choices = [d for d in directions if d["allowed"]]
        audit.check(decision["allowed"] == (len(choices) == 1), "両方向の集約許可", where, decision["allowed"], len(choices) == 1)
        if decision["allowed"] and len(choices) == 1:
            audit.check(decision["side"] == choices[0]["side"] and decision["role"] == choices[0]["role"] and not decision["required_unknown"], "唯一許可の方向役割", where, [decision["side"], decision["role"], decision["required_unknown"]], [choices[0]["side"], choices[0]["role"], False])
        for direction in directions:
            try:
                check_direction(audit, decision, direction, where + "/" + str(direction["side"]), statistics)
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
                audit.check(False, "方向保存形式の例外", where, type(error).__name__ + ":" + str(error), "全必要fieldと数式")
    for policy in POLICIES:
        audit.check(counts[policy] == len(expected_times) and {at for at, p in groups if p == policy} == set(expected_times), "政策ごとの全予定集合", session + "/" + policy, counts[policy], len(expected_times))
    for at in expected_times:
        a, b = groups.get((at, "B0")), groups.get((at, "B1"))
        if a is None or b is None:
            continue
        where = session + "/" + str(at)
        audit.check([a["clock_allowed"], a["window"], a["block_reason"]] == [b["clock_allowed"], b["window"], b["block_reason"]], "政策間の時計共有", where)
        for key in ("quote", "technical", "chart_pair", "evidence"):
            audit.check(a["decision"][key] == b["decision"][key], "政策間snapshot共有:" + key, where)
        ad, bd = a["decision"], b["decision"]
        audit.check(not bd["allowed"] or (ad["allowed"] and ad["side"] == bd["side"] and ad["role"] == bd["role"]), "B1許可はB0同方向の部分集合", where, [ad["allowed"], ad["side"], bd["allowed"], bd["side"]], "B1許可ならB0同方向")
        for side in (-1, 1):
            av = next((d for d in ad["directions"] if d["side"] == side), None)
            bv = next((d for d in bd["directions"] if d["side"] == side), None)
            if av is not None and bv is not None:
                audit.check(av["auxiliary"] == bv["auxiliary"], "政策間補助状態共有", where + "/" + str(side))
                if not av["auxiliary"]["slowdown"]:
                    audit.check(av["allowed"] == bv["allowed"], "非失速時は同じ片側許可", where + "/" + str(side), [av["allowed"], bv["allowed"]], "追加確認を非失速へ拡張しない")
    return {"場": session, "政策枠数": dict(counts), "政策許可数": dict(allowed_counts)}


def fixture(at: float = 1000, slowdown: bool = False, support: bool = False) -> dict:
    """
    機能: 非0候補と未知補助を持つ、手計算可能な人工保存判断を作る。
    引数: at (float)、slowdown/support (bool) は当時時計と補助の状態。
    返り値: dict は2政策・2方向を持ち、Goや原板を呼ばない1枠の保存形。
    """
    q = {"time": at - 1, "index": 50, "line": 42, "last": 1005, "bid": 1000, "ask": 1010, "valid": True}
    technical = {"trend_known": True, "reversal_known": True, "spike_known": True, "exit_known": True, "atr_known": True, "ema8_3": 1000, "ema21_3": 990, "ema8_15": 1000, "ema21_15": 990, "rsi3": 55, "previous_rsi3": 54, "histogram3": 1, "previous_histogram3": .9, "close3": 1005, "tr3": 5, "atr3": 30, "previous_atr3": 30, "bar3_end": at - 10, "bar15_end": at - 10}
    pair = {"previous_close3": 995, "previous_ema8_3": 1000, "previous_bar3_end": at - 190, "previous3_known": True}
    unknown_window = {"known": False, "move": 0, "speed": 0, "elapsed": 0, "endpoint": 0, "delay": 0, "reason": "未観測"}
    short = {"time": at - 1, "mid": 1005, "five": deepcopy(unknown_window), "fifteen": deepcopy(unknown_window)}
    if slowdown:
        for name, seconds, speed in (("five", 5, .5), ("fifteen", 15, 1)):
            short[name] = {"known": True, "move": seconds * speed, "speed": speed, "elapsed": seconds, "endpoint": at - 1 - seconds, "delay": 0, "reason": "既知"}
    source_support = {"ofi_known": support, "own_at": at - 1, "ofi30": .01 if support else 0}
    evidence = {"reference": "NK225", "time": at - 1, "received": at - 1, "source_index": 40, "source_line": 42, "last": q["last"], "bid": q["bid"], "ask": q["ask"], "buy": deepcopy(source_support), "sell": deepcopy(source_support), "short": short}
    grids = []
    for policy in POLICIES:
        chosen = policy == "B0" or not slowdown or support
        directions = []
        for side in (1, -1):
            auxiliary = {name: short_state(short[name], short, evidence, seconds, side) for name, seconds in (("five", 5), ("fifteen", 15))}
            auxiliary["ofi"] = classify(support, side * evidence["buy"]["ofi30"])
            auxiliary.update({"slowdown_known": slowdown, "slowdown": slowdown and side > 0, "structure_known": False, "structure_support": False, "pressure_clear": False})
            directions.append({"side": side, "allowed": side > 0 and chosen, "role": "順行" if side > 0 and chosen else "待機", "required_unknown": side > 0 and not chosen, "checks": [], "auxiliary": auxiliary})
        decision = {"at": at, "policy": policy, "allowed": chosen, "side": 1 if chosen else 0, "role": "順行" if chosen else "判定不能", "required_unknown": not chosen, "quote": deepcopy(q), "technical": deepcopy(technical), "chart_pair": deepcopy(pair), "evidence": deepcopy(evidence), "directions": directions}
        grids.append({"at": at, "entry_policy": policy, "clock_allowed": True, "window": "D164_15", "block_reason": "", "candidate_accepted": chosen, "decision": decision})
    return {"session": "人工_Day", "grid_decisions": grids}


def mirror_fixture(saved: dict) -> dict:
    """
    機能: 人工保存の全価格を反射し、全方向を反転する。
    引数: saved (dict) は買い主体の人工保存判断。
    返り値: dict は補助の実方向状態を保った売り主体の独立複写。
    """
    result = deepcopy(saved)
    pivot = 2000
    for grid in result["grid_decisions"]:
        decision = grid["decision"]
        decision["side"] = -decision["side"]
        q, t, pair, evidence = (decision[name] for name in ("quote", "technical", "chart_pair", "evidence"))
        for prices in (q, evidence):
            prices["last"], prices["bid"], prices["ask"] = pivot - prices["last"], pivot - prices["ask"], pivot - prices["bid"]
        for name in ("ema8_3", "ema21_3", "ema8_15", "ema21_15", "close3"):
            t[name] = pivot - t[name]
        for name in ("rsi3", "previous_rsi3"):
            t[name] = 100 - t[name]
        for name in ("histogram3", "previous_histogram3"):
            t[name] = -t[name]
        for name in ("previous_close3", "previous_ema8_3"):
            pair[name] = pivot - pair[name]
        evidence["buy"], evidence["sell"] = evidence["sell"], evidence["buy"]
        for name in ("buy", "sell"):
            evidence[name]["ofi30"] = -evidence[name]["ofi30"]
        evidence["short"]["mid"] = pivot - evidence["short"]["mid"]
        for name in ("five", "fifteen"):
            evidence["short"][name]["move"] = -evidence["short"][name]["move"]
            evidence["short"][name]["speed"] = -evidence["short"][name]["speed"]
        for direction in decision["directions"]:
            direction["side"] = -direction["side"]
    return result


def self_test() -> dict:
    """
    機能: 非0正常・失速・1bit破損・未来・包含破壊を人工検査する。
    引数: なし。
    返り値: dict は成功した人工系列と原板・売買再生0の証拠。
    """
    evidence = []
    for name, saved in (("未知補助でも非0順行", fixture()), ("既知失速はB1だけ追加支持", fixture(slowdown=True)), ("既知失速と正OFI支持", fixture(slowdown=True, support=True))):
        audit = Audit()
        inspect_session(audit, saved, [1000], Counter())
        assert audit.bad == 0, (name, audit.details)
        evidence.append({"人工": name, "比較": audit.count, "差": audit.bad})
        reflected = Audit()
        inspect_session(reflected, mirror_fixture(saved), [1000], Counter())
        assert reflected.bad == 0, (name + "売買鏡像", reflected.details)
        evidence.append({"人工": name + "売買鏡像", "比較": reflected.count, "差": reflected.bad})
    changes = []
    broken = fixture()
    broken["grid_decisions"][1]["decision"]["quote"]["last"] += 1
    changes.append(("共有snapshotの1値破壊", broken))
    broken = fixture()
    broken["grid_decisions"][0]["candidate_accepted"] = False
    changes.append(("候補供給1bit破壊", broken))
    broken = fixture()
    broken["grid_decisions"][0]["decision"]["technical"]["bar3_end"] = 1001
    changes.append(("未来3分足", broken))
    broken = fixture()
    broken["grid_decisions"][0]["decision"]["technical"]["bar15_end"] = 1001
    changes.append(("未来15分足", broken))
    broken = fixture()
    broken["grid_decisions"][0]["decision"]["directions"][0]["auxiliary"]["five"] = {"known": True, "state": "中立", "value": 0}
    changes.append(("未知を既知0へ破壊", broken))
    broken = fixture(slowdown=True, support=True)
    broken["grid_decisions"][0]["decision"]["evidence"]["short"]["five"]["speed"] = 2.5
    changes.append(("pt毎秒を窓幅へ破壊", broken))
    broken = fixture()
    broken["grid_decisions"][0]["decision"]["allowed"] = False
    broken["grid_decisions"][0]["decision"]["directions"][0]["allowed"] = False
    broken["grid_decisions"][0]["candidate_accepted"] = False
    changes.append(("B1部分集合破壊とB0過剰拒否", broken))
    broken = fixture()
    broken["grid_decisions"][0]["decision"]["chart_pair"]["previous_bar3_end"] -= 180
    changes.append(("前足の非連続", broken))
    broken = fixture()
    broken["grid_decisions"].append(deepcopy(broken["grid_decisions"][0]))
    changes.append(("定時政策の重複", broken))
    broken = fixture(slowdown=True)
    b1 = broken["grid_decisions"][1]
    b1["candidate_accepted"] = True
    b1["decision"].update(allowed=True, side=1, role="順行", required_unknown=False)
    b1["decision"]["directions"][0].update(allowed=True, role="順行", required_unknown=False)
    changes.append(("B1失速時の追加支持なし誤許可", broken))
    for name, saved in changes:
        audit = Audit()
        inspect_session(audit, saved, [1000], Counter())
        assert audit.bad > 0, name
        evidence.append({"破損人工": name, "検出": audit.bad})
    assert len(scheduled("2026-11-02_Day")) == 25 and len(scheduled("2026-11-02_Night")) == 49
    evidence.append({"人工": "初回除外のDay25枠Night49枠", "成功": True})
    for session in ("2026-11-02_Day", "2026-11-02_Night"):
        times = scheduled(session)
        saved = {"session": session, "grid_decisions": [grid for at in times for grid in fixture(at)["grid_decisions"]]}
        audit = Audit()
        summary = inspect_session(audit, saved, times, Counter())
        assert audit.bad == 0 and summary["政策許可数"] == {"B0": len(times), "B1": len(times)}, (session, audit.details)
        evidence.append({"人工": session + "全予定非0許可", "比較": audit.count, "差": audit.bad, "政策枠数": summary["政策枠数"]})
    return {"成功": True, "系列": len(evidence), "人工": evidence, "本物原板読取": 0, "新売買再生": 0}


def main() -> None:
    """
    機能: 全66場の保存判断だけを監査し、新規JSONへ差分と指紋を保存する。
    引数: --input/--out (Path) 又は --self-test (bool) を明示する。
    返り値: None。正式不一致は証拠保存後に終了1、既存出力は上書きしない。
    """
    parser = argparse.ArgumentParser(description="82の保存判断の独立監査")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if args.input or args.out:
            parser.error("人工と正式入力を同時指定しません")
        print(json.dumps(self_test(), ensure_ascii=False))
        return
    if args.input is None or args.out is None:
        parser.error("正式監査はinputとoutを明示します")
    if args.out.exists():
        raise FileExistsError("監査証拠を上書きしません")
    manifest_path = ROOT / "study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
    condition_path = ROOT / "study/00082_チャートの現在性と補助確認/条件.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    condition = json.loads(condition_path.read_text(encoding="utf-8"))
    audit = Audit()
    ids = [row["id"] for row in manifest["sessions"]]
    audit.check(len(ids) == len(set(ids)) == 66, "66場の固定入力集合", "全体", len(ids), 66)
    audit.check(condition["入力台帳SHA256"] == digest(manifest_path), "82条件と固定台帳の結合", "全体", condition["入力台帳SHA256"], digest(manifest_path))
    expected_paths = {session + ".json" for session in ids}
    found = {path.name for path in args.input.glob("*.json")}
    audit.check(found == expected_paths, "保存再生66場の過不足", "全体", {"不足": sorted(expected_paths - found), "余計": sorted(found - expected_paths)}, "固定66場だけ")
    hashes, sessions, statistics = {}, [], Counter()
    before_count = audit.count
    for session in ids:
        path = args.input / (session + ".json")
        if not path.exists():
            continue
        hashes[path.name] = digest(path)
        try:
            saved = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_nonfinite)
            audit.check(saved["session"] == session, "場IDとファイル結合", session, saved["session"], session)
            sessions.append(inspect_session(audit, saved, scheduled(session), statistics))
        except (KeyError, TypeError, ValueError) as error:
            audit.check(False, "場保存形式の例外", session, type(error).__name__ + ":" + str(error), "固定保存形式")
    total = {policy: sum(row["政策枠数"].get(policy, 0) for row in sessions) for policy in POLICIES}
    audit.check(total == {"B0": 2442, "B1": 2442}, "全政策2442予定枠", "全体", total, {"B0": 2442, "B1": 2442})
    after = {name: digest(args.input / name) for name in hashes}
    audit.check(hashes == after, "保存再生入力不変", "全体", hashes == after, True)
    value = {"試行": 82, "成功": audit.bad == 0, "場数": len(sessions), "政策予定枠": total, "照合項目数": audit.count,
        "不一致数": audit.bad, "不一致": audit.details, "項目別比較数": dict(audit.scope), "補助状態等": dict(statistics),
        "対象場": sessions, "入力再生SHA256": hashes, "入力不変": hashes == after,
        "入力台帳SHA256": digest(manifest_path), "固定条件SHA256": digest(condition_path), "監査コードSHA256": digest(Path(__file__)),
        "確認範囲": "全予定枠・A/B同時点共有・候補供給・B1包含・個別補助4状態/速度単位/両端・失速・許可時主軸/順行/初動の必要条件・B0既知順行の過剰拒否。",
        "範囲外": "元指標系列とShort/OFIを原板から再算出すること、保存した初動構造の全生成過程、Goの全未知分類の別実装。初動構造は保存された構造支持旗の必要条件を照合。",
        "本物原板読取": 0, "新売買再生": 0, "新アルゴリズム選択": 0, "保存判断比較数": audit.count - before_count}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: value[key] for key in ("成功", "場数", "政策予定枠", "照合項目数", "不一致数")}, ensure_ascii=False))
    if audit.bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
