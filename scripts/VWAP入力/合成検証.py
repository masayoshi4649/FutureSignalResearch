"""配信VWAP入力の時計・整合・起算を人工行だけで検査する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00017_配信元VWAPと売買代金の入力監査"
WORK = ROOT/"work/VWAP入力"


def load() -> object:
    """専有抽出監査モジュールをコマンド行実行せず読み込む。

    引数: なし。
    返り値: object は純粋APIを持つモジュール。原板やキャッシュを読み取らない。
    """
    spec = importlib.util.spec_from_file_location("VWAP入力の合成対象", HERE/"抽出監査.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


M = load()


def clock(text: str) -> float:
    """タイムゾーン付きの合成時計を秒へ変換する。

    引数: text (str) はISO形式時計。
    返り値: float はUnix秒。
    """
    return datetime.fromisoformat(text).timestamp()


def record(price_time: str = "2026-11-04T08:45:00+09:00", **updates: object) -> dict:
    """正の累積数量と比率整合値を持つ人工原板行を作る。

    引数: price_time (str) は価格時計、updates (object) は列名別の上書き値。
    返り値: dict は外部データを含まない原板形式の行。
    """
    value = {"Symbol": "169120018", "CurrentPriceTime": price_time, "CurrentPrice": 60000,
             "TradingVolume": 100, "TradingVolumeTime": price_time, "VWAP": 60000,
             "TradingValue": 6000000000, "OpeningPrice": 59900,
             "OpeningPriceTime": "2026-11-03T17:00:00+09:00", "Exchange": 2, "ExchangeName": "合成市場"}
    value.update(updates)
    return value


def arrays(rows: list[dict]) -> tuple[dict, list[str], list[dict]]:
    """人工原板行を実parse_recordとas_arraysへ通す。

    引数: rows (list[dict]) は物理行順の人工行。
    返り値: tuple[dict,list[str],list[dict]] は列配列と銘柄/市場辞書。
    """
    codes, exchanges, cache, parsed = [], [], {}, []
    for number, row in enumerate(rows, 1):
        parsed.append(M.parse_record(deepcopy(row), number, cache, codes, exchanges))
    return M.as_arrays(parsed), codes, exchanges


def condition() -> dict:
    """今回の条件正本を合成へ読み込む。

    引数: なし。
    返り値: dict は00017の条件。市場行や監査結果は読まない。
    """
    return json.loads((STUDY/"条件.json").read_text(encoding="utf-8"))


def audit(rows: list[dict], session: str = "2026-11-04_Day") -> dict:
    """人工原板を抽出して純粋監査APIへ渡す。

    引数: rows (list[dict]) は人工行、session (str) は場名。
    返り値: dict は時計・内部整合・起算の監査。外部の原板は参照しない。
    """
    data, codes, _ = arrays(rows)
    return M.audit_arrays(data, session, codes, condition())


def cumulative(price_time: str, quantity: float, value: float, **updates: object) -> dict:
    """数量と代金を指定した内部整合の人工行を作る。

    引数: price_time (str) は時計、quantity/value (float) は累積、updates (object) は上書き列。
    返り値: dict は人工行。量0の場合の配信VWAP0は計算対象外の入力として置く。
    """
    return record(price_time, TradingVolume=quantity, TradingValue=value,
                  VWAP=value/quantity/1000 if quantity > 0 else 0, **updates)


# ----------------------------------------
# 従来キャッシュにない列も、原行の時計と単独更新を保って抽出する。

class 抽出列検証(unittest.TestCase):
    """人工原板から小列への保持を確認する。"""

    def test_時計と配信列を保持する(self) -> None:
        """配信値・代金・数量・始値時計・銘柄を保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        data, codes, exchanges = arrays([record()])
        self.assertEqual(float(data["now"][0]), clock("2026-11-04T08:45:00+09:00"))
        self.assertEqual(float(data["volume_time"][0]), float(data["now"][0]))
        self.assertEqual(float(data["native_vwap"][0]), 60000)
        self.assertEqual(float(data["trading_value"][0]), 6000000000)
        self.assertEqual(float(data["opening_time"][0]), clock("2026-11-03T17:00:00+09:00"))
        self.assertEqual(codes[int(data["contract"][0])], "169120018")
        self.assertEqual(exchanges[int(data["exchange"][0])], {"Exchange": 2, "ExchangeName": "合成市場"})
        self.assertEqual(int(data["line"][0]), 1)

    def test_同秒の配信値だけの更新を失わない(self) -> None:
        """Lastと量が同一の原行でも配信VWAP更新を保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        data, _, _ = arrays([record(), record(VWAP=60001)])
        self.assertEqual(len(data["now"]), 2)
        self.assertEqual(list(data["line"]), [1, 2])
        self.assertEqual(list(data["native_vwap"]), [60000, 60001])

    def test_代金と始値と銘柄だけの更新も保持(self) -> None:
        """価格以外の更新を旧cacheの有無で消さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        data, codes, _ = arrays([record(), record(TradingValue=6000001000), record(OpeningPrice=59800), record(Symbol="169030018")])
        self.assertEqual(len(data["now"]), 4)
        self.assertEqual(list(data["line"]), [1, 2, 3, 4])
        self.assertEqual(float(data["trading_value"][1]), 6000001000)
        self.assertEqual(float(data["opening_price"][2]), 59800)
        self.assertEqual(codes[int(data["contract"][3])], "169030018")

    def test_欠測時計と数値を未来やゼロで補わない(self) -> None:
        """欠測はNaNとし現在時計や0を補わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        data, _, _ = arrays([record(CurrentPriceTime=None, TradingVolumeTime=None, VWAP=None, TradingValue=None, OpeningPriceTime=None)])
        for name in ("now", "volume_time", "native_vwap", "trading_value", "opening_time"):
            self.assertTrue(math.isnan(float(data[name][0])), name)

    def test_小数秒と原物理行を保存する(self) -> None:
        """同じ秒でも小数と物理行を秒整数へ丸めない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        codes, exchanges, cache = [], [], {}
        source = record("2026-11-04T08:45:00.125+09:00")
        event = M.parse_record(source, 127, cache, codes, exchanges)
        data = M.as_arrays([event])
        self.assertEqual(float(data["now"][0]), clock("2026-11-04T08:45:00.125+09:00"))
        self.assertEqual(int(data["line"][0]), 127)

    def test_欠測銘柄を別の実銘柄として補わない(self) -> None:
        """銘柄欠測は辞書の有効インデックスへ置換しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        data, codes, _ = arrays([record(Symbol=None)])
        self.assertEqual(int(data["contract"][0]), -1)
        self.assertNotIn("None", codes)

    def test_始値時計と市場表示だけの更新を保持する(self) -> None:
        """Lastや累積が同じでも起算・市場属性の更新を保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        data, _, exchanges = arrays([record(), record(OpeningPriceTime="2026-11-04T08:45:00+09:00"),
                                    record(Exchange=3), record(ExchangeName="別の合成市場")])
        self.assertEqual(len(data["now"]), 4)
        self.assertEqual(float(data["opening_time"][1]), clock("2026-11-04T08:45:00+09:00"))
        self.assertEqual(exchanges[int(data["exchange"][2])]["Exchange"], 3)
        self.assertEqual(exchanges[int(data["exchange"][3])]["ExchangeName"], "別の合成市場")


