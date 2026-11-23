"""74の保存公開足から内包足の偽突破と複数技法の直接条件を抽出する。"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math


SOURCE_FIELDS = ("session", "index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing", "open", "high", "low", "close")
SLOT_FIELDS = ("scheduled", "time", "line", "side", "role", "atr", "D", "reason", "ready", "slot_id")
VALUE_FIELDS = {"F01": 0, "F02": 1, "F03": 2, "F15": 14, "F48": 47, "F52": 51}
SIDES, POLICIES = (1, -1), ("I0", "H0", "H1")
STATUS_REASONS = {"有効": "直近900秒の終値確認が有効", "未確認": "終値確認待ち",
    "確認期限切れ": "B後3足の終値確認なし", "確認窓外": "終値確認が直近900秒窓外",
    "否定": "確認後に偽突破端を終値で否定"}
RULES = {"参照": "73保存Q0の特徴全文。旧ready・DI/FastK/ADX/ATR/Dは再計算しない",
    "出典": "feature73.base.historyのreference_sources可視10本とreaction_sources可視5本。最新はbase.base.sources.currentとSOURCE13全文一致",
    "可視": "当場、end<=scheduledかつ(confirm,confirm_line)<=(time,line)。未来は価格検査前に除外。可視の欠足を未来足で補完しない",
    "完全": "全15足が完全180秒・publish真・missing0・OHLC正有限。番号/終了開始隣接、公開key strict増加",
    "内包": "I.high<A.highかつI.low>A.low。A/I/Bは隣接三足",
    "偽突破": "買いB.low<I.lowかつB.high<I.high。売りB.high>I.highかつB.low>I.low",
    "確認": "B後1..3の別足で最初の終値strict反対端突破。買close>I.high、売close<I.low。最初C固定",
    "否定": "C後の別足で最初の終値が買B.low以下/売B.high以上。等号含む。否定後復活なし",
    "確認窓": "C.endは(scheduled-900,scheduled]。遅い公開による持越しを救済しない",
    "優先": "各sideの有効形をC.index降順、B.index降順で一つ選ぶ。否定statusは確認窓外に優先",
    "資格": "F02>=0/F03>0。F01>0順行。F01<0反転はF52=1/F48<0/F15>0。rawDI0及びF010は新H不採用",
    "鏡像": "価格反射で高安/DI/実sideを交換。両方向同時適格や保存値の鏡像矛盾は停止",
    "選択": "I0は保存Q0純値、Hは適格Hを優先し他は保存Q0。H0/H1はpolicy以外同値",
    "出力": "O49純10項目+session/policy/origin/pattern_idだけ。旧feature/予測/損益を転記しない",
    "限定": "原典price-crossを閉足終値へ適応した独自規則。新fit・市場計算・心理原因の識別なし"}


# ----------------------------------------
def finite(value: object) -> bool:
    """boolを除く有限な保存数値を判定する。

    引数: value(object)は保存値。
    返り値: boolは有限int/floatの場合に真。
    """
    return type(value) in (int, float) and math.isfinite(value)


def canonical(value: object) -> str:
    """型と数値表現を保存したcanonicalJSONを作る。

    引数: value(object)はJSON互換値。
    返り値: strはUTF8保存前の文字列。非有限値は拒否する。
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def clock(slot: dict, allow_placeholder: bool = False) -> tuple:
    """定時と実判断の公開限界を検査する。

    引数: slot(dict)は元純判断、allow_placeholder(bool)は未準備のline=Noneを許すか。
    返り値: tuple[float,int|None]は実判断key。不正時計は例外。
    """
    if (not isinstance(slot, dict) or not isinstance(slot.get("session"), str) or not slot["session"]
            or not isinstance(slot.get("slot_id"), str) or not slot["slot_id"]
            or not finite(slot.get("scheduled")) or not finite(slot.get("time"))
            or slot["time"] < slot["scheduled"]
            or not (type(slot.get("line")) is int and slot["line"] >= 0
                or allow_placeholder and slot.get("line") is None)):
        raise ValueError("元純判断の場・識別・時計が不正")
    return slot["time"], slot["line"]


