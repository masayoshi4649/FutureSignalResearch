"""市場資料を遮断し、Force波の数値・上位公開・一巡順序を人工だけで検査する。"""

import argparse
import builtins
from collections import Counter
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
HERE, WORK = Path(__file__).resolve().parent, ROOT/"work/Force波"
SESSION = "人工Force場"
CONFIG = {"残り時間下限分": 60, "確認遅延上限秒": 30}


def normalized(path: object) -> str:
    """市場遮断用の正規絶対パスを得る。

    引数: path(object)はファイル先又は非パス。
    返り値: strは正規パス又は空文字。
    """
    try: return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError): return ""


@contextmanager
def deny_market():
    """原板・実cache・実圧縮明細のopen/statを拒否する。

    引数: なし。
    返り値: contextmanagerは人工一時先とコード/小型証明だけを許す。
    """
    raw, work = normalized(ROOT.parent/"JP_OSE_Data"), normalized(ROOT/"work")
    opened, path_opened, stated = builtins.open, Path.open, Path.stat

    def check(path):
        """許可人工先以外の市場資料を拒否する。

        引数: path(object)はアクセス先。
        返り値: None。違反はAssertionError。
        """
        name = normalized(path); inside = name.startswith(work+os.sep)
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith(os.path.normcase("Force47合成_"))
        if name == raw or name.startswith(raw+os.sep) or inside and not artificial and name.endswith((".npz", ".jsonl.gz", ".trades.jsonl")):
            raise AssertionError("人工から実市場資料を読まない:"+str(path))

    def safe_open(path, *args, **kwargs):
        """通常openへ遮断を適用する。

        引数: path/args/kwargsは元open引数。
        返り値: objectは許可されたファイル。
        """
        check(path); return opened(path, *args, **kwargs)

    def safe_path_open(path, *args, **kwargs):
        """Path.openへ遮断を適用する。

        引数: path/args/kwargsは元open引数。
        返り値: objectは許可されたファイル。
        """
        check(path); return path_opened(path, *args, **kwargs)

    def safe_stat(path, *args, **kwargs):
        """Path.statへ遮断を適用する。

        引数: path/args/kwargsは元stat引数。
        返り値: objectは許可されたstat。
        """
        check(path); return stated(path, *args, **kwargs)

    with patch.object(builtins,"open",safe_open), patch.object(Path,"open",safe_path_open), patch.object(Path,"stat",safe_stat): yield


def load(path: Path, name: str):
    """CLI起動せずコード定義を読む。

    引数: path(Path)はコード、name(str)は読取識別子。
    返り値: moduleは定義。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name,path); value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value; spec.loader.exec_module(value); return value


def sha(path: Path) -> str:
    """小型証明とコードのSHAを求める。

    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


J, I = load(HERE/"指標.py","Force47人工数値"), load(HERE/"入口.py","Force47人工入口")


def frame(index: int, close: float, q: float | None = 3., minutes: int = 3, **changes) -> dict:
    """有限正の完全公開人工OHLCを作る。

    引数: index(int)は番号、close(float)はC、q(float|None)は観測量、minutes(int)は幅、changesは置換。
    返り値: dictは共有3分15列又は上位材料。
    """
    row = {"場": SESSION, "index": index, "minutes": minutes, "start": index*minutes*60., "end": (index+1)*minutes*60.,
        "confirm": (index+1)*minutes*60.+1., "confirm_line": index+1, "publish": True, "missing": 0,
        "open": close, "high": close+1., "low": close-1., "close": close, "atr": 10.1,
        "数量参照": {"観測差分量": q, "数量基準完全": q is not None}}
    row.update(changes); return row


def higher(direction: int = 1, later: int | None = None, reveal: float = 1000.) -> list[dict]:
    """負の人工時計に助走済み上位ペアを用意する。

    引数: direction(int)は初D、later(int|None)は後続D、reveal(float)は後続公開時計。
    返り値: list[dict]は14列。負時計は人工助走を小さく表すためだけに使う。
    """
    rows = [J.upper_projection(frame(i,200.,minutes=15,start=-1800.+900*i,end=-900.+900*i,
        confirm=-899.+900*i,macd_hist=float(i*direction))) for i in range(2)]
    if later is not None:
        rows.append(J.upper_projection(frame(2,200.,minutes=15,start=0.,end=900.,confirm=reveal,confirm_line=1,
            macd_hist=float(direction+later))))
    return rows


def material(kind: str = "T") -> list[dict]:
    """b3/j4/終端5を持つForce波を作る。

    引数: kind(str)はT又はR。
    返り値: list[dict]は旧ATR/Qを持つ人工材料。
    """
    return [frame(i,value) for i,value in enumerate([100.,101.,103.,100.,102.,104. if kind=="T" else 98.])]


def generated(source: list[dict], uppers: list[dict] | None = None, cutoff: float = 100000., deadline: float = 200000.) -> dict:
    """人工だけを精密Forceと一巡機械へ渡す。

    引数: source(list[dict])は共有材料、uppers(list[dict]|None)は上位、cutoff/deadline(float)は人工境界。
    返り値: dictは全当時判定。
    """
    rows,_ = J.build(source,SESSION)
    return I.generate(rows,higher() if uppers is None else uppers,SESSION,cutoff,deadline,CONFIG)


def reflected(source: list[dict], axis: float = 500.) -> list[dict]:
    """価格と上位Hを鏡像にする。

    引数: source(list[dict])は3分又は上位、axis(float)は反射定数。
    返り値: list[dict]は高安交換・終値反射・H符号反転した足。
    """
    result = []
    for row in source:
        value = {**deepcopy(row),"open":axis-row["open"],"high":axis-row["low"],"low":axis-row["high"],"close":axis-row["close"]}
        if "macd_hist" in row: value["macd_hist"] = -row["macd_hist"] if J.finite(row["macd_hist"]) else None
        result.append(value)
    return result


def actions(block: dict) -> list[str]:
    """人工監視の動作名だけを順に取り出す。

    引数: block(dict)はgenerate出力。
    返り値: list[str]は動作列。
    """
    return [action["動作"] for row in block["monitor_trace"] for action in row["動作"]]


# ----------------------------------------
# 数量・種・銀行の規約は、監視や将来の入口成績とは独立に検査する。

