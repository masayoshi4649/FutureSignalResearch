"""75の固定帯・公開足prefix・保存指標・当時気配だけから直接候補を作る。"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math


SOURCE_FIELDS = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
SLOT_FIELDS = ("scheduled", "time", "line", "side", "role", "atr", "D", "reason", "ready", "slot_id")
VALUE_FIELDS = {"F01": 0, "F02": 1, "F03": 2, "F07": 6, "F15": 14, "F47": 46, "F48": 47, "F51": 50, "F52": 51}
POLICIES, SIDES = ("O0", "P0", "P1"), (1, -1)
RULES = {
    "入力": "73保存Q0の旧64列・全当場3分SOURCE13・使う帯一つ・55当時6項目気配だけ。結果/先着/回収は渡さない",
    "公開": "end<=scheduledかつ公開key<=実判断key。未来は価格検査前に除外。index0から旧currentまでの全prefixを要求",
    "反応開始": "O0は帯end以後に開始した足、P0/P1は当場index0.start以後。帯形成足を反応へ兼用しない",
    "reset": "可視の不完全/不正価格と番号/end不連続で両端の現状態をclear。重複/後退/時計不正は例外",
    "T": "q終値>=5が完全隣接2本。最初b/2本目k固定。q終値<5で取消、次の連続2本は別形成",
    "R": "最後の外側足後1..3本で最初q終値<=-5をf、f後1..3で初回の同内側かつf反対端strict終値突破をk",
    "R終了": "f後q終値>-5又は3本確認なし、k後内側/strict線条件喪失で終了。同じ外試行から復活しない",
    "外試行": "最初外足ID/最後外足を共有。fで消費、新しい外足で新ID。中立のまま最後外足から3本超でも消費",
    "技法": "全候補F02>=0/F03>0/F07>0/rawDI非同値/F01非零。TはF01>0/F51=F52=1/F47>=0.20/F48>=0",
    "反転": "RでF01>0なら順行。RのF01<0はF52=1/F48<0/F15>0で反転",
    "ADX単位": "旧F47=ADX/100のfloat64へ0.20を直接比較。100倍してから20へ比較しない",
    "現在価格": "正常bid<ask/正Lastが必要。Lastと買ask/売bidの両方が前提線の実方向strict外",
    "位置": "P1は0<s(E*-line)<=D、Rのみs(M-E*)>=250。位置条件後の適格集合から選ぶ",
    "優先": "最新k公開key。同keyはT優先。反対方向同時資格は鏡像矛盾として停止",
    "寿命": "新k900秒制限なし。有効中は持越し、形成IDとk経過を保存。取消/品質resetは復活させない",
    "量": "数量を採否へ使わない。新fit/新指標/市場/損益の計算なし"}


# ----------------------------------------
def finite(value: object) -> bool:
    """boolを除く有限な保存数値を判定する。

    引数: value(object)は時計又は価格。
    返り値: boolは有限int/floatなら真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def exact(value: int | float) -> Fraction:
    """保存十進表現から比較用の有理数を作る。

    引数: value(int|float)は有限数値。
    返り値: Fractionは丸めを追加しない精密値。
    """
    if not finite(value):
        raise ValueError("精密比較の有限値なし")
    return Fraction(str(value))


