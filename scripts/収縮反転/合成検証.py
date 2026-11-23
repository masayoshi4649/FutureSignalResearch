"""00013の20/6/6/3状態順・補助独立・時点を実データなしで確認する。"""

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
    """合成対象をコマンド行実行せず読み込む。

    引数: path (Path) はコード、name (str) は識別名。
    返り値: object はモジュール。原板や研究結果は読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


I = module(Path(__file__).with_name("入口.py"), "収縮反転の合成対象")
CONFIG = {"時間足分": [3, 5], "残り時間下限分": 60, "確認遅延上限秒": 30, "運用": {"呼値pt": 5}}


def frame(index: int, size: int = 3, **changes) -> dict:
    """有限正帯幅を持つ確定足を作る。

    引数: index/size (int) は番号/足幅、changes (dict) は上書き列。
    返り値: dict は合成のOHLCと指標。
    """
    end = (index + 1) * size * 60
    close = changes.get("close", 1000.)
    return {"index": index, "minutes": size, "end": end, "confirm": end, "confirm_line": index * 10 + 1,
            "publish": True, "missing": 0, "open": 1000., "close": close, "high": max(1010., close),
            "low": min(990., close), "ema20": 1000., "atr": 20., "adx": 10., "bb_mean": 1000., "bb_sd": 20., **changes}


def higher(**changes) -> dict:
    """同場の準備済み15分買い方向を作る。

    引数: changes (dict) は上書き列。
    返り値: dict は上位の公開済み特徴。
    """
    return {"publish": True, "end": 0, "confirm": 0, "confirm_line": 0,
            "close": 1100., "ema20": 1050., "ema20_previous": 1000., **changes}


def mirror(value: dict) -> dict:
    """価格2000を軸に売買と高安を対称化する。

    引数: value (dict) は足。
    返り値: dict は正値中心を保つ鏡像。ATR・標準偏差・ADXは変えない。
    """
    row = deepcopy(value)
    for key in ("open", "close", "ema20", "ema20_previous", "bb_mean"):
        if key in value and value[key] is not None:
            row[key] = 2000 - value[key]
    if "high" in value and "low" in value:
        row["high"], row["low"] = 2000 - value["low"], 2000 - value["high"]
    return row


def seed(size: int = 3) -> list[dict]:
    """19本の幅0.08に続く20本目の幅0.04で収縮設定を作る。

    引数: size (int) は3分または5分。
    返り値: list[dict] は設定までの20足。
    """
    return [frame(n, size) for n in range(19)] + [frame(19, size, bb_sd=10.)]


def run(values: list[dict], uppers: list[dict] | None = None, cutoff: float = 50000,
        deadline: float = 60000) -> tuple[dict, dict]:
    """同じ時刻条件で収縮・突破・復帰を生成する。

    引数: values/uppers (list[dict]|None) は足、cutoff/deadline (float) は時計。
    返り値: tuple[dict,dict] は入口列と品質。
    """
    return I.generate(values, [higher()] if uppers is None else uppers, "合成場", cutoff, deadline, CONFIG)


def events(output: dict, family: str, extra: str = "なし") -> list[dict]:
    """足幅を問わず系統と補助に対応する発動を抽出する。

    引数: output (dict) は結果、family/extra (str) は系統/補助。
    返り値: list[dict] は対応する発動列。
    """
    return [r for values in output.values() for r in values if r["入口系統"] == family and r["補助"] == extra]


# ----------------------------------------
# 当足を含む20幅/6範囲、未突破1〜6、突破後1〜3の状態順を確認する。

class 収縮状態検証(unittest.TestCase):
    """状態の境界と最初の一回だけの消費を検査する。"""

    def test_帯幅は正の中心で正規化した四標準偏差(self) -> None:
        """帯幅式と無効値を直接確認する。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        self.assertEqual(I.bandwidth({"bb_mean": 1000., "bb_sd": 10.}), .04)
        for changes in ({"bb_sd": 0.}, {"bb_sd": -1.}, {"bb_sd": None}, {"bb_sd": float("nan")},
                        {"bb_sd": float("inf")}, {"bb_mean": 0.}, {"bb_mean": -1.}, {"bb_mean": None}):
            row = frame(0)
            row.update(changes)
            self.assertIsNone(I.bandwidth(row))

    def test_二十足目まで設定せず同足を突破にしない(self) -> None:
        """19本履歴からの20本目の範囲外終値を同足突破にしない。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        values = seed()[:19] + [frame(19, close=1015., bb_sd=15.)]
        output, quality = run(values)
        self.assertFalse(events(output, "突破追随"))
        self.assertEqual(quality["収縮設定登録"], 1)

    def test_等値最小と正規化幅を認める(self) -> None:
        """同率最小を認め、標準偏差だけで最小を選ばない。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        for mean, sd in ((1000., 10.), (1001., 10.005)):
            values = [frame(n, bb_sd=10.) for n in range(19)] + [frame(19, bb_mean=mean, bb_sd=sd),
                      frame(20, close=1015., bb_sd=15.)]
            output, _ = run(values)
            self.assertEqual(len(events(output, "突破追随")), 1)

    def test_固定六本は設定足自身を含む(self) -> None:
        """設定足の大きなヒゲを固定範囲から落とさない。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        values = seed()
        values[-1].update(high=1050., low=950.)
        values.append(frame(20, close=1020., bb_sd=15.))
        self.assertFalse(events(run(values)[0], "突破追随"))
        values.append(frame(21, close=1055., bb_sd=15.))
        hit = events(run(values)[0], "突破追随")[0]
        self.assertEqual(hit["収縮設定"]["固定高値"], 1050.)
        self.assertEqual(hit["収縮設定"]["固定安値"], 950.)

    def test_突破の一足目六足目を含み七足目は満了(self) -> None:
        """突破待機の最後の有効足と満了を分ける。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        for age in (1, 6, 7):
            tail = [frame(19 + j, bb_sd=15.) for j in range(1, age)]
            tail.append(frame(19 + age, close=1015., bb_sd=15.))
            output, quality = run(seed() + tail)
            self.assertEqual(len(events(output, "突破追随")), int(age <= 6))
            if age == 7:
                self.assertEqual(quality["未突破満了"], 1)

    def test_範囲境界等号は突破ではない(self) -> None:
        """終値の高安等号を待機として次のstrict突破を判定する。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        for close in (990., 1010.):
            values = seed() + [frame(20, close=close, bb_sd=15.)]
            self.assertFalse(events(run(values)[0], "突破追随"))
        output, _ = run(seed() + [frame(20, close=1010., bb_sd=15.), frame(21, close=1015., bb_sd=15.)])
        self.assertEqual([r["index"] for r in events(output, "突破追随")], [21])

    def test_範囲外でも帯幅等号縮小は登録しない(self) -> None:
        """非拡大の範囲外終値は失効し突破後復帰を作らない。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        for sd in (10., 9.):
            output, quality = run(seed() + [frame(20, close=1015., bb_sd=sd), frame(21, bb_sd=15.)])
            self.assertFalse(events(output, "突破追随"))
            self.assertFalse(events(output, "突破失敗反転"))
            self.assertEqual(quality["非拡大範囲外失効"], 1)

    def test_突破の同足反転と再追随をしない(self) -> None:
        """一突破につき追随と最初の内復帰を各一回だけ発動する。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        output, _ = run(seed() + [frame(20, close=1015., bb_sd=15.), frame(21, close=1020., bb_sd=15.),
                                  frame(22, bb_sd=15.), frame(23, bb_sd=15.)])
        self.assertEqual([r["index"] for r in events(output, "突破追随")], [20])
        self.assertEqual([r["index"] for r in events(output, "突破失敗反転")], [22])

    def test_復帰の一足目三足目を含み四足目は満了(self) -> None:
        """突破後の1〜3足だけstrict内復帰を採用する。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        for age in (1, 3, 4):
            values = seed() + [frame(20, close=1015., bb_sd=15.)]
            values += [frame(20 + j, close=1010., bb_sd=15.) for j in range(1, age)]
            values += [frame(20 + age, bb_sd=15.)]
            output, quality = run(values)
            self.assertEqual(len(events(output, "突破失敗反転")), int(age <= 3))
            if age == 4:
                self.assertEqual(quality["突破後満了"], 1)

    def test_突破側境界は待機し反対端等号は飛越失効(self) -> None:
        """上抜け後C==高を復帰にせずC<=安の後に遅れた復帰を拾わない。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        values = seed() + [frame(20, close=1015., bb_sd=15.), frame(21, close=1010., bb_sd=15.), frame(22, bb_sd=15.)]
        self.assertEqual([r["index"] for r in events(run(values)[0], "突破失敗反転")], [22])
        for close in (990., 985.):
            output, quality = run(seed() + [frame(20, close=1015., bb_sd=15.), frame(21, close=close, bb_sd=15.), frame(22, bb_sd=15.)])
            self.assertFalse(events(output, "突破失敗反転"))
            self.assertEqual(quality["反対端飛越失効"], 1)

    def test_最新の収縮へ未突破設定を置換(self) -> None:
        """旧設定の範囲外極値が落ちた最新設定の範囲を用いる。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        values = seed()
        values[14].update(high=1040., low=960.)
        values += [frame(20, bb_sd=8., high=1008., low=992.), frame(21, close=1015., bb_sd=15.)]
        hit = events(run(values)[0], "突破追随")[0]
        self.assertEqual((hit["収縮設定"]["index"], hit["収縮設定"]["固定高値"]), (20, 1010.))

    def test_突破中は新収縮を設定せず幅窓は更新(self) -> None:
        """突破後の新しい最小を旧設定に置き換えず復帰後の窓に残す。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        values = seed() + [frame(20, close=1015., bb_sd=15.),
                           frame(21, close=1015., high=1060., bb_sd=7.5),
                           frame(22, bb_sd=15.), frame(23, close=1070., bb_sd=20.)]
        output, quality = run(values)
        self.assertEqual([r["index"] for r in events(output, "突破追随")], [20])
        reversal = events(output, "突破失敗反転")[0]
        self.assertEqual(reversal["収縮設定"]["index"], 19)
        self.assertEqual(quality["収縮設定登録"], 1)

    def test_復帰足の新収縮登録は旧復帰の判定後(self) -> None:
        """復帰足のヒゲで旧範囲を置換して内復帰を消さない。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        values = seed() + [frame(20, close=1015., bb_sd=15.), frame(21, bb_sd=7., high=1060., low=940.)]
        output, quality = run(values)
        r = events(output, "突破失敗反転")[0]
        self.assertEqual(r["収縮設定"]["固定高値"], 1010.)
        self.assertEqual(quality["収縮設定登録"], 2)

    def test_ゼロ高安差を独自に禁止しない(self) -> None:
        """6足の同価格でもBB20の幅が正なら設定と突破を許す。

        引数: self (収縮状態検証) はテスト。
        返り値: None。
        """
        values = seed()
        for r in values[-6:]:
            r.update(high=1000., low=1000., close=1000.)
        output, _ = run(values + [frame(20, close=1005., bb_sd=15.)])
        self.assertEqual(len(events(output, "突破追随")), 1)


