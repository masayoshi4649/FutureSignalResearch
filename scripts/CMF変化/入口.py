"""固定42の最初再テストを保ち、CMFの現前準備と変化方向を分離する。"""

from collections import Counter, deque
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("CMF変化の固定42入口", ROOT/"scripts/再テスト量方向/入口.py")
OLD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OLD
SPEC.loader.exec_module(OLD)
SOURCE_FIELDS = OLD.SOURCE_FIELDS
FRAME_FIELDS = OLD.FRAME_FIELDS
SIGNAL_FIELDS = OLD.SIGNAL_FIELDS
POLICIES = ("D0", "D1", "D2")
ROLES = {policy: "切替" for policy in POLICIES}
finite, exact, canonical_sha, frame_projection = OLD.finite, OLD.exact, OLD.canonical_sha, OLD.frame_projection
RULES = {
    "対照": "D0は固定42A0全純13列を識別子だけ変更して保持。価格b/j/T/R/WAIT・時計・勢い・現jATRと既競合を変更しない",
    "D1": "D0かつ当場隣接現前CMF21数値準備。和集合22連続公開完全足と全22q完全有限非負・各幅正・現前各総q正",
    "D2": "D1かつ実side*(CMF現-CMF前)>0strict。差0不採用、現水準と当足寄与をANDしない",
    "精密": "元floatH/L/C/qを各Fractionへ写す。現前CMFの直接差とN現Q前-N前Q現の符号を別検算し、表示float/epsilonを採否に使わない",
    "分解": "I=q現*(m現-F前)/Q現、O=-q落*(m落-F前)/Q現。I+O=ΔFを精密照合。共通20足総量0でも現前各総q正なら有効",
    "局所": "当場missing0/公開有効完全180秒/index-end-key連続。数量不完全/零幅はCMF窓だけを切り、旧価格監視へ伝えず古正常へfallbackしない",
    "診断": "現水準・I/O・入足/落足CLVとqは保存診断のみ。量比VRと異なり最古足を含む全22qが必要。新しい待機hや閾値選別を加えない",
    "執行": "同じj要求+1価格秒/TTL30、全三XF。現在正常返済BBOの実side*(mark-entry)*10-122円>0strict起動、現j入口ATR固定D/名目entry床/非緩和を保持",
    "集合": "全案集合切替・実T順行/R反転。旧競合後A0を部分集合化し救済や後足再発動をせず、実pending/建玉抑止は別に扱う",
}


def fraction(value: dict) -> Fraction | None:
    """精密値辞書から表示値を使わず分数を復元する。

    引数: value(dict)は値/分子/分母/有効の精密値。
    返り値: Fraction|Noneは精密値又は未準備。
    """
    return Fraction(value["分子"], value["分母"]) if value["有効"] else None


def movement_window(rows: list[dict]) -> dict:
    """最大22連続足から現前CMFと窓入替えの恒等分解を計算する。

    引数: rows(list[dict])は価格/量/幅を検査済みの同場足。
    返り値: dictは現前窓・精密比/差/寄与・準備理由。中間20足の比を作らない。
    """
    current_rows, previous_rows = rows[-21:], rows[:-1] if rows else []
    current, previous = OLD.cmf_window(current_rows), OLD.cmf_window(previous_rows)
    ready = len(rows) == 22 and current["CMF準備"] and previous["CMF準備"]
    reasons = []
    if len(rows) != 22: reasons.append("同場CMF現前22連続足未準備")
    if not current["CMF準備"]: reasons.append("現在CMF21数値未準備")
    if not previous["CMF準備"]: reasons.append("前CMF21数値未準備")
    delta = cross = incoming = outgoing = None
    incoming_source = outgoing_source = None
    if ready:
        fcur, fprev = fraction(current["CMF21"]), fraction(previous["CMF21"])
        ncur, nprev = fraction(current["加重CLV合計"]), fraction(previous["加重CLV合計"])
        qcur, qprev = fraction(current["観測量合計"]), fraction(previous["観測量合計"])
        delta, cross = fcur-fprev, ncur*qprev-nprev*qcur
        first, last = rows[0], rows[-1]
        mnew = (2*Fraction(last["close"])-Fraction(last["high"])-Fraction(last["low"]))/(Fraction(last["high"])-Fraction(last["low"]))
        mold = (2*Fraction(first["close"])-Fraction(first["high"])-Fraction(first["low"]))/(Fraction(first["high"])-Fraction(first["low"]))
        qnew, qold = Fraction(last["数量参照"]["観測差分量"]), Fraction(first["数量参照"]["観測差分量"])
        incoming, outgoing = qnew*(mnew-fprev)/qcur, -qold*(mold-fprev)/qcur
        if delta != cross/(qcur*qprev) or delta != incoming+outgoing:
            raise ArithmeticError("CMF直接差・交差積・窓入替え分解が不一致")
        incoming_source = {"足出典": {key: deepcopy(last[key]) for key in ("場", *SOURCE_FIELDS)}, "CLV": exact(mnew), "観測q": exact(qnew)}
        outgoing_source = {"足出典": {key: deepcopy(first[key]) for key in ("場", *SOURCE_FIELDS)}, "CLV": exact(mold), "観測q": exact(qold)}
    return {"現窓足番号": current["CMF窓足番号"], "前窓足番号": previous["CMF窓足番号"],
        "CMF現前準備": bool(ready), "現前準備除外理由": reasons,
        "CMF現": current["CMF21"], "CMF前": previous["CMF21"], "CMF差": exact(delta),
        "CMF差符号": (delta > 0)-(delta < 0) if ready else None,
        "現加重CLV合計": current["加重CLV合計"], "前加重CLV合計": previous["加重CLV合計"],
        "現観測量合計": current["観測量合計"], "前観測量合計": previous["観測量合計"],
        "CMF差交差積": exact(cross), "当足寄与I": exact(incoming), "窓脱落寄与O": exact(outgoing),
        "分解一致": True if ready else None, "入足参照": incoming_source, "落足参照": outgoing_source,
        "現単位量CLV平均": current["単位量CLV平均"], "前単位量CLV平均": previous["単位量CLV平均"],
        "現窓全量正同値": current["CMF全量正同値"], "前窓全量正同値": previous["CMF全量正同値"]}


