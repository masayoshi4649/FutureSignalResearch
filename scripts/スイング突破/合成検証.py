"""実市場を遮断して確定スイング・DI・Fastと主接続を人工検査する。"""

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
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
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HERE, WORK = Path(__file__).resolve().parent, ROOT/"work/スイング突破"
SESSION = "人工スイング場"


def normalized(path: object) -> str:
    """市場遮断用に絶対パスを正規化する。

    引数: path(object)はパス又は非パス値。
    返り値: strは正規パス、非パスなら空文字。
    """
    try: return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError): return ""


@contextmanager
def deny_market():
    """原板と実cache/圧縮明細のopen/statを拒否する。

    引数: なし。
    返り値: contextmanagerは人工一時先とコード/小証明だけを許可する。
    """
    raw, work = normalized(ROOT.parent/"JP_OSE_Data"), normalized(ROOT/"work")
    opened, path_opened, stated = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """原板/実cache/実圧縮明細のアクセスを止める。

        引数: path(object)はアクセス先。
        返り値: None。人工一時先のprefixだけ例外にする。
        """
        name = normalized(path)
        inside = name.startswith(work+os.sep)
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith(os.path.normcase("スイング45合成_"))
        if name == raw or name.startswith(raw+os.sep) or inside and not artificial and name.endswith((".npz", ".jsonl.gz", ".trades.jsonl")):
            raise AssertionError("実市場資料を人工から読まない:"+str(path))

    def safe_open(path: object, *args, **kwargs):
        """通常openへ遮断を適用する。

        引数: path(object)とargs/kwargsは元open引数。
        返り値: objectは許可されたファイル。
        """
        check(path); return opened(path, *args, **kwargs)

    def safe_path_open(path: Path, *args, **kwargs):
        """Path.openへ遮断を適用する。

        引数: path(Path)とargs/kwargsは元open引数。
        返り値: objectは許可されたファイル。
        """
        check(path); return path_opened(path, *args, **kwargs)

    def safe_stat(path: Path, *args, **kwargs):
        """Path.statへ遮断を適用する。

        引数: path(Path)とargs/kwargsは元stat引数。
        返り値: objectは許可されたstat。
        """
        check(path); return stated(path, *args, **kwargs)

    with patch.object(builtins, "open", safe_open), patch.object(Path, "open", safe_path_open), patch.object(Path, "stat", safe_stat):
        yield


def load(path: Path, name: str):
    """CLIを実行せずコード定義を読む。

    引数: path(Path)はコード、name(str)はモジュール識別。
    返り値: moduleは読み込んだ定義。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec); sys.modules[name] = value
        spec.loader.exec_module(value)
        return value


def sha(path: Path) -> str:
    """コード又は小型人工証明の指紋を返す。

    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


J, I = load(HERE/"指標.py", "スイング45人工数値"), load(HERE/"入口.py", "スイング45人工入口")
CONFIG = {"残り時間下限分": 60, "確認遅延上限秒": 30}


def frame(index: int, close: float, high: float | None = None, low: float | None = None,
          session: str = SESSION, **changes) -> dict:
    """一意の公開keyを持つ人工完全3分足を作る。

    引数: index(int)は足番号、close/high/low(float|None)は値、session(str)は場、changesは置換列。
    返り値: dictは旧29のSOURCEとATRを持つ足。
    """
    row = {"場": session, "index": index, "minutes": 3, "start": index*180, "end": (index+1)*180,
        "confirm": (index+1)*180+1, "confirm_line": index+1, "publish": True, "missing": 0,
        "open": close, "high": close if high is None else high, "low": close if low is None else low,
        "close": close, "atr": 10.0}
    row.update(changes)
    return row


def reflected(rows: list[dict], axis: float = 300.) -> list[dict]:
    """価格を上下反射して別の人工入力を返す。

    引数: rows(list[dict])は人工価格、axis(float)は反射定数。
    返り値: list[dict]はH/L交換・O/C符号反転後の足。
    """
    return [{**deepcopy(row), "open": axis-row["open"], "high": axis-row["low"],
             "low": axis-row["high"], "close": axis-row["close"]} for row in rows]


def material() -> list[dict]:
    """未準備crossと後続の上向き構造crossを持つ人工系列を返す。

    引数: なし。
    返り値: list[dict]は平足20本と明示的な山谷列。
    """
    prices = [100.]*20+[100., 102., 105., 103., 101., 104., 108., 106., 103., 106., 110., 108., 105., 108., 112., 109., 111., 113.]
    return [frame(index, price) for index, price in enumerate(prices)]


def built(rows: list[dict]) -> list[dict]:
    """人工だけを新DMI/Fast銀行へ渡す。

    引数: rows(list[dict])は人工足。
    返り値: list[dict]は新限定数値。
    """
    return J.NumericBank().build(rows, rows[0]["場"] if rows else SESSION, ("人工限月",))[0]


def generated(rows: list[dict], **changes) -> dict:
    """人工数値を固定時間条件で新入口へ渡す。

    引数: rows(list[dict])は人工限定数値、changesは時刻置換。
    返り値: dictは全原P/極値/監視/三採否。
    """
    return I.generate(rows, SESSION, changes.get("cutoff", 100000.), changes.get("deadline", 200000.), CONFIG)


