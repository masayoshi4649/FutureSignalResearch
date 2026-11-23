"""前足までに確定した山谷への最初終値crossを構造と方向優勢で判別する。"""

from collections import Counter, defaultdict, deque
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("スイング突破の新数値", Path(__file__).with_name("指標.py"))
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
SOURCE_FIELDS, FRAME_FIELDS, NUMERIC_FIELDS = J.SOURCE_FIELDS, J.FRAME_FIELDS, J.NUMERIC_FIELDS
finite, exact, canonical_sha, frame_projection = J.finite, J.exact, J.canonical_sha, J.frame_projection
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
                 "確認遅延秒", "low", "high", "atr", "bb_mean")
POLICIES = ("C0", "C1", "C2")
ROLES = {policy: "切替" for policy in POLICIES}
METADATA_FIELDS = ("元価格side", "判別種別", "突破極値ID", "構造方向", "元極値中心番号")
RULES = {
    "価格": "同場公開連続有効3分。高中心は左2よりstrict高く右2以上、安値は鏡像。右2確認時に確定し、j判断はpまでの最新確定R/Lだけを使う",
    "cross": "買Cp<=R<Cj、売Cp>=L>Cj。p/j隣接、j.end>p.confirm、j.key>p.key。jで新確定するpivotはj判断後に反映",
    "消費": "方向とpivot中心IDの最初Pを一回消費。構造/指標/時間/保有で不採用でも取り直さず、古い有利なpivotを探索しない",
    "構造": "各最新2高と2安。高安とも上ならD+1、とも下ならD-1、同値/混在D0、各2未満は未準備。実side=DならT順行、実side=-DならR反転、他WAIT",
    "C0": "新価格Pかつ構造Dが非零かつ実side*(+DI14--DI14)>0strict。現在ATR有限正。DI準備だけを複合と呼ばない",
    "C1": "C0かつ当場Fast14/3の精密差準備。零差も準備可",
    "C2": "C1かつ実side*Fast差厳密符号>0strict。表示値/epsilon/80-20/交差条件を使わない",
    "局所": "場/契約/missing/index-end非連続/NP/価格不正でpivotとused解除。有効missing0当足はgap後seed可。公開key同値/後退と重複indexは入力拒否",
    "対象時点": "j.end<=p.confirmは価格P無し/消費無しで対象外理由だけ記録し、局所履歴とj新pivot確定は進める。jの全形成期間が水準公開後であるとは主張しない",
    "競合": "候補別で同判断複数なら同方向も全見送り。全採否確定後だけcase深複写。構造ラベルだけでXF出口を変えない",
    "数値": J.RULES,
}


def pure_signal(row: dict, policy: str = "C0") -> dict:
    """採用原Pを未来情報なしの純13列へ写す。

    引数: row(dict)は当時の原P又は採用enriched、policy(str)はC0/C1/C2。
    返り値: dictはj現在ATRを保持する執行用列。役割未定のWAITは拒否する。
    """
    if policy not in POLICIES or row["side"] not in (-1, 1) or row["役割"] not in ("順行", "反転"):
        raise ValueError("固定三案の実方向/実役割だけです")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向の表示不一致")
    result = {key: deepcopy(row[key]) for key in SIGNAL_FIELDS if key not in ("イベントID", "入口ID", "bb_mean")}
    result.update(イベントID=row["発動ID"]+"_"+policy, 入口ID="3分_"+policy, bb_mean=None)
    return result


def pivot(five: list[dict], side: int, session: str) -> dict:
    """中心と右2確認足を別出典として極値を記録する。

    引数: five(list[dict])は連続5足、side(int)は高値1/安値-1、session(str)は場。
    返り値: dictは一意ID・価格・中心/確認SOURCE・5足番号。RSIや間隔条件は持ち込まない。
    """
    center, current = five[2], five[-1]
    name = "高値" if side == 1 else "安値"
    return {"場": session, "極値ID": f"NK225_{session}_3分_確定{name}_{center['index']:04d}",
        "極値種別": name, "極値side": side, "極値価格": center["high"] if side == 1 else center["low"],
        "中心番号": center["index"], "確認足番号": current["index"],
        "中心出典": {key: deepcopy(center[key]) for key in ("場", *SOURCE_FIELDS)},
        "確認出典": {key: deepcopy(current[key]) for key in ("場", *SOURCE_FIELDS)},
        "五足番号": [row["index"] for row in five]}


def structure(highs: list[dict], lows: list[dict]) -> tuple[bool, int | None]:
    """独立した最新2高・2安から操作的な構造方向を決める。

    引数: highs/lows(list[dict])は各古い順の直近2極値。
    返り値: tuple[bool,int|None]は準備と方向。未準備と同値/混在0を区別する。
    """
    ready = len(highs) == len(lows) == 2
    if not ready:
        return False, None
    up = highs[-1]["極値価格"] > highs[-2]["極値価格"] and lows[-1]["極値価格"] > lows[-2]["極値価格"]
    down = highs[-1]["極値価格"] < highs[-2]["極値価格"] and lows[-1]["極値価格"] < lows[-2]["極値価格"]
    return True, 1 if up else -1 if down else 0


