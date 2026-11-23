"""31の保存値を、CCI現前と上位BB準備・値選別に分けて表示する。"""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00031_CCI持続と上位BB幅"
WORK = ROOT / "work/CCI突破/00031"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS, ("学習40場", "条件選択24場", "既使用11/4Day/Night2場")))
POLICIES = ("C0", "C1")
COMMON = ROOT/"docs/議論/CCI順行へ上位BB幅を加えた比較.md"


def helper() -> Any:
    """前試行のMarkdown表示と保存分母検算だけを読み込む。

    引数: なし。
    返り値: Anyは表示補助。入口/先着/運用を再生しない。
    """
    spec = importlib.util.spec_from_file_location("CCI帳票の保存表示", ROOT / "scripts/一目基準線/レポート.py")
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value

F = helper()
G, P, number = F.G, F.P, F.number


def version2() -> Any:
    """版1を変更しない版2カタログの読取・描画APIを取得する。

    引数: なし。
    返り値: Anyは52手法×9尺度の独立生成モジュール。旧globalは書き換えない。
    """
    spec=importlib.util.spec_from_file_location("CCI帳票の独立カタログ版2",ROOT/"scripts/レポート/カタログ版2.py")
    value=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=value
    spec.loader.exec_module(value)
    return value


V2=version2()


