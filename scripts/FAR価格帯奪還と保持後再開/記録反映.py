"""92の12保存正本だけから小型README/結果マーカーを生成・照合する。"""

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
NAMES=('result','cash','raw','source','saved','viewer','condition','input_ref','plan','settings_before','figure','availability')
KEYS=tuple(f'H{p}G1_D{d}' for d in (0,1) for p in (0,1))
BEGIN='<!-- 92_RESULTS_BEGIN -->';END='<!-- 92_RESULTS_END -->'
PRE='未実行。66場264会計・旧89対照132・独立価格/保存/原板/Source/Viewerの全証拠が揃うまで成績を記載しない。'
PRE_SHA='bb02c16b685161896674a16b5a751b7ea3cf2695b4787727b9d24fad0c7199fc'
NOTE='> 事前設定内の「未実行」は作成時点の記述です。現在の結果は末尾の「正式結果」を参照してください。'


def need(ok: bool, reason: str) -> None:
    """
    機能: 保存入力の不整合を明確な原因で拒否する。
    引数: ok(bool)、reason(str)は条件と説明。
    返り値: None。不成立はValueError。
    """
    if not ok:raise ValueError(reason)


def sha(path: Path) -> str:
    """
    機能: 明示正本又は依存コードの本文指紋を得る。
    引数: path(Path)は既存小型ファイル。
    返り値: strはSHA256。原板/ネットワークを開かない。
    """
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def number(value: object) -> Decimal:
    """
    機能: boolを混同せず有限の金額/量を十進比較へ変換する。
    引数: value(object)はJSONのint/float。
    返り値: Decimalは有限値。
    """
    need(type(value) in (int,float,Decimal) and math.isfinite(value),'有限数値が必要');return Decimal(str(value))


def count(value: object) -> int:
    """
    機能: 分母/件数を非負整数として確認する。
    引数: value(object)は件数。
    返り値: intは件数。boolを件数としない。
    """
    need(type(value) is int and value>=0,'非負int件数が必要');return value


def amount(value: object) -> str:
    """
    機能: 金額を桁区切りへ整形する。
    引数: value(object)は有限数値。
    返り値: strは金額表示。
    """
    s=format(number(value),',f');return s.rstrip('0').rstrip('.') if '.' in s else s


def marker(text: str, body: str) -> str:
    """
    機能: 92結果マーカーの内側だけを交換する。
    引数: text/body(str)は設定全文と結果文。
    返り値: strはマーカー外が不変の全文。
    """
    need(text.count(BEGIN)==text.count(END)==1,'92結果マーカーが一対必要');a,t=text.split(BEGIN,1);_,b=t.split(END,1);return a+BEGIN+'\n'+body+'\n'+END+b


def without_note(text: str) -> str:
    """
    機能: 生成器がタイトル直後へ加えた固定注記1件だけを除く。
    引数: text(str)は初回又は注記付きの設定全文。
    返り値: strは事前本文。任意位置/重複の注記を正規化しない。
    """
    prefix='# 00092：設定と結果\n\n'
    if NOTE in text:
        need(text.count(NOTE)==1 and text.startswith(prefix+NOTE+'\n\n'),'固定注記の位置/重複差');return prefix+text[len(prefix+NOTE+'\n\n'):]
    return text


def with_note(text: str) -> str:
    """
    機能: 事前状態と現在結果の関係をタイトル直後の固定注記で明示する。
    引数: text(str)は事前本文と今回結果。
    返り値: strは閾値を変えず注記だけ追加した設定。
    """
    prefix='# 00092：設定と結果\n\n';clean=without_note(text);need(clean.startswith(prefix),'設定表の先頭タイトル差');return prefix+NOTE+'\n\n'+clean[len(prefix):]


def settings(text: str) -> str:
    """
    機能: 初回/生成後どちらの表も事前本文へ復元して44設定/495セルを検査する。
    引数: text(str)は--settings-beforeの現在本文。
    返り値: strは固定事前表。結果マーカーを除く閾値は変更不可。
    """
    pre=marker(without_note(text),PRE);need(hashlib.sha256(pre.encode('utf-8')).hexdigest()==PRE_SHA,'固定事前表bb02の本文/閾値差')
    rows=[[c.strip() for c in l.split('|')[1:-1]] for l in pre.splitlines() if re.match(r'^\| [A-Z]\d\d \|',l) and len(l.split('|')[1:-1])==11]
    need(len(rows)==55 and len({r[0] for r in rows})==55 and all(len(r[2:])==9 and all(r[2:]) for r in rows),'版5の55×9差')
    definitions=pre.split('## 37基礎設定と7独立価格設定\n',1)[1].split('\n## ',1)[0];ids=re.findall(r'^\| ([A-Z]\d\d) \|',definitions,re.M)
    need(len(ids)==len(set(ids))==44 and ids[-7:]==[f'S{i:02d}' for i in range(1,8)],'37基礎/7独立価格ID差');return pre


