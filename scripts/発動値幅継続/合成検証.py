"""実市場I/Oを遮断し、上位の準備・値・公開時点と固定XFの接続を検査する。"""

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
WORK = ROOT/"work/発動値幅継続"
SESSION = "人工発動値幅場"
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
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("発動値幅40合成_")
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


I = load(HERE/"入口.py", "発動値幅40合成の入口")
O = load(HERE/"運用.py", "発動値幅40合成の運用")
S37 = load(ROOT/"scripts/構造判別/合成検証.py", "発動値幅40合成の固定37人工補助")
CONFIG = deepcopy(S37.CONFIG)


def frame(index: int = 0, minutes: int = 3, **updates: object) -> dict:
    """完全幅の人工OHLC/公開出典を作る。

    引数: index/minutes(int)は番号/幅、updates(object)は変更。
    返り値: dictはSOURCE_FIELDSを持つ足。
    """
    end = (index+1)*minutes*60.
    return {"index": index, "minutes": minutes, "start": end-minutes*60, "end": end,
        "confirm": end, "confirm_line": index+1, "publish": True, "missing": 0,
        "open": 10000., "high": 10010., "low": 9990., "close": 10000., **updates}


def signal(side: int = 1, clock: float = 1810., line: int = 20, event: str = "人工旧P") -> dict:
    """既に競合後の旧39J0純13列を作る。

    引数: side(int)は実方向、clock/line(float/int)とevent(str)は出典。
    返り値: dictは固定役割の旧H0。
    """
    row = S37.signal("T1", side, "順行", event, clock, line)
    row.update(場=SESSION,入口ID="3分_J0",イベントID=event+"_J0")
    return row


def block(rows: list[dict] | None = None, end: float = 1800.) -> dict:
    """固定J0純集合と当場の現前3分/出典を作る。

    引数: rows(list[dict]|None)は純入口、end(float)は最初の当足終了。
    返り値: dictは元J0と保存数値形状の人工材料。
    """
    originals=[signal()] if rows is None else deepcopy(rows)
    frames,sources=[],{}
    for index,row in enumerate(originals):
        finish=end+index*360
        previous={"場":SESSION,**frame(index*2,start=finish-360,end=finish-180,confirm=finish-179,
            confirm_line=max(0,row["要求原板行"]-1)),"atr":25.}
        current={"場":SESSION,**frame(index*2+1,start=finish-180,end=finish,confirm=row["要求時計秒"],
            confirm_line=row["要求原板行"],low=row["low"],high=row["high"]),"atr":row["atr"]}
        frames.extend([previous,current]);sources[row["イベントID"]]={k:deepcopy(current[k]) for k in I.SOURCE_FIELDS}
    return {"場":SESSION,"signals":{"3分_J0":originals},"frames":{3:frames},"下位出典":sources}


def price_pair(high: float = 106., low: float = 102., before_close: float = 100., before_atr: float | None = 6.) -> tuple[dict,dict]:
    """TR三距離を直接検算する公開3分ペアを作る。

    引数: high/low/before_close(float)は価格、before_atr(float|None)は前ATR正本。
    返り値: tuple[dict,dict]は当足/前足の限定14列。
    """
    previous={"場":SESSION,**frame(0,start=0.,end=180.,confirm=180.,confirm_line=1,
        open=before_close,high=before_close+0.25,low=before_close-0.25,close=before_close),"atr":before_atr}
    middle=(high+low)/2
    current={"場":SESSION,**frame(1,start=180.,end=360.,confirm=360.,confirm_line=2,
        open=middle,high=high,low=low,close=middle),"atr":6.}
    return current,previous


