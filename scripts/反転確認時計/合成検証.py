"""00026の反転確認hを人工足で検査し、固定25のSAR/価格/追尾を保つ。"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00026_反転のSAR確認時刻と順行持続"
WORK = ROOT / "work/反転確認時計"
SESSION = "2026-11-04_Day"


def load(path: Path, name: str) -> object:
    """市場結果を実行せず検査対象のAPIだけを読む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: object は読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


FIX = load(ROOT / "scripts/SAR持続/合成検証.py", "反転確認合成の固定25人工値")
F24 = FIX.FIX
I = load(HERE / "入口.py", "反転確認合成の入口")
J = load(HERE / "指標.py", "反転確認合成の固定25指標")
O = load(HERE / "運用.py", "反転確認合成の固定25追尾")


def config() -> dict:
    """正式予定の26条件を独立コピーで読む。

    引数: なし。
    返り値: dict は条件。保存先着/損益を参照しない。
    """
    return json.loads((STUDY / "条件.json").read_text(encoding="utf-8"))


def lower(side: int = 1, count: int = 9, g_index: int | None = 6) -> list[dict]:
    """b2/f3から帯内4〜5を経て寿命内g6へ進む鏡像系列を作る。

    引数: side (int) は元突破方向、count (int) は足数、g_index (int|None) は外回復位置。
    返り値: list[dict] は各h足に違うATRを付けた公開人工3分足。
    """
    rows = F24.lower(side, count)
    for index, row in enumerate(rows):
        base = (1000, 1000, 1010, 995, 990, 985, 980)[index] if index <= 6 else 975
        if g_index is not None and index >= g_index:
            base = 1005
        close = 1000+side*(base-1000)
        row.update(close=close, open=1000, high=max(1000,close)+20, low=min(1000,close)-20,
                   atr=20 if index <= 2 else 30 if index == 3 else 40 if index == 4 else 50 if index == 5 else 60)
    return rows


def sar_rows(frames: list[dict], side: int = 1, first_r: int | None = 4) -> list[dict]:
    """価格と別に公開SAR方向の確認位置だけを制御する。

    引数: frames (list[dict]) は人工価格、side (int) は元方向、first_r (int|None) はr観測開始。
    返り値: list[dict] は元方向→反転方向→g前二本で元方向へ戻る人工記録。
    """
    rows = FIX.sar_rows(frames, side)
    for row in rows:
        index = row["index"]
        if first_r is not None and first_r <= index <= max(first_r,4):
            row["SAR方向"] = -side
    return rows


def generate(side: int = 1, frames: list[dict] | None = None, sar: list[dict] | None = None,
             first_r: int | None = 4, cutoff: float = 20000, deadline: float = 30000,
             higher: list[dict] | None = None, quantity: dict | None = None) -> tuple[dict, dict]:
    """人工価格とSARだけを新しい三案の入口へ渡す。

    引数: side (int) は元方向、frames/sar/higher (list[dict]|None) は人工上書き、
    first_r (int|None) は人工SAR確認位置、cutoff/deadline (float) は停止/期限、quantity (dict|None) は診断量。
    返り値: tuple[dict,dict] は三純入口と原価格/h監視。先着や実相場損益を計算しない。
    """
    rows = lower(side) if frames is None else frames
    return I.generate(rows, F24.FIX.higher(side) if higher is None else higher, SESSION, cutoff, deadline, config(),
                      channels=F24.FIX.channels(side), quantity=quantity,
                      sar_rows=sar_rows(rows,side,first_r) if sar is None else sar)


def family(rows: list[dict], name: str) -> list[dict]:
    """役割系統で保存原イベントを抽出する。

    引数: rows (list[dict]) は原event又はcase、name (str) は入口系統。
    返り値: list[dict] は元順序の部分集合。
    """
    return [r for r in rows if r["入口系統"] == name]


