"""終値の高安突破に、精密OLSの方向と標本内直線性を組み合わせる。"""

from collections import Counter, defaultdict, deque
from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("回帰突破の固定29有効価格", ROOT/"scripts/OBV反転/指標.py")
NUMERIC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = NUMERIC
SPEC.loader.exec_module(NUMERIC)
SOURCE_FIELDS = NUMERIC.SOURCE_FIELDS
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr", "macd_hist")
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
POLICIES = ("L0", "L1", "L2")
ROLES = {policy: "順行" for policy in POLICIES}
RULES = {
    "価格": "同場連続公開有効な直前20足の最高H/最安Lを現Cがstrict突破。現在を旧窓に入れず、各rolling突破を別原Pとする",
    "回帰": "当足を含む直近20終値、x=0..19、切片付きOLS。元floatCをFraction化しDxx=13300/Dxy/Dyyから精密計算",
    "L0": "価格Pかつ実side*OLS20傾き>0かつ実side*中心化MACDヒスト現前差>0。全順行",
    "L1": "L0かつR2定義可能。有限20点と非零傾きから理論上冗長な準備対照",
    "L2": "L1かつR2>=1/2、等号採用。研究仮定であり将来確率/有意水準/最適値ではない",
    "準備": "同場21連続公開有効3分足/OLS20準備/同場現前MACDヒスト有限/現ATR14有限正。数量M/旧BB/上位/CLV/TR上限を加えない",
    "局所": "NP/missing>0/OHLC不正/完全180秒不足/終了前公開はclearして不投入。番号/end/key非連続はclear後の現有効足を新seed可。場跨ぎなし",
    "数値": "ATR/中心化MACD12/26/9は固定29保存正本。同限月carryと欠枠/不正/限月/尾部clear、全幅NP内部更新/partial不投入は旧規約を不変継承",
    "競合": "各候補で同判断複数は同方向も全見送り。全採否確定後にcase深複写し、後から良いR2へ取り直さない",
    "精密": "採否は傾き分子とR2-1/2分子符号。Syy=0はR2未定義で補完せず、表示float/epsilon/clampを使わない",
}


