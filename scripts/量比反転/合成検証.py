"""量比現前の厳密符号・準備差と固定X0/XF継承を人工入力だけで検査する。"""

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
WORK = ROOT / "work/量比反転"
SESSION = "人工量比反転場"
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
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("量比反転36合成_")
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


O = load(HERE/"運用.py", "量比反転36合成の運用")
I = load(HERE/"入口.py", "量比反転36合成の入口")
CONFIG = json.loads((ROOT/"study/00029_BB内復帰とOBV非追随/条件.json").read_text(encoding="utf-8"))["運用"]


def frame(index: int, close: float = 100., q: float = 1., **extra: object) -> dict:
    """量比窓へ当時渡せる人工公開足を作る。

    引数: index(int)は足番号、close/q(float)は終値/完全数量、extra(object)は変更点。
    返り値: dictは旧29数値足の必要属性だけを持つ人工足。
    """
    return {"場": SESSION, "minutes": 3, "index": index, "publish": True, "missing": 0,
        "価格数値入力可": True, "close": close, "confirm": 180.*(index+1), "confirm_line": 100+index,
        "数量参照": {"観測差分量": q, "数量基準完全": True}, **extra}


def signal(policy: str = "V0", side: int = 1, event: str = "人工") -> dict:
    """新規10000基準の反転純入口を作る。

    引数: policy(str)は三入口、side(int)は買売、event(str)は接尾辞前のID。
    返り値: dictは未来ラベルを持たない13列。
    """
    return {"場": SESSION, "イベントID": event+"_"+policy, "入口ID": "3分_"+policy, "役割": "反転",
        "side": side, "方向": "買い" if side == 1 else "売り", "要求時計秒": 10., "要求原板行": 10,
        "確認遅延秒": 0., "low": 9990., "high": 10010., "atr": 25., "bb_mean": None}


def quote(now: float, line: int, side: int = 1, profit: float = 0.) -> SimpleNamespace:
    """新規10000からの名目利益を持つ正常返済BBOを作る。

    引数: now/line(float/int)はkey、side(int)は方向、profit(float)は名目利益pt。
    返り値: SimpleNamespaceは正常人工気配。
    """
    mark = 10000.+side*profit
    return SimpleNamespace(now=now, line=line, valid=True,
        bid=mark if side == 1 else mark-5., ask=mark+5. if side == 1 else mark)


def sample_block() -> dict:
    """量比準備の前後と、旧不採用も残る人工場を作る。

    引数: なし。
    返り値: dictは旧29の非損益block必要属性。価格/先着の計算はしない。
    """
    rows = [frame(i, 500.-i) for i in range(21)]+[frame(21, 481.)]
    signals, records = [], []
    for index, adopted, side in ((20, True, 1), (21, True, 1), (21, False, -1)):
        event = f"人工{index}_{side}"
        records.append({"発動ID": event, "index": index, "side": side,
            "場": SESSION, "low": 9990., "high": 10010., "close": 10000.,
            "前20足番号": list(range(index-20, index)), "旧BB下端": 9900., "旧BB上端": 10100.,
            "共通M準備": adopted, "時間条件可": True, "確認遅延条件可": True,
            "要求時計秒": rows[index]["confirm"], "要求原板行": rows[index]["confirm_line"],
            "戦略判定": {"R0": {"採用": adopted, "理由": ["旧採用" if adopted else "旧不採用"]}}})
        if adopted:
            source = signal("R0", side, event)
            source.update(発動ID=event, 要求時計秒=rows[index]["confirm"], 要求原板行=rows[index]["confirm_line"],
                先着={"未来": 999}, 損益=123456)
            signals.append(source)
    return {"input_quality": {"場": SESSION}, "frames": {3: rows}, "signals": {"3分_R0": signals},
        "quality": {"全Q発動記録": records}}