def set_close(row: dict, close: float) -> None:
    """終値を変更するとき人工OHLCの包絡も保つ。

    引数: row (dict) は変更対象足、close (float) は新終値。
    返り値: None。高安は始終値の外側へ置く。
    """
    row.update(close=close,high=max(row["open"],close)+20,low=min(row["open"],close)-20)


def price_trace(rows: list[dict]) -> list[dict]:
    """三案で差し替えた採否表示を除き、旧価格監視を全属性比較する。

    引数: rows (list[dict]) は監視trace。
    返り値: list[dict] は価格出典/時点/動作/状態を全て保持したコピー。
    """
    return FIX.price_trace(rows)


# ----------------------------------------
# f同時の確認は既存fへ採否を付け、後続hだけを新しい価格時計にする。

class 反転確認と採否検証(unittest.TestCase):
    """N0即時MACD、N1即時SAR、N2確認待ちを鏡像で検査する。"""

    def test_固定25のSAR銀行とA5を参照し三案だけを生成する(self) -> None:
        """方向確認を追加しても価格式/SAR数値/出口を変更しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        self.assertIs(J.SARBank,J.BASE.SARBank)
        self.assertIs(O.replay,O.BASE.replay)
        self.assertEqual(O.trail_parameters(20.001),(5,25))
        self.assertEqual(set(generate()[0]),{"3分_N0","3分_N1","3分_N2"})

    def test_f現在が反転方向なら同じfでN1N2を採用し重複hを作らない(self) -> None:
        """前SARが元方向でも現在SARrで即時可、二本持続へ誤って戻さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            groups,quality = generate(side,first_r=3)
            raw = quality["全Q発動記録"]
            self.assertEqual(family(raw,"R方向確認"),[])
            f = family(raw,"R内復帰")[0]
            self.assertTrue(all(f["戦略判定"][p]["採用"] for p in ("N0","N1","N2")))
            for p in ("N1","N2"):
                case = family(groups["3分_"+p],"R内復帰")[0]
                self.assertEqual((case["index"],case["side"],case["atr"]),(3,-side,30))

    def test_後続初hだけを新しい時計と現在ATRでN2へ採用する(self) -> None:
        """fより後の方向確認をf価格やfATRへ遡及しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            frames = lower(side)
            groups,quality = generate(side,frames=frames,first_r=4)
            h = family(quality["全Q発動記録"],"R方向確認")
            self.assertEqual(len(h),1)
            row = h[0]
            self.assertEqual((row["index"],row["side"],row["atr"]),(4,-side,40))
            self.assertEqual((row["要求時計秒"],row["要求原板行"]),(frames[4]["confirm"],frames[4]["confirm_line"]))
            self.assertFalse(row["戦略判定"]["N0"]["採用"])
            self.assertFalse(row["戦略判定"]["N1"]["採用"])
            self.assertTrue(row["戦略判定"]["N2"]["採用"])
            self.assertEqual(len(family(groups["3分_N2"],"R方向確認")),1)
            self.assertEqual(family(groups["3分_N1"],"R内復帰"),[])
            self.assertEqual(len(family(groups["3分_N0"],"R内復帰")),1)

    def test_N1N2はMACD符号を追加ANDせずN0だけへ使う(self) -> None:
        """同じ価格fで勢い不成立でも現在SARrならN1N2を残す。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            frames = lower(side)
            frames[3]["macd_hist"] = frames[2]["macd_hist"]+side
            groups,quality = generate(side,frames=frames,first_r=3)
            f = family(quality["全Q発動記録"],"R内復帰")[0]
            self.assertFalse(f["戦略判定"]["N0"]["採用"])
            self.assertTrue(f["戦略判定"]["N1"]["採用"])
            self.assertTrue(f["戦略判定"]["N2"]["採用"])

    def test_h後もgのTは三案同じSAR二本持続で判定する(self) -> None:
        """反転確認を消費しても元の外回復監視を終了しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            groups,quality = generate(side)
            g = family(quality["全Q発動記録"],"T外回復")
            self.assertEqual(len(g),1)
            self.assertEqual(g[0]["index"],6)
            self.assertTrue(all(g[0]["戦略判定"][p]["採用"] for p in ("N0","N1","N2")))
            self.assertEqual([family(groups["3分_"+p],"T外回復")[0]["発動ID"] for p in ("N0","N1","N2")],[g[0]["発動ID"]]*3)

    def test_原f_gと価格traceは固定25と同値でhだけ追加する(self) -> None:
        """新規hを登録bや旧f/gへ混ぜず、SAR価格式を過去のhで書換えない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            frames = lower(side)
            sar = sar_rows(frames,side)
            _,quality = generate(side,frames=frames,sar=sar)
            _,old = FIX.generate(side,frames=frames,sar=sar)
            self.assertEqual(price_trace(quality["監視trace"]),price_trace(old["監視trace"]))
            self.assertEqual(quality["エピソード診断"],old["エピソード診断"])
            own = [r for r in quality["全Q発動記録"] if r["入口系統"] != "R方向確認"]
            self.assertEqual(len(own),len(old["全Q発動記録"]))
            for a,b in zip(own,old["全Q発動記録"]):
                for key in ("発動ID","エピソードID","index","要求時計秒","要求原板行","入口系統","side","固定設定","先着評価対象"):
                    self.assertEqual(a[key],b[key])

    def test_N1反転はN2即時集合に含まれT純集合は三案同じである(self) -> None:
        """確認位置の前後だけで役割を別票にせず、三案の純条件を対応させる。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            for first in (None,3,4,5,6):
                groups,quality = generate(side,first_r=first)
                sets = {p:{r["発動ID"] for r in groups["3分_"+p] if r["役割"] == "反転"} for p in ("N0","N1","N2")}
                self.assertLessEqual(sets["N1"],sets["N2"])
                trends = [{r["発動ID"] for r in groups["3分_"+p] if r["役割"] == "順行"} for p in ("N0","N1","N2")]
                self.assertEqual(trends[0],trends[1])
                self.assertEqual(trends[1],trends[2])
                for row in family(quality["全Q発動記録"],"R内復帰"):
                    self.assertEqual(row["戦略判定"]["N1"],row["戦略判定"]["N2"])


# ----------------------------------------
# 初SARrの観測と、数値/時間/strict帯内の採否を別にし、再試行を禁止する。

class 初回消費と取消検証(unittest.TestCase):
    """技術不採用・時点対象外・親のg/取消を区別して優先順を検査する。"""

    def test_f同足SARrはM不可でも消費し後続で取り直さない(self) -> None:
        """fの現前SAR準備が揃わなくても、現在公開SARrの確認済みを消さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            frames = lower(side)
            sar = sar_rows(frames,side,3)
            sar[2].update(SAR公開可=False,SAR準備済=False,SAR方向=0)
            groups,quality = generate(side,frames=frames,sar=sar)
            self.assertEqual(family(quality["全Q発動記録"],"R方向確認"),[])
            self.assertFalse(family(quality["全Q発動記録"],"R内復帰")[0]["戦略判定"]["N2"]["採用"])
            self.assertFalse(any(r["役割"] == "反転" for r in groups["3分_N2"]))

    def test_初後続hはM不準備でも消費し後足で再採用しない(self) -> None:
        """H欠測/ATR不準備を価格監視取消やh再試行の理由へ置換しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for field in ("macd_hist","atr"):
            frames = lower()
            frames[4][field] = None
            sar = sar_rows(frames)
            sar[5]["SAR方向"] = -1
            groups,quality = generate(frames=frames,sar=sar)
            h = family(quality["全Q発動記録"],"R方向確認")
            self.assertEqual([r["index"] for r in h],[4])
            self.assertFalse(h[0]["戦略判定"]["N2"]["採用"])
            self.assertEqual(family(groups["3分_N2"],"R方向確認"),[])

    def test_時間外と確認遅延超の初hも一度消費する(self) -> None:
        """時間/遅延で不採用のhを、後の正常足へ移さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for delayed in (False,True):
            frames = lower()
            cutoff = 20000 if delayed else frames[4]["confirm"]
            if delayed:
                frames[4]["confirm"] += 31
            sar = sar_rows(frames)
            sar[5]["SAR方向"] = -1
            groups,quality = generate(frames=frames,sar=sar,cutoff=cutoff)
            h = family(quality["全Q発動記録"],"R方向確認")
            self.assertEqual([r["index"] for r in h],[4])
            self.assertFalse(h[0]["先着評価対象"])
            self.assertFalse(h[0]["戦略判定"]["N2"]["採用"])
            self.assertEqual(family(groups["3分_N2"],"R方向確認"),[])

    def test_元端等号の初SARrはraw消費しstrict帯内不可で取り直さない(self) -> None:
        """元境界等号を待機して好条件の次足へ選び直さず、g/反対端とは区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            frames = lower(side)
            set_close(frames[4],1000)
            sar = sar_rows(frames,side)
            sar[5]["SAR方向"] = -side
            groups,quality = generate(side,frames=frames,sar=sar)
            h = family(quality["全Q発動記録"],"R方向確認")
            self.assertEqual([r["index"] for r in h],[4])
            self.assertTrue(h[0]["先着評価対象"])
            self.assertFalse(h[0]["戦略判定"]["N2"]["採用"])
            self.assertEqual(family(groups["3分_N2"],"R方向確認"),[])

    def test_gと初SARrが同じ足なら外回復を先にしhを作らない(self) -> None:
        """g後の帯内復帰を過去fのh監視へ戻さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            frames = lower(side,g_index=None)
            set_close(frames[4],1000+side*5)
            _,quality = generate(side,frames=frames)
            self.assertEqual(family(quality["全Q発動記録"],"R方向確認"),[])
            self.assertEqual([r["index"] for r in family(quality["全Q発動記録"],"T外回復")],[4])

    def test_反対端等号と飛越を先取消しhへ昇格しない(self) -> None:
        """買い元突破のC<=L/売C>=RはSARr確認より先に失効する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for side in (1,-1):
            for distance in (100,101):
                frames = lower(side,g_index=None)
                set_close(frames[4],1000-side*distance)
                _,quality = generate(side,frames=frames)
                self.assertEqual(family(quality["全Q発動記録"],"R方向確認"),[])

    def test_価格欠枠と未公開は親取消を優先し次のSARrで復活しない(self) -> None:
        """価格の連続性失効をM不可のh消費に置換しない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for field,value in (("missing",1),("publish",False)):
            frames = lower()
            frames[4][field] = value
            _,quality = generate(frames=frames)
            self.assertEqual(family(quality["全Q発動記録"],"R方向確認"),[])

    def test_返済期限の足で初SARrでもhを作らない(self) -> None:
        """h観測より期限取消を先にし、時間不可counterfactualと区別する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower()
        deadline = frames[2]["confirm"]+3601
        for row in frames[3:]:
            row["confirm"] = deadline-1+row["index"]-3
        _,quality = generate(frames=frames,deadline=deadline)
        self.assertEqual(len(family(quality["全Q発動記録"],"R内復帰")),1)
        self.assertEqual(family(quality["全Q発動記録"],"R方向確認"),[])

    def test_hの第三足は採用可能で第四足は満了する(self) -> None:
        """同じSAR方向条件でも後続寿命を件数に応じて広げない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for first,expected in ((6,[6]),(7,[])):
            _,quality = generate(frames=lower(g_index=None),first_r=first)
            self.assertEqual([r["index"] for r in family(quality["全Q発動記録"],"R方向確認")],expected)

    def test_endと公開keyが前段より後でない足は寿命だけ進める(self) -> None:
        """f確認と同時終了の足のSARrを使わず、次のeligible足から確認する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for close in (990,900,1005):
            frames = lower()
            frames[3]["confirm"] = frames[4]["end"]
            set_close(frames[4],close)
            sar = sar_rows(frames)
            sar[5]["SAR方向"] = -1
            _,quality = generate(frames=frames,sar=sar)
            self.assertEqual([r["index"] for r in family(quality["全Q発動記録"],"R方向確認")],[5])

    def test_公開不可SARrは確認に使わず次の公開rを初hとする(self) -> None:
        """数値方向がrでも未公開なら確認済みにせず、次足のM25は別に判定する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        frames = lower()
        sar = sar_rows(frames)
        sar[4]["SAR公開可"] = False
        sar[5]["SAR方向"] = -1
        _,quality = generate(frames=frames,sar=sar)
        h = family(quality["全Q発動記録"],"R方向確認")
        self.assertEqual([r["index"] for r in h],[5])
        self.assertFalse(h[0]["戦略判定"]["N2"]["採用"])


