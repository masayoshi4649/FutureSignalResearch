"""85Goの非0人工12場面を新しい保持帯原板規範へ接続する。"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


def load(path: Path, name: str) -> object:
    """
    機能: CLIを起動せず独立規範を読み込む。
    引数: path (Path)、name (str) はコードとモジュール名。
    返り値: object は読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect(raw: object, folder: Path, entry: dict, result: dict) -> dict:
    """
    機能: 保存改変を元人工と分離して原板へ照合する。
    引数: raw (object)、folder (Path)、entry/result (dict) は規範と人工。
    返り値: dict は照合結果。
    """
    with tempfile.TemporaryDirectory(prefix="85規範_", dir=folder) as temporary:
        (Path(temporary) / (entry["id"] + ".json")).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return raw.inspect_one((temporary, str(folder), entry))


def main() -> None:
    """
    機能: 正常48会計と出典・床・hit・理由・費用破損を市場なしで検査する。
    引数: --fixtures/--out (Path) はGo人工根と新規証拠。
    返り値: None。正常差又は破損未検出は例外。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("既存人工証拠は上書きしません")
    root = Path.cwd()
    source = root / "scripts/保持帯の返済側固定否定"
    raw = load(source / "原板監査.py", "raw85_initial")
    summary = load(source / "集計.py", "summary85_initial")
    fixtures = args.fixtures.resolve()
    checks = []
    cases = sorted(p for p in fixtures.iterdir() if p.is_dir())
    assert len(cases) == 12
    inputs_before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in fixtures.rglob("*.json")}
    normal_accounts = 0
    for folder in cases:
        result_path = folder / "85.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        quotes = json.loads((folder / "人工観測.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="85原板_", dir=root / "work/85準備") as materialized:
            material = Path(materialized)
            assert material.resolve().is_relative_to((root / "work/85準備").resolve())
            market = material / "book.jsonl.gz"
            by_line = {v["quote"]["line"]: v["quote"] for v in quotes}
            with gzip.open(market, "wt", encoding="utf-8", newline="\n") as stream:
                for line in range(1, max(by_line) + 1):
                    row = {"Symbol": "人工限月"}
                    if line in by_line:
                        q = by_line[line]
                        row = {"Symbol": "人工限月", "CurrentPriceTime": datetime.fromtimestamp(q["time"], timezone.utc).isoformat(), "CurrentPrice": q["last"], "Buy1": {"Price": q["bid"], "Qty": 10}, "Sell1": {"Price": q["ask"], "Qty": 10}}
                        for level in range(2, 11):
                            row[f"Buy{level}"] = {"Price": q["bid"] - 10 * (level - 1), "Qty": 10}
                            row[f"Sell{level}"] = {"Price": q["ask"] + 10 * (level - 1), "Qty": 10}
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            entry = {"id": result["session"], "contract": "人工限月", "files": {"NK225_book": {"path": market.name, "size": market.stat().st_size, "sha256": hashlib.sha256(market.read_bytes()).hexdigest()}}}
            result["quality"] = {"NK225": {"lines": max(by_line), "clock_missing": max(by_line) - len(by_line), "outside": 0, "backward": 0, "bad_last": 0, "bad_quote": 0, "accepted": len(by_line), "contracts": ["人工限月"]}}
            normal = inspect(raw, material, entry, result)
            assert normal["不一致数"] == 0, (folder.name, normal["不一致"])
            mutations = make_mutations(result)
            for label, changed in mutations:
                bad = inspect(raw, material, entry, changed)
                assert bad["不一致数"] > 0, (folder.name, label)
                checks.append({"場面": folder.name, "破損": label, "検出": bad["不一致数"]})
        assert normal["不一致数"] == 0, (folder.name, normal["不一致"])
        normal_accounts += len(result["books"])
        checks.append({"場面": folder.name, "正常会計": 4, "照合項目数": normal["照合項目数"]})

    # ----------------------------------------
    # 金融側の保有を優先し、入口の未知を別の方針分類へ重ねます。
    actions = ("待ち", "待ち", "待ち", "保有継続", "処理中", "新規要求", "判定不能")
    synthetic = {"books": {"H1G1_D0": {"decisions": [{"at": i, "action": a} for i, a in enumerate(actions)]}}, "grid_decisions": [
        {"at": i, "clock_allowed": i != 2, "policies": {"C0": {"required_unknown": i != 1}}} for i in range(len(actions))]}
    untouched = deepcopy(synthetic)
    assert summary.policy_actions(synthetic, "H1G1_D0") == {"判定不能": 2, "待ち": 2, "保有継続": 1, "処理中": 1, "新規要求": 1}
    assert synthetic == untouched
    checks.append({"方針分類": "7枠で未知/既知不成立/時計禁止/占有を分離", "入力不変": True})
    inputs_after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in fixtures.rglob("*.json")}
    assert inputs_before == inputs_after and normal_accounts == 48
    value = {"成功": True, "正常会計": normal_accounts, "入力前後不変": True, "入力SHA256": inputs_before, "系列": len(checks), "内容": checks, "本物原板": 0, "新売買再生": 0,
        "範囲": "Go手製quoteを物理行へ展開した原板規範検査。人工timerは全予定枠ではないため25/49枠を要求するcash_checkの人工完了とは呼ばない。",
        "コードSHA256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source / "原板監査.py", source / "集計.py", Path(__file__))}}
    out = args.out
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "正常会計", "系列", "本物原板", "新売買再生")}, ensure_ascii=False))


def make_mutations(result: dict) -> list:
    """
    機能: 保持帯・費用の保存破損を正常値から独立複写する。
    引数: result (dict) は一人工の保存結果。
    返り値: list はラベルと破損複写。無取引は空。
    """
    if not result["books"]["H1G1_D0"]["lots"]:
        return []
    mutations = (
            ("固定停止価格", lambda r: r["grid_decisions"][0]["hold_anchor"].update(stop_price=r["grid_decisions"][0]["hold_anchor"]["stop_price"] + 10)),
            ("H1活性床", lambda r: r["books"]["H1G1_D0"]["lots"][0].update(hold_floor=999)),
            ("H0架空活性", lambda r: r["books"]["H0G1_D0"]["lots"][0].update(hold_active=True)),
            ("hit物理行", lambda r: r["books"]["H1G1_D0"]["lots"][0].update(hold_first_hit_line=999)),
            ("費用", lambda r: r["books"]["H1G1_D0"]["trades"][0].update(fee_yen=0)),
            ("保持帯集計", lambda r: r["books"]["H1G1_D1"]["metrics"].update(hold_hit_lots=999)),
    )
    output = []
    for label, mutate in mutations:
        changed = deepcopy(result)
        mutate(changed)
        output.append((label, changed))
    return output


if __name__ == "__main__":
    main()
