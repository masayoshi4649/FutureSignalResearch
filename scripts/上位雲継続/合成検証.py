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
WORK = ROOT/"work/上位雲継続"
SESSION = "人工上位雲場"
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
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("上位雲38合成_")
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


I = load(HERE/"入口.py", "上位雲38合成の入口")
O = load(HERE/"運用.py", "上位雲38合成の運用")
J = load(ROOT/"scripts/一目基準線/指標.py", "上位雲38合成の固定28銀行")
S37 = load(ROOT/"scripts/構造判別/合成検証.py", "上位雲38合成の固定37人工補助")
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


def signal(side: int = 1, clock: float = 1000., line: int = 20, event: str = "人工旧P") -> dict:
    """既に競合後の旧37T1純13列を作る。

    引数: side(int)は実方向、clock/line(float/int)とevent(str)は出典。
    返り値: dictは固定役割の旧T1。
    """
    row = S37.signal("T1", side, "順行", event, clock, line)
    row["場"] = SESSION
    return row


def block(rows: list[dict] | None = None, end: float = 1000.) -> dict:
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
    return {"場": SESSION, "signals": {"3分_T1": originals}, "frames": {3: frames}, "下位出典": sources}


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
    result["cloud_lower"], result["cloud_upper"] = total-row["cloud_upper"], total-row["cloud_lower"]
    return result


