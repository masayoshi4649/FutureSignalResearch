"""固定54場・純戦略43本・試行93コードの前後不変を検査する。"""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
MANIFEST_SHA = "b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42"


def digest(path: Path) -> str:
    """
    機能: 一つの実ファイルのSHA256を得る。
    引数: path(Path)は入力。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect() -> dict:
    """
    機能: 固定台帳の元54場だけと、実行コードを検査する。
    引数: なし。
    返り値: dictは指紋と固定件数。不一致は例外。
    """
    assert digest(MANIFEST) == MANIFEST_SHA
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = [s for s in manifest["sessions"] if "2026-09-21" <= s["id"].split("_")[0] <= "2026-10-27"]
    assert len(selected) == 54
    raw = {}
    for session in selected:
        assert len(session["files"]) == 6
        for item in session["files"].values():
            path = Path(manifest["source_root"]) / item["path"]
            assert path.stat().st_size == item["size"]
            actual = digest(path)
            assert actual == item["sha256"], path
            raw[str(path)] = actual
    pure = {}
    for relative, expected in manifest["純戦略SHA256"].items():
        path = Path(manifest["純戦略repo"]) / relative
        actual = digest(path)
        assert actual == expected, path
        pure[str(path)] = actual
    assert len(raw) == 324 and len(pure) == 43
    code_root = Path(__file__).resolve().parent
    files = sorted(p for p in code_root.rglob("*") if p.is_file() and (p.suffix in (".go", ".py") or p.name in ("go.mod", "go.sum", "README.md")))
    code = {str(path): digest(path) for path in files}
    return {"台帳SHA256": MANIFEST_SHA, "場数": 54, "原入力数": 324, "純戦略数": 43, "原入力": raw, "純戦略": pure, "コード": code}


def main() -> None:
    """
    機能: 実行前又は実行後の指紋を新規保存し、後の場合は完全一致を要求する。
    引数: --out(Path)は新規保存先、--before(Path、省略可)は実行前の証拠。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    value = collect()
    if args.before:
        previous = json.loads(args.before.read_text(encoding="utf-8"))
        assert previous == value, "実行前後で固定入力又はコードが変わりました"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"成功": True, "場数": value["場数"], "原入力数": value["原入力数"], "純戦略数": value["純戦略数"], "コード数": len(value["コード"]), "前後照合": bool(args.before)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
