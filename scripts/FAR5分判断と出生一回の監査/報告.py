"""95の完了した保存正本から、事前本文を保持したREADME/設定結果を新規生成する。"""

import argparse
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import types


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00095_5分判断と開始30分見送り"
FIXED = ROOT / "scripts/FAR個別利益追尾の監査/報告.py"
FIXED_SHA = "c52d2f5f63570d8b2fd9427b308b4f34f3f153abbd84cc2ff676e3352d417df8"
if hashlib.sha256(FIXED.read_bytes()).hexdigest() != FIXED_SHA:
    raise ValueError("固定94報告部品のSHA差")
SPEC = importlib.util.spec_from_file_location("95への固定報告部品", FIXED)
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)
need, sha, load, fmt = OLD.need, OLD.sha, OLD.load, OLD.fmt
SETTINGS_SHA = "b6b0d4e650ba07615c276e04ac2a035421d0b73279b11b8a0566a8bf3ece8c22"
README_SHA = "88ef4f32908eb4364d46c2f4528e03b3a0c1d86b9ee93362619dd5a27262c8da"
AGG_SHA = "193acf7f0ddcd6b532b52d7ac7a105e2a1f61905bb97368dfeb79c177c5f5395"
KEYS = tuple(("" if t == "N" else t + "_") + f"P0_C{c}_D{d}"
             for t in ("N", "B5", "B5Q") for c in (0, 5) for d in (0, 1))
INPUT_NAMES = ("result", "diagnostics", "raw", "viewer", "inputs", "readme", "settings")
MARKERS = {name: getattr(OLD, name).replace("REPORT94", "REPORT95")
           for name in ("PLAN_BEGIN", "PLAN_END", "STATE_BEGIN", "STATE_END", "RESULT_BEGIN", "RESULT_END")}
globals().update(MARKERS)
ORIGINAL_NAMESPACE = dict(vars(OLD))
ORIGINAL_NAMESPACE.update(MARKERS)
original = types.FunctionType(OLD.original.__code__, ORIGINAL_NAMESPACE, "95の原計画復元")


def link(path: Path) -> str:
    """
    機能: work出力から正式へ同体copyしても有効な正式試行基準リンクを作る。
    引数: path(Path)は明示入力。
    返り値: strは正式試行からの相対参照。
    """
    return os.path.relpath(path.resolve(), STUDY).replace("\\", "/")


