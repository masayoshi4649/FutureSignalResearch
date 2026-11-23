"""00023の高位公開窓と突破・再テスト・再開を人工足で検査する。"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00023_上位高安の再テストと順行再開"
WORK = ROOT / "work/高安再開"
SESSION = "2026-11-04_Day"


def load(path: Path, name: str) -> object:
    """コマンド行実行せず検査対象APIだけを読む。

    引数:
        path (Path): コードの保存先。
        name (str): モジュール識別名。
    返り値:
        object: 読み込んだモジュール。市場の保存成績は読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


J = load(HERE / "指標.py", "高安再開合成の30分窓")
FIX = load(ROOT / "scripts/異種発動/合成検証.py", "高安再開合成の固定21人工値")
I = load(HERE / "入口.py", "高安再開合成の入口")
O = load(HERE / "運用.py", "高安再開合成の固定運用")


def config() -> dict:
    """正式予定の条件を独立コピーとして読む。

    引数:
        なし。
    返り値:
        dict: 00023条件。保存前だけ人工既定値を使い、最終proofは保存正本が必須。
    """
    path = STUDY / "条件.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {**deepcopy(I.OLD_CONFIG), "時間足分": [3], "戦略": list(I.POLICIES), "価格再開": deepcopy(I.RULES)}


def channel_frame(index: int, **updates: object) -> dict:
    """六本高安を手計算できる完全幅30分足を作る。

    引数:
        index (int): 同場の足番号。
        updates (object): 個別属性の上書き。
    返り値:
        dict: 公開済み30分人工足。
    """
    start = index * 1800
    frame = {"index": index, "minutes": 30, "start": start, "end": start + 1800,
             "confirm": start + 1800, "confirm_line": 10 + index, "publish": True, "missing": 0,
             "open": 1000., "close": 1000., "high": 1100. + index, "low": 900. - index}
    frame.update(updates)
    return frame


def channels(side: int = 1) -> list[dict]:
    """下位足開始前に準備済みの同一高安六本窓を作る。

    引数:
        side (int): 買い1または売り-1。
    返り値:
        list[dict]: 最後が時計3600の公開snapshot。
    """
    frames = []
    for index in range(6):
        start = -7200 + index * 1800
        frames.append(channel_frame(index, start=start, end=start + 1800, confirm=start + 1800,
                                    high=1000 if side == 1 else 1100, low=900 if side == 1 else 1000))
    return J.ChannelBank().build(frames, SESSION, ("NK225", "202612"))[0]


def lower(side: int = 1, count: int = 7) -> list[dict]:
    """設定2・再テスト4・再開6を持つ鏡像の3分系列を作る。

    引数:
        side (int): 売買方向。
        count (int): 必要な足数。
    返り値:
        list[dict]: 全OHLCが整合し、不要なEMA/RSIは未準備の公開足。
    """
    closes = [1000, 1000, 1010, 1010, 1005, 1010, 1020]
    hist = [0, 0, 1, 1, 1, 2, 3]
    frames = []
    for index in range(count):
        close = closes[index] if index < len(closes) else 1020
        h = hist[index] if index < len(hist) else index
        high, low = max(1000, close) + 5, 995 if index == 4 else 1000
        row = FIX.frame(index, 3, open=1000, close=close, high=high, low=low, atr=20, macd_hist=h)
        if side == -1:
            row.update(open=2000 - row["open"], close=2000 - close, high=2000 - low, low=2000 - high,
                       macd_hist=-h, stoch_k=100 - row["stoch_k"])
        frames.append(row)
    return frames


def higher(side: int = 1, ranging: bool = False) -> list[dict]:
    """下位三足より先に準備済みの固定22用15分ペアを作る。

    引数:
        side (int): DIの優勢方向。
        ranging (bool): 非拡大・ADX非上昇のRにするか。
    返り値:
        list[dict]: 当時のS2TまたはS2Rを表す二公開足。
    """
    return [FIX.upper(21 if ranging else 24, side, index=0, start=1800, end=2700,
                      confirm=2700, confirm_line=40, bandwidth=.041 if ranging else .039),
            FIX.upper(20 if ranging else 25, side, index=1, start=2700, end=3600,
                      confirm=3600, confirm_line=50, bandwidth=.04)]


def generate(side: int = 1, frames: list[dict] | None = None, upper: list[dict] | None = None,
             snapshots: list[dict] | None = None, quantity: dict | None = None,
             cutoff: float = 20000, deadline: float = 30000) -> tuple[dict, dict]:
    """人工公開足だけを新入口APIへ渡す。

    引数:
        side (int): 売買方向。frames/upper/snapshots (list[dict]|None): 人工上書き。
        quantity (dict|None): 診断だけの数量。cutoff/deadline (float): 新規停止と返済期限。
    返り値:
        tuple[dict,dict]: 二入口の候補と保存監視診断。
    """
    return I.generate(lower(side) if frames is None else frames, higher(side) if upper is None else upper,
                      SESSION, cutoff, deadline, config(), channels=channels(side) if snapshots is None else snapshots,
                      quantity=quantity)


def actions(quality: dict, index: int) -> list[dict]:
    """指定した人工判断足の監視動作を得る。

    引数:
        quality (dict): 入口APIの品質。
        index (int): 判断する足番号。
    返り値:
        list[dict]: その足の時系列動作。
    """
    return next(row["動作"] for row in quality["監視trace"] if row["index"] == index)


# ----------------------------------------
# 場間で保持する30分公開窓と、場内の過去公表snapshotを区別する。

