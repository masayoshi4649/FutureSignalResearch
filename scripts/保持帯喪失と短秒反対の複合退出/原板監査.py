"""86の旧G1規範と当原行の複合退出を、独立短秒履歴を含む2走査で照合する。"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT / "scripts/保持帯の返済側固定否定/原板監査.py"
OLD_SHA = "e11a83cc06c7f9a274fcf4f32f0e117776a3f90c88b96f0b1e7a758900991575"
KEYS = tuple(f"{m}_D{d}" for d in (0, 1) for m in ("J0G1", "J1G1"))
COUNT_KEYS = ("normal_quotes", "price_not_breached_short_known", "price_not_breached_short_unknown", "price_breached_short_unknown", "price_breached_not_opposed", "confirmed")
FIRST_KEYS = ("confirm_first_price_breach", "confirm_first_unknown", "confirm_first_confirmed")
REASON = "保持帯両気配1tick・短秒反対確認"
ACTIVE_CACHE = {}
ACTIVE_REPORT = {}


def load_old() -> object:
    """
    機能: 停止85の原板・所有・G1規範を変更せず読み込む。
    引数: なし。既知のSHA256へ結ぶ。
    返り値: object は固定モジュール。
    """
    import hashlib
    assert hashlib.sha256(OLD_PATH.read_bytes()).hexdigest() == OLD_SHA
    spec = importlib.util.spec_from_file_location("fixed85_raw_for86", OLD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.KEYS = KEYS
    module.BASE.MODES = KEYS
    return module


OLD = load_old()
BASE = OLD.BASE


def empty_counts() -> dict:
    """
    機能: 相互排他的な5群と全分母を初期化する。
    引数: なし。
    返り値: dict は毎回独立した6整数。
    """
    return dict.fromkeys(COUNT_KEYS, 0)


def count_evidence(counts: dict, evidence: dict) -> None:
    """
    機能: 当時の位置と既知性を5群の一つへ加える。
    引数: counts/evidence (dict) は累計と当原行値。
    返り値: None。未知を反対進行へ変換しない。
    """
    counts["normal_quotes"] += 1
    if not evidence["price_breached"]:
        key = "price_not_breached_short_known" if evidence["short_known"] else "price_not_breached_short_unknown"
    elif not evidence["short_known"]:
        key = "price_breached_short_unknown"
    elif not evidence["opposed"]:
        key = "price_breached_not_opposed"
    else:
        key = "confirmed"
    counts[key] += 1


class ShortHistory:
    """有効LastがSourceへ渡る経路だけで340秒の中央値・異常累計を独立追跡する。"""

    def __init__(self) -> None:
        """
        機能: 場ごとのSource時系列を初期化する。
        引数: なし。
        返り値: None。前場の短秒履歴は持たない。
        """
        self.valid = deque()
        self.bad = 0
        self.previous = None
        self.index = -1

    def observe(self, at: float, bid: float, ask: float) -> None:
        """
        機能: 有効Last行の価格中央と異常累計を進める。
        引数: at/bid/ask (float) は当原行の価格時計と気配。
        返り値: None。異常BBOも時計・累計へ含める。
        """
        self.index += 1
        good = 0 < bid < ask
        if not good or self.previous is not None and at - self.previous > 15:
            self.bad += 1
        self.previous = at
        if good:
            self.valid.append((at, bid + (ask - bid) / 2, self.bad))
        while self.valid and self.valid[0][0] < at - 340:
            self.valid.popleft()

    def view(self, at: float, mid: float) -> dict:
        """
        機能: 5/15秒の最新正常過去端から実経過秒速度を再構成する。
        引数: at/mid (float) は正常な当時点。
        返り値: dict はSourceと同じ窓情報。保存Knownを参照しない。
        """
        rows = list(self.valid)
        result = {"time": at, "mid": mid}
        for h, name in ((5, "five"), (15, "fifteen")):
            value = {"known": False, "move": 0, "speed": 0, "elapsed": 0, "endpoint": 0, "delay": 0, "reason": "過去端不足"}
            j = bisect_right(rows, at - h, key=lambda row: row[0]) - 1
            if j >= 0:
                endpoint, old_mid, bad = rows[j]
                value.update(endpoint=endpoint, elapsed=at - endpoint, delay=at - h - endpoint)
                if value["delay"] > 15 or value["elapsed"] <= 0 or self.bad != bad:
                    value["reason"] = "窓内欠測又は価格時計空白"
                else:
                    move = mid - old_mid
                    value.update(known=True, move=move, speed=move / value["elapsed"], reason="既知")
            result[name] = value
        return result


def prepare_cache(path: Path, result: dict) -> dict:
    """
    機能: 原板第1走査で短秒を作り、潜在保有区間と候補出典だけをメモリへ残す。
    引数: path (Path) は固定原板、result (dict) は保存結果。
    返り値: dict は物理行別出典。原板・巨大系列を正式保存しない。
    """
    intervals, targets = [], set()
    for book in result["books"].values():
        for lot in book["lots"]:
            pieces = [row["exit_line"] for row in book["closed"] if row["position_id"] == lot["id"]]
            end = max(pieces) if lot["quantity"] == 0 and pieces else float("inf")
            intervals.append((lot["entry_line"], end))
    for grid in result["grid_decisions"]:
        if grid["candidate_accepted"]:
            targets.add(grid["decision"]["quote"]["line"])
    intervals.sort()
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    start, end = BASE.bounds(result["session"])
    previous, index, cursor = start, -1, 0
    history, output = ShortHistory(), {}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line, text in enumerate(stream, 1):
            row = json.loads(text, parse_constant=BASE.bad_constant)
            at = BASE.clock(row.get("CurrentPriceTime"))
            if at is None or not start <= at < end or at < previous:
                continue
            previous, index = at, index + 1
            last = BASE.go_number(row.get("CurrentPrice"))
            bid = BASE.go_number((row.get("Buy1") or {}).get("Price"))
            ask = BASE.go_number((row.get("Sell1") or {}).get("Price"))
            if last <= 0:
                continue
            history.observe(at, bid, ask)
            while cursor < len(merged) and line > merged[cursor][1]:
                cursor += 1
            needed = line in targets or cursor < len(merged) and merged[cursor][0] <= line <= merged[cursor][1]
            if needed and 0 < bid < ask:
                output[line] = {"at": at, "quote_index": index, "source_line": line, "feature_index": history.index, "source_time": at, "received": at,
                    "last": last, "bid": bid, "ask": ask, "short": history.view(at, bid + (ask - bid) / 2)}
    return output


def evidence_at(base: dict, side: int, anchor: dict) -> dict:
    """
    機能: 原板の当時短秒と要求時帯から複合成立を別式で構成する。
    引数: base/anchor (dict) は当原行と凍結出典、side (int) は±1。
    返り値: dict は16tagの当原行証拠。
    """
    value = {"rule_version": 1, **deepcopy(base)}
    short = value["short"]
    price = side * (value["bid"] - anchor["hold_bid"]) <= -10 and side * (value["ask"] - anchor["hold_ask"]) <= -10
    known = short["five"]["known"] and short["fifteen"]["known"]
    opposed = known and side * short["five"]["speed"] < 0 and side * short["fifteen"]["speed"] < 0
    reason = "保持帯両気配1tick否定は未成立"
    if price:
        reason = "保持帯両気配1tick成立・短秒未知" if not known else "保持帯両気配1tick成立・短秒の両反対は不成立" if not opposed else REASON
    value.update(price_breached=price, short_known=known, opposed=opposed, confirmed=price and opposed, reason=reason)
    return value


def validate_new_types(saved: dict) -> None:
    """
    機能: Pythonのboolと整数の同値比較で保存型の破損を見逃さない。
    引数: saved (dict) は新4会計の保存値。
    返り値: None。新整数・真偽・証拠集合の不正は入力error。
    """
    evidence_keys = {"rule_version", "at", "quote_index", "source_line", "feature_index", "source_time", "received", "last", "bid", "ask", "short", "price_breached", "short_known", "opposed", "confirmed", "reason"}
    window_keys = {"known", "move", "speed", "elapsed", "endpoint", "delay", "reason"}
    for book in saved["books"].values():
        assert type(book["confirm_enabled"]) is bool
        counters = [book["metrics"]["confirm_counts"]]
        evidences = []
        for container in ("lots", "positions"):
            for row in book[container]:
                counters.append(row["confirm_counts"])
                evidences.extend(row[name] for name in FIRST_KEYS)
        for container in ("orders", "pending_entries"):
            evidences.extend(row["confirm_evidence"] for row in book[container])
        for row in book["closed"]:
            evidences.extend(row[name] for name in FIRST_KEYS)
            evidences.append(row["confirm_request_evidence"])
        assert all(set(counts) == set(COUNT_KEYS) and all(type(value) is int and value >= 0 for value in counts.values()) for counts in counters)
        assert all(type(book["metrics"][name]) is int and book["metrics"][name] >= 0 for name in ("confirm_confirmed_lots", "confirm_exit_orders", "confirm_exit_obligations", "confirm_missing_quantity"))
        for value in evidences:
            if value is None:
                continue
            assert type(value) is dict and set(value) == evidence_keys
            assert all(type(value[name]) is bool for name in ("price_breached", "short_known", "opposed", "confirmed"))
            assert all(type(value[name]) is int and value[name] >= 0 for name in ("rule_version", "quote_index", "source_line", "feature_index"))
            assert all(BASE.finite(value[name]) for name in ("at", "source_time", "received", "last", "bid", "ask")) and type(value["reason"]) is str
            short = value["short"]
            assert set(short) == {"time", "mid", "five", "fifteen"} and BASE.finite(short["time"]) and BASE.finite(short["mid"])
            for name in ("five", "fifteen"):
                window = short[name]
                assert set(window) == window_keys and type(window["known"]) is bool and type(window["reason"]) is str
                assert all(BASE.finite(window[field]) for field in ("move", "speed", "elapsed", "endpoint", "delay"))


class Whole86(OLD.Whole85):
    """固定85のG1所有へ、独立短秒と条件付き退出の規範だけを追加する。"""

    def __init__(self, books: dict, audit: object) -> None:
        """
        機能: 新退出と影観測の台帳を初期化する。
        引数: books (dict) とaudit (object) は保存会計と差分台帳。
        返り値: None。J0は旧金融のまま影観測だけ独立出力する。
        """
        super().__init__(books, audit)
        self.cache = ACTIVE_CACHE
        self.checked_prefill = set()
        self.confirm_orders_seen = {key: set() for key in KEYS}
        self.confirm_orders = {key: {} for key in KEYS}
        for key, book in books.items():
            audit.check("複合有効と外キー", (type(book["confirm_enabled"]) is bool, book["confirm_enabled"]), (True, key.startswith("J1G1")), 候補=key)
            for order in book["orders"]:
                if order["reason"] == REASON:
                    audit.check("新複合理由は有効会計の返済だけ", (order["kind"], book["confirm_enabled"]), ("exit", True), 候補=key, 注文=order["id"])
                    audit.check("複合要求は証拠を持ち撤回しない", (order["cancelled_quantity"], order["status"] != "cancelled", order["confirm_evidence"] is not None), (0, True, True), 候補=key, 注文=order["id"])
                    self.confirm_orders[key].setdefault(order["request_line"], []).append(order)
                else:
                    audit.check("旧注文・新規の複合証拠はnull", order["confirm_evidence"], None, 候補=key, 注文=order["id"])
            self.protection[key].update({name: 0 for name in ("複合成立原行", "複合要求不足原行", "複合要求不足数量")})

    def observe_residual(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """
        機能: 旧評価を保ち、J1の待機・保有prefill格子を追加確認する。
        引数: line/index (int) とat/bid/ask (float) は正常原行。
        返り値: None。全fill後の観測分母とは分ける。
        """
        super().observe_residual(line, index, at, bid, ask)
        for key, book in self.books.items():
            if not book["confirm_enabled"] or (key, line) in self.checked_prefill:
                continue
            relevant = any(state["remaining"] > 0 and state["anchor85"]["known"] for state in self.active[key].values())
            for order in book["orders"]:
                if order["kind"] != "entry" or not order["hold_anchor"]["known"] or line <= order["request_line"] or at < order["request_time"]:
                    continue
                pending = order["status"] == "pending" or order["status"] == "filled" and line <= order["fill_line"]
                if order["status"] == "cancelled":
                    cancel_at = min(t for t in book["_audit_force_times85"] if t >= order["request_time"])
                    pending = at < cancel_at
                relevant = relevant or pending
            if relevant:
                self.audit.check("複合prefillの正常気配は10pt格子", bid % 10 == 0 and ask % 10 == 0, True, 候補=key, 原行=line)
            self.checked_prefill.add((key, line))

    def fill(self, mode: str, order: dict, line: int, at: float, price: float) -> None:
        """
        機能: 返済片へfill時点の初回証拠だけを結び、実新規を初期化する。
        引数: mode/order (str/dict)、line (int)、at/price (float) は原板一致fill。
        返り値: None。同原行の後段確認や将来の確認を遡及しない。
        """
        if order["kind"] == "exit":
            state = self.active[mode].get(order["position_id"])
            pieces = [row for row in self.books[mode]["closed"] if row["position_id"] == order["position_id"] and row["exit_line"] == line and row["quantity"] == order["filled_quantity"] and row["reason"] == order["reason"]]
            self.audit.check("複合返済片の所有対応数", len(pieces), 1, 候補=mode, 原行=line)
            if state is not None and len(pieces) == 1:
                expected = tuple(state["confirm86"][name] if self.books[mode]["confirm_enabled"] else None for name in FIRST_KEYS)
                self.audit.check("返済片の初回証拠はfill前の当時状態", tuple(pieces[0][name] for name in FIRST_KEYS), expected, 候補=mode, 原行=line)
                self.audit.check("返済片は注文の複合証拠を固定継承", pieces[0]["confirm_request_evidence"], order["confirm_evidence"], 候補=mode, 原行=line)
        super().fill(mode, order, line, at, price)
        if order["kind"] == "entry":
            self.all[mode][order["position_id"]]["confirm86"] = {"counts": empty_counts(), **dict.fromkeys(FIRST_KEYS, None), "missing": 0}

    def inspect_protection(self, line: int, index: int, at: float, bid: float, ask: float) -> None:
        """
        機能: 旧G1優先を維持し、全残玉原行の確認・見逃し・新要求を独立照合する。
        引数: line/index (int) とat/bid/ask (float) は全fill後の正常原行。
        返り値: None。現在の新確認注文を旧G1履行の代用品にしない。
        """
        current_orders = {key: [o for o in self.confirm_orders[key].get(line, []) if o["request_time"] <= at] for key in KEYS}
        for key in KEYS:
            for order in current_orders[key]:
                self.reserved[key][order["position_id"]] -= order["quantity"] - order["cancelled_quantity"]
        try:
            super().inspect_protection(line, index, at, bid, ask)
        finally:
            for key in KEYS:
                for order in current_orders[key]:
                    self.reserved[key][order["position_id"]] += order["quantity"] - order["cancelled_quantity"]
        for key in KEYS:
            enabled = self.books[key]["confirm_enabled"]
            for pid, state in self.active[key].items():
                if state["remaining"] <= 0:
                    continue
                base = self.cache[line]
                self.audit.check("複合の当時出典を原板へ結合", (base["at"], base["quote_index"], base["bid"], base["ask"]), (at, index, bid, ask), 候補=key, 原行=line)
                evidence = evidence_at(base, state["side"], state["anchor85"])
                shadow = state["confirm86"]
                count_evidence(shadow["counts"], evidence)
                for name, condition in ((FIRST_KEYS[0], evidence["price_breached"]), (FIRST_KEYS[1], evidence["price_breached"] and not evidence["short_known"]), (FIRST_KEYS[2], evidence["confirmed"])):
                    if condition and shadow[name] is None:
                        shadow[name] = deepcopy(evidence)
                orders = [o for o in current_orders[key] if o["position_id"] == pid]
                newly_reserved = sum(o["quantity"] - o["cancelled_quantity"] for o in orders)
                before = self.reserved[key][pid] - newly_reserved
                expected_quantity = max(0, state["remaining"] - before) if enabled and evidence["confirmed"] else 0
                self.audit.check("複合要求の有無と旧予約優先", len(orders), int(expected_quantity > 0), 候補=key, 実玉=pid, 原行=line)
                self.audit.check("複合の未予約残量だけを要求", newly_reserved, expected_quantity, 候補=key, 実玉=pid, 原行=line)
                for order in orders:
                    self.confirm_orders_seen[key].add(order["id"])
                    self.audit.check("複合要求は当原行の独立短秒と固定帯", order["confirm_evidence"], evidence, 候補=key, 実玉=pid, 原行=line)
                    self.audit.check("複合要求で旧床を変えない", order["floor"], float(state["floor81"]), 候補=key, 実玉=pid, 原行=line)
                if enabled and evidence["confirmed"]:
                    shortage = max(0, state["remaining"] - self.reserved[key][pid])
                    shadow["missing"] += shortage
                    self.protection[key]["複合成立原行"] += 1
                    self.protection[key]["複合要求不足原行"] += shortage > 0
                    self.protection[key]["複合要求不足数量"] += shortage
                    self.audit.check("複合成立の同原行全量予約", shortage, 0, 候補=key, 実玉=pid, 原行=line)

    def result(self) -> dict:
        """
        機能: 全玉・新集計をGo保存値と照合し、J0にも独立影観測を返す。
        引数: なし。
        返り値: dict は旧全玉評価と複合規範。影観測をGooff値へ混ぜない。
        """
        output = super().result()
        for key in KEYS:
            enabled = self.books[key]["confirm_enabled"]
            self.audit.check("全複合要求を正常残玉の当原行へ結合", sorted(self.confirm_orders_seen[key]), sorted(order["id"] for orders in self.confirm_orders[key].values() for order in orders), 候補=key)
            sums, rows, firsts, missing = empty_counts(), [], 0, 0
            for pid, state in self.all[key].items():
                shadow = state["confirm86"]
                counts = shadow["counts"]
                for name in COUNT_KEYS:
                    sums[name] += counts[name]
                lot = self.saved[key][pid]
                expected = counts if enabled else empty_counts()
                self.audit.check("複合玉別5群の分母と全整数", lot["confirm_counts"], expected, 候補=key, 実玉=pid)
                self.audit.check("複合5群は全分母を分解", sum(counts[k] for k in COUNT_KEYS[1:]), counts["normal_quotes"], 候補=key, 実玉=pid)
                for name in FIRST_KEYS:
                    self.audit.check("複合玉の当時初回証拠:" + name, lot[name], shadow[name] if enabled else None, 候補=key, 実玉=pid)
                firsts += shadow[FIRST_KEYS[2]] is not None
                missing += shadow["missing"]
                rows.append({"実玉": pid, "counts": counts, **{name: shadow[name] for name in FIRST_KEYS}})
            metrics = self.books[key]["metrics"]
            expected_metrics = {"confirm_counts": sums if enabled else empty_counts(), "confirm_confirmed_lots": firsts if enabled else 0,
                "confirm_exit_orders": sum(len(orders) for orders in self.confirm_orders[key].values()), "confirm_exit_obligations": sums["confirmed"] if enabled else 0, "confirm_missing_quantity": missing if enabled else 0}
            for name, expected in expected_metrics.items():
                self.audit.check("複合集計:" + name, metrics[name], expected, 候補=key)
            ACTIVE_REPORT[key] = {"金融有効": enabled, "影観測": sums, "玉": rows, "限定": "J0の影観測は金融offの0/nullとは別。正常postfill残玉だけ、予約済みも含む。"}
        return output


BASE.WholePosition = Whole86


def inspect_one(args: tuple[str, str, dict]) -> dict:
    """
    機能: 一場の短秒準備と固定85由来の規範を2走査で結ぶ。
    引数: args (tuple) は結果根・原板根・一場台帳。
    返り値: dict は不一致・影観測。元の金融・原板を変更しない。
    """
    global ACTIVE_CACHE, ACTIVE_REPORT
    result_root, data_root, entry = args
    result_path = Path(result_root) / (entry["id"] + ".json")
    saved = BASE.read_json(result_path)
    before = BASE.sha(result_path)
    assert set(saved["books"]) == set(KEYS)
    validate_new_types(saved)
    for book in saved["books"].values():
        assert book["hold_enabled"] is False
    info = entry["files"]["NK225_book"]
    market = BASE.verify_file(Path(data_root), info)
    ACTIVE_CACHE = prepare_cache(market, saved)
    BASE.verify_file(Path(data_root), info)
    for grid in saved["grid_decisions"]:
        if not grid["candidate_accepted"]:
            continue
        quote, current = grid["decision"]["quote"], grid["decision"]["evidence"]
        source = ACTIVE_CACHE[quote["line"]]
        assert (quote["time"], quote["index"], quote["bid"], quote["ask"], quote["last"], current["source_index"], current["time"], current["received"]) == (
            source["at"], source["quote_index"], source["bid"], source["ask"], source["last"], source["feature_index"], source["source_time"], source["received"]), "候補出典の実原板Source連番・時計・価格と不整合"
    ACTIVE_REPORT = {}
    row = OLD.inspect_one(args)
    assert BASE.sha(result_path) == before
    row["診断"]["JSON本文走査回数"] = 2
    row["診断"]["短秒キャッシュ行数"] = len(ACTIVE_CACHE)
    row["診断"]["短秒規範"] = "340秒履歴、Source有効Lastだけ、正常過去端≤t−h、遅れ≤15秒、Bad累計同値。保存Knownを再利用しない。"
    row["診断"]["複合退出の独立規範"] = deepcopy(ACTIVE_REPORT)
    ACTIVE_CACHE = {}
    ACTIVE_REPORT = {}
    return row


def main() -> None:
    """
    機能: 明示された固定66場を独立workerで監査する。
    引数: --results/--manifest/--out (Path)、--workers (int) は対象と並列数。
    返り値: None。差分又は入力異常は非0終了、既存証拠は上書きしない。
    """
    parser = argparse.ArgumentParser()
    for name in ("results", "manifest", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    assert not args.out.exists() and 1 <= args.workers <= 16
    ledger = BASE.read_json(args.manifest)
    assert len(ledger["sessions"]) == 66
    tasks = [(str(args.results.resolve()), ledger["source_root"], entry) for entry in ledger["sessions"]]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(inspect_one, tasks))
    errors = sum(row["不一致数"] for row in rows)
    value = {"試行": 86, "成功": errors == 0, "場数": len(rows), "不一致数": errors, "照合項目数": sum(row["照合項目数"] for row in rows),
        "入力台帳SHA256": BASE.sha(args.manifest), "固定85監査SHA256": OLD_SHA, "監査コードSHA256": BASE.sha(Path(__file__)),
        "固定80監査SHA256": BASE.sha(ROOT / "scripts/FAR後期15分移植/原板照合.py"), "固定83監査SHA256": BASE.sha(ROOT / "scripts/構造否定と利益配分/原板監査.py"),
        "原板本文走査回数毎場": 2, "新売買再生": 0, "不一致": [error for row in rows for error in row["不一致"]], "対象場": rows}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "場数", "不一致数", "照合項目数")}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
