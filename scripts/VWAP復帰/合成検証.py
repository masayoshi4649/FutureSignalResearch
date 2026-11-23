"""00019の直接VWAP入口と通常線決済を人工価格/BBOで検証する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00019_VWAP復帰の入口と通常出口"
WORK = ROOT/"work/VWAP復帰"
JST = timezone(timedelta(hours=9))
START = datetime(2026, 11, 4, 8, 45, tzinfo=JST).timestamp()
SESSION = "2026-11-04_Day"
BOUNDS = (0.0, 100.0, 80.0, 90.0)


def load(path: Path, name: str) -> object:
    """対象APIをコマンド行実行せず読み込む。

    引数: path (Path) はコード、name (str) はmodule識別名。
    返り値: object はmodule。共有原板や保存成績は読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


I = load(HERE/"入口.py", "VWAP復帰合成の入口")
O = load(HERE/"運用.py", "VWAP復帰合成の運用")


def config() -> dict:
    """今回条件正本の独立コピーを返す。

    引数: なし。
    返り値: dict は00019条件。市場結果は読み取らない。
    """
    return json.loads((STUDY/"条件.json").read_text(encoding="utf-8"))


def frame(index: int, minutes: int = 1, **updates: object) -> dict:
    """下位の未使用指標をNoneにした公開価格足を作る。

    引数: index/minutes (int) は番号/足幅、updates (object) は人工上書き。
    返り値: dict はATRと価格を持つ人工足。
    """
    start = START+index*minutes*60
    value = {"index": index, "minutes": minutes, "start": start, "end": start+minutes*60,
             "confirm": start+minutes*60, "confirm_line": 100+index, "publish": True, "missing": 0,
             "open": 1000, "high": 1030, "low": 970, "close": 1000, "atr": 10,
             "ema20": None, "ema20_previous": None, "adx": None, "rsi": None, "bb_mean": None, "bb_sd": None}
    value.update(updates)
    return value


def reference(native: float = 1000, third: float = 990, **updates: object) -> dict:
    """固定18参照schemaの人工値を作る。

    引数: native/third (float) は現/三足前値、updates (object) は上書き。
    返り値: dict はN4済み参照。差分Dは今回使わない。
    """
    value = {"配信VWAP": native, "配信3足前VWAP": third, "当場差分VWAP": None, "差分3足前VWAP": None,
             "補助epoch": 0, "identity": {}, "native有効": True, "差分有効": False,
             "N共通準備": True, "D共通準備": False, "補助参照": {"line": 1}, "N除外理由": [], "D除外理由": []}
    value.update(updates)
    return value


def generate(family: str = "Q1", side: int = 1, minutes: int = 1,
             previous: dict | None = None, current: dict | None = None,
             prior_reference: dict | None = None, current_reference: dict | None = None,
             higher: list[dict] | None = None, cutoff: float | None = None,
             deadline: float | None = None) -> tuple[dict, dict]:
    """良好なQ1/Q2の人工対を基準として公開入口を作る。

    引数: family/side/minutes (str/int/int) は系統/向き/幅、previous/current (dict|None) は足上書き、
    prior_reference/current_reference (dict|None) は参照上書き、higher (list[dict]|None) は上位足、cutoff/deadline (float|None) は時刻。
    返り値: tuple[dict,dict] は四入口と品質。市場価格の再計算はしない。
    """
    first = 15//minutes+5
    before = frame(first, minutes, close=1000-5*side if family == "Q1" else 1000-20*side)
    row = frame(first+1, minutes, close=1000+5*side if family == "Q1" else 1000-5*side)
    before.update(previous or {})
    row.update(current or {})
    prior = reference(third=1000-10*side, N共通準備=False)
    now = reference(third=1000-10*side)
    prior.update(prior_reference or {})
    now.update(current_reference or {})
    upper = [frame(0, 15, close=1000+2*side, ema20=1000, ema20_previous=1000-side)] if higher is None else higher
    return I.generate([before, row], upper, SESSION, cutoff if cutoff is not None else row["confirm"]+3600,
                      deadline if deadline is not None else row["confirm"]+7200, config(), {before["index"]: prior, row["index"]: now})


