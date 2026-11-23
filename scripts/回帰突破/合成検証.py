"""実市場I/Oを遮断し、終値突破・精密OLS・公開時点と固定XFの接続を検査する。"""

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
WORK = ROOT/"work/回帰突破"
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
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("回帰突破41合成_")
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


I = load(HERE/"入口.py", "回帰突破41合成の入口")
O = load(HERE/"運用.py", "回帰突破41合成の運用")
S37 = load(ROOT/"scripts/構造判別/合成検証.py", "回帰突破41合成の固定37人工補助")
CONFIG = deepcopy(S37.CONFIG)


def frame(index: int, close: float, **updates: object) -> dict:
    """正しい公開順を持つ人工3分足を作る。

    引数: index(int)は番号、close(float)は終値、updates(object)は変更値。
    返り値: dictは使用15列と未使用の毒値を持つ人工数値足。
    """
    end = (index+1)*180.
    return {"場": SESSION, "index": index, "minutes": 3, "start": end-180, "end": end,
        "confirm": end, "confirm_line": index+1, "publish": True, "missing": 0,
        "open": close, "high": close, "low": close, "close": close, "atr": 25.,
        "macd_hist": float(index), "数量入力可": False, "OBV公開可": False,
        "cloud_upper": 999999., "ラベル": "渡してはいけない未来", **updates}


def material(values: list[float] | None = None) -> list[dict]:
    """21足の新しい価格突破又は指定の価格経路を作る。

    引数: values(list[float]|None)は古い順の終値。
    返り値: list[dict]は新規取得や市場ラベルを含まない足列。
    """
    return [frame(index, float(value)) for index, value in enumerate(values or [100.+i for i in range(21)])]


def generated(frames: list[dict], **updates: object) -> dict:
    """人工の時間制約で入口だけを計算する。

    引数: frames(list[dict])は人工足、updates(object)は検査用の時間設定。
    返り値: dictは先着や運用を含まない新しい入口判定。
    """
    config = {"残り時間下限分": 60, "確認遅延上限秒": 30, **updates}
    return I.generate(frames, SESSION, 20000., 30000., config)


def reflected(frames: list[dict], center: float = 1000.) -> list[dict]:
    """整数で正確な上下反射を行い、時計を保つ。

    引数: frames(list[dict])は人工価格足、center(float)は反射時の和。
    返り値: list[dict]はヒスト符号だけ反転した鏡像。
    """
    rows = deepcopy(frames)
    for row in rows:
        previous = deepcopy(row)
        row.update(open=center-previous["open"], high=center-previous["low"],
            low=center-previous["high"], close=center-previous["close"], macd_hist=-previous["macd_hist"])
    return rows