# ----------------------------------------
# 全三案の採否snapshotとh時計からの実約定・先着対象を接続する。

class 正本と運用接続検証(unittest.TestCase):
    """競合確定、h現在ATR、固定A5、対象外とprepare禁止経路を検査する。"""

    def test_N2だけh_g競合でもN0N1caseの全N採否を正本へ更新する(self) -> None:
        """人工的な同要求keyの衝突を全案確定後に深く複写する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        original = I.h_signal
        frames = lower()

        def collide(*args: object,**kwargs: object) -> dict:
            """hの要求だけを後のgと同じ人工keyへ置く。

            引数: args/kwargs (object) は元h_signal引数。
            返り値: dict は競合検査専用に要求keyを置換したh。
            """
            row = original(*args,**kwargs)
            row.update(要求時計秒=frames[6]["confirm"],要求原板行=frames[6]["confirm_line"])
            return row

        with patch.object(I,"h_signal",side_effect=collide):
            groups,quality = generate(frames=frames)
        self.assertEqual(groups["3分_N2"],[])
        canonical = {r["発動ID"]:r for r in quality["全Q発動記録"]}
        for cases in groups.values():
            for case in cases:
                self.assertEqual(case["戦略判定"],canonical[case["発動ID"]]["戦略判定"])
        g = family(groups["3分_N1"],"T外回復")[0]
        self.assertTrue(g["戦略判定"]["N2"]["同時競合"])
        self.assertFalse(g["戦略判定"]["N2"]["採用"])
        for trace in quality["監視trace"]+quality["反転監視trace"]:
            for action in trace["動作"]:
                if "戦略採否" in action:
                    self.assertEqual(action["戦略採否"],canonical[action["発動ID"]]["戦略判定"])

    def test_hとf_gの設定snapshotを後の状態やcase編集で書換えない(self) -> None:
        """hのf参照とgの内復帰参照を独立コピーで保持する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        groups,quality = generate()
        canonical = {r["発動ID"]:r for r in quality["全Q発動記録"]}
        h = family(groups["3分_N2"],"R方向確認")[0]
        g = family(groups["3分_N1"],"T外回復")[0]
        self.assertEqual(h["固定設定"]["内復帰"]["index"],3)
        h["固定設定"]["内復帰"]["index"] = 999
        self.assertEqual(canonical[h["発動ID"]]["固定設定"]["内復帰"]["index"],3)
        self.assertEqual(g["固定設定"]["内復帰"]["index"],3)
        self.assertTrue(all("ラベル" not in r for r in canonical.values()))

    def test_h実新規のATRと役割を固定し後のTでドテンせずA5最低同値を保つ(self) -> None:
        """人工BBOでh後の保有中T抑止と一秒返済を検査する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。実相場損益は計算しない。
        """
        for side in (1,-1):
            frames = lower(side)
            frames[6]["confirm_line"] = 200
            groups,_ = generate(side,frames=frames)
            signals = groups["3分_N2"]
            self.assertEqual([r["入口系統"] for r in signals],["R方向確認","T外回復"])
            now,g = signals[0]["要求時計秒"],signals[1]["要求時計秒"]
            quote = F24.Q
            quotes = [quote(now,103),quote(now+1,104),quote(now+2,105),quote(g-100,190),quote(g,200),
                      quote(g+1,201,990 if side == 1 else 1010),quote(g+2,202,995 if side == 1 else 1005),
                      quote(g+2,203,995 if side == 1 else 1005),quote(g+3,204,995 if side == 1 else 1005),quote(now+7201,300)]
            args = (quotes,signals,[],SESSION,"人工26",config()["運用"],{"出口ID":"X0"},"混合",
                    (now-100,now+7300,now+3600,now+7200))
            state,info = O.replay(*deepcopy(args))
            old,old_info = FIX.O.replay(*deepcopy(args))
            self.assertEqual((state.fills,state.orders,state.trades,info),(old.fills,old.orders,old.trades,old_info))
            self.assertEqual(len(state.trades),1)
            trade = state.trades[0]
            self.assertEqual((trade["入口役割"],trade["入口ATR"],trade["追尾距離pt"]),("反転",40,40))
            self.assertEqual((trade["追尾起動"],trade["返済時計秒"],trade["基準純損益円"]),(True,g+3,-22))
            self.assertEqual(info["建玉中抑止数"],1)

    def test_等号h技術不採用でも時間遅延可なら原先着診断を呼べる(self) -> None:
        """strict帯内の採否と先着評価対象のtime/delayを分離する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE/"検証.py","反転確認合成の技術不採用h先着")
        frames = lower()
        set_close(frames[4],1000)
        _,quality = generate(frames=frames)
        h = family(quality["全Q発動記録"],"R方向確認")[0]
        self.assertTrue(h["先着評価対象"])
        self.assertFalse(h["h価格条件可"])
        path = SimpleNamespace(evaluate=unittest.mock.Mock(return_value={"ラベル":"人工診断"}))
        driver.shadow_label(h,path,{},20000,30000,config())
        path.evaluate.assert_called_once_with(frames[4]["confirm"],20000,30000,-1,adverse=125,favorable=250)

    def test_時間外と確認遅延超hは先着を呼ばず時間優先と九数値Noneを保つ(self) -> None:
        """hという新系統でも対象外を未約定や技術不採用へ混ぜない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE/"検証.py","反転確認合成の対象外h先着")
        for cutoff,reason in ((4531,"要求時間条件外"),(20000,"足確定確認遅延30秒超")):
            frames = lower()
            frames[4]["confirm"] += 31
            _,quality = generate(frames=frames,cutoff=cutoff)
            h = family(quality["全Q発動記録"],"R方向確認")[0]
            forbidden = SimpleNamespace(evaluate=unittest.mock.Mock(side_effect=AssertionError("対象外先着は禁止")))
            result = driver.shadow_label(h,forbidden,{},cutoff,30000,config())
            self.assertEqual((result["ラベル"],result["理由"]),("対象外",reason))
            values = [v for k,v in result.items() if k not in ("ラベル","理由")]
            self.assertEqual(len(values),9)
            self.assertTrue(all(v is None for v in values))
            forbidden.evaluate.assert_not_called()

    def test_三候補と空足零を保ち旧十九項目と新確認規約の変更を拒否する(self) -> None:
        """三本寿命・等号消費・支持/費用/追尾の表示だけの変更を拒否する。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        driver = load(HERE/"検証.py","反転確認合成の三定義")
        self.assertEqual([r["入口ID"] for r in driver.sources(config())],["3分_N0","3分_N1","3分_N2"])
        groups,quality = driver.generate_or_empty([],[],SESSION,3,20000,30000,config(),[],[],{},[])
        self.assertEqual(groups,{"3分_N0":[],"3分_N1":[],"3分_N2":[]})
        self.assertEqual(quality["全Q発動記録"],[])
        self.assertEqual(quality["反転監視trace"],[])
        inherited = ("対象","全65場既使用","運用","必須追尾","発動条件","指標","局面改訂","逆行pt","順行pt",
            "残り時間下限分","確認遅延上限秒","入口支持","費用支持","目標確認率","間引き必要件数","分割","出口","終値切替","SAR")

        def changed(value: object) -> object:
            """固定値の最初の葉だけを同じ型で変更する。

            引数: value (object) は固定値。
            返り値: object は一箇所変更したコピー。
            """
            if isinstance(value,bool):
                return not value
            if isinstance(value,(int,float)):
                return value+1
            if isinstance(value,str):
                return value+"規約変更"
            result = deepcopy(value)
            if isinstance(value,list):
                result[0] = changed(result[0])
            elif isinstance(value,dict):
                key = next(iter(result))
                result[key] = changed(result[key])
            else:
                raise TypeError("想定外の固定型")
            return result

        for key in inherited:
            altered = deepcopy(config())
            altered[key] = changed(altered[key])
            with self.assertRaises(ValueError,msg=key):
                I.validate_config(altered)
        for key in config()["反転確認"]:
            altered = deepcopy(config())
            altered["反転確認"][key] = changed(altered["反転確認"][key])
            with self.assertRaises(ValueError,msg=key):
                I.validate_config(altered)

    def test_prepare六十五人工場で先着運用固定禁止と三案一九五行を確認する(self) -> None:
        """新h出力があってもprepareから評価・正式損益へ進めない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。原データ/実cacheは開かない。
        """
        driver = load(HERE/"検証.py","反転確認合成のprepare")
        with tempfile.TemporaryDirectory(prefix="反転確認合成_") as directory:
            base = Path(directory)
            study,work = base/"試行",base/"作業"
            study.mkdir()
            (study/"条件.json").write_text(json.dumps(config(),ensure_ascii=False),encoding="utf-8")
            source = base/"人工入力"
            source.write_text("",encoding="utf-8")
            stat = source.stat()
            sessions = [f"{date(2026,9,21)+timedelta(days=n)}_{kind}" for n in range(20) for kind in ("Day","Night")]
            sessions += [f"{date(2026,10,19)+timedelta(days=n)}_{kind}" for n in range(12) for kind in ("Day","Night")]
            sessions += [SESSION]
            manifest = {"source_root":str(base),"entries":[{"session":s,"symbol":"NK225","source_path":source.name,
                "source_size":stat.st_size,"source_mtime_ns":stat.st_mtime_ns,"cache_path":"存在しない人工cache",
                "sha256_cache":"人工SHA","in_session_contract_codes":["人工限月"]} for s in sessions]}
            original = driver.W.read_json

            def read_json(path: Path) -> dict:
                """人工台帳だけ置換し一時条件を読む。

                引数: path (Path) は参照先。
                返り値: dict は人工台帳又は条件。
                """
                return deepcopy(manifest) if path == driver.INPUT else original(path)

            forbidden = SimpleNamespace(replay=unittest.mock.Mock(side_effect=AssertionError("運用は禁止")))
            with patch.object(driver.W,"read_json",side_effect=read_json),patch.object(driver.O,"sha",return_value="人工SHA"), \
                    patch.object(driver.W.PREP,"read_events",return_value=[]), \
                    patch.object(driver.W.OLD,"気配経路",side_effect=AssertionError("先着は禁止")), \
                    patch.object(driver,"module",return_value=forbidden), \
                    patch.object(driver,"freeze",side_effect=AssertionError("固定は禁止")),redirect_stdout(io.StringIO()):
                result = driver.run(study,work,True)
            self.assertFalse(result["ラベル計算"])
            self.assertFalse(result["損益計算"])
            forbidden.replay.assert_not_called()
            summary = json.loads((work/"準備点検.json").read_text(encoding="utf-8"))
            self.assertEqual(len(summary["準備"]),65)
            self.assertEqual(len(summary["場別発動"]),195)
            self.assertFalse((study/"結果.json").exists())
            self.assertFalse(any(work.glob("*.jsonl.gz")))

    def test_ATR極微差は同じεD整数の技術投影で一致し原実値を変更しない(self) -> None:
        """準備canonicalだけをATR整数出力へ投影し、他の浮動値を丸めない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        original=[{"atr":20.1,"f":{"atr":35.3},"close":1000.,"other":None}]
        slightly=deepcopy(original)
        slightly[0]["atr"]+=1e-14
        slightly[0]["f"]["atr"]-=1e-14
        before=deepcopy(slightly)
        self.assertEqual(I.canonical_sha(original),I.canonical_sha(slightly))
        self.assertEqual(slightly,before)
        different=deepcopy(original)
        different[0]["close"]+=1e-8
        self.assertNotEqual(I.canonical_sha(original),I.canonical_sha(different))

    def test_ATR許容内の差でもceil境界を跨ぐε又はD差は投影hashが異なる(self) -> None:
        """小さい誤差という理由だけで注文のtick整数の差を隠さない。

        引数: self (TestCase) は検証インスタンス。
        返り値: None。
        """
        for base in (20.,25.):
            after=base+1e-14
            self.assertLess(abs(after-base),1e-10)
            left=(max(5,math.ceil(.25*base/5)*5),max(5,math.ceil(base/5)*5))
            right=(max(5,math.ceil(.25*after/5)*5),max(5,math.ceil(after/5)*5))
            self.assertNotEqual(left,right)
            self.assertNotEqual(I.canonical_sha([{"atr":base}]),I.canonical_sha([{"atr":after}]))


