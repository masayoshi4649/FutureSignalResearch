"""利益保護と役割別出口の時点・境界・鏡像を合成気配で検証する。"""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import io
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
import unittest


ROOT = Path(__file__).resolve().parents[2]
SESSION = "2026-10-01_Day"
BOUNDS = (0., 1000., 900., 950.)
CONFIG = {"数量": 1, "倍率": 10, "呼値pt": 5, "利確pt": 250, "保護逆行pt": 125,
          "片道手数料円": 11, "片道追加滑りpt": [0, 5, 10], "新規待機秒": 1,
          "新規有効秒": 30, "返済待機秒": 1, "正常板空白注意秒": 300}


def module(path: Path, name: str) -> Any:
    """合成検査対象をファイルから読み込む。

    引数: path (Path) はコード、name (str) は読込名。
    返り値: Any はモジュール。実データは読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


E = module(ROOT / "scripts/利益回収/運用.py", "合成利益回収運用")


def policy(name: str) -> dict:
    """六つの固定出口を合成用に指定する。

    引数: name (str) はP00〜P05。
    返り値: dict は追加出口条件。
    """
    result = {"出口ID": name}
    if name == "P01":
        result.update(床起動pt=20, 床利益pt=10)
    elif name in ("P02", "P05"):
        result.update(床起動pt=50, 床利益pt=20)
    elif name == "P03":
        result["ATR追尾"] = True
    if name in ("P04", "P05"):
        result["指標出口"] = True
    return result


def signal(now: float = 0, line: int = 1, side: int = 1, event: str = "入口1",
           atr: float = 20, mean: float | None = 1100) -> dict:
    """正常な特徴を持つ合成入口要求を作る。

    引数: now (float) は要求秒、line (int) は原行、side (int) は方向、
    event (str) は一意ID、atr (float) は入口ATR、mean (float|None) は固定中心。
    返り値: dict は入口。
    """
    return {"イベントID": event, "場": SESSION, "要求時計秒": now, "要求原板行": line,
            "方向": "買い" if side == 1 else "売り", "side": side, "確認遅延秒": 0,
            "atr": atr, "low": 980, "high": 1020, "bb_mean": mean}


def quote(now: float, line: int, bid: float, ask: float | None = None, valid: bool = True) -> Any:
    """合成正常板イベントを作る。

    引数: now (float) は価格時計、line (int) は原行、bid/ask (float|None) は気配、
    valid (bool) は正常性。ask省略時はbid+5。
    返り値: Any は運用入力イベント。
    """
    return SimpleNamespace(now=now, line=line, bid=bid, ask=bid + 5 if ask is None else ask, valid=valid)


def frame(end: float, confirm: float, line: int, close: float = 995,
          ema: float | None = 1000, publish: bool = True) -> dict:
    """合成の同尺度確定足を作る。

    引数: end/confirm (float) は終了・公開秒、line (int) は公開原行、
    close (float) は終値、ema (float|None) はEMA20、publish (bool) は公開状態。
    返り値: dict は確定足。
    """
    return {"end": end, "confirm": confirm, "confirm_line": line,
            "close": close, "ema20": ema, "publish": publish}


def entered(name: str = "P01", side: int = 1, role: str = "順行",
            atr: float = 20, mean: float | None = 1100) -> Any:
    """時刻1で1000に新規済みの合成状態を作る。

    引数: name/role (str) は出口と役割、side (int) は方向、atr (float) は固定ATR、
    mean (float|None) は入口中心線。
    返り値: Any は一建玉の状態。
    """
    row = signal(side=side, atr=atr, mean=mean)
    state = E.利益保護状態(SESSION, "合成", deepcopy(CONFIG), policy(name), role, [row], BOUNDS)
    state.signal_group([row])
    state.quote(1, 2, 995 if side == 1 else 1000, 1000 if side == 1 else 1005)
    return state


# ----------------------------------------
# 床・ATR追尾・元保護優先・一秒後の方向別BBO約定。

class 利益保護検証(unittest.TestCase):
    """利益保護の数値境界と鏡像を検査する。"""

    def test_P01は二十未満で起動しない(self) -> None:
        """床起動前の通常反落を許す。

        引数: なし。
        返り値: None。
        """
        state = entered()
        state.quote(2, 3, 1015, 1020)
        state.quote(3, 4, 1005, 1010)
        self.assertIsNone(state.pending)
        self.assertFalse(state.position["armed"])

    def test_P01は二十等号起動十等号要求(self) -> None:
        """床の両境界を等号で確認する。

        引数: なし。
        返り値: None。
        """
        state = entered()
        state.quote(2, 3, 1020, 1025)
        self.assertTrue(state.position["armed"])
        state.quote(3, 4, 1010, 1015)
        self.assertEqual(state.pending["reason"], "利益床")
        self.assertEqual(state.pending["time"], 3)

    def test_床要求は同時計後続原行で約定しない(self) -> None:
        """要求後一秒を満たすまで返済を保留する。

        引数: なし。
        返り値: None。
        """
        state = entered()
        state.quote(2, 3, 1020, 1025)
        state.quote(3, 4, 1010, 1015)
        state.quote(3, 5, 1005, 1010)
        self.assertEqual(len(state.trades), 0)
        state.quote(4, 6, 1000, 1005)
        self.assertEqual(state.trades[0]["返済価格"], 1000)
        self.assertEqual(state.trades[0]["基準純損益円"], -22)

    def test_P01売りはAskで鏡像(self) -> None:
        """売りの順行・床・返済方向を確認する。

        引数: なし。
        返り値: None。
        """
        state = entered(side=-1)
        state.quote(2, 3, 975, 980)
        state.quote(3, 4, 985, 990)
        self.assertEqual(state.pending["reason"], "利益床")
        state.quote(4, 5, 990, 995)
        self.assertEqual(state.trades[0]["粗損益円"], 50)
        self.assertEqual(state.trades[0]["基準純損益円"], 28)

    def test_P02は五十の含みから二十で要求(self) -> None:
        """別の床設定をP01と混ぜない。

        引数: なし。
        返り値: None。
        """
        state = entered("P02")
        state.quote(2, 3, 1045, 1050)
        state.quote(3, 4, 1020, 1025)
        self.assertIsNone(state.pending)
        state.quote(4, 5, 1050, 1055)
        state.quote(5, 6, 1020, 1025)
        self.assertEqual(state.pending["reason"], "利益床")

    def test_固定保護を利益床より先に要求(self) -> None:
        """同一気配で両方を越えた場合は固定保護を優先する。

        引数: なし。
        返り値: None。
        """
        state = entered()
        state.quote(2, 3, 1020, 1025)
        state.quote(3, 4, 875, 880)
        self.assertEqual(state.pending["reason"], "保護")

    def test_床は不利な飛びを指定価格で約定しない(self) -> None:
        """床価格ではなく一秒後の実際のBidを使う。

        引数: なし。
        返り値: None。
        """
        state = entered()
        state.quote(2, 3, 1020, 1025)
        state.quote(3, 4, 1010, 1015)
        state.quote(4, 5, 900, 905)
        self.assertEqual(state.trades[0]["返済理由"], "利益床")
        self.assertEqual(state.trades[0]["粗損益円"], -1000)

    def test_ATR未起動と等号起動(self) -> None:
        """入口ATR未満で追尾せず等号から開始する。

        引数: なし。
        返り値: None。
        """
        state = entered("P03")
        state.quote(2, 3, 1015, 1020)
        self.assertEqual(state.position["trailing"], 875)
        state.quote(3, 4, 1020, 1025)
        self.assertEqual(state.position["trailing"], 1000)

    def test_ATR追尾線は買いで後退しない(self) -> None:
        """峰が動かない反落で買いの追尾線を下げない。

        引数: なし。
        返り値: None。
        """
        state = entered("P03")
        state.quote(2, 3, 1030, 1035)
        self.assertEqual(state.position["trailing"], 1010)
        state.quote(3, 4, 1025, 1030)
        self.assertEqual(state.position["trailing"], 1010)
        state.quote(4, 5, 1010, 1015)
        self.assertEqual(state.pending["reason"], "ATR利益追尾")

    def test_ATR追尾線は売りで後退しない(self) -> None:
        """峰が動かない反発で売りの追尾線を上げない。

        引数: なし。
        返り値: None。
        """
        state = entered("P03", side=-1)
        state.quote(2, 3, 965, 970)
        self.assertEqual(state.position["trailing"], 990)
        state.quote(3, 4, 970, 975)
        self.assertEqual(state.position["trailing"], 990)
        state.quote(4, 5, 985, 990)
        self.assertEqual(state.pending["reason"], "ATR利益追尾")

    def test_ATR追尾を五ptへ不利側丸め(self) -> None:
        """小数ATRの追尾を買い切下げ・売り切上げにする。

        引数: なし。
        返り値: None。
        """
        buy, sell = entered("P03", atr=17.5), entered("P03", side=-1, atr=17.5)
        buy.quote(2, 3, 1020, 1025)
        sell.quote(2, 3, 975, 980)
        self.assertEqual(buy.position["trailing"], 1000)
        self.assertEqual(sell.position["trailing"], 1000)

    def test_入口ATRを後日の特徴で変更しない(self) -> None:
        """入口で固定したATRを追尾中に作り直さない。

        引数: なし。
        返り値: None。
        """
        state = entered("P03")
        state.features["入口1"]["atr"] = 200
        state.quote(2, 3, 1030, 1035)
        self.assertEqual(state.position["atr_entry"], 20)
        self.assertEqual(state.position["trailing"], 1010)


# ----------------------------------------
# 確定足と反転目標、注文要求の優先、入場前の足を使わない時点制約。

class 指標出口検証(unittest.TestCase):
    """順行と反転の確定足出口を検査する。"""

    def test_順行EMA反対側は厳密不等号(self) -> None:
        """EMA等号を失効とせず反対側だけで退出する。

        引数: なし。
        返り値: None。
        """
        state = entered("P04")
        state.bar(frame(2, 2, 3, close=1000))
        self.assertIsNone(state.pending)
        state.bar(frame(3, 3, 4, close=995))
        self.assertEqual(state.pending["reason"], "確定足EMA20失効")

    def test_順行売りのEMA失効は上側(self) -> None:
        """売りの失効を買いと逆向きにする。

        引数: なし。
        返り値: None。
        """
        state = entered("P04", side=-1)
        state.bar(frame(2, 2, 3, close=1005))
        self.assertEqual(state.pending["reason"], "確定足EMA20失効")

    def test_入口時以前に終了した足は利用しない(self) -> None:
        """入場後公開されても終了が入場以前の足を除く。

        引数: なし。
        返り値: None。
        """
        for ended in (0, 1):
            with self.subTest(ended=ended):
                state = entered("P04")
                state.bar(frame(ended, 2, 3))
                self.assertIsNone(state.pending)

    def test_未公開足と公開遅延三十秒超は除く(self) -> None:
        """確定・公開が条件を満たす足だけ利用する。

        引数: なし。
        返り値: None。
        """
        for item in (frame(2, 2, 3, publish=False), frame(2, 32.1, 3)):
            state = entered("P04")
            state.bar(item)
            self.assertIsNone(state.pending)
        state = entered("P04")
        state.bar(frame(2, 32, 3))
        self.assertEqual(state.pending["reason"], "確定足EMA20失効")

    def test_EMA未準備は失効に変えない(self) -> None:
        """EMA欠測を任意の方向へ読み替えない。

        引数: なし。
        返り値: None。
        """
        state = entered("P04")
        state.bar(frame(2, 2, 3, ema=None))
        self.assertIsNone(state.pending)

    def test_反転買い構造は入口安値引く五(self) -> None:
        """入口構造の等号を維持し厳密な下抜けで失効する。

        引数: なし。
        返り値: None。
        """
        state = entered("P04", role="反転")
        self.assertEqual(state.position["structure"], 975)
        state.bar(frame(2, 2, 3, close=975))
        self.assertIsNone(state.pending)
        state.bar(frame(3, 3, 4, close=970))
        self.assertEqual(state.pending["reason"], "確定足復帰構造失効")

    def test_反転売り構造は入口高値足す五(self) -> None:
        """売りの構造失効を買いと鏡像にする。

        引数: なし。
        返り値: None。
        """
        state = entered("P04", side=-1, role="反転", mean=900)
        self.assertEqual(state.position["structure"], 1025)
        state.bar(frame(2, 2, 3, close=1025))
        self.assertIsNone(state.pending)
        state.bar(frame(3, 3, 4, close=1030))
        self.assertEqual(state.pending["reason"], "確定足復帰構造失効")

    def test_入口時中心線を有利側だけ目標にする(self) -> None:
        """有利な固定中心への等号到達で返済を要求する。

        引数: なし。
        返り値: None。
        """
        state = entered("P04", role="反転", mean=1020)
        state.features["入口1"]["bb_mean"] = 1200
        state.quote(2, 3, 1015, 1020)
        self.assertIsNone(state.pending)
        state.quote(3, 4, 1020, 1025)
        self.assertEqual(state.pending["reason"], "入口時中心線目標")

    def test_反転売り中心はAskの下側で到達(self) -> None:
        """売りの有利中心へAskで到達する。

        引数: なし。
        返り値: None。
        """
        state = entered("P04", side=-1, role="反転", mean=980)
        state.quote(2, 3, 975, 980)
        self.assertEqual(state.pending["reason"], "入口時中心線目標")

    def test_不利側と等号と欠測中心は無効を記録(self) -> None:
        """無効中心でもTP・SLを残す。

        引数: なし。
        返り値: None。
        """
        for mean in (None, 995, 1000):
            with self.subTest(mean=mean):
                state = entered("P04", role="反転", mean=mean)
                self.assertFalse(state.position["center_valid"])
                self.assertEqual(state.center_disabled, 1)
                state.quote(2, 3, 1250, 1255)
                self.assertEqual(state.pending["reason"], "利確")

    def test_固定TPは反転中心目標より優先(self) -> None:
        """同一気配でTPと中心を通過しても元TPを優先する。

        引数: なし。
        返り値: None。
        """
        state = entered("P04", role="反転", mean=1100)
        state.quote(2, 3, 1250, 1255)
        self.assertEqual(state.pending["reason"], "利確")

    def test_P05は床と指標の両方を持つ(self) -> None:
        """役割別出口と50/20床を併用する。

        引数: なし。
        返り値: None。
        """
        state = entered("P05")
        state.quote(2, 3, 1050, 1055)
        state.quote(3, 4, 1020, 1025)
        state.bar(frame(3, 3, 4))
        self.assertEqual(state.pending["reason"], "利益床")

    def test_順行は反転の固定中心を使わない(self) -> None:
        """入口役割を混ぜて中心到達で退出しない。

        引数: なし。
        返り値: None。
        """
        state = entered("P04", role="順行", mean=1020)
        state.quote(2, 3, 1020, 1025)
        self.assertIsNone(state.pending)


# ----------------------------------------
# 再生の同時順序と原模型との非数値・数値同値。

class 再生順序検証(unittest.TestCase):
    """原行に対する足・価格・入口の順番を検査する。"""

    def test_同原行の価格保護が足失効より先(self) -> None:
        """同じ原行ではquoteをbarより先に処理する。

        引数: なし。
        返り値: None。
        """
        events = [quote(0, 1, 995), quote(1, 2, 995), quote(2, 3, 875), quote(3, 4, 870)]
        state, _ = E.replay(events, [signal()], [frame(2, 2, 3)], SESSION, "合成", CONFIG, policy("P04"), "順行", BOUNDS)
        self.assertEqual(state.trades[0]["返済理由"], "保護")

    def test_同原行の足は新規要求より先(self) -> None:
        """未保有の確定足で同原行の新規後出口を生成しない。

        引数: なし。
        返り値: None。
        """
        events = [quote(2, 3, 995), quote(3, 4, 995)]
        state, _ = E.replay(events, [signal(2, 3)], [frame(2, 2, 3)], SESSION, "合成", CONFIG, policy("P04"), "順行", BOUNDS)
        self.assertFalse(any(o["理由"] == "確定足EMA20失効" for o in state.orders))
        self.assertEqual(state.fills[0]["price_clock"], 3)

    def test_足公開後も返済一秒待機を守る(self) -> None:
        """足の確認時刻が返済約定時計へ化けない。

        引数: なし。
        返り値: None。
        """
        events = [quote(0, 1, 995), quote(1, 2, 995), quote(2, 3, 995), quote(2, 4, 990), quote(3, 5, 985)]
        state, _ = E.replay(events, [signal()], [frame(2, 2, 3)], SESSION, "合成", CONFIG, policy("P04"), "順行", BOUNDS)
        self.assertEqual(state.trades[0]["返済要求時計秒"], 2)
        self.assertEqual(state.trades[0]["返済時計秒"], 3)
        self.assertEqual(state.trades[0]["返済価格"], 985)

    def test_P00は元007と同じ約定注文会計(self) -> None:
        """追加出口なしの完結経路を原模型へ照合する。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            with self.subTest(side=side):
                events = [quote(0, 1, 995 if side == 1 else 1000),
                          quote(1, 2, 995 if side == 1 else 1000),
                          quote(2, 3, 1250 if side == 1 else 745),
                          quote(3, 4, 1240 if side == 1 else 755)]
                signals = [signal(side=side)]
                old, old_info = E.O.replay_session(events, deepcopy(signals), SESSION, "同一", CONFIG, BOUNDS)
                new, new_info = E.replay(events, deepcopy(signals), [frame(2, 2, 3)], SESSION, "同一", CONFIG, policy("P00"), "順行", BOUNDS)
                self.assertEqual(new.fills, old.fills)
                self.assertEqual(new.orders, old.orders)
                for actual, expected in zip(new.trades, old.trades):
                    self.assertEqual({k: actual[k] for k in expected}, expected)
                for key, value in old_info.items():
                    self.assertEqual(new_info[key], value)

    def test_元入力検査を維持する(self) -> None:
        """入口重複・別場・方向不正を再生前に拒否する。

        引数: なし。
        返り値: None。
        """
        bad_inputs = [[signal(), signal()], [dict(signal(), 場="別場")], [dict(signal(), side=0)]]
        for rows in bad_inputs:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                E.replay([], rows, [], SESSION, "合成", CONFIG, policy("P00"), "順行", BOUNDS)

    def test_正常フラグと不正気配の矛盾を拒否(self) -> None:
        """原模型と同様に正常フラグの不正な気配を拒否する。

        引数: なし。
        返り値: None。
        """
        with self.assertRaises(ValueError):
            E.replay([quote(0, 1, 1000, 995)], [], [], SESSION, "合成", CONFIG, policy("P00"), "順行", BOUNDS)

    def test_時計後退除外数を原模型と一致(self) -> None:
        """不正板も含む時計高値から後退した状態を除外する。

        引数: なし。
        返り値: None。
        """
        events = [quote(0, 1, 995), quote(1, 2, 995), quote(.5, 3, 995), quote(2, 4, 1250), quote(3, 5, 1240)]
        _, old_info = E.O.replay_session(events, [signal()], SESSION, "同一", CONFIG, BOUNDS)
        _, info = E.replay(events, [signal()], [], SESSION, "同一", CONFIG, policy("P00"), "順行", BOUNDS)
        self.assertEqual(info["時計後退除外数"], 1)
        self.assertEqual(info["時計後退除外数"], old_info["時計後退除外数"])

    def test_観測DDは将来返済料込みで検算(self) -> None:
        """実際の新規と返済を通る時価列からDDを手計算する。

        引数: なし。
        返り値: None。
        """
        for side in (1, -1):
            with self.subTest(side=side):
                state = entered("P01", side=side)
                self.assertEqual(state.equity_low, -72)
                self.assertEqual(state.max_drawdown, 72)
                if side == 1:
                    values = [(2, 3, 1020, 1025), (3, 4, 1010, 1015), (4, 5, 980, 985)]
                else:
                    values = [(2, 3, 975, 980), (3, 4, 985, 990), (4, 5, 1015, 1020)]
                for item in values:
                    state.quote(*item)
                # 時価列は 0,-72,178,78,-222。峰178から返済-222まで400円。
                self.assertEqual(state.equity_peak, 178)
                self.assertEqual(state.equity_low, -222)
                self.assertEqual(state.max_drawdown, 400)
                self.assertEqual(state.cash, -222)
                self.assertIsNone(state.position)

    def test_期限予約が追加出口より優先(self) -> None:
        """期限到達では期限返済注文を保持して一秒後に約定する。

        引数: なし。
        返り値: None。
        """
        state = entered("P01")
        state.quote(2, 3, 1020, 1025)
        state.quote(950, 4, 1010, 1015)
        self.assertEqual(state.pending["reason"], "期限")
        self.assertEqual(state.pending["line"], 0)
        state.quote(951, 5, 1005, 1010)
        self.assertEqual(state.trades[0]["返済理由"], "期限")


def run() -> dict:
    """合成検査だけを実行し作業JSONへ記録する。

    引数: なし。実データや損益結果は読まない。
    返り値: dict は件数・失敗・エラーと明示合否。
    """
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "対象コードSHA256": hashlib.sha256((ROOT / "scripts/利益回収/運用.py").read_bytes()).hexdigest(),
              "合成検証コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "失敗": [{"検査": str(t), "内容": text} for t, text in result.failures],
              "エラー": [{"検査": str(t), "内容": text} for t, text in result.errors],
              "検査範囲": "合成のみ。床・ATR・役割別出口の境界と鏡像、元保護優先、1秒待機、足の終了/公開、元P00同値、元入力防御と時計後退、実新規返済経路の時価DD。",
              "実行記録": stream.getvalue()}
    target = ROOT / "work/利益回収/合成検証.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(stream.getvalue())
    return report


if __name__ == "__main__":
    if not run()["全件成功"]:
        raise SystemExit(1)
