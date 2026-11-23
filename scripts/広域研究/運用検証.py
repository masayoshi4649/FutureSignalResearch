"""00006の固定入口を単一建玉で再生し、観測経路と費用感度を保存する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))
DEFAULT_STUDY = ROOT / "study/00007_固定入口の単一建玉と費用感度"


def load_module(path: Path, name: str) -> Any:
    """既存の固定入口処理をパス指定で読み込む。

    引数: path (Path) はコード、name (str) はプロセス内の識別名。
    返り値: Any は読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def sha(path: Path) -> str:
    """入力と実装の内容識別子を計算する。

    引数: path (Path) はファイル。
    返り値: str はSHA256。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expanded_sha(path: Path) -> str:
    """gzipの生成時刻に左右されない展開内容の識別子を計算する。

    引数: path (Path) は入口中間物のgzip。
    返り値: str は展開内容のSHA256。CRC破損や途中切断は例外。
    """
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    """日本語JSONを読み込む。

    引数: path (Path) は入力。
    返り値: dict は設定または台帳。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    """有限値だけを含むJSONを保存する。

    引数: path (Path) は出力、value (Any) は保存内容。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    """全行の列を保持してCSVを保存する。

    引数: path (Path) は出力、rows (list[dict]) は行。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        if keys:
            writer = csv.DictWriter(stream, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)


def iso(now: float) -> str:
    """価格時計秒を時差付き日本時刻へ変換する。

    引数: now (float) はUnix秒。
    返り値: str はISO日時。
    """
    return datetime.fromtimestamp(now, JST).isoformat()


def session_times(session: str) -> tuple[float, float, float, float]:
    """セッションの開始・終了・新規停止・期限要求を返す。

    引数: session (str) は開始日基準の場名。
    返り値: tuple[float, float, float, float] は四つのUnix秒。終了は未満で扱う。
    """
    day, part = session.split("_")
    date = datetime.fromisoformat(day).replace(tzinfo=JST)
    if part == "Day":
        return tuple(date.replace(hour=h, minute=m).timestamp() for h, m in ((8, 45), (15, 40), (15, 25), (15, 35)))
    if part == "Night":
        following = date + timedelta(days=1)
        return (date.replace(hour=17).timestamp(), following.replace(hour=5, minute=55).timestamp(),
                following.replace(hour=5, minute=40).timestamp(), following.replace(hour=5, minute=50).timestamp())
    raise ValueError("未知の場名")


def validate_config(config: dict) -> None:
    """本試行で固定した商品・幅・遅延条件だけを許可する。

    引数: config (dict) は条件JSON。
    返り値: None。不一致はValueError。
    """
    expected = {"対象": "NK225", "数量": 1, "倍率": 10, "呼値pt": 5, "利確pt": 250,
                "保護逆行pt": 125, "片道手数料円": 11, "片道追加滑りpt": [0, 5, 10],
                "新規待機秒": 1, "新規有効秒": 30, "返済待機秒": 1, "正常板空白注意秒": 300,
                "同時両方向": "見送り", "単一建玉": True,
                "入口候補ID": "3分_開始幅失敗復帰_15_ADX環境"}
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError("00007の固定された売買条件と一致しません")


# ----------------------------------------
# 原板の正常気配に対する注文状態。入口の将来ラベルは一切参照しない。

