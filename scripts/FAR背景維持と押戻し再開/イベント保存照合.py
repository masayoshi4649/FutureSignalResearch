"""88の疎な公開入力から背景・押し・回復・確認を独立再構成する。

元指標数値器そのものの独立実装ではない。入力Close/TR/Last不良の原板結合は
同フォルダのSource通知監査が担当し、本ファイルは順序・失効・期限を検査する。
"""

from copy import deepcopy
import math


INPUT_FIELDS = {"ordinal", "at", "origin", "window", "epoch_start", "after_eof", "quote", "technical"}
RECORD_FIELDS = {"id", "kind", "input"}
QUOTE_FIELDS = {"time", "index", "line", "last", "bid", "ask", "valid"}
TECH_FLAGS = {"trend_known", "reversal_known", "spike_known", "exit_known", "atr_known"}
TECH_VALUES = {"ema8_3", "ema21_3", "ema8_15", "ema21_15", "rsi3", "previous_rsi3", "histogram3", "previous_histogram3", "close3", "tr3", "atr3", "previous_atr3", "bar3_end", "bar15_end"}
ACTIVE_WINDOWS = {"D164_15", "P164_06", "U165_03"}


def require(condition: bool, reason: str) -> None:
    """
    機能: 入力矛盾・不足を通常の未知へ変換せず拒否する。
    引数: condition(bool)、reason(str)は成立条件と日本語理由。
    返り値: None。不成立時はValueError。
    """
    if not condition:
        raise ValueError(reason)