class 精密回帰検証(unittest.TestCase):
    """標本内回帰と新価格突破の少数境界を検査する。"""

    def test_直線と定数と必要本数を補完しない(self) -> None:
        """傾きと切片の単位を保ち、定数R2を欠測へ分ける。

        引数: self(TestCase)は対象。
        返り値: None。表示値は期待分数の参考値。
        """
        linear = I.ols([100.+3*i for i in range(20)])
        self.assertEqual(linear["傾き"], I.exact(Fraction(3)))
        self.assertEqual(linear["切片"], I.exact(Fraction(100)))
        self.assertEqual(linear["R2"], I.exact(Fraction(1)))
        self.assertEqual(linear["残差平方和"], I.exact(Fraction(0)))
        flat = I.ols([100.]*20)
        self.assertEqual(flat["傾き符号"], 0)
        self.assertFalse(flat["R2準備"])
        self.assertEqual(flat["R2"], I.exact(None))
        for values in ([1.]*19, [1.]*21, [1.]*19+[float('nan')]):
            self.assertFalse(I.ols(values)["回帰準備"])

    def test_最後だけ急変はR2七分の一(self) -> None:
        """ER効率と等間隔の直線性を同じ票にしない。

        引数: self(TestCase)は対象。
        返り値: None。新基準は採用するが半分以上には届かない。
        """
        rows = material([100.]*20+[170.])
        result = generated(rows)
        regression = result["raw"][0]["OLS20"]
        self.assertEqual(regression["傾き"], I.exact(Fraction(1)))
        self.assertEqual(regression["R2"], I.exact(Fraction(1, 7)))
        self.assertEqual(tuple(len(result["signals"]["3分_"+p]) for p in I.POLICIES), (1, 1, 0))

    def test_R2半分等号と一ULP境界を厳密に分ける(self) -> None:
        """同じ表示へ丸まる差をepsilonで消さない。

        引数: self(TestCase)は対象。
        返り値: None。直線成分と直交残差の平方和が同じ人工経路。
        """
        coefficients = [25, -25, 6, -6, 2, -2, 0, 0, 0, 0]
        errors = coefficients+coefficients[::-1]
        values = [200.+i-9.5+errors[i]/2 for i in range(20)]
        self.assertEqual(I.ols(values)["R2"], I.exact(Fraction(1, 2)))
        result = generated(material([200.]+values))
        self.assertTrue(result["raw"][0]["戦略判定"]["L2"]["採用"])
        self.assertEqual(result["raw"][0]["OLS20"]["R2半分比較符号"], 0)
        for toward, sign in ((math.inf, -1), (-math.inf, 1)):
            changed = list(values); changed[-1] = math.nextafter(values[-1], toward)
            self.assertEqual(I.ols(changed)["R2半分比較符号"], sign)

    def test_前20高安と当足含む回帰20をずらして使う(self) -> None:
        """最古足を回帰に残したり現在を突破水準へ入れない。

        引数: self(TestCase)は対象。
        返り値: None。21本目で初めて原Pが作られる。
        """
        rows = material()
        self.assertEqual(generated(rows[:20])["raw"], [])
        item = generated(rows)["raw"][0]
        self.assertEqual(item["前20足番号"], list(range(20)))
        self.assertEqual(item["回帰20足番号"], list(range(1, 21)))
        self.assertEqual(item["直前最高H"], 119.)
        self.assertEqual(item["OLS20"]["切片"], I.exact(Fraction(101)))
        same = deepcopy(rows); same[-1].update(open=119., high=119., low=119., close=119.)
        self.assertEqual(generated(same)["raw"], [])

    def test_価格突破から方向と勢いは自動成立しない(self) -> None:
        """新高値でも古い高値群による負傾きや逆ヒスト差を残す。

        引数: self(TestCase)は対象。
        返り値: None。原Pは保存するが不採用を後から取り直さない。
        """
        backward = generated(material([200.]*10+[100.]*10+[201.]))
        self.assertEqual(len(backward["raw"]), 1)
        self.assertLess(backward["raw"][0]["OLS20"]["傾き符号"], 0)
        self.assertFalse(backward["signals"]["3分_L0"])
        rows = material(); rows[-1]["macd_hist"] = -1.
        result = generated(rows)
        self.assertEqual(len(result["raw"]), 1)
        self.assertFalse(result["signals"]["3分_L0"])

    def test_数値や時間不成立でも価格原Pを残す(self) -> None:
        """共通Mと時間対象を価格発動へ混ぜない。

        引数: self(TestCase)は対象。
        返り値: None。旧数量の不準備は新Mへ影響しない。
        """
        for key, value in (("atr", None), ("atr", 0.), ("macd_hist", None)):
            rows = material(); rows[-1][key] = value
            result = generated(rows)
            self.assertEqual(len(result["raw"]), 1)
            self.assertFalse(result["signals"]["3分_L0"])
            self.assertTrue(result["raw"][0]["先着評価対象"])
        self.assertTrue(generated(material())["signals"]["3分_L0"])
        result = I.generate(material(), SESSION, 3780., 30000., {"残り時間下限分": 60, "確認遅延上限秒": 30})
        self.assertEqual(len(result["raw"]), 1)
        self.assertFalse(result["raw"][0]["時間条件可"])

    def test_欠枠NP不正は不投入で番号飛越後は新seed可(self) -> None:
        """欠枠を圧縮した価格21本を作らない。

        引数: self(TestCase)は対象。
        返り値: None。全ケースで新たな連続21足を待つ。
        """
        for change in ({"missing": 1}, {"publish": False}, {"open": None}, {"start": 1.}):
            rows = material([100.+i for i in range(41)])
            rows[19].update(change)
            result = generated(rows)
            self.assertEqual([row["index"] for row in result["raw"]], [40])
        rows = material([100.+i for i in range(41)])
        for row in rows[20:]:
            row["index"] += 2
            for key in ("start", "end", "confirm"): row[key] += 360
        self.assertEqual(generated(rows)["raw"][0]["index"], 42)

    def test_価格鏡映で傾きとヒストだけ反転する(self) -> None:
        """R2を売りで1-R2へ補数化しない。

        引数: self(TestCase)は対象。
        返り値: None。全三採否と要求keyは同じ。
        """
        buy, sell = generated(material()), generated(reflected(material()))
        left, right = buy["raw"][0], sell["raw"][0]
        self.assertEqual(left["side"], -right["side"])
        self.assertEqual(left["OLS20"]["傾き符号"], -right["OLS20"]["傾き符号"])
        for key in ("R2", "全平方和", "残差平方和", "R2半分比較符号"):
            self.assertEqual(left["OLS20"][key], right["OLS20"][key])
        self.assertEqual(left["戦略判定"], right["戦略判定"])

    def test_L1冗長と未来prefixとcase深複写(self) -> None:
        """後足追加や一候補の変更で過去の採否を変えない。

        引数: self(TestCase)は対象。
        返り値: None。原時点を保持する三純信号。
        """
        rows = material([100.+i for i in range(30)])
        short, full = generated(rows[:21]), generated(rows)
        self.assertEqual(short["raw"][0], full["raw"][0])
        self.assertEqual(len(full["signals"]["3分_L0"]), len(full["signals"]["3分_L1"]))
        full["signals"]["3分_L0"][0]["戦略判定"]["L2"]["採用"] = False
        self.assertTrue(full["raw"][0]["戦略判定"]["L2"]["採用"])
        self.assertTrue(full["signals"]["3分_L2"][0]["戦略判定"]["L2"]["採用"])

    def test_候補別の同key複数は同方向も見送り(self) -> None:
        """広い人工遅延枠で通常到達しない競合防御を検査する。

        引数: self(TestCase)は対象。
        返り値: None。先に全採否を確定し一方だけ復活させない。
        """
        rows = material([100.+i for i in range(22)])
        for row in rows[20:]: row.update(confirm=4000., confirm_line=999)
        result = generated(rows, 確認遅延上限秒=500)
        self.assertEqual(len(result["raw"]), 2)
        for policy in I.POLICIES:
            self.assertFalse(result["signals"]["3分_"+policy])
            self.assertTrue(all(row["戦略判定"][policy]["同時競合"] for row in result["raw"]))

    def test_live13列に回帰量や将来ラベルを渡さない(self) -> None:
        """旧BBがない新母集団でも固定運用の必要列を満たす。

        引数: self(TestCase)は対象。
        返り値: None。現在ATR/価格/時計のコピーはstrict。
        """
        row = generated(material())["signals"]["3分_L0"][0]
        row.update(ラベル="未来", 最大順行pt=999999.)
        pure = I.pure_signal(row)
        self.assertEqual(set(pure), set(I.SIGNAL_FIELDS))
        self.assertIsNone(pure["bb_mean"])
        self.assertEqual((pure["low"], pure["high"], pure["atr"]), (120., 120., 25.))
        self.assertEqual(set(I.frame_projection(material()[0])), set(I.FRAME_FIELDS))

    def test_独立中心化OLSと全P全採否が一致(self) -> None:
        """主の和の式と独立の偏差積を別計算して照合する。

        引数: self(TestCase)は対象。
        返り値: None。独立API未完成だけ途中は省略可。
        """
        path = HERE/"状態独立確認.py"
        if not path.exists(): self.skipTest("独立API完成前")
        state = load(path, "回帰突破41人工の独立入口")
        if not hasattr(state, "generate"): self.skipTest("独立generate完成前")
        examples = [material(), reflected(material()), material([100.]*20+[170.]),
            material([200.]*10+[100.]*10+[201.])]
        for updates in ({"atr": None}, {"macd_hist": None}, {"missing": 1}, {"publish": False}):
            rows = material([100.+i for i in range(42)])
            rows[20].update(updates)
            examples.append(rows)
        for rows in examples:
            self.assertEqual(generated(rows), state.generate(deepcopy(rows), SESSION, 20000., 30000.,
                {"残り時間下限分": 60, "確認遅延上限秒": 30}))


