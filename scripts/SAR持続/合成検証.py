"""00025のSAR数値・鏡像・公開時点と価格イベントの一度消費を人工足で検査する。"""

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
import random
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00025_価格イベントとSAR方向持続"
WORK = ROOT / "work/SAR持続"
SESSION = "2026-11-04_Day"
CONTRACT = ("NK225", "202612")


def load(path: Path, name: str) -> object:
    """保存成績を再生せず対象APIだけを読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: object は読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


FIX = load(ROOT / "scripts/終値切替/合成検証.py", "SAR合成の固定24人工価格")
I = load(HERE / "入口.py", "SAR合成の入口")
J = load(HERE / "指標.py", "SAR合成の数値銀行")
O = load(HERE / "運用.py", "SAR合成の固定A5")


def config() -> dict:
    """正式予定の条件を独立コピーで読む。

    引数: なし。
    返り値: dict は25条件。正式損益や先着ラベルを読まない。
    """
    return json.loads((STUDY / "条件.json").read_text(encoding="utf-8"))


def frame(index: int, high: float = 105., low: float = 95., close: float = 100., **updates: object) -> dict:
    """手計算できる完全幅の公開3分OHLCを作る。

    引数: index (int) は足番号、high/low/close (float) は価格、updates (object) は属性上書き。
    返り値: dict は人工足。原板・実相場を参照しない。
    """
    start = index * 180.
    return {"index": index, "minutes": 3, "start": start, "end": start + 180.,
            "confirm": start + 180., "confirm_line": 10 + index, "publish": True, "missing": 0,
            "open": min(high, max(low, close)), "high": high, "low": low, "close": close, **updates}


def reflect(frames: list[dict], center: float = 2000.) -> list[dict]:
    """人工OHLCを正の範囲で上下反射する。

    引数: frames (list[dict]) は人工系列、center (float) は価格の和となる反射定数。
    返り値: list[dict] は高安を入れ替えた鏡像系列。
    """
    rows = deepcopy(frames)
    for row in rows:
        high, low = row["high"], row["low"]
        row.update(open=center-row["open"], close=center-row["close"], high=center-low, low=center-high)
    return rows


def sar_rows(frames: list[dict], direction: int = 1, **updates: object) -> list[dict]:
    """入口採否を数式から独立に検査する人工SAR記録を作る。

    引数: frames (list[dict]) は下位足、direction (int) は公開後方向、updates (object) は全行上書き。
    返り値: list[dict] は同じ公開キーを持つ数値準備済み記録。
    """
    return [{**deepcopy(row), "場": SESSION, "SAR準備済": True, "SAR公開可": bool(row["publish"]),
             "SAR方向": direction, "SAR事前線": 900. if direction == 1 else 1100.,
             "SAR表示線": 900. if direction == 1 else 1100., "SAR次足線": 901. if direction == 1 else 1099.,
             "SAR_EP": 1100. if direction == 1 else 900., "SAR_AF": .02, "SAR反転": False,
             "SAR初期化": False, "SAR解除理由": [], **updates} for row in frames]


def generate(side: int = 1, frames: list[dict] | None = None, higher: list[dict] | None = None,
             channels: list[dict] | None = None, quantities: dict | None = None,
             sar: list[dict] | None = None, cutoff: float = 20000, deadline: float = 30000) -> tuple[dict, dict]:
    """実相場なしの価格イベントと人工SARを新入口へ接続する。

    引数: side (int) は元突破方向、frames/higher/channels/sar (list[dict]|None) は人工上書き、
    quantities (dict|None) は診断量、cutoff/deadline (float) は新規停止/期限。
    返り値: tuple[dict,dict] は二入口と全価格状態。先着・損益は計算しない。
    """
    rows = FIX.lower(side) if frames is None else frames
    return I.generate(rows, FIX.FIX.higher(side) if higher is None else higher, SESSION, cutoff, deadline, config(),
                      channels=FIX.FIX.channels(side) if channels is None else channels, quantity=quantities,
                      sar_rows=sar_rows(rows, side) if sar is None else sar)


def price_trace(rows: list[dict]) -> list[dict]:
    """監視traceから新旧で変わる戦略採否の表示だけを除く。

    引数: rows (list[dict]) は保存監視行。
    返り値: list[dict] は価格状態/出典/時計/動作を全て保持した比較用コピー。
    """
    values = deepcopy(rows)
    for row in values:
        for action in row["動作"]:
            action.pop("戦略採否", None)
    return values


# ----------------------------------------
# 数式の期待値は人工高安の手計算で固定し、主銀行の式を期待値に流用しない。

class SAR数値検証(unittest.TestCase):
    """独自の初期化・strict貫通・前二本制約・AFを手計算で検査する。"""

    def test_初期方向は二本終値差で同値は未確定のまま次の隣接対を使う(self) -> None:
        """同値履歴の古い極値を、後の初期化へ引きずらない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [frame(0, 130, 90, 100), frame(1, 120, 96, 100), frame(2, 110, 97, 101)]
        rows, _ = J.SARBank().build(frames, SESSION, CONTRACT)
        self.assertEqual([r["SAR方向"] for r in rows], [0, 0, 1])
        self.assertEqual([r["SAR準備済"] for r in rows], [False, False, True])
        self.assertEqual((rows[-1]["SAR表示線"], rows[-1]["SAR_EP"], rows[-1]["SAR_AF"]), (96, 110, .02))
        self.assertAlmostEqual(rows[-1]["SAR次足線"], 96.28)
        self.assertTrue(rows[-1]["SAR初期化"])

    def test_初期化継続と前二本制約の数値を手計算に合わせる(self) -> None:
        """次線を先にclampせず、非反転足の表示線だけ過去二本で制約する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [frame(i, 105+i, 95+i, 100+i) for i in range(4)]
        rows, _ = J.SARBank().build(frames, SESSION, CONTRACT)
        expected = [(95., 106., .02, 95.22), (95., 107., .04, 95.48), (95.48, 108., .06, 96.2312)]
        for row, values in zip(rows[1:], expected):
            for field, value in zip(("SAR表示線", "SAR_EP", "SAR_AF", "SAR次足線"), values):
                self.assertAlmostEqual(row[field], value, places=10)
            self.assertEqual(row["SAR方向"], 1)
            self.assertFalse(row["SAR反転"])
        self.assertIsNone(rows[1]["SAR事前線"])
        self.assertAlmostEqual(rows[2]["SAR事前線"], 95.22)

    def test_前二本制約前の次線をstrictに貫通してから反転する(self) -> None:
        """前next95.22を貫通し過去clamp95を割らない足も反転とする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [frame(0, 105, 95, 100), frame(1, 106, 96, 101), frame(2, 106, 95.1, 100)]
        rows, _ = J.SARBank().build(frames, SESSION, CONTRACT)
        row = rows[-1]
        self.assertEqual((row["SAR方向"], row["SAR反転"], row["SAR表示線"], row["SAR_EP"], row["SAR_AF"]), (-1, True, 106, 95.1, .02))
        self.assertAlmostEqual(row["SAR事前線"], 95.22)
        self.assertAlmostEqual(row["SAR次足線"], 105.782)

    def test_事前線と安値の等号は反転せず高安同値もAFを増やさない(self) -> None:
        """strict貫通とstrict極値更新の二つの等号を別に検査する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [frame(0, 105, 95, 100), frame(1, 106, 96, 101), frame(2, 106, 95.22, 100)]
        rows, _ = J.SARBank().build(frames, SESSION, CONTRACT)
        row = rows[-1]
        self.assertEqual((row["SAR方向"], row["SAR反転"], row["SAR表示線"], row["SAR_EP"], row["SAR_AF"]), (1, False, 95, 106, .02))
        self.assertAlmostEqual(row["SAR次足線"], 95.22)

    def test_反転は当足の極値確認後で表示点と事前線を区別しAFを初期化する(self) -> None:
        """大きな両方向足の観測順を捏造せず、確定後表示を開始時注文へ戻さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [frame(0, 105, 95, 100), frame(1, 106, 96, 101), frame(2, 120, 94, 100)]
        rows, _ = J.SARBank().build(frames, SESSION, CONTRACT)
        row = rows[-1]
        self.assertAlmostEqual(row["SAR事前線"], 95.22)
        self.assertEqual((row["SAR表示線"], row["SAR_EP"], row["SAR_AF"], row["SAR方向"]), (120, 94, .02, -1))
        self.assertAlmostEqual(row["SAR次足線"], 119.48)
        self.assertEqual((row["confirm"], row["confirm_line"]), (frames[-1]["confirm"], frames[-1]["confirm_line"]))

    def test_極値更新だけAFを増加させ上限二割を越えない(self) -> None:
        """高値を十分遠く更新する人工上昇で、増分と上限を確認する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [frame(i, 110+20*i, 100+20*i, 105+20*i) for i in range(20)]
        rows, _ = J.SARBank().build(frames, SESSION, CONTRACT)
        self.assertTrue(all(r["SAR方向"] == 1 for r in rows[1:]))
        for i, row in enumerate(rows[1:]):
            self.assertAlmostEqual(row["SAR_AF"], min(.2, .02*(i+1)))
        self.assertEqual(rows[-1]["SAR_AF"], .2)

    def test_上下反射で全数値と反転初期化履歴が鏡像になる(self) -> None:
        """同値・単調・往復・急変の全人工系列で買売優先を作らない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rng = random.Random(250125)
        frames = []
        close = 100.
        for i in range(160):
            close += rng.choice((-8, -3, 0, 0, 2, 9))
            close = max(40., min(180., close))
            frames.append(frame(i, close+rng.choice((0, 2, 11)), close-rng.choice((0, 1, 9)), close))
        left, _ = J.SARBank().build(frames, SESSION, CONTRACT)
        right, _ = J.SARBank().build(reflect(frames), SESSION, CONTRACT)
        for a, b in zip(left, right):
            self.assertEqual(a["SAR方向"], -b["SAR方向"])
            for field in ("SAR準備済", "SAR公開可", "SAR反転", "SAR初期化"):
                self.assertEqual(a[field], b[field])
            for field in ("SAR事前線", "SAR表示線", "SAR次足線", "SAR_EP"):
                self.assertEqual(a[field] is None, b[field] is None)
                if a[field] is not None:
                    self.assertAlmostEqual(a[field]+b[field], 2000., places=8)
            self.assertEqual(a["SAR_AF"], b["SAR_AF"])


