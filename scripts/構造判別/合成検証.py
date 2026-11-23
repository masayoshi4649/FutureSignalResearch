"""旧範囲帰還・外側継続と混合役割を人工入力だけで検査する。"""

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
import gzip
from fractions import Fraction
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
WORK = ROOT / "work/構造判別"
SESSION = "人工構造判別場"
BOUNDS = (0., 10000., 9000., 9500.)


def normalized(path: object) -> str:
    """市場資料へ触れず絶対比較表記を作る。

    引数: path(object)はパス又は記述子。
    返り値: strは正規表記。非パスは空文字。
    """
    try:
        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError):
        return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """実原板・cache・実圧縮明細のstat/openを遮断する。

    引数: なし。
    返り値: Iterator[None]は人工一時先とコードだけを許可する範囲。
    """
    raw, work = normalized(ROOT.parent / "JP_OSE_Data"), normalized(ROOT / "work")
    old_open, old_path_open, old_stat = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """市場資料又は実中間明細への接近を拒否する。

        引数: path(object)は対象。
        返り値: None。人工一時ディレクトリだけ圧縮を許可する。
        """
        name = normalized(path)
        inside = name.startswith(work + os.sep)
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("構造判別37合成_")
        if name == raw or name.startswith(raw + os.sep) or inside and (name.endswith(".npz") or not artificial and name.endswith((".jsonl.gz", ".trades.jsonl"))):
            raise AssertionError("合成から実原板/cache/明細へ触れない:" + str(path))

    def opened(path: object, *args: object, **kwargs: object) -> Any:
        """通常openへ市場遮断を適用する。

        引数: path(object)は対象、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
        """
        check(path)
        return old_open(path, *args, **kwargs)

    def path_opened(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.openへ市場遮断を適用する。

        引数: path(Path)は対象、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
        """
        check(path)
        return old_path_open(path, *args, **kwargs)

    def stated(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.statへ市場遮断を適用する。

        引数: path(Path)は対象、args/kwargs(object)は元引数。
        返り値: Anyは許可されたメタデータ。
        """
        check(path)
        return old_stat(path, *args, **kwargs)

    with patch.object(builtins, "open", opened), patch.object(Path, "open", path_opened), patch.object(Path, "stat", stated):
        yield


def load(path: Path, name: str) -> Any:
    """市場遮断下で定義だけを読み込む。

    引数: path(Path)はPython、name(str)はモジュール名。
    返り値: Anyは定義。CLIを起動しない。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
        return value


def sha(path: Path) -> str:
    """小型出典の現在SHAを返す。

    引数: path(Path)はコード又は条件。
    返り値: strはSHA256。実市場明細は対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


O = load(HERE/"運用.py", "構造判別37合成の主運用")
I = load(HERE/"入口.py", "構造判別37合成の主入口")
CONFIG = json.loads((ROOT/"study/00033_CCI突破と足内終値位置/条件.json").read_text(encoding="utf-8"))["運用"]


def raw(side: int = 1, close: float = 170., delta: float = 1., old: bool | None = None,
        index: int = 21, clock: float = 10., line: int = 10, **updates: object) -> dict:
    """旧29の原Pの最小公開形状を作る。

    引数: side(int)は元P、close/delta(float)は終値/ヒスト差、old(bool|None)は旧採否、
    index/clock/line(int/float/int)は出典、updates(object)は変更。
    返り値: dictは発動IDを持ち、イベントID/入口IDをまだ持たない原P。
    """
    adopted = side*delta > 0 if old is None else old
    return {"場": SESSION, "発動ID": f"人工P{index}_{side}", "index": index, "side": side,
        "方向": "買い" if side == 1 else "売り", "役割": "反転", "low": 90., "high": 230.,
        "close": close, "atr": 25., "bb_mean": 150., "要求時計秒": clock, "要求原板行": line,
        "前20足番号": list(range(index-20, index)), "旧BB下端": 50., "旧BB上端": 250.,
        "確認遅延秒": 0., "MACDヒスト変化": delta, "共通M準備": True, "時間条件可": True, "確認遅延条件可": True,
        "方向別準備": {"1": {"OBV_k参照": {"index": 4, "low": 100., "high": 105., "数量基準完全": True}},
            "-1": {"OBV_k参照": {"index": 7, "low": 195., "high": 200., "数量基準完全": True}}},
        "戦略判定": {"R0": {"採用": adopted, "同時競合": False, "理由": ["旧採用" if adopted else "旧不採用"]}},
        **updates}


def block(rows: list[dict]) -> dict:
    """原Pと旧R0信号を持つ非損益場材料を作る。

    引数: rows(list[dict])は人工の全原P。
    返り値: dictは旧29blockの必要属性。旧信号は比較用にだけ持つ。
    """
    signals = []
    for row in rows:
        if row["戦略判定"]["R0"]["採用"]:
            source = deepcopy(row)
            source.update(イベントID=row["発動ID"]+"_R0", 入口ID="3分_R0")
            signals.append(source)
    indices = sorted({i for row in rows for i in row["前20足番号"]})
    frames = [{"index": i, "low": 100. if i == 4 else 195. if i == 7 else 150.,
        "high": 105. if i == 4 else 200. if i == 7 else 150.} for i in indices]
    return {"input_quality": {"場": SESSION}, "quality": {"全Q発動記録": deepcopy(rows)},
        "signals": {"3分_R0": signals}, "frames": {3: frames}, "events": []}


def mirror(row: dict, center: float = 1000.) -> dict:
    """元Pと両端の出典を交換して上下反射する。

    引数: row(dict)は人工原P、center(float)は価格和。
    返り値: dictは時計/数量準備を保つ鏡像。
    """
    item = deepcopy(row)
    item.update(side=-row["side"], 方向="売り" if row["side"] == 1 else "買い",
        low=center-row["high"], high=center-row["low"], close=center-row["close"],
        bb_mean=center-row["bb_mean"], MACDヒスト変化=-row["MACDヒスト変化"])
    for destination, origin in (("1", "-1"), ("-1", "1")):
        previous = row["方向別準備"][origin]["OBV_k参照"]
        copied = deepcopy(previous)
        copied.update(low=center-previous["high"], high=center-previous["low"])
        item["方向別準備"][destination]["OBV_k参照"] = copied
    return item


def signal(entry: str = "B0", side: int = 1, role: str | None = None, event: str = "人工入口",
           clock: float = 10., line: int = 10) -> dict:
    """実方向と建玉の固定役割を持つ13列を作る。

    引数: entry(str)は四入口、side(int)は実方向、role(str|None)は役割、
    event(str)/clock(float)/line(int)は出典。
    返り値: dictは未来ラベルを持たない純信号。
    """
    return {"場": SESSION, "イベントID": event+"_"+entry, "入口ID": "3分_"+entry,
        "役割": role or ("順行" if entry == "T1" else "反転"), "side": side,
        "方向": "買い" if side == 1 else "売り", "要求時計秒": clock, "要求原板行": line,
        "確認遅延秒": 0., "low": 9990., "high": 10010., "atr": 25., "bb_mean": None}


def quote(now: float, line: int, side: int = 1, profit: float = 0.) -> SimpleNamespace:
    """新規10000からの名目利益を持つ正常返済BBOを作る。

    引数: now/line(float/int)はkey、side(int)は保有方向、profit(float)は利益pt。
    返り値: SimpleNamespaceは人工気配。
    """
    mark = 10000.+side*profit
    return SimpleNamespace(now=now, line=line, valid=True,
        bid=mark if side == 1 else mark-5., ask=mark+5. if side == 1 else mark)


class 価格構造検証(unittest.TestCase):
    """元P/実方向・全範囲内・外側と競合を人工で検査する。"""

    def test_生原Pにイベント入口IDがなくても純13列を作る(self) -> None:
        """getの既定値の先行評価や未変換ID参照を起こさない。

        引数: self(TestCase)は検査対象。
        返り値: None。未来の構造/ラベルは純信号へ入れない。
        """
        row = raw(); row.update(ラベル="未来", 将来損益=999999)
        value = I.pure_signal(row, "B0")
        self.assertEqual(set(value), set(I.SIGNAL_FIELDS))
        self.assertEqual(value["イベントID"], row["発動ID"]+"_B0")
        self.assertEqual(value["入口ID"], "3分_B0")
        self.assertEqual(value["bb_mean"], 150.)
        self.assertEqual(I.pure_signal({k:v for k,v in row.items() if k != "bb_mean"}, "B0")["bb_mean"], None)

    def test_R1は真の全範囲内で両端等号と反対端超えを待機にする(self) -> None:
        """k足自身の高安を旧20範囲と誤認しない。

        引数: self(TestCase)は検査対象。
        返り値: None。B0歴史採用は追加位置条件で変更しない。
        """
        for close, expected in ((90., False), (100., False), (101., True), (170., True), (199., True), (200., False), (220., False)):
            for side in (1, -1):
                row = raw(side, close, float(side))
                result = I.select(block([row]))
                self.assertEqual(len(result["signals"]["3分_B0"]), 1)
                self.assertEqual(bool(result["signals"]["3分_R1"]), expected)
                self.assertEqual(result["decisions"][0]["旧L"], 100.)
                self.assertEqual(result["decisions"][0]["旧H"], 200.)
                self.assertEqual(result["decisions"][0]["元境界K"], 100. if side == 1 else 200.)

    def test_T1は旧R0不採用の全原Pから逆実方向を作る(self) -> None:
        """突破側の勢いを元R0の補数ラベルへ読み替えない。

        引数: self(TestCase)は検査対象。
        返り値: None。旧PのOHLC/ATRと時計は保持する。
        """
        for original in (raw(1, 90., -1.), raw(-1, 220., 1.)):
            result = I.select(block([original]))
            self.assertFalse(result["signals"]["3分_B0"])
            self.assertFalse(result["signals"]["3分_R1"])
            current = result["signals"]["3分_T1"][0]
            self.assertEqual((current["side"], current["役割"]), (-original["side"], "順行"))
            self.assertEqual(current["要求時計秒"], original["要求時計秒"])
            self.assertEqual((current["low"], current["high"], current["atr"]), (original["low"], original["high"], original["atr"]))
            mixed = result["signals"]["3分_S1"][0]
            self.assertEqual((mixed["side"], mixed["役割"]), (current["side"], "順行"))

    def test_等号と勢い不一致と旧M不可をTへ昇格しない(self) -> None:
        """元Pの数量Mを実sideの反対端で取り直さない。

        引数: self(TestCase)は検査対象。
        返り値: None。旧準備不可と技術的不一致を待機に残す。
        """
        for close, delta in ((100., -1.), (200., -1.), (90., 0.), (90., 1.), (170., -1.)):
            self.assertFalse(I.select(block([raw(1, close, delta)]))["signals"]["3分_T1"])
        for key in ("共通M準備", "時間条件可", "確認遅延条件可"):
            row = raw(1, 90., -1., old=False); row[key] = False
            self.assertFalse(I.select(block([row]))["signals"]["3分_T1"])
        row = raw(1, 90., -1., old=False)
        row["方向別準備"]["-1"]["OBV_k参照"]["数量基準完全"] = False
        self.assertEqual(len(I.select(block([row]))["signals"]["3分_T1"]), 1)

    def test_片端帰還の同side二役割反例を全範囲判定で分ける(self) -> None:
        """旧BB50..250とC220を全範囲帰還と誤認しない。

        引数: self(TestCase)は検査対象。
        返り値: None。同じ一足のR/T価格領域は排他となる。
        """
        result = I.select(block([raw(1, 220., 1.), raw(-1, 220., 1.)]))
        self.assertEqual(len(result["signals"]["3分_B0"]), 1)
        self.assertFalse(result["signals"]["3分_R1"])
        self.assertEqual(len(result["signals"]["3分_T1"]), 1)
        self.assertEqual(len(result["signals"]["3分_S1"]), 1)
        self.assertEqual(result["signals"]["3分_S1"][0]["役割"], "順行")

    def test_全採否は鏡像と時点を保つ(self) -> None:
        """境界と勢いを反射して実sideだけ反転させる。

        引数: self(TestCase)は検査対象。
        返り値: None。役割/時計/元k対応は変えない。
        """
        for close, delta in ((90., -1.), (100., 1.), (170., 1.), (200., 1.), (220., 1.)):
            row = raw(1, close, delta)
            a, b = I.select(block([row])), I.select(block([mirror(row)]))
            da, db = a["decisions"][0], b["decisions"][0]
            self.assertEqual(da["構造区分"], db["構造区分"])
            for name in I.POLICIES:
                va, vb = da["戦略判定"][name], db["戦略判定"][name]
                self.assertEqual(va["採用"], vb["採用"])
                self.assertEqual(va["役割"], vb["役割"])
                self.assertEqual(va["実side"], None if vb["実side"] is None else -vb["実side"])

    def test_Sは技術和の後に同方向も反対方向も全競合を消費する(self) -> None:
        """単独R/TとS自身の競合を別々に保存する。

        引数: self(TestCase)は検査対象。
        返り値: None。先着一件や役割優先では選ばない。
        """
        for same_side in (True, False):
            r = raw(1, 170., 1., index=21)
            t = raw(-1 if same_side else 1, 220. if same_side else 90., 1. if same_side else -1., index=22)
            result = I.select(block([r, t]))
            self.assertEqual(len(result["signals"]["3分_R1"]), 1)
            self.assertEqual(len(result["signals"]["3分_T1"]), 1)
            self.assertFalse(result["signals"]["3分_S1"])
            self.assertTrue(all(d["戦略判定"]["S1"]["同時競合"] for d in result["decisions"]))
            self.assertEqual(len(result["signals"]["3分_B0"]), 1)

    def test_全判定snapshotは候補間で共有されず未来足で過去を変更しない(self) -> None:
        """同時計の集合選別をdeepcopyと公開keyで保つ。

        引数: self(TestCase)は検査対象。
        返り値: None。後続待機で元要求を変更しない。
        """
        first = raw()
        a = I.select(block([first]))
        b = I.select(block([first, raw(1, 90., -1., index=22, clock=20., line=20)]))
        self.assertEqual(a["decisions"][0], b["decisions"][0])
        a["signals"]["3分_S1"][0]["high"] = -999
        self.assertNotEqual(a["signals"]["3分_R1"][0]["high"], -999)

    def test_独立20足再走査と全判定純入口を合わせる(self) -> None:
        """主のk参照と別の元窓min/max計算を全属性比較する。

        引数: self(TestCase)は検査対象。
        返り値: None。旧準備と競合/役割を独立へ数値伝授しない。
        """
        other = load(HERE/"状態独立確認.py", "構造判別37合成の独立状態")
        for side in (1, -1):
            for close, delta in ((90., -1.), (100., 1.), (170., 1.), (200., -1.), (220., 1.)):
                source = block([raw(side, close, delta)])
                a, b = I.select(deepcopy(source)), other.select(deepcopy(source))
                self.assertEqual(a["decisions"], b["decisions"])
                self.assertEqual(a["signals"], b["signals"])


class 混合運用検証(unittest.TestCase):
    """固定33の五運用接続と建玉ごとの役割を検査する。"""

    def test_五運用の全台帳追尾を固定33へ直結し未来列を落とす(self) -> None:
        """wrapperが新しい退出やmetadataを足さないことを確認する。

        引数: self(TestCase)は検査対象。
        返り値: None。各買売の完結を全属性比較する。
        """
        for entry, exit_id in O.PAIRS:
            for side in (1, -1):
                source = signal(entry, side)
                source.update(将来ラベル="未来", 元価格side=-side, 旧範囲=[1, 2])
                clean = O.pure_signal(source)
                events = [quote(11., 11, side, -5.), quote(12., 12, side, 5.), quote(13., 13, side, 15.),
                    quote(14., 14, side, 0.), quote(15., 15, side, -5.)]
                args = (events, [source], [], SESSION, "3分_"+entry+"_"+exit_id, deepcopy(CONFIG), {"出口ID": exit_id}, O.ROLES[entry], BOUNDS)
                a, qa = O.replay(*args)
                b, qb = O.BASE.replay(events, [clean], [], *args[3:])
                self.assertEqual(qa, qb)
                for field in ("orders", "fills", "trades", "signals", "normal_log"):
                    self.assertEqual(getattr(a, field), getattr(b, field))
                self.assertEqual(len(a.trades), 1)
                self.assertEqual(a.trades[0]["入口役割"], clean["役割"])
                self.assertEqual(set(a.features[source["イベントID"]]), set(O.SIGNAL_FIELDS))

    def test_S1反転から順行の連続fillと保有中役割固定(self) -> None:
        """反対役割の後続抑止で既建玉の役割を変更しない。

        引数: self(TestCase)は検査対象。
        返り値: None。実R/Tを独立二建玉として同時保有しない。
        """
        for side in (1, -1):
            sources = [signal("S1", side, "反転", "最初R"),
                signal("S1", -side, "順行", "保有中T", 12.5, 125),
                signal("S1", -side, "順行", "後続T", 20., 200)]
            events = [quote(11., 110, side, -5.), quote(12., 120, side, 15.), quote(13., 130, side, 0.),
                quote(14., 140, side, -5.), quote(21., 210, -side, -5.), quote(22., 220, -side, 15.),
                quote(23., 230, -side, 0.), quote(24., 240, -side, -5.)]
            state, info = O.replay(events, sources, [], SESSION, "3分_S1_XF", deepcopy(CONFIG), {"出口ID": "XF"}, "切替", BOUNDS)
            self.assertEqual([r["入口役割"] for r in state.trades], ["反転", "順行"])
            self.assertEqual([r["方向"] for r in state.trades], ["買い" if side == 1 else "売り", "売り" if side == 1 else "買い"])
            self.assertEqual([r["取扱"] for r in state.signals], ["新規約定", "建玉中抑止", "新規約定"])
            first_logs = [r for r in state.normal_log if r["建玉"] and r["建玉"]["event_id"] == sources[0]["イベントID"]]
            self.assertTrue(all(r["建玉"]["entry_role"] == "反転" for r in first_logs))
            self.assertEqual(info["入口役割"], "取引ごと固定")

    def test_集合役割と実役割の偽装や未計画出口を拒否する(self) -> None:
        """S1の切替を個別信号の役割として渡さない。

        引数: self(TestCase)は検査対象。
        返り値: None。固定五運用だけを許可する。
        """
        for cid, role, exit_id in (("3分_T1_X0", "順行", "X0"), ("3分_T1_XF", "反転", "XF"), ("3分_S1_XF", "反転", "XF")):
            with self.assertRaises(ValueError):
                O.replay([], [], [], SESSION, cid, CONFIG, {"出口ID": exit_id}, role, BOUNDS)
        for entry, role in (("T1", "反転"), ("R1", "順行"), ("S1", "切替")):
            with self.assertRaises(ValueError):
                O.replay([], [signal(entry, role=role)], [], SESSION, "3分_"+entry+"_XF", CONFIG,
                    {"出口ID": "XF"}, O.ROLES[entry], BOUNDS)

    def test_B0X0の人工完結を旧29元config全属性へ合わせる(self) -> None:
        """旧33への接続が歴史X0の利益起動や会計を変えないことを確認する。

        引数: self(TestCase)は検査対象。
        返り値: None。識別子以外の数値/理由/ログ順序を除外しない。
        """
        driver = driver_module()
        for side in (1, -1):
            source = signal("B0", side)
            old_source = driver.rename(source, "_B0", "_R0")
            events = [quote(11., 11, side, -5.), quote(12., 12, side, 5.),
                quote(13., 13, side, 0.), quote(14., 14, side, -5.)]
            a, qa = O.replay(events, [source], [], SESSION, "3分_B0_X0", CONFIG, {"出口ID": "X0"}, "反転", BOUNDS)
            b, qb = driver.D.ENGINE.replay(events, [old_source], [], SESSION, "3分_R0_X0",
                driver.OLD_CONFIG["運用"], {"出口ID": "X0"}, "反転", BOUNDS)
            self.assertEqual(driver.rename(qa, "_B0", "_R0"), qb)
            for field in ("orders", "fills", "trades", "signals", "normal_log"):
                self.assertEqual(driver.rename(getattr(a, field), "_B0", "_R0"), getattr(b, field))


def driver_module() -> Any:
    """CLIを呼ばず主の定義だけを読み込む。

    引数: なし。
    返り値: Anyは市場入力を開かない主driver。
    """
    return load(HERE/"検証.py", "構造判別37合成の主driver")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """一時条件と同時点R/Tを持つ人工場を供給する。

    引数: driver(Any)は主、count(int)は人工場数。
    返り値: Iterator[Any]は一時study/work/旧case/純場材料。
    """
    WORK.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="構造判別37合成_", dir=ROOT/"work") as tmp:
        base = Path(tmp)
        study, work = base/"study", base/"work"
        study.mkdir(); work.mkdir()
        config = driver.expected_config()
        driver.W.write_json(study/"条件.json", config)
        for name in ("入力台帳.json", "入口参照.json", "対照参照.json"):
            driver.W.write_json(study/name, {"人工": True})
        (study/"計画.md").write_text("人工条件のみ\n", encoding="utf-8")
        driver.W.write_json(work/"診断予定.json", {"人工": True})
        entries, materials, cases = [], {}, []
        for index in range(count):
            session = str(date(2026, 9, 21)+timedelta(days=index//2))+('_Day' if index%2 == 0 else '_Night')
            rows = [raw(1, 170., 1., index=21), raw(1, 90., -1., index=22, clock=20., line=20),
                raw(-1, 220., -1., index=23, clock=30., line=30)]
            material = driver.rename(driver.rename(block(rows), SESSION, session), "人工", session+"_人工")
            originals = deepcopy(material["signals"]["3分_R0"])
            material = driver.I.select(material)
            material.update(events=[], frames={3: []}, duration=420., cutoff=10000., deadline=20000.)
            materials[session] = material
            cases.extend({**r, "ラベル": "人工未来", "最大順行pt": 987654.} for r in originals)
            entries.append({"session": session, "symbol": "NK225", "人工": True})
        ref = {"共有明細": [{"パス": (work/"人工旧"/"入口事例.jsonl.gz").relative_to(ROOT).as_posix()}]}
        control = {"共有明細": [{"パス": (work/"人工旧"/name).relative_to(ROOT).as_posix()}
            for name in ("全運用詳細.jsonl.gz", "追尾.jsonl.gz")]}

        def built(entry: dict, *args: object) -> dict:
            """市場組立だけを人工の同時点材料へ差し替える。

            引数: entry(dict)は人工場、args(object)は共通引数。
            返り値: dictは独立copy。指標やラベルを計算しない。
            """
            return deepcopy(materials[entry["session"]])

        yield SimpleNamespace(study=study, work=work, config=config, manifest={"entries": entries,
            "source_root": str(base/"人工市場")}, ref=ref, control=control, cases=cases, materials=materials, built=built)


class 主準備と固定検証(unittest.TestCase):
    """市場入力を差し替え、純準備・T新先着・固定の接続を検査する。"""

    def test_CLI人工66準備は気配経路も旧labelも損益も呼ばない(self) -> None:
        """四候補の構造/純信号だけを保存する。

        引数: self(TestCase)は検査対象。
        返り値: None。全原Pを採否へ分け、正式中間物は作らない。
        """
        driver = driver_module()

        class LabelDenied(dict):
            """旧caseの未来label参照を人工prepareで禁止する。"""

            def __getitem__(self, key: str) -> Any:
                """純入力属性だけを参照可能とする。

                引数: key(str)は対象キー。
                返り値: Anyは元値。11labelはAssertionError。
                """
                if key in driver.LABEL_FIELDS:
                    raise AssertionError("prepareはlabel参照禁止")
                return super().__getitem__(key)

        with artificial_driver(driver) as f, \
                patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", side_effect=lambda s, n: f.ref if n == "入口参照.json" else f.control), \
                patch.object(driver, "read_rows", return_value=[LabelDenied(row) for row in f.cases]), \
                patch.object(driver, "build_session", side_effect=f.built) as built, \
                patch.object(driver, "freeze", side_effect=AssertionError("prepareで固定不可")) as frozen, \
                patch.object(driver.W.OLD, "気配経路", side_effect=AssertionError("prepareで気配経路不可")) as prices, \
                patch.object(driver.ENGINE, "replay", side_effect=AssertionError("prepareで運用不可")) as replayed, \
                patch.object(driver.E, "entry_metrics", side_effect=AssertionError("prepareで先着集計不可")) as metric, \
                patch.object(driver.S, "operation_metrics", side_effect=AssertionError("prepareで損益不可")) as pnl, \
                patch.object(driver, "compressed", side_effect=AssertionError("prepareで正式gzip不可")), \
                patch.object(sys, "argv", ["人工37", "--study", str(f.study), "--work", str(f.work), "--prepare"]), redirect_stdout(io.StringIO()):
            driver.main()
            proof = driver.W.read_json(f.work/"準備点検.json")
            self.assertEqual(built.call_count, 66)
            self.assertEqual(proof["旧R0登録数"], 132)
            self.assertTrue(proof["旧29R0純登録同値"])
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            for record in proof["準備"]:
                self.assertEqual(len(record["純信号"]), 6)
                self.assertEqual(len(record["判定"]), 3)
                self.assertEqual({r["役割"] for r in record["純信号"] if r["入口ID"] == "3分_S1"}, {"反転", "順行"})
                self.assertTrue(all(set(r) == set(I.SIGNAL_FIELDS) for r in record["純信号"]))
            self.assertFalse((f.study/"結果.json").exists())
            self.assertFalse(any((f.work/n).exists() for n in driver.FILES))
            for mock in (frozen, prices, replayed, metric, pnl):
                mock.assert_not_called()

    def test_条件とpartialを市場処理前に拒否(self) -> None:
        """全範囲/方向式/競合と運用組合せのdriftを許可しない。

        引数: self(TestCase)は検査対象。
        返り値: None。既存partialは上書きしない。
        """
        driver = driver_module()
        for key, value in (("逆行pt", 124), ("戦略", ["B0", "S1"]), ("運用組合せ", [])):
            config = driver.expected_config(); config[key] = value
            with self.assertRaises(ValueError):
                driver.validate_config(config)
        config = driver.expected_config(); config["構造判別"]["R1"] = "片端だけへ変更"
        with self.assertRaises(ValueError):
            driver.validate_config(config)
        with artificial_driver(driver, 1) as f, \
                patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", side_effect=lambda s, n: f.ref if n == "入口参照.json" else f.control), \
                patch.object(driver, "freeze", side_effect=AssertionError("partialは固定前停止")) as frozen, \
                patch.object(driver, "build_session", side_effect=AssertionError("partialは市場前停止")) as built:
            path = f.work/driver.FILES[0]; path.write_bytes(b"artificial_partial")
            with self.assertRaises(ValueError):
                driver.run(f.study, f.work, False)
            self.assertEqual(path.read_bytes(), b"artificial_partial")
            frozen.assert_not_called(); built.assert_not_called()

    def test_人工正式五運用はT実方向で新先着を呼び役割別評価を保存する(self) -> None:
        """同時計反転は旧label同値、T/S順行は新方向を評価する。

        引数: self(TestCase)は検査対象。
        返り値: None。空活動の人工保存末尾と旧全台帳を照合する。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            session = f.manifest["entries"][0]["session"]
            phase = driver.E.phase_of(session, f.config)
            label = {k: None for k in driver.LABEL_FIELDS}; label.update(ラベル="未約定", 理由="人工未約定")
            f.cases = [{**r, **label} for r in f.cases]
            old_pure = [driver.rename(driver.I.pure_signal(row, "B0"), "_B0", "_R0") for row in f.cases]
            old_state, old_info = driver.D.ENGINE.replay([], old_pure, [], session, driver.CONTROL_ID,
                f.config["運用"], {"出口ID": "X0"}, "反転")
            old_info.update(期間=phase, 場時間分=f.materials[session]["duration"])
            old_detail = {"候補ID": driver.CONTROL_ID, "場": session, "品質": old_info,
                "約定": old_state.fills, "取引": old_state.trades, "注文": old_state.orders, "入口取扱": old_state.signals}
            old_logs = [{"期間": phase, **r} for r in old_state.normal_log]
            original, accepted, evaluated = driver.ENGINE.replay, [], []

            def read_rows(path: Path) -> list[dict]:
                """人工旧三系列を読み取りAPIへ渡す。

                引数: path(Path)は人工参照先。
                返り値: list[dict]は人工値。実明細は開かない。
                """
                return {"入口事例.jsonl.gz": f.cases, "全運用詳細.jsonl.gz": [old_detail], "追尾.jsonl.gz": old_logs}[path.name]

            def evaluate(now: float, cutoff: float, deadline: float, side: int, **kwargs: object) -> dict:
                """全案の新方向125/250評価という呼出境界だけを検査する。

                引数: now/cutoff/deadline(float)は時計、side(int)は実side、kwargs(object)は125/250。
                返り値: dictは人工未約定。実価格走査は行わない。
                """
                self.assertEqual(kwargs, {"adverse": 125, "favorable": 250})
                evaluated.append((now, side))
                return deepcopy(label)

            def replayed(*args: Any, **kwargs: Any) -> Any:
                """liveには純13列だけを渡し五候補を実人工運用へ接続する。

                引数: args/kwargs(Any)は人工運用。
                返り値: Anyは固定33の人工状態/品質。
                """
                self.assertTrue(all(set(r) == set(I.SIGNAL_FIELDS) for r in args[1]))
                accepted.append(args[4])
                return original(*args, **kwargs)

            def published(study: Path, *args: Any) -> None:
                """Viewer保存境界を人工5資源へ置き換える。

                引数: study(Path)は一時先、args(Any)は保存先等。
                返り値: None。市場ファイルを開かない。
                """
                driver.W.write_json(study/"一覧.resources.json", {"resources": [{"id": "00008_人工"+str(i)} for i in range(5)]})

            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver, "validate_reference", side_effect=lambda s, n: f.ref if n == "入口参照.json" else f.control), \
                    patch.object(driver, "read_rows", side_effect=read_rows), patch.object(driver, "build_session", side_effect=f.built), \
                    patch.object(driver, "freeze", return_value={}), patch.object(driver.W.OLD, "気配経路", return_value=SimpleNamespace(evaluate=evaluate)), \
                    patch.object(driver.ENGINE, "replay", side_effect=replayed), patch.object(driver.E, "publish_details", side_effect=published), redirect_stdout(io.StringIO()):
                result = driver.run(f.study, f.work, False)
            self.assertEqual(result["入口評価数"], 4)
            self.assertEqual(result["運用候補数"], 5)
            self.assertEqual(accepted, ["3分_"+p+"_"+x for p, x in driver.OPERATION_PAIRS])
            self.assertEqual(evaluated, [(10., 1), (30., -1), (20., -1)])
            saved = driver.W.read_json(f.study/"結果.json")
            self.assertEqual({(r["入口ID"], r["役割"]) for r in saved["役割別入口評価"]},
                {("3分_B0", "反転"), ("3分_R1", "反転"), ("3分_T1", "順行"), ("3分_S1", "反転"), ("3分_S1", "順行")})
            self.assertTrue(driver.W.read_json(f.study/"B0対照同値.json")["全件一致"])
            with gzip.open(f.work/"全運用詳細.jsonl.gz", "rt", encoding="utf-8") as stream:
                details = [json.loads(line) for line in stream]
            self.assertEqual(len(details), 5)
            self.assertEqual(driver.rename(details[0], "_B0", "_R0"), old_detail)
            with gzip.open(f.work/"入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
                cases = [json.loads(line) for line in stream]
            trends = [r for r in cases if r["役割"] == "順行"]
            self.assertEqual(len(trends), 2)
            self.assertTrue(all(r["元価格side"] == 1 and r["side"] == -1 and r["旧R0イベントID"] is None for r in trends))

    def test_旧29八証明六共有と対照二系列の欠落を拒否(self) -> None:
        """共有gzipを開かず宣言SHAで参照集合を検査する。

        引数: self(TestCase)は検査対象。
        返り値: None。正本参照は変更せず人工一時先だけを変える。
        """
        driver = driver_module()
        for name in ("入口参照.json", "対照参照.json"):
            pointer = driver.W.read_json(driver.STUDY/name)
            declared = {normalized(ROOT/row["パス"]): row["圧縮SHA256参考"] for row in pointer["共有明細"]}
            original = driver.O.sha

            def declared_sha(path: Path) -> str:
                """実gzipは宣言SHAへ置換し小型正本だけ実読取する。

                引数: path(Path)は参照先。
                返り値: strは宣言又は小型現SHA。
                """
                return declared.get(normalized(path)) or original(path)

            with artificial_driver(driver, 1) as f, patch.object(driver.O, "sha", side_effect=declared_sha):
                path = f.study/name
                driver.W.write_json(path, pointer)
                self.assertEqual(driver.validate_reference(f.study, name), pointer)
                for key in pointer["文書と証明"]:
                    changed = deepcopy(pointer); del changed["文書と証明"][key]
                    driver.W.write_json(path, changed)
                    with self.assertRaises(ValueError):
                        driver.validate_reference(f.study, name)
                for key, value in (("旧固定SHA256", "0"*64), ("大明細複製", True),
                        ("共有明細", pointer["共有明細"][:-1])):
                    changed = deepcopy(pointer); changed[key] = value
                    driver.W.write_json(path, changed)
                    with self.assertRaises(ValueError):
                        driver.validate_reference(f.study, name)

    def test_固定は主独立準備と最終人工の現版接続を必須にする(self) -> None:
        """独立失敗/古版/依存欠落を固定前に拒否する。

        引数: self(TestCase)は検査対象。
        返り値: None。固定は人工一時先だけへ作る。
        """
        driver = driver_module()
        if not (HERE/"追尾独立確認.py").exists():
            self.skipTest("独立CLI完成前の途中人工")
        with artificial_driver(driver, 1) as f, \
                patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", return_value={"文書と証明": {}, "共有明細": []}), \
                patch.object(driver, "read_rows", return_value=f.cases), \
                patch.object(driver, "shared_path", return_value=f.work/"人工旧入口事例.jsonl.gz"), \
                patch.object(driver, "build_session", side_effect=f.built), redirect_stdout(io.StringIO()):
            driver.run(f.study, f.work, True)
            dep = ROOT/"scripts/OBV反転/入口.py"
            proof = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
                "主準備SHA256": sha(f.work/"準備点検.json"), "主コードSHA256": driver.code_pins(),
                "条件SHA256": sha(f.study/"条件.json"), "入力台帳SHA256": sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256": sha(driver.MANIFEST_PATH), "入口参照SHA256": sha(f.study/"入口参照.json"),
                "対照参照SHA256": sha(f.study/"対照参照.json"), "コードSHA256": sha(HERE/"状態独立確認.py"),
                "追尾コードSHA256": sha(HERE/"追尾独立確認.py"),
                "依存コードSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
            synthetic = {"全件成功": True, "合成編集終了": False,
                "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in
                    [HERE/n for n in ("検証.py", "入口.py", "運用.py", "合成検証.py")]+[f.study/"条件.json"]},
                "独立数値補助SHA256": sha(HERE/"状態独立確認.py"), "独立追尾補助SHA256": sha(HERE/"追尾独立確認.py")}
            synthetic_file, independent = f.work/"人工最終合成.json", f.work/"独立準備点検.json"
            driver.W.write_json(synthetic_file, synthetic)
            real_read, real_sha = driver.W.read_json, driver.O.sha

            def redirected_read(path: Path) -> dict:
                """旧固定pinと最終人工だけを人工宣言へ向ける。

                引数: path(Path)は参照先。
                返り値: dictは人工宣言又は元小型正本。
                """
                if normalized(path) == normalized(driver.PREVIOUS/"固定.json"):
                    return {"ファイルSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
                if normalized(path) == normalized(WORK/"合成検証.json"):
                    return deepcopy(synthetic)
                return real_read(path)

            def redirected_sha(path: Path) -> str:
                """最終人工の固定対象だけを一時ファイルへ向ける。

                引数: path(Path)は参照先。
                返り値: strは元又は人工証拠SHA。
                """
                return sha(synthetic_file) if normalized(path) == normalized(WORK/"合成検証.json") else real_sha(path)

            with patch.object(driver.W, "read_json", side_effect=redirected_read), patch.object(driver.O, "sha", side_effect=redirected_sha):
                with self.assertRaises(FileNotFoundError):
                    driver.freeze(f.study, f.work)
                driver.W.write_json(independent, proof)
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                synthetic["合成編集終了"] = True
                for key in ("全件一致", "ラベル計算", "主準備SHA256", "主コードSHA256", "コードSHA256", "追尾コードSHA256", "対照参照SHA256", "依存コードSHA256"):
                    bad = deepcopy(proof); bad[key] = not proof[key] if isinstance(proof[key], bool) else {}
                    driver.W.write_json(independent, bad)
                    with self.assertRaises(ValueError):
                        driver.freeze(f.study, f.work)
                driver.W.write_json(independent, proof)
                correct = synthetic["独立追尾補助SHA256"]
                synthetic["独立追尾補助SHA256"] = "0"*64
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                synthetic["独立追尾補助SHA256"] = correct
                driver.W.write_json(synthetic_file, synthetic)
                fixed = driver.freeze(f.study, f.work)
                self.assertEqual(driver.freeze(f.study, f.work), fixed)
                self.assertEqual(fixed["独立準備SHA256"], sha(independent))
                (f.study/"計画.md").write_text("人工固定後の差\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                driver.W.write_json(f.study/"結果.json", {"人工": True})
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)


def main() -> None:
    """人工だけを実行し、編集途中又は最終の小型証明を保存する。

    引数: CLIの--final(bool)はroot許可・全担当編集終了後だけ指定する。
    返り値: None。市場準備/先着/PnLは起動しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    paths = [HERE/n for n in ("入口.py", "運用.py", "合成検証.py")]
    for path in (HERE/"検証.py", ROOT/"study/00037_高安帰還と外側継続の判別/条件.json"):
        if path.exists():
            paths.append(path)
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    helpers = [HERE/n for n in ("状態独立確認.py", "追尾独立確認.py")]
    helper_shas = [sha(p) if p.exists() else None for p in helpers]
    if args.final and (len(paths) != 5 or None in helper_shas):
        raise ValueError("主条件と独立二コードの完成前です")
    with deny_market():
        suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    unchanged = pins == {p.relative_to(ROOT).as_posix(): sha(p) for p in paths} and helper_shas == [sha(p) if p.exists() else None for p in helpers]
    success = result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
        "市場入力読取": False, "市場先着損益計算": False, "実行中コード条件不変": unchanged,
        "ファイルSHA256": pins, "独立数値補助SHA256": helper_shas[0], "独立追尾補助SHA256": helper_shas[1],
        "範囲": "人工の旧P全範囲内/外側/等号、元k/両端出典、鏡像、旧基準保持/T逆実方向、S技術和の候補別競合・同方向全見送り、独立元20足再走査の全判定/純入口、純13列、固定33五運用全台帳/追尾属性、旧29元config対照、混合R→T連続fill/保有中役割固定。人工66prepareは気配経路/旧label/新先着/運用/PnL禁止。人工五運用正式保存末尾/T実side新先着呼出/役割別5群保存、旧29八証明/共有六系列と対照二系列/partial・条件drift、独立準備と最終人工の現版必須join・固定後変更拒否。実市場のstat/openは禁止。",
        "省略": [{"検査": str(case), "理由": reason} for case, reason in result.skipped],
        "失敗": [{"検査": str(case), "内容": reason} for case, reason in result.failures],
        "エラー": [{"検査": str(case), "内容": reason} for case, reason in result.errors]}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k: proof[k] for k in ("全件成功", "検証件数", "合成編集終了", "実行中コード条件不変")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
