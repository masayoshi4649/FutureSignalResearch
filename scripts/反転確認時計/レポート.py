"""00026の保存結果から三運用の比較と必須51×9表だけを生成する。"""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00026_反転のSAR確認時刻と順行持続"
DISPLAY = ROOT / "scripts/局面変化/レポート.py"
POLICIES = ("N0", "N1", "N2")
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = {"学習": "学習40場", "条件選択": "条件選択24場", "後続検査": "既使用11/4デイ1場"}


def display_helper() -> Any:
    """既存の汎用表と保存集計の表示補助だけを読み込む。

    引数: なし。
    返り値: Any は表示モジュール。市場の先着や損益は再計算しない。
    """
    spec = importlib.util.spec_from_file_location("反転確認時計帳票の固定22表示", DISPLAY)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


H = display_helper()
P, G, number = H.P, H.G, H.number


def definitions(config: dict) -> list[dict]:
    """3分N0/N1/N2と共通X0の三評価を定義する。

    引数: config (dict) は固定条件。
    返り値: list[dict] は三入口と三運用の対応。
    """
    if config["時間足分"] != [3] or config["戦略"] != list(POLICIES) or config["出口"] != [{"出口ID": "X0"}]:
        raise ValueError("3分N0/N1/N2・共通X0と異なる")
    if config["終値切替"] != {"チャネル足分": 30, "チャネル本数": 6, "ε_ATR倍率": .25, "内復帰上限本数": 6, "外回復上限本数": 3}:
        raise ValueError("固定チャネルと6/3寿命と異なる")
    if any(config["SAR"][k] != v for k, v in {"初期AF": .02, "増分AF": .02, "上限AF": .2, "時間足分": 3, "比較本数": 2, "出口使用": False}.items()):
        raise ValueError("固定SARの数値条件と異なる")
    rows = []
    for policy in POLICIES:
        source = {"入口ID": "3分_" + policy, "戦略": policy, "時間足分": 3,
                  "名称": policy, "役割": "混合", "複合本命": True}
        rows.append({"候補ID": source["入口ID"] + "_X0", "入口": source,
                     "出口": {"出口ID": "X0"}, "評価ID": "R" + str(len(rows) + 1).zfill(2)})
    return rows


def validate(config: dict, report: dict, rules: list[dict]) -> tuple[dict, dict]:
    """三案の分母・費用感度・支持・品質nullを保存値から検算する。

    引数: config/report (dict) は条件/結果、rules (list[dict]) は三案の定義。
    返り値: tuple[dict,dict] は入口と運用のID別正本。
    """
    if report["全65場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性または先着幅が不一致")
    entries = {row["入口ID"]: row for row in report["入口評価"]}
    values = {row["候補ID"]: row for row in report["結果"]}
    if len(entries) != 3 or len(report["入口評価"]) != 3 or len(values) != 3 or len(report["結果"]) != 3:
        raise ValueError("全三入口/三運用と異なる")
    if set(entries) != {r["入口"]["入口ID"] for r in rules} or set(values) != {r["候補ID"] for r in rules}:
        raise ValueError("保存ID集合が不一致")
    for rule in rules:
        entry, value = entries[rule["入口"]["入口ID"]], values[rule["候補ID"]]
        if any(entry[k] != v for k, v in rule["入口"].items()) or value["入口"] != rule["入口"] or value["出口"] != rule["出口"]:
            raise ValueError("三案の定義が不一致")
        for period, sessions in zip(PERIODS, (40, 24, 1)):
            P.validate_entry(entry[period])
            item = value[period]["運用"]
            n = item["完結取引数"]
            if value[period]["入口"] != entry[period] or item["入力場数"] != sessions:
                raise ValueError("入口分母または入力場数が不一致")
            if item["活動場数"] + item["無取引場数"] != sessions or item["買い取引数"] + item["売り取引数"] != n or sum(item["役割別完結数"].values()) != n:
                raise ValueError("活動/方向/役割の会計が不一致")
            if not 0 <= item["起動後純赤字取引数"] <= item["追尾起動取引数"] <= n:
                raise ValueError("追尾起動と赤字数が不一致")
            for slip in (0, 5, 10):
                net, average = item[f"追加{slip}pt純損益円"], item[f"追加{slip}pt平均円"]
                if not math.isclose(net, item["追加0pt純損益円"] - 20 * slip * n, abs_tol=1e-8):
                    raise ValueError("費用感度が不一致")
                if (average is None) != (n == 0) or n and not math.isclose(average, net / n, abs_tol=1e-8):
                    raise ValueError("平均額が不一致")
                if item["品質注意場数"] and item[f"追加{slip}pt確定対象円"] is not None:
                    raise ValueError("品質注意を含む全体が確定額になっている")
        support = all(all(entry[p][k] >= limit for k, limit in limits.items()) for p, limits in config["入口支持"].items())
        goal = support and all(entry[p]["確認率"] >= config["目標確認率"] and entry[p]["30分間引き_約定候補数"] >= config["間引き必要件数"][p]
                               and entry[p]["30分間引き_確認率"] >= config["目標確認率"] for p in PERIODS[:2])
        qualified = all(all(value[p]["運用"][k] >= limit for k, limit in limits.items()) and value[p]["運用"]["品質注意場数"] == 0
                        and value[p]["運用"]["追加5pt純損益円"] > 0 for p, limits in config["費用支持"].items())
        if (entry["入口支持"], entry["70目標"], value["費用資格"]) != (support, bool(goal), bool(qualified)):
            raise ValueError("支持/70目標/費用資格が不一致")
    if report["表示固定ID"] != [rule["候補ID"] for rule in rules]:
        raise ValueError("事前N0/N1/N2表示と異なる")
    if report["入口70目標達成数"] != sum(row["70目標"] for row in entries.values()) or report["費用資格数"] != sum(row["費用資格"] for row in values.values()):
        raise ValueError("目標件数が不一致")
    return entries, values


