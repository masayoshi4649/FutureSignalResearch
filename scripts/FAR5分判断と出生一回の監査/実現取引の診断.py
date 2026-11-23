"""95の成立した実取引と保存MTMだけを12Actor別に診断する。"""

import argparse
from collections import defaultdict
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT / "scripts/FAR個別利益追尾の監査/診断.py"
OLD_SHA = "4f9d829811160899ca9962e6c8256105094e4d21d76945051d1a944eab1ed65e"
AGG_SHA = "193acf7f0ddcd6b532b52d7ac7a105e2a1f61905bb97368dfeb79c177c5f5395"
if hashlib.sha256(OLD_PATH.read_bytes()).hexdigest() != OLD_SHA:
    raise ValueError("固定94診断の由来SHA差")
SPEC = importlib.util.spec_from_file_location("固定94の完結玉診断", OLD_PATH)
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)
KEYS = tuple(("" if t == "N" else t + "_") + f"P0_C{c}_D{d}"
             for t in ("N", "B5", "B5Q") for c in (0, 5) for d in (0, 1))
COUNTERS = ("玉数", "新規枚数", "粗額円", "純額円", "黒字玉", "赤字玉", "同額玉", "正額円", "負額円", "保護起動玉") + tuple(
    p + s for p in ("u", "W") for s in ("正益玉", "正益後最終赤字玉", "正益後最終赤字額円", "初正益時全予約済赤字玉", "正益未観測赤字玉", "正益未観測赤字額円"))


def need(condition: bool, message: str) -> None:
    """
    機能: 保存値の集合/会計不一致を停止する。
    引数: condition(bool)は判定、message(str)は原因。
    返り値: None。不成立はValueError。
    """
    if not condition:
        raise ValueError(message)


def key_config(key: str) -> tuple:
    """
    機能: 95の明示12Actorだけを判断時計・滑り・遅延へ分ける。
    引数: key(str)は保存名。
    返り値: tupleはtiming(str)/slip(int)/delay(int)。
    """
    need(key in KEYS, "95 Actor集合")
    timing = "B5Q" if key.startswith("B5Q_") else "B5" if key.startswith("B5_") else "N"
    parts = key.split("_")
    return timing, int(parts[-2][1:]), int(parts[-1][1:])


def new_row() -> dict:
    """
    機能: 完結玉全件を走査する加算Counterを明示0で初期化する。
    引数: なし。
    返り値: dictは既知の加算項目。未知のMTM点は補完しない。
    """
    return {name: Decimal(0) for name in COUNTERS}


def finish_row(row: dict, key: str) -> None:
    """
    機能: 実玉純額の正負分解と実費用を照合し、分母付き指標を付ける。
    引数: row(dict)は全完結玉の加算、key(str)はActor。
    返り値: None。PF/勝率は分母0ならNone。
    """
    _, slip, _ = key_config(key)
    need(row["黒字玉"] + row["赤字玉"] + row["同額玉"] == row["玉数"], "勝敗の全玉分母")
    need(row["正額円"] + row["負額円"] == row["純額円"], "実玉正負/純額")
    row["指定手数料円"] = 77 * row["新規枚数"]
    row["仮定滑り円"] = 200 * slip * row["新規枚数"]
    row["手数料のみ控除円"] = row["粗額円"] - row["指定手数料円"]
    need(row["純額円"] == row["手数料のみ控除円"] - row["仮定滑り円"], "実玉費用の三列")
    for prefix in ("u", "W"):
        need(row[prefix + "正益後最終赤字玉"] + row[prefix + "正益未観測赤字玉"] == row["赤字玉"], "赤字玉の正益観測分解")
        need(row[prefix + "正益後最終赤字額円"] + row[prefix + "正益未観測赤字額円"] == row["負額円"], "赤字実額の正益観測分解")
    row["PF"] = row["正額円"] / -row["負額円"] if row["負額円"] else None
    row["黒字玉率"] = row["黒字玉"] / row["玉数"] if row["玉数"] else None


