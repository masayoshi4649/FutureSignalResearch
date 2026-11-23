// 由来: scripts/FAR背景と勢いと数量の再生/batch.go
// 由来SHA256: fa60fcf37d09e89fdb5bb3279354cf58d841ae648ae0ceb57199216c829bd28c
// 由来: scripts/FAR初回利益確定の再生/batch.go の集合/入力/code指紋/並列配送管理。
package grossport100

import (
	"encoding/json"
	"fmt"
	port "github.com/masayoshi4649/SessionTradeExecuter/actorport97"
	prior99 "github.com/masayoshi4649/SessionTradeExecuter/entryport99"
	tape "github.com/masayoshi4649/SessionTradeExecuter/lighttape97"
	prior98 "github.com/masayoshi4649/SessionTradeExecuter/riskport98"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"sync"
)

type TapeEntry = port.TapeEntry
type TapeIndex = port.TapeIndex

// BatchArguments は四段の固定保存入力と未固定100条件を明示します。
type BatchArguments struct {
	Index, Condition, Proof99, Proof98, Proof97, Proof96, Out, Stage string
	Workers                                                          int
}

// fileHashes は明示したコード/入力の現在指紋を保存します。
//
// 引数: paths([]string)はRawを含めない許可済みファイルです。
// 返り値: map[string]string/errorは絶対パスとSHA256又はIO不整合です。
func fileHashes(paths []string) (map[string]string, error) {
	out := map[string]string{}
	for _, path := range paths {
		absolute, err := filepath.Abs(path)
		if err != nil {
			return nil, err
		}
		sha, err := tape.Digest(absolute)
		if err != nil {
			return nil, err
		}
		out[absolute] = sha
	}
	return out, nil
}

