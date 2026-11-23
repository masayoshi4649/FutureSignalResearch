package far80

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"sync/atomic"
)

// PrepareTechnicalSeeds は場を時系列に進め、各場直前の技法種を独立値で保存します。
//
// 引数: mはInputManifestの固定台帳です。
// 返り値: map[string]TechnicalBankは各場の開始前種、errorは入力指紋又は足時計の異常です。
// Sourceや実所有は進めず、場独立の並列再生へ同じ因果的な種だけを渡します。
func PrepareTechnicalSeeds(m InputManifest) (map[string]TechnicalBank, error) {
	seeds := map[string]TechnicalBank{}
	bank := NewTechnicalBank()
	contract := ""
	for _, input := range m.Sessions {
		if input.Contract != contract {
			bank = NewTechnicalBank()
			contract = input.Contract
		}
		seeds[input.ID] = *bank
		session, e := sessionClock(input.ID)
		if e != nil {
			return nil, e
		}
		p, e := verifyInput(m.Root, input.Files["NK225_book"])
		if e != nil {
			return nil, e
		}
		rows, _, e := readBoards(p, "NK225", session)
		if e != nil {
			return nil, e
		}
		grids, e := ScheduledTimes(input.ID)
		if e != nil {
			return nil, e
		}
		timers := append([]float64{}, grids...)
		timers = append(timers, session.ForceClose)
		if session.Kind == "Night" {
			timers = append(timers, session.USOpen-900, session.USOpen+900)
		}
		sort.Float64s(timers)
		bank.BeginSession(session.Start)
		next := 0
		for index, row := range rows {
			for next < len(timers) && timers[next] <= row.Board.Time {
				at := timers[next]
				next++
				if next > 1 && at == timers[next-2] {
					continue
				}
				if e = bank.Advance(at); e != nil {
					return nil, e
				}
			}
			q := Quote{Time: row.Board.Time, Index: int64(index), Line: row.Line, Last: row.Board.Last, Valid: row.Board.Last > 0}
			if e = bank.Observe(q); e != nil {
				return nil, e
			}
		}
		for next < len(timers) {
			at := timers[next]
			next++
			if next > 1 && at == timers[next-2] {
				continue
			}
			if e = bank.Advance(at); e != nil {
				return nil, e
			}
		}
	}
	return seeds, nil
}

type batchJob struct {
	Input InputSession
	Delay float64
	Label string
}

// RunBatch は種を共有せず、各場と遅延を独立workerで再生します。
//
// 引数: mはInputManifest、outはstringの新規根、workersはintの並列数、progressはio.Writerです。
// 返り値: errorは入力・再生・保存の異常です。最初の異常後の成果は正式採用しません。
func RunBatch(m InputManifest, out string, workers int, progress io.Writer) error {
	if workers < 1 || workers > 16 {
		return fmt.Errorf("並列数は1..16です")
	}
	if e := ValidateManifest(m); e != nil {
		return e
	}
	if _, e := os.Stat(out); !os.IsNotExist(e) {
		return fmt.Errorf("出力根は新規である必要があります:%s", out)
	}
	if e := os.MkdirAll(out, 0755); e != nil {
		return e
	}
	for _, label := range []string{"主66場", "追加1秒66場"} {
		if e := os.Mkdir(filepath.Join(out, label), 0755); e != nil {
			return e
		}
	}
	seeds, e := PrepareTechnicalSeeds(m)
	if e != nil {
		return e
	}
	jobs := make(chan batchJob, len(m.Sessions)*2)
	for _, input := range m.Sessions {
		jobs <- batchJob{input, 0, "主66場"}
		jobs <- batchJob{input, 1, "追加1秒66場"}
	}
	close(jobs)
	var wg sync.WaitGroup
	var failed atomic.Bool
	var firstError error
	var outputLock sync.Mutex
	completed := 0
	for worker := 0; worker < workers; worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for job := range jobs {
				if failed.Load() {
					continue
				}
				seed := seeds[job.Input.ID]
				result, err := Replay(m.Root, job.Input, &seed, job.Delay)
				if err == nil {
					var data []byte
					data, err = json.Marshal(result)
					if err == nil {
						err = os.WriteFile(filepath.Join(out, job.Label, job.Input.ID+".json"), data, 0644)
					}
				}
				outputLock.Lock()
				if err != nil {
					if firstError == nil {
						firstError = fmt.Errorf("%s %s: %w", job.Label, job.Input.ID, err)
					}
					failed.Store(true)
				} else {
					completed++
					fmt.Fprintf(progress, "%d/%d %s %s", completed, len(m.Sessions)*2, job.Label, job.Input.ID)
					for _, mode := range []string{"F0", "P1", "T1"} {
						b := result.Books[mode]
						fmt.Fprintf(progress, " %s=%.0f円 未解決%v", mode, b.Metrics.NetPnLYen, b.Unresolved)
					}
					fmt.Fprintln(progress)
				}
				outputLock.Unlock()
			}
		}()
	}
	wg.Wait()
	return firstError
}