class 量比数値検証(unittest.TestCase):
    """期間・同値・欠測・反射を価格入力なしの人工値で検査する。"""

    def test_最速22終値21数量で最古数量は不要(self) -> None:
        """現20変化は21終値、現前は22終値で初めて有効になる。

        引数: self(TestCase)は検査対象。
        返り値: None。最古終値の数量不完全を追加gateにしない。
        """
        rows = [frame(i, 100.+i) for i in range(22)]
        rows[0]["数量参照"] = None
        panels = I.volume_panels(rows, SESSION)
        self.assertEqual(panels[19]["B現"], None)
        self.assertEqual(panels[20]["B現"], 1.)
        self.assertFalse(panels[20]["現前B準備"])
        self.assertTrue(panels[21]["現前B準備"])
        self.assertEqual((panels[21]["B差分子"], panels[21]["B差分母"]), (0, 1))
        self.assertEqual(panels[21]["現窓足番号"], list(range(2, 22)))
        self.assertEqual(panels[21]["前窓足番号"], list(range(1, 21)))

    def test_UDF同値数量は中立分母で鏡像符号だけ反転(self) -> None:
        """同値半配分と中心化VR2の式を明示値へ合わせる。

        引数: self(TestCase)は検査対象。
        返り値: None。VR1の逆数を補数として扱わない。
        """
        values = [(0, 1, 3.), (1, -1, 1.), (2, 0, 4.)]+[(i, 0, 0.) for i in range(3, 20)]
        b, amounts = I.ratio(values)
        other, _ = I.ratio([(i, -side, q) for i, side, q in values])
        self.assertEqual(b, Fraction(1, 4))
        self.assertEqual(other, -b)
        self.assertEqual(amounts, {"上昇量": 3., "下落量": 1., "同値量": 4., "合計量": 8.})
        self.assertEqual(50*(1+b), Fraction(125, 2))

    def test_量0は有効で全量0だけ比を無効にする(self) -> None:
        """完全0を欠測と混ぜず、正数量同値窓ではB0を準備済みにする。

        引数: self(TestCase)は検査対象。
        返り値: None。0と未定義を区別する。
        """
        flat = I.volume_panels([frame(i, q=10.) for i in range(22)], SESSION)[-1]
        zero = I.volume_panels([frame(i, q=0.) for i in range(22)], SESSION)[-1]
        self.assertTrue(flat["現前B準備"])
        self.assertEqual((flat["B現"], flat["B前"], flat["B差分子"]), (0., 0., 0))
        self.assertTrue(zero["数量入力可"])
        self.assertFalse(zero["現前B準備"])
        self.assertIsNone(zero["B差分子"])

    def test_現在上昇でも古い大数量脱落で量比悪化し鏡像も一致(self) -> None:
        """数量改善は現在終値方向から自動成立しないことを示す。

        引数: self(TestCase)は検査対象。
        返り値: None。架空反例で市場の有効性は主張しない。
        """
        closes = [500., 501.]+[501.-i for i in range(1, 20)]+[483.]
        rows = [frame(i, close, 100. if i == 1 else 1.) for i, close in enumerate(closes)]
        a = I.volume_panels(rows, SESSION)[-1]
        mirror = deepcopy(rows)
        for row in mirror:
            row["close"] = 2000.-row["close"]
        b = I.volume_panels(mirror, SESSION)[-1]
        self.assertEqual(Fraction(a["B前分子"], a["B前分母"]), Fraction(81, 119))
        self.assertEqual(Fraction(a["B現分子"], a["B現分母"]), Fraction(-9, 10))
        self.assertLess(a["B差分子"], 0)
        self.assertEqual(Fraction(a["B差分子"], a["B差分母"]), -Fraction(b["B差分子"], b["B差分母"]))
        self.assertEqual(a["現方向別量"]["上昇量"], b["現方向別量"]["下落量"])

    def test_数量不完全は量窓を切り有効closeを次比較元へ残す(self) -> None:
        """欠測の次の完全足から変化を数え直せるようにする。

        引数: self(TestCase)は検査対象。
        返り値: None。22足のq完全を余分に要求しない。
        """
        for bad in (None, {"観測差分量": 1., "数量基準完全": False}, {"観測差分量": -1., "数量基準完全": True}):
            rows = [frame(i, 100.+i) for i in range(23)]
            rows[1]["数量参照"] = bad
            panels = I.volume_panels(rows, SESSION)
            self.assertEqual(panels[2]["比較元足番号"], 1)
            self.assertTrue(panels[2]["VR入力可"])
            self.assertFalse(panels[21]["現前B準備"])
            self.assertTrue(panels[22]["現前B準備"])

    def test_NP欠枠不正と番号飛越は価格比較元も切る(self) -> None:
        """数量不完全だけの場合との解除範囲差を確認する。

        引数: self(TestCase)は検査対象。
        返り値: None。missing当足を新種へ入れない。
        """
        for change in ({"publish": False}, {"missing": 1}, {"価格数値入力可": False}):
            rows = [frame(i, 100.+i) for i in range(24)]
            rows[1].update(change)
            panels = I.volume_panels(rows, SESSION)
            self.assertFalse(panels[1]["VR入力可"])
            self.assertIsNone(panels[2]["比較元足番号"])
            self.assertFalse(panels[22]["現前B準備"])
            self.assertTrue(panels[23]["現前B準備"])
        gap = I.volume_panels([frame(0), frame(2, 101.), frame(3, 102.)], SESSION)
        self.assertFalse(gap[1]["VR入力可"])
        self.assertEqual(gap[2]["比較元足番号"], 2)
        self.assertTrue(gap[2]["VR入力可"])

    def test_Fraction元数量と未来prefixを厳密保持(self) -> None:
        """元floatの正確値を使い、将来の足で過去を改訂しない。

        引数: self(TestCase)は検査対象。
        返り値: None。表示floatの差から採否を作らない。
        """
        values = [(i, 1 if i%2 else -1, .1 if i%2 else .2) for i in range(20)]
        b, _ = I.ratio(values)
        self.assertEqual(b, (10*Fraction(.1)-10*Fraction(.2))/(10*Fraction(.1)+10*Fraction(.2)))
        rows = [frame(i, 100.+i%3, .1+i/10) for i in range(27)]
        self.assertEqual(I.volume_panels(rows[:22], SESSION), I.volume_panels(rows, SESSION)[:22])

    def test_MFIのTP重みは反射補数にならない(self) -> None:
        """標準MFIを採否から外す事前反例を有理数で検算する。

        引数: self(TestCase)は検査対象。
        返り値: None。MFIを別の量比へ変えて同名で使わない。
        """
        original, mirrored = Fraction(100*120, 230), Fraction(100*190, 370)
        self.assertEqual(original, Fraction(1200, 23))
        self.assertEqual(mirrored, Fraction(1900, 37))
        self.assertNotEqual(mirrored, 100-original)
        self.assertTrue(original > 50 and mirrored > 50)


