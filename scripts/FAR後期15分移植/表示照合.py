"""80の正式198資源をViewer数値APIと照合し、原資料を変更しない。"""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
MODES = ("F0", "P1", "T1")


class ViewerError(RuntimeError):
    """通信又はViewer応答の失敗を保存数値の不一致から分離する例外。"""

    def __init__(self, kind: str, url: str, message: str):
        """失敗種別とURLを保持する。

        引数: kind/url/message(str)は分類・接続先・説明。
        返り値: None。
        """
        super().__init__(message)
        self.kind, self.url = kind, url


class Audit:
    """比較数と数値差を記録し、通信失敗を差0へ読み替えない。"""

    def __init__(self):
        """比較台帳を初期化する。

        引数: なし。
        返り値: None。
        """
        self.count, self.bad, self.examples = 0, 0, []

    def check(self, name: str, actual: object, expected: object) -> None:
        """離散値と全文辞書を比較する。

        引数: name(str)は項目、actual/expected(object)は値。
        返り値: None。差は最大20例を残す。
        """
        self.record(name, actual, expected, actual == expected)

    def record(self, name: str, actual: object, expected: object, equal: bool) -> None:
        """一つの比較を記録する。

        引数: name(str)は項目、actual/expected(object)は値、equal(bool)は一致判定。
        返り値: None。
        """
        self.count += 1
        if not equal:
            self.bad += 1
            if len(self.examples) < 20:
                self.examples.append({"項目": name, "実値": json_safe(actual), "期待値": json_safe(expected)})

    def money(self, name: str, actual: object, expected: object) -> None:
        """未知を補完せず、十進表記で円数値を比較する。

        引数: name(str)は項目、actual/expected(object)は有限円値。
        返り値: None。bool/null/非有限値は不一致とする。
        """
        valid = all(type(v) in (int, float) and math.isfinite(v) for v in (actual, expected))
        self.record(name, actual, expected, valid and Decimal(str(actual)) == Decimal(str(expected)))


# ----------------------------------------
def json_safe(value: object) -> object:
    """失敗診断の集合や非有限値をJSON保存可能にする。

    引数: value(object)は診断値。
    返り値: objectは有限JSON互換値。不正数値を0へ変換しない。
    """
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if type(value) is float and not math.isfinite(value):
        return repr(value)
    if value is None or type(value) in (str, int, float, bool):
        return value
    return str(value)