def previous_display() -> Any:
    """固定25の保存値の表示補助だけを読み込む。

    引数: なし。
    返り値: Any は表示モジュール。先着・損益・入口は再生しない。
    """
    path=ROOT/"scripts/SAR持続/レポート.py"
    spec=importlib.util.spec_from_file_location("反転確認帳票の固定25表示",path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=value
    spec.loader.exec_module(value)
    return value


D=previous_display()


def settings(rules: list[dict]) -> list[dict]:
    """共通M・三つの反転時計・共有順行を51×9へ対応させる。

    引数: rules (list[dict]) は三評価。
    返り値: list[dict] は設定IDと適用評価。M26を全三案に明記する。
    """
    n0,n1,n2=[rules[0]],[rules[1]],[rules[2]]
    groups=[
        (["I03","I09"],["m03"],rules,"M24：同場公開現前C/H有限・現ATR正","15公開pair・固定30出典・遅延<=30、時間条件別。N1/N2でもH準備を同じにし、下位BB/K/RSI/VWAP/量をgateへ足さない"),
        (["I10"],["m03"],rules,"共通M26=M25：現前公開SAR有効","全三案に同じ数値準備。方向が実sideかは別の値条件。固定25のSAR数式/銀行をalias再用"),
        (["I03","P04"],["m03"],n0,"N0反転：最初fで実sideδH>0","H=MACD−Signal、12/26/9・EMA算術seed。Rの時計はfのみ、後続hは対象外"),
        (["I10","P04"],["m03"],n1,"N1反転：最初fで現公開SAR=r","前SARの方向持続もδH符号も不要。M26/時間は共通、f不成立後は反転を取り直さない"),
        (["I10","P03","P04"],["m03"],n2,"N2反転：f即時又は次1..3の初現公開SARr","f同時は元frawの全N採否で別hなし。後続hはend/keystrict、元端等号でも初r消費しstrict帯内不可で不採用、再試行禁止"),
        (["I10","P07"],["m03"],rules,"共有T：gの前現SAR方向が共にs","T純条件は固定25Q1と同じ。h後もg監視を継続、実建玉/待機でT実参加が変わる"),
        (["I05","I08","C07"],["m15"],rules,"15分の現前公開pairは数値準備のみ","ADX/DI/BB幅の値選別は三案に使わない。旧E1のADX非上昇を反転条件へ残さない"),
        (["P02","P03","P06","P07","C07"],["m30"],rules,"前公開3分pまでの完全公開30分6本R/L","end/key両上限。R/L/出典は登録bで固定、同限月carry/欠枠resetは固定25。後続で最新窓へ置換しない"),
        (["P01","P03","P04","P07","I09"],["m03"],rules,"価格b→f次1..6→g次1..3を固定25再用","bは価格＋ε=max5,ceil(.25ATR_b/5)*5・時間だけ。元端等号待機/反対端等号取消、初f/g消費は数値や採否と別"),
        (["V01"],["m03"],rules,"観測差分量/RVOLは診断のみ","欠測/0/値でM/状態/全N採否を変えない。全約定量/攻撃側flow/OIではない。量選別効果は未検証"),
        (["B01"],["tick"],rules,"一建玉・新規/返済+1価格秒・TTL30","ラージBBOをmicro1枚代理。買Ask/売Bid新規・返済側BBO。SAR/h/Tによる自動ドテンなし"),
        (["I09","C06","E02"],["tick"],rules,"A5/実入口ATRceil幅・最低新規同値ratchet","hard125/TP250/期限。hは現在hATRをfill固定しf/bATRへ遡及しない。返済pending中追尾停止、役割fill固定、SAR線は出口不使用"),
        (["E01"],["tick"],rules,"各新規125逆行前250先着・hは新時計価格","時間/遅延不可は対象外＋通常9数値None。strict帯内不可hでもtime/delay可なら原先着診断可。f/hを補数や同じ新規へ読み替えない"),
    ]
    return [{"設定ID":f"S{i:02d}","手法ID":methods,"尺度ID":scales,"短記":short,"説明":detail,
             "結果短記":"・".join(r["評価ID"] for r in applies),"適用評価":[r["評価ID"] for r in applies]}
            for i,(methods,scales,applies,short,detail) in enumerate(groups,1)]


def comparison(entries: dict,values: dict) -> str:
    """三案の保存先着・費用・支持を共通表示する。

    引数: entries/values (dict) は保存正本。
    返り値: str は三期間の比較表。実新規集合差と出口差は別節へ残す。
    """
    return D.comparison(entries,values).replace("二運用の結果","三運用の結果").replace("Q0/Q1の方式変更","N0/N1/N2の確認条件と時計の変更")


def audits(study: Path,output: Path) -> tuple[str,list[Path]]:
    """合成と全状態/会計/追尾/対応/三Viewerの明示判定を表示する。

    引数: study/output (Path) は正式試行/表示先。
    返り値: tuple[str,list[Path]] は合否表と出典。検算を独立標本へ合算しない。
    """
    text,paths=D.audits(study,output)
    proof=study/"合成検証.json"
    count=G.read_json(proof)["検証件数"] if proof.exists() else 27
    return (text.replace("最終30",f"最終{count}").replace("30合成",f"{count}合成").replace("全二集合","全三集合/h確認監視")
            .replace("SAR準備/方向置換/episode/参加と回収","f/h確認時計/episode/参加と回収").replace("Q0/Q1","N0/N1/N2")),paths


def stages(study: Path) -> str:
    """価格f/gと反転確認hを保存品質から別に表示する。

    引数: study (Path) は正式試行。
    返り値: str は三期間の段階と取消理由。採用と一回消費を混ぜない。
    """
    data=G.read_json(study/"入口品質.json")
    keys=("設定数","内復帰価格消費数","外回復価格消費数","反転候補登録数","f即時SAR確認数","後続SAR待機開始数",
          "後続SAR確認消費数","後続確認時点対象外足数","h元端等号不採用数","先着評価対象外数")
    rows,events,reasons=[],[],{p:Counter() for p in PERIODS}
    for period in PERIODS:
        own=[r for r in data if r["期間"] == period]
        rows.append([PERIOD_NAMES[period],*[sum(r[k] for r in own) for k in keys]])
        for r in own:
            reasons[period].update(r["反転監視終了理由別"])
        for family in ("R内復帰","T外回復","R方向確認"):
            local=[s for r in own for s in r["イベント段階"] if s["系統"] == family]
            fields=("原イベント数","先着評価対象数","M26時間通過数","N0採用数","N1採用数","N2採用数")
            events.append([PERIOD_NAMES[period],family,*[sum(r[k] for r in local) for k in fields]])
    text="## 価格と反転確認の段階\n\n原b/f/gは固定25と同じ。fを全て反転候補へ登録し、f現在の公開SARrなら既存fで即時確認、その他は次1〜3足だけ待つ。確認の消費と数値/時間/技術採用を別計数する。\n"
    text+=G.table(["期間","価格b","f","g","f反転登録","f即時確認","後続待機","後続h消費","時点対象外足","h等号不採用","先着対象外event"],rows)
    text+=G.table(["期間","系統","原event","先着対象","M26時間","N0","N1","N2"],events)
    text+="### 反転監視の終了理由\n\ng/親失効/反対端/期限・寿命を先に処理し、後続時点対象外は寿命のみ進める。最初SARrはM/時間/保有不可でも消費する。元端等号のhを後足へ取り直さない。\n"
    all_reasons=sorted({r for c in reasons.values() for r in c})
    return text+G.table(["理由",*[PERIOD_NAMES[p] for p in PERIODS]],[[r,*[reasons[p][r] for p in PERIODS]] for r in all_reasons])


def diagnosis(study: Path,output: Path) -> str:
    """同fの値条件と後続hの新時計を、実参加/回収から分ける。

    引数: study/output (Path) は正式試行/表示先。
    返り値: str は対応診断の小集計。全episode/約定を転記しない。
    """
    path=study/"対応診断.json"
    text="## 同時点の選別・確認待機・実回収\n\nN0/N1は同じfでの値条件差、N2後続hは新しい時計と価格からの判断。fの逆行率をhの勝率の補数へ裏返さず、同じ実新規の出口差と混同しない。\n\n"
    if not path.exists():
        return text+"対応診断は未完・未保存。正式完了後に反映する。\n\n"
    data=G.read_json(path)
    if data["対応集合全件一致"] is not True or data["結果SHA256"] != G.sha(study/"結果.json"):
        raise ValueError("対応診断の明示合否/結果SHA不一致")
    text+=G.link(path,output)+"：全件一致・"+number(data["照合項目数"])+"項目。固定25の全f/g出典/原先着、同fのN0と旧Q0、共有Tと旧Q1を照合。N1原採用はN2へ含まれ、f上のN1/N2採否は同じ。\n\n"
    rows=[]
    for r in data["役割別値と時計"]:
        if r["期間"] not in PERIODS[:2]:
            continue
        rates=[f"{r[p]['順行先着']}/{r[p]['約定候補数']}・{G.pct(r[p]['確認率'])}" for p in POLICIES]
        rows.append([PERIOD_NAMES[r["期間"]],r["系統"],r["全原イベント"]["候補数"],r["全原イベント"]["対象外数"],r["M26時間通過"]["候補数"],*rates])
    text+="### 系統別の原イベントと採用\n"+G.table(["期間","系統","原event","先着対象外","M26時間","N0順/仮約定・率","N1順/仮約定・率","N2順/仮約定・率"],rows)
    text+="### 純採用集合\n\n共通/片側だけは原event単位で、N2後続hを元fと同じ新規へまとめない。T純条件が同じでもRの保有による実参加は変わる。\n"
    text+=G.table(["期間","左→右","共通原採用","左のみ","右のみ"],[[PERIOD_NAMES[r["期間"]],r["左"]+"→"+r["右"],r["共通原採用数"],r["左のみ原採用数"],r["右のみ原採用数"]] for r in data["原発動参加集合"] if r["期間"] in PERIODS[:2]])
    text+="### 同episodeのfとhの待機・新規価格\n\n両仮新規を比較できた条件付き対応。fの技術採用や実注文を仮定せず、確認されたepisodeだけで待てば改善する因果効果とはしない。方向化価格差の正はhまで反転方向へ進行した価格で、hはその進行後に新規する。f/hの125/250は各新価格起点。\n"
    text+=G.table(["期間","集合","後続h","両先着対象","両仮新規可","待機分中央値","反転方向進行pt中央値","対応f順/仮約定","対応h順/仮約定"],[
        [PERIOD_NAMES[r["期間"]],r["集合"],r["後続h数"],r["両先着対象数"],r["両仮新規比較可数"],number(r["要求待機分"]["中央値"]),number(r["仮新規進行pt"]["中央値"]),
         f"{r['対応fの先着']['順行先着']}/{r['対応fの先着']['約定候補数']}",f"{r['対応hの先着']['順行先着']}/{r['対応hの先着']['約定候補数']}"] for r in data["待機要約"] if r["期間"] in PERIODS[:2]])
    text+="待機分の中央値はその行の全h、価格差と対応先着は両仮新規比較可の群だけから計算する。母数を揃えず二つの中央値を同一取引の変化とは読まない。\n\n"
    late=[]
    for r in data["待機要約"]:
        if r["期間"] not in PERIODS[:2] or r["集合"] != "N2採用h":
            continue
        a,b=r["対応fの先着"],r["対応hの先着"]
        late.append(f"{PERIOD_NAMES[r['期間']]}の比較可{r['両仮新規比較可数']}件でfの{a['順行先着']}/{a['約定候補数']}→hの{b['順行先着']}/{b['約定候補数']}、反転方向の価格進行中央値{number(r['仮新規進行pt']['中央値'])}pt")
    text+="今回のN2採用hでは"+"、".join(late)+"。確認待ちで参加を追加できても、この対応群の先着品質が改善したという結果ではない。待機中に有利な方向へ価格が動いた部分を、新規後に回収した利益へ加えない。\n\n"
    text+="### N0のfとN2のhへ両方実参加した対応\n\n以下は後にhが成立し両案とも実参加したことで事後に選ばれた群。f時点で実装可能な新しい選別戦略の収益でも、同じ実新規の出口比較でもない。上の全後続h、N2採用h、N0fかつN2h原採用から、さらに実参加へ絞った別分母。\n"
    text+=G.table(["期間","原両採用","両実新規","待機分中央値","実新規の反転方向進行pt中央値","f順/仮約定","h順/仮約定","f基準観測円","h基準観測円","f追加5pt円","h追加5pt円"],[
        [PERIOD_NAMES[r["期間"]],r["原両採用数"],r["両実新規対応数"],number(r["要求待機分"]["中央値"]),number(r["実新規進行pt"]["中央値"]),
         f"{r['f先着']['順行先着']}/{r['f先着']['約定候補数']}",f"{r['h先着']['順行先着']}/{r['h先着']['約定候補数']}",number(r["f基準純額円"]),number(r["h基準純額円"]),number(r["f追加5pt純額円"]),number(r["h追加5pt純額円"])] for r in data["N0fとN2hの実対応"] if r["期間"] in PERIODS[:2]])
    text+="f側の少数の基準黒字を、未来のh成立を知らずに選べた収益へ読み替えない。確認待機で時計と価格が変わった観測を、実装可能な前提条件を考える材料へ限定する。\n\n"
    text+="### 役割別の実回収\n\nR/T構成比と役割内の額を分ける。仮250先着には実返済後の経路も含み、実保有中250ptの含み益を失った件数とはしない。\n"
    text+=G.table(["候補","期間","役割","完結","基準観測円","追加5pt観測円","追加5pt平均円","対応仮250","仮250だが純赤字","仮250だがTP以外"],[
        [r["候補ID"],PERIOD_NAMES[r["期間"]],r["役割"],r["実新規対応数"],number(r["基準純額円"]),number(r["追加5pt純額円"]),
         number(r["追加5pt純額円"]/r["実新規対応数"] if r["実新規対応数"] else None),r["対応先着250数"],r["先着250だが基準純赤字数"],r["先着250だが250利確以外数"]] for r in data["入口先着と利益回収"] if r["期間"] in PERIODS[:2]])
    text+="### 共通実新規の出口差と参加集合差\n\n右−左の全観測純額差＝共通実新規の出口差＋右のみ額−左のみ額。f/hで時点/価格/ATRが違う対応はこの共通出口差へ入れない。\n"
    rows=[]
    for r in data["運用対応"]:
        if r["期間"] not in PERIODS[:2]:
            continue
        pair=r["運用比較"]
        delta=pair["右側のみ純額円"]-pair["左側のみ純額円"]
        if not math.isclose(pair["全運用純額差円"],pair["共通実新規純額差円"]+delta,abs_tol=1e-8):
            raise ValueError("共通出口/参加差と全額差不一致")
        rows.append([PERIOD_NAMES[r["期間"]],r["左"]+"→"+r["右"],f"{pair['共通実新規数']}/{pair['左側のみ実新規数']}/{pair['右側のみ実新規数']}",number(pair["共通実新規純額差円"]),number(delta),number(pair["全運用純額差円"])])
    text+=G.table(["期間","比較","共通/左のみ/右のみ実新規","共通出口差円","参加集合差円","全観測純額差円"],rows)
    additions=[]
    for r in data["運用対応"]:
        if r["期間"] not in PERIODS[:2] or (r["左"],r["右"]) != ("3分_N1_X0","3分_N2_X0"):
            continue
        pair=r["運用比較"]
        additions.append(f"{PERIOD_NAMES[r['期間']]}の共通{pair['共通実新規数']}件の出口差{number(pair['共通実新規純額差円'])}円、N2だけ{pair['右側のみ実新規数']}件の基準{number(pair['右側のみ純額円'])}円（追加片道5pt後{number(pair['右側のみ純額円']-100*pair['右側のみ実新規数'])}円）")
    text+="N1→N2は"+"、".join(additions)+"。後続hの追加参加による差と共通建玉の利益保護を分け、総額差だけで出口改善としない。\n\n"
    text+="### 同episodeの役割と運用抑止\n\n両役割実参加はR新規→R返済→T新規の順序・非重複を確認し、独立標本へ増幅しない。hやTの発生は既存Rの自動ドテンを意味しない。\n"
    text+=G.table(["候補","期間","Rのみepisode","Tのみepisode","両役割episode","両役割基準観測円"],[
        [r["候補ID"],PERIOD_NAMES[r["期間"]],r["反転のみ実参加episode数"],r["順行のみ実参加episode数"],r["両役割実参加episode数"],number(r["両役割基準純額円"])] for r in data["同episode役割順序"] if r["期間"] in PERIODS[:2]])
    text+=G.table(["候補","期間","役割","入口取扱","完結"],[[r["候補ID"],PERIOD_NAMES[r["期間"]],r["役割"],G.describe(r["運用入口取扱"]),r["実完結数"]] for r in data["役割別運用抑止"] if r["期間"] in PERIODS[:2]])
    text+="### 利益保護の設定と実約定\n\n同値未満/最終線不足は追尾起動後の取引だけ。設定の最低同値は費用後非赤字や線上の約定を保証しない。\n"
    text+=G.table(["候補","期間","起動","起動後純赤字","同値未満約定","最終線未満約定","最終線から不足pt計"],[[r["候補ID"],PERIOD_NAMES[r["期間"]],r["追尾起動数"],r["起動後純赤字数"],r["起動後同値未満約定数"],r["最終設定未満約定数"],number(r["最終設定からの不足pt計"])] for r in data["利益保護"] if r["期間"] in PERIODS[:2]])
    return text


def explanation() -> tuple[str,str,str,str]:
    """三案の役割・新hの時点・固定保護と限界を説明する。

    引数: なし。
    返り値: tuple[str,str,str,str] は準備/状態/執行/限界。正式価格再生をしない。
    """
    structure="## 複数手法の役割と共通M26\n\n30分6本の固定高安を価格構造、3分f/gを発動位置とする。RはN0がMACDヒスト差、N1がf現在の公開SAR方向、N2がf又は後続初SAR方向確認を組み合わせる。Tは全三案でg＋公開前足/現足SAR方向持続。同じ持続条件を反転にも一律要求する25Q1とは役割を分ける。\n\n"
    structure+="M26は固定25のM25と同値。現在/前の同場隣接公開3分C/H有限・現在ATR14正、公開15分現前ペア準備、登録時固定30窓有効、確認遅延<=30、現前公開SAR方向±1を全三案に共通とする。方向が実sideかは値条件で、準備へ混ぜない。要求時に新規停止前/期限まで残60分以上の時間条件も別。下位BB/K/RSI/VWAP/量をgateへ加えず、15分ADX/DI/BB幅は数値準備だけ。\n\n"
    structure+="同fのN0採否は旧25Q0と同じ、全Tの純採否は旧25Q1と同じ。ただしN0の全体はこのR/Tを混ぜる新運用で、旧Q0の総損益を再現する案とはしない。SAR数式・同限月carry/欠枠/限月reset・事前/表示/次線・末尾NPの内部更新と公開用途の分離は25をalias再用し変更しない。数値準備だけやATR保護だけを複数入口手法と数えない。\n\n"
    structure+="準備canonicalはatr浮動leafだけをε/Dの呼値整数へ投影し、保存raw/traceのATR実値や売買式は変更しない。独立に全3分足ATRを絶対許容1e−10・相対許容0で照合し、ε/D整数は厳密一致を要求する。許容内の微差でもceil境界を跨ぐ整数差は指紋不一致とする。他の価格/時計/key/採否/SARへこのATR許容を広げず、全浮動値のbyte完全一致とは書かない。\n\n"
    logic="## 反転確認の時計と一度消費\n\nsは元突破方向、r=−sは反転実方向。売りは全て符号反転した同条件。固定25の価格だけのb→初内復帰f→初外回復gを再用する。bのε=max(5,ceil(.25ATR_b/5)*5)、前公開3分pまでにend/key双方で既知の完全公開30分6本R/L/出典を凍結。bは注文でなく、SAR/勢い/確認遅延を登録gateへ入れない。f寿命6・g寿命3、元端等号待機/反対端等号取消も変更しない。\n"
    logic+=G.table(["案/段階","反転R","共通順行T"],[
        ["N0・f即時","M26/時間可＋実rδH>0","g＋M26/時間可＋公開前足SAR方向=現足方向=s"],
        ["N1・f即時","M26/時間可＋現在公開SAR方向=r","同じ純T条件"],
        ["N2・f又は後続h","f現在公開SARrならf即時。それ以外はf次1〜3の初公開SARrをhとして一回消費し、その時計から採否","h後もg判定は継続。同じ純T条件"],
    ])
    logic+="f現在SARrならM/時間/保有不可でも確認を消費する。N2のf即時は既存frawへ全N採否を付け、重複hrawを作らない。N1の原採用はN2に含まれるが、追加のhと保有抑止で実参加集合の単純包含は仮定しない。N1/N2へδH符号やADX低下をさらにANDしない。\n\n"
    logic+="後続hの優先は親価格監視の取消/失効・g先着・反対端・期限→age>3→end/key時点対象外→最初の現在公開SARrを消費→strict帯内/M/時間等の技術採否。後続はend>f.confirmかつ公開keystrict。同足f確認だけ明示許可し、後続の時点対象外は寿命のみ進めて反対端やSAR確認にも使わない。\n\n"
    logic+="元突破買いのC=R/元売りのC=Lでも、eligible初公開SARrならhrawを保存して消費し、strict L<C<R不成立でN2不採用。後の帯内足へ取り直さない。g側へ出た足や反対端は先取消でhrawなし。H/ATR不準備・確認遅延>30・時間/保有不可の初hも消費し、後の条件がよい足へ再試行しない。hのN0/N1は対象外。\n\n"
    logic+="先着対象は時間かつ遅延可だけ。strict帯内不可など技術不採用hでも対象なら原先着診断が可能で、採用caseへは混ぜない。対象外は時間理由優先/次に遅延、ラベル対象外・通常9数値None・evaluate不呼出、未約定へ混ぜない。全三案競合確定後のcase深複写、親trace/反転traceの全N採否同値を確認する。\n\n"
    protection="## 保護・約定・費用・場内完結\n\n固定25のnative通常出口なしA5/X0を再用。hard125/TP250/期限、正常返済BBOの正益5ptで必須追尾、D=max(5,ceil(実入口ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・非緩和・最低新規同値。hの入口ATRはh現在値で、f/bへ遡及しない。返済pending中更新停止、役割fill固定、自動ドテンなし。SAR線やhを通常出口へ使わない。優先は期限/既存待機約定→hard125→TP250→追尾。\n\n"
    protection+="ラージBBOをmicro1枚代理、倍率10円/pt・呼値5pt・片道11円を仮定。新規/返済+1価格時計秒以上の最初正常BBO、新規TTL30、買Ask/売Bid新規・返済側BBO、同原行は気配→確定足→signal。追加片道5/10ptは同じ完結往復から100/200円控除する費用感度で参加経路の再生とは別。価格時計は実受信時計と別。\n\n"
    protection+="デイ原範囲08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50を維持し持ち越さない。同値設定と実約定同値・費用後非赤字は別。正常板空白300秒超/EOF等の注意期の全体確定額はnullで、観測純額や平均を確定収益へ変換しない。\n\n"
    limits="## 限界と知見の扱い\n\n全65場は既使用の追加開発。新たに見つかった場は混ぜず、固定後確認は別試行に分ける。学習40/条件選択24/既使用11/4デイ1の率を未見確認とは呼ばない。支持60/20約定と日場数・30分間引き20/10件・両期70%、費用支持/方向最低数/品質の基準は固定のまま。\n\n"
    limits+="fを反転準備として新たな方向確認まで待つ規則は独自仮説。SARの一般式/往復の弱点はFidelity/TradingView等を参照し、URL/確認日2026-11-05は計画/共通議論に残す。参加者が反転へ移ったという心理は価格加工からの仮説で、注文動機を直接測っていない。資料がこの3足確認やNK225の70%/収益を実証したものではない。SAR数式は独自strict/seed/clamp順の固定25規約で他製品の点と完全一致を仮定しない。\n\n"
    limits+="同episodeのf/h比較は別時計の仮参加で、確認できた群だけの条件付き対応。待機で価格が反転方向へ進めば新規が遅れ、残る250ptが別になる。失効・g先着・f即時・h待機を分け、取引数や総損失の減少だけで入口品質を改善したとはしない。共有Tの純採否同値でもR保有により実参加は変わる。\n\n"
    limits+="仮125/250先着は実返済後も含む。MFEは実保有中の事後峰で全額回収可能とはせず、最大場内DDを期間累積DDとしない。同episodeや共通候補を独立成功票へ増幅しない。未来先着/MFEを当時の切替特徴へ戻さず、条件変更は新試行へ残す。量選別・他手法/尺度は今回未使用で、指標単独の効果は未評価。\n\n"
    return structure,logic,protection,limits


def run(study: Path,output: Path) -> list[Path]:
    """正式完了通知後に保存値から三案の二文書を生成する。

    引数: study/output (Path) は正式試行/表示先。
    返り値: list[Path] はREADME/設定と結果。先着・損益を再生しない。
    """
    for name in ("条件.json","計画.md","固定.json","結果.json","入力台帳.json","入口品質.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存")
    config,report=G.read_json(study/"条件.json"),G.read_json(study/"結果.json")
    rules=definitions(config)
    entries,values=validate(config,report,rules)
    if any(G.sha(ROOT/p) != sha for p,sha in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("固定code/条件/計画/入力SHA変化")
    pointer=G.read_json(study/"入力台帳.json")
    manifest=(study/pointer["参照"]).resolve()
    if G.sha(manifest) != pointer["SHA256"]:
        raise ValueError("入力参照SHA不一致")
    catalog=G.read_json(G.CATALOG)
    if (catalog["version"],len(catalog["methods"]),len(catalog["scales"])) != (1,51,9):
        raise ValueError("版1の51×9表と異なる")
    output.mkdir(parents=True,exist_ok=True)
    readme,mapping=output/"README.md",output/"設定と結果.md"
    intro="NK225の3分N0/N1/N2＝三入口・固定A5/X0の三運用。価格内復帰fでのRを、N0単足MACD、N1現在公開SAR、N2現在公開SARをf又は次1〜3の初hで確認する時計へ分けた。Tは全三案g＋公開前足/現足SAR方向持続。固定25の価格/SAR/準備/保護を再用し、全65場（40/24/既使用11/4デイ1）は既使用の追加開発。\n\n"
    conclusion=f"**支持付き入口70目標は{report['入口70目標達成数']}/3、費用資格は{report['費用資格数']}/3。** 同fの値条件・hの別時計・実参加・共通出口差を分けて判定する。\n\n"
    warnings=[f"{r['候補ID']}の{PERIOD_NAMES[p]}：{r[p]['運用']['品質注意場数']}場" for r in values.values() for p in PERIODS if r[p]["運用"]["品質注意場数"]]
    if warnings:
        conclusion+="品質注意は"+"、".join(warnings)+"。注意期の全体確定額はnullで、以下の額・平均・参加差は観測値。\n\n"
    structure,logic,protection,limits=explanation()
    audit_text,audit_paths=audits(study,readme)
    summary="# 試行00026：反転のSAR確認時刻と順行持続\n\n"+intro+" / ".join(G.link(study/n,readme) for n in ("計画.md","条件.json","固定.json","結果.json"))+" / "+G.link(mapping,readme)+"\n\n"
    summary+=conclusion+structure+logic+protection+stages(study)+comparison(entries,values)+diagnosis(study,readme)+limits+audit_text
    # ----------------------------------------
    # 元の51行9尺度を全て残し、共通準備と各案の条件を設定IDで分離する。
    common=settings(rules)
    ids,scales={r["id"] for r in catalog["methods"]},{r["id"] for r in catalog["scales"]}
    if any(set(r["手法ID"])-ids or set(r["尺度ID"])-scales for r in common):
        raise ValueError("設定が51×9へ対応しない")
    mapped="# 試行00026：設定と結果\n\n"+intro+conclusion+G.link(G.MASTER,mapping,"コピー元汎用表")+" / "+G.link(readme,mapping)+" / "+G.link(study/"結果.json",mapping,"全三評価正本")+"\n\n"
    mapped+="## 手法×時間スケール\n\n版1の51手法×9尺度、S01〜S13は設定、R01〜R03は複合評価。共通M26を全三案へ記録し、N0/N1/N2の値条件/時計は別設定とする。数量は診断だけ、指標単独効果は未検証。30分6本は計算期間で、30分間引きは30分足とは別。\n\n"+G.matrix(catalog,mapping,common)
    mapped+="## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],[[r["設定ID"],"/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]),r["短記"],r["説明"],"・".join(r["適用評価"])] for r in common])
    mapped+="## 全固定条件の要約\n"+G.table(["項目","固定値"],[[k,G.describe(v)] for k,v in config.items()])
    r_rules={"N0":"f即時＋実rδH>0","N1":"f即時＋現公開SARr","N2":"f即時又は次1..3の初現公開SARr、後続hはstrict帯内"}
    mapped+="## 全三運用の定義と合否\n"+G.table(["評価","候補","反転R","共通順行T","両期入口支持","70目標","費用資格"],[[r["評価ID"],r["候補ID"],r_rules[r["入口"]["戦略"]],"g＋公開前現SARs持続","充足" if values[r["候補ID"]]["入口支持"] else "未達","達成" if values[r["候補ID"]]["70目標"] else "未達","充足" if values[r["候補ID"]]["費用資格"] else "未達"] for r in rules])
    mapped+=comparison(entries,values)+structure+logic+protection+limits+audits(study,mapping)[0]
    # ----------------------------------------
    # 全件転記を避け、正本/11gzip台帳/証明/コード/共通知見を内容SHAで参照する。
    files=("入力台帳.json","一覧.resources.json","固定候補_取引.csv","固定候補_注文.csv","全候補_場別.csv","入口品質.json","局面品質.json","30窓品質.json","数量診断品質.json","SAR品質.json","入力品質.json","作業成果物.json")
    sources=[ROOT/"scripts/反転確認時計"/n for n in ("README.md","指標.py","入口.py","運用.py","検証.py","合成検証.py","レポート.py","独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py") if (ROOT/"scripts/反転確認時計"/n).exists()]
    docs=[ROOT/"docs/議論"/n for n in ("SARの方向持続と価格内復帰を比較する.md","反転の方向確認を待つ時計と入口価格.md") if (ROOT/"docs/議論"/n).exists()]
    preparation=[ROOT/"work/反転確認時計/00026"/n for n in ("準備点検.json","独立準備点検.json") if (ROOT/"work/反転確認時計/00026"/n).exists()]
    viewing="## 閲覧と再現\n\n"+" / ".join(G.link(study/n,readme) for n in files if (study/n).exists())+"\n\nコード："+" / ".join(G.link(p,readme) for p in sources)+"。背景："+" / ".join(G.link(p,readme) for p in docs)+"。\n\n"
    viewing+="ラベル/損益なし固定前準備："+" / ".join(G.link(p,readme) for p in preparation)+"。検算数を収益標本に加えない。\n\nViewerは事前三案、market_pathは設定data_root/pnl_pathはcatalog基準。原板/画像/全件MDを複製せず、Git外workの11gzip（旧10＋反転監視）と展開内容SHAを作業成果物へ残す。\n\n"
    fence=chr(96)*3
    viewing+="保存結果の再表示：\n\n"+fence+"powershell\npython -X utf8 scripts/反転確認時計/レポート.py\n"+fence+"\n\n検証.pyは既存結果.jsonの上書きを拒否。数値再生はコードREADMEの別保存先手順へ従う。--prepareはラベル/損益を計算しない件数点検。固定後の合成追加は別名へ分離する。新しい予約場は当試行へ混ぜない。\n\n"
    paths=[Path(__file__),DISPLAY,ROOT/"scripts/SAR持続/レポート.py",ROOT/"scripts/終値切替/レポート.py",ROOT/"scripts/レポート/設定結果レポート.py",G.MASTER,G.CATALOG,manifest,
           *[study/n for n in ("計画.md","条件.json","固定.json","結果.json",*files) if (study/n).exists()],*audit_paths,*sources,*docs,*preparation]
    for path,text in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """保存帳票の表示先を指定して二文書を生成する。

    引数: なし。--study/--outputは正式試行/表示先。
    返り値: None。主再生/先着/損益の再計算はしない。
    """
    parser=argparse.ArgumentParser(description="反転SAR確認時計の保存帳票")
    parser.add_argument("--study",type=Path,default=STUDY)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    print("\n".join(str(p) for p in run(args.study,args.output or args.study)))


if __name__ == "__main__":
    main()