def joined_dd(sessions: list[dict]) -> Decimal:
    """
    機能: flatなセッション間の実現carryと保存場内MTM極値からDDを厳密連結する。
    引数: sessions(list[dict])は時刻順の純額円/場内最大DD円/場内MTM最大円/最小円。
    返り値: Decimalは円DD。全原板から極値を再生成する処理ではない。
    """
    cash = peak = drawdown = Decimal(0)
    for row in sessions:
        high, low, inside = (Decimal(row[n]) for n in ("場内MTM最大円", "場内MTM最小円", "場内最大DD円"))
        need(high >= 0 >= low and inside >= 0, "開始flatを含む場内極値")
        drawdown = max(drawdown, inside, peak - (cash + low))
        peak = max(peak, cash + high)
        cash += row["純額円"]
    return drawdown


def analyze(summary: Path, native_dir: Path) -> dict:
    """
    機能: 正式集計と54圧縮Nativeを結び、成立取引の12比較を保存値だけで作る。
    引数: summary(Path)は95結果、native_dir(Path)は54gzipの保存先。
    返り値: dictは診断/入力前後指紋。退出後価格・未参加の仮想利益は計算しない。
    """
    result = OLD.load(summary)
    need(result["試行"] == 95 and result["成功"] is True and result["scope"] == "正式"
         and result["場数"] == 54 and result["会計数"] == 648, "95正式保存648")
    need(result["集計コードSHA256"] == AGG_SHA and result["固定54場金額照合実施"] is True
         and result["入力前後不変"] is True and result["入力SHA256前"] == result["入力SHA256後"], "95保存検算の停止指紋")
    need(set(result["集計"]) == set(KEYS) and len(result["入力SHA256"]) == 54, "12Actor/54Native")
    before = {str(summary.resolve()): OLD.sha(summary), str(Path(__file__).resolve()): OLD.sha(Path(__file__)), str(OLD_PATH): OLD_SHA}
    rows = {key: new_row() for key in KEYS}
    sessions, groups = [], {}
    saved_rows = {(row["session"], row["key"]): row for row in result["場別"]}
    need(len(saved_rows) == 648, "場別一意")
    all_sessions = set()
    for name, expected in sorted(result["入力SHA256"].items()):
        path = (native_dir / (name + ".gz")).resolve()
        need(path.is_relative_to(native_dir.resolve()) and path.name == name + ".gz", "圧縮保存参照の境界")
        body = path.read_bytes()
        before[str(path)] = hashlib.sha256(body).hexdigest()
        plain = gzip.decompress(body)
        need(hashlib.sha256(plain).hexdigest() == expected, "元Nativeとgzip内容SHA一致")
        value = json.loads(plain, parse_float=Decimal, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        session = value["session"]
        need(session not in all_sessions and name == session + ".json", "場ID/名前一意")
        all_sessions.add(session)
        need(set(value["books"]) == set(KEYS), "全12金融本文")
        for key in KEYS:
            book = value["books"][key]
            need(book["finished"] is True and book["complete"] is True and book["failure"] == "", "完結実口座")
            row = new_row()
            for p in book["positions"]:
                OLD.add_position(row, p)
                # Source.kindは元段階であり、Actorが親に初めて実参加したかとは別。
                group = key + "/" + p["source"]["method"] + "/" + p["source"]["kind"]
                OLD.add_position(groups.setdefault(group, new_row()), p)
            for field in COUNTERS:
                rows[key][field] += row[field]
            finish_row(row, key)
            saved = saved_rows[(session, key)]
            need(row["玉数"] == saved["counts"]["positions"] and row["新規枚数"] == saved["totals"]["entry_quantity"]
                 and row["粗額円"] == saved["totals"]["gross_yen"] and row["純額円"] == saved["totals"]["net_yen"], "場の実玉/保存会計")
            account = book["account"]
            need(account["first"] is not None and account["last"] is not None
                 and account["first"]["equity"] == 0 and account["last"]["equity"] == row["純額円"]
                 and account["last"]["open_buy"] == account["last"]["open_sell"] == 0, "場の開始終了flat/carry")
            need(account["max_drawdown"] == saved["account_max_drawdown_yen"], "場内DD正本対応")
            sessions.append({"session": session, "key": key, **row,
                             "場内最大DD円": account["max_drawdown"], "場内MTM最大円": account["max"]["equity"],
                             "場内MTM最小円": account["min"]["equity"], "grid": book["grid_metrics"]})
    dates = sorted({s[:10] for s in all_sessions})
    need(len(dates) == 27 and all({d + "_Day", d + "_Night"} <= all_sessions for d in dates), "27開始日54場")
    by_pair = {(s["session"], s["key"]): s for s in sessions}
    daily = []
    for key in KEYS:
        chronological = []
        for date in dates:
            pair = [by_pair[(date + "_" + kind, key)] for kind in ("Day", "Night")]
            chronological.extend(pair)
            day = {field: sum(s[field] for s in pair) for field in COUNTERS}
            finish_row(day, key)
            daily.append({"開始日": date, "key": key, **day, "日内最大DD円": joined_dd(pair),
                          "セッション": [s["session"] for s in pair]})
        row = rows[key]
        finish_row(row, key)
        row.update({"場数": 54, "取引あり場数": sum(s["玉数"] > 0 for s in chronological),
                    "黒字場数": sum(s["純額円"] > 0 for s in chronological), "赤字場数": sum(s["純額円"] < 0 for s in chronological),
                    "同額場数": sum(s["純額円"] == 0 for s in chronological), "開始日数": 27,
                    "黒字開始日数": sum(s["純額円"] > 0 for s in daily if s["key"] == key),
                    "赤字開始日数": sum(s["純額円"] < 0 for s in daily if s["key"] == key),
                    "場内最大DD円": max(s["場内最大DD円"] for s in chronological),
                    "日内最大DD円": max(s["日内最大DD円"] for s in daily if s["key"] == key),
                    "全54場連結MTM最大DD円": joined_dd(chronological)})
        e = result["集計"][key]
        for ours, theirs in (("玉数", "positions"), ("新規枚数", "entry_quantity"), ("粗額円", "gross_yen"), ("純額円", "net_yen"),
                             ("指定手数料円", "fee_yen"), ("仮定滑り円", "slip_yen"), ("u正益玉", "unit_positive_positions"),
                             ("W正益玉", "whole_positive_positions"), ("u正益後最終赤字玉", "unit_positive_closed_negative"),
                             ("W正益後最終赤字玉", "whole_positive_closed_negative"), ("場内最大DD円", "max_session_mtm_drawdown_yen")):
            need(row[ours] == e[theirs], "全54正本加算:" + key + "/" + ours)
    for name, row in groups.items():
        finish_row(row, name.split("/")[0])
    comparisons = {}
    for name, parts in result["同実入口と実現額差"].items():
        b, a = name.split("対")
        values = {field: sum(p[field] for p in parts) for field in parts[0] if field not in ("session", "限定")}
        need(values["全差円"] == rows[b]["純額円"] - rows[a]["純額円"]
             == values["同実入口差円"] + values["取得変更差円"] - values["Aのみ円"] + values["Bのみ円"], "参加差と実現額分解")
        comparisons[name] = values
    need(all(OLD.sha(Path(path)) == value for path, value in before.items()), "診断の入力前後不変")
    detail_fields = ("玉数", "新規枚数", "粗額円", "指定手数料円", "仮定滑り円", "純額円", "正額円", "負額円", "黒字玉", "赤字玉", "同額玉", "PF")
    compact_sessions = [{k: s[k] for k in ("session", "key", *detail_fields, "場内最大DD円", "場内MTM最大円", "場内MTM最小円")} for s in sessions]
    compact_daily = [{k: s[k] for k in ("開始日", "key", *detail_fields, "日内最大DD円")} for s in daily]
    return {"試行": 95, "成功": True, "状態": "54既使用場の実現取引診断。新売買/閾値選定なし", "集計": rows,
            "セッション別": compact_sessions, "開始日別": compact_daily, "元手法と元段階別": groups, "実現額と参加差": comparisons,
            "評価方針": "成立した実取引の実現額と保有中のu/W・DDだけを評価。未参加/決済後の仮想利益や機会損失を算出しない。",
            "分母とDD": "PF=実玉最終純額の正額/負額絶対値。uは残玉1枚の両建て費用控除後、Wは既実現＋残玉評価。日内DDは開始日のDay→Nightをflat境界で現金carry連結。全54DDも保存場内max/min/DDから連結し、原板からの極値再生成は独立Raw監査の範囲。",
            "限定": "C0は指定feeのみ、C5は追加5pt片道を含む別運転。正益後最終赤字額は該当玉の最終純額合計。u未観測は観測間欠を含み得る。予約は初正益の保存phaseであり、放置や赤字化原因とは単独断定しない。Nの出生は定時外なのでgrid新規0を全新規0と呼ばない。CurrentPriceTimeは価格項目の時計で独立受信時計ではなく、両市場の真の到着順は検証不能。同時刻TOPIX先行は再生規則。実mini板の流動性と5ptの実測は未確認。新技法gate追加0、元FAR全面同値false、未使用日0/未知安定未証明。",
            "入力SHA256": before, "入力前後不変": True, "由来94診断SHA256": OLD_SHA, "由来95集計SHA256": AGG_SHA,
            "未実施": {"金融再生": 0, "原板本文読取": 0, "ViewerAPI": 0, "退出後の仮想利益": 0, "未参加仮想利益": 0, "資本金ROI": None}}


def fmt(value: object) -> str:
    """
    機能: 円と半円を丸めず、比率は表示だけ3桁にする。
    引数: value(object)は数値又はNone。
    返り値: strは表示用。
    """
    if value is None:
        return "未定義"
    x = Decimal(value)
    return f"{x:,.0f}" if x == x.to_integral_value() else f"{x:,.1f}"


def render(proof: dict) -> str:
    """
    機能: 成立取引の実額・損失内訳・DDを12Actorの短い表へまとめる。
    引数: proof(dict)は検算済み診断。
    返り値: strはMarkdown。将来の退出後/未参加価格を評価しない。
    """
    lines = ["# 95：実現取引と利益保護の診断", "",
             "54既使用セッション（27開始日）。N＝元の連続出生、B5＝出生後の最初の5分枠、B5Q＝B5＋開始30分見送り。P0保護は共通。C0が指定手数料のみの主比較、C5は片道5pt追加を含む別運転。", "",
             "実現した各Actorの収支を比較する。未参加や退出後の仮想利益・機会損失は計算しない。", "",
             "| Actor | 玉/枚 | gross円 | 指定fee円 | 仮定slip円 | net円 | 正額/負額円 | PF | 黒/赤/同玉 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        r = proof["集計"][key]
        pf = "未定義" if r["PF"] is None else f"{r['PF']:.3f}"
        lines.append(f"| {key} | {fmt(r['玉数'])}/{fmt(r['新規枚数'])} | {fmt(r['粗額円'])} | {fmt(r['指定手数料円'])} | {fmt(r['仮定滑り円'])} | {fmt(r['純額円'])} | {fmt(r['正額円'])}/{fmt(r['負額円'])} | {pf} | {fmt(r['黒字玉'])}/{fmt(r['赤字玉'])}/{fmt(r['同額玉'])} |")
    lines += ["", "正額と負額は完結した実玉の最終純額を正負に分けた合計。PFの分母は負額の絶対値であり、資本金ROIではない。C5の手数料のみ列はC5運転のgrossからfeeだけを引いた金額で、C0と同じ約定を仮定した列ではない。", "",
              "| Actor | u後赤字玉/u正益玉 | u後赤字額円 | u未観測赤字玉/額円 | W後赤字玉/W正益玉 | W後赤字額円 | W未観測赤字玉/額円 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        r = proof["集計"][key]
        lines.append(f"| {key} | {fmt(r['u正益後最終赤字玉'])}/{fmt(r['u正益玉'])} | {fmt(r['u正益後最終赤字額円'])} | {fmt(r['u正益未観測赤字玉'])}/{fmt(r['u正益未観測赤字額円'])} | {fmt(r['W正益後最終赤字玉'])}/{fmt(r['W正益玉'])} | {fmt(r['W正益後最終赤字額円'])} | {fmt(r['W正益未観測赤字玉'])}/{fmt(r['W正益未観測赤字額円'])} |")
    lines += ["", "uは残玉1枚の取得価格から返済BBOまでの両建て費用控除後評価、Wは実現済み純額＋残玉評価。正益後赤字額と未観測赤字額の和は、それぞれ全負額へ一致する。分母を混ぜず、赤字額は最終実額であって正益時点との差や将来ピークとの差ではない。", "",
              "| Actor | 取引あり/54場 | 黒/赤/同場 | 黒/赤開始日/27 | 場内最大DD円 | 日内最大DD円 | 全54連結MTM DD円 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        r = proof["集計"][key]
        lines.append(f"| {key} | {r['取引あり場数']}/54 | {r['黒字場数']}/{r['赤字場数']}/{r['同額場数']} | {r['黒字開始日数']}/{r['赤字開始日数']}/27 | {fmt(r['場内最大DD円'])} | {fmt(r['日内最大DD円'])} | {fmt(r['全54場連結MTM最大DD円'])} |")
    lines += ["", "日内DDは開始日単位でDay→Nightを連結した口座MTM。場内DD/日内DD/全54連結DDを区別する。保存場内極値とDDを再集約したもので、全原行取り落としは独立原板監査へ依存する。開始日別・セッション別の全実額は診断JSONに置く。", "",
              "| 比較（B対A） | net差円 | 同出生/同実/取得変更 | Aのみ/Bのみ | 同実差/取得変更差円 | Aのみ額/Bのみ額円 |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, r in proof["実現額と参加差"].items():
        lines.append(f"| {name} | {fmt(r['全差円'])} | {r['同Source出生']}/{r['同実入口']}/{r['取得変更']} | {r['Aのみ']}/{r['Bのみ']} | {fmt(r['同実入口差円'])}/{fmt(r['取得変更差円'])} | {fmt(r['Aのみ円'])}/{fmt(r['Bのみ円'])} |")
    lines += ["", "全差＝同実入口差＋取得変更差−Aのみ実額＋Bのみ実額。参加差は成立した実取引の実額の分類で、未参加の仮想利益の評価ではない。判断時刻・Source取得・容量が変わるため、改善額を保護手法単独の効果としない。", "", proof["限定"], ""]
    return "\n".join(lines)


def main() -> None:
    """
    機能: 明示正式保存値から新規診断JSON/MDを作り、同入力から一致を照合する。
    引数: --summary/--native/--out(Path)、--check(bool)は既存出力の再生成一致。
    返り値: None。保存入力以外の市場/金融/APIは呼ばない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("summary", "native", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    proof = analyze(args.summary, args.native)
    bodies = {"実現取引の診断.json": json.dumps(proof, ensure_ascii=False, indent=2, default=OLD.serial, allow_nan=False) + "\n",
              "実現取引の診断.md": render(proof)}
    if args.check:
        for name, text in bodies.items():
            need((args.out / name).read_bytes() == text.encode("utf-8"), "診断の再生成一致:" + name)
    else:
        need(not args.out.exists(), "新規出力先")
        args.out.mkdir(parents=True)
        for name, text in bodies.items():
            (args.out / name).write_bytes(text.encode("utf-8"))
    print(json.dumps({"成功": True, "check": args.check, "口座": 12, "場口座": 648,
                      "ファイル": {name: OLD.sha(args.out / name) for name in bodies}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
