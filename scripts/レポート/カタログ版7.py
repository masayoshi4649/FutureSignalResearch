"""版6を保持し、数量入力を明示するI16 VWMAだけを追加した版7を生成する。"""
from pathlib import Path
import argparse
import importlib.util
import json
import re
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE=HERE/'手法カタログ_版6.json'
CATALOG=HERE/'手法カタログ_版7.json'
MASTER=ROOT/'docs/議論/手法と時間スケールの汎用表_版7.md'
TEXTBOOK=ROOT/'docs/technical-analysis/指標/出来高加重移動平均線.md'
ADDITION={'id':'I16','name':'出来高加重移動平均線（VWMA）','category':'指標','source':'docs/technical-analysis/指標/出来高加重移動平均線.md',
    'additional_input':'価格系列（Close/HLC3等）と足量。固定時間窓/足本数・0/未知/欠分・数量品質・場/限月・公表を固定。有限窓VWMAと起点累積VWAPを区別'}
SPEC=importlib.util.spec_from_file_location('版7の継承する純描画',HERE/'設定結果レポート.py')
G=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=G;SPEC.loader.exec_module(G)


def load_catalog() -> dict:
    """
    機能: 版6の全56手法/9尺度を保ったI16追加だけを検査する。
    引数: なし。
    返り値: dictは57手法・9尺度・重複なしの版7。
    """
    base=json.loads(BASE.read_bytes());expected=json.loads(json.dumps(base,ensure_ascii=False));expected['version']=7
    where=next(i+1 for i,row in enumerate(expected['methods']) if row['id']=='I15');expected['methods'].insert(where,ADDITION)
    value=json.loads(CATALOG.read_bytes())
    assert value==expected and value['scales']==base['scales']
    assert [x for x in value['methods'] if x['id']!='I16']==base['methods']
    assert len(value['methods'])==57 and len(value['scales'])==9 and len({x['id'] for x in value['methods']})==57
    return value


# ----------------------------------------
def matrix(catalog: dict,output: Path,settings: list[dict]|None=None) -> str:
    """
    機能: 版7の全手法/尺度を既存純描画へ明示して渡す。
    引数: catalog(dict)、output(Path)、settings(list[dict]|None)は設定候補。
    返り値: strは57行9尺度のMarkdown。旧カタログglobalは変更しない。
    """
    assert catalog['version']==7 and len(catalog['methods'])==57
    return G.matrix(catalog,output,settings)


# ----------------------------------------
def render(catalog: dict) -> str:
    """
    機能: 全513セル未設定の汎用表と明細欄を組み立てる。
    引数: catalog(dict)は検査済み版7。
    返り値: strは表全文。20分や売買条件を採用済みにしない。
    """
    text='# 手法と時間スケールの汎用表・版7\n\n作成日：2026-11-12。57手法×9尺度＝513組。\n\n'
    text+='版6の56手法・9尺度・ID順を保持し、I16 出来高加重移動平均線（VWMA）だけを指標群末尾へ追加した。版1〜版6と固定試行のコピーは変更しない。\n\n'
    text+=G.link(ROOT/'docs/議論/手法と時間スケールの汎用表_版6.md',MASTER,'版6の表')+' / '+G.link(TEXTBOOK,MASTER,'VWMAの教材')+'\n\n'
    text+='I01の価格だけの平均と異なる数量入力の既知性を追跡するためI16を設けた。Close/HLC3や期間違いはI16内の設定差、起点累積VWAPはI12で区別する。教材収録は戦略・20分窓・閾値の採用や利益の証明ではない。\n\n'
    text+='新試行では使用版とSHAを記し、設定と結果.mdへコピーする。設定ID・短い閾値・複合評価ID、準備/選別/診断、未使用/未検証/データ不足/対象外を区別する。\n\n'
    text+='## 手法×時間スケール\n\n全セルは未設定・未検証。足幅・固定時間窓・観測本数・起算を分ける。1分系列の固定20分窓は1分列へ記録し、欠分を飛ばした20本へ置換しない。\n\n'+matrix(catalog,MASTER)
    text+='## 設定明細（コピー後に記入）\n\n'+G.table(['設定ID','手法ID・尺度','役割','計算期間・入力・初期化','買い/売りの閾値・等号','適用候補・複合評価','実行状態・出典'],[['S01','未設定','未設定','未設定','未設定','R01','未検証']])
    text+='## 複合条件と結果（コピー後に記入）\n\n'+G.table(['評価ID','構成設定と入口・出口','入力・対象期間','分母・件数・日数・場数','結果・費用・執行仮定','不明・未約定・限界'],[['R01','未設定','未設定','未設定','未検証','未検証']])
    text+='## 追加入力・定義の確認欄\n\n'+G.table(['手法ID','必要な入力・確認'],[[r['id'],r['additional_input']] for r in catalog['methods'] if r.get('additional_input')])
    text+='## 再現\n\n```powershell\npython -X utf8 scripts/レポート/カタログ版7.py\npython -X utf8 scripts/レポート/カタログ版7.py --check\n```\n\n生成先は版7表だけ。--checkは保存済み表と57×9=513セルの照合だけで、過去試行を生成しない。\n\n'
    text+=G.provenance([BASE,CATALOG,HERE/'設定結果レポート.py',Path(__file__),TEXTBOOK],MASTER)
    rows=[]
    for line in text.splitlines():
        if re.match(r'^\| [A-Z]+\d{2} \|',line):
            row=[x.strip() for x in line.strip('|').split('|')]
            if len(row)==11:rows.append(row)
    assert len(rows)==57 and sum(len(x[2:]) for x in rows)==513
    old_order=[]
    for line in (ROOT/'docs/議論/手法と時間スケールの汎用表_版6.md').read_text('utf-8').splitlines():
        if re.match(r'^\| [A-Z]+\d{2} \|',line):
            row=[x.strip() for x in line.strip('|').split('|')]
            if len(row)==11:old_order.append(row[0])
    assert [x[0] for x in rows if x[0]!='I16']==old_order and len(old_order)==56
    assert all(cell=='未設定・未検証' for x in rows for cell in x[2:])
    return text


# ----------------------------------------
def main() -> None:
    """
    機能: 版7だけを新規生成するか保存済み表を確認する。
    引数: CLI --check(bool)。
    返り値: None。不一致は例外、旧版/固定試行/自然データは変更しない。
    """
    p=argparse.ArgumentParser(description='版7の57手法9尺度を生成/照合');p.add_argument('--check',action='store_true');args=p.parse_args()
    result=render(load_catalog())
    if args.check:assert MASTER.read_text('utf-8')==result
    else:MASTER.write_text(result,encoding='utf-8')
    print('版7：57手法×9尺度=513セル、旧56手法/尺度/順序不変を確認しました')


if __name__=='__main__':main()