class 高位公開窓検証(unittest.TestCase):
    """六本準備・carry・欠枠/非公開/限月の境界を検査する。"""

    def test_六本目で高安が準備され七本目は古い一本を外す(self) -> None:
        """高安を現在の下位足や架空値で補わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rows, quality = J.ChannelBank().build([channel_frame(i) for i in range(7)], SESSION, ("NK225", "202612"))
        self.assertEqual([r["30窓準備済"] for r in rows], [False] * 6 + [True, True])
        self.assertEqual((rows[6]["R"], rows[6]["L"]), (1105, 895))
        self.assertEqual([r["index"] for r in rows[7]["30足出典"]], list(range(1, 7)))
        self.assertTrue(all(set(("open", "high", "low", "close")).issubset(row) for row in rows[6]["30足出典"]))
        self.assertEqual(quality["30足数"], 7)

    def test_同限月は場頭carryしpartialは完全欠枠と混同しない(self) -> None:
        """完全足六本を保持し、場末切れ端そのものは窓へ入れない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bank = J.ChannelBank()
        before, _ = bank.build([channel_frame(i) for i in range(6)], SESSION, ("NK225", "202612"))
        carried, _ = bank.build([], "2026-11-04_Night", ("NK225", "202612"), tail_missing=0)
        self.assertTrue(carried[0]["30窓準備済"])
        self.assertEqual(carried[0]["30足出典"], before[-1]["30足出典"])
        new, _ = bank.build([channel_frame(0, start=50000, end=51800, confirm=51800, confirm_line=100)],
                            "2026-11-05_Day", ("NK225", "202612"))
        self.assertTrue(new[0]["30窓準備済"])
        self.assertEqual(new[-1]["30窓本数"], 6)
        self.assertEqual(new[-1]["30足出典"][-1]["場"], "2026-11-05_Day")
        events = [FIX.quote(index * 1800, index + 1, 1000 + index * 5) for index in range(7)]
        events.append(FIX.quote(10814, 8, 1035))
        formed = J.W.bars_from_events(events, 0, 10815, 30)
        self.assertEqual(len(formed), 6)
        self.assertTrue(all(row["publish"] for row in formed))
        self.assertEqual(formed[-1]["end"], 10800)
        actual_bank = J.ChannelBank()
        actual_bank.build(formed, SESSION, ("NK225", "202612"), tail_missing=0)
        carried, _ = actual_bank.build([], "2026-11-04_Night", ("NK225", "202612"))
        self.assertTrue(carried[0]["30窓準備済"])

    def test_完全非公開で内部carryを切っても過去公開snapshotを改訂しない(self) -> None:
        """非公開markerを公表判断にせず、次の公表窓は一本から作る。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        bank = J.ChannelBank()
        frames = [channel_frame(i) for i in range(8)]
        frames[6]["publish"] = False
        rows, _ = bank.build(frames, SESSION, ("NK225", "202612"))
        self.assertTrue(rows[6]["30窓準備済"])
        self.assertFalse(rows[7]["publish"])
        self.assertEqual(rows[7]["30窓本数"], 0)
        self.assertEqual(rows[8]["30窓本数"], 1)
        next_rows, _ = bank.build([], "2026-11-04_Night", ("NK225", "202612"))
        self.assertFalse(next_rows[0]["30窓準備済"])

    def test_末尾完全欠枠と限月変更は次場carryを破棄する(self) -> None:
        """最後の公表snapshotが準備済みでも末尾の実状態を使う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for missing, contract in ((1, ("NK225", "202612")), (0, ("NK225", "202703"))):
            bank = J.ChannelBank()
            rows, _ = bank.build([channel_frame(i) for i in range(6)], SESSION, ("NK225", "202612"), tail_missing=missing)
            self.assertTrue(rows[-1]["30窓準備済"])
            next_rows, _ = bank.build([], "2026-11-04_Night", contract)
            self.assertEqual(next_rows[0]["30窓本数"], 0)

    def test_番号欠枠とmissingは現在有効足から窓を再開始する(self) -> None:
        """古い五本と欠枠後の一本を連結しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"missing": 1}, {"index": 7}):
            current = channel_frame(6)
            current.update(change)
            frames = [channel_frame(i) for i in range(6)] + [current]
            rows, _ = J.ChannelBank().build(frames, SESSION, ("NK225", "202612"))
            self.assertEqual(rows[-1]["30窓本数"], 1)
            self.assertFalse(rows[-1]["30窓準備済"])
        bank = J.ChannelBank()
        bank.build([channel_frame(i) for i in range(6)], SESSION, ("NK225", "202612"))
        rows, _ = bank.build([channel_frame(2)], "2026-11-04_Night", ("NK225", "202612"))
        self.assertEqual(rows[-1]["30窓本数"], 1)

    def test_高安不正を窓へ入れず平坦六本を準備済みにしない(self) -> None:
        """非有限や0と真の高安差0を別々に検査する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for bad in (float("nan"), 0, -5):
            rows, _ = J.ChannelBank().build([channel_frame(i) for i in range(6)] + [channel_frame(6, high=bad)],
                                            SESSION, ("NK225", "202612"))
            self.assertEqual(rows[-1]["30窓本数"], 0)
        rows, _ = J.ChannelBank().build([channel_frame(i, high=1000, low=1000) for i in range(6)],
                                        SESSION, ("NK225", "202612"))
        self.assertFalse(rows[-1]["30窓準備済"])
        self.assertIsNone(rows[-1]["R"])

    def test_公開前時計番号重複と尺度違いは拒否する(self) -> None:
        """公開前を知った扱いや逆順の出典を黙って補正しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        samples = [[channel_frame(0, confirm=1799)], [channel_frame(0), channel_frame(0)],
                   [channel_frame(0, minutes=15)],
                   [channel_frame(0, confirm=3600, confirm_line=50), channel_frame(1, confirm=3600, confirm_line=49)]]
        for frames in samples:
            with self.assertRaises(ValueError):
                J.ChannelBank().build(frames, SESSION, ("NK225", "202612"))

    def test_出典は入力や後続snapshotの変更で書き換わらない(self) -> None:
        """登録時の値と後日の状態を同じdict参照で共有しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = [channel_frame(i) for i in range(7)]
        rows, _ = J.ChannelBank().build(frames, SESSION, ("NK225", "202612"))
        frames[5]["high"] = 99999
        rows[7]["30足出典"][4]["high"] = -999
        self.assertEqual(rows[6]["30足出典"][5]["high"], 1105)


# ----------------------------------------
# b自身で新たに知った上位足を使わず、一つ前の公開pへ結合する。

