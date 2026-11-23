"""固定NK再テストの同時点で、TOPIXの公開準備と方向・勢いを分離する。"""

from collections import Counter, deque
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("TOPIX補助の限定数値", Path(__file__).with_name("指標.py"))
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
SPEC_OLD = importlib.util.spec_from_file_location("TOPIX補助の固定42入口", ROOT/"scripts/再テスト量方向/入口.py")
OLD = importlib.util.module_from_spec(SPEC_OLD)
sys.modules[SPEC_OLD.name] = OLD
SPEC_OLD.loader.exec_module(OLD)
SOURCE_FIELDS, AUX_FIELDS, SIGNAL_FIELDS = J.SOURCE_FIELDS, J.AUX_FIELDS, OLD.SIGNAL_FIELDS
POLICIES = ("X0", "X1", "X2")
ROLES = {policy: "切替" for policy in POLICIES}
finite, exact, canonical_sha, aux_projection = OLD.finite, OLD.exact, J.canonical_sha, J.aux_projection
frame_projection = OLD.frame_projection
RULES = {
    "対照": "X0は固定43D0(42A0)全245純13を識別子だけ変更して保持。NKb/j/T/R/MACD/時計/現jATR・既競合を変更しない",
    "X1": "X0かつ限月年月一致、TOPIX同終了3分のstrict価格clock事前公開、同場連続OLS20と当場隣接現前ヒスト数値準備。傾き0/ヒスト差0は準備可",
    "X2": "X1かつ実side*TOPIXのOLS20傾き>0、かつ実side*TOPIXヒスト一足差>0strict。0不成立、単独手法効果ではなく複合条件の差",
    "時計": "TOPIX.confirm<NKj要求秒strictかつ同end。商品間の原行は比較しない。不可は参照Noneと同一理由、同秒/後公開/不在をlive理由へ分けず、古足fallback/後足待機なし",
    "回帰": "当足含む同場連続公開有効20終値、x0..19の切片付きOLS精密Fraction傾き。R2/正相関/NT倍率は計算gateにしない",
    "勢い": "TOPIX自身の固定29中心化MACD12/26/9。原点はreset時の初有効C。数値は同TPI契約carry、現前公開/OLS窓は毎場reset",
    "局所": "公開有効OHLC/価格数値入力可/missing0/完全180秒/confirm>=end/index-end-key連続。NP/不正/欠枠は公開窓解除、最新不準備に古正常fallbackなし",
    "限定": "価格clockstrict先行でも実受信先行は証明しない。関連二指数とTPI内OLS/MACDは独立票でなく、価格変化相関係数や騰落数を測らない。TPI数量/BBO正常/ATRは採否不使用",
    "執行": "NKだけの三XF/切替集合実T順行R反転。同じj要求+1秒TTL30/122円strict現在利益起動/現NKjATR固定D/名目entry床を保持、補助不一致から自動反転しない",
}
NO_VISIBLE = "TOPIX同終了strict事前公開参照なし"


def price_reasons(frame: dict) -> list[str]:
    """TOPIXの価格公開足を数量・気配状態から独立に検査する。

    引数: frame(dict)は限定TOPIX3分足。
    返り値: list[str]は公開/幅/価格/欠枠の不準備理由。
    """
    reasons = []
    if not frame["publish"]: reasons.append("TOPIX非公開足")
    if not frame["価格数値入力可"] or not J.NUMERIC.VALID(frame): reasons.append("TOPIX価格数値入力不正")
    if frame["missing"] != 0: reasons.append("TOPIX欠枠あり")
    if frame["minutes"] != 3 or frame["end"]-frame["start"] != 180: reasons.append("TOPIX完全180秒不成立")
    if frame["confirm"] < frame["end"]: reasons.append("TOPIX終了前公開")
    return reasons


def adjacent(previous: dict | None, current: dict) -> bool:
    """同じ商品の足区間と公開順の隣接を検査する。

    引数: previous(dict|None)は前足、current(dict)は当足。
    返り値: boolは前足あり・番号/end/keyの連続が成立すること。
    """
    return previous is not None and previous["index"]+1 == current["index"] and previous["end"] == current["start"] and (
        previous["confirm"], previous["confirm_line"]) <= (current["confirm"], current["confirm_line"])


def slope20(values: list[float]) -> dict:
    """20終値の切片付きOLS傾きだけを精密に計算する。

    引数: values(list[float])は古い順の終値。
    返り値: dictは準備/傾き精密値/符号。定値20点の傾き0も準備可でR2を要求しない。
    """
    ready = len(values) == 20 and all(finite(value) for value in values)
    slope = None
    if ready:
        ys = [Fraction(value) for value in values]
        slope = (20*sum(index*value for index, value in enumerate(ys))-190*sum(ys))/13300
    return {"準備": ready, "傾き": exact(slope), "符号": (slope > 0)-(slope < 0) if ready else None}