class 固定XF検証(unittest.TestCase):
    """新しい三候補でも固定出口を変更しない。"""

    def test_買売三運用の全台帳と追尾を固定33へ照合する(self) -> None:
        """回帰値を追尾幅や起動条件へ混入させない。

        引数: self(TestCase)は対象。
        返り値: None。旧出口との直接同値で新入口の台帳対照とは分ける。
        """
        for side in (1, -1):
            for policy in I.POLICIES:
                source = S37.signal(policy, side, "順行", "人工回帰入口", 10., 10)
                source["場"] = SESSION
                source.update(OLS20={"未来": "毒値"}, ラベル="渡さない")
                events = [S37.quote(10., 1, side, -5.), S37.quote(11., 2, side, -5.),
                    S37.quote(12., 3, side, 15.), S37.quote(13., 4, side, 5.),
                    S37.quote(14., 5, side, 0.), S37.quote(15., 6, side, -5.)]
                method = "3分_"+policy+"_XF"
                actual, quality = O.replay(events, [source], [], SESSION, method, CONFIG, {"出口ID": "XF"}, "順行", BOUNDS)
                reference, info = O.BASE.replay(events, [O.pure_signal(source)], [], SESSION, method,
                    CONFIG, {"出口ID": "XF"}, "順行", BOUNDS)
                for key in ("fills", "trades", "orders", "signals", "normal_log"):
                    self.assertEqual(getattr(actual, key), getattr(reference, key))
                self.assertEqual(quality, info)
                self.assertEqual(len(actual.trades), 1)


