"""共有二入口の先着と、ATR/公開SARの四運用を保存値だけで表示する。"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
import sys
from typing import Any

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
STUDY=ROOT/"study/00032_最低同値床と公開SAR追尾"
WORK=ROOT/"work/SAR追尾/00032"
OLD_STUDY=ROOT/"study/00031_CCI持続と上位BB幅"
PERIODS=("学習","条件選択","後続検査")
PERIOD_NAMES=dict(zip(PERIODS,("学習40場","条件選択24場","既使用11/4Day/Night2場")))
POLICIES=("C0","C1")
EXITS=("X0","XS")
COMMON=ROOT/"docs/議論/最低同値床の上でATRと公開SARを比較する.md"


def helper() -> Any:
    """固定31の保存表示・版2描画を読取再用する。

    引数: なし。
    返り値: Anyは表示モジュール。旧globalや旧ファイルを書き換えない。
    """
    spec=importlib.util.spec_from_file_location("SAR32帳票の固定31表示",ROOT/"scripts/CCI突破/レポート.py")
    value=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=value
    spec.loader.exec_module(value)
    return value


F=helper()
G,P,number,V2=F.G,F.P,F.number,F.V2


def definitions(config: dict) -> list[dict]:
    """二入口×二出口の四評価を事前順に列挙する。

    引数: config(dict)は32条件。
    返り値: list[dict]はR01..R04。入口評価はC0/C1の二つだけ。
    """
    if config["戦略"]!=list(POLICIES) or config["出口"]!=[{"出口ID":"X0"},{"出口ID":"XS"}]:
        raise ValueError("固定二入口・二出口と異なる")
    return [{"評価ID":f"R{index:02d}","候補ID":f"3分_{entry}_{exit}","入口ID":"3分_"+entry,
             "戦略":entry,"出口ID":exit,"役割":"順行"}
            for index,(entry,exit) in enumerate(((e,x) for e in POLICIES for x in EXITS),1)]


def validate(study: Path) -> tuple[dict,dict,list[dict],dict,dict,Path]:
    """共有先・四運用会計・品質・旧X0同値を保存正本から確認する。

    引数: study(Path)は32正式先。
    返り値: tuple[dict,dict,list[dict],dict,dict,Path]は条件/結果/評価/二入口/四運用/実台帳。
    """
    for name in ("条件.json","計画.md","固定.json","結果.json","入力台帳.json","入口参照.json","X0対照同値.json","指標品質.json"):
        if not (study/name).is_file():raise ValueError(name+"未保存。正式完了前の実測帳票は禁止")
    config,report=G.read_json(study/"条件.json"),G.read_json(study/"結果.json")
    rules=definitions(config)
    old_config,old_report,_,old_entries,old_values,manifest=F.validate(OLD_STUDY)
    if report["全66場既使用"] is not True or report["入口125250評価の変更"] is not False:
        raise ValueError("既使用性又は先着幅が不一致")
    if report["入口評価"]!=old_report["入口評価"] or report["入口評価数"]!=2 or report["運用候補数"]!=4:
        raise ValueError("二共有入口/四運用の分母が不一致")
    entries={row["入口ID"]:row for row in report["入口評価"]}
    values={row["候補ID"]:row for row in report["結果"]}
    if len(values)!=4 or len(report["結果"])!=4 or report["表示固定ID"]!=[row["候補ID"] for row in rules]:
        raise ValueError("事前四運用の集合・順序が不一致")
    pointer=G.read_json(study/"入口参照.json")
    if pointer["参照試行"]!="00031" or pointer["大明細複製"] is not False or pointer["旧固定SHA256"]!=G.sha(OLD_STUDY/"固定.json"):
        raise ValueError("共有入口の固定31参照が不一致")
    if set(pointer["文書と証明"])!={"固定.json","条件.json","結果.json","作業成果物.json","独立監査.json","状態独立確認.json","追尾独立確認.json","入力台帳.json"}:
        raise ValueError("共有先の必須八文書が不足")
    for name,item in pointer["文書と証明"].items():
        if (ROOT/item["パス"]).resolve()!=(OLD_STUDY/name).resolve() or G.sha(ROOT/item["パス"])!=item["SHA256"]:
            raise ValueError("共有先の文書/証明版差")
    for rule in rules:
        row,entry=values[rule["候補ID"]],entries[rule["入口ID"]]
        if row["入口"]!=old_values[rule["入口ID"]+"_X0"]["入口"] or row["出口"]!={"出口ID":rule["出口ID"]}:
            raise ValueError("四運用の入口/出口定義が不一致")
        if (row["入口支持"],row["70目標"])!=(entry["入口支持"],entry["70目標"]):
            raise ValueError("同じ入口を独立の支持/目標へ数え直さない")
        if rule["出口ID"]=="X0" and row!=old_values[rule["候補ID"]]:
            raise ValueError("固定31X0の保存集計に差")
        for period,count in zip(PERIODS,(40,24,2)):
            op=row[period]["運用"];n=op["完結取引数"]
            if row[period]["入口"]!=entry[period] or op["入力場数"]!=count or op["活動場数"]+op["無取引場数"]!=count:
                raise ValueError("期間/入口/活動分母に差")
            if op["買い取引数"]+op["売り取引数"]!=n or op["役割別完結数"].get("順行",0)!=n:
                raise ValueError("売買鏡像・順行完結分母に差")
            if not 0<=op["起動後純赤字取引数"]<=op["追尾起動取引数"]<=n:
                raise ValueError("追尾起動の分母に差")
            for slip in (0,5,10):
                net,average=op[f"追加{slip}pt純損益円"],op[f"追加{slip}pt平均円"]
                if not math.isclose(net,op["追加0pt純損益円"]-20*slip*n,abs_tol=1e-8):raise ValueError("追加費用に差")
                if (average is None)!=(n==0) or n and not math.isclose(average,net/n,abs_tol=1e-8):raise ValueError("平均の分母に差")
                if op["品質注意場数"] and op[f"追加{slip}pt確定対象円"] is not None:raise ValueError("注意期の確定額nullを維持する")
        qualified=all(all(row[period]["運用"][key]>=limit for key,limit in limits.items()) and row[period]["運用"]["品質注意場数"]==0 and row[period]["運用"]["追加5pt純損益円"]>0 for period,limits in config["費用支持"].items())
        if row["費用資格"]!=qualified:raise ValueError("費用資格に差")
    if report["入口70目標達成数"]!=sum(row["70目標"] for row in entries.values()) or report["費用資格数"]!=sum(row["費用資格"] for row in values.values()):
        raise ValueError("70は二入口、費用は四運用の分母を使う")
    control=G.read_json(study/"X0対照同値.json")
    if control["全件一致"] is not True or control["場候補数"]!=132 or len(control["照合"])!=132 or not all(row["全運用同値"] and row["全追尾同値"] for row in control["照合"]):
        raise ValueError("X0全ledger/trace同値が未確認")
    pins=G.read_json(study/"固定.json")["ファイルSHA256"]
    if any(G.sha(ROOT/name)!=digest for name,digest in pins.items()):raise ValueError("固定出典に変更")
    input_pointer=G.read_json(study/"入力台帳.json")
    if (study/input_pointer["参照"]).resolve()!=manifest or G.sha(manifest)!=input_pointer["SHA256"]:raise ValueError("共通66台帳参照に差")
    if config["入口条件参照"]["SHA256"]!=G.sha(OLD_STUDY/"条件.json") or config["カタログ版"]!=2:raise ValueError("固定31入口又は版2参照に差")
    return config,report,rules,entries,values,manifest


def settings(rules: list[dict]) -> list[dict]:
    """共有入口と出口ごとのATR/SAR・床・執行・診断を版2へ分ける。

    引数: rules(list[dict])は四運用評価。
    返り値: list[dict]は13設定。SAR準備を入口gateとして記録しない。
    """
    c1=[row for row in rules if row["戦略"]=="C1"]
    atr=[row for row in rules if row["出口ID"]=="X0"]
    sar=[row for row in rules if row["出口ID"]=="XS"]
    groups=[
        (["P01","P02","P07"],["m03"],rules,"共有31：前20高安strict終値突破",
         "同場連続公開20H/Lを固定、現在足除外。C>HH/C<LL、等号/ヒゲ不可。rolling原P・全採否・入口先着は31共有、出口で取り直さない"),
        (["I13"],["m03"],rules,"共有31：現前CCI20の実side値>100",
         "元H/L/C FractionのTP、各現在20窓μ/MD、係数3/200。MD0無効、現前に当場21公開、±100等号不成立。SAR数値をCCI準備へ追加しない"),
        (["I05"],["m15"],rules,"共有M：最新当場公開BB20現前準備",
         "15分BB数値は同限月carry、公開現前pairは同場隣接。最新不準備で古正常へ戻らない。C0/C1共通準備、数値0幅も可"),
        (["I05"],["m15"],c1,"共有C1値：15分BB絶対幅4σの厳密拡大",
         "母分散の現前Fraction差>0。分子分母は分散差で幅差ではない。数学等幅0/縮小は不採用。入口にSAR準備/方向のgateを増やさない"),
        (["I09"],["m03"],rules,"共有入口M：ATR14有限正",
         "固定31の3分ATR数値/公開・欠枠規約を保持。X0は実入口ATRからD固定、XSの上締上げにはATR距離を使わない"),
        (["C07"],["m03","m15"],rules,"共有入口：上位end/key asofと当場pair",
         "31と同じ現前CCI/上位BBの公開順、局所窓と数値carryを分離。純再構成whitelistだけを運用へ渡し、旧label/仮新規/判定/未来MFEを渡さない"),
        (["B01"],["tick"],rules,"一建玉・新規/返済1価格秒・TTL30秒",
         "買Ask/売Bid新規、返済側BBO。quote→公開足→signal。同keyのbar時にlastBBOで即要求しない。価格時計は実受信時計ではなく代理執行"),
        (["I09","C06","E02"],["tick"],atr,"X0：固定31 A5/入口ATR距離を完全再用",
         "D=max(5,ceil(入口ATR/5)*5)、保護利益max(0,MFE−D)、買ceil/売floor・非緩和。旧31全fill/order/取引/入口取扱/追尾traceと同値を検査"),
        (["I10"],["m03"],sar,"XS：精密SAR AF2/100・増分2/100・max20/100",
         "元OHLC各float→Fraction。初期終値差strict/同値保留、成熟は事前線strict貫通→非反転前2足clamp→EPstrict/AF→無clamp次線。25選定規約を精密化、旧float/TA-Lib完全同値としない。hex正規分子/正分母、打切りなし"),
        (["I10","E02"],["tick"],sar,"XS：公開key後BBOで精密次足線を上締上げ",
         "当場最新一つ、方向=sかつ元精密線のs*(S−新規)>0のみ。5pt買ceil/売floor、買max/売minで旧床非緩和。最新不良/逆向きは旧床維持・古SARfallbackなし。入口前当場公開も可、入口gate追加なし"),
        (["E02"],["tick"],rules,"共通：MFE5ptで名目同値床・hard125/TP250/期限",
         "SAR不準備でも初回床を必ず起動。XS初回BBOでSAR上締上げ可、既越候補は気配へclampせず要求後待機BBO約定。期限/既pending→hard→TP→追尾、pending中は建玉起動/線/適用出典凍結、global源とMFEは進行"),
        (["E01"],["tick"],rules,"共有125/250先着は二入口・運用は四案",
         "31入口評価/ラベルの既検証値を参照し新規に先着計算しない。70目標は2分母、費用資格4分母。純入口支持と保有中回収・片側再参加を分ける"),
        (["I10","E02"],["m03","tick"],sar,"診断のみ：SAR適用群・公開源・床/実回収",
         "SAR適用済み/未適用の事後群を当時の入口へ戻さない。適用可能な足/建玉の分母、追尾起動後の評価BBO・理由counter、最終線不足と同値費用を区別する"),
    ]
    return [{"設定ID":f"S{index:02d}","手法ID":methods,"尺度ID":scales,"短記":short,"説明":detail,
             "結果短記":"・".join(row["評価ID"] for row in applies),"適用評価":[row["評価ID"] for row in applies]}
            for index,(methods,scales,applies,short,detail) in enumerate(groups,1)]


def comparison(entries: dict, values: dict) -> str:
    """二つの共有先着と四つの実運用を別表・別分母で表示する。

    引数: entries/values(dict)は共有二入口/新四運用。
    返り値: strは支持・先着・費用・追尾/品質の小表。
    """
    entrance_rows=[]
    for eid,entry in entries.items():
        for period in PERIODS:
            row=entry[period]
            entrance_rows.append([eid,PERIOD_NAMES[period],row["候補数"],
                f"{row['順行先着']}/{row['約定候補数']}・{G.pct(row['確認率'])}",
                f"{row['30分間引き_順行先着']}/{row['30分間引き_約定候補数']}・{G.pct(row['30分間引き_確認率'])}",
                f"{row['逆行先着']}/{row['期限未達']}/{row['観測不足']}/{row['未約定']}"])
    text="## 共有二入口の125/250先着\n\n入口/仮新規/先着は固定31と同じ二つで、出口X0/XSごとに四標本へ増やさない。仮先着は実返済後も観測するため、今回の回収改善を直接示す指標ではない。分母は全仮約定で期限・不足を除かない。\n"
    text+=G.table(["入口","期間","純要求","250/仮約定・率","30分間引き250/仮約定・率","125/期限/不足/未約定"],entrance_rows)
    rows,quality,supports=[],[],[]
    for cid,value in values.items():
        for period in PERIODS:
            op=value[period]["運用"]
            rows.append([cid,PERIOD_NAMES[period],op["完結取引数"],
                *[number(op[f"追加{fee}pt純損益円"]) for fee in (0,5,10)],number(op["追加5pt平均円"]),
                op["買い取引数"],op["売り取引数"],op["品質注意場数"]])
            quality.append([cid,PERIOD_NAMES[period],op["追尾起動取引数"],op["起動後純赤字取引数"],
                str(op["活動場数"])+"/"+str(op["無取引場数"]),op["未解消場数"],op["EOF期限未達場数"],
                number(op["期間内最大場内DD円"]),number(op["追加0pt確定対象円"])])
            if period in PERIODS[:2]:
                supports.append([cid,PERIOD_NAMES[period],str(op["完結取引数"])+"/"+str(op["活動開始日数"])+"/"+str(op["活動場数"]),
                    str(op["買い取引数"])+"/"+str(op["売り取引数"]),"充足" if value["費用資格"] else "未達"])
    text+="## 四運用の実損益\n\n注意期の全体確定額はnull。総額・平均は観測値であり、注意を含む基準案と無注意案の差を確定した実力差としない。追加片道5/10ptは同じ約定往復へ100/200円を加算控除する費用感度。\n"
    text+=G.table(["運用","期間","実完結","基準観測円","追加5pt観測円","追加10pt観測円","追加5pt平均円","買","売","注意場"],rows)
    text+="### 支持と品質\n\n入口支持/主率70%/30分間引き70%の条件は固定31を共有。費用資格は四運用ごとに学習/選択の件数・活動日/場・両方向支持、注意0、追加5pt後の両期黒字を全て要求する。既使用2場で代用しない。最大DDは各場0開始で、期間接合の累積DDではない。\n"
    text+=G.table(["運用","期間","完結/日/場","実買/売","両期費用資格"],supports)
    return text+G.table(["運用","期間","追尾起動","起動後基準赤字","活動/無取引場","未解消場","EOF未達場","最大場内DD円","基準確定対象円"],quality)


def proof_path(study: Path, work: Path, name: str) -> Path:
    """同byteの正式copyか作業正本を選ぶ。

    引数: study/work(Path)は正式/作業先、name(str)は証明名。
    返り値: Pathは正式優先の正本。版差・未保存は例外。
    """
    return F.proof_path(study,work,name)


def stages(study: Path) -> str:
    """SAR数値準備・公開・桁数を入口件数と分離して表示する。

    引数: study(Path)は32正式先。
    返り値: strは期別の精密SAR品質表。長いhex本体は転記しない。
    """
    quality=G.read_json(study/"指標品質.json")
    fields=("SAR入力足数","SAR数値準備足数","SAR公開準備足数","SAR未公開数値更新数","SAR初期化数","SAR反転数","SARclear数","SAR尾部完全欠枠")
    rows=[]
    for period in PERIODS:
        own=[row for row in quality if row["期間"]==period]
        rows.append([PERIOD_NAMES[period],len(own),*[sum(row[key] for row in own) for key in fields],
            max((row["最大分母bit長"] for row in own),default=0),max((row["最大分数保存文字数"] for row in own),default=0)])
    text="## 精密SARの数値・公開準備\n\nSAR不準備で純入口を除外していない。以下は数値を計算できた足と公開できた足の別集計で、利益床を起動できた建玉数やSARで締められた回数ではない。数値carryと当場公開参照を分け、長い有理数は符号付き正規形hex分子/正分母で一度だけ新SAR明細へ保存する。float表示へ戻して判定せず、桁数制限のための打切り・分母制限・resetは加えない。\n"
    return text+G.table(["期間","入力場","SAR足","数値準備","公開準備","NP数値更新","初期化","反転","clear","尾部欠枠","最大分母bit","最大分数保存文字"],rows)


def audits(study: Path, work: Path, output: Path) -> tuple[str,list[Path]]:
    """新四運用・旧入口共有・主独立準備と全証明の版を照合する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: tuple[str,list[Path]]は監査状態表/出典。実再生は実行しない。
    """
    groups=[("合成検証.json","人工精密SAR/公開順/床/XS集計/非PnL/固定境界"),
        ("独立監査.json","全四運用Decimal会計/共有先着/資源"),
        ("状態独立確認.json","独立精密SAR/純signal/全公開元/X0同値"),
        ("追尾独立確認.json","独立XS全BBO走査/最初要求/床と全保有trace"),
        ("対応診断.json","共通実新規の出口差/片側参加/全費用分解/回収"),
        ("Viewer照合.json","事前四運用の代表Viewer")]
    paths=[];rows=[]
    for name,title in groups:
        path=proof_path(study,work,name);data=G.read_json(path)
        success=data.get("全件一致",data.get("対応集合全件一致"));count=data.get("照合項目数")
        if name=="合成検証.json":
            success=data.get("全件成功") is True and data.get("合成編集終了") is True
            count=data["検証件数"]
            if any(G.sha(ROOT/key)!=digest for key,digest in data["ファイルSHA256"].items()):raise ValueError("最終人工pin差")
            if data["独立数値補助SHA256"]!=G.sha(HERE/"状態独立確認.py") or data["独立追尾補助SHA256"]!=G.sha(HERE/"追尾独立確認.py"):
                raise ValueError("人工の独立補助版差")
        elif name=="Viewer照合.json":
            checks=data.get("照合",[])
            success=len(checks)==4 and all(row["一致"] is True for row in checks);count=len(checks)
        if success is not True:raise ValueError("正式証明未完："+name)
        if "不一致数" in data and data["不一致数"]!=0:raise ValueError("正式証明に不一致："+name)
        if "結果SHA256" in data and data["結果SHA256"]!=G.sha(study/"結果.json"):raise ValueError("証明対象結果の版差")
        if name=="独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("会計へ状態/追尾が未接続")
        if name=="対応診断.json" and data.get("ファイルSHA256",{}).get((study/"結果.json").relative_to(ROOT).as_posix())!=G.sha(study/"結果.json"):
            raise ValueError("対応診断の結果bind差")
        paths.append(path);rows.append([title,"一致/合格",number(count),G.link(path,output)])
    main=work/"準備点検.json"
    independent_path=proof_path(study,work,"独立準備点検.json")
    independent=G.read_json(independent_path)
    locked=G.read_json(study/"固定.json");ref=G.read_json(study/"準備参照.json")
    if G.sha(main)!=locked["主準備SHA256"] or G.sha(main)!=ref["主準備SHA256"] or G.sha(independent_path)!=locked["独立準備SHA256"]:
        raise ValueError("主独立準備と実行前固定のbind差")
    if independent["全件一致"] is not True or independent["主準備SHA256"]!=G.sha(main) or independent["ラベル計算"] is not False or independent["損益計算"] is not False:
        raise ValueError("独立非PnL準備が未完")
    for key,file in (("条件SHA256","条件.json"),("入力台帳SHA256","入力台帳.json"),("入口参照SHA256","入口参照.json")):
        if independent[key]!=G.sha(study/file):raise ValueError("独立準備の条件/入力/共有先版差")
    if ref["ラベル計算"] is not False or ref["損益計算"] is not False:raise ValueError("準備の非PnL表示に差")
    paths.extend([main,independent_path])
    rows.extend([["主準備：純入口再構成/精密SAR・label/PnLなし","66場・非損益",66,G.link(main,output)],
        ["独立非PnL：SAR有理数と純signal判断の別再構成","一致/合格",number(independent["照合項目数"]),G.link(independent_path,output)]])
    control=study/"X0対照同値.json"
    paths.append(control);rows.append(["旧31X0の全ledger/trace直比較","132場候補・一致",132,G.link(control,output)])
    if (study/"保存物読取補足.json").is_file() or (work/"保存物読取補足.json").is_file():
        extra=proof_path(study,work,"保存物読取補足.json");data=G.read_json(extra)
        if data.get("全件一致") is not True or data.get("不一致数",0)!=0:raise ValueError("保存物副読取が不一致")
        if data.get("参照SHA256",{}).get("対応診断.json")!=G.sha(proof_path(study,work,"対応診断.json")):
            raise ValueError("保存物副読取の対象診断版差")
        paths.append(extra);rows.append(["保存物の独立副読取","一致/合格",number(data.get("照合項目数")),G.link(extra,output)])
    text="## 検査と共有の状態\n\n固定前人工・主独立非PnL準備と、固定後の全SAR/純信号・全保有追尾・会計・共有先着・Viewerを区別する。精密SAR/AF/hex/公開key/呼値/採否は厳密。旧ATRの別演算微差だけabs1e−10と正有効/D整数へ別照合し、純signal全文SHAと判断SHAを混同しない。検算項目を独立した収益標本へ足さない。\n"
    return text+G.table(["範囲","明示合否","件/項目","正本"],rows),paths


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """共通実新規の出口差と片側参加・床/SAR適用・回収を表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: strは保存診断の小表。新しい入口・出口を再生しない。
    """
    path=proof_path(study,work,"対応診断.json");data=G.read_json(path)
    if data["全件一致"] is not True or data["ファイルSHA256"].get((study/"結果.json").relative_to(ROOT).as_posix())!=G.sha(study/"結果.json"):
        raise ValueError("対応診断の明示合否/結果bind差")
    text="## 出口・参加・回収の対応\n\n"+G.link(path,output)+"を正本とする。共有caseは"+number(data["共有case数"])+"件、完結件数"+number(data["実完結取引数"])+"は四運用の和で独立入口標本数ではない。SARを足して先着を計算し直しておらず、実保有中の回収を比較する。\n"
    text+="### 共通実新規の出口差\n\n同じ場・実方向・新規時計/原行・価格の組で対応する。今回の出口は異なるので共通出口差を0とは仮定しない。先後は返済key、改善/悪化は同じ追加費用の実純額で判定する。\n"
    rows=[]
    for row in data["共通実新規の出口差"]:
        fee=next(value for value in row["費用別"] if value["片道追加pt"]==5)
        earlier=row["出口先後"]
        rows.append([row["入口"],PERIOD_NAMES[row["期間"]],row["共通実新規数"],
            str(earlier.get("XS先",0))+"/"+str(earlier.get("X0先",0))+"/"+str(earlier.get("同key",0)),
            number(fee["純損益差円"]["合計"]),number(fee["純損益差円"]["平均"]),
            str(fee["改善数"])+"/"+str(fee["同額数"])+"/"+str(fee["悪化数"]),
            number(row["XS引くX0"]["実方向返済価格pt"]["中央値"]),number(row["XS引くX0"]["保有分"]["中央値"])])
    text+=G.table(["入口","期間","共通実新規","XS先/X0先/同key","共通追加5差円","同平均差円","改善/同額/悪化","回収差pt中央値","保有差分中央値"],rows)
    text+="### 全費用差と片側だけの参加\n\n総差=共通出口差−X0のみの純額＋XSのみの純額。退出が変わると後続へ入れる集合も変わるため、同一取引の改善と参加構成の差を分ける。注意期の差額は観測値である。\n"
    rows=[]
    for row in data["実参加の全費用分解"]:
        for fee in row["費用別"]:
            rows.append([row["入口"],PERIOD_NAMES[row["期間"]],fee["片道追加pt"],row["共通実新規数"],
                number(fee["共通出口差円"]),str(row["X0のみ"]["完結取引数"])+"件・"+number(fee["X0のみ損益円"]),
                str(row["XSのみ"]["完結取引数"])+"件・"+number(fee["XSのみ損益円"]),number(fee["総差円_XS引くX0"])])
    text+=G.table(["入口","期間","追加片道pt","共通新規","共通出口差円","X0のみ件数/円","XSのみ件数/円","総差円XS−X0"],rows)
    text+=G.table(["入口","期間","X0のみ：XS側取扱","XSのみ：X0側取扱"],
        [[row["入口"],PERIOD_NAMES[row["期間"]],G.describe(row["片側参加の相手取扱"]["X0のみ"]),
          G.describe(row["片側参加の相手取扱"]["XSのみ"])] for row in data["実参加の全費用分解"]])
    text+="### 仮250と実保有中の回収\n\n仮250は返済後も保有継続した反事実。判定前返済を、保有中250ptを得て失った取引とは数えない。実MFEもその価格で全額回収できた利益ではない。\n"
    text+=G.table(["運用","期間","完結","保有分中央値","実回収pt中央値","観測MFE中央値","対応仮250","判定前返済","実保有MFE250"],
        [[row["候補ID"],PERIOD_NAMES[row["期間"]],row["完結取引数"],number(row["保有分"]["中央値"]),
          number(row["実回収pt"]["中央値"]),number(row["観測MFEpt"]["中央値"]),row["仮250先着取引数"],
          row["仮250判定前返済数"],row["実保有MFE250取引数"]] for row in data["候補別回収"]])
    text+="以下の赤字内訳は、追尾起動済みかつ基準純損益が負の完結取引を分母にする。同値返済の往復22円費用と、不利価格の返済は別である。\n"
    text+=G.table(["運用","期間","追尾起動","起動後基準赤字","うち同値費用","うち不利返済"],
        [[row["候補ID"],PERIOD_NAMES[row["期間"]],row["追尾起動数"],row["起動後純赤字数"],
          row["同値返済費用赤字数"],row["不利返済赤字数"]] for row in data["候補別回収"]])
    trade_rows=G.read_csv(study/"固定候補_取引.csv")
    rows=[]
    for cid in (f"3分_{entry}_{exit}" for entry in POLICIES for exit in EXITS):
        for period in PERIODS:
            own=[row for row in trade_rows if row["手法"]==cid and row["期間"]==period and row["追尾起動"]=="True"]
            below=sum((1 if row["方向"]=="買い" else -1)*(float(row["返済価格"])-float(row["新規価格"]))<0 for row in own)
            line=sum(float(row["最終追尾から実返済方向差pt"])<0 for row in own)
            rows.append([cid,PERIOD_NAMES[period],len(own),below,line,
                number(sum(max(0.,-float(row["最終追尾から実返済方向差pt"])) for row in own))])
    text+="以下の同値未満/最終線不足は追尾起動後の取引に限る。床の設定、最終線、実約定、費用後非赤字を区別する。\n"
    text+=G.table(["運用","期間","追尾起動","同値未満約定","最終線未満約定","線不足pt計"],rows)
    text+="### XS適用群は事後の分類\n\n未起動・同値床のみ・SAR締上げ済みは保有後の経過で決まる。SAR適用群の成績を当時の入口選別やSAR単独の効果に置き換えない。特にpending後のMFE増は過去の起動を補完しない。\n"
    text+=G.table(["運用","期間","事後区分","完結","追加5pt平均円","保有分中央値","実回収pt中央値"],
        [[row["候補ID"],PERIOD_NAMES[row["期間"]],row["事後区分"],row["完結取引数"],number(row["追加5pt平均円"]),
          number(row["保有分"]["中央値"]),number(row["実回収pt"]["中央値"])] for row in data["XSの事後適用群"]])
    if (study/"保存物読取補足.json").is_file() or (work/"保存物読取補足.json").is_file():
        extra_path=proof_path(study,work,"保存物読取補足.json")
        extra=G.read_json(extra_path)
        text+="### 実際にSARが作用した建玉・足・時点\n\n"+G.link(extra_path,output)+"の独立副読取から、固有建玉/公開足とBBO評価回数を分ける。C0/C1の適用足は重なるため、合計を独立した観測足数としない。\n"
        text+=G.table(["運用","期間","完結建玉","SAR締上げ済建玉","締上げ回数","固有適用公開足"],
            [[row["候補ID"],PERIOD_NAMES[row["期間"]],row["完結建玉数"],row["締上げ済建玉数"],
              row["締上げ回数"],row["固有適用公開足数"]] for row in extra["SAR実適用の建玉と足"]])
        text+=G.table(["期間","C0/C1共通の適用足","両者和集合の適用足"],
            [[PERIOD_NAMES[row["期間"]],row["共通固有足数"],row["両者和集合の固有足数"]] for row in extra["C0C1の適用足の重なり"]])
        text+="初適用時点の次表はSAR締上げ済み建玉だけの事後群。起動から初SAR適用までの経過を通信遅延と同一視しない。公開からの秒差0も同key利用ではなく、同秒後行keyで利用する規約は維持している。\n"
        text+=G.table(["運用","期間","対象建玉","起動→初適用秒の最小/中央値/最大","初適用前の床利益pt最小/最大","初適用後の床利益pt中央値","初適用時MFEpt中央値"],
            [[row["候補ID"],PERIOD_NAMES[row["期間"]],row["対象建玉数"],
              "/".join(number(row["A5起動から初SAR適用秒"][key]) for key in ("最小","中央値","最大")),
              "/".join(number(row["初適用前の名目保護利益pt"][key]) for key in ("最小","最大")),
              number(row["初適用後の名目保護利益pt"]["中央値"]),number(row["初適用時の観測MFEpt"]["中央値"])]
             for row in extra["A5起動と初SAR適用の時点"]])
        text+="今回の適用済み建玉は少数で、初SAR適用前の設定床は全件名目0pt。既使用後続2場のC0ではSAR適用0でも共通40新規だけで総差+1,100円となった。これはSAR線が作用した利益ではなく、ATR上締上げを外した床のみ方針の差である。小標本・事後適用群を新しい入口や切替条件へ戻さない。\n\n"
    text+="### SAR評価の分母\n\n次表の試行は、追尾起動済み・pendingなしの正常BBOごとの評価回数。同じ公開源を何度も評価し得るため、固有足数・固有建玉数・入口の採用数とは別である。公開更新数には無建玉時も含む。\n"
    text+=G.table(["運用","期間","評価BBO試行","有効公開","key後","方向一致","精密名目正","締上げ回数","同値床設定","公開参照更新"],
        [[row["候補ID"],PERIOD_NAMES[row["期間"]],sum(row["SAR評価理由別_BBO試行数"].values()),
          row["有効公開参照あり試行数"],row["公開key後試行数"],row["方向一致試行数"],row["精密名目利益正試行数"],
          row["SAR締上げ回数"],row["同値床設定数"],row["SAR公開参照更新数"]] for row in data["SAR適用記録"]])
    text+="### 品質と全体確定額\n\n品質注意期のnullは観測総額や事後の注意場除外で置換しない。SARが無効なときの床維持と、板観測の空白は別の問題である。\n"
    warnings=[row for row in data["品質と確定額"] if row["品質注意場数"] or row["未解消場数"] or row["EOF期限未達場数"]]
    if warnings:
        text+=G.table(["運用","期間","注意場/未解消/EOF","注意場","基準観測円","基準確定額"],
            [[row["候補ID"],PERIOD_NAMES[row["期間"]],str(row["品質注意場数"])+"/"+str(row["未解消場数"])+"/"+str(row["EOF期限未達場数"]),
              "・".join(row["品質注意場"]),number(row["観測純額円"]["0"]),number(row["全体確定対象円"]["0"])] for row in warnings])
    else:text+="保存運用に品質注意・未解消・EOF未達の記録はない。\n\n"
    return text


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """正式保存値・全証明完成後だけ二Markdownを生成する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。市場/先着/運用の再生は行わない。
    """
    config,report,rules,entries,values,manifest=validate(study)
    catalog=V2.load_catalog()
    output.mkdir(parents=True,exist_ok=True)
    readme,mapping=output/"README.md",output/"設定と結果.md"
    common=settings(rules)
    intro="固定31のNK225順行C0/C1という二入口・125/250先着評価を共有し、同値床後のATR距離X0と公開精密SARのXSを比較する。入口を新しく選別せず2入口×2出口の4運用とし、カタログ版2・52手法×9尺度で記録する。全66場（学習40・条件選択24・既使用11/4Day/Night2）は既使用の追加開発。未使用確認ではない。\n\n"
    conclusion=f"**入口70目標は{report['入口70目標達成数']}/2、費用資格は{report['費用資格数']}/4。** 入口支持・先着は31から共有し、出口を変えて70%標本を四つへ増やさない。\n\n"
    for entry in POLICIES:
        left,right=values[f"3分_{entry}_X0"],values[f"3分_{entry}_XS"]
        conclusion+=entry+"の追加5pt平均は"+"、".join(PERIOD_NAMES[period]+"でATR "+number(left[period]["運用"]["追加5pt平均円"])+"→SAR "+number(right[period]["運用"]["追加5pt平均円"])+"円" for period in PERIODS[:2])+"。\n\n"
    if all(values[f"3分_{entry}_XS"][period]["運用"]["追加5pt平均円"]<values[f"3分_{entry}_X0"][period]["運用"]["追加5pt平均円"] for entry in POLICIES for period in PERIODS[:2]):
        conclusion+="両入口・両期間で費用後平均は悪化した。これはATR上締上げの除去と公開SAR追加を合わせた運用方針全体の比較で、SAR単独の性能とはしない。\n\n"
    warnings=[row["候補ID"]+"/"+PERIOD_NAMES[period]+"="+str(row[period]["運用"]["品質注意場数"])+"場"
        for row in values.values() for period in PERIODS if row[period]["運用"]["品質注意場数"]]
    if warnings:
        conclusion+="品質注意は"+"、".join(warnings)+"。該当期の全体確定額はnull、総額/平均/共通差は観測値。\n\n"
    logic="## 共有入口と出口の役割\n\nC0は当場3分前20高安へのstrict終値突破＋現前CCI20実方向100超、C1はさらに当場公開15分BB20絶対幅拡大。CCIは元H/L/C FractionのTP・同じ各20窓平均/MD・係数3/200、MD0無効/±100等号不可。15分BB数値carryと当場公開pair/end-key asof、ATR正を31と同じ準備にする。今回SARを入口gateへ追加していない。\n\n"
    logic+="旧case・旧labelは共有参照だがliveの出所にしない。固定31を純再構成し、場/ID/方向/要求key/当時low-high-ATR/bb_meanだけを明示whitelistで新辞書へ写す。仮新規・判定・未来MFE等は運用へ渡さない。入口評価は二案で不変、SARは出口の追加材料である。X0は旧関数へ直渡しし、全fill/order/取引/入口取扱/追尾属性を除外なしで旧31と一致確認した。\n\n"
    logic+="精密SARは固定25の選定規約を元OHLCのFraction・AF整数/100で新実装した。初期は隣接終値のstrict差・同値保留、初期表示は買min(前L,現L)/売max(前H,現H)、EP現高安・AF2。成熟時は前次足線へのstrict貫通を先に反転判定し、非反転時だけ前2足clamp、その後EPstrict更新でAFを2増/上限20、表示+AF×(EP−表示)で無clamp次足線を作る。反転は旧EPと現在高安から表示/EPを再設定しAF2へ戻す。旧floatやTA-Lib/TradingViewとの完全同値、唯一の標準SARとは呼ばない。\n\n"
    logic+="SAR銀行は同限月carry、欠枠/番号欠/不正/尾部/限月で解除。有効欠枠当足は数値の種、全幅NPは内部更新だけ、partialは不投入。場初の公開参照は空で、当場最新だけを使う。長い精密値はhex正規分子/正分母へ保存し、float表示を方向・反転・利益・呼値判定へ戻さない。\n\n"
    protection="## 同値床・SAR・BBO・注文の時点\n\n両出口とも建玉あり・pendingなしの正常返済BBOでMFE>=5ptなら必須起動。XSはSAR不準備/逆向きでも名目同値床を作り、入口時ATR距離による上締上げを行わない。X0はD=max(5,ceil(入口ATR/5)*5)、利益幅max(0,MFE−D)を継承する。\n\n"
    protection+="XSは公開足tの確定方向と精密次足線を、公開keyよりstrict後の正常BBOから使う。同keyはBBO→bar→signalで、bar時lastBBOで線更新や即時要求をしない。BBO間に溜まった公開は最新一つだけ、最新不良から古い正常SARへ戻らない。入口前の当場最新公開も利用可。方向=sかつ元精密線のs×(S−新規)>0のみを5pt買ceil/売floorし、買max/売minで旧線非緩和。逆向き/不正/非正益では旧床を維持する。\n\n"
    protection+="初回床BBOで既知SARを締めることもできる。候補が気配を既に越えていても現在気配へclampせず、そのBBOで初着要求、要求+1価格秒以降の最初正常BBOで代理約定する。SAR線そのもので約定した扱いにしない。返済pending中は建玉の起動/設定線/適用出典を凍結し、global数値/公開源と実返済までのMFE/MAEは進める。pending後にMFEだけ伸びても過去の起動を補完しない。\n\n"
    protection+="期限/既pending約定→hard125→TP250→必須追尾の優先を保持し、通常出口/自動ドテンは足さない。新規TTL30秒、ラージBBOのmicro1枚代理・10円/pt・呼値5pt・片道11円。買Ask/売Bid新規・返済側BBO、追加5/10pt片道費用は同じ完結往復への感度である。同値床は同値約定や費用後非赤字を保証しない。\n\n"
    protection+="デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50を継承。正常板空白300秒超/未解消/EOF不足を残す。価格時計は受信時計ではなく、1価格秒待機は実発注遅延の実測でも実micro約定再現でもない。\n\n"
    limits="## 限界と知見の扱い\n\nSARは極値・AF・時間から追随線を作るが、参加者の注文・心理を直接測らない。進まない建玉から退出しやすくなる仮説と、押し戻りで早く退出する可能性を両方持つ。今回XSはATR距離を外し、足公開単位のSARへ替えたため、値と更新頻度を含む方針全体の比較である。\n\n"
    limits+="SAR締上げ済/床のみ、共通実新規、仮250対応は結果後の群。良い群だけを当時の入口や動的切替へ戻さない。床のみの独立対照は実行しておらず、全期のSAR追加だけの純増分を識別する比較ではない。未起動の事後MFEもpending中の伸び等を含み、床省略の証明ではない。共有入口・X0同値でもXSの保有長が後続参加を変えるため、同じ取引の出口差と参加差を分ける。主要条件を変える場合は別試行として事前固定する。\n\n"
    audit_text,audit_paths=audits(study,work,readme)
    comparison_text=comparison(entries,values)
    summary="# 試行00032：最低同値床と公開SAR追尾\n\n"+intro+" / ".join(G.link(study/name,readme) for name in ("計画.md","条件.json","固定.json","結果.json","入口参照.json"))+" / "+G.link(mapping,readme)+"\n\n"
    summary+=conclusion+comparison_text+stages(study)+diagnosis(study,work,readme)+logic+protection+limits+audit_text

    # ----------------------------------------
    # 版2をコピーし、入口二案と出口四案・診断・未使用を分ける。
    mapped="# 試行00032：設定と結果\n\n"+intro+conclusion+G.link(V2.MASTER,mapping,"コピー元汎用表・版2")+" / "+G.link(readme,mapping)+"\n\n"
    mapped+="## 手法×時間スケール\n\n52手法×9尺度。S01〜S07は共有入口/執行、S08はX0のATR距離、S09/S10はXSのSAR数値/公開BBO適用、S11は共通床/優先、S12は共有先着評価、S13は診断のみ。R01=C0_X0/R02=C0_XS/R03=C1_X0/R04=C1_XS。SAR自体の計算足は3分で、逐次列は確定SAR値の保護利用/診断時点を示し、tick SARを算出していない。SARは入口条件ではなく出口材料で、未使用・未検証・データ不足・対象外を区別する。複合成績を指標単独の効果としない。\n\n"
    mapped+=V2.matrix(catalog,mapping,common)
    mapped+="## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],
        [[row["設定ID"],"/".join(row["手法ID"])+"・"+"/".join(row["尺度ID"]),row["短記"],row["説明"],"・".join(row["適用評価"])] for row in common])
    mapped+="## 全固定条件\n"+G.table(["項目","固定値"],
        [[key+"（X0継承値、XS差分はSAR追尾欄）" if key=="必須追尾" else key,G.describe(value)] for key,value in config.items()])
    mapped+="## 四運用の定義と判定\n"+G.table(["評価","運用","入口/出口","共有入口支持","共有70目標","費用資格"],
        [[rule["評価ID"],rule["候補ID"],rule["戦略"]+"/"+rule["出口ID"],
          "充足" if values[rule["候補ID"]]["入口支持"] else "未達","達成" if values[rule["候補ID"]]["70目標"] else "未達",
          "充足" if values[rule["候補ID"]]["費用資格"] else "未達"] for rule in rules])
    mapped+=comparison_text+logic+protection+limits+audits(study,work,mapping)[0]

    # ----------------------------------------
    # 旧6gzip/447MB準備/全caseを複製せず、共有参照と新3gzipを指す。
    files=("入力台帳.json","入口参照.json","準備参照.json","X0対照同値.json","一覧.resources.json",
        "固定候補_取引.csv","固定候補_注文.csv","全候補_場別.csv","入力品質.json","指標品質.json","作業成果物.json")
    source_paths=[HERE/name for name in ("README.md","指標.py","運用.py","検証.py","合成検証.py","レポート.py",
        "独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py") if (HERE/name).is_file()]
    docs=[ROOT/name for name in ("docs/technical-analysis/指標/パラボリックSAR.md","docs/technical-analysis/指標/CCI.md",
        "docs/technical-analysis/組み合わせ/ATRと追尾決済.md","docs/議論/テクニカル手法の検証範囲と次の複合候補.md")]
    if COMMON.is_file():docs.append(COMMON)
    viewing="## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/name,readme) for name in files if (study/name).is_file())+"\n\nコード："+" / ".join(G.link(path,readme) for path in source_paths)+"。\n\n"
    viewing+="固定31の旧6gzip・447MB準備・CCI/BB全列とcaseを32へ複製しない。入口参照.jsonが8文書/証明と既存明細SHAを指す。新規はSAR全足/全運用詳細/追尾の3gzip、Git外work・展開内容SHAを作業成果物へ保存。Viewer一覧は四運用各66場の264資源と4代表。market_pathはdata_root、pnl_pathはcatalog基準。CSV最終SAR参照の構造欄はwriterの文字列表記に従う。\n\n"
    viewing+="--prepareは純入口再構成/SAR数値だけでlabel/運用/PnLなし。正式は旧31先着証明を再用し、既存結果/partialを上書きしない。主再生の詳細はコードREADMEに従う。保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/SAR追尾/レポート.py\n```\n\n"
    if COMMON.is_file():viewing+=G.link(COMMON,readme,"共通知見")+"。\n\n"
    paths=[Path(__file__),Path(F.__file__),ROOT/"scripts/一目基準線/レポート.py",ROOT/"scripts/反転確認時計/レポート.py",
        F.F.F.DISPLAY,ROOT/"scripts/SAR持続/レポート.py",ROOT/"scripts/終値切替/レポート.py",
        ROOT/"scripts/レポート/設定結果レポート.py",ROOT/"scripts/レポート/カタログ版2.py",V2.BASE,V2.CATALOG,V2.MASTER,manifest,
        *[study/name for name in ("計画.md","条件.json","固定.json","結果.json",*files) if (study/name).is_file()],
        OLD_STUDY/"結果.json",OLD_STUDY/"固定.json",OLD_STUDY/"条件.json",*source_paths,*docs,*audit_paths]
    for planned in (work/"診断予定.json",ROOT/"work/SAR追尾候補設計.md",ROOT/"work/SAR追尾の資料整理.md"):
        if planned.is_file():paths.append(planned)
    for path,text in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(text+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """指定先の保存帳票だけを再生成する。

    引数: なし。CLIの--study/--work/--outputは正式/作業/表示先。
    返り値: None。市場/ラベル/運用を再計算しない。
    """
    parser=argparse.ArgumentParser(description="共有二入口・ATR対公開SAR四運用の保存帳票")
    parser.add_argument("--study",type=Path,default=STUDY)
    parser.add_argument("--work",type=Path,default=WORK)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    print("\n".join(str(path) for path in run(args.study.resolve(),args.work.resolve(),(args.output or args.study).resolve())))


if __name__=="__main__":
    main()
