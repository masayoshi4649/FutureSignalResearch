"""00011入口の状態・境界・確定時点を、実データなしで確認する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


PATH = Path(__file__).with_name("入口.py")
SPEC = importlib.util.spec_from_file_location("循環入口の検証対象", PATH)
E = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = E
SPEC.loader.exec_module(E)
ROOT = PATH.parents[2]
CONFIG = {"時間足分": [3, 5], "残り時間下限分": 60, "確認遅延上限秒": 30, "運用": {"呼値pt": 5}}


def frame(index: int, minutes: int = 3, **changes) -> dict:
    """共通準備を満たす合成の確定足を作る。

    引数: index/minutes (int) は足番号/尺度、changes (dict) は上書き列。
    返り値: dict は入口へ渡す特徴。
    """
    end = (index + 1) * minutes * 60
    return {"index": index, "minutes": minutes, "end": end, "confirm": end,
            "confirm_line": 10 * index + 1, "publish": True, "missing": 0,
            "open": 100., "close": 100., "high": 110., "low": 90., "ema20": 100.,
            "atr": 10., "adx": 10., "bb_mean": 120., "bb_sd": 20., **changes}


def higher(**changes) -> dict:
    """準備済み買方向の上位足を作る。

    引数: changes (dict) は上書き列。
    返り値: dict は15分特徴。
    """
    return {"publish": True, "end": 0, "confirm": 0, "confirm_line": 0,
            "close": 120., "ema20": 110., "ema20_previous": 100., **changes}


def mirror(row: dict) -> dict:
    """200を軸にOHLC・平均・上位方向の売買鏡像を作る。

    引数: row (dict) は足。
    返り値: dict は高安を交換した鏡像。
    """
    result = deepcopy(row)
    for key in ("open", "close", "ema20", "ema20_previous", "bb_mean"):
        if key in row and row[key] is not None:
            result[key] = 200 - row[key]
    if "high" in row and "low" in row:
        result["high"], result["low"] = 200 - row["low"], 200 - row["high"]
    return result


def run(frames: list[dict], uppers: list[dict] | None = None, cutoff: float = 20000,
        deadline: float = 30000) -> tuple[dict, dict]:
    """同じ固定時刻条件で入口生成を呼ぶ。

    引数: frames/uppers (list[dict]|None) は下位/上位足、cutoff/deadline (float) は時計。
    返り値: tuple[dict,dict] は発動列と品質。
    """
    return E.generate(frames, [higher()] if uppers is None else uppers, "合成場", cutoff, deadline, CONFIG)


def signals(output: dict, family: str, side: int = 1) -> list[dict]:
    """対象系統・方向の発動だけを抽出する。

    引数: output (dict) は生成結果、family (str) は系統、side (int) は方向。
    返り値: list[dict] は発動。
    """
    return [row for key, rows in output.items() if key.endswith("_" + family) for row in rows if row["side"] == side]


def t1(minutes: int = 3) -> list[dict]:
    """前終値がEMA以下で現足が上抜ける7足を作る。

    引数: minutes (int) は尺度。
    返り値: list[dict] は6本の履歴と発動足。
    """
    rows = [frame(i, minutes) for i in range(6)]
    rows[-1].update(close=99., ema20=100.)
    rows.append(frame(6, minutes, close=102., ema20=101.))
    return rows


def t2(tail: list[dict] | None = None) -> list[dict]:
    """直前6本高値110を突破し、翌足が110を再テストする列を作る。

    引数: tail (list[dict]|None) は突破後の足列。
    返り値: list[dict] は固定水準の突破・再テスト。
    """
    rows = [frame(i) for i in range(6)] + [frame(6, close=120., high=122., low=116.)]
    rows.extend([frame(7, close=116., high=119., low=110.)] if tail is None else tail)
    return rows


def driver() -> object:
    """入口名を明示してdriverを合成確認用に読み込む。

    引数: なし。
    返り値: object は実行関数を呼んでいないdriver。原板・cacheは読み込まない。
    """
    sys.modules["入口"] = E
    path = PATH.with_name("検証.py")
    spec = importlib.util.spec_from_file_location("循環driverの合成確認", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ----------------------------------------
# 各入口の発動と鏡像。共通準備は全系統へ同じ母集団条件を課す。

class 入口検証(unittest.TestCase):
    """状態を持つ登録と確定足の境界を検証する。"""

    def test_T1の前現上位方向とEMAの厳密境界(self) -> None:
        """前現の上位買方向・EMA上抜け・EMA上昇・終値改善を要求する。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        self.assertEqual(len(signals(run(t1())[0], "T1")), 1)
        for changes in ({"close": 101.}, {"ema20": 100.}, {"close": 99.}):
            rows = t1()
            rows[-1].update(changes)
            self.assertFalse(signals(run(rows)[0], "T1"))
        rows = t1()
        rows[-2]["close"] = 101.
        self.assertFalse(signals(run(rows)[0], "T1"))
        neutral = higher(close=110., ema20=110., ema20_previous=100.)
        new = higher(end=1260, confirm=1260, confirm_line=61)
        self.assertFalse(signals(run(t1(), [neutral, new])[0], "T1"))

    def test_T1の3分5分と鏡像(self) -> None:
        """両尺度で同じ条件と売買反転が成立する。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        for size in (3, 5):
            rows = t1(size)
            a = signals(run(rows)[0], "T1")
            b = signals(run([mirror(r) for r in rows], [mirror(higher())])[0], "T1", -1)
            self.assertEqual([r["index"] for r in a], [6])
            self.assertEqual([r["index"] for r in b], [6])

    def test_R1はstrict下抜けと範囲復帰と中心方向(self) -> None:
        """端への接触・中心到達・ADX20等号を反転発動にしない。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        rows = [frame(i, close=90.) for i in range(6)] + [frame(6, low=85., close=95., bb_mean=105.)]
        self.assertEqual(len(signals(run(rows)[0], "R1")), 1)
        for changes in ({"low": 90.}, {"close": 90.}, {"close": 111.}, {"bb_mean": 95.}, {"adx": 20.}):
            variant = deepcopy(rows)
            variant[-1].update(changes)
            self.assertFalse(signals(run(variant)[0], "R1"))
        reverse = signals(run([mirror(r) for r in rows], [mirror(higher())])[0], "R1", -1)
        self.assertEqual(len(reverse), 1)

    def test_R2は前終値帯外から現中心未満の内復帰(self) -> None:
        """前の帯等号は除き、現足下帯等号を認め中心等号は除く。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        rows = [frame(i, bb_mean=100., bb_sd=5.) for i in range(6)]
        rows[-1].update(close=85., low=84.)
        rows.append(frame(6, close=90., bb_mean=100., bb_sd=5.))
        self.assertEqual(len(signals(run(rows)[0], "R2")), 1)
        for previous, current in (({"close": 90.}, {}), ({}, {"close": 89.}), ({}, {"close": 100.}),
                                  ({}, {"adx": 20.}), ({"bb_sd": None}, {})):
            variant = deepcopy(rows)
            variant[-2].update(previous)
            variant[-1].update(current)
            self.assertFalse(signals(run(variant)[0], "R2"))
        self.assertEqual(len(signals(run([mirror(r) for r in rows], [mirror(higher())])[0], "R2", -1)), 1)

    def test_共通六本窓と指標準備(self) -> None:
        """窓・ATR正値・全共通指標・上位準備が必要である。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        self.assertFalse(signals(run(t1()[1:])[0], "T1"))
        for field in ("ema20", "atr", "adx", "bb_mean", "bb_sd"):
            rows = t1()
            rows[-1][field] = None
            self.assertFalse(any(run(rows)[0].values()))
        rows = t1()
        rows[-1]["atr"] = 0.
        self.assertFalse(any(run(rows)[0].values()))
        self.assertFalse(any(run(t1(), [higher(ema20_previous=None)])[0].values()))
        self.assertFalse(any(run(t1(), [higher(publish=False)])[0].values()))

    def test_時間境界と確認遅延候補(self) -> None:
        """残60分等号を含み、新規停止等号を除き、遅延候補を別記する。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        rows = t1()
        clock = rows[-1]["confirm"]
        self.assertEqual(len(signals(run(rows, deadline=clock + 3600)[0], "T1")), 1)
        self.assertFalse(any(run(rows, deadline=clock + 3599)[0].values()))
        self.assertFalse(any(run(rows, cutoff=clock)[0].values()))
        rows[-1]["confirm"] += 31
        out, quality = run(rows)
        self.assertEqual(signals(out, "T1")[0]["確認遅延秒"], 31)
        self.assertGreater(quality["確認遅延超過発動"], 0)

    def test_欠枠と非公開足を履歴へ混ぜない(self) -> None:
        """欠枠は履歴と登録を切り、非公開足は窓へ数えない。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        rows = t1()
        rows[-1]["missing"] = 1
        self.assertFalse(any(run(rows)[0].values()))
        rows = t1()
        rows[2]["publish"] = False
        self.assertFalse(any(run(rows)[0].values()))
        rows = t2()
        rows[-1]["missing"] = 1
        self.assertFalse(signals(run(rows)[0], "T2"))

    def test_上位の同時計原行と終了時点(self) -> None:
        """同時計の後続原行や下位足終了後の上位足を先読みしない。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        opposite = higher(end=1260, confirm=1260, confirm_line=62, close=80., ema20=90., ema20_previous=100.)
        self.assertEqual(len(signals(run(t1(), [higher(), opposite])[0], "T1")), 1)
        opposite["confirm_line"] = 61
        self.assertFalse(signals(run(t1(), [higher(), opposite])[0], "T1"))
        rows = t1()
        rows[-1]["confirm"] += 300
        future_end = higher(end=1400, confirm=1400, confirm_line=62, close=80., ema20=90., ema20_previous=100.)
        self.assertEqual(len(signals(run(rows, [higher(), future_end])[0], "T1")), 1)

    def test_未来特徴とラベルを変更しても発動は不変(self) -> None:
        """入口が使用しない将来損益を変えても同じ発動原行になる。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        rows = t1()
        a = run(rows)[0]
        for r in rows:
            r.update(ラベル="順行先着", 将来損益=999999, futurelabel=-999)
        b = run(rows)[0]
        self.assertEqual([r["イベントID"] for r in signals(a, "T1")], [r["イベントID"] for r in signals(b, "T1")])

    def test_T2の同足禁止と固定した旧水準(self) -> None:
        """突破足自身は再テストにせず、新しい窓高値で水準を動かさない。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        self.assertFalse(signals(run(t2([]))[0], "T2"))
        rows = signals(run(t2())[0], "T2")
        self.assertEqual([r["index"] for r in rows], [7])
        self.assertEqual(rows[0]["再テスト登録"]["水準"], 110.)
        self.assertEqual(rows[0]["直前6高値"], 122.)

    def test_T2の一から三足と満了(self) -> None:
        """登録後の1〜3足を含み4足目は満了させる。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        for age in (1, 2, 3, 4):
            tail = [frame(6 + j, close=118., low=116., high=120.) for j in range(1, age)]
            tail.append(frame(6 + age, close=116., low=110., high=119.))
            out, quality = run(t2(tail))
            self.assertEqual(len(signals(out, "T2")), int(age <= 3))
            if age == 4:
                self.assertEqual(quality["再テスト満了"], 1)

    def test_T2の接触一tickと終値一tickの厳密差(self) -> None:
        """安値帯の両端は含み、終値の突破幅1tick等号では発動しない。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        for low, close, count in ((105., 116., 1), (115., 116., 1), (104., 116., 0), (110., 115., 0)):
            rows = t2([frame(7, low=low, close=close, high=119.)])
            self.assertEqual(len(signals(run(rows)[0], "T2")), count)

    def test_T2の終値水準等号で失効し再登録なし(self) -> None:
        """終値が登録水準へ戻れば後の再テスト候補に流用しない。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        out, quality = run(t2([frame(7, low=109., close=110., high=119.),
                                frame(8, low=110., close=116., high=119.)]))
        self.assertFalse(signals(out, "T2"))
        self.assertEqual(quality["再テスト終値失効"], 1)

    def test_T2の最新突破へ置換(self) -> None:
        """追加突破の直前6本水準が旧登録を置き換える。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        out, _ = run(t2([frame(7, close=130., low=125., high=132.),
                         frame(8, close=128., low=122., high=131.)]))
        rows = signals(out, "T2")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["再テスト登録"]["水準"], 122.)
        self.assertEqual(rows[0]["再テスト登録"]["index"], 7)

    def test_T2の発動消費と鏡像(self) -> None:
        """一登録は一度だけ発動し、売り側も原順で同じ足となる。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        rows = t2([frame(7, low=110., close=116., high=119.), frame(8, low=110., close=117., high=119.)])
        out, quality = run(rows)
        reverse, _ = run([mirror(r) for r in rows], [mirror(higher())])
        self.assertEqual([r["index"] for r in signals(out, "T2")], [7])
        self.assertEqual([r["index"] for r in signals(reverse, "T2", -1)], [7])
        self.assertEqual(quality["再テスト消費"], 1)

    def test_確認時計後退と終了前公開を拒否(self) -> None:
        """矛盾した足時点を入口へ渡さない。

        引数: self (入口検証) はテスト。
        返り値: None。
        """
        rows = t1()
        rows[-1]["confirm"] = rows[-1]["end"] - 1
        with self.assertRaises(ValueError):
            run(rows)
        rows = t1()
        rows[-1]["confirm"] = 1
        with self.assertRaises(ValueError):
            run(rows)

    def test_driverの実継承元と入口検証を固定する(self) -> None:
        """実行時の継承元と入口検証をSHA一覧へ含める。

        引数: self (入口検証) はテスト。
        返り値: None。書込・SHA読取はmockで置き換え、入力や正式固定を変更しない。
        """
        module = driver()
        study = ROOT / "work/テクニカル循環/入口検証専用の未作成固定先"
        self.assertFalse(study.exists())
        with patch.object(module.O, "sha", return_value="合成SHA"), \
                patch.object(module.W, "read_json", return_value={"ファイルSHA256": {}}), \
                patch.object(module.W, "write_json"):
            locked = module.freeze(study)
        self.assertIn("scripts/利益回収/運用.py", locked["ファイルSHA256"])
        self.assertIn("scripts/テクニカル循環/入口検証.py", locked["ファイルSHA256"])

    def test_driverの中心超過キーは実在する品質列から集計(self) -> None:
        """中心を越えた新規が保存品質と同じ件数になる。

        引数: self (入口検証) はテスト。
        返り値: None。会計の数値コードはmockで分離する。
        """
        module = driver()
        infos = [{"観測含み込み最大DD円": 0, "観測最悪時価円": 0, "中心線超過新規数": 2}]
        with patch.object(module.E, "operation_metrics", return_value={"赤字場数": 0, "活動場数": 0}):
            metrics = module.operation_metrics(infos, [], "反転", {"出口ID": "X1"})
        self.assertEqual(metrics["中心線超過新規数"], 2)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(入口検証))
    target = ROOT / "work/テクニカル循環/入口検証.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"全件成功": result.wasSuccessful(), "件数": result.testsRun,
                                 "失敗数": len(result.failures), "例外数": len(result.errors),
                                 "入口SHA256": hashlib.sha256(PATH.read_bytes()).hexdigest(),
                                 "検証SHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not result.wasSuccessful():
        raise SystemExit(1)
