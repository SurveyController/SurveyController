package surveycore

import (
	"context"
	"math"
	"math/rand"
	"strings"
	"sync"

	"surveycontroller/surveycore/internal/model"
)

type distributionChoice struct {
	statKey     string
	optionIndex int
	optionCount int
}

type distributionBucket struct {
	total  int
	counts []int
}

type answerRuntimeState struct {
	mu      sync.Mutex
	stats   map[string]distributionBucket
	pending map[string][]distributionChoice
}

func newAnswerRuntimeState() *answerRuntimeState {
	return &answerRuntimeState{
		stats:   map[string]distributionBucket{},
		pending: map[string][]distributionChoice{},
	}
}

func (s *answerRuntimeState) SnapshotDistributionStats(statKey string, optionCount int) (int, []int) {
	if s == nil {
		return 0, make([]int, maxInt(0, optionCount))
	}
	key := strings.TrimSpace(statKey)
	count := maxInt(0, optionCount)
	s.mu.Lock()
	defer s.mu.Unlock()
	bucket := s.stats[key]
	counts := normalizeDistributionCounts(bucket.counts, count)
	return maxInt(0, bucket.total), counts
}

func (s *answerRuntimeState) AppendPendingDistributionChoice(owner string, statKey string, optionIndex int, optionCount int) {
	if s == nil || optionCount <= 0 || optionIndex < 0 || optionIndex >= optionCount {
		return
	}
	key := runtimeOwnerKey(owner)
	choice := distributionChoice{
		statKey:     strings.TrimSpace(statKey),
		optionIndex: optionIndex,
		optionCount: optionCount,
	}
	s.mu.Lock()
	s.pending[key] = append(s.pending[key], choice)
	s.mu.Unlock()
}

func (s *answerRuntimeState) CommitPendingDistribution(owner string) int {
	if s == nil {
		return 0
	}
	key := runtimeOwnerKey(owner)
	s.mu.Lock()
	defer s.mu.Unlock()
	pending := append([]distributionChoice(nil), s.pending[key]...)
	delete(s.pending, key)
	committed := 0
	for _, choice := range pending {
		if choice.optionCount <= 0 || choice.optionIndex < 0 || choice.optionIndex >= choice.optionCount {
			continue
		}
		bucket := s.stats[choice.statKey]
		counts := normalizeDistributionCounts(bucket.counts, choice.optionCount)
		counts[choice.optionIndex]++
		bucket.total = maxInt(0, bucket.total) + 1
		bucket.counts = counts
		s.stats[choice.statKey] = bucket
		committed++
	}
	return committed
}

func (s *answerRuntimeState) ResetPendingDistribution(owner string) {
	if s == nil {
		return
	}
	s.mu.Lock()
	delete(s.pending, runtimeOwnerKey(owner))
	s.mu.Unlock()
}

func normalizeDistributionCounts(raw []int, optionCount int) []int {
	count := maxInt(0, optionCount)
	normalized := make([]int, count)
	for index := 0; index < len(raw) && index < count; index++ {
		normalized[index] = maxInt(0, raw[index])
	}
	return normalized
}

func runtimeOwnerKey(owner string) string {
	key := strings.TrimSpace(owner)
	if key == "" {
		return "Worker-?"
	}
	return key
}

func (c *Client) prepareAnswerRuntimeExecution(cfg *RuntimeConfig, options ExecutionOptions) (*RuntimeConfig, ExecutionOptions) {
	runCfg := cloneRuntimeConfig(cfg)
	runtime := runCfg.AnswerRuntime
	if runtime == nil {
		runtime = newAnswerRuntimeState()
		runCfg.AnswerRuntime = runtime
	}
	configure := options.ConfigureRun
	options.ConfigureRun = func(ctx context.Context, jobIndex int, attempt int, local *RuntimeConfig) error {
		if configure != nil {
			if err := configure(ctx, jobIndex, attempt, local); err != nil {
				return err
			}
		}
		if local.AnswerRuntime == nil {
			local.AnswerRuntime = runtime
		}
		persona := generatePersona()
		local.Persona = &persona
		return nil
	}
	return &runCfg, options
}

