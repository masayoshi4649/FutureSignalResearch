"""83の手計算人工80会計を原板・表示の独立規範へ結ぶ。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


def load(path: Path, name: str) -> object:
    """
    機能: CLI実行をせず明示した独立監査の部品を読み込む。
    引数: path (Path) はソース、name (str) は独立モジュール名。
    返り値: object は検査用モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect(raw: object, folder: Path, entry: dict, result: dict) -> dict:
    """
    機能: 自作結果を別一時根へ保存して原板へ照合する。
    引数: raw (object)、folder (Path)、entry/result (dict) は独立規範と人工値。
    返り値: dict は不一致を含む照合結果。
    """
    with tempfile.TemporaryDirectory(prefix="検査_", dir=folder) as temp:
        (Path(temp) / (entry["id"] + ".json")).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return raw.inspect_one((temp, str(folder), entry))


def main() -> None:
    """
    機能: 正常10場面・80会計と破損拒否、表示の数値差と通信未完を確認する。
    引数: --fixtures (Path) はcmd/fixtureの新規人工根。
    返り値: None。不一致や破損未検出は非0終了する。実市場とAPIは読まない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", required=True, type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    raw = load(here / "原板監査.py", "raw83_artificial")
    summary = load(here / "集計.py", "summary83_artificial")
    viewer = load(here / "表示監査.py", "viewer83_artificial")
    fixed = load(here.parent / "定時の現在根拠と部分利益保護/監査確認.py", "fixture81_for83")
    cases = sorted(args.fixtures.iterdir())
    assert len(cases) == 10
    checks = []
    for folder in cases:
        market = folder / "book.jsonl.gz"
        result = json.loads((folder / "2026-09-21_Day.json").read_text(encoding="utf-8"))
        entry = {"id": result["session"], "contract": "人工限月", "files": {"NK225_book": {"path": market.name, "size": market.stat().st_size, "sha256": hashlib.sha256(market.read_bytes()).hexdigest()}}}
        normal = inspect(raw, folder, entry, result)
        assert normal["不一致数"] == 0, (folder.name, normal["不一致"])
        checks.append({"場面": folder.name, "正常照合": normal["照合項目数"], "不一致": 0})
        for book in result["books"].values():
            checked = summary.load_base().cash_check(book)
            assert checked["現金円"] == book["metrics"]["net_pnl_yen"]
        if folder.name == "大順行_1":
            checks += fixed.viewer_fake(viewer, folder, result["books"]["S0G1_D0"])
        # ----------------------------------------
        # 当時価格線、床、数量、利益配分の保存改変を別々に拒否する。
        mutations = (
            ("構造床", lambda v: v["books"]["S1G1_D0"]["lots"][0].update(structure_floor=999)),
            ("構造集計", lambda v: v["books"]["S1G1_D0"]["metrics"].update(structure_hit_lots=999)),
            ("要求時価格線", lambda v: v["grid_decisions"][0]["structure_anchor"].update(price=999)),
            ("G2架空部分", lambda v: v["books"]["S0G2_D0"]["lots"][0].update(harvest_order_id="架空")),
            ("返済片構造", lambda v: v["books"]["S1G1_D0"]["closed"][0].update(structure_first_hit_index=999)),
            ("約定費用", lambda v: v["books"]["S0G1_D0"]["trades"][0].update(fee_yen=0)),
        )
        for name, mutate in mutations:
            changed = deepcopy(result)
            mutate(changed)
            bad = inspect(raw, folder, entry, changed)
            assert bad["不一致数"] > 0, (folder.name, name)
            checks.append({"場面": folder.name, "破損": name, "検出": bad["不一致数"]})
    print(json.dumps({"成功": True, "系列": len(checks), "正常会計": 80, "人工": checks, "本物原板": 0, "新売買再生": 0, "実API": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
