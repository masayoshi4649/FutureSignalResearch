"""93の保存集計とNative54場だけを読み、会計3列と分母を報告する。"""

import argparse
from collections import defaultdict
from decimal import Decimal,ROUND_HALF_EVEN
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
PRE_SHA='bd2d6ec8258dce5b24fe1bbd1242b766d25973e8835e2abc2dc536baec6eec4d'
BEGIN='\n<!-- REPORT93:BEGIN -->\n'
END='<!-- REPORT93:END -->\n'
METHODS=('D164_15','P164_06','U165_03')
KEYS=tuple(p+'_'+m for p in ('micro','mini') for m in METHODS)
FIELDS=('entry_quantity','close_quantity','gross_yen','fee_yen','slippage_yen','gross_minus_fee_yen','net_yen')
BASES=('gross','fee_only','slip')


def need(ok: bool, reason: str) -> None:
    """
    機能: 保存正本の不一致と既存出力上書きを拒否する。
    引数: ok(bool)、reason(str)は成立条件と原因。
    返り値: None。不成立はValueError。
    """
    if not ok:raise ValueError(reason)


def sha(path: Path) -> str:
    """
    機能: 保存入力のbyte指紋を取得する。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。
    """
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def number(value: object) -> Decimal:
    """
    機能: boolを除く有限な保存金額/価格を十進数へ写す。
    引数: value(object)はJSON数値。
    返り値: Decimalは丸めない金額。非有限/文字列は拒否する。
    """
    need(type(value) in (int,float,Decimal),'有限数値の型');out=Decimal(str(value));need(out.is_finite(),'非有限数値');return out


def count(value: object) -> int:
    """
    機能: 実枚数/件数を厳密な非負intとして検査する。
    引数: value(object)はJSON件数。
    返り値: intは件数。bool/小数は受理しない。
    """
    need(type(value) is int and value>=0,'非負int件数');return value


def serial(value: object) -> int | float:
    """
    機能: 半円を保った十進数をJSON numberへ直列化する。
    引数: value(object)はDecimal。
    返り値: int|floatは整数又は小数。金額の整数丸めはしない。
    """
    if isinstance(value,Decimal):need(value.is_finite(),'JSON非有限');return int(value) if value==value.to_integral_value() else float(value)
    raise TypeError(type(value).__name__)


def json_text(value: object) -> str:
    """
    機能: 統計を決定的なUTF-8 JSON本文へ変換する。
    引数: value(object)は統計値。
    返り値: strは末尾LF付きJSON。
    """
    return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=serial)+'\n'


def pretable(text: str) -> str:
    """
    機能: 自身の結果markerだけを除去し元18設定/版5計画へ復元する。
    引数: text(str)は初回計画又は生成後の設定コピー。
    返り値: strは固定SHAへ一致する元計画。marker外変更を拒否する。
    """
    if BEGIN in text:
        need(text.count(BEGIN)==text.count(END)==1 and text.endswith(END),'結果marker集合/末尾');text=text.split(BEGIN,1)[0]
    need(hashlib.sha256(text.encode('utf-8')).hexdigest()==PRE_SHA,'元計画設定SHA差')
    rows=[]
    for line in text.splitlines():
        if re.match(r'^\| [A-Z]\d{2} \|',line):
            p=[x.strip() for x in line.strip().strip('|').split('|')]
            if len(p)==11:rows.append(p)
    need(len(rows)==55 and len({r[0] for r in rows})==55 and all(len(r[2:])==9 and all(r[2:]) for r in rows),'版5の55×9差')
    need(len(re.findall(r'^\| [SN]\d{2} \|',text,re.M))==18 and len(re.findall(r'^\| R0[1-6] \|',text,re.M))==6,'18設定/6評価差');return text


def ratio(numerator: Decimal, denominator: Decimal, label: str) -> dict:
    """
    機能: 分子/分母付きの割合を算出し資本金ROIと区別する。
    引数: numerator/denominator(Decimal)、label(str)は比の対象。
    返り値: dictは分母0ならnull、他は百分率を小数6桁表示する。
    """
    return {'分子':numerator,'分母':denominator,'分母の意味':label,'百分率':None if denominator==0 else (100*numerator/denominator).quantize(Decimal('.000001'),rounding=ROUND_HALF_EVEN),'分母0':denominator==0}


