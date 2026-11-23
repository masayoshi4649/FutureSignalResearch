"""広域研究の足・指標・六発動を、実相場を読まない合成経路で検証する。"""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
from datetime import datetime, timedelta, timezone
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
ENGINE_PATH = Path(__file__).with_name("検証.py")
SPEC = importlib.util.spec_from_file_location("広域研究の合成対象", ENGINE_PATH)
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)
JST = timezone(timedelta(hours=9))
CONFIG = json.loads((ROOT / "study/00006_外部手法を1分3分5分で比較/条件.json").read_text(encoding="utf-8"))


def quote(now: float, line: int, last: float) -> SimpleNamespace:
    """価格時計と原行を持つ合成状態を作る。

    引数: now (float) は時計秒、line (int) は原始行、last (float) は現在値。
    返り値: SimpleNamespace は正常BBO等を持つ状態。実原板は参照しない。
    """
    return SimpleNamespace(now=now, line=line, last=last, bid=100., ask=101., valid=True,
                           volume=float(line), volume_time=now)


def bar(index: int, close: float = 100., high: float | None = None, low: float | None = None,
        minutes: int = 5, start: float = 0., missing: int = 0) -> dict:
    """一つの完全確定足を合成する。

    引数: index/minutes/missing (int) は場内番号・幅・欠枠、close/high/low/start (float | None) は価格と開始秒。
    返り値: dict はfeaturesへ渡せる確定足。
    """
    begin = start + index * minutes * 60
    return {"index": index, "start": begin, "end": begin + minutes * 60,
            "open": close, "high": close + 1 if high is None else high,
            "low": close - 1 if low is None else low, "close": close,
            "missing": missing, "minutes": minutes, "confirm": begin + minutes * 60,
            "confirm_line": index + 1, "publish": True}


def reflect(bars: list[dict], level: float = 1000.) -> list[dict]:
    """価格を反転し、買い売り対称性を検査する経路を作る。

    引数: bars (list[dict]) は合成OHLC、level (float) は反転の基準和。
    返り値: list[dict] は高安を入れ替えた鏡像経路。
    """
    return [{**item, "open": level - item["open"], "high": level - item["low"],
             "low": level - item["high"], "close": level - item["close"]} for item in bars]


def computed(bars: list[dict]) -> list[dict]:
    """新しい指標状態で合成足の特徴を計算する。

    引数: bars (list[dict]) は合成足列。
    返り値: list[dict] は確定特徴。実データは読まない。
    """
    return engine.features(bars, engine.Indicators(), 0.)


class 固定指標:
    """BB境界だけを指標算式から分離して検証するための既知状態。"""

    def __init__(self, states: list[dict] | None = None) -> None:
        """既知の指標値を順番に返す状態を作る。

        引数: states (list[dict] | None) は各確定足時点で既知の値。
        返り値: None。
        """
        self.states = states or []
        self.index = 0

    def update(self, item: dict) -> dict:
        """次の既知状態を返す。

        引数: item (dict) は対応する合成足。
        返り値: dict は既知の指標値。将来状態は先に返さない。
        """
        values = {"atr": 1., "rsi": 50., "plus_di": 0., "minus_di": 0., "adx": 0.,
                  "ema10": 100., "ema20": 100., "ema10_previous": 100., "ema20_previous": 100.,
                  "bb_mean": None, "bb_sd": None}
        values.update(self.states[self.index])
        self.index += 1
        return values


# ----------------------------------------
# prepareは小さな合成ファイル配置と読取置換だけで動かし、実キャッシュを開かない。

