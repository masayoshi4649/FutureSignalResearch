"""入口イベントの代表を機械選択し、独立した2約定の経路例としてViewerへ渡す。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = Path(__file__).with_name("独立照合.py")
SPEC = importlib.util.spec_from_file_location("入口分析の独立入力読取", AUDIT_PATH)
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)
JST = audit.JST
GROUPS = ("整合突破", "押し戻り復帰")
LABELS = ("順行先着", "逆行先着")
POINT_VALUE = 10


def write_json(path: Path, value: Any) -> None:
    """日本語JSONを保存する。

    引数: path (Path) は保存先、value (Any) はJSON化できる内容。
    返り値: None。非有限数は保存しない。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def jst_time(seconds: float) -> str:
    """価格時計のUnix秒をJSTへ表記する。

    引数: seconds (float) はUnix秒。受信時刻ではない。
    返り値: str は時差付きISO日時。
    """
    return datetime.fromtimestamp(seconds, JST).isoformat()


def source_position(quotes: dict[str, np.ndarray], line: int, now: float) -> int:
    """CSVの原行と価格時計を正常板列へ対応させる。

    引数: quotes (dict[str, np.ndarray]) は正常板4列、line (int) は原始行、now (float) は価格時計。
    返り値: int は完全に対応する位置。不一致は例外にする。
    """
    positions = np.flatnonzero(quotes["line"] == line)
    if len(positions) != 1 or float(quotes["now"][positions[0]]) != now:
        raise ValueError("入口事例の原行・時計が正常板に対応しない")
    return int(positions[0])