def distribution(values: list) -> dict:
    """
    機能: 明示したHold又はセッション単位で正額/負額/勝敗を集約する。
    引数: values(list[Decimal])はその分母の純額。
    返り値: dictは損失を負号で保持した合計と勝率/利益損失比。
    """
    positive=sum((x for x in values if x>0),Decimal(0));negative=sum((x for x in values if x<0),Decimal(0));wins=sum(x>0 for x in values);losses=sum(x<0 for x in values);flat=sum(x==0 for x in values)
    return {'分母件数':len(values),'正額合計円':positive,'負額合計円':negative,'純額円':positive+negative,'黒字':wins,'赤字':losses,'同値':flat,'黒字率':ratio(Decimal(wins),Decimal(len(values)),'同値を含む全対象件数'),'平均額円':None if not values else (positive+negative)/len(values),'利益損失比':{'正額':positive,'損失絶対額':-negative,'比':None if negative==0 else positive/-negative,'分母0':negative==0}}


def money(row: dict, basis: str) -> Decimal:
    """
    機能: 3つの会計basisから一つの額を選ぶ。
    引数: row(dict)、basis(str)は金額行とgross/fee_only/slip。
    返り値: Decimalは指定額。
    """
    return row[{'gross':'gross_yen','fee_only':'gross_minus_fee_yen','slip':'net_yen'}[basis]]


def aggregate(rows: list, bases: tuple, unit: str) -> dict:
    """
    機能: Hold/セッションの分母を明示して数量/費用/3会計を集約する。
    引数: rows(list[dict])、bases(tuple[str])、unit(str)は対象と会計列/単位。
    返り値: dictは集約と粗利益を分母にした費用比率。ROIは計算しない。
    """
    gross_positive=sum((max(r['gross_yen'],0) for r in rows),Decimal(0));fees=sum((r['fee_yen'] for r in rows),Decimal(0));slips=sum((r['slippage_yen'] for r in rows),Decimal(0))
    return {'集計単位':unit,'件数':len(rows),'新規実枚数':sum(r['entry_quantity'] for r in rows),'手数料円':fees if 'fee_only' in bases else None,'仮定滑り円':slips if 'slip' in bases else None,'会計':{b:distribution([money(r,b) for r in rows]) for b in bases},'費用率':{'指定手数料/粗利益':ratio(fees,gross_positive,unit+'単位のgross正額合計') if 'fee_only' in bases else None,'手数料と仮定滑り/粗利益':ratio(fees+slips,gross_positive,unit+'単位のgross正額合計') if 'slip' in bases else None},'ROI':None,'ROI未計測理由':'資本金/証拠金/資金拘束の入力がない'}


