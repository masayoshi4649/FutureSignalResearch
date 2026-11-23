"""00017の保存済み入力監査を三文書・51×9表・少数事例CSVへ写す。"""

from __future__ import annotations

from collections import Counter
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00017_配信元VWAPと売買代金の入力監査"
WORK = ROOT/"work/VWAP入力"
JST = timezone(timedelta(hours=9))


def display() -> Any:
    """共通の表・リンク描画だけを読み込む。

    引数: なし。
    返り値: Any は表示補助。抽出・監査・先着・売買を再実行しない。
    """
    spec = importlib.util.spec_from_file_location("VWAP監査の表表示", ROOT/"scripts/レポート/設定結果レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


G = display()


def number(value: int | float | None) -> str:
    """件数と精度を区別して表示する。

    引数: value (int|float|None) は表示値。
    返り値: str は整数の桁区切りまたは精度を保つ数値。不明は未確認。
    """
    if value is None:
        return "未確認"
    return f"{int(value):,}" if float(value).is_integer() else format(value, ".12g")


def clock(value: float | None) -> str:
    """欠測を補わずUnix秒をJSTへ表示する。

    引数: value (float|None) は配信列の時計。
    返り値: str は時差付きISO時計、欠測は空文字列。
    """
    return datetime.fromtimestamp(value, JST).isoformat() if value is not None and math.isfinite(value) else ""


def copy_proof(study: Path, filename: str, count: int, locked: dict) -> Path | None:
    """作業proofを固定版と追補の区別を保ったまま正式保存する。

    引数: study (Path) は正式先、filename (str) はproof名、count (int) は想定件数、locked (dict) は固定SHA。
    返り値: Path|None は正式proof。未保存の追補はNone、変更された固定版は拒否する。
    """
    source, target = WORK/filename, study/filename
    if not source.exists():
        return target if target.exists() else None
    data = G.read_json(source)
    if data["全件成功"] is not True or data["検証件数"] != count:
        raise ValueError("合成proofの件数または合否が不一致")
    for name, digest in data["ファイルSHA256"].items():
        if G.sha(ROOT/name) != digest or name in locked and locked[name] != digest:
            raise ValueError("合成proofが実ファイルまたは固定版と不一致")
    if target.exists():
        prior = G.read_json(target)
        if any(prior[key] != data[key] for key in ("全件成功", "検証件数", "ファイルSHA256")):
            raise ValueError("既存の正式proofと識別が不一致")
    else:
        target.write_bytes(source.read_bytes())
    return target


def validate(report: dict) -> list[dict]:
    """入力監査の総数と65場の保存集計を検算する。

    引数: report (dict) は結果正本。
    返り値: list[dict] は65場。PnLや先着結果を生成しない条件も確認する。
    """
    if not report["入力監査"] or report["損益を計算"] or not report["全65場既使用"] or report["原板複製"]:
        raise ValueError("入力監査の位置付けが不一致")
    entries = report["場別"]
    if len(entries) != 65 or len({e["session"] for e in entries}) != 65 or sum(e["session"].endswith("_Day") for e in entries) != 33:
        raise ValueError("固定65場/Day33・Night32と異なる")
    if report["入力場数"] != len(entries) or not all(e["旧展開SHA一致"] for e in entries) or not report["展開SHA全場一致"]:
        raise ValueError("入力指紋照合が不一致")
    for key, field in (("原行数", "raw_lines"), ("保存状態数", "events"), ("原板保存バイト", "source_size"), ("補助NPZバイト", "cache_size")):
        if report[key] != sum(e[field] for e in entries):
            raise ValueError(key+"の総計が不一致")
    counts = sum((Counter(e["監査"]["件数"]) for e in entries), Counter())
    if counts != Counter(report["件数"]) or counts["原行重み合計"] != sum(e["decoded_rows"] for e in entries):
        raise ValueError("原行重みと場別件数が不一致")
    return entries


# ----------------------------------------
# 全小列の再計算結果と、直接原板へ対応させた少数事例の範囲を分ける。

def proof_table(study: Path, output: Path) -> tuple[str, list[Path]]:
    """固定36・後追補2・独立照合の合否と範囲を別々に示す。

    引数: study/output (Path) は正式試行と表示先。
    返り値: tuple[str,list[Path]] は検査表と出典。未保存を合格と扱わない。
    """
    rows, paths = [], []
    for name, label, key in (("合成検証.json", "実行前の固定合成", "検証件数"),
                             ("追加合成検証.json", "固定後追補・固定36へ非加算", "検証件数"),
                             ("独立確認.json", "全NPZ別計算と原板限定標本", "照合項目数")):
        path = study/name
        if not path.exists():
            rows.append([label, "未完・未保存", "未算出", "なし"])
            continue
        data = G.read_json(path)
        verdict = data.get("全件成功", data.get("全件一致"))
        rows.append([label, "全件一致/成功" if verdict is True else "不一致/失敗" if verdict is False else "明示合否未確認", number(data[key]), G.link(path, output)])
        paths.append(path)
    text = "## 検査とその範囲\n\n実行前に固定したのは36件。固定後の小型stream追補2件は別ファイル・別proofで、事前条件や固定SHAを書き換えていない。検査件数を新しい市場標本として加算しない。\n"
    text += G.table(["範囲", "明示判定", "項目/件数", "正本"], rows)
    path = study/"独立確認.json"
    if path.exists():
        data = G.read_json(path)
        text += "独立側は保存NPZの全状態について式・時計・重み付き分位・基準/差分判定を別実装で確認した。原板との直接対応は65場の131例、追加読取は展開86,512,056バイト。全原板を別プログラムで全行再抽出した監査ではない。入力展開SHAの一致は出典同一性であり、変換全行を独立に証明する代わりにはならない。\n\n"
    return text, paths


def origin_table(entries: list[dict]) -> str:
    """配信値参照と既知基準・数学差分を別の場数として表示する。

    引数: entries (list[dict]) は全場の保存監査。
    返り値: str はDay/Night別表。基準不明を値欠測へ読み替えない。
    """
    rows = []
    for suffix, title in (("_Day", "デイ"), ("_Night", "ナイト")):
        members = [e for e in entries if e["session"].endswith(suffix)]
        counts = sum((Counter(e["監査"]["件数"]) for e in members), Counter())
        origins = [e["監査"]["起算"] for e in members]
        rows.append([title, len(members), sum(e["監査"]["件数"].get("場内配信値観測参照候補原行数", 0) > 0 for e in members),
                     sum(o["既知接頭基準"] is not None for o in origins), sum(o["差分計算可能原行数"] > 0 for o in origins),
                     number(counts["差分計算可能原行数"]), number(counts["差分計算可能かつ内部整合かつ場内数量時計原行数"]),
                     number(counts["差分計算可能かつ場内観測参照候補原行数"]), number(counts["場内差分基準一時未確認原行数"])])
    text = "## 配信値と当場差分の起算可否\n\n配信値は全65場に観測参照候補がある一方、当日の閉場後に両時計を持つ既知基準から差し引ける場は限られる。数学的に比を作れること、内部整合と当場数量時計、正の差分価格/Lastを満たす候補を別集計にする。必要条件を満たす候補という名称であり、同時生成・正確な受信・全約定一致の認定ではない。\n"
    return text + G.table(["区分", "入力場", "native候補あり場", "既知基準あり場", "差分可の場", "数学差分可原行", "整合×場内量時計", "正価格等の候補交差", "identity一時未確認原行"], rows)


def session_table(entries: list[dict]) -> str:
    """保存された各場の比率・基準・時計件数を一覧にする。

    引数: entries (list[dict]) は65場。
    返り値: str は場別表。全体分位を場別分位の平均で捏造しない。
    """
    rows = []
    for entry in entries:
        audit, session = entry["監査"], entry["session"]
        ratio, origin, counts = audit["内部整合"], audit["起算"], Counter(audit["件数"])
        rows.append([session, number(entry["raw_lines"]), number(entry["events"]), number(ratio["比較原行数"]), number(ratio["不整合原行数"]),
                     number(ratio["最大絶対差pt"]), number(ratio["分位点"]["0.5"]), number(ratio["分位点"]["0.99"]),
                     "既知" if origin["既知接頭基準"] is not None else "不明", number(origin["差分計算可能原行数"]),
                     number(origin["差分計算可能かつ場内観測参照候補原行数"]), number(origin["基準無効化数"]),
                     number(counts["場内差分基準一時未確認原行数"]), number(counts["価格時計原行後退除外原行数"])])
    return "## 全65場の保存集計\n\n誤差分位は各場でrepeat原行重みを使ったもの。各場中央値を平均して全体中央値にはしない。基準不明の差分0は配信VWAP欠測を意味しない。\n" + G.table(["場", "原行", "保存状態", "比率比較", "不整合", "最大差pt", "p50差pt", "p99差pt", "開始前基準", "数学差分可原行", "候補交差原行", "基準失効", "identity一時未確認", "後退除外原行"], rows)


def examples(entries: list[dict], target: Path) -> list[dict]:
    """損益を使わない機械選択で最大誤差とfirst/last/差分の少数例を保存する。

    引数: entries (list[dict]) は保存結果、target (Path) は小型CSV。
    返り値: list[dict] は選択事例。原板やNPZは再読せず最大15行程度に抑える。
    """
    choices = []
    def select(entry: dict, kind: str, sample: dict | None, reason: str) -> None:
        """具体例の参照を欠測補完せず追加する。

        引数: entry/sample (dict) は場/具体例、kind/reason (str) は種類/規則。
        返り値: None。存在する具体例だけを追加する。
        """
        if sample is not None:
            choices.append((entry, kind, sample, reason))
    candidates = [e for e in entries if e["監査"]["内部整合"]["最大差例"] is not None]
    if candidates:
        entry = min(candidates, key=lambda e: (-e["監査"]["内部整合"]["最大絶対差pt"], e["session"]))
        select(entry, "内部最大差", entry["監査"]["内部整合"]["最大差例"], "全場最大差・同値は場名順")
    for suffix in ("_Day", "_Night"):
        members = [e for e in entries if e["session"].endswith(suffix)]
        for entry in (members[0], members[-1]):
            for key in ("最初場内", "最後場内"):
                select(entry, key, entry["監査"]["起算"][key], "区分の最初/最後の場")
    ready = [e for e in entries if e["監査"]["起算"]["差分計算可能原行数"] > 0]
    if ready:
        for entry in (ready[0], ready[-1]):
            for key in ("既知接頭基準", "最初差分例", "最後差分例"):
                select(entry, key, entry["監査"]["起算"][key], "差分可能な最初/最後の場")
    rows, seen = [], set()
    for entry, kind, sample, reason in choices:
        key = entry["session"], kind, sample["line"]
        if key in seen:
            continue
        seen.add(key)
        contract, exchange = sample.get("contract", -1), sample.get("exchange", -1)
        market = entry["exchange_values"][exchange] if 0 <= exchange < len(entry["exchange_values"]) else {}
        rows.append({"選択理由": reason, "場": entry["session"], "種類": kind, "source_path": entry["source_path"],
                     "原板行": sample["line"], "repeat": sample["repeat"], "価格時計JST": clock(sample.get("now")),
                     "数量時計JST": clock(sample.get("volume_time")), "Last": sample.get("last"), "累積数量": sample.get("volume"),
                     "配信VWAP": sample.get("native_vwap"), "累積売買代金": sample.get("trading_value"),
                     "始値": sample.get("opening_price"), "始値時計JST": clock(sample.get("opening_time")),
                     "Symbol": entry["contract_codes"][contract] if 0 <= contract < len(entry["contract_codes"]) else None,
                     "Exchange": market.get("Exchange"), "ExchangeName": market.get("ExchangeName"),
                     "比率VWAP": sample.get("代金数量比VWAP"), "内部絶対差pt": sample.get("絶対差pt"),
                     "基準原行": sample.get("基準原行"), "基準価格時計JST": clock(sample.get("基準価格時計")),
                     "差分数量": sample.get("差分数量"), "差分代金": sample.get("差分代金"), "差分VWAP": sample.get("差分VWAP")})
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["場"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


# ----------------------------------------
# 入力監査IDを売買の複合評価IDと分け、先着と保護注文は対象外と表示する。

def settings() -> list[dict]:
    """入力に使った原板セルと監査条件を定義する。

    引数: なし。
    返り値: list[dict] はS設定とA監査ID。R売買評価やPnLを作らない。
    """
    definitions = [
        (["I12"], "代金/量/1000・差<=0.00010001pt", "正量/正VWAP・非負代金、時計と独立に内部比較", "A01"),
        (["I12", "V01"], "価格時計/原行非後退・量時計<=価格時計", "必要条件のみ。VWAP/代金の固有時計や受信時計を補わない", "A02"),
        (["I12", "V01"], "Day06:00/Night15:45〜開始前の既知基準", "両時計/既知identity/内部整合又は直接零。減少や既知不一致で破棄、一時欠測は確認待ち", "A03"),
        (["I12", "V01"], "差分量>0・差分代金>=0", "数学比と、整合×場内数量時計×正価格/Lastの候補を分離。0価格を売買へ利用しない", "A04"),
        (["I12", "V01"], "原順12列・全展開SHA・repeat原行重み", "同一連続だけ省略、単独VWAP/代金/始値/市場更新は保持。全NPZ別計算/原板131例", "A05")]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": ["tick"], "短記": short, "説明": detail,
             "結果短記": audit_id+"入力監査", "適用評価": [audit_id]} for i, (methods, short, detail, audit_id) in enumerate(definitions, 1)]


