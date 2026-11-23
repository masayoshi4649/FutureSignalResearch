"""00021の保存結果を異種発動・局面選択・必須追尾へ分けて要約する。"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00021_BBとMACDとストキャスの発動切替"
DISPLAY = ROOT/"scripts/局面切替/レポート.py"
POLICIES = ("T0", "R0", "A0", "S1")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}


def display_helper() -> Any:
    """既存の汎用表と保存件数検査だけを読み込む。

    引数: なし。
    返り値: Any は表示module。数値再生や保存成績の読取を開始しない。
    """
    spec = importlib.util.spec_from_file_location("異種発動帳票の固定20表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


H = display_helper()
P, G, number = H.P, H.G, H.number


def definitions(config: dict) -> list[dict]:
    """三尺度四戦略と共通X0を全12評価へ対応付ける。

    引数: config (dict) は条件正本。
    返り値: list[dict] は全12の入口/運用・R評価。全案同じ資格判定を使う。
    """
    if config["時間足分"] != [1, 3, 5] or config["戦略"] != list(POLICIES) or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("固定三尺度・四戦略・X0と異なる")
    if config["必須追尾"]["起動幅pt"] != 5 or (config["逆行pt"], config["順行pt"]) != (125, 250):
        raise ValueError("A5必須追尾/125-250先着と異なる")
    rules = []
    for size in (1, 3, 5):
        for policy in POLICIES:
            source = {"入口ID": f"{size}分_{policy}", "戦略": policy, "時間足分": size,
                      "名称": policy, "役割": "混合", "複合本命": True}
            rules.append({"候補ID": source["入口ID"]+"_X0", "入口": source,
                          "出口": {"出口ID": "X0"}, "評価ID": f"R{len(rules)+1:02d}"})
    return rules


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict, dict]:
    """保存された全12の先着・会計感度・支持・資格を検算する。

    引数: config/report (dict) は条件/結果、rules (list[dict]) は全定義。
    返り値: tuple[dict,dict] は入口/運用のID別正本。再探索しない。
    """
    if report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性または先着定義が不一致")
    entries = {r["入口ID"]: r for r in report["入口評価"]}
    values = {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 12 or len(report["入口評価"]) != 12 or len(values) != 12 or len(report["結果"]) != 12:
        raise ValueError("全12入口/12運用と異なる")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules}:
        raise ValueError("保存ID集合が不一致")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("全案の固定定義が不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            P.validate_entry(entry[period])
            if row[period]["入口"] != entry[period]:
                raise ValueError("独立入口先着と運用の参照が不一致")
            item, n = row[period]["運用"], row[period]["運用"]["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"]+item["無取引場数"] != sessions or item["買い取引数"]+item["売り取引数"] != n or sum(item["役割別完結数"].values()) != n:
                raise ValueError("場/方向/固定役割の集計が不一致")
            if not 0 <= item["起動後純赤字取引数"] <= item["追尾起動取引数"] <= n:
                raise ValueError("起動と赤字件数が不一致")
            for slip in (0, 5, 10):
                net = item[f"追加{slip}pt純損益円"]
                if not math.isclose(net, item["追加0pt純損益円"]-20*slip*n, abs_tol=1e-8):
                    raise ValueError("費用感度が不一致")
                average = item[f"追加{slip}pt平均円"]
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均額が不一致")
                if item["品質注意場数"] and item[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("注意込み全体が確定額になっている")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["費用資格"]) != (support, bool(goal), bool(qualified)):
            raise ValueError("支持/70目標/全案共通費用資格が不一致")
    if report["表示固定ID"] != [r["候補ID"] for r in rules if r["入口"]["時間足分"] == 3]:
        raise ValueError("事前三分四資源と異なる")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("合格件数が不一致")
    return entries, values


# ----------------------------------------
# 先着と実建玉を分け、必要な比較だけをMarkdownへ要約する。

def comparison(entries: dict, values: dict) -> str:
    """三尺度四戦略を旧二期間の比較へ要約する。

    引数: entries/values (dict) は入口/運用正本。
    返り値: str は24行の比較。約定明細・全列の重複は保存しない。
    """
    rows = []
    for source, entry in entries.items():
        for period in PERIODS[:2]:
            e, o = entry[period], values[source+"_X0"][period]["運用"]
            rows.append([source, PERIOD_NAMES[period], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}",
                f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}",
                o["完結取引数"], number(o["追加5pt純損益円"]), number(o["追加5pt平均円"]), number(o["追加10pt純損益円"]),
                f"{o['活動場数']}/{o['入力場数']}", o["品質注意場数"], f"{o['起動後純赤字取引数']}/{o['追尾起動取引数']}"])
    text = "## 異種発動と局面選択の比較\n\nT0はT1だけ、R0はR1だけ、A0は両方、S1は当時のトレンド同DI方向T1/レンジR1を選ぶ。全案同じ共通Mと必須追尾を持ち、全12とも同じ費用資格を判定する。独立仮約定の250先着率と、単一建玉の黒字率/純額は別。金額は観測純額で、注意場込み全体の確定対象額は正本でnullを維持する。\n"
    text += G.table(["入口", "期間", "250先着/仮約定・率", "30分間引き順/仮約定・率", "完結", "追加5pt円", "追加5pt平均円", "追加10pt円", "活動/入力場", "注意場", "起動後純赤字/起動"], rows)
    positive = [cid for cid, row in values.items() if all(row[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS[:2])]
    text += "両旧期間で追加5pt後の観測純額が正の案："+("、".join(positive) if positive else "なし")+"。観測黒字と支持/品質込み費用資格を分け、0取引や少数例を安定収益としない。既使用最終1場も正本へ残し、旧二期間の支持不足を補う選別には使わない。\n\n"
    improved = all(entries[f"{size}分_S1"][p]["確認率"] is not None and entries[f"{size}分_A0"][p]["確認率"] is not None
        and entries[f"{size}分_S1"][p]["確認率"] > entries[f"{size}分_A0"][p]["確認率"] for size in (1, 3, 5) for p in PERIODS[:2])
    if improved:
        text += "S1の確認率は、1/3/5分の各尺度で学習/条件選択ともA0より高かった。これは分母を減らした同じ既使用市場での記述的な選別改善で、有意性や将来再現の証明ではない。入口70%にも費用資格にも届かず、見送った成功・失敗と同じ新規の会計を併せて読む。\n\n"
    a, b = [values[f"3分_{strategy}_X0"]["条件選択"]["運用"] for strategy in ("A0", "S1")]
    text += f"事前3分代表の条件選択ではA0→S1で完結{a['完結取引数']}→{b['完結取引数']}、追加5pt後総額{number(a['追加5pt純損益円'])}→{number(b['追加5pt純損益円'])}円となった一方、1取引平均は{number(a['追加5pt平均円'])}→{number(b['追加5pt平均円'])}円。総額の損失縮小を、1取引の費用後品質の改善と同一視しない。\n\n"
    return text


def diagnosis(study: Path, output: Path) -> str:
    """局面機会・見送り・参加集合と保護不足の正式診断を参照する。

    引数: study/output (Path) は試行/表示先。
    返り値: str は任意診断の状態と要約。未保存を成功にしない。
    """
    path = study/"対応診断.json"
    if not path.exists():
        return "## 見送りと参加集合の診断\n\n未完・対応診断は未保存。局面×T1/R1×side×期間の五ラベル、共通M除外、A0→S1の共通新規/参加集合、追尾後の価格不足と費用後赤字は正式保存後に反映する。\n\n"
    data = G.read_json(path)
    if data.get("結果SHA256") != G.sha(study/"結果.json"):
        raise ValueError("対応診断の結果SHAが不一致")
    verdict = data.get("全件一致", data.get("対応集合全件一致"))
    text = "## 見送りと参加集合の診断\n\n"+G.link(path, output)+"："+("全件一致" if verdict is True else "不一致または明示合否未確認")+f"・{number(data['照合項目数'])}項目。全有効発動{number(data['全発動候補数'])}・戦略別純入口{number(data['純入口数'])}を記録。戦略間/足幅間の重複を独立標本へ加算しない。全戦略採否は最終shadowを正本とし、case内他戦略欄の既知43表示差は分析入力に使っていない。\n\n"
    preparation = [r for r in data["準備総括"] if r["期間"] in PERIODS[:2]]
    text += "### 発動前の準備範囲\n\n指標未準備の価格足に架空の先着を作らず、Mと時間条件が揃ったT1/R1だけを比較する。除外理由は多重ラベルで、延べ数を足して除外足数としない。\n"
    text += G.table(["足分", "期間", "全足", "公開足", "M足", "時間付きM足"],
        [[r["足分"], PERIOD_NAMES[r["期間"]], r["全足数"], r["公開足数"], r["共通M足数"], r["時間条件付きM足数"]] for r in preparation])
    stages = [r for r in data["段階別"] if r["足分"] == 3 and r["期間"] in PERIODS[:2]]
    text += "### 事前3分代表の選択段階\n\n各欄は候補数・250先着/仮約定。固定順序での記述で、独立した条件効果ではない。全局面×系統×side/DI整合と五ラベルは正本へ残す。\n"
    text += G.table(["戦略", "期間", "全有効発動", "手法/当時局面選択", "競合除外後"],
        [[r["戦略"], PERIOD_NAMES[r["期間"]], *[f"{s['候補数']}件・{s['順行先着']}/{s['約定候補数']}" for s in r["段階"]]] for r in stages])
    selected = [r for r in data["A0対S1発動集合"] if r["足分"] == 3 and r["期間"] in PERIODS[:2]]
    text += "### S1はA0の単純部分集合ではない\n\nA0で両方向が競合して全見送りでも、S1で局面に合う片方だけが残る場合がある。以下は発動集合の五ラベル（順/逆/期限/不足/未約定）で、実新規対応とは別。見送った失敗と逃した成功の双方を読む。\n"
    labels = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")
    text += G.table(["期間", "共通発動：五ラベル", "A0のみ：五ラベル", "S1のみ：五ラベル"],
        [[PERIOD_NAMES[r["期間"]], *["/".join(str(r[k][label]) for label in labels) for k in ("共通発動", "A0のみ", "S1のみ")]] for r in selected])
    matched = []
    for r in data["運用対応"]:
        if r["左"] != "3分_A0_X0" or r["右"] != "3分_S1_X0" or r["期間"] not in PERIODS[:2]:
            continue
        p = r["運用比較"]
        difference = p["右側のみ純額円"]-p["左側のみ純額円"]
        if not math.isclose(p["全運用純額差円"], p["共通実新規純額差円"]+difference, abs_tol=1e-8):
            raise ValueError("共通新規と参加集合の会計分解が不一致")
        matched.append([PERIOD_NAMES[r["期間"]], f"{p['共通実新規数']}/{p['左側のみ実新規数']}/{p['右側のみ実新規数']}",
            number(p["共通実新規純額差円"]), number(p["左側のみ純額円"]), number(p["右側のみ純額円"]), number(p["全運用純額差円"])])
    text += "### 同じ新規の出口差と参加集合\n\n基準費用のS1−A0純額差＝共通新規の出口差＋S1のみ純額−A0のみ純額。混合A0と切替S1は同じX0追尾を使うので、総額差を利益回収そのものの改善としない。\n"
    text += G.table(["期間", "共通/A0のみ/S1のみ実新規", "共通出口差円", "A0のみ純額円", "S1のみ純額円", "全純額差円"], matched)
    recovery = [r for r in data["入口先着と利益回収"] if r["候補ID"] in ("3分_T0_X0", "3分_R0_X0", "3分_S1_X0") and r["期間"] in PERIODS[:2]]
    text += "### 入口が250先着でも回収できたとは限らない\n\n各実新規から期限まで仮に追った125/250先着は、実際の追尾返済後の価格も含む反実仮想。『先着250だが純赤字』は保有中250到達後に失った件数ではない。入口の方向予測と、早い追尾/待機/費用による回収を分ける事後診断で、将来250へ進む入口だけを新規へ戻さない。\n"
    text += G.table(["候補", "期間", "系統", "実新規対応", "250先着", "250先着だが基準赤字", "125先着", "125先着だが基準黒字"],
        [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["系統"], r["実新規対応数"], r["対応先着250数"], r["先着250だが基準純赤字数"], r["対応先着125数"], r["先着125でも基準黒字数"]] for r in recovery])
    protection = [r for r in data["利益保護"] if r["候補ID"] in ("3分_A0_X0", "3分_S1_X0") and r["期間"] in PERIODS[:2]]
    text += "### 保護設定と実約定・費用\n\n最低同値の設定は同値以上の実約定や費用後黒字を保証しない。返済pending後のMFEだけで未起動を補わず、価格の不足と純赤字を別に記録する。全12の不足・MFE後赤字は正本JSONへ保存する。\n"
    text += G.table(["候補", "期間", "起動", "起動後基準赤字", "起動後同値未満約定", "最終設定未満約定", "設定から不足pt計"],
        [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["追尾起動数"], r["起動後純赤字数"], r["起動後同値未満約定数"], r["最終設定未満約定数"], number(r["最終設定からの不足pt計"])] for r in protection])
    return text


def settings(rules: list[dict]) -> list[dict]:
    """51×9表へ使用セル・閾値・複合評価を対応付ける。

    引数: rules (list[dict]) は全12評価。
    返り値: list[dict] は設定S。未使用指標を使った表示にしない。
    """
    groups = []
    for size in (1, 3, 5):
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        trend = [r for r in same if r["入口"]["戦略"] in ("T0", "A0", "S1")]
        reversal = [r for r in same if r["入口"]["戦略"] in ("R0", "A0", "S1")]
        scale = [f"m{size:02d}"]
        groups += [
            (["I03"], scale, same, "MACD12/26・signal9、EMA算術seed", "H=MACD−signal。下位H三点は冷開始最短36本、MACD初26/Signal初34。共通Mは上位ADX等の公開準備も必要"),
            (["I05", "I09", "I07"], scale, same, "共通M：BB20母σ正/中心正・ATR14正・SlowK有限", "三公開足で揃え同じ助走。DはSMA3診断のみ、RSI/EMAの追加gateは使わない"),
            (["I03", "I05"], scale, trend, "T1：C中心有利/w増/ΔH前非正→ΔH現正", "w=4母σ/中心。売は鏡像、前差等号可/現差等号不可。H水準のゼロ交差ではない"),
            (["I05", "I07"], scale, reversal, "R1：買C<中心・K前<=20<K現、売鏡像80", "rawK14→SMA3のSlowK。外帯の上下限・K/D交差・前終値からの価格改善を追加要求しない"),
        ]
    chosen = [r for r in rules if r["入口"]["戦略"] == "S1"]
    groups += [
        (["I08", "C04", "C07"], ["m15"], rules, "共通M：最新公開ADX14/±DI14有限", "下位公開key/end以下を結合。EMAを上位準備へ追加しない。未準備と待機を区別"),
        (["I08", "C04"], ["m15"], chosen, "S1：ADX<=20 R1、>=25 DI一致T1、他待機", "高ADXでDI同値なら待機。過去の利益や将来ラベルで切り替えない"),
        (["B01"], ["tick"], rules, "一建玉/一注文・全要求後1価格時計秒", "ラージBBOでmicro1枚代理、新規買Ask/売Bid・返済買Bid/売Ask、新規有効30秒"),
        (["I09", "C06", "E02"], ["tick"], rules, "A=5、D=max(5,ceil(入口ATR/5)×5)必須追尾", "起動後最低同値/買ceil売floor/非緩和。pending中更新停止、125保護/250利確/期限優先"),
        (["E01"], ["tick"], rules, "独立125逆行前250順行・支持付き70%", "全仮約定分母に期限/不足を残す。30分間引きは30分足でなく、単一建玉損益とも別"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
        "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
        for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """正式合成・主/状態/追尾・対応/Viewerの明示合否を別掲する。

    引数: study/output (Path) は試行/文書出力先。
    返り値: tuple[str,list[Path]] は状態表/出典。重複する項目数は加算しない。
    """
    checks = [("合成検証.json", "最終34合成・編集終了"), ("独立監査.json", "主先着・会計・正式成果物"),
        ("状態独立確認.json", "新指標銀行・三公開足・ADX選択・全shadow"), ("追尾独立確認.json", "native不要追尾の初着・役割・全ログ"),
        ("対応診断.json", "見送り・共通新規/参加集合・保護不足"), ("Viewer照合.json", "事前三分表示のAPI照合")]
    rows, paths = [], []
    for name, label in checks:
        path = study/name
        if not path.exists():
            rows.append([label, "未完・未保存", "未算出", "なし"])
            continue
        data = G.read_json(path)
        verdict, count = data.get("全件一致"), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data.get("全件成功") is True and data.get("合成編集終了") is True, data["検証件数"]
        elif name == "対応診断.json" and verdict is None:
            verdict = data.get("対応集合全件一致")
        elif name == "Viewer照合.json" and verdict is None:
            cases = data.get("照合", [])
            verdict, count = (all(r.get("一致") is True for r in cases) if cases else None), len(cases)
        status = "合格" if verdict is True else "不一致/失敗" if verdict is False else "明示合否未確認"
        if name in ("状態独立確認.json", "独立監査.json") and verdict is True:
            status = "数値/自己採否/集合一致・他戦略表示差別掲"
        rows.append([label, status, number(count), G.link(path, output)])
        paths.append(path)
    display_path = study/"入口内他戦略表示差.json"
    display_count = 43
    if display_path.exists():
        display = G.read_json(display_path)
        if display["実選択判定一致"] is not True or display["他戦略表示差件数"] != len(display["他戦略表示差"]):
            raise ValueError("既知表示差と実選択判定の範囲が不一致")
        display_count = display["他戦略表示差件数"]
    text = "## 検査の状態\n\n最終34合成・編集終了true・関係6SHA実一致と静読後に固定。主/状態/追尾は同じ市場観測や参照を含み、照合件数を加算して独立標本とはしない。保存ファイルの存在だけで合格にせず明示判定を読む。未保存は未完を維持する。\n\n"
    text += f"**既知の表示差：採用case内の他戦略A0採否に{display_count}行の古い表示が残る。** 後続競合の確定前にcopyしたためで、実選択戦略の自己判定/採用集合/数値は一致する。全戦略の採否は最終shadowを正本とし、case内の他戦略snapshotをそのまま分析へ使わない。生case/core/成績は上書きせず差分を別保存した。全成果物の全文一致や表示差ゼロを主張する検査ではない。\n\n"
    if display_path.exists():
        text += G.link(display_path, output)+"に対象イベントと正本採否を保存。独立側の別順snapshot比較126件とは単位が異なり、実43表示行へ加算しない。\n\n"
        paths.append(display_path)
    else:
        text += "正式差分JSONの保存待ち。独立側の別順snapshot比較126件と実43表示行は別の単位である。\n\n"
    text += G.table(["範囲", "明示合否", "件/項目数", "正本"], rows)
    text += "合格は模型と保存成果物の整合であり、空白内の経路/正確な受信時計/将来の収益性の証明ではない。監査準備の人工proofも正式34合成や全件監査へ加算しない。\n\n"
    state_path, trail_path = study/"状態独立確認.json", study/"追尾独立確認.json"
    if state_path.exists():
        data = G.read_json(state_path)
        text += f"状態側は原価格cacheから1/3/5/15分足と算術seed MACD/母BB/SlowK/ATR/ADX/DIを別計算し、{number(data['保存context数'])}足・{number(data['保存shadow数'])}発動shadow・{number(data['保存入口数'])}入口集合を検査した。caseは自己判定と実指標/時点を確認し、他戦略表示差を別掲した。原板全行を別再抽出した証明ではない。\n\n"
    if trail_path.exists():
        data = G.read_json(trail_path)
        text += f"追尾側は保存された実保有区間を固定し、{number(data['対象場候補数'])}場候補・{number(data['対象完結取引数'])}完結・{number(data['保存追尾行数'])}全ログの初着要求/起動/非緩和/役割/MFEを原正常気配から照合。受注/一建玉/+1秒約定/会計は主監査と分担し、子件数は主へ非加算。\n\n"
    viewer_path = study/"Viewer照合.json"
    if viewer_path.exists():
        data = G.read_json(viewer_path)
        text += "### Viewer代表確認\n\n"+str(data["接続先"])+"・設定 "+str(data["設定"])+"・"+str(data["WindowStyle"])+"起動。market_pathは設定data_root基準、pnl_pathは一覧親基準。事前の3分四戦略を表示し採用選別とはしない。PNG追加"+str(data["追加PNG数"])+"枚。\n"
        text += G.table(["候補", "場", "研究/API実現円", "API買/売保有", "数値指紋", "一致"],
            [[r["手法"], r["場"], f"{number(r['研究側純損益円'])}/{number(r['API最終状態']['realized_pnl_yen'])}",
              f"{r['API最終状態']['long_qty']}/{r['API最終状態']['short_qty']}",
              "一致" if r["数値本文SHA256一致"] else "不一致", "一致" if r["一致"] else "不一致"] for r in data["照合"]])
    return text, paths


# ----------------------------------------
# 完成通知後だけ正式数値を読み、比較要約と必須の設定表へ絞る。

def run(study: Path, output: Path) -> list[Path]:
    """正式保存結果をREADMEと設定と結果へ要約する。

    引数: study/output (Path) は試行/文書先。
    返り値: list[Path] は二文書。全件転記MDや売買再計算は作らない。
    """
    for name in ("条件.json", "計画.md", "固定.json", "結果.json", "入力台帳.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存のため数値文書を生成しない")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    if any(G.sha(ROOT/path) != sha for path, sha in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定core/条件/合成/入力SHAが変化")
    pointer = G.read_json(study/"入力台帳.json")
    manifest_path = (study/pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("入力台帳参照が不一致")
    catalog = G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("51×9カタログが変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path = output/"README.md", output/"設定と結果.md"
    intro = "NK225の1/3/5分×T0/R0/A0/S1の12入口・共通X0必須追尾12運用。全案が新しい複数手法の発動候補で、全12に同じ入口支持/費用資格を判定した。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部の後続検査も未見確認ではない。保存結果の表示だけを行い、入力や売買を再生しない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/12、費用資格は{report['費用資格数']}/12。** 先着率と運用黒字率、保護設定と費用後実績を分けて読む。\n\n"
    methods = "## 発動と局面選択\n\nMはBB20の中心/母σ正、ATR14正、MACDヒストグラムHとSlowKが有限の同場連続公開三足と、最新公開15分ADX/±DI有限を要求。現在確認遅延<=30秒、新規停止前、期限残60分以上。過去二足へ遅延gateを追加せず、SlowD/RSI/EMA/VWAP/N4/数量を新しい必須gateにしない。\n\n"
    methods += G.table(["発動", "役割", "条件"], [["T1", "順行", "買C>BB中心、w>w前、ΔH前<=0<ΔH現。売はC<中心、ΔH前>=0>ΔH現"], ["R1", "反転", "買C<BB中心、SlowK前<=20<現。売C>中心、前>=80>現"]])
    methods += "H=MACD−signal、w=4母σ/正中心。T1はH水準のゼロ交差やMACD線signal交差ではなく、Hの増減が非加速側から加速側へ変わる点を使う。R1は中心の反対側とK領域復帰だけを使い、帯内上下限・K/D交差・前終値からの価格改善を追加しない。売買は同じ閾値を符号対称にする。\n\n"
    methods += "15分はADX<=20でレンジ、ADX>=25かつDI差の方向が±1でトレンド、他は待機。EMAを判別へ追加しない。未準備と既知の待機を分け、公開key/endとも下位以下の最新値を使う。T0はT1のみ、R0はR1のみ、A0は両方、S1はトレンド同DI方向T1/レンジR1だけ。見送りを逆方向新規へ自動変換しない。\n\n"
    timing = "## 銀行の初期化と判断時点\n\nMACDはEMA12/26とsignal EMA9を各算術平均でseedし、冷開始の初MACDは26本目、signal/Hは34本目、下位H三点という要件の最短は36本目。共通M全体の成立は上位15分ADX等の準備・公開も揃った時点となる。SlowKは当足を含むrawK14をSMA3、SlowDはKをさらにSMA3にし、初K16本目/初D18本目。Dは診断だけ。HH14=LL14ではrawKを補わずK/D平滑窓をclearし、高安14窓は保持。次の3連続rawでK、さらに3連続KでDを再種する。\n\n"
    timing += "銀行は旧W同値で全完全幅足を更新し、終端publishFalseも数値更新する。同限月なら場間carry、missing前/尾部欠枠/限月変更でreset。場開始だけでは銀行を切らない一方、発動の三足比較は同場だけで欠枠/非公開/index飛越/必要単点欠測によりclearする。したがって『36本』は毎場開始からの待機本数ではない。非公開足で発動せず、同時計の後原行や終了前の公開値を先取りしない。\n\n"
    protection = "## 一建玉と必須の利益追尾\n\n共通X0はhard125保護/TP250/期限とA5利益追尾。新規signalのATRを固定しD=max(5,ceil(入口ATR/5)×5)、実新規後・返済要求前の正常返済BBOでMFE>=5を観測したら起動する。方向側保護利益=max(0,MFE−D)を価格へ変換し、買ceil/売floorで5pt丸め、起動後最低新規同値・前設定より緩めない。\n\n"
    protection += "同原行は正常気配→公開足→入口、優先は期限/既pending約定→hard125→TP250→追尾。返済pending中は追尾起動/線更新を止め、後のMFEから起動を補わない。役割は実新規signalへ固定し、保有中の局面変更だけで役割/建玉を反転しない。同判断複数信号は同方向も全見送り、shadowは残す。native通常出口と架空native補完は使わない。\n\n"
    limits = "## 費用・品質・解釈の限界\n\nラージBBOをmicro1枚へ代用し倍率10円/pt・片道11円・呼値5pt。全注文は要求+1価格時計秒以上の最初正常BBO、新規有効30秒、新規買Ask/売Bid・返済買Bid/売Ask。設定価格で即時約定させず、同値以上の保護設定でもgap/待機/費用で純赤字がある。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、滑り後の発動/参加を再生したものではない。\n\n"
    limits += "300秒超正常BBO空白/EOF/未解消を含む全体の確定対象額はnullを維持。最大場内DDは期間最大の一場で累積期間DDではない。MFE20/50/100後純赤字は事後峰と最終純額の関係で、峰で回収可能だった証明ではない。見送りの250/125先着は仮参加の事後評価で、因果的な回避利益としない。共通実新規の出口差と片側だけの参加、費用後額と価格床を分ける。\n\n"
    limits += "BB/MACD/Stoch/ADXは同じ価格由来の関連特徴で、独立した票ではない。加速や領域復帰を参加者心理/需給の説明仮説にできるが、動機や建値を観測した事実ではない。全65既使用の追加開発で、将来の採用には別の未使用期間確認が必要。\n\n"
    threshold_table = "## 固定条件の要約\n"+G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    rule_table = "## 全12評価と表示代表\n\nViewerは実行前に固定した3分四資源だけ。1/5分を未実行とはせず全数値は結果JSON/場別CSVへ保存する。\n"+G.table(["評価", "候補", "Viewer", "入口支持", "70目標", "費用資格"], [[r["評価ID"], r["候補ID"], "表示" if r["入口"]["時間足分"] == 3 else "work明細・正式集計", "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    audit_text, audit_paths = audits(study, readme)
    body = "# 試行00021：BB・MACD・ストキャスの異種発動と局面選択\n\n"+intro+" / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json"))+" / "+G.link(setting_path, readme)+"\n\n"+conclusion+methods+timing+protection+comparison(entries, values)+diagnosis(study, readme)+limits+audit_text
    common = settings(rules)
    method_ids, scale_ids = {m["id"] for m in catalog["methods"]}, {s["id"] for s in catalog["scales"]}
    if any(set(s["手法ID"])-method_ids or set(s["尺度ID"])-scale_ids for s in common):
        raise ValueError("設定が51×9へ対応しない")
    mapping = "# 試行00021：設定と結果\n\n"+intro+conclusion+G.link(G.MASTER, setting_path, "コピー元の汎用表")+" / "+G.link(readme, setting_path)+" / "+G.link(study/"結果.json", setting_path, "全12数値の正本")+"\n\n## 手法×時間スケール\n\n51手法×9尺度を保持。Sは新指標/共通助走/異種発動/局面選択/執行、R01〜R12は複合評価で指標単独の成績ではない。30分間引きは30分足ではない。EMAはMACD内部計算で、下位/上位EMAの別gateは未使用。\n\n"+G.matrix(catalog, setting_path, common)
    mapping += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])+threshold_table+methods+timing+protection+rule_table+limits+audits(study, setting_path)[0]
    files = ("入力台帳.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "局面品質.json", "入力品質.json", "作業成果物.json")
    viewing = "## 閲覧と再現\n\n"+" / ".join(G.link(study/n, readme) for n in files if (study/n).exists())+"\n\nViewer market_pathは設定の市場root基準、pnl_pathはpath_base=catalogの一覧親基準。追加滑り0ptの3分四運用を表示する。原板は複製せず大きな全指標足/shadow/入口/運用/追尾ログはGit外work、正式は展開内容SHAを正本に記録する。\n\n"
    names = ("指標.py", "入口.py", "運用.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py")
    sources = [ROOT/"scripts/異種発動"/n for n in names if (ROOT/"scripts/異種発動"/n).exists()]
    docs = [ROOT/"docs/議論/異種指標の発動と局面切替を比較する.md"]
    viewing += "コード："+" / ".join(G.link(p, readme) for p in sources)+"。"+("背景："+" / ".join(G.link(p, readme) for p in docs)+"。" if docs else "")+"\n\n"
    fence = chr(96)*3
    viewing += "保存結果の再表示：\n\n"+fence+"powershell\npython -X utf8 scripts/異種発動/レポート.py\n"+fence+"\n\n数値再生は検証.pyへ別の保存先/作業先を指定する。合成検証.py --finalは固定後のコード変更を拒否し、追加検査は別ファイルへ分離する。\n\n"
    paths = [Path(__file__), DISPLAY, ROOT/"scripts/VWAP復帰/レポート.py", ROOT/"scripts/収縮反転/レポート.py", ROOT/"scripts/レポート/設定結果レポート.py", G.MASTER, G.CATALOG,
        *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *files) if (study/n).exists()], manifest_path, *audit_paths, *sources, *docs]
    paths = list(dict.fromkeys(paths))
    for path, text in ((readme, body+viewing), (setting_path, mapping)):
        path.write_text(text+G.provenance(paths, path), encoding="utf-8")
    return [readme, setting_path]


def main() -> None:
    """完成通知後の保存結果から比較要約と必須設定表を生成する。

    引数: なし。--study/--outputは任意の試行/文書先。
    返り値: None。ラベル・損益・入力の再計算はしない。
    """
    parser = argparse.ArgumentParser(description="異種発動と追尾の保存結果を要約")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study, args.output or args.study)))


if __name__ == "__main__":
    main()
