"""固定42A0とCMF変化三案を、保存証明と版4の二MDへ表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00043_再テスト時のCMF変化方向"
WORK = ROOT/"work/CMF変化/00043"
NUMERIC_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
COMMON = ROOT/"docs/議論/再テスト時にCMF水準と変化を分けた比較.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS,("学習40場","条件選択24場","既使用11/4Day/Night2場")))
POLICIES, ROLES = ("D0","D1","D2"), ("順行","反転")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
SPEC = importlib.util.spec_from_file_location("CMF変化43の固定41表示補助",ROOT/"scripts/回帰突破/レポート.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
G,P,F,number = BASE.G,BASE.P,BASE.F,BASE.number
VSPEC = importlib.util.spec_from_file_location("CMF変化43の独立版4表",ROOT/"scripts/レポート/カタログ版4.py")
V4 = importlib.util.module_from_spec(VSPEC)
sys.modules[VSPEC.name] = V4
VSPEC.loader.exec_module(V4)


PREVIOUS = ROOT/"study/00042_突破再テストと数量加重終値位置"

def definitions(config: dict) -> list[dict]:
    """三つの切替候補を、準備と値の三評価へ対応する。

    引数: config(dict)は42条件。
    返り値: list[dict]はR0〜R2。実T/Rは別役割として保持する。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["運用組合せ"] != [{"戦略":p,"出口ID":"XF"} for p in POLICIES]:
        raise ValueError("三切替入口/三XF以外")
    return [{"評価ID":"R"+str(i),"候補ID":cid,"入口":{"入口ID":"3分_"+p,"戦略":p,"時間足分":3,"名称":p,"役割":"切替","複合本命":True},"出口":{"出口ID":"XF"}} for i,(p,cid) in enumerate(zip(POLICIES,CANDIDATES))]


def validate(study: Path) -> tuple:
    """固定42対照/三切替/六役割・支持費用・指標参照と固定を確認する。

    引数: study(Path)は正式先。
    返り値: tupleは条件/結果/評価/入口/運用/台帳。結果なしでは生成しない。
    """
    for name in ("計画.md","条件.json","固定.json","結果.json","入口参照.json","対照参照.json","指標参照.json","D0対照同値.json"):
        if not (study/name).is_file():
            raise ValueError(name+"未保存。正式完了前に実測帳票を作らない")
    config,report=G.read_json(study/"条件.json"),G.read_json(study/"結果.json")
    rules=definitions(config)
    entries,values={r["入口ID"]:r for r in report["入口評価"]},{r["候補ID"]:r for r in report["結果"]}
    if config["カタログ版"] != 4 or report["全66場既使用"] is not True or (len(entries),len(values),report["入口評価数"],report["運用候補数"],report["現方針運用候補数"]) != (3,3,3,3,3) or report["表示固定ID"] != list(CANDIDATES):
        raise ValueError("版4/三入口運用/既使用性に差")
    for rule in rules:
        row,entry=values[rule["候補ID"]],entries[rule["入口"]["入口ID"]]
        if row["入口"] != rule["入口"] or row["出口"] != rule["出口"] or any(entry[k] != v for k,v in rule["入口"].items()):
            raise ValueError("集合切替/出口定義差")
        for period,count in zip(PERIODS,(40,24,2)):
            e,op=entry[period],row[period]["運用"]
            P.validate_entry(e)
            n=op["完結取引数"]
            if row[period]["入口"] != e or op["入力場数"] != count or op["活動場数"]+op["無取引場数"] != count or op["買い取引数"]+op["売り取引数"] != n or sum(op["役割別完結数"].get(role,0) for role in ROLES) != n:
                raise ValueError("期間/実役割の分母差")
            for fee in (0,5,10):
                net,mean=op[f"追加{fee}pt純損益円"],op[f"追加{fee}pt平均円"]
                if not math.isclose(net,op["追加0pt純損益円"]-20*fee*n,abs_tol=1e-8) or (mean is None) != (n == 0) or n and not math.isclose(mean,net/n,abs_tol=1e-8):
                    raise ValueError("同約定費用/平均差")
                if op["品質注意場数"] and op[f"追加{fee}pt確定対象円"] is not None:
                    raise ValueError("品質nullを維持")
        support,goal=F.entrance_flags(entry,config)
        fee_ok=all(all(row[p]["運用"][k]>=v for k,v in limits.items()) and row[p]["運用"]["品質注意場数"] == 0 and row[p]["運用"]["追加5pt純損益円"] > 0 for p,limits in config["費用支持"].items())
        if (entry["入口支持"],entry["70目標"],row["入口支持"],row["70目標"],row["費用資格"],row["現方針候補"],row["採用資格"]) != (support,goal,support,goal,fee_ok,True,goal and fee_ok):
            raise ValueError("支持/70/費用/採用差")
    roles=report["役割別入口評価"]
    if [(r["入口ID"],r["役割"]) for r in roles] != [("3分_"+p,role) for p in POLICIES for role in ROLES]:
        raise ValueError("三案×二実役割の六群差")
    for row in roles:
        for period in PERIODS:
            P.validate_entry(row[period])
        if (row["入口支持"],row["70目標"]) != F.entrance_flags(row,config):
            raise ValueError("役割別支持の分母差")
    for field,expected in (("入口70目標達成数",sum(r["70目標"] for r in entries.values())),("費用資格数",sum(r["費用資格"] for r in values.values())),("現方針費用資格数",sum(r["費用資格"] for r in values.values())),("採用資格数",sum(r["採用資格"] for r in values.values()))):
        if report[field] != expected:
            raise ValueError("全体資格数差:"+field)
    names={"固定.json","条件.json","結果.json","作業成果物.json","独立監査.json","状態独立確認.json","追尾独立確認.json","入力台帳.json"}
    reference=F.F.F.F.validate_reference(study/"指標参照.json",NUMERIC_STUDY,names)
    if reference["参照試行"] != "00029" or len(reference["共有明細"]) != 1:
        raise ValueError("共有数値一明細だけ")
    pointer=G.read_json(study/"入力台帳.json");manifest=(study/pointer["参照"]).resolve()
    if pointer["SHA256"] != G.sha(manifest) or manifest != ROOT/"study/00028_基準線復帰と上位一目の方向/入力台帳.json":
        raise ValueError("固定66場台帳差")
    for key,old in (("指標条件参照",NUMERIC_STUDY),("運用条件参照",EXIT_STUDY)):
        if config[key]["SHA256"] != G.sha(old/"条件.json"):
            raise ValueError("共有条件差")
    if any(G.sha(ROOT/n) != h for n,h in G.read_json(study/"固定.json")["ファイルSHA256"].items()):
        raise ValueError("全固定現在版差")
    previous_names=names|{"入力品質.json"}
    for filename,count in (("入口参照.json",5),("対照参照.json",2)):
        ref=F.F.F.F.validate_reference(study/filename,PREVIOUS,previous_names)
        if ref["参照試行"] != "00042" or len(ref["共有明細"]) != count:
            raise ValueError("旧42参照範囲差")
    control=G.read_json(study/"D0対照同値.json")
    if control["全件一致"] is not True or control["旧先着全件同値"] is not True or control["場候補数"] != 66 or any(not r["全運用同値"] or not r["全追尾同値"] for r in control["照合"]):
        raise ValueError("旧42A0完全対照未完")
    for filename,key in (("入口参照.json","入口参照SHA256"),("対照参照.json","対照参照SHA256")):
        if control[key] != G.sha(study/filename):raise ValueError("対照参照版差")
    return config,report,rules,entries,values,manifest