def event(now: float, line: int, bid: float = 1000, ask: float | None = None,
          valid: bool = True) -> object:
    """小型の正常/不正BBOイベントを作る。

    引数: now/line (float/int) は時計/原行、bid/ask (float|None) は気配、valid (bool) は正常性。
    返り値: object は旧replayへ渡す人工気配。
    """
    ask = bid+5 if ask is None else ask
    return SimpleNamespace(now=now, line=line, bid=bid, ask=ask, valid=valid, last=bid,
                           volume=0, volume_time=now)


def signal(side: int = 1, native: float = 990, role: str = "順行", **updates: object) -> dict:
    """通常出口へ渡す純入口の人工属性を作る。

    引数: side/native/role (int/float/str) は実side/入口線/役割、updates (object) は上書き。
    返り値: dict は未来ラベルを含まない新規要求。
    """
    value = {"場": SESSION, "イベントID": "人工入口", "入口ID": "人工Q", "side": side,
             "方向": "買い" if side == 1 else "売り", "役割": role, "要求時計秒": 0.0,
             "要求原板行": 1, "確認遅延秒": 0, "配信VWAP": native, "補助epoch": 0,
             "atr": 100, "high": 1050, "low": 950, "close": native+side*10 if role == "順行" else native-side*10,
             "bb_mean": None}
    value.update(updates)
    return value


def bar(now: float, line: int, native: float, epoch: int = 0, **updates: object) -> dict:
    """通常線へ渡す参照付き公開足を作る。

    引数: now/line (float/int) は公開キー、native (float) は現在線、epoch (int) は区間、updates (object) は上書き。
    返り値: dict は人工公開足。N4未回復でもnative現在有効を指定する。
    """
    value = {"index": line, "minutes": 1, "publish": True, "end": now,
             "confirm": now, "confirm_line": line, "close": 1000, "ema20": None,
             "配信VWAP": native, "native有効": True, "N共通準備": False, "補助epoch": epoch}
    value.update(updates)
    return value


def replay(policy: str = "X1", role: str = "順行", native: float = 990, side: int = 1,
           quotes: list | None = None, frames: list[dict] | None = None,
           signals: list[dict] | None = None) -> tuple[object, dict]:
    """実新規→通常要求→BBO返済まで短い原順経路を通す。

    引数: policy/role (str) は出口/役割、native/side (float/int) は入口線/side、quotes/frames/signals (list|None) は人工列。
    返り値: tuple[object,dict] は状態/集計。末尾の期限正常板を補い未解消だけで検査を終えない。
    """
    source = list(quotes if quotes is not None else [event(0, 1), event(1, 2), event(2, 3), event(3, 4)])
    if source[-1].now < 91:
        last = source[-1]
        source += [event(91, last.line+1, last.bid, last.ask), event(92, last.line+2, last.bid, last.ask)]
    return O.replay(source, signals if signals is not None else [signal(side, native, role)], frames or [],
                    SESSION, "合成運用", config()["運用"], {"出口ID": policy}, role, BOUNDS)


# ----------------------------------------
# 旧下位指標でなくVWAP位置変化・前現在ATR・共通上位準備から発動する。

