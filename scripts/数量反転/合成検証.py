"""00014の観測数量集約・共通助走・RVOL入口を合成データで確認する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def module(path: Path, name: str):
    """合成対象をコマンド行実行せず読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: object はモジュール。原板や実結果を読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


Q = module(Path(__file__).with_name("数量.py"), "数量集約の合成対象")
I = module(Path(__file__).with_name("入口.py"), "数量入口の合成対象")
CONFIG = {"時間足分": [1, 3, 5], "残り時間下限分": 60, "確認遅延上限秒": 30, "運用": {"呼値pt": 5},
          "数量条件": {"参照足数": 20, "RVOL下限": 1.2, "数量準備両側共通": True}}


def event(now: float, line: int, volume: float, volume_time: float | None = None,
          last: float = 1000., valid: bool = True) -> object:
    """価格時計・原行・累積量を持つ観測を作る。

    引数: now/volume/volume_time/last (float|None) は時計・数量・価格、line (int) は原行、
    valid (bool) はBBO正常性。数量時計省略時だけ価格時計と同じにする。
    返り値: object は入力cacheと同じ属性を持つ観測。
    """
    return SimpleNamespace(now=now, line=line, volume=volume, volume_time=now if volume_time is None else volume_time,
                           last=last, bid=995., ask=1000., valid=valid)


def frame(index: int, size: int = 1, **changes) -> dict:
    """数量枠と同じ開始・終了を持つ確定価格特徴を作る。

    引数: index/size (int) は番号/分幅、changes (dict) は上書き列。
    返り値: dict は価格足と指標。単なる数量枠にLastを捏造しないよう入力側も対応させる。
    """
    start, end = index * size * 60, (index + 1) * size * 60
    return {"index": index, "minutes": size, "start": start, "end": end, "confirm": end,
            "confirm_line": index + 2, "publish": True, "missing": 0,
            "open": 1000., "close": 1000., "high": 1010., "low": 990.,
            "ema20": 1000., "atr": 20., "adx": 10., "bb_mean": 1000., "bb_sd": 5., **changes}


def higher() -> dict:
    """当場で公開済みの準備済み15分足を作る。

    引数: なし。
    返り値: dict は上位買方向だが、反転入口では準備だけに用いる。
    """
    return {"publish": True, "end": 0., "confirm": 0., "confirm_line": 0,
            "close": 1100., "ema20": 1050., "ema20_previous": 1000.}


def aggregate(events: list[object], indices: list[int], size: int = 1,
              changes: dict[int, dict] | None = None) -> tuple[dict, dict]:
    """指定した価格足だけに観測数量を対応させる。

    引数: events (list[object]) は観測、indices (list[int]) は実在価格足、size (int) は分幅、
    changes (dict[int,dict]|None) は価格足の公開/欠枠等。
    返り値: tuple[dict,dict] は属性と品質。
    """
    alterations, frames, previous = changes or {}, [], None
    for index in indices:
        missing = index if previous is None else index - previous - 1
        frames.append(frame(index, size, missing=missing, **alterations.get(index, {})))
        previous = index
    return Q.aggregate(events, frames, 0., (max(indices) + 1) * size * 60., size)


def steady(count: int = 23, size: int = 1, amount: float = 100., special: dict[int, float] | None = None) -> list[object]:
    """初回0を基準とし各足の既知差分を積み上げる。

    引数: count/size (int) は足数/分幅、amount (float) は通常増分、
    special (dict[int,float]|None) は足別増分。
    返り値: list[object] は場外終端の確認用観測を含む列。終端数量は集約へ入らない。
    """
    total, values = 0., [event(0., 1, 0.)]
    for index in range(1, count):
        total += (special or {}).get(index, amount)
        values.append(event(index * size * 60., index + 1, total))
    values.append(event(count * size * 60., count + 1, total + 999999.))
    return values


# ----------------------------------------
# 数量時計は価格時計で採用可否を判定し、遡って前足へ配り直さない。

