"""突破水準の最初の再テストを、構造・勢い・数量加重終値位置で判別する。"""

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
SPEC = importlib.util.spec_from_file_location("再テスト量方向の固定29有効価格", ROOT/"scripts/OBV反転/指標.py")
NUMERIC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = NUMERIC
SPEC.loader.exec_module(NUMERIC)
SOURCE_FIELDS = NUMERIC.SOURCE_FIELDS
FRAME_FIELDS = ("場", *SOURCE_FIELDS, "atr", "macd_hist", "数量参照")
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
    "確認遅延秒", "low", "high", "atr", "bb_mean")
POLICIES = ("A0", "A1", "A2")
ROLES = {policy: "切替" for policy in POLICIES}
RULES = {
    "登録": "同場前20公開有効高安R/L(R>L)を現Cがstrict突破したb。価格21足と時間/遅延だけで一監視を登録し、ATR/H/Qで間引かない",
    "水準": "bでR/L/B/元side/公開keyを固定。used(元side,B)は受理時消費、同場再登録なし。親監視中と消費/取消/満了同足の登録不可",
    "寿命": "b次1..6足、7足目は満了。start_j>b.confirmかつ公開key_j>b.keyの正常足だけ対象。通常b+1は時点対象外だが年齢1に数える",
    "初回": "対象足の反対端終値取消を先に判定し、最初の買Low<=B/売High>=Bを一回消費。後足へ取り直さない",
    "分岐": "Tは元side*(C-B)>0で実side=元side/順行。RはL<C<R strictで実side=-元side/反転。B等号はWAIT、反対端終値到達/飛越は先取消",
    "A0": "T/R構造かつj現ATR14有限正/当場隣接現前ヒスト有限/実side*δH>0/時間遅延可",
    "A1": "A0かつ同場21足CMF数値準備。数量/幅/窓/総量の除外を値効果と分ける",
    "A2": "A1かつ実side*CMF21>0strict。0不成立、追加水準なし",
    "CMF": "元floatH/L/C/q各Fraction。CLV=(2C-H-L)/(H-L)、CMF21=Σ(CLV*q)/Σq。q完全有限非負/各幅正/総q正、0量有効・零幅と総量0は未定義",
    "局所": "価格/CMFは同場の公開有効完全180秒/missing0/index-end-key連続。CMFはq不完全/零幅でも切断、価格窓/親監視はqだけでは切断しない",
    "優先": "価格公開不正/連続性解除/返済期限→age>6→対象時点外(寿命のみ)→反対端終値→初touch→構造/技術/時間採否",
    "数値": "固定29のATR/中心化MACDと監査済Qをread共有。数値carry/reset/NP内部更新と当場公開窓を分け、旧BB/k数量M/OLS/上位/CLV単足/TR上限を加えない",
    "執行": "同じjの新要求+1価格秒/TTL30/全三XF、現在費用後122円strict正起動/名目床/現jATR固定D不変。新要求j30分間引き主、登録bは診断のみ",
    "競合": "全採否確定後case深複写。同key複数は同方向も全見送り。純監視と実pending/建玉を分離、自動ドテンなし",
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
    """保存3分数値から価格出典と使用するATR/ヒスト/数量参照だけを射影する。

    引数: row(dict|None)は固定29の数値足又は参照なし。
    返り値: dict|Noneは16列。数量参照以外のOBV/旧BB/上位/未来labelを含めない。
    """
    if row is None:
        return None
    if row["minutes"] != 3:
        raise ValueError("再テスト量方向は固定29の3分足だけです")
    return {key: deepcopy(row[key]) for key in FRAME_FIELDS}


def price_reasons(frame: dict) -> list[str]:
    """数量と無関係な公開価格足の利用可否を列挙する。

    引数: frame(dict)は当場3分足。
    返り値: list[str]は不正/非公開/欠枠/部分幅/終了前公開の理由。
    """
    reasons = []
    if not frame["publish"]: reasons.append("非公開足")
    if not NUMERIC.VALID(frame): reasons.append("OHLC不正")
    if frame["missing"] != 0: reasons.append("欠枠あり")
    if frame["end"]-frame["start"] != 180: reasons.append("完全180秒不成立")
    if frame["confirm"] < frame["end"]: reasons.append("終了前公開")
    return reasons


def adjacent(previous: dict | None, current: dict) -> bool:
    """番号・足区間・公開keyの連続性を数量とは別に調べる。

    引数: previous(dict|None)は前入力、current(dict)は当足。
    返り値: boolは最初の足又は隣接して公開順が非後退であること。
    """
    return previous is None or (previous["index"]+1 == current["index"] and previous["end"] == current["start"]
        and (previous["confirm"], previous["confirm_line"]) <= (current["confirm"], current["confirm_line"]))


def cmf_window(rows: list[dict]) -> dict:
    """有効な同場足のCLVを観測数量で加重する。

    引数: rows(list[dict])は検査済み連続足で最大21本。
    返り値: dictは窓足番号/加重和/総量/単位量平均/精密CMFと準備理由。
    """
    multipliers = [(2*Fraction(row["close"])-Fraction(row["high"])-Fraction(row["low"]))
        /(Fraction(row["high"])-Fraction(row["low"])) for row in rows]
    quantities = [Fraction(row["数量参照"]["観測差分量"]) for row in rows]
    total = sum(quantities, Fraction(0))
    weighted = sum((value*q for value, q in zip(multipliers, quantities)), Fraction(0))
    ready = len(rows) == 21 and total > 0
    reasons = []
    if len(rows) != 21: reasons.append("同場CMF21連続足未準備")
    if total <= 0: reasons.append("CMF観測総量正未準備")
    cmf = weighted/total if ready else None
    return {"CMF窓足番号": [row["index"] for row in rows], "CMF準備": ready, "CMF除外理由": reasons,
        "観測量合計": exact(total), "加重CLV合計": exact(weighted),
        "CMF全量正同値": bool(len(rows) == 21 and quantities[0] > 0 and all(q == quantities[0] for q in quantities)),
        "単位量CLV平均": exact(sum(multipliers, Fraction(0))/len(rows) if len(rows) == 21 else None),
        "CMF21": exact(cmf), "CMF符号": (cmf > 0)-(cmf < 0) if cmf is not None else None}


def volume_panels(frames: list[dict], session: str) -> list[dict]:
    """価格監視から独立した数量加重窓を全足について作る。

    引数: frames(list[dict])は旧29の3分全数値/Q、session(str)は場。
    返り値: list[dict]は全CMFpanel。数量不完全を価格窓の解除へ伝えない。
    """
    rows, window, previous = [], deque(maxlen=21), None
    for source in frames:
        frame = frame_projection(source)
        if frame["場"] != session or frame["minutes"] != 3:
            raise ValueError("当場の3分数値だけです")
        if previous is not None and frame["index"] <= previous["index"]:
            raise ValueError("3分足番号はstrict昇順だけです")
        reasons = price_reasons(frame)
        if not adjacent(previous, frame): reasons.append("価格番号区間公開順非連続")
        current_bad = price_reasons(frame)
        qref = frame["数量参照"]
        q = qref.get("観測差分量") if isinstance(qref, dict) else None
        quantity_ok = isinstance(qref, dict) and qref.get("数量基準完全") is True and finite(q) and q >= 0
        if not quantity_ok: reasons.append("数量基準完全非負未準備")
        width_ok = NUMERIC.VALID(frame) and frame["high"] > frame["low"]
        if not width_ok: reasons.append("CLV幅正未準備")
        if reasons: window.clear()
        if not current_bad and quantity_ok and width_ok: window.append(frame)
        panel = cmf_window(list(window))
        clv = ((2*Fraction(frame["close"])-Fraction(frame["high"])-Fraction(frame["low"]))
            /(Fraction(frame["high"])-Fraction(frame["low"]))) if width_ok else None
        rows.append({"場": session, "index": frame["index"], "足出典": {key: deepcopy(frame[key]) for key in ("場", *SOURCE_FIELDS)},
            "CLV現": exact(clv), "CMF窓解除理由": reasons, **panel})
        previous = frame
    return rows


def pure_signal(row: dict, policy: str = "A0") -> dict:
    """最初jの実役割と方向を保持して純13列へ写す。

    引数: row(dict)は採用T/R発動、policy(str)はA0/A1/A2。
    返り値: dictは当時jの価格/ATR/要求keyを持つ純入口。親未来や先着を含めない。
    """
    if policy not in POLICIES or row["side"] not in (-1, 1) or row["役割"] not in ("順行", "反転"):
        raise ValueError("三切替候補の実T/R役割だけです")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向と表示方向に差があります")
    result = {key: deepcopy(row[key]) for key in SIGNAL_FIELDS if key not in ("イベントID", "入口ID", "bb_mean")}
    result.update(イベントID=row["発動ID"]+"_"+policy, 入口ID="3分_"+policy, bb_mean=None)
    return result


def verdicts(context: dict) -> dict:
    """同じ最初jからCMF準備と実方向符号を段階追加する。

    引数: context(dict)は構造/当時数値/時間を持つ発動。
    返り値: dictは全三採否。WAITを逆方向へ補完しない。
    """
    base = list(context["M除外理由"])
    side = context["side"]
    if side not in (-1, 1): base.append("価格構造待機")
    if not context["時間条件可"]: base.append("要求時間条件外")
    if not context["確認遅延条件可"]: base.append("確認遅延30秒超")
    delta = context["MACDヒスト変化"]
    if side not in (-1, 1) or not finite(delta) or side*delta <= 0:
        base.append("MACDヒスト一足差実方向strict正不成立")
    output = {}
    for policy in POLICIES:
        reasons = list(base)
        if policy in ("A1", "A2") and not context["CMF準備"]: reasons.append("CMF21数値未準備")
        if policy == "A2" and (side not in (-1, 1) or context["CMF符号"] is None or side*context["CMF符号"] <= 0):
            reasons.append("CMF21実方向strict正不成立")
        output[policy] = {"採用": not reasons, "理由": reasons or ["最初再テストと複合採用"], "同時競合": False}
    return output


# ----------------------------------------
# 純価格監視は実建玉と独立。一つの親から最初の対象再テストだけを消費する。

def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> dict:
    """一監視の突破登録からT/R/WAITを確定し、CMF三案を作る。

    引数: frames(list[dict])は旧29全3分/Q、session(str)は場、cutoff/deadline(float)は停止/強制、config(dict)は固定条件。
    返り値: dictはsignals/全j判定/全足panel/監視trace/登録/品質。先着/損益を呼ばない。
    """
    if any(row["場"] != session or row["minutes"] != 3 for row in frames):
        raise ValueError("当場の保存3分足だけです")
    panels = volume_panels(frames, session)
    window, records, trace, registrations = deque(maxlen=20), [], [], []
    watch, previous, used, selected = None, None, set(), defaultdict(list)
    counts = Counter({"足数": 0, "価格20窓準備足数": 0, "CMF準備足数": 0})
    for source, panel in zip(frames, panels):
        frame = frame_projection(source)
        invalid = price_reasons(frame)
        if not adjacent(previous, frame): invalid.append("価格番号区間公開順非連続")
        current_bad = price_reasons(frame)
        if invalid: window.clear()
        prior = window[-1] if window else None
        price_ready = not current_bad and len(window) == 20
        before, actions = deepcopy(watch), []
        had_watch = watch is not None
        now, key = frame["confirm"], (frame["confirm"], frame["confirm_line"])
        time_ok = now < cutoff and deadline-now >= config["残り時間下限分"]*60
        delay_ok = now-frame["end"] <= config["確認遅延上限秒"]
        if watch is not None:
            age = frame["index"]-watch["登録足"]["index"]
            ending = list(invalid)
            if now >= deadline: ending.append("返済期限")
            if ending:
                actions.append({"動作": "監視取消", "登録ID": watch["登録ID"], "年齢": age, "理由": ending})
                watch = None
            elif age > 6:
                actions.append({"動作": "監視満了", "登録ID": watch["登録ID"], "年齢": age, "理由": ["六足満了"]})
                watch = None
            elif not (frame["start"] > watch["登録足"]["confirm"] and key > (watch["登録足"]["confirm"], watch["登録足"]["confirm_line"])):
                actions.append({"動作": "対象時点外", "登録ID": watch["登録ID"], "年齢": age, "理由": ["登録後に始まる後続公開足ではない"]})
            else:
                side, boundary = watch["元価格side"], watch["固定境界B"]
                opposite = frame["close"] <= watch["旧L"] if side == 1 else frame["close"] >= watch["旧R"]
                touched = frame["low"] <= boundary if side == 1 else frame["high"] >= boundary
                if opposite:
                    actions.append({"動作": "反対端終値取消", "登録ID": watch["登録ID"], "年齢": age, "理由": ["反対端終値到達又は飛越"]})
                    watch = None
                elif touched:
                    kind = "T" if side*(frame["close"]-boundary) > 0 else "R" if watch["旧L"] < frame["close"] < watch["旧R"] else "WAIT"
                    actual_side = side if kind == "T" else -side if kind == "R" else None
                    role = "順行" if kind == "T" else "反転" if kind == "R" else "待機"
                    delta = frame["macd_hist"]-prior["macd_hist"] if prior is not None and finite(frame["macd_hist"]) and finite(prior["macd_hist"]) else None
                    reasons = []
                    if prior is None or not finite(delta): reasons.append("当場隣接公開ヒスト未準備")
                    if not finite(frame["atr"]) or frame["atr"] <= 0: reasons.append("現在ATR14有限正未準備")
                    event = watch["登録ID"]+f"_再テスト_{frame['index']:04d}_{kind}"
                    record = {**deepcopy(frame), **deepcopy(panel), "時間足分": 3, "入口系統": "再テスト構造判定",
                        "登録参照": deepcopy(watch), "登録ID": watch["登録ID"], "元価格side": side, "構造区分": kind,
                        "年齢": age, "前3分参照": frame_projection(prior), "MACDヒスト変化": delta,
                        "共通M準備": not reasons, "M除外理由": reasons, "時間条件可": time_ok, "確認遅延条件可": delay_ok,
                        "役割": role, "side": actual_side, "方向": "買い" if actual_side == 1 else "売り" if actual_side == -1 else "待機",
                        "発動ID": event, "イベントID": event, "QイベントID": event, "入口ID": "3分_再テスト構造判定",
                        "要求時計秒": now, "要求原板行": frame["confirm_line"], "足終了時計秒": frame["end"],
                        "確認遅延秒": now-frame["end"], "期限時計秒": deadline, "残り分_判断時": (deadline-now)/60,
                        "先着評価対象": time_ok and delay_ok and actual_side in (-1, 1), "bb_mean": None}
                    record["戦略判定"] = verdicts(record)
                    records.append(record)
                    actions.append({"動作": "再テスト消費", "登録ID": watch["登録ID"], "発動ID": event, "構造区分": kind, "年齢": age})
                    for policy in POLICIES:
                        if record["戦略判定"][policy]["採用"]: selected[policy, now, frame["confirm_line"]].append(record)
                    watch = None
        if price_ready:
            lower, upper = min(row["low"] for row in window), max(row["high"] for row in window)
            for side in (1, -1):
                if not (frame["close"] > upper if side == 1 else frame["close"] < lower): continue
                boundary = upper if side == 1 else lower
                reasons = []
                if had_watch: reasons.append("監視中又は同足で監視終了")
                if not upper > lower: reasons.append("旧高安幅正未準備")
                if not time_ok: reasons.append("登録時間条件外")
                if not delay_ok: reasons.append("登録確認遅延30秒超")
                if (side, boundary) in used: reasons.append("同方向固定水準使用済み")
                event = f"NK225_{session}_3分_突破登録_{frame['index']:04d}_{side}"
                actions.append({"動作": "突破登録見送り" if reasons else "突破登録", "登録ID": event, "元価格side": side,
                    "固定境界B": boundary, "理由": reasons})
                if reasons: continue
                used.add((side, boundary))
                low_source = next(row for row in reversed(window) if row["low"] == lower)
                high_source = next(row for row in reversed(window) if row["high"] == upper)
                watch = {"登録ID": event, "登録足": {key: deepcopy(frame[key]) for key in ("場", *SOURCE_FIELDS)},
                    "元価格side": side, "旧L": lower, "旧R": upper, "固定境界B": boundary,
                    "旧20足番号": [row["index"] for row in window], "旧L足番号": low_source["index"], "旧R足番号": high_source["index"]}
                actions[-1]["登録参照"] = deepcopy(watch)
                registrations.append(deepcopy(watch))
        trace.append({"場": session, "index": frame["index"], "足出典": {key: deepcopy(frame[key]) for key in ("場", *SOURCE_FIELDS)},
            "監視前": before, "動作": actions, "監視後": deepcopy(watch), "使用済み水準数": len(used)})
        counts["足数"] += 1; counts["価格20窓準備足数"] += price_ready; counts["CMF準備足数"] += panel["CMF準備"]
        if not current_bad: window.append(frame)
        previous = frame
    ending_watch = watch is not None
    if ending_watch:
        trace[-1]["動作"].append({"動作": "場末監視取消", "登録ID": watch["登録ID"], "理由": ["場末"]})
        trace[-1]["監視後"] = None
    for (policy, _, _), values in selected.items():
        if len(values) > 1:
            for row in values: row["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
    signals = {"3分_"+policy: [] for policy in POLICIES}
    for row in records:
        for policy in POLICIES:
            if row["戦略判定"][policy]["採用"]:
                signals["3分_"+policy].append({**deepcopy(row), "入口ID": "3分_"+policy, "戦略": policy,
                    "複合判定": deepcopy(row["戦略判定"][policy]), "イベントID": row["発動ID"]+"_"+policy})
    actions = Counter(action["動作"] for item in trace for action in item["動作"])
    quality = {"場": session, "時間足分": 3, **dict(counts), "突破登録数": len(registrations), "最初再テスト消費数": len(records),
        "構造区分別": dict(Counter(row["構造区分"] for row in records)), "監視動作別": dict(actions),
        "場末残監視取消数": int(ending_watch), "終了時監視残数": 0,
        "先着評価対象外数": sum(not row["先着評価対象"] for row in records),
        "戦略別発動数": {key: len(values) for key, values in signals.items()},
        "戦略採否理由別": {policy: dict(Counter(reason for row in records for reason in row["戦略判定"][policy]["理由"])) for policy in POLICIES}}
    metadata = {row["発動ID"]: {"元登録ID": row["登録ID"], "元価格side": row["元価格side"],
        "元登録時計秒": row["登録参照"]["登録足"]["confirm"],
        "元登録原板行": row["登録参照"]["登録足"]["confirm_line"], "判別種別": row["構造区分"]} for row in records}
    return {"場": session, "signals": signals, "raw": records, "decisions": records, "volume_panels": panels,
        "monitor_trace": trace, "registrations": registrations, "quality": quality, "metadata": metadata}