class 方向数値検証(unittest.TestCase):
    """Wilderの種・floatモデルと精密Fastを分離する。"""

    def test_DIは15足目で初有効かつ売買交換(self):
        """14差分の種を14本の価格と取り違えない。

        引数: self(TestCase)は対象。
        返り値: None。一定TR2/上DM1でDI50を手計算照合する。
        """
        source = [frame(i, 101.+i, 102.+i, 100.+i) for i in range(18)]
        rows, mirror = built(source), built(reflected(source))
        self.assertTrue(all(row["plus_di"] is None for row in rows[:14]))
        self.assertEqual((rows[14]["plus_di"], rows[14]["minus_di"], rows[14]["DMI差分数"]), (50., 0., 14))
        for a, b in zip(rows, mirror, strict=True):
            self.assertEqual((a["plus_di"], a["minus_di"]), (b["minus_di"], b["plus_di"]))

    def test_DM同幅両拡大は両0とTR0の状態保持(self):
        """0の数値準備とTR0による未定義を分ける。

        引数: self(TestCase)は対象。
        返り値: None。方向なしを買いへ補完しない。
        """
        rows = built([frame(i, 100., 101., 99.) for i in range(16)])
        self.assertEqual((rows[-1]["plus_di"], rows[-1]["minus_di"], rows[-1]["DMI準備"]), (0., 0., True))
        state = J.DirectionalMovement()
        state.update(frame(0, 105., 110., 100.))
        state.update(frame(1, 105., 111., 99.))
        self.assertEqual(state.seed[-1], (12., 0., 0.))
        rows = built([frame(i, 100.) for i in range(15)]+[frame(15, 101., 102., 100.)])
        self.assertFalse(rows[14]["DMI準備"])
        self.assertTrue(rows[15]["DMI準備"])
        self.assertEqual((rows[15]["plus_di"], rows[15]["minus_di"]), (100., 0.))

    def test_Fast最速16と同値精密差0(self):
        """表示KとSMAの微差を採否へ使わない。

        引数: self(TestCase)は対象。
        返り値: None。100*3/11の三同値は数学的に差0。
        """
        rows = built([frame(i, 103., 111., 100.) for i in range(18)])
        self.assertFalse(rows[14]["Fast準備"])
        self.assertTrue(rows[15]["Fast準備"])
        self.assertEqual(rows[15]["FastK"], J.exact(Fraction(300, 11)))
        self.assertEqual(rows[15]["Fast差"], J.exact(Fraction(0)))
        self.assertEqual(rows[15]["Fast差厳密符号"], 0)
        self.assertTrue(all(row["Fast差厳密符号"] == 0 for row in rows[15:]))

    def test_幅0はK窓だけとNP不投入と数値carry(self):
        """場内Fastと同限月DMI銀行の寿命を分ける。

        引数: self(TestCase)は対象。
        返り値: None。契約・尾部・missing・番号gapを人工で照合する。
        """
        bank = J.NumericBank()
        first, _ = bank.build([frame(i, 101.+i, 102.+i, 100.+i) for i in range(18)], SESSION, ("A",))
        second, _ = bank.build([frame(0, 121., 122., 120., session="次場")], "次場", ("A",))
        self.assertTrue(second[0]["DMI準備"]); self.assertFalse(second[0]["Fast準備"])
        third, _ = bank.build([frame(0, 121., 122., 120., session="別契約")], "別契約", ("B",))
        self.assertFalse(third[0]["DMI準備"])
        source = [frame(i, 103., 111., 100.) for i in range(16)]
        source += [frame(i, 100.) for i in range(16, 30)]
        values = built(source)
        self.assertEqual(len(values[-1]["Fast価格窓足番号"]), 14)
        self.assertEqual(values[-1]["FastK窓足番号"], [])
        self.assertFalse(values[-1]["Fast準備"])
        for field, value in (("publish", False), ("missing", 1)):
            changed = deepcopy(material()); changed[20][field] = value
            rows = built(changed)
            self.assertEqual(rows[20]["Fast価格窓足番号"], [])
            self.assertEqual(rows[21]["Fast価格窓足番号"], [21])
        source = material(); source.pop(20)
        rows = built(source)
        self.assertEqual(rows[20]["index"], 21)
        self.assertEqual(rows[20]["DMI差分数"], 0)
        self.assertEqual(rows[20]["Fast価格窓足番号"], [21])
        bank.build([frame(0, 100.)], SESSION, ("B",), tail_missing=1)
        self.assertIsNone(bank.dmi.previous)

    def test_独立DIと精密Fastを原OHLCから別算照合(self):
        """独立生DIのfloat差を許容しても優勢符号は厳密に一致させる。

        引数: self(TestCase)は対象。
        返り値: None。Fast/SOURCEは全末端厳密、ATRは旧固定数値の別検算範囲。
        """
        path=HERE/"状態独立確認.py"
        if not path.exists():self.skipTest("独立API完成前")
        independent=load(path,"スイング45人工独立数値")
        if not hasattr(independent,"NumericHistory"):self.skipTest("独立数値API完成前")
        scenarios=[material(),[frame(i,103.,111.,100.) for i in range(40)],
                   [frame(i,101.+i+(i%3),104.+i+(i%3),99.+i) for i in range(50)]]
        changed=material();changed[20]["publish"]=False;scenarios.append(changed)
        changed=material();changed[20]["missing"]=1;scenarios.append(changed)
        changed=material();changed.pop(20);scenarios.append(changed)
        for source in [*scenarios,*[reflected(s) for s in scenarios]]:
            legacy,_=J.BASE.NumericBank().build(source,SESSION,("人工限月",),quantities=None)
            values=[{**row,"atr":old["atr"]} for row,old in zip(source,legacy,strict=True)]
            main,quality=J.NumericBank().build(values,SESSION,("人工限月",))
            alternate,other_quality=independent.NumericHistory().build(values,SESSION,("人工限月",))
            self.assertEqual(quality,other_quality)
            for a,b in zip(main,alternate,strict=True):
                for name in J.NUMERIC_FIELDS:
                    if name in ("plus_di","minus_di","atr") and J.finite(a[name]) and J.finite(b[name]):
                        self.assertAlmostEqual(a[name],b[name],delta=1e-10)
                    else:self.assertEqual(a[name],b[name],name)
                if a["DMI準備"]:
                    left,right=a["plus_di"]-a["minus_di"],b["plus_di"]-b["minus_di"]
                    self.assertEqual((left>0)-(left<0),(right>0)-(right<0))
                if J.finite(a["atr"]) and a["atr"]>0:
                    self.assertEqual(max(5,math.ceil(a["atr"]/5)*5),max(5,math.ceil(b["atr"]/5)*5))

    def test_DI二経路は微差だけ許容し優勢準備採否を厳密にする(self):
        """正本DI定義が独立生値の判断差を隠さないことを検査する。

        引数: self(TestCase)は対象。
        返り値: None。採否へepsilonを追加せず、数値と判断の比較を分離する。
        """
        independent=load(HERE/"状態独立確認.py","スイング45人工DI範囲独立")
        if not hasattr(independent,"compare_numeric_scope"):self.skipTest("独立二経路API完成前")
        base={"plus_di":30.,"minus_di":20.,"DI差":10.,"close":100.,"DMI準備":True,
              "戦略判定":{"C0":{"採用":True}}}
        changed=deepcopy(base);changed["plus_di"]=math.nextafter(30.,math.inf);changed["DI差"]=changed["plus_di"]-20.
        audit=independent.Audit()
        self.assertTrue(independent.compare_numeric_scope("同優勢微差",base,changed,audit))
        self.assertEqual(audit.mismatches,0)
        self.assertNotEqual(J.canonical_sha(base),J.canonical_sha(changed))
        changed=deepcopy(base);changed["plus_di"]+=1e-8;changed["DI差"]+=1e-8
        audit=independent.Audit();independent.compare_numeric_scope("許容超過",base,changed,audit)
        self.assertGreater(audit.mismatches,0)
        left={"plus_di":math.nextafter(20.,math.inf),"minus_di":20.}
        right={"plus_di":math.nextafter(20.,-math.inf),"minus_di":20.}
        audit=independent.Audit()
        self.assertFalse(independent.compare_numeric_scope("優勢反転",left,right,audit))
        self.assertGreater(audit.mismatches,0)
        for left,right in (({"plus_di":None,"minus_di":0.},{"plus_di":0.,"minus_di":0.}),
                           ({"DI差":1e-16},{"DI差":-1e-16})):
            audit=independent.Audit();self.assertFalse(independent.compare_numeric_scope("有限準備又は符号",left,right,audit))
            self.assertGreater(audit.mismatches,0)
        for kind in ("price","adopt","ready"):
            changed=deepcopy(base)
            if kind=="price":changed["close"]=math.nextafter(100.,math.inf)
            elif kind=="adopt":changed["戦略判定"]["C0"]["採用"]=False
            else:changed["DMI準備"]=False
            audit=independent.Audit();self.assertFalse(independent.compare_numeric_scope("全非許容値",base,changed,audit))
            self.assertGreater(audit.mismatches,0)


