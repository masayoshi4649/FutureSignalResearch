"""114専用Viewerの全一覧と11/06日夜24資源を、実約定・費用後純額へ照合する。"""

from concurrent.futures import ThreadPoolExecutor
import sys
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TRIAL = Path(sys.argv[1]).resolve()
ROOT = TRIAL.parents[1]
BASE = "http://127.0.0.1:8098"
SESSIONS = {"2026-11-06_Day", "2026-11-06_Night"}


def sha(path: Path) -> str:
    """機能: 明示ファイルの全バイト指紋を確認する。

    引数: path(Path)はmetadata・実約定・コードだけ。
    返り値: strはSHA256。Raw・価格CSV・Nativeは渡さない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    """機能: 認証対象JSONを十進数で復元する。

    引数: path(Path)は正式metadata。
    返り値: dictは元数値を保持したJSON。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal)


def request(route: str, payload: dict | None = None) -> tuple:
    """機能: 専用8098の許可されたAPIだけを要求する。

    引数: route(str)、payload(dict|None)はinfo・一覧load・固定data。
    返り値: tuple[dict,str]は十進数保持の応答と全本文SHA。
    """
    assert route in ("/api/info", "/api/catalogs/load") or route.startswith("/api/data?")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    with urlopen(Request(BASE + route, data=body, headers={"Content-Type": "application/json"}), timeout=60) as response:
        raw = response.read()
        digest = hashlib.sha256(raw).hexdigest()
        assert response.headers.get("x-chart-data-sha256", digest) == digest
        return json.loads(raw, parse_float=Decimal), digest


def check(item: tuple) -> dict:
    """機能: 一資源の全実約定とAPI現金増減、最後のflatを照合する。

    引数: item(tuple)はcatalogID・資源・正本純額。
    返り値: dictは限定された取得証拠。描画や次正常最初性は検査しない。
    """
    catalog_id, resource, expected = item
    path = TRIAL / "成果物" / resource["pnl_path"]
    original = path.read_bytes()
    lines = [json.loads(line, parse_float=Decimal) for line in original.decode("utf-8").splitlines() if line.strip()]
    query = urlencode({"catalog": catalog_id, "resource": resource["id"], "width": 1, "interval": "raw", "price": "last"})
    value, digest = request("/api/data?" + query)
    assert len(value["events"]) == len(lines)
    held, net = {}, Decimal(0)
    for index, (row, event) in enumerate(zip(lines, value["events"]), 1):
        for name in ("type", "price", "qty", "position_id", "method_id"):
            assert row[name] == event[name], (resource["id"], name)
        assert event["sequence"] == index
        assert event["timestamp_ms"] == round(datetime.fromisoformat(row["timestamp"]).timestamp() * 1000)
        cost = Decimal(row.get("fee_yen", 0)) + Decimal(row.get("slippage_yen", 0))
        kind, pid, quantity = row["type"], row["position_id"], row["qty"]
        if kind in ("LongN", "ShortN"):
            assert pid not in held
            held[pid] = {"side": 1 if kind == "LongN" else -1, "price": row["price"], "quantity": quantity}
            delta = -cost
        else:
            assert kind in ("LongR", "ShortR") and pid in held
            position = held[pid]
            assert position["side"] == (1 if kind == "LongR" else -1) and 0 < quantity <= position["quantity"]
            delta = (row["price"] - position["price"]) * position["side"] * quantity * 100 - cost
            position["quantity"] -= quantity
            if position["quantity"] == 0:
                del held[pid]
        assert event["realized_delta_yen"] == delta, resource["id"]
        net += delta
    assert not held and net == expected
    summary = value["summary"]
    assert summary["long_qty"] == summary["short_qty"] == summary["unrealized_pnl_yen"] == 0
    assert summary["realized_pnl_yen"] == expected
    assert path.read_bytes() == original
    return {"id": resource["id"], "純額円": float(net), "全実約定行": len(lines), "応答SHA256": digest}


def main() -> None:
    """機能: 840一覧と事前固定24資源をHTTP取得して前後不変を記録する。

    引数: CLIの第1引数(str)は試行の場所、第2引数(str)は独立結果SHA。専用8098が起動済みであること。
    返り値: None。証拠を新規保存し、既存証拠・旧Viewerは変更しない。
    """
    output = TRIAL / "検査/Viewer確認.json"
    assert not output.exists()
    catalog = TRIAL / "成果物/一覧.resources.json"
    result = TRIAL / "成果物/結果.json"
    assert len(sys.argv) == 3 and sha(result) == sys.argv[2], "114独立結果の期待SHA256"
    resources, data = load(catalog)["resources"], load(result)
    assert len(resources) == 840 and len({r["id"] for r in resources}) == 840
    selected = [r for r in resources if r["session"] in SESSIONS]
    assert len(selected) == 24
    before = {str(p): sha(p) for p in (catalog, result, Path(__file__).resolve())}
    for resource in selected:
        p = TRIAL / "成果物" / resource["pnl_path"]
        before[str(p)] = sha(p)
    expected = {(r["key"], r["session"]): r["net_yen"] for r in data["場別"]}
    info, info_sha = request("/api/info")
    assert Path(info["resource_root"]).resolve() == TRIAL
    assert Path(info["data_root"]).resolve() == (ROOT.parent / "JP_OSE_Data/future").resolve()
    loaded, catalog_sha = request("/api/catalogs/load", {"path": "成果物/一覧.resources.json"})
    assert {r["id"] for r in loaded["resources"]} == {r["id"] for r in resources}
    with ThreadPoolExecutor(max_workers=4) as pool:
        details = list(pool.map(check, [(loaded["catalog_id"], r, expected[(r["method_id"], r["session"])]) for r in selected]))
    after = {name: sha(Path(name)) for name in before}
    assert before == after
    proof = {"成功": True, "試行": 114, "一覧": 840, "実GET": 24,
             "範囲": "全一覧IDと11/06日夜24資源の全実約定・費用後純額・残0。全840GETや描画/目視確認ではない",
             "server": BASE, "info応答SHA256": info_sha, "一覧応答SHA256": catalog_sha,
             "details": details, "前後不変": True, "前": before, "後": after,
             "他Viewer操作": 0, "ローカルRaw_CSV_Native読取": 0, "11月09アクセス": 0, "金融再実行": False}
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"成功": True, "一覧": 840, "実GET": 24, "証拠SHA256": sha(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
