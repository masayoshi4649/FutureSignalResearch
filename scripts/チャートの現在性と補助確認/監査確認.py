"""82の4会計への監査接続を、固定81の手計算人工で確認する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile


def load(path: Path, name: str) -> object:
    """
    機能: CLIを動かさず、明示した検査部品だけを読み込む。
    引数: path (Path) はPythonソース、name (str) は独立モジュール名。
    返り値: object は検査用モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    """
    機能: 鏡像・分割・悪化・遅延・EOFと保存値破壊の検出を確認する。
    引数: なし。自作原板と保存値だけを作業域に一時作成する。
    返り値: None。正常不一致又は破損未検出は非0終了する。
    """
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    fixed = load(here.parent / "定時の現在根拠と部分利益保護/監査確認.py", "fixture81_for82")
    raw = load(here / "原板監査.py", "raw82_artificial")
    viewer = load(here / "表示監査.py", "viewer82_artificial")
    summary = load(here / "集計.py", "summary82_artificial")
    checks = []
    with tempfile.TemporaryDirectory(prefix="82監査人工_", dir=root / "work") as temp:
        for side in (1, -1):
            for scenario in ("成功", "悪化", "pending", "終端未約定"):
                folder = Path(temp) / f"{side}_{scenario}"
                entry, result = fixed.pending_end(folder, side) if scenario == "終端未約定" else fixed.fixture(folder, side, scenario)
                result["books"] = {k: v for k, v in result["books"].items() if k in raw.KEYS}
                good = fixed.raw_check(raw, folder, entry, result)
                assert good["不一致数"] == 0, good["不一致"]
                checks.append({"方向": side, "場面": scenario, "照合": good["照合項目数"], "差": 0})
                if scenario == "成功":
                    for book in result["books"].values():
                        assert summary.load_base().cash_check(book)["現金円"] == 2800
                    checks += fixed.viewer_fake(viewer, folder, result["books"]["B0G1_D0"])
                    for field, replacement in (("whole_flag", False), ("harvest_filled", 0), ("cash_floor_active", False)):
                        broken = deepcopy(result)
                        broken["books"]["B0G1_D0"]["lots"][0][field] = replacement
                        bad = fixed.raw_check(raw, folder, entry, broken)
                        assert bad["不一致数"] > 0, field
                        checks.append({"方向": side, "破損": field, "検出": bad["不一致数"]})
                    extra = deepcopy(result)
                    extra["books"]["B0G0_D0"] = extra["books"]["B0G1_D0"]
                    try:
                        fixed.raw_check(raw, folder, entry, extra)
                    except AssertionError:
                        checks.append({"方向": side, "対象外会計拒否": True})
                    else:
                        raise AssertionError("対象外会計を許容した")
    print(json.dumps({"成功": True, "系列": len(checks), "人工": checks, "本物原板": 0, "新売買再生": 0, "実API": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
