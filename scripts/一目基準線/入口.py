"""基準線への価格復帰を先に記録し、一目の方向追加を同じ時点で比較する。"""

from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("一目基準線の指標", Path(__file__).with_name("指標.py"))
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
OLD_CONFIG = json.loads((ROOT/"study/00026_反転のSAR確認時刻と順行持続/条件.json").read_text(encoding="utf-8"))
POLICIES = ("B0", "B1", "B2")
finite = J.finite
CORE_KEYS = ("対象", "時間足分", "出口", "逆行pt", "順行pt", "残り時間下限分", "確認遅延上限秒", "運用",
             "必須追尾", "入口支持", "費用支持", "目標確認率", "間引き必要件数")
RULES = {"下位分": 3, "上位分": 15, "転換期間": 9, "基準期間": 26, "先行B期間": 52, "描画シフト本数": 26,
    "生K期間": 14, "FastD期間": 3, "価格": "買Cprev<=Jprev<C、売Cprev>=Jprev>C。Jは同場隣接前公開3分の確定値に固定",
    "勢い": "Fraction(原OHLC float)の生K14と直近有効3生K平均の差を厳密符号化し実side一致。表示は固定26stoch_raw/stoch_k、slowD不使用",
    "雲": "最新当場公開15分uのcloseをA(u-26)/B(u-26)の現在雲と比較。end/keyとも下位asof",
    "B0": "価格復帰+Fast上下関係、全一目数値準備共通",
    "B1": "B0かつ15分closeが実方向の現在雲外strict、雲内/等号は不採用",
    "B2": "B1かつ15分転換9と基準26が実方向strict、等号は不採用",
    "共通M": "同場隣接公開現前3分2本、前J有限、現ATR正、表示FastK/D有限かつ厳密符号準備、当場最新公開15分現在雲/転換/基準有限。3分現在雲不要",
    "上位最新": "end<=現3分endかつkey<=現3分key。最新公開が不準備なら古正常へ戻らない。前場公開carryで代用しない",
    "消費": "価格復帰rawPはM/値/時間/遅延/保有と独立で一回保存。後続確認を待たず再発動へ取り直さない",
    "銀行": "同限月carry、欠枠/番号欠/不正/限月/尾部欠でclear。欠枠後有効当足は初足投入。不正は不投入。全幅末尾NP数値更新のみ、partial不投入",
    "ゼロ幅": "固定26Stochのraw/K/D平滑窓clear・高安14窓継続、一目窓は保持。Fast無効で全M待機",
    "値追加禁止": "20復帰/50/80制限・遅行線・ADX/SAR/RSI/数量を採否へ足さない",
    "役割": "全入口順行、反転は別仮説。B1/B2不採用を逆売買へ変換しない"}


def expected_config() -> dict:
    """固定26の運用数値と、新しい一目三案の定義を組み立てる。

    引数: なし。
    返り値: dictは全条件正本の期待値。既存期間・費用・支持を変えない。
    """
    return {"版": 1, **{k: deepcopy(OLD_CONFIG[k]) for k in CORE_KEYS}, "全66場既使用": True,
        "分割": {**OLD_CONFIG["分割"], "後続検査の表示名": "既使用11/4Day/Night2場"},
        "戦略": list(POLICIES), "一目基準線": deepcopy(RULES),
        "表示代表": "事前固定3分B0/B1/B2の3運用", "出口定義": {"X0": "固定26のhard125/TP250/期限と必須A5、通常native出口なし"},
        "先着対象": "時間可AND確認遅延可のみ。M/値不成立rawPも反事実先着を別計算。対象外9数値None",
        "競合": "同判断の戦略内複数採用は同方向も全見送り、全B採否確定後にcase深複写",
        "依存": "固定26のIndicators.update/気配経路/先着/entry_metrics/単一建玉X0A5/費用支持をread再用"}


def validate_config(config: dict) -> None:
    """全条件が固定の三案・継承数値と一致するか検査する。

    引数: config(dict)は試行28条件。
    返り値: None。数値又は表示規約のドリフトは例外。
    """
    if config != expected_config():
        raise ValueError("固定26の運用数値又は一目基準線三案の固定条件が不一致")


def reference(row: dict | None) -> dict | None:
    """当時の足・一目・Fastを小さい参照へ写す。

    引数: row(dict|None)は当時足。
    返り値: dict|Noneは公開出典と使用数値。未来ラベルを含まない。
    """
    if row is None:
        return None
    return deepcopy({k: row[k] for k in ("場", *J.SOURCE_FIELDS, "atr", "stoch_raw", "stoch_k", *J.EXACT_FIELDS, *J.ICHI_FIELDS,
        "雲計算元足", "一目数値入力可", "一目準備済", "一目公開可")})


def verdicts(context: dict, side: int) -> dict:
    """共通Mと時間/遅延を分離し、三案の同時点採否を返す。

    引数: context(dict)は当時数値と参照、side(int)は実方向。
    返り値: dictは全B採否。数値準備と値条件の理由を分ける。
    """
    reasons = list(context["M除外理由"])
    if not context["時間条件可"]:
        reasons.append("要求時間条件外")
    if not context["確認遅延条件可"]:
        reasons.append("確認遅延30秒超")
    upper = context["上位参照"]
    fast = context.get("Fast差厳密符号") == side
    cloud = bool(upper and upper["一目公開可"] and (
        upper["close"] > upper["cloud_upper"] if side == 1 else upper["close"] < upper["cloud_lower"]))
    aligned = bool(upper and finite(upper["ichimoku_tenkan"]) and finite(upper["ichimoku_kijun"])
        and side*(upper["ichimoku_tenkan"]-upper["ichimoku_kijun"]) > 0)
    result = {}
    for policy in POLICIES:
        local = list(reasons)
        if not fast:
            local.append("Fast実方向上下関係不成立")
        if policy in ("B1", "B2") and not cloud:
            local.append("上位現在雲外実方向不成立")
        if policy == "B2" and not aligned:
            local.append("上位転換基準実方向不成立")
        result[policy] = {"採用": not local, "理由": local or ["基準線価格復帰と複合条件採用"], "同時競合": False}
    return result


