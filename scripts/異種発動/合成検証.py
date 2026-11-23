"""00021の指標銀行・異種発動・ADX選択・native不要追尾を人工系列で検査する。"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00021_BBとMACDとストキャスの発動切替"
WORK = ROOT/"work/異種発動"
SESSION = "2026-11-04_Day"


def load(path: Path, name: str) -> object:
    """対象APIをコマンド行実行せず読み込む。

    引数: path (Path) はコード、name (str) はmodule識別名。
    返り値: object はmodule。原板や市場結果を読み取らない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


F = load(HERE/"指標.py", "異種発動合成の指標")
I = load(HERE/"入口.py", "異種発動合成の入口")
O = load(HERE/"運用.py", "異種発動合成の運用")


def config() -> dict:
    """固定予定の閾値と運用条件のコピーを返す。

    引数: なし。
    返り値: dict は21条件。保存前は人工条件だけを作り最終proofには使わない。
    """
    path = STUDY/"条件.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    previous = json.loads((ROOT/"study/00020_テクニカル局面による順行反転の切替/条件.json").read_text(encoding="utf-8"))
    return {**previous, "時間足分": [1, 3, 5], "戦略": list(I.POLICIES), "発動条件": deepcopy(I.RULES), "出口": [{"出口ID": "X0"}]}


def frame(index: int, minutes: int = 1, **updates: object) -> dict:
    """足の形と新旧指標の人工値を作る。

    引数: index/minutes (int) は番号/尺度、updates (object) は上書き。
    返り値: dict は公開足。不要なRSI/EMA/VWAPは準備しない。
    """
    start = 3600+index*minutes*60
    value = {"index": index, "minutes": minutes, "start": start, "end": start+minutes*60,
        "confirm": start+minutes*60, "confirm_line": 100+index, "publish": True, "missing": 0,
        "open": 1000, "high": 1020, "low": 980, "close": 1005, "atr": 10,
        "bb_mean": 1000., "bb_sd": 10., "bandwidth": .04,
        "macd": None, "macd_signal": None, "macd_hist": 0., "stoch_k": 50., "stoch_d": None,
        "rsi": None, "ema10": None, "ema20": None, "ema20_previous": None}
    value.update(updates)
    return value


def upper(adx: float | None = 25, side: int = 1, **updates: object) -> dict:
    """EMAを持たない公開15分ADX/DI足を作る。

    引数: adx (float|None) は強さ、side (int) はDI向き、updates (object) は上書き。
    返り値: dict は上位人工足。
    """
    value = frame(0, 15, start=2700, end=3600, confirm=3600, confirm_line=50,
        adx=adx, plus_di=30 if side == 1 else 10, minus_di=10 if side == 1 else 30)
    value.update(updates)
    return value


def generate(family: str = "T1", side: int = 1, size: int = 1,
             changes: dict | None = None, higher: list[dict] | None = None,
             cutoff: float | None = None, deadline: float | None = None) -> tuple[dict, dict]:
    """二つの良好な発動の三公開足を作り生成APIへ渡す。

    引数: family/side/size (str/int/int) は型/向き/幅、changes (dict|None) は足番号別上書き、
    higher (list[dict]|None) は上位、cutoff/deadline (float|None) は停止/期限。
    返り値: tuple[dict,dict] は四入口集合/全shadow品質。
    """
    rows = [frame(n, size) for n in range(3)]
    for n, row in enumerate(rows):
        row["close"] = 1000+5*side if family == "T1" else 1000-5*side
        row["macd_hist"] = [0., 0., float(side)][n] if family == "T1" else 0.
        row["bandwidth"] = .04 if n < 2 or family == "R1" else .041
        row["stoch_k"] = ([10., 20., 21.][n] if side == 1 else [90., 80., 79.][n]) if family == "R1" else 50.
        row.update((changes or {}).get(n, {}))
    h = [upper(25 if family == "T1" else 20, side)] if higher is None else higher
    return I.generate(rows, h, SESSION, rows[-1]["confirm"]+3600 if cutoff is None else cutoff,
        rows[-1]["confirm"]+7200 if deadline is None else deadline, config())


def quote(now: float, line: int, bid: float = 1000, ask: float | None = None, valid: bool = True) -> object:
    """人工の正常/不正BBOを作る。

    引数: now/line (float/int) は時計/原行、bid/ask (float|None) は気配、valid (bool) は正常性。
    返り値: object は運用APIへのイベント。
    """
    return SimpleNamespace(now=now, line=line, bid=bid, ask=bid+5 if ask is None else ask,
                           last=bid, valid=valid, volume=math.nan, volume_time=math.nan)


