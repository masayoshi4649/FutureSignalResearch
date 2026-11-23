"""29の前固定BB・MACD・観測OBVを人工入力で検査する。"""

from __future__ import annotations

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import io
import json
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
STUDY = ROOT / "study/00029_BB内復帰とOBV非追随"
WORK = ROOT / "work/OBV反転"
SESSION = "人工OBV場"
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


def golden() -> list[dict]:
    """前20BBが90..110となり、最新安値同値kが19となる人工買復帰を作る。

    引数: なし。
    返り値: list[dict]は前20本の終値105/95交互と現在安値90/終値100の21本。
    """
    return [frame(i, close=105. if i%2 == 0 else 95.) for i in range(20)] + [frame(20, low=90., close=100.)]


def sha(path: Path) -> str:
    """コードと条件の内容指紋を取得する。

    引数: path(Path)はコード又はJSON正本。
    返り値: strはSHA256。実市場資料を対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


J = load(HERE / "指標.py", "OBV合成の数値銀行")
I = load(HERE / "入口.py", "OBV合成の同時点入口")


def quantity_map(frames: list[dict], value: float = 10.) -> dict:
    """RVOL未準備でも完全な数量足を人工で作る。

    引数: frames(list[dict])は人工足、value(float)は観測差分量。
    返り値: dictは番号別数量属性。全約定の観測とは主張しない。
    """
    return {f["index"]: {"観測差分量": value, "数量基準完全": True, "数量準備済": False, "RVOL": None,
             "最終採用数量時計": f["end"]-1, "最終採用価格時計": f["end"]-1,
             "最終採用原行": f["confirm_line"], "数量不完全理由": []} for f in frames}


def entrance_fixture(source: list[dict] | None = None, quantities: dict | None = None) -> list[dict]:
    """価格/数量値選別に必要なMACD差だけを明示した人工足を用意する。

    引数: source(list[dict]|None)は人工足、quantities(dict|None)は人工数量。
    返り値: list[dict]は旧BB90..110とMACD差+1の入口専用fixture。
    """
    frames = source if source is not None else golden()
    quantities = quantities if quantities is not None else quantity_map(frames)
    rows, _ = J.NumericBank().build(frames, SESSION, CONTRACT, quantities=quantities)
    rows[-2]["macd_hist"], rows[-1]["macd_hist"], rows[-1]["atr"] = 0., 1., 20.
    return rows


def generate(rows: list[dict], cutoff: float = 10000., deadline: float = 20000.) -> tuple[dict, dict]:
    """人工の価格発動と二案採否だけを生成する。

    引数: rows(list[dict])は人工数値足、cutoff/deadline(float)は人工期限。
    返り値: tuple[dict,dict]は二純入口と全context/raw。先着/PnLなし。
    """
    return I.generate(rows, SESSION, cutoff, deadline, I.expected_config())


class 数値と数量区間検証(unittest.TestCase):
    """MACD原点と数量OBVの異なる継続/解除条件を検査する。"""

    def test_OBVは0種から当足qの終値符号を足し同値closeと0量は増分0(self) -> None:
        """加算量と終値符号を明示値と鏡像へ照合する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。0量を欠測や正平均gateへ変換しない。
        """
        frames = [frame(i, high=110., low=90., close=c) for i, c in enumerate((100., 102., 102., 99., 101.))]
        quantities = quantity_map(frames)
        for index, q in enumerate((5., 10., 20., 30., 0.)):
            quantities[index]["観測差分量"] = q
        rows, quality = J.NumericBank().build(frames, SESSION, CONTRACT, quantities=quantities)
        other, _ = J.NumericBank().build(reflect(frames), SESSION, CONTRACT, quantities=quantities)
        self.assertEqual([r["OBV"] for r in rows], [0., 10., 10., -20., -20.])
        self.assertEqual([r["OBV増分"] for r in rows], [0., 10., 0., -30., 0.])
        self.assertEqual([r["OBV"] for r in other], [0., -10., -10., 20., 20.])
        self.assertTrue(all(r["数量入力可"] and r["OBV公開可"] for r in rows))
        self.assertEqual(quality["完全0量足数"], 1)
        self.assertEqual([r["OBV種"] for r in rows], [True, False, False, False, False])

    def test_量欠測や不完全でOBVを切り次完全足を0種にしMACD原点は保持する(self) -> None:
        """数量の切断を価格数値銀行へ波及させない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。観測0量は上の別試験で有効とする。
        """
        frames = [frame(i, close=100.+i) for i in range(3)]
        for mode in ("欠測", "負量", "不完全"):
            quantities = quantity_map(frames)
            if mode == "欠測":
                quantities.pop(1)
            elif mode == "負量":
                quantities[1]["観測差分量"] = -1.
            else:
                quantities[1]["数量基準完全"] = False
            rows, _ = J.NumericBank().build(frames, SESSION, CONTRACT, quantities=quantities)
            self.assertIsNone(rows[1]["OBV"])
            self.assertFalse(rows[1]["数量入力可"])
            self.assertEqual(rows[2]["OBV"], 0.)
            self.assertTrue(rows[2]["OBV種"])
            self.assertNotEqual(rows[0]["OBV区間ID"], rows[2]["OBV区間ID"])
            self.assertTrue(all(r["MACD原点"] == 100. for r in rows))

    def test_MACDの算術seedと中心化原点を明示分数と鏡像へ照合する(self) -> None:
        """34定値からの35本目ヒストグラムを224/351へ照合する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。絶対価格EMAの差による鏡像の相殺誤差を避ける。
        """
        frames = [frame(i) for i in range(34)] + [frame(34, high=115., close=110.)]
        quantities = quantity_map(frames)
        rows, _ = J.NumericBank().build(frames, SESSION, CONTRACT, quantities=quantities)
        mirrored, _ = J.NumericBank().build(reflect(frames), SESSION, CONTRACT, quantities=quantities)
        self.assertTrue(all(r["macd_hist"] is None for r in rows[:33]))
        self.assertEqual(rows[33]["macd_hist"], 0.)
        self.assertAlmostEqual(rows[34]["macd_hist"], 224/351, delta=1e-12)
        self.assertEqual(rows[34]["MACD原点"], 100.)
        self.assertEqual(rows[34]["MACD原点出典"]["index"], 0)
        for left, right in zip(rows, mirrored):
            for key in ("macd", "macd_signal", "macd_hist"):
                self.assertEqual(left[key], -right[key] if right[key] is not None else None)
        flat, _ = J.NumericBank().build([frame(i) for i in range(40)], SESSION, CONTRACT, quantities=quantity_map([frame(i) for i in range(40)]))
        self.assertTrue(all(r["macd_hist"] == 0. for r in flat[33:]))

    def test_数値同限月carryとOBV毎場0種を分け限月尾部では数値も解除する(self) -> None:
        """MACD原点のcarryとOBV当場区間を別の状態として検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。古いOBV値/公開量区間を次場へ持ち越さない。
        """
        bank = J.NumericBank()
        frames = [frame(i) for i in range(35)]
        bank.build(frames, SESSION, CONTRACT, quantities=quantity_map(frames))
        second = [frame(0, high=125., close=120.), frame(1, high=130., close=125.)]
        rows, _ = bank.build(second, "人工次場", CONTRACT, quantities=quantity_map(second))
        self.assertEqual(rows[0]["MACD原点"], 100.)
        self.assertIsNotNone(rows[0]["macd_hist"])
        self.assertEqual([r["OBV"] for r in rows], [0., 10.])
        changed, _ = bank.build([frame(0)], "人工別限月", ("別限月",), quantities=quantity_map([frame(0)]))
        self.assertIsNone(changed[0]["macd_hist"])
        bank.build(frames, SESSION, CONTRACT, tail_missing=1, quantities=quantity_map(frames))
        final, _ = bank.build([frame(0, close=103.)], "人工尾部後", CONTRACT, quantities=quantity_map([frame(0)]))
        self.assertEqual(final[0]["MACD原点"], 103.)

    def test_missing足は数値へ投入するが価格窓とOBV種へ入れず番号飛越は種可(self) -> None:
        """missing footprintと番号不連続後の完全当足を区別する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。次missing0公開足から価格窓/量区間を再開する。
        """
        for mode in ("missing", "番号飛越"):
            frames = [frame(0), frame(1 if mode == "missing" else 2, close=101., missing=1 if mode == "missing" else 0), frame(2 if mode == "missing" else 3, close=102.)]
            rows, _ = J.NumericBank().build(frames, SESSION, CONTRACT, quantities=quantity_map(frames))
            self.assertEqual(rows[1]["MACD原点"], 101.)
            self.assertEqual(rows[1]["OBV公開可"], mode == "番号飛越")
            self.assertEqual(rows[1]["OBV種"], mode == "番号飛越")
            self.assertEqual(rows[2]["OBV種"], mode == "missing")
            _, quality = generate(rows)
            self.assertEqual(quality["複合context記録"][-1]["前20足番号"], [] if mode == "missing" else [2])

    def test_NPと不正OHLCでOBV公開を止めNPだけMACD内部更新を続ける(self) -> None:
        """NPの数値更新と局所公開量、OHLC不正の不投入を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。非有限OHLCは保存でNoneとなり価格へ補完しない。
        """
        for mode in ("NP", "不正"):
            frames = [frame(i) for i in range(35)] + [frame(35, high=115., close=110.)]
            if mode == "NP":
                frames[-1].update(publish=False, confirm=None, confirm_line=None)
            else:
                frames[-1]["high"] = float("nan")
            rows, _ = J.NumericBank().build(frames, SESSION, CONTRACT, quantities=quantity_map(frames))
            self.assertFalse(rows[-1]["OBV公開可"])
            self.assertEqual(rows[-1]["価格数値入力可"], mode == "NP")
            self.assertEqual(rows[-1]["macd_hist"] is not None, mode == "NP")
            json.dumps(rows, ensure_ascii=False, allow_nan=False)

    def test_固定数量集約は0差分と累積減少と確認行の次足量を区別する(self) -> None:
        """原順人工数量から、RVOL未準備でも0量有効となることを検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。確認原行の新量を終了した前足へ遡及配置しない。
        """
        aggregate = load(ROOT / "scripts/数量反転/数量.py", "OBV合成の固定数量集約")
        frames = [frame(0, confirm_line=3), frame(1, confirm_line=5)]
        events = [SimpleNamespace(now=now, line=line, last=100., volume=q, volume_time=now)
                  for line, (now, q) in enumerate(((0., 100.), (10., 110.), (180., 110.), (200., 110.), (360., 115.)), 1)]
        quantities, _ = aggregate.aggregate(events, frames, 0., 540., 3)
        self.assertFalse(quantities[0]["数量基準完全"])
        self.assertTrue(quantities[1]["数量基準完全"])
        self.assertEqual(quantities[1]["観測差分量"], 0.)
        self.assertFalse(quantities[1]["数量準備済"])
        rows, _ = J.NumericBank().build(frames, SESSION, CONTRACT, quantities=quantities)
        self.assertTrue(rows[1]["数量入力可"])
        self.assertTrue(rows[1]["OBV種"])
        events[3].volume = 80.
        reset, _ = aggregate.aggregate(events, frames, 0., 540., 3)
        self.assertFalse(reset[1]["数量基準完全"])
        other, _ = J.NumericBank().build(frames, SESSION, CONTRACT, quantities=reset)
        self.assertFalse(other[1]["OBV公開可"])

    def test_中心化MACDとOBVを独立の数値区間再構成へ照合する(self) -> None:
        """独立EMA/区間prefix和へ鏡像も含めて照合する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。ATR/MACDだけabs1e−10、差符号/OBV/出典は厳密。
        """
        independent = load(HERE / "状態独立確認.py", "OBV合成の独立数値区間")
        frames = [frame(i, high=120., low=80., close=100.+5*(i%7-3)) for i in range(80)]
        frames[40]["missing"] = 1
        frames[-1].update(publish=False, confirm=None, confirm_line=None)
        quantities = quantity_map(frames)
        quantities[9]["数量基準完全"] = False
        quantities[35]["観測差分量"] = 0.
        for source in (frames, reflect(frames)):
            actual, _ = J.NumericBank().build(source, SESSION, CONTRACT, quantities=quantities)
            expected, _ = independent.NumericHistory().build(source, SESSION, CONTRACT, quantities=quantities)
            for index, (left, right) in enumerate(zip(actual, expected)):
                for key in ("MACD原点", "MACD原点出典", "価格数値入力可", "数量入力可", "OBV", "OBV増分", "OBV種", "OBV区間ID", "OBV区間足数", "OBV公開可"):
                    self.assertEqual(left[key], right[key], key)
                for key in ("atr", "macd", "macd_signal", "macd_hist"):
                    if left[key] is None:
                        self.assertIsNone(right[key])
                    else:
                        self.assertAlmostEqual(left[key], right[key], delta=1e-10)
                if index and all(r["macd_hist"] is not None for r in (left, right, actual[index-1], expected[index-1])):
                    a, b = left["macd_hist"]-actual[index-1]["macd_hist"], right["macd_hist"]-expected[index-1]["macd_hist"]
                    self.assertEqual((a > 0)-(a < 0), (b > 0)-(b < 0))
        rows = entrance_fixture()
        a, qa = generate(rows)
        b, qb = independent.generate(rows, SESSION, 10000., 20000., I.expected_config())
        self.assertEqual(a, b)
        self.assertEqual(qa["全Q発動記録"], qb["全Q発動記録"])


class 価格と同時点採否検証(unittest.TestCase):
    """前20BBと極値k、MACD/OBVの役割を分けて人工検査する。"""

    def test_旧20BB固定とstrict新安値の帯内復帰で最新同値kを参照する(self) -> None:
        """現在足をBB/極値窓へ先に混ぜず、前C帯外を追加しない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。L=旧BB下端でもstrict新20安値なら発動可。
        """
        rows = entrance_fixture()
        grouped, quality = generate(rows)
        self.assertEqual(quality["原価格発動数"], 1)
        self.assertEqual(tuple(len(v) for v in grouped.values()), (1, 1))
        raw = quality["全Q発動記録"][0]
        self.assertEqual((raw["旧BB平均"], raw["旧BB標準偏差"], raw["旧BB下端"], raw["旧BB上端"]), (100., 5., 90., 110.))
        self.assertEqual(raw["OBV_k参照"]["index"], 19)
        self.assertEqual(raw["前20足番号"], list(range(20)))
        self.assertEqual(raw["要求時計秒"], rows[-1]["confirm"])
        self.assertTrue(raw["共通M準備"])
        self.assertEqual(raw["役割"], "反転")

    def test_買売鏡像でMACD差OBV差と二案採否が対称になる(self) -> None:
        """価格と終値符号付き量を反射し、反転二案を同じ規則で判定する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。売だけ閾値やkの選択規則を変えない。
        """
        a = entrance_fixture()
        b = entrance_fixture(reflect(golden()))
        b[-2]["macd_hist"], b[-1]["macd_hist"] = 0., -1.
        _, left = generate(a)
        _, right = generate(b)
        x, y = left["全Q発動記録"][0], right["全Q発動記録"][0]
        self.assertEqual(x["side"], -y["side"])
        self.assertEqual(x["MACDヒスト変化"], -y["MACDヒスト変化"])
        self.assertEqual(x["OBV比較差"], -y["OBV比較差"])
        self.assertEqual(x["戦略判定"], y["戦略判定"])

    def test_現在終値の帯端等号と新極値同値は価格rawにしない(self) -> None:
        """BBのstrict内と極値のstrict更新を別々に検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。既に帯内なら常にエントリーする条件へ緩めない。
        """
        for mode in ("下帯等号", "上帯等号", "新安値等号"):
            frames = golden()
            if mode == "下帯等号":
                frames[-1].update(close=90., open=90.)
            elif mode == "上帯等号":
                frames[-1].update(close=110., high=110., open=110.)
            else:
                frames[-1]["low"] = 95.
            _, quality = generate(entrance_fixture(frames))
            self.assertEqual(quality["原価格発動数"], 0)

    def test_完全0量は共通Mで有効だがOBV同値なのでR1だけ不採用(self) -> None:
        """0量と量欠測、値条件と準備条件を区別する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。RVOLや正量の追加gateを設けない。
        """
        frames = golden()
        quantities = quantity_map(frames)
        quantities[20]["観測差分量"] = 0.
        grouped, quality = generate(entrance_fixture(frames, quantities))
        self.assertEqual(tuple(len(v) for v in grouped.values()), (1, 0))
        raw = quality["全Q発動記録"][0]
        self.assertTrue(raw["共通M準備"])
        self.assertEqual(raw["OBV比較差"], 0.)
        self.assertTrue(raw["先着評価対象"])
        quantities[20]["数量基準完全"] = False
        grouped, quality = generate(entrance_fixture(frames, quantities))
        self.assertEqual(tuple(len(v) for v in grouped.values()), (0, 0))
        self.assertFalse(quality["全Q発動記録"][0]["共通M準備"])

    def test_MACD差の同値と逆向きは両案不採用でも価格rawを残す(self) -> None:
        """生MACD水準や一指標だけで反転採用としない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。未来のヒスト改善を待って取り直さない。
        """
        for change in (0., -1.):
            rows = entrance_fixture()
            rows[-1]["macd_hist"] = change
            grouped, quality = generate(rows)
            self.assertEqual(quality["原価格発動数"], 1)
            self.assertTrue(quality["全Q発動記録"][0]["共通M準備"])
            self.assertEqual(tuple(len(v) for v in grouped.values()), (0, 0))

    def test_価格kの最新同値と方向別量区間を選び全20数量完全を足さない(self) -> None:
        """kより前の欠測や反対側kを、実sideの準備へ混ぜない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。共通Mは方向別に作りrawへ実方向分を写す。
        """
        frames = golden()
        frames[2].update(low=80., high=200.)
        frames[10]["low"] = 80.
        frames[-1]["low"] = 79.
        quantities = quantity_map(frames)
        quantities[5]["数量基準完全"] = False
        quantities[20]["観測差分量"] = 20.
        grouped, quality = generate(entrance_fixture(frames, quantities))
        raw = quality["全Q発動記録"][0]
        self.assertEqual(raw["OBV_k参照"]["index"], 10)
        self.assertTrue(raw["共通M準備"])
        self.assertTrue(raw["方向別準備"]["1"]["共通M準備"])
        self.assertFalse(raw["方向別準備"]["-1"]["共通M準備"])
        self.assertEqual(tuple(len(v) for v in grouped.values()), (1, 1))

    def test_kと当足が別量区間ならR0にも同じ準備除外を課す(self) -> None:
        """R1だけ量品質の良い区間へ選別する対照にしない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。価格窓は量不完全だけではclearしない。
        """
        frames = golden()
        quantities = quantity_map(frames)
        quantities[19]["数量基準完全"] = False
        grouped, quality = generate(entrance_fixture(frames, quantities))
        self.assertEqual(quality["原価格発動数"], 1)
        raw = quality["全Q発動記録"][0]
        self.assertEqual(len(raw["前20足番号"]), 20)
        self.assertFalse(raw["共通M準備"])
        self.assertEqual(tuple(len(v) for v in grouped.values()), (0, 0))

    def test_価格欠枠NP不正と場開始で20窓を借用せず将来足も既存rawを変えない(self) -> None:
        """公開価格20本の連続性とprefix不変を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。数値銀行carryは場内公開20窓の代用にならない。
        """
        for mode in ("missing", "NP", "番号欠"):
            rows = entrance_fixture()
            if mode == "missing":
                rows[10]["missing"] = 1
            elif mode == "NP":
                rows[10]["publish"] = False
            else:
                for row in rows[10:]:
                    row["index"] += 1
            _, quality = generate(rows)
            self.assertEqual(quality["原価格発動数"], 0)
        rows = entrance_fixture()
        _, before = generate(rows)
        later = deepcopy(rows[-1])
        later.update(index=21, low=1., high=1000., close=900., end=3960., confirm=3960., confirm_line=100)
        _, after = generate([*rows, later])
        self.assertEqual(before["全Q発動記録"], after["全Q発動記録"][:len(before["全Q発動記録"])] )
        self.assertEqual(before["複合context記録"], after["複合context記録"][:21])
        _, only = generate(rows[-1:])
        self.assertEqual(only["原価格発動数"], 0)

    def test_時間遅延不可でもrawを消さず共通Mから分けて先着対象外とする(self) -> None:
        """新規停止/残60分/確認遅延30秒の境界を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。未来labelの数値をこの生成へ渡さない。
        """
        for mode in ("停止等号", "残り不足", "遅延超", "境界可"):
            rows = entrance_fixture()
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
            raw = quality["全Q発動記録"][0]
            self.assertTrue(raw["共通M準備"])
            self.assertEqual(raw["先着評価対象"], mode == "境界可")
            self.assertEqual(tuple(len(v) for v in grouped.values()), (1, 1) if mode == "境界可" else (0, 0))

    def test_二案全採否を深複写しcaseの後変更をrawや他案へ漏らさない(self) -> None:
        """共通集合の全判定と将来ラベル非混入を生成直後に検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。元の人工入力も変更しない。
        """
        rows = entrance_fixture()
        before = deepcopy(rows)
        grouped, quality = generate(rows)
        raw = quality["全Q発動記録"][0]
        for records in grouped.values():
            self.assertEqual(records[0]["戦略判定"], raw["戦略判定"])
            self.assertNotIn("ラベル", records[0])
        grouped["3分_R0"][0]["戦略判定"]["R1"]["理由"].append("人工変更")
        self.assertNotIn("人工変更", raw["戦略判定"]["R1"]["理由"])
        self.assertNotIn("人工変更", grouped["3分_R1"][0]["戦略判定"]["R1"]["理由"])
        self.assertEqual(rows, before)


@contextmanager
def driver_fixture(name: str) -> Iterator[tuple[Any, Path, Path, dict]]:
    """主driverのファイル境界だけを人工保存先へ差し替える。

    引数: name(str)はmodule識別名。
    返り値: Iterator[tuple[Any,Path,Path,dict]]はdriver/人工study/work/66場名台帳。
    """
    driver = load(HERE / "検証.py", name)
    with tempfile.TemporaryDirectory(prefix="OBV主境界合成_", dir=ROOT / "work") as folder:
        study, work = Path(folder) / "study", Path(folder) / "work"
        study.mkdir()
        work.mkdir()
        (study / "条件.json").write_text(json.dumps(I.expected_config(), ensure_ascii=False), encoding="utf-8")
        pointer = {"参照": str(driver.OLD_STUDY / "入力台帳.json"), "SHA256": sha(driver.OLD_STUDY / "入力台帳.json")}
        (study / "入力台帳.json").write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
        (study / "計画.md").write_text("人工固定計画\n", encoding="utf-8")
        sessions = [f"2026-09-{1+i//2:02d}_{'Day' if i%2 == 0 else 'Night'}" for i in range(40)]
        sessions += [f"2026-10-{20+i//2:02d}_{'Day' if i%2 == 0 else 'Night'}" for i in range(24)]
        sessions += ["2026-11-04_Day", "2026-11-04_Night"]
        yield driver, study, work, {"entries": [{"session": name} for name in sessions]}


def driver_block(driver: Any, session: str) -> dict:
    """人工入口だけを主driverの当場schemaへ包む。

    引数: driver(Any)は主module、session(str)は人工場名。
    返り値: dictは数値/数量/純採用と空eventで、先着/損益値は持たない。
    """
    rows = entrance_fixture()
    for row in rows:
        row["場"] = session
    signals, quality = driver.I.generate(rows, session, 10000., 20000., I.expected_config())
    return {"events": [], "frames": {3: rows}, "signals": signals, "quality": quality,
            "numeric_quality": [], "quantity_quality": [], "input_quality": {"場": session},
            "cutoff": 10000., "deadline": 20000., "duration": 100.}


class 主準備と固定境界検証(unittest.TestCase):
    """主の入力参照/非損益準備/純signal/固定拒否を人工で確認する。"""

    def test_人工66prepareは旧台帳参照を固定し先着会計運用を呼ばない(self) -> None:
        """入力pointerと全66×2の準備を人工へ差し替え禁止経路を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。実価格/実量cacheを一切開かない。
        """
        with driver_fixture("OBV合成の非損益準備") as (driver, study, work, manifest):
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
                    patch.object(driver.E, "entry_metrics", side_effect=forbidden) as metric, patch.object(driver, "compressed", side_effect=forbidden) as compressed, redirect_stdout(io.StringIO()):
                driver.run(study, work, prepare_only=True)
            for guard in (freeze, label, path, replay, metric, compressed):
                guard.assert_not_called()
            proof = json.loads((work / "準備点検.json").read_text(encoding="utf-8"))
            self.assertEqual(len(proof["準備"]), 66)
            self.assertEqual(len(proof["場別発動"]), 132)
            self.assertEqual(len(proof["期間別発動"]), 6)
            self.assertEqual(len(set(bank_ids)), 1)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertEqual(proof["参照台帳SHA256"], sha(driver.OLD_STUDY / "入力台帳.json"))
            self.assertFalse((study / "結果.json").exists())
            self.assertTrue(all(not (work / name).exists() for name in driver.FILES))

    def test_未来labelは二案保存caseだけへ付け運用signalへ漏らさない(self) -> None:
        """主driverの二案受渡しを人工labelと空運用で検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。二案目の受渡しで止め、実先着/損益を呼ばない。
        """
        with driver_fixture("OBV合成の純signal受渡し") as (driver, study, work, manifest):
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
                self.assertEqual(args[-1], "反転")
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
            self.assertEqual([cid for cid, _ in received], ["3分_R0_X0", "3分_R1_X0"])
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
        for section, key in ((None, "逆行pt"), (None, "順行pt"), ("運用", "片道手数料円"), ("必須追尾", "起動幅pt"), *[("OBV反転", key) for key in config["OBV反転"]]):
            changed = deepcopy(config)
            target = changed if section is None else changed[section]
            value = target[key]
            target[key] = value + "人工差" if isinstance(value, str) else value+1 if isinstance(value, (int, float)) else []
            with self.assertRaises(ValueError):
                I.validate_config(changed)
        with driver_fixture("OBV合成の固定ガード") as (driver, study, work, manifest):
            prepare = {"コードSHA256": driver.code_pins(), "条件SHA256": sha(study / "条件.json"),
                       "入力台帳SHA256": sha(study / "入力台帳.json"), "参照台帳SHA256": sha(driver.OLD_STUDY / "入力台帳.json")}
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
    parser = argparse.ArgumentParser(description="BB内復帰とOBV非追随の人工検査")
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
             "範囲": "前20BB固定/strict新極値と帯内終値/k最新同値、中心化MACD算術seedと鏡像、0量/同値close/欠測/累積減少/確認行の次足量、価格数値とOBV区間の別reset、missing当足skipと番号飛越seed、方向別共通量準備/価格rawと値採否分離、独立数値と全raw比較、人工66準備の非label/PnL・純signal/固定前後/pointer/既存結果guard。ATR/MACDのみabs1e−10、差符号/OBV/出典/採否は厳密。実原板とwork内npzはstat/open禁止、実先着/PnL未計算。",
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
