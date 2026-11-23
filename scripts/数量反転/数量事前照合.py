"""損益を見ず、00014の数量集約と固定5分台帳の共通条件を事前照合する。"""

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00014_反転入口と観測差分量"
INPUT = ROOT/"study/00008_外部研究を共通尺度へ移して探索/入力台帳.json"


def main() -> None:
    """固定入力から数量だけを処理し、65場の旧5分集計を検算する。

    引数: なし。
    返り値: None。入口・先着・運用損益を生成しない。
    """
    path = Path(__file__).with_name("検証.py")
    spec = importlib.util.spec_from_file_location("数量事前の読取補助", path)
    driver = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = driver
    spec.loader.exec_module(driver)
    manifest = json.loads(INPUT.read_text(encoding="utf-8"))
    rows, comparisons, errors = [], [], []
    mapping = {"数量価格足数": "price_bars", "数量基準完全足数": "baseline_complete_bars",
               "数量基準不完全足数": "baseline_incomplete_bars", "直前20数量足利用可能足数": "rvol_previous_twenty_available_bars"}
    checks = 0
    for entry in manifest["entries"]:
        cache = ROOT/"work/複合検証"/entry["cache_path"]
        source = Path(manifest["source_root"])/entry["source_path"]
        stat = source.stat()
        if driver.O.sha(cache) != entry["sha256_cache"] or (stat.st_size, stat.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
            raise ValueError("固定入力の指紋が変化")
        begin, end, _, _ = driver.W.OLD.shared.legacy.session_times(entry["session"])
        start, finish = begin.timestamp(), end.timestamp()
        events, previous = [], -math.inf
        for event in driver.W.PREP.read_events(cache):
            if math.isfinite(event.now) and start <= event.now <= finish and event.now >= previous:
                events.append(event)
                previous = event.now
        for size in (1, 3, 5):
            frames = driver.W.bars_from_events(events, start, finish, size)
            _, quality = driver.Q.aggregate(events, frames, start, finish, size)
            rows.append({"場": entry["session"], **quality})
            if size != 5:
                continue
            saved = entry["volume_audit"]
            pairs = {key: (quality.get(key, 0), saved[field]) for key, field in mapping.items()}
            for new, old in (("場内採用価格時計観測数", "in_session_events"), ("数量時計同時計観測数", "volume_clock_equal_price"),
                             ("数量時計先行観測数", "volume_clock_after_price"), ("数量時計遅延観測数", "volume_clock_before_price"),
                             ("累積基準設定数", "initial_baselines"), ("正の差分採用数", "positive_delta_updates")):
                pairs[new] = quality.get(new, 0), saved["counts"].get(old, 0)
            for name, (observed, expected) in pairs.items():
                checks += 1
                if observed != expected:
                    errors.append({"場": entry["session"], "項目": name, "新集計": observed, "旧台帳": expected})
            comparisons.append({"場": entry["session"], "共通定義集計一致": all(a == b for a, b in pairs.values()),
                                "無価格枠後基準切替数": quality.get("無価格枠後基準切替数", 0)})
        print("数量事前照合 "+entry["session"], flush=True)
    output = {"確認日": "2026-11-04", "入口先着と損益の実行": False, "全件一致": not errors,
              "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
              "旧5分監査との比較": comparisons, "全尺度数量品質": rows,
              "入力台帳SHA256": driver.O.sha(INPUT), "事前照合コードSHA256": driver.O.sha(Path(__file__)),
              "対象数量コードSHA256": driver.O.sha(Path(__file__).with_name("数量.py")),
              "限界": "数量.pyを実行して旧台帳の共通集計と比較した入力ゲート。数量各足・発動の独立再実装監査とは別。無価格枠後reset・無効量完全性等の追加仕様は合成で検査し、旧定義と常に同等とはしない。"}
    (STUDY/"数量事前照合.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"全件一致": not errors, "照合項目数": checks, "不一致": errors[:8]}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
