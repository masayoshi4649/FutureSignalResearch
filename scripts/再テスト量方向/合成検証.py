"""実市場I/Oを遮断し、再テスト・CMF・公開時点と固定XFの接続を検査する。"""

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
from fractions import Fraction
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
WORK = ROOT/"work/再テスト量方向"
SESSION = "人工再テスト量方向場"
BOUNDS = (0., 10000., 9000., 9500.)


def normalized(path: object) -> str:
    """パスを市場遮断用の絶対表記へ写す。

    引数: path(object)はパス又は非パス値。
    返り値: strは正規表記。非パスは空文字。
    """
    try:
        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError):
        return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """原市場・cache・実圧縮明細を人工検査から遮断する。

    引数: なし。
    返り値: Iterator[None]はコード/小型正本/人工一時先だけを許す範囲。
    """
    raw, work = normalized(ROOT.parent/"JP_OSE_Data"), normalized(ROOT/"work")
    original_open, original_path_open, original_stat = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """対象が実市場資料なら拒否する。

        引数: path(object)はアクセス先。
        返り値: None。人工一時先は明示prefixだけを許す。
        """
        name = normalized(path)
        inside = name.startswith(work+os.sep)
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("再テスト量方向42合成_")
        if (name == raw or name.startswith(raw+os.sep) or inside and
                (name.endswith(".npz") or not artificial and name.endswith((".jsonl.gz", ".trades.jsonl")))):
            raise AssertionError("合成から実市場資料へ触れない:"+str(path))

    def opened(path: object, *args: object, **kwargs: object) -> Any:
        """通常openへ市場遮断を適用する。

        引数: path(object)は先、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
        """
        check(path)
        return original_open(path, *args, **kwargs)

    def path_opened(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.openへ市場遮断を適用する。

        引数: path(Path)は先、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
        """
        check(path)
        return original_path_open(path, *args, **kwargs)

    def stated(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.statへ市場遮断を適用する。

        引数: path(Path)は先、args/kwargs(object)は元引数。
        返り値: Anyは許可されたstat。
        """
        check(path)
        return original_stat(path, *args, **kwargs)

    with patch.object(builtins, "open", opened), patch.object(Path, "open", path_opened), patch.object(Path, "stat", stated):
        yield


def load(path: Path, name: str) -> Any:
    """市場遮断下で定義だけを読み込む。

    引数: path(Path)はコード、name(str)は識別。
    返り値: AnyはCLIを実行しないモジュール。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
        return value


def sha(path: Path) -> str:
    """小型出典の指紋を返す。

    引数: path(Path)はコード又は小型正本。
    返り値: strはSHA256。市場明細は対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


I = load(HERE/"入口.py", "再テスト量方向42合成の入口")
O = load(HERE/"運用.py", "再テスト量方向42合成の運用")
S37 = load(ROOT/"scripts/構造判別/合成検証.py", "再テスト量方向42合成の固定37人工補助")
CONFIG = deepcopy(S37.CONFIG)


def frame(index: int, close: float = 105., **changes: object) -> dict:
    """監査済みQを持つ人工の公開3分足を作る。

    引数: index(int)は番号、close(float)は終値、changes(object)は変更値。
    返り値: dictは実市場を参照しない完全足。
    """
    end = (index+1)*180.
    return {"場": SESSION, "index": index, "minutes": 3, "start": end-180, "end": end,
        "confirm": end, "confirm_line": index+1, "publish": True, "missing": 0,
        "open": 100., "high": 110., "low": 90., "close": close, "atr": 25., "macd_hist": float(index),
        "数量参照": {"数量基準完全": True, "観測差分量": 1.}, **changes}


def material(kind: str = "T") -> list[dict]:
    """b20・時点対象外21・最初j22の人工経路を作る。

    引数: kind(str)はT/R/WAIT。
    返り値: list[dict]は旧R110/L90を登録する23足。
    """
    rows = [frame(index) for index in range(20)]
    rows.append(frame(20, 120., open=115., high=125., low=111.))
    rows.append(frame(21, 120., open=115., high=130., low=105.))
    if kind == "T": rows.append(frame(22, 115., open=110., high=120., low=105.))
    elif kind == "R": rows.append(frame(22, 100., open=105., high=115., low=95., macd_hist=19.))
    else: rows.append(frame(22, 110., open=110., high=120., low=100.))
    return rows


def generated(rows: list[dict], **config_changes: object) -> dict:
    """人工時刻で新監視とCMF三案だけを計算する。

    引数: rows(list[dict])は人工足、config_changes(object)は人工の時間設定。
    返り値: dictは先着/実運用を含まない判定。
    """
    return I.generate(rows, SESSION, 20000., 30000., {"残り時間下限分": 60, "確認遅延上限秒": 30, **config_changes})


def reflected(rows: list[dict], center: float = 1000.) -> list[dict]:
    """価格とヒストを正確な上下反射へ写す。

    引数: rows(list[dict])は足列、center(float)は価格の和。
    返り値: list[dict]は数量と時計を保った鏡像。
    """
    output = deepcopy(rows)
    for row in output:
        old = deepcopy(row)
        row.update(open=center-old["open"], high=center-old["low"], low=center-old["high"],
            close=center-old["close"], macd_hist=-old["macd_hist"])
    return output


class 価格監視とCMF検証(unittest.TestCase):
    """数量と価格監視の責任を分けて最初jを一度だけ消費する。"""

    def test_CMF21定数CLVと鏡像とゼロ境界(self) -> None:
        """CMFを終値変化方向やMFIへ取り違えない。

        引数: self(TestCase)は対象。
        返り値: None。21本目のCLV1/2、鏡像−1/2を照合する。
        """
        rows = [frame(index) for index in range(21)]
        self.assertFalse(I.volume_panels(rows[:20], SESSION)[-1]["CMF準備"])
        result = I.volume_panels(rows, SESSION)[-1]
        self.assertEqual(result["CMF21"], I.exact(Fraction(1, 2)))
        self.assertEqual(result["単位量CLV平均"], I.exact(Fraction(1, 2)))
        self.assertEqual(I.volume_panels(reflected(rows), SESSION)[-1]["CMF21"], I.exact(Fraction(-1, 2)))
        for row in rows: row["close"] = 100.
        self.assertEqual(I.volume_panels(rows, SESSION)[-1]["CMF符号"], 0)

    def test_CMF幅ゼロ数量不完全と総量ゼロを区別する(self) -> None:
        """完全0量は有効で総量0だけ未定義、零幅は補完しない。

        引数: self(TestCase)は対象。
        返り値: None。各理由と21足準備の解除を確認する。
        """
        rows = [frame(index) for index in range(21)]
        for row in rows: row["数量参照"]["観測差分量"] = 0.
        panel = I.volume_panels(rows, SESSION)[-1]
        self.assertEqual(len(panel["CMF窓足番号"]), 21)
        self.assertFalse(panel["CMF準備"])
        self.assertIn("CMF観測総量正未準備", panel["CMF除外理由"])
        rows[0]["数量参照"]["観測差分量"] = 1.
        self.assertTrue(I.volume_panels(rows, SESSION)[-1]["CMF準備"])
        rows[-1].update(open=100., high=100., low=100., close=100.)
        panel = I.volume_panels(rows, SESSION)[-1]
        self.assertFalse(panel["CMF準備"])
        self.assertIn("CLV幅正未準備", panel["CMF窓解除理由"])
        rows[-1] = frame(20); rows[-1]["数量参照"]["数量基準完全"] = False
        self.assertIn("数量基準完全非負未準備", I.volume_panels(rows, SESSION)[-1]["CMF窓解除理由"])

    def test_b次足は対象外で最短二足目の最初jを使う(self) -> None:
        """登録前に形成し始めたヒゲを確認に使わない。

        引数: self(TestCase)は対象。
        返り値: None。21はtouchしても消費せず、22だけ新発動にする。
        """
        result = generated(material())
        self.assertEqual(len(result["registrations"]), 1)
        self.assertEqual(len(result["raw"]), 1)
        self.assertEqual((result["raw"][0]["index"], result["raw"][0]["年齢"]), (22, 2))
        self.assertIn("対象時点外", [action["動作"] for action in result["monitor_trace"][21]["動作"]])
        self.assertTrue(all(len(rows) == 1 for rows in result["signals"].values()))
        row = result["raw"][0]
        self.assertEqual(result["metadata"][row["発動ID"]]["元登録時計秒"], 3780.)
        self.assertEqual(row["要求時計秒"], 4140.)

    def test_TとRと境界WAITを同時点で区別する(self) -> None:
        """CMF不一致やMACD不一致を自動反転へ変換しない。

        引数: self(TestCase)は対象。
        返り値: None。構造/実side/実役割を対応させる。
        """
        expected = {"T": (1, "順行", (1, 1, 1)), "R": (-1, "反転", (1, 1, 0)), "WAIT": (None, "待機", (0, 0, 0))}
        for kind, (side, role, counts) in expected.items():
            result = generated(material(kind)); row = result["raw"][0]
            self.assertEqual((row["構造区分"], row["side"], row["役割"]), (kind, side, role))
            self.assertEqual(tuple(len(result["signals"]["3分_"+p]) for p in I.POLICIES), counts)
        rows = material(); rows[-1]["macd_hist"] = rows[-2]["macd_hist"]
        rows.append(frame(23, 115., open=110., high=120., low=105., macd_hist=30.))
        result = generated(rows)
        self.assertEqual(len(result["raw"]), 1)
        self.assertFalse(result["signals"]["3分_A0"])

    def test_反対端は終値取消を先にしヒゲだけでは取消さない(self) -> None:
        """帯端等号を内側反転へ昇格させない。

        引数: self(TestCase)は対象。
        返り値: None。終値90は取消、安値89/終値115はT。
        """
        rows = material(); rows[-1].update(open=95., high=115., low=85., close=90.)
        result = generated(rows)
        self.assertFalse(result["raw"])
        self.assertIn("反対端終値取消", [action["動作"] for action in result["monitor_trace"][-1]["動作"]])
        rows[-1].update(open=110., high=120., low=89., close=115.)
        self.assertEqual(generated(rows)["raw"][0]["構造区分"], "T")

    def test_数量と登録ATRヒストは価格監視を抑止しない(self) -> None:
        """bは価格/時間だけ、jの量不準備はA0へ先掛けしない。

        引数: self(TestCase)は対象。
        返り値: None。A0は残りA1/A2準備だけが落ちる。
        """
        rows = material()
        rows[20].update(atr=None, macd_hist=None, 数量参照={"数量基準完全": False, "観測差分量": None})
        result = generated(rows)
        self.assertEqual(len(result["registrations"]), 1)
        self.assertEqual(tuple(len(result["signals"]["3分_"+p]) for p in I.POLICIES), (1, 0, 0))
        rows = material(); rows[-1]["数量参照"]["数量基準完全"] = False
        result = generated(rows)
        self.assertEqual(tuple(len(result["signals"]["3分_"+p]) for p in I.POLICIES), (1, 0, 0))
        self.assertEqual(result["quality"]["最初再テスト消費数"], 1)

    def test_寿命七足目と欠枠は先取消し同足再登録しない(self) -> None:
        """物理touchがあっても期限外を新jにしない。

        引数: self(TestCase)は対象。
        返り値: None。親監視を取消した足を新しいbにしない。
        """
        rows = material()[:22]
        rows.extend(frame(index, 120., open=120., high=125., low=115.) for index in range(22, 27))
        rows.append(frame(27, 115., open=110., high=120., low=105.))
        result = generated(rows)
        self.assertFalse(result["raw"])
        self.assertIn("監視満了", [action["動作"] for action in result["monitor_trace"][-1]["動作"]])
        rows = material(); rows[-1]["missing"] = 1
        self.assertFalse(generated(rows)["raw"])

    def test_同方向同水準usedと別水準の登録を分ける(self) -> None:
        """最初bを消費した後の同水準を再使用しない。

        引数: self(TestCase)は対象。
        返り値: None。rollingの前C条件を重複抑止と呼ばない。
        """
        rows = material()+[frame(index) for index in range(23, 43)]
        rows.append(frame(43, 120., open=115., high=125., low=111.))
        result = generated(rows)
        self.assertEqual(len(result["registrations"]), 1)
        reasons = [reason for action in result["monitor_trace"][-1]["動作"] for reason in action.get("理由", [])]
        self.assertIn("同方向固定水準使用済み", reasons)
        for row in rows[23:43]: row["high"] = 111.
        self.assertEqual(len(generated(rows)["registrations"]), 2)

    def test_鏡像と純13列と未来prefixを維持する(self) -> None:
        """構造roleは同じ、実方向とCMF符号は逆にする。

        引数: self(TestCase)は対象。
        返り値: None。親未来とlabelをliveへ渡さない。
        """
        for kind in ("T", "R", "WAIT"):
            left, right = generated(material(kind)), generated(reflected(material(kind)))
            a, b = left["raw"][0], right["raw"][0]
            self.assertEqual(a["構造区分"], b["構造区分"])
            self.assertEqual(a["役割"], b["役割"])
            self.assertEqual(a["CMF符号"], -b["CMF符号"])
            self.assertEqual(a["戦略判定"], b["戦略判定"])
        row = generated(material())["signals"]["3分_A0"][0]
        row["ラベル"] = "未来"
        self.assertEqual(set(I.pure_signal(row)), set(I.SIGNAL_FIELDS))
        long = material()+[frame(23)]
        self.assertEqual(generated(material())["raw"][0], generated(long)["raw"][0])


    def test_最終足bの登録actionだけで正式親集合を復元する(self) -> None:
        """場末取消で監視後がNoneでも登録の全出典を失わない。

        引数: self(TestCase)は対象。
        返り値: None。登録は毎b一回だけ完全snapshotを残す。
        """
        result = generated(material()[:21])
        self.assertIsNone(result["monitor_trace"][-1]["監視後"])
        restored = [action["登録参照"] for row in result["monitor_trace"] for action in row["動作"] if action["動作"] == "突破登録"]
        self.assertEqual(restored, result["registrations"])
        self.assertEqual(len(restored), 1)

    def test_登録遅延とj遅延と対象外反対端を分ける(self) -> None:
        """初回の不可jも消費し、対象外ヒゲ/終値を使わない。

        引数: self(TestCase)は対象。
        返り値: None。全幅対象時点と時間採否を混ぜない。
        """
        rows = material(); rows[21].update(open=95., high=110., low=80., close=85.)
        self.assertEqual(generated(rows)["raw"][0]["index"], 22)
        rows = material(); rows[20]["confirm"] += 31
        self.assertFalse(generated(rows)["registrations"])
        rows = material(); rows[22]["confirm"] += 31
        rows.append(frame(23, 115., open=110., high=120., low=105.))
        result = generated(rows)
        self.assertEqual(len(result["raw"]), 1)
        self.assertFalse(result["raw"][0]["確認遅延条件可"])
        self.assertFalse(result["signals"]["3分_A0"])

    def test_CMF符号一ULPと全正同量旗を採否から分ける(self) -> None:
        """精密ゼロの両側を丸めず、等量旗は十分条件の診断だけにする。

        引数: self(TestCase)は対象。
        返り値: None。価格構造は同じTのままA2だけを分ける。
        """
        for toward, expected in ((None, 0), (math.inf, 1), (-math.inf, -1)):
            rows = material()
            for row in rows[:20]: row["close"] = 100.
            for row in rows[20:22]: row["数量参照"]["観測差分量"] = 0.
            rows[-1].update(open=115., high=125., low=105., close=115. if toward is None else math.nextafter(115., toward))
            row = generated(rows)["raw"][0]
            self.assertEqual(row["CMF符号"], expected)
            self.assertTrue(row["戦略判定"]["A0"]["採用"])
            self.assertEqual(row["戦略判定"]["A2"]["採用"], expected == 1)
            self.assertFalse(row["CMF全量正同値"])
        panel = I.volume_panels([frame(i) for i in range(21)], SESSION)[-1]
        self.assertTrue(panel["CMF全量正同値"])

    def test_独立量加重式と親区間走査の全dictが一致(self) -> None:
        """逐次watchと別手順の区間列挙を人工で照合する。

        引数: self(TestCase)は対象。
        返り値: None。独立完成前だけ途中省略を許す。
        """
        path = HERE/"状態独立確認.py"
        if not path.exists(): self.skipTest("独立API完成前")
        state = load(path, "再テスト量方向42人工の独立入口")
        if not hasattr(state, "generate"): self.skipTest("独立generate完成前")
        examples = [material(k) for k in ("T", "R", "WAIT")]
        examples.extend(reflected(rows) for rows in deepcopy(examples))
        examples.append(material()[:21])
        for change in ({"missing": 1}, {"publish": False}, {"atr": None}, {"macd_hist": None},
                {"数量参照": {"数量基準完全": False, "観測差分量": None}}):
            rows = material(); rows[22].update(change); examples.append(rows)
        for rows in examples:
            self.assertEqual(generated(rows), state.generate(deepcopy(rows), SESSION, 20000., 30000.,
                {"残り時間下限分": 60, "確認遅延上限秒": 30}))


class 切替XF検証(unittest.TestCase):
    """集合切替と実役割を分け、現jATRの固定出口を維持する。"""

    def test_三候補買売実二役割を固定33へ全属性照合する(self) -> None:
        """新しいCMFや親出典をliveに混入させない。

        引数: self(TestCase)は対象。
        返り値: None。全12経路を旧出口と直比較する。
        """
        for policy in I.POLICIES:
            for side in (1, -1):
                for role in ("順行", "反転"):
                    row = S37.signal(policy, side, role); row.update(場=SESSION, 将来ラベル="毒値")
                    events = [S37.quote(11., 11, side, -5.), S37.quote(12., 12, side, 15.),
                        S37.quote(13., 13, side, 0.), S37.quote(14., 14, side, -5.)]
                    args = (events, [row], [], SESSION, "3分_"+policy+"_XF", CONFIG, {"出口ID": "XF"}, "切替", BOUNDS)
                    actual, quality = O.replay(*args)
                    expected, info = O.BASE.replay(events, [O.pure_signal(row)], [], *args[3:])
                    for key in ("orders", "fills", "trades", "signals", "normal_log"):
                        self.assertEqual(getattr(actual, key), getattr(expected, key))
                    self.assertEqual(quality, info)
                    self.assertEqual(actual.trades[0]["入口役割"], role)

    def test_T完結後Rへ切替え現jATRと保有役割を固定する(self) -> None:
        """保有中の反対役割は抑止し、次建玉だけ新ATRを使う。

        引数: self(TestCase)は対象。
        返り値: None。買売鏡像でT→Rを同一場に作る。
        """
        for side in (1, -1):
            rows = [S37.signal("A0", side, "順行", "最初T", 10., 10),
                S37.signal("A0", -side, "反転", "保有中R", 12.5, 125),
                S37.signal("A0", -side, "反転", "後続R", 20., 200)]
            for row in rows: row["場"] = SESSION
            rows[2]["atr"] = 40.
            events = [S37.quote(11., 110, side, -5.), S37.quote(12., 120, side, 15.),
                S37.quote(13., 130, side, 0.), S37.quote(14., 140, side, -5.),
                S37.quote(21., 210, -side, -5.), S37.quote(22., 220, -side, 15.),
                S37.quote(23., 230, -side, 0.), S37.quote(24., 240, -side, -5.)]
            state, info = O.replay(events, rows, [], SESSION, "3分_A0_XF", CONFIG, {"出口ID": "XF"}, "切替", BOUNDS)
            self.assertEqual([row["入口役割"] for row in state.trades], ["順行", "反転"])
            self.assertEqual([row["追尾距離pt"] for row in state.trades], [25., 40.])
            self.assertEqual([row["取扱"] for row in state.signals], ["新規約定", "建玉中抑止", "新規約定"])
            logs = [row for row in state.normal_log if row["建玉"] and row["建玉"]["event_id"] == rows[0]["イベントID"]]
            self.assertTrue(all(row["建玉"]["entry_role"] == "順行" for row in logs))
            self.assertEqual(info["入口役割"], "取引ごと固定")


def driver_module() -> Any:
    """主CLIを起動せず現在の定義だけを読み込む。

    引数: なし。
    返り値: Anyは実市場I/Oを遮断した主モジュール。
    """
    return load(HERE/"検証.py", "再テスト量方向42人工の主")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """新母集団用の人工数値束と保存先を作る。

    引数: driver(Any)は主、count(int)は場数。
    返り値: Iterator[Any]は一時study/work/数値束/buildの組。
    """
    with tempfile.TemporaryDirectory(prefix="再テスト量方向42合成_", dir=ROOT/"work") as temporary:
        folder = Path(temporary); study, work = folder/"study", folder/"work"
        study.mkdir(); work.mkdir()
        config = driver.expected_config()
        driver.W.write_json(study/"条件.json", config)
        for name in ("入力台帳.json", "指標参照.json"):
            driver.W.write_json(study/name, {"人工": True})
        (study/"計画.md").write_text("人工の新発動固定対象\n", encoding="utf-8")
        driver.W.write_json(work/"診断予定.json", {"人工": True})
        sessions = [str(date(2026, 9, 22)+timedelta(days=i//2))+("_Day" if i%2 == 0 else "_Night") for i in range(count)]
        bundle = {"lower": {}}
        for name in sessions:
            rows = material()
            for row in rows: row["場"] = name
            bundle["lower"][name] = rows

        def built(entry: dict, manifest: dict, shared: dict, current: dict, include_events: bool = False) -> dict:
            """新I.generateを通して人工の純入口と正式時の気配だけを作る。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式フラグ。
            返り値: dictは原板stat/cacheを使わない場材料。
            """
            name = entry["session"]
            frames = deepcopy(shared["lower"][name])
            block = driver.I.generate(frames, name, 9000., 9500., current)
            block["signals"] = {sid: [driver.I.pure_signal(row, sid[3:]) for row in values]
                for sid, values in block["signals"].items()}
            block.update(frames={3: frames}, input_quality=deepcopy(block["quality"]), events=[],
                cutoff=9000., deadline=9500., duration=10000./60)
            if include_events:
                block["events"] = [S37.quote(4140., 1, 1, -5.), S37.quote(4141., 2, 1, -5.),
                    S37.quote(4142., 3, 1, 15.), S37.quote(4143., 4, 1, 5.),
                    S37.quote(4144., 5, 1, 0.), S37.quote(4145., 6, 1, -5.)]
            return block

        yield SimpleNamespace(study=study, work=work, config=config, bundle=bundle, built=built,
            manifest={"source_root": "人工予約だけ", "entries": [{"session": name} for name in sessions]},
            ref={"文書と証明": {}, "共有明細": []})


class 主接続検証(unittest.TestCase):
    """新再テストj・数値共有・非損益準備・正式末尾を人工で接続する。"""

    def test_共有は29の3分数値だけで旧caseや上位を読まない(self) -> None:
        """新母集団へ旧入口/ラベルを紛れ込ませない。

        引数: self(TestCase)は対象。
        返り値: None。読取名は全指標だけで、その3分行へ限定する。
        """
        driver = driver_module()
        rows = material()+[{"minutes": 15, "場": "上位を使わない"}]
        with patch.object(driver, "validate_reference", return_value={}), \
                patch.object(driver, "shared_path", side_effect=lambda ref, name: Path(name)) as resolved, \
                patch.object(driver, "read_rows", return_value=rows) as read:
            bundle = driver.read_bundle(driver.STUDY)
        self.assertEqual(bundle, {"lower": {SESSION: rows[:-1]}})
        self.assertEqual(resolved.call_args.args[1], "全指標.jsonl.gz")
        self.assertEqual(read.call_count, 1)

    def test_CLI人工66準備はlabel運用損益を一切呼ばない(self) -> None:
        """66場の新再テストjと全監視/CMF/採否だけをCLIまで通す。

        引数: self(TestCase)は対象。
        返り値: None。旧全同値/ラベル証明を新母集団の準備へ要求しない。
        """
        driver = driver_module()
        with artificial_driver(driver, 66) as f, \
                patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", return_value=f.ref), \
                patch.object(driver, "read_bundle", return_value=f.bundle), \
                patch.object(driver, "build_session", side_effect=f.built) as built, \
                patch.object(driver, "freeze", side_effect=AssertionError("準備を固定しない")), \
                patch.object(driver.W.OLD, "気配経路", side_effect=AssertionError("準備で先着を呼ばない")), \
                patch.object(driver.W.PREP, "read_events", side_effect=AssertionError("準備で気配を読まない")), \
                patch.object(driver.E, "entry_metrics", side_effect=AssertionError("準備で先着集計しない")), \
                patch.object(driver.S, "operation_metrics", side_effect=AssertionError("準備で損益集計しない")), \
                patch.object(driver.ENGINE, "replay", side_effect=AssertionError("準備で運用しない")), \
                patch.object(sys, "argv", ["検証.py", "--study", str(f.study), "--work", str(f.work), "--prepare"]), \
                redirect_stdout(io.StringIO()):
            driver.main()
            proof = driver.W.read_json(f.work/"準備点検.json")
            self.assertEqual(len(proof["準備"]), 66)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertTrue(all(call.args[-1] is False for call in built.call_args_list))
            self.assertEqual(len(proof["準備"][0]["判定"]), 1)
            self.assertEqual(len(proof["準備"][0]["純信号"]), 3)
            self.assertEqual(proof["準備"][0]["3分投影足数"], 23)
            saved = proof["準備"][0]
            self.assertEqual(len(saved["登録"]), 1)
            self.assertEqual(len(saved["監視"]), 23)
            self.assertEqual(saved["CMF足数"], 23)
            self.assertEqual(saved["登録SHA256"], I.canonical_sha(saved["登録"]))
            self.assertEqual(saved["監視SHA256"], I.canonical_sha(saved["監視"]))
            self.assertFalse((f.study/"結果.json").exists())
            self.assertFalse(any((f.work/name).exists() for name in driver.FILES))

    def test_人工正式新先着と三運用を末尾まで保存する(self) -> None:
        """新しい先着を使い、旧対照なしで三caseと三台帳を作る。

        引数: self(TestCase)は対象。
        返り値: None。人工labelだけでAPIの125/250と全保存形を確認する。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            label = {"ラベル": "未約定", "理由": "人工先着APIだけ", **{key: None for key in driver.LABEL_FIELDS[2:]}}
            calls, evaluations = [], []

            def evaluate(now: float, cutoff: float, deadline: float, side: int, **kwargs: object) -> dict:
                """実相場を走査せず新規先着の時点と幅を点検する。

                引数: now/cutoff/deadline(float)は時計、side(int)は方向、kwargs(object)は125/250。
                返り値: dictは人工のラベル。
                """
                self.assertEqual(kwargs, {"adverse": 125, "favorable": 250})
                evaluations.append((now, side))
                return deepcopy(label)

            original = driver.ENGINE.replay

            def replayed(*args: Any, **kwargs: Any) -> Any:
                """純13列だけを新候補の人工XFへ渡す。

                引数: args/kwargs(Any)は主運用契約。
                返り値: Anyは人工時計範囲での固定出口。
                """
                self.assertTrue(all(set(row) == set(I.SIGNAL_FIELDS) for row in args[1]))
                calls.append(args[4])
                return original(*args, **kwargs, bounds=BOUNDS)

            def published(study: Path, *args: Any) -> None:
                """Viewer境界を人工の三資源へ限定する。

                引数: study(Path)は一時先、args(Any)は出力契約。
                返り値: None。実Viewerを起動しない。
                """
                driver.W.write_json(study/"一覧.resources.json", {"resources": [{"id": "00008_人工"+str(i)} for i in range(3)]})

            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "read_bundle", return_value=f.bundle), \
                    patch.object(driver, "build_session", side_effect=f.built), \
                    patch.object(driver, "freeze", return_value={}), \
                    patch.object(driver.W.OLD, "気配経路", return_value=SimpleNamespace(evaluate=evaluate)), \
                    patch.object(driver.ENGINE, "replay", side_effect=replayed), \
                    patch.object(driver.E, "publish_details", side_effect=published), redirect_stdout(io.StringIO()):
                result = driver.run(f.study, f.work, False)
            self.assertEqual((result["入口評価数"], result["運用候補数"]), (3, 3))
            self.assertEqual(calls, ["3分_"+p+"_XF" for p in I.POLICIES])
            self.assertEqual(evaluations, [(4140., 1)])
            import gzip
            with gzip.open(f.work/"入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
                cases = [json.loads(line) for line in stream]
            with gzip.open(f.work/"全運用詳細.jsonl.gz", "rt", encoding="utf-8") as stream:
                details = [json.loads(line) for line in stream]
            self.assertEqual(len(cases), 3)
            self.assertEqual(len(details), 3)
            self.assertTrue(all(row["元価格side"] == 1 and row["元価格発動ID"].endswith("再テスト_0022_T") for row in cases))
            self.assertTrue(all(row["元登録時計秒"] == 3780. and row["元登録原板行"] == 21 and row["判別種別"] == "T" for row in cases))
            self.assertTrue(all(row["元登録ID"].endswith("0020_1") for row in cases))
            self.assertTrue(all("元39J0イベントID" not in row for row in cases))
            self.assertEqual(len(driver.W.read_json(f.study/"結果.json")["役割別入口評価"]), 6)
            artifacts = driver.W.read_json(f.study/"作業成果物.json")["ファイル"]
            self.assertEqual(len(artifacts), 5)
            self.assertEqual({Path(row["パス"]).name for row in artifacts}, set(driver.FILES))
            self.assertFalse((f.study/"W0対照同値.json").exists())

    def test_条件変更とpartialを数値処理前に拒否する(self) -> None:
        """新監視/数量方向の変更と正式明細の上書きを止める。

        引数: self(TestCase)は対象。
        返り値: None。人工一時先以外を編集しない。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            wrong = deepcopy(f.config); wrong["再テスト量方向"]["L2"] = "結果後調整"
            with self.assertRaises(ValueError): driver.validate_config(wrong)
            (f.work/driver.FILES[0]).write_bytes("人工partial".encode("utf-8"))
            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "read_bundle", side_effect=AssertionError("partial後に資料を開かない")):
                with self.assertRaises(ValueError): driver.run(f.study, f.work, False)

    def test_単一数値参照の証明欠落と固定差を拒否する(self) -> None:
        """旧価格Pや旧台帳を追加参照する変更も拒否する。

        引数: self(TestCase)は対象。
        返り値: None。実gzipの読取は宣言済みSHAへ置換する。
        """
        driver = driver_module()
        path = driver.STUDY/"指標参照.json"
        if not path.exists(): self.skipTest("主の数値参照完成前")
        pointer = driver.W.read_json(path)
        declared = {normalized(ROOT/row["パス"]): row["圧縮SHA256参考"] for row in pointer["共有明細"]}
        expanded = {normalized(ROOT/row["パス"]): row["展開内容SHA256"] for row in pointer["共有明細"]}
        guard = driver.M.M
        original = guard.O.sha
        with artificial_driver(driver, 1) as f, \
                patch.object(guard.O, "sha", side_effect=lambda p: declared[normalized(p)] if normalized(p) in declared else original(p)), \
                patch.object(guard, "content_sha", side_effect=lambda p: expanded[normalized(p)]):
            driver.W.write_json(f.study/"指標参照.json", pointer)
            driver.validate_reference(f.study)
            for key in ("文書と証明", "共有明細"):
                wrong = deepcopy(pointer)
                if key == "文書と証明": wrong[key].pop(next(iter(wrong[key])))
                else: wrong[key] = []
                driver.W.write_json(f.study/"指標参照.json", wrong)
                with self.assertRaises(ValueError): driver.validate_reference(f.study)
            wrong = deepcopy(pointer); wrong["旧固定SHA256"] = "0"*64
            driver.W.write_json(f.study/"指標参照.json", wrong)
            with self.assertRaises(ValueError): driver.validate_reference(f.study)
            with self.assertRaises(ValueError): driver.validate_reference(f.study, "入口参照.json")

    def test_固定は主独立最終人工の全現在版joinを必須にする(self) -> None:
        """旧入口同値を要求せず、登録監視準備の失敗/欠落/古版を止める。

        引数: self(TestCase)は対象。
        返り値: None。固定ファイルは人工一時先だけへ作る。
        """
        driver = driver_module()
        if not (HERE/"追尾独立確認.py").exists(): self.skipTest("独立CLI完成前")
        with artificial_driver(driver, 1) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", return_value=f.ref), \
                patch.object(driver, "read_bundle", return_value=f.bundle), \
                patch.object(driver, "build_session", side_effect=f.built), redirect_stdout(io.StringIO()):
            driver.run(f.study, f.work, True)
            finance = driver.W.read_json(driver.WORK/"会計人工接続.json")
            driver.W.write_json(f.work/"会計人工接続.json", finance)
            (f.work/"会計人工接続.py").write_bytes((driver.WORK/"会計人工接続.py").read_bytes())
            dep = ROOT/"scripts/OBV反転/入口.py"
            proof = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
                "主準備SHA256": sha(f.work/"準備点検.json"), "主コードSHA256": driver.code_pins(),
                "条件SHA256": sha(f.study/"条件.json"), "入力台帳SHA256": sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256": sha(driver.MANIFEST_PATH), "指標参照SHA256": sha(f.study/"指標参照.json"),
                "コードSHA256": sha(HERE/"状態独立確認.py"), "追尾コードSHA256": sha(HERE/"追尾独立確認.py"),
                "依存コードSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
            synthetic = {"全件成功": True, "合成編集終了": False,
                "ファイルSHA256": {path.relative_to(ROOT).as_posix(): sha(path) for path in
                    [HERE/name for name in ("検証.py", "入口.py", "運用.py", "合成検証.py")]+[f.study/"条件.json"]},
                "独立数値補助SHA256": sha(HERE/"状態独立確認.py"), "独立追尾補助SHA256": sha(HERE/"追尾独立確認.py")}
            synthetic_file = f.work/"人工最終合成.json"
            driver.W.write_json(synthetic_file, synthetic)
            independent = f.work/"独立準備点検.json"
            old_read, old_sha = driver.W.read_json, driver.O.sha

            def read_json(path: Path) -> dict:
                """直前固定pinと最終人工の宣言だけを人工へ差替える。

                引数: path(Path)は小型証拠。
                返り値: dictは人工又は実小型正本。
                """
                if normalized(path) == normalized(driver.PREVIOUS/"固定.json"):
                    return {"ファイルSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
                return deepcopy(synthetic) if normalized(path) == normalized(WORK/"合成検証.json") else old_read(path)

            def current_sha(path: Path) -> str:
                """実最終人工パスだけ一時証明へ写す。

                引数: path(Path)は指紋対象。
                返り値: strは人工又は正本SHA。
                """
                return sha(synthetic_file) if normalized(path) == normalized(WORK/"合成検証.json") else old_sha(path)

            with patch.object(driver.W, "read_json", side_effect=read_json), patch.object(driver.O, "sha", side_effect=current_sha):
                with self.assertRaises(FileNotFoundError): driver.freeze(f.study, f.work)
                driver.W.write_json(independent, proof)
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                synthetic["合成編集終了"] = True
                for key in proof:
                    wrong = deepcopy(proof)
                    wrong[key] = not proof[key] if isinstance(proof[key], bool) else "不一致" if not isinstance(proof[key], dict) else {}
                    driver.W.write_json(independent, wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(independent, proof)
                for key in ("独立数値補助SHA256", "独立追尾補助SHA256"):
                    correct = synthetic[key]; synthetic[key] = "0"*64
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                    synthetic[key] = correct
                for key in ("全件一致", "不一致数", "人工経路数", "コードSHA256", "条件SHA256", "実行中code不変"):
                    wrong = deepcopy(finance)
                    wrong[key] = (False if key in ("全件一致", "実行中code不変") else {}
                        if key == "コードSHA256" else "0"*64 if key == "条件SHA256" else -1)
                    driver.W.write_json(f.work/"会計人工接続.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                for source in ("scripts/再テスト量方向/独立監査.py", "scripts/再テスト量方向/運用.py", "work/再テスト量方向/00042/会計人工接続.py"):
                    wrong = deepcopy(finance); wrong["コードSHA256"].pop(source)
                    driver.W.write_json(f.work/"会計人工接続.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                wrong = deepcopy(finance)
                first = next(iter(wrong["コードSHA256"]))
                wrong["コードSHA256"][first] = "0"*64
                driver.W.write_json(f.work/"会計人工接続.json", wrong)
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.work/"会計人工接続.json", finance)
                driver.W.write_json(synthetic_file, synthetic)
                locked = driver.freeze(f.study, f.work)
                self.assertEqual(driver.freeze(f.study, f.work), locked)
                self.assertEqual(locked["独立準備SHA256"], sha(independent))
                (f.study/"計画.md").write_text("人工固定後変更\n", encoding="utf-8")
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.study/"結果.json", {"人工": True})
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)



def main() -> None:
    """人工だけを実行して最終許可前は途中証拠を保存する。

    引数: CLI --final(bool)は主独立準備後のroot許可で一回だけ指定する。
    返り値: None。原板/cache/市場先着/損益を使用しない。
    """
    parser = argparse.ArgumentParser(description="再テスト量方向の人工検査")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    paths = [HERE/name for name in ("検証.py", "入口.py", "運用.py", "合成検証.py")]
    paths.append(ROOT/"study/00042_突破再テストと数量加重終値位置/条件.json")
    paths = [path for path in paths if path.exists()]
    helpers = [path for path in (HERE/"状態独立確認.py", HERE/"追尾独立確認.py") if path.exists()]
    pins = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in helpers}
    with deny_market():
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged = pins == {path.relative_to(ROOT).as_posix(): sha(path) for path in paths} and before == {path.relative_to(ROOT).as_posix(): sha(path) for path in helpers}
    success = result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    if args.final and (len(pins) != 5 or len(before) != 2): raise ValueError("主/独立の完成前です")
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
        "市場入力読取": False, "市場先着損益計算": False, "実行中コード条件不変": unchanged,
        "ファイルSHA256": pins, "独立数値補助SHA256": before.get("scripts/再テスト量方向/状態独立確認.py"),
        "独立追尾補助SHA256": before.get("scripts/再テスト量方向/追尾独立確認.py"),
        "skip数": len(result.skipped), "失敗数": len(result.failures), "エラー数": len(result.errors)}
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"出力": str(path), "全件成功": success, "件数": result.testsRun, "SHA256": sha(path)}, ensure_ascii=False))
    if not success: raise SystemExit(1)


if __name__ == "__main__":
    main()

