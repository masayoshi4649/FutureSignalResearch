"""00010の代表4出口を、運用コードを呼ばず正常板と独立確定足から照合する。"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00010_順行と反転の利益保護と通常出口"
SOURCE = ROOT / "study/00008_外部研究を共通尺度へ移して探索"
DETAIL = ROOT / "work/利益回収/00010/全運用詳細.jsonl.gz"
OUTPUT = ROOT / "work/利益回収/出口独立確認.json"
JST = timezone(timedelta(hours=9))


def sha(path: Path) -> str:
    """小型入力またはcacheのSHA256を計算する。

    引数: path (Path) は対象。原板本文には使わない。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounds(session: str) -> tuple[float, float, float]:
    """場開始・ザラバ終了・期限を独立に求める。

    引数: session (str) は開始日基準の場名。
    返り値: tuple[float,float,float] はUnix秒。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith("Day"):
        times = day.replace(hour=8, minute=45), day.replace(hour=15, minute=40), day.replace(hour=15, minute=35)
    else:
        next_day = day + timedelta(days=1)
        times = day.replace(hour=17), next_day.replace(hour=5, minute=55), next_day.replace(hour=5, minute=50)
    return tuple(t.timestamp() for t in times)


def load(entry: dict) -> tuple[list[dict], list[dict]]:
    """固定cacheを原順走査し場内非後退状態と正常気配を抽出する。

    引数: entry (dict) は固定入力台帳。
    返り値: tuple[list[dict],list[dict]] は場内状態と正常気配。原板は読まない。
    """
    path = ROOT / "work/複合検証" / entry["cache_path"]
    if sha(path) != entry["sha256_cache"] or path.stat().st_size != entry["cache_size"]:
        raise ValueError("cache指紋不一致")
    start, end, _ = bounds(entry["session"])
    rows, normal, previous = [], [], -math.inf
    with np.load(path, allow_pickle=False) as data:
        for now, line, last, bid, ask, valid in zip(data["now"], data["line"], data["last"], data["bid"], data["ask"], data["valid"]):
            if not math.isfinite(now) or not start <= now <= end or now < previous:
                continue
            previous = now
            row = {"now": float(now), "line": int(line), "last": float(last),
                   "bid": float(bid), "ask": float(ask)}
            rows.append(row)
            if valid and now < end:
                normal.append(row)
    return rows, normal


# ----------------------------------------
# 足は半開価格区間と初めて次区間を観測した原行から独立に作る。

class Averages:
    """EMA20・ATR14・BB中心を独立の算術種で更新する。"""

    def __init__(self) -> None:
        """指標を未準備へ戻す。

        引数: なし。
        返り値: None。
        """
        self.closes, self.ema_seed, self.tr_seed = deque(maxlen=20), [], []
        self.ema, self.atr, self.previous_close = None, None, None

    def add(self, bar: dict) -> dict:
        """一足からEMA20・ATR14・中心を計算する。

        引数: bar (dict) は独立OHLC。
        返り値: dict は指標を付けた足。差分ATR初回は前足なしとして飛ばす。
        """
        close = bar["close"]
        self.closes.append(close)
        if self.ema is None:
            self.ema_seed.append(close)
            if len(self.ema_seed) == 20:
                self.ema = sum(self.ema_seed) / 20
        else:
            self.ema += 2 / 21 * (close - self.ema)
        if self.previous_close is not None:
            tr = max(bar["high"] - bar["low"], abs(bar["high"] - self.previous_close), abs(bar["low"] - self.previous_close))
            if self.atr is None:
                self.tr_seed.append(tr)
                if len(self.tr_seed) == 14:
                    self.atr = sum(self.tr_seed) / 14
            else:
                self.atr += (tr - self.atr) / 14
        self.previous_close = close
        return {**bar, "ema": self.ema, "atr": self.atr,
                "mean": sum(self.closes) / 20 if len(self.closes) == 20 else None}


def bars(rows: list[dict], session: str, minutes: int, state: Averages) -> list[dict]:
    """状態を区間ごとに分けOHLCと最初の確認原行を再構成する。

    引数: rows (list[dict]) は場内原順、session (str) は場、
    minutes (int) は足幅、state (Averages) は前場からの同尺度履歴。
    返り値: list[dict] は完全時間幅だけの足。欠枠で履歴を初期化する。
    """
    start, end, _ = bounds(session)
    width, groups = minutes * 60, {}
    for row in rows:
        if row["now"] >= end or not math.isfinite(row["last"]) or row["last"] <= 0:
            continue
        index = int((row["now"] - start) // width)
        groups.setdefault(index, []).append(row)
    result, previous_index = [], None
    for index, values in groups.items():
        if start + (index + 1) * width > end:
            continue
        missing = index if previous_index is None else index - previous_index - 1
        if missing:
            state.__init__()
        finish = start + (index + 1) * width
        confirmed = next((r for r in rows if r["now"] >= finish), None)
        prices = [v["last"] for v in values]
        bar = {"index": index, "end": finish, "high": max(prices), "low": min(prices), "close": prices[-1],
               "confirm": confirmed["now"] if confirmed else end,
               "line": confirmed["line"] if confirmed else 0, "publish": confirmed is not None}
        result.append(state.add(bar))
        previous_index = index
    if not result or result[-1]["index"] < int((end - start) // width) - 1:
        state.__init__()
    return result


def select(trades: list[dict]) -> list[dict]:
    """結果値を順位にせず、指定出口の時刻順最初の実例を選ぶ。

    引数: trades (list[dict]) は全保存取引。
    返り値: list[dict] は床買い・ATR売り・順行EMA・反転中心の4例。
    """
    chosen = []
    plans = (("床20/10の買い", "T01_X01", "利益床", "買い"),
             ("ATR追尾の売り", None, "ATR利益追尾", "売り"),
             ("順行の確定EMA", "T01_X04", "確定足EMA20失効", None),
             ("反転の入口固定中心", "R02_X04", "入口時中心線目標", None))
    for title, cid, reason, side in plans:
        eligible = [t for t in trades if (cid is None or t["手法"] == cid) and t["返済理由"] == reason and (side is None or t["方向"] == side)]
        if not eligible:
            raise ValueError("予定した代表理由が存在しない: " + title)
        first = min(eligible, key=lambda t: (t["返済要求時計秒"], t["返済要求原板行"], t["手法"], t["建玉ID"]))
        chosen.append({"選択理由": title, **first})
    return chosen


# ----------------------------------------
# 気配→同原行確定足の順に、初めて発動する要求を素朴に求める。

def replay_exit(trade: dict, normal: list[dict], frames: list[dict], entry_frame: dict) -> dict:
    """既存運用を呼ばず、保有後の最初の出口要求を見つける。

    引数: trade (dict) は保存取引、normal (list[dict]) は正常板、
    frames (list[dict]) は独立同尺度足、entry_frame (dict) は入口判断足。
    返り値: dict は独立要求・起動・追尾・次1秒約定の診断。
    """
    side, price = (1 if trade["方向"] == "買い" else -1), trade["新規価格"]
    _, _, force = bounds(trade["場"])
    policy, role = trade["出口ID"], trade["入口役割"]
    atr, center = entry_frame["atr"], entry_frame["mean"]
    structure = entry_frame["low"] - 5 if side == 1 else entry_frame["high"] + 5
    timeline = [(r["now"], r["line"], 0, r) for r in normal if r["line"] >= trade["新規原板行"]]
    timeline += [(f["confirm"], f["line"], 1, f) for f in frames if f["publish"] and (f["confirm"], f["line"]) >= (trade["新規時計秒"], trade["新規原板行"])]
    timeline += [(force, 0, -1, {})]
    timeline.sort(key=lambda item: item[:3])
    peak, trailing, armed, updates = 0, price - side * 125, None, []
    request, reason, triggered = None, None, None
    for now, line, kind, value in timeline:
        if kind == -1:
            reason = "期限"
        elif kind == 0:
            mark = value["bid"] if side == 1 else value["ask"]
            distance = side * (mark - price)
            peak = max(peak, distance)
            if distance <= -125:
                reason = "保護"
            elif distance >= 250:
                reason = "利確"
            elif policy == "X01" and peak >= 20:
                armed = armed or (now, line)
                if distance <= 10:
                    reason = "利益床"
            elif policy == "X03" and peak >= atr:
                armed = armed or (now, line)
                raw = price + side * peak - side * atr
                rounded = math.floor(raw / 5) * 5 if side == 1 else math.ceil(raw / 5) * 5
                new = max(trailing, rounded) if side == 1 else min(trailing, rounded)
                if new != trailing:
                    updates.append({"時計": now, "原行": line, "旧線": trailing, "新線": new, "峰pt": peak})
                trailing = new
                if side * (mark - trailing) <= 0:
                    reason = "ATR利益追尾"
            elif policy == "X04" and role == "反転" and center is not None and side * (center - price) > 0 and side * (mark - center) >= 0:
                reason = "入口時中心線目標"
        elif policy == "X04" and value["end"] > trade["新規時計秒"] and value["confirm"] - value["end"] <= 30:
            if role == "順行" and value["ema"] is not None and side * (value["close"] - value["ema"]) < 0:
                reason = "確定足EMA20失効"
            elif role == "反転" and side * (value["close"] - structure) < 0:
                reason = "確定足復帰構造失効"
        if reason:
            request = now, line
            triggered = ({"種類": "正常気配", "Bid": value["bid"], "Ask": value["ask"],
                          "返済差pt": distance, "観測峰pt": peak}
                         if kind == 0 else
                         {"種類": "同尺度確定足", "終了時計": value["end"], "公開時計": value["confirm"],
                          "公開原行": value["line"], "終値": value["close"], "EMA20": value["ema"]}
                         if kind == 1 else {"種類": "期限予約"})
            break
    if request is None:
        raise ValueError("独立要求がない")
    fill = next(r for r in normal if r["now"] >= request[0] + 1)
    return {"要求理由": reason, "要求時計": request[0], "要求原行": request[1],
            "起動時計原行": armed, "要求時までMFE": peak, "要求時追尾線": trailing,
            "追尾更新": updates, "利確床pt": 10 if policy == "X01" else None,
            "固定入口ATR": atr, "固定入口中心": center, "固定構造": structure,
            "約定時計": fill["now"], "約定原行": fill["line"],
            "約定価格": fill["bid"] if side == 1 else fill["ask"],
            "発動観測": triggered,
            "同時計変化数": sum(a["now"] == b["now"] for a, b in zip(normal[:-1], normal[1:])
                               if trade["新規原板行"] <= a["line"] <= trade["返済原板行"])}


def run() -> dict:
    """4実例の発動と次1秒約定を独立照合しJSONへ保存する。

    引数: なし。固定台帳、作業詳細、既存小型cacheだけを読む。
    返り値: dict は明示合否・件数・4例・範囲と限界。
    """
    trades = []
    with gzip.open(DETAIL, "rt", encoding="utf-8") as stream:
        for line in stream:
            trades.extend(json.loads(line)["取引"])
    chosen = select(trades)
    manifest = json.loads((SOURCE / "入力台帳.json").read_text(encoding="utf-8"))
    last_session = max(t["場"] for t in chosen)
    states, all_frames, normals, previous_contract = {3: Averages(), 5: Averages()}, {}, {}, None
    fingerprints = []
    for entry in manifest["entries"]:
        if entry["session"] > last_session:
            break
        contract = entry["in_session_contract_codes"]
        if previous_contract is not None and contract != previous_contract:
            states = {3: Averages(), 5: Averages()}
        previous_contract = contract
        raw, normal = load(entry)
        normals[entry["session"]] = normal
        for minutes in (3, 5):
            all_frames[(entry["session"], minutes)] = bars(raw, entry["session"], minutes, states[minutes])
        fingerprints.append({"場": entry["session"], "cacheSHA256": entry["sha256_cache"]})
    count, errors, examples = 0, [], []
    for trade in chosen:
        minutes = 5 if trade["手法"].startswith("R02") else 3
        frames = all_frames[(trade["場"], minutes)]
        entry = next(f for f in frames if (f["confirm"], f["line"]) == (trade["新規要求時計秒"], trade["新規要求原板行"]))
        actual = replay_exit(trade, normals[trade["場"]], frames, entry)
        expected = {"要求理由": trade["返済理由"], "要求時計": trade["返済要求時計秒"], "要求原行": trade["返済要求原板行"],
                    "約定時計": trade["返済時計秒"], "約定原行": trade["返済原板行"], "約定価格": trade["返済価格"],
                    "固定入口ATR": trade["入口ATR"], "固定入口中心": trade["入口中心線目標"]}
        for key, value in expected.items():
            count += 1
            same = abs(actual[key] - value) <= 1e-7 if isinstance(value, (int, float)) and actual[key] is not None else actual[key] == value
            if not same:
                errors.append({"候補": trade["手法"], "場": trade["場"], "項目": key, "独立": actual[key], "保存": value})
        if trade["返済理由"] == "利益床":
            count += 1
            if actual["起動時計原行"] is None:
                errors.append({"項目": "床起動なし"})
        for update in actual["追尾更新"]:
            count += 1
            if (1 if trade["方向"] == "買い" else -1) * (update["新線"] - update["旧線"]) < 0:
                errors.append({"項目": "追尾後退", "更新": update})
        examples.append({"選択理由": trade["選択理由"], "候補ID": trade["手法"], "場": trade["場"],
                         "建玉ID": trade["建玉ID"], "方向": trade["方向"], "入口": {"価格": trade["新規価格"], "時計": trade["新規時計秒"], "原行": trade["新規原板行"]},
                         "独立診断": actual, "観測経路注意": trade["観測経路注意"], "返済待機秒": trade["要求から返済秒"]})
    result = {"全件一致": not errors, "照合項目数": count, "不一致数": len(errors), "不一致": errors,
              "コードSHA256": sha(Path(__file__)), "対象運用コードSHA256": sha(ROOT / "scripts/利益回収/運用.py"),
              "詳細SHA256": sha(DETAIL), "入力台帳SHA256": sha(SOURCE / "入力台帳.json"),
              "選択規則": "床はT01_X01買い、ATRは全X03売り、EMAはT01_X04、中心はR02_X04。それぞれ要求時計/原行/候補ID/建玉ID順の最初。",
              "入力cache": fingerprints, "実例": examples,
              "方法": "運用・比較・指標コードをimportせず、正常板と半開3/5分OHLC、算術種EMA20/ATR14/SMA20を独立再構成。quote→同原行bar順で初要求と+1秒最初BBOを照合。",
              "限界": "4実例の確認。全18の発動を全面再実装したものではない。50/20床と復帰構造の実例は本4件に含まず合成検査が担当。ATR売り例には観測経路空白があり614秒後の返済は確定利益を意味しない。"}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"全件一致": not errors, "照合項目数": count, "不一致数": len(errors), "不一致": errors}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    if not run()["全件一致"]:
        raise SystemExit(1)
