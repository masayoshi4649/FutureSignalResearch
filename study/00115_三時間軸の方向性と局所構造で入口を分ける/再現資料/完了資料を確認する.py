"""115の成功参照と現在の結果文書を、金融再実行なしで確認する。"""

import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

TRIAL = Path(__file__).resolve().parents[1]
ROOT = TRIAL.parents[1]


def sha(path: Path) -> str:
    """
    機能: 明示した成果物の全bytesのSHA256を求める。
    引数: path(Path)はコード・文書・出力CSV・小metadataのファイル。
    返り値: strはSHA256。原板や価格CSVを指定しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    """
    機能: 十進数を保持して成功metadataを読む。
    引数: path(Path)は明示したJSON。
    返り値: dictは保存した内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal)


def main() -> None:
    """
    機能: 独立検査と出力・文書の結合を確認して試行完了記録を新規保存する。
    引数: review(str)とreview-sha(str)は最終read-only文書レビューのFileRef。
    返り値: None。採用・研究目標達成をfalseのまま記録する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--review-sha", required=True)
    args = parser.parse_args()
    output = TRIAL / "検査/完了記録.json"
    assert not output.exists()
    assert sha(args.review) == args.review_sha and load(args.review)["成功"] is True
    refs = {
        "成果物/結果.json": "b4d9df3568098a73d38a670a9cca7a7dc0e6b4d79fe07a8ae8dd21d9cf6293df",
        "検査/正式保存の確認.json": "c1e2aefa1bbd8e72289288eab8ea16182d9f99eeff8673271f0843482029015e",
        "検査/正式追補の確認.json": "e5ba7262d91dc982456ae8b970f8058b1da651b2cd572fc3e547884798032211",
        "検査/Viewer確認.json": "ef5443d38e755e54d77a6272ba6f813f46a8ec75f04472d2d40bf51583ba7dbf",
        "診断/同入口と費用差の結果.json": "c9ea16a9ee6f5fddeabdd9ddda3128346225976bac0a38ade20ee2220c167292",
        "診断/診断の独立照合.json": "c01987d9842b22bffbae0ce1973774b20174686dc5198f0ef520b4d2183ac321",
        "診断/11月06日の2玉と既存OHLCの対応.json": "1970dc3aaf5ad24df5aaaa5a1ae01f63002b1a255ceccb21419ecb67ef030df0",
        "設定と結果.md": "3e27641b849464ed8a532dff35cd20a552b330585c49190f990fe6bd2460f326",
        "再現資料/実行と検査の補足.md": "5b51a3579c261e949c3b8a6beac917fee80d21e731d73ff95e3da21af60e0f74",
    }
    before = {str(TRIAL / p): sha(TRIAL / p) for p in refs}
    assert before == {str(TRIAL / p): digest for p, digest in refs.items()}
    for name in refs:
        if name.endswith(".json"):
            assert load(TRIAL / name)["成功"] is True, name
    result = load(TRIAL / "成果物/結果.json")
    assert result["場数"] == 70 and result["会計数"] == 840 and len(result["場別"]) == 840
    nets = {
        "A0_C0_D0": 1126987, "A0_C0_D1": 1528603, "A0_C5_D0": -363013, "A0_C5_D1": -4397,
        "T_C0_D0": 386917, "T_C0_D1": 350917, "T_C5_D0": -49083, "T_C5_D1": -36083,
        "TR_C0_D0": 407916, "TR_C0_D1": 364916, "TR_C5_D0": -40084, "TR_C5_D1": -33084,
    }
    for key, net in nets.items():
        row = result["集計"][key]
        assert row["net_yen"] == row["positive_yen"] + row["negative_yen"] == net
        assert row["gross_yen"] - row["fee_yen"] - row["slip_yen"] == net
        assert row["entry_quantity"] == row["close_quantity"]
        assert row["fee_yen"] == row["entry_quantity"] * 77
        assert row["slip_yen"] == row["entry_quantity"] * (1000 if "_C5_" in key else 0)
        assert all(row[name] == 0 for name in ("open_buy", "open_sell", "pending_buy", "pending_sell"))
    assert len(load(TRIAL / "成果物/一覧.resources.json")["resources"]) == 840
    assert load(TRIAL / "検査/Viewer確認.json")["実GET"] == 24

    # ----------------------------------------
    # CSV正本と過去の固定記録の不変を確認する。
    csv_folder = ROOT / "outputs/01a1889f-f2af-7943-a047-543275ee9ed2/115損益CSV"
    csv_checks = []
    for name, expected, rows, columns in (
        ("候補別集計.csv", "293eb7e6cc6ea7837ec07a7ba226718a5c65cd059bed2381a6da6d7060694134", 12, 44),
        ("全セッション.csv", "8aef25abd16cf5c77023b1ddeab8e7b67b858acdd38682441456bc347c114826", 840, 40),
    ):
        path = csv_folder / name
        assert sha(path) == expected
        with path.open(encoding="utf-8-sig", newline="") as handle:
            data = list(csv.DictReader(handle))
        assert len(data) == rows and all(len(row) == columns for row in data)
        csv_checks.append({"path": str(path), "sha256": expected, "行": rows, "列": columns})
    old = {
        "study/00112_支持否定の確認と通常追尾幅の比較/検査/完了記録.json": "432fbbaf445a9d00916d927a4b87cb5992500ad585507189a71d499e498e672c",
        "study/00113_起動前の支持否定と利益保護の切替/検査/完了記録.json": "23ecc1b0c6d14fb801b74e22505cb96c3ccd183a9d50969fe6cf4d62073c8168",
        "study/00113_起動前の支持否定と利益保護の切替/検査/完了記録の追補.json": "cd6187bbf4ac665e1da94b0f62f86db3524b2edc64fc1d6062395ca179e1fdc1",
        "study/00113_起動前の支持否定と利益保護の切替/根拠/112保有区間OHLC/検査/調査の完了確認.json": "83d8382dc89181645a8a2cd88dbc2e87b94195b99abffce5afda671e30c0f9b3",
        "study/00114_順行と反転の取得確認を分ける/検査/完了記録.json": "8efdfb9cc2164d8f4de885a463946eeeb5b56ca1e399f399866f49cea83d7ed3",
    }
    assert all(sha(ROOT / path) == expected for path, expected in old.items())
    assert "/work/" in (ROOT / ".gitignore").read_text(encoding="utf-8-sig")

    # ----------------------------------------
    # 今回反映した文書だけのローカルリンクを確認する。
    documents = [ROOT / name for name in (
        "README.md", "docs/README.md", "docs/議論/README.md", "study/README.md",
        "docs/議論/PDCAの進行.md", "docs/議論/外部再調査/README.md",
        "docs/議論/外部再調査/利益保護と相場の持続性を分ける.md",
        "docs/議論/三時間軸の選別と正益後赤字を分けて読む.md",
    )] + [TRIAL / name for name in (
        "README.md", "設定と結果.md", "診断/実現差のレビュー.md",
        "診断/11月06日の2玉と保有区間OHLC.md", "再現資料/実行と検査の補足.md",
    )]
    count = 0
    for path in documents:
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8-sig")):
            target = link.split("#")[0].strip("<>")
            if not target or re.match(r"^[a-z]+://", target) or target.startswith("mailto:"):
                continue
            count += 1
            assert (path.parent / unquote(target)).exists(), (path, link)
    assert all(sha(Path(path)) == digest for path, digest in before.items())
    proof = {"試行": 115, "成功": True, "試行作業完了": True, "採用": False, "研究目標達成": False,
             "最終文書レビュー": {"path": str(args.review.resolve()), "sha256": args.review_sha},
             "成功参照": {p: {"path": str(TRIAL / p), "sha256": digest} for p, digest in refs.items()},
             "純額円": nets, "CSV": csv_checks, "旧固定記録不変": old,
             "文書SHA256": {str(p): sha(p) for p in documents}, "ローカルリンク": count, "不在": 0,
             "入力SHA256前": before, "入力SHA256後": {p: sha(Path(p)) for p in before}, "前後不変": True,
             "確認コード": {"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__).resolve())},
             "保有区間OHLC": "112の全件集計を継承し、115の11/06主2玉を同入口・同寿命で接合。115全玉をRawから再形成したとはしない。",
             "限界": ["既使用70場、未知期間の安定収益は未確認", "ラージ板によるmini約定の代理", "Viewerは840一覧IDと24GET、描画なし"],
             "未実施": {"金融再実行": 0, "Raw追加読取": 0, "価格CSV追加読取": 0, "11月09価格_損益_入力指紋読取": 0,
                         "退出後仮利益_機会損失_ROI": 0, "閾値変更": 0},
             "次の問い": "小順行後の通常の押戻しと根拠失効を当時の複数技法の状態遷移で区別する。起動前の保有判断と、費用で変わる起動/床/実退出を分けて事前固定する。"}
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"成功": True, "path": str(output), "sha256": sha(output), "研究目標達成": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
