"""76の公開局所波を、過去の採否・教師・損益を参照せず再構成する。"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "scripts/事前帯と現在の反応/入力.py"
SHARED_SHA256 = "2ef17219cb82b9ca45e106ba9abf84837c1649e73c60519030a2bdd33aba6f2a"
if hashlib.sha256(SHARED_PATH.read_bytes()).hexdigest() != SHARED_SHA256:
    raise ValueError("固定75入力のSHA不一致")
_spec = importlib.util.spec_from_file_location("固定75局所波用純補助", SHARED_PATH)
SHARED = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SHARED)
SOURCE_FIELDS = SHARED.SOURCE_FIELDS
SLOT_FIELDS = SHARED.SLOT_FIELDS
VALUE_FIELDS = SHARED.VALUE_FIELDS
POLICIES = ("L0", "L1")
SIDES = (1, -1)
finite, exact, canonical = SHARED.finite, SHARED.exact, SHARED.canonical
RULES = {
    "入力": "旧73の64列/現ATR・D/全当場SOURCE13/出生時3分ATR/55当時quote。旧予測・教師・結果は不使用",
    "出生": "隣接a,m,bの終値差2本が同方向strict正かつs*(Cb-Ca)>=ATR_b。originはa反対端",
    "親": "当場一件。最初b/r/f/k固定。親存続中新bなし。終端/reset足と次a/m/bを兼用しない",
    "準備": "価格又は出生ATR未知で親/bufferをclear、新しい完全隣接3足で再準備。旧readyFalseは復活しない",
    "T": "最初逆終値r後、別足の最初r実方向端strict終値突破。k前はorigin維持、r反対端だけの喪失では取消しない",
    "T前提": "k後は買max(origin,r.low)/売min(origin,r.high)のstrict側。等号取消、同r復活なし",
    "R": "最初origin終値喪失fを共有。別足1..3本の最初f実R端strict終値突破。確認前origin再獲得優先終了",
    "R前提": "k後は買max(origin,f.low)/売min(origin,f.high)のstrict側。確認端への戻りだけでは取消しない",
    "期限": "親b.end+1620、未確認Rはmin(f.end+540,親期限)。end/confirmの超過を遷移前に処理。判断time超過も終了",
    "鮮度": "独立900秒gateなし。k公開key<=実判断/end<=予定、同k反復と経過を別記",
    "技法": "全候補F02>=0/F03>0/F07>0/F01非零/rawDI非同値。TはF01>0/F51=F52=1/F47>=.20/F48>=0",
    "反転": "RでF01>0は順行、F01<0はF52=1/F48<0/F15>0。形成T/RとDI役割を分離",
    "現在価格": "正常BBO/正Last、Lastと実方向E*がともにpremiseのstrict側。確認価格へ約定を戻さない",
    "場所": "前帯はE*別の内外/HLM距離/前方線の診断だけ。未知で局所readyを落とさず距離・中央250gateなし",
    "政策": "L0もR全履歴を再構成し採用はTのみ、L1はT/R。純包含であり実参加包含は保証しない",
    "tip": "a..b方向高安の先頭極値とr前までの極値を別保存。足内順序を推測せず採否には使わない"}


# ----------------------------------------
def digest(value: object, invalid: bool = False) -> str:
    """固定JSONのSHAを作る。

    引数: value(object)は出典配列等、invalid(bool)は既知不良価格を指紋に含めるか。
    返り値: strはSHA256。
    """
    return hashlib.sha256(canonical(value, invalid).encode("utf-8")).hexdigest()


def event_ref(row: dict | None, slot: dict | None = None) -> dict:
    """公開足又は判断timerの終了出典を作る。

    引数: row(dict|None)は公開足、slot(dict|None)は判断時計。
    返り値: dictは価格を含まない時点参照。
    """
    if row is not None:
        return {"index": row["index"], "key": [row["confirm"], row["confirm_line"]], "clock": "公開足", "end": row["end"]}
    return {"index": None, "key": [slot["time"], slot["line"]], "clock": "判断時刻", "end": None}


def bind_atr(prefix: list[dict], rows: list[dict]) -> list[dict]:
    """可視価格足と出生ATR行を全文指紋・時計で一対一結合する。

    引数: prefix(list[dict])はSOURCE13、rows(list[dict])は出生ATR.visible_rowsの返り値。
    返り値: list[dict]は価格順の深い複写。欠落・余剰・型差・偽readyは停止する。
    """
    if not isinstance(rows, list) or len(rows) != len(prefix):
        raise ValueError("可視価格と出生ATR行の件数差")
    result = []
    fields = SOURCE_FIELDS[:9]
    for source, atr in zip(prefix, rows):
        if (not isinstance(atr, dict) or any(type(atr.get(k)) is not type(source[k]) or atr[k] != source[k] for k in fields)
                or atr.get("source_sha256") != digest(source, True)):
            raise ValueError("出生ATRのSOURCE指紋・時計・状態差")
        if (type(atr.get("valid")) is not bool or type(atr.get("ready")) is not bool
                or type(atr.get("numeric_count")) is not int or atr["numeric_count"] < 0
                or not isinstance(atr.get("reason"), str) or not isinstance(atr.get("reset_reasons"), list)
                or any(not isinstance(r, str) for r in atr["reset_reasons"])
                or atr.get("atr") is not None and not finite(atr["atr"])):
            raise ValueError("出生ATRの値・準備schema不正")
        expected = atr["valid"] and finite(atr["atr"]) and atr["atr"] > 0
        if atr["ready"] != expected or not atr["valid"] and atr["atr"] is not None:
            raise ValueError("出生ATR readyと値の矛盾")
        result.append(deepcopy(atr))
    return result


def extreme(rows: list[dict], side: int) -> dict:
    """方向高安の最初の最大を出典付きで求める。

    引数: rows(list[dict])は完全足、side(int)は元親方向。
    返り値: dictはprice/source。ヒゲ発生の足内順序を推定しない。
    """
    field = "high" if side == 1 else "low"
    winner = max(rows, key=lambda row: side * exact(row[field]))
    return {"price": winner[field], "source": deepcopy(winner)}


# ----------------------------------------
class Machine:
    """一件の原因を共有したT/Rと再出生bufferを公開順で保持する。"""

    def __init__(self, session: str) -> None:
        """空の当場状態を作る。

        引数: session(str)は形成場。
        返り値: None。
        """
        self.session, self.parent = session, None
        self.parents, self.formations, self.buffer, self.resets, self.rejected_births = [], [], [], [], []
        self.prepared, self.previous = False, None

    def trace(self, parent: dict, ref: dict, action: str) -> None:
        """処理後の段階と最小出典を履歴へ追加する。

        引数: parent/ref(dict)は親/時点、action(str)は動作。
        返り値: None。
        """
        parent["trace"].append({**deepcopy(ref), "action": action, "status": parent["status"], "active": parent["active"]})

    def finish_formation(self, formation: dict | None, ref: dict, reason: str, status: str = "取消") -> None:
        """形成の最初の終了を固定する。

        引数: formation(dict|None)はT/R、ref(dict)は時点、reason/status(str)は理由/状態。
        返り値: None。同じ形成を復活させない。
        """
        if formation is not None and formation["cancel"] is None:
            formation.update(active=False, status=status, cancel={**deepcopy(ref), "reason": reason})

    def terminate(self, ref: dict, reason: str, status: str = "期限終了") -> None:
        """親を終了し、終端足を再出生へ流用しない。

        引数: ref(dict)は時点、reason/status(str)は理由/状態。
        返り値: None。正常終端では入力の既知性preparedを保つ。
        """
        parent = self.parent
        if parent is not None:
            self.finish_formation(parent["T"], ref, reason, status)
            self.finish_formation(parent["R"], ref, reason, status)
            parent.update(active=False, status=status, terminal={**deepcopy(ref), "reason": reason})
            self.trace(parent, ref, reason)
        self.parent, self.buffer = None, []

    def reset(self, row: dict, reason: str) -> None:
        """価格・ATR未知又は不連続を追加準備待ちへ戻す。

        引数: row(dict)は観測足、reason(str)は不良理由。
        返り値: None。reset足は次aにも使わない。
        """
        ref = event_ref(row)
        self.terminate(ref, reason, "品質reset")
        self.resets.append({**ref, "reason": reason})
        self.prepared, self.previous = False, None

    def formation(self, parent: dict, kind: str, row: dict | None = None) -> dict:
        """同じ親に属するT又はRの一回限りの形成を作る。

        引数: parent(dict)は親、kind(str)はT/R、row(dict|None)はRのf。
        返り値: dictは全形成一覧と親へ同じ参照で登録した形成。
        """
        result = {"id": parent["id"] + "|" + kind, "parent_id": parent["id"], "kind": kind,
            "side": parent["direction"] if kind == "T" else -parent["direction"], "b": deepcopy(parent["b"]),
            "r": None, "f": deepcopy(row), "k": None, "trigger_line": None, "premise_line": None,
            "deadline": parent["deadline"] if kind == "T" else min(row["end"] + 540, parent["deadline"]),
            "active": False, "status": "最初r待ち" if kind == "T" else "反対確認待ち", "cancel": None}
        self.formations.append(result)
        parent[kind] = result
        parent[kind + "_id"] = result["id"]
        return result

    def born(self, atr: dict) -> None:
        """直近完全3足から最初の同方向進行を出生させる。

        引数: atr(dict)はbへ完全結合した出生ATR。
        返り値: None。条件不成立は既知の出生待ち。
        """
        a, m, b = self.buffer
        first, second = exact(m["close"]) - exact(a["close"]), exact(b["close"]) - exact(m["close"])
        if first * second <= 0:
            return
        side = 1 if first > 0 else -1
        if side * (exact(b["close"]) - exact(a["close"])) < exact(atr["atr"]):
            return
        deadline = b["end"] + 1620
        if b["confirm"] > deadline:
            self.rejected_births.append({"a": deepcopy(a), "m": deepcopy(m), "b": deepcopy(b),
                "atr_b": atr["atr"], "deadline": deadline, "reason": "出生公開が寿命後"})
            self.buffer = []
            return
        identity = f"{self.session}|W|{side:+d}|{b['index']}|{float(b['confirm']).hex()}|{b['confirm_line']}"
        tip = extreme(self.buffer, side)
        parent = {"id": identity, "direction": side, "a": deepcopy(a), "m": deepcopy(m), "b": deepcopy(b),
            "atr_b": atr["atr"], "birth_atr_source": deepcopy(atr), "origin": a["low"] if side == 1 else a["high"],
            "deadline": deadline, "r": None, "f": None, "T": None, "R": None, "T_id": None, "R_id": None,
            "birth_tip": deepcopy(tip), "tip_before_r": deepcopy(tip), "current_tip": deepcopy(tip),
            "active": True, "status": "最初r待ち", "terminal": None, "late_f": None, "trace": []}
        self.parents.append(parent)
        self.parent = parent
        self.formation(parent, "T")
        self.trace(parent, event_ref(b), "局所波出生b")
        self.buffer = []

    def expire(self, ref: dict) -> bool:
        """価格段階の処理前に公開時計と足終端の期限を検査する。

        引数: ref(dict)は公開足又は判断timer。
        返り値: boolは親が終了したか。等号は期限内。
        """
        parent = self.parent
        if parent is None:
            return False
        if ref["key"][0] > parent["deadline"] or ref["end"] is not None and ref["end"] > parent["deadline"]:
            self.terminate(ref, "親の出生後9本期限超過")
            return True
        reversal = parent["R"]
        if reversal is not None and reversal["k"] is None and reversal["cancel"] is None:
            if ref["key"][0] > reversal["deadline"] or ref["end"] is not None and ref["end"] > reversal["deadline"]:
                self.terminate(ref, "反対確認期限超過", "反対確認期限終了")
                return True
        return False

    def step_parent(self, row: dict) -> None:
        """同じ親のorigin・T・Rを一足一段階で更新する。

        引数: row(dict)は正常/ATR既知/隣接/期限内の公開足。
        返り値: None。取消や起点喪失を反対注文と同一視しない。
        """
        p, ref = self.parent, event_ref(row)
        side, close = p["direction"], exact(row["close"])
        p["current_tip"] = extreme([p["current_tip"]["source"], row], side)
        if p["f"] is None and side * (close - exact(p["origin"])) <= 0:
            p["f"] = deepcopy(row)
            self.finish_formation(p["T"], ref, "起点の終値喪失")
            r = self.formation(p, "R", row)
            r["trigger_line"] = row["high"] if r["side"] == 1 else row["low"]
            r["premise_line"] = max(p["origin"], row["low"]) if r["side"] == 1 else min(p["origin"], row["high"])
            remaining = min(3, max(0, (p["deadline"] - row["end"]) // 180))
            p["late_f"] = {"remaining_bars": int(remaining), "reason": "確認余地0本" if remaining == 0 else "確認余地1本" if remaining == 1 else None}
            p["status"] = "反対確認待ち"
            self.trace(p, ref, "起点喪失f・同原因R待ち")
            if remaining == 0:
                self.terminate(ref, "遅い起点喪失で反対確認余地0本", "反対確認期限終了")
            return
        if p["R"] is not None:
            r = p["R"]
            if r["k"] is None:
                if r["side"] * (close - exact(p["origin"])) <= 0:
                    self.terminate(ref, "反対確認前に元起点を再獲得", "R取消")
                    return
                if r["side"] * (close - exact(r["trigger_line"])) > 0:
                    r.update(k=deepcopy(row), active=True, status="有効")
                    p["status"] = "R有効"
                    self.trace(p, ref, "R再開k")
                elif row["index"] - r["f"]["index"] >= 3:
                    self.terminate(ref, "f後3本の反対確認なし", "反対確認期限終了")
            elif r["side"] * (close - exact(r["premise_line"])) <= 0:
                self.terminate(ref, "R確認後の前提線終値否定", "R取消")
            return
        t = p["T"]
        if t["cancel"] is not None:
            return
        if t["r"] is None:
            if side * (close - exact(self.previous["close"])) < 0:
                p["r"] = t["r"] = deepcopy(row)
                t["trigger_line"] = row["high"] if side == 1 else row["low"]
                t["premise_line"] = max(p["origin"], row["low"]) if side == 1 else min(p["origin"], row["high"])
                p["status"] = t["status"] = "再開待ち"
                self.trace(p, ref, "最初の逆終値r")
            else:
                p["tip_before_r"] = extreme([p["tip_before_r"]["source"], row], side)
        elif t["k"] is None:
            if side * (close - exact(t["trigger_line"])) > 0:
                t.update(k=deepcopy(row), active=True, status="有効")
                p["status"] = "T有効"
                self.trace(p, ref, "T再開k")
        elif side * (close - exact(t["premise_line"])) <= 0:
            self.finish_formation(t, ref, "T確認後の前提線終値否定")
            p["status"] = "親起点喪失待ち"
            self.trace(p, ref, "T取消・親は起点喪失待ち")

    def step(self, row: dict, atr: dict) -> None:
        """品質resetを期限より優先し、完全足を機械へ渡す。

        引数: row/atr(dict)は結合済み価格と出生ATR。
        返り値: None。reset/終端足を再出生へ兼用しない。
        """
        reason = SHARED.price_reason(row)
        if self.previous is not None and (row["index"] != self.previous["index"] + 1 or row["start"] != self.previous["end"]):
            reason = "番号又は足終端の不連続"
        if reason is not None or not atr["ready"]:
            self.reset(row, reason or atr["reason"])
            return
        if self.expire(event_ref(row)):
            self.previous = deepcopy(row)
            return
        if self.parent is None:
            self.buffer.append(deepcopy(row))
            self.buffer = self.buffer[-3:]
            if len(self.buffer) == 3:
                self.prepared = True
                self.born(atr)
        else:
            self.step_parent(row)
        self.previous = deepcopy(row)


# ----------------------------------------
def qualification(candidate: dict, values: dict, quote: dict) -> dict:
    """現在の複数技法とLast/E*を形成の固定前提線へ接続する。

    引数: candidate/values/quote(dict)は有効形成/旧float64値/正常気配。
    返り値: dictは資格・DI役割・固定順理由・現在距離。位置gateを追加しない。
    """
    reasons, di = [], values["F01"]
    role = "上位同値" if di == 0 or values["raw_background_direction"] == 0 else "順行" if di > 0 else "反転"
    for condition, reason in ((values["F02"] < 0, "FastKの方向位置が負"), (values["F03"] <= 0, "FastKの方向進行が非正"),
            (values["F07"] <= 0, "現在価格の方向進行が非正"), (di == 0 or values["raw_background_direction"] == 0, "上位DIが同値")):
        if condition:
            reasons.append(reason)
    if candidate["kind"] == "T":
        for condition, reason in ((di <= 0, "継続Tは上位DI同方向が必要"), (values["F51"] != 1 or values["F52"] != 1, "継続TのADX現値又は変化が未知"),
                (values["F47"] < .20, "継続TのADX20未満"), (values["F48"] < 0, "継続TのADXが減速")):
            if condition:
                reasons.append(reason)
    elif di < 0:
        for condition, reason in ((values["F52"] != 1, "反転のADX変化が未知"), (values["F48"] >= 0, "反転のADXが非減速"),
                (values["F15"] <= 0, "反転の15分終値位置が非正")):
            if condition:
                reasons.append(reason)
    side = candidate["side"]
    entry = quote["ask"] if side == 1 else quote["bid"]
    last_distance = side * (exact(quote["last"]) - exact(candidate["premise_line"]))
    entry_distance = side * (exact(entry) - exact(candidate["premise_line"]))
    if last_distance <= 0:
        reasons.append("現在Lastが前提線を否定")
    if entry_distance <= 0:
        reasons.append("現在新規BBOが前提線を否定")
    return {"qualified": not reasons, "role": role, "reasons": reasons, "values": deepcopy(values),
        "price": {"last": quote["last"], "entry_proxy": entry, "premise_line": candidate["premise_line"],
            "last_distance": float(last_distance), "entry_distance": float(entry_distance)}}


def location_for(slot: dict, band: dict | None, quote: dict | None, normal: bool) -> tuple:
    """前帯の場所と前方線を診断だけに限定する。

    引数: slot/band/quote(dict|None)は元時計/前帯/気配、normal(bool)は現在観測正常。
    返り値: tupleは帯snapshotと両方向E*別の場所。未知を無限余地にしない。
    """
    view = SHARED.band_view(slot, band) if band is not None else None
    ready = view is not None and view["ready"] and normal
    result = {"ready": ready, "reason": "場所診断準備済み" if ready else "前帯不明" if view is None else view["reason"] if not view["ready"] else "現在BBO又はLastの観測不足", "by_side": {}}
    for side in SIDES:
        row = {"entry_proxy": None, "position": "未知", "levels": None, "forward_lines": None}
        if ready:
            entry = quote["ask"] if side == 1 else quote["bid"]
            position = "上外" if entry > view["high"] else "下外" if entry < view["low"] else "上端" if entry == view["high"] else "下端" if entry == view["low"] else "帯内"
            levels = {name: {"price": view[name], "signed_distance": float(side * (exact(view[name]) - exact(entry)))} for name in ("high", "mid", "low")}
            forward = [{"name": name, **value} for name, value in levels.items() if value["signed_distance"] > 0]
            forward.sort(key=lambda line: (line["signed_distance"], line["name"]))
            row.update(entry_proxy=entry, position=position, levels=levels, forward_lines=forward)
        result["by_side"][str(side)] = row
    return view, result


def policy_choice(candidates: list[dict], qualifications: dict, policy: str, ready: bool, reason: str) -> dict:
    """同じ観測からT限定又はT/Rの純候補を選ぶ。

    引数: candidates/qualificationsは有効形成と資格、policy(str)はL0/L1、ready/reasonは準備状態。
    返り値: dictはside/role/reason/selected。反対資格の同時成立は停止する。
    """
    eligible = [c for c in candidates if qualifications.get(c["id"], {}).get("qualified") and (policy == "L1" or c["kind"] == "T")]
    if len({c["side"] for c in eligible}) > 1:
        raise ValueError("反対方向同時資格の鏡像矛盾")
    selected = max(eligible, key=lambda c: (c["k"]["confirm"], c["k"]["confirm_line"], c["kind"] == "T")) if eligible and ready else None
    return {"side": selected["side"] if selected else 0, "role": qualifications[selected["id"]]["role"] if selected else "待機",
        "reason": "局所波の継続候補" if selected and selected["kind"] == "T" else "同原因の起点喪失反対候補" if selected else reason,
        "selected": deepcopy(selected)}


def extract(old_slot: dict, history_sources: list[dict], birth_atr_rows: list[dict], decision_quote: dict | None, prior_band: dict | None) -> dict:
    """全公開prefixから政策共通の親局所波と現在資格を作る。

    引数: old_slot(dict)は旧73判断、history_sourcesは全当場SOURCE13、birth_atr_rowsは可視出生ATR行、decision_quoteは55当時気配、prior_bandは診断帯。
    返り値: dictは政策共通観測。旧採否・予測・先着・損益を参照しない。
    """
    SHARED.clock(old_slot)
    feature = old_slot.get("feature")
    if not isinstance(feature, dict) or type(feature.get("ready")) is not bool or feature["ready"] is not old_slot["ready"]:
        raise ValueError("旧特徴と純判断の準備差")
    result = {"base_ready": feature["ready"], "ready": False, "reason": "旧73特徴が未準備", "source_count": 0,
        "source_sha256": None, "atr_source_sha256": None, "history": {"current": None, "resets": [], "birth_buffer": [],
            "preparation": {"ready": False, "count": 0, "required": 3, "reason": "旧73特徴が未準備"}, "rejected_births": []},
        "parents": [], "formations": [], "candidates": [], "qualifications": {}, "selected_by_policy": {},
        "band": None, "location": None, "side": 0, "role": "待機", "selected": None}
    if not feature["ready"]:
        for policy in POLICIES:
            result["selected_by_policy"][policy] = policy_choice([], {}, policy, False, result["reason"])
        return result
    if (not finite(old_slot.get("atr")) or old_slot["atr"] <= 0 or not finite(old_slot.get("D")) or old_slot["D"] <= 0
            or feature.get("atr") != old_slot["atr"] or feature.get("D") != old_slot["D"]):
        raise ValueError("旧現在ATR/Dの不整合")
    prefix = SHARED.visible_prefix(old_slot, history_sources, feature)
    atr_rows, values = bind_atr(prefix, birth_atr_rows), SHARED.values_for(feature)
    machine = Machine(old_slot["session"])
    for row, atr in zip(prefix, atr_rows):
        machine.step(row, atr)
    machine.expire(event_ref(None, old_slot))
    normal = SHARED.quote_view(old_slot, decision_quote)
    ready = machine.prepared and normal
    parent = machine.parent
    reason = "出生準備待ち" if not machine.prepared else "現在BBO又はLastの観測不足" if not normal else parent["status"] if parent else "出生待ち"
    if not parent and machine.parents and machine.parents[-1]["terminal"] is not None:
        reason = machine.parents[-1]["terminal"]["reason"] if not machine.buffer else "出生待ち"
    if (not parent and not machine.buffer and machine.rejected_births
            and machine.rejected_births[-1]["b"]["index"] == prefix[-1]["index"]):
        reason = "出生公開が寿命後"
    if not machine.prepared:
        reason = "出生準備待ち"
    elif not normal:
        reason = "現在BBO又はLastの観測不足"
    candidates = [deepcopy(f) for f in machine.formations if f["active"]]
    if len(candidates) > 1:
        raise ValueError("一親でT/R同時activeの矛盾")
    for candidate in candidates:
        candidate["k_age_seconds"] = old_slot["time"] - candidate["k"]["confirm"]
        candidate["k_end_age_seconds"] = old_slot["scheduled"] - candidate["k"]["end"]
        candidate["tip_distance"] = float(candidate["side"] * (exact(parent["tip_before_r"]["price"]) - exact(candidate["k"]["close"])))
        if normal:
            result["qualifications"][candidate["id"]] = qualification(candidate, values[str(candidate["side"])], decision_quote)
    if candidates and normal and not any(q["qualified"] for q in result["qualifications"].values()):
        reason = "局所波の現在複合条件不適格"
    band, location = location_for(old_slot, prior_band, decision_quote, normal)
    result.update(ready=ready, reason=reason, source_count=len(prefix), source_sha256=digest(prefix, True), atr_source_sha256=digest(atr_rows),
        history={"current": deepcopy(prefix[-1]), "resets": machine.resets, "birth_buffer": [event_ref(r) for r in machine.buffer],
            "preparation": {"ready": machine.prepared, "count": len(machine.buffer), "required": 3,
                "reason": "出生入力準備済み" if machine.prepared else "出生準備待ち"}, "rejected_births": machine.rejected_births},
        parents=machine.parents, formations=machine.formations, candidates=candidates, band=band, location=location)
    for policy in POLICIES:
        policy_reason = "R形成はL0で採用対象外" if policy == "L0" and candidates and candidates[0]["kind"] == "R" and ready else reason
        result["selected_by_policy"][policy] = policy_choice(candidates, result["qualifications"], policy, ready, policy_reason)
    result.update({key: deepcopy(result["selected_by_policy"]["L1"][key]) for key in ("side", "role", "selected", "reason")})
    return result


def choose(old_slot: dict, observation: dict, policy: str) -> dict:
    """政策共通観測をO49純10項目と形成由来へ射影する。

    引数: old_slot/observation(dict)は元時計と共通観測、policy(str)はL0/L1。
    返り値: dictは純10＋session/policy/origin/pattern_id/parent_id/formation/premise_line/trigger_line/birth_atr/band_id。
    """
    if policy not in POLICIES or not all(k in old_slot for k in SLOT_FIELDS):
        raise ValueError("政策又は純10項目なし")
    SHARED.clock(old_slot)
    choice = observation["selected_by_policy"][policy]
    selected = choice["selected"]
    if selected is not None and (not observation["ready"] or selected["side"] != choice["side"]
            or not observation["qualifications"][selected["id"]]["qualified"] or policy == "L0" and selected["kind"] != "T"):
        raise ValueError("政策選択と資格の矛盾")
    parent = next((p for p in observation["parents"] if selected is not None and p["id"] == selected["parent_id"]), None)
    result = {key: deepcopy(old_slot[key]) for key in SLOT_FIELDS}
    kind = selected["kind"] if selected else None
    result.update(session=old_slot["session"], policy=policy, side=choice["side"], role=choice["role"], reason=choice["reason"],
        ready=observation["ready"], origin="局所波継続" if kind == "T" else "同原因起点喪失反対" if kind == "R" else "局所波待機",
        pattern_id=selected["id"] if selected else None, parent_id=parent["id"] if parent else None, formation=kind,
        premise_line=selected["premise_line"] if selected else None, trigger_line=selected["trigger_line"] if selected else None,
        birth_atr=parent["atr_b"] if parent else None, band_id=observation["band"]["id"] if observation["band"] else None)
    return result


# ----------------------------------------
def synthetic(closes: list[int | float], desired_side: int = 1, background: int = 1, birth_atr: int | float = 5) -> tuple:
    """価格本文を読まず局所機械の人工入力一式を作る。

    引数: closes(list)は終値、desired_side/background(int)は現在勢い/DI、birth_atrは人工ATR。
    返り値: tupleはextractの5引数。出生用ATRと現在判断ATRは別値。
    """
    slot, sources, band, quote = SHARED.synthetic(closes, desired_side, background)
    rows = [{**{key: deepcopy(source[key]) for key in SOURCE_FIELDS[:9]}, "source_sha256": digest(source, True),
        "atr": birth_atr, "valid": True, "numeric_count": 30, "reset_reasons": [], "ready": True,
        "reason": "出生ATR準備済み"} for source in sources]
    return slot, sources, rows, quote, band


def refresh(case: tuple) -> tuple:
    """人工の出典改変を現在SOURCEと出生ATR指紋へ同期する。

    引数: case(tuple)は人工5引数。
    返り値: tupleは同じ辞書参照の一式。実入力へ使用しない。
    """
    slot, sources, rows, quote, band = case
    for source, atr in zip(sources, rows):
        atr.update({key: deepcopy(source[key]) for key in SOURCE_FIELDS[:9]})
        atr["source_sha256"] = digest(source, True)
    slot["feature"]["base"]["base"]["sources"]["current"] = deepcopy(sources[-1])
    quote.update(now=slot["time"], line=slot["line"])
    return case


def reflected(case: tuple, constant: int = 2200) -> tuple:
    """人工価格を反射し現在方向vectorを交換する。

    引数: case(tuple)は人工5引数、constant(int)は反射価格。
    返り値: tupleは同じ時計の売買鏡像。出生ATRは方向不変。
    """
    slot, sources, rows, quote, band = deepcopy(case)
    slot, sources, band, quote = SHARED.reflected((slot, sources, band, quote), constant)
    return refresh((slot, sources, rows, quote, band))


def self_test() -> dict:
    """局所出生・同原因切替・因果時計・準備と政策包含を人工検査する。

    引数: なし。
    返り値: dictは成功/テスト件数/照合項目数。本物入力・fit・市場・新計測は0。
    """
    tests, checks = 0, 0

    def check(actual: object, expected: object) -> None:
        """人工期待を型を含む固定JSONで比較する。

        引数: actual/expected(object)は実値/期待値。
        返り値: None。不一致は即停止。
        """
        nonlocal checks
        checks += 1
        if canonical(actual, True) != canonical(expected, True):
            raise AssertionError((actual, expected))

    def observe(case: tuple) -> dict:
        """入力不変と政策の純包含を各人工例で検査する。

        引数: case(tuple)は人工5引数。
        返り値: dictは共通観測。
        """
        before = canonical(case, True)
        obs = extract(*case)
        check(canonical(case, True), before)
        l0, l1 = choose(case[0], obs, "L0"), choose(case[0], obs, "L1")
        if l0["side"]:
            check({k: l0[k] for k in SLOT_FIELDS}, {k: l1[k] for k in SLOT_FIELDS})
            check(l1["formation"], "T")
        elif l1["side"]:
            check(l1["formation"], "R")
        return obs

    def reject(case: tuple) -> None:
        """schema矛盾が停止することを検査する。

        引数: case(tuple)は破壊した人工入力。
        返り値: None。
        """
        caught = False
        try:
            extract(*case)
        except ValueError:
            caught = True
        check(caught, True)

    base = synthetic([100, 103, 106, 104, 106])
    obs = observe(base)
    check((obs["side"], obs["selected"]["kind"], obs["role"]), (1, "T", "順行"))
    check((obs["parents"][0]["a"]["index"], obs["parents"][0]["b"]["index"], obs["parents"][0]["r"]["index"]), (0, 2, 3))
    check((obs["selected"]["trigger_line"], obs["selected"]["premise_line"]), (105, 103))
    check((obs["parents"][0]["atr_b"], choose(base[0], obs, "L0")["atr"]), (5, 100.0))
    tests += 1
    for closes, expected in (([100, 100, 106], 0), ([100, 103, 105], 1), ([100, 103, 104], 0), ([100, 99, 106], 0)):
        got = observe(synthetic(closes))
        check(len(got["parents"]), expected)
    for closes in ([100], [100, 103]):
        check(observe(synthetic(closes))["ready"], False)
    tests += 1
    got = observe(synthetic([100, 103, 106, 104, 102, 106]))
    check((got["side"], got["selected"]["r"]["index"], got["selected"]["k"]["index"]), (1, 3, 5))
    got = observe(synthetic([100, 103, 106, 104, 106, 105]))
    check((got["side"], got["selected"]["k"]["index"]), (1, 4))
    tests += 1
    got = observe(synthetic([100, 103, 106, 104, 106, 103, 106]))
    check((got["side"], got["parents"][0]["status"], got["formations"][0]["cancel"]["index"]), (0, "親起点喪失待ち", 5))
    check(len(got["parents"]), 1)
    tests += 1
    reverse = synthetic([100, 103, 106, 104, 106, 103, 98, 96], -1, -1)
    got = observe(reverse)
    check((got["side"], got["selected"]["kind"], got["role"]), (-1, "R", "順行"))
    check((got["selected"]["f"]["index"], got["selected"]["k"]["index"], got["selected"]["parent_id"]), (6, 7, got["parents"][0]["id"]))
    check((choose(reverse[0], got, "L0")["side"], choose(reverse[0], got, "L1")["side"]), (0, -1))
    tests += 1
    got = observe(synthetic([100, 103, 106, 98], -1, -1))
    check((got["side"], got["formations"][1]["k"], got["parents"][0]["status"]), (0, None, "反対確認待ち"))
    got = observe(synthetic([100, 103, 106, 98, 99, 96], -1, -1))
    check((got["side"], got["parents"][0]["terminal"]["reason"]), (0, "反対確認前に元起点を再獲得"))
    tests += 1
    got = observe(synthetic([100, 103, 106, 98, 98, 98, 96], -1, -1))
    check((got["side"], got["selected"]["k"]["index"]), (-1, 6))
    got = observe(synthetic([100, 103, 106, 98, 98, 98, 98, 96], -1, -1))
    check((got["side"], got["parents"][0]["terminal"]["index"]), (0, 6))
    tests += 1
    c = synthetic([100, 103, 106, 98, 96, 97], -1, -1)
    got = observe(c)
    check((got["side"], got["selected"]["trigger_line"], got["selected"]["premise_line"]), (-1, 97, 99))
    got = observe(synthetic([100, 103, 106, 98, 96, 99, 96], -1, -1))
    check((got["side"], got["parents"][0]["terminal"]["index"]), (0, 5))
    tests += 1
    for c in (base, reverse, synthetic([100, 103, 106, 104, 102, 106]), synthetic([100, 103, 106, 98, 98, 98, 96], -1, -1)):
        left, right = observe(c), observe(reflected(c))
        check((right["side"], right["role"], right["ready"]), (-left["side"], left["role"], left["ready"]))
        check([(f["kind"], f["active"], f["status"]) for f in left["formations"]], [(f["kind"], f["active"], f["status"]) for f in right["formations"]])
    tests += 1
    for field, value in (("F02", -.1), ("F03", 0), ("F07", 0), ("F47", math.nextafter(.20, -math.inf)), ("F48", -.01), ("F51", 0), ("F52", 0)):
        c = deepcopy(base)
        for side in SIDES:
            c[0]["feature"]["vectors"][str(side)][VALUE_FIELDS[field]] = side * value if field in ("F02", "F03", "F07") else value
        check(observe(c)["side"], 0)
    check(observe(synthetic([100, 103, 106, 104, 106], 1, 0))["side"], 0)
    tests += 1
    c = synthetic([100, 103, 106, 98, 96], -1, 1)
    for vector in c[0]["feature"]["vectors"].values():
        vector[47] = -.01
    check((observe(c)["side"], observe(c)["role"]), (-1, "反転"))
    for field, value in (("F15", 0), ("F48", 0), ("F52", 0)):
        bad = deepcopy(c)
        for side in SIDES:
            bad[0]["feature"]["vectors"][str(side)][VALUE_FIELDS[field]] = side * value if field == "F15" else value
        check(observe(bad)["side"], 0)
    tests += 1
    c = list(deepcopy(base))
    c[4] = None
    got = observe(c)
    check((got["side"], got["ready"], got["location"]["ready"]), (1, True, False))
    c = deepcopy(base)
    c[4].update(reference_available=False, published=False, ready=False, reason="前収録なし", begin=None, end=None, high="未知価格")
    check(observe(c)["side"], 1)
    tests += 1
    for key, value in (("last", 103), ("ask", 103), ("last", None), ("valid", False)):
        c = deepcopy(base)
        c[3][key] = value
        got = observe(c)
        check(got["side"], 0)
    tests += 1
    c = synthetic([100, 103, 106, 104, 106, 107, 108, 109])
    c[2][4].update(atr=None, ready=False, reason="出生ATR未準備")
    got = observe(c)
    check((len(got["history"]["resets"]), got["ready"], got["parents"][0]["terminal"]["index"]), (1, True, 4))
    for length, ready in ((6, False), (7, False), (8, True)):
        c = synthetic([100, 103, 106, 104, 106, 107, 108, 109][:length])
        c[2][4].update(atr=0, ready=False, reason="出生ATR非正")
        check(observe(c)["ready"], ready)
    tests += 1
    c = synthetic([100, 103, 106, 104, 106, 107, 108, 109])
    c[1][4]["high"] = float("nan")
    got = observe(refresh(c))
    check((got["ready"], got["parents"][0]["terminal"]["reason"]), (True, "価格不正"))
    check(isinstance(canonical(got), str), True)
    tests += 1
    c = deepcopy(base)
    original = observe(c)
    c[1].append({"session": c[0]["session"], "end": c[0]["scheduled"] + 180, "close": "未来不正"})
    check(observe(c), original)
    c[1].append({"session": c[0]["session"], "end": c[0]["scheduled"], "confirm": c[0]["time"], "confirm_line": c[0]["line"] + 1})
    check(observe(c), original)
    tests += 1
    c = deepcopy(base)
    original = observe(c)
    c[0].update(side=-1, role="反転", reason="旧判断改変", prediction={"score": -999, "side": -1})
    check(observe(c), original)
    tests += 1
    c = synthetic([100, 103, 106] + [106] * 8 + [104, 108])
    c[0].update(time=2160, scheduled=2160)
    del c[1][12:]
    del c[2][12:]
    refresh(c)
    check(observe(c)["parents"][0]["active"], True)
    c[0]["time"] = 2160.0001
    refresh(c)
    got = observe(c)
    check((got["parents"][0]["active"], got["parents"][0]["terminal"]["clock"], got["ready"]), (False, "判断時刻", True))
    tests += 1
    c = synthetic([100, 103, 106, 104, 106])
    for row in c[1][3:]:
        row["confirm"] += 1800
        row["confirm_line"] += 1000
    c[0].update(time=c[1][-1]["confirm"] + 1, line=9999)
    got = observe(refresh(c))
    check((got["side"], got["parents"][0]["terminal"]["index"]), (0, 3))
    tests += 1
    c = synthetic([100, 103, 106])
    c[1][-1]["confirm"] = 2160.1
    c[0].update(time=2161, line=9999)
    got = observe(refresh(c))
    check((len(got["parents"]), got["history"]["rejected_births"][0]["reason"], got["reason"]), (0, "出生公開が寿命後", "出生公開が寿命後"))
    tests += 1
    c = synthetic([100, 103, 106, 98, 99, 100, 103, 106])
    got = observe(c)
    check([(p["a"]["index"], p["b"]["index"]) for p in got["parents"]], [(0, 2), (5, 7)])
    check(got["parents"][0]["terminal"]["index"], 4)
    tests += 1
    c = synthetic([100, 103, 106, 98, 98, 98, 96], -1, -1)
    c[1][-1]["confirm"] = c[1][3]["end"] + 540 + .001
    c[0].update(time=c[1][-1]["confirm"] + 1, line=9999)
    got = observe(refresh(c))
    check((got["side"], got["parents"][0]["terminal"]["reason"]), (0, "反対確認期限超過"))
    c[1][-1]["confirm"] -= .001
    c[0]["time"] = c[1][-1]["confirm"] + 1
    check(observe(refresh(c))["side"], -1)
    tests += 1
    for f_index, remaining in ((10, 1), (11, 0)):
        c = synthetic([100, 103, 106] + [106] * (f_index - 3) + [98], -1, -1)
        c[0]["time"] = c[0]["scheduled"]
        got = observe(refresh(c))
        check(got["parents"][0]["late_f"]["remaining_bars"], remaining)
        check(got["parents"][0]["active"], remaining > 0)
    tests += 1
    c = synthetic([100, 103, 106, 104, 106, 107, 108, 109, 114])
    for row in c[1][5:]:
        for key in ("start", "end", "confirm"):
            row[key] += 180
        row["index"] += 1
    c[0].update(scheduled=c[1][-1]["end"], time=c[1][-1]["confirm"] + 1)
    got = observe(refresh(c))
    check((got["parents"][0]["terminal"]["reason"], got["parents"][-1]["a"]["index"]), ("番号又は足終端の不連続", 7))
    tests += 1
    c = deepcopy(base)
    c[1][3]["high"] = 200
    got = observe(refresh(c))
    check((got["parents"][0]["birth_tip"]["price"], got["parents"][0]["tip_before_r"]["price"], got["parents"][0]["current_tip"]["price"]), (107, 107, 200))
    check(got["selected"], None)
    tests += 1
    c = deepcopy(base)
    c[0].update(time=c[1][-1]["confirm"], line=c[1][-1]["confirm_line"])
    check(observe(refresh(c))["side"], 1)
    c[0]["line"] -= 1
    refresh(c)
    reject(c)
    tests += 1
    c = synthetic([100, 103, 106, 104, 106] + [106] * 5)
    got = observe(c)
    k_end = got["selected"]["k"]["end"]
    deadline = got["parents"][0]["deadline"]
    for offset in (0, 1, 179, 899):
        scheduled = list(range(k_end + offset, int(deadline) + 1, 900))
        check(len(scheduled) <= 2, True)
    tests += 1
    for mutation in ("atr_missing", "atr_hash", "atr_ready", "current", "quote", "prefix", "key", "mask"):
        c = deepcopy(base)
        if mutation == "atr_missing":
            c[2].pop()
        elif mutation == "atr_hash":
            c[2][0]["source_sha256"] = "0" * 64
        elif mutation == "atr_ready":
            c[2][0].update(atr=0, ready=True)
        elif mutation == "current":
            c[0]["feature"]["base"]["base"]["sources"]["current"]["close"] += 1
        elif mutation == "quote":
            c[3]["line"] += 1
        elif mutation == "prefix":
            c[1].pop(0)
        elif mutation == "key":
            c[1][1].update(confirm=c[1][0]["confirm"], confirm_line=c[1][0]["confirm_line"])
        else:
            c[0]["feature"]["vectors"]["1"][50] = True
        reject(c)
    tests += 1
    c = deepcopy(base)
    c[0].update(ready=False, line=None)
    c[0]["feature"] = {"ready": False}
    got = extract(c[0], None, None, None, None)
    check((got["ready"], got["source_count"], choose(c[0], got, "L0")["line"]), (False, 0, None))
    tests += 1
    check(hashlib.sha256(SHARED_PATH.read_bytes()).hexdigest(), SHARED_SHA256)
    return {"成功": True, "テスト件数": tests, "照合項目数": checks, "不一致数": 0,
        "本物入力読取": False, "fit": 0, "市場再生": False, "新計測": 0}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, indent=2, allow_nan=False))
