"""96純技法の公開保存入力を独立した三値式で照合する。金融/原板は運転しない。"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import math


def need(condition: bool, message: str) -> None:
    """
    機能: 不一致停止。
    引数: condition(bool)/message(str)。
    返り値: None。
    """
    if not condition:
        raise ValueError(message)


def f(value) -> float:
    """
    機能: Go同様のfloat64値。
    引数: value(number)。
    返り値: float/不正なら例外。
    """
    need(type(value) in (int, float, Decimal), "技法の数値型")
    result = float(value)
    need(math.isfinite(result), "技法の非有限値")
    return result


def finite_tree(value) -> None:
    """
    機能: 未使用fieldを含む有限性検査。
    引数: value(object)。
    返り値: None。
    """
    if isinstance(value, dict):
        for item in value.values(): finite_tree(item)
    elif isinstance(value, list):
        for item in value: finite_tree(item)
    elif type(value) in (int, float, Decimal):
        f(value)


def flag(value) -> bool:
    """
    機能: boolを数値と分離。
    引数: value(object)。
    返り値: bool/例外。
    """
    need(type(value) is bool, "技法のbool型")
    return value


def check(identity: str, known: bool, passed: bool, reason: str) -> dict:
    """
    機能: 未知Passedを偽へ正規化。
    引数: id/known/passed/reasonはstr/bool/bool/str。
    返り値: dictは個別check。
    """
    return {"id": identity, "known": known, "passed": known and passed, "reason": reason}


def conjunction(checks: list[dict]) -> tuple[bool, bool]:
    """
    機能: 既知否定優先AND。
    引数: checks(list)。
    返り値: known/passed(bool組)。
    """
    if any(c["known"] and not c["passed"] for c in checks): return True, False
    known = all(c["known"] for c in checks)
    return known, known


def validate_technical(t: dict) -> None:
    """
    機能: 固定指標の範囲と既知価格検査。
    引数: t(dict)。
    返り値: None。
    """
    for name in ("bar3_end", "bar15_end", "close3", "tr3", "atr3", "previous_atr3", "ema8_3", "ema21_3", "ema8_15", "ema21_15"):
        need(f(t[name]) >= 0, "技法の負価格/幅/時計: " + name)
    for name in ("rsi3", "previous_rsi3"):
        need(0 <= f(t[name]) <= 100, "RSI範囲")
    for name in ("trend_known", "exit_known", "reversal_known", "spike_known", "atr_known"):
        flag(t[name])
    if t["trend_known"]:
        need(all(f(t[n]) > 0 for n in ("ema8_3", "ema21_3", "ema8_15", "ema21_15")), "既知EMAの非正価格")
    if t["exit_known"] or t["reversal_known"]:
        need(f(t["ema8_3"]) > 0 and f(t["close3"]) > 0, "既知出口/反転の価格")
    if t["spike_known"]: need(f(t["close3"]) > 0, "既知Spikeの価格")


def validate_snapshot(s: dict, at: float) -> None:
    """
    機能: 公開出典と半開足の検査。
    引数: s(dict)/at(float)。
    返り値: None。
    """
    a, t, c = f(s["at"]), s["chart"]["Technical"], s["chart"]
    for name in ("has_observed_clock","has_last_input","carried_numeric_seed","sealed"): flag(s[name])
    need(0 <= a <= at and 0 <= f(s["invalidated_at"]) <= at and 0 <= f(s["scene"]["start"]) <= a, "未来snapshot")
    need(f(t["bar3_end"]) <= a and f(t["bar15_end"]) <= a, "未来確定足")
    validate_technical(t)
    if flag(s["has_last_input"]):
        q = s["last_input"]
        need(0 < f(q["time"]) <= a and type(q["index"]) is int and type(q["line"]) is int and q["index"] >= 0 and q["line"] > 0, "snapshot最終原行")
        if flag(q["valid"]): need(f(q["last"]) > 0, "既知Last")
    for e in (s["three"], s["fifteen"]):
        need(0 <= f(e["bar_end"]) <= f(e["available_at"]) <= a and type(e["rows"]) is int and e["rows"] >= 0, "足公開/入力数")
        if flag(e["data_known"]): need(e["bar_end"] > 0 and e["rows"] > 0 and flag(e["has_last_source"]), "足既知性")
        if flag(e["has_last_source"]):
            q = e["last_source"]
            need(0 < f(q["time"]) < f(e["bar_end"]) and type(q["index"]) is int and type(q["line"]) is int and q["index"] >= 0 and q["line"] > 0, "足最終原行")
            if e["data_known"]: need(flag(q["valid"]) and f(q["last"]) > 0, "足の正常Last")
    need(s["three"]["bar_end"] == t["bar3_end"] and s["fifteen"]["bar_end"] == t["bar15_end"], "足終端結合")
    need(0 <= f(c["PreviousBar3End"]) <= a, "前足の未来")
    if flag(c["Previous3Known"]):
        need(f(c["PreviousClose3"]) > 0 and f(c["PreviousEMA8_3"]) > 0 and f(t["bar3_end"]) - f(c["PreviousBar3End"]) == 180, "前3分の価格/連続性")


def validate_current_times(current: dict, at: float) -> None:
    """
    機能: 全共有Current出典の未来を拒否。
    引数: current(dict)/at(float)。
    返り値: None。
    """
    need(0 <= f(current["time"]) <= at and 0 <= f(current["received"]) <= at, "共有Currentの未来")
    for support in (current["buy"], current["sell"]):
        for name in ("own_at", "peer_at"):
            need(0 <= f(support[name]) <= f(current["time"]), "支持出典の未来")
        for window in (support.get("windows") or {}).values():
            need(all(0 <= f(window[n]) <= f(current["time"]) for n in ("current_at", "endpoint_at")), "支持窓の未来")
    night = current["night"]
    for owner, names in ((night, ("time",)), (night["band"], ("time", "start_time"))):
        need(all(0 <= f(owner[n]) <= f(current["time"]) for n in names), "E08出典の未来")
    for hold in (night["buy"], night["sell"]):
        for owner in (hold, hold["barrier"], hold["support"]):
            need(0 <= f(owner["time"]) <= f(current["time"]), "保持帯出典の未来")
    short = current["short"]
    for owner, name in ((short, "time"), (short["five"], "endpoint"), (short["fifteen"], "endpoint")):
        need(0 <= f(owner[name]) <= f(current["time"]), "短秒の未来")
    need(all(f(night["band"][n]) >= 0 for n in ("bid_refill", "ask_refill", "bid_deplete", "ask_deplete")), "負数量変化")


def validate(incoming: dict, candidate: dict, policy: str) -> None:
    """
    機能: 技法入力と候補の同原行を検査。
    引数: input_value(dict)、candidate(dict)、policy(str)。
    返り値: None。不整合は例外。
    """
    finite_tree(incoming); finite_tree(candidate)
    need(policy in ("A", "B", "AB"), "技法政策")
    at, s, q, current = f(incoming["at"]), incoming["chart"], candidate["quote"], incoming["current"]
    need(type(incoming["snapshot_id"]) is str and incoming["snapshot_id"] and at > 0 and at == f(candidate["at"]) == f(s["at"]) and incoming["kind"] in ("Day", "Night"), "技法の枠/ID")
    need(s["scene"]["id"] and s["scene"]["contract"] and f(s["scene"]["start"]) > 0, "技法のScene")
    need(type(candidate["side"]) is int and candidate["side"] in (-1, 1), "候補方向")
    need(0 < f(q["time"]) <= at and q["index"] >= 0 and q["source_line"] > 0 and flag(q["quote_ok"]) and f(q["last"]) > 0 and 0 < f(q["bid"]) < f(q["ask"]), "候補の正常気配")
    for left, right in (("time", "time"), ("source_index", "index"), ("source_line", "source_line"), ("last", "last"), ("bid", "bid"), ("ask", "ask")):
        need(current[left] == q[right], "特徴と候補の同原行: " + left)
    need(0 <= f(current["received"]) <= at, "現在特徴のReceived")
    validate_current_times(current, at)
    validate_snapshot(s, at)
    need(isinstance(incoming["recent3"], list) and len(incoming["recent3"]) <= 3, "直近3足窓")
    for i, old in enumerate(incoming["recent3"]):
        validate_snapshot(old, at)
        need(old["scene"] == s["scene"] and old["at"] == old["three"]["bar_end"] and (i == 0 or old["at"] > incoming["recent3"][i-1]["at"]), "直近足の順序/場")


def assess(incoming: dict, candidate: dict, policy: str) -> dict:
    """
    機能: A/B/AB純採否を独立計算。
    引数: input_value(dict)、candidate(dict)、policy(str)。
    返り値: dictはdecisionとchecks。
    """
    validate(incoming, candidate, policy)
    s, at, chart = candidate["side"], f(incoming["at"]), incoming["chart"]
    c, t = chart["chart"], chart["chart"]["Technical"]
    e = f(candidate["quote"]["ask" if s == 1 else "bid"])
    three = chart["three"]["data_known"] and t["bar3_end"] > 0 and at-f(t["bar3_end"]) < 180
    fifteen = chart["fifteen"]["data_known"] and t["bar15_end"] > 0 and at-f(t["bar15_end"]) < 900
    common = [
        check("共通.現在価格時計", at-f(candidate["quote"]["time"]) <= 15, True, "候補とCurrentの同原行を検査済み・価格時計は15秒以内"),
        check("共通.確定3分", three, True, "当場の既知確定足・終端以下で足齢180秒未満"),
        check("共通.確定15分", fifteen, True, "当場の既知確定足・終端以下で足齢900秒未満"),
        check("共通.EMA背景既知", three and fifteen and t["trend_known"], True, "固定APIのTrendKnownを使用・EMA15単独の既知性は推測しない"),
        check("共通.MACD増分", three and t["exit_known"], s*(f(t["histogram3"])-f(t["previous_histogram3"])) > 0, "3分ヒストグラム増分が候補方向へstrict正"),
        check("共通.終値とEMA8", three and t["exit_known"], s*(f(t["close3"])-f(t["ema8_3"])) > 0, "確定終値は現在EMA8の候補方向側"),
        check("共通.取得位置ATR", three and t["exit_known"] and t["atr_known"] and t["atr3"] > 0,
              0 <= s*(e-f(t["ema8_3"])) <= f(t["atr3"]), "取得側気配の符号付きEMA8距離が0以上1ATR以下・等号許容"),
        check("共通.同時スパイク警戒", three and t["spike_known"], not (f(t["tr3"]) > 2*f(t["previous_atr3"]) and abs(f(t["rsi3"])-f(t["previous_rsi3"])) > 15), "TR>前ATRの2倍 AND RSI変化絶対値>15のみ拒否・RSI水準単独では拒否しない"),
    ]
    current = incoming["current"]
    if incoming["kind"] == "Day":
        volume = current["buy" if s == 1 else "sell"]
        volume_known = flag(volume["ofi_known"]) and volume["own_at"] == current["time"]
        volume_pass = s*f(volume["ofi30"]) > 0
        reason = "当原行OwnAtの既知OFI30に候補方向を掛けstrict正・約定出来高ではない"
    else:
        night, volume = current["night"], current["night"]["band"]
        volume_known = flag(night["available"]) and night["window"] == "E08" and flag(volume["quantity_known"]) and volume["time"] == current["time"] and volume["index"] == current["source_index"]
        volume_pass = s*(f(volume["bid_refill"])+f(volume["ask_deplete"])-f(volume["ask_refill"])-f(volume["bid_deplete"])) > 0
        reason = "同時刻/同FeaturesIndexのE08数量変化4成分の符号差・約定出来高ではない"
    common.append(check("共通.現在量支持", volume_known, volume_pass, reason))
    a = [
        check("A.3分EMA方向", three and t["trend_known"], s*(f(t["ema8_3"])-f(t["ema21_3"])) > 0, "EMA8とEMA21の差が候補方向へstrict正"),
        check("A.15分EMA方向", fifteen and t["trend_known"], s*(f(t["ema8_15"])-f(t["ema21_15"])) > 0, "上位EMA背景も候補方向へstrict正"),
        check("A.確定終値進行", three and flag(c["Previous3Known"]), s*(f(t["close3"])-f(c["PreviousClose3"])) > 0, "連続する直前3分確定終値より候補方向へ進む"),
    ]
    b = [check("B.15分EMA逆背景", fifteen and t["trend_known"], s*(f(t["ema8_15"])-f(t["ema21_15"])) < 0, "候補方向は上位EMA8/21のstrict逆・Source方向は変更しない")]
    recent = incoming["recent3"]
    known = len(recent) == 3 and t["exit_known"] and t["spike_known"]
    if known:
        known = all(p["three"]["data_known"] and p["three"]["bar_end"] == p["at"] and (i == 0 or f(p["at"])-f(recent[i-1]["at"]) == 180) for i,p in enumerate(recent))
        ta,tb,tc = (p["chart"]["Technical"] for p in recent)
        known = known and (ta["trend_known"] or ta["exit_known"] or ta["reversal_known"]) and (tb["spike_known"] or tb["reversal_known"]) and (tc["spike_known"] or tc["reversal_known"])
        known = known and recent[2]["at"] == t["bar3_end"]
        if known: need(all(recent[2]["chart"]["Technical"][n] == t[n] for n in ("close3", "ema8_3", "rsi3")), "直近c足と現在値")
    b.append(check("B.固定3足窓", known, True, "同場の最新a/b/cだけ・各足終端差180秒・空足/欠足/助走不足を補完しない"))
    ac = bc = cc = br = cr = level = 0.0
    if known:
        ta,tb,tc = (p["chart"]["Technical"] for p in recent)
        ac,bc,cc,br,cr,level = (f(x) for x in (ta["close3"],tb["close3"],tc["close3"],tb["rsi3"],tc["rsi3"],ta["ema8_3"]))
    for identity, passed, reason in (
        ("B.a足は固定線反対側", s*(ac-level) <= 0, "L=a時点EMA8固定・a終値は反対側又は同値"),
        ("B.b足で固定線奪還", s*(bc-level) > 0, "b確定終値が固定Lの候補方向側へstrict移行"),
        ("B.c足で固定線維持", s*(cc-level) > 0, "別の後足cでも固定L方向側を維持・後のEMAで線を更新しない"),
        ("B.c足で価格再進行", s*(cc-bc) > 0, "c終値がb終値から候補方向へstrict進行"),
        ("B.c足でRSI再進行", s*(cr-br) > 0, "cのRSIがbから候補方向へstrict進行"),
        ("B.現在取得側も固定線方向", s*(e-level) > 0, "取得側気配も固定Lの候補方向側・Side反転なし"),
    ): b.append(check(identity, known, passed, reason))
    state_a, state_b = conjunction(common+a), conjunction(common+b)
    state, checks, role = state_a, common+a, "順行"
    if policy == "B": state,checks,role = state_b,common+b,"反転"
    if policy == "AB":
        checks = common+a+b
        if state_a == (True, True): state,role = state_a,"順行"
        elif state_b == (True, True): state,role = state_b,"反転"
        else: state = (state_a[0] and state_b[0], False)
    known, passed = state
    role,reason = (role,"公開済み複合テクニカルが成立") if passed else ("待機","公開済みの必要条件が不成立") if known else ("判定不能","既知の否定条件はなく採否に必要な値が未知")
    return {"decision": {"policy":policy,"snapshot_id":incoming["snapshot_id"],"known":known,"allowed":passed,"role":role,"reason":reason}, "checks":checks}


class GateIndex:
    """全共有入力と適格出生のassessmentを一度ずつ独立結合する。"""

    def __init__(self, value: dict):
        """
        機能: 共有出典を索引化。
        引数: value(dict)。
        返り値: None。
        """
        self.grids, self.records, self.used = {}, {}, set()
        self.check_counts = defaultdict(Counter)
        previous = None
        for row in value["chart_grids"]:
            need(set(row) == {"snapshot_id","at","kind","chart","recent3","current"}, "ChartGrid schema")
            finite_tree(row)
            need(row["snapshot_id"] and row["kind"] in ("Day","Night") and row["at"] == row["chart"]["at"], "ChartGrid識別/時計")
            validate_snapshot(row["chart"], f(row["at"]))
            validate_current_times(row["current"], f(row["at"]))
            need(isinstance(row["recent3"],list) and len(row["recent3"]) <= 3, "共有直近足の型/数")
            for i, recent in enumerate(row["recent3"]):
                validate_snapshot(recent,f(row["at"]))
                need(recent["scene"] == row["chart"]["scene"] and recent["at"] == recent["three"]["bar_end"] and (i == 0 or recent["at"] > row["recent3"][i-1]["at"]), "共有直近足の場/順序")
            need(row["snapshot_id"] not in self.grids and (previous is None or row["at"] > previous), "ChartGridのID/時計一意")
            self.grids[row["snapshot_id"]] = row; previous = row["at"]
        for record in value["gate_assessments"]:
            need(set(record) == {"key","ordinal","source","assessment"}, "GateAssessment schema")
            need(type(record["key"]) is str and type(record["ordinal"]) is int and record["ordinal"] > 0, "GateAssessmentのkey/ordinal型")
            identity = record["key"], record["ordinal"]
            need(identity not in self.records, "GateAssessment重複")
            self.records[identity] = record

    def claim(self, key: str, p: dict) -> dict:
        """
        機能: 適格候補の1判定を消費。
        引数: key(str)、p(dict)はRaw又は保存から再構築した候補。
        返り値: dictは技法decision。
        """
        identity = key,p["ordinal"]
        need(identity in self.records and identity not in self.used, "適格出生の判定欠落/重複")
        r = self.records[identity]; need(r["source"] == p["source"], "GateAssessment出生出典")
        saved = r["assessment"]
        need(set(saved) == {"decision","checks"}, "Assessment schema")
        need(set(saved["decision"]) == {"policy","snapshot_id","known","allowed","role","reason"}, "GateDecision schema")
        for name in ("known","allowed"): flag(saved["decision"][name])
        need(isinstance(saved["checks"],list), "checks型")
        for item in saved["checks"]:
            need(set(item) == {"id","known","passed","reason"}, "GateCheck schema")
            flag(item["known"]); flag(item["passed"])
        snapshot_id = saved["decision"]["snapshot_id"]
        need(snapshot_id in self.grids, "GateAssessmentの共有snapshot欠落")
        incoming = self.grids[snapshot_id]
        candidate = {"ordinal":p["ordinal"],"at":p["evaluated_at"],"side":p["side"],"source":p["source"],"quote":p["quote"],"available":p["available"],"quantity":min(p["source"]["birth_quantity"],p["source_quantity"],p["available"])}
        policy = key.split("_")[0]
        result = assess(incoming,candidate,policy)
        need(saved == result, "独立技法の全checks/decision相違: " + str(identity))
        for row in result["checks"]:
            self.check_counts[key+"/"+row["id"]]["成立" if row["known"] and row["passed"] else "既知不成立" if row["known"] else "未知"] += 1
        self.used.add(identity)
        return result["decision"]

    def finish(self, clock_rows: list) -> dict:
        """
        機能: 孤立判定と枠欠落を拒否。
        引数: clock_rows(list[dict])は枠の保存列。
        返り値: dictは条件計数。
        """
        need(self.used == set(self.records), "非適格/孤立GateAssessment")
        need([g["at"] for g in self.grids.values()] == clock_rows, "ChartGridと金融枠の全列")
        return {"共有枠":len(self.grids),"適格出生判定":len(self.used),"条件別":{name:dict(row) for name,row in self.check_counts.items()}}
