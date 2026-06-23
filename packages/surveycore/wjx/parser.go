package wjx

import (
	"context"
	"sort"
	"strconv"
	"strings"

	nethtml "golang.org/x/net/html"
	"surveycontroller/surveycore/internal/model"
)

func (p Parser) Parse(ctx context.Context, surveyURL string) (model.SurveyDefinition, error) {
	htmlText, err := p.getHTML(ctx, surveyURL)
	if err != nil {
		return model.SurveyDefinition{}, err
	}
	definition, err := ParseDefinitionFromHTML(htmlText)
	if err != nil {
		return model.SurveyDefinition{}, err
	}
	if len(definition.Questions) == 0 {
		return model.SurveyDefinition{}, ParseError{Message: "问卷星 HTTP 页面未返回可解析题目"}
	}
	return definition, nil
}

func ParseDefinitionFromHTML(htmlText string) (model.SurveyDefinition, error) {
	if err := pageStateError(htmlText); err != nil {
		return model.SurveyDefinition{}, err
	}
	root, err := parseHTML(htmlText)
	if err != nil {
		return model.SurveyDefinition{}, err
	}
	container := findFirst(root, func(node *nethtml.Node) bool {
		return isElement(node, "div") && attr(node, "id") == "divQuestion"
	})
	if container == nil {
		return model.SurveyDefinition{}, nil
	}
	fieldsets := findAll(container, func(node *nethtml.Node) bool {
		return isElement(node, "fieldset")
	})
	if len(fieldsets) == 0 {
		fieldsets = []*nethtml.Node{container}
	}
	questions := make([]model.QuestionMeta, 0)
	for pageIndex, fieldset := range fieldsets {
		visible := 0
		for _, questionDiv := range directQuestionDivs(fieldset) {
			question := normalizeQuestion(questionDiv, pageIndex+1)
			if !isHidden(questionDiv) {
				visible++
				if question.Num != visible {
					question.Page = pageIndex + 1
				}
				display := visible
				question.DisplayNum = &display
			}
			questions = append(questions, question)
		}
	}
	sort.SliceStable(questions, func(i int, j int) bool {
		if questions[i].Page == questions[j].Page {
			return questions[i].Num < questions[j].Num
		}
		return questions[i].Page < questions[j].Page
	})
	return model.SurveyDefinition{
		Provider:  model.ProviderWJX,
		Title:     surveyTitle(root),
		Questions: questions,
	}, nil
}

func directQuestionDivs(root *nethtml.Node) []*nethtml.Node {
	candidates := findAll(root, func(node *nethtml.Node) bool {
		return isElement(node, "div") && hasAttr(node, "topic")
	})
	result := make([]*nethtml.Node, 0, len(candidates))
	for _, candidate := range candidates {
		hasQuestionAncestor := false
		for parent := candidate.Parent; parent != nil && parent != root; parent = parent.Parent {
			if isElement(parent, "div") && hasAttr(parent, "topic") {
				hasQuestionAncestor = true
				break
			}
		}
		if !hasQuestionAncestor {
			result = append(result, candidate)
		}
	}
	return result
}

func normalizeQuestion(div *nethtml.Node, page int) model.QuestionMeta {
	num := questionNumber(div)
	typeCode := strings.TrimSpace(attr(div, "type"))
	if typeCode == "" {
		typeCode = "0"
	}
	if typeCode != "11" && looksLikeOrder(div) {
		typeCode = "11"
	}
	title := questionTitle(div, num)
	optionTexts, rowTexts, fillable := questionOptions(div, num, typeCode)
	textInputs := 0
	switch typeCode {
	case "1", "2", "9":
		textInputs = countTextInputs(div)
	}
	isLocation := isLocationQuestion(div) && (typeCode == "1" || typeCode == "2")
	if isLocation {
		textInputs = 0
	}
	isDescription := looksLikeDescription(div, typeCode)
	isSliderMatrix := typeCode != "8" && looksLikeSliderMatrix(div)
	if isSliderMatrix {
		typeCode = "6"
	}
	if typeCode == "8" && len(optionTexts) == 0 {
		optionTexts = []string{"50"}
	}
	rating := typeCode == "5" && looksLikeRating(div)
	if typeCode == "5" && len(optionTexts) == 0 {
		optionTexts = ratingTexts(div)
	}
	if typeCode == "11" && len(optionTexts) == 0 {
		optionTexts, _ = choiceTexts(div)
	}
	multiMin, multiMax := multiLimits(div, typeCode)
	forcedIdx, forcedText := forceSelectOption(title, optionTexts)
	providerType := providerType(typeCode, textInputs, len(optionTexts), isSliderMatrix)
	textLabels := textInputLabels(div)
	attachedSelects := attachedOptionSelects(div, optionTexts)
	sliderMin, sliderMax, sliderStep := sliderRange(div)
	hasJump, jumpRules, hasDisplay, displayConditions, hasDependentDisplay, controlsDisplayTargets, logicStatus := logicMetadata(div, num, optionTexts)
	if isDescription {
		typeCode = "0"
		providerType = "description"
	}
	return model.QuestionMeta{
		Num:                      num,
		Title:                    title,
		Description:              "",
		TypeCode:                 typeCode,
		Options:                  len(optionTexts),
		Rows:                     maxInt(1, len(rowTexts)),
		RowTexts:                 rowTexts,
		Page:                     page,
		OptionTexts:              optionTexts,
		Provider:                 model.ProviderWJX,
		ProviderID:               strconv.Itoa(num),
		ProviderPageID:           strconv.Itoa(page),
		ProviderType:             providerType,
		Required:                 required(div),
		IsDescription:            isDescription,
		IsLocation:               isLocation,
		IsRating:                 rating,
		RatingMax:                ratingMax(rating, len(optionTexts)),
		TextInputs:               textInputs,
		TextInputLabels:          textLabels,
		IsTextLike:               isTextLike(typeCode, textInputs, len(optionTexts), isLocation),
		IsMultiText:              textInputs > 1,
		IsSliderMatrix:           isSliderMatrix,
		LogicStatus:              logicStatus,
		HasJump:                  hasJump,
		JumpRules:                jumpRules,
		HasDisplayCondition:      hasDisplay,
		DisplayConditions:        displayConditions,
		HasDependentDisplayLogic: hasDependentDisplay,
		ControlsDisplayTargets:   controlsDisplayTargets,
		QuestionMedia:            questionMedia(div, rowTexts, optionTexts),
		SliderMin:                sliderMin,
		SliderMax:                sliderMax,
		SliderStep:               sliderStep,
		MultiMinLimit:            multiMin,
		MultiMaxLimit:            multiMax,
		ForcedOptionIdx:          forcedIdx,
		ForcedOption:             forcedText,
		ForcedTexts:              []string{},
		FillableOptions:          fillable,
		AttachedOptionSelects:    attachedSelects,
		HasAttachedOptionSelect:  len(attachedSelects) > 0,
	}
}
