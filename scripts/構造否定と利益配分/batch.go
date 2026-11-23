package far83

// 83派生元: scripts/チャートの現在性と補助確認/batch.go
// 83派生元SHA256: ab931645419fe6a546a012dedeff68c039311c8923eff6a4d6da29b2a4f5d932

// 派生元: scripts/定時の現在根拠と部分利益保護/batch.go
// 派生元SHA256: 950719b961dd61071d5e7ca1dfc181a31bff90253a1791f8aee8c42e322726cb
// 元ファイルは固定のまま編集しません。

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"

	far80 "github.com/masayoshi4649/SessionTradeExecuter/research80"
)

// RunBatch は時間順の固定技法種を複写し、独立した各場を並列に再生します。
//
// 引数: manifest(InputManifest)は固定入力、out(string)は新規根、workers(int)は1..16、progress(io.Writer)は進捗先です。
// 返り値: errorは入力・再生・保存異常です。失敗した場のJSONを成功成果物として保存しません。
func RunBatch(manifest InputManifest, out string, workers int, progress io.Writer) error {
	if workers < 1 || workers > 16 {
		return fmt.Errorf("並列数は1..16です")
	}
	if e := far80.ValidateManifest(manifest); e != nil {
		return e
	}
	if _, e := os.Stat(out); !os.IsNotExist(e) {
		return fmt.Errorf("出力根は新規である必要があります:%s", out)
	}
	if progress == nil {
		progress = io.Discard
	}
	if e := os.MkdirAll(out, 0755); e != nil {
		return e
	}
	seeds, e := far80.PrepareTechnicalSeeds(manifest)
	if e != nil {
		return e
	}
	// ----------------------------------------
	// 一jobで8会計を作り、源特徴と足の計算を出口・遅延ごとに重複させません。
	jobs := make(chan InputSession, len(manifest.Sessions))
	for _, session := range manifest.Sessions {
		jobs <- session
	}
	close(jobs)
	var workersDone sync.WaitGroup
	var failed atomic.Bool
	var lock sync.Mutex
	var firstError error
	completed := 0
	for worker := 0; worker < workers; worker++ {
		workersDone.Add(1)
		go func() {
			defer workersDone.Done()
			for input := range jobs {
				if failed.Load() {
					continue
				}
				seed := seeds[input.ID]
				result, err := Replay(manifest.Root, input, &seed)
				if err == nil {
					var data []byte
					data, err = json.Marshal(result)
					if err == nil {
						err = os.WriteFile(filepath.Join(out, input.ID+".json"), data, 0644)
					}
				}
				lock.Lock()
				if err != nil {
					if firstError == nil {
						firstError = fmt.Errorf("%s: %w", input.ID, err)
					}
					failed.Store(true)
				} else {
					completed++
					fmt.Fprintf(progress, "%d/%d %s", completed, len(manifest.Sessions), input.ID)
					for _, mode := range Modes {
						for delay := 0; delay <= 1; delay++ {
							key := bookKey(mode, delay)
							b := result.Books[key]
							fmt.Fprintf(progress, " %s=%.0f円 未解決%v", key, b.Metrics.NetPnLYen, b.Unresolved)
						}
					}
					fmt.Fprintln(progress)
				}
				lock.Unlock()
			}
		}()
	}
	workersDone.Wait()
	return firstError
}
