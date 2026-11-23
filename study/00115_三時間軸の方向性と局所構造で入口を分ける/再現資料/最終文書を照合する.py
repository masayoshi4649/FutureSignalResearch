"""115の最終12文書を、許可済み結果/診断metadataへ読取照合する。"""

from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
OWN = Path(__file__).resolve().parent
TRIAL = ROOT / 'study/00115_三時間軸の方向性と局所構造で入口を分ける'
READ = {}
CHECKS = []
NUMBERS = 0


def sha(path: Path) -> str:
    """機能: 許可文書又は小JSONのSHAを返す。

    引数: path(Path)は明示対象。
    返り値: strはSHA256。Native/CSV/原板を渡さない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(path: Path, prefix: str | None = None) -> str:
    """機能: 指定文書/小JSONを指紋付きで読む。

    引数: path(Path)、prefix(str|None)は明示対象と既知SHA先頭。
    返り値: strはUTF-8本文。
    """
    if path.suffix not in ('.md', '.json') or '.Native.' in path.name:
        raise ValueError('文書/小metadataだけ')
    digest = sha(path)
    if prefix is not None and not digest.startswith(prefix):
        raise ValueError('Root指定SHA差: ' + str(path))
    READ[str(path)] = digest
    return path.read_text(encoding='utf-8-sig')


def metadata(path: Path, prefix: str) -> dict:
    """機能: Root許可の小JSONを十進数で読む。

    引数: path(Path)、prefix(str)は明示対象と期待SHA。
    返り値: dictはmetadata。金融を再生しない。
    """
    return json.loads(text(path, prefix), parse_float=Decimal)


def check(name: str, passed: bool, detail: str) -> None:
    """機能: レビューの成立と証明範囲を記録する。

    引数: name/detail(str)、passed(bool)は項目・説明・判定。
    返り値: None。
    """
    CHECKS.append({'項目': name, '成立': bool(passed), '範囲': detail})


def number(cell: str) -> Decimal:
    """機能: 文書の円/率の表示を数値へ戻す。

    引数: cell(str)は表示セル。
    返り値: Decimalは桁区切り/全角符号/率記号を外した値。
    """
    return Decimal(cell.replace(',', '').replace('＋', '+').replace('−', '-').removesuffix('%'))


def tables(body: str) -> dict[str, list[list[str]]]:
    """機能: READMEの5比較表だけを分ける。

    引数: body(str)はREADME。
    返り値: dict[str,list[list[str]]]は数値表のセル列。
    """
    markers = {'| 口座 | 純額円': '全70', '| 口座 | 全玉正益経験': '保護', '| 口座 | 元54純額円': '期間',
               '| 口座 | 11/06Day純額円': '1106', '| モード | 選択真': '入口'}
    out, active = {key: [] for key in markers.values()}, None
    for line in body.splitlines():
        found = next((kind for start, kind in markers.items() if line.startswith(start)), None)
        if found:
            active = found
        elif not line.startswith('|'):
            active = None
        elif active and re.match(r'^\| (?:A0|T|TR)(?:_C[05]_D[01])? \|', line):
            out[active].append([cell.strip() for cell in line.split('|')[1:-1]])
    return out


def equal(cell: str, expected: int | Decimal, label: str, digits: int | None = None) -> None:
    """機能: 文書表示と正本値を厳密又は指定表示桁で照合する。

    引数: cell/label(str)、expected(int|Decimal)、digits(int|None)は表示・期待値・説明・表示桁。
    返り値: None。比較数を加算し不一致を検査票へ残す。
    """
    global NUMBERS
    target = Decimal(expected)
    if digits is not None:
        target = Decimal(f'{target:.{digits}f}')
    NUMBERS += 1
    if number(cell) != target:
        check(label, False, f'{cell} / 期待{target}')


def main() -> None:
    """機能: 最終文書を許可正本へ照合し新規レビューJSONを保存する。

    引数: なし。Root指定の文書/小metadataだけへ固定。
    返り値: None。金融再計算/既存物編集は行わない。
    """
    documents = [TRIAL / 'README.md', TRIAL / '設定と結果.md', ROOT / 'docs/議論/三時間軸の選別と正益後赤字を分けて読む.md',
                 *[ROOT / name for name in ('README.md', 'docs/README.md', 'docs/議論/README.md', 'study/README.md',
                                            'docs/議論/PDCAの進行.md', 'docs/議論/外部再調査/README.md')],
                 TRIAL / '診断/実現差のレビュー.md', TRIAL / '診断/11月06日の2玉と保有区間OHLC.md', TRIAL / '再現資料/実行と検査の補足.md']
    bodies = {str(path): text(path) for path in documents}
    readme, settings, common = (bodies[str(path)] for path in documents[:3])
    check('Root確定文書SHA', READ[str(documents[0])].startswith('e85279c') and READ[str(documents[1])].startswith('3e27641b')
          and READ[str(documents[2])].startswith('88e23d') and READ[str(documents[10])].startswith('5764aacf')
          and READ[str(documents[11])] == '5b51a3579c261e949c3b8a6beac917fee80d21e731d73ff95e3da21af60e0f74', 'README/設定/共通知見/OHLCと既レビュー済みCLI補足を同SHAで認証。')
    data = metadata(TRIAL / '成果物/結果.json', 'b4d9df3568098a73d38a670a9cca7a7dc0e6b4d79fe07a8ae8dd21d9cf6293df')
    diag = metadata(TRIAL / '診断/同入口と費用差の結果.json', 'c9ea16a9')
    independent = metadata(TRIAL / '診断/診断の独立照合.json', 'c01987d9')
    ohlc = metadata(TRIAL / '診断/11月06日の2玉と既存OHLCの対応.json', '1970dc3a')
    price = metadata(TRIAL / '検査/price_check.json', 'e2f7e62c')
    view = metadata(TRIAL / '検査/Viewer確認.json', 'ef5443d3')
    grouped = tables(readme)
    check('README全12/全0場の表', all(len(grouped[name]) == 12 for name in ('全70', '保護', '期間', '1106')) and len(grouped['入口']) == 3, '4表各12口座、入口表3モード。')
    for row in grouped['全70']:
        source = data['集計'][row[0]]
        for cell, field in zip(row[1:6], ('net_yen', 'positive_yen', 'negative_yen', 'positions', 'entry_quantity')):
            equal(cell, source[field], row[0] + field)
        equal(row[6], source['PF'], row[0] + 'PF', 3)
        equal(row[7], source['win_rate'] * 100, row[0] + '勝率', 2)
        equal(row[8], source['保存点連結時価DD'], row[0] + 'DD')
    for row in grouped['保護']:
        source = data['集計'][row[0]]
        for at, field in ((1, 'whole_positive_positions'), (2, 'whole_positive_closed_negative'), (4, 'whole_positive_closed_negative_yen'),
                          (5, 'protection_activated_positions'), (6, 'activated_closed_negative')):
            equal(row[at], source[field], row[0] + field)
        equal(row[3], Decimal(source['whole_positive_closed_negative']) / source['whole_positive_positions'] * 100, row[0] + '正益後赤字率', 2)
        equal(row[7], Decimal(source['activated_closed_negative']) / source['protection_activated_positions'] * 100, row[0] + '起動後赤字率', 2)
    for row in grouped['期間']:
        for offset, kind in ((1, 'original54'), (4, 'additional16')):
            selected = [r for r in data['場別'] if r['key'] == row[0] and r['history_class'] == kind]
            for at, field in enumerate(('net_yen', 'positions', 'entry_quantity'), offset):
                equal(row[at], sum(r[field] for r in selected), row[0] + kind + field)
    for row in grouped['1106']:
        for offset, kind in ((1, 'Day'), (4, 'Night')):
            source = next(r for r in data['場別'] if r['key'] == row[0] and r['session'] == '2026-11-06_' + kind)
            equal(row[offset], source['net_yen'], row[0] + kind + '純額')
            equal(row[offset + 1], source['positions'], row[0] + kind + '玉')
            for cell, field in zip(row[offset + 2].split('/'), ('whole_positive_positions', 'whole_positive_closed_negative')):
                equal(cell, source[field], row[0] + kind + field)
    for row in grouped['入口']:
        key = row[0] + '_C0_D0'
        source = Counter(data['入口票集計'][key])
        for at, field in enumerate(('selected_true', 'selected_false', 'selected_unknown', 'input_missing'), 1):
            equal(row[at], source[field], key + field)
        equal(row[5], Decimal(source['allowed']) / source['source_new'] * 100, key + '許可率', 2)
        equal(row[6], source['actual_new_fills'], key + '実玉')
        equal(row[7], source['actual_quantity'], key + '実枚')

    # ----------------------------------------
    technical = settings.split('## 設定明細', 1)[0]
    cells = [line for line in technical.splitlines() if re.match(r'^\| [A-Z][0-9]{2} \|', line)]
    ids = re.findall(r'^\| S([0-9]{2}) \|', settings, re.MULTILINE)
    results = re.findall(r'^\| R([0-9]{2}) \| ([A-Z0-9_]+) \| (.+)$', settings, re.MULTILINE)
    check('設定表版6/56×9/S23/R12', len(cells) == 56 and all(len(line.split('|')[1:-1]) == 11 for line in cells)
          and ids == [f'{i:02}' for i in range(1, 24)] and len(results) == 12, 'IDと手法2列＋9尺度、順序を維持。')
    for _, key, description in results:
        s = data['集計'][key]
        amount = ('＋' if s['net_yen'] >= 0 else '−') + f"{abs(s['net_yen']):,}"
        tokens = [f'純額{amount}円', f"PF {s['PF']:.3f}", f"勝率{s['win_rate'] * 100:.2f}%", f"新規{s['positions']}玉/{s['entry_quantity']:,}枚",
                  f"全玉正益後赤字{s['whole_positive_closed_negative']}玉", f"起動{s['protection_activated_positions']}玉", f"起動後赤字{s['activated_closed_negative']}玉"]
        check(key + '設定結果', all(token in description for token in tokens), '独立結果の7表示へ一致。')
    check('A0/S0と時刻/指標role', 'S0の原手法そのものではない' in readme and '5/15/30分は指標の足幅' in readme
          and 'MACD-H増分M' in technical and 'BB20±2幅縮小は診断のみ' in technical
          and 'P100の狭幅はBを使わない' in settings, 'A0は元Source入口＋P100。源内/準備/診断/新取得/保護を分離。')
    check('正益分母/起動/採否scope', all(term in readme for term in ('178/477=37.32%', '11/25=44.00%', '14/31=45.16%',
          '起動玉が10/13', '全70は過去研究で既使用', '11/09の価格・損益・入力指紋は未読', '採用はfalse')),
          '起動後0と未起動正益後赤字を別集計、小標本・未知期間未確認を保持。')
    five = independent['Tの実返済差5玉']
    point0 = independent['最大差の保存点再照合']['T_C0_D0']
    point5 = independent['最大差の保存点再照合']['T_C5_D0']
    hit = point5['保存保護点']['first_floor_hit']
    check('費用原因の保存事実', len(five) == 5 and sum(r['粗利益差円'] for r in five) == -357000
          and hit['snapshot']['normal_width'] == hit['snapshot']['width_points'] == 505
          and hit['snapshot']['minimum_floor'] == 20 and hit['snapshot']['narrowed'] is False
          and hit['decision']['floor_hit'] is True and hit['quote']['ask'] == 65360
          and point5['保存保護点']['first_narrowing'] is None and point0['純額'] == 314615 and point5['純額'] == 4615,
          'C5は通常幅のまま費用最低床hit。MA収束狭幅の単独原因とせず、実粗利益差−357000/追加滑り79000/純差−436000を説明。')
    check('診断の集計と範囲', diag['成功'] is True and diag['対照数'] == 22 and diag['場別対照数'] == 1540
          and independent['成功'] is True and '22対照・8,037対応' in bodies[str(documents[9])], '22対照の加算/保存点監査。全tickStateや床緩和の有効性へ拡大しない。')
    pieces = ohlc['2玉の抜粋']
    claims = [(7, 57500, -77539, 27461, 70000, '000022'), (1, 57330, -15077, 7923, 10000, '000038')]
    for row, (qty, entry, net, peak, threshold, suffix) in zip(pieces, claims):
        source = row['112CSV必要抜粋']
        check('1106の出生' + suffix, row['Source出生'].endswith(suffix) and int(source['初期枚数']) == qty
              and Decimal(source['取得価格']) == entry and Decimal(source['実現純利益円']) == net
              and Decimal(source['全玉最大W円']) == peak and row['W起動閾値円'] == threshold and row['全玉H100未到達'] is True,
              '既正式112OHLCの該当寿命へ同体鎖で接合。取得/返済の物理行・価格・量・純額を使いIDだけで結ばない。')
    check('11/06別7枚玉の非混同', '12:25:06' in bodies[str(documents[10])] and '15:08:27' in bodies[str(documents[10])]
          and '13:52取得57,420の別の売り7枚と混同しない' in bodies[str(documents[10])]
          and '115全玉のOHLCを再形成したという意味ではない' in readme, '今回2玉の保有中のみ。退出後仮利益・H変更成績は推定しない。')
    counts = {name: sum(row['比較'][name] for row in price['場別']) for name in ('公表', 'OHLC値', 'DMI現前値と計数')}
    check('DMI範囲/Viewer範囲', counts == {'公表': 12320, 'OHLC値': 49280, 'DMI現前値と計数': 123200}
          and view['成功'] is True and '全840GET・描画・目視確認ではない' in readme,
          'OHLC/DMIの別式範囲と、840一覧/24GETのHTTPを区別。再現補足5b51の前回CLIレビューを同SHAで継承。')

    # ----------------------------------------
    broken, link_count = [], 0
    for path in documents:
        for _, target in re.findall(r'\[([^\]]+)\]\(([^)]+)\)', bodies[str(path)]):
            if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target) or target.startswith('#'):
                continue
            local = unquote(target.split('#', 1)[0]).strip('<>')
            local = re.sub(r':\d+$', '', local)
            link_count += 1
            if not (path.parent / local).resolve().is_file():
                broken.append({'文書': str(path.relative_to(ROOT)), 'リンク': target})
    check('最終12文書のローカル参照', not broken, f'{link_count}件を存在確認。CSV/Nativeへのリンクも本文は開かず。外部HTTP/描画を呼ばない。')
    unchanged = all(sha(Path(path)) == digest for path, digest in READ.items())
    check('文書/許可metadata前後不変', unchanged, '既存固定物/正式文書/6目次は編集0。')
    issues = [item for item in CHECKS if not item['成立']]
    out = {'試行': 115, '成功': not issues, '範囲': '最終12文書の読取レビュー', '文書': {str(path.relative_to(ROOT)): READ[str(path)] for path in documents},
           '検査': CHECKS, '数値セル照合数': NUMBERS, 'ローカルリンク数': link_count, '不実在リンク': broken, '問題': issues,
           '前後不変': unchanged, '許可metadata': {path: digest for path, digest in READ.items() if path not in bodies},
           '未実施': {'Native/Raw/市場CSV/損益CSV本文': 0, '金融再実行': 0, '既存固定物/正式文書/6目次編集': 0, 'HTTP/描画': 0},
           '限界': ['OHLCは既存112の必要2寿命の同体参照で、115全玉Rawを再計算した確認ではない。', '費用原因は保存点と両側で成立した実績の比較。単独因果や幅変更後の収益性を証明しない。', '再現補足は前回CLI読取レビューと同SHA、今回実行しない。']}
    target = OWN / '最終12文書のレビュー.json'
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'成功': out['成功'], '問題数': len(issues), '数値セル': NUMBERS, 'リンク': link_count, 'path': str(target), 'sha256': sha(target)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
