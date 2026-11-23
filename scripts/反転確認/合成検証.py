"""00012の一足確認・送信前構造拒否・実約定後保護を合成経路で確認する。"""

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
    """合成対象と固定済みのテスト用足・気配補助を読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: object はモジュール。実データは読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


I = module(Path(__file__).with_name("入口.py"), "反転入口の合成対象")
E = module(Path(__file__).with_name("運用.py"), "反転運用の合成対象")
T = module(ROOT / "scripts/テクニカル循環/入口検証.py", "固定の合成足補助")
F = module(ROOT / "scripts/テクニカル循環/合成検証.py", "固定の合成気配補助")
SESSION, CONFIG, BOUNDS = F.SESSION, deepcopy(F.CONFIG), F.BOUNDS


def recovery(size: int = 3) -> list[dict]:
    """R2設定足から次足で設定高値94を越える列を作る。

    引数: size (int) は3分または5分。
    返り値: list[dict] は6本履歴・設定足・確認足。
    """
    values = [T.frame(n, size, bb_mean=100., bb_sd=5.) for n in range(6)]
    values[-1].update(close=85., low=84.)
    values.append(T.frame(6, size, open=90., close=90., high=94., low=80., bb_mean=100., bb_sd=5., atr=10.))
    values.append(T.frame(7, size, open=92., close=95., high=96., low=91., bb_mean=80., bb_sd=5., atr=20.))
    return values


def generate(values: list[dict], higher: list[dict] | None = None, cutoff: float = 20000,
             deadline: float = 30000) -> tuple[dict, dict]:
    """固定時刻条件で即時と一足確認を生成する。

    引数: values/higher (list[dict]|None) は足、cutoff/deadline (float) は時計。
    返り値: tuple[dict,dict] は発動列と品質。
    """
    return I.generate(values, [T.higher()] if higher is None else higher, SESSION, cutoff, deadline, T.CONFIG)


def signal(side: int = 1, structure: float = 975., now: float = 10., line: int = 2) -> dict:
    """当時既知の設定足と固定構造価格を持つ新規要求を作る。

    引数: side (int) は方向、structure/now (float) は構造/要求時計、line (int) は原行。
    返り値: dict は未来ラベルを持たない合成要求。
    """
    row = F.signal(now=now, line=line, side=side)
    setup = {"index": 0, "end": now, "confirm": now, "confirm_line": line,
             "low": structure + 5 if side == 1 else 980., "high": 1020. if side == 1 else structure - 5,
             "close": 1000., "bb_mean": 1100., "atr": 20.}
    row.update(構造価格=structure, 設定足=setup, 確認方式="即時")
    return row


def state(mode: str = "構造", side: int = 1, structure: float = 975., prior: bool = True,
          now: float = 10., prior_time: float = 9.) -> object:
    """要求前の正常板を観測した任意の新規待機状態を作る。

    引数: mode (str) は固定/構造、side (int) は方向、structure/now/prior_time (float) は価格/時計、
    prior (bool) は要求前正常板を与えるか。
    返り値: object は新規要求処理後の状態。
    """
    row = signal(side, structure, now)
    value = E.反転確認状態(SESSION, "合成", deepcopy(CONFIG), {"出口ID": mode}, "反転", [row], BOUNDS)
    if prior:
        value.quote(prior_time, 1, 995. if side == 1 else 1000., 1000. if side == 1 else 1005.)
    value.signal_group([row])
    return value


# ----------------------------------------
# 入口は純125/250評価の集合。構造による送信拒否をここへ混ぜない。

class 入口確認(unittest.TestCase):
    """即時と次の連続一足確認を検証する。"""

    def test_即時は旧R2と同じ設定足(self) -> None:
        """新しい方式でも即時発動足と方向を変えない。

        引数: self (入口確認) はテスト。
        返り値: None。
        """
        for size in (3, 5):
            values = recovery(size)
            original, _ = I.CORE.generate(values, [T.higher()], SESSION, 20000, 30000, T.CONFIG)
            output, _ = generate(values)
            self.assertEqual([(r["index"], r["side"]) for r in output[f"{size}分_即時"]],
                             [(r["index"], r["side"]) for r in original[f"{size}分_R2"]])

    def test_確認ATRは現足だが中心と構造は設定足(self) -> None:
        """確認足中心を設定中心へ後付けで差し替えず出所を区別する。

        引数: self (入口確認) はテスト。
        返り値: None。
        """
        output, _ = generate(recovery())
        rows = output["3分_次足確認"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["index"], row["atr"], row["bb_mean"], row["確認足bb_mean"], row["構造価格"]), (7, 20., 100., 80., 75.))
        self.assertEqual(row["設定足"]["index"], 6)

    def test_同足不可と次足高値等号不可(self) -> None:
        """設定足自体と、次足の設定高値への接触だけで確認しない。

        引数: self (入口確認) はテスト。
        返り値: None。
        """
        self.assertFalse(generate(recovery()[:-1])[0]["3分_次足確認"])
        values = recovery()
        values[-1]["close"] = 94.
        self.assertFalse(generate(values)[0]["3分_次足確認"])
        values.append(T.frame(8, close=95., bb_mean=100., bb_sd=5.))
        self.assertFalse(generate(values)[0]["3分_次足確認"])

    def test_設定中心は確認時も有利側かつ等号不可(self) -> None:
        """確認時中心が遠くても設定中心到達を有利側としない。

        引数: self (入口確認) はテスト。
        返り値: None。
        """
        values = recovery()
        values[-1].update(close=100., high=101., bb_mean=200.)
        self.assertFalse(generate(values)[0]["3分_次足確認"])

    def test_確認足もADX未満と共通準備と時間を要求(self) -> None:
        """設定足だけでなく確認足のADX/ATR/共通時間を検査する。

        引数: self (入口確認) はテスト。
        返り値: None。
        """
        for changes in ({"adx": 20.}, {"atr": 0.}, {"ema20": None}, {"bb_sd": None}):
            values = recovery()
            values[-1].update(changes)
            self.assertFalse(generate(values)[0]["3分_次足確認"])
        values = recovery()
        clock = values[-1]["confirm"]
        self.assertFalse(generate(values, cutoff=clock)[0]["3分_次足確認"])
        self.assertEqual(len(generate(values, deadline=clock + 3600)[0]["3分_次足確認"]), 1)
        self.assertFalse(generate(values, deadline=clock + 3599)[0]["3分_次足確認"])

    def test_欠枠非公開を跨いで設定を再使用しない(self) -> None:
        """欠枠や未公開の次足では設定が失効する。

        引数: self (入口確認) はテスト。
        返り値: None。
        """
        for changes in ({"missing": 1}, {"publish": False}):
            values = recovery()
            values[-1].update(changes)
            values.append(T.frame(8, close=96., bb_mean=100., bb_sd=5.))
            self.assertFalse(generate(values)[0]["3分_次足確認"])

    def test_鏡像と未来ラベル不変(self) -> None:
        """売りの対称条件と将来損益からの独立を確認する。

        引数: self (入口確認) はテスト。
        返り値: None。
        """
        values = recovery()
        output, _ = generate([T.mirror(r) for r in values], [T.mirror(T.higher())])
        self.assertEqual([(r["index"], r["side"], r["構造価格"]) for r in output["3分_次足確認"]], [(7, -1, 125.)])
        for row in values:
            row.update(ラベル="順行先着", 将来損益=999999)
        self.assertEqual(len(generate(values)[0]["3分_次足確認"]), 1)


# ----------------------------------------
# 送信前は既知の正常板だけ。送信後の不利な板をfee0取消に使わない。

class 構造運用確認(unittest.TestCase):
    """既知板の鮮度と構造保護・待機・固定同値を検証する。"""

    def test_要求前BBOなしと古い板は送信しない(self) -> None:
        """次の約定板を事前確認に使わず、古さ30秒超を拒否する。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        for value in (state(prior=False), state(now=40.001, prior_time=10.)):
            value.quote(41.1, 3, 995., 1000.)
            self.assertFalse(value.fills)
            self.assertEqual(value.cash, 0)
        exact = state(now=40., prior_time=10.)
        exact.quote(41., 3, 995., 1000.)
        self.assertEqual(len(exact.fills), 1)

    def test_要求時既知板の構造等号は送信前拒否(self) -> None:
        """構造に接した買Bid/売Askをfeeなしで拒否する。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        for side, level in ((1, 995.), (-1, 1005.)):
            value = state(side=side, structure=level)
            value.quote(11., 3, 1000., 1005.)
            self.assertFalse(value.fills)
            self.assertEqual(value.cash, 0)

    def test_送信後の無効板は約定してから保護し往復fee(self) -> None:
        """不利な実約定板を見てfee0取消する楽観を禁止する。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        value = state(structure=975.)
        value.quote(11., 3, 970., 975.)
        self.assertEqual(len(value.fills), 1)
        self.assertEqual(value.fills[0]["price"], 975.)
        self.assertIsNotNone(value.pending)
        self.assertEqual(value.pending["time"], 11.)
        value.quote(11., 4, 965., 970.)
        self.assertEqual(len(value.fills), 1)
        value.quote(12., 5, 960., 965.)
        self.assertEqual(len(value.fills), 2)
        self.assertEqual(value.trades[0]["基準純損益円"], -172.)
        self.assertEqual(value.trades[0]["手数料円"], 22)

    def test_同時計未来原行で事前拒否を救済しない(self) -> None:
        """要求より後の同時計正常板は要求時点で未知である。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        row = signal(structure=995., now=10., line=2)
        events = [F.quote(9., 1, 995., 1000.), F.quote(10., 3, 1000., 1005.), F.quote(11., 4, 1000., 1005.)]
        value, _ = E.replay(events, [row], [], SESSION, "合成", deepcopy(CONFIG), {"出口ID": "構造"}, "反転", BOUNDS)
        self.assertFalse(value.fills)
        self.assertEqual(value.cash, 0)

    def test_構造保護は返済側等号で要求して一秒後BBO(self) -> None:
        """買いと売りの構造線へ即約定せず実気配で返済する。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        for side, level in ((1, 975.), (-1, 1025.)):
            value = state(side=side, structure=level)
            value.quote(11., 3, 995. if side == 1 else 1000., 1000. if side == 1 else 1005.)
            value.quote(12., 4, 975. if side == 1 else 1020., 980. if side == 1 else 1025.)
            self.assertEqual(len(value.fills), 1)
            value.quote(13., 5, 970. if side == 1 else 1035., 975. if side == 1 else 1040.)
            self.assertEqual(value.trades[0]["保護価格"], level)
            self.assertEqual(value.trades[0]["返済価格"], 970. if side == 1 else 1040.)

    def test_構造が遠くても初期百二十五を広げない(self) -> None:
        """遠い設定足の極値よりhard125を先に用いる。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        value = state(structure=700.)
        value.quote(11., 3, 995., 1000.)
        value.quote(12., 4, 875., 880.)
        self.assertEqual(value.pending["reason"], "保護")
        value.quote(13., 5, 870., 875.)
        self.assertEqual(value.trades[0]["保護価格"], 875.)

    def test_構造保護でもTP二百五十を維持(self) -> None:
        """通常のTP250到達で要求し、次秒の板で確定する。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        value = state()
        value.quote(11., 3, 995., 1000.)
        value.quote(12., 4, 1250., 1255.)
        self.assertEqual(value.pending["reason"], "利確")
        value.quote(13., 5, 1240., 1245.)
        self.assertEqual(value.trades[0]["返済価格"], 1240.)

    def test_新規一秒とTTLを維持(self) -> None:
        """送信後の新規待機を短縮せず30秒超失効を守る。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        value = state()
        value.quote(10.5, 3, 970., 975.)
        self.assertFalse(value.fills)
        value.quote(11., 4, 995., 1000.)
        self.assertEqual(len(value.fills), 1)
        expired = state()
        expired.quote(40.1, 3, 995., 1000.)
        self.assertFalse(expired.fills)
        self.assertEqual(expired.cash, 0)

    def test_固定は旧X0の約定会計と同値(self) -> None:
        """固定模型へ送信前構造拒否や新たな出口を足さない。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        row = signal(structure=1010.)
        events = [F.quote(9., 1, 995., 1000.), F.quote(11., 3, 995., 1000.),
                  F.quote(12., 4, 1250., 1255.), F.quote(13., 5, 1240., 1245.)]
        new, _ = E.replay(events, [row], [], SESSION, "合成", deepcopy(CONFIG), {"出口ID": "固定"}, "反転", BOUNDS)
        old, _ = F.E.replay(events, [row], [], SESSION, "合成", deepcopy(CONFIG), {"出口ID": "X0"}, "反転", BOUNDS)
        self.assertEqual(new.fills, old.fills)
        self.assertEqual(new.cash, old.cash)
        self.assertEqual(len(new.trades), len(old.trades))
        for key, expected in old.trades[0].items():
            if key not in ("出口ID",):
                self.assertEqual(new.trades[0][key], expected)

    def test_同時計の要求原行以前の正常板を利用(self) -> None:
        """要求と同時計でも先に観測した原行を有効な送信前板とする。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        row = signal(now=10., line=2)
        events = [F.quote(10., 1, 995., 1000.), F.quote(11., 3, 995., 1000.),
                  F.quote(12., 4, 1250., 1255.), F.quote(13., 5, 1240., 1245.)]
        value, info = E.replay(events, [row], [], SESSION, "合成", deepcopy(CONFIG), {"出口ID": "構造"}, "反転", BOUNDS)
        self.assertEqual(len(value.fills), 2)
        self.assertEqual(info["構造未確認新規取消数"], 0)

    def test_不正板で要求前板の鮮度を更新しない(self) -> None:
        """直前の不正BBOを正常な送信前根拠へ変換しない。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        row = signal(now=40., line=3)
        events = [F.quote(0., 1, 995., 1000.), F.quote(39., 2, 995., 1000., valid=False),
                  F.quote(41., 4, 995., 1000.)]
        value, info = E.replay(events, [row], [], SESSION, "合成", deepcopy(CONFIG), {"出口ID": "構造"}, "反転", BOUNDS)
        self.assertFalse(value.fills)
        self.assertEqual(info["構造未確認新規取消数"], 1)
        self.assertEqual(info["構造無効新規取消数"], 0)
        self.assertEqual(value.orders[0]["取消理由"], "構造未確認で送信前取消")

    def test_期限要求は同原行の構造割れより優先(self) -> None:
        """期限時に構造を割れても既存期限要求を取り替えない。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        value = state()
        value.quote(11., 3, 995., 1000.)
        value.quote(950., 4, 860., 865.)
        self.assertEqual(value.pending["reason"], "期限")
        self.assertEqual(value.pending["time"], 950.)
        value.quote(951., 5, 850., 855.)
        self.assertEqual(value.trades[0]["返済理由"], "期限")

    def test_設定足と構造は約定後に変更しない(self) -> None:
        """後の特徴更新で入口時の構造保護を遠ざけない。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        value = state()
        value.quote(11., 3, 995., 1000.)
        value.features["入口1"]["構造価格"] = 700.
        value.features["入口1"]["設定足"]["low"] = 705.
        value.quote(12., 4, 975., 980.)
        value.quote(13., 5, 970., 975.)
        self.assertEqual(value.trades[0]["構造価格"], 975.)
        self.assertEqual(value.trades[0]["設定足"]["low"], 980.)
        self.assertEqual(value.trades[0]["保護価格"], 975.)

    def test_新規停止と建玉中抑止を構造拒否で上書きしない(self) -> None:
        """送信へ進まない要求を構造審査の件数へ混ぜない。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        stopped = state(now=900., prior=False)
        self.assertEqual(stopped.structure_unknown_count, 0)
        self.assertEqual(stopped.signals[0]["取扱"], "新規停止時刻外")
        value = state()
        value.quote(11., 3, 995., 1000.)
        row = signal(now=12., line=4)
        row["イベントID"] = "入口2"
        value.features["入口2"] = row
        value.signal_group([row])
        self.assertEqual(value.signals[-1]["取扱"], "建玉中抑止")
        self.assertEqual(value.structure_unknown_count, 0)

    def test_TTL三十秒等号の不利約定も無償取消しない(self) -> None:
        """有効期限内の最後の秒で破れても実新規と保護要求を残す。

        引数: self (構造運用確認) はテスト。
        返り値: None。
        """
        value = state()
        value.quote(40., 3, 970., 975.)
        self.assertEqual(len(value.fills), 1)
        self.assertEqual(value.pending["reason"], "構造保護")
        self.assertEqual(value.structure_cancel_count, 0)


# ----------------------------------------
# driverは実数値を呼ばず、固定依存と新しい取消分類の集計だけを検証する。

class 実行側確認(unittest.TestCase):
    """固定前のdriver参照漏れと診断列の混同を検査する。"""

    def test_依存固定に新合成と継承元を含める(self) -> None:
        """新3コードと旧11の継承元・テスト用補助を固定一覧へ含める。

        引数: self (実行側確認) はテスト。
        返り値: None。SHA計算と書込はmockで実行し正式固定を作らない。
        """
        sys.modules["入口"] = I
        driver = module(Path(__file__).with_name("検証.py"), "反転driver合成")
        study = ROOT / "work/反転確認/合成固定専用の未作成先"
        self.assertFalse(study.exists())
        with patch.object(driver.O, "sha", return_value="合成SHA"), patch.object(driver.W, "write_json"):
            locked = driver.freeze(study)
        pins = locked["ファイルSHA256"]
        for path in ("scripts/反転確認/合成検証.py", "scripts/反転確認/入口.py", "scripts/反転確認/運用.py",
                     "scripts/テクニカル循環/運用.py", "scripts/テクニカル循環/入口検証.py", "scripts/テクニカル循環/合成検証.py"):
            self.assertIn(path, pins)

    def test_未確認と無効の取消集計を分離する(self) -> None:
        """送信前の未確認・無効と約定後保護を別々に集計する。

        引数: self (実行側確認) はテスト。
        返り値: None。元会計集約だけmockで分離する。
        """
        sys.modules["入口"] = I
        driver = module(Path(__file__).with_name("検証.py"), "反転driver列合成")
        infos = [{"観測含み込み最大DD円": 0., "観測最悪時価円": 0., "構造無効新規取消数": 2,
                  "構造未確認新規取消数": 3, "構造保護返済数": 4}]
        with patch.object(driver.E, "operation_metrics", return_value={"赤字場数": 0, "活動場数": 0}):
            values = driver.operation_metrics(infos, [], "反転", {"出口ID": "構造"})
        self.assertEqual((values["構造無効新規取消数"], values["構造未確認新規取消数"], values["構造保護返済数"]), (2, 3, 4))


def run() -> dict:
    """合成検査だけを行い、明示合否と対象版をGit外へ保存する。

    引数: なし。実データや研究結果は読み込まない。
    返り値: dict は検査件数・失敗・例外・指紋。
    """
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "失敗": [{"検査": str(t), "内容": text} for t, text in result.failures],
              "エラー": [{"検査": str(t), "内容": text} for t, text in result.errors],
              "ファイルSHA256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__), Path(__file__).with_name("入口.py"), Path(__file__).with_name("運用.py"))},
              "範囲": "入口の一足確認と、要求時既知BBOによる構造送信前拒否・送信後の不利約定/往復費用・固定同値。数値再生なし。",
              "実行記録": stream.getvalue()}
    target = ROOT / "work/反転確認/合成検証.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(stream.getvalue())
    return report


if __name__ == "__main__":
    if not run()["全件成功"]:
        raise SystemExit(1)
