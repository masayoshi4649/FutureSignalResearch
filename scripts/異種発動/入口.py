"""BBとMACD再加速、BBとStoch領域復帰を当時局面で選ぶ。"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from copy import deepcopy
import math

POLICIES = ("T0", "R0", "A0", "S1")
FAMILIES = {"T1": "BBとMACD再加速", "R1": "BBとStoch領域復帰"}
ROLES = {"T1": "順行", "R1": "反転"}
RULES = {"ADX弱境界": 20, "ADX強境界": 25, "Stoch下境界": 20, "Stoch上境界": 80}


def finite(*values: object) -> bool:
    """数値欠測を埋めず有限性を検査する。

    引数: values (object) は候補値。
    返り値: bool は全て有限数値か。
    """
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def validate_config(config: dict) -> None:
    """固定の三尺度・二発動・四規則を検査する。

    引数: config (dict) は21条件。
    返り値: None。不一致は例外。
    """
    if config["時間足分"] != [1, 3, 5] or config["戦略"] != list(POLICIES) or config["発動条件"] != RULES:
        raise ValueError("固定三尺度・四規則・発動閾値だけ")


def classify(higher: list[dict], session: str, config: dict) -> tuple[list[dict], dict]:
    """公開15分ADX/DIだけから即時局面を一回ずつ分類する。

    引数: higher (list[dict]) は15分足、session (str) は場、config (dict) は条件。
    返り値: tuple[list[dict],dict] は全分類と件数。EMAは判定に使用しない。
    """
    validate_config(config)
    records, counts, previous_index, previous_key = [], Counter(), None, None
    for f in higher:
        key = f["confirm"], f["confirm_line"]
        if f["minutes"] != 15 or previous_index is not None and f["index"] <= previous_index:
            raise ValueError("15分以外または足番号重複/後退")
        if f["publish"] and (f["confirm"] < f["end"] or previous_key is not None and key < previous_key):
            raise ValueError("公開時点の先読み/後退")
        previous_index = f["index"]
        if f["publish"]:
            previous_key = key
        ready = bool(f["publish"] and finite(f.get("adx"), f.get("plus_di"), f.get("minus_di")))
        direction = (1 if f["plus_di"] > f["minus_di"] else -1 if f["plus_di"] < f["minus_di"] else 0) if ready else 0
        state = "未準備" if not ready else "レンジ" if f["adx"] <= 20 else "トレンド" if f["adx"] >= 25 and direction else "待機"
        row = {"場": session, "局面ID": f"NK225_{session}_15分_{f['index']:04d}",
               **{k: f[k] for k in ("index", "minutes", "start", "end", "confirm", "confirm_line", "publish", "missing")},
               "上位準備済": ready, "ADX14": f.get("adx"), "+DI14": f.get("plus_di"), "-DI14": f.get("minus_di"),
               "局面": state, "DI方向": direction}
        records.append(row)
        counts[state] += 1
    return records, dict(counts)


def assign(frames: list[dict], states: list[dict]) -> dict[int, dict]:
    """最新公開15分を公開キーと足終了の二重上限で割り当てる。

    引数: frames/states (list[dict]) は下位足/全15分分類。
    返り値: dict[int,dict] は足番号別の上位context。未準備公開足を古正常へ戻さない。
    """
    published = [s for s in states if s["publish"]]
    result, pointer, current = {}, 0, None
    for f in frames:
        while pointer < len(published) and (published[pointer]["confirm"], published[pointer]["confirm_line"]) <= (f["confirm"], f["confirm_line"]) and published[pointer]["end"] <= f["end"]:
            current = published[pointer]
            pointer += 1
        result[f["index"]] = {"上位準備済": bool(current and current["上位準備済"]),
            "局面参照ID": current["局面ID"] if current else None,
            "局面公開秒": current["confirm"] if current else None,
            "局面公開原行": current["confirm_line"] if current else None,
            "局面足終了秒": current["end"] if current else None,
            **{k: current[k] if current else "未準備" if k == "局面" else 0 if k == "DI方向" else None
               for k in ("局面", "DI方向", "ADX14", "+DI14", "-DI14")}}
    return result


def local_ready(frame: dict) -> bool:
    """局所比較へ積める必要単点だけを判定する。

    引数: frame (dict) は一足。
    返り値: bool はBB正幅/ATR正/H/Kの準備。診断用Dは不問。
    """
    return bool(finite(*(frame.get(k) for k in ("bb_mean", "bb_sd", "atr", "macd_hist", "stoch_k", "bandwidth")))
                and frame["bb_mean"] > 0 and frame["bb_sd"] > 0 and frame["atr"] > 0)


def trigger(family: str, side: int, current: dict, previous: dict, older: dict) -> bool:
    """二つの新発動を同じ数値で符号対称に判定する。

    引数: family (str) はT1/R1、side (int) は買1売−1、current/previous/older (dict) は同場三公開足。
    返り値: bool は発動。旧Q/sweep/帯外内復帰の条件は加えない。
    """
    if family == "T1":
        change = side*(current["macd_hist"]-previous["macd_hist"])
        before = side*(previous["macd_hist"]-older["macd_hist"])
        return bool(side*(current["close"]-current["bb_mean"]) > 0
                    and current["bandwidth"] > previous["bandwidth"] and before <= 0 < change)
    if family == "R1":
        prior = previous["stoch_k"] if side == 1 else 100-previous["stoch_k"]
        now = current["stoch_k"] if side == 1 else 100-current["stoch_k"]
        return bool(side*(current["bb_mean"]-current["close"]) > 0 and prior <= 20 < now)
    raise ValueError("未知の発動")


def decision(policy: str, family: str, side: int, context: dict) -> tuple[bool, str]:
    """当時局面だけで固定・混合・切替を選択する。

    引数: policy/family (str) は戦略/発動、side (int) は売買、context (dict) は準備/局面。
    返り値: tuple[bool,str] は採否と理由。
    """
    if policy not in POLICIES or family not in FAMILIES or side not in (1, -1):
        raise ValueError("戦略/発動/方向が不正")
    if not context["共通M準備"]:
        return False, "共通M未準備"
    if policy in ("T0", "R0", "A0"):
        ok = policy == "A0" or family == ("T1" if policy == "T0" else "R1")
        return ok, "固定手法選択" if ok else "固定手法対象外"
    if context["局面"] == "トレンド":
        ok = family == "T1" and side == context["DI方向"]
        return ok, "トレンド同DI方向の継続" if ok else "トレンドで対象外発動"
    if context["局面"] == "レンジ":
        return family == "R1", "レンジの反転" if family == "R1" else "レンジで継続見送り"
    return False, "転換待機"


# ----------------------------------------
# 数値銀行と場内比較履歴を分け、三公開足が揃った時点だけ発動を作る。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float, deadline: float,
             config: dict, states: list[dict] | None = None) -> tuple[dict, dict]:
    """全発動shadowと四戦略のlabelなし入口を生成する。

    引数: frames/higher (list[dict]) は下位/15分、session (str) は場、cutoff/deadline (float) は停止/期限、
    config (dict) は条件、states (list[dict]|None) は一回分類済み上位。
    返り値: tuple[dict,dict] は四集合と全足準備/全発動。将来ラベルは読まない。
    """
    validate_config(config)
    if not frames:
        raise ValueError("空足はdriverで尺度を指定")
    size = frames[0]["minutes"]
    if size not in (1, 3, 5) or any(f["minutes"] != size for f in frames):
        raise ValueError("同じ1/3/5分だけを扱う")
    if states is None:
        states, _ = classify(higher, session, config)
    assigned = assign(frames, states)
    history, prior_index, records, contexts, counts = deque(maxlen=3), None, [], [], Counter()
    prior_key = None
    output, selected = {f"{size}分_{p}": [] for p in POLICIES}, defaultdict(list)
    for f in frames:
        key = f["confirm"], f["confirm_line"]
        if f["publish"] and (f["confirm"] < f["end"] or prior_key is not None and key < prior_key):
            raise ValueError("下位足公開時点の先読み/後退")
        if f["publish"]:
            prior_key = key
        if prior_index is not None and f["index"] <= prior_index:
            raise ValueError("下位足番号重複/後退")
        discontinuous = prior_index is not None and f["index"] != prior_index+1
        prior_index = f["index"]
        if not f["publish"] or f["missing"] or discontinuous or not local_ready(f):
            history.clear()
        if f["publish"] and local_ready(f):
            history.append(f)
        context = assigned[f["index"]]
        reasons = []
        if len(history) != 3:
            reasons.append("同場連続公開三足未準備")
        if not context["上位準備済"]:
            reasons.append("公開15分ADX_DI未準備")
        if not f["publish"]:
            reasons.append("非公開足")
        if f["confirm"]-f["end"] > 30:
            reasons.append("確認遅延30秒超")
        ready = not reasons
        time_ok = f["confirm"] < cutoff and deadline-f["confirm"] >= 3600
        row_context = {**context, "共通M準備": ready, "M除外理由": reasons,
            "局所三足番号": [r["index"] for r in history], "時間条件可": time_ok}
        contexts.append({"場": session, "時間足分": size, **f, **row_context})
        counts["足数"] += 1
        counts["共通M準備足数"] += ready
        if not ready or not time_ok:
            continue
        older, previous, current = history
        for family in FAMILIES:
            for side in (1, -1):
                if not trigger(family, side, current, previous, older):
                    continue
                event = f"NK225_{session}_{size}分_{family}_{f['index']:04d}_{side}"
                verdicts = {p: {"採用": decision(p, family, side, row_context)[0],
                                "理由": [decision(p, family, side, row_context)[1]], "同時競合": False} for p in POLICIES}
                signal = {**f, **row_context, "場": session, "時間足分": size, "入口系統": family, "役割": ROLES[family],
                    "side": side, "方向": "買い" if side == 1 else "売り", "QイベントID": event, "発動ID": event,
                    "イベントID": event, "入口ID": f"{size}分_{family}", "戦略判定": verdicts,
                    "要求時計秒": f["confirm"], "要求原板行": f["confirm_line"], "確認遅延秒": f["confirm"]-f["end"],
                    "足終了時計秒": f["end"], "期限時計秒": deadline, "残り分_判断時": (deadline-f["confirm"])/60,
                    "直前足": {k: previous[k] for k in ("index", "confirm", "confirm_line", "close", "bb_mean", "bb_sd", "bandwidth", "macd_hist", "stoch_k")},
                    "二足前": {k: older[k] for k in ("index", "confirm", "confirm_line", "macd_hist")}}
                records.append(signal)
                for p in POLICIES:
                    if verdicts[p]["採用"]:
                        selected[p, f["confirm"], f["confirm_line"]].append(signal)
    for (policy, _, _), signals in selected.items():
        if len(signals) > 1:
            for s in signals:
                s["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
            continue
        s = signals[0]
        source = f"{size}分_{policy}"
        output[source].append({**deepcopy(s), "入口ID": source, "戦略": policy,
                               "複合判定": deepcopy(s["戦略判定"][policy]), "イベントID": f"{s['発動ID']}_{policy}"})
    return output, {"場": session, "時間足分": size, **dict(counts), "全Q発動記録": records,
                    "複合context記録": contexts, "戦略別発動数": {k: len(v) for k, v in output.items()}}