def make_examples(study: Path, cache_root: Path) -> dict[str, Any]:
    """指定2群と先着2種類の最初の返済可能イベントを選択する。

    引数: study (Path) は00004、cache_root (Path) は固定npzの親。
    返り値: dict[str, Any] は選択例、欠落理由、時計・価格、出所の証跡。
    """
    csv_path = study / "入口事例.csv"
    audit_path = study / "独立照合結果.json"
    report = json.loads(audit_path.read_text(encoding="utf-8"))
    if not report["一致"] or report["不一致数"]:
        raise ValueError("全件の独立照合が成功していない")
    if report["ファイルSHA256"].get(audit.show_path(csv_path)) != audit.file_sha(csv_path):
        raise ValueError("独立照合後に入口事例.csvが変わっている")
    manifest, manifest_path = audit.read_manifest(study)
    entries = {entry["session"]: entry for entry in manifest["entries"] if entry["symbol"] == "NK225"}
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        rows = [(line, row) for line, row in enumerate(csv.DictReader(source), 2)]
    cached = {}
    resources, examples, omissions = [], [], []
    destination = study / "シナリオ"
    destination.mkdir(parents=True, exist_ok=True)
    for group in GROUPS:
        for label in LABELS:
            candidates = sorted([(line, row) for line, row in rows
                                 if group in row["条件群"].split("|") and row["ラベル"] == label],
                                key=lambda item: (float(item[1]["新規時計秒"]), int(item[1]["新規原板行"]), item[1]["イベントID"]))
            skipped = []
            chosen = None
            for csv_line, row in candidates:
                session = row["場"]
                entry = entries[session]
                if session not in cached:
                    source = Path(manifest["source_root"]) / entry["source_path"]
                    status = source.stat()
                    if (status.st_size, status.st_mtime_ns) != (entry["source_size"], entry["source_mtime_ns"]):
                        raise ValueError("代表例の原板statが固定台帳と異なる")
                    quotes, _, _ = audit.load_quotes(cache_root / entry["cache_path"], entry)
                    cached[session] = quotes
                quotes = cached[session]
                start, end, _, _ = audit.session_times(session)
                hit_time, entry_time = float(row["判定時計秒"]), float(row["新規時計秒"])
                entry_index = source_position(quotes, int(row["新規原板行"]), entry_time)
                hit_index = source_position(quotes, int(row["判定原板行"]), hit_time)
                side = int(row["side"])
                entry_price = float(quotes["ask"][entry_index] if side == 1 else quotes["bid"][entry_index])
                hit_price = float(quotes["bid"][hit_index] if side == 1 else quotes["ask"][hit_index])
                if entry_price != float(row["新規価格"]) or hit_price != float(row["判定気配"]):
                    raise ValueError("代表例の新規価格または判定気配が原行と不一致")

                # ----------------------------------------
                # 到達と返済を別イベントとし、1価格時計秒以上待って実際のBBOを使う。
                possible = np.flatnonzero((quotes["now"] >= hit_time + 1) & (quotes["now"] < end)
                                          & (quotes["line"] > int(row["判定原板行"])))
                if not len(possible):
                    skipped.append({"イベントID": row["イベントID"], "理由": "hit+1秒以後かつザラバ終了未満の正常板がない"})
                    continue
                exit_index = int(possible[0])
                exit_time = float(quotes["now"][exit_index])
                exit_line = int(quotes["line"][exit_index])
                exit_price = float(quotes["bid"][exit_index] if side == 1 else quotes["ask"][exit_index])
                identity = f"単独例_{group}_{label}_{row['イベントID']}"
                path = destination / f"{group}_{label}_{row['イベントID']}.trades.jsonl"
                prefix = "Long" if side == 1 else "Short"
                fills = [{"id": identity + "_新規", "timestamp": jst_time(entry_time), "type": prefix + "N",
                          "position_id": identity, "price": entry_price, "qty": 1, "fee_yen": 0,
                          "method_id": identity, "source_line": int(row["新規原板行"])},
                         {"id": identity + "_返済", "timestamp": jst_time(exit_time), "type": prefix + "R",
                          "position_id": identity, "price": exit_price, "qty": 1, "fee_yen": 0,
                          "method_id": identity, "source_line": exit_line}]
                path.write_text("".join(json.dumps(fill, ensure_ascii=False, allow_nan=False) + "\n" for fill in fills), encoding="utf-8")
                resource = {"id": identity, "title": f"独立入口イベントの単独経路例・{group}・{label}・運用損益ではない・{row['イベントID']}",
                            "symbol": "NK225", "session": session, "product": "NK225micro", "method_id": identity,
                            "entry_method_id": identity, "point_value": POINT_VALUE,
                            "pnl_format": "trades", "pnl_basis": "gross",
                            "pnl_path": path.relative_to(study).as_posix(), "market_path": entry["source_path"]}
                resources.append(resource)
                points = side * (exit_price - entry_price)
                chosen = {"条件群": group, "ラベル": label, "イベントID": row["イベントID"],
                          "入口CSV物理行": csv_line, "場": session, "方向": row["方向"], "side": side,
                          "候補数": len(candidates), "選択前の除外": skipped, "資源ID": identity,
                          "新規時計秒": entry_time, "新規時計JST": jst_time(entry_time),
                          "新規原板行": int(row["新規原板行"]), "新規価格": entry_price,
                          "逆行線": float(row["逆行線"]), "順行線": float(row["順行線"]),
                          "到達時計秒": hit_time, "到達時計JST": jst_time(hit_time),
                          "到達原板行": int(row["判定原板行"]), "到達返済気配": hit_price,
                          "返済時計秒": exit_time, "返済時計JST": jst_time(exit_time),
                          "返済原板行": exit_line, "返済価格": exit_price, "到達後返済待機秒": exit_time - hit_time,
                          "単独例価格差pt": points, "単独例粗損益円": points * POINT_VALUE,
                          "表示開始秒": max(start, entry_time - 900), "表示終了秒": min(end, exit_time + 900),
                          "約定": path.relative_to(study).as_posix(), "約定SHA256": audit.file_sha(path),
                          "原板": entry["source_path"], "原板展開SHA256_固定台帳参照": entry["sha256_uncompressed"],
                          "キャッシュ": audit.show_path(cache_root / entry["cache_path"]), "キャッシュSHA256": entry["sha256_cache"]}
                examples.append(chosen)
                break
            if chosen is None:
                omissions.append({"条件群": group, "ラベル": label, "候補数": len(candidates), "除外": skipped,
                                  "理由": "群内に当該先着ラベルがない" if not candidates else "全候補が返済正常板を確保できない"})
    catalog = {"schema_version": 1, "path_base": "catalog", "resources": resources}
    catalog_path = study / "シナリオ.resources.json"
    write_json(catalog_path, catalog)
    result = {"作成日時": datetime.now(JST).isoformat(), "用途": "独立入口イベントから機械選択した単独の経路表示。運用成績でも全入口の合算損益でもない。",
              "選択規則": "整合突破/押し戻り復帰×順行先着/逆行先着。新規時計秒・新規原板行・イベントIDの昇順で、hit+1価格時計秒以後の正常BBOがザラバ終了未満にある最初の例。",
              "返済モデル": "hitはラベル判定。返済はhit+1秒以後・ザラバ終了未満の最初の正常板で、買い玉はBid、売り玉はAsk。到達線上の約定を造らない。",
              "表示尺度": "ラージBBOをNK225micro1枚/1pt=10円へ仮置き。手数料0のgross表示で、microの実執行を再現しない。",
              "時計": "CurrentPriceTimeによる価格時計。受信時計ではなく、同時計の板だけの更新到着時刻は復元できない。",
              "ラベル証明": "Viewerは表示と2約定会計だけを照合。最初の到達・空白・EOFの独立証明は独立照合結果.jsonを参照。",
              "独立照合": "独立照合結果.json", "カタログ": "シナリオ.resources.json", "代表": examples, "欠落": omissions,
              "ファイルSHA256": {audit.show_path(path): audit.file_sha(path) for path in
                                   (Path(__file__), AUDIT_PATH, csv_path, audit_path, study / "条件.json",
                                    study / "入力台帳.json", manifest_path, catalog_path)}}
    write_json(study / "代表事例.json", result)
    write_readme(study, result)
    return result


