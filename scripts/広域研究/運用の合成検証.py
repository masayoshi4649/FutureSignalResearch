"""一建玉運用の時点・会計・欠測を、実データを使わず合成検証する。"""

from __future__ import annotations

from decimal import Decimal
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import NamedTuple
import unittest


PATH = Path(__file__).with_name("運用検証.py")
SPEC = importlib.util.spec_from_file_location("運用合成対象", PATH)
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)
CONFIG = {"対象": "NK225", "数量": 1, "倍率": 10, "呼値pt": 5, "利確pt": 250,
          "保護逆行pt": 125, "片道手数料円": 11, "片道追加滑りpt": [0, 5, 10],
          "新規待機秒": 1, "新規有効秒": 30, "返済待機秒": 1, "正常板空白注意秒": 300,
          "同時両方向": "見送り", "単一建玉": True, "入口候補ID": "3分_開始幅失敗復帰_15_ADX環境"}
BOUNDS = (0.0, 1000.0, 800.0, 900.0)
SESSION = "2026-10-01_Day"


class Quote(NamedTuple):
    """実板と独立した合成正常気配。"""

    now: float
    line: int
    bid: float
    ask: float
    valid: bool = True


def signal(now: float = 10, line: int = 1, side: int = 1, suffix: str = "", late: float = 0) -> dict:
    """将来結果を必要としない入口を作る。

    引数: now (float) とline (int) は要求、side (int) は方向、suffix (str) はID末尾、late (float) は確認遅延。
    返り値: dict は合成入口。
    """
    return {"イベントID": f"合成_{now}_{line}_{side}_{suffix}", "場": SESSION,
            "要求時計秒": now, "要求原板行": line, "side": side,
            "方向": "買い" if side == 1 else "売り", "確認遅延秒": late}


def replay(quotes: list[Quote], signals: list[dict] | None = None) -> tuple:
    """固定した合成時刻で一場を再生する。

    引数: quotes (list[Quote]) は気配、signals (list[dict] | None) は入口。
    返り値: tuple は運用状態と集計。
    """
    return ENGINE.replay_session(quotes, [signal()] if signals is None else signals,
                                 SESSION, CONFIG["入口候補ID"], CONFIG, BOUNDS)


# ----------------------------------------
# 入口と注文・約定の因果順。

