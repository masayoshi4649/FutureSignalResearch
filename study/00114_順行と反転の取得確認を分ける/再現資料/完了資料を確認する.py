"""114の最終文書、成功metadata、CSV指紋と再現追補を接続する。"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote


def ref(path: Path, expected: str | None = None) -> dict:
    """機能: 指定した正式成果物のSHA256を確認する。

    引数: path(Path)は対象、expected(str|None)は任意の期待指紋。
    返り値: dictは絶対pathと指紋。Raw/Nativeの本文には使用しない。
    """
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert expected is None or actual == expected, str(path)
    return {"path": str(path.resolve()), "sha256": actual}


def load(path: Path) -> dict:
    """機能: 正式な小metadataまたは保存結果を読む。

    引数: path(Path)はJSONの所在。
    返り値: dictは解析結果。金融計算・原板再生は行わない。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def links(path: Path) -> list[dict]:
    """機能: 編集対象Markdownのローカルリンクの実在を確認する。

    引数: path(Path)はMarkdownの所在。
    返り値: list[dict]は確認したリンク。URL先や見出し名は検査しない。
    """
    rows = []
    for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", path.read_text(encoding="utf-8")):
        target = target.strip().strip("<>")
        if target.startswith(("http:", "https:", "mailto:", "#", "plugin:")):
            continue
        local = unquote(target.split("#", 1)[0])
        if not local:
            continue
        resolved = (path.parent / local).resolve()
        assert resolved.exists(), f"{path}: {target}"
        rows.append({"target": target, "exists": True})
    return rows