def write_readme(study: Path, examples: dict[str, Any]) -> None:
    """単独シナリオの尺度・選択規則・読図上の注意を生成する。

    引数: study (Path) は試行、examples (dict[str, Any]) は代表事例の出所。
    返り値: None。既存の試行READMEは編集しない。
    """
    lines = ["# 独立入口イベントの単独経路例", "", "作成日：2026-11-01。運用損益ではなく、各入口を独立させた2約定だけの仮想経路表示。", "",
             "整合突破と押し戻り復帰について、順行先着・逆行先着それぞれの時刻順最初の返済可能例を選んだ。順序は新規価格時計、原板物理行、イベントID。該当例なし・返済不能の場合は[代表事例](../代表事例.json)に理由を残す。", "",
             "ラベルは買い玉のBid・売り玉のAskが200pt逆行または400pt順行へ最初に達した観測による。返済は別に1価格時計秒以上待ち、ザラバ終了前の最初の正常BBOを使う。到達時の線や価格で返済したとは扱わず、Viewerの返済印は待機後の約定を指す。", "",
             "ラージ板の価格をNK225micro1枚（1pt=10円）へ仮置きし、手数料0のgrossで表示する。microの実際の板や約定可能性を立証するものではない。重なる全入口を同時保有した成績や、この4例を合算した戦略成績は作らない。", "",
             "CurrentPriceTimeは価格時計で、受信時刻ではない。300秒超の正常板価格時計の空白等を含むラベル全件の独立照合は[独立照合結果](../独立照合結果.json)、表示・2約定会計・指紋の照合は[Viewer照合](../Viewer照合.json)を参照。価格の足はLastを表示し、到達の判定対象は別の返済気配である。汎用の閾値線や指標の描画はViewerへ追加していない。", "",
             "図は入口前15分から返済後15分までを場内へ制限した5分足。各印の正確な価格時計・原行と、到達と返済の違いは[代表事例](../代表事例.json)で確認する。足内の一時的な状態はraw表示で調べる。", "",
             "[シナリオ一覧](../シナリオ.resources.json)は原板を相対参照し、各約定ファイルは新規・返済の2行だけ。", "",
             "| 条件群 | 先着ラベル | 元イベント | 図 |", "| --- | --- | --- | --- |"]
    for example in examples["代表"]:
        image = f"../図/{example['条件群']}_{example['ラベル']}_{example['イベントID']}.png"
        lines.append(f"| {example['条件群']} | {example['ラベル']} | `{example['イベントID']}` | [単独例]({image}) |")
    lines.extend(["", "再生成はリポジトリルートで次を実行する。Viewer起動済みの場合は `--viewer` を付ける。", "", "```powershell",
                  'python -X utf8 "scripts/入口分析/代表事例.py" --study "study/00004_逆行200ptと順行400ptの入口分析" --viewer',
                  "```", "", "Viewer停止時は `work/viewer/conf/viewer.toml` の原板・研究ルートとポートを合わせ、作業コピーのexeを非表示で起動する。隣接リポジトリの設定や原板は変更しない。", ""])
    (study / "シナリオ/README.md").write_text("\n".join(lines), encoding="utf-8")