def synthetic_prepare(gap: bool = False, duplicate_boundary: bool = False,
                      future_label: str = "順行先着", add_future: bool = False) -> list[dict]:
    """当場15分足の利用時刻を、実データを持たない一場のprepareで調べる。

    引数: gap/duplicate_boundary/add_future (bool) は欠区間・同時計境界・未使用場の合成、
    future_label (str) は未来列の置換値。
    返り値: list[dict] は合成入口。実際の新4場・既存キャッシュは読まない。
    """
    workspace = ROOT / "work/広域研究"
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="合成入力_", dir=workspace) as name:
        temporary = Path(name).resolve()
        if not temporary.is_relative_to(workspace.resolve()):
            raise AssertionError("合成ファイルが作業領域外")
        project = temporary / "研究"
        project.mkdir()
        session = "2026-01-05_Day"
        source = temporary / "JP_OSE_Data/future/NK225" / session / "book.jsonl"
        source.parent.mkdir(parents=True)
        source.write_text("合成のstat確認専用", encoding="utf-8")
        status = source.stat()
        begin = datetime(2026, 1, 5, 8, 45, tzinfo=JST).timestamp()
        events = []
        for minute in range(416):
            if gap and 310 <= minute < 330:
                continue
            if duplicate_boundary and minute == 315:
                events.append(quote(begin + minute * 60, len(events) + 1, math.nan))
            events.append(quote(begin + minute * 60, len(events) + 1, 100. + minute / 2))
        entry = {"session": session, "source_path": f"NK225/{session}/book.jsonl",
                 "source_size": status.st_size, "source_mtime_ns": status.st_mtime_ns,
                 "cache_path": "キャッシュ/NK225/合成.npz", "sha256_cache": "合成の識別子",
                 "in_session_contract_codes": ["合成限月"]}
        entries = [entry]
        if add_future:
            entries.append({**entry, "session": "2026-11-02_Day",
                            "source_path": "禁止された合成後続を読まない", "cache_path": "禁止された後続.npz"})
        manifest = {"entries": entries}
        config = copy.deepcopy(CONFIG)
        result = {"ラベル": future_label, "理由": "合成の未来列", "新規価格": -999. if future_label == "逆行先着" else 999.,
                  "新規時計秒": None, "判定時計秒": -999., "判定原板行": 999999,
                  "新規原板行": None, "判定気配": -999., "最大順行pt": 100000., "最大逆行pt": 100000., "所要分": 9999.}

        def fake_json(path: Path) -> dict:
            """合成設定または合成台帳を返す。

            引数: path (Path) はprepareの読取要求。
            返り値: dict は実データを持たない二種類の入力。
            """
            return config if path.name == "条件.json" else manifest

        def fake_events(path: Path) -> object:
            """合成一場だけを返し、後続入力へ進んだら失敗させる。

            引数: path (Path) は要求キャッシュ。
            返り値: object は合成状態のイテレータ。
            """
            if path.name != "合成.npz":
                raise AssertionError("探索が後続キャッシュを開こうとした")
            return iter(events)

        with patch.object(engine, "ROOT", project), patch.object(engine, "read_json", side_effect=fake_json), \
                patch.object(engine, "sha", return_value="合成の識別子"), \
                patch.object(engine.PREP, "read_events", side_effect=fake_events), \
                patch.object(engine.OLD.気配経路, "evaluate", return_value=result), redirect_stdout(io.StringIO()):
            rows, _ = engine.prepare(project / "study", "探索")
        return rows