def book_holds(book: dict, session: str, key: str) -> tuple[list,dict]:
    """
    機能: 完結Nativeの実約定配分からHold別費用/粗益を再結合する。
    引数: book(dict)、session/key(str)は保存台帳と場/商品手法ID。
    返り値: tuple[list,dict]は小型Hold行と7合計。元通知や原板は再計算しない。
    """
    need(book['complete'] is True and book['finished'] is True and not book['failure'] and not book['pending'],'未完結Native');need(book['method']=='NK225_'+key.split('_',1)[1],'商品手法key/元method差')
    c=book['config'];mini=key.startswith('mini_');need(c['product']==('NK225mini' if mini else 'NK225micro') and number(c['point_value'])==(100 if mini else 10) and number(c['fee_yen_per_side'])==(Decimal('38.5') if mini else 11) and number(c['slippage_points'])==5,'商品/点価/費用規格')
    point=number(c['point_value']);fee=number(c['fee_yen_per_side']);slip=number(c['slippage_points'])*point;entries={};parts=defaultdict(list);execution=set();paid_fee=paid_slip=Decimal(0)
    for row in book['fills']:
        f=row['fill'];need(f['Fee']==0 and f['ExecutionID'] not in execution,'元Fee0/実約定ID');execution.add(f['ExecutionID']);qty=count(f['Quantity']);need(qty>0,'実約定量0');need(number(row['fee_yen'])==fee*qty and number(row['slippage_yen'])==slip*qty,'片道費用の実量差');paid_fee+=fee*qty;paid_slip+=slip*qty
        if row['action']=='new':
            identity=f['HoldID'];need(identity and identity not in entries and not f['Closed'] and not row['allocations'],'実新規HoldID');entries[identity]={'quantity':qty,'price':number(f['Price']),'side':row['side'],'entry_id':f['SignalID']}
        else:
            need(row['action']=='close','約定action');alloc=row['allocations'];targets=[(a['id'],a['quantity']) for a in f['Closed']];allocated=[(a['hold_id'],a['quantity']) for a in alloc];need(len(set(t[0] for t in targets))==len(targets) and len(set(t[0] for t in allocated))==len(allocated) and sorted(targets)==sorted(allocated) and sum(a['quantity'] for a in alloc)==qty,'実Closed/返済配分')
            for a in alloc:
                identity=a['hold_id'];need(identity in entries,'返済先の実取得なし');entry=entries[identity];n=count(a['quantity']);need(n>0 and row['side']==-entry['side'],'返済量/方向');g=entry['side']*(number(f['Price'])-entry['price'])*point*n
                need(number(a['gross_yen'])==g and number(a['entry_price'])==entry['price'] and number(a['exit_price'])==number(f['Price']),'返済配分の価格/gross')
                need(number(a['entry_fee_yen'])==number(a['exit_fee_yen'])==fee*n and number(a['entry_slippage_yen'])==number(a['exit_slippage_yen'])==slip*n and number(a['net_yen'])==g-2*(fee+slip)*n,'Hold配分の往復費用')
                parts[identity].append({'quantity':n,'gross':g})
    saved={h['hold_id']:h for h in book['holds']};need(len(saved)==len(book['holds']) and set(saved)==set(entries),'保存Hold集合')
    result=[]
    for identity,e in entries.items():
        h=saved[identity];q=e['quantity'];gross=sum((p['gross'] for p in parts[identity]),Decimal(0));need(sum(p['quantity'] for p in parts[identity])==q and h['initial_quantity']==h['closed_quantity']==q and h['quantity']==0 and number(h['gross_yen'])==gross and number(h['closed_net_yen'])==gross-2*(fee+slip)*q,'保存Holdの完結量/純額')
        result.append({'session':session,'key':key,'hold_id':identity,'side':e['side'],'kind':h['kind'],'entry_quantity':q,'gross_yen':gross,'fee_yen':2*fee*q,'slippage_yen':2*slip*q,'gross_minus_fee_yen':gross-2*fee*q,'net_yen':gross-2*(fee+slip)*q})
    total={n:sum((r[n] for r in result),0 if n=='entry_quantity' else Decimal(0)) for n in ('entry_quantity','gross_yen','fee_yen','slippage_yen','gross_minus_fee_yen','net_yen')};total['close_quantity']=total['entry_quantity']
    need(total['fee_yen']==paid_fee and total['slippage_yen']==paid_slip,'Hold費用と全Fill費用');need(all(number(book['totals'][n])==number(total[n]) for n in FIELDS),'Native totals/Hold合計差');return result,total