// RunBatch は固定条件と構築済みTapeから12口座を並列運転します。
//
// 引数: args(BatchArguments)は明示index/条件/96証拠/新規出力/stage/worker数です。
// 返り値: errorは前後指紋/旧4口座全文/新金融の不整合です。Source/Features/助走/Rawは再生しません。
func RunBatch(args BatchArguments) error {
	if args.Index == "" || args.Condition == "" || args.Proof96 == "" || args.Proof97 == "" || args.Proof98 == "" || args.Proof99 == "" || args.Out == "" || args.Workers < 1 || args.Workers > 8 {
		return fmt.Errorf("必須引数又はworker数が不正")
	}
	// 未固定条件はTape/index/旧Nativeを開く前に拒否する。
	conditionBody, err := os.ReadFile(args.Condition)
	if err != nil {
		return err
	}
	var condition struct {
		Trial         int               `json:"試行"`
		Proof99       string            `json:"固定99完了SHA256"`
		Proof98       string            `json:"固定98完了SHA256"`
		Proof97       string            `json:"固定97完了SHA256"`
		Proof96       string            `json:"固定96完了SHA256"`
		FinancialStop string            `json:"金融停止SHA256"`
		Manifest      string            `json:"台帳SHA256"`
		Index2        string            `json:"接続2場Tape台帳SHA256"`
		Index54       string            `json:"正式54Tape台帳SHA256"`
		Keys          []string          `json:"全12Key"`
		Fixed         bool              `json:"市場損益を開く前の固定"`
		Code          map[string]string `json:"コードSHA256"`
	}
	if err = json.Unmarshal(conditionBody, &condition); err != nil {
		return err
	}
	if condition.Trial != 100 || !condition.Fixed || condition.Proof99 != Fixed99CompletionSHA256 || condition.Proof98 != prior99.Fixed98CompletionSHA256 || condition.Proof97 != prior98.Fixed97CompletionSHA256 || condition.Proof96 != tape.SelectedCompletionSHA256 || len(condition.Code) == 0 || !reflect.DeepEqual(condition.Keys, Keys()) {
		return fmt.Errorf("固定100条件又はコード集合が不明")
	}
	if !validSHA(Fixed100FinancialStopSHA256) || condition.FinancialStop != Fixed100FinancialStopSHA256 {
		return fmt.Errorf("100金融停止SHAが未結合又は不一致")
	}
	indexExpected := condition.Index2
	if args.Stage == "full54" {
		indexExpected = condition.Index54
	} else if args.Stage != "first2" {
		return fmt.Errorf("100のstageが不正")
	}
	if !validSHA(indexExpected) {
		return fmt.Errorf("固定100台帳SHAが不明")
	}
	if got, e := tape.Digest(args.Index); e != nil || got != indexExpected {
		return fmt.Errorf("固定100のstage台帳SHA差")
	}
	allowed, err := Selected99Catalog(args.Proof99)
	if err != nil {
		return err
	}
	allowed98, err := prior99.Selected98Catalog(args.Proof98)
	if err != nil {
		return err
	}
	if len(allowed98) != len(allowed) {
		return fmt.Errorf("固定99/98場集合差")
	}
	for session := range allowed {
		if _, ok := allowed98[session]; !ok {
			return fmt.Errorf("固定99/98場集合差")
		}
	}
	allowed97, err := prior98.Selected97Catalog(args.Proof97)
	if err != nil {
		return err
	}
	if len(allowed97) != len(allowed) {
		return fmt.Errorf("固定99/97の場集合差")
	}
	for session := range allowed {
		if _, ok := allowed97[session]; !ok {
			return fmt.Errorf("固定99/97の場集合差")
		}
	}
	proof96SHA, err := tape.Digest(args.Proof96)
	if err != nil {
		return err
	}
	if proof96SHA != tape.SelectedCompletionSHA256 {
		return fmt.Errorf("固定96完了SHAが不一致")
	}
	allowed96, err := tape.SelectedCatalog(args.Proof96)
	if err != nil {
		return err
	}
	for session := range allowed {
		if _, ok := allowed96[session]; !ok {
			return fmt.Errorf("固定96/97の54集合が不一致")
		}
	}
	body, err := os.ReadFile(args.Index)
	if err != nil {
		return err
	}
	var index TapeIndex
	if err = json.Unmarshal(body, &index); err != nil {
		return err
	}
	if err = port.ValidateIndex(index, args.Stage, allowed); err != nil {
		return err
	}
	root, err := filepath.Abs(filepath.Join(filepath.Dir(args.Proof96), "..", ".."))
	if err != nil {
		return err
	}
	manifest := filepath.Join(root, "study", "00080_FAR後期三手法の15分移植と利益保護", "入力台帳.json")
	sha, err := tape.Digest(manifest)
	if err != nil {
		return err
	}
	if sha != condition.Manifest {
		return fmt.Errorf("固定80台帳のSHA差")
	}
	codePaths := []string{}
	for name, expected := range condition.Code {
		path := filepath.Join(root, name)
		got, err := tape.Digest(path)
		if err != nil {
			return err
		}
		if got != expected {
			return fmt.Errorf("固定コードのSHA差: %s", name)
		}
		codePaths = append(codePaths, path)
	}
	inputs := []string{args.Index, args.Condition, args.Proof99, args.Proof98, args.Proof97, args.Proof96, manifest}
	for i := range index.Entries {
		entry := &index.Entries[i]
		if !filepath.IsAbs(entry.Path) {
			entry.Path = filepath.Join(filepath.Dir(args.Index), entry.Path)
		}
		entry.Path, err = filepath.Abs(entry.Path)
		if err != nil {
			return err
		}
		got, err := tape.Digest(entry.Path)
		if err != nil {
			return err
		}
		if got != entry.SHA256 {
			return fmt.Errorf("TapeのSHA差: %s", entry.Session)
		}
		inputs = append(inputs, entry.Path, filepath.Join(filepath.Dir(args.Proof99), "成果物", entry.Session+".json.gz"))
	}
	inputBefore, err := fileHashes(inputs)
	if err != nil {
		return err
	}
	codeBefore, err := fileHashes(codePaths)
	if err != nil {
		return err
	}
	if _, err = os.Stat(args.Out); !os.IsNotExist(err) {
		return fmt.Errorf("出力dirは新規だけ")
	}
	if err = os.MkdirAll(args.Out, 0755); err != nil {
		return err
	}
	type outcome struct {
		Session string `json:"session"`
		Path    string `json:"path"`
		SHA256  string `json:"sha256"`
		Error   string `json:"error,omitempty"`
	}
	jobs, results := make(chan TapeEntry), make(chan outcome, len(index.Entries))
	var workers sync.WaitGroup
	for i := 0; i < args.Workers; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for entry := range jobs {
				result := outcome{Session: entry.Session}
				input, err := tape.LoadCache(entry.Path, entry.SHA256)
				if err == nil && input.Session.ID != entry.Session {
					err = fmt.Errorf("indexとTapeの場ID差")
				}
				var output Envelope
				if err == nil {
					output, err = BuildEnvelope(input, args.Proof99, args.Proof98, args.Proof97, args.Proof96, entry.Path, entry.SHA256)
				}
				if err == nil {
					var encoded []byte
					encoded, err = json.Marshal(output)
					if err == nil {
						result.Path = filepath.Join(args.Out, entry.Session+".json")
						err = os.WriteFile(result.Path, append(encoded, '\n'), 0644)
					}
					if err == nil {
						result.SHA256, err = tape.Digest(result.Path)
					}
				}
				if err != nil {
					result.Error = err.Error()
				}
				results <- result
			}
		}()
	}
	go func() {
		for _, entry := range index.Entries {
			jobs <- entry
		}
		close(jobs)
		workers.Wait()
		close(results)
	}()
	all := []outcome{}
	success := true
	for result := range results {
		all = append(all, result)
		if result.Error != "" {
			success = false
		}
	}
	sort.Slice(all, func(i, j int) bool { return all[i].Session < all[j].Session })
	inputAfter, afterErr := fileHashes(inputs)
	if afterErr != nil {
		return afterErr
	}
	codeAfter, err := fileHashes(codePaths)
	if err != nil {
		return err
	}
	left, _ := json.Marshal(inputBefore)
	right, _ := json.Marshal(inputAfter)
	inputEqual := string(left) == string(right)
	left, _ = json.Marshal(codeBefore)
	right, _ = json.Marshal(codeAfter)
	codeEqual := string(left) == string(right)
	success = success && inputEqual && codeEqual
	proof := map[string]any{"成功": success, "stage": args.Stage, "場数": len(all), "口座/場": 12, "H0対99E3S全文比較/場": 4, "結果": all, "入力前SHA256": inputBefore, "入力後SHA256": inputAfter, "コード前SHA256": codeBefore, "コード後SHA256": codeAfter, "入力前後不変": inputEqual, "コード前後不変": codeEqual, "Source再運転": false, "チャート再計算": false, "Raw/CSV読取": 0, "全原行BookSnapshot連鎖": "未計測。人工Runで同配送/最終全文/現在Gate回数を検査済み"}
	encoded, err := json.MarshalIndent(proof, "", "  ")
	if err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(args.Out, "完了.json"), append(encoded, '\n'), 0644); err != nil {
		return err
	}
	if !success {
		return fmt.Errorf("新金融又は指紋が不一致。保存した完了記録を参照")
	}
	return nil
}