# ----------------------------------------
# 価格発動を先に固定し、全採否確定後だけ純入口を深複写する。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float,
             deadline: float, config: dict) -> tuple[dict, dict]:
    """全価格復帰を保存し、同じ時計の一目方向選別を比較する。

    引数: frames/higher(list[dict])は3/15数値足、session(str)は場、cutoff/deadline(float)は期限、config(dict)は条件。
    返り値: tuple[dict,dict]は三純入口と全context/rawP/品質。ラベルと損益を読まない。
    """
    validate_config(config)
    if any(f["minutes"] != 3 for f in frames) or any(f["minutes"] != 15 for f in higher):
        raise ValueError("3分発動と15分背景だけ")
    if any(f["場"] != session for f in (*frames, *higher)):
        raise ValueError("当場の数値足だけを公開参照へ渡します")
    published = [f for f in higher if f["publish"]]
    pointer, upper, previous = 0, None, None
    contexts, records, selected = [], [], defaultdict(list)
    counts, exclusions = Counter({"足数": 0, "共通M準備足数": 0}), Counter()
    for f in frames:
        key = f["confirm"], f["confirm_line"]
        while pointer < len(published) and (published[pointer]["confirm"], published[pointer]["confirm_line"]) <= key and published[pointer]["end"] <= f["end"]:
            upper = published[pointer]
            pointer += 1
        prior = previous if (previous is not None and previous["publish"] and previous["一目数値入力可"]
            and f["publish"] and f["一目数値入力可"] and not f["missing"] and f["index"] == previous["index"]+1) else None
        price_ready = bool(prior is not None and finite(prior["ichimoku_kijun"]) and finite(prior["close"]) and finite(f["close"]))
        reasons = []
        if not price_ready:
            reasons.append("同場隣接公開価格前基準線未準備")
        if not finite(f["atr"]) or f["atr"] <= 0:
            reasons.append("現在ATR正未準備")
        if not finite(f["stoch_raw"]) or not finite(f["stoch_k"]) or f["Fast差厳密符号"] is None:
            reasons.append("現在FastK_D未準備")
        if upper is None or not upper["一目公開可"]:
            reasons.append("当場最新公開15分一目未準備")
        context = {**deepcopy(f), "時間足分": 3, "前3分参照": reference(prior), "上位参照": reference(upper),
            "価格準備": price_ready, "共通M準備": not reasons, "M除外理由": reasons,
            "時間条件可": f["confirm"] < cutoff and deadline-f["confirm"] >= config["残り時間下限分"]*60,
            "確認遅延条件可": f["confirm"]-f["end"] <= config["確認遅延上限秒"]}
        contexts.append(context)
        exclusions.update(reasons)
        counts["足数"] += 1
        counts["共通M準備足数"] += not reasons
        if price_ready:
            level = prior["ichimoku_kijun"]
            for side in (1, -1):
                if not side*(f["close"]-level) > 0 or not side*(prior["close"]-level) <= 0:
                    continue
                event = f"NK225_{session}_3分_基準線復帰_{f['index']:04d}_{side}"
                record = {**deepcopy(context), "入口系統": "T基準線復帰", "役割": "順行", "side": side,
                    "方向": "買い" if side == 1 else "売り", "発動ID": event, "QイベントID": event, "イベントID": event,
                    "入口ID": "3分_T基準線復帰", "要求時計秒": f["confirm"], "要求原板行": f["confirm_line"],
                    "足終了時計秒": f["end"], "確認遅延秒": f["confirm"]-f["end"], "期限時計秒": deadline,
                    "残り分_判断時": (deadline-f["confirm"])/60, "固定基準線": level,
                    "先着評価対象": bool(context["時間条件可"] and context["確認遅延条件可"]), "戦略判定": verdicts(context, side)}
                records.append(record)
                for policy in POLICIES:
                    if record["戦略判定"][policy]["採用"]:
                        selected[policy, *key].append(record)
        previous = f if f["publish"] and f["一目数値入力可"] else None
    for (policy, _, _), values in selected.items():
        if len(values) > 1:
            for record in values:
                record["戦略判定"][policy].update(採用=False, 同時競合=True, 理由=["同判断複数信号見送り"])
    grouped = {"3分_"+p: [] for p in POLICIES}
    for record in records:
        for policy in POLICIES:
            if record["戦略判定"][policy]["採用"]:
                grouped["3分_"+policy].append({**deepcopy(record), "入口ID": "3分_"+policy,
                    "戦略": policy, "複合判定": deepcopy(record["戦略判定"][policy]), "イベントID": record["発動ID"]+"_"+policy})
    return grouped, {"場": session, "時間足分": 3, **dict(counts), "M除外理由別": dict(exclusions),
        "全Q発動記録": records, "複合context記録": contexts, "原価格発動数": len(records),
        "先着評価対象外数": sum(not r["先着評価対象"] for r in records),
        "戦略別発動数": {k: len(v) for k, v in grouped.items()},
        "戦略採否理由別": {p: dict(Counter(reason for r in records for reason in r["戦略判定"][p]["理由"])) for p in POLICIES}}
