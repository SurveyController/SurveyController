package model

import "time"

const (
	ProviderWJX     = "wjx"
	ProviderQQ      = "qq"
	ProviderCredamo = "credamo"

	LogicParseStatusComplete = "complete"
	LogicParseStatusNone     = "none"
	LogicParseStatusUnknown  = "unknown"
)

type SurveyDefinition struct {
	Provider  string         `json:"provider"`
	Title     string         `json:"title"`
	Questions []QuestionMeta `json:"questions"`
}

type QuestionMeta struct {
	Num                      int              `json:"num"`
	Title                    string           `json:"title"`
	DisplayNum               *int             `json:"display_num,omitempty"`
	Description              string           `json:"description"`
	TypeCode                 string           `json:"type_code"`
	Options                  int              `json:"options"`
	Rows                     int              `json:"rows"`
	RowTexts                 []string         `json:"row_texts"`
	Page                     int              `json:"page"`
	OptionTexts              []string         `json:"option_texts"`
	Provider                 string           `json:"provider"`
	ProviderID               string           `json:"provider_question_id"`
	ProviderPageID           string           `json:"provider_page_id"`
	ProviderType             string           `json:"provider_type"`
	ProviderPageRaw          any              `json:"provider_page_raw,omitempty"`
	Required                 bool             `json:"required"`
	IsDescription            bool             `json:"is_description"`
	IsLocation               bool             `json:"is_location"`
	IsRating                 bool             `json:"is_rating"`
	RatingMax                int              `json:"rating_max"`
	TextInputs               int              `json:"text_inputs"`
	TextInputLabels          []string         `json:"text_input_labels"`
	IsTextLike               bool             `json:"is_text_like"`
	IsMultiText              bool             `json:"is_multi_text"`
	IsSliderMatrix           bool             `json:"is_slider_matrix"`
	LogicStatus              string           `json:"logic_parse_status"`
	HasJump                  bool             `json:"has_jump"`
	JumpRules                []map[string]any `json:"jump_rules"`
	HasDisplayCondition      bool             `json:"has_display_condition"`
	DisplayConditions        []map[string]any `json:"display_conditions"`
	HasDependentDisplayLogic bool             `json:"has_dependent_display_logic"`
	ControlsDisplayTargets   []map[string]any `json:"controls_display_targets"`
	QuestionMedia            []map[string]any `json:"question_media"`
	SliderMin                any              `json:"slider_min,omitempty"`
	SliderMax                any              `json:"slider_max,omitempty"`
	SliderStep               any              `json:"slider_step,omitempty"`
	MultiMinLimit            *int             `json:"multi_min_limit,omitempty"`
	MultiMaxLimit            *int             `json:"multi_max_limit,omitempty"`
	ForcedOptionIdx          *int             `json:"forced_option_index,omitempty"`
	ForcedOption             string           `json:"forced_option_text"`
	ForcedTexts              []string         `json:"forced_texts"`
	FillableOptions          []int            `json:"fillable_options"`
	AttachedOptionSelects    []map[string]any `json:"attached_option_selects"`
	HasAttachedOptionSelect  bool             `json:"has_attached_option_select"`
	Unsupported              bool             `json:"unsupported"`
	UnsupportedReason        string           `json:"unsupported_reason"`
}

