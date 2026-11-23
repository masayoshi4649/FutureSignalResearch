"""00016の逆向き入口と一件監視の失効・満了・因果的消費を合成確認する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def module(path: Path, name: str):
    """合成対象を数値再生なしで読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: object はモジュール。成績や原板は読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


I = module(Path(__file__).with_name("入口.py"), "反転失効の合成対象")
CONFIG = {"時間足分": [1, 3, 5], "入口系統": ["単純逆向き", "価格失効待ち"],
          "補助": ["なし", "15分方向一致"], "出口": [{"出口ID": "X0"}],
          "監視条件": {"下限本数": 1, "上限本数": 6, "最新一件": True, "同足発動": False},
          "残り時間下限分": 60, "確認遅延上限秒": 30}


def frame(index: int, size: int = 1, **changes) -> dict:
    """公開RSI/ATRと時点キーだけが準備済みの合成足を作る。

    引数: index/size (int) は番号/尺度、changes (dict) は上書き。
    返り値: dict は下位EMA/ADX/数量を未準備とした足。
    """
    start, end = index*size*60., (index+1)*size*60.
    return {"index": index, "minutes": size, "start": start, "end": end,
            "confirm": end, "confirm_line": index*10+1, "publish": True, "missing": 0,
            "open": 1000., "close": 1000., "high": 1020., "low": 990.,
            "rsi": 50., "atr": 20., "ema20": None, "adx": None, "bb_mean": None,
            "bb_sd": None, "数量準備済": False, **changes}


def higher(**changes) -> dict:
    """買い方向の利用可能な15分足を作る。

    引数: changes (dict) は上書き。
    返り値: dict は公開キーとEMA20前値を持つ上位足。
    """
    return {"index": 0, "publish": True, "end": 0., "confirm": 0., "confirm_line": 0,
            "close": 1100., "ema20": 1050., "ema20_previous": 1000., **changes}


def mirror(value: dict) -> dict:
    """価格とRSIの鏡像を作る。

    引数: value (dict) は下位/上位足。
    返り値: dict は価格2000−元値、RSI100−元値。
    """
    row = deepcopy(value)
    for key in ("open", "close", "ema20", "ema20_previous", "bb_mean"):
        if row.get(key) is not None:
            row[key] = 2000.-row[key]
    if "high" in row:
        row["high"], row["low"] = 2000.-value["low"], 2000.-value["high"]
    if row.get("rsi") is not None:
        row["rsi"] = 100.-row["rsi"]
    return row


def real_series(size: int = 1) -> list[dict]:
    """固定15の実価格式で一つの反転買い乖離が出る経路を作る。

    引数: size (int) は尺度。
    返り値: list[dict] は中心3/6を足8で確認する二谷。
    """
    values = [frame(i, size) for i in range(9)]
    values[3].update(low=970., rsi=30.)
    values[6].update(low=960., rsi=40.)
    values[8]["close"] = 1005.
    return values


def prepared(index: int = 8, side: int = 1, size: int = 1,
             price: float | None = None, **changes) -> dict:
    """実際の固定15信号を複製し、状態境界用の指定位置へ移す。

    引数: index/side/size (int) は準備番号/元方向/尺度、price (float|None) は第2極値、
    changes (dict) は判断属性の上書き。
    返り値: dict は固定15と同じ完全schemaの準備。状態テストの入力を作る用途。
    """
    values = real_series(size)
    uppers = [higher()]
    if side == -1:
        values, uppers = [mirror(r) for r in values], [mirror(higher())]
    output, _ = I.BASE.generate(values, uppers, "合成場", 100000., 200000., deepcopy(I.BASE_CONFIG))
    row = deepcopy(output[f"{size}分_反転乖離_なし"][0])
    row.update(frame(index, size, **changes))
    row.update(場="合成場", side=side, 方向="買い" if side == 1 else "売り",
               イベントID=f"準備_{size}_{index}_{side}", 要求時計秒=row["confirm"],
               要求原板行=row["confirm_line"], 確認遅延秒=row["confirm"]-row["end"],
               足終了時計秒=row["end"])
    row["現極値"]["極値価格"] = (960. if side == 1 else 1040.) if price is None else price
    return row


