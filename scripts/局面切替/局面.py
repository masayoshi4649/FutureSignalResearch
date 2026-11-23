"""公開15分足のADX・EMA・DMIで局面を判別し、発動手法を切り替える。"""

from collections import Counter
import math


RULES = {"局面足分": 15, "EMA期間": 20, "DMI期間": 14, "ADX弱境界": 20, "ADX強境界": 25}
POLICIES = ("B1", "B2", "S0", "S1", "S2")
WAIT = ("待機", 0)
UNKNOWN = ("未準備", 0)
RANGE = ("レンジ", 0)


def validate_config(config: dict) -> None:
    """局面の固定尺度と閾値を検査する。

    引数: config(dict)は局面条件を含む全条件。
    返り値: None。異なる値はValueErrorで拒否する。
    """
    if config["局面条件"] != RULES:
        raise ValueError("15分ADX20/25・EMA20/DMI14の固定条件が不一致")


def number(value: float | None) -> float | None:
    """JSONへ保存できる有限値だけを返す。

    引数: value(float|None)は指標値。
    返り値: float|None は有限数または欠測。欠測を0にしない。
    """
    return float(value) if value is not None and math.isfinite(value) else None


def directions(frame: dict) -> tuple[bool, int, int, int]:
    """共通準備とEMA/DMIの方向を別々に判定する。

    引数: frame(dict)は15分の確定特徴。
    返り値: tuple[bool,int,int,int] は準備・EMA方向・DI方向・一致方向。
    """
    keys = ("close", "ema20", "ema20_previous", "adx", "plus_di", "minus_di")
    ready = bool(frame["publish"] and all(number(frame.get(key)) is not None for key in keys))
    if not ready:
        return False, 0, 0, 0
    close, average, previous = frame["close"], frame["ema20"], frame["ema20_previous"]
    ema = 1 if close > average > previous else -1 if close < average < previous else 0
    di = 1 if frame["plus_di"] > frame["minus_di"] else -1 if frame["plus_di"] < frame["minus_di"] else 0
    return True, ema, di, ema if ema == di else 0


# ----------------------------------------
# 即時分類と履歴保持を同じ入力から比較し、未来の成績を参照しない。

def instant(ready: bool, adx: float | None, direction: int) -> tuple[str, int]:
    """S1の20/25閾値から現在の局面を分類する。

    引数: ready(bool)は準備、adx(float|None)は強さ、direction(int)は一致方向。
    返り値: tuple[str,int] は局面名と方向。20/25の等号は計画どおり扱う。
    """
    if not ready:
        return UNKNOWN
    if adx <= 20:
        return RANGE
    if adx >= 25 and direction:
        return "トレンド", direction
    return WAIT


def sticky(previous: tuple[str, int], ready: bool, adx: float | None,
           direction: int) -> tuple[str, int]:
    """S2の局面記憶と固定した二境界から次の状態を決める。

    引数: previous(tuple[str,int])は前状態、ready(bool)は準備、adx(float|None)は強さ、direction(int)は一致方向。
    返り値: tuple[str,int] は現在局面。方向崩れと25未満の方向反転は待機へ移る。
    """
    if not ready:
        return UNKNOWN
    if adx <= 20:
        return RANGE
    if previous[0] == "レンジ" and adx < 25:
        return RANGE
    if previous[0] == "トレンド" and direction == previous[1]:
        return "トレンド", direction
    if adx >= 25 and direction:
        return "トレンド", direction
    return WAIT


