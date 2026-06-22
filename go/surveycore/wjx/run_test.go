package wjx

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"surveycontroller/surveycore/internal/model"
)

func TestRunnerSubmitsWJX(t *testing.T) {
	server := newWJXTestServer(t, true)
	defer server.Close()
	cfg := &model.RuntimeConfig{
		URL:            "https://www.wjx.cn/vm/demo.aspx",
		SurveyProvider: model.ProviderWJX,
		Target:         1,
	}
	var events []Event
	result, err := (Runner{Client: rewriteWJXClient(server.URL)}).Run(context.Background(), cfg, func(event Event) {
		events = append(events, event)
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Success != 1 || result.Fail != 0 || len(events) == 0 {
		t.Fatalf("result = %#v events = %#v", result, events)
	}
}

func TestRunnerReturnsRejectedSubmit(t *testing.T) {
	server := newWJXTestServer(t, false)
	defer server.Close()
	cfg := &model.RuntimeConfig{
		URL:            "https://www.wjx.cn/vm/demo.aspx",
		SurveyProvider: model.ProviderWJX,
		Target:         1,
	}
	_, err := (Runner{Client: rewriteWJXClient(server.URL)}).Run(context.Background(), cfg, nil)
	if err == nil || !strings.Contains(err.Error(), "提交被拒绝") {
		t.Fatalf("err = %v", err)
	}
}

func newWJXTestServer(t *testing.T, submitOK bool) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/vm/demo.aspx":
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			_, _ = w.Write([]byte(sampleHTML()))
		case "/joinnew/processjq.ashx":
			if err := r.ParseForm(); err != nil {
				t.Fatal(err)
			}
			submitData := r.Form.Get("submitdata")
			if !strings.Contains(submitData, "1$") || !strings.Contains(submitData, "2$") || !strings.Contains(submitData, "5$") {
				t.Fatalf("submitdata = %q", submitData)
			}
			if submitOK {
				_, _ = io.WriteString(w, "10")
			} else {
				_, _ = io.WriteString(w, "1〒2〒答案不符合要求")
			}
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
}

func rewriteWJXClient(baseURL string) *http.Client {
	return &http.Client{Transport: rewriteWJXTransport{baseURL: baseURL, next: http.DefaultTransport}}
}

type rewriteWJXTransport struct {
	baseURL string
	next    http.RoundTripper
}

func (t rewriteWJXTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if strings.Contains(req.URL.Host, "wjx.cn") || strings.Contains(req.URL.Host, "wjx.com") {
		rewritten, err := http.NewRequestWithContext(req.Context(), req.Method, strings.Replace(req.URL.String(), req.URL.Scheme+"://"+req.URL.Host, t.baseURL, 1), req.Body)
		if err != nil {
			return nil, err
		}
		rewritten.Header = req.Header.Clone()
		req = rewritten
	}
	return t.next.RoundTrip(req)
}

func sampleHTML() string {
	return `
<html>
  <head><title>消费测试 - 问卷星</title></head>
  <body>
    <div id="divTitle"><h1>消费测试 - 问卷星</h1></div>
    <div id="divQuestion">
      <fieldset>
        <div topic="1" id="div1" type="3" req="1">
          <div class="topichtml">1. 本题检测，请选择 非常满意</div>
          <div class="ui-controlgroup">
            <div><span class="label">一般</span></div>
            <div><span class="label">非常满意</span></div>
          </div>
        </div>
        <div topic="2" id="div2" type="4">
          <div class="topichtml">2. 常用功能 [至少选1项，最多选2项]</div>
          <div class="ui-controlgroup">
            <div><span class="label">功能A</span></div>
            <div><span class="label">功能B</span></div>
            <div><span class="label">其他</span><input type="text" /></div>
          </div>
        </div>
        <div topic="3" id="div3" type="7">
          <div class="topichtml">3. 城市</div>
          <select id="q3"><option value="">请选择</option><option>北京</option><option>上海</option></select>
        </div>
        <div topic="4" id="div4" type="5">
          <div class="topichtml">4. 满意度</div>
          <ul tp="d"><li><a dval="1">1</a></li><li><a dval="2">2</a></li><li><a dval="3">3</a></li><li><a dval="4">4</a></li><li><a dval="5">5</a></li></ul>
        </div>
        <div topic="5" id="div5" type="6">
          <div class="topichtml">5. 矩阵题</div>
          <table id="divRefTab5">
            <tr><td></td><td>差</td><td>好</td></tr>
            <tr rowindex="1"><td>外观</td><td><input name="q5_1_1" /></td><td><input name="q5_1_2" /></td></tr>
            <tr rowindex="2"><td>功能</td><td><input name="q5_2_1" /></td><td><input name="q5_2_2" /></td></tr>
          </table>
        </div>
        <div topic="6" id="div6" type="1" gapfill="1">
          <div class="topichtml">6. 联系方式</div>
          姓名：<input type="text" />
          电话：<input type="text" />
        </div>
      </fieldset>
    </div>
  </body>
</html>`
}
