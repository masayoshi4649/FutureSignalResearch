"""実市場I/Oを遮断し、上位の準備・値・公開時点と固定XFの接続を検査する。"""

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
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
WORK = ROOT/"work/上位中心継続"
SESSION = "人工上位中心場"
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
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("上位中心39合成_")
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


I = load(HERE/"入口.py", "上位中心39合成の入口")
O = load(HERE/"運用.py", "上位中心39合成の運用")
J = load(ROOT/"scripts/一目基準線/指標.py", "上位中心39合成の固定28銀行")
S37 = load(ROOT/"scripts/構造判別/合成検証.py", "上位中心39合成の固定37人工補助")
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
    """既に競合後の旧38H0純13列を作る。

    引数: side(int)は実方向、clock/line(float/int)とevent(str)は出典。
    返り値: dictは固定役割の旧H0。
    """
    row = S37.signal("T1", side, "順行", event, clock, line)
    row.update(場=SESSION,入口ID="3分_H0",イベントID=event+"_H0")
    return row


def block(rows: list[dict] | None = None, end: float = 1800.) -> dict:
    """旧T1純集合と番号で確定した下位出典をまとめる。

    引数: rows(list[dict]|None)は純入口、end(float)は最初の足終了。
    返り値: dictは市場labelや元rawを持たない入力。
    """
    originals = [signal()] if rows is None else deepcopy(rows)
    frames, sources = [], {}
    for index, row in enumerate(originals):
        current = frame(index, end=end+index*180, confirm=row["要求時計秒"], confirm_line=row["要求原板行"])
        frames.append(current)
        sources[row["イベントID"]] = deepcopy(current)
    return {"場": SESSION, "signals": {"3分_H0": originals}, "frames": {3: frames}, "下位出典": sources}


def upper(index: int = 0, **updates: object) -> dict:
    """準備済みの人工15分と不要な旧数値を作る。

    引数: index(int)は番号、updates(object)は変更。
    返り値: dictは一目限定列へ投影できる保存28形状。
    """
    return {"場": SESSION, **frame(index, 15, end=900., confirm=900., confirm_line=index+1),
        "close": 10020., "ichimoku_tenkan": 10010., "ichimoku_kijun": 10000.,
        "ichimoku_a": 10005., "ichimoku_b": 9990., "cloud_a": 10000., "cloud_b": 10010.,
        "cloud_upper": 10010., "cloud_lower": 10000., "雲計算元足": {"場": "人工前場", **frame(0, 15)},
        "一目数値入力可": True, "一目準備済": True, "一目公開可": True, "一目窓本数": 78,
        "銀行解除理由": [], "atr": 777., "stoch_raw": 99., "Fast差厳密符号": -1,
        "未来ラベル": "250", **updates}


def reflect_upper(row: dict, total: float = 20000.) -> dict:
    """上位OHLCと一目を上下反射する。

    引数: row(dict)は上位、total(float)は反射価格和。
    返り値: dictは時計/準備状態を保つ鏡像。
    """
    result = deepcopy(row)
    result.update(open=total-row["open"], close=total-row["close"], high=total-row["low"], low=total-row["high"])
    for name in I.ICHI_FIELDS:
        result[name] = None if row[name] is None else total-row[name]
    result["cloud_lower"] = None if row["cloud_upper"] is None else total-row["cloud_upper"]
    result["cloud_upper"] = None if row["cloud_lower"] is None else total-row["cloud_lower"]
    return result


def pair(**updates: object) -> list[dict]:
    """雲未準備でもJ26現前が揃う人工27本目の公開ペアを作る。

    引数: updates(object)は現足の変更。
    返り値: list[dict]は前/現の限定27列へ射影できる足。
    """
    previous=upper(25,start=0.,end=900.,confirm=901.,confirm_line=1,ichimoku_kijun=10000.)
    current=upper(26,start=900.,end=1800.,confirm=1801.,confirm_line=2,ichimoku_kijun=10005.,
        一目公開可=False,一目準備済=False,cloud_a=None,cloud_b=None,cloud_upper=None,cloud_lower=None,一目窓本数=27)
    current.update(updates)
    return [previous,current]


