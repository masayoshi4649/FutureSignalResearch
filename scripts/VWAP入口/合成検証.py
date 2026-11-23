"""00018の公開原行結合・同epoch四点・役割別位置を人工データで確認する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00018_VWAPの位置と傾きで順行反転を比較"
WORK = ROOT/"work/VWAP入口"
JST = timezone(timedelta(hours=9))
START = datetime(2026, 11, 4, 8, 45, tzinfo=JST).timestamp()
SESSION = "2026-11-04_Day"


def load(path: Path, name: str) -> object:
    """対象の純粋APIをコマンド行実行せず読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: object はmodule。市場cacheや原板は読み取らない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


R = load(HERE/"参照.py", "VWAP合成の参照")
I = load(HERE/"入口.py", "VWAP合成の入口")
D = load(HERE/"検証.py", "VWAP合成のdriver")
RAW = R.PREP


def config() -> dict:
    """条件正本のコピーを返す。

    引数: なし。
    返り値: dict は00018条件。市場結果は読み込まない。
    """
    return json.loads((STUDY/"条件.json").read_text(encoding="utf-8"))


def stamp(value: float | None) -> str | None:
    """人工Unix時計を原板形式へ写す。

    引数: value (float|None) は人工時計。
    返り値: str|None はISO時計または欠測。
    """
    return datetime.fromtimestamp(value, JST).isoformat() if value is not None else None


def frame(index: int, minutes: int = 1, **updates: object) -> dict:
    """公開済み価格足と準備済み指標の人工値を作る。

    引数: index/minutes (int) は番号/足幅、updates (object) は上書き。
    返り値: dict は旧価格入口にも渡せる人工特徴。
    """
    start = START+index*minutes*60
    value = {"index": index, "minutes": minutes, "start": start, "end": start+minutes*60,
             "confirm": start+minutes*60, "confirm_line": index+100, "publish": True, "missing": 0,
             "open": 60000, "high": 60030, "low": 59970, "close": 60000,
             "ema20": 60000, "ema20_previous": 59990, "atr": 100, "adx": 10,
             "rsi": 50, "bb_mean": 60000, "bb_sd": 100, "has_previous": True}
    value.update(updates)
    return value


def raw(now: float | None, volume: float = 200, native: float = 60000, **updates: object) -> dict:
    """内部比率が一致する人工の配信状態を作る。

    引数: now (float|None) は時計、volume/native (float) は量/配信値、updates (object) は上書き。
    返り値: dict は17parserへ渡す原板形式。実市場行は含まない。
    """
    value = {"Symbol": "合成限月A", "Exchange": 2, "ExchangeName": "合成市場",
             "CurrentPriceTime": stamp(now), "CurrentPrice": 60000,
             "TradingVolume": volume, "TradingVolumeTime": stamp(now),
             "VWAP": native, "TradingValue": volume*native*1000,
             "OpeningPrice": 59900, "OpeningPriceTime": "2026-11-03T17:00:00+09:00"}
    value.update(updates)
    return value


def events(rows: list[dict], lines: list[int] | None = None,
           repeats: list[int] | None = None) -> tuple[list, dict]:
    """人工原板を固定17parserへ通し12列Eventを作る。

    引数: rows (list[dict]) は原行順、lines/repeats (list[int]|None) は物理行/省略数。
    返り値: tuple[list,dict] はEvent列と原識別対応表。
    """
    codes, markets, cache, output = [], [], {}, []
    for index, row in enumerate(rows):
        event = RAW.parse_record(deepcopy(row), lines[index] if lines else index+1, cache, codes, markets)
        output.append(event._replace(repeat=repeats[index]) if repeats else event)
    return output, {"contract_codes": codes, "exchange_values": markets}


def history(count: int = 8, prefix: bool = True) -> tuple[list[dict], list[dict]]:
    """連続足と各公開原行ちょうどの人工補助行を作る。

    引数: count (int) は足数、prefix (bool) は06時既知基準の有無。
    返り値: tuple[list[dict],list[dict]] は価格足/原板形式行。
    """
    rows = [raw(START-9900, 100, 60000)] if prefix else []
    frames = []
    for offset in range(count):
        row = frame(15+offset, confirm_line=offset+1+int(prefix))
        frames.append(row)
        rows.append(raw(row["confirm"], 200+100*offset, 60000+10*offset))
    return frames, rows


