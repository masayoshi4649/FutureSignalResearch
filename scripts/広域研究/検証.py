"""外部資料から作った価格の六仮説を、確定1/3/5分足と原板先着で比較する。"""

from __future__ import annotations

import argparse
from collections import Counter, deque
import csv
from datetime import datetime
import gzip
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
WORK = ROOT / "work/広域研究"
DEFAULT_STUDY = ROOT / "study/00006_外部手法を1分3分5分で比較"
TREND = {"開始幅突破", "狭幅突破", "EMA復帰"}


def module(path: Path, name: str) -> Any:
    """固定済みの共有処理を明示したパスから読み込む。

    引数: path (Path) は実装、name (str) はこのプロセス内の識別名。
    返り値: Any は読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


OLD = module(ROOT / "scripts/入口分析/分析.py", "広域研究の先着共有")
PREP = module(ROOT / "scripts/複合検証/データ準備.py", "広域研究の入力共有")
METRICS = module(ROOT / "scripts/入口探索/評価.py", "広域研究の評価共有")
JST = OLD.JST


def read_json(path: Path) -> dict:
    """UTF-8の正式JSONを読む。

    引数: path (Path) は入力。
    返り値: dict は設定・台帳・固定記録。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: object) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、value (object) はJSONへ変換可能な内容。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    """異なる候補にも共通列順で集計を保存する。

    引数: path (Path) は出力、rows (list[dict]) は行。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    """ファイル内容の識別子を計算する。

    引数: path (Path) はファイル。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------
# 足形成・指標。入力の未来値と未確定足を過去の判断へ混ぜない。

