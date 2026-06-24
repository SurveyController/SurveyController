package surveycore

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/xuri/excelize/v2"
)

func TestRunWJXReverseFillSubmitsExcelAnswers(t *testing.T) {
	sourcePath := filepath.Join(t.TempDir(), "reverse.xlsx")
	file := excelize.NewFile()
	sheet := file.GetSheetName(0)
	_ = file.SetSheetRow(sheet, "A1", &[]any{"1、单选题", "2、文本题", "3、矩阵题-外观", "3、矩阵题-功能"})
	_ = file.SetSheetRow(sheet, "A2", &[]any{"B", "hello", "1", "2"})
	if err := file.SaveAs(sourcePath); err != nil {
		t.Fatal(err)
	}
	_ = file.Close()

	var submitData string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/vm/demo.aspx":
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			_, _ = io.WriteString(w, reverseFillWJXHTML())
		case "/joinnew/processjq.ashx":
			if err := r.ParseForm(); err != nil {
				t.Fatal(err)
			}
			submitData = r.Form.Get("submitdata")
			_, _ = io.WriteString(w, "10")
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer server.Close()

	result, err := New(WithHTTPClient(rewriteWJXHTTPClient(server.URL))).Run(context.Background(), &RuntimeConfig{
		URL:                   "https://www.wjx.cn/vm/demo.aspx",
		SurveyProvider:        ProviderWJX,
		Target:                1,
		ReverseFillEnabled:    true,
		ReverseFillSourcePath: sourcePath,
		ReverseFillFormat:     "wjx_text",
		ReverseFillStartRow:   1,
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Success != 1 || result.Fail != 0 {
		t.Fatalf("result = %#v", result)
	}
	for _, want := range []string{"1$2", "2$hello", "3$1!1,2!2"} {
		if !strings.Contains(submitData, want) {
			t.Fatalf("submitdata = %q, want %q", submitData, want)
		}
	}
}

func TestPrepareReverseFillRejectsUnsupportedProvider(t *testing.T) {
	_, _, err := New().prepareReverseFillExecution(context.Background(), &RuntimeConfig{
		URL:                   "https://www.wjx.cn/vm/demo.aspx",
		SurveyProvider:        ProviderCredamo,
		Target:                1,
		ReverseFillEnabled:    true,
		ReverseFillSourcePath: "demo.xlsx",
	}, ProviderCredamo, ExecutionOptions{})
	if err == nil || !strings.Contains(err.Error(), "只支持问卷星") {
		t.Fatalf("err = %v", err)
	}
}

func reverseFillWJXHTML() string {
	return `
<html>
  <head><title>反填测试 - 问卷星</title></head>
  <body>
    <div id="divQuestion">
      <fieldset>
        <div topic="1" id="div1" type="3">
          <div class="topichtml">1. 单选题</div>
          <div class="ui-controlgroup">
            <div><span class="label">A</span></div>
            <div><span class="label">B</span></div>
          </div>
        </div>
        <div topic="2" id="div2" type="1">
          <div class="topichtml">2. 文本题</div>
          <input type="text" />
        </div>
        <div topic="3" id="div3" type="6">
          <div class="topichtml">3. 矩阵题</div>
          <table id="divRefTab3">
            <tr><td></td><td>差</td><td>好</td></tr>
            <tr rowindex="1"><td>外观</td><td><input name="q3_1_1" /></td><td><input name="q3_1_2" /></td></tr>
            <tr rowindex="2"><td>功能</td><td><input name="q3_2_1" /></td><td><input name="q3_2_2" /></td></tr>
          </table>
        </div>
      </fieldset>
    </div>
  </body>
</html>`
}