class 確定水準と入口検証(unittest.TestCase):
    """中心と確認、原P消費と複合採否を分ける。"""

    def test_左strict右等号と同中心両極値(self):
        """旧15の片側同値規約だけを再用する。

        引数: self(TestCase)は対象。
        返り値: None。RSI/中心間隔/上位を追加しない。
        """
        source = [frame(i, 100., h, l) for i, (h,l) in enumerate([(102.,98.),(103.,97.),(105.,95.),(105.,95.),(104.,96.)])]
        result = generated(built(source))
        self.assertEqual([(p["中心番号"], p["確認足番号"],p["極値side"]) for p in result["pivots"]], [(2,4,1),(2,4,-1)])
        self.assertTrue(all(p["五足番号"] == [0,1,2,3,4] for p in result["pivots"]))
        source[0]["high"] = 105.
        self.assertFalse(any(p["極値side"] == 1 for p in generated(built(source))["pivots"]))

    def test_j新pivotは判断後と未準備でも消費(self):
        """現在確認された安値を過去p時点の構造へ入れない。

        引数: self(TestCase)は対象。
        返り値: None。最初rawの未準備を後の好条件へ取り直さない。
        """
        result = generated(built(material()))
        by_index = {r["index"]: r for r in result["decisions"]}
        self.assertIn(30, by_index)
        self.assertFalse(by_index[30]["構造準備"])
        self.assertEqual(by_index[30]["判別種別"], "WAIT")
        self.assertTrue(by_index[34]["戦略判定"]["C0"]["採用"])
        self.assertEqual((by_index[34]["構造方向"],by_index[34]["判別種別"],by_index[34]["役割"]),(1,"T","順行"))
        self.assertTrue(any(action["動作"] == "使用済みcross見送り" for t in result["monitor_trace"] for action in t["動作"]))
        for record in result["decisions"]:
            point = next(p for p in result["pivots"] if p["極値ID"] == record["突破極値ID"])
            self.assertLessEqual((point["確認出典"]["confirm"],point["確認出典"]["confirm_line"]),
                                 (record["前3分参照"]["confirm"],record["前3分参照"]["confirm_line"]))
            prior=result["monitor_trace"][record["index"]]["監視前"]
            self.assertEqual(record["突破極値ID"],prior["高値ID" if record["side"]==1 else "安値ID"][-1])

    def test_構造の継続破綻混在と売買鏡像(self):
        """HHHL継続とLHLL破綻を同じ実方向式で分類する。

        引数: self(TestCase)は対象。
        返り値: None。全反射では役割を変えず、価格/DI/Fast符号を反転する。
        """
        a, b = generated(built(material())), generated(built(reflected(material())))
        self.assertEqual(len(a["decisions"]),len(b["decisions"]))
        for first, second in zip(a["decisions"],b["decisions"],strict=True):
            self.assertEqual(first["side"],-second["side"])
            self.assertEqual(first["判別種別"],second["判別種別"])
            self.assertEqual([first["戦略判定"][p]["採用"] for p in I.POLICIES],[second["戦略判定"][p]["採用"] for p in I.POLICIES])
        source=material()[:35];source[34]=frame(34,100.)
        reversal=next(r for r in generated(built(source))["decisions"] if r["index"]==34)
        self.assertEqual((reversal["構造方向"],reversal["side"],reversal["判別種別"],reversal["役割"]),(1,-1,"R","反転"))
        self.assertTrue(reversal["戦略判定"]["C2"]["採用"])
        p = lambda price: {"極値価格":price}
        self.assertEqual(I.structure([p(100),p(110)],[p(90),p(95)]),(True,1))
        self.assertEqual(I.structure([p(110),p(100)],[p(95),p(90)]),(True,-1))
        self.assertEqual(I.structure([p(100),p(110)],[p(95),p(90)]),(True,0))
        self.assertEqual(I.structure([p(100)],[p(90)]),(False,None))

    def test_対象時点外はP消費無しで局所履歴を進める(self):
        """j.end>p.confirmは終点発動の意味でありj.start条件を加えない。

        引数: self(TestCase)は対象。
        返り値: None。等号を禁止し直上で元Pを回復する。
        """
        values = built(material())
        self.assertTrue(any(r["index"]==34 for r in generated(values)["decisions"]))
        values[33]["confirm"] = values[34]["end"]
        result = generated(values)
        self.assertFalse(any(r["index"]==34 for r in result["decisions"]))
        self.assertEqual(result["monitor_trace"][34]["動作"][0]["動作"],"価格観測対象外")
        self.assertIn(34,result["monitor_trace"][34]["監視後"]["局所五足番号"])
        values[33]["confirm"] -= 1
        self.assertTrue(any(r["index"]==34 for r in generated(values)["decisions"]))

    def test_準備値時間を分けFast同値を0有効のまま除外する(self):
        """C0のDI方向を準備だけへ弱めずC1/C2の差を一条件にする。

        引数: self(TestCase)は対象。
        返り値: None。非採用/時間外でも全Pを消費する。
        """
        values = built(material())
        values[34]["Fast準備"] = False;values[34]["Fast差厳密符号"] = None
        record = next(r for r in generated(values)["decisions"] if r["index"]==34)
        self.assertEqual([record["戦略判定"][p]["採用"] for p in I.POLICIES],[True,False,False])
        values[34]["Fast準備"] = True;values[34]["Fast差厳密符号"] = 0
        record = next(r for r in generated(values)["decisions"] if r["index"]==34)
        self.assertEqual([record["戦略判定"][p]["採用"] for p in I.POLICIES],[True,True,False])
        values[34]["plus_di"] = values[34]["minus_di"] = 0.
        record = next(r for r in generated(values)["decisions"] if r["index"]==34)
        self.assertTrue(record["DMI準備"])
        self.assertFalse(any(record["戦略判定"][p]["採用"] for p in I.POLICIES))
        result = generated(built(material()),cutoff=0.)
        self.assertTrue(result["decisions"])
        self.assertFalse(any(result["signals"].values()))
        self.assertTrue(any(a["動作"]=="使用済みcross見送り" for t in result["monitor_trace"] for a in t["動作"]))

    def test_純13のsnapshot未来label排除とprefix不変(self):
        """全採否後深複写し、未来の極値確定を過去判断へ戻さない。

        引数: self(TestCase)は対象。
        返り値: None。元ATR/OHLCと要求時計を保持する。
        """
        values = built(material()); result = generated(values)
        earlier = generated(values[:35])
        self.assertEqual(earlier["decisions"],[r for r in result["decisions"] if r["index"]<35])
        for p in I.POLICIES:
            for row in result["signals"]["3分_"+p]:
                row["ラベル"]="将来毒";pure=I.pure_signal(row,p)
                self.assertEqual(set(pure),set(I.SIGNAL_FIELDS))
                self.assertNotIn("ラベル",pure)
                self.assertEqual(pure["atr"],10.)
        record = next(r for r in result["decisions"] if r["index"]==34)
        selected=next(r for r in result["signals"]["3分_C0"] if r["index"]==34)
        selected["戦略判定"]["C2"]["採用"]=False
        self.assertTrue(record["戦略判定"]["C2"]["採用"])

    def test_不正NP欠枠clearと公開key同値拒否(self):
        """古い有利pivotの探索や公開前足の飛ばし継続をしない。

        引数: self(TestCase)は対象。
        返り値: None。gap後missing0有効当足だけ新seedを許す。
        """
        for field,value in (("publish",False),("missing",1)):
            source=material();source[33][field]=value
            result=generated(built(source))
            self.assertEqual(result["monitor_trace"][33]["監視後"]["高値ID"],[])
            self.assertFalse(any(r["index"]==34 for r in result["decisions"]))
        source=material();source[33]["confirm"]=source[32]["confirm"];source[33]["confirm_line"]=source[32]["confirm_line"]
        with self.assertRaises(ValueError):built(source)

    def test_独立区間走査と全極値監視発動採否が一致(self):
        """主の逐次dequeとは別の中心予約走査へ全schemaを照合する。

        引数: self(TestCase)は対象。
        返り値: None。正本定義のDI入力に対する価格機械と全採否を厳密に検査する。
        """
        independent=load(HERE/"状態独立確認.py","スイング45人工独立価格")
        if not hasattr(independent,"generate"):self.skipTest("独立価格API完成前")
        scenarios=[material()]
        source=material()[:35];source[34]=frame(34,100.);scenarios.append(source)
        for field,value in (("publish",False),("missing",1)):
            source=material();source[28][field]=value;scenarios.append(source)
        source=material();source.pop(28);scenarios.append(source)
        for source in [*scenarios,*[reflected(s) for s in scenarios]]:
            values=built(source)
            self.assertEqual(generated(values),independent.generate(values,SESSION,100000.,200000.,CONFIG))
        values=built(material());values[33]["confirm"]=values[34]["end"]
        self.assertEqual(generated(values),independent.generate(values,SESSION,100000.,200000.,CONFIG))


