"""96の入力・固定95・新金融/独立チャートを市場実行の前後で照合する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXED = ROOT / "scripts/FAR5分判断と出生一回/固定入力監査.py"
FIXED_SHA = "d59f4734b3620b56b850e1edcccd8ba65c76acdcffa24627b51058639a2b1e3e"
if hashlib.sha256(FIXED.read_bytes()).hexdigest() != FIXED_SHA:
    raise ValueError("固定95入力監査の指紋差")
SPEC = importlib.util.spec_from_file_location("固定95入力監査の再用", FIXED)
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)
BASE95 = ROOT / "study/00095_5分判断と開始30分見送り"
PROOF95 = "b7df0d9f793fca1ee9fbb489e045b927f8cf4b46e0e81a6c199920f128e4d943"


def collect() -> dict:
    """
    機能: 旧95の固定入力検査を再用し、固定95正本と96コードを別に追加する。
    引数: なし。
    返り値: dictは前後で全文一致する群別指紋。
    """
    value = OLD.collect()
    assert OLD.digest(BASE95 / "完了記録.json") == PROOF95
    fixed = OLD.load(BASE95 / "完了記録.json")
    previous = OLD.fixed_files(BASE95, fixed["自己を除く正式指紋"])
    assert len(previous) == 728
    old_code = value.pop("コード")
    assert old_code == fixed["固定金融コードSHA256"]
    here = Path(__file__).resolve().parent
    directories = (here, ROOT / "scripts/複数尺度チャートの助走")
    code = {p.relative_to(ROOT).as_posix(): OLD.digest(p) for directory in directories
            for p in sorted(directory.rglob("*")) if p.is_file()
            and (p.suffix in (".go", ".py") or p.name in ("go.mod", "go.sum", "README.md"))}
    condition = OLD.load(ROOT / "study/00096_5分枠の順行反転と現在数量/条件.json")
    assert code == condition["コードSHA256"], "96固定コードが変更"
    value.update({"試行": 96, "固定95完了SHA256": PROOF95, "固定95コード": old_code,
                  "固定95正本": previous, "コード": code})
    return value


def main() -> None:
    """
    機能: 96の市場実行前後の一致証拠を新規保存する。
    引数: --out(Path)、--before(Path、省略可)は新規先と実行前証拠。
    返り値: None。不一致や上書きは例外。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    value = collect()
    if args.before:
        assert value == OLD.load(args.before), "96の固定入力/旧正本/コードが前後で変化"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"成功": True, "場数": 54, "原入力": 324, "旧95正本": 728,
                      "96コード数": len(value["コード"]), "前後検査": bool(args.before)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
