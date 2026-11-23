"""32の精密SARと公開後BBOの最低同値追尾を人工入力だけで検査する。"""

from __future__ import annotations

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
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
from typing import Any, Iterator
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00032_最低同値床と公開SAR追尾"
WORK = ROOT / "work/SAR追尾"
SESSION = "人工SAR追尾場"
CONTRACT = ("人工限月",)


def normalized(path: object) -> str:
    """ファイルへ触れず、内容読取禁止先との比較表記を作る。

    引数: path(object)はパス又はファイル記述子。
    返り値: strは絶対表記。パスでなければ空文字。
    """
    try:
        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError):
        return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """人工合成から共有原板/cache/実圧縮明細へstat/openさせない。

    引数: なし。
    返り値: Iterator[None]は読取禁止範囲。条件/既知コード/人工値だけ使う。
    """
    raw, work = normalized(ROOT.parent / "JP_OSE_Data"), normalized(ROOT / "work")
    original_open, original_path_open, original_stat = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """共有市場資料を開く前に合成を失敗させる。

        引数: path(object)は対象。
        返り値: None。原板又はnpzはAssertionError。
        """
        name = normalized(path)
        is_work = name.startswith(work + os.sep)
        artificial = is_work and os.path.relpath(name, work).split(os.sep)[0].casefold().startswith("sar32合成_")
        if name == raw or name.startswith(raw + os.sep) or is_work and (name.endswith(".npz") or not artificial and name.endswith((".jsonl.gz", ".trades.jsonl"))):
            raise AssertionError("人工合成から実原板/cache/実圧縮明細へ触れない:" + str(path))

    def guarded_open(path: object, *args: object, **kwargs: object) -> Any:
        """openで市場内容へ到達させない。

        引数: path(object)は対象、args/kwargs(object)はopen引数。
        返り値: Anyは許された人工/コードファイル。
        """
        check(path)
        return original_open(path, *args, **kwargs)

    def guarded_path_open(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.openでも市場内容へ到達させない。

        引数: path(Path)は対象、args/kwargs(object)はopen引数。
        返り値: Anyは許された人工/コードファイル。
        """
        check(path)
        return original_path_open(path, *args, **kwargs)

    def guarded_stat(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.statでも実原板/cacheへ接近しない。

        引数: path(Path)は対象、args/kwargs(object)はstat引数。
        返り値: Anyは許されたstat。
        """
        check(path)
        return original_stat(path, *args, **kwargs)

    with patch.object(builtins, "open", guarded_open), patch.object(Path, "open", guarded_path_open), patch.object(Path, "stat", guarded_stat):
        yield


def load(path: Path, name: str) -> Any:
    """市場読取禁止のままPythonのAPI定義だけを読み込む。

    引数: path(Path)はコード、name(str)は登録名。
    返り値: Anyは読込モジュール。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
        return value


def frame(index: int, high: float = 105., low: float = 95., close: float = 100., minutes: int = 3, base: float = 0., **updates: object) -> dict:
    """手計算できる人工の完全幅OHLCを返す。

    引数: index(int)は番号、high/low/close(float)は価格、minutes(int)は足幅、base(float)は開始基点、updates(object)は上書き。
    返り値: dictは人工足。原板を参照しない。
    """
    width = minutes * 60.
    start = base + index * width
    return {"index": index, "minutes": minutes, "start": start, "end": start+width, "confirm": start+width,
            "confirm_line": index+10, "publish": True, "missing": 0,
            "open": min(high, max(low, close)), "high": high, "low": low, "close": close, **updates}


def reflect(frames: list[dict], center: float = 2000.) -> list[dict]:
    """高安を交換し、正価格の範囲で人工系列を上下反射する。

    引数: frames(list[dict])は人工足、center(float)は価格の和。
    返り値: list[dict]は独立した鏡像で、量/時計/keyは変更しない。
    """
    result = deepcopy(frames)
    for row in result:
        high, low = row["high"], row["low"]
        row.update(open=center-row["open"], high=center-low, low=center-high, close=center-row["close"])
    return result


def sha(path: Path) -> str:
    """コードと条件の内容指紋を取得する。

    引数: path(Path)はコード又はJSON正本。
    返り値: strはSHA256。実市場資料を対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


J=load(HERE/"指標.py","SAR32人工の精密数値")
O=load(HERE/"運用.py","SAR32人工の公開追尾")
CONFIG=json.loads((ROOT/"study/00031_CCI持続と上位BB幅/条件.json").read_text(encoding="utf-8"))["運用"]
BOUNDS=(0.,1000.,800.,900.)


def series(values: list[float]) -> list[dict]:
    """H=L=Cの人工完全幅足を番号順に作る。

    引数: values(list[float])は価格。
    返り値: list[dict]はSARの手計算用足。外部市場は使わない。
    """
    return [frame(index,high=value,low=value,close=value) for index,value in enumerate(values)]


def numeric(frames: list[dict]) -> list[dict]:
    """人工OHLCだけを空の精密SAR銀行へ渡す。

    引数: frames(list[dict])は人工3分足。
    返り値: list[dict]はhex精密値と表示値。公開/約定はまだ処理しない。
    """
    return J.SARBank().build(frames,SESSION,CONTRACT)[0]


def signal(side: int = 1) -> dict:
    """将来値を含まない10000pt基準の人工純信号を作る。

    引数: side(int)は買1/売-1。
    返り値: dictは旧一建玉模型に必要な当時特徴だけ。
    """
    return {"場":SESSION,"イベントID":"人工入口","入口ID":"3分_C0","役割":"順行","side":side,
        "方向":"買い" if side==1 else "売り","要求時計秒":10.,"要求原板行":10,"確認遅延秒":0.,
        "low":9990.,"high":10010.,"atr":25.,"bb_mean":None}


def event(now: float, line: int, side: int, profit: float) -> SimpleNamespace:
    """10000ptの新規基準に対する正常返済BBOを作る。

    引数: now(float)/line(int)は時計/key、side(int)は方向、profit(float)は返済側名目利益。
    返り値: SimpleNamespaceはnow/line/bid/ask/validを持つ人工気配。
    """
    mark=10000.+side*profit
    return SimpleNamespace(now=now,line=line,bid=mark if side==1 else mark-5.,
        ask=mark+5. if side==1 else mark,valid=True)


def quote(state: Any, now: float, line: int, profit: float) -> None:
    """建玉方向に合わせた人工正常BBOを状態へ渡す。

    引数: state(Any)は人工運用、now(float)/line(int)はkey、profit(float)は名目返済幅。
    返り値: None。旧会計の注文待機とMFE順序をそのまま通す。
    """
    value=event(now,line,state.position["side"],profit)
    state.quote(now,line,value.bid,value.ask)


def opened(side: int = 1) -> Any:
    """人工新規を1価格秒待機して約定させたXS状態を返す。

    引数: side(int)は買1/売-1。
    返り値: Anyは新規10000pt・未起動・SAR未公開の建玉を持つ。
    """
    source=signal(side)
    state=O.SAR追尾状態(SESSION,"人工_XS",deepcopy(CONFIG),{"出口ID":"XS"},"順行",[source],BOUNDS)
    state.signal_group([source])
    value=event(11.,11,side,-5.)
    state.quote(value.now,value.line,value.bid,value.ask)
    if state.position is None or state.position["price"]!=10000.:
        raise AssertionError("人工新規の設定が不正")
    return state


def source(now: float, line: int, value: Fraction | None, direction: int = 1,
           ready: bool = True, index: int = 0, publish: bool = True) -> dict:
    """運用の公開順だけを検査する人工SAR参照を注入する。

    引数: now(float)/line(int)は公開key、value(Fraction|None)は精密次足線、direction(int)は方向、ready(bool)は有効、index(int)は足番号、publish(bool)は公開。
    返り値: dictはO.referenceに必要な小型数値行。SAR式の検算とは分離する。
    """
    return {"場":SESSION,"index":index,"end":now,"confirm":now,"confirm_line":line,"publish":publish,
        "missing":0,"SAR準備済":ready,"SAR公開可":ready and publish,"SAR方向":direction if ready else 0,
        "SAR次足線":float(value) if value is not None else None,"SAR精密次足線":J.pack(value) if ready else None,
        "SAR_AF整数":2 if ready else None,"SAR解除理由":[]}


class 精密SAR数値検証(unittest.TestCase):
    """手計算と独立核へ数値・鏡像・長桁の境界を確認する。"""

    def test_初期同値は保留し最初の非同値ペアでだけ初期化する(self) -> None:
        """初期当足の大きな安値を成熟反転へ二重利用しない。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。表示min98,50/EP103/AF2を明示値へ照合。
        """
        frames=[frame(0,101.,99.,100.),frame(1,102.,98.,100.),frame(2,103.,50.,101.)]
        rows=numeric(frames)
        self.assertFalse(rows[0]["SAR準備済"])
        self.assertFalse(rows[1]["SAR準備済"])
        self.assertTrue(rows[2]["SAR初期化"])
        self.assertFalse(rows[2]["SAR反転"])
        self.assertEqual(J.unpack(rows[2]["SAR精密表示線"]),50)
        self.assertEqual(J.unpack(rows[2]["SAR精密EP"]),103)
        self.assertEqual(rows[2]["SAR_AF整数"],2)

    def test_前二足clampの後にEPとAFを更新し次線に再clampしない(self) -> None:
        """事前98.12→表示98→次98.32、極値同値AF据置を照合する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。数式を主から生成した期待値へ置き換えない。
        """
        frames=[frame(0,102.,98.,100.),frame(1,104.,99.,102.),frame(2,106.,100.,103.),frame(3,106.,101.,104.)]
        rows=numeric(frames)
        self.assertEqual(J.unpack(rows[1]["SAR精密次足線"]),Fraction(2453,25))
        self.assertEqual(J.unpack(rows[2]["SAR精密事前線"]),Fraction(2453,25))
        self.assertEqual(J.unpack(rows[2]["SAR精密表示線"]),98)
        self.assertEqual(J.unpack(rows[2]["SAR精密次足線"]),Fraction(2458,25))
        self.assertEqual(rows[2]["SAR_AF整数"],4)
        self.assertEqual(rows[3]["SAR_AF整数"],4)
        self.assertEqual(J.unpack(rows[3]["SAR精密次足線"]),Fraction(61642,625))
        self.assertEqual([row["index"] for row in rows[3]["SAR前二足"]],[1,2])
        growing=numeric(series([float(100+i) for i in range(30)]+[129.]))
        self.assertEqual(growing[-1]["SAR_AF整数"],20)
        self.assertEqual(growing[-2]["SAR_AF整数"],20)

    def test_事前線105の等号は非反転でstrict下抜けだけ反転し売りも鏡像(self) -> None:
        """等号がTA-Lib式の反転へ変わらないことを原OHLCで検査する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。反転表示旧EP350・AF2、次線は別保存。
        """
        for penetrated in (False,True):
            low=104.5 if penetrated else 105.
            frames=[frame(0,110.,100.,105.),frame(1,350.,100.,110.),frame(2,350.,low,120.)]
            long=numeric(frames)
            short=numeric(reflect(frames))
            self.assertEqual(J.unpack(long[2]["SAR精密事前線"]),105)
            self.assertEqual(long[2]["SAR反転"],penetrated)
            self.assertEqual(short[2]["SAR反転"],penetrated)
            self.assertEqual(short[2]["SAR方向"],-long[2]["SAR方向"])
            for key in ("SAR精密事前線","SAR精密表示線","SAR精密次足線","SAR精密EP"):
                self.assertEqual(J.unpack(long[2][key])+J.unpack(short[2][key]),2000)
            if penetrated:
                self.assertEqual(J.unpack(long[2]["SAR精密表示線"]),350)
                self.assertEqual(long[2]["SAR_AF整数"],2)

    def test_精密呼値は同値と微小差および長いhexをfloat経由せず区別する(self) -> None:
        """floatでは同じになるE±微小と5pt境界、正規hexを検査する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。1/10^5000を丸めず保持し上下反射する。
        """
        tiny=Fraction(1,10**5000)
        for value,want in ((Fraction(10000),10000),(Fraction(10000)+tiny,10005),
                           (Fraction(10005)-tiny,10005),(Fraction(10005),10005),(Fraction(10005)+tiny,10010)):
            self.assertEqual(J.round_stop(value,1),want)
            self.assertEqual(J.round_stop(20000-value,-1),20000-want)
            stored=J.pack(value)
            self.assertEqual(J.unpack(json.loads(json.dumps(stored))),value)
        self.assertIsNone(J.unpack(J.pack(None)))
        with self.assertRaises(ValueError):
            J.unpack({"分子16進":"0x02","分母16進":"0x1"})

    def test_3002足の固定EPでも分母を制限せず閉形式とhex往復が一致する(self) -> None:
        """AF2/100の長い収束で十進4300桁を超える分母を保存する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。最初の前二足clamp後の3000回更新を閉形式へ照合。
        """
        rows,quality=J.SARBank().build(series([100.]+[110.]*3001),SESSION,CONTRACT)
        exact=J.unpack(rows[-1]["SAR精密次足線"])
        self.assertEqual(exact,110-10*Fraction(49,50)**3000)
        self.assertLess(exact,110)
        self.assertGreater(exact.denominator.bit_length(),15000)
        self.assertGreater(quality["最大分母bit長"],15000)
        encoded=json.dumps(rows[-1],ensure_ascii=False,allow_nan=False)
        self.assertEqual(J.unpack(json.loads(encoded)["SAR精密次足線"]),exact)
        self.assertEqual(rows[-1]["SAR_AF整数"],2)

    def test_欠枠限月尾部で解除しNPは数値carryしても公開しない(self) -> None:
        """同限月数値の継続と公開の可否を別に検査する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。不正非有限OHLCはNone保存し種へ補完しない。
        """
        bank=J.SARBank()
        frames=series([100.,110.,110.]);frames[-1]["publish"]=False
        rows,_=bank.build(frames,"前場",CONTRACT)
        self.assertTrue(rows[-1]["SAR準備済"])
        self.assertFalse(rows[-1]["SAR公開可"])
        fresh=bank.build(series([110.]),SESSION,CONTRACT)[0][0]
        self.assertTrue(fresh["SAR公開可"])
        self.assertFalse(bank.build(series([110.]),"新限月",("別限月",))[0][0]["SAR準備済"])
        bank.build(series([100.,110.]),"尾部",CONTRACT,1)
        self.assertFalse(bank.build(series([110.]),SESSION,CONTRACT)[0][0]["SAR準備済"])
        for kind in ("missing","番号欠","不正"):
            frames=series([100.,110.,120.,130.])
            if kind=="missing": frames[2]["missing"]=1
            elif kind=="番号欠":
                for row in frames[2:]: row["index"]+=1
            else: frames[2]["high"]=math.inf
            rows=numeric(frames)
            self.assertFalse(rows[2]["SAR準備済"])
            if kind=="不正":
                self.assertIsNone(rows[2]["high"])
                self.assertFalse(rows[3]["SAR準備済"])
            else: self.assertTrue(rows[3]["SAR初期化"])

    def test_独立Fraction核と同じ人工系列の全精密値が一致する(self) -> None:
        """主をimportしない別手順の核へ全線・AF・方向を照合する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。主出力を独立の期待値として渡さない。
        """
        independent=load(HERE/"状態独立確認.py","SAR32人工の独立分数核")
        frames=[frame(0,102.,98.,100.),frame(1,104.,99.,102.),frame(2,106.,100.,103.),
                frame(3,106.,101.,104.),frame(4,107.,90.,92.),frame(5,99.,85.,90.)]
        for used in (frames,reflect(frames)):
            rows=numeric(used);other=independent.RationalSAR()
            for row,raw in zip(rows,used):
                expected=other.step(raw,SESSION)
                for main_key,other_key in (("SAR精密事前線","before_line"),("SAR精密表示線","display"),
                    ("SAR精密次足線","next_line"),("SAR精密EP","extreme"),("SAR精密事前EP","before_extreme")):
                    self.assertEqual(J.unpack(row[main_key]),expected[other_key])
                self.assertEqual(row["SAR方向"],expected["direction"] if expected["ready"] else 0)
                self.assertEqual(row["SAR_AF整数"],expected["af"] if expected["ready"] else None)
            actual,quality=J.SARBank().build(used,SESSION,CONTRACT)
            independent_rows,independent_quality=independent.NumericHistory().build(used,SESSION,CONTRACT)
            self.assertEqual(actual,independent_rows)
            self.assertEqual(quality,independent_quality)


class 公開SARと最低同値床検証(unittest.TestCase):
    """公開順・厳密候補・優先・pendingと旧X0不変を人工で調べる。"""

    def test_SAR不良逆向き同値でも初回5ptで必ず床を起動する(self) -> None:
        """SARを追加入口gateにせず、名目0以下を上締上げへ使わない。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。ATR距離の代用上締上げを入れず、旧床だけ保持。
        """
        for side in (1,-1):
            for mode in ("未公開","不良","逆向き","同値","不利"):
                state=opened(side)
                if mode!="未公開":
                    value=Fraction(10000) if mode=="同値" else Fraction(10000-side*5) if mode=="不利" else Fraction(10000+side*20)
                    state.bar(source(12.,12,value,-side if mode=="逆向き" else side,mode!="不良"))
                quote(state,13.,13,5.)
                self.assertTrue(state.position["armed"])
                self.assertEqual(state.position["trail_stop"],10000.)
                self.assertEqual(state.position["sar_updates"],0)
                self.assertIsNone(state.position["trail_D"])
                quote(state,14.,14,100.)
                self.assertEqual(state.position["trail_stop"],10000.)

    def test_呼値境界の微小利益で締め上げ非緩和し不利な新SARへ戻らない(self) -> None:
        """float表示が新規同値でも精密正益を認識し、ceil/floorで締める。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。全売買を同じ実side条件にする。
        """
        tiny=Fraction(1,10**5000)
        for side in (1,-1):
            state=opened(side)
            state.bar(source(12.,12,Fraction(10000)+side*tiny,side))
            quote(state,13.,13,20.)
            self.assertEqual(state.position["trail_stop"],10000+side*5)
            state.bar(source(14.,14,Fraction(10000)+side*12,side,index=1))
            quote(state,15.,15,30.)
            self.assertEqual(state.position["trail_stop"],10000+side*15)
            applied=deepcopy(state.position["sar_applied"])
            state.bar(source(16.,16,Fraction(10000)+side*7,side,index=2))
            quote(state,17.,17,30.)
            self.assertEqual(state.position["trail_stop"],10000+side*15)
            self.assertEqual(state.position["sar_applied"],applied)

    def test_公開barは古BBOを使わず同key不可で同秒後行BBOからだけ使う(self) -> None:
        """quote→bar同keyの順序と、bar時に線/注文が変わらないことを確認。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。同秒でも原行が後なら公開後とする。
        """
        state=opened()
        quote(state,12.,12,20.)
        quote(state,13.,13,20.)
        state.bar(source(13.,13,Fraction(10012)))
        self.assertEqual(state.position["trail_stop"],10000)
        self.assertIsNone(state.pending)
        quote(state,13.,13,20.)
        self.assertEqual(state.position["trail_stop"],10000)
        quote(state,13.,14,20.)
        self.assertEqual(state.position["trail_stop"],10015)
        self.assertEqual(state.position["sar_applied"]["confirm_line"],13)

    def test_BBO前に溜まった最新一つだけを使い最新不良に旧正常fallbackしない(self) -> None:
        """中間の強い線を先に適用せず、最新不良/逆方向では旧床保持。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。入口前の当場公開源も新しい待機なしで使える。
        """
        state=opened()
        state.bar(source(12.,12,Fraction(10020)))
        state.bar(source(12.5,13,Fraction(10005),index=1))
        quote(state,13.,14,30.)
        self.assertEqual(state.position["trail_stop"],10005)
        state.bar(source(14.,15,None,ready=False,index=2))
        quote(state,15.,16,30.)
        self.assertIsNone(state.latest_sar)
        self.assertEqual(state.position["trail_stop"],10005)
        state.bar(source(16.,17,Fraction(10030),direction=-1,index=3))
        quote(state,17.,18,30.)
        self.assertEqual(state.position["trail_stop"],10005)
        own=signal()
        early=O.SAR追尾状態(SESSION,"人工_XS",deepcopy(CONFIG),{"出口ID":"XS"},"順行",[own],BOUNDS)
        early.bar(source(5.,5,Fraction(10010)))
        early.signal_group([own])
        value=event(11.,11,1,-5.);early.quote(value.now,value.line,value.bid,value.ask)
        quote(early,12.,12,20.)
        self.assertEqual(early.position["trail_stop"],10010)

    def test_既越候補も気配へclampせず初着要求しpending中は建玉を凍結する(self) -> None:
        """要求後1秒待機でBBO約定し、SAR価格約定やpending中再起動をしない。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。global最新源/MFEは進むが設定線と適用源は固定。
        """
        for side in (1,-1):
            state=opened(side)
            state.bar(source(12.,12,Fraction(10000+side*7),side))
            quote(state,13.,13,5.)
            self.assertEqual(state.position["trail_stop"],10000+side*10)
            self.assertEqual(state.pending["reason"],"必須利益追尾")
            applied=deepcopy(state.position["sar_applied"])
            state.bar(source(13.25,14,Fraction(10000+side*40),side,index=1))
            quote(state,13.5,15,30.)
            self.assertEqual(state.position["trail_stop"],10000+side*10)
            self.assertEqual(state.position["sar_applied"],applied)
            self.assertEqual(state.position["mfe"],30.)
            self.assertEqual(state.latest_publication["index"],1)
            self.assertEqual(len(state.fills),1)
            quote(state,14.,16,20.)
            self.assertIsNone(state.position)
            self.assertEqual(state.trades[0]["返済価格"],10000+side*20)
            self.assertEqual(state.trades[0]["最終追尾価格"],10000+side*10)
            self.assertEqual(state.trades[0]["SAR締上げ回数"],1)

    def test_hardとTPと期限が優先しpending後のMFE増でも床起動を補完しない(self) -> None:
        """XSなら起動可能でも先に作られた注文理由を取り直さない。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。保有後の高MFEで過去のarmを捏造しない。
        """
        for side in (1,-1):
            for reason,now,profit in (("保護",12.,-125.),("利確",12.,250.),("期限",900.,250.)):
                state=opened(side)
                state.bar(source(11.5,12,Fraction(10000+side*20),side))
                quote(state,now,13,profit)
                self.assertEqual(state.pending["reason"],reason)
                self.assertFalse(state.position["armed"])
                self.assertIsNone(state.position["trail_stop"])
                quote(state,now+.5,14,300.)
                self.assertFalse(state.position["armed"])
                self.assertEqual(state.position["sar_updates"],0)
                self.assertEqual(state.pending["reason"],reason)

    def test_X0はSAR列や新方式に影響されず旧31の全保存運用と同じになる(self) -> None:
        """X0の直呼出しを同じ人工入力の旧関数と比較する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。純入口・fill/order/trace/取引/品質をそのまま保つ。
        """
        for side in (1,-1):
            own=signal(side)
            events=[event(10.,10,side,-5.),event(11.,11,side,-5.),event(12.,12,side,50.),
                    event(13.,13,side,20.),event(14.,14,side,15.),event(901.,20,side,0.)]
            old,old_info=O.BASE.replay(events,[deepcopy(own)],[],SESSION,"人工_X0",deepcopy(CONFIG),{"出口ID":"X0"},"順行",BOUNDS)
            current,current_info=O.replay(events,[deepcopy(own)],[],[source(12.,12,Fraction(10100))],SESSION,"人工_X0",deepcopy(CONFIG),{"出口ID":"X0"},"順行",BOUNDS)
            for name in ("fills","orders","trades","signals","normal_log"):
                self.assertEqual(getattr(old,name),getattr(current,name))
            self.assertEqual(old_info,current_info)

    def test_XS原順replayは同keyのBBOを先に処理しNP参照を公開しない(self) -> None:
        """directメソッドだけでなく、統合timelineの種類順とNP除外も検査する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。同秒後行で初適用し、pending中の不良公開はglobalだけ更新。
        """
        own=signal()
        events=[event(10.,10,1,-5.),event(11.,11,1,-5.),event(12.,12,1,20.),event(12.,13,1,20.),
            event(13.,14,1,20.),event(14.,14,1,10.),event(15.,15,1,20.),event(901.,20,1,0.)]
        sar=[source(12.,12,Fraction(10012)),source(13.,14,Fraction(10100),index=1,publish=False),
            source(14.,14,None,ready=False,index=2)]
        state,info=O.replay(events,[own],[],sar,SESSION,"人工_XS",deepcopy(CONFIG),{"出口ID":"XS"},"順行",BOUNDS)
        updates=[row for row in state.normal_log if row["動作"]=="追尾線更新" and row.get("更新根拠")=="公開SAR次足線"]
        self.assertEqual([(row["時計秒"],row["原板行"]) for row in updates],[(12.,13)])
        self.assertEqual(state.trades[0]["最終追尾価格"],10015)
        self.assertEqual(state.trades[0]["最終SAR適用参照"]["index"],0)
        self.assertEqual(state.latest_publication["index"],2)
        self.assertIsNone(state.latest_sar)
        published=[row for row in state.normal_log if row["動作"]=="SAR公開参照更新"]
        self.assertEqual([row["最新SAR参照"]["index"] for row in published],[0,2])
        independent=load(HERE/"追尾独立確認.py","SAR32人工の独立XS走査")
        audit=independent.A.Audit()
        detail={"候補ID":"人工_XS","場":SESSION,"品質":{**info,"期間":"人工"},
            "約定":state.fills,"取引":state.trades,"注文":state.orders,"入口取扱":state.signals}
        logs,_=independent.replay_xs(detail,[vars(value) for value in events],{own["イベントID"]:own},sar,audit,BOUNDS)
        self.assertEqual(audit.mismatches,0,audit.errors)
        self.assertEqual(logs,[{"期間":"人工",**row} for row in state.normal_log])


@contextmanager
def driver_fixture(name: str) -> Iterator[SimpleNamespace]:
    """共有明細は指紋だけを人工化し、主の保存境界を隔離する。

    引数: name(str)は主module識別名。
    返り値: Iterator[SimpleNamespace]はdriver/人工study/work/台帳/共有参照/読替辞書。
    """
    driver=load(HERE/"検証.py",name)
    with tempfile.TemporaryDirectory(prefix="SAR32合成_",dir=ROOT/"work") as folder:
        base=Path(folder).resolve()
        if not base.is_relative_to((ROOT/"work").resolve()):
            raise ValueError("人工一時先がwork外")
        study,work=base/"study",base/"work"
        study.mkdir();work.mkdir()
        pointer=json.loads((STUDY/"入口参照.json").read_text(encoding="utf-8"))
        old_lock=json.loads((driver.OLD_STUDY/"固定.json").read_text(encoding="utf-8"))
        hashes={(ROOT/key).resolve():value for key,value in old_lock["ファイルSHA256"].items()}
        hashes.update({(ROOT/item["パス"]).resolve():item["SHA256"] for item in pointer["文書と証明"].values()})
        hashes.update({(ROOT/item["パス"]).resolve():item["圧縮SHA256参考"] for item in pointer["共有明細"]})
        reads,redirects={},{}
        original_read=driver.W.read_json

        def read(path: Path) -> dict:
            """人工proof/結果だけを読替え、コードと入力宣言は元のまま読む。

            引数: path(Path)はJSON読込先。
            返り値: dictは人工値又は既知の宣言。実圧縮明細は読まない。
            """
            key=Path(path).resolve()
            if key in reads: return deepcopy(reads[key])
            return original_read(redirects.get(key,path))

        def digest(path: Path) -> str:
            """共有旧データは宣言済みSHAを使い、実明細を一切開かない。

            引数: path(Path)は指紋対象。
            返り値: strは人工世界の旧指紋又は実コード/人工ファイルのSHA。
            """
            key=Path(path).resolve()
            if key in hashes: return hashes[key]
            return sha(redirects.get(key,Path(path)))

        with patch.object(driver.W,"read_json",side_effect=read),patch.object(driver.O,"sha",side_effect=digest):
            config=driver.expected_config()
            (study/"条件.json").write_text(json.dumps(config,ensure_ascii=False),encoding="utf-8")
            (study/"入力台帳.json").write_text(json.dumps({"参照":str(driver.MANIFEST_PATH),"SHA256":sha(driver.MANIFEST_PATH)}),encoding="utf-8")
            (study/"入口参照.json").write_text(json.dumps(pointer,ensure_ascii=False),encoding="utf-8")
            (study/"計画.md").write_text("人工固定計画\n",encoding="utf-8")
            (work/"診断予定.json").write_text("{}\n",encoding="utf-8")
            sessions=[f"2026-09-{1+i//2:02d}_{'Day' if i%2==0 else 'Night'}" for i in range(40)]
            sessions += [f"2026-10-{20+i//2:02d}_{'Day' if i%2==0 else 'Night'}" for i in range(24)]
            sessions += ["2026-11-04_Day","2026-11-04_Night"]
            manifest={"entries":[{"session":session,"in_session_contract_codes":list(CONTRACT)} for session in sessions]}
            yield SimpleNamespace(D=driver,study=study,work=work,manifest=manifest,pointer=pointer,config=config,
                hashes=hashes,reads=reads,redirects=redirects,base=base)


def driver_block(driver: Any, session: str, empty: bool = False) -> dict:
    """固定31の人工OHLC再構成から、SARとwhitelist信号を作る。

    引数: driver(Any)は32主、session(str)は人工場、empty(bool)は無活動の末尾検査。
    返り値: dictは市場抽出を使わない人工当場。未来labelは含めない。
    """
    values=[100. if empty else 100.+i for i in range(21)]
    lower=[frame(i,high=value,low=value,close=value,base=15300.) for i,value in enumerate(values)]
    higher=[frame(i,high=value,low=value,close=value,minutes=15) for i,value in enumerate([95.]*10+[105.]*10+[110.])]
    low_rows=driver.D.J.NumericBank(3).build(lower,session,CONTRACT)[0]
    high_rows=driver.D.J.NumericBank(15).build(higher,session,CONTRACT)[0]
    signals,quality=driver.D.I.generate(low_rows,high_rows,session,100000.,200000.,driver.OLD_CONFIG)
    signals={key:[] if empty else [driver.pure_signal(row) for row in rows] for key,rows in signals.items()}
    sar_rows,sar_quality=J.SARBank().build(lower,session,CONTRACT)
    return {"events":[],"frames":{3:low_rows,15:high_rows},"signals":signals,"quality":quality,
        "sar_rows":sar_rows,"sar_quality":sar_quality,"input_quality":{"場":session,"尾部欠枠":{"3":0,"15":0}},
        "cutoff":100000.,"deadline":200000.,"duration":100.}


class 主の共有入口と非損益境界検証(unittest.TestCase):
    """共有caseからの未来値遮断、非PnL準備、四運用と固定を人工で調べる。"""

    def test_whitelistだけがliveに入りATR表現差はD整数境界を保つ(self) -> None:
        """将来ラベルを変えても純信号が変わらず、元辞書も共有しない。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。actual build_sessionの末尾でもwhitelistを通す。
        """
        with driver_fixture("SAR32人工の純signal") as f:
            driver=f.D
            old={**signal(),"ラベル":"人工未来","新規価格":999999,"判定時計秒":999999.,
                "最大順行pt":999999.,"観測最大逆行pt":999999.,"将来辞書":{"値":999}}
            pure=driver.pure_signal(old)
            self.assertEqual(set(pure),set(driver.SIGNAL_FIELDS))
            old["ラベル"]="別未来";old["将来辞書"]["値"]=-999
            self.assertEqual(driver.pure_signal(old),pure)
            old["atr"]=30.
            self.assertEqual(pure["atr"],25.)
            a={**pure,"atr":24.}
            b={**pure,"atr":24.+1e-14}
            self.assertNotEqual(driver.J.canonical_sha([a]),driver.J.canonical_sha([b]))
            self.assertEqual(driver.decision_signal(a),driver.decision_signal(b))
            self.assertNotEqual(driver.decision_signal({**pure,"atr":25.}),driver.decision_signal({**pure,"atr":25.+1e-14}))
            block=driver_block(driver,SESSION)
            for rows in block["signals"].values():
                for row in rows: row.update(ラベル="混入させない未来",最大順行pt=99999.)
            with patch.object(driver.D,"build_session",return_value=block):
                result=driver.build_session({"session":SESSION,"in_session_contract_codes":list(CONTRACT)}, {}, {},J.SARBank(),f.config)
            self.assertTrue(all(set(row)==set(driver.SIGNAL_FIELDS) for rows in result["signals"].values() for row in rows))

    def test_人工66prepareは純射影だけを共有し運用先着会計圧縮を呼ばない(self) -> None:
        """実caseを開かず、人工未来を混ぜた比較caseだけを渡す。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。旧CCI/context447MBを新準備へ転記しない。
        """
        with driver_fixture("SAR32人工の非損益準備") as f:
            driver=f.D
            blocks={entry["session"]:driver_block(driver,entry["session"]) for entry in f.manifest["entries"]}
            cases={key:[] for key in ("3分_C0","3分_C1")}
            for block in blocks.values():
                for key,rows in block["signals"].items():
                    cases[key].extend({**deepcopy(row),"ラベル":"人工未来","新規価格":999999.,"最大順行pt":999999.} for row in rows)
            bank_ids=[]

            def build(entry: dict, manifest: dict, banks: dict, sarbank: Any, config: dict) -> dict:
                """市場抽出を完全に人工材料へ差し替える。

                引数: entry/manifest/banks/config(dict)とsarbank(Any)は主の同署名。
                返り値: dictは人工当場。3/15/SAR銀行の同一個体継続を記録。
                """
                self.assertEqual(set(banks),{3,15})
                bank_ids.append((id(banks[3]),id(banks[15]),id(sarbank)))
                return deepcopy(blocks[entry["session"]])

            forbidden=AssertionError("prepareから運用/先着/会計/圧縮へ進まない")
            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"build_session",side_effect=build), \
                    patch.object(driver,"load_shared_cases",return_value=cases),patch.object(driver,"freeze",side_effect=forbidden) as freeze, \
                    patch.object(driver.ENGINE,"replay",side_effect=forbidden) as replay, \
                    patch.object(driver.D,"shadow_label",side_effect=forbidden) as label, \
                    patch.object(driver.D.W.OLD,"気配経路",side_effect=forbidden) as path, \
                    patch.object(driver,"operation_metrics",side_effect=forbidden) as metric, \
                    patch.object(driver,"compressed",side_effect=forbidden) as compressed,redirect_stdout(io.StringIO()):
                driver.run(f.study,f.work,True)
            for guard in (freeze,replay,label,path,metric,compressed): guard.assert_not_called()
            proof=json.loads((f.work/"準備点検.json").read_text(encoding="utf-8"))
            self.assertEqual(len(proof["準備"]),66)
            self.assertEqual(proof["純信号数"],132)
            self.assertEqual(len(set(bank_ids)),1)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertTrue(proof["旧31純信号同値"])
            for block in proof["準備"]:
                self.assertNotIn("指標",block)
                self.assertNotIn("全複合context",block)
                self.assertTrue(all(set(row)==set(driver.SIGNAL_FIELDS) for row in block["純信号"]))
            self.assertTrue(all(not (f.work/name).exists() for name in driver.FILES))
            self.assertFalse((f.study/"結果.json").exists())

    def test_共有必須証明と指紋差を拒否し市場I_Oguardも実明細を開かせない(self) -> None:
        """共有参照の省略/自己更新を許さず、実圧縮I/Oを事前遮断する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。検査で市場資料の存在確認すら実行しない。
        """
        with driver_fixture("SAR32人工の共有参照拒否") as f:
            driver=f.D
            self.assertEqual(driver.validate_entry_reference(f.study),f.pointer)
            target=f.study/"入口参照.json"
            for mode in ("証明省略","旧固定自己更新","共有明細削除","証明SHA差"):
                changed=deepcopy(f.pointer)
                if mode=="証明省略": changed["文書と証明"].pop("結果.json")
                elif mode=="旧固定自己更新": changed["旧固定SHA256"]="0"*64
                elif mode=="共有明細削除": changed["共有明細"].pop()
                else: changed["文書と証明"]["独立監査.json"]["SHA256"]="0"*64
                target.write_text(json.dumps(changed,ensure_ascii=False),encoding="utf-8")
                with self.assertRaises(ValueError): driver.validate_entry_reference(f.study)
            target.write_text(json.dumps(f.pointer,ensure_ascii=False),encoding="utf-8")
            original=f.hashes[(driver.OLD_STUDY/"条件.json").resolve()]
            f.hashes[(driver.OLD_STUDY/"条件.json").resolve()]="0"*64
            with self.assertRaises(ValueError): driver.validate_entry_reference(f.study)
            f.hashes[(driver.OLD_STUDY/"条件.json").resolve()]=original
            for path in (ROOT.parent/"JP_OSE_Data/人工禁止",ROOT/"work/人工禁止.npz",ROOT/"work/CCI突破/00031/入口事例.jsonl.gz"):
                with self.assertRaises(AssertionError): path.open("rb")

    def test_人工無活動一場の2入口4運用がXS会計集計と結果保存まで完了する(self) -> None:
        """市場入力なしでformal末尾まで通し、XSを旧X0制限で拒否しない。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。取引0でも二入口・四運用を保持し、P&L標本を捏造しない。
        """
        with driver_fixture("SAR32人工の四運用末尾") as f:
            driver=f.D
            entry=f.manifest["entries"][0]
            manifest={"entries":[entry]}
            session,period=entry["session"],"学習"
            block=driver_block(driver,session,True)
            self.assertTrue(all(not rows for rows in block["signals"].values()))
            entrances=[]
            details=[]
            for item in driver.sources(f.config):
                entrance={**item,**{name:driver.E.entry_metrics([],name) for name in driver.PERIODS},
                    "入口支持":False,"70目標":False}
                entrances.append(entrance)
                cid=item["入口ID"]+"_X0"
                state,info=driver.ENGINE.BASE.replay([],[],[],session,cid,deepcopy(CONFIG),{"出口ID":"X0"},"順行")
                info.update(期間=period,場時間分=100.)
                details.append({"候補ID":cid,"場":session,"品質":info,"約定":state.fills,
                    "取引":state.trades,"注文":state.orders,"入口取扱":state.signals})
            f.reads[(driver.OLD_STUDY/"結果.json").resolve()]={"入口評価":entrances}
            old_detail=f.work/"人工旧全運用.jsonl.gz"
            old_trail=f.work/"人工旧追尾.jsonl.gz"
            with gzip.open(old_detail,"wt",encoding="utf-8") as stream:
                for row in details: stream.write(json.dumps(row,ensure_ascii=False)+"\n")
            with gzip.open(old_trail,"wt",encoding="utf-8") as stream:
                stream.write("")

            def publish(study: Path, path: Path, ids: list, supplied: dict, prefix: str) -> None:
                """Viewerの実市場参照を作らず、形式だけの人工一覧を置く。

                引数: study/path(Path)は人工先、ids(list)は四案、supplied(dict)は人工台帳、prefix(str)は表示接頭辞。
                返り値: None。市場内容や旧Viewerを開かない。
                """
                (study/"一覧.resources.json").write_text('{"resources":[]}',encoding="utf-8")

            with patch.object(driver,"manifest_for",return_value=manifest), \
                    patch.object(driver,"build_session",return_value=block),patch.object(driver,"freeze",return_value={}), \
                    patch.object(driver,"load_shared_cases",return_value={"3分_C0":[],"3分_C1":[]}), \
                    patch.object(driver,"shared_path",side_effect=lambda pointer,name:old_detail if name=="全運用詳細.jsonl.gz" else old_trail), \
                    patch.object(driver.E,"publish_details",side_effect=publish), \
                    patch.object(driver,"operation_metrics",wraps=driver.operation_metrics) as metrics,redirect_stdout(io.StringIO()):
                summary=driver.run(f.study,f.work,False)
            self.assertEqual(summary["入口数"],2)
            self.assertEqual(summary["運用候補数"],4)
            self.assertEqual(metrics.call_count,12)
            self.assertEqual(sum(call.args[3]=={"出口ID":"XS"} for call in metrics.call_args_list),6)
            result=json.loads((f.study/"結果.json").read_text(encoding="utf-8"))
            self.assertEqual(len(result["入口評価"]),2)
            self.assertEqual([row["候補ID"] for row in result["結果"]],["3分_C0_X0","3分_C0_XS","3分_C1_X0","3分_C1_XS"])
            self.assertTrue(all(row["学習"]["運用"]["完結取引数"]==0 for row in result["結果"]))
            self.assertTrue(all((f.work/name).is_file() for name in driver.FILES))

    def test_独立準備と最終合成のjoinを必須にし固定差とpartial既存を拒否する(self) -> None:
        """人工の現版proofだけでfreezeの拒否/成功/再固定を検査する。

        引数: self(TestCase)は検査インスタンス。
        返り値: None。旧明細は指紋宣言だけを使い、正式固定を変更しない。
        """
        with driver_fixture("SAR32人工の固定join") as f:
            driver=f.D
            prepared={"コードSHA256":driver.code_pins(),"条件SHA256":sha(f.study/"条件.json"),
                "入力台帳SHA256":sha(f.study/"入力台帳.json"),"参照台帳SHA256":sha(driver.MANIFEST_PATH),
                "入口参照SHA256":sha(f.study/"入口参照.json"),"ラベル計算":False,"損益計算":False,"旧31純信号同値":True}
            prepared_path=f.work/"準備点検.json"
            prepared_path.write_text(json.dumps(prepared),encoding="utf-8")
            with self.assertRaises((ValueError,FileNotFoundError)):
                driver.validate_independent(f.study,f.work)
            dependency=ROOT/"scripts/一目基準線/状態独立確認.py"
            independent={"全件一致":True,"不一致数":0,"不一致":[],"ラベル計算":False,"損益計算":False,
                "主準備SHA256":sha(prepared_path),"主コードSHA256":driver.code_pins(),
                "条件SHA256":sha(f.study/"条件.json"),"入力台帳SHA256":sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256":sha(driver.MANIFEST_PATH),"入口参照SHA256":sha(f.study/"入口参照.json"),
                "コードSHA256":sha(HERE/"状態独立確認.py"),"追尾コードSHA256":sha(HERE/"追尾独立確認.py"),
                "依存コードSHA256":{dependency.relative_to(ROOT).as_posix():sha(dependency)}}
            independent_path=f.work/"独立準備点検.json"
            for key in ("全件一致","不一致数","不一致","ラベル計算","損益計算","主準備SHA256","主コードSHA256",
                        "条件SHA256","入力台帳SHA256","参照入力台帳SHA256","入口参照SHA256","コードSHA256","追尾コードSHA256","依存コードSHA256"):
                bad=deepcopy(independent)
                if key=="全件一致":bad[key]=False
                elif key=="不一致数":bad[key]=1
                elif key=="不一致":bad[key]=["人工不一致"]
                elif key in ("ラベル計算","損益計算"):bad[key]=True
                elif key=="依存コードSHA256":bad[key]={}
                else:bad[key]="0"*64
                independent_path.write_text(json.dumps(bad),encoding="utf-8")
                with self.assertRaises(ValueError):driver.validate_independent(f.study,f.work)
            independent_path.write_text(json.dumps(independent),encoding="utf-8")
            self.assertEqual(driver.validate_independent(f.study,f.work),independent)

            # ----------------------------------------
            # 正式合成の代わりを一時先に置き、未完/不一致と版固定を調べる。
            paths=[HERE/name for name in ("検証.py","指標.py","運用.py","合成検証.py")]+[f.study/"条件.json"]
            synthetic={"全件成功":True,"合成編集終了":False,
                "ファイルSHA256":{path.relative_to(ROOT).as_posix():sha(path) for path in paths}}
            canonical=(WORK/"合成検証.json").resolve()
            synthetic_path=f.work/"人工合成proof.json"
            f.reads[canonical]=synthetic
            f.redirects[canonical]=synthetic_path
            synthetic_path.write_text(json.dumps(synthetic),encoding="utf-8")
            with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
            synthetic["合成編集終了"]=True
            f.reads[canonical]=synthetic
            synthetic_path.write_text(json.dumps(synthetic),encoding="utf-8")
            fixed=driver.freeze(f.study,f.work)
            self.assertEqual(driver.freeze(f.study,f.work),fixed)
            self.assertEqual(fixed["独立準備SHA256"],sha(independent_path))
            self.assertEqual(fixed["入口参照SHA256"],sha(f.study/"入口参照.json"))
            (f.study/"計画.md").write_text("人工固定後差\n",encoding="utf-8")
            with self.assertRaises(ValueError):driver.freeze(f.study,f.work)

            # ----------------------------------------
            # partialだけ残った状態も結果既存も、byteを保って早期停止する。
            partial=f.work/driver.FILES[0]
            partial.write_bytes("人工partial".encode("utf-8"))
            before=partial.read_bytes()
            with patch.object(driver,"manifest_for",return_value=f.manifest), \
                    patch.object(driver,"freeze",side_effect=AssertionError("partial既存はfreeze前に停止")) as freeze, \
                    patch.object(driver,"build_session",side_effect=AssertionError("partial既存は抽出禁止")) as build:
                with self.assertRaises(ValueError):driver.run(f.study,f.work,False)
            freeze.assert_not_called();build.assert_not_called()
            self.assertEqual(partial.read_bytes(),before)
            partial.unlink()
            existing=f.study/"結果.json"
            existing.write_text('{"人工既存":true}',encoding="utf-8")
            before=existing.read_bytes()
            with patch.object(driver,"manifest_for",return_value=f.manifest), \
                    patch.object(driver,"build_session",side_effect=AssertionError("既存結果後は抽出禁止")) as build:
                with self.assertRaises(ValueError):driver.run(f.study,f.work,False)
            build.assert_not_called()
            self.assertEqual(existing.read_bytes(),before)
            changed=deepcopy(f.config);changed["SAR追尾"]["AF上限整数"]+=2
            with self.assertRaises(ValueError):driver.validate_config(changed)
            changed=deepcopy(f.config);changed["運用"]["返済待機秒"]+=1
            with self.assertRaises(ValueError):driver.validate_config(changed)