def visible(rows: object, slot: dict) -> list[dict]:
    """未来を先に除外し、当時可視なSOURCE13だけを深く複写する。

    引数: rows(object)は参照又は反応の保存配列、slot(dict)は判断限界。
    返り値: list[dict]は可視出典。判定不能な時計・可視schema矛盾は例外。
    """
    if not isinstance(rows, list):
        raise ValueError("参照又は反応SOURCE配列なし")
    result, limit = [], clock(slot)
    for row in rows:
        if not isinstance(row, dict) or row.get("session") != slot["session"] or not finite(row.get("end")):
            raise ValueError("SOURCEの場又は可視終端を判定できない")
        if row["end"] > slot["scheduled"]:
            continue
        if not finite(row.get("confirm")) or type(row.get("confirm_line")) is not int or row["confirm_line"] < 0:
            raise ValueError("SOURCEの公開keyを判定できない")
        if (row["confirm"], row["confirm_line"]) > limit:
            continue
        if (not set(SOURCE_FIELDS) <= set(row) or type(row["index"]) is not int or row["index"] < 0
                or type(row["minutes"]) is not int or row["minutes"] != 3
                or type(row["publish"]) is not bool or type(row["missing"]) is not int
                or not finite(row["start"])):
            raise ValueError("可視SOURCE13のschema不正")
        item = {key: deepcopy(row[key]) for key in SOURCE_FIELDS}
        if (not item["publish"] or item["missing"] != 0 or item["end"] - item["start"] != 180
                or item["confirm"] < item["end"]):
            raise ValueError("可視SOURCEが公開完全3分足でない")
        if (not all(finite(item[key]) and item[key] > 0 for key in ("open", "high", "low", "close"))
                or item["high"] < max(item["open"], item["close"], item["low"])
                or item["low"] > min(item["open"], item["close"], item["high"])):
            raise ValueError("可視SOURCEのOHLC不正")
        result.append(item)
    return result


def sources(slot: dict, feature: dict) -> list[dict]:
    """旧53の履歴schemaから可視15足を取り、現足と隣接性を検査する。

    引数: slot(dict)は元判断、feature(dict)は73Q0特徴。
    返り値: list[dict]は参照10+反応5のSOURCE13。旧ready真との矛盾は停止する。
    """
    try:
        history = feature["base"]["history"]
        current = feature["base"]["base"]["sources"]["current"]
        reference = visible(history["reference_sources"], slot)
        reaction = visible(history["reaction_sources"], slot)
    except (KeyError, TypeError) as exc:
        raise ValueError("73Q0の旧53履歴又は現足出典なし") from exc
    if len(reference) != 10 or len(reaction) != 5:
        raise ValueError("可視参照10本・反応5本の不足又は重複")
    rows = reference + reaction
    if not isinstance(current, dict) or not set(SOURCE_FIELDS) <= set(current):
        raise ValueError("旧現足SOURCE13なし")
    if canonical(rows[-1]) != canonical({key: current[key] for key in SOURCE_FIELDS}):
        raise ValueError("最新SOURCEと旧currentの全文差")
    for left, right in zip(rows, rows[1:]):
        if (right["index"] != left["index"] + 1 or right["start"] != left["end"]
                or (right["confirm"], right["confirm_line"]) <= (left["confirm"], left["confirm_line"])):
            raise ValueError("15SOURCEの番号・終了開始・公開keyが不連続")
    return rows