class 上位窓結合検証(unittest.TestCase):
    """前足の公開時計・原行・終了時点と非公開markerを検査する。"""

    def test_突破足と同時公開の新窓を前足pへ先取りしない(self) -> None:
        """b自身の高安を含む新水準で突破を消したり作ったりしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, snapshots = lower(count=4), channels()
        newer = {**deepcopy(snapshots[-1]), "R": 2000, "confirm": frames[2]["confirm"],
                 "confirm_line": frames[2]["confirm_line"], "end": frames[2]["end"]}
        assigned = I.assign_channel(frames, snapshots + [newer])
        self.assertEqual(assigned[2]["30窓参照"]["R"], 1000)
        self.assertEqual(assigned[3]["30窓参照"]["R"], 2000)
        groups, _ = generate(frames=frames[:3], snapshots=snapshots + [newer])
        self.assertEqual(len(groups["3分_B0"]), 1)

    def test_同秒の後原行とp終了後の足は参照へ入れない(self) -> None:
        """clockだけで同時を扱わず、end条件も独立に要求する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, snapshots = lower(count=3), channels()
        p = frames[1]
        for change in ({"confirm": p["confirm"], "confirm_line": p["confirm_line"] + 1, "end": p["end"]},
                       {"confirm": p["confirm"], "confirm_line": p["confirm_line"], "end": p["end"] + 1}):
            newer = {**deepcopy(snapshots[-1]), "R": 2000, **change}
            self.assertEqual(I.assign_channel(frames, snapshots + [newer])[2]["30窓参照"]["R"], 1000)
        same = {**deepcopy(snapshots[-1]), "R": 1500, "confirm": p["confirm"],
                "confirm_line": p["confirm_line"], "end": p["end"]}
        self.assertEqual(I.assign_channel(frames, snapshots + [same])[2]["30窓参照"]["R"], 1500)

    def test_非公開markerは過去公表を改訂せず次公開未準備から復帰する(self) -> None:
        """古い有効窓へ戻ることと、非公開markerを参照しないことを区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, snapshots = lower(count=4), channels()
        marker = {**deepcopy(snapshots[-1]), "publish": False, "30窓準備済": False,
                  "confirm": frames[1]["confirm"], "confirm_line": frames[1]["confirm_line"], "end": frames[1]["end"]}
        unready = {**deepcopy(marker), "publish": True, "confirm": frames[2]["confirm"],
                   "confirm_line": frames[2]["confirm_line"], "end": frames[2]["end"]}
        assigned = I.assign_channel(frames, snapshots + [marker, unready])
        self.assertTrue(assigned[2]["30窓準備済"])
        self.assertFalse(assigned[3]["30窓準備済"])
        self.assertFalse(assigned[3]["30窓参照"]["30窓準備済"])

    def test_直前下位足が非公開か番号非隣接ならpを補完しない(self) -> None:
        """公開された古い下位足を飛び越し前値へ流用しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"publish": False}, {"index": 5}):
            frames = lower(count=3)
            frames[1].update(change)
            assigned = I.assign_channel(frames, channels())
            self.assertFalse(assigned[2]["30窓準備済"])
            self.assertIsNone(assigned[2]["前3分参照"])


# ----------------------------------------
# 同じepisodeのB0即時とC0後続を、未来の成績なしで人工検査する。

class 突破設定検証(unittest.TestCase):
    """ε丸め・strict突破・方向化勢い・不変設定を検査する。"""

    def test_εは突破ATRの四分の一を五ptへ切り上げる(self) -> None:
        """0付近は最低5pt、20ptちょうどと少し上を別に扱う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        self.assertEqual([I.width(x) for x in (1, 20, 20.0001, 40, 40.0001)], [5, 5, 10, 10, 15])
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                I.width(value)

    def test_買売鏡像で設定二と再テスト四と再開六が一度ずつ発動(self) -> None:
        """同じ経路からB0/C0の入口時点を分け、役割は順行を維持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            groups, quality = generate(side)
            self.assertEqual([r["index"] for r in groups["3分_B0"]], [2])
            self.assertEqual([r["index"] for r in groups["3分_C0"]], [6])
            self.assertEqual(groups["3分_B0"][0]["side"], side)
            self.assertEqual(groups["3分_C0"][0]["役割"], "順行")
            self.assertEqual(quality["設定数"], 1)
            self.assertEqual(quality["監視trace"][4]["監視後"]["再テスト"]["index"], 4)
            self.assertEqual((quality["再テスト登録数"], quality["再開価格消費数"], quality["再開条件採用数"],
                              quality["再開採用数"], quality["対象外足数"]), (1, 1, 1, 1, 2))
            self.assertEqual(quality["終了理由別"], {"再開価格消費": 1})

    def test_突破は現strict前inclusiveでMACD差とS2方向を要求(self) -> None:
        """現在等号、既に前足が外、勢い0、逆方向を新設定にしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            rows = lower(side, 3)
            rows[1]["close"] = 1000 + side * 5
            self.assertEqual(len(generate(side, frames=rows)[0]["3分_B0"]), 1)
            for target, value in (("現在等号", 1000 + side * 5), ("前既突破", 1000 + side * 6), ("勢い0", 0)):
                changed = lower(side, 3)
                if target == "現在等号":
                    changed[2]["close"] = value
                elif target == "前既突破":
                    changed[1]["close"] = value
                    changed[1]["high" if side == 1 else "low"] = value + side * 5
                else:
                    changed[2]["macd_hist"] = changed[1]["macd_hist"]
                self.assertEqual(generate(side, frames=changed)[0]["3分_B0"], [], target)
            self.assertEqual(generate(side, frames=lower(side, 3), upper=higher(-side))[0]["3分_B0"], [])

    def test_設定境界εと出典は後のATRや上位更新に追随しない(self) -> None:
        """再開注文ATRだけは現足を使い、突破ATRを出口へ流用しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, snapshots = lower(), channels()
        frames[4]["atr"], frames[6]["atr"] = 60, 45
        newer = {**deepcopy(snapshots[-1]), "R": 1050, "confirm": frames[3]["confirm"],
                 "confirm_line": frames[3]["confirm_line"], "end": frames[3]["end"]}
        groups, quality = generate(frames=frames, snapshots=snapshots + [newer])
        entry, resumed = groups["3分_B0"][0], groups["3分_C0"][0]
        self.assertEqual((entry["固定設定"]["境界"], resumed["固定設定"]["境界"], resumed["固定設定"]["ε"]), (1000, 1000, 5))
        self.assertEqual(resumed["固定設定"]["設定"]["atr"], 20)
        self.assertEqual(resumed["atr"], 45)
        self.assertEqual(entry["固定設定"]["段階"], "再テスト待ち")
        self.assertIsNone(entry["固定設定"]["再テスト"])
        quality["監視trace"][4]["監視後"]["設定"]["atr"] = -99
        self.assertEqual(entry["固定設定"]["設定"]["atr"], 20)


