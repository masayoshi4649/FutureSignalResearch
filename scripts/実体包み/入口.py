"""二足実体包みと現前MACD差から、前平均の準備と局面を三段比較する。"""

from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("実体包みの新精密平均", Path(__file__).with_name("指標.py"))
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
SOURCE_FIELDS, FRAME_FIELDS, NUMERIC_FIELDS = J.SOURCE_FIELDS, J.FRAME_FIELDS, J.NUMERIC_FIELDS
finite, exact, canonical_sha, frame_projection = J.finite, J.exact, J.canonical_sha, J.frame_projection
SIGNAL_FIELDS = ("場", "イベントID", "入口ID", "役割", "side", "方向", "要求時計秒", "要求原板行",
                 "確認遅延秒", "low", "high", "atr", "bb_mean")
POLICIES = ("B0", "B1", "B2")
ROLES = {"B0": "反転", "B1": "反転", "B2": "切替"}
ACTIVE_ROLES = {"B0": ("反転",), "B1": ("反転",), "B2": ("順行", "反転")}
METADATA_FIELDS = ("元価格side", "前足番号", "B2判別種別", "B2役割")
RULES = {
    "価格": "同場隣接二足p/j。s(Cp-Op)<0、s(Cj-Oj)>0、s(Oj-Cp)<=0、s(Cj-Op)>0。元OHLCを各Fractionへ写し判定。始値等号可/終値strict/ゼロ実体不可。ヒゲ全包み/長さ閾値なし",
    "公開": "p/j公開有効/missing0/完全180秒、index隣接/endp=startj/p.key<j.key、両confirm>=end。j.end>p.confirmやj.start前のp公開を追加しない。公開key同値/後退・重複indexは拒否",
    "B0": "価格Pかつ現前中心化MACDヒスト差の実方向strict正、現ATR有限正、時間/遅延可。全反転の操作的役割で長期転換完成とはしない",
    "B1": "B0かつjを除くSMA前/SMA前々の共通準備だけ。B0と同じ反転、位置/進行値を選別しない",
    "B2": "B1かつ実side*SMA進行>0と実side*(Cj-SMA前)>0ならT順行、両strict負ならR反転。混在/等号WAIT。未準備は別記し実sideを変更しない",
    "比較": "B0反転/B1反転/B2順行反転のactive4役割群。役割だけ変わる同時点入口の経済的同値と厳密同役割共通を分ける。新Pであり旧case/control流用なし",
    "消費": "各jの二足Pを一回保存。技術/時間/保有で不採用でも後の時計へ取り直さず、確認待ち/別価格取得へ進めない",
    "競合": "候補別で同判断複数なら同方向も全見送り。全採否後だけenrichedを深複写し、pure13へ平均/将来label/分類metadataを渡さない",
    "局所": "NP/missing>0/価格不正は二足窓とSMAをclearし当足不投入。番号/endgap後のmissing0有効当足だけ新seed可。ATR/Hは共有29をstrictコピーし新銀行を作らない",
    "数値": J.RULES,
}


def body_envelop(previous: dict, current: dict, side: int) -> bool:
    """元floatを個別に精密化して二実体の包含を判定する。

    引数: previous/current(dict)は前/現足、side(int)は実方向の買1/売-1。
    返り値: boolは反対色・始値等号可・終値strictの全成立。
    """
    if side not in (-1, 1):
        raise ValueError("実方向は1又は-1だけです")
    op, cp, oj, cj = (Fraction(value) for value in (previous["open"], previous["close"], current["open"], current["close"]))
    return bool(side*(cp-op) < 0 and side*(cj-oj) > 0 and side*(oj-cp) <= 0 and side*(cj-op) > 0)