def build(frames: list[dict], rows: list[dict], **metadata_updates: object) -> tuple[dict, dict]:
    """人工列だけで足参照APIを実行する。

    引数: frames/rows (list[dict]) は人工足/原行、metadata_updates (object) は対応表付加情報。
    返り値: tuple[dict,dict] は足参照と品質。
    """
    source, metadata = events(rows)
    metadata.update(metadata_updates)
    return R.build(source, frames, SESSION, metadata, config())


def ready_reference(**updates: object) -> dict:
    """役割別選別だけを分離するため既知四点参照を作る。

    引数: updates (object) は上書き参照属性。
    返り値: dict はN/D準備済みの人工参照。
    """
    value = {"配信VWAP": 100, "当場差分VWAP": 110, "配信3足前VWAP": 95, "差分3足前VWAP": 105,
             "補助epoch": 0, "identity": {}, "native有効": True, "差分有効": True,
             "N共通準備": True, "D共通準備": True, "補助参照": {"line": 1}, "N除外理由": [], "D除外理由": []}
    value.update(updates)
    return value


def select(family: str = "T1", side: int = 1, close: float = 105,
           reference: dict | None = None) -> tuple[set[str], dict, list]:
    """価格Pを一件に固定し、VWAP追加条件だけを検査する。

    引数: family (str) はT1/R2、side (int) は実入口側、close (float) は終値、reference (dict|None) は人工参照。
    返り値: tuple[set[str],dict,list] は通過設定名/品質/信号列。価格条件の計算とは分離する。
    """
    current = frame(21, close=close)
    signal = {**current, "場": SESSION, "時間足分": 1, "side": side, "イベントID": "人工価格P",
              "入口ID": f"1分_{family}", "入口系統": family,
              "要求時計秒": current["confirm"], "要求原板行": current["confirm_line"], "確認遅延秒": 0}
    original = {f"1分_{name}": [signal] if name == family else [] for name in I.BASE.FAMILIES}
    refs = {21: deepcopy(reference if reference is not None else ready_reference())}
    with patch.object(I.BASE, "generate", return_value=(original, {})):
        output, quality = I.generate([current], [], SESSION, START+22000, START+24000, config(), refs)
    signals = [row for rows in output.values() for row in rows]
    return {row["補助"] for row in signals}, quality, signals


# ----------------------------------------
# 価格終端ではなく判断公開時計/原行までの最新補助だけを参照する。