def analyze(summary: dict, natives: list, allow_reference_mismatch: bool=False) -> dict:
    """
    機能: 6窓・mini54セッション・各Holdの総額を保存集計へ結合する。
    引数: summary(dict)、natives(list[dict])、allow_reference_mismatch(bool)は保存正本と明示的な暫定許可。
    返り値: dictは損益3列/正負額/勝敗/数量/未計測事項。
    """
    need(summary['試行']==93 and summary['場数']==54 and summary['手法場数']==81 and summary['商品手法会計数']==162 and type(summary['元gross一致']) is bool,'元再現の集計/一致型')
    expected_rows={(r['session'],r['key']):r for r in summary['場別']};need(len(expected_rows)==len(summary['場別'])==162 and set(summary['集計'])==set(KEYS),'集計の162/6集合')
    seen=set();allholds=[];window=defaultdict(list);session_totals={};alltotals=defaultdict(lambda:defaultdict(Decimal))
    for native in natives:
        session=native['session'];need(session not in seen,'Native場の重複');seen.add(session);need('2026-09-21'<=session[:10]<='2026-10-27' and session.endswith(('_Day','_Night')),'54既使用期間外')
        methods=METHODS[:1] if session.endswith('_Day') else METHODS[1:];need(set(native['books'])=={p+'_'+m for p in ('mini','micro') for m in methods},'日中/夜間の手法集合')
        combined={'session':session,'entry_quantity':0,**{n:Decimal(0) for n in FIELDS if n not in ('entry_quantity','close_quantity')}}
        for key,book in sorted(native['books'].items()):
            hold,total=book_holds(book,session,key);need((session,key) in expected_rows and all(number(expected_rows[(session,key)]['totals'][n])==number(total[n]) for n in FIELDS),'場別集計/Native差');allholds+=hold;window[key]+=hold
            for n in FIELDS:alltotals[key][n]+=total[n]
            if key.startswith('mini_'):
                for n in combined:
                    if n!='session':combined[n]+=total[n]
        session_totals[session]=combined
    need(len(seen)==54 and sum(s.endswith('_Day') for s in seen)==sum(s.endswith('_Night') for s in seen)==27,'54場/昼夜27場')
    need(set(expected_rows)=={(n['session'],k) for n in natives for k in n['books']},'場別集合差')
    for key in KEYS:need(all(number(summary['集計'][key][n])==number(alltotals[key][n]) for n in FIELDS),'6窓合計差:'+key)
    reference={};need(set(summary['対照照合'])=={'micro_'+m for m in METHODS},'元gross対照3種の集合')
    for method,old in zip(METHODS,(1248500,392000,1181000),strict=True):
        key='micro_'+method;actual=alltotals[key]['gross_yen'];saved=summary['対照照合'][key];need(set(saved)=={'元報告gross','再現gross','差'} and number(saved['元報告gross'])==old and number(saved['再現gross'])==actual and number(saved['差'])==actual-old,'固定期待/保存差/Native元grossの結合差:'+key);reference[key]={'元報告gross':old,'再現gross':actual,'差':actual-old,'一致':actual==old}
    reference_ok=all(r['一致'] for r in reference.values());need(summary['元gross一致'] is reference_ok,'保存の元gross一致flag差');need(reference_ok or allow_reference_mismatch,'旧FARgross未一致。暫定集約には--allow-reference-mismatchが必要')
    sessions=[session_totals[s] for s in sorted(session_totals)];mini=[h for h in allholds if h['key'].startswith('mini_')];window_stats={}
    for key in KEYS:
        bases=BASES if key.startswith('mini_') else ('gross',);v=aggregate(window[key],bases,'Hold');v['評価会計']='mini主はfee_only、slipは仮定感度' if len(bases)>1 else '旧microはgrossのみ。外micro費用を評価に混ぜない';v['手法枠数']=27;window_stats[key]=v
    groups={}
    for label,chosen in (('全体',sessions),('日中',[s for s in sessions if s['session'].endswith('_Day')]),('夜間',[s for s in sessions if s['session'].endswith('_Night')])):
        v=aggregate(chosen,BASES,'セッション（夜間P+U合算）');v.update(取引あり場数=sum(r['entry_quantity']>0 for r in chosen),無取引場数=sum(r['entry_quantity']==0 for r in chosen));groups[label]=v
    holdstats=aggregate(mini,BASES,'Hold');need(all(holdstats['会計'][b]['純額円']==groups['全体']['会計'][b]['純額円'] for b in BASES),'mini Holdと54セッション純額差')
    mini_display=deepcopy_holds(allholds)
    return {'試行':93,'会計集約検算':True,'元再現':reference_ok,'暫定':not reference_ok,'元gross対照':reference,'状態':'既使用54場の保存会計。元gross不一致は暫定として保持し、完全再現/未知期間の安定利益を証明しない' if not reference_ok else '既使用54場の元連続再現・保存会計。未知期間の安定利益を証明しない','窓別':window_stats,'miniセッション集約':groups,'mini_Hold集約':holdstats,'miniセッション':sessions,'Hold別':mini_display,'未計測':{'連続時価DD円':None,'利益後赤字玉数':None,'利益後赤字率':None,'状態':'未計測','理由':'本帳票は保存約定/最終会計だけを集約。原板連続時価/利益起動の独立評価を行っていない','ROI':None,'ROI理由':'資本金/証拠金/資金拘束不明'},'限界':['正額/負額は完結Hold全体で分類し、返済片別の正負合計とは区別する','セッション勝敗は夜間P/Uを合算した54場が分母。81手法枠やHold数とは別','仮定5pt片道は実測又は手数料ではない。主は指定手数料のみ','無取引0を安定利益と読まず、取引あり場と分母を併記する','元通知・Source・原板・金融は再生していない']}