class 上位判別検証(unittest.TestCase):
    """H0保持・準備/値・二時計・最新不良・鏡映を検査する。"""

    def test_H0保持と準備だけのH1と値だけのH2(self) -> None:
        """準備不足と値不一致を別の純部分集合にする。

        引数: self(TestCase)は対象。
        返り値: None。上位なしでもH0の値/時計は変えない。
        """
        for higher, expected in (([], (1,0,0)), ([upper(一目公開可=False)], (1,0,0)),
                ([upper(close=10005.)], (1,1,0)), ([upper()], (1,1,1))):
            initial = block()
            old = deepcopy(initial["signals"]["3分_T1"][0])
            result = I.select(initial, higher)
            self.assertEqual(tuple(len(result["signals"]["3分_"+p]) for p in I.POLICIES), expected)
            baseline = result["signals"]["3分_H0"][0]
            baseline.update(イベントID=old["イベントID"], 入口ID=old["入口ID"])
            self.assertEqual(baseline, old)

    def test_雲内等号逆方向はH2だけ待機で売買鏡像(self) -> None:
        """準備を変えず、strictな雲位置だけを比較する。

        引数: self(TestCase)は対象。
        返り値: None。上下反射で分類/採否を保つ。
        """
        for close, kind in ((9995.,"逆方向外"),(10000.,"等号"),(10005.,"内"),(10010.,"等号"),(10015.,"実方向外")):
            high = upper(close=close)
            buy = I.select(block(), [high])
            sell = I.select(block([signal(-1)]), [reflect_upper(high)])
            for result in (buy, sell):
                self.assertTrue(result["decisions"][0]["上位準備"])
                self.assertEqual(result["decisions"][0]["雲方向"],kind)
                self.assertEqual(bool(result["signals"]["3分_H2"]),kind=="実方向外")

    def test_TJ同方向等号逆方向は採否を変えない(self) -> None:
        """転換/基準は診断のみで方向票を追加しない。

        引数: self(TestCase)は対象。
        返り値: None。三状態でもH2を保持する。
        """
        for tenkan, kind in ((9990.,"逆方向"),(10000.,"等号"),(10010.,"同方向")):
            result=I.select(block(),[upper(ichimoku_tenkan=tenkan)])
            self.assertEqual(result["decisions"][0]["TJ方向"],kind)
            self.assertEqual(len(result["signals"]["3分_H2"]),1)

    def test_endとkeyを独立に満たし同keyは可で後行不可(self) -> None:
        """足終了だけ又は公開keyだけで未来足を採らない。

        引数: self(TestCase)は対象。
        返り値: None。同秒後行を含む公開順を守る。
        """
        base=block([signal(clock=1005.,line=20)],end=1000.)
        old=upper(0)
        same=upper(1,end=1000.,confirm=1005.,confirm_line=20)
        late=upper(2,end=1000.,confirm=1005.,confirm_line=21)
        future_end=upper(3,end=1001.,confirm=1001.,confirm_line=1)
        future_key=upper(4,end=900.,confirm=1006.,confirm_line=1)
        for candidate, expected in ((same,1),(late,0),(future_end,0),(future_key,0)):
            result=I.select(deepcopy(base),[old,candidate])
            self.assertEqual(result["decisions"][0]["上位参照"]["index"],expected)

    def test_最新不準備は古正常へfallbackせずNPは公開しない(self) -> None:
        """不良の最新を診断へ残し、非公開内部足とは区別する。

        引数: self(TestCase)は対象。
        返り値: None。最新が準備不可ならH1/H2を見送る。
        """
        latest=upper(1,confirm=990.,一目公開可=False,銀行解除理由=["欠枠"])
        result=I.select(block(),[upper(),latest])
        self.assertEqual(result["decisions"][0]["上位参照"]["index"],1)
        self.assertFalse(result["signals"]["3分_H1"])
        np=deepcopy(latest);np.update(publish=False)
        result=I.select(block(),[upper(),np])
        self.assertEqual(result["decisions"][0]["上位参照"]["index"],0)
        self.assertTrue(result["signals"]["3分_H2"])

    def test_当場限定と下位index出典整合を検査する(self) -> None:
        """前場公開carryや曖昧な要求key対応を拒否する。

        引数: self(TestCase)は対象。
        返り値: None。数値carryと当場参照を分ける。
        """
        with self.assertRaises(ValueError):I.select(block(),[upper(場="前場")])
        bad=block();bad["下位出典"]["人工旧P_T1"]["end"]-=1
        with self.assertRaises(ValueError):I.select(bad,[upper()])
        bad=block();bad["下位出典"]["人工旧P_T1"]["confirm_line"]+=1
        with self.assertRaises(ValueError):I.select(bad,[upper()])
        with self.assertRaises(ValueError):I.select(block([signal(),signal(event="別P")]),[upper()])

    def test_未来labelと未使用上位数値を純列へ渡さない(self) -> None:
        """旧caseを想定した追加未来列や上位Fastを落とす。

        引数: self(TestCase)は対象。
        返り値: None。全H純列は13列で参照は限定列だけ。
        """
        old=signal();old.update(ラベル="250",最大順行pt=99999.,将来損益=99999.)
        value=I.select(block([old]),[upper()])
        for rows in value["signals"].values():
            self.assertEqual(set(rows[0]),set(I.SIGNAL_FIELDS))
        reference=value["decisions"][0]["上位参照"]
        self.assertEqual(set(reference),set(I.UPPER_FIELDS))
        for key in ("atr","stoch_raw","Fast差厳密符号","未来ラベル"):
            self.assertNotIn(key,reference)

    def test_判定snapshotと未来prefixと空場を保つ(self) -> None:
        """後続足や候補の変更で過去の判定を変えない。

        引数: self(TestCase)は対象。
        返り値: None。空場でも三集合を保持する。
        """
        higher=[upper()]
        first=I.select(block(),higher)
        future=upper(2,end=2000.,confirm=2000.)
        self.assertEqual(first,I.select(block(),higher+[future]))
        first["signals"]["3分_H0"][0]["atr"]=0
        self.assertEqual(first["signals"]["3分_H1"][0]["atr"],25.)
        self.assertEqual(I.select(block([]),[]) ["signals"],{"3分_H0":[],"3分_H1":[],"3分_H2":[]})

    def test_独立全列挙の採否参照と純列を全属性で照合する(self) -> None:
        """主pointerと独立の上位全候補走査を照合する。

        引数: self(TestCase)は対象。
        返り値: None。人工以外の数値銀行や原板を読まない。
        """
        state=load(HERE/"状態独立確認.py","上位雲38人工の独立入口")
        for higher in ([],[upper()],[upper(close=10005.)],[upper(),upper(1,confirm=990.,一目公開可=False)]):
            actual=I.select(block(),deepcopy(higher))
            expected=state.select(block(),deepcopy(higher))
            self.assertEqual(actual["signals"],expected["signals"])
            self.assertEqual(actual["decisions"],expected["decisions"])
        for side in (1,-1):
            values=block([signal(side)])
            higher=[upper() if side==1 else reflect_upper(upper())]
            self.assertEqual(I.select(deepcopy(values),deepcopy(higher)),state.select(deepcopy(values),deepcopy(higher)))