class 原順結合検証(unittest.TestCase):
    """同時計・repeat・不正最新行を原順で扱う。"""

    def test_足終端と判断時点を分ける(self) -> None:
        """確認行で更新した値を使い、前足終端値とは呼ばない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(15, confirm_line=3)
        current["confirm"] += 1
        result, _ = build([current], [raw(START-9900, 100), raw(current["end"], 200, 60000), raw(current["confirm"], 300, 60100)])
        self.assertEqual(result[15]["配信VWAP"], 60100)
        self.assertEqual(result[15]["補助参照"]["line"], 3)

    def test_同時計の次原行を混ぜない(self) -> None:
        """同秒でも判断より後の単独VWAP更新は参照しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(15, confirm_line=2)
        result, _ = build([current], [raw(START-9900, 100), raw(current["confirm"], 200, 60000), raw(current["confirm"], 300, 60100)])
        self.assertEqual(result[15]["配信VWAP"], 60000)
        self.assertEqual(result[15]["補助参照"]["line"], 2)

    def test_原行が完全一致しなくても既知の直前状態を使う(self) -> None:
        """旧cacheで省略された判断行でもheadが既知なら状態を結合する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(15, confirm_line=5)
        source, metadata = events([raw(START-9900, 100), raw(current["confirm"], 200)], [1, 4])
        refs, _ = R.build(source, [current], SESSION, metadata, config())
        self.assertTrue(refs[15]["native有効"])
        self.assertEqual(refs[15]["補助参照"]["line"], 4)

    def test_repeat途中の判断は先頭で既知の状態を使う(self) -> None:
        """完全同一runの末尾を待たず、次の別更新は取り込まない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(15, confirm_line=4)
        source, metadata = events([raw(START-9900, 100), raw(current["confirm"], 200), raw(current["confirm"], 300, 60100)], [1, 2, 7], [1, 5, 1])
        refs, _ = R.build(source, [current], SESSION, metadata, config())
        self.assertEqual(refs[15]["配信VWAP"], 60000)
        self.assertEqual(refs[15]["補助参照"]["repeat"], 5)

    def test_補助最大keyが先行後に時計だけ戻っても救済しない(self) -> None:
        """未来時計の原行を先に見た後、timestampソートで後退行を正常化しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(15, confirm_line=3)
        refs, quality = build([current], [raw(START-9900, 100), raw(current["confirm"]+60, 200), raw(current["confirm"], 300)])
        self.assertFalse(refs[15]["native有効"])
        self.assertIn("価格時計原行後退", refs[15]["補助参照"]["現在不可理由"])
        self.assertEqual(refs[15]["補助参照"]["最大既知キー"], [current["confirm"]+60, 2])
        self.assertEqual(quality["後退除外状態数"], 1)

    def test_不正な最新値から古い正常値へ戻らない(self) -> None:
        """欠測時計/量時計先行/不整合/identity欠測/Last0を不可として保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(15, confirm_line=3)
        for change in ({"CurrentPriceTime": None}, {"TradingVolumeTime": stamp(current["confirm"]+1)},
                       {"VWAP": 61000}, {"OpeningPriceTime": None}, {"CurrentPrice": 0}):
            with self.subTest(不正=change):
                refs, _ = build([current], [raw(START-9900, 100), raw(current["confirm"], 200), raw(current["confirm"], 300, **change)])
                self.assertFalse(refs[15]["native有効"])
                self.assertIsNone(refs[15]["配信VWAP"])
                self.assertEqual(refs[15]["補助参照"]["line"], 3)

    def test_同時計単独更新の前後で値を区別する(self) -> None:
        """同じLastでもnative/代金が更新した後の公開原行だけで新値を使う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        first, second = frame(15, confirm_line=2), frame(16, confirm_line=3)
        source, metadata = events([raw(START-9900, 100), raw(first["confirm"], 200), raw(first["confirm"], 200, 60050)])
        refs, _ = R.build(source, [first, second], SESSION, metadata, config())
        self.assertEqual(refs[15]["配信VWAP"], 60000)
        self.assertEqual(refs[16]["配信VWAP"], 60050)

    def test_native参照も固定許容の内外を区別する(self) -> None:
        """17と同じ0.00010001pt境界を18の現在参照でも維持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(15, confirm_line=2)
        tolerance = .0001+.00000001
        inside = math.nextafter(60000+tolerance, 60000)
        outside = math.nextafter(60000+tolerance, math.inf)
        for value, valid in ((inside, True), (outside, False)):
            with self.subTest(配信値=value):
                refs, _ = build([current], [raw(START-9900, 100), raw(current["confirm"], 200, value, TradingValue=12000000000)])
                self.assertEqual(refs[15]["native有効"], valid)

    def test_数量と配信値の正値や当場数量時計を必須とする(self) -> None:
        """古い正常値があってもゼロ/負/非有限/場外量時計へfallbackしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        current = frame(15, confirm_line=3)
        for change in ({"TradingVolume": 0}, {"TradingVolume": -1}, {"VWAP": 0}, {"VWAP": math.inf},
                       {"TradingValue": -1}, {"TradingVolumeTime": stamp(START-1)},
                       {"OpeningPriceTime": stamp(current["confirm"]+1)}):
            with self.subTest(不正=change):
                refs, _ = build([current], [raw(START-9900, 100), raw(current["confirm"], 200), raw(current["confirm"], 300, **change)])
                self.assertFalse(refs[15]["native有効"])
                self.assertFalse(refs[15]["差分有効"])


# ----------------------------------------
# 線の起算/基準と手法の四点履歴を独立に扱う。

class 四点と区間検証(unittest.TestCase):
    """共通助走・epoch・同基準・欠測復帰を検査する。"""

    def test_三点では不可四点で初成立(self) -> None:
        """現在と直前3点を両対照へ共通要求し三足前値を保存する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, rows = history(4)
        refs, _ = build(frames, rows)
        self.assertEqual([refs[f["index"]]["N共通準備"] for f in frames], [False, False, False, True])
        self.assertEqual([refs[f["index"]]["D共通準備"] for f in frames], [False, False, False, True])
        self.assertEqual(refs[18]["配信3足前VWAP"], 60000)
        self.assertEqual(refs[18]["配信VWAP"], 60030)

    def test_接頭がなければNだけをオンラインで準備する(self) -> None:
        """Day一覧の将来フラグでDを許可せず、既知基準不明は保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, rows = history(5, prefix=False)
        refs, _ = build(frames, rows, 将来差分可能場=True)
        other, _ = build(frames, rows, 将来差分可能場=False)
        self.assertEqual(refs, other)
        self.assertTrue(refs[19]["N共通準備"])
        self.assertFalse(refs[19]["D共通準備"])
        self.assertIsNone(refs[19]["当場差分VWAP"])

    def test_identity一時未確認は基準を保持して四点は再助走(self) -> None:
        """欠測復帰時に古い基準は保持しても三点の傾きを橋渡ししない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, rows = history(8)
        rows[4]["OpeningPriceTime"] = None
        refs, _ = build(frames, rows)
        self.assertEqual(refs[17]["補助epoch"], refs[22]["補助epoch"])
        self.assertFalse(refs[18]["native有効"])
        self.assertEqual(refs[18]["補助参照"]["基準"]["line"], 1)
        self.assertFalse(refs[21]["N共通準備"])
        self.assertTrue(refs[22]["N共通準備"])
        self.assertTrue(refs[22]["D共通準備"])

    def test_累積resetはepochを変えD基準を永久破棄(self) -> None:
        """同identityの量減少でも前区間の傾きや基準へ戻らない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, rows = history(8)
        rows[5] = raw(frames[4]["confirm"], 10, 60040)
        refs, _ = build(frames, rows)
        self.assertNotEqual(refs[18]["補助epoch"], refs[19]["補助epoch"])
        self.assertFalse(refs[19]["N共通準備"])
        self.assertTrue(refs[22]["N共通準備"])
        self.assertTrue(all(not refs[f["index"]]["D共通準備"] for f in frames[4:]))

    def test_既知identity不一致はepochと助走を変更(self) -> None:
        """始値/限月/市場の既知変更ごとに四点をやり直す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"OpeningPrice": 59800}, {"OpeningPriceTime": "2026-11-04T09:00:00+09:00"}, {"Symbol": "合成限月B"}, {"Exchange": 3}):
            with self.subTest(変更=change):
                frames, rows = history(8)
                for row in rows[5:]:
                    row.update(change)
                refs, _ = build(frames, rows)
                self.assertNotEqual(refs[18]["補助epoch"], refs[19]["補助epoch"])
                self.assertFalse(refs[19]["N共通準備"])
                self.assertTrue(refs[22]["N共通準備"])
                self.assertFalse(refs[22]["D共通準備"])

    def test_native不正や数量時計先行の後は新しい四点を待つ(self) -> None:
        """基準候補を保持しても参照不可行の前後を傾きへ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"VWAP": None}, {"VWAP": 61000}, {"CurrentPrice": 0}, {"TradingVolumeTime": stamp(frame(18)["end"]+1)}):
            with self.subTest(不正=change):
                frames, rows = history(8)
                rows[4].update(change)
                refs, _ = build(frames, rows)
                self.assertFalse(refs[18]["N共通準備"])
                self.assertFalse(refs[21]["N共通準備"])
                self.assertTrue(refs[22]["N共通準備"])

    def test_確認遅延30は可31は履歴を切る(self) -> None:
        """共通上限の等号を含め、超過後は四点を取り直す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for delay, ready in ((30, True), (31, False)):
            with self.subTest(秒=delay):
                frames, rows = history(8)
                frames[3]["confirm"] += delay
                refs, _ = build(frames, rows)
                self.assertEqual(refs[18]["N共通準備"], ready)
                if delay == 31:
                    self.assertFalse(refs[21]["N共通準備"])
                    self.assertTrue(refs[22]["N共通準備"])

    def test_欠枠と飛越と非公開で履歴を切る(self) -> None:
        """連続性の破れを最新値が正しくても共通助走で除外する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, rows = history(8)
        frames[3]["missing"] = 1
        refs, _ = build(frames, rows)
        self.assertFalse(refs[18]["N共通準備"])
        self.assertTrue(refs[21]["N共通準備"])
        frames, rows = history(8)
        frames[3]["publish"] = False
        refs, _ = build(frames, rows)
        self.assertFalse(refs[21]["N共通準備"])
        self.assertTrue(refs[22]["N共通準備"])
        frames, rows = history(8)
        del frames[3]
        refs, _ = build(frames, rows)
        self.assertFalse(refs[19]["N共通準備"])
        self.assertTrue(refs[22]["N共通準備"])

    def test_同epochでも差分基準が違えばDを許可しない(self) -> None:
        """Nの四点成立だけでDを許可せず基準原行も揃える。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, rows = history(4)
        original = R.Online.snapshot
        def changed(state: object, key: tuple) -> dict:
            """人工的に四点の基準原行だけを変えてD条件を独立に検査する。

            引数: state (Online) は状態、key (tuple) は判断キー。
            返り値: dict は同epochだが異なる基準の人工snapshot。
            """
            row = deepcopy(original(state, key))
            if key == (frames[-1]["confirm"], frames[-1]["confirm_line"]):
                row["補助参照"]["基準"]["line"] = 99
            return row
        with patch.object(R.Online, "snapshot", changed):
            refs, _ = build(frames, rows)
        self.assertTrue(refs[18]["N共通準備"])
        self.assertFalse(refs[18]["D共通準備"])

    def test_別呼出しへ四点を持ち越さない(self) -> None:
        """場の状態や価格指標履歴とVWAP助走を混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, rows = history(4)
        refs, _ = build(frames, rows)
        self.assertTrue(refs[18]["N共通準備"])
        other, _ = build([frames[-1]], rows)
        self.assertFalse(other[18]["N共通準備"])

    def test_将来行追加で過去参照を改訂しない(self) -> None:
        """判断後の大量増減やidentity変更を過去へ遡及させない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, rows = history(4)
        before, _ = build(frames, rows)
        after, _ = build(frames, rows+[raw(frames[-1]["confirm"]+60, 1, 30000, Symbol="別限月")])
        self.assertEqual(before, after)


