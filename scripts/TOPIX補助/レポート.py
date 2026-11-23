"""固定NK再テストとTOPIX補助三案を、保存証明と版4の二MDへ表示する。"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT/"study/00044_TOPIX方向とNK再テスト"
WORK = ROOT/"work/TOPIX補助/00044"
NUMERIC_STUDY = ROOT/"study/00029_BB内復帰とOBV非追随"
EXIT_STUDY = ROOT/"study/00033_CCI突破と足内終値位置"
COMMON = ROOT/"docs/議論/TOPIX方向でNK再テストを補助した比較.md"
PERIODS = ("学習", "条件選択", "後続検査")
PERIOD_NAMES = dict(zip(PERIODS,("学習40場","条件選択24場","既使用11/4Day/Night2場")))
POLICIES, ROLES = ("X0","X1","X2"), ("順行","反転")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
SPEC = importlib.util.spec_from_file_location("TOPIX44の固定41表示補助",ROOT/"scripts/回帰突破/レポート.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
G,P,F,number = BASE.G,BASE.P,BASE.F,BASE.number
VSPEC = importlib.util.spec_from_file_location("TOPIX44の独立版4表",ROOT/"scripts/レポート/カタログ版4.py")
V4 = importlib.util.module_from_spec(VSPEC)
sys.modules[VSPEC.name] = V4
VSPEC.loader.exec_module(V4)


ENTRY_STUDY = ROOT/"study/00042_突破再テストと数量加重終値位置"
PREVIOUS = ROOT/"study/00043_再テスト時のCMF変化方向"

def definitions(config: dict) -> list[dict]:
    """三つの切替候補を、準備と値の三評価へ対応する。

    引数: config(dict)は44条件。
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
    for name in ("計画.md","条件.json","固定.json","結果.json","入口参照.json","対照参照.json","指標参照.json","TOPIX入力参照.json","X0対照同値.json"):
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
        ref=F.F.F.F.validate_reference(study/filename,ENTRY_STUDY,previous_names)
        if ref["参照試行"] != "00042" or len(ref["共有明細"]) != count:
            raise ValueError("旧42参照範囲差")
    control=G.read_json(study/"X0対照同値.json")
    if control["全件一致"] is not True or control["旧先着全件同値"] is not True or control["場候補数"] != 66 or any(not r["全運用同値"] or not r["全追尾同値"] for r in control["照合"]):
        raise ValueError("旧42A0完全対照未完")
    for filename,key in (("入口参照.json","入口参照SHA256"),("対照参照.json","対照参照SHA256")):
        if control[key] != G.sha(study/filename):raise ValueError("対照参照版差")
    tpi_ref=G.read_json(study/"TOPIX入力参照.json")
    if tpi_ref["原板複製"] is not False or set(tpi_ref) != {"入力台帳","入力監査","入力予約","原板複製"}:
        raise ValueError("TOPIX入力参照範囲差")
    for name in ("入力台帳","入力監査","入力予約"):
        item=tpi_ref[name]
        if G.sha(ROOT/item["パス"]) != item["SHA256"]:raise ValueError("TOPIX入力参照版差")
    return config,report,rules,entries,values,manifest


def proof_path(study: Path, work: Path, name: str) -> Path:
    """正式小証明を優先し、work正本とのbyte差を拒否する。

    引数: study/work(Path)は保存先、name(str)は証明名。
    返り値: Pathは同版の保存証明。
    """
    return BASE.proof_path(study,work,name)


