"""85の保持帯off/on・二遅延4会計を、当時出典と原板のG1保護へ独立照合する。"""

from __future__ import annotations

import argparse

# 派生元83原板監査SHA256: ce632316677a7f965d93f890a9c3cae33653815545558c92961f37858d297d05
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import importlib.util
import json
from pathlib import Path


def load_base() -> object:
    """
    機能: 固定80の価格時計・原行・約定照合を読取依存として読み込む。
    引数: なし。
    返り値: object は独立監査の既存部品。固定ファイルは編集しない。
    """
    path = Path(__file__).resolve().parent.parent / "FAR後期15分移植/原板照合.py"
    spec = importlib.util.spec_from_file_location("fixed80_raw", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_base()
KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in ("H0G1", "H1G1"))
BASE.MODES = KEYS


def ceiling5(value: Decimal) -> Decimal:
    """
    機能: 保護床を5pt単位で上へ丸める。
    引数: value (Decimal) は非負の方向値差。
    返り値: Decimal は切上げ幅。
    """
    return (value / 5).to_integral_value(rounding=ROUND_CEILING) * 5


HOLD_REASON = "保持帯返済側1tick否定"
HOLD_FIELDS = ("hold_anchor", "hold_active", "hold_floor", "hold_activated_at", "hold_entry_breached", "hold_first_hit_at", "hold_first_hit_index", "hold_first_hit_line")


def hold_state(state: dict) -> tuple:
    """
    機能: 独立所有状態の保持帯snapshotを返す。
    引数: state (dict) は原板から再構築した所有。
    返り値: tuple は保存8項目と同じ順序の値。
    """
    return tuple(state[k] for k in ("anchor85", "hold_active85", "hold_floor85", "hold_at85", "hold_breached85", "hold_hit_at85", "hold_hit_index85", "hold_hit_line85"))