# ----------------------------------------
def patterns(rows: list[dict], scheduled: float) -> list[dict]:
    """全内包形を列挙し、最初の終値確認とその後の最初の否定を固定する。

    引数: rows(list[dict])は完全隣接15足、scheduled(float)は予定判断秒。
    返り値: list[dict]はA/I/Bで成立した全形と5区分。足内順序を推測しない。
    """
    candidates = []
    prices = [{key: Fraction(str(row[key])) for key in ("high", "low", "close")} for row in rows]
    for b_index in range(2, len(rows)):
        a, inside, b = prices[b_index - 2:b_index + 1]
        if not (inside["high"] < a["high"] and inside["low"] > a["low"]):
            continue
        for side in SIDES:
            formed = (b["low"] < inside["low"] and b["high"] < inside["high"]) if side == 1 else (
                b["high"] > inside["high"] and b["low"] > inside["low"])
            if not formed:
                continue
            confirmation = None
            observed = min(3, len(rows) - b_index - 1)
            for index in range(b_index + 1, b_index + observed + 1):
                confirmed = prices[index]["close"] > inside["high"] if side == 1 else prices[index]["close"] < inside["low"]
                if confirmed:
                    confirmation = index
                    break
            denial = None
            if confirmation is not None:
                for index in range(confirmation + 1, len(rows)):
                    denied = prices[index]["close"] <= b["low"] if side == 1 else prices[index]["close"] >= b["high"]
                    if denied:
                        denial = index
                        break
            status = "未確認" if observed < 3 else "確認期限切れ"
            if confirmation is not None:
                status = "有効" if scheduled - 900 < rows[confirmation]["end"] <= scheduled else "確認窓外"
                if denial is not None:
                    status = "否定"
            source_b = rows[b_index]
            identity = f"{source_b['session']}|H|{side:+d}|{source_b['index']}|{float(source_b['confirm']).hex()}|{source_b['confirm_line']}"
            candidates.append({"id": identity, "side": side, "A": deepcopy(rows[b_index - 2]), "I": deepcopy(rows[b_index - 1]),
                "B": deepcopy(source_b), "C": deepcopy(rows[confirmation]) if confirmation is not None else None,
                "denial": deepcopy(rows[denial]) if denial is not None else None, "status": status, "reason": STATUS_REASONS[status],
                "confirmation_observed": observed, "confirmation_complete": observed == 3,
                "confirmation_deadline_end": source_b["end"] + 540,
                "confirmation_line": rows[b_index - 1]["high" if side == 1 else "low"],
                "denial_line": source_b["low" if side == 1 else "high"]})
    return candidates


def values_for(feature: dict) -> dict:
    """73保存float64の6値とraw背景を取り、鏡像とmask型を検査する。

    引数: feature(dict)は旧ready真のQ0特徴。
    返り値: dict[str,dict]は方向別の元値。指標再計算・float32化・0補完をしない。
    """
    vectors, background = feature.get("vectors"), feature.get("background_direction")
    if (not isinstance(vectors, dict) or set(vectors) != {"1", "-1"}
            or type(background) is not int or background not in (-1, 0, 1)):
        raise ValueError("両方向vector又はraw背景なし")
    result = {}
    for side in SIDES:
        vector = vectors[str(side)]
        if not isinstance(vector, list) or len(vector) != 64:
            raise ValueError("保存Q0の64特徴が必要")
        values = {name: deepcopy(vector[index]) for name, index in VALUE_FIELDS.items()}
        if not all(finite(value) for value in values.values()) or values["F52"] not in (0, 1):
            raise ValueError("直接条件の保存値又はADXmask不正")
        if values["F01"] != 0 and (int(values["F01"] > 0) - int(values["F01"] < 0)) != side * background:
            raise ValueError("F01とraw背景の方向が不一致")
        result[str(side)] = {**values, "raw_background_direction": background}
    for name in ("F01", "F02", "F03", "F15"):
        if result["1"][name] != -result["-1"][name]:
            raise ValueError("方向正規化値の鏡像差")
    for name in ("F48", "F52"):
        if result["1"][name] != result["-1"][name]:
            raise ValueError("方向不変値の鏡像差")
    return result


def qualification(side: int, selected: dict | None, values: dict) -> dict:
    """有効形へFastK・DI・反転用ADX/終値位置を固定順で適用する。

    引数: side(int)は実方向、selected(dict|None)は最新有効形、values(dict)は保存6値と背景。
    返り値: dictはqualified/role/reason/values。失格でも当時の配置と数値を残す。
    """
    background, di = values["raw_background_direction"], values["F01"]
    role = "待機" if background == 0 or di == 0 else "順行" if side == background else "反転"
    if selected is None:
        reason = "有効な終値確認なし"
    elif background == 0:
        reason = "上位DI同値"
    elif di == 0:
        reason = "DI優勢差同値"
    elif values["F02"] < 0:
        reason = "FastK中央差が逆向き"
    elif values["F03"] <= 0:
        reason = "FastK進行が非正"
    elif di < 0 and values["F52"] != 1:
        reason = "ADX変化が未知"
    elif di < 0 and values["F48"] >= 0:
        reason = "ADXが非減速"
    elif di < 0 and values["F15"] <= 0:
        reason = "15分終値位置が非正"
    else:
        reason = "順行条件適格" if di > 0 else "反転条件適格"
    return {"qualified": reason in ("順行条件適格", "反転条件適格"), "role": role, "reason": reason, "values": deepcopy(values)}


