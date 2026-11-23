"""定時枠までの公開足を進め、局所再開と突破失敗の初発動を消費する。

固定49の数値銀行だけを読み込む。市場ファイル・ラベル・損益は読まず、
保有の有無を知らないまま全予定枠でP0/P1の入口を返す。
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys


SPEC = importlib.util.spec_from_file_location(
    "局所再開が固定参照する49入口", Path(__file__).resolve().parents[1] / "定時帯反応/入口.py")
I49 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = I49
SPEC.loader.exec_module(I49)
POLICIES = ("P0", "P1")
LIFETIME = 9
FRESHNESS = 900


def build_bank(sessions: list[dict]) -> dict:
    """固定49の数値銀行をそのまま構築する。

    引数: sessions(list[dict])は49のSOURCE入力契約。
    返り値: dictは固定49銀行。価格ファイルを自ら開かない。
    """
    return I49.build_bank(sessions)


def price(value: float) -> Fraction:
    """保存された価格の精密値を作る。

    引数: value(float)は元価格。
    返り値: Fractionは丸めを追加しない有理数。
    """
    return Fraction(value)


def sign(value: Fraction | float) -> int:
    """値のstrict方向を得る。

    引数: value(Fraction|float)は有限値。
    返り値: intは−1、0、+1。
    """
    return int(value > 0) - int(value < 0)


def band_line(band: dict, side: int, outer: bool = True) -> Fraction:
    """元方向に対応するORの外5pt又は内5pt線を得る。

    引数: band(dict)はOR、side(int)は元方向、outer(bool)は外線か。
    返り値: Fractionは固定端に対する線。
    """
    edge = price(band["high"] if side == 1 else band["low"])
    return edge + side * (5 if outer else -5)


class SessionSignals:
    """当場のT/R監視と未消費初発動を、全定時callbackで進める。"""

    def __init__(self, bank: dict, session: str) -> None:
        """場内出典を凍結し、監視・発動・時計を空にする。

        引数: bank(dict)は49数値銀行、session(str)は場名。
        返り値: None。旧49モジュール・入力銀行を変更しない。
        """
        self.session = session
        self.data = deepcopy(bank[session])
        self.bank = {session: self.data}
        self.rows = self.data["frames3"]
        self.indexed = {row["index"]: row for row in self.rows}
        self.processed = set()
        self.previous = None
        self.t_watch = None
        self.r_watch = None
        self.events = []
        self.actions = []
        self.last_scheduled = None
        self.last_limit = None

    def _action(self, row: dict | None, action: str, **values) -> None:
        """足で観測した遷移と根拠をJSON安全に残す。

        引数: row(dict|None)は足、action(str)は動作、values(dict)は追加根拠。
        返り値: None。
        """
        self.actions.append({"action": action, "source": I49.source(row) if row else None,
                             **deepcopy(values)})

    def _di(self, scheduled: float, time: float, line: int) -> dict:
        """指定された公開時点だけから当場の上位DIを参照する。

        引数: scheduled(float)は下位終了又は定時、time(float)/line(int)は可視key。
        返り値: dictは準備、優勢、SOURCEと診断ADX。
        """
        row = I49.choose_asof(self.data["frames15"], scheduled, time, line)
        ready = bool(row is not None and row["valid"] and scheduled - row["end"] <= 900
                     and I49.finite(row["plus_di"]) and I49.finite(row["minus_di"]))
        return {"ready": ready, "source": I49.source(row) if row is not None else None,
                "plus_di": row["plus_di"] if row is not None else None,
                "minus_di": row["minus_di"] if row is not None else None,
                "direction": sign(row["plus_di"] - row["minus_di"]) if ready else None,
                "adx": row["adx"] if row is not None else None}

    def _foot_di(self, row: dict) -> dict:
        """その3分足が公開された時点の上位値を得る。

        引数: row(dict)は公開足。
        返り値: dictは未来上位を混ぜないDI出典。
        """
        return self._di(row["end"], row["confirm"], row["confirm_line"])

    def _background(self, row: dict, band: dict, side: int, di: dict) -> bool:
        """TのOR外保持と同方向DI優勢を確認する。

        引数: row(dict)は足、band(dict)はOR、side(int)は実方向、di(dict)は当時上位。
        返り値: boolは値の同値を含めない背景保持。
        """
        return bool(di["ready"] and di["direction"] == side
                    and side * (price(row["close"]) - band_line(band, side)) > 0)

    def _cancel_all(self, row: dict, reason: str) -> None:
        """価格の切断で両監視と未消費発動を取消す。

        引数: row(dict)は切断が判明した足、reason(str)は理由。
        返り値: None。新しい価格種は次の別足から使える。
        """
        for name in ("t_watch", "r_watch"):
            watch = getattr(self, name)
            if watch is not None:
                self._action(row, "監視取消", kind=watch["kind"], reason=reason, watch=watch)
                setattr(self, name, None)
        for event in self.events:
            if event["active"]:
                event.update(active=False, cancel_reason=reason)
                self._action(row, "発動失効", event_id=event["event_id"], reason=reason)

    def _new_watch(self, kind: str, row: dict, side: int, band: dict, di: dict) -> dict:
        """現在足だけを起点に監視を登録する。

        引数: kind(str)はT/R、row(dict)は起点、side(int)は元方向、
            band(dict)は固定OR、di(dict)は起点時点上位。
        返り値: dictは出典を一度保持する監視。
        """
        watch = {"watch_id": f"{self.session}_{kind}監視_{row['index']:04d}_{side}",
                 "kind": kind, "side": side, "origin_index": row["index"],
                 "origin": I49.source(row), "origin_di": deepcopy(di),
                 "OR": {"low": band["low"], "high": band["high"]},
                 "stage": "再開待ち" if kind == "T" else "復帰待ち",
                 "failure": None, "failure_di": None, "line_price": None}
        self._action(row, "監視登録", watch=watch)
        return watch

    def _emit(self, watch: dict, row: dict, previous: dict, di: dict, line_price: float) -> None:
        """最初の価格確認を一つの未消費発動へ固定する。

        引数: watch(dict)は監視、row(dict)は発動、previous(dict)は前足、
            di(dict)は発動上位、line_price(float)は発動後否定線。
        返り値: None。新規注文は作らない。
        """
        side = watch["side"] if watch["kind"] == "T" else -watch["side"]
        event = {"event_id": f"{watch['watch_id']}_初発動_{row['index']:04d}",
                 "kind": watch["kind"], "side": side, "original_side": watch["side"],
                 "role": "順行" if watch["kind"] == "T" else "反転",
                 "origin_index": watch["origin_index"], "trigger_index": row["index"],
                 "trigger_end": row["end"], "trigger_key": list(I49.key(row)),
                 "origin": deepcopy(watch["origin"]), "trigger": I49.source(row),
                 "previous": I49.source(previous), "failure": deepcopy(watch["failure"]),
                 "origin_di": deepcopy(watch["origin_di"]), "failure_di": deepcopy(watch["failure_di"]),
                 "trigger_di": deepcopy(di), "OR": deepcopy(watch["OR"]),
                 "line_price": float(line_price), "trigger_atr": row["atr"],
                 "trigger_fast_change": deepcopy(row["fast_change"]),
                 "active": True, "cancel_reason": ""}
        self.events.append(event)
        self._action(row, "初発動固定", event=event)

    def _invalidate_events(self, row: dict, band: dict, di: dict) -> bool:
        """発動後の別足で、否定とT背景失効を先に確認する。

        引数: row(dict)は後足、band(dict)はOR、di(dict)は当時上位。
        返り値: boolは同足T再登録を禁止する失効があったか。
        """
        block_t = False
        for event in self.events:
            if not event["active"] or row["index"] <= event["trigger_index"]:
                continue
            reason = ""
            if event["kind"] == "R" and event["original_side"] * (
                    price(row["close"]) - band_line(band, event["original_side"])) >= 0:
                reason = "R元外側再獲得"
            elif event["side"] * (price(row["close"]) - price(event["line_price"])) <= 0:
                reason = "発動線の終値否定"
            elif event["kind"] == "T" and not self._background(row, band, event["side"], di):
                reason = "T発動後背景失効"
            if reason:
                event.update(active=False, cancel_reason=reason)
                self._action(row, "発動失効", event_id=event["event_id"], reason=reason)
                block_t |= event["kind"] == "T"
        return block_t

    def _on_row(self, row: dict) -> None:
        """一つの公開足を、取消・発動・新監視の順で進める。

        引数: row(dict)は当時可視となった3分足。
        返り値: None。足内高安の順序は推定しない。
        """
        previous = self.previous
        contiguous = previous is not None and I49.adjacent(previous, row)
        if not row["valid"] or previous is not None and not contiguous:
            self._cancel_all(row, "価格不正又は公開足の不連続")
            previous = None
        if not row["valid"]:
            self.previous = None
            return
        band = I49.opening_range(self.rows, self.data["begin"], row["end"], *I49.key(row))
        if not band["ready"]:
            self._cancel_all(row, "OR未準備")
            self.previous = row
            return
        di = self._foot_di(row)
        block_t = self._invalidate_events(row, band, di)
        had_t, had_r = self.t_watch is not None, self.r_watch is not None
        if had_t:
            watch, side = self.t_watch, self.t_watch["side"]
            reason = ("10本寿命" if row["index"] - watch["origin_index"] > LIFETIME else
                      "T背景失効" if not self._background(row, band, side, di) else "")
            if reason:
                self._action(row, "監視取消", kind="T", reason=reason, watch=watch)
                self.t_watch = None
                block_t = True
            elif previous is not None and side * (price(row["close"]) - price(
                    previous["high"] if side == 1 else previous["low"])) > 0:
                self._emit(watch, row, previous, di, previous["high"] if side == 1 else previous["low"])
                self.t_watch = None
        if had_r:
            watch, original = self.r_watch, self.r_watch["side"]
            actual = -original
            if row["index"] - watch["origin_index"] > LIFETIME:
                self._action(row, "監視取消", kind="R", reason="10本寿命", watch=watch)
                self.r_watch = None
            elif watch["stage"] == "復帰待ち":
                if original * (price(row["close"]) - band_line(band, original, False)) < 0:
                    change = I49.fraction(row["fast_change"])
                    missing = change is None or not di["ready"]
                    allowed = not missing and actual * change > 0 and di["direction"] != original
                    if allowed:
                        watch.update(stage="逆端確認待ち", failure=I49.source(row), failure_di=deepcopy(di),
                                     line_price=row["low"] if original == 1 else row["high"])
                        self._action(row, "初回復帰固定", watch=watch, fast_change=row["fast_change"])
                    else:
                        self._action(row, "初回復帰見送り消費", kind="R", watch=watch,
                                     status="invalid" if missing else "WAIT",
                                     reason="復帰Fast又はDI未準備" if missing else "復帰Fast又はDI不一致",
                                     di=di, fast_change=row["fast_change"])
                        self.r_watch = None
            else:
                if original * (price(row["close"]) - band_line(band, original)) >= 0:
                    self._action(row, "監視取消", kind="R", reason="R元外側再獲得", watch=watch)
                    self.r_watch = None
                elif actual * (price(row["close"]) - price(watch["line_price"])) > 0:
                    if di["ready"] and di["direction"] != original:
                        self._emit(watch, row, previous, di, watch["line_price"])
                    else:
                        self._action(row, "初回逆端見送り消費", kind="R", watch=watch,
                                     status="WAIT" if di["ready"] else "invalid",
                                     reason="確認DI不一致" if di["ready"] else "確認DI未準備", di=di)
                    self.r_watch = None
        if previous is not None:
            if not had_t and not block_t:
                change = I49.fraction(row["fast_change"])
                for side in (1, -1):
                    if (self._background(row, band, side, di) and change is not None
                            and side * (price(row["close"]) - price(previous["close"])) < 0
                            and side * change < 0):
                        self.t_watch = self._new_watch("T", row, side, band, di)
                        break
            if not had_r:
                for side in (1, -1):
                    limit = band_line(band, side)
                    if side * (price(previous["close"]) - limit) <= 0 < side * (price(row["close"]) - limit):
                        self.r_watch = self._new_watch("R", row, side, band, di)
                        break
        self.previous = row

    def _advance(self, scheduled: float, limit: tuple) -> None:
        """まだ処理していない可視足だけを進める。

        引数: scheduled(float)は予定、limit(tuple)は実公開制限。
        返り値: None。未来・未公開足の存在を取消理由へ使わない。
        """
        for row in self.rows:
            if row["index"] not in self.processed and row["publish"] and row["end"] <= scheduled and I49.key(row) <= limit:
                self.processed.add(row["index"])
                self._on_row(row)

    def _context(self, scheduled: float, limit: tuple) -> dict:
        """新方式の共通準備を、旧Rの10本条件と独立に確認する。

        引数: scheduled(float)は予定、limit(tuple)は実公開制限。
        返り値: dictは価格3本/OR/ATR/Fast/DIの出典と準備理由。
        """
        current = I49.choose_asof(self.rows, scheduled, *limit)
        result = {"ready": False, "reason": "", "current": None, "previous": None, "OR": None,
                  "upper": self._di(scheduled, *limit), "atr": None, "D": None}
        if current is None:
            result["reason"] = "当場公開3分参照なし"
            return result
        result.update(current=I49.source(current), atr=current["atr"])
        if not current["valid"] or scheduled - current["end"] > 180:
            result["reason"] = "最新3分価格不正又は180秒超過"
            return result
        band = I49.opening_range(self.rows, self.data["begin"], scheduled, *limit)
        result["OR"] = band
        recent = I49.local_window(self.rows, current, 3, *limit)
        if not band["ready"] or recent is None:
            result["reason"] = "OR未準備" if not band["ready"] else "直近3本公開完全隣接不足"
            return result
        result["previous"] = I49.source(recent[-2])
        if not I49.finite(current["atr"]) or current["atr"] <= 0:
            result["reason"] = "ATR正値未準備"
        elif not current["fast_k"]["valid"] or not current["fast_change"]["valid"]:
            result["reason"] = "FastK現前未準備"
        elif not result["upper"]["ready"]:
            result["reason"] = "当場15分DI未準備又は900秒超過"
        else:
            result.update(ready=True, D=I49.distance(current["atr"]))
        return result

    def evaluate(self, scheduled: float, time: float, line: int | None, bbo_ok: bool) -> dict:
        """可視発動を当該枠で一度消費し、P0/P1の入口を返す。

        引数: scheduled(float)は予定、time(float)/line(int|None)は最初の価格key、
            bbo_ok(bool)はそのBBO正常性。欠測でも全枠で呼ぶ。
        返り値: dictはP0/P1各feature。保有中・未約定でも消費は取り消さない。
        """
        if not I49.finite(scheduled) or not I49.finite(time) or not scheduled <= time <= scheduled + 30:
            raise I49.InputError("定時と実判断時計が不正")
        if self.last_scheduled is not None and scheduled <= self.last_scheduled:
            raise I49.InputError("全予定枠はstrict昇順で一度だけ")
        if type(bbo_ok) is not bool or line is not None and (type(line) is not int or line < 0):
            raise I49.InputError("BBO旗又は原行が不正")
        if line is None and (time != scheduled or bbo_ok):
            raise I49.InputError("欠測はtime=scheduledかつBBO不正")
        limit = (scheduled, -1) if line is None else (time, line)
        if self.last_limit is not None and limit < self.last_limit:
            raise I49.InputError("実判断公開keyの後退")
        if not self.data["begin"] <= scheduled < self.data["end"]:
            raise I49.InputError("予定時刻が場外")
        self.actions = []
        self._advance(scheduled, limit)
        context = self._context(scheduled, limit)
        current_di = context["upper"]
        available, consumed = {"P0": [], "P1": []}, {"P0": [], "P1": []}
        for event in self.events:
            age = scheduled - event["trigger_end"]
            used = deepcopy(event)
            used["age_seconds"] = age
            if used["active"] and age > FRESHNESS:
                used.update(active=False, cancel_reason="発動900秒超過")
            if used["active"] and context["current"] is not None and context["OR"] is not None:
                row = context["current"]
                if used["kind"] == "T" and not self._background(row, context["OR"], used["side"], current_di):
                    used.update(active=False, cancel_reason="定時T背景不一致又は未準備")
                if used["kind"] == "R" and (not current_di["ready"] or current_di["direction"] == used["original_side"]):
                    used.update(active=False, cancel_reason="定時RのDI不一致又は未準備")
            for policy in (POLICIES if event["kind"] == "T" else ("P1",)):
                consumed[policy].append(used)
                if used["active"]:
                    available[policy].append(used)
        old = (I49.evaluate_slot(self.bank, self.session, scheduled, time, line, "S1")
               if line is not None else {"ready": False, "side": 0, "role": "待機", "kind": None,
                                         "reason": "判断時計欠測", "atr": None, "D": None})
        if old["side"] and old["kind"] == "R":
            available["P0"].append({"event_id": None, "kind": "旧R", "side": old["side"], "role": old["role"],
                                     "age_seconds": None, "old_feature": deepcopy(old)})
        result = {}
        for policy in POLICIES:
            choices = available[policy]
            feature = {"side": 0, "role": "待機", "atr": context["atr"], "D": context["D"],
                       "reason": context["reason"], "ready": context["ready"],
                       "current": deepcopy(context["current"]), "previous": deepcopy(context["previous"]),
                       "upper": deepcopy(current_di), "OR": deepcopy(context["OR"]),
                       "diagnostic": {"actions": deepcopy(self.actions),
                                      "consumed_ids": [x["event_id"] for x in consumed[policy]],
                                      "consumed_events": deepcopy(consumed[policy]),
                                      "candidate_events": deepcopy(choices), "trigger_age_seconds": None,
                                      "T_watch": deepcopy(self.t_watch), "R_watch": deepcopy(self.r_watch),
                                      "old_R": deepcopy(old) if policy == "P0" else None}}
            if not bbo_ok:
                feature.update(ready=False, reason="判断時計欠測" if line is None else "判断BBO不正")
            elif not context["ready"]:
                pass
            elif len(choices) > 1:
                feature["reason"] = "同枠複数発動WAIT"
            elif not choices:
                if policy == "P0" and not old["ready"]:
                    feature.update(ready=False, reason="旧R判定不能: " + old["reason"])
                else:
                    feature["reason"] = "新しい初発動なし"
            else:
                selected = choices[0]
                feature.update(side=selected["side"], role=selected["role"], reason="採用")
                feature["diagnostic"]["trigger_age_seconds"] = selected["age_seconds"]
                if selected["kind"] == "旧R":
                    feature.update(atr=old["atr"], D=old["D"])
            result[policy] = feature
        self.events = []
        self.last_scheduled, self.last_limit = scheduled, limit
        return result
