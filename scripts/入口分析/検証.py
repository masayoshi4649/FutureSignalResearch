"""実損益を見ず、先着到達検索を独立した順走査と合成経路で検証する。"""

from __future__ import annotations

from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import random
import sys
from typing import Any, NamedTuple
import unittest
from unittest.mock import patch

import numpy as np


対象パス = Path(__file__).with_name("分析.py")
仕様 = importlib.util.spec_from_file_location("入口分析の合成検証対象", 対象パス)
分析 = importlib.util.module_from_spec(仕様)
sys.modules[仕様.name] = 分析
仕様.loader.exec_module(分析)


# ----------------------------------------
# 参照実装は到達木・気配経路を呼ばず、原順に一つずつ判定する

class 観測(NamedTuple):
    """価格時計・原行・気配と、足作成用の最小入力。"""

    now: float
    line: int
    bid: float
    ask: float
    last: float = 1000
    valid: bool = True
    volume: float = 100
    volume_time: float = 0


def 素朴評価(quotes: list[観測], signal: float, cutoff: float, deadline: float,
         side: int, adverse: float = 200, favorable: float = 400) -> dict[str, Any]:
    """正常観測を原順に一つずつ調べ、新規と二閾値の先着を判定する。

    引数: quotes (list[観測]) は正常板の原順、signal/cutoff/deadline (float) は各価格時計、
    side (int) は方向、adverse/favorable (float) は固定距離。
    返り値: dict[str, Any] は期待するラベル・根拠行・最大順逆行。
    """
    start = next((index for index, quote in enumerate(quotes) if quote.now >= signal + 1), None)
    empty = {"ラベル": "未約定", "理由": "30秒内に正常板なし", "新規価格": None,
             "新規時計秒": None, "新規原板行": None, "判定時計秒": None, "判定原板行": None,
             "判定気配": None, "最大順行pt": None, "最大逆行pt": None, "所要分": None}
    if start is None or quotes[start].now > signal + 30 or quotes[start].now >= cutoff:
        return empty
    entry_quote = quotes[start]
    entry = entry_quote.ask if side == 1 else entry_quote.bid
    distances = []
    last = start
    gap = False
    label = None
    for index in range(start, len(quotes)):
        quote = quotes[index]
        if quote.now > deadline:
            break
        if index > start and quote.now - quotes[index - 1].now > 300:
            gap = True
            break
        distance = side * ((quote.bid if side == 1 else quote.ask) - entry)
        distances.append(distance)
        last = index
        if distance <= -adverse:
            label = "逆行先着"
            break
        if distance >= favorable:
            label = "順行先着"
            break
    if label is not None:
        reason = "返済気配の閾値初着"
    else:
        covered = any(quote.now >= deadline for quote in quotes)
        stale = deadline - quotes[last].now > 300
        label = "観測不足" if gap or not covered or stale else "期限未達"
        reason = ("正常板価格時計300秒超空白" if gap or stale else
                  "入力末尾不足" if not covered else "期限内どちらも未到達")
    quote = quotes[last]
    return {"ラベル": label, "理由": reason, "新規価格": float(entry),
            "新規時計秒": float(entry_quote.now), "新規原板行": entry_quote.line,
            "判定時計秒": float(quote.now), "判定原板行": quote.line,
            "判定気配": float(quote.bid if side == 1 else quote.ask),
            "最大順行pt": float(max([0, *distances])), "最大逆行pt": float(max([0, *[-value for value in distances]])),
            "所要分": float((quote.now - entry_quote.now) / 60)}


def 距離経路(side: int, points: list[tuple[float, float]]) -> list[観測]:
    """新規価格からの返済気配距離を指定し、両方向の正常板列を作る。

    引数: side (int) は方向、points (list[tuple[float, float]]) は時刻・利益方向距離の組。
    返り値: list[観測] は時刻1で約定できる列。最初のスプレッド距離は-1。
    """
    result = [観測(1, 1, 1000, 1001)]
    entry = 1001 if side == 1 else 1000
    for line, (now, distance) in enumerate(points, 2):
        mark = entry + side * distance
        bid, ask = (mark, mark + 1) if side == 1 else (mark - 1, mark)
        result.append(観測(now, line, bid, ask))
    return result


