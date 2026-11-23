"""80の原板・確定足と純戦略ソースを実行前に固定する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path: Path) -> str:
    """
    機能: 入力ファイルを変更せずSHA256を計算する。
    引数: path (Path) は実ファイル。
    返り値: str は16進SHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(repo: Path, *args: str) -> str:
    """
    機能: 指定repoのGit情報を読取専用で取得する。
    引数: repo (Path) はrepo根、args (str) はGit引数。
    返り値: str はUTF-8標準出力。
    """
    return subprocess.check_output(["git", "-C", str(repo), *args], encoding="utf-8").strip()


def main() -> None:
    """
    機能: 既使用66場と二市場の6ファイルずつを固定する。
    引数: コマンド引数の--out (Path) は未作成の台帳先。
    返り値: None。既存台帳は上書きしない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source_ledger = root / "study/00028_基準線復帰と上位一目の方向/入力台帳.json"
    old = json.loads(source_ledger.read_text(encoding="utf-8"))
    data_root = Path(old["source_root"])
    sessions = []
    for entry in old["entries"]:
        files = {}
        for ref in ("NK225", "TOPIX"):
            for key, name in (("book", "book.jsonl.gz"), ("candle_60", "candle_1min.csv"), ("candle_300", "candle_5min.csv")):
                rel = Path(ref) / entry["session"] / name
                path = data_root / rel
                files[f"{ref}_{key}"] = {"path": rel.as_posix(), "sha256": digest(path), "size": path.stat().st_size}
        if len(entry["contract_codes"]) != 1:
            raise ValueError("参照NK台帳の限月が一意でない")
        sessions.append({"id": entry["session"], "contract": entry["contract_codes"][0], "files": files})
    sibling = root.parent / "SessionTradeExecuter"
    code = {}
    for folder in ("strategy", "e01", "rules"):
        for path in sorted((sibling / "internal" / folder).glob("*.go")):
            if not path.name.endswith("_test.go"):
                code[path.relative_to(sibling).as_posix()] = digest(path)
    for name in ("go.mod", "go.sum"):
        code[name] = digest(sibling / name)
    value = {
        "source_root": str(data_root), "sessions": sessions,
        "固定日": "2026-11-07", "全66場既使用": True,
        "元台帳": source_ledger.relative_to(root).as_posix(), "元台帳SHA256": digest(source_ledger),
        "FAR参照commit": "cf0717daa1eed78759f78a428bce50129e7f705b",
        "純戦略repo": str(sibling), "純戦略commit": git(sibling, "rev-parse", "HEAD"),
        "純戦略差分一覧": git(sibling, "status", "--short", "--", "internal/strategy", "internal/e01", "internal/rules", "go.mod", "go.sum"),
        "純戦略SHA256": code,
        "制約": "実注文アプリ・API・設定は開かない。原板の価格時計を受信時計の代理にする。時計欠損行は配置不能として除外し、当時の受信遅延は復元できない。",
        "接続確認": [s["id"] for s in sessions[:2]],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"場数": len(sessions), "入力数": sum(len(s["files"]) for s in sessions), "純戦略ファイル数": len(code), "台帳SHA256": digest(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
