"""135のF1・原文・復元15源・全504セル・独立検算・CSVとリンクを確認する。"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import gzip
import hashlib
import json
import re
import zipfile


def sha(body: bytes) -> str:
    """
    機能: 保管内容の指紋を返す。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def cells(text: str) -> dict:
    """
    機能: 版6の56手法×9尺度を抽出する。
    引数: text(str)。
    返り値: dictは504セル。
    """
    result = {}
    for line in text.splitlines():
        if re.match(r'^\| [A-Z][0-9]{2} ', line):
            p = [x.strip() for x in line.split('|')[1:-1]]
            if len(p) == 11:
                assert p[0] not in result
                result[p[0]] = p[2:]
    assert len(result) == 56
    return result


# ----------------------------------------
def main() -> None:
    """
    機能: 正式保管と復元先を照合し、新規確認票を作る。
    引数: CLI --restored(Path)、--output(Path|None)。
    返り値: None。Raw/巨大入力・新仮説金融・CSV生成を実行しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--restored', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    formal = Path(__file__).resolve().parent.parent; root = formal.parents[1]
    restored = args.restored.resolve(); assert restored.is_relative_to(root / 'work')
    manifest = json.loads((formal / '保管索引.json').read_bytes())
    f1_body = (formal / '検査/F1.json').read_bytes()
    assert sha(f1_body) == '841514160f4ea92036a06688cbce5b1404f6f3ae0040751e0a7aa44b0211a0c2'
    assert (restored / 'work/公表差で反転が不安定な入口を保守化する/F1.json').read_bytes() == f1_body
    f1 = json.loads(f1_body)
    anchor = next(Path(p) for p in f1['ファイル'] if p.endswith('study\\00135_公表差で不安定な方向上書きを抑える\\README.md'))
    old_root = anchor.parents[2]
    for p, expected in f1['ファイル'].items():
        assert sha((restored / Path(p).relative_to(old_root)).read_bytes()) == expected
    assert len(f1['ファイル']) == 15
    snapshot = json.loads(gzip.decompress((formal / '検査/実行前文書.json.gz').read_bytes()))
    assert snapshot['MD数'] == len(snapshot['文書']) == 4
    for item in snapshot['文書']:
        body = item['本文'].encode('utf-8')
        assert len(body) == item['bytes'] and sha(body) == item['sha256']
        assert (restored / item['path']).read_bytes() == body
        if item['path'].endswith('/設定と結果.md'):
            assert cells(item['本文']) == cells((formal / '設定と結果.md').read_text('utf-8'))
    archive_records = {}
    for key in ('共有固定コード','追加固定コード','後発コード'):
        item = manifest[key]
        path = root / item['保存元ZIP'] if key == '共有固定コード' else formal / '再現資料' / item['ZIP']
        assert sha(path.read_bytes()) == item['ZIP_SHA256']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            if key != '共有固定コード': assert len(z.namelist()) == item['格納源数']
            for source in item['格納源']:
                body = z.read(source['path']); assert sha(body) == source['sha256']
                assert (restored / source['path']).read_bytes() == body
        archive_records[key] = {'sha256': item['ZIP_SHA256'], '源数': item['格納源数']}
    assert manifest['共有固定コード']['格納源数'] == 2 and manifest['追加固定コード']['格納源数'] == 7
    for item in manifest['新共用入力'] + manifest['共有参照']:
        body = (root / item['保存元']).read_bytes(); assert sha(body) == item['保存SHA256']
        decoded = gzip.decompress(body) if item['形式'] == 'gzip' else body
        assert sha(decoded) == item['解凍SHA256'] and (restored / item['復元先']).read_bytes() == decoded
    assert len(manifest['新共用入力']) == 2 and len(manifest['共有参照']) == 4
    aggregate_body = (formal / '成果物/集計.json').read_bytes()
    assert sha(aggregate_body) == manifest['集計SHA256'] == '90b8ea3eeff6314b36f15637fcf7608c8336fe0202a9d3b41486ab91330a5c29'
    aggregate = json.loads(aggregate_body); main = aggregate['集計']['all']['U0']['BBO']['3600']['125']
    assert tuple(main[k] for k in ('entries','sessions','forward','adverse','neither','censored','ifd_known','ifd_unknown','ifd_net5_profit','ifd_net5_loss','ifd_net5_sum')) == (79,73,33,23,17,6,76,3,450612,373464,77148)
    assert aggregate['目標判定']['全73場最低1取得'] and not aggregate['目標判定']['両条件達成']
    independent_body = (formal / '検査/独立確認.json').read_bytes()
    assert sha(independent_body) == manifest['独立金融検算']['正本SHA256']
    independent = json.loads(independent_body)
    assert independent.get('success',independent.get('成功')) is True
    assert independent['condition_count'] == 360 and independent['old_conditions_identical'] == 120
    assert independent['main'] == main and independent['aggregate_leaf_values_checked'] == 9453
    assert independent['all_sessions_minimum_one'] and independent['entries'] == 79 and independent['sessions'] == 73
    assert independent['phase_checks'] == {'選択stream検査':948,'entry検査':948,'endpoint検査':1752,'touch検査':7239}
    assert independent['table_checks']['all_data_cells_equal'] == 19809
    replay = json.loads((formal / '検査/保存観測からの再現確認.json').read_bytes())
    assert replay['成功'] and replay['原F1同体'] and replay['集計は原F1_SHA参照を含む全bytes同体']
    assert replay['全三表JSON_SHA256同体'] == 'dff78180df502ee24f642defded977b187a655d3045c130384479e79a88dda7b'
    csv_proof = json.loads((formal / '検査/CSV独立再読.json').read_bytes())
    assert csv_proof['成功'] and csv_proof['全データセル比較数'] == 19809 and csv_proof['数値比較数'] == 14145
    csv_hashes = {}
    for item in csv_proof['表別']:
        path = Path(item['CSV']['path']); assert sha(path.read_bytes()) == item['CSV']['sha256']
        with path.open(encoding='utf-8-sig',newline='') as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == item['行数']+1 and all(len(row) == item['列数'] for row in rows)
        csv_hashes[path.name] = item['CSV']['sha256']
    nonfinancial = (formal / '検査/非金融の独立確認.json').read_bytes()
    assert sha(nonfinancial) == '7931f796b17dde9ba2ca1b5934aeb6268d223c02125c5500fb5db605b88e566f'
    cause = (formal / '根拠/遅延変更5件の原因.json').read_bytes()
    assert sha(cause) == 'cdffc1868159916806c49dbc812eb15b51aa3fdd697c6b9fc42580ad92562eb6'
    changes = gzip.decompress((formal / '根拠/変更群の分解.json.gz').read_bytes())
    assert sha(changes) == '3c76e021b0289a76d9b8217c6eea55f836857cd98249f74e8dc933e700a9cc71'
    docs = list(formal.rglob('*.md')) + [root/'outputs/01a1889f-f2af-7943-a047-543275ee9ed2/135公表差CSV/README.md',
                                       root/'docs/議論/公表で不安定な方向を元へ戻した比較.md']
    links = 0
    for path in docs:
        for target in re.findall(r'\]\(([^)]+)\)',path.read_text('utf-8')):
            if target.startswith(('http://','https://','#')): continue
            assert (path.parent / target.split('#')[0]).resolve().exists(),(path,target)
            links += 1
    for name in ('README.md','docs/README.md','docs/議論/README.md','study/README.md'):
        assert formal.name in (root/name).read_text('utf-8')
    result = {'成功': True,'試行': 135,'確認UTC': datetime.now(timezone.utc).isoformat(),
              'F1原文同体': True,'金融前MD原文': 4,'F1全15源実復元': True,'504セル不変': True,
              'コードZIP': archive_records,'新共用gzip一度保存': 2,'共有旧資源恒久複製': False,
              '集計と三表の保存観測再現は全bytes同体': True,'独立条件': 360,'旧条件': 120,
              '独立集計末端値':9453,'独立CSV再読セル':19809,'CSV現在bytes':csv_hashes,'相対リンク確認数':links,
              '非金融と金融と事後群を区別':True,'134と異なる固定79出生':True,
              'Raw/巨大派生入力読取':False,'新仮説の金融実行':False,'新CSV生成':False,
              '重大不足':[],'確認コードSHA256':sha(Path(__file__).read_bytes())}
    target = args.output.resolve() if args.output else formal/'検査/保管復元の確認.json'
    assert target.is_relative_to(root) and not target.exists()
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as handle:
        handle.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'成功':True,'確認SHA256':sha(target.read_bytes()),'F1復元':15,'504セル不変':True,'リンク':links,'重大不足':[]},ensure_ascii=False))


if __name__ == '__main__':
    main()
