"""113の保存済み成果物と文書を照合し、金融再実行なしで完了を記録する。"""

from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote


def sha(path: Path) -> str:
    """機能: 明示ファイルのSHA256を求める。

    引数: path(Path)は正式成果物または文書。
    返り値: strは全バイトのSHA256。原板・価格CSV・Native本文は対象外。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    """機能: 正式JSONを数値精度を保って読む。

    引数: path(Path)は検査証拠または集計結果。
    返り値: dictはJSON。小数はDecimalとして保持する。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal)


def check_links(paths: list[Path]) -> int:
    """機能: 対象Markdownの通常のローカルリンクが存在するか調べる。

    引数: paths(list[Path])は対象文書。外部URLと頁内アンカーは除外する。
    返り値: intは検査したリンク数。リンク先本文や原板は読まない。
    """
    count = 0
    for path in paths:
        text = path.read_text(encoding="utf-8-sig")
        for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", text):
            if target.startswith(("http:", "https:", "#", "mailto:", "plugin:")):
                continue
            target = unquote(target.strip("<> ").split("#", 1)[0])
            assert target and (path.parent / target).exists(), (str(path), target)
            count += 1
    return count


def main() -> None:
    """機能: 金融・独立・正式保存・CSV・Viewerの証拠と結果を最終接続する。

    引数: CLI第1引数(str)は113正式フォルダ。条件変更・市場再生は行わない。
    返り値: None。新規の検査/完了記録.jsonを作る。研究目標達成と採用はfalse。
    """
    assert len(sys.argv) == 2
    trial = Path(sys.argv[1]).resolve()
    root = trial.parents[1]
    output = trial / "検査/完了記録.json"
    assert not output.exists()
    fixed = {
        "検査/condition.json": "065cb5ebc894627cb70cf6f3d8f0add7698532af269cb92c2dd3decf4051a138",
        "検査/正式保存の確認.json": "17604a16d23514e67a8b2e2309ca43a9394d0b3fb810682445311f69206caa9b",
        "成果物/結果.json": "6492ae50b8fbf5b3dbe61d4295147119619e7ecbfd7cb09cbe39bc267663852b",
        "成果物/保存会計の確認.json": "aaa203a0afc7c7c08f9faa049cbddbf6636242ffa9a1356bb2bdb754dd2daafa",
        "検査/Viewer確認.json": "dfcfc044263854f338c937469d469fecf123cce3db0ce0d8af21a7eeaecca7f6",
        "根拠/112保有区間OHLC/検査/調査の完了確認.json": "83d8382dc89181645a8a2cd88dbc2e87b94195b99abffce5afda671e30c0f9b3",
    }
    csv_root = root / "outputs/01a1889f-f2af-7943-a047-543275ee9ed2/113損益CSV"
    csv_fixed = {
        "候補別集計.csv": "287964e711ff2f86e1978abc9e72018238ff350b5ed5227d7095ca5f6ab029de",
        "全セッション.csv": "e0102b9cf0daf6e608478d69320a249ccd3d82a5a7dfdb63368c876ddcfc81dc",
        "CSVの独立再読.json": "0b83f03e0a5c0660be5f7363619968654b6e64105ec704491f4e463eab97412b",
    }
    guards = {trial / name: value for name, value in fixed.items()}
    guards.update({csv_root / name: value for name, value in csv_fixed.items()})
    old = root / "study/00112_支持否定の確認と通常追尾幅の比較/検査/完了記録.json"
    guards[old] = "432fbbaf445a9d00916d927a4b87cb5992500ad585507189a71d499e498e672c"
    for path, expected in guards.items():
        assert sha(path) == expected, str(path)

    # ----------------------------------------
    saved = load(trial / "検査/正式保存の確認.json")
    assert saved["成功"] and saved["前後不変"]
    checked = 0
    native_skipped = 0
    for entry in saved["同bytes成果物"]:
        if entry["relative"].startswith("成果物_金融/"):
            native_skipped += 1
            continue
        path = (trial / entry["relative"]).resolve()
        assert path.is_relative_to(trial)
        assert path.stat().st_size == entry["bytes"] and sha(path) == entry["sha256"]
        checked += 1
    for name in ("Native台帳", "ZIP", "コード所在索引", "CSV所在", "入力参照"):
        ref = saved[name]
        assert sha(Path(ref["path"])) == ref["sha256"]
    native = load(trial / "成果物_金融/Native参照台帳.json")
    assert native["成功"] and len(native["Native"]) == 70
    assert native["元54認証再用"] == 54 and native["追加16再生"] == 16

    # ----------------------------------------
    result = load(trial / "成果物/結果.json")
    expected_net = {
        "S0": [2146987, 2489603, 977987, 1328603],
        "W100": [1114987, 1552603, -414013, 38603],
        "P100": [1126987, 1528603, -363013, -4397],
        "P50": [298987, 691372, -693013, -198397],
        "E100": [896987, 1349603, -594013, -178397],
        "E50": [71987, 517372, -924013, -374397],
    }
    costs = ("C0_D0", "C0_D1", "C5_D0", "C5_D1")
    assert result["成功"] and result["会計数"] == 1680 and len(result["集計"]) == 24
    for policy, values in expected_net.items():
        for cost, expected in zip(costs, values):
            item = result["集計"][f"{policy}_{cost}"]
            assert item["net_yen"] == expected
            assert all(item[name] == 0 for name in ("open_buy", "open_sell", "pending_buy", "pending_sell"))
    pairs = (("P100", "P50"), ("P100", "E100"), ("P50", "E50"), ("E100", "E50"))
    assert all(result["集計"][f"{after}_{cost}"]["net_yen"] < result["集計"][f"{before}_{cost}"]["net_yen"] for before, after in pairs for cost in costs)
    viewer = load(trial / "検査/Viewer確認.json")
    assert viewer["成功"] and viewer["前後不変"] and viewer["一覧"] == 1680 and viewer["実GET"] == 48
    assert viewer["11月09アクセス"] == viewer["他Viewer操作"] == 0
    csv_proof = load(csv_root / "CSVの独立再読.json")
    assert csv_proof["成功"] and csv_proof["数値比較数"] == 42768

    # ----------------------------------------
    docs = [root / name for name in (
        "README.md", "docs/README.md", "docs/議論/README.md", "study/README.md", "docs/議論/PDCAの進行.md",
        "docs/議論/低い利益起動と支持失効だけでは改善しなかった比較.md",
        "docs/議論/利益起動前の支持失効を判別する.md",
        "docs/議論/保有区間OHLCで分けた利益後赤字の原因.md",
    )] + [trial / "README.md", trial / "設定と結果.md", csv_root / "README.md"]
    links = check_links(docs)
    table = (trial / "設定と結果.md").read_text(encoding="utf-8")
    method_text = table.split("## 設定明細", 1)[0]
    method_rows = [line for line in method_text.splitlines() if re.match(r"\| [A-Z]\d\d \|", line)]
    assert len(method_rows) == 56, len(method_rows)
    assert all(len(line.split("|")) == 13 for line in method_rows)
    assert len(re.findall(r"^\| S\d\d \|", table, re.M)) == 22
    assert len(re.findall(r"^\| R\d\d \|", table, re.M)) == 24
    guards.update({p: sha(p) for p in docs})
    guards[Path(__file__).resolve()] = sha(Path(__file__).resolve())
    for path, expected in guards.items():
        assert sha(path) == expected
    proof = {
        "試行": 113, "成功": True, "確認日時": datetime.now().astimezone().isoformat(),
        "試行の金融と報告の完了": True, "ユーザー依頼のOHLC調査完了": True,
        "研究目標達成": False, "採用": False, "全70会計": 1680, "旧112金融対照": 840,
        "保存済み同bytes成果物の今回再読": checked, "Native本文の今回再読": 0,
        "Native関連の再読除外": native_skipped, "Nativeの根拠": "既完了の正式保存検査と台帳SHA。金融・原板の再走査ではない",
        "CSV二点": True, "CSV数値再読の既存証拠": 42768, "Viewer一覧": 1680, "Viewer実GET": 48,
        "手法": 56, "尺度": 9, "設定": 22, "複合評価": 24, "対象Markdownリンク確認数": links,
        "全16対照で新側の純額悪化": True, "追加16主条件全6政策赤字": True,
        "条件変更": False, "金融再実行": False, "原板読取": 0, "11月09読取": 0,
        "固定112とOHLC完了の指紋一致": True, "最終参照SHA256": {str(p): value for p, value in guards.items()},
        "次の問い": "順行と反転の取得確認、取得後の状態遷移、逐次BBOと確定足の時計差、構造距離に対する数量を分ける。次案の改善額は未確認",
    }
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"成功": True, "保存成果物再読": checked, "ローカルリンク": links, "完了SHA256": sha(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