# ----------------------------------------
# 比率の内部整合は、時計採否と異なる母集団の検査として照合する。

class 内部整合検証(unittest.TestCase):
    """固定換算と許容・原行重みの手計算を確認する。"""

    def test_固定係数と完全一致を確認する(self) -> None:
        """代金60億/100枚/1000が60000になる既知例を確認する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record()])
        self.assertEqual(result["内部整合"]["比較原行数"], 1)
        self.assertEqual(result["内部整合"]["不整合原行数"], 0)
        self.assertEqual(result["内部整合"]["最大絶対差pt"], 0)
        self.assertIsNone(result["内部整合"]["最初不整合"])

    def test_許容と浮動余裕の内外を区別する(self) -> None:
        """絶対1e-4と余裕1e-8を合わせた実float境界を検査する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        tolerance = 0.0001+0.00000001
        inside = math.nextafter(60000+tolerance, 60000)
        outside = math.nextafter(60000+tolerance, math.inf)
        self.assertLessEqual(inside-60000, tolerance)
        self.assertGreater(outside-60000, tolerance)
        result = audit([record(VWAP=inside), record(VWAP=outside)])
        self.assertEqual(result["内部整合"]["比較原行数"], 2)
        self.assertEqual(result["内部整合"]["不整合原行数"], 1)
        self.assertEqual(result["内部整合"]["最初不整合"]["line"], 2)

    def test_倍率や許容を実行時に変更しない(self) -> None:
        """mini倍率混入や不整合を消す許容拡大を拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        data, codes, _ = arrays([record()])
        for key, value in (("ラージ換算係数", 100), ("絶対許容pt", .01), ("浮動余裕pt", 0)):
            with self.subTest(設定=key):
                config = condition()
                config[key] = value
                with self.assertRaises(ValueError):
                    M.audit_arrays(data, "2026-11-04_Day", codes, config)

    def test_ゼロ負欠測非有限は比較可能性を分ける(self) -> None:
        """分母0や不正配信値を0誤差とせず、代金0は比較して不整合とする。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rows = [record(TradingVolume=0), record(TradingVolume=-1), record(VWAP=0), record(VWAP=-1),
                record(VWAP=None), record(VWAP=math.inf), record(TradingValue=-1), record(TradingValue=math.nan),
                record(TradingValue=0)]
        result = audit(rows)
        self.assertEqual(result["内部整合"]["比較原行数"], 1)
        self.assertEqual(result["内部整合"]["不整合原行数"], 1)
        self.assertEqual(result["数値列"]["volume"]["ゼロ"], 1)
        self.assertEqual(result["数値列"]["native_vwap"]["欠測または非有限"], 2)
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_repeat原行重みと分位の手計算(self) -> None:
        """誤差0が5行・1が1行・2が4行の中央値0.5を確認する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        data, codes, _ = arrays([record(), record(VWAP=60001), record(VWAP=60002)])
        data["repeat"][:] = [5, 1, 4]
        data["line"][:] = [1, 6, 7]
        result = M.audit_arrays(data, "2026-11-04_Day", codes, condition())
        self.assertEqual(result["件数"]["原行重み合計"], 10)
        self.assertEqual(result["内部整合"]["比較原行数"], 10)
        self.assertEqual(result["内部整合"]["不整合原行数"], 5)
        self.assertEqual(result["内部整合"]["分位点"], {"0.5": .5, "0.95": 2, "0.99": 2, "1.0": 2})
        self.assertEqual(result["件数"]["同一価格時計隣接原行数"], 9)

    def test_価格時計不明でも内部比率の母集団には残す(self) -> None:
        """時計不明は利用候補から外し内部整合の数値比較は保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record(CurrentPriceTime=None)])
        self.assertEqual(result["内部整合"]["比較原行数"], 1)
        self.assertEqual(result["件数"]["価格時計欠測除外原行数"], 1)
        self.assertIsNone(result["起算"]["最初場内"])