def volume_panels(frames: list[dict], session: str) -> list[dict]:
    """旧29保存価格/Qから全足の現前CMFを作り、欠測を圧縮しない。

    引数: frames(list[dict])は当場旧29の全3分足、session(str)は場。
    返り値: list[dict]は数量比だけの全足列。旧b/j監視・数値銀行は変更しない。
    """
    window, previous, output = deque(maxlen=22), None, []
    for source in frames:
        frame = frame_projection(source)
        if frame["場"] != session or frame["minutes"] != 3:
            raise ValueError("当場の保存3分足だけです")
        if previous is not None and frame["index"] <= previous["index"]:
            raise ValueError("3分足番号はstrict昇順だけです")
        reasons = OLD.price_reasons(frame)
        if not OLD.adjacent(previous, frame): reasons.append("価格番号区間公開順非連続")
        current_bad = OLD.price_reasons(frame)
        qref = frame["数量参照"]
        q = qref.get("観測差分量") if isinstance(qref, dict) else None
        quantity_ok = isinstance(qref, dict) and qref.get("数量基準完全") is True and finite(q) and q >= 0
        width_ok = OLD.NUMERIC.VALID(frame) and frame["high"] > frame["low"]
        if not quantity_ok: reasons.append("数量基準完全非負未準備")
        if not width_ok: reasons.append("CLV幅正未準備")
        if reasons: window.clear()
        if not current_bad and quantity_ok and width_ok: window.append(frame)
        output.append({"場": session, "index": frame["index"],
            "足出典": {key: deepcopy(frame[key]) for key in ("場", *SOURCE_FIELDS)},
            "CMF窓解除理由": reasons, **movement_window(list(window))})
        previous = frame
    return output


def pure_signal(row: dict, policy: str = "D0") -> dict:
    """固定42A0純13列を保持し、識別子だけを三案へ変換する。

    引数: row(dict)は固定42のA0純入口、policy(str)はD0/D1/D2。
    返り値: dictは同じj時計/価格/ATR/実役割の純13列。数量診断や未来labelを含めない。
    """
    if policy not in POLICIES or row["入口ID"] != "3分_A0" or not row["イベントID"].endswith("_A0"):
        raise ValueError("固定42A0を三案へ写すだけです")
    if row["side"] not in (-1, 1) or row["役割"] not in ("順行", "反転") or row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("固定42の実方向/役割が不正です")
    result = {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}
    result.update(イベントID=row["イベントID"][:-3]+"_"+policy, 入口ID="3分_"+policy)
    return result


# ----------------------------------------
# 既競合後A0の同時点集合を保持し、数値準備と差の符号だけを段階追加する。