class 運用状態:
    """一枚・一建玉の成行要求と約定、観測上の現金を管理する。"""

    def __init__(self, session: str, method: str, config: dict,
                 bounds: tuple[float, float, float, float] | None = None) -> None:
        """場内状態を初期化する。

        引数: session/method (str) は場と入口ID、config (dict) は条件、bounds (tuple | None) は合成検証用の時刻。
        返り値: None。
        """
        self.session, self.method, self.config = session, method, config
        self.start, self.end, self.cutoff, self.force = bounds or session_times(session)
        self.position, self.pending = None, None
        self.fills, self.trades, self.orders, self.signals = [], [], [], []
        self.counts = Counter()
        self.cash = 0.0
        self.force_done = False
        self.previous_quote = None
        self.maximum_gap = 0.0
        self.positions = 0
        self.gap_intervals = []

    def request(self, kind: str, side: int, now: float, line: int, reason: str,
                event_id: str, signal: dict | None = None) -> None:
        """約定まで保持する成行要求を一つ作る。

        引数: kind (str) は新規/返済、side (int) は建玉方向、now (float) とline (int) は要求根拠、
        reason/event_id (str) は理由と入口ID、signal (dict | None) は入口取扱行。
        返り値: None。
        """
        order_id = f"{self.session}_注文{len(self.orders) + 1:04d}"
        self.pending = {"kind": kind, "side": side, "time": now, "line": line, "reason": reason,
                        "event_id": event_id, "id": order_id, "signal": signal, "gap": False}
        self.orders.append({"注文ID": order_id, "場": self.session, "入口イベントID": event_id,
                            "区分": kind, "方向": "買い" if side == 1 else "売り", "理由": reason,
                            "要求時計秒": now, "要求時計JST": iso(now), "要求原板行": line,
                            "状態": "待機", "約定時計秒": None, "約定原板行": None})

    def cancel_entry(self, reason: str) -> None:
        """未約定の新規を取り消し、入口取扱と注文台帳へ理由を残す。

        引数: reason (str) は取消理由。
        返り値: None。
        """
        if self.pending and self.pending["kind"] == "新規":
            self.orders[-1]["状態"] = reason
            self.pending["signal"]["取扱"] = reason
            self.counts["新規取消数"] += 1
            self.pending = None

    def before(self, now: float) -> None:
        """期限予約と新規失効を、当該価格イベントより先に処理する。

        引数: now (float) は次のイベント時刻。
        返り値: None。
        """
        if self.pending and self.pending["kind"] == "新規":
            if now >= self.cutoff or now > self.pending["time"] + self.config["新規有効秒"]:
                self.cancel_entry("新規停止または30秒失効")
        if now >= self.force and not self.force_done:
            self.force_done = True
            self.cancel_entry("期限で新規取消")
            if self.position is not None and self.pending is None:
                self.request("返済", self.position["side"], self.force, 0, "期限", self.position["event_id"])

    def mark(self, bid: float, ask: float) -> None:
        """保有の観測順行・逆行を、返済気配で更新する。

        引数: bid/ask (float) は正常気配。
        返り値: None。返済約定の気配も範囲へ含める。
        """
        if self.position is not None:
            pos = self.position
            distance = pos["side"] * ((bid if pos["side"] == 1 else ask) - pos["price"])
            pos["mfe"] = max(pos["mfe"], distance)
            pos["mae"] = max(pos["mae"], -distance)

    def fill(self, now: float, line: int, bid: float, ask: float) -> None:
        """待機秒を満たす注文を現在の正常気配で約定させる。

        引数: now (float) は価格時計、line (int) は原行、bid/ask (float) は正常気配。
        返り値: None。注文の閾値そのものでは約定しない。
        """
        pending = self.pending
        if pending is None:
            return
        wait = self.config["新規待機秒" if pending["kind"] == "新規" else "返済待機秒"]
        if now < pending["time"] + wait or now >= self.end:
            return
        side = pending["side"]
        entry = pending["kind"] == "新規"
        price = (ask if side == 1 else bid) if entry else (bid if side == 1 else ask)
        if not math.isclose(price / self.config["呼値pt"], round(price / self.config["呼値pt"]), abs_tol=1e-8):
            raise ValueError("約定気配がmicroモデルの呼値と不一致")
        fee = self.config["片道手数料円"]
        if entry:
            self.positions += 1
            position_id = f"{self.session}_建玉{self.positions:04d}"
            self.position = {"id": position_id, "side": side, "price": price, "time": now, "line": line,
                             "event_id": pending["event_id"], "request_time": pending["time"],
                             "request_line": pending["line"], "target": price + side * self.config["利確pt"],
                             "stop": price - side * self.config["保護逆行pt"], "gap": False,
                             "entry_gap": pending["gap"], "mfe": 0.0, "mae": 0.0}
            pending["signal"].update(取扱="新規約定", 建玉ID=position_id, 新規時計秒=now, 新規原板行=line)
            self.cash -= fee
        else:
            pos = self.position
            position_id = pos["id"]
            gross = side * (price - pos["price"]) * self.config["倍率"]
            self.cash += gross - fee
            net = gross - 2 * fee
            trade = {"銘柄": "NK225", "商品": "NK225micro代理", "場": self.session, "手法": self.method,
                     "建玉ID": position_id, "入口イベントID": pos["event_id"], "方向": "買い" if side == 1 else "売り",
                     "枚数": 1, "新規要求時計秒": pos["request_time"], "新規要求原板行": pos["request_line"],
                     "新規時計秒": pos["time"], "新規時計JST": iso(pos["time"]), "新規原板行": pos["line"], "新規価格": pos["price"],
                     "返済要求時計秒": pending["time"], "返済要求原板行": pending["line"],
                     "返済時計秒": now, "返済時計JST": iso(now), "返済原板行": line, "返済価格": price,
                     "返済理由": pending["reason"], "利確価格": pos["target"], "保護価格": pos["stop"],
                     "要求から返済秒": now - pending["time"], "保有分": (now - pos["time"]) / 60,
                     "観測最大順行pt": pos["mfe"], "観測最大逆行pt": pos["mae"],
                     "保有経路空白": pos["gap"], "新規待機空白": pos["entry_gap"],
                     "観測経路注意": pos["gap"] or pos["entry_gap"], "粗損益円": gross,
                     "手数料円": 2 * fee, "基準純損益円": net}
            for slip in self.config["片道追加滑りpt"]:
                trade[f"追加滑り{slip}pt純損益円"] = net - 2 * slip * self.config["倍率"]
            self.trades.append(trade)
            self.position = None
        self.fills.append({"id": f"{self.session}_約定{len(self.fills) + 1:04d}", "timestamp": iso(now),
                           "type": ("Long" if side == 1 else "Short") + ("N" if entry else "R"),
                           "position_id": position_id, "price": price, "qty": 1, "fee_yen": fee,
                           "method_id": self.method, "source_line": line, "price_clock": now,
                           "request_timestamp": iso(pending["time"]), "request_clock": pending["time"],
                           "request_source_line": pending["line"], "reason": pending["reason"],
                           "entry_event_id": pending["event_id"], "order_id": pending["id"]})
        self.orders[-1].update(状態="約定", 約定時計秒=now, 約定原板行=line, 約定価格=price, 手数料円=fee)
        self.pending = None

    def quote(self, now: float, line: int, bid: float, ask: float) -> None:
        """正常板で空白、既存約定、新たな閾値到達を順番に処理する。

        引数: now (float) は価格時計、line (int) は原行、bid/ask (float) は正常気配。
        返り値: None。空白後も観測上の再生を続け、判定打切りラベルとは分ける。
        """
        self.before(now)
        previous = self.previous_quote if self.previous_quote is not None else self.start
        if now > previous:
            gap = now - previous
            self.maximum_gap = max(self.maximum_gap, gap)
            if gap > self.config["正常板空白注意秒"]:
                self.gap_intervals.append((previous, now))
                self.counts["場内正常板空白区間数"] += 1
                if self.position is not None:
                    self.position["gap"] = True
                    self.counts["保有中空白区間数"] += 1
                if self.pending is not None and self.pending["kind"] == "新規":
                    self.pending["gap"] = True
                    self.counts["新規待機中空白区間数"] += 1
        self.previous_quote = now
        self.counts["正常板数"] += 1
        self.mark(bid, ask)
        self.fill(now, line, bid, ask)
        self.mark(bid, ask)
        if self.position is not None and self.pending is None:
            pos = self.position
            mark = bid if pos["side"] == 1 else ask
            distance = pos["side"] * (mark - pos["price"])
            reason = "保護" if distance <= -self.config["保護逆行pt"] else (
                "利確" if distance >= self.config["利確pt"] else None)
            if reason is not None:
                self.request("返済", pos["side"], now, line, reason, pos["event_id"])

    def signal_group(self, rows: list[dict]) -> None:
        """同じ要求時計・原行の固定入口を、将来結果を見ずに受け付ける。

        引数: rows (list[dict]) は同時に確定した選択規則の入口。
        返り値: None。両方向同時は全見送り、建玉・注文中は抑止。
        """
        now, line = float(rows[0]["要求時計秒"]), int(rows[0]["要求原板行"])
        self.before(now)
        both = {int(row["side"]) for row in rows} == {1, -1}
        for row in rows:
            record = {"イベントID": row["イベントID"], "場": self.session, "方向": row["方向"],
                      "side": int(row["side"]), "要求時計秒": now, "要求時計JST": iso(now),
                      "要求原板行": line, "確認遅延秒": float(row["確認遅延秒"]), "取扱": "受付"}
            self.signals.append(record)
            if both:
                record["取扱"] = "同時両方向見送り"
            elif row["確認遅延秒"] > 30:
                record["取扱"] = "足確定確認遅延30秒超"
            elif now < self.start or now >= self.cutoff:
                record["取扱"] = "新規停止時刻外"
            elif self.position is not None:
                record["取扱"] = "建玉中抑止"
            elif self.pending is not None:
                record["取扱"] = "注文待機中抑止"
            else:
                self.request("新規", int(row["side"]), now, line, "固定入口", row["イベントID"], record)

    def finish(self) -> dict:
        """EOFの新規取消・期限要求と未解消・経路注意を集計する。

        引数: なし。
        返り値: dict は基準費用の場別集計。観測不明を確定収益と呼ばない。
        """
        self.before(self.end)
        self.cancel_entry("EOF新規未約定")
        tail = self.previous_quote is None or self.previous_quote < self.force
        tail_stale = self.previous_quote is None or self.force - self.previous_quote > self.config["正常板空白注意秒"]
        unresolved = int(self.position is not None)
        gap_trades = sum(trade["観測経路注意"] for trade in self.trades)
        waiting_gaps = sum(
            order["要求時計秒"] < right and (
                order["約定時計秒"] if order["約定時計秒"] is not None else
                min(order["要求時計秒"] + self.config["新規有効秒"], self.cutoff, self.force)
            ) > left
            for left, right in self.gap_intervals for order in self.orders if order["区分"] == "新規")
        attention = bool(gap_trades or unresolved or self.counts["保有中空白区間数"]
                         or waiting_gaps or tail)
        states = Counter(row["取扱"] for row in self.signals)
        return {"銘柄": "NK225", "場": self.session, "手法": self.method,
                "候補要求数": len(self.signals), "新規約定数": sum(fill["type"].endswith("N") for fill in self.fills),
                "完結取引数": len(self.trades), "建玉中抑止数": states["建玉中抑止"],
                "注文待機中抑止数": states["注文待機中抑止"], "両方向見送り数": states["同時両方向見送り"],
                "確認遅延不可数": states["足確定確認遅延30秒超"], "新規取消数": self.counts["新規取消数"],
                "終了建玉": unresolved, "終了返済待機": int(self.pending is not None),
                "観測現金増減円": self.cash, "観測完結取引純損益円": sum(trade["基準純損益円"] for trade in self.trades),
                "手数料円": len(self.fills) * self.config["片道手数料円"],
                "観測経路注意取引数": gap_trades, "経路注意取引純損益円": sum(trade["基準純損益円"] for trade in self.trades if trade["観測経路注意"]),
                "場内正常板空白区間数": self.counts["場内正常板空白区間数"],
                "保有中空白区間数": self.counts["保有中空白区間数"], "新規待機中空白区間数": waiting_gaps,
                "最長正常板間隔秒": self.maximum_gap, "正常板数": self.counts["正常板数"],
                "正常板最終時計秒": self.previous_quote, "EOF期限未達": tail, "期限まで300秒超尾部": tail_stale,
                "観測経路注意": attention, "確定対象純損益円": None if attention else self.cash,
                "未解消建玉": self.position, "未解消返済要求": self.pending}


