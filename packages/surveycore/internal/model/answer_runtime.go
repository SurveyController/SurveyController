package model

type AnswerRuntime interface {
	SnapshotDistributionStats(statKey string, optionCount int) (int, []int)
	AppendPendingDistributionChoice(owner string, statKey string, optionIndex int, optionCount int)
	CommitPendingDistribution(owner string) int
	ResetPendingDistribution(owner string)
}