def select(block: dict, session: str | None = None) -> dict:
    """固定42全jを参照し、旧採用対照と現前CMF三採否を作る。

    引数: block(dict)は場/signals[3分_A0純13]/frames[3]/旧j判定、session(str|None)は場。
    返り値: dictは全jのdecisions/三signals/全panel/quality/親metadataを追加した場材料。
    """
    original, contexts, frames = block["signals"]["3分_A0"], block["旧j判定"], block["frames"][3]
    actual_session = session or block.get("場") or (original[0]["場"] if original else None)
    if actual_session is None: raise ValueError("空のA0場にも場を明示してください")
    panels = volume_panels(frames, actual_session)
    by_index = {row["index"]: row for row in panels}
    frame_by_index = {row["index"]: row for row in frames}
    by_event = {row["発動ID"]: row for row in contexts}
    if len(by_event) != len(contexts): raise ValueError("旧j発動IDは一意だけです")
    originals = {row["イベントID"]: row for row in original}
    keys = [(row["要求時計秒"], row["要求原板行"]) for row in original]
    if len(originals) != len(original) or keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ValueError("固定42A0の既競合後公開順だけです")
    expected = {row["発動ID"]+"_A0": OLD.pure_signal(row, "A0") for row in contexts if row["戦略判定"]["A0"]["採用"]}
    if originals != expected: raise ValueError("固定42全j採用集合と旧A0純13列が不一致")
    grouped, decisions, metadata = {"3分_"+p: [] for p in POLICIES}, [], {}
    for row in contexts:
        if row["場"] != actual_session: raise ValueError("旧j判定の場が不一致")
        source, panel = frame_by_index[row["index"]], by_index[row["index"]]
        if any(row[key] != source[key] for key in SOURCE_FIELDS):
            raise ValueError("旧j判定と保存29の足出典が不一致")
        if (row["要求時計秒"], row["要求原板行"]) != (source["confirm"], source["confirm_line"]):
            raise ValueError("旧j要求keyと公開出典が不一致")
        old = bool(row["戦略判定"]["A0"]["採用"])
        ready, side = panel["CMF現前準備"], row["side"]
        improved = ready and side in (-1, 1) and side*panel["CMF差符号"] > 0
        verdicts = {"D0": {"採用": old, "理由": list(row["戦略判定"]["A0"]["理由"]),
                "同時競合": row["戦略判定"]["A0"].get("同時競合", False)},
            "D1": {"採用": old and ready, "理由": ["旧A0採用・現前CMF21準備"] if old and ready else
                ["旧A0不採用"] if not old else list(panel["現前準備除外理由"]), "同時競合": False},
            "D2": {"採用": old and bool(improved), "理由": ["旧A0採用・CMF差実方向strict正"] if old and improved else
                ["旧A0不採用"] if not old else list(panel["現前準備除外理由"]) if not ready else ["CMF差実方向strict正不成立"], "同時競合": False}}
        event = row["発動ID"]
        metadata[event] = {"元登録ID": row["登録ID"], "元価格side": row["元価格side"],
            "元登録時計秒": row["登録参照"]["登録足"]["confirm"],
            "元登録原板行": row["登録参照"]["登録足"]["confirm_line"], "判別種別": row["構造区分"]}
        decisions.append({"場": actual_session, "発動ID": event, "元42j発動ID": event,
            "元42A0イベントID": event+"_A0" if old else None, **deepcopy(metadata[event]),
            "index": row["index"], "足終了時計秒": row["end"], "要求時計秒": row["要求時計秒"],
            "要求原板行": row["要求原板行"], "side": side, "役割": row["役割"],
            "旧A0採用": old, "CMF現前参照": deepcopy(panel), "戦略判定": verdicts})
    selected = {row["元42A0イベントID"]: row for row in decisions if row["旧A0採用"]}
    for row in original:
        if row["場"] != actual_session: raise ValueError("旧A0純入口の場が不一致")
        for policy in POLICIES:
            if selected[row["イベントID"]]["戦略判定"][policy]["採用"]:
                grouped["3分_"+policy].append(pure_signal(row, policy))
    quality = {"場": actual_session, "時間足分": 3, "旧j判定数": len(contexts), "旧A0純登録数": len(original),
        "旧A0純登録同値": True, "CMF足数": len(panels), "現前CMF準備足数": sum(p["CMF現前準備"] for p in panels),
        "戦略別発動数": {key: len(values) for key, values in grouped.items()},
        "戦略採否理由別": {p: dict(Counter(reason for row in decisions for reason in row["戦略判定"][p]["理由"])) for p in POLICIES}}
    block.update(signals=grouped, decisions=decisions, volume_panels=panels, quality=quality, metadata=metadata)
    return block
