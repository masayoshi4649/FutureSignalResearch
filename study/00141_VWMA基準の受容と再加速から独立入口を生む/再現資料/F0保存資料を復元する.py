"""141の出生前固定小資料を恒久先から新規workへ復元する。自然再生は行わない。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
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
    機能: 復元先の内側だけへ原文を書く。
    引数: root(Path)、name(str)、raw(bytes)。
    返り値: None。同名既存は同体のみ許す。
    """
    path=(root/name).resolve();assert path.is_relative_to(root)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==raw
    else:
        with path.open('xb') as f:f.write(raw)


# ----------------------------------------
def main() -> None:
    """
    機能: F0直接小型36源とビルド継承源を復元し、元指紋へ照合する。
    引数: CLI --destination(Path)、--with-preparation(bool)。
    返り値: None。CSV/Raw/177MB/実行体/Source/金融を読み出し又は実行しない。
    """
    p=argparse.ArgumentParser(description='141 F0小型保存資料の復元')
    p.add_argument('--destination',type=Path,required=True);p.add_argument('--with-preparation',action='store_true');args=p.parse_args()
    dest=args.destination.resolve();assert dest.is_relative_to(ROOT/'work') and not dest.exists();dest.mkdir(parents=True)
    m=json.loads((FORMAL/'保管索引.json').read_bytes())
    groups=[m['追加固定資料'],m['共有固定コード'],m['kernel共有源']]
    if args.with_preparation:groups.append(m['出生後段の準備資料'])
    for item in groups:
        archive=ROOT/item['保存元ZIP'] if '保存元ZIP' in item else FORMAL/'再現資料'/item['ZIP']
        assert sha(archive.read_bytes())==item['ZIP_SHA256']
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for entry in item['格納源']:
                raw=z.read(entry.get('ZIP内path',entry.get('path')));assert sha(raw)==entry['sha256']
                put(dest,entry.get('復元先',entry.get('path')),raw)
    for item in m['共有入力']+m['新共用入力']:
        raw=(ROOT/item['保存元']).read_bytes();assert sha(raw)==item['保存SHA256']
        decoded=gzip.decompress(raw) if item['形式']=='gzip' else raw;assert sha(decoded)==item['解凍SHA256']
        put(dest,item['復元先'],decoded)
    original=(FORMAL/'検査/F0出生前.json').read_bytes();assert sha(original)==m['F0_SHA256'];put(dest,'元F0出生前.json',original)
    f0=json.loads(original);omitted={x['path'] for x in m['意図して複製しない固定源']};mapped={}
    source_root=next(Path(n).parents[2] for n in f0['ファイル'] if n.endswith('00141_VWMA基準の受容と再加速から独立入口を生む\\README.md'))
    external={x['path']:x['sha256'] for x in m['共用CSV参照']}
    for name,h in f0['ファイル'].items():
        if name in external:assert external[name]==h;continue
        relative=Path(name).relative_to(source_root).as_posix()
        if relative in omitted:assert not (dest/relative).exists();continue
        target=dest/relative;assert sha(target.read_bytes())==h;mapped[str(target)]=h
    assert len(mapped)==36 and len(external)==73 and len(omitted)==3
    table={'用途':'Source実行前固定ではなく、F0保存資料を別pathへ復元した参照台帳。自然再生不可',
        '元F0_SHA256':sha(original),'復元ファイル':mapped,'外部CSV指紋のみ':external,'未複製':sorted(omitted),
        '原F0を書換/事前固定を後造り':False}
    put(dest,'復元だけの参照台帳.json',(json.dumps(table,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    proof={'成功':True,'試行':141,'F0小型36/112源同体復元':True,'共用CSV73を読取/複写':False,'177MB/2exeを読取/複写':False,
        'Source/金融/ビルドの実行':False,'追加2場読取':False,'正式3MDはF0原文':True,'元F0_SHA256':sha(original),
        '後段準備復元':args.with_preparation,'保管索引SHA256':sha((FORMAL/'保管索引.json').read_bytes())}
    raw=(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode('utf-8');put(dest,'F0保存資料の復元確認.json',raw)
    print(json.dumps({'成功':True,'復元確認SHA256':sha(raw),'F0小型復元数':36,'自然実行':False},ensure_ascii=False))


if __name__=='__main__':main()