# ----------------------------------------
# SAR系列の銀行carryと、入口の同場公開隣接pairを別に検査する。

class SAR履歴公開検証(unittest.TestCase):
    """欠枠/限月resetと未公開数値更新・場間carryを分ける。"""

    def test_同限月場間carryと限月変更resetを分ける(self) -> None:
        """場頭の足番号0を銀行欠枠とせず、限月変更では再seedする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        first = [frame(i, 105+i, 95+i, 100+i) for i in range(4)]
        next_frames = [frame(0, 110, 100, 105), frame(1, 111, 101, 106)]
        bank = J.SARBank()
        before, _ = bank.build(first, SESSION, CONTRACT)
        carry, _ = bank.build(next_frames, "2026-11-04_Night", CONTRACT)
        self.assertTrue(carry[0]["SAR準備済"])
        self.assertAlmostEqual(carry[0]["SAR事前線"], before[-1]["SAR次足線"])
        reset, _ = bank.build(next_frames, "2026-11-05_Day", ("NK225", "202703"))
        self.assertFalse(reset[0]["SAR準備済"])
        self.assertTrue(reset[1]["SAR初期化"])

    def test_欠枠番号飛越と尾部完全欠枠は銀行を切る(self) -> None:
        """現在有効足はreset後の一足目となり、欠落を前方向で補わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for update in ({"missing": 1}, {"index": 3}):
            frames = [frame(0, 105, 95, 100), frame(1, 106, 96, 101), frame(2, 107, 97, 102)]
            frames[-1].update(update)
            rows, _ = J.SARBank().build(frames, SESSION, CONTRACT)
            self.assertFalse(rows[-1]["SAR準備済"])
        bank = J.SARBank()
        bank.build([frame(0), frame(1, close=101)], SESSION, CONTRACT, tail_missing=1)
        rows, _ = bank.build([frame(0), frame(1, close=101)], "2026-11-04_Night", CONTRACT)
        self.assertFalse(rows[0]["SAR準備済"])
        self.assertTrue(rows[1]["SAR初期化"])

    def test_末尾完全未公開足は内部数値だけ進め次場へcarryできる(self) -> None:
        """未公開後の銀行値と、注文に使える公開値を同一視しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bank = J.SARBank()
        frames = [frame(i, 105+i, 95+i, 100+i) for i in range(3)]
        frames[-1].update(publish=False, confirm=None, confirm_line=None)
        rows, _ = bank.build(frames, SESSION, CONTRACT)
        self.assertTrue(rows[-1]["SAR準備済"])
        self.assertFalse(rows[-1]["SAR公開可"])
        carry, _ = bank.build([frame(0, 110, 100, 105)], "2026-11-04_Night", CONTRACT)
        self.assertAlmostEqual(carry[0]["SAR事前線"], rows[-1]["SAR次足線"])

    def test_不正OHLCを銀行から除き次の正常足で古方向を復活させない(self) -> None:
        """不正の観測行をseedにせず、二本の正常値から再初期化する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for invalid in ({"close": None}, {"low": 0}, {"high": math.nan}, {"low": 120},
                        {"open": math.inf}, {"close": -math.inf}):
            frames = [frame(i, 105+i, 95+i, 100+i) for i in range(5)]
            frames[2].update(invalid)
            rows, _ = J.SARBank().build(frames, SESSION, CONTRACT)
            self.assertFalse(rows[2]["SAR準備済"])
            self.assertFalse(rows[2]["SAR数値入力可"])
            self.assertFalse(rows[3]["SAR準備済"])
            self.assertTrue(rows[4]["SAR初期化"])
            self.assertIn("3分OHLC不正", rows[2]["SAR解除理由"])
            for key, value in invalid.items():
                if isinstance(value, float) and not math.isfinite(value):
                    self.assertIsNone(rows[2][key])
            json.dumps(rows, ensure_ascii=False, allow_nan=False)

    def test_未完成足と公開key後退を拒否し同時計の次原行は保持する(self) -> None:
        """同時計でも原行を捨てず、公開前や過去の原行へ巻き戻さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [frame(0, confirm=1000, confirm_line=10), frame(1, close=101, confirm=1000, confirm_line=11)]
        rows, _ = J.SARBank().build(frames, SESSION, CONTRACT)
        self.assertEqual([(r["confirm"], r["confirm_line"]) for r in rows], [(1000, 10), (1000, 11)])
        self.assertTrue(rows[-1]["SAR公開可"])
        frames[-1]["confirm_line"] = 9
        with self.assertRaises(ValueError):
            J.SARBank().build(frames, SESSION, CONTRACT)
        with self.assertRaises(ValueError):
            J.SARBank().build([frame(0, confirm=179)], SESSION, CONTRACT)
        with self.assertRaises(ValueError):
            J.SARBank().build([frame(0, minutes=5)], SESSION, CONTRACT)


# ----------------------------------------
# 価格イベント、数値M25、Q0/Q1の値条件、実注文を分離する。

class 複合入口検証(unittest.TestCase):
    """単足勢いとSAR二本持続を同じ価格イベント上で比較する。"""

    def test_価格構造は固定24からそのまま再用しQ0とQ1だけ作る(self) -> None:
        """新指標で監視寿命/元の出典/最初f/g/取消を変更しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            groups, quality = generate(side)
            _, old_quality = FIX.generate(side)
            self.assertEqual(set(groups), {"3分_Q0", "3分_Q1"})
            self.assertEqual(price_trace(quality["監視trace"]), price_trace(old_quality["監視trace"]))
            self.assertEqual(quality["エピソード診断"], old_quality["エピソード診断"])
            for a, b in zip(quality["全Q発動記録"], old_quality["全Q発動記録"]):
                for key in ("発動ID", "エピソードID", "入口系統", "要求時計秒", "要求原板行", "side", "固定設定", "先着評価対象"):
                    self.assertEqual(a[key], b[key])
            self.assertEqual(len(groups["3分_Q0"]), 2)

    def test_SAR当足だけ転換では持続とせず前現両方の実方向を要求する(self) -> None:
        """当足の反転点だけを見て事前から続いていた方向へ昇格させない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = FIX.lower(side)
            sar = sar_rows(frames, side)
            sar[3]["SAR方向"] = -side
            groups, _ = generate(side, sar=sar)
            self.assertFalse(any(r["役割"] == "反転" for r in groups["3分_Q1"]))
            sar[2]["SAR方向"] = -side
            groups, _ = generate(side, sar=sar)
            self.assertEqual([r["役割"] for r in groups["3分_Q1"]], ["反転"])

    def test_Q1はMACD符号や上位ADX低下を追加ANDせずQ0と対照する(self) -> None:
        """Q0の勢い不成立でも、M準備とSAR持続があればQ1の反転を残す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = FIX.lower(side)
            frames[3]["macd_hist"] = frames[2]["macd_hist"] + side
            sar = sar_rows(frames, -side)
            groups, _ = generate(side, frames=frames, sar=sar)
            self.assertFalse(any(r["役割"] == "反転" for r in groups["3分_Q0"]))
            self.assertEqual([r["役割"] for r in groups["3分_Q1"]], ["反転"])

    def test_SAR未準備のfでも一度消費しgでだけ復帰する(self) -> None:
        """新準備不可の最初内復帰を捨てて後の都合のよい内復帰へ取り直さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = FIX.lower(side)
            sar = sar_rows(frames, side)
            sar[2].update(SAR準備済=False, SAR公開可=False, SAR方向=0)
            groups, quality = generate(side, sar=sar)
            self.assertEqual([r["index"] for r in quality["全Q発動記録"]], [3, 4])
            self.assertEqual((quality["内復帰価格消費数"], quality["外回復価格消費数"]), (1, 1))
            self.assertEqual([r["役割"] for r in groups["3分_Q0"]], ["順行"])
            self.assertEqual([r["役割"] for r in groups["3分_Q1"]], ["順行"])

    def test_当時SARが公開不可なら両案同じM25で除外しQ0だけ救済しない(self) -> None:
        """方向値が保存されていても未公開足を注文条件へ使わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = FIX.lower()
        sar = sar_rows(frames)
        sar[3]["SAR公開可"] = False
        groups, quality = generate(sar=sar)
        self.assertTrue(all(not rows for rows in groups.values()))
        self.assertEqual(len(quality["全Q発動記録"]), 2)

    def test_数量と旧上位選別値を変えてもQの値条件を変えない(self) -> None:
        """数量は診断のみで、旧E1のADX非上昇をQへ残さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        base_groups, baseline = generate()
        quantities = {i: {"数量準備済": False, "RVOL": 9999} for i in range(5)}
        groups, quality = generate(higher=FIX.FIX.higher(ranging=True), quantities=quantities)
        self.assertEqual([r["動作"] for r in quality["監視trace"]], [r["動作"] for r in baseline["監視trace"]])
        for key in groups:
            self.assertEqual([r["イベントID"] for r in groups[key]], [r["イベントID"] for r in base_groups[key]])

    def test_SAR現在を前の公開まで先取りせず異なる公開keyを拒否する(self) -> None:
        """同じ足番号へ未来の線や同秒の後原行を注入して使わせない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = FIX.lower()
        for field, change in (("confirm", 1), ("confirm_line", 1), ("end", 180)):
            sar = sar_rows(frames)
            sar[3][field] += change
            with self.assertRaises(ValueError):
                generate(sar=sar)
        sar = sar_rows(frames)
        sar.append(deepcopy(sar[-1]))
        with self.assertRaises(ValueError):
            generate(sar=sar)

    def test_前SARの欠測では古い正常値へ戻さず現在だけの持続へ昇格しない(self) -> None:
        """局所前足は同場隣接一足だけで、SAR方向0も準備不可とする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = FIX.lower()
        sar = sar_rows(frames)
        sar = [r for r in sar if r["index"] != 3]
        groups, quality = generate(sar=sar)
        self.assertTrue(all(not rows for rows in groups.values()))
        self.assertEqual(len(quality["全Q発動記録"]), 2)
        sar = sar_rows(frames)
        sar[3]["SAR方向"] = 0
        self.assertTrue(all(not rows for rows in generate(sar=sar)[0].values()))

    def test_Q1も共通M24のHと上位公開pair準備を省略しない(self) -> None:
        """Q1の値条件に使わない指標の準備除外も、Q0と同じ母集団に揃える。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = FIX.lower()
        frames[3]["macd_hist"] = None
        self.assertTrue(all(not rows for rows in generate(frames=frames)[0].values()))
        groups, quality = generate(higher=[])
        self.assertTrue(all(not rows for rows in groups.values()))
        self.assertEqual(len(quality["全Q発動記録"]), 2)

    def test_新準備を全て満たすQ0は旧E0を同じ価格イベントで再現する(self) -> None:
        """SAR方向選別と準備追加で失った旧E0を別に分けられるようにする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            groups, quality = generate(side)
            old, _ = FIX.generate(side)
            self.assertEqual([r["発動ID"] for r in groups["3分_Q0"]], [r["発動ID"] for r in old["3分_E0"]])
            self.assertEqual(sum(r["SAR準備でQ0除外数"] for r in quality["イベント段階"]), 0)
            frames = FIX.lower(side)
            sar = sar_rows(frames, side)
            sar[2].update(SAR準備済=False, SAR公開可=False, SAR方向=0)
            _, quality = generate(side, sar=sar)
            self.assertEqual(sum(r["SAR準備でQ0除外数"] for r in quality["イベント段階"]), 1)

    def test_全Q競合確定後にcaseの全採否を正本へ揃え深複写する(self) -> None:
        """片側戦略だけ競合した場合も、他戦略caseに古い採用を残さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        original = I.BASE.signal

        def same_key(*args: object, **kwargs: object) -> dict:
            """二つの人工eventを同要求keyへ衝突させる。

            引数: args/kwargs (object) は元signal引数。
            返り値: dict は時点だけ置換した人工signal。
            """
            row = original(*args, **kwargs)
            row.update(要求時計秒=4320, 要求原板行=103)
            return row

        with patch.object(I.BASE, "signal", side_effect=same_key):
            groups, quality = generate()
        self.assertEqual(groups["3分_Q0"], [])
        self.assertEqual(len(groups["3分_Q1"]), 1)
        case = groups["3分_Q1"][0]
        canonical = next(r for r in quality["全Q発動記録"] if r["発動ID"] == case["発動ID"])
        self.assertEqual(case["戦略判定"], canonical["戦略判定"])
        self.assertTrue(case["戦略判定"]["Q0"]["同時競合"])
        case["戦略判定"]["Q0"]["同時競合"] = False
        self.assertTrue(canonical["戦略判定"]["Q0"]["同時競合"])
        self.assertNotIn("ラベル", canonical)

    def test_多数の価格条件変更でも固定24の価格状態だけは同一である(self) -> None:
        """端等号・飛越・寿命・時点・未公開をSAR採否で取り替えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        changes = [None, (3, "close", 1000), (3, "close", 900), (3, "close", 899),
                   (3, "close", 1010), (4, "close", 1000), (4, "close", 900),
                   (3, "confirm", 4351), (3, "missing", 1), (3, "publish", False), (3, "macd_hist", None)]
        for side in (1, -1):
            for change in changes:
                frames = FIX.lower(side, 10)
                if change is not None:
                    index, field, value = change
                    if field == "close" and side == -1:
                        value = 2000-value
                    frames[index][field] = value
                _, quality = generate(side, frames=frames)
                _, old = FIX.generate(side, frames=frames)
                self.assertEqual(price_trace(quality["監視trace"]), price_trace(old["監視trace"]))
                self.assertEqual(quality["エピソード診断"], old["エピソード診断"])


# ----------------------------------------
# 時間/遅延対象外、人工約定の固定A5、prepare禁止経路を接続する。

class 評価と運用接続検証(unittest.TestCase):
    """新指標を出口へ混ぜず、当時採否と事後先着を別経路に保つ。"""

    def test_時間外と確認遅延超は先着を呼ばず九数値Noneとする(self) -> None:
        """両方不可なら時間理由を優先し、未約定へ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "SAR合成の対象外先着")
        for cutoff, reason in ((4351, "要求時間条件外"), (20000, "足確定確認遅延30秒超")):
            frames = FIX.lower()
            frames[3]["confirm"] += 31
            _, quality = generate(frames=frames, cutoff=cutoff)
            record = quality["全Q発動記録"][0]
            forbidden = SimpleNamespace(evaluate=unittest.mock.Mock(side_effect=AssertionError("対象外の先着は禁止")))
            result = driver.shadow_label(record, forbidden, {}, cutoff, 30000, config())
            self.assertEqual((result["ラベル"], result["理由"]), ("対象外", reason))
            numbers = [v for k, v in result.items() if k not in ("ラベル", "理由")]
            self.assertEqual(len(numbers), 9)
            self.assertTrue(all(v is None for v in numbers))
            forbidden.evaluate.assert_not_called()

    def test_SAR不準備でも時間遅延可の原eventは先着診断だけできる(self) -> None:
        """M25不成立を先着対象外と同一視せず、case採用分母へは戻さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "SAR合成の通常先着")
        frames = FIX.lower()
        groups, quality = generate(sar=sar_rows(frames, SAR準備済=False, SAR公開可=False, SAR方向=0))
        self.assertTrue(all(not rows for rows in groups.values()))
        record = quality["全Q発動記録"][0]
        self.assertTrue(record["先着評価対象"])
        path = SimpleNamespace(evaluate=unittest.mock.Mock(return_value={"ラベル": "人工診断"}))
        cache = {}
        driver.shadow_label(record, path, cache, 20000, 30000, config())
        driver.shadow_label(record, path, cache, 20000, 30000, config())
        path.evaluate.assert_called_once_with(4320, 20000, 30000, -1, adverse=125, favorable=250)

    def test_固定24のA5を再用しSAR点を出口や自動ドテンへ変換しない(self) -> None:
        """人工正常BBOだけで、入口ATR・同値保護・同秒返済禁止を照合する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。実相場損益は計算しない。
        """
        self.assertIs(O.replay, O.BASE.replay)
        self.assertEqual(O.trail_parameters(20.001), (5, 25))
        for side in (1, -1):
            frames = FIX.lower(side)
            frames[4]["confirm_line"] = 200
            groups, _ = generate(side, frames=frames)
            signals = groups["3分_Q0"]
            now, g = signals[0]["要求時計秒"], signals[1]["要求時計秒"]
            quote = FIX.Q
            quotes = [quote(now, 103), quote(now+1, 104), quote(now+2, 105), quote(g, 200),
                      quote(g+1, 201, 990 if side == 1 else 1010), quote(g+2, 202, 995 if side == 1 else 1005),
                      quote(g+2, 203, 995 if side == 1 else 1005), quote(g+3, 204, 995 if side == 1 else 1005),
                      quote(now+7201, 300)]
            args = (quotes, signals, [], SESSION, "人工25", config()["運用"], {"出口ID": "X0"}, "混合",
                    (now-100, now+7300, now+3600, now+7200))
            state, info = O.replay(*deepcopy(args))
            old, old_info = FIX.O.replay(*deepcopy(args))
            self.assertEqual((state.fills, state.orders, state.trades, info), (old.fills, old.orders, old.trades, old_info))
            self.assertEqual(len(state.trades), 1)
            trade = state.trades[0]
            self.assertEqual((trade["入口役割"], trade["入口ATR"], trade["追尾距離pt"]), ("反転", 30, 30))
            self.assertEqual((trade["追尾起動"], trade["返済時計秒"], trade["基準純損益円"]), (True, g+3, -22))
            self.assertEqual(trade["返済理由"], "必須利益追尾")
            self.assertEqual(info["建玉中抑止数"], 1)

    def test_二候補空足零とSARや費用支持の固定変更拒否を検査する(self) -> None:
        """実装と設定の数値だけがずれる変更や比較本数の緩和を拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "SAR合成の二定義")
        self.assertEqual([r["入口ID"] for r in driver.sources(config())], ["3分_Q0", "3分_Q1"])
        groups, quality = driver.generate_or_empty([], [], SESSION, 3, 20000, 30000, config(), [], [], {}, [])
        self.assertEqual(groups, {"3分_Q0": [], "3分_Q1": []})
        self.assertEqual(quality["全Q発動記録"], [])
        changes = [(('SAR', '比較本数'), 1), (('SAR', '初期AF'), .03), (('SAR', '出口使用'), True),
                   (('運用', '片道手数料円'), 12), (('必須追尾', '起動幅pt'), 10),
                   (('入口支持', '学習', '約定候補数'), 59), (('費用支持', '学習', '完結取引数'), 19),
                   (('目標確認率',), .6), (('分割', '選択開始日'), '2026-10-20'),
                   (('逆行pt',), 120), (('終値切替', '内復帰上限本数'), 7)]
        for keys, value in changes:
            altered, parent = deepcopy(config()), None
            parent = altered
            for key in keys[:-1]:
                parent = parent[key]
            parent[keys[-1]] = value
            with self.assertRaises(ValueError):
                I.validate_config(altered)

    def test_旧十八項目とSAR全項目は数値も規約文字列も変化を拒否する(self) -> None:
        """実装の参照値と正式表示の差や、SARの等号/公開規約の表示だけ変更を防ぐ。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        inherited = ("対象", "全65場既使用", "運用", "必須追尾", "発動条件", "指標", "局面改訂", "逆行pt", "順行pt",
                     "残り時間下限分", "確認遅延上限秒", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割", "出口", "終値切替")

        def changed(value: object) -> object:
            """固定値の型を保ちながら最初の葉だけを変更する。

            引数: value (object) は固定条件の値。
            返り値: object は一箇所だけ差を持つコピー。
            """
            if isinstance(value, bool):
                return not value
            if isinstance(value, (int, float)):
                return value+1
            if isinstance(value, str):
                return value+"規約変更"
            result = deepcopy(value)
            if isinstance(value, list):
                result[0] = changed(result[0])
                return result
            if isinstance(value, dict):
                first = next(iter(result))
                result[first] = changed(result[first])
                return result
            raise TypeError("想定外の固定値型")

        for key in inherited:
            altered = deepcopy(config())
            altered[key] = changed(altered[key])
            with self.assertRaises(ValueError, msg=key):
                I.validate_config(altered)
        for key in config()["SAR"]:
            altered = deepcopy(config())
            altered["SAR"][key] = changed(altered["SAR"][key])
            with self.assertRaises(ValueError, msg="SAR:"+key):
                I.validate_config(altered)

    def test_prepare六十五人工場は先着運用固定を呼ばない(self) -> None:
        """人工空入力で65場の準備分岐を通し、禁止経路へ進めない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。原板や実在cacheを開かない。
        """
        driver = load(HERE / "検証.py", "SAR合成のprepare")
        with tempfile.TemporaryDirectory(prefix="SAR持続合成_") as directory:
            base = Path(directory)
            study, work = base / "試行", base / "作業"
            study.mkdir()
            (study / "条件.json").write_text(json.dumps(config(), ensure_ascii=False), encoding="utf-8")
            source = base / "人工入力"
            source.write_text("", encoding="utf-8")
            stat = source.stat()
            sessions = [f"{date(2026, 9, 21)+timedelta(days=n)}_{kind}" for n in range(20) for kind in ("Day", "Night")]
            sessions += [f"{date(2026, 10, 19)+timedelta(days=n)}_{kind}" for n in range(12) for kind in ("Day", "Night")]
            sessions += [SESSION]
            manifest = {"source_root": str(base), "entries": [{"session": session, "symbol": "NK225", "source_path": source.name,
                        "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns, "cache_path": "存在しない人工cache",
                        "sha256_cache": "人工SHA", "in_session_contract_codes": ["人工限月"]} for session in sessions]}
            original = driver.W.read_json

            def read_json(path: Path) -> dict:
                """人工台帳だけを置換し、一時条件はそのまま読む。

                引数: path (Path) は参照先。
                返り値: dict は人工台帳又は条件。
                """
                return deepcopy(manifest) if path == driver.INPUT else original(path)

            forbidden = SimpleNamespace(replay=unittest.mock.Mock(side_effect=AssertionError("運用は禁止")))
            with patch.object(driver.W, "read_json", side_effect=read_json), patch.object(driver.O, "sha", return_value="人工SHA"), \
                    patch.object(driver.W.PREP, "read_events", return_value=[]), \
                    patch.object(driver.W.OLD, "気配経路", side_effect=AssertionError("先着は禁止")), \
                    patch.object(driver, "module", return_value=forbidden), \
                    patch.object(driver, "freeze", side_effect=AssertionError("固定は禁止")), redirect_stdout(io.StringIO()):
                result = driver.run(study, work, True)
            self.assertFalse(result["ラベル計算"])
            self.assertFalse(result["損益計算"])
            forbidden.replay.assert_not_called()
            summary = json.loads((work / "準備点検.json").read_text(encoding="utf-8"))
            self.assertEqual(len(summary["準備"]), 65)
            self.assertEqual(len(summary["場別発動"]), 130)
            self.assertEqual(len(summary["SAR品質"]), 65)
            self.assertFalse((study / "結果.json").exists())
            self.assertFalse((work / "全運用詳細.jsonl.gz").exists())
            self.assertFalse((work / "SAR.jsonl.gz").exists())


def main() -> None:
    """人工検査と関係6SHAを途中又は編集終了proofへ保存する。

    引数: なし。--finalは全追加と主版停止後に指定する。
    返り値: None。失敗時は終了1。原相場・保存損益・先着ラベルは読まない。
    """
    parser = argparse.ArgumentParser(description="価格イベントとSAR方向持続の人工合成")
    parser.add_argument("--final", action="store_true", help="合成編集終了の最終proof")
    args = parser.parse_args()
    expected = [HERE / name for name in ("指標.py", "入口.py", "運用.py", "検証.py", "合成検証.py")] + [STUDY / "条件.json"]
    paths = [p for p in expected if p.exists()]
    pins = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if args.final and len(paths) != 6:
        raise ValueError("全6pin前は固定不可")
    if args.final and (STUDY / "固定.json").exists():
        frozen = json.loads((STUDY / "固定.json").read_text(encoding="utf-8"))["ファイルSHA256"]
        if any(frozen.get(name) != value for name, value in pins.items()):
            raise ValueError("固定後の追加は別名へ分離する")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    proof = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
             "合成編集終了": bool(args.final and result.wasSuccessful()), "ファイルSHA256": pins,
             "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
             "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors],
             "範囲": "人工OHLCだけでSAR初期同値/strict貫通/前二本制約/EP/AF/事前線と確定後表示/鏡像/carry/reset/NPを検査。固定24価格状態の同値、共通M25、Q0単足MACD対Q1前現SAR持続、初価格event消費、公開時点と診断量不使用。原板・正式先着・損益は実行しない。",
             "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / ("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k: proof[k] for k in ("全件成功", "検証件数", "合成編集終了")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