def finite(value: object) -> bool:
    """
    機能: boolを除く有限JSON数値だけを識別する。
    引数: value(object)は保存値。
    返り値: boolは有限int/floatなら真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def technical_known(v: dict) -> bool:
    """
    機能: 順序状態の価格・勢い・急変が判定できる公開値か確認する。
    引数: v(dict)は固定数値器のTechnicalView。
    返り値: boolは段階評価に必要な既知性が揃えば真。
    """
    return (v["trend_known"] and v["reversal_known"] and v["spike_known"]
            and all(v[k] > 0 for k in ("close3", "ema8_3", "ema21_3", "ema8_15", "ema21_15"))
            and v["previous_atr3"] >= 0 and v["tr3"] >= 0
            and 0 <= v["rsi3"] <= 100 and 0 <= v["previous_rsi3"] <= 100)


def validate_technical(at: float, v: dict) -> None:
    """
    機能: 既知値の価格・RSI・値幅矛盾と未来公開を拒否する。
    引数: at(float)、v(dict)は公開時計とTechnicalView。
    返り値: None。未知値を正常な既知値へ補正しない。
    """
    require(set(v) == TECH_FLAGS | TECH_VALUES and all(type(v[k]) is bool for k in TECH_FLAGS) and all(finite(v[k]) for k in TECH_VALUES), "イベント指標全field型")
    require(0 <= v["bar3_end"] <= at and 0 <= v["bar15_end"] <= at, "イベント足終端非未来")
    require(not v["trend_known"] or (all(v[k] > 0 for k in ("ema8_3", "ema21_3", "ema8_15", "ema21_15")) and v["bar3_end"] > 0 and v["bar15_end"] > 0), "既知背景の価格/公開時計")
    require(not (v["exit_known"] or v["reversal_known"]) or (v["close3"] > 0 and v["ema8_3"] > 0 and v["bar3_end"] > 0), "既知価格の矛盾")
    require(not (v["reversal_known"] or v["spike_known"]) or (0 <= v["rsi3"] <= 100 and 0 <= v["previous_rsi3"] <= 100), "既知RSIの範囲")
    require(not v["spike_known"] or (v["previous_atr3"] >= 0 and v["tr3"] >= 0), "既知急変値幅非負")
    require(not v["atr_known"] or v["atr3"] >= 0, "既知ATR非負")


def empty_state(side: int, reason: str, unknown: bool = False) -> dict:
    """
    機能: 出典を持たない方向別背景待ち状態を作る。
    引数: side(int)、reason(str)、unknown(bool)は方向・理由・必要未知。
    返り値: dictはGo保存schemaと同じnullを持つ独立値。
    """
    return {"side": side, "stage": "背景待ち", "reason": reason, "required_unknown": unknown,
            "impulse": None, "pullback": None, "recovery": None, "confirmation": None,
            "event": None, "event_valid": False}


class Sequence:
    """疎な公開入力だけから二方向の因果順と失効を追跡する。"""

    def __init__(self) -> None:
        """
        機能: 場間carryのない新しい順序状態を初期化する。
        引数: なし。
        返り値: None。市場・金融へ接続しない。
        """
        self.states = [empty_state(s, "当場の確定足を未観測", True) for s in (1, -1)]
        self.last = None
        self.last_bar = None
        self.last_unknown = False
        self.eof = False
        self.count = 0

    def clear(self, reason: str, unknown: bool) -> None:
        """
        機能: 両方向の出典とeventを失効させる。
        引数: reason(str)、unknown(bool)は失効理由と必要未知。
        返り値: None。数値器やSourceの状態を変更しない。
        """
        self.states = [empty_state(s, reason, unknown) for s in (1, -1)]

    def advance_direction(self, state: dict, observation: dict, point: dict) -> dict:
        """
        機能: 一つの正常確定足を独立の四段階へ適用する。
        引数: state/observation/point(dict)は直前状態・当時入力・公開点。
        返り値: dictは更新後の方向状態。現在足でkを若返らせない。
        """
        v, side = observation["technical"], state["side"]
        background = side * (v["ema8_15"] - v["ema21_15"]) > 0
        price = side * (v["close3"] - v["ema8_3"]) > 0
        momentum = side * (v["histogram3"] - v["previous_histogram3"]) > 0 and side * (v["rsi3"] - v["previous_rsi3"]) > 0
        spike = v["tr3"] > 2 * v["previous_atr3"] and abs(v["rsi3"] - v["previous_rsi3"]) > 15
        if not background:
            return empty_state(side, "15分背景が同方向を支持しない")
        state["required_unknown"] = False
        if state["event"] is not None and not price:
            updated = empty_state(side, "再開後の再押しで旧event失効")
            updated.update(stage="押し", impulse=deepcopy(state["event"]["confirmation"]), pullback=deepcopy(point))
            return updated
        stage = state["stage"]
        if stage == "背景待ち":
            if price and momentum:
                state.update(stage="推進", reason="背景内の価格と勢いの推進を観測", impulse=deepcopy(point))
            else:
                state["reason"] = "背景支持下の推進を待つ"
        elif stage == "推進":
            if not price:
                state.update(stage="押し", reason="平均逆側への押しを観測", pullback=deepcopy(point))
        elif stage in ("押し", "価格回復"):
            if not price:
                state.update(stage="押し", pullback=deepcopy(point))
                if stage == "押し":
                    state["reason"] = "押しの最新確定足を更新"
                else:
                    state.update(reason="再押しで価格回復を破棄", recovery=None)
                return state
            if stage == "押し":
                state.update(stage="価格回復", reason="価格回復後の勢い確認を待つ", recovery=deepcopy(point))
            if momentum and not spike:
                state.update(stage="再開", reason="価格回復後の勢いと非急変を確認", confirmation=deepcopy(point), event_valid=True)
                state["event"] = {"id": f"E{point['observation_id']:06d}_S{side}", "side": side,
                                  "window": observation["window"], "epoch_start": observation["epoch_start"],
                                  **{k: deepcopy(state[k]) for k in ("impulse", "pullback", "recovery", "confirmation")}}
        elif stage == "再開":
            state["reason"] = "同じ再開eventを維持"
        else:
            raise ValueError("未定義のイベント段階")
        return state

    def feed(self, record: dict) -> None:
        """
        機能: 保存された公開入力を検査し、成立だけでなく失効も再構成する。
        引数: record(dict)はid/kind/inputを持つ疎なEventRecord。
        返り値: None。入力に合わないkind・未来値・重複出典は拒否する。
        """
        require(set(record) == RECORD_FIELDS and type(record["id"]) is int and record["id"] == self.count + 1, "イベント観測IDの連続性")
        x = record["input"]
        require(set(x) == INPUT_FIELDS and type(x["ordinal"]) is int and x["ordinal"] > 0, "イベント入力8tag/ordinal")
        require(type(x["after_eof"]) is bool and x["origin"] in ("three_timer", "core_timer", "quote"), "イベント公開元/EOF型")
        require(finite(x["at"]) and x["at"] > 0 and finite(x["epoch_start"]) and 0 <= x["epoch_start"] <= x["at"], "イベント入力時計")
        q, v = x["quote"], x["technical"]
        require(set(q) == QUOTE_FIELDS and type(q["index"]) is int and type(q["line"]) is int and type(q["valid"]) is bool, "イベント気配schema")
        require(all(finite(q[k]) for k in ("time", "last", "bid", "ask")) and q["time"] <= x["at"], "イベント気配非未来")
        validate_technical(x["at"], v)
        if self.last is not None:
            require(x["ordinal"] > self.last["ordinal"] and x["at"] >= self.last["at"], "イベント順序後退/重複")
        changed_epoch = self.last is None or (x["window"], x["epoch_start"]) != (self.last["window"], self.last["epoch_start"])
        changed_bar = self.last is None or v["bar3_end"] != self.last["technical"]["bar3_end"]
        unknown = not technical_known(v) or v["bar3_end"] <= 0 or v["bar15_end"] <= 0 or x["at"] - v["bar3_end"] > 180 or x["at"] - v["bar15_end"] > 900
        expired = False
        for i, state in enumerate(self.states):
            event = state["event"]
            if event is not None and x["at"] - event["confirmation"]["bar_end"] >= 900:
                self.states[i] = empty_state(state["side"], "再開確認から900秒以上で失効")
                expired = True
        kind, reset = "", False
        if x["after_eof"]:
            kind = "EOF" if not self.eof or changed_bar or changed_epoch else ""
            self.clear("原板終端後のため失効", False)
            reset = True
        elif x["window"] not in ACTIVE_WINDOWS:
            kind = "窓停止" if changed_epoch or changed_bar else ""
            self.clear("静観又は場末のため失効", False)
            reset = True
        elif changed_epoch:
            kind = "窓開始"
            self.clear("Source時間窓を開始", unknown)
            reset = True
        elif x["origin"] == "quote" and q["last"] <= 0:
            kind = "Last不良"
            self.clear("Last不良で必要値を失効", True)
            reset = True
        elif unknown:
            kind = "必要値未知" if not self.last_unknown or changed_bar else ""
            self.clear("確定足の必要値又は鮮度が未知", True)
            reset = True
        elif expired:
            kind = "期限失効"
        if changed_bar and not kind:
            kind = "確定3分"
        require(kind and record["kind"] == kind, "イベントkindと当時失効条件の独立一致")
        self.count += 1
        if changed_bar and v["bar3_end"] > 0 and not x["after_eof"] and x["window"] in ACTIVE_WINDOWS and not unknown and not (x["origin"] == "quote" and q["last"] <= 0):
            continuous = changed_epoch or self.last_bar is None or (v["bar3_end"] - self.last_bar["bar3_end"] == 180 and self.last_bar["histogram3"] == v["previous_histogram3"] and self.last_bar["rsi3"] == v["previous_rsi3"])
            if not continuous:
                self.clear("確定3分の欠足又は前値結合が不成立", True)
            if v["bar3_end"] > x["epoch_start"]:
                point = {"observation_id": record["id"], "bar_end": v["bar3_end"], "published_at": x["at"]}
                self.states = [self.advance_direction(state, x, point) for state in self.states]
        if reset and not (changed_epoch and not unknown and not (x["origin"] == "quote" and q["last"] <= 0) and x["window"] in ACTIVE_WINDOWS and not x["after_eof"] and v["bar3_end"] > x["epoch_start"]):
            self.last_bar = None
        elif changed_bar and v["bar3_end"] > 0:
            self.last_bar = deepcopy(v)
        self.last, self.last_unknown, self.eof = deepcopy(x), unknown, x["after_eof"]

    def snapshot(self, at: float) -> dict:
        """
        機能: 定時までに公開された状態を複写し、厳密900秒期限を計算する。
        引数: at(float)は判断時計。
        返り値: dictはEventSnapshot。過去eventの再消費や若返りを行わない。
        """
        require(finite(at) and at > 0 and (self.last is None or at >= self.last["at"]), "イベントsnapshot時計")
        window, epoch = (self.last["window"], self.last["epoch_start"]) if self.last else ("", 0)
        result = {"at": at, "window": window, "epoch_start": epoch, "directions": deepcopy(self.states)}
        for state in result["directions"]:
            event = state["event"]
            state["event_valid"] = (event is not None and not state["required_unknown"] and window in ACTIVE_WINDOWS
                                    and event["window"] == window and event["epoch_start"] == epoch
                                    and event["confirmation"]["published_at"] <= at and event["confirmation"]["bar_end"] <= at
                                    and at - event["confirmation"]["bar_end"] < 900)
            if event is not None and not state["event_valid"]:
                state["reason"] = "再開eventの期限又は窓が不成立"
        return result


def qualification(name: str, known: bool, passed: bool) -> dict:
    """
    機能: 現在資格の未知と既知不成立を独立に表現する。
    引数: name(str)、known/passed(bool)は条件名と評価。
    返り値: dictは一つのQualificationCheck。
    """
    return {"id": name, "known": known, "passed": known and passed,
            "reason": "必要値未知" if not known else "既知成立" if passed else "既知不成立"}


def evaluate(at: float, quote: dict, technical: dict, pair: dict, events: dict) -> dict:
    """
    機能: 旧actualの共通現在資格と順序event資格を別式で再計算する。
    引数: at(float)、quote/technical/pair/events(dict)は定時公開値。
    返り値: dictはE0/E1の二方向評価。
    """
    q, v = quote, technical
    validate_technical(at, v)
    require(all(finite(pair[k]) for k in ("previous_close3", "previous_ema8_3", "previous_bar3_end")) and 0 <= pair["previous_bar3_end"] <= at, "旧ChartPair非未来有限")
    require(not pair["previous3_known"] or (pair["previous_close3"] > 0 and pair["previous_ema8_3"] > 0 and pair["previous_bar3_end"] > 0 and v["bar3_end"] - pair["previous_bar3_end"] == 180), "旧直前180秒足の価格/結合")
    result = {"at": at, "quote_time": q["time"], "quote_index": q["index"], "source_line": q["line"], "directions": []}
    for side, state in zip((1, -1), events["directions"], strict=True):
        require(state["side"] == side, "イベント側順序")
        known = all(v[k] for k in ("trend_known", "reversal_known", "spike_known", "atr_known"))
        clock = v["bar3_end"] > 0 and v["bar15_end"] > 0 and at-v["bar3_end"] <= 180 and at-v["bar15_end"] <= 900
        quote_known = q["valid"] and q["last"] > 0 and q["bid"] > 0 and q["ask"] > q["bid"] and q["time"] > 0 and at-q["time"] <= 15 and q["index"] >= 0 and q["line"] > 0
        placement_known = v["atr_known"] and quote_known and v["ema8_3"] > 0
        placement, placement_passed = None, False
        if placement_known and v["atr3"] > 0:
            placement = side * ((q["ask"] if side == 1 else q["bid"]) - v["ema8_3"]) / v["atr3"]
            require(finite(placement), "取得ATR比の有限性")
            placement_passed = 0 <= placement <= 1
        checks = [qualification("必要指標既知", known, known),
                  qualification("確定足時計", clock, clock),
                  qualification("旧直前3分結合", pair["previous3_known"], pair["previous3_known"]),
                  qualification("当時新規気配", quote_known, quote_known),
                  qualification("15分背景", v["trend_known"], side*(v["ema8_15"]-v["ema21_15"]) > 0),
                  qualification("3分価格側", v["reversal_known"], side*(v["close3"]-v["ema8_3"]) > 0),
                  qualification("MACD増分", v["reversal_known"], side*(v["histogram3"]-v["previous_histogram3"]) > 0),
                  qualification("RSI増分", v["reversal_known"], side*(v["rsi3"]-v["previous_rsi3"]) > 0),
                  qualification("同時スパイクなし", v["spike_known"], not (v["tr3"] > 2*v["previous_atr3"] and abs(v["rsi3"]-v["previous_rsi3"]) > 15)),
                  qualification("取得0から1ATR", placement_known, placement_passed)]
        current_known = all(c["known"] for c in checks)
        allowed = all(c["passed"] for c in checks)
        result["directions"].append({"side": side, "current_known": current_known, "current_allowed": allowed,
                                     "e0_allowed": allowed, "e1_allowed": allowed and state["event_valid"],
                                     "required_unknown": not current_known, "event_required_unknown": state["required_unknown"],
                                     "reason": "現在資格の必要値が未知" if not current_known else "現在の複合資格が成立" if allowed else "現在資格が既知不成立",
                                     "placement_atr": placement, "checks": checks, "event": deepcopy(state["event"]), "event_valid": state["event_valid"]})
    return result


def filter_pool(policy: str, source: dict, evaluation: dict) -> tuple[dict, list[dict]]:
    """
    機能: 元poolの全値を保ち、外資格のID部分列と二順位を再計算する。
    引数: policy(str)、source/evaluation(dict)はS/E0/E1と当時入力。
    返り値: tuple[dict,list[dict]]は供給snapshotと全raw候補評価。
    """
    require(policy in ("S", "E0", "E1"), "外入口政策")
    out, checks = deepcopy(source), []
    out["lots"] = []
    directions = {d["side"]: d for d in evaluation["directions"]}
    for rank, row in enumerate(sorted(source["lots"], key=lambda r: (r["reference"]["at"], r["reference"]["id"])), 1):
        r = row["reference"]
        d = directions[r["side"]]
        check = {"reference_id": r["id"], "side": r["side"], "raw_rank": rank, "supplied_rank": None,
                 "known": d["current_known"], "allowed": d["e0_allowed"], "required_unknown": d["required_unknown"],
                 "reason": d["reason"], "event_id": "", "event_before_source": None, "event_source_relation": "再開eventなし"}
        if policy == "S":
            check.update(known=True, allowed=True, required_unknown=False, reason="元参照を無filterで供給")
        elif policy == "E1":
            known = d["current_known"] and not d["event_required_unknown"]
            check.update(known=known, required_unknown=not known, allowed=d["e1_allowed"])
            check["reason"] = ("現在資格又は順序履歴の必要値が未知" if not known else "現在資格が既知不成立" if not d["current_allowed"]
                               else "有効な順行再開eventがない" if not d["event_valid"] else "現在資格と順行再開eventが成立")
        if d["event"] is not None:
            end = d["event"]["confirmation"]["bar_end"]
            check.update(event_id=d["event"]["id"], event_before_source=end < r["at"],
                         event_source_relation="eventがSource生成前" if end < r["at"] else "eventがSource生成後" if end > r["at"] else "同時")
        if check["allowed"]:
            out["lots"].append(deepcopy(row))
            check["supplied_rank"] = len(out["lots"])
        checks.append(check)
    return out, checks
