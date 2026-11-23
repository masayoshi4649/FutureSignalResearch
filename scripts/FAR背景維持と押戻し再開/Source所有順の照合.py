"""88の所有一覧だけをID集合・全値で照合し、固定失敗証拠を別証拠で補う。

固定Source通知監査と条件は変更しない。影響1場だけ元NK原板を再走査し、
他65場は入力・再生・監査版へ結んだ旧成功行を全文のまま再利用する。
注文・通知・返済片・約定等の時系列順は、元監査の比較を変更しない。
"""

import argparse
from collections import Counter
import copy
import hashlib
import importlib.util
import json
from pathlib import Path


SOURCE_PATH = Path(__file__).with_name("Source通知監査.py")
SOURCE_SHA = "506fd648cbca1861bb465ac5ed143f27a1ae7f66d2def54825b57f83d9727a12"
CONDITION_SHA = "c9f4dda1d50b0057188c3013008d6456ae1af856dc52569d83a26a6c8be4a9dc"
AFFECTED = "2026-10-23_Day"
LABEL = "全玉の実初参加と最終所有・予約"
FIELDS = {"id", "reference_id", "side", "quantity", "initial_quantity", "reserved_exit", "closed_quantity", "entry_price", "entry_time", "entry_index", "entry_line"}


def sha(path: Path) -> str:
    """
    機能: 正本・固定コード・圧縮入力をbyte指紋へ結ぶ。
    引数: path (Path) は実ファイル。
    返り値: str はSHA256。原板JSON本文は解釈しない。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value: object) -> str:
    """
    機能: 再利用する場別証拠の全値を内容指紋へ写す。
    引数: value (object) は有限JSON値。
    返り値: str はUTF-8・キー整列JSONのSHA256。
    """
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def require(condition: bool, reason: str) -> None:
    """
    機能: 未完・型不正・指紋変更を成功へ補完しない。
    引数: condition (bool)、reason (str) は条件と説明。
    返り値: None。不成立ならValueError。
    """
    if not condition:
        raise ValueError(reason)


def ownership_map(value: object) -> dict:
    """
    機能: 全所有fieldを残し、一意な実玉IDだけを辞書キーにする。
    引数: value (object) は元監査の11field所有一覧。
    返り値: dict は順序以外の情報を落とさないID辞書。重複/欠落fieldは拒否。
    """
    require(type(value) is list, "所有一覧はlistが必要")
    mapped = {}
    for row in value:
        require(type(row) is dict and set(row) == FIELDS, "所有一覧の全field集合が不正")
        identity = row["id"]
        require(type(identity) is str and identity and identity not in mapped, "所有IDが空又は重複")
        mapped[identity] = row
    return mapped


def load_source() -> object:
    """
    機能: 停止原監査をSHA固定importし、対象label一つだけを比較時に正規化する。
    引数: なし。
    返り値: object は独立importされた旧監査。元ファイルは変更しない。
    """
    require(sha(SOURCE_PATH) == SOURCE_SHA, "停止Source原監査SHA不一致")
    spec = importlib.util.spec_from_file_location("source88_ownership_order_only", SOURCE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.check

    def normalized(audit: object, label: str, actual: object, expected: object, **context) -> None:
        """
        機能: 所有一覧だけ集合比較にし、全値/型とその他全配列の順を維持する。
        引数: audit (object)、label (str)、actual/expected (object)、context (dict)。
        返り値: None。元checkと同じ照合数で差を記録する。
        """
        if label == LABEL:
            actual, expected = ownership_map(actual), ownership_map(expected)
        original(audit, label, actual, expected, **context)

    module.check = normalized
    return module


def bind_sources(saved: dict, module: object) -> int:
    """
    機能: 影響場の所有出典を要求時raw pool・外binding・注文・玉・返済片へ結ぶ。
    引数: saved (dict)、module (object) は保存結果と固定型比較API。
    返り値: int は追加全文照合数。Source戦略を別実装するものではない。
    """
    checks = 0

    def equal(actual: object, expected: object, reason: str) -> None:
        """
        機能: 出典全文を固定監査と同じ数値/型規範で比較する。
        引数: actual/expected (object)、reason (str) は観測・期待・理由。
        返り値: None。不一致なら停止する。
        """
        nonlocal checks
        checks += 1
        require(module.same(actual, expected), reason)

    grids = {g["at"]: g for g in saved["grid_decisions"]}
    require(len(grids) == len(saved["grid_decisions"]), "出典bindの定時重複")
    bindings = {(b["book_key"], b["entry_order_id"]): b for b in saved["entry_bindings"]}
    require(len(bindings) == len(saved["entry_bindings"]), "外entry binding重複")
    visited = set()
    for key, book in saved["books"].items():
        entries = {o["position_id"]: o for o in book["orders"] if o["kind"] == "entry"}
        require(len(entries) == sum(o["kind"] == "entry" for o in book["orders"]), "同じ実玉へ新規要求重複")
        for pid, order in entries.items():
            token = key, order["id"]
            require(token in bindings, "新規要求に外bindingがない")
            visited.add(token)
            binding = bindings[token]
            grid = grids[order["request_time"]]
            policy = key.split("_D")[0]
            raw = [r for r in grid["source"]["lots"] if r["reference"]["id"] == order["reference_id"]]
            require(len(raw) == 1, "要求元参照が全raw poolに一意でない")
            raw = raw[0]
            c0 = grid["c0"]
            expected = {"policy": "S", "read_lot": raw, "snapshot_method": grid["source"]["method"], "snapshot_at": grid["source"]["at"], "snapshot_index": grid["source"]["source_index"], "snapshot_started": grid["source"]["started"], "rank": binding["supplied_rank"], "requested_quantity": order["quantity"], "reference_kind": raw["reference"]["kind"], "c0_used": False, "c0_allowed": c0["allowed"], "c0_required_unknown": c0["required_unknown"], "c0_side": c0["side"], "c0_role": c0["role"], "c0_reason": c0["reason"]}
            equal(order["source_entry"], expected, "要求SourceEntryが当時全raw pool/数量/出典と不一致")
            pool = [r for r in grid["policies"][policy]["pool"] if r["reference_id"] == order["reference_id"]]
            direction = [r for r in grid["entry"]["directions"] if r["side"] == order["side"]]
            require(len(pool) == len(direction) == 1, "外bindingの候補又は方向が一意でない")
            expected_binding = {"book_key": key, "policy": policy, "delay_seconds": int(key[-1]), "entry_order_id": order["id"], "position_id": pid, "reference_id": order["reference_id"], "at": grid["at"], "requested_quantity": order["quantity"], "raw_rank": pool[0]["raw_rank"], "supplied_rank": pool[0]["supplied_rank"], "source_method": grid["source"]["method"], "source_at": grid["source"]["at"], "source_index": grid["source"]["source_index"], "pool_evaluation": pool[0], "current_qualification": direction[0]}
            equal(binding, expected_binding, "外binding全文が当時候補/要求と不一致")
        for lot in book["lots"]:
            require(lot["id"] in entries, "実玉に元新規要求がない")
            order = entries[lot["id"]]
            equal(lot["source_entry"], order["source_entry"], "実玉SourceEntryと元要求が不一致")
            equal(lot["reference_id"], order["reference_id"], "実玉と元要求の参照ID不一致")
            equal(lot["initial_quantity"], order["filled_quantity"], "実初期量と取得量不一致")
        for piece in book["closed"]:
            require(piece["position_id"] in entries, "返済片に元新規要求がない")
            equal(piece["source_entry"], entries[piece["position_id"]]["source_entry"], "返済片SourceEntryと元要求が不一致")
    require(visited == set(bindings), "要求のない孤立外binding")
    return checks


def run(results: Path, manifest: Path, previous: Path, condition: Path, out: Path) -> dict:
    """
    機能: 固定失敗証拠へ全入力をbindし、影響1場だけ所有順を除いて再監査する。
    引数: results/manifest/previous/condition/out (Path) は明示した入出力。
    返り値: dict は旧schemaを維持した別の訂正証拠。旧証拠と金融を変更しない。
    """
    require(not out.exists(), "訂正証拠は新規先が必要")
    module = load_source()
    before = {str(p.resolve()): sha(p) for p in (Path(__file__), SOURCE_PATH, module.HELPER_PATH, module.FIXED87_PATH, module.RAW_PATH, module.EVENT_PATH, manifest, previous, condition)}
    require(sha(condition) == CONDITION_SHA, "88固定条件SHA不一致")
    config, ledger, old = (module.BASE.read_json(p) for p in (condition, manifest, previous))
    require(sha(manifest) == config["入力台帳SHA256"] == old["入力台帳SHA256"] == old["入力台帳SHA256前"] == old["入力台帳SHA256後"], "訂正元証拠と台帳指紋不一致")
    require(old["試行"] == 88 and old["成功"] is False and old["処理完了"] is True and old["場数"] == 66 and old["会計数"] == 396 and old["不一致数"] == 2 and old["入力前後不変"] is True, "訂正対象は固定88の2差完了証拠のみ")
    for field, expected in (("監査コードSHA256", SOURCE_SHA), ("固定80監査SHA256", module.HELPER_SHA), ("固定87通知監査SHA256", module.FIXED87_SHA), ("イベント原板コードSHA256", sha(module.RAW_PATH)), ("イベント保存コードSHA256", sha(module.EVENT_PATH))):
        require(old[field] == expected, "訂正元監査の依存指紋不一致:" + field)
    require(len(ledger["sessions"]) == len(old["対象場"]) == 66, "66場証拠不足")
    rows = {r["session"]: r for r in old["対象場"]}
    require(len(rows) == 66 and [r["session"] for r in old["対象場"]] == [e["id"] for e in ledger["sessions"]], "場ID重複又は元台帳との順序差")
    failures = [r for r in rows.values() if r["不一致数"]]
    require(len(failures) == 1 and failures[0]["session"] == AFFECTED and failures[0]["不一致数"] == 2, "訂正対象外の場に不一致")
    for details in (old["不一致"], failures[0]["不一致"]):
        require(len(details) == 2 and {d["会計"] for d in details} == {"E0_D0", "E0_D1"} and all(d["検査"] == LABEL for d in details), "所有一覧以外の差を訂正へ混ぜない")
    require(old["不一致"] == failures[0]["不一致"], "元証拠の全差と場別差が不一致")
    raw_root = Path(ledger["source_root"])
    all_inputs, replay_inputs = {}, {}
    for entry in ledger["sessions"]:
        row, path = rows[entry["id"]], results / (entry["id"] + ".json")
        require(row["処理完了"] is True and row["入力前後不変"] is True and row["会計数"] == 6 and row["不一致数"] == len(row["不一致"]), "再利用場の未完又は省略差")
        require(row["再生結果SHA256"] == row["再生結果SHA256前"] == row["再生結果SHA256後"] == sha(path), "再利用する保存結果の指紋変更")
        replay_inputs[entry["id"]] = sha(path)
        require(len(entry["files"]) == 6, "旧6入力の不足")
        for key, info in entry["files"].items():
            module.BASE.verify_file(raw_root, info)
            all_inputs[entry["id"] + ":" + key] = {"path": info["path"], "size": info["size"], "sha256": info["sha256"]}
        require(row["原板SHA256前"] == row["原板SHA256後"] == entry["files"]["NK225_book"]["sha256"], "旧原板証拠の入力結合が不一致")
    require(sum(r["照合項目数"] for r in rows.values()) == old["照合項目数"] and sum(r["不一致数"] for r in rows.values()) == 2, "訂正元集計と場別計数が不一致")
    entry = next(e for e in ledger["sessions"] if e["id"] == AFFECTED)
    saved = module.BASE.read_json(results / (AFFECTED + ".json"))
    extra = bind_sources(saved, module)
    inspected = module.inspect_one((str(results.resolve()), str(raw_root), entry))
    require(inspected["処理完了"] and inspected["入力前後不変"] and inspected["不一致数"] == 0 and not inspected["不一致"], "影響場の再原板照合が失敗")
    for key in failures[0]:
        if key not in ("不一致数", "不一致"):
            require(module.same(inspected[key], failures[0][key]), "影響場の順序差以外の観測変更:" + key)
    new_rows = [inspected if r["session"] == AFFECTED else copy.deepcopy(r) for r in old["対象場"]]
    for entry in ledger["sessions"]:
        require(sha(results / (entry["id"] + ".json")) == replay_inputs[entry["id"]], "保存結果の実行中変更")
        for info in entry["files"].values():
            module.BASE.verify_file(raw_root, info)
    require(all(sha(Path(name)) == value for name, value in before.items()), "訂正前後の固定証拠/コード変更")
    summary = Counter()
    for row in new_rows:
        for account in row["各会計通知要約"]:
            summary.update({k: v for k, v in account.items() if k != "会計"})
    require(dict(summary) == old["要約"], "訂正で通知作用集計が変化")
    value = copy.deepcopy(old)
    value.update(成功=True, 不一致数=0, 不一致=[], 対象場=new_rows, 監査コードSHA256=sha(Path(__file__)))
    value["訂正"] = {"訂正元証拠": {"path": str(previous.resolve()), "sha256": sha(previous), "成功": False, "不一致数": 2, "監査コードSHA256": SOURCE_SHA}, "訂正内容": "所有一覧の1項目だけ実玉ID集合と11field全文で比較。通知/注文/返済片/約定の時系列順は旧規範のまま。", "訂正コードSHA256": sha(Path(__file__)), "影響場": [AFFECTED], "再原板走査場数": 1, "再利用場数": 65, "再利用行SHA256": {r["session"]: canonical(r) for r in old["対象場"] if r["session"] != AFFECTED}, "影響場の旧行SHA256": canonical(failures[0]), "影響場の新行SHA256": canonical(inspected), "追加出典結合数": extra, "旧監査コードSHA256": SOURCE_SHA, "条件SHA256": CONDITION_SHA, "固定前後SHA256": before, "全入力396": all_inputs, "全保存66SHA256": replay_inputs, "入力前後不変": True, "新売買再生": 0}
    value["限界"] = list(old["限界"]) + ["訂正証拠は1場の再原板照合と、SHAが一致した65場の旧成功証拠を結合した。今回全66場を再走査したものではない。所有一覧だけ順序を問わず、全11fieldの値と型は比較する。"]
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return value


def main() -> None:
    """
    機能: 明示した旧失敗proofを別の訂正proofへ新規出力する。
    引数: --results/--manifest/--previous/--condition/--out (Path) は必須先。
    返り値: None。例外又は不一致では非0終了し、停止監査や旧証拠を変更しない。
    """
    parser = argparse.ArgumentParser()
    for name in ("results", "manifest", "previous", "condition", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    value = run(args.results, args.manifest, args.previous, args.condition, args.out)
    print(json.dumps({k: value[k] for k in ("成功", "場数", "会計数", "照合項目数", "不一致数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
