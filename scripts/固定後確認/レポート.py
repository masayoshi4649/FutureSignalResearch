"""00027の保存結果だけから固定後の新一場確認と設定表を表示する。"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00027_試行00026の新Night固定後確認"
OLD_STUDY = ROOT / "study/00026_反転のSAR確認時刻と順行持続"
WORK = ROOT / "work/固定後確認/00027"
IDS = ["3分_N0_X0", "3分_N1_X0", "3分_N2_X0"]
PERIOD = "固定後確認"
SESSION = "2026-11-04_Night"


def display_helper() -> Any:
    """固定26の設定とMarkdown表示補助だけを読み込む。

    引数: なし。
    返り値: Anyは表示モジュール。先着/運用/原板読取を呼び出さない。
    """
    spec = importlib.util.spec_from_file_location("固定後確認帳票の26表示", ROOT / "scripts/反転確認時計/レポート.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


F = display_helper()
G, P, number = F.G, F.P, F.number


def validate(study: Path, work: Path) -> tuple[dict, dict, list[dict], dict]:
    """保存済みの固定/分母/費用/旧資格が新一場の定義に一致するか検査する。

    引数: study/work(Path)は正式試行/作業成果物の保存先。
    返り値: tuple[dict,dict,list[dict],dict]は固定26条件/27結果/三定義/新台帳。
    """
    required = ("計画.md", "条件参照.json", "固定.json", "結果.json", "入力台帳.json", "助走参照.json", "作業成果物.json")
    for name in required:
        if not (study / name).is_file():
            raise ValueError(name + "未保存。正式完了前の実測帳票を生成しない")
    pointer = G.read_json(study / "条件参照.json")
    for field, filename in (("条件", "条件.json"), ("固定", "固定.json")):
        path = (study / pointer[field + "参照"]).resolve()
        if G.sha(path) != pointer[field + "SHA256"] or G.sha(OLD_STUDY / filename) != pointer[field + "SHA256"]:
            raise ValueError("固定26正本の" + field + "指紋差")
    config = G.read_json(OLD_STUDY / "条件.json")
    rules = F.definitions(config)
    report = G.read_json(study / "結果.json")
    expected = {"新規確認場": SESSION, "新規確認場数": 1, "確認候補": IDS, "表示固定ID": IDS,
                "期間": PERIOD, "旧助走場数": 65, "旧場損益合算": False, "条件変更": False,
                "新規場確認前未使用": True, "確認後は既使用": True, "新1場による支持代用": False}
    if any(report.get(k) != v for k, v in expected.items()) or pointer["確認候補"] != IDS:
        raise ValueError("事前指定の新一場/全三案/分離方針に不一致")
    locked = G.read_json(study / "固定.json")
    for path, digest in locked["ファイルSHA256"].items():
        if G.sha(ROOT / path) != digest:
            raise ValueError("27固定の版差:" + path)
    if report["27固定SHA256"] != G.sha(study / "固定.json") or report["参照26結果SHA256"] != G.sha(OLD_STUDY / "結果.json"):
        raise ValueError("結果の参照指紋不一致")
    old = G.read_json(OLD_STUDY / "結果.json")
    F.validate(config, old, rules)
    priors = {r["候補ID"]: r for r in old["結果"]}
    if [r["候補ID"] for r in report["結果"]] != IDS or len(report["入口評価"]) != 3:
        raise ValueError("全三案の0取引も残す必要がある")
    entrances = {r["入口ID"]: r for r in report["入口評価"]}
    for rule, row in zip(rules, report["結果"]):
        if row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("26と異なる条件定義")
        entry, operation = row["新規確認"]["入口"], row["新規確認"]["運用"]
        P.validate_entry(entry)
        if entrances[rule["入口"]["入口ID"]]["新規確認"] != entry or entry["分割"] != PERIOD:
            raise ValueError("入口評価の二重保存不一致")
        n = operation["完結取引数"]
        if operation["入力場数"] != 1 or operation["活動場数"] + operation["無取引場数"] != 1:
            raise ValueError("旧65場を新一場の活動分母へ混ぜない")
        if operation["買い取引数"] + operation["売り取引数"] != n or sum(operation["役割別完結数"].values()) != n:
            raise ValueError("方向/役割の完結会計不一致")
        if not 0 <= operation["起動後純赤字取引数"] <= operation["追尾起動取引数"] <= n:
            raise ValueError("追尾の起動分母不一致")
        for slip in (0, 5, 10):
            net, average = operation[f"追加{slip}pt純損益円"], operation[f"追加{slip}pt平均円"]
            if not math.isclose(net, operation["追加0pt純損益円"] - 20 * slip * n, abs_tol=1e-8):
                raise ValueError("追加費用感度が保存取引数に不一致")
            if (average is None) != (n == 0) or n and not math.isclose(average, net / n, abs_tol=1e-8):
                raise ValueError("平均額の分母不一致")
            if operation["品質注意場数"] and operation[f"追加{slip}pt確定対象円"] is not None:
                raise ValueError("品質注意を含む観測額を確定成績へ変換しない")
        prior = priors[row["候補ID"]]
        if row["旧26資格"] != {k: prior[k] for k in ("入口支持", "70目標", "費用資格")}:
            raise ValueError("旧26の支持/資格を新一場で更新しない")
    manifest = G.read_json(study / "入力台帳.json")
    if len(manifest["entries"]) != 1 or manifest["entries"][0]["session"] != SESSION:
        raise ValueError("新入力台帳は予約一場のみ")
    for filename, key, value in (("初回開封記録.json", "状態", "初回抽出完了"), ("新規確認実行記録.json", "状態", "初回新規確認完了")):
        if G.read_json(work / filename).get(key) != value:
            raise ValueError(filename + "の明示完了なし")
    return config, report, rules, manifest


def comparison(report: dict) -> str:
    """新一場の先着・実運用を旧26の支持/資格から分けて表示する。

    引数: report(dict)は27の結果正本。
    返り値: strは全三案の比較表。結果の良い案を事後選択しない。
    """
    entries, costs, quality, priors = [], [], [], []
    for row in report["結果"]:
        cid = row["候補ID"]
        entry, op = row["新規確認"]["入口"], row["新規確認"]["運用"]
        entries.append([cid, entry["候補数"], entry["約定候補数"], entry["順行先着"], entry["逆行先着"],
                        entry["期限未達"], entry["観測不足"], entry["未約定"], G.pct(entry["確認率"]),
                        f"{entry['30分間引き_順行先着']}/{entry['30分間引き_約定候補数']}・{G.pct(entry['30分間引き_確認率'])}"])
        costs.append([cid, op["完結取引数"], f"{op['買い取引数']}/{op['売り取引数']}",
                      *[number(op[f"追加{s}pt純損益円"]) for s in (0, 5, 10)],
                      number(op["追加5pt平均円"]), number(op["追加0pt確定対象円"])])
        quality.append([cid, f"{op['活動場数']}/{op['無取引場数']}", op["品質注意場数"],
                        op["未解消場数"], op["EOF期限未達場数"], op["追尾起動取引数"], op["起動後純赤字取引数"],
                        number(op["期間内最大場内DD円"]), G.describe(op["役割別完結数"])])
        prior = row["旧26資格"]
        priors.append([cid, "充足" if prior["入口支持"] else "未達", "達成" if prior["70目標"] else "未達",
                       "充足" if prior["費用資格"] else "未達", "代用しない"])
    text = "## 新Night一場の結果\n\n先着は実保有制約なしの各要求後の仮新規から測る。分母は全仮約定で、125先着・期限・不足も除かない。仮250先着と実利益/勝率は別。全三案を事前指定どおり載せ、無取引案も残す。\n"
    text += G.table(["候補", "純採用", "仮約定", "250先着", "125先着", "期限", "不足", "未約定", "確認率", "30分間引き250/仮約定・率"], entries)
    text += "### 一建玉運用と費用感度\n\n基準はラージBBOによるmicro1枚代理・片道11円。追加5/10ptは片道仮定の感度で、実運用の再生経路は同じ。注意ありなら全体確定額はnull（未算出）で、観測額や平均を確定収益へ読み替えない。\n"
    text += G.table(["候補", "実完結", "買/売", "基準観測円", "追加5pt観測円", "追加10pt観測円", "追加5pt平均円", "基準確定対象円"], costs)
    text += G.table(["候補", "活動/無取引場", "品質注意場", "未解消場", "EOF未達場", "追尾起動", "起動後純赤字", "最大場内DD円", "役割別完結"], quality)
    text += "### 旧26の支持と資格を別に保持\n\n以下は旧65場（学習40・条件選択24・既使用11/4デイ1）の固定済み判定で、新Nightの件数/損益を足していない。新一場が高率又は黒字でも、支持付き70%や安定収益の達成とはしない。\n"
    return text + G.table(["候補", "旧両期入口支持", "旧70目標", "旧費用資格", "新1場で支持代用"], priors)


def stages(study: Path) -> str:
    """保存された価格/反転監視の段階と取消を一場だけ表示する。

    引数: study(Path)は正式試行。
    返り値: strは登録/消費/採用の別表。取り直しや推定件数を追加しない。
    """
    data = G.read_json(study / "入口品質.json")
    if len(data) != 1 or data[0]["期間"] != PERIOD:
        raise ValueError("入口品質も新一場に限る")
    quality = data[0]
    fields = ("設定数", "内復帰価格消費数", "外回復価格消費数", "反転候補登録数", "f即時SAR確認数", "後続SAR待機開始数",
              "後続SAR確認消費数", "後続確認時点対象外足数", "h元端等号不採用数", "先着評価対象外数")
    text = "## 価格/反転確認の段階\n\n原b/f/g・公開時点・初回消費は26から変更しない。後続hが技術不採用でも初SARrの確認は一度消費し、後足へ取り直さない。元端等号hはraw保存・strict帯内不可で不採用、g/反対端/期限等は先取消。\n"
    text += G.table(["価格b", "f", "g", "f反転登録", "f即時確認", "後続待機", "後続h消費", "時点対象外足", "h等号不採用", "先着対象外event"], [[quality[k] for k in fields]])
    event_fields = ("原イベント数", "先着評価対象数", "M26時間通過数", "N0採用数", "N1採用数", "N2採用数")
    text += G.table(["系統", "役割", "原event", "先着対象", "M26時間", "N0", "N1", "N2"], [[r["系統"], r["役割"], *[r[k] for k in event_fields]] for r in quality["イベント段階"]])
    text += G.table(["反転監視終了理由", "件数"], [[k, v] for k, v in sorted(quality["反転監視終了理由別"].items())])
    sar = G.read_json(study / "SAR品質.json")
    keys = ("SAR入力足数", "SAR数値準備足数", "SAR公開準備足数", "SAR初期化数", "SAR反転数", "SAR未公開数値更新数", "SARclear数", "SAR尾部完全欠枠")
    text += "SAR末尾完全幅NPは数値銀行だけ更新/carryし、公開の現前方向へ使わない。銀行clear件数をエントリー見送りの件数にしない。\n"
    return text + G.table(["SAR全足", "数値準備", "公開準備", "seed", "反転", "NP内部更新", "clear", "尾部完全欠枠"], [[r[k] for k in keys] for r in sar])


def proof_path(study: Path, work: Path, name: str) -> Path:
    """正式へ移した証明と作業正本の内容が同じときだけ表示元を選ぶ。

    引数: study/work(Path)は正式先/作業先、name(str)は証明名。
    返り値: Pathは正式優先の証明。両版不一致又は両方未保存は例外。
    """
    formal, original = study / name, work / name
    if formal.is_file():
        if original.is_file() and G.sha(formal) != G.sha(original):
            raise ValueError("証明の正式/作業版差:" + name)
        return formal
    if original.is_file():
        return original
    raise ValueError("証明未保存:" + name)


def audits(study: Path, work: Path, output: Path) -> tuple[str, list[Path]]:
    """合成/助走/新一場の各監査を明示合否と指紋で表示する。

    引数: study/work/output(Path)は正式先/作業先/表示先Markdown。
    返り値: tuple[str,list[Path]]は検査表と出典。独立標本数へ加算しない。
    """
    groups = [(study / "合成検証.json", "人工境界合成・編集終了", "合成"),
              (work / "助走点検.json", "旧65場の主助走・7技術系列", "通常"),
              (work / "助走独立確認.json", "旧65場の独立助走・ATR別照合", "通常"),
              (proof_path(study, work, "独立監査.json"), "新一場の全先着/Decimal会計/正式成果物", "通常"),
              (proof_path(study, work, "状態独立確認.json"), "新一場の原OHLC/全SAR/全N/h監視", "通常"),
              (proof_path(study, work, "追尾独立確認.json"), "新一場の全保有A5最初要求/原気配", "通常"),
              (proof_path(study, work, "対応診断.json"), "新一場の役割/参加集合/回収", "対応"),
              (work / "新1場補足点検.json", "採用case/rawの分母・N1/N2同値・全f終了", "通常"),
              (proof_path(study, work, "Viewer照合.json"), "全三案のViewer表示", "Viewer")]
    rows, paths = [], []
    for path, title, kind in groups:
        if not path.is_file():
            raise ValueError("正式帳票の証明未完:" + str(path))
        data = G.read_json(path)
        if kind == "合成":
            verdict = data.get("全件成功") is True and data.get("合成編集終了") is True
            count = data["検証件数"]
            for name, digest in data["ファイルSHA256"].items():
                if G.sha(ROOT / name) != digest:
                    raise ValueError("最終合成のpin差:" + name)
        elif kind == "Viewer":
            checks = data.get("照合", [])
            verdict, count = len(checks) == 3 and all(r.get("一致") is True for r in checks), len(checks)
        else:
            verdict = data.get("全件一致", data.get("対応集合全件一致"))
            count = data.get("照合項目数")
        if verdict is not True:
            raise ValueError("監査の明示合格なし:" + str(path))
        if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study / "結果.json"):
            raise ValueError("監査の結果SHA差:" + str(path))
        if kind == "対応":
            result_key = (study / "結果.json").relative_to(ROOT).as_posix()
            if data["ファイルSHA256"].get(result_key) != G.sha(study / "結果.json"):
                raise ValueError("対応診断の結果pin差")
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
        paths.append(path)
    text = "## 検査の状態\n\n開封前の人工合成/主独立助走、開封後の新一場の状態/先着/会計/追尾/Viewerを分ける。旧助走はラベル/損益を計算せず、検算件数は独立した収益標本へ合算しない。全浮動値のbyte完全一致ではなく、ATRだけ26の絶対許容1e−10・相対0とε/D呼値整数厳密一致を維持する。\n"
    text += G.table(["範囲", "明示合否", "件/項目", "正本"], rows)
    viewer = G.read_json(proof_path(study, work, "Viewer照合.json"))
    checks = viewer["照合"]
    if all("API最終状態" in r for r in checks):
        text += G.table(["候補", "場", "研究/API実現円", "API買/売保有", "数値本文指紋"], [
            [r["手法"], r["場"], f"{number(r['研究側純損益円'])}/{number(r['API最終状態']['realized_pnl_yen'])}",
             f"{r['API最終状態']['long_qty']}/{r['API最終状態']['short_qty']}", "一致" if r.get("数値本文SHA256一致") else "未確認"] for r in checks])
    text += "Viewerは事前全三案、market_pathは設定data_root・pnl_pathはcatalog基準。PNG追加" + str(viewer.get("追加PNG数", 0)) + "枚。保存/模型の一致は実micro約定や将来収益の証明ではない。\n\n"
    return text, paths


def input_and_order(study: Path, work: Path, manifest: dict, output: Path) -> str:
    """予約メタ情報と開封後に初めて得た指紋、数値助走を時点別に示す。

    引数: study/work/output(Path)は保存先、manifest(dict)は新一場台帳。
    返り値: strは入力/順序の説明。原板やcacheの本文を開かない。
    """
    pointer = G.read_json(study / "条件参照.json")
    journal = G.read_json(work / "初回開封記録.json")
    entry = manifest["entries"][0]
    reserved = next(r for r in pointer["予約確認"]["ファイル"] if r["名前"] == "book.jsonl")
    text = "## 入力と固定後確認の順序\n\n計画/参照条件/候補/runnerを固定した後に新Nightを初回開封した。予約時は名前/サイズ/更新nsだけで、原板内容ハッシュは開封後に初めて保存。CSVへ入力を切り替えず、26と同じ固定readerで原板を一cacheへ抽出した。\n"
    text += G.table(["項目", "値"], [["新規場", SESSION], ["予約bookバイト", reserved["バイト"]], ["予約更新ns", reserved["更新ns"]],
                 ["原板SHA256（開封後）", entry["sha256_uncompressed"]], ["cacheSHA256（開封後）", entry["sha256_cache"]],
                 ["cache参照", entry["cache_path"]], ["初回開封状態", journal["状態"]], ["新規入力数", 1], ["助走場数", 65]])
    locked = G.read_json(study / "固定.json")
    text += "開封前固定は" + number(len(locked["ファイルSHA256"])) + "ファイルの指紋。初回抽出開始" + journal["開封開始日時"] + "、完了" + journal["開封完了日時"] + "。予約サイズ/更新nsを前後で照合し、一回の抽出だけを正式入力にした。\n\n"
    text += "同限月の3/15指標・30分窓・SARの数値銀行だけを旧65場の同じ順で助走し、限月変更や欠枠は固定26の解除を適用する。建玉/注文/当場usedキー/価格f/g/反転h監視は新場で0。旧65場の損益や支持を新場へ足さない。新Nightはこの確認後に既使用となり、同資料で条件変更した次研究を未見検証とは呼ばない。\n\n"
    text += "初回記録：" + " / ".join(G.link(work / n, output) for n in ("初回開封記録.json", "新規入力台帳.json", "新規確認実行記録.json")) + "。抽出/実行失敗時は記録とpartialcacheを残し、初回を未見状態へ戻して再試行しない。\n\n"
    quality = G.read_json(study / "入力品質.json")
    text += G.table(["入力品質", "保存値"], [[k, G.describe(v)] for k, v in quality[0].items()])
    text += "原板行の品質検知と、実保有中の正常板空白等による運用品質注意は別の計数。異常値をCSVや仮価格で補完しない。数量診断は観測累積差分で、真の全約定量や攻撃側flowを証明しない。\n"
    return text + G.table(["抽出/入力診断", "保存件数"], [[k, entry[k]] for k in ("raw_lines", "decoded_rows", "events", "omitted_identical")] + [[k, v] for k, v in entry["quality"].items()])


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """新一場の役割と実参加、先着/回収の時点差を小集計で表示する。

    引数: study/work/output(Path)は正式先/作業先/表示先。
    返り値: strは診断説明。先着や運用を再計算しない。
    """
    path = proof_path(study, work, "対応診断.json")
    data = G.read_json(path)
    result_key = (study / "結果.json").relative_to(ROOT).as_posix()
    if data.get("対応集合全件一致", data.get("全件一致")) is not True or data["ファイルSHA256"].get(result_key) != G.sha(study / "結果.json"):
        raise ValueError("対応診断の合否/結果SHA差")
    text = "## 役割と実参加の診断\n\n" + G.link(path, output) + "が対応診断の正本。f上のN1/N2採否、共有Tの純集合、後続hの追加参加と保有抑止を分ける。同episodeや三候補の重複を独立成功票にしない。仮先着は実返済後まで観測し、仮250先着を保有中250pt獲得やその取り逃しと呼ばない。\n\n"
    text += G.table(["比較", "共通実新規", "左のみ", "右のみ", "共通返済の純額差円"], [[r["左"] + "/" + r["右"], r["共通実新規数"], r["左のみ実新規数"], r["右のみ実新規数"], number(r["共通返済純損益差円"])] for r in data["案間対応"]])
    text += "当場のN1/N2は反転Rを採らず、共通T一件だけ。N2の後続h生成は" + number(data["後続h生成数"]) + "件で、待機確認による反転取引の収益は当場では未観測。待機3件はg先着2/三足満了1で終了し、当場のN1/N2一致を両手法が一般に同じという根拠にしない。共有Tの共通返済差は0円で、全体の差を出口改善の効果にしない。\n\n"
    supplement = G.read_json(work / "新1場補足点検.json")
    if supplement["全件一致"] is not True or supplement["結果SHA256"] != G.sha(study / "結果.json"):
        raise ValueError("新一場補足点検の合否/結果版差")
    text += "補足読取では、最初のfの次足がSARrと一致しても同時計に価格gが先成立し、規約のg優先で反転監視を取消したと確認。h生成後に除外した事例ではない。N1/N2は品質/約定/取引/注文/入口取扱も識別表記だけを正規化して全て同値。\n\n"
    role_rows = []
    for cid in IDS:
        for role in ("反転", "順行"):
            own = [r for r in data["入口実返済対応"] if r["候補ID"] == cid and r["役割"] == role]
            role_rows.append([cid, role, len(own), sum(r["入口ラベル"] == "順行先着" for r in own),
                              number(sum(r["基準純損益円"] for r in own)), number(sum(r["追加5pt純損益円"] for r in own))])
    text += G.table(["候補", "役割", "実完結", "対応仮250", "基準観測円", "追加5pt観測円"], role_rows)
    text += "### 先着の時計と利益回収\n\n"
    text += G.table(["候補", "実完結", "仮250対応", "仮125でも実黒字", "保有中250到達", "追尾起動", "起動後基準赤字"], [[r["候補ID"], r["実取引数"], r["順行先着取引数"], r["逆行先着なのに実黒字数"], r["実保有250到達取引数"], r["追尾起動数"], r["追尾起動後基準赤字数"]] for r in data["候補別"]])
    own = [r for r in data["入口実返済対応"] if r["候補ID"] == IDS[0]]
    text += "N0の三件を時刻対応で示す。22:12の共通TはN1/N2でも同じ実新規/実返済で、独立した成功三票にはしない。\n"
    text += G.table(["役割/方向", "実新規JST", "実返済JST", "仮ラベル判定JST", "仮ラベル", "保有MFE pt", "基準/追加5pt円"], [[r["役割"] + "/" + r["方向"], r["入口JST"], r["返済JST"], r["先着判定JST"], r["入口ラベル"], number(r["実保有最大順行pt"]), f"{number(r['基準純損益円'])}/{number(r['追加5pt純損益円'])}"] for r in own])
    if not all(r["先着判定前に返済"] is True for r in data["入口実返済対応"]):
        raise ValueError("全返済が先着判定より前という説明を満たさない")
    text += "全5候補取引の実返済は、それぞれの仮先着判定より前。採用case5件内の仮250はN0の一件で、実保有MFE20pt・20:23:32返済に対して250先着は21:09:05（返済2,733秒後）。250ptの利益が乗ってから返した事例ではない。全案不採用の別原f121も仮250先着であり、原raw全体の250先着2件と採用caseの1件を混ぜない。\n\n一方、仮125先着でも先にA5で小益を確定した対応があり、250/125確認率と実黒字率を同一視できない。追加10ptでは全三案それぞれの合計が赤字になり、小益の費用耐性も限られる。\n\n"
    trades = G.read_csv(study / "固定候補_取引.csv")
    rows = []
    for cid in IDS:
        armed = [r for r in trades if r["手法"] == cid and r["追尾起動"] == "True"]
        below_entry = sum((1 if r["方向"] == "買い" else -1) * (float(r["返済価格"]) - float(r["新規価格"])) < 0 for r in armed)
        below_line = sum(float(r["最終追尾から実返済方向差pt"]) < 0 for r in armed)
        rows.append([cid, len(armed), below_entry, below_line,
                     number(sum(max(0, -float(r["最終追尾から実返済方向差pt"])) for r in armed)),
                     sum(r["返済理由"] == "必須利益追尾" for r in armed)])
    text += "### 追尾設定と実約定\n\n以下の同値未満/最終線不足は追尾起動後の取引に限る。最低同値設定と実返済/費用後非赤字は別で、当場で不足0を観測しても将来の線上約定を保証しない。\n"
    return text + G.table(["候補", "追尾起動", "同値未満約定", "最終線未満約定", "最終線不足pt計", "A5返済"], rows)


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """全正式証明が揃ってから保存値のみで二Markdownを生成する。

    引数: study/work/output(Path)は正式試行/作業先/表示先。
    返り値: list[Path]はREADME/設定と結果。原板・cache本文を読み込まない。
    """
    config, report, rules, manifest = validate(study, work)
    catalog = G.read_json(G.CATALOG)
    if (catalog["version"], len(catalog["methods"]), len(catalog["scales"])) != (1, 51, 9):
        raise ValueError("版1の51手法×9尺度を保持する")
    output.mkdir(parents=True, exist_ok=True)
    readme, mapping = output / "README.md", output / "設定と結果.md"
    common = F.settings(rules)
    if len(common) != 13 or len(rules) != 3:
        raise ValueError("固定26の13設定/3評価から変更しない")
    intro = "NK225の固定26・3分N0/N1/N2・共通A5/X0を、事前指定した新Night一場でそのまま確認した。反転Rの値条件/確認時計だけが三案で異なり、順行Tはg＋公開前現SAR方向持続を共有する。計画時未閲覧の2026-11-04_Nightを開封前固定後に評価し、旧65場は数値助走だけに使用。条件・候補の選び直しはしていない。\n\n"
    goals = sum(r["旧26資格"]["70目標"] for r in report["結果"])
    qualifications = sum(r["旧26資格"]["費用資格"] for r in report["結果"])
    conclusion = f"**旧26の支持付き入口70目標は{goals}/3、費用資格は{qualifications}/3を保持。新1場でこれらを達成したとは判定しない。** 新1場の率/黒字は下表の観測結果で、将来の安定性を証明しない。\n\n"
    warnings = [r["候補ID"] for r in report["結果"] if r["新規確認"]["運用"]["品質注意場数"]]
    if warnings:
        conclusion += "新場に品質注意あり：" + "、".join(warnings) + "。該当全体の確定額はnullで、観測総額を確定収益としない。\n\n"
    structure, logic, protection, _ = F.explanation()
    limits = "## 限界と次の研究\n\n新1場は独立した相場局面/開始日の数が足りず、支持付き70%や安定収益を判断できない。旧65場は既使用の開発資料、今回の新場は固定後確認だが以後既使用。同じ資料で改良する場合は新試行へ分け、全三案を比較した後で良い案だけを未見成功例にしない。\n\n"
    limits += "30分価格構造と3分MACD又はSARの複合条件を評価し、ATR数値準備/保護だけを複数入口手法とは数えない。量は診断のみ、他手法/尺度は未使用、指標単独効果は未評価。SAR方向を参加者心理そのものとせず、固定strict/seed/clamp規約による価格加工の仮説とする。A5同値設定は実約定同値や費用後非赤字を保証しない。未来の先着/MFEを当時の採用特徴へ戻さない。\n\n"
    audit_text, audit_paths = audits(study, work, readme)
    common_result = comparison(report)
    summary = "# 試行00027：試行00026の新Night固定後確認\n\n" + intro
    summary += " / ".join(G.link(study / n, readme) for n in ("計画.md", "条件参照.json", "固定.json", "結果.json")) + " / " + G.link(mapping, readme) + "\n\n"
    summary += conclusion + common_result + input_and_order(study, work, manifest, readme) + stages(study) + diagnosis(study, work, readme) + structure + logic + protection + limits + audit_text
    # ----------------------------------------
    # 26と同じ全セル/設定ID/評価IDをコピーし、新1場の結果と旧資格を別表へ置く。
    mapped = "# 試行00027：設定と結果\n\n" + intro + conclusion + G.link(G.MASTER, mapping, "コピー元汎用表") + " / " + G.link(readme, mapping) + " / " + G.link(study / "結果.json", mapping, "新1場の全三案正本") + "\n\n"
    mapped += "## 手法×時間スケール\n\n版1の51手法×9尺度、S01〜S13とR01〜R03は固定26を読取再用し、閾値を変更しない。共通M26は全三案、R値条件と時計は別設定、数量は診断だけ。未使用と単独未評価を区別する。30分6本は計算期間、30分間引きは評価感度で30分足と別。\n\n" + G.matrix(catalog, mapping, common)
    mapped += "## 設定明細\n" + G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[r["設定ID"], "/".join(r["手法ID"]) + "・" + "/".join(r["尺度ID"]), r["短記"], r["説明"], "・".join(r["適用評価"])] for r in common])
    mapped += "## 全固定条件の要約\n\n条件正本は" + G.link(OLD_STUDY / "条件.json", mapping) + "、参照指紋は" + G.link(study / "条件参照.json", mapping) + "。\n" + G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    r_rules = {"N0": "f即時＋実rδH>0", "N1": "f即時＋現公開SARr", "N2": "f即時又は次1..3の初現公開SARr、後続hはstrict帯内"}
    mapped += "## 複合評価の定義\n" + G.table(["評価", "候補", "反転R", "共通順行T", "確認対象"], [[r["評価ID"], r["候補ID"], r_rules[r["入口"]["戦略"]], "g＋公開前現SARs持続", "事前指定の新Night1場"] for r in rules])
    mapped += common_result + structure + logic + protection + limits + audits(study, work, mapping)[0]
    # ----------------------------------------
    # 大きな全件明細をMDへ転記せず、入力指紋/11gzip台帳/全証明/版を参照する。
    files = ("入力台帳.json", "助走参照.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "局面品質.json", "30窓品質.json", "数量診断品質.json", "SAR品質.json", "入力品質.json", "作業成果物.json")
    sources = [HERE / n for n in ("README.md", "確認.py", "抽出.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py") if (HERE / n).is_file()]
    docs = [ROOT / "docs/議論" / n for n in ("反転の方向確認を待つ時計と入口価格.md", "固定条件を新しい一場へ適用した確認.md") if (ROOT / "docs/議論" / n).is_file()]
    extra = [work / n for n in ("初回開封記録.json", "新規入力台帳.json", "新規確認実行記録.json", "助走点検.json", "助走独立確認.json")]
    viewing = "## 閲覧と再表示\n\n" + " / ".join(G.link(study / n, readme) for n in files if (study / n).is_file()) + "\n\nコード：" + " / ".join(G.link(p, readme) for p in sources) + "。固定26：" + G.link(OLD_STUDY / "README.md", readme) + "。\n\n"
    viewing += "原板/cache/大量画像を複製せず、11gzipはGit外workへ保持し展開内容SHAを作業成果物へ保存。Viewerは全三案の一覧と約定。--warmupは旧65場の技術助走だけで新原板抽出/先着/損益なし、--freezeは予約statと既知版の固定で新原板内容hashなし。--開封実行は既存結果/初回開封記録を拒否し、未見状態への再実行をしない。固定後条件変更は新試行に分ける。\n\n"
    fence = chr(96) * 3
    viewing += "保存結果だけの再表示：\n\n" + fence + "powershell\npython -X utf8 scripts/固定後確認/レポート.py\n" + fence + "\n\n"
    paths = [Path(__file__), ROOT / "scripts/反転確認時計/レポート.py", F.DISPLAY, ROOT / "scripts/SAR持続/レポート.py", ROOT / "scripts/終値切替/レポート.py", ROOT / "scripts/レポート/設定結果レポート.py", G.MASTER, G.CATALOG,
             *[study / n for n in ("計画.md", "条件参照.json", "固定.json", "結果.json", *files) if (study / n).is_file()],
             OLD_STUDY / "条件.json", OLD_STUDY / "固定.json", OLD_STUDY / "結果.json", *audit_paths, *sources, *docs, *extra]
    for path, text in ((readme, summary + viewing), (mapping, mapped)):
        path.write_text(text + G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, mapping]


def main() -> None:
    """保存帳票だけを指定先へ再生成する。

    引数: なし。--study/--work/--outputは正式先/作業先/表示先。
    返り値: None。原板/キャッシュ抽出・先着・主運用を再実行しない。
    """
    parser = argparse.ArgumentParser(description="固定26全三案の新一場保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(), args.work.resolve(), (args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