type RuntimeConfig struct {
	URL                    string           `json:"url"`
	SurveyTitle            string           `json:"survey_title,omitempty"`
	SurveyProvider         string           `json:"survey_provider,omitempty"`
	Target                 int              `json:"target,omitempty"`
	Threads                int              `json:"threads,omitempty"`
	SubmitInterval         [2]int           `json:"submit_interval,omitempty"`
	AnswerDuration         [2]int           `json:"answer_duration,omitempty"`
	AnswerDatetimeWindow   [2]string        `json:"answer_datetime_window,omitempty"`
	RandomIPEnabled        bool             `json:"random_ip_enabled,omitempty"`
	ProxySource            string           `json:"proxy_source,omitempty"`
	CustomProxyAPI         string           `json:"custom_proxy_api,omitempty"`
	ProxyAreaCode          *string          `json:"proxy_area_code,omitempty"`
	ActiveProxyAddress     string           `json:"-"`
	RandomUAEnabled        bool             `json:"random_ua_enabled,omitempty"`
	RandomUARatios         map[string]int   `json:"random_ua_ratios,omitempty"`
	FailStopEnabled        bool             `json:"fail_stop_enabled,omitempty"`
	PauseOnAliyunCaptcha   bool             `json:"pause_on_aliyun_captcha,omitempty"`
	ReliabilityModeEnabled bool             `json:"reliability_mode_enabled,omitempty"`
	PsychoTargetAlpha      float64          `json:"psycho_target_alpha,omitempty"`
	AIMode                 string           `json:"ai_mode,omitempty"`
	AIProvider             string           `json:"ai_provider,omitempty"`
	AIAPIKey               string           `json:"ai_api_key,omitempty"`
	AIBaseURL              string           `json:"ai_base_url,omitempty"`
	AIAPIProtocol          string           `json:"ai_api_protocol,omitempty"`
	AIModel                string           `json:"ai_model,omitempty"`
	AISystemPrompt         string           `json:"ai_system_prompt,omitempty"`
	ReverseFillEnabled     bool             `json:"reverse_fill_enabled,omitempty"`
	ReverseFillSourcePath  string           `json:"reverse_fill_source_path,omitempty"`
	ReverseFillFormat      string           `json:"reverse_fill_format,omitempty"`
	ReverseFillStartRow    int              `json:"reverse_fill_start_row,omitempty"`
	ReverseFillThreads     int              `json:"reverse_fill_threads,omitempty"`
	AnswerRules            []map[string]any `json:"answer_rules,omitempty"`
	DimensionGroups        []string         `json:"dimension_groups,omitempty"`
	QuestionEntries        []QuestionEntry  `json:"question_entries,omitempty"`
	QuestionsInfo          []QuestionMeta   `json:"questions_info,omitempty"`
	AnswerRuntime          AnswerRuntime    `json:"-"`
	AnswerRuntimeOwner     string           `json:"-"`
	Persona                *Persona         `json:"-"`
}

type QuestionEntry struct {
	QuestionType            string           `json:"question_type"`
	Probabilities           any              `json:"probabilities"`
	Texts                   []string         `json:"texts,omitempty"`
	Rows                    int              `json:"rows,omitempty"`
	OptionCount             int              `json:"option_count,omitempty"`
	DistributionMode        string           `json:"distribution_mode,omitempty"`
	CustomWeights           any              `json:"custom_weights,omitempty"`
	QuestionNum             *int             `json:"question_num,omitempty"`
	QuestionTitle           *string          `json:"question_title,omitempty"`
	SurveyProvider          string           `json:"survey_provider,omitempty"`
	ProviderQuestionID      *string          `json:"provider_question_id,omitempty"`
	ProviderPageID          *string          `json:"provider_page_id,omitempty"`
	AIEnabled               bool             `json:"ai_enabled,omitempty"`
	OptionFillTexts         []*string        `json:"option_fill_texts,omitempty"`
	FillableOptionIndices   []int            `json:"fillable_option_indices,omitempty"`
	AttachedOptionSelects   []map[string]any `json:"attached_option_selects,omitempty"`
	IsLocation              bool             `json:"is_location,omitempty"`
	LocationParts           []string         `json:"location_parts,omitempty"`
	MultiTextBlankModes     []string         `json:"multi_text_blank_modes,omitempty"`
	MultiTextBlankAIFlags   []bool           `json:"multi_text_blank_ai_flags,omitempty"`
	MultiTextBlankIntRanges [][]int          `json:"multi_text_blank_int_ranges,omitempty"`
	TextRandomMode          string           `json:"text_random_mode,omitempty"`
	TextRandomIntRange      []int            `json:"text_random_int_range,omitempty"`
	Dimension               string           `json:"dimension,omitempty"`
	PsychoBias              string           `json:"psycho_bias,omitempty"`
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