# ----------------------------------------
# 18Onlineへ複製した起算規則を17の合格で代用せず直接検査する。

class 基準正本同値検証(unittest.TestCase):
    """閉場窓・内部整合・直接零・欠測時の累積更新を確認する。"""

    def test_閉場前や古い数量時計のprefixを基準にしない(self) -> None:
        """Day06時/Night15時45分の両時計下限を18でも維持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for session, floor in ((SESSION, START-9900), ("2026-11-04_Night", START+25200)):
            for now, volume_time in ((floor-1, floor-1), (floor, floor-1)):
                with self.subTest(場=session, 価格時計=now, 数量時計=volume_time):
                    source, metadata = events([raw(now, 100, TradingVolumeTime=stamp(volume_time))])
                    online = R.Online(session, metadata)
                    online.apply(source[0])
                    self.assertIsNone(online.base)

    def test_不整合prefixを更新に使わず旧整合基準は保持(self) -> None:
        """nativeだけの不整合で旧基準を差し替えず、全不整合なら不明とする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for prior_good, expected_base in ((False, None), (True, 1)):
            with self.subTest(先行整合=prior_good):
                rows = [raw(START-9900, 100)] if prior_good else []
                rows += [raw(START-9840, 100, 61000, TradingValue=6000000000), raw(frame(15)["confirm"], 200)]
                source, metadata = events(rows)
                online = R.Online(SESSION, metadata)
                for event in source:
                    online.apply(event)
                result = online.snapshot((source[-1].now, source[-1].line))
                self.assertTrue(result["native有効"])
                self.assertEqual(result["差分有効"], prior_good)
                self.assertEqual(online.base.line if online.base else None, expected_base)

    def test_量代金ともゼロの開始直接基準だけを許可(self) -> None:
        """Night開始後の途中ゼロを全セッションの起点へ補わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        night_start = START+29700
        for zero_time, allowed in ((night_start, True), (night_start+1, False)):
            with self.subTest(ゼロ時計=zero_time):
                rows = [raw(zero_time, 0, 0, OpeningPriceTime=stamp(night_start)),
                        raw(night_start+60, 200, OpeningPriceTime=stamp(night_start))]
                source, metadata = events(rows)
                online = R.Online("2026-11-04_Night", metadata)
                online.apply(source[0])
                self.assertFalse(online.snapshot((zero_time, 1))["native有効"])
                online.apply(source[1])
                result = online.snapshot((night_start+60, 2))
                self.assertTrue(result["native有効"])
                self.assertEqual(result["差分有効"], allowed)
                if allowed:
                    self.assertEqual(result["当場差分VWAP"], 60000)

    def test_contract欠測でも累積previousを前進させる(self) -> None:
        """欠測行の200から次の150への減少を古い100との増加へ読み替えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        source, metadata = events([raw(START-9900, 100), raw(START, 200, Symbol=None), raw(START+60, 150)])
        online = R.Online(SESSION, metadata)
        online.apply(source[0])
        online.apply(source[1])
        self.assertEqual(online.previous.volume, 200)
        self.assertFalse(online.snapshot((START, 2))["native有効"])
        online.apply(source[2])
        result = online.snapshot((START+60, 3))
        self.assertTrue(result["native有効"])
        self.assertFalse(result["差分有効"])
        self.assertEqual(online.epoch, 1)
        self.assertIsNone(online.base)