def driver_module():
    """市場起動せず新主driverの定義を読む。

    引数: なし。
    返り値: moduleは現主。
    """
    return load(HERE/"検証.py","スイング45人工主")


@contextmanager
def artificial_driver(driver, count: int = 66):
    """新母集団の人工66場と小型一時studyを作る。

    引数: driver(module)は主、count(int)は人工場数。
    返り値: contextmanagerは束/新build/一時保存先。旧入口/旧labelの対照は作らない。
    """
    with tempfile.TemporaryDirectory(prefix="スイング45合成_",dir=ROOT/"work") as temporary:
        folder=Path(temporary);study,work=folder/"study",folder/"work";study.mkdir();work.mkdir()
        config=driver.expected_config();driver.W.write_json(study/"条件.json",config)
        driver.W.write_json(study/"入力台帳.json",{"人工":True})
        driver.W.write_json(study/"指標参照.json",{"文書と証明":{},"共有明細":[]})
        (study/"計画.md").write_text("人工スイング比較\n",encoding="utf-8")
        driver.W.write_json(work/"診断予定.json",{"人工":True})
        sessions=[str(date(2026,9,22)+timedelta(days=i//2))+("_Day" if i%2==0 else "_Night") for i in range(count)]
        bundle={"lower":{},"numeric":{},"numeric_quality":{}}
        for index,session in enumerate(sessions):
            source=material()[:35] if index==0 else []
            source=[{**row,"場":session} for row in source]
            rows,quality=J.NumericBank().build(source,session,("人工限月",))
            bundle["lower"][session]=[J.frame_projection(row) for row in source]
            bundle["numeric"][session]=rows;bundle["numeric_quality"][session]=quality

        def build(entry,manifest,shared,current,include_events=False):
            """実I.generateと純13を通し、正式だけ人工正常BBOを渡す。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式フラグ。
            返り値: dictは新三案の場bundle。
            """
            session=entry["session"]
            block=driver.I.generate(shared["numeric"][session],session,90000.,95000.,current)
            block["signals"]={sid:[driver.I.pure_signal(row,sid[3:]) for row in values] for sid,values in block["signals"].items()}
            events=[]
            if include_events and shared["numeric"][session]:
                events=[SimpleNamespace(now=t,line=i+1,valid=True,bid=bid,ask=bid+5,last=bid+2.5)
                        for i,(t,bid) in enumerate([(6301.,110.),(6302.,110.),(6303.,135.),(6304.,115.),(6305.,115.)])]
            block.update(input_quality=deepcopy(block["quality"]),events=events,cutoff=90000.,deadline=95000.,duration=100000./60)
            return block

        yield SimpleNamespace(folder=folder,study=study,work=work,config=config,bundle=bundle,build=build,
            manifest={"source_root":"人工予約だけ","entries":[{"session":s} for s in sessions]},
            ref={"文書と証明":{},"共有明細":[]})


class 主driver接続検証(unittest.TestCase):
    """新価格母集団の非損益準備・新先着・六保存物を人工で接続する。"""

    def test_CLI人工66準備は新価格数値だけでlabel運用禁止(self):
        """準備で先着や成績を計算せず、4列定義を一回保存する。

        引数: self(TestCase)は対象。
        返り値: None。実CLI引数からrunまで人工に限定する。
        """
        driver=driver_module()
        with artificial_driver(driver) as f, patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",return_value=f.bundle), \
                patch.object(driver,"build_session",side_effect=f.build) as build, \
                patch.object(driver,"freeze",side_effect=AssertionError("prepare固定禁止")), \
                patch.object(driver.W.OLD,"気配経路",side_effect=AssertionError("prepare先着禁止")), \
                patch.object(driver.ENGINE,"replay",side_effect=AssertionError("prepare運用禁止")), \
                patch.object(driver.E,"entry_metrics",side_effect=AssertionError("prepare先着成績禁止")), \
                patch.object(driver.S,"operation_metrics",side_effect=AssertionError("prepare運用成績禁止")), \
                patch.object(sys,"argv",[str(HERE/"検証.py"),"--study",str(f.study),"--work",str(f.work),"--prepare"]),redirect_stdout(io.StringIO()):
            driver.main()
            prepared=driver.W.read_json(f.work/"準備点検.json")
            self.assertFalse(prepared["ラベル計算"]);self.assertFalse(prepared["損益計算"])
            self.assertEqual(len(prepared["準備"]),66)
            self.assertEqual(build.call_count,66)
            self.assertTrue(all(call.args[-1] is False for call in build.call_args_list))
            info=prepared["DMI数値定義"];path=ROOT/info["パス"]
            self.assertEqual(set(info),{"パス","圧縮SHA256参考","展開内容SHA256","行数"})
            with gzip.open(path,"rt",encoding="utf-8") as stream:rows=[json.loads(line) for line in stream]
            self.assertEqual(len(rows),35)
            self.assertTrue(all(set(row)=={"場","index","plus_di","minus_di"} for row in rows))
            for record in prepared["準備"]:
                self.assertEqual(record["極値数"],len(f.build({"session":record["場"]},None,f.bundle,f.config)["pivots"]))
            with self.assertRaises(ValueError):driver.run(f.study,f.work,True)
            self.assertFalse(any((f.work/name).exists() for name in driver.FILES))

    def test_人工正式は新三case六gzip六役割群を最後まで保存(self):
        """旧labelを流用せず、三案へ同じ当時純信号だけを運用へ渡す。

        引数: self(TestCase)は対象。
        返り値: None。実XFの人工新規/返済を主の末尾集計へ接続する。
        """
        driver=driver_module()
        with artificial_driver(driver,1) as f:
            replay=driver.ENGINE.replay
            label=dict(zip(driver.C.LABEL_FIELDS,["順行先着","人工直接先着",115.,6302.,2,7000.,9,365.,250.,10.,11.]))

            def operation(*args):
                """純列を確認して人工範囲の実XFへ渡す。

                引数: args(tuple)は主の運用引数。
                返り値: tupleは人工状態と品質。
                """
                self.assertTrue(all(set(row)==set(I.SIGNAL_FIELDS) for row in args[1]))
                return replay(*args,bounds=(0.,100000.,90000.,95000.))

            def publish(study,path,ids,manifest,suffix):
                """Viewer外部起動を小型の人工一覧へ置換する。

                引数: study/path(Path),ids(list),manifest(dict),suffix(str)は主契約。
                返り値: None。実Viewer/資料を開かない。
                """
                driver.W.write_json(study/"一覧.resources.json",{"resources":[{"id":"00008_人工"}]})

            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                    patch.object(driver,"read_bundle",return_value=f.bundle),patch.object(driver,"build_session",side_effect=f.build), \
                    patch.object(driver,"freeze",return_value={}),patch.object(driver.W.OLD,"気配経路",return_value=SimpleNamespace(evaluate=lambda *a,**k:deepcopy(label))), \
                    patch.object(driver.ENGINE,"replay",side_effect=operation) as operated,patch.object(driver.E,"publish_details",side_effect=publish),redirect_stdout(io.StringIO()):
                driver.run(f.study,f.work,False)
            result=driver.W.read_json(f.study/"結果.json")
            self.assertEqual(result["入口評価数"],3);self.assertEqual(len(result["役割別入口評価"]),6)
            self.assertEqual(operated.call_count,3)
            artifacts=driver.W.read_json(f.study/"作業成果物.json")
            self.assertEqual(len(artifacts["ファイル"]),6)
            with gzip.open(f.work/"入口事例.jsonl.gz","rt",encoding="utf-8") as stream:cases=[json.loads(line) for line in stream]
            self.assertEqual(len(cases),3)
            for row in cases:
                self.assertEqual({key:row[key] for key in driver.C.LABEL_FIELDS},label)
                self.assertTrue(set(I.METADATA_FIELDS)<=set(row))
                self.assertNotIn("旧A0イベントID",row)
            with gzip.open(f.work/"価格状態.jsonl.gz","rt",encoding="utf-8") as stream:prices=[json.loads(line) for line in stream]
            self.assertEqual({row["種別"] for row in prices},{"極値","監視"})
            ids=[row["極値ID"] for row in prices if row["種別"]=="極値"]
            self.assertEqual(len(ids),len(set(ids)))

    def test_共有束の新数値carryと実buildの純13と気配分離(self):
        """旧29材料だけから新銀行を作り、新公開窓を場ごとに解除する。

        引数: self(TestCase)は対象。
        返り値: None。実build_sessionも人工stat/cacheで通す。
        """
        driver=driver_module()
        with artificial_driver(driver,2) as f:
            entries=f.manifest["entries"]
            for entry in entries:entry["in_session_contract_codes"]=["人工限月"]
            source=[frame(i,101.+i,102.+i,100.+i,session=entries[0]["session"]) for i in range(18)]
            following=[frame(0,121.,122.,120.,session=entries[1]["session"])]
            old={"lower":{entries[0]["session"]:source,entries[1]["session"]:following}}
            times=tuple(SimpleNamespace(timestamp=lambda x=x:x) for x in (0.,3240.,90000.,95000.))
            with patch.object(driver.C,"read_bundle",return_value=old),patch.object(driver,"manifest_for",return_value=f.manifest), \
                    patch.object(driver.W.OLD.shared.legacy,"session_times",return_value=times):
                bundle=driver.read_bundle(f.study)
            self.assertEqual(set(bundle),{"lower","numeric","numeric_quality"})
            self.assertTrue(bundle["numeric"][entries[1]["session"]][0]["DMI準備"])
            self.assertFalse(bundle["numeric"][entries[1]["session"]][0]["Fast準備"])
            entry=f.manifest["entries"][0];source_path=f.folder/"人工source.bin";cache=f.folder/"人工cache.bin"
            source_path.write_bytes(b"artificial");cache.write_bytes(b"cache")
            stat=source_path.stat();entry.update(source_path=source_path.name,cache_path=os.path.relpath(cache,ROOT/"work/複合検証"),
                source_size=stat.st_size,source_mtime_ns=stat.st_mtime_ns,sha256_cache=sha(cache))
            manifest={**f.manifest,"source_root":str(f.folder)}
            with patch.object(driver.W.OLD.shared.legacy,"session_times",return_value=times), \
                    patch.object(driver.W.PREP,"read_events",side_effect=AssertionError("prepare気配禁止")):
                block=driver.build_session(entry,manifest,f.bundle,f.config,False)
            self.assertTrue(all(set(row)==set(I.SIGNAL_FIELDS) for values in block["signals"].values() for row in values))
            self.assertEqual(block["events"],[])
            entry["sha256_cache"]="0"*64
            with self.assertRaises(ValueError):driver.build_session(entry,manifest,f.bundle,f.config,False)

    def test_条件partial実行中版差を拒否(self):
        """閾値更新と未完正式出力の再実行を早期に止める。

        引数: self(TestCase)は対象。
        返り値: None。既存固定/モデルへの書込みはしない。
        """
        driver=driver_module()
        with artificial_driver(driver,1) as f:
            wrong=deepcopy(f.config);wrong["スイング突破"]["C2"]="結果後変更"
            with self.assertRaises(ValueError):driver.validate_config(wrong)
            (f.work/driver.FILES[0]).write_bytes(b"partial")
            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                    patch.object(driver,"read_bundle",side_effect=AssertionError("partial後は入力禁止")):
                with self.assertRaises(ValueError):driver.run(f.study,f.work,False)
            initial=driver.current_bindings(f.study);changed=deepcopy(initial);changed["条件SHA256"]="0"*64
            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                    patch.object(driver,"read_bundle",return_value=f.bundle),patch.object(driver,"build_session",side_effect=f.build), \
                    patch.object(driver,"current_bindings",side_effect=[initial,changed]),redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError):driver.run(f.study,f.work,True)
            self.assertFalse((f.work/"準備点検.json").exists())

    def test_固定は正本DI定義と主独立最終人工会計12をjoinする(self):
        """全必須版と定義指紋を人工の固定へ接続する。

        引数: self(TestCase)は対象。
        返り値: None。独立CLI完成前は明示skipし最終成功としない。
        """
        required=[HERE/"状態独立確認.py",HERE/"追尾独立確認.py",HERE/"独立監査.py",ROOT/"work/スイング突破/00045/会計人工接続.py"]
        if not all(path.exists() for path in required):self.skipTest("独立二CLI/会計人工source完成前")
        driver=driver_module()
        with artificial_driver(driver,1) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",return_value=f.bundle), \
                patch.object(driver,"build_session",side_effect=f.build),redirect_stdout(io.StringIO()):
            driver.run(f.study,f.work,True)
            prepared=driver.W.read_json(f.work/"準備点検.json")
            dependency=HERE/"指標.py"
            finance_sources=("scripts/スイング突破/独立監査.py","scripts/スイング突破/運用.py","work/スイング突破/00045/会計人工接続.py")
            finance={"全件一致":True,"不一致数":0,"人工経路数":12,"実行中code不変":True,
                "条件SHA256":sha(f.study/"条件.json"),"コードSHA256":{name:sha(ROOT/name) for name in finance_sources}}
            driver.W.write_json(f.work/"会計人工接続.json",finance)
            (f.work/"会計人工接続.py").write_bytes((ROOT/finance_sources[-1]).read_bytes())
            proof={"全件一致":True,"不一致数":0,"不一致":[],"ラベル計算":False,"損益計算":False,
                "主準備SHA256":sha(f.work/"準備点検.json"),"主コードSHA256":driver.code_pins(),
                "条件SHA256":sha(f.study/"条件.json"),"入力台帳SHA256":sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256":sha(driver.MANIFEST_PATH),"指標参照SHA256":sha(f.study/"指標参照.json"),
                "コードSHA256":sha(required[0]),"追尾コードSHA256":sha(required[1]),
                "依存コードSHA256":{dependency.relative_to(ROOT).as_posix():sha(dependency)},"DMI数値定義":prepared["DMI数値定義"]}
            synthetic={"全件成功":True,"合成編集終了":False,"実行中code不変":True,
                "ファイルSHA256":{p.relative_to(ROOT).as_posix():sha(p) for p in [HERE/n for n in ("検証.py","入口.py","指標.py","運用.py","合成検証.py")]+[f.study/"条件.json"]},
                "独立数値補助SHA256":sha(required[0]),"独立追尾補助SHA256":sha(required[1])}
            synthetic_file=f.work/"人工最終合成.json";driver.W.write_json(synthetic_file,synthetic)
            actual_read,actual_sha=driver.W.read_json,driver.O.sha

            def read_json(path):
                """旧固定集合と最終人工の読取先だけを人工宣言へ写す。

                引数: path(Path)は小証明先。
                返り値: dictは人工宣言又は現在正本。旧モデル数式は変更しない。
                """
                if normalized(path)==normalized(driver.PREVIOUS/"固定.json"):
                    return {"ファイルSHA256":{dependency.relative_to(ROOT).as_posix():sha(dependency)}}
                return deepcopy(synthetic) if normalized(path)==normalized(WORK/"合成検証.json") else actual_read(path)

            def current_sha(path):
                """人工最終proof参照だけのSHA読取を一時先へ写す。

                引数: path(Path)は指紋先。
                返り値: strは人工又は現在指紋。
                """
                return sha(synthetic_file) if normalized(path)==normalized(WORK/"合成検証.json") else actual_sha(path)

            target=f.work/"独立準備点検.json"
            with patch.object(driver.W,"read_json",side_effect=read_json),patch.object(driver.O,"sha",side_effect=current_sha):
                with self.assertRaises(FileNotFoundError):driver.freeze(f.study,f.work)
                driver.W.write_json(target,proof)
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                synthetic["合成編集終了"]=True
                for key in proof:
                    changed=deepcopy(proof);changed[key]=not proof[key] if isinstance(proof[key],bool) else {} if isinstance(proof[key],dict) else "不一致"
                    driver.W.write_json(target,changed)
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                driver.W.write_json(target,proof)
                for key in ("全件成功","合成編集終了","実行中code不変","独立数値補助SHA256","独立追尾補助SHA256"):
                    before=synthetic[key];synthetic[key]=False if isinstance(before,bool) else "0"*64
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                    synthetic[key]=before
                for path in synthetic["ファイルSHA256"]:
                    before=synthetic["ファイルSHA256"][path];synthetic["ファイルSHA256"][path]="0"*64
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                    synthetic["ファイルSHA256"][path]=before
                for key in prepared["DMI数値定義"]:
                    changed=deepcopy(prepared);changed["DMI数値定義"][key]=-1 if key=="行数" else "不一致"
                    driver.W.write_json(f.work/"準備点検.json",changed)
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                driver.W.write_json(f.work/"準備点検.json",prepared)
                for key in ("全件一致","不一致数","人工経路数","実行中code不変","条件SHA256","コードSHA256"):
                    changed=deepcopy(finance);changed[key]=False if isinstance(finance[key],bool) else {} if isinstance(finance[key],dict) else "不一致"
                    driver.W.write_json(f.work/"会計人工接続.json",changed)
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                for source in finance_sources:
                    changed=deepcopy(finance);changed["コードSHA256"].pop(source);driver.W.write_json(f.work/"会計人工接続.json",changed)
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                driver.W.write_json(f.work/"会計人工接続.json",finance)
                driver.W.write_json(synthetic_file,synthetic)
                locked=driver.freeze(f.study,f.work)
                self.assertEqual(driver.freeze(f.study,f.work),locked)
                relative=(f.work/"DMI数値定義.jsonl.gz").relative_to(ROOT).as_posix()
                self.assertEqual(locked["ファイルSHA256"][relative],sha(f.work/"DMI数値定義.jsonl.gz"))
                (f.study/"計画.md").write_text("固定後変更",encoding="utf-8")
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                driver.W.write_json(f.study/"結果.json",{})
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)


class 独立定義接続検証(unittest.TestCase):
    """小型4列の実readerと生値非改変overlayを市場外で接続する。"""

    def test_4列blob実読取と全行guardと非改変overlay(self):
        """小型定義が任意の属性や別場・欠損足を正当化しない。

        引数: self(TestCase)は対象。
        返り値: None。人工2行だけをgzipへ保存して全metadataを実検算する。
        """
        independent=load(HERE/"状態独立確認.py","スイング45人工4列読取独立")
        if not all(hasattr(independent,k) for k in ("read_definition","define_rows")):
            self.skipTest("独立reader/overlay完成前")
        driver=driver_module()
        with tempfile.TemporaryDirectory(prefix="スイング45合成_",dir=ROOT/"work") as temporary:
            work=Path(temporary);path=work/"DMI数値定義.jsonl.gz"
            main=built([frame(i,101.+i,102.+i,100.+i) for i in range(18)])[14:16]
            for row in main:row["atr"]=10.1
            rows=[{k:row[k] for k in ("場","index","plus_di","minus_di")} for row in main]

            def saved(values):
                """人工の4列だけを保存し、主prepareと同じ参照を返す。

                引数: values(list[dict])は人工定義行。
                返り値: dictは4metadataと当場全足数。
                """
                with driver.compressed(path) as stream:
                    for row in values:stream.write(driver.D.encode(row))
                return {"DMI数値定義":{"パス":path.relative_to(ROOT).as_posix(),"圧縮SHA256参考":sha(path),
                    "展開内容SHA256":driver.content_sha(path),"行数":len(values)},"準備":[{"場":SESSION,"全指標足数":2}]}

            master=saved(rows)
            values=independent.read_definition(work,master,independent.Audit())
            self.assertEqual(values,{SESSION:{row["index"]:row for row in rows}})
            raw=deepcopy(main);raw[-1]["plus_di"]=math.nextafter(raw[-1]["plus_di"],math.inf)
            raw[-1]["atr"]=math.nextafter(10.1,math.inf);kept=deepcopy(raw)
            shared=[J.frame_projection(row) for row in main]
            defined=independent.define_rows(raw,shared,values[SESSION])
            self.assertEqual(raw,kept);self.assertEqual(defined,main)
            self.assertNotEqual(J.canonical_sha(raw),J.canonical_sha(defined))
            audit=independent.Audit()
            self.assertTrue(independent.compare_numeric_scope("独立生対定義",defined,raw,audit));self.assertEqual(audit.mismatches,0)
            for kind in ("source","definition","duplicate","session"):
                other_shared,other_values,other_raw=deepcopy(shared),deepcopy(values[SESSION]),deepcopy(raw)
                if kind=="source":other_shared.pop()
                elif kind=="definition":other_values.pop(next(iter(other_values)))
                elif kind=="duplicate":other_raw.append(deepcopy(other_raw[0]))
                else:other_values[next(iter(other_values))]["場"]="別場"
                with self.assertRaises(ValueError):independent.define_rows(other_raw,other_shared,other_values)
            for key in master["DMI数値定義"]:
                changed=deepcopy(master);changed["DMI数値定義"][key]=-1 if key=="行数" else "不一致"
                with self.assertRaises(ValueError):independent.read_definition(work,changed,independent.Audit())
            changed=deepcopy(master);changed["DMI数値定義"]["余分属性"]=True
            with self.assertRaises(ValueError):independent.read_definition(work,changed,independent.Audit())
            for kind in ("extra","duplicate","reverse","session","count","negative","oneNone","boolindex"):
                changed=deepcopy(rows)
                if kind=="extra":changed[0]["未来label"]="毒値"
                elif kind=="duplicate":changed[-1]["index"]=changed[0]["index"]
                elif kind=="reverse":changed.reverse()
                elif kind=="session":changed[0]["場"]="別場"
                elif kind=="count":changed.pop()
                elif kind=="negative":changed[0]["plus_di"]=-1.
                elif kind=="oneNone":changed[0]["plus_di"]=None
                else:changed[0]["index"]=True
                bad_master=saved(changed)
                with self.assertRaises(ValueError):independent.read_definition(work,bad_master,independent.Audit())
            allowed=deepcopy(rows);allowed[0]["plus_di"]=allowed[0]["minus_di"]=None
            self.assertIsNone(independent.read_definition(work,saved(allowed),independent.Audit())[SESSION][14]["plus_di"])

    def test_独立CLIは無指定を拒否し不正準備をcache前停止する(self):
        """明示モードと成功bindがないまま市場を読む経路を作らない。

        引数: self(TestCase)は対象。
        返り値: None。CLIと実guarded_inputsを人工JSONへ接続する。
        """
        independent=load(HERE/"状態独立確認.py","スイング45人工CLI独立")
        trail=load(HERE/"追尾独立確認.py","スイング45人工CLI追尾")
        for module in (independent,trail):
            with patch.object(sys,"argv",["人工.py"]),patch.object(module,"run",side_effect=AssertionError("無指定実行禁止")), \
                    redirect_stdout(io.StringIO()),patch.object(sys,"stderr",io.StringIO()):
                with self.assertRaises(SystemExit) as caught:module.main()
                self.assertEqual(caught.exception.code,2)
        driver=driver_module()
        with artificial_driver(driver,1) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",return_value=f.bundle), \
                patch.object(driver,"build_session",side_effect=f.build),redirect_stdout(io.StringIO()):
            driver.run(f.study,f.work,True)
            master=driver.W.read_json(f.work/"準備点検.json")
            resolved=f.study/"入力台帳.json";master["参照台帳SHA256"]=sha(resolved)
            driver.W.write_json(f.work/"準備点検.json",master)
            with patch.object(independent,"references",return_value=None), \
                    patch.object(independent.G,"resolved_manifest",return_value=(f.manifest,resolved)), \
                    patch.object(independent,"shared_bundle",side_effect=AssertionError("guard差の後は共有/原入力禁止")), \
                    patch.object(independent.G,"observed",side_effect=AssertionError("guard差の後は原入力禁止")):
                _,manifest,checked,_=independent.guarded_inputs(f.study,f.work,independent.Audit())
                self.assertEqual(manifest,f.manifest);self.assertEqual(checked,master)
                for key in ("条件SHA256","コードSHA256","ラベル計算"):
                    changed=deepcopy(master)
                    changed[key]=True if key=="ラベル計算" else {} if key=="コードSHA256" else "0"*64
                    driver.W.write_json(f.work/"準備点検.json",changed)
                    with patch.object(sys,"argv",["人工.py","--prepare","--study",str(f.study),"--work",str(f.work)]):
                        with self.assertRaises(ValueError):independent.main()


def main() -> None:
    """市場を遮断して人工だけを起動し小型証明を保存する。

    引数: CLI --final(bool)はrootの最終許可時に一回使う。
    返り値: None。通常は途中proofだけを保存する。
    """
    parser=argparse.ArgumentParser(description="確定スイング/DI/Fastの人工検査")
    parser.add_argument("--final",action="store_true");args=parser.parse_args()
    paths=[HERE/name for name in ("検証.py","入口.py","指標.py","運用.py","合成検証.py")]
    paths.append(ROOT/"study/00045_確定スイング突破と方向優勢/条件.json")
    paths=[p for p in paths if p.exists()]
    helpers=[p for p in (HERE/"状態独立確認.py",HERE/"追尾独立確認.py") if p.exists()]
    pins={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    before={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    with deny_market():result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged=pins=={p.relative_to(ROOT).as_posix():sha(p) for p in paths} and before=={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    success=result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    if args.final and (len(pins)!=6 or len(before)!=2):raise ValueError("主4code/条件/合成と独立二code完成前")
    proof={"全件成功":success,"検証件数":result.testsRun,"合成編集終了":bool(args.final and success),"実行中code不変":unchanged,
        "市場入力読取":False,"市場先着損益計算":False,"ファイルSHA256":pins,
        "独立数値補助SHA256":before.get("scripts/スイング突破/状態独立確認.py"),
        "独立追尾補助SHA256":before.get("scripts/スイング突破/追尾独立確認.py"),
        "skip数":len(result.skipped),"失敗数":len(result.failures),"エラー数":len(result.errors)}
    WORK.mkdir(parents=True,exist_ok=True);target=WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"出力":str(target),"全件成功":success,"件数":result.testsRun,"SHA256":sha(target)},ensure_ascii=False))
    if not success:raise SystemExit(1)


if __name__=="__main__":main()