def auxiliary_panels(frames: list[dict], session: str) -> list[dict]:
    """TOPIXの場内OLS窓と現前公開ヒストを全足で分けて保存する。

    引数: frames(list[dict])は当場TOPIX限定数値、session(str)は場。
    返り値: list[dict]は全補助panel。未可視足はselectの出典へ渡さない。
    """
    window, previous, last_public_key, output = deque(maxlen=20), None, None, []
    for source in frames:
        frame = aux_projection(source)
        if frame["場"] != session: raise ValueError("当場TOPIXだけです")
        if previous is not None and frame["index"] <= previous["index"]: raise ValueError("TOPIX足番号はstrict昇順だけです")
        key = (frame["confirm"], frame["confirm_line"])
        if frame["publish"]:
            if last_public_key is not None and key < last_public_key: raise ValueError("TOPIX公開keyが後退")
            last_public_key = key
        reasons, current_bad = price_reasons(frame), price_reasons(frame)
        joined = adjacent(previous, frame)
        if previous is not None and not joined: reasons.append("TOPIX番号区間公開順非連続")
        if reasons: window.clear()
        if not current_bad: window.append(frame)
        ols = slope20([row["close"] for row in window])
        pair = not current_bad and joined and not price_reasons(previous)
        prior = previous if pair else None
        change = frame["macd_hist"]-prior["macd_hist"] if prior is not None and finite(frame["macd_hist"]) and finite(prior["macd_hist"]) else None
        ready_reasons = list(current_bad)
        if not ols["準備"]: ready_reasons.append("TOPIX同場OLS20未準備")
        if not pair: ready_reasons.append("TOPIX当場隣接公開現前未準備")
        if not finite(change): ready_reasons.append("TOPIX現前MACDヒスト有限未準備")
        latest = max(((row["confirm"], row["confirm_line"]) for row in window), default=None)
        output.append({"場": session, "index": frame["index"], "足出典": frame,
            "前足出典": deepcopy(prior), "OLS20窓足番号": [row["index"] for row in window],
            "OLS20傾き": ols["傾き"], "OLS20傾き符号": ols["符号"],
            "MACDヒスト現": frame["macd_hist"], "MACDヒスト前": prior["macd_hist"] if prior else None,
            "MACDヒスト変化": change, "補助数値準備": not ready_reasons,
            "補助準備除外理由": ready_reasons, "窓解除理由": reasons,
            "窓最遅公開key": list(latest) if latest is not None else None})
        previous = frame
    return output


def pure_signal(row: dict, policy: str = "X0") -> dict:
    """旧A0純13列を保ち、候補識別子だけを変更する。

    引数: row(dict)は43D0からA0へ正規化した純入口、policy(str)はX0/X1/X2。
    返り値: dictはNKのj価格/時計/ATR/実役割を保持した純13列。
    """
    if policy not in POLICIES or row["入口ID"] != "3分_A0" or not row["イベントID"].endswith("_A0"):
        raise ValueError("固定A0純入口を三案へ写すだけです")
    if row["役割"] not in ("順行", "反転") or row["side"] not in (-1, 1) or row["方向"] != ("買い" if row["side"] == 1 else "売り"):
        raise ValueError("固定NKの役割/実方向が不正")
    value = {key: deepcopy(row.get(key)) if key == "bb_mean" else deepcopy(row[key]) for key in SIGNAL_FIELDS}
    value.update(入口ID="3分_"+policy, イベントID=row["イベントID"][:-3]+"_"+policy)
    return value