class Force精密検証(unittest.TestCase):
    """元float精密化・二X種・0量・欠測の境界を検査する。"""

    def test_最古q不要と二X平均種と0量残響(self):
        """価格基準足のqや総q正を追加gateにしない。

        引数: self(TestCase)は対象。
        返り値: None。3足目F=9/2、4足目=-9/2、0量で-3/2を確認する。
        """
        source = material(); source[0]["数量参照"] = None; source[4]["数量参照"]["観測差分量"] = 0.
        rows,_ = J.build(source,SESSION)
        self.assertEqual([row["Force2"]["有効"] for row in rows[:3]],[False,False,True])
        self.assertEqual(rows[2]["Force2"],J.exact(Fraction(9,2)))
        self.assertEqual(rows[3]["Force2"],J.exact(Fraction(-9,2)))
        self.assertEqual(rows[4]["Force素"],J.exact(Fraction(0)))
        self.assertEqual(rows[4]["Force2"],J.exact(Fraction(-3,2)))
        zero,_ = J.build([frame(i,100.+i,q=0.) for i in range(4)],SESSION)
        self.assertEqual(zero[2]["Force2"],J.exact(Fraction(0)))
        self.assertEqual(zero[3]["Force前符号"],0)

    def test_不完全量だけなら終値基準を保持して再seedする(self):
        """qbadを0とせずForce列だけ解除し、次足Xにbad足の既知Cを使える。

        引数: self(TestCase)は対象。
        返り値: None。価格基準と数量区間を分離する。
        """
        for quantity in (None,{"数量基準完全":False,"観測差分量":0.},{"数量基準完全":True,"観測差分量":-1.}):
            source = [frame(i,100.+i) for i in range(6)]; source[3]["数量参照"] = quantity
            rows,_ = J.build(source,SESSION)
            self.assertFalse(rows[3]["Force2"]["有効"])
            self.assertEqual(rows[4]["Force価格基準足番号"],3)
            self.assertEqual(rows[4]["Force素"],J.exact(Fraction(3)))
            self.assertFalse(rows[4]["Force2"]["有効"]); self.assertEqual(rows[5]["Force2"],J.exact(Fraction(3)))

    def test_NP欠枠は不投入とgap正常当足新種(self):
        """局所Forceを欠落観測へ跨がせない。

        引数: self(TestCase)は対象。
        返り値: None。幅0自体はForceの欠測理由でないことも確認する。
        """
        for field,value in (("publish",False),("missing",1)):
            source = material(); source[3][field] = value
            rows,_ = J.build(source,SESSION)
            self.assertIsNone(rows[4]["Force価格基準足番号"])
            self.assertFalse(rows[5]["Force2"]["有効"])
        source = material(); source.pop(2)
        rows,_ = J.build(source,SESSION)
        self.assertIsNone(rows[2]["Force価格基準足番号"])
        self.assertEqual(rows[3]["Force価格基準足番号"],3)
        flat = [frame(i,100.,high=100.,low=100.) for i in range(4)]
        self.assertEqual(J.build(flat,SESSION)[0][-1]["Force符号"],0)

    def test_上位銀行carryと契約欠枠NP尾部を分離(self):
        """固定29update順の新15分Hと場内公開参照を混同しない。

        引数: self(TestCase)は対象。
        返り値: None。人工のみで種35足、場間carryと全resetを確認する。
        """
        source = [frame(i,100.+i,minutes=15) for i in range(36)]
        for row in source: row["publish"] = False
        bank = J.UpperBank(); rows,quality = bank.build(source,SESSION,("人工限月",))
        reference = J.BASE.NumericBank()
        expected = [J.upper_projection(reference.update(row,SESSION)) for row in source]
        self.assertEqual(rows,expected); self.assertIsNotNone(rows[34]["macd_hist"])
        self.assertEqual(quality["非公開価格数値更新数"],36)
        following = frame(0,140.,minutes=15)
        self.assertIsNotNone(bank.build([following],SESSION,("人工限月",))[0][0]["macd_hist"])
        self.assertIsNone(bank.build([following],SESSION,("別限月",))[0][0]["macd_hist"])
        for change in ({"missing":1},{"end":899.,"confirm":900.},{"low":200.}):
            bank = J.UpperBank(); bank.build(source,SESSION,("人工限月",))
            row = frame(0,140.,minutes=15,**change)
            result,_ = bank.build([row],SESSION,("人工限月",))
            self.assertIsNone(result[0]["macd_hist"])
        bank = J.UpperBank(); bank.build(source,SESSION,("人工限月",),tail_missing=1)
        self.assertIsNone(bank.build([following],SESSION,("人工限月",))[0][0]["macd_hist"])

    def test_独立指数重み和の全26と生上位14を別照合(self):
        """再帰Forceと明示重み和、固定更新Hと独立中心化銀行を比較する。

        引数: self(TestCase)は対象。
        返り値: None。H値だけ限定許容し価格/精密分数/品質は厳密一致。
        """
        independent = load(HERE/"状態独立確認.py","Force47人工独立数値")
        if not all(hasattr(independent,k) for k in ("build_local","UpperHistory")): self.skipTest("独立数値完成前")
        scenarios = [material(),material("R"),[frame(i,100.+i/4,q=float(i%4)) for i in range(30)]]
        for field,value in (("publish",False),("missing",1),("数量参照",None)):
            source = material(); source[3][field] = value; scenarios.append(source)
        source = material(); source.pop(2); scenarios.append(source)
        for source in [*scenarios,*[reflected(value) for value in scenarios]]:
            self.assertEqual(J.build(source,SESSION),independent.build_local(source,SESSION))
        for reflection in (False,True):
            bank,other = J.UpperBank(),independent.UpperHistory()
            for offset,contract,tail in ((0,"一",0),(1,"一",0),(2,"二",1),(3,"二",0)):
                source = [frame(i,200.+offset*10+math.sin(i/3),minutes=15) for i in range(40)]
                if offset==1: source[10]["publish"] = False
                if offset==2: source[7]["missing"] = 1
                if reflection: source = reflected(source)
                a,qa = bank.build(source,SESSION,(contract,),tail)
                b,qb = other.build(source,SESSION,(contract,),tail)
                self.assertEqual(qa,qb)
                audit = independent.Audit(); audit.check("上位全14",a,b)
                self.assertEqual(audit.mismatches,0)

    def test_H水準の符号は新gateにせず差符号だけstrict(self):
        """表示Hの微差と方向Dの微差を同じ許容へ隠さない。

        引数: self(TestCase)は対象。
        返り値: None。H水準0跨ぎは許容内、差0跨ぎは不一致。
        """
        independent = load(HERE/"状態独立確認.py","Force47人工H責任分界")
        for field in ("macd_hist","上位ヒスト現","上位ヒスト前"):
            audit = independent.Audit(); audit.check(field,-1e-16,1e-16)
            self.assertEqual(audit.mismatches,0)
        audit = independent.Audit(); audit.check("上位ヒスト差",-1e-16,1e-16)
        self.assertGreater(audit.mismatches,0)


