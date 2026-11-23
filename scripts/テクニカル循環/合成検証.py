"""00011の固定幅対照・通常出口・実峰ATR保護を合成データで検証する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
import unittest


ROOT = Path(__file__).resolve().parents[2]
SESSION = "2026-10-01_Day"
BOUNDS = (0., 1000., 900., 950.)
CONFIG = {"数量": 1, "倍率": 10, "呼値pt": 5, "利確pt": 250, "保護逆行pt": 125,
          "片道手数料円": 11, "片道追加滑りpt": [0, 5, 10], "新規待機秒": 1,
          "新規有効秒": 30, "返済待機秒": 1, "正常板空白注意秒": 300}


def module(path: Path, name: str) -> Any:
    """合成検査対象を読み込む。

    引数: path (Path) はコード、name (str) は読込名。
    返り値: Any はモジュール。実データは読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


E = module(ROOT / "scripts/テクニカル循環/運用.py", "循環運用合成")


def signal(now: float = 0, line: int = 1, side: int = 1, event: str = "入口1",
           atr: float = 20, mean: float | None = 1300) -> dict:
    """入口ATRと固定中心を持つ合成要求を作る。

    引数: now (float) は要求秒、line (int) は原行、side (int) は方向、event (str) はID、
    atr (float) は固定ATR、mean (float|None) は入口中心。
    返り値: dict は合成入口。
    """
    return {"イベントID": event, "場": SESSION, "要求時計秒": now, "要求原板行": line,
            "方向": "買い" if side == 1 else "売り", "side": side, "確認遅延秒": 0,
            "atr": atr, "low": 980, "high": 1020, "bb_mean": mean}


def quote(now: float, line: int, bid: float, ask: float | None = None, valid: bool = True) -> Any:
    """合成の気配イベントを作る。

    引数: now (float) は価格時計、line (int) は原行、bid/ask (float|None) は気配、
    valid (bool) は正常性。Ask省略時はBid+5。
    返り値: Any は観測イベント。
    """
    return SimpleNamespace(now=now, line=line, bid=bid, ask=bid + 5 if ask is None else ask, valid=valid)


def frame(end: float = 2, confirm: float = 2, line: int = 3,
          close: float = 1000, ema: float | None = 1000, publish: bool = True) -> dict:
    """同尺度の確定足を作る。

    引数: end/confirm (float) は終了/公開秒、line (int) は公開原行、
    close (float) は終値、ema (float|None) はEMA、publish (bool) は確定公開。
    返り値: dict は合成足。
    """
    return {"end": end, "confirm": confirm, "confirm_line": line,
            "close": close, "ema20": ema, "publish": publish}


def entered(variant: str = "X1", role: str = "順行", side: int = 1,
            atr: float = 20, mean: float | None = 1300) -> Any:
    """価格1000で時刻1に新規済みの状態を作る。

    引数: variant/role (str) は出口と役割、side (int) は方向、atr (float) は入口ATR、
    mean (float|None) は固定中心。
    返り値: Any は新規約定後の状態。
    """
    row = signal(side=side, atr=atr, mean=mean)
    state = E.チャート状態(SESSION, "合成", deepcopy(CONFIG), {"出口ID": variant}, role, [row], BOUNDS)
    state.signal_group([row])
    state.quote(1, 2, 995 if side == 1 else 1000, 1000 if side == 1 else 1005)
    return state


# ----------------------------------------
# 固定TP/SLと通常出口、保存メタと旧対照の同値。