def proof_path(study: Path, work: Path, name: str) -> Path:
    """正式小証明を優先し、work正本とのbyte差を拒否する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは同版の保存証明。
    """
    return BASE.proof_path(study,work,name)


def audits(study: Path, work: Path, output: Path) -> tuple:
    """人工・純準備・現前CMF/差/I-O・直接先着・実会計/追尾を分ける。

    引数: study/work/output(Path)は保存/表示先。
    返り値: tupleは検査表と出典。市場や監査を起動しない。
    """
    rows,paths=[],[]
    for name,title in (("合成検証.json","人工現前CMF/精密差とI-O/鏡像/旧対照/固定guard"),("独立監査.json","新case集計/Decimal会計/全資源"),("状態独立確認.json","旧A0完全対照/現前CMF/差/全採否/直接先着"),("追尾独立確認.json","三XFの全保有/費用起動/名目床/最初要求"),("対応診断.json","現前準備/水準と差/I-O/実参加と役割別回収"),("Viewer照合.json","三運用の代表Viewer")):
        path=proof_path(study,work,name);data=G.read_json(path)
        verdict,count=data.get("全件一致"),data.get("照合項目数")
        if name == "合成検証.json":
            verdict,count=data["全件成功"] is True and data["合成編集終了"] is True,data["検証件数"]
            if any(G.sha(ROOT/n) != h for n,h in data["ファイルSHA256"].items()):
                raise ValueError("人工主版差")
            for key,file in (("独立数値補助SHA256","状態独立確認.py"),("独立追尾補助SHA256","追尾独立確認.py")):
                if data[key] != G.sha(HERE/file):
                    raise ValueError("人工独立版差")
        elif name == "Viewer照合.json":
            verdict,count=len(data.get("照合",[])) == 3 and all(r["一致"] for r in data["照合"]),len(data.get("照合",[]))
        if verdict is not True or data.get("結果SHA256") is not None and data["結果SHA256"] != G.sha(study/"結果.json"):
            raise ValueError("証明未完又は結果版差:"+name)
        if name == "対応診断.json" and data["参照SHA256"]["結果.json"] != G.sha(study/"結果.json"):
            raise ValueError("診断版差")
        if name == "独立監査.json" and (data.get("状態確認未完") is not False or data.get("追尾確認未完") is not False):
            raise ValueError("独立未接続")
        rows.append([title,"一致/合格",number(count),G.link(path,output)]);paths.append(path)
    main,ip=work/"準備点検.json",proof_path(study,work,"独立準備点検.json")
    independent,lock,ref=G.read_json(ip),G.read_json(study/"固定.json"),G.read_json(study/"準備参照.json")
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main) or lock["主準備SHA256"] != G.sha(main) or lock["独立準備SHA256"] != G.sha(ip):
        raise ValueError("非損益準備join差")
    if any(data["ラベル計算"] is not False or data["損益計算"] is not False for data in (G.read_json(main),independent)):
        raise ValueError("準備は非先着/非PnL")
    references=ref["参照"].values() if isinstance(ref["参照"],dict) else ref["参照"]
    if ref.get("大準備複製",False) is not False:
        raise ValueError("大量準備は軽量参照のみ")
    for item in references:
        path=ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:
            raise ValueError("準備軽量参照差")
        paths.append(path)
    paths.extend((main,ip))
    rows.extend((["固定前主準備・旧純対照/現前CMF/hash/三採否","66場・非損益",66,G.link(main,output)],["固定前独立・数値/現前CMF/差/I-O/三採否","一致/合格",number(independent["照合項目数"]),G.link(ip,output)]))
    for name in ("会計人工接続.json","保存物読取補足.json"):
        if not ((study/name).is_file() or (work/name).is_file()):
            continue
        path=proof_path(study,work,name);data=G.read_json(path)
        if data["全件一致"] is not True or data["不一致数"] != 0:
            raise ValueError("小証明未完")
        if name == "会計人工接続.json" and any(G.sha(ROOT/n) != h for n,h in data["コードSHA256"].items()):
            raise ValueError("会計人工の版差")
        rows.append([name+"・主最終人工と別","一致/合格",number(data["照合項目数"]),G.link(path,output)]);paths.append(path)
    text="## 検査の状態\n\n固定42の価格b/j/T-R/旧A0純245と全属性を対照にし、固定29のOHLC/ATR/中心化MACD/Qを共有する。43では現前CMF/精密差とI-O/全採否、新case全実sideの原BBO直接先着を独立確認する。旧11先着同値は直接走査の代用でない。CMF分数/時点/価格/全採否は厳密、ATR/H等の表現差だけを正式計画の範囲で許容し採否epsilonにしない。保存正本SHAと再算の生float SHAを区別し、準備は先着/運用/PnLなし。\n"
    for key in ("検証範囲","厳密範囲","数値許容"):
        if independent.get(key):
            text+=key+"："+G.cell(independent[key]).rstrip("。")+"。\n"
    for label,key in (("ATR表現差足数","独立atr表現差足数"),("ヒスト表現差足数","独立macd_hist表現差足数"),("ATR最大絶対差","独立atr最大絶対差"),("ヒスト最大絶対差","独立macd_hist最大絶対差")):
        if key in independent:
            text+=label+"："+str(independent[key])+"。\n"
    return text+G.table(["範囲","明示合否","件/項目","正本"],rows),paths