def driver_module() -> Any:
    """主CLIを起動せず現在の定義だけを読み込む。

    引数: なし。
    返り値: Anyは実市場I/Oを遮断した主モジュール。
    """
    return load(HERE/"検証.py", "回帰突破41人工の主")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """新母集団用の人工数値束と保存先を作る。

    引数: driver(Any)は主、count(int)は場数。
    返り値: Iterator[Any]は一時study/work/数値束/buildの組。
    """
    with tempfile.TemporaryDirectory(prefix="回帰突破41合成_", dir=ROOT/"work") as temporary:
        folder = Path(temporary); study, work = folder/"study", folder/"work"
        study.mkdir(); work.mkdir()
        config = driver.expected_config()
        driver.W.write_json(study/"条件.json", config)
        for name in ("入力台帳.json", "指標参照.json"):
            driver.W.write_json(study/name, {"人工": True})
        (study/"計画.md").write_text("人工の新発動固定対象\n", encoding="utf-8")
        driver.W.write_json(work/"診断予定.json", {"人工": True})
        sessions = [str(date(2026, 9, 22)+timedelta(days=i//2))+("_Day" if i%2 == 0 else "_Night") for i in range(count)]
        bundle = {"lower": {}}
        for name in sessions:
            rows = material()
            for row in rows: row["場"] = name
            bundle["lower"][name] = rows

        def built(entry: dict, manifest: dict, shared: dict, current: dict, include_events: bool = False) -> dict:
            """新I.generateを通して人工の純入口と正式時の気配だけを作る。

            引数: entry/manifest/shared/current(dict)は主契約、include_events(bool)は正式フラグ。
            返り値: dictは原板stat/cacheを使わない場材料。
            """
            name = entry["session"]
            frames = deepcopy(shared["lower"][name])
            block = driver.I.generate(frames, name, 9000., 9500., current)
            block["signals"] = {sid: [driver.I.pure_signal(row, sid[3:]) for row in values]
                for sid, values in block["signals"].items()}
            block.update(frames={3: frames}, input_quality=deepcopy(block["quality"]), events=[],
                cutoff=9000., deadline=9500., duration=10000./60)
            if include_events:
                block["events"] = [S37.quote(3780., 1, 1, -5.), S37.quote(3781., 2, 1, -5.),
                    S37.quote(3782., 3, 1, 15.), S37.quote(3783., 4, 1, 5.),
                    S37.quote(3784., 5, 1, 0.), S37.quote(3785., 6, 1, -5.)]
            return block

        yield SimpleNamespace(study=study, work=work, config=config, bundle=bundle, built=built,
            manifest={"source_root": "人工予約だけ", "entries": [{"session": name} for name in sessions]},
            ref={"文書と証明": {}, "共有明細": []})


class 主接続検証(unittest.TestCase):
    """新価格P・数値共有・非損益準備・正式末尾を人工で接続する。"""

    def test_共有は29の3分数値だけで旧caseや上位を読まない(self) -> None:
        """新母集団へ旧入口/ラベルを紛れ込ませない。

        引数: self(TestCase)は対象。
        返り値: None。読取名は全指標だけで、その3分行へ限定する。
        """
        driver = driver_module()
        rows = material()+[{"minutes": 15, "場": "上位を使わない"}]
        with patch.object(driver, "validate_reference", return_value={}), \
                patch.object(driver, "shared_path", side_effect=lambda ref, name: Path(name)) as resolved, \
                patch.object(driver, "read_rows", return_value=rows) as read:
            bundle = driver.read_bundle(driver.STUDY)
        self.assertEqual(bundle, {"lower": {SESSION: rows[:-1]}})
        self.assertEqual(resolved.call_args.args[1], "全指標.jsonl.gz")
        self.assertEqual(read.call_count, 1)

    def test_CLI人工66準備はlabel運用損益を一切呼ばない(self) -> None:
        """66場の新価格Pと全採否だけをCLIまで通す。

        引数: self(TestCase)は対象。
        返り値: None。旧全同値/ラベル証明を新母集団の準備へ要求しない。
        """
        driver = driver_module()
        with artificial_driver(driver, 66) as f, \
                patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", return_value=f.ref), \
                patch.object(driver, "read_bundle", return_value=f.bundle), \
                patch.object(driver, "build_session", side_effect=f.built) as built, \
                patch.object(driver, "freeze", side_effect=AssertionError("準備を固定しない")), \
                patch.object(driver.W.OLD, "気配経路", side_effect=AssertionError("準備で先着を呼ばない")), \
                patch.object(driver.W.PREP, "read_events", side_effect=AssertionError("準備で気配を読まない")), \
                patch.object(driver.E, "entry_metrics", side_effect=AssertionError("準備で先着集計しない")), \
                patch.object(driver.S, "operation_metrics", side_effect=AssertionError("準備で損益集計しない")), \
                patch.object(driver.ENGINE, "replay", side_effect=AssertionError("準備で運用しない")), \
                patch.object(sys, "argv", ["検証.py", "--study", str(f.study), "--work", str(f.work), "--prepare"]), \
                redirect_stdout(io.StringIO()):
            driver.main()
            proof = driver.W.read_json(f.work/"準備点検.json")
            self.assertEqual(len(proof["準備"]), 66)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertTrue(all(call.args[-1] is False for call in built.call_args_list))
            self.assertEqual(len(proof["準備"][0]["判定"]), 1)
            self.assertEqual(len(proof["準備"][0]["純信号"]), 3)
            self.assertEqual(proof["準備"][0]["3分投影足数"], 21)
            self.assertFalse((f.study/"結果.json").exists())
            self.assertFalse(any((f.work/name).exists() for name in driver.FILES))

    def test_人工正式新先着と三運用を末尾まで保存する(self) -> None:
        """新しい先着を使い、旧対照なしで三caseと三台帳を作る。

        引数: self(TestCase)は対象。
        返り値: None。人工labelだけでAPIの125/250と全保存形を確認する。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            label = {"ラベル": "未約定", "理由": "人工先着APIだけ", **{key: None for key in driver.LABEL_FIELDS[2:]}}
            calls, evaluations = [], []

            def evaluate(now: float, cutoff: float, deadline: float, side: int, **kwargs: object) -> dict:
                """実相場を走査せず新規先着の時点と幅を点検する。

                引数: now/cutoff/deadline(float)は時計、side(int)は方向、kwargs(object)は125/250。
                返り値: dictは人工のラベル。
                """
                self.assertEqual(kwargs, {"adverse": 125, "favorable": 250})
                evaluations.append((now, side))
                return deepcopy(label)

            original = driver.ENGINE.replay

            def replayed(*args: Any, **kwargs: Any) -> Any:
                """純13列だけを新候補の人工XFへ渡す。

                引数: args/kwargs(Any)は主運用契約。
                返り値: Anyは人工時計範囲での固定出口。
                """
                self.assertTrue(all(set(row) == set(I.SIGNAL_FIELDS) for row in args[1]))
                calls.append(args[4])
                return original(*args, **kwargs, bounds=BOUNDS)

            def published(study: Path, *args: Any) -> None:
                """Viewer境界を人工の三資源へ限定する。

                引数: study(Path)は一時先、args(Any)は出力契約。
                返り値: None。実Viewerを起動しない。
                """
                driver.W.write_json(study/"一覧.resources.json", {"resources": [{"id": "00008_人工"+str(i)} for i in range(3)]})

            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "read_bundle", return_value=f.bundle), \
                    patch.object(driver, "build_session", side_effect=f.built), \
                    patch.object(driver, "freeze", return_value={}), \
                    patch.object(driver.W.OLD, "気配経路", return_value=SimpleNamespace(evaluate=evaluate)), \
                    patch.object(driver.ENGINE, "replay", side_effect=replayed), \
                    patch.object(driver.E, "publish_details", side_effect=published), redirect_stdout(io.StringIO()):
                result = driver.run(f.study, f.work, False)
            self.assertEqual((result["入口評価数"], result["運用候補数"]), (3, 3))
            self.assertEqual(calls, ["3分_"+p+"_XF" for p in I.POLICIES])
            self.assertEqual(evaluations, [(3780., 1)])
            import gzip
            with gzip.open(f.work/"入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
                cases = [json.loads(line) for line in stream]
            with gzip.open(f.work/"全運用詳細.jsonl.gz", "rt", encoding="utf-8") as stream:
                details = [json.loads(line) for line in stream]
            self.assertEqual(len(cases), 3)
            self.assertEqual(len(details), 3)
            self.assertTrue(all(row["元価格side"] == 1 and row["元価格発動ID"].endswith("0020_1") for row in cases))
            self.assertTrue(all("元39J0イベントID" not in row for row in cases))
            self.assertEqual(len(driver.W.read_json(f.study/"結果.json")["役割別入口評価"]), 3)
            self.assertFalse((f.study/"W0対照同値.json").exists())

    def test_条件変更とpartialを数値処理前に拒否する(self) -> None:
        """新P/半分境界の変更と正式明細の上書きを止める。

        引数: self(TestCase)は対象。
        返り値: None。人工一時先以外を編集しない。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            wrong = deepcopy(f.config); wrong["回帰突破"]["L2"] = "結果後調整"
            with self.assertRaises(ValueError): driver.validate_config(wrong)
            (f.work/driver.FILES[0]).write_bytes("人工partial".encode("utf-8"))
            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver, "validate_reference", return_value=f.ref), \
                    patch.object(driver, "read_bundle", side_effect=AssertionError("partial後に資料を開かない")):
                with self.assertRaises(ValueError): driver.run(f.study, f.work, False)

    def test_単一数値参照の証明欠落と固定差を拒否する(self) -> None:
        """旧価格Pや旧台帳を追加参照する変更も拒否する。

        引数: self(TestCase)は対象。
        返り値: None。実gzipの読取は宣言済みSHAへ置換する。
        """
        driver = driver_module()
        path = driver.STUDY/"指標参照.json"
        if not path.exists(): self.skipTest("主の数値参照完成前")
        pointer = driver.W.read_json(path)
        declared = {normalized(ROOT/row["パス"]): row["圧縮SHA256参考"] for row in pointer["共有明細"]}
        expanded = {normalized(ROOT/row["パス"]): row["展開内容SHA256"] for row in pointer["共有明細"]}
        original = driver.M.O.sha
        with artificial_driver(driver, 1) as f, \
                patch.object(driver.M.O, "sha", side_effect=lambda p: declared[normalized(p)] if normalized(p) in declared else original(p)), \
                patch.object(driver.M, "content_sha", side_effect=lambda p: expanded[normalized(p)]):
            driver.W.write_json(f.study/"指標参照.json", pointer)
            driver.validate_reference(f.study)
            for key in ("文書と証明", "共有明細"):
                wrong = deepcopy(pointer)
                if key == "文書と証明": wrong[key].pop(next(iter(wrong[key])))
                else: wrong[key] = []
                driver.W.write_json(f.study/"指標参照.json", wrong)
                with self.assertRaises(ValueError): driver.validate_reference(f.study)
            wrong = deepcopy(pointer); wrong["旧固定SHA256"] = "0"*64
            driver.W.write_json(f.study/"指標参照.json", wrong)
            with self.assertRaises(ValueError): driver.validate_reference(f.study)
            with self.assertRaises(ValueError): driver.validate_reference(f.study, "入口参照.json")

    def test_固定は主独立最終人工の全現在版joinを必須にする(self) -> None:
        """旧入口同値を要求せず、新P準備の失敗/欠落/古版を止める。

        引数: self(TestCase)は対象。
        返り値: None。固定ファイルは人工一時先だけへ作る。
        """
        driver = driver_module()
        if not (HERE/"追尾独立確認.py").exists(): self.skipTest("独立CLI完成前")
        with artificial_driver(driver, 1) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver, "validate_reference", return_value=f.ref), \
                patch.object(driver, "read_bundle", return_value=f.bundle), \
                patch.object(driver, "build_session", side_effect=f.built), redirect_stdout(io.StringIO()):
            driver.run(f.study, f.work, True)
            finance = driver.W.read_json(driver.WORK/"会計人工接続.json")
            driver.W.write_json(f.work/"会計人工接続.json", finance)
            (f.work/"会計人工接続.py").write_bytes((driver.WORK/"会計人工接続.py").read_bytes())
            dep = ROOT/"scripts/OBV反転/入口.py"
            proof = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
                "主準備SHA256": sha(f.work/"準備点検.json"), "主コードSHA256": driver.code_pins(),
                "条件SHA256": sha(f.study/"条件.json"), "入力台帳SHA256": sha(f.study/"入力台帳.json"),
                "参照入力台帳SHA256": sha(driver.MANIFEST_PATH), "指標参照SHA256": sha(f.study/"指標参照.json"),
                "コードSHA256": sha(HERE/"状態独立確認.py"), "追尾コードSHA256": sha(HERE/"追尾独立確認.py"),
                "依存コードSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
            synthetic = {"全件成功": True, "合成編集終了": False,
                "ファイルSHA256": {path.relative_to(ROOT).as_posix(): sha(path) for path in
                    [HERE/name for name in ("検証.py", "入口.py", "運用.py", "合成検証.py")]+[f.study/"条件.json"]},
                "独立数値補助SHA256": sha(HERE/"状態独立確認.py"), "独立追尾補助SHA256": sha(HERE/"追尾独立確認.py")}
            synthetic_file = f.work/"人工最終合成.json"
            driver.W.write_json(synthetic_file, synthetic)
            independent = f.work/"独立準備点検.json"
            old_read, old_sha = driver.W.read_json, driver.O.sha

            def read_json(path: Path) -> dict:
                """直前固定pinと最終人工の宣言だけを人工へ差替える。

                引数: path(Path)は小型証拠。
                返り値: dictは人工又は実小型正本。
                """
                if normalized(path) == normalized(driver.PREVIOUS/"固定.json"):
                    return {"ファイルSHA256": {dep.relative_to(ROOT).as_posix(): sha(dep)}}
                return deepcopy(synthetic) if normalized(path) == normalized(WORK/"合成検証.json") else old_read(path)

            def current_sha(path: Path) -> str:
                """実最終人工パスだけ一時証明へ写す。

                引数: path(Path)は指紋対象。
                返り値: strは人工又は正本SHA。
                """
                return sha(synthetic_file) if normalized(path) == normalized(WORK/"合成検証.json") else old_sha(path)

            with patch.object(driver.W, "read_json", side_effect=read_json), patch.object(driver.O, "sha", side_effect=current_sha):
                with self.assertRaises(FileNotFoundError): driver.freeze(f.study, f.work)
                driver.W.write_json(independent, proof)
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                synthetic["合成編集終了"] = True
                for key in proof:
                    wrong = deepcopy(proof)
                    wrong[key] = not proof[key] if isinstance(proof[key], bool) else "不一致" if not isinstance(proof[key], dict) else {}
                    driver.W.write_json(independent, wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(independent, proof)
                for key in ("独立数値補助SHA256", "独立追尾補助SHA256"):
                    correct = synthetic[key]; synthetic[key] = "0"*64
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                    synthetic[key] = correct
                for key in ("全件一致", "不一致数", "人工経路数", "コードSHA256", "条件SHA256", "実行中code不変"):
                    wrong = deepcopy(finance)
                    wrong[key] = (False if key in ("全件一致", "実行中code不変") else {}
                        if key == "コードSHA256" else "0"*64 if key == "条件SHA256" else -1)
                    driver.W.write_json(f.work/"会計人工接続.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                for source in ("scripts/回帰突破/独立監査.py", "scripts/回帰突破/運用.py", "work/回帰突破/00041/会計人工接続.py"):
                    wrong = deepcopy(finance); wrong["コードSHA256"].pop(source)
                    driver.W.write_json(f.work/"会計人工接続.json", wrong)
                    with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                wrong = deepcopy(finance)
                first = next(iter(wrong["コードSHA256"]))
                wrong["コードSHA256"][first] = "0"*64
                driver.W.write_json(f.work/"会計人工接続.json", wrong)
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.work/"会計人工接続.json", finance)
                driver.W.write_json(synthetic_file, synthetic)
                locked = driver.freeze(f.study, f.work)
                self.assertEqual(driver.freeze(f.study, f.work), locked)
                self.assertEqual(locked["独立準備SHA256"], sha(independent))
                (f.study/"計画.md").write_text("人工固定後変更\n", encoding="utf-8")
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)
                driver.W.write_json(f.study/"結果.json", {"人工": True})
                with self.assertRaises(ValueError): driver.freeze(f.study, f.work)


def main() -> None:
    """人工だけを検査し、最終許可前は途中証明を保存する。

    引数: CLI --final(bool)はroot許可後に一回だけ指定する。
    返り値: None。市場の原板/cache/先着/運用を起動しない。
    """
    parser = argparse.ArgumentParser(description="回帰突破の人工検査")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    paths = [HERE/name for name in ("検証.py", "入口.py", "運用.py", "合成検証.py")]
    paths.append(ROOT/"study/00041_終値突破と回帰の方向と直線性/条件.json")
    paths = [path for path in paths if path.exists()]
    helpers = [path for path in (HERE/"状態独立確認.py", HERE/"追尾独立確認.py") if path.exists()]
    pins = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in helpers}
    with deny_market():
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged = (pins == {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
        and before == {path.relative_to(ROOT).as_posix(): sha(path) for path in helpers})
    success = result.wasSuccessful() and unchanged and (not args.final or not result.skipped)
    if args.final and (len(pins) != 5 or len(before) != 2):
        raise ValueError("主3code/条件/合成と独立二code完成前です")
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
        "市場入力読取": False, "市場先着損益計算": False, "実行中コード条件不変": unchanged,
        "ファイルSHA256": pins, "独立数値補助SHA256": before.get("scripts/回帰突破/状態独立確認.py"),
        "独立追尾補助SHA256": before.get("scripts/回帰突破/追尾独立確認.py"),
        "skip数": len(result.skipped), "失敗数": len(result.failures), "エラー数": len(result.errors)}
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK/("合成検証.json" if args.final else "合成検証_途中.json")
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"出力": str(path), "全件成功": success, "件数": result.testsRun, "SHA256": sha(path)}, ensure_ascii=False))
    if not success: raise SystemExit(1)


if __name__ == "__main__":
    main()

