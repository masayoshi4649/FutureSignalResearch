"""136のF0資料を共有ZIPから新規workへ復元する。Raw/177MB/実行体は複製しない。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import zipfile

FORMAL=Path(__file__).resolve().parent.parent
ROOT=FORMAL.parents[1]


def sha(body: bytes) -> str:
    """
    機能: 復元する原文の指紋を返す。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def put(root: Path, name: str, body: bytes) -> None:
    """
    機能: 作業先内へ同体の原文だけを保存する。
    引数: root(Path)、name(str)は相対位置、body(bytes)。
    返り値: None。既存同名は完全同体だけ許す。
    """
    target=(root/name).resolve();assert target.is_relative_to(root)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        assert target.read_bytes()==body,name
    else:
        with target.open('xb') as handle:handle.write(body)


# ----------------------------------------
def main() -> None:
    """
    機能: F0の直接61源と間接固定共有依存を未作成workへ戻す。
    引数: CLI --destination(Path)、--with-source(bool)は保存済み新Sourceも戻す指定。
    返り値: None。自然走査・金融・コード実行・新F0/F1作成を呼ばない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--with-source',action='store_true')
    args=parser.parse_args();destination=args.destination.resolve()
    assert destination.is_relative_to(ROOT/'work') and not destination.exists()
    destination.mkdir(parents=True)
    m=json.loads((FORMAL/'保管索引.json').read_bytes())
    for key in ('F0追加資料','F0共有コード','間接固定の共有依存'):
        item=m[key]
        path=FORMAL/'再現資料'/item['ZIP'] if key=='F0追加資料' else ROOT/item['保存元ZIP']
        assert sha(path.read_bytes())==item['ZIP_SHA256']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            for source in item['格納源']:
                name=source['path'] if key=='F0追加資料' else source['ZIP内path']
                target=source['path'] if key=='F0追加資料' else source['復元先']
                body=z.read(name);assert sha(body)==source['sha256']
                put(destination,target,body)
    for item in m['F0共有入力']:
        body=(ROOT/item['保存元']).read_bytes();assert sha(body)==item['保存SHA256']
        decoded=gzip.decompress(body);assert sha(decoded)==item['解凍SHA256']
        put(destination,item['復元先'],decoded)
    if '後発資料' in m:
        item=m['後発資料'];path=FORMAL/'再現資料'/item['ZIP']
        assert sha(path.read_bytes())==item['ZIP_SHA256']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            for source in item['格納源']:
                body=z.read(source['path']);assert sha(body)==source['sha256']
                put(destination,source['path'],body)
    f0=(FORMAL/'検査/F0.json').read_bytes();assert sha(f0)==m['F0_SHA256']
    put(destination,'work/136押戻し回復の評価/F0.json',f0)
    if args.with_source:
        item=m['新Source入力']
        body=(ROOT/item['保存元']).read_bytes();assert sha(body)==item['保存SHA256']
        decoded=gzip.decompress(body);assert sha(decoded)==item['解凍SHA256']
        put(destination,item['復元先'],decoded)
    f=json.loads(f0);original_root=next(Path(p).parents[2] for p in f['ファイル'] if p.endswith('study\\00136_押戻し後の回復入口を加えて頻度と先着を比較する\\README.md'))
    excluded={x['path'] for x in m['意図して複製しないF0源']}
    count=0
    for p,h in f['ファイル'].items():
        relative=Path(p).relative_to(original_root).as_posix()
        if relative in excluded:
            assert not (destination/relative).exists()
            continue
        assert sha((destination/relative).read_bytes())==h,relative
        count+=1
    assert count==61
    print(json.dumps({'成功':True,'F0直接61源同体':True,'共有依存':m['間接固定の共有依存']['格納源数'],
                      '復元先':str(destination),'保存Sourceを復元':args.with_source,
                      'Raw/177MB/実行体の複製':False,'Source実行':False,'金融実行':False},ensure_ascii=False))


if __name__=='__main__':
    main()
