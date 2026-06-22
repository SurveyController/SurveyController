package reversefill

import (
	"path/filepath"
	"testing"

	"github.com/xuri/excelize/v2"
	"surveycontroller/surveycore"
)

func TestResolveOrderedColumnsReordersBySuffix(t *testing.T) {
	columns := []Column{
		{ColumnIndex: 4, Header: "1、矩阵题-功能", QuestionNum: 1, Suffix: "功能"},
		{ColumnIndex: 3, Header: "1、矩阵题-外观", QuestionNum: 1, Suffix: "外观"},
	}
	ordered := ResolveOrderedColumns(columns, []string{"外观", "功能"})
	if ordered[0].ColumnIndex != 3 || ordered[1].ColumnIndex != 4 {
		t.Fatalf("ordered = %#v", ordered)
	}
}

func TestParseChoiceAnswer(t *testing.T) {
	answer, err := ParseChoiceAnswer(1, "2", FormatWJXScore, []string{"差", "中", "好"})
	if err != nil {
		t.Fatal(err)
	}
	if answer == nil || answer.ChoiceIndex == nil || *answer.ChoiceIndex != 1 {
		t.Fatalf("answer = %#v", answer)
	}
	_, err = ParseChoiceAnswer(1, "其他〖请填写〗", FormatWJXText, []string{"A"})
	if err == nil {
		t.Fatal("expected composite error")
	}
}

func TestParseMatrixAnswerRejectsPartialBlank(t *testing.T) {
	_, err := ParseMatrixAnswer(4, []Column{{ColumnIndex: 5}, {ColumnIndex: 6}}, RawRow{ValuesByColumn: map[int]string{5: "1", 6: ""}}, FormatWJXScore, []string{"差", "中", "好"})
	if err == nil {
		t.Fatal("expected partial blank error")
	}
}

func TestPreviewExcelParsesRows(t *testing.T) {
	path := filepath.Join(t.TempDir(), "reverse.xlsx")
	file := excelize.NewFile()
	sheet := file.GetSheetName(0)
	_ = file.SetSheetRow(sheet, "A1", &[]any{"1、单选题", "2、文本题", "3、矩阵题-外观", "3、矩阵题-功能"})
	_ = file.SetSheetRow(sheet, "A2", &[]any{"B", "hello", "1", "2"})
	if err := file.SaveAs(path); err != nil {
		t.Fatal(err)
	}
	_ = file.Close()

	preview, err := PreviewExcel(PreviewOptions{
		Path:     path,
		Format:   FormatWJXText,
		StartRow: 1,
		Questions: []surveycore.QuestionMeta{
			{Num: 1, Title: "单选题", TypeCode: "3", OptionTexts: []string{"A", "B"}},
			{Num: 2, Title: "文本题", TypeCode: "1", TextInputs: 1},
			{Num: 3, Title: "矩阵题", TypeCode: "6", OptionTexts: []string{"差", "好"}, RowTexts: []string{"外观", "功能"}},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if preview.TotalDataRows != 1 || len(preview.SampleRows) != 1 {
		t.Fatalf("preview = %#v", preview)
	}
	if answer := preview.SampleRows[0].Answers[1]; answer.ChoiceIndex == nil || *answer.ChoiceIndex != 1 {
		t.Fatalf("single answer = %#v", answer)
	}
	if answer := preview.SampleRows[0].Answers[3]; len(answer.MatrixChoiceIndexes) != 2 {
		t.Fatalf("matrix answer = %#v", answer)
	}
}