def audits(study: Path, work: Path, output: Path) -> tuple:
    """人工・純準備・TOPIX数値/跨時点・直接先着・実会計/追尾を分ける。

    引数: study/work/output(Path)は保存/表示先。
    返り値: tupleは検査表と出典。市場や監査を起動しない。
    """
    rows,paths,proofs=[],[],{}
    tpi_ref=G.read_json(study/"TOPIX入力参照.json")
    tpi_bindings={"TOPIX入力参照SHA256":G.sha(study/"TOPIX入力参照.json"),
        **{"TOPIX"+n+"SHA256":G.sha(ROOT/tpi_ref[n]["パス"]) for n in ("入力台帳","入力監査","入力予約")}}
    for name,title in (("合成検証.json","人工TOPIX/strict跨時点/非可視マスク/旧対照/固定guard"),("独立監査.json","新case集計/Decimal会計/全資源"),("状態独立確認.json","旧NK証明共有/TOPIX数値/跨時点/全採否/直接先着"),("追尾独立確認.json","三XFの全保有/費用起動/名目床/最初要求"),("対応診断.json","TOPIX準備/複合方向/事後時計/実参加と役割別回収"),("Viewer照合.json","三運用の代表Viewer")):
        path=proof_path(study,work,name);data=G.read_json(path);proofs[name]=data
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
        if name in ("独立監査.json","状態独立確認.json","追尾独立確認.json") and any(data.get(k) != h for k,h in tpi_bindings.items()):
            raise ValueError("TOPIX入力4SHAの証明接続差:"+name)
        rows.append([title,"一致/合格",number(count),G.link(path,output)]);paths.append(path)
    main,ip=work/"準備点検.json",proof_path(study,work,"独立準備点検.json")
    independent,lock,ref=G.read_json(ip),G.read_json(study/"固定.json"),G.read_json(study/"準備参照.json")
    if independent["全件一致"] is not True or independent["主準備SHA256"] != G.sha(main) or lock["主準備SHA256"] != G.sha(main) or lock["独立準備SHA256"] != G.sha(ip):
        raise ValueError("非損益準備join差")
    prepared=G.read_json(main)
    if any(data["ラベル計算"] is not False or data["損益計算"] is not False for data in (prepared,independent)):
        raise ValueError("準備は非先着/非PnL")
    if any(data.get(k) != h for data in (prepared,independent) for k,h in tpi_bindings.items()):
        raise ValueError("主独立準備のTOPIX入力4SHA差")
    definition=prepared["TOPIX数値定義"];definition_path=ROOT/definition["パス"]
    if G.sha(definition_path) != definition["圧縮SHA256参考"]:
        raise ValueError("TOPIX正本H小型定義の圧縮指紋差")
    if any(data["TOPIX数値定義"] != definition for data in (independent,proofs["状態独立確認.json"],proofs["追尾独立確認.json"])):
        raise ValueError("TOPIX正本H定義の主/独立/状態/追尾join差")
    definition_saved=study/"TOPIX数値定義.jsonl.gz"
    if G.sha(definition_saved) != definition["圧縮SHA256参考"]:
        raise ValueError("正式保全のTOPIX正本H定義とwork正本に差")
    paths.extend((definition_path,definition_saved))
    rows.append(["固定前TOPIX正本H小型定義・場/index/Hのみ","正本定義と独立生Hを分離",definition["行数"],G.link(definition_saved,output)])
    references=ref["参照"].values() if isinstance(ref["参照"],dict) else ref["参照"]
    if ref.get("大準備複製",False) is not False:
        raise ValueError("大量準備は軽量参照のみ")
    for item in references:
        path=ROOT/item["パス"]
        if G.sha(path) != item["SHA256"] or path.stat().st_size != item["バイト"]:
            raise ValueError("準備軽量参照差")
        paths.append(path)
    paths.extend((main,ip))
    rows.extend((["固定前主準備・旧純対照/TOPIX数値/三採否","66場・非損益",66,G.link(main,output)],["固定前独立・TOPIX数値/strict跨時点/三採否","一致/合格",number(independent["照合項目数"]),G.link(ip,output)]))
    for name in ("会計人工接続.json","保存物読取補足.json"):
        if not ((study/name).is_file() or (work/name).is_file()):
            continue
        path=proof_path(study,work,name);data=G.read_json(path)
        if data["全件一致"] is not True or data["不一致数"] != 0:
            raise ValueError("小証明未完")
        if name == "会計人工接続.json" and any(G.sha(ROOT/n) != h for n,h in data["コードSHA256"].items()):
            raise ValueError("会計人工の版差")
        rows.append([name+"・主最終人工と別","一致/合格",number(data["照合項目数"]),G.link(path,output)]);paths.append(path)
    text="## 検査の状態\n\n旧NK原3分/監視/A0由来は独立42/43証明を共有する。44状態は新TOPIX数値/OLS20/跨商品strict公開/同終了/限月/三採否と全実sideのNK原BBO直接先着を確認し、旧CMFの再構築と主張しない。会計はNKのみ、旧42A0直接対照を43D0同値proofへ推移接続する。精密傾き/時点/価格/全採否はstrict、数値表現差の許容を採否epsilonへ使わない。独立生17列の非H/原点出典は厳密、H現前/差のみabs1e−10/rel0・符号/採否strictとし、正本H定義へ置いた17列/panel/decisionの全内容hashを別に厳密照合する。独立生H差件数/最大差/生hash差は参考で、保存正本の一致を独立再算の生float SHA同一と呼ばない。初回生SHA差は保全し、I/J/O・条件・閾値を変えず先着/PnL前に準備を再bindした。小型定義は場/index/Hだけの準備証明で、正式新5系列や採否ゲートの追加ではない。準備は先着/運用/PnLなし。\n"
    for key in ("検証範囲","厳密範囲","数値許容"):
        if independent.get(key):
            text+=key+"："+G.cell(independent[key]).rstrip("。")+"。\n"
    aliases=independent["H表示alias表現差"]
    exact_zero=("独立H準備不一致足数","独立H符号不一致足数","H厳密符号不一致leaf数","TOPIX全内容SHA不一致場数","新採否厳密不一致場数")
    if any(independent[k] != 0 for k in exact_zero) or any(r[k] != 0 for r in aliases.values() for k in ("準備不一致足数","符号不一致足数")):
        raise ValueError("独立生Hの準備/符号又は定義SHA/採否に差")
    text+="独立生Hの表現差は"+str(independent["独立H表現差足数"])+"/"+str(independent["TOPIX独立再構築足数"])+"一意足、最大絶対差"+str(independent["独立H最大絶対差"])+"。δHは"+str(aliases["MACDヒスト変化"]["表現差足数"])+"一意足、最大絶対差"+str(aliases["MACDヒスト変化"]["最大絶対差"])+"。全H/δHの準備・符号と全採否に差0、正本定義全内容hash不一致0。\n"
    text+="独立生のTOPIX足/panel/全j内容SHA差は参考として"+"/".join(str(independent[k]) for k in ("独立生TOPIX内容SHA差場数_参考","独立生補助内容SHA差場数_参考","独立生全j内容SHA差場数_参考"))+"場。以下のleafは同じHが足/出典/判定へ現れる重複を含み、一意足数とは分母が異なる。\n"
    text+=G.table(["H数値欄・重複込み","数値leaf","表現差leaf","最大絶対差"],[[k,v["全数値leaf"],v["leaf差数"],str(v["最大絶対差"])] for k,v in independent["H限定数値leaf比較_重複含む"].items()])
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
    """商品を区別し、TOPIX準備/複合方向と固定NK条件を版4へ記録する。

    引数: rules(list[dict])は三評価。
    返り値: list[dict]は11設定。相関係数/NT倍率/リターン/CMFを測定扱いにしない。
    """
    groups=[
        (["P07","P10"],["m03"],rules,"NK：固定43D0=42A0全245純/価格再テストを保持","b/j/T順行R反転/一監視/used/最初対象再テストの完全対照。新価格母集団やTOPIX注文を作らない"),
        (["I03"],["m03"],rules,"NK：当時実方向MACDヒスト差を保持","NKの既採用/既競合/時間/勢いを取り直さず、TOPIX値で旧WAITを救済しない"),
        (["I09"],["m03"],rules,"NK：現j入口ATR正/同じDを保持","TOPIX ATRやTOPIX呼値をNKのATR/追尾幅/125250へ混ぜない"),
        (["X01"],["m03"],rules[1:],"TOPIX：同終了・同限月年月・confirm<NKj要求秒strict","関連指数の利用時点整合。異商品line比較なし、同秒不可/参照None/一理由、古足fallback/後足待ちなし"),
        (["I14","I03"],["m03"],rules[1:],"TOPIX準備：当場OLS20と現前ヒスト有限","元TOPIX20Cの精密OLS/同TPI限月の中心化MACD12/26/9。傾き0/差0は準備可。NKの同名指標と区別"),
        (["X01","I14","I03"],["m03"],rules[2:],"TOPIX値：実side×傾き>0かつ実side×δH>0strict","別商品の方向・勢い整合という複合1条件。相関係数/NT倍率/相対リターン未計算、単独効果/独立二票ではない"),
        (["X01","I14","I03"],["m03"],rules,"診断のみ：同X1内の符号shadow/事後時計/日夜役割構成","全TOPIXから同秒/後公開/未収録/NPを分けるのは事後専用。live理由や未知の当時数値へ戻さず、別運用/新閾値なし"),
        (["B01"],["m03"],rules,"NK：固定j時計/残60分/遅延30秒/純13非label","NK確認遅延0は同終了strict事前公開から構造上X1不可。上限を仮約定支持や方向効果としない"),
        (["B01"],["tick"],rules,"NK：市場+1秒/TTL30/一pending・一建玉","TOPIXは補助のみで約定商品へ混ぜず、純subsetと実占有差を分ける"),
        (["I09","C06","E02"],["tick"],rules,"NK XF：現在返済利益円−122>0strict/名目entry床","現NKj入口ATR固定D/MFE−D/非緩和/pending凍結、起動参照滑り5pt固定。追加0/5/10は同約定ストレス"),
        (["E01","B01"],["tick"],rules,"NK診断：旧完全対照/直接先着/実参加/共通出口/回収","42A0直対照＋43D0 proof推移、旧11同値と全実side原BBO直接監査を分離。仮250と実回収/費用資格は別"),
    ]
    return [{"設定ID":f"S{i:02d}","手法ID":m,"尺度ID":sc,"短記":short,"説明":detail,"結果短記":"・".join(r["評価ID"] for r in applies),"適用評価":[r["評価ID"] for r in applies]} for i,(m,sc,applies,short,detail) in enumerate(groups,1)]