def select(block: dict, session: str | None = None) -> dict:
    """同終了TOPIXのstrict事前公開から準備・複合方向を追加する。

    引数: block(dict)はA0純/旧全j/NK3分/補助足/商品照合、session(str|None)は場。
    返り値: dictは三純集合/全j判定/全補助panel/品質/旧A0keyの親metadata。
    """
    original, contexts, nk_frames = block["signals"]["3分_A0"], block["旧j判定"], block["frames"][3]
    actual_session = session or block.get("場") or (original[0]["場"] if original else None)
    if actual_session is None: raise ValueError("空場にも場名を明示してください")
    if type(block["商品照合"]) is not bool: raise ValueError("監査済み限月年月照合は真偽値だけです")
    panels = auxiliary_panels(block["補助足"], actual_session)
    nk_by_index = {row["index"]: row for row in nk_frames}
    if len(nk_by_index) != len(nk_frames): raise ValueError("NK足番号は一意だけです")
    originals = {row["イベントID"]: row for row in original}
    expected = {row["発動ID"]+"_A0": OLD.pure_signal(row, "A0") for row in contexts if row["戦略判定"]["A0"]["採用"]}
    keys = [(row["要求時計秒"], row["要求原板行"]) for row in original]
    if originals != expected or len(originals) != len(original) or keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ValueError("固定A0既競合後全純13集合に差")
    if len({row["発動ID"] for row in contexts}) != len(contexts): raise ValueError("旧j発動IDが重複")
    grouped, decisions, metadata = {"3分_"+p: [] for p in POLICIES}, [], {}
    for row in contexts:
        source = nk_by_index[row["index"]]
        if row["場"] != actual_session or source["場"] != actual_session or any(row[k] != source[k] for k in SOURCE_FIELDS):
            raise ValueError("旧NKjと保存3分出典に差")
        if (row["要求時計秒"], row["要求原板行"]) != (source["confirm"], source["confirm_line"]):
            raise ValueError("旧NKj要求keyと公開出典に差")
        visible = [p for p in panels if p["足出典"]["publish"] and p["足出典"]["confirm"] < row["要求時計秒"]
            and p["足出典"]["end"] == source["end"]]
        if len(visible) > 1: raise ValueError("同終了TOPIX公開足が複数")
        upper = visible[0] if visible else None
        ready_reasons = []
        if not block["商品照合"]: ready_reasons.append("NKとTOPIXの限月年月不一致")
        if upper is None: ready_reasons.append(NO_VISIBLE)
        else:
            if upper["窓最遅公開key"] is not None and upper["窓最遅公開key"][0] >= row["要求時計秒"]:
                raise ValueError("TOPIX回帰窓に未可視足が混入")
            if upper["前足出典"] is not None and upper["前足出典"]["confirm"] >= row["要求時計秒"]:
                raise ValueError("TOPIX前足に未可視値が混入")
            ready_reasons.extend(upper["補助準備除外理由"])
        ready, side = not ready_reasons, row["side"]
        direction = ready and side in (-1, 1) and side*upper["OLS20傾き符号"] > 0 and side*upper["MACDヒスト変化"] > 0
        old = bool(row["戦略判定"]["A0"]["採用"])
        verdicts = {"X0": {"採用": old, "理由": list(row["戦略判定"]["A0"]["理由"]), "同時競合": row["戦略判定"]["A0"].get("同時競合", False)},
            "X1": {"採用": old and ready, "理由": ["旧A0採用・TOPIX共通準備"] if old and ready else ["旧A0不採用"] if not old else list(ready_reasons), "同時競合": False},
            "X2": {"採用": old and bool(direction), "理由": ["旧A0採用・TOPIX方向勢い一致"] if old and direction else ["旧A0不採用"] if not old else list(ready_reasons) if not ready else ["TOPIX方向勢い実方向strict正不成立"], "同時競合": False}}
        event, old_id = row["発動ID"], row["発動ID"]+"_A0"
        if old:
            metadata[old_id] = {"元登録ID": row["登録ID"], "元価格side": row["元価格side"],
                "元登録時計秒": row["登録参照"]["登録足"]["confirm"], "元登録原板行": row["登録参照"]["登録足"]["confirm_line"], "判別種別": row["構造区分"]}
        decisions.append({"場": actual_session, "発動ID": event, "元42j発動ID": event,
            "元42A0イベントID": old_id if old else None, "元登録ID": row["登録ID"], "元価格side": row["元価格side"],
            "元登録時計秒": row["登録参照"]["登録足"]["confirm"], "元登録原板行": row["登録参照"]["登録足"]["confirm_line"],
            "判別種別": row["構造区分"], "index": row["index"], "足終了時計秒": row["end"],
            "要求時計秒": row["要求時計秒"], "要求原板行": row["要求原板行"], "side": side, "役割": row["役割"],
            "旧A0採用": old, "商品照合": block["商品照合"], "補助参照": deepcopy(upper),
            "補助準備": ready, "準備除外理由": ready_reasons, "戦略判定": verdicts})
    by_event = {row["元42A0イベントID"]: row for row in decisions if row["旧A0採用"]}
    for row in original:
        if row["場"] != actual_session: raise ValueError("旧A0純入口の場に差")
        for policy in POLICIES:
            if by_event[row["イベントID"]]["戦略判定"][policy]["採用"]:
                grouped["3分_"+policy].append(pure_signal(row, policy))
    quality = {"場": actual_session, "時間足分": 3, "旧j判定数": len(contexts), "旧A0純登録数": len(original), "旧A0純登録同値": True,
        "TOPIX足数": len(block["補助足"]), "補助判定足数": len(panels), "TOPIX補助数値準備足数": sum(p["補助数値準備"] for p in panels),
        "同終了事前公開参照数": sum(d["補助参照"] is not None for d in decisions),
        "戦略別発動数": {sid: len(values) for sid, values in grouped.items()},
        "戦略採否理由別": {p: dict(Counter(reason for d in decisions for reason in d["戦略判定"][p]["理由"])) for p in POLICIES}}
    block.update(signals=grouped, decisions=decisions, aux_panels=panels, quality=quality, metadata=metadata)
    return block