def replay_session(events: list[Any], signals: list[dict], session: str, method: str, config: dict,
                   bounds: tuple[float, float, float, float] | None = None) -> tuple[運用状態, dict]:
    """気配と要求の原順を合わせて一場を再生する。

    引数: events (list[Any]) はキャッシュ状態、signals (list[dict]) は固定入口、session/method (str) は識別、
    config (dict) は条件、bounds (tuple | None) は合成検証用の時刻。
    返り値: tuple[運用状態, dict] は約定等の状態と場別集計。
    """
    state = 運用状態(session, method, config, bounds)
    groups = defaultdict(list)
    ids = set()
    for row in signals:
        if row["イベントID"] in ids or row["場"] != session or int(row["side"]) not in (1, -1):
            raise ValueError("入口ID重複または場・方向不一致")
        ids.add(row["イベントID"])
        groups[(float(row["要求時計秒"]), int(row["要求原板行"]))].append(row)
    timeline, previous = [], -math.inf
    backwards = 0
    for event in events:
        if not math.isfinite(event.now) or not state.start <= event.now < state.end:
            continue
        if event.now < previous:
            backwards += 1
            continue
        previous = event.now
        if event.valid:
            if not (math.isfinite(event.bid) and math.isfinite(event.ask) and 0 < event.bid <= event.ask):
                raise ValueError("正常板フラグと気配が不一致")
            timeline.append((event.now, int(event.line), 0, event))
    for (now, line), group in groups.items():
        timeline.append((now, line, 1, group))
    timeline.sort(key=lambda item: item[:3])
    for now, line, kind, value in timeline:
        if kind == 0:
            state.quote(now, line, value.bid, value.ask)
        else:
            state.signal_group(value)
    result = state.finish()
    result["時計後退除外数"] = backwards
    return state, result


