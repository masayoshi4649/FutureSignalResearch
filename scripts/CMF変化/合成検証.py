"""市場資料を遮断し、同時点CMF差・窓入替え・固定XF接続を人工検査する。"""

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import date, datetime, timedelta
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
HERE, WORK = Path(__file__).resolve().parent, ROOT/"work/CMF変化"
SESSION = "人工CMF変化場"
BOUNDS = (0., 10000., 9000., 9500.)


def normalized(path: object) -> str:
    """市場遮断用にパスを絶対表記へ写す。

    引数: path(object)はパス又は非パス値。
    返り値: strは絶対正規表記。非パスは空文字。
    """
    try: return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError): return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """人工一時先以外の市場資料をopen/statの前に拒否する。

    引数: なし。
    返り値: Iterator[None]は原板/cache/実圧縮明細を読まない検査範囲。
    """
    raw, work = normalized(ROOT.parent/"JP_OSE_Data"), normalized(ROOT/"work")
    opened, path_opened, stated = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """ファイルが実市場資料なら拒否する。

        引数: path(object)はアクセス先。
        返り値: None。人工一時先は明示prefixだけを許す。
        """
        name = normalized(path)
        inside = name.startswith(work+os.sep)
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith(os.path.normcase("CMF変化43合成_"))
        if name == raw or name.startswith(raw+os.sep) or inside and (name.endswith(".npz") or not artificial and name.endswith((".jsonl.gz", ".trades.jsonl"))):
            raise AssertionError("人工検査から市場資料を読まない:"+str(path))

    def safe_open(path: object, *args: object, **kwargs: object) -> Any:
        """通常openに市場遮断を適用する。

        引数: path(object)は先、args/kwargs(object)は元引数。
        返り値: Anyは許可ファイル。
        """
        check(path); return opened(path, *args, **kwargs)

    def safe_path_open(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.openに市場遮断を適用する。

        引数: path(Path)は先、args/kwargs(object)は元引数。
        返り値: Anyは許可ファイル。
        """
        check(path); return path_opened(path, *args, **kwargs)

    def safe_stat(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.statに市場遮断を適用する。

        引数: path(Path)は先、args/kwargs(object)は元引数。
        返り値: Anyは許可されたstat。
        """
        check(path); return stated(path, *args, **kwargs)

    with patch.object(builtins, "open", safe_open), patch.object(Path, "open", safe_path_open), patch.object(Path, "stat", safe_stat):
        yield


def load(path: Path, name: str) -> Any:
    """CLIを起動せず、市場遮断下でコード定義を読み込む。

    引数: path(Path)はコード、name(str)は識別。
    返り値: Anyは読み込んだモジュール。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
        return value


def sha(path: Path) -> str:
    """コードと小型出典の指紋を返す。

    引数: path(Path)は小型ファイル。
    返り値: strはSHA256。市場明細は対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


I = load(HERE/"入口.py", "CMF変化43人工入口")
O = load(HERE/"運用.py", "CMF変化43人工運用")
H = load(ROOT/"scripts/再テスト量方向/合成検証.py", "CMF変化43固定42人工補助")
S37, CONFIG = H.S37, deepcopy(H.CONFIG)


def frame(index: int, close: float = 100., q: float = 1., **changes: object) -> dict:
    """完全qを持つ人工3分足を作る。

    引数: index(int)は番号、close/q(float)は終値/数量、changes(object)は変更。
    返り値: dictは当場公開完全足。
    """
    value = H.frame(index, close, **changes)
    value.update(場=SESSION, 数量参照={"数量基準完全": True, "観測差分量": q})
    return value


def old_block(rows: list[dict], session: str = SESSION) -> dict:
    """固定42を人工足だけで再構成し、純A0と全jを渡す。

    引数: rows(list[dict])は人工価格/Q列、session(str)は場。
    返り値: dictは43の正式block契約。未来labelは含めない。
    """
    result = I.OLD.generate(rows, session, 20000., 30000., {"残り時間下限分": 60, "確認遅延上限秒": 30})
    return {"場": session, "signals": {"3分_A0": [I.OLD.pure_signal(r, "A0") for r in result["signals"]["3分_A0"]]},
        "frames": {3: deepcopy(rows)}, "旧j判定": deepcopy(result["decisions"])}


def material(kind: str = "T") -> list[dict]:
    """旧42の登録b/最初jの人工経路を当場へ写す。

    引数: kind(str)はT/R/WAIT。
    返り値: list[dict]は23人工足。
    """
    rows = H.material(kind)
    for row in rows: row["場"] = SESSION
    return rows


class 現前CMF検証(unittest.TestCase):
    """差の精密境界と、当足/窓落ちの別の役割を検査する。"""

    def test_現前は22足で最古qも必要(self) -> None:
        """21足の現在準備と22足の現前準備を分ける。

        引数: self(TestCase)は対象。
        返り値: None。36の最古q不要規約を混ぜない。
        """
        rows = [frame(i) for i in range(22)]
        panel = I.volume_panels(rows[:21], SESSION)[-1]
        self.assertTrue(panel["CMF現"]["有効"]); self.assertFalse(panel["CMF現前準備"])
        self.assertTrue(I.volume_panels(rows, SESSION)[-1]["CMF現前準備"])
        rows[0]["数量参照"]["数量基準完全"] = False
        panel = I.volume_panels(rows, SESSION)[-1]
        self.assertTrue(panel["CMF現"]["有効"]); self.assertFalse(panel["CMF現前準備"])

    def test_完全0量の窓落ちだけで改善する(self) -> None:
        """当足に方向加重量がなくても差は正になり得る。

        引数: self(TestCase)は対象。
        返り値: None。F前−1/21、Δ1/21、I0/O1/21を照合する。
        """
        rows = [frame(i) for i in range(22)]
        rows[0]["close"] = 90.; rows[-1]["数量参照"]["観測差分量"] = 0.
        p = I.volume_panels(rows, SESSION)[-1]
        for key, value in (("CMF前", -Fraction(1, 21)), ("CMF現", Fraction(0)), ("CMF差", Fraction(1, 21)),
                ("当足寄与I", Fraction(0)), ("窓脱落寄与O", Fraction(1, 21))): self.assertEqual(p[key], I.exact(value))
        self.assertTrue(p["分解一致"]); self.assertEqual(p["CMF差符号"], 1)

    def test_中立CLVでも当足寄与は正になり得る(self) -> None:
        """Iは現在CLVそのものでも積極買い量でもない。

        引数: self(TestCase)は対象。
        返り値: None。I1/441とO20/441を照合する。
        """
        rows = [frame(i) for i in range(22)]; rows[0]["close"] = 90.
        p = I.volume_panels(rows, SESSION)[-1]
        self.assertEqual(p["当足寄与I"], I.exact(Fraction(1, 441)))
        self.assertEqual(p["窓脱落寄与O"], I.exact(Fraction(20, 441)))
        self.assertEqual(p["入足参照"]["CLV"], I.exact(Fraction(0)))

    def test_共通20総量0でも両端量で現前は有効(self) -> None:
        """中間20足の比を作りゼロ除算へ落とさない。

        引数: self(TestCase)は対象。
        返り値: None。F前−1/現1/Δ2を照合する。
        """
        rows = [frame(i, q=0.) for i in range(22)]
        rows[0].update(close=90.); rows[-1].update(close=110.)
        rows[0]["数量参照"]["観測差分量"] = rows[-1]["数量参照"]["観測差分量"] = 1.
        p = I.volume_panels(rows, SESSION)[-1]
        self.assertTrue(p["CMF現前準備"]); self.assertEqual(p["CMF差"], I.exact(Fraction(2)))
        self.assertEqual(p["当足寄与I"], I.exact(Fraction(2))); self.assertEqual(p["窓脱落寄与O"], I.exact(Fraction(0)))

    def test_一定CLVは量が変わっても差0(self) -> None:
        """水準同方向と変化正を別条件として残す。

        引数: self(TestCase)は対象。
        返り値: None。準備済み差等号0を確認する。
        """
        rows = [frame(i, 105., q=float(i+1)) for i in range(22)]
        p = I.volume_panels(rows, SESSION)[-1]
        self.assertEqual(p["CMF現"], I.exact(Fraction(1, 2))); self.assertEqual(p["CMF前"], p["CMF現"])
        self.assertEqual(p["CMF差符号"], 0); self.assertTrue(p["CMF現前準備"])

    def test_鏡像でF差寄与が反転し量と時計は保持(self) -> None:
        """価格反射を時間順逆転やMFIの反射式と混同しない。

        引数: self(TestCase)は対象。
        返り値: None。直接差と交差積/I/O全精密値を照合する。
        """
        rows = [frame(i, 92.+i%18, q=float(i%7)) for i in range(24)]
        a, b = I.volume_panels(rows, SESSION), I.volume_panels(H.reflected(rows), SESSION)
        for x, y in zip(a, b):
            self.assertEqual(x["現窓足番号"], y["現窓足番号"])
            self.assertEqual(x["CMF現前準備"], y["CMF現前準備"])
            for name in ("CMF現", "CMF前", "CMF差", "CMF差交差積", "当足寄与I", "窓脱落寄与O"):
                f = I.fraction(x[name]); self.assertEqual(y[name], I.exact(-f if f is not None else None))

    def test_ゼロ総量零幅欠枠NPと量欠測を区別(self) -> None:
        """量0は有効で、数量不正/幅0/価格不正を圧縮しない。

        引数: self(TestCase)は対象。
        返り値: None。最新不準備時に古正常へ戻らない。
        """
        zero = [frame(i, q=0.) for i in range(22)]
        self.assertFalse(I.volume_panels(zero, SESSION)[-1]["CMF現前準備"])
        for bad in ("missing", "publish", "width", "quantity"):
            rows = [frame(i) for i in range(24)]
            if bad == "missing": rows[-1]["missing"] = 1
            elif bad == "publish": rows[-1]["publish"] = False
            elif bad == "width": rows[-1].update(high=100., low=100., open=100., close=100.)
            else: rows[-1]["数量参照"]["数量基準完全"] = False
            p = I.volume_panels(rows, SESSION)[-1]
            self.assertFalse(p["CMF現前準備"]); self.assertFalse(p["CMF前"]["有効"])
            self.assertIsNone(p["分解一致"])

    def test_番号欠後正常足は新seedで未来prefixを保つ(self) -> None:
        """局所窓を切り、欠枠当足の不投入と番号飛越を区別する。

        引数: self(TestCase)は対象。
        返り値: None。先頭で将来の準備/理由を参照しない。
        """
        rows = [frame(i) for i in range(23)]
        rows[-1] = frame(25)
        p = I.volume_panels(rows, SESSION)[-1]
        self.assertEqual(p["現窓足番号"], [25]); self.assertFalse(p["CMF現前準備"])
        prefix = I.volume_panels(rows[:21], SESSION)
        self.assertEqual(I.volume_panels(rows, SESSION)[:21], prefix)

    def test_一ULP差を表示ゼロやepsilonへ丸めない(self) -> None:
        """等しいCMFの直上/直下だけでも精密符号を残す。

        引数: self(TestCase)は対象。
        返り値: None。CMF差と交差積の符号を鏡像で検査する。
        """
        for close, sign in ((100., 0), (math.nextafter(100., math.inf), 1), (math.nextafter(100., -math.inf), -1)):
            rows = [frame(i) for i in range(22)]; rows[-1]["close"] = close
            p = I.volume_panels(rows, SESSION)[-1]
            self.assertEqual(p["CMF差符号"], sign)
            self.assertEqual((p["CMF差交差積"]["分子"] > 0)-(p["CMF差交差積"]["分子"] < 0), sign)
            reflected = I.volume_panels(H.reflected(rows, 200.), SESSION)[-1]
            self.assertEqual(reflected["CMF差符号"], -sign)


class 純入口と運用検証(unittest.TestCase):
    """旧A0全保持、準備の分離、同時点役割と純signalを検査する。"""

    def test_D0はCMF不可でも旧A0全純13を保持(self) -> None:
        """数量準備を基準の価格発動へ先掛けしない。

        引数: self(TestCase)は対象。
        返り値: None。T/R/WAITと鏡像で旧集合と同時計を照合する。
        """
        for kind in ("T", "R", "WAIT"):
            for mirror in (False, True):
                rows = material(kind)
                if mirror: rows = H.reflected(rows)
                rows[-1]["数量参照"]["数量基準完全"] = False
                old = old_block(rows); result = I.select(deepcopy(old), SESSION)
                self.assertEqual(result["signals"]["3分_D0"], [I.pure_signal(r) for r in old["signals"]["3分_A0"]])
                self.assertEqual(result["signals"]["3分_D1"], []); self.assertEqual(result["signals"]["3分_D2"], [])
                self.assertEqual(len(result["decisions"]), len(old["旧j判定"]))

    def test_差方向だけを加え現水準と寄与はANDしない(self) -> None:
        """現在水準が正のTでもΔが負なら除外、Rでは逆を許す。

        引数: self(TestCase)は対象。
        返り値: None。D2⊆D1⊆D0と純key不変を照合する。
        """
        for kind in ("T", "R"):
            result = I.select(old_block(material(kind)), SESSION)
            p, row = result["decisions"][0]["CMF現前参照"], result["decisions"][0]
            self.assertTrue(p["CMF現前準備"])
            self.assertEqual(row["戦略判定"]["D2"]["採用"], row["side"]*p["CMF差符号"] > 0)
            self.assertGreater(I.fraction(p["CMF現"]), 0)
            self.assertEqual(tuple(len(result["signals"]["3分_"+x]) for x in I.POLICIES), (1, 1, 0) if kind == "T" else (1, 1, 1))

    def test_純13排除未来labelと元親metadataを保持(self) -> None:
        """元のj要求やATRをb/将来情報で書き換えない。

        引数: self(TestCase)は対象。
        返り値: None。深複写/全元j対応/将来列不流入を確認する。
        """
        block = old_block(material())
        block["旧j判定"][0]["将来ラベル"] = "毒値"
        before = deepcopy(block)
        result = I.select(block, SESSION)
        signal = result["signals"]["3分_D0"][0]
        self.assertEqual(set(signal), set(I.SIGNAL_FIELDS)); self.assertNotIn("将来ラベル", signal)
        old = before["signals"]["3分_A0"][0]
        for key in I.SIGNAL_FIELDS:
            if key not in ("入口ID", "イベントID"): self.assertEqual(signal[key], old[key])
        self.assertEqual(result["metadata"][old["イベントID"][:-3]]["判別種別"], "T")
        signal["atr"] = 999.
        self.assertEqual(before["signals"]["3分_A0"][0]["atr"], 25.)

    def test_旧採用集合とsourcekey改変を拒否(self) -> None:
        """対照の欠落/未来時計をコピー時の許容へ隠さない。

        引数: self(TestCase)は対象。
        返り値: None。旧pureと全j/保存足が不一致なら停止する。
        """
        block = old_block(material()); block["signals"]["3分_A0"] = []
        with self.assertRaises(ValueError): I.select(block, SESSION)
        block = old_block(material()); block["旧j判定"][0]["要求原板行"] += 1
        with self.assertRaises(ValueError): I.select(block, SESSION)

    def test_三案買売二役割を固定33へ全属性照合(self) -> None:
        """新しい数量条件を出口・受付へ持ち込まない。

        引数: self(TestCase)は対象。
        返り値: None。12人工運用の全ledger/logを照合する。
        """
        for policy in I.POLICIES:
            for side in (1, -1):
                for role in ("順行", "反転"):
                    row = S37.signal(policy, side, role); row.update(場=SESSION, 将来ラベル="毒値")
                    events = [S37.quote(11., 11, side, -5.), S37.quote(12., 12, side, 15.), S37.quote(13., 13, side, 0.), S37.quote(14., 14, side, -5.)]
                    args = (events, [row], [], SESSION, "3分_"+policy+"_XF", CONFIG, {"出口ID": "XF"}, "切替", BOUNDS)
                    actual, info = O.replay(*args)
                    expected, quality = O.BASE.replay(events, [O.pure_signal(row)], [], *args[3:])
                    for key in ("orders", "fills", "trades", "signals", "normal_log"):
                        self.assertEqual(getattr(actual, key), getattr(expected, key))
                    self.assertEqual(info, quality)

    def test_混合T完結後Rへ切替えjATRを各fill固定(self) -> None:
        """同じ候補の保有役割とATRを後続signalで上書きしない。

        引数: self(TestCase)は対象。
        返り値: None。買売鏡像で順行25→反転40のDを検査する。
        """
        for side in (1, -1):
            rows = [S37.signal("D0", side, "順行", "最初T", 10., 10), S37.signal("D0", -side, "反転", "保有R", 12.5, 125), S37.signal("D0", -side, "反転", "後続R", 20., 200)]
            for row in rows: row["場"] = SESSION
            rows[2]["atr"] = 40.
            events = [S37.quote(t, int(t*10), d, price) for t, d, price in [(11.,side,-5.),(12.,side,15.),(13.,side,0.),(14.,side,-5.),(21.,-side,-5.),(22.,-side,15.),(23.,-side,0.),(24.,-side,-5.)]]
            actual, _ = O.replay(events, rows, [], SESSION, "3分_D0_XF", CONFIG, {"出口ID": "XF"}, "切替", BOUNDS)
            self.assertEqual([r["入口役割"] for r in actual.trades], ["順行", "反転"])
            self.assertEqual([r["追尾距離pt"] for r in actual.trades], [25., 40.])
            self.assertEqual([r["取扱"] for r in actual.signals], ["新規約定", "建玉中抑止", "新規約定"])

    def test_独立全panelと全j採否は別算で一致(self) -> None:
        """独立核完成前は明示skipとし、最終proofでは許さない。

        引数: self(TestCase)は対象。
        返り値: None。主をimportしない独立全dictを照合する。
        """
        path = HERE/"状態独立確認.py"
        if not path.exists(): self.skipTest("独立核未完成")
        independent = load(path, "CMF変化43人工独立")
        if not all(hasattr(independent, name) for name in ("volume_panels", "select")): self.skipTest("独立API未完成")
        for kind in ("T", "R", "WAIT"):
            for reflected in (False, True):
                rows = material(kind)
                if reflected: rows = H.reflected(rows)
                block = old_block(rows)
                self.assertEqual(I.volume_panels(rows, SESSION), independent.volume_panels(rows, SESSION))
                a, b = I.select(deepcopy(block), SESSION), independent.select(deepcopy(block), SESSION)
                for key in ("signals", "decisions", "metadata", "quality", "volume_panels"): self.assertEqual(a[key], b[key])


def driver_module() -> Any:
    """主CLIを起動せず現定義だけを読み込む。

    引数: なし。
    返り値: Anyは43主。未保存なら明示skipを呼出側で行う。
    """
    return load(HERE/"検証.py", "CMF変化43人工主")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """旧A0/全j/3分Qと一時保存先だけの人工束を作る。

    引数: driver(Any)は主、count(int)は人工場数。
    返り値: Iterator[Any]はstudy/work/bundle/build/manifest。実gzipを開かない。
    """
    with tempfile.TemporaryDirectory(prefix="CMF変化43合成_", dir=ROOT/"work") as temporary:
        folder = Path(temporary); study, work = folder/"study", folder/"work"
        study.mkdir(); work.mkdir()
        config = driver.expected_config()
        driver.W.write_json(study/"条件.json", config)
        for name in ("入口参照.json", "対照参照.json", "指標参照.json", "入力台帳.json"):
            driver.W.write_json(study/name, {"人工": True})
        (study/"計画.md").write_text("人工固定対象\n", encoding="utf-8")
        driver.W.write_json(work/"診断予定.json", {"人工": True})
        sessions = [str(date(2026, 9, 22)+timedelta(days=i//2))+("_Day" if i%2 == 0 else "_Night") for i in range(count)]
        bundle = {"pure": {}, "metadata": {}, "old_decisions": {}, "lower": {}}
        for name in sessions:
            rows = material("R")
            for row in rows: row["場"] = name
            original = old_block(rows, name)
            bundle["lower"][name] = rows
            bundle["pure"][name] = original["signals"]["3分_A0"]
            bundle["old_decisions"][name] = original["旧j判定"]
            for row in original["旧j判定"]:
                if row["戦略判定"]["A0"]["採用"]:
                    bundle["metadata"][row["発動ID"]+"_A0"] = {"元登録ID": row["登録ID"], "元価格side": row["元価格side"],
                        "元登録時計秒": row["登録参照"]["登録足"]["confirm"], "元登録原板行": row["登録参照"]["登録足"]["confirm_line"], "判別種別": row["構造区分"]}

        def built(entry: dict, manifest: dict, shared: dict, current: dict, include_events: bool = False) -> dict:
            """実selectと純13を通し、正式時だけ人工BBOを渡す。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式フラグ。
            返り値: dictは当場三入口/全j/全panel/人工気配。
            """
            name = entry["session"]
            block = {"場": name, "signals": {"3分_A0": deepcopy(shared["pure"][name])},
                "frames": {3: deepcopy(shared["lower"][name])}, "旧j判定": deepcopy(shared["old_decisions"][name])}
            driver.I.select(block, name)
            block.update(input_quality=deepcopy(block["quality"]), cutoff=9000., deadline=9500., duration=10000./60, events=[])
            if include_events:
                block["events"] = [S37.quote(t, i+1, -1, price) for i, (t, price) in enumerate(
                    [(4140.,-5.),(4141.,-5.),(4142.,15.),(4143.,0.),(4144.,-5.)])]
            return block

        yield SimpleNamespace(study=study, work=work, config=config, bundle=bundle, built=built,
            manifest={"source_root": "人工予約だけ", "entries": [{"session": name} for name in sessions]},
            ref={"文書と証明": {}, "共有明細": []})


class 主接続検証(unittest.TestCase):
    """共有入口のコピー、非損益準備、完全対照の正式末尾を人工で接続する。"""

    def test_共有245純と424jを別読取しlabelを即排除(self) -> None:
        """旧監視/上位を再読せず、保存caseを純13へ直ちに写す。

        引数: self(TestCase)は対象。
        返り値: None。共有数固定と読取名/純字段を確認する。
        """
        driver = driver_module()
        original = old_block(material("R")); signal = original["signals"]["3分_A0"][0]
        meta = {"元登録ID": "人工親", "元価格side": 1, "元登録時計秒": 3780., "元登録原板行": 21, "判別種別": "R"}
        cases = [{**deepcopy(signal), **meta, "イベントID": f"人工j{i}_A0", "ラベル": "毒値", "将来利益": 999.} for i in range(245)]
        contexts = [{**deepcopy(original["旧j判定"][0]), "期間": "学習"} for _ in range(424)]
        streams = {"入口事例.jsonl.gz": cases, "発動判定.jsonl.gz": contexts,
            "全指標.jsonl.gz": material()+[{"minutes": 15, "場": "不使用上位"}]}
        with patch.object(driver, "validate_reference", return_value={}), patch.object(driver, "shared_path", side_effect=lambda ref, name: Path(name)), \
                patch.object(driver, "read_rows", side_effect=lambda path: deepcopy(streams[path.name])) as reader:
            bundle = driver.read_bundle(driver.STUDY)
        self.assertEqual(reader.call_count, 3)
        self.assertEqual(sum(map(len, bundle["pure"].values())), 245)
        self.assertEqual(sum(map(len, bundle["old_decisions"].values())), 424)
        self.assertEqual(set(bundle["pure"][SESSION][0]), set(I.SIGNAL_FIELDS))
        self.assertNotIn("期間", bundle["old_decisions"][SESSION][0])
        self.assertTrue(all(row["minutes"] == 3 for row in bundle["lower"][SESSION]))
        streams["入口事例.jsonl.gz"].pop()
        with patch.object(driver, "validate_reference", return_value={}), patch.object(driver, "shared_path", side_effect=lambda ref, name: Path(name)), \
                patch.object(driver, "read_rows", side_effect=lambda path: deepcopy(streams[path.name])):
            with self.assertRaises(ValueError): driver.read_bundle(driver.STUDY)

    def test_実build_sessionはselect済D純を再変換せずprepareで気配を読まない(self) -> None:
        """新APIの非空D0で、旧A0only変換を二重に呼ばない。

        引数: self(TestCase)は対象。
        返り値: None。人工source/cacheだけで主buildの純13を検査する。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            source, cache = f.study.parent/"source.bin", f.study.parent/"cache.bin"
            source.write_bytes(b"artificial-source"); cache.write_bytes(b"artificial-cache")
            stat = source.stat(); name = f.manifest["entries"][0]["session"]
            entry = {"session": name, "source_path": source.name, "cache_path": os.path.relpath(cache, ROOT/"work/複合検証"),
                "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns, "sha256_cache": sha(cache)}
            times = tuple(SimpleNamespace(timestamp=lambda value=value: value) for value in (0., 10000., 9000., 9500.))
            with patch.object(driver.W.OLD.shared.legacy, "session_times", return_value=times), \
                    patch.object(driver.W.PREP, "read_events", side_effect=AssertionError("準備で気配を読まない")):
                block = driver.build_session(entry, {"source_root": str(source.parent)}, f.bundle, f.config, False)
            self.assertEqual([len(block["signals"]["3分_"+p]) for p in I.POLICIES], [1, 1, 1])
            self.assertEqual(block["events"], [])
            self.assertTrue(all(set(r) == set(I.SIGNAL_FIELDS) for rows in block["signals"].values() for r in rows))

    def test_CLI人工66準備は先着運用損益を一切呼ばない(self) -> None:
        """全j/全panel/三純だけをprepareのCLIへ接続する。

        引数: self(TestCase)は対象。
        返り値: None。旧label/対照ledgerも準備では読まない。
        """
        driver = driver_module()
        with artificial_driver(driver, 66) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", return_value=f.ref), patch.object(driver, "read_bundle", return_value=f.bundle), \
                patch.object(driver, "build_session", side_effect=f.built), patch.object(driver, "freeze", side_effect=AssertionError("準備でfreeze不可")), \
                patch.object(driver, "read_rows", side_effect=AssertionError("準備で旧label/ledger不可")), \
                patch.object(driver.W.OLD, "気配経路", side_effect=AssertionError("準備で先着不可")), \
                patch.object(driver.ENGINE, "replay", side_effect=AssertionError("準備で運用不可")), \
                patch.object(driver.E, "entry_metrics", side_effect=AssertionError("準備で入口成績不可")), \
                patch.object(driver.S, "operation_metrics", side_effect=AssertionError("準備で損益不可")), \
                patch.object(sys, "argv", [str(HERE/"検証.py"), "--prepare", "--study", str(f.study), "--work", str(f.work)]), redirect_stdout(io.StringIO()):
            driver.main()
            prepared = driver.W.read_json(f.work/"準備点検.json")
            self.assertFalse(prepared["ラベル計算"]); self.assertFalse(prepared["損益計算"])
            self.assertTrue(prepared["旧A0純登録同値"]); self.assertEqual(prepared["旧A0登録数"], 66)
            self.assertEqual(len(prepared["準備"]), 66)
            self.assertTrue(all(r["CMF足数"] == 23 and "登録" not in r and "監視" not in r for r in prepared["準備"]))
            self.assertFalse(any((f.work/name).exists() for name in driver.FILES))

    def test_人工正式三先着三運用と旧A0全対照を末尾まで保存(self) -> None:
        """同j旧11label照合/4gzip/6役割/完全対照に到達する。

        引数: self(TestCase)は対象。
        返り値: None。ラベルは人工値、運用は人工BBOだけを使う。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            entry, period = f.manifest["entries"][0], "学習"
            block = f.built(entry, f.manifest, f.bundle, f.config, True)
            name = entry["session"]
            old_signal = f.bundle["pure"][name][0]
            old_state, old_info = H.O.replay(block["events"], [old_signal], block["frames"][3], name,
                "3分_A0_XF", f.config["運用"], {"出口ID": "XF"}, "切替", BOUNDS)
            old_info.update(期間=period, 場時間分=block["duration"])
            for r in old_state.trades: r["期間"] = period
            detail = {"候補ID": "3分_A0_XF", "場": name, "品質": old_info, "約定": old_state.fills,
                "取引": old_state.trades, "注文": old_state.orders, "入口取扱": old_state.signals}
            logs = [{"期間": period, **r} for r in old_state.normal_log]
            label = dict(zip(driver.LABEL_FIELDS, ["逆行先着", "人工", 1005., 4141., 2, 4144., 5, 1010., 20., 5., 0.05]))
            old_cases = [{**old_signal, **label}]
            streams = {"入口事例.jsonl.gz": old_cases, "全運用詳細.jsonl.gz": [detail], "追尾.jsonl.gz": logs}
            replay = driver.ENGINE.replay

            def operation(*args: object) -> tuple:
                """人工の固定範囲を明示して新wrapperを呼ぶ。

                引数: args(object)は主の逐次運用引数。
                返り値: tupleは人工BBOの状態/品質。
                """
                return replay(*args, bounds=BOUNDS)

            def publish(study: Path, path: Path, ids: list[str], manifest: dict, suffix: str) -> None:
                """Viewer公開を人工小型一覧へ差替える。

                引数: study/path(Path)は保存先、ids(list[str])は三候補、manifest(dict)/suffix(str)は元契約。
                返り値: None。市場資料は読まない。
                """
                driver.W.write_json(study/"一覧.resources.json", {"resources": [{"id": "00008_人工", "人工": True}]})

            with patch.object(driver, "manifest_for", return_value=f.manifest), patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "read_bundle", return_value=f.bundle), patch.object(driver, "build_session", side_effect=f.built), \
                    patch.object(driver, "freeze", return_value={}), patch.object(driver, "shared_path", side_effect=lambda ref, n: Path(n)), \
                    patch.object(driver, "read_rows", side_effect=lambda path: deepcopy(streams[path.name])), \
                    patch.object(driver.W.OLD, "気配経路", return_value=SimpleNamespace(evaluate=lambda *args, **kwargs: deepcopy(label))), \
                    patch.object(driver.ENGINE, "replay", side_effect=operation), patch.object(driver.E, "publish_details", side_effect=publish), redirect_stdout(io.StringIO()):
                result = driver.run(f.study, f.work, False)
            self.assertEqual(result["入口評価数"], 3)
            report = driver.W.read_json(f.study/"結果.json")
            self.assertEqual(len(report["役割別入口評価"]), 6)
            controls = driver.W.read_json(f.study/"D0対照同値.json")
            self.assertTrue(controls["全件一致"]); self.assertTrue(controls["旧先着全件同値"])
            self.assertTrue(controls["照合"][0]["全運用同値"]); self.assertTrue(controls["照合"][0]["全追尾同値"])
            self.assertEqual(len(driver.W.read_json(f.study/"作業成果物.json")["ファイル"]), 4)
            with driver.gzip.open(f.work/"入口事例.jsonl.gz", "rt", encoding="utf-8") as stream: cases = [json.loads(r) for r in stream]
            self.assertEqual(len(cases), 3)
            for row in cases:
                self.assertEqual({k: row[k] for k in driver.LABEL_FIELDS}, label)
                self.assertEqual(row["旧A0イベントID"], old_signal["イベントID"])

    def test_条件変更partialと実行中出典差は上書き前に拒否(self) -> None:
        """主要条件を変更せず、正式partialの続行を許さない。

        引数: self(TestCase)は対象。
        返り値: None。資料読取前の停止と準備の版不変guardを確認する。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            wrong = deepcopy(f.config); wrong["CMF変化"]["D2"] = "結果後変更"
            with self.assertRaises(ValueError): driver.validate_config(wrong)
            (f.work/driver.FILES[0]).write_bytes(b"artificial-partial")
            with patch.object(driver, "manifest_for", return_value=f.manifest), patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "read_bundle", side_effect=AssertionError("partial後に資料を開かない")):
                with self.assertRaises(ValueError): driver.run(f.study, f.work, False)
            bindings = driver.current_bindings(f.study)
            changed = deepcopy(bindings); changed["条件SHA256"] = "0"*64
            with patch.object(driver, "manifest_for", return_value=f.manifest), patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "read_bundle", return_value=f.bundle), patch.object(driver, "build_session", side_effect=f.built), \
                    patch.object(driver, "current_bindings", side_effect=[bindings, changed]), redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError): driver.run(f.study, f.work, True)
            self.assertFalse((f.work/"準備点検.json").exists())

    def test_入口対照参照の必須証明共有範囲とdigestを厳密にする(self) -> None:
        """pointer自己更新だけで固定42正本を置き換えさせない。

        引数: self(TestCase)は対象。
        返り値: None。実gzipは宣言済み指紋の人工戻しで開かない。
        """
        driver = driver_module()
        for name in ("入口参照.json", "対照参照.json"):
            pointer = driver.W.read_json(driver.STUDY/name)
            declared = {normalized(ROOT/r["パス"]): r["圧縮SHA256参考"] for r in pointer["共有明細"]}
            expanded = {normalized(ROOT/r["パス"]): r["展開内容SHA256"] for r in pointer["共有明細"]}
            actual_sha = driver.O.sha
            with artificial_driver(driver, 1) as f, patch.object(driver.O, "sha", side_effect=lambda p: declared.get(normalized(p), None) or actual_sha(p)), \
                    patch.object(driver, "content_sha", side_effect=lambda p: expanded[normalized(p)]):
                driver.W.write_json(f.study/name, pointer)
                self.assertEqual(driver.validate_reference(f.study, name), pointer)
                for key in pointer["文書と証明"]:
                    wrong = deepcopy(pointer); wrong["文書と証明"].pop(key)
                    driver.W.write_json(f.study/name, wrong)
                    with self.assertRaises(ValueError): driver.validate_reference(f.study, name)
                for key in ("旧固定SHA256", "共有明細"):
                    wrong = deepcopy(pointer); wrong[key] = "0"*64 if key == "旧固定SHA256" else []
                    driver.W.write_json(f.study/name, wrong)
                    with self.assertRaises(ValueError): driver.validate_reference(f.study, name)
                driver.W.write_json(f.study/name, pointer)
                first = next(iter(declared)); original = declared[first]; declared[first] = "0"*64
                with self.assertRaises(ValueError): driver.validate_reference(f.study, name)
                declared[first] = original
        with patch.object(driver.M, "validate_reference", return_value={"人工数値": True}) as delegated:
            self.assertEqual(driver.validate_reference(driver.STUDY, "指標参照.json"), {"人工数値": True})
            delegated.assert_called_once_with(driver.STUDY, "指標参照.json")
        with self.assertRaises(ValueError): driver.validate_reference(driver.STUDY, "未登録参照.json")

    def test_固定は旧245同値と独立最終人工と会計12の全現在版joinを要求(self) -> None:
        """非損益準備/依存指紋/三参照を固定前に必須接続する。

        引数: self(TestCase)は対象。
        返り値: None。固定は人工一時先だけ、独立CLI未完成は最終前だけskipする。
        """
        driver = driver_module()
        required = [HERE/"追尾独立確認.py", ROOT/"work/CMF変化43の事前案.md", driver.WORK/"会計人工接続.json"]
        if not all(p.exists() for p in required): self.skipTest("固定の全出典完成前")
        with artificial_driver(driver, 1) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", return_value=f.ref), patch.object(driver, "read_bundle", return_value=f.bundle), \
                patch.object(driver, "build_session", side_effect=f.built), redirect_stdout(io.StringIO()):
            driver.run(f.study, f.work, True)
            prepared = driver.W.read_json(f.work/"準備点検.json"); prepared["旧A0登録数"] = 245
            driver.W.write_json(f.work/"準備点検.json", prepared)
            finance = driver.W.read_json(driver.WORK/"会計人工接続.json")
            finance["条件SHA256"] = sha(f.study/"条件.json")
            driver.W.write_json(f.work/"会計人工接続.json", finance)
            (f.work/"会計人工接続.py").write_bytes((driver.WORK/"会計人工接続.py").read_bytes())
            dep = ROOT/"scripts/OBV反転/入口.py"
            proof = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
                "主準備SHA256": sha(f.work/"準備点検.json"), "主コードSHA256": driver.code_pins(),
                "条件SHA256": sha(f.study/"条件.json"), "入力台帳SHA256": sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256": sha(driver.MANIFEST_PATH), "入口参照SHA256": sha(f.study/"入口参照.json"),
                "対照参照SHA256": sha(f.study/"対照参照.json"), "指標参照SHA256": sha(f.study/"指標参照.json"),
                "コードSHA256": sha(HERE/"状態独立確認.py"), "追尾コードSHA256": sha(HERE/"追尾独立確認.py"),
                "依存コードSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
            synthetic = {"全件成功": True, "合成編集終了": False,
                "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in
                    [HERE/n for n in ("検証.py", "入口.py", "運用.py", "合成検証.py")]+[f.study/"条件.json"]},
                "独立数値補助SHA256": sha(HERE/"状態独立確認.py"), "独立追尾補助SHA256": sha(HERE/"追尾独立確認.py")}
            synthetic_file, independent = f.work/"人工最終合成.json", f.work/"独立準備点検.json"
            driver.W.write_json(synthetic_file, synthetic)
            actual_read, actual_sha = driver.W.read_json, driver.O.sha

            def read_json(path: Path) -> dict:
                """直前固定集合と最終人工だけを一時証明へ差替える。

                引数: path(Path)は小型出典。
                返り値: dictは人工宣言又は実小型正本。
                """
                if normalized(path) == normalized(driver.PREVIOUS/"固定.json"):
                    return {"ファイルSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
                return deepcopy(synthetic) if normalized(path) == normalized(WORK/"合成検証.json") else actual_read(path)

            def current_sha(path: Path) -> str:
                """最終人工の実パスだけを人工指紋へ置換する。

                引数: path(Path)は対象。
                返り値: strは人工又は現在正本のSHA256。
                """
                return sha(synthetic_file) if normalized(path) == normalized(WORK/"合成検証.json") else actual_sha(path)

            with patch.object(driver.W, "read_json", side_effect=read_json), patch.object(driver.O, "sha", side_effect=current_sha):
                with self.assertRaises(FileNotFoundError): driver.freeze(f.study, f.work)
                driver.W.write_json(independent, proof)
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                synthetic["合成編集終了"] = True
                for key in proof:
                    wrong = deepcopy(proof)
                    wrong[key] = not proof[key] if isinstance(proof[key], bool) else {} if isinstance(proof[key], dict) else "不一致"
                    driver.W.write_json(independent, wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(independent, proof)
                for key in ("独立数値補助SHA256", "独立追尾補助SHA256"):
                    original = synthetic[key]; synthetic[key] = "0"*64
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                    synthetic[key] = original
                for key in ("旧A0純登録同値", "旧A0登録数", "ラベル計算", "損益計算"):
                    wrong = deepcopy(prepared); wrong[key] = False if key == "旧A0純登録同値" else 244 if key == "旧A0登録数" else True
                    driver.W.write_json(f.work/"準備点検.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.work/"準備点検.json", prepared)
                for key in ("全件一致", "不一致数", "人工経路数", "コードSHA256", "条件SHA256", "実行中code不変"):
                    wrong = deepcopy(finance)
                    wrong[key] = False if key in ("全件一致", "実行中code不変") else {} if key == "コードSHA256" else "0"*64 if key == "条件SHA256" else -1
                    driver.W.write_json(f.work/"会計人工接続.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                for source in ("scripts/CMF変化/独立監査.py", "scripts/CMF変化/運用.py", "work/CMF変化/00043/会計人工接続.py"):
                    wrong = deepcopy(finance); wrong["コードSHA256"].pop(source)
                    driver.W.write_json(f.work/"会計人工接続.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.work/"会計人工接続.json", finance)
                driver.W.write_json(synthetic_file, synthetic)
                locked = driver.freeze(f.study, f.work)
                self.assertEqual(driver.freeze(f.study, f.work), locked)
                self.assertEqual(locked["独立準備SHA256"], sha(independent))
                (f.study/"計画.md").write_text("人工の固定後変更\n", encoding="utf-8")
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.study/"結果.json", {"人工": True})
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)


def main() -> None:
    """人工だけを検査し、root最終許可前は途中証明を保存する。

    引数: CLI --final(bool)はroot許可後の一回だけ指定する。
    返り値: None。原市場/実先着/実運用の再生は行わない。
    """
    parser = argparse.ArgumentParser(description="CMF変化の人工検証")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    paths = [HERE/name for name in ("検証.py", "入口.py", "運用.py", "合成検証.py")]
    paths.append(ROOT/"study/00043_再テスト時のCMF変化方向/条件.json")
    paths = [p for p in paths if p.exists()]
    helpers = [p for p in (HERE/"状態独立確認.py", HERE/"追尾独立確認.py") if p.exists()]
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in helpers}
    with deny_market(): result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged = pins == {p.relative_to(ROOT).as_posix(): sha(p) for p in paths} and before == {p.relative_to(ROOT).as_posix(): sha(p) for p in helpers}
    success = result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    if args.final and (len(pins) != 5 or len(before) != 2): raise ValueError("主3code/条件/合成と独立二code完成前です")
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
        "市場入力読取": False, "市場先着損益計算": False, "実行中コード条件不変": unchanged,
        "ファイルSHA256": pins, "独立数値補助SHA256": before.get("scripts/CMF変化/状態独立確認.py"),
        "独立追尾補助SHA256": before.get("scripts/CMF変化/追尾独立確認.py"),
        "skip数": len(result.skipped), "失敗数": len(result.failures), "エラー数": len(result.errors)}
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"出力": str(path), "全件成功": success, "件数": result.testsRun, "SHA256": sha(path)}, ensure_ascii=False))
    if not success: raise SystemExit(1)


if __name__ == "__main__": main()
