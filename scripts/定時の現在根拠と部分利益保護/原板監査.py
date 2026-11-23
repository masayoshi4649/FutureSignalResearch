"""81の注文、全玉損益、ATR床と確定予算を原板から独立に照合する。"""

from __future__ import annotations

import argparse
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
KEYS = tuple(f"{mode}_D{delay}" for delay in (0, 1) for mode in ("B0G0", "B0G1", "B1G0", "B1G1"))
BASE.MODES = KEYS


def ceiling5(value: Decimal) -> Decimal:
    """
    機能: 保護床を5pt単位で上へ丸める。
    引数: value (Decimal) は非負の方向値差。
    返り値: Decimal は切上げ幅。
    """
    return (value / 5).to_integral_value(rounding=ROUND_CEILING) * 5


class Whole81(BASE.WholePosition):
    """原板を用いた独立所有に、81固有の予算とATR規範を追加する。"""

    def __init__(self, books: dict, audit: object) -> None:
        """
        機能: 8会計の独立台帳と利確完了量を初期化する。
        引数: books (dict) は保存結果、audit (object) は不一致台帳。
        返り値: None。利確計画を実現利益へ計上しない。
        """
        super().__init__(books, audit)
        self.books = books
        self.harvest = {mode: {} for mode in KEYS}
        self.harvest_filled = {mode: {} for mode in KEYS}
        self.protection = {mode: {k: 0 for k in ("正常保有原行", "正益後保有原行", "床到達原行", "125pt到達原行", "cash床原行", "返済義務原行", "予約不足原行", "予約不足数量", "利確要求義務原行", "利確要求不足原行", "利確量検査")} for mode in KEYS}
        self.eq = {mode: {"realized": Decimal(0), "peak": Decimal(0), "minimum": Decimal(0), "dd": Decimal(0), "worst_floating": Decimal(0)} for mode in KEYS}
        for mode, book in books.items():
            for order in book["orders"]:
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
        elif order.get("harvest", False):
            self.harvest_filled[mode][pid] = self.harvest_filled[mode].get(pid, 0) + order["filled_quantity"]
            state = self.all[mode][pid]
            target = self.harvest[mode][pid]["quantity"]
            if self.harvest_filled[mode][pid] == target:
                state["harvest_done81"] = at
                state["funding_failed81"] = state["realized"] - 222 * state["remaining"] < 1

    def inspect_protection(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """
        機能: ATR損失追尾とG0/G1の利益床で同原行の全量予約を要求する。
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
                floor = max(state["floor81"], Decimal(-125), state["best_gain"] - d)
                cash_active = False
                if flagged:
                    if mode[:4].endswith("G0"):
                        floor = max(floor, Decimal(20))
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
                state["floor81"] = floor
                hit, hard = gain <= floor, gain <= -125
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
        機能: 全玉旗と口座DDを保存値へ独立結合する。
        引数: なし。
        返り値: dict は原板から得た玉別・口座別診断。
        """
        output = super().result()
        for mode in KEYS:
            expected_metrics = {k: 0 for k in ("whole_profit_flags", "whole_flag_after_loss_lots", "harvest_orders", "harvest_quantity", "harvest_filled_quantity", "harvest_done_lots", "cash_floor_activated_lots", "funding_failure_lots")}
            for pid, state in self.all[mode].items():
                lot = self.saved[mode][pid]
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
            for name, expected in expected_metrics.items():
                self.audit.check("81予算集計:" + name, metrics[name], expected, 候補=mode)
            for key, field in (("peak", "equity_peak_yen"), ("minimum", "min_equity_yen"), ("dd", "max_drawdown_yen"), ("worst_floating", "worst_floating_yen")):
                self.audit.check("独立口座:" + key, float(eq[key]), metrics[field], 候補=mode)
        return output


BASE.WholePosition = Whole81


def inspect_one(args: tuple[str, str, dict]) -> dict:
    """
    機能: 一場だけ原板を1回読み、8会計の価格・所有・床を照合する。
    引数: args (tuple) は結果根・入力根・一場台帳。
    返り値: dict は差分台帳と小型診断。新しい売買は生成しない。
    """
    result_root, data_root, entry = args
    path = Path(result_root) / f"{entry['id']}.json"
    result = BASE.read_json(path)
    before = BASE.sha(path)
    audit = BASE.Audit()
    normalized = deepcopy(result)
    for key, book in normalized["books"].items():
        expected, delay = key.split("_D")
        if book["mode"] != expected or book["fill_delay_seconds"] != int(delay) or any(t["method_id"] != expected for t in book["trades"]):
            raise ValueError("81会計キーと実手法が不一致")
        book["mode"] = key
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
    value = {"試行": 81, "成功": error_count == 0, "場数": len(rows), "不一致数": error_count, "照合項目数": sum(r["照合項目数"] for r in rows),
        "入力台帳SHA256": BASE.sha(args.manifest), "固定80監査SHA256": BASE.sha(Path(__file__).resolve().parent.parent / "FAR後期15分移植/原板照合.py"),
        "監査コードSHA256": BASE.sha(Path(__file__)), "新売買再生": 0, "不一致": errors, "対象場": rows}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "場数", "不一致数", "照合項目数")}, ensure_ascii=False))
    if error_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