def deepcopy_holds(rows: list) -> list:
    """
    機能: 小型Hold出典を保存し、旧microの外費用を評価列から除く。
    引数: rows(list[dict])は完結Holdの会計。
    返り値: list[dict]はmini3列/microgrossだけの小型出典。
    """
    result=[]
    for row in rows:
        out=dict(row)
        if row['key'].startswith('micro_'):
            for n in ('fee_yen','slippage_yen','gross_minus_fee_yen','net_yen'):out[n]=None
        result.append(out)
    return result


def amount(value: object) -> str:
    """
    機能: 金額を半円まで読みやすく表示する。
    引数: value(object)は数値又はNone。
    返り値: strは円表示。未計測を0へ変えない。
    """
    if value is None:return '対象外/未計測'
    n=number(value);return f'{n:,.0f}' if n==n.to_integral_value() else f'{n:,.1f}'


def reference_notice(value: dict) -> str:
    """
    機能: 固定元grossとの差を本文/設定markerの先頭へ表示する。
    引数: value(dict)は元対照の照合を含む検算済み報告。
    返り値: strは暫定と会計検算を分けた日本語注記。
    """
    differences=' / '.join(m[0]+' '+('＋' if value['元gross対照']['micro_'+m]['差']>0 else '')+amount(value['元gross対照']['micro_'+m]['差']).replace('-','−')+'円' for m in METHODS)
    return ('**暫定報告：元grossは不一致。'+differences+'。会計集約検算=true、元再現=false、暫定=true。期待値や保存値は変更せず、完全再現/安定成功とはしない。**') if value['暫定'] else '元gross3対照は一致。会計集約検算=true、元再現=true、暫定=false。未見期間の安定成功を示すものではない。'


def render(value: dict) -> str:
    """
    機能: 6窓/mini54場/取引Holdの分母を分けた結果Markdownを作る。
    引数: value(dict)は検算済み統計。
    返り値: strは結果本文。資本金ROIや未計測DDを作らない。
    """
    lines=['# 元三手法のmini連続再現と費用・結果','',reference_notice(value),'','元100microのgross対照と、miniの粗損益・指定手数料のみ・仮定滑り込みを分ける。54場は既使用、未知期間の安定収益は未確認。正負額はHold完結全体の分類で、返済片別の総利益/総損失とは分母が異なる。','', '| 商品/窓 | Hold数 | 新規実枚 | gross円 | gross−fee円（mini主） | gross−fee−slip円（仮定5pt） |','| --- | ---: | ---: | ---: | ---: | ---: |']
    for key,row in value['窓別'].items():
        v=row['会計'];lines.append(f"| {key} | {row['件数']} | {row['新規実枚数']} | {amount(v['gross']['純額円'])} | {amount(v.get('fee_only',{}).get('純額円'))} | {amount(v.get('slip',{}).get('純額円'))} |")
    lines+=['','## miniのセッション会計','','夜間は同じ開始日の米国前P＋米国後Uを先に合算する。全体54場、日中27場、夜間27場。','', '| 区分 | 全場/取引あり/無取引 | gross円 | 指定手数料のみ円 | 仮定滑り込み円 |','| --- | --- | ---: | ---: | ---: |']
    for name,row in value['miniセッション集約'].items():lines.append(f"| {name} | {row['件数']}/{row['取引あり場数']}/{row['無取引場数']} | {amount(row['会計']['gross']['純額円'])} | {amount(row['会計']['fee_only']['純額円'])} | {amount(row['会計']['slip']['純額円'])} |")
    lines+=['','## mini完結Holdの正負額','','| 会計 | 分母Hold | 正額合計円 | 負額合計円 | 純額円 | 黒字/赤字/同値 |','| --- | ---: | ---: | ---: | ---: | --- |']
    for name,v in value['mini_Hold集約']['会計'].items():lines.append(f"| {name} | {v['分母件数']} | {amount(v['正額合計円'])} | {amount(v['負額合計円'])} | {amount(v['純額円'])} | {v['黒字']}/{v['赤字']}/{v['同値']} |")
    allmini=value['mini_Hold集約'];lines+=['',f"実新規{allmini['新規実枚数']}枚。指定手数料{amount(allmini['手数料円'])}円、別の仮定滑り{amount(allmini['仮定滑り円'])}円。片道38.5円/枚と5pt×100円/枚を分け、0.5円を保持した。",'', '費用率は各表の集計単位におけるgross正額合計が分母。黒字率は同値を含む全Hold/全セッションが分母。利益損失比は正額合計÷損失絶対額で、損失0なら未定義。資本金/証拠金ROIは算出していない。分子/分母は[統計JSON](統計.json)に明記した。','', '**連続時価DD・利益後赤字は未計測（null）。** 約定後の最終損益だけから0としない。元保護の動作/実板約定や、未知期間の安定性をこの帳票で追加検証したものではない。',''];return '\n'.join(lines)


