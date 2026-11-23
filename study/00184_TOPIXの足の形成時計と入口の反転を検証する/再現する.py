"""正式Sourceと恒久入力だけでTOPIX183/184を再生し、保存正本と照合する。"""
from pathlib import Path
from copy import deepcopy
import argparse,gzip,hashlib,importlib,json,sys,zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
S183=ROOT/'study/00183_単純IFDで両指数の入口と損失安定性を検証する/TOPIX'
INPUT=ROOT/'inputs/TOPIX原順8列_20260921_20261116'


def read(p):
    """
    機能: JSONを読む。
    引数: p(Path)。
    返り値: objectは正本内容。
    """
    data=p.read_bytes();return json.loads(gzip.decompress(data) if p.suffix=='.gz' else data)


def sha(p):
    """
    機能: SHA256を得る。
    引数: p(Path)。
    返り値: str。
    """
    return hashlib.sha256(p.read_bytes()).hexdigest()


def expand(archive,target,wanted=None):
    """
    機能: 固定Sourceを専有作業領域へ安全に配置する。
    引数: archive,target(Path),wanted(set[str]|None)。
    返り値: intは保存数。既存差分は上書きしない。
    """
    count=0
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():
            if wanted is not None and member not in wanted:continue
            destination=(target/member).resolve();assert destination.is_relative_to(target.resolve())
            data=z.read(member);destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists():assert destination.read_bytes()==data,destination
            else:destination.write_bytes(data)
            count+=1
    return count


