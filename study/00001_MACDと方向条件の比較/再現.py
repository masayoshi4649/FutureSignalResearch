"""MACDの入口条件を逐次比較し、約定・品質・損益を保存する研究用計算。"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# ----------------------------------------
# 入力と指標の共通処理

JST = timezone(timedelta(hours=9))
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "work" / "pythonlibs"))
try:
    import orjson
except ImportError:
    orjson = None


def parse_json(line: bytes) -> dict[str, Any]:
    """JSON行を解析する。

    引数: line (bytes) はUTF-8のJSON。
    返り値: dict[str, Any] は解析結果。不正JSONは例外にする。
    """
    return orjson.loads(line) if orjson else json.loads(line)


def write_json(path: Path, data: Any) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、data (Any) はJSON化可能な値。
    返り値: None。
    """
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """小さな集計表をCSVへ保存する。

    引数: path (Path) は保存先、rows (list[dict[str, Any]]) は同じ列の行。
    返り値: None。空の場合は空ファイルにする。
    """
    with path.open("w", encoding="utf-8", newline="") as target:
        if rows:
            writer = csv.DictWriter(target, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def session_times(name: str) -> tuple[datetime, datetime, datetime, datetime]:
    """開始・ザラバ終了・新規停止・返済要求の時刻を求める。

    引数: name (str) は開始日基準のセッション名。
    返り値: tuple[datetime, datetime, datetime, datetime] はJSTの四時刻。
    """
    day, part = name.split("_")
    date = datetime.fromisoformat(day).replace(tzinfo=JST)
    if part == "Day":
        return (date.replace(hour=8, minute=45), date.replace(hour=15, minute=40),
                date.replace(hour=15, minute=25), date.replace(hour=15, minute=35))
    following = date + timedelta(days=1)
    return (date.replace(hour=17), following.replace(hour=5, minute=55),
            following.replace(hour=5, minute=40), following.replace(hour=5, minute=50))


def positive(value: Any) -> bool:
    """有限の正数か判定する。

    引数: value (Any) は検査する値。
    返り値: bool は正の数値である場合に真。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


@dataclass
class Average:
    """単純平均で初期化し、EMAまたはWilder平均を更新する状態。"""

    length: int
    alpha: float
    total: float = 0.0
    count: int = 0
    value: float | None = None

    def update(self, value: float) -> float | None:
        """一つの入力で平滑値を更新する。

        引数: value (float) は今回の有効入力。
        返り値: float | None は初期化後の値、または必要本数不足。
        """
        if self.value is None:
            self.total += value
            self.count += 1
            if self.count == self.length:
                self.value = self.total / self.length
        else:
            self.value += self.alpha * (value - self.value)
        return self.value


class Indicators:
    """同一限月の確定足だけを順に処理する指標の状態。"""

    def __init__(self) -> None:
        """指標を未初期化状態にする。

        引数: なし。
        返り値: None。
        """
        self.fast = Average(12, 2 / 13)
        self.slow = Average(26, 2 / 27)
        self.signal = Average(9, 2 / 10)
        self.trend = Average(60, 2 / 61)
        self.up = Average(14, 1 / 14)
        self.down = Average(14, 1 / 14)
        self.atr = Average(14, 1 / 14)
        self.previous_close: float | None = None
        self.previous: dict[str, Any] | None = None

    def update(self, bar: dict[str, Any]) -> dict[str, Any]:
        """確定足から指標と交差を計算する。

        引数: bar (dict[str, Any]) は高安終値を持つ確定足。
        返り値: dict[str, Any] は指標値、有効性、交差方向。
        """
        close = bar["close"]
        fast, slow, trend = self.fast.update(close), self.slow.update(close), self.trend.update(close)
        macd = None if fast is None or slow is None else fast - slow
        signal = None if macd is None else self.signal.update(macd)
        rsi = None
        if self.previous_close is not None:
            delta = close - self.previous_close
            up = self.up.update(max(delta, 0))
            down = self.down.update(max(-delta, 0))
            self.atr.update(max(bar["high"] - bar["low"], abs(bar["high"] - self.previous_close), abs(bar["low"] - self.previous_close)))
            if up is not None and down is not None and up + down > 0:
                rsi = 100 * up / (up + down)
        ready = all(value is not None for value in (macd, signal, trend, rsi, self.atr.value))
        result = {"close": close, "macd": macd, "signal": signal, "ema60": trend,
                  "rsi": rsi, "atr": self.atr.value, "ready": ready, "cross": 0, "trend_direction": 0}
        previous = self.previous
        if ready and previous and previous["ready"]:
            if previous["macd"] <= previous["signal"] and macd > signal:
                result["cross"] = 1
            elif previous["macd"] >= previous["signal"] and macd < signal:
                result["cross"] = -1
            if close > trend and trend > previous["ema60"]:
                result["trend_direction"] = 1
            elif close < trend and trend < previous["ema60"]:
                result["trend_direction"] = -1
        self.previous_close, self.previous = close, result
        return result


# ----------------------------------------
# 注文と建玉の逐次再生

@dataclass
class Strategy:
    """一つの候補の建玉、注文、会計と監査用記録。"""

    method: str
    symbol: str
    session: str
    product: dict[str, Any]
    cutoff: float
    force: float
    end: float
    position: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    fills: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    cash: float = 0.0
    peak: float = 0.0
    minimum: float = 0.0
    drawdown: float = 0.0
    last_exit_bucket: int | None = None
    cancellations: int = 0
    max_exit_delay: float = 0.0

    def expire_entry(self, now: float) -> None:
        """新規要求の期限を、次の判断より先に適用する。

        引数: now (float) は現在の価格時計秒。
        返り値: None。失効した新規だけを取り消し、返済は維持する。
        """
        if self.pending and self.pending["kind"] == "entry" and (now >= self.cutoff or now - self.pending["time"] > 30):
            self.pending = None
            self.cancellations += 1

    def request(self, kind: str, side: int, now: float, line: int, reason: str, atr: float | None = None) -> None:
        """一つの新規または返済要求を登録する。

        引数: kind (str) はentry/exit、side (int) は建玉方向、now (float) は価格時計秒、
        line (int) は原板物理行、reason (str) は理由、atr (float | None) は入口のATR。
        返り値: None。既存返済は重複させず、より高い優先理由だけ更新する。
        """
        priorities = {"期限返済": 3, "保護発動": 2, "逆交差": 1}
        if self.pending and self.pending["kind"] == "exit":
            if priorities.get(reason, 0) > priorities.get(self.pending["reason"], 0):
                self.pending["reason"] = reason
            return
        self.pending = {"kind": kind, "side": side, "time": now, "line": line, "reason": reason, "atr": atr}
        self.decisions.append({"判断時刻": datetime.fromtimestamp(now, JST).isoformat(), "原板行": line,
                               "要求": kind, "方向": side, "理由": reason, "ATR": atr})

    def on_signal(self, values: dict[str, Any], now: float, line: int, bucket: int) -> None:
        """確定足の交差で共通出口と候補別入口を判定する。

        引数: values (dict[str, Any]) は確定足の指標、now (float) は判断秒、
        line (int) は判断を確認した原板行、bucket (int) は現在の5分区間番号。
        返り値: None。
        """
        self.expire_entry(now)
        cross = values["cross"]
        if not cross:
            return
        if self.position:
            if cross == -self.position["side"]:
                self.request("exit", self.position["side"], now, line, "逆交差")
            return
        if self.pending and self.pending["kind"] == "entry" and self.pending["side"] != cross:
            self.pending = None
            self.cancellations += 1
        if self.pending or not values["ready"] or now >= self.cutoff or self.last_exit_bucket == bucket:
            return
        if self.method != "MACDのみ" and values["trend_direction"] != cross:
            return
        if self.method == "方向条件とRSI" and not ((cross == 1 and values["rsi"] > 50) or (cross == -1 and values["rsi"] < 50)):
            return
        self.request("entry", cross, now, line, "交差", values["atr"])

    def mark(self, bid: float, ask: float) -> None:
        """正常板で含み込み資産と建玉の順行・逆行を更新する。

        引数: bid (float) は買気配、ask (float) は売気配。
        返り値: None。支払済み費用はcashへ一度だけ反映済み。
        """
        unrealized = 0.0
        if self.position:
            pos = self.position
            unrealized = (bid - pos["entry"]) * self.product["point_value"] if pos["side"] == 1 else (pos["entry"] - ask) * self.product["point_value"]
            pos["mfe"] = max(pos["mfe"], unrealized)
            pos["mae"] = max(pos["mae"], -unrealized)
        equity = self.cash + unrealized
        self.peak = max(self.peak, equity)
        self.minimum = min(self.minimum, equity)
        self.drawdown = max(self.drawdown, self.peak - equity)

    def on_quote(self, now: float, line: int, bucket: int, bid: float | None, ask: float | None, valid: bool) -> None:
        """期限・保護・待機注文を観測順に処理する。

        引数: now (float) は価格時計秒、line (int) は原板行、bucket (int) は5分区間、
        bid/ask (float | None) は気配、valid (bool) は正常な両気配と数量の成立。
        返り値: None。要求と同じ価格時計では約定させない。
        """
        self.expire_entry(now)
        if valid:
            self.mark(bid, ask)
        if now >= self.force and self.position:
            self.request("exit", self.position["side"], now, line, "期限返済")
        if valid and self.position:
            pos = self.position
            crossed = bid <= pos["stop"] if pos["side"] == 1 else ask >= pos["stop"]
            if crossed:
                self.request("exit", pos["side"], now, line, "保護発動")
        pending = self.pending
        if valid and pending and now < self.end and now >= pending["time"] + 1:
            side = pending["side"]
            is_entry = pending["kind"] == "entry"
            price = (ask if side == 1 else bid) if is_entry else (bid if side == 1 else ask)
            fee = self.product["fee_yen"]
            stamp = datetime.fromtimestamp(now, JST).isoformat()
            if is_entry:
                position_id = f"建玉{len(self.trades) + 1}"
                stop = price - side * 2 * pending["atr"]
                tick = self.product["tick"]
                stop = (math.floor(stop / tick) if side == 1 else math.ceil(stop / tick)) * tick
                self.position = {"id": position_id, "side": side, "entry": price, "time": now,
                                 "stop": stop, "mfe": 0.0, "mae": 0.0, "entry_line": line,
                                 "signal_time": pending["time"], "atr": pending["atr"]}
                self.cash -= fee
                fill_type = "LongN" if side == 1 else "ShortN"
            else:
                pos = self.position
                position_id = pos["id"]
                gross = side * (price - pos["entry"]) * self.product["point_value"]
                self.cash += gross - fee
                self.trades.append({"銘柄": self.symbol, "場": self.session, "手法": self.method,
                                    "建玉ID": position_id, "方向": "買い" if side == 1 else "売り",
                                    "新規時刻": datetime.fromtimestamp(pos["time"], JST).isoformat(),
                                    "返済時刻": stamp, "新規価格": pos["entry"], "返済価格": price,
                                    "数量": 1, "値幅損益円": gross, "手数料円": fee * 2, "純損益円": gross - fee * 2,
                                    "返済理由": pending["reason"], "保護価格": pos["stop"], "入口ATR": pos["atr"],
                                    "MFE円": pos["mfe"], "MAE円": pos["mae"], "保有秒": now - pos["time"],
                                    "判断から新規秒": pos["time"] - pos["signal_time"],
                                    "要求から返済秒": now - pending["time"], "新規原板行": pos["entry_line"], "返済原板行": line})
                self.max_exit_delay = max(self.max_exit_delay, now - pending["time"])
                self.position = None
                self.last_exit_bucket = bucket
                fill_type = "LongR" if side == 1 else "ShortR"
            self.fills.append({"id": f"約定{len(self.fills) + 1}", "timestamp": stamp, "type": fill_type,
                               "position_id": position_id, "price": price, "qty": 1, "fee_yen": fee,
                               "method_id": self.method, "source_line": line})
            self.pending = None
        if valid:
            self.mark(bid, ask)


# ----------------------------------------
# 原板の一回走査と出力

def process_session(path: Path, symbol: str, session: str, bank: Indicators, previous_symbol: str | None,
                    config: dict[str, Any]) -> tuple[list[Strategy], dict[str, Any], list[dict[str, Any]], str | None]:
    """原板を一度だけ読み、三候補を同じ観測で再生する。

    引数: path (Path) は原板、symbol/session (str) は対象、bank (Indicators) は過去状態、
    previous_symbol (str | None) は直前の限月コード、config (dict[str, Any]) は事前設定。
    返り値: tuple は候補状態、品質とハッシュ、確定足一覧、最終限月コード。
    """
    start, end, cutoff, force = session_times(session)
    start_s, end_s = start.timestamp(), end.timestamp()
    states = [Strategy(method, symbol, session, config["商品"][symbol], cutoff.timestamp(), force.timestamp(), end_s) for method in config["候補"]]
    quality = {"銘柄": symbol, "場": session, "入力": str(path), "ファイルバイト": path.stat().st_size,
               "原行数": 0, "時計欠測": 0, "時計後退": 0, "場外時計": 0, "非正Last": 0,
               "不正板": 0, "同時計行": 0, "足欠損数": 0, "指標リセット": 0, "最大価格時計間隔秒": 0.0,
               "最初時計": None, "最後時計": None, "限月コード": None, "銘柄名": None,
               "入力更新時刻ns": path.stat().st_mtime_ns}
    digest = hashlib.sha256()
    previous_time: float | None = None
    cached_clock, cached_seconds = None, None
    bar: dict[str, Any] | None = None
    bars: list[dict[str, Any]] = []
    last_index: int | None = None
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as source:
        for line_no, raw in enumerate(source, 1):
            digest.update(raw)
            quality["原行数"] = line_no
            if not raw.strip():
                continue
            row = parse_json(raw)
            clock = row.get("CurrentPriceTime")
            if not clock:
                quality["時計欠測"] += 1
                continue
            if clock == cached_clock:
                now = cached_seconds
            else:
                parsed_clock = datetime.fromisoformat(clock)
                if parsed_clock.utcoffset() is None:
                    raise ValueError(f"時差のない時計: {path}:{line_no}")
                now = parsed_clock.timestamp()
                cached_clock, cached_seconds = clock, now
            if now < start_s or now > end_s:
                quality["場外時計"] += 1
                continue
            if previous_time is not None and now < previous_time:
                quality["時計後退"] += 1
                continue
            if previous_time == now:
                quality["同時計行"] += 1
            if previous_time is not None:
                quality["最大価格時計間隔秒"] = max(quality["最大価格時計間隔秒"], now - previous_time)
            previous_time = now
            quality["最初時計"] = quality["最初時計"] or clock
            quality["最後時計"] = clock
            code = row.get("Symbol")
            if quality["限月コード"] is not None and code != quality["限月コード"]:
                raise ValueError(f"場内で限月が混在しました: {path}:{line_no}")
            if code != previous_symbol:
                bank.__init__()
                previous_symbol = code
                quality["指標リセット"] += 1
                bar = None
                last_index = None
            quality["限月コード"], quality["銘柄名"] = code, row.get("SymbolName")
            index = int((now - start_s) // 300)
            if bar and index != bar["index"]:
                values = bank.update(bar)
                bar["確定確認時刻"] = clock
                bar["指標有効"] = values["ready"]
                bars.append(bar)
                for state in states:
                    state.on_signal(values, now, line_no, index)
                bar = None
            last = row.get("CurrentPrice")
            if not positive(last):
                quality["非正Last"] += 1
            elif now < end_s:
                if bar is None:
                    missing = index if last_index is None else index - last_index - 1
                    if missing > 0:
                        quality["足欠損数"] += missing
                        quality["指標リセット"] += 1
                        bank.__init__()
                        for state in states:
                            if state.pending and state.pending["kind"] == "entry":
                                state.pending = None
                                state.cancellations += 1
                    bar = {"time": datetime.fromtimestamp(start_s + index * 300, JST).isoformat(), "index": index,
                           "open": last, "high": last, "low": last, "close": last, "観測行数": 1}
                    last_index = index
                else:
                    bar["high"], bar["low"], bar["close"] = max(bar["high"], last), min(bar["low"], last), last
                    bar["観測行数"] += 1
            buy, sell = row.get("Buy1") or {}, row.get("Sell1") or {}
            bid, ask = buy.get("Price"), sell.get("Price")
            valid = positive(bid) and positive(ask) and bid < ask and positive(buy.get("Qty")) and positive(sell.get("Qty")) and buy["Qty"] >= 1 and sell["Qty"] >= 1
            if not valid:
                quality["不正板"] += 1
            for state in states:
                state.on_quote(now, line_no, index, bid, ask, valid)
    if bar:
        values = bank.update(bar)
        bar["確定確認時刻"] = "次セッションまでの履歴専用"
        bar["指標有効"] = values["ready"]
        bars.append(bar)
    expected_last = int((end_s - start_s) / 300) - 1
    tail_missing = expected_last - (last_index if last_index is not None else -1)
    if tail_missing > 0:
        quality["足欠損数"] += tail_missing
        quality["指標リセット"] += 1
        bank.__init__()
    quality["展開内容SHA256"] = digest.hexdigest()
    if path.stat().st_size != quality["ファイルバイト"] or path.stat().st_mtime_ns != quality["入力更新時刻ns"]:
        raise RuntimeError(f"読取中に入力が変化しました: {path}")
    quality["確定足数"] = len(bars)
    quality["有効指標足数"] = sum(bar["指標有効"] for bar in bars)
    if not bars:
        raise ValueError(f"評価できる原板足がありません: {path}")
    for state in states:
        if state.pending and state.pending["kind"] == "entry":
            state.cancellations += 1
            state.pending = None
    return states, quality, bars, previous_symbol


def summary(trades: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """指定した取引とセッションから評価値を集計する。

    引数: trades (list[dict[str, Any]]) は完結取引、sessions (list[dict[str, Any]]) は対象全場。
    返り値: dict[str, Any] は純損益、費用感度、取引数等。
    """
    profits = [trade["純損益円"] for trade in trades]
    gains = sum(max(value, 0) for value in profits)
    losses = -sum(min(value, 0) for value in profits)
    total = sum(profits)
    incomplete = any(row["終了建玉"] != 0 or row["終了未約定"] != 0 for row in sessions)
    cash, peak, max_dd = 0.0, 0.0, 0.0
    for row in sessions:
        max_dd = max(max_dd, row["含み込み最大DD円"], peak - (cash + row["最小資産円"]))
        peak = max(peak, cash + row["最大資産円"])
        cash += row["純損益円"]
    return {"セッション数": len(sessions), "無取引場数": sum(row["取引数"] == 0 for row in sessions),
            "取引数": len(profits), "値幅損益円": sum(trade["値幅損益円"] for trade in trades),
            "手数料円": sum(trade["手数料円"] for trade in trades), "純損益円": None if incomplete else total,
            "完結取引純損益円": total, "現金会計合計円": sum(row["純損益円"] for row in sessions),
            "結果状態": "不完全・持越し制約違反" if incomplete else "完結",
            "平均場損益円": total / len(sessions) if sessions and not incomplete else None,
            "平均取引損益円": total / len(profits) if profits else None,
            "勝率": sum(value > 0 for value in profits) / len(profits) if profits else None,
            "PF": gains / losses if losses else None,
            "最悪場円": min((row["純損益円"] for row in sessions), default=None),
            "含み込み最大DD円": max_dd,
            "費用増純損益円": sum(trade["費用増純損益円"] for trade in trades),
            "期限返済数": sum(trade["返済理由"] == "期限返済" for trade in trades),
            "保護返済数": sum(trade["返済理由"] == "保護発動" for trade in trades),
            "未解消場数": sum(row["終了建玉"] != 0 for row in sessions)}


def git_head(path: Path) -> str:
    """再現用にGitのコミットを読む。

    引数: path (Path) はリポジトリ内のパス。
    返り値: str はコミット文字列。
    """
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def validate_config(config: dict[str, Any]) -> None:
    """再現専用コードの固定条件と設定の不一致を拒否する。

    引数: config (dict[str, Any]) は採用する条件JSON。
    返り値: None。不一致ならValueErrorを送出する。
    """
    expected = {"足秒": 300, "新規有効秒": 30, "約定待ち価格時計秒": 1,
                "MACD": [12, 26, 9], "方向EMA": 60, "RSI期間": 14, "ATR期間": 14, "保護ATR倍": 2,
                "候補": ["MACDのみ", "方向条件", "方向条件とRSI"],
                "新規停止": {"Day": "15:25", "Night": "05:40"},
                "全返済要求": {"Day": "15:35", "Night": "05:50"}}
    for key, value in expected.items():
        if config.get(key) != value:
            raise ValueError(f"再現専用コードと条件が不一致: {key}")


def run(data_root: Path, output: Path) -> None:
    """全対象を事前設定で計算して小さな成果物を保存する。

    引数: data_root (Path) は指数フォルダの親、output (Path) は成果物の保存先。
    返り値: None。
    """
    config = json.loads((HERE / "条件.json").read_text(encoding="utf-8"))
    validate_config(config)
    output.mkdir(parents=True, exist_ok=True)
    quality_rows, session_rows, trade_rows, resources, comparisons = [], [], [], [], []
    bar_comparison = []
    previous_manifest_path = output / "データ品質と入力台帳.json"
    previous_manifest = {}
    if previous_manifest_path.exists():
        previous_manifest = {(row["銘柄"], row["場"]): row["展開内容SHA256"] for row in json.loads(previous_manifest_path.read_text(encoding="utf-8"))}
    for symbol in config["商品"]:
        bank, previous_code = Indicators(), None
        selected = [row for row in config["入力一覧"] if row["銘柄"] == symbol]
        for number, entry in enumerate(selected, 1):
            path = data_root / entry["相対パス"]
            folder = path.parent
            if not path.exists():
                raise FileNotFoundError(path)
            if path.stat().st_size != entry["ファイルバイト"]:
                raise ValueError(f"凍結した入力とサイズが異なります: {path}")
            states, quality, bars, previous_code = process_session(path, symbol, folder.name, bank, previous_code, config)
            previous_hash = previous_manifest.get((symbol, folder.name))
            if previous_hash and previous_hash != quality["展開内容SHA256"]:
                raise ValueError(f"前回実行から入力内容が変化しました: {path}")
            quality["入力"] = path.relative_to(data_root).as_posix()
            quality_rows.append(quality)
            phase = "未使用評価" if folder.name[:10] >= config["評価開始日"] else "開発"
            csv_path = folder / "candle_5min.csv"
            if csv_path.exists():
                with csv_path.open(encoding="utf-8-sig", newline="") as source:
                    existing = {row["time"]: row for row in csv.DictReader(source)}
                matches = differences = 0
                for bar in bars:
                    old = existing.get(bar["time"])
                    if old:
                        equal = all(math.isclose(bar[key], float(old[key]), abs_tol=1e-8) for key in ("open", "high", "low", "close"))
                        matches += equal
                        differences += not equal
                bar_comparison.append({"銘柄": symbol, "場": folder.name, "原板足": len(bars), "既存CSV足": len(existing),
                                       "一致足": matches, "不一致足": differences, "共通外原板足": len(bars) - matches - differences})
            for state in states:
                relative = Path("約定") / symbol / f"{folder.name}_{config['候補'].index(state.method)}.trades.jsonl"
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("".join(json.dumps(fill, ensure_ascii=False, allow_nan=False) + "\n" for fill in state.fills), encoding="utf-8")
                audit_path = output / "判断" / symbol / f"{folder.name}_{config['候補'].index(state.method)}.jsonl"
                audit_path.parent.mkdir(parents=True, exist_ok=True)
                audit_path.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in state.decisions), encoding="utf-8")
                for trade in state.trades:
                    trade["期間"] = phase
                    trade["費用増純損益円"] = trade["純損益円"] - trade["手数料円"] - 2 * state.product["tick"] * state.product["point_value"]
                trade_rows.extend(state.trades)
                session_rows.append({"銘柄": symbol, "場": folder.name, "期間": phase, "手法": state.method,
                                     "取引数": len(state.trades), "値幅損益円": sum(row["値幅損益円"] for row in state.trades),
                                     "手数料円": len(state.fills) * state.product["fee_yen"], "純損益円": state.cash,
                                     "含み込み最大DD円": state.drawdown, "最大資産円": state.peak, "最小資産円": state.minimum,
                                     "終了建玉": 0 if state.position is None else state.position["side"],
                                     "終了未約定": 0 if state.pending is None else 1,
                                     "取消新規数": state.cancellations, "最大返済待ち秒": state.max_exit_delay,
                                     "足欠損数": quality["足欠損数"]})
                resources.append({"id": f"{symbol}_{folder.name}_{config['候補'].index(state.method)}",
                                  "title": f"{symbol} {folder.name} {state.method}・ラージ代理",
                                  "symbol": symbol, "session": folder.name, "product": state.product["product"],
                                  "method_id": state.method, "point_value": state.product["point_value"],
                                  "pnl_format": "trades", "pnl_basis": "net", "pnl_path": relative.as_posix(),
                                  "market_path": path.relative_to(data_root).as_posix()})
            print(f"処理済み {symbol} {number}/{len(selected)} {folder.name} 原行{quality['原行数']} 足{len(bars)}", flush=True)
    aggregates = []
    for symbol in config["商品"]:
        for phase in ("全期間", "開発", "未使用評価"):
            for method in config["候補"]:
                selected_sessions = [row for row in session_rows if row["銘柄"] == symbol and row["手法"] == method and (phase == "全期間" or row["期間"] == phase)]
                selected_trades = [row for row in trade_rows if row["銘柄"] == symbol and row["手法"] == method and (phase == "全期間" or row["期間"] == phase)]
                aggregates.append({"銘柄": symbol, "期間": phase, "手法": method, **summary(selected_trades, selected_sessions)})
        for folder_name in sorted({row["場"] for row in session_rows if row["銘柄"] == symbol}):
            rows = {row["手法"]: row for row in session_rows if row["銘柄"] == symbol and row["場"] == folder_name}
            comparisons.append({"銘柄": symbol, "場": folder_name, "期間": rows["MACDのみ"]["期間"],
                                "方向追加差円": rows["方向条件"]["純損益円"] - rows["MACDのみ"]["純損益円"],
                                "RSI追加差円": rows["方向条件とRSI"]["純損益円"] - rows["方向条件"]["純損益円"]})
    write_csv(output / "セッション集計.csv", session_rows)
    write_csv(output / "取引集計.csv", trade_rows)
    write_csv(output / "候補比較.csv", aggregates)
    write_csv(output / "対応差.csv", comparisons)
    write_csv(output / "足の照合.csv", bar_comparison)
    write_json(output / "データ品質と入力台帳.json", quality_rows)
    write_json(output / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    write_json(output / "結果.json", aggregates)
    write_json(output / "実行情報.json", {"実行日時": datetime.now(JST).isoformat(), "Python": platform.python_version(),
                                        "OS": platform.platform(), "JSON読取": f"orjson {orjson.__version__}" if orjson else "標準json",
                                        "研究コミット": git_head(ROOT), "データコミット": git_head(data_root),
                                        "Viewerコミット": git_head(ROOT.parent / "SessionTradeViewer"),
                                        "計算コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                        "条件SHA256": hashlib.sha256((HERE / "条件.json").read_bytes()).hexdigest(),
                                        "セッション資源数": len(resources), "入力数": len(quality_rows), "計算資源": "CPU、原板1回走査・3候補同時"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MACDと方向条件の初回試行を再現する")
    parser.add_argument("--data-root", type=Path, default=ROOT.parent / "JP_OSE_Data" / "future")
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args()
    run(args.data_root.resolve(), args.output.resolve())
