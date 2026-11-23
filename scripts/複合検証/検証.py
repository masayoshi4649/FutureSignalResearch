"""実データの損益を見ず、複合条件と注文時点を合成入力で検証する。"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Iterator, NamedTuple
import unittest
from unittest.mock import patch


対象パス = Path(__file__).with_name("再生.py")
仕様 = importlib.util.spec_from_file_location("複合再生の合成検証対象", 対象パス)
再生 = importlib.util.module_from_spec(仕様)
sys.modules[仕様.name] = 再生
仕様.loader.exec_module(再生)
基準時刻 = datetime(2026, 10, 30, 8, 45, tzinfo=再生.JST).timestamp()
商品 = {"product": "合成商品", "point_value": 10, "tick": 1, "fee_yen": 1}


# ----------------------------------------
# 実データを必要としない観測と状態

class 合成観測(NamedTuple):
    """価格時計と数量時計を独立に指定できる、一つの板観測。"""

    now: float
    line: int
    last: float
    bid: float
    ask: float
    valid: bool
    volume: float
    volume_time: float


def 観測(秒: float, 行: int = 1, 現在値: float = 100, 買気配: float = 99,
       売気配: float = 100, 数量: float = 100, 数量秒: float | None = None,
       正常: bool = True) -> 合成観測:
    """場の開始からの秒数で合成観測を生成する。

    引数: 秒 (float) は価格時計、行 (int) は原行、現在値・買気配・売気配・数量 (float) は観測値、
    数量秒 (float | None) は独立した数量時計、正常 (bool) は板の有効性。
    返り値: 合成観測 は明示した時点と値を持つ観測。
    """
    return 合成観測(基準時刻 + 秒, 行, 現在値, 買気配, 売気配, 正常,
                  数量, 基準時刻 + (秒 if 数量秒 is None else 数量秒))


def 足(番号: int = 0, 終値: float = 100, 数量: float = 10,
      数量有効: bool = True) -> dict[str, Any]:
    """指定区間に所属する5分足を生成する。

    引数: 番号 (int) は場内区間、終値・数量 (float) は値、数量有効 (bool) は観測差分の継続可否。
    返り値: dict[str, Any] は合成の確定足。
    """
    return {"index": 番号, "start": 基準時刻 + 番号 * 300,
            "end": 基準時刻 + (番号 + 1) * 300, "open": 終値,
            "high": 終値, "low": 終値 - 1, "close": 終値,
            "volume": 数量, "volume_ok": 数量有効, "volume_seen": 数量有効}


def 特徴(**変更: Any) -> dict[str, Any]:
    """注文検証に不要な指標計算を切り離すため、既知の特徴を作る。

    引数: 変更 (Any) は標準値から置き換える各項目。
    返り値: dict[str, Any] は完全指定された判定用特徴。
    """
    result = {"ready": True, "side": 1, "flags": dict.fromkeys("MRVB", True),
              "close": 100, "ema": 99, "atr": 10, "rsi5": 45, "rsi15": 40,
              "direction15": 1, "direction30": 1, "upper": 99, "lower": 90,
              "relative_volume": 2, "norm_atr": 0.1, "norm_threshold": 0.2,
              "bar_end": 基準時刻 + 300, "volume": 20, "volume_ok": True}
    result.update(変更)
    return result


class 指標代役:
    """既知の指標結果と更新履歴を返し、集約・窓処理だけを検証する。"""

    def __init__(self, 方向: int = 1, RSI: float = 60, ATR: float = 1,
                 初期方向: int | None = None) -> None:
        """更新前と更新後の結果を準備する。

        引数: 方向 (int) は更新後の方向、RSI・ATR (float) は固定値、初期方向 (int | None) は更新前の方向。
        返り値: None。
        """
        self.方向, self.RSI, self.ATR = 方向, RSI, ATR
        self.履歴: list[dict[str, Any]] = []
        self.result = {"close": 100, "ema": 99, "ema_previous": 98,
                       "direction": 方向 if 初期方向 is None else 初期方向,
                       "rsi": RSI, "atr": ATR}

    def update(self, bar: dict[str, Any]) -> dict[str, Any]:
        """渡された集約足を記録して既知の結果を返す。

        引数: bar (dict[str, Any]) は集約済みまたは5分の確定足。
        返り値: dict[str, Any] は指定された指標値。
        """
        self.履歴.append(dict(bar))
        self.result = {"close": bar["close"], "ema": bar["close"] - self.方向,
                       "ema_previous": bar["close"] - 2 * self.方向,
                       "direction": self.方向, "rsi": self.RSI, "atr": self.ATR}
        return self.result


def 有効窓(方向: int = 1, RSI5: float = 60, RSI15: float = 60,
          ATR: float = 1) -> Any:
    """窓計算の検証に必要な過去データだけを準備する。

    引数: 方向 (int) は基準方向、RSI5・RSI15・ATR (float) は既知の指標値。
    返り値: 複数時間足 は履歴を準備した検証用状態。
    """
    bank = 再生.複数時間足()
    bank.channels = {5: 指標代役(方向, RSI5, ATR),
                     15: 指標代役(方向, RSI15), 30: 指標代役(方向)}
    bank.ranges = deque([(99, 98)] * 6 if 方向 == 1 else [(102, 101)] * 6, maxlen=6)
    bank.norms = deque([0.1] * 60, maxlen=60)
    bank.volumes = deque([10] * 20, maxlen=20)
    return bank


class 台本足(再生.複数時間足):
    """時間境界と注文の検証に、指定した足番号だけ既知の特徴を返す。"""

    def __init__(self, 台本: dict[int, dict[str, Any]] | None = None) -> None:
        """台本と観測済み足を準備する。

        引数: 台本 (dict[int, dict[str, Any]] | None) は足番号ごとの特徴。省略時は既存台本を維持する。
        返り値: None。
        """
        self.台本 = 台本 if 台本 is not None else getattr(self, "台本", {})
        self.記録 = getattr(self, "記録", [])
        self.初期化数 = getattr(self, "初期化数", 0) + 1
        super().__init__()

    def update(self, bar: dict[str, Any]) -> dict[str, Any]:
        """受け取った足と、その足の終了時刻に対応する特徴を返す。

        引数: bar (dict[str, Any]) は再生処理が確定した足。
        返り値: dict[str, Any] は台本の特徴。指定のない足は新規を許さない。
        """
        self.記録.append(dict(bar))
        return 特徴(ready=False, side=0, bar_end=bar["end"]) | self.台本.get(bar["index"], {})


class 合成準備:
    """実ファイル解析をせず、合成観測を入力順で返す。"""

    def __init__(self, 観測列: list[合成観測]) -> None:
        """再生する観測列を保持する。

        引数: 観測列 (list[合成観測]) は順序を確定した入力。
        返り値: None。
        """
        self.観測列 = 観測列

    def read_events(self, path: Path) -> Iterator[合成観測]:
        """入力順を変えず、観測を一つずつ返す。

        引数: path (Path) はハッシュ検査済みの仮キャッシュ。
        返り値: Iterator[合成観測] は保持した観測の反復子。
        """
        return iter(self.観測列)


def 合成再生(観測列: list[合成観測], 指標: Any,
          候補: list[dict[str, Any]] | None = None, 分数: int = 15) -> tuple:
    """小さな仮キャッシュと短い場で本番の再生関数を呼び出す。

    引数: 観測列 (list[合成観測]) は入力、指標 (Any) は本物または台本の状態、
    候補 (list[dict[str, Any]] | None) は比較候補、分数 (int) は合成場の長さ。
    返り値: tuple は本番関数が返す候補状態・発動候補・品質。
    """
    start = datetime.fromtimestamp(基準時刻, 再生.JST)
    end = start + timedelta(minutes=分数)
    times = (start, end, end - timedelta(minutes=5), end - timedelta(minutes=1))
    rules = 候補 if 候補 is not None else 再生.factorial_rules()[:1]
    with TemporaryDirectory(prefix="複合検証_") as temporary:
        folder = Path(temporary)
        content = "合成キャッシュ".encode("utf-8")
        (folder / "入力.bin").write_bytes(content)
        entry = {"symbol": "NK225", "session": "2026-10-30_Day", "cache_path": "入力.bin",
                 "sha256_cache": hashlib.sha256(content).hexdigest()}
        with patch.object(再生.legacy, "session_times", return_value=times):
            return 再生.replay_session(entry, folder, 合成準備(観測列), 指標, rules, 商品)


def 手法(因子: list[str] | None = None, **変更: Any) -> Any:
    """実際の場時刻と共通費用を使う検証用の手法を作る。

    引数: 因子 (list[str] | None) は必須因子、変更 (Any) は候補条件の上書き。
    返り値: 複合手法 は未保有・未注文の候補状態。
    """
    rule = {"名前": "検証候補", "因子": 因子 or [], "EMA決済": True, "保護ATR倍": 2}
    rule.update(変更)
    return 再生.複合手法(rule, "NK225", "2026-10-30_Day", 商品)


def 建てる(状態: Any, 方向: int = 1, ATR: float = 5) -> float:
    """要求と同時計では約定しないことを保ち、1枚を建てる。

    引数: 状態 (複合手法) は対象、方向 (int) は買い1または売り-1、ATR (float) は入口確定値。
    返り値: float は新規要求の価格時計。
    """
    now = 基準時刻 + 900
    状態.request("entry", 方向, now, 1, "価格帯突破", ATR)
    状態.on_quote(now, 1, 3, 99, 100, True)
    状態.on_quote(now + 1, 2, 3, 99, 100, True)
    return now


# ----------------------------------------
# 集約・指標・因子の検証

class 指標と因子の検証(unittest.TestCase):
    """本物の平滑処理と、独立した窓・集約の性質を確かめる。"""

    def test_EMAの初期化と21本目の更新(self) -> None:
        """20本の平均を初期値にし、次の値を係数2/21で反映する。

        引数: なし。
        返り値: None。
        """
        channel = 再生.時間足指標()
        for number in range(1, 21):
            result = channel.update(足(number, 100 + number))
        self.assertEqual(result["ema"], 110.5)
        self.assertIsNone(result["ema_previous"])
        result = channel.update(足(21, 121))
        self.assertEqual(result["ema"], 111.5)
        self.assertEqual(result["ema_previous"], 110.5)
        self.assertEqual(result["direction"], 1)

    def test_完全な上位足だけ更新し同時確定値を使う(self) -> None:
        """30分足の6本目では、新しい15分・30分の両方を判断へ使う。

        引数: なし。
        返り値: None。
        """
        bank = 有効窓()
        bank.channels[15] = 指標代役(1, 初期方向=-1)
        bank.channels[30] = 指標代役(1, 初期方向=-1)
        for number in range(6):
            result = bank.update(足(number, 100 + number))
            if number < 2:
                self.assertEqual(len(bank.channels[15].履歴), 0)
            if number < 5:
                self.assertEqual(len(bank.channels[30].履歴), 0)
                self.assertEqual(result["direction30"], -1)
                self.assertFalse(result["flags"]["M"])
        self.assertEqual(result["direction15"], 1)
        self.assertEqual(result["direction30"], 1)
        self.assertTrue(result["flags"]["M"])
        self.assertEqual(len(bank.channels[15].履歴), 2)
        self.assertEqual(bank.channels[30].履歴[0], {"high": 105, "low": 99, "close": 105, "count": 6})

    def test_場末の未完成上位足を次の場へつながない(self) -> None:
        """場起点の端数を破棄し、5分足一つで旧場の30分足を完成させない。

        引数: なし。
        返り値: None。
        """
        bank = 有効窓()
        for number in range(5):
            bank.update(足(number, 100 + number))
        self.assertEqual(len(bank.channels[30].履歴), 0)
        bank.start_session()
        bank.update(足(0, 200))
        self.assertEqual(len(bank.channels[30].履歴), 0)
        self.assertEqual(bank.parts[30]["count"], 1)

    def test_中央値と出来高分母から今足を除く(self) -> None:
        """突出した今足を加える前の60値・20値を比較基準にする。

        引数: なし。
        返り値: None。
        """
        bank = 有効窓(ATR=20000)
        bank.norms = deque(range(60), maxlen=60)
        result = bank.update(足(0, 200, 1000))
        self.assertEqual(result["norm_threshold"], 29.5)
        self.assertEqual(result["norm_atr"], 100)
        self.assertEqual(result["relative_volume"], 100)
        self.assertFalse(result["flags"]["B"])
        self.assertEqual(bank.norms[-1], 100)
        self.assertEqual(bank.volumes[-1], 1000)

    def test_突破範囲は今足を含めない(self) -> None:
        """今足の高値が大きくても、直前6足の高値を超える終値を検出する。

        引数: なし。
        返り値: None。
        """
        bank = 有効窓()
        bank.ranges = deque([(number, 90) for number in range(100, 106)], maxlen=6)
        current = 足(0, 106)
        current["high"] = 1000
        result = bank.update(current)
        self.assertEqual(result["upper"], 105)
        self.assertEqual(result["side"], 1)
        self.assertEqual(bank.ranges[-1][0], 1000)

    def test_RSIは50の方向条件を追加しない(self) -> None:
        """買いで50未満、売りで50超でも、非過熱だけなら通す。

        引数: なし。
        返り値: None。
        """
        for direction, rsi5, rsi15 in ((1, 45, 40), (-1, 55, 60)):
            with self.subTest(方向=direction):
                result = 有効窓(direction, rsi5, rsi15).update(足())
                self.assertTrue(result["ready"])
                self.assertEqual(result["side"], direction)
                self.assertTrue(result["flags"]["R"])

    def test_RSIのしきい値は厳密な不等号(self) -> None:
        """買いの70と売りの30を通さず、5分・15分の両方を確認する。

        引数: なし。
        返り値: None。
        """
        for direction, rsi5, rsi15 in ((1, 70, 60), (1, 60, 70), (-1, 30, 40), (-1, 40, 30)):
            with self.subTest(方向=direction, RSI5=rsi5, RSI15=rsi15):
                self.assertFalse(有効窓(direction, rsi5, rsi15).update(足())["flags"]["R"])

    def test_数量無効後は直前20足を蓄積し直す(self) -> None:
        """無効足を飛び越した出来高平均を使わず、20足の連続基準を作り直す。

        引数: なし。
        返り値: None。
        """
        bank = 有効窓()
        self.assertFalse(bank.update(足(0, 数量有効=False))["ready"])
        self.assertEqual(len(bank.volumes), 0)
        for number in range(1, 21):
            self.assertFalse(bank.update(足(number))["ready"])
        self.assertTrue(bank.update(足(21))["ready"])

    def test_四因子は16種類で重複しない(self) -> None:
        """候補が4因子の全ての部分集合に一対一で対応する。

        引数: なし。
        返り値: None。
        """
        rules = 再生.factorial_rules()
        self.assertEqual(len(rules), 16)
        self.assertEqual(len({rule["名前"] for rule in rules}), 16)
        self.assertEqual(len({frozenset(rule["因子"]) for rule in rules}), 16)
        self.assertEqual(sum(len(rule["因子"]) for rule in rules), 32)
        self.assertEqual(rules[0]["因子"], [])
        self.assertEqual(set(rules[-1]["因子"]), set("MRVB"))


# ----------------------------------------
# 数量時計・欠足・観測の省略

class 観測と欠足の検証(unittest.TestCase):
    """数量の未来参照と欠足後の状態汚染を合成観測で検出する。"""

    def test_未来の数量時計で基準を更新しない(self) -> None:
        """価格時計より先の数量を無視し、後の利用可能な値との差だけを数える。

        引数: なし。
        返り値: None。
        """
        volume = 再生.観測数量()
        first = 足()
        first["volume"] = 0
        volume.update(観測(0, 数量=100), first)
        volume.update(観測(60, 数量=999, 数量秒=120), first)
        self.assertEqual(volume.previous, 100)
        self.assertEqual(first["volume"], 0)
        self.assertEqual(volume.future, 1)
        volume.update(観測(180, 数量=120), first)
        self.assertEqual(first["volume"], 20)

    def test_累積減少と数量時計後退は差分を加算しない(self) -> None:
        """数量のリセットと時計後退では、当足を無効にして基準だけ更新する。

        引数: なし。
        返り値: None。
        """
        for second in (観測(60, 数量=90), 観測(60, 数量=110, 数量秒=-1)):
            with self.subTest(観測=second):
                volume = 再生.観測数量()
                current = 足()
                current["volume"] = 0
                volume.update(観測(0), current)
                current["volume_ok"] = True
                volume.update(second, current)
                self.assertEqual(current["volume"], 0)
                self.assertFalse(current["volume_ok"])
                self.assertEqual(volume.previous, second.volume)

    def test_欠足の後は数量基準を再初期化する(self) -> None:
        """観測されない5分区間をまたぐ数量差を、後続の一足へ流し込まない。

        引数: なし。
        返り値: None。
        """
        bank = 台本足()
        events = [観測(0, 1, 数量=100), 観測(60, 2, 数量=110),
                  観測(300, 3, 数量=120), 観測(900, 4, 数量=200),
                  観測(960, 5, 数量=205), 観測(1200, 6, 数量=210)]
        _, _, quality = 合成再生(events, bank, 分数=25)
        bars = {bar["index"]: bar for bar in bank.記録}
        self.assertEqual(quality["足欠損"], 1)
        self.assertGreaterEqual(bank.初期化数, 2)
        self.assertEqual(bars[3]["volume"], 5)
        self.assertFalse(bars[3]["volume_ok"])
        self.assertEqual(bars[4]["volume"], 5)
        self.assertTrue(bars[4]["volume_ok"])

    def test_非正Lastだけの区間も欠足として扱う(self) -> None:
        """板だけがある無効価格区間の後も、数量差分の連続性を切る。

        引数: なし。
        返り値: None。
        """
        bank = 台本足()
        events = [観測(0, 1, 数量=100), 観測(300, 2, 現在値=0, 数量=150),
                  観測(600, 3, 数量=200), 観測(660, 4, 数量=205)]
        _, _, quality = 合成再生(events, bank)
        second = next(bar for bar in bank.記録 if bar["index"] == 2)
        self.assertEqual(quality["足欠損"], 1)
        self.assertEqual(second["volume"], 5)
        self.assertFalse(second["volume_ok"])

    def test_欠足後も数量の品質件数は失わない(self) -> None:
        """欠足前の未来数量件数と再基準化を、場全体の品質へ残す。

        引数: なし。
        返り値: None。
        """
        events = [観測(0, 1), 観測(60, 2, 数量=110, 数量秒=120),
                  観測(300, 3, 数量=120), 観測(900, 4, 数量=200),
                  観測(1200, 5, 数量=210)]
        _, _, quality = 合成再生(events, 台本足(), 分数=25)
        self.assertEqual(quality["数量未来時計未使用イベント"], 1)
        self.assertEqual(quality["数量再基準化"], 2)

    def test_同時計の完全同一観測を省いても約定は同じ(self) -> None:
        """同一イベントの連続重複を消しても、1価格時計秒待つ約定列は変わらない。

        引数: なし。
        返り値: None。
        """
        events = [観測(0, 1), 観測(60, 2, 数量=110),
                  観測(300, 3, 現在値=110, 買気配=109, 売気配=110, 数量=120),
                  観測(300, 4, 現在値=110, 買気配=109, 売気配=110, 数量=120),
                  観測(301, 5, 現在値=110, 買気配=109, 売気配=110, 数量=120),
                  観測(301, 6, 現在値=110, 買気配=109, 売気配=110, 数量=120),
                  観測(600, 7, 買気配=109, 売気配=110, 数量=130),
                  観測(600, 8, 買気配=109, 売気配=110, 数量=130),
                  観測(601, 9, 買気配=109, 売気配=110, 数量=130)]
        compressed = [events[0]]
        for event in events[1:]:
            previous = compressed[-1]
            if event._replace(line=0) != previous._replace(line=0):
                compressed.append(event)
        script = {0: 特徴(), 1: 特徴(ready=False, side=0, close=98, ema=100)}
        original, _, _ = 合成再生(events, 台本足(script))
        reduced, _, _ = 合成再生(compressed, 台本足(script))
        self.assertEqual(len(original[0].fills), 2)
        self.assertEqual(original[0].fills, reduced[0].fills)
        self.assertEqual(original[0].trades, reduced[0].trades)
        self.assertEqual(original[0].cash, -12)


# ----------------------------------------
# 注文・保護・会計・比較不能の検証

class 注文と会計の検証(unittest.TestCase):
    """確定足の発動から約定・返済までを観測順に確かめる。"""

    def test_30秒を超えて確認した発動は棄却する(self) -> None:
        """30秒ちょうどは許し、それを超える古い発動は使わない。

        引数: なし。
        返り値: None。
        """
        for delay, allowed in ((30, True), (30.001, False)):
            with self.subTest(遅延=delay):
                state = 手法()
                state.on_signal(特徴(), 基準時刻 + 300 + delay, 1, 1)
                self.assertEqual(state.pending is not None, allowed)

    def test_通常出口は非突破かつ共通無効でも機能する(self) -> None:
        """入口の準備条件と独立に、買い・売り両方のEMA反対側決済を要求する。

        引数: なし。
        返り値: None。
        """
        for side, close, ema in ((1, 100, 101), (-1, 100, 99)):
            with self.subTest(方向=side):
                state = 手法(list("MRVB"))
                now = 建てる(state, side)
                state.on_signal(特徴(ready=False, side=0, close=close, ema=ema), now + 300, 3, 4)
                self.assertEqual(state.pending["kind"], "exit")
                self.assertEqual(state.pending["reason"], "EMA反対側")

    def test_EMAと同値では通常出口を発動しない(self) -> None:
        """出口の厳密な不等号を保ち、同値を反対側と扱わない。

        引数: なし。
        返り値: None。
        """
        state = 手法()
        now = 建てる(state)
        state.on_signal(特徴(ready=False, side=0, close=100, ema=100), now + 300, 3, 4)
        self.assertIsNone(state.pending)

    def test_新規も返済も要求と同時計では約定しない(self) -> None:
        """正常板でも要求時計から1秒に達するまでは待機する。

        引数: なし。
        返り値: None。
        """
        state = 手法()
        now = 基準時刻 + 900
        state.request("entry", 1, now, 1, "価格帯突破", 5)
        state.on_quote(now, 2, 3, 99, 100, True)
        state.on_quote(now + 0.9, 3, 3, 99, 100, True)
        self.assertEqual(state.fills, [])
        state.on_quote(now + 1, 4, 3, 99, 100, True)
        state.request("exit", 1, now + 2, 5, "EMA反対側")
        state.on_quote(now + 2, 5, 3, 99, 100, True)
        self.assertEqual(len(state.fills), 1)
        state.on_quote(now + 3, 6, 3, 99, 100, True)
        self.assertEqual(len(state.fills), 2)
        self.assertEqual(state.cash, -12)

    def test_保護は入口ATR固定で発動後の正常板で返済する(self) -> None:
        """買いはBid・売りはAskで保護を発動し、不正板を飛ばして費用を一度だけ払う。

        引数: なし。
        返り値: None。
        """
        for side, trigger, execution, stop in ((1, (89, 90), (88, 89), 90),
                                             (-1, (109, 110), (110, 111), 109)):
            with self.subTest(方向=side):
                state = 手法()
                now = 建てる(state, side, ATR=5)
                self.assertEqual(state.position["stop"], stop)
                state.on_quote(now + 2, 3, 3, *trigger, True)
                self.assertIsNotNone(state.position)
                self.assertEqual(state.pending["reason"], "保護発動")
                state.on_quote(now + 3, 4, 3, *execution, False)
                self.assertEqual(len(state.fills), 1)
                state.on_quote(now + 4, 5, 3, *execution, True)
                self.assertIsNone(state.position)
                self.assertEqual(state.trades[0]["値幅損益円"], -120)
                self.assertEqual(state.trades[0]["手数料円"], 2)
                self.assertEqual(state.cash, -122)
                self.assertEqual(state.trades[0]["MAE円"], 120)

    def test_新規要求は30秒超過と新規停止時刻で失効する(self) -> None:
        """遅い板や停止時刻以後の板で期限切れ新規を約定させない。

        引数: なし。
        返り値: None。
        """
        for at_cutoff in (False, True):
            with self.subTest(停止境界=at_cutoff):
                state = 手法()
                now = state.cutoff - 1 if at_cutoff else 基準時刻 + 900
                state.request("entry", 1, now, 1, "価格帯突破", 5)
                state.on_quote(state.cutoff if at_cutoff else now + 31, 2, 3, 99, 100, True)
                self.assertIsNone(state.position)
                self.assertIsNone(state.pending)
                self.assertEqual(state.cancellations, 1)

    def test_期限返済は保護より優先し場末時計では約定させない(self) -> None:
        """期限の要求理由を維持し、ザラバ終了未満の正常板だけで返済する。

        引数: なし。
        返り値: None。
        """
        state = 手法()
        建てる(state)
        state.on_quote(state.force, 3, 82, 89, 90, True)
        self.assertEqual(state.pending["reason"], "期限返済")
        self.assertEqual(len(state.fills), 1)
        state.on_quote(state.end, 4, 83, 89, 90, True)
        self.assertIsNotNone(state.position)
        self.assertEqual(len(state.fills), 1)

    def test_期限要求後の最初の正常板で返済する(self) -> None:
        """期限返済も同時計を避け、1秒後の板で現金と取引会計を一致させる。

        引数: なし。
        返り値: None。
        """
        state = 手法()
        建てる(state)
        state.on_quote(state.force, 3, 82, 99, 100, True)
        state.on_quote(state.force + 1, 4, 82, 99, 100, True)
        self.assertIsNone(state.position)
        self.assertEqual(state.trades[0]["返済理由"], "期限返済")
        self.assertEqual(state.cash, state.trades[0]["純損益円"])

    def test_未解消は総純損益にも対応差にも使わない(self) -> None:
        """完結取引だけの合計を、未解消を含む主結果として公表しない。

        引数: なし。
        返り値: None。
        """
        row = {"銘柄": "NK225", "場": "合成場", "期間": "探索", "手法": "基準",
               "取引数": 0, "終了建玉": 1, "終了未約定": 1, "純損益円": -1,
               "含み込み最大DD円": 50, "最大資産円": 0, "最小資産円": -50}
        summary = 再生.legacy.summary([], [row])
        self.assertIsNone(summary["純損益円"])
        self.assertIsNone(summary["平均場損益円"])
        rules = [{"名前": "基準", "因子": []}, {"名前": "M", "因子": ["M"]}]
        after = row | {"手法": "M", "終了建玉": 0, "終了未約定": 0, "純損益円": 0}
        comparison = 再生.paired_effects([row, after], rules)[0]
        self.assertEqual(comparison["結果状態"], "未解消・比較不可")
        self.assertIsNone(comparison["純損益差円"])

    def test_履歴専用は発動があっても取引しない(self) -> None:
        """指標初期化用の場で、未選択候補の取引計算を起こさない。

        引数: なし。
        返り値: None。
        """
        state = 手法(取引禁止=True)
        state.on_signal(特徴(), 基準時刻 + 300, 1, 1)
        self.assertIsNone(state.pending)
        self.assertEqual(state.fills, [])


# ----------------------------------------
# 追加試行の利確と確定足追尾

class 利確と追尾の検証(unittest.TestCase):
    """利確を指値保証と扱わず、追尾は確定足で一方向だけ更新する。"""

    def test_ATR利確は待機し価格が戻れば戻り価格で返済する(self) -> None:
        """買いBid・売りAskで発動し、次の正常板が不利へ戻ってもその価格で決済する。

        引数: なし。
        返り値: None。
        """
        for side, trigger, execution, expected in ((1, (105, 106), (103, 104), 103),
                                                  (-1, (93, 94), (96, 97), 97)):
            with self.subTest(方向=side):
                state = 手法(利確ATR倍=1)
                now = 建てる(state, side)
                state.on_quote(now + 2, 3, 3, *trigger, True)
                self.assertIsNotNone(state.position)
                self.assertEqual(state.pending["reason"], "ATR利確")
                self.assertEqual(len(state.fills), 1)
                state.on_quote(now + 3, 4, 3, *execution, True)
                self.assertEqual(state.trades[0]["返済価格"], expected)
                self.assertEqual(state.trades[0]["返済理由"], "ATR利確")
                self.assertEqual(state.cash, 28 if side == 1 else 18)

    def test_ATR利確を飛び越えても目標価格へ約定を固定しない(self) -> None:
        """有利な飛越えでも、発動時計より1秒後の実際のBBOを使う。

        引数: なし。
        返り値: None。
        """
        for side, trigger, execution, expected in ((1, (110, 111), (112, 113), 112),
                                                  (-1, (88, 89), (86, 87), 87)):
            with self.subTest(方向=side):
                state = 手法(利確ATR倍=1)
                now = 建てる(state, side)
                target = state.position["target"]
                state.on_quote(now + 2, 3, 3, *trigger, True)
                self.assertEqual(len(state.fills), 1)
                state.on_quote(now + 3, 4, 3, *execution, True)
                self.assertNotEqual(expected, target)
                self.assertEqual(state.trades[0]["返済価格"], expected)
                self.assertEqual(state.cash, 118)

    def test_ATR利確目標は有利側の呼値へ外丸めする(self) -> None:
        """小数の入口ATRによる目標は買いで切上げ、売りで切下げする。

        引数: なし。
        返り値: None。
        """
        for side, expected in ((1, 103), (-1, 96)):
            with self.subTest(方向=side):
                state = 手法(利確ATR倍=1)
                建てる(state, side, ATR=2.25)
                self.assertEqual(state.position["target"], expected)

    def test_確定足追尾は損失側へ後退しない(self) -> None:
        """ATR拡大や終値の逆行で保護を緩めず、有利な更新だけ採用する。

        引数: なし。
        返り値: None。
        """
        for side, closes, stops in ((1, (110, 105, 120), (102, 102, 112)),
                                    (-1, (90, 95, 80), (98, 98, 88))):
            with self.subTest(方向=side):
                state = 手法(追尾ATR倍=2, EMA決済=False)
                now = 建てる(state, side)
                for number, (close, atr, expected) in enumerate(zip(closes, (4, 10, 4), stops), 1):
                    state.on_signal(特徴(ready=False, side=0, close=close, atr=atr),
                                    now + number * 300, 10 + number, 3 + number)
                    self.assertEqual(state.position["stop"], expected)
                    self.assertIsNone(state.pending)

    def test_形成中足の気配では追尾水準を動かさない(self) -> None:
        """気配が有利に動いても次の確定足まで保護を固定する。

        引数: なし。
        返り値: None。
        """
        for side, quotes, close, expected in ((1, (109, 110), 110, 102),
                                             (-1, (89, 90), 90, 98)):
            with self.subTest(方向=side):
                state = 手法(追尾ATR倍=2, EMA決済=False)
                now = 建てる(state, side)
                initial = state.position["stop"]
                state.on_quote(now + 2, 3, 3, *quotes, True)
                self.assertEqual(state.position["stop"], initial)
                state.on_signal(特徴(ready=False, side=0, close=close, atr=4), now + 300, 4, 4)
                self.assertEqual(state.position["stop"], expected)
                state.on_quote(now + 301, 5, 4, *quotes, True)
                self.assertEqual(state.position["stop"], expected)
                self.assertEqual(state.position["atr"], 5)


# ----------------------------------------
# 独立会計監査自身の異常検出

class 台帳監査の検証(unittest.TestCase):
    """手計算の一往復台帳と、意図的に壊した台帳を区別できるか確かめる。"""

    def test_正しい台帳と六種類の異常を区別する(self) -> None:
        """手計算98円と参照台帳を通し、費用・方向・帰属・ID・時刻・参照ハッシュの異常を拒否する。

        引数: なし。
        返り値: None。
        """
        path = Path(__file__).with_name("台帳検証.py")
        spec = importlib.util.spec_from_file_location("独立台帳監査の合成検証対象", path)
        audit = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = audit
        spec.loader.exec_module(audit)

        def CSVを保存(path: Path, rows: list[dict[str, Any]]) -> None:
            """合成の小集計をUTF-8のCSVで保存する。

            引数: path (Path) は保存先、rows (list[dict[str, Any]]) は同じ列の行。
            返り値: None。
            """
            with path.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

        with TemporaryDirectory(prefix="独立台帳_") as temporary:
            parent = Path(temporary)
            folder = parent / "試行"
            folder.mkdir()
            manifest = parent / "共用台帳.json"
            manifest.write_text(json.dumps({"entries": [{"symbol": "NK225", "session": "2026-10-30_Day",
                                                        "source_path": "合成原板", "raw_lines": 300}]}), encoding="utf-8")
            config = {"商品": {"NK225": 商品}, "候補": [{"名前": "基準", "因子": []}],
                      "キャッシュルート": "work/合成", "新規停止": {"Day": "15:25", "Night": "05:40"},
                      "全返済要求": {"Day": "15:35", "Night": "05:50"}}
            (folder / "条件.json").write_text(json.dumps(config), encoding="utf-8")
            resource = {"id": "合成", "symbol": "NK225", "session": "2026-10-30_Day",
                        "product": 商品["product"], "point_value": 10, "method_id": "基準",
                        "entry_method_id": "基準", "pnl_format": "trades", "pnl_basis": "net",
                        "pnl_path": "合成.trades.jsonl", "market_path": "合成原板"}
            (folder / "一覧.resources.json").write_text(json.dumps({"schema_version": 1, "path_base": "catalog",
                                                                   "resources": [resource]}), encoding="utf-8")
            session = {"銘柄": "NK225", "場": "2026-10-30_Day", "手法": "基準", "取引数": 1,
                       "純損益円": 98, "終了建玉": 0, "終了未約定": 0}
            trade = {"銘柄": "NK225", "場": "2026-10-30_Day", "手法": "基準", "建玉ID": "P",
                     "方向": "買い", "新規時刻": "2026-10-30T10:00:00+09:00", "返済時刻": "2026-10-30T10:05:00+09:00",
                     "数量": 1, "新規価格": 100, "返済価格": 110, "値幅損益円": 100, "手数料円": 2,
                     "純損益円": 98, "新規原板行": 100, "返済原板行": 200, "保有秒": 300,
                     "判断から新規秒": 1, "要求から返済秒": 1, "返済理由": "EMA反対側", "入口ATR": 5, "保護価格": 90}
            CSVを保存(folder / "セッション集計.csv", [session])
            CSVを保存(folder / "取引集計.csv", [trade])
            for case in ("正常", "費用", "返済方向", "新規帰属", "重複ID", "時刻逆転", "参照ハッシュ"):
                with self.subTest(異常=case):
                    fills = [{"id": "N", "position_id": "P", "timestamp": trade["新規時刻"], "type": "LongN",
                              "price": 100, "qty": 1, "fee_yen": 1, "source_line": 100, "method_id": "基準"},
                             {"id": "R", "position_id": "P", "timestamp": trade["返済時刻"], "type": "LongR",
                              "price": 110, "qty": 1, "fee_yen": 1, "source_line": 200, "method_id": "基準"}]
                    if case == "費用":
                        fills[0]["fee_yen"] = 2
                    elif case == "返済方向":
                        fills[1]["type"] = "ShortR"
                    elif case == "新規帰属":
                        fills[0]["method_id"] = "別手法"
                    elif case == "重複ID":
                        fills[1]["id"] = "N"
                    elif case == "時刻逆転":
                        fills[1]["timestamp"] = "2026-10-30T09:59:00+09:00"
                    (folder / "合成.trades.jsonl").write_text("".join(json.dumps(fill) + "\n" for fill in fills), encoding="utf-8")
                    reference = {"参照": "../共用台帳.json", "SHA256": "0" * 64 if case == "参照ハッシュ" else audit.ハッシュ(manifest)}
                    (folder / "入力台帳.json").write_text(json.dumps(reference), encoding="utf-8")
                    result = audit.実行(folder)
                    self.assertEqual(result["監査状態"], "成功" if case == "正常" else "失敗")
                    self.assertEqual(result["不一致数"] == 0, case == "正常")


if __name__ == "__main__":
    unittest.main(verbosity=2)
