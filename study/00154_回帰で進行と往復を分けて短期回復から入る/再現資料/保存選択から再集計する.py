"""154の保存選択と共有148観測を使い、再選択せず1020比較を再現する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3] if Path(__file__).resolve().parent.name == '再現資料' else Path(__file__).resolve().parents[2]
FORMAL = ROOT / 'study/00154_回帰で進行と往復を分けて短期回復から入る'


def sha(path: Path) -> str:
    """
    機能: 保存実体を固定bufferで指紋照合する。
    引数: path(Path)。返り値: str。
    """
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for body in iter(lambda: source.read(1 << 20), b''):
            digest.update(body)
    return digest.hexdigest()


def ref_index(index: dict) -> dict:
    """
    機能: 正式索引のZIP/gzip/同体保存から元path別の復元票を作る。
    引数: index(dict)。返り値: dict[str,dict]。
    """
    out, pending = {}, [index]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            if '復元先' in item and ('解凍SHA256' in item or 'sha256' in item):
                out.setdefault(item['復元先'], item)
            if '格納源' in item and '保存元ZIP' in item:
                for row in item['格納源']:
                    out[row['path']] = {'保存元ZIP': item['保存元ZIP'], 'ZIP_SHA256': item['ZIP_SHA256'],
                        'ZIP内path': row['ZIP内path'], 'sha256': row['sha256']}
            pending.extend(item.values())
    return out


def restored_body(ref: dict, expected: str) -> bytes:
    """
    機能: 保存元指紋とCRCを検査し必要な小型Source/選択のbytesだけを復元する。
    引数: ref(dict)、expected(str)。返り値: bytes。
    """
    if '保存元ZIP' in ref:
        source = ROOT / ref['保存元ZIP']
        assert sha(source) == ref['ZIP_SHA256']
        with zipfile.ZipFile(source) as archive:
            body = archive.read(ref['ZIP内path'])
    else:
        source = ROOT / ref['保存元']
        assert sha(source) == ref['保存SHA256']
        body = gzip.decompress(source.read_bytes()) if ref['形式'] == 'gzip' else source.read_bytes()
    assert hashlib.sha256(body).hexdigest() == expected
    return body


def main() -> None:
    """
    機能: 未作成出力先へ保存金融を再集計し、正本と三表bytesを照合する。
    引数: CLI --output-dir(Path)。返り値: None。
    不足するwork源のみ復元し、既存不一致源・正式原文・旧試行を上書きしない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    assert args.output_dir.is_relative_to(ROOT) and not args.output_dir.exists()
    index = json.loads((FORMAL / '保管索引.json').read_bytes())
    refs = ref_index(index)
    freeze = json.loads((FORMAL / '検査/F2実金融集計前.json').read_bytes())
    wanted = {p: h for p, h in freeze['ファイル'].items()
              if p.startswith('work/') and (ROOT / p).suffix in ('.py', '.md', '.json')
              and '/入口選択/' not in p}
    selection_rel = 'work/154回帰環境の評価/入口選択/選択対応.json'
    wanted[selection_rel] = 'f1a6d038c1f25ae703b7aef45c41fe4470899a531481abfd735e17c6128df5ea'
    for name in ('F1入口選択後.json', 'F2実金融集計前.json'):
        rel = 'work/154回帰環境の評価/' + name
        wanted[rel] = sha(FORMAL / '検査' / name)
    for rel, expected in wanted.items():
        path = ROOT / rel
        if path.exists():
            assert sha(path) == expected, ('既存源不一致は上書きしない', rel)
            continue
        body = restored_body(refs[rel], expected)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as target:
            target.write(body)
    summary = json.loads((FORMAL / '成果物/集計.json').read_bytes())
    result = ROOT / 'study/00148_全1分知得から入口品質の母集団を固定する/成果物/固定取得の正逆観測.json.gz'
    assert sha(result) == summary['観測物理SHA256']
    runtime = ROOT / 'work/154回帰環境の評価'
    command = [sys.executable, '-X', 'utf8', str(ROOT / 'work/154回帰環境の金融集計/集計する.py'),
        '--preparation-sha256', summary['集計準備SHA256'],
        '--f1', str(runtime / 'F1入口選択後.json'), '--f1-sha256', summary['F1_SHA256'],
        '--f2', str(runtime / 'F2実金融集計前.json'), '--f2-sha256', summary['F2_SHA256'],
        '--selection', str(ROOT / selection_rel), '--selection-sha256', summary['選択対応SHA256'],
        '--generation-dir', str(ROOT / 'inputs/00148_全1分入口母集団'),
        '--result', str(result), '--result-sha256', summary['観測物理SHA256'],
        '--result-decoded-sha256', summary['観測解凍SHA256'], '--output-dir', str(args.output_dir)]
    subprocess.run(command, check=True)
    assert sha(args.output_dir / '集計.json') == sha(FORMAL / '成果物/集計.json')
    table_body = gzip.decompress((FORMAL / '成果物/CSV用の表.json.gz').read_bytes())
    assert (args.output_dir / 'CSV用の表.json').read_bytes() == table_body
    proof = {'成功': True, '試行': 154, '比較数': 1020, '正本と三表bytes再現': True,
             '再選択_新モデル_新学習_新Raw走査': False, '既存源上書き': False,
             '復元検査work源数': len(wanted), '集計SHA256': sha(args.output_dir / '集計.json'),
             '三表SHA256': hashlib.sha256(table_body).hexdigest(), '共有観測は再複写しない': True}
    (args.output_dir / '保存観測からの再現確認.json').write_bytes(
        (json.dumps(proof, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
