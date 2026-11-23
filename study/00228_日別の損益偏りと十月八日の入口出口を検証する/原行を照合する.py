"""1秒執行で再生した全候補を、売買規則を呼び直さず価格原行から照合する。"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GROUPS = ("228入口", "228出口", "228小値幅", "228併用1", "228両方", "228回復入口")
JST = timezone(timedelta(hours=9))
VERIFY = runpy.run_path(str(next(HERE.parent.glob("00219*/経路診断/出口の原行を照合する.py"))))
FIELDS = ("side", "width", "request_time", "request_line", "entry_index", "entry_line", "entry_price",
          "entry_time", "exit_index", "exit_line", "exit_price", "exit_time", "net", "gross", "status",
          "initial_stop_points", "target_points", "trigger_time", "trigger_index", "activated", "activation_index",
          "activation_time", "extra_signal", "extra_signal_time", "extra_trigger", "extra_trigger_time", "extra_fill",
          "max_unrealized_net", "min_unrealized_net", "max_unrealized_time", "min_unrealized_time")


def verify_path(raw: np.ndarray, t: dict, cutoff: float) -> None:
    """
    機能：原板から取得、返済、転記された起動・発動時刻、固定IFDの初回到達を検算する。
    引数：raw（np.ndarray）は単一場の原行順の指紋照合済み板、t（dict）は一建玉、cutoff（float）は15:30の秒。
    返り値：None。気配側・費用、極値の初回時計、場末返済や動的返済の遅延が合わない場合は停止する。
    """
    VERIFY["verify"](raw, t)
    first, end = t["entry_index"], t["exit_index"]
    at = int(raw["source_line"].searchsorted(t["request_line"]))
    assert at <= first and raw["source_line"][at] == t["request_line"] and raw["time"][at] == t["request_time"]
    assert t.get("activated", False) == (t.get("activation_index", -1) >= 0)
    for index_key, time_key in (("activation_index", "activation_time"), ("extra_signal", "extra_signal_time"),
                                ("extra_trigger", "extra_trigger_time")):
        i = t.get(index_key, -1)
        if i >= 0:
            assert first < i <= end and raw["normal"][i] and raw["time"][i] == t[time_key]
        else:
            assert t.get(time_key) is None
    if t.get("extra_fill"):
        assert first < t["extra_signal"] <= t["extra_trigger"] == t["trigger_index"] < end and t["status"] == 5
    # ----------------------------------------
    path = raw[first + 1:end + 1]
    normal = path[path["normal"] == 1]
    side = t["side"]
    points = (normal["bid"] - t["entry_price"]) if side == 0 else (t["entry_price"] - normal["ask"])
    stop = t["initial_stop_points"]
    target = t["target_points"]
    assert t["width"] == target == stop and len(points)
    hits = np.flatnonzero((points >= target) | (points <= -stop))
    if t["status"] in (1, 2):
        assert len(hits) and normal["source_line"][hits[0]] == t["exit_line"]
        assert (points[hits[0]] >= target) == (t["status"] == 1)
    elif t["status"] == 4:
        assert not np.any((normal["time"][hits] < cutoff - 60))
        valid = normal[normal["time"] >= cutoff - 59]
        assert len(valid) and valid["source_line"][0] == t["exit_line"]
    else:
        assert t["status"] == 5


def main() -> None:
    """
    機能：45デイの全口座で日中の一枚制限・時計を点検し、重複する全項目は原行照合を共有する。
    引数：なし。workの各群の既存1秒元帳、219の固定価格索引指紋を参照する。
    返り値：None。試行へ対象群と件数を記した原行照合.mdを作成する。
    """
    by_scene = defaultdict(dict)
    cutoffs = {}
    archives = VERIFY["SOURCE"]["archives"]()
    results = []
    missing = []
    for group in GROUPS:
        path = ROOT / "work" / group / "口座元帳.json"
        if not path.is_file():
            missing.append(group)
            continue
        data = json.loads(path.read_bytes())
        assert data.get("執行秒", 1) == 1
        expected = set(data["対象場"])
        assert len(expected) == 45 and all(s.endswith("_Day") and s in archives for s in expected)
        counts = Counter()
        for name, trades in data["口座再生"].items():
            wait = int(name[-2:])
            assert wait in (20, 30) and all(t["scene"] in expected for t in trades)
            counts["口座"] += 1
            last = {}
            for t in trades:
                scene = t["scene"]
                midnight = datetime.fromisoformat(scene[:10]).replace(tzinfo=JST)
                opened = midnight.replace(hour=8, minute=45).timestamp()
                cutoff = midnight.replace(hour=15, minute=30).timestamp()
                cutoffs[scene] = cutoff
                assert opened + 60 * wait <= t["request_time"] <= t["entry_time"] < cutoff - 60
                assert t["net"] is not None and t["status"] in (1, 2, 4, 5) and t["exit_horizon"] == "SESSION"
                assert t["entry_time"] <= t["exit_time"] == t["confirmed_until"] <= cutoff
                assert scene not in last or last[scene] < t["request_time"]
                last[scene] = t["exit_time"]
                fingerprint = tuple(t.get(k) for k in FIELDS)
                by_scene[scene][fingerprint] = t
                counts["建玉"] += 1
                counts[t["status"]] += 1
        results.append((group, counts))
    # ----------------------------------------
    for scene, unique in by_scene.items():
        raw = VERIFY["SOURCE"]["load_records"](*archives[scene])
        for t in unique.values():
            verify_path(raw, t, cutoffs[scene])
    unique_count = sum(len(items) for items in by_scene.values())
    total = sum((c for _, c in results), Counter())
    assert len(by_scene) == 45
    lines = ["# 1秒執行の全口座を原行に照合した結果", "",
             f"既使用{len(by_scene)}デイ、{total['口座']}口座・延べ{total['建玉']:,}建玉。各口座で時間制約・建玉の重複禁止を検算し、"
             f"場、価格の原行、損益、起動・発動、含み極値が同じ記録をまとめた{unique_count:,}経路を、"
             "指紋照合済みのラージ原順板で再計算した。費用後損益未知は0件。", "",
             "|元帳の群|口座|延べ建玉|固定利確|固定損切|場末返済|動的返済|", "|---|---:|---:|---:|---:|---:|---:|"]
    for group, c in results:
        lines.append(f"|{group}|{c['口座']}|{c['建玉']:,}|{c[1]:,}|{c[2]:,}|{c[4]:,}|{c[5]:,}|")
    lines.extend(["", "各口座で開始20分・30分後から予約可、15:29未満に新規、15:30までに清算、各決済まで次の予約なしを確認した。"
                  "一建玉につき新規側・清算側の価格と原行番号、往復1,077円控除、保有中の最高・最低含み損益とその初回時刻を照合した。"
                  "固定注文は原行上の初回到達、場末返済は15:29:01以降の最初の正常気配、動的返済は発動から1秒以上経過した"
                  "最初の正常気配に照合した。起動・発動の記録がある場合は正常な原行と秒も一致した。"
                  "この検算の対象は執行と保有経路で、各仮説のテクニカル条件自体の独立な再導出は含まない。", "",
                  "再現には上記各群の口座元帳を作成し、リポジトリ直下で次を実行する。"
                  "執行3秒・5秒の感度結果は別集計とする。[照合コード](原行を照合する.py)", "",
                  "```powershell", "python -X utf8 (Get-Item 'study/00228*/原行を照合する.py').FullName", "```", ""])
    if missing:
        lines.extend(["未生成のため未照合の群は" + "、".join(missing) + "。", ""])
    (HERE / "原行照合.md").write_text("\n".join(lines), encoding="utf8")
    print(f"{total['口座']}口座、延べ{total['建玉']}件、固有{unique_count}経路")


if __name__ == "__main__":
    main()