# ----------------------------------------
def extract(slot: dict, feature73: dict) -> dict:
    """当時可視15足から全形・最新確認・両側の複合資格を純粋に返す。

    引数: slot(dict)は元Q0純判断、feature73(dict)は保存Q0の全64特徴。
    返り値: dictはready/reason/source_count/source_sha256/candidates/selected/qualifications/side/role。
        本物入力・市場・教師・損益を読み込まず、引数も変更しない。
    """
    if not isinstance(feature73, dict) or type(feature73.get("ready")) is not bool:
        raise ValueError("73特徴のready型不正")
    empty_values = {name: None for name in (*VALUE_FIELDS, "raw_background_direction")}
    result = {"ready": feature73["ready"], "reason": "旧73特徴が未準備", "source_count": 0,
        "source_sha256": None, "candidates": [], "selected": {"1": None, "-1": None},
        "qualifications": {str(side): {"qualified": False, "role": "待機", "reason": "旧73特徴が未準備", "values": deepcopy(empty_values)} for side in SIDES},
        "side": 0, "role": "待機"}
    if not feature73["ready"]:
        return result
    clock(slot)
    rows, values = sources(slot, feature73), values_for(feature73)
    result.update(source_count=15, source_sha256=hashlib.sha256(canonical(rows).encode("utf-8")).hexdigest(),
        candidates=patterns(rows, slot["scheduled"]))
    for side in SIDES:
        candidates = [row for row in result["candidates"] if row["side"] == side and row["status"] == "有効"]
        if candidates:
            result["selected"][str(side)] = deepcopy(max(candidates, key=lambda row: (row["C"]["index"], row["B"]["index"])))
        result["qualifications"][str(side)] = qualification(side, result["selected"][str(side)], values[str(side)])
    qualified = [side for side in SIDES if result["qualifications"][str(side)]["qualified"]]
    if len(qualified) > 1:
        raise ValueError("両方向が同時に内包偽突破の複合条件適格")
    if qualified:
        side = qualified[0]
        result.update(side=side, role=result["qualifications"][str(side)]["role"], reason="内包偽突破の複合候補")
    else:
        result["reason"] = "有効な終値確認なし" if not any(result["selected"].values()) else "内包偽突破の複合条件不適格"
    return result


def choose(source_Q0_slot: dict, observation: dict, policy: str) -> dict:
    """保存Q0と新H優先を選び、O49純項目だけへ射影する。

    引数: source_Q0_slot(dict)は元純判断、observation(dict)はextract結果、policy(str)はI0/H0/H1。
    返り値: dictは純10項目とsession/policy/origin/pattern_id。feature・予測・保有を転記しない。
    """
    if policy not in POLICIES or not all(key in source_Q0_slot for key in SLOT_FIELDS):
        raise ValueError("政策又は元Q0純10項目が不正")
    if (type(source_Q0_slot["ready"]) is not bool or not isinstance(observation, dict)
            or observation.get("ready") is not source_Q0_slot["ready"]
            or type(source_Q0_slot["side"]) is not int or source_Q0_slot["side"] not in (-1, 0, 1)):
        raise ValueError("元Q0と新観測の準備又は方向が不整合")
    clock(source_Q0_slot, allow_placeholder=not source_Q0_slot["ready"])
    result = {key: deepcopy(source_Q0_slot[key]) for key in SLOT_FIELDS}
    result.update(session=source_Q0_slot["session"], policy=policy, origin="保存Q0", pattern_id=None)
    if policy != "I0" and observation["side"]:
        side = observation["side"]
        selected, allowed = observation["selected"][str(side)], observation["qualifications"][str(side)]
        if (type(side) is not int or side not in SIDES or not observation["ready"] or not allowed["qualified"]
                or selected is None or selected["status"] != "有効" or allowed["role"] != observation["role"]):
            raise ValueError("新Hの採用方向・資格・形が不整合")
        result.update(side=side, role=observation["role"], reason="内包偽突破の複合候補",
            origin="内包偽突破", pattern_id=selected["id"])
    return result
