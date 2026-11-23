"""共通カタログを全試行へコピーし、実行済みの設定と結果をMarkdownへ写す。"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CATALOG = HERE / "手法カタログ.json"
MAPPING = HERE / "既存試行設定.json"
MASTER = ROOT / "docs/議論/手法と時間スケールの汎用表.md"
DATE = "2026-11-01"
KEYS = {"移動平均線": "I01", "MACD": "I03", "RSI": "I04", "ATR": "I09",
        "相対出来高": "V01", "高安突破": "P07", "先着到達ラベル": "E01"}


def read_json(path: Path) -> dict:
    """UTF-8のJSONを読む。

    引数: path (Path) は入力ファイル。
    返り値: dict は読み込んだ定義または結果。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path) -> list[dict[str, str]]:
    """列名付きCSVを読み込む。

    引数: path (Path) は入力ファイル。
    返り値: list[dict[str, str]] は元の順序を保つ行。
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha(path: Path) -> str:
    """ファイル内容の版を識別する。

    引数: path (Path) は入力ファイル。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cell(value: object) -> str:
    """表セル内の区切り文字を保護する。

    引数: value (object) は文字列化する値。
    返り値: str はMarkdown表へ挿入できる文字列。
    """
    escaped = html.escape(str(value), quote=False).replace("&lt;br&gt;", "<br>")
    return escaped.replace("|", "&#124;").replace("\n", "<br>").replace("\r", "")


