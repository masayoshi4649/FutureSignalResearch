"""00013の全入口を、原価格からの独立足・指標と区間走査で再構成する。"""

from __future__ import annotations

from collections import Counter, deque
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00013_収縮後の突破と失敗反転"
WORK = ROOT / "work/収縮反転/00013"
MANIFEST = ROOT / "study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"
HELPER = ROOT / "scripts/広域研究/独立監査.py"


def read(path: Path) -> Any:
    """日本語JSONを読む。

    引数: path (Path) は対象。
    返り値: Any はJSON値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """小型資料とcacheのSHA256を計算する。

    引数: path (Path) は対象。巨大原板本文には使わない。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def independent_indicator() -> Any:
    """既存の独立Wilder計算だけを読み込む。

    引数: なし。
    返り値: Any は旧独立監査。元の入口・指標・運用classは読み込まない。
    """
    spec = importlib.util.spec_from_file_location("収縮確認の独立Wilder", HELPER)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


G = independent_indicator()


class Audit:
    """比較数と先頭100差分を保持する。"""

    def __init__(self) -> None:
        """空の照合結果を作る。

        引数: なし。
        返り値: None。
        """
        self.count, self.mismatches, self.errors = 0, 0, []

    def check(self, name: str, actual: Any, expected: Any) -> None:
        """数値は絶対誤差1e-7、他は同値で比較する。

        引数: name (str) は項目、actual/expected (Any) は値。
        返り値: None。辞書は各項目を再帰比較する。
        """
        if isinstance(expected, dict) and isinstance(actual, dict):
            self.check(name + ":キー", set(actual), set(expected))
            for key in expected.keys() & actual.keys():
                self.check(name + ":" + key, actual[key], expected[key])
            return
        self.count += 1
        if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
            same = math.isclose(actual, expected, rel_tol=0, abs_tol=1e-7)
        else:
            same = actual == expected
        if not same:
            self.mismatches += 1
            if len(self.errors) < 100:
                self.errors.append({"項目": name, "保存": sorted(actual) if isinstance(actual, set) else actual,
                                    "独立": sorted(expected) if isinstance(expected, set) else expected})


class Indicators:
    """EMA20とBB20を独立計算し、ATR/ADXは独立Wilder補助を使う。"""

    def __init__(self) -> None:
        """同じ尺度の指標を未準備へ戻す。

        引数: なし。
        返り値: None。
        """
        self.closes, self.seed = deque(maxlen=20), []
        self.ema = None
        self.wilder = G.Indicator()

    def add(self, bar: dict) -> dict:
        """一足の終値・高安から必要な指標を再計算する。

        引数: bar (dict) は独立OHLC。
        返り値: dict はEMA前値/現在、ATR/ADX、平均と母標準偏差を付けた足。
        """
        previous_ema = self.ema
        close = bar["close"]
        if self.ema is None:
            self.seed.append(close)
            if len(self.seed) == 20:
                self.ema = sum(self.seed) / 20
        else:
            self.ema += 2 / 21 * (close - self.ema)
        self.closes.append(close)
        mean = sum(self.closes) / 20 if len(self.closes) == 20 else None
        sd = math.sqrt(sum((p - mean) ** 2 for p in self.closes) / 20) if mean is not None else None
        return {**bar, **self.wilder.add(bar), "ema20_previous": previous_ema, "ema20": self.ema,
                "bb_mean": mean, "bb_sd": sd}


# ----------------------------------------
# 原価格の半開区間から足を作り、確認に使える最初の原行を独立に取得する。