# ----------------------------------------
# 費用感度は完結取引だけへ適用し、同じ注文・約定経路を維持する。

def sensitivity(sessions: list[dict], config: dict) -> list[dict]:
    """基準の場別会計へ、完結往復の追加費用を差し引く。

    引数: sessions (list[dict]) は基準集計、config (dict) は倍率と追加滑り。
    返り値: list[dict] は各場×各費用の集計。
    """
    result = []
    for session in sessions:
        for slip in config["片道追加滑りpt"]:
            extra = 2 * slip * config["倍率"] * session["完結取引数"]
            row = {key: value for key, value in session.items() if key not in ("未解消建玉", "未解消返済要求")}
            row.update(片道追加滑りpt=slip, 追加費用円=extra,
                       観測現金増減円=session["観測現金増減円"] - extra,
                       観測完結取引純損益円=session["観測完結取引純損益円"] - extra,
                       経路注意取引純損益円=session["経路注意取引純損益円"] - 2 * slip * config["倍率"] * session["観測経路注意取引数"],
                       確定対象純損益円=None if session["確定対象純損益円"] is None else session["確定対象純損益円"] - extra)
            result.append(row)
    return result


def aggregate(sessions: list[dict]) -> list[dict]:
    """全対象と期間別を集計し、注意経路を含む総額を確定扱いしない。

    引数: sessions (list[dict]) は費用感度済み場別集計。
    返り値: list[dict] は期間×追加滑りの小集計。
    """
    result = []
    for period in ["全対象", *dict.fromkeys(row["期間"] for row in sessions)]:
        for slip in sorted({row["片道追加滑りpt"] for row in sessions}):
            rows = [row for row in sessions if row["片道追加滑りpt"] == slip and (period == "全対象" or row["期間"] == period)]
            clean = [row for row in rows if not row["観測経路注意"]]
            result.append({"期間": period, "片道追加滑りpt": slip, "場数": len(rows),
                           **{key: sum(row[key] for row in rows) for key in (
                               "候補要求数", "新規約定数", "建玉中抑止数", "注文待機中抑止数", "両方向見送り数", "確認遅延不可数", "新規取消数")},
                           "完結取引数": sum(row["完結取引数"] for row in rows),
                           "終了未解消場数": sum(bool(row["終了建玉"]) for row in rows),
                           "観測経路注意場数": sum(row["観測経路注意"] for row in rows),
                           "観測経路注意取引数": sum(row["観測経路注意取引数"] for row in rows),
                           "EOF期限未達場数": sum(row["EOF期限未達"] for row in rows),
                           "観測現金増減円": sum(row["観測現金増減円"] for row in rows),
                           "観測完結取引純損益円": sum(row["観測完結取引純損益円"] for row in rows),
                           "経路注意取引純損益円": sum(row["経路注意取引純損益円"] for row in rows),
                           "手数料円": sum(row["手数料円"] for row in rows), "追加費用円": sum(row["追加費用円"] for row in rows),
                           "確定対象純損益円": sum(row["確定対象純損益円"] for row in rows) if len(clean) == len(rows) else None,
                           "注意なし場数": len(clean), "注意なし場のみ純損益円": sum(row["確定対象純損益円"] for row in clean),
                           "注意なし部分集計の限界": "欠落場を含む全体の確定収益ではない。事後選別による部分集計。"})
    return result