class 運用合成検証(unittest.TestCase):
    """固定された売買仕様を独立した小経路で確認する。"""

    def test_買い利確は一秒待ち戻り価格(self) -> None:
        """利確観測後の同時計は約定せず、戻った気配で返済する。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(11, 2, 1000, 1005), Quote(12, 3, 1255, 1260),
                           Quote(12, 4, 1260, 1265), Quote(13, 5, 1240, 1245)])
        trade = state.trades[0]
        self.assertEqual((trade["新規価格"], trade["返済価格"], trade["返済原板行"]), (1005, 1240, 5))
        self.assertEqual(trade["返済理由"], "利確")
        self.assertEqual(trade["基準純損益円"], 2328)
        self.assertEqual((trade["観測最大順行pt"], trade["観測最大逆行pt"]), (255, 5))

    def test_売り利確はAsk返済(self) -> None:
        """売りはBid新規・Ask到達・Ask返済を使う。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(11, 2, 1000, 1005), Quote(12, 3, 745, 750), Quote(13, 4, 755, 760)], [signal(side=-1)])
        self.assertEqual(state.trades[0]["基準純損益円"], 2378)
        self.assertEqual([fill["type"] for fill in state.fills], ["ShortN", "ShortR"])

    def test_保護飛越えを閾値価格で約定しない(self) -> None:
        """保護を飛び越しても次の正常気配まで待つ。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(11, 2, 1000, 1005), Quote(12, 3, 880, 885), Quote(13, 4, 850, 855)])
        self.assertEqual((state.trades[0]["保護価格"], state.trades[0]["返済価格"]), (880, 850))
        self.assertEqual(state.trades[0]["基準純損益円"], -1572)

    def test_売り保護の方向と等号(self) -> None:
        """売りの保護はAskが新規より125pt高い時に発動する。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(11, 2, 1000, 1005), Quote(12, 3, 1120, 1125), Quote(13, 4, 1130, 1135)], [signal(side=-1)])
        self.assertEqual((state.trades[0]["返済理由"], state.trades[0]["返済価格"]), ("保護", 1135))

    def test_新規同時計不約定と三十秒端点(self) -> None:
        """新規は同時計で付かず、要求30秒後の等号を許す。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(10, 2, 1000, 1005), Quote(40, 3, 1010, 1015)])
        self.assertEqual((state.fills[0]["price_clock"], state.fills[0]["price"]), (40, 1015))
        expired, _ = replay([Quote(40.001, 2, 1010, 1015)])
        self.assertEqual(expired.fills, [])

    def test_注文と建玉による新規抑止(self) -> None:
        """新規待機中と保有中は別の理由で重複入口を抑止する。

        引数: なし。
        返り値: None。
        """
        state, result = replay([Quote(11, 5, 1000, 1005)], [signal(), signal(10.5, 3), signal(12, 6)])
        self.assertEqual((result["注文待機中抑止数"], result["建玉中抑止数"], len(state.fills)), (1, 1, 1))

    def test_両方向同原行だけ見送る(self) -> None:
        """同じ要求時計・原行の両方向だけ全見送りする。

        引数: なし。
        返り値: None。
        """
        both, result = replay([Quote(11, 4, 1000, 1005)], [signal(), signal(side=-1)])
        self.assertEqual((len(both.fills), result["両方向見送り数"]), (0, 2))
        ordered, _ = replay([Quote(11, 4, 1000, 1005)], [signal(), signal(line=2, side=-1)])
        self.assertEqual(len(ordered.fills), 1)
        self.assertEqual(ordered.signals[1]["取扱"], "注文待機中抑止")

    def test_期限と到達同時は期限優先(self) -> None:
        """期限で先に要求し、期限と同時計の閾値発動に置き換えない。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(11, 2, 1000, 1005), Quote(900, 3, 1255, 1260), Quote(901, 4, 1240, 1245)])
        trade = state.trades[0]
        self.assertEqual((trade["返済理由"], trade["返済要求時計秒"], trade["返済時計秒"]), ("期限", 900, 901))

    def test_期限前の利確要求は維持(self) -> None:
        """期限より早い返済要求を価格反転や期限で取り消さない。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(11, 2, 1000, 1005), Quote(899.5, 3, 1255, 1260), Quote(900.5, 4, 800, 805)])
        self.assertEqual((state.trades[0]["返済理由"], state.trades[0]["返済価格"]), ("利確", 800))

    def test_終端未満だけ返済する(self) -> None:
        """終端ちょうどの正常板は返済に利用しない。

        引数: なし。
        返り値: None。
        """
        state, result = replay([Quote(11, 2, 1000, 1005), Quote(1000, 3, 1100, 1105)])
        self.assertEqual((len(state.trades), result["終了建玉"], result["確定対象純損益円"]), (0, 1, None))

    def test_新規停止の等号不可と確認遅延(self) -> None:
        """cutoff等号を禁止し、30秒超の足確認を新規へ使わない。

        引数: なし。
        返り値: None。
        """
        stopped, _ = replay([Quote(800, 2, 1000, 1005)], [signal(799)])
        late, _ = replay([Quote(11, 2, 1000, 1005)], [signal(late=30.001)])
        equal, _ = replay([Quote(11, 2, 1000, 1005)], [signal(late=30)])
        self.assertEqual((len(stopped.fills), len(late.fills), len(equal.fills)), (0, 0, 1))

    def test_新規スプレッドだけで保護発動(self) -> None:
        """新規直後の返済気配を保護判定に含める。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(11, 2, 875, 1000), Quote(12, 3, 870, 1000)])
        self.assertEqual((state.trades[0]["返済理由"], state.trades[0]["返済要求時計秒"]), ("保護", 11))

    def test_返済同原行で次の要求は可能(self) -> None:
        """返済約定後の同原行入口を受け、新規はさらに一秒待つ。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(11, 2, 1000, 1005), Quote(12, 3, 1255, 1260), Quote(13, 4, 1250, 1255),
                           Quote(14, 5, 1250, 1255)], [signal(), signal(13, 4, -1)])
        self.assertEqual([fill["type"] for fill in state.fills], ["LongN", "LongR", "ShortN"])
        self.assertEqual(state.fills[-1]["price_clock"], 14)

    # ----------------------------------------
    # 観測不明と会計・費用感度。

    def test_空白でも再生を続け注意付き損益(self) -> None:
        """300秒超空白を打切りラベルにせず、観測損益へ注意を付ける。

        引数: なし。
        返り値: None。
        """
        state, result = replay([Quote(11, 2, 1000, 1005), Quote(500, 3, 1255, 1260), Quote(501, 4, 1240, 1245), Quote(901, 5, 1240, 1245)])
        self.assertEqual(len(state.trades), 1)
        self.assertTrue(state.trades[0]["観測経路注意"])
        self.assertEqual(result["観測完結取引純損益円"], 2328)
        self.assertIsNone(result["確定対象純損益円"])

    def test_三百秒ちょうどは空白フラグなし(self) -> None:
        """保有中の正常板間隔300秒は超過に含めない。

        引数: なし。
        返り値: None。
        """
        state, _ = replay([Quote(11, 2, 1000, 1005), Quote(311, 3, 1255, 1260), Quote(312, 4, 1240, 1245)])
        self.assertFalse(state.trades[0]["保有経路空白"])

    def test_空白で未約定失効した要求も品質に残る(self) -> None:
        """空白中に失効した新規を、約定なしとして消さず品質へ残す。

        引数: なし。
        返り値: None。
        """
        state, result = replay([Quote(9, 1, 1000, 1005), Quote(500, 3, 1000, 1005), Quote(901, 4, 1000, 1005)])
        self.assertEqual(len(state.fills), 0)
        self.assertEqual(result["新規待機中空白区間数"], 1)
        self.assertIsNone(result["確定対象純損益円"])

    def test_最初の正常板までの待機空白も残る(self) -> None:
        """場頭に正常板が無い間の要求・失効も経路注意として残す。

        引数: なし。
        返り値: None。
        """
        _, result = replay([Quote(400, 3, 1000, 1005), Quote(901, 4, 1000, 1005)])
        self.assertEqual(result["新規待機中空白区間数"], 1)
        self.assertIsNone(result["確定対象純損益円"])

    def test_EOF未解消に返済を捏造しない(self) -> None:
        """EOFで建玉を残し、新規手数料と未解消を保持する。

        引数: なし。
        返り値: None。
        """
        state, result = replay([Quote(11, 2, 1000, 1005), Quote(12, 3, 1000, 1005)])
        self.assertEqual((len(state.trades), result["観測現金増減円"], result["終了建玉"]), (0, -11, 1))
        self.assertTrue(result["EOF期限未達"])
        self.assertIsNone(result["確定対象純損益円"])
        result["期間"] = "学習"
        costs = ENGINE.sensitivity([result], CONFIG)
        self.assertEqual([row["観測現金増減円"] for row in costs], [-11, -11, -11])

    def test_費用だけを控除して元約定を変えない(self) -> None:
        """追加滑りを完結往復へ100円・200円控除する。

        引数: なし。
        返り値: None。
        """
        state, result = replay([Quote(11, 2, 1000, 1005), Quote(12, 3, 1255, 1260), Quote(13, 4, 1240, 1245)])
        original = json.dumps(state.fills, ensure_ascii=False)
        result["期間"] = "学習"
        rows = ENGINE.sensitivity([result], CONFIG)
        self.assertEqual([row["観測完結取引純損益円"] for row in rows], [2328, 2228, 2128])
        self.assertEqual(json.dumps(state.fills, ensure_ascii=False), original)

    def test_独立Decimal台帳会計(self) -> None:
        """約定種別と原価格からDecimalで会計を独立に算出する。

        引数: なし。
        返り値: None。
        """
        state, result = replay([Quote(11, 2, 1000, 1005), Quote(12, 3, 1255, 1260), Quote(13, 4, 1240, 1245)])
        opened, cash = {}, Decimal(0)
        for fill in state.fills:
            price, fee = Decimal(str(fill["price"])), Decimal(str(fill["fee_yen"]))
            cash -= fee
            if fill["type"].endswith("N"):
                opened[fill["position_id"]] = (price, 1 if fill["type"].startswith("Long") else -1)
            else:
                entry, side = opened.pop(fill["position_id"])
                cash += (price - entry) * side * Decimal(10)
        self.assertFalse(opened)
        self.assertEqual(cash, Decimal(str(result["観測現金増減円"])))

    def test_未来ラベル列を書き換えても経路不変(self) -> None:
        """入口の将来ラベル・約定・最大順逆行を参照しない。

        引数: なし。
        返り値: None。
        """
        quotes = [Quote(11, 2, 1000, 1005), Quote(12, 3, 1255, 1260), Quote(13, 4, 1240, 1245)]
        base, _ = replay(quotes)
        row = {**signal(), "ラベル": "観測不足", "新規価格": -999, "判定時計秒": 1e20, "最大順行pt": 1e30}
        changed, _ = replay(quotes, [row])
        self.assertEqual(base.fills, changed.fills)
        self.assertEqual(base.trades, changed.trades)

    def test_不正気配と後退を約定へ使わない(self) -> None:
        """不正板を除外し、後退行を原順から削除する。

        引数: なし。
        返り値: None。
        """
        state, result = replay([Quote(11, 2, 1000, 1005), Quote(13, 3, 1000, 1005),
                               Quote(12, 4, 1255, 1260), Quote(14, 5, 1255, 1260, False)])
        self.assertEqual(result["時計後退除外数"], 1)
        self.assertEqual(len(state.trades), 0)

    def test_同時計同状態の省略で経路同値(self) -> None:
        """同時計の完全同値行追加が約定を変えないことを確認する。

        引数: なし。
        返り値: None。
        """
        quotes = [Quote(11, 2, 1000, 1005), Quote(12, 4, 1255, 1260), Quote(13, 6, 1240, 1245)]
        base, _ = replay(quotes)
        repeated, _ = replay([quotes[0], Quote(11, 3, 1000, 1005), quotes[1], Quote(12, 5, 1255, 1260), quotes[2]])
        self.assertEqual(base.fills, repeated.fills)

    def test_注意場を含む全体は確定額なし(self) -> None:
        """部分集計を全体の確定収益に置き換えない。

        引数: なし。
        返り値: None。
        """
        _, row = replay([Quote(11, 2, 1000, 1005)])
        row["期間"] = "学習"
        aggregate = ENGINE.aggregate(ENGINE.sensitivity([row], CONFIG))
        self.assertTrue(all(value["確定対象純損益円"] is None for value in aggregate))
        self.assertTrue(all(value["注意なし場数"] == 0 for value in aggregate))
        json.dumps(aggregate, ensure_ascii=False, allow_nan=False)

    def test_時刻仕様と条件を固定(self) -> None:
        """日中夜間の期限と条件逸脱の拒否を確認する。

        引数: なし。
        返り値: None。
        """
        day = ENGINE.session_times("2026-10-01_Day")
        night = ENGINE.session_times("2026-10-01_Night")
        self.assertIn("15:35", ENGINE.iso(day[3]))
        self.assertIn("2026-10-02T05:50", ENGINE.iso(night[3]))
        ENGINE.validate_config(CONFIG)
        with self.assertRaises(ValueError):
            ENGINE.validate_config({**CONFIG, "利確pt": 300})

    def test_gzip再生成は展開内容で識別(self) -> None:
        """圧縮時刻だけが違う入口中間物を同一内容として識別する。

        引数: なし。
        返り値: None。
        """
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / "一.gz", Path(directory) / "二.gz"]
            for number, path in enumerate(paths, 1):
                with path.open("wb") as raw:
                    with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=number) as stream:
                        stream.write('{"同じ内容": true}\n'.encode("utf-8"))
            self.assertNotEqual(ENGINE.sha(paths[0]), ENGINE.sha(paths[1]))
            self.assertEqual(ENGINE.expanded_sha(paths[0]), ENGINE.expanded_sha(paths[1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