def generate(summary_path: Path, native_root: Path, settings_path: Path, out: Path, check: bool=False, allow_reference_mismatch: bool=False) -> dict:
    """
    機能: 明示保存入力だけで新しい結果/統計/設定コピーを生成又は照合する。
    引数: summary_path/native_root/settings_path/out(Path)、check/allow_reference_mismatch(bool)は照合/暫定許可。
    返り値: dictは生成統計。原設定や既存出力を上書きしない。
    """
    files=sorted(native_root.glob('*.json.gz'));need(len(files)==54,'圧縮Native54場が必要');need(out.is_dir() if check else not out.exists(),'出力先は新規（check時は既存）が必要')
    watched={'summary':sha(summary_path),'settings_bytes':sha(settings_path),'code':sha(Path(__file__)),'native':{p.name:sha(p) for p in files}};pre=pretable(settings_path.read_text(encoding='utf-8'));summary=json.loads(summary_path.read_text(encoding='utf-8'),parse_float=Decimal);natives=[]
    for path in files:
        with gzip.open(path,'rt',encoding='utf-8') as stream:natives.append(json.load(stream,parse_float=Decimal))
    value=analyze(summary,natives,allow_reference_mismatch);value['入力']={'summary':str(summary_path.resolve()),'native':str(native_root.resolve()),'settings':str(settings_path.resolve())};value['入力SHA256']={**watched,'settings_bytes':PRE_SHA};value['元設定SHA256']=PRE_SHA;value['市場/原板/Source再計算']=0
    md=render(value);settings=pre+BEGIN+reference_notice(value)+'\n\n## 報告生成結果\n\n作成時点の「未実行」は上記の計画を記したもの。現在の保存集計はこのmarker内に示す。18設定と495セルの元本文は変更していない。\n\n'+md.replace('# 元三手法のmini連続再現と費用・結果','### 元三手法の連続再現・保存結果',1)+END
    need(pretable(settings)==pre,'生成後の元設定復元差');outputs={'結果.md':md,'設定と結果.md':settings};value['出力SHA256']={name:hashlib.sha256(text.encode('utf-8')).hexdigest() for name,text in outputs.items()};outputs['統計.json']=json_text(value)
    need(watched=={'summary':sha(summary_path),'settings_bytes':sha(settings_path),'code':sha(Path(__file__)),'native':{p.name:sha(p) for p in files}},'入力/コードの読取前後変更')
    if not check:out.mkdir(parents=True)
    for name,text in outputs.items():
        path=out/name
        if check:need(path.read_text(encoding='utf-8')==text,'出力不一致:'+name)
        else:
            with path.open('x',encoding='utf-8',newline='\n') as stream:stream.write(text)
    return value


def main() -> None:
    """
    機能: 原板や金融を呼ばず保存入力を明示して報告を生成する。
    引数: --summary/--native/--settings/--out(Path)全必須、--check/--allow-reference-mismatch(bool)は照合/明示暫定許可。
    返り値: None。失敗は非0、出力が存在すれば新規生成を拒否する。
    """
    parser=argparse.ArgumentParser(description='93保存会計の報告')
    for name in ('summary','native','settings','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--check',action='store_true');parser.add_argument('--allow-reference-mismatch',action='store_true');args=parser.parse_args();value=generate(args.summary,args.native,args.settings,args.out,args.check,args.allow_reference_mismatch);print(json.dumps({'会計集約検算':value['会計集約検算'],'元再現':value['元再現'],'暫定':value['暫定'],'窓数':len(value['窓別']),'miniセッション':len(value['miniセッション']),'DD':'未計測'},ensure_ascii=False))


if __name__=='__main__':main()
