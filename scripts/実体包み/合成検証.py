"""市場を遮断し二実体・過去平均・勢い・役割の境界を人工検査する。"""

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

ROOT=Path(__file__).resolve().parents[2]
HERE,WORK=Path(__file__).resolve().parent,ROOT/"work/実体包み"
SESSION="人工実体包み場"
CONFIG={"残り時間下限分":60,"確認遅延上限秒":30}


def normalized(path: object) -> str:
    """市場遮断用の絶対パスを得る。

    引数: path(object)はパス又は非パス値。
    返り値: strは正規パス、非パスなら空文字。
    """
    try:return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError,ValueError):return ""


@contextmanager
def deny_market():
    """原板・実cache・実圧縮明細のopen/statを拒否する。

    引数: なし。
    返り値: contextmanagerは人工一時先とコード/小型証明だけを許可する。
    """
    raw,work=normalized(ROOT.parent/"JP_OSE_Data"),normalized(ROOT/"work")
    opened,path_opened,stated=builtins.open,Path.open,Path.stat

    def check(path):
        """実市場パスを拒否する。

        引数: path(object)はアクセス先。
        返り値: None。人工prefixだけを例外にする。
        """
        name=normalized(path);inside=name.startswith(work+os.sep)
        artificial=inside and os.path.relpath(name,work).split(os.sep)[0].startswith(os.path.normcase("実体46合成_"))
        if name==raw or name.startswith(raw+os.sep) or inside and not artificial and name.endswith((".npz",".jsonl.gz",".trades.jsonl")):
            raise AssertionError("人工から実市場資料を読まない:"+str(path))

    def safe_open(path,*args,**kwargs):
        """通常openへ遮断を適用する。

        引数: pathとargs/kwargsは元open引数。
        返り値: objectは許可されたファイル。
        """
        check(path);return opened(path,*args,**kwargs)

    def safe_path_open(path,*args,**kwargs):
        """Path.openへ遮断を適用する。

        引数: pathとargs/kwargsは元open引数。
        返り値: objectは許可されたファイル。
        """
        check(path);return path_opened(path,*args,**kwargs)

    def safe_stat(path,*args,**kwargs):
        """Path.statへ遮断を適用する。

        引数: pathとargs/kwargsは元stat引数。
        返り値: objectは許可されたstat。
        """
        check(path);return stated(path,*args,**kwargs)

    with patch.object(builtins,"open",safe_open),patch.object(Path,"open",safe_path_open),patch.object(Path,"stat",safe_stat):yield


def load(path: Path,name: str):
    """CLI起動なしでコード定義を読む。

    引数: path(Path)はコード、name(str)は識別。
    返り値: moduleは定義。
    """
    with deny_market():
        spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
        sys.modules[name]=value;spec.loader.exec_module(value);return value