def run(values: list[dict], preparations: list[dict] | None = None,
        uppers: list[dict] | None = None, cutoff: float = 100000.,
        deadline: float = 200000.) -> tuple[dict, dict]:
    """合成準備を差し替え可能にし、監視の境界だけを検査する。

    引数: values/preparations/uppers (list[dict]|None) は下位足/準備/上位足、
    cutoff/deadline (float) は停止/期限秒。
    返り値: tuple[dict,dict] は入口と全監視記録。準備None時は旧15をそのまま使う。
    """
    higher_rows = [higher()] if uppers is None else uppers
    if preparations is None:
        return I.generate(values, higher_rows, "合成場", cutoff, deadline, deepcopy(CONFIG))
    size = values[0]["minutes"]
    output = {f"{size}分_{family}_{extra}": [] for family in ("反転乖離", "押し戻り継続")
              for extra in ("なし", "ネック位置確認")}
    output[f"{size}分_反転乖離_なし"] = deepcopy(preparations)
    with patch.object(I.BASE, "generate", return_value=(output, {"全pivot記録": []})):
        return I.generate(values, higher_rows, "合成場", cutoff, deadline, deepcopy(CONFIG))


def selected(output: dict, family: str = "価格失効待ち", extra: str = "なし") -> list[dict]:
    """指定方式と補助の入口を読む。

    引数: output (dict) は結果、family/extra (str) は方式/補助。
    返り値: list[dict] は一致する入口。
    """
    return [r for key, rows in output.items() if key.endswith("_"+family+"_"+extra) for r in rows]


def frames(last: int = 15, size: int = 1) -> list[dict]:
    """足8の準備を監視できる連続公開経路を作る。

    引数: last/size (int) は末尾番号/尺度。
    返り値: list[dict] は当初失効しない終値1000の足。
    """
    return [frame(i, size) for i in range(last+1)]


# ----------------------------------------
# 同じ準備から逆向きにする対照と、未来の失効を待つ入口を区別する。

class 方向と元信号検証(unittest.TestCase):
    """準備自体は固定15と同値に保ち、実際の新規方向へだけ補助を課す。"""

    def test_固定十五の準備から一三五分で逆向きにする(self) -> None:
        """実価格の反転買い準備を、元時点の売り入口へ変える。

        引数: self (方向と元信号検証) はテスト。
        返り値: None。
        """
        for size in (1, 3, 5):
            values = real_series(size)
            actual, quality = run(values)
            base, _ = I.BASE.generate(values, [higher()], "合成場", 100000., 200000., deepcopy(I.BASE_CONFIG))
            origin = base[f"{size}分_反転乖離_なし"][0]
            row = selected(actual, "単純逆向き")[0]
            self.assertEqual((row["index"], row["side"]), (8, -1))
            self.assertEqual((row["要求時計秒"], row["要求原板行"]),
                             (origin["要求時計秒"], origin["要求原板行"]))
            self.assertEqual(quality["全準備記録"][0]["元信号"], origin)
            self.assertEqual(row["元準備イベントID"], origin["イベントID"])
            self.assertFalse(selected(actual))

    def test_上位方向は元買いでなく実売りへ要求する(self) -> None:
        """元買い方向の上位一致を逆売りの一致と誤認しない。

        引数: self (方向と元信号検証) はテスト。
        返り値: None。
        """
        values, prep = frames(), prepared()
        a, _ = run(values, [prep])
        b, _ = run(values, [prep], [mirror(higher())])
        self.assertEqual(len(selected(a, "単純逆向き")), 1)
        self.assertFalse(selected(a, "単純逆向き", "15分方向一致"))
        self.assertEqual(len(selected(b, "単純逆向き", "15分方向一致")), 1)

    def test_売買鏡像は元売りから実買いへ変える(self) -> None:
        """売り準備の第2高値超過を買いへ対称化する。

        引数: self (方向と元信号検証) はテスト。
        返り値: None。
        """
        values = frames(9)
        values[9].update(close=1045., high=1050.)
        result, _ = run(values, [prepared(side=-1)])
        self.assertEqual([(r["index"], r["side"]) for r in selected(result)], [(9, 1)])
        self.assertEqual(selected(result, "単純逆向き")[0]["side"], 1)
        self.assertEqual(len(selected(result, extra="15分方向一致")), 1)

    def test_三十秒超準備は両方式共通除外し等号は残す(self) -> None:
        """遅延準備で逆向きだけ発動させたり監視だけ登録したりしない。

        引数: self (方向と元信号検証) はテスト。
        返り値: None。
        """
        for delay, count in ((30., 1), (31., 0)):
            values = frames(9)
            values[8]["confirm"] += delay
            values[9].update(close=955., low=950.)
            prep = prepared(confirm=values[8]["confirm"])
            result, _ = run(values, [prep])
            self.assertEqual(len(selected(result, "単純逆向き")), count)
            self.assertEqual(len(selected(result)), count)


