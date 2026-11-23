"""141金融前の固定追加入力をF0復元先へ結ぶ。金融や自然Sourceは実行しない。"""
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
    機能: 復元先内へ同体原文だけを置く。
    引数: root(Path)、name(str)、raw(bytes)。
    返り値: None。既存は同体のみ許す。
    """
    target=(root/name).resolve();assert target.is_relative_to(root);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():assert target.read_bytes()==raw
    else:
        with target.open('xb') as f:f.write(raw)


# ----------------------------------------
def main() -> None:
    """
    機能: 51/127直接源を復元するか、Source大JSONだけを省略して50源復元する。
    引数: CLI --destination(Path)、--with-source(bool)。既存F0復元先も可。
    返り値: None。CSV/Raw/177MB/実行体を複写せず、Source/金融は実行しない。
    """
    p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True);p.add_argument('--with-source',action='store_true');args=p.parse_args()
    dest=args.destination.resolve();assert dest.is_relative_to(ROOT/'work')
    if not dest.exists():
        subprocess.run([sys.executable,'-X','utf8',str(FORMAL/'再現資料/F0保存資料を復元する.py'),'--destination',str(dest),'--with-preparation'],check=True)
    else:assert (dest/'F0保存資料の復元確認.json').is_file()
    m=json.loads((FORMAL/'保管索引.json').read_bytes())
    groups=[m['F1増分固定資料']]+m['F1共有コード']
    for item in groups:
        archive=ROOT/item['保存元ZIP'] if '保存元ZIP' in item else FORMAL/'再現資料'/item['ZIP']
        assert sha(archive.read_bytes())==item['ZIP_SHA256']
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for entry in item['格納源']:
                raw=z.read(entry.get('ZIP内path',entry.get('path')));assert sha(raw)==entry['sha256']
                put(dest,entry.get('復元先',entry.get('path')),raw)
    skipped=[]
    for item in m['F1追加入力']+m['F1共有入力']:
        raw=(ROOT/item['保存元']).read_bytes();assert sha(raw)==item['保存SHA256']
        if item['復元先'].endswith('/V0の出生と取得.json') and not args.with_source:
            skipped.append(item['復元先']);continue
        decoded=gzip.decompress(raw) if item['形式']=='gzip' else raw;assert sha(decoded)==item['解凍SHA256'];put(dest,item['復元先'],decoded)
    original=(FORMAL/'検査/F1金融前.json').read_bytes();assert sha(original)==m['F1_SHA256'];put(dest,'元F1金融前.json',original)
    f1=json.loads(original);original_f0=(FORMAL/'検査/F0出生前.json').read_bytes();assert sha((dest/'元F0出生前.json').read_bytes())==sha(original_f0)
    source_root=next(Path(n).parents[2] for n in f1['ファイル'] if n.endswith('00141_VWMA基準の受容と再加速から独立入口を生む\\README.md'))
    external={x['path'] for x in m['共用CSV参照']};excluded={x['path'] for x in m['意図して複製しない固定源']};mapped={}
    for name,h in f1['ファイル'].items():
        if name in external:continue
        relative=Path(name).relative_to(source_root).as_posix()
        if relative in excluded or relative in skipped:continue
        target=dest/relative;assert sha(target.read_bytes())==h;mapped[str(target)]=h
    assert len(mapped)==(51 if args.with_source else 50)
    ledger={'用途':'金融前F1ではない。保存入力の復元だけの参照台帳','元F1_SHA256':sha(original),'ファイル':mapped,
        '外部CSV非複製':73,'177MB/2exe非複製':sorted(excluded),'Source非展開':skipped,'Source/金融実行可としない':True}
    put(dest,'F1復元だけの参照台帳.json',(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    proof={'成功':True,'試行':141,'F1復元直接源数':len(mapped),'F1直接源数':127,'Source同体展開':args.with_source,
        'F0/F1/正式3MDの原文改変':False,'CSV/Raw/177MB/2exe読取又は複製':False,'Source/金融を実行':False,'追加2場読取':False,
        'F1_SHA256':sha(original),'保管索引SHA256':sha((FORMAL/'保管索引.json').read_bytes())}
    raw=(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode('utf-8');put(dest,'F1保存資料の復元確認.json',raw)
    print(json.dumps({'成功':True,'F1直接源復元数':len(mapped),'復元確認SHA256':sha(raw),'金融実行':False},ensure_ascii=False))


if __name__=='__main__':main()