# ----------------------------------------
# 設定を知る前のヒゲを使わず、最初の再開を後で選び直さない。

class 再テスト再開検証(unittest.TestCase):
    """strict開始、寿命、取消優先、使用済み水準の境界を検査する。"""

    def test_設定公開と開始同値または前の足のヒゲで取り消さない(self) -> None:
        """b次一足のL/Hを設定後の完全足として使わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for delay in (0, 5):
                frames = lower(side)
                frames[2]["confirm"] += delay
                frames[3]["low" if side == 1 else "high"] = 990 if side == 1 else 1010
                groups, quality = generate(side, frames=frames)
                self.assertEqual([r["index"] for r in groups["3分_C0"]], [6])
                self.assertIn("再テスト足対象外", [a["動作"] for a in actions(quality, 3)])

    def test_再テスト帯端等号は許すが境界終値等号は許さない(self) -> None:
        """zoneの閉区間と回復終値のstrictを混同しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for touch in (995, 1005):
                frames = lower(side, 5)
                frames[4].update(open=1010 if side == 1 else 990, close=1010 if side == 1 else 990)
                frames[4]["low" if side == 1 else "high"] = touch if side == 1 else 2000 - touch
                frames[4]["high" if side == 1 else "low"] = 1015 if side == 1 else 985
                _, quality = generate(side, frames=frames)
                self.assertIn("再テスト登録", [a["動作"] for a in actions(quality, 4)])
            frames = lower(side, 5)
            frames[4]["close"] = 1000
            _, quality = generate(side, frames=frames)
            self.assertNotIn("再テスト登録", [a["動作"] for a in actions(quality, 4)])

    def test_再開開始がj公開以下ならcrossもまだ対象にしない(self) -> None:
        """j次一足の終値crossを先取りせず、経過本数だけは進める。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for delay in (0, 5):
                frames = lower(side)
                frames[4]["confirm"] += delay
                frames[5]["close"] = 1020 if side == 1 else 980
                frames[5]["high" if side == 1 else "low"] = 1025 if side == 1 else 975
                groups, quality = generate(side, frames=frames)
                self.assertEqual([r["index"] for r in groups["3分_C0"]], [6])
                self.assertIn("再開足対象外", [a["動作"] for a in actions(quality, 5)])

    def test_再テスト六本目再開三本目を含み次足で満了する(self) -> None:
        """開始不適合足や等号足を飛ばして寿命を延長しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=12)
        for index in range(3, 12):
            frames[index].update(open=1020, close=1020, high=1025, low=1010, macd_hist=index)
        frames[8].update(open=1005, close=1005, high=1010, low=995)
        frames[9].update(open=1005, close=1010, high=1015, low=1000)
        frames[10].update(open=1005, close=1010, high=1015, low=1000)
        frames[11].update(open=1005, close=1020, high=1025, low=1000)
        groups, quality = generate(frames=frames)
        self.assertEqual([r["index"] for r in groups["3分_C0"]], [11])
        self.assertIn("再テスト登録", [a["動作"] for a in actions(quality, 8)])
        late = deepcopy(frames[:10])
        late[8].update(open=1020, close=1020, high=1025, low=1010)
        late[9].update(open=1005, close=1005, high=1010, low=995)
        groups, quality = generate(frames=late)
        self.assertEqual(groups["3分_C0"], [])
        self.assertEqual(quality["エピソード診断"][0]["終了理由"], "再テスト六足満了")
        late = lower(count=9)
        late[6].update(open=1005, close=1010, high=1015, low=1000)
        late[7].update(open=1005, close=1010, high=1015, low=1000)
        late[8].update(open=1005, close=1020, high=1025, low=1000)
        groups, quality = generate(frames=late)
        self.assertEqual(groups["3分_C0"], [])
        self.assertEqual(quality["エピソード診断"][0]["終了理由"], "再開三足満了")

    def test_再開の終値等号は未発動で次のstrictcrossを使う(self) -> None:
        """買jH/売jLそのものを突破済みとしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = lower(side, 8)
            frames[6]["close"] = 1010 if side == 1 else 990
            groups, quality = generate(side, frames=frames)
            self.assertEqual([r["index"] for r in groups["3分_C0"]], [7])
            self.assertNotIn("再開価格消費", [a["動作"] for a in actions(quality, 6)])

    def test_構造失敗は再開crossやS2判定より先で復活しない(self) -> None:
        """帯反対側を飛び越えた足を再テストや再開へ格上げしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = lower(side)
            frames[6]["low" if side == 1 else "high"] = 994 if side == 1 else 1006
            groups, quality = generate(side, frames=frames)
            self.assertEqual(groups["3分_C0"], [])
            self.assertEqual(actions(quality, 6)[0]["理由"], "固定帯を割った構造失敗")
            frames = lower(side, 5)
            frames[4]["low" if side == 1 else "high"] = 994 if side == 1 else 1006
            upper = higher(side) + [FIX.upper(20, side, index=2, start=3600, end=4500, confirm=4500,
                                                    confirm_line=104, bandwidth=.039)]
            _, quality = generate(side, frames=frames, upper=upper)
            self.assertEqual(actions(quality, 4)[0]["理由"], "固定帯を割った構造失敗")

    def test_再開開始不適合でも設定後に始まった足の帯失敗は有効(self) -> None:
        """再開eligibleのj時計を、構造失敗eligibleのb時計へ流用しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower()
        frames[5]["low"] = 994
        groups, quality = generate(frames=frames)
        self.assertEqual(groups["3分_C0"], [])
        self.assertEqual(actions(quality, 5)[0]["理由"], "固定帯を割った構造失敗")

    def test_数値公開不正と同方向T消失は取消し時間不可だけは消費(self) -> None:
        """不正による監視中断を、有限H差非正や時間による要求見送りと分ける。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"atr": None}, {"macd_hist": None}, {"publish": False}, {"missing": 1},
                       {"open": 0}, {"high": 999}, {"confirm": 4891}, {"index": 10}):
            frames = lower()
            frames[6].update(change)
            groups, quality = generate(frames=frames)
            self.assertEqual(groups["3分_C0"], [])
            self.assertEqual(actions(quality, frames[6]["index"])[0]["理由"], "公開数値準備または連続性失効")
        upper = higher() + [FIX.upper(20, index=2, start=3600, end=4500, confirm=4500, confirm_line=104, bandwidth=.039)]
        _, quality = generate(upper=upper)
        self.assertEqual(actions(quality, 4)[0]["理由"], "同方向S2T消失")
        for deadline in (8459, 8460):
            groups, quality = generate(deadline=deadline)
            self.assertEqual(bool(groups["3分_C0"]), deadline == 8460)
            self.assertIn("再開価格消費", [a["動作"] for a in actions(quality, 6)])
        groups, quality = generate(cutoff=4860)
        self.assertEqual(groups["3分_C0"], [])
        self.assertEqual(actions(quality, 6)[0]["動作"], "再開価格消費")

    def test_勢い不成立でも初crossで消費し後の良いcrossへ延ばさない(self) -> None:
        """後から正のH差や建玉状態を得ても同じ再開を選び直さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=9)
        frames[6]["macd_hist"] = frames[5]["macd_hist"]
        frames[7].update(open=1000, close=1000, high=1005, low=995)
        frames[8].update(open=1000, close=1020, high=1025, low=1000, macd_hist=10)
        groups, quality = generate(frames=frames)
        self.assertEqual(groups["3分_C0"], [])
        self.assertEqual(quality["エピソード診断"][0]["終了理由"], "再開価格消費")
        self.assertEqual(actions(quality, 6)[0], {"動作": "再開価格消費", "採用条件可": False, "勢い可": False, "時間可": True})
        self.assertTrue(any(a.get("使用済み") for a in actions(quality, 8)))

    def test_消費同足に新水準を再登録せず次足以後にだけ許す(self) -> None:
        """旧監視の判定を新しい30分水準の登録より先に行う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, snapshots = lower(), channels()
        newer = {**deepcopy(snapshots[-1]), "R": 1010, "confirm": frames[5]["confirm"],
                 "confirm_line": frames[5]["confirm_line"], "end": frames[5]["end"]}
        groups, quality = generate(frames=frames, snapshots=snapshots + [newer])
        self.assertEqual(len(groups["3分_B0"]), 1)
        self.assertEqual(len(groups["3分_C0"]), 1)
        self.assertEqual(actions(quality, 6), [{"動作": "再開価格消費", "採用条件可": True, "勢い可": True, "時間可": True}])

    def test_使用済みは取消後も残すが別境界と次場は別episode(self) -> None:
        """ε変更や取消を同じ水準の再参加許可に使わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=6)
        frames[4]["low"] = 994
        frames[5].update(open=1000, close=1010, high=1015, low=1000, atr=1)
        groups, quality = generate(frames=frames)
        self.assertEqual(len(groups["3分_B0"]), 1)
        self.assertTrue(any(a.get("使用済み") for a in actions(quality, 5)))
        snapshots = channels()
        newer = {**deepcopy(snapshots[-1]), "R": 1010, "confirm": frames[4]["confirm"],
                 "confirm_line": frames[4]["confirm_line"], "end": frames[4]["end"]}
        frames[5].update(close=1020, high=1025)
        groups, _ = generate(frames=frames, snapshots=snapshots + [newer])
        self.assertEqual([r["index"] for r in groups["3分_B0"]], [2, 5])
        args = (lower(), higher(), "2026-11-04_Night", 20000, 30000, config())
        next_groups, _ = I.generate(*args, channels=channels())
        self.assertEqual([r["index"] for r in next_groups["3分_B0"]], [2])

    def test_監視中に別境界の突破があってもglobal一件を置換しない(self) -> None:
        """旧監視の価格水準を新しい上位窓へ追従させない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, snapshots = lower(), channels()
        frames[3].update(close=1020, high=1025)
        newer = {**deepcopy(snapshots[-1]), "R": 1005, "confirm": frames[2]["confirm"],
                 "confirm_line": frames[2]["confirm_line"], "end": frames[2]["end"]}
        groups, quality = generate(frames=frames, snapshots=snapshots + [newer])
        self.assertEqual(quality["設定数"], 1)
        self.assertEqual([r["index"] for r in groups["3分_B0"]], [2])
        self.assertEqual(quality["監視trace"][3]["監視後"]["境界"], 1000)

    def test_同じ境界価格でも逆sideは別の使用済みキーである(self) -> None:
        """価格だけで使用済み集合を作り、反対側episodeまで禁じない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, snapshots = lower(count=6), channels()
        frames[4]["low"] = 994
        frames[5].update(open=1000, close=990, high=1000, low=985, macd_hist=-1)
        newer = {**deepcopy(snapshots[-1]), "R": 1100, "L": 1000, "confirm": frames[4]["confirm"],
                 "confirm_line": frames[4]["confirm_line"], "end": frames[4]["end"]}
        _, old = I.BASE.generate(frames, higher(), SESSION, 20000, 30000, I.OLD_CONFIG)
        old["複合context記録"][-1].update(S2局面="トレンド", S2方向=-1)
        with patch.object(I.BASE, "generate", return_value=({}, old)):
            groups, _ = generate(frames=frames, snapshots=snapshots + [newer])
        self.assertEqual([r["side"] for r in groups["3分_B0"]], [1, -1])
        self.assertEqual([r["固定設定"]["境界"] for r in groups["3分_B0"]], [1000, 1000])

    def test_時間不可では新設定を登録せず数値共通Mとは分ける(self) -> None:
        """停止時刻等号と残60分未満を数値未準備として隠さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for cutoff, deadline in ((4140, 30000), (20000, 7739)):
            groups, quality = generate(frames=lower(count=3), cutoff=cutoff, deadline=deadline)
            self.assertTrue(quality["複合context記録"][-1]["共通M準備"])
            self.assertEqual(quality["設定数"], 0)
            self.assertEqual(groups["3分_B0"], [])
            self.assertIn("新登録時間不可", quality["監視trace"][-1]["新設定除外理由"])


