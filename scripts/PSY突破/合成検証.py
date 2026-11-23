"""30の価格突破・BB絶対幅・現前PSYを人工入力で検査する。"""

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
STUDY = ROOT / "study/00030_価格突破とBB幅と方向頻度"
WORK = ROOT / "work/PSY突破"
SESSION = "人工PSY場"
CONTRACT = ("人工限月",)


def normalized(path: object) -> str:
    """ファイルへ触れず、内容読取禁止先との比較表記を作る。

    引数: path(object)はパス又はファイル記述子。
    返り値: strは絶対表記。パスでなければ空文字。
    """
    try:
        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError):
        return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """人工合成から共有原板とwork内npzへstat/openさせない。

    引数: なし。
    返り値: Iterator[None]は読取禁止範囲。条件/既知コード/人工値だけ使う。
    """
    raw, work = normalized(ROOT.parent / "JP_OSE_Data"), normalized(ROOT / "work")
    original_open, original_path_open, original_stat = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """共有市場資料を開く前に合成を失敗させる。

        引数: path(object)は対象。
        返り値: None。原板又はnpzはAssertionError。
        """
        name = normalized(path)
        if name == raw or name.startswith(raw + os.sep) or name.startswith(work + os.sep) and name.endswith(".npz"):
            raise AssertionError("人工合成から実原板/cacheへ触れない:" + str(path))

    def guarded_open(path: object, *args: object, **kwargs: object) -> Any:
        """openで市場内容へ到達させない。

        引数: path(object)は対象、args/kwargs(object)はopen引数。
        返り値: Anyは許された人工/コードファイル。
        """
        check(path)
        return original_open(path, *args, **kwargs)

    def guarded_path_open(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.openでも市場内容へ到達させない。

        引数: path(Path)は対象、args/kwargs(object)はopen引数。
        返り値: Anyは許された人工/コードファイル。
        """
        check(path)
        return original_path_open(path, *args, **kwargs)

    def guarded_stat(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.statでも実原板/cacheへ接近しない。

        引数: path(Path)は対象、args/kwargs(object)はstat引数。
        返り値: Anyは許されたstat。
        """
        check(path)
        return original_stat(path, *args, **kwargs)

    with patch.object(builtins, "open", guarded_open), patch.object(Path, "open", guarded_path_open), patch.object(Path, "stat", guarded_stat):
        yield


def load(path: Path, name: str) -> Any:
    """市場読取禁止のままPythonのAPI定義だけを読み込む。

    引数: path(Path)はコード、name(str)は登録名。
    返り値: Anyは読込モジュール。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
        return value


def frame(index: int, high: float = 105., low: float = 95., close: float = 100., **updates: object) -> dict:
    """手計算できる人工の完全幅3分OHLCを返す。

    引数: index(int)は番号、high/low/close(float)は価格、updates(object)は上書き。
    返り値: dictは人工足。原板を参照しない。
    """
    start = index * 180.
    return {"index": index, "minutes": 3, "start": start, "end": start+180., "confirm": start+180.,
            "confirm_line": index+10, "publish": True, "missing": 0,
            "open": min(high, max(low, close)), "high": high, "low": low, "close": close, **updates}


def reflect(frames: list[dict], center: float = 2000.) -> list[dict]:
    """高安を交換し、正価格の範囲で人工系列を上下反射する。

    引数: frames(list[dict])は人工足、center(float)は価格の和。
    返り値: list[dict]は独立した鏡像で、量/時計/keyは変更しない。
    """
    result = deepcopy(frames)
    for row in result:
        high, low = row["high"], row["low"]
        row.update(open=center-row["open"], high=center-low, low=center-high, close=center-row["close"])
    return result


def sha(path: Path) -> str:
    """コードと条件の内容指紋を取得する。

    引数: path(Path)はコード又はJSON正本。
    返り値: strはSHA256。実市場資料を対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


J = load(HERE / "指標.py", "PSY合成の数値銀行")
I = load(HERE / "入口.py", "PSY合成の同時点入口")


def from_closes(values: list[float]) -> list[dict]:
    """終値を包含する人工OHLCを順番に作る。

    引数: values(list[float])は終値。
    返り値: list[dict]はH=C+1/L=C−1の完全公開足。
    """
    return [frame(i, high=c+1., low=c-1., close=c) for i, c in enumerate(values)]


def golden() -> list[dict]:
    """旧BBσ5から現幅√451へ拡大する人工買突破を作る。

    引数: なし。
    返り値: list[dict]は95×10/105×10と現在110の21本。
    """
    return from_closes([95.]*10+[105.]*10+[110.])


def rows_of(frames: list[dict]) -> list[dict]:
    """人工OHLCのATRと局所PSYだけを計算する。

    引数: frames(list[dict])は人工足。
    返り値: list[dict]は人工数値足。量/外部系列は読まない。
    """
    return J.NumericBank().build(frames, SESSION, CONTRACT)[0]


def generate(rows: list[dict], cutoff: float = 10000., deadline: float = 20000.) -> tuple[dict, dict]:
    """原価格突破と二案採否だけを人工時点で生成する。

    引数: rows(list[dict])は人工数値足、cutoff/deadline(float)は期限。
    返り値: tuple[dict,dict]は二純入口/全contextとraw。先着/PnLなし。
    """
    return I.generate(rows, SESSION, cutoff, deadline, I.expected_config())


class PSY数値と公開窓検証(unittest.TestCase):
    """整数U/D/Fと数値carry/局所公開窓を検査する。"""

    def test_13closeで現12変化ができ14closeで現前が初めて揃う(self) -> None:
        """同値12個はup/downとも0で、100−upへ反射しない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。足番号13個を保存した最速境界へ照合。
        """
        rows = rows_of(from_closes([100.]*14))
        self.assertTrue(all(r["PSY現"] is None for r in rows[:12]))
        self.assertIsNotNone(rows[12]["PSY現"])
        self.assertIsNone(rows[12]["PSY前"])
        self.assertFalse(rows[12]["PSY準備済"])
        self.assertTrue(rows[13]["PSY準備済"])
        for key in ("PSY現", "PSY前"):
            item = rows[13][key]
            self.assertEqual((item["上昇数"], item["下落数"], item["同値数"], item["方向差整数"]), (0, 0, 12, 0))
            self.assertEqual((item["上昇率"], item["下落率"]), (0., 0.))
        self.assertEqual(rows[13]["PSY現"]["足番号"], list(range(1, 14)))
        self.assertEqual(rows[13]["PSY前"]["足番号"], list(range(13)))

    def test_同値を含むPSYはUとDが交換されFと母数12が保たれる(self) -> None:
        """U6/D3/F3と鏡像U3/D6/F3を明示計数へ照合する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。上昇率と下落率の和を常に100としない。
        """
        frames = from_closes([100.,105.,110.,110.,105.,110.,110.,105.,110.,115.,115.,110.,115.])
        a, b = rows_of(frames)[-1]["PSY現"], rows_of(reflect(frames))[-1]["PSY現"]
        self.assertEqual((a["上昇数"], a["下落数"], a["同値数"], a["方向差整数"]), (6, 3, 3, 3))
        self.assertEqual((b["上昇数"], b["下落数"], b["同値数"], b["方向差整数"]), (3, 6, 3, -3))
        self.assertEqual((a["上昇率"], a["下落率"]), (50., 25.))
        self.assertEqual((b["上昇率"], b["下落率"]), (25., 50.))
        self.assertNotEqual(b["上昇率"], 100-a["上昇率"])

    def test_ATRだけ同限月carryしPSYは毎場初期化して限月尾部で数値も解除する(self) -> None:
        """場間のATR銀行と局所14closeを別状態として検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。前場PSYを当場の公開現前値へ代用しない。
        """
        bank = J.NumericBank()
        bank.build(from_closes([100.]*20), SESSION, CONTRACT)
        first, _ = bank.build([frame(0)], "人工次場", CONTRACT)
        self.assertIsNotNone(first[0]["atr"])
        self.assertIsNone(first[0]["PSY現"])
        self.assertIsNone(first[0]["PSY前"])
        changed, _ = bank.build([frame(0)], "人工別限月", ("別限月",))
        self.assertIsNone(changed[0]["atr"])
        bank.build(from_closes([100.]*20), SESSION, CONTRACT, tail_missing=1)
        final, _ = bank.build([frame(0)], "人工尾部後", CONTRACT)
        self.assertIsNone(final[0]["atr"])

    def test_missing当足不投入と番号飛越後missing0当足新種の差を守る(self) -> None:
        """missing足はATRだけ更新し、PSY/価格窓へ入れない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。13closeの再準備が一足違うことを検査。
        """
        prefix = [frame(i) for i in range(13)]
        missing = [*prefix, frame(13, missing=1), *[frame(i) for i in range(14, 26)]]
        gap = [*prefix, *[frame(i) for i in range(14, 27)]]
        a, b = rows_of(missing), rows_of(gap)
        self.assertIsNone(a[13]["PSY現"])
        self.assertIsNone(a[-1]["PSY現"])
        self.assertIsNotNone(b[-1]["PSY現"])
        self.assertEqual(b[-1]["PSY現"]["足番号"], list(range(14, 27)))
        _, qa = generate(a)
        self.assertEqual(qa["複合context記録"][14]["前20足番号"], [])

    def test_NPと不正で局所PSYを切りNPはATR数値だけ更新する(self) -> None:
        """未公開と不正OHLCの投入/保存を区別する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。非有限OHLCを価格へ補完しない。
        """
        for mode in ("NP", "不正"):
            frames = [frame(i) for i in range(20)]
            if mode == "NP":
                frames[-1].update(publish=False, confirm=None, confirm_line=None)
            else:
                frames[-1]["high"] = float("nan")
            rows = rows_of(frames)
            self.assertIsNone(rows[-1]["PSY現"])
            self.assertIsNone(rows[-1]["PSY前"])
            self.assertEqual(rows[-1]["atr"] is not None, mode == "NP")
            json.dumps(rows, ensure_ascii=False, allow_nan=False)

    def test_局所PSYと精密分散差を独立の直接計数と偏差二乗和へ照合する(self) -> None:
        """独立PSY/ATRと別式のFraction分散を比較する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。ATRだけabs1e−10、整数/率/精密比較と採否は厳密。
        """
        independent = load(HERE / "状態独立確認.py", "PSY合成の独立数値窓")
        frames = from_closes([100.+5*(i%7-3) for i in range(80)])
        frames[40]["missing"] = 1
        frames[-1].update(publish=False, confirm=None, confirm_line=None)
        for source in (frames, reflect(frames)):
            actual = rows_of(source)
            expected, _ = independent.NumericHistory().build(source, SESSION, CONTRACT)
            for left, right in zip(actual, expected):
                for key in ("PSY現", "PSY前", "PSY準備済", "価格数値入力可", "PSY解除理由", "銀行解除理由"):
                    self.assertEqual(left[key], right[key], key)
                if left["atr"] is None:
                    self.assertIsNone(right["atr"])
                else:
                    self.assertAlmostEqual(left["atr"], right["atr"], delta=1e-10)
                    self.assertEqual(max(5, math.ceil(left["atr"]/5)*5), max(5, math.ceil(right["atr"]/5)*5))
        for source in (golden(), reflect(golden()), from_closes([94.]+[100.]*19+[106.])):
            wanted = independent.exact_width_change(source[:20], source[1:])
            actual = I.variance_difference([r["close"] for r in source[:20]], [r["close"] for r in source[1:]])
            self.assertEqual(tuple(actual[k] for k in I.EXACT_FIELDS), wanted)
        source = golden()
        actual, qa = generate(rows_of(source))
        expected_rows, _ = independent.NumericHistory().build(source, SESSION, CONTRACT)
        expected, qe = independent.generate(expected_rows, SESSION, 10000., 20000., I.expected_config())
        self.assertEqual(actual, expected)
        self.assertEqual(qa["全Q発動記録"], qe["全Q発動記録"])


class 価格突破と精密幅検証(unittest.TestCase):
    """原P・共通M・幅・PSY値追加を別に人工検査する。"""

    def test_前20高安current除外と旧現BB20の分散差を明示値へ照合する(self) -> None:
        """95/105旧窓へ110を入れた母σと絶対幅を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。分子51/分母16は分散差で幅差ではない。
        """
        rows = rows_of(golden())
        grouped, quality = generate(rows)
        self.assertEqual(tuple(len(v) for v in grouped.values()), (1, 1))
        self.assertEqual(quality["原価格発動数"], 1)
        raw = quality["全Q発動記録"][0]
        self.assertEqual(raw["前20足番号"], list(range(20)))
        self.assertEqual(raw["現BB足番号"], list(range(1, 21)))
        self.assertEqual(raw["直前最高H"], 106.)
        self.assertEqual((raw["旧BB平均"], raw["旧BB標準偏差"], raw["旧BB幅"]), (100., 5., 20.))
        self.assertAlmostEqual(raw["現BB幅"], math.sqrt(451), delta=1e-12)
        self.assertEqual(tuple(raw[k] for k in I.EXACT_FIELDS), (1, 51, 16))
        self.assertEqual(raw["役割"], "順行")

    def test_数学等幅のbreakoutは浮動表示差にかかわらず両案不採用(self) -> None:
        """旧94/100×19から106へ置換する厳密等号と鏡像を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。分散差0はM準備可だが値条件不成立。
        """
        frames = from_closes([94.]+[100.]*19+[106.])
        for source in (frames, reflect(frames)):
            grouped, quality = generate(rows_of(source))
            self.assertEqual(quality["原価格発動数"], 1)
            self.assertEqual(tuple(len(v) for v in grouped.values()), (0, 0))
            raw = quality["全Q発動記録"][0]
            self.assertTrue(raw["共通M準備"])
            self.assertEqual(tuple(raw[k] for k in I.EXACT_FIELDS), (0, 0, 1))

    def test_価格突破でも幅収縮ならrawだけを残し上下反射で同じ採否になる(self) -> None:
        """最古の外れ値を落とした分散減少を新高値突破と区別する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。20窓の全符号を同じにし売だけ閾値を変えない。
        """
        frames = from_closes([80.]+[100.]*19+[106.])
        a, b = generate(rows_of(frames)), generate(rows_of(reflect(frames)))
        for grouped, quality in (a, b):
            self.assertEqual(quality["原価格発動数"], 1)
            self.assertEqual(tuple(len(v) for v in grouped.values()), (0, 0))
            self.assertEqual(quality["全Q発動記録"][0]["BB幅比較厳密符号"], -1)
        self.assertEqual(a[1]["全Q発動記録"][0]["戦略判定"], b[1]["全Q発動記録"][0]["戦略判定"])

    def test_現終値等号とヒゲだけの突破は原Pにしない(self) -> None:
        """高安の新極値だけでなくCのstrict突破を要求する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。前20HH/LLを現在足の高安へ置換しない。
        """
        for close in (106., 105.):
            frames = golden()
            frames[-1].update(close=close, high=111., low=104., open=close)
            _, quality = generate(rows_of(frames))
            self.assertEqual(quality["原価格発動数"], 0)

    def test_PSYの低い上昇率でもU優位なら可で前state中立はP1だけ見送る(self) -> None:
        """U>Dと上昇率50超/連勝の条件を混同しない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。P0にも同じPSY準備を課すが値は使わない。
        """
        rows = rows_of(golden())
        grouped, quality = generate(rows)
        raw = quality["全Q発動記録"][0]
        self.assertEqual(raw["PSY前"]["方向差整数"], 1)
        self.assertEqual(raw["PSY現"]["方向差整数"], 2)
        self.assertLess(raw["PSY前"]["上昇率"], 50.)
        self.assertEqual(tuple(len(v) for v in grouped.values()), (1, 1))
        flat = from_closes([100.]*20+[110.])
        grouped, quality = generate(rows_of(flat))
        self.assertTrue(quality["全Q発動記録"][0]["共通M準備"])
        self.assertEqual(tuple(len(v) for v in grouped.values()), (1, 0))

    def test_strict突破ではPSY前実方向正なら現在も自動で正になる(self) -> None:
        """現差=前差+1−古Δ符号の恒等式と二gateの冗長性を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。PSY二状態を独立した二票/後続確認としない。
        """
        for frames in (golden(), from_closes([100.]*20+[110.]), from_closes([94.]+[100.]*19+[106.])):
            for source in (frames, reflect(frames)):
                rows = rows_of(source)
                _, quality = generate(rows)
                raw = quality["全Q発動記録"][0]
                side = raw["side"]
                dropped = rows[-13]["close"]-rows[-14]["close"]
                sign = (dropped > 0)-(dropped < 0)
                previous, current = raw["PSY前"]["方向差整数"]*side, raw["PSY現"]["方向差整数"]*side
                self.assertEqual(current-previous, 1-side*sign)
                self.assertGreaterEqual(current, previous)
                self.assertEqual(previous > 0 and current > 0, previous > 0)

    def test_共通PSY不準備とATR不準備はP0にも課してrawと別に残す(self) -> None:
        """二案の準備集合を同じにしてPSY方向の効果だけ比較する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。未使用の量/MACD等を準備へ追加しない。
        """
        for mode in ("PSY", "ATR"):
            rows = rows_of(golden())
            if mode == "PSY":
                rows[-1].update(PSY準備済=False, PSY前=None)
            else:
                rows[-1]["atr"] = 0.
            grouped, quality = generate(rows)
            self.assertEqual(quality["原価格発動数"], 1)
            self.assertTrue(quality["全Q発動記録"][0]["先着評価対象"])
            self.assertFalse(quality["全Q発動記録"][0]["共通M準備"])
            self.assertEqual(tuple(len(v) for v in grouped.values()), (0, 0))

    def test_価格窓は同場の公開20足だけでNP欠枠をまたがず将来も不変(self) -> None:
        """非公開/missing/番号欠の後の価格窓とprefix不変を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。前場数値carryを公開窓へ代用しない。
        """
        for mode in ("NP", "missing", "番号欠"):
            rows = rows_of(golden())
            if mode == "NP":
                rows[10]["publish"] = False
            elif mode == "missing":
                rows[10]["missing"] = 1
            else:
                for row in rows[10:]:
                    row["index"] += 1
            _, quality = generate(rows)
            self.assertEqual(quality["原価格発動数"], 0)
        rows = rows_of(golden())
        _, before = generate(rows)
        later = deepcopy(rows[-1])
        later.update(index=21, close=1000., high=1001., low=999., end=3960., confirm=3960., confirm_line=99)
        _, after = generate([*rows, later])
        self.assertEqual(before["全Q発動記録"], after["全Q発動記録"][:1])
        self.assertEqual(before["複合context記録"], after["複合context記録"][:21])
        _, only = generate(rows[-1:])
        self.assertEqual(only["原価格発動数"], 0)

    def test_時間遅延不可もrawを消さず二案snapshotを深複写する(self) -> None:
        """時間/遅延境界と全採否の別コピーを人工で検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。未来labelや後変更を元rawへ漏らさない。
        """
        for mode in ("停止等号", "残り不足", "遅延超", "境界可"):
            rows = rows_of(golden())
            now, cutoff, deadline = rows[-1]["confirm"], 10000., 20000.
            if mode == "停止等号":
                cutoff = now
            elif mode == "残り不足":
                deadline = now+3599.
            elif mode == "遅延超":
                rows[-1]["confirm"] += 31.
            else:
                rows[-1]["confirm"] += 30.
                deadline = rows[-1]["confirm"]+3600.
            grouped, quality = generate(rows, cutoff, deadline)
            self.assertEqual(quality["原価格発動数"], 1)
            self.assertEqual(quality["全Q発動記録"][0]["先着評価対象"], mode == "境界可")
            self.assertEqual(tuple(len(v) for v in grouped.values()), (1,1) if mode == "境界可" else (0,0))
        rows = rows_of(golden())
        before = deepcopy(rows)
        grouped, quality = generate(rows)
        raw = quality["全Q発動記録"][0]
        self.assertEqual(grouped["3分_P0"][0]["戦略判定"], raw["戦略判定"])
        grouped["3分_P0"][0]["戦略判定"]["P1"]["理由"].append("人工変更")
        self.assertNotIn("人工変更", raw["戦略判定"]["P1"]["理由"])
        self.assertNotIn("人工変更", grouped["3分_P1"][0]["戦略判定"]["P1"]["理由"])
        self.assertEqual(rows, before)


@contextmanager
def driver_fixture(name: str) -> Iterator[tuple[Any, Path, Path, dict]]:
    """主driverのファイル境界だけを人工保存先へ差し替える。

    引数: name(str)はmodule識別名。
    返り値: Iterator[tuple[Any,Path,Path,dict]]はdriver/人工study/work/66場名台帳。
    """
    driver = load(HERE / "検証.py", name)
    with tempfile.TemporaryDirectory(prefix="PSY主境界合成_", dir=ROOT / "work") as folder:
        study, work = Path(folder) / "study", Path(folder) / "work"
        study.mkdir()
        work.mkdir()
        (study / "条件.json").write_text(json.dumps(I.expected_config(), ensure_ascii=False), encoding="utf-8")
        pointer = {"参照": str(driver.MANIFEST_PATH), "SHA256": sha(driver.MANIFEST_PATH)}
        (study / "入力台帳.json").write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
        (study / "計画.md").write_text("人工固定計画\n", encoding="utf-8")
        sessions = [f"2026-09-{1+i//2:02d}_{'Day' if i%2 == 0 else 'Night'}" for i in range(40)]
        sessions += [f"2026-10-{20+i//2:02d}_{'Day' if i%2 == 0 else 'Night'}" for i in range(24)]
        sessions += ["2026-11-04_Day", "2026-11-04_Night"]
        yield driver, study, work, {"entries": [{"session": name} for name in sessions]}


def driver_block(driver: Any, session: str) -> dict:
    """主driverへ当場の人工価格/PSYだけを渡す。

    引数: driver(Any)は主module、session(str)は場名。
    返り値: dictは先着/量/会計のない人工当場。
    """
    rows = rows_of(golden())
    for row in rows:
        row["場"] = session
    signals, quality = driver.I.generate(rows, session, 10000., 20000., I.expected_config())
    return {"events": [], "frames": {3: rows}, "signals": signals, "quality": quality,
            "numeric_quality": [], "input_quality": {"場": session},
            "cutoff": 10000., "deadline": 20000., "duration": 100.}


class 主準備と固定境界検証(unittest.TestCase):
    """主の入力参照/非損益準備/純signal/固定拒否を人工で確認する。"""

    def test_人工66prepareは旧台帳参照を固定し先着会計運用を呼ばない(self) -> None:
        """入力pointerと全66×2の準備を人工へ差し替え禁止経路を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。実価格/実量cacheを一切開かない。
        """
        with driver_fixture("PSY合成の非損益準備") as (driver, study, work, manifest):
            config = I.expected_config()
            self.assertEqual(len(driver.manifest_for(study, config)["entries"]), 66)
            pointer_path = study / "入力台帳.json"
            original = pointer_path.read_bytes()
            bad = json.loads(original)
            bad["SHA256"] = "0"*64
            pointer_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError):
                driver.manifest_for(study, config)
            pointer_path.write_bytes(original)
            bank_ids = []

            def build(entry: dict, supplied: dict, banks: dict, supplied_config: dict) -> dict:
                """主の市場抽出を人工の当場材料へ差し替える。

                引数: entry/supplied/banks/supplied_config(dict)は主APIの引数。
                返り値: dictは人工当場で、数値銀行識別を検査用に保存する。
                """
                bank_ids.append(id(banks[3]))
                self.assertEqual(set(banks), {3})
                return driver_block(driver, entry["session"])

            forbidden = AssertionError("prepareから先着/損益/固定へ進まない")
            with patch.object(driver, "manifest_for", return_value=manifest), patch.object(driver, "build_session", side_effect=build), \
                    patch.object(driver, "freeze", side_effect=forbidden) as freeze, patch.object(driver, "shadow_label", side_effect=forbidden) as label, \
                    patch.object(driver.W.OLD, "気配経路", side_effect=forbidden) as path, patch.object(driver.ENGINE, "replay", side_effect=forbidden) as replay, \
                    patch.object(driver.E, "entry_metrics", side_effect=forbidden) as metric, patch.object(driver, "compressed", side_effect=forbidden) as compressed, \
                    patch.object(driver.D.Q, "aggregate", side_effect=AssertionError("PSYで量集約を呼ばない")) as quantity, redirect_stdout(io.StringIO()):
                driver.run(study, work, prepare_only=True)
            for guard in (freeze, label, path, replay, metric, compressed, quantity):
                guard.assert_not_called()
            proof = json.loads((work / "準備点検.json").read_text(encoding="utf-8"))
            self.assertEqual(len(proof["準備"]), 66)
            self.assertEqual(len(proof["場別発動"]), 132)
            self.assertEqual(len(proof["期間別発動"]), 6)
            self.assertEqual(len(set(bank_ids)), 1)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertEqual(proof["参照台帳SHA256"], sha(driver.MANIFEST_PATH))
            self.assertFalse((study / "結果.json").exists())
            self.assertTrue(all(not (work / name).exists() for name in driver.FILES))

    def test_未来labelは二案保存caseだけへ付け運用signalへ漏らさない(self) -> None:
        """主driverの二案受渡しを人工labelと空運用で検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。二案目の受渡しで止め、実先着/損益を呼ばない。
        """
        with driver_fixture("PSY合成の純signal受渡し") as (driver, study, work, manifest):
            entry = manifest["entries"][0]
            manifest["entries"] = [entry]
            block = driver_block(driver, entry["session"])
            before = deepcopy(block["signals"])
            received = []

            def replay(events: list, signals: list, rows: list, session: str, cid: str, *args: object) -> tuple:
                """二案の純signalを受け取り最後で停止する。

                引数: events/signals/rows(list)は人工列、session/cid(str)は場/案、args(object)は運用設定。
                返り値: tupleは空運用。二案目では停止用RuntimeError。
                """
                self.assertEqual(args[-1], "順行")
                received.append((cid, deepcopy(signals)))
                if len(received) == 2:
                    raise RuntimeError("人工二案受渡し完了")
                return SimpleNamespace(trades=[], normal_log=[], fills=[], orders=[], signals=[]), {}

            future = {"ラベル": "人工未来", "最大順行pt": 999., "人工未来値": 12345}
            with patch.object(driver, "manifest_for", return_value=manifest), patch.object(driver, "build_session", return_value=block), \
                    patch.object(driver, "freeze", return_value={}), patch.object(driver.W.OLD, "気配経路", return_value=object()), \
                    patch.object(driver, "shadow_label", return_value=future), patch.object(driver.ENGINE, "replay", side_effect=replay), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "人工二案受渡し完了"):
                    driver.run(study, work, prepare_only=False)
            self.assertEqual([cid for cid, _ in received], ["3分_P0_X0", "3分_P1_X0"])
            for cid, signals in received:
                self.assertEqual(len(signals), 1)
                self.assertTrue(all(key not in signals[0] for key in future))
                self.assertEqual(signals[0]["期間"], "学習")
                self.assertIn("要求時計JST", signals[0])
                self.assertEqual({k: v for k, v in signals[0].items() if k not in ("期間", "要求時計JST")}, before[cid.removesuffix("_X0")][0])
            with gzip.open(work / "入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
                cases = [json.loads(line) for line in stream]
            self.assertEqual(len(cases), 2)
            self.assertTrue(all(c["人工未来値"] == 12345 for c in cases))
            self.assertFalse((study / "結果.json").exists())

    def test_条件driftと最終未完を拒否し固定後計画差と既存結果も上書きしない(self) -> None:
        """数値/文字列と固定/再実行の境界を人工保存先だけで検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。実固定/旧資産を編集しない。
        """
        config = I.expected_config()
        for section, key in ((None, "逆行pt"), (None, "順行pt"), ("運用", "片道手数料円"), ("必須追尾", "起動幅pt"), *[("PSY突破", key) for key in config["PSY突破"]]):
            changed = deepcopy(config)
            target = changed if section is None else changed[section]
            value = target[key]
            target[key] = value + "人工差" if isinstance(value, str) else value+1 if isinstance(value, (int, float)) else []
            with self.assertRaises(ValueError):
                I.validate_config(changed)
        with driver_fixture("PSY合成の固定ガード") as (driver, study, work, manifest):
            prepare = {"コードSHA256": driver.code_pins(), "条件SHA256": sha(study / "条件.json"),
                       "入力台帳SHA256": sha(study / "入力台帳.json"), "参照台帳SHA256": sha(driver.MANIFEST_PATH)}
            (work / "準備点検.json").write_text(json.dumps(prepare), encoding="utf-8")
            paths = [HERE / n for n in ("指標.py", "入口.py", "検証.py", "合成検証.py")] + [study / "条件.json"]
            proof = {"全件成功": True, "合成編集終了": False, "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}}
            original = driver.W.read_json

            def read(path: Path) -> dict:
                """最終合成だけ人工proofへ差し替える。

                引数: path(Path)は読込先。
                返り値: dictは人工proof又は変更しない既知JSON。
                """
                return deepcopy(proof) if path == WORK / "合成検証.json" else original(path)

            with patch.object(driver.W, "read_json", side_effect=read):
                with self.assertRaises(ValueError):
                    driver.freeze(study, work)
                proof["合成編集終了"] = True
                fixed = driver.freeze(study, work)
                self.assertEqual(driver.freeze(study, work), fixed)
                (study / "計画.md").write_text("人工固定後差\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(study, work)
            result = study / "結果.json"
            result.write_text('{"人工既存結果":true}', encoding="utf-8")
            before = result.read_bytes()
            with patch.object(driver, "manifest_for", return_value=manifest), patch.object(driver, "build_session", side_effect=AssertionError("既存結果後数値禁止")) as build:
                with self.assertRaises(ValueError):
                    driver.run(study, work, prepare_only=False)
            build.assert_not_called()
            self.assertEqual(result.read_bytes(), before)


def main() -> None:
    """API確定後の人工検査だけを実行し固定用の証拠を保存する。

    引数: なし。--finalは全実装/条件/独立補助版のroot確認後だけ指定する。
    返り値: None。実資料の先着/損益を計算しない。
    """
    parser = argparse.ArgumentParser(description="価格突破とBB幅とPSYの人工検査")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    paths = [HERE / n for n in ("指標.py", "入口.py", "検証.py", "合成検証.py")] + [STUDY / "条件.json"]
    if any(not p.is_file() for p in paths):
        raise ValueError("主3コード/合成/条件の確定を待つ")
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    stream = io.StringIO()
    with deny_market():
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    success = result.wasSuccessful() and result.testsRun > 0
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
             "実資料の先着損益計算": False, "ファイルSHA256": pins,
             "独立数値補助SHA256": sha(HERE / "状態独立確認.py"),
             "範囲": "前20HH/LLへの現Cstrict突破とcurrent除外、旧/現20BB母σ・絶対幅4σ、Fraction分散差0/正負と鏡像、PSY12のU/D/F・13/14close最速・同値中立・現前恒等式、ATRcarry/局所欠枠NP/場間reset、rawと共通M/値/time分離・snapshot、独立原窓比較、人工66非label/PnL/非量集約・純signal/固定/pointer/既存結果拒否。ATRのみabs1e−10、他値/精密分散/価格/時点/採否strict。実原板/work内npzはstat/open禁止、実先着/PnL未計算。",
             "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
             "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors], "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / ("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k: proof[k] for k in ("全件成功", "検証件数", "合成編集終了", "実資料の先着損益計算")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
