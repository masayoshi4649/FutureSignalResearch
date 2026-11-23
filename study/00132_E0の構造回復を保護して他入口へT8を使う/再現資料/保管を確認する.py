"""132の非金融同体正本・実復元・条件セル・関連診断の保管を確認する。"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
import re
import zipfile


def sha(body: bytes) -> str:
    """
    機能: bytesのSHA256を返す。
    引数: body(bytes)。
    返り値: str。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def main() -> None:
    """
    機能: 公式復元先の同体再実行結果を正本へ照合し、未作成証跡へ保存する。
    引数: CLI --restored(Path)は復元と非金融再実行済み先、--output(Path|None)は新規証跡。
    返り値: None。金融・Raw・CSV生成・F1作成は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--restored', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    formal = Path(__file__).resolve().parent.parent
    root = formal.parents[1]
    restored = args.restored.resolve()
    assert restored.is_relative_to(root / 'work') and restored.is_dir()
    manifest = json.loads((formal / '保管索引.json').read_bytes())
    assert manifest['試行'] == 132 and manifest['金融前F1'] is None
    assert not manifest['金融実行'] and not manifest['新CSV生成']
    assert not list(formal.rglob('*F1*')) and not list(formal.rglob('*.csv'))
    packed = (formal / '検査/方向の同体検査.json.gz').read_bytes()
    assert sha(packed) == manifest['方向証跡gzipSHA256']
    original = gzip.decompress(packed)
    assert sha(original) == manifest['方向証跡解凍SHA256'] == 'cf24a024311a072216a7efdffff8df3ff36c59994cd8916327ddb965e5d38782'
    path = restored / 'work/E0の構造回復を保護する切替案/方向の同体検査.json'
    assert path.read_bytes() == original
    proof = json.loads(original)
    assert proof['人工検査成功'] == 8 and proof['固定取得'] == 79 and proof['固定場'] == 73
    assert proof['E0保護の適用'] == 9 and proof['T8から方向変更'] == 0 and proof['全79方向同体']
    assert not proof['金融結果読取'] and not proof['Raw読取'] and not proof['新CSV生成']
    assert len(proof['方向票']) == 79 and len({r['セッション'] for r in proof['方向票']}) == 73
    assert all(r['P0'] == r['T8'] and r['R0'] == -r['P0'] for r in proof['方向票'])
    for name, value in proof['入力前後SHA256'].items():
        assert sha((root / name).read_bytes()) == sha((restored / name).read_bytes()) == value
    archives = manifest['コード']
    archive = formal / '再現資料' / archives['ZIP']
    assert sha(archive.read_bytes()) == archives['ZIP_SHA256']
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None and len(z.namelist()) == archives['格納源数']
        for item in archives['格納源']:
            body = z.read(item['path'])
            assert len(body) == item['bytes'] and sha(body) == item['sha256']
            assert (restored / item['path']).read_bytes() == body
    cells = {}
    for line in (formal / '設定と結果.md').read_text('utf-8').splitlines():
        if re.match(r'^\| [A-Z][0-9]{2} ', line):
            fields = [x.strip() for x in line.split('|')[1:-1]]
            if len(fields) == 11:
                assert fields[0] not in cells
                cells[fields[0]] = fields[2:]
    assert len(cells) == 56 and cells == manifest['504セル基準']
    typed = gzip.decompress((formal / '根拠/入口型の追補/入口型の診断.json.gz').read_bytes())
    assert sha(typed) == manifest['関連する旧T8型別診断の解凍SHA256']
    related = json.loads(typed)
    assert related['success'] and related['all_rows'] == 79 and related['all_sessions'] == 73
    assert not related['new_policy_evaluation']
    links = 0
    for p in list(formal.rglob('*.md')) + [root / 'docs/議論/E0保護の方向同体と期限補完に残る逆行.md']:
        for target in re.findall(r'\]\(([^)]+)\)', p.read_text('utf-8')):
            if target.startswith(('http://', 'https://', '#')):
                continue
            assert (p.parent / target.split('#')[0]).resolve().exists(), (p, target)
            links += 1
    for name in ('README.md', 'docs/README.md', 'docs/議論/README.md', 'study/README.md'):
        assert formal.name in (root / name).read_text('utf-8')
    value = {'成功': True, '試行': 132, '確認UTC': datetime.now(timezone.utc).isoformat(),
             '方向同体正本SHA256': sha(original), '実復元再実行proof同体': True,
             '人工検査': 8, '非金融源の同体': 3, '全取得': 79, '全場': 73,
             'E0保護適用': 9, '実方向変更': 0, '504セル不変': True,
             'コードZIP_SHA256': archives['ZIP_SHA256'], 'コード原文源': archives['格納源数'],
             '相対リンク確認数': links, '金融前F1': None, '132金融実行': False,
             '新CSV生成': False, 'Raw読取': False, '旧T8型別関連診断を区別': True,
             '重大不足': [], '確認コードSHA256': sha(Path(__file__).read_bytes())}
    destination = args.output.resolve() if args.output else formal / '検査/保管復元の確認.json'
    assert destination.is_relative_to(root) and not destination.exists()
    with destination.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2); handle.write('\n')
    print(json.dumps({'成功': True, '確認': str(destination), 'SHA256': sha(destination.read_bytes()),
                      '方向変更': 0, 'F1': None, '金融実行': False, '相対リンク': links}, ensure_ascii=False))


if __name__ == '__main__':
    main()
