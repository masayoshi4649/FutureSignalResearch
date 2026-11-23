"""113完了後の表現明確化・再現CLI・固定要求の追加だけを追補検査する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote


def sha(path: Path) -> str:
    """機能: 明示ファイルのSHA256を求める。

    引数: path(Path)は文書・検査証拠・小さい固定要求。
    返り値: strは全バイトSHA。市場原板とNativeは読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 既存完了と現在文書を接続し、追補を新規保存する。

    引数: CLI第1引数(str)は正式113の場所。
    返り値: None。金融・CSV・既存検査証拠を変更しない。
    """
    assert len(sys.argv) == 2
    trial = Path(sys.argv[1]).resolve()
    root = trial.parents[1]
    original = trial / "検査/完了記録.json"
    output = trial / "検査/完了記録の追補.json"
    assert not output.exists()
    assert sha(original) == "23ecc1b0c6d14fb801b74e22505cb96c3ccd183a9d50969fe6cf4d62073c8168"
    prior = json.loads(original.read_text(encoding="utf-8"))
    changed = []
    for name, expected in prior["最終参照SHA256"].items():
        path = Path(name)
        actual = sha(path)
        if actual != expected:
            assert path == trial / "README.md", name
            changed.append({"path": name, "旧SHA256": expected, "新SHA256": actual})
    assert len(changed) == 1
    supplement = trial / "再現資料/実行と検査の補足.md"
    requests = {}
    for stage, expected in (
        ("first2", "87a87b4e7ee450ec2155521e5cbd3e2f12cfe8ecc925218b69a78914d27b3cac"),
        ("base54", "f216854325035dcfbe867b33c9fff46fe7d5504049594d84b9629eda4932b604"),
        ("full70", "c5f9f48fbf5f03f3ce8c46a2c46ba2837af81b6ad3041acfaa4f1326d7c1c11f"),
    ):
        path = trial / f"再現資料/独立保存要求_{stage}.json"
        assert sha(path) == expected
        requests[str(path)] = expected
    docs = [trial / "README.md", supplement]
    count = 0
    for path in docs:
        for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith(("https:", "http:", "#", "mailto:")):
                continue
            target_path = (path.parent / unquote(target.strip("<> ").split("#", 1)[0])).resolve()
            assert target_path == output or target_path.exists(), (str(path), target)
            count += 1
    proof = {
        "試行": 113, "成功": True, "確認日時": datetime.now().astimezone().isoformat(),
        "元完了記録": {"path": str(original), "sha256": sha(original)},
        "変更点": "READMEの主C0D0/P100→P50明確化と再現補足・追補へのリンク。固定金融/集計/CSV/Viewer/既存完了は不変",
        "変更文書": changed, "再現補足": {"path": str(supplement), "sha256": sha(supplement)},
        "独立保存要求の原文一致": requests, "当該二文書ローカルリンク": count,
        "元完了の他参照は現SHA一致": True,
        "追加検査コード": {"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__).resolve())},
        "金融再実行": False, "原板読取": 0, "Native本文読取": 0, "11月09読取": 0,
        "研究目標達成": False, "採用": False,
    }
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"成功": True, "参照不変": True, "リンク": count, "追補SHA256": sha(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
