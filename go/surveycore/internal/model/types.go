package model

import "time"

const (
	ProviderWJX     = "wjx"
	ProviderQQ      = "qq"
	ProviderCredamo = "credamo"

	LogicParseStatusNone    = "none"
	LogicParseStatusUnknown = "unknown"
)

type SurveyDefinition struct {
	Provider  string         `json:"provider"`
	Title     string         `json:"title"`
	Questions []QuestionMeta `json:"questions"`
}

type QuestionMeta struct {
	Num             int      `json:"num"`
	Title           string   `json:"title"`
	Description     string   `json:"description"`
	TypeCode        string   `json:"type_code"`
	Options         int      `json:"options"`
	Rows            int      `json:"rows"`
	RowTexts        []string `json:"row_texts"`
	Page            int      `json:"page"`
	OptionTexts     []string `json:"option_texts"`
	Provider        string   `json:"provider"`
	ProviderID      string   `json:"provider_question_id"`
	ProviderPageID  string   `json:"provider_page_id"`
	ProviderType    string   `json:"provider_type"`
	Required        bool     `json:"required"`
	IsDescription   bool     `json:"is_description"`
	IsRating        bool     `json:"is_rating"`
	RatingMax       int      `json:"rating_max"`
	TextInputs      int      `json:"text_inputs"`
	IsTextLike      bool     `json:"is_text_like"`
	IsMultiText     bool     `json:"is_multi_text"`
	LogicStatus     string   `json:"logic_parse_status"`
	MultiMinLimit   *int     `json:"multi_min_limit,omitempty"`
	MultiMaxLimit   *int     `json:"multi_max_limit,omitempty"`
	ForcedOptionIdx *int     `json:"forced_option_index,omitempty"`
	ForcedOption    string   `json:"forced_option_text"`
	ForcedTexts     []string `json:"forced_texts"`
	FillableOptions []int    `json:"fillable_options"`
}

type RuntimeConfig struct {
	URL                    string          `json:"url"`
	SurveyTitle            string          `json:"survey_title,omitempty"`
	SurveyProvider         string          `json:"survey_provider,omitempty"`
	Target                 int             `json:"target,omitempty"`
	Threads                int             `json:"threads,omitempty"`
	AnswerDuration         [2]int          `json:"answer_duration,omitempty"`
	ReliabilityModeEnabled bool            `json:"reliability_mode_enabled,omitempty"`
	PsychoTargetAlpha      float64         `json:"psycho_target_alpha,omitempty"`
	QuestionEntries        []QuestionEntry `json:"question_entries,omitempty"`
	QuestionsInfo          []QuestionMeta  `json:"questions_info,omitempty"`
}

type QuestionEntry struct {
	QuestionType          string    `json:"question_type"`
	Probabilities         any       `json:"probabilities"`
	Texts                 []string  `json:"texts,omitempty"`
	Rows                  int       `json:"rows,omitempty"`
	OptionCount           int       `json:"option_count,omitempty"`
	DistributionMode      string    `json:"distribution_mode,omitempty"`
	CustomWeights         any       `json:"custom_weights,omitempty"`
	QuestionNum           *int      `json:"question_num,omitempty"`
	QuestionTitle         *string   `json:"question_title,omitempty"`
	SurveyProvider        string    `json:"survey_provider,omitempty"`
	ProviderQuestionID    *string   `json:"provider_question_id,omitempty"`
	ProviderPageID        *string   `json:"provider_page_id,omitempty"`
	AIEnabled             bool      `json:"ai_enabled,omitempty"`
	OptionFillTexts       []*string `json:"option_fill_texts,omitempty"`
	FillableOptionIndices []int     `json:"fillable_option_indices,omitempty"`
	PsychoBias            string    `json:"psycho_bias,omitempty"`
}

type RunResult struct {
	Success        int              `json:"success"`
	Fail           int              `json:"fail"`
	Stopped        bool             `json:"stopped"`
	ThreadProgress []ThreadProgress `json:"thread_progress,omitempty"`
}

type ThreadProgress struct {
	ThreadName   string    `json:"thread_name"`
	ThreadIndex  int       `json:"thread_index"`
	SuccessCount int       `json:"success_count"`
	FailCount    int       `json:"fail_count"`
	StepCurrent  int       `json:"step_current"`
	StepTotal    int       `json:"step_total"`
	StatusText   string    `json:"status_text"`
	Running      bool      `json:"running"`
	LastUpdate   time.Time `json:"last_update,omitempty"`
}

type Event struct {
	Worker  string    `json:"worker"`
	Message string    `json:"message"`
	Success bool      `json:"success"`
	Fail    bool      `json:"fail"`
	Current int       `json:"current"`
	Total   int       `json:"total"`
	Time    time.Time `json:"time"`
}
