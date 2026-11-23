"""00022の保存結果を準備範囲の変更と局面改訂の効果へ分けて要約する。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00022_ADXと上位BB幅の変化による局面切替"
DISPLAY = ROOT/"scripts/異種発動/レポート.py"
POLICIES = ("A0", "S1", "S2")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}


def display_helper() -> Any:
    """既存の汎用表と入口集計の検算だけを読む。

    引数: なし。
    返り値: Any は表示module。入力/ラベル/売買を再計算しない。
    """
    spec = importlib.util.spec_from_file_location("局面変化帳票の固定21表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


H = display_helper()
P, G, number = H.P, H.G, H.number


def definitions(config: dict) -> list[dict]:
    """三尺度三選択規則と共通X0を全9評価へ対応付ける。

    引数: config (dict) は固定条件。
    返り値: list[dict] は9入口/運用の定義。全て同じ費用資格を判定する。
    """
    if config["時間足分"] != [1, 3, 5] or config["戦略"] != list(POLICIES) or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("三尺度/三戦略/固定X0と異なる")
    if config["局面改訂"] != {"上位分": 15, "ADX弱境界": 20, "ADX強境界": 25, "現前同場隣接公開": True} or config["必須追尾"]["起動幅pt"] != 5:
        raise ValueError("15分ペア/20-25/A5固定条件と異なる")
    rows = []
    for size in (1, 3, 5):
        for policy in POLICIES:
            source = {"入口ID": f"{size}分_{policy}", "戦略": policy, "時間足分": size,
                      "名称": policy, "役割": "混合", "複合本命": True}
            rows.append({"候補ID": source["入口ID"]+"_X0", "入口": source,
                         "出口": {"出口ID": "X0"}, "評価ID": f"R{len(rows)+1:02d}"})
    return rows


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict, dict]:
    """全9の件数・費用感度・支持と三分表示を検算する。

    引数: config/report (dict) は条件/結果、rules (list[dict]) は全定義。
    返り値: tuple[dict,dict] は入口/運用のID別正本。
    """
    if report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性または先着定義が不一致")
    entries, values = {r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 9 or len(report["入口評価"]) != 9 or len(values) != 9 or len(report["結果"]) != 9:
        raise ValueError("全9入口/運用と異なる")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules}:
        raise ValueError("保存ID集合が不一致")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("全案定義が不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            P.validate_entry(entry[period])
            if row[period]["入口"] != entry[period]:
                raise ValueError("独立先着と運用参照が不一致")
            item, n = row[period]["運用"], row[period]["運用"]["完結取引数"]
            if item["入力場数"] != sessions or item["活動場数"]+item["無取引場数"] != sessions or item["買い取引数"]+item["売り取引数"] != n or sum(item["役割別完結数"].values()) != n:
                raise ValueError("場/方向/役割数が不一致")
            if not 0 <= item["起動後純赤字取引数"] <= item["追尾起動取引数"] <= n:
                raise ValueError("追尾起動/赤字数が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"]-20*slip*n, abs_tol=1e-8):
                    raise ValueError("費用感度が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均額が不一致")
                if item["品質注意場数"] and item[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("品質注意込み全体が確定額になっている")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], row["費用資格"]) != (support, bool(goal), bool(qualified)):
            raise ValueError("支持/70/費用資格が不一致")
    if report["表示固定ID"] != [r["候補ID"] for r in rules if r["入口"]["時間足分"] == 3]:
        raise ValueError("事前三分3資源と異なる")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in entries.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("合格件数が不一致")
    return entries, values


# ----------------------------------------
# M22という同じ機会集合で旧S1と改訂S2を並べ、M21との差を別に残す。

def comparison(entries: dict, values: dict) -> str:
    """全9の旧二期間を先着・参加・費用後額で比較する。

    引数: entries/values (dict) は入口/運用正本。
    返り値: str は18行の要約。全列や全約定を転記しない。
    """
    rows = []
    for source, entry in entries.items():
        for period in PERIODS[:2]:
            e, o = entry[period], values[source+"_X0"][period]["運用"]
            rows.append([source, PERIOD_NAMES[period], f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}",
                f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}",
                o["完結取引数"], number(o["追加5pt純損益円"]), number(o["追加5pt平均円"]),
                number(o["追加10pt純損益円"]), f"{o['活動場数']}/{o['入力場数']}", o["品質注意場数"]])
    text = "## 同じM22での局面比較\n\n全9に同じM22と固定21の追尾/費用を使う。A0は常時混合、S1は旧水準分類、S2は現前変化を使う。金額は観測純額で、注意場を含む全体の確定対象額は正本でnullを維持する。仮約定先着率と単一建玉の黒字率/純額を混同しない。\n"
    text += G.table(["入口", "期間", "250先着/仮約定・率", "30分間引き順/仮約定・率", "完結", "追加5pt円", "追加5pt平均円", "追加10pt円", "活動/入力場", "注意場"], rows)
    positive = [cid for cid, r in values.items() if all(r[p]["運用"]["追加5pt純損益円"] > 0 for p in PERIODS[:2])]
    text += "両旧期間で追加5pt後の観測純額が正の案："+("、".join(positive) if positive else "なし")+"。総額差と1取引平均、支持/品質を分け、既使用最終1場で旧二期間の不足を補わない。\n\n"
    changes = []
    for size in (1, 3, 5):
        e1, e2 = entries[f"{size}分_S1"], entries[f"{size}分_S2"]
        v1, v2 = values[f"{size}分_S1_X0"], values[f"{size}分_S2_X0"]
        changes.append([size, *[G.pct(e1[p]["確認率"])+"→"+G.pct(e2[p]["確認率"]) for p in PERIODS[:2]],
            *[number(v1[p]["運用"]["追加5pt平均円"])+"→"+number(v2[p]["運用"]["追加5pt平均円"]) for p in PERIODS[:2]]])
    text += "### S1からS2への変化は一貫したか\n"+G.table(["足分", "学習先着率S1→S2", "選択先着率S1→S2", "学習追加5pt平均円S1→S2", "選択追加5pt平均円S1→S2"], changes)
    text += "事前3分代表では先着率が両旧期間で上がる一方、学習の1取引平均は悪化し条件選択は改善した。1分/5分では同じ改善を示しておらず、上位判別を変えれば全尺度で有効になるとの結論にはしない。\n\n"
    return text


def diagnosis(study: Path, output: Path) -> str:
    """M21除外とS1/S2変更、参加集合、保護診断を正式正本へ結び付ける。

    引数: study/output (Path) は試行/文書先。
    返り値: str は任意診断の明示状態。未保存なら未完を維持する。
    """
    path = study/"対応診断.json"
    if not path.exists():
        return "## 準備除外と局面変更の診断\n\n未完・正式対応診断は未保存。旧4475rawをM22で消さず、旧M21→新M22除外、低ADX始動の追加/高ADX失速の見送り/R→WAIT、共通実新規と参加集合、保護設定と実返済の不足を保存後に反映する。\n\n"
    data = G.read_json(path)
    if data.get("結果SHA256") != G.sha(study/"結果.json"):
        raise ValueError("対応診断の結果SHAが不一致")
    old_result = ROOT/"study/00021_BBとMACDとストキャスの発動切替/結果.json"
    if data["旧結果SHA256"] != G.sha(old_result):
        raise ValueError("対応診断の旧結果SHAが不一致")
    verdict = data.get("全件一致", data.get("対応集合全件一致"))
    text = "## 準備除外と局面変更の診断\n\n"+G.link(path, output)+"："+("一致" if verdict is True else "不一致または明示合否未確認")+f"・{number(data['照合項目数'])}項目。旧raw{number(data['全旧発動数'])}の{data['旧発動照合フィールド数']}フィールド/ラベルを照合し、M22通過{number(data['新M22発動数'])}/除外{data['準備除外数']}。戦略別case{number(data['純入口数'])}は重複する機会を含み、独立標本に加算しない。全case全戦略属性一致は"+("確認済み" if data["全case全戦略属性一致"] is True else "未確認/不一致")+"。\n\n"
    text += "### M21→M22で失った機会\n\n局面条件以前の準備範囲変更。除外した発動にも将来先着を残し、選別の成功へ混ぜない。五ラベルは順/逆/期限/不足/未約定。\n"
    text += G.table(["足分", "期間", "旧raw候補", "M22通過候補", "準備除外候補", "除外の五ラベル"],
        [[r["足分"], PERIOD_NAMES[r["期間"]], r["旧M21全発動"]["候補数"], r["新M22通過"]["候補数"], r["準備除外"]["候補数"],
          "/".join(str(r["準備除外"][k]) for k in ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定"))] for r in data["準備差"] if r["期間"] in PERIODS[:2]])
    labels = ("順行先着", "逆行先着", "期限未達", "観測不足", "未約定")
    buckets = defaultdict(Counter)
    categories = ("低ADX始動の追加", "高ADX失速の抑止", "R発動を始動局面で抑止", "R発動を非レンジ待機で抑止")
    for r in data["局面選択差"]:
        if r["足分"] == 3 and r["期間"] in PERIODS[:2] and r["変化区分"] in categories:
            buckets[(r["期間"], r["変化区分"])].update({k: r[k] for k in ("候補数", "約定候補数", *labels)})
    text += "### 事前3分代表で何を追加し何を見送ったか\n\nS1とS2で採否が変わる方向を分ける。見送りで避けた125先着だけでなく逃した250先着も残す。局面別先着は仮参加の反実仮想で実現損益ではない。\n"
    text += G.table(["期間", "変化区分", "候補", "250先着/仮約定", "125先着", "期限/不足/未約定"],
        [[PERIOD_NAMES[p], category, r["候補数"], f"{r['順行先着']}/{r['約定候補数']}", r["逆行先着"],
          "/".join(str(r[k]) for k in ("期限未達", "観測不足", "未約定"))] for (p, category), r in buckets.items()])
    text += "### 準備差と判別差の会計を分ける\n\n基準費用の右−左純額差は、共通実新規の出口差＋右側だけ純額−左側だけ純額へ分解する。下表の上段は21→22の同じS1（準備の変更）、下段は22内S1→S2（局面の変更）。どちらも総額差だけで1取引の回収改善とはしない。\n"
    matched = []
    for r in data["M21対M22運用対応"]:
        if r["候補ID"] == "3分_S1_X0" and r["期間"] in PERIODS[:2]:
            matched.append(("21S1→22S1・準備差", r))
    for r in data["運用対応"]:
        if r["左"] == "3分_S1_X0" and r["右"] == "3分_S2_X0" and r["期間"] in PERIODS[:2]:
            matched.append(("22S1→22S2・判別差", r))
    rows = []
    for label, r in matched:
        p = r["運用比較"]
        participation = p["右側のみ純額円"]-p["左側のみ純額円"]
        if not math.isclose(p["全運用純額差円"], p["共通実新規純額差円"]+participation, abs_tol=1e-8):
            raise ValueError("準備/判別の会計分解が不一致")
        rows.append([label, PERIOD_NAMES[r["期間"]], f"{p['共通実新規数']}/{p['左側のみ実新規数']}/{p['右側のみ実新規数']}",
            number(p["共通実新規純額差円"]), number(participation), number(p["全運用純額差円"])])
    text += G.table(["比較", "期間", "共通/左のみ/右のみ実新規", "共通出口差円", "参加集合差円", "全純額差円"], rows)
    protected = [r for r in data["利益保護"] if r["候補ID"] in ("3分_S1_X0", "3分_S2_X0") and r["期間"] in PERIODS[:2]]
    text += "### 同値保護と実回収\n\n同じA5追尾でも、最低同値設定と同値以上の実返済・費用後黒字は別。起動後の価格不足と純赤字を分ける。実新規に対応させた250/125先着と実回収の関係は正本の『入口先着と利益回収』へ保存し、実返済後の価格も含む反実仮想を未来の新規選別へ戻さない。\n"
    text += G.table(["候補", "期間", "起動", "起動後基準赤字", "起動後同値未満約定", "最終設定未満約定", "設定から不足pt計"],
        [[r["候補ID"], PERIOD_NAMES[r["期間"]], r["追尾起動数"], r["起動後純赤字数"], r["起動後同値未満約定数"], r["最終設定未満約定数"], number(r["最終設定からの不足pt計"])] for r in protected])
    return text


def settings(rules: list[dict]) -> list[dict]:
    """51×9表へ旧発動と新上位判別の設定・複合評価を対応付ける。

    引数: rules (list[dict]) は全9定義。
    返り値: list[dict] は設定S。DXを独立した追加手法に数えない。
    """
    groups = []
    for size in (1, 3, 5):
        same = [r for r in rules if r["入口"]["時間足分"] == size]
        scales = [f"m{size:02d}"]
        groups += [
            (["I03", "I05", "I07", "I09"], scales, same, "固定21のBB/MACD/SlowK/ATRと旧M21", "指標銀行/seed/carryと同場三公開足は変更なし。H三点冷開始36は下位要件、全Mは上位準備も必要"),
            (["I03", "I05"], scales, same, "T1：C中心有利・下位w増・H差非正→正", "売は鏡像。新上位15分幅変化をこの下位幅へ再要求しない"),
            (["I05", "I07"], scales, same, "R1：中心反対側・K20/80領域復帰", "raw14→SMA3のK、Dは診断のみ。外帯内復帰や終値改善を追加しない"),
        ]
    changed = [r for r in rules if r["入口"]["戦略"] == "S2"]
    old = [r for r in rules if r["入口"]["戦略"] == "S1"]
    groups += [
        (["I05", "I08", "C04", "C07"], ["m15"], rules, "M22：同場隣接公開現前ADX/DI有限・BB正幅", "全戦略で同じpairを要求。場頭/欠枠/非公開/indexjump/不正点で切り、最新pubcur不可の古正常fallbackなし"),
        (["I08", "C04"], ["m15"], old, "旧S1：A<=20 R、A>=25 DI方向T、他WAIT", "旧水準分類もM22助走へ揃え、21全体との額差を分類変更の効果としない"),
        (["I05", "I08", "C04"], ["m15"], changed, "S2T：d!=0・a>0・(A>=25 OR b>0)", "A=現ADX/a=現前差/b=15分w現前差。高A上昇ならb非拡大でもT、低Aには幅拡大も要求"),
        (["I05", "I08", "C04"], ["m15"], changed, "S2R：A<=20・a<=0・b<=0、他WAIT", "等号含む。DI同値はT不可でもR可、高ADX減速を直ちに反転へしない"),
        (["I08"], ["m15"], rules, "DX/ADX差は診断だけ・DX−A=13a", "同銀行seed後の隣接更新時の恒等式で独立二票でない。DI和0のDX0規約をflagで分離"),
        (["B01"], ["tick"], rules, "一建玉/一注文・+1価格時計秒・TTL30", "固定21のnative不要運用、ラージBBO/micro代理、新規買Ask/売Bid・返済買Bid/売Ask"),
        (["I09", "C06", "E02"], ["tick"], rules, "固定21 A5/入口ATRceil距離・最低同値ratchet", "全X0 hard125/TP250/期限・pending更新停止。設定同値は実約定/純額の保証でない"),
        (["E01"], ["tick"], rules, "125逆行前250先着・全仮約定分母", "30分間引きは30分足でない。旧raw4475保持/M22後case、未来先着を新規判定に使わない"),
    ]
    return [{"設定ID": f"S{i:02d}", "手法ID": methods, "尺度ID": scales, "短記": short, "説明": detail,
        "結果短記": "・".join(r["評価ID"] for r in applies), "適用評価": [r["評価ID"] for r in applies]}
        for i, (methods, scales, applies, short, detail) in enumerate(groups, 1)]


def audits(study: Path, output: Path) -> tuple[str, list[Path]]:
    """正式合成・主/状態/追尾・対応/Viewerの明示合否を別掲する。

    引数: study/output (Path) は試行/文書先。
    返り値: tuple[str,list[Path]] は状態表/出典。各項目数を独立標本へ合算しない。
    """
    checks = [("合成検証.json", "最終22合成・編集終了"), ("独立監査.json", "主先着・会計・正式成果物"),
        ("状態独立確認.json", "旧raw保持/M22/pair/全戦略case採否"), ("追尾独立確認.json", "固定21運用同値・追尾初着"),
        ("対応診断.json", "M準備差・局面改訂・参加/回収"), ("Viewer照合.json", "事前三分3資源のAPI照合")]
    rows, paths = [], []
    for name, title in checks:
        path = study/name
        if not path.exists():
            rows.append([title, "未完・未保存", "未算出", "なし"])
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
        rows.append([title, "一致/合格" if verdict is True else "不一致/失敗" if verdict is False else "明示合否未確認", number(count), G.link(path, output)])
        paths.append(path)
    text = "## 検査の状態\n\n最終22合成・編集終了true・関係6SHA実一致と静読後に固定した。主/状態/追尾は同じ観測や参照を含むため件数を合算して独立標本とはしない。存在だけで成功とせず明示合否を読む。未保存は未完のまま後で再生成する。\n"+G.table(["範囲", "明示合否", "件/項目数", "正本"], rows)
    text += "全戦略の競合を第1passで確定後、第2passでcaseをdeepcopyする。自己採否に加え、全caseの全戦略verdictと最終canonical shadowの一致を合成/全件監査の対象とした。合否は上表へ記録する。旧21の43表示行は旧試行の既知表示差として残し、旧core/旧case/旧成績は修正していない。\n\n"
    text += G.link(ROOT/"study/00021_BBとMACDとストキャスの発動切替/入口内他戦略表示差.json", output, "旧21表示差の対照")+"。照合合格は模型と保存成果物の一致であり、空白内経路/正確な受信時計/将来収益性を証明しない。\n\n"
    state_path, trail_path = study/"状態独立確認.json", study/"追尾独立確認.json"
    if state_path.exists():
        data = G.read_json(state_path)
        text += f"今回22の状態側は原価格から全足/固定21指標・旧raw{number(data['保存shadow数'])}・M22通過{number(data['新M22準備raw数'])}/除外{data['新M22除外raw数']}・case{number(data['保存入口数'])}を別計算。全caseの全3戦略verdictとcanonicalの不一致は{data['case内canonical判定不一致数']}件、表示属性注意は{str(data['表示属性注意']).lower()}。旧21の既知43表示行と今回のcase採否照合結果を分ける。主Wの未使用パターン列/原板本文の全再抽出は検査範囲外。\n\n"
    if trail_path.exists():
        data = G.read_json(trail_path)
        text += f"追尾側は保存実保有区間を入力として{data['対象場候補数']}場候補・{number(data['対象完結取引数'])}完結・{number(data['保存追尾行数'])}全ログを原正常気配から独立検査。新規受入/一秒後約定/会計は主監査と分担し、状態/追尾の項目数を主へ加算しない。\n\n"
    viewer_path = study/"Viewer照合.json"
    if viewer_path.exists():
        data = G.read_json(viewer_path)
        text += "### Viewer代表確認\n\n"+str(data["接続先"])+"・設定 "+str(data["設定"])+"・"+str(data["WindowStyle"])+"起動。事前3分A0/S1/S2を表示し採用選別とはしない。market_pathは設定data_root基準。PNG追加"+str(data["追加PNG数"])+"枚。\n"
        text += G.table(["候補", "場", "研究/API実現円", "API買/売保有", "数値指紋", "一致"],
            [[r["手法"], r["場"], f"{number(r['研究側純損益円'])}/{number(r['API最終状態']['realized_pnl_yen'])}",
              f"{r['API最終状態']['long_qty']}/{r['API最終状態']['short_qty']}",
              "一致" if r["数値本文SHA256一致"] else "不一致", "一致" if r["一致"] else "不一致"] for r in data["照合"]])
    return text, paths


# ----------------------------------------
# 完成通知後だけ結果を読み、要約と必須設定表へ絞って生成する。

def run(study: Path, output: Path) -> list[Path]:
    """保存済み正本からREADMEと設定と結果を生成する。

    引数: study/output (Path) は正式試行/文書先。
    返り値: list[Path] は二文書。原板/ラベル/損益の再計算をしない。
    """
    for name in ("条件.json", "計画.md", "固定.json", "結果.json", "入力台帳.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存")
    config, report = G.read_json(study/"条件.json"), G.read_json(study/"結果.json")
    rules = definitions(config)
    entries, values = validate(config, report, rules)
    if any(G.sha(ROOT/path) != sha for path, sha in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定core/条件/計画/合成/入力SHAが変化")
    pointer = G.read_json(study/"入力台帳.json")
    manifest_path = (study/pointer["参照"]).resolve()
    if G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("入力台帳の参照SHA不一致")
    catalog = G.read_json(G.CATALOG)
    if (len(catalog["methods"]), len(catalog["scales"])) != (51, 9):
        raise ValueError("51×9カタログが変化")
    output.mkdir(parents=True, exist_ok=True)
    readme, setting_path = output/"README.md", output/"設定と結果.md"
    intro = "NK225の1/3/5分×A0/S1/S2＝9入口・共通X0必須追尾9運用。指標銀行/下位T1-R1発動/native不要運用は固定21を読取再用し、同じ新M22で上位判別だけを比較した。全65場は既使用（学習40・条件選択24・既使用11/4デイ1）。内部の後続検査も未見確認ではない。保存結果を表示するだけで売買を再計算しない。\n\n"
    conclusion = f"**支持付き入口70目標は{report['入口70目標達成数']}/9、費用資格は{report['費用資格数']}/9。** 全9を通常の支持/費用条件で判定し、先着率と運用黒字率を分けて読む。\n\n"
    preparation = "## 変更した準備と保持した発動\n\n旧M21は同場三公開足のH/K有限・BB中心/母σ/ATR正、最新公開15分ADX/DI有限、現在確認遅延<=30秒・停止前・期限残60分。新M22はこれに、同場隣接公開15分の現/前ともADX/DI有限・BB中心/母σ/帯幅正を加える。A0/S1/S2を同じM22へ揃え、旧M21からの準備除外と局面選別の変化を別に評価する。\n\n"
    preparation += "旧21の全有効raw発動4,475を保持し、M22不可もshadowへ残す。caseはM22成立後の選択集合だけとする。T1はBB中心の有利側・下位正規化幅増・MACD-H差の非加速→加速、R1は中心反対側・SlowK20/80領域復帰で、固定21条件をそのまま旧生成へ渡す。D/EMA/RSI/VWAP/数量や追加の価格改善を新規gateへ混ぜない。\n\n"
    preparation += "指標の算術seed/carry/resetも固定21同値。下位H三点は冷開始最短36本の要件だが、共通M全体は上位指標の準備/公開も必要。数値銀行は非公開完全幅足も更新する一方、routerの前値は同場隣接公開だけ。前場非公開末尾を前公開足へ流用しない。\n\n"
    timing = "## 上位現前ペアの時点\n\n上位は公開(clock,line)<=下位判断keyかつ15分end<=下位endの最新公開cur。非公開marker自体で以前の公開判断を改訂しないが、分類内部のペア履歴は切る。次の公開curは前値なしで再出発し、さらに隣接公開するとpairへ復帰する。\n\n"
    timing += "欠枠/index飛越/非公開/必要値不正でpairを切り、reset後curが有効なら次回の前候補一本目にする。不正curは前候補へ残さない。最新公開curがpair不可なら古い正常pairへfallbackせず、未準備と準備済みWAITを分ける。新しい15分足ごと一回分類し、下位の繰返し参照で更新回数を増やさない。\n\n"
    logic = "## S1とS2の役割\n\nA=現ADX14、a=A−前A、w15=4母σ/SMA20、b=w15−前w15、d=sign(+DI−−DI)。S1は旧分類のA<=20レンジ、A>=25かつDI方向明確でトレンド、他待機。\n"
    logic += G.table(["改訂S2", "条件", "許可"], [["強まり/始動", "d!=0、a>0、(A>=25 OR b>0)", "d側T1"], ["低方向性・非拡大", "A<=20、a<=0、b<=0", "R1"], ["失速/不一致等", "上記以外", "待機"]])
    logic += "高ADX上昇なら上位幅非拡大でもTを許し、低ADX始動にはa/bとも正を要求。a0/b0/A20の等号はR側で、DI同値はT不可でもR可。高ADX減速を直ちに反転へしない。S2理由は強ADX上昇継続/低ADX上昇・幅拡大/低ADX非上昇・幅非拡大/高ADX失速待機/条件不一致待機/未準備の6種。\n\n"
    logic += "DX=100×abs(+DI−−DI)/(+DI+−DI)は診断だけ。DI和0は旧W同値のDX0規約とflagを残し0/0の実測値にしない。同銀行seed後の隣接更新ではA=(13前A+DX)/14よりDX−A=13aとなるので、ADX上昇とDX>ADXを独立二票へ数えず、ΔDX等の追加ANDにも使わない。非公開/欠枠を跨ぐ前公開足へ恒等式を無条件適用しない。\n\n"
    protection = "## 保持する一建玉・費用・保護\n\n固定21と同じX0を読取再用し、実新規signalの役割/ATRを固定。hard125/TP250/期限＋A5必須追尾、D=max(5,ceil(入口ATR/5)×5)、起動後最低同値・買ceil/売floor・非緩和を維持する。正常返済BBOで返済要求前にMFE>=5を実観測した取引だけを起動済みとし、pending中の追尾更新は停止。新しい通常出口や建玉中の局面だけによるドテンは追加しない。\n\n"
    protection += "ラージBBOでmicro1枚代理、倍率10円/pt・片道11円・呼値5pt。全要求+1価格時計秒以上の最初正常BBO、新規TTL30秒、新規買Ask/売Bid・返済買Bid/売Ask。同値設定は実同値約定や費用後黒字の保証ではない。追加片道5/10ptは同じ完結往復から100/200円控除する感度で、滑り後の参加を再生したものではない。\n\n"
    limits = "## 解釈の限界\n\n旧21との直接金額差にはM21→M22の参加範囲差も含む。同じM22上のS1/S2、準備で失った機会、共通実新規の出口差と片側参加を分ける。低ADX始動/高ADX失速等は当時の特徴の名前で、真の始動や反転を確認した名称ではない。幅変化は方向を示さずDI一時反転やゼロ近傍のa/b変化も反例となる。\n\n"
    limits += "正常BBO空白300秒超/EOF/未解消を含む全体確定対象額はnullを維持する。最大場内DDは期間最大の一場で累積DDではない。先着やMFEは事後経路であり、実返済後の価格も含む仮保有先着を実利益としない。全65既使用の追加開発で、照合合格は将来の有効性/収益性を証明しない。\n\n"
    threshold_table = "## 全固定条件の要約\n"+G.table(["項目", "固定値"], [[k, G.describe(v)] for k, v in config.items()])
    rule_table = "## 全9評価と表示代表\n\n事前Viewerは3分A0/S1/S2の3資源。1/5分を未実行とはせず、全数値は結果JSON/場別CSVへ残す。\n"+G.table(["評価", "候補", "Viewer", "入口支持", "70目標", "費用資格"], [[r["評価ID"], r["候補ID"], "表示" if r["入口"]["時間足分"] == 3 else "work明細・正式集計", "充足" if values[r["候補ID"]]["入口支持"] else "未達", "達成" if values[r["候補ID"]]["70目標"] else "未達", "充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    audit_text, audit_paths = audits(study, readme)
    summary = "# 試行00022：ADXと上位BB幅の変化による局面切替\n\n"+intro+" / ".join(G.link(study/n, readme) for n in ("計画.md", "条件.json", "固定.json", "結果.json"))+" / "+G.link(setting_path, readme)+"\n\n"+conclusion+preparation+timing+logic+protection+comparison(entries, values)+diagnosis(study, readme)+limits+audit_text
    common = settings(rules)
    method_ids, scale_ids = {m["id"] for m in catalog["methods"]}, {s["id"] for s in catalog["scales"]}
    if any(set(s["手法ID"])-method_ids or set(s["尺度ID"])-scale_ids for s in common):
        raise ValueError("設定が51×9へ対応しない")
    mapping = "# 試行00022：設定と結果\n\n"+intro+conclusion+G.link(G.MASTER, setting_path, "コピー元の汎用表")+" / "+G.link(readme, setting_path)+" / "+G.link(study/"結果.json", setting_path, "全9数値の正本")+"\n\n## 手法×時間スケール\n\n51手法×9尺度。Sは旧発動/新共通M22/上位判別/執行、R01〜R09は複合評価で指標単独の成績ではない。MACD内部EMAを別の方向gateと数えず、DX診断を独立の票へ増やさない。30分間引きは30分足ではない。\n\n"+G.matrix(catalog, setting_path, common)
    mapping += "## 設定明細\n"+G.table(["設定", "手法/尺度", "短記", "条件と役割", "適用評価"], [[s["設定ID"], "/".join(s["手法ID"])+"・"+"/".join(s["尺度ID"]), s["短記"], s["説明"], "・".join(s["適用評価"])] for s in common])+threshold_table+preparation+timing+logic+protection+rule_table+limits+audits(study, setting_path)[0]
    files = ("入力台帳.json", "一覧.resources.json", "固定候補_取引.csv", "固定候補_注文.csv", "全候補_場別.csv", "入口品質.json", "局面品質.json", "入力品質.json", "作業成果物.json")
    viewing = "## 閲覧と再現\n\n"+" / ".join(G.link(study/n, readme) for n in files if (study/n).exists())+"\n\nViewer market_pathは設定の市場root基準、pnl_pathはpath_base=catalogの一覧親基準。3分3運用の追加滑り0ptを表示し、原板は複製しない。大きな全raw/context/局面/入口/運用/追尾はGit外work、正式では展開内容SHAを正本へ記録する。\n\n"
    names = ("指標.py", "入口.py", "運用.py", "検証.py", "合成検証.py", "レポート.py", "独立監査.py", "状態独立確認.py", "追尾独立確認.py", "対応診断.py")
    sources = [ROOT/"scripts/局面変化"/n for n in names if (ROOT/"scripts/局面変化"/n).exists()]
    docs = [ROOT/"docs/議論"/n for n in ("異種指標の発動と局面切替を比較する.md", "ADXと上位BB幅で始動と失速を分ける.md")]
    viewing += "コード："+" / ".join(G.link(p, readme) for p in sources)+"。旧発動と保護："+G.link(ROOT/"study/00021_BBとMACDとストキャスの発動切替/README.md", readme)+"。背景："+" / ".join(G.link(p, readme) for p in docs)+"。\n\n"
    fence = chr(96)*3
    viewing += "保存結果の再表示：\n\n"+fence+"powershell\npython -X utf8 scripts/局面変化/レポート.py\n"+fence+"\n\n数値再生は検証.pyへ別の保存先/作業先を指定する。合成検証.py --finalは固定後変更を拒否し、追加検査は別ファイルへ保存する。\n\n"
    paths = [Path(__file__), DISPLAY, ROOT/"scripts/レポート/設定結果レポート.py", G.MASTER, G.CATALOG,
        *[study/n for n in ("計画.md", "条件.json", "固定.json", "結果.json", *files) if (study/n).exists()], manifest_path, *audit_paths, *sources, *docs,
        ROOT/"study/00021_BBとMACDとストキャスの発動切替/条件.json", ROOT/"study/00021_BBとMACDとストキャスの発動切替/入口内他戦略表示差.json"]
    for path, text in ((readme, summary+viewing), (setting_path, mapping)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)), path), encoding="utf-8")
    return [readme, setting_path]


def main() -> None:
    """完成通知後の保存結果から要約と必須設定表を生成する。

    引数: なし。--study/--outputは任意の試行/文書先。
    返り値: None。入力/ラベル/損益の再計算はしない。
    """
    parser = argparse.ArgumentParser(description="ADXと上位幅の局面改訂の保存帳票")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print("\n".join(str(p) for p in run(args.study, args.output or args.study)))


if __name__ == "__main__":
    main()