class 観測順序検証(unittest.TestCase):
    """登録・回復・初端の一回消費と三候補の同一監視を検査する。"""

    def test_TとRは異なる価格端と実方向でSに入る(self):
        """RをTの不採用補集合にせず、回復後の明示失敗だけで発動する。

        引数: self(TestCase)は対象。
        返り値: None。b3/j4/kf5の役割/時刻/全三採否を確認する。
        """
        for kind in ("T","R"):
            block = generated(material(kind),higher(later=-1) if kind=="R" else higher())
            self.assertEqual(len(block["decisions"]),1)
            row = block["decisions"][0]
            self.assertEqual((row["登録足番号"],row["回復足番号"],row["index"]),(3,4,5))
            self.assertEqual((row["価格区分"],row["判別種別"]),(kind,kind))
            self.assertEqual(row["side"],1 if kind=="T" else -1)
            self.assertEqual([len(block["signals"]["3分_"+p]) for p in I.POLICIES],[1,0,1] if kind=="T" else [0,1,1])
            self.assertEqual(sum(row["受理"] for row in block["registrations"]),1)
            self.assertIn("監視中又は同足で監視終了",block["registrations"][1]["登録除外理由"])

    def test_回復前失敗と初回D不一致はrawに混ぜない(self):
        """回復前WAITを後の価格Pとして取り直さない。

        引数: self(TestCase)は対象。
        返り値: None。0/逆Dで初回回復を消費する。
        """
        source = material(); source[4] = frame(4,98.); source[5] = frame(5,110.)
        block = generated(source)
        self.assertIn("回復前失敗WAIT",actions(block)); self.assertFalse(block["decisions"])
        for direction in (0,-1):
            block = generated(material(),higher(later=direction,reveal=901.))
            self.assertIn("初回回復不一致WAIT",actions(block)); self.assertFalse(block["decisions"])

    def test_対象外足の価格失敗を見ず初対象で失敗を先消費(self):
        """bの遅延追加gateを作らず、対象終値の判定順を固定する。

        引数: self(TestCase)は対象。
        返り値: None。Fが回復していても先の逆端失敗を優先する。
        """
        source = material(); source[3]["confirm"] = 1000.
        source[4] = frame(4,95.,confirm=1001.); source[5] = frame(5,98.)
        block = generated(source)
        self.assertTrue(block["registrations"][0]["受理"])
        self.assertIn("段階時点対象外",actions(block)); self.assertIn("回復前失敗WAIT",actions(block))
        self.assertNotIn("初回回復固定",actions(block)); self.assertFalse(block["decisions"])

    def test_六足等号可七先満了とjで寿命を伸ばさない(self):
        """bからの絶対足年齢を両段階で共有する。

        引数: self(TestCase)は対象。
        返り値: None。回復age5→初端age6とage7の差だけを見る。
        """
        source = material()[:4]+[frame(i,100.,q=0.) for i in range(4,8)]+[frame(8,102.),frame(9,104.)]
        self.assertEqual(generated(source)["decisions"][0]["年齢"],6)
        late = material()[:4]+[frame(i,100.,q=0.) for i in range(4,8)]+[frame(8,102.),frame(9,102.),frame(10,104.)]
        block = generated(late)
        self.assertIn("寿命満了",actions(block)); self.assertFalse(block["decisions"])

    def test_取消は年齢より先でD反転だけでは取消しない(self):
        """数値未準備は延命せず、準備済み中立/逆向きは別扱いにする。

        引数: self(TestCase)は対象。
        返り値: None。qbadと新上位不良の取消を確認する。
        """
        source = material()[:4]+[frame(i,100.,q=0.) for i in range(4,11)]
        source[-1]["missing"] = 1
        block = generated(source)
        self.assertIn("監視取消",actions(block)); self.assertNotIn("寿命満了",actions(block))
        for value in (None,):
            uppers = higher(later=-1); uppers[-1]["macd_hist"] = value
            block = generated(material(),uppers)
            self.assertIn("監視取消",actions(block)); self.assertFalse(block["decisions"])
        source = material()[:4]+[frame(4,100.,q=0.),frame(5,100.,q=0.)]
        block = generated(source,higher(later=-1,reveal=901.))
        self.assertNotIn("監視取消",actions(block)); self.assertIn("場末監視取消",actions(block))

    def test_最初価格端はATR技術時間でWAITでも消費する(self):
        """bにATR/cutoff/残60を課さず、終端だけへ適用する。

        引数: self(TestCase)は対象。
        返り値: None。失敗後の別端や後足採り直しをしない。
        """
        for kind in ("atr","time","direction"):
            source = material(); source[3]["atr"] = None
            if kind=="atr": source[5]["atr"] = None
            block = generated(source,higher(later=-1) if kind=="direction" else higher(),cutoff=0. if kind=="time" else 100000.)
            self.assertTrue(block["registrations"][0]["受理"])
            self.assertEqual(len(block["decisions"]),1)
            self.assertEqual(block["decisions"][0]["価格区分"],"T")
            self.assertEqual(block["decisions"][0]["判別種別"],"WAIT")
            self.assertFalse(any(block["signals"].values()))

    def test_端等号とヒゲ両端touchでは消費しない(self):
        """終値で初端を定義し、高安から都合のよい到達順を作らない。

        引数: self(TestCase)は対象。
        返り値: None。同値/ヒゲの後のstrict終値だけで一回発動する。
        """
        for value in (102.,103.):
            source = material()[:5]+[frame(5,value,high=200.,low=50.),frame(6,104.)]
            block = generated(source)
            self.assertEqual(len(block["decisions"]),1); self.assertEqual(block["decisions"][0]["index"],6)
        source = material()[:5]+[frame(5,99.),frame(6,98.)]
        self.assertEqual(generated(source,higher(later=-1))["decisions"][0]["index"],6)

    def test_上位同時点可視と未来追加のprefix不変(self):
        """別場/未来/NPの値を使わず、同key可とkey後行不可を分ける。

        引数: self(TestCase)は対象。
        返り値: None。未来前足の存在で理由やsnapshotを変えない。
        """
        source = material(); small = source[:5]
        base = generated(small)
        future = higher(later=-1,reveal=9999.)
        added = generated(small,future)
        for field in ("registrations","decisions","monitor_trace","signals"): self.assertEqual(base[field],added[field])
        unknown = higher(); unknown[0]["confirm"] = 9999.
        with_unknown = generated(source,unknown); without = generated(source,[unknown[1]])
        for field in ("registrations","decisions","monitor_trace","signals"): self.assertEqual(with_unknown[field],without[field])
        lower = frame(4,102.)
        upper = higher(later=-1,reveal=lower["confirm"])
        upper[-1]["confirm_line"] = lower["confirm_line"]
        self.assertEqual(I.upper_state(upper,lower)["上位方向"],-1)
        upper[-1]["confirm_line"] += 1
        self.assertEqual(I.upper_state(upper,lower)["上位方向"],1)
        same = higher(); same[-1]["macd_hist"] = None
        self.assertFalse(I.upper_state(same,lower)["上位現前準備"])

    def test_鏡像と純13深写と四実役割(self):
        """価格/Q/H/時計を反射して実方向と全採否を対称にする。

        引数: self(TestCase)は対象。
        返り値: None。Sの純集合は単独T/Rの和で、liveへlabelを渡さない。
        """
        self.assertEqual(sum(map(len,I.ACTIVE_ROLES.values())),4)
        for kind in ("T","R"):
            source,uppers = material(kind),higher(later=-1) if kind=="R" else higher()
            normal = generated(source,uppers); mirror = generated(reflected(source),reflected(uppers))
            a,b = normal["decisions"][0],mirror["decisions"][0]
            self.assertEqual((a["価格区分"],a["役割"]),(b["価格区分"],b["役割"]))
            self.assertEqual(a["side"],-b["side"])
            for policy in I.POLICIES:
                self.assertEqual(a["戦略判定"][policy],b["戦略判定"][policy])
            policy = "T0" if kind=="T" else "R0"
            pure = I.pure_signal(a,policy); self.assertEqual(set(pure),set(I.SIGNAL_FIELDS))
            poisoned = deepcopy(a); poisoned["未来label"] = "毒値"; self.assertEqual(pure,I.pure_signal(poisoned,policy))
            normal["signals"]["3分_S0"][0]["戦略判定"][policy]["採用"] = False
            self.assertTrue(a["戦略判定"][policy]["採用"])

    def test_独立登録単位走査の全監視と全判定が一致(self):
        """主一足FSMと独立候補事前列挙/区間走査を全出典で比較する。

        引数: self(TestCase)は対象。
        返り値: None。初回WAIT/期限/対象外/欠測/鏡像を含む全dictを厳密照合する。
        """
        independent = load(HERE/"状態独立確認.py","Force47人工独立一巡")
        if not hasattr(independent,"generate"): self.skipTest("独立監視完成前")
        scenarios = [(material(),higher()),(material("R"),higher(later=-1))]
        for field,value in (("missing",1),("publish",False),("数量参照",None),("atr",None)):
            source = material(); source[5][field] = value; scenarios.append((source,higher()))
        for later in (0,-1): scenarios.append((material(),higher(later=later,reveal=901.)))
        source = material(); source[3]["confirm"] = 1000.; source[4] = frame(4,95.,confirm=1001.); source[5] = frame(5,98.)
        scenarios.append((source,higher()))
        source = material()[:4]+[frame(i,100.,q=0.) for i in range(4,8)]+[frame(8,102.),frame(9,104.)]
        scenarios.append((source,higher()))
        source = material()[:4]+[frame(i,100.,q=0.) for i in range(4,8)]+[frame(8,102.),frame(9,102.),frame(10,104.)]
        scenarios.append((source,higher()))
        for source,uppers in [*scenarios,*[(reflected(a),reflected(b)) for a,b in scenarios]]:
            rows,_ = J.build(source,SESSION)
            self.assertEqual(I.generate(rows,uppers,SESSION,100000.,200000.,CONFIG),
                independent.generate(rows,uppers,SESSION,100000.,200000.,CONFIG))