# ----------------------------------------
# 取消・満了の診断範囲を限定し、反転と共通Mを順行と同じ正本へ合わせる。

class 診断と反転整合検証(unittest.TestCase):
    """寿命優先・内側終値・旧R1・数量非関与・全採否copyを検査する。"""

    def test_第七足第四足は帯失敗や内復帰より満了を優先する(self) -> None:
        """寿命を終えた最初の足を監視中の価格反応へ含めない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=10)
        for index in range(3, 9):
            frames[index].update(open=1020, close=1020, high=1025, low=1010)
        frames[9].update(open=950, close=950, high=960, low=940)
        _, quality = generate(frames=frames)
        episode = quality["エピソード診断"][0]
        self.assertEqual(episode["終了理由"], "再テスト六足満了")
        self.assertIsNone(episode["最初帯割れ"])
        self.assertIsNone(episode["最初内側終値"])
        frames = lower(count=9)
        for index in (6, 7):
            frames[index].update(open=1005, close=1010, high=1015, low=1000)
        frames[8].update(open=950, close=950, high=960, low=940)
        _, quality = generate(frames=frames)
        episode = quality["エピソード診断"][0]
        self.assertEqual(episode["終了理由"], "再開三足満了")
        self.assertIsNone(episode["最初帯割れ"])
        self.assertIsNone(episode["最初内側終値"])

    def test_内復帰はLとRのstrict内側だけで取消同足を含む(self) -> None:
        """一方の境界を越えただけや反対端到達を内側へ一括しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for close, inside, equal, opposite in ((1000, False, True, False), (950, True, False, False),
                                               (900, False, True, True), (890, False, False, True)):
            frames = lower(count=6)
            frames[4].update(open=close, close=close, high=max(close, 1000), low=min(close, 994))
            frames[5].update(open=950, close=950, high=960, low=940)
            _, quality = generate(frames=frames)
            episode = quality["エピソード診断"][0]
            self.assertEqual(episode["最初内側終値"] is not None, inside)
            self.assertEqual(episode["最初境界等号"] is not None, equal)
            self.assertEqual(episode["最初反対端到達"] is not None, opposite)
            if inside:
                self.assertEqual(episode["最初内側終値"]["index"], 4)
            self.assertEqual(episode["終了理由"], "固定帯を割った構造失敗")

    def test_未公開不正や取消後の内復帰を後入れしない(self) -> None:
        """監視終了後の未来足から診断を遡及補完しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"publish": False}, {"atr": None}):
            frames = lower(count=6)
            frames[4].update(open=950, close=950, high=960, low=940, **change)
            frames[5].update(open=950, close=950, high=960, low=940)
            _, quality = generate(frames=frames)
            self.assertIsNone(quality["エピソード診断"][0]["最初内側終値"])
        frames = lower(count=6)
        frames[4]["low"] = 994
        frames[5].update(open=950, close=950, high=960, low=940)
        _, quality = generate(frames=frames)
        self.assertIsNone(quality["エピソード診断"][0]["最初内側終値"])

    def test_未準備数量や未来診断値を変えて価格状態と採否を変えない(self) -> None:
        """数量は付記だけで、欠測や大きなRVOLを共通Mに足さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        base_groups, base_quality = generate()
        quantity = {index: {"数量準備済": index % 2 == 0, "RVOL": None if index % 2 else 9999,
                             "観測差分量": -1, "仮250先着": index % 2 == 0} for index in range(7)}
        groups, quality = generate(quantity=quantity)
        self.assertEqual(quality["監視trace"], base_quality["監視trace"])
        self.assertEqual(quality["エピソード診断"], base_quality["エピソード診断"])
        for source in groups:
            self.assertEqual([r["イベントID"] for r in groups[source]], [r["イベントID"] for r in base_groups[source]])
            for before, after in zip(base_groups[source], groups[source]):
                self.assertEqual({k: v for k, v in before.items() if k != "数量診断"},
                                 {k: v for k, v in after.items() if k != "数量診断"})
        self.assertTrue(all(c["共通M準備"] == b["共通M準備"] for b, c in zip(base_quality["複合context記録"], quality["複合context記録"])))

    def test_旧R1は二戦略同じ発動で新30窓不明ならshadowだけ残す(self) -> None:
        """反転そのものを変更せず、追加共通準備で除いた元Rを消さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = [FIX.frame(i, 3, close=995 if side == 1 else 1005,
                                stoch_k=([10, 20, 21] if side == 1 else [90, 80, 79])[i]) for i in range(3)]
            upper = higher(side, True)
            groups, quality = generate(side, frames=frames, upper=upper)
            _, old = I.BASE.generate(frames, upper, SESSION, 20000, 30000, I.OLD_CONFIG)
            original = next(r for r in old["全Q発動記録"] if r["入口系統"] == "R1")
            for source in ("3分_B0", "3分_C0"):
                self.assertEqual(len(groups[source]), 1)
                self.assertEqual(groups[source][0]["旧22R1"], original)
                self.assertEqual(groups[source][0]["役割"], "反転")
            empty, absent = generate(side, frames=frames, upper=upper, snapshots=[])
            self.assertTrue(all(not values for values in empty.values()))
            self.assertEqual(absent["旧R1発動数"], 1)
            self.assertEqual(len(absent["全Q発動記録"]), 1)
            self.assertFalse(absent["全Q発動記録"][0]["戦略判定"]["B0"]["採用"])

    def test_T監視をRで取消した同足にも旧R1を受け付ける(self) -> None:
        """同足新T設定禁止を、独立のR候補禁止へ拡大しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=5)
        frames[3]["stoch_k"], frames[4]["stoch_k"] = 20, 21
        frames[4].update(open=995, close=995, high=1000, low=995)
        upper = higher() + [FIX.upper(20, index=2, start=3600, end=4500, confirm=4500, confirm_line=104, bandwidth=.039)]
        groups, quality = generate(frames=frames, upper=upper)
        self.assertEqual(actions(quality, 4)[0]["理由"], "同方向S2T消失")
        self.assertEqual([r["入口系統"] for r in groups["3分_B0"]], ["T突破", "R1"])
        self.assertEqual([r["入口系統"] for r in groups["3分_C0"]], ["R1"])

    def test_競合確定後の第二passで全caseの全採否を複写する(self) -> None:
        """一方の戦略でだけ競合した場合も他方caseへ古い表示を残さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, upper = lower(count=3), higher()
        _, old = I.BASE.generate(frames, upper, SESSION, 20000, 30000, I.OLD_CONFIG)
        old["複合context記録"][-1].update(S2局面="レンジ", S2方向=0)
        old["全Q発動記録"].append({"index": 2, "入口系統": "R1", "side": -1, "発動ID": "人工R1競合"})
        with patch.object(I.BASE, "generate", return_value=({}, old)), patch.object(I, "trend", return_value=True):
            groups, quality = generate(frames=frames, upper=upper)
        self.assertEqual(groups["3分_B0"], [])
        self.assertEqual(len(groups["3分_C0"]), 1)
        canonical = {r["発動ID"]: r for r in quality["全Q発動記録"]}
        case = groups["3分_C0"][0]
        self.assertEqual(case["戦略判定"], canonical[case["発動ID"]]["戦略判定"])
        self.assertFalse(case["戦略判定"]["B0"]["採用"])
        self.assertTrue(case["戦略判定"]["B0"]["同時競合"])
        case["旧22R1"]["side"] = 999
        self.assertEqual(canonical[case["発動ID"]]["旧22R1"]["side"], -1)


# ----------------------------------------
# 出口の読取再用と、件数prepareが市場先着・運用を呼ばないことを確認する。

class 固定運用と準備検証(unittest.TestCase):
    """二候補定義、A5一秒会計、prepare禁止経路を検査する。"""

    def test_指標銀行と運用は固定21公開APIそのものである(self) -> None:
        """新しいepisodeのために既存A5出口や指標を複製変更しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        self.assertIs(J.Indicators, J.BASE.Indicators)
        self.assertIs(J.features, J.BASE.features)
        self.assertIs(O.replay, O.BASE.replay)
        self.assertIs(O.trail_parameters, O.BASE.trail_parameters)
        self.assertEqual(O.trail_parameters(20.001), (5, 25))

    def test_生成C0をA5一秒BBOと往復費用へ接続する(self) -> None:
        """買Ask/売Bid新規、追尾要求後の同秒次行不可と同値費用赤字を確認する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            groups, _ = generate(side)
            signals = groups["3分_C0"]
            now = signals[0]["要求時計秒"]
            quotes = [FIX.quote(now, 106), FIX.quote(now + 1, 107),
                      FIX.quote(now + 2, 108, 1010 if side == 1 else 990),
                      FIX.quote(now + 3, 109, 1005 if side == 1 else 995),
                      FIX.quote(now + 3, 110, 1005 if side == 1 else 995),
                      FIX.quote(now + 4, 111, 1005 if side == 1 else 995), FIX.quote(now + 7201, 200)]
            suppressed = {**deepcopy(signals[0]), "要求時計秒": now + 2, "要求原板行": 108,
                          "イベントID": "保有中別反転", "役割": "反転", "side": -side}
            args = (quotes, signals + [suppressed], [], SESSION, "人工23", config()["運用"],
                    {"出口ID": "X0"}, "混合", (now - 100, now + 7300, now + 3600, now + 7200))
            state, info = O.replay(*deepcopy(args))
            old, old_info = FIX.O.replay(*deepcopy(args))
            self.assertEqual((state.fills, state.trades, state.orders, info), (old.fills, old.trades, old.orders, old_info))
            self.assertEqual(len(state.trades), 1)
            trade = state.trades[0]
            self.assertEqual((trade["追尾起動"], trade["基準純損益円"], trade["手数料円"]), (True, -22, 22))
            self.assertEqual((trade["入口役割"], trade["返済時計秒"]), ("順行", now + 4))
            self.assertEqual(trade["新規価格"], 1005 if side == 1 else 1000)
            self.assertEqual(trade["返済理由"], "必須利益追尾")

    def test_二候補と空足零を保持し固定閾値の変更を拒否する(self) -> None:
        """3分以外や追加出口を候補へ黙って混入しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "高安再開合成のdriver")
        self.assertEqual([r["入口ID"] for r in driver.sources(config())], ["3分_B0", "3分_C0"])
        groups, quality = driver.generate_or_empty([], [], SESSION, 3, 20000, 30000, config(), [], [], {})
        self.assertEqual(groups, {"3分_B0": [], "3分_C0": []})
        self.assertEqual(quality["監視trace"], [])
        for changed in ({"時間足分": [1, 3]}, {"戦略": ["B0", "C0", "C1"]},
                        {"価格再開": {**I.RULES, "再テスト上限本数": 7}}):
            with self.assertRaises(ValueError):
                I.validate_config({**config(), **changed})
        with self.assertRaises(ValueError):
            driver.sources({**config(), "出口": [{"出口ID": "X1"}]})
        changed_values = [(('運用', '片道手数料円'), 12), (('必須追尾', '起動幅pt'), 10),
                          (('指標', 'MACD'), [11, 26, 9]), (('入口支持', '学習', '約定候補数'), 59),
                          (('目標確認率',), .6), (('分割', '選択開始日'), '2026-10-20'),
                          (('確認遅延上限秒',), 31), (('逆行pt',), 120)]
        for keys, value in changed_values:
            altered = deepcopy(config())
            parent = altered
            for key in keys[:-1]:
                parent = parent[key]
            parent[keys[-1]] = value
            with self.assertRaises(ValueError, msg=str(keys)):
                I.validate_config(altered)
        with patch.object(I.BASE, "generate", wraps=I.BASE.generate) as original:
            generate()
        self.assertEqual(original.call_args.args[5], I.OLD_CONFIG)
        self.assertNotEqual(original.call_args.args[5]["戦略"], config()["戦略"])

    def test_時間外の価格消費shadowは対象外で先着APIを呼ばない(self) -> None:
        """対象外を未約定や通常五分類の分母へ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "高安再開合成の対象外ラベル")
        groups, quality = generate(cutoff=4860)
        record = next(row for row in quality["全Q発動記録"] if row["入口系統"] == "T再開")
        self.assertFalse(record["先着評価対象"])
        self.assertEqual(groups["3分_C0"], [])
        self.assertEqual(quality["先着評価対象外数"], 1)
        self.assertEqual(quality["再開価格消費数"], 1)
        forbidden = SimpleNamespace(evaluate=unittest.mock.Mock(side_effect=AssertionError("時間外先着は禁止")))
        label = driver.shadow_label(record, forbidden, {}, 4860, 30000, config())
        self.assertEqual((label["ラベル"], label["理由"]), ("対象外", "要求時間条件外"))
        numeric = {key: value for key, value in label.items() if key not in ("ラベル", "理由")}
        self.assertEqual(len(numeric), 9)
        self.assertTrue(all(value is None for value in numeric.values()))
        forbidden.evaluate.assert_not_called()
        with self.assertRaises(ValueError):
            driver.shadow_label({**record, "先着評価対象": True}, forbidden, {}, 4860, 30000, config())
        forbidden.evaluate.assert_not_called()

    def test_時間内で勢い不可の価格eventは通常先着を一度だけ評価できる(self) -> None:
        """採用不可と観測の対象外を混同せず、同要求評価のcacheを共有する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "高安再開合成の通常ラベル")
        frames = lower()
        frames[6]["macd_hist"] = frames[5]["macd_hist"]
        _, quality = generate(frames=frames)
        record = next(row for row in quality["全Q発動記録"] if row["入口系統"] == "T再開")
        self.assertTrue(record["先着評価対象"])
        self.assertFalse(record["戦略判定"]["C0"]["採用"])
        path = SimpleNamespace(evaluate=unittest.mock.Mock(return_value={"ラベル": "逆行先着", "診断用人工値": True}))
        cache = {}
        a = driver.shadow_label(record, path, cache, 20000, 30000, config())
        b = driver.shadow_label(record, path, cache, 20000, 30000, config())
        self.assertEqual(a, b)
        path.evaluate.assert_called_once_with(4860, 20000, 30000, 1, adverse=125, favorable=250)

    def test_prepareは六十五人工場でも先着運用固定を呼ばない(self) -> None:
        """件数専用の実分岐へ禁止呼出を仕掛け、原データを使わず通す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "高安再開合成のprepare")
        with tempfile.TemporaryDirectory(prefix="高安再開合成_") as directory:
            base = Path(directory)
            study, work = base / "試行", base / "作業"
            study.mkdir()
            (study / "条件.json").write_text(json.dumps(config(), ensure_ascii=False), encoding="utf-8")
            source = base / "人工入力"
            source.write_text("", encoding="utf-8")
            stat = source.stat()
            sessions = [f"{date(2026, 9, 21) + timedelta(days=n)}_{kind}" for n in range(20) for kind in ("Day", "Night")]
            sessions += [f"{date(2026, 10, 19) + timedelta(days=n)}_{kind}" for n in range(12) for kind in ("Day", "Night")]
            sessions += ["2026-11-04_Day"]
            manifest = {"source_root": str(base), "entries": [{"session": session, "symbol": "NK225", "source_path": source.name,
                        "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns, "cache_path": "存在しない人工cache",
                        "sha256_cache": "人工SHA", "in_session_contract_codes": ["人工限月"]} for session in sessions]}
            original = driver.W.read_json

            def read_json(path: Path) -> dict:
                """人工台帳だけ置き換え、条件は一時ファイルから読む。

                引数: path (Path) は参照先。
                返り値: dict は人工台帳または人工条件。
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
            self.assertTrue((work / "準備点検.json").exists())
            self.assertFalse((study / "結果.json").exists())
            self.assertFalse((work / "全運用詳細.jsonl.gz").exists())
            summary = json.loads((work / "準備点検.json").read_text(encoding="utf-8"))
            self.assertEqual(len(summary["準備"]), 65)
            self.assertEqual(len(summary["場別発動"]), 130)
            self.assertTrue(all(row["再開価格消費数"] == 0 and row["先着評価対象外数"] == 0 for row in summary["準備"]))


