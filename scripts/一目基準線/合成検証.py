"""28の人工一目/fast条件と公開時点を検査し、固定前の証拠を残す。"""

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
STUDY = ROOT / "study/00028_基準線復帰と上位一目の方向"
WORK = ROOT / "work/一目基準線"


def normalized(path: object) -> str:
    """ファイルに触れず、読取禁止先と比較する絶対表記を作る。

    引数: path(object)はパス又はファイル記述子。
    返り値: strは比較用の表記。パスでなければ空文字。
    """
    try:
        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError):
        return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """合成中の共有原板と実cacheへのstat/openを禁止する。

    引数: なし。
    返り値: Iterator[None]は保護範囲。設定/既知コード/人工足だけを使う。
    """
    banned = [ROOT.parent / "JP_OSE_Data", ROOT / "work/複合検証/キャッシュ",
              ROOT / "work/固定後確認/00027/キャッシュ"]
    starts = [normalized(p) for p in banned]
    original_open, original_path_open, original_stat = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """対象が実市場資料なら呼出しを拒否する。

        引数: path(object)は開く予定のパス。
        返り値: None。禁止対象ではAssertionError。
        """
        name = normalized(path)
        if any(name == head or name.startswith(head + os.sep) for head in starts):
            raise AssertionError("人工合成から実市場資料を開かない:" + str(path))

    def guarded_open(path: object, *args: object, **kwargs: object) -> Any:
        """内容を開く前に実資料への接近を拒否する。

        引数: path(object)は対象、args/kwargs(object)はopen引数。
        返り値: Anyは人工又はコード用のファイル。
        """
        check(path)
        return original_open(path, *args, **kwargs)

    def guarded_path_open(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.openでも実資料を通過させない。

        引数: path(Path)は対象、args/kwargs(object)はopen引数。
        返り値: Anyは許されたファイル。
        """
        check(path)
        return original_path_open(path, *args, **kwargs)

    def guarded_stat(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.statでも実資料へ接近しない。

        引数: path(Path)は対象、args/kwargs(object)はstat引数。
        返り値: Anyは許されたファイルのstat。
        """
        check(path)
        return original_stat(path, *args, **kwargs)

    with patch.object(builtins, "open", guarded_open), patch.object(Path, "open", guarded_path_open), patch.object(Path, "stat", guarded_stat):
        yield


def load(path: Path, name: str) -> Any:
    """対象のAPI定義を実資料の読取禁止下で読み込む。

    引数: path(Path)はPythonコード、name(str)は独立した登録名。
    返り値: Anyは読込モジュール。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module


def frame(index: int, minutes: int = 3, high: float = 105., low: float = 95., close: float = 100., **updates: object) -> dict:
    """明示式で検算できる人工の完全幅OHLCを作る。

    引数: index/minutes(int)は番号/足幅、high/low/close(float)は価格、updates(object)は上書き。
    返り値: dictは原資料を読まない人工足。
    """
    start = index * minutes * 60.
    return {"index": index, "minutes": minutes, "start": start, "end": start + minutes * 60.,
            "confirm": start + minutes * 60., "confirm_line": index + 10, "publish": True, "missing": 0,
            "open": min(high, max(low, close)), "high": high, "low": low, "close": close, **updates}


def golden(count: int = 81, minutes: int = 3) -> list[dict]:
    """最高/最安が常に両端となる単純上昇の人工列を返す。

    引数: count/minutes(int)は足数/足幅。
    返り値: list[dict]はt77のT=1073/J=1064.5/現在雲A=1042.75,B=1025.5となる列。
    """
    return [frame(i, minutes, 1010. + i, 990. + i, 1000. + i) for i in range(count)]


def reflect(frames: list[dict], center: float = 4000.) -> list[dict]:
    """高安を入れ替えて人工系列を上下反射する。

    引数: frames(list[dict])は足、center(float)は元値と鏡像値の和。
    返り値: list[dict]は独立した鏡像。時刻/keyは変更しない。
    """
    result = deepcopy(frames)
    for row in result:
        high, low = row["high"], row["low"]
        row.update(open=center-row["open"], high=center-low, low=center-high, close=center-row["close"])
    return result


def sha(path: Path) -> str:
    """コード/条件だけの内容指紋を計算する。

    引数: path(Path)はコード又は条件。
    返り値: strはSHA256。原板/cacheを対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


J = load(HERE / "指標.py", "一目合成の数値銀行")
I = load(HERE / "入口.py", "一目合成の同時点入口")
SESSION = "人工一目場"
CONTRACT = ("人工限月",)


def entrance_fixture() -> tuple[list[dict], list[dict]]:
    """数式と値選別を分離するため、既知の公開数値を持つ人工対を作る。

    引数: なし。
    返り値: tuple[list[dict],list[dict]]は3分2足と同時点公開15分1足。
    """
    def row(source: dict, upper: bool = False) -> dict:
        """参照schemaを満たす人工数値列をOHLCへ付ける。

        引数: source(dict)は人工足、upper(bool)は15分の完全一目準備。
        返り値: dictは現在/前値条件の検査専用足。
        """
        values = {k: None for k in J.ICHI_FIELDS}
        if upper:
            values.update(ichimoku_tenkan=120., ichimoku_kijun=110., ichimoku_a=115., ichimoku_b=100.,
                          cloud_a=110., cloud_b=100., cloud_upper=110., cloud_lower=100.)
        return {"場": SESSION, **source, "atr": 20., "stoch_raw": 60., "stoch_k": 40., **values,
                "Fast差厳密符号": 1, "Fast差厳密分子": 20, "Fast差厳密分母": 1,
                "一目数値入力可": True, "一目準備済": upper, "一目公開可": upper, "一目窓本数": 78 if upper else 2,
                "銀行解除理由": [], "雲計算元足": None}

    prior = row(frame(8, close=100., confirm_line=19))
    current = row(frame(9, close=101., confirm_line=20))
    prior["ichimoku_kijun"] = 100.
    current["ichimoku_kijun"] = 1000.
    higher = row(frame(1, 15, 130., 90., 120., confirm_line=20), True)
    return [prior, current], [higher]


def mirrored_rows(rows: list[dict], center: float = 4000.) -> list[dict]:
    """公開数値も含む入口fixtureを価格の符号反転へ写す。

    引数: rows(list[dict])は数値付き人工足、center(float)は反射定数。
    返り値: list[dict]は価格・雲上下・Fastを反射した列。
    """
    result = reflect(rows, center)
    for old, new in zip(rows, result):
        for key in J.ICHI_FIELDS:
            if old[key] is not None:
                other = {"cloud_upper": "cloud_lower", "cloud_lower": "cloud_upper"}.get(key, key)
                new[key] = center - old[other]
        for key in ("stoch_raw", "stoch_k"):
            if old[key] is not None:
                new[key] = 100 - old[key]
        for key in ("Fast差厳密符号", "Fast差厳密分子"):
            if old[key] is not None:
                new[key] = -old[key]
    return result


def generate(frames: list[dict], higher: list[dict], cutoff: float = 5000., deadline: float = 10000.) -> tuple[dict, dict]:
    """人工時点の入口だけを生成し、先着/損益を一切呼ばない。

    引数: frames/higher(list[dict])は人工3/15分、cutoff/deadline(float)は人工期限。
    返り値: tuple[dict,dict]は三純採用と全context/raw。
    """
    return I.generate(frames, higher, SESSION, cutoff, deadline, I.expected_config())


class 数値窓検証(unittest.TestCase):
    """明示計算と境界から一目/fastの数値銀行を検査する。"""

    def test_雲は78本目で26本前の52窓を使いFastDは16本目が最速(self) -> None:
        """最速準備と高安窓を手計算値へ照合する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。未来に描画する当足A/Bを現在雲と混ぜない。
        """
        for minutes in (3, 15):
            rows, quality = J.NumericBank(minutes).build(golden(81, minutes), SESSION, CONTRACT)
            self.assertTrue(all(r["stoch_raw"] is None for r in rows[:13]))
            self.assertTrue(all(r["stoch_k"] is None for r in rows[:15]))
            self.assertAlmostEqual(rows[13]["stoch_raw"], 2300 / 33)
            self.assertAlmostEqual(rows[15]["stoch_k"], 2300 / 33)
            self.assertTrue(all(not r["一目準備済"] for r in rows[:77]))
            current = rows[77]
            expected = {"ichimoku_tenkan": 1073., "ichimoku_kijun": 1064.5,
                        "cloud_a": 1042.75, "cloud_b": 1025.5, "cloud_upper": 1042.75, "cloud_lower": 1025.5}
            for key, value in expected.items():
                self.assertEqual(current[key], value, key)
            self.assertEqual(current["雲計算元足"]["index"], 51)
            self.assertEqual(current["雲計算元足"]["場"], SESSION)
            self.assertTrue(current["一目公開可"])
            self.assertNotEqual(current["cloud_a"], current["ichimoku_a"])
            self.assertEqual(quality["一目準備足数"], 4)

    def test_上下反射で一目全線と雲上下とFastが対称になる(self) -> None:
        """買売の数値対称を明示反射へ照合する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。主の反射処理を期待値には使わない。
        """
        original = golden()
        a, _ = J.NumericBank(3).build(original, SESSION, CONTRACT)
        b, _ = J.NumericBank(3).build(reflect(original), SESSION, CONTRACT)
        for left, right in zip(a, b):
            for key in J.ICHI_FIELDS:
                other = {"cloud_upper": "cloud_lower", "cloud_lower": "cloud_upper"}.get(key, key)
                if left[key] is None:
                    self.assertIsNone(right[other])
                else:
                    self.assertAlmostEqual(4000-left[key], right[other])
            for key in ("stoch_raw", "stoch_k"):
                if left[key] is not None:
                    self.assertAlmostEqual(100-left[key], right[key])

    def test_後続の巨大値を足しても既存公開列が変わらない(self) -> None:
        """既存prefixの全保存値が将来足に依存しないことを検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。現在雲へ未来26本を参照しない。
        """
        prefix = golden(78)
        a, _ = J.NumericBank(3).build(prefix, SESSION, CONTRACT)
        later = [frame(i, high=5000.+i, low=4500.+i, close=4700.+i) for i in range(78, 110)]
        b, _ = J.NumericBank(3).build(prefix + later, SESSION, CONTRACT)
        self.assertEqual(a, b[:78])

    def test_ゼロ幅でFastだけ解除し一目窓を保持する(self) -> None:
        """ゼロ分母を0/50へ補完せず、FastDの再準備を待つ。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。一目の高安履歴はゼロ幅だけでは消さない。
        """
        flat = [frame(i, high=100., low=100., close=100.) for i in range(81)]
        rows, _ = J.NumericBank(3).build(flat + [frame(i, high=110., low=90., close=105.) for i in range(81, 84)], SESSION, CONTRACT)
        self.assertTrue(rows[80]["一目準備済"])
        self.assertIsNone(rows[80]["stoch_raw"])
        self.assertIsNone(rows[80]["stoch_k"])
        self.assertTrue(all(r["一目窓本数"] == 78 for r in rows[77:]))
        self.assertIsNone(rows[81]["stoch_k"])
        self.assertIsNone(rows[82]["stoch_k"])
        self.assertIsNone(rows[81]["Fast差厳密符号"])
        self.assertIsNone(rows[82]["Fast差厳密符号"])
        self.assertAlmostEqual(rows[83]["stoch_k"], 75.)
        self.assertEqual(rows[83]["Fast差厳密符号"], 0)

    def test_有理数Fast同値は浮動丸めや鏡像で採否を変えない(self) -> None:
        """3/11の定値と非同値の正負を明示分数へ照合する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。epsilonを足さず厳密な数学同値を0とする。
        """
        prefix = [frame(i, high=111., low=100., close=103.) for i in range(16)]
        for next_close, sign, numerator in ((103., 0, 0), (104., 1, 200), (102., -1, -200)):
            source = prefix + [frame(16, high=111., low=100., close=next_close)]
            a, _ = J.NumericBank(3).build(source, SESSION, CONTRACT)
            b, _ = J.NumericBank(3).build(reflect(source), SESSION, CONTRACT)
            self.assertEqual(a[15]["Fast差厳密符号"], 0)
            self.assertEqual(b[15]["Fast差厳密符号"], 0)
            for rows, reflected in ((a, False), (b, True)):
                self.assertEqual(rows[-1]["Fast差厳密符号"], -sign if reflected else sign)
                self.assertEqual(rows[-1]["Fast差厳密分子"], -numerator if reflected else numerator)
                self.assertEqual(rows[-1]["Fast差厳密分母"], 1 if not sign else 33)
        frames, higher = entrance_fixture()
        for sign in (0, 1, -1):
            frames[-1].update(stoch_raw=100*3/11, stoch_k=(100*3/11)*3/3,
                              Fast差厳密符号=sign, Fast差厳密分子=sign, Fast差厳密分母=1)
            grouped, quality = generate(frames, higher)
            self.assertEqual(tuple(len(v) for v in grouped.values()), (1, 1, 1) if sign == 1 else (0, 0, 0))

    def test_一目と精密Fastを独立の原窓再走査にも照合する(self) -> None:
        """明示goldenに加え、異なる手順で原OHLCを再走査した期待へ照合する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。一目全線/精密符号分数は厳密、表示Fastだけ絶対許容1e−12。
        """
        independent = load(HERE / "状態独立確認.py", "一目合成の独立原窓再走査")
        for minutes in (3, 15):
            source = [frame(i, minutes, 111., 100., 103. if i < 80 else 104.) for i in range(81)]
            for values in (source, reflect(source), golden(81, minutes)):
                actual, _ = J.NumericBank(minutes).build(values, SESSION, CONTRACT)
                expected, _ = independent.NumericHistory(minutes).build(values, SESSION, CONTRACT)
                self.assertEqual(len(actual), len(expected))
                for left, right in zip(actual, expected):
                    for key in (*J.ICHI_FIELDS, *J.EXACT_FIELDS, "雲計算元足", "一目数値入力可", "一目準備済", "一目公開可"):
                        self.assertEqual(left[key], right[key], key)
                    for key in ("stoch_raw", "stoch_k"):
                        if left[key] is None:
                            self.assertIsNone(right[key])
                        else:
                            self.assertAlmostEqual(left[key], right[key], delta=1e-12)

    def test_欠枠後の有効当足は初足となり不正足は投入しない(self) -> None:
        """番号欠/欠枠/非有限OHLCの解除位置と再準備を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。不正な価格を補完して窓へ戻さない。
        """
        for mode in ("番号欠", "欠枠", "不正"):
            bank = J.NumericBank(3)
            bank.build(golden(80), SESSION, CONTRACT)
            value = frame(0, missing=1) if mode == "欠枠" else frame(1 if mode == "番号欠" else 0)
            if mode == "不正":
                value["high"] = float("nan")
            result, _ = bank.build([value], "人工次場", CONTRACT)
            row = result[0]
            self.assertEqual(row["一目窓本数"], 0 if mode == "不正" else 1)
            self.assertFalse(row["一目準備済"])
            self.assertEqual(row["一目数値入力可"], mode != "不正")
            json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_末尾NPは内部carryだけで限月と尾部欠枠は解除する(self) -> None:
        """同限月carryと公開用途、明示resetを分離する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。NPを局所公開の前足に使わない。
        """
        bank = J.NumericBank(3)
        prior = golden(78)
        prior[-1].update(publish=False, confirm=None, confirm_line=None)
        rows, _ = bank.build(prior, SESSION, CONTRACT)
        self.assertTrue(rows[-1]["一目準備済"])
        self.assertFalse(rows[-1]["一目公開可"])
        result, _ = bank.build([frame(0, high=1100., low=1080., close=1090.)], "人工次場", CONTRACT)
        self.assertTrue(result[0]["一目準備済"])
        self.assertEqual(result[0]["雲計算元足"]["場"], SESSION)
        changed, q = bank.build([frame(0)], "人工別限月", ("別限月",))
        self.assertFalse(changed[0]["一目準備済"])
        self.assertIn("限月変更", changed[0]["銀行解除理由"])
        bank.build(golden(78), "人工蓄積", CONTRACT, tail_missing=1)
        reset, q = bank.build([frame(0)], "人工欠枠後", CONTRACT)
        self.assertEqual(reset[0]["一目窓本数"], 1)


class 同時点入口検証(unittest.TestCase):
    """価格rawと共通M/値選別を同じ時点で検査する。"""

    def test_前基準線固定crossを同足で発動し現在基準線に置換しない(self) -> None:
        """Cprev=Jprevを許し、現在Jを使わないことを検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。3分現在雲は共通Mに不要。
        """
        frames, higher = entrance_fixture()
        grouped, quality = generate(frames, higher)
        self.assertEqual(quality["原価格発動数"], 1)
        self.assertTrue(all(len(v) == 1 for v in grouped.values()))
        record = quality["全Q発動記録"][0]
        self.assertEqual(record["固定基準線"], 100.)
        self.assertEqual(record["要求時計秒"], frames[-1]["confirm"])
        self.assertTrue(record["共通M準備"])
        self.assertFalse(record["一目準備済"])

    def test_買売鏡像の三案採否と固定線が同じになる(self) -> None:
        """入口値を反転しても同じ複合規則が働くことを検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。売だけ閾値や雲端を変更しない。
        """
        frames, higher = entrance_fixture()
        _, a = generate(frames, higher)
        _, b = generate(mirrored_rows(frames), mirrored_rows(higher))
        left, right = a["全Q発動記録"][0], b["全Q発動記録"][0]
        self.assertEqual(left["side"], -right["side"])
        self.assertEqual(left["戦略判定"], right["戦略判定"])
        self.assertEqual(left["固定基準線"] + right["固定基準線"], 4000.)

    def test_現在終値の基準線等号と非crossは発動しない(self) -> None:
        """境界の等号と既に同方向外側の場合を区別する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。直近足を待って都合よく同じcrossを取り直さない。
        """
        for prior_close, close in ((100., 100.), (101., 102.)):
            frames, higher = entrance_fixture()
            frames[0]["close"], frames[1]["close"] = prior_close, close
            _, quality = generate(frames, higher)
            self.assertEqual(quality["原価格発動数"], 0)

    def test_Fast同値と逆向きは全案不採用でも価格rawを残す(self) -> None:
        """勢い判定と価格消費、反事実の先着対象を分ける。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。Fast値は20/50/80制限へ読み替えない。
        """
        for k, d in ((40., 40.), (30., 40.)):
            frames, higher = entrance_fixture()
            frames[-1].update(stoch_raw=k, stoch_k=d, Fast差厳密符号=0 if k == d else -1,
                              Fast差厳密分子=0 if k == d else -10)
            grouped, quality = generate(frames, higher)
            self.assertEqual(quality["原価格発動数"], 1)
            self.assertTrue(all(not values for values in grouped.values()))
            record = quality["全Q発動記録"][0]
            self.assertTrue(record["共通M準備"])
            self.assertTrue(record["先着評価対象"])
        frames, higher = entrance_fixture()
        frames[-1].update(stoch_raw=99., stoch_k=98.)
        grouped, _ = generate(frames, higher)
        self.assertTrue(all(len(v) == 1 for v in grouped.values()))

    def test_雲外と転換基準の値条件はB0B1B2へ順にだけ適用する(self) -> None:
        """雲内/等号/転換基準等号を数値不準備と区別する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。B1/B2の不採用を逆方向注文へ変換しない。
        """
        for close, tenkan, expected in ((105., 120., (1, 0, 0)), (110., 120., (1, 0, 0)),
                                        (120., 110., (1, 1, 0)), (120., 120., (1, 1, 1))):
            frames, higher = entrance_fixture()
            higher[0].update(close=close, ichimoku_tenkan=tenkan)
            grouped, quality = generate(frames, higher)
            self.assertTrue(quality["全Q発動記録"][0]["共通M準備"])
            self.assertEqual(tuple(len(v) for v in grouped.values()), expected)

    def test_一目不準備やFast欠測はB0にも共通で価格rawだけ残す(self) -> None:
        """完全共通準備を全三案へ課すことを検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。M不成立でもtime/delay可なら原先着対象。
        """
        for mode in ("上位一目", "Fast", "ATR"):
            frames, higher = entrance_fixture()
            if mode == "上位一目":
                higher[0].update(一目準備済=False, 一目公開可=False)
            elif mode == "Fast":
                frames[-1]["stoch_k"] = None
            else:
                frames[-1]["atr"] = 0.
            grouped, quality = generate(frames, higher)
            self.assertEqual(quality["原価格発動数"], 1)
            self.assertTrue(all(not v for v in grouped.values()))
            raw = quality["全Q発動記録"][0]
            self.assertFalse(raw["共通M準備"])
            self.assertTrue(raw["先着評価対象"])

    def test_15分はendと公開key双方の同時点までで同clock原行順も守る(self) -> None:
        """終了済みでも公開が遅い足、先に公開した未来endを拒否する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。等key/endは利用可能。
        """
        for field, value, expected in (("confirm_line", 21, 0), ("end", 1801., 0), ("confirm_line", 20, 1), ("confirm_line", 19, 1)):
            frames, higher = entrance_fixture()
            higher[0][field] = value
            grouped, quality = generate(frames, higher)
            self.assertEqual(tuple(len(v) for v in grouped.values()), (expected, expected, expected))
            self.assertEqual(quality["原価格発動数"], 1)

    def test_最新公開が不準備なら古正常へ戻らずNPは公開参照へ入れない(self) -> None:
        """不準備と未公開の扱いを別の分岐として検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。末尾NP数値carryが現在公開15分の代用にならない。
        """
        frames, higher = entrance_fixture()
        old = deepcopy(higher[0])
        old.update(index=0, start=0., end=900., confirm=900., confirm_line=10)
        higher[0].update(一目準備済=False, 一目公開可=False)
        grouped, quality = generate(frames, [old, *higher])
        self.assertTrue(all(not v for v in grouped.values()))
        self.assertEqual(quality["全Q発動記録"][0]["上位参照"]["index"], 1)
        higher[0].update(publish=False, confirm=None, confirm_line=None)
        grouped, quality = generate(frames, [old, *higher])
        self.assertTrue(all(len(v) == 1 for v in grouped.values()))
        self.assertEqual(quality["全Q発動記録"][0]["上位参照"]["index"], 0)

    def test_3分の欠枠NPと場開始では前公開を借りてcrossしない(self) -> None:
        """同場隣接公開2本だけで価格を発動させる。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。後続確認の待機状態は保持しない。
        """
        for mode in ("場開始", "番号欠", "現在NP", "前NP", "欠枠"):
            frames, higher = entrance_fixture()
            if mode == "場開始":
                frames = frames[-1:]
            elif mode == "番号欠":
                frames[-1]["index"] += 1
            elif mode == "現在NP":
                frames[-1]["publish"] = False
            elif mode == "前NP":
                frames[0]["publish"] = False
            else:
                frames[-1]["missing"] = 1
            grouped, quality = generate(frames, higher)
            self.assertEqual(quality["原価格発動数"], 0)

    def test_別場の上位又は下位rowを現在公開値の代用にしない(self) -> None:
        """銀行carryの数値と当場公開rowを入力境界で分離する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。別場rowを混ぜた入力は明示拒否する。
        """
        for upper in (True, False):
            frames, higher = entrance_fixture()
            (higher if upper else frames)[0]["場"] = "別の人工場"
            with self.assertRaises(ValueError):
                generate(frames, higher)

    def test_時間と遅延不可はrawを残すが採用と先着対象へ入れない(self) -> None:
        """新規停止/残り60分/確認30秒の境界を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。共通Mと時間条件は別に記録する。
        """
        for mode in ("停止等号", "残り不足", "遅延超", "境界可"):
            frames, higher = entrance_fixture()
            cutoff, deadline = 5000., 10000.
            if mode == "停止等号":
                cutoff = 1800.
            elif mode == "残り不足":
                deadline = 5399.
            elif mode == "遅延超":
                frames[-1]["confirm"] += 31.
            else:
                frames[-1]["confirm"] += 30.
                deadline = frames[-1]["confirm"] + 3600.
            grouped, quality = generate(frames, higher, cutoff, deadline)
            self.assertEqual(quality["原価格発動数"], 1)
            raw = quality["全Q発動記録"][0]
            self.assertTrue(raw["共通M準備"])
            self.assertEqual(raw["先着評価対象"], mode == "境界可")
            self.assertEqual(tuple(len(v) for v in grouped.values()), (1, 1, 1) if mode == "境界可" else (0, 0, 0))

    def test_全採否は確定後に深複写して後変更を他案へ漏らさない(self) -> None:
        """全B判定がcanonicalと同じ内容で別オブジェクトとして保存される。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。市場の未来先着を入口へ渡さない。
        """
        frames, higher = entrance_fixture()
        before = deepcopy((frames, higher))
        grouped, quality = generate(frames, higher)
        raw = quality["全Q発動記録"][0]
        for name, records in grouped.items():
            self.assertEqual(records[0]["戦略判定"], raw["戦略判定"])
            self.assertNotIn("ラベル", records[0])
        grouped["3分_B0"][0]["戦略判定"]["B1"]["理由"].append("人工変更")
        self.assertNotIn("人工変更", raw["戦略判定"]["B1"]["理由"])
        self.assertNotIn("人工変更", grouped["3分_B1"][0]["戦略判定"]["B1"]["理由"])
        self.assertEqual((frames, higher), before)

    def test_同判断に二価格信号があれば全B競合確定後にcaseを作る(self) -> None:
        """同原keyの競合処理だけを人工同時計列で検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。実分足の再現でなく競合枝への明示入力。
        """
        frames, higher = entrance_fixture()
        frames[-1]["ichimoku_kijun"] = 102.
        duplicate = deepcopy(frames[-1])
        duplicate.update(index=10, close=103.)
        grouped, quality = generate([*frames, duplicate], higher)
        self.assertEqual(quality["原価格発動数"], 2)
        self.assertTrue(all(not values for values in grouped.values()))
        for record in quality["全Q発動記録"]:
            self.assertTrue(all(not v["採用"] and v["同時競合"] for v in record["戦略判定"].values()))


class 準備と固定境界検証(unittest.TestCase):
    """既使用66場を人工へ差し替え、固定前に損益を呼ばないことを検査する。"""

    def test_条件の旧数値と精密文字列と全候補の変更を拒否する(self) -> None:
        """運用/支持/新指標の値を後から緩められないことを検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。正式条件を変更せず複写の末端だけを変える。
        """
        original = I.expected_config()
        I.validate_config(original)
        paths = [("逆行pt",), ("順行pt",), ("残り時間下限分",), ("確認遅延上限秒",), ("目標確認率",),
                 *[("運用", k) for k in original["運用"]], *[("必須追尾", k) for k in original["必須追尾"]],
                 *[("一目基準線", k) for k in original["一目基準線"]], ("戦略",), ("出口",), ("全66場既使用",)]
        for path in paths:
            changed = deepcopy(original)
            target = changed
            for key in path[:-1]:
                target = target[key]
            current = target[path[-1]]
            target[path[-1]] = (not current) if isinstance(current, bool) else current + 1 if isinstance(current, (float, int)) else current + "人工差" if isinstance(current, str) else []
            with self.assertRaises(ValueError, msg=str(path)):
                I.validate_config(changed)

    def test_人工66prepareは気配先着会計固定運用へ進まず全三案を保持する(self) -> None:
        """準備専用runnerで禁止経路に到達したら即失敗とする。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。市場入力・原板・cacheは一切開かない。
        """
        driver = load(HERE / "検証.py", "一目合成の準備経路")
        with tempfile.TemporaryDirectory(prefix="一目準備合成_", dir=ROOT / "work") as folder:
            base = Path(folder)
            study, work = base / "study", base / "work"
            study.mkdir()
            config = I.expected_config()
            (study / "条件.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            sessions = [f"2026-09-{1+i//2:02d}_{'Day' if i%2 == 0 else 'Night'}" for i in range(40)]
            sessions += [f"2026-10-{20+i//2:02d}_{'Day' if i%2 == 0 else 'Night'}" for i in range(24)]
            sessions += ["2026-11-04_Day", "2026-11-04_Night"]
            manifest = {"entries": [{"session": name} for name in sessions]}
            (study / "入力台帳.json").write_text(json.dumps(manifest), encoding="utf-8")
            bank_ids = []

            def build(entry: dict, supplied: dict, banks: dict, supplied_config: dict) -> dict:
                """市場読取を人工の数値付き足だけへ差し替える。

                引数: entry/supplied/banks/supplied_config(dict)は主APIの引数。
                返り値: dictは人工当場の純採用と数値品質。
                """
                bank_ids.append(tuple(id(banks[n]) for n in (3, 15)))
                frames, higher = entrance_fixture()
                for row in (*frames, *higher):
                    row["場"] = entry["session"]
                signals, quality = driver.I.generate(frames, higher, entry["session"], 5000., 10000., supplied_config)
                return {"events": [], "frames": {3: frames, 15: higher}, "signals": signals, "quality": quality,
                        "numeric_quality": [], "input_quality": {"場": entry["session"]}, "cutoff": 5000., "deadline": 10000., "duration": 10.}

            forbidden = AssertionError("prepareから先着/会計/運用/固定へ進まない")
            with patch.object(driver, "manifest_for", return_value=manifest), patch.object(driver, "build_session", side_effect=build) as made, \
                    patch.object(driver, "freeze", side_effect=forbidden) as freeze, \
                    patch.object(driver, "shadow_label", side_effect=forbidden) as label, \
                    patch.object(driver.W.OLD, "気配経路", side_effect=forbidden) as path, \
                    patch.object(driver.ENGINE, "replay", side_effect=forbidden) as replay, \
                    patch.object(driver.E, "entry_metrics", side_effect=forbidden) as metric, \
                    patch.object(driver, "compressed", side_effect=forbidden) as compressed, redirect_stdout(io.StringIO()):
                result = driver.run(study, work, prepare_only=True)
                self.assertEqual(made.call_count, 66)
                for guard in (freeze, label, path, replay, metric, compressed):
                    guard.assert_not_called()
            proof = json.loads((work / "準備点検.json").read_text(encoding="utf-8"))
            self.assertEqual(len(proof["準備"]), 66)
            self.assertEqual(len(proof["場別発動"]), 66 * 3)
            self.assertEqual(len(proof["期間別発動"]), 9)
            self.assertEqual(len(set(bank_ids)), 1)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertTrue(result["準備点検"])
            self.assertFalse((study / "固定.json").exists())
            self.assertFalse((study / "結果.json").exists())
            self.assertTrue(all(not (work / name).exists() for name in driver.FILES))

    def test_既存結果を正式再生で上書きしない(self) -> None:
        """既存結果があると新たな数値場生成/先着/運用より先に拒否する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。人工の既存結果本文も保持する。
        """
        driver = load(HERE / "検証.py", "一目合成の既存結果拒否")
        with tempfile.TemporaryDirectory(prefix="一目結果拒否合成_", dir=ROOT / "work") as folder:
            study, work = Path(folder) / "study", Path(folder) / "work"
            study.mkdir()
            (study / "条件.json").write_text(json.dumps(I.expected_config(), ensure_ascii=False), encoding="utf-8")
            (study / "入力台帳.json").write_text('{"entries":[]}', encoding="utf-8")
            existing = study / "結果.json"
            existing.write_text('{"人工既存結果":true}', encoding="utf-8")
            before = existing.read_bytes()
            with patch.object(driver, "manifest_for", return_value={"entries": []}), \
                    patch.object(driver, "build_session", side_effect=AssertionError("数値生成禁止")) as build, \
                    patch.object(driver, "shadow_label", side_effect=AssertionError("先着禁止")) as label, \
                    patch.object(driver.ENGINE, "replay", side_effect=AssertionError("運用禁止")) as replay:
                with self.assertRaises(ValueError):
                    driver.run(study, work, prepare_only=False)
            build.assert_not_called()
            label.assert_not_called()
            replay.assert_not_called()
            self.assertEqual(existing.read_bytes(), before)

    def test_主driverは全三案の未来labelを保存caseだけへ付け運用へ渡さない(self) -> None:
        """人工の将来値を返すlabelと空運用を差し替えて受渡しだけ検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。実資料の先着/会計を呼ばず三案受渡し後に停止する。
        """
        driver = load(HERE / "検証.py", "一目合成の純signal受渡し")
        with tempfile.TemporaryDirectory(prefix="一目受渡し合成_", dir=ROOT / "work") as folder:
            study, work = Path(folder) / "study", Path(folder) / "work"
            study.mkdir()
            config = I.expected_config()
            session = "2026-09-01_Day"
            manifest = {"entries": [{"session": session}]}
            (study / "条件.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            (study / "入力台帳.json").write_text(json.dumps(manifest), encoding="utf-8")
            frames, higher = entrance_fixture()
            for row in (*frames, *higher):
                row["場"] = session
            signals, quality = driver.I.generate(frames, higher, session, 5000., 10000., config)
            before = deepcopy(signals)
            block = {"events": [], "frames": {3: frames, 15: higher}, "signals": signals, "quality": quality,
                     "numeric_quality": [], "input_quality": {"場": session}, "cutoff": 5000., "deadline": 10000., "duration": 10.}
            received = []

            def replay(events: list, pure: list, rows: list, name: str, cid: str, *args: object) -> tuple:
                """人工の全三案を受取り、最後で正式処理を打ち切る。

                引数: events/pure/rows(list)は人工列、name/cid(str)は場/案、args(object)は運用設定。
                返り値: tupleは空運用。三案目は停止用RuntimeError。
                """
                received.append((cid, deepcopy(pure)))
                if len(received) == 3:
                    raise RuntimeError("人工の全三案受渡し完了")
                return SimpleNamespace(trades=[], normal_log=[], fills=[], orders=[], signals=[]), {}

            future = {"ラベル": "人工将来", "人工未来値": 12345, "最大順行pt": 999.}
            with patch.object(driver, "manifest_for", return_value=manifest), patch.object(driver, "build_session", return_value=block), \
                    patch.object(driver, "freeze", return_value={}), patch.object(driver.W.OLD, "気配経路", return_value=object()), \
                    patch.object(driver, "shadow_label", return_value=future), patch.object(driver.ENGINE, "replay", side_effect=replay), \
                    patch.object(driver.E, "entry_metrics", side_effect=AssertionError("人工会計停止後には到達しない")), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "人工の全三案受渡し完了"):
                    driver.run(study, work, prepare_only=False)
            self.assertEqual([cid for cid, _ in received], ["3分_B0_X0", "3分_B1_X0", "3分_B2_X0"])
            for cid, records in received:
                self.assertEqual(len(records), 1)
                self.assertTrue(all(key not in records[0] for key in future))
                self.assertEqual(records[0]["期間"], "学習")
                self.assertIn("要求時計JST", records[0])
                pure = {k: v for k, v in records[0].items() if k not in ("期間", "要求時計JST")}
                self.assertEqual(pure, before[cid.removesuffix("_X0")][0])
            with gzip.open(work / "入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
                cases = [json.loads(line) for line in stream]
            self.assertEqual(len(cases), 3)
            self.assertTrue(all(c["ラベル"] == "人工将来" and c["人工未来値"] == 12345 for c in cases))
            self.assertFalse((study / "結果.json").exists())

    def test_最終合成と準備pinを要求し固定後の計画差も拒否する(self) -> None:
        """人工保存先でfreeze境界と既存固定の不変性を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。実固定/旧資産は編集せず、参照の指紋だけ読む。
        """
        driver = load(HERE / "検証.py", "一目合成の固定前後境界")
        with tempfile.TemporaryDirectory(prefix="一目固定合成_", dir=ROOT / "work") as folder:
            study, work = Path(folder) / "study", Path(folder) / "work"
            study.mkdir()
            work.mkdir()
            for name, text in (("条件.json", json.dumps(I.expected_config(), ensure_ascii=False)), ("入力台帳.json", '{"entries":[]}'), ("計画.md", "人工固定計画\n")):
                (study / name).write_text(text, encoding="utf-8")
            prepare = {"コードSHA256": driver.code_pins(), "条件SHA256": sha(study / "条件.json"), "入力台帳SHA256": sha(study / "入力台帳.json")}
            (work / "準備点検.json").write_text(json.dumps(prepare), encoding="utf-8")
            paths = [HERE / n for n in ("指標.py", "入口.py", "検証.py", "合成検証.py")] + [study / "条件.json"]
            proof = {"全件成功": True, "合成編集終了": True, "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}}
            original = driver.W.read_json
            target = ROOT / "work/一目基準線/合成検証.json"

            def read(path: Path) -> dict:
                """最終合成の参照だけを人工証拠へ差し替える。

                引数: path(Path)は読込予定の正本。
                返り値: dictは人工proof又は変更しない既知JSON。
                """
                return deepcopy(proof) if path == target else original(path)

            with patch.object(driver.W, "read_json", side_effect=read):
                proof["合成編集終了"] = False
                with self.assertRaises(ValueError):
                    driver.freeze(study, work)
                proof["合成編集終了"] = True
                key = (HERE / "指標.py").relative_to(ROOT).as_posix()
                digest = proof["ファイルSHA256"][key]
                proof["ファイルSHA256"][key] = "0" * 64
                with self.assertRaises(ValueError):
                    driver.freeze(study, work)
                proof["ファイルSHA256"][key] = digest
                fixed = driver.freeze(study, work)
                before = (study / "固定.json").read_bytes()
                self.assertEqual(driver.freeze(study, work), fixed)
                self.assertEqual((study / "固定.json").read_bytes(), before)
                (study / "計画.md").write_text("人工の固定後差\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(study, work)
                self.assertEqual((study / "固定.json").read_bytes(), before)


def main() -> None:
    """実装API安定後に合成を実行し、固定用の版と明示合否を残す。

    引数: なし。--finalはrootの最終pin確認後だけ指定する。
    返り値: None。実資料の先着/損益を計算しない。
    """
    parser = argparse.ArgumentParser(description="一目基準線の人工境界検証")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    paths = [HERE / n for n in ("指標.py", "入口.py", "検証.py", "合成検証.py")] + [STUDY / "条件.json"]
    if any(not p.is_file() for p in paths):
        raise ValueError("主3コード/合成/条件のAPI確定を待つ")
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    stream = io.StringIO()
    with deny_market():
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    success = result.wasSuccessful() and result.testsRun > 0
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
             "実資料の先着損益計算": False, "ファイルSHA256": pins,
             "独立数値補助SHA256": sha(HERE / "状態独立確認.py"),
             "範囲": "人工OHLCの一目9/26/52と26本シフト・最速78本、Fast14/3最速16本・有理数strict差、上下反射/欠枠/不正/NPcarry/限月reset、公開end/key/同時原行/前基準固定cross、全B共通M/raw分離・競合確定/深複写、人工66prepareの先着運用禁止、label非混入/固定前後/既存結果拒否。共有原板と実cacheのstat/openは禁止。実資料の先着/PnLは未計算。",
             "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
             "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors],
             "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / ("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k: proof[k] for k in ("全件成功", "検証件数", "合成編集終了", "実資料の先着損益計算")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
