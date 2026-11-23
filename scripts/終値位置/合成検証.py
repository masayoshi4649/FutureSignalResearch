"""同時点CLVの二案を、人工値だけで境界・対称性・情報分離まで検査する。"""

from __future__ import annotations

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from fractions import Fraction
import gzip
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Iterator
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "work/終値位置"
SESSION = "人工終値位置場"


def normalized(path: object) -> str:
    """市場資料へ触れず比較用の絶対表記を作る。

    引数: path(object)はパス又は記述子。
    返り値: strは正規表記。非パスなら空文字。
    """
    try:
        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError):
        return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """実原板/cache/実圧縮明細をstat/open前に遮断する。

    引数: なし。
    返り値: Iterator[None]は人工一時先とコードだけ使える範囲。
    """
    raw, work = normalized(ROOT.parent / "JP_OSE_Data"), normalized(ROOT / "work")
    old_open, old_path_open, old_stat = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """実市場資料への接近を拒否する。

        引数: path(object)は対象。
        返り値: None。人工tempの圧縮明細だけを許可する。
        """
        name = normalized(path)
        inside = name.startswith(work + os.sep)
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("終値位置33合成_")
        if name == raw or name.startswith(raw + os.sep) or inside and (name.endswith(".npz") or not artificial and name.endswith((".jsonl.gz", ".trades.jsonl"))):
            raise AssertionError("合成から実原板/cache/明細へ触れない:" + str(path))

    def opened(path: object, *args: object, **kwargs: object) -> Any:
        """通常openへ読取禁止を適用する。

        引数: path(object)は対象、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
        """
        check(path)
        return old_open(path, *args, **kwargs)

    def path_opened(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.openへ読取禁止を適用する。

        引数: path(Path)は対象、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
        """
        check(path)
        return old_path_open(path, *args, **kwargs)

    def stated(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.statへ読取禁止を適用する。

        引数: path(Path)は対象、args/kwargs(object)は元引数。
        返り値: Anyは許可されたメタデータ。
        """
        check(path)
        return old_stat(path, *args, **kwargs)

    with patch.object(builtins, "open", opened), patch.object(Path, "open", path_opened), patch.object(Path, "stat", stated):
        yield


def load(path: Path, name: str) -> Any:
    """市場遮断下で定義だけを読む。

    引数: path(Path)はPython、name(str)はモジュール名。
    返り値: Anyは定義。CLIは起動しない。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
        return value


def sha(path: Path) -> str:
    """主コード/条件/独立補助の指紋を返す。

    引数: path(Path)はコード又は条件。
    返り値: strはSHA256。実市場を対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


I = load(HERE / "入口.py", "終値位置33合成の主入口")
J31 = load(ROOT / "scripts/CCI突破/指標.py", "終値位置33合成の既存CCI数値")
S = load(HERE / "状態独立確認.py", "終値位置33合成の独立CLV")
T = load(HERE / "追尾独立確認.py", "終値位置33合成の独立費用追尾")
O33 = load(HERE / "運用.py", "終値位置33合成の費用後起動")
OPERATION_CONFIG = json.loads((ROOT / "study/00031_CCI持続と上位BB幅/条件.json").read_text(encoding="utf-8"))["運用"]
BOUNDS = (0., 1000., 800., 900.)


def raw(index: int = 21, side: int = 1, high: float = 125., low: float = 115., close: float = 123.,
        accepted: bool = True, **updates: Any) -> dict:
    """単体検査用の人工原Pを作る。

    引数: index/side(int)は番号/方向、high/low/close(float)はOHLC、accepted(bool)は注入する旧C0採否、updates(Any)は上書き。
    返り値: dictは旧原P必要列。旧C0数式自体の反例は別に実CCIを使う。
    """
    event_id = f"人工_{index}_{side}"
    verdict = {"採用": accepted, "理由": ["旧C0採用"] if accepted else ["旧C0技術不可"], "同時競合": False}
    return {"場": SESSION, "index": index, "open": close, "high": high, "low": low, "close": close,
        "side": side, "方向": "買い" if side == 1 else "売り", "要求時計秒": float((index + 1) * 180),
        "要求原板行": 100 + index, "足終了時計秒": float((index + 1) * 180), "確認遅延秒": 0.,
        "共通M準備": True, "M除外理由": [], "時間条件可": True, "確認遅延条件可": True,
        "先着評価対象": True, "発動ID": event_id, "イベントID": event_id + "_C0", "入口ID": "3分_C0",
        "役割": "順行", "atr": 25., "直前最高H": 120., "直前最安L": 110.,
        "前3分参照": {"atr": 20.}, "戦略判定": {"C0": verdict, "C1": deepcopy(verdict)},
        "CCI現": {"分子": 120, "分母": 1, "有効": True},
        "CCI前": {"分子": 120, "分母": 1, "有効": True}, "BB幅比較厳密符号": 1, **updates}


def reflect(row: dict, center: float = 300.) -> dict:
    """高安/基準線/方向を交換して正価格の鏡像を作る。

    引数: row(dict)は人工原P、center(float)は価格の和。
    返り値: dictは独立した鏡像。
    """
    out = deepcopy(row)
    out.update(open=center - row["open"], high=center - row["low"], low=center - row["high"],
        close=center - row["close"], side=-row["side"], 方向="買い" if row["side"] == -1 else "売り",
        直前最高H=center - row["直前最安L"], 直前最安L=center - row["直前最高H"])
    return out


def block(rows: list[dict]) -> dict:
    """全人工rawと旧C0採用信号を別に持つ場材料を作る。

    引数: rows(list[dict])は人工原P。
    返り値: dictは主selectへ渡す非PnL材料。
    """
    return {"quality": {"全Q発動記録": deepcopy(rows)},
        "signals": {"3分_C0": [deepcopy(r) for r in rows if r["戦略判定"]["C0"]["採用"]]}}


class ShapeTests(unittest.TestCase):
    """人工OHLCだけで形状と採否の追加差を確認する。"""

    def test_positive_negative_zero_and_width_zero(self) -> None:
        """正/負/0/未定義を別にし、T0を維持する。

        引数: なし。
        返り値: None。幅0はT1だけ技術不可。
        """
        fixtures = ((125., 115., 123., Fraction(3, 5), True), (125., 115., 117., Fraction(-3, 5), False),
            (125., 115., 120., Fraction(0), False), (123., 123., 123., None, False))
        for high, low, close, expected, adopted in fixtures:
            actual = I.shape(raw(high=high, low=low, close=close))
            self.assertEqual(actual["CLV"], I.ratio(expected))
            self.assertTrue(actual["T0採用"])
            self.assertEqual(actual["T1採用"], adopted)
        zero = I.shape(raw(high=123., low=123., close=123.))
        self.assertEqual(zero["CLV"], {"値": None, "分子": None, "分母": None, "有効": False})
        self.assertEqual(zero["戦略判定"]["T1"]["理由"], ["現在足高安幅0"])

    def test_valid_cci_counterexample_and_reflection(self) -> None:
        """直前21足からCCI現前成立とCLV反対符号を同時に作る。

        引数: なし。
        返り値: None。人工数値だけで非冗長性と売買鏡像を確認する。
        """
        history = [{"index": n, "open": x, "high": x, "low": x, "close": x} for n, x in enumerate([100.] * 20 + [110.])]
        current = {"index": 21, "open": 110., "high": 200., "low": 100., "close": 120.}
        previous = J31.cci20(history[-20:])
        now = J31.cci20([*history[-19:], current])
        self.assertEqual(Fraction(previous["分子"], previous["分母"]), Fraction(2000, 3))
        self.assertEqual(Fraction(now["分子"], now["分母"]), Fraction(5000, 9))
        source = raw(**{k: current[k] for k in ("open", "high", "low", "close")}, 直前最高H=110., 直前最安L=100.)
        self.assertGreater(source["close"], source["直前最高H"])
        actual = I.shape(source)
        self.assertTrue(actual["T0採用"])
        self.assertFalse(actual["T1採用"])
        self.assertEqual(actual["CLV"], I.ratio(Fraction(-3, 5)))
        inverse = I.shape(reflect(source))
        self.assertEqual(inverse["CLV"], I.ratio(Fraction(3, 5)))
        self.assertEqual(actual["実方向CLV符号"], inverse["実方向CLV符号"])
        self.assertEqual(actual["T1採用"], inverse["T1採用"])

    def test_exact_sign_survives_float_display_underflow(self) -> None:
        """表示が0へ丸まっても元floatの精密比で採否を分ける。

        引数: なし。
        返り値: None。C0採否は単体前提として注入する。
        """
        source = raw(side=-1, high=1e308, low=math.ulp(0.), close=5e307,
            直前最高H=7e307, 直前最安L=6e307)
        actual = I.shape(source)
        self.assertEqual(actual["CLV"]["値"], 0.)
        self.assertLess(actual["CLV"]["分子"], 0)
        self.assertTrue(actual["T1採用"])

    def test_ulp_and_exact_zero(self) -> None:
        """1ULP前後のstrict符号と厳密等号を検査する。

        引数: なし。
        返り値: None。任意epsilonを使わない。
        """
        for close, sign in ((math.nextafter(2., -math.inf), -1), (2., 0), (math.nextafter(2., math.inf), 1)):
            row = I.shape(raw(high=3., low=1., close=close, 直前最高H=1.5, 直前最安L=1.))
            self.assertEqual(row["実方向CLV符号"], sign)
            self.assertEqual(row["T1採用"], sign == 1)

    def test_independent_formula_all_cases(self) -> None:
        """別実装の上下距離比と主の全CLV列を比較する。

        引数: なし。
        返り値: None。鏡像・端・中点・小数を人工だけで確認する。
        """
        for high, low, close in ((125., 115., 123.), (125., 115., 120.), (123., 123., 123.),
                                 (1.3, .9, 1.1), (3., 1., math.nextafter(2., math.inf))):
            source = raw(high=high, low=low, close=close)
            for value in (source, reflect(source, 300.)):
                actual = I.shape(value)["CLV"]
                self.assertEqual(actual, I.ratio(S.clv(value)))

    def test_independent_whole_shape(self) -> None:
        """独立の全形状/採否/診断を主と照合する。

        引数: なし。
        返り値: None。前ATRには人工の厳密値を使う。
        """
        for source in (raw(), raw(high=125., low=115., close=120.), raw(high=123., low=123., close=123.),
                       raw(accepted=False), reflect(raw())):
            self.assertEqual(I.shape(source), S.shape(source))

    def test_independent_selection_and_decision_projection(self) -> None:
        """独立の全raw採否と前ATR判断射影を主へ接続する。

        引数: なし。
        返り値: None。人工のCLV各群を同時計のまま比較する。
        """
        driver = driver_module()
        source = block([raw(index=21), raw(index=22, high=125., low=115., close=117.),
            raw(index=23, high=123., low=123., close=123.), raw(index=24, accepted=False)])
        main, independent = I.select(deepcopy(source)), S.select(deepcopy(source))
        self.assertEqual(main, independent)
        for row in main["shape_rows"]:
            self.assertEqual(driver.decision_shape(row), S.decision_shape(row))

    def test_previous_atr_is_diagnostic_only(self) -> None:
        """前ATRの欠測/不正/大きさが二採否へ介入しない。

        引数: なし。
        返り値: None。規格化距離の有効性だけが変わる。
        """
        source = raw()
        original = I.shape(source)["戦略判定"]
        for value in (None, 0., -1., math.nan, math.inf, 1., 10000.):
            candidate = deepcopy(source)
            candidate["前3分参照"] = {"atr": value}
            actual = I.shape(candidate)
            self.assertEqual(actual["戦略判定"], original)
            self.assertFalse(actual["診断"]["採否への使用"])

    def test_all_old_verdict_fields_are_preserved(self) -> None:
        """旧C0の採否/理由/同競合をT0へ全て残す。

        引数: なし。
        返り値: None。値条件で共通Mを変更しない。
        """
        for accepted, conflict, reasons in ((True, False, ["旧採用"]), (False, False, ["M不準備", "遅延超過"]), (False, True, ["同時競合"])):
            source = raw()
            source["戦略判定"]["C0"] = {"採用": accepted, "理由": reasons, "同時競合": conflict}
            before = deepcopy(source)
            actual = I.shape(source)
            self.assertEqual(actual["戦略判定"]["T0"], before["戦略判定"]["C0"])
            self.assertEqual(actual["共通M準備"], before["共通M準備"])
            self.assertEqual(source, before)

    def test_full_raw_population_and_same_time_consumption(self) -> None:
        """後足の改善を前の発動IDへ取り直さず、全rawを残す。

        引数: なし。
        返り値: None。T1の最初の不成立も形状行として保存する。
        """
        first = raw(index=21, high=125., low=115., close=117.)
        second, rejected = raw(index=22), raw(index=23, accepted=False)
        source = block([first, second, rejected])
        output = I.select(source)
        self.assertEqual(len(output["shape_rows"]), 3)
        self.assertEqual([r["イベントID"] for r in output["signals"]["3分_T0"]], [first["発動ID"] + "_T0", second["発動ID"] + "_T0"])
        self.assertEqual([r["イベントID"] for r in output["signals"]["3分_T1"]], [second["発動ID"] + "_T1"])
        selected = output["signals"]["3分_T1"][0]
        self.assertEqual((selected["要求時計秒"], selected["要求原板行"]), (second["要求時計秒"], second["要求原板行"]))

    def test_pure_signal_whitelist_and_snapshot(self) -> None:
        """将来列を捨て、二信号を別辞書として保持する。

        引数: なし。
        返り値: None。比較用保存caseを注入しても未来値を渡さない。
        """
        source = raw(ラベル="架空の未来成功", 新規価格=999999., 判定時計秒=999999., 最大順行pt=999999., 秘密列={"未来": True})
        left, right = I.pure_signal(source, "T0"), I.pure_signal(source, "T1")
        self.assertEqual(set(left), set(I.SIGNAL_FIELDS))
        self.assertEqual(set(right), set(I.SIGNAL_FIELDS))
        self.assertEqual(left["入口ID"], "3分_T0")
        self.assertEqual(right["イベントID"], source["発動ID"] + "_T1")
        left["atr"] = -100
        self.assertEqual(right["atr"], 25.)
        self.assertEqual(source["atr"], 25.)

    def test_reject_duplicate_or_incomplete_old_cases(self) -> None:
        """原発動重複や旧採用集合の欠落を拒否する。

        引数: なし。
        返り値: None。都合のよい一部だけをT0へ移さない。
        """
        source = raw()
        with self.assertRaises(ValueError):
            I.select(block([source, source]))
        candidate = block([source])
        candidate["signals"]["3分_C0"] = []
        with self.assertRaises(ValueError):
            I.select(candidate)
        with self.assertRaises(ValueError):
            I.pure_signal(source, "T2")

    def test_invalid_ohlc_and_side_rejected(self) -> None:
        """高安不整合・範囲外終値・無方向を拒否する。

        引数: なし。
        返り値: None。無効形状を有効0へ補完しない。
        """
        for source in (raw(high=100., low=110., close=105.), raw(high=120., low=110., close=130.), raw(side=0)):
            with self.assertRaises(ValueError):
                I.shape(source)


def driver_module() -> Any:
    """保存済み主driverの定義だけを読む。

    引数: なし。
    返り値: Anyは主モジュール。市場CLIは呼ばない。
    """
    return load(HERE / "検証.py", "終値位置33合成のdriver定義")


def operation_signal(side: int = 1) -> dict:
    """新規10000pt基準の当時情報だけを持つ人工信号を作る。

    引数: side(int)は買1/売-1。
    返り値: dictは共通運用へ渡す13列。
    """
    return {"場": SESSION, "イベントID": "人工費用入口", "入口ID": "3分_T0", "役割": "順行",
        "side": side, "方向": "買い" if side == 1 else "売り", "要求時計秒": 10., "要求原板行": 10,
        "確認遅延秒": 0., "low": 9990., "high": 10010., "atr": 25., "bb_mean": None}


def operation_event(now: float, line: int, side: int, profit: float) -> SimpleNamespace:
    """スプレッドを含む正常返済BBOを作る。

    引数: now/line(float/int)はkey、side(int)は保有方向、profit(float)は名目返済幅。
    返り値: SimpleNamespaceは新規10000ptからのbid/ask/validを持つ。
    """
    mark = 10000. + side * profit
    return SimpleNamespace(now=now, line=line, valid=True,
        bid=mark if side == 1 else mark - 5., ask=mark + 5. if side == 1 else mark)


def opened_cost(side: int = 1) -> Any:
    """1秒待機で新規約定した未起動XF状態を作る。

    引数: side(int)は方向。
    返り値: Anyは新規10000pt・MFE0・名目MAE5の人工状態。
    """
    source = operation_signal(side)
    state = O33.費用起動状態(SESSION, "人工_XF", deepcopy(OPERATION_CONFIG), {"出口ID": "XF"}, "順行", [source], BOUNDS)
    state.signal_group([source])
    event = operation_event(11., 11, side, -5.)
    state.quote(event.now, event.line, event.bid, event.ask)
    return state


def cost_quote(state: Any, now: float, line: int, profit: float) -> None:
    """人工名目利益を正常返済BBOとして処理する。

    引数: state(Any)はXF状態、now/line(float/int)はkey、profit(float)は名目利益pt。
    返り値: None。約定を必要待機前へ戻さない。
    """
    event = operation_event(now, line, state.position["side"], profit)
    state.quote(event.now, event.line, event.bid, event.ask)


class CostActivationTests(unittest.TestCase):
    """ユーザー指定の現在費用後strict正と旧A5対照を検査する。"""

    def test_strict_current_net_boundary_and_reference_cost(self) -> None:
        """12.2等号は不起動、次呼値15の現在利益はstrict正とする。

        引数: なし。
        返り値: None。参照滑りは感度列と独立の片道5。
        """
        self.assertEqual(O33.cost_parameters(OPERATION_CONFIG), (Fraction(122), Fraction(61, 5)))
        for side in (1, -1):
            for point, expected in ((5., False), (10., False), (12.2, False), (15., True), (20., True)):
                decision = O33.current_net(10000. + side * point, 10000., side, OPERATION_CONFIG)
                self.assertEqual(decision["strict正"], expected)
                self.assertEqual(decision["境界pt"], 12.2)
                self.assertEqual(decision["起動参照費用円"], 122.)
                if point == 12.2:
                    self.assertEqual(decision["控除後含み益円分子"], 0)
        for sensitivity in ([0], [5], [10], [0, 5, 10]):
            config = deepcopy(OPERATION_CONFIG); config["片道追加滑りpt"] = sensitivity
            self.assertEqual(O33.current_net(10015., 10000., 1, config)["控除後含み益円"], 28.)

    def test_initial_log_and_first_current_profit_activation(self) -> None:
        """初期化から正しい境界を保存し、現在BBOの15ptで初起動する。

        引数: なし。
        返り値: None。12.2は単体境界、実呼値へ閾値を固定丸めしない。
        """
        for side in (1, -1):
            state = opened_cost(side)
            initialization = next(r for r in state.normal_log if r["動作"] == "追尾初期化")
            self.assertEqual(initialization["建玉"]["trail_A"], 12.2)
            self.assertTrue(initialization["起動境界strict"])
            self.assertEqual(initialization["起動参照費用円"], 122.)
            for now, point in ((12., 5.), (13., 10.), (14., 12.2)):
                cost_quote(state, now, int(now), point)
                self.assertFalse(state.position["armed"])
                self.assertIsNone(state.position["trail_stop"])
            cost_quote(state, 15., 15, 15.)
            self.assertTrue(state.position["armed"])
            self.assertEqual(state.position["trail_stop"], 10000.)
            origin = state.position["cost_arm"]
            self.assertEqual((origin["価格時計秒"], origin["原板行"]), (15., 15))
            self.assertEqual(Fraction(origin["控除後含み益円分子"], origin["控除後含み益円分母"]), 28)
            self.assertEqual(origin["返済気配"], origin["元bid"] if side == 1 else origin["元ask"])

    def test_historical_mfe_alone_never_arms(self) -> None:
        """過去MFEが高くても現在費用後非正なら起動しない。

        引数: なし。
        返り値: None。MFEは起動後追尾だけの材料として残す。
        """
        state = opened_cost()
        state.position["mfe"] = 100.
        cost_quote(state, 12., 12, 5.)
        self.assertFalse(state.position["armed"])
        self.assertIsNone(state.position["cost_arm"])

    def test_activation_is_sticky_and_floor_is_nominal(self) -> None:
        """現在純益低下で解除せず、名目同値床と返済待機を維持する。

        引数: なし。
        返り値: None。同値返済は費用後黒字を保証しない。
        """
        for side in (1, -1):
            state = opened_cost(side)
            cost_quote(state, 12., 12, 15.)
            origin = deepcopy(state.position["cost_arm"])
            cost_quote(state, 13., 13, 10.)
            self.assertTrue(state.position["armed"])
            self.assertEqual(state.position["cost_arm"], origin)
            cost_quote(state, 14., 14, 0.)
            self.assertEqual(state.pending["reason"], "必須利益追尾")
            self.assertEqual(state.position["trail_stop"], 10000.)
            cost_quote(state, 14., 15, -5.)
            self.assertIsNotNone(state.pending)
            cost_quote(state, 15., 16, -5.)
            self.assertIsNone(state.position)
            trade = state.trades[-1]
            self.assertEqual(trade["追尾起動幅pt"], 12.2)
            self.assertTrue(trade["起動境界strict"])
            self.assertEqual(trade["起動判定出典"], origin)
            self.assertEqual(trade["起動参照片道滑りpt"], 5)
            self.assertLess(trade["基準純損益円"], 0)

    def test_nonrelax_and_pending_priority(self) -> None:
        """起動後のMFE-D非緩和とpendingでの起動禁止を確認する。

        引数: なし。
        返り値: None。待機中MFE観測は止めない。
        """
        state = opened_cost()
        cost_quote(state, 12., 12, 50.)
        self.assertEqual(state.position["trail_stop"], 10025.)
        cost_quote(state, 13., 13, 40.)
        self.assertEqual(state.position["trail_stop"], 10025.)
        other = opened_cost()
        other.request("返済", 1, 20., 20, "人工既存要求", "人工費用入口")
        cost_quote(other, 20., 21, 30.)
        self.assertFalse(other.position["armed"])
        self.assertIsNone(other.position["cost_arm"])
        self.assertEqual(other.position["mfe"], 30.)
        cost_quote(other, 21., 22, 30.)
        self.assertFalse(other.trades[-1]["追尾起動"])

    def test_hard_target_deadline_precede_cost_activation(self) -> None:
        """hard/TP/期限が費用起動より先に要求を固定する。

        引数: なし。
        返り値: None。高い含み益だけで先行要求を上書きしない。
        """
        for point, reason in ((-125., "保護"), (250., "利確")):
            state = opened_cost()
            cost_quote(state, 12., 12, point)
            self.assertEqual(state.pending["reason"], reason)
            self.assertFalse(state.position["armed"])
        state = opened_cost()
        cost_quote(state, 900., 900, 30.)
        self.assertEqual(state.pending["reason"], "期限")
        self.assertFalse(state.position["armed"])

    def test_x0_is_literal_old_replay_control(self) -> None:
        """新dispatcherのX0が旧模型の全詳細/ログと同じであることを検査する。

        引数: なし。
        返り値: None。XFの追加属性をX0へ混入させない。
        """
        for side in (1, -1):
            source = operation_signal(side)
            events = [operation_event(11., 11, side, -5.), operation_event(12., 12, side, 5.),
                operation_event(13., 13, side, 0.), operation_event(14., 14, side, -5.)]
            a, qa = O33.replay(events, [deepcopy(source)], [], SESSION, "人工_X0", deepcopy(OPERATION_CONFIG), {"出口ID": "X0"}, "順行", BOUNDS)
            b, qb = O33.BASE.replay(events, [deepcopy(source)], [], SESSION, "人工_X0", deepcopy(OPERATION_CONFIG), {"出口ID": "X0"}, "順行", BOUNDS)
            self.assertEqual((qa, a.fills, a.orders, a.trades, a.normal_log), (qb, b.fills, b.orders, b.trades, b.normal_log))

    def test_independent_cost_and_full_trace(self) -> None:
        """別十進変換の独立金額と全人工XF追尾を照合する。

        引数: なし。
        返り値: None。主モデルを独立側へimportさせず保存値と正常板を渡す。
        """
        for side in (1, -1):
            for point in (5., 10., 12.2, 15., 30.):
                mark = 10000. + side * point
                self.assertEqual(O33.current_net(mark, 10000., side, OPERATION_CONFIG), T.current_net(mark, 10000., side, OPERATION_CONFIG))
            source = operation_signal(side)
            events = [operation_event(11., 11, side, -5.), operation_event(12., 12, side, 5.),
                operation_event(13., 13, side, 10.), operation_event(14., 14, side, 15.),
                operation_event(15., 15, side, 0.), operation_event(16., 16, side, -5.)]
            state, info = O33.replay(events, [source], [], SESSION, "人工_XF", deepcopy(OPERATION_CONFIG), {"出口ID": "XF"}, "順行", BOUNDS)
            info["期間"] = "学習"
            detail = {"候補ID": "人工_XF", "場": SESSION, "品質": info,
                "約定": state.fills, "注文": state.orders, "取引": state.trades}
            outer = self

            class Audit:
                """人工一件の独立照合をunittestへ接続する。"""

                def check(self, name: str, actual: object, expected: object) -> None:
                    """独立比較を厳密検査する。

                    引数: name(str)は項目、actual/expected(object)は比較値。
                    返り値: None。不一致は検査失敗。
                    """
                    outer.assertEqual(actual, expected, name)

            logs, _ = T.replay_cost(detail, [vars(e) for e in events], {source["イベントID"]: source},
                Audit(), (BOUNDS[0], BOUNDS[1], BOUNDS[3]), deepcopy(OPERATION_CONFIG))
            self.assertEqual(logs, [{"期間": "学習", **row} for row in state.normal_log])


@contextmanager
def artificial_driver(driver: Any, count: int = 66, active: bool = True) -> Iterator[Any]:
    """原板なしの一時正式先・台帳・共有case・純場材料を組み立てる。

    引数: driver(Any)は主、count(int)は人工場数、active(bool)は人工C0発動の有無。
    返り値: Iterator[Any]は人工材料と主呼出のpatch範囲。
    """
    with tempfile.TemporaryDirectory(prefix="終値位置33合成_", dir=ROOT / "work") as temporary:
        base = Path(temporary)
        study, work = base / "study", base / "work"
        study.mkdir(); work.mkdir()
        config = driver.expected_config()
        for name, value in (("条件.json", config), ("入力台帳.json", {"人工": True}), ("入口参照.json", {"人工": True})):
            (study / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        (study / "計画.md").write_text("人工計画\n", encoding="utf-8")
        (work / "診断予定.json").write_text('{"人工":true}', encoding="utf-8")
        (work / "仕様更新記録.json").write_text('{"人工":true}', encoding="utf-8")
        sessions = [f"2099-01-{1+i//2:02d}_{'Day' if i%2==0 else 'Night'}" for i in range(count)]
        manifest = {"entries": [{"session": session, "source_path": "人工.gz"} for session in sessions]}
        cases, material = [], {}
        for n, session in enumerate(sessions):
            source = raw(accepted=active, 場=session, 発動ID=session + "_人工_21", イベントID=session + "_人工_21_C0")
            if active:
                cases.append({**deepcopy(source), "ラベル": "未来を運用へ渡さない人工値", "新規価格": 987654., "最大順行pt": 987654.})
            value = block([source])
            value.update(events=[], frames={3: []}, duration=415., input_quality={"場": session})
            material[session] = value

        def built(entry: dict, manifest_value: dict, banks: dict, config_value: dict) -> dict:
            """人工場だけを同時点選別へ渡す。

            引数: entry/manifest_value/config_value(dict)は人工材料、banks(dict)は未使用。
            返り値: dictは人工純選別済み場。
            """
            return I.select(deepcopy(material[entry["session"]]))

        holder = SimpleNamespace(study=study, work=work, config=config, manifest=manifest, cases=cases,
            pointer={"人工": True}, material=material, built=built)
        yield holder


class DriverTests(unittest.TestCase):
    """主CLIと固定接続を人工保存先だけで検査する。"""

    def test_cli_prepare_never_calls_label_or_operation(self) -> None:
        """人工66場のCLI prepareを禁止経路付きで最後まで通す。

        引数: なし。
        返り値: None。旧case未来列はliveへ混入しない。
        """
        driver = driver_module()
        with artificial_driver(driver) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_entry_reference", return_value=f.pointer), \
                patch.object(driver.S, "load_shared_cases", return_value={"3分_C0": f.cases}), \
                patch.object(driver, "build_session", side_effect=f.built) as built, \
                patch.object(driver, "freeze", side_effect=AssertionError("prepareは固定禁止")) as freeze, \
                patch.object(driver.ENGINE, "replay", side_effect=AssertionError("prepareは運用禁止")) as replay, \
                patch.object(driver.E, "entry_metrics", side_effect=AssertionError("prepareは先着集計禁止")) as metrics, \
                patch.object(driver.D, "shadow_label", side_effect=AssertionError("prepareは新ラベル禁止")) as label, \
                patch.object(driver, "shared_path", side_effect=AssertionError("prepareは旧運用明細禁止")), \
                patch.object(sys, "argv", ["人工33", "--study", str(f.study), "--work", str(f.work), "--prepare"]), \
                redirect_stdout(io.StringIO()):
            driver.main()
            proof = json.loads((f.work / "準備点検.json").read_text(encoding="utf-8"))
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertTrue(proof["旧31C0純信号同値"])
            self.assertEqual(proof["T0純信号数"], 66)
            self.assertEqual(built.call_count, 66)
            self.assertEqual(sum(len(r["形状選別"]) for r in proof["準備"]), 66)
            for scene in proof["準備"]:
                for signal in scene["純信号"]:
                    self.assertEqual(set(signal), set(I.SIGNAL_FIELDS))
                self.assertNotIn("指標", scene)
                self.assertNotIn("複合context記録", scene)
            self.assertFalse((f.study / "結果.json").exists())
            self.assertFalse(any((f.work / name).exists() for name in driver.FILES))
            freeze.assert_not_called(); replay.assert_not_called(); metrics.assert_not_called(); label.assert_not_called()

    def test_build_session_delegates_old_numeric_without_relabel(self) -> None:
        """旧純再構成へ固定31条件を渡し、形状だけ追加する。

        引数: なし。
        返り値: None。既存数値銀行や公開時計を取り替えない。
        """
        driver = driver_module()
        value = block([raw()])
        with patch.object(driver.D, "build_session", return_value=deepcopy(value)) as old:
            result = driver.build_session({"session": SESSION}, {"人工": True}, {"人工": True}, driver.expected_config())
        self.assertEqual(old.call_args.args[-1], driver.OLD_CONFIG)
        self.assertEqual(len(result["shape_rows"]), 1)
        self.assertEqual(result["signals"]["3分_T0"][0]["要求時計秒"], value["signals"]["3分_C0"][0]["要求時計秒"])

    def test_identity_mapping_keeps_all_other_attributes(self) -> None:
        """T0識別子以外の数値・理由・ログ順序を落とさない。

        引数: なし。
        返り値: None。数値差はID正規化後にも残る。
        """
        driver = driver_module()
        value = {"候補ID": "3分_T0_X0", "約定": [{"entry_event_id": "人工_T0", "price": 120., "source_line": 7}],
            "未知列": {"名目床": 100., "理由": "必須利益追尾"}, "順序": [3, 1, 2]}
        expected = deepcopy(value)
        expected["候補ID"] = "3分_C0_X0"
        expected["約定"][0]["entry_event_id"] = "人工_C0"
        self.assertEqual(driver.old_identity(value), expected)
        value["約定"][0]["price"] += 5
        self.assertNotEqual(driver.old_identity(value), expected)

    def test_decision_shape_limits_atr_tolerance_to_diagnostic(self) -> None:
        """前ATRの表現差とCLV/価格差を判断指紋で区別する。

        引数: なし。
        返り値: None。許容内でもD呼値境界は消さない。
        """
        driver = driver_module()
        first, second = raw(), raw()
        first["前3分参照"]["atr"] = 20.1
        second["前3分参照"]["atr"] = 20.1 + 1e-14
        self.assertEqual(driver.decision_shape(I.shape(first)), driver.decision_shape(I.shape(second)))
        second["close"] += 1e-8
        self.assertNotEqual(driver.decision_shape(I.shape(first)), driver.decision_shape(I.shape(second)))
        first["前3分参照"]["atr"] = 20.
        second = deepcopy(first); second["前3分参照"]["atr"] += 1e-14
        self.assertNotEqual(driver.decision_shape(I.shape(first)), driver.decision_shape(I.shape(second)))

    def test_configuration_and_partial_refusal(self) -> None:
        """条件ドリフトとpartial上書きを市場処理前に拒否する。

        引数: なし。
        返り値: None。人工途中byteを保持する。
        """
        driver = driver_module()
        for section, key, value in (("終値位置", "追加", "改変"), ("運用", "返済待機秒", 2)):
            config = driver.expected_config()
            config[section][key] = value
            with self.assertRaises(ValueError):
                driver.validate_config(config)
        with artificial_driver(driver, 1) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_entry_reference", return_value=f.pointer), \
                patch.object(driver, "freeze", side_effect=AssertionError("partialはfreeze前拒否")) as freeze, \
                patch.object(driver, "build_session", side_effect=AssertionError("partialは市場処理前拒否")) as built:
            path = f.work / driver.FILES[0]
            path.write_bytes(b"artificial_partial")
            with self.assertRaises(ValueError):
                driver.run(f.study, f.work, False)
            self.assertEqual(path.read_bytes(), b"artificial_partial")
            freeze.assert_not_called(); built.assert_not_called()

    def test_formal_artificial_shared_case_and_t0_control(self) -> None:
        """人工一場だけで旧C0正規化・共有先着集計・三運用末尾を通す。

        引数: なし。
        返り値: None。実ケース/市場の読取や新ラベル計算はしない。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            session = f.manifest["entries"][0]["session"]
            begin, finish, cutoff, deadline = driver.W.OLD.shared.legacy.session_times(session)
            now = begin.timestamp() + 3960
            source = raw(場=session, 発動ID=session + "_人工_21", イベントID=session + "_人工_21_C0",
                要求時計秒=now, 足終了時計秒=now)
            material = block([source])
            material.update(events=[], frames={3: []}, duration=(finish-begin).total_seconds()/60, input_quality={"場": session})
            f.material[session] = material
            phase = driver.E.phase_of(session, f.config)
            case = {**deepcopy(source), "期間": phase, "ラベル": "未約定", "理由": "人工だけ",
                **{name: None for name in ("新規価格", "新規時計秒", "判定時計秒", "判定原板行", "新規原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")}}
            old_signal = driver.S.pure_signal(source)
            old_state, old_info = driver.ENGINE.replay([], [old_signal], [], session, "3分_C0_X0", f.config["運用"], {"出口ID": "X0"}, "順行")
            old_info.update(期間=phase, 場時間分=material["duration"])
            old_detail = {"候補ID": "3分_C0_X0", "場": session, "品質": old_info,
                "約定": old_state.fills, "取引": old_state.trades, "注文": old_state.orders, "入口取扱": old_state.signals}
            mapping = {name: f.work / ("人工旧_" + name) for name in ("全運用詳細.jsonl.gz", "追尾.jsonl.gz")}
            for name, rows in (("全運用詳細.jsonl.gz", [old_detail]), ("追尾.jsonl.gz", [{"期間": phase, **r} for r in old_state.normal_log])):
                with gzip.open(mapping[name], "wt", encoding="utf-8") as stream:
                    for row in rows:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            original_replay, original_metrics = driver.ENGINE.replay, driver.E.entry_metrics
            seen_signals, seen_cases = [], []

            def replayed(*args: Any, **kwargs: Any) -> Any:
                """人工live信号の列を保存して旧模型へ渡す。

                引数: args/kwargs(Any)は人工再生引数。
                返り値: Anyは人工再生結果。共有caseの未来列を受け付けない。
                """
                for signal in args[1]:
                    self.assertEqual(set(signal), set(I.SIGNAL_FIELDS))
                    seen_signals.append(deepcopy(signal))
                return original_replay(*args, **kwargs)

            def measured(rows: list[dict], period: str) -> dict:
                """正式集計だけが共有caseのラベルを受け取る。

                引数: rows(list[dict])は人工共有case、period(str)は区分。
                返り値: dictは元の集計。
                """
                seen_cases.extend(rows)
                return original_metrics(rows, period)

            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver, "validate_entry_reference", return_value=f.pointer), \
                    patch.object(driver.S, "load_shared_cases", return_value={"3分_C0": [case]}), \
                    patch.object(driver, "build_session", side_effect=f.built), \
                    patch.object(driver, "freeze", return_value={}), \
                    patch.object(driver, "shared_path", side_effect=lambda _, name: mapping[name]), \
                    patch.object(driver.ENGINE, "replay", side_effect=replayed), \
                    patch.object(driver.E, "entry_metrics", side_effect=measured), \
                    patch.object(driver.D, "shadow_label", side_effect=AssertionError("共有caseで新ラベル禁止")), \
                    redirect_stdout(io.StringIO()):
                result = driver.run(f.study, f.work, False)
            self.assertEqual(result["運用候補数"], 3)
            self.assertEqual(len(seen_signals), 3)
            self.assertEqual(len(seen_cases), 2)
            self.assertTrue(all(row["ラベル"] == "未約定" for row in seen_cases))
            self.assertTrue(json.loads((f.study / "T0対照同値.json").read_text(encoding="utf-8"))["全件一致"])
            output = json.loads((f.study / "結果.json").read_text(encoding="utf-8"))
            self.assertEqual(output["入口評価数"], 2)
            self.assertEqual(output["運用候補数"], 3)
            self.assertEqual(output["現方針運用候補数"], 2)
            self.assertEqual(output["表示固定ID"], ["3分_T0_X0", "3分_T0_XF", "3分_T1_XF"])
            self.assertEqual([r["現方針候補"] for r in output["結果"]], [False, True, True])
            self.assertEqual(output["入口評価"][0][phase]["候補数"], 1)
            catalog = json.loads((f.study / "一覧.resources.json").read_text(encoding="utf-8"))
            self.assertEqual(len(catalog["resources"]), 3)
            self.assertTrue(all(r["id"].startswith("00033_") for r in catalog["resources"]))

    def test_shared_reference_requires_all_proofs_and_fingerprints(self) -> None:
        """宣言SHAを人工化し、共有8証明の欠落/改変を拒否する。

        引数: なし。
        返り値: None。共有六gzipの内容は一切開かない。
        """
        driver = driver_module()
        pointer = json.loads((ROOT / "study/00032_最低同値床と公開SAR追尾/入口参照.json").read_text(encoding="utf-8"))
        declared = {normalized(ROOT / r["パス"]): r["圧縮SHA256参考"] for r in pointer["共有明細"]}
        original_sha = driver.O.sha

        def declared_sha(path: Path) -> str:
            """六gzipだけは宣言値を返し、実内容を開かない。

            引数: path(Path)は検算先。
            返り値: strは人工化したSHA又はコード/文書の現在SHA。
            """
            return declared[normalized(path)] if normalized(path) in declared else original_sha(path)

        with artificial_driver(driver, 1) as f, patch.object(driver.O, "sha", side_effect=declared_sha):
            target = f.study / "入口参照.json"
            target.write_text(json.dumps(pointer), encoding="utf-8")
            self.assertEqual(driver.validate_entry_reference(f.study), pointer)
            for mutation in ("missing", "sha", "artifact"):
                changed = deepcopy(pointer)
                if mutation == "missing":
                    changed["文書と証明"].pop("独立監査.json")
                elif mutation == "sha":
                    changed["文書と証明"]["条件.json"]["SHA256"] = "0" * 64
                else:
                    changed["共有明細"][0]["圧縮SHA256参考"] = "0" * 64
                target.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.validate_entry_reference(f.study)

    def test_freeze_requires_independent_current_bind_and_final_synthetic(self) -> None:
        """独立成功/現版bind/最終人工と固定後変更拒否を人工先で通す。

        引数: なし。
        返り値: None。旧巨大出典は人工一コードへ置換し実明細を開かない。
        """
        driver = driver_module()
        with artificial_driver(driver, 1, False) as f:
            f.pointer = {"文書と証明": {}, "共有明細": []}
            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver, "validate_entry_reference", return_value=f.pointer), \
                    patch.object(driver.S, "load_shared_cases", return_value={"3分_C0": []}), \
                    patch.object(driver, "build_session", side_effect=f.built), redirect_stdout(io.StringIO()):
                driver.run(f.study, f.work, True)
            paths = [HERE / name for name in ("検証.py", "入口.py", "運用.py", "合成検証.py")] + [f.study / "条件.json"]
            synthetic = {"全件成功": True, "合成編集終了": False,
                "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
                "独立数値補助SHA256": sha(HERE / "状態独立確認.py"),
                "独立追尾補助SHA256": sha(HERE / "追尾独立確認.py")}
            synthetic_file = f.work / "人工合成証拠.json"
            canonical_synthetic = ROOT / "work/終値位置/合成検証.json"
            previous = ROOT / "study/00032_最低同値床と公開SAR追尾/固定.json"
            dependency = ROOT / "scripts/CCI突破/入口.py"
            proof = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
                "主準備SHA256": sha(f.work / "準備点検.json"), "主コードSHA256": driver.code_pins(),
                "条件SHA256": sha(f.study / "条件.json"), "入力台帳SHA256": sha(f.study / "入力台帳.json"),
                "参照入力台帳SHA256": sha(driver.MANIFEST_PATH), "入口参照SHA256": sha(f.study / "入口参照.json"),
                "コードSHA256": sha(HERE / "状態独立確認.py"), "追尾コードSHA256": sha(HERE / "追尾独立確認.py"),
                "依存コードSHA256": {dependency.relative_to(ROOT).as_posix(): sha(dependency)}}
            independent_file = f.work / "独立準備点検.json"
            original_read, original_sha = driver.W.read_json, driver.O.sha

            def read_json(path: Path) -> dict:
                """正本を触らず人工の旧出典宣言/合成証拠へ振り替える。

                引数: path(Path)は参照先。
                返り値: dictは人工宣言又は元の小JSON。
                """
                if normalized(path) == normalized(previous):
                    return {"ファイルSHA256": {dependency.relative_to(ROOT).as_posix(): sha(dependency)}}
                if normalized(path) == normalized(canonical_synthetic):
                    return deepcopy(synthetic)
                return original_read(path)

            def redirected_sha(path: Path) -> str:
                """人工合成証拠だけを一時ファイルのSHAへ振り替える。

                引数: path(Path)は固定する出典。
                返り値: strは現在コード又は人工証拠のSHA。
                """
                return sha(synthetic_file) if normalized(path) == normalized(canonical_synthetic) else original_sha(path)

            with patch.object(driver, "validate_entry_reference", return_value=f.pointer), \
                    patch.object(driver.W, "read_json", side_effect=read_json), patch.object(driver.O, "sha", side_effect=redirected_sha):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    driver.freeze(f.study, f.work)
                independent_file.write_text(json.dumps(proof), encoding="utf-8")
                synthetic_file.write_text(json.dumps(synthetic), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                synthetic["合成編集終了"] = True
                synthetic_file.write_text(json.dumps(synthetic), encoding="utf-8")
                changed = deepcopy(proof); changed["入口参照SHA256"] = "0" * 64
                independent_file.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                changed = deepcopy(proof); changed["依存コードSHA256"] = {}
                independent_file.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                independent_file.write_text(json.dumps(proof), encoding="utf-8")
                original_trail = synthetic["独立追尾補助SHA256"]
                synthetic["独立追尾補助SHA256"] = "0" * 64
                synthetic_file.write_text(json.dumps(synthetic), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                synthetic["独立追尾補助SHA256"] = original_trail
                synthetic_file.write_text(json.dumps(synthetic), encoding="utf-8")
                fixed = driver.freeze(f.study, f.work)
                self.assertEqual(driver.freeze(f.study, f.work), fixed)
                self.assertEqual(fixed["独立準備SHA256"], sha(independent_file))
                (f.study / "計画.md").write_text("人工固定後改変\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                (f.study / "結果.json").write_text('{"人工":true}', encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)


def main() -> None:
    """人工検査だけを実行して現五pinsへbindする。

    引数: なし。--finalは主二コード/条件/独立完成通知後に指定する。
    返り値: None。実市場準備・先着・運用を実行しない。
    """
    parser = argparse.ArgumentParser(description="CCI突破の同時点終値位置を人工検査")
    parser.add_argument("--final", action="store_true")
    arguments = parser.parse_args()
    driver = load(HERE / "検証.py", "終値位置33合成の主driver")
    paths = [HERE / name for name in ("検証.py", "入口.py", "運用.py", "合成検証.py")] + [driver.STUDY / "条件.json"]
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    state, trail = sha(HERE / "状態独立確認.py"), sha(HERE / "追尾独立確認.py")
    stream = io.StringIO()
    with deny_market():
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged = pins == {p.relative_to(ROOT).as_posix(): sha(p) for p in paths} and state == sha(HERE / "状態独立確認.py") and trail == sha(HERE / "追尾独立確認.py")
    success = result.wasSuccessful() and result.testsRun > 0 and unchanged
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(arguments.final and success),
        "実資料の先着損益計算": False, "実行中コード条件不変": unchanged, "ファイルSHA256": pins,
        "独立数値補助SHA256": state, "独立追尾補助SHA256": trail,
        "範囲": "CLV分数/CCI現前反例/鏡像/幅0/CLV0/ULP/表示underflow精密符号、独立全shape/select/判断射影一致、前ATR診断非介入、旧C0全verdict保持、全raw/同時点消費、純whitelist/別snapshot、原発動重複/旧集合不一致拒否、人工66場CLI prepareの固定/先着/運用禁止、人工一場の共有case正式集計/T0X0全detail-trace同値/3運用とViewer/参考と現方針分離、現在費用後strict正の12.2等号/15起動・MFEだけ不起動・買売鏡像・固定参照滑り5と感度分離・初期logとcost_arm・sticky非緩和/名目床/pending-hard-TP-期限優先・独立金額と全XF追尾一致、共有8証明/六明細の宣言bind、ATR判断のD整数境界、独立準備成功/現在bind/依存辞書/最終合成の独立2SHA必須join、固定後変更/partial/既存結果拒否。実原板/cache/実圧縮明細へのstat/open禁止、旧巨大明細は人工宣言だけ。",
        "失敗": [{"検証": str(c), "内容": m} for c, m in result.failures],
        "エラー": [{"検証": str(c), "内容": m} for c, m in result.errors], "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / ("合成検証.json" if arguments.final else "合成検証_途中.json")
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({key: proof[key] for key in ("全件成功", "検証件数", "合成編集終了", "実行中コード条件不変")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