def finite(value: object) -> bool:
    """真偽値・欠測・非有限を除く実数かを検査する。

    引数: value(object)は観測値。
    返り値: boolは有限な整数又は浮動小数点数であること。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def canonical_sha(value: object) -> str:
    """全ての出典と採否を厳密JSONの指紋へ写す。

    引数: value(object)はJSON互換の純数値又は判定列。
    返り値: strは順序と全末端値を保持するSHA256。非有限値は拒否する。
    """
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def exact(value: Fraction | None) -> dict:
    """精密分数と参考表示値を分けて保存する。

    引数: value(Fraction|None)は精密値又は未準備。
    返り値: dictは値/分子/分母/有効。無効を0で補完しない。
    """
    return {"値": float(value) if value is not None else None,
        "分子": value.numerator if value is not None else None,
        "分母": value.denominator if value is not None else None, "有効": value is not None}


def frame_projection(row: dict | None) -> dict | None:
    """保存3分数値から価格出典と使用するATR/ヒストだけを射影する。

    引数: row(dict|None)は固定29の数値足又は参照なし。
    返り値: dict|Noneは15列。数量/OBV/旧BB/上位/未来labelを含めない。
    """
    if row is None:
        return None
    if row["minutes"] != 3:
        raise ValueError("回帰突破は固定29の3分足だけです")
    return {key: deepcopy(row[key]) for key in FRAME_FIELDS}


def ols(values: list[float]) -> dict:
    """20終値の切片付きOLSとR2を元価格から精密計算する。

    引数: values(list[float])は古い順の当足含む20終値。
    返り値: dictは傾き/切片/全平方和/残差平方和/R2と半分比較。表示値は採否に使わない。
    """
    ready = len(values) == 20 and all(finite(value) for value in values)
    dxy = dyy = slope = intercept = syy = sse = r2 = half = None
    if ready:
        ys = [Fraction(value) for value in values]
        total, squared = sum(ys), sum(value*value for value in ys)
        dxy = 20*sum(index*value for index, value in enumerate(ys))-190*total
        dyy = 20*squared-total*total
        slope = dxy/13300
        intercept = total/20-slope*Fraction(19, 2)
        syy = dyy/20
        sse = (dyy-dxy*dxy/13300)/20
        if dyy > 0:
            r2 = dxy*dxy/(13300*dyy)
            half = r2-Fraction(1, 2)
    return {"回帰準備": ready, "回帰点数": len(values), "Dxx": 13300,
        "Dxy": exact(dxy), "Dyy": exact(dyy), "傾き": exact(slope), "切片": exact(intercept),
        "全平方和": exact(syy), "残差平方和": exact(sse), "R2": exact(r2), "R2準備": r2 is not None,
        "傾き符号": (slope > 0)-(slope < 0) if slope is not None else None,
        "R2半分差": exact(half), "R2半分比較符号": (half > 0)-(half < 0) if half is not None else None}


def pure_signal(row: dict, policy: str = "L0") -> dict:
    """新原P又は採用caseを執行用の純13列へ深複写する。

    引数: row(dict)は当時値の原P又は採用case、policy(str)はL0/L1/L2。
    返り値: dictは診断/先着を含まない純13列。原発動時計と現在ATRを保持する。
    """
    if policy not in POLICIES:
        raise ValueError("事前の回帰三案だけです")
    if row["役割"] != "順行" or row["side"] not in (-1, 1):
        raise ValueError("実方向が明示された順行だけです")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示方向が不一致です")
    result = {key: deepcopy(row[key]) for key in SIGNAL_FIELDS if key not in ("イベントID", "入口ID", "bb_mean")}
    event = row["発動ID"]
    result.update(イベントID=event+"_"+policy, 入口ID="3分_"+policy, bb_mean=None)
    return result


def verdicts(context: dict, side: int) -> dict:
    """共通の価格/回帰方向/勢いへR2の準備と値だけを段階追加する。

    引数: context(dict)は原P時点の純数値、side(int)は買1/売-1。
    返り値: dictは三案の全採否と理由。時間対象と技術不採用を分ける。
    """
    base = list(context["M除外理由"])
    if not context["時間条件可"]:
        base.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        base.append("確認遅延30秒超")
    regression = context["OLS20"]
    if regression["傾き符号"] is None or side*regression["傾き符号"] <= 0:
        base.append("OLS20傾き実方向strict正不成立")
    change = context["MACDヒスト変化"]
    if not finite(change) or side*change <= 0:
        base.append("MACDヒスト一足差実方向strict正不成立")
    output = {}
    for policy in POLICIES:
        reasons = list(base)
        if policy in ("L1", "L2") and not regression["R2準備"]:
            reasons.append("R2数値未準備")
        if policy == "L2" and regression["R2半分比較符号"] not in (0, 1):
            reasons.append("R2半分以上不成立")
        output[policy] = {"採用": not reasons, "理由": reasons or ["終値突破と回帰複合採用"], "同時競合": False}
    return output


# ----------------------------------------
# 原価格突破は全て一回保存し、全候補の競合を確定した後でcaseを深複写する。

def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> dict:
    """新しい同場rolling突破を回帰方向とR2の三案へ変換する。

    引数: frames(list[dict])は旧29保存3分、session(str)は場、cutoff/deadline(float)は停止/強制、
    config(dict)は残り時間下限分と確認遅延上限秒を含む固定条件。
    返り値: dictはsignals/raw/decisions/quality。rawとdecisionsは同じ判定列で、片方だけ保存する。
    """
    if any(row["場"] != session or row["minutes"] != 3 for row in frames):
        raise ValueError("当場の保存3分足だけです")
    window, records, selected = deque(maxlen=20), [], defaultdict(list)
    previous_input = None
    counts = Counter({"足数": 0, "価格20窓準備足数": 0, "共通M準備足数": 0, "局所窓解除足数": 0})
    for source in frames:
        frame = frame_projection(source)
        if previous_input is not None and frame["index"] <= previous_input["index"]:
            raise ValueError("3分足番号はstrict昇順だけです")
        valid = bool(frame["publish"] and NUMERIC.VALID(frame) and frame["missing"] == 0
            and frame["end"]-frame["start"] == 180 and frame["confirm"] >= frame["end"])
        consecutive = previous_input is None or (previous_input["index"]+1 == frame["index"]
            and previous_input["end"] == frame["start"]
            and (previous_input["confirm"], previous_input["confirm_line"]) <= (frame["confirm"], frame["confirm_line"]))
        if not valid or not consecutive:
            window.clear()
            counts["局所窓解除足数"] += 1
        ready = bool(valid and len(window) == 20)
        previous = window[-1] if window else None
        current_values = [row["close"] for row in list(window)[1:]]+[frame["close"]] if ready else []
        regression = ols(current_values)
        hist_change = (frame["macd_hist"]-previous["macd_hist"]
            if previous is not None and finite(frame["macd_hist"]) and finite(previous["macd_hist"]) else None)
        reasons = []
        if not ready:
            reasons.append("同場21連続公開価格足未準備")
        if not regression["回帰準備"]:
            reasons.append("OLS20数値未準備")
        if not finite(frame["atr"]) or frame["atr"] <= 0:
            reasons.append("現在ATR14有限正未準備")
        if not finite(hist_change):
            reasons.append("同場隣接公開MACDヒスト未準備")
        counts["足数"] += 1
        counts["価格20窓準備足数"] += ready
        counts["共通M準備足数"] += not reasons
        if ready:
            high, low = max(row["high"] for row in window), min(row["low"] for row in window)
            context = {**deepcopy(frame), "時間足分": 3, "価格準備": True,
                "前20足番号": [row["index"] for row in window],
                "回帰20足番号": [row["index"] for row in list(window)[1:]]+[frame["index"]],
                "直前最高H": high, "直前最安L": low, "前3分参照": frame_projection(previous),
                "OLS20": regression, "MACDヒスト変化": hist_change, "bb_mean": None,
                "共通M準備": not reasons, "M除外理由": reasons,
                "時間条件可": frame["confirm"] < cutoff and deadline-frame["confirm"] >= config["残り時間下限分"]*60,
                "確認遅延条件可": frame["confirm"]-frame["end"] <= config["確認遅延上限秒"]}
            for side in (1, -1):
                if not (frame["close"] > high if side == 1 else frame["close"] < low):
                    continue
                event = f"NK225_{session}_3分_回帰突破_{frame['index']:04d}_{side}"
                record = {**deepcopy(context), "入口系統": "T価格突破", "役割": "順行", "side": side,
                    "方向": "買い" if side == 1 else "売り", "発動ID": event, "QイベントID": event,
                    "イベントID": event, "入口ID": "3分_T価格突破", "要求時計秒": frame["confirm"],
                    "要求原板行": frame["confirm_line"], "足終了時計秒": frame["end"],
                    "確認遅延秒": frame["confirm"]-frame["end"], "期限時計秒": deadline,
                    "残り分_判断時": (deadline-frame["confirm"])/60,
                    "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]),
                    "戦略判定": verdicts(context, side)}
                records.append(record)
                for policy in POLICIES:
                    if record["戦略判定"][policy]["採用"]:
                        selected[policy, frame["confirm"], frame["confirm_line"]].append(record)
        if valid:
            window.append(frame)
        previous_input = frame
    for (policy, _, _), values in selected.items():
        if len(values) > 1:
            for row in values:
                row["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
    signals = {"3分_"+policy: [] for policy in POLICIES}
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                signals["3分_"+policy].append({**deepcopy(row), "入口ID": "3分_"+policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": row["発動ID"]+"_"+policy})
    quality = {"場": session, "時間足分": 3, **dict(counts), "原価格発動数": len(records),
        "先着評価対象外数": sum(not row["先着評価対象"] for row in records),
        "戦略別発動数": {key: len(values) for key, values in signals.items()},
        "戦略採否理由別": {policy: dict(Counter(reason for row in records for reason in row["戦略判定"][policy]["理由"])) for policy in POLICIES}}
    return {"場": session, "signals": signals, "raw": records, "decisions": records, "quality": quality}