def main() -> None:
    """人工検証と6pinsを途中又は編集終了proofへ記録する。

    引数: なし。--finalは全実装停止・主独立準備一致後に指定する。
    返り値: None。失敗時終了1。実相場の先着/P&Lや正式結果を参照しない。
    """
    parser = argparse.ArgumentParser(description="反転のSAR確認時刻の人工合成")
    parser.add_argument("--final",action="store_true",help="合成編集終了の最終proof")
    args = parser.parse_args()
    expected = [HERE/n for n in ("指標.py","入口.py","運用.py","検証.py","合成検証.py")]+[STUDY/"条件.json"]
    paths = [p for p in expected if p.exists()]
    pins = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if args.final and len(paths) != 6:
        raise ValueError("全6pin前は固定不可")
    if args.final and (STUDY/"固定.json").exists():
        frozen = json.loads((STUDY/"固定.json").read_text(encoding="utf-8"))["ファイルSHA256"]
        if any(frozen.get(k) != v for k,v in pins.items()):
            raise ValueError("固定後の追加は別名へ分離する")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    proof = {"全件成功":result.wasSuccessful(),"検証件数":result.testsRun,"合成編集終了":bool(args.final and result.wasSuccessful()),
        "ファイルSHA256":pins,"失敗":[{"検証":str(c),"内容":m} for c,m in result.failures],
        "エラー":[{"検証":str(c),"内容":m} for c,m in result.errors],
        "範囲":"人工価格/SARによるf同時確認/後続h/初回消費・元端等号技術不採用・g/親取消/反対端/期限/寿命/時点の優先・鏡像・M準備と値条件分離・固定25価格trace/SAR/A5再用。正式先着/P&Lは実行しない。",
        "実行記録":stream.getvalue()}
    WORK.mkdir(parents=True,exist_ok=True)
    (WORK/("合成検証.json" if args.final else "合成検証_途中.json")).write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({k:proof[k] for k in ("全件成功","検証件数","合成編集終了")},ensure_ascii=False))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
