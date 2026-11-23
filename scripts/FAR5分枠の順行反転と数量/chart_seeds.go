package minichart

import (
	"fmt"
	"sort"

	warm "github.com/masayoshi4649/SessionTradeExecuter/chartwarmup96"
)

// ChartSeeds は場直前の非公開数値種と、その入力で閉じた場末公開値を分けます。
type ChartSeeds struct {
	Before map[string]*warm.Seed
	Ending map[string]warm.Snapshot
}

// PrepareChartSeeds は指定済みの場だけを因果順に進め、場外の足を作りません。
//
// 引数: root(string)とselected([]InputSession)は先に抽出した最大54場です。
// 返り値: ChartSeeds/errorは独立種と終値証拠、又は入力・時計・限月の異常です。
func PrepareChartSeeds(root string, selected []InputSession) (ChartSeeds, error) {
	out := ChartSeeds{Before: map[string]*warm.Seed{}, Ending: map[string]warm.Snapshot{}}
	if len(selected) == 0 || len(selected) > 54 {
		return out, fmt.Errorf("助走対象は指定済み1..54場だけ")
	}
	var previous *warm.Seed
	priorStart := 0.0
	for _, input := range selected {
		session, err := sessionClock(input.ID)
		if err != nil {
			return out, err
		}
		if session.Start <= priorStart {
			return out, fmt.Errorf("助走場の順序が不正")
		}
		priorStart = session.Start
		out.Before[input.ID] = previous
		bank, err := warm.New(warm.Scene{ID: input.ID, Contract: input.Contract, Start: session.Start}, previous)
		if err != nil {
			return out, err
		}
		boards := []replayBoard{}
		for _, ref := range []string{"TOPIX", "NK225"} {
			path, err := verifyInput(root, input.Files[ref+"_book"])
			if err != nil {
				return out, err
			}
			rows, quality, err := readBoards(path, ref, session)
			if err != nil {
				return out, err
			}
			if len(quality.Contracts) != 1 || ref == "NK225" && quality.Contracts[0] != input.Contract {
				return out, fmt.Errorf("助走限月不一致")
			}
			boards = append(boards, rows...)
		}
		sort.SliceStable(boards, func(i, j int) bool { return boards[i].Board.Time < boards[j].Board.Time })
		index := int64(0)
		for _, row := range boards {
			if row.Board.Reference == "NK225" {
				_, err = bank.Step(warm.Quote{Time: row.Board.Time, Index: index, Line: row.Line, Last: row.Board.Last, Bid: row.Board.Bid, Ask: row.Board.Ask, Valid: row.Board.Last > 0}, nil)
				index++
			} else {
				_, err = bank.AdvanceObserved(row.Board.Time, nil)
			}
			if err != nil {
				return out, fmt.Errorf("%s 助走: %w", input.ID, err)
			}
		}
		seed, end, err := bank.Seal()
		if err != nil {
			return out, err
		}
		previous = &seed
		out.Ending[input.ID] = end
	}
	return out, nil
}
