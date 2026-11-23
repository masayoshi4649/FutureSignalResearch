"""30秒指値・180秒指値・到達後回復を人工入力だけで検査する。"""

import argparse
import builtins
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import io
import json
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
WORK = ROOT / "work/回復監視"
SESSION = "人工回復監視場"
BOUNDS = (0., 10000., 9000., 9500.)


def normalized(path: object) -> str:
    """市場資料へ触れず絶対比較表記を作る。

    引数: path(object)はパス又は記述子。
    返り値: strは正規表記。非パスは空文字。
    """
    try:
        return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
    except (TypeError, ValueError):
        return ""


@contextmanager
def deny_market() -> Iterator[None]:
    """実原板・cache・実圧縮明細のstat/openを遮断する。

    引数: なし。
    返り値: Iterator[None]は人工一時先とコードだけを許可する範囲。
    """
    raw, work = normalized(ROOT.parent / "JP_OSE_Data"), normalized(ROOT / "work")
    old_open, old_path_open, old_stat = builtins.open, Path.open, Path.stat

    def check(path: object) -> None:
        """市場資料又は実中間明細への接近を拒否する。

        引数: path(object)は対象。
        返り値: None。人工一時ディレクトリだけ圧縮を許可する。
        """
        name = normalized(path)
        inside = name.startswith(work + os.sep)
        artificial = inside and os.path.relpath(name, work).split(os.sep)[0].startswith("回復監視35合成_")
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
    """市場遮断下で定義だけを読み込む。

    引数: path(Path)はPython、name(str)はモジュール名。
    返り値: Anyは定義。CLIを起動しない。
    """
    with deny_market():
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
        return value