class 発動値幅検証(unittest.TestCase):
    """TR・前ATR・非拡大の精密境界と時点を検査する。"""

    def test_TR三距離は足内幅と上下ギャップを測る(self) -> None:
        """高安幅だけへTRを置換しない。

        引数: self(TestCase)は対象。
        返り値: None。上下離れのTRは同じ6。
        """
        for high,low,distances in ((106.,102.,[4.,6.,2.]),(98.,94.,[4.,2.,6.])):
            result=I.range_state(*price_pair(high,low))
            self.assertEqual([v["値"] for v in result["TR三距離"].values()],distances)
            self.assertEqual(result["TR"],{"値":6.,"分子":6,"分母":1,"有効":True})
            self.assertEqual(result["値幅区分"],"非拡大")
            self.assertEqual(result["TR前ATR比"]["値"],1.)

    def test_TR0は有効で前ATR0欠測負は未準備(self) -> None:
        """ゼロTRとゼロ分母を混同しない。

        引数: self(TestCase)は対象。
        返り値: None。TRだけは前ATR不可でも保存できる。
        """
        zero=I.range_state(*price_pair(100.,100.,100.,5.))
        self.assertTrue(zero["値幅準備"])
        self.assertEqual(zero["TR"]["値"],0.)
        for value in (None,0.,-1.,math.inf):
            result=I.range_state(*price_pair(before_atr=value))
            self.assertTrue(result["TR準備"])
            self.assertFalse(result["値幅準備"])
            self.assertTrue(result["TR"]["有効"])
            self.assertFalse(result["TR前ATR比"]["有効"])

    def test_保存前ATRの次浮動値でも等号境界を厳密に分ける(self) -> None:
        """abs許容内の差を採否epsilonへ転用しない。

        引数: self(TestCase)は対象。
        返り値: None。TR6と前ATRの上下ULPで採否が変わる。
        """
        for atr,expected in ((math.nextafter(6.,-math.inf),"拡大"),(6.,"非拡大"),(math.nextafter(6.,math.inf),"非拡大")):
            result=I.range_state(*price_pair(before_atr=atr))
            self.assertEqual(result["値幅区分"],expected)
            delta=Fraction(6)-Fraction(atr)
            self.assertEqual((result["TR前ATR差"]["分子"],result["TR前ATR差"]["分母"]),(delta.numerator,delta.denominator))

    def test_Wilder境界1の代数同値と保存丸めの区別(self) -> None:
        """前分母が全倍率で別採否になると説明しない。

        引数: self(TestCase)は対象。
        返り値: None。保存現ATR比較へ採否を置換しない。
        """
        previous=Fraction(7)
        for tr in map(Fraction,(0,6,7,12)):
            current=(13*previous+tr)/14
            self.assertEqual(tr<=previous,current<=previous)
            self.assertEqual(tr<=previous,tr/current<=1)
        high=math.nextafter(2.,math.inf)
        result=I.range_state(*price_pair(high,1.,1.,1.))
        saved_current=(13.+result["TR"]["値"])/14
        self.assertEqual(saved_current,1.)
        self.assertEqual(result["値幅区分"],"拡大")

    def test_W0全保持とW1準備とW2非拡大を分ける(self) -> None:
        """準備なしでも旧純登録を維持し、現ATRを前へ替えない。

        引数: self(TestCase)は対象。
        返り値: None。全三集合は純13列を保つ。
        """
        for prior_atr,expected in ((25.,(1,1,1)),(20.,(1,1,1)),(15.,(1,1,0)),(None,(1,0,0))):
            material=block();material["frames"][3][0]["atr"]=prior_atr
            result=I.select(material)
            self.assertEqual(tuple(len(result["signals"]["3分_"+p]) for p in I.POLICIES),expected)
            self.assertEqual(result["signals"]["3分_W0"][0]["atr"],25.)

    def test_当場隣接公開有効3分だけを前足にする(self) -> None:
        """古正常や欠枠/不正足で幅を計算しない。

        引数: self(TestCase)は対象。
        返り値: None。各不準備でも旧W0を維持する。
        """
        changes=[{"missing":1},{"open":None},{"start":1441.},{"end":1619.},{"index":-1}]
        for change in changes:
            material=block();material["frames"][3][0].update(change)
            result=I.select(material)
            self.assertTrue(result["signals"]["3分_W0"])
            self.assertFalse(result["signals"]["3分_W1"])
        wrong=block();wrong["frames"][3][0]["場"]="前場"
        with self.assertRaises(ValueError):I.select(wrong)

    def test_NP未来前足の存在で過去decision理由を変えない(self) -> None:
        """不存在と不可視前足をNone同理由にする。

        引数: self(TestCase)は対象。
        返り値: None。全decisionと純集合のprefixが不変。
        """
        base=block();previous=base["frames"][3].pop(0)
        expected=I.select(deepcopy(base))
        for change in ({"publish":False},{"confirm":1811.},{"end":1801.}):
            hidden=deepcopy(previous);hidden.update(change)
            candidate=deepcopy(base);candidate["frames"][3].insert(0,hidden)
            actual=I.select(candidate)
            self.assertEqual(actual["decisions"],expected["decisions"])
            self.assertEqual(actual["signals"],expected["signals"])
            self.assertIsNone(expected["decisions"][0]["前足参照"])

    def test_鏡像でTR全精密値と採否を保つ(self) -> None:
        """値幅へ売買の方向票を混ぜない。

        引数: self(TestCase)は対象。
        返り値: None。三距離の対応は交換してもTR/比は同一。
        """
        material=block();mirror=deepcopy(material)
        row=mirror["signals"]["3分_J0"][0]
        row.update(side=-1,方向="売り",low=20000.-row["high"],high=20000.-row["low"])
        for f in mirror["frames"][3]:
            old=deepcopy(f);f.update(open=20000.-old["open"],close=20000.-old["close"],high=20000.-old["low"],low=20000.-old["high"])
        mirror["下位出典"][row["イベントID"]]={k:deepcopy(mirror["frames"][3][-1][k]) for k in I.SOURCE_FIELDS}
        buy,sell=I.select(material),I.select(mirror)
        for key in ("TR","TR前ATR差","TR前ATR比","TR前ATR差符号","値幅区分","戦略判定"):
            self.assertEqual(buy["decisions"][0][key],sell["decisions"][0][key])

    def test_純13列と現ATRsourceを厳密保持する(self) -> None:
        """量/MACD/未来列を参照へ増やさず現ATRコピー差を拒否する。

        引数: self(TestCase)は対象。
        返り値: None。元時点の全値を保持する。
        """
        old=signal();old.update(ラベル="未来",最大順行pt=99999.)
        result=I.select(block([old]))
        for rows in result["signals"].values():self.assertEqual(set(rows[0]),set(I.SIGNAL_FIELDS))
        for key in ("当足参照","前足参照"):self.assertEqual(set(result["decisions"][0][key]),set(I.FRAME_FIELDS))
        bad=block();bad["signals"]["3分_J0"][0]["atr"]+=1e-12
        with self.assertRaises(ValueError):I.select(bad)
        with self.assertRaises(ValueError):I.select(block([signal(),signal(event="別")]))

    def test_独立包絡TRと全decision純集合を照合(self) -> None:
        """主三距離maxと独立包絡幅を人工で照合する。

        引数: self(TestCase)は対象。
        返り値: None。再算ATR境界照合は正式準備と別範囲。
        """
        state=load(HERE/"状態独立確認.py","発動値幅40人工の独立入口")
        if not hasattr(state,"select"):self.skipTest("独立API完成前")
        for atr in (25.,20.,15.,0.,None):
            material=block();material["frames"][3][0]["atr"]=atr
            self.assertEqual(I.select(deepcopy(material)),state.select(deepcopy(material)))
        current,previous=price_pair()
        self.assertEqual(I.range_state(current,previous),state.range_state(current,previous))


