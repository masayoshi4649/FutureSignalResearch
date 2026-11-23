"""固定突破指値と費用後起動を人工入力だけで検査する。"""

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Iterator
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
WORK = ROOT / "work/突破指値"
SESSION = "人工突破指値場"
BOUNDS = (0., 200., 180., 190.)


def normalized(path: object) -> str:
    """実ファイルへ触れず絶対比較表記を作る。

    引数: path(object)はパス又は記述子。
    返り値: strは正規表記。非パスは空文字。
    """
    try:
        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError):
        return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """実原板・cache・実圧縮明細へのstat/openを遮断する。

    引数: なし。
    返り値: Iterator[None]は人工一時先とコードだけを許可する範囲。
    """
    raw, work = normalized(ROOT.parent / "JP_OSE_Data"), normalized(ROOT / "work")
    old_open, old_path_open, old_stat = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """市場資料又は実中間明細への接近を拒否する。

        引数: path(object)は対象。
        返り値: None。人工一時ディレクトリ内だけ圧縮を許可する。
        """
        name = normalized(path)
        inside = name.startswith(work + os.sep)
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("突破指値34合成_")
        if name == raw or name.startswith(raw + os.sep) or inside and (name.endswith(".npz") or not artificial and name.endswith((".jsonl.gz", ".trades.jsonl"))):
            raise AssertionError("合成から実原板/cache/明細へ触れない:" + str(path))

    def opened(path: object, *args: object, **kwargs: object) -> Any:
        """通常openへ市場遮断を適用する。

        引数: path(object)は対象、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
        """
        check(path)
        return old_open(path, *args, **kwargs)

    def path_opened(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.openへ市場遮断を適用する。

        引数: path(Path)は対象、args/kwargs(object)は元引数。
        返り値: Anyは許可されたファイル。
        """
        check(path)
        return old_path_open(path, *args, **kwargs)

    def stated(path: Path, *args: object, **kwargs: object) -> Any:
        """Path.statへ市場遮断を適用する。

        引数: path(Path)は対象、args/kwargs(object)は元引数。
        返り値: Anyは許可されたメタデータ。
        """
        check(path)
        return old_stat(path, *args, **kwargs)

    with patch.object(builtins, "open", opened), patch.object(Path, "open", path_opened), patch.object(Path, "stat", stated):
        yield


def load(path: Path, name: str) -> Any:
    """市場遮断下でPython定義だけを読み込む。

    引数: path(Path)はコード、name(str)は識別。
    返り値: Anyは定義。市場CLIは起動しない。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
        return value


def sha(path: Path) -> str:
    """コード・条件の現在SHAを得る。

    引数: path(Path)は小型の出典。
    返り値: strはSHA256。実市場明細は対象外。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


O = load(HERE / "運用.py", "突破指値34合成の運用")
I = load(HERE / "入口.py", "突破指値34合成の入口")
CONFIG = json.loads((ROOT / "study/00031_CCI持続と上位BB幅/条件.json").read_text(encoding="utf-8"))["運用"]


def signal(side: int = 1, policy: str = "E1", now: float = 10., line: int = 10, index: int = 21) -> dict:
    """人工の旧高安を根拠とする同時点信号を作る。

    引数: side(int)は方向、policy(str)はE0/E1、now/line(float/int)は登録key、index(int)は番号。
    返り値: dictは13列と、E1だけの指値2列。
    """
    result = {"場": SESSION, "イベントID": f"人工{index}_{policy}", "入口ID": "3分_" + policy,
        "役割": "順行", "side": side, "方向": "買い" if side == 1 else "売り", "要求時計秒": now,
        "要求原板行": line, "確認遅延秒": 0., "low": 990., "high": 1010., "atr": 25., "bb_mean": None}
    if policy == "E1":
        result.update(新規指値価格=1000., 指値根拠={"旧C0イベントID": f"人工{index}_C0", "登録足番号": index,
            "公開時計秒": now, "公開原板行": line, "前20足番号": list(range(index - 20, index)),
            "前20最高H": 1000. if side == 1 else 1010., "前20最安L": 990. if side == 1 else 1000., "実side": side})
    return result


def quote(now: float, line: int, bid: float, ask: float, valid: bool = True) -> SimpleNamespace:
    """原行順を持つ人工BBOを作る。

    引数: now/line(float/int)はkey、bid/ask(float)は価格、valid(bool)は正常性。
    返り値: SimpleNamespaceは市場ファイルに依存しない観測。
    """
    return SimpleNamespace(now=now, line=line, bid=bid, ask=ask, valid=valid)


def simulate(events: list[Any], sources: list[dict] | None = None, policy: str = "E1",
             frames: list[dict] | None = None, bounds: tuple = BOUNDS) -> tuple[Any, dict]:
    """新運用を人工入力だけで再生する。

    引数: events(list[Any])は人工気配、sources(list[dict]|None)は信号、policy(str)はE0/E1、frames(list[dict]|None)は足、bounds(tuple)は人工時計。
    返り値: tuple[Any,dict]は状態/場別会計。
    """
    return O.replay(events, sources or [signal(policy=policy)], frames or [], SESSION, "3分_" + policy + "_XF",
        deepcopy(CONFIG), {"出口ID": "XF"}, "順行", bounds)


def entries(state: Any) -> list[dict]:
    """人工状態から新規fillだけを取り出す。

    引数: state(Any)は人工再生状態。
    返り値: list[dict]はLongN/ShortN。
    """
    return [row for row in state.fills if row["type"].endswith("N")]


class OperationTests(unittest.TestCase):
    """指値の時計/価格境界と固定XF継承を検査する。"""

    def test_limit_equality_and_better_quote_mirror(self) -> None:
        """境界等号と有利側の実在気配だけを買売鏡像で使う。

        引数: なし。
        返り値: None。指値へ価格を割り当てない。
        """
        for side in (1, -1):
            for improvement in (0., 5.):
                price = 1000. - side * improvement
                bid, ask = (price - 5., price) if side == 1 else (price, price + 5.)
                state, _ = simulate([quote(11., 11, bid, ask)], [signal(side)])
                self.assertEqual(entries(state)[0]["price"], price)
                self.assertEqual(entries(state)[0]["source_line"], 11)

    def test_effective_key_and_first_same_second_line(self) -> None:
        """登録前と+1秒未満を使わず、同秒の最初の成立原行で約定する。

        引数: なし。
        返り値: None。成立後の再待機や良い後行の取り直しはしない。
        """
        rows = [quote(10., 9, 990., 995.), quote(10., 10, 990., 995.), quote(10., 11, 990., 995.),
            quote(10.999, 12, 990., 995.), quote(11., 13, 1000., 1005.), quote(11., 14, 995., 1000.), quote(11., 15, 990., 995.)]
        state, _ = simulate(rows)
        self.assertEqual([(r["price_clock"], r["source_line"], r["price"]) for r in entries(state)], [(11., 14, 1000.)])

    def test_ttl_thirty_inclusive_and_over_expiry(self) -> None:
        """要求から30秒の等号を含み、超過時は成立気配より先に取消す。

        引数: なし。
        返り値: None。有効化時刻を起点へずらさない。
        """
        for time, count in ((40., 1), (40.000001, 0)):
            state, _ = simulate([quote(11., 11, 1000., 1005.), quote(time, 12, 995., 1000.)])
            self.assertEqual(len(entries(state)), count)
            if not count:
                self.assertEqual(state.orders[0]["状態"], "新規停止または30秒失効")

    def test_cutoff_equal_before_price_and_force(self) -> None:
        """停止等号・期限を指値成立より先に処理する。

        引数: なし。
        返り値: None。停止後の新規は発生しない。
        """
        for bounds in ((0., 200., 40., 190.), (0., 200., 180., 40.)):
            state, _ = simulate([quote(40., 12, 995., 1000.)], bounds=bounds)
            self.assertEqual(entries(state), [])

    def test_same_side_touch_and_ohlc_do_not_fill(self) -> None:
        """買bid/売askや足高安のタッチを新規約定へ使わない。

        引数: なし。
        返り値: None。対当側BBOが指値内となるまで未成立。
        """
        frame = {"publish": True, "confirm": 20., "confirm_line": 20, "end": 19., "low": 900., "high": 1100., "close": 1000.}
        for side in (1, -1):
            bid, ask = (1000., 1005.) if side == 1 else (995., 1000.)
            state, _ = simulate([quote(11., 11, bid, ask)], [signal(side)], frames=[frame])
            self.assertEqual(entries(state), [])

    def test_invalid_bbo_flag_not_used(self) -> None:
        """不正常フラグの成立気配を使わず、後の正常原行だけ使う。

        引数: なし。
        返り値: None。
        """
        state, _ = simulate([quote(11., 11, 990., 995., False), quote(12., 12, 995., 1000.)])
        self.assertEqual(entries(state)[0]["source_line"], 12)

    def test_waiting_signal_consumed_without_amendment(self) -> None:
        """待機中の同方向/反対信号を消費し、指値とTTLを更新しない。

        引数: なし。
        返り値: None。満了後に抑止信号を再利用しない。
        """
        for side in (1, -1):
            first, later = signal(), signal(side, now=20., line=20, index=22)
            later["新規指値価格"] = 1100.
            state, _ = simulate([quote(11., 11, 1000., 1005.), quote(41., 41, 995., 1000.)], [first, later])
            self.assertEqual(entries(state), [])
            self.assertEqual([r["取扱"] for r in state.signals], ["新規停止または30秒失効", "注文待機中抑止"])
            self.assertEqual(len(state.orders), 1)
            self.assertEqual(state.orders[0]["新規指値価格"], 1000.)
            self.assertEqual(state.orders[0]["要求時計秒"], 10.)

    def test_wide_spread_entry_quote_can_request_hard(self) -> None:
        """指値成立と同quoteの逆側気配で保護初着を判定し後続で返済する。

        引数: なし。
        返り値: None。新規同quoteの大幅逆行を無視しない。
        """
        state, _ = simulate([quote(11., 11, 800., 1000.), quote(12., 12, 790., 800.)])
        trade = state.trades[0]
        self.assertEqual((trade["新規価格"], trade["返済要求時計秒"], trade["返済時計秒"], trade["返済価格"]), (1000., 11., 12., 790.))
        self.assertEqual(trade["返済理由"], "保護")
        self.assertFalse(trade["追尾起動"])

    def test_cost_boundary_current_floor_and_pending_are_inherited(self) -> None:
        """12.2等号は不起動、15現在益で起動後に床を維持する。

        引数: なし。
        返り値: None。起動後の返済待機中は線を凍結する。
        """
        state = O.指値費用起動状態(SESSION, "3分_E1_XF", deepcopy(CONFIG), {"出口ID": "XF"}, "順行", [signal()], BOUNDS)
        state.signal_group([signal()])
        state.quote(11., 11, 995., 1000.)
        state.position["mfe"] = 30.
        state.quote(12., 12, 1012.2, 1015.)
        self.assertFalse(state.position["armed"])
        state.quote(13., 13, 1015., 1020.)
        self.assertTrue(state.position["armed"])
        self.assertEqual(state.position["cost_arm"]["控除後含み益円"], 28.)
        stop = state.position["trail_stop"]
        self.assertGreaterEqual(stop, 1000.)
        state.quote(14., 14, 1000., 1005.)
        self.assertIsNotNone(state.pending)
        state.quote(14.5, 15, 1030., 1035.)
        self.assertEqual(state.position["trail_stop"], stop)
        state.quote(15., 16, 995., 1000.)
        self.assertEqual(state.trades[0]["返済価格"], 995.)

    def test_fixed_metadata_in_orders_trade_and_initial_log(self) -> None:
        """登録出典を注文・初期log・返済tradeへ残し、外部変更を遮断する。

        引数: なし。
        返り値: None。取消注文も元出典を保持する。
        """
        source = signal()
        state = O.指値費用起動状態(SESSION, "3分_E1_XF", deepcopy(CONFIG), {"出口ID": "XF"}, "順行", [source], BOUNDS)
        state.signal_group([source])
        source["新規指値価格"] = 1100.
        source["指値根拠"]["前20足番号"][0] = -999
        state.quote(11., 11, 995., 1000.)
        state.quote(199., 199, 995., 1000.)
        for row in (state.orders[0], state.trades[0], state.normal_log[0]):
            self.assertEqual(row["新規指値価格"], 1000.)
            self.assertEqual(row["指値根拠"]["前20足番号"][0], 1)
        state.orders[0]["指値根拠"]["前20足番号"][0] = -111
        self.assertEqual(state.trades[0]["指値根拠"]["前20足番号"][0], 1)

    def test_e0_is_literal_old33_whole_ledger_and_trace(self) -> None:
        """E0を固定33へ直呼出しし全属性と動作順を一致させる。

        引数: なし。
        返り値: None。新指値字段をE0へ加えない。
        """
        source = signal(policy="E0")
        rows = [quote(11., 11, 995., 1000.), quote(12., 12, 1020., 1025.), quote(13., 13, 1000., 1005.), quote(14., 14, 995., 1000.), quote(199., 199, 995., 1000.)]
        a, qa = simulate(rows, [deepcopy(source)], "E0")
        b, qb = O.BASE.replay(rows, [deepcopy(source)], [], SESSION, "3分_E0_XF", deepcopy(CONFIG), {"出口ID": "XF"}, "順行", BOUNDS)
        self.assertEqual(qa, qb)
        for name in ("fills", "orders", "trades", "signals", "normal_log"):
            self.assertEqual(getattr(a, name), getattr(b, name))
            self.assertTrue(all("新規指値価格" not in row and "指値根拠" not in row for row in getattr(a, name)))

    def test_bad_limit_and_wrong_policy_rejected(self) -> None:
        """不正指値と予定外候補/出口を静かに補正しない。

        引数: なし。
        返り値: None。有限正値・呼値・根拠が必要。
        """
        for price in (None, float("nan"), float("inf"), 0., 1001., True):
            source = signal(); source["新規指値価格"] = price
            with self.assertRaises(ValueError):
                simulate([], [source])
        with self.assertRaises(ValueError):
            O.replay([], [], [], SESSION, "3分_E0_XF", CONFIG, {"出口ID": "X0"}, "順行", BOUNDS)

    def test_independent_full_xf_trace_with_limit_source(self) -> None:
        """独立XF別走査と指値出典込みの全logを買売二案で一致させる。

        引数: なし。
        返り値: None。主運用を独立側からimportさせない。
        """
        independent = load(HERE / "追尾独立確認.py", "突破指値34合成の独立追尾")
        outer = self

        class Audit:
            """人工一場の独立照合を厳密unittestへ渡す。"""

            def check(self, name: str, actual: object, expected: object) -> None:
                """独立側の保存値比較を検査失敗へ接続する。

                引数: name(str)は項目、actual/expected(object)は比較値。
                返り値: None。不一致を黙認しない。
                """
                outer.assertEqual(actual, expected, name)

        base = [quote(11., 11, 1000., 1005.), quote(12., 12, 995., 1000.), quote(13., 13, 1020., 1025.),
            quote(14., 14, 1000., 1005.), quote(14.5, 15, 1030., 1035.), quote(15., 16, 995., 1000.)]
        for side in (1, -1):
            rows = base if side == 1 else [quote(q.now, q.line, 2000. - q.ask, 2000. - q.bid) for q in base]
            for policy in ("E0", "E1"):
                source = signal(side, policy)
                state, info = simulate(rows, [source], policy)
                info["期間"] = "学習"
                detail = {"候補ID": "3分_" + policy + "_XF", "場": SESSION, "品質": info,
                    "約定": state.fills, "注文": state.orders, "取引": state.trades}
                logs, _ = independent.replay(detail, [vars(q) for q in rows], {source["イベントID"]: source},
                    Audit(), (BOUNDS[0], BOUNDS[1], BOUNDS[3]), deepcopy(CONFIG))
                self.assertEqual(logs, [{"期間": "学習", **row} for row in state.normal_log])


class EntryTests(unittest.TestCase):
    """価格窓登録と仮新規の原順/鏡像を人工で検査する。"""

    def test_registration_whitelist_and_same_c0_snapshot(self) -> None:
        """全C0登録を二案へ同時計で渡し、未来値を信号から排除する。

        引数: なし。
        返り値: None。指値は旧20窓で固定する。
        """
        old = signal(policy="E0")
        old.update(イベントID="人工21_C0", 入口ID="3分_C0", ラベル="未来先着", 最大順行pt=9999.)
        raw = {**old, "発動ID": "人工21", "index": 21, "足終了時計秒": 10., "前20足番号": list(range(1, 21)),
            "直前最高H": 1000., "直前最安L": 990., "close": 1010., "戦略判定": {"C0": {"採用": True}}}
        result = I.select({"quality": {"全Q発動記録": [raw]}, "signals": {"3分_C0": [old]}})
        a, b = result["signals"]["3分_E0"][0], result["signals"]["3分_E1"][0]
        self.assertEqual(set(a), set(I.SIGNAL_FIELDS["E0"]))
        self.assertEqual(set(b), set(I.SIGNAL_FIELDS["E1"]))
        self.assertEqual(b["新規指値価格"], 1000.)
        self.assertEqual((a["要求時計秒"], a["要求原板行"]), (b["要求時計秒"], b["要求原板行"]))
        self.assertNotIn("ラベル", b)
        b["指値根拠"]["前20足番号"][0] = -99
        self.assertEqual(result["registrations"][0]["前20足番号"][0], 1)

    def test_entry_first_bbo_ttl_stop_and_mirror(self) -> None:
        """同秒原順・30秒等号・停止等号を仮新規でも一致させる。

        引数: なし。
        返り値: None。純E1仮約定はE0仮約定の部分集合。
        """
        for side in (1, -1):
            rows = [quote(10.9, 11, 995., 1000.), quote(11., 12, 1000., 1005.), quote(40., 13, 995., 1000.)]
            if side == -1:
                rows = [quote(r.now, r.line, 2000. - r.ask, 2000. - r.bid) for r in rows]
            path = I.入口経路(rows)
            source = signal(side)
            self.assertEqual(path.entry_index(source, 180., "E0"), 1)
            self.assertEqual(path.entry_index(source, 180., "E1"), 2)
            self.assertIsNone(path.entry_index(source, 40., "E1"))
            late = I.入口経路([quote(40.001, 14, 995., 1000.)])
            self.assertIsNone(late.entry_index(source, 180., "E1"))

    def test_same_entry_quote_adverse_and_better_limit_label(self) -> None:
        """仮新規と同quoteの125逆行を含め、指値値段を先着へ流用しない。

        引数: なし。
        返り値: None。人工値だけで125/250を評価する。
        """
        path = I.入口経路([quote(11., 11, 800., 995.), quote(12., 12, 1250., 1255.)])
        item = path.evaluate_signal(signal(), 180., 150., "E1")
        self.assertEqual((item["新規価格"], item["ラベル"], item["判定原板行"]), (995., "逆行先着", 11))

    def test_force_equal_is_not_new_entry_even_with_later_cutoff(self) -> None:
        """停止を人工的に後へ置いてもforce等号の新規を許可しない。

        引数: なし。
        返り値: None。九数値を欠測として保持する。
        """
        path = I.入口経路([quote(20., 20, 995., 1000.)])
        for policy in ("E0", "E1"):
            self.assertIsNone(path.entry_index(signal(policy=policy), 100., policy, 20.))
            result = path.evaluate_signal(signal(policy=policy), 100., 20., policy)
            self.assertEqual(result["ラベル"], "未約定")
            self.assertTrue(all(result[key] is None for key in ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")))

    def test_independent_registration_and_direct_labels(self) -> None:
        """別原列走査と登録/全ラベル字段を人工経路で一致させる。

        引数: なし。
        返り値: None。主区間木と独立全走査の共通実装を避ける。
        """
        independent = load(HERE / "状態独立確認.py", "突破指値34合成の独立入口")
        old = signal(policy="E0")
        old.update(イベントID="人工21_C0", 入口ID="3分_C0")
        raw = {**old, "発動ID": "人工21", "index": 21, "足終了時計秒": 10., "前20足番号": list(range(1, 21)),
            "直前最高H": 1000., "直前最安L": 990., "close": 1010., "戦略判定": {"C0": {"採用": True}}}
        block = {"quality": {"全Q発動記録": [raw]}, "signals": {"3分_C0": [old]}}
        self.assertEqual(I.registration(raw), independent.registration(raw))
        self.assertEqual(I.select(deepcopy(block)), independent.select(deepcopy(block)))
        paths = [
            [quote(11., 11, 1000., 1005.), quote(20., 20, 995., 1000.), quote(50., 50, 1250., 1255.), quote(150., 150, 1250., 1255.)],
            [quote(11., 11, 800., 995.), quote(50., 50, 1000., 1005.)],
            [quote(11., 11, 1000., 1005.), quote(40., 40, 995., 1000.), quote(150., 150, 1000., 1005.)],
            [quote(41., 41, 995., 1000.)],
            [quote(11., 11, 995., 1000.), quote(1000., 1000, 1000., 1005.)],
        ]
        for side in (1, -1):
            for path_rows in paths:
                rows = path_rows if side == 1 else [quote(q.now, q.line, 2000. - q.ask, 2000. - q.bid) for q in path_rows]
                columns = {key: [getattr(row, key) for row in rows] for key in ("now", "line", "bid", "ask")}
                main = I.入口経路(rows)
                for policy in ("E0", "E1"):
                    source = signal(side, policy)
                    self.assertEqual(main.evaluate_signal(source, 180., 150., policy), independent.label_direct(columns, source, 180., 150., policy))


def driver_module() -> Any:
    """主driverの定義だけを読み込む。

    引数: なし。
    返り値: Anyは主モジュール。市場CLIは起動しない。
    """
    return load(HERE / "検証.py", "突破指値34合成の主driver")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """人工C0登録と一時保存先だけを主へ渡す。

    引数: driver(Any)は主、count(int)は人工場数。
    返り値: Iterator[Any]は人工台帳・純材料・未来列付き共有case。
    """
    with tempfile.TemporaryDirectory(prefix="突破指値34合成_", dir=ROOT / "work") as temporary:
        base = Path(temporary)
        study, work = base / "study", base / "work"
        study.mkdir(); work.mkdir()
        config = driver.expected_config()
        for name, value in (("条件.json", config), ("入力台帳.json", {"人工": True}), ("入口参照.json", {"人工": True}), ("対照参照.json", {"人工": True})):
            (study / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        (study / "計画.md").write_text("人工計画\n", encoding="utf-8")
        (work / "診断予定.json").write_text('{"人工":true}', encoding="utf-8")
        sessions = [f"2099-01-{1 + index // 2:02d}_{'Day' if index % 2 == 0 else 'Night'}" for index in range(count)]
        manifest = {"entries": [{"session": session, "source_path": "人工.gz"} for session in sessions]}
        cases, material = [], {}
        for session in sessions:
            source = signal(policy="E0")
            source.update(場=session, イベントID=session + "_人工21_C0", 入口ID="3分_C0")
            raw = {**source, "発動ID": session + "_人工21", "index": 21, "足終了時計秒": 10.,
                "前20足番号": list(range(1, 21)), "直前最高H": 1000., "直前最安L": 990., "close": 1010.,
                "共通M準備": True, "M除外理由": [], "時間条件可": True, "確認遅延条件可": True, "先着評価対象": True,
                "戦略判定": {"C0": {"採用": True}, "C1": {"採用": False}}, "BB幅比較厳密符号": 0,
                "CCI現": {"分子": 120, "分母": 1, "有効": True}, "CCI前": {"分子": 120, "分母": 1, "有効": True}}
            cases.append({**deepcopy(source), "ラベル": "人工未来先着を渡さない", "最大順行pt": 987654.})
            material[session] = {"quality": {"全Q発動記録": [raw]}, "signals": {"3分_C0": [source]},
                "events": [], "frames": {3: []}, "duration": 415., "input_quality": {"場": session}, "cutoff": 180., "deadline": 190.}

        def built(entry: dict, manifest_value: dict, banks: dict, config_value: dict) -> dict:
            """人工場だけを純登録へ射影する。

            引数: entry/manifest_value/config_value(dict)は人工入力、banks(dict)は未使用。
            返り値: dictは当時情報だけの二案。
            """
            return I.select(deepcopy(material[entry["session"]]))

        yield SimpleNamespace(study=study, work=work, config=config, manifest=manifest, cases=cases, material=material,
            built=built, pointer={"文書と証明": {}, "共有明細": []}, control={"文書と証明": {}, "共有明細": []})


class DriverTests(unittest.TestCase):
    """準備CLIと出典固定を人工材料だけで検査する。"""

    def test_cli_prepare_forbids_labels_operations_and_control_gzip(self) -> None:
        """人工66場のprepareを先着/損益禁止で最後まで通す。

        引数: なし。
        返り値: None。共有caseは13列だけへ即射影される。
        """
        driver = driver_module()
        with artificial_driver(driver) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver.S, "validate_entry_reference", return_value=f.pointer), \
                patch.object(driver, "validate_control_reference", return_value=f.control), \
                patch.object(driver.S.S, "load_shared_cases", return_value={"3分_C0": f.cases}), \
                patch.object(driver, "build_session", side_effect=f.built) as built, \
                patch.object(driver, "freeze", side_effect=AssertionError("prepareは固定禁止")) as freeze, \
                patch.object(driver.ENGINE, "replay", side_effect=AssertionError("prepareは運用禁止")) as replay, \
                patch.object(driver.I.入口経路, "evaluate_signal", side_effect=AssertionError("prepareは新先着禁止")) as label, \
                patch.object(driver.E, "entry_metrics", side_effect=AssertionError("prepareは先着集計禁止")) as metrics, \
                patch.object(driver.gzip, "open", side_effect=AssertionError("prepareは旧運用明細禁止")), \
                patch.object(sys, "argv", ["人工34", "--study", str(f.study), "--work", str(f.work), "--prepare"]), redirect_stdout(io.StringIO()):
            driver.main()
            proof = json.loads((f.work / "準備点検.json").read_text(encoding="utf-8"))
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertTrue(proof["旧31C0純登録同値"])
            self.assertEqual(proof["原C0登録数"], 66)
            self.assertEqual(built.call_count, 66)
            for scene in proof["準備"]:
                for source in scene["純信号"]:
                    self.assertEqual(set(source), set(I.SIGNAL_FIELDS[source["入口ID"][-2:]]))
                    self.assertNotIn("ラベル", source)
                    self.assertNotIn("最大順行pt", source)
                self.assertNotIn("指標", scene)
            self.assertFalse((f.study / "結果.json").exists())
            self.assertFalse(any((f.work / name).exists() for name in driver.FILES))
            freeze.assert_not_called(); replay.assert_not_called(); label.assert_not_called(); metrics.assert_not_called()

    def test_config_partial_and_identity_guards(self) -> None:
        """条件ドリフトとpartialを拒否し、識別子変換で数値差を隠さない。

        引数: なし。
        返り値: None。途中ファイルはそのまま保持する。
        """
        driver = driver_module()
        for section, key, value in (("水準指値", "E1", "変更"), ("運用", "新規有効秒", 31), ("運用", "新規待機秒", 0)):
            config = driver.expected_config(); config[section][key] = value
            with self.assertRaises(ValueError):
                driver.validate_config(config)
        expected = {"候補ID": "3分_T0_XF", "価格": 1000., "元行": 5, "未知列": [3, 1, 2]}
        actual = {**expected, "候補ID": "3分_E0_XF"}
        self.assertEqual(driver.rename(actual, "_E0", "_T0"), expected)
        actual["価格"] += 5
        self.assertNotEqual(driver.rename(actual, "_E0", "_T0"), expected)
        with artificial_driver(driver, 1) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver.S, "validate_entry_reference", return_value=f.pointer), \
                patch.object(driver, "validate_control_reference", return_value=f.control), \
                patch.object(driver, "freeze", side_effect=AssertionError("partialは固定前拒否")) as freeze, \
                patch.object(driver, "build_session", side_effect=AssertionError("partialは市場前拒否")) as built:
            path = f.work / driver.FILES[0]; path.write_bytes(b"artificial_partial")
            with self.assertRaises(ValueError):
                driver.run(f.study, f.work, False)
            self.assertEqual(path.read_bytes(), b"artificial_partial")
            freeze.assert_not_called(); built.assert_not_called()

    def test_control_reference_complete_proofs_and_sha(self) -> None:
        """旧対照八証明/固定版/二明細の欠落や改変を拒否する。

        引数: なし。
        返り値: None。実gzipは宣言SHAだけを使いopenしない。
        """
        driver = driver_module()
        pointer = json.loads((driver.STUDY / "対照参照.json").read_text(encoding="utf-8"))
        declared = {normalized(ROOT / row["パス"]): row["圧縮SHA256参考"] for row in pointer["共有明細"]}
        original_sha = driver.O.sha

        def declared_sha(path: Path) -> str:
            """共有gzipだけ宣言指紋へ振り替える。

            引数: path(Path)は検算先。
            返り値: strは宣言又は現コード/小文書のSHA。
            """
            return declared[normalized(path)] if normalized(path) in declared else original_sha(path)

        with artificial_driver(driver, 1) as f, patch.object(driver.O, "sha", side_effect=declared_sha):
            path = f.study / "対照参照.json"
            path.write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(driver.validate_control_reference(f.study), pointer)
            for key in pointer["文書と証明"]:
                changed = deepcopy(pointer); del changed["文書と証明"][key]
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.validate_control_reference(f.study)
            for key in ("旧固定SHA256",):
                changed = deepcopy(pointer); changed[key] = "0" * 64
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.validate_control_reference(f.study)
            changed = deepcopy(pointer); changed["共有明細"][0]["展開内容SHA256"] = "0" * 64
            path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                driver.validate_control_reference(f.study)

    def test_artificial_formal_two_operations_and_old_xf_control(self) -> None:
        """人工一場の新先着・二運用・保存末尾と旧XF全対照を通す。

        引数: なし。
        返り値: None。実共有case/気配/圧縮明細は使用しない。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            session = f.manifest["entries"][0]["session"]
            begin, finish, cutoff, deadline = driver.W.OLD.shared.legacy.session_times(session)
            now = begin.timestamp() + 3960
            base = f.material[session]
            source = base["signals"]["3分_C0"][0]
            source.update(要求時計秒=now, 要求原板行=10)
            base["quality"]["全Q発動記録"][0].update(要求時計秒=now, 要求原板行=10, 足終了時計秒=now)
            base.update(cutoff=cutoff.timestamp(), deadline=deadline.timestamp(), duration=(finish - begin).total_seconds() / 60)
            phase = driver.E.phase_of(session, f.config)
            case = {**deepcopy(source), "ラベル": "未約定", "理由": "30秒内に正常板なし",
                **{key: None for key in ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")}}
            old_signal = deepcopy(source)
            old_signal.update(入口ID="3分_T0", イベントID=source["イベントID"][:-3] + "_T0")
            old_state, old_info = driver.ENGINE.BASE.replay([], [old_signal], [], session, "3分_T0_XF", f.config["運用"], {"出口ID": "XF"}, "順行")
            old_info.update(期間=phase, 場時間分=base["duration"])
            old_detail = {"候補ID": "3分_T0_XF", "場": session, "品質": old_info, "約定": old_state.fills,
                "取引": old_state.trades, "注文": old_state.orders, "入口取扱": old_state.signals}
            control = {"文書と証明": {}, "共有明細": []}
            for name, rows in (("全運用詳細.jsonl.gz", [old_detail]), ("追尾.jsonl.gz", [{"期間": phase, **row} for row in old_state.normal_log])):
                path = f.work / "人工旧" / name
                path.parent.mkdir(exist_ok=True)
                with gzip.open(path, "wt", encoding="utf-8") as stream:
                    for row in rows:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                control["共有明細"].append({"パス": path.relative_to(ROOT).as_posix()})
            original_replay = driver.ENGINE.replay
            accepted = []

            def replayed(*args: Any, **kwargs: Any) -> Any:
                """人工liveのwhitelistを確認して本来の運用へ渡す。

                引数: args/kwargs(Any)は人工再生引数。
                返り値: Anyは人工運用結果。未来の先着値を受け付けない。
                """
                for row in args[1]:
                    self.assertEqual(set(row), set(I.SIGNAL_FIELDS[row["入口ID"][-2:]]))
                    self.assertNotIn("ラベル", row)
                    accepted.append(deepcopy(row))
                return original_replay(*args, **kwargs)

            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver.S, "validate_entry_reference", return_value=f.pointer), \
                    patch.object(driver, "validate_control_reference", return_value=control), \
                    patch.object(driver.S.S, "load_shared_cases", return_value={"3分_C0": [case]}), \
                    patch.object(driver, "build_session", side_effect=f.built), \
                    patch.object(driver, "freeze", return_value={}), patch.object(driver.ENGINE, "replay", side_effect=replayed), \
                    redirect_stdout(io.StringIO()):
                summary = driver.run(f.study, f.work, False)
            self.assertEqual(summary["運用候補数"], 2)
            self.assertEqual(len(accepted), 2)
            output = json.loads((f.study / "結果.json").read_text(encoding="utf-8"))
            self.assertEqual(output["表示固定ID"], ["3分_E0_XF", "3分_E1_XF"])
            self.assertEqual(output["入口評価数"], 2)
            self.assertTrue(output["入口125250評価の変更"])
            self.assertTrue(json.loads((f.study / "E0対照同値.json").read_text(encoding="utf-8"))["全件一致"])
            with gzip.open(f.work / "入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
                saved_cases = [json.loads(line) for line in stream]
            self.assertEqual(len(saved_cases), 2)
            self.assertEqual([row["ラベル"] for row in saved_cases], ["未約定", "未約定"])
            catalog = json.loads((f.study / "一覧.resources.json").read_text(encoding="utf-8"))
            self.assertEqual(len(catalog["resources"]), 2)
            self.assertTrue(all(row["id"].startswith("00034_") for row in catalog["resources"]))

    def test_freeze_requires_current_independent_and_final_synthetic(self) -> None:
        """現版独立準備・最終人工・全依存bindを固定前に必須とする。

        引数: なし。
        返り値: None。人工固定先だけを作り、実固定を更新しない。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver.S, "validate_entry_reference", return_value=f.pointer), \
                patch.object(driver, "validate_control_reference", return_value=f.control), \
                patch.object(driver.S.S, "load_shared_cases", return_value={"3分_C0": f.cases}), \
                patch.object(driver, "build_session", side_effect=f.built), redirect_stdout(io.StringIO()):
            driver.run(f.study, f.work, True)
            dependency = ROOT / "scripts/CCI突破/入口.py"
            independent_path = f.work / "独立準備点検.json"
            proof = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
                "主準備SHA256": sha(f.work / "準備点検.json"), "主コードSHA256": driver.code_pins(),
                "条件SHA256": sha(f.study / "条件.json"), "入力台帳SHA256": sha(f.study / "入力台帳.json"),
                "参照入力台帳SHA256": sha(driver.MANIFEST_PATH), "入口参照SHA256": sha(f.study / "入口参照.json"),
                "対照参照SHA256": sha(f.study / "対照参照.json"), "コードSHA256": sha(HERE / "状態独立確認.py"),
                "追尾コードSHA256": sha(HERE / "追尾独立確認.py"),
                "依存コードSHA256": {dependency.relative_to(ROOT).as_posix(): sha(dependency)}}
            synthetic_paths = [HERE / name for name in ("検証.py", "入口.py", "運用.py", "合成検証.py")] + [f.study / "条件.json"]
            synthetic = {"全件成功": True, "合成編集終了": False,
                "ファイルSHA256": {p.relative_to(ROOT).as_posix(): sha(p) for p in synthetic_paths},
                "独立数値補助SHA256": sha(HERE / "状態独立確認.py"), "独立追尾補助SHA256": sha(HERE / "追尾独立確認.py")}
            synthetic_file = f.work / "人工合成証拠.json"
            canonical_synthetic = ROOT / "work/突破指値/合成検証.json"
            previous_lock = driver.PREVIOUS / "固定.json"
            original_read, original_sha = driver.W.read_json, driver.O.sha

            def redirected_read(path: Path) -> dict:
                """旧固定依存と合成証拠だけを人工宣言へ差し替える。

                引数: path(Path)は参照先。
                返り値: dictは人工証拠又は元の小文書。
                """
                if normalized(path) == normalized(previous_lock):
                    return {"ファイルSHA256": {dependency.relative_to(ROOT).as_posix(): sha(dependency)}}
                if normalized(path) == normalized(canonical_synthetic):
                    return deepcopy(synthetic)
                return original_read(path)

            def redirected_sha(path: Path) -> str:
                """人工合成の指紋だけを一時先へ向ける。

                引数: path(Path)は検算先。
                返り値: strは人工合成又は現小型ファイルのSHA。
                """
                return sha(synthetic_file) if normalized(path) == normalized(canonical_synthetic) else original_sha(path)

            with patch.object(driver.W, "read_json", side_effect=redirected_read), patch.object(driver.O, "sha", side_effect=redirected_sha):
                with self.assertRaises(FileNotFoundError):
                    driver.freeze(f.study, f.work)
                independent_path.write_text(json.dumps(proof), encoding="utf-8")
                synthetic_file.write_text(json.dumps(synthetic), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                synthetic["合成編集終了"] = True
                for key in ("主準備SHA256", "コードSHA256", "追尾コードSHA256", "対照参照SHA256"):
                    changed = deepcopy(proof); changed[key] = "0" * 64
                    independent_path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        driver.freeze(f.study, f.work)
                changed = deepcopy(proof); changed["依存コードSHA256"] = {}
                independent_path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                independent_path.write_text(json.dumps(proof), encoding="utf-8")
                correct = synthetic["独立追尾補助SHA256"]
                synthetic["独立追尾補助SHA256"] = "0" * 64
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                synthetic["独立追尾補助SHA256"] = correct
                synthetic_file.write_text(json.dumps(synthetic), encoding="utf-8")
                fixed = driver.freeze(f.study, f.work)
                self.assertEqual(driver.freeze(f.study, f.work), fixed)
                self.assertEqual(fixed["独立準備SHA256"], sha(independent_path))
                (f.study / "計画.md").write_text("人工改変\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                (f.study / "結果.json").write_text('{"人工":true}', encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)


def main() -> None:
    """人工だけの検査を実行し、最終版では全主/独立SHAへbindする。

    引数: なし。--operation-onlyは主driver未完成時の途中検査、--finalは全コード編集終了後。
    返り値: None。実市場準備/先着/運用は呼ばない。
    """
    parser = argparse.ArgumentParser(description="旧突破境界への指値待機を人工検査")
    parser.add_argument("--operation-only", action="store_true")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    if args.final and args.operation_only:
        raise ValueError("途中検査で最終証拠を作れません")
    files = [HERE / name for name in ("入口.py", "運用.py", "合成検証.py")]
    if not args.operation_only:
        driver = load(HERE / "検証.py", "突破指値34合成のdriver")
        files.extend([HERE / "検証.py", driver.STUDY / "条件.json"])
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in files}
    helper_paths = [HERE / name for name in ("状態独立確認.py", "追尾独立確認.py")]
    helpers = [sha(p) if p.exists() else None for p in helper_paths]
    if args.final and any(value is None for value in helpers):
        raise ValueError("独立コード未完成です")
    stream = io.StringIO()
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(OperationTests), loader.loadTestsFromTestCase(EntryTests)]) if args.operation_only else loader.loadTestsFromModule(sys.modules[__name__])
    with deny_market():
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    unchanged = pins == {p.relative_to(ROOT).as_posix(): sha(p) for p in files} and helpers == [sha(p) if p.exists() else None for p in helper_paths]
    success = result.wasSuccessful() and result.testsRun > 0 and unchanged
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
        "実資料の先着損益計算": False, "実行中コード条件不変": unchanged, "ファイルSHA256": pins,
        "独立数値補助SHA256": helpers[0], "独立追尾補助SHA256": helpers[1], "運用入口途中検査だけ": args.operation_only,
        "範囲": "旧境界指値の買売鏡像/境界等号/有利現在BBO/+1秒と同秒原行/TTL30等号/停止期限優先/同側タッチとOHLC非約定/待機信号消費/固定出典/同quote125逆行/現在費用後strict起動と床維持/返済待機/E0固定33全属性対照/純whitelist/独立登録と直接先着全字段/独立XF全logと指値出典/人工66場CLI prepareの先着損益禁止/人工一場正式二運用と旧XF全対照・Viewer二資源/条件ドリフトとpartial拒否/旧対照八証明・固定・二明細bind/独立準備と最終人工の現在版必須join・固定改変拒否。実市場原板/cache/圧縮明細のstat/openは禁止。",
        "失敗": [{"検証": str(test), "内容": message} for test, message in result.failures],
        "エラー": [{"検証": str(test), "内容": message} for test, message in result.errors], "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / ("合成検証.json" if args.final else "合成検証_途中.json")
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({key: proof[key] for key in ("全件成功", "検証件数", "合成編集終了", "実行中コード条件不変")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