def verify_result(value: dict, cash: dict) -> dict:
    """
    機能: 4成績と264保存会計・2参加差の全額対応を確認する。
    引数: value/cash(dict)は結果と独立会計証拠。
    返り値: dictは(session,key)別場会計。新売買数値器を作らない。
    """
    need(value['試行']==92 and value['場数']==66 and set(value['比較'])==set(KEYS),'92全4成績が必要')
    rows={(r['session'],r['key']):r for r in value['場別']};sessions={s for s,k in rows}
    need(len(rows)==len(value['場別'])==264 and len(sessions)==66 and set(rows)=={(s,k) for s in sessions for k in KEYS},'264会計集合差')
    need(set(value['再生結果SHA256'])=={s+'.json' for s in sessions},'66保存指紋集合差')
    checks={(r['session'],r['key']):r for r in cash['照合']};need(cash['会計数']==264 and cash['不一致数']==0 and len(checks)==len(cash['照合'])==264 and set(checks)==set(rows),'会計照合の全件成功が必要')
    for token,r in rows.items():
        m=r['metrics'];c=checks[token]
        need(number(m['net_pnl_yen'])==number(m['gross_pnl_yen'])-number(m['total_cost_yen'])==number(c['現金円']) and number(c['粗損益円'])==number(m['gross_pnl_yen']) and number(c['費用円'])==number(m['total_cost_yen']),'会計と正本純額差')
        need(all(count(m[n])==0 for n in ('open_quantity','pending_entry_quantity','reserved_exit_quantity')) and c['残量']==0,'未完結会計')
    for key in KEYS:
        s=value['比較'][key];chosen=[r for (session,k),r in rows.items() if k==key]
        need(sum(number(r['metrics']['net_pnl_yen']) for r in chosen)==number(s['費用後損益円'])==number(s['総計']['net_pnl_yen']),'四成績の純額合計差')
        for total,field in (('gross_pnl_yen','gross_pnl_yen'),('total_cost_yen','total_cost_yen')):need(number(s['総計'][total])==sum(number(r['metrics'][field]) for r in chosen),'粗益/費用の合計差')
        need(count(s['赤字場数'])==sum(r['metrics']['net_pnl_yen']<0 for r in chosen),'赤字場数の正本差')
        for r in chosen:count(r['metrics']['entry_quantity'])
        need(s['赤字場数']<=sum(r['metrics']['entry_quantity']>0 for r in chosen),'無取引場を赤字場へ混入')
        count(s['完結玉']);count(s['新規枚数']);number(s['最大DD円'])
        need(count(s['総計']['funding_failure_lots'])<=s['完結玉'],'保護予算不足の玉分母差')
        for flag,loss in (('全玉旗','全玉旗後赤字'),('残玉旗','残玉旗後赤字')):need(count(s[loss])<=count(s[flag])<=s['完結玉'],'正益後赤字の分母差')
    need(set(value['出口間の同実新規分解'])=={f'H1G1対H0G1_D{d}' for d in (0,1)},'二参加差集合')
    for d in (0,1):
        a,b=[f'H{p}G1_D{d}' for p in (0,1)];v=value['出口間の同実新規分解'][f'H1G1対H0G1_D{d}']
        need(v['比較']==[a,b] and count(v['同参照ID'])==count(v['同実新規'])+count(v['共通だが取得変更']),'参照親と実入口の分母差')
        need(v['同参照ID']+count(v['Aのみ'])==value['比較'][a]['完結玉'] and v['同参照ID']+count(v['Bのみ'])==value['比較'][b]['完結玉'],'片側参加の分母差')
        delta=number(v['同実新規出口差円'])+number(v['取得変更B損益円'])-number(v['取得変更A損益円'])+number(v['Bのみ損益円'])-number(v['Aのみ損益円'])
        need(number(v['同実新規出口差円'])==number(v['同実新規B損益円'])-number(v['同実新規A損益円']) and delta==number(v['全差円'])==number(value['比較'][b]['費用後損益円'])-number(value['比較'][a]['費用後損益円']),'全額参加差の再結合差')
    return rows