class 入口と運用検証(unittest.TestCase):
    """同時点三入口と固定四運用の純経路を検査する。"""

    def test_V0完全保持とV1準備とV2値を別集合にする(self) -> None:
        """旧不採用も診断に残し、原時計を後へ取り直さない。

        引数: self(TestCase)は検査対象。
        返り値: None。旧量準備の条件も変えない。
        """
        source = sample_block()
        old = deepcopy(source["signals"]["3分_R0"])
        result = I.select(source)
        self.assertEqual([len(result["signals"]["3分_"+p]) for p in I.POLICIES], [2, 1, 1])
        self.assertEqual(len(result["decisions"]), 3)
        for original, current in zip(old, result["signals"]["3分_V0"]):
            back = deepcopy(current)
            back.update(入口ID="3分_R0", イベントID=back["イベントID"][:-3]+"_R0")
            self.assertEqual(back, {k: original[k] for k in I.SIGNAL_FIELDS})
        a = result["signals"]["3分_V1"][0]
        b = result["signals"]["3分_V2"][0]
        self.assertEqual((a["要求時計秒"], a["要求原板行"]), (b["要求時計秒"], b["要求原板行"]))
        b["high"] = -999
        self.assertNotEqual(a["high"], b["high"])
        self.assertEqual(set(a), set(I.SIGNAL_FIELDS))

    def test_表示Bの差が0でも分数差の正符号を採否に使う(self) -> None:
        """巨大量に小量を足す厳密境界をfloatの引算へ戻さない。

        引数: self(TestCase)は検査対象。
        返り値: None。任意epsilonを追加せず鏡像も同採否とする。
        """
        rows = [frame(0, 1000.), frame(1, 999.)]+[frame(i, 998.+i, float(2**60) if i == 2 else 1.) for i in range(2, 22)]
        for side in (1, -1):
            source = sample_block()
            source["frames"][3] = deepcopy(rows)
            if side == -1:
                for row in source["frames"][3]:
                    row["close"] = 3000.-row["close"]
            record = deepcopy(source["quality"]["全Q発動記録"][1])
            record["side"] = side
            source["quality"]["全Q発動記録"] = [record]
            source["signals"]["3分_R0"] = [signal("R0", side, record["発動ID"])]
            source["signals"]["3分_R0"][0]["発動ID"] = record["発動ID"]
            result = I.select(source)
            panel = result["volume_panels"][-1]
            self.assertEqual(panel["B現"]-panel["B前"], 0.)
            self.assertGreater(side*panel["B差分子"], 0)
            self.assertEqual(len(result["signals"]["3分_V2"]), 1)

    def test_独立窓再走査と全panel全採否全純入口を比較(self) -> None:
        """主のrolling実装と別の窓再走査を人工全属性で合わせる。

        引数: self(TestCase)は検査対象。
        返り値: None。独立側へ主の期待数値を渡さない。
        """
        other = load(HERE/"状態独立確認.py", "量比反転36合成の独立状態")
        rows = [frame(i, 100.+(i%7)-i/10, .1+i/10) for i in range(60)]
        rows[0]["数量参照"] = None
        rows[24]["数量参照"]["数量基準完全"] = False
        rows[26]["missing"] = 1
        rows[28]["publish"] = False
        rows[30]["価格数値入力可"] = False
        rows[32]["数量参照"]["観測差分量"] = 0.
        self.assertEqual(I.volume_panels(rows, SESSION), other.volume_panels(rows, SESSION))
        a, b = I.select(sample_block()), other.select(sample_block())
        for name in ("volume_panels", "decisions", "signals"):
            self.assertEqual(a[name], b[name])

    def test_固定運用直呼出し全属性と将来列非混入(self) -> None:
        """四運用の出力を同一入力の固定33運用へ全属性で照合する。

        引数: self(TestCase)は検査対象。
        返り値: None。wrapperから新しい追尾や約定を足さない。
        """
        for entry, exit_id in O.PAIRS:
            for side in (1, -1):
                source = signal(entry, side)
                source.update(先着={"未来250": 999}, 将来損益=-12345, B差=999)
                clean = O.pure_signal(source)
                events = [quote(11., 11, side, -5.), quote(12., 12, side, 5.), quote(13., 13, side, 15.),
                    quote(14., 14, side, 0.), quote(15., 15, side, -5.)]
                args = (events, [source], [], SESSION, "3分_"+entry+"_"+exit_id, deepcopy(CONFIG), {"出口ID": exit_id}, "反転", BOUNDS)
                a, qa = O.replay(*args)
                b, qb = O.BASE.replay(events, [clean], [], *args[3:])
                self.assertEqual(qa, qb)
                for field in ("orders", "fills", "trades", "signals", "normal_log"):
                    self.assertEqual(getattr(a, field), getattr(b, field))
                self.assertEqual(len(a.trades), 1)
                self.assertEqual(set(a.features[source["イベントID"]]), set(O.SIGNAL_FIELDS))
                self.assertEqual(a.trades[0]["入口役割"], "反転")

    def test_費用起動と旧A5を同じ条件に書き換えない(self) -> None:
        """5ptの旧X0起動と15ptのXF起動を区別する。

        引数: self(TestCase)は検査対象。
        返り値: None。名目床と費用後黒字を同一視しない。
        """
        for side in (1, -1):
            events = [quote(11., 11, side, -5.), quote(12., 12, side, 5.), quote(13., 13, side, 15.),
                quote(14., 14, side, 0.), quote(15., 15, side, -5.)]
            result = {}
            for exit_id in ("X0", "XF"):
                state, _ = O.replay(events, [signal("V0", side)], [], SESSION, "3分_V0_"+exit_id,
                    deepcopy(CONFIG), {"出口ID": exit_id}, "反転", BOUNDS)
                result[exit_id] = state.trades[0]
            self.assertEqual(result["X0"]["追尾起動時計秒"], 12.)
            self.assertEqual(result["XF"]["追尾起動時計秒"], 13.)
            self.assertEqual(result["XF"]["起動判定出典"]["控除後含み益円"], 28.)
            self.assertEqual(result["XF"]["最終追尾価格"], 10000.)

    def test_旧29の元configとX0全属性を人工完結で保つ(self) -> None:
        """新configの費用起動用項目が旧X0結果を変えないことを確認する。

        引数: self(TestCase)は検査対象。
        返り値: None。正規化は_V0/_R0のIDだけで数値や理由を落とさない。
        """
        driver = driver_module()
        current_config = driver.expected_config()["運用"]
        for side in (1, -1):
            source = signal("V0", side)
            old_source = driver.rename(source, "_V0", "_R0")
            events = [quote(11., 11, side, -5.), quote(12., 12, side, 5.),
                quote(13., 13, side, 0.), quote(14., 14, side, -5.)]
            a, qa = O.replay(events, [source], [], SESSION, "3分_V0_X0", current_config,
                {"出口ID": "X0"}, "反転", BOUNDS)
            b, qb = driver.D.ENGINE.replay(events, [old_source], [], SESSION, "3分_R0_X0", CONFIG,
                {"出口ID": "X0"}, "反転", BOUNDS)
            self.assertEqual(driver.rename(qa, "_V0", "_R0"), qb)
            for field in ("orders", "fills", "trades", "signals", "normal_log"):
                self.assertEqual(driver.rename(getattr(a, field), "_V0", "_R0"), getattr(b, field))

    def test_四組合せ以外と役割偽装を拒否し入力は変更しない(self) -> None:
        """未計画運用と順行役割の混入を受付前に拒否する。

        引数: self(TestCase)は検査対象。
        返り値: None。旧globalsや渡されたconfigも変更しない。
        """
        before = deepcopy(CONFIG)
        for method, policy, role in (("3分_V1_X0", {"出口ID": "X0"}, "反転"),
                ("3分_V0_XF", {"出口ID": "X0"}, "反転"), ("3分_V0_XF", {"出口ID": "XF"}, "順行")):
            with self.assertRaises(ValueError):
                O.replay([], [], [], SESSION, method, CONFIG, policy, role, BOUNDS)
        bad = signal(); bad["役割"] = "順行"
        with self.assertRaises(ValueError):
            O.replay([], [bad], [], SESSION, "3分_V0_XF", CONFIG, {"出口ID": "XF"}, "反転", BOUNDS)
        self.assertEqual(CONFIG, before)