class 数量集約検証(unittest.TestCase):
    """累積差分と基準継続、数量履歴と公開可否を分離する。"""

    def test_初回累積を全量計上せず同足正常差分は残す(self) -> None:
        """初回100は基準だけにし、同足の10増分と次足差分を記録する。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        rows, _ = aggregate([event(0., 1, 100.), event(1., 2, 110.), event(60., 3, 120.)], [0, 1])
        self.assertEqual(rows[0]["観測差分量"], 10.)
        self.assertFalse(rows[0]["数量基準完全"])
        self.assertEqual(rows[1]["観測差分量"], 10.)
        self.assertTrue(rows[1]["数量基準完全"])

    def test_確認行と同秒追加行を次足へだけ加える(self) -> None:
        """足確定の境界数量を前足へ入れず、同秒の全原行増分を保持する。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        values = [event(0., 1, 100.), event(59., 2, 110.), event(60., 3, 120.), event(60., 4, 125.)]
        rows, _ = aggregate(values, [0, 1])
        self.assertEqual((rows[0]["観測差分量"], rows[1]["観測差分量"]), (10., 15.))
        self.assertEqual((rows[0]["最終採用原行"], rows[1]["最終採用原行"]), (2, 4))

    def test_Last欠測や不正BBOでも量を処理(self) -> None:
        """Lastや提示板の有効性を約定量の採否へ流用しない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        values = [event(0., 1, 100.), event(59., 2, 110., last=float("nan")),
                  event(60., 3, 120., last=float("nan"), valid=False), event(61., 4, 130.)]
        rows, _ = aggregate(values, [0, 1])
        self.assertEqual((rows[0]["観測差分量"], rows[1]["観測差分量"]), (10., 20.))
        self.assertTrue(rows[1]["数量基準完全"])

    def test_価格時計欠枠後は再基準化(self) -> None:
        """欠けた枠を跨ぐ100増分を次の価格足へ全量計上しない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        rows, quality = aggregate([event(0., 1, 100.), event(120., 2, 200.), event(121., 3, 205.)], [0, 2])
        self.assertEqual(rows[2]["観測差分量"], 5.)
        self.assertFalse(rows[2]["数量基準完全"])
        self.assertEqual(quality["価格時計欠枠数"], 1)

    def test_無価格枠直後も再基準化して窓に残さない(self) -> None:
        """観測があってもLastがない枠を価格数量足として使わない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        values = [event(0., 1, 100.), event(60., 2, 200., last=float("nan")),
                  event(120., 3, 300.), event(121., 4, 310.)]
        rows, quality = aggregate(values, [0, 2])
        self.assertEqual(set(rows), {0, 2})
        self.assertEqual(rows[2]["観測差分量"], 10.)
        self.assertFalse(rows[2]["数量基準完全"])
        self.assertEqual(quality["無価格枠後基準切替数"], 1)

    def test_数量時計先行は保留し後の採用足へ差分(self) -> None:
        """先行累積で基準を動かさず、採用時の価格足にまとめる。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        values = [event(0., 1, 100.), event(60., 2, 150., volume_time=130.),
                  event(61., 3, 110.), event(130., 4, 155.)]
        rows, quality = aggregate(values, [0, 1, 2])
        self.assertEqual((rows[1]["観測差分量"], rows[2]["観測差分量"]), (10., 45.))
        self.assertTrue(rows[1]["数量基準完全"])
        self.assertEqual(quality["数量時計先行観測数"], 1)

    def test_当足数量時計未採用なら不完全(self) -> None:
        """先行しかない足、過去足時計しかない足を完全にしない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        for clock in (130., 59.):
            rows, _ = aggregate([event(0., 1, 100.), event(60., 2, 110., volume_time=clock)], [0, 1])
            self.assertFalse(rows[1]["数量基準完全"])
            self.assertIn("当足に属する採用数量時計なし", rows[1]["数量不完全理由"])

    def test_不正量時計は当足不完全だが旧基準保持(self) -> None:
        """欠測の次の正常差分は前の有効基準から計算する。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        for amount, clock in ((float("nan"), 60.), (-1., 60.), (float("inf"), 60.), (110., float("nan")), (110., float("inf"))):
            values = [event(0., 1, 100.), event(60., 2, amount, volume_time=clock), event(61., 3, 120.)]
            rows, _ = aggregate(values, [0, 1])
            self.assertEqual(rows[1]["観測差分量"], 20.)
            self.assertFalse(rows[1]["数量基準完全"])
            self.assertEqual(rows[1]["最終採用原行"], 3)

    def test_累積減少や数量時計後退は基準を取り直す(self) -> None:
        """既に採用した増分を消さず、基準切替行の増分を加えない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        cases = ([event(0., 1, 100.), event(60., 2, 150.), event(61., 3, 20.), event(62., 4, 25.)],
                 [event(0., 1, 100.), event(60., 2, 150.), event(61., 3, 160., volume_time=59.), event(62., 4, 165.)])
        for values in cases:
            rows, _ = aggregate(values, [0, 1])
            self.assertEqual(rows[1]["観測差分量"], 55.)
            self.assertFalse(rows[1]["数量基準完全"])

    def test_価格時計原行の後退は数量基準を動かさない(self) -> None:
        """古い価格時計や同時計の過去原行を並べ替えて採用しない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        for bad in (event(59., 4, 9999.), event(60., 2, 9999.)):
            values = [event(0., 1, 100.), event(60., 3, 110.), bad, event(61., 5, 115.)]
            rows, quality = aggregate(values, [0, 1])
            self.assertEqual(rows[1]["観測差分量"], 15.)
            self.assertTrue(rows[1]["数量基準完全"])
            self.assertEqual(quality["価格時計原行後退除外"], 1)

    def test_場外非有限時計と終了等号を入れない(self) -> None:
        """NaN・開始前・終了時点の累積で場内基準を変更しない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        values = [event(-1., 1, 10000.), event(float("nan"), 2, 20000.),
                  event(0., 3, 100.), event(60., 4, 120.), event(120., 5, 99999.)]
        rows, _ = aggregate(values, [0, 1])
        self.assertEqual(rows[1]["観測差分量"], 20.)
        self.assertEqual(rows[1]["最終採用原行"], 4)

    def test_一三五分の初回と当足除外二十本(self) -> None:
        """足幅ごとに20完全足を待ち、当足120を平均100へ入れない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        for size in (1, 3, 5):
            rows, _ = aggregate(steady(22, size, special={21: 120.}), list(range(22)), size)
            self.assertFalse(rows[20]["数量準備済"])
            self.assertEqual((rows[21]["直前数量足数"], rows[21]["直前数量合計"], rows[21]["直前数量平均"]), (20, 2000., 100.))
            self.assertEqual(rows[21]["RVOL"], 1.2)
            self.assertTrue(rows[21]["数量準備済"])

    def test_当足ゼロはRVOLゼロで準備可能(self) -> None:
        """分母が正なら0量を欠測や数量基準不完全に変えない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        rows, _ = aggregate(steady(22, special={21: 0.}), list(range(22)))
        self.assertTrue(rows[21]["数量準備済"])
        self.assertEqual(rows[21]["RVOL"], 0.)

    def test_分母ゼロは二十本ありと準備済を区別(self) -> None:
        """履歴20本でも平均0ならRVOLを定義せず、その履歴は保持する。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        rows, quality = aggregate(steady(23, amount=0., special={21: 100., 22: 100.}), list(range(23)))
        self.assertEqual(rows[21]["直前数量足数"], 20)
        self.assertEqual(rows[21]["直前数量平均"], 0.)
        self.assertFalse(rows[21]["数量準備済"])
        self.assertIsNone(rows[21]["RVOL"])
        self.assertTrue(rows[22]["数量準備済"])
        self.assertEqual(rows[22]["直前数量平均"], 5.)
        self.assertGreater(quality["直前20数量足利用可能足数"], quality["数量準備済足数"])

    def test_不完全足は履歴を切るが累積基準は保持(self) -> None:
        """不正量の次足から20完全足を数え直す。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        values = steady(43)
        values[21].volume = float("nan")
        rows, _ = aggregate(values, list(range(43)))
        self.assertFalse(rows[21]["数量準備済"])
        self.assertEqual((rows[22]["直前数量足数"], rows[22]["観測差分量"]), (0, 200.))
        self.assertFalse(rows[41]["数量準備済"])
        self.assertTrue(rows[42]["数量準備済"])

    def test_非公開足は数量準備とは別に次の履歴を切る(self) -> None:
        """当足の量準備を保っても非公開足を次足分母へ入れない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        rows, quality = aggregate(steady(23), list(range(23)), changes={21: {"publish": False}})
        self.assertTrue(rows[21]["数量準備済"])
        self.assertEqual(rows[22]["直前数量足数"], 0)
        self.assertFalse(rows[22]["数量準備済"])
        self.assertGreater(quality["数量準備済足数"], quality["公開数量準備済足数"])

    def test_後続更新は既公開数量足を改訂しない(self) -> None:
        """後続の大量増加や累積減少で過去の量・平均を変更しない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        before = steady(22)[:-1]
        after = before + [event(22*60., 30, 999999.), event(22*60.+1, 31, 1.)]
        prefix, _ = aggregate(before, list(range(22)))
        full, _ = aggregate(after, list(range(23)))
        self.assertEqual(prefix, {index: full[index] for index in prefix})

    def test_別セッション呼出で数量助走を継承しない(self) -> None:
        """前場の20本準備を次場の累積基準や参照窓へ持ち越さない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        old, _ = aggregate(steady(22), list(range(22)))
        new, _ = aggregate([event(0., 1, 50000.), event(60., 2, 50100.)], [0, 1])
        self.assertTrue(old[21]["数量準備済"])
        self.assertEqual(new[0]["観測差分量"], 0.)
        self.assertEqual(new[1]["直前数量足数"], 0)
        self.assertFalse(new[1]["数量準備済"])

    def test_価格足番号重複と尺度時計矛盾を拒否する(self) -> None:
        """量を別の足幅や別開始時刻へ暗黙に対応させない。

        引数: self (数量集約検証) はテスト。
        返り値: None。
        """
        values = [event(0., 1, 100.), event(60., 2, 110.)]
        for frames in ([frame(0), frame(0)], [frame(1), frame(0)],
                       [frame(0, minutes=3)], [frame(0, start=1.)]):
            with self.assertRaises(ValueError):
                Q.aggregate(values, frames, 0., 120., 1)


