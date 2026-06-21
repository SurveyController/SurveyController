package reversefill

import (
	"fmt"
	"strings"

	"github.com/xuri/excelize/v2"
	"surveycontroller/surveycore"
)

type PreviewOptions struct {
	Path            string
	Format          string
	StartRow        int
	Questions       []surveycore.QuestionMeta
	QuestionEntries []surveycore.QuestionEntry
	MaxSampleRows   int
}

func PreviewExcel(options PreviewOptions) (Preview, error) {
	path := strings.TrimSpace(options.Path)
	if path == "" {
		return Preview{}, fmt.Errorf("反填 Excel 路径不能为空")
	}
	file, err := excelize.OpenFile(path)
	if err != nil {
		return Preview{}, err
	}
	defer file.Close()
	sheets := file.GetSheetList()
	if len(sheets) == 0 {
		return Preview{}, fmt.Errorf("Excel 文件没有工作表")
	}
	rows, err := file.GetRows(sheets[0])
	if err != nil {
		return Preview{}, err
	}
	if len(rows) == 0 {
		return Preview{}, fmt.Errorf("Excel 工作表为空")
	}
	headerRowNumber := 1
	headers := rows[0]
	startRow := options.StartRow
	if startRow < 1 {
		startRow = 1
	}
	dataStartIndex := startRow
	if dataStartIndex < 1 {
		dataStartIndex = 1
	}
	columns := InferQuestionColumns(headers)
	format := strings.ToLower(strings.TrimSpace(options.Format))
	if format == "" || format == FormatAuto {
		format = FormatWJXText
	}
	maxRows := options.MaxSampleRows
	if maxRows <= 0 {
		maxRows = 20
	}
	preview := Preview{
		SourcePath:      path,
		SelectedFormat:  options.Format,
		DetectedFormat:  format,
		HeaderRowNumber: headerRowNumber,
		TotalDataRows:   maxInt(0, len(rows)-dataStartIndex),
		QuestionColumns: columns,
		SampleRows:      []SampleRow{},
	}
	questionByNum := map[int]surveycore.QuestionMeta{}
	for _, question := range options.Questions {
		questionByNum[question.Num] = question
	}
	for rowIndex := dataStartIndex; rowIndex < len(rows) && len(preview.SampleRows) < maxRows; rowIndex++ {
		rawRow := RawRow{
			DataRowNumber:      rowIndex - dataStartIndex + 1,
			WorksheetRowNumber: rowIndex + 1,
			ValuesByColumn:     valuesByColumn(rows[rowIndex]),
		}
		sample := SampleRow{
			DataRowNumber:      rawRow.DataRowNumber,
			WorksheetRowNumber: rawRow.WorksheetRowNumber,
			Answers:            map[int]Answer{},
		}
		for questionNum, questionColumns := range columns {
			question, ok := questionByNum[questionNum]
			if !ok {
				continue
			}
			answer, err := parseQuestionAnswer(question, questionColumns, rawRow, format)
			if err != nil {
				preview.UnsupportedFields = append(preview.UnsupportedFields, fmt.Sprintf("第%d题第%d行：%v", questionNum, rawRow.WorksheetRowNumber, err))
				continue
			}
			if answer != nil {
				sample.Answers[questionNum] = *answer
			}
		}
		if len(sample.Answers) > 0 {
			preview.SampleRows = append(preview.SampleRows, sample)
		}
	}
	return preview, nil
}

func parseQuestionAnswer(question surveycore.QuestionMeta, columns []Column, row RawRow, format string) (*Answer, error) {
	questionType := inferQuestionType(question)
	orderedColumns := ResolveOrderedColumns(columns, question.RowTexts)
	switch questionType {
	case "single", "dropdown", "scale":
		if len(orderedColumns) == 0 {
			return nil, nil
		}
		return ParseChoiceAnswer(question.Num, row.ValuesByColumn[orderedColumns[0].ColumnIndex], format, question.OptionTexts)
	case "text":
		if question.TextInputs > 1 || len(orderedColumns) > 1 {
			return ParseMultiTextAnswer(question.Num, orderedColumns, row), nil
		}
		if len(orderedColumns) == 0 {
			return nil, nil
		}
		return ParseTextAnswer(question.Num, row.ValuesByColumn[orderedColumns[0].ColumnIndex]), nil
	case "matrix":
		return ParseMatrixAnswer(question.Num, orderedColumns, row, format, question.OptionTexts)
	default:
		return nil, fmt.Errorf("暂不支持反填题型：%s", questionType)
	}
}

func inferQuestionType(question surveycore.QuestionMeta) string {
	if question.ProviderType != "" {
		switch question.ProviderType {
		case "radio", "single":
			return "single"
		case "select", "dropdown":
			return "dropdown"
		case "matrix_radio", "matrix":
			return "matrix"
		case "text", "textarea":
			return "text"
		}
	}
	switch question.TypeCode {
	case "3":
		return "single"
	case "5":
		return "scale"
	case "6":
		return "matrix"
	case "7":
		return "dropdown"
	default:
		return "text"
	}
}

func valuesByColumn(row []string) map[int]string {
	result := map[int]string{}
	for index, value := range row {
		result[index+1] = value
	}
	return result
}

func maxInt(left int, right int) int {
	if left > right {
		return left
	}
	return right
}
