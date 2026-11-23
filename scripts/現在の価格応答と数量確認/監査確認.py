"""84の6会計ラベル接続・独立保護・政策未知分類を市場なし人工で確認する。"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


def load(path: Path, name: str) -> object:
    """
    機能: 検査部品をCLIを実行せず読み込む。
    引数: path (Path) はコード、name (str) はモジュール名。
    返り値: object は読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect(raw: object, folder: Path, entry: dict, result: dict) -> dict:
    """
    機能: 一時保存した人工会計を人工原板へ照合する。
    引数: raw (object)、folder (Path)、entry/result (dict) は規範と人工入力。
    返り値: dict は独立照合結果。
    """
    with tempfile.TemporaryDirectory(prefix="84検査_", dir=folder) as temp:
        (Path(temp) / (entry["id"] + ".json")).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return raw.inspect_one((temp, str(folder), entry))


def main() -> None:
    """
    機能: 10手計算場面のS0G1を6入口ラベルへ結び、破損と分類を検査する。
    引数: --fixtures/--out (Path) は固定83人工根と新規証拠。
    返り値: None。未検出・差・既存出力があれば例外で終了する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("既存人工証拠は上書きしません")
    here = Path(__file__).resolve().parent
    raw = load(here / "原板監査.py", "raw84_artificial")
    summary = load(here / "集計.py", "summary84_artificial")
    viewer = load(here / "表示監査.py", "viewer84_artificial")
    fixed = load(here.parent / "定時の現在根拠と部分利益保護/監査確認.py", "fixture81_for84")
    checks = []
    cases = sorted(args.fixtures.iterdir())
    assert len(cases) == 10
    for folder in cases:
        source = json.loads((folder / "2026-09-21_Day.json").read_text(encoding="utf-8"))
        result = {**source, "books": {key: deepcopy(source["books"]["S0G1_D" + key[-1]]) for key in raw.KEYS}}
        before = json.dumps(result, ensure_ascii=False, sort_keys=True)
        market = folder / "book.jsonl.gz"
        entry = {"id": result["session"], "contract": "人工限月", "files": {"NK225_book": {"path": market.name, "size": market.stat().st_size, "sha256": hashlib.sha256(market.read_bytes()).hexdigest()}}}
        normal = inspect(raw, folder, entry, result)
        assert normal["不一致数"] == 0, (folder.name, normal["不一致"])
        assert before == json.dumps(result, ensure_ascii=False, sort_keys=True)
        for book in result["books"].values():
            assert summary.load_base().cash_check(book)["現金円"] == book["metrics"]["net_pnl_yen"]
        checks.append({"場面": folder.name, "正常会計": 6, "照合項目数": normal["照合項目数"]})
        mutations = (
            ("約定費用", lambda r: r["books"]["C0G1_D0"]["trades"][0].update(fee_yen=0)),
            ("S0構造創作", lambda r: r["books"]["C1G1_D1"]["lots"][0].update(structure_active=True)),
            ("確定純額", lambda r: r["books"]["A0G1_D0"]["lots"][0].update(net_pnl=1)),
            ("金融モード差", lambda r: r["books"]["C0G1_D1"].update(mode="S1G1")),
            ("外入口漏れ", lambda r: r["books"].pop("C1G1_D0")),
        )
        for label, mutate in mutations:
            bad = deepcopy(result)
            mutate(bad)
            try:
                audit = inspect(raw, folder, entry, bad)
            except ValueError:
                detected = True
            else:
                detected = audit["不一致数"] > 0
            assert detected, (folder.name, label)
            checks.append({"場面": folder.name, "破損": label, "検出": True})
        if folder.name == "大順行_1":
            checks += fixed.viewer_fake(viewer, folder, result["books"]["A0G1_D0"])
    # ----------------------------------------
    # 保有・処理中・新規の優先を保ち、非占有の入口未知だけを別集計します。
    actions = ("待ち", "待ち", "待ち", "保有継続", "処理中", "新規要求", "判定不能")
    synthetic = {"books": {"C0G1_D0": {"decisions": [{"at": i, "action": a} for i, a in enumerate(actions)]}}, "grid_decisions": [
        {"at": i, "clock_allowed": i != 2, "policies": {"C0": {"required_unknown": i != 1}}} for i in range(len(actions))]}
    saved = deepcopy(synthetic)
    assert summary.policy_actions(synthetic, "C0G1_D0") == {"判定不能": 2, "待ち": 2, "保有継続": 1, "処理中": 1, "新規要求": 1}
    assert synthetic == saved
    checks.append({"方針分類": "未知・既知不成立・時計禁止・占有優先の7枠", "入力不変": True})
    value = {"成功": True, "系列": len(checks), "正常会計": 60, "人工": checks, "本物原板": 0, "新売買再生": 0, "実API": 0,
        "コードSHA256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (here / "原板監査.py", here / "集計.py", here / "表示監査.py", Path(__file__))}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "系列", "正常会計", "本物原板", "新売買再生")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