def prepare(paths: dict) -> dict:
    """
    機能: 12正本・現在coreコード・原板/保存/Viewerの結合を読取で確認する。
    引数: paths(dict[str,Path])は12必須の明示入力。
    返り値: dictは生成用値。設定入力は事前本文への正規化指紋を記録する。
    """
    need(set(paths)==set(NAMES) and len({str(p.resolve()).casefold() for p in paths.values()})==12,'12入力の重複/不足')
    raw_hashes={n:sha(p) for n,p in paths.items()};pre=settings(paths['settings_before'].read_text(encoding='utf-8'));hashes={**raw_hashes,'settings_before':PRE_SHA}
    values={n:json.loads(p.read_text(encoding='utf-8')) for n,p in paths.items() if n not in ('plan','settings_before','figure')}
    for v in values.values():need(type(v) is dict,'正本は辞書JSON');json.dumps(v,allow_nan=False)
    c=values['condition'];ref=values['input_ref'];need(c['試行']==ref['試行']==92 and c['事前設定表SHA256']==PRE_SHA and c['keys']==list(KEYS),'条件/参照/事前表/4会計差')
    core=c['コードと依存SHA256'];need(type(core) is dict and bool(core),'固定core指紋が必要');code={}
    for name,wanted in core.items():
        p=(ROOT/name).resolve();need(p.is_relative_to(ROOT) and p.suffix in ('.go','.mod','.sum','.py','.ps1','.md','.json') and sha(p)==wanted,'依存コード変更:'+name);code[name]=wanted
    for name in ('plan','input_ref'):
        relative=paths[name].relative_to(ROOT).as_posix();need(core.get(relative)==hashes[name],'条件へ結んだ計画/入力参照差')
    rows=verify_result(values['result'],values['cash']);fingerprints=values['result']['再生結果SHA256'];sessions={s for s,k in rows};saved=values['saved']
    need(saved['成功'] is True and saved['処理完了'] is True and saved['入力不変'] is True and (saved['場数'],saved['基準C0枠'],saved['基準会計'],saved['保存会計'])==(66,2442,132,264) and saved['不一致数']==0,'全保存132対照/264会計未完')
    need(saved['入力SHA256前']==saved['入力SHA256後'] and saved['入力SHA256前']['92']==fingerprints,'保存前後と結果指紋差')
    need(saved['照合コードSHA256']==sha(Path(__file__).with_name('基準と保存判断の照合.py')),'保存監査コード差')
    for name in ('raw','source'):
        p=values[name];need(p['試行']==92 and p['成功'] is True and p['処理完了'] is True and (p['場数'],p['会計数'],p['不一致数'])==(66,264,0),'全原板証拠未完:'+name)
        indexed={r['session']:r for r in p['対象場']};need(len(indexed)==len(p['対象場'])==66 and set(indexed)==sessions,'原板対象66場差')
        need(all(r['不一致数']==0 and r['再生結果SHA256前']==r['再生結果SHA256後']==fingerprints[s+'.json'] and (name=='raw' or r['再生結果SHA256']==fingerprints[s+'.json']) for s,r in indexed.items()),'原板の前後/Source単独指紋と結果の結合差')
        file='原板監査.py' if name=='raw' else 'Source通知監査.py';need(p['監査コードSHA256']==sha(Path(__file__).with_name(file)) and p['原板本文走査回数毎場']==1,'原板コード/走査数差')
    need(values['source']['入力前後不変'] is True,'Source入力変更')
    viewer=values['viewer'];expected={f'92_{k}_{s}' for s,k in rows};observed={v['id']:v for v in viewer['資源']}
    need(viewer['試行']==92 and viewer['成功'] is True and viewer['予定資源']==viewer['完了資源']==264 and viewer['不一致数']==0 and not viewer['APIエラー'] and viewer['入力不変'] is True and viewer['入力SHA256前']==viewer['入力SHA256後'],'Viewer全264成功が必要')
    need(viewer['結果SHA256']==hashes['result'] and viewer['監査コードSHA256']==sha(Path(__file__).with_name('表示監査.py')) and set(observed)==expected and len(viewer['資源'])==264,'Viewer結果/コード/対象差')
    for (s,k),r in rows.items():
        v=observed[f'92_{k}_{s}'];need(v['完了'] is True and v['不一致数']==0 and v['APIエラー'] is None and number(v['原純額円'])==number(v['API費用後円'])==number(r['metrics']['net_pnl_yen']),'Viewer個別純額/完了差')
    available=values['availability'];need(available['成功'] is True and available['固定依存と入力前後不変'] is True and available['可用性']['場数']==66 and available['可用性']['全定時']==2442,'可用性前検査の全場/固定差')
    descriptions=[e.text for e in ET.parse(paths['figure']).iter() if e.tag.endswith('description') and e.text];metadata=next((json.loads(t) for t in descriptions if t.lstrip().startswith('{')),None)
    need(metadata is not None and metadata['入力結果SHA256']==hashes['result'] and metadata['場数']==66 and metadata['会計数']==264 and metadata['図示コードSHA256']==sha(Path(__file__).with_name('図示.py')),'図の入力/コード/全場出典差')
    need(raw_hashes=={n:sha(p) for n,p in paths.items()},'正本読取中の変更')
    return {'paths':paths,'values':values,'hashes':hashes,'raw_hashes':raw_hashes,'pre':pre,'core':code,'rows':rows}