def driver_module() -> Any:
    """主CLIを起動せず定義だけを読み込む。

    引数: なし。
    返り値: Anyは主driver。実manifestやcacheは開かない。
    """
    return load(HERE/"検証.py", "量比反転36合成の主driver")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """一時条件と人工66場を主CLIの入口へ供給する。

    引数: driver(Any)は主、count(int)は人工場数。
    返り値: Iterator[Any]は一時study/work/共有case/場材料。旧case未来列は人工値だけ。
    """
    WORK.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="量比反転36合成_", dir=ROOT/"work") as tmp:
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
            material = driver.rename(driver.rename(sample_block(), SESSION, session), "人工", session+"_人工")
            originals = deepcopy(material["signals"]["3分_R0"])
            material = driver.I.select(material)
            material.update(events=[], duration=420., cutoff=10000., deadline=20000.)
            materials[session] = material
            for row in originals:
                cases.append({**row, "ラベル": "人工未来ラベル", "最大順行pt": 987654.})
            entries.append({"session": session, "symbol": "NK225", "人工": True})
        ref = {"共有明細": [{"パス": (work/"人工旧"/"入口事例.jsonl.gz").relative_to(ROOT).as_posix()}]}
        control = {"共有明細": [{"パス": (work/"人工旧"/name).relative_to(ROOT).as_posix()}
            for name in ("全運用詳細.jsonl.gz", "追尾.jsonl.gz")]}

        def built(entry: dict, *args: object) -> dict:
            """主の市場組立だけを人工場材料へ置き換える。

            引数: entry(dict)は人工場、args(object)は未使用の共通引数。
            返り値: dictは未来ラベルを持たない独立copy。
            """
            return deepcopy(materials[entry["session"]])

        yield SimpleNamespace(study=study, work=work, config=config, manifest={"entries": entries,
            "source_root": str(base/"人工市場")}, ref=ref, control=control, cases=cases, materials=materials, built=built)