def classification(row: dict, side: int) -> tuple[str, str | None]:
    """共通準備後の位置と進行からB2の実役割だけを分類する。

    引数: row(dict)は新平均数値、side(int)は元P実方向。
    返り値: tuple[str,str|None]はT/R/WAIT/未準備と順行/反転。売買方向は変更しない。
    """
    if not row["SMA準備"]:
        return "未準備", None
    change, position = side*row["SMA進行符号"], side*row["SMA位置符号"]
    if change > 0 and position > 0:
        return "T", "順行"
    if change < 0 and position < 0:
        return "R", "反転"
    return "WAIT", None


def role_for(row: dict, policy: str) -> str | None:
    """候補ごとの実役割を当時分類から得る。

    引数: row(dict)は原P、policy(str)はB0/B1/B2。
    返り値: str|NoneはB0/B1反転又はB2当時役割。WAITを他役割へ補完しない。
    """
    if policy not in POLICIES:
        raise ValueError("固定三案だけです")
    return row["B2役割"] if policy == "B2" else "反転"


def pure_signal(row: dict, policy: str = "B0") -> dict:
    """当時の実方向・実役割を純13列へ深複写する。

    引数: row(dict)は原P又は採用enriched、policy(str)は固定三案。
    返り値: dictは執行用13列。平均/分類metadata/未来先着を含めない。
    """
    role = role_for(row, policy)
    if role not in ACTIVE_ROLES[policy] or row["side"] not in (-1, 1):
        raise ValueError("採用可能な実方向/実役割だけです")
    if row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("実方向表示の不一致")
    result = {name: deepcopy(row[name]) for name in SIGNAL_FIELDS if name not in ("イベントID", "入口ID", "役割", "bb_mean")}
    result.update(イベントID=row["発動ID"]+"_"+policy, 入口ID="3分_"+policy, 役割=role, bb_mean=None)
    return result


def verdicts(row: dict) -> dict:
    """二足価格と勢い基準へ平均の準備・値だけを段階追加する。

    引数: row(dict)は原P時点の数値/時間/分類。
    返り値: dictは全三案の採否と理由。採用後の役割/時計変更はしない。
    """
    base = list(row["M除外理由"])
    if not row["時間条件可"]:
        base.append("要求時間条件外")
    if not row["確認遅延条件可"]:
        base.append("確認遅延30秒超")
    if row["MACDヒスト変化符号"] is None or row["side"]*row["MACDヒスト変化符号"] <= 0:
        base.append("MACDヒスト実方向strict正不成立")
    result = {}
    for policy in POLICIES:
        reasons = list(base)
        if policy in ("B1", "B2") and not row["SMA準備"]:
            reasons.append("当場21過去終値SMA二平均未準備")
        if policy == "B2" and row["SMA準備"] and row["B2判別種別"] == "WAIT":
            reasons.append("平均位置進行の混在又は等号WAIT")
        result[policy] = {"採用": not reasons, "理由": reasons or ["二足実体包みと勢い複合採用"], "同時競合": False}
    return result


# ----------------------------------------
# 一足の比率や高安全体の包含を足さず、二足Pを全件残してから候補を分ける。

