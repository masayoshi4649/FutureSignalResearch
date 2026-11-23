"""CCI現前と価格突破の順行へ、上位絶対BB幅の拡大だけを追加する。"""

from collections import Counter, defaultdict, deque
from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("CCI突破の指標", Path(__file__).with_name("指標.py"))
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
OLD_CONFIG = json.loads((ROOT/"study/00030_価格突破とBB幅と方向頻度/条件.json").read_text(encoding="utf-8"))
POLICIES = ("C0", "C1")
finite = J.finite
CORE_KEYS = ("対象", "時間足分", "出口", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "運用",
    "必須追尾", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割")
EXACT_FIELDS = ("BB幅比較厳密符号", "BB分散差厳密分子", "BB分散差厳密分母")
RULES = {"下位分": 3, "上位分": 15, "価格窓本数": 20, "CCI期間": 20, "CCI係数分子": 3, "CCI係数分母": 200,
    "CCI境界": 100, "BB期間": 20, "BB偏差倍率": 2,
    "価格": "当場直前20公開高安を固定し現C>最高Hで買/C<最安Lで売strict。各rolling突破を別rawP、待ち直しなし",
    "CCI": "当場連続公開21足。元OHLC各floatからFraction TP=(H+L+C)/3、同20TP平均μ、MD=Σabs(TP-μ)/20、CCI=(TP現-μ)/((3/200)MD)。MD0欠測、±100等号不採用",
    "C0": "価格原発動かつ現前CCI20とも実side*CCI>100strict、全準備をC1と共有",
    "C1": "C0かつ当場最新公開15分uと隣接公開u-1のBB20絶対幅4σがstrict拡大",
    "BB": "15分数値20終値窓は同限月carry。Fraction母分散現前差を厳密比較し符号+1を採用。表示4σfloat、価格割りなし、等号0不成立",
    "公開": "当場最新公開15分u、end<=現3分endかつkey<=現3分key。前上位は当場隣接公開、最新未準備に旧正常fallbackなし",
    "共通M": "同場20価格窓・CCI現前有効・現ATR正・当場15分BB現前pair有効/幅精密比較準備を両案共通",
    "局所": "3分価格/CCIと15分公開pairは同場。missing>0/NP/不正はclear後局所不投入、番号飛越missing0有効当足は新種可",
    "数値": "ATRと15分BBだけ同限月carry。欠枠/番号欠/不正/尾部完全欠枠/限月clear、有効missing当足は数値だけ投入。全幅NP数値更新、partial不投入",
    "消費": "価格rawPをCCI/上位準備や値/時間/遅延/保有と分離して一回保存、全採否確定後にcase深複写",
    "役割": "全順行。PSY/3分BB値/ADX/RSI/MACD/一目/SAR/量は採否へ追加しない"}


def expected_config() -> dict:
    """固定運用値と新しいCCI二案を組み立てる。

    引数: なし。
    返り値: dictは条件期待値。支持・費用・時計を変えない。
    """
    return {"版": 1, **{k: deepcopy(OLD_CONFIG[k]) for k in CORE_KEYS}, "全66場既使用": True,
        "戦略": list(POLICIES), "CCI突破": deepcopy(RULES), "カタログ版": 2, "CCI手法ID": "I13",
        "表示代表": "事前固定3分C0/C1の2運用", "出口定義": {"X0": "固定26のhard125/TP250/期限と必須A5、通常native出口なし"},
        "先着対象": "時間可AND確認遅延可だけ。M/値不成立rawPも反事実先着を別計算、対象外9数値None",
        "競合": "同判断の戦略内複数採用は同方向も全見送り、全C採否確定後にcase深複写",
        "依存": "固定30/28のW/E/O/気配経路/entry_metricsと固定26単一建玉X0A5をread再用"}


def validate_config(config: dict) -> None:
    """新二案と継承数値が固定定義と一致するか検査する。

    引数: config(dict)は31条件。
    返り値: None。不一致は例外。
    """
    if config != expected_config():
        raise ValueError("固定運用値又はCCI突破二案の規約が不一致")


def reference(row: dict | None) -> dict | None:
    """下位CCI又は上位BBの出典を深複写する。

    引数: row(dict|None)は当時足。
    返り値: dict|Noneは使用した数値・公開元。ラベルは含めない。
    """
    if row is None:
        return None
    fields = ("CCI現", "CCI前", "CCI準備済") if row["minutes"] == 3 else (
        "BB平均", "BB標準偏差", "BB幅", "BB分散分子", "BB分散分母", "BB窓出典", "BB準備済")
    return deepcopy({k: row[k] for k in ("場", *J.SOURCE_FIELDS, "atr", "価格数値入力可", *fields)})


def upper_states(higher: list[dict], session: str) -> list[dict]:
    """最新公開15分の現前pairを作り、不準備を古いpairへ戻さない。

    引数: higher(list[dict])は当場15分数値足、session(str)は場。
    返り値: list[dict]は全15分の出典・pair可否・精密幅比較。
    """
    rows, previous, last_index = [], None, None
    for f in higher:
        if f["minutes"] != 15 or f["場"] != session:
            raise ValueError("当場15分だけ")
        reasons = []
        if last_index is not None and f["index"] != last_index+1:
            reasons.append("15分番号飛越")
        if f["missing"]:
            reasons.append("15分欠枠")
        if not f["publish"]:
            reasons.append("非公開15分")
        if not f["価格数値入力可"]:
            reasons.append("15分OHLC不正")
        if reasons:
            previous = None
        prior = previous
        ready = bool(not reasons and prior is not None and prior["index"]+1 == f["index"] and prior["BB準備済"] and f["BB準備済"])
        if not ready:
            reasons.append("当場隣接公開15分BB未準備")
        exact = {k: None for k in EXACT_FIELDS}
        if ready:
            delta = Fraction(f["BB分散分子"], f["BB分散分母"])-Fraction(prior["BB分散分子"], prior["BB分散分母"])
            exact = {"BB幅比較厳密符号": (delta > 0)-(delta < 0), "BB分散差厳密分子": delta.numerator, "BB分散差厳密分母": delta.denominator}
        rows.append({"場": session, **{k: f[k] for k in ("index", "end", "confirm", "confirm_line", "publish")},
            "上位参照": reference(f), "前上位参照": reference(prior), "上位ペア準備": ready, "上位ペア除外理由": reasons, **exact})
        previous = f if f["publish"] and f["価格数値入力可"] and not f["missing"] else None
        last_index = f["index"]
    return rows


def verdicts(context: dict, side: int) -> dict:
    """共通準備のCCI現前条件へ、上位幅の値条件だけを追加する。

    引数: context(dict)は当時数値、side(int)は買1/売−1。
    返り値: dictは全C採否。CCI表示floatを閾値判定へ使わない。
    """
    base = list(context["M除外理由"])
    if not context["時間条件可"]:
        base.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        base.append("確認遅延30秒超")
    for name in ("CCI現", "CCI前"):
        value = context[name]
        if not value or not value["有効"] or side*value["分子"] <= 100*value["分母"]:
            base.append(name+"実方向100超不成立")
    output = {}
    for policy in POLICIES:
        reasons = list(base)
        if policy == "C1" and context["BB幅比較厳密符号"] != 1:
            reasons.append("上位BB絶対幅strict拡大不成立")
        output[policy] = {"採用": not reasons, "理由": reasons or ["価格突破と複合条件採用"], "同時競合": False}
    return output


# ----------------------------------------
# 価格原発動を先に保存し、全戦略の競合を確定後に純入口を深複写する。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict, dict]:
    """同じ突破時刻でCCI持続と上位幅追加を比較する。

    引数: frames/higher(list[dict])は3/15分数値足、session(str)は場、cutoff/deadline(float)は期限、config(dict)は条件。
    返り値: tuple[dict,dict]は二純入口と全context/rawP。先着/損益を呼ばない。
    """
    validate_config(config)
    if any(f["minutes"] != 3 or f["場"] != session for f in frames):
        raise ValueError("当場3分だけ")
    states = [r for r in upper_states(higher, session) if r["publish"]]
    pointer, upper, previous_index = 0, None, None
    window, contexts, records, selected = deque(maxlen=20), [], [], defaultdict(list)
    counts = Counter({"足数": 0, "価格20窓準備足数": 0, "共通M準備足数": 0})
    for f in frames:
        key = f["confirm"], f["confirm_line"]
        while pointer < len(states) and (states[pointer]["confirm"], states[pointer]["confirm_line"]) <= key and states[pointer]["end"] <= f["end"]:
            upper = states[pointer]
            pointer += 1
        continuous = bool(f["publish"] and f["価格数値入力可"] and not f["missing"]
            and (previous_index is None and f["index"] == 0 or previous_index is not None and f["index"] == previous_index+1))
        if not continuous:
            window.clear()
        ready = bool(len(window) == 20 and f["publish"] and f["価格数値入力可"])
        high, low = (max(r["high"] for r in window), min(r["low"] for r in window)) if ready else (None, None)
        upper_context = {k: deepcopy(upper[k]) if upper else [] if k == "上位ペア除外理由" else False if k == "上位ペア準備" else None
            for k in ("上位参照", "前上位参照", "上位ペア準備", "上位ペア除外理由", *EXACT_FIELDS)}
        reasons = []
        if not ready:
            reasons.append("同場直前20公開価格足未準備")
        if not finite(f["atr"]) or f["atr"] <= 0:
            reasons.append("現在ATR正未準備")
        if not f["CCI準備済"]:
            reasons.append("同場CCI現前未準備")
        if not upper_context["上位ペア準備"]:
            reasons.append("当場最新公開15分BB現前未準備")
        context = {**deepcopy(f), **upper_context, "時間足分": 3, "価格準備": ready,
            "前20足番号": [r["index"] for r in window], "直前最高H": high, "直前最安L": low,
            "前3分参照": reference(window[-1]) if window else None, "共通M準備": not reasons, "M除外理由": reasons,
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
                    "イベントID": event, "入口ID": "3分_T価格突破", "要求時計秒": f["confirm"], "要求原板行": f["confirm_line"],
                    "足終了時計秒": f["end"], "確認遅延秒": f["confirm"]-f["end"], "期限時計秒": deadline,
                    "残り分_判断時": (deadline-f["confirm"])/60, "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]),
                    "戦略判定": verdicts(context, side)}
                records.append(record)
                for policy in POLICIES:
                    if record["戦略判定"][policy]["採用"]:
                        selected[policy, *key].append(record)
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
