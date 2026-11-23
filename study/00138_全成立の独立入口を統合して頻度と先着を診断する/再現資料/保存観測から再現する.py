"""138を共有保存資料から新規workへ復元し、保存833観測だけで再集計する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import zipfile

FORMAL = Path(__file__).resolve().parent.parent
ROOT = FORMAL.parents[1]


def sha(body: bytes) -> str:
    """
    機能: 保存原文の指紋を求める。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def put(root: Path, name: str, body: bytes) -> None:
    """
    機能: 新規作業先内へ同体原文だけを置く。
    引数: root(Path)、name(str)、body(bytes)。
    返り値: None。既存は同体だけ許す。
    """
    target = (root / name).resolve(); assert target.is_relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == body
    else:
        with target.open('xb') as handle:
            handle.write(body)


# ----------------------------------------
def main() -> None:
    """
    機能: 47直接源と継承源を復元し、任意で保存観測を再集計する。
    引数: CLI --destination(Path)、--replay/--with-features/--with-post(bool)。
    返り値: None。Raw/巨大入力/新観測は作らない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, required=True)
    for name in ('replay', 'with-features', 'with-post'):
        parser.add_argument('--' + name, action='store_true')
    args = parser.parse_args(); destination = args.destination.resolve()
    assert destination.is_relative_to(ROOT / 'work') and not destination.exists()
    destination.mkdir(parents=True)
    m = json.loads((FORMAL / '保管索引.json').read_bytes())
    groups = [('新', m['追加固定資料']), ('共有', m['共有固定コード']), ('継承', m['後段再現用の継承源'])]
    if args.with_post:
        groups.append(('新', m['後発資料']))
    for kind, item in groups:
        path = FORMAL / '再現資料' / item['ZIP'] if kind == '新' else ROOT / item['保存元ZIP']
        assert sha(path.read_bytes()) == item['ZIP_SHA256']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            for source in item['格納源']:
                name = source['ZIP内path'] if kind == '共有' else source['path']
                target = source['復元先'] if kind == '共有' else source['path']
                body = z.read(name); assert sha(body) == source['sha256']
                put(destination, target, body)
    inputs = m['共有入力'] + m['新共用入力'] + [m['保存済み正逆観測']]
    if args.with_post:
        inputs += m.get('追加の検算用共有参照', [])
    if args.with_features:
        inputs.append(m['特徴診断入力'])
    for item in inputs:
        body = (ROOT / item['保存元']).read_bytes(); assert sha(body) == item['保存SHA256']
        decoded = gzip.decompress(body) if item['形式'] == 'gzip' else body
        assert sha(decoded) == item['解凍SHA256']
        put(destination, item['復元先'], decoded)
    original = (FORMAL / '検査/F1.json').read_bytes(); assert sha(original) == m['F1_SHA256']
    put(destination, '原金融前F1.json', original); f1 = json.loads(original)
    old_root = next(Path(p).parents[2] for p in f1['ファイル'] if p.endswith('00138_全成立の独立入口を統合して頻度と先着を診断する\\README.md'))
    excluded = {x['path'] for x in m['意図して複製しないF1源']}; mapped = {}
    for path, expected in f1['ファイル'].items():
        relative = Path(path).relative_to(old_root).as_posix()
        if relative in excluded:
            assert not (destination / relative).exists(); continue
        target = destination / relative; assert sha(target.read_bytes()) == expected
        mapped[str(target)] = expected
    assert len(mapped) == 47
    proof = {'成功':True,'試行':138,'原F1_SHA256':sha(original),'F1直接47/50源同体':True,
        '未複製源':sorted(excluded),'旧kernel継承源':m['後段再現用の継承源']['格納源数'],
        '原F1改変/事前固定偽造':False,'Raw/177MB/77MB/追加2場読取':False,'新Source/金融観測':False}
    if args.replay:
        ledger = {'用途':'金融後の保存観測再現専用。金融前F1ではない','元F1_SHA256':sha(original),'未複製3源を省略':True,'ファイル':mapped}
        ledger_raw = (json.dumps(ledger,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        ledger_path = destination / '再現専用パス台帳.json'; put(destination, ledger_path.name, ledger_raw)
        fixed = destination/'work/138全成立入口の評価/固定入力_版2/固定取得入力.json';meta = fixed.with_name('入口参照.json')
        result = destination / m['保存済み正逆観測']['復元先']; output = destination / '再集計'
        command = [sys.executable,'-X','utf8',str(destination/'work/138全成立入口と頻度の集計/集計する.py')]
        for name, path in [('f1',ledger_path),('fixed-input',fixed),('metadata',meta),('result',result)]:
            command += ['--'+name,str(path),'--'+name+'-sha256',sha(path.read_bytes())]
        command += ['--output-dir',str(output)]
        completed = subprocess.run(command,cwd=destination,capture_output=True,text=True,encoding='utf-8',check=True)
        generated = json.loads((output/'集計.json').read_bytes()); expected = json.loads((FORMAL/'成果物/集計.json').read_bytes())
        assert generated.pop('F1_SHA256') == sha(ledger_raw); expected.pop('F1_SHA256'); assert generated == expected
        table_sha = sha((output/'CSV用の表.json').read_bytes())
        assert table_sha == 'c8a83240c0345662353af42d5eeafa306bd68a710f53985be01dc0676c5f2f5d'
        proof.update({'保存833観測だけの再集計':True,'全数値/旧対照/phase/頻度一致':True,
            '三表全bytes一致_SHA256':table_sha,'差分はF1参照の再現台帳SHAだけ':True,
            '再現台帳SHA256':sha(ledger_raw),'集計CLI成功':completed.returncode==0})
    put(destination,'保存資料の再現確認.json',(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