# ----------------------------------------
# 主のCLI/保存接続は架空場と隔離保存先だけで検査する。

def driver_module():
    """市場起動せず新主driverを読む。

    引数: なし。
    返り値: moduleは現主の定義。
    """
    return load(HERE/"検証.py","Force47人工主")


@contextmanager
def artificial_driver(driver, count: int = 66):
    """T/R二場と空場から成る人工束を隔離先へ作る。

    引数: driver(module)は主、count(int)は人工場数。
    返り値: contextmanagerは共有束/build/条件/参照/保存先。
    """
    with tempfile.TemporaryDirectory(prefix="Force47合成_",dir=ROOT/"work") as temporary:
        folder = Path(temporary); study,work = folder/"study",folder/"work"; study.mkdir(); work.mkdir()
        config = driver.expected_config(); driver.W.write_json(study/"条件.json",config)
        driver.W.write_json(study/"入力台帳.json",{"人工":True})
        ref = {"文書と証明":{},"共有明細":[]}
        for name in ("指標参照.json","上位参照.json"): driver.W.write_json(study/name,ref)
        (study/"計画.md").write_text("人工Force波比較\n",encoding="utf-8")
        driver.W.write_json(work/"診断予定.json",{"人工":True})
        sessions = [str(date(2026,9,22)+timedelta(days=i//2))+("_Day" if i%2==0 else "_Night") for i in range(count)]
        bundle = {name:{} for name in ("lower","numeric","numeric_quality","upper_source","higher","upper_quality")}
        for index,session in enumerate(sessions):
            source = [{**row,"場":session} for row in material("T" if index==0 else "R")] if index<2 else []
            uppers = [{**row,"場":session} for row in (higher() if index==0 else higher(later=-1))] if index<2 else []
            rows,quality = J.build(source,session)
            bundle["lower"][session] = source; bundle["numeric"][session] = rows; bundle["numeric_quality"][session] = quality
            bundle["upper_source"][session] = [I.price_source(row) for row in uppers]
            bundle["higher"][session] = uppers; bundle["upper_quality"][session] = {"場":session,"人工":True}

        def build(entry,manifest,shared,current,include_events=False):
            """実Iを通し、正式時にだけ人工の正常BBOを追加する。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式フラグ。
            返り値: dictは三純信号/監視と人工執行材料。
            """
            session = entry["session"]
            block = driver.I.generate(shared["numeric"][session],shared["higher"][session],session,90000.,95000.,current)
            block["signals"] = {sid:[driver.I.pure_signal(row,sid[3:]) for row in values] for sid,values in block["signals"].items()}
            events = []
            if include_events and shared["numeric"][session]:
                prices = [100.,100.,125.,105.,105.] if session==sessions[0] else [100.,100.,75.,95.,95.]
                events = [SimpleNamespace(now=1081.+i,line=i+1,valid=True,bid=bid,ask=bid+5,last=bid+2.5) for i,bid in enumerate(prices)]
            block.update(input_quality=deepcopy(block["quality"]),events=events,cutoff=90000.,deadline=95000.,duration=100000./60)
            return block

        yield SimpleNamespace(folder=folder,study=study,work=work,config=config,bundle=bundle,build=build,ref=ref,
            manifest={"source_root":"人工予約だけ","entries":[{"session":s,"in_session_contract_codes":["人工限月"]} for s in sessions]})


class 主driver接続検証(unittest.TestCase):
    """新二尺度準備/七正式系列/純13と固定出典の接続を人工検査する。"""

    def test_CLI人工66準備は23keyと上位H3列だけ保存(self):
        """全登録/監視の準備に先着・運用・成績を混ぜない。

        引数: self(TestCase)は対象。
        返り値: None。実CLI引数から人工prepareまで通す。
        """
        driver = driver_module()
        with artificial_driver(driver) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",return_value=f.bundle), \
                patch.object(driver,"build_session",side_effect=f.build) as built,patch.object(driver,"freeze",side_effect=AssertionError("準備固定禁止")), \
                patch.object(driver.W.OLD,"気配経路",side_effect=AssertionError("準備先着禁止")), \
                patch.object(driver.ENGINE,"replay",side_effect=AssertionError("準備運用禁止")), \
                patch.object(driver.E,"entry_metrics",side_effect=AssertionError("準備先着成績禁止")), \
                patch.object(driver.S,"operation_metrics",side_effect=AssertionError("準備損益禁止")), \
                patch.object(sys,"argv",["人工.py","--study",str(f.study),"--work",str(f.work),"--prepare"]),redirect_stdout(io.StringIO()):
            driver.main(); proof = driver.W.read_json(f.work/"準備点検.json")
            self.assertFalse(proof["ラベル計算"]); self.assertFalse(proof["損益計算"])
            self.assertEqual(len(proof["準備"]),66); self.assertEqual(built.call_count,66)
            self.assertTrue(all(len(row)==23 for row in proof["準備"]))
            self.assertTrue(all(call.args[-1] is False for call in built.call_args_list))
            definition = proof["上位数値定義"]
            self.assertEqual(set(definition),{"パス","圧縮SHA256参考","展開内容SHA256","行数"})
            with gzip.open(ROOT/definition["パス"],"rt",encoding="utf-8") as stream:rows = [json.loads(line) for line in stream]
            self.assertEqual(len(rows),5); self.assertTrue(all(set(row)=={"場","index","macd_hist"} for row in rows))
            self.assertEqual(definition["展開内容SHA256"],driver.content_sha(ROOT/definition["パス"]))
            self.assertEqual(sum(row["登録候補数"] for row in proof["準備"]),5)
            self.assertEqual(sum(row["監視足数"] for row in proof["準備"]),12)
            self.assertFalse(any((f.work/name).exists() for name in driver.FILES))
            with self.assertRaises(ValueError):driver.run(f.study,f.work,True)

    def test_準備既存blob結果七系列と正式partialを入力前拒否(self):
        """中間物を消して黙って再準備せず、各存在を早期拒否する。

        引数: self(TestCase)は対象。
        返り値: None。原入力/共有束は読まない。
        """
        driver = driver_module()
        with artificial_driver(driver,1) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",side_effect=AssertionError("既存物後は入力禁止")):
            for path in [f.work/"準備点検.json",f.work/"上位数値定義.jsonl.gz",f.study/"結果.json",*[f.work/n for n in driver.FILES]]:
                path.write_bytes(b"artificial")
                with self.assertRaises(ValueError):driver.run(f.study,f.work,True)
                if path.name in driver.FILES:
                    with self.assertRaises(ValueError):driver.run(f.study,f.work,False)
                path.unlink()

    def test_人工正式七gzip全四役割とT_R_S純和集合(self):
        """二場のT/Rを三運用へ渡し全保存と末尾集計を接続する。

        引数: self(TestCase)は対象。
        返り値: None。純13以外をXFへ渡さず、旧label/controlを作らない。
        """
        driver = driver_module()
        with artificial_driver(driver,2) as f:
            replay = driver.ENGINE.replay
            label = dict(zip(driver.C.LABEL_FIELDS,["順行先着","人工直接先着",105.,1082.,2,7000.,9,355.,250.,10.,11.]))

            def operation(*args):
                """純列を確認して人工範囲の実XFへ渡す。

                引数: args(tuple)は主運用引数。
                返り値: tupleは人工状態/品質。
                """
                self.assertTrue(all(set(row)==set(I.SIGNAL_FIELDS) for row in args[1]))
                return replay(*args,bounds=(0.,100000.,90000.,95000.))

            def publish(study,path,ids,manifest,suffix):
                """外部Viewer処理を人工一覧へ置換する。

                引数: study/path(Path),ids(list),manifest(dict),suffix(str)は主契約。
                返り値: None。市場やViewerを起動しない。
                """
                driver.W.write_json(study/"一覧.resources.json",{"resources":[{"id":"00008_人工"}]})

            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                    patch.object(driver,"read_bundle",return_value=f.bundle),patch.object(driver,"build_session",side_effect=f.build), \
                    patch.object(driver,"freeze",return_value={}),patch.object(driver.ENGINE,"replay",side_effect=operation) as operated, \
                    patch.object(driver.W.OLD,"気配経路",return_value=SimpleNamespace(evaluate=lambda *a,**k:deepcopy(label))), \
                    patch.object(driver.E,"publish_details",side_effect=publish),redirect_stdout(io.StringIO()):
                driver.run(f.study,f.work,False)
            result = driver.W.read_json(f.study/"結果.json")
            self.assertEqual(result["実役割群数"],4); self.assertEqual(len(result["役割別入口評価"]),4)
            self.assertEqual(operated.call_count,6)
            self.assertEqual(len(driver.W.read_json(f.study/"作業成果物.json")["ファイル"]),7)
            with gzip.open(f.work/"入口事例.jsonl.gz","rt",encoding="utf-8") as stream:cases = [json.loads(line) for line in stream]
            self.assertEqual(len(cases),4)
            for row in cases:
                self.assertEqual({k:row[k] for k in driver.C.LABEL_FIELDS},label)
                self.assertTrue(set(I.METADATA_FIELDS)<=set(row)); self.assertNotIn("旧A0イベントID",row)
            self.assertEqual(Counter(row["役割"] for row in cases),{"順行":2,"反転":2})
            with gzip.open(f.work/"価格状態.jsonl.gz","rt",encoding="utf-8") as stream:prices = [json.loads(line) for line in stream]
            self.assertEqual(Counter(row["種別"] for row in prices),{"登録":5,"監視":12})
            with gzip.open(f.work/"全運用詳細.jsonl.gz","rt",encoding="utf-8") as stream:details = [json.loads(line) for line in stream]
            self.assertEqual(sum(len(row["取引"]) for row in details),4)
            self.assertEqual({row["取引"][0]["入口役割"] for row in details if row["取引"]},{"順行","反転"})
            independent = load(HERE/"追尾独立確認.py","Force47人工全追尾")
            with gzip.open(f.work/"追尾.jsonl.gz","rt",encoding="utf-8") as stream:logs = [json.loads(line) for line in stream]
            audit = independent.Y.Audit()
            for entry in f.manifest["entries"]:
                block = f.build(entry,f.manifest,f.bundle,f.config,True)
                quotes = [{k:getattr(event,k) for k in ("now","line","bid","ask")} for event in block["events"]]
                signals = {row["イベントID"]:row for values in block["signals"].values() for row in values}
                for detail in (row for row in details if row["場"]==entry["session"]):
                    alternate,_ = independent.replay(detail,quotes,signals,audit,bounds=(0.,100000.,95000.),config=f.config["運用"])
                    self.assertEqual(alternate,[row for row in logs if row["場"]==detail["場"] and row["候補ID"]==detail["候補ID"]])
            self.assertEqual(audit.mismatches,0)

    def test_共有二尺度と実buildの純13気配分離(self):
        """旧28SOURCEだけから新Hを作り、旧3分値はコピーする。

        引数: self(TestCase)は対象。
        返り値: None。実read_bundle/build_sessionを人工材料で接続する。
        """
        driver = driver_module()
        with artificial_driver(driver,2) as f:
            upper = [row for rows in f.bundle["upper_source"].values() for row in rows]
            times = tuple(SimpleNamespace(timestamp=lambda x=x:x) for x in (0.,2700.,90000.,95000.))
            with patch.object(driver.C,"read_bundle",return_value={"lower":f.bundle["lower"]}), \
                    patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_rows",return_value=upper), \
                    patch.object(driver,"shared_path",return_value=f.folder/"人工参照"),patch.object(driver,"manifest_for",return_value=f.manifest), \
                    patch.object(driver.W.OLD.shared.legacy,"session_times",return_value=times):
                bundle = driver.read_bundle(f.study)
            self.assertEqual(set(bundle),set(f.bundle)); self.assertEqual(bundle["lower"],f.bundle["lower"])
            self.assertTrue(all(set(row)==set(J.UPPER_FIELDS) for rows in bundle["higher"].values() for row in rows))
            entry = f.manifest["entries"][0]; source = f.folder/"人工source.bin"; cache = f.folder/"人工cache.bin"
            source.write_bytes(b"artificial"); cache.write_bytes(b"cache"); stat = source.stat()
            entry.update(source_path=source.name,cache_path=os.path.relpath(cache,ROOT/"work/複合検証"),source_size=stat.st_size,
                source_mtime_ns=stat.st_mtime_ns,sha256_cache=sha(cache))
            manifest = {**f.manifest,"source_root":str(f.folder)}
            with patch.object(driver.W.OLD.shared.legacy,"session_times",return_value=times), \
                    patch.object(driver.W.PREP,"read_events",side_effect=AssertionError("純準備気配禁止")):
                block = driver.build_session(entry,manifest,f.bundle,f.config,False)
            self.assertEqual(block["events"],[])
            self.assertTrue(all(set(row)==set(I.SIGNAL_FIELDS) for values in block["signals"].values() for row in values))
            self.assertEqual(len(block["metadata"]),1)
            entry["sha256_cache"] = "0"*64
            with self.assertRaises(ValueError):driver.build_session(entry,manifest,f.bundle,f.config,False)

    def test_条件と実行中版差を成功として保存しない(self):
        """入口機械や実行途中source差を結果前に拒否する。

        引数: self(TestCase)は対象。
        返り値: None。人工準備だけを実行する。
        """
        driver = driver_module()
        with artificial_driver(driver,1) as f:
            bad = deepcopy(f.config); bad["Force波"]["寿命"] = "結果後変更"
            with self.assertRaises(ValueError):driver.validate_config(bad)
            first = driver.current_bindings(f.study); changed = deepcopy(first); changed["上位参照SHA256"] = "0"*64
            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                    patch.object(driver,"read_bundle",return_value=f.bundle),patch.object(driver,"build_session",side_effect=f.build), \
                    patch.object(driver,"current_bindings",side_effect=[first,changed]),redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError):driver.run(f.study,f.work,True)
            self.assertFalse((f.work/"準備点検.json").exists())

    def test_S0同場でT完結後Rへ切替え現ATRを各fillで固定(self):
        """混合の役割とDを一建玉前の設定へ置換しない。

        引数: self(TestCase)は対象。
        返り値: None。同場の順行買い→反転売りを同じXFへ順に渡す。
        """
        driver = driver_module(); config = driver.expected_config()["運用"]
        a = generated(material())["decisions"][0]
        source = material("R")
        for row in source:
            for key in ("start","end","confirm"): row[key] += 20.
            row["atr"] = 20.1
        b = generated(source,higher(later=-1))["decisions"][0]
        signals = [I.pure_signal(a,"S0"),I.pure_signal(b,"S0")]
        events = [SimpleNamespace(now=t,line=i+1,valid=True,bid=bid,ask=bid+5,last=bid+2.5) for i,(t,bid) in enumerate([
            (1081.,100.),(1082.,100.),(1083.,125.),(1084.,105.),(1085.,105.),
            (1101.,100.),(1102.,100.),(1103.,70.),(1104.,95.),(1105.,95.)])]
        state,info = driver.ENGINE.replay(events,signals,[],SESSION,"3分_S0_XF",config,{"出口ID":"XF"},"切替",bounds=(0.,100000.,90000.,95000.))
        self.assertEqual(len(state.trades),2)
        self.assertEqual([row["入口役割"] for row in state.trades],["順行","反転"])
        self.assertEqual([row["入口ATR"] for row in state.trades],[10.1,20.1])
        self.assertEqual([row["追尾距離pt"] for row in state.trades],[15,25])
        self.assertEqual(info["終了建玉"],0)


# ----------------------------------------
# 小型正本定義のreaderとCLIは実上位ファイルを開かず人工3列だけで検査する。

class 独立保存接続検証(unittest.TestCase):
    """新H正本の内容構造と入力前版guardを接続する。"""

    def test_ATR_Hだけ非改変overlayし方向採否とForce_Qをstrict(self):
        """生値の限定許容を価格・数量・精密分数・方向の救済へ広げない。

        引数: self(TestCase)は対象。
        返り値: None。正本定義SHAと生値比較の二経路を人工接続する。
        """
        independent = load(HERE/"状態独立確認.py","Force47人工二経路")
        if not all(hasattr(independent,k) for k in ("define_lower","define_upper","compare_numeric_scope")):
            self.skipTest("独立overlay二経路完成前")
        shared = material(); raw = deepcopy(shared); raw[-1]["atr"] = math.nextafter(raw[-1]["atr"],math.inf)
        kept = deepcopy(raw); defined = independent.define_lower(raw,shared)
        self.assertEqual(raw,kept); self.assertEqual(defined,shared)
        upper = higher(); source = deepcopy(upper)
        source[0]["macd_hist"] = -1e-16; source[-1]["macd_hist"] = math.nextafter(source[-1]["macd_hist"],math.inf)
        retained = deepcopy(source)
        definition = {row["index"]:{k:row[k] for k in ("場","index","macd_hist")} for row in upper}
        canonical = independent.define_upper(source,definition)
        self.assertEqual(source,retained); self.assertEqual(canonical,upper)
        self.assertNotEqual(J.canonical_sha(source),J.canonical_sha(canonical))
        main_rows,_ = J.build(defined,SESSION); live_rows,_ = independent.build_local(raw,SESSION)
        normal = I.generate(main_rows,canonical,SESSION,100000.,200000.,CONFIG)
        live = independent.generate(live_rows,source,SESSION,100000.,200000.,CONFIG)
        audit = independent.Audit(); self.assertTrue(independent.compare_numeric_scope("生値と正本",normal,live,audit))
        self.assertEqual(audit.mismatches,0)
        for kind in ("missing","duplicate","session"):
            low,high = deepcopy(raw),deepcopy(source)
            if kind=="missing": low.pop(); high.pop()
            elif kind=="duplicate": low.append(deepcopy(low[0])); high.append(deepcopy(high[0]))
            else: low[0]["場"] = "別場"; high[0]["場"] = "別場"
            with self.assertRaises(ValueError):independent.define_lower(low,shared)
            with self.assertRaises(ValueError):independent.define_upper(high,definition)
        for field,value in (("close",105.),("confirm",2000.),("数量参照",{"数量基準完全":True,"観測差分量":4.})):
            modified = deepcopy(raw); modified[-1][field] = value
            result = independent.define_lower(modified,shared)
            self.assertEqual(result[-1][field],value)
            audit = independent.Audit(); self.assertFalse(independent.compare_numeric_scope("非許容出典",defined,result,audit))
            self.assertGreater(audit.mismatches,0)
        for left,right in (({"atr":10.},{"atr":math.nextafter(10.,math.inf)}),
                ({"上位ヒスト差":-1e-16},{"上位ヒスト差":1e-16}),
                ({"Force2":J.exact(Fraction(1))},{"Force2":J.exact(Fraction(1)+Fraction(1,10**30))})):
            audit = independent.Audit(); self.assertFalse(independent.compare_numeric_scope("判断境界",left,right,audit))
            self.assertGreater(audit.mismatches,0)
        audit = independent.Audit(); independent.compare_numeric_scope("H許容超過",{"macd_hist":1.},{"macd_hist":1.000001},audit)
        self.assertGreater(audit.mismatches,0)

    def test_三列H実readerの指紋全行構造一意順序を検査(self):
        """正本3列を任意の数値や未来属性の救済に使わない。

        引数: self(TestCase)は対象。
        返り値: None。人工2行のgzipだけを実読取する。
        """
        independent = load(HERE/"状態独立確認.py","Force47人工H定義読取")
        driver = driver_module()
        with tempfile.TemporaryDirectory(prefix="Force47合成_",dir=ROOT/"work") as temporary:
            work = Path(temporary); path = work/"上位数値定義.jsonl.gz"
            rows = [{"場":SESSION,"index":0,"macd_hist":None},{"場":SESSION,"index":1,"macd_hist":-1e-16}]

            def saved(values):
                """人工3列を保存して主準備相当metadataを作る。

                引数: values(list[dict])は人工H定義行。
                返り値: dictは4metadataと当場全足数。
                """
                with driver.compressed(path) as stream:
                    for row in values: stream.write(driver.D.encode(row))
                return {"上位数値定義":{"パス":path.relative_to(ROOT).as_posix(),"圧縮SHA256参考":sha(path),
                    "展開内容SHA256":driver.content_sha(path),"行数":len(values)},"準備":[{"場":SESSION,"上位足数":2}]}

            master = saved(rows)
            self.assertEqual(independent.read_definition(work,master,independent.Audit()),{SESSION:{row["index"]:row for row in rows}})
            for key in master["上位数値定義"]:
                changed = deepcopy(master); changed["上位数値定義"][key] = -1 if key=="行数" else "不一致"
                with self.assertRaises(ValueError):independent.read_definition(work,changed,independent.Audit())
            changed = deepcopy(master); changed["上位数値定義"]["余分"] = True
            with self.assertRaises(ValueError):independent.read_definition(work,changed,independent.Audit())
            for kind in ("extra","duplicate","reverse","session","count","invalid","boolindex"):
                changed = deepcopy(rows)
                if kind=="extra": changed[0]["未来label"] = "毒値"
                elif kind=="duplicate": changed[-1]["index"] = 0
                elif kind=="reverse": changed.reverse()
                elif kind=="session": changed[0]["場"] = "別場"
                elif kind=="count": changed.pop()
                elif kind=="invalid": changed[0]["macd_hist"] = "非数値"
                else: changed[0]["index"] = True
                with self.assertRaises(ValueError):independent.read_definition(work,saved(changed),independent.Audit())

    def test_独立CLIは無指定と不正masterを入力前停止(self):
        """明示モードと現在版の主準備がなければ原入力へ進まない。

        引数: self(TestCase)は対象。
        返り値: None。人工JSON以外の市場資料は拒否する。
        """
        independent = load(HERE/"状態独立確認.py","Force47人工CLI独立")
        trail = load(HERE/"追尾独立確認.py","Force47人工CLI追尾")
        for module in (independent,trail):
            with patch.object(sys,"argv",["人工.py"]),patch.object(module,"run",create=True,side_effect=AssertionError("無指定実行禁止")), \
                    redirect_stdout(io.StringIO()),patch.object(sys,"stderr",io.StringIO()):
                with self.assertRaises(SystemExit) as caught:module.main()
                self.assertEqual(caught.exception.code,2)
        driver = driver_module()
        with artificial_driver(driver,1) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",return_value=f.bundle), \
                patch.object(driver,"build_session",side_effect=f.build),redirect_stdout(io.StringIO()):
            driver.run(f.study,f.work,True)
            master = driver.W.read_json(f.work/"準備点検.json")
            resolved = f.study/"入力台帳.json"; master["参照台帳SHA256"] = sha(resolved)
            driver.W.write_json(f.work/"準備点検.json",master)
            with patch.object(independent,"references",create=True,return_value=None), \
                    patch.object(independent.G,"resolved_manifest",return_value=(f.manifest,resolved)), \
                    patch.object(independent,"shared_bundle",create=True,side_effect=AssertionError("不正準備後は共有入力禁止")), \
                    patch.object(independent.G,"observed",side_effect=AssertionError("不正準備後は原入力禁止")):
                _,manifest,checked,_ = independent.guarded_inputs(f.study,f.work,independent.Audit())
                self.assertEqual(manifest,f.manifest); self.assertEqual(checked,master)
                for key in ("条件SHA256","コードSHA256","上位参照SHA256","ラベル計算"):
                    changed = deepcopy(master); changed[key] = True if key=="ラベル計算" else {} if key=="コードSHA256" else "0"*64
                    driver.W.write_json(f.work/"準備点検.json",changed)
                    with patch.object(sys,"argv",["人工.py","--prepare","--study",str(f.study),"--work",str(f.work)]):
                        with self.assertRaises(ValueError):independent.main()


class 固定証明接続検証(unittest.TestCase):
    """新H定義と全証明の必須結合を人工だけで検査する。"""

    def test_固定は新H定義と主独立最終合成会計8経路をjoin(self):
        """不足証明/異版/旧固定変化を拒否してから人工固定を保存する。

        引数: self(TestCase)は対象。
        返り値: None。旧モデル数式と既存固定ファイルを変更しない。
        """
        required=[HERE/"状態独立確認.py",HERE/"追尾独立確認.py",HERE/"独立監査.py",ROOT/"work/Force波/00047/会計人工接続.py"]
        if not all(path.exists() for path in required):self.skipTest("独立二CLI/会計人工source完成前")
        driver=driver_module()
        with artificial_driver(driver,1) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",return_value=f.bundle), \
                patch.object(driver,"build_session",side_effect=f.build),redirect_stdout(io.StringIO()):
            driver.run(f.study,f.work,True)
            prepared=driver.W.read_json(f.work/"準備点検.json")
            dependency=HERE/"指標.py"
            finance_sources=("scripts/Force波/独立監査.py","scripts/Force波/運用.py","work/Force波/00047/会計人工接続.py")
            finance={"全件一致":True,"不一致数":0,"人工経路数":8,"実行中code不変":True,
                "条件SHA256":sha(f.study/"条件.json"),"コードSHA256":{name:sha(ROOT/name) for name in finance_sources}}
            driver.W.write_json(f.work/"会計人工接続.json",finance)
            (f.work/"会計人工接続.py").write_bytes((ROOT/finance_sources[-1]).read_bytes())
            proof={"全件一致":True,"不一致数":0,"不一致":[],"ラベル計算":False,"損益計算":False,
                "主準備SHA256":sha(f.work/"準備点検.json"),"主コードSHA256":driver.code_pins(),
                "条件SHA256":sha(f.study/"条件.json"),"入力台帳SHA256":sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256":sha(driver.MANIFEST_PATH),"指標参照SHA256":sha(f.study/"指標参照.json"),
                "コードSHA256":sha(required[0]),"追尾コードSHA256":sha(required[1]),
                "依存コードSHA256":{dependency.relative_to(ROOT).as_posix():sha(dependency)},
                "上位参照SHA256":sha(f.study/"上位参照.json"),"上位数値定義":prepared["上位数値定義"]}
            synthetic={"全件成功":True,"合成編集終了":False,"実行中code不変":True,
                "ファイルSHA256":{p.relative_to(ROOT).as_posix():sha(p) for p in [HERE/n for n in ("検証.py","入口.py","指標.py","運用.py","合成検証.py")]+[f.study/"条件.json"]},
                "独立数値補助SHA256":sha(required[0]),"独立追尾補助SHA256":sha(required[1])}
            synthetic_file=f.work/"人工最終合成.json";driver.W.write_json(synthetic_file,synthetic)
            actual_read,actual_sha=driver.W.read_json,driver.O.sha

            def read_json(path):
                """旧固定集合と最終合成の参照先だけを人工へ写す。

                引数: path(Path)は小証明先。
                返り値: dictは人工宣言又は元の現在資料。
                """
                if normalized(path)==normalized(driver.PREVIOUS/"固定.json"):
                    return {"ファイルSHA256":{dependency.relative_to(ROOT).as_posix():sha(dependency)}}
                return deepcopy(synthetic) if normalized(path)==normalized(WORK/"合成検証.json") else actual_read(path)

            def current_sha(path):
                """最終人工proofへの指紋だけを一時先へ写す。

                引数: path(Path)は対象。
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
                for key in ("全件一致","不一致数","人工経路数","実行中code不変","条件SHA256","コードSHA256"):
                    changed=deepcopy(finance);changed[key]=False if isinstance(finance[key],bool) else {} if isinstance(finance[key],dict) else "不一致"
                    driver.W.write_json(f.work/"会計人工接続.json",changed)
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                for source in finance_sources:
                    changed=deepcopy(finance);changed["コードSHA256"].pop(source);driver.W.write_json(f.work/"会計人工接続.json",changed)
                    with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                driver.W.write_json(f.work/"会計人工接続.json",finance);driver.W.write_json(synthetic_file,synthetic)
                locked=driver.freeze(f.study,f.work)
                self.assertEqual(driver.freeze(f.study,f.work),locked)
                relative=(f.work/"上位数値定義.jsonl.gz").relative_to(ROOT).as_posix()
                self.assertEqual(locked["ファイルSHA256"][relative],sha(f.work/"上位数値定義.jsonl.gz"))
                (f.study/"計画.md").write_text("固定後変更",encoding="utf-8")
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                driver.W.write_json(f.study/"結果.json",{})
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)


def main() -> None:
    """開発人工だけを実行し、最終proofはrootが停止版へ一度起動する。

    引数: CLI --final(bool)はroot管理の最終指定。
    返り値: None。市場の準備/先着/運用を起動しない。
    """
    parser = argparse.ArgumentParser(description="Force波の順序と精密数値の人工検査")
    parser.add_argument("--final",action="store_true"); args = parser.parse_args()
    paths = [HERE/name for name in ("検証.py","入口.py","指標.py","運用.py","合成検証.py")]
    paths += [ROOT/"study/00047_上位方向とForce波からの価格発動/条件.json"]
    paths = [p for p in paths if p.exists()]
    helpers = [p for p in (HERE/"状態独立確認.py",HERE/"追尾独立確認.py") if p.exists()]
    pins = {p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    before = {p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    with deny_market(): result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged = pins=={p.relative_to(ROOT).as_posix():sha(p) for p in paths} and before=={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    success = result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    if args.final and (len(pins)!=6 or len(before)!=2): raise ValueError("主4code/条件/合成と独立二code完成前")
    proof = {"全件成功":success,"検証件数":result.testsRun,"合成編集終了":bool(args.final and success),"実行中code不変":unchanged,
        "市場入力読取":False,"市場先着損益計算":False,"ファイルSHA256":pins,
        "独立数値補助SHA256":before.get("scripts/Force波/状態独立確認.py"),"独立追尾補助SHA256":before.get("scripts/Force波/追尾独立確認.py"),
        "skip数":len(result.skipped),"失敗数":len(result.failures),"エラー数":len(result.errors)}
    WORK.mkdir(parents=True,exist_ok=True); target = WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"出力":str(target),"全件成功":success,"件数":result.testsRun,"SHA256":sha(target)},ensure_ascii=False))
    if not success: raise SystemExit(1)


if __name__=="__main__": main()
