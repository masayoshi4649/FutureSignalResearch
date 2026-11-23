"""H0と床の意味を分ける設計用一段算術。金融候補や停止純Goの実装ではない。"""
from decimal import Decimal,ROUND_CEILING


def number(value) -> Decimal:
    """
    機能: 手製の有限値を十進数として扱う。
    引数: value(数値)。返り値: Decimal。bool/非有限を拒否する。
    """
    if isinstance(value,bool):raise ValueError('boolは実数でない')
    v=Decimal(str(value))
    if not v.is_finite():raise ValueError('有限手製値だけ')
    return v


def ceil5(value) -> Decimal:
    """
    機能: miniの5pt格子へ数学的ceilを適用する。
    引数: value(数値)。返り値: Decimal。負数もゼロ方向へ単純丸めしない。
    """
    return (number(value)/5).to_integral_value(rounding=ROUND_CEILING)*5


def step(side: int,cost: int,gain,n: int=2,reserved: int=0,realized=0,mode: str='余白5pt',phase: str='after_source',active: bool=False,previous_floor=None,peak=None,whole_target=0,mark_known: bool=True) -> dict:
    """
    機能: 仮の厳密H0起動と三種の床を一段評価し、追尾起動/床hit/返済適格量を分ける。
    引数: side/cost/n/reserved(int)、gain/realized/previous_floor/peak/whole_target(数値|None)、mode/phase(str)、active/mark_known(bool)。
    返り値: dictは設計算術。ATR/構造床を未知とし、通常幅200で最低床の寄与だけを分離する。
    """
    if side not in (1,-1) or cost not in (0,5) or not(0<=reserved<=n) or n<0 or phase not in ('pre_fill','after_source'):raise ValueError('手製入力不正')
    if mode not in ('価格同値','費用後ゼロ','余白5pt'):raise ValueError('床の意味が未定義')
    k=Decimal(77+200*cost);r=number(realized);g=number(gain) if mark_known else None;w=None if g is None else r+n*(100*g-k);new=bool(not active and n>0 and w is not None and w>0);now=active or new
    result={'side':side,'C':cost,'n':n,'reserved':reserved,'R':r,'mode':mode,'phase':phase,'cost_yen':k,'cost_points':k/100,'gain':g,'mark':None if g is None else 1000+side*g,'W':w,'strict_H0_activated_now':new,'active':now,'floor':previous_floor,'protect_price':None,'floor_hit':False,'exit_eligible_quantity':0,'WholeFloor':None,'PeakFloor':None}
    if g is None or not now or n==0:return result
    minimum=Decimal(0) if mode=='価格同値' else ceil5(k/100+(5 if mode=='余白5pt' else 0));f=minimum
    if previous_floor is not None:f=max(f,number(previous_floor))
    current_peak=max(g,number(peak)) if peak is not None else g;pf=ceil5(current_peak-200);f=max(f,pf);result['PeakFloor']=pf
    # ----------------------------------------
    # 「価格同値」は全玉L>=0を要求しない対照。既存L=0を残すと費用後ゼロ床になる。
    if mode!='価格同値':
        fw=ceil5((n*k+number(whole_target)-r)/(100*n));result['WholeFloor']=fw;f=max(f,fw)
    result.update(minimum=minimum,floor=f,protect_price=1000+side*f,floor_hit=g<=f)
    if result['floor_hit'] and phase=='after_source':result['exit_eligible_quantity']=n-reserved
    return result