def request(side: int = 1, role: str = "順行", **updates: object) -> dict:
    """nativeを一切持たない人工要求を作る。

    引数: side/role (int/str) は売買/入口役割、updates (object) は上書き。
    返り値: dict は21型の純入口。
    """
    row = {"場": SESSION, "入口ID": "1分_A0", "イベントID": "人工入口", "side": side,
           "方向": "買い" if side == 1 else "売り", "役割": role, "要求時計秒": 0., "要求原板行": 1,
           "確認遅延秒": 0, "atr": 100., "high": 1050., "low": 950., "close": 1000., "bb_mean": 1000.}
    row.update(updates)
    return row


def replay(quotes: list, signals: list[dict] | None = None, frames: list[dict] | None = None) -> tuple[object, dict]:
    """人工の単一注文経路を実新規から返済まで再生する。

    引数: quotes (list) は気配、signals/frames (list[dict]|None) は要求/足。
    返り値: tuple[object,dict] は状態/会計。省略時に期限後の正常板を追加する。
    """
    values = list(quotes)
    if values[-1].now < 91:
        last = values[-1]
        values += [quote(91, last.line+1, last.bid, last.ask), quote(92, last.line+2, last.bid, last.ask)]
    return O.replay(values, [request()] if signals is None else signals, frames or [], SESSION,
                    "人工21", config()["運用"], {"出口ID": "X0"}, "混合", (0, 100, 80, 90))


# ----------------------------------------
# 数式の既知値と必要本数を固定し、入口を決める前に指標系列を確認する。

