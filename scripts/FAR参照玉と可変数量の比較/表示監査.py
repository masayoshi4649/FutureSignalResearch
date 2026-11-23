# 停止86派生元SHA256: 5b4b03e0d7cf69dca032cce435d93270f6dc323243d93e789e6a82e20ee82093

"""87の全264資源をViewer数値APIへ結び、約定と最終純額を照合する。"""

# 固定85派生元SHA256: a549dab64789a9dbfaa6c4d5b71aab48805dadb08cf36cc294b2a9190e8b88ed

import argparse

# 派生元84表示監査SHA256: e62cd82ac206c04df1081327b3ef81eafaf0000336568d0fbf521e2bd558f7e6

# 派生元83のSHA256: 68e698bb88f9e81b6569b05e0fa544d295e77dd9eb6754f355d9609aec17af7b
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode


def load_base() -> object:
    """
    機能: 固定80の数値API・所有イベント照合部品を読取で読み込む。
    引数: なし。
    返り値: object は既存のAPI照合モジュール。
    """
    path = Path(__file__).resolve().parent.parent / "FAR後期15分移植/表示照合.py"
    spec = importlib.util.spec_from_file_location("fixed80_viewer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_base()


def digest(path: Path) -> str:
    """
    機能: 小型入力の前後不変を確認する指紋を得る。
    引数: path (Path) は入力。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_one(task: tuple) -> dict:
    """
    機能: 一資源のAPIを取得し独立約定と比較する。
    引数: task (tuple) はURL・解決済資源・約定・純額・一覧。
    返り値: dict は完了又は通信/数値差。通信失敗を差0としない。
    """
    url, resolved, trades, net, catalog = task
    audit = BASE.Audit()
    try:
        data, raw, headers = BASE.fetch_json("GET", url)
        events = BASE.trade_expectations(trades, 10)
        audit.money("約定独立純額", sum(event["realized_delta_yen"] for event in events), net)
        BASE.compare_data(data, raw, headers, resolved, events, net, audit, catalog)
        return {"id": resolved["id"], "完了": True, "API費用後円": data["summary"].get("realized_pnl_yen"),
            "原純額円": net, "約定片数": len(events), "本文SHA256": hashlib.sha256(raw).hexdigest(),
            "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
            "警告数": len(data["quality"]["warnings"]), "APIエラー": None}
    except Exception as error:
        return {"id": resolved["id"], "完了": False, "照合項目数": audit.count, "不一致数": audit.bad,
            "不一致": audit.examples, "APIエラー": {"型": type(error).__name__, "説明": str(error)}}


def main() -> None:
    """
    機能: 並列読取で264資源を検査し、全件成功だけを成功と保存する。
    引数: --catalog/--result/--out (Path)、--url (str)、--workers (int)。
    返り値: None。不一致又は通信未完なら証拠を保存して終了1。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8092")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("既存表示監査は上書きしません")
    assert 1 <= args.workers <= 16
    catalog_path, result_path = args.catalog.resolve(), args.result.resolve()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    resources = catalog["resources"]
    assert result["場数"] == 66 and len(resources) == 264 and len({r["id"] for r in resources}) == 264
    expected = {f"87_{row['key']}_{row['session']}": row for row in result["場別"]}
    assert len(expected) == 264 and set(expected) == {r["id"] for r in resources}
    paths = [catalog_path, result_path]
    local = {}
    for resource in resources:
        assert (resource["product"], resource["point_value"], resource["pnl_basis"]) == ("NK225micro", 10, "net")
        path = (catalog_path.parent / resource["pnl_path"]).resolve()
        assert path.is_relative_to(catalog_path.parent)
        paths.append(path)
        local[resource["id"]] = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    before = {str(path): digest(path) for path in paths}
    base = args.url.rstrip("/")
    info, _, _ = BASE.fetch_json("GET", base + "/api/info")
    resource_root = Path(info["resource_root"]).resolve()
    assert catalog_path.is_relative_to(resource_root)
    loaded, _, _ = BASE.fetch_json("POST", base + "/api/catalogs/load", {"path": str(catalog_path.relative_to(resource_root))})
    loaded_by_id = {r["id"]: r for r in loaded["resources"]}
    assert len(loaded_by_id) == 264 and set(loaded_by_id) == set(expected)
    tasks = []
    for resource in resources:
        resolved = {**resource, "pnl_path": str((catalog_path.parent / resource["pnl_path"]).resolve()),
            "market_path": str((Path(info["data_root"]) / resource["market_path"]).resolve())}
        assert loaded_by_id[resource["id"]] == resolved
        query = urlencode({"catalog": loaded["catalog_id"], "resource": resource["id"], "width": 1, "interval": "raw", "price": "last"})
        tasks.append((base + "/api/data?" + query, resolved, local[resource["id"]], expected[resource["id"]]["metrics"]["net_pnl_yen"], catalog_path))
    rows = []
    with ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(check_one, task) for task in tasks]
        for future in as_completed(futures):
            rows.append(future.result())
            if len(rows) % 32 == 0:
                print(f"表示監査 {len(rows)}/264", flush=True)
    rows.sort(key=lambda row: row["id"])
    after = {str(path): digest(path) for path in paths}
    errors = [row for row in rows if row["APIエラー"]]
    differences = sum(row["不一致数"] for row in rows)
    success = len(rows) == 264 and not errors and differences == 0 and before == after
    value = {"試行": 87, "成功": success, "完了資源": sum(row["完了"] for row in rows), "予定資源": 264,
        "照合項目数": sum(row["照合項目数"] for row in rows), "不一致数": differences, "APIエラー": errors,
        "入力不変": before == after, "入力SHA256前": before, "入力SHA256後": after,
        "監査コードSHA256": digest(Path(__file__)), "一覧SHA256": digest(catalog_path), "結果SHA256": digest(result_path),
        "資源": rows, "Viewer設定": info, "Viewer再起動": 0, "新売買再生": 0}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: value[k] for k in ("成功", "完了資源", "照合項目数", "不一致数")}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
