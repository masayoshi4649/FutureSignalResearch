"""00024の価格だけの登録と、終値内復帰・外回復を人工足で検査する。"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00024_終値の内復帰と外回復による順行反転"
WORK = ROOT / "work/終値切替"
SESSION = "2026-11-04_Day"


def load(path: Path, name: str) -> object:
    """市場の保存成績を実行せず、対象APIを読み込む。

    引数: path (Path) はコード、name (str) はモジュール識別名。
    返り値: object は読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


I = load(HERE / "入口.py", "終値切替合成の入口")
J = load(HERE / "指標.py", "終値切替合成の固定指標")
O = load(HERE / "運用.py", "終値切替合成の固定運用")
FIX = load(ROOT / "scripts/高安再開/合成検証.py", "終値切替合成の固定23人工値")
Q = FIX.FIX.quote


def config() -> dict:
    """固定予定の24条件を独立コピーで読む。

    引数: なし。
    返り値: dict は24条件。保存前の人工既定値は最終proofに使わない。
    """
    path = STUDY / "条件.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {**deepcopy(I.OLD_CONFIG), "戦略": list(I.POLICIES), "終値切替": deepcopy(I.RULES)}


def lower(side: int = 1, count: int = 5) -> list[dict]:
    """設定2・内復帰3・外回復4の終値系列を作る。

    引数: side (int) は元突破方向、count (int) は足数。
    返り値: list[dict] は下位BB/K/EMA/RSI未準備でもH/ATRを持つ人工公開足。
    """
    frames = FIX.lower(1, count)
    closes, histogram = [1000, 1000, 1010, 995, 1005], [0, 0, 5, 4, 5]
    for index, frame in enumerate(frames):
        close = closes[index] if index < len(closes) else 1005
        frame.update(open=1000, close=close, high=max(1000, close) + 20, low=min(1000, close) - 20,
                     atr=20 if index < 3 else 30 if index == 3 else 45,
                     macd_hist=histogram[index] if index < len(histogram) else index + 1,
                     bb_mean=None, bb_sd=None, bandwidth=None, stoch_k=None, stoch_d=None, rsi=None)
        if side == -1:
            old_high, old_low = frame["high"], frame["low"]
            frame.update(open=2000 - frame["open"], close=2000 - close,
                         high=2000 - old_low, low=2000 - old_high, macd_hist=-frame["macd_hist"])
    return frames


def generate(side: int = 1, frames: list[dict] | None = None, higher: list[dict] | None = None,
             channels: list[dict] | None = None, quantity: dict | None = None,
             cutoff: float = 20000, deadline: float = 30000) -> tuple[dict, dict]:
    """人工価格だけを24の新入口へ渡す。

    引数: side (int) は元方向、frames/higher/channels (list[dict]|None) は人工上書き、
    quantity (dict|None) は診断値、cutoff/deadline (float) は新規停止/返済期限。
    返り値: tuple[dict,dict] は二採用集合と全価格状態・発動。
    """
    return I.generate(lower(side) if frames is None else frames, FIX.higher(side) if higher is None else higher,
                      SESSION, cutoff, deadline, config(), channels=FIX.channels(side) if channels is None else channels,
                      quantity=quantity)


def actions(quality: dict, index: int) -> list[dict]:
    """指定した足の監視動作を得る。

    引数: quality (dict) はAPI品質、index (int) は判断足番号。
    返り値: list[dict] は時系列動作。
    """
    return next(row["動作"] for row in quality["監視trace"] if row["index"] == index)


def context(side: int = 1, **updates: object) -> dict:
    """数式の括弧と境界を独立に検査する最小の当時値を作る。

    引数: side (int) は実新規方向、updates (object) は当時値の上書き。
    返り値: dict はM準備・時間可の人工context。
    """
    return {"M除外理由": [], "時間条件可": True, "MACDヒスト変化": float(side),
            "S2局面": "トレンド", "S2方向": side, "ADX変化": 1., **updates}


# ----------------------------------------
# 新規の登録を、上位・MACDの採否と分離する。