class 指標銀行検証(unittest.TestCase):
    """算術seed・母分散・K/Dの別助走と状態持続を検査する。"""

    def test_MACD26signal34H三点36本の必要本数(self) -> None:
        """線形終値は初MACD7/初signal7/H0を厳密な既知例にする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bank = F.Indicators()
        rows = [bank.update({"close": n, "high": n+1, "low": n-1}) for n in range(1, 37)]
        self.assertTrue(all(r["macd"] is None for r in rows[:25]))
        self.assertEqual(rows[25]["macd"], 7)
        self.assertTrue(all(r["macd_signal"] is None for r in rows[:33]))
        self.assertEqual(rows[33]["macd_signal"], 7)
        self.assertEqual([r["macd_hist"] for r in rows[33:]], [0, 0, 0])
        self.assertIsNone(rows[13]["atr"])
        self.assertEqual(rows[14]["atr"], 2)

    def test_MACD線形後の十点跳躍と鏡像の既知値(self) -> None:
        """EMAを最初値seedへ変えると一致しない37本目を検査する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            bank = F.Indicators()
            for n in range(1, 37):
                value = 1000+side*n
                bank.update({"close": value, "high": value+1, "low": value-1})
            row = bank.update({"close": 1000+side*47, "high": 1001+side*47, "low": 999+side*47})
            self.assertAlmostEqual(row["macd_hist"], side*.6381766381766382, places=11)

    def test_BBは20本母標準偏差と中心で正規化した幅(self) -> None:
        """標本標準偏差や絶対幅と混同しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bank = F.Indicators()
        rows = [bank.update({"close": n, "high": n+1, "low": n-1}) for n in range(1, 21)]
        self.assertIsNone(rows[18]["bb_mean"])
        self.assertEqual(rows[19]["bb_mean"], 10.5)
        self.assertAlmostEqual(rows[19]["bb_sd"], math.sqrt(33.25))
        self.assertAlmostEqual(rows[19]["bandwidth"], 4*math.sqrt(33.25)/10.5)
        bank = F.Indicators()
        for _ in range(20):
            row = bank.update({"close": 1000, "high": 1001, "low": 999})
        self.assertEqual(row["bb_sd"], 0)
        self.assertIsNone(row["bandwidth"])

    def test_rawK14slowK16slowD18と算術三点平滑(self) -> None:
        """KとDにEMAを使わず現rawを含むSMA3を確認する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bank = F.Indicators()
        rows = [bank.update({"close": 105, "high": 110, "low": 100}) for _ in range(13)]
        rows += [bank.update({"close": n, "high": 110, "low": 100}) for n in range(101, 106)]
        self.assertTrue(all(r["stoch_raw"] is None for r in rows[:13]))
        self.assertEqual([r["stoch_raw"] for r in rows[13:]], [10, 20, 30, 40, 50])
        self.assertIsNone(rows[14]["stoch_k"])
        self.assertEqual([r["stoch_k"] for r in rows[15:]], [20, 30, 40])
        self.assertIsNone(rows[16]["stoch_d"])
        self.assertEqual(rows[17]["stoch_d"], 30)

    def test_range零は平滑だけ切り三rawと三Kで再種(self) -> None:
        """OHLC14を保持しK/D欠測を0や50へ補わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bank = F.Indicators()
        for _ in range(50):
            bank.update({"close": 105, "high": 110, "low": 100})
        for _ in range(14):
            row = bank.update({"close": 100, "high": 100, "low": 100})
        self.assertEqual(len(bank.ohlc14), 14)
        self.assertIsNone(row["stoch_raw"])
        self.assertIsNone(row["stoch_k"])
        self.assertIsNone(row["stoch_d"])
        self.assertIsNotNone(row["macd_hist"])
        rows = [bank.update({"close": 105, "high": 110, "low": 100}) for _ in range(5)]
        self.assertEqual([r["stoch_k"] for r in rows], [None, None, 50, 50, 50])
        self.assertEqual([r["stoch_d"] for r in rows], [None, None, None, None, 50])

    def test_missing更新前に全銀行resetし非公開足も更新(self) -> None:
        """公開可否の入口制約と完全幅足の銀行更新を分ける。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bank = F.Indicators()
        rows = [frame(n, close=1000+n, high=1001+n, low=999+n) for n in range(40)]
        F.features(rows, bank, rows[0]["start"])
        reset = F.features([frame(40, close=1050, missing=1, publish=False)], bank, rows[0]["start"])[0]
        for key in ("ema10", "ema20", "atr", "macd", "macd_signal", "macd_hist", "stoch_k", "stoch_d"):
            self.assertIsNone(reset[key])
        self.assertEqual(len(bank.closes), 1)
        self.assertEqual(len(bank.ohlc14), 1)
        self.assertEqual(bank.fast.count, 1)

    def test_同一銀行は場間持続し終端非公開足も次場へ反映(self) -> None:
        """場開始だけで算術seedへ戻さず欠枠resetとは別にする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bank = F.Indicators()
        first = [frame(n, close=n+1, high=n+2, low=n) for n in range(20)]
        first[-1]["publish"] = False
        F.features(first, bank, first[0]["start"])
        second = [frame(n, close=n+21, high=n+22, low=n+20) for n in range(14)]
        rows = F.features(second, bank, second[0]["start"])
        self.assertEqual(rows[5]["macd"], 7)
        self.assertEqual(rows[13]["macd_signal"], 7)
        self.assertEqual(rows[13]["macd_hist"], 0)


# ----------------------------------------
# 新発動の符号とstrict境界を独立に検査する。

class 発動検証(unittest.TestCase):
    """T1/R1の鏡像・等号・共通準備と上位選択を検査する。"""

    def test_二系統三尺度両sideがEMA等なしで発動する(self) -> None:
        """旧Qやnative/RSI/EMAのgateを新発動へ持ち込まない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for family, control, role in (("T1", "T0", "順行"), ("R1", "R0", "反転")):
            for size in (1, 3, 5):
                for side in (1, -1):
                    groups, quality = generate(family, side, size)
                    for policy in (control, "A0", "S1"):
                        self.assertEqual(len(groups[f"{size}分_{policy}"]), 1)
                        row = groups[f"{size}分_{policy}"][0]
                        self.assertEqual((row["役割"], row["side"]), (role, side))
                        self.assertIsNone(row["stoch_d"])
                        self.assertNotIn("配信VWAP", row)
                    self.assertEqual(len(quality["全Q発動記録"]), 1)

    def test_T1はH水準でなく差分の非正から正へ転じる(self) -> None:
        """前差0を含め現差0を除外し既に加速中の足へ遅く乗らない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for hist, expected in (([0, 0, 1], True), ([0, -1, 0], True), ([-3, -3, -2], True),
                                   ([0, 1, 2], False), ([0, -1, -1], False)):
                groups, _ = generate("T1", side, changes={n: {"macd_hist": side*h} for n, h in enumerate(hist)})
                self.assertEqual(bool(groups["1分_T0"]), expected)

    def test_T1中心strictと正規化帯幅strict増加(self) -> None:
        """中心等号と同幅を除き帯外という追加条件は付けない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for changes, expected in (({2: {"close": 1000}}, False), ({2: {"bandwidth": .04}}, False),
                                  ({2: {"bandwidth": .039}}, False), ({2: {"close": 1100}}, True)):
            groups, _ = generate(changes=changes)
            self.assertEqual(bool(groups["1分_T0"]), expected)

    def test_R1は20と80の前等号を含み現等号を除く(self) -> None:
        """SlowK領域復帰をK/D交差や帯外内復帰へ置き換えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for before, now, expected in ((20, 20, False), (20, 20.001, True), (20.001, 21, False), (0, 21, True)):
                values = [before, now] if side == 1 else [100-before, 100-now]
                groups, _ = generate("R1", side, changes={1: {"stoch_k": values[0]}, 2: {"stoch_k": values[1]}})
                self.assertEqual(bool(groups["1分_R0"]), expected)
            groups, _ = generate("R1", side, changes={2: {"close": 1000}})
            self.assertEqual(groups["1分_R0"], [])
            groups, _ = generate("R1", side, changes={2: {"close": 1000-100*side}})
            self.assertEqual(len(groups["1分_R0"]), 1)

    def test_共通Mは必要単点だけでDや他指標は不問(self) -> None:
        """H/K/BB正幅/ATRを全戦略で揃え診断Dをgateへ加えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        self.assertTrue(I.local_ready(frame(0, stoch_d=None, rsi=None, ema20=None)))
        for key in ("bb_mean", "bb_sd", "atr", "macd_hist", "stoch_k", "bandwidth"):
            for value in (None, float("nan"), float("inf")):
                self.assertFalse(I.local_ready(frame(0, **{key: value})))
        for key in ("bb_mean", "bb_sd", "atr"):
            self.assertFalse(I.local_ready(frame(0, **{key: 0})))
        for key in ("macd_hist", "stoch_k", "bb_sd", "atr"):
            groups, quality = generate(changes={1: {key: None}})
            self.assertTrue(all(not rows for rows in groups.values()))
            self.assertFalse(quality["複合context記録"][-1]["共通M準備"])

    def test_三公開足の最初成立と場頭reset(self) -> None:
        """前場の比較履歴や将来足を使わず当前三本から発動する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, quality = generate()
        self.assertEqual([r["共通M準備"] for r in quality["複合context記録"]], [False, False, True])
        frames = [frame(n, macd_hist=0 if n < 2 else 1, bandwidth=.04 if n < 2 else .041) for n in range(3)]
        next_groups, next_quality = I.generate(frames[-1:], [upper()], "2026-11-04_Night", 10000, 20000, config())
        self.assertEqual(next_groups["1分_T0"], [])
        self.assertEqual(next_quality["複合context記録"][0]["局所三足番号"], [2])

    def test_欠枠非公開番号飛越で比較窓を再開始する(self) -> None:
        """missing現在足はreset後一本目、非公開は比較窓へ積まない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for changes, expected in (({2: {"missing": 1}}, [2]), ({2: {"publish": False}}, []),
                                  ({2: {"index": 4}}, [4])):
            groups, quality = generate(changes=changes)
            self.assertTrue(all(not rows for rows in groups.values()))
            self.assertEqual(quality["複合context記録"][-1]["局所三足番号"], expected)

    def test_現在だけ遅延30秒まで許可し過去二本の遅延を加えない(self) -> None:
        """遅延済み足が既知なら局所H比較へ残し当前発動時刻を制限する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for delay, expected in ((30, True), (30.001, False)):
            groups, _ = generate(changes={2: {"confirm": frame(2)["end"]+delay}})
            self.assertEqual(bool(groups["1分_T0"]), expected)
        groups, quality = generate(changes={0: {"confirm": frame(0)["end"]+31}, 1: {"confirm": frame(1)["end"]+31}})
        self.assertEqual(len(groups["1分_T0"]), 1)
        self.assertTrue(quality["複合context記録"][-1]["共通M準備"])

    def test_残60分等号と新規停止時刻strict(self) -> None:
        """未来ラベルに依存せず要求時点の停止/残時間を判定する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        now = frame(2)["confirm"]
        for deadline, cutoff, expected in ((now+3600, now+1, True), (now+3599.999, now+1, False), (now+7200, now, False)):
            groups, _ = generate(deadline=deadline, cutoff=cutoff)
            self.assertEqual(bool(groups["1分_T0"]), expected)

    def test_ADX20range25trendとDI同値waitをEMAなしで分類(self) -> None:
        """ADXだけで方向を与えず未準備と既知WAITを区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for adx, di_equal, expected in ((20, False, "レンジ"), (20, True, "レンジ"),
                (20.001, False, "待機"), (24.999, False, "待機"), (25, False, "トレンド"), (25, True, "待機"), (None, False, "未準備")):
            row = upper(adx, **({"plus_di": 20, "minus_di": 20} if di_equal else {}))
            states, _ = I.classify([row], SESSION, config())
            self.assertEqual(states[0]["局面"], expected)
        states, _ = I.classify([upper(25, -1)], SESSION, config())
        self.assertEqual(states[0]["DI方向"], -1)

    def test_四戦略共通Mと局面選択の全向き(self) -> None:
        """固定対照と混合は同じ準備を待ちS1だけ方向と系統を選ぶ。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        possibilities = [(q, side) for q in ("T1", "R1") for side in (1, -1)]
        for state, direction in (("トレンド", 1), ("トレンド", -1), ("レンジ", 0), ("待機", 0)):
            context = {"共通M準備": True, "局面": state, "DI方向": direction}
            expected = {"T0": {("T1", 1), ("T1", -1)}, "R0": {("R1", 1), ("R1", -1)}, "A0": set(possibilities),
                "S1": {("T1", direction)} if state == "トレンド" else {("R1", 1), ("R1", -1)} if state == "レンジ" else set()}
            for policy in I.POLICIES:
                self.assertEqual({(q, side) for q, side in possibilities if I.decision(policy, q, side, context)[0]}, expected[policy])
                self.assertTrue(all(not I.decision(policy, q, side, {**context, "共通M準備": False})[0] for q, side in possibilities))

    def test_上位は公開同秒原行とendの両上限を満たす(self) -> None:
        """EMAを用いず未準備の最新上位から古正常へfallbackしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(2)
        for line, expected in ((current["confirm_line"]+1, False), (current["confirm_line"], True)):
            h = [upper(confirm=current["confirm"], end=current["end"], confirm_line=line)]
            groups, _ = generate(higher=h)
            self.assertEqual(bool(groups["1分_T0"]), expected)
        h = [upper(confirm=current["confirm"]+1, end=current["end"]+1)]
        groups, _ = generate(higher=h, changes={2: {"confirm": current["confirm"]+2}})
        self.assertEqual(groups["1分_T0"], [])
        h = [upper(), upper(index=1, start=3600, end=current["end"], confirm=current["confirm"], confirm_line=100, adx=None)]
        groups, quality = generate(higher=h)
        self.assertEqual(groups["1分_T0"], [])
        self.assertFalse(quality["複合context記録"][-1]["上位準備済"])

    def test_公開前時刻と尺度混在と番号重複を拒否(self) -> None:
        """純APIでも足終了前公開を受け入れて先読みを起こさない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for changes in ({2: {"confirm": frame(2)["end"]-1}}, {2: {"minutes": 3}}, {2: {"index": 1}}):
            with self.assertRaises(ValueError):
                generate(changes=changes)
        for h in ([upper(minutes=5)], [upper(), upper()], [upper(confirm=3599)]):
            with self.assertRaises(ValueError):
                I.classify(h, SESSION, config())

    def test_未来ラベルと未来足を変えて過去発動不変(self) -> None:
        """後日の成功をshadowの採否へ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        a, _ = generate(changes={2: {"未来ラベル": "順行先着", "将来損益": 99999}})
        b, _ = generate(changes={2: {"未来ラベル": "逆行先着", "将来損益": -99999}})
        for key in a:
            self.assertEqual([(r["要求時計秒"], r["side"], r["複合判定"]) for r in a[key]],
                             [(r["要求時計秒"], r["side"], r["複合判定"]) for r in b[key]])
        context = {"共通M準備": True, "局面": "レンジ", "DI方向": 0}
        self.assertEqual(I.decision("S1", "R1", 1, {**context, "将来損益": 99999}), I.decision("S1", "R1", 1, {**context, "将来損益": -99999}))

    def test_同時複数候補は同方向もshadowを残して全見送り(self) -> None:
        """混合A0の先頭だけ発注せず対照単独側の選択とは分ける。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for sides in ((1, 1), (1, -1)):
            def selected(family: str, side: int, current: dict, previous: dict, older: dict) -> bool:
                """人工の競合二件を検査入口へ返す。

                引数: family (str) は系統、side (int) は向き、current/previous/older (dict) は三足。
                返り値: bool は三足目の指定候補だけ真。
                """
                return side == (sides[0] if family == "T1" else sides[1])
            with patch.object(I, "trigger", side_effect=selected):
                groups, quality = generate()
            self.assertEqual(groups["1分_A0"], [])
            self.assertEqual(len(quality["全Q発動記録"]), 2)
            self.assertTrue(all(r["戦略判定"]["A0"]["同時競合"] for r in quality["全Q発動記録"]))
            self.assertEqual(len(groups["1分_T0"]), 1)
            self.assertEqual(len(groups["1分_R0"]), 1)