class 監視状態検証(unittest.TestCase):
    """監視は最新一件、失効の最初の一足を条件不成立でも消費する。"""

    def test_同足不可と次一から六を含み七で満了する(self) -> None:
        """同足の失効位置を利用せず、1/6だけを期限内とする。

        引数: self (監視状態検証) はテスト。
        返り値: None。
        """
        for age, count in ((0, 0), (1, 1), (6, 1), (7, 0)):
            values = frames(max(9, 8+age))
            values[8+age].update(close=955., low=950.)
            result, _ = run(values, [prepared()])
            self.assertEqual(len(selected(result)), count)
            if count:
                self.assertEqual(selected(result)[0]["index"], 8+age)
                self.assertEqual(selected(result)[0]["待機本数"], age)

    def test_失効線等号では消費せず次の厳密超過で発動する(self) -> None:
        """終値=第2安値を失効扱いせず、次の下抜けを初着とする。

        引数: self (監視状態検証) はテスト。
        返り値: None。
        """
        values = frames(11)
        values[9].update(close=960., low=950.)
        values[10].update(close=955., low=950.)
        values[11].update(close=950., low=945.)
        rows = selected(run(values, [prepared()])[0])
        self.assertEqual([r["index"] for r in rows], [10])

    def test_方向を跨いで最新準備一件へ置換する(self) -> None:
        """買い準備と売り準備の二件を同時に残さない。

        引数: self (監視状態検証) はテスト。
        返り値: None。
        """
        values = frames(11)
        values[10].update(close=955., low=950.)
        values[11].update(close=1045., high=1050.)
        rows = selected(run(values, [prepared(), prepared(9, side=-1)])[0])
        self.assertEqual([(r["index"], r["side"]) for r in rows], [(11, 1)])

    def test_旧監視の判定を新登録より先に行う(self) -> None:
        """旧買い準備の失効と新売り準備が同足でも旧の売り発動を失わない。

        引数: self (監視状態検証) はテスト。
        返り値: None。
        """
        values = frames(10)
        values[9].update(close=955., low=950.)
        values[10].update(close=1045., high=1050.)
        result, _ = run(values, [prepared(), prepared(9, side=-1)])
        self.assertEqual([(r["index"], r["side"]) for r in selected(result)], [(9, -1), (10, 1)])
        self.assertEqual([(r["index"], r["side"]) for r in selected(result, "単純逆向き")], [(8, -1), (9, 1)])

    def test_準備不足と方向不一致でも初回失効を消費する(self) -> None:
        """後から条件がそろっても同じ準備を使い直さない。

        引数: self (監視状態検証) はテスト。
        返り値: None。
        """
        for changes in ({"rsi": None}, {"atr": None}, {"atr": 0.}, {"atr": float("inf")}):
            values = frames(10)
            values[9].update(close=955., low=950., **changes)
            values[10].update(close=950., low=945.)
            self.assertFalse(selected(run(values, [prepared()])[0]))
        values = frames(10)
        values[9].update(close=955., low=950.)
        values[10].update(close=950., low=945.)
        upper = mirror(higher(end=values[10]["end"], confirm=values[10]["confirm"], confirm_line=values[10]["confirm_line"]))
        result, _ = run(values, [prepared()], [higher(), upper])
        self.assertEqual([r["index"] for r in selected(result)], [9])
        self.assertFalse(selected(result, extra="15分方向一致"))

    def test_時間不成立や確認遅延でも初回失効を消費する(self) -> None:
        """新規できない初着を見逃し、後足の価格で再発動しない。

        引数: self (監視状態検証) はテスト。
        返り値: None。
        """
        values = frames(10)
        values[9].update(close=955., low=950.)
        values[10].update(close=950., low=945.)
        result, quality = run(values, [prepared()], cutoff=values[9]["confirm"])
        self.assertFalse(selected(result))
        self.assertTrue(quality["全監視記録"])
        values[9]["confirm"] += 31.
        result, _ = run(values, [prepared()])
        self.assertFalse(selected(result))

    def test_上位未準備で見送っても失効を消費する(self) -> None:
        """上位が後で利用可能になっても以前の失効準備を使い直さない。

        引数: self (監視状態検証) はテスト。
        返り値: None。状態入力の境界として旧準備だけを差し替える。
        """
        values = frames(10)
        values[9].update(close=955., low=950.)
        values[10].update(close=950., low=945.)
        upper = mirror(higher(end=values[10]["end"], confirm=values[10]["confirm"],
                              confirm_line=values[10]["confirm_line"]))
        result, quality = run(values, [prepared()], [upper])
        self.assertFalse(selected(result))
        consumed = [r for r in quality["全監視記録"] if r["動作"] == "失効消費"]
        self.assertEqual([r["判断足番号"] for r in consumed], [9])

    def test_遅延新準備を除外しても旧監視を先に判定する(self) -> None:
        """30秒超の新準備が旧監視の失効や継続を取り消さない。

        引数: self (監視状態検証) はテスト。
        返り値: None。
        """
        values = frames(10)
        values[9]["confirm"] += 31.
        values[10].update(close=955., low=950.)
        bad = prepared(9, side=-1, confirm=values[9]["confirm"])
        rows = selected(run(values, [prepared(), bad])[0])
        self.assertEqual([(r["index"], r["side"]) for r in rows], [(10, -1)])

    def test_欠枠非公開番号飛越で監視を全リセットする(self) -> None:
        """元の極値線を欠けた価格区間の後で再利用しない。

        引数: self (監視状態検証) はテスト。
        返り値: None。
        """
        for kind in ("欠枠", "非公開", "番号飛越"):
            values = frames(10)
            values[10].update(close=955., low=950.)
            if kind == "欠枠":
                values[9]["missing"] = 1
            elif kind == "非公開":
                values[9]["publish"] = False
            else:
                values.pop(9)
            self.assertFalse(selected(run(values, [prepared()])[0]))

    def test_別セッション呼出へ監視を持ち越さない(self) -> None:
        """準備が未失効のまま終わっても次の呼出で元の極値線を使わない。

        引数: self (監視状態検証) はテスト。
        返り値: None。
        """
        run(frames(8), [prepared()])
        values = frames(9)
        values[9].update(close=955., low=950.)
        self.assertFalse(any(run(values, [])[0].values()))


