"""実市場を遮断し、跨商品の価格時計・TOPIX数値・NK純入口を人工検査する。"""

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
HERE, WORK = Path(__file__).resolve().parent, ROOT/"work/TOPIX補助"
SESSION = "人工TOPIX補助場"


def normalized(path: object) -> str:
    """市場遮断用にパスを正規絶対表記へ写す。

    引数: path(object)はパス又は非パス値。
    返り値: strは正規表記。非パスなら空文字。
    """
    try: return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError): return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """JP原入力と実cache/圧縮明細のopen/statを拒否する。

    引数: なし。
    返り値: Iterator[None]は人工一時先とコード/小型正本だけを許す範囲。
    """
    raw, work = normalized(ROOT.parent/"JP_OSE_Data"), normalized(ROOT/"work")
    opened, path_opened, stated = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """実市場へのアクセスなら拒否する。

        引数: path(object)はアクセス先。
        返り値: None。人工一時先のprefixだけを例外にする。
        """
        name = normalized(path)
        inside = name.startswith(work+os.sep)
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith(os.path.normcase("TOPIX補助44合成_"))
        if name == raw or name.startswith(raw+os.sep) or inside and not artificial and name.endswith((".npz", ".jsonl.gz", ".trades.jsonl")):
            raise AssertionError("人工検査から実市場資料を読まない:"+str(path))

    def safe_open(path: object, *args: object, **kwargs: object) -> Any:
        """通常openに市場遮断を適用する。

        引数: path(object)は先、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
        """
        check(path); return opened(path, *args, **kwargs)

    def safe_path_open(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.openに市場遮断を適用する。

        引数: path(Path)は先、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
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
    """CLIを起動せず定義だけを市場遮断下で読む。

    引数: path(Path)はコード、name(str)は識別。
    返り値: Anyはモジュール。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value; spec.loader.exec_module(value)
        return value


def sha(path: Path) -> str:
    """コードと小型証明のSHA256を返す。

    引数: path(Path)は対象。
    返り値: strは指紋。実市場明細は対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


I = load(HERE/"入口.py", "TOPIX44人工入口")
J = load(HERE/"指標.py", "TOPIX44人工数値")
H = load(ROOT/"scripts/CMF変化/合成検証.py", "TOPIX44固定43人工補助")


def auxiliary(index: int, direction: int = 1, **changes: object) -> dict:
    """公開済みのTOPIX限定数値足を人工で作る。

    引数: index(int)は番号、direction(int)は人工の価格/ヒスト方向、changes(object)は変更。
    返り値: dictは17列。実数値銀行の検査ではこのヒスト注入値を使わない。
    """
    close = 200.+direction*index*0.5
    row = H.frame(index, close, high=close+1., low=close-1., open=close)
    row.update(場=SESSION, 価格数値入力可=True, macd_hist=direction*float(index),
        MACD原点=200., MACD原点出典={"場": "過去の人工場", "index": 0})
    row.update(changes)
    return J.aux_projection(row)


def material(kind: str = "T", delay: float = 2., direction: int | None = None, session: str = SESSION) -> dict:
    """固定42のNK人工jと同終了TOPIXを組み合わせる。

    引数: kind(str)はT/R/WAIT、delay(float)はNKj遅延、direction(int|None)は補助方向、session(str)は場。
    返り値: dictは44の場材料。旧labelは含めない。
    """
    rows = H.material(kind)
    for row in rows: row["場"] = session
    rows[-1]["confirm"] += delay
    block = H.old_block(rows, session)
    actual = 1 if kind != "R" else -1
    block.update(補助足=[auxiliary(i, direction if direction is not None else actual) for i in range(23)], 商品照合=True)
    for row in block["補助足"]: row["場"] = session
    block["補助足"][-1]["confirm"] += 1.
    return block


class 補助時点と採否検証(unittest.TestCase):
    """別ファイルの行を序列にせず、可視参照と部分集合を検査する。"""

    def test_strict事前同終了だけを参照し他商品lineを比較しない(self) -> None:
        """同秒は待機、1価格秒前なら原行大小によらず参照できる。

        引数: self(TestCase)は対象。
        返り値: None。X0保持とX1/X2の同時点追加を確認する。
        """
        for line in (1, 999999):
            block = material(); block["補助足"][-1]["confirm_line"] = line
            result = I.select(block, SESSION)
            self.assertEqual([len(result["signals"]["3分_"+p]) for p in I.POLICIES], [1, 1, 1])
            self.assertIsNotNone(result["decisions"][0]["補助参照"])
        block = material(delay=1.)
        result = I.select(block, SESSION)
        self.assertEqual([len(result["signals"]["3分_"+p]) for p in I.POLICIES], [1, 0, 0])
        self.assertIsNone(result["decisions"][0]["補助参照"])
        self.assertEqual(result["decisions"][0]["準備除外理由"], [I.NO_VISIBLE])

    def test_未収録同秒後公開を追加してもNone理由と純を変えない(self) -> None:
        """未可視の足の存在を準備理由へ漏らさない。

        引数: self(TestCase)は対象。
        返り値: None。全decision+signalsのfuture prefix不変を確認する。
        """
        block = material(); hidden = deepcopy(block["補助足"][-1]); block["補助足"].pop()
        baseline = I.select(deepcopy(block), SESSION)
        for confirm, publish in ((4142., True), (4143., True), (4141., False)):
            candidate = deepcopy(block); hidden_copy = deepcopy(hidden)
            hidden_copy.update(confirm=confirm, publish=publish)
            candidate["補助足"].append(hidden_copy)
            actual = I.select(candidate, SESSION)
            self.assertEqual(actual["decisions"], baseline["decisions"])
            self.assertEqual(actual["signals"], baseline["signals"])

    def test_NK遅延0なら同終了strict事前は不可(self) -> None:
        """時計による除外をTOPIX方向不一致へ読み替えない。

        引数: self(TestCase)は対象。
        返り値: None。古い正常足へのfallbackを禁止する。
        """
        block = material(delay=0.); block["補助足"][-1]["confirm"] = 4140.
        actual = I.select(block, SESSION)
        self.assertEqual(actual["decisions"][0]["準備除外理由"], [I.NO_VISIBLE])
        self.assertEqual(len(actual["signals"]["3分_X0"]), 1)

    def test_傾き0とヒスト差0は準備だけ通り値で不成立(self) -> None:
        """R2/非零値をX1準備へ紛れ込ませない。

        引数: self(TestCase)は対象。
        返り値: None。定値20点とH同値でもX1を保持する。
        """
        block = material()
        for row in block["補助足"]: row.update(open=200., high=201., low=199., close=200., macd_hist=0.)
        result = I.select(block, SESSION); panel = result["decisions"][0]["補助参照"]
        self.assertTrue(panel["補助数値準備"])
        self.assertEqual(panel["OLS20傾き"], I.exact(Fraction(0)))
        self.assertEqual(panel["MACDヒスト変化"], 0.)
        self.assertEqual([len(result["signals"]["3分_"+p]) for p in I.POLICIES], [1, 1, 0])

    def test_OLSとヒストの複合値であり片方だけで採用しない(self) -> None:
        """別手法の単独効果や相関係数を測ったとしない。

        引数: self(TestCase)は対象。
        返り値: None。方向/勢いのAND、0値、売りの同じ式を確認する。
        """
        for kind in ("T", "R"):
            for opposite in ("price", "hist"):
                block = material(kind)
                if opposite == "price":
                    for row in block["補助足"]:
                        prior = deepcopy(row); row.update(open=400.-prior["open"], high=400.-prior["low"], low=400.-prior["high"], close=400.-prior["close"])
                else:
                    for row in block["補助足"]: row["macd_hist"] = -row["macd_hist"]
                result = I.select(block, SESSION)
                self.assertEqual([len(result["signals"]["3分_"+p]) for p in I.POLICIES], [1, 1, 0])

    def test_両商品を同時反射し役割と採否を維持(self) -> None:
        """NKだけの反射を関連二系列の鏡映検査にしない。

        引数: self(TestCase)は対象。
        返り値: None。T/Rと補助符号が共に反転することを照合する。
        """
        for kind in ("T", "R"):
            block = material(kind); normal = I.select(deepcopy(block), SESSION)
            rows = H.H.reflected(block["frames"][3])
            reflected = H.old_block(rows, SESSION)
            reflected.update(商品照合=True, 補助足=[])
            for row in block["補助足"]:
                value = deepcopy(row)
                value.update(open=400.-row["open"], high=400.-row["low"], low=400.-row["high"], close=400.-row["close"], macd_hist=-row["macd_hist"], MACD原点=200.)
                reflected["補助足"].append(value)
            actual = I.select(reflected, SESSION)
            for p in I.POLICIES:
                left, right = normal["signals"]["3分_"+p], actual["signals"]["3分_"+p]
                self.assertEqual(len(left), len(right))
                for a, b in zip(left, right): self.assertEqual(a["side"], -b["side"]); self.assertEqual(a["役割"], b["役割"])

    def test_数量不使用と価格準備欠測と限月年月を分ける(self) -> None:
        """数量/BBO/ATRを補助準備へ加えず、価格不正は最新のまま待機する。

        引数: self(TestCase)は対象。
        返り値: None。X0は補助不足でも保持、旧正常へ戻らない。
        """
        for reason in ("missing", "hist", "month"):
            block = material()
            if reason == "missing": block["補助足"][-1]["missing"] = 1
            elif reason == "hist": block["補助足"][-1]["macd_hist"] = None
            else: block["商品照合"] = False
            result = I.select(block, SESSION)
            self.assertEqual([len(result["signals"]["3分_"+p]) for p in I.POLICIES], [1, 0, 0])
            self.assertIsNotNone(result["decisions"][0]["補助参照"])

    def test_局所窓最速20とNP番号欠と場リセット(self) -> None:
        """MACD数値carryと当場公開OLS窓を別にする。

        引数: self(TestCase)は対象。
        返り値: None。未準備と当場現前の出典を確認する。
        """
        rows = [auxiliary(i) for i in range(23)]
        panels = I.auxiliary_panels(rows, SESSION)
        self.assertFalse(panels[18]["補助数値準備"]); self.assertTrue(panels[19]["補助数値準備"])
        self.assertEqual(panels[19]["OLS20傾き"], I.exact(Fraction(1, 2)))
        for reason in ("publish", "missing", "gap"):
            bad = deepcopy(rows)
            if reason == "publish": bad[-2]["publish"] = False
            elif reason == "missing": bad[-2]["missing"] = 1
            else: bad[-1]["index"] += 1
            self.assertFalse(I.auxiliary_panels(bad, SESSION)[-1]["補助数値準備"])
        self.assertFalse(I.auxiliary_panels(rows[-2:], SESSION)[0]["補助数値準備"])
        rows[-1]["confirm"] = 3000.
        with self.assertRaises(ValueError): I.auxiliary_panels(rows, SESSION)

    def test_純13と旧全j採用集合のstrict対応(self) -> None:
        """TOPIX診断や未来labelをliveへ入れず旧不採用を救済しない。

        引数: self(TestCase)は対象。
        返り値: None。T/R/WAITの基準同値と改変拒否を確認する。
        """
        for kind in ("T", "R", "WAIT"):
            block = material(kind); original = deepcopy(block["signals"]["3分_A0"])
            block["旧j判定"][0]["将来ラベル"] = "毒値"
            result = I.select(block, SESSION)
            self.assertEqual(result["signals"]["3分_X0"], [I.pure_signal(r) for r in original])
            self.assertTrue(all(set(row) == set(I.SIGNAL_FIELDS) for rows in result["signals"].values() for row in rows))
            self.assertEqual(set(result["metadata"]), {row["イベントID"] for row in original})
        block = material(); block["signals"]["3分_A0"] = []
        with self.assertRaises(ValueError): I.select(block, SESSION)


class TOPIX数値銀行検証(unittest.TestCase):
    """固定29数値の限定再用と予約指紋の接続を検査する。"""

    def test_中心化H同限月carryと契約尾部resetを公開窓と区別(self) -> None:
        """新しいOP/数量指標を数値gateへ加えない。

        引数: self(TestCase)は対象。
        返り値: None。完全NP内部更新と17列射影を検査する。
        """
        frames = [H.frame(i, 200.+i*0.5, high=201.+i*0.5, low=199.+i*0.5, open=200.+i*0.5) for i in range(40)]
        frames[-1]["publish"] = False
        bank = J.AuxiliaryBank(); rows, quality = bank.build(frames, SESSION, ("TPI12",))
        self.assertTrue(all(set(row) == set(J.AUX_FIELDS) for row in rows))
        self.assertEqual(quality["非公開価格数値更新数"], 1)
        next_frames = [H.frame(i, 220.+i*0.5, high=221.+i*0.5, low=219.+i*0.5, open=220.+i*0.5) for i in range(2)]
        following, _ = bank.build(next_frames, SESSION, ("TPI12",))
        self.assertIsNotNone(following[0]["macd_hist"])
        self.assertFalse(I.auxiliary_panels(following, SESSION)[-1]["補助数値準備"])
        reset, _ = bank.build(next_frames, SESSION, ("TPI03",))
        self.assertIsNone(reset[0]["macd_hist"])
        bank.build(frames, SESSION, ("TPI03",), tail_missing=1)
        reset, _ = bank.build(next_frames, SESSION, ("TPI03",))
        self.assertIsNone(reset[0]["macd_hist"])
        bad = deepcopy(next_frames); bad[0]["end"] -= 1
        with self.assertRaises(ValueError): bank.build(bad, SESSION, ("TPI03",))

    def test_build_auxは予約指紋と年月を検査しBBO不正常eventを足入力から除かない(self) -> None:
        """予約外列挙をせず、Last数値と約定可能BBOを別にする。

        引数: self(TestCase)は対象。
        返り値: None。人工2場だけでbuild_auxと品質sinkを接続する。
        """
        with tempfile.TemporaryDirectory(prefix="TOPIX補助44合成_", dir=ROOT/"work") as temporary:
            folder = Path(temporary); entries = []
            for name in ("2026-09-22_Day", "2026-09-22_Night"):
                source = folder/"TOPIX"/name/"source.bin"; source.parent.mkdir(parents=True); source.write_bytes(b"artificial")
                cache = folder/(name+".bin"); cache.write_bytes(b"artificial-cache")
                stat = source.stat()
                entries.append({"symbol": "TOPIX", "session": name, "source_path": source.relative_to(folder).as_posix(),
                    "cache_path": cache.name, "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns,
                    "sha256_cache": sha(cache), "sha256_uncompressed": "人工展開SHA", "in_session_contract_codes": ["TPI12"],
                    "限月年月": "2026-12", "場内限月年月": ["2026-12"]})
            manifest = {"source_root": str(folder), "cache_base": str(folder), "entries": entries}
            times = tuple(SimpleNamespace(timestamp=lambda v=v: v) for v in (0., 10000., 9000., 9500.))
            event = SimpleNamespace(now=1., valid=False, last=200.)
            forms = [[H.frame(i, 200.+i*0.5, high=201.+i*0.5, low=199.+i*0.5, open=200.+i*0.5) for i in range(40)] for _ in entries]
            quality = {}
            with patch.object(J.W.OLD.shared.legacy, "session_times", return_value=times), patch.object(J.W.PREP, "read_events", return_value=[event]), \
                    patch.object(J.W, "bars_from_events", side_effect=forms) as bars:
                result = J.build_aux(manifest, quality)
            self.assertEqual(list(result), [e["session"] for e in entries])
            self.assertEqual(bars.call_args_list[0].args[0], [event])
            self.assertTrue(all(q["全足SHA256"] == J.canonical_sha(result[s]) for s, q in quality.items()))
            entries[0]["sha256_cache"] = "0"*64
            with patch.object(J.W.PREP, "read_events", side_effect=AssertionError("指紋差後は読まない")):
                with self.assertRaises(ValueError): J.build_aux(manifest)

    def test_独立補助panelとselectの全dict一致(self) -> None:
        """独立実装完成前だけ明示skipとする。

        引数: self(TestCase)は対象。
        返り値: None。主数値/入口をimportしない独立核を照合する。
        """
        path = HERE/"状態独立確認.py"
        if not path.exists(): self.skipTest("独立API完成前")
        independent = load(path, "TOPIX44人工独立")
        if not all(hasattr(independent, name) for name in ("auxiliary_panels", "select")): self.skipTest("独立API完成前")
        for kind in ("T", "R", "WAIT"):
            block = material(kind)
            self.assertEqual(I.auxiliary_panels(block["補助足"], SESSION), independent.auxiliary_panels(block["補助足"], SESSION))
            a, b = I.select(deepcopy(block), SESSION), independent.select(deepcopy(block), SESSION)
            for key in ("signals", "decisions", "aux_panels", "quality", "metadata"): self.assertEqual(a[key], b[key])

    def test_独立MACD銀行の原OHLC別算と公開判断を分けて照合(self) -> None:
        """Hの許容数値差をOLS/出典/準備/方向の許容へ広げない。

        引数: self(TestCase)は対象。
        返り値: None。人工のcarry/NP/契約解除で17列と判断を比較する。
        """
        path = HERE/"状態独立確認.py"
        if not path.exists(): self.skipTest("独立数値API完成前")
        independent = load(path, "TOPIX44人工独立銀行")
        if not hasattr(independent, "AuxiliaryHistory"): self.skipTest("独立数値API完成前")
        main_bank, separate_bank = J.AuxiliaryBank(), independent.AuxiliaryHistory()
        for contract, tail in ((("TPI12",), 0), (("TPI12",), 1), (("TPI03",), 0)):
            frames = []
            for i in range(60):
                c = 200.+((i*7)%19)*0.5
                frames.append(H.frame(i, c, high=c+1., low=c-1., open=c))
            frames[-1]["publish"] = False
            a, aq = main_bank.build(frames, SESSION, contract, tail)
            b, bq = separate_bank.build(frames, SESSION, contract, tail)
            for x, y in zip(a, b):
                self.assertEqual({k:v for k,v in x.items() if k != "macd_hist"}, {k:v for k,v in y.items() if k != "macd_hist"})
                if x["macd_hist"] is None: self.assertIsNone(y["macd_hist"])
                else: self.assertAlmostEqual(x["macd_hist"], y["macd_hist"], delta=1e-10)
            self.assertEqual({k:v for k,v in aq.items() if k != "全足SHA256"}, {k:v for k,v in bq.items() if k != "全足SHA256"})
            self.assertEqual(aq["全足SHA256"], J.canonical_sha(a)); self.assertEqual(bq["全足SHA256"], independent.canonical_sha(b))
            left, right = I.auxiliary_panels(a, SESSION), independent.auxiliary_panels(b, SESSION)
            for x, y in zip(left, right):
                self.assertEqual(x["補助数値準備"], y["補助数値準備"])
                self.assertEqual(x["OLS20傾き"], y["OLS20傾き"])
                u, v = x["MACDヒスト変化"], y["MACDヒスト変化"]
                self.assertEqual((u > 0)-(u < 0) if u is not None else None, (v > 0)-(v < 0) if v is not None else None)


def driver_module() -> Any:
    """現主CLIの定義だけを市場遮断下で読む。

    引数: なし。
    返り値: Anyは新主モジュール。
    """
    return load(HERE/"検証.py", "TOPIX44人工主")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """二商品とも人工の束と、四参照用の小型一時先を作る。

    引数: driver(Any)は主、count(int)は場数。
    返り値: Iterator[Any]は主契約のstudy/work/manifest/bundle/build。実原板を開かない。
    """
    with tempfile.TemporaryDirectory(prefix="TOPIX補助44合成_", dir=ROOT/"work") as temporary:
        folder = Path(temporary); study, work = folder/"study", folder/"work"
        study.mkdir(); work.mkdir()
        config = driver.expected_config(); driver.W.write_json(study/"条件.json", config)
        for name in ("入口参照.json", "対照参照.json", "指標参照.json", "入力台帳.json"):
            driver.W.write_json(study/name, {"人工": True})
        (study/"計画.md").write_text("人工二商品比較\n", encoding="utf-8")
        driver.W.write_json(work/"診断予定.json", {"人工": True})
        tpi_ref = {"原板複製": False}
        for name in ("入力台帳", "入力監査", "入力予約"):
            path = work/("TOPIX"+name+".json")
            driver.W.write_json(path, {"人工": True})
            tpi_ref[name] = {"パス": path.relative_to(ROOT).as_posix(), "SHA256": sha(path)}
        driver.W.write_json(study/"TOPIX入力参照.json", tpi_ref)
        sessions = [str(date(2026, 9, 22)+timedelta(days=i//2))+("_Day" if i%2 == 0 else "_Night") for i in range(count)]
        bundle = {"pure": {}, "metadata": {}, "old_decisions": {}, "lower": {}, "auxiliary": {}, "商品照合": {}}
        for name in sessions:
            block = material("R", session=name)
            bundle["pure"][name] = block["signals"]["3分_A0"]
            bundle["old_decisions"][name] = block["旧j判定"]
            bundle["lower"][name] = block["frames"][3]
            bundle["auxiliary"][name] = block["補助足"]
            bundle["商品照合"][name] = True
            for row in block["旧j判定"]:
                if row["戦略判定"]["A0"]["採用"]:
                    bundle["metadata"][row["発動ID"]+"_A0"] = {"元登録ID": row["登録ID"], "元価格side": row["元価格side"],
                        "元登録時計秒": row["登録参照"]["登録足"]["confirm"], "元登録原板行": row["登録参照"]["登録足"]["confirm_line"], "判別種別": row["構造区分"]}

        def built(entry: dict, manifest: dict, shared: dict, current: dict, include_events: bool = False) -> dict:
            """新selectを通し、正式時だけNK人工BBOを渡す。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式フラグ。
            返り値: dictは三純/全補助panel/人工気配。
            """
            name = entry["session"]
            block = {"場": name, "signals": {"3分_A0": deepcopy(shared["pure"][name])}, "旧j判定": deepcopy(shared["old_decisions"][name]),
                "frames": {3: deepcopy(shared["lower"][name])}, "補助足": deepcopy(shared["auxiliary"][name]), "商品照合": shared["商品照合"][name]}
            driver.I.select(block, name)
            block.update(input_quality=deepcopy(block["quality"]), events=[], cutoff=9000., deadline=9500., duration=10000./60)
            if include_events:
                block["events"] = [H.S37.quote(t, i+1, -1, price) for i, (t, price) in enumerate(
                    [(4142.,-5.),(4143.,-5.),(4144.,15.),(4145.,0.),(4146.,-5.)])]
            return block

        yield SimpleNamespace(study=study, work=work, config=config, bundle=bundle, built=built,
            manifest={"source_root": "人工予約だけ", "entries": [{"session": name} for name in sessions]},
            ref={"文書と証明": {}, "共有明細": []}, tpi_ref=tpi_ref)


class 主接続検証(unittest.TestCase):
    """新二商品束と非損益準備/同一NK運用を人工で接続する。"""

    def test_人工read_bundle245純424jと補助数値を分ける(self) -> None:
        """旧caseを即13列へ写し、TOPIX数量を新判断へ渡さない。

        引数: self(TestCase)は対象。
        返り値: None。主の固定件数guardとJ呼出しを検査する。
        """
        driver = driver_module(); block = material("R")
        signal = block["signals"]["3分_A0"][0]
        meta = {"元登録ID": "人工親", "元価格side": 1, "元登録時計秒": 3780., "元登録原板行": 21, "判別種別": "R"}
        cases = [{**deepcopy(signal), **meta, "イベントID": f"人工{i}_A0", "ラベル": "毒値"} for i in range(245)]
        contexts = [{**deepcopy(block["旧j判定"][0]), "期間": "学習"} for _ in range(424)]
        streams = {"入口事例.jsonl.gz": cases, "発動判定.jsonl.gz": contexts, "全指標.jsonl.gz": block["frames"][3]}
        manifest = {"entries": [{"session": SESSION, "限月年月": "2026-12"}]}
        with patch.object(driver, "validate_reference", return_value={}), patch.object(driver, "shared_path", side_effect=lambda ref, name: Path(name)), \
                patch.object(driver, "read_rows", side_effect=lambda path: deepcopy(streams[path.name])), \
                patch.object(driver, "auxiliary_manifest", return_value=manifest), patch.object(driver.AUX, "build_aux", return_value={SESSION: block["補助足"]}) as build:
            bundle = driver.read_bundle(driver.STUDY)
        self.assertEqual(sum(map(len, bundle["pure"].values())), 245)
        self.assertEqual(sum(map(len, bundle["old_decisions"].values())), 424)
        self.assertEqual(set(bundle["pure"][SESSION][0]), set(I.SIGNAL_FIELDS)); build.assert_called_once_with(manifest)
        self.assertEqual(bundle["auxiliary"][SESSION], block["補助足"])

    def test_実buildはX純を二重変換せずprepareでNK気配を読まない(self) -> None:
        """補助数値はbundle済み、準備で新規BBO/先着へ進まない。

        引数: self(TestCase)は対象。
        返り値: None。人工source/cacheだけで非空X三案を作る。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            source, cache = f.study.parent/"NKsource.bin", f.study.parent/"NKcache.bin"
            source.write_bytes(b"artificial"); cache.write_bytes(b"artificial-cache")
            stat = source.stat(); name = f.manifest["entries"][0]["session"]
            entry = {"session": name, "source_path": source.name, "cache_path": os.path.relpath(cache, ROOT/"work/複合検証"),
                "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns, "sha256_cache": sha(cache)}
            times = tuple(SimpleNamespace(timestamp=lambda v=v: v) for v in (0., 10000., 9000., 9500.))
            with patch.object(driver.W.OLD.shared.legacy, "session_times", return_value=times), \
                    patch.object(driver.W.PREP, "read_events", side_effect=AssertionError("準備でNK気配を読まない")):
                block = driver.build_session(entry, {"source_root": str(source.parent)}, f.bundle, f.config, False)
            self.assertEqual([len(block["signals"]["3分_"+p]) for p in I.POLICIES], [1, 1, 1])
            self.assertEqual(block["events"], [])

    def test_CLI人工66準備は両指標判定だけで先着運用成績禁止(self) -> None:
        """TOPIXとNKの投影hashを保存し、旧label/台帳再読はしない。

        引数: self(TestCase)は対象。
        返り値: None。実際のprepare CLIを人工66場で検査する。
        """
        driver = driver_module()
        with artificial_driver(driver, 66) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", return_value=f.ref), patch.object(driver, "auxiliary_manifest", return_value={}), \
                patch.object(driver, "read_bundle", return_value=f.bundle), patch.object(driver, "build_session", side_effect=f.built), \
                patch.object(driver, "freeze", side_effect=AssertionError("準備で固定禁止")), patch.object(driver, "read_rows", side_effect=AssertionError("準備で旧label禁止")), \
                patch.object(driver.W.OLD, "気配経路", side_effect=AssertionError("準備で先着禁止")), patch.object(driver.ENGINE, "replay", side_effect=AssertionError("準備で運用禁止")), \
                patch.object(driver.E, "entry_metrics", side_effect=AssertionError("準備で入口成績禁止")), patch.object(driver.S, "operation_metrics", side_effect=AssertionError("準備で損益禁止")), \
                patch.object(sys, "argv", [str(HERE/"検証.py"), "--prepare", "--study", str(f.study), "--work", str(f.work)]), redirect_stdout(io.StringIO()):
            driver.main()
            prepared = driver.W.read_json(f.work/"準備点検.json")
            self.assertFalse(prepared["ラベル計算"]); self.assertFalse(prepared["損益計算"])
            self.assertEqual(len(prepared["準備"]), 66); self.assertTrue(prepared["旧A0純登録同値"])
            for row in prepared["準備"]:
                self.assertEqual(row["TOPIX足数"], 23); self.assertEqual(row["補助判定足数"], 23)
                self.assertIn("全TOPIX投影SHA256", row); self.assertIn("全補助判定SHA256", row)
            definition_path = f.work/"TOPIX数値定義.jsonl.gz"
            with driver.gzip.open(definition_path, "rt", encoding="utf-8") as stream:
                definitions = [json.loads(line) for line in stream]
            expected_definitions = [{key: row[key] for key in ("場", "index", "macd_hist")}
                for values in f.bundle["auxiliary"].values() for row in values]
            self.assertEqual(definitions, expected_definitions)
            self.assertEqual(prepared["TOPIX数値定義"], {"パス": definition_path.relative_to(ROOT).as_posix(),
                "圧縮SHA256参考": sha(definition_path), "展開内容SHA256": driver.content_sha(definition_path), "行数": 66*23})
            with self.assertRaises(ValueError): driver.run(f.study, f.work, True)
            self.assertFalse(any((f.work/name).exists() for name in driver.FILES))

    def test_人工正式三先着三運用旧A0対照と5gzip六役割を保存(self) -> None:
        """売買はNKだけで、TOPIX更新から返済条件を追加しない。

        引数: self(TestCase)は対象。
        返り値: None。人工NK気配で新主の正式末尾まで接続する。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            with patch.object(driver, "manifest_for", return_value=f.manifest), patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "auxiliary_manifest", return_value={}), patch.object(driver, "read_bundle", return_value=f.bundle), \
                    patch.object(driver, "build_session", side_effect=f.built), redirect_stdout(io.StringIO()):
                driver.run(f.study, f.work, True)
            definition_path = f.work/"TOPIX数値定義.jsonl.gz"
            definition_sha = sha(definition_path)
            entry = f.manifest["entries"][0]; name = entry["session"]
            block = f.built(entry, f.manifest, f.bundle, f.config, True)
            old_signal = f.bundle["pure"][name][0]
            old_state, old_info = H.H.O.replay(block["events"], [old_signal], block["frames"][3], name,
                "3分_A0_XF", f.config["運用"], {"出口ID": "XF"}, "切替", H.BOUNDS)
            old_info.update(期間="学習", 場時間分=block["duration"])
            for row in old_state.trades: row["期間"] = "学習"
            detail = {"候補ID": "3分_A0_XF", "場": name, "品質": old_info, "約定": old_state.fills,
                "取引": old_state.trades, "注文": old_state.orders, "入口取扱": old_state.signals}
            logs = [{"期間": "学習", **r} for r in old_state.normal_log]
            label = dict(zip(driver.LABEL_FIELDS, ["逆行先着", "人工", 1005., 4143., 2, 4146., 5, 1010., 20., 5., 0.05]))
            streams = {"入口事例.jsonl.gz": [{**old_signal, **label}], "全運用詳細.jsonl.gz": [detail], "追尾.jsonl.gz": logs}
            replay = driver.ENGINE.replay

            def operation(*args: object) -> tuple:
                """人工時計の固定範囲で新wrapperを呼ぶ。

                引数: args(object)は主の運用引数。
                返り値: tupleはNK人工状態/品質。
                """
                return replay(*args, bounds=H.BOUNDS)

            def publish(study: Path, path: Path, ids: list[str], manifest: dict, suffix: str) -> None:
                """Viewer公開を小型人工一覧へ差替える。

                引数: study/path(Path)は先、ids(list[str])/manifest(dict)/suffix(str)は元契約。
                返り値: None。実資料を開かない。
                """
                driver.W.write_json(study/"一覧.resources.json", {"resources": [{"id": "00008_人工"}]})

            with patch.object(driver, "manifest_for", return_value=f.manifest), patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "auxiliary_manifest", return_value={}), patch.object(driver, "read_bundle", return_value=f.bundle), \
                    patch.object(driver, "build_session", side_effect=f.built), patch.object(driver, "freeze", return_value={}), \
                    patch.object(driver, "shared_path", side_effect=lambda ref, n: Path(n)), patch.object(driver, "read_rows", side_effect=lambda p: deepcopy(streams[p.name])), \
                    patch.object(driver.W.OLD, "気配経路", return_value=SimpleNamespace(evaluate=lambda *a, **k: deepcopy(label))), \
                    patch.object(driver.ENGINE, "replay", side_effect=operation), patch.object(driver.E, "publish_details", side_effect=publish), redirect_stdout(io.StringIO()):
                report = driver.run(f.study, f.work, False)
            self.assertEqual(report["入口評価数"], 3)
            self.assertEqual(len(driver.W.read_json(f.study/"結果.json")["役割別入口評価"]), 6)
            self.assertEqual(len(driver.W.read_json(f.study/"作業成果物.json")["ファイル"]), 5)
            self.assertEqual(sha(definition_path), definition_sha)
            self.assertNotIn("TOPIX数値定義.jsonl.gz", driver.FILES)
            control = driver.W.read_json(f.study/"X0対照同値.json")
            self.assertTrue(control["全件一致"]); self.assertTrue(control["旧先着全件同値"])
            with driver.gzip.open(f.work/"入口事例.jsonl.gz", "rt", encoding="utf-8") as stream: cases = [json.loads(row) for row in stream]
            self.assertEqual(len(cases), 3)
            for row in cases: self.assertEqual({k: row[k] for k in driver.LABEL_FIELDS}, label)

    def test_TOPIX四SHA参照は成功監査と予約台帳と現在出典をjoinする(self) -> None:
        """同66場でも別の成功proofを混ぜた自己整合pointerを拒否する。

        引数: self(TestCase)は対象。
        返り値: None。実入力は開かず、44work内の一時JSONだけを使う。
        """
        driver = driver_module()
        driver.WORK.mkdir(parents=True, exist_ok=True)
        with artificial_driver(driver, 1) as f, tempfile.TemporaryDirectory(prefix="人工参照44_", dir=driver.WORK) as temporary:
            folder = Path(temporary)
            sessions = [r["session"] for r in driver.W.read_json(driver.MANIFEST_PATH)["entries"]]
            manifest = {"entries": [{"symbol": "TOPIX", "session": name, "限月年月": "2026-12"} for name in sessions]}
            paths = {name: folder/(name+".json") for name in ("入力台帳", "入力監査", "入力予約")}
            driver.W.write_json(paths["入力台帳"], manifest); driver.W.write_json(paths["入力予約"], {"人工": True})
            dep = ROOT/"scripts/OBV反転/指標.py"
            proof = {"全件一致": True, "不一致数": 0, "不一致": [], "入力台帳SHA256": sha(paths["入力台帳"]),
                "入力予約SHA256": sha(paths["入力予約"]), "出典SHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}

            def refresh(current: dict, input_manifest: dict | None = None) -> dict:
                """人工監査と参照宣言のSHAだけを現在バイトへ更新する。

                引数: current(dict)は監査、input_manifest(dict|None)は任意の変更台帳。
                返り値: dictは三ファイルと複製falseの参照。
                """
                if input_manifest is not None: driver.W.write_json(paths["入力台帳"], input_manifest)
                driver.W.write_json(paths["入力監査"], current)
                ref = {"原板複製": False, **{name: {"パス": path.relative_to(ROOT).as_posix(), "SHA256": sha(path)} for name, path in paths.items()}}
                driver.W.write_json(f.study/"TOPIX入力参照.json", ref)
                return ref

            ref = refresh(proof)
            self.assertEqual(driver.auxiliary_manifest(f.study), manifest)
            for key in ref:
                wrong = deepcopy(ref); wrong.pop(key); driver.W.write_json(f.study/"TOPIX入力参照.json", wrong)
                with self.assertRaises(ValueError): driver.auxiliary_manifest(f.study)
            for key in ("全件一致", "不一致数", "不一致", "入力台帳SHA256", "入力予約SHA256", "出典SHA256"):
                wrong = deepcopy(proof)
                wrong[key] = False if key == "全件一致" else 1 if key == "不一致数" else ["差"] if key == "不一致" else {} if key == "出典SHA256" else "0"*64
                refresh(wrong)
                with self.assertRaises(ValueError): driver.auxiliary_manifest(f.study)
            wrong = deepcopy(proof); wrong["出典SHA256"][dep.relative_to(ROOT).as_posix()] = "0"*64
            refresh(wrong)
            with self.assertRaises(ValueError): driver.auxiliary_manifest(f.study)
            for kind in ("missing", "symbol", "month"):
                changed = deepcopy(manifest)
                if kind == "missing": changed["entries"].pop()
                elif kind == "symbol": changed["entries"][0]["symbol"] = "NK225"
                else: changed["entries"][0]["限月年月"] = "2027-03"
                driver.W.write_json(paths["入力台帳"], changed)
                new_proof = deepcopy(proof); new_proof["入力台帳SHA256"] = sha(paths["入力台帳"])
                refresh(new_proof)
                with self.assertRaises(ValueError): driver.auxiliary_manifest(f.study)

    def test_条件drift_partial_実行中code差を保存前に拒否(self) -> None:
        """未完了正式明細や実行中版変更を続行/上書きしない。

        引数: self(TestCase)は対象。
        返り値: None。人工入力の外には書き込まない。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            wrong = deepcopy(f.config); wrong["TOPIX補助"]["X2"] = "結果後緩和"
            with self.assertRaises(ValueError): driver.validate_config(wrong)
            (f.work/driver.FILES[0]).write_bytes(b"artificial-partial")
            with patch.object(driver, "manifest_for", return_value=f.manifest), patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "read_bundle", side_effect=AssertionError("partial後に読まない")):
                with self.assertRaises(ValueError): driver.run(f.study, f.work, False)
            initial = driver.current_bindings(f.study); changed = deepcopy(initial); changed["TOPIX入力監査SHA256"] = "0"*64
            with patch.object(driver, "manifest_for", return_value=f.manifest), patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "read_bundle", return_value=f.bundle), patch.object(driver, "build_session", side_effect=f.built), \
                    patch.object(driver, "current_bindings", side_effect=[initial, changed]), redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError): driver.run(f.study, f.work, True)
            self.assertFalse((f.work/"準備点検.json").exists())

    def test_固定は二商品四参照主独立最終人工会計12の現在版joinを要求(self) -> None:
        """主4codeと合成自己/四参照/独立二codeの改変を固定前に止める。

        引数: self(TestCase)は対象。
        返り値: None。宣言用人工proofと人工一時固定だけを作り実入力へ触れない。
        """
        driver = driver_module()
        if not (HERE/"追尾独立確認.py").exists(): self.skipTest("独立二CLI完成前")
        with artificial_driver(driver, 1) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", return_value=f.ref), patch.object(driver, "auxiliary_manifest", return_value={}), \
                patch.object(driver, "read_bundle", return_value=f.bundle), patch.object(driver, "build_session", side_effect=f.built), redirect_stdout(io.StringIO()):
            driver.run(f.study, f.work, True)
            prepared = driver.W.read_json(f.work/"準備点検.json"); prepared["旧A0登録数"] = 245
            driver.W.write_json(f.work/"準備点検.json", prepared)
            dep = ROOT/"scripts/OBV反転/指標.py"
            finance_sources = ("scripts/TOPIX補助/独立監査.py", "scripts/TOPIX補助/運用.py", "work/TOPIX補助/00044/会計人工接続.py")
            if not all((ROOT/n).exists() for n in finance_sources): self.skipTest("財務人工のsource完成前")
            finance = {"全件一致": True, "不一致数": 0, "人工経路数": 12, "実行中code不変": True,
                "条件SHA256": sha(f.study/"条件.json"), "コードSHA256": {n: sha(ROOT/n) for n in finance_sources}}
            driver.W.write_json(f.work/"会計人工接続.json", finance)
            (f.work/"会計人工接続.py").write_bytes((ROOT/finance_sources[-1]).read_bytes())
            proof = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
                "主準備SHA256": sha(f.work/"準備点検.json"), "主コードSHA256": driver.code_pins(),
                "条件SHA256": sha(f.study/"条件.json"), "入力台帳SHA256": sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256": sha(driver.MANIFEST_PATH),
                **{n[:-5]+"SHA256": sha(f.study/n) for n in ("入口参照.json", "対照参照.json", "指標参照.json", "TOPIX入力参照.json")},
                "コードSHA256": sha(HERE/"状態独立確認.py"), "追尾コードSHA256": sha(HERE/"追尾独立確認.py"),
                "依存コードSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
            synthetic = {"全件成功": True, "合成編集終了": False, "実行中code不変": True,
                "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in
                    [HERE/n for n in ("検証.py", "入口.py", "指標.py", "運用.py", "合成検証.py")]+[f.study/"条件.json"]},
                "独立数値補助SHA256": sha(HERE/"状態独立確認.py"), "独立追尾補助SHA256": sha(HERE/"追尾独立確認.py")}
            synthetic_file, independent = f.work/"人工最終合成.json", f.work/"独立準備点検.json"
            driver.W.write_json(synthetic_file, synthetic)
            actual_read, actual_sha = driver.W.read_json, driver.O.sha

            def read_json(path: Path) -> dict:
                """直前固定集合と最終人工だけを一時宣言へ置換する。

                引数: path(Path)は小型出典。
                返り値: dictは人工又は実小型JSON。
                """
                if normalized(path) == normalized(driver.PREVIOUS/"固定.json"):
                    return {"ファイルSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
                return deepcopy(synthetic) if normalized(path) == normalized(WORK/"合成検証.json") else actual_read(path)

            def current_sha(path: Path) -> str:
                """最終人工の実パスを人工証明の指紋へ写す。

                引数: path(Path)は先。
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
                for key in ("全件成功", "合成編集終了", "実行中code不変", "独立数値補助SHA256", "独立追尾補助SHA256"):
                    old = synthetic[key]; synthetic[key] = False if isinstance(old, bool) else "0"*64
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                    synthetic[key] = old
                for path in synthetic["ファイルSHA256"]:
                    old = synthetic["ファイルSHA256"][path]; synthetic["ファイルSHA256"][path] = "0"*64
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                    synthetic["ファイルSHA256"][path] = old
                for key in prepared["TOPIX数値定義"]:
                    wrong = deepcopy(prepared)
                    wrong["TOPIX数値定義"][key] = -1 if key == "行数" else "不一致"
                    driver.W.write_json(f.work/"準備点検.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.work/"準備点検.json", prepared)
                for key in ("全件一致", "不一致数", "人工経路数", "実行中code不変", "条件SHA256", "コードSHA256"):
                    wrong = deepcopy(finance)
                    wrong[key] = False if isinstance(finance[key], bool) else {} if isinstance(finance[key], dict) else "0"*64 if key == "条件SHA256" else -1
                    driver.W.write_json(f.work/"会計人工接続.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                for source in finance_sources:
                    wrong = deepcopy(finance); wrong["コードSHA256"].pop(source)
                    driver.W.write_json(f.work/"会計人工接続.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.work/"会計人工接続.json", finance)
                driver.W.write_json(synthetic_file, synthetic)
                locked = driver.freeze(f.study, f.work)
                self.assertEqual(driver.freeze(f.study, f.work), locked)
                self.assertEqual(locked["独立準備SHA256"], sha(independent))
                definition_relative = (f.work/"TOPIX数値定義.jsonl.gz").relative_to(ROOT).as_posix()
                self.assertEqual(locked["ファイルSHA256"][definition_relative], sha(f.work/"TOPIX数値定義.jsonl.gz"))
                (f.study/"計画.md").write_text("人工固定後変更\n", encoding="utf-8")
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.study/"結果.json", {"人工": True})
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)


class 正本定義と独立生H検証(unittest.TestCase):
    """H表示誤差の許容と、準備・符号・採否・非Hの厳密性を分ける。"""

    def test_H微差だけを許し非H準備符号採否差を隠さない(self) -> None:
        """正本overlayは独立数値を上書きして正解化する経路ではない。

        引数: self(TestCase)は対象。
        返り値: None。独立生値を残した二経路を人工の一ULP差で検査する。
        """
        independent = load(HERE/"状態独立確認.py", "TOPIX44人工H定義独立")
        if not all(hasattr(independent, k) for k in ("define_rows", "compare_h_scope", "judgment_projection")):
            self.skipTest("二経路API完成前")
        block = material()
        main_rows = deepcopy(block["補助足"])
        for row in main_rows: row["macd_hist"] = row["index"]/32.
        values = {row["index"]: {k: row[k] for k in ("場", "index", "macd_hist")} for row in main_rows}
        raw = deepcopy(main_rows); raw[-1]["macd_hist"] = math.nextafter(raw[-1]["macd_hist"], math.inf)
        kept = deepcopy(raw)
        defined = independent.define_rows(raw, values, SESSION)
        self.assertEqual(raw, kept)
        self.assertEqual(defined, main_rows)
        self.assertNotEqual(I.canonical_sha(raw), I.canonical_sha(defined))
        audit = independent.Audit()
        self.assertTrue(independent.compare_h_scope("人工TOPIX全足", defined, raw, audit))
        main_block, raw_block = deepcopy(block), deepcopy(block)
        main_block["補助足"], raw_block["補助足"] = defined, raw
        source_selected = independent.select(main_block, SESSION)
        raw_selected = independent.select(raw_block, SESSION)
        for key in ("aux_panels", "decisions", "signals"):
            self.assertTrue(independent.compare_h_scope("人工"+key, source_selected[key], raw_selected[key], audit))
        self.assertEqual(audit.mismatches, 0)
        changed = deepcopy(raw); changed[-1]["macd_hist"] += 1e-8
        too_large = independent.Audit()
        independent.compare_h_scope("許容超過", defined, changed, too_large)
        self.assertGreater(too_large.mismatches, 0)
        for field in ("close", "confirm_line"):
            changed = deepcopy(raw)
            changed[-1][field] = math.nextafter(changed[-1][field], math.inf) if field == "close" else changed[-1][field]+1
            wrong_definition = independent.define_rows(changed, values, SESSION)
            self.assertNotEqual(I.canonical_sha(wrong_definition), I.canonical_sha(main_rows))
            failed = independent.Audit()
            self.assertFalse(independent.compare_h_scope("非H厳密", main_rows, changed, failed))
            self.assertGreater(failed.mismatches, 0)
        crossed = deepcopy(main_rows)
        main_cross = deepcopy(main_rows)
        main_cross[-2]["macd_hist"] = crossed[-2]["macd_hist"] = .5
        main_cross[-1]["macd_hist"] = math.nextafter(.5, math.inf)
        crossed[-1]["macd_hist"] = math.nextafter(.5, -math.inf)
        first, second = deepcopy(block), deepcopy(block)
        first["補助足"], second["補助足"] = main_cross, crossed
        a, b = independent.select(first, SESSION), independent.select(second, SESSION)
        self.assertTrue(a["decisions"][0]["戦略判定"]["X2"]["採用"])
        self.assertFalse(b["decisions"][0]["戦略判定"]["X2"]["採用"])
        failed = independent.Audit()
        self.assertFalse(independent.compare_h_scope("差符号反転", a["decisions"], b["decisions"], failed))
        self.assertGreater(failed.mismatches, 0)
        for left, right in ((1e-16, -1e-16), (None, 0.)):
            failed = independent.Audit()
            self.assertFalse(independent.compare_h_scope("H符号又は有限準備", {"macd_hist": left}, {"macd_hist": right}, failed))
            self.assertGreater(failed.mismatches, 0)
        changed_decision = deepcopy(source_selected["decisions"])
        changed_decision[0]["戦略判定"]["X2"]["採用"] = not changed_decision[0]["戦略判定"]["X2"]["採用"]
        failed = independent.Audit()
        self.assertFalse(independent.compare_h_scope("全採否厳密", source_selected["decisions"], changed_decision, failed))
        self.assertGreater(failed.mismatches, 0)
        missing = deepcopy(values); missing.pop(next(iter(missing)))
        with self.assertRaises(ValueError): independent.define_rows(raw, missing, SESSION)
        wrong = deepcopy(values); wrong[next(iter(wrong))]["場"] = "別場"
        with self.assertRaises(ValueError): independent.define_rows(raw, wrong, SESSION)

    def test_小型3列定義は構造一意順序全足数と4metadataを照合(self) -> None:
        """正本値の定義入力を、未来labelや任意の別sourceへ拡張させない。

        引数: self(TestCase)は対象。
        返り値: None。人工gzipだけで定義readerの全guardを確認する。
        """
        independent = load(HERE/"状態独立確認.py", "TOPIX44人工定義読取独立")
        if not hasattr(independent, "read_definition"): self.skipTest("定義reader完成前")
        driver = driver_module()
        with tempfile.TemporaryDirectory(prefix="TOPIX補助44合成_", dir=ROOT/"work") as temporary:
            work = Path(temporary); path = work/"TOPIX数値定義.jsonl.gz"
            rows = [{"場": SESSION, "index": 0, "macd_hist": None}, {"場": SESSION, "index": 1, "macd_hist": .5}]

            def saved(values: list[dict]) -> dict:
                """人工の定義だけをgzipへ保存し、現在のmetadataを返す。

                引数: values(list[dict])は人工3列。
                返り値: dictは主prepare同型の小型定義参照。
                """
                with driver.compressed(path) as stream:
                    for row in values: stream.write(driver.D.encode(row))
                return {"TOPIX数値定義": {"パス": path.relative_to(ROOT).as_posix(), "圧縮SHA256参考": sha(path),
                    "展開内容SHA256": driver.content_sha(path), "行数": len(values)}, "準備": [{"場": SESSION, "TOPIX足数": len(rows)}]}

            master = saved(rows)
            actual = independent.read_definition(work, master, independent.Audit())
            self.assertEqual(actual, {SESSION: {row["index"]: row for row in rows}})
            for key in ("圧縮SHA256参考", "展開内容SHA256", "行数"):
                wrong = deepcopy(master); wrong["TOPIX数値定義"][key] = -1 if key == "行数" else "0"*64
                with self.assertRaises(ValueError): independent.read_definition(work, wrong, independent.Audit())
            for kind in ("extra", "duplicate", "reverse", "session", "count"):
                changed = deepcopy(rows)
                if kind == "extra": changed[0]["将来ラベル"] = "毒値"
                elif kind == "duplicate": changed[-1]["index"] = 0
                elif kind == "reverse": changed.reverse()
                elif kind == "session": changed[0]["場"] = "別場"
                else: changed.pop()
                changed_master = saved(changed)
                with self.assertRaises(ValueError): independent.read_definition(work, changed_master, independent.Audit())


def main() -> None:
    """人工だけを実行し、最終版起動はroot担当の許可契約に従う。

    引数: CLI --final(bool)は全停止後rootが一回だけ指定する。
    返り値: None。市場入力/先着/損益を起動しない。
    """
    parser = argparse.ArgumentParser(description="TOPIX補助の時計・数値・純入口の人工確認")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    paths = [HERE/n for n in ("検証.py", "入口.py", "指標.py", "運用.py", "合成検証.py")]
    paths.append(ROOT/"study/00044_TOPIX方向とNK再テスト/条件.json")
    paths = [p for p in paths if p.exists()]
    helpers = [p for p in (HERE/"状態独立確認.py", HERE/"追尾独立確認.py") if p.exists()]
    pins, before = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}, {p.relative_to(ROOT).as_posix(): sha(p) for p in helpers}
    with deny_market(): result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged = pins == {p.relative_to(ROOT).as_posix(): sha(p) for p in paths} and before == {p.relative_to(ROOT).as_posix(): sha(p) for p in helpers}
    success = result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    if args.final and (len(pins) != 6 or len(before) != 2): raise ValueError("主4code/条件/合成と独立二code完成前です")
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
        "実行中code不変": unchanged, "市場入力読取": False, "市場先着損益計算": False,
        "ファイルSHA256": pins, "独立数値補助SHA256": before.get("scripts/TOPIX補助/状態独立確認.py"),
        "独立追尾補助SHA256": before.get("scripts/TOPIX補助/追尾独立確認.py"),
        "skip数": len(result.skipped), "失敗数": len(result.failures), "エラー数": len(result.errors)}
    WORK.mkdir(parents=True, exist_ok=True)
    target = WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"出力": str(target), "全件成功": success, "件数": result.testsRun, "SHA256": sha(target)}, ensure_ascii=False))
    if not success: raise SystemExit(1)


if __name__ == "__main__": main()