class 保存28銀行検証(unittest.TestCase):
    """共有する28銀行の人工定義と公開/carryを再確認する。"""

    def test_現在雲は26前で最速78本目(self) -> None:
        """現在A/Bではなく26本前のA/Bを使う。

        引数: self(TestCase)は対象。
        返り値: None。独立prefix窓との限定全列も照合する。
        """
        frames=[frame(i,15,open=1000.+i,high=1010.+i,low=990.+i,close=1000.+i) for i in range(80)]
        rows,quality=J.NumericBank(15).build(frames,SESSION,(2026,12))
        self.assertFalse(rows[76]["一目準備済"])
        current=rows[77]
        self.assertTrue(current["一目準備済"])
        self.assertEqual((current["ichimoku_tenkan"],current["ichimoku_kijun"]),(1073.,1064.5))
        self.assertEqual((current["cloud_a"],current["cloud_b"]),(1042.75,1025.5))
        self.assertEqual(current["雲計算元足"]["index"],51)
        state=load(HERE/"状態独立確認.py","上位雲38人工の独立数値")
        expected,_=state.NumericHistory(15).build(frames,SESSION,(2026,12))
        self.assertEqual([I.upper_projection(r) for r in rows],expected)

    def test_NP内部carryと当場公開と限月欠枠解除を分ける(self) -> None:
        """NPは銀行だけ更新し、場開始で公開参照を空にする。

        引数: self(TestCase)は対象。
        返り値: None。欠枠有効当足は銀行の初足へ投入する。
        """
        bank=J.NumericBank(15)
        frames=[frame(i,15,open=1000.+i,high=1010.+i,low=990.+i,close=1000.+i) for i in range(78)]
        frames[-1]["publish"]=False
        rows,_=bank.build(frames,"前場",(2026,12))
        self.assertTrue(rows[-1]["一目準備済"])
        self.assertFalse(rows[-1]["一目公開可"])
        carried,_=bank.build([frame(0,15)],SESSION,(2026,12))
        self.assertTrue(carried[0]["一目公開可"])
        reset,_=bank.build([frame(0,15,missing=1)],SESSION,(2026,12))
        self.assertEqual(reset[0]["一目窓本数"],1)
        changed,_=bank.build([frame(0,15)],SESSION,(2027,3))
        self.assertIn("限月変更",changed[0]["銀行解除理由"])
        self.assertFalse(changed[0]["一目準備済"])
        bank.build([],SESSION,(2027,3),tail_missing=1)
        after,_=bank.build([frame(0,15)],SESSION,(2027,3))
        self.assertEqual(after[0]["一目窓本数"],1)


class 固定XF検証(unittest.TestCase):
    """三案の運用は旧T1XFと識別子以外同値か確認する。"""

    def test_三運用の買売全台帳追尾を旧37T1XFと照合(self) -> None:
        """新規前の上位判定を出口へ混入させない。

        引数: self(TestCase)は対象。
        返り値: None。現在益起動/同値床/返済遅延を旧固定へ直結する。
        """
        previous=load(ROOT/"scripts/構造判別/運用.py","上位雲38人工の固定37運用")
        def renamed(value: object, old: str, new: str) -> object:
            """識別子断片だけをJSON値の全階層へ置換する。

            引数: value(object)は保存形状、old/new(str)は識別子。
            返り値: objectは数値を保持する変換値。
            """
            if isinstance(value,dict):return {k:renamed(v,old,new) for k,v in value.items()}
            if isinstance(value,list):return [renamed(v,old,new) for v in value]
            return value.replace(old,new) if isinstance(value,str) else value
        for side in (1,-1):
            source=signal(side,10.,10)
            events=[S37.quote(10.,1,side,-5.),S37.quote(11.,2,side,-5.),S37.quote(12.,3,side,15.),
                S37.quote(13.,4,side,5.),S37.quote(14.,5,side,0.),S37.quote(15.,6,side,-5.)]
            old_state,old_quality=previous.replay(events,[source],[],SESSION,"3分_T1_XF",CONFIG,{"出口ID":"XF"},"順行",BOUNDS)
            for policy in I.POLICIES:
                pure=I.pure_signal(source,policy);pure.update(ラベル="250",将来利益=99999.)
                current,quality=O.replay(events,[pure],[],SESSION,"3分_"+policy+"_XF",CONFIG,{"出口ID":"XF"},"順行",BOUNDS)
                for field in ("fills","trades","orders","signals","normal_log"):
                    self.assertEqual(getattr(current,field),renamed(getattr(old_state,field),"_T1","_"+policy))
                self.assertEqual(quality,renamed(old_quality,"_T1","_"+policy))
                self.assertEqual(len(current.trades),1)

    def test_未計画出口と反転役割や偽装入口を拒否(self) -> None:
        """全XF順行の契約を運用の入口で検査する。

        引数: self(TestCase)は対象。
        返り値: None。旧X0やS/Rは実行しない。
        """
        row=I.pure_signal(signal())
        for method,policy,role in (("3分_H0_X0",{"出口ID":"X0"},"順行"),("3分_H0_XF",{"出口ID":"XF"},"反転")):
            with self.assertRaises(ValueError):O.replay([],[],[],SESSION,method,CONFIG,policy,role,BOUNDS)
        row["方向"]="売り"
        with self.assertRaises(ValueError):O.replay([],[row],[],SESSION,"3分_H0_XF",CONFIG,{"出口ID":"XF"},"順行",BOUNDS)