class 基準進行検証(unittest.TestCase):
    """個別J準備・時間変化・前足の公開時点を検査する。"""

    def test_J0全保持とJ1個別準備は雲公開可を要求しない(self) -> None:
        """旧H0と同じ時点で準備だけと値だけを分離する。

        引数: self(TestCase)は対象。
        返り値: None。雲未準備の27本区間でもJ1/J2を許す。
        """
        for rows,expected in (([],(1,0,0)),(pair(),(1,1,1)),(pair(ichimoku_kijun=10000.),(1,1,0))):
            initial=block();old=deepcopy(initial["signals"]["3分_H0"][0])
            result=I.select(initial,rows)
            self.assertEqual(tuple(len(result["signals"]["3分_"+p]) for p in I.POLICIES),expected)
            baseline=deepcopy(result["signals"]["3分_J0"][0]);baseline.update(イベントID=old["イベントID"],入口ID=old["入口ID"])
            self.assertEqual(baseline,old)
        decision=I.select(block(),pair())["decisions"][0]
        self.assertFalse(decision["上位参照"]["一目公開可"])
        self.assertTrue(decision["上位現前準備"])
        self.assertEqual(decision["基準線差厳密分子"],5)
        self.assertEqual(decision["基準線差厳密分母"],1)

    def test_進行正零負をstrict比較して売買鏡像を保つ(self) -> None:
        """基準差の符号を表示floatの丸め閾値へ変えない。

        引数: self(TestCase)は対象。
        返り値: None。等号は両側不採用。
        """
        for current,kind in ((10005.,"同方向"),(10000.,"等号"),(9995.,"逆方向")):
            buy=I.select(block(),pair(ichimoku_kijun=current))
            sell=I.select(block([signal(-1)]),[reflect_upper(r) for r in pair(ichimoku_kijun=current)])
            for result in (buy,sell):
                self.assertEqual(result["decisions"][0]["進行方向"],kind)
                self.assertEqual(bool(result["signals"]["3分_J2"]),kind=="同方向")
            self.assertEqual(buy["decisions"][0]["基準線差厳密符号"],-sell["decisions"][0]["基準線差厳密符号"])

    def test_最新不良に古正常ペアfallbackをしない(self) -> None:
        """Jが古い良好ペアにあっても最新の不準備を保持する。

        引数: self(TestCase)は対象。
        返り値: None。元要求を後続公開へ取り直さない。
        """
        rows=pair()
        bad=upper(27,start=1800.,end=2700.,confirm=2701.,confirm_line=3,ichimoku_kijun=None)
        source=block([signal(clock=2710.)],end=2700.)
        result=I.select(source,rows+[bad])
        self.assertEqual(result["decisions"][0]["上位参照"]["index"],27)
        self.assertFalse(result["signals"]["3分_J1"])
        self.assertTrue(result["signals"]["3分_J0"])

    def test_ペアの各完全幅欠枠入力数値隣接条件を守る(self) -> None:
        """現在雲の準備とJペアの準備を混ぜない。

        引数: self(TestCase)は対象。
        返り値: None。各欠測はJ0保持/J1除外となる。
        """
        variants=[(0,{"missing":1}),(1,{"missing":1}),(0,{"一目数値入力可":False}),
            (1,{"一目数値入力可":False}),(0,{"ichimoku_kijun":None}),(1,{"ichimoku_kijun":None}),
            (0,{"start":1.}),(1,{"end":1799.}),(0,{"end":899.}),(0,{"index":24})]
        for position,change in variants:
            rows=pair();rows[position].update(change)
            result=I.select(block(),rows)
            self.assertTrue(result["signals"]["3分_J0"])
            self.assertFalse(result["signals"]["3分_J1"])

    def test_未来またはNP前足の追加除去で全判定純列が不変(self) -> None:
        """未公開前候補の存在をsnapshotや理由へ露出させない。

        引数: self(TestCase)は対象。
        返り値: None。前参照None/同一理由を保持する。
        """
        previous,current=pair()
        expected=I.select(block(),[current])
        for change in ({"publish":False},{"confirm":1811.},{"end":1801.}):
            hidden=deepcopy(previous);hidden.update(change)
            actual=I.select(block(),[hidden,current])
            self.assertEqual(actual,expected)
            self.assertIsNone(actual["decisions"][0]["前上位参照"])
            self.assertEqual(actual["decisions"][0]["準備除外理由"],["前上位公開参照なし"])
        future=upper(27,start=1800.,end=2700.,confirm=2701.)
        self.assertEqual(I.select(block(),[previous,current]),I.select(block(),[previous,current,future]))

    def test_公開前後順ガードはpair_state単体の防御契約(self) -> None:
        """key優先latestでは通常到達しない異常ペアを単体で拒否する。

        引数: self(TestCase)は対象。
        返り値: None。selectの最新定義をend/index優先へ替えない。
        """
        previous,current=pair();previous["confirm"]=1805.
        lower=next(iter(block()["下位出典"].values()))
        result=I.pair_state(I.upper_projection(current),I.upper_projection(previous),lower,1)
        self.assertFalse(result["上位現前準備"])
        self.assertIn("前後公開順不整合",result["準備除外理由"])

    def test_asof両条件と同keyと当場を守る(self) -> None:
        """終了だけ又はkeyだけで未来uを参照しない。

        引数: self(TestCase)は対象。
        返り値: None。同key可/後行不可と前場排除を照合する。
        """
        previous,current=pair()
        same=deepcopy(current);same.update(confirm=1810.,confirm_line=20)
        result=I.select(block(),[previous,same])
        self.assertTrue(result["signals"]["3分_J2"])
        later=deepcopy(same);later["confirm_line"]=21
        result=I.select(block(),[previous,later])
        self.assertEqual(result["decisions"][0]["上位参照"]["index"],25)
        future=deepcopy(current);future.update(end=1801.,confirm=1802.)
        self.assertEqual(I.select(block(),[previous,future])["decisions"][0]["上位参照"]["index"],25)
        with self.assertRaises(ValueError):I.select(block(),[upper(場="前場")])

    def test_TJ静的整列とJ時間進行は互いに同値ではない(self) -> None:
        """TJ診断の良い群を進行条件へ混ぜない。

        引数: self(TestCase)は対象。
        返り値: None。静的正/進行0と静的逆/進行正を区別する。
        """
        flat=I.select(block(),pair(ichimoku_kijun=10000.,ichimoku_tenkan=10010.))
        moving=I.select(block(),pair(ichimoku_kijun=10005.,ichimoku_tenkan=9990.))
        self.assertEqual(flat["decisions"][0]["TJ方向"],"同方向")
        self.assertFalse(flat["signals"]["3分_J2"])
        self.assertEqual(moving["decisions"][0]["TJ方向"],"逆方向")
        self.assertTrue(moving["signals"]["3分_J2"])

    def test_純13列snapshot出典と競合後集合の前提を守る(self) -> None:
        """上位や将来labelをliveへ渡さずコピーも候補間で共有しない。

        引数: self(TestCase)は対象。
        返り値: None。元13列のATRも変更しない。
        """
        source=signal();source.update(ラベル="未来",最大順行pt=99999.)
        result=I.select(block([source]),pair())
        for rows in result["signals"].values():self.assertEqual(set(rows[0]),set(I.SIGNAL_FIELDS))
        result["signals"]["3分_J0"][0]["atr"]=0
        self.assertEqual(result["signals"]["3分_J1"][0]["atr"],25.)
        bad=block();bad["下位出典"]["人工旧P_H0"]["end"]-=1
        with self.assertRaises(ValueError):I.select(bad,pair())
        with self.assertRaises(ValueError):I.select(block([signal(),signal(event="別")]),pair())
        self.assertEqual(I.select(block([]),[]) ["signals"],{"3分_J0":[],"3分_J1":[],"3分_J2":[]})

    def test_独立全列挙のペア数値採否を全属性照合(self) -> None:
        """主pointerと独立の上位全列挙を人工で照合する。

        引数: self(TestCase)は対象。
        返り値: None。未完成段階は最終前だけ省略する。
        """
        state=load(HERE/"状態独立確認.py","上位中心39人工の独立入口")
        if not hasattr(state,"select"):self.skipTest("独立API完成前")
        for rows in ([],pair(),pair(ichimoku_kijun=10000.),pair(ichimoku_kijun=9995.),[pair()[1]]):
            self.assertEqual(I.select(block(),deepcopy(rows)),state.select(block(),deepcopy(rows)))