def bars_from_events(events: list[Any], start: float, finish: float, minutes: int) -> list[dict]:
    """価格観測から完全な時間幅の足と、その確定を知れる時刻を作る。

    引数: events (list[Any]) は非後退の場内状態、start/finish (float) はザラバ秒、minutes (int) は足幅。
    返り値: list[dict] はOHLC、確認時計/行、欠枠、発動可否を持つ足。
    """
    width = minutes * 60
    result, current = [], None
    previous_index = None
    for event in events:
        index = int((event.now - start) // width)
        if current is not None and index != current["index"]:
            current.update(confirm=event.now, confirm_line=event.line, publish=True)
            if current["end"] <= finish:
                result.append(current)
            current = None
        if event.now >= finish or not OLD.shared.legacy.positive(event.last):
            continue
        if current is None:
            missing = index if previous_index is None else index - previous_index - 1
            current = {"index": index, "start": start + index * width, "end": start + (index + 1) * width,
                       "open": event.last, "high": event.last, "low": event.last, "close": event.last,
                       "missing": max(0, missing), "minutes": minutes}
            previous_index = index
        else:
            current["high"] = max(current["high"], event.last)
            current["low"] = min(current["low"], event.last)
            current["close"] = event.last
    if current is not None and current["end"] <= finish:
        current.update(confirm=finish, confirm_line=0, publish=False)
        result.append(current)
    return result


class Indicators:
    """同じ尺度の確定足だけでEMA・Wilder系列・BBを更新する。"""

    def __init__(self) -> None:
        """欠枠または限月変更時にも使える空の指標状態を作る。

        引数: なし。
        返り値: None。
        """
        average = OLD.shared.legacy.Average
        self.emas = {n: average(n, 2 / (n + 1)) for n in (10, 20)}
        self.atr = average(14, 1 / 14)
        self.up, self.down = average(14, 1 / 14), average(14, 1 / 14)
        self.plus, self.minus, self.adx = (average(14, 1 / 14) for _ in range(3))
        self.closes = deque(maxlen=20)
        self.previous = None

    def update(self, bar: dict) -> dict:
        """一つの確定足から指標値を返す。

        引数: bar (dict) は確定OHLC。
        返り値: dict は未準備をNoneとする指標。DX分母0は0、RSIの上下幅とも0は未定義。
        """
        result = {"close": bar["close"], "atr": None, "rsi": None, "plus_di": None,
                  "minus_di": None, "adx": None, "bb_mean": None, "bb_sd": None}
        for n, ema in self.emas.items():
            result[f"ema{n}_previous"] = ema.value
            result[f"ema{n}"] = ema.update(bar["close"])
        self.closes.append(bar["close"])
        if len(self.closes) == 20:
            result["bb_mean"] = float(np.mean(self.closes))
            result["bb_sd"] = float(np.std(self.closes, ddof=0))
        if self.previous is not None:
            prior = self.previous
            change = bar["close"] - prior["close"]
            atr = self.atr.update(max(bar["high"] - bar["low"], abs(bar["high"] - prior["close"]), abs(bar["low"] - prior["close"])))
            gain, loss = self.up.update(max(0, change)), self.down.update(max(0, -change))
            rise, fall = bar["high"] - prior["high"], prior["low"] - bar["low"]
            plus = self.plus.update(rise if rise > 0 and rise > fall else 0.0)
            minus = self.minus.update(fall if fall > 0 and fall > rise else 0.0)
            result["atr"] = atr
            if gain is not None and loss is not None and gain + loss > 0:
                result["rsi"] = 100 * gain / (gain + loss)
            if atr is not None and plus is not None and minus is not None:
                pdi, mdi = (100 * plus / atr, 100 * minus / atr) if atr > 0 else (0.0, 0.0)
                dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi > 0 else 0.0
                result.update(plus_di=pdi, minus_di=mdi, adx=self.adx.update(dx))
        self.previous = bar
        return result


def features(bars: list[dict], indicator: Indicators, start: float) -> list[dict]:
    """同場の価格窓と指標から、結果を見ずに発動フラグを作る。

    引数: bars (list[dict]) は一尺度一場、indicator (Indicators) は履歴、start (float) は開始秒。
    返り値: list[dict] は確定足に対応する特徴。indicatorは末尾状態へ更新される。
    """
    history = deque(maxlen=20)
    previous = None
    opening, opening_bars = {}, []
    opening_valid = True
    result = []
    for bar in bars:
        if bar["missing"]:
            indicator.__init__()
            history.clear()
            previous = None
            opening_valid = False
        values = indicator.update(bar)
        row = {**bar, **values, "has_previous": previous is not None}
        if bar["start"] < start + 1800:
            opening_bars.append(bar)
        for window in (15, 30):
            if opening_valid and bar["end"] == start + window * 60:
                opening[window] = (max(b["high"] for b in opening_bars), min(b["low"] for b in opening_bars))
            for side in (1, -1):
                row[f"開始幅突破_{window}_{side}"] = False
                row[f"開始幅失敗復帰_{window}_{side}"] = False
            if window in opening and previous is not None and bar["start"] >= start + window * 60:
                high, low = opening[window]
                row[f"開始幅突破_{window}_1"] = previous["close"] <= high < bar["close"]
                row[f"開始幅突破_{window}_-1"] = previous["close"] >= low > bar["close"]
                row[f"開始幅失敗復帰_{window}_1"] = previous["close"] < low <= bar["close"] <= high
                row[f"開始幅失敗復帰_{window}_-1"] = previous["close"] > high >= bar["close"] >= low
        for length in (4, 7):
            prior = list(history)[-length:]
            narrow = len(prior) == length and prior[-1]["high"] - prior[-1]["low"] < min(b["high"] - b["low"] for b in prior[:-1])
            row[f"狭幅突破_{length}_1"] = narrow and bar["close"] > prior[-1]["high"]
            row[f"狭幅突破_{length}_-1"] = narrow and bar["close"] < prior[-1]["low"]
        for length in (10, 20):
            prior = list(history)[-length:]
            high = max((b["high"] for b in prior), default=math.inf)
            low = min((b["low"] for b in prior), default=-math.inf)
            ready = len(prior) == length
            row[f"高安端復帰_{length}_1"] = ready and bar["low"] < low < bar["close"] <= high
            row[f"高安端復帰_{length}_-1"] = ready and bar["high"] > high > bar["close"] >= low
            ema, before = row[f"ema{length}"], row[f"ema{length}_previous"]
            ready = previous is not None and ema is not None and before is not None
            row[f"EMA復帰_{length}_1"] = ready and previous["close"] <= before and bar["close"] > ema > before
            row[f"EMA復帰_{length}_-1"] = ready and previous["close"] >= before and bar["close"] < ema < before
        for multiple in (2.0, 2.5):
            ready = previous is not None and previous["bb_mean"] is not None and row["bb_mean"] is not None
            row[f"BB内復帰_{multiple}_1"] = ready and previous["close"] < previous["bb_mean"] - multiple * previous["bb_sd"] and bar["close"] >= row["bb_mean"] - multiple * row["bb_sd"]
            row[f"BB内復帰_{multiple}_-1"] = ready and previous["close"] > previous["bb_mean"] + multiple * previous["bb_sd"] and bar["close"] <= row["bb_mean"] + multiple * row["bb_sd"]
        result.append(row)
        history.append(bar)
        previous = row
    return result


def rules(config: dict) -> list[dict]:
    """計画の147候補を固定順で展開する。

    引数: config (dict) は条件JSON。
    返り値: list[dict] はID・尺度・手法・パラメータ・補助。
    """
    result = []
    for size in config["時間足分"]:
        result.append({"候補ID": f"対照{size}分", "時間足分": size, "手法": "全時点両方向", "パラメータ": None, "補助": "なし"})
        for family, parameters in config["手法"].items():
            for parameter in parameters:
                for extra in config["補助条件"]:
                    result.append({"候補ID": f"{size}分_{family}_{parameter}_{extra}", "時間足分": size,
                                   "手法": family, "パラメータ": parameter, "補助": extra})
    if len(result) != config["候補数"]:
        raise ValueError("候補数が計画と一致しない")
    return result


def allowed(row: dict, rule: dict) -> bool:
    """一つの確定時点に、固定規則を当てはめる。

    引数: row (dict) は入口前特徴、rule (dict) は候補設定。
    返り値: bool は発動の可否。将来ラベルは一切参照しない。
    """
    if row["時間足分"] != rule["時間足分"]:
        return False
    family, parameter, side = rule["手法"], rule["パラメータ"], row["side"]
    if family == "全時点両方向":
        return True
    if not row.get(f"{family}_{parameter}_{side}", False):
        return False
    extra = rule["補助"]
    if extra == "上位方向":
        return row["上位方向"] == side
    if extra == "ADX環境":
        if row["adx"] is None:
            return False
        if family in TREND:
            directional = row["plus_di"] > row["minus_di"] if side == 1 else row["minus_di"] > row["plus_di"]
            return row["adx"] >= 25 and directional
        return row["adx"] < 20
    if extra == "RSI帯":
        if row["rsi"] is None:
            return False
        directional = row["rsi"] if side == 1 else 100 - row["rsi"]
        return 50 <= directional < 70 if family in TREND else 30 <= directional <= 50
    return True


# ----------------------------------------
# データ台帳を固定し、探索と新しい四場の検査を分離する。

def prepare(study: Path, phase: str, selected: dict | None = None) -> tuple[list[dict], list[dict]]:
    """指定した分割だけをラベル化し、履歴と品質を記録する。

    引数: study (Path) は試行、phase (str) は探索/後続、selected (dict | None) は後続で許可する固定規則。
    返り値: tuple[list[dict], list[dict]] は入口事例と場別品質。
    """
    config, manifest = read_json(study / "条件.json"), read_json(study / "入力台帳.json")
    banks = {n: Indicators() for n in (1, 3, 5, 15)}
    result, quality = [], []
    previous_contract = None
    for entry in manifest["entries"]:
        session = entry["session"]
        future = session[:10] >= config["分割"]["後続開始日"]
        if phase == "探索" and future:
            continue
        publish = (phase == "探索" and not future) or (phase == "後続" and future)
        source = ROOT.parent / "JP_OSE_Data/future" / entry["source_path"]
        stat = source.stat()
        cache = ROOT / "work/複合検証" / entry["cache_path"]
        if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or sha(cache) != entry["sha256_cache"]:
            raise ValueError(f"入力が固定台帳と異なる: {session}")
        contract = tuple(entry["in_session_contract_codes"])
        if len(contract) != 1:
            raise ValueError("場内限月が一意でない")
        if previous_contract is not None and previous_contract != contract:
            banks = {n: Indicators() for n in banks}
        previous_contract = contract
        start, finish, cutoff, deadline = OLD.shared.legacy.session_times(session)
        begin, end = start.timestamp(), finish.timestamp()
        events, previous_now, backwards = [], -math.inf, 0
        for event in PREP.read_events(cache):
            if not math.isfinite(event.now) or event.now < begin or event.now > end:
                continue
            if event.now < previous_now:
                backwards += 1
                continue
            previous_now = event.now
            events.append(event)
        all_features, tails = {}, {}
        for size, bank in banks.items():
            formed = bars_from_events(events, begin, end, size)
            all_features[size] = features(formed, bank, begin)
            complete = int((end - begin) // (size * 60))
            tail_missing = max(0, complete - 1 - (formed[-1]["index"] if formed else -1))
            tails[size] = tail_missing
            if tail_missing:
                bank.__init__()
        if not publish:
            continue
        quotes = [event for event in events if event.valid]
        path = OLD.気配経路(quotes)
        day_quality = {"場": session, "時計後退除外": backwards, "正常板": len(quotes), "候補数": 0}
        higher = all_features[15]
        for size in config["時間足分"]:
            day_quality[f"{size}分_確定足"] = sum(f["publish"] for f in all_features[size])
            day_quality[f"{size}分_欠枠"] = sum(f["missing"] for f in all_features[size])
            day_quality[f"{size}分_尾部欠枠"] = tails[size]
            position, upper = 0, None
            for frame in all_features[size]:
                while position < len(higher) and (higher[position]["confirm"], higher[position]["confirm_line"]) <= (frame["confirm"], frame["confirm_line"]) and higher[position]["end"] <= frame["end"]:
                    upper = higher[position]
                    position += 1
                direction = 0
                if upper is not None and upper["publish"] and upper["ema20_previous"] is not None:
                    if upper["close"] > upper["ema20"] > upper["ema20_previous"]:
                        direction = 1
                    elif upper["close"] < upper["ema20"] < upper["ema20_previous"]:
                        direction = -1
                signal = frame["confirm"]
                ready = frame["publish"] and frame["has_previous"] and frame["atr"] is not None and frame["atr"] > 0
                if not ready or signal >= cutoff.timestamp() or deadline.timestamp() - signal < config["残り時間下限分"] * 60:
                    continue
                for side in (1, -1):
                    row = {**frame, "イベントID": f"NK225_{session}_{size}分_{frame['index']:04d}_{side}",
                           "場": session, "時間足分": size, "side": side, "方向": "買い" if side == 1 else "売り",
                           "上位方向": direction, "上位足終了秒": None if upper is None else upper["end"],
                           "上位確認秒": None if upper is None else upper["confirm"],
                           "要求時計秒": signal, "要求時計JST": datetime.fromtimestamp(signal, JST).isoformat(),
                           "要求原板行": frame["confirm_line"], "足終了時計秒": frame["end"],
                           "確認遅延秒": signal - frame["end"], "残り分_判断時": (deadline.timestamp() - signal) / 60,
                           "新規停止時計秒": cutoff.timestamp(), "期限時計秒": deadline.timestamp()}
                    if selected is not None and not allowed(row, selected):
                        continue
                    if row["確認遅延秒"] > config["確認遅延上限秒"]:
                        label = {"ラベル": "未約定", "理由": "足確定確認遅延30秒超", "新規価格": None,
                                 "新規時計秒": None, "判定時計秒": None, "判定原板行": None,
                                 "新規原板行": None, "判定気配": None, "最大順行pt": None, "最大逆行pt": None, "所要分": None}
                    else:
                        label = path.evaluate(signal, cutoff.timestamp(), deadline.timestamp(), side,
                                              adverse=config["逆行pt"], favorable=config["順行pt"])
                    row.update(label)
                    row["新規時計JST"] = None if row["新規時計秒"] is None else datetime.fromtimestamp(row["新規時計秒"], JST).isoformat()
                    result.append(row)
                    day_quality["候補数"] += 1
        quality.append(day_quality)
        print(f"{phase} 入力処理 {session} 完了", flush=True)
    return result, quality


def metrics(rows: list[dict], phase: str) -> dict:
    """主率・件数・日別・事前時計間引きを共有仕様で集計する。

    引数: rows (list[dict]) は一候補の事例、phase (str) は分割名。
    返り値: dict は集計。
    """
    return METRICS.evaluate(rows, np.ones(len(rows), dtype=bool), phase)


def supported(result: dict, limits: dict) -> bool:
    """期間別の最低件数・日数・場数を判定する。

    引数: result (dict) は集計、limits (dict) は下限。
    返り値: bool は全下限を満たすか。
    """
    return all(result[key] >= value for key, value in limits.items())


def fixed_files(study: Path) -> dict[str, str]:
    """後続前に固定する入力・実装・結果のSHAを列挙する。

    引数: study (Path) は試行。
    返り値: dict[str, str] はルート相対パスとSHA256。
    """
    paths = [Path(__file__), ROOT / "scripts/入口分析/分析.py", ROOT / "scripts/複合検証/再生.py",
             ROOT / "scripts/複合検証/データ準備.py", ROOT / "scripts/入口探索/評価.py",
             ROOT / "study/00001_MACDと方向条件の比較/再現.py", study / "条件.json", study / "計画.md",
             study / "入力台帳.json", study / "全候補_探索.csv"]
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}


def save_work(rows: list[dict], path: Path) -> None:
    """大きな入口中間表をGit外へ圧縮保存する。

    引数: rows (list[dict]) は入口行、path (Path) はgzip保存先。
    返り値: None。
    """
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def search(study: Path) -> None:
    """既使用60場で147候補を比較し、後続用一候補を固定する。

    引数: study (Path) は正式試行。
    返り値: None。後続済みの再探索は拒否する。
    """
    if (study / "後続結果.json").exists():
        raise ValueError("後続確認済み。条件の選び直しは新試行へ分ける")
    config = read_json(study / "条件.json")
    rows, quality = prepare(study, "探索")
    WORK.mkdir(parents=True, exist_ok=True)
    save_work(rows, WORK / "00006_探索事例.jsonl.gz")
    split_day = config["分割"]["選択開始日"]
    parts = {"学習": [r for r in rows if r["場"][:10] < split_day],
             "条件選択": [r for r in rows if r["場"][:10] >= split_day]}
    reports, details = [], {}
    for rule in rules(config):
        report = dict(rule)
        values, chosen = {}, {}
        for name, part in parts.items():
            chosen[name] = [row for row in part if allowed(row, rule)]
            values[name] = metrics(chosen[name], name)
            opposite = {(r["場"], r["時間足分"], r["index"], r["side"]): r for r in part}
            control = [matched for r in chosen[name] for matched in
                       (r, opposite[(r["場"], r["時間足分"], r["index"], -r["side"])])]
            comparison = metrics(control, name)
            values[name]["同時刻両方向対照率"] = comparison["確認率"]
            values[name]["同時刻差pp"] = None if values[name]["確認率"] is None else 100 * (values[name]["確認率"] - comparison["確認率"])
            for key, value in values[name].items():
                if key != "分割":
                    report[name + "_" + key] = value
        support = all(supported(values[name], config["支持条件"][name]) for name in parts)
        reached = support and all(values[name]["確認率"] >= config["目標率"] and values[name]["30分間引き_約定候補数"] >= config["間引き支持"][name]
                                  and values[name]["30分間引き_確認率"] >= config["目標率"] for name in parts)
        report.update(支持条件=support, 探索70条件=reached)
        reports.append(report)
        details[rule["候補ID"]] = {"規則": rule, "結果": values, "事例": chosen}
    write_csv(study / "全候補_探索.csv", reports)
    write_json(study / "入力品質_探索.json", quality)
    eligible = [r for r in reports if r["手法"] != "全時点両方向" and r["学習_約定候補数"] >= 20 and r["条件選択_約定候補数"] >= 10]
    if not eligible:
        write_json(study / "探索結果.json", {"状態": "選択最低件数も不足", "候補数": len(reports), "固定候補": None})
        return
    def order(record: dict) -> tuple:
        """事前に固定した順位で比較する。

        引数: record (dict) は候補集計。
        返り値: tuple は大きい順の比較キー。同順位は生成順。
        """
        return (record["探索70条件"], record["支持条件"], min(record["学習_確認率"], record["条件選択_確認率"]),
                min(record["学習_30分間引き_確認率"] or 0, record["条件選択_30分間引き_確認率"] or 0), record["条件選択_約定候補数"])
    best = max(eligible, key=order)
    detail = details[best["候補ID"]]
    lock = {"固定日時": datetime.now(JST).isoformat(), "候補ID": best["候補ID"], "規則": detail["規則"],
            "探索結果": detail["結果"], "探索候補数": len(reports),
            "支持候補数": sum(bool(r["支持条件"]) for r in reports if r["手法"] != "全時点両方向"),
            "探索70候補数": sum(bool(r["探索70条件"]) for r in reports if r["手法"] != "全時点両方向"),
            "位置付け": "70条件を満たす候補" if best["探索70条件"] else "目標未達の診断用固定候補",
            "後続状態": "新しい4場は未評価。固定後に一候補だけ評価する",
            "Python": platform.python_version(), "NumPy": np.__version__, "ファイルSHA256": fixed_files(study)}
    write_json(study / "選択固定.json", lock)
    write_json(study / "探索結果.json", {key: value for key, value in lock.items() if key != "ファイルSHA256"})
    write_csv(study / "固定候補_探索事例.csv", [{key: row.get(key) for key in ("イベントID", "場", "時間足分", "方向", "要求時計JST", "新規時計JST", "新規価格", "ラベル", "理由", "判定気配", "最大順行pt", "最大逆行pt")} for name in parts for row in detail["事例"][name]])
    print(json.dumps({"固定候補": best["候補ID"], "候補数": len(reports), "探索70候補数": lock["探索70候補数"], "結果": detail["結果"]}, ensure_ascii=False), flush=True)


def confirm(study: Path) -> None:
    """固定済みの一候補だけを新しい4場で評価する。

    引数: study (Path) は正式試行。
    返り値: None。固定不一致と後続上書きを拒否する。
    """
    if (study / "後続結果.json").exists():
        raise ValueError("後続結果は既存。新試行で再研究する")
    fixed = read_json(study / "選択固定.json")
    for name, expected in fixed["ファイルSHA256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"固定後の変更: {name}")
    config = read_json(study / "条件.json")
    rows, quality = prepare(study, "後続", fixed["規則"])
    report = metrics(rows, "後続検査")
    support = supported(report, config["支持条件"]["後続検査"])
    reached = bool(fixed["探索70候補数"] and support and report["確認率"] >= .7
                   and report["30分間引き_約定候補数"] >= 10 and report["30分間引き_確認率"] >= .7)
    result = {"候補ID": fixed["候補ID"], "評価日時": datetime.now(JST).isoformat(), "結果": report,
              "支持条件": support, "探索後続70条件": reached, "選択固定SHA256": sha(study / "選択固定.json"),
              "限界": "新規後続は2開始日4場。支持日数・場数に不足し、70%の確立とはしない"}
    write_json(study / "後続結果.json", result)
    write_json(study / "入力品質_後続.json", quality)
    save_work(rows, WORK / "00006_後続事例.jsonl.gz")
    write_csv(study / "後続事例.csv", [{key: row.get(key) for key in ("イベントID", "場", "時間足分", "方向", "要求時計JST", "要求時計秒", "新規時計JST", "新規時計秒", "新規価格", "ラベル", "理由", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt")} for row in rows])
    write_csv(study / "後続日別.csv", METRICS.group_by_day(rows, np.ones(len(rows), dtype=bool)))
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main() -> None:
    """実行段階をコマンド引数で選択する。

    引数: なし。study/phaseを引数から読む。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="六手法×三時間足×補助条件の比較")
    parser.add_argument("--study", type=Path, default=DEFAULT_STUDY)
    parser.add_argument("--phase", choices=("探索", "後続"), required=True)
    args = parser.parse_args()
    study = args.study.resolve()
    search(study) if args.phase == "探索" else confirm(study)


if __name__ == "__main__":
    main()