# ----------------------------------------
# 同じ価格Pと共通マスクに対して位置・傾きだけを付け外す。

class 入口選別検証(unittest.TestCase):
    """strict境界・役割・六条件の包含を独立した人工価格で確認する。"""

    def test_T1買いはnativeの上で差分の下ならD_Dだけ除く(self) -> None:
        """順行位置を終値−線で判定しD_BとD_Dを区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        passed, _, _ = select()
        self.assertEqual(passed, {"N_A", "N_B", "N_C", "D_A", "D_B"})

    def test_T1売りへ鏡像の位置と傾きを適用する(self) -> None:
        """売り側へ同じstrict条件を反転して適用する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        passed, _, _ = select(side=-1, close=95, reference=ready_reference(配信3足前VWAP=105, 当場差分VWAP=90))
        self.assertEqual(passed, {"N_A", "N_B", "N_C", "D_A", "D_B"})

    def test_R2買いは線へ向かう余地を要求する(self) -> None:
        """反転は順行と逆の線−終値位置でnativeと差分を区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        passed, _, _ = select(family="R2")
        self.assertEqual(passed, {"N_A", "D_A", "D_D"})

    def test_R2売りも余地の鏡像とする(self) -> None:
        """売り反転は下の線への余地を測り、上の線を採用しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        passed, _, _ = select(family="R2", side=-1, close=95, reference=ready_reference(配信3足前VWAP=105, 当場差分VWAP=90))
        self.assertEqual(passed, {"N_A", "D_A", "D_D"})

    def test_終値と線の等号はAだけ残す(self) -> None:
        """位置等号ではB/C/D_Dへ入らず共通対照Aは残す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for family in ("T1", "R2"):
            with self.subTest(役割=family):
                passed, _, _ = select(family=family, close=100, reference=ready_reference(当場差分VWAP=100))
                self.assertEqual(passed, {"N_A", "D_A"})

    def test_三足前と同じ線ならCだけ見送る(self) -> None:
        """位置が成立しても傾き等号はstrict条件を満たさない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        passed, _, _ = select(reference=ready_reference(配信3足前VWAP=100))
        self.assertEqual(passed, {"N_A", "N_B", "D_A", "D_B"})

    def test_R2の傾きも実sideへ向かうことを要求(self) -> None:
        """反転位置の符号を傾きへ重ねて反転しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        up, _, _ = select(family="R2", close=95)
        down, _, _ = select(family="R2", close=95, reference=ready_reference(配信3足前VWAP=105))
        self.assertIn("N_C", up)
        self.assertNotIn("N_C", down)
        self.assertIn("N_B", down)

    def test_NとDは共通助走の中でだけ選別する(self) -> None:
        """三点しかない対照Aを先行発動させず、Nだけ準備ならDを除く。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        none, _, _ = select(reference=ready_reference(N共通準備=False, D共通準備=False))
        native, _, _ = select(reference=ready_reference(D共通準備=False))
        self.assertEqual(none, set())
        self.assertEqual(native, {"N_A", "N_B", "N_C"})

    def test_準備フラグと不正値の矛盾を拒否する(self) -> None:
        """N/D準備trueを理由に欠測や非正線を黙って使わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"配信VWAP": None}, {"配信VWAP": 0}, {"配信3足前VWAP": math.nan},
                       {"当場差分VWAP": 0}, {"差分3足前VWAP": None}, {"N共通準備": False}):
            with self.subTest(矛盾=change):
                with self.assertRaises(ValueError):
                    select(reference=ready_reference(**change))

    def test_価格対照の要求属性と補助参照を保存(self) -> None:
        """VWAPで約定した値へ置き換えず元価格Pと判断キーを保つ。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        _, quality, signals = select()
        self.assertEqual(quality["全価格発動記録"][0]["元価格信号"]["イベントID"], "人工価格P")
        for signal in signals:
            self.assertEqual(signal["価格イベントID"], "人工価格P")
            self.assertEqual(signal["close"], 105)
            self.assertEqual(signal["要求時計秒"], frame(21)["confirm"])
            self.assertEqual(signal["要求原板行"], frame(21)["confirm_line"])