def main() -> None:
    """人工検査だけを実行し、現5pinsと独立補助へ証拠をbindする。

    引数: なし。--finalは主/条件/独立の完成後にroot指示で指定する。
    返り値: None。実市場prepare・指標・先着・運用を起動しない。
    """
    parser=argparse.ArgumentParser(description="精密公開SARと最低同値床の人工境界")
    parser.add_argument("--final",action="store_true")
    arguments=parser.parse_args()
    paths=[HERE/name for name in ("検証.py","指標.py","運用.py","合成検証.py")]+[STUDY/"条件.json"]
    if any(not path.is_file() for path in paths):
        raise ValueError("主3/合成/条件の完成を待つ")
    pins={path.relative_to(ROOT).as_posix():sha(path) for path in paths}
    independent=sha(HERE/"状態独立確認.py")
    trail=sha(HERE/"追尾独立確認.py")
    stream=io.StringIO()
    with deny_market():
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged=pins=={path.relative_to(ROOT).as_posix():sha(path) for path in paths} and independent==sha(HERE/"状態独立確認.py") and trail==sha(HERE/"追尾独立確認.py")
    success=result.wasSuccessful() and result.testsRun>0 and unchanged
    proof={"全件成功":success,"検証件数":result.testsRun,"合成編集終了":bool(arguments.final and success),
        "実資料の先着損益計算":False,"実行中コード条件不変":unchanged,"ファイルSHA256":pins,
        "独立数値補助SHA256":independent,"独立追尾補助SHA256":trail,
        "範囲":"元OHLC Fraction/AF整数/初期同値/strict反転/前2clamp/EP/AF上限/鏡像/3002足閉形式・hex長桁往復/E±1÷10^5000の精密5pt境界、数値carry/NP/欠枠/不正/限月/尾部、同値床必須/最新一つ/同key→後続BBO/無効逆向き旧床/既越要求後1秒BBO/建玉pending凍結とglobal継続/hard-TP-期限優先/X0旧31保存値同値、独立核/全row/品質比較、純signal whitelistとATR判断射影、人工66非PnLprepare、人工1場無活動2入口4運用末尾XS会計adapter、共有8証明/指紋/独立準備join/最終合成/固定後差/既存partialと結果拒否。実原板/cache/実圧縮明細はstat/open禁止。旧明細は宣言SHAだけを人工化し内容を開かない。",
        "失敗":[{"検証":str(case),"内容":message} for case,message in result.failures],
        "エラー":[{"検証":str(case),"内容":message} for case,message in result.errors],"実行記録":stream.getvalue()}
    WORK.mkdir(parents=True,exist_ok=True)
    path=WORK/("合成検証.json" if arguments.final else "合成検証_途中.json")
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({key:proof[key] for key in ("全件成功","検証件数","合成編集終了","実資料の先着損益計算","実行中コード条件不変")},ensure_ascii=False))
    if not success:raise SystemExit(1)


if __name__=="__main__":
    main()


