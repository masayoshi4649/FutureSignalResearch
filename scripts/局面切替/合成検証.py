"""00020の局面分類・当時割当・選択と混合一建玉を人工系列で検査する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00020_テクニカル局面による順行反転の切替"
WORK = ROOT/"work/局面切替"


def load(path: Path, name: str) -> object:
    """公開APIをコマンド行実行せず読み込む。

    引数: path (Path) は対象コード、name (str) はmodule識別名。
    返り値: object は読み込んだmodule。市場結果を読み取らない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


R = load(HERE/"局面.py", "局面切替合成の局面")
I = load(HERE/"入口.py", "局面切替合成の複合入口")
O = load(HERE/"運用.py", "局面切替合成の混合運用")


def config() -> dict:
    """結果を含まない固定条件のコピーを返す。

    引数: なし。
    返り値: dict は条件正本、作成前だけ局面部分の人工条件。
    """
    path = STUDY/"条件.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    previous = json.loads((ROOT/"study/00019_VWAP復帰の入口と通常出口/条件.json").read_text(encoding="utf-8"))
    return {**previous, "局面条件": deepcopy(R.RULES), "複合条件": deepcopy(I.RULES), "戦略": list(R.POLICIES)}


def upper(index: int, adx: float | None = 25, side: int = 1, **updates: object) -> dict:
    """価格とDIが同じ向きの15分公開足を作る。

    引数: index (int) は番号、adx (float|None) は強さ、side (int) は方向、updates (object) は上書き。
    返り値: dict は人工15分足。保存された場や価格経路を使わない。
    """
    value = {"index": index, "minutes": 15, "start": index*900., "end": (index+1)*900.,
             "confirm": (index+1)*900., "confirm_line": 100+index, "publish": True, "missing": 0,
             "close": 1000+side*10, "ema20": 1000, "ema20_previous": 1000-side,
             "adx": adx, "plus_di": 30 if side == 1 else 10, "minus_di": 10 if side == 1 else 30}
    value.update(updates)
    return value


def lower(index: int, end: float, now: float | None = None, line: int = 1000, **updates: object) -> dict:
    """上位割当だけを検査する下位公開足を作る。

    引数: index (int) は番号、end/now (float|None) は終了/確認時計、line (int) は公開原行、updates (object) は上書き。
    返り値: dict は人工下位足。状態遷移を新しく作る入力ではない。
    """
    value = {"index": index, "minutes": 1, "start": end-60, "end": end,
             "confirm": end if now is None else now, "confirm_line": line, "publish": True, "missing": 0}
    value.update(updates)
    return value


def context(state: str = "トレンド", side: int = 1, ready: bool = True) -> dict:
    """局面選択の最小の人工文脈を作る。

    引数: state (str) は状態、side (int) は方向、ready (bool) は共通M。
    返り値: dict はS1/S2の同じ人工文脈。
    """
    return {"共通M準備": ready, "S1局面": state, "S1方向": side,
            "S2局面": state, "S2方向": side}


def price(index: int, minutes: int = 1, **updates: object) -> dict:
    """三尺度特徴とRSIを持つ公開人工足を作る。

    引数: index/minutes (int) は足番号/尺度、updates (object) は上書き。
    返り値: dict は合成専用足。EMA/ATR/RSIの計算自体を検査するfixtureではない。
    """
    start = 3600+index*minutes*60
    value = {"index": index, "minutes": minutes, "start": start, "end": start+minutes*60,
        "confirm": start+minutes*60, "confirm_line": 2000+index, "publish": True, "missing": 0,
        "open": 1000, "high": 1020, "low": 980, "close": 1010, "atr": 100,
        "ema10": 1000, "ema20": 1000, "ema20_previous": 998, "adx": None, "rsi": 55,
        "bb_mean": None, "bb_sd": None}
    value.update(updates)
    return value


def higher_pair(side: int = 1) -> tuple[list[dict], list[dict]]:
    """一時間後に利用可能な15/60分の正規化傾き境界を用意する。

    引数: side (int) は買1/売−1。
    返り値: tuple[list[dict],list[dict]] は上位15分/60分。
    """
    fifteen = upper(3, side=side, ema10=1000, ema20_previous=1000-2*side, atr=100)
    sixty = {**fifteen, "minutes": 60, "index": 0, "start": 0, "confirm_line": 103}
    return [fifteen], [sixty]


def complex_context(side: int = 1, state: str = "トレンド", rsi: list[float] | None = None) -> dict:
    """複合条件の人工文脈を作り方向側RSIへ鏡映する。

    引数: side (int) は方向、state (str) は局面、rsi (list[float]|None) は方向側RSI。
    返り値: dict は三尺度傾き0.02/収束3尺度の準備済み文脈。
    """
    values = [55]*5 if rsi is None else rsi
    feature = I.scale_feature(price(0, close=1000+10*side, ema20_previous=1000-2*side))
    return {**context(state, side), "旧M準備": True, "M除外理由": [],
            "三尺度特徴": {name: deepcopy(feature) for name in ("入口", "15分", "60分")},
            "収束尺度数": 3, "RSI五本": [{"index": n, "rsi": value if side == 1 else 100-value,
                "confirm": n*60., "confirm_line": n+1} for n, value in enumerate(values)]}


def quote(now: float, line: int, bid: float = 1000, ask: float | None = None, valid: bool = True) -> object:
    """原順時計とBBOだけを持つ人工正常板を作る。

    引数: now/line (float/int) は時計/原行、bid/ask (float|None) は気配、valid (bool) は正常性。
    返り値: object は公開運用APIへ渡すイベント。
    """
    ask = bid+5 if ask is None else ask
    return SimpleNamespace(now=now, line=line, last=bid, bid=bid, ask=ask, valid=valid, volume=0, volume_time=now)


