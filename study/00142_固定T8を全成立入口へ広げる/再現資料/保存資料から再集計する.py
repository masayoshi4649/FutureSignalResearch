"""142の全固定源を共有保存から復元し、保存138実正逆だけで再集計する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import zipfile

FORMAL=Path(__file__).resolve().parent.parent
ROOT=FORMAL.parents[1]


def sha(raw: bytes) -> str:
    """
    機能: 保存原文の指紋を求める。
    引数: raw(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------
def put(root: Path,name: str,raw: bytes) -> None:
    """
    機能: 作業先の内側だけへ同体原文を置く。
    引数: root(Path)、name(str)、raw(bytes)。
    返り値: None。既存は同体だけ許す。
    """
    p=(root/name).resolve();assert p.is_relative_to(root);p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==raw
    else:
        with p.open('xb') as f:f.write(raw)


# ----------------------------------------
def main() -> None:
    """
    機能: F1全30源を復元し、任意で180比較/三表を再現する。
    引数: CLI destination(Path)、replay(bool)。
    返り値: None。新学習/出生/Raw/CSV/金融観測を実行しない。
    """
    p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True);p.add_argument('--replay',action='store_true');args=p.parse_args()
    dest=args.destination.resolve();assert dest.is_relative_to(ROOT/'work') and not dest.exists();dest.mkdir(parents=True)
    m=json.loads((FORMAL/'保管索引.json').read_bytes())
    for item in [m['追加固定資料']]+m['共有固定コード群']:
        archive=ROOT/item['保存元ZIP'] if '保存元ZIP' in item else FORMAL/'再現資料'/item['ZIP'];assert sha(archive.read_bytes())==item['ZIP_SHA256']
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for x in item['格納源']:
                raw=z.read(x.get('ZIP内path',x.get('path')));assert sha(raw)==x['sha256'];put(dest,x.get('復元先',x.get('path')),raw)
    for item in m['共有入力']+m['新共用入力']+[m['元F0の復元参照']]:
        raw=(ROOT/item['保存元']).read_bytes();assert sha(raw)==item['保存SHA256']
        decoded=gzip.decompress(raw) if item['形式']=='gzip' else raw;assert sha(decoded)==item['解凍SHA256'];put(dest,item['復元先'],decoded)
    original=(FORMAL/'検査/F1金融前.json').read_bytes();assert sha(original)==m['F1_SHA256'];f1=json.loads(original);put(dest,'元F1金融前.json',original)
    source_root=next(Path(n).parents[2] for n in f1['ファイル'] if n.endswith('00142_固定T8を全成立入口へ広げる\\README.md'));mapped={}
    for name,h in f1['ファイル'].items():
        target=dest/Path(name).relative_to(source_root);assert sha(target.read_bytes())==h;mapped[str(target)]=h
    assert len(mapped)==30
    proof={'成功':True,'試行':142,'F0全17/F1全30源同体復元':True,'元F1_SHA256':sha(original),'大入力の新恒久複写':False,
        '新学習/Raw/CSV/出生/金融観測':False,'元F0/F1改変/事前固定の後造り':False}
    if args.replay:
        choices=dest/'work/142固定T8の拡張評価/方向票/全752の方向.json';data=json.loads(choices.read_bytes());original_choice_sha=sha(choices.read_bytes())
        data['sources']={str(dest/Path(name).relative_to(source_root)):h for name,h in data['sources'].items()}
        body=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf-8');adapted=dest/'再現用のパス変更方向票.json';put(dest,adapted.name,body);mapped[str(adapted)]=sha(body)
        ledger={'試行':142,'用途':'金融後の保存観測再現用。金融前F1ではない','元F1_SHA256':sha(original),'方向票はsources絶対パスだけ変更':'全752方向/数値/判断は不変','ファイル':mapped}
        path=dest/'再現専用パス台帳.json';put(dest,path.name,(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        model=dest/'work/142固定T8の全成立への方向票/固定条件.json';output=dest/'再集計'
        command=[sys.executable,'-X','utf8',str(dest/'work/142固定T8の全成立への方向票/集計する.py')]
        for name,x in [('f1',path),('model',model),('choices',adapted)]:command += ['--'+name,str(x),'--'+name+'-sha256',sha(x.read_bytes())]
        command += ['--output-dir',str(output)];run=subprocess.run(command,cwd=dest,text=True,encoding='utf-8',capture_output=True);assert run.returncode==0,run.stderr+run.stdout
        new=json.loads((output/'集計.json').read_bytes());old=json.loads((FORMAL/'成果物/集計.json').read_bytes())
        assert old['方向SHA256']==original_choice_sha and old['F1_SHA256']==sha(original)
        for key in ('方向SHA256','F1_SHA256'):new.pop(key);old.pop(key)
        assert new==old and sha((output/'CSV用の表.json').read_bytes())==m['表JSON再現期待SHA256']
        proof.update({'全180比較/参加/頻度/旧120/phase同体':True,'三表JSON全bytes同体':True,'集計の相違はパス台帳/方向票sourcesの2指紋だけ':True,
            '再現台帳SHA256':sha(path.read_bytes()),'元方向票SHA256':original_choice_sha,'再現方向票SHA256':sha(body)})
    raw=(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode('utf-8');put(dest,'保存資料の再現確認.json',raw)
    print(json.dumps({'成功':True,'再現確認SHA256':sha(raw),'再集計':args.replay},ensure_ascii=False))


if __name__=='__main__':main()