def main():
    """
    機能: 既存workを参照せず原順入力から純特徴/全金融を検算する。
    引数: CLI --pure(bool)は特徴再生成、--financial(bool)は全156金融、--output(str)は専有先。
    返り値: None。検査票を専有workへ保存する。
    """
    ap=argparse.ArgumentParser();ap.add_argument('--pure',action='store_true');ap.add_argument('--financial',action='store_true')
    ap.add_argument('--output',default='work/TOPIX183184正式再現');args=ap.parse_args()
    output=(ROOT/args.output).resolve();assert output.is_relative_to((ROOT/'work').resolve())
    output.mkdir(parents=True,exist_ok=True);sourcechecks=0
    for base in (S183,HERE):
        with zipfile.ZipFile(base/'Source.zip') as z:
            for row in read(base/'Source索引.json'):
                assert hashlib.sha256(z.read(row['元相対パス'])).hexdigest()==row['sha256'];sourcechecks+=1
        expand(base/'Source.zip',output)
    common=ROOT/'study/00183_単純IFDで両指数の入口と損失安定性を検証する/Source/NK225/新規Source.zip'
    expand(common,output,{'work/183損失安定性/安定性183.py','work/183損失安定性/新候補の集計を独立検査する.py','work/183損失安定性/順位方針.json'})
    expected=read(S183/'金融開始前固定_実装修正1.json')['安定性']
    assert sha(output/'work/183損失安定性/安定性183.py')==expected;sourcechecks+=1
    entries=deepcopy(read(S183/'入力台帳.json')['entries']);mapping={r['session']:r for r in read(INPUT/'台帳.json')['entries']}
    for e in entries:
        row=mapping[e['session']];p=ROOT/row['path'];assert sha(p)==row['sha256']==e['sha256_cache']
        e['cache_absolute']=str(p)
    assert sha(INPUT/'純特徴183.json.gz')==read(S183/'条件_実装修正1.json')['純特徴SHA']
    assert sha(INPUT/'純特徴184直接.json.gz')==read(HERE/'条件.json')['直接純SHA']
    sys.path[:0]=[str(output/'work/183TOPIX'),str(output/'work/184TOPIX')]
    M=importlib.import_module('入口とIFD');F=importlib.import_module('金融を比較する');D=importlib.import_module('直接形成184')
    pure=[read(INPUT/'純特徴183.json.gz'),read(INPUT/'純特徴184直接.json.gz')]
    report={'成功':True,'Source照合':sourcechecks,'入力照合':len(entries),'既存workへの入力依存':False,
       '環境':{'Python':sys.version,'NumPy':__import__('numpy').__version__},'純特徴SHA':[sha(INPUT/'純特徴183.json.gz'),sha(INPUT/'純特徴184直接.json.gz')]}
    if args.pure:
        counts=[]
        for mode in range(2):
            channels={s:M.Channel() for s in (5,15,30)};contract=None;rows=[]
            for e in entries:
                if contract!=e['in_session_contract_codes']:
                    channels={s:M.Channel() for s in (5,15,30)};contract=e['in_session_contract_codes']
                part,_=(M.bars_and_features if mode==0 else D.direct_features)(e,channels)
                for r in part:
                    plus=M.roles(r,1);minus=M.roles(r,-1)
                    r['signals']=[1 if a and not b else -1 if b and not a else 0 for a,b in zip(plus,minus)]
                rows+=part
            assert rows==pure[mode],f'純特徴{mode}';counts.append(len(rows));print('純特徴照合',mode,len(rows),flush=True)
        report['純特徴再生成照合']=counts
    if args.financial:
        meta=F.sessions(entries);by={k:{s['scene']:[] for s in meta} for k in range(2)}
        for k,rows in enumerate(pure):
            for r in rows:by[k][r['session']].append(r)
        packs={}
        for case in range(4):
            for i,name in enumerate(M.NAMES):
                for w in M.WIDTHS:
                    ident=f'TOPIX183_{name}_W{w:g}_H60' if case==0 else f'TOPIX184_C{case}_{name}_W{w:g}_H60'
                    packs[(case,i,w)]=F.empty(ident,meta)
        for e in entries:
            route=M.Route(e);cache={}
            for (case,ci,w),pack in packs.items():
                busy=-float('inf');accepted=blocked=expired=signals=0
                for r in by[0 if case<2 else 1][e['session']]:
                    side=r['signals'][ci]*(-1 if case in (1,3) else 1)
                    if not side:continue
                    signals+=1
                    if r['time']<=busy:blocked+=1;continue
                    key=(r['time'],r['line'],side,w)
                    if key not in cache:cache[key]=route.cell(*key)
                    cell=cache[key]
                    if cell is None:expired+=1;continue
                    accepted+=1;F.append(pack,cell);busy=route.end if cell['unknown'] else cell['exit_time']
                pack['diagnostics'].append({'scene':e['session'],'純成立':signals,'保有棄却':blocked,'取得':accepted,'失効':expired})
            print('金融再生',e['session'],flush=True)
        reference={r['id']:r for r in read(S183/'全39組短表.json.gz')['rows']}
        reference.update({r['id']:r for r in read(HERE/'全156組短表.json.gz')['rows'] if r['case']!=0})
        periods={'全80':[s['scene'] for s in meta[:-1]],'前48':[s['scene'] for s in meta[:48]],
          '後25':[s['scene'] for s in meta[48:73]],'追加7':[s['scene'] for s in meta[73:80]],'本日1':[meta[-1]['scene']]}
        financechecks=fullpacks=0
        for pack in packs.values():
            stat=F.A.evaluate_pack(pack,periods);r=reference[pack['id']]
            assert {k:F.terse(v) for k,v in stat['groups'].items()}==r['全81'];financechecks+=1
            assert {p:{k:F.terse(v) for k,v in b.items()} for p,b in stat['periods'].items()}==r['期間'];financechecks+=1
            selected=(S183 if pack['id'].startswith('TOPIX183') else HERE)/'金融正本'/(pack['id']+'.json.gz')
            if selected.exists():assert pack==read(selected);fullpacks+=1
        report['金融候補再生成照合']=len(packs);report['全体と期間集計照合']=financechecks;report['選択全件台帳照合']=fullpacks
    (output/'再現確認.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
