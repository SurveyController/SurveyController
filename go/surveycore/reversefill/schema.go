package reversefill

const (
	FormatAuto        = "auto"
	FormatWJXSequence = "wjx_sequence"
	FormatWJXScore    = "wjx_score"
	FormatWJXText     = "wjx_text"

	KindChoice    = "choice"
	KindText      = "text"
	KindMultiText = "multi_text"
	KindMatrix    = "matrix"
)

type Column struct {
	ColumnIndex int    `json:"column_index"`
	Header      string `json:"header"`
	QuestionNum int    `json:"question_num"`
	Suffix      string `json:"suffix,omitempty"`
}

type RawRow struct {
	DataRowNumber      int            `json:"data_row_number"`
	WorksheetRowNumber int            `json:"worksheet_row_number"`
	ValuesByColumn     map[int]string `json:"values_by_column"`
}

type Answer struct {
	QuestionNum         int      `json:"question_num"`
	Kind                string   `json:"kind"`
	ChoiceIndex         *int     `json:"choice_index,omitempty"`
	TextValue           string   `json:"text_value,omitempty"`
	TextValues          []string `json:"text_values,omitempty"`
	MatrixChoiceIndexes []int    `json:"matrix_choice_indexes,omitempty"`
}

type SampleRow struct {
	DataRowNumber      int            `json:"data_row_number"`
	WorksheetRowNumber int            `json:"worksheet_row_number"`
	Answers            map[int]Answer `json:"answers"`
}

type Preview struct {
	SourcePath        string           `json:"source_path"`
	SelectedFormat    string           `json:"selected_format"`
	DetectedFormat    string           `json:"detected_format"`
	HeaderRowNumber   int              `json:"header_row_number"`
	TotalDataRows     int              `json:"total_data_rows"`
	QuestionColumns   map[int][]Column `json:"question_columns"`
	SampleRows        []SampleRow      `json:"sample_rows"`
	UnsupportedFields []string         `json:"unsupported_fields,omitempty"`
}
