"""86の全原行付きGo人工を、独立短秒と原板規範へ接続する。"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


def load(path: Path, name: str) -> object:
    """
    機能: 明示した86コードを読取部品として読み込む。
    引数: path (Path)、name (str) はコードと識別名。
    返り値: object はモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    """
    機能: 人工入力の不変を本文指紋で確認する。
    引数: path (Path) は実ファイル。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(folder: Path, target: Path, raw: object) -> tuple:
    """
    機能: 全物理行付き人工quoteを原板gzipへ写し、欠測とLast0を保持する。
    引数: folder/target (Path) はGo人工と一時領域、raw (object) は86監査。
    返り値: tuple は一場台帳と品質。元の人工ファイルは変更しない。
    """
    rows = json.loads((folder / "raw_quotes.json").read_text(encoding="utf-8"))
    result = json.loads((folder / "86.json").read_text(encoding="utf-8"))
    quality = dict.fromkeys(("lines", "clock_missing", "outside", "backward", "bad_last", "bad_quote", "accepted"), 0)
    quality["contracts"] = ["人工限月"]
    index, feature = -1, -1
    with gzip.open(target / "book.jsonl.gz", "wt", encoding="utf-8", newline="\n") as stream:
        for line, item in enumerate(rows, 1):
            q = item["quote"]
            assert q["line"] == line
            row = {"Symbol": "人工限月"}
            quality["lines"] += 1
            if item["clock_missing"]:
                quality["clock_missing"] += 1
                assert not item["accepted"] and item["feature_expected"] == -1
            else:
                index += 1
                assert q["index"] == index and item["accepted"]
                quality["accepted"] += 1
                quality["bad_last"] += q["last"] <= 0
                quality["bad_quote"] += not 0 < q["bid"] < q["ask"]
                if q["last"] > 0:
                    feature += 1
                    assert item["feature_expected"] == feature
                else:
                    assert item["feature_expected"] == -1
                row.update(CurrentPriceTime=datetime.fromtimestamp(q["time"], timezone.utc).isoformat(), CurrentPrice=q["last"])
                for level in range(1, 11):
                    row[f"Buy{level}"] = {"Price": q["bid"] - 10 * (level - 1), "Qty": 100}
                    row[f"Sell{level}"] = {"Price": q["ask"] + 10 * (level - 1), "Qty": 100}
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    market = target / "book.jsonl.gz"
    entry = {"id": result["session"], "contract": "人工限月", "files": {"NK225_book": {"path": market.name, "size": market.stat().st_size, "sha256": sha(market)}}}
    return entry, quality


def inspect(raw: object, target: Path, entry: dict, result: dict) -> dict:
    """
    機能: メモリで複写した保存結果だけを一時先へ置き、原板2走査へ渡す。
    引数: raw (object)、target (Path)、entry/result (dict) は監査と人工値。
    返り値: dict は差分。正式保存結果を上書きしない。
    """
    (target / (entry["id"] + ".json")).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return raw.inspect_one((str(target), str(target), entry))


def mutations(result: dict) -> list:
    """
    機能: 正常保存値から新証拠・会計・off状態の破損例を作る。
    引数: result (dict) は正常Go人工の複写。
    返り値: list は破損名と変更済み値。
    """
    changed = []
    for label in ("複合分母改変", "成立数改変", "費用0", "J0架空初回", "未宣言証拠型", "新規注文を複合返済へ偽装"):
        value = deepcopy(result)
        if label == "複合分母改変":
            value["books"]["J1G1_D0"]["metrics"]["confirm_counts"]["normal_quotes"] += 1
        elif label == "成立数改変":
            value["books"]["J1G1_D1"]["metrics"]["confirm_counts"]["confirmed"] += 1
        elif label == "費用0":
            rows = value["books"]["J1G1_D0"]["trades"]
            if not rows:
                continue
            rows[0]["fee_yen"] = 0
        elif label == "J0架空初回":
            rows = value["books"]["J0G1_D0"]["lots"]
            if not rows:
                continue
            rows[0]["confirm_first_unknown"] = {"破損": True}
        elif label == "未宣言証拠型":
            value["books"]["J1G1_D0"]["metrics"]["confirm_counts"]["confirmed"] = False
        else:
            book = value["books"]["J1G1_D0"]
            entries = [row for row in book["orders"] if row["kind"] == "entry"]
            if not entries:
                continue
            entries[0]["reason"] = "保持帯両気配1tick・短秒反対確認"
            book["metrics"]["confirm_exit_orders"] += 1
        changed.append((label, value))
    for key, book in result["books"].items():
        for i, order in enumerate(book["orders"]):
            if order["reason"] == "保持帯両気配1tick・短秒反対確認":
                value = deepcopy(result)
                value["books"][key]["orders"][i]["confirm_evidence"]["short"]["five"]["move"] += 10
                changed.append(("凍結短秒幅の改変", value))
                value = deepcopy(result)
                fake = deepcopy(order)
                fake.update(id=order["id"] + "_孤立", request_line=value["grid_decisions"][0]["decision"]["quote"]["line"], request_index=value["grid_decisions"][0]["decision"]["quote"]["index"],
                    request_time=value["grid_decisions"][0]["at"], status="cancelled", remaining=0, filled_quantity=0, cancelled_quantity=order["quantity"], fill_time=None, fill_price=None, fill_line=0, confirm_evidence=None)
                value["books"][key]["orders"].append(fake)
                value["books"][key]["metrics"]["confirm_exit_orders"] += 1
                changed.append(("残玉へ未結合の撤回注文を追加", value))
                return changed
    return changed


def main() -> None:
    """
    機能: 原板接続8場面32会計と破損反証を新規証拠へ保存する。
    引数: --fixtures/--out (Path) はGo人工根と新規証拠。
    返り値: None。不一致・見逃しは例外、実市場・API利用は0。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    assert not args.out.exists()
    root = Path(__file__).resolve().parents[2]
    raw = load(Path(__file__).with_name("原板監査.py"), "raw86_artificial")
    folders = sorted(p for p in args.fixtures.iterdir() if p.is_dir())
    assert len(folders) == 8
    before = {str(p): sha(p) for p in args.fixtures.rglob("*.json")}
    checks, accounts = [], 0
    history = raw.ShortHistory()
    for at in (0, 5, 10, 15):
        history.observe(at, 100 + at, 110 + at)
    assert history.view(15, 120)["five"]["speed"] == 1 and history.view(15, 120)["fifteen"]["speed"] == 1
    history = raw.ShortHistory()
    for at, bid, ask in ((0, 100, 110), (5, 0, 0), (10, 110, 120)):
        history.observe(at, bid, ask)
    assert not history.view(10, 115)["five"]["known"]
    history = raw.ShortHistory()
    history.observe(0, 100, 110)
    history.observe(15, 110, 120)
    assert history.view(15, 115)["five"]["known"]
    history = raw.ShortHistory()
    history.observe(0, 100, 110)
    history.observe(15.001, 110, 120)
    assert not history.view(15.001, 115)["five"]["known"]
    history = raw.ShortHistory()
    history.observe(0, 100, 110)
    history.observe(0, 110, 120)
    history.observe(5, 120, 130)
    assert history.view(5, 125)["five"]["move"] == 10
    checks.append({"独立短秒": "5/15単位、途中異常、15秒gap包含/超過、同時計の最後の正常端を確認"})
    for folder in folders:
        result = json.loads((folder / "86.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="86原板_", dir=root / "work/86準備") as material:
            target = Path(material)
            assert target.resolve().is_relative_to((root / "work/86準備").resolve())
            entry, quality = materialize(folder, target, raw)
            result["quality"] = {"NK225": quality}
            normal = inspect(raw, target, entry, result)
            assert normal["不一致数"] == 0, (folder.name, normal["不一致"])
            checks.append({"場面": folder.name, "正常会計": len(result["books"]), "照合項目数": normal["照合項目数"]})
            for label, changed in mutations(result):
                try:
                    bad = inspect(raw, target, entry, changed)
                except (AssertionError, ValueError, KeyError, TypeError) as error:
                    checks.append({"場面": folder.name, "破損": label, "拒否": type(error).__name__ + ":" + str(error)})
                else:
                    assert bad["不一致数"] > 0, (folder.name, label)
                    checks.append({"場面": folder.name, "破損": label, "不一致": bad["不一致数"]})
            if folder.name.startswith("両気配反対"):
                market = target / "book.jsonl.gz"
                binary_before = market.read_bytes()
                with gzip.open(market, "rt", encoding="utf-8") as stream:
                    rows = [json.loads(line) for line in stream]
                rows[18]["Buy1"]["Price"] += 10
                rows[18]["Sell1"]["Price"] += 10
                with gzip.open(market, "wt", encoding="utf-8") as stream:
                    for row in rows:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                changed_entry = deepcopy(entry)
                changed_entry["files"]["NK225_book"].update(size=market.stat().st_size, sha256=sha(market))
                bad = inspect(raw, target, changed_entry, result)
                assert bad["不一致数"] > 0, "源端点だけ改変しても短秒を信じて通過しました"
                checks.append({"場面": folder.name, "破損": "金融約定を変えない過去端点の改変", "不一致": bad["不一致数"]})
                market.write_bytes(binary_before)
        accounts += len(result["books"])
    assert accounts == 32 and all(sha(Path(name)) == digest for name, digest in before.items())
    value = {"成功": True, "正常会計": accounts, "系列": len(checks), "内容": checks, "入力前後不変": True, "入力SHA256": before,
        "原板監査SHA256": sha(Path(__file__).with_name("原板監査.py")), "確認コードSHA256": sha(Path(__file__)), "実市場原板": 0, "新売買再生": 0,
        "限定": "Goの全物理行付き8場面から原板を作り、短秒も独立再構成。入口指標/E08は人工。全予定25/49枠のcash_check完了ではない。API人工の強制短秒改変とは別。"}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({name: value[name] for name in ("成功", "正常会計", "系列", "実市場原板", "新売買再生")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