class 主準備と固定検証(unittest.TestCase):
    """市場処理を差し替え、準備と正式guardの責務を検査する。"""

    def test_CLI人工66準備は旧ラベルも新運用も集計も呼ばない(self) -> None:
        """旧共有caseから純13列だけを使い量比/採否証拠を作る。

        引数: self(TestCase)は検査対象。
        返り値: None。仮先着/PnLや正式gzipを生成しない。
        """
        driver = driver_module()

        class LabelDenied(dict):
            """label属性の参照を人工prepareで明示的に拒否する。"""

            def __getitem__(self, key: str) -> Any:
                """未来ラベル以外の辞書値だけを返す。

                引数: key(str)はキー。
                返り値: Anyは元値。正式11label参照はAssertionError。
                """
                if key in driver.LABEL_FIELDS:
                    raise AssertionError("prepareで旧labelを参照しない")
                return super().__getitem__(key)

        with artificial_driver(driver) as f, \
                patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", side_effect=lambda s, n: f.ref if n == "入口参照.json" else f.control), \
                patch.object(driver, "read_rows", return_value=[LabelDenied(row) for row in f.cases]), \
                patch.object(driver, "build_session", side_effect=f.built) as built, \
                patch.object(driver, "freeze", side_effect=AssertionError("prepareは固定不可")) as frozen, \
                patch.object(driver.ENGINE, "replay", side_effect=AssertionError("prepareは運用不可")) as replayed, \
                patch.object(driver.E, "entry_metrics", side_effect=AssertionError("prepareは先着集計不可")) as metric, \
                patch.object(driver.S, "operation_metrics", side_effect=AssertionError("prepareは損益集計不可")) as pnl, \
                patch.object(driver, "compressed", side_effect=AssertionError("prepareは正式gzip不可")), \
                patch.object(sys, "argv", ["人工36", "--study", str(f.study), "--work", str(f.work), "--prepare"]), redirect_stdout(io.StringIO()):
            driver.main()
            proof = driver.W.read_json(f.work/"準備点検.json")
            self.assertEqual(built.call_count, 66)
            self.assertEqual(proof["旧R0登録数"], 132)
            self.assertTrue(proof["旧29R0純登録同値"])
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertEqual(len(proof["準備"]), 66)
            for row in proof["準備"]:
                self.assertEqual(len(row["純信号"]), 4)
                self.assertEqual(len(row["採否"]), 3)
                for source in row["純信号"]:
                    self.assertEqual(set(source), set(I.SIGNAL_FIELDS))
                self.assertNotIn("全指標", row)
            self.assertFalse((f.study/"結果.json").exists())
            self.assertFalse(any((f.work/n).exists() for n in driver.FILES))
            for mock in (frozen, replayed, metric, pnl):
                mock.assert_not_called()

    def test_条件とpartialを市場前に拒否(self) -> None:
        """期間/比較式/組合せの変更とpartial再実行を止める。

        引数: self(TestCase)は検査対象。
        返り値: None。保存partialを上書きしない。
        """
        driver = driver_module()
        for key, value in (("VR期間", 25), ("戦略", ["V0", "V2"]), ("運用組合せ", [])):
            config = driver.expected_config(); config[key] = value
            with self.assertRaises(ValueError):
                driver.validate_config(config)
        config = driver.expected_config(); config["量比方向"]["V2"] = "量優勢も追加"
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

    def test_人工無活動四運用の正式末尾と旧29全台帳対照(self) -> None:
        """人工一場を四運用の集計/保存末尾へ通す。

        引数: self(TestCase)は検査対象。
        返り値: None。旧市場結果は開かず人工旧台帳を全属性比較する。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            session = f.manifest["entries"][0]["session"]
            phase = driver.E.phase_of(session, f.config)
            f.cases = [{**r, **{k: None for k in driver.LABEL_FIELDS}, "ラベル": "未約定", "理由": "人工未約定"} for r in f.cases]
            old_pure = [driver.rename(driver.I.pure_signal(row), "_V0", "_R0") for row in f.cases]
            old_state, old_info = driver.D.ENGINE.replay([], old_pure, f.materials[session]["frames"][3], session,
                driver.CONTROL_ID, f.config["運用"], {"出口ID": "X0"}, "反転")
            old_info.update(期間=phase, 場時間分=f.materials[session]["duration"])
            old_detail = {"候補ID": driver.CONTROL_ID, "場": session, "品質": old_info,
                "約定": old_state.fills, "取引": old_state.trades, "注文": old_state.orders, "入口取扱": old_state.signals}
            old_logs = [{"期間": phase, **row} for row in old_state.normal_log]
            original, accepted = driver.ENGINE.replay, []

            def read_rows(path: Path) -> list[dict]:
                """人工旧入口/台帳/追尾を保存読取APIへ渡す。

                引数: path(Path)は人工参照。
                返り値: list[dict]は人工値。実gzipは開かない。
                """
                return {"入口事例.jsonl.gz": f.cases, "全運用詳細.jsonl.gz": [old_detail], "追尾.jsonl.gz": old_logs}[path.name]

            def replayed(*args: Any, **kwargs: Any) -> Any:
                """純13列の四運用だけを実人工運用へ通す。

                引数: args/kwargs(Any)は人工運用引数。
                返り値: Anyは固定運用の人工状態/品質。
                """
                for row in args[1]:
                    self.assertEqual(set(row), set(I.SIGNAL_FIELDS))
                accepted.append(args[4])
                return original(*args, **kwargs)

            def published(study: Path, *args: Any) -> None:
                """Viewer整形境界を人工4資源宣言へ置き換える。

                引数: study(Path)は一時先、args(Any)は保存明細等。
                返り値: None。市場価格ファイルを開かない。
                """
                driver.W.write_json(study/"一覧.resources.json", {"resources": [{"id": "00008_人工"+str(i)} for i in range(4)]})

            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver, "validate_reference", side_effect=lambda s, n: f.ref if n == "入口参照.json" else f.control), \
                    patch.object(driver, "read_rows", side_effect=read_rows), \
                    patch.object(driver, "build_session", side_effect=f.built), \
                    patch.object(driver, "freeze", return_value={}), \
                    patch.object(driver.ENGINE, "replay", side_effect=replayed), \
                    patch.object(driver.E, "publish_details", side_effect=published), redirect_stdout(io.StringIO()):
                result = driver.run(f.study, f.work, False)
            self.assertEqual(result["入口評価数"], 3)
            self.assertEqual(result["運用候補数"], 4)
            self.assertEqual(accepted, ["3分_"+p+"_"+x for p, x in driver.OPERATION_PAIRS])
            self.assertTrue(driver.W.read_json(f.study/"V0対照同値.json")["全件一致"])
            with gzip.open(f.work/"全運用詳細.jsonl.gz", "rt", encoding="utf-8") as stream:
                details = [json.loads(line) for line in stream]
            self.assertEqual(len(details), 4)
            self.assertEqual(driver.rename(details[0], "_V0", "_R0"), old_detail)
            self.assertTrue(all(not row["取引"] for row in details))
            self.assertTrue(all(n.startswith("00036_") for n in [r["id"] for r in driver.W.read_json(f.study/"一覧.resources.json")["resources"]]))

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
    """人工だけを検査し、現在出典を小型証明へ保存する。

    引数: CLIの--final(bool)は担当編集終了後だけ指定する。
    返り値: None。市場準備/先着/損益を起動しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true", help="全担当編集終了後の最終出典で保存")
    args = parser.parse_args()
    driver = driver_module()
    paths = [HERE/n for n in ("検証.py", "入口.py", "運用.py", "合成検証.py")]+[driver.STUDY/"条件.json"]
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    helpers = [HERE/n for n in ("状態独立確認.py", "追尾独立確認.py")]
    helper_shas = [sha(p) if p.exists() else None for p in helpers]
    if args.final and None in helper_shas:
        raise ValueError("独立二コードの完成前に最終証明は作れません")
    with deny_market():
        suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    print(stream.getvalue())
    unchanged = pins == {p.relative_to(ROOT).as_posix(): sha(p) for p in paths} and helper_shas == [sha(p) if p.exists() else None for p in helpers]
    success = result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
        "市場入力読取": False, "市場先着損益計算": False,
        "実行中コード条件不変": unchanged, "ファイルSHA256": pins,
        "独立数値補助SHA256": helper_shas[0], "独立追尾補助SHA256": helper_shas[1],
        "範囲": "人工量比U/D/F・22終値21数量・最古q不要・欠枠/量切断・Fraction符号/鏡像・窓脱落/MFI非補数反例・表示同値の精密差・準備差/値差・独立全panel/採否/純13列・固定33四運用の全台帳/追尾属性・旧A5と現在費用起動。人工66prepareは旧label参照/先着/運用/PnL禁止。旧29八証明六共有/二対照参照、partial、人工無活動四運用末尾と旧29全台帳対照、主独立準備と最終人工の現在版必須join/固定後変更拒否。実市場のstat/openは禁止。",
        "省略": [{"検査": str(case), "理由": reason} for case, reason in result.skipped],
        "失敗": [{"検査": str(case), "内容": reason} for case, reason in result.failures],
        "エラー": [{"検査": str(case), "内容": reason} for case, reason in result.errors]}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: proof[k] for k in ("全件成功", "検証件数", "合成編集終了", "実行中コード条件不変")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
