"""固定36件を変更せず、小型stream抽出だけを固定後追補として確認する。"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load() -> object:
    """固定合成の人工fixtureと対象moduleを読取再利用する。

    引数: なし。
    返り値: object は固定合成module。固定合成のmainや原板全量処理は実行しない。
    """
    spec = importlib.util.spec_from_file_location("VWAP入力の固定36合成", HERE/"合成検証.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


BASE = load()
M, WORK = BASE.M, BASE.WORK
record, condition = BASE.record, BASE.condition


# ----------------------------------------
# 自作の数行ファイルだけでstream抽出とSHA・空行・圧縮原行範囲を確認する。

class 小型stream検証(unittest.TestCase):
    """共有原板を使わず実抽出経路の保存と拒否条件を検査する。"""

    def test_生とgzipの展開SHAと空行での同一状態分断(self) -> None:
        """空行を跨いでrepeatを延ばさず、単独VWAP/代金更新をNPZへ残す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。自作の一時入力だけを読み取り、終了時に片付ける。
        """
        WORK.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=WORK) as temporary:
            folder = Path(temporary).resolve()
            self.assertTrue(folder.is_relative_to(WORK.resolve()))
            first = json.dumps(record(), ensure_ascii=False).encode()+b"\n"
            body = first+first+b"\n"+first+json.dumps(record(VWAP=60001)).encode()+b"\n"+json.dumps(record(VWAP=60001, TradingValue=6000001000)).encode()+b"\n"
            for suffix in (".jsonl", ".jsonl.gz"):
                with self.subTest(形式=suffix):
                    source = folder/("人工原板"+suffix)
                    source.write_bytes(gzip.compress(body, mtime=0) if suffix.endswith(".gz") else body)
                    status = source.stat()
                    entry = {"symbol": "NK225", "session": "2026-11-04_Day", "source_path": source.name,
                             "source_size": status.st_size, "source_mtime_ns": status.st_mtime_ns,
                             "sha256_uncompressed": hashlib.sha256(body).hexdigest(), "raw_lines": 6, "decoded_rows": 5}
                    target = folder/("抽出"+suffix+".npz")
                    result = M.extract_one(entry, folder, target, condition())
                    events = list(M.read_events(target))
                    self.assertTrue(result["旧展開SHA一致"])
                    self.assertEqual(result["raw_lines"], 6)
                    self.assertEqual(result["decoded_rows"], 5)
                    self.assertEqual(result["events"], 4)
                    self.assertEqual([e.line for e in events], [1, 4, 5, 6])
                    self.assertEqual([e.repeat for e in events], [2, 1, 1, 1])
                    self.assertEqual([e.native_vwap for e in events], [60000, 60000, 60001, 60001])
                    self.assertEqual(result["原行品質"]["空行数"], 1)
                    self.assertEqual(result["原行品質"]["VWAP代金だけ更新した保存状態数"], 2)
                    wrong = {**entry, "sha256_uncompressed": "0"*64}
                    rejected_target = folder/("指紋不一致"+suffix+".npz")
                    with self.assertRaises(ValueError):
                        M.extract_one(wrong, folder, rejected_target, condition())
                    self.assertFalse(rejected_target.exists())
                    before = hashlib.sha256(target.read_bytes()).hexdigest()
                    with self.assertRaises(FileExistsError):
                        M.extract_one(entry, folder, target, condition())
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)

    def test_欠測同士の完全同一判定と列単独差を区別(self) -> None:
        """NaN同士を同一状態とし、lineやrepeat以外の列差を保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        codes, exchanges, cache = [], [], {}
        a = M.parse_record(record(VWAP=None), 1, cache, codes, exchanges)
        b = M.parse_record(record(VWAP=None), 9, cache, codes, exchanges)
        c = M.parse_record(record(VWAP=None, TradingValue=6000001000), 10, cache, codes, exchanges)
        self.assertEqual(M.state_key(a), M.state_key(b))
        self.assertNotEqual(M.state_key(a), M.state_key(c))


# ----------------------------------------
# 固定36件のproofを上書きせず、追補2件だけを別記録へ保存する。


def main() -> None:
    """追加2件を実行し固定後追補JSONへ記録する。

    引数: なし。
    返り値: None。全量結果や固定台帳を変更せず、失敗時は終了コード1。
    """
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    paths = (Path(__file__), HERE/"合成検証.py", HERE/"抽出監査.py", BASE.STUDY/"条件.json")
    report = {"固定後追補": True, "固定36件へ加算しない": True,
              "全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
              "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors],
              "ファイルSHA256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
              "範囲": "固定後追補の小型自作生/gzipだけ。展開SHA/物理行/repeat/空行切断/単独更新/上書きとSHA不一致拒否。共有原板・PnLは扱わない。",
              "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/"追加合成検証.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({key: report[key] for key in ("全件成功", "検証件数", "固定後追補")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
