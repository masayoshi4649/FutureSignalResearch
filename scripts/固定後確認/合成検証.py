"""00027の開封境界・入力固定・助走と新一場の分離を人工入力だけで検査する。"""

from __future__ import annotations

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Iterator
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
STUDY=ROOT/"study/00027_試行00026の新Night固定後確認"
WORK=ROOT/"work/固定後確認"
OLD_STUDY=ROOT/"study/00026_反転のSAR確認時刻と順行持続"
SESSION="2026-11-04_Night"


def load(path: Path,name: str) -> object:
    """コマンド行実行せずAPIだけを読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: object はモジュール。新Nightの原板/CSV/cacheは開かない。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


X=load(HERE/"抽出.py","固定後確認合成の人工抽出")


def normalized(path: object) -> str:
    """I/Oせずパスを比較用の絶対表現へ変換する。

    引数: path (object) はpathlike。
    返り値: str は正規化パス。fd等は空文字にする。
    """
    try:
        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except TypeError:
        return ""


@contextmanager
def deny_actual(extra_contents: tuple[Path,...]=()) -> Iterator[None]:
    """実予約Nightのstat/openと、指定人工sourceの内容openを遮断する。

    引数: extra_contents (tuple[Path,...]) はmetadata-only試験の人工原板。
    返り値: Iterator[None] は遮断scope。既知65やコードは読める。
    """
    roots=[normalized(ROOT.parent/"JP_OSE_Data/future/NK225"/SESSION),normalized(WORK/"00027/キャッシュ")]
    extra={normalized(p) for p in extra_contents}
    old_open,old_path_open,old_stat=builtins.open,Path.open,Path.stat

    def reserved(path: object) -> bool:
        """文字列だけで実予約領域へのアクセスか判定する。

        引数: path (object) はpathlike。
        返り値: bool は実原板/CSV/cache領域か。
        """
        value=normalized(path)
        return any(value == root or value.startswith(root+os.sep) for root in roots)

    def safe_open(file: object,*args: object,**kwargs: object) -> object:
        """実予約又はmetadata-only原板の内容openを拒否する。

        引数: file/args/kwargs (object) はopen引数。
        返り値: object は許可済みのfile handle。
        """
        if reserved(file) or normalized(file) in extra:
            raise AssertionError("合成から実予約資料又はmetadata-only原板を開いてはいけない")
        return old_open(file,*args,**kwargs)

    def safe_path_open(path: Path,*args: object,**kwargs: object) -> object:
        """Path.openにも同じ内容遮断を適用する。

        引数: path (Path) はパス、args/kwargs (object) はopen引数。
        返り値: object は許可済みのfile handle。
        """
        if reserved(path) or normalized(path) in extra:
            raise AssertionError("合成から実予約資料又はmetadata-only原板を開いてはいけない")
        return old_path_open(path,*args,**kwargs)

    def safe_stat(path: Path,*args: object,**kwargs: object) -> object:
        """実予約のメタ情報も合成では触れない。

        引数: path (Path) はパス、args/kwargs (object) はstat引数。
        返り値: object は人工又は既知資料のstat。
        """
        if reserved(path):
            raise AssertionError("合成から実予約資料をstatしてはいけない")
        return old_stat(path,*args,**kwargs)

    with patch("builtins.open",side_effect=safe_open),patch.object(Path,"open",safe_path_open),patch.object(Path,"stat",safe_stat):
        yield


with deny_actual():
    M=load(HERE/"確認.py","固定後確認合成の新一場runner")


def sha(path: Path) -> str:
    """人工ファイルと既知コードの内容指紋を計算する。

    引数: path (Path) は人工又は既知ファイル。
    返り値: str はSHA256。予約した実Nightを呼び出し元から渡さない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def fixture() -> Iterator[dict]:
    """workspace/work内に人工一原板と人工試行だけを作る。

    引数: なし。
    返り値: Iterator[dict] は一時study/work/raw/pointer等。実予約ファイルはstatもopenもしない。
    """
    (ROOT/"work").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="固定後確認合成_",dir=ROOT/"work") as directory:
        base=Path(directory)
        study,work=base/"試行",base/"作業"
        study.mkdir()
        raw=base/"人工データ/future/NK225"/SESSION/"book.jsonl"
        raw.parent.mkdir(parents=True)
        raw.write_text("人工の原板であり市場値ではない\n",encoding="utf-8")
        stat=raw.stat()
        pointer=json.loads((STUDY/"条件参照.json").read_text(encoding="utf-8"))
        pointer["条件参照"]=str(OLD_STUDY/"条件.json")
        pointer["固定参照"]=str(OLD_STUDY/"固定.json")
        pointer["予約確認"]["パス"]=str(raw.parent)
        pointer["予約確認"]["ファイル"]=[{"名前":"book.jsonl","バイト":stat.st_size,"更新ns":stat.st_mtime_ns}]
        (study/"条件参照.json").write_text(json.dumps(pointer,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (study/"計画.md").write_text("# 人工合成専用\n\n実予約Nightは開かない。\n",encoding="utf-8")
        yield {"base":base,"study":study,"work":work,"raw":raw,"pointer":pointer}


def artificial_build(source: Path,cache: Path,symbol: str,session: str,source_root: Path) -> dict:
    """抽出の制御経路だけのため人工cacheと台帳行を作る。

    引数: source/cache/source_root (Path) は人工パス、symbol/session (str) は識別名。
    返り値: dict は固定readerと同形の最小台帳。cacheは数値npzではなく人工バイトで市場値を含まない。
    """
    cache.parent.mkdir(parents=True,exist_ok=True)
    cache.write_bytes("人工cache".encode("utf-8"))
    stat=source.stat()
    return {"session":session,"symbol":symbol,"source_path":source.relative_to(source_root).as_posix(),
        "source_size":stat.st_size,"source_mtime_ns":stat.st_mtime_ns,"sha256_uncompressed":sha(source),
        "sha256_cache":sha(cache),"cache_path":"上書きされる人工参照", "in_session_contract_codes":["人工限月"]}


@contextmanager
def warmup_fixture(f: dict) -> Iterator[dict]:
    """人工65場の空技術系列だけをwarmupの制御経路へ渡す。

    引数: f (dict) は一時fixture。
    返り値: Iterator[dict] は人工manifest/config/block生成器。実旧原板も実新原板も読まない。
    """
    config=json.loads((OLD_STUDY/"条件.json").read_text(encoding="utf-8"))
    known=json.loads(M.D.INPUT.read_text(encoding="utf-8"))
    raw=f["base"]/"旧人工book.jsonl"
    raw.write_bytes(b"old artificial")
    stat=raw.stat()
    entries=[{**deepcopy(e),"source_path":raw.name,"source_size":stat.st_size,"source_mtime_ns":stat.st_mtime_ns,
        "cache_path":"人工助走/"+e["session"]+".npz","sha256_cache":"人工cacheSHA"} for e in known["entries"]]
    manifest={"source_root":str(f["base"]),"entries":entries}
    manifest_path=f["base"]/"人工65台帳.json"
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding="utf-8")

    def block(entry: dict,*args: object) -> dict:
        """市場値なしの空足・空監視を一場分組み立てる。

        引数: entry (dict) は人工台帳、args (object) はcache/bank/config。
        返り値: dict はwarmupの保存制御に必要な最小情報。
        """
        session=entry["session"]
        quality={"場":session,**{name:[] for name in ("全Q発動記録","複合context記録","監視trace","エピソード診断","反転監視trace","反転監視診断")}}
        return {"場":session,"events":[],"frames":{3:[],15:[],30:[]},"signals":{"3分_"+p:[] for p in ("N0","N1","N2")},
            "quality":quality,"channels":[],"sar":[],"regimes":[],"channel_info":{},"sar_info":{"場":session},
            "regime_info":{},"quantity_info":{},"cutoff":0,"deadline":1,
            "input_info":{"場":session,"正常板数":0,"確定足数":{},"尾部欠枠":{}}}

    artifacts={"ファイル":[{"パス":"人工/"+n,"展開内容SHA256":hashlib.sha256(b"").hexdigest()} for n in M.TECHNICAL]}
    expected={name:[] for name in ("入口品質.json","入力品質.json","30窓品質.json","SAR品質.json","局面品質.json","数量診断品質.json")}
    for entry in entries:
        session=entry["session"]
        period=M.D.E.phase_of(session,config)
        b=block(entry)
        expected["入口品質.json"].append(M.summary_quality(b,period))
        expected["入力品質.json"].append({**b["input_info"],"期間":period})
        for name,info in (("30窓品質.json","channel_info"),("局面品質.json","regime_info"),("数量診断品質.json","quantity_info")):
            expected[name].append({"場":session,"期間":period,**b[info]})
        expected["SAR品質.json"].append({"期間":period,**b["sar_info"]})
    old_read,old_sha=M.read_json,M.sha

    def read(path: Path) -> dict:
        """旧保存品質だけを人工期待値へ差し替える。

        引数: path (Path) は参照先。
        返り値: dict は人工品質又は通常の既知JSON。
        """
        if path == OLD_STUDY/"作業成果物.json":
            return deepcopy(artifacts)
        if path.parent == OLD_STUDY and path.name in expected:
            return deepcopy(expected[path.name])
        return old_read(path)

    def fingerprint(path: Path) -> str:
        """存在しない人工cacheの指紋だけを置換する。

        引数: path (Path) は対象。
        返り値: str は人工cache又は既知ファイルのSHA。
        """
        if "人工助走" in path.parts:
            return "人工cacheSHA"
        return old_sha(path)

    with deny_actual((f["raw"],)),patch.object(M,"validate_pointer",return_value=(deepcopy(f["pointer"]),config,manifest_path)), \
            patch.object(M,"read_json",side_effect=read),patch.object(M,"sha",side_effect=fingerprint), \
            patch.object(M,"build_session",side_effect=block):
        yield {"config":config,"manifest":manifest,"block":block,"manifest_path":manifest_path}


@contextmanager
def freeze_fixture(f: dict) -> Iterator[dict]:
    """本物の27最終proofを書かず、人工proofでmetadata固定を試験する。

    引数: f (dict) は一時fixture。
    返り値: Iterator[dict] は人工合成proofと助走proof。正式27証拠は変更しない。
    """
    f["work"].mkdir()
    proof_path=ROOT/"work/固定後確認/合成検証.json"
    proof={"全件成功":True,"合成編集終了":True,"人工試験専用":True,
        "ファイルSHA256":{p.relative_to(ROOT).as_posix():sha(p) for p in (HERE/"確認.py",HERE/"抽出.py",HERE/"合成検証.py",f["study"]/"条件参照.json")}}
    proof_bytes=(json.dumps(proof,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    warm={"全件一致":True,"コードSHA256":M.code_pins(),"条件参照SHA256":sha(f["study"]/"条件参照.json")}
    (f["work"]/"助走点検.json").write_text(json.dumps(warm,ensure_ascii=False),encoding="utf-8")
    old_read,old_sha=M.read_json,M.sha

    def read(path: Path) -> dict:
        """合成proofの読取だけを人工辞書へ置換する。

        引数: path (Path) は参照先。
        返り値: dict は人工proof又は既知JSON。
        """
        return deepcopy(proof) if path == proof_path else old_read(path)

    def fingerprint(path: Path) -> str:
        """人工proofのhashだけ置換し、新原板hashを拒否する。

        引数: path (Path) は参照先。
        返り値: str は人工又は既知のSHA。
        """
        if path == f["raw"]:
            raise AssertionError("開封前固定で原板をhashしてはいけない")
        return hashlib.sha256(proof_bytes).hexdigest() if path == proof_path else old_sha(path)

    with deny_actual((f["raw"],)),patch.object(M,"read_json",side_effect=read),patch.object(M,"sha",side_effect=fingerprint):
        yield {"proof":proof,"warm":warm}


@contextmanager
def fresh_fixture(f: dict,block_factory: object | None=None) -> Iterator[dict]:
    """新一場runの接続だけを人工cache/助走proofで検査する。

    引数: f (dict) は一時fixture、block_factory (object|None) は人工技術block生成器。
    返り値: Iterator[dict] は人工locked/banks/proof。正式27固定や実新資料は開かない。
    """
    f["work"].mkdir()
    (f["study"]/"固定.json").write_text('{"人工固定":true}',encoding="utf-8")
    warm={"全件一致":True,"人工助走":True}
    (f["work"]/"助走点検.json").write_text(json.dumps(warm,ensure_ascii=False),encoding="utf-8")
    locked={"人工固定":True,"確認候補":M.IDS}
    banks=M.Banks()

    def extract(pointer: dict,work: Path,fixed_sha: str,authorized: bool=False) -> dict:
        """人工原板だけを人工readerで一回処理する。

        引数: pointer (dict) は人工予約、work (Path) は一時先、fixed_sha (str) は人工固定、authorized (bool) は人工許可。
        返り値: dict は人工一cache台帳。実原板へ差し替わればtripwireで失敗する。
        """
        self_path=Path(pointer["予約確認"]["パス"])/"book.jsonl"
        if self_path.resolve() != f["raw"].resolve():
            raise AssertionError("人工試験に実予約を渡してはいけない")
        with patch.object(X.PREP,"build_one",side_effect=artificial_build):
            return X.extract(pointer,work,fixed_sha,authorized)

    with deny_actual(),patch.object(M,"check_fixed",return_value=locked) as check, \
            patch.object(M,"warmup",return_value=(banks,warm)) as warm_call, \
            patch.object(M.X,"extract",side_effect=extract) as extract_call, \
            patch.object(M.D.W.PREP,"read_events",return_value=[]):
        if block_factory is None:
            yield {"locked":locked,"banks":banks,"warm":warm,"check":check,"extract":extract_call,"warm_call":warm_call}
        else:
            with patch.object(M,"build_session",side_effect=block_factory):
                yield {"locked":locked,"banks":banks,"warm":warm,"check":check,"extract":extract_call,"warm_call":warm_call}


# ----------------------------------------
# 実資料を一切渡さず、承認/予約stat/journal/抽出一回の境界を検査する。

class 人工抽出境界検証(unittest.TestCase):
    """一原板の拒否条件と初回失敗記録を人工一時ファイルだけで検査する。"""

    def test_承認なしでは予約statもreaderも呼ばない(self) -> None:
        """開封許可falseは新内容へ至るどの入口よりも先に拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f,patch.object(X,"check_reservation",side_effect=AssertionError("予約statも禁止")) as meta, \
                patch.object(X.PREP,"build_one",side_effect=AssertionError("reader禁止")) as reader:
            with self.assertRaises(ValueError):
                X.extract(f["pointer"],f["work"],"人工27固定",False)
            meta.assert_not_called()
            reader.assert_not_called()
            self.assertFalse(f["work"].exists())

    def test_原板サイズ又は更新nsの変更をreader呼出前に拒否する(self) -> None:
        """予約版から変わった入力を同一の初回確認として開かない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for mode in ("size","mtime"):
            with fixture() as f:
                if mode == "size":
                    f["raw"].write_bytes(f["raw"].read_bytes()+b"x")
                else:
                    old=f["raw"].stat()
                    os.utime(f["raw"],ns=(old.st_atime_ns,old.st_mtime_ns+10000))
                with patch.object(X.PREP,"build_one",side_effect=AssertionError("reader禁止")) as reader:
                    with self.assertRaises(ValueError):
                        X.extract(f["pointer"],f["work"],"人工27固定",True)
                    reader.assert_not_called()

    def test_原板予約の場名とbook一意性を内容なしで検査する(self) -> None:
        """別の場や複数bookの予約を黙って選び直さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f:
            altered=deepcopy(f["pointer"])
            altered["予約確認"]["場"]="人工の別場"
            with self.assertRaises(ValueError):
                X.reserved_source(altered)
            altered=deepcopy(f["pointer"])
            altered["予約確認"]["ファイル"]*=2
            with self.assertRaises(ValueError):
                X.reserved_source(altered)
            altered=deepcopy(f["pointer"])
            altered["予約確認"]["パス"]=str(f["raw"].parent/"別場")
            with self.assertRaises(ValueError):
                X.reserved_source(altered)

    def test_readerの前に初回journalを残し失敗記録とpartialcacheを消さない(self) -> None:
        """初回抽出失敗を未見状態に戻して再試行しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f:
            journal=f["work"]/"初回開封記録.json"

            def failure(*args: object,**kwargs: object) -> dict:
                """journalを確認後、人工readerを失敗させる。

                引数: args/kwargs (object) は固定reader引数。
                返り値: dict は返さずRuntimeErrorを送出する。
                """
                data=json.loads(journal.read_text(encoding="utf-8"))
                self.assertEqual(data["状態"],"初回抽出開始")
                cache=args[1]
                cache.parent.mkdir(parents=True)
                cache.write_bytes(b"partial")
                raise RuntimeError("人工reader失敗")

            with patch.object(X.PREP,"build_one",side_effect=failure) as reader:
                with self.assertRaisesRegex(RuntimeError,"人工reader失敗"):
                    X.extract(f["pointer"],f["work"],"人工27固定",True)
                self.assertEqual(reader.call_count,1)
                data=json.loads(journal.read_text(encoding="utf-8"))
                self.assertEqual((data["状態"],data["例外型"]),("初回抽出失敗","RuntimeError"))
                before=journal.read_bytes()
                with self.assertRaises(FileExistsError):
                    X.extract(f["pointer"],f["work"],"人工27固定",True)
                self.assertEqual(reader.call_count,1)
                self.assertEqual(journal.read_bytes(),before)
                self.assertTrue((f["work"]/"キャッシュ/NK225"/(SESSION+".npz")).exists())

    def test_成功抽出の一cacheと相対参照と内容指紋を一致させる(self) -> None:
        """新一場だけを共通cache基底から参照し、原板を複製しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f,patch.object(X.PREP,"build_one",side_effect=artificial_build) as reader:
            before=sha(f["raw"])
            manifest=X.extract(f["pointer"],f["work"],"人工27固定",True)
            reader.assert_called_once()
            self.assertEqual(len(manifest["entries"]),1)
            self.assertEqual(manifest["新規確認場数"],1)
            self.assertTrue(manifest["全旧65は助走のみ"])
            self.assertFalse(manifest["原板複製"])
            entry=manifest["entries"][0]
            cache=(ROOT/manifest["cache_base"]/entry["cache_path"]).resolve()
            self.assertTrue(cache.is_relative_to(f["work"]))
            self.assertEqual(cache,(f["work"]/"キャッシュ/NK225"/(SESSION+".npz")).resolve())
            self.assertEqual(entry["sha256_cache"],sha(cache))
            self.assertEqual(entry["sha256_uncompressed"],before)
            self.assertEqual(sha(f["raw"]),before)
            journal=json.loads((f["work"]/"初回開封記録.json").read_text(encoding="utf-8"))
            self.assertEqual(journal["状態"],"初回抽出完了")
            self.assertEqual(journal["新規入力台帳SHA256"],sha(f["work"]/"新規入力台帳.json"))
            with self.assertRaises(FileExistsError):
                X.extract(f["pointer"],f["work"],"人工27固定",True)
            self.assertEqual(reader.call_count,1)

    def test_抽出中のサイズ変化を拒否し初回失敗journalを残す(self) -> None:
        """readerの後に予約版と違う入力になった場合、成功台帳を作らない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f:

            def changing(*args: object,**kwargs: object) -> dict:
                """人工cacheを作った後に人工原板だけを変化させる。

                引数: args/kwargs (object) はreader引数。
                返り値: dict は変更前の人工台帳。
                """
                entry=artificial_build(*args,**kwargs)
                f["raw"].write_bytes(f["raw"].read_bytes()+b"changed")
                return entry

            with patch.object(X.PREP,"build_one",side_effect=changing):
                with self.assertRaisesRegex(ValueError,"statが変化"):
                    X.extract(f["pointer"],f["work"],"人工27固定",True)
            data=json.loads((f["work"]/"初回開封記録.json").read_text(encoding="utf-8"))
            self.assertEqual(data["状態"],"初回抽出失敗")
            self.assertFalse((f["work"]/"新規入力台帳.json").exists())

    def test_既存cacheを上書きせず初回成功とも扱わない(self) -> None:
        """journalなしでも既存cacheがあるなら読取を止める。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f:
            cache=f["work"]/"キャッシュ/NK225"/(SESSION+".npz")
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"existing")
            with patch.object(X.PREP,"build_one",side_effect=AssertionError("reader禁止")) as reader:
                with self.assertRaises(FileExistsError):
                    X.extract(f["pointer"],f["work"],"人工27固定",True)
                reader.assert_not_called()
            self.assertEqual(cache.read_bytes(),b"existing")
            self.assertFalse((f["work"]/"初回開封記録.json").exists())


# ----------------------------------------
# 固定26の正本とのアンカー、全候補、助走だけの再現性、metadata固定を検査する。

class 参照固定と助走検証(unittest.TestCase):
    """新資料をI/O遮断したまま旧条件と人工65場を検査する。"""

    def test_固定26同バイト参照を許し全三案の順序や数の変更を拒否する(self) -> None:
        """絶対Pathの既知正本参照は通し、候補を結果で選び直さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f,deny_actual((f["raw"],)):
            pointer,config,manifest=M.validate_pointer(f["study"])
            self.assertEqual(pointer["確認候補"],M.IDS)
            self.assertEqual([r["入口ID"]+"_X0" for r in M.D.sources(config)],M.IDS)
            self.assertEqual(manifest,M.D.INPUT)
            for ids in (M.IDS[:-1],list(reversed(M.IDS)),M.IDS+["3分_N3_X0"],["3分_N0_X1",*M.IDS[1:]]):
                altered=deepcopy(f["pointer"])
                altered["確認候補"]=ids
                (f["study"]/"条件参照.json").write_text(json.dumps(altered,ensure_ascii=False),encoding="utf-8")
                with self.assertRaises(ValueError):
                    M.validate_pointer(f["study"])

    def test_参照SHAも更新した別条件や空固定表を固定26正本として受け入れない(self) -> None:
        """pointerの自己整合だけで固定26の全条件/依存を外せないことを検査する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for kind in ("条件","固定"):
            with fixture() as f,deny_actual((f["raw"],)):
                pointer=deepcopy(f["pointer"])
                if kind == "条件":
                    value=json.loads((OLD_STUDY/"条件.json").read_text(encoding="utf-8"))
                    value["版"]+=1
                    path=f["base"]/"別条件.json"
                else:
                    value={"ファイルSHA256":{}}
                    path=f["base"]/"空固定.json"
                path.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
                pointer[kind+"参照"]=str(path)
                pointer[kind+"SHA256"]=sha(path)
                (f["study"]/"条件参照.json").write_text(json.dumps(pointer,ensure_ascii=False),encoding="utf-8")
                with self.assertRaises(ValueError):
                    M.validate_pointer(f["study"])

    def test_固定26依存の指紋差を実ファイルを変更せず拒否する(self) -> None:
        """主コード/入力参照が変わったとき正本hashが同じという理由だけで通さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f,deny_actual((f["raw"],)):
            old=M.sha
            target=ROOT/"scripts/反転確認時計/入口.py"

            def drift(path: Path) -> str:
                """既知一依存のhashだけを人工的に変化させる。

                引数: path (Path) は参照先。
                返り値: str は人工差又は実際の既知SHA。
                """
                return "人工依存差" if path == target else old(path)

            with patch.object(M,"sha",side_effect=drift):
                with self.assertRaisesRegex(ValueError,"固定26依存"):
                    M.validate_pointer(f["study"])

    def test_人工65助走は新抽出先着運用を呼ばず日時なしproofを再現する(self) -> None:
        """同じ既知入力で再助走しても固定済み助走証拠のbyteSHAを変えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f,warmup_fixture(f), \
                patch.object(M.X,"extract",side_effect=AssertionError("新抽出禁止")) as extract, \
                patch.object(M.ENGINE,"replay",side_effect=AssertionError("運用禁止")) as replay, \
                patch.object(M.D,"shadow_label",side_effect=AssertionError("先着禁止")) as label, \
                patch.object(M.D.W.OLD,"気配経路",side_effect=AssertionError("気配先着禁止")),redirect_stdout(io.StringIO()):
            first,proof=M.warmup(f["study"],f["work"])
            data=(f["work"]/"助走点検.json").read_bytes()
            second,again=M.warmup(f["study"],f["work"])
            self.assertEqual(proof,again)
            self.assertEqual(data,(f["work"]/"助走点検.json").read_bytes())
            self.assertEqual(proof["旧助走場数"],65)
            self.assertTrue(proof["全件一致"])
            self.assertEqual(len(proof["技術系列"]),7)
            self.assertEqual(set(vars(first)),{"indicators","channel","sar","contract"})
            self.assertEqual(set(vars(second)),set(vars(first)))
            for key in ("新規原板閲覧","新規cache閲覧","先着計算","損益計算"):
                self.assertFalse(proof[key])
            extract.assert_not_called()
            replay.assert_not_called()
            label.assert_not_called()
            self.assertFalse((f["study"]/"結果.json").exists())

    def test_助走実行中のコード差を検出し成功証拠を書かない(self) -> None:
        """実行開始/終了の版が違う助走を最終版へ読み替えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f,warmup_fixture(f),patch.object(M,"code_pins",side_effect=[{"版":"前"},{"版":"後"}]),redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError,"助走実行中"):
                M.warmup(f["study"],f["work"])
            self.assertFalse((f["work"]/"助走点検.json").exists())

    def test_開封前固定は新原板内容hashなしで同一版を再現し変更を拒否する(self) -> None:
        """人工新sourceはstatだけにし、固定後の計画差/既存結果を拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f,freeze_fixture(f):
            locked=M.freeze(f["study"],f["work"])
            self.assertEqual(locked["確認候補"],M.IDS)
            self.assertTrue(locked["新原板内容未閲覧"])
            self.assertNotIn(f["raw"].relative_to(ROOT).as_posix(),locked["ファイルSHA256"])
            before=(f["study"]/"固定.json").read_bytes()
            self.assertEqual(M.freeze(f["study"],f["work"]),locked)
            self.assertEqual(M.check_fixed(f["study"],f["work"]),locked)
            self.assertEqual((f["study"]/"固定.json").read_bytes(),before)
            (f["study"]/"計画.md").write_text("人工計画の変更",encoding="utf-8")
            with self.assertRaises(ValueError):
                M.check_fixed(f["study"],f["work"])
            (f["study"]/"結果.json").write_text("{}",encoding="utf-8")
            with self.assertRaises(FileExistsError):
                M.freeze(f["study"],f["work"])

    def test_未編集終了又は助走版差では開封前固定も作れない(self) -> None:
        """途中の合成/旧codeの助走を最終固定へ昇格しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for mode in ("proof","warm"):
            with fixture() as f,freeze_fixture(f) as values:
                if mode == "proof":
                    values["proof"]["合成編集終了"]=False
                else:
                    warm=deepcopy(values["warm"])
                    warm["コードSHA256"]={"人工":"旧版"}
                    (f["work"]/"助走点検.json").write_text(json.dumps(warm,ensure_ascii=False),encoding="utf-8")
                with self.assertRaises(ValueError):
                    M.freeze(f["study"],f["work"])
                self.assertFalse((f["study"]/"固定.json").exists())


# ----------------------------------------
# 人工一場の全三案/ゼロ取引、表示列と未来label分離、数値銀行だけのcarryを検査する。

class 新一場分離検証(unittest.TestCase):
    """新資料をI/O遮断したまま、新一場の初期化と一回実行を検査する。"""

    def test_run未承認又は既存結果journalなら固定助走抽出も呼ばない(self) -> None:
        """承認前/既存初回を黙って新規確認へ進めない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for mode in ("unauthorized","result","journal"):
            with fixture() as f,deny_actual((f["raw"],)), \
                    patch.object(M,"check_fixed",side_effect=AssertionError("固定検査まで進めない")) as check, \
                    patch.object(M,"warmup",side_effect=AssertionError("助走禁止")) as warm, \
                    patch.object(M.X,"extract",side_effect=AssertionError("抽出禁止")) as extract:
                if mode == "result":
                    (f["study"]/"結果.json").write_bytes(b"existing result")
                elif mode == "journal":
                    f["work"].mkdir()
                    (f["work"]/"初回開封記録.json").write_bytes(b"existing journal")
                error=ValueError if mode == "unauthorized" else FileExistsError
                with self.assertRaises(error):
                    M.run(f["study"],f["work"],mode != "unauthorized")
                check.assert_not_called()
                warm.assert_not_called()
                extract.assert_not_called()

    def test_人工新一場は無活動でも全三案を保存し旧場損益支持へ合算しない(self) -> None:
        """空eventsの新一場でも三結果/三Viewer資源と終建玉0を保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。人工cacheだけを使い、実新Nightはstatもopenもしない。
        """
        with fixture() as f,fresh_fixture(f) as values:
            report=M.run(f["study"],f["work"],True)
            self.assertEqual(report["確認候補"],M.IDS)
            self.assertEqual([r["候補ID"] for r in report["結果"]],M.IDS)
            self.assertEqual(report["新規確認場数"],1)
            self.assertEqual(report["旧助走場数"],65)
            self.assertFalse(report["旧場損益合算"])
            self.assertFalse(report["新1場による支持代用"])
            self.assertFalse(report["条件変更"])
            self.assertTrue(report["確認後は既使用"])
            old={r["候補ID"]:r for r in json.loads((OLD_STUDY/"結果.json").read_text(encoding="utf-8"))["結果"]}
            for row in report["結果"]:
                self.assertEqual(row["新規確認"]["入口"]["候補数"],0)
                operation=row["新規確認"]["運用"]
                self.assertEqual(operation["入力場数"],1)
                self.assertEqual(operation["完結取引数"],0)
                self.assertEqual(operation["活動場数"],0)
                self.assertEqual(operation["無取引場数"],1)
                self.assertEqual(row["旧26資格"],{k:old[row["候補ID"]][k] for k in ("入口支持","70目標","費用資格")})
            catalog=json.loads((f["study"]/"一覧.resources.json").read_text(encoding="utf-8"))
            self.assertEqual([r["method_id"] for r in catalog["resources"]],M.IDS)
            with gzip.open(f["work"]/"全運用詳細.jsonl.gz","rt",encoding="utf-8") as stream:
                details=[json.loads(line) for line in stream]
            self.assertEqual(len(details),3)
            self.assertTrue(all(not r["約定"] and not r["注文"] and not r["取引"] for r in details))
            self.assertEqual(values["extract"].call_count,1)
            self.assertEqual(values["warm_call"].call_count,1)
            self.assertEqual(len(list(f["work"].glob("*.jsonl.gz"))),11)

    def test_engineへのsignalは表示二列だけを追加しcaseの未来labelを混ぜない(self) -> None:
        """固定26の人工f/h/gを新runnerへ渡し、運用と先着保存を分離する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。人工値だけで実資料先着/P&Lを見ない。
        """
        with deny_actual():
            fixed=load(ROOT/"scripts/反転確認時計/合成検証.py","固定後確認合成の固定26人工signal")
        signals,quality=fixed.generate()
        before={r["イベントID"]:deepcopy(r) for rows in signals.values() for r in rows}
        for row in before.values():
            row["場"]=SESSION
        for rows in signals.values():
            for row in rows:
                row["場"]=SESSION
        for row in quality["全Q発動記録"]:
            row["場"]=SESSION
        delivered=[]
        real_replay=M.ENGINE.replay

        def block(entry: dict,*args: object) -> dict:
            """新一場の生成結果を固定26人工signalへ置換する。

            引数: entry (dict) は人工台帳、args (object) はcache/banks/config。
            返り値: dict は人工技術block。
            """
            return {"場":SESSION,"events":[],"frames":{3:fixed.lower(),15:[],30:[]},"signals":signals,
                "quality":quality,"channels":[],"sar":[],"regimes":[],"channel_info":{},"sar_info":{"場":SESSION},
                "regime_info":{},"quantity_info":{},"cutoff":20000,"deadline":30000,
                "input_info":{"場":SESSION,"正常板数":0,"確定足数":{},"尾部欠枠":{}}}

        def replay(*args: object,**kwargs: object) -> object:
            """engineへ届く原signalを返済等で変更される前に保存する。

            引数: args/kwargs (object) は固定engine引数。
            返り値: object は本来の人工運用結果。
            """
            delivered.extend(deepcopy(args[1]))
            return real_replay(*args,**kwargs)

        fake_path=SimpleNamespace(evaluate=unittest.mock.Mock(return_value=M.D.blank_label()))
        with fixture() as f,fresh_fixture(f,block),patch.object(M.ENGINE,"replay",side_effect=replay), \
                patch.object(M.D.W.OLD,"気配経路",return_value=fake_path):
            M.run(f["study"],f["work"],True)
            self.assertTrue(delivered)
            for row in delivered:
                self.assertEqual(row["期間"],M.PERIOD)
                self.assertIn("要求時計JST",row)
                self.assertTrue(all(k not in row for k in ("ラベル","新規価格","新規時計秒","判定時計秒","判定原板行","最大順行pt","最大逆行pt")))
                self.assertEqual({k:v for k,v in row.items() if k not in ("期間","要求時計JST")},before[row["イベントID"]])
            with gzip.open(f["work"]/"入口事例.jsonl.gz","rt",encoding="utf-8") as stream:
                cases=[json.loads(line) for line in stream]
            self.assertEqual(len(cases),len(delivered))
            self.assertTrue(all(r["ラベル"] == "未約定" for r in cases))

    def test_開封後の固定コード差は実行失敗を残し新規結果を完成しない(self) -> None:
        """初回抽出後の版違いを成功確認や未見再試行へ置換しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        with fixture() as f,fresh_fixture(f) as values,patch.object(M.ENGINE,"replay",side_effect=AssertionError("運用へ進めない")) as replay:
            values["check"].side_effect=[values["locked"],values["locked"],ValueError("人工コード差")]
            with self.assertRaisesRegex(ValueError,"人工コード差"):
                M.run(f["study"],f["work"],True)
            replay.assert_not_called()
            self.assertFalse((f["study"]/"結果.json").exists())
            record=json.loads((f["work"]/"新規確認実行記録.json").read_text(encoding="utf-8"))
            self.assertEqual(record["状態"],"初回開封後の確認失敗")
            self.assertTrue(record["再度未見としない"])
            with self.assertRaises(FileExistsError):
                M.run(f["study"],f["work"],True)
            self.assertEqual(values["extract"].call_count,1)

    def test_同限月で数値銀行だけcarryし限月変更では解除する(self) -> None:
        """完全幅足のない人工1分窓でtail-resetを避け、銀行carryと新場監視0の枝を検査する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。指標数式は固定26/25を変更しない。
        """
        with deny_actual():
            fixed=load(ROOT/"scripts/SAR持続/合成検証.py","固定後確認合成の人工SARseed")
        config=json.loads((OLD_STUDY/"条件.json").read_text(encoding="utf-8"))
        banks=M.Banks()
        contract=("人工限月",)
        banks.contract=contract
        seed=[fixed.frame(i,105+i,95+i,100+i) for i in range(4)]
        banks.sar.build(seed,"人工旧場",contract)
        direction,following=banks.sar.direction,banks.sar.next_line
        previous=dict(banks.indicators)
        begin=datetime(2000,1,1,tzinfo=timezone.utc)
        times=(begin,begin+timedelta(minutes=1),begin+timedelta(hours=1),begin+timedelta(hours=2))
        entry={"session":SESSION,"in_session_contract_codes":list(contract)}
        with deny_actual(),patch.object(M.D.W.PREP,"read_events",return_value=[]), \
                patch.object(M.D.W.OLD.shared.legacy,"session_times",return_value=times):
            block=M.build_session(entry,ROOT/"work/存在しない人工cache",banks,config)
            self.assertEqual((banks.sar.direction,banks.sar.next_line),(direction,following))
            self.assertTrue(all(banks.indicators[n] is previous[n] for n in previous))
            self.assertEqual(set(vars(banks)),{"indicators","channel","sar","contract"})
            self.assertTrue(all(not rows for rows in block["signals"].values()))
            self.assertEqual(block["quality"]["設定数"],0)
            self.assertEqual(block["quality"]["反転候補登録数"],0)
            entry["in_session_contract_codes"]=["別人工限月"]
            M.build_session(entry,ROOT/"work/存在しない人工cache",banks,config)
            self.assertTrue(all(banks.indicators[n] is not previous[n] for n in previous))
            self.assertEqual((banks.sar.direction,banks.sar.next_line),(0,None))


def main() -> None:
    """人工検査とコード/計画/条件参照の現在版を途中又は最終proofへ保存する。

    引数: なし。--finalは全追加編集終了とrootの固定前確認後に指定する。
    返り値: None。実新Nightは内容/CSV/cacheを開かず、失敗時は終了1。
    """
    parser=argparse.ArgumentParser(description="新一場固定後確認の人工境界合成")
    parser.add_argument("--final",action="store_true",help="合成編集終了の最終proof")
    args=parser.parse_args()
    paths=[HERE/n for n in ("確認.py","抽出.py","合成検証.py")]+[STUDY/"条件参照.json"]
    pins={p.relative_to(ROOT).as_posix():sha(p) for p in paths if p.exists()}
    if args.final and len(pins) != len(paths):
        raise ValueError("全runner/抽出/合成/条件参照が揃う前は固定不可")
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    proof={"全件成功":result.wasSuccessful(),"検証件数":result.testsRun,"合成編集終了":bool(args.final and result.wasSuccessful()),
        "新Night内容閲覧":False,"ファイルSHA256":pins,
        "失敗":[{"検証":str(c),"内容":m} for c,m in result.failures],"エラー":[{"検証":str(c),"内容":m} for c,m in result.errors],
        "範囲":"人工一時sourceだけで予約stat/開封承認/journal/一回抽出/一cache参照を検証。固定26正本アンカー/全三案/助走の非損益・再現性/固定後差拒否/新一場のみの無活動成績/ラベル非混入/数値銀行carryと場内状態非carryを検証。実新Nightの原板/CSV/cache/価格/指標/先着/P&Lは未閲覧。",
        "実行記録":stream.getvalue()}
    WORK.mkdir(parents=True,exist_ok=True)
    (WORK/("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k:proof[k] for k in ("全件成功","検証件数","合成編集終了","新Night内容閲覧")},ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
