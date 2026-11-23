本稿は103実行前に作った静的な再利用接続案。その後、既存Tapeの元通知を保つ多玉・数量・起動比較を[103として実行・保存](利益追尾の起動時機と元の建玉構造を分ける.md)した。以下の103未確定表記は調査当時の状態。新条件のSource再実行・参照台帳の市場復元は引き続き未実行で、本稿をその証明へ代用しない。

# 元参照と定時判断の接続調査

2026-11-09。静的コードと既存の小metadataだけを確認した。Raw・CSV・Tape・Native本文・全54場・金融は今回読取/実行0。103の採用・実装・利益は未確定。確認した事実と候補を以下で分ける。

## まず保持する構造

102の参加55〜67%・全金融赤字はRootの完了報告による。本調査では再計算しない。**102は単一建玉・2/4/6枚・追加入れなし・両建てなし。一方、元S0はD/P/Uの複数玉・元の可変数量・両側上限10を持つ。** 入口を全5分の票判定へ置き換えた際、数量と保有構造も変わっている。赤字の原因を支持票だけへ帰属できない。

連続S0は固定参考対照に留める。新候補は5分/15分判断と開始30分見送りを維持する。最小の基礎比較は、旧95B5Q等の**元Source多玉・数量・返済を保つ定時会計**へ、即時起動と一定益起動の差だけを追加する形が適する。現在生存poolへの拡張、現在技法の追加、D07重複裁定の修正は別の変更として扱う。

## 元入口の優位性「候補」

以下は静的に確認できた状態機械であり、各部が黒字を生んだという寄与証明ではない。[selected_source.go](../../../SessionTradeExecuter/internal/strategy/selected_source.go):14–43でD→S01、P→P05、U→D07を構築し、各階層の状態を継続する。

| 元手法 | 残す価値のある構造候補 | 単純な票入口との違い・根拠 |
| --- | --- | --- |
| D164_15 | S01と内側D07の親/占有・準備を継承。初回支持量、短秒失速待機/再加速、追撃確認、部分返済後の残玉資格 | 希望量は支持不明でも基準量を持つ `floor(10+90×M×T)` の100基準。初回量を固定して整数配分する。5/15秒は初回待機と追撃で役割が異なる。[selected_day164_policy.go](../../../SessionTradeExecuter/internal/strategy/selected_day164_policy.go):95–102、[selected_methods.go](../../../SessionTradeExecuter/internal/rules/selected_methods.go):9–14 |
| P164_06 | P05/D07の基底と親・小量初回/残玉資格・元数量を継承 | 小量資格は元親の初回量に基づく。現在残量が少ないことへ付け替えない。元部分返済の実益を条件とする残玉資格もあり、初回/追撃が同じ処理ではない。[selected_night_policy.go](../../../SessionTradeExecuter/internal/strategy/selected_night_policy.go):210–272、[selected_methods.go](../../../SessionTradeExecuter/internal/rules/selected_methods.go):24–27 |
| U165_03 | D07の準備構造と、反対帯＋表示数量支持がある初回だけの待機、新しい自方向帯による解除 | 元は全原行で30秒待機を進める。未知時に追加待機しない元フォールバックもある。定時まで資格を無条件延命すると別方式になる。[selected_night_policy.go](../../../SessionTradeExecuter/internal/strategy/selected_night_policy.go):128–185、[selected_methods.go](../../../SessionTradeExecuter/internal/rules/selected_methods.go):37–39 |

S01/P05/D07には、境界・突破/往復の段階、親・既予約・実所有による抑止がある。これらを外して「現在の方向点数」だけを作れば、元の候補母集団ではなくなる。元の表示量支持は校正確率や実際の約定出来高とは呼ばない。

## 現在生存する元参照玉を復元できるか

