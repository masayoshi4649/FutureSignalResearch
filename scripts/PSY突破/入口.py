"""前20高安の終値突破と幅拡大へ、PSYの整数方向二状態だけを追加する。"""

from collections import Counter, defaultdict, deque
from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("PSY突破の指標", Path(__file__).with_name("指標.py"))
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
OLD_CONFIG = json.loads((ROOT/"study/00029_BB内復帰とOBV非追随/条件.json").read_text(encoding="utf-8"))
POLICIES = ("P0", "P1")
finite = J.finite
CORE_KEYS = ("対象", "時間足分", "出口", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "運用",
    "必須追尾", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割")
EXACT_FIELDS = ("BB幅比較厳密符号", "BB分散差厳密分子", "BB分散差厳密分母")
RULES = {"時間足分": 3, "価格窓本数": 20, "BB期間": 20, "BB偏差倍率": 2, "PSY変化本数": 12,
    "価格": "同場直前20公開高安を固定し、現C>最高Hで買/C<最安Lで売strict。各rolling突破足を別rawP、後続待ちなし",
    "BB窓": "旧は前20C、現は最古1本を除外し現Cを追加した20C。母標準偏差の絶対幅4σ、価格割りなし",
    "幅比較": "Fraction(元floatC)の母分散現前差を厳密比較。nΣC²-(ΣC)²の現前差/n²、分散差の分子分母を保存。幅増加と符号同値、等号0不採用、表示幅float",
    "PSY": "現は末尾13終値の12変化、前はその1本前13終値。U/D/F整数、同値F中立、U+D+F=12。表示率100*count/12",
    "P0": "価格原発動かつBB幅比較厳密符号=+1",
    "P1": "P0かつ現/前PSY12のU-D整数が両方実side正。0不成立、売り100-upを使わない",
    "共通M": "同場20公開価格窓・現ATR正・PSY現前準備・現前幅有限/厳密比較準備を両案共通。PSY方向はP1値条件",
    "局所窓": "価格20/PSYは同場だけ。missing>0/NP/不正はclear後当足不投入、番号飛越missing0有効当足は新種可",
    "数値銀行": "ATRだけ同限月carry、欠枠/番号欠/不正/尾部完全欠枠/限月でclear、有効missing当足は数値だけ投入。全幅NP数値更新のみ、partial不投入",
    "消費": "rawPは幅/PSY/ATR/時間/遅延/保有の採否と別に一回保存、後から良い確認へ取り直さない",
    "解釈": "U>Dの二状態はU>6/連勝/投資家多数ではない。U1D0F11でも正、一発スパイク完全除外の保証なし",
    "役割": "全順行。量/OBV/MACD/一目/RSI/ADXや追加PSY水準を採否に使わない"}


def expected_config() -> dict:
    """固定運用数値とPSY二案の全条件を返す。

    引数: なし。
    返り値: dictは固定前の期待条件。支持・費用・125/250を変更しない。
    """
    return {"版": 1, **{k: deepcopy(OLD_CONFIG[k]) for k in CORE_KEYS}, "全66場既使用": True,
        "戦略": list(POLICIES), "PSY突破": deepcopy(RULES), "表示代表": "事前固定3分P0/P1の2運用",
        "出口定義": {"X0": "固定26のhard125/TP250/期限と必須A5、通常native出口なし"},
        "先着対象": "時間可AND確認遅延可だけ。M/値不成立rawPも反事実先着を別計算、対象外9数値None",
        "競合": "同判断の戦略内複数採用は同方向も全見送り、全P採否確定後にcase深複写",
        "依存": "固定29/28W/E/O/気配経路/entry_metricsと固定26単一建玉X0A5をread再用"}


def validate_config(config: dict) -> None:
    """継承数値と新しいPSY/幅境界を検査する。

    引数: config(dict)は30条件。
    返り値: None。不一致は例外。
    """
    if config != expected_config():
        raise ValueError("固定運用数値又はPSY突破二案の定義が不一致")


def variance_difference(before: list[float], after: list[float]) -> dict:
    """同じ20本の母分散差を正確な分数へ変換する。

    引数: before/after(list[float])は旧/現20終値。
    返り値: dictは幅比較符号と母分散差分子/分母。実幅差の分数ではない。
    """
    if len(before) != 20 or len(after) != 20:
        return {k: None for k in EXACT_FIELDS}
    values = []
    for source in (before, after):
        exact = [Fraction(v) for v in source]
        values.append((20*sum(v*v for v in exact)-sum(exact)**2)/400)
    delta = values[1]-values[0]
    return {"BB幅比較厳密符号": (delta > 0)-(delta < 0),
        "BB分散差厳密分子": delta.numerator, "BB分散差厳密分母": delta.denominator}


def reference(row: dict | None) -> dict | None:
    """前足の公開出典とPSYを固定する。

    引数: row(dict|None)は当時足。
    返り値: dict|NoneはATRと局所PSYを含む参照。
    """
    if row is None:
        return None
    return deepcopy({k: row[k] for k in ("場", *J.SOURCE_FIELDS, "atr", "価格数値入力可", "PSY現", "PSY前", "PSY準備済")})


def verdicts(context: dict, side: int) -> dict:
    """同じMの幅拡大へ、PSY整数二状態の実方向を追加する。

    引数: context(dict)は当時情報、side(int)は買1/売-1。
    返り値: dictはP0/P1全採否。浮動表示の微差はgateへ使わない。
    """
    base = list(context["M除外理由"])
    if not context["時間条件可"]:
        base.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        base.append("確認遅延30秒超")
    if context["BB幅比較厳密符号"] != 1:
        base.append("BB絶対幅strict拡大不成立")
    current, previous = context["PSY現"], context["PSY前"]
    psy = bool(current is not None and previous is not None and side*current["方向差整数"] > 0 and side*previous["方向差整数"] > 0)
    output = {}
    for policy in POLICIES:
        reasons = list(base)
        if policy == "P1" and not psy:
            reasons.append("PSY整数U_D二状態実方向不成立")
        output[policy] = {"採用": not reasons, "理由": reasons or ["価格突破と複合条件採用"], "同時競合": False}
    return output


# ----------------------------------------
# 原価格発動は全て保持し、全採否と競合を確定してから純入口を複写する。

def generate(frames: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict, dict]:
    """rolling高安突破を一回ずつ保存し、二案を同時計で比較する。

    引数: frames(list[dict])は3分数値足、session(str)は場、cutoff/deadline(float)は期限、config(dict)は条件。
    返り値: tuple[dict,dict]は二純入口と全context/rawP。先着/PnLを読まない。
    """
    validate_config(config)
    if any(f["minutes"] != 3 or f["場"] != session for f in frames):
        raise ValueError("当場の3分足だけ")
    window, contexts, records = deque(maxlen=20), [], []
    previous_index, selected = None, defaultdict(list)
    counts = Counter({"足数": 0, "価格20窓準備足数": 0, "共通M準備足数": 0})
    for f in frames:
        continuous = bool(f["publish"] and f["価格数値入力可"] and not f["missing"]
            and (previous_index is None and f["index"] == 0 or previous_index is not None and f["index"] == previous_index+1))
        if not continuous:
            window.clear()
        ready = bool(len(window) == 20 and f["publish"] and f["価格数値入力可"])
        previous = window[-1] if window else None
        before = [r["close"] for r in window]
        after = [*before[1:], f["close"]] if ready else []
        bb = {"旧BB平均": None, "旧BB標準偏差": None, "旧BB幅": None,
            "現BB平均": None, "現BB標準偏差": None, "現BB幅": None}
        if ready:
            for prefix, values in (("旧", before), ("現", after)):
                bb[prefix+"BB平均"] = float(J.W.np.mean(values))
                bb[prefix+"BB標準偏差"] = float(J.W.np.std(values, ddof=0))
                bb[prefix+"BB幅"] = 4*bb[prefix+"BB標準偏差"]
        exact = variance_difference(before, after)
        high = max(r["high"] for r in window) if ready else None
        low = min(r["low"] for r in window) if ready else None
        reasons = []
        if not ready:
            reasons.append("同場直前20公開価格足未準備")
        if not finite(f["atr"]) or f["atr"] <= 0:
            reasons.append("現在ATR正未準備")
        if not f["PSY準備済"]:
            reasons.append("同場PSY現前未準備")
        if not all(finite(bb[k]) for k in ("旧BB幅", "現BB幅")) or exact["BB幅比較厳密符号"] is None:
            reasons.append("現前BB幅精密比較未準備")
        context = {**deepcopy(f), **bb, **exact, "時間足分": 3, "価格準備": ready,
            "前20足番号": [r["index"] for r in window], "現BB足番号": [r["index"] for r in list(window)[1:]]+[f["index"]] if ready else [],
            "直前最高H": high, "直前最安L": low, "前3分参照": reference(previous),
            "共通M準備": not reasons, "M除外理由": reasons,
            "時間条件可": f["confirm"] < cutoff and deadline-f["confirm"] >= config["残り時間下限分"]*60,
            "確認遅延条件可": f["confirm"]-f["end"] <= config["確認遅延上限秒"]}
        contexts.append(context)
        counts["足数"] += 1
        counts["価格20窓準備足数"] += ready
        counts["共通M準備足数"] += not reasons
        if ready:
            for side in (1, -1):
                if not (f["close"] > high if side == 1 else f["close"] < low):
                    continue
                event = f"NK225_{session}_3分_価格突破_{f['index']:04d}_{side}"
                record = {**deepcopy(context), "入口系統": "T価格突破", "役割": "順行", "side": side,
                    "方向": "買い" if side == 1 else "売り", "発動ID": event, "QイベントID": event,
                    "イベントID": event, "入口ID": "3分_T価格突破", "要求時計秒": f["confirm"],
                    "要求原板行": f["confirm_line"], "足終了時計秒": f["end"], "確認遅延秒": f["confirm"]-f["end"],
                    "期限時計秒": deadline, "残り分_判断時": (deadline-f["confirm"])/60,
                    "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]), "戦略判定": verdicts(context, side)}
                records.append(record)
                for policy in POLICIES:
                    if record["戦略判定"][policy]["採用"]:
                        selected[policy, f["confirm"], f["confirm_line"]].append(record)
        if f["publish"] and f["価格数値入力可"] and not f["missing"]:
            window.append(f)
        previous_index = f["index"]
    for (policy, _, _), values in selected.items():
        if len(values) > 1:
            for r in values:
                r["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
    output = {"3分_"+p: [] for p in POLICIES}
    for r in records:
        for policy in POLICIES:
            if r["戦略判定"][policy]["採用"]:
                output["3分_"+policy].append({**deepcopy(r), "入口ID": "3分_"+policy, "戦略": policy,
                    "複合判定": deepcopy(r["戦略判定"][policy]), "イベントID": r["発動ID"]+"_"+policy})
    return output, {"場": session, "時間足分": 3, **dict(counts), "原価格発動数": len(records),
        "全Q発動記録": records, "複合context記録": contexts, "先着評価対象外数": sum(not r["先着評価対象"] for r in records),
        "戦略別発動数": {k: len(v) for k, v in output.items()},
        "戦略採否理由別": {p: dict(Counter(reason for r in records for reason in r["戦略判定"][p]["理由"])) for p in POLICIES}}