# ----------------------------------------
# 新しい入口に必要のないnativeを補わず、一建玉と必須追尾へ接続する。

class 保護運用検証(unittest.TestCase):
    """役割固定・新規と返済気配・待機・追尾・費用を検査する。"""

    def test_nativeなし両役割両sideで5pt起動と同値返済費用(self) -> None:
        """全新入口がnativefreeのまま往復し売買を符号対称に扱う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for role in ("順行", "反転"):
                quotes = [quote(0, 1), quote(1, 2), quote(2, 3, 1010 if side == 1 else 990),
                    quote(3, 4, 1005 if side == 1 else 995), quote(3, 5, 1005 if side == 1 else 995), quote(4, 6, 1005 if side == 1 else 995)]
                state, info = replay(quotes, [request(side, role)])
                t = state.trades[0]
                self.assertEqual(t["基準純損益円"], -22)
                self.assertEqual(t["入口役割"], role)
                self.assertEqual(t["返済理由"], "必須利益追尾")
                self.assertEqual((t["返済要求時計秒"], t["返済時計秒"]), (3, 4))
                self.assertFalse(t["通常出口使用"])
                self.assertTrue(t["起動後純赤字"])
                self.assertEqual(info["起動後純赤字取引数"], 1)

    def test_入口ATR距離切上げと買ceil売floor非緩和(self) -> None:
        """起動幅は5固定で距離だけATR由来とする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for atr, expected in ((.1, (5, 5)), (5, (5, 5)), (5.01, (5, 10)), (31, (5, 35))):
            self.assertEqual(O.trail_parameters(atr), expected)
        for side in (1, -1):
            signal = request(side, atr=31)
            state = O.切替状態(SESSION, "人工丸め", config()["運用"], {"出口ID": "X0"}, "混合", [signal], (0, 100, 80, 90))
            state.signal_group([signal])
            state.quote(1, 2, 1000, 1005)
            state.quote(2, 3, 1042 if side == 1 else 958, 1047 if side == 1 else 963)
            self.assertEqual(state.position["trail_stop"], 1010 if side == 1 else 995)
            state.quote(3, 4, 1035 if side == 1 else 965, 1040 if side == 1 else 970)
            self.assertEqual(state.position["trail_stop"], 1010 if side == 1 else 995)

    def test_前場峰と公開足高値は起動せず現在返済気配だけ使う(self) -> None:
        """新規前/未確定高値や局面変更だけで追尾や退出を作らない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        fake_bar = {**frame(0), "end": 2., "confirm": 2., "confirm_line": 3, "high": 9000, "局面": "レンジ", "DI方向": -1}
        state, _ = replay([quote(0, 1, 1200), quote(1, 2), quote(2, 3, 1009.999), quote(3, 4, 1000)], frames=[fake_bar])
        self.assertFalse(state.trades[0]["追尾起動"])
        self.assertEqual(state.trades[0]["返済理由"], "期限")

    def test_hard125TP250期限は追尾より先でpending中更新停止(self) -> None:
        """既pending後のMFE上昇を追尾へ遡及しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        cases = [([quote(0, 1), quote(1, 2), quote(2, 3, 1010), quote(3, 4, 880), quote(4, 5, 875)], "保護", True),
            ([quote(0, 1), quote(1, 2), quote(2, 3, 1255), quote(2.5, 4, 1300), quote(3, 5, 1300)], "利確", False),
            ([quote(0, 1), quote(1, 2), quote(2, 3, 1010), quote(90, 4, 1005), quote(91, 5, 1000)], "期限", True)]
        for quotes, reason, armed in cases:
            state, _ = replay(quotes)
            self.assertEqual(state.trades[0]["返済理由"], reason)
            self.assertEqual(state.trades[0]["追尾起動"], armed)
        state, _ = replay([quote(0, 1), quote(1, 2), quote(2, 3, 1010), quote(3, 4, 1005), quote(3.5, 5, 1200), quote(4, 6, 1200)])
        self.assertEqual(state.trades[0]["最終追尾価格"], 1005)
        self.assertEqual(state.trades[0]["返済理由"], "必須利益追尾")

    def test_保護の同値設定と実赤字約定を分離する(self) -> None:
        """不利gapを設定価格へ置き換えず返済BBOと往復費用を残す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay([quote(0, 1), quote(1, 2), quote(2, 3, 1010), quote(3, 4, 990), quote(4, 5, 985)])
        trade = state.trades[0]
        self.assertEqual((trade["最終追尾価格"], trade["返済価格"], trade["基準純損益円"]), (1005, 985, -222))
        self.assertTrue(any(r["動作"] == "起動済み純赤字約定" for r in state.normal_log))

    def test_建玉中抑止の別役割で実新規役割を上書きしない(self) -> None:
        """混合運用の役割は実際に約定した入口だけから決まる。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        signals = [request(), request(role="反転", イベントID="抑止反転", 要求時計秒=2, 要求原板行=3)]
        state, _ = replay([quote(0, 1), quote(1, 2), quote(2, 3), quote(3, 4)], signals)
        self.assertEqual(state.trades[0]["入口役割"], "順行")
        self.assertEqual(state.signals[1]["取扱"], "建玉中抑止")
        self.assertEqual(state.trades[0]["返済理由"], "期限")

    def test_同判断の同方向も両方向も全件見送り(self) -> None:
        """運用側でも曖昧な二候補の先頭だけを発注しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            state, info = replay([quote(0, 1), quote(1, 2)], [request(), request(side, "反転", イベントID="競合")])
            self.assertEqual(state.orders, [])
            self.assertEqual(info["同判断複数見送り数"], 2)

    def test_新規は一秒待機30秒有効で返済板なしは未解消(self) -> None:
        """同時計約定や30秒超の遅延新規を認めずEOF架空返済を作らない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for delay, expected in ((30, 1), (30.001, 0)):
            state, _ = replay([quote(0, 1), quote(0, 2), quote(delay, 3)])
            self.assertEqual(sum(f["type"].endswith("N") for f in state.fills), expected)
        state, info = O.replay([quote(0, 1), quote(1, 2), quote(2, 3, 1010), quote(3, 4, 1005)],
            [request()], [], SESSION, "未解消", config()["運用"], {"出口ID": "X0"}, "混合", (0, 100, 80, 90))
        self.assertEqual(state.trades, [])
        self.assertEqual(info["終了建玉"], 1)
        self.assertEqual(info["観測現金増減円"], -11)
        self.assertIsNone(info["確定対象純損益円"])