class 通常出口検証(unittest.TestCase):
    """固定幅対照と役割別通常出口を検査する。"""

    def test_X0は二百五十等号で利確(self) -> None:
        """固定幅対照だけが250pt等号で要求する。

        引数: なし。
        返り値: None。
        """
        state = entered("X0")
        state.quote(2, 3, 1250, 1255)
        self.assertEqual(state.pending["reason"], "利確")

    def test_X1X2は二百五十を越えても固定TPなし(self) -> None:
        """通常出口型を固定TPで頭打ちにしない。

        引数: なし。
        返り値: None。
        """
        for variant in ("X1", "X2"):
            for side in (1, -1):
                with self.subTest(variant=variant, side=side):
                    state = entered(variant, side=side)
                    state.quote(2, 3, 1300 if side == 1 else 695, 1305 if side == 1 else 700)
                    self.assertIsNone(state.pending)
                    state.bar(frame(3, 3, 4))
                    self.assertEqual(state.pending["reason"], "確定足EMA20失効")
                    state.quote(4, 5, 1290 if side == 1 else 705, 1295 if side == 1 else 710)
                    self.assertFalse(state.trades[0]["固定利確使用"])
                    self.assertIsNone(state.trades[0]["利確価格"])

    def test_全出口の非常保護は百二十五等号(self) -> None:
        """通常出口型にも初期125pt保護を残す。

        引数: なし。
        返り値: None。
        """
        for variant in ("X0", "X1", "X2"):
            for side in (1, -1):
                with self.subTest(variant=variant, side=side):
                    state = entered(variant, side=side)
                    state.quote(2, 3, 875 if side == 1 else 1120, 880 if side == 1 else 1125)
                    self.assertEqual(state.pending["reason"], "保護")

    def test_順行EMA等号は買売とも失効(self) -> None:
        """X1/X2はEMAの反対側だけでなく等号も出口とする。

        引数: なし。
        返り値: None。
        """
        for variant in ("X1", "X2"):
            for side in (1, -1):
                with self.subTest(variant=variant, side=side):
                    state = entered(variant, side=side)
                    state.bar(frame(close=1000, ema=1000))
                    self.assertEqual(state.pending["reason"], "確定足EMA20失効")

    def test_順行EMA有利側と欠測は失効しない(self) -> None:
        """有利な終値と未準備EMAを失効に変えない。

        引数: なし。
        返り値: None。
        """
        for side, close in ((1, 1005), (-1, 995)):
            state = entered(side=side)
            state.bar(frame(close=close))
            self.assertIsNone(state.pending)
            state.bar(frame(3, 3, 4, ema=None))
            self.assertIsNone(state.pending)

    def test_入口以前終了足と公開遅延超過を除く(self) -> None:
        """保有前に終わった足・未確定足・30秒超遅延を使わない。

        引数: なし。
        返り値: None。
        """
        for item in (frame(1, 2, 3), frame(publish=False), frame(2, 32.1, 3)):
            state = entered()
            state.bar(item)
            self.assertIsNone(state.pending)
        state = entered()
        state.bar(frame(2, 32, 3))
        self.assertEqual(state.pending["reason"], "確定足EMA20失効")

    def test_反転は構造破れやEMAで返済しない(self) -> None:
        """00010の構造出口を反転のX1/X2へ引き継がない。

        引数: なし。
        返り値: None。
        """
        for variant in ("X1", "X2"):
            state = entered(variant, role="反転")
            state.bar(frame(close=900, ema=1000))
            self.assertIsNone(state.pending)

    def test_中心有利側は返済BBO等号で到達(self) -> None:
        """買いBid・売りAskが中心へ届いた時点で要求する。

        引数: なし。
        返り値: None。
        """
        for side, mean, bid, ask in ((1, 1020, 1020, 1025), (-1, 980, 975, 980)):
            state = entered(role="反転", side=side, mean=mean)
            state.quote(2, 3, bid, ask)
            self.assertEqual(state.pending["reason"], "入口時中心線目標")

    def test_中心超過新規は初回気配で即要求(self) -> None:
        """新規価格が中心を越えた場合は返済気配が未達でも要求する。

        引数: なし。
        返り値: None。
        """
        for variant in ("X1", "X2"):
            for side, mean in ((1, 998), (-1, 1002), (1, 1000), (-1, 1000)):
                with self.subTest(variant=variant, side=side, mean=mean):
                    state = entered(variant, role="反転", side=side, mean=mean)
                    self.assertEqual(state.pending["reason"], "中心線超過新規")
                    self.assertEqual(state.pending["time"], 1)
                    self.assertEqual(state.pending["line"], 2)
                    self.assertEqual(state.center_crossed_entries, 1)
                    self.assertEqual(len(state.trades), 0)
                    state.quote(1, 3, 990, 995)
                    self.assertEqual(len(state.trades), 0)
                    state.quote(2, 4, 990, 995)
                    self.assertEqual(state.trades[0]["返済時計秒"], 2)
                    self.assertTrue(state.trades[0]["中心線超過新規"])

    def test_中心超過新規でも非常保護が先(self) -> None:
        """広いスプレッドが125ptに達する新規は保護理由を優先する。

        引数: なし。
        返り値: None。
        """
        row = signal(mean=1000)
        state = E.チャート状態(SESSION, "合成", CONFIG, {"出口ID": "X2"}, "反転", [row], BOUNDS)
        state.signal_group([row])
        state.quote(1, 2, 875, 1000)
        self.assertEqual(state.pending["reason"], "保護")
        self.assertEqual(state.center_crossed_entries, 1)

    def test_反転中心を約定後に更新しない(self) -> None:
        """後日の特徴値で固定中心を動かさない。

        引数: なし。
        返り値: None。
        """
        state = entered(role="反転", mean=1020)
        state.features["入口1"]["bb_mean"] = 1200
        state.quote(2, 3, 1020, 1025)
        self.assertEqual(state.pending["reason"], "入口時中心線目標")
        self.assertEqual(state.position["center"], 1020)

    def test_反転中心欠測と非有限を拒否(self) -> None:
        """X1/X2の反転入口に中心なしの取引を作らない。

        引数: なし。
        返り値: None。
        """
        for mean in (None, float("nan"), float("inf")):
            with self.subTest(mean=mean), self.assertRaises(ValueError):
                entered(role="反転", mean=mean)

    def test_X0は元010の完結会計と同値(self) -> None:
        """追加出口を外したX0の約定・注文・既存取引列を固定模型へ照合する。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            events = [quote(0, 1, 995 if side == 1 else 1000),
                      quote(1, 2, 995 if side == 1 else 1000),
                      quote(2, 3, 1250 if side == 1 else 745),
                      quote(3, 4, 1240 if side == 1 else 755)]
            old, old_info = E.M.replay(events, [signal(side=side)], [], SESSION, "同一", CONFIG, {"出口ID": "X0"}, "順行", BOUNDS)
            state, info = E.replay(events, [signal(side=side)], [frame()], SESSION, "同一", CONFIG, {"出口ID": "X0"}, "順行", BOUNDS)
            self.assertEqual(state.fills, old.fills)
            self.assertEqual(state.orders, old.orders)
            for actual, expected in zip(state.trades, old.trades):
                self.assertEqual({k: actual[k] for k in expected}, expected)
                self.assertTrue(actual["固定利確使用"])
                self.assertIsNotNone(actual["利確価格"])
            for key, value in old_info.items():
                self.assertEqual(info[key], value)


# ----------------------------------------
# 実返済BBO峰からの順行2ATR追尾と、反転1ATR起動・0.5ATR床。

class ATR保護検証(unittest.TestCase):
    """負値の実峰・単調保護・鏡像と不利な約定を検査する。"""

    def test_実新規の負峰で幻の即返済を避ける(self) -> None:
        """初期MFE0を実在した返済価格の峰と誤読しない。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            state = entered("X2", side=side, atr=1)
            self.assertEqual(state.position["mfe"], 0)
            self.assertEqual(state.position["observed_peak"], -5)
            self.assertEqual(state.position["trailing"], 990 if side == 1 else 1010)
            self.assertIsNone(state.pending)

    def test_負峰のまま改善しても実値で追尾(self) -> None:
        """建値にまだ届かない正常板の実最高値を使う。

        引数: なし。
        返り値: None。
        """
        row = signal(atr=1)
        state = E.チャート状態(SESSION, "合成", CONFIG, {"出口ID": "X2"}, "順行", [row], BOUNDS)
        state.signal_group([row])
        state.quote(1, 2, 990, 1000)
        self.assertEqual(state.position["observed_peak"], -10)
        self.assertEqual(state.position["trailing"], 985)
        state.quote(2, 3, 995, 1000)
        self.assertEqual(state.position["observed_peak"], -5)
        self.assertEqual(state.position["trailing"], 990)
        self.assertIsNone(state.pending)

    def test_順行二ATR追尾は買売で後退しない(self) -> None:
        """実峰の上昇と反落を通り保護線を緩めない。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            state = entered("X2", side=side, atr=20)
            if side == 1:
                values = [(2, 3, 1060, 1065), (3, 4, 1050, 1055), (4, 5, 1020, 1025)]
                expected = 1020
            else:
                values = [(2, 3, 935, 940), (3, 4, 945, 950), (4, 5, 975, 980)]
                expected = 980
            state.quote(*values[0])
            self.assertEqual(state.position["trailing"], expected)
            state.quote(*values[1])
            self.assertEqual(state.position["trailing"], expected)
            state.quote(*values[2])
            self.assertEqual(state.pending["reason"], "2ATR追尾保護")

    def test_二ATRが大きくても初期保護を広げない(self) -> None:
        """入口ATRが大きい場合も初期125pt保護より緩めない。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            state = entered("X2", side=side, atr=100)
            self.assertEqual(state.position["trailing"], 875 if side == 1 else 1125)

    def test_追尾要求後も一秒待機し不利BBOで返済(self) -> None:
        """追尾水準を約定価格として使わない。

        引数: なし。
        返り値: None。
        """
        state = entered("X2", atr=20)
        state.quote(2, 3, 1060, 1065)
        state.quote(3, 4, 1020, 1025)
        state.quote(3, 5, 1010, 1015)
        self.assertEqual(len(state.trades), 0)
        state.quote(4, 6, 990, 995)
        self.assertEqual(state.trades[0]["返済価格"], 990)
        self.assertEqual(state.trades[0]["基準純損益円"], -122)

    def test_非常保護が順行追尾より優先(self) -> None:
        """同一気配で125ptも越えたら元保護理由を優先する。

        引数: なし。
        返り値: None。
        """
        state = entered("X2")
        state.quote(2, 3, 1060, 1065)
        state.quote(3, 4, 875, 880)
        self.assertEqual(state.pending["reason"], "保護")

    def test_反転一ATR未満は床なし等号から起動(self) -> None:
        """反転の利益床起動値を順行追尾と混ぜない。

        引数: なし。
        返り値: None。
        """
        state = entered("X2", role="反転", mean=1300, atr=20)
        state.quote(2, 3, 1015, 1020)
        state.quote(3, 4, 1010, 1015)
        self.assertFalse(state.position["armed"])
        self.assertIsNone(state.pending)
        state.quote(4, 5, 1020, 1025)
        self.assertTrue(state.position["armed"])
        state.quote(5, 6, 1010, 1015)
        self.assertEqual(state.pending["reason"], "反転ATR利益床")

    def test_反転床の小数ATR丸めと鏡像(self) -> None:
        """0.5ATRを買い下丸め・売り上丸めした等号で要求する。

        引数: なし。
        返り値: None。
        """
        for side, mean in ((1, 1300), (-1, 700)):
            state = entered("X2", role="反転", side=side, mean=mean, atr=17.5)
            state.quote(2, 3, 1020 if side == 1 else 975, 1025 if side == 1 else 980)
            state.quote(3, 4, 1010 if side == 1 else 985, 1015 if side == 1 else 990)
            self.assertIsNone(state.pending)
            state.quote(4, 5, 1005 if side == 1 else 990, 1010 if side == 1 else 995)
            self.assertEqual(state.pending["reason"], "反転ATR利益床")

    def test_反転中心が追加保護より先の通常目標(self) -> None:
        """中心へ到達した気配で通常目標理由を記録する。

        引数: なし。
        返り値: None。
        """
        state = entered("X2", role="反転", mean=1020, atr=20)
        state.quote(2, 3, 1020, 1025)
        self.assertEqual(state.pending["reason"], "入口時中心線目標")

    def test_入口ATRの後日書換えは保護を変えない(self) -> None:
        """新規時のATRだけで2ATR線を作り続ける。

        引数: なし。
        返り値: None。
        """
        state = entered("X2", atr=20)
        state.features["入口1"]["atr"] = 200
        state.quote(2, 3, 1060, 1065)
        self.assertEqual(state.position["atr_entry"], 20)
        self.assertEqual(state.position["trailing"], 1020)

    def test_次の建玉へ前の実峰を持ち越さない(self) -> None:
        """再参加時に実峰と追尾線を初返済気配から作り直す。

        引数: なし。
        返り値: None。
        """
        first, second = signal(), signal(4, 6, event="入口2")
        state = E.チャート状態(SESSION, "合成", CONFIG, {"出口ID": "X2"}, "順行", [first, second], BOUNDS)
        state.signal_group([first])
        state.quote(1, 2, 995, 1000)
        state.quote(2, 3, 1060, 1065)
        state.quote(3, 4, 1020, 1025)
        state.quote(4, 5, 1010, 1015)
        self.assertIsNone(state.position)
        state.signal_group([second])
        state.quote(5, 7, 995, 1000)
        self.assertEqual(state.position["observed_peak"], -5)
        self.assertEqual(state.position["trailing"], 955)
        self.assertIsNone(state.pending)


