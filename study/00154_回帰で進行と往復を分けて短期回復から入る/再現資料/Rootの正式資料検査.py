"""正式保存後の154を、保存担当の復元器を使わず照合する。"""
from pathlib import Path
from urllib.parse import unquote
import gzip
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent.parent
CACHE = {}


def digest(path: Path, decoded: bool = False) -> str:
    """
    機能: 保存実体を全読し、必要ならgzipのCRCと解凍指紋を確認する。
    引数: path(Path)、decoded(bool)。返り値: strはSHA256。
    """
    key = (str(path), decoded)
    if key not in CACHE:
        value = hashlib.sha256()
        with (gzip.open(path, 'rb') if decoded else path.open('rb')) as stream:
            for block in iter(lambda: stream.read(1048576), b''):
                value.update(block)
        CACHE[key] = value.hexdigest()
    return CACHE[key]


# ----------------------------------------
def restored(ref: dict, snapshot: dict) -> tuple[str, str]:
    """
    機能: 明示された恒久実体・gzip・ZIP・文書snapshotを独立に照合する。
    引数: ref/snapshot(dict)。返り値: tuple[str,str]は復元先と解凍指紋。
    """
    dest = ref['復元先']
    if '保存元ZIP' in ref:
        path = ROOT / ref['保存元ZIP']
        assert digest(path) == ref['ZIP_SHA256']
        with zipfile.ZipFile(path) as archive:
            actual = hashlib.sha256(archive.read(ref['ZIP内path'])).hexdigest()
        assert actual == ref['sha256'], dest
    elif ref['形式'] == '文書snapshot':
        assert digest(ROOT / ref['保存元']) == ref['保存SHA256']
        actual = hashlib.sha256(snapshot[ref['抽出キー']].encode('utf-8')).hexdigest()
        assert actual == ref['sha256'], dest
    else:
        path = ROOT / ref['保存元']
        assert digest(path) == ref['保存SHA256'], dest
        assert ref['形式'] in ('同体', 'gzip')
        actual = digest(path, ref['形式'] == 'gzip')
        assert actual == ref['解凍SHA256'], dest
    return dest, actual


# ----------------------------------------
def main() -> None:
    """
    機能: 全159固定参照、条件原文、57×9構造、README数値とリンクを検査する。
    引数: なし。返り値: None。金融再計算・新選択・原板走査は行わない。
    """
    index_path = STUDY / '保管索引.json'
    index_sha = digest(index_path)
    assert index_sha == 'fe8523d9256dadfe4e08afcd9b59e1fb87d3b38181cb4456a731b987628e0ce2'
    index = json.loads(index_path.read_bytes())
    with gzip.open(STUDY / '検査/F0実行前文書.json.gz', 'rt', encoding='utf-8') as stream:
        original = json.load(stream)
    snapshots = {item['path']: item['本文'] for item in original['文書']}
    stage_counts = {}
    for name, stage in index['固定段階'].items():
        freeze_ref = stage['原文']
        assert digest(ROOT / freeze_ref['保存元']) == stage['SHA256']
        frozen = json.loads((ROOT / freeze_ref['保存元']).read_bytes())
        expected = frozen['ファイル']
        refs = stage['全源復元参照']
        found = {}
        for group in ('保存済み参照', '既存恒久正本', '共有源'):
            for ref in refs[group]:
                dest, value = restored(ref, snapshots)
                assert dest not in found
                found[dest] = value
        if refs['新小型源']:
            archive = refs['新小型ZIP']
            assert digest(ROOT / archive['保存元ZIP']) == archive['ZIP_SHA256']
            with zipfile.ZipFile(ROOT / archive['保存元ZIP']) as source:
                for ref in refs['新小型源']:
                    assert ref['path'] not in found
                    value = hashlib.sha256(source.read(ref['path'])).hexdigest()
                    assert value == ref['sha256']
                    found[ref['path']] = value
        assert found == expected, name
        stage_counts[name] = len(found)
    assert stage_counts == {'F0': 42, 'F1': 46, 'F2': 71}
    # ----------------------------------------
    for name in ('条件.md', '設定と結果.md'):
        path = STUDY / name
        old = snapshots[path.relative_to(ROOT).as_posix()]
        assert path.read_bytes().startswith(old.encode('utf-8')), name
    rows = [line for line in snapshots[(STUDY / '設定と結果.md').relative_to(ROOT).as_posix()].splitlines()
        if re.match(r'^\|\s*[A-Z]\d{2}\s*\|', line)]
    assert len(rows) == 57 and all(len(line.strip().strip('|').split('|')) == 11 for line in rows)
    summary_path = STUDY / '成果物/集計.json'
    summary = json.loads(summary_path.read_bytes())
    part, table_rows, cells = 'all', 0, 0
    for line in (STUDY / 'README.md').read_text(encoding='utf-8').splitlines():
        if line.startswith('### 前48'):
            part = 'train'
        if line.startswith('### 後25'):
            part = 'validation'
        fields = [x.strip() for x in line.strip().strip('|').split('|')]
        if not line.startswith('|') or len(fields) != 8 or fields[0] not in summary['集計'][part]:
            continue
        value = summary['集計'][part][fields[0]]['BBO']['3600']['125']
        assert int(fields[1]) == value['entries']
        assert [int(x) for x in fields[2].split('/')] == [value[k] for k in ('forward', 'adverse', 'neither', 'censored')]
        assert fields[3] == (f"{value['resolved_rate'] * 100:.2f}%" if value['resolved_rate'] is not None else '未定義')
        for col, key in ((4, 'ifd_net5_profit'), (5, 'ifd_net5_loss'), (6, 'ifd_net5_sum'), (7, 'ifd_unknown')):
            actual = None if fields[col] == '未定義' else int(fields[col].replace(',', ''))
            assert actual == value[key], (part, fields[0], key)
        table_rows += 1
        cells += 10
    assert table_rows == 33 and cells == 330
    links = 0
    for path in STUDY.glob('*.md'):
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if '://' in target or target.startswith('#'): continue
            resolved = (path.parent / unquote(target.split('#')[0].strip('<>'))).resolve()
            assert resolved.exists(), (path.name, target)
            links += 1
    assert digest(index_path) == index_sha
    output = {'成功': True, '試行': 154, '固定源の独立復元数': stage_counts,
        'F0条件と設定の全原文prefix保持': True, 'V7構造': '57手法×9尺度',
        'README数値表': table_rows, '数値セル': cells, '正式MDの実在リンク': links,
        '索引SHA256': index_sha, '金融正本SHA256': digest(summary_path),
        '独立金融再計算は既存1020比較票': True, '新選択又はRaw走査': False,
        '検査コードSHA256': digest(Path(__file__))}
    target = STUDY / '検査/Rootの正式資料確認.json'
    with target.open('x', encoding='utf-8', newline='\n') as sink:
        json.dump(output, sink, ensure_ascii=False, indent=2)
        sink.write('\n')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
