"""00022の同場15分ペア・S2境界・旧発動保持・全採否snapshotを検査する。"""

from __future__ import annotations

import argparse
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
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00022_ADXと上位BB幅の変化による局面切替"
WORK = ROOT/"work/局面変化"
SESSION = "2026-11-04_Day"


def load(path: Path, name: str) -> object:
    """コマンド行実行せず固定処理と検査対象を読む。

    引数: path (Path) はコード、name (str) はmodule識別名。
    返り値: object はmodule。保存市場成績は読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


I = load(HERE/"入口.py", "局面変化合成の入口")
J = load(HERE/"指標.py", "局面変化合成の固定指標")
O = load(HERE/"運用.py", "局面変化合成の固定運用")
FIX = load(ROOT/"scripts/異種発動/合成検証.py", "局面変化合成の固定21人工値")


def config() -> dict:
    """22固定条件の独立コピーを返す。

    引数: なし。
    返り値: dict は条件正本。作成前の人工条件は最終proofへ使わない。
    """
    path = STUDY/"条件.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {**FIX.config(), "戦略": list(I.POLICIES), "局面改訂": {
        "上位分": 15, "ADX弱境界": 20, "ADX強境界": 25, "現前同場隣接公開": True}}


def pair(side: int = 1, prior: dict | None = None, current: dict | None = None) -> list[dict]:
    """下位人工足より前に公開済みの有効15分ペアを作る。

    引数: side (int) はDI向き、prior/current (dict|None) は現前の上書き。
    返り値: list[dict] は同場index0/1の二足。
    """
    a = FIX.upper(24, side, index=0, start=1800, end=2700, confirm=2700, confirm_line=40, bandwidth=.039)
    b = FIX.upper(25, side, index=1, start=2700, end=3600, confirm=3600, confirm_line=50, bandwidth=.04)
    a.update(prior or {})
    b.update(current or {})
    return [a, b]


def lower(family: str = "T1", side: int = 1, size: int = 1) -> list[dict]:
    """旧21と同じ発動を持つ三足を作る。

    引数: family/side/size (str/int/int) は発動/方向/尺度。
    返り値: list[dict] は同場三公開足。新局面で発動自体は変更しない。
    """
    rows = [FIX.frame(n, size) for n in range(3)]
    for n, row in enumerate(rows):
        row["close"] = 1000+5*side if family == "T1" else 1000-5*side
        row["macd_hist"] = [0., 0., float(side)][n] if family == "T1" else 0.
        row["bandwidth"] = .04 if n < 2 or family == "R1" else .041
        row["stoch_k"] = ([10., 20., 21.][n] if side == 1 else [90., 80., 79.][n]) if family == "R1" else 50.
    return rows


def generate(family: str = "T1", side: int = 1, size: int = 1,
             higher: list[dict] | None = None, frames: list[dict] | None = None) -> tuple[dict, dict]:
    """人工三足とペアから新規APIを実行する。

    引数: family/side/size (str/int/int) は型/向き/幅、higher/frames (list[dict]|None) は上書き。
    返り値: tuple[dict,dict] は三戦略の入口と全旧rawshadow。
    """
    rows = lower(family, side, size) if frames is None else frames
    h = pair(side, prior={"adx": 21, "bandwidth": .041}, current={"adx": 20}) if family == "R1" else pair(side)
    h = h if higher is None else higher
    return I.generate(rows, h, SESSION, rows[-1]["confirm"]+3600, rows[-1]["confirm"]+7200, config())


# ----------------------------------------
# S2は一つの改訂規則とし、ADX差とDX差を独立した票へしない。

class 改訂境界検証(unittest.TestCase):
    """S2のOR・strict/等号・理由とDX診断を検査する。"""

    def test_高ADXなら幅非拡大でも上昇継続を許す(self) -> None:
        """A25等号とa正を使いb正を一律ANDへ追加しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for width in (0., -.01, .01):
                self.assertEqual(I.revised(25, .001, width, side), ("トレンド", side, "強ADX上昇継続"))
            self.assertEqual(I.revised(25, 0, .01, side), ("待機", 0, "高ADX失速待機"))
            self.assertEqual(I.revised(30, -1, -.01, side), ("待機", 0, "高ADX失速待機"))

    def test_低ADXの始動は差と幅の両方正を要求(self) -> None:
        """A20でも始動を許すがa0/b0を正と同一視しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            for a in (20, 20.001, 24.999):
                self.assertEqual(I.revised(a, 1, .001, side), ("トレンド", side, "低ADX上昇・幅拡大"))
            self.assertEqual(I.revised(22, 1, 0, side), ("待機", 0, "条件不一致待機"))
            self.assertEqual(I.revised(20, 0, .001, side), ("待機", 0, "条件不一致待機"))

    def test_レンジは20差0幅0の等号を含みDIゼロでも可(self) -> None:
        """低ADX非拡大だけをRにし高ADX失速から反転へ自動参加しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (0, 1, -1):
            for a, da, dw in ((20, 0, 0), (19, -1, -.01)):
                self.assertEqual(I.revised(a, da, dw, side), ("レンジ", 0, "低ADX非上昇・幅非拡大"))
        self.assertEqual(I.revised(20.001, 0, 0, 1)[0], "待機")
        self.assertEqual(I.revised(30, 1, .01, 0)[0], "待機")

    def test_DX零和と欠測を区別し恒等式goldを検査(self) -> None:
        """前A20からDX48で現A22となるWilder更新を数値検算する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1, -1):
            h = pair(side, prior={"adx": 20, "plus_di": 60, "minus_di": 40},
                current={"adx": 22, "plus_di": 74 if side == 1 else 26, "minus_di": 26 if side == 1 else 74})
            rows, _ = I.classify(h, SESSION, config())
            row = rows[1]
            self.assertEqual((row["現DX"], row["前DX"], row["ADX変化"]), (48, 20, 2))
            self.assertEqual(row["DX_ADX差"], 26)
            self.assertEqual(row["平滑恒等残差"], 0)
            self.assertEqual(row["S2方向"], side)
        self.assertEqual(I.dx(FIX.upper(20, plus_di=0, minus_di=0)), (0., True))
        self.assertEqual(I.dx(FIX.upper(20, plus_di=None)), (None, False))

    def test_DXと差分診断を選択の追加gateにしない(self) -> None:
        """同じADX/幅/DI方向なら診断列や未来ラベルを変えて採否を変えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        context = {"共通M準備": True, "S1局面": "待機", "S1方向": 0, "S2局面": "トレンド", "S2方向": 1}
        altered = {**context, "現DX": -999, "DX_ADX差": -999, "DX差": -999,
                   "平滑恒等残差": 999, "将来先着": "逆行", "将来損益": -99999}
        for policy in I.POLICIES:
            for family in I.FAMILIES:
                for side in (1, -1):
                    self.assertEqual(I.decision(policy, family, side, context), I.decision(policy, family, side, altered))


