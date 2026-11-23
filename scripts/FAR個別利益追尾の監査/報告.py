"""94の完了した保存正本だけからREADMEと設定結果を新規生成する。"""

import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00094_連続出生を固定した個別利益追尾"
SETTINGS_SHA = "f469f98d9028ce42d84b2ceaa27b1a438e2402c2dfca4c6df4b182a3febeee78"
README_SHA = "d812970ca87ae4444bd8ab4d84f7123dce078fe593e722d61fc3b6e88ff7d580"
PLAN_BEGIN = "<!-- REPORT94:PLAN:BEGIN -->\n"
PLAN_END = "<!-- REPORT94:PLAN:END -->\n"
STATE_BEGIN = "<!-- REPORT94:STATE:BEGIN -->\n"
STATE_END = "<!-- REPORT94:STATE:END -->\n"
RESULT_BEGIN = "<!-- REPORT94:RESULT:BEGIN -->\n"
RESULT_END = "<!-- REPORT94:RESULT:END -->\n"
KEYS = tuple(f"{p}_C{c}_D{d}" for p in ("S0", "P0", "P1") for c in (0, 5) for d in (0, 1))
INPUT_NAMES = ("result", "diagnostics", "raw", "viewer", "inputs_before", "inputs", "readme", "settings")


def need(condition: bool, message: str) -> None:
    """
    機能: 不明や不一致を0に補完せず停止する。
    引数: condition(bool)は条件、message(str)は説明。
    返り値: None。不成立はValueError。
    """
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    """
    機能: 明示された保存正本のbytes指紋を取得する。
    引数: path(Path)は入力又は生成物。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    """
    機能: 保存JSONを十進数で読み、非有限の定数を拒否する。
    引数: path(Path)は保存正本。
    返り値: dictは本文。
    """
    def bad(value):
        """
        機能: NaN等の非標準JSON定数を拒否する。
        引数: value(str)は定数名。
        返り値: None。常に例外。
        """
        raise ValueError(value)
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal, parse_constant=bad)


def numeric(value, label: str) -> Decimal:
    """
    機能: bool/nullを金額と扱わず有限値に統一する。
    引数: value(any)は数値、label(str)は項目名。
    返り値: Decimalは有限値。
    """
    need(type(value) in (int, float, Decimal), label + "の数値型")
    number = Decimal(str(value)); need(number.is_finite(), label + "の有限値")
    return number


def sparse(row: dict, name: str) -> Decimal:
    """
    機能: 完結全玉を走査した診断の疎な加算Counterだけを0扱いする。
    引数: row(dict)はRoot診断集計、name(str)は既知の加算項目。
    返り値: Decimalは存在値又は論理的な件数0。
    """
    return numeric(row.get(name, 0), name)


def fmt(value, digits: int | None = None) -> str:
    """
    機能: 金額の半円を保持し、比率だけを指定桁へ整形する。
    引数: value(number|None)は表示値、digits(int|None)は小数桁。
    返り値: strは日本語表向け文字列。
    """
    if value is None:
        return "未定義"
    n = numeric(value, "表示値")
    if digits is not None:
        return f"{n:,.{digits}f}"
    return f"{n:,.0f}" if n == n.to_integral_value() else f"{n:,.1f}"


def link(path: Path) -> str:
    """
    機能: work出力を正式へ移しても変わらない正式試行基準の相対リンクを作る。
    引数: path(Path)は明示された入力。
    返り値: strはスラッシュ区切りの相対参照。
    """
    return os.path.relpath(path.resolve(), STUDY).replace("\\", "/")


def original(text: str, expected_sha: str) -> str:
    """
    機能: 生の計画又は生成済み文書から元計画bytesを厳密復元する。
    引数: text(str)は文書、expected_sha(str)は固定計画SHA。
    返り値: strは元計画。未完/重複markerや閾値変更は拒否する。
    """
    markers = (PLAN_BEGIN, PLAN_END, STATE_BEGIN, STATE_END, RESULT_BEGIN, RESULT_END)
    if any(marker in text for marker in markers):
        need(all(text.count(marker) == 1 for marker in markers), "report markerの欠落/重複")
        need(text.index(STATE_BEGIN) < text.index(STATE_END) < text.index(PLAN_BEGIN) < text.index(PLAN_END)
             < text.index(RESULT_BEGIN) < text.index(RESULT_END), "report marker順序")
        text = text.split(PLAN_BEGIN, 1)[1].split(PLAN_END, 1)[0]
    need(hashlib.sha256(text.encode("utf-8")).hexdigest() == expected_sha, "固定計画の内容差")
    return text


def mapped_sha(mapping: dict, path: Path) -> str:
    """
    機能: 結合先の保存Pathを指紋写像から一意に選ぶ。
    引数: mapping(dict)は指紋、path(Path)は対象。
    返り値: strは保存SHA。元ファイルの再走査はしない。
    """
    found = [v for k, v in mapping.items() if Path(k).resolve() == path.resolve()]
    need(len(found) == 1, "証拠の入力path結合: " + str(path))
    return found[0]


def prepare(args) -> dict:
    """
    機能: 完了正本8Pathを結合し、文書生成に必要な保存値だけ検査する。
    引数: args(Namespace)は明示された結果/診断/Raw/Viewer/前後入力/計画2文書。
    返り値: dictは生成context。Native/原板/Source/MTMは再計算しない。
    """
    paths = {name: getattr(args, name).resolve() for name in INPUT_NAMES}
    physical = {name: sha(path) for name, path in paths.items()}
    plans = {"settings": original(paths["settings"].read_bytes().decode("utf-8"), SETTINGS_SHA),
             "readme": original(paths["readme"].read_bytes().decode("utf-8"), README_SHA)}
    settings = plans["settings"]
    table = settings.split("## 継承設定", 1)[0]
    rows = [line for line in table.splitlines() if re.match(r"^\| [ICPVXBME]\d{2} \|", line)]
    need(len(rows) == 55 and all(len(line.split("|")) == 13 for line in rows), "55×9表")
    need(len(re.findall(r"^\| (?:S\d{2}|N\d{2}|T\d{2}) \|", settings, re.M)) == 30, "30設定")
    result, diag, raw, viewer, before, after = (load(paths[name]) for name in INPUT_NAMES[:6])
    need(result["試行"] == 94 and result["成功"] is True and result["scope"] == "正式"
         and result["場数"] == 54 and result["Actor数"] == 12 and result["会計数"] == 648
         and result["固定54場金額照合実施"] is True and result["入力前後不変"] is True, "正式54集計完了")
    need(set(result["集計"]) == set(KEYS) and len(result["場別"]) == 648, "12Actor/648場別")
    need(diag["試行"] == 94 and diag["成功"] is True and diag["入力前後不変"] is True
         and set(diag["集計"]) == set(KEYS), "事後診断完了")
    need(mapped_sha(diag["入力SHA256"], paths["result"]) == physical["result"], "診断/結果SHA結合")
    sessions = {row["session"] for row in result["場別"]}
    need(len(sessions) == 54 and len({(row["session"], row["key"]) for row in result["場別"]}) == 648, "全場会計一意")
    need(raw["成功"] is True and raw["セッション数"] == 54 and raw["会計数"] == 648
         and raw["不一致数"] == 0 and raw["入力前後不変"] is True, "全経路Raw完了")
    need(len(raw["details"]) == 54 and {row["session"] for row in raw["details"]} == sessions, "Raw54場集合")
    for row in raw["details"]:
        need(row["成功"] is True and row["会計数"] == 12 and row["不一致数"] == 0
             and row["全経路MTM"] is True and row["入力前後不変"] is True, "Raw各場完了")
        source = [v for k, v in row["入力SHA256"].items() if Path(k).name == row["session"] + ".json"]
        need(len(source) == 1 and source[0] == result["入力SHA256"][row["session"] + ".json"], "Raw/Native指紋結合")
    need(viewer["試行"] == 94 and viewer["成功"] is True and viewer["scope"] == "正式"
         and viewer["予定資源"] == viewer["完了資源"] == 648 and viewer["全資源検証完了"] is True
         and viewer["不一致数"] == 0 and not viewer["APIエラー"] and viewer["入力不変"] is True, "648Viewer完了")
    need(viewer["結果SHA256"] == physical["result"], "Viewer/結果SHA結合")
    need(before == after and after["試行"] == 94 and after["場数"] == 54, "固定入力前後の辞書全文一致")
    need(len(after["原入力"]) == 324 and len(after["純戦略"]) == 43
         and len(after["固定93コード"]) == 11 and len(after["固定93正本"]) == 313, "固定入力/基準の分母")
    need(after["台帳SHA256"] == "b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42"
         and after["基準93完了SHA256"] == "e811571a876f3fdc2f5ba7c09b3906c84db9e380ef89c24b920e5c3f199a2a37", "固定基準SHA")
    sums = {key: {"gross_yen": Decimal(0), "fee_yen": Decimal(0), "slip_yen": Decimal(0), "net_yen": Decimal(0), "DD": Decimal(0), "赤字場": 0, "稼働場": 0} for key in KEYS}
    for row in result["場別"]:
        out = sums[row["key"]]
        for name in ("gross_yen", "fee_yen", "slip_yen", "net_yen"):
            out[name] += numeric(row["totals"][name], name)
        out["DD"] = max(out["DD"], numeric(row["account_max_drawdown_yen"], "場内DD"))
        out["赤字場"] += row["totals"]["net_yen"] < 0
        out["稼働場"] += row["counts"]["positions"] > 0
    for key in KEYS:
        d, a = diag["集計"][key], result["集計"][key]
        for field in ("gross_yen", "fee_yen", "slip_yen", "net_yen"):
            need(sums[key][field] == numeric(a[field], field), "集計/場別加算")
        need(d["玉数"] == a["positions"] and d["新規枚数"] == a["entry_quantity"]
             and d["粗額円"] == a["gross_yen"] and d["純額円"] == a["net_yen"], "診断/会計結合")
        positive, negative = numeric(d["正額円"], "正額"), sparse(d, "負額円")
        need(positive >= 0 >= negative and positive + negative == d["純額円"], "正負額加算")
        need(sparse(d, "黒字玉") + sparse(d, "赤字玉") + sparse(d, "同額玉") == d["玉数"], "実玉勝敗分母")
        if negative:
            need(d["PF"] is not None and abs(numeric(d["PF"], "PF") - positive / -negative) <= Decimal("1e-12") * max(1, abs(positive / -negative)), "PF定義")
        else:
            need(d["PF"] is None, "負額0のPF未定義")
        for label, count_field, negative_field in (("u", "unit_positive_positions", "unit_positive_closed_negative"), ("W", "whole_positive_positions", "whole_positive_closed_negative")):
            need(d[label + "正益玉"] == a[count_field] and sparse(d, label + "正益後最終赤字玉") == a[negative_field], "u/W分母結合")
            need(sparse(d, label + "正益後最終赤字玉") + sparse(d, label + "正益未観測赤字玉") == sparse(d, "赤字玉"), "赤字内訳")
            need(sparse(d, label + "正益後最終赤字額円") + sparse(d, label + "正益未観測赤字額円") == negative, "赤字額内訳")
        need(d["開始日数"] == 27 and sparse(d, "黒字開始日数") + sparse(d, "赤字開始日数") <= 27, "開始日27分母")
    need(result["集計"]["S0_C0_D0"]["gross_yen"] == result["集計"]["S0_C5_D0"]["gross_yen"] == 2898000
         and result["集計"]["S0_C0_D0"]["net_yen"] == 2839865 and result["集計"]["S0_C5_D0"]["net_yen"] == 2084865, "S0固定3額")
    for name, rows in result["同実入口と参加差"].items():
        need(len(rows) == 54 and {r["session"] for r in rows} == sessions, "比較54場")
        for row in rows:
            need(row["全差円"] == row["同実入口差円"] + row["取得変更差円"] - row["Aのみ円"] + row["Bのみ円"], "参加差加算")
    normalized = {str(paths[name]): physical[name] for name in INPUT_NAMES}
    normalized[str(paths["readme"])] = README_SHA; normalized[str(paths["settings"])] = SETTINGS_SHA
    return {"paths": paths, "physical": physical, "normalized": normalized, "plans": plans,
            "result": result, "diag": diag, "raw": raw, "viewer": viewer, "inputs": after, "session_sums": sums}


def tables(context: dict, short: bool = False) -> str:
    """
    機能: 検算済み正本から12評価の実現会計/赤字化/実現額比較表を作る。
    引数: context(dict)はprepare結果、short(bool)はREADME向け。
    返り値: strは結果Markdown。
    """
    result, diag = context["result"], context["diag"]
    lines = ["## 実行後の結果", "", "C0は指定手数料のみの主条件、C5は起動/床にも片道5pt仮定を使う別運転。全54場は既使用期間である。",
             "評価は各Actorの実現利益/損失・正負額・PF・u/W正益後の最終赤字額・DD・取引数を主とする。未参加や決済後の仮想利益、S0の将来ピークからの取り逃がし（機会損失）は評価・最小化しない。元手法と新手法の実現額は比較する。", ""]
    if short:
        lines += ["| Actor | 実玉/枚 | 正額円 | 負額円 | 純額円 | PF | u正益後赤字/正益玉 | 最大場内DD円 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    else:
        lines += ["| 評価 | Actor | 実玉/枚 | gross円 | 手数料円 | 仮定滑り円 | gross−fee円 | net円 | 正額円 | 負額円 | PF |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for n, key in enumerate(KEYS, 1):
        a, d = result["集計"][key], diag["集計"][key]
        if short:
            lines.append(f"| {key} | {fmt(d['玉数'])}/{fmt(d['新規枚数'])} | {fmt(d['正額円'])} | {fmt(sparse(d,'負額円'))} | {fmt(d['純額円'])} | {fmt(d['PF'],3)} | {fmt(sparse(d,'u正益後最終赤字玉'))}/{fmt(d['u正益玉'])} | {fmt(a['max_session_mtm_drawdown_yen'])} |")
        else:
            lines.append(f"| R{n:02} | {key} | {fmt(d['玉数'])}/{fmt(d['新規枚数'])} | {fmt(a['gross_yen'])} | {fmt(a['fee_yen'])} | {fmt(a['slip_yen'])} | {fmt(a['gross_minus_fee_yen'])} | {fmt(a['net_yen'])} | {fmt(d['正額円'])} | {fmt(sparse(d,'負額円'))} | {fmt(d['PF'],3)} |")
    lines += ["", "正額/負額/PFは各Actorの実玉netで集計。PF=正額合計÷|負額合計|、負額0なら未定義。C5のgross−feeもC5の取得/退出列の会計で、C0と同じ取引列を意味しない。", "",
              "### 正益後の回収と分母", "",
              "| Actor | u正益玉 | u後最終赤字玉/円 | W正益玉 | W後最終赤字玉/円 | u未観測の赤字玉/円 | u初回全予約済の赤字玉 | 保護起動玉 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        d = diag["集計"][key]
        lines.append(f"| {key} | {fmt(d['u正益玉'])} | {fmt(sparse(d,'u正益後最終赤字玉'))}/{fmt(sparse(d,'u正益後最終赤字額円'))} | {fmt(d['W正益玉'])} | {fmt(sparse(d,'W正益後最終赤字玉'))}/{fmt(sparse(d,'W正益後最終赤字額円'))} | {fmt(sparse(d,'u正益未観測赤字玉'))}/{fmt(sparse(d,'u正益未観測赤字額円'))} | {fmt(sparse(d,'u初正益時全予約済赤字玉'))} | {fmt(sparse(d,'保護起動玉'))} |")
    lines += ["", "uは未返済単価益、Wは配賦済み確定純額＋残玉清算額。起動はu>0であり、W>0と同義ではない。『未観測』には無効/欠測区間も含み得るため、一度も利益がなかったと断定しない。初回に全量返済予約済みなら新しい保護要求を出す余地がない。途中の0以下戻りと最終赤字も別である。", "",
              "### セッションと同実入口", "",
              "| Actor | 取引あり/54場 | 赤字/54場 | 開始日黒字/赤字（27日） | 最大場内MTM DD円 |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        d, a = diag["集計"][key], result["集計"][key]
        lines.append(f"| {key} | {fmt(a['active_sessions'])}/54 | {fmt(a['negative_sessions'])}/54 | {fmt(sparse(d,'黒字開始日数'))}/{fmt(sparse(d,'赤字開始日数'))} | {fmt(a['max_session_mtm_drawdown_yen'])} |")
    lines += ["", "開始日はDay/Nightを合算した27日。場内MTMはP/U・両方向を同時刻で合算し、fill前/後を評価した。表は各場DDの最大値であり、54場を連結した期間DDの値ではない。未知気配区間を含めた真の最悪値や、資本金に対するROIは未保証。", "",
              "| 比較 B対A | 同実入口 | 取得変更 | Aのみ/Bのみ | 全差円 | 同実退出差円 | 取得変更差円 | Aのみ円 | Bのみ円 | 同実赤→黒/黒→赤 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, rows in result["同実入口と参加差"].items():
        total = lambda field: sum((r[field] for r in rows), Decimal(0))
        lines.append(f"| {name} | {fmt(total('同実入口'))} | {fmt(total('取得変更'))} | {fmt(total('Aのみ'))}/{fmt(total('Bのみ'))} | {fmt(total('全差円'))} | {fmt(total('同実入口差円'))} | {fmt(total('取得変更差円'))} | {fmt(total('Aのみ円'))} | {fmt(total('Bのみ円'))} | {fmt(total('同実入口の赤字から黒字'))}/{fmt(total('同実入口の黒字から赤字'))} |")
    lines += ["", "全差=同実入口差＋取得変更差−Aのみ円＋Bのみ円。表の金額は各Actorで実際に実現した額の比較であり、未参加側の仮想利益ではない。同実入口は元出生に加え要求時刻・方向・実取得時刻/価格/量・Index/物理行が一致するもの。D1の容量/参加差、保護後の空きによる別出生の採用を、保護単独の退出差へ混ぜない。", ""]
    return "\n".join(lines)


def render(context: dict, name: str) -> str:
    """
    機能: 原計画をbytes復元可能に保持し、現在状態と正本実績を付加する。
    引数: context(dict)は検算値、name(str)はreadme又はsettings。
    返り値: strは生成文書。
    """
    p = context["paths"]
    header = ("# 00094：連続出生を固定した個別利益追尾" + ("・設定と結果" if name == "settings" else "") + "（実行済み）\n\n"
              "**54既使用場・12Actor/648会計の実行と独立検査が完了。以下の原計画内の『未実行』は作成時点の記述であり、現在結果は末尾の実行後欄にある。**\n\n"
              "主C0と動的感度C5を分け、元FAR全面同値=false、新5分=false、未知期間の安定利益は未証明を保持する。Source93固定は93 Nativeへの同値であり、元FARの全面同値へ意味を広げない。\n\n"
              "**最新評価方針：手法の実現利益/損失を評価し、未参加・決済後の仮想利益や将来ピークからの取り逃がしは評価対象にしない。元手法と新手法の実現額比較は行う。原計画内の異なる評価表現は当時の記録として保持する。**\n\n")
    body = tables(context, short=name == "readme")
    raw, viewer = context["raw"], context["viewer"]
    body += ("\n### 正本と検査範囲\n\n"
             f"- [独立集計]({link(p['result'])})・[事後診断]({link(p['diagnostics'])})・[Viewer一覧]({link(p['result'].with_name('一覧.resources.json'))})。実現損益の比較であり、将来のピークからの取り逃がしは評価しない。事後の差額上位例も入口へ読み戻さない。\n"
             f"- [原板/保護の独立照合]({link(p['raw'])})：54場/648会計、{fmt(raw['照合項目数'])}項目差0。保存Source通知と全適格原行MTMを照合し、新しいSource生成はしない。\n"
             f"- [Viewer照合]({link(p['viewer'])})：648資源、{fmt(viewer['照合項目数'])}項目差0。保存全約定/半円費用/終了所有0のAPI一致。mini固有板・実執行・MTM極値の証明とは分ける。\n"
             f"- [固定入力の前]({link(p['inputs_before'])})/[後]({link(p['inputs'])})：324入力・純戦略43・93コード11・93正本313と94実装群の保存辞書が全文一致。報告生成器は原板hashや金融再生を再実行しない。\n\n"
             "- [再現手順](再現手順.md)・[条件](条件.json)・[評価方針更新](評価方針更新.json)・[利益保護の実作用](利益保護の実作用.md)。固定条件と最新の実現損益中心の評価範囲、実際の注文への作用を参照できる。\n\n"
             "54場はいずれも研究で既使用であり探索外確認ではない。ラージBBOをmini代理にした模型。C5片道5ptは実測ではない。名目建値/費用床は次正常行の実純額を保証せず、未予約残だけを保護する。正益後赤字の件数減だけで改善を判定せず、各Actorの実現正負額・純額・PF・DD・取引数を併せて読む。資本金不明の全額ROIは算出しない。\n")
    return (STATE_BEGIN + header + STATE_END + "\n<details>\n<summary>固定した原計画・閾値（作成時点の未実行記述）</summary>\n\n"
            + PLAN_BEGIN + context["plans"][name] + PLAN_END + "\n</details>\n\n" + RESULT_BEGIN + body + RESULT_END)


def generation(context: dict, outputs: dict) -> dict:
    """
    機能: 正規化した入力と2出力の指紋を小型生成証拠へまとめる。
    引数: context(dict)は検算値、outputs(dict[str,str])は生成2本文。
    返り値: dictは再実行可能な生成証拠。
    """
    return {"試行": 94, "成功": True, "生成対象": ["README.md", "設定と結果.md"],
            "正規化入力SHA256": context["normalized"], "原計画SHA256": {"README.md": README_SHA, "設定と結果.md": SETTINGS_SHA},
            "出力SHA256": {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in outputs.items()},
            "生成コードSHA256": sha(Path(__file__)), "入力検査": "計画/生成済み文書をPLAN markerから固定原文へ復元。他6正本はbytes SHA。入力物理bytesは各実行内で前後一致。",
            "全495セルと30設定": "固定原文SHA復元により不変", "実結果": "54既使用場/12Actor/648会計/648Viewer",
            "元FAR全面同値": False, "新5分": False, "未知安定性": "未証明", "原板本文読取とhash再実行": 0, "新金融再生": 0}


def main() -> None:
    """
    機能: 完了正本から2文書を新規生成、又は既存生成物を再生成一致で検査する。
    引数: --result/diagnostics/raw/viewer/inputs-before/inputs/readme/settings(Path)、--out(Path)、--check(bool)。
    返り値: None。正式文書を自動上書きせず、差があれば非0。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in INPUT_NAMES:
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True); parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    need(args.out.exists() if args.check else not args.out.exists(), "出力は新規、checkは既存のみ")
    context = prepare(args)
    outputs = {"README.md": render(context, "readme"), "設定と結果.md": render(context, "settings")}
    for name, expected in (("readme", README_SHA), ("settings", SETTINGS_SHA)):
        text = outputs["README.md" if name == "readme" else "設定と結果.md"]
        original(text, expected)
    proof = generation(context, outputs)
    if args.check:
        for name, expected in outputs.items():
            need((args.out / name).read_bytes() == expected.encode("utf-8"), "生成文書差:" + name)
        need(load(args.out / "生成証拠.json") == proof, "生成証拠差")
        for name in ("readme", "settings"):
            text = context["paths"][name].read_bytes().decode("utf-8")
            if PLAN_BEGIN in text:
                need(text == outputs["README.md" if name == "readme" else "設定と結果.md"], "入力生成済み文書の手修正差")
    else:
        args.out.mkdir(parents=True)
        for name, text in outputs.items(): (args.out / name).write_text(text, encoding="utf-8", newline="\n")
        (args.out / "生成証拠.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    need(all(sha(context["paths"][name]) == expected for name, expected in context["physical"].items()), "入力前後差")
    print(json.dumps({"成功": True, "check": args.check, "原計画復元": True, "出力SHA256": proof["出力SHA256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