def result_tables(report: dict, entries: dict, values: dict) -> str:
    """混合全体と六役割群の先着・支持、実費用を分けて表示する。

    引数: report/entries/values(dict)は保存結果。
    返り値: strは小型表。後続2場へ単独の支持資格を付けない。
    """
    erows,orows,rrows=[],[],[]
    for policy in POLICIES:
        for period in PERIODS:
            e=entries["3分_"+policy][period]
            erows.append([policy,PERIOD_NAMES[period],e["候補数"],e["約定候補数"],f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}","/".join(str(e[k]) for k in ("逆行先着","期限未達","観測不足","未約定")),f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}"])
    for cid in CANDIDATES:
        row=values[cid]
        for period in PERIODS:
            op=row[period]["運用"]
            orows.append([cid,PERIOD_NAMES[period],op["完結取引数"],*[number(op[f"追加{f}pt純損益円"]) for f in (0,5,10)],number(op["追加5pt平均円"]),op["品質注意場数"],BASE.confirmed(op["追加0pt確定対象円"],op["品質注意場数"])])
    for role in report["役割別入口評価"]:
        for period in PERIODS:
            e=role[period]
            rrows.append([role["入口ID"],role["役割"],PERIOD_NAMES[period],f"{e['候補数']}/{e['約定候補数']}",f"{e['順行先着']}/{e['約定候補数']}・{G.pct(e['確認率'])}",f"{e['30分間引き_順行先着']}/{e['30分間引き_約定候補数']}・{G.pct(e['30分間引き_確認率'])}",f"{e['約定開始日数']}/{e['約定場数']}","充足" if role["入口支持"] else "未達","達成" if role["70目標"] else "未達"])
    text="## 三入口・三XFと六役割群\n\n主先着率は期限/観測不足を含む全仮約定が分母、未約定は別記。新要求j時計を30分間引きの主にする。集合は切替、実Tは順行/実Rは反転。混合率の変化を両役割の改善や片役割支持へ代用しない。\n"
    text+=G.table(["入口","期間","純要求","仮約定","250/全仮約定・率","125/期限/不足/未約定","j30分間引き250/仮約定・率"],erows)
    text+=G.table(["運用","期間","実完結","基準観測円","追加5pt観測円","追加10pt観測円","追加5pt平均円","注意場","基準確定円"],orows)
    text+="入口支持は学習60仮約定/6日/10場・選択20/3/5。70は両期主率/間引き率70%・間引き件数20/10。費用支持は学習20完結/6日/10場/買売各5・選択10/3/6/各3と品質注意0、追加5pt後両期黒字。採用は入口70と費用資格の両方。以下の役割支持/70は学習＋条件選択の両期判定の再掲で、後続2場単独が支持条件を満たす意味ではない。\n"
    return text+G.table(["入口","実役割","期間","要求/仮約定","250/仮約定・率","j間引き250/仮約定・率","日/場","両期役割支持","両期役割70"],rrows)