# ----------------------------------------
# 同じ価格発動へ同じ数量助走を課し、RVOL追加だけを比較する。

class 数量入口検証(unittest.TestCase):
    """1/3/5分の価格式を保ち、数量の共通準備と1.2等号を検査する。"""

    def case(self, size: int, rvol: float = 1.2, ready: bool = True) -> tuple[list[dict], dict]:
        """共通R2価格発動と、外部集約済みの数量属性を作る。

        引数: self (数量入口検証) はテスト、size (int) は足幅、rvol (float) は比率、
        ready (bool) は数量準備。
        返り値: tuple[list[dict],dict] は価格足と数量map。
        """
        frames = [frame(i, size) for i in range(7)]
        frames[5].update(close=985., low=980.)
        frames[6].update(close=995., low=990.)
        q = {"観測差分量": 100. * rvol, "数量基準完全": ready, "直前数量足数": 20 if ready else 19,
             "直前数量合計": 2000., "直前数量平均": 100., "RVOL": rvol if ready else None,
             "数量準備済": ready, "最終採用数量時計": frames[6]["end"] - 1,
             "最終採用価格時計": frames[6]["end"] - 1, "最終採用原行": 7,
             "数量不完全理由": [] if ready else ["合成で数量未準備"]}
        return frames, {6: q}

    def test_一三五分で価格式同一かつRVOL等号を含む(self) -> None:
        """1分を追加しても価格式を変えず、1.2等号を補助に含める。

        引数: self (数量入口検証) はテスト。
        返り値: None。
        """
        for size in (1, 3, 5):
            frames, quantity = self.case(size)
            result, quality = I.generate(frames, [higher()], "合成場", 20000., 30000., CONFIG, quantity)
            self.assertEqual(len(result[f"{size}分_R2_なし"]), 1)
            self.assertEqual(len(result[f"{size}分_R2_RVOL1.2以上"]), 1)
            self.assertEqual(quality["数量準備除外数"], 0)

    def test_数量助走は両候補共通(self) -> None:
        """補助なし側だけ数量未準備の入口を残さない。

        引数: self (数量入口検証) はテスト。
        返り値: None。
        """
        frames, quantity = self.case(1, ready=False)
        result, quality = I.generate(frames, [higher()], "合成場", 20000., 30000., CONFIG, quantity)
        self.assertFalse(any(result.values()))
        self.assertEqual((quality["基準価格入口数"], quality["数量準備除外数"]), (1, 1))
        self.assertEqual(len(quality["基準価格入口記録"]), 1)

    def test_RVOL未満とゼロは補助なしに残す(self) -> None:
        """当足0や1.2直下を入口不足でなく数量条件の不成立とする。

        引数: self (数量入口検証) はテスト。
        返り値: None。
        """
        for rvol in (0., 1.199999):
            frames, quantity = self.case(1, rvol)
            result, quality = I.generate(frames, [higher()], "合成場", 20000., 30000., CONFIG, quantity)
            self.assertEqual(len(result["1分_R2_なし"]), 1)
            self.assertFalse(result["1分_R2_RVOL1.2以上"])
            self.assertEqual(quality["RVOL補助除外数"], 1)

    def test_数量属性欠落と不正RVOLを黙って補完しない(self) -> None:
        """基準価格発動の量map欠落やready矛盾を入力エラーにする。

        引数: self (数量入口検証) はテスト。
        返り値: None。
        """
        frames, quantity = self.case(1)
        with self.assertRaises(ValueError):
            I.generate(frames, [higher()], "合成場", 20000., 30000., CONFIG, {})
        quantity[6]["RVOL"] = None
        with self.assertRaises(ValueError):
            I.generate(frames, [higher()], "合成場", 20000., 30000., CONFIG, quantity)

    def test_実集約の二十本助走から入口まで接続する(self) -> None:
        """集約済みRVOL1.2とその直前の未準備足を入口へ渡す。

        引数: self (数量入口検証) はテスト。
        返り値: None。
        """
        for size in (1, 3, 5):
            values = steady(22, size, special={21: 120.})
            frames = [frame(i, size) for i in range(22)]
            frames[20].update(close=985., low=980.)
            frames[21].update(close=995., low=990.)
            quantity, _ = Q.aggregate(values, frames, 0., 22*size*60., size)
            result, quality = I.generate(frames, [higher()], "合成場", 20000., 30000., CONFIG, quantity)
            self.assertEqual([r["index"] for r in result[f"{size}分_R2_なし"]], [21])
            self.assertEqual([r["index"] for r in result[f"{size}分_R2_RVOL1.2以上"]], [21])
            self.assertEqual(quality["数量準備通過数"], 1)
            self.assertEqual(result[f"{size}分_R2_なし"][0]["直前数量平均"], 100.)

    def test_R1の鏡像でも同じ数量条件で選別する(self) -> None:
        """安値割れ復帰と高値超え復帰に同じRVOLと助走を適用する。

        引数: self (数量入口検証) はテスト。
        返り値: None。
        """
        frames, quantity = self.case(1)
        frames[5].update(close=990., low=990.)
        frames[6].update(close=995., low=985.)
        mirrored = deepcopy(frames)
        for row in mirrored:
            old_high, old_low = row["high"], row["low"]
            for key in ("open", "close", "ema20", "bb_mean"):
                row[key] = 2000. - row[key]
            row["high"], row["low"] = 2000. - old_low, 2000. - old_high
        a, _ = I.generate(frames, [higher()], "合成場", 20000., 30000., CONFIG, quantity)
        b, _ = I.generate(mirrored, [higher()], "合成場", 20000., 30000., CONFIG, quantity)
        for extra in I.EXTRAS:
            self.assertEqual([r["side"] for r in a[f"1分_R1_{extra}"]], [1])
            self.assertEqual([r["side"] for r in b[f"1分_R1_{extra}"]], [-1])

    def test_数量準備済でも未公開価格足では発動しない(self) -> None:
        """数量準備だけで価格足の公開条件を通過させない。

        引数: self (数量入口検証) はテスト。
        返り値: None。
        """
        frames, quantity = self.case(1)
        frames[-1]["publish"] = False
        result, quality = I.generate(frames, [higher()], "合成場", 20000., 30000., CONFIG, quantity)
        self.assertFalse(any(result.values()))
        self.assertEqual(quality["基準価格入口数"], 0)