# ----------------------------------------
# Viewerは独立ラベルの証明ではなく、単独2約定の表示・会計・出所を確認する。

def fetch(url: str) -> tuple[bytes, dict[str, str]]:
    """ローカルViewerの数値または画像を取得する。

    引数: url (str) はメタ情報・数値・画像のURL。
    返り値: tuple[bytes, dict[str, str]] は生本文と小文字のヘッダ。
    """
    with urlopen(url, timeout=120) as response:
        return response.read(), {key.lower(): value for key, value in response.headers.items()}


def verify_viewer(study: Path, examples: dict[str, Any], base: str) -> dict[str, Any]:
    """代表資源だけをViewer APIで照合し、最大4枚のPNGを保存する。

    引数: study (Path) は試行、examples (dict[str, Any]) は代表事例、base (str) は接続先。
    返り値: dict[str, Any] は資源・独立会計・指紋・保存画像の照合記録。
    """
    catalog_path = study / "シナリオ.resources.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    relative_catalog = catalog_path.relative_to(ROOT).as_posix()
    listed_body, _ = fetch(base + "/api/resources?" + urlencode({"catalog_path": relative_catalog}))
    listed = json.loads(listed_body)["resources"]
    assert {row["id"] for row in listed} == {row["id"] for row in catalog["resources"]}, "APIの資源一覧が不一致"
    checks = []
    for example, resource in zip(examples["代表"], catalog["resources"]):
        assert example["資源ID"] == resource["id"], "代表例と資源の順が不一致"
        params = {"catalog_path": relative_catalog, "resource": resource["id"], "interval": "5", "price": "last",
                  "from": int(example["表示開始秒"] * 1000), "to": int(example["表示終了秒"] * 1000),
                  "width": 2000, "height": 1300}
        meta_body, _ = fetch(base + "/api/chart?" + urlencode(params))
        meta = json.loads(meta_body)
        data_body, headers = fetch(urljoin(base + "/", meta["data_url"]))
        data = json.loads(data_body)
        fingerprint = hashlib.sha256(data_body).hexdigest()
        assert fingerprint == meta["data_sha256"] == headers.get("x-chart-data-sha256"), "数値の指紋が不一致"
        fills_path = study / example["約定"]
        fills = [json.loads(raw) for raw in fills_path.read_text(encoding="utf-8").splitlines() if raw.strip()]
        assert len(fills) == len(data["events"]) == 2, "単独2約定ではない"
        side = example["side"]
        gross = Decimal(side) * (Decimal(str(fills[1]["price"])) - Decimal(str(fills[0]["price"]))) * Decimal(POINT_VALUE)
        assert float(gross) == example["単独例粗損益円"], "独立2約定会計が不一致"
        assert all(fill["qty"] == 1 and fill["fee_yen"] == 0 for fill in fills), "数量または費用が不一致"
        assert fills[0]["position_id"] == fills[1]["position_id"], "新規・返済の建玉IDが異なる"
        summary = data["summary"]
        assert summary == meta["summary"], "メタと数値の最終状態が不一致"
        assert summary == {"long_qty": 0, "short_qty": 0, "realized_pnl_yen": float(gross), "unrealized_pnl_yen": 0}, "最終会計が不一致"
        for index, (fill, event) in enumerate(zip(fills, data["events"]), 1):
            assert event["sequence"] == index, "約定物理行が不一致"
            assert all(event[key] == fill[key] for key in ("type", "price", "qty", "position_id", "method_id")), "約定列が不一致"
            assert event["timestamp_ms"] == datetime.fromisoformat(fill["timestamp"]).timestamp() * 1000, "約定時計が不一致"
            assert event["realized_delta_yen"] == (0 if index == 1 else float(gross)), "片の粗損益が不一致"
        assert data["resource"]["entry_method_id"] == resource["entry_method_id"], "手法帰属が不一致"
        assert data["resource"]["point_value"] == POINT_VALUE and data["resource"]["pnl_basis"] == "gross", "表示尺度が不一致"
        assert Path(data["files"]["pnl"]).resolve() == fills_path.resolve(), "約定出所が不一致"
        expected_market = ROOT.parent / "JP_OSE_Data/future" / example["原板"]
        assert Path(data["files"]["market"]).resolve() == expected_market.resolve(), "原板出所が不一致"
        png, image_headers = fetch(urljoin(base + "/", meta["png_url"]))
        assert png.startswith(b"\x89PNG\r\n\x1a\n") and image_headers.get("x-chart-data-sha256") == fingerprint, "PNGまたは画像指紋が不一致"
        image_path = study / "図" / f"{example['条件群']}_{example['ラベル']}_{example['イベントID']}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(png)
        checks.append({"資源ID": resource["id"], "条件群": example["条件群"], "ラベル": example["ラベル"],
                       "イベントID": example["イベントID"], "独立会計_単独例粗損益円": float(gross),
                       "API最終状態": summary, "API約定片数": len(data["events"]),
                       "約定": example["約定"], "約定SHA256": audit.file_sha(fills_path),
                       "原行BBOの照合": "代表事例生成時に新規・到達・返済を固定npzで照合。Viewerのeventsにはsource_line列はない。",
                       "到達時計JST": example["到達時計JST"], "返済時計JST": example["返済時計JST"],
                       "到達返済気配": example["到達返済気配"], "返済価格": example["返済価格"],
                       "数値SHA256": fingerprint, "数値本文SHA256一致": True,
                       "数値ヘッダSHA256": headers.get("x-chart-data-sha256"),
                       "画像ヘッダSHA256": image_headers.get("x-chart-data-sha256"),
                       "PNG": image_path.relative_to(study).as_posix(), "PNGSHA256": audit.file_sha(image_path),
                       "表示範囲": meta["range"], "品質": data["quality"], "出所": data["files"], "一致": True})
        print(json.dumps({"イベントID": example["イベントID"], "単独例粗損益円": float(gross), "一致": True}, ensure_ascii=False), flush=True)
    info_body, _ = fetch(base + "/api/info")
    binary = ROOT / "work/viewer/session-trade-viewer.exe"
    result = {"確認日時": datetime.now(JST).isoformat(), "接続先": base, "API情報": json.loads(info_body),
              "API資源数": len(listed), "カタログ": relative_catalog, "カタログSHA256": audit.file_sha(catalog_path),
              "Viewer実行コピー": audit.show_path(binary), "Viewer実行コピーSHA256": audit.file_sha(binary) if binary.is_file() else None,
              "表示設定": {"interval": "5", "price": "last", "width": 2000, "height": 1300},
              "照合": checks, "全件一致": len(checks) == len(examples["代表"]),
              "注意": "独立入口の単独2約定例。ラベルは返済約定・運用損益とは別。全件ラベルの証明は独立照合結果.jsonで行う。PNG代表4例は収益性の立証ではない。"}
    write_json(study / "Viewer照合.json", result)
    return result


def main() -> None:
    """代表シナリオの再生成と任意のViewer照合をCLIで行う。

    引数: なし。--study/--cache-root/--viewer/--api-baseを取得する。
    返り値: None。既存の分析結果・条件・隣接リポジトリは変更しない。
    """
    parser = argparse.ArgumentParser(description="独立入口イベントの単独経路例")
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=ROOT / "work/複合検証")
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--api-base", default="http://127.0.0.1:8092")
    arguments = parser.parse_args()
    study = arguments.study.resolve()
    examples = make_examples(study, arguments.cache_root.resolve())
    print(json.dumps({"代表数": len(examples["代表"]), "欠落": examples["欠落"]}, ensure_ascii=False), flush=True)
    if arguments.viewer:
        verify_viewer(study, examples, arguments.api_base.rstrip("/"))


if __name__ == "__main__":
    main()
