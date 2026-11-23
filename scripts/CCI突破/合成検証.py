"""31のCCI厳密値・上位BB公開時点・純採否を人工入力で検査する。"""

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
STUDY = ROOT / "study/00031_CCI持続と上位BB幅"
WORK = ROOT / "work/CCI突破"
SESSION = "人工CCI場"
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
    """人工合成から共有原板とwork内npzへstat/openさせない。

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
        if name == raw or name.startswith(raw + os.sep) or name.startswith(work + os.sep) and name.endswith(".npz"):
            raise AssertionError("人工合成から実原板/cacheへ触れない:" + str(path))

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


def from_closes(values: list[float], minutes: int = 3, base: float = 15300.) -> list[dict]:
    """終値と同じ高安を持つ、検算用の人工公開足を作る。

    引数: values(list[float])は終値、minutes(int)は3又は15、base(float)は開始基点。
    返り値: list[dict]は原板を使わない足。高安差0でも終値変化のATRは測れる。
    """
    return [frame(i, high=value, low=value, close=value, minutes=minutes, base=base)
            for i, value in enumerate(values)]


def lower_golden() -> list[dict]:
    """現前CCIが380/3で、最後に前20高値を終値突破する21足を作る。

    引数: なし。
    返り値: list[dict]は100..120の人工3分足。最新終了は19080秒。
    """
    return from_closes([float(100+index) for index in range(21)])


def upper_golden() -> list[dict]:
    """現前20母分散の差が51/16で、最新終了18900秒の上位足を作る。

    引数: なし。
    返り値: list[dict]は95×10/105×10/110の21本の人工15分足。
    """
    return from_closes([95.]*10+[105.]*10+[110.], minutes=15, base=0.)


def exact_cci(frames: list[dict]) -> tuple[Fraction, Fraction, Fraction | None]:
    """元OHLCのFractionから、同じ最後20本の平均とMDを直接検算する。

    引数: frames(list[dict])は20本以上の人工足。
    返り値: tuple[Fraction,Fraction,Fraction|None]は平均/MD/CCI。MD0は無効。
    """
    values = [(Fraction(row["high"])+Fraction(row["low"])+Fraction(row["close"]))/3
              for row in frames[-20:]]
    if len(values) != 20:
        raise ValueError("人工期待値には20本必要")
    mean = sum(values)/20
    md = sum(abs(value-mean) for value in values)/20
    return mean, md, (values[-1]-mean)/(Fraction(3, 200)*md) if md else None


J = load(HERE / "指標.py", "CCI合成の数値銀行")
I = load(HERE / "入口.py", "CCI合成の同時点入口")


def rows_of(frames: list[dict], session: str = SESSION) -> list[dict]:
    """一つの人工足幅の数値だけを生成する。

    引数: frames(list[dict])は同じ幅の人工足、session(str)は場名。
    返り値: list[dict]はCCI又はBB数値足。先着・損益は計算しない。
    """
    return J.NumericBank(frames[0]["minutes"]).build(frames, session, CONTRACT)[0]


def generate(lower: list[dict] | None = None, higher: list[dict] | None = None,
             cutoff: float = 100000., deadline: float = 200000.) -> tuple[dict, dict]:
    """人工の当場3分/15分だけから原PとC0/C1を生成する。

    引数: lower/higher(list[dict]|None)は数値足、cutoff/deadline(float)は期限。
    返り値: tuple[dict,dict]は二純入口と全context/raw。Noneなら人工golden。
    """
    return I.generate(rows_of(lower_golden()) if lower is None else lower,
                      rows_of(upper_golden()) if higher is None else higher,
                      SESSION, cutoff, deadline, I.expected_config())


def rational(value: dict, numerator: str = "分子", denominator: str = "分母") -> Fraction | None:
    """保存済み既約分子分母を検算用Fractionへ戻す。

    引数: value(dict)はCCI又は出典値、numerator/denominator(str)は保存キー。
    返り値: Fraction|Noneは正確値。欠測を数値へ補完しない。
    """
    return None if value[numerator] is None else Fraction(value[numerator], value[denominator])


class CCIの原式と銀行検証(unittest.TestCase):
    """同じ現在窓のTP/平均/MD、厳密水準と局所・数値銀行の境界を調べる。"""

    def test_原HLCを先にFraction化し同じ現在平均からMDを計算する(self) -> None:
        """丸め済みfloatTPを分数化する実装と異なる明示期待値へ照合する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。平均1504/15・MD34/75・CCI20500/51へ厳密照合。
        """
        frames = from_closes([100.]*20)
        for row, high in zip(frames[-3:], (102., 105., 109.)):
            row["high"] = high
        item = rows_of(frames)[-1]["CCI現"]
        self.assertEqual(exact_cci(frames), (Fraction(1504,15), Fraction(34,75), Fraction(20500,51)))
        self.assertEqual(rational(item, "平均分子", "平均分母"), Fraction(1504,15))
        self.assertEqual(rational(item, "MD分子", "MD分母"), Fraction(34,75))
        self.assertEqual(rational(item, "現TP分子", "現TP分母"), Fraction(103))
        self.assertEqual(rational(item), Fraction(20500,51))
        self.assertTrue(item["有効"])
        self.assertEqual(item["足番号"], list(range(20)))

    def test_20本目と21本目およびMD0を明示し古い値へ補完しない(self) -> None:
        """線形CCIの最速現前準備と全同値の0除算を検査する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。20本目現在CCI380/3、21本目に現前が揃う。
        """
        rows = rows_of(lower_golden())
        self.assertTrue(all(row["CCI現"] is None for row in rows[:19]))
        self.assertEqual(rational(rows[19]["CCI現"]), Fraction(380,3))
        self.assertIsNone(rows[19]["CCI前"])
        self.assertFalse(rows[19]["CCI準備済"])
        self.assertTrue(rows[20]["CCI準備済"])
        self.assertEqual(rational(rows[20]["CCI現"]), Fraction(380,3))
        self.assertEqual(rational(rows[20]["CCI前"]), Fraction(380,3))
        constant = rows_of(from_closes([100.]*21))[-1]
        for key in ("CCI現", "CCI前"):
            self.assertFalse(constant[key]["有効"])
            self.assertIsNone(constant[key]["値"])
            self.assertIsNone(rational(constant[key]))
            self.assertEqual(rational(constant[key], "MD分子", "MD分母"), 0)
        self.assertFalse(constant["CCI準備済"])

    def test_100等号と上下鏡像および最古TP脱落を厳密に保存する(self) -> None:
        """同じ現在平均で100となる窓を、前方の大価格から切り離す。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。MD2/CCI±100と最後20番号が反射でも一致する。
        """
        frames = from_closes([999.]+[100.]*17+[117.,80.,103.])
        current = rows_of(frames)[-1]["CCI現"]
        mirror = rows_of(reflect(frames))[-1]["CCI現"]
        self.assertEqual(rational(current), 100)
        self.assertEqual(rational(current, "平均分子", "平均分母"), 100)
        self.assertEqual(rational(current, "MD分子", "MD分母"), 2)
        self.assertEqual(current["足番号"], list(range(1,21)))
        self.assertEqual(rational(mirror), -100)
        self.assertEqual(rational(mirror, "MD分子", "MD分母"), 2)
        self.assertEqual(rational(mirror, "平均分子", "平均分母"), 1900)

    def test_3分は当場21公開で15分BBだけ数値carryし限月尾部で解除する(self) -> None:
        """場をまたぐ数値と当場の準備を混同しない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。3分CCIは未準備、15分BBは前場窓から更新可。
        """
        lower_bank, upper_bank = J.NumericBank(3), J.NumericBank(15)
        lower_bank.build(lower_golden(), "前場", CONTRACT)
        upper_bank.build(upper_golden(), "前場", CONTRACT)
        fresh3 = lower_bank.build(from_closes([130.]), SESSION, CONTRACT)[0][0]
        fresh15 = upper_bank.build(from_closes([120.,130.],15,0.), SESSION, CONTRACT)[0]
        self.assertIsNone(fresh3["CCI現"])
        self.assertTrue(math.isfinite(fresh3["atr"]) and fresh3["atr"] > 0)
        self.assertTrue(all(row["BB準備済"] for row in fresh15))
        self.assertTrue(any(ref["場"] == "前場" for ref in fresh15[0]["BB窓出典"]))
        reset = upper_bank.build(from_closes([140.],15,0.), "新限月場", ("別限月",))[0][0]
        self.assertFalse(reset["BB準備済"])
        upper_bank.build(upper_golden(), "尾部場", CONTRACT, tail_missing=1)
        self.assertFalse(upper_bank.build(from_closes([150.],15,0.), SESSION, CONTRACT)[0][0]["BB準備済"])

    def test_missing当足不投入と番号飛越missing0新種とNP数値更新を分ける(self) -> None:
        """CCI局所窓の開始位置とATR/15分BBの更新用途を区別する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。missing/NP足をCCI20へ紛れ込ませない。
        """
        for mode in ("missing", "番号欠", "NP", "不正"):
            frames = from_closes([float(100+i) for i in range(43)])
            if mode == "missing":
                frames[21]["missing"] = 1
            elif mode == "番号欠":
                for row in frames[21:]:
                    row["index"] += 1
            elif mode == "NP":
                frames[21]["publish"] = False
            else:
                frames[21]["low"] = frames[21]["high"]+1
            rows = rows_of(frames)
            seed = 21 if mode == "番号欠" else 22
            self.assertIsNone(rows[seed+18]["CCI現"])
            self.assertEqual(rows[seed+19]["CCI現"]["足番号"][0], frames[seed]["index"])
            if mode == "NP":
                self.assertTrue(math.isfinite(rows[21]["atr"]))
        upper_bank = J.NumericBank(15)
        frames = upper_golden()
        frames[-1]["publish"] = False
        rows = upper_bank.build(frames, "前場", CONTRACT)[0]
        self.assertTrue(rows[-1]["BB準備済"])
        self.assertTrue(upper_bank.build(from_closes([120.],15,0.), SESSION, CONTRACT)[0][0]["BB準備済"])


class 価格とCCIと上位公開検証(unittest.TestCase):
    """原P・共通準備・CCI値・上位幅・公開時点を分けて調べる。"""

    def test_価格は前20高安への終値strict突破だけでcurrentを含めない(self) -> None:
        """正常突破・終値等号・ヒゲだけを独立の価格例で区別する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。元価格rawはCCIや上位値の後に作らない。
        """
        signals, quality = generate()
        self.assertEqual(tuple(map(len,signals.values())), (1,1))
        self.assertEqual(quality["原価格発動数"],1)
        for mode in ("終値等号", "ヒゲのみ"):
            frames = lower_golden()
            frames[-1].update(high=121., low=119., close=119.)
            if mode == "終値等号":
                frames[-1]["high"] = 119.
            self.assertEqual(generate(rows_of(frames))[1]["原価格発動数"],0)

    def test_現前CCI二条件は非冗長で100等号も両案から除く(self) -> None:
        """前だけ強い例・現だけ強い例・前100等号を生価格から作る。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。価格突破を保持し、CCIを独立した二票とは数えない。
        """
        examples = []
        frames = from_closes([100.]*19+[110.,115.])
        frames[-1]["low"] = 75.
        examples.append((frames,Fraction(2000,3),Fraction(13000,189)))
        examples.append((from_closes([100.]*18+[110.,100.,115.]),Fraction(-2000,57),Fraction(11000,27)))
        examples.append((from_closes([100.]*17+[117.,80.,103.,120.]),Fraction(100),None))
        for frames, previous, current in examples:
            for mirror in (False,True):
                used = reflect(frames) if mirror else frames
                rows = rows_of(used)
                self.assertEqual(rational(rows[-1]["CCI前"]), -previous if mirror else previous)
                if current is not None:
                    self.assertEqual(rational(rows[-1]["CCI現"]), -current if mirror else current)
                grouped,quality = generate(rows,rows_of(reflect(upper_golden()) if mirror else upper_golden()))
                self.assertEqual(quality["原価格発動数"],1)
                self.assertTrue(quality["全Q発動記録"][0]["共通M準備"])
                self.assertEqual(tuple(map(len,grouped.values())),(0,0))

    def test_上位幅拡大は51_16で等幅0と収縮はC0だけになり鏡像も同じ(self) -> None:
        """BBの母分散差を幅差と混同せず、数学等号を採用しない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。3分ではなく当場15分pairの分散を比較する。
        """
        uppers = [(upper_golden(),Fraction(51,16),True),
                  (from_closes([94.]+[100.]*19+[106.],15,0.),Fraction(0),False),
                  (from_closes([80.]+[100.]*19+[105.],15,0.),None,False)]
        for frames,delta,selected in uppers:
            for mirror in (False,True):
                grouped,quality = generate(rows_of(reflect(lower_golden()) if mirror else lower_golden()),
                    rows_of(reflect(frames) if mirror else frames))
                raw = quality["全Q発動記録"][0]
                self.assertTrue(raw["共通M準備"])
                self.assertEqual(tuple(map(len,grouped.values())), (1,1 if selected else 0))
                if delta is not None:
                    self.assertEqual(Fraction(raw["BB分散差厳密分子"],raw["BB分散差厳密分母"]),delta)
                else:
                    self.assertLess(raw["BB幅比較厳密符号"],0)

    def test_共通CCIと最新上位準備はC0にも課し旧正常へ戻らない(self) -> None:
        """原Pを消さず、CCI欠測と最新15分不準備を共通に扱う。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。新しい不準備値を無視して古い正常値で入らない。
        """
        grouped,quality = generate(rows_of(from_closes([100.]*20+[120.])))
        self.assertEqual(quality["原価格発動数"],1)
        self.assertFalse(quality["全Q発動記録"][0]["共通M準備"])
        self.assertEqual(tuple(map(len,grouped.values())),(0,0))
        upper = rows_of(upper_golden())
        upper[-1].update(BB準備済=False,BB平均=None,BB標準偏差=None,BB幅=None,BB分散分子=None,BB分散分母=None)
        grouped,quality = generate(higher=upper)
        raw = quality["全Q発動記録"][0]
        self.assertEqual(raw["上位参照"]["index"],20)
        self.assertFalse(raw["共通M準備"])
        self.assertEqual(tuple(map(len,grouped.values())),(0,0))

    def test_上位asofは同時刻原行までと下位足終了以前の両方を要求する(self) -> None:
        """key等号は可、同秒後行と下位終了より後の上位は不可とする。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。上位足の後からの公開を過去の3分判断へ流さない。
        """
        lower = rows_of(lower_golden())
        for offset in (0,1):
            upper = rows_of(upper_golden())
            upper[-1].update(confirm=lower[-1]["confirm"],confirm_line=lower[-1]["confirm_line"]+offset)
            grouped,quality = generate(lower,upper)
            raw=quality["全Q発動記録"][0]
            self.assertEqual(raw["上位参照"]["index"],20 if not offset else 19)
            self.assertEqual(tuple(map(len,grouped.values())),(1,1) if not offset else (0,0))
        upper = rows_of(from_closes([95.]*10+[105.]*10+[110.],15,900.))
        lower[-1]["confirm"] = upper[-1]["confirm"]+30.
        raw=generate(lower,upper)[1]["全Q発動記録"][0]
        self.assertEqual(raw["上位参照"]["index"],19)
        self.assertFalse(raw["確認遅延条件可"])

    def test_上位は当場隣接pairのみで前場数値carryを局所前足にしない(self) -> None:
        """BB数値が有効でも、当場一足だけ/間のNP/番号飛越はpair不可。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。準備不足をC1の幅収縮効果へ混ぜない。
        """
        bank=J.NumericBank(15)
        bank.build(upper_golden(),"前場",CONTRACT)
        current=bank.build(from_closes([120.],15,18000.),SESSION,CONTRACT)[0]
        self.assertTrue(current[0]["BB準備済"])
        grouped,quality=generate(higher=current)
        self.assertFalse(quality["全Q発動記録"][0]["共通M準備"])
        self.assertEqual(tuple(map(len,grouped.values())),(0,0))
        for mode in ("欠番号","NP","missing"):
            upper=rows_of(upper_golden())
            if mode == "欠番号":
                upper.pop(-2)
            elif mode == "NP":
                upper[-2]["publish"]=False
            else:
                upper[-2]["missing"]=1
            grouped,quality=generate(higher=upper)
            self.assertFalse(quality["全Q発動記録"][0]["共通M準備"])
            self.assertEqual(tuple(map(len,grouped.values())),(0,0))

    def test_原価格窓は当場公開連続21足で未来の追加にも不変(self) -> None:
        """価格窓のNP/欠枠をまたがず、後続足で既存contextを変えない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。原Pと全採否は同じ判断時点の値に固定される。
        """
        for mode in ("NP","missing","番号欠"):
            lower=rows_of(lower_golden())
            if mode == "NP": lower[10]["publish"]=False
            elif mode == "missing": lower[10]["missing"]=1
            else:
                for row in lower[10:]: row["index"]+=1
            self.assertEqual(generate(lower)[1]["原価格発動数"],0)
        lower,upper=rows_of(lower_golden()),rows_of(upper_golden())
        before=generate(lower,upper)[1]
        future_lower=rows_of(from_closes([float(100+i) for i in range(22)]))
        future_upper=rows_of(from_closes([95.]*10+[105.]*10+[110.,120.],15,0.))
        after=generate(future_lower,future_upper)[1]
        self.assertEqual(before["全Q発動記録"],after["全Q発動記録"][:1])
        self.assertEqual(before["複合context記録"],after["複合context記録"][:21])

    def test_時間と遅延でrawを消さず全採否snapshotは二案から独立する(self) -> None:
        """時間・遅延・残り時間とdeepcopyの境界を人工で調べる。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。未来ラベルやcaseの後変更を元rawへ漏らさない。
        """
        for mode in ("停止等号","残り不足","遅延超","境界可"):
            lower=rows_of(lower_golden())
            now,cutoff,deadline=lower[-1]["confirm"],100000.,200000.
            if mode == "停止等号": cutoff=now
            elif mode == "残り不足": deadline=now+3599.
            elif mode == "遅延超": lower[-1]["confirm"]+=31.
            else:
                lower[-1]["confirm"]+=30.
                deadline=lower[-1]["confirm"]+3600.
            grouped,quality=generate(lower,cutoff=cutoff,deadline=deadline)
            self.assertEqual(quality["原価格発動数"],1)
            self.assertEqual(quality["全Q発動記録"][0]["先着評価対象"],mode=="境界可")
            self.assertEqual(tuple(map(len,grouped.values())),(1,1) if mode=="境界可" else (0,0))
        lower,upper=rows_of(lower_golden()),rows_of(upper_golden())
        original=deepcopy((lower,upper))
        grouped,quality=generate(lower,upper)
        raw=quality["全Q発動記録"][0]
        self.assertEqual(grouped["3分_C0"][0]["戦略判定"],raw["戦略判定"])
        grouped["3分_C0"][0]["戦略判定"]["C1"]["理由"].append("人工変更")
        self.assertNotIn("人工変更",raw["戦略判定"]["C1"]["理由"])
        self.assertNotIn("人工変更",grouped["3分_C1"][0]["戦略判定"]["C1"]["理由"])
        self.assertEqual((lower,upper),original)


class 独立人工比較検証(unittest.TestCase):
    """主とは別の原窓再走査へ、人工数値・全context・採否を照合する。"""

    def test_独立原窓再走査でもCCI分数と上位分散差と全採否が同じになる(self) -> None:
        """明示期待値に加え、主をimportしない独立APIへ全人工出典を比較する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。ATRだけabs1e−10、その他は厳密同値。
        """
        independent=load(HERE/"状態独立確認.py","CCI合成の独立原窓")

        def compare(left: Any, right: Any, path: str = "") -> None:
            """ネストした人工保存値を、ATRだけ既定許容で比較する。

            引数: left/right(Any)は主/独立の値、path(str)は検査箇所。
            返り値: None。不一致はunittestの失敗として残す。
            """
            if isinstance(left,dict) and isinstance(right,dict):
                self.assertEqual(set(left),set(right),path)
                for key in left:
                    compare(left[key],right[key],path+"/"+str(key))
            elif isinstance(left,(list,tuple)) and isinstance(right,(list,tuple)):
                self.assertEqual(len(left),len(right),path)
                for index,(a,b) in enumerate(zip(left,right)):
                    compare(a,b,path+"/"+str(index))
            elif path.endswith("/atr") and left is not None and right is not None:
                self.assertLessEqual(abs(left-right),1e-10,path)
                self.assertEqual(max(5,math.ceil(left/5)*5),max(5,math.ceil(right/5)*5),path)
            else:
                self.assertEqual(left,right,path)

        for mirrored in (False,True):
            lower=reflect(lower_golden()) if mirrored else lower_golden()
            higher=reflect(upper_golden()) if mirrored else upper_golden()
            main_lower,main_higher=rows_of(lower),rows_of(higher)
            other_lower=independent.NumericHistory(3).build(lower,SESSION,CONTRACT)[0]
            other_higher=independent.NumericHistory(15).build(higher,SESSION,CONTRACT)[0]
            compare(main_lower,other_lower)
            compare(main_higher,other_higher)
            main=generate(main_lower,main_higher)
            other=independent.generate(other_lower,other_higher,SESSION,100000.,200000.,I.expected_config())
            compare(main,other)


@contextmanager
def driver_fixture(name: str) -> Iterator[tuple[Any,Path,Path,dict]]:
    """主driverの保存先と市場抽出だけを人工先へ差し替える。

    引数: name(str)はmodule識別名。
    返り値: Iterator[tuple[Any,Path,Path,dict]]はdriver/人工study/work/場名66件。
    """
    driver=load(HERE/"検証.py",name)
    with tempfile.TemporaryDirectory(prefix="CCI主境界合成_",dir=ROOT/"work") as folder:
        study,work=Path(folder)/"study",Path(folder)/"work"
        study.mkdir()
        work.mkdir()
        (study/"条件.json").write_text(json.dumps(I.expected_config(),ensure_ascii=False),encoding="utf-8")
        pointer={"参照":str(driver.MANIFEST_PATH),"SHA256":sha(driver.MANIFEST_PATH)}
        (study/"入力台帳.json").write_text(json.dumps(pointer,ensure_ascii=False),encoding="utf-8")
        (study/"計画.md").write_text("人工固定計画\n",encoding="utf-8")
        sessions=[f"2026-09-{1+i//2:02d}_{'Day' if i%2==0 else 'Night'}" for i in range(40)]
        sessions += [f"2026-10-{20+i//2:02d}_{'Day' if i%2==0 else 'Night'}" for i in range(24)]
        sessions += ["2026-11-04_Day","2026-11-04_Night"]
        yield driver,study,work,{"entries":[{"session":session} for session in sessions]}


def driver_block(driver: Any, session: str) -> dict:
    """主driverへ当場の人工CCI/上位BBと二純入口を渡す。

    引数: driver(Any)は主module、session(str)は人工場名。
    返り値: dictは先着・会計・実原板のない当場材料。
    """
    lower,higher=rows_of(lower_golden(),session),rows_of(upper_golden(),session)
    signals,quality=driver.I.generate(lower,higher,session,100000.,200000.,I.expected_config())
    return {"events":[],"frames":{3:lower,15:higher},"signals":signals,"quality":quality,
            "numeric_quality":[],"input_quality":{"場":session},
            "cutoff":100000.,"deadline":200000.,"duration":100.}


class 主準備と固定境界検証(unittest.TestCase):
    """実資料を差し替えたprepare・ラベル分離・固定joinの境界を調べる。"""

    def test_人工66prepareは二銀行をcarryし先着会計運用を呼ばない(self) -> None:
        """実市場抽出を禁止し、二案×66の非損益準備だけを実行する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。新旧の原板/cacheをstat/openしない。
        """
        with driver_fixture("CCI合成の非損益準備") as (driver,study,work,manifest):
            self.assertEqual(len(driver.manifest_for(study,I.expected_config())["entries"]),66)
            pointer_path=study/"入力台帳.json"
            original=pointer_path.read_bytes()
            bad=json.loads(original)
            bad["SHA256"]="0"*64
            pointer_path.write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ValueError):
                driver.manifest_for(study,I.expected_config())
            pointer_path.write_bytes(original)
            bank_ids=[]

            def build(entry: dict, supplied: dict, banks: dict, supplied_config: dict) -> dict:
                """原市場の代わりに独立した人工当場を返す。

                引数: entry/supplied/banks/supplied_config(dict)は主の同署名引数。
                返り値: dictは人工当場。銀行は3/15の同じ個体が継続する。
                """
                self.assertEqual(set(banks),{3,15})
                bank_ids.append((id(banks[3]),id(banks[15])))
                return driver_block(driver,entry["session"])

            forbidden=AssertionError("prepareから先着/損益/固定へ進まない")
            with patch.object(driver,"manifest_for",return_value=manifest),patch.object(driver,"build_session",side_effect=build), \
                    patch.object(driver,"freeze",side_effect=forbidden) as freeze, \
                    patch.object(driver,"shadow_label",side_effect=forbidden) as label, \
                    patch.object(driver.W.OLD,"気配経路",side_effect=forbidden) as path, \
                    patch.object(driver.ENGINE,"replay",side_effect=forbidden) as replay, \
                    patch.object(driver.E,"entry_metrics",side_effect=forbidden) as metric, \
                    patch.object(driver,"compressed",side_effect=forbidden) as compressed, \
                    patch.object(driver.D.D.Q,"aggregate",side_effect=AssertionError("CCIで数量集約しない")) as quantity,redirect_stdout(io.StringIO()):
                driver.run(study,work,prepare_only=True)
            for guard in (freeze,label,path,replay,metric,compressed,quantity):
                guard.assert_not_called()
            proof=json.loads((work/"準備点検.json").read_text(encoding="utf-8"))
            self.assertEqual(len(proof["準備"]),66)
            self.assertEqual(len(proof["場別発動"]),132)
            self.assertEqual(len(proof["期間別発動"]),6)
            self.assertEqual(len(set(bank_ids)),1)
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertEqual(proof["参照台帳SHA256"],sha(driver.MANIFEST_PATH))
            self.assertFalse((study/"結果.json").exists())
            self.assertTrue(all(not (work/name).exists() for name in driver.FILES))

    def test_固定運用とCCI上位幅の数値文字列や候補差を拒否する(self) -> None:
        """変更した条件を主validateへ渡し、勝手な別候補を通さない。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。数値・Source式の文字列・カタログ版の全一致を要求。
        """
        config=I.expected_config()
        locations=[(None,"逆行pt"),(None,"順行pt"),(None,"カタログ版"),(None,"戦略"),
            ("運用","片道手数料円"),("必須追尾","起動幅pt"),
            *[("CCI突破",key) for key in config["CCI突破"]]]
        for section,key in locations:
            changed=deepcopy(config)
            target=changed if section is None else changed[section]
            value=target[key]
            target[key]=value+"人工差" if isinstance(value,str) else value+1 if isinstance(value,(int,float)) else []
            with self.assertRaises(ValueError):
                I.validate_config(changed)

    def test_未来labelは保存caseにだけ付き運用の二純signalへ混入しない(self) -> None:
        """人工labelと空運用を使い、二候補目の受渡しで停止する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。未来値をENTRY又は運用条件へ参照させない。
        """
        with driver_fixture("CCI合成の純signal受渡し") as (driver,study,work,manifest):
            entry=manifest["entries"][0]
            manifest["entries"]=[entry]
            block=driver_block(driver,entry["session"])
            original=deepcopy(block["signals"])
            received=[]

            def replay(events: list, signals: list, rows: list, session: str, cid: str, *args: object) -> tuple:
                """二案のlabelなしsignalを記録して二案目で終了する。

                引数: events/signals/rows(list)は人工列、session/cid(str)は場/案、args(object)は固定運用設定。
                返り値: tupleは空運用。二案目では停止用RuntimeError。
                """
                self.assertEqual(args[-1],"順行")
                received.append((cid,deepcopy(signals)))
                if len(received)==2:
                    raise RuntimeError("人工二案受渡し完了")
                return SimpleNamespace(trades=[],normal_log=[],fills=[],orders=[],signals=[]),{}

            future={"ラベル":"人工未来","最大順行pt":999.,"人工未来値":12345}
            with patch.object(driver,"manifest_for",return_value=manifest),patch.object(driver,"build_session",return_value=block), \
                    patch.object(driver,"freeze",return_value={}),patch.object(driver.W.OLD,"気配経路",return_value=object()), \
                    patch.object(driver,"shadow_label",return_value=future),patch.object(driver.ENGINE,"replay",side_effect=replay),redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,"人工二案受渡し完了"):
                    driver.run(study,work,prepare_only=False)
            self.assertEqual([cid for cid,_ in received],["3分_C0_X0","3分_C1_X0"])
            for cid,signals in received:
                self.assertEqual(len(signals),1)
                self.assertTrue(all(key not in signals[0] for key in future))
                self.assertEqual(signals[0]["期間"],"学習")
                self.assertIn("要求時計JST",signals[0])
                self.assertEqual({key:value for key,value in signals[0].items() if key not in ("期間","要求時計JST")},original[cid.removesuffix("_X0")][0])
            with gzip.open(work/"入口事例.jsonl.gz","rt",encoding="utf-8") as stream:
                cases=[json.loads(line) for line in stream]
            self.assertEqual(len(cases),2)
            self.assertTrue(all(case["人工未来値"]==12345 for case in cases))
            self.assertFalse((study/"結果.json").exists())

    def test_独立準備joinは未完旧版差有を拒否し固定後差と既存結果も拒否する(self) -> None:
        """人工proofだけで主・独立・合成のbindと固定不変を確認する。

        引数: self(TestCase)は検証インスタンス。
        返り値: None。正式proof/条件/固定を書き換えず、同じ失敗境界を通す。
        """
        with driver_fixture("CCI合成の独立準備固定join") as (driver,study,work,manifest):
            prepare={"コードSHA256":driver.code_pins(),"条件SHA256":sha(study/"条件.json"),
                "入力台帳SHA256":sha(study/"入力台帳.json"),"参照台帳SHA256":sha(driver.MANIFEST_PATH)}
            (work/"準備点検.json").write_text(json.dumps(prepare),encoding="utf-8")
            with self.assertRaises(ValueError):
                driver.validate_independent(study,work)
            dependency=ROOT/"scripts/一目基準線/状態独立確認.py"
            independent={"全件一致":True,"不一致数":0,"不一致":[],"ラベル計算":False,"損益計算":False,
                "主準備SHA256":sha(work/"準備点検.json"),"主コードSHA256":driver.code_pins(),
                "条件SHA256":sha(study/"条件.json"),"入力台帳SHA256":sha(study/"入力台帳.json"),
                "参照入力台帳SHA256":sha(driver.MANIFEST_PATH),"コードSHA256":sha(HERE/"状態独立確認.py"),
                "追尾コードSHA256":sha(HERE/"追尾独立確認.py"),
                "依存コードSHA256":{dependency.relative_to(ROOT).as_posix():sha(dependency)}}
            independent_path=work/"独立準備点検.json"
            for key in ("全件一致","不一致数","不一致","ラベル計算","損益計算","主準備SHA256", "主コードSHA256",
                        "条件SHA256","入力台帳SHA256","参照入力台帳SHA256","コードSHA256","追尾コードSHA256","依存コードSHA256"):
                bad=deepcopy(independent)
                if key=="全件一致": bad[key]=False
                elif key=="不一致数": bad[key]=1
                elif key=="不一致": bad[key]=["人工不一致"]
                elif key in ("ラベル計算","損益計算"): bad[key]=True
                elif key=="依存コードSHA256": bad[key]={dependency.relative_to(ROOT).as_posix():"0"*64}
                else: bad[key]="0"*64
                independent_path.write_text(json.dumps(bad),encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.validate_independent(study,work)
            independent_path.write_text(json.dumps(independent),encoding="utf-8")
            self.assertEqual(driver.validate_independent(study,work),independent)

            # ----------------------------------------
            # 最終合成だけを人工proofへ差し替え、正式proofを作成しない。
            paths=[HERE/name for name in ("指標.py","入口.py","検証.py","合成検証.py")]+[study/"条件.json"]
            synthetic={"全件成功":True,"合成編集終了":False,
                "ファイルSHA256":{path.relative_to(ROOT).as_posix():sha(path) for path in paths}}
            synthetic_path=work/"人工合成proof.json"
            canonical=WORK/"合成検証.json"
            read_original,sha_original=driver.W.read_json,driver.O.sha

            def read(path: Path) -> dict:
                """主が読む合成proofだけを人工辞書に置き換える。

                引数: path(Path)は読込先。
                返り値: dictは人工合成又は既存の正本。
                """
                return deepcopy(synthetic) if path==canonical else read_original(path)

            def digest(path: Path) -> str:
                """人工合成のSHAだけを人工ファイルから取得する。

                引数: path(Path)は指紋対象。
                返り値: strは人工又は変更しない既存ファイルのSHA。
                """
                return sha(synthetic_path) if path==canonical else sha_original(path)

            synthetic_path.write_text(json.dumps(synthetic),encoding="utf-8")
            with patch.object(driver.W,"read_json",side_effect=read),patch.object(driver.O,"sha",side_effect=digest):
                with self.assertRaises(ValueError):
                    driver.freeze(study,work)
                synthetic["合成編集終了"]=True
                synthetic_path.write_text(json.dumps(synthetic),encoding="utf-8")
                fixed=driver.freeze(study,work)
                self.assertEqual(driver.freeze(study,work),fixed)
                self.assertEqual(fixed["独立準備SHA256"],sha(independent_path))
                for path in (HERE/"状態独立確認.py",HERE/"追尾独立確認.py",dependency,*driver.EXTRA_SOURCES):
                    self.assertEqual(fixed["ファイルSHA256"][path.relative_to(ROOT).as_posix()],sha(path))
                (study/"計画.md").write_text("人工固定後差\n",encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(study,work)
            result=study/"結果.json"
            result.write_text('{"人工既存結果":true}',encoding="utf-8")
            before=result.read_bytes()
            with patch.object(driver,"manifest_for",return_value=manifest), \
                    patch.object(driver,"build_session",side_effect=AssertionError("既存結果後は数値禁止")) as build:
                with self.assertRaises(ValueError):
                    driver.run(study,work,prepare_only=False)
            build.assert_not_called()
            self.assertEqual(result.read_bytes(),before)


def main() -> None:
    """人工境界だけを実行し、確定時に5pinsと独立補助版を保存する。

    引数: なし。CLIの--finalは全実装/条件/独立補助のroot最終確認後だけ指定する。
    返り値: None。実資料の先着・損益・prepare・主再生を起動しない。
    """
    parser=argparse.ArgumentParser(description="CCI持続と上位BB公開時点の人工検査")
    parser.add_argument("--final",action="store_true")
    arguments=parser.parse_args()
    paths=[HERE/name for name in ("指標.py","入口.py","検証.py","合成検証.py")]+[STUDY/"条件.json"]
    if any(not path.is_file() for path in paths):
        raise ValueError("主3コード/合成/条件の確定を待つ")
    pins={path.relative_to(ROOT).as_posix():sha(path) for path in paths}
    independent_sha=sha(HERE/"状態独立確認.py")
    stream=io.StringIO()
    with deny_market():
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    unchanged=pins=={path.relative_to(ROOT).as_posix():sha(path) for path in paths} and independent_sha==sha(HERE/"状態独立確認.py")
    success=result.wasSuccessful() and result.testsRun>0 and unchanged
    proof={"全件成功":success,"検証件数":result.testsRun,"合成編集終了":bool(arguments.final and success),
        "実資料の先着損益計算":False,"ファイルSHA256":pins,"独立数値補助SHA256":independent_sha,
        "実行中コード条件不変":unchanged,
        "範囲":"元HLC FractionのTP/同じ現在20平均のMD/3÷200、MD0、±100strict/鏡像/古値脱落/現前21本、現前非冗長、3分局所とATR/15分BB数値carry/欠枠NP/限月/尾部、原PとM/値/time分離、当場上位pair/end-key asof/最新不準備、Fraction母分散差51÷16/0/負、全採否deepcopy/未来prefix、独立原窓・二純入口/context、人工66非label/PnL準備・運用signalラベル非混入・固定条件/独立準備join/既存結果拒否。ATRのみabs1e−10とD整数、その他値/時点/出典/採否strict。実原板/work内npzはstat/open禁止。",
        "失敗":[{"検証":str(case),"内容":message} for case,message in result.failures],
        "エラー":[{"検証":str(case),"内容":message} for case,message in result.errors],"実行記録":stream.getvalue()}
    WORK.mkdir(parents=True,exist_ok=True)
    output=WORK/("合成検証.json" if arguments.final else "合成検証_途中.json")
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({key:proof[key] for key in ("全件成功","検証件数","合成編集終了","実資料の先着損益計算","実行中コード条件不変")},ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__=="__main__":
    main()