def definitions(config: dict) -> list[dict]:
    """事前固定した全順行二案を表示評価へ対応させる。

    引数: config(dict)は条件正本。
    返り値: list[dict]は二入口/二運用の定義。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("3分C0/C1・固定X0の二案と異なる")
    return [{"評価ID": f"R{i:02d}", "候補ID": f"3分_{p}_X0", "入口": {"入口ID": "3分_" + p,
             "戦略": p, "時間足分": 3, "名称": p, "役割": "順行", "複合本命": True}, "出口": {"出口ID": "X0"}}
            for i, p in enumerate(POLICIES, 1)]



def validate(study: Path) -> tuple[dict, dict, list[dict], dict, dict, Path]:
    """固定版/全二集合/40・24・2分母と費用/支持を保存値から検算する。

    引数: study(Path)は正式試行。
    返り値: tuple[dict,dict,list[dict],dict,dict,Path]は条件/結果/定義/入口/運用/解決台帳。
    """
    for name in ("計画.md", "条件.json", "固定.json", "結果.json", "入力台帳.json", "入口品質.json", "指標品質.json"):
        if not (study / name).is_file():
            raise ValueError(name + "未保存。正式完了前に実測帳票を生成しない")
    config, report = G.read_json(study / "条件.json"), G.read_json(study / "結果.json")
    if report["全66場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性/先着幅が不一致")
    rules = definitions(config)
    entries, values = {r["入口ID"]: r for r in report["入口評価"]}, {r["候補ID"]: r for r in report["結果"]}
    if len(entries) != 2 or len(values) != 2 or len(report["入口評価"]) != 2 or len(report["結果"]) != 2:
        raise ValueError("全二案の分母が不一致")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules} or report["表示固定ID"] != [r["候補ID"] for r in rules]:
        raise ValueError("事前二案の集合が不一致")
    for rule in rules:
        entry, row = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or row["入口"] != rule["入口"] or row["出口"] != rule["出口"]:
            raise ValueError("二案の役割/定義が不一致")
        for period, count in zip(PERIODS, (40, 24, 2)):
            P.validate_entry(entry[period])
            op = row[period]["運用"]
            n = op["完結取引数"]
            if row[period]["入口"] != entry[period] or op["入力場数"] != count or op["活動場数"] + op["無取引場数"] != count:
                raise ValueError("入口/活動/入力の期間分母が不一致")
            if op["買い取引数"] + op["売り取引数"] != n or op["役割別完結数"].get("順行", 0) != n:
                raise ValueError("方向/順行役割の会計が不一致")
            if not 0 <= op["起動後純赤字取引数"] <= op["追尾起動取引数"] <= n:
                raise ValueError("追尾の起動分母が不一致")
            for slip in (0, 5, 10):
                net, average = op[f"追加{slip}pt純損益円"], op[f"追加{slip}pt平均円"]
                if not math.isclose(net, op["追加0pt純損益円"]-20*slip*n, abs_tol=1e-8):
                    raise ValueError("費用感度の保存値が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net/n, abs_tol=1e-8):
                    raise ValueError("平均額の分母が不一致")
                if op["品質注意場数"] and op[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("注意込み観測額を確定対象へ変換しない")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p] and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(row[p]["運用"][k] >= limit for k, limit in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], row["入口支持"], entry["70目標"], row["70目標"], row["費用資格"]) != (support, support, bool(goal), bool(goal), qualified):
            raise ValueError("支持/70/費用資格が不一致")
    if report["入口70目標達成数"] != sum(r["70目標"] for r in values.values()) or report["費用資格数"] != sum(r["費用資格"] for r in values.values()):
        raise ValueError("目標件数が不一致")
    pins = G.read_json(study / "固定.json")["ファイルSHA256"]
    if any(G.sha(ROOT / name) != digest for name, digest in pins.items()):
        raise ValueError("固定版が変更")
    pointer = G.read_json(study / "入力台帳.json")
    manifest_path = (study / pointer["参照"]).resolve()
    if manifest_path != ROOT / "study/00028_基準線復帰と上位一目の方向/入力台帳.json" or G.sha(manifest_path) != pointer["SHA256"]:
        raise ValueError("固定28の入力台帳参照が不一致")
    manifest = G.read_json(manifest_path)
    if len(manifest["entries"]) != 66 or len({r["session"] for r in manifest["entries"]}) != 66:
        raise ValueError("既使用66場の分母が不一致")
    return config, report, rules, entries, values, manifest_path



def comparison(entries: dict, values: dict) -> str:
    """共通保存形式の二案・三期間を既存の表示だけで整形する。

    引数: entries/values(dict)は入口/運用正本。
    返り値: strは仮先着/実参加/費用/支持の小表。
    """
    return F.comparison(entries, values).replace("三運用", "二運用")


def settings(rules: list[dict]) -> list[dict]:
    """CCI/上位BBの準備と値・価格/公開/保護を版2へ分けて記す。

    引数: rules(list[dict])は事前二評価。
    返り値: list[dict]は採用等9設定と診断専用1設定。
    """
    groups=[
        (["P01","P02","P07"],["m03"],rules,"原P：前20高安を現在終値がstrict突破",
         "当場連続公開有効20本の最高H/最安Lを固定し現在足除外。買C>HH/売C<LL、ヒゲ/等号不可。rolling各突破を別rawとし、CCI/上位準備/値/時間/保有と別保存"),
        (["I13"],["m03"],rules,"C0/C1共通：現前CCI20を実sideで100超",
         "元OHLC各float→FractionのTP=(H+L+C)/3、同じ各20窓のμとMD=Σ|TP−μ|/20、係数3/200。現前には当場連続公開21本。MD0は無効、±100等号は不採用、表示floatでなく分子分母strict判定。前/現は非冗長だが独立二票ではない"),
        (["I05"],["m15"],rules,"共通M：当場最新公開BB20現前ペア準備",
         "15分BB20数値窓は同限月carry、母σ・絶対幅4σ。現u/前u−1の当場隣接公開・数値有効を両案へ共通要求。BB0幅も数値準備可、最新不準備を古い正常pairへ戻さない"),
        (["I05"],["m15"],rules[1:],"C1値追加：15分BB絶対幅の厳密拡大",
         "元20CのFraction母分散現前差>0。価格割りの相対幅でなく、差の分子分母は分散差。数学等幅0はM可/値不成立、縮小も見送る。3分BB/PSY等は足さない"),
        (["I09"],["m03"],rules,"共通M：ATR14有限正・入口D固定",
         "固定26Wilderの絶対価格数値。3分ATRは同限月carryし、欠枠/不正/尾部/限月でclear。有効missing当足と全幅NPは数値更新のみ。保護のATRだけを複数入口分析と数えない"),
        (["C07"],["m03","m15"],rules,"公開：当場上位隣接・end/key二重asof",
         "u.end<=現3分endかつ(u.confirm,line)<=現3分key、同key/end等号可・同秒後行不可。3分価格/CCIと15分公開pairは局所、missing/NP/不正は当足不投入、番号飛越missing0有効当足は新種可。前場BB数値を当場公開前足へ代用しない"),
        (["B01"],["tick"],rules,"一建玉・新規/返済1価格秒・TTL30秒",
         "ラージBBOでmicro1枚代理、買Ask/売Bid新規・返済側BBO。同原行は気配→確定足→signal、全順行・fill固定、自動ドテンなし。価格時計を実受信待機と同一視しない"),
        (["I09","C06","E02"],["tick"],rules,"固定A5：有利5pt起動・最低新規同値",
         "hard125/TP250/期限、D=max5,ceil(入口ATR/5)*5、保護利益max(0,MFE−D)。買ceil/売floor・非緩和、返済pending中追尾停止。CCI/BBの通常出口は新設しない"),
        (["E01"],["tick"],rules,"125逆行前250順行・支持/費用/実回収は別",
         "原P先着対象は時間AND遅延のみ、対象外9数値None。主率と30分間引き70%・支持・一建玉実参加と費用後回収を分離し、既使用2場を不足支持の代用にしない"),
        (["I13","P05","P07"],["m03"],rules,"診断のみ：CCI現前・突破位置の保持/除外",
         "事前予定の現前条件の重複や、C0純入口をC1保持/除外した要求終値/仮新規の突破距離を記述。価格位置差を後続待機の進行とせず、未来仮約定価格や事後区分を今回のgateへ戻さない"),
    ]
    return [{"設定ID":f"S{index:02d}","手法ID":methods,"尺度ID":scales,"短記":short,"説明":detail,
             "結果短記":"・".join(rule["評価ID"] for rule in applies),"適用評価":[rule["評価ID"] for rule in applies]}
            for index,(methods,scales,applies,short,detail) in enumerate(groups,1)]


def stages(study: Path) -> str:
    """足・原価格発動・共通準備・二案採用を別分母で表示する。

    引数: study(Path)は正式試行。
    返り値: strは3分/15分銀行と原P段階・重複理由の集計表。
    """
    quality,numeric=G.read_json(study/"入口品質.json"),G.read_json(study/"指標品質.json")
    rows=[]
    reasons={period:{policy:Counter() for policy in POLICIES} for period in PERIODS}
    for period in PERIODS:
        own=[row for row in quality if row["期間"]==period]
        rows.append([PERIOD_NAMES[period],len(own),*[sum(row[key] for row in own) for key in
            ("足数","価格20窓準備足数","共通M準備足数","原価格発動数","先着評価対象外数")],
            *[sum(row["戦略別発動数"]["3分_"+policy] for row in own) for policy in POLICIES]])
        for row in own:
            for policy in POLICIES:
                reasons[period][policy].update(row["戦略採否理由別"][policy])
    text="## 原価格発動・共通準備・値追加\n\n全3分足、原P、純入口は別分母。C0にも当場15分BB現前の準備を課し、C1の幅値追加へ準備差を混ぜない。CCI/上位/ATR/時間が不成立でも原Pを消さず、後足へ取り直さない。\n"
    text+=G.table(["期間","入力場","3分足","価格20窓準備足","共通M足","原P","先着対象外P","C0","C1"],rows)
    fields=("入力足数","ATR正準備足数","CCI現前準備足数","BB数値準備足数","数値clear数","CCI局所clear数","非公開数値更新数","尾部完全欠枠")
    text+=G.table(["期間","尺度","足数","ATR正","CCI現前","BB数値","数値clear","局所CCIclear","NP数値更新","尾部欠枠"],
        [[PERIOD_NAMES[period],str(size)+"分",*[sum(row[key] for row in numeric if row["期間"]==period and row["時間足分"]==size) for key in fields]]
         for period in PERIODS for size in (3,15)])
    all_reasons=sorted({key for group in reasons.values() for counts in group.values() for key in counts})
    text+="採否理由は原Pへ重複して付くので、合計を除外総数へ読み替えない。\n"
    return text+G.table(["原Pの採否理由",*[PERIOD_NAMES[period]+"/"+policy for period in PERIODS for policy in POLICIES]],
        [[reason,*[reasons[period][policy][reason] for period in PERIODS for policy in POLICIES]] for reason in all_reasons])



def proof_path(study: Path, work: Path, name: str) -> Path:
    """同値の正式コピー又は作業正本を選ぶ。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは正式優先。版差や未保存は例外。
    """
    return F.proof_path(study, work, name)



def audits(study: Path, work: Path, output: Path) -> tuple[str, list[Path]]:
    """人工/主独立準備/正式六証明の明示合否と対象版を表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: tuple[str,list[Path]]は検査表/出典。検算を収益標本へ加えない。
    """
    groups = [("合成検証.json", "人工突破/精密幅/CCI/非PnL境界"), ("独立監査.json", "全先着/Decimal会計/正式資源"),
              ("状態独立確認.json", "原OHLC/ATR/BB/CCI/精密分散/全採否"), ("追尾独立確認.json", "全保有A5最初要求/気配"),
              ("対応診断.json", "共通準備/上位幅追加/実参加/回収"), ("Viewer照合.json", "事前二運用の代表Viewer")]
    rows, paths = [], []
    for name, title in groups:
        path = proof_path(study, work, name)
        data = G.read_json(path)
        verdict, count = data.get("全件一致", data.get("対応集合全件一致")), data.get("照合項目数")
        if name == "合成検証.json":
            verdict, count = data.get("全件成功") is True and data.get("合成編集終了") is True, data["検証件数"]
            if any(G.sha(ROOT / k) != digest for k, digest in data["ファイルSHA256"].items()):
                raise ValueError("最終合成のpin差")
        elif name == "Viewer照合.json":
            checks = data.get("照合", [])
            verdict, count = len(checks) == 2 and all(r.get("一致") is True for r in checks), len(checks)
        if verdict is not True:
            raise ValueError("明示監査未完:" + name)
        if data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study / "結果.json"):
            raise ValueError("証明の結果版差:" + name)
        if name == "対応診断.json" and data["ファイルSHA256"].get((study / "結果.json").relative_to(ROOT).as_posix()) != G.sha(study / "結果.json"):
            raise ValueError("対応診断の結果pin差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("状態/追尾が正式会計へ未接続")
        rows.append([title, "一致/合格", number(count), G.link(path, output)])
        paths.append(path)
    preparation = proof_path(study, work, "独立準備点検.json")
    independent = G.read_json(preparation)
    main = work / "準備点検.json"
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main):
        raise ValueError("主独立準備の対象版差")
    paths += [main, preparation]
    rows += [["固定前主準備・label/PnLなし", "66場・非損益", 66, G.link(main, output)], ["固定前独立数値/CCI/原P", "一致/合格", number(independent["照合項目数"]), G.link(preparation, output)]]
    ref = G.read_json(study / "準備参照.json")
    resolved = (study / G.read_json(study / "入力台帳.json")["参照"]).resolve()
    locked = G.read_json(study / "固定.json")
    if G.sha(main) != locked["主準備SHA256"] or G.sha(main) != ref["主準備SHA256"] or G.sha(preparation) != locked["独立準備SHA256"]:
        raise ValueError("準備参照/実行前固定と準備SHAの版差")
    if "独立準備SHA256" in ref and G.sha(preparation) != ref["独立準備SHA256"]:
        raise ValueError("準備参照の任意独立SHAが固定版と不一致")
    if independent["条件SHA256"] != G.sha(study / "条件.json") or independent["入力台帳SHA256"] != G.sha(study / "入力台帳.json") or independent["解決入力台帳SHA256"] != G.sha(resolved):
        raise ValueError("独立準備の条件/pointer/台帳bind差")
    if ref["ラベル計算"] is not False or ref["損益計算"] is not False or independent["ラベル計算"] is not False or independent["損益計算"] is not False:
        raise ValueError("準備の非label/PnL証拠が不一致")
    supplement_path = proof_path(study, work, "保存物読取補足.json")
    supplement = G.read_json(supplement_path)
    if supplement["全件一致"] is not True or supplement["不一致"] or supplement["参照SHA256"]["対応診断.json"] != G.sha(proof_path(study, work, "対応診断.json")):
        raise ValueError("保存物読取補足の合否/対象診断版差")
    paths.append(supplement_path)
    rows.append(["保存物の独立読取/全費用分解", "一致/合格", number(supplement["照合項目数"]), G.link(supplement_path, output)])
    text = "## 検査の状態\n\n固定前人工/主独立準備と、正式固定後の状態/先着/会計/全保有追尾/代表Viewerを分ける。ATRのみabs1e−10・rel0、CCI分子分母/TP/同窓MD/BB表示/精密分散/全採否/価格/時点/追尾D整数は厳密。ゲートへεを足さず、検算件数を独立収益標本へ合算しない。\n"
    return text + G.table(["範囲", "明示合否", "件/項目", "正本"], rows), paths


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """上位幅による純入口選別と実参加・価格位置・回収を表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: strは対応診断の小集計。未来値を入口条件へ利用しない。
    """
    path=proof_path(study,work,"対応診断.json")
    data=G.read_json(path)
    result_key=(study/"結果.json").relative_to(ROOT).as_posix()
    if data["全件一致"] is not True or data["ファイルSHA256"].get(result_key)!=G.sha(study/"結果.json"):
        raise ValueError("対応診断の合否/結果pin差")
    text="## 上位幅追加と実参加の対応\n\n"+G.link(path,output)+"を正本とする。CCI現前と価格突破を共通にし、C1が加えた上位幅の選別・同一実新規の出口・片側参加・仮先着と回収を分ける。\n"
    text+=G.table(["期間","原P","原Pの共通M","time/delay先着可","Day/Night原P","C0","C1"],
        [[PERIOD_NAMES[row["期間"]],row["原価格発動数"],row["共通M準備数"],row["先着評価対象数"],
          str(row["DayNight原発動数"]["Day"])+"/"+str(row["DayNight原発動数"]["Night"]),
          row["全案採用数"]["C0"],row["全案採用数"]["C1"]] for row in data["期間別原発動"]])
    supplement=G.read_json(proof_path(study,work,"保存物読取補足.json"))
    text+="### CCI現前の四区分\n\n分母は共通Mと時間/遅延を通過した原Pで、C0純入口や全rawではない。現前とも・現のみ・前のみ・双方不成立を、同じ実方向100超の厳密値で分類した保存shadowの記述比較である。現のみ等を新しい運用候補として再生していない。\n"
    text+=G.table(["期間","CCI区分","要求","250/仮約定・率","125先着","期限/不足/未約定"],
        [[PERIOD_NAMES[row["期間"]],row["CCI区分"],row["候補数"],
          f"{row['順行先着']}/{row['約定候補数']}・{G.pct(row['確認率'])}",row["逆行先着"],
          f"{row['期限未達']}/{row['観測不足']}/{row['未約定']}"] for row in supplement["CCI現前4区分"]])
    text+="この実標本では前のみが0件でも、CCIの恒等的な冗長性を意味しない。現のみと現前ともを比べた前条件の率の改善は学習と選択で揃わず、CCI単独の増分効果や費用後運用の改善を示す比較でもない。閾値や今回の条件へ戻さない。\n\n"
    text+="### C0純入口の保持/除外\n\n分母はC0純入口で、全rawの分割ではない。同じ価格候補を同時点で分類し、共通数値準備による除外を幅の値効果へ足さない。除外群の仮先着を、そのまま実現円の機会損失へ変換しない。\n"
    rows=[]
    for row in data["入口追加比較"]:
        if row["新規追加入口数"]!=0:
            raise ValueError("純C1がC0の部分集合でない")
        for name in ("保持入口","除外入口"):
            entry=row[name]
            rows.append([PERIOD_NAMES[row["期間"]],name,entry["候補数"],
                f"{entry['順行先着']}/{entry['約定候補数']}・{G.pct(entry['確認率'])}",entry["逆行先着"],
                f"{entry['期限未達']}/{entry['観測不足']}/{entry['未約定']}"])
    text+=G.table(["期間","群","要求","250/仮約定・率","125先着","期限/不足/未約定"],rows)
    text+="### 同時点の価格位置\n\nC0純入口の保持/除外を、固定した突破水準から実方向への距離で比べた中央値。要求終値は未約定を含む純C0全件、仮新規はその仮約定だけを分母とする。要求終値は当時の値、仮新規は要求後に決まる値である。保持群の価格差は選別された構成の差であり、C1が後足まで待って進んだ距離ではない。仮新規や事後区分を採否へ戻していない。\n"
    text+=G.table(["期間","群","純入口要求/仮約定","要求終値の突破距離pt中央値","仮新規の突破距離pt中央値"],
        [[PERIOD_NAMES[row["期間"]],"保持" if row["C1保持"] else "除外",str(row["候補数"])+"/"+str(row["約定候補数"]),
          number(row["要求終値の突破距離pt中央値"]),number(row["仮新規の突破距離pt中央値"])] for row in data["保持除外の価格位置"]])
    text+="### 共通実新規の出口と片側参加\n\n純C1はC0の部分集合でも、先行保有を減らすことで基準案が抑止した後続へ入る可能性がある。実新規の同一性で対応し、共通出口差と片側のみの参加差を費用0/5/10で分ける。品質注意期の円は観測値である。\n"
    text+=G.table(["期間","共通実新規","共通出口差0/5/10円","C0のみ完結・0/5/10円","C1のみ完結・0/5/10円","総差0/5/10円"],
        [[PERIOD_NAMES[row["期間"]],row["共通実新規数"],
          "/".join(number(row[f"追加{fee}pt共通出口差円"]) for fee in (0,5,10)),
          str(row["C0のみ"]["完結取引数"])+"・"+"/".join(number(row["C0のみ"][f"追加{fee}pt純損益円"]) for fee in (0,5,10)),
          str(row["C1のみ"]["完結取引数"])+"・"+"/".join(number(row["C1のみ"][f"追加{fee}pt純損益円"]) for fee in (0,5,10)),
          "/".join(number(row[f"追加{fee}pt総額差円"]) for fee in (0,5,10))] for row in data["実参加比較"]])
    text+="### 仮250先着と実保有の回収\n\n仮先着は実返済後も観測する反事実。実保有MFEも全額を回収できた利益とは限らない。追尾起動後赤字は、同値返済の往復手数料と不利価格約定を分ける。\n"
    text+=G.table(["候補","期間","実完結","対応仮250","判定前に返済","実保有MFE250","追尾起動","起動後基準赤字","うち同値費用/不利返済"],
        [[row["候補ID"],PERIOD_NAMES[row["期間"]],row["完結取引数"],row["仮250先着取引数"],
          row["仮250判定前返済数"],row["実保有MFE250取引数"],row["追尾起動数"],row["起動後純赤字数"],
          str(row["同値返済費用赤字数"])+"/"+str(row["不利返済赤字数"])] for row in data["候補別回収"]])
    trades=G.read_csv(study/"固定候補_取引.csv")
    rows=[]
    for period in PERIODS:
        for policy in POLICIES:
            cid="3分_"+policy+"_X0"
            armed=[row for row in trades if row["期間"]==period and row["手法"]==cid and row["追尾起動"]=="True"]
            below=sum((1 if row["方向"]=="買い" else -1)*(float(row["返済価格"])-float(row["新規価格"]))<0 for row in armed)
            line=sum(float(row["最終追尾から実返済方向差pt"])<0 for row in armed)
            rows.append([cid,PERIOD_NAMES[period],len(armed),below,line,
                number(sum(max(0.,-float(row["最終追尾から実返済方向差pt"])) for row in armed))])
    text+="以下の同値未満/最終線不足は追尾起動後の取引に限る。設定床、最終追尾線、実約定、費用後非赤字は別である。\n"
    text+=G.table(["候補","期間","追尾起動","同値未満約定","最終線未満約定","線不足pt計"],rows)
    text+="### 品質注意\n\n価格時計の正常板空白は通信遅延の実測ではない。注意期の全体確定額nullを保持し、注意場の減少をCCIや幅の一般的な品質検知効果としない。\n"
    if data["品質注意の実参加"]:
        text+=G.table(["候補","場","観測場純額円","完結","注意取引","注意取引観測円","保有空白区間","当場最長正常板間隔秒"],
            [[row["候補ID"],row["場"],number(row["観測現金増減円"]),row["完結取引数"],row["観測経路注意取引数"],
              number(row["経路注意取引純損益円"]),row["保有中空白区間数"],number(row["最長正常板間隔秒"])] for row in data["品質注意の実参加"]])
    else:
        text+="今回の保存運用に品質注意の実参加記録はない。\n\n"
    return text


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """正式完了後の保存結果と証明から、版2の二Markdownを生成する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。市場データや主再生を実行しない。
    """
    config,report,rules,entries,values,manifest=validate(study)
    if config["カタログ版"]!=2 or config["CCI手法ID"]!="I13":
        raise ValueError("CCIをI13へ登録したカタログ版2が必要")
    catalog=V2.load_catalog()
    output.mkdir(parents=True,exist_ok=True)
    readme,mapping=output/"README.md",output/"設定と結果.md"
    common=settings(rules)
    intro="NK225・3分の前20高安へのstrict終値突破へ現前CCI20の実方向100超を要求するC0と、さらに当場公開15分BB20絶対幅拡大を要求するC1の二つの順行運用。全案でCCI現前・ATR正・上位BB現前公開ペアの準備、執行、A5を共有する。記録はI13 CCIを追加したカタログ版2・52手法×9尺度。全66場（学習40・条件選択24・既使用11月4日Day/Night2）は既使用の追加開発で、未使用確認ではない。\n\n"
    conclusion=f"**支持付き入口70目標は{report['入口70目標達成数']}/2、費用資格は{report['費用資格数']}/2。** 純入口の先着率、実参加の費用後平均、品質注意と全体確定額を分ける。\n\n"
    left,right=values["3分_C0_X0"],values["3分_C1_X0"]
    if all(row["入口支持"] for row in values.values()):
        conclusion+="両案の入口支持は充足。"
    conclusion+="C0→C1の"
    conclusion+="、".join(PERIOD_NAMES[period]+"は先着率"+G.pct(left[period]["入口"]["確認率"])+"→"+
        G.pct(right[period]["入口"]["確認率"])+"、追加5pt平均"+number(left[period]["運用"]["追加5pt平均円"])+"→"+
        number(right[period]["運用"]["追加5pt平均円"])+"円" for period in PERIODS[:2])+"。\n\n"
    if all(right[period]["入口"]["確認率"]>left[period]["入口"]["確認率"] and
           right[period]["運用"]["追加5pt平均円"]<left[period]["運用"]["追加5pt平均円"] for period in PERIODS[:2]):
        conclusion+="入口率の上昇は両期の費用後平均改善へ結び付かず、採用を減らすだけで利益保護や回収が改善するとは判断しない。\n\n"
    warnings=[row["候補ID"]+"の"+PERIOD_NAMES[period]+"・"+str(row[period]["運用"]["品質注意場数"])+"場"
        for row in values.values() for period in PERIODS if row[period]["運用"]["品質注意場数"]]
    if warnings:
        conclusion+="品質注意は"+"、".join(warnings)+"。該当期の全体確定額はnull、総額・平均・参加差は観測値として表示する。注意が減ったことを一般的な品質検知効果としない。\n\n"
    logic="## 複数手法の役割と厳密境界\n\n原Pは当場の連続公開有効3分20本を固定し、買C>前HH・売C<前LL。現在足を前窓へ含めず、等号/ヒゲだけの突破は不可。rolling各突破を別IDで保存し、M/CCI/上位値/時間/保有で消さない。後足の確認まで待って時計や価格を取り直さない。\n\n"
    logic+="CCIは元H/L/C各floatをFractionへ写しTP=(H+L+C)/3。各20本窓の同じ現在平均μからMD=Σ|TP−μ|/20を求め、(TP現−μ)/((3/200)MD)で規格化する。各足当時の別平均からの偏差を平滑する式ではなく、MD0は無効・0補完なし。現20本と前20本には当場連続公開21足が必要。実方向s=±1として現前ともs×CCI>100を既約分子分母でstrict判定し、±100等号は不採用。表示floatや任意εで境界を変えない。\n\n"
    logic+="現前条件は非冗長である。人工の前20本100×19/110では前CCI=2000/3だが、現H=C=115・L=75なら終値突破しても現CCI=13000/189で100未満。逆に現だけ100超となる例もある。両状態を測る意義と、同じOHLC由来の条件を独立した二票とする主張は別であり、実標本で成功率を保証しない。\n\n"
    logic+="15分BBは終値20本・母σの絶対幅4σで、価格割りの相対幅ではない。数値窓は同限月carryするが、参照u/前u−1は当場の隣接公開足に限る。u.end<=現3分endかつ(u.confirm,line)<=現3分key、同key/end等号可・同秒後行不可。最新公開uが未準備でも古い正常pairへ戻らない。両案へ同じBB現前準備を課し、C1だけ元20CのFraction母分散現前差>0を加える。分子分母は分散差で幅差ではなく、数学等幅0は準備可/値不成立。\n\n"
    logic+="3分価格/CCIと15分公開pairは同場局所。missing>0/NP/不正はclear後当足不投入、番号飛越missing0有効当足は新種可。ATRと15分BB数値だけ同限月carryし、欠枠/不正/尾部/限月で解除、有効missing当足と全幅NPは数値更新だけを行う。前場BB数値を当場公開前足へ昇格させない。原P先着対象は時間AND遅延のみ、Mと値は別。全採否・競合確定後にcaseを深複写し、未来labelを運用signalへ混ぜない。\n\n"
    protection="## 利益保護・執行・費用・場内完結\n\n固定26の一建玉X0/A5を継承し、新出口を作らない。hard125/TP250/期限、正常返済側BBOで有利5ptなら必須追尾。D=max(5,ceil(実入口ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・非緩和・最低新規同値。返済pending中追尾停止、全role順行・fill固定、自動ドテンなし。CCI/BBの通常決済は採用していない。\n\n"
    protection+="ラージBBOでmicro1枚を代理し、10円/pt・呼値5pt・片道11円。新規/返済は要求+1価格秒以上の最初正常BBO、新規TTL30。買Ask/売Bidで新規、返済は逆側BBO、同原行は気配→確定足→signal。同じ完結往復から追加片道5/10ptの100/200円を控除する感度であり、別の注文経路を再生した値ではない。同値設定は実同値約定や費用後非赤字を保証しない。\n\n"
    protection+="デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50。正常板空白300秒超/EOF/未解消の品質を残し、持ち越さない。価格時計は受信時計ではなく、1価格秒待機は実発注遅延の実測ではない。実microの板・約定再現でもない。\n\n"
    limits="## 限界と知見の扱い\n\n価格突破は既知水準の通過、CCIは同窓平均からの偏り、上位BBは方向を持たない変動背景として役割を分けた。追随参加や利確心理は仮説であり、人数・注文量を直接観測したものではない。高CCIが続く可能性はあるが継続を保証せず、CCI/BB/価格は同じ価格系列の加工で独立票ではない。\n\n"
    limits+="この二案で直接比べるのは上位BB幅値の追加。CCIなしの同条件対照を置いておらず、CCI単独の増分効果は未測定。PSY/量/OBV/MACD/一目/RSI/ADX等と他尺度は未使用、ATR準備/保護だけを複数入口分析と数えない。純集合包含と一建玉の実参加包含は別であり、共通出口差と片側参加を対応させる。未来先着・事後MFE・仮新規価格を当時の採否へ戻さず、主要条件変更は別試行にする。既使用2場で不足支持を代用しない。\n\n"
    audit_text,audit_paths=audits(study,work,readme)
    results=comparison(entries,values)
    summary="# 試行00031：CCI持続と上位BB幅\n\n"+intro+" / ".join(G.link(study/name,readme) for name in ("計画.md","条件.json","固定.json","結果.json"))+" / "+G.link(mapping,readme)+"\n\n"
    summary+=conclusion+results+stages(study)+diagnosis(study,work,readme)+logic+protection+limits+audit_text

    # ----------------------------------------
    # 版2の52行9尺度を保持し、未使用・共通準備・値追加・診断を分ける。
    mapped="# 試行00031：設定と結果\n\n"+intro+conclusion+G.link(V2.MASTER,mapping,"コピー元汎用表・版2")+" / "+G.link(readme,mapping)+"\n\n"
    mapped+="## 手法×時間スケール\n\nカタログ版2の52手法×9尺度。旧51ID/定義と9尺度を保ちI13 CCIのみ追加。S01〜S09は採用/準備/執行/保護/評価、S10は診断のみ。R01/R02は複合評価で指標単独の性能ではない。CCIと上位BB準備は共通、上位幅の値はC1だけ。未使用・未検証・データ不足・対象外を区別する。\n\n"
    mapped+=V2.matrix(catalog,mapping,common)
    mapped+="## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],
        [[row["設定ID"],"/".join(row["手法ID"])+"・"+"/".join(row["尺度ID"]),row["短記"],row["説明"],"・".join(row["適用評価"])] for row in common])
    mapped+="## 全固定条件\n"+G.table(["項目","固定値"],[[key,G.describe(value)] for key,value in config.items()])
    mapped+="## 二評価の定義と判定\n"+G.table(["評価","候補","同時点条件","入口支持","70目標","費用資格"],
        [[rule["評価ID"],rule["候補ID"],config["CCI突破"][rule["入口"]["戦略"]],
          "充足" if values[rule["候補ID"]]["入口支持"] else "未達",
          "達成" if values[rule["候補ID"]]["70目標"] else "未達",
          "充足" if values[rule["候補ID"]]["費用資格"] else "未達"] for rule in rules])
    mapped+=results+logic+protection+limits+audits(study,work,mapping)[0]

    # ----------------------------------------
    # 六系列全件や原板を重複せず、正本・Viewer・proof・出典SHAを指す。
    files=("入力台帳.json","準備参照.json","一覧.resources.json","固定候補_取引.csv","固定候補_注文.csv",
        "全候補_場別.csv","入口品質.json","指標品質.json","入力品質.json","作業成果物.json")
    sources=[HERE/name for name in ("README.md","指標.py","入口.py","検証.py","合成検証.py","レポート.py",
        "独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py") if (HERE/name).is_file()]
    docs=[ROOT/name for name in ("docs/technical-analysis/指標/CCI.md","docs/technical-analysis/指標/ボリンジャーバンド.md",
        "docs/議論/テクニカル手法の検証範囲と次の複合候補.md")]
    if COMMON.is_file():
        docs.append(COMMON)
    viewing="## 閲覧と再表示\n\n"+" / ".join(G.link(study/name,readme) for name in files if (study/name).is_file())+"\n\nコード："+" / ".join(G.link(path,readme) for path in sources)+"。\n\n"
    if COMMON.is_file():
        viewing+=G.link(COMMON,readme,"共通知見")+"。\n\n"
    viewing+="同じ66場を小型pointer/SHAで参照し、原板を複製・再抽出しない。六gzipはGit外work・展開内容SHAを作業成果物へ保存。Viewer一覧は事前C0/C1各66場・API代表2資源。market_pathはdata_root、pnl_pathはcatalog基準。--prepareは数値/原P/全採否だけでlabel/PnL/量集約なし。主再生は既存結果/正式中間物を拒否し、固定を上書きしない。再生の詳細はコードREADMEに従う。\n\n"
    viewing+="保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/CCI突破/レポート.py\n```\n\n"
    paths=[Path(__file__),ROOT/"scripts/一目基準線/レポート.py",ROOT/"scripts/反転確認時計/レポート.py",F.F.DISPLAY,
        ROOT/"scripts/SAR持続/レポート.py",ROOT/"scripts/終値切替/レポート.py",ROOT/"scripts/レポート/設定結果レポート.py",
        V2.BASE,V2.CATALOG,ROOT/"scripts/レポート/カタログ版2.py",V2.MASTER,manifest,
        *[study/name for name in ("計画.md","条件.json","固定.json","結果.json",*files) if (study/name).is_file()],
        *audit_paths,*sources,*docs]
    if (work/"診断予定.json").is_file():
        paths.append(work/"診断予定.json")
    for path,text in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """保存値だけを指定先へ再表示する。

    引数: なし。CLIの--study/--work/--outputは正式/作業/表示先。
    返り値: None。先着/運用の再生や数値探索は行わない。
    """
    parser=argparse.ArgumentParser(description="CCI持続と上位BB幅の保存帳票・カタログ版2")
    parser.add_argument("--study",type=Path,default=STUDY)
    parser.add_argument("--work",type=Path,default=WORK)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    print("\n".join(str(path) for path in run(args.study.resolve(),args.work.resolve(),(args.output or args.study).resolve())))


if __name__=="__main__":
    main()