class 固定XF検証(unittest.TestCase):
    """三XFは旧39J0とID以外全同値のまま使用する。"""

    def test_三運用買売の全台帳追尾を旧39へ合わせる(self) -> None:
        """前ATRゲートを出口Dや起動へ流用しない。

        引数: self(TestCase)は対象。
        返り値: None。全13列の現在ATRで固定XFを使う。
        """
        previous=load(ROOT/"scripts/上位中心継続/運用.py","発動値幅40人工の旧39運用")
        def renamed(value: object,old: str,new: str) -> object:
            """ID断片だけをJSON全階層で置換する。

            引数: value(object)は形状、old/new(str)はID断片。
            返り値: objectは数値を全保持する変換値。
            """
            if isinstance(value,dict):return {k:renamed(v,old,new) for k,v in value.items()}
            if isinstance(value,list):return [renamed(v,old,new) for v in value]
            return value.replace(old,new) if isinstance(value,str) else value
        for side in (1,-1):
            source=signal(side,10.,10)
            events=[S37.quote(10.,1,side,-5.),S37.quote(11.,2,side,-5.),S37.quote(12.,3,side,15.),
                S37.quote(13.,4,side,5.),S37.quote(14.,5,side,0.),S37.quote(15.,6,side,-5.)]
            old,info=previous.replay(events,[source],[],SESSION,"3分_J0_XF",CONFIG,{"出口ID":"XF"},"順行",BOUNDS)
            for policy in I.POLICIES:
                source_new=I.pure_signal(source,policy);source_new.update(ラベル="未来",TR前ATR比=99999.)
                actual,quality=O.replay(events,[source_new],[],SESSION,"3分_"+policy+"_XF",CONFIG,{"出口ID":"XF"},"順行",BOUNDS)
                for key in ("fills","trades","orders","signals","normal_log"):
                    self.assertEqual(getattr(actual,key),renamed(getattr(old,key),"_J0","_"+policy))
                self.assertEqual(quality,renamed(info,"_J0","_"+policy))
                self.assertEqual(len(actual.trades),1)