# ----------------------------------------
# 原行の同時順序、期限、入力防御と既存会計の保存。

class 再生時点検証(unittest.TestCase):
    """気配・確定足・新規要求の順序を検査する。"""

    def test_価格の非常保護は同原行のEMAより先(self) -> None:
        """価格出口の要求を後続足出口で上書きしない。

        引数: なし。
        返り値: None。
        """
        events = [quote(0, 1, 995), quote(1, 2, 995), quote(2, 3, 875), quote(3, 4, 870)]
        state, _ = E.replay(events, [signal()], [frame()], SESSION, "合成", CONFIG, {"出口ID": "X1"}, "順行", BOUNDS)
        self.assertEqual(state.trades[0]["返済理由"], "保護")

    def test_同原行の足は新規要求より先(self) -> None:
        """未保有の足を同原行で新規した建玉の出口に使わない。

        引数: なし。
        返り値: None。
        """
        events = [quote(2, 3, 995), quote(3, 4, 995)]
        state, _ = E.replay(events, [signal(2, 3)], [frame()], SESSION, "合成", CONFIG, {"出口ID": "X1"}, "順行", BOUNDS)
        self.assertFalse(any(o["理由"] == "確定足EMA20失効" for o in state.orders))
        self.assertEqual(state.fills[0]["price_clock"], 3)

    def test_EMA要求時計と返済時計を分ける(self) -> None:
        """足での返済要求も一秒後の最初正常板へ待つ。

        引数: なし。
        返り値: None。
        """
        events = [quote(0, 1, 995), quote(1, 2, 995), quote(2, 3, 995), quote(2, 4, 990), quote(3, 5, 985)]
        state, _ = E.replay(events, [signal()], [frame()], SESSION, "合成", CONFIG, {"出口ID": "X1"}, "順行", BOUNDS)
        self.assertEqual(state.trades[0]["返済要求時計秒"], 2)
        self.assertEqual(state.trades[0]["返済時計秒"], 3)
        self.assertEqual(state.trades[0]["返済価格"], 985)

    def test_期限は他出口より優先し原行ゼロで予約(self) -> None:
        """期限予約を追加追尾や足出口へ置き換えない。

        引数: なし。
        返り値: None。
        """
        state = entered("X2")
        state.quote(950, 3, 990, 995)
        self.assertEqual(state.pending["reason"], "期限")
        self.assertEqual(state.pending["time"], 950)
        self.assertEqual(state.pending["line"], 0)
        state.quote(951, 4, 985, 990)
        self.assertEqual(state.trades[0]["返済理由"], "期限")

    def test_入口重複別場方向不正を拒否(self) -> None:
        """元の入口所有検査を維持する。

        引数: なし。
        返り値: None。
        """
        for rows in ([signal(), signal()], [dict(signal(), 場="別場")], [dict(signal(), side=0)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                E.replay([], rows, [], SESSION, "合成", CONFIG, {"出口ID": "X0"}, "順行", BOUNDS)

    def test_足終了前公開と正常フラグ矛盾を拒否(self) -> None:
        """不正な足と不正な正常気配を時点検査で止める。

        引数: なし。
        返り値: None。
        """
        for events, frames in (([], [frame(3, 2, 1)]), ([quote(0, 1, 1000, 995)], [])):
            with self.subTest(events=events), self.assertRaises(ValueError):
                E.replay(events, [], frames, SESSION, "合成", CONFIG, {"出口ID": "X0"}, "順行", BOUNDS)

    def test_時計後退を除外して品質件数を残す(self) -> None:
        """不正板を含めた価格時計の高値から後退を判定する。

        引数: なし。
        返り値: None。
        """
        events = [quote(0, 1, 995), quote(1, 2, 995), quote(.5, 3, 875), quote(2, 4, 1250), quote(3, 5, 1240)]
        state, info = E.replay(events, [signal()], [], SESSION, "合成", CONFIG, {"出口ID": "X0"}, "順行", BOUNDS)
        self.assertEqual(info["時計後退除外数"], 1)
        self.assertEqual(state.trades[0]["返済理由"], "利確")

    def test_時価DDは将来返済料を含み実新規から追う(self) -> None:
        """0,-72,178,78,-222円の実経路を手計算する。

        引数: なし。
        返り値: None。
        """
        state = entered("X1")
        self.assertEqual(state.equity_low, -72)
        state.quote(2, 3, 1020, 1025)
        state.quote(3, 4, 1010, 1015)
        state.bar(frame(3, 3, 4))
        state.quote(4, 5, 980, 985)
        self.assertEqual(state.equity_peak, 178)
        self.assertEqual(state.equity_low, -222)
        self.assertEqual(state.max_drawdown, 400)
        self.assertEqual(state.cash, -222)


def run() -> dict:
    """合成検査だけを実行し明示合否と版指紋を保存する。

    引数: なし。実データ・探索結果は読まない。
    返り値: dict は件数・失敗・エラー・コードSHA。
    """
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "対象運用SHA256": hashlib.sha256((ROOT / "scripts/テクニカル循環/運用.py").read_bytes()).hexdigest(),
              "合成コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "失敗": [{"検査": str(t), "内容": text} for t, text in result.failures],
              "エラー": [{"検査": str(t), "内容": text} for t, text in result.errors],
              "範囲": "運用合成のみ。X0旧対照、X1/2固定TPなし・EMA等号、中心超過、実負峰2ATR、反転ATR床、優先順、実約定待機、入力防御・DD。",
              "実行記録": stream.getvalue()}
    path = ROOT / "work/テクニカル循環/合成検証.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(stream.getvalue())
    return report


if __name__ == "__main__":
    if not run()["全件成功"]:
        raise SystemExit(1)
