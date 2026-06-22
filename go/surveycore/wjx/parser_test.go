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