def sha(path: Path) -> str:
    """小型証明とコードの指紋を得る。

    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


J,I=load(HERE/"指標.py","実体46人工数値"),load(HERE/"入口.py","実体46人工入口")


def frame(index: int,close: float,open: float | None=None,high: float | None=None,low: float | None=None,session: str=SESSION,**changes) -> dict:
    """有限正で公開済みの人工3分足を作る。

    引数: index(int)は番号、close/open/high/low(float|None)はOHLC、session(str)は場、changesは置換。
    返り値: dictは共有15列を含む人工足。
    """
    opening=close if open is None else open
    row={"場":session,"index":index,"minutes":3,"start":index*180.,"end":(index+1)*180.,
        "confirm":(index+1)*180.+1.,"confirm_line":index+1,"publish":True,"missing":0,
        "open":opening,"high":max(opening,close)+1 if high is None else high,
        "low":min(opening,close)-1 if low is None else low,"close":close,"atr":10.1,"macd_hist":0.}
    row.update(changes);return row


def material(kind: str="T") -> list[dict]:
    """SMA位置/進行の四分類を持つ一つの買い二足Pを作る。

    引数: kind(str)はT/R/WAIT/zero/position0/short。
    返り値: list[dict]は人工価格。Hは当時の勢いの明示人工値。
    """
    prices={"T":[100.+i for i in range(21)],"R":[140.-i for i in range(21)],
        "WAIT":[100.]+[140.]*19+[120.],"zero":[120.]*21,
        "position0":[100.]+[122.]*18+[124.,120.],"short":[120.]}[kind]
    rows=[frame(i,value) for i,value in enumerate(prices)]
    rows[-1]=frame(len(rows)-1,120.,open=121.)
    rows.append(frame(len(rows),122.,open=120.,macd_hist=1.))
    return rows


def reflected(rows: list[dict],axis: float=500.) -> list[dict]:
    """価格と中心化Hを同時反射する。

    引数: rows(list[dict])は人工足、axis(float)は反射定数。
    返り値: list[dict]は高安交換/実体とH符号を反転した足。
    """
    return [{**deepcopy(row),"open":axis-row["open"],"high":axis-row["low"],
        "low":axis-row["high"],"close":axis-row["close"],
        "macd_hist":-row["macd_hist"] if J.finite(row["macd_hist"]) else None} for row in rows]


def generated(source: list[dict],cutoff: float=100000.,deadline: float=200000.) -> dict:
    """人工だけを平均と三候補へ渡す。

    引数: source(list[dict])は人工共有15列、cutoff/deadline(float)は人工時刻。
    返り値: dictは新全P/全採否。
    """
    rows,_=J.build(source,SESSION)
    return I.generate(rows,SESSION,cutoff,deadline,CONFIG)


class 二実体と勢い検証(unittest.TestCase):
    """実体区間とヒゲ/値幅/単なる終値変化を分ける。"""

    def test_始値等号可と終値strictとヒゲ不要(self):
        """旧P12や高安全包みの閾値を追加しない。

        引数: self(TestCase)は対象。
        返り値: None。鏡像/ドジ/一ULP境界を確認する。
        """
        p=frame(0,100.,open=110.,high=120.,low=90.)
        j=frame(1,111.,open=100.,high=115.,low=95.,macd_hist=1.)
        self.assertTrue(I.body_envelop(p,j,1))
        self.assertGreater(p["high"],j["high"]);self.assertLess(p["low"],j["low"])
        self.assertTrue(I.body_envelop(*reflected([p,j]),-1))
        for field,value in (("close",110.),("open",math.nextafter(100.,math.inf))):
            bad=deepcopy(j);bad[field]=value;self.assertFalse(I.body_envelop(p,bad,1))
        tiny=deepcopy(j);tiny["close"]=math.nextafter(110.,math.inf)
        self.assertTrue(I.body_envelop(p,tiny,1))
        doji=deepcopy(p);doji["open"]=doji["close"]
        self.assertFalse(I.body_envelop(doji,j,1))

    def test_実MACDの履歴からPでもH差逆方向を作れる(self):
        """価格反転とH一足差を独立な票や論理必然にしない。

        引数: self(TestCase)は対象。
        返り値: None。固定29の人工数値計算だけを使い、市場は読まない。
        """
        source=[frame(i,100.+2*i,open=99.+2*i) for i in range(60)]
        source += [frame(60,218.,open=219.,high=220.,low=217.),frame(61,220.,open=218.,high=221.,low=217.)]
        values,_=J.BASE.NumericBank().build(source,SESSION,("人工限月",),quantities=None)
        block=generated(values);row=next(r for r in block["decisions"] if r["index"]==61)
        self.assertEqual(row["side"],1)
        self.assertGreater(row["close"],row["前3分参照"]["close"])
        self.assertLess(row["MACDヒスト変化"],0.)
        self.assertFalse(row["戦略判定"]["B0"]["採用"])

    def test_公開時点はjend前のp公開を追加要求しない(self):
        """45の水準cross時点制限を二足Pへ持ち込まない。

        引数: self(TestCase)は対象。
        返り値: None。p.confirm=j.endでもj公開時に両足が既知なら採用する。
        """
        source=material();source[-2]["confirm"]=source[-1]["end"]
        row=generated(source)["decisions"][-1]
        self.assertEqual(row["前3分参照"]["confirm"],row["end"])
        self.assertTrue(row["戦略判定"]["B2"]["採用"])
        source[-1]["confirm"]=source[-2]["confirm"];source[-1]["confirm_line"]=source[-2]["confirm_line"]
        with self.assertRaises(ValueError):generated(source)

    def test_原Pを準備時間技術で消さず取り直さない(self):
        """H/ATR/時間不成立でも新二足Pを保存する。

        引数: self(TestCase)は対象。
        返り値: None。将来の良い時計へ同じPを移さない。
        """
        for kind in ("hist","atr","time"):
            source=material()
            if kind=="hist":source[-1]["macd_hist"]=None
            if kind=="atr":source[-1]["atr"]=None
            result=generated(source,cutoff=0. if kind=="time" else 100000.)
            self.assertEqual(len(result["decisions"]),1)
            self.assertFalse(any(result["signals"].values()))


class 平均と役割検証(unittest.TestCase):
    """平均の準備、位置/進行、実sideと役割名を分離する。"""

    def test_SMA20二窓は21過去足でjを除く(self):
        """j20の単独平均とj21の共通準備を区別する。

        引数: self(TestCase)は対象。
        返り値: None。1..21の過去Cでは前11.5/前々10.5を得る。
        """
        source=[frame(i,100.+i) for i in range(23)]
        rows,_=J.build(source,SESSION)
        self.assertFalse(rows[19]["SMA前"]["有効"])
        self.assertTrue(rows[20]["SMA前"]["有効"]);self.assertFalse(rows[20]["SMA準備"])
        self.assertEqual(rows[21]["SMA前"],J.exact(Fraction(221,2)))
        self.assertEqual(rows[21]["SMA前々"],J.exact(Fraction(219,2)))
        self.assertEqual(rows[21]["SMA進行"],J.exact(Fraction(1)))
        self.assertEqual(rows[21]["SMA前20足番号"],list(range(1,21)))
        self.assertEqual(rows[21]["SMA前々20足番号"],list(range(20)))
        changed=deepcopy(source);changed[21]["close"]=1000.;changed[21]["open"]=1000.;changed[21]["high"]=1001.;changed[21]["low"]=999.
        other,_=J.build(changed,SESSION)
        self.assertEqual(rows[21]["SMA前"],other[21]["SMA前"])
        self.assertNotEqual(rows[21]["終値対前SMA"],other[21]["終値対前SMA"])

    def test_準備未了をB0へ課さずB1は値0も準備可(self):
        """準備による除外とB2の等号WAITを別段階にする。

        引数: self(TestCase)は対象。
        返り値: None。B0/B1の実役割は反転固定。
        """
        short=generated(material("short"))["decisions"][-1]
        self.assertEqual([short["戦略判定"][p]["採用"] for p in I.POLICIES],[True,False,False])
        self.assertEqual(short["B2判別種別"],"未準備")
        zero=generated(material("zero"))["decisions"][-1]
        self.assertEqual([zero["戦略判定"][p]["採用"] for p in I.POLICIES],[True,True,False])
        self.assertEqual(zero["SMA進行符号"],0)
        position=generated(material("position0"))["decisions"][-1]
        self.assertEqual(position["SMA位置符号"],0);self.assertEqual(position["B2判別種別"],"WAIT")

    def test_B2は位置進行を分類してside維持とactive4群(self):
        """共通入口で役割だけ変わるTを別売買にしない。

        引数: self(TestCase)は対象。
        返り値: None。T/R/混在と両方向鏡像を確認する。
        """
        self.assertEqual(sum(map(len,I.ACTIVE_ROLES.values())),4)
        for kind,branch,role in (("T","T","順行"),("R","R","反転"),("WAIT","WAIT",None)):
            normal=generated(material(kind));mirror=generated(reflected(material(kind)))
            a,b=normal["decisions"][-1],mirror["decisions"][-1]
            self.assertEqual((a["B2判別種別"],a["B2役割"]),(branch,role))
            self.assertEqual(a["B2判別種別"],b["B2判別種別"]);self.assertEqual(a["side"],-b["side"])
            self.assertEqual([a["戦略判定"][p]["採用"] for p in I.POLICIES],[b["戦略判定"][p]["採用"] for p in I.POLICIES])
            if role is not None:
                first=I.pure_signal(a,"B1");second=I.pure_signal(a,"B2")
                self.assertEqual(first["side"],second["side"])
                self.assertEqual(first["役割"],"反転");self.assertEqual(second["役割"],role)

    def test_missing当足不投入と番号gap新seedを区別(self):
        """二足/SMAを不完全観測へ跨がせず、数量は使わない。

        引数: self(TestCase)は対象。
        返り値: None。旧29数値銀行の内部処理とは分離する。
        """
        for field,value in (("publish",False),("missing",1)):
            source=material();source[-2][field]=value
            rows,_=J.build(source,SESSION)
            self.assertEqual(rows[-2]["SMA過去足数"],0);self.assertEqual(rows[-1]["SMA過去足数"],0)
            self.assertFalse(generated(source)["decisions"])
        source=material();source.pop(19)
        rows,_=J.build(source,SESSION)
        self.assertEqual(rows[-2]["SMA過去足数"],0);self.assertEqual(rows[-1]["SMA過去足数"],1)
        self.assertTrue(generated(source)["decisions"])

    def test_prefix共有値コピー純13とsnapshot(self):
        """後の足・labelを当時判断や実運用へ漏らさない。

        引数: self(TestCase)は対象。
        返り値: None。平均/SMA分類metadataはpureへ渡さない。
        """
        source=material();values,_=J.build(source,SESSION)
        self.assertEqual([J.frame_projection(row) for row in values],source)
        result=generated(source);extended=generated(source+[frame(22,119.),frame(23,123.,open=119.,macd_hist=2.)])
        self.assertEqual(result["decisions"],[r for r in extended["decisions"] if r["index"]<22])
        record=result["decisions"][-1]
        for policy in I.POLICIES:
            own=result["signals"]["3分_"+policy][-1];own["未来label"]="毒値"
            pure=I.pure_signal(own,policy)
            self.assertEqual(set(pure),set(I.SIGNAL_FIELDS))
            self.assertNotIn("B2役割",pure)
        result["signals"]["3分_B2"][-1]["戦略判定"]["B0"]["採用"]=False
        self.assertTrue(record["戦略判定"]["B0"]["採用"])

    def test_独立窓和と二実体列挙の全dictが一致(self):
        """主の局所dequeとは別のslice和と二実体包含へ全列を照合する。

        引数: self(TestCase)は対象。
        返り値: None。実入力を読まずT/R/WAIT/準備と欠測・鏡像を確認する。
        """
        path=HERE/"状態独立確認.py"
        if not path.exists():self.skipTest("独立核完成前")
        independent=load(path,"実体46人工独立核")
        if not all(hasattr(independent,k) for k in ("build_local","generate")):self.skipTest("独立全核完成前")
        scenarios=[material(kind) for kind in ("T","R","WAIT","zero","position0","short")]
        for field,value in (("publish",False),("missing",1)):
            source=material();source[-2][field]=value;scenarios.append(source)
        source=material();source.pop(19);scenarios.append(source)
        source=material();source[-2]["confirm"]=source[-1]["end"];scenarios.append(source)
        for source in [*scenarios,*[reflected(rows) for rows in scenarios]]:
            rows,quality=J.build(source,SESSION)
            alternate,other_quality=independent.build_local(source,SESSION)
            self.assertEqual(rows,alternate);self.assertEqual(quality,other_quality)
            actual=I.generate(rows,SESSION,100000.,200000.,CONFIG)
            expected=independent.generate(alternate,SESSION,100000.,200000.,CONFIG)
            self.assertEqual(actual,expected)


# ----------------------------------------
# 主CLIは人工66場だけで接続し、正式市場ファイルは一切開かない。

def driver_module():
    """市場起動なしで現主driverを読む。

    引数: なし。
    返り値: moduleは現主の定義。
    """
    return load(HERE/"検証.py","実体46人工主")


@contextmanager
def artificial_driver(driver, count: int=66):
    """新二足母集団の人工場と隔離した保存先を作る。

    引数: driver(module)は主、count(int)は人工場数。
    返り値: contextmanagerは人工束/実Iを通すbuild/保存先。
    """
    with tempfile.TemporaryDirectory(prefix="実体46合成_",dir=ROOT/"work") as temporary:
        folder=Path(temporary);study,work=folder/"study",folder/"work";study.mkdir();work.mkdir()
        config=driver.expected_config();driver.W.write_json(study/"条件.json",config)
        driver.W.write_json(study/"入力台帳.json",{"人工":True})
        ref={"文書と証明":{},"共有明細":[]};driver.W.write_json(study/"指標参照.json",ref)
        (study/"計画.md").write_text("人工の二足比較\n",encoding="utf-8")
        driver.W.write_json(work/"診断予定.json",{"人工":True})
        sessions=[str(date(2026,9,22)+timedelta(days=i//2))+("_Day" if i%2==0 else "_Night") for i in range(count)]
        bundle={"lower":{},"numeric":{},"numeric_quality":{}}
        for index,session in enumerate(sessions):
            source=[{**row,"場":session} for row in material()] if index==0 else []
            rows,quality=J.build(source,session)
            bundle["lower"][session]=source;bundle["numeric"][session]=rows;bundle["numeric_quality"][session]=quality

        def build(entry,manifest,shared,current,include_events=False):
            """実Iと純13を通し正式時だけ人工BBOを渡す。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式フラグ。
            返り値: dictは三案の場束。未来labelは含めない。
            """
            session=entry["session"]
            block=driver.I.generate(shared["numeric"][session],session,90000.,95000.,current)
            block["signals"]={sid:[driver.I.pure_signal(row,sid[3:]) for row in values] for sid,values in block["signals"].items()}
            events=[]
            if include_events and shared["numeric"][session]:
                events=[SimpleNamespace(now=t,line=i+1,valid=True,bid=bid,ask=bid+5,last=bid+2.5)
                        for i,(t,bid) in enumerate([(3961.,120.),(3962.,120.),(3963.,145.),(3964.,125.),(3965.,125.)])]
            block.update(input_quality=deepcopy(block["quality"]),events=events,cutoff=90000.,deadline=95000.,duration=100000./60)
            return block

        yield SimpleNamespace(folder=folder,study=study,work=work,config=config,bundle=bundle,build=build,
            manifest={"source_root":"人工予約だけ","entries":[{"session":s} for s in sessions]},ref=ref)


class 主driver接続検証(unittest.TestCase):
    """CLI・純準備・新先着・五系列・固定証明の境界を人工で接続する。"""

    def test_CLI66準備は14keyで先着運用を呼ばない(self):
        """CLIから純準備までを通し、旧label/数値blobを作らない。

        引数: self(TestCase)は対象。
        返り値: None。実入力/先着/運用/成績経路は明示拒否する。
        """
        driver=driver_module()
        with artificial_driver(driver) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",return_value=f.bundle), \
                patch.object(driver,"build_session",side_effect=f.build) as built, \
                patch.object(driver,"freeze",side_effect=AssertionError("準備で固定しない")), \
                patch.object(driver.W.OLD,"気配経路",side_effect=AssertionError("準備で先着を計算しない")), \
                patch.object(driver.ENGINE,"replay",side_effect=AssertionError("準備で運用しない")), \
                patch.object(driver.E,"entry_metrics",side_effect=AssertionError("準備で先着成績を計算しない")), \
                patch.object(driver.S,"operation_metrics",side_effect=AssertionError("準備で損益を集計しない")), \
                patch.object(sys,"argv",["人工.py","--study",str(f.study),"--work",str(f.work),"--prepare"]),redirect_stdout(io.StringIO()):
            driver.main();proof=driver.W.read_json(f.work/"準備点検.json")
            self.assertFalse(proof["ラベル計算"]);self.assertFalse(proof["損益計算"])
            self.assertEqual(len(proof["準備"]),66);self.assertEqual(built.call_count,66)
            self.assertTrue(all(call.args[-1] is False for call in built.call_args_list))
            fields={"場","期間","純信号","純信号内容SHA256","純信号判断SHA256","判定","判定SHA256","判定判断SHA256",
                "全3分投影SHA256","3分投影足数","入力品質","全指標内容SHA256","全指標足数","数値品質"}
            self.assertTrue(all(set(row)==fields for row in proof["準備"]))
            self.assertEqual(len(proof["準備"][0]["純信号"]),3)
            self.assertEqual(set(p.name for p in f.work.iterdir()),{"診断予定.json","準備点検.json"})
            with self.assertRaises(ValueError):driver.run(f.study,f.work,True)

    def test_準備と正式の既存成果物を入力前に拒否(self):
        """準備JSON/結果/五系列を上書きせず、部分正式も再起動しない。

        引数: self(TestCase)は対象。
        返り値: None。各既存物についてread_bundle到達前の拒否を確認する。
        """
        driver=driver_module()
        with artificial_driver(driver,1) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref), \
                patch.object(driver,"read_bundle",side_effect=AssertionError("既存物の後は共有束を読まない")):
            paths=[f.work/"準備点検.json",f.study/"結果.json",*[f.work/name for name in driver.FILES]]
            for path in paths:
                path.write_bytes(b"artificial")
                with self.assertRaises(ValueError):driver.run(f.study,f.work,True)
                if path.name in driver.FILES:
                    with self.assertRaises(ValueError):driver.run(f.study,f.work,False)
                path.unlink()

    def test_人工正式は三case五系列四実役割と同時役割差(self):
        """全三案へ当時純信号だけを渡し、旧labelを持ち込まない。

        引数: self(TestCase)は対象。
        返り値: None。人工XF約定と最後の会計/Viewer保存APIを接続する。
        """
        driver=driver_module()
        with artificial_driver(driver,1) as f:
            replay=driver.ENGINE.replay
            label=dict(zip(driver.C.LABEL_FIELDS,["順行先着","人工先着",125.,3962.,2,7000.,9,375.,250.,10.,11.]))

            def operation(*args):
                """純列を検査して人工範囲の実XFへ渡す。

                引数: args(tuple)は主運用引数。
                返り値: tupleは人工状態と品質。
                """
                self.assertTrue(all(set(row)==set(I.SIGNAL_FIELDS) for row in args[1]))
                return replay(*args,bounds=(0.,100000.,90000.,95000.))

            def publish(study,path,ids,manifest,suffix):
                """Viewer外部起動を人工一覧JSONへ置換する。

                引数: study/path(Path),ids(list),manifest(dict),suffix(str)は主契約。
                返り値: None。実資料は開かない。
                """
                driver.W.write_json(study/"一覧.resources.json",{"resources":[{"id":"00008_人工"}]})

            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                    patch.object(driver,"read_bundle",return_value=f.bundle),patch.object(driver,"build_session",side_effect=f.build), \
                    patch.object(driver,"freeze",return_value={}), \
                    patch.object(driver.W.OLD,"気配経路",return_value=SimpleNamespace(evaluate=lambda *a,**k:deepcopy(label))) as path, \
                    patch.object(driver.ENGINE,"replay",side_effect=operation) as operated, \
                    patch.object(driver.E,"publish_details",side_effect=publish),redirect_stdout(io.StringIO()):
                driver.run(f.study,f.work,False)
            result=driver.W.read_json(f.study/"結果.json")
            self.assertEqual(result["入口評価数"],3);self.assertEqual(result["実役割群数"],4)
            self.assertEqual(len(result["役割別入口評価"]),4);self.assertEqual(operated.call_count,3)
            self.assertEqual(len(driver.W.read_json(f.study/"作業成果物.json")["ファイル"]),5)
            with gzip.open(f.work/"入口事例.jsonl.gz","rt",encoding="utf-8") as stream:cases=[json.loads(line) for line in stream]
            self.assertEqual(len(cases),3)
            for row in cases:
                self.assertEqual({key:row[key] for key in driver.C.LABEL_FIELDS},label)
                self.assertTrue(set(I.METADATA_FIELDS)<=set(row));self.assertNotIn("旧A0イベントID",row)
            self.assertEqual([row["役割"] for row in cases],["反転","反転","順行"])
            self.assertEqual(len({(row["要求時計秒"],row["side"]) for row in cases}),1)
            with gzip.open(f.work/"全運用詳細.jsonl.gz","rt",encoding="utf-8") as stream:details=[json.loads(line) for line in stream]
            self.assertEqual(len(details),3);self.assertTrue(all(len(row["取引"])==1 for row in details))
            self.assertEqual([row["取引"][0]["入口役割"] for row in details],["反転","反転","順行"])
            self.assertEqual(len({row["取引"][0]["基準純損益円"] for row in details}),1)
            independent=load(HERE/"追尾独立確認.py","実体46人工全追尾")
            block=f.build(f.manifest["entries"][0],f.manifest,f.bundle,f.config,True)
            quotes=[{k:getattr(event,k) for k in ("now","line","bid","ask")} for event in block["events"]]
            signals={row["イベントID"]:row for values in block["signals"].values() for row in values}
            with gzip.open(f.work/"追尾.jsonl.gz","rt",encoding="utf-8") as stream:logs=[json.loads(line) for line in stream]
            audit=independent.Y.Audit()
            for detail in details:
                alternate,_=independent.replay(detail,quotes,signals,audit,bounds=(0.,100000.,95000.),config=f.config["運用"])
                self.assertEqual(alternate,[row for row in logs if row["候補ID"]==detail["候補ID"]])
            self.assertEqual(audit.mismatches,0)

    def test_共有15コピーと場別SMAと実buildの純13(self):
        """旧29数値を再更新せず、局所平均だけ場ごとに作る。

        引数: self(TestCase)は対象。
        返り値: None。実buildのstat/cache検査も人工小ファイルで接続する。
        """
        driver=driver_module()
        with artificial_driver(driver,2) as f:
            first,second=[row["session"] for row in f.manifest["entries"]]
            source=[{**row,"場":first,"未来label":"毒値"} for row in material()]
            following=[frame(0,122.,session=second)]
            with patch.object(driver.C,"read_bundle",return_value={"lower":{first:source,second:following}}):
                bundle=driver.read_bundle(f.study)
            self.assertEqual(set(bundle),{"lower","numeric","numeric_quality"})
            self.assertEqual(bundle["lower"][first],[J.frame_projection(row) for row in source])
            self.assertFalse(bundle["numeric"][second][0]["SMA準備"])
            self.assertEqual(bundle["numeric"][second][0]["SMA過去足数"],0)
            entry=f.manifest["entries"][0];source_path=f.folder/"人工source.bin";cache=f.folder/"人工cache.bin"
            source_path.write_bytes(b"artificial");cache.write_bytes(b"cache")
            stat=source_path.stat();entry.update(source_path=source_path.name,cache_path=os.path.relpath(cache,ROOT/"work/複合検証"),
                source_size=stat.st_size,source_mtime_ns=stat.st_mtime_ns,sha256_cache=sha(cache))
            manifest={**f.manifest,"source_root":str(f.folder)}
            times=tuple(SimpleNamespace(timestamp=lambda x=x:x) for x in (0.,100000.,90000.,95000.))
            with patch.object(driver.W.OLD.shared.legacy,"session_times",return_value=times), \
                    patch.object(driver.W.PREP,"read_events",side_effect=AssertionError("純準備でBBOを読まない")):
                block=driver.build_session(entry,manifest,bundle,f.config,False)
            self.assertTrue(all(set(row)==set(I.SIGNAL_FIELDS) for values in block["signals"].values() for row in values))
            self.assertEqual(block["events"],[]);self.assertEqual(len(block["metadata"]),1)
            entry["sha256_cache"]="0"*64
            with self.assertRaises(ValueError):driver.build_session(entry,manifest,bundle,f.config,False)

    def test_条件と実行中の版差を拒否(self):
        """閾値変更や実行途中のcode差を成功準備として保存しない。

        引数: self(TestCase)は対象。
        返り値: None。人工JSONだけを使用する。
        """
        driver=driver_module()
        with artificial_driver(driver,1) as f:
            wrong=deepcopy(f.config);wrong["実体包み"]["B2"]="結果後変更"
            with self.assertRaises(ValueError):driver.validate_config(wrong)
            initial=driver.current_bindings(f.study);changed=deepcopy(initial);changed["条件SHA256"]="0"*64
            with patch.object(driver,"manifest_for",return_value=f.manifest),patch.object(driver,"validate_reference",return_value=f.ref), \
                    patch.object(driver,"read_bundle",return_value=f.bundle),patch.object(driver,"build_session",side_effect=f.build), \
                    patch.object(driver,"current_bindings",side_effect=[initial,changed]),redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError):driver.run(f.study,f.work,True)
            self.assertFalse((f.work/"準備点検.json").exists())

    def test_固定は主独立最終合成と会計8経路を必須join(self):
        """不足証明/異版/旧固定変化を拒否してから人工固定を保存する。

        引数: self(TestCase)は対象。
        返り値: None。旧モデル数式と既存固定ファイルを変更しない。
        """
        required=[HERE/"状態独立確認.py",HERE/"追尾独立確認.py",HERE/"独立監査.py",ROOT/"work/実体包み/00046/会計人工接続.py"]
        if not all(path.exists() for path in required):self.skipTest("独立二CLI/会計人工source完成前")
        driver=driver_module()
        with artificial_driver(driver,1) as f,patch.object(driver,"manifest_for",return_value=f.manifest), \
                patch.object(driver,"validate_reference",return_value=f.ref),patch.object(driver,"read_bundle",return_value=f.bundle), \
                patch.object(driver,"build_session",side_effect=f.build),redirect_stdout(io.StringIO()):
            driver.run(f.study,f.work,True)
            dependency=HERE/"指標.py"
            finance_sources=("scripts/実体包み/独立監査.py","scripts/実体包み/運用.py","work/実体包み/00046/会計人工接続.py")
            finance={"全件一致":True,"不一致数":0,"人工経路数":8,"実行中code不変":True,
                "条件SHA256":sha(f.study/"条件.json"),"コードSHA256":{name:sha(ROOT/name) for name in finance_sources}}
            driver.W.write_json(f.work/"会計人工接続.json",finance)
            (f.work/"会計人工接続.py").write_bytes((ROOT/finance_sources[-1]).read_bytes())
            proof={"全件一致":True,"不一致数":0,"不一致":[],"ラベル計算":False,"損益計算":False,
                "主準備SHA256":sha(f.work/"準備点検.json"),"主コードSHA256":driver.code_pins(),
                "条件SHA256":sha(f.study/"条件.json"),"入力台帳SHA256":sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256":sha(driver.MANIFEST_PATH),"指標参照SHA256":sha(f.study/"指標参照.json"),
                "コードSHA256":sha(required[0]),"追尾コードSHA256":sha(required[1]),
                "依存コードSHA256":{dependency.relative_to(ROOT).as_posix():sha(dependency)}}
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
                self.assertTrue(all(not name.endswith("数値定義.jsonl.gz") for name in locked["ファイルSHA256"]))
                (f.study/"計画.md").write_text("固定後変更",encoding="utf-8")
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)
                driver.W.write_json(f.study/"結果.json",{})
                with self.assertRaises(ValueError):driver.freeze(f.study,f.work)


# ----------------------------------------
# 独立生値の限定許容と正本15列定義を混同せず、厳密な採否を別に検査する。

class 独立二経路接続検証(unittest.TestCase):
    """新floatblob無しのoverlayとCLI入力前guardを人工検査する。"""

    def test_正本二列だけoverlayし生値と非許容出典を変えない(self):
        """ATR/Hの演算差を許しても価格/時点/SMA/符号/採否差は拒否する。

        引数: self(TestCase)は対象。
        返り値: None。独立生配列は変更せず、新定義blobは作らない。
        """
        independent=load(HERE/"状態独立確認.py","実体46人工二経路")
        shared=material();raw=deepcopy(shared)
        raw[-1]["atr"]=math.nextafter(raw[-1]["atr"],math.inf)
        raw[-1]["macd_hist"]=math.nextafter(raw[-1]["macd_hist"],math.inf);kept=deepcopy(raw)
        defined=independent.define_frames(raw,shared)
        self.assertEqual(raw,kept);self.assertEqual(defined,shared)
        self.assertNotEqual(J.canonical_sha(raw),J.canonical_sha(defined))
        audit=independent.Audit()
        self.assertTrue(independent.compare_numeric_scope("15列定義対生",defined,raw,audit));self.assertEqual(audit.mismatches,0)
        for kind in ("missing","duplicate","shared_duplicate"):
            changed,source=deepcopy(raw),deepcopy(shared)
            if kind=="missing":changed.pop()
            elif kind=="duplicate":changed.append(deepcopy(changed[0]))
            else:source.append(deepcopy(source[0]))
            with self.assertRaises(ValueError):independent.define_frames(changed,source)
        for field,value in (("close",123.),("confirm",9999.),("場","別場")):
            changed=deepcopy(raw);changed[-1][field]=value
            copied=independent.define_frames(changed,shared)
            self.assertEqual(copied[-1][field],value)
            audit=independent.Audit();self.assertFalse(independent.compare_numeric_scope("非許容出典",defined,copied,audit))
            self.assertGreater(audit.mismatches,0)
        normal=generated(shared)
        for field,value in (("MACDヒスト現",-1e-16),("MACDヒスト変化",-1e-16),("atr",10.),("SMA進行符号",-1)):
            changed=deepcopy(normal);changed["decisions"][-1][field]=value
            audit=independent.Audit();independent.compare_numeric_scope("符号/D/精密差",normal,changed,audit)
            self.assertGreater(audit.mismatches,0)
        too_far=deepcopy(raw);too_far[-1]["macd_hist"]+=1e-5
        audit=independent.Audit();independent.compare_numeric_scope("許容超過",defined,too_far,audit)
        self.assertGreater(audit.mismatches,0)

    def test_独立CLIは無指定拒否と不正masterを入力前に止める(self):
        """明示モード/現在版の成功準備がなければ原入力へ進まない。

        引数: self(TestCase)は対象。
        返り値: None。人工study以外は小コードと固定条件だけを読む。
        """
        independent=load(HERE/"状態独立確認.py","実体46人工CLI独立")
        trail=load(HERE/"追尾独立確認.py","実体46人工CLI追尾")
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
                    patch.object(independent,"shared_bundle",side_effect=AssertionError("不正準備後は共有入力禁止")), \
                    patch.object(independent.G,"observed",side_effect=AssertionError("不正準備後は原入力禁止")):
                _,manifest,checked,_=independent.guarded_inputs(f.study,f.work,independent.Audit())
                self.assertEqual(manifest,f.manifest);self.assertEqual(checked,master)
                for key in ("条件SHA256","コードSHA256","ラベル計算"):
                    changed=deepcopy(master);changed[key]=True if key=="ラベル計算" else {} if key=="コードSHA256" else "0"*64
                    driver.W.write_json(f.work/"準備点検.json",changed)
                    with patch.object(sys,"argv",["人工.py","--prepare","--study",str(f.study),"--work",str(f.work)]):
                        with self.assertRaises(ValueError):independent.main()


def main() -> None:
    """人工だけを実行し最終版はrootの明示管理で保存する。

    引数: CLI --final(bool)は全コード停止後rootが一回だけ指定する。
    返り値: None。実市場のprepare/先着/運用は呼ばない。
    """
    parser=argparse.ArgumentParser(description="二実体と過去平均の人工検査")
    parser.add_argument("--final",action="store_true");args=parser.parse_args()
    paths=[HERE/n for n in ("検証.py","入口.py","指標.py","運用.py","合成検証.py")]
    paths.append(ROOT/"study/00046_二足の実体包みと平均進行/条件.json")
    paths=[p for p in paths if p.exists()];helpers=[p for p in (HERE/"状態独立確認.py",HERE/"追尾独立確認.py") if p.exists()]
    pins={p.relative_to(ROOT).as_posix():sha(p) for p in paths};before={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    with deny_market():result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged=pins=={p.relative_to(ROOT).as_posix():sha(p) for p in paths} and before=={p.relative_to(ROOT).as_posix():sha(p) for p in helpers}
    success=result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    if args.final and (len(pins)!=6 or len(before)!=2):raise ValueError("主4code/条件/合成と独立二code完成前")
    proof={"全件成功":success,"検証件数":result.testsRun,"合成編集終了":bool(args.final and success),"実行中code不変":unchanged,
        "市場入力読取":False,"市場先着損益計算":False,"ファイルSHA256":pins,
        "独立数値補助SHA256":before.get("scripts/実体包み/状態独立確認.py"),"独立追尾補助SHA256":before.get("scripts/実体包み/追尾独立確認.py"),
        "skip数":len(result.skipped),"失敗数":len(result.failures),"エラー数":len(result.errors)}
    WORK.mkdir(parents=True,exist_ok=True);target=WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"出力":str(target),"全件成功":success,"件数":result.testsRun,"SHA256":sha(target)},ensure_ascii=False))
    if not success:raise SystemExit(1)


if __name__=="__main__":main()