class 登録と参照検証(unittest.TestCase):
    """価格登録、固定出典、前pまでの結合、未使用gateを検査する。"""

    def test_固定23の銀行30窓と運用を同じ公開APIで使う(self) -> None:
        """今回の仮説で指標・チャネル・A5出口を複製変更しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        self.assertIs(J.ChannelBank, J.BASE.ChannelBank)
        self.assertIs(J.Indicators, J.BASE.Indicators)
        self.assertIs(J.features, J.BASE.features)
        self.assertIs(O.replay, O.BASE.replay)
        self.assertEqual(O.trail_parameters(20.001), (5, 25))

    def test_Hや上位未準備でも価格だけで登録するが注文は出さない(self) -> None:
        """登録の母集団へ旧S2Tや勢い準備を戻さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = lower(side, 3)
            frames[2]["macd_hist"] = None
            groups, quality = generate(side, frames=frames, higher=[])
            self.assertEqual(quality["設定数"], 1)
            self.assertEqual(quality["全Q発動記録"], [])
            self.assertTrue(all(not rows for rows in groups.values()))
            self.assertFalse(quality["エピソード診断"][0]["登録旧23方向勢い資格"])
            self.assertTrue(quality["複合context記録"][-1]["登録価格準備"])

    def test_登録確認遅延三十一秒でも監視を開始し次の正常fを消費する(self) -> None:
        """登録自体に注文遅延gateを加えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower()
        frames[2]["confirm"] += 31
        groups, quality = generate(frames=frames)
        self.assertEqual((quality["設定数"], quality["登録遅延超数"]), (1, 1))
        self.assertEqual(quality["全Q発動記録"][0]["index"], 3)
        self.assertEqual(len(groups["3分_E0"]), 2)

    def test_価格突破strictとε丸めおよび登録時間を分ける(self) -> None:
        """価格等号や前足既突破を新登録にせず、時間外はtraceだけへ残す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        self.assertEqual([I.width(x) for x in (1, 20, 20.0001)], [5, 5, 10])
        for side in (1, -1):
            frames = lower(side, 3)
            frames[1]["close"] = 1000 + side * 5
            self.assertEqual(generate(side, frames=frames)[1]["設定数"], 1)
            for index, value in ((2, 1000 + side * 5), (1, 1000 + side * 6)):
                changed = lower(side, 3)
                changed[index]["close"] = value
                if index == 1:
                    changed[0]["close"] = value
                self.assertEqual(generate(side, frames=changed)[1]["設定数"], 0)
        _, quality = generate(frames=lower(count=3), cutoff=4140)
        self.assertEqual(quality["設定数"], 0)
        self.assertIn("新登録時間不可", actions(quality, 2)[0]["理由"])

    def test_前pより後に知る30窓は登録に先取りせず既存出典も置換しない(self) -> None:
        """bで知る新高安と後の再準備を固定episodeへ流用しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, snapshots = lower(), FIX.channels()
        newer = {**deepcopy(snapshots[-1]), "R": 2000, "confirm": frames[2]["confirm"],
                 "confirm_line": frames[2]["confirm_line"], "end": frames[2]["end"]}
        groups, quality = generate(frames=frames, channels=snapshots + [newer])
        self.assertEqual(quality["設定数"], 1)
        for case in groups["3分_E0"]:
            self.assertEqual((case["固定設定"]["R"], case["固定設定"]["ε"]), (1000, 5))
        newer.update({"30窓準備済": False, "30窓本数": 1, "R": None, "L": None})
        groups, quality = generate(frames=frames, channels=snapshots + [newer])
        self.assertFalse(quality["複合context記録"][3]["30窓準備済"])
        self.assertTrue(quality["複合context記録"][3]["固定30窓有効"])
        self.assertTrue(quality["複合context記録"][3]["共通M準備"])
        self.assertEqual(len(groups["3分_E0"]), 2)


# ----------------------------------------
# ヒゲを使わず、終値の順序・寿命・消費だけで価格状態を進める。

class 終値状態検証(unittest.TestCase):
    """f/gの鏡像とstrict終値、時点不適格、監視の消費を検査する。"""

    def test_買売鏡像で内復帰逆sideから外回復元sideへ一度ずつ進む(self) -> None:
        """startが前公開と同値でもendが後なら終値を利用する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            groups, quality = generate(side)
            raw = quality["全Q発動記録"]
            self.assertEqual([(r["index"], r["side"], r["役割"]) for r in raw], [(3, -side, "反転"), (4, side, "順行")])
            self.assertEqual([r["index"] for r in groups["3分_E0"]], [3, 4])
            self.assertEqual([r["index"] for r in groups["3分_E1"]], [4])
            self.assertEqual(raw[0]["start"], raw[0]["固定設定"]["設定"]["confirm"])
            self.assertEqual(raw[1]["close"], 1000 + side * 5)
            self.assertEqual(quality["終了理由別"], {"外回復価格消費": 1})
            self.assertNotIn("R1", {r["入口系統"] for r in raw})

    def test_ヒゲで反対端を越えても終値だけでfとgを決める(self) -> None:
        """23の帯割れL/Hをclose-onlyへ持ち込まない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = lower(side)
            for frame in frames[3:]:
                frame.update(high=None, low=None, open=None)
            groups, quality = generate(side, frames=frames)
            self.assertEqual(len(groups["3分_E0"]), 2)
            self.assertEqual(quality["内復帰価格消費数"], 1)
            self.assertEqual(quality["外回復価格消費数"], 1)

    def test_元境界終値等号は両段階で待機し反対端等号は取消する(self) -> None:
        """strict内復帰・strict外回復と閉じた反対端取消を区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = lower(side, 6)
            frames[3]["close"] = 1000
            frames[4].update(close=995 if side == 1 else 1005, macd_hist=4 * side)
            frames[5].update(close=1005 if side == 1 else 995, macd_hist=5 * side)
            _, quality = generate(side, frames=frames)
            self.assertEqual([r["index"] for r in quality["全Q発動記録"]], [4, 5])
            frames = lower(side, 6)
            frames[4]["close"] = 1000
            frames[5]["macd_hist"] = 6 * side
            self.assertEqual([r["index"] for r in generate(side, frames=frames)[1]["全Q発動記録"]], [3, 5])
            for index in (3, 4):
                for beyond in (0, 1):
                    frames = lower(side)
                    frames[index]["close"] = 900 - beyond if side == 1 else 1100 + beyond
                    _, quality = generate(side, frames=frames)
                    self.assertEqual(quality["エピソード診断"][0]["終了理由"], "反対端到達")
                    self.assertFalse(any(r["index"] == index for r in quality["全Q発動記録"]))

    def test_内復帰は任意のstrict内側でepsilonやf高安をgへ要求しない(self) -> None:
        """gがR+εと同値でもRだけ越えれば価格イベントになる。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower()
        frames[3].update(close=901, high=1500, low=800)
        frames[4].update(close=1005, high=1200, low=800)
        _, quality = generate(frames=frames)
        self.assertEqual([r["index"] for r in quality["全Q発動記録"]], [3, 4])
        self.assertLess(quality["全Q発動記録"][1]["close"], frames[3]["high"])

    def test_設定公開を越えないendの足は反対端でも取消せず寿命だけ進む(self) -> None:
        """end等号でkeyだけ後の足を終値反応へ使わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=6)
        frames[2]["confirm"] = frames[3]["end"]
        frames[3]["close"] = 899
        frames[4].update(close=995, macd_hist=3)
        frames[5].update(close=1005, macd_hist=4)
        _, quality = generate(frames=frames)
        self.assertEqual([r["index"] for r in quality["全Q発動記録"]], [4, 5])
        self.assertEqual(actions(quality, 3)[0]["動作"], "価格時点対象外")
        self.assertIsNone(quality["エピソード診断"][0]["反対端到達"])

    def test_f公開を越えないg候補は対端到達でも取消しない(self) -> None:
        """前段fの遅延で既に含まれる終値を次段反応へ使わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=6)
        frames[3]["confirm"] = frames[4]["end"]
        frames[4]["close"] = 899
        frames[5].update(close=1005, macd_hist=6)
        _, quality = generate(frames=frames)
        self.assertEqual([r["index"] for r in quality["全Q発動記録"]], [3, 5])
        self.assertEqual(actions(quality, 4)[0]["動作"], "価格時点対象外")

    def test_f六足目g三足目を含み七足目四足目は満了が先(self) -> None:
        """対象外や等号足で寿命を繰り延べず満了足へ価格を付けない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=12)
        for index in range(3, 12):
            frames[index].update(close=1010, macd_hist=index)
        frames[8].update(close=995, macd_hist=6)
        frames[9]["close"], frames[10]["close"] = 1000, 1000
        frames[11].update(close=1005, macd_hist=12)
        _, quality = generate(frames=frames)
        self.assertEqual([r["index"] for r in quality["全Q発動記録"]], [8, 11])
        frames[8]["close"], frames[9]["close"] = 1010, 899
        _, quality = generate(frames=frames[:10])
        self.assertEqual(quality["エピソード診断"][0]["終了理由"], "内復帰六足満了")
        self.assertIsNone(quality["エピソード診断"][0]["反対端到達"])
        frames = lower(count=8)
        for index in (4, 5, 6):
            frames[index]["close"] = 1000
        frames[7]["close"] = 899
        _, quality = generate(frames=frames)
        self.assertEqual(quality["エピソード診断"][0]["終了理由"], "外回復三足満了")

    def test_指標や上位未準備のfも消費しgを現在値で別判定する(self) -> None:
        """価格連続性以外の不採用で監視を取り消さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"atr": None}, {"macd_hist": None}):
            frames = lower(count=6)
            frames[3].update(change)
            frames[4]["close"] = 1000
            frames[5].update(close=1005, macd_hist=7)
            groups, quality = generate(frames=frames)
            self.assertEqual([r["index"] for r in quality["全Q発動記録"]], [3, 5])
            self.assertFalse(quality["全Q発動記録"][0]["戦略判定"]["E0"]["採用"])
            self.assertEqual([r["index"] for r in groups["3分_E0"]], [5])
            self.assertEqual(groups["3分_E0"][0]["atr"], 45)
        frames = lower()
        frames[2]["macd_hist"] = None
        groups, quality = generate(frames=frames)
        self.assertEqual([r["index"] for r in groups["3分_E0"]], [4])
        self.assertEqual(quality["終了理由別"], {"外回復価格消費": 1})

    def test_遅延三十一秒のfでも消費し正常gへ前足遅延gateを足さない(self) -> None:
        """現在の注文遅延条件を前足の新しい準備条件へ拡大しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for delay in (30, 31):
            frames = lower()
            frames[3]["confirm"] += delay
            groups, quality = generate(frames=frames)
            self.assertEqual(quality["内復帰価格消費数"], 1)
            self.assertEqual(quality["全Q発動記録"][0]["先着評価対象"], delay == 30)
            self.assertEqual([r["index"] for r in groups["3分_E0"]], [3, 4] if delay == 30 else [4])

    def test_勢いや時間不可でも最初のfとgを消費して取り直さない(self) -> None:
        """後の都合のよいH差や価格へ発動時計を延ばさない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=7)
        frames[3]["macd_hist"] = 6
        frames[4]["macd_hist"] = 5
        frames[5].update(close=995, macd_hist=4)
        frames[6].update(close=1020, macd_hist=7)
        groups, quality = generate(frames=frames)
        self.assertTrue(all(not r for r in groups.values()))
        self.assertEqual([r["index"] for r in quality["全Q発動記録"]], [3, 4])
        self.assertTrue(any(a.get("理由") and "当場同方向境界使用済み" in a["理由"] for a in actions(quality, 6)))
        groups, quality = generate(cutoff=4320)
        self.assertTrue(all(not r for r in groups.values()))
        self.assertEqual([r["index"] for r in quality["全Q発動記録"]], [3, 4])
        self.assertEqual(quality["先着評価対象外数"], 2)

    def test_価格の非公開欠枠番号飛越不正はイベントより先に取消する(self) -> None:
        """H等の未準備と、使える終値がない失効を区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"publish": False}, {"missing": 1}, {"index": 6}, {"close": 0}, {"close": float("nan")}):
            frames = lower(count=4)
            frames[3].update(change)
            _, quality = generate(frames=frames)
            self.assertEqual(quality["エピソード診断"][0]["終了理由"], "公開価格連続性失効")
            self.assertEqual(quality["全Q発動記録"], [])

    def test_global監視と同境界使用済みを維持し場でresetする(self) -> None:
        """内復帰消費後に新しい突破を同足登録せず、終了後も元キーを復活させない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=7)
        frames[5]["close"], frames[6]["close"] = 1000, 1020
        _, quality = generate(frames=frames)
        self.assertEqual(quality["設定数"], 1)
        self.assertTrue(any("当場同方向境界使用済み" in a.get("理由", []) for a in actions(quality, 6)))
        self.assertIn("旧監視あり・同足新設定禁止", quality["監視trace"][4]["新設定除外理由"])
        _, again = I.generate(lower(), FIX.higher(), "2026-11-04_Night", 20000, 30000, config(), channels=FIX.channels())
        self.assertEqual(again["設定数"], 1)


# ----------------------------------------
# 価格イベントが生じた後にだけ、実sideのMACDと上位の括弧を評価する。

class 複合採否検証(unittest.TestCase):
    """E0/E1共通準備、方向化H、RのOR、全採否snapshotを検査する。"""

    def test_両戦略とも実新規sideのH差strict正を要求する(self) -> None:
        """元突破sideを反転Rへ流用せず、上位ORで勢い不成立を救わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for family in ("R内復帰", "T外回復"):
                for delta in (side * .001, 0, -side * .001, None):
                    result = I.decisions(context(side, MACDヒスト変化=delta), family, side)
                    self.assertEqual(result["E0"]["採用"], delta == side * .001)
                    self.assertEqual(result["E1"]["採用"], delta == side * .001)

    def test_R上位は反転方向TかADX非上昇で横ばいを弱まりと分ける(self) -> None:
        """a0を許可する一方、逆の上位Tかつa正を許可しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for delta, allowed, word in ((-1, True, "弱まり"), (0, True, "横ばい"), (.001, False, "対象外")):
                ctx = context(side, S2方向=-side, ADX変化=delta)
                verdicts = I.decisions(ctx, "R内復帰", side)
                self.assertTrue(verdicts["E0"]["採用"])
                self.assertEqual(verdicts["E1"]["採用"], allowed)
                self.assertTrue(any(word in reason for reason in verdicts["E1"]["理由"]))
            verdicts = I.decisions(context(side, ADX変化=1), "R内復帰", side)
            self.assertTrue(verdicts["E1"]["採用"])
            self.assertTrue(any("実方向S2T" in reason for reason in verdicts["E1"]["理由"]))
            verdicts = I.decisions(context(side, S2局面="待機", ADX変化=0), "R内復帰", side)
            self.assertTrue(verdicts["E1"]["採用"])

    def test_T上位は同方向TだけでADX低下や横ばいから自動参加しない(self) -> None:
        """R専用のa<=0許可をTへ横流ししない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for phase, direction, delta in (("待機", 0, -1), ("レンジ", 0, 0), ("トレンド", -side, 1)):
                result = I.decisions(context(side, S2局面=phase, S2方向=direction, ADX変化=delta), "T外回復", side)
                self.assertTrue(result["E0"]["採用"])
                self.assertFalse(result["E1"]["採用"])

    def test_下位二本HだけでMを満たし旧三本KやBBを足さない(self) -> None:
        """固定bankの値を使っても今回の準備を旧M23へ戻さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=4)
        for frame, close, hist in zip(frames, (1000, 1010, 995, 1005), (0, 5, 4, 5)):
            frame.update(close=close, macd_hist=hist)
        groups, quality = generate(frames=frames)
        self.assertEqual([r["index"] for r in groups["3分_E0"]], [2, 3])
        self.assertTrue(quality["複合context記録"][2]["共通M24準備"])
        self.assertIsNone(groups["3分_E0"][0]["stoch_k"])
        self.assertIsNone(groups["3分_E0"][0]["bb_mean"])

    def test_上位未準備のfも進みgで公開されたpairからだけ復帰する(self) -> None:
        """fを消費しないまま後の上位値で採否を遡及しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        upper = FIX.higher()
        upper[0].update(start=2700, end=3600, confirm=3600, confirm_line=50)
        upper[1].update(start=3600, end=4500, confirm=4500, confirm_line=104)
        groups, quality = generate(higher=upper)
        self.assertFalse(quality["全Q発動記録"][0]["共通M24準備"])
        self.assertEqual([r["index"] for r in groups["3分_E0"]], [4])
        self.assertEqual([r["index"] for r in groups["3分_E1"]], [4])
        self.assertEqual(quality["内復帰価格消費数"], 1)

    def test_数量や未来診断を変えても価格状態と全採否を変えない(self) -> None:
        """量の欠測・大きなRVOLを新しいgateへ追加しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        baseline, base_quality = generate()
        quantity = {i: {"数量準備済": bool(i % 2), "RVOL": None if i % 2 else 9999, "将来先着": "逆行先着"} for i in range(5)}
        groups, quality = generate(quantity=quantity)
        self.assertEqual(quality["監視trace"], base_quality["監視trace"])
        self.assertEqual(quality["エピソード診断"], base_quality["エピソード診断"])
        for policy in groups:
            self.assertEqual([r["イベントID"] for r in groups[policy]], [r["イベントID"] for r in baseline[policy]])
        for before, after in zip(base_quality["全Q発動記録"], quality["全Q発動記録"]):
            self.assertEqual(before["戦略判定"], after["戦略判定"])

    def test_固定設定snapshotはfからgの後の状態で書き換わらない(self) -> None:
        """f時点の内復帰未登録とg時点の登録済みを別コピーで保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, quality = generate()
        raw = quality["全Q発動記録"]
        self.assertEqual(raw[0]["固定設定"]["段階"], "内復帰待ち")
        self.assertIsNone(raw[0]["固定設定"]["内復帰"])
        self.assertEqual(raw[1]["固定設定"]["内復帰"]["index"], 3)
        canonical = {r["発動ID"]: r for r in raw}
        for cases in groups.values():
            for case in cases:
                self.assertEqual(case["戦略判定"], canonical[case["発動ID"]]["戦略判定"])
                self.assertTrue(case["先着評価対象"])
                self.assertNotIn("ラベル", case)
        groups["3分_E0"][1]["固定設定"]["内復帰"]["index"] = 999
        self.assertEqual(raw[1]["固定設定"]["内復帰"]["index"], 3)
        self.assertEqual(groups["3分_E1"][0]["固定設定"]["内復帰"]["index"], 3)

    def test_全競合確定後に別戦略caseの全verdictも複写する(self) -> None:
        """人工的に同要求keyへ衝突させ、単独E1caseへ古いE0採否を残さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        original = I.signal

        def same_key(*args: object, **kwargs: object) -> dict:
            """競合処理だけのため二原発動を同じ要求keyへ置く。

            引数: args/kwargs (object) は本来のsignal引数。
            返り値: dict は採否を変えず要求keyだけを上書きした人工signal。
            """
            row = original(*args, **kwargs)
            row.update(要求時計秒=4320, 要求原板行=103)
            return row

        with patch.object(I, "signal", side_effect=same_key):
            groups, quality = generate()
        self.assertEqual(groups["3分_E0"], [])
        self.assertEqual(len(groups["3分_E1"]), 1)
        case = groups["3分_E1"][0]
        canonical = next(row for row in quality["全Q発動記録"] if row["発動ID"] == case["発動ID"])
        self.assertEqual(case["戦略判定"], canonical["戦略判定"])
        self.assertTrue(case["戦略判定"]["E0"]["同時競合"])
        self.assertFalse(case["戦略判定"]["E0"]["採用"])

    def test_旧R1の形を足しても新しい価格イベントへ混合しない(self) -> None:
        """今回使わないストキャスとBBの復帰だけで別Rを作らない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=5)
        for i, row in enumerate(frames):
            row.update(close=1010 if i >= 2 else 1000, bb_mean=1020, bb_sd=10,
                       stoch_k=10 if i < 3 else 20 if i == 3 else 21)
        groups, quality = generate(frames=frames, higher=FIX.higher(ranging=True))
        self.assertEqual(quality["設定数"], 1)
        self.assertEqual(quality["全Q発動記録"], [])
        self.assertTrue(all(not rows for rows in groups.values()))