def driver_module() -> Any:
    """主CLIを起動せず現在の定義を人工へ読み込む。

    引数: なし。
    返り値: Anyは市場I/Oを遮断した主モジュール。
    """
    return load(HERE/"検証.py","発動値幅40合成の主検証")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """主CLI用の人工場・参照・純材料を一時先だけへ作る。

    引数: driver(Any)は主、count(int)は人工場数。
    返り値: Iterator[Any]は一時study/workと純bundle/buildの束。
    """
    with tempfile.TemporaryDirectory(prefix="発動値幅40合成_",dir=ROOT/"work") as temporary:
        folder=Path(temporary);study,work=folder/"study",folder/"work"
        study.mkdir();work.mkdir()
        config=driver.expected_config()
        driver.W.write_json(study/"条件.json",config)
        for name in ("入力台帳.json","入口参照.json","対照参照.json","指標参照.json"):
            driver.W.write_json(study/name,{"人工":True})
        (study/"計画.md").write_text("人工の固定対象\n",encoding="utf-8")
        driver.W.write_json(work/"診断予定.json",{"人工":True})
        sessions=[str(date(2026,9,22)+timedelta(days=i//2))+ ("_Day" if i%2==0 else "_Night") for i in range(count)]
        bundle={"pure":{},"metadata":{},"lower":{},"lower_sources":{},"input_quality":{}}
        for name in sessions:
            old=signal(clock=10.,line=10,event="人工P_"+name);old["場"]=name
            material=block([old],end=10.);material["場"]=name
            for source_frame in material["frames"][3]:source_frame["場"]=name
            bundle["pure"][name]=[old]
            bundle["lower"][name]=material["frames"][3]
            bundle["lower_sources"][name]=material["下位出典"]
            bundle["input_quality"][name]={"場":name}
            bundle["metadata"][old["イベントID"]]={"元価格発動ID":old["イベントID"][:-3],"元価格side":-1}

        def built(entry: dict, manifest: dict, shared: dict, current: dict, include_events: bool = False) -> dict:
            """元13列を当場の人工上位へ結び、正式だけ人工気配を返す。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式経路。
            返り値: dictは人工場材料。実source/stat/cacheを参照しない。
            """
            name=entry["session"]
            material={"場":name,"signals":{"3分_J0":deepcopy(shared["pure"][name])},
                "frames":{3:deepcopy(shared["lower"][name])},"下位出典":deepcopy(shared["lower_sources"][name]),
                "input_quality":deepcopy(shared["input_quality"][name]),"events":[],"cutoff":9000.,"deadline":9500.,"duration":10000./60}
            driver.I.select(material,name)
            if include_events:
                material["events"]=[S37.quote(10.,1,1,-5.),S37.quote(11.,2,1,-5.),S37.quote(12.,3,1,15.),
                    S37.quote(13.,4,1,5.),S37.quote(14.,5,1,0.),S37.quote(15.,6,1,-5.)]
            return material

        yield SimpleNamespace(study=study,work=work,config=config,bundle=bundle,built=built,
            manifest={"source_root":"人工予約だけ","entries":[{"session":s} for s in sessions]},
            ref={"文書と証明":{},"共有明細":[]})


class 主接続検証(unittest.TestCase):
    """共有読取・非損益準備・正式末尾・固定joinを人工だけで検査する。"""

    def test_39共有橋188caseは純ATRまでstrictで上位を返さない(self) -> None:
        """旧39束と直接caseを二重照合し、旧29の3分だけを共有する。

        引数: self(TestCase)は対象。
        返り値: None。未来labelへ触れずコピーATR差も拒否する。
        """
        driver=driver_module()
        class FuturePoison(dict):
            """未来列の取得を禁止する人工case。"""
            def __getitem__(self,key: str) -> Any:
                """過去の必須列だけ取得する。

                引数: key(str)は列。
                返り値: Anyは過去値。未来列なら例外。
                """
                if key in driver.LABEL_FIELDS:raise AssertionError("準備でlabelを読まない")
                return super().__getitem__(key)
        rows,metadata,sources,cases,lower=[],{},{},[],[]
        for index in range(188):
            old=signal(clock=1000.+index*180,line=index+1,event="人工旧"+str(index))
            old.update(入口ID="3分_H0",イベントID="人工旧"+str(index)+"_H0")
            rows.append(old);metadata[old["イベントID"]]={"元価格発動ID":old["イベントID"][:-3],"元価格side":-1}
            numeric={"場":SESSION,**frame(index),"atr":25.}
            lower.append(numeric);sources[old["イベントID"]]={k:numeric[k] for k in I.SOURCE_FIELDS}
            clean=driver.M.I.pure_signal(old,"J0")
            cases.append(FuturePoison({**clean,**{k:"取得不可" for k in driver.LABEL_FIELDS}}))
        bundle={"pure":{SESSION:rows},"metadata":metadata,"lower_sources":{SESSION:sources},
            "lower":{SESSION:lower},"upper":{"使用禁止":"旧上位は持ち込まない"},"input_quality":{SESSION:{"場":SESSION}}}
        def read_rows(path: Path) -> list[dict]:
            """人工39case又は旧29全3分だけを返す。

            引数: path(Path)は人工共有名。
            返り値: list[dict]は過去数値又はlabel拒否case。
            """
            return lower if path.name=="全指標.jsonl.gz" else cases
        with patch.object(driver,"validate_reference",return_value={}),patch.object(driver.M,"read_bundle",return_value=bundle), \
                patch.object(driver,"shared_path",side_effect=lambda r,n:Path(n)),patch.object(driver,"read_rows",side_effect=read_rows):
            result=driver.read_bundle(driver.STUDY)
            self.assertEqual(len(result["metadata"]),188)
            self.assertNotIn("upper",result)
            self.assertEqual(set(result["pure"][SESSION][0]),set(I.SIGNAL_FIELDS))
            self.assertEqual(result["lower"][SESSION],lower)
            cases[0]["atr"]+=1e-12
            with self.assertRaises(ValueError):driver.read_bundle(driver.STUDY)

    def test_CLI人工66準備は先着運用損益と正式共有labelを呼ばない(self) -> None:
        """元T1の全同値を確認しながら正式価格経路を遮断する。

        引数: self(TestCase)は対象。
        返り値: None。CLI --prepareまで人工入出力だけで通す。
        """
        driver=driver_module()
        with artificial_driver(driver,66) as f, \
                patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                patch.object(driver,"read_bundle",return_value=f.bundle),patch.object(driver,"build_session",side_effect=f.built) as built, \
                patch.object(driver,"read_rows",side_effect=AssertionError("準備から正式共有labelを読まない")), \
                patch.object(driver,"freeze",side_effect=AssertionError("準備を固定しない")), \
                patch.object(driver.W.OLD,"気配経路",side_effect=AssertionError("準備から先着を呼ばない")), \
                patch.object(driver.W.PREP,"read_events",side_effect=AssertionError("準備からcacheを読まない")), \
                patch.object(driver.E,"entry_metrics",side_effect=AssertionError("準備から先着集計しない")), \
                patch.object(driver.S,"operation_metrics",side_effect=AssertionError("準備から運用集計しない")), \
                patch.object(driver.ENGINE,"replay",side_effect=AssertionError("準備から運用しない")), \
                patch.object(sys,"argv",["検証.py","--study",str(f.study),"--work",str(f.work),"--prepare"]),redirect_stdout(io.StringIO()):
            driver.main()
            proof=driver.W.read_json(f.work/"準備点検.json")
            self.assertEqual(len(proof["準備"]),66)
            self.assertEqual(proof["旧J0登録数"],66)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertTrue(proof["旧39J0純登録同値"])
            self.assertTrue(all(c.args[-1] is False for c in built.call_args_list))
            self.assertFalse((f.study/"結果.json").exists())
            self.assertFalse(any((f.work/n).exists() for n in driver.FILES))

    def test_人工正式三case三運用とH0旧対照を全属性で保存する(self) -> None:
        """新先着を同時計に一回評価し、全三運用を正式末尾へ通す。

        引数: self(TestCase)は対象。
        返り値: None。実gzip/気配は読まず人工完結を保存する。
        """
        driver=driver_module()
        with artificial_driver(driver,1) as f:
            session=f.manifest["entries"][0]["session"]
            material=f.built(f.manifest["entries"][0],f.manifest,f.bundle,f.config,True)
            old=f.bundle["pure"][session][0]
            previous=load(ROOT/"scripts/上位中心継続/運用.py","発動値幅40主人工の旧運用")
            old_state,old_info=previous.replay(material["events"],[old],material["frames"][3],session,driver.CONTROL_ID,
                f.config["運用"],{"出口ID":"XF"},"順行",BOUNDS)
            phase=driver.E.phase_of(session,f.config)
            old_info.update(期間=phase,場時間分=material["duration"])
            for trade in old_state.trades:trade["期間"]=phase
            old_detail={"候補ID":driver.CONTROL_ID,"場":session,"品質":old_info,"約定":old_state.fills,
                "取引":old_state.trades,"注文":old_state.orders,"入口取扱":old_state.signals}
            old_logs=[{"期間":phase,**r} for r in old_state.normal_log]
            label={"ラベル":"未約定","理由":"人工先着APIだけ",**{k:None for k in driver.LABEL_FIELDS[2:]}}
            called,evaluated=[],[]

            def read_rows(path: Path) -> list[dict]:
                """人工旧case/ledger/traceだけを返す。

                引数: path(Path)は人工共有名。
                返り値: list[dict]は人工保存値。
                """
                return {"入口事例.jsonl.gz":[{**old,**label}],"全運用詳細.jsonl.gz":[old_detail],"追尾.jsonl.gz":old_logs}[path.name]

            def evaluate(now: float, cutoff: float, deadline: float, side: int, **kwargs: object) -> dict:
                """同じ要求/方向の新先着API契約だけを検査する。

                引数: now/cutoff/deadline(float)は時計、side(int)は方向、kwargs(object)は125/250。
                返り値: dictは人工ラベル。市場価格を走査しない。
                """
                self.assertEqual(kwargs,{"adverse":125,"favorable":250})
                evaluated.append((now,side))
                return deepcopy(label)

            original=driver.ENGINE.replay
            def replayed(*args: Any,**kwargs: Any) -> Any:
                """純13列と三運用を人工XFへ通す。

                引数: args/kwargs(Any)は主運用契約。
                返り値: Anyは人工時刻範囲の固定XF。
                """
                self.assertTrue(all(set(r)==set(I.SIGNAL_FIELDS) for r in args[1]))
                called.append(args[4])
                return original(*args,**kwargs,bounds=BOUNDS)

            def published(study: Path,*args: Any) -> None:
                """Viewer出力境界を人工三資源へ置換する。

                引数: study(Path)は一時先、args(Any)は主契約。
                返り値: None。実価格のViewerを起動しない。
                """
                driver.W.write_json(study/"一覧.resources.json",{"resources":[{"id":"00008_人工"+str(i)} for i in range(3)]})

            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                    patch.object(driver,"read_bundle",return_value=f.bundle),patch.object(driver,"build_session",side_effect=f.built), \
                    patch.object(driver,"read_rows",side_effect=read_rows),patch.object(driver,"shared_path",side_effect=lambda r,n:f.work/n), \
                    patch.object(driver,"freeze",return_value={}),patch.object(driver.W.OLD,"気配経路",return_value=SimpleNamespace(evaluate=evaluate)), \
                    patch.object(driver.ENGINE,"replay",side_effect=replayed),patch.object(driver.E,"publish_details",side_effect=published),redirect_stdout(io.StringIO()):
                result=driver.run(f.study,f.work,False)
            self.assertEqual((result["入口評価数"],result["運用候補数"]),(3,3))
            self.assertEqual(called,["3分_"+p+"_XF" for p in I.POLICIES])
            self.assertEqual(evaluated,[(10.,1)])
            self.assertTrue(driver.W.read_json(f.study/"W0対照同値.json")["全件一致"])
            import gzip
            with gzip.open(f.work/"入口事例.jsonl.gz","rt",encoding="utf-8") as stream:cases=[json.loads(r) for r in stream]
            with gzip.open(f.work/"全運用詳細.jsonl.gz","rt",encoding="utf-8") as stream:details=[json.loads(r) for r in stream]
            self.assertEqual(len(cases),3)
            self.assertEqual(len(details),3)
            self.assertEqual(driver.rename(details[0],"_W0","_J0"),old_detail)
            saved=driver.W.read_json(f.study/"結果.json")
            self.assertEqual(len(saved["役割別入口評価"]),3)
            self.assertTrue(all(r["役割"]=="順行" for r in saved["役割別入口評価"]))

    def test_条件driftとpartialを市場処理前に拒否する(self) -> None:
        """既存正式中間物や条件変更で再処理を始めない。

        引数: self(TestCase)は対象。
        返り値: None。一時先以外の正本は変更しない。
        """
        driver=driver_module()
        with artificial_driver(driver,1) as f:
            bad=deepcopy(f.config);bad["発動値幅継続"]["W2"]="後付け変更"
            with self.assertRaises(ValueError):driver.validate_config(bad)
            (f.work/driver.FILES[0]).write_bytes("人工partial".encode("utf-8"))
            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                    patch.object(driver,"read_bundle",side_effect=AssertionError("partial後に資料を開かない")):
                with self.assertRaises(ValueError):driver.run(f.study,f.work,False)

    def test_三共有参照の証明欠落と固定共有ドリフトを拒否(self) -> None:
        """圧縮/展開の実読取を宣言値へ置換して参照契約を検査する。

        引数: self(TestCase)は対象。
        返り値: None。旧明細を開かず小型宣言だけを人工へ写す。
        """
        driver=driver_module()
        for name in ("入口参照.json","対照参照.json","指標参照.json"):
            pointer=driver.W.read_json(driver.STUDY/name)
            declared={normalized(ROOT/r["パス"]):r["圧縮SHA256参考"] for r in pointer["共有明細"]}
            expanded={normalized(ROOT/r["パス"]):r["展開内容SHA256"] for r in pointer["共有明細"]}
            original=driver.O.sha
            with artificial_driver(driver,1) as f, \
                    patch.object(driver.O,"sha",side_effect=lambda p:declared.get(normalized(p),original(p)) if normalized(p) not in declared else declared[normalized(p)]), \
                    patch.object(driver,"content_sha",side_effect=lambda p:expanded[normalized(p)]):
                driver.W.write_json(f.study/name,pointer)
                driver.validate_reference(f.study,name)
                for key in ("文書と証明","共有明細"):
                    bad=deepcopy(pointer)
                    if key=="文書と証明":bad[key].pop(next(iter(bad[key])))
                    else:bad[key]=[]
                    driver.W.write_json(f.study/name,bad)
                    with self.assertRaises(ValueError):driver.validate_reference(f.study,name)
                bad=deepcopy(pointer);bad["旧固定SHA256"]="0"*64
                driver.W.write_json(f.study/name,bad)
                with self.assertRaises(ValueError):driver.validate_reference(f.study,name)

    def test_固定は主独立準備と最終人工の現版を必須joinする(self) -> None:
        """独立欠落/失敗/古版や固定後変更を正式前に止める。

        引数: self(TestCase)は対象。
        返り値: None。固定ファイルは人工一時先だけへ作る。
        """
        driver=driver_module()
        if not (HERE/"追尾独立確認.py").exists():self.skipTest("独立CLI完成前の途中人工")
        with artificial_driver(driver,1) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",return_value=f.bundle), \
                patch.object(driver,"build_session",side_effect=f.built),redirect_stdout(io.StringIO()):
            driver.run(f.study,f.work,True)
            dep=ROOT/"scripts/OBV反転/入口.py"
            proof={"全件一致":True,"不一致数":0,"不一致":[],"ラベル計算":False,"損益計算":False,
                "主準備SHA256":sha(f.work/"準備点検.json"),"主コードSHA256":driver.code_pins(),
                "条件SHA256":sha(f.study/"条件.json"),"入力台帳SHA256":sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256":sha(driver.MANIFEST_PATH),"入口参照SHA256":sha(f.study/"入口参照.json"),
                "対照参照SHA256":sha(f.study/"対照参照.json"),"指標参照SHA256":sha(f.study/"指標参照.json"),
                "コードSHA256":sha(HERE/"状態独立確認.py"),"追尾コードSHA256":sha(HERE/"追尾独立確認.py"),
                "依存コードSHA256":{dep.relative_to(ROOT).as_posix():sha(dep)}}
            synthetic={"全件成功":True,"合成編集終了":False,"ファイルSHA256":{p.relative_to(ROOT).as_posix():sha(p)
                for p in [HERE/n for n in ("検証.py","入口.py","運用.py","合成検証.py")]+[f.study/"条件.json"]},
                "独立数値補助SHA256":sha(HERE/"状態独立確認.py"),"独立追尾補助SHA256":sha(HERE/"追尾独立確認.py")}
            synthetic_file=f.work/"人工最終合成.json"
            driver.W.write_json(synthetic_file,synthetic)
            independent=f.work/"独立準備点検.json"
            old_read,old_sha=driver.W.read_json,driver.O.sha
            def read_json(path: Path) -> dict:
                """旧pinsと最終人工だけを人工宣言へ置換する。

                引数: path(Path)は証拠パス。
                返り値: dictは人工宣言又は既存小型正本。
                """
                if normalized(path)==normalized(driver.PREVIOUS/"固定.json"):
                    return {"ファイルSHA256":{dep.relative_to(ROOT).as_posix():sha(dep)}}
                return deepcopy(synthetic) if normalized(path)==normalized(WORK/"合成検証.json") else old_read(path)
            def current_sha(path: Path) -> str:
                """最終人工参照のSHAだけ一時証拠へ向ける。

                引数: path(Path)はパス。
                返り値: strは人工又は実小型正本SHA。
                """
                return sha(synthetic_file) if normalized(path)==normalized(WORK/"合成検証.json") else old_sha(path)
            with patch.object(driver.W,"read_json",side_effect=read_json),patch.object(driver.O,"sha",side_effect=current_sha):
                with self.assertRaises(FileNotFoundError):driver.freeze(f.study,f.work)
                driver.W.write_json(independent,proof)
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                synthetic["合成編集終了"]=True
                for key in proof:
                    wrong=deepcopy(proof)
                    wrong[key]=not proof[key] if isinstance(proof[key],bool) else "不一致" if not isinstance(proof[key],dict) else {}
                    driver.W.write_json(independent,wrong)
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                driver.W.write_json(independent,proof)
                for key in ("独立数値補助SHA256","独立追尾補助SHA256"):
                    actual=synthetic[key];synthetic[key]="0"*64
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                    synthetic[key]=actual
                driver.W.write_json(synthetic_file,synthetic)
                locked=driver.freeze(f.study,f.work)
                self.assertEqual(driver.freeze(f.study,f.work),locked)
                self.assertEqual(locked["独立準備SHA256"],sha(independent))
                (f.study/"計画.md").write_text("人工固定後変更\n",encoding="utf-8")
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                driver.W.write_json(f.study/"結果.json",{"人工":True})
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)




def main() -> None:
    """人工検査だけを起動し、固定前/最終の小型証明を保存する。

    引数: CLI --final(bool)はroot許可後に一回だけ指定する。
    返り値: None。市場原板/cache/先着/PnLは使用しない。
    """
    parser=argparse.ArgumentParser(description="発動値幅継続の人工検査")
    parser.add_argument("--final",action="store_true")
    args=parser.parse_args()
    paths=[HERE/n for n in ("検証.py","入口.py","運用.py","合成検証.py")]
    paths.append(ROOT/"study/00040_外側継続と発動足の相対値幅/条件.json")
    paths=[p for p in paths if p.exists()]
    helpers=[p for p in (HERE/"状態独立確認.py",HERE/"追尾独立確認.py") if p.exists()]
    pins={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    before={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    with deny_market():result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged=pins=={p.relative_to(ROOT).as_posix():sha(p) for p in paths} and before=={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    success=result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    if args.final and (len(pins)!=5 or len(before)!=2):raise ValueError("主3code/条件/合成と独立二code完成前")
    proof={"全件成功":success,"検証件数":result.testsRun,"合成編集終了":bool(args.final and success),"市場入力読取":False,
        "市場先着損益計算":False,"実行中コード条件不変":unchanged,"ファイルSHA256":pins,
        "独立数値補助SHA256":before.get("scripts/発動値幅継続/状態独立確認.py"),
        "独立追尾補助SHA256":before.get("scripts/発動値幅継続/追尾独立確認.py"),
        "skip数":len(result.skipped),"失敗数":len(result.failures),"エラー数":len(result.errors)}
    WORK.mkdir(parents=True,exist_ok=True)
    path=WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"出力":str(path),"全件成功":success,"件数":result.testsRun,"SHA256":sha(path)},ensure_ascii=False))
    if not success:raise SystemExit(1)


if __name__=="__main__":
    main()