def settings(rules: list[dict]) -> list[dict]:
    """固定価格/勢いとCMF現前準備・変化・診断を区別する。

    引数: rules(list[dict])は三評価。
    返り値: list[dict]は10設定。現水準/I正を採否へ加えない。
    """
    groups=[
        (["P07","P10"],["m03"],rules,"D0：固定42A0の価格登録/最初再テスト全純保持","前20突破b/一監視/used/6足/最初対象j/T順行R反転。新価格母集団を作らず旧245純と全66運用/追尾をIDだけ変換して対照"),
        (["I03"],["m03"],rules,"固定42の実side×δMACDヒスト>0を保持","当時j/既競合後A0/現前数値/時間を取り直さず、旧不採用やWAITを数量で救済しない"),
        (["I09"],["m03"],rules,"共通：固定jATR14正/同じ入口D","bや後足ATRへ替えず、価格/役割/要求時計/ATRは旧A0純13保持"),
        (["V06"],["m03"],rules[1:],"D1準備：現前CMF21/22連続足と全22q/両総q正","当場隣接前index−1・公開asof、各幅正/q完全非負。完全0q可、共通20q0でも両21総量正なら可。未定義を0にしない"),
        (["V06"],["m03"],rules[2:],"D2差：実side×(F現−F前)>0strict","元HLCq各Fractionの直接差/交差積符号。差0不採用、表示epsilonなし。現水準/I正/後足h確認をANDしない"),
        (["V06"],["m03"],rules,"診断のみ：同D1内の水準×差/I-O/入落m,q","Δ=I+O、I=q現(m現−F前)/Q現、O=−q落(m落−F前)/Q現。分母希釈を含み注文flowでない。新水準/I/O運用なし"),
        (["B01"],["m03"],rules,"固定j時計/残60分/遅延30秒/既競合を保持","b時計へ主間引きを移さず、全採否後pure13へdeepcopy。未来labelなし・新h待機なし"),
        (["B01"],["tick"],rules,"市場+1秒/TTL30/一pending・一建玉","純subsetと実占有差を分ける。旧11先着を照合し全実sideの新caseを原BBO直接独立再走査"),
        (["I09","C06","E02"],["tick"],rules,"XF：現在返済利益円−122>0strict/名目entry床","現j入口ATR固定D/MFE−D/非緩和/pending凍結。追加0/5/10は同約定費用ストレス、起動参照5固定"),
        (["E01","B01"],["tick"],rules,"診断：直接先着/旧完全対照/共通出口/片側参加/回収","同時計旧11値の同値は直接先着監査の代用でない。総額/平均/役割支持/仮250とMFE/実回収/費用を分離"),
    ]
    return [{"設定ID":f"S{i:02d}","手法ID":m,"尺度ID":sc,"短記":short,"説明":detail,"結果短記":"・".join(r["評価ID"] for r in applies),"適用評価":[r["評価ID"] for r in applies]} for i,(m,sc,applies,short,detail) in enumerate(groups,1)]


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """共通準備内の水準/差/I-Oと、実参加・役割別回収を表示する。

    引数: study/work/output(Path)は保存/表示先。
    返り値: strは保存診断本文。旧母監視/全CMFpanelを再転記しない。
    """
    path=proof_path(study,work,"対応診断.json");data=G.read_json(path)
    text="## 旧j全体・固定基準・現前準備・差選別\n\n"+G.link(path,output)+"が正本。旧全424jとD0純245は別分母で、CMF準備から旧不採用/WAITを救済しない。D0は固定42A0完全対照、D0→D1は22足の準備、D1→D2は同時計の差符号。\n"
    text+=G.table(["期間","全旧j/旧A0純/全j現前準備","D0/D1/D2純"],[[PERIOD_NAMES[r["期間"]],f"{r['旧全j数']}/{r['旧A0純数']}/{r['全j現前準備数']}","/".join(str(r[p+"純入口数"]) for p in POLICIES)] for r in data["旧jと三入口"]])
    text+=G.table(["比較/期間/役割","保持要求/仮約定・250率","除外要求/仮約定・250率","純追加","準備除外理由・重複あり"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]]+"/"+r["役割"],*[f"{r[k]['候補数']}/{r[k]['約定候補数']}・{r[k]['順行先着']}/{r[k]['約定候補数']}={G.pct(r[k]['確認率'])}" for k in ("保持入口","除外入口")],r["新規追加入口数"],G.describe(r["現前準備除外理由_重複あり"])] for r in data["入口追加比較"]])
    text+="## 同じD1準備で現水準と変化を比べる\n\n分母は現前CMFが揃ったD1純要求だけ。現在水準の正負と変化の正負/0を分ける。旧42A2全体は前CMF準備を必須にせず、準備を揃えない全体損益差を水準対変化の純効果としない。水準だけの新第4運用は実行していない。\n"
    text+=G.table(["期間/役割","実方向F現/差","要求/仮約定","250/仮約定・率"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["実方向現水準"]+"/"+r["実方向差"],f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["現水準と変化"] if r["候補数"]])
    text+=G.table(["期間/役割","水準と差のshadow区分","要求/仮約定","250/仮約定・率"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["区分"],f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["水準と差の保持重複"]])
    text+="## 当足Iと窓脱落Oの寄与\n\nI/OはD1全体の同じ保存分数からの恒等分解で、D2通過だけで機序を結論しない。I正は当足m正/新買い圧力を意味せず、Oは売り手退出人数でない。寄与/水準の新AND、別運用、h待機は追加していない。\n"
    opposite=[sum(r["実方向差別"].get("正",0) for r in data["IとOの寄与区分"] if r["期間"] == period and r["役割"] == "全体" and r["実方向I"] == "負" and r["実方向O"] == "正") for period in PERIODS]
    text+="実方向Iが負でもOを合わせた差が実方向正となる純要求は、学習/選択/後続の順に"+"/".join(map(str,opposite))+"件。I0の脱落だけ改善例が0件でも、窓脱落の寄与がないことや差正が当足量増勢であることを意味しない。\n"
    text+=G.table(["期間/役割","実方向I/O","差符号別","要求/仮約定","250/仮約定・率"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["実方向I"]+"/"+r["実方向O"],G.describe(r["実方向差別"]),f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["IとOの寄与区分"]])
    text+=G.table(["期間/役割","D1/D2純","当足q0/落足q0","I0/O0","I0・脱落だけ実方向改善"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],f"{r['D1純要求数']}/{r['D2純要求数']}",f"{r['当足q0数']}/{r['落足q0数']}",f"{r['I0数']}/{r['O0数']}",r["I0脱落だけ実方向改善数"]] for r in data["寄与機序"]])



    text+="## 厳密共通出口と実参加\n\n厳密共通は場/実side/実役割/新規key/価格/入口jATR/D。親b一致だけを共通出口としない。純subsetでも実追加は起こり得るが、今回の件数を下表で区別する。共通0の差0は比較対象なし。全額差=共通出口差＋右のみ額−左のみ額を追加0/5/10別に確認する。総赤字縮小を平均回収改善へ読み替えない。\n"
    text+=G.table(["比較/期間/役割","同j両参加/厳密共通","共通出口属性差","共通出口差0/5/10円","左のみ完結・0/5/10円","右のみ完結・0/5/10円","全差0/5/10円"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]]+"/"+r["役割"],f"{r['同j両実参加数']}/{r['厳密共通実新規数']}",r["共通出口属性差数"],"/".join(number(v["共通出口差円"]) for v in r["費用別"]),*[str(r[k]["完結取引数"])+"・"+"/".join(number(r[k][f"追加{f}pt純損益円"]) for f in (0,5,10)) for k in ("左のみ","右のみ")],"/".join(number(v["総差円_右引く左"]) for v in r["費用別"])] for r in (*data["実参加比較"],*data["役割別実参加比較"])])
    text+=G.table(["比較/期間","左のみの相手取扱","右のみの相手取扱"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]],G.describe(r["左のみの相手取扱"]),G.describe(r["右のみの相手取扱"])] for r in data["実参加比較"]])
    text+="## 仮250と役割別実回収・利益保護\n\n仮250は実返済後も追う経路。実保有MFE250、実回収、起動後費用赤字とは別である。名目床は費用後同値や遅延後同値約定を保証しない。\n"
    text+=G.table(["運用/役割","期間","実完結","対応仮250/判定前返済","実MFE250","起動/基準赤字","同値費用/不利/正益費用負け"],[[r["候補ID"]+"/"+r["役割"],PERIOD_NAMES[r["期間"]],r["完結取引数"],f"{r['対応仮250数']}/{r['仮250判定前返済数']}",r["実保有MFE250数"],f"{r['起動数']}/{r['起動後基準赤字数']}",f"{r['名目同値費用赤字数']}/{r['不利返済赤字数']}/{r['正名目利益の基準費用負け数']}"] for r in (*data["候補別回収"],*data["役割別回収"])])
    text+="以下の同値未満/最終線不足は追尾起動後の取引に限る。\n"
    trades=G.read_csv(study/"固定候補_取引.csv");floors=[]
    for cid in CANDIDATES:
        for period in PERIODS:
            own=[r for r in trades if r["手法"] == cid and r["期間"] == period and r["追尾起動"] == "True"]
            below=sum((1 if r["方向"] == "買い" else -1)*(float(r["返済価格"])-float(r["新規価格"])) < 0 for r in own)
            delta=[float(r["最終追尾から実返済方向差pt"]) for r in own if r["最終追尾から実返済方向差pt"] not in ("","None")]
            floors.append([cid,PERIOD_NAMES[period],len(own),below,sum(v < 0 for v in delta),number(min(delta) if delta else None)])
    text+=G.table(["運用","期間","起動済み","実同値未満","最終線未満","最終線から返済の最小差pt"],floors)
    return text+G.table(["運用","期間","注意/未解消/EOF","基準観測円","基準確定円"],[[r["候補ID"],PERIOD_NAMES[r["期間"]],f"{r['品質注意場数']}/{r['未解消場数']}/{r['EOF期限未達場数']}",number(r["観測純額円"]["0"]),BASE.confirmed(r["全体確定対象円"]["0"],r["品質注意場数"])] for r in data["品質と確定額"]])