# ----------------------------------------
# 指標銀行のcarryと、routerが許す同場公開前値を分ける。

class 上位ペア検証(unittest.TestCase):
    """公開隣接・reset・未準備と最新as-ofの境界を検査する。"""

    def test_最初の有効足は未準備で二本目からペア(self) -> None:
        """同場前値がない足を前場末尾や架空0で補わない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rows, quality = I.classify(pair(), SESSION, config())
        self.assertEqual([r["ペア準備済"] for r in rows], [False, True])
        self.assertIsNone(rows[0]["上位前足"])
        self.assertEqual(rows[0]["S2局面"], "未準備")
        self.assertEqual(quality["ペア準備足数"], 1)
        again, _ = I.classify(pair()[1:], "2026-11-04_Night", config())
        self.assertFalse(again[0]["ペア準備済"])

    def test_欠枠番号飛越はreset後現在を一本目にする(self) -> None:
        """現在が有効なら次の隣接公開足の前候補に復帰できる。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change, reason in (({"missing": 1}, "15分欠枠"), ({"index": 3}, "15分番号飛越")):
            h = pair(current=change)
            h.append(FIX.upper(26, index=h[1]["index"]+1, start=3600, end=4500, confirm=4500, confirm_line=60))
            rows, _ = I.classify(h, SESSION, config())
            self.assertFalse(rows[1]["ペア準備済"])
            self.assertIn(reason, rows[1]["ペア不可理由"])
            self.assertTrue(rows[2]["ペア準備済"])
            self.assertEqual(rows[2]["上位前足"]["index"], h[1]["index"])

    def test_非公開と必要値不正は前候補を消す(self) -> None:
        """前の有効足を飛ばして古正常pairへfallbackしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for change in ({"publish": False}, {"adx": None}, {"plus_di": None}, {"bb_mean": 0}, {"bb_sd": 0}, {"bandwidth": 0}):
            h = pair(current=change)
            h += [FIX.upper(26, index=2, start=3600, end=4500, confirm=4500, confirm_line=60),
                  FIX.upper(27, index=3, start=4500, end=5400, confirm=5400, confirm_line=70)]
            rows, _ = I.classify(h, SESSION, config())
            self.assertEqual([r["ペア準備済"] for r in rows], [False, False, False, True])
            self.assertIsNone(rows[2]["上位前足"])

    def test_最新公開cur不正は新Mを不可にし旧pairを使わない(self) -> None:
        """同秒後原行は旧pair、同原行以降は不正最新curという時点を守る。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        h = pair()+[FIX.upper(None, index=2, start=3600, end=4500, confirm=4500, confirm_line=200)]
        rows, _ = I.classify(h, SESSION, config())
        frames = [FIX.frame(0, end=4500, confirm=4500, confirm_line=199),
                  FIX.frame(1, end=4500, confirm=4500, confirm_line=200)]
        assigned = I.assign(frames, rows)
        self.assertTrue(assigned[0]["ペア準備済"])
        self.assertFalse(assigned[1]["ペア準備済"])
        self.assertEqual(assigned[1]["上位現足"]["index"], 2)

    def test_終了時刻上限と同上位繰返し割当は記録を変えない(self) -> None:
        """遅延下位のclockだけで後の上位終端を先取りしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        rows, quality = I.classify(pair(), SESSION, config())
        saved = deepcopy((rows, quality))
        assigned = I.assign([FIX.frame(0, end=3599, confirm=3601), FIX.frame(1, end=3600, confirm=3601)], rows)
        self.assertFalse(assigned[0]["ペア準備済"])
        self.assertTrue(assigned[1]["ペア準備済"])
        for size in (1, 3, 5):
            I.assign([FIX.frame(n, size) for n in range(20)], rows)
        self.assertEqual((rows, quality), saved)

    def test_非公開markerは過去判断を改訂せず次の公開curで不可になる(self) -> None:
        """非公開更新を観測したことと公開前値として参照することを分ける。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        h = pair()+[FIX.upper(26, index=2, start=3600, end=4500, confirm=4500, confirm_line=60, publish=False),
            FIX.upper(27, index=3, start=4500, end=5400, confirm=5400, confirm_line=70),
            FIX.upper(28, index=4, start=5400, end=6300, confirm=6300, confirm_line=80)]
        states, _ = I.classify(h, SESSION, config())
        rows = [FIX.frame(n, end=end, confirm=end, confirm_line=1000+n) for n, end in enumerate((4500, 5400, 6300))]
        contexts = I.assign(rows, states)
        self.assertEqual([r["ペア準備済"] for r in contexts.values()], [True, False, True])
        self.assertEqual(contexts[0]["上位現足"]["index"], 1)
        self.assertEqual(contexts[0]["局面公開原行"], 50)
        self.assertEqual(contexts[1]["上位現足"]["index"], 3)
        self.assertIsNone(contexts[1]["上位前足"])
        self.assertEqual(contexts[2]["上位前足"]["index"], 3)

    def test_15分だけを使い終了前公開と番号重複を拒否(self) -> None:
        """固定21の時点guardsを新分類も維持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for h in ([FIX.upper(minutes=5)], [FIX.upper(confirm=3599)], [FIX.upper(), FIX.upper()]):
            with self.assertRaises(ValueError):
                I.classify(h, SESSION, config())


# ----------------------------------------
# 全旧rawを保存し、M22後の選択と最終全戦略snapshotを分けて検査する。

class 発動保持検証(unittest.TestCase):
    """旧21同値・M22除外shadow・新旧選択・二段階copyを検査する。"""

    def test_三尺度両系統両sideで同じ旧発動を保持(self) -> None:
        """新routerで下位BB/MACD/Stochの発動式を作り直さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for family in I.FAMILIES:
            for side in (1, -1):
                for size in (1, 3, 5):
                    frames = lower(family, side, size)
                    h = pair(side, prior={"adx": 21, "bandwidth": .041}, current={"adx": 20}) if family == "R1" else pair(side)
                    groups, quality = generate(family, side, size, h, frames)
                    old_config = {**config(), "戦略": list(I.BASE.POLICIES)}
                    _, old = I.BASE.generate(frames, h, SESSION, frames[-1]["confirm"]+3600, frames[-1]["confirm"]+7200, old_config)
                    self.assertEqual(len(quality["全Q発動記録"]), len(old["全Q発動記録"]))
                    self.assertEqual(len(quality["全Q発動記録"]), 1)
                    current, original = quality["全Q発動記録"][0], old["全Q発動記録"][0]
                    for key in ("発動ID", "要求時計秒", "要求原板行", "side", "役割", "close", "atr", "macd_hist", "stoch_k", "直前足", "二足前"):
                        self.assertEqual(current[key], original[key])
                    self.assertEqual(current["旧21戦略判定"], original["戦略判定"])
                    self.assertTrue(all(len(rows) == 1 for rows in groups.values()))

    def test_固定21条件をそのまま旧生成と分類へ渡す(self) -> None:
        """新pairや新戦略の設定を旧raw発動の計算へ混入させない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        expected = json.loads((ROOT/"study/00021_BBとMACDとストキャスの発動切替/条件.json").read_text(encoding="utf-8"))
        with patch.object(I.BASE, "generate", wraps=I.BASE.generate) as old_generate, \
                patch.object(I.BASE, "classify", wraps=I.BASE.classify) as old_classify:
            groups, _ = generate()
        self.assertEqual(len(groups["1分_S2"]), 1)
        self.assertEqual(I.OLD_CONFIG, expected)
        self.assertEqual(old_generate.call_args.args[5], expected)
        self.assertTrue(all(call.args[2] == expected for call in old_classify.call_args_list))
        self.assertNotIn("局面改訂", old_generate.call_args.args[5])

    def test_旧M真でもペアなしはshadow保持して全戦略除外(self) -> None:
        """新Mの助走による機会消失を局面の選別効果へ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, quality = generate(higher=pair()[1:])
        self.assertTrue(all(not rows for rows in groups.values()))
        self.assertEqual(quality["旧M21発動数"], 1)
        self.assertEqual(quality["新M22発動数"], 0)
        row = quality["全Q発動記録"][0]
        self.assertTrue(row["旧M21準備"])
        self.assertFalse(row["共通M22準備"])
        self.assertFalse(row["共通M準備"])
        self.assertTrue(all(not v["採用"] for v in row["戦略判定"].values()))

    def test_始動と高ADX失速で新旧選択を分ける(self) -> None:
        """単に全条件を増やさず低ADXのT追加と高ADXのWAITを測る。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for h, s1, s2 in ((pair(prior={"adx": 21}, current={"adx": 22}), False, True),
                          (pair(prior={"adx": 30}, current={"adx": 29}), True, False)):
            groups, _ = generate(higher=h)
            self.assertEqual(bool(groups["1分_S1"]), s1)
            self.assertEqual(bool(groups["1分_S2"]), s2)
            self.assertEqual(len(groups["1分_A0"]), 1)

    def test_両側方向選択とRからWAITへの移動(self) -> None:
        """S2不成立を反対側へ自動参入する条件にしない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, _ = generate(side=-1, higher=pair(1))
        self.assertEqual(len(groups["1分_A0"]), 1)
        self.assertEqual(groups["1分_S1"], [])
        self.assertEqual(groups["1分_S2"], [])

    def test_DI零和の低ADX非上昇はMもRも有効(self) -> None:
        """診断DX0規約を未準備扱いやT参加へ読み替えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        h = pair(prior={"adx": 21, "bandwidth": .041, "plus_di": 0, "minus_di": 0},
                 current={"adx": 20, "plus_di": 0, "minus_di": 0})
        groups, quality = generate("R1", higher=h)
        self.assertTrue(all(len(v) == 1 for v in groups.values()))
        context = quality["複合context記録"][-1]
        self.assertTrue(context["共通M22準備"])
        self.assertTrue(context["DI和ゼロ"])
        self.assertEqual(context["現DX"], 0)
        self.assertEqual((context["S2局面"], context["S2方向"]), ("レンジ", 0))
        groups, _ = generate("R1", higher=pair(prior={"adx": 19, "bandwidth": .04}, current={"adx": 20, "bandwidth": .04}))
        self.assertEqual(len(groups["1分_S1"]), 1)
        self.assertEqual(groups["1分_S2"], [])

    def test_後続戦略競合確定後にだけ全case採否を複写(self) -> None:
        """早いS1の単独caseが後のS2衝突前の古い表示を持たない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames, h = lower(), pair()
        old_config = {**config(), "戦略": list(I.BASE.POLICIES)}
        _, old = I.BASE.generate(frames, h, SESSION, 10000, 20000, old_config)
        second = deepcopy(old["全Q発動記録"][0])
        second.update(入口系統="R1", 役割="反転", side=-1, 発動ID="人工R1", QイベントID="人工R1", イベントID="人工R1")
        old["全Q発動記録"].append(second)
        def select(policy: str, family: str, side: int, context: dict) -> tuple[bool, str]:
            """S1単独とS2後続衝突を同じ要求keyへ注入する。

            引数: policy/family (str) は戦略/発動、side (int) は向き、context (dict) は当時値。
            返り値: tuple[bool,str] は人工採否。実戦略の収益を評価しない。
            """
            return (policy != "S1" or family == "T1"), "人工採否"
        with patch.object(I.BASE, "generate", return_value=({}, deepcopy(old))), patch.object(I, "decision", side_effect=select):
            groups, quality = I.generate(frames, h, SESSION, 10000, 20000, config())
        self.assertEqual(groups["1分_A0"], [])
        self.assertEqual(groups["1分_S2"], [])
        self.assertEqual(len(groups["1分_S1"]), 1)
        canonical = {r["発動ID"]: r for r in quality["全Q発動記録"]}
        for cases in groups.values():
            for case in cases:
                self.assertEqual(case["戦略判定"], canonical[case["発動ID"]]["戦略判定"])
                self.assertFalse(case["戦略判定"]["S2"]["採用"])
        groups["1分_S1"][0]["上位現足"]["adx"] = -999
        self.assertEqual(quality["全Q発動記録"][0]["上位現足"]["adx"], 25)