# ----------------------------------------
# 実発動の属性と上位公開を準備時点の値へ差し戻さない。

class 発動時点検証(unittest.TestCase):
    """RSI/ATR/時計/上位方向は失効を観測した現在足のものを使う。"""

    def test_現ATR_RSI_要求キーを使い準備と区別する(self) -> None:
        """待機中に変わったATRやRSIを新規発動へ保存する。

        引数: self (発動時点検証) はテスト。
        返り値: None。
        """
        values = frames(9)
        values[9].update(close=955., low=950., atr=55., rsi=18.)
        row = selected(run(values, [prepared()])[0])[0]
        self.assertEqual((row["atr"], row["rsi"]), (55., 18.))
        self.assertEqual((row["要求時計秒"], row["要求原板行"]), (values[9]["confirm"], values[9]["confirm_line"]))

    def test_上位同時計の未来原行を利用しない(self) -> None:
        """同時計でも失効発動の原行より後の上位変更を先読みしない。

        引数: self (発動時点検証) はテスト。
        返り値: None。
        """
        values = frames(9)
        values[9].update(close=955., low=950.)
        current = values[9]
        upper = mirror(higher(end=current["end"], confirm=current["confirm"], confirm_line=current["confirm_line"]+1))
        a, _ = run(values, [prepared()], [higher(), upper])
        self.assertFalse(selected(a, extra="15分方向一致"))
        upper["confirm_line"] = current["confirm_line"]
        b, _ = run(values, [prepared()], [higher(), upper])
        self.assertEqual(len(selected(b, extra="15分方向一致")), 1)

    def test_上位未来終了と未公開を使わない(self) -> None:
        """値があっても現在の失効足より後の上位終了や未公開足は準備にしない。

        引数: self (発動時点検証) はテスト。
        返り値: None。
        """
        values = frames(9)
        values[9].update(close=955., low=950.)
        for upper in (higher(publish=False), higher(end=values[9]["end"]+1)):
            self.assertFalse(selected(run(values, [prepared()], [upper])[0]))

    def test_残六十分等号と停止等号を扱う(self) -> None:
        """実失効時点に残60分以上を要求し、停止等号では発動しない。

        引数: self (発動時点検証) はテスト。
        返り値: None。
        """
        values = frames(9)
        values[9].update(close=955., low=950.)
        now = values[9]["confirm"]
        self.assertEqual(len(selected(run(values, [prepared()], deadline=now+3600.)[0])), 1)
        self.assertFalse(selected(run(values, [prepared()], deadline=now+3599.)[0]))
        self.assertFalse(selected(run(values, [prepared()], cutoff=now)[0]))

    def test_不要下位指標と未来ラベルで発動を変えない(self) -> None:
        """下位EMA/ADX/数量の準備や将来の利益で監視の状態を変えない。

        引数: self (発動時点検証) はテスト。
        返り値: None。
        """
        values = frames(9)
        values[9].update(close=955., low=950.)
        prep = prepared()
        a, _ = run(values, [prep])
        for row in values:
            row.update(ema20=None, adx=None, 数量準備済=False, ラベル="順行先着", 将来損益=999999.)
        b, _ = run(values, [prep])
        self.assertEqual({k: [r["イベントID"] for r in v] for k, v in a.items()},
                         {k: [r["イベントID"] for r in v] for k, v in b.items()})

    def test_同足複数準備を入力矛盾として拒否する(self) -> None:
        """最新一件の選び方を保存順へ依存させない。

        引数: self (発動時点検証) はテスト。
        返り値: None。
        """
        with self.assertRaises(ValueError):
            run(frames(), [prepared(), prepared(side=-1)])


