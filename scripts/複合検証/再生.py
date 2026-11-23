"""確定した複数時間足の複合条件を、同じ板観測と注文規則で比較する。"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import platform
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = ROOT / "study/00001_MACDと方向条件の比較/再現.py"
SPEC = importlib.util.spec_from_file_location("初回試行の共通処理", LEGACY_PATH)
legacy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = legacy
SPEC.loader.exec_module(legacy)
JST = legacy.JST


# ----------------------------------------
# 複数時間足と、観測時点の数量

class 時間足指標:
    """一つの時間足の確定値から平均線・RSI・ATRを逐次更新する。"""

    def __init__(self) -> None:
        """未初期化の平滑状態を用意する。

        引数: なし。
        返り値: None。
        """
        self.ema = legacy.Average(20, 2 / 21)
        self.up = legacy.Average(14, 1 / 14)
        self.down = legacy.Average(14, 1 / 14)
        self.atr = legacy.Average(14, 1 / 14)
        self.previous_close = None
        self.result = None

    def update(self, bar: dict[str, Any]) -> dict[str, Any]:
        """確定足一つを受け入れ、方向と平滑値を返す。

        引数: bar (dict[str, Any]) は高値・安値・終値を持つ確定足。
        返り値: dict[str, Any] は方向、EMA、RSI、ATR、終値。
        """
        close = bar["close"]
        previous_ema = self.ema.value
        ema = self.ema.update(close)
        rsi = None
        if self.previous_close is not None:
            delta = close - self.previous_close
            up = self.up.update(max(delta, 0))
            down = self.down.update(max(-delta, 0))
            self.atr.update(max(bar["high"] - bar["low"],
                                abs(bar["high"] - self.previous_close),
                                abs(bar["low"] - self.previous_close)))
            if up is not None and down is not None:
                rsi = 50.0 if up + down == 0 else 100 * up / (up + down)
        direction = 0
        if ema is not None and previous_ema is not None:
            if close > ema and ema > previous_ema:
                direction = 1
            elif close < ema and ema < previous_ema:
                direction = -1
        self.previous_close = close
        self.result = {"close": close, "ema": ema, "rsi": rsi,
                       "atr": self.atr.value, "direction": direction,
                       "ema_previous": previous_ema}
        return self.result


class 複数時間足:
    """完全確定足だけを集約し、先行する参照窓と比較する。"""

    def __init__(self) -> None:
        """全時間足と参照履歴を初期化する。

        引数: なし。
        返り値: None。
        """
        self.channels = {size: 時間足指標() for size in (5, 15, 30)}
        self.parts = {}
        self.ranges = deque(maxlen=6)
        self.norms = deque(maxlen=60)
        self.volumes = deque(maxlen=20)

    def start_session(self) -> None:
        """場をまたがせない集約足・突破範囲・数量参照を消去する。

        引数: なし。
        返り値: None。EMA・RSI・ATRと正規化ATRの履歴は維持する。
        """
        self.parts.clear()
        self.ranges.clear()
        self.volumes.clear()

    def update(self, bar: dict[str, Any]) -> dict[str, Any]:
        """5分足を確定し、同時に閉じる上位足も先に更新する。

        引数: bar (dict[str, Any]) は場内index、四本値、観測数量と有効性。
        返り値: dict[str, Any] は共通有効性、発動方向、四因子と指標。
        """
        base = self.channels[5].update(bar)
        for size in (15, 30):
            factor = size // 5
            if bar["index"] % factor == 0:
                self.parts[size] = {"high": bar["high"], "low": bar["low"],
                                    "close": bar["close"], "count": 1}
            elif size in self.parts:
                part = self.parts[size]
                part["high"] = max(part["high"], bar["high"])
                part["low"] = min(part["low"], bar["low"])
                part["close"] = bar["close"]
                part["count"] += 1
            if bar["index"] % factor == factor - 1:
                part = self.parts.pop(size, None)
                if part and part["count"] == factor:
                    self.channels[size].update(part)
        higher = {size: self.channels[size].result for size in (15, 30)}
        upper = max((item[0] for item in self.ranges), default=None)
        lower = min((item[1] for item in self.ranges), default=None)
        threshold = statistics.median(self.norms) if len(self.norms) == 60 else None
        volume_mean = statistics.mean(self.volumes) if len(self.volumes) == 20 else None
        relative_volume = bar["volume"] / volume_mean if volume_mean and bar["volume_ok"] else None
        norm = base["atr"] / bar["close"] if base["atr"] is not None else None
        ready = (len(self.ranges) == 6 and threshold is not None and relative_volume is not None
                 and base["ema_previous"] is not None and base["rsi"] is not None
                 and all(higher[size] is not None and higher[size]["ema_previous"] is not None
                         for size in (15, 30)) and higher[15]["rsi"] is not None)
        side = 0
        if len(self.ranges) == 6:
            if bar["close"] > upper and base["direction"] == 1:
                side = 1
            elif bar["close"] < lower and base["direction"] == -1:
                side = -1
        flags = {"M": False, "R": False, "V": False, "B": False}
        if ready and side:
            flags = {
                "M": all(higher[size]["direction"] == side for size in (15, 30)),
                "R": all(value < 70 for value in (base["rsi"], higher[15]["rsi"])) if side == 1
                     else all(value > 30 for value in (base["rsi"], higher[15]["rsi"])),
                "V": relative_volume >= 1.2,
                "B": norm <= threshold,
            }
        result = {"ready": ready, "side": side, "flags": flags, "close": bar["close"],
                  "ema": base["ema"], "atr": base["atr"], "rsi5": base["rsi"],
                  "rsi15": higher[15]["rsi"] if higher[15] else None,
                  "direction15": higher[15]["direction"] if higher[15] else None,
                  "direction30": higher[30]["direction"] if higher[30] else None,
                  "upper": upper, "lower": lower, "relative_volume": relative_volume,
                  "norm_atr": norm, "norm_threshold": threshold,
                  "bar_end": bar["end"], "volume": bar["volume"], "volume_ok": bar["volume_ok"]}
        self.ranges.append((bar["high"], bar["low"]))
        if norm is not None:
            self.norms.append(norm)
        if bar["volume_ok"]:
            self.volumes.append(bar["volume"])
        else:
            self.volumes.clear()
        return result


class 観測数量:
    """価格時計で利用可能な累積数量差分を、観測した足へ加算する。"""

    def __init__(self) -> None:
        """数量基準と品質件数を初期化する。

        引数: なし。
        返り値: None。
        """
        self.previous = None
        self.previous_clock = None
        self.resets = 0
        self.future = 0

    def update(self, event: Any, bar: dict[str, Any]) -> None:
        """未来の数量時計を利用せず、受け入れられる差分だけ集計する。

        引数: event (Any) はnow/volume/volume_timeを持つ観測、bar (dict[str, Any]) は現在足。
        返り値: None。初回・減少・数量時計後退は基準更新のみとして当足を不完全にする。
        """
        value, clock = event.volume, event.volume_time
        if not math.isfinite(value) or not math.isfinite(clock) or value < 0:
            bar["volume_ok"] = False
            return
        if clock > event.now:
            self.future += 1
            return
        if self.previous is None or value < self.previous or clock < self.previous_clock:
            bar["volume_ok"] = False
            self.resets += 1
        else:
            bar["volume"] += value - self.previous
        self.previous, self.previous_clock = value, clock
        if clock >= bar["start"]:
            bar["volume_seen"] = True


# ----------------------------------------
# 共通注文規則と、候補別の入口・出口

class 複合手法(legacy.Strategy):
    """共通の注文・会計を継承し、明示した因子だけを入口へ加える。"""

    def __init__(self, rule: dict[str, Any], symbol: str, session: str, product: dict[str, Any]) -> None:
        """一つの候補のセッション状態を生成する。

        引数: rule (dict[str, Any]) は固定候補、symbol/session (str) は指数・場、
        product (dict[str, Any]) は実行商品の仮定。
        返り値: None。
        """
        start, end, cutoff, force = legacy.session_times(session)
        super().__init__(rule["名前"], symbol, session, product,
                         cutoff.timestamp(), force.timestamp(), end.timestamp())
        self.rule = rule
        self.opportunities = 0
        self.allowed = 0
        self.entry_values = {}

    def on_signal(self, values: dict[str, Any], now: float, line: int, bucket: int) -> None:
        """毎確定足で通常出口を判定し、有効な発動へ因子を適用する。

        引数: values (dict[str, Any]) は全時間足更新後の特徴、now (float) は価格時計秒、
        line (int) は原板行、bucket (int) は観測中の5分区間。
        返り値: None。出口は入口の共通有効性・突破の有無に依存しない。
        """
        self.expire_entry(now)
        if self.rule.get("取引禁止"):
            return
        if self.position:
            side = self.position["side"]
            if self.rule.get("追尾ATR倍") and values["atr"] is not None:
                proposal = values["close"] - side * self.rule["追尾ATR倍"] * values["atr"]
                tick = self.product["tick"]
                proposal = (math.floor(proposal / tick) if side == 1 else math.ceil(proposal / tick)) * tick
                self.position["stop"] = max(self.position["stop"], proposal) if side == 1 else min(self.position["stop"], proposal)
            if self.rule.get("最大保有分") and now - self.position["time"] >= self.rule["最大保有分"] * 60:
                self.request("exit", side, now, line, "時間返済")
            if self.rule.get("EMA決済", True) and values["ema"] is not None and side * (values["close"] - values["ema"]) < 0:
                self.request("exit", side, now, line, "EMA反対側")
            return
        side = values["side"]
        if self.pending and self.pending["kind"] == "entry" and side and side != self.pending["side"]:
            self.pending = None
            self.cancellations += 1
        if (not values["ready"] or not side or now - values["bar_end"] > 30 or now >= self.cutoff):
            return
        self.opportunities += 1
        if not all(values["flags"][key] for key in self.rule["因子"]):
            return
        self.allowed += 1
        if self.pending or self.last_exit_bucket == bucket:
            return
        self.entry_values = {key: values[key] for key in ("rsi5", "rsi15", "relative_volume", "norm_atr")}
        self.request("entry", side, now, line, "価格帯突破", values["atr"])

    def on_quote(self, now: float, line: int, bucket: int, bid: float, ask: float, valid: bool) -> None:
        """既存注文処理を使い、約定時に候補の保護幅を確定する。

        引数: now (float) は価格時計秒、line/bucket (int) は原板行と足番号、
        bid/ask (float) は両気配、valid (bool) は正常板。
        返り値: None。
        """
        previous = self.position
        if valid and self.position and self.rule.get("利確ATR倍"):
            pos = self.position
            reached = bid >= pos["target"] if pos["side"] == 1 else ask <= pos["target"]
            if reached:
                self.request("exit", pos["side"], now, line, "ATR利確")
        super().on_quote(now, line, bucket, bid, ask, valid)
        if previous is None and self.position is not None:
            pos = self.position
            proposal = pos["entry"] - pos["side"] * self.rule.get("保護ATR倍", 2) * pos["atr"]
            tick = self.product["tick"]
            pos["stop"] = (math.floor(proposal / tick) if pos["side"] == 1 else math.ceil(proposal / tick)) * tick
            if self.rule.get("利確ATR倍"):
                target = pos["entry"] + pos["side"] * self.rule["利確ATR倍"] * pos["atr"]
                pos["target"] = (math.ceil(target / tick) if pos["side"] == 1 else math.floor(target / tick)) * tick
            pos["features"] = dict(self.entry_values)
        if previous is not None and self.position is None:
            self.trades[-1].update(previous.get("features", {}))


def load_preparation() -> Any:
    """同じフォルダのキャッシュ読取処理を読み込む。

    引数: なし。
    返り値: Any はデータ準備モジュール。
    """
    path = Path(__file__).with_name("データ準備.py")
    spec = importlib.util.spec_from_file_location("複合検証のデータ準備", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def replay_session(entry: dict[str, Any], cache_root: Path, preparation: Any,
                   bank: 複数時間足, rules: list[dict[str, Any]], product: dict[str, Any]) -> tuple:
    """一場の入力を一度走査し、全候補へ同じ観測を渡す。

    引数: entry (dict[str, Any]) は凍結入力、cache_root (Path) は台帳親、
    preparation (Any) は読取モジュール、bank (複数時間足) は継続指標、
    rules (list[dict[str, Any]]) は候補、product (dict[str, Any]) は商品条件。
    返り値: tuple は手法状態、発動候補、品質集計。
    """
    start, end, _, _ = legacy.session_times(entry["session"])
    start_s, end_s = start.timestamp(), end.timestamp()
    bank.start_session()
    states = [複合手法(rule, entry["symbol"], entry["session"], product) for rule in rules]
    volume = 観測数量()
    bar, previous_time, last_index = None, None, None
    signals = []
    quality = {"銘柄": entry["symbol"], "場": entry["session"], "確定5分足": 0,
               "共通有効足": 0, "数量基準有効足": 0, "足欠損": 0, "遅延発動除外": 0}

    def finish(current: dict[str, Any], now: float, line: int, bucket: int, allow_signal: bool) -> None:
        """直前足を確定し、参照履歴を更新して判断を配布する。

        引数: current (dict[str, Any]) は確定対象、now (float) は確認価格時計、
        line/bucket (int) は確認原行と次区間、allow_signal (bool) は判断を許すか。
        返り値: None。
        """
        current["volume_ok"] = current["volume_ok"] and current["volume_seen"]
        values = bank.update(current)
        quality["確定5分足"] += 1
        quality["数量基準有効足"] += int(current["volume_ok"])
        quality["共通有効足"] += int(values["ready"])
        if allow_signal:
            if values["ready"] and values["side"]:
                row = {"銘柄": entry["symbol"], "場": entry["session"],
                       "足開始": datetime.fromtimestamp(current["start"], JST).isoformat(),
                       "判断時刻": datetime.fromtimestamp(now, JST).isoformat(), "原板行": line,
                       "方向": values["side"], "判断遅延秒": now - current["end"],
                       "発動可能": now - current["end"] <= 30 and now < states[0].cutoff}
                row.update({key: values[key] for key in ("close", "ema", "atr", "rsi5", "rsi15",
                            "direction15", "direction30", "upper", "lower", "relative_volume", "norm_atr", "norm_threshold")})
                row.update(values["flags"])
                signals.append(row)
                quality["遅延発動除外"] += int(now - current["end"] > 30)
            for state in states:
                state.on_signal(values, now, line, bucket)

    cache_path = cache_root / entry["cache_path"]
    if hashlib.sha256(cache_path.read_bytes()).hexdigest() != entry["sha256_cache"]:
        raise ValueError(f"キャッシュハッシュ不一致: {cache_path}")
    for event in preparation.read_events(cache_path):
        now = event.now
        if not math.isfinite(now) or now < start_s or now > end_s or (previous_time is not None and now < previous_time):
            continue
        previous_time = now
        index = int((now - start_s) // 300)
        if bar and index != bar["index"]:
            missing = index - bar["index"] - 1
            finish(bar, now, event.line, index, missing == 0)
            bar = None
        if legacy.positive(event.last) and now < end_s:
            if bar is None:
                initial_missing = index if last_index is None else index - last_index - 1
                if initial_missing > 0:
                    quality["足欠損"] += initial_missing
                    bank.__init__()
                    volume.previous = volume.previous_clock = None
                    for state in states:
                        if state.pending and state.pending["kind"] == "entry":
                            state.pending = None
                            state.cancellations += 1
                bar = {"index": index, "start": start_s + index * 300, "end": start_s + (index + 1) * 300,
                       "open": event.last, "high": event.last, "low": event.last, "close": event.last,
                       "volume": 0.0, "volume_ok": volume.previous is not None, "volume_seen": False}
                last_index = index
            else:
                bar["high"] = max(bar["high"], event.last)
                bar["low"] = min(bar["low"], event.last)
                bar["close"] = event.last
            volume.update(event, bar)
        for state in states:
            if state.position or state.pending:
                state.on_quote(now, event.line, index, event.bid, event.ask, bool(event.valid))
    if bar:
        finish(bar, end_s, 0, bar["index"] + 1, False)
    expected_last = int((end_s - start_s) // 300) - 1
    tail = expected_last - (last_index if last_index is not None else -1)
    if tail > 0:
        quality["足欠損"] += tail
        bank.__init__()
    for state in states:
        if state.pending and state.pending["kind"] == "entry":
            state.cancellations += 1
            state.pending = None
    quality["数量再基準化"] = volume.resets
    quality["数量未来時計未使用イベント"] = volume.future
    return states, signals, quality


# ----------------------------------------
# 小型の成果物・対応差・出所の保存

def factorial_rules() -> list[dict[str, Any]]:
    """四因子の全オン・オフを固定した16候補を作る。

    引数: なし。
    返り値: list[dict[str, Any]] は固定順の候補。
    """
    result = []
    for switches in itertools.product((False, True), repeat=4):
        active = [key for key, enabled in zip("MRVB", switches) if enabled]
        result.append({"名前": "基準" if not active else "+".join(active), "因子": active,
                       "EMA決済": True, "保護ATR倍": 2})
    return result


def paired_effects(sessions: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """一因子だけ違う候補の同一場損益差を全て保存する。

    引数: sessions (list[dict[str, Any]]) は全場集計、rules (list[dict[str, Any]]) は候補。
    返り値: list[dict[str, Any]] は因子追加の対応差。
    """
    by_factors = {frozenset(rule["因子"]): rule["名前"] for rule in rules}
    indexed = {(row["銘柄"], row["場"], row["手法"]): row for row in sessions}
    result = []
    for factors, before in by_factors.items():
        for factor in "MRVB":
            after = by_factors.get(factors | {factor})
            if factor in factors or after is None:
                continue
            for row in sessions:
                if row["手法"] != before:
                    continue
                other = indexed[row["銘柄"], row["場"], after]
                complete = not any(item["終了建玉"] or item["終了未約定"] for item in (row, other))
                result.append({"銘柄": row["銘柄"], "場": row["場"], "期間": row["期間"],
                               "追加因子": factor, "追加前": before, "追加後": after,
                               "結果状態": "完結" if complete else "未解消・比較不可",
                               "純損益差円": other["純損益円"] - row["純損益円"] if complete else None,
                               "取引数差": other["取引数"] - row["取引数"]})
    return result


def read_manifest(study: Path) -> tuple[dict[str, Any], Path]:
    """入力台帳または内容ハッシュ付き参照を解決する。

    引数: study (Path) は試行フォルダ。
    返り値: tuple[dict[str, Any], Path] は台帳内容と実体パス。
    """
    path = study / "入力台帳.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if "参照" in data:
        source = (path.parent / data["参照"]).resolve()
        if hashlib.sha256(source.read_bytes()).hexdigest() != data["SHA256"]:
            raise ValueError("参照した入力台帳のハッシュ不一致")
        path = source
        data = json.loads(path.read_text(encoding="utf-8"))
    keys = [(entry["symbol"], entry["session"]) for entry in data["entries"]]
    if len(keys) != len(set(keys)):
        raise ValueError("入力台帳に銘柄・場の重複がある")
    if keys != sorted(keys):
        raise ValueError("入力台帳が指数・場の順でない")
    return data, path


def validate_config(config: dict[str, Any]) -> None:
    """コードで固定する指標と期限が、条件ファイルと一致するか調べる。

    引数: config (dict[str, Any]) は試行条件。
    返り値: None。未対応条件・明示値の不一致はValueErrorにする。
    """
    expected = {"EMA": 20, "RSI": 14, "ATR": 14, "突破参照本数": 6, "数量参照本数": 20,
                "相対数量閾値": 1.2, "正規化ATR参照本数": 60, "時間足分": [5, 15, 30], "確定確認遅延許容秒": 30}
    if config.get("共通指標") != expected or config.get("版") != 1:
        raise ValueError("コードが対応する指標条件と異なる")
    if config.get("新規停止") != {"Day": "15:25", "Night": "05:40"}:
        raise ValueError("コードの新規停止時刻と異なる")
    if config.get("全返済要求") != {"Day": "15:35", "Night": "05:50"}:
        raise ValueError("コードの全返済要求時刻と異なる")
    if len(config["追加確認場"]) != len(set(config["追加確認場"])):
        raise ValueError("追加確認場が重複している")
    for rule in config["候補"]:
        if set(rule["因子"]) - set("MRVB") or len(rule["因子"]) != len(set(rule["因子"])):
            raise ValueError("未対応または重複した因子")
        for key in ("保護ATR倍", "追尾ATR倍", "利確ATR倍", "最大保有分"):
            if key in rule and not legacy.positive(rule[key]):
                raise ValueError(f"正の数が必要: {key}")


def verify_confirmation_lock(study: Path) -> None:
    """追加確認前に固定した条件・コードの内容ハッシュを検査する。

    引数: study (Path) は追加確認を許可した試行。
    返り値: None。固定記録がないか内容が変わっていれば例外にする。
    """
    lock = json.loads((study / "追加確認前の固定.json").read_text(encoding="utf-8"))
    for relative, expected in lock["固定対象SHA256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError(f"追加確認の固定後に変更された: {relative}")


def run(study: Path, phase: str) -> None:
    """凍結した入力・条件を読み、探索または追加確認だけを実行する。

    引数: study (Path) は条件と成果物の保存先、phase (str) は探索/追加確認。
    返り値: None。入力・設定・コード版と約定を記録する。
    """
    config_path = study / "条件.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_config(config)
    if phase == "追加確認":
        verify_confirmation_lock(study)
    rules = config["候補"]
    if len({rule["名前"] for rule in rules}) != len(rules):
        raise ValueError("候補名の重複")
    manifest, manifest_path = read_manifest(study)
    all_entries = manifest["entries"]
    if any(entry["session"] > config["探索最終場"] and entry["session"] not in config["追加確認場"] for entry in all_entries):
        raise ValueError("台帳に固定範囲外の追加場がある")
    entries = [entry for entry in all_entries if entry["session"] <= config["探索最終場"]] if phase == "探索" else [entry for entry in all_entries if entry["session"] in config["追加確認場"]]
    if phase != "探索" and any((symbol, session) not in {(entry["symbol"], entry["session"]) for entry in entries}
                                  for symbol in config["商品"] for session in config["追加確認場"]):
        raise ValueError("固定した追加確認入力が不足")
    if not entries:
        raise ValueError("対象入力がない")
    output = study if phase == "探索" else study / "追加確認"
    output.mkdir(parents=True, exist_ok=True)
    cache_root = ROOT / config["キャッシュルート"]
    preparation = load_preparation()
    sessions, trades, opportunities, resources, quality_rows = [], [], [], [], []
    for symbol in config["商品"]:
        bank, previous_contract = 複数時間足(), None
        # 追加確認の指標には探索期の価格履歴を使うが、探索期の注文を再計算しない。
        symbol_entries = [entry for entry in all_entries if entry["symbol"] == symbol]
        for number, entry in enumerate(symbol_entries, 1):
            selected = entry in entries
            if phase == "探索" and not selected:
                continue
            source_path = ROOT.parent / "JP_OSE_Data/future" / entry["source_path"]
            status = source_path.stat()
            if status.st_size != entry["source_size"] or status.st_mtime_ns != entry["source_mtime_ns"]:
                raise ValueError(f"凍結後に入力が変更された: {source_path}")
            contract = tuple(entry["contract_codes"])
            if len(contract) != 1:
                raise ValueError(f"場内限月が一意でない: {symbol}/{entry['session']}")
            if contract != previous_contract:
                bank = 複数時間足()
                previous_contract = contract
            active_rules = rules if selected else [{"名前": "履歴専用", "因子": list("MRVB"), "EMA決済": True, "取引禁止": True}]
            states, signals, quality = replay_session(entry, cache_root, preparation, bank, active_rules, config["商品"][symbol])
            if not selected:
                continue
            period = "追加確認" if phase != "探索" else ("探索後半" if entry["session"][:10] >= "2026-10-19" else "探索前半")
            quality_rows.append(quality)
            for row in signals:
                row["期間"] = period
            opportunities.extend(signals)
            merged_fills = []
            relative = Path("約定") / symbol / f"{entry['session']}.trades.jsonl"
            for rule_index, state in enumerate(states):
                prefix = f"候補{rule_index:02d}_"
                for fill in state.fills:
                    fill["id"] = prefix + fill["id"]
                    fill["position_id"] = prefix + fill["position_id"]
                    merged_fills.append(fill)
                for trade in state.trades:
                    trade["建玉ID"] = prefix + trade["建玉ID"]
                    trade["期間"] = period
                    trade["費用増純損益円"] = trade["純損益円"] - trade["手数料円"] - 2 * state.product["tick"] * state.product["point_value"]
                trades.extend(state.trades)
                sessions.append({"銘柄": symbol, "場": entry["session"], "期間": period, "手法": state.method,
                                 "取引数": len(state.trades), "純損益円": state.cash,
                                 "含み込み最大DD円": state.drawdown, "最大資産円": state.peak, "最小資産円": state.minimum,
                                 "終了建玉": int(state.position is not None), "終了未約定": int(state.pending is not None),
                                 "入口機会数": state.opportunities, "条件許可数": state.allowed,
                                 "取消数": state.cancellations, "最大返済待ち秒": state.max_exit_delay})
                resources.append({"id": f"{symbol}_{entry['session']}_{rule_index}",
                                  "title": f"{entry['session']} {state.method}", "symbol": symbol,
                                  "session": entry["session"], "product": state.product["product"],
                                  "method_id": state.method, "entry_method_id": state.method,
                                  "point_value": state.product["point_value"], "pnl_format": "trades",
                                  "pnl_basis": "net", "pnl_path": relative.as_posix(), "market_path": entry["source_path"]})
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            merged_fills.sort(key=lambda fill: (fill["timestamp"], fill["source_line"], fill["id"]))
            target.write_text("".join(json.dumps(fill, ensure_ascii=False, allow_nan=False) + "\n" for fill in merged_fills), encoding="utf-8")
            print(f"{symbol} {number}/{len(symbol_entries)} {entry['session']} 完了", flush=True)
    aggregates = []
    for symbol in config["商品"]:
        for rule in rules:
            for period in ("全対象", "追加確認") if phase != "探索" else ("全対象", "探索前半", "探索後半"):
                selected_sessions = [row for row in sessions if row["銘柄"] == symbol and row["手法"] == rule["名前"]
                                     and (period == "全対象" or row["期間"] == period)]
                selected_trades = [row for row in trades if row["銘柄"] == symbol and row["手法"] == rule["名前"]
                                   and (period == "全対象" or row["期間"] == period)]
                aggregates.append({"銘柄": symbol, "手法": rule["名前"], "期間": period,
                                   **legacy.summary(selected_trades, selected_sessions)})
    legacy.write_csv(output / "セッション集計.csv", sessions)
    legacy.write_csv(output / "取引集計.csv", trades)
    legacy.write_csv(output / "候補比較.csv", aggregates)
    legacy.write_csv(output / "発動候補.csv", opportunities)
    legacy.write_csv(output / "対応差.csv", paired_effects(sessions, rules))
    legacy.write_json(output / "結果.json", aggregates)
    legacy.write_json(output / "品質集計.json", quality_rows)
    legacy.write_json(output / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    files = [Path(__file__), LEGACY_PATH, Path(preparation.__file__), config_path, study / "入力台帳.json", manifest_path]
    legacy.write_json(output / "実行情報.json", {"日時": datetime.now(JST).isoformat(), "段階": phase,
                      "Python": platform.python_version(), "計算資源": "CPU、キャッシュ1走査・全候補同時",
                      "条件SHA256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                      "ファイルSHA256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
                      "資源数": len(resources), "入力数": len(quality_rows),
                      "研究HEAD": legacy.git_head(ROOT), "データHEAD": legacy.git_head(ROOT.parent / "JP_OSE_Data")})


def main() -> None:
    """引数から対象試行と実行段階を選ぶ。

    引数: なし。argparseで実行引数を取得する。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="複数時間足と四因子を逐次比較する")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--phase", choices=("探索", "追加確認"), default="探索")
    args = parser.parse_args()
    run(args.study.resolve(), args.phase)


if __name__ == "__main__":
    main()