def result_block(value: dict) -> str:
    """
    機能: 4成績と正益分母を短いMarkdownへ整形する。
    引数: value(dict)は検査済結果正本。
    返り値: strは設定結果マーカー内の本文。
    """
    lines=['固定条件による全66場・264会計の結果。全場既使用。','',
      '| 会計 | 費用後円 | 粗損益/費用円 | 最大DD円 | 実参加/枚 | 取引場/無取引場 | 赤字場/66・取引場内率 | 全玉正益後赤字 | 残玉正益後赤字 |','| --- | ---: | --- | ---: | --- | --- | --- | --- | --- |']
    for key in KEYS:
        s=value['比較'][key];active=sum(r['key']==key and r['metrics']['entry_quantity']>0 for r in value['場別']);loss=s['赤字場数'];rate=f'{loss}/{active}（{100*loss/active:.1f}%）' if active else '0/0（未評価）'
        lines.append(f"| {key} | {amount(s['費用後損益円'])} | {amount(s['総計']['gross_pnl_yen'])}/{amount(s['総計']['total_cost_yen'])} | {amount(s['最大DD円'])} | {s['完結玉']}/{s['新規枚数']} | {active}/{66-active} | {loss}/66・{rate} | {s['全玉旗後赤字']}/{s['全玉旗']} | {s['残玉旗後赤字']}/{s['残玉旗']} |")
    failures='、'.join(f"{key} {value['比較'][key]['総計']['funding_failure_lots']}玉" for key in KEYS)
    lines+=['',f'保護予算不足（funding_failure_lots）：{failures}。旗後赤字0だけで要求時の予定保全が成功したとは判断しない。','',
      '複合入口の成績で、P04/P10やEMA/RSI等の個別効果ではない。無取引によるDD・赤字場数の減少と、取引した場での回収を分ける。少数・無取引・正益分母減を安定利益の証拠としない。'];return '\n'.join(lines)


def link(study: Path, path: Path, label: str) -> str:
    """
    機能: 生成先から明示正本への相対リンクを作る。
    引数: study/path(Path)、label(str)は基準・参照先・名称。
    返り値: strはMarkdownリンク。
    """
    return f'[{label}](<{Path(os.path.relpath(path,study)).as_posix()}>)'


def render(data: dict, study: Path) -> str:
    """
    機能: 仮説/4結果/参加差/根拠への導線を小型READMEへ生成する。
    引数: data(dict)、study(Path)は検査済12正本と生成先。
    返り値: strは全件転記しないREADME。
    """
    value=data['values']['result'];negative=sum(value['比較'][k]['費用後損益円']<0 for k in KEYS)
    lines=['# 00092：価格帯奪還と保持後の独立再開','','旧89 E1/G1と、現在E0＋独立i/p・H奪還→P下の保持→P越えvを比較した。H1は旧E1への追加ANDではない。両案は初回を除く15分新規、元Source現在量・永久seen・同時一玉、共通G1を使う。','',result_block(value),'',
      '**全4会計が赤字。安定利益は未確認。**' if negative==4 else '**赤字会計あり。安定利益は未確認。**' if negative else '既使用66場の探索結果。安定利益は別期間での検証を要する。','',
      '| 比較 | 同実玉 | 取得変更 | H0のみ/H1のみ | 同実出口差円 | 全差円 |','| --- | ---: | ---: | --- | ---: | ---: |']
    if str(value.get('状態','')).startswith('人工'):lines[2:2]=['**生成器の人工正本による表示試験。実市場の結果ではない。**','']
    for d in (0,1):
        v=value['出口間の同実新規分解'][f'H1G1対H0G1_D{d}'];lines.append(f"| D{d} | {v['同実新規']} | {v['共通だが取得変更']} | {v['Aのみ']}/{v['Bのみ']} | {amount(v['同実新規出口差円'])} | {amount(v['全差円'])} |")
    lines+=['','同実入口は要求時計・方向・取得時計/価格/量・実Index/物理Lineまで同じ群。取得の遅れや片側参加を出口効果へ混ぜない。','',
      '費用後現在単価益strict正で最低建値床、G1部分収穫・実確定益予算・ATR/125pt/3分失敗/Source返済を旧89から直接再用。往復122円/実枚（1pt10円、片道手数料11円＋滑り5pt）。売買は符号反転の同条件。ラージ気配のmicro代理約定で、床の起動は黒字約定の保証ではない。','',
      '保存132対照・264会計、金融原板一走査＋Source/event/独立価格一走査、Viewer264資源を照合済み。人工の部分scopeは全面検査と区別する。指標全前史・Source生成は固定数値器/seed/元driver同値へ依存する。可用性は候補の計数であり、実注文数や運用損益ではない。','',
      '!'+link(study,data['paths']['figure'],'全66場の累積費用後損益'),'']
    labels={'result':'結果正本','cash':'会計照合','raw':'金融原板','source':'Source・公開価格原板','saved':'基準と保存判断','viewer':'Viewer照合','condition':'固定条件','input_ref':'入力参照','plan':'検証計画','settings_before':'全設定と結果','availability':'可用性前検査'}
    lines+=[' / '.join(link(study,data['paths'][n],label) for n,label in labels.items()),'', '[入口と回収の診断](入口と回収の診断.md)は保存結果の記述統計で、12入力の独立監査とは区別する。','', '[再現補足](再現補足.md)の12明示入力で--run後に--check。[生成証拠](レポート生成証拠.json)に入力・依存コード・出力SHAを記録。市場/原板/APIの再実行0。',''];return '\n'.join(lines)