# ----------------------------------------
# 最終通知までは途中proofだけ保存し、自分では固定・正式再生しない。

def main() -> None:
    """人工足だけを実行して途中または最終の合成proofを保存する。

    引数:
        なし。--finalは主API変更停止・全検査追加後にだけ指定する。
    返り値:
        None: work配下へproofを保存し、不成功時は終了コード1。
    """
    parser = argparse.ArgumentParser(description="上位高安の突破・再テスト・再開の人工合成")
    parser.add_argument("--final", action="store_true", help="合成編集終了の最終proof")
    args = parser.parse_args()
    expected_paths = [HERE / name for name in ("指標.py", "入口.py", "運用.py", "検証.py", "合成検証.py")]
    expected_paths.append(STUDY / "条件.json")
    paths = [path for path in expected_paths if path.exists()]
    pins = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if args.final and len(paths) != 6:
        raise ValueError("全6pinが揃う前は固定不可")
    if args.final and (STUDY / "固定.json").exists():
        frozen = json.loads((STUDY / "固定.json").read_text(encoding="utf-8"))["ファイルSHA256"]
        if any(frozen.get(name) != digest for name, digest in pins.items()):
            raise ValueError("固定後の追加は別ファイルへ分離する")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    proof = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
             "合成編集終了": bool(args.final and result.wasSuccessful()), "ファイルSHA256": pins,
             "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
             "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors],
             "範囲": "人工30分公開六本窓/carry/欠枠/非公開/限月/前pのend原行asof、3分突破ε/鏡像/不変snapshot、再テスト1〜6/再開1〜3とstrict開始、寿命/失敗/局面消失/時間不可消費、global監視と使用済みside境界、strict内復帰/取消後未追跡、固定22R1/全競合確定後copy、数量非関与、固定21A5一秒BBO費用同値、数値継承変更拒否、時間外shadow先着不呼出、prepare人工65場のラベル/運用/固定呼出禁止。原板・市場先着・損益は実行しない。",
             "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / ("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({key: proof[key] for key in ("全件成功", "検証件数", "合成編集終了")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