def request(side: int = 1, role: str = "順行", native: float | None = None, **updates: object) -> dict:
    """固定入口特徴と役割を持つ人工要求を作る。

    引数: side/role (int/str) は売買/役割、native (float|None) は線、updates (object) は上書き。
    返り値: dict は将来ラベルを含まない入口。
    """
    value = {"場": "2026-11-04_Day", "イベントID": "人工入口", "入口ID": "1分_S0",
        "side": side, "方向": "買い" if side == 1 else "売り", "役割": role,
        "要求時計秒": 0., "要求原板行": 1, "確認遅延秒": 0,
        "配信VWAP": (1000-100*side if role == "順行" else 1000+100*side) if native is None else native,
        "補助epoch": 0, "atr": 100, "high": 1050, "low": 950, "close": 1000, "bb_mean": None}
    value.update(updates)
    return value


def native_bar(now: float, line: int, native: float = 900, **updates: object) -> dict:
    """通常線と局面を独立に上書きできる公開足を作る。

    引数: now/line (float/int) は公開キー、native (float) は線、updates (object) は上書き。
    返り値: dict は通常出口へ渡す人工足。
    """
    value = {"index": line, "minutes": 1, "end": now, "confirm": now, "confirm_line": line,
             "publish": True, "native有効": True, "配信VWAP": native, "補助epoch": 0,
             "N共通準備": False, "close": 1000, "ema20": None}
    value.update(updates)
    return value


def replay(policy: str, quotes: list, signals: list[dict] | None = None,
           frames: list[dict] | None = None) -> tuple[object, dict]:
    """短い原順人工経路を混合一建玉の実新規から返済まで通す。

    引数: policy (str) は出口、quotes (list) は気配、signals/frames (list[dict]|None) は要求/公開足。
    返り値: tuple[object,dict] は状態/会計。省略した終端正常板を補う。
    """
    source = list(quotes)
    if source[-1].now < 91:
        last = source[-1]
        source += [quote(91, last.line+1, last.bid, last.ask), quote(92, last.line+2, last.bid, last.ask)]
    return O.replay(source, [request()] if signals is None else signals, frames or [], "2026-11-04_Day",
                    "合成混合", config()["運用"], {"出口ID": policy}, "混合", (0, 100, 80, 90))


# ----------------------------------------
# 20/25の強さとEMA/DIの向きを分け、期待する状態を固定表で照合する。