# ----------------------------------------
# 当時利用可能な時計だけを基準へ採用し、後続行から過去へ戻さない。

class 時計検証(unittest.TestCase):
    """同秒原行・価格時計後退・数量時計先行の境界を検査する。"""

    def test_同時計の後続原行の状態を保持する(self) -> None:
        """価格時計が同じでも後続行の配信値を別状態として監査する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record(), record(VWAP=60001)])
        self.assertEqual(result["件数"]["保存状態数"], 2)
        self.assertEqual(result["件数"]["同一価格時計隣接原行数"], 1)
        self.assertEqual(result["内部整合"]["最初不整合"]["line"], 2)

    def test_原行後退重複とrepeat重なりを拒否する(self) -> None:
        """同秒の原行後退だけでなく圧縮区間の重なりも拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for lines, repeats in (([2, 1], [1, 1]), ([1, 1], [1, 1]), ([1, 3], [3, 1])):
            with self.subTest(原行=lines, 圧縮=repeats):
                data, codes, _ = arrays([record(), record()])
                data["line"][:] = lines
                data["repeat"][:] = repeats
                with self.assertRaises(ValueError):
                    M.audit_arrays(data, "2026-11-04_Day", codes, condition())

    def test_隣接後退と最大キーからの除外を分ける(self) -> None:
        """一回の後退後に増えても最大時計未満の原行を除外する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        data, codes, _ = arrays([record("2026-11-04T08:46:00+09:00"), record("2026-11-04T08:45:00+09:00"), record("2026-11-04T08:45:30+09:00")])
        data["repeat"][:] = [5, 3, 2]
        data["line"][:] = [1, 6, 9]
        result = M.audit_arrays(data, "2026-11-04_Day", codes, condition())
        self.assertEqual(result["件数"]["価格時計隣接後退回数"], 1)
        self.assertEqual(result["件数"]["価格時計原行後退除外原行数"], 5)
        self.assertEqual(result["内部整合"]["比較原行数"], 10)

    def test_数量時計欠測や未来を現在値で補わない(self) -> None:
        """比率が一致しても欠測/未来の数量時計を採用累積へ入れない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record(TradingVolumeTime=None), record(TradingVolumeTime="2026-11-04T08:46:00+09:00")])
        self.assertEqual(result["内部整合"]["比較原行数"], 2)
        self.assertEqual(result["件数"]["数量時計欠測除外原行数"], 1)
        self.assertEqual(result["件数"]["数量時計先行原行数"], 1)
        self.assertEqual(result["件数"].get("採用累積原行数", 0), 0)

    def test_終端等号は場内に含めない(self) -> None:
        """現行Day/Nightザラバ終了を半開端点として扱う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for session, stamp in (("2026-11-04_Day", "2026-11-04T15:40:00+09:00"), ("2026-11-04_Night", "2026-11-05T05:55:00+09:00")):
            with self.subTest(場=session):
                result = audit([record(stamp)], session)
                self.assertEqual(result["件数"].get("場内原行数", 0), 0)
                self.assertEqual(result["件数"]["終端以後原行数"], 1)


# ----------------------------------------
# 前夜累積をそのまま日中起算とせず、既知接頭基準がある範囲だけ差し引く。

class 起算検証(unittest.TestCase):
    """既知基準・直接ゼロ・区間変更による失効を確認する。"""

    def test_前夜継続を既知基準から差し引く(self) -> None:
        """累積120と代金72.1億から基準100と60億を引き60500を得る。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([cumulative("2026-11-04T06:00:00+09:00", 100, 6000000000), cumulative("2026-11-04T08:45:00+09:00", 120, 7210000000)])
        origin = result["起算"]
        self.assertEqual(origin["既知接頭基準"]["line"], 1)
        self.assertEqual(origin["差分計算可能原行数"], 1)
        self.assertEqual(origin["最初差分例"]["差分数量"], 20)
        self.assertEqual(origin["最初差分例"]["差分代金"], 1210000000)
        self.assertEqual(origin["最初差分例"]["差分VWAP"], 60500)
        self.assertEqual(origin["始値起算分類"]["当場前の始値時計"], 1)

    def test_接頭がなければ始値だけからゼロを推定しない(self) -> None:
        """当場の始値時計があっても正の最初累積を0起算へ補わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record(OpeningPriceTime="2026-11-04T08:45:00+09:00"), record("2026-11-04T08:46:00+09:00", TradingVolume=120, TradingValue=7200000000, OpeningPriceTime="2026-11-04T08:45:00+09:00")])
        self.assertIsNone(result["起算"]["既知接頭基準"])
        self.assertEqual(result["起算"]["差分計算可能原行数"], 0)
        self.assertFalse(result["起算"]["推定ゼロを差分基準へ補完"])

    def test_接頭基準は両時計が閉場後窓の中だけ(self) -> None:
        """価格/数量の片方だけが閉場後でも基準へ採用しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for price, volume in (("2026-11-04T05:59:59+09:00", "2026-11-04T05:59:59+09:00"),
                              ("2026-11-04T06:00:00+09:00", "2026-11-04T05:59:59+09:00"),
                              ("2026-11-04T06:00:00+09:00", "2026-11-04T08:45:00+09:00")):
            with self.subTest(価格=price, 数量=volume):
                result = audit([record(price, TradingVolumeTime=volume), record()])
                self.assertIsNone(result["起算"]["既知接頭基準"])
                self.assertEqual(result["起算"]["差分計算可能原行数"], 0)

    def test_Nightの接頭下限を15時45分とする(self) -> None:
        """夜間も開場前の既知累積を同じ定義で扱う。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record("2026-11-04T15:45:00+09:00"), record("2026-11-04T17:00:00+09:00", TradingVolume=120, TradingValue=7200000000)], "2026-11-04_Night")
        self.assertIsNotNone(result["起算"]["既知接頭基準"])
        self.assertEqual(result["起算"]["最初差分例"]["差分VWAP"], 60000)

    def test_場内後に現れた過去接頭を遡及しない(self) -> None:
        """物理順で後から届いた過去時計を既知基準に使わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record(), record("2026-11-04T06:00:00+09:00")])
        self.assertIsNone(result["起算"]["既知接頭基準"])
        self.assertEqual(result["起算"]["差分計算可能原行数"], 0)
        self.assertEqual(result["件数"]["価格時計原行後退除外原行数"], 1)

    def test_最初の場内行が未来数量時計でも既知基準を失わない(self) -> None:
        """後の利用可能行から差分を作り、接頭基準も明示して保存する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record("2026-11-04T06:00:00+09:00"),
                        record(TradingVolume=120, TradingValue=7200000000, TradingVolumeTime="2026-11-04T08:46:00+09:00"),
                        record("2026-11-04T08:46:00+09:00", TradingVolume=120, TradingValue=7200000000)])
        self.assertEqual(result["起算"]["差分計算可能原行数"], 1)
        self.assertIsNotNone(result["起算"]["既知接頭基準"])
        self.assertEqual(result["起算"]["最初差分例"]["line"], 3)

    def test_累積減少後は再増加しても古い基準を復活させない(self) -> None:
        """同じ始値時計のまま減少した場合も旧区間の基準を破棄する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([cumulative("2026-11-04T06:00:00+09:00", 100, 6000000000),
                        cumulative("2026-11-04T08:45:00+09:00", 120, 7200000000),
                        cumulative("2026-11-04T08:46:00+09:00", 90, 5400000000),
                        cumulative("2026-11-04T08:47:00+09:00", 130, 7800000000)])
        self.assertEqual(result["起算"]["差分計算可能原行数"], 1)
        self.assertEqual(result["起算"]["最後差分例"]["line"], 2)
        self.assertEqual(result["起算"]["基準無効化数"], 1)

    def test_始値時計価格限月市場の各単独変更で失効(self) -> None:
        """累積が減らなくても区間の識別が変われば基準を破棄する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"OpeningPriceTime": "2026-11-04T08:45:00+09:00"}, {"OpeningPrice": 59800}, {"Symbol": "169030018"}, {"Exchange": 3}):
            with self.subTest(変更=change):
                result = audit([record("2026-11-04T06:00:00+09:00"), record(**change)])
                self.assertEqual(result["起算"]["基準無効化数"], 1)
                self.assertEqual(result["起算"]["差分計算可能原行数"], 0)

    def test_開始ちょうどの直接ゼロと途中ゼロを分ける(self) -> None:
        """Night17時の直接0だけを開始基準とし途中0を全場へ補わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for stamp, expected in (("2026-11-04T17:00:00+09:00", 1), ("2026-11-04T17:00:01+09:00", 0)):
            with self.subTest(ゼロ時計=stamp):
                result = audit([cumulative(stamp, 0, 0, OpeningPriceTime="2026-11-04T17:00:00+09:00"),
                                cumulative("2026-11-04T17:01:00+09:00", 20, 1200000000, OpeningPriceTime="2026-11-04T17:00:00+09:00")], "2026-11-04_Night")
                self.assertEqual(result["起算"]["直接ゼロ観測原行数"], 1)
                self.assertEqual(result["起算"]["差分計算可能原行数"], expected)

    def test_差分分母ゼロと正分母の代金ゼロを分ける(self) -> None:
        """0除算へ0を補わず、正分母の実差分代金0は数学的0として区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for quantity, value, expected in ((100, 6000000000, None), (100, 6000001000, None), (101, 6000000000, 0)):
            with self.subTest(累積量=quantity, 代金=value):
                result = audit([cumulative("2026-11-04T06:00:00+09:00", 100, 6000000000), cumulative("2026-11-04T08:45:00+09:00", quantity, value)])
                if expected is None:
                    self.assertEqual(result["起算"]["差分計算可能原行数"], 0)
                    self.assertIsNone(result["起算"]["最初差分例"])
                else:
                    self.assertEqual(result["起算"]["最初差分例"]["差分VWAP"], expected)

    def test_identity一時欠測は保留し同じ既知値の再確認後に再開(self) -> None:
        """始値と限月と市場の欠測を不一致とせず当該行だけ除外する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for missing in ({"OpeningPriceTime": None}, {"OpeningPrice": None}, {"Symbol": None}, {"Exchange": None, "ExchangeName": None}):
            with self.subTest(欠測=missing):
                result = audit([record("2026-11-04T06:00:00+09:00"),
                                cumulative("2026-11-04T08:45:00+09:00", 120, 7200000000, **missing),
                                cumulative("2026-11-04T08:46:00+09:00", 130, 7800000000)])
                self.assertEqual(result["起算"]["基準無効化数"], 0)
                self.assertEqual(result["件数"]["場内差分基準一時未確認原行数"], 1)
                self.assertEqual(result["起算"]["差分計算可能原行数"], 1)
                self.assertEqual(result["起算"]["最初差分例"]["line"], 3)

    def test_欠測を挟んだ既知不一致は同値へ戻っても永久破棄(self) -> None:
        """直近既知identityを保存し、欠測を経由した変更も検出する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record("2026-11-04T06:00:00+09:00"),
                        cumulative("2026-11-04T08:45:00+09:00", 120, 7200000000, OpeningPrice=None),
                        cumulative("2026-11-04T08:46:00+09:00", 130, 7800000000, OpeningPrice=59800),
                        cumulative("2026-11-04T08:47:00+09:00", 140, 8400000000)])
        self.assertEqual(result["起算"]["基準無効化数"], 1)
        self.assertEqual(result["起算"]["差分計算可能原行数"], 0)
        self.assertGreaterEqual(result["件数"]["始値価格変更状態数"], 1)

    def test_数量時計の後退は累積が増えても基準を失効(self) -> None:
        """価格時計の増加だけで数量時計後退を正常増分と見なさない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record("2026-11-04T06:00:00+09:00"),
                        cumulative("2026-11-04T08:45:00+09:00", 120, 7200000000),
                        cumulative("2026-11-04T08:46:00+09:00", 130, 7800000000, TradingVolumeTime="2026-11-04T08:44:59+09:00")])
        self.assertEqual(result["起算"]["差分計算可能原行数"], 1)
        self.assertEqual(result["件数"]["数量時計後退状態数"], 1)
        self.assertEqual(result["起算"]["基準無効化数"], 1)

    def test_場内価格で古い数量時計なら数学比と場内参照を分ける(self) -> None:
        """当場前の量時計から得た差分を当場数量更新と呼ばない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record("2026-11-04T06:00:00+09:00"),
                        cumulative("2026-11-04T08:45:00+09:00", 120, 7200000000, TradingVolumeTime="2026-11-04T08:44:59+09:00")])
        self.assertEqual(result["件数"]["場内だが数量時計は場開始前原行数"], 1)
        self.assertEqual(result["起算"]["差分計算可能原行数"], 1)
        self.assertEqual(result["起算"]["差分計算可能かつ内部整合かつ場内数量時計原行数"], 0)
        self.assertEqual(result["起算"]["差分計算可能かつ場内観測参照候補原行数"], 0)

    def test_数学差分と内部整合と正価格の交差を別掲する(self) -> None:
        """数学的0価格・native不整合・整合正価格を参照候補で区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for updates, intersection, candidate in (({}, 1, 1), ({"VWAP": 60001}, 0, 0)):
            with self.subTest(現在=updates):
                current = cumulative("2026-11-04T08:45:00+09:00", 120, 7200000000)
                current.update(updates)
                result = audit([record("2026-11-04T06:00:00+09:00"), current])
                self.assertEqual(result["起算"]["差分計算可能原行数"], 1)
                self.assertEqual(result["起算"]["差分計算可能かつ内部整合かつ場内数量時計原行数"], intersection)
                self.assertEqual(result["起算"]["差分計算可能かつ場内観測参照候補原行数"], candidate)
        zero = audit([record("2026-11-04T06:00:00+09:00"), cumulative("2026-11-04T08:45:00+09:00", 101, 6000000000)])
        self.assertEqual(zero["件数"]["差分価格ゼロ原行数"], 1)
        self.assertEqual(zero["起算"]["差分計算可能かつ内部整合かつ場内数量時計原行数"], 1)
        self.assertEqual(zero["起算"]["差分計算可能かつ場内観測参照候補原行数"], 0)

    def test_全接頭が不整合なら基準不明のままにする(self) -> None:
        """時計とidentityが既知でも非ゼロprefixの内部不整合を採用しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record("2026-11-04T06:00:00+09:00", VWAP=61000),
                        cumulative("2026-11-04T08:45:00+09:00", 120, 7200000000)])
        self.assertEqual(result["件数"]["接頭内部不整合による基準更新見送り原行数"], 1)
        self.assertIsNone(result["起算"]["既知接頭基準"])
        self.assertEqual(result["起算"]["差分計算可能原行数"], 0)

    def test_不整合prefixの後の整合prefixからだけ基準を作る(self) -> None:
        """後で確認できた整合prefixを過去の不整合に遡及しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record("2026-11-04T06:00:00+09:00", VWAP=61000),
                        record("2026-11-04T06:01:00+09:00"), cumulative("2026-11-04T08:45:00+09:00", 120, 7200000000)])
        self.assertEqual(result["起算"]["既知接頭基準"]["line"], 2)
        self.assertEqual(result["起算"]["差分計算可能原行数"], 1)

    def test_nativeだけ不整合prefixでは前の整合基準を保持(self) -> None:
        """累積やidentityの変更なしでnativeだけ壊れても旧基準を改訂しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        result = audit([record("2026-11-04T06:00:00+09:00"), record("2026-11-04T06:01:00+09:00", VWAP=61000),
                        cumulative("2026-11-04T08:45:00+09:00", 120, 7200000000)])
        self.assertEqual(result["起算"]["既知接頭基準"]["line"], 1)
        self.assertEqual(result["起算"]["基準無効化数"], 0)
        self.assertEqual(result["起算"]["差分計算可能原行数"], 1)


# ----------------------------------------
# 実行記録は合成だけを対象とし、PnLやViewer約定を生成しない。

def main() -> None:
    """全合成を実行し日本語JSONと標準出力へ結果を保存する。

    引数: なし。
    返り値: None。失敗時は終了コード1。原板全量や保存監査結果は読まない。
    """
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
              "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors],
              "ファイルSHA256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in (Path(__file__), HERE/"抽出監査.py", STUDY/"条件.json")},
              "範囲": "人工原板行だけの抽出/時計/配信VWAP整合/起算基準。損益・先着・Viewer取引を生成しない。",
              "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/"合成検証.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({key: report[key] for key in ("全件成功", "検証件数")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