def 確定足(index: int, close: float, start: float = 0, flat: bool = False) -> dict[str, Any]:
    """数量準備を満たさない合成5分足を作る。

    引数: index (int) は場内番号、close/start (float) は終値・場開始秒、flat (bool) は値幅ゼロか。
    返り値: dict[str, Any] は数量基準が無効な確定足。
    """
    return {"index": index, "start": start + index * 300, "end": start + (index + 1) * 300,
            "open": close, "high": close if flat else close + 0.5,
            "low": close if flat else close - 0.5, "close": close,
            "volume": 0, "volume_ok": False, "volume_seen": False}


def 履歴付き特徴(flat: bool = False) -> Any:
    """過去に確定済みの合成足で指標を初期化し、新しい場の前まで進める。

    引数: flat (bool) は過去価格を一定にするか。
    返り値: 入口特徴 は過去履歴だけを持つ状態。
    """
    bank = 分析.入口特徴()
    bank.start_session(0)
    for number in range(300):
        bank.update(確定足(number, 1000 if flat else 1000 + number, flat=flat))
    bank.start_session(100000)
    return bank


class 特徴代役:
    """足の切り分け検証だけに既知の有効特徴を渡す。"""

    def __init__(self) -> None:
        """欠足で再初期化されても受領足の記録を残す。

        引数: なし。
        返り値: None。
        """
        self.bars = getattr(self, "bars", [])
        self.resets = getattr(self, "resets", 0) + 1

    def start_session(self, start: float) -> None:
        """場開始時刻を保存する。

        引数: start (float) は場開始秒。
        返り値: None。
        """
        self.start = start

    def update(self, bar: dict[str, Any]) -> dict[str, Any]:
        """確定対象を記録し、その終値と既知の比較特徴を返す。

        引数: bar (dict[str, Any]) は確定対象。
        返り値: dict[str, Any] は候補生成を許す合成特徴。
        """
        self.bars.append(dict(bar))
        return {"ready": True, "direction5": 1, "direction15": 1, "direction30": 1,
                "side": 1, "previous_squeeze": False, "expansion": False, "recovery": 0,
                "close": bar["close"], "ema": 999, "atr": 10, "rsi5": 60, "rsi15": 60,
                "tr_previous_atr": 1, "relative_volume": None, "upper": 999, "lower": 900}


# ----------------------------------------
# 区間木と、素朴な全探索との一致

class 検索の検証(unittest.TestCase):
    """最初の到達位置と区間の端点を、別の順走査で確認する。"""

    def test_空列と一要素と等号(self) -> None:
        """空列・一要素でも安全で、下限上限の等号を含む。

        引数: なし。
        返り値: None。
        """
        self.assertIsNone(分析.到達木(np.array([])).first(0, 0, 1, 2))
        for value, expected in ((0, 0), (1, 0), (2, None), (3, 0), (4, 0)):
            with self.subTest(価格=value):
                self.assertEqual(分析.到達木(np.array([value])).first(0, 1, 1, 3), expected)

    def test_半開区間の外の到達を使わない(self) -> None:
        """開始前と終了位置の価格を検索対象から除く。

        引数: なし。
        返り値: None。
        """
        tree = 分析.到達木(np.array([0, 5, 5, 10]))
        self.assertIsNone(tree.first(1, 3, 0, 10))
        self.assertEqual(tree.first(1, 4, 0, 10), 3)
        self.assertIsNone(tree.first(2, 2, 0, 10))

    def test_固定乱数の区間木が素朴検索と一致する(self) -> None:
        """非2冪長を含む80配列・計6400区間を、独立した順走査と比較する。

        引数: なし。
        返り値: None。
        """
        rng = random.Random(20261101)
        for case in range(80):
            prices = [rng.randrange(900, 1101) for _ in range(rng.randrange(0, 75))]
            tree = 分析.到達木(np.array(prices, dtype=float))
            for _ in range(80):
                start = rng.randrange(len(prices) + 1)
                end = rng.randrange(start, len(prices) + 1)
                lower = rng.randrange(900, 1001)
                upper = rng.randrange(1001, 1101)
                expected = next((i for i in range(start, end) if prices[i] <= lower or prices[i] >= upper), None)
                self.assertEqual(tree.first(start, end, lower, upper), expected, (case, start, end))

    def test_固定乱数の経路判定が素朴順走査と両方向で一致する(self) -> None:
        """空白・重複時計・期限外板を含む240経路を両方向で照合する。

        引数: なし。
        返り値: None。
        """
        rng = random.Random(20261102)
        for case in range(240):
            quotes = []
            now = 0
            for line in range(1, rng.randrange(0, 70) + 1):
                now += rng.choice((0, 1, 2, 10, 100, 299, 300, 301, 600))
                bid = rng.randrange(700, 1701)
                quotes.append(観測(now, line, bid, bid + rng.choice((1, 5, 50, 200, 300))))
            signal = rng.randrange(0, max(1, now + 20))
            cutoff = signal + rng.randrange(1, 100)
            deadline = cutoff + rng.randrange(1, 1000)
            route = 分析.気配経路(quotes)
            for side in (1, -1):
                expected = 素朴評価(quotes, signal, cutoff, deadline, side)
                actual = route.evaluate(signal, cutoff, deadline, side)
                self.assertEqual(actual, expected, (case, side, signal, deadline))