def main() -> None:
    """機能: 成功成果物と文書を最終照合し、試行完了を新規記録する。

    引数: なし。Rootが実行済みの114正式成功だけを参照する。
    返り値: None。未知期間・原板・Native・価格CSVの再読は行わない。
    """
    root = next(parent for parent in Path(__file__).resolve().parents if (parent / "AGENTS.md").is_file())
    study = root / "study/00114_順行と反転の取得確認を分ける"
    output = study / "検査/完了記録.json"
    assert not output.exists(), "完了記録の上書きは禁止"
    specifications = {
        "検査/condition.json": "b0bf17c4bcd435dcca13da12995a11a9c6f5617f86a27ca2f0994528a3823167",
        "検査/market.json": "2589160f6e86e618a64372a52cad0abd76e19e5b49d607897f758604600a0b18",
        "成果物/結果.json": "28006bfa74cee9ac93e85496590c4b93479bc0c7d31080c3b2f1eeb938d9fb1c",
        "成果物/保存会計の確認.json": "301c2b4359484ba2e4a4748dae4c069201ed03c959ff10be452531ad200a34b7",
        "検査/entry_check.json": "5e5bc4e9ceeba8a1522becc5842a7dc259f94d18b8d527447d1f912496f15b1f",
        "検査/正式保存の確認.json": "cb17015535835c75b4dfd53f04d4482e895494509225086ce34dfbc5059a3423",
        "検査/Viewer確認.json": "85aa97cd0495cb7c467d4928dfeaa720376af68417749c0f709b476d44ad3527",
        "検査/csv_check.json": "1ea6ab25e9e6fee6a400369bdc130c598d790d992e7b464bffd1801121f5c7f5",
        "再現資料/コードと実使用実行物.zip": "237bb1f59d123def6b1bb63374d396a0544c10c3d15b2e61651ea77b99d09cde",
        "再現資料/コード所在索引.json": "16310f3796ac8f4385f20ca3c5a4a7f6ce9124ca95249fd9341e6488b788e124",
        "成果物_金融/Native参照台帳.json": "93627b2b4348f2d1e86d52f2d24946f3c36aded3664c4733e219389f9b8c6f5e",
        "設定と結果.md": "245c0b228bff58137e714bb7c318a38d5dd1c0ec9ba3863fd7c3dc325e500a8b",
        "診断/要求時技法の文脈/正本の独立確認.json": "7379b4498abb7e5f835b723d092f4f458422eb5c8ba2eaec55608a23d52bc191",
        "診断/要求時技法の文脈/EMA同足の数式確認.json": "8d80c45c68ae3e7bc49c7f6144bd0be8099b290e03f53389b3845c8056a09b60",
    }
    authenticated = {name: ref(study / name, expected) for name, expected in specifications.items()}
    result = load(study / "成果物/結果.json")
    saved = load(study / "成果物/保存会計の確認.json")
    market = load(study / "検査/market.json")
    entry = load(study / "検査/entry_check.json")
    formal = load(study / "検査/正式保存の確認.json")
    viewer = load(study / "検査/Viewer確認.json")
    csv_check = load(study / "検査/csv_check.json")
    assert result["成功"] and result["場数"] == 70 and result["会計数"] == 840
    assert saved["全Source111同体"] and saved["全残玉予約0"] and saved["不一致数"] == 0
    assert saved["旧113全金融比較"] == 280
    assert market["success"] and market["reused_sessions"] == 54 and market["replayed_sessions"] == 16
    assert market["all_reference113_equal"] and market["all_source111_equal"] and market["unchanged"]
    assert not market["historical_saved_events_equal"] and not market["all_original_signal_full_json_equal"]
    assert entry["成功"] and entry["会計数"] == 840 and len(entry["場別"]) == 70
    assert formal["成功"] and formal["同梱entry数"] == 107 and formal["既正式参照数"] == 437
    assert len(formal["同bytes成果物"]) == 958 and all(row["同bytes"] for row in formal["同bytes成果物"])
    assert viewer["成功"] and viewer["一覧"] == 840 and viewer["実GET"] == 24
    assert csv_check["成功"] and csv_check["場別行数"] == 840 and csv_check["候補数"] == 12
    assert csv_check["0取引行数"] == 116 and csv_check["数値比較数"] == 32252
    for row in result["場別"]:
        assert all(row[key] == 0 for key in ("open_buy", "open_sell", "pending_buy", "pending_sell"))
    assert len(result["場別"]) == 840 and len({row["session"] for row in result["場別"]}) == 70

    # ----------------------------------------
    expected_net = {
        "A0": [1126987, 1528603, -363013, -4397],
        "T": [437127, 438127, 55127, 113127],
        "TR": [269739, 287739, -156261, -80261],
    }
    costs = ("C0_D0", "C0_D1", "C5_D0", "C5_D1")
    loss_rates = {}
    for candidate, amounts in expected_net.items():
        for cost, amount in zip(costs, amounts):
            key = candidate + "_" + cost
            aggregate = result["集計"][key]
            assert aggregate["net_yen"] == amount
            assert sum(row["net_yen"] for row in result["場別"] if row["key"] == key) == amount
        main_book = result["集計"][candidate + "_C0_D0"]
        denominator = main_book["whole_positive_positions"]
        numerator = main_book["whole_positive_closed_negative"]
        loss_rates[candidate] = {"正益経験玉": denominator, "最終赤字玉": numerator, "条件付き率": numerator / denominator}
    assert [(loss_rates[key]["正益経験玉"], loss_rates[key]["最終赤字玉"]) for key in expected_net] == [(477, 178), (112, 44), (132, 53)]
    context = load(study / "診断/要求時技法の文脈/正本の独立確認.json")
    assert context["成功"] and context["同体を確認した対照延べ共通入口"] == 1648
    assert context["独立検査"]["対応台帳全件"] == 1 and context["全Native"] == 70
    table_check = load(study / "検査/設定表の結合確認.json")
    assert table_check["成功"] and table_check["検査"]["56手法"] == 56
    assert table_check["検査"]["尺度"] == 9 and table_check["検査"]["設定数"] == 23 and table_check["検査"]["結果行数"] == 12
    csv_root = root / "outputs/01a1889f-f2af-7943-a047-543275ee9ed2/114損益CSV"
    csv_refs = {name: ref(csv_root / name, digest) for name, digest in (
        ("候補別集計.csv", "de1cab06ee857c23736aec14da20695346c70bdefcf14e2fef5dda7dcf35a57d"),
        ("全セッション.csv", "9f48e7cfef1bfe403e7b7a1fafc243a1fa5f628259548ae1cfbf00d6326ad70a"),
    )}
    old_refs = {}
    for relative, digest in (
        ("study/00112_支持否定の確認と通常追尾幅の比較/検査/完了記録.json", "432fbbaf445a9d00916d927a4b87cb5992500ad585507189a71d499e498e672c"),
        ("study/00113_起動前の支持否定と利益保護の切替/検査/完了記録.json", "23ecc1b0c6d14fb801b74e22505cb96c3ccd183a9d50969fe6cf4d62073c8168"),
        ("study/00113_起動前の支持否定と利益保護の切替/検査/完了記録の追補.json", "cd6187bbf4ac665e1da94b0f62f86db3524b2edc64fc1d6062395ca179e1fdc1"),
        ("study/00113_起動前の支持否定と利益保護の切替/根拠/112保有区間OHLC/検査/調査の完了確認.json", "83d8382dc89181645a8a2cd88dbc2e87b94195b99abffce5afda671e30c0f9b3"),
    ):
        old_refs[relative] = ref(root / relative, digest)

    # ----------------------------------------
    supplement = load(root / "work/114再現補足/正式追補の確認.json")
    assert supplement["成功"] and len(supplement["コピー一覧"]) == 7
    supplement_refs = {}
    for item in supplement["コピー一覧"]:
        supplement_refs[item["relative"]] = ref(Path(item["target"]["path"]), item["target"]["sha256"])
    docs = [
        "README.md", "docs/README.md", "study/README.md", "docs/議論/README.md", "docs/議論/PDCAの進行.md",
        "docs/technical-analysis/README.md", "docs/technical-analysis/指標/移動平均線.md", "docs/technical-analysis/組み合わせ/README.md",
        "docs/technical-analysis/組み合わせ/同じEMAの傾きと価格位置の重複.md", "docs/議論/順行と反転の入口を分けた実現収支.md",
        "docs/議論/順行と反転の取得確認を保護から分離する.md", "docs/議論/外部再調査/README.md",
        "docs/議論/外部再調査/順行の水準と反転の回復イベントを分ける.md",
        "study/00114_順行と反転の取得確認を分ける/README.md", "study/00114_順行と反転の取得確認を分ける/設定と結果.md",
        "study/00114_順行と反転の取得確認を分ける/再現資料/実行と検査の補足.md",
        "outputs/01a1889f-f2af-7943-a047-543275ee9ed2/114損益CSV/README.md",
    ]
    document_refs = {relative: ref(root / relative) for relative in docs}
    checked_links = {relative: links(root / relative) for relative in docs}
    self_ref = ref(Path(__file__))
    record = {
        "試行": 114, "成功": True, "確認日時": datetime.now().astimezone().isoformat(),
        "試行の金融と報告の完了": True, "研究目標達成": False, "採用": False,
        "金融条件変更": False, "金融再実行": False, "原板読取": False, "Native本文読取": False, "11月09読取": False,
        "全70会計": 840, "旧113金融対照": 280, "全残玉予約0": True,
        "正式保存済み同bytes成果物": 958, "正式新規コードentry": 107, "旧正式コード参照": 437,
        "正式保存後の追加資料": supplement_refs, "CSV二点": csv_refs,
        "CSV数値再読の既確認": {"値": 32252, "未定義空欄": 1348, "0取引場行": 116},
        "Viewer一覧": 840, "Viewer実GET": 24, "Viewer描画確認": False,
        "主費用の正益経験後赤字率": loss_rates,
        "利益保護率改善": False, "同入口延べ照合": 1648,
        "最終参照": authenticated, "旧固定成果物": old_refs,
        "文書": document_refs, "対象Markdownリンク確認数": sum(map(len, checked_links.values())),
        "リンク切れ": [], "確認コード": self_ref,
        "次の問い": "5/15/30分の背景・方向の強さ・価格構造を役割別に固定比較する。起動前の正益後赤字は別の保有問題として残す。",
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"成功": True, "記録": ref(output), "リンク数": record["対象Markdownリンク確認数"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