def canonical(value: object, allow_invalid: bool = False) -> str:
    """入力比較又は可視prefix指紋用の固定JSONを作る。

    引数: value(object)は保存値、allow_invalid(bool)は既知不良価格を指紋へ残すか。
    返り値: strはkey順に依らないJSON。不良価格は状態をresetし、数値比較へ投入しない。
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=allow_invalid)


def clock(slot: dict) -> tuple:
    """元判断の識別と価格時計を検査する。

    引数: slot(dict)は73保存Q0の純判断とfeature。
    返り値: tupleは実判断key。旧未準備だけline=Noneを許す。
    """
    if (not isinstance(slot, dict) or not isinstance(slot.get("session"), str) or not slot["session"]
            or not isinstance(slot.get("slot_id"), str) or not slot["slot_id"]
            or type(slot.get("ready")) is not bool or not finite(slot.get("scheduled"))
            or not finite(slot.get("time")) or slot["time"] < slot["scheduled"]
            or not (type(slot.get("line")) is int and slot["line"] >= 0 or not slot["ready"] and slot.get("line") is None)):
        raise ValueError("元判断の場・ID・時計・準備が不正")
    return slot["time"], slot["line"]


def reference(row: dict) -> dict:
    """trace用の足番号と公開keyだけを写す。

    引数: row(dict)は可視SOURCE。
    返り値: dictは価格を含めない出典参照。
    """
    return {"index": row["index"], "key": [row["confirm"], row["confirm_line"]]}


def price_reason(row: dict) -> str | None:
    """既知の不完全足・不正価格をreset理由へ分類する。

    引数: row(dict)はschema検査済みSOURCE13。
    返り値: str|Noneはreset理由又は正常。未知を価格0へ補完しない。
    """
    if not row["publish"] or row["missing"] != 0 or row["end"] - row["start"] != 180 or row["confirm"] < row["end"]:
        return "公開完全3分足でない"
    if (not all(finite(row[k]) and row[k] > 0 for k in ("open", "high", "low", "close"))
            or row["low"] > min(row["open"], row["close"], row["high"])
            or row["high"] < max(row["open"], row["close"], row["low"])):
        return "価格不正"
    return None


def visible_prefix(slot: dict, history_sources: list[dict], feature: dict) -> list[dict]:
    """未来を先に除外し、全当場prefixと旧current全文を検査する。

    引数: slot/feature(dict)は旧判断と旧64特徴、history_sources(list[dict])は当場全SOURCE13。
    返り値: list[dict]は当時可視な深い複写。部分prefix・順序矛盾は停止する。
    """
    if not isinstance(history_sources, list):
        raise ValueError("全当場SOURCE配列なし")
    result, limit = [], clock(slot)
    for source in history_sources:
        if not isinstance(source, dict) or source.get("session") != slot["session"] or not finite(source.get("end")):
            raise ValueError("SOURCEの場又は可視終端を判定できない")
        if source["end"] > slot["scheduled"]:
            continue
        if not finite(source.get("confirm")) or type(source.get("confirm_line")) is not int or source["confirm_line"] < 0:
            raise ValueError("SOURCEの公開keyを判定できない")
        if (source["confirm"], source["confirm_line"]) > limit:
            continue
        if (not set(SOURCE_FIELDS) <= set(source) or type(source["index"]) is not int or source["index"] < 0
                or type(source["minutes"]) is not int or source["minutes"] != 3
                or type(source["publish"]) is not bool or type(source["missing"]) is not int or source["missing"] < 0
                or not finite(source["start"])):
            raise ValueError("可視SOURCE13のschema不正")
        row = {key: deepcopy(source[key]) for key in SOURCE_FIELDS}
        if result and (row["index"] <= result[-1]["index"]
                or (row["confirm"], row["confirm_line"]) <= (result[-1]["confirm"], result[-1]["confirm_line"])):
            raise ValueError("可視SOURCE番号又は公開keyの重複・後退")
        result.append(row)
    try:
        current = {k: feature["base"]["base"]["sources"]["current"][k] for k in SOURCE_FIELDS}
    except (KeyError, TypeError) as exc:
        raise ValueError("旧73のcurrent SOURCE13なし") from exc
    if not result or result[0]["index"] != 0:
        raise ValueError("index0からの全当場prefixが必要")
    if canonical(result[-1], True) != canonical(current, True) or price_reason(result[-1]) is not None:
        raise ValueError("prefix末尾と旧currentの全文差又は旧準備との矛盾")
    return result


def values_for(feature: dict) -> dict:
    """旧64列の直接gate値とraw背景を検査して両方向へ写す。

    引数: feature(dict)は旧ready真の73保存特徴。
    返り値: dictは値/背景を持つ方向辞書。float32化や指標再算出はしない。
    """
    vectors, background = feature.get("vectors"), feature.get("background_direction")
    if not isinstance(vectors, dict) or set(vectors) != {"1", "-1"} or type(background) is not int or background not in (-1, 0, 1):
        raise ValueError("旧両方向vector又はraw背景なし")
    result = {}
    for side in SIDES:
        vector = vectors[str(side)]
        if not isinstance(vector, list) or len(vector) != 64:
            raise ValueError("旧73の64列が必要")
        values = {name: deepcopy(vector[index]) for name, index in VALUE_FIELDS.items()}
        if not all(finite(v) for v in values.values()) or any(values[k] not in (0, 1) for k in ("F51", "F52")):
            raise ValueError("直接条件値又はADX mask不正")
        if not 0 <= values["F47"] <= 1 or not -1 <= values["F48"] <= 1:
            raise ValueError("旧ADX/100の値域不正")
        if values["F01"] and (1 if values["F01"] > 0 else -1) != side * background:
            raise ValueError("旧F01とraw背景が不整合")
        result[str(side)] = {**values, "raw_background_direction": background}
    for name in ("F01", "F02", "F03", "F07", "F15"):
        if result["1"][name] != -result["-1"][name]:
            raise ValueError("方向値の売買鏡像矛盾")
    for name in ("F47", "F48", "F51", "F52"):
        if result["1"][name] != result["-1"][name]:
            raise ValueError("方向不変値の売買鏡像矛盾")
    return result


def band_view(slot: dict, band: dict) -> dict:
    """未公開帯の価格・被覆を見ず、使える固定帯の小型情報を作る。

    引数: slot(dict)は判断key、band(dict)は外層が選んだO30又は前帯だけ。
    返り値: dictは公開/準備/高安中央/識別。未来価格は返さない。
    """
    if (not isinstance(band, dict) or type(band.get("reference_available")) is not bool
            or not isinstance(band.get("id"), str) or not band["id"] or band.get("current_session") != slot["session"]):
        raise ValueError("参照帯の識別又は参照有無が不正")
    if not band["reference_available"]:
        if band.get("published") is not False or band.get("ready") is not False or not isinstance(band.get("reason"), str):
            raise ValueError("前参照なしと帯準備の矛盾")
        return {"id": band["id"], "session": band.get("session"), "current_session": slot["session"],
            "reference_type": band.get("reference_type"), "prior_gap_seconds": band.get("prior_gap_seconds"),
            "reference_available": False, "begin": None, "end": None, "publication": band.get("publication"),
            "publication_key": None, "published": False, "ready": False, "reason": band["reason"],
            "high": None, "low": None, "mid": None}
    if (type(band.get("published")) is not bool or band.get("publication") not in ("timer", "row")
            or not finite(band.get("begin")) or not finite(band.get("end")) or band["end"] <= band["begin"]):
        raise ValueError("参照帯の識別・時計schema不正")
    result = {key: deepcopy(band.get(key)) for key in
        ("id", "session", "current_session", "reference_type", "prior_gap_seconds", "reference_available", "begin", "end", "publication")}
    result.update(publication_key=None, published=False, ready=False, reason="帯未公開", high=None, low=None, mid=None)
    if not band["published"]:
        return result
    key = band.get("publication_key")
    if (not isinstance(key, dict) or not finite(key.get("time")) or key["time"] < band["end"]
            or not (key.get("line") is None if band["publication"] == "timer"
                else type(key.get("line")) is int and key["line"] >= 0)):
        raise ValueError("帯の公開key不正")
    if key["time"] > slot["time"] or (band["publication"] == "row" and (key["time"], key["line"]) > clock(slot)):
        return result
    if type(band.get("ready")) is not bool or not isinstance(band.get("reason"), str):
        raise ValueError("公開帯の準備schema不正")
    result.update(publication_key=deepcopy(key), published=True, ready=band["ready"], reason=band["reason"])
    if band["ready"]:
        if not all(finite(band.get(k)) and band[k] > 0 for k in ("high", "low", "mid")) or band["low"] > band["high"]:
            raise ValueError("準備済み帯の高安不正")
        if exact(band["mid"]) != (exact(band["high"]) + exact(band["low"])) / 2:
            raise ValueError("帯中央と高安の不整合")
        result.update({key: deepcopy(band[key]) for key in ("high", "low", "mid")})
    return result


def quote_view(slot: dict, quote: dict | None) -> bool:
    """55保存quoteの元判断を結合し、正常BBO・正Lastを判定する。

    引数: slot(dict)は元判断、quote(dict|None)は判断時6項目。
    返り値: boolは現在価格の前提を検査できるか。schema/時計違いは例外。
    """
    if quote is None:
        return False
    if (not isinstance(quote, dict) or set(quote) != {"now", "line", "valid", "bid", "ask", "last"}
            or type(quote["valid"]) is not bool or not finite(quote["now"])
            or type(quote["line"]) is not int or quote["line"] < 0
            or (quote["now"], quote["line"]) != clock(slot)):
        raise ValueError("当時気配と判断のschema又は時計差")
    return (quote["valid"] and all(finite(quote[k]) and quote[k] > 0 for k in ("bid", "ask", "last"))
        and quote["bid"] < quote["ask"])


# ----------------------------------------
class Endpoint:
    """一つの固定端に外試行を一つ結合し、TとRの現在状態を保持する。"""

    def __init__(self, session: str, band_id: str, direction: int, level: int | float) -> None:
        """固定端と未形成状態を初期化する。

        引数: session/band_id(str)は場/帯、direction(int)は外方向、levelは固定高安。
        返り値: None。
        """
        self.session, self.band_id, self.direction, self.level = session, band_id, direction, level
        self.trials, self.formations = [], []
        self.trial = self.t = self.r = None
        self.previous_outside = False

    def identity(self, row: dict, kind: str) -> str:
        """出典keyから不変の形成識別子を作る。

        引数: row(dict)は最初b又はf、kind(str)は外試行/T/R。
        返り値: strは帯・方向・出典を含むID。
        """
        return f"{self.session}|{self.band_id}|{self.direction:+d}|{kind}|{row['index']}|{float(row['confirm']).hex()}|{row['confirm_line']}"

    def trace(self, formation: dict, row: dict, action: str) -> None:
        """状態の遷移後に最小出典と動作を保存する。

        引数: formation/row(dict)は形成/当足、action(str)は遷移。
        返り値: None。
        """
        formation["trace"].append({**reference(row), "action": action, "status": formation["status"], "active": formation["active"]})

    def finish(self, formation: dict | None, row: dict, reason: str, status: str = "取消") -> None:
        """未取消の形成を終了し、最初の取消理由を固定する。

        引数: formation(dict|None)は形成、row(dict)は当足、reason/status(str)は理由/状態。
        返り値: None。同じ形成を復活させない。
        """
        if formation is not None and formation["cancel"] is None:
            formation.update(active=False, status=status, cancel={**reference(row), "reason": reason})
            self.trace(formation, row, reason)

    def reset(self, row: dict, reason: str) -> None:
        """既知不良又は不連続で現在状態を消し、終了履歴を残す。

        引数: row(dict)は観測足、reason(str)はreset理由。
        返り値: None。正常な現足は呼出側から新しい1本目にできる。
        """
        self.finish(self.t, row, reason, "品質reset")
        self.finish(self.r, row, reason, "品質reset")
        if self.trial is not None and not self.trial["consumed"]:
            self.consume(row, reason)
        self.trial = self.t = self.r = None
        self.previous_outside = False

    def consume(self, row: dict, reason: str) -> None:
        """同じ外試行からの内回帰を一回に制限する。

        引数: row(dict)は消費足、reason(str)はf又は期限/reset。
        返り値: None。
        """
        self.trial.update(consumed=True, consumed_at=reference(row), consume_reason=reason)

    def formation(self, row: dict, kind: str, line: int | float) -> dict:
        """外試行IDを共有した新T又はR形成を作る。

        引数: row(dict)はTのrun先頭又はRのf、kind(str)はT/R、lineは名目前提線。
        返り値: dictは履歴配列へ登録済みの形成。
        """
        result = {"id": self.identity(row, kind), "episode_id": self.trial["id"], "kind": kind,
            "side": self.direction if kind == "T" else -self.direction, "break_direction": self.direction,
            "level": self.level, "premise_line": line,
            "b": deepcopy(row if kind == "T" else self.trial["first_outside"]),
            "last_outside": deepcopy(self.trial["last_outside"]), "f": deepcopy(row) if kind == "R" else None,
            "k": None, "active": False, "status": "確認待ち", "cancel": None, "trace": []}
        self.formations.append(result)
        if kind == "T":
            self.trial["T_ids"].append(result["id"])
        else:
            self.trial["R_id"] = result["id"]
        self.trace(result, row, "T外足1本目" if kind == "T" else "R内回帰f")
        return result

    def step(self, row: dict) -> None:
        """公開完全足一つでTの連続保持と、同じ外試行のRだけを更新する。

        引数: row(dict)は順序検査済みの正常SOURCE13。
        返り値: None。fとkの同足成立や取消後の同原因復活をしない。
        """
        q = self.direction * (exact(row["close"]) - exact(self.level))
        outside = q >= 5
        if (self.trial is not None and not self.trial["consumed"]
                and row["index"] - self.trial["last_outside"]["index"] > 3):
            self.consume(row, "最後の外足後3本の内回帰なし")
        # ----------------------------------------
        # f後のRは、外試行の消費とは別に最初確認とその取消を追う。
        if self.r is not None and self.r["cancel"] is None:
            r = self.r
            progress = r["side"] * (exact(row["close"]) - exact(r["premise_line"]))
            elapsed = row["index"] - r["f"]["index"]
            if q > -5:
                self.finish(r, row, "内回帰の内側条件否定")
            elif r["k"] is not None and progress <= 0:
                self.finish(r, row, "再開線終値否定")
            elif r["k"] is None:
                if 1 <= elapsed <= 3 and progress > 0:
                    r.update(k=deepcopy(row), active=True, status="有効")
                    self.trace(r, row, "R再開k")
                elif elapsed >= 3:
                    self.finish(r, row, "f後3本の再開確認なし", "確認期限切れ")
        # ----------------------------------------
        # Tは2本目のkを固定し、その後はq>=5の間だけ継続する。
        if not outside:
            self.finish(self.t, row, "外保持の終値5未満")
            self.t = None
        if outside:
            if self.trial is None or self.trial["consumed"]:
                self.trial = {"id": self.identity(row, "外試行"), "direction": self.direction, "level": self.level,
                    "first_outside": deepcopy(row), "last_outside": deepcopy(row), "consumed": False,
                    "consumed_at": None, "consume_reason": None, "T_ids": [], "R_id": None}
                self.trials.append(self.trial)
            self.trial["last_outside"] = deepcopy(row)
            if not self.previous_outside or self.t is None:
                self.t = self.formation(row, "T", self.level)
            else:
                self.t["last_outside"] = deepcopy(row)
                if self.t["k"] is None:
                    self.t.update(k=deepcopy(row), active=True, status="有効")
                    self.trace(self.t, row, "T外保持k")
        elif self.trial is not None and not self.trial["consumed"]:
            if q <= -5:
                self.r = self.formation(row, "R", row["high"] if self.direction == -1 else row["low"])
                self.consume(row, "最初の内回帰f")
        self.previous_outside = outside


def reconstruct(slot: dict, prefix: list[dict], band: dict, reaction_start: int | float) -> tuple:
    """反応開始以後の全prefixから上下端の結合機械を再構成する。

    引数: slot(dict)は元判断、prefix(list[dict])は全可視足、band(dict)は固定帯、reaction_startは開始境界。
    返り値: tupleは外試行/全形成/現在候補/reset履歴/反応足数。
    """
    endpoints = [Endpoint(slot["session"], band["id"], d, band["high"] if d == 1 else band["low"]) for d in SIDES]
    previous, resets, count = None, [], 0
    for row in prefix:
        if row["start"] < reaction_start:
            continue
        count += 1
        reason = price_reason(row)
        discontinuity = previous is not None and (row["index"] != previous["index"] + 1 or row["start"] != previous["end"])
        reasons = (["番号又はend不連続"] if discontinuity else []) + ([reason] if reason is not None else [])
        if reasons:
            text = "・".join(reasons)
            resets.append({**reference(row), "reason": text})
            for endpoint in endpoints:
                endpoint.reset(row, text)
        if reason is None:
            for endpoint in endpoints:
                endpoint.step(row)
        previous = row
    trials = [deepcopy(record) for endpoint in endpoints for record in endpoint.trials]
    formations = [deepcopy(record) for endpoint in endpoints for record in endpoint.formations]
    candidates = [deepcopy(record) for record in formations if record["active"]]
    for candidate in candidates:
        candidate["k_age_seconds"] = slot["time"] - candidate["k"]["confirm"]
    return trials, formations, candidates, resets, count


# ----------------------------------------
def qualification(candidate: dict, values: dict, quote: dict, D: int | float, mid: int | float, policy: str) -> dict:
    """価格形成へ共通資格と現在価格、その後でP1位置条件を適用する。

    引数: candidate/values/quote(dict)は現在候補/保存値/正常気配、Dは旧幅、midは帯中央、policyはO0/P0/P1。
    返り値: dictは位置前後の資格・理由・値・距離。反対側の救済順位を作らない。
    """
    side = candidate["side"]
    di, background = values["F01"], values["raw_background_direction"]
    role = "待機" if not background or not di else "順行" if di > 0 else "反転"
    reasons = []
    if not background:
        reasons.append("上位DI同値")
    if not di:
        reasons.append("DI優勢差同値")
    if values["F02"] < 0:
        reasons.append("FastK中央差が逆向き")
    if values["F03"] <= 0:
        reasons.append("FastK進行が非正")
    if values["F07"] <= 0:
        reasons.append("終値変化が非正")
    if candidate["kind"] == "T":
        if di <= 0:
            reasons.append("外保持は上位DI同方向が必要")
        if values["F51"] != 1 or values["F52"] != 1:
            reasons.append("外保持のADX現値又は変化が未知")
        if values["F47"] < 0.20:
            reasons.append("外保持のADX20未満")
        if values["F48"] < 0:
            reasons.append("外保持のADXが減速")
    elif di < 0:
        if values["F52"] != 1:
            reasons.append("反転のADX変化が未知")
        if values["F48"] >= 0:
            reasons.append("反転のADXが非減速")
        if values["F15"] <= 0:
            reasons.append("反転の15分終値位置が非正")
    entry = quote["ask"] if side == 1 else quote["bid"]
    last_distance = side * (exact(quote["last"]) - exact(candidate["premise_line"]))
    entry_distance = side * (exact(entry) - exact(candidate["premise_line"]))
    room = side * (exact(mid) - exact(entry)) if candidate["kind"] == "R" else None
    if last_distance <= 0:
        reasons.append("現在Lastが前提線を否定")
    if entry_distance <= 0:
        reasons.append("現在新規BBOが前提線を否定")
    basic = not reasons
    position_reasons = []
    if entry_distance <= 0 or entry_distance > exact(D):
        position_reasons.append("前提線までの新規距離がD範囲外")
    if room is not None and room < 250:
        position_reasons.append("内回帰の中央余地250未満")
    position = basic and not position_reasons
    return {"basic_qualified": basic, "position_qualified": position,
        "qualified": position if policy == "P1" else basic, "role": role,
        "reasons": reasons + (position_reasons if policy == "P1" else []), "basic_reasons": reasons,
        "position_reasons": position_reasons, "values": deepcopy(values),
        "price": {"last": quote["last"], "entry_proxy": entry, "premise_line": candidate["premise_line"],
            "last_distance": float(last_distance), "entry_distance": float(entry_distance),
            "mid_room": float(room) if room is not None else None, "D": D}}


def latest(candidates: list[dict], qualifications: dict, field: str) -> dict | None:
    """適格集合の最新kを選び、同keyならTを優先する。

    引数: candidates(list[dict])は現在有効形成、qualifications(dict)は資格、field(str)は位置前/後の資格名。
    返り値: dict|Noneは選択。反対方向同時資格や同種同方向重複は停止する。
    """
    chosen = [c for c in candidates if qualifications[c["id"]][field]]
    if len({c["side"] for c in chosen}) > 1:
        raise ValueError("反対方向が同時に技法資格を満たす鏡像矛盾")
    identities = [(c["kind"], c["side"]) for c in chosen]
    if len(identities) != len(set(identities)):
        raise ValueError("同種・同方向の現在候補が重複")
    if not chosen:
        return None
    return deepcopy(max(chosen, key=lambda c: (c["k"]["confirm"], c["k"]["confirm_line"], c["kind"] == "T")))


def extract(old_slot: dict, history_sources: list[dict], band: dict, decision_quote: dict | None, policy: str) -> dict:
    """当時の固定帯・公開履歴・保存指標・気配だけから75観測を返す。

    引数: old_slot(dict)は73保存feature付き判断、history_sourcesは全当場SOURCE13、bandは選択済み帯、decision_quoteは55当時気配、policyはO0/P0/P1。
    返り値: dictは全形成・現在資格・位置前後選択と純方向。結果/先着/回収は受け取らない。
    """
    if policy not in POLICIES:
        raise ValueError("75政策はO0/P0/P1のみ")
    clock(old_slot)
    feature = old_slot.get("feature")
    if not isinstance(feature, dict) or type(feature.get("ready")) is not bool or feature["ready"] is not old_slot["ready"]:
        raise ValueError("旧73特徴と純判断の準備不一致")
    result = {"ready": False, "reason": "旧73特徴が未準備", "policy": policy,
        "source_count": 0, "source_sha256": None, "reaction_count": 0, "reaction_start": None,
        "band": None, "history": {"current": None, "resets": []}, "trials": [], "formations": [],
        "candidates": [], "qualifications": {}, "selected_before_position": None, "selected": None, "side": 0, "role": "待機"}
    if not feature["ready"]:
        return result
    if (not finite(old_slot.get("atr")) or old_slot["atr"] <= 0 or not finite(old_slot.get("D")) or old_slot["D"] <= 0
            or feature.get("atr") != old_slot["atr"] or feature.get("D") != old_slot["D"]):
        raise ValueError("旧ATR/Dと純判断の不整合")
    prefix, values = visible_prefix(old_slot, history_sources, feature), values_for(feature)
    result.update(source_count=len(prefix), source_sha256=hashlib.sha256(canonical(prefix, True).encode("utf-8")).hexdigest())
    result["history"]["current"] = deepcopy(prefix[-1])
    view = band_view(old_slot, band)
    result["band"] = view
    if not view["ready"]:
        result["reason"] = view["reason"]
        return result
    result["ready"] = True
    if view["high"] == view["low"]:
        result["reason"] = "平坦帯は反応対象外"
        return result
    reaction_start = view["end"] if policy == "O0" else prefix[0]["start"]
    if "reaction_start" in band and band["reaction_start"] != reaction_start:
        raise ValueError("帯の反応開始境界が政策と不整合")
    result["reaction_start"] = reaction_start
    trials, formations, candidates, resets, count = reconstruct(old_slot, prefix, view, reaction_start)
    result.update(trials=trials, formations=formations, candidates=candidates, reaction_count=count)
    result["history"]["resets"] = resets
    if not quote_view(old_slot, decision_quote):
        result.update(ready=False, reason="現在BBO又はLastの観測不足")
        return result
    for candidate in candidates:
        result["qualifications"][candidate["id"]] = qualification(candidate, values[str(candidate["side"])], decision_quote, old_slot["D"], view["mid"], policy)
    result["selected_before_position"] = latest(candidates, result["qualifications"], "basic_qualified")
    result["selected"] = latest(candidates, result["qualifications"], "qualified")
    selected = result["selected"]
    if selected is not None:
        result.update(side=selected["side"], role=result["qualifications"][selected["id"]]["role"], reason="固定帯反応の複合候補")
    else:
        result["reason"] = "現在有効な固定帯反応なし" if not candidates else "固定帯反応の複合条件不適格"
    return result


def choose(old_slot: dict, observation: dict, policy: str) -> dict:
    """観測結果をO49純10項目と由来の小型metadataへ射影する。

    引数: old_slot(dict)は元保存判断、observation(dict)は同政策extract結果、policyはO0/P0/P1。
    返り値: dictは純判断とsession/policy/origin/pattern_id/formation/premise_line/band_id。旧予測・損益は転記しない。
    """
    if policy not in POLICIES or not all(key in old_slot for key in SLOT_FIELDS):
        raise ValueError("政策又は元純10項目なし")
    clock(old_slot)
    if (not isinstance(observation, dict) or observation.get("policy") != policy
            or type(observation.get("ready")) is not bool or type(observation.get("side")) is not int
            or observation["side"] not in (-1, 0, 1)):
        raise ValueError("75観測の政策・準備・方向不正")
    side, selected = observation["side"], observation["selected"]
    if side and (not observation["ready"] or selected is None or selected["side"] != side
            or not observation["qualifications"][selected["id"]]["qualified"]):
        raise ValueError("選択形成と純方向の不整合")
    result = {key: deepcopy(old_slot[key]) for key in SLOT_FIELDS}
    kind = selected["kind"] if selected is not None else None
    origin = ("O30" if policy == "O0" else "前帯") + ("外保持" if kind == "T" else "内回帰" if kind == "R" else "待機")
    result.update(session=old_slot["session"], policy=policy, ready=observation["ready"], side=side,
        role=observation["role"], reason=observation["reason"], origin=origin,
        pattern_id=selected["id"] if selected is not None else None, formation=kind,
        premise_line=selected["premise_line"] if selected is not None else None,
        band_id=observation["band"]["id"] if observation["band"] is not None else None)
    return result


# ----------------------------------------
def synthetic(closes: list[int | float], desired_side: int = 1, background: int = 1) -> tuple:
    """本物を読まない公開足・旧64値・前帯・当時quoteの人工一式を作る。

    引数: closes(list)は人工終値、desired_side(int)は勢い方向、background(int)はraw DI。
    返り値: tupleはold_slot/history_sources/band/quote。fitや市場再生を行わない。
    """
    session = "2026-10-01_Day"
    sources = [{"session": session, "index": index, "minutes": 3, "start": index * 180,
        "end": (index + 1) * 180, "confirm": (index + 1) * 180, "confirm_line": index + 1,
        "publish": True, "missing": 0, "open": close, "high": close + 1, "low": close - 1, "close": close}
        for index, close in enumerate(closes)]
    values = {"F01": .2 * background, "F02": .1 * desired_side, "F03": .1 * desired_side,
        "F07": .1 * desired_side, "F15": .1 * desired_side, "F47": .20, "F48": .01, "F51": 1, "F52": 1}
    vectors = {}
    for side in SIDES:
        vector = [0.0] * 64
        for name, index in VALUE_FIELDS.items():
            vector[index] = values[name] * side if name in ("F01", "F02", "F03", "F07", "F15") else values[name]
        vectors[str(side)] = vector
    feature = {"ready": True, "atr": 100.0, "D": 125.0, "background_direction": background,
        "vectors": vectors, "base": {"base": {"sources": {"current": deepcopy(sources[-1])}}}}
    slot = {"session": session, "slot_id": session + "_人工", "scheduled": sources[-1]["end"],
        "time": sources[-1]["end"] + 1, "line": len(sources) + 100, "side": 0, "role": "待機",
        "atr": 100.0, "D": 125.0, "reason": "旧人工判断", "ready": True, "feature": feature}
    band = {"id": "FULL:人工前Night", "session": "人工前Night", "current_session": session,
        "reference_type": "前帯", "reference_available": True, "prior_gap_seconds": 1, "begin": -2000, "end": -1,
        "publication": "timer", "published": True, "publication_key": {"time": -1, "line": None},
        "ready": True, "reason": "準備済み", "open": 550, "high": 1000, "low": 100, "close": 550, "mid": 550,
        "reaction_start": 0}
    last = closes[-1]
    quote = {"now": slot["time"], "line": slot["line"], "valid": True, "last": last, "bid": last - 1, "ask": last + 1}
    return slot, sources, band, quote


def reflected(case: tuple, constant: int = 2200) -> tuple:
    """人工価格と方向を反射し、高安とBBO端を交換する。

    引数: case(tuple)はsynthetic一式、constant(int)は全価格より大きい反射定数。
    返り値: tupleは売買鏡像。時間・IDの元出典は保つ。
    """
    slot, sources, band, quote = deepcopy(case)
    for row in sources:
        row.update(open=constant - row["open"], close=constant - row["close"], high=constant - row["low"], low=constant - row["high"])
    feature = slot["feature"]
    feature["vectors"]["1"], feature["vectors"]["-1"] = feature["vectors"]["-1"], feature["vectors"]["1"]
    feature["background_direction"] *= -1
    feature["base"]["base"]["sources"]["current"] = deepcopy(sources[-1])
    band.update(open=constant - band["open"], close=constant - band["close"],
        high=constant - band["low"], low=constant - band["high"], mid=constant - band["mid"])
    quote.update(last=constant - quote["last"], bid=constant - quote["ask"], ask=constant - quote["bid"])
    return slot, sources, band, quote


def self_test() -> dict:
    """境界・結合状態・位置前後・未来不使用を人工だけで検査する。

    引数: なし。
    返り値: dictは成功/テスト件数/照合項目数。本物入力・fit・市場は0。
    """
    tests, checks = 0, 0

    def check(actual: object, expected: object) -> None:
        """人工期待値を比較し、不一致で即停止する。

        引数: actual/expected(object)は実値/人工期待。
        返り値: None。
        """
        nonlocal checks
        checks += 1
        if canonical(actual, True) != canonical(expected, True):
            raise AssertionError((actual, expected))

    def observe(case: tuple, policy: str = "P0") -> dict:
        """人工一式を本体へ渡し、元データ不変も検査する。

        引数: case(tuple)は人工4引数、policy(str)はO0/P0/P1。
        返り値: dictは観測。
        """
        before = canonical(case, True)
        result = extract(*case, policy)
        check(canonical(case, True), before)
        return result

    case = synthetic([1005, 1006])
    obs = observe(case)
    check((obs["side"], obs["selected"]["kind"], obs["role"]), (1, "T", "順行"))
    check((obs["selected"]["b"]["index"], obs["selected"]["k"]["index"]), (0, 1))
    check(choose(case[0], obs, "P0")["premise_line"], 1000)
    tests += 1
    for closes, expected in (([1005], False), ([1005, 1004], False), ([1005, 1005], True),
            ([1005, 1006, 1004, 1005, 1006], True)):
        got = observe(synthetic(closes))
        check(bool(got["selected"]), expected)
    tests += 1
    got = observe(synthetic([1005, 1006] + [1007] * 8))
    check(got["selected"]["k_age_seconds"] > 900, True)
    check(got["selected"]["k"]["index"], 1)
    tests += 1
    reverse = synthetic([1005, 1006, 995, 990], -1, 1)
    for vector in reverse[0]["feature"]["vectors"].values():
        vector[47] = -.01
    got = observe(reverse)
    check((got["side"], got["selected"]["kind"], got["role"]), (-1, "R", "反転"))
    trial = next(t for t in got["trials"] if t["direction"] == 1)
    check(trial["consumed"], True)
    check(sorted({r["episode_id"] for r in got["formations"] if r["break_direction"] == 1}), [trial["id"]])
    tests += 1
    for closes, expected in (([1005, 1000, 1000, 995, 990], True),
            ([1005, 1000, 1000, 1000, 995, 990], False),
            ([1005, 995, 995, 995, 990], True),
            ([1005, 995, 995, 995, 995, 990], False),
            ([1005, 995, 996, 990], False),
            ([1005, 995, 990, 995, 990], False)):
        c = synthetic(closes, -1, -1)
        got = observe(c)
        check(any(r["active"] and r["kind"] == "R" and r["side"] == -1 for r in got["formations"]), expected)
    tests += 1
    c = synthetic([1005, 995, 990, 995, 1005, 995, 990], -1, -1)
    got = observe(c)
    rforms = [r for r in got["formations"] if r["kind"] == "R" and r["side"] == -1]
    check((len(rforms), len({r["episode_id"] for r in rforms}), [r["active"] for r in rforms]), (2, 2, [False, True]))
    tests += 1
    c = synthetic([1005, 1000, 1000, 1000, 1005, 1006])
    got = observe(c)
    trials = [r for r in got["trials"] if r["direction"] == 1]
    check((len(trials), [r["first_outside"]["index"] for r in trials], [r["consumed"] for r in trials]),
        (2, [0, 4], [True, False]))
    tests += 1
    for c in (case, reverse, synthetic([90, 1005, 1008]), synthetic([1005, 995, 990], -1, -1)):
        left, right = observe(c), observe(reflected(c))
        check((right["ready"], right["side"], right["role"]), (left["ready"], -left["side"], left["role"]))
        check([(r["kind"], r["active"], r["status"]) for r in sorted(left["formations"], key=lambda r: (r["kind"], r["b"]["index"]))],
            [(r["kind"], r["active"], r["status"]) for r in sorted(right["formations"], key=lambda r: (r["kind"], r["b"]["index"]))])
    tests += 1
    c = synthetic([90, 1005, 1008])
    got = observe(c)
    check((got["selected"]["kind"], len([r for r in got["candidates"] if r["side"] == 1])), ("T", 2))
    tests += 1
    c = synthetic([90, 1005, 1006, 1008])
    p0, p1 = observe(c), observe(c, "P1")
    check((p0["selected"]["kind"], p1["selected_before_position"]["kind"], p1["selected"]["kind"], p1["side"]), ("R", "R", "T", p0["side"]))
    tests += 1
    for last, ask, expected in ((1124, 1125, True), (1124, 1125.0001, False), (1000, 1001, False)):
        c = synthetic([1005, 1006])
        c[3].update(last=last, bid=last - 1, ask=ask)
        check(bool(observe(c, "P1")["side"]), expected)
    c = synthetic([1005, 901, 899], -1, -1)
    for bid, expected in ((800, True), (799, False)):
        c[3].update(last=bid + 1, bid=bid, ask=bid + 2)
        check(bool(observe(c, "P1")["side"]), expected)
    tests += 1
    for field, value in (("F03", 0), ("F07", 0), ("F02", -.001), ("F47", math.nextafter(.20, -math.inf)), ("F48", -.001), ("F51", 0), ("F52", 0)):
        c = synthetic([1005, 1006])
        index = VALUE_FIELDS[field]
        c[0]["feature"]["vectors"]["1"][index] = value
        c[0]["feature"]["vectors"]["-1"][index] = -value if field in ("F02", "F03", "F07") else value
        check(observe(c)["side"], 0)
    c = synthetic([1005, 1006], 1, 0)
    check(observe(c)["side"], 0)
    c = synthetic([1005, 995, 990], -1, -1)
    for vector in c[0]["feature"]["vectors"].values():
        vector[46] = vector[47] = vector[50] = vector[51] = 0
    check((observe(c)["side"], observe(c)["role"]), (-1, "順行"))
    tests += 1
    for field, value in (("F15", 0), ("F48", 0), ("F52", 0)):
        c = deepcopy(reverse)
        for side in SIDES:
            c[0]["feature"]["vectors"][str(side)][VALUE_FIELDS[field]] = side * value if field == "F15" else value
        check(observe(c)["side"], 0)
    c = synthetic([1005, 1006])
    for vector in c[0]["feature"]["vectors"].values():
        vector[0] = 0
    check(observe(c)["side"], 0)
    c = synthetic([1005, 995, 994, 990], -1, -1)
    check(observe(c)["selected"]["k"]["index"], 3)
    tests += 1
    c = synthetic([1005, 1006])
    baseline = observe(c)
    future = {"session": c[0]["session"], "end": c[0]["scheduled"] + 180, "close": "未来不正"}
    c[1].append(future)
    check(observe(c), baseline)
    c[1].append({"session": c[0]["session"], "end": c[0]["scheduled"], "confirm": c[0]["time"], "confirm_line": c[0]["line"] + 1})
    check(observe(c), baseline)
    tests += 1
    c = synthetic([1005, 1006])
    c[2].update(publication="row", publication_key={"time": c[0]["time"] + 1, "line": 999}, high=float("nan"), mid=None)
    unpublished = observe(c)
    c[2].update(publication_key={"time": c[0]["time"] + 500, "line": 1999}, high="未来改竄")
    check(observe(c), unpublished)
    check((unpublished["ready"], unpublished["band"]["publication_key"]), (False, None))
    tests += 1
    c = synthetic([1005, 1006])
    c[2].update(reference_available=False, published=False, ready=False, reason="前収録なし", begin=None, end=None,
        high="未知の価格", coverage={"未来": float("nan")})
    missing = observe(c)
    check((missing["ready"], missing["reason"], missing["band"]["begin"], missing["band"]["high"]),
        (False, "前収録なし", None, None))
    tests += 1
    c = synthetic([1005, 1006])
    c[2].update(high=1000, low=1000, mid=1000)
    check((observe(c)["ready"], observe(c)["side"]), (True, 0))
    for field, value in (("valid", False), ("last", None), ("last", 0), ("bid", 1007)):
        c = synthetic([1005, 1006])
        c[3][field] = value
        check((observe(c)["ready"], observe(c)["side"]), (False, 0))
    tests += 1
    c = synthetic([1005, 1006, 1007])
    c[1][1]["missing"] = 1
    got = observe(c)
    check((len(got["history"]["resets"]), got["side"]), (1, 0))
    c = synthetic([1005, 1006, 1007])
    c[1][1]["high"] = float("nan")
    got = observe(c)
    check((len(got["history"]["resets"]), got["side"], isinstance(canonical(got), str)), (1, 0, True))
    c = synthetic([1005, 1006])
    for key in ("start", "end", "confirm"):
        c[1][-1][key] += 180
    c[1][-1]["index"] += 1
    c[0].update(scheduled=c[1][-1]["end"], time=c[1][-1]["confirm"] + 1)
    c[0]["feature"]["base"]["base"]["sources"]["current"] = deepcopy(c[1][-1])
    c[3]["now"] = c[0]["time"]
    got = observe(c)
    check((len(got["history"]["resets"]), got["side"]), (1, 0))
    tests += 1
    c = synthetic([1005] * 10 + [1005, 1006])
    c[2].update(id="OR30:" + c[0]["session"], session=c[0]["session"], begin=0, end=1800,
        publication="row", publication_key={"time": 1800, "line": 10}, reaction_start=1800)
    got = observe(c, "O0")
    check((got["reaction_count"], got["selected"]["b"]["index"], got["selected"]["k"]["index"]), (2, 10, 11))
    tests += 1
    corruptions = ("prefix", "clock", "current", "mask", "quote")
    for corruption in corruptions:
        c = synthetic([1005, 1006])
        if corruption == "prefix":
            c[1].pop(0)
        elif corruption == "clock":
            c[1][1]["confirm_line"] = c[1][0]["confirm_line"]
            c[1][1]["confirm"] = c[1][0]["confirm"]
        elif corruption == "current":
            c[0]["feature"]["base"]["base"]["sources"]["current"]["close"] += 1
        elif corruption == "mask":
            c[0]["feature"]["vectors"]["1"][50] = True
        else:
            c[3]["line"] += 1
        rejected = False
        try:
            extract(*c, "P0")
        except ValueError:
            rejected = True
        check(rejected, True)
    tests += 1
    c = synthetic([1005, 1006])
    c[0].update(ready=False, line=None)
    c[0]["feature"] = {"ready": False}
    unknown = extract(c[0], None, None, None, "P0")
    check((unknown["ready"], unknown["source_count"], choose(c[0], unknown, "P0")["line"]), (False, 0, None))
    tests += 1
    return {"成功": True, "テスト件数": tests, "照合項目数": checks, "不一致数": 0,
        "本物入力読取": False, "fit": 0, "市場再生": False, "新計測": 0}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, indent=2, allow_nan=False))