class 実行側検証(unittest.TestCase):
    """新12案と実継承元15/11を固定し、既使用最終場を選定へ混ぜない。"""

    def test_十二案とX0と一件六本監視を固定する(self) -> None:
        """方向別監視や別待機期間・出口を後から追加しない。

        引数: self (実行側検証) はテスト。
        返り値: None。条件JSONだけを読む。
        """
        driver = module(Path(__file__).with_name("検証.py"), "反転失効driver候補合成")
        config = driver.W.read_json(driver.STUDY/"条件.json")
        rows = driver.sources(config)
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({r["入口ID"] for r in rows}), 12)
        self.assertEqual({r["役割"] for r in rows}, {"順行"})
        self.assertTrue(config["全65場既使用"])
        for key, value in (("下限本数", 0), ("上限本数", 7), ("最新一件", False), ("同足発動", True)):
            bad = deepcopy(config)
            bad["監視条件"][key] = value
            with self.assertRaises(ValueError):
                driver.sources(bad)
        bad = deepcopy(config)
        bad["出口"] = [{"出口ID": "X1"}]
        with self.assertRaises(ValueError):
            driver.sources(bad)

    def test_準備十五と実運用十一と合成を固定する(self) -> None:
        """固定15を読取利用し、数量や構造損切りへ依存しない。

        引数: self (実行側検証) はテスト。
        返り値: None。正式書込をmockにして実固定依存だけSHA照合する。
        """
        driver = module(Path(__file__).with_name("検証.py"), "反転失効driver固定合成")
        study = ROOT/"work/反転失効/合成固定用の未作成先"
        self.assertFalse(study.exists())
        original_sha = driver.O.sha

        def synthetic_sha(path: Path) -> str:
            """架空試行内だけ仮SHAとし、実際の継承元は本物で照合する。

            引数: path (Path) は対象。
            返り値: str は合成値または実SHA256。
            """
            return "合成SHA" if path.is_relative_to(study) else original_sha(path)

        with patch.object(driver.O, "sha", side_effect=synthetic_sha), patch.object(driver.W, "write_json"):
            locked = driver.freeze(study)
        pins = locked["ファイルSHA256"]
        for name in ("入口.py", "検証.py", "合成検証.py"):
            self.assertIn("scripts/反転失効/"+name, pins)
        self.assertIn("scripts/RSI構造/入口.py", pins)
        self.assertIn("study/00015_RSIの山谷と価格構造/固定.json", pins)
        self.assertIn("scripts/テクニカル循環/運用.py", pins)
        self.assertNotIn("scripts/数量反転/数量.py", pins)

    def test_既使用最終一場を支持と入口目標へ使わない(self) -> None:
        """旧40/24の集計が同じなら最終場の値で選定判定を変えない。

        引数: self (実行側検証) はテスト。
        返り値: None。実成績の代わりに合成期間集計を渡す。
        """
        driver = module(Path(__file__).with_name("検証.py"), "反転失効driver期間合成")
        config = driver.W.read_json(driver.STUDY/"条件.json")
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
    """合成合否・記録・対象SHAをGit外へ保存する。

    引数: なし。実データ再生は呼ばない。
    返り値: dict は検査件数・失敗・エラー・版指紋。
    """
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "失敗": [{"検査": str(t), "内容": text} for t, text in result.failures],
              "エラー": [{"検査": str(t), "内容": text} for t, text in result.errors],
              "ファイルSHA256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("検証.py"))},
              "範囲": "固定15準備・逆向き/実入口上位方向・最新一件/旧先判定・同足不可/1〜6/7満了/strict失効・不可でも消費・準備遅延共通除外・現属性と公開上位・欠枠/非公開/番号飛越/場間reset・12X0依存。実データ再生なし。",
              "実行記録": stream.getvalue()}
    target = ROOT/"work/反転失効/合成検証.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(stream.getvalue())
    return report


if __name__ == "__main__":
    if not run_tests()["全件成功"]:
        raise SystemExit(1)
