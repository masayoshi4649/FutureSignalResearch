"""合成原板だけで欠測・同時計・状態差分保持と数量の時間帰属を検証する。"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("複合検証の入力準備", Path(__file__).with_name("データ準備.py"))
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
START, _ = MODULE.session_bounds("2026-10-01_Day")


def quote(now: float | None, last: float | None = 100, volume: float | None = 100) -> dict:
    """
    機能: 時差付き時計を持つ架空の原板行を作る。
    引数: now (float | None) は価格時計、last/volume (float | None) は価格・数量。
    返り値: dict は正常な気配と固定限月のJSON化可能な行。
    """
    stamp = datetime.fromtimestamp(now, MODULE.JST).isoformat() if now is not None else None
    return {"Symbol": "合成限月", "SymbolName": "架空先物", "CurrentPriceTime": stamp,
            "CurrentPrice": last, "Buy1": {"Price": 99, "Qty": 2},
            "Sell1": {"Price": 101, "Qty": 2}, "TradingVolume": volume, "TradingVolumeTime": stamp}


def event(offset: float, volume: float, volume_offset: float | None = None) -> object:
    """
    機能: 数量監査用の状態を任意の二つの時計で作る。
    引数: offset (float) は開始後秒、volume (float) は累積量、volume_offset (float | None) は数量時計秒。
    返り値: object は価格・気配が正常なEvent。
    """
    return MODULE.Event(START + offset, int(offset) + 1, 100, 99, 101, True, volume,
                        START + (offset if volume_offset is None else volume_offset))


class キャッシュの検証(unittest.TestCase):
    """連続同一状態だけの省略と原板対応を検証する。"""

    def test_同時計の状態変化と欠測の原行を保持する(self) -> None:
        """
        機能: NaNの反復だけを潰し、価格・数量・正常性・数量時計の変化を残すか確認する。
        引数: self (キャッシュの検証) はテスト状態。
        返り値: None。
        """
        rows = [quote(None, None, None), quote(None, None, None), quote(START)]
        rows.append(quote(START, 101))
        rows.append(quote(START, 101, 101))
        invalid = quote(START, 101, 101)
        invalid["Buy1"]["Qty"] = 0
        rows.append(invalid)
        shifted = json.loads(json.dumps(invalid))
        shifted["TradingVolumeTime"] = datetime.fromtimestamp(START + 1, MODULE.JST).isoformat()
        rows.extend([shifted, shifted])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "book.jsonl", root / "events.npz"
            source.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            meta = MODULE.build_one(source, target, "NK225", "2026-10-01_Day", root)
            events = list(MODULE.read_events(target))
        self.assertEqual([row.line for row in events], [1, 3, 4, 5, 6, 7])
        self.assertTrue(math.isnan(events[0].now))
        self.assertEqual(meta["omitted_identical"], 2)
        self.assertEqual(meta["raw_lines"], 8)
        self.assertEqual(events[2].last, 101)
        self.assertFalse(events[4].valid)
        self.assertEqual(events[5].volume_time, START + 1)

    def test_数量が共に1以上の変更だけなら省略できる(self) -> None:
        """
        機能: 1枚モデルで同じ正常性となる板数量の変化は状態同値にするか確認する。
        引数: self (キャッシュの検証) はテスト状態。
        返り値: None。
        """
        first, second = quote(START), quote(START)
        second["Buy1"]["Qty"] = 8
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "book.jsonl", root / "events.npz"
            source.write_text("\n".join(json.dumps(row) for row in (first, second)) + "\n", encoding="utf-8")
            meta = MODULE.build_one(source, target, "NK225", "2026-10-01_Day", root)
        self.assertEqual(meta["events"], 1)
        self.assertEqual(meta["omitted_identical"], 1)


class 数量の検証(unittest.TestCase):
    """採用時計・差分・再基準化・直前履歴を検証する。"""

    def test_数量時計の先行を保留し採用時点へ差分を帰属する(self) -> None:
        """
        機能: 未来側の数量時計をskipし、後続の採用時に増分を一度だけ計上するか確認する。
        引数: self (数量の検証) はテスト状態。
        返り値: None。
        """
        result = MODULE.audit_volume(iter([event(0, 100), event(1, 105), event(300, 110),
                                          event(301, 115, 302), event(302, 118)]), "2026-10-01_Day")
        rows = result["five_minute_bars"]
        self.assertFalse(rows[0]["baseline_complete"])
        self.assertTrue(rows[1]["baseline_complete"])
        self.assertEqual(rows[1]["observed_volume"], 13)
        self.assertEqual(result["counts"]["volume_clock_after_price"], 1)

    def test_減少と数量時計後退と足欠損後を再基準化する(self) -> None:
        """
        機能: 不連続な数量を正の増分として足へ流さず、その足を不完全にするか確認する。
        引数: self (数量の検証) はテスト状態。
        返り値: None。
        """
        result = MODULE.audit_volume(iter([event(0, 100), event(300, 110), event(600, 5),
                                          event(601, 8, 599), event(900, 12), event(1500, 20)]), "2026-10-01_Day")
        rows = {row["index"]: row for row in result["five_minute_bars"]}
        self.assertFalse(rows[2]["baseline_complete"])
        self.assertEqual(rows[2]["observed_volume"], 0)
        self.assertEqual(rows[3]["observed_volume"], 4)
        self.assertFalse(rows[5]["baseline_complete"])
        self.assertEqual(rows[5]["observed_volume"], 0)
        self.assertEqual(result["counts"]["accepted_cumulative_decreases"], 1)
        self.assertEqual(result["counts"]["accepted_volume_clock_backwards"], 1)

    def test_RVOLには現在より前の有効な20本が必要(self) -> None:
        """
        機能: 初足を使わず、現在足を分母履歴へ混ぜずに21本目の有効量から許可する。
        引数: self (数量の検証) はテスト状態。
        返り値: None。
        """
        result = MODULE.audit_volume(iter(event(index * 300, 100 + index) for index in range(22)), "2026-10-01_Day")
        rows = result["five_minute_bars"]
        self.assertFalse(rows[20]["preceding_twenty_quantity_bars_available"])
        self.assertTrue(rows[21]["preceding_twenty_quantity_bars_available"])
        self.assertEqual(result["rvol_previous_twenty_available_bars"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
