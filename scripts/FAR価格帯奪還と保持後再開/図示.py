"""92の全66場をゼロ起点・赤字表示・検査scope脚注付きで描く。"""

import argparse
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

KEYS=tuple(f'H{p}G1_D{d}' for d in (0,1) for p in (0,1))


def render(value: dict, output: Path, source_sha: str, preview: Path | None = None) -> None:
    """
    機能: 四会計の全66場累積費用後純額を同尺度とゼロ線で描く。
    引数: value(dict)、output(Path)、source_sha(str)、preview(Path|None)は正本・新規SVG・結果指紋・任意PNG。
    返り値: None。入力正本を再計算/変更せず、SVGへ出典を記録する。
    """
    if output.exists() or preview is not None and preview.exists():raise FileExistsError('図の既存出力は上書きしない')
    if value['試行']!=92 or value['場数']!=66 or len(value['場別'])!=264 or set(value['比較'])!=set(KEYS):raise ValueError('92の全66場/264会計が必要')
    names={f.name for f in font_manager.fontManager.ttflist};font=next((n for n in ('Meiryo','Yu Gothic','Noto Sans CJK JP') if n in names),None)
    if font is None:raise ValueError('日本語フォントが必要')
    plt.rcParams.update({'font.family':font,'axes.unicode_minus':False,'font.size':10});fig,axes=plt.subplots(1,2,figsize=(12,5),sharey=True)
    sessions=None
    for delay,ax in enumerate(axes):
        for mode,color in (('H0G1','#146eab'),('H1G1','#a63d70')):
            key=f'{mode}_D{delay}';rows=[r for r in value['場別'] if r['key']==key];order=[r['session'] for r in rows]
            if len(rows)!=66 or len(set(order))!=66:raise ValueError('各会計に一意66場が必要')
            if sessions is None:sessions=order
            elif sessions!=order:raise ValueError('会計間の場順序差')
            series=[0]+[r['累積損益円'] for r in rows]
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in series):raise ValueError('図の有限純額が必要')
            if series[-1]!=value['比較'][key]['費用後損益円']:raise ValueError('末尾と比較純額差')
            ax.plot(range(67),series,color=color,label=f"{mode}（{value['比較'][key]['完結玉']}玉）",linewidth=1.6)
        ticks=[0,13,26,39,52,66];ax.set_xticks(ticks,['開始']+[sessions[i-1][5:].replace('_Day','昼').replace('_Night','夜') for i in ticks[1:]],rotation=30,ha='right')
        ax.axhline(0,color='#555555',linewidth=0.9);ax.set_xlim(0,66);ax.grid(axis='y',alpha=.2);ax.legend(frameon=False);ax.set_title('次正常原行' if delay==0 else '追加価格時計1秒');ax.set_xlabel('完了セッション');ax.ticklabel_format(axis='y',style='plain',useOffset=False)
    artificial=str(value.get('状態','')).startswith('人工')
    axes[0].set_ylabel('累積費用後損益（円）');fig.suptitle(('人工表示試験：' if artificial else '')+'旧E1と現在E0＋独立価格再開：共通G1')
    losses=sum(value['比較'][k]['費用後損益円']<0 for k in KEYS);warning='全4会計が赤字。安定利益は未確認。' if losses==4 else '赤字の会計あり。安定利益は未確認。' if losses else '既使用66場。安定性は別検証。'
    fig.text(.5,.10,warning,ha='center',color='#b22222' if losses else '#444444',weight='bold')
    fig.text(.5,.035,'全66場・ゼロ場も含む。人工の部分scopeと全場検査は別。指標前史・Source生成は固定数値器/seed/元driver依存。',ha='center',fontsize=8)
    fig.subplots_adjust(bottom=.27,top=.85,wspace=.08)
    metadata={'入力結果SHA256':source_sha,'図示コードSHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'場数':66,'会計数':264,'ゼロ起点':True,'部分scope脚注':True,'人工表示':artificial}
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output,format='svg',metadata={'Description':json.dumps(metadata,ensure_ascii=False,sort_keys=True)})
    if preview is not None:preview.parent.mkdir(parents=True,exist_ok=True);fig.savefig(preview,format='png',dpi=125)
    plt.close(fig)


def main() -> None:
    """
    機能: 明示結果JSONから新規SVGと任意work PNGを生成する。
    引数: --result/--out(Path)、--preview(Path|None)はCLI入力と先。
    返り値: None。原板・市場・Viewerへ接続しない。
    """
    parser=argparse.ArgumentParser(description='92の全66場累積純額図')
    for n in ('result','out'):parser.add_argument('--'+n,type=Path,required=True)
    parser.add_argument('--preview',type=Path);a=parser.parse_args();before=hashlib.sha256(a.result.read_bytes()).hexdigest();render(json.loads(a.result.read_text(encoding='utf-8')),a.out,before,a.preview)
    if hashlib.sha256(a.result.read_bytes()).hexdigest()!=before:raise ValueError('図示中の結果変更')
    print('比較図を保存: '+str(a.out))


if __name__=='__main__':main()