def generate(paths: dict, check: bool) -> dict:
    """
    機能: 検証後にREADME/設定マーカー/生成証拠だけを生成又は一致照合する。
    引数: paths(dict[str,Path])、check(bool)は12正本と照合指定。
    返り値: dictは生成証拠。11正本はbyte不変、設定は結果部分だけ可変。
    """
    data=prepare(paths);study=paths['plan'].parent;result=with_note(marker(data['pre'],result_block(data['values']['result'])));readme=render(data,study)
    outputs={study/'README.md':readme,study/'設定と結果.md':result};proof={'試行':92,'成功':True,'明示入力数':12,'場数':66,'会計数':264,'入力':{n:str(p) for n,p in paths.items()},'入力SHA256':data['hashes'],
      '設定入力指紋':'settings_beforeは固定先頭注記だけ除去し結果を未実行文へ復元したbb02事前本文。初回/生成後共通。','事前設定表SHA256':PRE_SHA,'版5':{'手法':55,'尺度':9,'セル':495,'設定':44,'複合評価':4},'金融固定コード数':len(data['core']),'依存コードSHA256':data['core'],'生成コードSHA256':sha(Path(__file__)),
      '出力SHA256':{p.name:hashlib.sha256(t.encode('utf-8')).hexdigest() for p,t in outputs.items()},'設定マーカー外不変':marker(data['pre'],'')==marker(without_note(result),''),'表示注記追加':NOTE,'設定外の比較範囲':'固定先頭注記1件を除く事前本文','新市場再生':0,'原板読取':0,'新API取得':0}
    outputs[study/'レポート生成証拠.json']=json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if check:
        for p,text in outputs.items():need(p.is_file() and p.read_text(encoding='utf-8')==text,'生成内容差:'+p.name)
    else:
        for p,text in outputs.items():p.write_text(text,encoding='utf-8',newline='\n')
    for n,p in paths.items():need(settings(p.read_text(encoding='utf-8'))==data['pre'] if n=='settings_before' else sha(p)==data['raw_hashes'][n],'生成前後の正本変更:'+n)
    need(all(sha(ROOT/p)==h for p,h in data['core'].items()),'生成前後のcore変更');return proof


def main() -> None:
    """
    機能: 12明示Pathだけで保存生成又は照合を行う。
    引数: NAMESの12必須Path、--run/--check(bool)はCLI入力。
    返り値: None。不整合は非0。原板/売買/ネットワークを起動しない。
    """
    p=argparse.ArgumentParser(description='92の12正本から小型帳票を生成')
    for n in NAMES:p.add_argument('--'+n.replace('_','-'),type=Path,required=True)
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--run',action='store_true');mode.add_argument('--check',action='store_true');a=p.parse_args();v=generate({n:getattr(a,n).resolve() for n in NAMES},a.check);print(json.dumps({k:v[k] for k in ('試行','成功','明示入力数','会計数','設定マーカー外不変')},ensure_ascii=False))


if __name__=='__main__':main()