# ----------------------------------------
# 無効幅・連続性リセットと、準備/時間/方向補助による発動抑止を分離する。

class 準備補助検証(unittest.TestCase):
    """状態消費が補助や将来結果へ依存しないことを検査する。"""

    def test_無効帯幅は窓設定突破後を全リセット(self) -> None:
        """帯幅の未定義・非有限・非正と非正中心で復帰を継続しない。

        引数: self (準備補助検証) はテスト。
        返り値: None。
        """
        for changes in ({"bb_sd": None}, {"bb_sd": 0.}, {"bb_sd": -1.}, {"bb_sd": float("nan")},
                        {"bb_sd": float("inf")}, {"bb_mean": 0.}, {"bb_mean": -1.}):
            values = seed() + [frame(20, close=1015., bb_sd=15.), frame(21, **changes), frame(22, bb_sd=15.)]
            output, quality = run(values)
            self.assertFalse(events(output, "突破失敗反転"))
            self.assertEqual(quality["帯幅無効リセット"], 1)

    def test_欠枠非公開で全状態を切る(self) -> None:
        """既存の突破後状態を欠枠や未公開の後へ持ち越さない。

        引数: self (準備補助検証) はテスト。
        返り値: None。
        """
        for changes in ({"missing": 1}, {"publish": False}):
            values = seed() + [frame(20, close=1015., bb_sd=15.), frame(21, bb_sd=15., **changes), frame(22, bb_sd=15.)]
            self.assertFalse(events(run(values)[0], "突破失敗反転"))

    def test_指標不足は状態を切らず発動だけ抑止(self) -> None:
        """突破時の準備不足でも後の復帰を既存突破から判定する。

        引数: self (準備補助検証) はテスト。
        返り値: None。
        """
        for changes in ({"ema20": None}, {"atr": None}, {"atr": 0.}, {"adx": None}, {"adx": float("nan")}):
            values = seed() + [frame(20, close=1015., bb_sd=15., **changes), frame(21, bb_sd=15.)]
            output, quality = run(values)
            self.assertFalse(events(output, "突破追随"))
            self.assertEqual([r["index"] for r in events(output, "突破失敗反転")], [21])
            self.assertEqual(quality["拡大突破消費"], 1)

    def test_上位未準備でも状態消費し準備後の復帰を認める(self) -> None:
        """上位準備の有無で価格構造を登録し直さない。

        引数: self (準備補助検証) はテスト。
        返り値: None。
        """
        values = seed() + [frame(20, close=1015., bb_sd=15.), frame(21, bb_sd=15.)]
        later = higher(end=values[-1]["end"], confirm=values[-1]["confirm"], confirm_line=values[-1]["confirm_line"])
        output, _ = run(values, [higher(publish=False), later])
        self.assertFalse(events(output, "突破追随"))
        self.assertEqual(len(events(output, "突破失敗反転")), 1)

    def test_補助不成立の突破も反転状態を保持(self) -> None:
        """買突破の上位不一致を理由に、後の売り失敗反転を失わない。

        引数: self (準備補助検証) はテスト。
        返り値: None。
        """
        values = seed() + [frame(20, close=1015., bb_sd=15.), frame(21, bb_sd=15.), frame(22, bb_sd=15.)]
        output, quality = run(values, [mirror(higher())])
        self.assertEqual(len(events(output, "突破追随")), 1)
        self.assertFalse(events(output, "突破追随", "15分方向一致"))
        self.assertEqual(len(events(output, "突破失敗反転", "15分方向一致")), 1)
        self.assertEqual(quality["突破失敗消費"], 1)

    def test_時間不可でも消費し遅延発動を別記(self) -> None:
        """時刻で発動できなくても状態は一回進め、確認遅延は候補へ記録する。

        引数: self (準備補助検証) はテスト。
        返り値: None。
        """
        values = seed() + [frame(20, close=1015., bb_sd=15.), frame(21, bb_sd=15.)]
        output, quality = run(values, cutoff=values[-2]["confirm"])
        self.assertFalse(any(output.values()))
        self.assertEqual((quality["拡大突破消費"], quality["突破失敗消費"]), (1, 1))
        delayed = seed() + [frame(20, close=1015., bb_sd=15.)]
        delayed[-1]["confirm"] += 31
        output, quality = run(delayed)
        self.assertEqual(events(output, "突破追随")[0]["確認遅延秒"], 31)
        self.assertGreater(quality["確認遅延超過発動"], 0)

    def test_同時計未来上位を補助に利用しない(self) -> None:
        """要求より後の同時計上位原行で方向を変更しない。

        引数: self (準備補助検証) はテスト。
        返り値: None。
        """
        values = seed() + [frame(20, close=1015., bb_sd=15.)]
        row = values[-1]
        future = mirror(higher(end=row["end"], confirm=row["confirm"], confirm_line=row["confirm_line"] + 1))
        output, _ = run(values, [higher(), future])
        self.assertEqual(len(events(output, "突破追随", "15分方向一致")), 1)
        future["confirm_line"] = row["confirm_line"]
        output, _ = run(values, [higher(), future])
        self.assertFalse(events(output, "突破追随", "15分方向一致"))

    def test_鏡像と三分五分で状態番号が一致(self) -> None:
        """売買を対称化しても同じ年齢の突破と復帰になる。

        引数: self (準備補助検証) はテスト。
        返り値: None。
        """
        for size in (3, 5):
            values = seed(size) + [frame(20, size, close=1015., bb_sd=15.), frame(21, size, bb_sd=15.)]
            a = run(values)[0]
            b = run([mirror(r) for r in values], [mirror(higher())])[0]
            for family in I.FAMILIES:
                self.assertEqual([(r["index"], r["side"]) for r in events(a, family)],
                                 [(r["index"], -r["side"]) for r in events(b, family)])

    def test_未来ラベルで状態と消費を変えない(self) -> None:
        """未使用の将来結果列を付けても発動と消費は変わらない。

        引数: self (準備補助検証) はテスト。
        返り値: None。
        """
        values = seed() + [frame(20, close=1015., bb_sd=15.), frame(21, bb_sd=15.)]
        a, qa = run(values)
        for row in values:
            row.update(ラベル="順行先着", 将来損益=999999)
        b, qb = run(values)
        self.assertEqual({k: [r["イベントID"] for r in v] for k, v in a.items()},
                         {k: [r["イベントID"] for r in v] for k, v in b.items()})
        self.assertEqual(qa, qb)