def generate(frames: list[dict], session: str, cutoff: float, deadline: float, config: dict) -> dict:
    """新しい二足実体Pと三候補の全判断を構築する。

    引数: frames(list[dict])はJの新27列、session(str)は場、cutoff/deadline(float)は停止/強制、
    config(dict)は残り時間下限分/確認遅延上限秒を持つ事前条件。
    返り値: dictはframes/signals/raw=decisions/metadata/quality。市場先着・運用は計算しない。
    """
    previous_input, previous, public_key = None, None, None
    records, metadata = [], {}
    counts = Counter({"局所解除足数": 0, "二足価格準備数": 0})
    for source in frames:
        row = J.numeric_projection(source)
        if row["場"] != session or row["minutes"] != 3:
            raise ValueError("当場の新3分足だけです")
        key = row["confirm"], row["confirm_line"]
        if previous_input is not None and row["index"] <= previous_input["index"]:
            raise ValueError("足番号重複又は後退")
        if row["publish"] and (row["confirm"] < row["end"] or public_key is not None and key <= public_key):
            raise ValueError("公開key同値/後退又は終了前公開")
        consecutive = previous_input is None or (row["index"] == previous_input["index"]+1 and row["start"] == previous_input["end"])
        valid = bool(row["publish"] and not row["missing"] and J.price_valid(row))
        if not valid or not consecutive:
            previous = None; counts["局所解除足数"] += 1
        if valid and previous is not None:
            counts["二足価格準備数"] += 1
            hist_change = row["macd_hist"]-previous["macd_hist"] if finite(row["macd_hist"]) and finite(previous["macd_hist"]) else None
            for side in (1, -1):
                if not body_envelop(previous, row, side):
                    continue
                event = f"NK225_{session}_3分_実体包み_{row['index']:04d}_{side}"
                branch, role = classification(row, side)
                missing = []
                if not finite(row["atr"]) or row["atr"] <= 0:
                    missing.append("現在ATR14有限正未準備")
                if hist_change is None:
                    missing.append("同場隣接公開MACDヒスト未準備")
                time_ok = row["confirm"] < cutoff and deadline-row["confirm"] >= config["残り時間下限分"]*60
                delay_ok = row["confirm"]-row["end"] <= config["確認遅延上限秒"]
                record = {**deepcopy(row), "時間足分": 3, "発動ID": event, "イベントID": event,
                    "入口ID": "3分_実体包み", "入口系統": "二足実体包み", "役割": "反転", "side": side,
                    "元価格side": side, "方向": "買い" if side == 1 else "売り", "前足番号": previous["index"],
                    "前3分参照": frame_projection(previous), "前実体": exact(Fraction(previous["close"])-Fraction(previous["open"])),
                    "現実体": exact(Fraction(row["close"])-Fraction(row["open"])),
                    "始値対前終値": exact(Fraction(row["open"])-Fraction(previous["close"])),
                    "終値対前始値": exact(Fraction(row["close"])-Fraction(previous["open"])),
                    "MACDヒスト現": row["macd_hist"], "MACDヒスト前": previous["macd_hist"],
                    "MACDヒスト変化": hist_change, "MACDヒスト変化符号": (hist_change > 0)-(hist_change < 0) if hist_change is not None else None,
                    "B2判別種別": branch, "B2役割": role, "共通M準備": not missing, "M除外理由": missing,
                    "時間条件可": time_ok, "確認遅延条件可": delay_ok,
                    "要求時計秒": row["confirm"], "要求原板行": row["confirm_line"], "足終了時計秒": row["end"],
                    "確認遅延秒": row["confirm"]-row["end"], "期限時計秒": deadline,
                    "残り分_判断時": (deadline-row["confirm"])/60, "先着評価対象": time_ok and delay_ok, "bb_mean": None}
                record["戦略判定"] = verdicts(record)
                records.append(record)
                metadata[event] = {name: deepcopy(record[name]) for name in METADATA_FIELDS}
        previous = row if valid else None
        previous_input = row
        if row["publish"]:
            public_key = key
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
                    "入口ID": "3分_"+policy, "戦略": policy, "役割": role_for(row, policy),
                    "複合判定": deepcopy(row["戦略判定"][policy])})
    quality = {"場": session, "時間足分": 3, "入力足数": len(frames), **dict(counts), "原価格発動数": len(records),
        "先着評価対象外数": sum(not row["先着評価対象"] for row in records),
        "B2分類数": dict(Counter(row["B2判別種別"] for row in records)),
        "戦略別発動数": {sid: len(rows) for sid, rows in signals.items()},
        "戦略採否理由別": {p: dict(Counter(reason for row in records for reason in row["戦略判定"][p]["理由"])) for p in POLICIES}}
    return {"場": session, "frames": {3: [J.numeric_projection(row) for row in frames]}, "signals": signals,
        "raw": records, "decisions": records, "metadata": metadata, "quality": quality}
