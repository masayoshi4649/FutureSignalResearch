"""直前極値更新と旧BB内終値の反転を、観測OBV非追随の追加だけで比較する。"""

from collections import Counter, defaultdict, deque
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("OBV反転の指標", Path(__file__).with_name("指標.py"))
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
OLD_CONFIG = json.loads((ROOT/"study/00028_基準線復帰と上位一目の方向/条件.json").read_text(encoding="utf-8"))
POLICIES = ("R0", "R1")
finite = J.finite
CORE_KEYS = ("対象", "時間足分", "出口", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "運用",
    "必須追尾", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割")
RULES = {"時間足分": 3, "価格窓本数": 20, "BB期間": 20, "BB偏差倍率": 2, "BB標準偏差": "母標準偏差・直前20公開終値のみ",
    "MACD期間": [12, 26, 9], "MACD平均": "各系列期間本数算術seed・EMAα=2/(n+1)",
    "MACD原点": "数値reset後の最初の有効終値oを保存しC-oへ12/26/9を適用。同限月carry、未来原点禁止",
    "価格": "買currentL<直前20最安L・売currentH>直前20最高H、現在Cは旧BB下<C<旧BB上strict内。ヒゲBB外/前C帯外を追加しない",
    "価格窓": "同場の連続公開有効20本。現在足除外、非公開/価格欠枠/不正でclear。missing当足不投入、missing0番号飛越後の有効当足は新窓投入可。数量不完全だけではclearしない",
    "k": "直前20価格窓の買最安L/売最高H、同値は最新足を選ぶ。未来山谷確認なし",
    "R0": "価格原発動と同場隣接公開MACDヒスト一足差の実side正",
    "R1": "R0かつside*(OBV_t-OBV_k)>0strict。OBV差同値は不成立",
    "共通M": "前20価格窓・同場隣接現前hist有限・現ATR正・当足数量基準完全/有限非負q・t/k同一OBV有効区間を両案共通。kより前の全20数量完全は要求しない",
    "数量": "固定14Q.aggregateをread再用。数量基準完全と有限非負qを使用、完全0有効。RVOL準備/正平均gateなし",
    "OBV": "同場連続完全公開区間の初足OBV0種、次足からsign(C_t-C_prev)*当足qを加算。同値close増分0",
    "OBV解除": "毎場/非公開/価格番号欠/欠枠/不正/数量不完全で切断、missing当足は不投入、次の完全有効公開足を新種。missing0番号飛越後の有効当足は新種可。MACD/ATRは数量不完全だけでは切らない",
    "数値銀行": "MACD/ATRだけ同限月carry、欠枠/番号欠/不正/尾部完全欠枠/限月変更でclear。有効欠枠後当足投入。不正不投入。全幅NPは数値更新のみ、partial不投入",
    "消費": "価格rawPをM/勢い/OBV値/時間/遅延/保有と分離して一回保存、後続確認で時計や価格を取り直さない",
    "役割": "全反転。上位一目/ADX/SAR/RSI/他量閾値は採否へ追加しない"}


def expected_config() -> dict:
    """固定28の運用数値と、新しい反転二案を組み立てる。

    引数: なし。
    返り値: dictは全条件の期待値。支持・費用・125/250を変えない。
    """
    return {"版": 1, **{k: deepcopy(OLD_CONFIG[k]) for k in CORE_KEYS}, "全66場既使用": True,
        "戦略": list(POLICIES), "OBV反転": deepcopy(RULES), "表示代表": "事前固定3分R0/R1の2運用",
        "出口定義": {"X0": "固定26のhard125/TP250/期限と必須A5、通常native出口なし"},
        "先着対象": "時間可AND確認遅延可だけ。M/値不成立rawPも反事実先着を別計算、対象外9数値None",
        "競合": "同判断の戦略内複数採用は同方向も全見送り、全R採否確定後にcase深複写",
        "依存": "固定14Q数量集約と固定28W/E/O/先着/entry_metrics/固定26単一建玉X0A5をread再用"}


def validate_config(config: dict) -> None:
    """継承数値・数量・価格・二案の定義を検査する。

    引数: config(dict)は29条件。
    返り値: None。不一致は例外。
    """
    if config != expected_config():
        raise ValueError("固定の運用数値又はOBV反転二案の定義が不一致")


def reference(row: dict | None) -> dict | None:
    """当時の足とMACD/OBVの出典を小さく固定する。

    引数: row(dict|None)は同場の当時足。
    返り値: dict|Noneは計算に用いた参照で、未来ラベルを含まない。
    """
    if row is None:
        return None
    fields = ("場", *J.SOURCE_FIELDS, "atr", "macd", "macd_signal", "macd_hist", "MACD原点", "MACD原点出典",
        "価格数値入力可", "数量参照", "数量入力可", "OBV", "OBV区間ID", "OBV区間足数", "OBV公開可")
    return deepcopy({k: row[k] for k in fields})


def verdicts(context: dict, side: int) -> dict:
    """同じ数量準備でMACDとOBV非追随の値条件だけを比較する。

    引数: context(dict)は実sideの準備と当時値、side(int)は買1/売-1。
    返り値: dictはR0/R1の全採否と理由。
    """
    base = list(context["M除外理由"])
    if not context["時間条件可"]:
        base.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        base.append("確認遅延30秒超")
    change = context["MACDヒスト変化"]
    if not finite(change) or side*change <= 0:
        base.append("MACDヒスト一足差実方向不成立")
    output = {}
    for policy in POLICIES:
        reasons = list(base)
        if policy == "R1" and (not finite(context["OBV比較差"]) or side*context["OBV比較差"] <= 0):
            reasons.append("価格極値に対するOBV非追随不成立")
        output[policy] = {"採用": not reasons, "理由": reasons or ["旧帯内終値と複合反転採用"], "同時競合": False}
    return output


# ----------------------------------------
# 価格窓は数量不完全でも継続し、採否準備は実方向のkだけを参照する。

def generate(frames: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict, dict]:
    """全価格発動を保存し、同時点の二案を二段階で複写する。

    引数: frames(list[dict])は3分数量付き数値足、session(str)は場、cutoff/deadline(float)は期限、config(dict)は条件。
    返り値: tuple[dict,dict]は二純入口と全context/rawP/準備品質。先着と損益を呼ばない。
    """
    validate_config(config)
    if any(f["minutes"] != 3 or f["場"] != session for f in frames):
        raise ValueError("当場の3分足だけ")
    window, contexts, records = deque(maxlen=20), [], []
    previous_index = None
    selected = defaultdict(list)
    counts = Counter({"足数": 0, "価格20窓準備足数": 0})
    for f in frames:
        continuous = bool(f["publish"] and f["価格数値入力可"] and not f["missing"]
            and (previous_index is None and f["index"] == 0 or previous_index is not None and f["index"] == previous_index+1))
        if not continuous:
            window.clear()
        price_ready = bool(len(window) == 20 and f["publish"] and f["価格数値入力可"])
        previous = window[-1] if window else None
        values = [r["close"] for r in window]
        mean = float(J.W.np.mean(values)) if len(window) == 20 else None
        sd = float(J.W.np.std(values, ddof=0)) if len(window) == 20 else None
        lower, upper = (mean-2*sd, mean+2*sd) if mean is not None else (None, None)
        hist_change = f["macd_hist"]-previous["macd_hist"] if previous is not None and finite(f["macd_hist"]) and finite(previous["macd_hist"]) else None
        ks, direction_ready = {}, {}
        for side in (1, -1):
            k = None
            if price_ready:
                extreme = min(r["low"] for r in window) if side == 1 else max(r["high"] for r in window)
                k = next(r for r in reversed(window) if (r["low"] if side == 1 else r["high"]) == extreme)
            reasons = []
            if not price_ready:
                reasons.append("同場直前20公開価格足未準備")
            if not finite(f["atr"]) or f["atr"] <= 0:
                reasons.append("現在ATR正未準備")
            if not finite(hist_change):
                reasons.append("同場隣接公開MACDヒスト未準備")
            if not f["数量入力可"]:
                reasons.append("当足数量基準完全未準備")
            same = bool(k is not None and k["OBV公開可"] and f["OBV公開可"] and f["OBV区間ID"] == k["OBV区間ID"]
                and finite(f["OBV"]) and finite(k["OBV"]))
            if not same:
                reasons.append("当足と価格極値kの同一OBV区間未準備")
            ks[side] = k
            direction_ready[str(side)] = {"共通M準備": not reasons, "M除外理由": reasons,
                "OBV_k参照": reference(k), "OBV比較差": f["OBV"]-k["OBV"] if same else None}
        context = {**deepcopy(f), "時間足分": 3, "価格準備": price_ready,
            "前20足番号": [r["index"] for r in window], "旧BB平均": mean, "旧BB標準偏差": sd,
            "旧BB下端": lower, "旧BB上端": upper, "前3分参照": reference(previous),
            "MACDヒスト変化": hist_change, "方向別準備": direction_ready,
            "時間条件可": f["confirm"] < cutoff and deadline-f["confirm"] >= config["残り時間下限分"]*60,
            "確認遅延条件可": f["confirm"]-f["end"] <= config["確認遅延上限秒"]}
        contexts.append(context)
        counts["足数"] += 1
        counts["価格20窓準備足数"] += price_ready
        if price_ready and lower < f["close"] < upper:
            for side in (1, -1):
                k = ks[side]
                if not (f["low"] < k["low"] if side == 1 else f["high"] > k["high"]):
                    continue
                event = f"NK225_{session}_3分_極値更新帯内_{f['index']:04d}_{side}"
                scoped = {**deepcopy(context), **deepcopy(direction_ready[str(side)])}
                record = {**scoped, "入口系統": "R極値更新帯内", "役割": "反転", "side": side,
                    "方向": "買い" if side == 1 else "売り", "発動ID": event, "QイベントID": event,
                    "イベントID": event, "入口ID": "3分_R極値更新帯内", "要求時計秒": f["confirm"],
                    "要求原板行": f["confirm_line"], "足終了時計秒": f["end"], "確認遅延秒": f["confirm"]-f["end"],
                    "期限時計秒": deadline, "残り分_判断時": (deadline-f["confirm"])/60,
                    "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]),
                    "戦略判定": verdicts(scoped, side)}
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
