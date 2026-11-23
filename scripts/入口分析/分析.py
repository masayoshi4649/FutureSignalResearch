"""入口時点の特徴と、逆行200pt・順行400ptへの観測上の先着を分析する。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "scripts/複合検証/再生.py"
SPEC = importlib.util.spec_from_file_location("固定済みの複合検証", SHARED_PATH)
shared = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shared
SPEC.loader.exec_module(shared)
JST = shared.JST
GROUPS = ("無条件両方向", "5分方向", "複数足整合", "整合突破", "押し戻り復帰", "収縮拡大突破")
LABELS = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")


# ----------------------------------------
# 当該時点で利用可能なチャート特徴

class 入口特徴:
    """既存の指標計算を使い、数量準備と独立した入口比較の母集団を作る。"""

    def __init__(self) -> None:
        """過去指標と場内の比較状態を初期化する。

        引数: なし。
        返り値: None。
        """
        self.bank = shared.複数時間足()
        self.previous = None
        self.closed_at = {15: None, 30: None}
        self.start = None

    def start_session(self, start: float) -> None:
        """指標履歴を残し、場内の集約・確定時点・前足比較を消去する。

        引数: start (float) はセッション開始のUnix秒。
        返り値: None。
        """
        self.bank.start_session()
        self.closed_at = {15: None, 30: None}
        self.previous = None
        self.start = start

    def update(self, bar: dict[str, Any]) -> dict[str, Any]:
        """確定足と同時確定する上位足を更新して、入口の根拠を固定する。

        引数: bar (dict[str, Any]) は四本値、場内index、観測数量を持つ5分足。
        返り値: dict[str, Any] は共通有効性、方向・パターン・診断用指標。
        """
        before = {size: self.bank.channels[size].result for size in (5, 15, 30)}
        prior_six = len(self.bank.ranges) == 6
        previous_close = self.bank.channels[5].previous_close
        values = self.bank.update(bar)
        for size in (15, 30):
            if self.bank.channels[size].result is not before[size]:
                self.closed_at[size] = bar["end"]
        current = self.bank.channels[5].result
        fresh = all(self.closed_at[size] is not None and self.closed_at[size] >= self.start for size in (15, 30))
        previous = self.previous
        ready = (prior_six and fresh and previous is not None and previous["fresh"]
                 and current["ema_previous"] is not None and current["rsi"] is not None
                 and current["atr"] is not None and current["atr"] > 0
                 and values["norm_threshold"] is not None and previous["norm_threshold"] is not None
                 and all(self.bank.channels[size].result["ema_previous"] is not None for size in (15, 30)))
        true_range = None if previous_close is None else max(bar["high"] - bar["low"],
                     abs(bar["high"] - previous_close), abs(bar["low"] - previous_close))
        result = {**values, "ready": ready, "fresh": fresh, "direction5": current["direction"],
                  "tr": true_range, "tr_previous_atr": None,
                  "previous_squeeze": False, "recovery": 0,
                  "expansion": previous is not None and previous["atr"] is not None
                               and true_range is not None and true_range > previous["atr"]}
        if previous is not None and previous["atr"] is not None and previous["atr"] > 0:
            result["tr_previous_atr"] = true_range / previous["atr"]
        if previous is not None and previous["norm_threshold"] is not None:
            result["previous_squeeze"] = previous["norm_atr"] <= previous["norm_threshold"]
        if ready:
            higher = values["direction15"]
            stable = (higher in (-1, 1) and values["direction30"] == higher
                      and previous["direction15"] == higher and previous["direction30"] == higher)
            if stable and higher == 1 and previous["close"] <= previous["ema"] and values["close"] > values["ema"]:
                result["recovery"] = 1
            elif stable and higher == -1 and previous["close"] >= previous["ema"] and values["close"] < values["ema"]:
                result["recovery"] = -1
        self.previous = result
        return result


def memberships(values: dict[str, Any], side: int) -> list[str]:
    """同じ入口イベントが属する、事前に固定した条件群を返す。

    引数: values (dict[str, Any]) は確定時点の特徴、side (int) は買い1・売り-1。
    返り値: list[str] は適合した群名。未来のラベルを参照しない。
    """
    groups = [GROUPS[0]]
    if values["direction5"] == side:
        groups.append(GROUPS[1])
    aligned = all(values[key] == side for key in ("direction5", "direction15", "direction30"))
    if aligned:
        groups.append(GROUPS[2])
    if aligned and values["side"] == side:
        groups.append(GROUPS[3])
        if values["previous_squeeze"] and values["expansion"]:
            groups.append(GROUPS[5])
    if values["recovery"] == side:
        groups.append(GROUPS[4])
    return groups


# ----------------------------------------
# 観測列に対する、上下閾値の最初の到達検索

class 到達木:
    """区間の最小・最大で枝を省略し、原順の最初の閾値到達を探す。"""

    def __init__(self, prices: np.ndarray) -> None:
        """有限の気配価格列から区間木を構築する。

        引数: prices (np.ndarray) は原順の正常BidまたはAsk。
        返り値: None。
        """
        self.length = len(prices)
        self.size = 1 << max(0, self.length - 1).bit_length()
        self.minimum = np.full(self.size * 2, np.inf)
        self.maximum = np.full(self.size * 2, -np.inf)
        self.minimum[self.size:self.size + self.length] = prices
        self.maximum[self.size:self.size + self.length] = prices
        for level in range(self.size.bit_length() - 2, -1, -1):
            left, right = 1 << level, 1 << (level + 1)
            self.minimum[left:right] = np.minimum(self.minimum[2 * left:2 * right:2], self.minimum[2 * left + 1:2 * right:2])
            self.maximum[left:right] = np.maximum(self.maximum[2 * left:2 * right:2], self.maximum[2 * left + 1:2 * right:2])

    def first(self, start: int, end: int, lower: float, upper: float) -> int | None:
        """指定範囲で価格が下限以下または上限以上になる最初の位置を返す。

        引数: start/end (int) は半開探索範囲、lower/upper (float) は等号を含む閾値。
        返り値: int | None は最初の到達位置、または到達なし。
        """
        stack = [(1, 0, self.size)]
        while stack:
            node, left, right = stack.pop()
            if right <= start or left >= end or (self.minimum[node] > lower and self.maximum[node] < upper):
                continue
            if right - left == 1:
                return left
            middle = (left + right) // 2
            stack.append((node * 2 + 1, middle, right))
            stack.append((node * 2, left, middle))
        return None


class 気配経路:
    """正常板の原順と価格時計を保ったまま、新規と到達を判定する。"""

    def __init__(self, quotes: list[Any]) -> None:
        """正常板列と300秒超の空白位置、Bid・Ask区間木を作る。

        引数: quotes (list[Any]) はnow/line/bid/askを持つ正常観測列。
        返り値: None。
        """
        self.now = np.array([item.now for item in quotes], dtype=float)
        self.line = np.array([item.line for item in quotes], dtype=np.int64)
        self.bid = np.array([item.bid for item in quotes], dtype=float)
        self.ask = np.array([item.ask for item in quotes], dtype=float)
        self.gaps = np.flatnonzero(np.diff(self.now) > 300) + 1
        self.trees = {1: 到達木(self.bid), -1: 到達木(self.ask)}

    def evaluate(self, signal: float, cutoff: float, deadline: float, side: int,
                 adverse: float = 200, favorable: float = 400) -> dict[str, Any]:
        """要求1秒後の新規と、逆行・順行・期限・空白の先着を判定する。

        引数: signal/cutoff/deadline (float) は要求・新規停止・評価期限秒、
        side (int) は買い1・売り-1、adverse/favorable (float) は価格pt幅。
        返り値: dict[str, Any] は約定と、観測上の到達ラベル・原行・順逆行幅。
        """
        index = int(np.searchsorted(self.now, signal + 1, side="left"))
        empty = {"ラベル": "未約定", "理由": "30秒内に正常板なし", "新規価格": None,
                 "新規時計秒": None, "新規原板行": None, "判定時計秒": None, "判定原板行": None,
                 "判定気配": None, "最大順行pt": None, "最大逆行pt": None, "所要分": None}
        if index >= len(self.now) or self.now[index] > signal + 30 or self.now[index] >= cutoff:
            return empty
        entry = float(self.ask[index] if side == 1 else self.bid[index])
        mark = self.bid if side == 1 else self.ask
        lower, upper = (entry - adverse, entry + favorable) if side == 1 else (entry - favorable, entry + adverse)
        end = int(np.searchsorted(self.now, deadline, side="right"))
        gap_position = int(np.searchsorted(self.gaps, index + 1))
        next_gap = int(self.gaps[gap_position]) if gap_position < len(self.gaps) else None
        quality_limited = next_gap is not None and self.now[next_gap - 1] + 300 < deadline
        limit = min(end, next_gap) if quality_limited else end
        hit = self.trees[side].first(index, limit, lower, upper)
        if hit is not None:
            distance = side * (mark[hit] - entry)
            label = "順行先着" if distance >= favorable else "逆行先着"
            reason = "返済気配の閾値初着"
            last = hit
        else:
            last = max(index, limit - 1)
            covered = len(self.now) > 0 and self.now[-1] >= deadline
            stale_tail = deadline - self.now[last] > 300
            label = "観測不足" if quality_limited or not covered or stale_tail else "期限未達"
            reason = "正常板価格時計300秒超空白" if quality_limited or stale_tail else ("入力末尾不足" if not covered else "期限内どちらも未到達")
        distances = side * (mark[index:last + 1] - entry)
        return {"ラベル": label, "理由": reason, "新規価格": entry,
                "新規時計秒": float(self.now[index]), "新規原板行": int(self.line[index]),
                "判定時計秒": float(self.now[last]), "判定原板行": int(self.line[last]),
                "判定気配": float(mark[last]), "最大順行pt": float(max(0, np.max(distances))),
                "最大逆行pt": float(max(0, -np.min(distances))),
                "所要分": float((self.now[last] - self.now[index]) / 60)}


# ----------------------------------------
# 足確定の再生、全入口イベントの共通ラベル化

def candidate_rows(events: list[Any], session: str, bank: 入口特徴) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """原順の場内観測から確定足だけで入口候補と固定特徴を作る。

    引数: events (list[Any]) は場内の非後退イベント、session (str) は場名、
    bank (入口特徴) は同限月で継続する過去指標。
    返り値: tuple は候補行と足の品質集計。
    """
    start, end, cutoff, deadline = shared.legacy.session_times(session)
    begin, finish = start.timestamp(), end.timestamp()
    bank.start_session(begin)
    volume = shared.観測数量()
    bar, last_index = None, None
    rows = []
    quality = {"場": session, "5分足": 0, "共通有効足": 0, "欠5分枠": 0, "確認遅延候補": 0}

    def close_bar(current: dict[str, Any], now: float, line: int, publish: bool) -> None:
        """直前足を確定し、買い・売りへ同じ確定特徴を渡す。

        引数: current (dict[str, Any]) は前足、now (float) は確認時計、line (int) は原行、
        publish (bool) は新規候補の生成を許すか。
        返り値: None。
        """
        current["volume_ok"] = current["volume_ok"] and current["volume_seen"]
        values = bank.update(current)
        quality["5分足"] += 1
        quality["共通有効足"] += int(values["ready"])
        if not publish or not values["ready"] or now >= cutoff.timestamp():
            return
        late = now - current["end"] > 30
        quality["確認遅延候補"] += int(late)
        for side in (1, -1):
            groups = memberships(values, side)
            row = {"イベントID": f"NK225_{session}_{current['index']:03d}_{side}", "場": session,
                   "方向": "買い" if side == 1 else "売り", "side": side, "条件群": "|".join(groups),
                   "足終了時計秒": current["end"], "要求時計秒": now, "要求原板行": line,
                   "確認遅延秒": now - current["end"], "発動遅延超過": late,
                   "期限時計秒": deadline.timestamp(), "新規停止時計秒": cutoff.timestamp(),
                   "残り分_判断時": (deadline.timestamp() - now) / 60,
                   "終値": values["close"], "EMA5": values["ema"], "ATR5": values["atr"],
                   "400ptのATR倍": 400 / values["atr"], "200ptのATR倍": 200 / values["atr"],
                   "RSI5": values["rsi5"], "RSI15": values["rsi15"],
                   "方向側RSI5": values["rsi5"] if side == 1 else 100 - values["rsi5"],
                   "方向5": values["direction5"], "方向15": values["direction15"], "方向30": values["direction30"],
                   "TRの前ATR倍": values["tr_previous_atr"], "前足収縮": values["previous_squeeze"],
                   "当足拡大": values["expansion"],
                   "観測数量比": values["relative_volume"], "直前高値": values["upper"], "直前安値": values["lower"]}
            rows.append(row)

    for event in events:
        now = event.now
        index = int((now - begin) // 300)
        if bar is not None and index != bar["index"]:
            close_bar(bar, now, event.line, index == bar["index"] + 1)
            bar = None
        if shared.legacy.positive(event.last) and now < finish:
            if bar is None:
                missing = index if last_index is None else index - last_index - 1
                if missing > 0:
                    quality["欠5分枠"] += missing
                    bank.__init__()
                    bank.start_session(begin)
                    volume.previous = volume.previous_clock = None
                bar = {"index": index, "start": begin + index * 300, "end": begin + (index + 1) * 300,
                       "open": event.last, "high": event.last, "low": event.last, "close": event.last,
                       "volume": 0.0, "volume_ok": volume.previous is not None, "volume_seen": False}
                last_index = index
            else:
                bar["high"] = max(bar["high"], event.last)
                bar["low"] = min(bar["low"], event.last)
                bar["close"] = event.last
            volume.update(event, bar)
    if bar is not None:
        close_bar(bar, finish, 0, False)
    tail = int((finish - begin) // 300) - 1 - (last_index if last_index is not None else -1)
    if tail > 0:
        quality["欠5分枠"] += tail
        bank.__init__()
    return rows, quality


def summarize(rows: list[dict[str, Any]], group: str, phase: str, direction: str) -> dict[str, Any]:
    """群に属する入口について、期限・不明を落とさず到達割合を集計する。

    引数: rows (list[dict[str, Any]]) は入口イベント、group/phase/direction (str) は集計条件。
    返り値: dict[str, Any] は件数・到達割合・発生場数。
    """
    counts = Counter(row["ラベル"] for row in rows)
    filled = len(rows) - counts["未約定"]
    known = filled - counts["観測不足"]
    decided = counts["順行先着"] + counts["逆行先着"]
    return {"条件群": group, "期間": phase, "方向": direction, "候補数": len(rows), "約定候補数": filled,
            **{key: counts[key] for key in LABELS},
            "順行先着率_全約定": counts["順行先着"] / filled if filled else None,
            "順行先着率_判定可能": counts["順行先着"] / known if known else None,
            "順行先着率_二閾値到達のみ": counts["順行先着"] / decided if decided else None,
            "候補発生場数": len({row["場"] for row in rows}),
            "順行発生場数": len({row["場"] for row in rows if row["ラベル"] == "順行先着"})}


def phase_of(session: str) -> str:
    """既に利用した期間を、未使用と呼ばず固定区分へ割り当てる。

    引数: session (str) は場名。
    返り値: str は既使用前半40場・後半17場・末尾3場の区分。
    """
    if session > "2026-10-29_Day":
        return "既使用末尾3場"
    return "既使用後半17場" if session[:10] >= "2026-10-19" else "既使用前半40場"


def run(study: Path) -> None:
    """固定したNK225入力を処理し、独立入口イベントと集計だけ保存する。

    引数: study (Path) は計画・条件・入力参照と成果物の保存先。
    返り値: None。通常の運用損益や、全候補の合算建玉は作らない。
    """
    config = json.loads((study / "条件.json").read_text(encoding="utf-8"))
    if config != {"版": 1, "対象": "NK225", "逆行pt": 200, "順行pt": 400, "正常板空白許容秒": 300,
                  "新規待機秒": 1, "新規有効秒": 30, "確認遅延許容秒": 30, "条件群": list(GROUPS),
                  "入力場数": 60, "計画日": "2026-11-01"}:
        raise ValueError("未対応の分析条件")
    manifest, actual_manifest = shared.read_manifest(study)
    entries = [entry for entry in manifest["entries"] if entry["symbol"] == "NK225"]
    if len(entries) != config["入力場数"]:
        raise ValueError("固定した入力場数と異なる")
    preparation = shared.load_preparation()
    bank, contract = 入口特徴(), None
    all_rows, qualities = [], []
    for number, entry in enumerate(entries, 1):
        source = ROOT.parent / "JP_OSE_Data/future" / entry["source_path"]
        status = source.stat()
        if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
            raise ValueError(f"凍結後に原板が変化した: {source}")
        path = ROOT / "work/複合検証" / entry["cache_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256_cache"]:
            raise ValueError("キャッシュSHA256不一致")
        code = tuple(entry["contract_codes"])
        if len(code) != 1:
            raise ValueError("場内限月が一意でない")
        if code != contract:
            bank, contract = 入口特徴(), code
        start, end, _, _ = shared.legacy.session_times(entry["session"])
        events, previous_time = [], None
        for event in preparation.read_events(path):
            if not math.isfinite(event.now) or not start.timestamp() <= event.now <= end.timestamp():
                continue
            if previous_time is not None and event.now < previous_time:
                continue
            previous_time = event.now
            events.append(event)
        quotes = [event for event in events if event.valid]
        if not quotes:
            raise ValueError("正常板がない入力")
        route = 気配経路(quotes)
        rows, quality = candidate_rows(events, entry["session"], bank)
        quality["正常板数"] = len(quotes)
        quality["300秒超空白数"] = len(route.gaps)
        qualities.append(quality)
        for row in rows:
            result = route.evaluate(row["要求時計秒"], row["新規停止時計秒"], row["期限時計秒"], row["side"])
            if row["発動遅延超過"]:
                result = {key: None for key in result}
                result.update({"ラベル": "未約定", "理由": "足確定確認が30秒超"})
            row.update(result)
            row["期間"] = phase_of(entry["session"])
            row["逆行線"] = row["新規価格"] - row["side"] * 200 if row["新規価格"] is not None else None
            row["順行線"] = row["新規価格"] + row["side"] * 400 if row["新規価格"] is not None else None
            for column in ("要求時計秒", "新規時計秒", "判定時計秒"):
                row[column.replace("秒", "JST")] = datetime.fromtimestamp(row[column], JST).isoformat() if row[column] is not None else None
        all_rows.extend(rows)
        print(f"入口分析 {number}/{len(entries)} {entry['session']} 候補{len(rows)}", flush=True)
    summaries, session_rows = [], []
    for group in GROUPS:
        selected = [row for row in all_rows if group in row["条件群"].split("|")]
        for phase in ("全60場", "既使用前半40場", "既使用後半17場", "既使用末尾3場"):
            for direction in ("両方向", "買い", "売り"):
                part = [row for row in selected if (phase == "全60場" or row["期間"] == phase)
                        and (direction == "両方向" or row["方向"] == direction)]
                summaries.append(summarize(part, group, phase, direction))
        for entry in entries:
            part = [row for row in selected if row["場"] == entry["session"]]
            session_rows.append({"場": entry["session"], **summarize(part, group, phase_of(entry["session"]), "両方向")})
    shared.legacy.write_csv(study / "入口事例.csv", all_rows)
    shared.legacy.write_csv(study / "候補比較.csv", summaries)
    shared.legacy.write_csv(study / "場別集計.csv", session_rows)
    shared.legacy.write_json(study / "結果.json", summaries)
    shared.legacy.write_json(study / "品質集計.json", qualities)
    files = [Path(__file__), SHARED_PATH, shared.LEGACY_PATH, Path(preparation.__file__),
             study / "条件.json", study / "計画.md", study / "入力台帳.json", actual_manifest]
    shared.legacy.write_json(study / "実行情報.json", {"実行日時": datetime.now(JST).isoformat(),
            "Python": platform.python_version(), "NumPy": np.__version__, "入力場数": len(entries),
            "独立入口イベント数": len(all_rows), "方法": "全観測の閾値先着検索。実運用の同時保有・合算損益ではない。",
            "対象": "NK225指数価格pt、200円/400円。全期間再利用探索。",
            "ファイルSHA256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}})


def main() -> None:
    """引数で正式な試行フォルダを選択する。

    引数: なし。argparseで--study (Path) を取得する。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="NK225の逆行200ptと順行400ptの入口分析")
    parser.add_argument("--study", required=True, type=Path)
    arguments = parser.parse_args()
    run(arguments.study.resolve())


if __name__ == "__main__":
    main()