class 足形成検証(unittest.TestCase):
    """半開・確認・欠枠・端数だけを、指標やラベルから独立して検証する。"""

    def test_半開区間と境界観測の除外(self) -> None:
        """境界観測は次足へ入り、直前足の終値に混ざらないことを確認する。

        引数: self (足形成検証) はテスト状態。
        返り値: None。
        """
        for minutes in (1, 3, 5, 15):
            with self.subTest(minutes=minutes):
                width = minutes * 60
                rows = engine.bars_from_events([quote(0, 1, 100), quote(width - .01, 2, 102),
                                                quote(width, 3, 999), quote(width, 4, 888)], 0, width * 2, minutes)
                self.assertEqual((rows[0]["open"], rows[0]["high"], rows[0]["close"]), (100, 102, 102))
                self.assertEqual((rows[0]["confirm"], rows[0]["confirm_line"]), (width, 3))
                self.assertTrue(rows[0]["publish"])
                self.assertEqual((rows[1]["open"], rows[1]["close"]), (999, 888))

    def test_次区間の欠測Lastでも最初の価格時計行が確認(self) -> None:
        """Last欠測行の後へ確認をずらさず、最初の境界原行を使うことを確認する。

        引数: self (足形成検証) はテスト状態。
        返り値: None。
        """
        rows = engine.bars_from_events([quote(0, 1, 100), quote(60, 2, math.nan), quote(60, 3, 101)], 0, 120, 1)
        self.assertEqual((rows[0]["confirm"], rows[0]["confirm_line"]), (60, 2))
        self.assertEqual(rows[1]["open"], 101)

    def test_尾部未確認は発動不可(self) -> None:
        """EOFを直後の市場観測と見なさず、最後の足を非発動にすることを確認する。

        引数: self (足形成検証) はテスト状態。
        返り値: None。
        """
        rows = engine.bars_from_events([quote(0, 1, 100), quote(59, 2, 101)], 0, 180, 1)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["publish"])
        self.assertEqual(rows[0]["confirm_line"], 0)

    def test_3分と15分の尾部端数は完全足へ含めない(self) -> None:
        """Day415分とNight775分の端数足を除外することを確認する。

        引数: self (足形成検証) はテスト状態。
        返り値: None。
        """
        for total in (415, 775):
            for minutes in (1, 3, 5, 15):
                with self.subTest(total=total, minutes=minutes):
                    events = [quote(i * 60, i + 1, 100 + i) for i in range(total + 1)]
                    rows = engine.bars_from_events(events, 0, total * 60, minutes)
                    self.assertEqual(len(rows), total // minutes)
                    self.assertTrue(all(row["end"] <= total * 60 for row in rows))

    def test_欠枠を埋めず先頭と途中の欠枠を数える(self) -> None:
        """欠けた区間を前値足にせず、次の実在足へ欠枠数を付けることを確認する。

        引数: self (足形成検証) はテスト状態。
        返り値: None。
        """
        rows = engine.bars_from_events([quote(60, 1, 100), quote(180, 2, 101), quote(240, 3, 102)], 0, 300, 1)
        self.assertEqual([row["index"] for row in rows], [1, 3, 4])
        self.assertEqual([row["missing"] for row in rows], [1, 1, 0])
        self.assertEqual(rows[0]["confirm"], 180)


class 指標検証(unittest.TestCase):
    """SMA種と前足差分による初期化、Wilder平滑と方向性を検証する。"""

    def test_EMAは期間SMA種と次足更新(self) -> None:
        """EMA10/20の種・前値・平滑値を手計算と比較する。

        引数: self (指標検証) はテスト状態。
        返り値: None。
        """
        state = engine.Indicators()
        values = [state.update(bar(i, i + 1)) for i in range(21)]
        self.assertIsNone(values[8]["ema10"])
        self.assertEqual(values[9]["ema10"], 5.5)
        self.assertEqual(values[10]["ema10_previous"], 5.5)
        self.assertAlmostEqual(values[10]["ema10"], 6.5)
        self.assertIsNone(values[18]["ema20"])
        self.assertEqual(values[19]["ema20"], 10.5)
        self.assertAlmostEqual(values[20]["ema20"], 11.5)

    def test_Wilder初期化15本とADX28本(self) -> None:
        """差分14本とDX14本が揃う本数、および既知の直線経路を確認する。

        引数: self (指標検証) はテスト状態。
        返り値: None。
        """
        state = engine.Indicators()
        values = [state.update(bar(i, 100 + i * 2)) for i in range(29)]
        for key in ("atr", "rsi", "plus_di", "minus_di"):
            self.assertIsNone(values[13][key])
            self.assertIsNotNone(values[14][key])
        self.assertEqual(values[14]["atr"], 3)
        self.assertEqual(values[14]["rsi"], 100)
        self.assertAlmostEqual(values[14]["plus_di"], 200 / 3)
        self.assertEqual(values[14]["minus_di"], 0)
        self.assertIsNone(values[26]["adx"])
        self.assertEqual(values[27]["adx"], 100)

    def test_RSIの既知14差分例(self) -> None:
        """既知終値列からRSIの最初の値を検算する。

        引数: self (指標検証) はテスト状態。
        返り値: None。
        """
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
                  46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        state = engine.Indicators()
        values = [state.update(bar(i, value)) for i, value in enumerate(closes)]
        self.assertAlmostEqual(values[-1]["rsi"], 70.46413502109705)

    def test_ATRは前終値ギャップとWilder更新を含む(self) -> None:
        """H-Lだけでなく前終値距離を使い、14分の1で更新することを確認する。

        引数: self (指標検証) はテスト状態。
        返り値: None。
        """
        state = engine.Indicators()
        for i in range(15):
            value = state.update(bar(i, 100, 101, 99))
        self.assertEqual(value["atr"], 2)
        after = state.update(bar(15, 109.5, 110, 109))
        self.assertAlmostEqual(after["atr"], (13 * 2 + 10) / 14)

    def test_DMI同幅拡大は両DMゼロ(self) -> None:
        """上昇幅と下降幅が等しいoutside足では両DMを同時加算しないことを確認する。

        引数: self (指標検証) はテスト状態。
        返り値: None。
        """
        state = engine.Indicators()
        for i in range(28):
            values = state.update(bar(i, 100, 101 + i, 99 - i))
        self.assertEqual((values["plus_di"], values["minus_di"], values["adx"]), (0, 0, 0))
        self.assertIsNone(values["rsi"])

    def test_完全横ばいのゼロ分母(self) -> None:
        """ATR0、DMI/DX0、上下変化とも0のRSI未定義を確認する。

        引数: self (指標検証) はテスト状態。
        返り値: None。
        """
        state = engine.Indicators()
        for i in range(28):
            values = state.update(bar(i, 100, 100, 100))
        self.assertEqual((values["atr"], values["plus_di"], values["minus_di"], values["adx"]), (0, 0, 0, 0))
        self.assertIsNone(values["rsi"])

    def test_BB20本と母標準偏差(self) -> None:
        """BBの20本準備とddof0を、1〜20の分散33.25へ照合する。

        引数: self (指標検証) はテスト状態。
        返り値: None。
        """
        state = engine.Indicators()
        values = [state.update(bar(i, i + 1)) for i in range(20)]
        self.assertIsNone(values[18]["bb_mean"])
        self.assertEqual(values[19]["bb_mean"], 10.5)
        self.assertAlmostEqual(values[19]["bb_sd"], math.sqrt(33.25))

    def test_指標の鏡像対称(self) -> None:
        """価格反転でRSIとDIが反転し、ATR/ADX/標準偏差は保たれることを確認する。

        引数: self (指標検証) はテスト状態。
        返り値: None。
        """
        randomizer = random.Random(20261104)
        closes = [100.]
        for _ in range(50):
            closes.append(closes[-1] + randomizer.choice([-3., -1., 1., 2.]))
        source = [bar(i, close, close + 2, close - 1) for i, close in enumerate(closes)]
        first, second = engine.Indicators(), engine.Indicators()
        for original, mirrored in zip(source, reflect(source)):
            a, b = first.update(original), second.update(mirrored)
            for key in ("atr", "adx", "bb_sd"):
                if a[key] is not None:
                    self.assertAlmostEqual(a[key], b[key])
            if a["rsi"] is not None:
                self.assertAlmostEqual(a["rsi"] + b["rsi"], 100)
            if a["plus_di"] is not None:
                self.assertAlmostEqual(a["plus_di"], b["minus_di"])
                self.assertAlmostEqual(a["minus_di"], b["plus_di"])


class 発動検証(unittest.TestCase):
    """六発動の今足除外・等号・方向を、既知のチャート配置で検証する。"""

    def test_開始幅突破は幅固定後で端超えが必要(self) -> None:
        """開始15/30分の幅を確定後に固定し、終値の厳密突破だけを採ることを確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        for window in (15, 30):
            length = window // 5
            source = [bar(i, 100, 110, 90) for i in range(length)]
            source += [bar(length, 110, 112, 95), bar(length + 1, 111, 113, 95)]
            values = computed(source)
            self.assertFalse(values[length - 1][f"開始幅突破_{window}_1"])
            self.assertFalse(values[length][f"開始幅突破_{window}_1"])
            self.assertTrue(values[length + 1][f"開始幅突破_{window}_1"])
            self.assertTrue(computed(reflect(source))[length + 1][f"開始幅突破_{window}_-1"])

    def test_開始幅失敗復帰は外側厳密と内側等号(self) -> None:
        """前足は端の外側、復帰終値は両端を含む幅内という条件を確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        for window in (15, 30):
            count = window // 5
            initial = [bar(i, 100, 110, 90) for i in range(count)]
            for close, expected in ((90, True), (110, True), (89, False), (111, False)):
                source = initial + [bar(count, 89, 100, 88), bar(count + 1, close, max(111, close), min(89, close))]
                self.assertEqual(computed(source)[-1][f"開始幅失敗復帰_{window}_1"], expected)
                self.assertEqual(computed(reflect(source))[-1][f"開始幅失敗復帰_{window}_-1"], expected)
            equal_previous = initial + [bar(count, 90, 100, 89), bar(count + 1, 100, 101, 89)]
            self.assertFalse(computed(equal_previous)[-1][f"開始幅失敗復帰_{window}_1"])

    def test_開始幅の初期欠枠を途中からの幅で補わない(self) -> None:
        """開場区間を欠いた場合に、残る観測だけで開始幅を作らないことを確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        source = [bar(1, 100, 110, 90, missing=1), bar(2, 100, 110, 90), bar(3, 111, 112, 90)]
        self.assertFalse(computed(source)[-1]["開始幅突破_15_1"])

    def test_NR4とNR7はstrictで今足を窓へ含めない(self) -> None:
        """前足が直前N本の唯一最小幅であることと、今足の幅を除くことを確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        for length in (4, 7):
            widths = list(range(length + 5, 6, -1))[:length - 1] + [2]
            source = [bar(i, 100, 100 + width / 2, 100 - width / 2) for i, width in enumerate(widths)]
            source.append(bar(length, 102, 10000, 0))
            self.assertTrue(computed(source)[-1][f"狭幅突破_{length}_1"])
            self.assertTrue(computed(reflect(source))[-1][f"狭幅突破_{length}_-1"])
            tied = copy.deepcopy(source)
            tied[0].update(high=101, low=99)
            self.assertFalse(computed(tied)[-1][f"狭幅突破_{length}_1"])
            boundary = copy.deepcopy(source)
            boundary[-1]["close"] = 101
            self.assertFalse(computed(boundary)[-1][f"狭幅突破_{length}_1"])

    def test_NRは次の一本だけで古い狭幅を使い回さない(self) -> None:
        """狭幅直後の一本が外れた後、同じ狭幅条件を再利用しないことを確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        source = [bar(0, 100, 105, 95), bar(1, 100, 104, 96), bar(2, 100, 103, 97),
                  bar(3, 100, 101, 99), bar(4, 100, 103, 97), bar(5, 104, 105, 100)]
        values = computed(source)
        self.assertFalse(values[4]["狭幅突破_4_1"])
        self.assertFalse(values[5]["狭幅突破_4_1"])

    def test_高安端復帰は直前窓だけを使い安値と終値はstrict(self) -> None:
        """今足を過去高安窓へ入れず、割込みと復帰の端点を確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        for length in (10, 20):
            initial = [bar(i, 100, 105, 95) for i in range(length)]
            for low, close, expected in ((94, 96, True), (95, 96, False), (94, 95, False), (94, 105, True), (94, 106, False)):
                source = initial + [bar(length, close, max(close, 106), low)]
                self.assertEqual(computed(source)[-1][f"高安端復帰_{length}_1"], expected)
                self.assertEqual(computed(reflect(source))[-1][f"高安端復帰_{length}_-1"], expected)

    def test_EMA復帰10と20は前足の等号と現在のstrictを区別(self) -> None:
        """前終値と前EMAの等号は許し、今終値とEMA上昇を要求することを確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        source = [bar(i, 100) for i in range(20)] + [bar(20, 101)]
        for length in (10, 20):
            self.assertTrue(computed(source)[-1][f"EMA復帰_{length}_1"])
            self.assertTrue(computed(reflect(source))[-1][f"EMA復帰_{length}_-1"])
            flat = source[:-1] + [bar(20, 100)]
            self.assertFalse(computed(flat)[-1][f"EMA復帰_{length}_1"])

    def test_BBは前帯の外側strictと今帯の内側inclusive(self) -> None:
        """前終値の帯外と今終値の帯上を、2σ/2.5σで確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        for multiple in (2., 2.5):
            boundary = 100 - multiple * 10
            for prior, current, expected in ((boundary - 1, boundary, True), (boundary, boundary, False), (boundary - 1, boundary - .01, False)):
                source = [bar(0, prior), bar(1, current)]
                states = [{"bb_mean": 100., "bb_sd": 10.}] * 2
                values = engine.features(source, 固定指標(states), 0.)
                self.assertEqual(values[-1][f"BB内復帰_{multiple}_1"], expected)
                reflected = engine.features(reflect(source), 固定指標([{"bb_mean": 900., "bb_sd": 10.}] * 2), 0.)
                self.assertEqual(reflected[-1][f"BB内復帰_{multiple}_-1"], expected)

    def test_欠枠は指標と交差とパターン履歴を初期化(self) -> None:
        """場内欠枠の直後を過去EMAや直前窓に接続しないことを確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        source = [bar(i, 100 + i) for i in range(30)] + [bar(32, 150, missing=2)]
        last = computed(source)[-1]
        self.assertFalse(last["has_previous"])
        self.assertIsNone(last["ema10"])
        self.assertIsNone(last["atr"])
        self.assertFalse(last["狭幅突破_4_1"])
        self.assertFalse(last["高安端復帰_10_1"])

    def test_同限月の指標継続と場内交差切断を分ける(self) -> None:
        """指標値を持ち越しても、新場の一足目を前場の交差にしないことを確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        indicator = engine.Indicators()
        engine.features([bar(i, 100) for i in range(30)], indicator, 0.)
        first = engine.features([bar(0, 101, start=10000)], indicator, 10000.)[0]
        self.assertIsNotNone(first["ema20"])
        self.assertFalse(first["has_previous"])
        self.assertFalse(first["EMA復帰_20_1"])
        self.assertFalse(first["BB内復帰_2.0_1"])

    def test_六発動の価格鏡像対称(self) -> None:
        """同じOHLCの鏡像で六発動の買い売りが交換されることを確認する。

        引数: self (発動検証) はテスト状態。
        返り値: None。
        """
        generator = random.Random(157)
        close, source = 100., []
        for i in range(90):
            close += generator.choice([-5., -2., 1., 4.])
            source.append(bar(i, close, close + generator.randint(1, 6), close - generator.randint(1, 6)))
        normal, mirrored = computed(source), computed(reflect(source))
        for original, inverse in zip(normal, mirrored):
            for family, parameters in CONFIG["手法"].items():
                for parameter in parameters:
                    self.assertEqual(original[f"{family}_{parameter}_1"], inverse[f"{family}_{parameter}_-1"])
                    self.assertEqual(original[f"{family}_{parameter}_-1"], inverse[f"{family}_{parameter}_1"])


class 補助と時点検証(unittest.TestCase):
    """補助条件の境界、上位足の確認順、未来ラベル非依存を確認する。"""

    def test_147候補は固定設定の直積で一意(self) -> None:
        """六手法二値三尺度四補助と対照3件の147候補を確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        rules = engine.rules(CONFIG)
        self.assertEqual(len(rules), 147)
        self.assertEqual(len({row["候補ID"] for row in rules}), 147)
        self.assertEqual(sum(row["手法"] == "全時点両方向" for row in rules), 3)

    def test_ADX環境は強さとDI方向を分ける(self) -> None:
        """追随25以上とDI厳密優位、反転20未満の端点を確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        for side in (1, -1):
            rule = {"時間足分": 1, "手法": "EMA復帰", "パラメータ": 10, "補助": "ADX環境"}
            row = {"時間足分": 1, "side": side, f"EMA復帰_10_{side}": True, "adx": 25.,
                   "plus_di": 30. if side == 1 else 10., "minus_di": 10. if side == 1 else 30.}
            self.assertTrue(engine.allowed(row, rule))
            self.assertFalse(engine.allowed({**row, "adx": 24.999}, rule))
            self.assertFalse(engine.allowed({**row, "plus_di": 20., "minus_di": 20.}, rule))
            self.assertFalse(engine.allowed({**row, "adx": None}, rule))
            reverse = {**rule, "手法": "開始幅失敗復帰", "パラメータ": 15}
            row[f"開始幅失敗復帰_15_{side}"] = True
            self.assertTrue(engine.allowed({**row, "adx": 19.999}, reverse))
            self.assertFalse(engine.allowed({**row, "adx": 20.}, reverse))

    def test_RSI帯は方向反転と端点の違いを保つ(self) -> None:
        """追随50〜70未満と反転30〜50以下を買売両方向で確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        for family, parameter, bounds in (("EMA復帰", 10, ((50., True), (69.999, True), (70., False), (49.999, False))),
                                          ("BB内復帰", 2., ((30., True), (50., True), (29.999, False), (50.001, False)))):
            rule = {"時間足分": 3, "手法": family, "パラメータ": parameter, "補助": "RSI帯"}
            for side in (1, -1):
                for directional, expected in bounds:
                    row = {"時間足分": 3, "side": side, f"{family}_{parameter}_{side}": True,
                           "rsi": directional if side == 1 else 100 - directional}
                    self.assertEqual(engine.allowed(row, rule), expected)

    def test_上位方向と尺度の条件(self) -> None:
        """同方向のみを許し、別尺度の行を候補へ流さないことを確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        rule = {"時間足分": 5, "手法": "狭幅突破", "パラメータ": 4, "補助": "上位方向"}
        row = {"時間足分": 5, "side": -1, "狭幅突破_4_-1": True, "上位方向": -1}
        self.assertTrue(engine.allowed(row, rule))
        for direction in (0, 1):
            self.assertFalse(engine.allowed({**row, "上位方向": direction}, rule))
        self.assertFalse(engine.allowed({**row, "時間足分": 1}, rule))

    def test_全規則で未来列を書換えてもallowed不変(self) -> None:
        """新規や到達ラベルを極端な値へ変えても発動判定が変わらないことを確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        for rule in engine.rules(CONFIG):
            for side in (1, -1):
                row = {"時間足分": rule["時間足分"], "side": side, "上位方向": side, "adx": 30.,
                       "plus_di": 30. if side == 1 else 10., "minus_di": 10. if side == 1 else 30.,
                       "rsi": 60. if side == 1 else 40.,
                       f"{rule['手法']}_{rule['パラメータ']}_{side}": True}
                baseline = engine.allowed(row, rule)
                for label in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定"):
                    changed = {**row, "ラベル": label, "新規価格": 1e30, "判定時計秒": -1e30,
                               "最大順行pt": -1e30, "最大逆行pt": 1e30, "所要分": -999.}
                    self.assertEqual(engine.allowed(changed, rule), baseline)

    def test_15分同時確認は同じ原行まで利用可能(self) -> None:
        """1/3/5分と15分が同時確定した時、新しい15分足を利用できることを確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        rows = synthetic_prepare()
        begin = datetime(2026, 1, 5, 8, 45, tzinfo=JST).timestamp()
        same_time = [row for row in rows if row["足終了時計秒"] == begin + 315 * 60]
        self.assertEqual({row["時間足分"] for row in same_time}, {1, 3, 5})
        for row in same_time:
            self.assertEqual(row["上位足終了秒"], row["足終了時計秒"])
            self.assertEqual(row["上位確認秒"], row["要求時計秒"])
            self.assertEqual(row["上位方向"], 1)
        before = next(row for row in rows if row["時間足分"] == 1 and row["足終了時計秒"] == begin + 314 * 60)
        self.assertEqual(before["上位足終了秒"], begin + 300 * 60)

    def test_大きな空白で同時確認しても後の終了足を先読みしない(self) -> None:
        """確認時刻が同じでも、終了が後の上位足を古い下位足へ付けないことを確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        rows = synthetic_prepare(gap=True)
        begin = datetime(2026, 1, 5, 8, 45, tzinfo=JST).timestamp()
        row = next(row for row in rows if row["時間足分"] == 1 and row["足終了時計秒"] == begin + 310 * 60)
        self.assertEqual(row["要求時計秒"], begin + 330 * 60)
        self.assertEqual(row["上位足終了秒"], begin + 300 * 60)
        self.assertEqual(row["ラベル"], "未約定")

    def test_同時計境界の最初の原行で上位も確認(self) -> None:
        """同時計の後続価格行を確認行へすり替えないことを確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        rows = synthetic_prepare(duplicate_boundary=True)
        begin = datetime(2026, 1, 5, 8, 45, tzinfo=JST).timestamp()
        same_time = [row for row in rows if row["足終了時計秒"] == begin + 315 * 60]
        self.assertEqual(len(same_time), 6)
        for row in same_time:
            self.assertEqual(row["要求原板行"], 316)
            self.assertEqual(row["上位確認秒"], row["要求時計秒"])

    def test_prepare未来ラベル置換でも全候補の許可不変(self) -> None:
        """入口生成から未来値を置換しても、147規則の判定が変わらないことを確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        first = synthetic_prepare(future_label="順行先着")
        second = synthetic_prepare(future_label="逆行先着")
        self.assertEqual([row["イベントID"] for row in first], [row["イベントID"] for row in second])
        self.assertGreater(len(first), 0)
        for rule in engine.rules(CONFIG):
            self.assertEqual([engine.allowed(row, rule) for row in first], [engine.allowed(row, rule) for row in second])

    def test_探索は合成後続さえロードしない(self) -> None:
        """後続の架空パスへ進むと失敗する置換で、探索の入力分離を確認する。

        引数: self (補助と時点検証) はテスト状態。
        返り値: None。
        """
        self.assertGreater(len(synthetic_prepare(add_future=True)), 0)


# ----------------------------------------
# 実相場を使わない検証結果と、実行したコード版を記録する。

def flatten(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    """入れ子のテスト一覧を記録用に平坦化する。

    引数: suite (unittest.TestSuite) は検証一覧。
    返り値: list[unittest.TestCase] は各テスト。
    """
    result = []
    for item in suite:
        result.extend(flatten(item) if isinstance(item, unittest.TestSuite) else [item])
    return result


def main() -> None:
    """合成検証を実行し、作業領域へJSONと短い結果を保存する。

    引数: なし。実原板や新4場の事例は入力にしない。
    返り値: None。失敗はJSON保存後に終了コード1にする。
    """
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    names = [case.id() for case in flatten(suite)]
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    failed = {case.id() for case, _ in result.failures + result.errors}
    payload = {"確認日時": datetime.now(JST).isoformat(), "全件通過": result.wasSuccessful(),
               "検証件数": result.testsRun, "失敗数": len(result.failures), "エラー数": len(result.errors),
               "実相場使用": False, "新4場の価格経路結果閲覧": False,
               "範囲": "1/3/5/15分の半開・確認原行・欠枠・端数、指標初期化と既知例、六発動の厳密境界と鏡像、ADX/RSI補助、上位同時確認、未来ラベル非依存、探索での後続非読取。",
               "対象外": "親が修正中のセッション尾部欠枠による次場指標リセットは今回の合成検証対象から除外。真の受信時刻・全約定・実執行の完全性は証明しない。",
               "コードSHA256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in (Path(__file__), ENGINE_PATH)},
               "検証": [{"名前": name, "通過": name not in failed} for name in names],
               "失敗詳細": [{"名前": case.id(), "内容": details} for case, details in result.failures + result.errors]}
    target = ROOT / "work/広域研究/合成検証.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(log.getvalue())
    print(json.dumps({"全件通過": payload["全件通過"], "検証件数": result.testsRun,
                      "失敗数": len(result.failures), "エラー数": len(result.errors)}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