def describe(value: object) -> str:
    """設定辞書を日本語の明細へ展開する。

    引数: value (object) は辞書・配列・単一値。
    返り値: str は値を省略しない説明。
    """
    if isinstance(value, dict):
        return "<br>".join(f"{key}：{describe(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " / ".join(describe(item) for item in value)
    if value is None:
        return "なし"
    return str(value)


def link(target: Path, output: Path, label: str | None = None) -> str:
    """出力先からの相対リンクを作る。

    引数: target/output (Path) はリンク先と出力MD、label (str | None) は表示名。
    返り値: str はMarkdownリンク。
    """
    relative = os.path.relpath(target, output.parent).replace("\\", "/")
    return f"[{label or target.name}]({relative})"


def table(headers: list[str], rows: list[list[object]]) -> str:
    """見出しと行からMarkdown表を作る。

    引数: headers (list[str]) は列名、rows (list[list[object]]) は行。
    返り値: str は前後に空行のある表。
    """
    lines = ["| " + " | ".join(map(cell, headers)) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
    return "\n" + "\n".join(lines) + "\n\n"


def pct(value: object) -> str:
    """比率を表示用の百分率へ変換する。

    引数: value (object) は数値・数値文字列・欠測。
    返り値: str は百分率。欠測は未算出とする。
    """
    return "未算出" if value is None or value == "" else f"{float(value) * 100:.2f}%"


def matrix(catalog: dict, output: Path, settings: list[dict] | None = None) -> str:
    """カタログ全行と全尺度を保った表を作る。

    引数: catalog (dict) は手法一覧、output (Path) は出力先、settings (list[dict] | None) は設定。
    返り値: str は分類ごとの汎用表またはその記入済みコピー。
    """
    grouped = defaultdict(list)
    index = defaultdict(list)
    for setting in settings or []:
        for method in setting["手法ID"]:
            for scale in setting["尺度ID"]:
                summary = setting.get("短記", "設定明細参照")
                result = setting.get("結果短記", "全候補一覧")
                index[method, scale].append(f"{setting['設定ID']}（{summary}）／{result}")
    for method in catalog["methods"]:
        grouped[method["category"]].append(method)
    text = ""
    for category, methods in grouped.items():
        text += f"### {category}\n"
        rows = []
        for method in methods:
            values = [method["id"], link(ROOT / method["source"], output, method["name"])]
            for scale in catalog["scales"]:
                ids = index[method["id"], scale["id"]]
                values.append("<br>".join(ids) if ids else ("未設定・未検証" if settings is None else "未使用"))
            rows.append(values)
        text += table(["ID", "手法"] + [x["label"] for x in catalog["scales"]], rows)
    return text


def provenance(paths: list[Path], output: Path) -> str:
    """設定と結果の出典・内容ハッシュを記す。

    引数: paths (list[Path]) は出典、output (Path) は出力先。
    返り値: str は重複のない出典表。
    """
    unique = list(dict.fromkeys(paths))
    return "## 出典と版\n" + table(["参照ファイル", "SHA256"], [
        [link(path, output, path.relative_to(ROOT).as_posix()), f"`{sha(path)}`"] for path in unique])


def write_master(catalog: dict) -> None:
    """未記入の汎用表と最小限の記入欄を保存する。

    引数: catalog (dict) は手法・時間尺度一覧。
    返り値: None。docs配下の正式MDを更新する。
    """
    methods, scales = len(catalog["methods"]), len(catalog["scales"])
    text = f"# 手法と時間スケールの汎用表\n\n作成日：{DATE}。カタログ版{catalog['version']}。{methods}手法×{scales}尺度＝{methods * scales}組。\n\n"
    text += "この文書を各試行の `設定と結果.md` へコピーし、使ったセルを設定ID（S01等）に置き換える。未使用セルも残す。下段へ期間・閾値・役割・複合評価ID（R01等）と結果を記入する。\n\n"
    text += "収録範囲は本リポジトリの教科書、組み合わせ、価格・数量・板・関連系列と研究で使うモデル・評価・保護である。世界中の技法を網羅する表ではなく、追加時はカタログへ新IDを登録する。\n\n"
    text += "時間尺度は**計算に用いる足**。EMA20の20本や過去12本窓は計算期間であり時間足とは分ける。セッション足はデイまたはナイトを1本にした足。VWAPの起算点とは区別する。30分間引きは30分足の使用を意味しない。\n\n"
    text += link(ROOT / "docs/議論/手法と時間スケールの記録方針.md", MASTER, "記録方針") + " / " + link(ROOT / "docs/試行記録テンプレート.md", MASTER, "試行テンプレート") + "\n\n"
    text += "## 手法×時間スケール\n\n全セルは未設定・未検証。試行では、未使用・未検証・データ不足・対象外を区別する。Sは設定、Rは複合評価への参照。指標単独の効果を測っていなければ、単独未評価と記す。\n\n"
    text += matrix(catalog, MASTER)
    text += "## 設定明細（コピー後に記入）\n"
    text += table(["設定ID", "手法ID・尺度", "役割", "計算期間・入力・初期化", "買い/売りの閾値・等号", "適用候補・複合評価", "実行状態・出典"],
                  [["S01", "未設定", "環境/位置/発動/決済/保護/診断/評価", "未設定", "未設定", "R01", "未検証"]])
    text += "## 複合条件と結果（コピー後に記入）\n"
    text += table(["評価ID", "構成設定と入口・出口", "入力・対象期間", "分母・件数・日数・場数", "結果・費用・執行仮定", "不明・未約定・限界"],
                  [["R01", "未設定", "未設定", "未設定", "未検証", "未検証"]])
    text += "指標単独と複合条件、運用損益と先着確認率、学習・条件選択・後続検査を区別する。結果が出たあとに条件を変更する場合は新しい試行へ分ける。\n\n"
    extras = [[m["id"], m["additional_input"]] for m in catalog["methods"] if m.get("additional_input")]
    text += "## 追加入力・定義の確認欄\n\n次はカタログ上の必要条件。データの有無は試行ごとに確認し、未使用をデータ不存在へ読み替えない。\n" + table(["手法ID", "必要な入力・確認"], extras)
    text += provenance([CATALOG], MASTER)
    MASTER.write_text(text, encoding="utf-8")


# ----------------------------------------
# 既存試行は確定済みの設定と集計から転記し、再計算や再選択をしない。

def old_settings(study: dict) -> list[dict]:
    """旧試行の指標設定を共通の表示形式へ正規化する。

    引数: study (dict) は既存試行設定。
    返り値: list[dict] は参照を保った設定。準備・診断も役割を明記する。
    """
    settings = []
    for source in study["指標設定"]:
        item = dict(source)
        item["手法ID"] = [KEYS[item["指標キー"]]]
        size = item["時間足分"]
        item["尺度ID"] = [f"m{size:02d}" if size else "tick"]
        if "押し戻り復帰発動" in item["役割"]:
            item["手法ID"].append("P08")
        if "保護追尾" in item["役割"]:
            item["手法ID"].append("C06")
        if "収縮拡大フィルター" in item["役割"]:
            item["手法ID"].append("P11")
        settings.append(item)
    candidates = [item["候補ID"] for item in study["候補一覧"]]
    if study["試行ID"] != "00001":
        if study["試行ID"] == "00002":
            multiscale = [item["候補ID"] for item in study["候補一覧"] if "M" in item["因子"]]
        elif study["試行ID"] == "00004":
            multiscale = [name for name in candidates if name not in ("無条件両方向", "5分方向")]
        else:
            multiscale = candidates
        settings.append({"指標キー": "複数時間足の参照", "手法ID": ["C07"], "尺度ID": ["m05", "m15", "m30"],
            "計算パラメータ": "判断は確定5分、環境は最後の確定15/30分。利用可能時刻を守る",
            "閾値と判定": "方向一致は各EMA20の方向。00002はM因子あり候補、00003は全候補、00004は各群の定義に従う",
            "役割": ["環境・発動の参照関係（準備条件とは区別）"], "適用候補ID": multiscale,
            "出典": study["出典"], "注意": "指標単独の追加効果を示す行ではない"})
    else:
        settings.append({"指標キー": "MA・MACD・RSIの組み合わせ", "手法ID": ["C01"], "尺度ID": ["m05"],
            "計算パラメータ": "MACD12/26/9、EMA60方向、RSI14、2ATR14保護",
            "閾値と判定": "MACD交差 AND EMA60方向一致 AND 買RSI>50/売RSI<50",
            "役割": ["三指標を組み合わせた派生条件"], "適用候補ID": ["方向条件とRSI"], "出典": study["出典"],
            "注意": "C01の方向・タイミング・モメンタムという役割を具体化した一実装。教科書の全パラメータ例を試した結果ではない"})
    settings.append({"指標キー": "正常板の受入条件", "手法ID": ["B01", "B02"], "尺度ID": ["tick"],
        "計算パラメータ": "原板物理行順、Buy1=Bid・Sell1=Ask、CurrentPriceTimeを価格時計に利用",
        "閾値と判定": "正価格、Bid<Ask、両側最良数量>=1。数量比の売買優位・板深さは未比較",
        "役割": ["新規と評価/決済に用いる気配の受入"], "適用候補ID": candidates,
        "出典": study["出典"], "注意": "ラージ板による約定モデル。mini/microの実板・実約定ではない"})
    if study["試行ID"] != "00004":
        settings.append({"指標キー": "逆指値の逐次監視", "手法ID": ["E02"], "尺度ID": ["tick"],
            "計算パラメータ": "ATRの値は確定5分足、保護線は正常板ごとに監視",
            "閾値と判定": "買いBid<=保護線、売りAsk>=保護線で返済要求。次の価格時計1秒以上後の正常板でモデル約定",
            "役割": ["保護"], "適用候補ID": candidates, "出典": study["出典"],
            "注意": "逆指値価格での約定を保証しない。追尾幅・丸めはATR設定を参照"})
    return settings


def annotate(settings: list[dict], candidates: list[str]) -> None:
    """セルの短い設定名と複合結果への参照を付ける。

    引数: settings (list[dict]) は設定、candidates (list[str]) は評価順。
    返り値: None。各設定へ表示用の短記を付加する。
    """
    index = {name: i for i, name in enumerate(candidates, 1)}
    for item in settings:
        key, params, role = item.get("指標キー", ""), item["計算パラメータ"], " / ".join(item["役割"])
        if "短記" not in item:
            period = params.get("期間", "") if isinstance(params, dict) else ""
            if key == "移動平均線":
                item["短記"] = f"EMA{period}・" + ("準備" if "準備" in role else "決済" if "決済" in role else "復帰" if "復帰" in role else "方向")
            elif key == "RSI":
                item["短記"] = f"RSI{period}・" + ("70/30" if "非過熱" in role else "50" if "フィルター" in role else "診断/準備")
            elif key == "MACD":
                item["短記"] = "EMA12/26/9交差"
            elif key == "ATR":
                item["短記"] = "ATR14・" + ("2倍追尾" if "追尾" in role else "1倍利確" if "利確" in role else "収縮/TR拡大" if "収縮" in role else "比率60中央値" if "低ボラ" in role else "準備" if role == "共通準備" else "保護/診断")
            else:
                item["短記"] = {"相対出来高": "前20足・" + ("準備/診断" if "準備" in role or "診断" in role else ">=1.2"),
                    "高安突破": "直前6本・突破/準備", "先着到達ラベル": "逆行200/順行400", "複数時間足の参照": "5/15/30分",
                    "正常板の受入条件": "正Bid<Ask・数量>=1", "逆指値の逐次監視": "保護線到達",
                    "MA・MACD・RSIの組み合わせ": "MACD＋EMA60＋RSI50"}.get(key, "設定明細参照")
        numbers = sorted(index[name] for name in item["適用候補ID"] if name in index)
        if len(numbers) > 3 and numbers == list(range(numbers[0], numbers[-1] + 1)):
            item["結果短記"] = f"R{numbers[0]:02d}〜R{numbers[-1]:02d}"
        else:
            item["結果短記"] = "・".join(f"R{number:02d}" for number in numbers) or "全候補一覧"


def setting_section(settings: list[dict], candidates: list[str], output: Path) -> str:
    """設定ごとにパラメータ・閾値・役割・結果参照を表示する。

    引数: settings (list[dict]) は設定、candidates (list[str]) は評価順、output (Path) は出力先。
    返り値: str は設定明細表。
    """
    result_ids = {name: f"R{index:02d}" for index, name in enumerate(candidates, 1)}
    rows = []
    for item in settings:
        refs = [result_ids[name] for name in item["適用候補ID"] if name in result_ids]
        sources = []
        for source in item.get("出典", []):
            file = source if isinstance(source, str) else source.get("ファイル")
            if file:
                sources.append(link(ROOT / file, output))
        rows.append([item["設定ID"], " / ".join(item["手法ID"]) + "<br>" + " / ".join(item["尺度ID"]),
            describe(item["役割"]), describe(item["計算パラメータ"]), describe(item["閾値と判定"]),
            "・".join(refs) if refs else "全候補一覧参照",
            (item.get("注意") or "単独未評価。複合結果を参照") + "<br>" + " / ".join(dict.fromkeys(sources))])
    return "## 設定・閾値・役割\n\nSはこの試行内の設定ID。準備・記録だけの設定を入口フィルターとみなさない。全て指標単独の損益・効果は未評価。\n" + table(
        ["設定ID", "手法ID・尺度", "役割", "計算期間・入力・初期化", "閾値・判定", "複合評価", "注意・出典"], rows)


def old_result_section(study: dict, settings: list[dict], output: Path) -> tuple[str, list[Path]]:
    """旧試行の候補別結果を正本CSVから写す。

    引数: study (dict) は試行、settings (list[dict]) は設定、output (Path) は出力先。
    返り値: tuple[str, list[Path]] はMDと参照CSV。
    """
    definitions, results, paths = [], [], []
    is_label = study["試行ID"] == "00004"
    for number, candidate in enumerate(study["候補一覧"], 1):
        name, rid = candidate["候補ID"], f"R{number:02d}"
        ids = [s["設定ID"] for s in settings if name in s["適用候補ID"]]
        details = {key: value for key, value in candidate.items() if key not in ("候補ID", "結果参照")}
        definitions.append([rid, name, "・".join(ids), describe(details)])
        for reference in candidate["結果参照"]:
            path = ROOT / reference["ファイル"]
            paths.append(path)
            matched = [r for r in read_csv(path) if all(r[k] == str(v) for k, v in reference["選択条件"].items())]
            if not matched:
                raise ValueError(f"結果参照が空: {name} {path}")
            for row in matched:
                if is_label:
                    results.append([rid, row["期間"], row["方向"], row["候補数"], row["約定候補数"],
                        row["順行先着"], row["逆行先着"], row["期限未達"], row["観測不足"], row["未約定"],
                        pct(row["順行先着率_全約定"]), row["候補発生場数"], link(path, output)])
                else:
                    results.append([rid, row["銘柄"], row["期間"], row["セッション数"], row["取引数"],
                        f"{float(row['純損益円']):,.0f}", pct(row["勝率"]), row["未解消場数"], link(path, output)])
    text = "## 複合条件\n" + table(["評価ID", "候補", "構成設定", "入口・出口・保護"], definitions)
    text += "## 複合条件の結果\n"
    if is_label:
        text += "主率は順行先着/全約定候補。運用損益・運用の勝率ではない。200pt逆行と400pt順行を比較し、125/250の00005と混ぜない。全60場は既使用の探索。重複する入口を独立に評価するため同時保有制約も課していない。\n"
        headers = ["評価ID", "期間", "方向", "候補", "約定", "順行", "逆行", "期限", "不足", "未約定", "全約定の確認率", "候補発生場", "正本"]
    else:
        text += "純損益・勝率は各複合戦略を一つずつ運用するモデルの値。NK225はmicro1枚、TOPIXはmini1枚、ラージ板から執行を模擬。手数料等は元の条件・READMEが正本。\n"
        headers = ["評価ID", "銘柄", "期間", "場数", "完結取引", "純損益円", "勝率", "未解消場", "正本"]
    text += table(headers, results)
    return text, paths


def write_old(catalog: dict, study: dict) -> None:
    """既存試行へ共通表をコピーし記入する。

    引数: catalog (dict) は手法一覧、study (dict) は既存試行の設定。
    返り値: None。元の数値・コード・条件は変更しない。
    """
    output = ROOT / study["フォルダ"] / "設定と結果.md"
    settings = old_settings(study)
    for index, item in enumerate(settings, 1):
        item["設定ID"] = f"S{index:02d}"
    annotate(settings, [c["候補ID"] for c in study["候補一覧"]])
    text = f"# 試行{study['試行ID']}：設定と結果\n\n共通表への転記日：{DATE}。既存試行の再計算・条件変更ではない。\n\n"
    text += link(MASTER, output, "コピー元の汎用表") + " / " + link(output.parent / "README.md", output, "試行README") + "\n\n"
    text += f"対象：{describe(study['対象'])}。結果種別：{study['結果種別']}。\n\n期間：{describe(study['期間の意味'])}\n\n"
    text += f"## 手法×時間スケール（共通表のコピー）\n\n{len(catalog['methods'])}行・{len(catalog['scales'])}尺度を保持。Sは下段の設定、Rは複合条件と結果。未使用は無効という意味ではない。\n\n" + matrix(catalog, output, settings)
    text += setting_section(settings, [c["候補ID"] for c in study["候補一覧"]], output)
    text += "## 共通執行と除外\n\n" + describe(study["共通執行"]) + "\n\n"
    if study.get("内部計算のみ"):
        text += "使用セルへ数えない内部計算：" + describe(study["内部計算のみ"]) + "\n\n"
    result, paths = old_result_section(study, settings, output)
    text += result
    text += "## 限界\n\nこの表の転記で、指標単独の効果や未使用尺度の有効性を検証したことにはならない。入力の欠測・足の準備条件・執行モデル・前半後半等の詳細は元READMEと参照ファイルを優先する。各候補は同じ相場の重複経路を使う。複合結果を独立した指標ごとの成功例として数えない。\n\n"
    text += provenance([CATALOG, MAPPING, Path(__file__), output.parent / "条件.json"] + paths, output)
    output.write_text(text, encoding="utf-8")


# ----------------------------------------
# 00005の閾値探索は共通表と全候補一覧の二段に分け、同じ巨大表を候補数分複製しない。

def new_settings(folder: Path) -> list[dict]:
    """00005の実装済み設定を共通形式で定義する。

    引数: folder (Path) は00005の正式フォルダ。
    返り値: list[dict] は手作業の解釈を明示した設定。数値結果は別途正本から読む。
    """
    settings = []
    def add(methods: list[str], scales: list[str], role: str, calculation: str, threshold: str, note: str = "") -> None:
        """表示用の設定を登録する。

        引数: methods/scales (list[str]) はID、role/calculation/threshold/note (str) は説明。
        返り値: None。
        """
        settings.append({"設定ID": f"S{len(settings) + 1:02d}", "手法ID": methods, "尺度ID": scales,
            "役割": [role], "計算パラメータ": calculation, "閾値と判定": threshold,
            "適用候補ID": [], "注意": note or "単独未評価。固定条件・モデルの構成要素。全候補一覧参照",
            "出典": ["scripts/入口探索/特徴生成.py", "scripts/入口探索/探索.py"]})
    for size in (5, 15, 30):
        add(["I01"], [f"m{size:02d}"], "環境・モデル入力・共通準備", "EMA20、初期20本SMA。最後に確定した足",
            "買い：C>EMA20かつEMA20>前EMA20、売り：C<EMA20かつEMA20<前EMA20。距離/傾きもモデル許可特徴へ",
            "固定候補は15/30方向一致。5分方向一致そのものは固定候補の要件ではない。モデル分岐の閾値は全候補一覧")
    for size in (5, 15):
        add(["I04"], [f"m{size:02d}"], "モデル入力。5分は固定格子にも使用", "Wilder RSI14。方向側RSI=買RSI・売100−RSI",
            "5分の格子：条件なし / [20,45) / [30,55) / [45,65) / [50,70) / [55,80)。15分は固定RSI格子なし",
            "固定候補は方向側5分RSIが55以上80未満。売り生RSIでは20超45以下。15分RSIはモデルへ供給し単独未評価")
    add(["I09"], ["m05"], "値幅・収縮拡大・構造の正規化", "Wilder ATR14。TRはH−L、|H−前C|、|L−前C|の最大",
        "ATR範囲：(0,50] / (25,75] / (50,125] / (75,250] / (0,100000]。収縮：前足ATR/C<=それ以前60中央値、拡大：当足TR>前ATR")
    add(["V01"], ["m05"], "補助格子・モデル入力", "観測累積差分量 / 同場直前20有効足の平均",
        "条件なし または >=1.2", "完全な約定出来高ではない。固定候補では数量閾値を使わない")
    add(["P01"], ["m05", "m15", "m30"], "ローソク特徴をモデルへ供給", "確定足の値幅・方向実体・上下ヒゲ・方向終値位置。分母0は欠測",
        "強い足の固定仮説だけ5分方向実体比>=0.6、方向終値位置>=0.8。モデルの個別分岐は全候補一覧")
    add(["P05"], ["m05"], "発動・モデル入力", "方向変化=s×(C−同場1/3/6本前C)、ATRでも正規化",
        "構造内位置追随・強い足継続は1本変化>0")
    add(["P06"], ["m05"], "位置・余地・モデル入力", "当足を除く同場直前6/12/24本の高安。反対端距離=買C−L/売H−C、前方距離=買H−C/売C−L",
        "6本反対端0超125以下、12本復帰は同反対端0超125以下かつ前方端250以上。窓12/24は本数であり時間足ではない")
    add(["P07"], ["m05"], "突破発動・モデル入力", "当足除外、直前6本高安。過去12/24本の突破有無も入力",
        "買C>過去H、売C<過去L。等号は突破でない")
    add(["P08"], ["m05"], "EMA復帰発動", "前5分時点と現在の15/30分方向が同じ側で維持",
        "買：前C<=前EMAかつ今C>今EMA。売：前C>=前EMAかつ今C<今EMA。追随復帰と構造では6本反対端距離も要求")
    add(["P09"], ["m05"], "レンジ端復帰発動", "当足を除く12本高安。上位足相互整合=0（片側方向なしも含む）",
        "買：当L<=過去L<C<=過去H。売：過去L<=C<過去H<=当H。反対端0超125以下、前方端>=250")
    add(["P10"], ["m05"], "再テスト発動", "前1〜3本の6本高安突破で固定した水準。今足突破は同時登録しない",
        "買は当L<=水準かつC>水準、売は当H>=水準かつC<水準。上位方向一致、水準方向距離0以上125以下")
    add(["P11"], ["m05"], "収縮拡大突破発動", "前足収縮＋当足拡大＋6本方向端突破",
        "上位方向一致、前足ATR/C<=それ以前60中央値、今TR>前ATR、方向端突破=1")
    add(["P12"], ["m05"], "強い足継続発動", "上位方向一致＋5分ローソクと直前変化",
        "方向実体比>=0.6、方向終値位置>=0.8、方向変化1本>0")
    add(["C07"], ["m05", "m15", "m30"], "環境と発動の参照関係", "判断は5分足確定後、上位環境は確定15/30分。場の完全足の利用時刻を守る",
        "上位整合：15/30が売買方向に一致。全足整合：5/15/30一致。各familyは異なる参照を持つ")
    add(["M01"], ["m05"], "複合条件抽出（判断5分、参照5/15/30）", "12木=深さ2/3/4/5×min_leaf40/80/160、criterion=log_loss、seed20261101。学習約定行中央値で欠測補完、開始日重み等分",
        "学習済み全葉123候補＋スコア>=0.50〜0.90（0.05刻み）108候補。個別葉の全閾値は全候補一覧",
        "84列を供給。特徴の供給と分岐利用と除去効果を区別。スコア0.7は実確認率70%ではない")
    add(["M02"], ["m05"], "複合スコア（判断5分、参照5/15/30）", "4モデル=葉上限7/15×学習率0.05/0.1、depth3、min_leaf80、150反復、L2=1、64bin、early_stopping=False、seed20261101。欠測native、開始日重み等分",
        "各モデルで固定9スコア閾値＋学習スコア90/95/98分位の計12閾値、48候補。全閾値は全候補一覧",
        "分位は学習のみ。スコア0.7は実確認率70%ではない。特徴単独の効果未評価")
    add(["B01", "B02"], ["tick"], "気配受入・仮新規・到達観測", "原板物理行順。Buy1=Bid/Sell1=Ask、CurrentPriceTime",
        "Bid/Ask正、Bid<Ask、両最良数量>=1。要求後1価格時計秒以上、30秒以内。cutoff15:25/翌05:40未満",
        "板偏り・深さを入口スコアにしていない。ラージ気配によるモデル")
    add(["E01"], ["tick"], "到達ラベル。通常決済・逆指値運用ではない", "買Ask/売Bid新規、買Bid/売Ask評価。物理順、期限端点含む",
        "順行>=250より先に逆行>=125なら失敗。期限15:35/翌05:50。未決着300秒超正常板空白・期限前EOFは観測不足",
        "主率=順行/全約定（逆行・期限・不足も分母）。未約定は別記。125ptは10pt刻み板で130pt等になり得る。運用損益未算出")
    for index in (2, 3, 4, 6, 9, 10, 17, 20, 21):
        settings[index - 1]["適用候補ID"] = ["診断用固定候補"]
    labels = ["EMA20方向/距離", "EMA20方向/距離", "EMA20方向/距離", "RSI14・5帯/なし", "RSI14入力", "ATR14・五帯",
              "前20足比>=1.2/なし", "実体0.6・位置0.8等", "変化1/3/6本", "高安6/12/24本・125/250", "終値6本端突破",
              "EMA20復帰", "12本端復帰・125/250", "前1〜3本水準・0〜125", "収縮60窓＋TR拡大", "実体>=0.6・位置>=0.8",
              "判断5・環境15/30", "深さ2〜5・葉40/80/160", "葉7/15・学習率0.05/0.1", "正Bid<Ask・数量>=1", "逆行125/順行250"]
    for item, label in zip(settings, labels, strict=True):
        item["短記"] = label
    annotate(settings, ["診断用固定候補"])
    return settings


def validate_candidates(folder: Path) -> None:
    """正本CSVの候補数と仕様を確認し、重複する全件転記を作らない。

    引数: folder(Path)は00005の正式フォルダ。
    返り値: None。全候補の仕様と数値はCSV正本を参照する。
    """
    records = read_csv(folder / "全候補_探索.csv")
    if len(records) != 4605 or len({r["候補ID"] for r in records}) != 4605:
        raise ValueError("正本CSVの候補数が不一致")
    for row in records:
        json.loads(row["仕様"])


def write_new(catalog: dict) -> None:
    """00005の設定と現時点の結果を共通表へ記入する。

    引数: catalog (dict) は共通手法一覧。
    返り値: None。後続が実行済みならその結果だけを追記する。
    """
    folder = next((ROOT / "study").glob("00005_*"))
    output = folder / "設定と結果.md"
    fixed = read_json(folder / "選択固定.json")
    config = read_json(folder / "条件.json")
    settings = new_settings(folder)
    text = f"# 試行00005：設定と結果\n\n転記日：{DATE}。NK225のみ、順行250pt先着・125pt以上逆行なしを探索。\n\n"
    text += link(MASTER, output, "コピー元の汎用表") + " / " + link(folder / "README.md", output, "試行README") + " / " + link(folder / "全候補_探索.csv", output, "4,605候補の全閾値と結果") + "\n\n"
    text += f"**探索70候補は{fixed['探索70候補数']}件。目標達成は確認できていない。** 比較候補{fixed['探索候補数']:,}件、最低支持を満たす候補{fixed['支持候補数']}件。固定した{fixed['候補ID']}は診断用であり、70%を達成した入口ではない。\n\n"
    text += "## 手法×時間スケール（共通表のコピー）\n\n未使用セルも含め51手法・9尺度を保持。モデル入力を供給したセルは特徴単独の有効性を示さない。モデル判断は5分時点、参照する足は5/15/30分。1分・3分は今回未使用。\n\n" + matrix(catalog, output, settings)
    text += setting_section(settings, ["診断用固定候補"], output)
    text += "## 六仮説と補助格子\n\n六仮説×方向3×残り4×ATR5×数量2×RSI6＝4,320件に旧六群を加え4,326規則。具体的なAND条件は設定Sと[探索コード](../../scripts/入口探索/探索.py)のfamily_mask、全展開は[全候補の閾値と結果](全候補_探索.csv)を参照。\n"
    text += table(["仮説", "主な設定と条件"], [
        ["追随復帰と構造", "S12：EMA復帰 AND S10：6本反対端距離0超125以下"],
        ["構造内位置追随", "S17：上位整合 AND S10：6本反対端距離0超125以下 AND S09：1本方向変化>0"],
        ["レンジ端復帰", "S13：上位相互不整合 AND 12本端復帰 AND 反対端0超125以下 AND 前方端250以上"],
        ["突破再テスト", "S14：上位整合 AND 前1〜3本の固定水準に接触・復帰 AND 水準距離0以上125以下"],
        ["収縮突破", "S15：上位整合 AND 前足収縮 AND 今足TR拡大 AND 6本端突破"],
        ["強い足継続", "S16：上位整合 AND 方向実体比>=0.6 AND 方向終値位置>=0.8 AND 1本方向変化>0"]])
    text += "補助格子（旧六群には追加しない）：\n" + table(["項目", "設定した値・端点"], [
        ["方向", describe(config["固定条件探索"]["directions"])],
        ["残り時間", "要求時点から評価期限まで >=30 / >=60 / >=180 / >=300分"],
        ["ATR5", "(0,50] / (25,75] / (50,125] / (75,250] / (0,100000] pt"],
        ["相対数量", "条件なし / >=1.2"], ["方向側RSI5", "条件なし / [20,45) / [30,55) / [45,65) / [50,70) / [55,80)"]])
    text += "## R01：診断用固定候補の設定と結果\n\n"
    text += f"候補ID：**{fixed['候補ID']}**。" + describe(fixed["仕様"]) + "\n\n"
    text += "売り、確定15/30分がともに下向き、直前6本最高値−5分終値が0超125pt以下、終値が前5分終値より低い。残り60分以上、0<ATR5<=100000、数量制約なし。方向側RSI5が55以上80未満（生RSIは20超45以下）。5分方向整合やEMA復帰自体は要件にしていない。\n\n"
    text += "この候補で入口条件として使用するのはEMA15/30（S02/03）、RSI5（S04）、ATR5（S06）、1本変化（S09）、6本構造（S10）、多足関係（S17）。共通準備・気配・ラベルは別途適用。モデル/数量/ローソク等の全設定がこの一候補の入口条件になるわけではない。\n\n"
    follow = folder / "後続結果.json"
    reports = dict(fixed["探索結果"])
    if follow.exists():
        check = read_json(follow)
        reports["後続検査"] = check["結果"]["後続検査"]
        text += "後続検査は固定一候補のみを実行済み。詳細は[後続結果](後続結果.json)を参照。\n\n"
        text += f"後続は{pct(reports['後続検査']['確認率'])}。20約定の支持にも未達（{reports['後続検査']['約定候補数']}約定）。成功は1開始日に集中し、30分間引きは1/8＝12.50%。探索・後続の70条件は未達。\n\n"
    else:
        text += "**後続検査は未実行。** 10/26〜10/30の数値を開いて条件を選び直していない。探索段階の結果と後続結果を区別する。\n\n"
    rows = []
    for split, result in reports.items():
        rows.append([split, result["候補数"], result["約定候補数"], result["順行先着"], result["逆行先着"], result["期限未達"], result["観測不足"], result["未約定"], pct(result["確認率"]), f"{result['約定開始日数']}日/{result['約定場数']}場", f"{result['30分間引き_順行先着']}/{result['30分間引き_約定候補数']} ({pct(result['30分間引き_確認率'])})"])
    text += table(["分割", "候補", "約定", "順行", "逆行", "期限", "不足", "未約定", "主確認率", "支持", "30分感度"], rows)
    text += "## 分割・支持・解釈\n\n学習は09/21〜10/16の20開始日40場、選択は10/19〜10/23の5日10場、後続は10/26〜10/30の5日10場。全60場は旧研究で既使用なので未見評価とは呼ばない。00004の共通準備済み10,588候補を使い、時間軸/機会の選び方自体は未拡張。\n\n"
    text += "支持は学習60約定・6開始日・10場以上、選択/後続は各20約定・3開始日・5場以上。探索70条件は学習/選択とも主率70%以上に加え、30分間引きで学習20/選択10約定以上かつ双方70%以上。間引きは要求時計で場・方向ごと、未約定も起点。分母は全約定、期限・不足を除かない。\n\n"
    text += "ラージ気配の先着確認であり、同時保有制約・実際の返済遅延・手数料を伴う運用損益は算出していない。比較候補は重複し、多重探索や日内相関がある。モデルのスコア0.7・少数葉の高率を70%の確証としない。\n\n"
    paths = [CATALOG, Path(__file__), folder / "条件.json", folder / "選択固定.json", folder / "全候補_探索.csv", folder / "特徴定義.json"]
    if follow.exists():
        paths.append(follow)
    text += provenance(paths, output)
    output.write_text(text, encoding="utf-8")
    validate_candidates(folder)


def main() -> None:
    """共通表と既存五試行を生成し、全候補は正本CSVへ参照する。

    引数: なし。
    返り値: None。入力が不整合なら例外を上げる。
    """
    catalog = read_json(CATALOG)
    assert len({m["id"] for m in catalog["methods"]}) == len(catalog["methods"])
    assert len({s["id"] for s in catalog["scales"]}) == len(catalog["scales"])
    write_master(catalog)
    for study in read_json(MAPPING)["試行一覧"]:
        write_old(catalog, study)
    write_new(catalog)
    print(f"汎用表{len(catalog['methods']) * len(catalog['scales'])}組、既存5試行、全候補4605件は正本CSVへ参照した")


if __name__ == "__main__":
    main()
