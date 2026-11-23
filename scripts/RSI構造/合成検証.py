"""00015の山谷確認時点・隣接更新・RSI型・ネック位置と固定依存を合成検証する。"""

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
    """合成対象をコマンド行の数値再生なしで読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: object はモジュール。原板や成績は読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


I = module(Path(__file__).with_name("入口.py"), "RSI構造の合成対象")
CONFIG = {"時間足分": [1, 3, 5], "入口系統": ["反転乖離", "押し戻り継続"],
          "補助": ["なし", "ネック位置確認"], "出口": [{"出口ID": "X0"}],
          "極値条件": {"左足本数": 2, "右足本数": 2, "中心間隔下限本数": 3,
                     "中心間隔上限本数": 20, "RSI期間": 14},
          "残り時間下限分": 60, "確認遅延上限秒": 30}


def frame(index: int, size: int = 1, **changes) -> dict:
    """数量・下位EMA/ADXを必要としない公開価格足を作る。

    引数: index/size (int) は番号/分幅、changes (dict) は上書き。
    返り値: dict はOHLC・現RSI14/ATR14と公開キーを持つ足。
    """
    start, end = index*size*60., (index+1)*size*60.
    return {"index": index, "minutes": size, "start": start, "end": end,
            "confirm": end, "confirm_line": index*10+1, "publish": True, "missing": 0,
            "open": 1000., "high": 1020., "low": 990., "close": 1000.,
            "rsi": 50., "atr": 20., "ema20": None, "adx": None,
            "bb_mean": None, "bb_sd": None, **changes}


def higher(**changes) -> dict:
    """当場の公開済み15分方向を作る。

    引数: changes (dict) は公開キー/方向/準備の上書き。
    返り値: dict は通常買い方向の上位足。
    """
    return {"index": 0, "publish": True, "end": 0., "confirm": 0., "confirm_line": 0,
            "close": 1100., "ema20": 1050., "ema20_previous": 1000., **changes}


def series(centers: list[tuple[int, float, float | None]] | None = None,
           size: int = 1, finish: int | None = None) -> list[dict]:
    """指定した安値中心と中心RSIだけを持つ、既知の二谷経路を作る。

    引数: centers (list[tuple[int,float,float|None]]|None) は中心番号/安値/RSI、
    size (int) は尺度、finish (int|None) は末尾番号。
    返り値: list[dict] は安値極値の2本後に終値改善を置く足。
    """
    pivots = centers or [(3, 970., 30.), (6, 960., 40.)]
    last = max(i for i, _, _ in pivots)+2 if finish is None else finish
    values = [frame(i, size) for i in range(last+1)]
    for index, low, rsi in pivots:
        values[index].update(low=low, rsi=rsi)
        if index+2 <= last:
            values[index+2].update(close=1005.)
    return values


def mirror(value: dict) -> dict:
    """価格とRSIを反転し、買いと売りの対称経路を作る。

    引数: value (dict) は足または上位足。
    返り値: dict は価格2000−元値、RSI100−元値の鏡像。
    """
    row = deepcopy(value)
    for key in ("open", "close", "ema20", "ema20_previous", "bb_mean"):
        if key in row and row[key] is not None:
            row[key] = 2000.-row[key]
    if "high" in row:
        row["high"], row["low"] = 2000.-value["low"], 2000.-value["high"]
    if row.get("rsi") is not None:
        row["rsi"] = 100.-row["rsi"]
    return row


def run(values: list[dict], uppers: list[dict] | None = None,
        cutoff: float = 100000., deadline: float = 200000.) -> tuple[dict, dict]:
    """合成価格足だけを固定共通条件で入口へ渡す。

    引数: values/uppers (list[dict]|None) は下位/上位足、cutoff/deadline (float) は停止/期限秒。
    返り値: tuple[dict,dict] は入口集合とpivot記録・品質。
    """
    return I.generate(values, [higher()] if uppers is None else uppers,
                      "合成場", cutoff, deadline, deepcopy(CONFIG))


def selected(output: dict, family: str = "反転乖離", extra: str = "なし") -> list[dict]:
    """合成出力から指定型・補助だけを尺度を跨いで読む。

    引数: output (dict) は入口集合、family/extra (str) は型・補助。
    返り値: list[dict] は一致する入口。
    """
    return [row for key, rows in output.items() if key.endswith("_"+family+"_"+extra) for row in rows]


# ----------------------------------------
# 未来右2本の確定と、等号・隣接更新・連続性の境界を確認する。

class 極値時点検証(unittest.TestCase):
    """中心の時刻へ遡らず、全pivotを隣接した一組だけで評価する。"""

    def test_右二足前に発動せず確認足でだけ要求する(self) -> None:
        """同じ二谷でも右2本目が公開されるまで新規要求を作らない。

        引数: self (極値時点検証) はテスト。
        返り値: None。
        """
        values = series()
        self.assertFalse(any(run(values[:-1])[0].values()))
        result, _ = run(values)
        row = selected(result)[0]
        self.assertEqual((row["index"], row["要求時計秒"], row["要求原板行"]),
                         (8, values[8]["confirm"], values[8]["confirm_line"]))
        self.assertEqual(row["現極値"]["中心番号"], 6)
        self.assertEqual(row["現極値"]["中心足公開時計秒"], values[6]["confirm"])
        self.assertEqual(row["現極値"]["中心足公開原行"], values[6]["confirm_line"])
        self.assertEqual((row["現極値"]["極値確認足index"], row["現極値"]["極値確認時計秒"],
                          row["現極値"]["極値確認原行"]),
                         (8, values[8]["confirm"], values[8]["confirm_line"]))

    def test_左の等安値は拒否し右の等安値は許す(self) -> None:
        """左strict・右inclusiveを左右ともstrictへ置き換えない。

        引数: self (極値時点検証) はテスト。
        返り値: None。
        """
        values = series([(3, 950., 40.), (6, 960., 30.)])
        values[4]["low"] = 960.
        self.assertFalse(selected(run(values)[0], "押し戻り継続"))
        for positions in ((7,), (8,), (7, 8)):
            values = series(finish=10)
            for index in positions:
                values[index]["low"] = values[6]["low"]
            result, _ = run(values)
            self.assertEqual([r["現極値"]["中心番号"] for r in selected(result)], [6])
            reflected, _ = run([mirror(r) for r in values], [mirror(higher())])
            self.assertEqual([r["現極値"]["中心番号"] for r in selected(reflected)], [6])

    def test_三本と二十本の距離等号を含み二十一を除く(self) -> None:
        """隣接中心の距離を中心番号で数え、確認足距離へずらさない。

        引数: self (極値時点検証) はテスト。
        返り値: None。
        """
        for distance, count in ((3, 1), (20, 1), (21, 0)):
            values = series([(3, 970., 30.), (3+distance, 960., 40.)])
            rows = selected(run(values)[0])
            self.assertEqual(len(rows), count)
            if rows:
                self.assertEqual(rows[0]["極値間隔本数"], distance)

    def test_RSI未定義でも直前pivotを更新する(self) -> None:
        """途中のRSI未定義pivotを飛ばし古い都合のよい谷へ戻らない。

        引数: self (極値時点検証) はテスト。
        返り値: None。
        """
        for bad in (None, float("nan"), float("inf")):
            values = series([(3, 970., 30.), (6, 960., bad), (9, 950., 50.)])
            self.assertFalse(any(run(values)[0].values()))

    def test_距離不成立でも直前pivotを更新する(self) -> None:
        """21本離れた谷を見送った後、そこから3本の谷を隣接として使う。

        引数: self (極値時点検証) はテスト。
        返り値: None。
        """
        values = series([(3, 970., 30.), (24, 960., 40.), (27, 950., 50.)])
        rows = selected(run(values)[0])
        self.assertEqual([r["現極値"]["中心番号"] for r in rows], [27])
        self.assertEqual(rows[0]["前極値"]["中心番号"], 24)

    def test_準備不足と時間不成立でも直前pivotを更新する(self) -> None:
        """一回の発動不可を理由に古い谷と比較し直さない。

        引数: self (極値時点検証) はテスト。
        返り値: None。
        """
        for changes in ({"atr": None}, {"atr": 0.}, {"rsi": None}):
            values = series([(3, 970., 30.), (6, 960., 40.), (9, 950., 50.)])
            values[8].update(changes)
            rows = selected(run(values)[0])
            self.assertEqual([r["現極値"]["中心番号"] for r in rows], [9])
            self.assertEqual(rows[0]["前極値"]["中心番号"], 6)
        values = series([(3, 970., 30.), (6, 960., 40.), (9, 950., 50.)])
        # 後の足ほど残時間は短いので、旧pivot時点が不可・次が可となる上位準備で更新を検査する。
        upper = higher(confirm=values[10]["confirm"], end=values[10]["end"], confirm_line=values[10]["confirm_line"])
        rows = selected(run(values, [upper])[0])
        self.assertEqual(rows[0]["前極値"]["中心番号"], 6)
        result, quality = run(values, cutoff=values[8]["confirm"])
        self.assertFalse(any(result.values()))
        blocked = next(r for r in quality["全pivot記録"] if r["side"] == 1 and r["現極値"]["中心番号"] == 9)
        self.assertEqual(blocked["前極値"]["中心番号"], 6)
        self.assertFalse(blocked["時間条件成立"])

    def test_欠枠非公開と番号飛越は全隣接状態を切る(self) -> None:
        """missing0でもindexが飛べば前の谷との比較を禁止する。

        引数: self (極値時点検証) はテスト。
        返り値: None。
        """
        for kind in ("欠枠", "非公開", "番号飛越"):
            values = series([(3, 970., 30.), (9, 960., 40.)])
            if kind == "欠枠":
                values[6]["missing"] = 1
            elif kind == "非公開":
                values[6]["publish"] = False
            else:
                values.pop(6)
            self.assertFalse(any(run(values)[0].values()))


# ----------------------------------------
# RSI自身の山谷と混同せず、価格pivot中心のRSIと現判断RSIを使い分ける。

class 型とネック検証(unittest.TestCase):
    """反転/継続の厳密な不等号と現位置の追加選別を確認する。"""

    def test_一三五分と買売鏡像で反転が同じ位置に出る(self) -> None:
        """RSIを100−値、価格を2000−値へ反転して売買対称を確かめる。

        引数: self (型とネック検証) はテスト。
        返り値: None。
        """
        for size in (1, 3, 5):
            values = series(size=size)
            a, _ = run(values)
            b, _ = run([mirror(r) for r in values], [mirror(higher())])
            self.assertEqual([(r["index"], r["side"]) for r in selected(a)], [(8, 1)])
            self.assertEqual([(r["index"], r["side"]) for r in selected(b)], [(8, -1)])

    def test_価格または中心RSIの等号は型不成立(self) -> None:
        """同値の価格やRSIを乖離・継続に含めない。

        引数: self (型とネック検証) はテスト。
        返り値: None。
        """
        for centers in ([(3, 970., 30.), (6, 970., 40.)], [(3, 970., 30.), (6, 960., 30.)]):
            self.assertFalse(any(run(series(centers))[0].values()))

    def test_中心RSIは価格pivotに対応させ現RSIと分ける(self) -> None:
        """右2本のRSIの大小で乖離を置き換えず、判断RSIは有限性だけを課す。

        引数: self (型とネック検証) はテスト。
        返り値: None。
        """
        values = series()
        values[5]["rsi"], values[8]["rsi"] = 99., 1.
        rows = selected(run(values)[0])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["前極値"]["中心RSI14"], rows[0]["現極値"]["中心RSI14"]), (30., 40.))
        values[8]["rsi"] = None
        self.assertFalse(any(run(values)[0].values()))

    def test_継続だけが上位方向一致を必要とする(self) -> None:
        """準備済み逆方向でも反転を残し、継続は方向不一致で見送る。

        引数: self (型とネック検証) はテスト。
        返り値: None。
        """
        continuation = series([(3, 960., 40.), (6, 970., 30.)])
        self.assertEqual(len(selected(run(continuation)[0], "押し戻り継続")), 1)
        opposite = [mirror(higher())]
        self.assertFalse(selected(run(continuation, opposite)[0], "押し戻り継続"))
        self.assertEqual(len(selected(run(series(), opposite)[0])), 1)

    def test_下位EMA_ADX_BB_数量は未使用(self) -> None:
        """新しい不要指標や数量の準備を暗黙に足さない。

        引数: self (型とネック検証) はテスト。
        返り値: None。
        """
        values = series()
        for row in values:
            row.update(ema20=None, adx=None, bb_mean=None, bb_sd=None,
                       数量準備済=False, RVOL=None, 観測差分量=None)
        self.assertEqual(len(selected(run(values)[0])), 1)

    def test_ネックは両中心を除き現終値の厳密位置を使う(self) -> None:
        """中心足の大きい高値をネックへ混ぜず、同値は見送る。

        引数: self (型とネック検証) はテスト。
        返り値: None。
        """
        values = series()
        values[3]["high"], values[6]["high"] = 1100., 1090.
        values[4]["high"], values[5]["high"] = 1025., 1030.
        values[8].update(close=1030., high=1040.)
        a, _ = run(values)
        self.assertEqual(len(selected(a)), 1)
        self.assertFalse(selected(a, extra="ネック位置確認"))
        values[8]["close"] = 1035.
        b, _ = run(values)
        row = selected(b, extra="ネック位置確認")[0]
        self.assertEqual(row["ネック価格"], 1030.)
        self.assertTrue(row["ネック条件成立"])
        reflected, _ = run([mirror(r) for r in values], [mirror(higher())])
        self.assertEqual(len(selected(reflected, extra="ネック位置確認")), 1)

    def test_ネック未達を後続足へ待機させない(self) -> None:
        """確定足でネックを満たさなかった組を後から発動させない。

        引数: self (型とネック検証) はテスト。
        返り値: None。
        """
        values = series(finish=10)
        values[9].update(close=1035., high=1040.)
        values[10].update(close=1040., high=1045.)
        result, _ = run(values)
        self.assertEqual([r["index"] for r in selected(result)], [8])
        self.assertFalse(selected(result, extra="ネック位置確認"))

    def test_ネックは交差瞬間でなく現時点の位置を使う(self) -> None:
        """前足もネックより上なら交差ではないが位置条件は満たす。

        引数: self (型とネック検証) はテスト。
        返り値: None。
        """
        values = series()
        values[7].update(close=1030., high=1040.)
        values[8].update(close=1035., high=1040.)
        result, _ = run(values)
        row = selected(result, extra="ネック位置確認")[0]
        self.assertEqual(row["ネック価格"], 1020.)
        self.assertGreater(values[7]["close"], row["ネック価格"])

    def test_同時の高安pivotは両側更新し現終値改善で売買排他(self) -> None:
        """同じ中心が高値/安値になっても片側の状態を更新し忘れない。

        引数: self (型とネック検証) はテスト。
        返り値: None。
        """
        values = series()
        values[3]["high"], values[6]["high"] = 1040., 1030.
        result, quality = run(values, [mirror(higher())])
        rows = [r for v in result.values() for r in v]
        self.assertTrue(rows)
        self.assertEqual({r["side"] for r in rows}, {1})
        self.assertEqual(len(quality["全pivot記録"]), 4)


# ----------------------------------------
# 公開順・共通時間条件・コード固定を、未来成績を入力せずに検査する。

class 共通時点検証(unittest.TestCase):
    """要求の公開キーと準備を、中心足や未来上位足に置き換えない。"""

    def test_上位同時計の未来原行を使わない(self) -> None:
        """同じ時計でも現要求行より後の上位方向変更を先読みしない。

        引数: self (共通時点検証) はテスト。
        返り値: None。
        """
        values = series([(3, 960., 40.), (6, 970., 30.)])
        current = values[-1]
        later = mirror(higher(end=current["end"], confirm=current["confirm"],
                              confirm_line=current["confirm_line"]+1))
        self.assertEqual(len(selected(run(values, [higher(), later])[0], "押し戻り継続")), 1)
        later["confirm_line"] = current["confirm_line"]
        self.assertFalse(selected(run(values, [higher(), later])[0], "押し戻り継続"))

    def test_上位未公開と足終了より後の上位を使わない(self) -> None:
        """方向の値だけがあっても未公開/未来終了の上位は準備としない。

        引数: self (共通時点検証) はテスト。
        返り値: None。
        """
        values = series()
        self.assertFalse(any(run(values, [higher(publish=False)])[0].values()))
        self.assertFalse(any(run(values, [higher(end=values[-1]["end"]+1)])[0].values()))

    def test_停止等号と残六十分境界を厳密に扱う(self) -> None:
        """cutoff等号では発動せず、期限残60分の等号では候補を残す。

        引数: self (共通時点検証) はテスト。
        返り値: None。
        """
        values = series()
        now = values[-1]["confirm"]
        self.assertFalse(any(run(values, cutoff=now)[0].values()))
        self.assertEqual(len(selected(run(values, deadline=now+3600.)[0])), 1)
        self.assertFalse(any(run(values, deadline=now+3599.)[0].values()))

    def test_確認遅延は発動へ記録し足終了前公開を拒否する(self) -> None:
        """30秒超の候補を黙って有利な足終了時刻へ戻さない。

        引数: self (共通時点検証) はテスト。
        返り値: None。
        """
        values = series()
        values[-1]["confirm"] += 31.
        row = selected(run(values)[0])[0]
        self.assertEqual(row["確認遅延秒"], 31.)
        self.assertEqual(row["要求時計秒"], values[-1]["confirm"])
        values[-1]["confirm"] = values[-1]["end"]-1
        with self.assertRaises(ValueError):
            run(values)

    def test_未来ラベルを変えても発動IDとpivot記録は不変(self) -> None:
        """将来の成功や利益を山谷の登録・発動判定へ混ぜない。

        引数: self (共通時点検証) はテスト。
        返り値: None。
        """
        values = series()
        a, qa = run(values)
        for row in values:
            row.update(ラベル="順行先着", 将来損益=999999)
        b, qb = run(values)
        self.assertEqual({k: [r["イベントID"] for r in v] for k, v in a.items()},
                         {k: [r["イベントID"] for r in v] for k, v in b.items()})
        self.assertEqual(qa["全pivot記録"], qb["全pivot記録"])


class 実行側検証(unittest.TestCase):
    """12案と旧X0を固定し、最終1場を未見としない。"""

    def test_十二案とX0と極値条件を固定する(self) -> None:
        """尺度・左右本数・距離・RSI期間・出口を事後に追加しない。

        引数: self (実行側検証) はテスト。
        返り値: None。条件JSONだけを読む。
        """
        driver = module(Path(__file__).with_name("検証.py"), "RSI構造driver候補合成")
        config = driver.W.read_json(driver.STUDY / "条件.json")
        rows = driver.sources(config)
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({r["入口ID"] for r in rows}), 12)
        self.assertTrue(config["全65場既使用"])
        for key, value in (("左足本数", 1), ("右足本数", 3), ("中心間隔下限本数", 2),
                           ("中心間隔上限本数", 21), ("RSI期間", 7)):
            bad = deepcopy(config)
            bad["極値条件"][key] = value
            with self.assertRaises(ValueError):
                driver.sources(bad)
        bad = deepcopy(config)
        bad["出口"] = [{"出口ID": "X1"}]
        with self.assertRaises(ValueError):
            driver.sources(bad)

    def test_旧十一運用と新合成を固定する(self) -> None:
        """未使用の数量や構造損切りを継承せず実際の旧11固定依存を検査する。

        引数: self (実行側検証) はテスト。
        返り値: None。架空試行への書込をmockし正式固定は作らない。
        """
        driver = module(Path(__file__).with_name("検証.py"), "RSI構造driver固定合成")
        study = ROOT / "work/RSI構造/合成固定用の未作成先"
        self.assertFalse(study.exists())
        original_sha = driver.O.sha

        def synthetic_sha(path: Path) -> str:
            """架空試行内だけ仮SHAにし、実依存は本物のSHAで検査する。

            引数: path (Path) は固定対象。
            返り値: str は合成値または実SHA256。
            """
            return "合成SHA" if path.is_relative_to(study) else original_sha(path)

        with patch.object(driver.O, "sha", side_effect=synthetic_sha), patch.object(driver.W, "write_json"):
            fixed = driver.freeze(study)
        pins = fixed["ファイルSHA256"]
        for name in ("入口.py", "検証.py", "合成検証.py"):
            self.assertIn("scripts/RSI構造/"+name, pins)
        self.assertIn("scripts/テクニカル循環/運用.py", pins)
        self.assertIn("study/00011_順行と反転のチャート構造と利益回収/固定.json", pins)
        self.assertNotIn("scripts/数量反転/数量.py", pins)
        self.assertNotIn("scripts/反転確認/運用.py", pins)

    def test_旧X0は下位EMA_ADX_BBなしでも新規返済できる(self) -> None:
        """入口で不要とした下位指標を固定出口が暗黙の必須条件へ戻さない。

        引数: self (実行側検証) はテスト。
        返り値: None。合成BBOだけを旧X0へ渡す。
        """
        driver = module(Path(__file__).with_name("検証.py"), "RSI構造driver接続合成")
        config = driver.W.read_json(driver.STUDY / "条件.json")
        engine = module(ROOT/"scripts/テクニカル循環/運用.py", "RSI構造の固定X0接続合成")
        values = series()
        row = selected(run(values)[0])[0]
        now, line = row["要求時計秒"], row["要求原板行"]
        events = [SimpleNamespace(now=now, line=line, bid=995., ask=1000., valid=True),
                  SimpleNamespace(now=now+1, line=line+1, bid=995., ask=1000., valid=True),
                  SimpleNamespace(now=now+2, line=line+2, bid=1250., ask=1255., valid=True),
                  SimpleNamespace(now=now+3, line=line+3, bid=1250., ask=1255., valid=True),
                  SimpleNamespace(now=596., line=line+4, bid=1250., ask=1255., valid=True)]
        state, quality = engine.replay(events, [row], values, "合成場", "合成候補_X0",
                                        config["運用"], {"出口ID": "X0"}, "反転", (0., 600., 590., 595.))
        self.assertEqual(len(state.fills), 2)
        self.assertEqual(state.trades[0]["返済理由"], "利確")
        self.assertEqual(state.trades[0]["基準純損益円"], 2478.)
        self.assertIsNone(state.trades[0]["入口中心線目標"])
        self.assertEqual(quality["終了建玉"], 0)

    def test_既使用最終一場を入口目標選定へ混ぜない(self) -> None:
        """旧40/24が同じなら既使用最終場の成績で目標判定を変えない。

        引数: self (実行側検証) はテスト。
        返り値: None。合成期間集計だけを使う。
        """
        driver = module(Path(__file__).with_name("検証.py"), "RSI構造driver期間合成")
        config = driver.W.read_json(driver.STUDY / "条件.json")
        result = {p: {**limits, "確認率": .7,
                       "30分間引き_約定候補数": config["間引き必要件数"][p],
                       "30分間引き_確認率": .7}
                  for p, limits in config["入口支持"].items()}
        result["後続検査"] = {"確認率": 0.}
        self.assertEqual(driver.entry_flags(result, config), (True, True))
        result["後続検査"] = {"確認率": 1.}
        self.assertEqual(driver.entry_flags(result, config), (True, True))
        result["学習"]["確認率"] = .699999
        self.assertEqual(driver.entry_flags(result, config), (True, False))


def run_tests() -> dict:
    """合成検証の明示合否・記録・対象SHAをGit外へ保存する。

    引数: なし。実データの数値再生は呼ばない。
    返り値: dict は件数・失敗・エラー・版指紋。
    """
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "失敗": [{"検査": str(t), "内容": text} for t, text in result.failures],
              "エラー": [{"検査": str(t), "内容": text} for t, text in result.errors],
              "ファイルSHA256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("検証.py"))},
              "範囲": "左右2本確認・中心/判断時計・左strict右inclusive・隣接pivot更新・3/20・欠枠非公開/飛越・RSI型/鏡像・ネック中心除外/strict/待機なし・公開上位・不要指標なし・12X0固定依存。実データ再生なし。",
              "実行記録": stream.getvalue()}
    target = ROOT / "work/RSI構造/合成検証.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(stream.getvalue())
    return report


if __name__ == "__main__":
    if not run_tests()["全件成功"]:
        raise SystemExit(1)