def verdicts(row: dict) -> dict:
    """価格・構造・DI基準へFast準備と値だけを追加する。

    引数: row(dict)は最初Pの当時判断。
    返り値: dictは三案の全採否/理由。既に消費したPを後から取り直さない。
    """
    reasons = list(row["M除外理由"])
    if not row["時間条件可"]:
        reasons.append("要求時間条件外")
    if not row["確認遅延条件可"]:
        reasons.append("確認遅延30秒超")
    if row["構造方向"] == 0:
        reasons.append("構造方向同値又は混在WAIT")
    if row["DI優勢符号"] is None or row["side"]*row["DI優勢符号"] <= 0:
        reasons.append("DI実方向優勢strict正不成立")
    result = {}
    for policy in POLICIES:
        own = list(reasons)
        if policy in ("C1", "C2") and not row["Fast準備"]:
            own.append("Fast14_3精密差未準備")
        if policy == "C2" and (row["Fast差厳密符号"] is None or row["side"]*row["Fast差厳密符号"] <= 0):
            own.append("Fast実方向strict正不成立")
        result[policy] = {"採用": not own, "理由": own or ["確定スイング突破と構造DI複合採用"], "同時競合": False}
    return result


# ----------------------------------------
# 最初Pは採否前に消費し、当足で新たに確定する極値は判断後だけへ進める。

