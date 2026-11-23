"""突破再テストとCMF三案を、保存証明と版4の二MDへ表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00042_突破再テストと数量加重終値位置"
WORK = ROOT/"work/再テスト量方向/00042"
NUMERIC_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
COMMON = ROOT/"docs/議論/突破の再テストを数量加重終値位置で判別する.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS,("学習40場","条件選択24場","既使用11/4Day/Night2場")))
POLICIES, ROLES = ("A0","A1","A2"), ("順行","反転")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
SPEC = importlib.util.spec_from_file_location("再テスト42の固定41表示補助",ROOT/"scripts/回帰突破/レポート.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
G,P,F,number = BASE.G,BASE.P,BASE.F,BASE.number
VSPEC = importlib.util.spec_from_file_location("再テスト42の独立版4表",ROOT/"scripts/レポート/カタログ版4.py")
V4 = importlib.util.module_from_spec(VSPEC)
sys.modules[VSPEC.name] = V4
VSPEC.loader.exec_module(V4)


def definitions(config: dict) -> list[dict]:
    """三つの切替候補を、準備と値の三評価へ対応する。

    引数: config(dict)は42条件。
    返り値: list[dict]はR0〜R2。実T/Rは別役割として保持する。
    """
    if config["戦略"] != list(POLICIES) or config["時間足分"] != [3] or config["運用組合せ"] != [{"戦略":p,"出口ID":"XF"} for p in POLICIES]:
        raise ValueError("三切替入口/三XF以外")
    return [{"評価ID":"R"+str(i),"候補ID":cid,"入口":{"入口ID":"3分_"+p,"戦略":p,"時間足分":3,"名称":p,"役割":"切替","複合本命":True},"出口":{"出口ID":"XF"}} for i,(p,cid) in enumerate(zip(POLICIES,CANDIDATES))]


def validate(study: Path) -> tuple:
    """新母集団/三切替/六役割・支持費用・指標参照と固定を確認する。

    引数: study(Path)は正式先。
    返り値: tupleは条件/結果/評価/入口/運用/台帳。結果なしでは生成しない。
    """
    for name in ("計画.md","条件.json","固定.json","結果.json","指標参照.json"):
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
    return config,report,rules,entries,values,manifest


def settings(rules: list[dict]) -> list[dict]:
    """価格監視・勢い・CMF準備/値・共通執行を版4へ役割分けする。

    引数: rules(list[dict])は三評価。
    返り値: list[dict]は12設定。単足CLV/旧OBV/回帰/上位を採用にしない。
    """
    groups=[
        (["P07"],["m03"],rules,"登録b：前20高安strict終値突破","当場公開連続有効21足。旧R/L/B/元sを固定し、登録だけでは注文しない。数量/ATR/MACDの値で登録を間引かない"),
        (["P10"],["m03"],rules,"一監視/used(s,B)/次6足・最初の対象再テスト一回","start_j>b.confirm/key後strict。通常b+1対象外でも寿命に数え最短b+2〜6、消費/取消同足の再登録なし"),
        (["P10"],["m03"],rules,"外側T=d=s/旧strict帯内R=d=−s/元端等号WAIT","反対端終値取消優先。最初jを勢い/量不成立でも消費、取り直し/後足確認/自動ドテンなし"),
        (["I03"],["m03"],rules,"当時j：実side×MACDヒスト一足差>0strict","固定29中心化12/26/9、当場隣接現前有限。元登録方向と反転Rの実方向を区別"),
        (["I09"],["m03"],rules,"共通：現jATR14正・入口D固定","数量準備をA0へ先に課さない。bATR/前ATR/CMFを出口距離へ使わない"),
        (["V06"],["m03"],rules[1:],"A1準備：CMF21連続/全21q完全/各幅正/総q正","数量q0有効、H=Lはq0でもCLV未定義。数量欠測/21本不足/零幅/総q0を方向0と混ぜない"),
        (["V06"],["m03"],rules[2:],"A2値：実side×CMF21>0strict","CMF=ΣCLV*q/Σq、元HLCq各Fractionの精密符号。0不採用・表示epsilon/追加閾値なし。勢い/足位置と独立した票にしない"),
        (["B01"],["m03"],rules,"新要求j30分間引き主/b診断・残60分/遅延30秒","集合切替/実T順行R反転、全採否後deepcopy/live13列、未来labelなし。同key複数は同方向も全見送り"),
        (["B01"],["tick"],rules,"市場+1秒/TTL30・一pending/一建玉","純価格監視は実建玉と独立。実抑止を次の空き時計へ延期しない"),
        (["I09","C06","E02"],["tick"],rules,"XF：現在返済BBO利益円−122>0strict","参照片道5pt/往復fee22、現j入口ATR固定D/MFE−D/最低名目entry床・非緩和・pending凍結"),
        (["E01"],["tick"],rules,"新jの実side正常BBOから125/250直接判定","旧41label/全属性対照なし。bや待機中高安を新規後MFE/MAEへ加えず、未発動の仮250は未計算"),
        (["V06","P05","E01","B01"],["m03","tick"],rules,"診断のみ：等量CLV符号/準備/実参加/回収","CMF対単位量平均は同じ21窓の保存値だけ。全21q正同値は同値保証の十分条件で非必要。閾値/単位量運用を追加しない"),
    ]
    return [{"設定ID":f"S{i:02d}","手法ID":m,"尺度ID":sc,"短記":short,"説明":detail,"結果短記":"・".join(r["評価ID"] for r in applies),"適用評価":[r["評価ID"] for r in applies]} for i,(m,sc,applies,short,detail) in enumerate(groups,1)]


def proof_path(study: Path, work: Path, name: str) -> Path:
    """正式小証明を優先し、work正本とのbyte差を拒否する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは同版の保存証明。
    """
    return BASE.proof_path(study,work,name)


def audits(study: Path, work: Path, output: Path) -> tuple:
    """人工・純準備・新監視/CMF・直接先着・実会計/追尾を分ける。

    引数: study/work/output(Path)は保存/表示先。
    返り値: tupleは検査表と出典。市場や監査を起動しない。
    """
    rows,paths=[],[]
    for name,title in (("合成検証.json","人工監視/時点/一回消費/精密CMF/鏡像/固定guard"),("独立監査.json","新case集計/Decimal会計/全資源"),("状態独立確認.json","全登録監視/最初j/CMF/全採否/新直接先着"),("追尾独立確認.json","三XFの全保有/費用起動/名目床/最初要求"),("対応診断.json","登録と発動/CMF準備と値/実参加と役割別回収"),("Viewer照合.json","三運用の代表Viewer")):
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
    rows.extend((["固定前主準備・登録/監視/CMF/hash/純信号","66場・非損益",66,G.link(main,output)],["固定前独立・数値/新監視/CMF/三採否","一致/合格",number(independent["照合項目数"]),G.link(ip,output)]))
    for name in ("会計人工接続.json","保存物読取補足.json"):
        if not ((study/name).is_file() or (work/name).is_file()):
            continue
        path=proof_path(study,work,name);data=G.read_json(path)
        if data["全件一致"] is not True or data["不一致数"] != 0:
            raise ValueError("小証明未完")
        if name == "会計人工接続.json" and any(G.sha(ROOT/n) != h for n,h in data["コードSHA256"].items()):
            raise ValueError("会計人工の版差")
        rows.append([name+"・主最終人工と別","一致/合格",number(data["照合項目数"]),G.link(path,output)]);paths.append(path)
    text="## 検査の状態\n\n固定29はOHLC/ATR/中心化MACD/Qの出典。42で原入力からの登録一監視/最初対象j/精密CMF/全採否/新case直接先着を独立確認する。旧41の登録/先着/全運用同値対照は使わない。精密CMF/価格/時点/全採否は厳密、ATR/ヒスト等の表現差は正式計画の対象だけを許容し、採否epsilonへ使わない。保存正本SHAと独立再算の生float SHAを混同しない。準備は先着/運用/PnLなし。\n"
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


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """登録監視・数量準備/値・混合占有・役割別回収を保存診断から表示する。

    引数: study/work/output(Path)は保存/表示先。
    返り値: strは診断本文。全panel/個別traceを転記しない。
    """
    path=proof_path(study,work,"対応診断.json");data=G.read_json(path)
    text="## 登録・最初の対象再テスト・三採否\n\n"+G.link(path,output)+"が正本。全登録候補、受理親b、最初j、純要求、仮約定、実参加を別分母にする。監視中/used拒否と、実pending/建玉抑止を混ぜない。\n"
    text+=G.table(["期間","全登録候補/受理b/最初j","監視動作","登録見送り理由・重複あり","終了理由・重複あり"],[[PERIOD_NAMES[r["期間"]],f"{r['登録候補数']}/{r['登録受理数']}/{r['最初j数']}",G.describe(r["動作別"]),G.describe(r["見送り理由別_重複あり"]),G.describe(r["終了理由別_重複あり"])] for r in data["登録と監視"]])
    text+=G.table(["期間","構造","最初j/M/時間可","A0/A1/A2要求"],[[PERIOD_NAMES[r["期間"]],r["構造区分"],f"{r['最初j数']}/{r['M準備数']}/{r['時間遅延可数']}","/".join(str(r[p+"純入口数"]) for p in POLICIES)] for r in data["構造と三入口"]])
    text+=G.table(["比較/期間/役割","保持要求/仮約定・250率","除外要求/仮約定・250率","純追加","除外CMF理由・重複あり"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]]+"/"+r["役割"],*[f"{r[k]['候補数']}/{r[k]['約定候補数']}・{r[k]['順行先着']}/{r[k]['約定候補数']}={G.pct(r[k]['確認率'])}" for k in ("保持入口","除外入口")],r["新規追加入口数"],G.describe(r["除外CMF理由別_重複あり"])] for r in data["入口追加比較"]])
    text+="## CMFと単位量CLV平均・待機時計\n\n分母は同じjのA1純要求。実量CMFと同じ21窓の単位量CLV平均の実方向符号を比較するだけで、単位量戦略の運用/新gateは実行しない。全21qが同じ正量なら同じ平均になる十分条件で、必要条件ではない。量が不均一でも同じ値/符号になり得る。\n"
    text+=G.table(["期間/役割","実量/単位量の実方向","要求/仮約定","250/仮約定・率"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["実量CMF実方向"]+"/"+r["単位量CLV実方向"],f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["CMFと単位量CLV符号"] if r["候補数"]])
    text+=G.table(["期間/役割","A1要求/21量正同値/旗なし"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],f"{r['A1要求数']}/{r['全21量正同値数']}/{r['等量旗未保存数']}"] for r in data["等量十分条件"]])
    text+="b→j終値差は既知終値間の記述で、未計算のb仮約定価格との改善や待機の収益効果ではない。未発動親が250へ進んだ取り逃しは未検証。通常b+1は時点対象外でも寿命に数え、最短b+2〜6の最初の対象足再テストを扱う。\n"
    text+=G.table(["期間/構造","消費j","b→j秒中央値","経過足中央値","元s方向終値差中央値pt"],[[PERIOD_NAMES[r["期間"]]+"/"+r["構造区分"],r["最初j数"],number(r["bからj秒"]["中央値"]),number(r["経過足数"]["中央値"]),number(r["元s方向終値差pt"]["中央値"])] for r in data["登録から消費の時計"]])
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
    """正式保存値と証明だけから、版4の二MDを表示する。

    引数: study/work/output(Path)は正式/作業/出力先。
    返り値: list[Path]はREADME/設定と結果。結果前には生成しない。
    """
    config,report,rules,entries,values,manifest=validate(study)
    output.mkdir(parents=True,exist_ok=True)
    readme,mapping=output/"README.md",output/"設定と結果.md"
    common,catalog=settings(rules),V4.load_catalog()
    diagnostic=G.read_json(proof_path(study,work,"対応診断.json"))
    intro="新しい3分前20高安終値突破を登録bとし、固定水準の最初の対象足再テストjで外側T順行/旧strict帯内R反転/WAITへ分ける。A0は当時jの実方向MACDヒスト差、A1はCMF21準備、A2は実方向CMF符号を追加。三切替入口・三XF運用・六実役割群、カタログ版4・54手法×9尺度。全66場（学習40・選択24・既使用11/4Day/Night2）は既使用の開発で、未使用確認ではない。旧41へのAND追加でも旧label流用でもない。\n\n"
    conclusion=f"**支持付き入口70目標は{report['入口70目標達成数']}/3、費用資格は{report['費用資格数']}/3、現在費用資格は{report['現方針費用資格数']}/3、採用資格は{report['採用資格数']}/3。**\n\n"
    for policy in POLICIES:
        conclusion+=policy+"XF："+"、".join(PERIOD_NAMES[p]+"は250先着率"+G.pct(entries["3分_"+policy][p]["確認率"])+"・追加5pt平均"+number(values["3分_"+policy+"_XF"][p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。\n\n"
    e=entries["3分_A2"]
    conclusion+="A2学習仮約定"+str(e["学習"]["約定候補数"])+"件に対し支持下限"+str(config["入口支持"]["学習"]["約定候補数"])+"件、学習j間引き"+str(e["学習"]["30分間引き_順行先着"])+"/"+str(e["学習"]["30分間引き_約定候補数"])+"="+G.pct(e["学習"]["30分間引き_確認率"])+"。両期入口支持は"+("充足" if e["入口支持"] else "未達")+"。条件選択期の率上昇や既使用後続2場の黒字を、両期支持/70/費用資格へ代用しない。\n\n"
    for period in PERIODS[:2]:
        left,right=(values[cid][period]["運用"] for cid in CANDIDATES[1:])
        conclusion+=PERIOD_NAMES[period]+"のA1→A2追加5pt平均は"+number(left["追加5pt平均円"])+"→"+number(right["追加5pt平均円"])+"円。先着率、総額、平均、役割構成を別に評価する。\n\n"
    for title in ("CMF準備追加","CMF方向追加"):
        groups=[r for r in diagnostic["実参加比較"] if r["比較"] == title]
        conclusion+=title+"：実共通は学習/選択/後続"+"/".join(str(r["厳密共通実新規数"]) for r in groups)+"件、右だけ実参加"+"/".join(str(r["右のみ"]["完結取引数"]) for r in groups)+"件。共通出口と片側参加、全額と一取引平均を分ける。\n\n"
    warns=[cid+"/"+PERIOD_NAMES[p]+"="+str(values[cid][p]["運用"]["品質注意場数"])+"場" for cid in CANDIDATES for p in PERIODS if values[cid][p]["運用"]["品質注意場数"]]
    conclusion+=("品質注意は"+"、".join(warns)+"。該当期の円と全額差は観測値で、全体確定nullを観測額で置換しない。\n\n") if warns else "全案各期の品質注意0。実micro約定や将来の経路品質を保証しない。\n\n"
    logic="## 独自の一監視・最初の対象再テスト\n\n当場の前20公開連続有効3分の旧R/Lを現Cがstrict突破したbでR/L/B/元sを固定。一監視でused(s,B)を登録時消費し、監視中の別bと同水準を抑止、消費/取消同足の登録はしない。登録は注文でなく、数量/MACD/ATR値で登録を間引かない。新しいBの別登録は可能で、同じトレンドの参加を全て一回に制限した意味ではない。\n\n"
    logic+="寿命はb次1..6足。start_j>b.confirmかつ公開key後strictの対象足だけ高安を使う。通常b+1は対象外でも寿命に数え、最短b+2〜6の『最初の対象足再テスト』である。反対端終値取消を先に、買Low<=B/売High>=Bを初touchとする。外側終値Tは実side=s/順行、旧L<C<R strictならRは実side=−s/反転、元端等号WAIT。指標/時間が悪くても一回消費して後足へ取り直さず、自動ドテンしない。\n\n"
    logic+="不正/公開不備/欠枠/期限→寿命超過→対象時点→反対端終値→初touch→技術/時間採否の順。ヒゲだけの反対端到達を取消へ加えず、足中高安の順序を推定しない。登録snapshotは登録actionへ一回保存し、最終足登録から即場末取消でも正式親出典を保持する。\n\n"
    cmf="## CMF準備と値を分ける\n\nCLV_i=(2C−H−L)/(H−L)、CMF21=Σ(CLV_i*q_i)/Σq_i。元floatH/L/C/qを各々Fraction化し、加重和/総量/CMFの精密分子分母で符号を判定する。全21足の同場連続公開完全足・各幅正・全q基準完全/有限非負・総q正がA1準備。完全0qは有効だが総q0は未定義、H=Lはq0でもCLV未定義で0補完しない。数量不完全や零幅はCMF窓だけを切り、価格監視を数量理由だけで取消しない。\n\n"
    cmf+="A0は現jATR正/当場隣接現前ヒスト有限・実side×δH>0、A1がCMF準備、A2が実side×CMF>0strict。0不採用/epsilonや新閾値なし。同じjで準備と符号を追加するためCMF待ちの時計延長はない。CMFは観測量で加重した足内終値位置であり、真の売買側flow・新規参加者・機関注文や資金流入を直接測らない。前終値ギャップを含まず、古い足の窓落ちでも変化する。\n\n"
    clocks="## 二つの時計・新先着・責任分界\n\n新要求jの30分間引きを主、親bは対応診断だけ。b→j終値差を、未計算のb仮約定からの価格改善や待機収益へ読み替えない。未発動親の仮250は未検証で、旧41labelから取り逃し利益を作らない。T/R全新caseをj要求+1秒以降TTL30の最初正常BBOから実sideの125/250へ直接評価し、bや待機中高安を新規後MFE/MAEへ含めない。反転Rのlabelを元方向の補数で作らない。\n\n"
    clocks+="局所価格/CMFは当場公開・完全180秒・missing0・連続index/end/key。固定29ATR/MACD数値銀行の同限月carry/reset/NP内部更新と、局所不投入を分ける。CMF全panelは準備hash/countのみ、正式はjに必要な出典へ限定。原板/旧context/全CMFを複製せず、後段診断は保存加重和等の内部算術だけで窓/指標/先着を再計算しない。全採否/競合後deepcopy/live純13列へ未来labelを混ぜない。\n\n"
    protection="## 現在XF・費用・回収の限界\n\nmicro1枚代理/倍率10円/pt/呼値5pt/片道fee11円、新規要求+1秒/TTL30、一pending/一建玉。現在正常返済BBOの実方向価格差pt×10円/pt−122円>0strictで起動し、現j入口ATR固定D=max(5,ceil(ATR/5)*5)、MFE−D/最低名目entry床/非緩和/pending凍結。過去MFEだけでは起動せず、bATR/CMFを出口距離に使わない。hard125/TP250/期限を維持する。\n\n名目床は費用後同値や遅延後同値約定を保証しない。追加0/5/10は同約定への費用負荷で参照5を変えない。デイ入力08:45〜15:40/停止15:25/強制15:35、ナイト17:00〜05:55/停止05:40/強制05:50。価格時計と受信時計、ラージBBO代理と実microキュー/部分約定は別である。\n\n"
    limits="## 再利用と限界\n\n同じ新基準A0から数量準備A1と値A2を分ける。混合全体と六実役割群を分け、混合支持を片役割支持に代用しない。等量CLV比較は保存符号の説明だけで、単位量運用やT/R単独運用は実行していない。旧23/24の再テスト思想、33CLV、35待機、37T/R分類と重なるが、期間/発動/時計/母集団/出口の差もありCMF単独の新理論や因果効果と呼ばない。\n\n全66場は既使用。重複窓/監視の標本独立性を仮定せず、主率/間引き/日/場/支持70/費用を緩めない。未使用確認、将来の高率や収益、損失原因の証明とはしない。主要条件変更は新試行へ分ける。\n\n"
    table,(audit_text,audit_paths)=result_tables(report,entries,values),audits(study,work,readme)
    links=" / ".join(G.link(study/n,readme) for n in ("計画.md","条件.json","固定.json","結果.json","指標参照.json"))
    summary="# 試行00042：突破再テストと数量加重終値位置\n\n"+intro+links+" / "+G.link(mapping,readme)+"\n\n"+conclusion+table+diagnosis(study,work,readme)+logic+cmf+clocks+protection+limits+audit_text
    mapped="# 試行00042：設定と結果\n\n"+intro+conclusion+G.link(V4.MASTER,mapping,"コピー元汎用表・版4")+" / "+G.link(readme,mapping)+"\n\n"
    mapped+="## 手法×時間スケール\n\n54手法×9尺度。R0=A0XF価格再テスト/勢い、R1=A1XF数量準備、R2=A2XF実量符号。V06の準備S06/値S07/診断S12を分け、旧OBV/VR/MFI/RVOL/OLS/上位/単足CLV/TR上限を採用扱いにしない。\n\n"+V4.matrix(catalog,mapping,common)
    mapped+="## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],[[r["設定ID"],"/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]),r["短記"],r["説明"],"・".join(r["適用評価"])] for r in common])
    mapped+="## 全固定条件\n"+G.table(["項目","固定値"],[[k,G.describe(v)] for k,v in config.items()])
    mapped+="## 三評価の定義\n"+G.table(["評価","候補","集合役割","入口支持","70目標","費用資格","採用資格"],[[r["評価ID"],r["候補ID"],"切替","充足" if values[r["候補ID"]]["入口支持"] else "未達","達成" if values[r["候補ID"]]["70目標"] else "未達","充足" if values[r["候補ID"]]["費用資格"] else "未達","充足" if values[r["候補ID"]]["採用資格"] else "未達"] for r in rules])
    mapped+=table+logic+cmf+clocks+protection+limits+audits(study,work,mapping)[0]
    names=("入力台帳.json","指標参照.json","準備参照.json","一覧.resources.json","固定候補_取引.csv","固定候補_注文.csv","全候補_場別.csv","入力品質.json","作業成果物.json")
    sources=[HERE/n for n in ("README.md","入口.py","運用.py","検証.py","合成検証.py","独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py","レポート.py") if (HERE/n).is_file()]
    docs=[ROOT/n for n in ("docs/technical-analysis/指標/CMF.md","docs/technical-analysis/指標/MACD.md","docs/technical-analysis/指標/ATR.md","docs/technical-analysis/01_チャートの読み方と仮説化.md","docs/README.md","docs/議論/README.md","docs/議論/PDCAの進行.md","docs/議論/テクニカル手法の検証範囲と次の複合候補.md","study/README.md") if (ROOT/n).is_file()]
    if COMMON.is_file():docs.append(COMMON)
    viewing="## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n,readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p,readme) for p in sources)+"。\n\n"
    viewing+="新大明細は登録監視/発動判定/最小case/全運用/追尾の5gzip。全CMFは準備hash/countだけでj出典を正式保存、旧全contextを複製しない。Viewerは各3運用66場の198資源と3代表。--prepareは新登録監視/CMF/三採否/純信号だけで先着/運用/PnLなし。正式は既存結果/部分gzipを上書きしない。再現はコードREADME、保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/再テスト量方向/レポート.py\n```\n\n"
    if COMMON.is_file():viewing+=G.link(COMMON,readme,"共通知見")+"。\n\n"
    helpers=[ROOT/"scripts"/name/"レポート.py" for name in ("回帰突破","構造判別","量比反転","回復監視","突破指値","終値位置","CCI突破","一目基準線","反転確認時計","SAR持続","終値切替")]
    paths=[Path(__file__),*helpers,ROOT/"scripts/レポート/設定結果レポート.py",ROOT/"scripts/レポート/カタログ版4.py",V4.BASE,V4.CATALOG,V4.MASTER,V4.TEXTBOOK,manifest,
        *[study/n for n in ("計画.md","条件.json","固定.json","結果.json",*names) if (study/n).is_file()],NUMERIC_STUDY/"条件.json",NUMERIC_STUDY/"固定.json",EXIT_STUDY/"条件.json",*sources,*docs,*audit_paths]
    for path in (work/"診断予定.json",ROOT/"work/再テスト量方向42の記録案.md",ROOT/"work/再テスト量方向42の独立案.md",ROOT/"work/再テスト量方向42の事前案.md"):
        if path.is_file():paths.append(path)
    for path,body in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(body+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """全proof完成後の保存二MDだけをCLIで再表示する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。主/独立/監査を起動しない。
    """
    parser=argparse.ArgumentParser(description="最初再テストとCMF・保存帳票版4")
    parser.add_argument("--study",type=Path,default=STUDY)
    parser.add_argument("--work",type=Path,default=WORK)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    print("\n".join(str(p) for p in run(args.study.resolve(),args.work.resolve(),(args.output or args.study).resolve())))


if __name__ == "__main__":
    main()