def sha(path: Path) -> str:
    """小型出典の現在SHAを返す。

    引数: path(Path)はコード又は条件。
    返り値: strはSHA256。実市場明細は対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


O = load(HERE / "運用.py", "回復監視35合成の主運用")
I = load(HERE / "入口.py", "回復監視35合成の主入口")
CONFIG = json.loads((ROOT / "study/00034_CCI突破の水準指値/条件.json").read_text(encoding="utf-8"))["運用"]


def signal(policy: str = "E3", side: int = 1, now: float = 10., line: int = 10, index: int = 21) -> dict:
    """旧C0登録時点の15列だけを持つ人工信号を作る。

    引数: policy(str)は三案、side(int)は方向、now/line(float/int)は登録key、index(int)は番号。
    返り値: dictは純入口。未来touch/回復は含めない。
    """
    return {"場": SESSION, "イベントID": f"人工{index}_{policy}", "入口ID": "3分_" + policy, "役割": "順行",
        "side": side, "方向": "買い" if side == 1 else "売り", "要求時計秒": now, "要求原板行": line,
        "確認遅延秒": 0., "low": 990., "high": 1010., "atr": 25., "bb_mean": None,
        "新規指値価格": 1000., "指値根拠": {"旧C0イベントID": f"人工{index}_C0", "登録足番号": index,
            "公開時計秒": now, "公開原板行": line, "前20足番号": list(range(index - 20, index)),
            "前20最高H": 1000. if side == 1 else 1010., "前20最安L": 990. if side == 1 else 1000., "実side": side}}


def quote(now: float, line: int, bid: float, ask: float, valid: bool = True) -> SimpleNamespace:
    """原行順を持つ人工BBOを作る。

    引数: now/line(float/int)はkey、bid/ask(float)は価格、valid(bool)は正常性。
    返り値: SimpleNamespaceは人工観測。
    """
    return SimpleNamespace(now=now, line=line, bid=bid, ask=ask, valid=valid)


def mirror(rows: list[Any]) -> list[Any]:
    """価格和2000の上下反射を作る。

    引数: rows(list[Any])は人工買い経路。
    返り値: list[Any]は高低の気配を交換した売り経路。
    """
    return [quote(row.now, row.line, 2000. - row.ask, 2000. - row.bid, row.valid) for row in rows]


def simulate(rows: list[Any], sources: list[dict] | None = None, policy: str = "E3",
             frames: list[dict] | None = None, bounds: tuple = BOUNDS) -> tuple[Any, dict]:
    """新運用を人工材料だけで逐次実行する。

    引数: rows(list[Any])は人工気配、sources(list[dict]|None)は純信号、policy(str)は三案、frames(list[dict]|None)は公開足、bounds(tuple)は人工時計。
    返り値: tuple[Any,dict]は状態/場会計。実市場起動は行わない。
    """
    return O.replay(rows, sources or [signal(policy)], frames or [], SESSION, "3分_" + policy + "_XF",
        deepcopy(CONFIG), {"出口ID": "XF"}, "順行", bounds)


def entries(state: Any) -> list[dict]:
    """新規fillだけを取得する。

    引数: state(Any)は人工状態。
    返り値: list[dict]はLongN/ShortN。
    """
    return [row for row in state.fills if row["type"].endswith("N")]


class OperationTests(unittest.TestCase):
    """完全対照と監視の時計・一回消費・費用起動を人工検査する。"""

    def test_e1_literal_fixed34_whole_control(self) -> None:
        """E1の全台帳・追尾・会計を固定34と完全一致させる。

        引数: なし。
        返り値: None。監視記録や新字段をE1へ足さない。
        """
        source = signal("E1")
        rows = [quote(11., 11, 995., 1000.), quote(12., 12, 1020., 1025.), quote(13., 13, 1000., 1005.), quote(14., 14, 995., 1000.)]
        a, qa = simulate(rows, [deepcopy(source)], "E1")
        b, qb = O.BASE.replay(rows, [deepcopy(source)], [], SESSION, "3分_E1_XF", deepcopy(CONFIG), {"出口ID": "XF"}, "順行", BOUNDS)
        self.assertEqual(qa, qb)
        for key in ("orders", "fills", "trades", "signals", "normal_log"):
            self.assertEqual(getattr(a, key), getattr(b, key))
        self.assertFalse(hasattr(a, "watch_records"))

    def test_e2_same_touch_and_new_lifetime_mirror(self) -> None:
        """旧30秒内はE1同新規、延長だけで新しい到達を拾う。

        引数: なし。
        返り値: None。元configを破壊せず、売買を反射する。
        """
        for side in (1, -1):
            for time in (20., 80.):
                rows = [quote(11., 11, 1000., 1005.), quote(time, 80, 995., 1000.)]
                if side == -1:
                    rows = mirror(rows)
                e1, _ = simulate(rows, [signal("E1", side)], "E1")
                e2, _ = simulate(rows, [signal("E2", side)], "E2")
                self.assertEqual(len(entries(e1)), int(time <= 40.))
                self.assertEqual(entries(e2)[0]["price_clock"], time)
                self.assertEqual(entries(e2)[0]["price"], 1000.)
                if entries(e1):
                    self.assertEqual(entries(e1)[0]["price"], entries(e2)[0]["price"])
        self.assertEqual(CONFIG["新規有効秒"], 30)

    def test_e2_expiry_equal_stop_and_force(self) -> None:
        """180秒等号は有効、超過と停止/強制等号は先取消する。

        引数: なし。
        返り値: None。
        """
        for clock, bounds, count in ((190., BOUNDS, 1), (190.001, BOUNDS, 0),
                (190., (0., 10000., 190., 9500.), 0), (190., (0., 10000., 9000., 190.), 0)):
            state, _ = simulate([quote(clock, 190, 995., 1000.)], [signal("E2")], "E2", bounds=bounds)
            self.assertEqual(len(entries(state)), count)

    def test_e3_local_reservation_then_same_second_recovery(self) -> None:
        """予約/初touch/strict後行回復/実要求+1秒を別段階にする。

        引数: なし。
        返り値: None。同じ回復quoteではfillしない。
        """
        state = O.回復監視状態(SESSION, "3分_E3_XF", CONFIG, {"出口ID": "XF"}, "順行", [signal()], BOUNDS)
        state.signal_group([signal()])
        self.assertIsNone(state.pending)
        self.assertEqual(state.orders, [])
        self.assertEqual(state.normal_log, [])
        state.quote(10.999, 11, 995., 1000.)
        self.assertIsNone(state.watch["初回到達出典"])
        state.quote(11., 12, 995., 1000.)
        state.quote(11., 13, 1000., 1005.)
        self.assertEqual(state.orders, [])
        state.quote(11., 14, 1005., 1010.)
        self.assertIsNone(state.watch)
        self.assertEqual(state.pending["time"], 11.)
        self.assertEqual(entries(state), [])
        state.quote(11., 15, 1010., 1015.)
        self.assertEqual(entries(state), [])
        state.quote(12., 16, 1010., 1015.)
        self.assertEqual((entries(state)[0]["price_clock"], entries(state)[0]["source_line"], entries(state)[0]["price"]), (12., 16, 1015.))
        self.assertEqual(state.orders[0]["元登録時計秒"], 10.)
        self.assertEqual(state.orders[0]["要求時計秒"], 11.)
        self.assertEqual(state.orders[0]["初回到達出典"]["原板行"], 12)
        self.assertEqual(state.orders[0]["初回回復出典"]["原板行"], 14)
        self.assertTrue(all(not row["動作"].startswith("監視") and row["動作"] not in ("初回到達", "初回回復") for row in state.normal_log))

    def test_e3_first_touch_no_replacement_and_mirror(self) -> None:
        """深い後続touchへ差し替えず、回復後現在BBOを買売対称に使う。

        引数: なし。
        返り値: None。実約定が旧指値より有利へ戻る例も許可する。
        """
        base = [quote(11., 11, 995., 1000.), quote(12., 12, 975., 980.), quote(13., 13, 1005., 1010.), quote(14., 14, 990., 995.)]
        for side in (1, -1):
            state, _ = simulate(base if side == 1 else mirror(base), [signal(side=side)])
            order = state.orders[0]
            self.assertEqual(order["初回到達出典"]["原板行"], 11)
            self.assertEqual(order["初回回復出典"]["原板行"], 13)
            self.assertEqual(entries(state)[0]["price"], 995. if side == 1 else 1005.)
            self.assertEqual(order["絶対失効時計秒"], 190.)
            self.assertEqual(order["新規実効TTL秒"], 177.)

    def test_e3_last_effective_second_and_too_late_recovery(self) -> None:
        """回復+1の元期限等号だけを認め、元期限の回復は消費して拒否する。

        引数: なし。
        返り値: None。回復で寿命を再開始しない。
        """
        for recovery, fill_count in ((189., 1), (190., 0)):
            state, info = simulate([quote(11., 11, 995., 1000.), quote(recovery, 189, 1005., 1010.), quote(190., 190, 1010., 1015.)])
            self.assertEqual(len(entries(state)), fill_count)
            self.assertEqual(info["監視初回回復数"], 1)
            if not fill_count:
                self.assertEqual(state.orders, [])
                last = state.watch_records[-1]
                self.assertEqual(last["終了理由"], "回復時刻不可")
                self.assertEqual(last["除外理由"], ["回復後1秒が元期限外"])

    def test_e3_absolute_order_expiry_and_waiting_gap(self) -> None:
        """回復要求後も元期限で取消し、空白品質をrequest+180へ延長しない。

        引数: なし。
        返り値: None。純粋な無建玉空白だけで確定額をnullにしない。
        """
        state, info = simulate([quote(20., 20, 995., 1000.), quote(180., 180, 1005., 1010.),
            quote(200., 200, 1010., 1015.), quote(600., 600, 1010., 1015.), quote(9501., 9501, 1010., 1015.)])
        self.assertEqual(entries(state), [])
        self.assertEqual(state.orders[0]["状態"], "新規停止または元登録180秒失効")
        self.assertEqual(state.orders[0]["新規実効TTL秒"], 10.)
        self.assertEqual(info["新規待機中空白区間数"], 0)
        self.assertFalse(info["観測経路注意"])
        self.assertEqual(info["確定対象純損益円"], 0.)

    def test_e3_remaining_sixty_minutes_boundary_consumed(self) -> None:
        """回復時残60分の等号を認め、不可初回回復を後へ取り直さない。

        引数: なし。
        返り値: None。未約定を反転注文へ変えない。
        """
        bounds = (0., 4000., 3500., 3700.)
        for recovered, count in ((100., 1), (101., 0)):
            state, info = simulate([quote(20., 20, 995., 1000.), quote(recovered, 100, 1005., 1010.),
                quote(recovered + 1, 101, 1010., 1015.), quote(recovered + 2, 102, 1005., 1010.)], bounds=bounds)
            self.assertEqual(len(entries(state)), count)
            self.assertEqual(info["監視初回回復数"], 1)
            if not count:
                self.assertEqual(len(state.orders), 0)
                self.assertEqual(state.watch_records[-1]["除外理由"], ["回復時残り60分未満"])

    def test_e3_monitor_signal_suppression_and_no_ttl_amendment(self) -> None:
        """監視中の後続C0を消費し、元境界・期限・初回touchを固定する。

        引数: なし。
        返り値: None。監視は実注文pendingとは別に数える。
        """
        later = signal(side=-1, now=20., line=20, index=22)
        later["新規指値価格"] = 1100.
        state, info = simulate([quote(11., 11, 1000., 1005.), quote(191., 191, 995., 1000.)], [signal(), later])
        self.assertEqual(state.orders, [])
        self.assertEqual([row["取扱"] for row in state.signals], ["未到達で180秒失効", "監視中抑止"])
        self.assertEqual(info["監視予約数"], 1)
        self.assertEqual(info["監視終了数"], 1)
        self.assertEqual(info["監視中抑止数"], 1)
        self.assertEqual(info["新規取消数"], 0)
        self.assertEqual(state.watch_records[-1]["監視"]["絶対失効時計秒"], 190.)

    def test_e3_ohlc_and_same_side_touch_are_not_observations(self) -> None:
        """足高安や買bidだけの接触から到達/回復を作らない。

        引数: なし。
        返り値: None。
        """
        frame = {"publish": True, "confirm": 20., "confirm_line": 20, "end": 19., "low": 900., "high": 1100., "close": 1000.}
        state, info = simulate([quote(11., 11, 1000., 1005.)], frames=[frame])
        self.assertEqual(info["監視初回到達数"], 0)
        self.assertEqual(info["監視初回回復数"], 0)
        self.assertEqual(state.orders, [])

    def test_e3_new_fill_quote_hard_and_return_source(self) -> None:
        """回復確認後でも新規同quoteの125逆行を監視し後続で返済する。

        引数: なし。
        返り値: None。回復BBOや旧水準で約定しない。
        """
        state, _ = simulate([quote(11., 11, 995., 1000.), quote(12., 12, 1005., 1010.),
            quote(13., 13, 800., 1000.), quote(14., 14, 790., 800.)])
        trade = state.trades[0]
        self.assertEqual((trade["新規価格"], trade["返済要求時計秒"], trade["返済時計秒"], trade["返済価格"]), (1000., 13., 14., 790.))
        self.assertEqual(trade["返済理由"], "保護")
        self.assertEqual(trade["元登録時計秒"], 10.)
        self.assertEqual(trade["新規要求時計秒"], 12.)
        self.assertEqual(trade["初回回復出典"]["原板行"], 12)
        self.assertTrue(all("新規指値価格" not in row for row in (state.orders[0], trade)))

    def test_e3_cost_current_boundary_sticky_floor_and_source(self) -> None:
        """XFの現在費用後strict起動と非緩和を初期出典込みで継承する。

        引数: なし。
        返り値: None。過去MFEで起動せず、pending中は線と出典を凍結する。
        """
        state = O.回復監視状態(SESSION, "3分_E3_XF", CONFIG, {"出口ID": "XF"}, "順行", [signal()], BOUNDS)
        state.signal_group([signal()])
        for row in [quote(11., 11, 995., 1000.), quote(12., 12, 1005., 1010.), quote(13., 13, 990., 995.)]:
            state.quote(row.now, row.line, row.bid, row.ask)
        state.position["mfe"] = 30.
        state.quote(14., 14, 1007.2, 1010.)
        self.assertFalse(state.position["armed"])
        state.quote(15., 15, 1010., 1015.)
        self.assertTrue(state.position["armed"])
        self.assertEqual(state.position["cost_arm"]["控除後含み益円"], 28.)
        stop, source = state.position["trail_stop"], deepcopy(state.position["entry_recovery"])
        self.assertGreaterEqual(stop, 995.)
        state.quote(16., 16, 995., 1000.)
        state.quote(16.5, 17, 1030., 1035.)
        self.assertEqual(state.position["trail_stop"], stop)
        self.assertEqual(state.position["entry_recovery"], source)
        state.quote(17., 18, 990., 995.)
        trade = state.trades[0]
        self.assertEqual(trade["返済価格"], 990.)
        for key in O.CONTEXT_FIELDS:
            self.assertEqual(trade[key], source[key])
        first = next(row for row in state.normal_log if row["動作"] == "追尾初期化")
        self.assertEqual(first["元登録時計秒"], 10.)
        self.assertEqual(first["新規実効TTL秒"], 178.)
        self.assertEqual(first["絶対失効時計秒"], 190.)


class ObservationTests(unittest.TestCase):
    """純監視の公共出典と独立直接走査を比較する。"""

    def test_public_observation_matches_independent_all_fields(self) -> None:
        """到達/回復/時間不可を含む公共観測と仮新規を全列比較する。

        引数: なし。
        返り値: None。実資料は読まず人工列だけを使う。
        """
        independent = load(HERE / "状態独立確認.py", "回復監視35合成の独立状態")
        paths = [
            [quote(11., 11, 995., 1000.), quote(11., 12, 1005., 1010.), quote(12., 13, 1010., 1015.)],
            [quote(11., 11, 995., 1000.), quote(190., 190, 1005., 1010.)],
            [quote(11., 11, 995., 1000.), quote(40., 40, 990., 995.)],
            [quote(11., 11, 1000., 1005.), quote(200., 200, 995., 1000.)],
        ]
        for side in (1, -1):
            for rows in paths:
                rows = rows if side == 1 else mirror(rows)
                q = {key: [getattr(row, key) for row in rows] for key in ("now", "line", "bid", "ask")}
                path = I.入口経路(rows)
                source = signal(side=side)
                self.assertEqual(path.observation(source, BOUNDS[2], BOUNDS[3]), independent.observation(q, source, BOUNDS[2], BOUNDS[3]))
                for policy in ("E1", "E2", "E3"):
                    self.assertEqual(path.entry_index(source, BOUNDS[2], policy, BOUNDS[3]), independent.entry_index(q, source, BOUNDS[2], BOUNDS[3], policy))

    def test_independent_actual_entry_machine_all_attributes(self) -> None:
        """独立実受付機械と全新規/監視recordを買売三案で比較する。

        引数: なし。
        返り値: None。返済解放以外の保存新規を独立生成の根拠にしない。
        """
        independent = load(HERE / "状態独立確認.py", "回復監視35合成の独立実受付")
        outer = self

        class Audit:
            """人工独立比較をunittestへ渡す。"""

            def check(self, name: str, actual: object, expected: object) -> None:
                """全属性を厳密比較する。

                引数: name(str)は項目、actual/expected(object)は比較値。
                返り値: None。不一致を黙認しない。
                """
                outer.assertEqual(actual, expected, name)

        paths = [
            ([quote(11., 11, 995., 1000.), quote(12., 12, 1005., 1010.), quote(13., 13, 1010., 1015.),
                quote(14., 14, 1030., 1035.), quote(15., 15, 1000., 1005.), quote(16., 16, 995., 1000.)], BOUNDS, 12.5),
            ([quote(11., 11, 1000., 1005.), quote(191., 191, 995., 1000.)], BOUNDS, 20.),
            ([quote(11., 11, 995., 1000.), quote(190., 190, 1005., 1010.)], BOUNDS, None),
            ([quote(20., 20, 995., 1000.), quote(101., 101, 1005., 1010.)], (0., 4000., 3500., 3700.), None),
            ([quote(20., 20, 995., 1000.), quote(180., 180, 1005., 1010.), quote(200., 200, 1010., 1015.),
                quote(600., 600, 1010., 1015.), quote(9501., 9501, 1010., 1015.)], BOUNDS, None),
        ]
        for side in (1, -1):
            for base, bounds, later in paths:
                rows = base if side == 1 else mirror(base)
                q = {name: [getattr(row, name) for row in rows] for name in ("now", "line", "bid", "ask")}
                for policy in ("E1", "E2", "E3"):
                    sources = [signal(policy, side)]
                    if later is not None:
                        sources.append(signal(policy, -side, now=later, line=125, index=22))
                    state, info = simulate(rows, sources, policy, bounds=bounds)
                    detail = {"場": SESSION, "候補ID": "3分_" + policy + "_XF", "品質": info,
                        "約定": state.fills, "注文": state.orders, "取引": state.trades, "入口取扱": state.signals}
                    if policy == "E3":
                        detail["監視記録"] = state.watch_records
                    generated = independent.entry_replay(detail, q, sources, [], Audit(), bounds)
                    independent.compare_entry_replay(detail, generated, Audit())

    def test_independent_xf_full_logs_with_recovery_context(self) -> None:
        """独立XFと全三案の追尾log/二段階出典を省略せず一致させる。

        引数: なし。
        返り値: None。監視actionをXFnormal_logへ混ぜない。
        """
        independent = load(HERE / "追尾独立確認.py", "回復監視35合成の独立追尾")
        outer = self

        class Audit:
            """人工追尾全比較をunittestへ接続する。"""

            def check(self, name: str, actual: object, expected: object) -> None:
                """独立追尾の比較を厳密に判定する。

                引数: name(str)は項目、actual/expected(object)は比較値。
                返り値: None。
                """
                outer.assertEqual(actual, expected, name)

        base = [quote(11., 11, 995., 1000.), quote(12., 12, 1005., 1010.), quote(13., 13, 1010., 1015.),
            quote(14., 14, 1030., 1035.), quote(15., 15, 1000., 1005.), quote(16., 16, 995., 1000.)]
        for side in (1, -1):
            rows = base if side == 1 else mirror(base)
            for policy in ("E1", "E2", "E3"):
                source = signal(policy, side)
                state, info = simulate(rows, [source], policy)
                info["期間"] = "学習"
                detail = {"場": SESSION, "候補ID": "3分_" + policy + "_XF", "品質": info,
                    "約定": state.fills, "注文": state.orders, "取引": state.trades, "入口取扱": state.signals}
                logs, _ = independent.replay(detail, [vars(row) for row in rows], {source["イベントID"]: source},
                    Audit(), (BOUNDS[0], BOUNDS[1], BOUNDS[3]), deepcopy(CONFIG))
                self.assertEqual(logs, [{"期間": "学習", **row} for row in state.normal_log])


def driver_module() -> Any:
    """主driverの定義だけを読む。

    引数: なし。
    返り値: Anyは主定義。市場CLIを起動しない。
    """
    return load(HERE / "検証.py", "回復監視35合成の主driver")


@contextmanager
def artificial_driver(driver: Any, count: int = 66) -> Iterator[Any]:
    """人工C0の純材料と一時保存先だけを主へ渡す。

    引数: driver(Any)は主、count(int)は人工場数。
    返り値: Iterator[Any]は人工材料と未来列付き旧case。
    """
    with tempfile.TemporaryDirectory(prefix="回復監視35合成_", dir=ROOT / "work") as temporary:
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
            source = {key: value for key, value in signal().items() if key in I.BASE_FIELDS}
            source.update(場=session, イベントID=session + "_人工21_C0", 入口ID="3分_C0")
            raw = {**source, "発動ID": session + "_人工21", "index": 21, "足終了時計秒": 10.,
                "前20足番号": list(range(1, 21)), "直前最高H": 1000., "直前最安L": 990., "close": 1010.,
                "共通M準備": True, "M除外理由": [], "時間条件可": True, "確認遅延条件可": True, "先着評価対象": True,
                "戦略判定": {"C0": {"採用": True}, "C1": {"採用": False}}, "BB幅比較厳密符号": 0,
                "CCI現": {"分子": 120, "分母": 1, "有効": True}, "CCI前": {"分子": 120, "分母": 1, "有効": True}}
            cases.append({**deepcopy(source), "ラベル": "人工未来を渡さない", "最大順行pt": 987654.})
            material[session] = {"quality": {"全Q発動記録": [raw]}, "signals": {"3分_C0": [source]},
                "events": [], "frames": {3: []}, "duration": 415., "input_quality": {"場": session}, "cutoff": 9000., "deadline": 9500.}

        def built(entry: dict, manifest_value: dict, banks: dict, config_value: dict) -> dict:
            """人工場の純登録だけを三案へ射影する。

            引数: entry/manifest_value/config_value(dict)は人工入力、banks(dict)は未使用。
            返り値: dictは当時15列の三案と別監視観測の材料。
            """
            return I.select(deepcopy(material[entry["session"]]))

        yield SimpleNamespace(study=study, work=work, config=config, manifest=manifest, cases=cases,
            material=material, built=built, pointer={"文書と証明": {}, "共有明細": []}, control={"文書と証明": {}, "共有明細": []})


class DriverTests(unittest.TestCase):
    """準備の情報分離と正式三案の末尾を人工保存先だけで確認する。"""

    def test_cli_prepare_observes_but_forbids_fill_labels_operations(self) -> None:
        """人工66場prepareで公共観測だけを計算し仮新規/先着/運用を呼ばない。

        引数: なし。
        返り値: None。公共観測を純15列へ混入させない。
        """
        driver = driver_module()
        with artificial_driver(driver) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver.S, "validate_entry_reference", return_value=f.pointer), \
                patch.object(driver, "validate_control_reference", return_value=f.control), \
                patch.object(driver.S.S, "load_shared_cases", return_value={"3分_C0": f.cases}), \
                patch.object(driver, "build_session", side_effect=f.built) as built, \
                patch.object(driver, "freeze", side_effect=AssertionError("prepareは固定禁止")) as freeze, \
                patch.object(driver.ENGINE, "replay", side_effect=AssertionError("prepareは運用禁止")) as replay, \
                patch.object(driver.I.入口経路, "entry_index", side_effect=AssertionError("prepareは仮新規禁止")) as fill, \
                patch.object(driver.I.入口経路, "evaluate_signal", side_effect=AssertionError("prepareは先着禁止")) as label, \
                patch.object(driver.E, "entry_metrics", side_effect=AssertionError("prepareは先着集計禁止")) as metric, \
                patch.object(driver.gzip, "open", side_effect=AssertionError("prepareは旧三明細open禁止")), \
                patch.object(sys, "argv", ["人工35", "--study", str(f.study), "--work", str(f.work), "--prepare"]), redirect_stdout(io.StringIO()):
            driver.main()
            proof = json.loads((f.work / "準備点検.json").read_text(encoding="utf-8"))
            self.assertFalse(proof["ラベル計算"])
            self.assertFalse(proof["損益計算"])
            self.assertEqual(proof["原C0登録数"], 66)
            self.assertEqual(built.call_count, 66)
            for record in proof["準備"]:
                self.assertEqual(len(record["純信号"]), 3)
                self.assertEqual(len(record["仮監視観測"]), 1)
                for source in record["純信号"]:
                    self.assertEqual(set(source), set(I.SIGNAL_FIELDS[source["入口ID"][-2:]]))
                    self.assertNotIn("初回回復出典", source)
                    self.assertNotIn("ラベル", source)
                self.assertIsNone(record["仮監視観測"][0]["回復観測"]["初回到達出典"])
                self.assertNotIn("指標", record)
            self.assertFalse((f.study / "結果.json").exists())
            self.assertFalse(any((f.work / name).exists() for name in driver.FILES))
            freeze.assert_not_called(); replay.assert_not_called(); fill.assert_not_called(); label.assert_not_called(); metric.assert_not_called()

    def test_configuration_and_partial_refusal(self) -> None:
        """条件ドリフトと既存partialを市場処理前に拒否する。

        引数: なし。
        返り値: None。途中byteを保存したまま停止する。
        """
        driver = driver_module()
        for section, key, value in (("到達後回復", "E3", "変更"), ("運用", "新規待機秒", 0), ("運用", "新規有効秒", 180)):
            config = driver.expected_config(); config[section][key] = value
            with self.assertRaises(ValueError):
                driver.validate_config(config)
        with artificial_driver(driver, 1) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver.S, "validate_entry_reference", return_value=f.pointer), \
                patch.object(driver, "validate_control_reference", return_value=f.control), \
                patch.object(driver, "freeze", side_effect=AssertionError("partialは固定前停止")) as freeze, \
                patch.object(driver, "build_session", side_effect=AssertionError("partialは市場前停止")) as build:
            path = f.work / driver.FILES[0]; path.write_bytes(b"artificial_partial")
            with self.assertRaises(ValueError):
                driver.run(f.study, f.work, False)
            self.assertEqual(path.read_bytes(), b"artificial_partial")
            freeze.assert_not_called(); build.assert_not_called()

    def test_control_proofs_and_three_artifact_bind(self) -> None:
        """旧34の八証明と三明細宣言を欠落なく固定する。

        引数: なし。
        返り値: None。実gzipは宣言SHAだけを使い開かない。
        """
        driver = driver_module()
        pointer = json.loads((driver.STUDY / "対照参照.json").read_text(encoding="utf-8"))
        declared = {normalized(ROOT / row["パス"]): row["圧縮SHA256参考"] for row in pointer["共有明細"]}
        original = driver.O.sha

        def declared_sha(path: Path) -> str:
            """旧gzipは固定宣言値、それ以外は現小型出典を使う。

            引数: path(Path)は検算先。
            返り値: strはSHA256。実市場明細は開かない。
            """
            return declared.get(normalized(path)) or original(path)

        with artificial_driver(driver, 1) as f, patch.object(driver.O, "sha", side_effect=declared_sha):
            path = f.study / "対照参照.json"
            path.write_text(json.dumps(pointer), encoding="utf-8")
            self.assertEqual(driver.validate_control_reference(f.study), pointer)
            for key in pointer["文書と証明"]:
                changed = deepcopy(pointer); del changed["文書と証明"][key]
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.validate_control_reference(f.study)
            for key in ("旧固定SHA256",):
                changed = deepcopy(pointer); changed[key] = "0" * 64
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.validate_control_reference(f.study)
            changed = deepcopy(pointer); changed["共有明細"] = changed["共有明細"][:-1]
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(ValueError):
                driver.validate_control_reference(f.study)

    def test_artificial_formal_three_paths_and_local_watch_detail(self) -> None:
        """人工一場の旧E1対照・新先着・三運用・監視記録・Viewerを最後まで通す。

        引数: なし。
        返り値: None。旧C0未来列をliveへ渡さず、実市場を開かない。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f:
            session = f.manifest["entries"][0]["session"]
            begin, finish, cutoff, deadline = driver.W.OLD.shared.legacy.session_times(session)
            now = begin.timestamp() + 3960
            base = f.material[session]
            source = base["signals"]["3分_C0"][0]
            source.update(要求時計秒=now, 要求原板行=10)
            f.cases = [{**deepcopy(source), "ラベル": "人工未来を渡さない", "最大順行pt": 987654.}]
            base["quality"]["全Q発動記録"][0].update(要求時計秒=now, 要求原板行=10, 足終了時計秒=now)
            base.update(cutoff=cutoff.timestamp(), deadline=deadline.timestamp(), duration=(finish - begin).total_seconds() / 60)
            selected = I.select(deepcopy(base))
            pure = selected["signals"]["3分_E1"][0]
            phase = driver.E.phase_of(session, f.config)
            empty = {"ラベル": "未約定", "理由": "30秒内に指値成立正常BBOなし",
                **{key: None for key in ("新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分")}}
            old_case = {**deepcopy(pure), "期間": phase, "要求時計JST": driver.O.iso(now),
                "旧C0イベントID": source["イベントID"], "登録出典": deepcopy(selected["registrations"][0]), **empty}
            old_state, old_info = driver.ENGINE.BASE.replay([], [deepcopy(pure)], [], session, "3分_E1_XF", f.config["運用"], {"出口ID": "XF"}, "順行")
            old_info.update(期間=phase, 場時間分=base["duration"])
            old_detail = {"候補ID": "3分_E1_XF", "場": session, "品質": old_info,
                "約定": old_state.fills, "取引": old_state.trades, "注文": old_state.orders, "入口取扱": old_state.signals}
            control = {"文書と証明": {}, "共有明細": []}
            for name, rows in (("入口事例.jsonl.gz", [old_case]), ("全運用詳細.jsonl.gz", [old_detail]),
                    ("追尾.jsonl.gz", [{"期間": phase, **row} for row in old_state.normal_log])):
                path = f.work / "人工旧" / name
                path.parent.mkdir(exist_ok=True)
                with gzip.open(path, "wt", encoding="utf-8") as stream:
                    for row in rows:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                control["共有明細"].append({"パス": path.relative_to(ROOT).as_posix()})
            original, accepted = driver.ENGINE.replay, []

            def replayed(*args: Any, **kwargs: Any) -> Any:
                """新liveは15列だけとして実運用関数へ渡す。

                引数: args/kwargs(Any)は人工再生。
                返り値: Anyは人工状態と会計。未来観測を受け付けない。
                """
                for row in args[1]:
                    self.assertEqual(set(row), set(I.SIGNAL_FIELDS[row["入口ID"][-2:]]))
                    self.assertNotIn("回復観測", row)
                    accepted.append(row)
                return original(*args, **kwargs)

            with patch.object(driver, "manifest_for", return_value=f.manifest), \
                    patch.object(driver.S, "validate_entry_reference", return_value=f.pointer), \
                    patch.object(driver, "validate_control_reference", return_value=control), \
                    patch.object(driver.S.S, "load_shared_cases", return_value={"3分_C0": f.cases}), \
                    patch.object(driver, "build_session", side_effect=f.built), patch.object(driver, "freeze", return_value={}), \
                    patch.object(driver.ENGINE, "replay", side_effect=replayed), redirect_stdout(io.StringIO()):
                summary = driver.run(f.study, f.work, False)
            self.assertEqual(summary["運用候補数"], 3)
            self.assertEqual(len(accepted), 3)
            self.assertTrue(json.loads((f.study / "E1対照同値.json").read_text(encoding="utf-8"))["全件一致"])
            output = json.loads((f.study / "結果.json").read_text(encoding="utf-8"))
            self.assertEqual(output["表示固定ID"], ["3分_E1_XF", "3分_E2_XF", "3分_E3_XF"])
            with gzip.open(f.work / "全運用詳細.jsonl.gz", "rt", encoding="utf-8") as stream:
                details = [json.loads(line) for line in stream]
            self.assertTrue(all("監視記録" not in row for row in details[:2]))
            self.assertEqual([row["動作"] for row in details[2]["監視記録"]], ["監視受理", "監視終了"])
            with gzip.open(f.work / "入口事例.jsonl.gz", "rt", encoding="utf-8") as stream:
                cases = [json.loads(line) for line in stream]
            self.assertNotIn("回復観測", cases[0])
            self.assertIn("回復観測", cases[2])
            self.assertIsNone(cases[2]["新規要求時計秒"])
            catalog = json.loads((f.study / "一覧.resources.json").read_text(encoding="utf-8"))
            self.assertEqual(len(catalog["resources"]), 3)
            self.assertTrue(all(row["id"].startswith("00035_") for row in catalog["resources"]))

    def test_freeze_requires_current_independent_and_final_synthetic(self) -> None:
        """独立準備・最終人工・現在全依存のbindを固定前に必須とする。

        引数: なし。
        返り値: None。人工一時固定先だけを作り、正本を更新しない。
        """
        driver = driver_module()
        with artificial_driver(driver, 1) as f, patch.object(driver, "manifest_for", return_value=f.manifest), \
                patch.object(driver.S, "validate_entry_reference", return_value=f.pointer), \
                patch.object(driver, "validate_control_reference", return_value=f.control), \
                patch.object(driver.S.S, "load_shared_cases", return_value={"3分_C0": f.cases}), \
                patch.object(driver, "build_session", side_effect=f.built), redirect_stdout(io.StringIO()):
            driver.run(f.study, f.work, True)
            dependency = ROOT / "scripts/CCI突破/入口.py"
            independent_file = f.work / "独立準備点検.json"
            proof = {"全件一致": True, "不一致数": 0, "不一致": [], "ラベル計算": False, "損益計算": False,
                "主準備SHA256": sha(f.work / "準備点検.json"), "主コードSHA256": driver.code_pins(),
                "条件SHA256": sha(f.study / "条件.json"), "入力台帳SHA256": sha(f.study / "入力台帳.json"),
                "参照入力台帳SHA256": sha(driver.MANIFEST_PATH), "入口参照SHA256": sha(f.study / "入口参照.json"),
                "対照参照SHA256": sha(f.study / "対照参照.json"), "コードSHA256": sha(HERE / "状態独立確認.py"),
                "追尾コードSHA256": sha(HERE / "追尾独立確認.py"),
                "依存コードSHA256": {dependency.relative_to(ROOT).as_posix(): sha(dependency)}}
            pins = [HERE / name for name in ("検証.py", "入口.py", "運用.py", "合成検証.py")] + [f.study / "条件.json"]
            synthetic = {"全件成功": True, "合成編集終了": False,
                "ファイルSHA256": {path.relative_to(ROOT).as_posix(): sha(path) for path in pins},
                "独立数値補助SHA256": sha(HERE / "状態独立確認.py"), "独立追尾補助SHA256": sha(HERE / "追尾独立確認.py")}
            synthetic_file = f.work / "人工最終合成.json"
            canonical_synthetic = ROOT / "work/回復監視/合成検証.json"
            previous = driver.PREVIOUS / "固定.json"
            original_read, original_sha = driver.W.read_json, driver.O.sha

            def redirected_read(path: Path) -> dict:
                """旧固定依存と最終合成だけを人工宣言へ向ける。

                引数: path(Path)は参照先。
                返り値: dictは人工又は元の小型文書。
                """
                if normalized(path) == normalized(previous):
                    return {"ファイルSHA256": {dependency.relative_to(ROOT).as_posix(): sha(dependency)}}
                if normalized(path) == normalized(canonical_synthetic):
                    return deepcopy(synthetic)
                return original_read(path)

            def redirected_sha(path: Path) -> str:
                """人工最終合成だけを一時先の指紋へ差し替える。

                引数: path(Path)は固定対象。
                返り値: strは現出典又は人工証拠のSHA。
                """
                return sha(synthetic_file) if normalized(path) == normalized(canonical_synthetic) else original_sha(path)

            with patch.object(driver.W, "read_json", side_effect=redirected_read), patch.object(driver.O, "sha", side_effect=redirected_sha):
                with self.assertRaises(FileNotFoundError):
                    driver.freeze(f.study, f.work)
                independent_file.write_text(json.dumps(proof), encoding="utf-8")
                synthetic_file.write_text(json.dumps(synthetic), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                synthetic["合成編集終了"] = True
                for key in ("主準備SHA256", "主コードSHA256", "対照参照SHA256", "コードSHA256", "追尾コードSHA256"):
                    changed = deepcopy(proof); changed[key] = "0" * 64
                    independent_file.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        driver.freeze(f.study, f.work)
                changed = deepcopy(proof); changed["依存コードSHA256"] = {}
                independent_file.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                independent_file.write_text(json.dumps(proof), encoding="utf-8")
                correct = synthetic["独立追尾補助SHA256"]
                synthetic["独立追尾補助SHA256"] = "0" * 64
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                synthetic["独立追尾補助SHA256"] = correct
                synthetic_file.write_text(json.dumps(synthetic), encoding="utf-8")
                fixed = driver.freeze(f.study, f.work)
                self.assertEqual(driver.freeze(f.study, f.work), fixed)
                self.assertEqual(fixed["独立準備SHA256"], sha(independent_file))
                (f.study / "計画.md").write_text("人工固定後改変\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)
                (f.study / "結果.json").write_text('{"人工":true}', encoding="utf-8")
                with self.assertRaises(ValueError):
                    driver.freeze(f.study, f.work)


def main() -> None:
    """人工検査だけを実行し、完成版では主/独立の現在SHAへbindする。

    引数: なし。--operation-onlyは主driver完成前、--finalは全編集停止後。
    返り値: None。市場準備/先着/運用は起動しない。
    """
    parser = argparse.ArgumentParser(description="到達後回復と180秒指値の人工検査")
    parser.add_argument("--operation-only", action="store_true")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    if args.final and args.operation_only:
        raise ValueError("途中検査で最終証拠を作れません")
    paths = [HERE / name for name in ("入口.py", "運用.py", "合成検証.py")]
    if not args.operation_only:
        driver = load(HERE / "検証.py", "回復監視35合成の主driver")
        paths.extend([HERE / "検証.py", driver.STUDY / "条件.json"])
    pins = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    helper_paths = [HERE / name for name in ("状態独立確認.py", "追尾独立確認.py")]
    helpers = [sha(path) if path.exists() else None for path in helper_paths]
    if args.final and any(value is None for value in helpers):
        raise ValueError("独立コード未完成です")
    stream = io.StringIO()
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(OperationTests), loader.loadTestsFromTestCase(ObservationTests)]) if args.operation_only else loader.loadTestsFromModule(sys.modules[__name__])
    with deny_market():
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    unchanged = pins == {path.relative_to(ROOT).as_posix(): sha(path) for path in paths} and helpers == [sha(path) if path.exists() else None for path in helper_paths]
    success = result.wasSuccessful() and result.testsRun > 0 and unchanged
    proof = {"全件成功": success, "検証件数": result.testsRun, "合成編集終了": bool(args.final and success),
        "実資料の先着損益計算": False, "実行中コード条件不変": unchanged, "ファイルSHA256": pins,
        "独立数値補助SHA256": helpers[0], "独立追尾補助SHA256": helpers[1],
        "範囲": "E1固定34全属性対照、180秒寿命と等号、局所予約と注文の分離、初回touch/strict後key回復/同秒後行/回復+1の現在BBO、元絶対期限/残60分/不可初回消費、監視抑止/固定出典、足高安非観測、新規同quotehard、現在費用後strict起動/非緩和/初期出典、独立公共観測/仮新規/全実受付機械/全XFlogと二段階出典、人工66prepareの公共観測と純15列分離・仮新規先着運用禁止、人工正式三案/旧E1全case-detail-log対照/監視別記録/Viewer三資源、条件/partial/旧八証明三明細/独立準備と最終人工の現在版必須join・固定後変更拒否。実市場のstat/openは禁止。",
        "失敗": [{"検証": str(case), "内容": message} for case, message in result.failures],
        "エラー": [{"検証": str(case), "内容": message} for case, message in result.errors], "実行記録": stream.getvalue()}
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / ("合成検証.json" if args.final else "合成検証_途中.json")
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps({key: proof[key] for key in ("全件成功", "検証件数", "合成編集終了", "実行中コード条件不変")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