class 局面境界検証(unittest.TestCase):
    """閾値・方向・履歴保持・初期化と切替件数を検査する。"""

    def test_S1の20と25等号と中間待機(self) -> None:
        """弱側20はレンジ、強側25は一致方向だけトレンドにする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for adx, direction, expected in ((20, 1, ("レンジ", 0)), (20, 0, ("レンジ", 0)),
                (20.0001, 1, ("待機", 0)), (24.9999, -1, ("待機", 0)),
                (25, 1, ("トレンド", 1)), (25, -1, ("トレンド", -1)), (50, 0, ("待機", 0))):
            with self.subTest(ADX=adx, 方向=direction):
                self.assertEqual(R.instant(True, adx, direction), expected)
        self.assertEqual(R.instant(False, None, 0), ("未準備", 0))

    def test_EMAとDIの一致だけ方向を持つ(self) -> None:
        """ADXの大きさだけで上昇方向を与えずEMAとDIを別に記録する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            self.assertEqual(R.directions(upper(0, side=side)), (True, side, side, side))
            opposite = upper(0, side=side, plus_di=10 if side == 1 else 30, minus_di=30 if side == 1 else 10)
            self.assertEqual(R.directions(opposite), (True, side, -side, 0))
        self.assertEqual(R.directions(upper(0, plus_di=20, minus_di=20)), (True, 1, 0, 0))
        self.assertEqual(R.directions(upper(0, close=1000)), (True, 0, 1, 0))
        self.assertEqual(R.directions(upper(0, ema20_previous=1000)), (True, 0, 1, 0))

    def test_Mは全六値有限かつ公開を共通に要求(self) -> None:
        """既知中立と指標未準備を区別し欠測を0補完しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for key in ("close", "ema20", "ema20_previous", "adx", "plus_di", "minus_di"):
            for missing in (None, float("nan"), float("inf")):
                with self.subTest(列=key, 値=missing):
                    self.assertEqual(R.directions(upper(0, **{key: missing})), (False, 0, 0, 0))
        self.assertEqual(R.directions(upper(0, publish=False)), (False, 0, 0, 0))
        self.assertTrue(R.directions(upper(0, plus_di=0, minus_di=0))[0])

    def test_S2固定遷移表の全状態方向境界(self) -> None:
        """レンジ維持とトレンド維持を即時閾値と区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        cases = [
            (("待機", 0), 20, 0, ("レンジ", 0)), (("待機", 0), 22, 1, ("待機", 0)),
            (("待機", 0), 25, -1, ("トレンド", -1)), (("待機", 0), 25, 0, ("待機", 0)),
            (("レンジ", 0), 24.999, 0, ("レンジ", 0)), (("レンジ", 0), 25, 0, ("待機", 0)),
            (("レンジ", 0), 25, 1, ("トレンド", 1)),
            (("トレンド", 1), 20, 1, ("レンジ", 0)), (("トレンド", 1), 20.001, 1, ("トレンド", 1)),
            (("トレンド", 1), 24, 0, ("待機", 0)), (("トレンド", 1), 24, -1, ("待機", 0)),
            (("トレンド", 1), 25, -1, ("トレンド", -1)),
            (("トレンド", -1), 22, -1, ("トレンド", -1)), (("トレンド", -1), 22, 1, ("待機", 0)),
            (("トレンド", -1), 25, 1, ("トレンド", 1)),
        ]
        for previous, adx, direction, expected in cases:
            with self.subTest(直前=previous, ADX=adx, 方向=direction):
                self.assertEqual(R.sticky(previous, True, adx, direction), expected)
        for previous in (("待機", 0), ("レンジ", 0), ("トレンド", 1)):
            self.assertEqual(R.sticky(previous, False, None, 0), ("未準備", 0))

    def test_履歴保持は一足一回で初回を切替に足さない(self) -> None:
        """既知系列のS1とS2の切替回数を手計算で比較する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        sequence = [upper(0, 20), upper(1, 22), upper(2, 25), upper(3, 22),
                    upper(4, 22, plus_di=10, minus_di=30), upper(5, 25, -1), upper(6, 20, -1)]
        rows, quality = R.build(sequence, "人工_Day", config())
        self.assertEqual([(r["S1局面"], r["S1方向"]) for r in rows],
            [("レンジ", 0), ("待機", 0), ("トレンド", 1), ("待機", 0), ("待機", 0), ("トレンド", -1), ("レンジ", 0)])
        self.assertEqual([(r["S2局面"], r["S2方向"]) for r in rows],
            [("レンジ", 0), ("レンジ", 0), ("トレンド", 1), ("トレンド", 1), ("待機", 0), ("トレンド", -1), ("レンジ", 0)])
        self.assertEqual(quality["S1切替回数"], 5)
        self.assertEqual(quality["S2切替回数"], 4)
        self.assertEqual(quality["初回準備分類数"], 1)
        self.assertFalse(rows[0]["切替比較可能"])

    def test_index飛越欠枠非公開未準備は記憶を初期化(self) -> None:
        """ADX22の前のレンジやトレンドをreset越しに持ち越さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        cases = [([upper(0, 20), upper(2, 22)], 1, "15分足番号飛越"),
                 ([upper(0, 20), upper(1, 22, missing=1)], 1, "15分欠枠"),
                 ([upper(0, 20), upper(1, 22, publish=False), upper(2, 22)], 2, "非公開15分足"),
                 ([upper(0, 20), upper(1, None), upper(2, 22)], 2, "上位指標未準備")]
        for frames, position, reason in cases:
            with self.subTest(原因=reason):
                rows, quality = R.build(frames, "人工_Day", config())
                self.assertEqual(rows[position]["S2局面"], "待機")
                self.assertFalse(rows[position]["切替比較可能"])
                self.assertEqual(quality["S2切替回数"], 0)
                self.assertTrue(any(reason in r["記憶初期化理由"] for r in rows))
        rows, _ = R.build([upper(0, 22)], "人工_Night", config())
        self.assertEqual(rows[0]["S2適用前局面"], "待機")
        self.assertEqual(rows[0]["S2局面"], "待機")

    def test_未来の足を変更して過去分類を訂正しない(self) -> None:
        """未来の極端なADXや方向を前の分類へ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        prefix = [upper(0, 20), upper(1, 22)]
        first, _ = R.build(prefix+[upper(2, 60, -1)], "人工_Day", config())
        second, _ = R.build(prefix+[upper(2, 5, 1)], "人工_Day", config())
        self.assertEqual(first[:2], second[:2])

    def test_公開順番号逆行と未来公開を拒否(self) -> None:
        """重複足や終了前公開を通常系列へ黙って混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for frames in ([upper(0), upper(0)], [upper(1), upper(0)],
                       [upper(0, confirm=899)], [upper(0, minutes=5)],
                       [upper(0), upper(1, confirm=900, confirm_line=100)]):
            with self.subTest(足=frames):
                with self.assertRaises(ValueError):
                    R.build(frames, "人工_Day", config())


# ----------------------------------------
# 上位の公開秒と原行と終了時刻を満たすものだけを下位へ当時割当てする。