def prepare(args) -> dict:
    """
    機能: 保存正本7Pathの完了・指紋・分母と固定事前本文だけを照合する。
    引数: args(Namespace)は結果/診断/原板/Viewer/入力照合/README/設定。
    返り値: dictは生成context。原板hash/Native/金融/APIを再実行しない。
    """
    paths = {name: getattr(args, name).resolve() for name in INPUT_NAMES}
    physical = {name: sha(path) for name, path in paths.items()}
    plans = {name: original(paths[name].read_bytes().decode("utf-8"), expected)
             for name, expected in (("readme", README_SHA), ("settings", SETTINGS_SHA))}
    settings = plans["settings"]
    cells = [s for s in settings.splitlines() if re.match(r"^\| [ICPVXBME]\d{2} \|", s)]
    need(len(cells) == 55 and all(len(s.split("|")) == 13 for s in cells), "55×9固定表")
    need(len(re.findall(r"^\| (?:S|N|G)\d{2} \|", settings, re.M)) == 36, "36固定設定")
    need(re.findall(r"^\| (R\d{2}) \|", settings, re.M) == [f"R{i:02}" for i in range(1, 13)], "事前12評価")
    result, diag, raw, viewer, inputs = (load(paths[n]) for n in INPUT_NAMES[:5])
    need(result["試行"] == 95 and result["成功"] is True and result["scope"] == "正式" and result["場数"] == 54
         and result["会計数"] == 648 and result["Actor数"] == 12 and result["集計コードSHA256"] == AGG_SHA
         and result["固定54場金額照合実施"] is True and result["入力前後不変"] is True, "正式保存会計完了")
    need(set(result["集計"]) == set(diag["集計"]) == set(KEYS), "12Actorの結果/診断集合")
    need(diag["試行"] == 95 and diag["成功"] is True and diag["入力前後不変"] is True
         and diag["由来95集計SHA256"] == AGG_SHA, "95実現診断完了")
    need(OLD.mapped_sha(diag["入力SHA256"], paths["result"]) == physical["result"], "診断/結果指紋")
    sessions = {r["session"] for r in result["場別"]}
    need(len(sessions) == 54 and len(result["場別"]) == len({(r["session"], r["key"]) for r in result["場別"]}) == 648, "54場648口座一意")
    need(raw["成功"] is True and raw["セッション数"] == 54 and raw["会計数"] == 648
         and raw["N基準会計数"] == 216 and raw["不一致数"] == 0 and raw["入力前後不変"] is True
         and len(raw["details"]) == 54 and {r["session"] for r in raw["details"]} == sessions, "独立境界/MTM原板照合完了")
    for row in raw["details"]:
        need(row["成功"] is True and row["会計数"] == 12 and row["N基準会計数"] == 4
             and row["不一致数"] == 0 and row["入力前後不変"] is True, "原板各場完了")
        found = [v for k, v in row["入力SHA256"].items() if Path(k).name == row["session"] + ".json"]
        need(len(found) == 1 and found[0] == result["入力SHA256"][row["session"] + ".json"], "Raw/Nativeの指紋結合")
    need(viewer["試行"] == 95 and viewer["成功"] is True and viewer["scope"] == "正式"
         and viewer["予定資源"] == viewer["完了資源"] == 648 and viewer["全資源検証完了"] is True
         and viewer["不一致数"] == 0 and not viewer["APIエラー"] and viewer["入力不変"] is True
         and viewer["結果SHA256"] == physical["result"], "全648Viewer保存会計完了")
    need(inputs["試行"] == 95 and inputs["成功"] is True and inputs["保存辞書全文一致"] is True
         and inputs["前SHA256"] == inputs["後SHA256"], "固定入力前後辞書一致")
    need(all(inputs[k] == v for k, v in {"原入力数": 324, "純戦略数": 43, "固定93コード数": 11,
         "固定94コード数": 13, "固定93正本数": 313, "固定94正本数": 726, "新金融コード数": 15}.items()), "固定分母")
    for key in KEYS:
        a, d = result["集計"][key], diag["集計"][key]
        for ours, theirs in (("玉数", "positions"), ("新規枚数", "entry_quantity"), ("粗額円", "gross_yen"),
                             ("指定手数料円", "fee_yen"), ("仮定滑り円", "slip_yen"), ("純額円", "net_yen"),
                             ("u正益玉", "unit_positive_positions"), ("W正益玉", "whole_positive_positions")):
            need(d[ours] == a[theirs], "診断/保存会計:" + key + "/" + ours)
        need(d["正額円"] + d["負額円"] == d["純額円"] and d["黒字玉"] + d["赤字玉"] + d["同額玉"] == d["玉数"], "実玉の正負/分母")
        for p in ("u", "W"):
            need(d[p + "正益後最終赤字額円"] + d[p + "正益未観測赤字額円"] == d["負額円"], "実損失の全額分解")
        need(d["場内最大DD円"] == a["max_session_mtm_drawdown_yen"] and d["場数"] == 54 and d["開始日数"] == 27, "DD/開始日分母")
    normalized = {str(paths[n]): physical[n] for n in INPUT_NAMES}
    normalized[str(paths["readme"])] = README_SHA
    normalized[str(paths["settings"])] = SETTINGS_SHA
    return {"paths": paths, "physical": physical, "normalized": normalized, "plans": plans,
            "result": result, "diag": diag, "raw": raw, "viewer": viewer, "inputs": inputs}