func resetPendingAnswerRuntime(cfg *RuntimeConfig) {
	if cfg == nil || cfg.AnswerRuntime == nil {
		return
	}
	cfg.AnswerRuntime.ResetPendingDistribution(cfg.AnswerRuntimeOwner)
}

func finalizeAnswerRuntime(cfg *RuntimeConfig, success bool) {
	if cfg == nil || cfg.AnswerRuntime == nil {
		return
	}
	if success {
		cfg.AnswerRuntime.CommitPendingDistribution(cfg.AnswerRuntimeOwner)
		return
	}
	cfg.AnswerRuntime.ResetPendingDistribution(cfg.AnswerRuntimeOwner)
}

func generatePersona() model.Persona {
	persona := model.Persona{}
	persona.Gender = weightedString([]string{"男", "女"}, []float64{1, 1})
	persona.AgeGroup = weightedString([]string{"18-25", "26-35", "36-45", "46-60"}, []float64{35, 35, 20, 10})
	switch persona.AgeGroup {
	case "18-25":
		persona.Education = weightedString([]string{"高中及以下", "大专", "本科", "研究生及以上"}, []float64{15, 20, 50, 15})
		persona.Occupation = weightedString([]string{"学生", "上班族", "自由职业"}, []float64{55, 35, 10})
	case "46-60":
		persona.Education = weightedString([]string{"高中及以下", "大专", "本科", "研究生及以上"}, []float64{25, 25, 35, 15})
		persona.Occupation = weightedString([]string{"上班族", "自由职业", "退休"}, []float64{50, 25, 25})
	default:
		persona.Education = weightedString([]string{"高中及以下", "大专", "本科", "研究生及以上"}, []float64{10, 20, 45, 25})
		persona.Occupation = weightedString([]string{"上班族", "自由职业"}, []float64{75, 25})
	}
	switch {
	case persona.Occupation == "学生":
		persona.IncomeLevel = weightedString([]string{"低", "中"}, []float64{85, 15})
	case persona.Occupation == "退休":
		persona.IncomeLevel = weightedString([]string{"低", "中", "高"}, []float64{30, 50, 20})
	case persona.AgeGroup == "36-45" || persona.AgeGroup == "46-60":
		persona.IncomeLevel = weightedString([]string{"低", "中", "高"}, []float64{15, 45, 40})
	case persona.AgeGroup == "26-35":
		persona.IncomeLevel = weightedString([]string{"低", "中", "高"}, []float64{20, 50, 30})
	default:
		persona.IncomeLevel = weightedString([]string{"低", "中", "高"}, []float64{40, 45, 15})
	}
	switch persona.AgeGroup {
	case "18-25":
		persona.MaritalStatus = weightedString([]string{"未婚", "已婚"}, []float64{90, 10})
	case "26-35":
		persona.MaritalStatus = weightedString([]string{"未婚", "已婚"}, []float64{45, 55})
	case "36-45":
		persona.MaritalStatus = weightedString([]string{"未婚", "已婚"}, []float64{15, 85})
	default:
		persona.MaritalStatus = weightedString([]string{"未婚", "已婚"}, []float64{10, 90})
	}
	switch {
	case persona.MaritalStatus == "未婚":
		persona.HasChildren = rand.Float64() < 0.03
	case persona.AgeGroup == "36-45" || persona.AgeGroup == "46-60":
		persona.HasChildren = rand.Float64() < 0.90
	case persona.AgeGroup == "26-35":
		persona.HasChildren = rand.Float64() < 0.50
	default:
		persona.HasChildren = rand.Float64() < 0.10
	}
	persona.SatisfactionTendency = math.Max(0.1, math.Min(0.9, rand.NormFloat64()*0.15+0.6))
	return persona
}

func weightedString(values []string, weights []float64) string {
	if len(values) == 0 {
		return ""
	}
	total := 0.0
	for i := 0; i < len(values) && i < len(weights); i++ {
		if weights[i] > 0 {
			total += weights[i]
		}
	}
	if total <= 0 {
		return values[rand.Intn(len(values))]
	}
	pick := rand.Float64() * total
	acc := 0.0
	for i, value := range values {
		if i >= len(weights) || weights[i] <= 0 {
			continue
		}
		acc += weights[i]
		if pick <= acc {
			return value
		}
	}
	return values[len(values)-1]
}