def input_signals(path: Path, allowed: Any, rule: dict, future: bool, future_day: str) -> list[dict]:
    """00006の全入口特徴へ同じ固定規則を適用し、将来ラベルを捨てる。

    引数: path (Path) は既存gzip、allowed (Any) は固定判定、rule (dict) は固定入口、
    future (bool) は後続だけか、future_day (str) は境界開始日。
    返り値: list[dict] は必要な要求列だけの入口。損益やラベルで選別しない。
    """
    result = []
    keys = ("イベントID", "場", "方向", "side", "要求時計秒", "要求原板行", "確認遅延秒")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if (row["場"][:10] >= future_day) != future:
                raise ValueError("入口中間物に実行段階外の場が混在")
            if allowed(row, rule):
                result.append({key: row[key] for key in keys})
    return result


def run(study: Path, phase: str, output: Path | None = None, allow_future: bool = False) -> dict:
    """固定入力・入口を確認して、指定段階だけの運用結果を出力する。

    引数: study (Path) は00007、phase (str) は探索/後続、output (Path | None) は保存先、
    allow_future (bool) は明示的に後続を許すCLI指定。
    返り値: dict は実行段階と期間集計。後続は固定不一致・再実行を拒否する。
    """
    if phase not in ("探索", "後続") or phase == "後続" and not allow_future:
        raise ValueError("後続は固定確認と--allow-futureの明示が必要")
    config = read_json(study / "条件.json")
    validate_config(config)
    source = (study / config["入口元試行"]).resolve()
    fixed = read_json(source / "選択固定.json")
    if fixed["候補ID"] != config["入口候補ID"] or fixed["規則"]["候補ID"] != config["入口候補ID"]:
        raise ValueError("入口候補が00006の選択固定と異なる")
    output = output or (study if phase == "探索" else study / "追加確認")
    if (output / "結果.json").exists():
        raise ValueError("既存の運用結果は上書きしません")
    files = {ROOT / name: expected for name, expected in fixed["ファイルSHA256"].items()}
    for path, expected in files.items():
        if sha(path) != expected:
            raise ValueError(f"00006の固定後に変更された入力・実装: {path.name}")
    old_signals = ROOT / "work/広域研究/00006_探索事例.jsonl.gz"
    future_signals = ROOT / "work/広域研究/00006_後続事例.jsonl.gz"
    signal_path = old_signals if phase == "探索" else future_signals
    lock_path = study / "運用固定.json"
    pin_files = [Path(__file__), Path(__file__).with_name("運用の合成検証.py"), study / "条件.json",
                 study / "計画.md", source / "選択固定.json", *files]
    pins = {path.relative_to(ROOT).as_posix(): sha(path) for path in dict.fromkeys(pin_files)}
    input_pins = {path.relative_to(ROOT).as_posix(): expanded_sha(path) for path in (old_signals, future_signals)}
    if phase == "後続":
        locked = read_json(lock_path)
        if locked["ファイルSHA256"] != pins:
            raise ValueError("運用固定後に条件・入口・コードが変更された")
        if locked["入口事例展開SHA256"] != input_pins:
            raise ValueError("固定後に入口中間物の展開内容が変更された")
    wide = load_module(ROOT / "scripts/広域研究/検証.py", "運用の固定入口")
    signals = input_signals(signal_path, wide.allowed, fixed["規則"], phase == "後続", config["分割"]["後続開始日"])
    manifest = read_json(source / "入力台帳.json")
    entries = [entry for entry in manifest["entries"] if (entry["session"][:10] >= config["分割"]["後続開始日"]) == (phase == "後続")]
    expected_count = 4 if phase == "後続" else 60
    if len(entries) != expected_count or any(entry["symbol"] != "NK225" for entry in entries):
        raise ValueError("固定された場数または商品と異なる")
    grouped = defaultdict(list)
    for row in signals:
        grouped[row["場"]].append(row)
    if set(grouped) - {entry["session"] for entry in entries}:
        raise ValueError("台帳にない入口場がある")
    output.mkdir(parents=True, exist_ok=True)
    if phase == "探索":
        lock = {"固定日時": datetime.now(JST).isoformat(), "固定入口": fixed["規則"],
                "入口事例展開SHA256": input_pins,
                "入口事例圧縮SHA256_参考": {path.relative_to(ROOT).as_posix(): sha(path) for path in (old_signals, future_signals)},
                "入口中間物の固定方法": "展開内容SHA256を正本とする。圧縮SHA256はgzip生成時刻等で変わるため参考記録。",
                "00006選択固定SHA256": sha(source / "選択固定.json"), "ファイルSHA256": pins,
                "後続": "新4場は明示許可後に一回だけ。条件変更や入口再選択をしない。"}
        target_lock = lock_path if output == study else output / "運用固定.json"
        if target_lock.exists() and read_json(target_lock)["ファイルSHA256"] != pins:
            raise ValueError("既存の運用固定は上書きしません")
        if not target_lock.exists():
            write_json(target_lock, lock)
    sessions, trades, orders, signal_rows, resources, quality = [], [], [], [], [], []
    for entry in entries:
        raw = Path(manifest["source_root"]) / entry["source_path"]
        status = raw.stat()
        cache = ROOT / "work/複合検証" / entry["cache_path"]
        if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]) or sha(cache) != entry["sha256_cache"]:
            raise ValueError("固定台帳の原板またはキャッシュと不一致")
        if len(entry["in_session_contract_codes"]) != 1:
            raise ValueError("場内限月が一意でない")
        session = entry["session"]
        state, info = replay_session(list(wide.PREP.read_events(cache)), grouped[session], session, config["入口候補ID"], config)
        period = "後続検査" if phase == "後続" else ("学習" if session[:10] < config["分割"]["選択開始日"] else "条件選択")
        info["期間"] = period
        quality.append(info)
        sessions.append(info)
        for rows, target in ((state.trades, trades), (state.orders, orders), (state.signals, signal_rows)):
            for row in rows:
                row["期間"] = period
            target.extend(rows)
        relative = Path("約定/NK225") / f"{session}.trades.jsonl"
        (output / relative).parent.mkdir(parents=True, exist_ok=True)
        (output / relative).write_text("".join(json.dumps(fill, ensure_ascii=False, allow_nan=False) + "\n" for fill in state.fills), encoding="utf-8")
        resources.append({"id": f"00007_{session}", "title": f"{session} 固定入口・追加滑り0pt・観測代理",
                          "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": state.method,
                          "entry_method_id": state.method, "point_value": config["倍率"], "pnl_format": "trades", "pnl_basis": "net",
                          "pnl_path": relative.as_posix(), "market_path": entry["source_path"]})
        print(f"{phase} 運用 {session} 完了", flush=True)
    sensitive = sensitivity(sessions, config)
    comparisons = aggregate(sensitive)
    result = {"段階": phase, "固定入口": config["入口候補ID"], "入口元選択固定SHA256": sha(source / "選択固定.json"),
              "基準Viewerの追加滑りpt": 0, "集計": comparisons,
              "限界": "ラージ板によるmicro代理。価格時計は受信時計ではない。経路注意・未解消を含む総額は確定収益でない。追加滑りは完結取引の費用感度のみ。"}
    write_csv(output / "セッション集計.csv", sensitive)
    write_csv(output / "取引集計.csv", trades)
    write_csv(output / "注文台帳.csv", orders)
    write_csv(output / "入口取扱.csv", signal_rows)
    write_csv(output / "期間比較.csv", comparisons)
    write_json(output / "品質集計.json", quality)
    write_json(output / "一覧.resources.json", {"schema_version": 1, "path_base": "catalog", "resources": resources})
    write_json(output / "実行情報.json", {"日時": datetime.now(JST).isoformat(), "Python": platform.python_version(),
              "入口事例": signal_path.relative_to(ROOT).as_posix(), "入口事例展開SHA256": expanded_sha(signal_path),
              "入口事例圧縮SHA256_参考": sha(signal_path), "ファイルSHA256": pins})
    write_json(output / "結果.json", result)
    return result


def main() -> None:
    """コマンド引数から段階を選び、固定運用を実行する。

    引数: なし。--study/--phase/--output/--allow-futureを読む。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="00006固定入口の一建玉運用と費用感度")
    parser.add_argument("--study", type=Path, default=DEFAULT_STUDY)
    parser.add_argument("--phase", choices=("探索", "後続"), default="探索")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-future", action="store_true")
    args = parser.parse_args()
    result = run(args.study.resolve(), args.phase, args.output.resolve() if args.output else None, args.allow_future)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