def matrix(catalog: dict, output: Path, definitions: list[dict]) -> str:
    """51×9表を保ち、先着と保護注文の全セルを対象外へ区別する。

    引数: catalog (dict) は共通表、output (Path) は表示先、definitions (list[dict]) は入力設定。
    返り値: str は使用/未使用/対象外を区別した表。
    """
    lines = G.matrix(catalog, output, definitions).splitlines()
    for i, line in enumerate(lines):
        if line.startswith("| E01 |") or line.startswith("| E02 |"):
            cells = line.split("|")
            cells[3:-1] = [" 対象外 "]*9
            lines[i] = "|".join(cells)
    return "\n".join(lines)+"\n\n"


def run(study: Path, output: Path) -> list[Path]:
    """保存済み監査JSONから正式三文書と小型CSVを生成する。

    引数: study/output (Path) は正式試行/任意表示先。
    返り値: list[Path] は三Markdownと事例CSV。原板・NPZの抽出や売買再生は呼ばない。
    """
    report, config = G.read_json(study/"結果.json"), G.read_json(study/"条件.json")
    entries = validate(report)
    locked = G.read_json(study/"固定.json")["ファイルSHA256"]
    if any(G.sha(ROOT/name) != digest for name, digest in locked.items()):
        raise ValueError("固定後にコード・計画・条件・入力が変更されている")
    fixed_proof = copy_proof(study, "合成検証.json", 36, locked)
    if fixed_proof is None:
        raise ValueError("固定36件の合成proofがない")
    additional_proof = copy_proof(study, "追加合成検証.json", 2, locked)
    pointer = G.read_json(study/"入力台帳.json")
    source_manifest = (study/pointer["参照"]).resolve()
    if G.sha(source_manifest) != pointer["SHA256"]:
        raise ValueError("入力台帳参照SHA不一致")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path, all_path, case_path = [output/name for name in ("README.md", "設定と結果.md", "全監査結果.md", "小型事例.csv")]
    selected = examples(entries, case_path)
    counts = Counter(report["件数"])
    largest = max(e["監査"]["内部整合"]["最大絶対差pt"] for e in entries)
    ratio_count = sum(e["監査"]["内部整合"]["比較原行数"] for e in entries)
    mismatch = sum(e["監査"]["内部整合"]["不整合原行数"] for e in entries)
    intro = "状態：全65場の入力抽出・集計保存済み。全65場は00016以前からの既使用データ。これは新しい入力の監査で、売買仮説の成績ではない。**先着率・損益は未検証/今回の対象外。注文・約定・Viewer架空取引は生成していない。**\n\n"
    overview = "## 確認できたこと\n" + G.table(["項目", "保存結果"], [
        ["入力", "NK225ラージ65場（Day33/Night32）・全既使用"], ["参照元保存サイズ", number(report["原板保存バイト"])+"B"],
        ["原行→保存状態", number(report["原行数"])+"→"+number(report["保存状態数"])],
        ["補助NPZ合計", number(report["補助NPZバイト"])+"B・原板複製なし"],
        ["展開SHA/物理行/復号行の固定台帳照合", "全65場一致"], ["比率比較可能な原行", number(ratio_count)],
        ["内部不整合", number(mismatch)], ["最大絶対差", number(largest)+"pt（許容0.00010001pt）"],
        ["identity一時未確認", number(counts["場内差分基準一時未確認原行数"])+"原行"],
        ["価格時計隣接後退/最大既知キーからの除外", number(counts["価格時計隣接後退回数"])+"回 / "+number(counts["価格時計原行後退除外原行数"])+"原行"]])
    meaning = "## 内部整合と利用可能性を分ける\n\n原板にnative VWAP/TradingValueがあり、旧8列キャッシュが保持していなかった。配信VWAPと売買代金/累積数量/1000の内部一致を確認しても、全約定履歴から独立再計算した証明にはならない。VWAPは全参加者の現在建値でも売買方向でもない。\n\n"
    meaning += "CurrentPriceTimeは現値時計、TradingVolumeTimeは売買高時計。数量時計<=価格時計は必要条件だけで、VWAP/売買代金の同時生成・受信済み・公表時刻を保証しない。両者の固有時計と受信時計はこの入力にない。古い同時計の後続行を過去の判断へ混ぜず、価格時計/原行の後退は参照から外す。\n\n"
    meaning += "基準規則は当日Day06:00/Night15:45以後の閉場区間に両時計がある既知値だけを認める。休場を越えた以前の累積値を取引日カレンダーで格上げしていないため、差分不明はデータが存在しない断定ではない。量/代金減少・数量時計後退・既知identity変更で永久破棄。一時欠測は基準を不変保持し当該行を除外、同じ既知identityを再確認した後だけ再開する。未観測resetまで否定できる規則ではない。\n\n"
    meaning += "差分量0へ0を補わない。正の差分量でも差分代金0なら数学比は0と定義できるが、正価格の観測参照候補と分ける。今回の数学差分可能行はすべて内部整合・場内数量時計・正価格等の交差も満たしたという観測で、一般に両者が同じ集合になる保証ではない。\n\n"
    last = next(e for e in reversed(entries) if e["session"].endswith("_Day"))
    sample = last["監査"]["起算"]["最後差分例"]
    example_note = ""
    if sample is not None:
        example_note = "## 同原行でも異なる起算\n\n"+last["session"]+"の"+clock(sample["now"])+"・原行"+str(sample["line"])+"では、配信VWAP"+number(sample["native_vwap"])+"に対し、既知"+clock(sample["基準価格時計"])+"からの差分加重価格は"+number(sample["差分VWAP"])+"。差は約"+number(abs(sample["native_vwap"]-sample["差分VWAP"]))+"ptで、起算を無視して両者を同じデイVWAPとは呼ばない。配信値全65場と差分可23場をそのまま損益比較すれば場選択が混ざる。次試行では共通利用可能場と全運用を別に固定する。\n\n"
    official = "## 公式仕様と未確定部分\n\n確認日2026-11-04。[公式PUSH仕様](https://kabucom.github.io/kabusapi/ptal/push.html)には先物のVWAP・売買代金・売買高時刻があるが、VWAP/売買代金それぞれの固有時計は掲載されていない。この表だけで08:45/17:00の厳密な累積リセットを断定しない。" + G.link(ROOT/"docs/議論/配信元VWAPとセッション起算を確認する.md", readme, "一次資料・標本・次仮説") + "と、今回の入力監査の条件/結果を分ける。\n\n"
    audit_text, audit_paths = proof_table(study, readme)
    refs = " / ".join(G.link(study/name, readme) for name in ("計画.md", "条件.json", "入力台帳.json", "固定.json", "結果.json"))
    summary = "# 試行00017：配信元VWAPと売買代金の入力監査\n\n"+intro+refs+" / "+G.link(setting_path, readme)+" / "+G.link(all_path, readme)+"\n\n"+overview+origin_table(entries)+meaning+example_note+audit_text+official
    reproduction = "## 入力・保存・再現\n\n"+G.link(source_manifest, readme, "00008固定入力台帳")+" / "+G.link(ROOT/report["抽出台帳"], readme, "作業抽出台帳（Git外）")+" / "+G.link(case_path, readme)+"\n\n"
    reproduction += "小型CSVは"+str(len(selected))+"例。最大差（同値は場名順）、Day/Nightの最初/最後の場のfirst/last、差分可能な最初/最後の場の基準とfirst/last差分を保存。数値0と不明空欄を区別する。全原板や全小列を正式フォルダへ重複保存しない。\n\n"
    reproduction += "補助列：now/line/last/volume/volume_time/native_vwap/trading_value/opening_price/opening_time/contract/exchange/repeat。時計float64 Unix秒・欠測NaN、原行/repeat int64、識別int16を対応表で原値へ戻す。全列同一の連続だけを圧縮し、VWAP・代金・始値・市場単独更新と空行による物理区間分断を保持する。\n\n"
    names = ["抽出監査.py", "合成検証.py", "追加合成検証.py", "独立確認.py", "レポート.py"]
    reproduction += "コード："+" / ".join(G.link(ROOT/"scripts/VWAP入力"/n, readme) for n in names)+"。\n\n"
    fence = chr(96)*3
    reproduction += "保存結果の再表示（原板/NPZ再計算なし）：\n\n"+fence+"powershell\npython -X utf8 scripts/VWAP入力/レポート.py\n"+fence+"\n\n抽出は抽出監査.py --study/--workで別保存先を指定し、固定36件proofと入力/条件/コード指紋を照合する。正式結果上書き・固定後変更を拒否する。追補は追加合成検証.pyで別proofへ保存する。\n\n"
    catalog, definitions = G.read_json(G.CATALOG), settings()
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("51×9カタログが変化")
    mapping = "# 試行00017：設定と結果\n\n"+intro+G.link(G.MASTER, setting_path, "コピー元の汎用表")+" / "+G.link(readme, setting_path)+" / "+G.link(all_path, setting_path)+"\n\n"
    mapping += "## 手法×時間スケール\n\n51手法×9尺度を保持。使用セルはVWAP・累積数量の入力監査で、A01〜A05は監査ID。R売買評価IDや収益は作らない。1/3/5分等の足指標は生成せず未使用、先着E01/保護E02は今回対象外で収益性は未検証。Day/Night別起算を監査しても、セッション足の売買指標を検証した意味ではない。\n\n"+matrix(catalog, setting_path, definitions)
    mapping += "## 入力設定明細\n"+G.table(["設定", "手法/尺度", "閾値と短記", "意味", "監査ID"], [[s["設定ID"], "/".join(s["手法ID"])+"/tick", s["短記"], s["説明"], s["結果短記"]] for s in definitions])
    conditions = "## 全監査条件\n"+G.table(["条件", "固定値/規則"], [[k, G.describe(v)] for k, v in config.items()])
    mapping += conditions+overview+origin_table(entries)+meaning+"全65場は"+G.link(all_path, setting_path)+"、先着/PnLは対象外・未検証。\n\n"
    all_audits, _ = proof_table(study, all_path)
    full = "# 試行00017：全監査結果\n\n"+intro+G.link(readme, all_path)+" / "+G.link(setting_path, all_path)+" / "+G.link(study/"結果.json", all_path)+"\n\n"+conditions+overview+origin_table(entries)+session_table(entries)
    full += "## 全件カウンタ\n\n原行数と状態数/隣接後退回数を区別する。省略した同一状態もrepeat原行重みへ含める。\n"+G.table(["カウンタ", "値"], [[k, number(v)] for k, v in report["件数"].items()])+meaning+all_audits
    paths = [Path(__file__), ROOT/"scripts/レポート/設定結果レポート.py", G.CATALOG, G.MASTER, study/"計画.md", study/"条件.json", study/"固定.json", study/"入力台帳.json", source_manifest, study/"結果.json", case_path, *audit_paths,
             ROOT/"docs/議論/配信元VWAPとセッション起算を確認する.md"]
    paths += [ROOT/"scripts/VWAP入力"/n for n in names if n != "レポート.py"]
    for path, text in ((readme, summary+reproduction), (setting_path, mapping), (all_path, full)):
        path.write_text(text+G.provenance(paths, path), encoding="utf-8")
    return [readme, setting_path, all_path, case_path]


def main() -> None:
    """試行と表示先を読み取り保存監査だけを表示する。

    引数: なし。--study/--outputを読む。
    返り値: None。新しい売買・先着・入力抽出は呼ばない。
    """
    parser = argparse.ArgumentParser(description="配信VWAP入力監査の保存結果表示")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    print(json.dumps({"生成": [str(p) for p in run(study, (args.output or study).resolve())]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