class 数値定義と運用検証(unittest.TestCase):
    """固定28数値の27本準備と旧38XF完全対照を検査する。"""

    def test_現前J最速27で雲は未準備でも採用できる(self) -> None:
        """J個別準備へ78本雲準備を混入させない。

        引数: self(TestCase)は対象。
        返り値: None。J現前と差は人工原高安から確認する。
        """
        frames=[frame(i,15,open=1000.+i,high=1010.+i,low=990.+i,close=1000.+i) for i in range(27)]
        rows,_=J.NumericBank(15).build(frames,SESSION,(2026,12))
        self.assertIsNone(rows[24]["ichimoku_kijun"])
        self.assertEqual(rows[25]["ichimoku_kijun"],1012.5)
        self.assertEqual(rows[26]["ichimoku_kijun"],1013.5)
        self.assertFalse(rows[26]["一目公開可"])
        old=signal(clock=rows[26]["confirm"]+10,line=100)
        result=I.select(block([old],end=rows[26]["end"]),rows)
        self.assertTrue(result["signals"]["3分_J2"])
        self.assertEqual(result["decisions"][0]["基準線差"],1.)

    def test_古い安値脱落だけでもJは上昇し得る(self) -> None:
        """J進行を新高値更新や現在終値上昇の保証としない。

        引数: self(TestCase)は対象。
        返り値: None。機序を診断gateへ追加しない。
        """
        frames=[frame(i,15,open=100.,high=120.,low=80. if i==0 else 90.,close=100.) for i in range(27)]
        rows,_=J.NumericBank(15).build(frames,SESSION,(2026,12))
        self.assertEqual((rows[25]["ichimoku_kijun"],rows[26]["ichimoku_kijun"]),(100.,105.))
        self.assertEqual(frames[-1]["high"],frames[-2]["high"])
        self.assertEqual(frames[-1]["close"],frames[-2]["close"])
        result=I.select(block([signal(clock=rows[-1]["confirm"]+10,line=100)],end=rows[-1]["end"]),rows)
        self.assertTrue(result["signals"]["3分_J2"])

    def test_三運用買売の全属性は旧38H0XFとID以外同じ(self) -> None:
        """新上位条件を保有や返済へ混入させない。

        引数: self(TestCase)は対象。
        返り値: None。人工現在益起動から返済まで全列一致する。
        """
        previous=load(ROOT/"scripts/上位雲継続/運用.py","上位中心39人工の固定38運用")
        def renamed(value: object, old: str, new: str) -> object:
            """識別子だけをJSON全階層で置換する。

            引数: value(object)は保存形状、old/new(str)はID断片。
            返り値: objectは数値/属性を全保持する写像。
            """
            if isinstance(value,dict):return {k:renamed(v,old,new) for k,v in value.items()}
            if isinstance(value,list):return [renamed(v,old,new) for v in value]
            return value.replace(old,new) if isinstance(value,str) else value
        for side in (1,-1):
            source=signal(side,10.,10)
            events=[S37.quote(10.,1,side,-5.),S37.quote(11.,2,side,-5.),S37.quote(12.,3,side,15.),
                S37.quote(13.,4,side,5.),S37.quote(14.,5,side,0.),S37.quote(15.,6,side,-5.)]
            old,info=previous.replay(events,[source],[],SESSION,"3分_H0_XF",CONFIG,{"出口ID":"XF"},"順行",BOUNDS)
            for policy in I.POLICIES:
                clean=I.pure_signal(source,policy);clean.update(ラベル="未来",上位基準=99999.)
                actual,quality=O.replay(events,[clean],[],SESSION,"3分_"+policy+"_XF",CONFIG,{"出口ID":"XF"},"順行",BOUNDS)
                for key in ("fills","trades","orders","signals","normal_log"):
                    self.assertEqual(getattr(actual,key),renamed(getattr(old,key),"_H0","_"+policy))
                self.assertEqual(quality,renamed(info,"_H0","_"+policy))
                self.assertEqual(len(actual.trades),1)


