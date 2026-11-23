"""130小型コード/方向票と旧共有正本を未作成のworkへ復元する。Rawは読まない。"""
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
    機能: bytesのSHAを返す。
    引数: body(bytes)。返り値: str。
    """
    return hashlib.sha256(body).hexdigest()


def put(root: Path,name: str,body: bytes) -> None:
    """
    機能: 新規作業先内だけへ同体bytesを書き込む。
    引数: root(Path)/name(str)/body(bytes)。返り値: None。
    """
    path=(root/name).resolve();assert path.is_relative_to(root)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==body;return
    with path.open('xb') as stream:stream.write(body)


def main() -> None:
    """
    機能: sourceZIP/共用gzipを照合してworkへ復元し、恒久複製しない。
    引数: --destination(Path)/--inputs-only(bool)。返り値: None。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True,type=Path);parser.add_argument('--inputs-only',action='store_true');args=parser.parse_args()
    dest=args.destination.resolve();assert not dest.exists();dest.mkdir(parents=True)
    folder=FORMAL/'再現資料'
    for indexname in ['コード復元索引.json','追補コード索引.json']:
        p=folder/indexname
        if not p.exists():
            assert indexname=='追補コード索引.json'
            continue
        index=json.loads(p.read_bytes());archive=folder/index['ZIP'];assert sha(archive.read_bytes())==index['ZIP_SHA256']
        with zipfile.ZipFile(archive)as z:
            assert z.testzip() is None
            for x in index['格納源']:
                b=z.read(x['path']);assert sha(b)==x['sha256'];put(dest,x['path'],b)
    manifest=json.loads((FORMAL/'保管索引.json').read_bytes())
    item=manifest['新方向票'];packed=(ROOT/item['path']).read_bytes();assert sha(packed)==item['sha256'];b=gzip.decompress(packed);assert sha(b)==item['decoded_sha256'];put(dest,'work/T8の活動による切替案/choices.json',b)
    for item in manifest['共有参照']:
        b=gzip.decompress((ROOT/item['保存元']).read_bytes());assert sha(b)==item['解凍SHA'];put(dest,item['復元先'],b)
    metadata=manifest['共用metadata'];b=(ROOT/metadata).read_bytes();assert sha(b)==manifest['共用metadata保存SHA'];put(dest,metadata,b)
    put(dest,'work/130既存入口の活動切替評価/F1.json',(FORMAL/'検査/金融前F1.json').read_bytes())
    for source,name in [('方向票の人工検査.json','人工検査.json'),('方向票の準備確認.json','準備の確認.json')]:
        put(dest,'work/T8の活動による切替案/'+name,(FORMAL/'検査'/source).read_bytes())
    if not args.inputs_only:put(dest,'work/130既存入口の活動切替評価/集計.json',(FORMAL/'成果物/集計.json').read_bytes())
    print(json.dumps({'成功':True,'復元先':str(dest),'金融再計算':False,'原板読取':False,'恒久共有正本の複製':False,'作業用の共有正本解凍':4,'保存集計の復元':not args.inputs_only},ensure_ascii=False))


if __name__=='__main__':
    main()