# ----------------------------------------
# 固定旧Pとdriverの定義を数値探索なしで確認する。

class 固定依存検証(unittest.TestCase):
    """既存の価格式と固定36案/3分代表/最終期間の非選定を確認する。"""

    def test_旧PのT1とR2を三尺度両方向で保持(self) -> None:
        """追加線条件の前に旧11と全文同じ価格発動を使う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for minutes in (1, 3, 5):
            for family in ("T1", "R2"):
                for side in (1, -1):
                    with self.subTest(分=minutes, 系統=family, side=side):
                        first = 15//minutes
                        frames = [frame(first+i, minutes) for i in range(7)]
                        if family == "T1":
                            prior, current = 60000-10*side, 60000+20*side
                            for row in frames[:-1]:
                                row.update(close=prior, ema20=60000)
                            frames[-1].update(close=current, ema20=60000+10*side)
                        else:
                            prior, current = 60000-300*side, 60000-150*side
                            for row in frames[:-1]:
                                row.update(close=prior, high=prior+20, low=prior-20)
                            frames[-1].update(close=current, high=current+20, low=current-20)
                        upper = [frame(0, 15, close=60000+20*side, ema20=60000, ema20_previous=60000-10*side)]
                        original, _ = I.BASE.generate(frames, upper, SESSION, START+20000, START+24000, deepcopy(I.BASE_CONFIG))
                        source = original[f"{minutes}分_{family}"]
                        self.assertEqual(len(source), 1)
                        references = {row["index"]: ready_reference(配信VWAP=60000, 配信3足前VWAP=60000-side, 当場差分VWAP=60000, 差分3足前VWAP=60000-side) for row in frames}
                        _, quality = I.generate(frames, upper, SESSION, START+20000, START+24000, config(), references)
                        saved = [record["元価格信号"] for record in quality["全価格発動記録"] if record["価格入口ID"] == f"{minutes}分_{family}"]
                        self.assertEqual(saved, source)

    def test_固定36案と3分だけの表示代表(self) -> None:
        """結果に応じずT1/R2×三尺度×六設定を列挙する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        sources = D.sources(config())
        self.assertEqual(len(sources), 36)
        self.assertEqual(len({s["入口ID"] for s in sources}), 36)
        self.assertEqual(len([s for s in sources if s["時間足分"] == 3]), 12)
        self.assertEqual(config()["出口"], [{"出口ID": "X0"}])

    def test_空足でも六設定から12ゼロ入口を返す(self) -> None:
        """I.EXTRASなど旧実装名へ依存せず固定六設定を列挙する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for size in (1, 3, 5):
            with self.subTest(分=size):
                groups, quality = D.generate_or_empty([], [], SESSION, size, START+20000, START+24000, config(), {})
                expected = {f"{size}分_{family}_{setting}" for family in ("T1", "R2") for setting in I.SETTINGS}
                self.assertEqual(set(groups), expected)
                self.assertTrue(all(rows == [] for rows in groups.values()))
                self.assertEqual(quality["全価格発動記録"], [])
                self.assertEqual(quality["系統別発動数"], {key: 0 for key in expected})

    def test_旧Pの下位準備を削らずRSIの新gateも加えない(self) -> None:
        """EMA/ATR/ADX/BBの旧共通準備だけを保ち新RSI閾値を加えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for field in ("ema20", "atr", "adx", "bb_mean", "bb_sd", "rsi"):
            with self.subTest(欠測=field):
                frames = [frame(15+i, close=59990) for i in range(7)]
                frames[-1].update(close=60020, ema20=60010)
                frames[-1][field] = None
                higher = [frame(0, 15, close=60020)]
                references = {f["index"]: ready_reference(配信VWAP=60000, 配信3足前VWAP=59990, 当場差分VWAP=60000, 差分3足前VWAP=59990) for f in frames}
                _, quality = I.generate(frames, higher, SESSION, START+20000, START+24000, config(), references)
                self.assertEqual(quality.get("価格発動数", 0), 1 if field == "rsi" else 0)

    def test_参照条件を実行時に変更しない(self) -> None:
        """四点/三足前/判断時点だけを使い、別の条件を拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, rows = history(4)
        source, metadata = events(rows)
        for key, value in (("連続点数", 3), ("傾き差本数", 2), ("判断時点", False)):
            with self.subTest(設定=key):
                altered = config()
                altered["参照条件"][key] = value
                with self.assertRaises(ValueError):
                    R.build(source, frames, SESSION, metadata, altered)
                with self.assertRaises(ValueError):
                    I.validate_config(altered)


def main() -> None:
    """人工合成を実行し途中proofと最終固定用proofを区別する。

    引数: なし。--finalの最終実行だけ編集終了を記録する。
    返り値: None。失敗時は終了コード1、共有原板や市場結果を読まない。
    """
    parser = argparse.ArgumentParser(description="VWAP入口の人工合成。最終通知前は途中記録だけを保存")
    parser.add_argument("--final", action="store_true", help="全編集終了時だけ固定用proofを保存")
    args = parser.parse_args()
    paths = [Path(__file__), HERE/"参照.py", HERE/"入口.py", HERE/"検証.py", STUDY/"条件.json"]
    pins = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if args.final and (STUDY/"固定.json").exists():
        locked = json.loads((STUDY/"固定.json").read_text(encoding="utf-8"))["ファイルSHA256"]
        if any(locked.get(name) != digest for name, digest in pins.items()):
            raise ValueError("固定後の合成変更は別ファイルへ分離する")
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "合成編集終了": bool(args.final and result.wasSuccessful()), "ファイルSHA256": pins,
              "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
              "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors],
              "範囲": "人工原板だけの原順join/同時計/repeat/最新不正/epochと基準/四点助走/strict位置と傾き/役割/旧P同値/36案。共有原板・PnLは再計算しない。",
              "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    target = WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k: report[k] for k in ("全件成功", "検証件数", "合成編集終了")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