def observed(entry: dict) -> dict[str, np.ndarray]:
    """固定cacheの場内非後退列を読み取る。

    引数: entry (dict) は固定台帳行。
    返り値: dict[str,np.ndarray] は価格時計・原行・Last列。原板は変更/複製しない。
    """
    source = ROOT.parent / "JP_OSE_Data/future" / entry["source_path"]
    stat = source.stat()
    if (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
        raise ValueError("固定原板statが変更")
    path = ROOT / "work/複合検証" / entry["cache_path"]
    if sha(path) != entry["sha256_cache"] or path.stat().st_size != entry["cache_size"]:
        raise ValueError("固定cache指紋が不一致")
    start, finish, _, _ = G.times(entry["session"])
    with np.load(path, allow_pickle=False) as archive:
        a = {key: archive[key] for key in ("now", "line", "last")}
    indices = np.flatnonzero(np.isfinite(a["now"]) & (a["now"] >= start) & (a["now"] <= finish))
    times = a["now"][indices]
    if len(times):
        indices = indices[np.r_[True, times[1:] >= np.maximum.accumulate(times[:-1])]]
    return {key: value[indices] for key, value in a.items()}


def bars(data: dict, session: str, minutes: int, state: Indicators) -> list[dict]:
    """3/5/15分のOHLC・最初の確認原行・欠枠を別方式で形成する。

    引数: data (dict) は場内状態、session (str) は場、minutes (int) は尺度、state (Indicators) は持越し指標。
    返り値: list[dict] は完全時間幅の足。欠枠/前場尾部欠枠で指標をリセットする。
    """
    begin, finish, _, _ = G.times(session)
    positive = np.isfinite(data["last"]) & (data["last"] > 0) & (data["now"] < finish)
    times, prices = data["now"][positive], data["last"][positive]
    indices = ((times - begin) // (60 * minutes)).astype(int)
    heads = np.flatnonzero(np.r_[True, indices[1:] != indices[:-1]]) if len(indices) else []
    tails = np.r_[heads[1:], len(prices)] if len(indices) else []
    output, previous_index = [], None
    for head, tail in zip(heads, tails):
        index = int(indices[head])
        start, end = begin + index * 60 * minutes, begin + (index + 1) * 60 * minutes
        if end > finish:
            continue
        missing = index if previous_index is None else index - previous_index - 1
        if missing:
            state.__init__()
        confirm_at = int(np.searchsorted(data["now"], end, side="left"))
        known = confirm_at < len(data["now"])
        values = prices[head:tail]
        bar = {"index": index, "start": start, "end": end, "minutes": minutes,
               "open": float(values[0]), "high": float(np.max(values)), "low": float(np.min(values)), "close": float(values[-1]),
               "missing": missing, "publish": known, "confirm": float(data["now"][confirm_at]) if known else finish,
               "confirm_line": int(data["line"][confirm_at]) if known else 0}
        output.append(state.add(bar))
        previous_index = index
    complete = int((finish - begin) // (60 * minutes))
    if not output or output[-1]["index"] < complete - 1:
        state.__init__()
    return output


def finite(*values: Any) -> bool:
    """必要値が全て有限か判定する。

    引数: values (Any) は値列。
    返り値: bool は全て有限数なら真。
    """
    return all(v is not None and math.isfinite(v) for v in values)


def contexts(frames: list[dict], higher: list[dict], session: str) -> list[dict]:
    """各足の有効幅・連続区間・収縮候補・当時既知の上位準備を先計算する。

    引数: frames/higher (list[dict]) は独立の下位/15分足、session (str) は場。
    返り値: list[dict] は当足含む20幅と6高安を持つ候補列。
    """
    output, segment, consecutive, previous = [], 0, 0, None
    for frame in frames:
        mean, sd = frame["bb_mean"], frame["bb_sd"]
        width = 4 * sd / mean if finite(mean, sd) and mean > 0 and sd > 0 else None
        valid = frame["publish"] and width is not None and math.isfinite(width) and width > 0
        gap = previous is None or frame["missing"] or frame["index"] != previous["index"] + 1
        if not valid:
            consecutive = 0
            segment += 1
        else:
            if gap or consecutive == 0:
                segment += 1
                consecutive = 0
            consecutive += 1
        available = [u for u in higher if u["end"] <= frame["end"] and
                     (u["confirm"], u["confirm_line"]) <= (frame["confirm"], frame["confirm_line"])]
        upper = available[-1] if available else None
        ready = upper is not None and upper["publish"] and finite(upper["close"], upper["ema20"], upper["ema20_previous"])
        direction = 0
        if ready:
            direction = 1 if upper["close"] > upper["ema20"] > upper["ema20_previous"] else (
                -1 if upper["close"] < upper["ema20"] < upper["ema20_previous"] else 0)
        current = {**frame, "帯幅": width, "区間": segment if valid else None,
                   "上位準備済": bool(ready), "上位方向": direction,
                   "上位確認秒": upper["confirm"] if upper else None,
                   "上位確認行": upper["confirm_line"] if upper else None,
                   "上位足終了秒": upper["end"] if upper else None, "収縮候補": False}
        output.append(current)
        if valid and consecutive >= 20:
            window = output[-20:]
            current["収縮候補"] = width <= min(r["帯幅"] for r in window)
            recent = output[-6:]
            current["収縮設定候補"] = {key: current[key] for key in ("index", "end", "confirm", "confirm_line", "bb_mean", "帯幅")}
            current["収縮設定候補"].update(固定高値=max(r["high"] for r in recent), 固定安値=min(r["low"] for r in recent))
        previous = frame
    return output


# ----------------------------------------
# 元の一足ごとの状態機械を使わず、収縮候補から次の区間を走査して全発動を再構成する。

def interval_events(frames: list[dict], session: str) -> dict[str, dict]:
    """未突破期間と突破後期間を区間探索し、共通状態から補助を適用する。

    引数: frames (list[dict]) は事前計算済み候補列、session (str) は場。
    返り値: dict[str,dict] はイベントID別の独立入口。
    """
    _, _, cutoff, deadline = G.times(session)
    output = {}

    def emit(at: int, setup_at: int, broken_at: int, side: int, family: str) -> None:
        """状態の消費後に発動資格と上位補助だけを適用する。

        引数: at/setup_at/broken_at (int) は現足/設定/突破の配列位置、side (int) は方向、family (str) は系統。
        返り値: None。状態探索の継続条件に発動可否を使わない。
        """
        r, setup_row, break_row = frames[at], frames[setup_at], frames[broken_at]
        ready = finite(r["ema20"], r["atr"], r["adx"], r["bb_mean"], r["bb_sd"]) and r["atr"] > 0 and r["上位準備済"]
        if not ready or r["confirm"] >= cutoff or deadline - r["confirm"] < 3600:
            return
        setup = setup_row["収縮設定候補"]
        broken = {key: break_row[key] for key in ("index", "end", "confirm", "confirm_line", "帯幅")}
        broken["side"] = 1 if break_row["close"] > setup["固定高値"] else -1
        for extra in ("なし", "15分方向一致"):
            if extra == "15分方向一致" and r["上位方向"] != side:
                continue
            source = f'{r["minutes"]}分_{family}_{extra}'
            identity = f'NK225_{session}_{source}_{r["index"]:04d}_{side}'
            output[identity] = {**r, "場": session, "入口ID": source, "入口系統": family, "補助": extra, "side": side,
                                "イベントID": identity, "収縮設定": dict(setup), "突破登録": broken,
                                "収縮からの経過足": r["index"] - setup_row["index"],
                                "突破からの経過足": r["index"] - break_row["index"]}

    cursor, length = 0, len(frames)
    while cursor < length:
        candidates = [i for i in range(cursor, length) if frames[i]["収縮候補"]]
        if not candidates:
            break
        setup_at = candidates[0]
        j = setup_at + 1
        while True:
            if j >= length:
                cursor = length
                break
            current, setup = frames[j], frames[setup_at]
            if current["区間"] != setup["区間"] or current["index"] - setup["index"] > 6:
                cursor = j
                break
            low, high = setup["収縮設定候補"]["固定安値"], setup["収縮設定候補"]["固定高値"]
            side = 1 if current["close"] > high else (-1 if current["close"] < low else 0)
            if side:
                if current["帯幅"] <= setup["帯幅"]:
                    cursor = j
                    break
                emit(j, setup_at, j, side, "突破追随")
                k = j + 1
                while k < length and frames[k]["区間"] == setup["区間"] and frames[k]["index"] - current["index"] <= 3:
                    close = frames[k]["close"]
                    if (side == 1 and close <= low) or (side == -1 and close >= high):
                        break
                    if low < close < high:
                        emit(k, setup_at, j, -side, "突破失敗反転")
                        break
                    k += 1
                cursor = k
                break
            if current["収縮候補"]:
                setup_at = j
            j += 1
    return output


def run() -> dict:
    """全65場を独立再構成し、全入口集合と保存設定を原価格に照合する。

    引数: なし。既使用65場の固定cacheだけを読み取る。
    返り値: dict は明示合否・件数・範囲・指紋。元13コードを実行しない。
    """
    audit = Audit()
    with gzip.open(WORK / "入口事例.jsonl.gz", "rb") as stream:
        body = stream.read()
    cases = [json.loads(line) for line in body.splitlines() if line.strip()]
    saved = {r["イベントID"]: r for r in cases}
    audit.check("保存イベントID一意", len(saved), len(cases))
    entries = read(MANIFEST)["entries"]
    banks, last_contract = {n: Indicators() for n in (3, 5, 15)}, None
    expected, frame_count, candidate_count = {}, Counter(), Counter()
    for entry in entries:
        contract = tuple(entry["in_session_contract_codes"])
        if last_contract is not None and contract != last_contract:
            banks = {n: Indicators() for n in banks}
        last_contract = contract
        data, session = observed(entry), entry["session"]
        formed = {n: bars(data, session, n, bank) for n, bank in banks.items()}
        for n in (3, 5):
            ready = contexts(formed[n], formed[15], session)
            independent = interval_events(ready, session)
            if set(independent) & set(expected):
                raise ValueError("独立イベントIDが重複")
            expected.update(independent)
            frame_count[str(n)] += len(ready)
            candidate_count[str(n)] += sum(r["収縮候補"] for r in ready)
        frame_count["15"] += len(formed[15])
    audit.check("全8入口イベント集合", set(saved), set(expected))
    fields = ("index", "start", "end", "minutes", "open", "high", "low", "close", "missing", "publish",
              "confirm", "confirm_line", "ema20", "ema20_previous", "atr", "adx", "bb_mean", "bb_sd", "帯幅",
              "上位準備済", "上位方向", "上位確認秒", "上位確認行", "上位足終了秒", "side",
              "収縮設定", "突破登録", "収縮からの経過足", "突破からの経過足")
    for identity in saved.keys() & expected.keys():
        for field in fields:
            audit.check(identity + ":" + field, saved[identity][field], expected[identity][field])
    result = {"全件一致": audit.mismatches == 0, "照合項目数": audit.count, "不一致数": audit.mismatches, "不一致": audit.errors,
              "保存入口数": len(cases), "独立入口数": len(expected), "入力場数": len(entries),
              "独立足数": dict(frame_count), "事前計算した収縮候補数": dict(candidate_count),
              "入口別件数": dict(Counter(r["入口ID"] for r in expected.values())),
              "コードSHA256": sha(Path(__file__)), "独立Wilder補助SHA256": sha(HELPER),
              "入力台帳SHA256": sha(MANIFEST), "入口事例展開SHA256": hashlib.sha256(body).hexdigest(),
              "検証範囲": "原価格cacheの全65場から3/5/15分半開OHLC・確認原行・欠枠・EMA20/BB母標準偏差/ATR/ADXを別実装。20当足含収縮候補と6当足含固定高安を先計算し、未突破/突破後を区間走査して全8入口集合と保存設定・初着を照合。",
              "限界": "原板本文・取引所の全約定履歴を再取得した監査ではない。固定cacheのLast価格時計に基づく。元の00013入口/検証/元指標classはimportせず、Wilderだけ旧独立補助を再利用。価格時計を受信時計としない。"}
    target = WORK / "状態独立確認.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("全件一致", "照合項目数", "不一致数", "保存入口数", "独立入口数")}, ensure_ascii=False))
    if audit.errors:
        print(json.dumps(audit.errors[:5], ensure_ascii=False))
    return result


if __name__ == "__main__":
    if not run()["全件一致"]:
        raise SystemExit(1)