| 入力 | 可能な範囲 | 不足/制約 |
| --- | --- | --- |
| 101共有Header/records | 当時のチャート・Current・Scalarと時計 | `RawContext`にはSource台帳がない。これだけから参照玉を創作できない。[sidecar.go](../../scripts/保護判断の連続技法入力/sidecar.go):63–69 |
| 小101NativeのP0一口座にある `source_events` | 全配送から元注文・実取得・返済予約・現在残量をActorの採否とは別に復元する型を持つ | source_events単独ではParent・Kind・内側SourceIDが不足。全出生を保存する `entry_opportunities[].source` へmethod+signal_idで結合する必要がある |
| 元Tapeの `quote/force` の実NativeBatch | Signal/Fill/取消/CloseNoticeの所有内訳を直接再配送できる | 既存Sourceを固定する場合だけ。D07を変更した新Sourceの通知を旧Tapeから合成できない |
| 全原行Sourceを直接運転するReference/Adapter | `Frame/ReadMetadata` 又はSnapshotから現在所有を読む | 旧87Referenceはmicro尺度、93mini Adapterはmini尺度。数量をそのまま混ぜない。元の私有親全状態を公開getterで自由に再初期化できるわけではない |

`EntryOpportunityTrace`は全Source出生で作られるため、実側で拒否した出生もidentityを持つ。[entry_grid.go](../../scripts/FAR利益化前後の保護/entry_grid.go):68–84。`SourceIdentity`にはMethod/SignalID/Kind/Parent/SourceID/BirthQuantity/BirthTime/BirthQuoteがある。[actual_types.go](../../scripts/FAR利益化前後の保護/actual_types.go):107–116。旧 `consumed/expired` は「出生後一枠」の実受付履歴であり、新しい生存poolの可否へ流用しない。

復元の最小台帳は `(method,signal_id)` の元注文と `(method,hold_id)` の元所有を分ける。

1. `new_signal`で出生identityを結び、`new_fill`で初めて元所有Qを作る。未取得や取消は保有ではない。
2. `close_notice`を `(method,close signal_id,hold_id,notice_id)` へ結び、予約Rを増やす。`before`は既予約控除後の未通知量で、総保有Qとは別。[adapter.go](../../scripts/FAR元三手法のmini連続再現/adapter.go):280–305。
3. `close_fill`で、先行する同method/close signal_idのnotice各HoldID内訳を使いQ/Rを減らす。**close_fill trace自体にはtargets配列がない**ので、数量だけでFIFO配分しない。元は全量fillであることも照合する。[actual.go](../../scripts/FAR利益化前後の保護/actual.go):389–429、[actual_types.go](../../scripts/FAR利益化前後の保護/actual_types.go):251–272。
4. 定時ごとにQ・R・自由量Q−R・元初期量・出生量・元役割を別記する。元Sourceの取得価格・確定益・利益起動を実口座へ移植しない。識別子の文字列分割でParentや役割を推測しない。

同秒はAtだけで切らない。旧runtimeのSourceForce→grid→rawを保ち、gridの最後のQuote.Index/SourceLineへ当時のイベントprefixを結ぶ。同Atでもgrid後rawの大きいIndexは含めず、先行Forceの予約/取消は含む。将来の最終残量や実Actual positionから過去を逆算しない。SourceのIndexとChart.LastInput.Indexも同一視しない。

これは**型とコード上の再構成可能性**までである。今回Native一場の実抽出や全件整合は未実施。実装時は空場・部分返済・全予約・同秒Force・未取得取消を人工で先に確認する。

## D07重複裁定と、Source再実行の最小接続

固定43は無条件に対称ではない。`addon.entry.range_side`は安値側判定を先に返すため、両条件真なら買い優先。`W<=0.2R`では領域が重なり得る。[addon_specs.go](../../../SessionTradeExecuter/internal/rules/addon_specs.go):31、[active143.go](../../../SessionTradeExecuter/internal/strategy/active143.go):241–258、[features143.go](../../../SessionTradeExecuter/internal/strategy/features143.go):234。自然発動数・経済影響は未確認。

候補は**両方真なら待機、それ以外は唯一成立側**という重複裁定だけの対称化。新しい勢い・量で方向を決める案は別変更となる。任意の価格反射でbp等の全特徴まで完全鏡像になる証明とは分ける。