class 連携検証(unittest.TestCase):
    """指標から発動・追尾と固定候補/空場/準備モードを検査する。"""

    def test_12入口12X0と事前三分四資源と空足(self) -> None:
        """指標の準備不足場も全候補を0件として保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE/"検証.py", "異種発動合成のdriver")
        sources = driver.sources(config())
        self.assertEqual(len(sources), 12)
        self.assertEqual(len(config()["出口"]), 1)
        self.assertEqual(sum(r["時間足分"] == 3 for r in sources), 4)
        for size in (1, 3, 5):
            groups, quality = driver.generate_or_empty([], [], SESSION, size, 10000, 20000, config(), [])
            self.assertEqual(list(groups), [f"{size}分_{p}" for p in I.POLICIES])
            self.assertTrue(all(not rows for rows in groups.values()))
            self.assertEqual(quality["全Q発動記録"], [])

    def test_実生成signalをnativefree追尾会計まで接続(self) -> None:
        """BB/Hの発動に架空nativeを付け足さず追尾往復を完結する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, _ = generate()
        signals = groups["1分_S1"]
        self.assertNotIn("配信VWAP", signals[0])
        now = signals[0]["要求時計秒"]
        quotes = [quote(now, 102), quote(now+1, 103), quote(now+2, 104, 1010), quote(now+3, 105, 1005), quote(now+4, 106, 1005), quote(now+7201, 200, 1005)]
        state, _ = O.replay(quotes, signals, [], SESSION, "接続21", config()["運用"], {"出口ID": "X0"}, "混合", (now-100, now+7300, now+3600, now+7200))
        self.assertEqual(state.trades[0]["基準純損益円"], -22)
        self.assertEqual(state.trades[0]["入口役割"], "順行")
        self.assertIsNone(state.position)

    def test_実指標から36本目M準備と37本目H加速発動を連結(self) -> None:
        """手作りHでなく新指標銀行の算術seedから共通Mへ接続する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bars = [frame(n, close=n+1, high=n+2, low=n) for n in range(36)]
        bars.append(frame(36, close=47, high=48, low=46))
        features = F.features(bars, F.Indicators(), bars[0]["start"])
        groups, quality = I.generate(features, [upper()], SESSION, features[-1]["confirm"]+3600,
            features[-1]["confirm"]+7200, config())
        contexts = quality["複合context記録"]
        self.assertTrue(all(not r["共通M準備"] for r in contexts[:35]))
        self.assertTrue(contexts[35]["共通M準備"])
        self.assertEqual([r["index"] for r in groups["1分_T0"]], [36])
        self.assertAlmostEqual(groups["1分_T0"][0]["macd_hist"], .6381766381766382, places=11)

    def test_prepareモードは65人工場でもラベルと運用を呼ばない(self) -> None:
        """件数点検の分岐を人工台帳で通し禁止計算の呼出を失敗にする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE/"検証.py", "異種発動合成のprepare")
        with tempfile.TemporaryDirectory(prefix="異種発動合成_") as directory:
            base = Path(directory); study, work = base/"試行", base/"作業"
            study.mkdir()
            (study/"条件.json").write_text(json.dumps(config(), ensure_ascii=False), encoding="utf-8")
            source = base/"人工入力"; source.write_text("", encoding="utf-8")
            stat = source.stat()
            sessions = [f"{date(2026,9,21)+timedelta(days=n)}_{kind}" for n in range(20) for kind in ("Day", "Night")]
            sessions += [f"{date(2026,10,19)+timedelta(days=n)}_{kind}" for n in range(12) for kind in ("Day", "Night")]
            sessions += ["2026-11-04_Day"]
            manifest = {"source_root": str(base), "entries": [{"session": s, "symbol": "NK225", "source_path": source.name,
                "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns, "cache_path": "存在しない人工cache", "sha256_cache": "人工SHA", "in_session_contract_codes": ["人工限月"]} for s in sessions]}
            original = driver.W.read_json
            def read_json(path: Path) -> dict:
                """人工台帳だけを返し条件は一時ファイルから読む。

                引数: path (Path) は参照先。
                返り値: dict は人工manifestまたは条件。
                """
                return deepcopy(manifest) if path == driver.INPUT else original(path)
            forbidden = SimpleNamespace(replay=unittest.mock.Mock(side_effect=AssertionError("運用計算は禁止")))
            with patch.object(driver.W, "read_json", side_effect=read_json), patch.object(driver.O, "sha", return_value="人工SHA"), \
                    patch.object(driver.W.PREP, "read_events", return_value=[]), patch.object(driver.W.OLD, "気配経路", side_effect=AssertionError("先着計算は禁止")), \
                    patch.object(driver, "module", return_value=forbidden), patch.object(driver, "freeze", side_effect=AssertionError("固定は禁止")), redirect_stdout(io.StringIO()):
                result = driver.run(study, work, True)
            self.assertFalse(result["損益計算"])
            self.assertFalse(result["ラベル計算"])
            forbidden.replay.assert_not_called()
            self.assertTrue((work/"準備点検.json").exists())
            self.assertFalse((study/"結果.json").exists())
            self.assertFalse((work/"全運用詳細.jsonl.gz").exists())


# ----------------------------------------
# 最終通知までは途中proofだけを保存し、編集終了後は変更しない。

def main() -> None:
    """人工系列の合成を実行し編集終了と関係SHAを記録する。

    引数: なし。--finalは全編集終了時だけ指定する。
    返り値: None。失敗時は終了コード1。市場データは実行しない。
    """
    parser = argparse.ArgumentParser(description="異種発動と利益追尾の人工合成")
    parser.add_argument("--final", action="store_true", help="編集終了時だけ固定用proofを保存")
    args = parser.parse_args()
    targets = [Path(__file__), HERE/"指標.py", HERE/"入口.py", HERE/"運用.py"]
    targets += [p for p in (HERE/"検証.py", STUDY/"条件.json") if p.exists()]
    pins = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in targets}
    if args.final and len(targets) != 6:
        raise ValueError("関係6コード/条件が揃う前には固定不可")
    if args.final and (STUDY/"固定.json").exists():
        frozen = json.loads((STUDY/"固定.json").read_text(encoding="utf-8"))["ファイルSHA256"]
        if any(frozen.get(name) != sha for name, sha in pins.items()):
            raise ValueError("固定後の追加は別ファイルへ分離する")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    proof = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
        "合成編集終了": bool(args.final and result.wasSuccessful()), "ファイルSHA256": pins,
        "失敗": [{"検証": str(c), "内容": m} for c, m in result.failures],
        "エラー": [{"検証": str(c), "内容": m} for c, m in result.errors],
        "範囲": "人工OHLCの算術seed MACD26/Signal34/H三点36・母BB・rawK14/SlowK16/SlowD18と再種、欠枠/非公開/carry、異種発動のstrictと鏡像・同場共通M・ADXDI/公開原行選択・全shadow競合、native不要A5追尾/1秒BBO/費用・未解消・12固定候補。prepare65人工場でラベル/損益/固定の呼出禁止を確認。原板/市場損益は実行しない。",
        "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k: proof[k] for k in ("全件成功", "検証件数", "合成編集終了")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