def diagnosis(study: Path, work: Path, output: Path) -> str:
    """当時可視性・事後時計・複合方向・実回収を保存診断から表示する。

    引数: study/work/output(Path)は保存/表示先。
    返り値: strは小型本文。原相場/TOPIX OLS/母監視を再計算しない。
    """
    path=proof_path(study,work,"対応診断.json");data=G.read_json(path)
    text="## 固定NK基準とTOPIX準備/方向の選別\n\n"+G.link(path,output)+"が正本。旧全424jとX0純245を分け、X0→X1は時計/限月/数値の準備、X1→X2は同準備下の方向・勢いの複合選別。CMF/相関係数/NT倍率/相対リターンの効果ではない。\n"
    text+=G.table(["期間","全j/旧A0純","NK遅延0/時計だけの登録上限","全jstrict可視/準備","X0/X1/X2要求"],[[PERIOD_NAMES[r["期間"]],f"{r['旧全j数']}/{r['旧A0純数']}",f"{r['旧A0_NK遅延0数']}/{r['時計だけのX1登録上限']}",f"{r['全jstrict可視数']}/{r['全j補助準備数']}","/".join(str(r[p+"純入口数"]) for p in POLICIES)] for r in data["旧jと三入口"]])
    text+=G.table(["比較/期間/役割","保持要求/仮約定・250率","除外要求/仮約定・250率","純追加","準備除外理由・重複あり"],[[r["比較"]+"/"+PERIOD_NAMES[r["期間"]]+"/"+r["役割"],*[f"{r[k]['候補数']}/{r[k]['約定候補数']}・{r[k]['順行先着']}/{r[k]['約定候補数']}={G.pct(r[k]['確認率'])}" for k in ("保持入口","除外入口")],r["新規追加入口数"],G.describe(r["準備除外理由_重複あり"])] for r in data["入口追加比較"]])
    text+="## 同じX1準備内のTOPIX傾き×ヒスト差\n\n実sideを掛けたTOPIX値の正/0/負を同じX1内で記述するshadowで、OLS単独/MACD単独の別運用ではない。両値はTOPIX自身の終値由来で独立二票にしない。NKのMACD/ATRや価格リターンと混同しない。\n"
    text+=G.table(["期間/役割","実方向TOPIX傾き/ヒスト差","要求/仮約定","250/仮約定・率"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["実方向TOPIX傾き"]+"/"+r["実方向TOPIXヒスト差"],f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["X1内の傾きと勢い"] if r["候補数"]])
    text+="## 事後時計診断専用・当時理由との分離\n\n以下は全保存TOPIXを知った後の同終了区分で、live採否・理由へ使っていない。当時strict可視足が無ければ参照None＋『TOPIX同終了strict事前公開参照なし』を保持する。同秒/後公開/未収録/NP等の区分から未知の指標値を当時欄へ補わない。異商品lineの大小は比較しない。\n"
    text+=G.table(["期間/役割","事後時計区分","全j/うちNK遅延0","X0要求/仮約定","X0の250/仮約定・率"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["事後時計区分"],f"{r['全j数']}/{r['NK遅延0の全j数']}",f"{r['候補数']}/{r['約定候補数']}",f"{r['順行先着']}/{r['約定候補数']}・{G.pct(r['確認率'])}"] for r in data["事後時計診断専用"] if r["全j数"]])
    text+="## 準備による日夜・役割・NK遅延の構成差\n\n分母はX0純要求。NK遅延0はTOPIX確認>=同endとstrict事前公開から構造上X1不可で、時計上限だけでは仮約定支持不足を断定しない。別商品準備による活動/日夜/役割の構成選別を方向予測効果から分ける。X0要求0の行は省略。\n"
    text+=G.table(["期間/役割","日夜/NK遅延","X0/X1/X2要求","X0の250/仮約定・率"],[[PERIOD_NAMES[r["期間"]]+"/"+r["役割"],r["日夜"]+"/"+r["NK確認遅延"],f"{r['X0純要求数']}/{r['X1純要求数']}/{r['X2純要求数']}",f"{r['X0先着']['順行先着']}/{r['X0先着']['約定候補数']}・{G.pct(r['X0先着']['確認率'])}"] for r in data["準備の日夜役割遅延構成"] if r["X0純要求数"]])



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
    """全証明完成後の保存値だけから関連指数補助の二MDを表示する。

    引数: study/work/output(Path)は正式/作業/表示先。
    返り値: list[Path]はREADME/設定と結果。正式結果前には生成しない。
    """
    config,report,rules,entries,values,manifest=validate(study)
    output.mkdir(parents=True,exist_ok=True)
    readme,mapping=output/"README.md",output/"設定と結果.md"
    common,catalog=settings(rules),V4.load_catalog()
    diagnostic=G.read_json(proof_path(study,work,"対応診断.json"))
    intro="固定43D0=42A0のNK再テスト全245純をX0対照とし、X1で同終了TOPIX3分のstrict事前公開/同限月年月/当場OLS20/現前ヒスト準備、X2で実方向の傾きとヒスト差の両strict正を追加。売買はNKだけ、三切替入口/三XF/六実役割群、版4・54手法×9尺度。全NK66場（学習40・選択24・既使用11/4Day/Night2）は既使用の追加開発で、初TOPIX結合を未知データ実証や未使用確認とは呼ばない。11/5Dayは両商品とも対象外・内容未読。\n\n"
    conclusion=f"**支持付き入口70目標は{report['入口70目標達成数']}/3、費用資格は{report['費用資格数']}/3、現在費用資格は{report['現方針費用資格数']}/3、採用資格は{report['採用資格数']}/3。**\n\n"
    for policy in POLICIES:
        conclusion+=policy+"XF："+"、".join(PERIOD_NAMES[p]+"は250先着率"+G.pct(entries["3分_"+policy][p]["確認率"])+"・追加5pt平均"+number(values["3分_"+policy+"_XF"][p]["運用"]["追加5pt平均円"])+"円" for p in PERIODS[:2])+"。\n\n"
    for policy in POLICIES[1:]:
        e=entries["3分_"+policy]
        conclusion+=policy+"学習/選択仮約定は"+str(e["学習"]["約定候補数"])+"/"+str(e["条件選択"]["約定候補数"])+"件、両期入口支持は"+("充足" if e["入口支持"] else "未達")+"。高率の少数群や後続2場だけの成績を両期支持/70/費用へ代用しない。\n\n"
    for title in ("TOPIX準備追加","TOPIX方向勢い追加"):
        groups=[r for r in diagnostic["実参加比較"] if r["比較"] == title]
        conclusion+=title+"：実共通は学習/選択/後続"+"/".join(str(r["厳密共通実新規数"]) for r in groups)+"件、右だけ実参加"+"/".join(str(r["右のみ"]["完結取引数"]) for r in groups)+"件。共通出口/片側参加、総額/平均/役割構成は別に評価する。\n\n"
    warnings=[cid+"/"+PERIOD_NAMES[p]+"="+str(values[cid][p]["運用"]["品質注意場数"])+"場" for cid in CANDIDATES for p in PERIODS if values[cid][p]["運用"]["品質注意場数"]]
    conclusion+=("NK運用の品質注意は"+"、".join(warnings)+"。該当期の円/全額差は観測値で、全体確定nullを観測額で置換しない。\n\n") if warnings else "NK運用は全案各期の品質注意0。TOPIX入力の時計後退等の注意とは別で、実micro約定や将来経路の品質を保証しない。\n\n"
    clock="## strict価格時計と受信時計の限界\n\nTOPIX同場u.end=NKj.endかつu.confirm<NKj要求秒strictの足だけを当時参照する。別ファイルのline大小は比較しない。同秒/後公開/未収録は当時の参照None＋『TOPIX同終了strict事前公開参照なし』一理由とし、古い正常足や別endへfallbackせずjを後待ちしない。未来足追加で当時None/理由/採否が変わらないことを人工検査する。\n\nNK遅延0はTOPIX.confirm>=同endとstrict<から構造上不可。時計だけの登録上限は仮約定支持でなく、準備による活動/日夜/T-R構成の変化を値の効果と分ける。全保存TOPIXから同秒/後公開/NP等を分けた表は事後時計診断専用で、採否や未知の当時数値へ戻さない。\n\nstrict価格時刻先行でも実受信先行を証明しない。価格時計しかない模型の探索であり、実WebSocketの共通受信時刻/連番/保存順が得られた確認とは別試行にする。二指数の恒常的先行・独立性・騰落人数や因果関係を仮定しない。\n\n"
    method="## 二商品の役割を分ける\n\nNKは固定価格b/j/T順行R反転・MACD・jATR・既競合・時計を維持し、X0を42A0へ直接全属性対照、43D0同値proofへ推移接続する。TOPIXは方向補助だけで建玉/損益を作らない。TOPIX逆向き/0/未準備からNKのsideを反転せず、自動ドテンや保有中の返済条件を追加しない。\n\nTOPIXの当足含む同場連続公開20Cへx0..19/切片付きOLSを適用し、元各CをFraction化して傾き符号を使う。傾き0は準備可でX2不成立、R²は要求しない。中心化MACD12/26/9はTOPIX同限月でcarry/resetし、当場隣接の現前ヒスト差を使う。公開OLS窓/前値は当場、NP内部数値更新と公開参照可否を分け、数値許容を採否epsilonにしない。\n\nX2はTOPIX傾きとδHの複合1条件全体で、単独効果/独立二票ではない。X01は関連指数整合の具体設定で、相関係数/NT倍率/相対リターンを測った意味ではない。CMF/量/RVOL/TOPIX ATR/上位一目/多時間軸は不使用。TOPIXをNKの呼値へ丸めず、商品間ptや円損益を足さない。\n\n"
    protection="## 同じNK XF・費用と回収\n\nmicro1枚/倍率10円/pt/呼値5pt/片道fee11円、正常BBO新規+1秒TTL30/返済+1秒、一pending・一建玉。実side×(現在返済mark−entry)pt×10円/pt−122円>0strictで起動し、現NKj入口ATR固定D=max(5,ceil(ATR/5)*5)、MFE−D/最低名目entry床/非緩和/返済pending凍結。参照滑り5ptと費用後起動閾値0円という『5+0』で、旧A5名目5pt起動ではない。\n\n追加0/5/10は同約定への費用負荷で起動参照5を変えない。hard125/TP250/期限と場内完結は固定し、TOPIX値を保護床や幅に混ぜない。名目床は費用後同値/遅延後同値約定を保証せず、仮250/実MFE250/回収と費用資格を分ける。ラージBBO代理は実microキュー/数量/部分約定を保証しない。\n\n"
    limits="## 再利用と限界\n\nX0→X1の準備とX1→X2複合値、純subsetとactual追加、共通出口と片側額、総額/平均、切替全体と六役割群を分ける。全額差=共通出口差＋右のみ額−左のみ額を全費用で確認し、共通0の差0は比較対象なし。支持/70/費用/品質nullを緩めず、後続2場単独で両期資格を補わない。\n\nTOPIX初回利用でもNKの固定66場は開発既使用。二商品同方向の一般説明や一次研究の先行遅行結果を、2026年3分条件の有効/無効や将来利益へ拡張しない。新条件/古足fallback/新h/閾値探索を結果後に足さず、主要変更は新試行へ分ける。\n\n"
    audit_text,audit_paths=audits(study,work,readme)
    table=result_tables(report,entries,values)
    links=" / ".join(G.link(study/n,readme) for n in ("計画.md","条件.json","固定.json","結果.json","入口参照.json","対照参照.json","指標参照.json","TOPIX入力参照.json","X0対照同値.json"))
    summary="# 試行00044：TOPIX方向とNK再テスト\n\n"+intro+links+" / "+G.link(mapping,readme)+"\n\n"+conclusion+table+diagnosis(study,work,readme)+clock+method+protection+limits+audit_text
    mapped="# 試行00044：設定と結果\n\n"+intro+conclusion+G.link(V4.MASTER,mapping,"コピー元汎用表・版4")+" / "+G.link(readme,mapping)+"\n\n"
    mapped+="## 手法×時間スケール\n\n54手法×9尺度・版4不変。X01は関連指数整合、I14/I03のS05/S06はTOPIX3分、NKのMACD/ATR/P07/P10は別設定。係数/NT倍率/リターン/P05/CMF/量/R²/上位を使用扱いにしない。R0=X0XF完全対照、R1=X1XF補助準備、R2=X2XF方向勢い。\n\n"+V4.matrix(catalog,mapping,common)
    mapped+="## 設定明細\n"+G.table(["設定","手法/尺度","短記","条件と役割","適用評価"],[[r["設定ID"],"/".join(r["手法ID"])+"・"+"/".join(r["尺度ID"]),r["短記"],r["説明"],"・".join(r["適用評価"])] for r in common])
    mapped+="## 全固定条件\n"+G.table(["項目","固定値"],[[k,G.describe(v)] for k,v in config.items()])
    mapped+="## 三評価の定義\n"+G.table(["評価","候補","集合役割","入口支持","70目標","費用資格","採用資格"],[[r["評価ID"],r["候補ID"],"切替","充足" if values[r["候補ID"]]["入口支持"] else "未達","達成" if values[r["候補ID"]]["70目標"] else "未達","充足" if values[r["候補ID"]]["費用資格"] else "未達","充足" if values[r["候補ID"]]["採用資格"] else "未達"] for r in rules])
    mapped+=table+clock+method+protection+limits+audits(study,work,mapping)[0]
    names=("入力台帳.json","入口参照.json","対照参照.json","指標参照.json","TOPIX入力参照.json","TOPIX入力記録.zip","TOPIX数値定義.jsonl.gz","X0対照同値.json","準備参照.json","一覧.resources.json","固定候補_取引.csv","固定候補_注文.csv","全候補_場別.csv","入力品質.json","作業成果物.json")
    sources=[HERE/n for n in ("README.md","入口.py","指標.py","運用.py","検証.py","入力監査.py","合成検証.py","独立監査.py","状態独立確認.py","追尾独立確認.py","対応診断.py","レポート.py") if (HERE/n).is_file()]
    docs=[ROOT/n for n in ("docs/technical-analysis/指標/関連指数の方向確認.md","docs/technical-analysis/指標/線形回帰と決定係数.md","docs/technical-analysis/指標/MACD.md","docs/technical-analysis/指標/ATR.md","docs/議論/価格時計と受信時計を分ける.md","docs/README.md","docs/議論/README.md","docs/議論/PDCAの進行.md","docs/議論/テクニカル手法の検証範囲と次の複合候補.md","study/README.md") if (ROOT/n).is_file()]
    if COMMON.is_file():docs.append(COMMON)
    viewing="## 閲覧・共有と再表示\n\n"+" / ".join(G.link(study/n,readme) for n in names if (study/n).is_file())+"\n\nコード："+" / ".join(G.link(p,readme) for p in sources)+"。\n\n"
    viewing+="旧母監視/NK全数値は三参照で共有、新TOPIX入力は別参照。新大明細はTOPIX全指標/発動判定/最小case/全運用/追尾の5gzip、全TOPIX足は1系列だけに保存する。ViewerはNK三運用各66場の198資源と3代表。--prepareはTOPIX数値/跨時点/採否/純信号のみで先着/運用/PnLなし。正式結果/部分gzipを上書きしない。\n\n保存値だけの再表示：\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/TOPIX補助/レポート.py\n```\n\n"
    viewing+="TOPIX入力記録.zipは必須の入力台帳/入力監査/入力予約3JSONだけを同byte保全し、原板/cacheを含まない。work消去時は所定workへ3JSONを復元し、TOPIX入力参照のSHAと照合する。モデルの参照先・同SHAは維持し、zipを新たな採否ゲートや別入力版にしない。入力照合一致は品質無注意ではなく、価格時計後退やLast/BBOの不一致等を別に残す。\n\n"
    viewing+="TOPIX数値定義.jsonl.gzの正式保全は場/index/macd_histの3列だけで、全17列/原板の複製ではない。workの定義が無ければ正式同byte保全から所定workへ復元し、準備参照と同じ圧縮/展開内容SHAを照合する。全13,004足の正本H定義と独立生H検算を再現するための資料で、正式新5系列や採否条件の追加ではない。\n\n"
    if COMMON.is_file():viewing+=G.link(COMMON,readme,"共通知見")+"。\n\n"
    helpers=[ROOT/"scripts"/name/"レポート.py" for name in ("CMF変化","再テスト量方向","回帰突破","構造判別","量比反転","回復監視","突破指値","終値位置","CCI突破","一目基準線","反転確認時計","SAR持続","終値切替")]
    paths=[Path(__file__),*helpers,ROOT/"scripts/レポート/設定結果レポート.py",ROOT/"scripts/レポート/カタログ版4.py",V4.BASE,V4.CATALOG,V4.MASTER,manifest,PREVIOUS/"固定.json",PREVIOUS/"結果.json",PREVIOUS/"D0対照同値.json",
        *[study/n for n in ("計画.md","条件.json","固定.json","結果.json",*names) if (study/n).is_file()],NUMERIC_STUDY/"条件.json",EXIT_STUDY/"条件.json",*sources,*docs,*audit_paths]
    tpi_ref=G.read_json(study/"TOPIX入力参照.json")
    paths.extend(ROOT/tpi_ref[n]["パス"] for n in ("入力台帳","入力監査","入力予約"))
    for path in (work/"診断予定.json",ROOT/"work/次研究44の独立案.md",work/"NK時計による準備上限.json"):
        if path.is_file():paths.append(path)
    for path,body in ((readme,summary+viewing),(mapping,mapped)):
        path.write_text(body+G.provenance(list(dict.fromkeys(paths)),path),encoding="utf-8")
    return [readme,mapping]


def main() -> None:
    """全証明後の保存二MDだけを表示する。

    引数: なし。--study/--work/--outputはPath。
    返り値: None。主/独立/監査/診断を起動しない。
    """
    parser=argparse.ArgumentParser(description="固定NKとTOPIX準備/方向勢い・保存帳票")
    parser.add_argument("--study",type=Path,default=STUDY);parser.add_argument("--work",type=Path,default=WORK);parser.add_argument("--output",type=Path)
    args=parser.parse_args();print("\n".join(str(p) for p in run(args.study.resolve(),args.work.resolve(),(args.output or args.study).resolve())))


if __name__ == "__main__":main()