class 割当選択検証(unittest.TestCase):
    """as-of割当・五戦略の手法/方向選択と予測情報の範囲を検査する。"""

    def test_同秒後原行の上位を先取りしない(self) -> None:
        """公開秒が同じでも原行前の下位には旧局面を残す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rows, _ = R.build([upper(0, 20), upper(1, 25, -1, confirm_line=200)], "人工_Day", config())
        result = R.assign([lower(0, 1800, line=199), lower(1, 1800, line=200), lower(2, 1800, line=201)], rows)
        self.assertEqual([r["S1局面"] for r in result.values()], ["レンジ", "トレンド", "トレンド"])
        self.assertEqual(result[0]["局面公開原行"], 100)
        self.assertEqual(result[1]["局面公開原行"], 200)
        self.assertEqual(result[1]["S1方向"], -1)

    def test_価格足終端より後の上位は確認済みでも使わない(self) -> None:
        """遅延した下位の時計だけで未来の上位終端を採用しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rows, _ = R.build([upper(0, 20), upper(1, 25, -1)], "人工_Day", config())
        result = R.assign([lower(0, 1740, now=1801), lower(1, 1800, now=1801)], rows)
        self.assertEqual(result[0]["S1局面"], "レンジ")
        self.assertEqual(result[1]["S1局面"], "トレンド")

    def test_同じ上位への下位繰返しで状態と件数を変えない(self) -> None:
        """割当は分類の読取でありS2を再遷移させない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rows, quality = R.build([upper(0, 20), upper(1, 22)], "人工_Day", config())
        saved = deepcopy((rows, quality))
        for size in (1, 3, 5):
            assigned = R.assign([lower(i, 1800+i*size) for i in range(30)], rows)
            self.assertTrue(all(r["S2局面"] == "レンジ" for r in assigned.values()))
        self.assertEqual((rows, quality), saved)

    def test_参照なし非公開指標未準備を転換待機と区別(self) -> None:
        """待機は準備済み分類、未準備は五戦略共通gateとして記録する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rows, _ = R.build([upper(0, 22), upper(1, None)], "人工_Day", config())
        result = R.assign([lower(0, 899), lower(1, 900), lower(2, 960, publish=False), lower(3, 1800)], rows)
        self.assertEqual(result[0]["S1局面"], "未準備")
        self.assertFalse(result[0]["共通M準備"])
        self.assertEqual(result[1]["S1局面"], "待機")
        self.assertTrue(result[1]["共通M準備"])
        self.assertFalse(result[2]["共通M準備"])
        self.assertEqual(result[3]["S1局面"], "未準備")
        self.assertFalse(result[3]["共通M準備"])

    def test_五戦略は同じMを必要とする(self) -> None:
        """固定手法や混合だけ未準備時から発動して助走差を作らない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for policy in R.POLICIES:
            for family in ("Q1", "Q2"):
                for side in (1, -1):
                    self.assertEqual(R.allowed(policy, family, side, context(ready=False)), (False, "共通局面準備なし"))

    def test_五戦略のトレンドレンジ待機選択を全向き比較(self) -> None:
        """方向一致順行と向きに依存しない反転を手計算集合で確認する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        opportunities = [(q, side) for q in ("Q1", "Q2") for side in (1, -1)]
        for state, direction in (("トレンド", 1), ("トレンド", -1), ("レンジ", 0), ("待機", 0)):
            expected = {"B1": {("Q1", 1), ("Q1", -1)}, "B2": {("Q2", 1), ("Q2", -1)},
                "S0": set(opportunities),
                "S1": {("Q1", direction)} if state == "トレンド" else {("Q2", 1), ("Q2", -1)} if state == "レンジ" else set()}
            expected["S2"] = expected["S1"]
            for policy in R.POLICIES:
                accepted = {(q, side) for q, side in opportunities if R.allowed(policy, q, side, context(state, direction))[0]}
                self.assertEqual(accepted, expected[policy])

    def test_未来ラベルや損益を追加変更して選択不変(self) -> None:
        """先着や将来の収益をrouter入力にしていないことを確認する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        first = context("トレンド", 1)
        second = {**first, "先着ラベル": "250先着", "純損益円": 9999999, "未来局面": "レンジ"}
        third = {**first, "先着ラベル": "125先着", "純損益円": -9999999, "未来局面": "トレンド"}
        for policy in R.POLICIES:
            for q in ("Q1", "Q2"):
                for side in (1, -1):
                    self.assertEqual(R.allowed(policy, q, side, second), R.allowed(policy, q, side, third))

    def test_割当番号重複と不正な選択定義を拒否(self) -> None:
        """不正入力を待機や空集合へ黙って変えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rows, _ = R.build([upper(0)], "人工_Day", config())
        with self.assertRaises(ValueError):
            R.assign([lower(0, 900), lower(0, 960)], rows)
        for args in (("S9", "Q1", 1, context()), ("S1", "Q9", 1, context()),
                     ("S1", "Q1", 0, context()), ("S1", "Q1", 1, context("トレンド", 0)),
                     ("S1", "Q1", 1, context("未準備", 0))):
            with self.assertRaises(ValueError):
                R.allowed(*args)
        changed = deepcopy(config())
        changed["局面条件"]["ADX強境界"] = 24
        with self.assertRaises(ValueError):
            R.build([upper(0)], "人工_Day", changed)


# ----------------------------------------
# 三尺度のEMAとRSIの持続/急変を組み合わせ、見送りを逆方向発動へ読み替えない。