def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> dict:
    """確定済み水準への後続crossを新しい母集団として構築する。

    引数: frames(list[dict])はJの限定3分数値、session(str)は場、cutoff/deadline(float)は停止/強制、
    config(dict)は残り時間下限分/確認遅延上限秒を含む事前条件。
    返り値: dictは全数値/全極値/全監視/全初回P/三採否とmetadata。市場先着/運用は計算しない。
    """
    five, highs, lows, used = deque(maxlen=5), deque(maxlen=2), deque(maxlen=2), set()
    pivots, traces, records, metadata = [], [], [], {}
    previous_input, published_key = None, None
    counts = Counter({"局所解除足数": 0, "対象時点外足数": 0, "再cross消費済み数": 0})

    def snapshot() -> dict:
        """現在の最新極値IDと消費件数だけを保存する。

        引数: なし。generate内の当場状態を参照する。
        返り値: dictは価格状態の小型snapshot。全窓/全usedを毎足複製しない。
        """
        return {"高値ID": [row["極値ID"] for row in highs], "安値ID": [row["極値ID"] for row in lows],
                "局所五足番号": [row["index"] for row in five], "使用済み数": len(used)}

    for source in frames:
        row = J.numeric_projection(source)
        if row["場"] != session or row["minutes"] != 3:
            raise ValueError("当場の新3分数値だけです")
        key = row["confirm"], row["confirm_line"]
        if previous_input is not None and row["index"] <= previous_input["index"]:
            raise ValueError("足番号重複又は後退")
        if row["publish"] and (row["confirm"] < row["end"] or published_key is not None and key <= published_key):
            raise ValueError("公開key同値/後退又は終了前公開")
        before, actions = snapshot(), []
        reasons = []
        if previous_input is not None and (row["index"] != previous_input["index"]+1 or row["start"] != previous_input["end"]):
            reasons.append("番号又は終了非連続")
        if row["missing"]:
            reasons.append("欠枠")
        if not row["publish"]:
            reasons.append("非公開")
        if not J.price_valid(row):
            reasons.append("完全3分価格不正")
        if "限月変更" in row["DMI解除理由"]:
            reasons.append("限月変更")
        if reasons:
            five.clear(); highs.clear(); lows.clear(); used.clear()
            counts["局所解除足数"] += 1
            actions.append({"動作": "局所解除", "理由": reasons})
        valid = bool(row["publish"] and not row["missing"] and J.price_valid(row))
        previous = five[-1] if five else None
        if valid and previous is not None:
            if row["end"] <= previous["confirm"]:
                counts["対象時点外足数"] += 1
                actions.append({"動作": "価格観測対象外", "理由": ["当足終了が前足公開以前"], "前足番号": previous["index"]})
            else:
                ready, direction = structure(list(highs), list(lows))
                for side, latest in ((1, highs[-1] if highs else None), (-1, lows[-1] if lows else None)):
                    if latest is None:
                        continue
                    level = latest["極値価格"]
                    crossed = previous["close"] <= level < row["close"] if side == 1 else previous["close"] >= level > row["close"]
                    if not crossed:
                        continue
                    marker = side, latest["極値ID"]
                    if marker in used:
                        counts["再cross消費済み数"] += 1
                        actions.append({"動作": "使用済みcross見送り", "side": side, "極値ID": latest["極値ID"]})
                        continue
                    used.add(marker)
                    event = f"NK225_{session}_3分_スイング突破_{row['index']:04d}_{side}_{latest['中心番号']:04d}"
                    role = "順行" if ready and direction == side else "反転" if ready and direction == -side else None
                    branch = "T" if role == "順行" else "R" if role == "反転" else "WAIT"
                    diff = row["plus_di"]-row["minus_di"] if finite(row["plus_di"]) and finite(row["minus_di"]) else None
                    missing = []
                    if not ready:
                        missing.append("最新2高2安未準備")
                    if not row["DMI準備"] or diff is None:
                        missing.append("DMI14有限未準備")
                    if not finite(row["atr"]) or row["atr"] <= 0:
                        missing.append("現在ATR14有限正未準備")
                    time_ok = row["confirm"] < cutoff and deadline-row["confirm"] >= config["残り時間下限分"]*60
                    delay_ok = row["confirm"]-row["end"] <= config["確認遅延上限秒"]
                    record = {**deepcopy(row), "発動ID": event, "イベントID": event, "入口ID": "3分_スイング突破",
                        "入口系統": "確定スイング突破", "時間足分": 3, "side": side, "元価格side": side,
                        "方向": "買い" if side == 1 else "売り", "役割": role, "判別種別": branch,
                        "突破極値ID": latest["極値ID"], "突破価格": level, "元極値中心番号": latest["中心番号"],
                        "構造準備": ready, "構造方向": direction,
                        "構造参照": {"高値ID": [p["極値ID"] for p in highs], "安値ID": [p["極値ID"] for p in lows]},
                        "前3分参照": frame_projection(previous), "DI差": diff,
                        "DI優勢符号": (diff > 0)-(diff < 0) if diff is not None else None,
                        "共通M準備": not missing, "M除外理由": missing, "時間条件可": time_ok, "確認遅延条件可": delay_ok,
                        "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"], "足終了時計秒": row["end"],
                        "確認遅延秒": row["confirm"]-row["end"], "期限時計秒": deadline,
                        "残り分_判断時": (deadline-row["confirm"])/60, "先着評価対象": time_ok and delay_ok, "bb_mean": None}
                    record["戦略判定"] = verdicts(record)
                    records.append(record)
                    metadata[event] = {name: deepcopy(record[name]) for name in METADATA_FIELDS}
                    actions.append({"動作": "初回cross消費", "発動ID": event, "side": side, "極値ID": latest["極値ID"]})

        # ----------------------------------------
        # 現在jで確定する中心は、上のP判定が終わってから将来の判断へ渡す。
        if valid:
            five.append(row)
            if len(five) == 5:
                values = list(five)
                for side, field, history in ((1, "high", highs), (-1, "low", lows)):
                    center = values[2][field]
                    found = all(side*(center-part[field]) > 0 for part in values[:2]) and all(side*(center-part[field]) >= 0 for part in values[3:])
                    if found:
                        point = pivot(values, side, session)
                        pivots.append(point); history.append(point)
                        actions.append({"動作": "極値確定", "極値ID": point["極値ID"]})
        traces.append({"場": session, "index": row["index"], "公開key": list(key), "足終了時計秒": row["end"],
            "監視前": before, "動作": actions, "監視後": snapshot()})
        previous_input = row
        if row["publish"]:
            published_key = key
    selected = defaultdict(list)
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                selected[policy, row["要求時計秒"], row["要求原板行"]].append(row)
    for (policy, _, _), same in selected.items():
        if len(same) > 1:
            for row in same:
                row["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
    signals = {"3分_"+policy: [] for policy in POLICIES}
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                signals["3分_"+policy].append({**deepcopy(row), "イベントID": row["発動ID"]+"_"+policy,
                    "入口ID": "3分_"+policy, "戦略": policy, "複合判定": deepcopy(row["戦略判定"][policy])})
    quality = {"場": session, "時間足分": 3, "入力足数": len(frames), **dict(counts), "確定極値数": len(pivots),
        "高値極値数": sum(p["極値side"] == 1 for p in pivots), "安値極値数": sum(p["極値side"] == -1 for p in pivots),
        "原価格発動数": len(records), "先着評価対象外数": sum(not r["先着評価対象"] for r in records),
        "戦略別発動数": {key: len(values) for key, values in signals.items()},
        "構造判別数": dict(Counter(r["判別種別"] for r in records)),
        "戦略採否理由別": {p: dict(Counter(reason for r in records for reason in r["戦略判定"][p]["理由"])) for p in POLICIES}}
    return {"場": session, "frames": {3: [J.numeric_projection(row) for row in frames]}, "signals": signals, "raw": records, "decisions": records,
        "pivots": pivots, "monitor_trace": traces, "metadata": metadata, "quality": quality}