# ----------------------------------------
# 約定と、先着ラベルの境界

class 先着の検証(unittest.TestCase):
    """保存観測上の先着を、売買両方向の手計算ケースで確かめる。"""

    def test_両方向の閾値は等号込み(self) -> None:
        """400ptちょうどと-200ptちょうどを到達として扱う。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            for distance, label in ((400, "順行先着"), (-200, "逆行先着")):
                with self.subTest(方向=side, 距離=distance):
                    result = 分析.気配経路(距離経路(side, [(2, distance)])).evaluate(0, 100, 1000, side)
                    self.assertEqual(result["ラベル"], label)
                    self.assertEqual(result["判定原板行"], 2)

    def test_順行後の逆行と逆行後の順行でラベルを変更しない(self) -> None:
        """先着後の価格を、ラベルと最大順逆行のどちらにも混ぜない。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            for points, label, mfe, mae in (([(2, 400), (3, -500)], "順行先着", 400, 1),
                                            ([(2, -200), (3, 800)], "逆行先着", 0, 200)):
                with self.subTest(方向=side, ラベル=label):
                    result = 分析.気配経路(距離経路(side, points)).evaluate(0, 100, 1000, side)
                    self.assertEqual((result["ラベル"], result["最大順行pt"], result["最大逆行pt"]), (label, mfe, mae))

    def test_同時計は原板の物理行順で先着を決める(self) -> None:
        """同じ価格時計に両閾値が現れても、原順を勝手に価格順へ並べ替えない。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            for distances, label in (((400, -200), "順行先着"), ((-200, 400), "逆行先着")):
                with self.subTest(方向=side, 順序=distances):
                    quotes = 距離経路(side, [(2, value) for value in distances])
                    result = 分析.気配経路(quotes).evaluate(0, 100, 1000, side)
                    self.assertEqual(result["ラベル"], label)
                    self.assertEqual(result["判定原板行"], 2)

    def test_300秒超の空白はその直後の到達より優先する(self) -> None:
        """空白中の逆側先着を否定できないため、再開板の到達を採用しない。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            result = 分析.気配経路(距離経路(side, [(302, 400)])).evaluate(0, 100, 500, side)
            self.assertEqual(result["ラベル"], "観測不足")
            self.assertEqual(result["判定原板行"], 1)
            self.assertEqual(result["最大順行pt"], 0)

    def test_300秒ちょうどの空白は許容する(self) -> None:
        """超過という定義を保ち、300秒間隔の到達は捨てない。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            result = 分析.気配経路(距離経路(side, [(301, 400)])).evaluate(0, 100, 500, side)
            self.assertEqual(result["ラベル"], "順行先着")

    def test_先着した後の空白はラベルを不明に戻さない(self) -> None:
        """先着は既に観測できているため、後続の欠測で取り消さない。

        引数: なし。
        返り値: None。
        """
        quotes = 距離経路(1, [(2, 400), (1000, -200)])
        self.assertEqual(分析.気配経路(quotes).evaluate(0, 100, 1200, 1)["ラベル"], "順行先着")

    def test_期限ちょうどの板を含め期限後は使わない(self) -> None:
        """期限端点の到達だけを採用し、1秒後の到達で期限ラベルを書き換えない。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            exact = 分析.気配経路(距離経路(side, [(100, 400)])).evaluate(0, 50, 100, side)
            after = 分析.気配経路(距離経路(side, [(99, 0), (101, 400)])).evaluate(0, 50, 100, side)
            self.assertEqual(exact["ラベル"], "順行先着")
            self.assertEqual(after["ラベル"], "期限未達")
            self.assertEqual(after["判定時計秒"], 99)
            self.assertEqual(after["最大順行pt"], 0)

    def test_次板が期限後でも期限までの空白超過を不明にする(self) -> None:
        """次板の時計だけで期限まで観測できたと扱わず、最後の板からの空白を調べる。

        引数: なし。
        返り値: None。
        """
        route = 分析.気配経路(距離経路(1, [(500, 400)]))
        self.assertEqual(route.evaluate(0, 100, 302, 1)["ラベル"], "観測不足")
        self.assertEqual(route.evaluate(0, 100, 301, 1)["ラベル"], "期限未達")

    def test_EOFが期限前なら300秒以内でも不明にする(self) -> None:
        """短い入力末尾を、期限まで閾値未達だったという証拠にしない。

        引数: なし。
        返り値: None。
        """
        result = 分析.気配経路(距離経路(1, [(10, 20)])).evaluate(0, 50, 100, 1)
        self.assertEqual((result["ラベル"], result["理由"]), ("観測不足", "入力末尾不足"))

    def test_新規は1秒以上後の最初の板で30秒と停止境界を守る(self) -> None:
        """同時計を約定に使わず、30秒ちょうどを許し、新規停止ちょうどは拒否する。

        引数: なし。
        返り値: None。
        """
        route = 分析.気配経路([観測(0, 1, 900, 901), 観測(0.999, 2, 950, 951),
                            観測(30, 3, 1000, 1001), 観測(100, 4, 1000, 1001)])
        filled = route.evaluate(0, 31, 100, 1)
        self.assertEqual((filled["新規時計秒"], filled["新規原板行"]), (30, 3))
        self.assertEqual(route.evaluate(0, 30, 100, 1)["ラベル"], "未約定")
        late = 分析.気配経路([観測(30.001, 1, 1000, 1001)]).evaluate(0, 100, 100, 1)
        self.assertEqual(late["ラベル"], "未約定")

    def test_新規板のスプレッドだけで逆行線に届けば即失敗(self) -> None:
        """新規した同じ板の返済気配を、最大逆行と失敗判定へ含める。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            result = 分析.気配経路([観測(1, 1, 1000, 1200)]).evaluate(0, 50, 100, side)
            self.assertEqual(result["ラベル"], "逆行先着")
            self.assertEqual(result["最大逆行pt"], 200)
            self.assertEqual(result["所要分"], 0)

    def test_未約定と期限未達と観測不足を混ぜない(self) -> None:
        """空の入力、観測継続した未達、入力末尾不足を区別する。

        引数: なし。
        返り値: None。
        """
        self.assertEqual(分析.気配経路([]).evaluate(0, 50, 100, 1)["ラベル"], "未約定")
        self.assertEqual(分析.気配経路(距離経路(1, [(100, 10)])).evaluate(0, 50, 100, 1)["ラベル"], "期限未達")
        self.assertEqual(分析.気配経路(距離経路(1, [])).evaluate(0, 50, 100, 1)["ラベル"], "観測不足")


# ----------------------------------------
# 確定足・群の帰属・分母

class 特徴と集計の検証(unittest.TestCase):
    """未来の上位足と数量準備の有無を混同せず、同じ母集団を作る。"""

    def test_当場上位足と前のsnapshotが揃うまで使わない(self) -> None:
        """過去指標が初期化済みでも、新しい場の30分足と次の5分足まで待つ。

        引数: なし。
        返り値: None。
        """
        bank = 履歴付き特徴()
        old30 = bank.bank.channels[30].result
        for index in range(7):
            result = bank.update(確定足(index, 2000 + index, start=100000))
            if index < 5:
                self.assertIs(bank.bank.channels[30].result, old30)
                self.assertFalse(result["fresh"])
            if index <= 5:
                self.assertFalse(result["ready"])
        self.assertTrue(result["fresh"])
        self.assertTrue(result["ready"])
        self.assertIsNone(result["relative_volume"])

    def test_前ATRゼロでも拡大を直接比較できる(self) -> None:
        """ゼロ除算を避けつつ、静かな前足からの正のTR拡大を保持する。

        引数: なし。
        返り値: None。
        """
        bank = 履歴付き特徴(flat=True)
        for index in range(6):
            bank.update(確定足(index, 1000, start=100000, flat=True))
        result = bank.update(確定足(6, 1100, start=100000, flat=True))
        self.assertTrue(result["ready"])
        self.assertTrue(result["previous_squeeze"])
        self.assertTrue(result["expansion"])
        self.assertIsNone(result["tr_previous_atr"])

    def test_六群の帰属は固定特徴だけで決まる(self) -> None:
        """ラベルを渡さずに、方向・整合・突破・前収縮・拡大・回復で所属を作る。

        引数: なし。
        返り値: None。
        """
        values = {"direction5": 1, "direction15": 1, "direction30": 1, "side": 1,
                  "previous_squeeze": True, "expansion": True, "recovery": 1}
        self.assertEqual(set(分析.memberships(values, 1)), set(分析.GROUPS))
        self.assertEqual(分析.memberships(values, -1), [分析.GROUPS[0]])
        values["expansion"] = False
        self.assertNotIn(分析.GROUPS[5], 分析.memberships(values, 1))

    def test_期限と不明と未約定を集計の分母から黙って消さない(self) -> None:
        """全約定・判定可能・二閾値到達だけの三つの分母を区別する。

        引数: なし。
        返り値: None。
        """
        rows = [{"ラベル": label, "場": "合成場"} for label in 分析.LABELS]
        result = 分析.summarize(rows, 分析.GROUPS[0], "合成期間", "両方向")
        self.assertEqual(result["候補数"], 5)
        self.assertEqual(result["約定候補数"], 4)
        self.assertEqual(result["順行先着率_全約定"], 1 / 4)
        self.assertEqual(result["順行先着率_判定可能"], 1 / 3)
        self.assertEqual(result["順行先着率_二閾値到達のみ"], 1 / 2)

    def test_境界の観測を前の足へ混ぜずEOFから候補を発行しない(self) -> None:
        """次区間の大きな価格を直前終値へ混ぜず、EOF確定は履歴だけにする。

        引数: なし。
        返り値: None。
        """
        start = datetime(2026, 11, 1, 8, 45, tzinfo=分析.JST)
        begin = start.timestamp()
        times = (start, start + timedelta(minutes=15), start + timedelta(minutes=12), start + timedelta(minutes=14))
        events = [観測(begin, 1, 999, 1000, 1000, volume_time=begin),
                  観測(begin + 299, 2, 1003, 1004, 1004, volume_time=begin + 299),
                  観測(begin + 300, 3, 1998, 1999, 1999, volume_time=begin + 300)]
        bank = 特徴代役()
        with patch.object(分析.shared.legacy, "session_times", return_value=times):
            rows, _ = 分析.candidate_rows(events, "2026-11-01_Day", bank)
        self.assertEqual(len(rows), 2)
        self.assertEqual(bank.bars[0]["close"], 1004)
        self.assertEqual(bank.bars[0]["high"], 1004)
        self.assertTrue(all(row["終値"] == 1004 and row["要求原板行"] == 3 for row in rows))

    def test_欠足を飛び越す候補は作らず基準を再初期化する(self) -> None:
        """古い足を遅れて入口に使わず、欠けた区間の後は特徴を作り直す。

        引数: なし。
        返り値: None。
        """
        start = datetime(2026, 11, 1, 8, 45, tzinfo=分析.JST)
        begin = start.timestamp()
        times = (start, start + timedelta(minutes=15), start + timedelta(minutes=12), start + timedelta(minutes=14))
        bank = 特徴代役()
        events = [観測(begin, 1, 999, 1000, volume_time=begin),
                  観測(begin + 600, 2, 999, 1000, volume_time=begin + 600)]
        with patch.object(分析.shared.legacy, "session_times", return_value=times):
            rows, quality = 分析.candidate_rows(events, "2026-11-01_Day", bank)
        self.assertEqual(rows, [])
        self.assertEqual(quality["欠5分枠"], 1)
        self.assertEqual(bank.resets, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