class 複合条件検証(unittest.TestCase):
    """共通助走・三尺度正規化・RSI鏡像・影の全候補を検査する。"""

    def test_三尺度傾きと収束は各自ATRで正規化し等号を含む(self) -> None:
        """収束二条件の等号と一方だけ超過の非成立を検査する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        feature = I.scale_feature(price(0, ema10=1025, ema20_previous=990))
        self.assertEqual(feature["正規化間隔"], .25)
        self.assertEqual(feature["正規化傾き"], .10)
        self.assertTrue(feature["収束"])
        for updates in ({"ema10": 1025.001}, {"ema20_previous": 989.999}):
            self.assertFalse(I.scale_feature(price(0, **{"ema10": 1025, "ema20_previous": 990, **updates}))["収束"])
        for atr in (0, -1, None, float("nan")):
            self.assertFalse(I.scale_feature(price(0, atr=atr))["準備済"])

    def test_現在を含むRSI五本と三尺度が全策略共通助走(self) -> None:
        """一戦略だけ準備前から始めず四本時点と五本時点を区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        h15, h60 = higher_pair()
        regimes, _ = R.build(h15, "人工_Day", config())
        rows, quality = I.contexts([price(n) for n in range(5)], h15, h60, regimes, config())
        self.assertFalse(rows[3]["共通M準備"])
        self.assertTrue(rows[4]["共通M準備"])
        self.assertEqual(quality["共通M準備足数"], 1)
        self.assertEqual([r["index"] for r in rows[4]["RSI五本"]], list(range(5)))
        for policy in R.POLICIES:
            self.assertFalse(I.decision(policy, "Q1", 1, rows[3])[0])

    def test_RSI欠枠非公開番号飛越欠測は履歴を切る(self) -> None:
        """欠測を0として履歴へ詰めず復帰後の五本から再開する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        h15, h60 = higher_pair()
        regimes, _ = R.build(h15, "人工_Day", config())
        cases = [[price(n) for n in (0, 1, 3, 4, 5, 6, 7)]]
        for updates in ({"missing": 1}, {"publish": False}, {"rsi": None}, {"rsi": float("nan")}):
            frames = [price(n) for n in range(9)]
            frames[3].update(updates)
            cases.append(frames)
        for frames in cases:
            rows, _ = I.contexts(frames, h15, h60, regimes, config())
            self.assertTrue(rows[frames[-1]["index"]]["共通M準備"])
            self.assertFalse(rows[frames[3]["index"]]["共通M準備"])
            self.assertLessEqual(len(rows[frames[3]["index"]]["RSI五本"]), 2)

    def test_60分の同秒後原行と未来終端を先取りしない(self) -> None:
        """最新公開15分だけでは共通Mを満たさず60分の当時キーを待つ。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [price(n) for n in range(5)]
        h15, h60 = higher_pair()
        regimes, _ = R.build(h15, "人工_Day", config())
        for line, expected in ((2005, False), (2004, True)):
            upper60 = [{**h60[0], "end": 3900., "confirm": 3900., "confirm_line": line}]
            rows, _ = I.contexts(frames, h15, upper60, regimes, config())
            self.assertEqual(rows[4]["共通M準備"], expected)
        frames[-1]["confirm"] = 4000.
        rows, _ = I.contexts(frames, h15, [{**h60[0], "end": 3960., "confirm": 3960.}], regimes, config())
        self.assertFalse(rows[4]["共通M準備"])

    def test_各尺度のEMA欠測とATR不正は対照にも共通除外(self) -> None:
        """60分や下位の準備欠測を一つの票の不一致へ読み替えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for size in ("入口", "15分", "60分"):
            for key, value in (("ema10", None), ("ema20", float("nan")), ("ema20_previous", None), ("atr", 0)):
                frames = [price(n) for n in range(5)]
                h15, h60 = higher_pair()
                target = frames[-1] if size == "入口" else h15[0] if size == "15分" else h60[0]
                target[key] = value
                regimes, _ = R.build(h15, "人工_Day", config())
                rows, _ = I.contexts(frames, h15, h60, regimes, config())
                self.assertFalse(rows[4]["共通M準備"])
                for policy in R.POLICIES:
                    self.assertFalse(I.decision(policy, "Q1", 1, rows[4])[0])

    def test_順行の三尺度傾き下限とRSI三本50を両sideで含む(self) -> None:
        """EMA傾き0.02とRSI50の等号は採用し一尺度不足は見送る。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            row = complex_context(side, rsi=[45, 45, 50, 50, 50])
            for policy in ("S1", "S2"):
                self.assertTrue(I.decision(policy, "Q1", side, row)[0])
                for name in ("入口", "15分", "60分"):
                    changed = deepcopy(row)
                    changed["三尺度特徴"][name]["正規化傾き"] = side*.019999
                    self.assertFalse(I.decision(policy, "Q1", side, changed)[0])
                changed = deepcopy(row)
                changed["三尺度特徴"]["入口"]["close"] = 1000
                self.assertFalse(I.decision(policy, "Q1", side, changed)[0])
                changed = complex_context(side, rsi=[55, 55, 49.999, 55, 55])
                self.assertFalse(I.decision(policy, "Q1", side, changed)[0])

    def test_RSI高水準持続と一時急変を区別し対照は抑止しない(self) -> None:
        """70以上という水準だけで除外せず差12と過去4本条件を全て要する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        cases = [([70, 72, 73, 74, 75], False), ([50, 50, 55, 58, 70], True),
                 ([50, 50, 55, 58.001, 70], False), ([50, 50, 55, 57, 69.999], False),
                 ([65, 50, 55, 58, 70], True), ([65, 65, 55, 58, 70], False)]
        for side in (1, -1):
            for values, spike in cases:
                row = complex_context(side, rsi=values)
                accepted, result = I.decision("S1", "Q1", side, row)
                self.assertEqual(result["RSI急変警戒"], spike)
                self.assertEqual(accepted, not spike)
                for policy in ("B1", "S0"):
                    self.assertTrue(I.decision(policy, "Q1", side, row)[0])

    def test_反転は二尺度収束とRSI戻り30から60の等号を使う(self) -> None:
        """反転側も方向側RSIへ鏡映し前40/現30と60を含む。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for before, current, expected in ((40, 60, True), (29, 30, True), (40, 40, False),
                    (40.001, 50, False), (29, 29.999, False), (40, 60.001, False)):
                row = complex_context(side, "レンジ", [45, 45, 35, before, current])
                row["収束尺度数"] = 2
                self.assertEqual(I.decision("S2", "Q2", side, row)[0], expected)
            row = complex_context(side, "レンジ", [45, 45, 35, 30, 45])
            row["収束尺度数"] = 1
            self.assertFalse(I.decision("S1", "Q2", side, row)[0])

    def test_待機や順行不一致から反対側へ自動発動しない(self) -> None:
        """トレンドQ1の不成立をQ2選択の根拠にしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for state in ("トレンド", "待機"):
            row = complex_context(1, state, [45, 45, 35, 30, 45])
            for policy in ("S1", "S2"):
                self.assertFalse(I.decision(policy, "Q2", 1, row)[0])
                self.assertFalse(I.decision(policy, "Q1", -1, row)[0])
        row = complex_context()
        mutated = {**row, "先着ラベル": "250先着", "将来損益円": -99999}
        self.assertEqual(I.decision("S1", "Q1", 1, row), I.decision("S1", "Q1", 1, mutated))

    def test_固定19のQを三尺度両sideで同値利用し影候補を残す(self) -> None:
        """三尺度特徴を固定Qへ上書きせず元QIDを対照へ対応させる。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for size in (1, 3, 5):
            for side in (1, -1):
                frames = [price(n, size, close=1000-5*side, rsi=55 if side == 1 else 45,
                                ema20_previous=1000-2*side) for n in range(5)]
                frames[-1]["close"] = 1000+5*side
                h15, h60 = higher_pair(side)
                refs = {f["index"]: {"配信VWAP": 1000., "配信3足前VWAP": 1000.-10*side,
                    "N共通準備": True, "native有効": True, "補助epoch": 0} for f in frames}
                cutoff, deadline = frames[-1]["confirm"]+3600, frames[-1]["confirm"]+7200
                current, quality = I.generate(frames, h15, h60, "2026-11-04_Day", cutoff, deadline, config(), refs)
                old_config = {**config(), "入口系統": ["Q1", "Q2"], "補助": ["なし", "15分方向一致"]}
                old, _ = I.Q.generate(frames, h15, "2026-11-04_Day", cutoff, deadline, old_config, refs)
                original = old[f"{size}分_Q1_なし"]
                self.assertEqual(len(original), 1)
                self.assertEqual([r["QイベントID"] for r in quality["全Q発動記録"]], [r["QイベントID"] for r in original])
                for policy in ("B1", "S0", "S1", "S2"):
                    self.assertEqual(len(current[f"{size}分_{policy}"]), 1)
                    row = current[f"{size}分_{policy}"][0]
                    for key, value in original[0].items():
                        if key not in ("入口ID", "イベントID"):
                            self.assertEqual(row[key], value)
                    self.assertEqual(row["元Q入口ID"], f"{size}分_Q1_なし")
                self.assertEqual(current[f"{size}分_B2"], [])

    def test_生成で同方向両方向の競合をshadowに残して見送る(self) -> None:
        """戦略ごとの採用後に重複を検出し全Q発動の記録を消さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [price(n) for n in range(5)]
        h15, h60 = higher_pair()
        base = {**frames[-1], **request(), "index": 4, "入口ID": "1分_Q1_なし", "入口系統": "Q1",
                "イベントID": "元Q1", "QイベントID": "Q1", "要求時計秒": frames[-1]["confirm"],
                "要求原板行": frames[-1]["confirm_line"]}
        for side in (1, -1):
            second = {**base, "side": side, "方向": "買い" if side == 1 else "売り", "役割": "反転",
                "入口系統": "Q2", "入口ID": "1分_Q2_なし", "イベントID": "元Q2", "QイベントID": "Q2"}
            generated = {"1分_Q1_なし": [base], "1分_Q2_なし": [second],
                         "1分_Q1_15分方向一致": [], "1分_Q2_15分方向一致": []}
            with patch.object(I.Q, "generate", return_value=(deepcopy(generated), {})):
                groups, quality = I.generate(frames, h15, h60, "2026-11-04_Day", 10000, 20000, config(), {})
            self.assertEqual(len(quality["全Q発動記録"]), 2)
            self.assertEqual(groups["1分_S0"], [])
            self.assertEqual(len(groups["1分_B1"]), 1)
            self.assertEqual(len(groups["1分_B2"]), 1)
            self.assertTrue(all(r["戦略判定"]["S0"]["同時競合"] for r in quality["全Q発動記録"]))
            self.assertNotIn("戦略判定", base)


# ----------------------------------------
# 実新規後の返済BBOで一呼値正益を観測したら全出口を最低同値から追尾する。

class 混合追尾検証(unittest.TestCase):
    """必須追尾・丸め・初着・費用赤字・実新規役割の固定を検査する。"""

    def test_追尾起動は5固定で距離だけ入口ATR切上げ(self) -> None:
        """撤回済み0.5ATR起動を使わず全ATRでA5にする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for atr, expected in ((.1, (5, 5)), (5, (5, 5)), (5.01, (5, 10)), (31, (5, 35)), (100, (5, 100))):
            self.assertEqual(O.trail_parameters(atr), expected)
        for atr in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                O.trail_parameters(atr)

    def test_三出口とも5ptで同値起動し等号初着後一秒BBO返済(self) -> None:
        """同値の設定を同値約定や純損失なしという保証へ読み替えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for policy in ("X0", "X1", "X2"):
            state, info = replay(policy, [quote(0, 1), quote(1, 2), quote(2, 3, 1010),
                quote(3, 4, 1005), quote(3, 5, 1005), quote(4, 6, 1005)])
            trade = state.trades[0]
            self.assertTrue(trade["必須追尾使用"])
            self.assertEqual(trade["追尾起動幅pt"], 5)
            self.assertEqual(trade["追尾起動時計秒"], 2)
            self.assertEqual(trade["最終追尾価格"], 1005)
            self.assertEqual(trade["返済理由"], "必須利益追尾")
            self.assertEqual(trade["返済要求時計秒"], 3)
            self.assertEqual(trade["返済時計秒"], 4)
            self.assertEqual(trade["基準純損益円"], -22)
            self.assertTrue(trade["起動後純赤字"])
            self.assertEqual(info["起動後純赤字取引数"], 1)

    def test_売りも買いと対称で新規Bid返済Askを使う(self) -> None:
        """売りの有利方向を逆にしAsk側の初着を判定する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X0", [quote(0, 1), quote(1, 2), quote(2, 3, 990),
                          quote(3, 4, 995), quote(4, 5, 995)], [request(-1)])
        trade = state.trades[0]
        self.assertEqual((trade["新規価格"], trade["返済価格"], trade["最終追尾価格"]), (1000, 1000, 1000))
        self.assertEqual(trade["返済要求時計秒"], 3)
        self.assertEqual(trade["基準純損益円"], -22)

    def test_買ceil売floorの有利側丸めと非緩和(self) -> None:
        """原値が呼値間でも保護線を利益側へ丸め高低の後退で緩めない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            state = O.切替状態("2026-11-04_Day", "人工丸め", config()["運用"], {"出口ID": "X0"}, "混合", [request(side, atr=31)], (0, 100, 80, 90))
            state.signal_group([request(side, atr=31)])
            state.quote(1, 2, 1000, 1005)
            if side == 1:
                state.quote(2, 3, 1042, 1047)
                self.assertEqual(state.position["trail_stop"], 1010)
                state.quote(3, 4, 1035, 1040)
                self.assertEqual(state.position["trail_stop"], 1010)
            else:
                state.quote(2, 3, 958, 963)
                self.assertEqual(state.position["trail_stop"], 995)
                state.quote(3, 4, 965, 970)
                self.assertEqual(state.position["trail_stop"], 995)
            self.assertIsNone(state.pending)

    def test_新規前高値と公開足高値で追尾を起動しない(self) -> None:
        """実新規後の正常返済BBOだけをMFEに用いる。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X0", [quote(0, 1, 1200), quote(1, 2), quote(2, 3)],
                          frames=[native_bar(2, 3, high=2000, S1局面="トレンド", S1方向=-1)])
        self.assertFalse(state.trades[0]["追尾起動"])
        self.assertEqual(state.trades[0]["返済理由"], "期限")

    def test_5pt未満の正益ではまだ起動しない(self) -> None:
        """起動等号の手前を0埋めや四捨五入で繰り上げない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X0", [quote(0, 1), quote(1, 2), quote(2, 3, 1009.999), quote(3, 4, 1000)])
        self.assertFalse(state.trades[0]["追尾起動"])
        self.assertEqual(state.trades[0]["返済理由"], "期限")

    def test_追尾は通常線より先に要求し既pendingを上書きしない(self) -> None:
        """同一quoteで二条件到達しても追尾を優先しbarの起算変更も抑止する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X2", [quote(0, 1), quote(1, 2), quote(2, 3, 1010), quote(3, 4, 990), quote(4, 5, 985)],
            [request(native=990)], [native_bar(3, 4, 1100, 補助epoch=1)])
        self.assertEqual(state.trades[0]["返済理由"], "必須利益追尾")
        self.assertEqual(state.epoch_requests, 0)

    def test_hard125と250および期限は追尾より先(self) -> None:
        """既起動後の大きな不利gapでも125保護を先に記録する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        cases = [([quote(0, 1), quote(1, 2), quote(2, 3, 1010), quote(3, 4, 880), quote(4, 5, 875)], "保護"),
                 ([quote(0, 1), quote(1, 2), quote(2, 3, 1255), quote(3, 4, 1250)], "利確"),
                 ([quote(0, 1), quote(1, 2), quote(2, 3, 1010), quote(90, 4, 1005), quote(91, 5, 1000)], "期限")]
        for quotes, reason in cases:
            state, _ = replay("X0", quotes)
            self.assertEqual(state.trades[0]["返済理由"], reason)

    def test_追尾価格を跳び越す返済は不利BBOと純赤字を残す(self) -> None:
        """床より下の要求/約定気配を床価格で架空補正しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X0", [quote(0, 1), quote(1, 2), quote(2, 3, 1010), quote(3, 4, 990), quote(4, 5, 985)])
        trade = state.trades[0]
        self.assertEqual(trade["返済価格"], 985)
        self.assertEqual(trade["基準純損益円"], -222)
        self.assertEqual(trade["最終追尾から実返済方向差pt"], -20)
        self.assertTrue(any(r["動作"] == "起動済み純赤字約定" for r in state.normal_log))

    def test_混合の実新規役割を保持し抑止signalで入れ替えない(self) -> None:
        """順行→反転を別の実建玉として扱い保有中局面だけで退出しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        signals = [request(native=990), request(role="反転", native=1020, イベントID="抑止反転", 要求時計秒=2, 要求原板行=3),
            request(role="反転", native=1020, イベントID="次の反転", 要求時計秒=4, 要求原板行=5)]
        quotes = [quote(0, 1), quote(1, 2), quote(2, 3, 1000), quote(3, 4, 990),
                  quote(4, 5, 995), quote(5, 6), quote(6, 7, 1020), quote(7, 8, 1025)]
        state, _ = replay("X1", quotes, signals, [native_bar(2, 3, 990, S1局面="レンジ", S1方向=0)])
        self.assertEqual([t["入口役割"] for t in state.trades], ["順行", "反転"])
        self.assertEqual([t["返済理由"] for t in state.trades], ["VWAP通常逆抜け", "VWAP通常到達"])
        self.assertEqual([t["返済要求時計秒"] for t in state.trades], [3, 6])
        self.assertEqual(state.signals[1]["取扱"], "建玉中抑止")

    def test_同方向二信号も両方向二信号も全見送り(self) -> None:
        """先頭だけ注文せず曖昧な重複を一建玉模型へ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            state, info = replay("X0", [quote(0, 1), quote(1, 2)],
                [request(), request(side, "反転", イベントID="競合入口")])
            self.assertEqual(state.orders, [])
            self.assertEqual(state.trades, [])
            self.assertEqual(info["同判断複数見送り数"], 2)

    def test_pending中とTP要求済みは追尾の起動更新を止める(self) -> None:
        """返済要求後のMFE上昇を遡って追尾起動した記録にしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        state, _ = replay("X1", [quote(0, 1), quote(1, 2), quote(1.5, 3, 1100), quote(2, 4, 1100)],
                          [request(native=1005)])
        self.assertEqual(state.trades[0]["返済理由"], "VWAP通常逆抜け")
        self.assertFalse(state.trades[0]["追尾起動"])
        self.assertEqual(state.trail_updates, 0)
        state, _ = replay("X0", [quote(0, 1), quote(1, 2), quote(2, 3, 1255), quote(3, 4, 1250)])
        self.assertEqual(state.trades[0]["観測最大順行pt"], 250)
        self.assertFalse(state.trades[0]["追尾起動"])

    def test_X2の同key更新と古いBBO非利用を継承(self) -> None:
        """追尾が未起動の経路でも同時計の別原行で通常初着を捏造しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for same, expected in ((True, 2), (False, 3)):
            state, _ = replay("X2", [quote(0, 1), quote(1, 2), quote(2, 3), quote(3, 5), quote(4, 6)],
                [request(native=990)], [native_bar(2, 3 if same else 4, 1002)])
            self.assertEqual(state.trades[0]["返済理由"], "VWAP通常逆抜け")
            self.assertEqual(state.trades[0]["返済要求時計秒"], expected)
            self.assertFalse(state.trades[0]["追尾起動"])

    def test_未起動経路は固定19の新規返済会計と一致(self) -> None:
        """新しい混合保護で役割や通常線の旧優先順を変えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for policy in ("X0", "X1", "X2"):
            quotes = [quote(0, 1), quote(1, 2), quote(2, 3, 995), quote(3, 4, 990), quote(4, 5, 990), quote(91, 6, 990)]
            signals = [request(native=990)]
            args = (quotes, signals, [], "2026-11-04_Day", "合成対照", config()["運用"], {"出口ID": policy}, "順行", (0, 100, 80, 90))
            current, info = O.replay(*deepcopy(args))
            previous, old_info = O.N.replay(*deepcopy(args))
            self.assertEqual(current.fills, previous.fills)
            self.assertEqual(current.orders, previous.orders)
            self.assertEqual(current.signals, previous.signals)
            self.assertEqual(info["観測現金増減円"], old_info["観測現金増減円"])
            self.assertFalse(current.trades[0]["追尾起動"])


class 定義連携検証(unittest.TestCase):
    """固定15入口/45運用/事前3分10表示と空足を確認する。"""

    def test_全15入口45運用と空足五戦略を残す(self) -> None:
        """入口尺度/戦略/出口の欠落や結果後の表示変更を防ぐ。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE/"検証.py", "局面切替合成のdriver")
        sources = driver.sources(config())
        self.assertEqual(len(sources), 15)
        self.assertEqual(len(sources)*len(config()["出口"]), 45)
        self.assertEqual(sum(r["時間足分"] == 3 for r in sources)*2, 10)
        for size in (1, 3, 5):
            groups, quality = driver.generate_or_empty([], [], [], "2026-11-04_Day", size, 10000, 20000, config(), {}, [])
            self.assertEqual(list(groups), [f"{size}分_{p}" for p in R.POLICIES])
            self.assertTrue(all(not values for values in groups.values()))
            self.assertEqual(quality["全Q発動記録"], [])
        changed = deepcopy(config())
        changed["複合条件"]["傾き下限"] = .03
        with self.assertRaises(ValueError):
            I.validate_config(changed)

    def test_実複合signalを一建玉へ接続し追尾往復費用まで完結(self) -> None:
        """人工価格の生成・選択・役割固定・Ask新規/Bid返済を連結する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [price(n, close=995) for n in range(5)]
        frames[-1]["close"] = 1005
        h15, h60 = higher_pair()
        refs = {n: {"配信VWAP": 1000., "配信3足前VWAP": 990., "N共通準備": True,
                    "native有効": True, "補助epoch": 0} for n in range(5)}
        groups, _ = I.generate(frames, h15, h60, "2026-11-04_Day", 7500, 11100, config(), refs)
        signal = groups["1分_S1"]
        self.assertEqual(len(signal), 1)
        quotes = [quote(3900, 2004, 1005), quote(3901, 2005, 1005), quote(3902, 2006, 1015),
                  quote(3903, 2007, 1010), quote(3904, 2008, 1005), quote(11101, 3000, 1005)]
        state, _ = O.replay(quotes, signal, [], "2026-11-04_Day", "実複合合成", config()["運用"],
                            {"出口ID": "X0"}, "混合", (3600, 11200, 7500, 11100))
        trade = state.trades[0]
        self.assertEqual((trade["新規価格"], trade["返済価格"]), (1010, 1005))
        self.assertEqual((trade["入口役割"], trade["返済理由"]), ("順行", "必須利益追尾"))
        self.assertEqual(trade["手数料円"], 22)
        self.assertEqual(trade["基準純損益円"], -72)
        self.assertIsNone(state.position)


# ----------------------------------------
# 開発中proofと編集終了proofを分け、固定後の追加は別ファイルへ保存する。

def main() -> None:
    """人工局面・選択・混合運用の合成を実行してproofを保存する。

    引数: なし。--finalは全編集終了後だけ指定する。
    返り値: None。失敗時は終了コード1。共有原板も市場成績も再生しない。
    """
    parser = argparse.ArgumentParser(description="テクニカル局面切替の人工合成")
    parser.add_argument("--final", action="store_true", help="編集終了時だけ固定用proofを保存")
    args = parser.parse_args()
    paths = [Path(__file__), HERE/"局面.py"]
    paths += [p for p in (HERE/"入口.py", HERE/"運用.py", HERE/"検証.py", STUDY/"条件.json") if p.exists()]
    pins = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if args.final and len(paths) != 6:
        raise ValueError("主4コード/合成/条件が揃う前には固定不可")
    if args.final and (STUDY/"固定.json").exists():
        frozen = json.loads((STUDY/"固定.json").read_text(encoding="utf-8"))["ファイルSHA256"]
        if any(frozen.get(name) != digest for name, digest in pins.items()):
            raise ValueError("固定後の追加は別ファイルへ分離する")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    proof = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
             "合成編集終了": bool(args.final and result.wasSuccessful()), "ファイルSHA256": pins,
             "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
             "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors],
             "範囲": "人工15分S1/S2・三尺度EMA/ATR・方向側RSI持続と急変・同場五本助走・60分公開原行・固定19Q同値・全shadow/競合・全45定義・混合役割固定・A5必須追尾の丸め/非緩和/1秒BBO/費用赤字・通常線/TP/SL/期限優先。原板も市場成績も再生しない。",
             "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k: proof[k] for k in ("全件成功", "検証件数", "合成編集終了")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
