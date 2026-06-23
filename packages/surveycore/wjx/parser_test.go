package wjx

import (
	"context"
	"testing"
)

func TestParseDefinitionFromHTML(t *testing.T) {
	definition, err := ParseDefinitionFromHTML(sampleHTML())
	if err != nil {
		t.Fatal(err)
	}
	if definition.Provider != "wjx" || definition.Title != "消费测试" {
		t.Fatalf("definition = %#v", definition)
	}
	if len(definition.Questions) != 6 {
		t.Fatalf("question count = %d", len(definition.Questions))
	}
	first := definition.Questions[0]
	if first.ProviderType != "single" || first.TypeCode != "3" || first.Options != 2 || first.ForcedOptionIdx == nil || *first.ForcedOptionIdx != 1 {
		t.Fatalf("first = %#v", first)
	}
	multiple := definition.Questions[1]
	if multiple.ProviderType != "multiple" || multiple.MultiMinLimit == nil || *multiple.MultiMinLimit != 1 || multiple.MultiMaxLimit == nil || *multiple.MultiMaxLimit != 2 {
		t.Fatalf("multiple = %#v", multiple)
	}
	matrix := definition.Questions[4]
	if matrix.ProviderType != "matrix" || matrix.Rows != 2 || matrix.Options != 2 || len(matrix.RowTexts) != 2 {
		t.Fatalf("matrix = %#v", matrix)
	}
	text := definition.Questions[5]
	if text.ProviderType != "multi_text" || text.TextInputs != 2 {
		t.Fatalf("text = %#v", text)
	}
}

func TestParserRejectsPausedPage(t *testing.T) {
	_, err := ParseDefinitionFromHTML("<html><body>问卷已暂停，不能填写</body></html>")
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestParseDefinitionMetadataFields(t *testing.T) {
	definition, err := ParseDefinitionFromHTML(`
<html><head><title>元数据 - 问卷星</title></head><body>
<div id="divQuestion"><fieldset>
  <div topic="1" id="div1" type="3">
    <div class="topichtml">1. 单选<img src="//cdn.test/title.png"></div>
    <div class="ui-controlgroup">
      <div jumpto="3"><span class="label">A</span><select><option>请选择</option><option>北京</option></select></div>
      <div><span class="label">B</span></div>
    </div>
  </div>
  <div topic="2" id="div2" type="1" style="display:none" relation="1">
    <div class="topichtml">2. 填空</div><input type="text" placeholder="姓名" /><input type="text" />
  </div>
  <div topic="3" id="div3" type="5">
    <div class="topichtml">3. 滑块</div><input type="range" min="2" max="8" step="2" />
  </div>
</fieldset></div></body></html>`)
	if err != nil {
		t.Fatal(err)
	}
	if len(definition.Questions) != 3 {
		t.Fatalf("question count = %d", len(definition.Questions))
	}
	first := definition.Questions[0]
	if first.DisplayNum == nil || *first.DisplayNum != 1 || !first.HasJump || len(first.JumpRules) != 1 || len(first.QuestionMedia) != 1 {
		t.Fatalf("first = %#v", first)
	}
	if !first.HasAttachedOptionSelect || len(first.AttachedOptionSelects) != 1 || first.AttachedOptionSelects[0]["option_index"] != 0 {
		t.Fatalf("attached selects = %#v", first.AttachedOptionSelects)
	}
	second := definition.Questions[1]
	if !second.HasDisplayCondition || len(second.TextInputLabels) != 2 || second.TextInputLabels[1] != "填空2" {
		t.Fatalf("second = %#v", second)
	}
	third := definition.Questions[2]
	if third.SliderMin != "2" || third.SliderMax != "8" || third.SliderStep != "2" {
		t.Fatalf("third = %#v", third)
	}
}

func TestParserFetchesHTML(t *testing.T) {
	server := newWJXTestServer(t, true)
	defer server.Close()
	parser := Parser{Client: rewriteWJXClient(server.URL)}

	definition, err := parser.Parse(context.Background(), "https://www.wjx.cn/vm/demo.aspx")
	if err != nil {
		t.Fatal(err)
	}
	if definition.Title != "消费测试" || len(definition.Questions) == 0 {
		t.Fatalf("definition = %#v", definition)
	}
}