def tables(context: dict, short: bool) -> str:
    """
    機能: 主経済結果を先に置き、実損失・DD・数量と12複合評価を表示する。
    引数: context(dict)は保存正本、short(bool)はREADME表示。
    返り値: strはMarkdown。指標単独効果や仮想の未参加利益を算出しない。
    """
    diag, result = context["diag"], context["result"]
    all_red = all(d["純額円"] < 0 for d in diag["集計"].values())
    lines = ["## 実行後の結果", "",
             "**12Actorすべて純損失・PFは1未満。安定利益を確認できなかった。**" if all_red else "12Actorの実現額を以下へ記録する。", "",
             "C0は指定手数料のみの主条件。C5は片道5pt仮定を保護起動にも用いる別運転で、C0の同じ取引へ費用を後付けした感度ではない。N/B5/B5Qは共通P0。", "",
             "| 評価/Actor | 玉/枚 | gross円 | fee円 | 仮定slip円 | net円 | 正額/負額円 | PF |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for i, key in enumerate(KEYS, 1):
        d = diag["集計"][key]
        lines.append(f"| R{i:02}/{key} | {fmt(d['玉数'])}/{fmt(d['新規枚数'])} | {fmt(d['粗額円'])} | {fmt(d['指定手数料円'])} | {fmt(d['仮定滑り円'])} | {fmt(d['純額円'])} | {fmt(d['正額円'])}/{fmt(d['負額円'])} | {fmt(d['PF'],3)} |")
    lines += ["", "正額・負額は完結実玉の最終netを符号で分けた合計。PF=正額÷負額絶対値。勝率だけで利益保全を判定せず、各実損失額を併せて読む。資本金不明のROIは算出しない。", "",
              "| Actor | u後赤字/正益玉 | u後赤字額円 | u未観測赤字玉/額円 | W後赤字/正益玉 | W後赤字額円 |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        d = diag["集計"][key]
        lines.append(f"| {key} | {fmt(d['u正益後最終赤字玉'])}/{fmt(d['u正益玉'])} | {fmt(d['u正益後最終赤字額円'])} | {fmt(d['u正益未観測赤字玉'])}/{fmt(d['u正益未観測赤字額円'])} | {fmt(d['W正益後最終赤字玉'])}/{fmt(d['W正益玉'])} | {fmt(d['W正益後最終赤字額円'])} |")
    lines += ["", "uは残玉1枚の両建て費用控除後の現在益、Wは実現済み純額＋残玉評価。正益後赤字額は該当玉の最終net合計で、正益時との差や将来ピークからの取り逃がしではない。未観測は観測間欠も含み得る。", "",
              "| Actor | 取引あり/赤字場（各54） | 開始日黒/赤（27日） | 場内最大DD円 | 日内最大DD円 | 全54連結MTM DD円 |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key in KEYS:
        d = diag["集計"][key]
        lines.append(f"| {key} | {d['取引あり場数']}/{d['赤字場数']} | {d['黒字開始日数']}/{d['赤字開始日数']} | {fmt(d['場内最大DD円'])} | {fmt(d['日内最大DD円'])} | {fmt(d['全54場連結MTM最大DD円'])} |")
    lines += ["", "日内DDは開始日Day→Nightのflat境界を実現carryで連結。全54DDも保存場内極値/DDを連結した口座MTMであり、原板の全経路照合へ依存する。各セッションDDと日別の詳細は事後診断に保存した。", ""]
    if not short:
        lines += ["| 比較B対A | 同実/取得変更 | Aのみ/Bのみ | 全差円 | 同実差/取得変更差円 | Aのみ実額/Bのみ実額円 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for name, r in diag["実現額と参加差"].items():
            lines.append(f"| {name} | {r['同実入口']}/{r['取得変更']} | {r['Aのみ']}/{r['Bのみ']} | {fmt(r['全差円'])} | {fmt(r['同実入口差円'])}/{fmt(r['取得変更差円'])} | {fmt(r['Aのみ円'])}/{fmt(r['Bのみ円'])} |")
        lines += ["", "全差=同実入口差＋取得変更差−Aのみ実額＋Bのみ実額。成立した実取引を比較し、未参加側の仮想利益は計算しない。取得変更・容量・参加差を保護の単独効果へ帰属しない。", ""]
    lines += ["Nは定時外の出生受理なのでgrid新規数0でも実新規0ではない。全12に同じ観測grid列があり、EOF後の未観測枠を追加しない。開始からの連続prefixと全12列同値は保存集計、EOFまでの最終欠落と同秒原行/Forceの因果は独立境界監査で照合した。", ""]
    return "\n".join(lines)


def render(context: dict, name: str) -> str:
    """
    機能: 事前本文/36設定/495セルを原文復元可能に保持し、実行状態と結果を追加する。
    引数: context(dict)はprepare結果、name(str)はreadme/settings。
    返り値: strは新規出力本文。旧計画の未実行は作成時点の記録として区別する。
    """
    p, raw, viewer = context["paths"], context["raw"], context["viewer"]
    header = ("# 00095：5分判断と開始30分見送り" + ("・設定と結果" if name == "settings" else "") + "（実行済み）\n\n"
              "**54既使用場・12Actor/648会計の実行と独立保存/原板/Viewer照合が完了。全12は純損失で、未知期間の安定利益は未証明。**\n\n"
              "元の連続出生Nと、出生後一回のB5/B5Qを共通P0で比較した。5分は受付時計で、現在テクニカル再成立の新gateは追加していない。元FAR全面同値=falseを維持する。\n\n"
              "最新評価方針は成立取引の実現利益/損失・正負額/PF・正益後赤字額・DD・数量/回数。未参加/決済後の仮想利益・機会損失は評価しない。下の原計画内『未実行』は作成時点の状態であり、現在実績は末尾に記録した。\n\n")
    body = tables(context, name == "readme")
    body += ("\n### 正本・検査範囲・再現\n\n"
             f"- [独立保存集計]({link(p['result'])})・[事後診断]({link(p['diagnostics'])})・[実現取引の診断](実現取引の診断.md)・[Viewer一覧]({link(p['result'].with_name('一覧.resources.json'))})。\n"
             f"- [原板照合]({link(p['raw'])})：54場/648会計、{fmt(raw['照合項目数'])}項目差0。両市場EOF、出生一枠、Source比例返済、N対94と全正常原行MTMの模型内照合。\n"
             f"- [Viewer照合]({link(p['viewer'])})：648資源、{fmt(viewer['照合項目数'])}項目差0。保存全約定・半円費用・終了所有0のAPI一致。\n"
             f"- [入力前後照合]({link(p['inputs'])})：324入力/純戦略43/93コード11/94コード13/93正本313/94正本726/金融15が固定辞書で一致。N4は指定追加5fieldだけを除き旧94P0本文全文に一致。\n"
             "- [条件](条件.json)・[検証計画](検証計画.md)・[再現手順](再現手順.md)・[設定と結果](設定と結果.md)。[EOF時計の訂正](集計時計の訂正.json)・[同時計予約の訂正](同時計予約の訂正.json)・[表示指紋の更新](表示監査の指紋更新.json)を保持し、初回失敗を成功へ書き替えない。\n\n"
             "CurrentPriceTimeは価格項目時計で独立受信時計ではない。両市場の真の到着順は検証不能で、同時刻TOPIX先行は再生規則。ラージBBOをmini約定代理にしており、実mini板の流動性と片道5ptの実測は未確認。これらを実市場で先読みなしの全面証明と呼ばない。54場は既使用で探索外ではない。名目建値床は次正常原行の実現netを保証しない。\n")
    return (STATE_BEGIN + header + STATE_END + "\n<details>\n<summary>固定した事前計画・36設定（作成時点の未実行記述）</summary>\n\n"
            + PLAN_BEGIN + context["plans"][name] + PLAN_END + "\n</details>\n\n" + RESULT_BEGIN + body + RESULT_END)


def main() -> None:
    """
    機能: 完了した7正本から2文書と生成証拠を新規生成し、--checkで再生成一致を検査する。
    引数: --result/diagnostics/raw/viewer/inputs/readme/settings/out(Path)、--check(bool)。
    返り値: None。正式文書を自動上書きせず、市場/金融/APIを呼ばない。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in INPUT_NAMES:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    need(args.out.exists() if args.check else not args.out.exists(), "新規出力/check既存だけ")
    ctx = prepare(args)
    outputs = {"README.md": render(ctx, "readme"), "設定と結果.md": render(ctx, "settings")}
    for name, expected in (("README.md", README_SHA), ("設定と結果.md", SETTINGS_SHA)):
        original(outputs[name], expected)
    proof = {"試行": 95, "成功": True, "生成対象": list(outputs), "正規化入力SHA256": ctx["normalized"],
             "原計画SHA256": {"README.md": README_SHA, "設定と結果.md": SETTINGS_SHA},
             "出力SHA256": {n: hashlib.sha256(t.encode("utf-8")).hexdigest() for n, t in outputs.items()},
             "生成コードSHA256": sha(Path(__file__)), "固定94報告部品SHA256": FIXED_SHA,
             "全495セルと36設定": "固定原計画SHA復元で不変", "実結果": "54既使用場/12Actor/648会計/648Viewer",
             "原板/金融/APIの再実行": 0, "機会損失/退出後仮想利益": 0, "元FAR全面同値": False,
             "5分受付": True, "現在技法再成立の新gate": False, "未知安定性": "未証明"}
    if args.check:
        for name, text in outputs.items():
            need((args.out / name).read_bytes() == text.encode("utf-8"), "生成文書差:" + name)
        need(load(args.out / "生成証拠.json") == proof, "生成証拠差")
        for name in ("readme", "settings"):
            text = ctx["paths"][name].read_bytes().decode("utf-8")
            if PLAN_BEGIN in text:
                need(text == outputs["README.md" if name == "readme" else "設定と結果.md"], "生成済み入力の手修正差")
    else:
        args.out.mkdir(parents=True)
        for name, text in outputs.items():
            (args.out / name).write_bytes(text.encode("utf-8"))
        (args.out / "生成証拠.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    need(all(sha(ctx["paths"][n]) == v for n, v in ctx["physical"].items()), "生成入力の前後差")
    print(json.dumps({"成功": True, "check": args.check, "事前全文復元": True, "出力SHA256": proof["出力SHA256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