def build(higher: list[dict], session: str, config: dict) -> tuple[list[dict], dict]:
    """15分足を一回ずつ処理し、全局面と遷移を不変の記録へ保存する。

    引数: higher(list[dict])は同場15分足、session(str)は場、config(dict)は固定条件。
    返り値: tuple[list[dict],dict] は全局面記録と件数。場を越えて記憶しない。
    """
    validate_config(config)
    first, second, previous_ready = WAIT, WAIT, False
    last_index, last_key = None, None
    records, counts = [], Counter()
    categories = {"S1": Counter(), "S2": Counter()}
    for frame in higher:
        if frame["minutes"] != 15:
            raise ValueError("局面は15分足だけを使う")
        index, key = frame["index"], (frame["confirm"], frame["confirm_line"])
        if last_index is not None and index <= last_index:
            raise ValueError("15分足番号が重複または後退")
        if frame["publish"] and (frame["confirm"] < frame["end"] or last_key is not None and key <= last_key):
            raise ValueError("15分足の公開順が不正")
        ready, ema, di, direction = directions(frame)
        resets = []
        if last_index is not None and index != last_index + 1:
            resets.append("15分足番号飛越")
        if frame["missing"]:
            resets.append("15分欠枠")
        if not frame["publish"]:
            resets.append("非公開15分足")
        if not ready:
            resets.append("上位指標未準備")
        before_first, before_second = first, second
        input_second = WAIT if resets else second
        first = instant(ready, frame.get("adx"), direction)
        second = sticky(input_second, ready, frame.get("adx"), direction)
        comparable = previous_ready and ready and not resets
        counts["15分足数"] += 1
        counts["公開15分足数"] += int(frame["publish"])
        counts["共通M準備15分足数"] += int(ready)
        counts["記憶初期化足数"] += bool(resets)
        counts["初回準備分類数"] += int(ready and (not previous_ready or bool(resets)))
        counts["S1切替回数"] += int(comparable and first != before_first)
        counts["S2切替回数"] += int(comparable and second != before_second)
        for name, state in (("S1", first), ("S2", second)):
            categories[name][state[0]] += 1
        record = {"場": session, "局面ID": f"NK225_{session}_15分_{index:04d}", "時間足分": 15,
                  **{k: frame[k] for k in ("index", "start", "end", "confirm", "confirm_line", "publish", "missing")},
                  "共通M準備": ready, "EMA方向": ema, "DI方向": di, "一致方向": direction,
                  "ADX14": number(frame.get("adx")), "+DI14": number(frame.get("plus_di")),
                  "-DI14": number(frame.get("minus_di")), "15分終値": number(frame.get("close")),
                  "EMA20": number(frame.get("ema20")), "EMA20前": number(frame.get("ema20_previous")),
                  "S1直前局面": before_first[0], "S1直前方向": before_first[1],
                  "S1局面": first[0], "S1方向": first[1],
                  "S2直前局面": before_second[0], "S2直前方向": before_second[1],
                  "S2適用前局面": input_second[0], "S2適用前方向": input_second[1],
                  "S2局面": second[0], "S2方向": second[1],
                  "記憶初期化理由": sorted(set(resets)),
                  "切替比較可能": bool(comparable), "S1切替": bool(comparable and first != before_first),
                  "S2切替": bool(comparable and second != before_second)}
        records.append(record)
        previous_ready, last_index = ready, index
        if frame["publish"]:
            last_key = key
    return records, {**dict(counts), "S1局面足数": dict(categories["S1"]), "S2局面足数": dict(categories["S2"])}


# ----------------------------------------
# 下位足の公開上限へ局面を割当て、局面の更新回数を下位足数で増やさない。

def assign(frames: list[dict], regimes: list[dict]) -> dict[int, dict]:
    """価格足の公開キーと終了時点までに存在する最新局面を割り当てる。

    引数: frames(list[dict])は同尺度下位足、regimes(list[dict])は同場15分分類。
    返り値: dict[int,dict] は下位足番号別の局面と出典。未知を後の分類で補わない。
    """
    result, pointer, current, previous = {}, 0, None, None
    for frame in frames:
        key = frame["confirm"], frame["confirm_line"]
        if frame["index"] in result or previous is not None and frame["index"] <= previous:
            raise ValueError("下位足番号が重複または後退")
        previous = frame["index"]
        while pointer < len(regimes) and (regimes[pointer]["confirm"], regimes[pointer]["confirm_line"]) <= key and regimes[pointer]["end"] <= frame["end"]:
            current = regimes[pointer]
            pointer += 1
        ready = bool(current is not None and current["共通M準備"] and frame["publish"])
        row = {"共通M準備": ready, "局面参照ID": current["局面ID"] if current else None,
               "局面公開秒": current["confirm"] if current else None,
               "局面公開原行": current["confirm_line"] if current else None,
               "局面足終了秒": current["end"] if current else None,
               "局面準備不可理由": [] if ready else ["局面参照なし" if current is None else "非公開下位足" if not frame["publish"] else "上位指標未準備"]}
        for name in ("EMA方向", "DI方向", "一致方向", "ADX14", "+DI14", "-DI14", "15分終値", "EMA20", "EMA20前",
                     "S1局面", "S1方向", "S2局面", "S2方向"):
            row[name] = current[name] if current is not None else "未準備" if name in ("S1局面", "S2局面") else 0 if name.endswith("方向") else None
        result[frame["index"]] = row
    return result


def allowed(policy: str, family: str, side: int, context: dict) -> tuple[bool, str]:
    """当時の局面でQ1/Q2/待機を選び、全見送り理由を返す。

    引数: policy(str)はB1/B2/S0/S1/S2、family(str)はQ1/Q2、side(int)は売買側、context(dict)は当時局面。
    返り値: tuple[bool,str] は選択可否と理由。ラベルや将来損益は使わない。
    """
    if policy not in POLICIES or family not in ("Q1", "Q2") or side not in (1, -1):
        raise ValueError("選択戦略/手法/方向が不正")
    if not context["共通M準備"]:
        return False, "共通局面準備なし"
    if policy in ("B1", "B2", "S0"):
        accepted = policy == "S0" or family == ("Q1" if policy == "B1" else "Q2")
        return accepted, "固定手法選択" if accepted else "固定手法の対象外"
    state, direction = context[policy + "局面"], context[policy + "方向"]
    if state == "トレンド":
        if direction not in (1, -1):
            raise ValueError("トレンド局面の方向が不正")
        if family != "Q1":
            return False, "トレンドで反転を見送り"
        return side == direction, "トレンド方向の順行" if side == direction else "トレンド逆向きを見送り"
    if state == "レンジ":
        return family == "Q2", "レンジの反転" if family == "Q2" else "レンジで順行を見送り"
    if state == "待機":
        return False, "転換待機"
    raise ValueError("準備済み局面の状態名が不正")