class Whole85(BASE.WholePosition):
    """固定80/83由来の独立所有で、旧S0G1床と保持帯固定否定を別に再構成する。"""

    def __init__(self, books: dict, audit: object) -> None:
        """
        機能: 4会計の独立台帳と利確完了量を初期化する。
        引数: books (dict) は保存結果、audit (object) は不一致台帳。
        返り値: None。利確計画を実現利益へ計上しない。
        """
        super().__init__(books, audit)
        self.books = books
        self.current_bbo = None
        self.structure_orders = {mode: {} for mode in KEYS}
        self.hold_orders = {mode: {} for mode in KEYS}
        self.floor_orders = {mode: {} for mode in KEYS}
        self.harvest = {mode: {} for mode in KEYS}
        self.harvest_filled = {mode: {} for mode in KEYS}
        self.protection = {mode: {k: 0 for k in ("正常保有原行", "正益後保有原行", "床到達原行", "125pt到達原行", "cash床原行", "返済義務原行", "予約不足原行", "予約不足数量", "利確要求義務原行", "利確要求不足原行", "利確量検査", "構造活性原行", "構造到達原行", "構造要求不足原行", "保持帯活性原行", "保持帯到達原行", "保持帯要求不足原行")} for mode in KEYS}
        self.eq = {mode: {"realized": Decimal(0), "peak": Decimal(0), "minimum": Decimal(0), "dd": Decimal(0), "worst_floating": Decimal(0)} for mode in KEYS}
        self.quote_sources85 = {}
        self.quote_sources_seen85 = set()
        first_book = next(iter(books.values()))
        for source in first_book["_audit_source_quotes85"]:
            self.quote_sources85.setdefault(source["quote"]["line"], []).append(source)
        for mode, book in books.items():
            for order in book["orders"]:
                if order["kind"] == "exit" and order["reason"] == HOLD_REASON:
                    self.hold_orders[mode].setdefault(order["request_line"], []).append(order)
                if order["kind"] == "exit" and order["reason"] in (HOLD_REASON, "共通125pt保護", "正益前ATR損失追尾", "G1建値床・ATR追尾", "G1確定益予算・ATR追尾"):
                    self.floor_orders[mode].setdefault(order["request_line"], []).append(order)
                if order["kind"] == "exit" and order["reason"] == "固定EMA構造否定":
                    self.structure_orders[mode].setdefault(order["request_line"], []).append(order)
                if order.get("harvest", False):
                    pid = order["position_id"]
                    if pid in self.harvest[mode] or order["kind"] != "exit":
                        raise ValueError("利確注文の重複又は種別不正")
                    self.harvest[mode][pid] = order

    def account_mark(self, bid: float, ask: float) -> None:
        """
        機能: 正常BBOだけで想定返済費用込みの口座評価を再構成する。
        引数: bid/ask (float) は正常原行。
        返り値: None。約定前と全約定後の両端でDDを記録する。
        """
        for mode in KEYS:
            floating = Decimal(0)
            for state in self.active[mode].values():
                price = Decimal(str(bid if state["side"] > 0 else ask))
                floating += state["remaining"] * (state["side"] * (price - state["entry"]) * 10 - 122)
            eq = self.eq[mode]
            value = eq["realized"] + floating
            eq["peak"] = max(eq["peak"], value)
            eq["minimum"] = min(eq["minimum"], value)
            eq["dd"] = max(eq["dd"], eq["peak"] - value)
            eq["worst_floating"] = min(eq["worst_floating"], floating)

    def observe_residual(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """
        機能: 元の初回単価旗検査と独立口座評価を両立する。
        引数: line/index (int)、at/bid/ask (float) は採用原行。
        返り値: None。保存旗の時刻を判定へ使わない。
        """
        if line in self.quote_sources85 and line not in self.quote_sources_seen85:
            for source in self.quote_sources85[line]:
                quote = source["quote"]
                self.audit.check("保持帯出典の物理原行時計IndexBBO", (at, index, bid, ask),
                    (quote["time"], quote["index"], quote["bid"], quote["ask"]), 原行=line, 要求時計=source["at"])
            self.quote_sources_seen85.add(line)
        # ----------------------------------------
        # 出典の照合と保有中の格子検査は別に行い、二度目のpostfill観測で出典を重複計数しません。
        for mode, book in self.books.items():
            if not book["hold_enabled"]:
                continue
            relevant = any(state["remaining"] > 0 and state["hold_active85"] for state in self.active[mode].values())
            for order in book["orders"]:
                if order["kind"] != "entry" or not order["hold_anchor"]["known"] or line <= order["request_line"] or at < order["request_time"]:
                    continue
                pending = order["status"] == "pending" or order["status"] == "filled" and line <= order["fill_line"]
                if order["status"] == "cancelled":
                    cancel_at = min(t for t in book["_audit_force_times85"] if t >= order["request_time"])
                    pending = at < cancel_at
                relevant = relevant or pending
            if relevant:
                self.audit.check("保持帯の保有/新規待機prefill気配は10pt格子", bid % 10 == 0 and ask % 10 == 0, True, 候補=mode, 原行=line, Index=index, 時計=at)
        self.current_bbo = (bid, ask)
        super().observe_residual(line, index, at, bid, ask)
        self.account_mark(bid, ask)

    def fill(self, mode: str, order: dict, line: int, at: float, price: float) -> None:
        """
        機能: 一致した原板約定から確定純額と利確済枚数だけを更新する。
        引数: mode/order (str/dict)、line (int)、at/price (float) は約定情報。
        返り値: None。未約定注文の予定益は加えない。
        """
        pid = order["position_id"]
        if order["kind"] == "entry":
            self.audit.check("81同時一建玉", sum(s["remaining"] for s in self.active[mode].values()), 0, 候補=mode, 実玉=pid)
        if order["kind"] == "exit":
            state = self.active[mode].get(pid)
            if state is not None:
                pieces = [c for c in self.books[mode]["closed"] if c["position_id"] == pid and c["exit_line"] == line and c["quantity"] == order["filled_quantity"] and c["reason"] == order["reason"]]
                self.audit.check("返済片の当時構造対応数", len(pieces), 1, 候補=mode, 実玉=pid)
                if len(pieces) == 1:
                    self.audit.check("返済片はfill時点の保持帯snapshot", tuple(pieces[0][k] for k in HOLD_FIELDS), hold_state(state), 候補=mode, 実玉=pid, 原行=line)
                    expected = (state["anchor83"], state["structure_active83"], state["structure_floor83"], state["structure_at83"], state["structure_breached83"], state["structure_hit_at83"], state["structure_hit_index83"])
                    observed = tuple(pieces[0][k] for k in ("structure_anchor", "structure_active", "structure_floor", "structure_activated_at", "structure_entry_breached", "structure_first_hit_at", "structure_first_hit_index"))
                    self.audit.check("返済時点の構造snapshot", observed, expected, 候補=mode, 実玉=pid)
                net = (state["side"] * (Decimal(str(price)) - state["entry"]) * 10 - 122) * order["filled_quantity"]
                self.eq[mode]["realized"] += net
        super().fill(mode, order, line, at, price)
        if order["kind"] == "entry":
            self.all[mode][pid]["floor81"] = Decimal(-125)
            self.all[mode][pid]["cash_active81"] = False
            self.all[mode][pid]["cash_floor81"] = None
            self.all[mode][pid]["cash_at81"] = None
            self.all[mode][pid]["harvest_done81"] = None
            self.all[mode][pid]["funding_failed81"] = False
            state = self.all[mode][pid]
            anchor = order["structure_anchor"]
            active = mode.startswith("S1") and anchor["known"]
            floor = state["side"] * (anchor["price"] - float(state["entry"])) if active else None
            bid, ask = self.current_bbo
            gain = state["side"] * (Decimal(str(bid if state["side"] > 0 else ask)) - state["entry"])
            state.update(anchor83=anchor, structure_active83=active, structure_floor83=floor,
                structure_at83=at if active else None, structure_breached83=active and gain <= Decimal(str(floor)),
                structure_hit_at83=None, structure_hit_index83=-1)
            hold = order["hold_anchor"]
            enabled = self.books[mode]["hold_enabled"]
            hold_active = enabled and hold["known"]
            hold_floor = state["side"] * (hold["stop_price"] - float(state["entry"])) if hold_active else None
            state.update(anchor85=hold, hold_active85=hold_active, hold_floor85=hold_floor,
                hold_at85=at if hold_active else None, hold_breached85=hold_active and gain <= Decimal(str(hold_floor)),
                hold_hit_at85=None, hold_hit_index85=-1, hold_hit_line85=0, hold_base85=Decimal(-125))
        elif order.get("harvest", False):
            self.harvest_filled[mode][pid] = self.harvest_filled[mode].get(pid, 0) + order["filled_quantity"]
            state = self.all[mode][pid]
            target = self.harvest[mode][pid]["quantity"]
            if self.harvest_filled[mode][pid] == target:
                state["harvest_done81"] = at
                state["funding_failed81"] = state["realized"] - 222 * state["remaining"] < 1

    def inspect_protection(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """
        機能: 旧ATR/G1の私有床へ保持帯床を重ね、全fill後の残玉保護と同原行予約を検査する。
        引数: line/index (int)、at/bid/ask (float) は全fill後の原行。
        返り値: None。利確完了前の実現していない予算は利用しない。
        """
        for mode in KEYS:
            counts = self.protection[mode]
            for pid, state in self.active[mode].items():
                quantity = state["remaining"]
                if quantity <= 0:
                    continue
                lot = self.saved[mode][pid]
                atr = lot["entry_atr"]
                d = Decimal(125) if atr is None else min(Decimal(125), max(Decimal(15), ceiling5(Decimal(str(atr)))))
                self.audit.check("ATR由来固定幅", Decimal(str(lot["d"])), d, 候補=mode, 実玉=pid)
                price = Decimal(str(bid if state["side"] > 0 else ask))
                gain = state["side"] * (price - state["entry"])
                flagged = state["residual_first"] is not None
                floor = max(state["hold_base85"], Decimal(-125), state["best_gain"] - d)
                structure_floor = Decimal(str(state["structure_floor83"])) if state["structure_active83"] else None
                if structure_floor is not None:
                    floor = max(floor, structure_floor)
                    counts["構造活性原行"] += 1
                    if gain <= structure_floor:
                        counts["構造到達原行"] += 1
                        if state["structure_hit_at83"] is None:
                            state["structure_hit_at83"], state["structure_hit_index83"] = at, index
                cash_active = False
                if flagged:
                    if mode[:4].endswith("G2"):
                        floor = max(floor, Decimal(0))
                    else:
                        floor = max(floor, Decimal(0))
                        harvest = self.harvest[mode].get(pid)
                        issued = harvest is not None and harvest["request_line"] <= line and harvest["request_time"] <= at
                        if not issued and self.reserved[mode][pid] < quantity:
                            counts["利確要求義務原行"] += 1
                            counts["利確要求不足原行"] += 1
                            self.audit.check("G1正益後の即時利確要求", False, True, 候補=mode, 実玉=pid, 原行=line, 時計=at)
                        if issued and harvest["request_line"] == line:
                            counts["利確要求義務原行"] += 1
                            unit = gain * 10 - 122
                            if unit <= 0:
                                self.audit.check("G1利確の現在単価strict正", float(unit), "正", 候補=mode, 実玉=pid)
                            else:
                                needed = int(((222 * quantity + 1 - state["realized"]) / (unit + 222)).to_integral_value(rounding=ROUND_CEILING))
                                target = min(quantity, max(1, needed))
                                self.audit.check("G1確定益だけの利確量", harvest["quantity"], target, 候補=mode, 実玉=pid, 原行=line)
                                self.audit.check("G1必要量と充足可否", (harvest["harvest_needed"], harvest["harvest_feasible"]), (needed, needed <= quantity), 候補=mode, 実玉=pid)
                                counts["利確量検査"] += 1
                        if harvest is not None and self.harvest_filled[mode].get(pid, 0) >= harvest["quantity"]:
                            cash = ceiling5(max(Decimal(0), (222 + (Decimal(1) - state["realized"]) / quantity) / 10))
                            floor = max(floor, cash)
                            cash_active = True
                            state["cash_floor81"] = float(cash)
                            if not state["cash_active81"]:
                                state["cash_active81"] = True
                                state["cash_at81"] = at
                state["hold_base85"] = floor
                hold_floor = Decimal(str(state["hold_floor85"])) if state["hold_active85"] else None
                hold_binding = hold_floor is not None and hold_floor > floor
                if hold_floor is not None:
                    counts["保持帯活性原行"] += 1
                    floor = max(floor, hold_floor)
                    if gain <= hold_floor:
                        counts["保持帯到達原行"] += 1
                        if state["hold_hit_at85"] is None:
                            state["hold_hit_at85"], state["hold_hit_index85"], state["hold_hit_line85"] = at, index, line
                floor = max(state["floor81"], floor)
                state["floor81"] = floor
                for order in self.structure_orders[mode].get(line, []):
                    if order["position_id"] == pid:
                        binding = structure_floor is not None and gain <= structure_floor and floor == structure_floor
                        self.audit.check("構造理由は当時の拘束床到達", binding, True, 候補=mode, 実玉=pid, 原行=line)
                        self.audit.check("構造要求に最終床を保存", order["floor"], float(floor), 候補=mode, 実玉=pid, 原行=line)
                hit, hard = gain <= floor, gain <= -125
                expected_reason = None
                if hard:
                    expected_reason = "共通125pt保護"
                elif hit:
                    expected_reason = HOLD_REASON if hold_binding else ("G1確定益予算・ATR追尾" if flagged and cash_active else "G1建値床・ATR追尾" if flagged else "正益前ATR損失追尾")
                for floor_order in self.floor_orders[mode].get(line, []):
                    if floor_order["position_id"] == pid:
                        self.audit.check("保持帯と旧床の理由優先", floor_order["reason"], expected_reason, 候補=mode, 実玉=pid, 原行=line)
                        self.audit.check("床要求に最終非緩和床", floor_order["floor"], float(floor), 候補=mode, 実玉=pid, 原行=line)
                counts["正常保有原行"] += 1
                counts["正益後保有原行"] += flagged
                counts["床到達原行"] += hit
                counts["125pt到達原行"] += hard
                counts["cash床原行"] += cash_active
                if hit or hard:
                    counts["返済義務原行"] += 1
                    shortage = max(0, quantity - self.reserved[mode][pid])
                    counts["予約不足原行"] += shortage > 0
                    counts["予約不足数量"] += shortage
                    self.audit.check("81床到達の全量予約", shortage, 0, 候補=mode, 実玉=pid, 原行=line, Index=index, 時計=at, 床=float(floor), 幅=float(gain))
                    if structure_floor is not None and gain <= structure_floor:
                        counts["構造要求不足原行"] += shortage > 0
                    if hold_floor is not None and gain <= hold_floor:
                        counts["保持帯要求不足原行"] += shortage > 0

    def mark(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """
        機能: 全fill後の全玉初回益を記録し、その独立Indexを添える。
        引数: line/index (int)、at/bid/ask (float) は採用原行。
        返り値: None。閉じた玉の最後純額を含みへ戻さない。
        """
        super().mark(line, index, at, bid, ask)
        for mode in KEYS:
            for state in self.all[mode].values():
                if state["first"] is not None and state["first"]["原行"] == line:
                    state["first"]["Index"] = index

    def result(self) -> dict:
        """
        機能: 4会計の全玉旗・口座DD・保持帯snapshotと新6集計を保存値へ独立結合する。
        引数: なし。
        返り値: dict は原板から得た玉別・口座別診断。
        """
        self.audit.check("保持帯出典の正常物理原行が全件出現", sorted(self.quote_sources_seen85), sorted(self.quote_sources85))
        output = super().result()
        for mode in KEYS:
            expected_metrics = {k: 0 for k in ("whole_profit_flags", "whole_flag_after_loss_lots", "harvest_orders", "harvest_quantity", "harvest_filled_quantity", "harvest_done_lots", "cash_floor_activated_lots", "funding_failure_lots")}
            structure_metrics = {k: 0 for k in ("structure_known_entries", "structure_unknown_entries", "structure_activated_lots", "structure_entry_breached_lots", "structure_hit_lots", "structure_exit_orders")}
            hold_metrics = {k: 0 for k in ("hold_known_entries", "hold_unknown_entries", "hold_activated_lots", "hold_entry_breached_lots", "hold_hit_lots", "hold_exit_orders")}
            for pid, state in self.all[mode].items():
                lot = self.saved[mode][pid]
                self.audit.check("保持帯の活性・床・取得時否定・postfill初回hit", tuple(lot[k] for k in HOLD_FIELDS), hold_state(state), 候補=mode, 実玉=pid)
                hold_metrics["hold_known_entries"] += state["anchor85"]["known"]
                hold_metrics["hold_unknown_entries"] += not state["anchor85"]["known"]
                hold_metrics["hold_activated_lots"] += state["hold_active85"]
                hold_metrics["hold_entry_breached_lots"] += state["hold_breached85"]
                hold_metrics["hold_hit_lots"] += state["hold_hit_at85"] is not None
                expected = (state["anchor83"], state["structure_active83"], state["structure_floor83"], state["structure_at83"], state["structure_breached83"], state["structure_hit_at83"], state["structure_hit_index83"])
                observed = tuple(lot[k] for k in ("structure_anchor", "structure_active", "structure_floor", "structure_activated_at", "structure_entry_breached", "structure_first_hit_at", "structure_first_hit_index"))
                self.audit.check("構造線と当時の活性・到達", observed, expected, 候補=mode, 実玉=pid)
                self.audit.check("最終の非緩和床", lot["floor"], float(state["floor81"]), 候補=mode, 実玉=pid)
                structure_metrics["structure_known_entries"] += state["anchor83"]["known"]
                structure_metrics["structure_unknown_entries"] += not state["anchor83"]["known"]
                structure_metrics["structure_activated_lots"] += state["structure_active83"]
                structure_metrics["structure_entry_breached_lots"] += state["structure_breached83"]
                structure_metrics["structure_hit_lots"] += state["structure_hit_at83"] is not None
                first = state["first"]
                self.audit.check("全玉初回益旗", lot["whole_flag"], first is not None, 候補=mode, 実玉=pid)
                self.audit.check("全玉初回益の原行時計Index", (lot["whole_flag_line"], lot["whole_flag_time"], lot["whole_flag_index"]),
                    (first["原行"], first["時計"], first["Index"]) if first else (0, None, 0), 候補=mode, 実玉=pid)
                order = self.harvest[mode].get(pid)
                expected_harvest = (order["id"], order["quantity"], self.harvest_filled[mode].get(pid, 0), order["harvest_needed"], order["harvest_feasible"], order["request_time"], state["harvest_done81"]) if order else ("", 0, 0, 0, False, None, None)
                self.audit.check("利確の計画と実完了", tuple(lot[k] for k in ("harvest_order_id", "harvest_target", "harvest_filled", "harvest_needed", "harvest_feasible", "harvest_at", "harvest_done_at")), expected_harvest, 候補=mode, 実玉=pid)
                self.audit.check("確定後だけのcash床", tuple(lot[k] for k in ("cash_floor_active", "cash_floor", "cash_floor_at", "funding_failed")),
                    (state["cash_active81"], state["cash_floor81"], state["cash_at81"], state["funding_failed81"]), 候補=mode, 実玉=pid)
                expected_metrics["whole_profit_flags"] += first is not None
                expected_metrics["whole_flag_after_loss_lots"] += first is not None and state["remaining"] == 0 and state["realized"] < 0
                expected_metrics["harvest_orders"] += order is not None
                expected_metrics["harvest_quantity"] += order["quantity"] if order else 0
                expected_metrics["harvest_filled_quantity"] += self.harvest_filled[mode].get(pid, 0)
                expected_metrics["harvest_done_lots"] += state["harvest_done81"] is not None
                expected_metrics["cash_floor_activated_lots"] += state["cash_active81"]
                expected_metrics["funding_failure_lots"] += state["funding_failed81"]
            eq = self.eq[mode]
            metrics = self.books[mode]["metrics"]
            structure_metrics["structure_exit_orders"] = sum(o["reason"] == "固定EMA構造否定" for o in self.books[mode]["orders"])
            for name, expected in structure_metrics.items():
                self.audit.check("構造集計:" + name, metrics[name], expected, 候補=mode)
            hold_metrics["hold_exit_orders"] = sum(o["kind"] == "exit" and o["reason"] == HOLD_REASON for o in self.books[mode]["orders"])
            for name, expected in hold_metrics.items():
                self.audit.check("保持帯集計:" + name, metrics[name], expected, 候補=mode)
            if mode[:4].endswith("G2"):
                self.audit.check("G2は未確定益予算も部分利確もなし", sum(expected_metrics[k] for k in ("harvest_orders", "harvest_quantity", "harvest_filled_quantity", "harvest_done_lots", "cash_floor_activated_lots", "funding_failure_lots")), 0, 候補=mode)
            for name, expected in expected_metrics.items():
                self.audit.check("81予算集計:" + name, metrics[name], expected, 候補=mode)
            for key, field in (("peak", "equity_peak_yen"), ("minimum", "min_equity_yen"), ("dd", "max_drawdown_yen"), ("worst_floating", "worst_floating_yen")):
                self.audit.check("独立口座:" + key, float(eq[key]), metrics[field], 候補=mode)
        return output


BASE.WholePosition = Whole85


def bind_structure(saved: dict, audit: object) -> None:
    """
    機能: 構造価格線を新規要求時の保存確定EMAへ結び、後の移動を拒否する。
    引数: saved (dict) は一場4会計、audit (object) は独立差分台帳。
    返り値: None。元EMA系列の再計算はせず当時snapshotとの同一性を検査する。
    """
    grids = {g["at"]: g for g in saved["grid_decisions"]}
    audit.check("単一B1定時の重複なし", len(grids), len(saved["grid_decisions"]))
    for at, grid in grids.items():
        technical = grid["decision"]["technical"]
        anchor = grid["structure_anchor"]
        known = technical["exit_known"] and BASE.finite(technical["ema8_3"]) and technical["ema8_3"] > 0 and BASE.finite(technical["bar3_end"]) and technical["bar3_end"] > 0 and technical["bar3_end"] <= at and at-technical["bar3_end"] <= 180
        audit.check("要求時EMA線の個別既知性", anchor["known"], known, 時計=at)
        audit.check("要求時EMA価格と公開時計", (anchor["price"], anchor["at"], anchor["bar_end"]),
            (technical["ema8_3"], at, technical["bar3_end"]) if known else (0, 0, 0), 時計=at)
    for mode, book in saved["books"].items():
        origins = {}
        for order in book["orders"]:
            if order["kind"] == "entry":
                anchor = grids[order["request_time"]]["structure_anchor"]
                audit.check("新規要求と当時EMA線", order["structure_anchor"], anchor, 候補=mode, 注文=order["id"])
                audit.check("未約定新規は構造床未活性", (order["structure_active"], order["structure_floor"]), (False, None), 候補=mode, 注文=order["id"])
                origins[order["position_id"]] = anchor
        for lot in book["lots"]:
            audit.check("実新規へ固定線を継承", lot["structure_anchor"], origins[lot["id"]], 候補=mode, 実玉=lot["id"])
        for order in book["orders"]:
            if order["kind"] == "exit":
                anchor = origins[order["position_id"]]
                active = mode.startswith("S1") and anchor["known"]
                lot = next(p for p in book["lots"] if p["id"] == order["position_id"])
                floor = lot["side"] * (anchor["price"] - lot["entry_price"]) if active else None
                audit.check("返済要求に固定線と床を継承", (order["structure_anchor"], order["structure_active"], order["structure_floor"]), (anchor, active, floor), 候補=mode, 注文=order["id"])


def barrier_valid(point: dict, current: dict) -> bool:
    """
    機能: 当時の既知数量回復点の価格・時計・別系統番号を検査する。
    引数: point/current (dict) は回復点と元特徴。
    返り値: bool は未知点又は未来・不正値のない既知点なら真。
    """
    return not point["known"] or (BASE.finite(point["price"]) and point["price"] > 0 and BASE.finite(point["time"]) and point["time"] <= current["time"] and 0 <= point["index"] <= current["source_index"] and 0 <= point["event"] <= current["night"]["price_event"])


def barrier_fresh(point: dict, at: float, current: dict) -> bool:
    """
    機能: 旧82と同じ60秒・32更新以内の回復点を判定する。
    引数: point (dict)、at (float)、current (dict) は点・要求時計・当時特徴。
    返り値: bool は当時までのfresh既知点なら真。
    """
    return point["known"] and barrier_valid(point, current) and point["time"] <= at and at - point["time"] <= 60 and current["night"]["price_event"] - point["event"] <= 32


def bind_hold(saved: dict, audit: object) -> None:
    """
    機能: 保存した当時C0出典から保持帯価格線と継承を別式で再構成する。
    引数: saved (dict) は一場、audit (object) は独立差分台帳。
    返り値: None。出生時BBOと確認時原板を同値にしない。
    """
    grids = {g["at"]: g for g in saved["grid_decisions"]}
    for at, grid in grids.items():
        assert BASE.finite(at), "保持帯の要求時計が非有限"
        actual = grid["hold_anchor"]
        expected = {"known": False, "kind": "E08保持帯返済側1tick", "rule_version": 1, "at": 0, "side": 0, "quote_time": 0, "quote_index": 0, "source_line": 0, "feature_index": 0, "price_event": 0, "hold_id": 0, "hold_side": 0, "hold_bid": 0, "hold_ask": 0, "hold_time": 0, "hold_index": 0, "hold_event": 0, "tick": 10, "stop_price": 0, "reason": "当時のC0候補がないため保持帯線は未使用"}
        if grid["candidate_accepted"]:
            d, side = grid["decision"], grid["policies"]["C0"]["side"]
            q, c = d["quote"], d["evidence"]
            n = c["night"]
            h = n["buy" if side > 0 else "sell"]
            opposite = n["sell" if side > 0 else "buy"]
            assert side in (1, -1) and grid["clock_allowed"] and grid["policies"]["C0"]["allowed"]
            assert q["valid"] and q["index"] >= 0 and c["source_index"] >= 0 and 0 < q["bid"] < q["ask"]
            assert c["reference"] == "NK225" and c["time"] == q["time"] and q["time"] <= c["received"] <= at and c["source_line"] == q["line"] > 0
            assert all(BASE.finite(v) for v in (q["time"], q["last"], q["bid"], q["ask"], c["time"], c["received"], n["time"], n["band"]["time"], n["band"]["start_time"], h["time"]))
            assert c["last"] == q["last"] > 0 and c["bid"] == q["bid"] and c["ask"] == q["ask"]
            assert n["available"] and n["known"] and not n["invalid"] and n["window"] == "E08" and n["time"] == c["time"] and n["index"] == c["source_index"]
            assert n["band"]["known"] and n["band"]["index"] == c["source_index"] and 0 <= n["band"]["start_index"] <= c["source_index"]
            assert n["band"]["time"] == c["time"] and n["band"]["start_time"] <= c["time"]
            assert h["active"] and not h["pressured"] and h["side"] == side and h["id"] > 0 and h["ask"] > h["bid"]
            assert 0 <= at - q["time"] <= 15 and 0 <= at - h["time"] <= 60 and h["time"] <= c["time"]
            assert 0 <= h["index"] <= c["source_index"] and 0 <= h["event"] <= n["price_event"] and n["price_event"] - h["event"] <= 32
            assert side * (q["bid"] - h["bid"]) >= 0 and side * (q["ask"] - h["ask"]) >= 0
            assert all(barrier_valid(point, c) for point in (h["barrier"], h["support"], opposite["support"]))
            liquidation = q["bid"] if side > 0 else q["ask"]
            passed = not barrier_fresh(h["barrier"], at, c) or side * (liquidation - h["barrier"]["price"]) >= 10
            pressured = opposite["active"] and opposite["quantity_support"] and barrier_fresh(opposite["support"], at, c) and BASE.finite(opposite["time"]) and 0 <= at - opposite["time"] <= 60 and 0 <= opposite["index"] <= c["source_index"] and 0 <= opposite["event"] <= n["price_event"] and n["price_event"] - opposite["event"] <= 32
            assert passed and not pressured, "保持帯の反対圧力が解消していない"
            stop = h["bid"] - 10 if side > 0 else h["ask"] + 10
            assert all(BASE.finite(p) and p > 0 and p % 10 == 0 for p in (h["bid"], h["ask"], q["bid"], q["ask"], stop))
            expected.update(known=True, at=at, side=side, quote_time=q["time"], quote_index=q["index"], source_line=q["line"], feature_index=c["source_index"], price_event=n["price_event"], hold_id=h["id"], hold_side=h["side"], hold_bid=h["bid"], hold_ask=h["ask"], hold_time=h["time"], hold_index=h["index"], hold_event=h["event"], stop_price=stop, reason="新規要求時点のfreshなE08同方向保持帯の返済側1tick否定")
        audit.check("保持帯線は当時出典と停止式の全field一致", actual, expected, 時計=at)
    for key, book in saved["books"].items():
        enabled = key.startswith("H1G1_")
        origins = {}
        for order in book["orders"]:
            if order["kind"] == "entry":
                anchor = grids[order["request_time"]]["hold_anchor"]
                audit.check("新規要求と当時HoldAnchor", order["hold_anchor"], anchor, 候補=key)
                audit.check("未約定新規の保持帯は未活性", (order["hold_active"], order["hold_floor"]), (False, None), 候補=key)
                origins[order["position_id"]] = anchor
        for lot in book["lots"]:
            audit.check("実新規の保持帯出典を固定継承", lot["hold_anchor"], origins[lot["id"]], 候補=key)
        for order in book["orders"]:
            if order["kind"] == "exit":
                lot = next(p for p in book["lots"] if p["id"] == order["position_id"])
                anchor = origins[order["position_id"]]
                active = enabled and anchor["known"]
                floor = lot["side"] * (anchor["stop_price"] - lot["entry_price"]) if active else None
                audit.check("返済要求の保持帯出典と実建値床", (order["hold_anchor"], order["hold_active"], order["hold_floor"]), (anchor, active, floor), 候補=key)


def inspect_one(args: tuple[str, str, dict]) -> dict:
    """
    機能: 一場の原板本文を1回走査し、4会計の価格・所有・保持帯固定否定と出典BBOを照合する。
    引数: args (tuple) は結果根・入力根・一場台帳。
    返り値: dict は差分台帳と小型診断。新しい売買は生成しない。
    """
    result_root, data_root, entry = args
    path = Path(result_root) / f"{entry['id']}.json"
    result = BASE.read_json(path)
    before = BASE.sha(path)
    audit = BASE.Audit()
    if set(result["books"]) != set(KEYS):
        raise ValueError("85の4会計対象に過不足")
    bind_structure(result, audit)
    bind_hold(result, audit)
    normalized = deepcopy(result)
    source_quotes = [{"at": g["at"], "quote": g["decision"]["quote"]} for g in result["grid_decisions"] if g["candidate_accepted"]]
    force_times = [BASE.bounds(result["session"])[1] - 600]
    quiet = [g["at"] for g in result["grid_decisions"] if g["window"] == "静観"]
    if quiet:
        force_times.append(min(quiet))
    for key, book in normalized["books"].items():
        expected, delay = key.split("_D")
        enabled = expected == "H1G1"
        if book["mode"] != "S0G1" or type(book["hold_enabled"]) is not bool or book["hold_enabled"] != enabled or book["fill_delay_seconds"] != int(delay) or any(t["method_id"] != "S0G1" for t in book["trades"]):
            raise ValueError("85の外政策/内部S0G1/保持帯設定/遅延が不整合")
        book["mode"] = key
        book["_audit_force_times85"] = force_times
        book["_audit_source_quotes85"] = source_quotes
        for trade in book["trades"]:
            trade["method_id"] = key
    for info in entry["files"].values():
        BASE.verify_file(Path(data_root), info)
    market = Path(data_root) / entry["files"]["NK225_book"]["path"]
    summary = BASE.inspect_session(market, entry["id"], normalized, audit, True)
    for info in entry["files"].values():
        BASE.verify_file(Path(data_root), info)
    if BASE.sha(path) != before:
        raise ValueError("監査中の保存結果変更")
    return {"session": entry["id"], "再生結果SHA256": before, "照合項目数": audit.checks, "不一致数": audit.errors, "不一致": audit.details, "診断": summary}


def main() -> None:
    """
    機能: 明示された固定66場を独立workerで監査する。
    引数: --results/--manifest/--out (Path)、--workers (int) は対象と並列数。
    返り値: None。差分があれば証拠を保存して非0終了する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("既存監査は上書きしません")
    ledger = BASE.read_json(args.manifest)
    assert len(ledger["sessions"]) == 66 and 1 <= args.workers <= 16
    tasks = [(str(args.results.resolve()), ledger["source_root"], entry) for entry in ledger["sessions"]]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(inspect_one, tasks))
    errors = [error for row in rows for error in row["不一致"]]
    error_count = sum(row["不一致数"] for row in rows)
    value = {"試行": 85, "成功": error_count == 0, "場数": len(rows), "不一致数": error_count, "照合項目数": sum(r["照合項目数"] for r in rows),
        "入力台帳SHA256": BASE.sha(args.manifest), "固定80監査SHA256": BASE.sha(Path(__file__).resolve().parent.parent / "FAR後期15分移植/原板照合.py"),
        "固定83監査SHA256": BASE.sha(Path(__file__).resolve().parent.parent / "構造否定と利益配分/原板監査.py"),
        "監査コードSHA256": BASE.sha(Path(__file__)), "新売買再生": 0, "不一致": errors, "対象場": rows}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "場数", "不一致数", "照合項目数")}, ensure_ascii=False))
    if error_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
