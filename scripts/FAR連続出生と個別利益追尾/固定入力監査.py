"""固定94の原入力・93依存・純戦略・Actorコードを実行前後で照合する。"""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "study/00093_元三手法のmini連続再現と費用"
MANIFEST = ROOT / "study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
MANIFEST_SHA = "b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42"
PROOF_SHA = "e811571a876f3fdc2f5ba7c09b3906c84db9e380ef89c24b920e5c3f199a2a37"


def digest(path: Path) -> str:
    """
    機能: 実ファイルの内容指紋を得る。
    引数: path(Path)は入力。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    """
    機能: UTF8の正本JSONを読む。
    引数: path(Path)は保存値。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def collect() -> dict:
    """
    機能: 固定54場だけと、変更しない93/純戦略/94実装を検査する。
    引数: なし。
    返り値: dictは群別の実指紋。不一致は例外。
    """
    assert digest(MANIFEST) == MANIFEST_SHA and digest(BASE / "完了記録.json") == PROOF_SHA
    manifest = load(MANIFEST)
    selected = [s for s in manifest["sessions"] if "2026-09-21" <= s["id"].split("_")[0] <= "2026-10-27"]
    assert len(selected) == 54
    raw = {}
    for scene in selected:
        assert len(scene["files"]) == 6
        for item in scene["files"].values():
            path = Path(manifest["source_root"]) / item["path"]
            actual = digest(path)
            assert path.stat().st_size == item["size"] and actual == item["sha256"], path
            raw[str(path)] = actual
    pure = {}
    for relative, expected in manifest["純戦略SHA256"].items():
        path = Path(manifest["純戦略repo"]) / relative
        actual = digest(path)
        assert actual == expected, path
        pure[str(path)] = actual
    expected_core = dict(load(BASE / "条件.json")["コードSHA256"])
    correction = load(BASE / "集計形式訂正.json")
    expected_core[correction["変更ファイル"]] = correction["新SHA256"]
    core93 = {name: digest(ROOT / name) for name in expected_core}
    assert core93 == expected_core and len(core93) == 11
    fixed = load(BASE / "完了記録.json")["自己を除く正式指紋"]
    saved = {name: digest(BASE / Path(name)) for name in fixed}
    assert saved == fixed and len(saved) == 313
    here = Path(__file__).resolve().parent
    code = {str(p.relative_to(ROOT)): digest(p) for p in sorted(here.rglob("*")) if p.is_file() and (p.suffix in (".go", ".py") or p.name in ("go.mod", "go.sum", "README.md"))}
    return {"試行": 94, "台帳SHA256": MANIFEST_SHA, "基準93完了SHA256": PROOF_SHA, "場数": 54,
            "原入力": raw, "純戦略": pure, "固定93コード": core93, "固定93正本": saved, "コード": code}


def main() -> None:
    """
    機能: 新規の前後検査証拠を保存する。
    引数: --out(Path)は新規先、--before(Path、省略可)は前の証拠。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    value = collect()
    assert len(value["原入力"]) == 324 and len(value["純戦略"]) == 43
    if args.before:
        assert value == load(args.before), "前後で入力・固定基準・実装が変わりました"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"成功": True, "場数": 54, "原入力数": 324, "純戦略数": 43, "旧93コード数": 11,
                      "旧93正本数": 313, "94コード数": len(value["コード"]), "前後検査": bool(args.before)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