def driver_module() -> Any:
    """主CLIを起動せず現在の定義を人工へ読み込む。

    引数: なし。
    返り値: Anyは市場I/Oを遮断した主モジュール。
    """
    return load(HERE/"検証.py","上位中心39合成の主検証")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """主CLI用の人工場・参照・純材料を一時先だけへ作る。

    引数: driver(Any)は主、count(int)は人工場数。
    返り値: Iterator[Any]は一時study/workと純bundle/buildの束。
    """
    with tempfile.TemporaryDirectory(prefix="上位中心39合成_",dir=ROOT/"work") as temporary:
        folder=Path(temporary);study,work=folder/"study",folder/"work"
        study.mkdir();work.mkdir()
        config=driver.expected_config()
        driver.W.write_json(study/"条件.json",config)
        for name in ("入力台帳.json","入口参照.json","対照参照.json","上位参照.json"):
            driver.W.write_json(study/name,{"人工":True})
        (study/"計画.md").write_text("人工の固定対象\n",encoding="utf-8")
        driver.W.write_json(work/"診断予定.json",{"人工":True})
        sessions=[str(date(2026,9,22)+timedelta(days=i//2))+ ("_Day" if i%2==0 else "_Night") for i in range(count)]
        bundle={"pure":{},"metadata":{},"lower":{},"lower_sources":{},"upper":{},"input_quality":{}}
        for name in sessions:
            old=signal(clock=10.,line=10,event="人工P_"+name);old["場"]=name
            material=block([old],end=10.);material["場"]=name
            previous,high=pair()
            previous.update(場=name,start=-1790.,end=-890.,confirm=-889.,confirm_line=1)
            high.update(場=name,start=-890.,end=10.,confirm=10.,confirm_line=2)
            bundle["pure"][name]=[old]
            bundle["lower"][name]=material["frames"][3]
            bundle["lower_sources"][name]=material["下位出典"]
            bundle["upper"][name]=[I.upper_projection(previous),I.upper_projection(high)]
            bundle["input_quality"][name]={"場":name}
            bundle["metadata"][old["イベントID"]]={"元価格発動ID":old["イベントID"][:-3],"元価格side":-1}

        def built(entry: dict, manifest: dict, shared: dict, current: dict, include_events: bool = False) -> dict:
            """元13列を当場の人工上位へ結び、正式だけ人工気配を返す。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式経路。
            返り値: dictは人工場材料。実source/stat/cacheを参照しない。
            """
            name=entry["session"]
            material={"場":name,"signals":{"3分_H0":deepcopy(shared["pure"][name])},
                "frames":{3:deepcopy(shared["lower"][name])},"下位出典":deepcopy(shared["lower_sources"][name]),
                "input_quality":deepcopy(shared["input_quality"][name]),"events":[],"cutoff":9000.,"deadline":9500.,"duration":10000./60}
            driver.I.select(material,shared["upper"][name],name)
            if include_events:
                material["events"]=[S37.quote(10.,1,1,-5.),S37.quote(11.,2,1,-5.),S37.quote(12.,3,1,15.),
                    S37.quote(13.,4,1,5.),S37.quote(14.,5,1,0.),S37.quote(15.,6,1,-5.)]
            return material

        yield SimpleNamespace(study=study,work=work,config=config,bundle=bundle,built=built,
            manifest={"source_root":"人工予約だけ","entries":[{"session":s} for s in sessions]},
            ref={"文書と証明":{},"共有明細":[]})


class 主接続検証(unittest.TestCase):
    """共有読取・非損益準備・正式末尾・固定joinを人工だけで検査する。"""

    def test_38共有橋188caseは未来列を読まず純ATRまでstrict確認(self) -> None:
        """旧38共有束からのH0射影と固定38自身caseを二重照合する。

        引数: self(TestCase)は対象。
        返り値: None。実共有gzipを開かず未来label参照を禁止する。
        """
        driver=driver_module()
        class FuturePoison(dict):
            """未来列への取得を拒否する人工旧case。"""
            def __getitem__(self,key: str) -> Any:
                """純13列だけの取得を許す。

                引数: key(str)は取得列。
                返り値: Anyは過去列。未来labelなら例外。
                """
                if key in driver.LABEL_FIELDS:raise AssertionError("純準備で未来labelを読まない")
                return super().__getitem__(key)
        rows,metadata,sources,cases=[],{},{},[]
        for index in range(188):
            old=S37.signal("T1",1,"順行","人工旧P"+str(index),1000.+index*180,index+1)
            old["場"]=SESSION
            rows.append(old)
            metadata[old["イベントID"]]={"元価格発動ID":old["イベントID"][:-3],"元価格side":-1}
            sources[old["イベントID"]]=frame(index)
            pure=driver.M.I.pure_signal(old,"H0")
            cases.append(FuturePoison({**pure,**{k:"取得不可" for k in driver.LABEL_FIELDS}}))
        bundle={"pure":{SESSION:rows},"metadata":metadata,"lower_sources":{SESSION:sources},
            "lower":{SESSION:list(sources.values())},"upper":{SESSION:pair()},"input_quality":{SESSION:{"場":SESSION}}}
        with patch.object(driver,"validate_reference",return_value={}),patch.object(driver.M,"read_bundle",return_value=bundle), \
                patch.object(driver,"shared_path",return_value=Path("人工共有39")),patch.object(driver,"read_rows",return_value=cases):
            result=driver.read_bundle(driver.STUDY)
            self.assertEqual(len(result["metadata"]),188)
            self.assertEqual(set(result["pure"][SESSION][0]),set(I.SIGNAL_FIELDS))
            self.assertEqual(set(result["lower_sources"][SESSION]),{r["イベントID"] for r in cases})
            self.assertEqual(result["pure"][SESSION][0]["atr"],rows[0]["atr"])
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
            self.assertEqual(proof["旧H0登録数"],66)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertTrue(proof["旧38H0純登録同値"])
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
            previous=load(ROOT/"scripts/上位雲継続/運用.py","上位中心39主人工の旧運用")
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
            self.assertTrue(driver.W.read_json(f.study/"J0対照同値.json")["全件一致"])
            import gzip
            with gzip.open(f.work/"入口事例.jsonl.gz","rt",encoding="utf-8") as stream:cases=[json.loads(r) for r in stream]
            with gzip.open(f.work/"全運用詳細.jsonl.gz","rt",encoding="utf-8") as stream:details=[json.loads(r) for r in stream]
            self.assertEqual(len(cases),3)
            self.assertEqual(len(details),3)
            self.assertEqual(driver.rename(details[0],"_J0","_H0"),old_detail)
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
            bad=deepcopy(f.config);bad["上位中心継続"]["J2"]="後付け変更"
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
        for name in ("入口参照.json","対照参照.json","上位参照.json"):
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
                "対照参照SHA256":sha(f.study/"対照参照.json"),"上位参照SHA256":sha(f.study/"上位参照.json"),
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
    """人工だけを起動し、固定前/最終の小型証明を保存する。

    引数: CLI --final(bool)はroot許可後だけ指定する。
    返り値: None。市場資料/市場先着/PnLを計算しない。
    """
    parser=argparse.ArgumentParser(description="上位中心継続の人工検査")
    parser.add_argument("--final",action="store_true")
    args=parser.parse_args()
    paths=[HERE/n for n in ("検証.py","入口.py","運用.py","合成検証.py")]
    paths.append(ROOT/"study/00039_外側継続と上位基準線の進行/条件.json")
    present=[p for p in paths if p.exists()]
    helpers=[p for p in (HERE/"状態独立確認.py",HERE/"追尾独立確認.py") if p.exists()]
    pins={p.relative_to(ROOT).as_posix():sha(p) for p in present}
    before={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    with deny_market():
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged=pins=={p.relative_to(ROOT).as_posix():sha(p) for p in present} and before=={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    success=result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    if args.final and (len(pins)!=5 or len(before)!=2):raise ValueError("主三code/条件/合成/独立二code完成前です")
    proof={"全件成功":success,"検証件数":result.testsRun,"合成編集終了":bool(args.final and success),"市場入力読取":False,
        "市場先着損益計算":False,"実行中コード条件不変":unchanged,"ファイルSHA256":pins,
        "独立数値補助SHA256":before.get("scripts/上位中心継続/状態独立確認.py"),
        "独立追尾補助SHA256":before.get("scripts/上位中心継続/追尾独立確認.py"),
        "skip数":len(result.skipped),"失敗数":len(result.failures),"エラー数":len(result.errors)}
    WORK.mkdir(parents=True,exist_ok=True)
    path=WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"出力":str(path),"全件成功":success,"件数":result.testsRun,"SHA256":sha(path)},ensure_ascii=False))
    if not success:raise SystemExit(1)


if __name__=="__main__":
    main()