def driver_module() -> Any:
    """主CLIを起動せず現在の定義を人工へ読み込む。

    引数: なし。
    返り値: Anyは市場I/Oを遮断した主モジュール。
    """
    return load(HERE/"検証.py","上位雲38合成の主検証")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """主CLI用の人工場・参照・純材料を一時先だけへ作る。

    引数: driver(Any)は主、count(int)は人工場数。
    返り値: Iterator[Any]は一時study/workと純bundle/buildの束。
    """
    with tempfile.TemporaryDirectory(prefix="上位雲38合成_",dir=ROOT/"work") as temporary:
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
            high=upper(end=9.,confirm=9.,confirm_line=1);high["場"]=name
            bundle["pure"][name]=[old]
            bundle["lower"][name]=material["frames"][3]
            bundle["lower_sources"][name]=material["下位出典"]
            bundle["upper"][name]=[I.upper_projection(high)]
            bundle["input_quality"][name]={"場":name}
            bundle["metadata"][old["イベントID"]]={"元価格発動ID":old["イベントID"][:-3],"元価格side":-1}

        def built(entry: dict, manifest: dict, shared: dict, current: dict, include_events: bool = False) -> dict:
            """元13列を当場の人工上位へ結び、正式だけ人工気配を返す。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式経路。
            返り値: dictは人工場材料。実source/stat/cacheを参照しない。
            """
            name=entry["session"]
            material={"場":name,"signals":{"3分_T1":deepcopy(shared["pure"][name])},
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

    def test_共有188caseはlabelへ触れず即13列と過去二列へ射影する(self) -> None:
        """新bundleへ旧case全体や未来ラベルを保持しない。

        引数: self(TestCase)は対象。
        返り値: None。保存値読取境界も全て人工へ置換する。
        """
        driver=driver_module()
        class FuturePoison(dict):
            """未来ラベルの取得を拒否する人工case。"""
            def __getitem__(self, key: str) -> Any:
                """未来列への参照だけ失敗させる。

                引数: key(str)は取得列。
                返り値: Anyは過去の必須列のみ。
                """
                if key in driver.LABEL_FIELDS:raise AssertionError("準備へ未来labelを渡さない")
                return super().__getitem__(key)
        cases,lower,structure=[],[],[]
        for index in range(188):
            old=signal(clock=1000.+index*180,line=index+1,event="人工原P"+str(index))
            cases.append(FuturePoison({**old,"元価格発動ID":old["イベントID"][:-3],"元価格side":-1,
                **{k:"取得不可" for k in driver.LABEL_FIELDS}}))
            source=frame(index,confirm=old["要求時計秒"],confirm_line=index+1);source["場"]=SESSION
            lower.append(source)
            structure.append({"場":SESSION,"発動ID":old["イベントID"][:-3],"index":index})

        def read_rows(path: Path) -> list[dict]:
            """参照の種類ごとに人工共有行だけを渡す。

            引数: path(Path)は人工参照の種別/ファイル名。
            返り値: list[dict]はlabel拒否case又は過去出典。
            """
            return {("37","入口事例.jsonl.gz"):cases,("37","構造判定.jsonl.gz"):structure,
                ("29","全指標.jsonl.gz"):lower,("28","全指標.jsonl.gz"):[upper()]}[(path.parent.name,path.name)]

        old_read=driver.W.read_json
        def read_json(path: Path) -> Any:
            """旧品質だけを人工一場へ置換する。

            引数: path(Path)は小型正本。
            返り値: Anyは人工品質又は既存小型資料。
            """
            return [{"場":SESSION,"期間":"学習"}] if path==driver.ENTRY_STUDY/"入力品質.json" else old_read(path)

        with patch.object(driver,"validate_reference",side_effect=lambda s,n:{"kind":"28" if n=="上位参照.json" else "37"}), \
                patch.object(driver.M,"validate_reference",return_value={"kind":"29"}), \
                patch.object(driver,"shared_path",side_effect=lambda r,n:Path(r["kind"])/n), \
                patch.object(driver,"read_rows",side_effect=read_rows),patch.object(driver.W,"read_json",side_effect=read_json):
            shared=driver.read_bundle(driver.STUDY)
        self.assertEqual(len(shared["metadata"]),188)
        self.assertEqual(set(shared["pure"][SESSION][0]),set(I.SIGNAL_FIELDS))
        self.assertEqual(set(next(iter(shared["metadata"].values()))),{"元価格発動ID","元価格side"})
        self.assertEqual(set(shared["upper"][SESSION][0]),set(I.UPPER_FIELDS))

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
            self.assertEqual(proof["旧T1登録数"],66)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertTrue(proof["旧37T1純登録同値"])
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
            previous=load(ROOT/"scripts/構造判別/運用.py","上位雲38主人工の旧運用")
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
            self.assertTrue(driver.W.read_json(f.study/"H0対照同値.json")["全件一致"])
            import gzip
            with gzip.open(f.work/"入口事例.jsonl.gz","rt",encoding="utf-8") as stream:cases=[json.loads(r) for r in stream]
            with gzip.open(f.work/"全運用詳細.jsonl.gz","rt",encoding="utf-8") as stream:details=[json.loads(r) for r in stream]
            self.assertEqual(len(cases),3)
            self.assertEqual(len(details),3)
            self.assertEqual(driver.rename(details[0],"_H0","_T1"),old_detail)
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
            bad=deepcopy(f.config);bad["上位雲継続"]["H2"]="後付け変更"
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
    """人工検査だけを実行し、現在版へbindした小型証明を保存する。

    引数: CLIの--final(bool)は編集終了の宣言。
    返り値: None。市場処理を起動せず、失敗は非零終了にする。
    """
    parser=argparse.ArgumentParser(description="上位雲継続の人工検査だけを行う")
    parser.add_argument("--final",action="store_true")
    args=parser.parse_args()
    paths=[HERE/n for n in ("検証.py","入口.py","運用.py","合成検証.py")]
    paths.append(ROOT/"study/00038_外側継続と上位の現在雲/条件.json")
    present=[p for p in paths if p.exists()]
    initial={p.relative_to(ROOT).as_posix():sha(p) for p in present}
    helpers=[p for p in (HERE/"状態独立確認.py",HERE/"追尾独立確認.py") if p.exists()]
    helper_initial={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    with deny_market():
        suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    current={p.relative_to(ROOT).as_posix():sha(p) for p in present}
    independent={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    unchanged=current==initial and independent==helper_initial
    complete=result.wasSuccessful() and unchanged and not result.skipped
    if args.final and (len(initial)!=5 or len(independent)!=2):
        raise ValueError("最終人工には主三コード/条件/合成と独立二コードが必要")
    proof={"全件成功":complete,"検証件数":result.testsRun,"失敗数":len(result.failures),"エラー数":len(result.errors),
        "skip数":len(result.skipped),"合成編集終了":bool(args.final and complete),"実行中の指紋不変":unchanged,
        "市場入力使用":False,"先着計算":False,"市場損益計算":False,
        "ファイルSHA256":current,"独立補助SHA256":independent,"独立数値補助SHA256":independent.get("scripts/上位雲継続/状態独立確認.py"),
        "独立追尾補助SHA256":independent.get("scripts/上位雲継続/追尾独立確認.py")}
    WORK.mkdir(parents=True,exist_ok=True)
    output=WORK/"合成検証.json"
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"出力":str(output),"全件成功":complete,"件数":result.testsRun,"SHA256":sha(output)},ensure_ascii=False))
    if not complete:raise SystemExit(1)


if __name__=="__main__":
    main()