def first_positive_gain(cost: int,tick: int) -> Decimal:
    """
    機能: R=0の新品玉が正益になる最初の手製価格格子を返す。
    引数: cost/tick(int)。返り値: Decimal。mini5/large10は観測格子の手製仮定。
    """
    k=Decimal(77+200*cost)/100;step=number(tick)
    if tick not in (5,10):raise ValueError('今回の手製格子だけ')
    return (k//step+1)*step


class PriceStage:
    """価格床Eで始め、実現R/nと非緩和Targetを守って利益進行時だけ新目標を採用する提案式。"""

    def __init__(self,side: int,cost: int,q0: int=2):
        """
        機能: 手製の方向/費用/初期枚数と未起動状態だけを作る。
        引数: side/cost/q0(int)。返り値: None。金融純APIやActorへ接続しない。
        """
        if side not in (1,-1) or cost not in (0,5) or not(1<=q0<=10):raise ValueError('手製初期条件')
        self.side,self.cost,self.q0=side,cost,q0;self.k=Decimal(77+200*cost);self.active=False;self.floor=None;self.target=None;self.peak=None

    def advance(self,gain,n: int=2,reserved: int=0,realized=0,phase: str='after_source',mark_known: bool=True) -> dict:
        """
        機能: W>0で価格床E/Target=R−nKを作り、新峰と実行余地がある時だけ費用目標を昇格する。
        引数: gain/realized(数値)、n/reserved(int)、phase(str)、mark_known(bool)。
        返り値: dictは提案の床/全玉Target/返済適格量。過去床が破られたら緩めず現在価格で要求する。
        """
        if not(0<=reserved<=n<=self.q0) or phase not in ('pre_fill','after_source'):raise ValueError('手製実残/位相')
        r=number(realized);g=number(gain) if mark_known else None;w=None if g is None else r+n*(100*g-self.k);previous_target=self.target;previous_floor=self.floor;new=False;new_peak=False;promoted=[];deferred=[]
        result={'side':self.side,'C':self.cost,'q0':self.q0,'n':n,'reserved':reserved,'R':r,'gain':g,'W':w,'phase':phase,'activated_now':False,'active':self.active,'floor':self.floor,'target_yen':self.target,'previous_floor':previous_floor,'previous_target_yen':previous_target,'promoted':promoted,'deferred':deferred,'floor_hit':False,'exit_eligible_quantity':0}
        if n==0 or g is None:return result
        if not self.active and w>0:
            self.active=True;new=True;self.floor=Decimal(0);self.target=r-n*self.k;self.peak=g
        if not self.active:return result
        if g>self.peak:self.peak=g;new_peak=True
        # ----------------------------------------
        # 既存約束は現在価格に合わせて緩めない。FWは初回Targetなら厳密0となる。
        target_before_floor=self.target;fw=ceil5((n*self.k+self.target-r)/(100*n));peak_floor=ceil5(self.peak-200);floor=max(Decimal(0),self.floor,fw,peak_floor)
        if not new and new_peak:
            goal=max(self.target,Decimal(0));fee_floor=max(floor,ceil5((n*self.k+goal-r)/(100*n)))
            if fee_floor<=g-5:self.target=goal;floor=fee_floor;promoted.append('全玉費用後ゼロ以上')
            else:deferred.append('新しい全玉ゼロ床が現markの1呼値後ろへ置けない')
            margin_floor=max(floor,ceil5(self.k/100+5))
            if self.target>=0 and margin_floor<=g-5:floor=margin_floor;promoted.append('残1枚の費用後5pt以上余白')
            else:deferred.append('新しい余白床が未実行又は全玉ゼロ未達')
        self.floor=floor;self.target=max(self.target,r+n*(100*floor-self.k))
        if previous_floor is not None and self.floor<previous_floor:raise AssertionError('床非緩和')
        if previous_target is not None and self.target<previous_target:raise AssertionError('全玉Target非緩和')
        hit=g<=floor;qty=n-reserved if hit and phase=='after_source' else 0
        result.update(activated_now=new,active=True,floor=floor,target_yen=self.target,initial_target_formula='R−nK' if new else None,target_before_floor_yen=target_before_floor,WholeFloor=fw,WholeFloor_basis='今回の床採用前Target',WholeFloor_final=ceil5((n*self.k+self.target-r)/(100*n)),PeakFloor=peak_floor,peak=self.peak,protect_price=1000+self.side*floor,floor_hit=hit,exit_eligible_quantity=qty)
        return result