def sha(path: Path) -> str:
    """小型の原資料内容の指紋を求める。

    引数: path(Path)は一覧・結果・約定又はコード。
    返り値: strはSHA256。市場原板は直接読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_json(method: str, url: str, payload: dict | None = None) -> tuple[dict, bytes, dict]:
    """ローカルViewerのJSONだけを読み、失敗を分類する。

    引数: method/url(str)はHTTP手段とURL、payload(dict|None)は一覧パス。
    返り値: tuple[dict,bytes,dict]はJSON・一時本文・ヘッダ。本文を保存しない。
    """
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, method=method, headers={"Accept-Encoding": "identity", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ViewerError("応答上限", url, "数値JSONが32MiBを超えた")
            headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as error:
        message = error.read(2048).decode("utf-8", errors="replace")
        raise ViewerError("HTTP", url, str(error.code) + ":" + message) from error
    except (URLError, TimeoutError, ConnectionError, OSError) as error:
        raise ViewerError("通信", url, str(error)) from error
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ViewerError("JSON応答", url, str(error)) from error
    if not isinstance(value, dict):
        raise ViewerError("応答schema", url, "最上位JSONが辞書でない")
    return value, raw, headers


def trade_expectations(trades: list[dict], point_value: int | float) -> list[dict]:
    """約定片から所有別にViewerの確定増減を別算する。

    引数: trades(list[dict])は保存約定、point_value(int|float)は商品倍率。
    返り値: list[dict]は全約定イベントの独立期待値。
    """
    owners, expected = {}, []
    for sequence, trade in enumerate(trades, 1):
        kind, pid, n = trade["type"], trade["position_id"], trade["qty"]
        assert kind in ("LongN", "LongR", "ShortN", "ShortR") and type(n) is int and n > 0
        price = Decimal(str(trade["price"]))
        side = 1 if kind.startswith("Long") else -1
        delta = -Decimal(str(trade["fee_yen"]))
        if kind.endswith("N"):
            assert pid not in owners, "実所有IDの再新規"
            owners[pid] = {"side": side, "quantity": n, "entry": price}
        else:
            owner = owners[pid]
            assert owner["side"] == side and owner["quantity"] >= n
            delta += Decimal(side * n) * Decimal(str(point_value)) * (price - owner["entry"])
            owner["quantity"] -= n
        expected.append({"timestamp_ms": datetime.fromisoformat(trade["timestamp"]).timestamp() * 1000,
            "sequence": sequence, "type": kind, "price": trade["price"], "qty": n,
            "position_id": pid, "method_id": trade["method_id"], "realized_delta_yen": float(delta)})
    assert all(owner["quantity"] == 0 for owner in owners.values()), "一覧の実所有が未解消"
    return expected


def compare_data(data: dict, raw: bytes, headers: dict, resource: dict, expected_events: list[dict], net: int | float, audit: Audit, catalog_path: Path) -> None:
    """一資源のAPI終状態と全イベントを保存値へ照合する。

    引数: data/raw/headersはdict/bytes/dictのAPI応答、resource(dict)は資源、expected_events(list)は期待約定、netは円値、audit(Audit)は比較台帳、catalog_path(Path)は原一覧。
    返り値: None。未知の数量や利益を0へ補完しない。
    """
    prefix = resource["id"] + ":"
    audit.check(prefix + "本文SHA", headers.get("x-chart-data-sha256"), hashlib.sha256(raw).hexdigest())
    audit.check(prefix + "資源全文", data["resource"], resource)
    for field, path in (("pnl", resource["pnl_path"]), ("market", resource["market_path"]), ("catalog", catalog_path)):
        audit.check(prefix + "参照原本:" + field, str(Path(data["files"][field]).resolve()), str(Path(path).resolve()))
    summary = data["summary"]
    for name in ("long_qty", "short_qty"):
        audit.check(prefix + name + "型", type(summary.get(name)).__name__, "int")
        audit.check(prefix + name, summary.get(name), 0)
    audit.money(prefix + "最終費用後損益", summary.get("realized_pnl_yen"), net)
    audit.money(prefix + "最終含み", summary.get("unrealized_pnl_yen"), 0)
    columns = data["state_columns"]
    assert data["states"] and len(set(columns)) == len(columns), "表示終状態又は列が不正"
    audit.check(prefix + "終状態列数", len(data["states"][-1]), len(columns))
    last = dict(zip(columns, data["states"][-1]))
    for name in ("long_qty", "short_qty"):
        audit.check(prefix + "終状態型:" + name, type(last.get(name)).__name__, "int")
        audit.check(prefix + "終状態:" + name, last.get(name), 0)
    audit.money(prefix + "終状態:費用後", last.get("realized_pnl_yen"), net)
    audit.money(prefix + "終状態:含み", last.get("unrealized_pnl_yen"), 0)
    events = data["events"]
    audit.check(prefix + "約定片数", len(events), len(expected_events))
    for actual, expected in zip(events, expected_events):
        for name in ("sequence", "type", "qty", "position_id", "method_id"):
            audit.check(prefix + "約定:" + name, actual.get(name), expected[name])
        for name in ("sequence", "qty"):
            audit.check(prefix + "約定型:" + name, type(actual.get(name)).__name__, "int")
        audit.money(prefix + "約定:価格", actual.get("price"), expected["price"])
        audit.money(prefix + "約定:費用込み増減", actual.get("realized_delta_yen"), expected["realized_delta_yen"])
        actual_time = actual.get("timestamp_ms")
        valid = type(actual_time) in (int, float) and math.isfinite(actual_time)
        audit.record(prefix + "約定:時計ms", actual_time, expected["timestamp_ms"], valid and abs(actual_time - expected["timestamp_ms"]) <= .001)


# ----------------------------------------
def run(catalog_path: Path, result_path: Path, base: str = "http://127.0.0.1:8092", transport=None, progress: bool = True) -> dict:
    """正式80一覧を登録し、全198資源を読取照合する。

    引数: catalog_path/result_path(Path)は正式一覧と結果、base(str)はローカルURL、transport(callable|None)は人工だけの通信代替、progress(bool)は小型進捗。
    返り値: dictは成否・数値差・通信失敗を分離したproof。既存カタログや原資料を変更しない。
    """
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("ローカルViewerのhttp URLだけを指定する")
    catalog_path, result_path = catalog_path.resolve(), result_path.resolve()
    catalog, result = [json.loads(path.read_text(encoding="utf-8")) for path in (catalog_path, result_path)]
    resources = catalog["resources"]
    expected = {(row["session"], row["mode"]): row for row in result["場別"]}
    sessions = {row["session"] for row in result["場別"]}
    assert result["場数"] == len(sessions) == 66 and len(expected) == len(result["場別"]) == 198
    assert set(expected) == {(session, mode) for session in sessions for mode in MODES}
    assert set(result["比較"]) == set(MODES)
    for mode in MODES:
        assert sum(Decimal(str(row["net_pnl_yen"])) for row in result["場別"] if row["mode"] == mode) \
            == Decimal(str(result["比較"][mode]["費用後損益円"])), "正本の場別と案別の差"
    assert len(resources) == len({row["id"] for row in resources}) == 198 and catalog["path_base"] == "catalog"
    assert {(row["session"], row["method_id"]) for row in resources} == set(expected)
    files = [catalog_path, result_path, Path(__file__).resolve()]
    local_trades = {}
    for resource in resources:
        assert (resource["symbol"], resource["product"], resource["point_value"], resource["pnl_format"], resource["pnl_basis"]) == ("NK225", "NK225micro", 10, "trades", "net")
        path = (catalog_path.parent / resource["pnl_path"]).resolve()
        assert path.is_relative_to(catalog_path.parent), "約定参照が正式出力外"
        files.append(path)
        local_trades[resource["id"]] = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    before = {str(path): sha(path) for path in files}
    request = fetch_json if transport is None else transport
    audit = Audit()
    completed, errors, info, catalog_id = [], [], None, None
    try:
        info, _, _ = request("GET", base + "/api/info")
        resource_root = Path(info["resource_root"]).resolve()
        assert catalog_path.is_relative_to(resource_root), "一覧がViewer resource_root外"
        loaded, _, _ = request("POST", base + "/api/catalogs/load", {"path": str(catalog_path.relative_to(resource_root))})
        catalog_id = loaded["catalog_id"]
        loaded_map = {row["id"]: row for row in loaded["resources"]}
        audit.check("API198資源全集合", set(loaded_map), {row["id"] for row in resources})
        audit.check("API198資源数", len(loaded["resources"]), 198)
        audit.check("API一覧原本", str(Path(loaded["path"]).resolve()), str(catalog_path))
        for resource in resources:
            resolved = {**resource, "pnl_path": str((catalog_path.parent / resource["pnl_path"]).resolve()),
                "market_path": str((Path(info["data_root"]) / resource["market_path"]).resolve())}
            audit.check(resource["id"] + ":登録メタ全文", loaded_map.get(resource["id"]), resolved)
            query = urlencode({"catalog": catalog_id, "resource": resource["id"], "width": 1, "interval": "raw", "price": "last"})
            url = base + "/api/data?" + query
            data, raw, headers = request("GET", url)
            events = trade_expectations(local_trades[resource["id"]], resource["point_value"])
            net = expected[resource["session"], resource["method_id"]]["net_pnl_yen"]
            audit.money(resource["id"] + ":約定別算の費用後", sum(row["realized_delta_yen"] for row in events), net)
            compare_data(data, raw, headers, resolved, events, net, audit, catalog_path)
            completed.append({"id": resource["id"], "session": resource["session"], "mode": resource["method_id"],
                "最終数量": {"買い": data["summary"].get("long_qty"), "売り": data["summary"].get("short_qty")},
                "API費用後円": data["summary"].get("realized_pnl_yen"), "正本費用後円": net,
                "約定片数": len(data["events"]), "数値本文SHA256": hashlib.sha256(raw).hexdigest(), "品質警告数": len(data["quality"]["warnings"])})
            if progress and len(completed) % 18 == 0:
                print(json.dumps({"表示照合進捗": len(completed), "全資源": 198}, ensure_ascii=False), flush=True)
    except ViewerError as error:
        errors.append({"種類": error.kind, "URL": error.url, "説明": str(error)[:2000]})
    except (KeyError, TypeError, ValueError, AssertionError) as error:
        errors.append({"種類": "応答schema又は入力結合", "説明": str(error)[:2000]})
    after = {str(path): sha(path) for path in files}
    audit.check("全原資料の前後指紋", after, before)
    complete = len(completed) == 198 and not errors
    return json_safe({"試行": 80, "確認日時": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "全件一致": complete and audit.bad == 0, "全資源検証完了": complete, "予定資源数": 198,
        "数値取得完了資源数": len(completed), "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "APIエラー": errors, "数値一致判定": "完了" if complete else "未完了。未取得分を差0としない",
        "Viewer設定": info, "catalog_id": catalog_id, "一覧SHA256": before[str(catalog_path)], "結果SHA256": before[str(result_path)],
        "入力SHA256前": before, "入力SHA256後": after, "入力不変": before == after, "資源別": completed,
        "新売買再生": 0, "原板直接読取": 0, "原板又はAPI本文複写": 0, "Viewer停止又は再起動": False,
        "限定": "全198数値APIの終数量・費用後累積損益・全約定と終状態。画像の目視品質や実商品約定可能性の証明ではない"})


def self_test() -> dict:
    """架空198資源と通信代替だけで正常・数値差・通信未完を検査する。

    引数: なし。
    返り値: dictは人工成否。実Viewer登録と本物結果読取は0。
    """
    with tempfile.TemporaryDirectory(prefix="FAR80表示人工_", dir=ROOT / "work") as directory:
        temp = Path(directory).resolve()
        assert temp.is_relative_to((ROOT / "work").resolve())
        output = temp / "正式"
        output.mkdir()
        resources, rows = [], []
        active = []
        for day in range(33):
            date = (datetime(2026, 10, 1) + timedelta(days=day)).date().isoformat()
            for kind in ("Day", "Night"):
                session = date + "_" + kind
                for mode in MODES:
                    rid = session + "_" + mode
                    trades = []
                    if not resources:
                        at = datetime.fromisoformat(date + "T09:15:00+09:00")
                        for i, (typ, qty, price) in enumerate((("LongN", 2, 1000), ("LongR", 1, 1100), ("LongR", 1, 1000))):
                            trades.append({"id": str(i), "timestamp": (at + timedelta(seconds=i)).isoformat(), "type": typ,
                                "position_id": "人工実玉", "price": price, "qty": qty, "fee_yen": 61 * qty, "method_id": mode, "source_line": i + 1})
                        active = trades
                    path = output / (rid + ".trades.jsonl")
                    path.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in trades), encoding="utf-8")
                    resources.append({"id": rid, "title": "人工", "symbol": "NK225", "session": session, "product": "NK225micro",
                        "method_id": mode, "point_value": 10, "pnl_format": "trades", "pnl_basis": "net", "pnl_path": path.name,
                        "market_path": "NK225/" + session + "/book.jsonl.gz"})
                    rows.append({"session": session, "mode": mode, "net_pnl_yen": 756 if trades else 0})
        catalog_path, result_path = output / "一覧.resources.json", output / "結果.json"
        catalog_path.write_text(json.dumps({"schema_version": 1, "path_base": "catalog", "resources": resources}, ensure_ascii=False), encoding="utf-8")
        result_path.write_text(json.dumps({"場数": 66, "場別": rows, "比較": {mode: {"費用後損益円": 756 if mode == "F0" else 0} for mode in MODES}}, ensure_ascii=False), encoding="utf-8")
        resolved = [{**r, "pnl_path": str(output / r["pnl_path"]), "market_path": str(temp / "市場" / r["market_path"])} for r in resources]
        by_id = {r["id"]: r for r in resolved}

        def fake(method: str, url: str, payload: dict | None = None) -> tuple[dict, bytes, dict]:
            """人工API応答を返し、ネットワークへ接続しない。

            引数: method/url(str)はAPI、payload(dict|None)は一覧指定。
            返り値: tuple[dict,bytes,dict]は架空応答。
            """
            if url.endswith("/api/info"):
                value = {"resource_root": str(temp), "data_root": str(temp / "市場"), "listen": "127.0.0.1:8092"}
            elif url.endswith("/api/catalogs/load"):
                assert method == "POST" and payload == {"path": str(catalog_path.relative_to(temp))}
                value = {"catalog_id": "人工198", "path": str(catalog_path), "resources": resolved}
            else:
                from urllib.parse import parse_qs
                rid = parse_qs(urlparse(url).query)["resource"][0]
                is_active = rid == resources[0]["id"]
                events = [{"timestamp_ms": datetime.fromisoformat(t["timestamp"]).timestamp() * 1000,
                    "sequence": i + 1, "type": t["type"], "price": t["price"], "qty": t["qty"], "position_id": t["position_id"],
                    "method_id": t["method_id"], "realized_delta_yen": (-122, 939, -61)[i]} for i, t in enumerate(active)] if is_active else []
                net = 756 if is_active else 0
                value = {"resource": by_id[rid], "summary": {"long_qty": 0, "short_qty": 0, "realized_pnl_yen": net, "unrealized_pnl_yen": 0},
                    "state_columns": ["t", "long_qty", "short_qty", "realized_pnl_yen", "unrealized_pnl_yen"], "states": [[0, 0, 0, net, 0]],
                    "files": {"pnl": by_id[rid]["pnl_path"], "market": by_id[rid]["market_path"], "catalog": str(catalog_path)},
                    "events": events, "quality": {"warnings": []}}
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            return value, raw, {"x-chart-data-sha256": hashlib.sha256(raw).hexdigest()}

        good = run(catalog_path, result_path, transport=fake, progress=False)
        assert good["全件一致"] and good["数値取得完了資源数"] == 198 and good["不一致数"] == 0

        def broken(method: str, url: str, payload: dict | None = None) -> tuple[dict, bytes, dict]:
            """API成功のまま数値と未知を壊す人工応答を返す。

            引数: method/url(str)とpayload(dict|None)は人工依頼。
            返り値: tupleは原数値差を含む応答。
            """
            value, _, _ = fake(method, url, payload)
            if "/api/data?" in url:
                value["summary"]["realized_pnl_yen"] += 1
                value["summary"]["long_qty"] = None
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            return value, raw, {"x-chart-data-sha256": hashlib.sha256(raw).hexdigest()}

        bad = run(catalog_path, result_path, transport=broken, progress=False)
        assert not bad["全件一致"] and bad["全資源検証完了"] and bad["不一致数"] == 594 and not bad["APIエラー"]

        def disconnected(method: str, url: str, payload: dict | None = None) -> tuple[dict, bytes, dict]:
            """数値APIだけ通信失敗する人工応答を作る。

            引数: method/url(str)とpayload(dict|None)は人工依頼。
            返り値: tupleは成功部分。数値APIでViewerError。
            """
            if "/api/data?" in url:
                raise ViewerError("通信", url, "人工接続拒否")
            return fake(method, url, payload)

        partial = run(catalog_path, result_path, transport=disconnected, progress=False)
        assert not partial["全件一致"] and not partial["全資源検証完了"] and partial["数値取得完了資源数"] == 0
        assert partial["不一致数"] == 0 and partial["APIエラー"][0]["種類"] == "通信" and "未完了" in partial["数値一致判定"]
        return {"成功": True, "不一致数": 0, "テスト件数": 3, "正常照合項目数": good["照合項目数"],
            "人工数値破損検出数": bad["不一致数"], "実API呼出": 0, "本物結果読取": False}


def main() -> None:
    """人工又は正式一覧と結果を指定した表示照合を排他起動する。

    引数: CLIの--self-test(bool)、--catalog/--result/--output(Path)、--viewer-url(str)は段階と保存先。
    返り値: None。proofは新規保存し、失敗を0円へ読み替えない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--viewer-url", default="http://127.0.0.1:8092")
    args = parser.parse_args()
    if args.self_test:
        if args.catalog or args.result or args.output:
            parser.error("人工と正式入力を同時指定しない")
        value = self_test()
    else:
        if not all((args.catalog, args.result, args.output)):
            parser.error("正式照合には--catalog/--result/--outputが必要")
        if args.output.exists():
            raise FileExistsError("表示proofは保存済み。上書きしない")
        value = run(args.catalog, args.result, args.viewer_url)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    keys = ("成功", "全件一致", "全資源検証完了", "数値取得完了資源数", "照合項目数", "不一致数", "APIエラー", "テスト件数", "正常照合項目数")
    print(json.dumps({key: value[key] for key in keys if key in value}, ensure_ascii=False), flush=True)
    raise SystemExit(0 if value.get("成功", value.get("全件一致", False)) else 2 if value.get("APIエラー") else 1)


if __name__ == "__main__":
    main()