# ----------------------------------------
# 対象外ラベル、固定A5の実fill、prepareの禁止経路まで接続する。

class ラベルと運用検証(unittest.TestCase):
    """価格状態の消費と、評価/注文/保有の別の母集団を検査する。"""

    def test_時間外と遅延超は対象外九数値欠測でevaluateを呼ばない(self) -> None:
        """両方不可のときは時間理由を先にし、未約定と混同しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "終値切替合成の対象外ラベル")
        for cutoff, reason in ((4351, "要求時間条件外"), (20000, "足確定確認遅延30秒超")):
            frames = lower()
            frames[3]["confirm"] += 31
            _, quality = generate(frames=frames, cutoff=cutoff)
            record = quality["全Q発動記録"][0]
            forbidden = SimpleNamespace(evaluate=unittest.mock.Mock(side_effect=AssertionError("対象外の先着は禁止")))
            result = driver.shadow_label(record, forbidden, {}, cutoff, 30000, config())
            self.assertEqual((result["ラベル"], result["理由"]), ("対象外", reason))
            numeric = {key: value for key, value in result.items() if key not in ("ラベル", "理由")}
            self.assertEqual(len(numeric), 9)
            self.assertTrue(all(value is None for value in numeric.values()))
            forbidden.evaluate.assert_not_called()
            with self.assertRaises(ValueError):
                driver.shadow_label({**record, "先着評価対象": True}, forbidden, {}, cutoff, 30000, config())
            forbidden.evaluate.assert_not_called()

    def test_時間と遅延可ならM不可の原イベントも診断評価できる(self) -> None:
        """採用caseから除いた原価格イベントを先着対象外と同一視しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "終値切替合成の通常ラベル")
        _, quality = generate(higher=[])
        record = quality["全Q発動記録"][0]
        self.assertFalse(record["共通M24準備"])
        self.assertTrue(record["先着評価対象"])
        path = SimpleNamespace(evaluate=unittest.mock.Mock(return_value={"ラベル": "逆行先着", "人工値": True}))
        cache = {}
        self.assertEqual(driver.shadow_label(record, path, cache, 20000, 30000, config()),
                         driver.shadow_label(record, path, cache, 20000, 30000, config()))
        path.evaluate.assert_called_once_with(4320, 20000, 30000, -1, adverse=125, favorable=250)

    def test_生成Rを実新規して保有中Tでもroleを書換えずA5会計へ接続する(self) -> None:
        """下位BB/K未準備でも旧出口を使い、同秒次行で返済しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            frames = lower(side)
            frames[4]["confirm_line"] = 200
            groups, _ = generate(side, frames=frames)
            signals = groups["3分_E0"]
            now, g = signals[0]["要求時計秒"], signals[1]["要求時計秒"]
            quotes = [Q(now, 103), Q(now + 1, 104), Q(now + 2, 105), Q(g, 200),
                      Q(g + 1, 201, 990 if side == 1 else 1010),
                      Q(g + 2, 202, 995 if side == 1 else 1005),
                      Q(g + 2, 203, 995 if side == 1 else 1005),
                      Q(g + 3, 204, 995 if side == 1 else 1005), Q(now + 7201, 300)]
            args = (quotes, signals, [], SESSION, "人工24", config()["運用"], {"出口ID": "X0"}, "混合",
                    (now - 100, now + 7300, now + 3600, now + 7200))
            state, info = O.replay(*deepcopy(args))
            old, old_info = FIX.O.replay(*deepcopy(args))
            self.assertEqual((state.fills, state.orders, state.trades, info), (old.fills, old.orders, old.trades, old_info))
            self.assertEqual(len(state.trades), 1)
            trade = state.trades[0]
            self.assertEqual((trade["入口役割"], trade["入口ATR"], trade["追尾距離pt"]), ("反転", 30, 30))
            self.assertEqual((trade["追尾起動"], trade["返済時計秒"], trade["基準純損益円"]), (True, g + 3, -22))
            self.assertEqual(trade["新規価格"], 1000 if side == 1 else 1005)
            self.assertEqual(trade["返済理由"], "必須利益追尾")
            self.assertEqual(info["建玉中抑止数"], 1)

    def test_二候補と空足零を保持し主要な固定継承変更を拒否する(self) -> None:
        """実装が旧値を使うのに設定の数値表示だけ変わる事故を拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "終値切替合成の二定義")
        self.assertEqual([r["入口ID"] for r in driver.sources(config())], ["3分_E0", "3分_E1"])
        groups, quality = driver.generate_or_empty([], [], SESSION, 3, 20000, 30000, config(), [], [], {})
        self.assertEqual(groups, {"3分_E0": [], "3分_E1": []})
        self.assertEqual(quality["全Q発動記録"], [])
        changes = [(('運用', '片道手数料円'), 12), (('必須追尾', '起動幅pt'), 10),
                   (('指標', 'MACD'), [11, 26, 9]), (('入口支持', '学習', '約定候補数'), 59),
                   (('目標確認率',), .6), (('分割', '選択開始日'), '2026-10-20'),
                   (('確認遅延上限秒',), 31), (('逆行pt',), 120), (('終値切替', '内復帰上限本数'), 7)]
        for keys, value in changes:
            altered = deepcopy(config())
            parent = altered
            for key in keys[:-1]:
                parent = parent[key]
            parent[keys[-1]] = value
            with self.assertRaises(ValueError):
                I.validate_config(altered)
        with self.assertRaises(ValueError):
            I.validate_config({**config(), "戦略": ["E0", "E1", "E2"]})
        with self.assertRaises(ValueError):
            driver.sources({**config(), "出口": [{"出口ID": "X1"}]})

    def test_登録の価格準備と公開順不正を黙って補正しない(self) -> None:
        """ATRや既知窓がない登録を作らず、未完成/番号後退を拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=3)
        frames[2]["atr"] = None
        self.assertEqual(generate(frames=frames)[1]["設定数"], 0)
        self.assertEqual(generate(channels=[])[1]["設定数"], 0)
        for change in ({"index": 1}, {"confirm": 4139}):
            frames = lower(count=3)
            frames[2].update(change)
            with self.assertRaises(ValueError):
                generate(frames=frames)

    def test_寿命満了より価格不正を優先し不正価格を対象外待機にしない(self) -> None:
        """第七足の不正を満了や反対端到達へ取り替えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower(count=10)
        for frame in frames[3:9]:
            frame["close"] = 1010
        frames[9].update(close=899, missing=1)
        _, quality = generate(frames=frames)
        self.assertEqual(quality["エピソード診断"][0]["終了理由"], "公開価格連続性失効")

    def test_prepare六十五人工場は先着運用固定を呼ばない(self) -> None:
        """原データなしで件数分岐を通し、禁止経路が呼ばれれば失敗する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE / "検証.py", "終値切替合成のprepare")
        with tempfile.TemporaryDirectory(prefix="終値切替合成_") as directory:
            base = Path(directory)
            study, work = base / "試行", base / "作業"
            study.mkdir()
            (study / "条件.json").write_text(json.dumps(config(), ensure_ascii=False), encoding="utf-8")
            source = base / "人工入力"
            source.write_text("", encoding="utf-8")
            stat = source.stat()
            sessions = [f"{date(2026, 9, 21) + timedelta(days=n)}_{kind}" for n in range(20) for kind in ("Day", "Night")]
            sessions += [f"{date(2026, 10, 19) + timedelta(days=n)}_{kind}" for n in range(12) for kind in ("Day", "Night")]
            sessions += ["2026-11-04_Day"]
            manifest = {"source_root": str(base), "entries": [{"session": session, "symbol": "NK225", "source_path": source.name,
                        "source_size": stat.st_size, "source_mtime_ns": stat.st_mtime_ns, "cache_path": "存在しない人工cache",
                        "sha256_cache": "人工SHA", "in_session_contract_codes": ["人工限月"]} for session in sessions]}
            original = driver.W.read_json

            def read_json(path: Path) -> dict:
                """人工台帳だけ置き換え、条件は一時ファイルから読む。

                引数: path (Path) は参照先。
                返り値: dict は人工台帳又は条件。
                """
                return deepcopy(manifest) if path == driver.INPUT else original(path)

            forbidden = SimpleNamespace(replay=unittest.mock.Mock(side_effect=AssertionError("運用は禁止")))
            with patch.object(driver.W, "read_json", side_effect=read_json), patch.object(driver.O, "sha", return_value="人工SHA"), \
                    patch.object(driver.W.PREP, "read_events", return_value=[]), \
                    patch.object(driver.W.OLD, "気配経路", side_effect=AssertionError("先着は禁止")), \
                    patch.object(driver, "module", return_value=forbidden), \
                    patch.object(driver, "freeze", side_effect=AssertionError("固定は禁止")), redirect_stdout(io.StringIO()):
                result = driver.run(study, work, True)
            self.assertFalse(result["ラベル計算"])
            self.assertFalse(result["損益計算"])
            forbidden.replay.assert_not_called()
            summary = json.loads((work / "準備点検.json").read_text(encoding="utf-8"))
            self.assertEqual(len(summary["準備"]), 65)
            self.assertEqual(len(summary["場別発動"]), 130)
            self.assertFalse((study / "結果.json").exists())
            self.assertFalse((work / "全運用詳細.jsonl.gz").exists())


# ----------------------------------------
# 最終明示通知まで途中proofのみとし、固定・正式データ再生は行わない。

def main() -> None:
    """人工価格の検査結果と現在版SHAを途中又は最終proofへ保存する。

    引数: なし。--finalは全追加と主版停止後だけ指定する。
    返り値: None。失敗時は終了コード1。原データや正式損益は読まない。
    """
    parser = argparse.ArgumentParser(description="終値内復帰/外回復の人工合成")
    parser.add_argument("--final", action="store_true", help="合成編集終了の最終proof")
    args = parser.parse_args()
    expected = [HERE / name for name in ("指標.py", "入口.py", "運用.py", "検証.py", "合成検証.py")] + [STUDY / "条件.json"]
    paths = [path for path in expected if path.exists()]
    pins = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if args.final and len(paths) != 6:
        raise ValueError("全6pinが揃う前は固定不可")
    if args.final and (STUDY / "固定.json").exists():
        frozen = json.loads((STUDY / "固定.json").read_text(encoding="utf-8"))["ファイルSHA256"]
        if any(frozen.get(name) != digest for name, digest in pins.items()):
            raise ValueError("固定後の追加は別ファイルへ分離する")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    proof = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
             "合成編集終了": bool(args.final and result.wasSuccessful()), "ファイルSHA256": pins,
             "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
             "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors],
             "範囲": "人工30分窓/price-only登録・close-only f/g時点/6・3寿命/端等号/対象外/初回消費/価格取消と指標採否分離・E0/E1方向MACDと上位括弧・対象外ラベル/固定A5/prepare呼出禁止。正式の価格先着・損益は実行しない。",
             "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / ("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({key: proof[key] for key in ("全件成功", "検証件数", "合成編集終了")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