class 入口境界検証(unittest.TestCase):
    """Q1/Q2の不等号・鏡像・現在N4・上位マスクを検査する。"""

    def test_Q1とQ2を三尺度両方向で発動する(self) -> None:
        """前N4Falseでも現N4Trueなら最初の四点目で発動できる。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for minutes in (1, 3, 5):
            for family in ("Q1", "Q2"):
                for side in (1, -1):
                    with self.subTest(分=minutes, Q=family, side=side):
                        groups, quality = generate(family, side, minutes)
                        rows = [r for values in groups.values() for r in values]
                        self.assertEqual(len(rows), 2)
                        self.assertTrue(all(r["side"] == side and r["入口系統"] == family for r in rows))
                        self.assertEqual(len(quality["全Q発動記録"]), 1)
                        self.assertIsNone(rows[0]["adx"])
                        self.assertIsNone(rows[0]["ema20"])
                        self.assertIsNone(rows[0]["rsi"])
                        self.assertIsNone(rows[0]["bb_mean"])

    def test_Q1の前等号は含み現等号は除く(self) -> None:
        """再獲得の前は線上でもよいが現在はstrict有利側を要求する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for previous, current, expected in ((1000, 1005, 2), (995, 1000, 0), (1001, 1005, 0)):
            with self.subTest(前=previous, 現=current):
                groups, _ = generate(previous={"close": previous}, current={"close": current})
                self.assertEqual(sum(len(v) for v in groups.values()), expected)

    def test_Q1は各足のnativeで前後距離を測る(self) -> None:
        """現在線だけで前終値を再評価して架空のcrossを作らない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, _ = generate(previous={"close": 1001}, current={"close": 1006}, current_reference={"配信VWAP": 1005})
        self.assertEqual(sum(len(v) for v in groups.values()), 0)

    def test_Q1のnative三足差は等号と逆向きを除く(self) -> None:
        """価格crossがあっても線の方向が0/反対なら発動しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for third in (1000, 1010):
            with self.subTest(三前=third):
                groups, _ = generate(current_reference={"配信3足前VWAP": third})
                self.assertEqual(sum(len(v) for v in groups.values()), 0)

    def test_Q2は前ATR外strictと現在下端inclusiveで線上を除く(self) -> None:
        """前ちょうど1ATRは不可、現在ちょうど−ATRは可、現在線上は不可。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for before, current, expected in ((990, 995, 0), (980, 990, 2), (980, 1000, 0)):
            with self.subTest(前=before, 現=current):
                groups, _ = generate("Q2", previous={"close": before}, current={"close": current})
                self.assertEqual(sum(len(v) for v in groups.values()), expected)

    def test_Q2は前現在の別ATRを使い傾きを要求しない(self) -> None:
        """帯幅を取り違えずQ1の傾きをQ2へ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, _ = generate("Q2", previous={"close": 980, "atr": 25}, current={"close": 995, "atr": 10})
        self.assertEqual(sum(len(v) for v in groups.values()), 0)
        groups, _ = generate("Q2", previous={"close": 970, "atr": 10}, current={"close": 980, "atr": 25}, current_reference={"配信3足前VWAP": 1010})
        self.assertEqual(sum(len(v) for v in groups.values()), 2)

    def test_Q2も前距離には前nativeを使う(self) -> None:
        """前線1000からの乖離を現在線995で上書きしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, _ = generate("Q2", previous={"close": 986}, current={"close": 990}, current_reference={"配信VWAP": 995})
        self.assertEqual(sum(len(v) for v in groups.values()), 2)

    def test_価格改善がなければ幅変化だけで復帰しない(self) -> None:
        """ATRやnative変動だけの位置改善を価格改善と混同しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, _ = generate("Q2", previous={"close": 980, "atr": 10}, current={"close": 980, "atr": 25})
        self.assertEqual(sum(len(v) for v in groups.values()), 0)

    def test_現在前ATRとnative準備と同epochを共通要求(self) -> None:
        """上位方向なしにも現N4/前native/正ATRの同じ準備を課す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for kwargs in ({"previous": {"atr": None}}, {"current": {"atr": 0}}, {"current_reference": {"N共通準備": False}},
                       {"prior_reference": {"native有効": False}}, {"current_reference": {"補助epoch": 1}}, {"current": {"missing": 1}}):
            with self.subTest(不成立=kwargs):
                groups, _ = generate(**kwargs)
                self.assertEqual(sum(len(v) for v in groups.values()), 0)

    def test_上位なしも準備は必要で方向だけ付け外す(self) -> None:
        """中立/逆方向は補助ありだけを除き、未準備は両方除く。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for upper, expected in ((frame(0, 15, close=999, ema20=1000, ema20_previous=1001), 1),
                                (frame(0, 15, close=1000, ema20=1000, ema20_previous=1000), 1),
                                (frame(0, 15, close=1002, ema20=1000, ema20_previous=None), 0)):
            with self.subTest(上位=upper):
                groups, _ = generate(higher=[upper])
                rows = [r for values in groups.values() for r in values]
                self.assertEqual(len(rows), expected)
                if expected:
                    self.assertEqual(rows[0]["補助"], "なし")

    def test_上位の同時計後原行と未来終了足を使わない(self) -> None:
        """判断キーより後に知れる上位足を準備へ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        now = frame(21)
        for upper in (frame(0, 15, close=1002, ema20=1000, ema20_previous=999, confirm=now["confirm"], confirm_line=now["confirm_line"]+1),
                      frame(0, 15, close=1002, ema20=1000, ema20_previous=999, end=now["end"]+1, confirm=now["confirm"]+1)):
            with self.subTest(上位=upper):
                groups, _ = generate(higher=[upper])
                self.assertEqual(sum(len(v) for v in groups.values()), 0)

    def test_確認遅延と停止残時間の境界を維持(self) -> None:
        """30秒は含み31秒/停止等号/残時間不足は除く。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(21)
        for kwargs, expected in (({"current": {"confirm": current["end"]+30}}, 2),
                                 ({"current": {"confirm": current["end"]+31}}, 0),
                                 ({"cutoff": current["confirm"]}, 0),
                                 ({"deadline": current["confirm"]+3600}, 2),
                                 ({"deadline": current["confirm"]+3599}, 0)):
            with self.subTest(条件=kwargs):
                groups, _ = generate(**kwargs)
                self.assertEqual(sum(len(v) for v in groups.values()), expected)

    def test_参照矛盾を欠測補完せず拒否する(self) -> None:
        """現N4trueなのに線が未定義なら仮の価格を使わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with self.assertRaises(ValueError):
            generate(current_reference={"配信VWAP": None})


# ----------------------------------------
# 新規から通常要求と返済まで通し、閾値価格そのもので即約定しない。

class 通常出口検証(unittest.TestCase):
    """hard保護/TPと通常線・更新・epochの実行優先順を確認する。"""

    def test_通常線の等号を買売両役割で要求する(self) -> None:
        """順行の逆抜けと反転到達を返済側Bid/Askで対称に判定する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        cases = [("順行", 1, 990, event(2, 3, 990), event(3, 4, 985), "VWAP通常逆抜け"),
                 ("順行", -1, 1010, event(2, 3, 1005), event(3, 4, 1010), "VWAP通常逆抜け"),
                 ("反転", 1, 1010, event(2, 3, 1010), event(3, 4, 1005), "VWAP通常到達"),
                 ("反転", -1, 990, event(2, 3, 985), event(3, 4, 990), "VWAP通常到達")]
        for policy in ("X1", "X2"):
            for role, side, native, hit, fill, reason in cases:
                with self.subTest(出口=policy, 役割=role, side=side):
                    state, _ = replay(policy, role, native, side, [event(0, 1), event(1, 2), hit, fill])
                    self.assertEqual(len(state.trades), 1)
                    trade = state.trades[0]
                    self.assertEqual(trade["返済理由"], reason)
                    self.assertEqual(trade["返済要求時計秒"], 2)
                    self.assertEqual(trade["返済時計秒"], 3)
                    self.assertTrue(trade["固定利確使用"])
                    self.assertEqual(trade["利確価格"], trade["新規価格"]+side*250)

    def test_新規も通常返済も同時計次行で即約定しない(self) -> None:
        """新規と返済の要求後1秒待機を同秒の別原行でも維持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        quotes = [event(0, 1), event(0, 2), event(1, 3), event(2, 4, 990), event(2, 5, 985), event(3, 6, 980)]
        state, _ = replay(quotes=quotes)
        trade = state.trades[0]
        self.assertEqual(trade["新規時計秒"], 1)
        self.assertEqual(trade["返済要求時計秒"], 2)
        self.assertEqual(trade["返済原板行"], 6)
        self.assertEqual(trade["返済時計秒"], 3)
        self.assertEqual(trade["返済価格"], 980)

    def test_fill時に線超過でも実新規してさらに一秒後返済(self) -> None:
        """未来の新規板でfee0取消せず往復約定と費用を残す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for policy in ("X1", "X2"):
            for role in ("順行", "反転"):
                for side, native in ((1, 1000), (-1, 1005)):
                    with self.subTest(出口=policy, 役割=role, side=side):
                        state, _ = replay(policy, role, native, side, [event(0, 1), event(1, 2), event(1, 3, 995), event(2, 4, 995)])
                        trade = state.trades[0]
                        self.assertEqual(trade["新規時計秒"], 1)
                        self.assertEqual(trade["返済要求時計秒"], 1)
                        self.assertEqual(trade["返済要求原板行"], 2)
                        self.assertEqual(trade["返済時計秒"], 2)
                        self.assertEqual(len(state.fills), 2)
                        self.assertEqual(trade["手数料円"], 22)
                        self.assertEqual(sum(f["fee_yen"] for f in state.fills), 22)

    def test_通常線を非呼値のまま保持し実BBOで返済する(self) -> None:
        """線1002.4を1000へ丸めず1005到達後の次気配で返済する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        quotes = [event(0, 1, 990), event(1, 2, 990), event(2, 3, 1000), event(3, 4, 1005), event(4, 5, 1000)]
        state, _ = replay("X1", "反転", 1002.4, quotes=quotes)
        trade = state.trades[0]
        self.assertEqual(trade["返済要求時計秒"], 3)
        self.assertEqual(trade["返済時計秒"], 4)
        self.assertEqual(trade["返済時通常線"], 1002.4)
        self.assertEqual(trade["返済価格"], 1000)

    def test_hard125保護は通常線より優先する(self) -> None:
        """hard境界と通常逆抜けが同時なら保護理由を維持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side, native, hit, fill in ((1, 990, event(2, 3, 880), event(3, 4, 875)),
                                        (-1, 1010, event(2, 3, 1120), event(3, 4, 1125))):
            with self.subTest(side=side):
                state, _ = replay("X2", "順行", native, side, [event(0, 1), event(1, 2), hit, fill], [bar(2, 3, native, epoch=1)])
                self.assertEqual(state.trades[0]["返済理由"], "保護")
                self.assertEqual(state.epoch_requests, 0)
                self.assertEqual(state.normal_updates, 0)

    def test_hard250TPも全X1X2で通常到達より優先する(self) -> None:
        """通常到達とTP250が同時でも旧hard利確を除去しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for policy in ("X1", "X2"):
            for side, native, hit, fill in ((1, 1100, event(2, 3, 1255), event(3, 4, 1250)),
                                            (-1, 900, event(2, 3, 745), event(3, 4, 750))):
                with self.subTest(出口=policy, side=side):
                    state, _ = replay(policy, "反転", native, side, [event(0, 1), event(1, 2), hit, fill], [bar(2, 3, native, epoch=1)])
                    self.assertEqual(state.trades[0]["返済理由"], "利確")
                    self.assertEqual(state.epoch_requests, 0)

    def test_X1は公開nativeが変わっても入口線を保持(self) -> None:
        """固定通常線を後日値へ引き直さず期限まで保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X1", frames=[bar(2, 3, 1010)])
        trade = state.trades[0]
        self.assertEqual(trade["返済理由"], "期限")
        self.assertEqual(trade["返済時通常線"], 990)
        self.assertEqual(state.normal_updates, 0)

    def test_barからsignalの順でも新規通常線を後日値へ補完しない(self) -> None:
        """要求後の公開線を約定時に引き直さず元signalのnativeを固定する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for policy in ("X1", "X2"):
            with self.subTest(出口=policy):
                quotes = [event(0, 1), event(1, 2, valid=False), event(2, 3), event(3, 4)]
                state, _ = replay(policy, quotes=quotes, frames=[bar(0, 1, 990), bar(1, 2, 1100)])
                trade = state.trades[0]
                self.assertEqual(trade["新規時計秒"], 2)
                self.assertEqual(trade["入口配信VWAP"], 990)
                self.assertEqual(trade["返済時通常線"], 990)
                self.assertEqual(trade["返済理由"], "期限")
                self.assertEqual(state.normal_updates, 0)

    def test_X2はN4未回復でも現在native有効なら更新する(self) -> None:
        """新規助走と保有中の現在線更新の必要条件を分ける。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X2", frames=[bar(2, 3, 1001, N共通準備=False)])
        trade = state.trades[0]
        self.assertEqual(trade["返済理由"], "VWAP通常逆抜け")
        self.assertEqual(trade["返済要求時計秒"], 2)
        self.assertEqual(trade["返済要求原板行"], 3)
        self.assertEqual(trade["返済時計秒"], 3)
        self.assertEqual(trade["返済時通常線"], 1001)

    def test_X2は古い正常BBOで更新直後の到達を作らない(self) -> None:
        """確認行が不正BBOなら新線だけ更新し次の正常quoteで判定する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        quotes = [event(0, 1), event(1, 2), event(2, 3, valid=False), event(3, 4), event(4, 5, 995)]
        state, _ = replay("X2", quotes=quotes, frames=[bar(2, 3, 1001)])
        self.assertEqual(state.trades[0]["返済要求時計秒"], 3)
        self.assertEqual(state.trades[0]["返済時計秒"], 4)
        self.assertTrue(any(row["動作"] == "通常価格判定待機" and row["時計秒"] == 2 for row in state.normal_log))

    def test_X2は同clockでも原行が違う古BBOを使わない(self) -> None:
        """同秒の前原行BBOを新しい公開原行の到達証拠としない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        quotes = [event(0, 1), event(1, 2), event(2, 3), event(2, 5), event(3, 6, 995)]
        state, _ = replay("X2", quotes=quotes, frames=[bar(2, 4, 1001)])
        trade = state.trades[0]
        self.assertEqual(trade["返済要求時計秒"], 2)
        self.assertEqual(trade["返済要求原板行"], 5)
        self.assertEqual(trade["返済時計秒"], 3)

    def test_X2の更新後判定は同一keyならその原行で要求(self) -> None:
        """quoteでは未到達でも同keyの公開更新後に要求し同秒fillしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        quotes = [event(0, 1), event(1, 2), event(2, 3), event(2, 4, 995), event(3, 5, 990)]
        state, _ = replay("X2", quotes=quotes, frames=[bar(2, 3, 1001)])
        self.assertEqual(state.trades[0]["返済要求原板行"], 3)
        self.assertEqual(state.trades[0]["返済時計秒"], 3)
        self.assertTrue(any(row["動作"] == "通常閾値到達" and row["判定元"] == "同原行更新直後" for row in state.normal_log))

    def test_X2の線更新は約定後に終わった足だけ(self) -> None:
        """公開は後でもendが新規約定以前なら線を更新しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X2", quotes=[event(0, 1), event(1, 2), event(2, 3), event(3, 4), event(4, 5, 995)],
                          frames=[bar(2, 3, 1001, end=1), bar(3, 4, 1001)])
        self.assertEqual(state.normal_updates, 1)
        self.assertEqual(state.trades[0]["返済要求時計秒"], 3)
        self.assertTrue(any(row["動作"] == "通常更新抑止" for row in state.normal_log))

    def test_epoch不一致はendguardや同keyBBOなしでも要求する(self) -> None:
        """起算変更の有効公開を価格閾値判定と異なる根拠として扱う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for policy in ("X1", "X2"):
            with self.subTest(出口=policy):
                state, _ = replay(policy, quotes=[event(0, 1), event(1, 2), event(3, 4), event(4, 5)],
                                  frames=[bar(2, 3, 990, epoch=1, end=0)])
                trade = state.trades[0]
                self.assertEqual(trade["返済理由"], "VWAP起算失効")
                self.assertEqual(trade["返済要求時計秒"], 2)
                self.assertEqual(trade["返済時計秒"], 3)
                self.assertEqual(state.normal_updates, 0)

    def test_native不可ならepochが違っても線据置で要求しない(self) -> None:
        """現在無効の参照で起算失効を先取りせず後の有効公開だけを使う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X2", quotes=[event(0, 1), event(1, 2), event(2, 3), event(3, 4), event(4, 5)],
                          frames=[bar(2, 3, 990, epoch=1, native有効=False), bar(3, 4, 990, epoch=1)])
        self.assertEqual(state.trades[0]["返済理由"], "VWAP起算失効")
        self.assertEqual(state.trades[0]["返済要求時計秒"], 3)
        self.assertEqual(state.normal_unavailable, 1)

    def test_欠測時の既知線保持は新規特徴のfallbackと分ける(self) -> None:
        """保有中にnative不可でも入口で設定した線で次quoteを監視する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X2", quotes=[event(0, 1), event(1, 2), event(2, 3), event(3, 4, 990), event(4, 5, 985)],
                          frames=[bar(2, 3, 1100, native有効=False)])
        self.assertEqual(state.trades[0]["返済要求時計秒"], 3)
        self.assertEqual(state.trades[0]["返済時通常線"], 990)
        self.assertEqual(state.normal_updates, 0)

    def test_X2は単調利益床でなく有効nativeへ上下更新(self) -> None:
        """通常線を追尾保護と混同して有利側へだけratchetしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X2", quotes=[event(0, 1), event(1, 2), event(2, 3, 1100), event(3, 4, 1100), event(4, 5, 1100)],
                          frames=[bar(2, 3, 1000), bar(3, 4, 980), bar(4, 5, 1005)])
        levels = [row["新通常線"] for row in state.normal_log if row["動作"] == "通常線更新"]
        self.assertEqual(levels, [1000, 980, 1005])
        self.assertEqual(state.trades[0]["返済理由"], "期限")

    def test_先に出た通常返済をbarの変更で取り消さない(self) -> None:
        """同keyのquote通常要求を後の新線やepochで上書きしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X2", quotes=[event(0, 1), event(1, 2), event(2, 3, 990), event(3, 4)],
                          frames=[bar(2, 3, 980, epoch=1)])
        self.assertEqual(state.trades[0]["返済理由"], "VWAP通常逆抜け")
        self.assertEqual(state.trades[0]["返済要求時計秒"], 2)
        self.assertEqual(state.epoch_requests, 0)
        self.assertEqual(state.normal_updates, 0)

    def test_期限は同keyのepochや通常線より優先する(self) -> None:
        """期限前の処理を先に実行し既存期限要求を上書きしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X2", quotes=[event(0, 1), event(1, 2), event(90, 3), event(91, 4)],
                          frames=[bar(90, 3, 1100, epoch=1)])
        self.assertEqual(state.trades[0]["返済理由"], "期限")
        self.assertEqual(state.trades[0]["返済要求時計秒"], 90)
        self.assertEqual(state.trades[0]["返済要求原板行"], 0)
        self.assertEqual(state.epoch_requests, 0)

    def test_返済正常板がなければ未解消と費用を保持(self) -> None:
        """通常線の要求価格で架空返済せずEOFの未解消を残す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, info = O.replay([event(0, 1), event(1, 2), event(2, 3, 990)], [signal()], [], SESSION,
                               "未解消合成", config()["運用"], {"出口ID": "X1"}, "順行", BOUNDS)
        self.assertEqual(len(state.fills), 1)
        self.assertEqual(state.trades, [])
        self.assertEqual(info["終了建玉"], 1)
        self.assertEqual(info["観測現金増減円"], -11)
        self.assertIsNone(info["確定対象純損益円"])


# ----------------------------------------
# X0は旧コードの返り値を直接使い、定義/表示代表を結果前に固定する。

class 固定依存検証(unittest.TestCase):
    """旧X0同値・十二入口/三出口・空足と原順の制約を確認する。"""

    def test_X0は旧COREの会計約定注文と全文同値(self) -> None:
        """新通常状態を通さず旧replayの返り値と一致する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        quotes = [event(0, 1), event(1, 2), event(2, 3, 1255), event(3, 4, 1250), event(91, 5, 1250)]
        args = (quotes, [signal()], [], SESSION, "X0同値", config()["運用"], {"出口ID": "X0"}, "順行", BOUNDS)
        current, info = O.replay(*deepcopy(args))
        legacy, expected = O.CORE.replay(*deepcopy(args))
        self.assertEqual(type(current), type(legacy))
        for attr in ("fills", "trades", "orders", "signals"):
            self.assertEqual(getattr(current, attr), getattr(legacy, attr))
        self.assertEqual(info, expected)
        self.assertFalse(hasattr(current, "normal_log"))

    def test_入口12と運用36と空足4を列挙(self) -> None:
        """三尺度二Q二上位三出口を結果で増減しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE/"検証.py", "VWAP復帰の定義確認")
        sources = driver.sources(config())
        self.assertEqual(len(sources), 12)
        self.assertEqual(len(sources)*len(config()["出口"]), 36)
        self.assertEqual(sum(s["時間足分"] == 3 for s in sources)*3, 12)
        for size in (1, 3, 5):
            groups, quality = driver.generate_or_empty([], [], SESSION, size, START+22000, START+24000, config(), {})
            self.assertEqual(len(groups), 4)
            self.assertTrue(all(not rows for rows in groups.values()))
            self.assertEqual(quality["全Q発動記録"], [])


# ----------------------------------------
# 最終通知前は途中proofだけを作り、固定後変更は別追補へ分離する。

def main() -> None:
    """入口/通常出口の合成を実行して途中と最終proofを区別する。

    引数: なし。--finalの完成時だけ編集終了を記録する。
    返り値: None。失敗時は終了コード1、共有市場データは再生しない。
    """
    parser = argparse.ArgumentParser(description="VWAP復帰入口と通常出口の人工合成")
    parser.add_argument("--final", action="store_true", help="全編集終了時だけ固定用proofを保存")
    args = parser.parse_args()
    paths = [Path(__file__), HERE/"入口.py", HERE/"運用.py", HERE/"検証.py", STUDY/"条件.json"]
    pins = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if args.final and (STUDY/"固定.json").exists():
        locked = json.loads((STUDY/"固定.json").read_text(encoding="utf-8"))["ファイルSHA256"]
        if any(locked.get(name) != digest for name, digest in pins.items()):
            raise ValueError("固定後の追加は別ファイルへ分離する")
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    proof = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
             "合成編集終了": bool(args.final and result.wasSuccessful()), "ファイルSHA256": pins,
             "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
             "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors],
             "範囲": "人工価格とBBOのQ1/Q2/上位/現N4/通常線/TP-SL期限/原行/待機/epoch/旧X0同値。共有原板や市場成績を再生しない。",
             "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k: proof[k] for k in ("全件成功", "検証件数", "合成編集終了")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