def run(study: Path, work: Path, output: Path) -> list[Path]:
    """全証明完成後に保存値だけから版4の正式二MDを表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。結果前に実測を生成しない。
    """
    config,report,rules,entries,values,manifest=validate(study)
    output.mkdir(parents=True,exist_ok=True)
    readme,mapping=output/"README.md",output/"設定と結果.md"
    common,catalog=settings(rules),V4.load_catalog()
    diagnostic=G.read_json(proof_path(study,work,"対応診断.json"))
    intro="固定42A0全245純をIDだけ変えてD0完全対照とし、D1は当場現前CMF21の共通準備、D2は実side×CMF現前差>0strictを追加する。同じ価格b/j・実T順行R反転・MACD・j時計/jATR・三XFを保持。三切替入口/三運用/六実役割群、カタログ版4・54手法×9尺度。全66場（学習40・選択24・既使用11/4Day/Night2）は既使用の開発で、未使用確認ではない。未予約11/5Dayの内容は未読で温存する。\n\n"
    conclusion=f"**支持付き入口70目標は{report['入口70目標達成数']}/3、費用資格は{report['費用資格数']}/3、現在費用資格は{report['現方針費用資格数']}/3、採用資格は{report['採用資格数']}/3。**\n\n"
    for policy in POLICIES:
        conclusion+=policy+"XF："+"、".join(PERIOD_NAMES[p]+"は250先着率"+G.pct(entries["3分_"+policy][p]["確認率"])+"・追加5pt平均"+number(values["3分_"+policy+"_XF"][p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。\n\n"
    entry=entries["3分_D2"]
    conclusion+="D2学習仮約定"+str(entry["学習"]["約定候補数"])+"件/支持下限"+str(config["入口支持"]["学習"]["約定候補数"])+"件、学習j間引き"+str(entry["学習"]["30分間引き_順行先着"])+"/"+str(entry["学習"]["30分間引き_約定候補数"])+"="+G.pct(entry["学習"]["30分間引き_確認率"])+"。両期入口支持は"+("充足" if entry["入口支持"] else "未達")+"。条件選択や既使用後続2場だけの高率/黒字を両期資格へ代用しない。\n\n"
    for title in ("現前CMF準備追加","CMF変化方向追加"):
        groups=[r for r in diagnostic["実参加比較"] if r["比較"] == title]
        conclusion+=title+"：実共通は学習/選択/後続"+"/".join(str(r["厳密共通実新規数"]) for r in groups)+"件、右だけ実参加"+"/".join(str(r["右のみ"]["完結取引数"]) for r in groups)+"件。全額差/平均と共通出口/片側参加は別に評価する。\n\n"
    for period in PERIODS[:2]:
        left,right=(values[cid][period]["運用"] for cid in CANDIDATES[1:])
        conclusion+=PERIOD_NAMES[period]+"のD1→D2追加5pt平均は"+number(left["追加5pt平均円"])+"→"+number(right["追加5pt平均円"])+"円。水準条件/I寄与の新ANDや別h待機の成績ではない。\n\n"
    warnings=[cid+"/"+PERIOD_NAMES[p]+"="+str(values[cid][p]["運用"]["品質注意場数"])+"場" for cid in CANDIDATES for p in PERIODS if values[cid][p]["運用"]["品質注意場数"]]
    conclusion+=("品質注意は"+"、".join(warnings)+"。該当期の金額/差額は観測値で、全体確定nullを観測値で置換しない。\n\n") if warnings else "全案各期の品質注意0。実micro約定や将来経路の品質を保証しない。\n\n"
    logic="## 固定価格対照と新しい準備/差\n\nD0は固定42A0の全245純13列、同時計11先着、全66ledger/traceをIDだけ正規化して完全同値にする。旧42全424jは別の保存母集合で、WAIT/旧A0不採用をCMFから救済しない。旧一監視/used/6足/最初の対象再テスト、通常b+1時点対象外でも寿命に数える最短b+2〜6、T/R実方向とMACDを保持する。新価格母集団を作らず、新しいh待機は実行しない。\n\nD1は当場隣接現前CMF21の22公開連続完全足・全22q完全有限非負・各幅正・両総q正。最古qも必要で36VRの準備とは異なる。完全0qは有効、零幅/総q0/未準備を0補完せず、現が悪いとき古正常/前場へfallbackしない。数量不完全で旧価格親を取消さない。\n\n"
    formula="## 精密差と窓入替えの分解\n\nm_i=(2C−H−L)/(H−L)、N=Σm_iq_i、Q=Σq_i、F=N/Q。元floatHLCq各FractionからF現/前と差を定義する。ΔF=F現−F前、I=q現(m現−F前)/Q現、O=−q落(m落−F前)/Q現、ΔF=I+O。落足はj−21で、差の交差積N現Q前−N前Q現の符号とも精密照合する。表示float差/epsilonは採否に使わず、差0は不採用。\n\n共通20足総q0でも両21総q正なら定義可能で、中間比を作って不要な欠測を生まない。前窓の最古m−1/q1・他20m0/q1へ当足m0/q0が入る人工例では、F前−1/21→現0、差+1/21、I0/O+1/21。m0/q1を入れるとI=1/441/O=20/441で、I正は当足m正を意味しない。mが全1/2なら量が変わっても差0となり、価格上昇と両立する。\n\nIは前値基準の相対CLVと量/分母希釈を含み新買い圧力でなく、Oは売り手の退出人数でない。価格ギャップ/close-to-close方向も直接測らない。CMFと差/寄与は同じ価格量加工なので独立票へ足し合わせず、現水準/I正/寄与大小を新ANDしない。\n\n"
    clocks="## 時計・共通準備内shadow・直接先着\n\n新規要求は固定42と同じj公開key、30分間引きの主もjで、bは対応出典だけ。D2は同時点の選別で、確認まで待って入口を早めたり遅らせたりする試行ではない。現水準と差は同じD1準備に揃えて正/0/負と重複を記述し、旧42A2全体との差を純粋な水準対差の効果にしない。水準だけ/寄与だけの新運用を実行していない。\n\n各新caseは全実sideを原正常BBOの要求+1秒/TTL30の最初新規から125/250へ独立直接再走査する。旧11値の同値を直接監査の代用とせず、逆sideの補数・別h時計・b以前のMFEへ流用しない。仮250は実返済後まで追う経路で、実保有MFE/回収と分ける。\n\n"
    protection="## 同じXFと費用・実占有\n\nmicro1枚代理/倍率10円/pt/呼値5pt/片道fee11円、新規+1秒TTL30/一pending一建玉。現在正常返済BBOの実side×(mark−entry)pt×10円/pt−122円>0strictで起動し、現j入口ATR固定D=max(5,ceil(ATR/5)*5)、MFE−D/最低名目entry床/非緩和/返済pending凍結を保持。CMF/I/O/bATRを追尾幅に使わない。hard125/TP250/期限・場内完結は不変。\n\n名目床は費用後同値や遅延後同値約定を保証しない。追加0/5/10は同約定への費用負荷で起動参照5ptを変えない。価格時計は受信時計でなく、ラージBBO代理は実microキュー/数量/部分約定を保証しない。\n\n"
    limits="## 限界と再利用\n\n現前準備の除外と差符号選別、純subsetとactual追加、総額と平均、切替全体と六役割群を分ける。全額差=共通出口差＋右のみ額−左のみ額を全費用で照合し、共通0の出口差0は比較対象なし。混合支持や率改善を片役割の支持/改善へ代用しない。\n\n全66場既使用。未予約11/5Day内容を開かず、未使用確認と呼ばない。旧42水準条件の期間不一致は新差が改善する証明や窓落ちが損失原因だった証拠でない。主要条件変更は新試行へ分け、支持70/費用/品質null規約を緩めない。\n\n"
    audit_text,audit_paths=audits(study,work,readme)
    table=result_tables(report,entries,values)
    links=" / ".join(G.link(study/n,readme) for n in ("計画.md","条件.json","固定.json","結果.json","入口参照.json","対照参照.json","指標参照.json","D0対照同値.json"))
    summary="# 試行00043：再テスト時のCMF変化方向\n\n"+intro+links+" / "+G.link(mapping,readme)+"\n\n"+conclusion+table+diagnosis(study,work,readme)+logic+formula+clocks+protection+limits+audit_text
    mapped="# 試行00043：設定と結果\n\n"+intro+conclusion+G.link(V4.MASTER,mapping,"コピー元汎用表・版4")+" / "+G.link(readme,mapping)+"\n\n"
    mapped+="## 手法×時間スケール\n\n54手法×9尺度・版4不変。R0=D0XF固定42A0、R1=D1XF現前準備、R2=D2XF差方向。V06の準備S04/差S05/水準とI-O診断S06を分け、現水準/I正を採用条件にしない。\n\n"+V4.matrix(catalog,mapping,common)
    mapped+="## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],[[r["設定ID"],"/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]),r["短記"],r["説明"],"・".join(r["適用評価"])] for r in common])
    mapped+="## 全固定条件\n"+G.table(["項目","固定値"],[[k,G.describe(v)] for k,v in config.items()])
    mapped+="## 三評価の定義\n"+G.table(["評価","候補","集合役割","入口支持","70目標","費用資格","採用資格"],[[r["評価ID"],r["候補ID"],"切替","充足" if values[r["候補ID"]]["入口支持"] else "未達","達成" if values[r["候補ID"]]["70目標"] else "未達","充足" if values[r["候補ID"]]["費用資格"] else "未達","充足" if values[r["候補ID"]]["採用資格"] else "未達"] for r in rules])
    mapped+=table+logic+formula+clocks+protection+limits+audits(study,work,mapping)[0]
    names=("入力台帳.json","入口参照.json","対照参照.json","指標参照.json","D0対照同値.json","準備参照.json","一覧.resources.json","固定候補_取引.csv","固定候補_注文.csv","全候補_場別.csv","入力品質.json","作業成果物.json")
    sources=[HERE/n for n in ("README.md","入口.py","運用.py","検証.py","合成検証.py","独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py","レポート.py") if (HERE/n).is_file()]
    docs=[ROOT/n for n in ("docs/technical-analysis/指標/CMFの変化と窓の入替え.md","docs/technical-analysis/指標/CMF.md","docs/technical-analysis/指標/MACD.md","docs/technical-analysis/指標/ATR.md","docs/README.md","docs/議論/README.md","docs/議論/PDCAの進行.md","docs/議論/テクニカル手法の検証範囲と次の複合候補.md","study/README.md") if (ROOT/n).is_file()]
    if COMMON.is_file():docs.append(COMMON)
    viewing="## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n,readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p,readme) for p in sources)+"。\n\n"
    viewing+="旧42全5大明細/対照2/固定29数値1を三小参照で共有。新大明細は発動判定/最小case/全運用/追尾の4gzipだけ。全CMFは準備hash/count、現前F/Δ/I/O/入落m,q限定出典は判定へ一回保存し旧母監視を複製しない。Viewerは三運用各66場の198資源と3代表。--prepareは旧純対照/CMF現前/差/採否だけで先着/運用/PnLなし、正式結果/部分gzipを上書きしない。\n\n保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/CMF変化/レポート.py\n```\n\n"
    if COMMON.is_file():viewing+=G.link(COMMON,readme,"共通知見")+"。\n\n"
    helpers=[ROOT/"scripts"/name/"レポート.py" for name in ("再テスト量方向","回帰突破","構造判別","量比反転","回復監視","突破指値","終値位置","CCI突破","一目基準線","反転確認時計","SAR持続","終値切替")]
    paths=[Path(__file__),*helpers,ROOT/"scripts/レポート/設定結果レポート.py",ROOT/"scripts/レポート/カタログ版4.py",V4.BASE,V4.CATALOG,V4.MASTER,V4.TEXTBOOK,manifest,PREVIOUS/"固定.json",PREVIOUS/"条件.json",
        *[study/n for n in ("計画.md","条件.json","固定.json","結果.json",*names) if (study/n).is_file()],NUMERIC_STUDY/"条件.json",EXIT_STUDY/"条件.json",*sources,*docs,*audit_paths]
    for path in (work/"診断予定.json",ROOT/"work/CMF変化43の記録案.md",ROOT/"work/CMF変化43の事前案.md",ROOT/"work/CMF変化43の独立案.md"):
        if path.is_file():paths.append(path)
    for path,body in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(body+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """全証明完成後の保存二MDだけを再表示する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。主/独立/監査/診断を起動しない。
    """
    parser=argparse.ArgumentParser(description="固定A0対照とCMF現前変化・保存帳票")
    parser.add_argument("--study",type=Path,default=STUDY);parser.add_argument("--work",type=Path,default=WORK);parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(),args.work.resolve(),(args.output or args.study).resolve())))


if __name__ == "__main__":main()
