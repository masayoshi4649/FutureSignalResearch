"""実データを使わず、指標の既知値と注文の時間・売買方向を確認する。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("初回試行の計算", HERE / "再現.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
BASE = datetime(2026, 10, 1, 9, tzinfo=MODULE.JST).timestamp()


def bar(close: float) -> dict[str, float]:
    """
    機能: 指標の数値検証に使う正の高安終値を作る。
    引数: close (float) は終値。
    返り値: dict[str, float] は高値・安値・終値。
    """
    return {"high": close + 1, "low": close - 1, "close": close}


def signal(side: int = 1) -> dict[str, Any]:
    """
    機能: 注文処理へ渡す初期化済みの合成交差を作る。
    引数: side (int) は買い1または売り−1。
    返り値: dict[str, Any] は有効性・交差・方向・RSI・ATR。
    """
    return {"ready": True, "cross": side, "trend_direction": side,
            "rsi": 60 if side == 1 else 40, "atr": 5.0}


def strategy() -> Any:
    """
    機能: 1価格単位10円・手数料片道2円の合成戦略を作る。
    引数: なし。
    返り値: Any は実データや実料金と無関係なStrategy。
    """
    product = {"product": "合成商品", "point_value": 10, "tick": 5, "fee_yen": 2}
    return MODULE.Strategy("MACDのみ", "NK225", "2026-10-01_Day", product,
                           BASE + 50, BASE + 60, BASE + 90)


def open_position(side: int = 1) -> Any:
    """
    機能: 合成交差の1秒後に1枚の建玉を作る。
    引数: side (int) は買い1または売り−1。
    返り値: Any は買Ask105または売Bid100で約定済みのStrategy。
    """
    state = strategy()
    state.on_signal(signal(side), BASE, 1, 0)
    state.on_quote(BASE + 1, 2, 0, 100.0, 105.0, True)
    return state


def raw_row(at: datetime, close: float) -> dict[str, Any]:
    """
    機能: 原板再生へ入力する架空の1行を作る。
    引数: at (datetime) は価格時計、close (float) はLast。
    返り値: dict[str, Any] は正常気配・数量・固定限月を持つ行。
    """
    return {"Symbol": "合成限月", "SymbolName": "監査用の架空先物",
            "CurrentPriceTime": at.isoformat(), "CurrentPrice": close,
            "Buy1": {"Price": close - 5, "Qty": 10},
            "Sell1": {"Price": close + 5, "Qty": 10}}


# ----------------------------------------
# 数式の既知値と、入力本数の検証

class 指標の検証(unittest.TestCase):
    """相場の損益に依存しない計算例と初期化境界を確認する。"""

    def test_EMAは必要本数後にSMAで初期化する(self) -> None:
        """
        機能: EMA初回が5終値の単純平均で、その後だけ平滑更新するか確認する。
        引数: self (指標の検証) はテスト状態。
        返り値: None。
        """
        average = MODULE.Average(5, 2 / 6)
        values = [average.update(value) for value in (100, 101, 102, 103, 104, 110)]
        self.assertEqual(values[:4], [None] * 4)
        self.assertEqual(values[4], 102)
        self.assertAlmostEqual(values[5], float(Fraction(314, 3)))

    def test_MACDとシグナルと方向平均の必要本数(self) -> None:
        """
        機能: MACD初回26本・Signal初回34本・EMA60初回60本を確認する。
        引数: self (指標の検証) はテスト状態。
        返り値: None。
        """
        bank = MODULE.Indicators()
        values = [bank.update(bar(100 + index)) for index in range(61)]
        self.assertIsNone(values[24]["macd"])
        self.assertIsNotNone(values[25]["macd"])
        self.assertIsNone(values[32]["signal"])
        self.assertIsNotNone(values[33]["signal"])
        self.assertIsNone(values[58]["ema60"])
        self.assertTrue(values[59]["ready"])
        self.assertEqual(values[59]["cross"], 0)
        self.assertEqual(values[59]["trend_direction"], 0)
        self.assertEqual(values[60]["trend_direction"], 1)

    def test_MACDの定常価格から一度上がる既知例(self) -> None:
        """
        機能: 定常価格後の4単位上昇に対するEMA差とSignalの既知値を確認する。
        引数: self (指標の検証) はテスト状態。
        返り値: None。
        """
        bank = MODULE.Indicators()
        for _ in range(60):
            bank.update(bar(100))
        value = bank.update(bar(104))
        expected_macd = Fraction(112, 351)
        self.assertAlmostEqual(value["macd"], float(expected_macd))
        self.assertAlmostEqual(value["signal"], float(expected_macd / 5))

    def test_RSIの初期14変化とWilder更新の既知例(self) -> None:
        """
        機能: RSI14が15終値を必要とし、上25・下11の幅配分から更新するか確認する。
        引数: self (指標の検証) はテスト状態。
        返り値: None。
        """
        bank = MODULE.Indicators()
        close = 100.0
        self.assertIsNone(bank.update(bar(close))["rsi"])
        changes = [4, -2, 3, -1] * 3 + [4, -2]
        for index, change in enumerate(changes):
            close += change
            value = bank.update(bar(close))
            if index < 13:
                self.assertIsNone(value["rsi"])
        self.assertAlmostEqual(value["rsi"], float(Fraction(2500, 36)))
        value = bank.update(bar(close - 2))
        self.assertAlmostEqual(value["rsi"], float(Fraction(32500, 496)))

    def test_RSIの片方向と全同値を区別する(self) -> None:
        """
        機能: 連騰100・連落0と、全同値の欠損を区別する。
        引数: self (指標の検証) はテスト状態。
        返り値: None。
        """
        for change, expected in ((1, 100), (-1, 0), (0, None)):
            with self.subTest(変化=change):
                bank = MODULE.Indicators()
                for index in range(15):
                    value = bank.update(bar(100 + index * change))
                self.assertEqual(value["rsi"], expected)
                if change == 0:
                    self.assertFalse(value["ready"])


# ----------------------------------------
# 合成注文と約定の因果順序・売買方向の検証

class 約定の検証(unittest.TestCase):
    """未来の板や同時計を先取りせず、反対気配で会計するか確認する。"""

    def test_同時計と1秒未満では約定しない(self) -> None:
        """
        機能: 異なる原板行でも要求と同時計・1秒未満の気配を約定へ使わないか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = strategy()
        state.on_signal(signal(), BASE, 1, 0)
        for line, delta in ((2, 0), (3, 0), (4, 0.999)):
            state.on_quote(BASE + delta, line, 0, 100.0, 105.0, True)
            self.assertIsNone(state.position)
            self.assertEqual(state.fills, [])
        state.on_quote(BASE + 1, 5, 0, 100.0, 105.0, True)
        self.assertEqual(state.position["entry"], 105)
        self.assertEqual(state.fills[0]["source_line"], 5)

    def test_買い新規はAskで買い玉返済はBid(self) -> None:
        """
        機能: 買い往復がAsk105からBid110で成立し、費用を二度だけ控除するか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = open_position()
        state.request("exit", 1, BASE + 2, 3, "逆交差")
        state.on_quote(BASE + 3, 4, 0, 110.0, 115.0, True)
        self.assertEqual([(fill["type"], fill["price"]) for fill in state.fills], [("LongN", 105), ("LongR", 110)])
        self.assertEqual(state.trades[0]["純損益円"], 46)
        self.assertEqual(state.cash, 46)
        self.assertIsNone(state.position)

    def test_売り新規はBidで売り玉返済はAsk(self) -> None:
        """
        機能: 売り往復がBid100からAsk95で成立するか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = open_position(-1)
        state.request("exit", -1, BASE + 2, 3, "逆交差")
        state.on_quote(BASE + 3, 4, 0, 90.0, 95.0, True)
        self.assertEqual([(fill["type"], fill["price"]) for fill in state.fills], [("ShortN", 100), ("ShortR", 95)])
        self.assertEqual(state.trades[0]["純損益円"], 46)

    def test_買いの保護価格を飛び越えたら不利なBidで返済する(self) -> None:
        """
        機能: 買い保護95への到達後、待機中に80へ飛んだ実気配を採用するか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = open_position()
        self.assertEqual(state.position["stop"], 95)
        state.on_quote(BASE + 10, 3, 0, 85.0, 90.0, True)
        self.assertEqual(len(state.fills), 1)
        self.assertEqual(state.pending["reason"], "保護発動")
        state.on_quote(BASE + 11, 4, 0, 80.0, 85.0, True)
        self.assertEqual(state.fills[-1]["price"], 80)
        self.assertEqual(state.trades[0]["純損益円"], -254)

    def test_売りの保護価格を飛び越えたら不利なAskで返済する(self) -> None:
        """
        機能: 売り保護110を越え、140のAskで返済する損失を確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = open_position(-1)
        self.assertEqual(state.position["stop"], 110)
        state.on_quote(BASE + 10, 3, 0, 125.0, 130.0, True)
        state.on_quote(BASE + 11, 4, 0, 135.0, 140.0, True)
        self.assertEqual(state.fills[-1]["price"], 140)
        self.assertEqual(state.trades[0]["純損益円"], -404)

    def test_期限到達で返済を要求し次時計で返済する(self) -> None:
        """
        機能: シグナルがなくても期限返済が優先され、同時計では約定しないか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = open_position()
        state.on_quote(BASE + 60, 3, 0, 100.0, 105.0, True)
        self.assertEqual(state.pending["reason"], "期限返済")
        self.assertEqual(len(state.fills), 1)
        state.on_quote(BASE + 61, 4, 0, 100.0, 105.0, True)
        self.assertEqual(state.trades[0]["返済理由"], "期限返済")
        self.assertIsNone(state.position)

    def test_返済板がなければ未解消を残し終端で架空返済しない(self) -> None:
        """
        機能: 返済要求後に正常板がなくても建玉を消さず、終端の架空約定を防ぐ。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = open_position()
        state.on_quote(BASE + 60, 3, 0, None, None, False)
        state.on_quote(BASE + 61, 4, 0, None, None, False)
        state.on_quote(BASE + 90, 5, 0, 100.0, 105.0, True)
        self.assertIsNotNone(state.position)
        self.assertEqual(state.pending["kind"], "exit")
        self.assertEqual(state.trades, [])
        self.assertEqual(len(state.fills), 1)

    def test_返済した足では再新規を認めない(self) -> None:
        """
        機能: 一度返済した5分区間の再新規を止め、次の区間だけ認めるか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = open_position()
        state.request("exit", 1, BASE + 2, 3, "逆交差")
        state.on_quote(BASE + 3, 4, 4, 100.0, 105.0, True)
        state.on_signal(signal(-1), BASE + 4, 5, 4)
        self.assertIsNone(state.pending)
        state.on_signal(signal(-1), BASE + 5, 6, 5)
        self.assertEqual(state.pending["kind"], "entry")
        self.assertEqual(state.pending["side"], -1)

    def test_不正板では待機し正常板の最初で約定する(self) -> None:
        """
        機能: 交差・欠損等を表すvalid=falseの板では約定を作らないか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = strategy()
        state.on_signal(signal(), BASE, 1, 0)
        state.on_quote(BASE + 1, 2, 0, 110.0, 105.0, False)
        self.assertEqual(state.fills, [])
        state.on_quote(BASE + 2, 3, 0, 100.0, 105.0, True)
        self.assertEqual(state.fills[0]["source_line"], 3)

    def test_新規要求は30秒を過ぎると取消しになる(self) -> None:
        """
        機能: 古い入口を31秒後の有利な板で成立させないか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = strategy()
        state.on_signal(signal(), BASE, 1, 0)
        state.on_quote(BASE + 31, 2, 0, 100.0, 105.0, True)
        self.assertIsNone(state.pending)
        self.assertEqual(state.fills, [])
        self.assertEqual(state.cancellations, 1)

    def test_失効した新規要求が新しい交差を妨げない(self) -> None:
        """
        機能: 板の再開前に新交差が来ても旧要求を先に失効し、新要求から1秒待つか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = strategy()
        state.on_signal(signal(), BASE, 1, 0)
        state.on_signal(signal(), BASE + 31, 2, 1)
        self.assertEqual(state.cancellations, 1)
        self.assertIsNotNone(state.pending)
        self.assertEqual(state.pending["time"], BASE + 31)
        self.assertEqual(state.pending["line"], 2)
        self.assertEqual(len(state.decisions), 2)
        state.on_quote(BASE + 31, 3, 1, 100.0, 105.0, True)
        self.assertEqual(state.fills, [])
        state.on_quote(BASE + 32, 4, 1, 100.0, 105.0, True)
        self.assertEqual(state.fills[0]["source_line"], 4)
        self.assertEqual(state.position["signal_time"], BASE + 31)

    def test_反対交差は未約定新規を取消し新条件を評価する(self) -> None:
        """
        機能: 有効期間内の買い待機を反対交差で取消し、方向条件を再評価して売りを判定する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        for method, accepted in (("MACDのみ", True), ("方向条件", False)):
            with self.subTest(手法=method):
                state = strategy()
                state.method = method
                state.on_signal(signal(), BASE, 1, 0)
                reverse = signal(-1)
                reverse["trend_direction"] = 1
                state.on_signal(reverse, BASE + 10, 2, 1)
                self.assertEqual(state.cancellations, 1)
                if accepted:
                    self.assertEqual(state.pending["side"], -1)
                    self.assertEqual(state.pending["time"], BASE + 10)
                    state.on_quote(BASE + 10, 3, 1, 100.0, 105.0, True)
                    self.assertEqual(state.fills, [])
                    state.on_quote(BASE + 11, 4, 1, 100.0, 105.0, True)
                    self.assertEqual(state.fills[0]["type"], "ShortN")
                else:
                    self.assertIsNone(state.pending)
                    state.on_quote(BASE + 11, 3, 1, 100.0, 105.0, True)
                    self.assertEqual(state.fills, [])

    def test_新規停止時刻の要求と待機注文を止める(self) -> None:
        """
        機能: 新規停止と同時のシグナル・未約定新規をどちらも止めるか確認する。
        引数: self (約定の検証) はテスト状態。
        返り値: None。
        """
        state = strategy()
        state.on_signal(signal(), BASE + 50, 1, 0)
        self.assertIsNone(state.pending)
        state.on_signal(signal(), BASE + 49, 2, 0)
        state.on_quote(BASE + 50, 3, 0, 100.0, 105.0, True)
        self.assertEqual(state.fills, [])
        self.assertEqual(state.cancellations, 1)


# ----------------------------------------
# 場をまたぐ資産系列と、未解消を含む会計集計の検証

class 会計集計の検証(unittest.TestCase):
    """局所ドローダウンの過大合算と未完結成績の誤表示を防ぐ。"""

    def test_二場の資産系列から総期間DDを検算する(self) -> None:
        """
        機能: 最安値が最高値より前にある場を連結し、局所DDを単純加算しないか確認する。
        引数: self (会計集計の検証) はテスト状態。
        返り値: None。
        """
        # 第1場は0→100→80。第2場は局所0→−30→50→−10→20。
        # 全体は0→100→80→50→130→70→100となり、130から70への60が最大。
        sessions = [
            {"取引数": 1, "純損益円": 80, "最大資産円": 100, "最小資産円": 0,
             "含み込み最大DD円": 20, "終了建玉": 0, "終了未約定": 0},
            {"取引数": 1, "純損益円": 20, "最大資産円": 50, "最小資産円": -30,
             "含み込み最大DD円": 60, "終了建玉": 0, "終了未約定": 0},
        ]
        trades = [{"純損益円": profit, "値幅損益円": profit, "手数料円": 0,
                   "費用増純損益円": profit, "返済理由": "逆交差"} for profit in (80, 20)]
        result = MODULE.summary(trades, sessions)
        self.assertEqual(result["含み込み最大DD円"], 60)
        self.assertEqual(result["純損益円"], 100)
        self.assertEqual(result["現金会計合計円"], 100)
        self.assertEqual(result["結果状態"], "完結")

        # 同じ第1場の後、局所0→−30→10→−20→0なら、前場高値100から50への50が最大。
        sessions[1] = {"取引数": 1, "純損益円": 0, "最大資産円": 10, "最小資産円": -30,
                       "含み込み最大DD円": 30, "終了建玉": 0, "終了未約定": 0}
        trades[1] = {"純損益円": 0, "値幅損益円": 0, "手数料円": 0,
                     "費用増純損益円": 0, "返済理由": "逆交差"}
        result = MODULE.summary(trades, sessions)
        self.assertEqual(result["含み込み最大DD円"], 50)
        self.assertEqual(result["純損益円"], 80)

    def test_未解消建玉は全体純損益を欠損にし現金を保持する(self) -> None:
        """
        機能: 完結利益46円と次の建玉の新規費用2円を区別し、未完結成績を成功表示しない。
        引数: self (会計集計の検証) はテスト状態。
        返り値: None。
        """
        state = open_position()
        state.request("exit", 1, BASE + 2, 3, "逆交差")
        state.on_quote(BASE + 3, 4, 0, 110.0, 115.0, True)
        state.on_signal(signal(), BASE + 4, 5, 1)
        state.on_quote(BASE + 5, 6, 1, 100.0, 105.0, True)
        self.assertEqual(state.cash, 44)
        self.assertIsNotNone(state.position)
        trades = [dict(trade, 費用増純損益円=trade["純損益円"]) for trade in state.trades]
        sessions = [{"取引数": len(trades), "純損益円": state.cash,
                     "最大資産円": state.peak, "最小資産円": state.minimum,
                     "含み込み最大DD円": state.drawdown,
                     "終了建玉": 1, "終了未約定": 0}]
        result = MODULE.summary(trades, sessions)
        self.assertIsNone(result["純損益円"])
        self.assertIsNone(result["平均場損益円"])
        self.assertEqual(result["完結取引純損益円"], 46)
        self.assertEqual(result["現金会計合計円"], 44)
        self.assertEqual(result["未解消場数"], 1)
        self.assertEqual(result["結果状態"], "不完全・持越し制約違反")


# ----------------------------------------
# 小さな合成JSONLによる原板経路と指標リセットの検証

class 原板再生の検証(unittest.TestCase):
    """巨大ファイルや外部データを使わず、欠枠と品質判定を確認する。"""

    def test_連続グリッドに欠枠があると指標を再初期化する(self) -> None:
        """
        機能: 過去に初期化済みでも5分欠枠後の足を有効指標として利用しないか確認する。
        引数: self (原板再生の検証) はテスト状態。
        返り値: None。
        """
        config = json.loads((HERE / "条件.json").read_text(encoding="utf-8"))
        bank = MODULE.Indicators()
        for index in range(61):
            previous = bank.update(bar(100 + index))
        self.assertTrue(previous["ready"])
        start, _, _, _ = MODULE.session_times("2026-10-01_Day")
        rows = [raw_row(start + timedelta(minutes=5 * index), 200 + 5 * index)
                for index in range(83) if index != 1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            _, quality, bars, code = MODULE.process_session(path, "NK225", "2026-10-01_Day", bank, "合成限月", config)
        self.assertEqual(code, "合成限月")
        self.assertEqual(quality["足欠損数"], 1)
        self.assertEqual(quality["指標リセット"], 1)
        self.assertTrue(bars[0]["指標有効"])
        self.assertEqual(bars[1]["index"], 2)
        self.assertFalse(bars[1]["指標有効"])

    def test_無数量板と場外時計と後退時計を約定対象にしない(self) -> None:
        """
        機能: 原板経路が数量不足・場外時計・後退時計を品質件数へ分離するか確認する。
        引数: self (原板再生の検証) はテスト状態。
        返り値: None。
        """
        config = json.loads((HERE / "条件.json").read_text(encoding="utf-8"))
        start, _, _, _ = MODULE.session_times("2026-10-01_Day")
        rows = [raw_row(start - timedelta(seconds=1), 100),
                raw_row(start, 100), raw_row(start + timedelta(seconds=2), 100),
                raw_row(start + timedelta(seconds=1), 100)]
        rows[2]["Buy1"]["Qty"] = 0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            states, quality, _, _ = MODULE.process_session(path, "NK225", "2026-10-01_Day", MODULE.Indicators(), "合成限月", config)
        self.assertEqual(quality["場外時計"], 1)
        self.assertEqual(quality["時計後退"], 1)
        self.assertEqual(quality["不正板"], 1)
        self.assertTrue(all(not state.fills for state in states))


if __name__ == "__main__":
    unittest.main(verbosity=2)