# ----------------------------------------
# 実データ再生を呼ばず、候補・期間・継承依存と非上書きを確認する。

class 実行側検証(unittest.TestCase):
    """固定12案と旧X0だけを用い、既使用最終場を選定へ混ぜない。"""

    def test_十二案とX0と数量条件を固定する(self) -> None:
        """尺度・補助・期間本数・出口の別案を実行時に追加しない。

        引数: self (実行側検証) はテスト。
        返り値: None。条件JSONだけを読む。
        """
        driver = module(Path(__file__).with_name("検証.py"), "数量driver候補合成")
        config = driver.W.read_json(driver.STUDY / "条件.json")
        candidates = driver.sources(config)
        self.assertEqual(len(candidates), 12)
        self.assertEqual(len({r["入口ID"] for r in candidates}), 12)
        self.assertEqual({r["時間足分"] for r in candidates}, {1, 3, 5})
        self.assertTrue(config["全65場既使用"])
        for key, value in (("時間足分", [3, 5]), ("出口", [{"出口ID": "X1"}])):
            bad = deepcopy(config)
            bad[key] = value
            with self.assertRaises(ValueError):
                driver.sources(bad)
        for key, value in (("参照足数", 19), ("RVOL下限", 1.1), ("数量準備両側共通", False)):
            bad = deepcopy(config)
            bad["数量条件"][key] = value
            with self.assertRaises(ValueError):
                driver.sources(bad)

    def test_実際の十一継承と数量と新合成を固定する(self) -> None:
        """旧11固定版を実SHA検査し、今回3実装と合成を固定対象へ含める。

        引数: self (実行側検証) はテスト。
        返り値: None。正式固定を作らず書込だけmockにする。
        """
        driver = module(Path(__file__).with_name("検証.py"), "数量driver固定合成")
        study = ROOT / "work/数量反転/合成固定用の未作成先"
        self.assertFalse(study.exists())
        original_sha = driver.O.sha

        def synthetic_sha(path: Path) -> str:
            """架空試行内だけ仮SHAとし、実継承元は本物のSHAで照合する。

            引数: path (Path) は固定対象。
            返り値: str は合成値または実SHA256。
            """
            return "合成SHA" if path.is_relative_to(study) else original_sha(path)

        with patch.object(driver.O, "sha", side_effect=synthetic_sha), patch.object(driver.W, "write_json"):
            locked = driver.freeze(study)
        pins = locked["ファイルSHA256"]
        for name in ("検証.py", "入口.py", "数量.py", "合成検証.py"):
            self.assertIn("scripts/数量反転/" + name, pins)
        self.assertIn("scripts/テクニカル循環/入口.py", pins)
        self.assertIn("scripts/テクニカル循環/運用.py", pins)
        self.assertIn("study/00011_順行と反転のチャート構造と利益回収/固定.json", pins)
        self.assertNotIn("scripts/反転確認/運用.py", pins)
        self.assertNotIn("scripts/収縮反転/入口.py", pins)

    def test_既使用最終一場を入口目標の選定へ使わない(self) -> None:
        """旧40/24の同一条件では最終場の成績を変えても支持と目標を保つ。

        引数: self (実行側検証) はテスト。
        返り値: None。合成集計だけを渡す。
        """
        driver = module(Path(__file__).with_name("検証.py"), "数量driver期間合成")
        config = driver.W.read_json(driver.STUDY / "条件.json")
        result = {p: {**limits, "確認率": .7,
                       "30分間引き_約定候補数": config["間引き必要件数"][p],
                       "30分間引き_確認率": .7}
                  for p, limits in config["入口支持"].items()}
        result["後続検査"] = {"確認率": 0., "約定候補数": 0}
        self.assertEqual(driver.entry_flags(result, config), (True, True))
        result["後続検査"] = {"確認率": 1., "約定候補数": 999999}
        self.assertEqual(driver.entry_flags(result, config), (True, True))
        result["学習"]["確認率"] = .699999
        self.assertEqual(driver.entry_flags(result, config), (True, False))


def run_tests() -> dict:
    """合成検査の明示合否と版指紋をGit外へ保存する。

    引数: なし。実データの数値再生は行わない。
    返り値: dict は件数・失敗・エラー・指紋・検査記録。
    """
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "失敗": [{"検査": str(t), "内容": text} for t, text in result.failures],
              "エラー": [{"検査": str(t), "内容": text} for t, text in result.errors],
              "ファイルSHA256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__), Path(__file__).with_name("数量.py"), Path(__file__).with_name("入口.py"), Path(__file__).with_name("検証.py"))},
              "範囲": "数量初回/欠枠/Last欠測/時計先行後退/累積減少/不正/ゼロ/当足除外20/非公開/未来更新不変/場別初期化・入口共通助走/RVOL1.2等号/R1鏡像/実集約連携・driver12案/X0/実継承固定/期間。数値再生なし。",
              "実行記録": stream.getvalue()}
    target = ROOT / "work/数量反転/合成検証.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(stream.getvalue())
    return report


if __name__ == "__main__":
    if not run_tests()["全件成功"]:
        raise SystemExit(1)