class 実行側検証(unittest.TestCase):
    """実数値を呼ばず8案と実継承元の固定を確認する。"""

    def test_八案とX0だけを固定(self) -> None:
        """2足2系統2補助を保ち未指定の本数や出口を拒否する。

        引数: self (実行側検証) はテスト。
        返り値: None。条件JSONだけを読む。
        """
        sys.modules["入口"] = I
        driver = module(Path(__file__).with_name("検証.py"), "収縮driver案数合成")
        config = driver.W.read_json(driver.STUDY / "条件.json")
        self.assertEqual(len(driver.sources(config)), 8)
        bad = deepcopy(config)
        bad["状態本数"]["帯幅参照"] = 19
        with self.assertRaises(ValueError):
            driver.sources(bad)
        bad = deepcopy(config)
        bad["出口"] = [{"出口ID": "X1"}]
        with self.assertRaises(ValueError):
            driver.sources(bad)

    def test_actual十一継承と新合成を固定(self) -> None:
        """使う旧11を固定し未使用の00012実装を依存へ足さない。

        引数: self (実行側検証) はテスト。
        返り値: None。正式固定/入力は変更せず書込をmockにする。
        """
        sys.modules["入口"] = I
        driver = module(Path(__file__).with_name("検証.py"), "収縮driver固定合成")
        study = ROOT / "work/収縮反転/合成固定用の未作成先"
        self.assertFalse(study.exists())
        original_sha = driver.O.sha

        def synthetic_sha(path: Path) -> str:
            """架空試行内の計画等だけ仮SHAにし、実継承元のSHAは本物で検査する。

            引数: path (Path) は対象。
            返り値: str は合成または実SHA。
            """
            return "合成SHA" if path.is_relative_to(study) else original_sha(path)

        with patch.object(driver.O, "sha", side_effect=synthetic_sha), patch.object(driver.W, "write_json"):
            locked = driver.freeze(study)
        pins = locked["ファイルSHA256"]
        self.assertIn("scripts/収縮反転/合成検証.py", pins)
        self.assertIn("scripts/テクニカル循環/運用.py", pins)
        self.assertIn("study/00011_順行と反転のチャート構造と利益回収/固定.json", pins)
        self.assertNotIn("scripts/反転確認/入口.py", pins)
        self.assertNotIn("scripts/反転確認/運用.py", pins)


def run_tests() -> dict:
    """合成検証の明示合否と版をGit外へ保存する。

    引数: なし。実データの数値再生は行わない。
    返り値: dict は件数・失敗・エラー・指紋。
    """
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {"全件成功": result.wasSuccessful(), "検証件数": result.testsRun,
              "失敗": [{"検査": str(t), "内容": text} for t, text in result.failures],
              "エラー": [{"検査": str(t), "内容": text} for t, text in result.errors],
              "入口SHA256": hashlib.sha256(Path(__file__).with_name("入口.py").read_bytes()).hexdigest(),
              "合成SHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "範囲": "20/6当足含・6/3待機境界・同足不可・strict範囲・飛越・最新設定・全resetと発動抑止・補助独立。数値再生なし。",
              "実行記録": stream.getvalue()}
    target = ROOT / "work/収縮反転/合成検証.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(stream.getvalue())
    return report


if __name__ == "__main__":
    if not run_tests()["全件成功"]:
        raise SystemExit(1)