# ----------------------------------------
# 固定21の銀行とnativefree運用を同値利用し、正式データを再生しない。

class 固定依存検証(unittest.TestCase):
    """読取wrapperと全9運用・人工会計の接続を検査する。"""

    def test_指標と運用wrapperは固定21の公開APIそのもの(self) -> None:
        """改訂routerのために指標や出口を複製変更しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        self.assertIs(J.Indicators, J.BASE.Indicators)
        self.assertIs(J.features, J.BASE.features)
        self.assertIs(O.replay, O.BASE.replay)
        self.assertIs(O.trail_parameters, O.BASE.trail_parameters)

    def test_新S2signalも同じA5一秒追尾会計へ接続(self) -> None:
        """同じ実新規の役割・保護・往復料がrouter改訂で変わらない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups, _ = generate()
        signal = groups["1分_S2"]
        now = signal[0]["要求時計秒"]
        quotes = [FIX.quote(now, 102), FIX.quote(now+1, 103), FIX.quote(now+2, 104, 1010),
            FIX.quote(now+3, 105, 1005), FIX.quote(now+4, 106, 1005), FIX.quote(now+7201, 200, 1005)]
        args = (quotes, signal, [], SESSION, "人工22", config()["運用"], {"出口ID": "X0"}, "混合", (now-100, now+7300, now+3600, now+7200))
        current, info = O.replay(*deepcopy(args))
        old, old_info = FIX.O.replay(*deepcopy(args))
        self.assertEqual(current.fills, old.fills)
        self.assertEqual(current.trades, old.trades)
        self.assertEqual(current.orders, old.orders)
        self.assertEqual(info, old_info)
        self.assertEqual(current.trades[0]["基準純損益円"], -22)
        self.assertFalse(current.trades[0]["通常出口使用"])

    def test_全9候補と事前三分3資源を空場でも残す(self) -> None:
        """未準備や無発動を候補欠落にせず固定条件の変更も拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE/"検証.py", "局面変化合成のdriver")
        sources = driver.sources(config())
        self.assertEqual(len(sources), 9)
        self.assertEqual(sum(r["時間足分"] == 3 for r in sources), 3)
        self.assertEqual(config()["出口"], [{"出口ID": "X0"}])
        for size in (1, 3, 5):
            groups, quality = driver.generate_or_empty([], [], SESSION, size, 10000, 20000, config(), [])
            self.assertEqual(list(groups), [f"{size}分_{p}" for p in I.POLICIES])
            self.assertTrue(all(not rows for rows in groups.values()))
            self.assertEqual(quality["全Q発動記録"], [])
        altered = deepcopy(config())
        altered["局面改訂"]["ADX強境界"] = 24
        with self.assertRaises(ValueError):
            I.validate_config(altered)


# ----------------------------------------
# 編集終了を明示するまで途中proofだけを保存し、固定後追加は別名とする。

def main() -> None:
    """人工ペア・旧発動・採否snapshotの合成を実行する。

    引数: なし。--finalは全編集終了後だけ指定する。
    返り値: None。失敗時は終了コード1。原板/市場損益は実行しない。
    """
    parser = argparse.ArgumentParser(description="ADX/上位幅改訂の人工合成")
    parser.add_argument("--final", action="store_true", help="合成編集終了の最終proof")
    args = parser.parse_args()
    paths = [Path(__file__), HERE/"入口.py", HERE/"指標.py", HERE/"運用.py"]
    paths += [p for p in (HERE/"検証.py", STUDY/"条件.json") if p.exists()]
    pins = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if args.final and len(paths) != 6:
        raise ValueError("全6pinが揃う前は固定不可")
    if args.final and (STUDY/"固定.json").exists():
        frozen = json.loads((STUDY/"固定.json").read_text(encoding="utf-8"))["ファイルSHA256"]
        if any(frozen.get(name) != sha for name, sha in pins.items()):
            raise ValueError("固定後の追加は別ファイルへ分離する")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    proof = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
        "合成編集終了": bool(args.final and result.wasSuccessful()), "ファイルSHA256": pins,
        "失敗": [{"検証": str(c), "内容": m} for c, m in result.failures],
        "エラー": [{"検証": str(c), "内容": m} for c, m in result.errors],
        "範囲": "人工同場15分公開ペア・ADX/幅/DIの単一S2境界・DX診断・旧21発動保持/M22除外shadow・全競合確定後case全verdict・固定21銀行/運用同値。原板/市場損益は実行しない。",
        "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k: proof[k] for k in ("全件成功", "検証件数", "合成編集終了")}, ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