静的には43本文を変えず `Config.RuleExpressions` のこの式だけを新条件として上書きできる接続がある。`bindRules`が実式をActive145へ渡し、D07Rules経路では式結果が先行する手書きcandidateを上書きする。[rules.go](../../../SessionTradeExecuter/internal/strategy/rules.go):8–24、46–49。D/P/U内側への継承は[selected_source.go](../../../SessionTradeExecuter/internal/strategy/selected_source.go):36–43、[s01.go](../../../SessionTradeExecuter/internal/strategy/s01.go):45–67、[p05.go](../../../SessionTradeExecuter/internal/strategy/p05.go):41–50。**本文同体でも実式を変えれば別Source条件**であり、旧Source成功へ代用しない。

ただし1キーだけの部分mapは渡せない。profileの既定**全式**を複写してこの1式だけを変更し、全件mapを渡す必要がある。`CompileFor`は必須件数と各IDを検査する。[engine.go](../../../SessionTradeExecuter/internal/rules/engine.go):128–139、211–217。

既存93 `NewAdapter` は外部RuleExpressionsを受けずbookがprivateなので、そのまま後から注入する公開口はない。[adapter.go](../../scripts/FAR元三手法のmini連続再現/adapter.go):76–104。新しい小adapter派生で生成時の明示overrideを受け、Step/Force/Fill/所有規範は旧93と同体にするのが接続候補。実式全体とoverride SHA、旧43 SHAを別記する。空overrideの全台帳同値を先に確認する。

新Sourceは完全な当時Observationを要する。共有Scalar/Currentには元Research/Selectedの全状態入力がないため、それを穴埋めしてSourceを再運転しない。最小の将来実行口は、既存の[93 Replay](../../scripts/FAR元三手法のmini連続再現/replay.go):20–150又は新しいproducer派生の `Features.OnBoard` 直後の正NK Observationから、元adapterを全原行で進める口である。前者は原板/分足の再読が必要、後者も完全Observationを生成する段階の一巡が必要。今回はどちらも未実行。Signal/Fillを後処理で削除して新NativeBatchを偽造する方式は採らない。

## 保護は旧多建玉会計への小さな追加を優先する

`minishortfinance.ActualBook`はPosition/SourceHold別の多玉とP/U合算の片側10枚を既に持つ。返済予約を空きへ戻さず、注文と保有で余力を計算する。[actual.go](../../scripts/短秒の複合退出の会計/actual.go):251–267。空S政策なら既存OnNativeStepを使え、Source受付・予約・fill・費用を再実装する必要はない。

最小leaf候補は `markPositions` の起動判定（同:865）と幅選択（同:889–900）だけを明示policyへ分離する新派生。一定益の数値・単位・等号・未知ATRはまだ固定しない。次を維持する。

- `FirstUnitPositive`は費用後単価益u>0の観測として残し、遅い保護起動と別旗にする。WholeHoldの実現額込みWとも分ける。
- 起動・ピーク・床は実Actual建値から計算し、起動後は最低名目建値・非緩和床・連続監視を守る。Sourceの過去益や旧ピークを足さない。
- pre_fill評価→既予約fill→Source返済予約/新規→after_source評価の旧順を維持し、新しい返済はSource後の未予約量だけ。同原行fill禁止/D1/費用/容量を保持する。同:1011–1057。
- 基礎比較では旧B5Qの新規時計・出生一回・数量・Source返済をまず固定する。空新policyの旧B5Q全JSON対照を先行する。生存poolへ改める場合は入口規約の別差として比較する。

## 次に固定すべき候補と未確定事項

優先候補は「旧Source多玉/可変量を維持するB5Q基礎」対「同じ入口・数量の一定益起動追尾」。現在生存pool×現在技法はその後の独立した候補とする。5分/15分のどちらか、US見送り、参照選択の順位、Source予約中の扱い、同一HoldIDの再取得/seen、一定益と幅は実行前に明記する。多数の複合票だけで全枠へ新規を乱発する方式へ戻さない。

参加>=25%は未確認。Source生存枠、技法可用枠、実NEW、実HOLD、WAIT、UNKNOWNを同じ事前分母で分け、欠測も分母に残す。高参加を得るために条件を結果後に緩めない。実現損益・利益後赤字・DD・回数枚数・費用・日別集中を評価し、機会損失・退出後価格・仮想約定は対象外。既使用54場での改善を未知期間の安定利益とはしない。
