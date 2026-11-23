"""全83場から事前固定位置を取り、未来の切落し・価格変更に対する不変性を確認する。"""
from pathlib import Path
import gzip
import hashlib
import json
import numpy as np
from 特徴核 import features

ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'inputs/00206_両指数の固定端点相対変化'


# ----------------------------------------
def fingerprint(path: Path) -> dict:
    """
    機能: 内容の指紋を得る。
    引数: path(Path)は対象。
    返り値: dict。
    """
    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,'sha256':sha}


# ----------------------------------------
def main() -> None:
    """
    機能: 各商品各場の先頭/三分点/末尾q0で未来変更の不変性を確認する。
    引数: なし。
    返り値: None。損益や結果を見て検査点を選ばない。生産値の独立算術検査は別Source。
    """
    plan=json.loads(gzip.decompress((DEST/'抽出前固定.json.gz').read_bytes()))
    done=json.loads((DEST/'完了.json').read_text(encoding='utf-8'));outputs={(r['symbol'],r['session']):r['file'] for r in done['files']}
    checks=[];cells=0
    for scene in plan['scenes']:
        raw={}
        for symbol,r in scene['sources'].items():
            p=ROOT/r['path'];assert fingerprint(p)['sha256']==r['sha256']
            with np.load(p,allow_pickle=False) as z:raw[symbol]={k:z[k].copy() for k in z.files}
        for symbol in ('NK225','TOPIX'):
            peer='TOPIX' if symbol=='NK225' else 'NK225';rows=scene['q0'][symbol];n=len(rows)
            p=ROOT/outputs[(symbol,scene['session'])]['path']
            with np.load(p,allow_pickle=False) as z:saved={k:z[k].copy() for k in z.files}
            for qi in sorted({0,n//3,2*n//3,n-1}):
                q=rows[qi];own=raw[symbol];other=raw[peer]
                a=int(np.searchsorted(own['line'],q['line']))+1
                later=np.flatnonzero(np.isfinite(other['now'])&(other['now']>q['time']-1))
                b=int(later[0]) if len(later) else len(other['now'])
                before_a={k:v[:a].copy() for k,v in own.items()};before_b={k:v[:b].copy() for k,v in other.items()}
                prefix,_=features(before_a,before_b,[q],scene['start'],scene['end'])
                changed_a={k:v.copy() for k,v in own.items()};changed_b={k:v.copy() for k,v in other.items()}
                changed_a['last'][a:]=1e8;changed_b['last'][b:]=1e-8
                changed,_=features(changed_a,changed_b,[q],scene['start'],scene['end'])
                for name,value in prefix.items():
                    np.testing.assert_array_equal(value,saved[name][qi:qi+1],err_msg=f'{symbol}/{scene["session"]}/{qi}/{name}/prefix')
                    np.testing.assert_array_equal(changed[name],value,err_msg=f'{symbol}/{scene["session"]}/{qi}/{name}/future')
                    cells+=2*value.size
                checks.append({'symbol':symbol,'session':scene['session'],'q0_index':qi,'line':q['line'],'time':q['time'],
                    '自己prefix原行':int(own['line'][a-1]),'相手価格prefix最終原行':int(other['line'][b-1]) if b else None,'成功':True})
        for r in scene['sources'].values():assert fingerprint(ROOT/r['path'])['sha256']==r['sha256']
    proof={'試行':206,'成功':True,'金融参照':False,'検査点規則':'各商品各場のq0添字 0,n//3,2*n//3,n-1。結果では選ばない。',
        '実点数':len(checks),'照合属性':cells,'切落しと未来価格変更で不変':True,'原入力変更なし':True,
        '時計の限界':'相手は価格時計prefixであり受信prefixではない。異商品原行番号の大小を先後に使わない。',
        'Source':fingerprint(Path(__file__)),'生産核':fingerprint(Path(__file__).with_name('特徴核.py')),
        '抽出前固定':fingerprint(DEST/'抽出前固定.json.gz'),'点別':checks}
    p=DEST/'実prefix確認.json';body=json.dumps(proof,ensure_ascii=False,indent=2)+'\n'
    if p.exists():assert p.read_text(encoding='utf-8')==body
    else:p.write_text(body,encoding='utf-8')
    print(json.dumps({'成功':True,'実点数':len(checks),'照合属性':cells},ensure_ascii=False),flush=True)


# ----------------------------------------
if __name__=='__main__':main()
