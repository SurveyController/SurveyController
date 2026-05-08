from __future__ import annotations

from bs4 import BeautifulSoup

from software.core.engine import dom_helpers
from wjx.provider import html_parser_choice
from wjx.provider import html_parser_common
from wjx.provider import html_parser_matrix
from wjx.provider import html_parser_rules


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class _FakeDriverAnchor:
    def __init__(self, attrs: dict[str, str]) -> None:
        self.text = ""
        self._attrs = dict(attrs)

    def get_attribute(self, name: str) -> str:
        return self._attrs.get(name, "")


class _FakeDriverQuestionDiv:
    def __init__(self, selector_map: dict[str, list[object]]) -> None:
        self._selector_map = dict(selector_map)

    def find_elements(self, _by, selector: str) -> list[object]:
        return list(self._selector_map.get(selector, []))


class WjxHtmlParserHelperTests:
    def test_extract_survey_title_from_html_strips_wjx_suffix(self) -> None:
        html = """
        <html>
          <head><title>备用标题 - 问卷星</title></head>
          <body><div id="divTitle"><h1>正式标题 - 问卷星</h1></div></body>
        </html>
        """
        assert html_parser_common.extract_survey_title_from_html(html) == "正式标题"

    def test_extract_question_number_and_cleanup_helpers(self) -> None:
        soup = _soup("<div id='div12' topic='12'></div>")
        assert html_parser_common._extract_question_number_from_div(soup.div) == 12
        assert html_parser_common._cleanup_question_title(" 1. 【单选题】 题目标题 ") == "题目标题"
        assert html_parser_common._extract_display_question_number("* 18. 题目") == 18

    def test_extract_display_heading_text_includes_split_topic_number(self) -> None:
        soup = _soup(
            """
            <div id="div23" topic="23" type="2">
              <div class="field-label">
                <span class="req">*</span>
                <div class="topicnumber">22.</div>
                <div class="topichtml">请评价培训和实习</div>
              </div>
            </div>
            """
        )
        heading = html_parser_common._extract_display_heading_text(soup.div)
        assert heading == "22. 请评价培训和实习"
        assert html_parser_common._extract_display_question_number(heading) == 22

    def test_count_text_inputs_and_extract_labels_from_mixed_nodes(self) -> None:
        soup = _soup(
            """
            <div>
              <input type="text" placeholder="姓名" />
              性别：<input type="text" />
              <textarea aria-label="备注"></textarea>
              <div contenteditable="true"></div>
              <input type="hidden" />
              <input type="text" /><span class="textedit"></span>
            </div>
            """
        )
        assert html_parser_common._count_text_inputs_in_soup(soup.div) == 5
        assert html_parser_common._extract_text_input_labels(soup.div) == ["姓名", "性别", "备注", "填空4", "填空5"]

    def test_description_reorder_scale_and_rating_detection(self) -> None:
        description_div = _soup("<div><div class='topichtml'>说明</div></div>").div
        reorder_div = _soup("<div><ul><li>A</li><li>B</li></ul><div class='ui-sortable'></div></div>").div
        scale_div = _soup(
            """
            <div>
              <div class="scaleTitle"></div>
              <ul tp="d">
                <li><a>1</a></li><li><a>2</a></li><li><a>3</a></li><li><a>4</a></li><li><a>5</a></li>
                <li><a>6</a></li><li><a>7</a></li><li><a>8</a></li><li><a>9</a></li><li><a>10</a></li>
              </ul>
            </div>
            """
        ).div
        rating_div = _soup("<div><div class='evaluateTagWrap'></div><a class='rate-off'>星</a></div>").div
        rating_count_div = _soup("<div><ul class='modlen5'><li></li></ul></div>").div

        assert html_parser_common._soup_question_looks_like_description(description_div, "3")
        assert not html_parser_common._soup_question_looks_like_description(_soup("<div><input type='radio'/></div>").div, "3")
        assert html_parser_common._soup_question_looks_like_reorder(reorder_div)
        assert html_parser_common._soup_question_looks_like_numeric_scale(scale_div)
        assert not html_parser_common._soup_question_looks_like_rating(scale_div)
        assert html_parser_common._soup_question_looks_like_rating(rating_div)
        assert html_parser_common._extract_rating_option_count(rating_count_div) == 5

    def test_dval_scale_with_blank_rate_icons_is_not_rating(self) -> None:
        scale_div = _soup(
            """
            <div>
              <div class="scaleTitle_frist">很不同意</div>
              <div class="scaleTitle_last">很同意</div>
              <ul tp="d">
                <li><a class="rate-off" dval="1"></a></li>
                <li><a class="rate-off" dval="2"></a></li>
                <li><a class="rate-off" dval="3"></a></li>
                <li><a class="rate-off" dval="4"></a></li>
                <li><a class="rate-off" dval="5"></a></li>
              </ul>
            </div>
            """
        ).div

        assert html_parser_common._soup_question_looks_like_numeric_scale(scale_div)
        assert not html_parser_common._soup_question_looks_like_rating(scale_div)

    def test_driver_dval_scale_with_blank_rate_icons_is_not_rating(self) -> None:
        anchors = [_FakeDriverAnchor({"dval": str(index)}) for index in range(1, 6)]
        question_div = _FakeDriverQuestionDiv(
            {
                "ul[tp='d'] li a, .scale-rating ul li a, .scale-rating a[val]": anchors,
                ".scaleTitle, .scaleTitle_frist, .scaleTitle_last, .scaleTitleFirst, .scaleTitleLast": [object()],
                "a.rate-off, a.rate-on, .rate-off, .rate-on": anchors,
            }
        )

        assert dom_helpers._driver_question_looks_like_numeric_scale(question_div)
        assert not dom_helpers._driver_question_looks_like_rating(question_div)

    def test_should_mark_as_multi_text_respects_type_and_flags(self) -> None:
        assert html_parser_common._should_mark_as_multi_text("1", 0, 2, False)
        assert html_parser_common._should_mark_as_multi_text("9", 0, 1, False, has_gapfill=True)
        assert not html_parser_common._should_mark_as_multi_text("3", 4, 2, False)
        assert not html_parser_common._should_mark_as_multi_text("1", 0, 2, True)
        assert not html_parser_common._should_mark_as_multi_text("1", 0, 2, False, has_slider_matrix=True)

    def test_force_select_detection_supports_text_label_and_index(self) -> None:
        text_div = _soup("<div><div class='topichtml'>本题检测，请选择 非常满意。</div></div>").div
        label_div = _soup("<div><div class='topichtml'>请务必选A项</div></div>").div
        index_div = _soup("<div><div class='topichtml'>请直接选第2项</div></div>").div

        assert html_parser_choice._extract_force_select_option(text_div, "本题检测，请选择 非常满意。", ["非常不满意", "非常满意"]) == (1, "非常满意")
        assert html_parser_choice._extract_force_select_option(label_div, "请务必选A项", ["(A) 苹果", "(B) 香蕉"]) == (0, "(A) 苹果")
        assert html_parser_choice._extract_force_select_option(index_div, "请直接选第2项", ["甲", "乙", "丙"]) == (1, "乙")

    def test_choice_option_and_attached_select_parsing_marks_fillable_options(self) -> None:
        question_div = _soup(
            """
            <div>
              <div class="ui-controlgroup">
                <div>
                  <span class="label">选项A</span>
                </div>
                <div>
                  <span class="label">其他</span>
                  <input type="text" />
                  <select>
                    <option value="">请选择</option>
                    <option>红色</option>
                    <option>蓝色</option>
                  </select>
                </div>
              </div>
            </div>
            """
        ).div

        texts, fillable_indices = html_parser_choice._collect_choice_option_texts(question_div)
        attached = html_parser_choice._extract_choice_attached_selects(question_div)

        assert texts == ["选项A", "其他"]
        assert fillable_indices == [1]
        assert attached == [
            {
                "option_index": 1,
                "option_text": "其他",
                "select_options": ["红色", "蓝色"],
                "select_option_count": 2,
            }
        ]

    def test_custom_select_and_location_helpers(self) -> None:
        custom_input = _soup("<input custom='请选择, 苹果,香蕉, 苹果' />").input
        location_div = _soup("<div><input verify='地图定位' /></div>").div
        soup = _soup(
            """
            <div>
              <div topic="7">
                <select id="q7">
                  <option value="">请选择</option>
                  <option value="1">北京</option>
                  <option value="2">上海</option>
                </select>
              </div>
            </div>
            """
        )

        assert html_parser_choice._extract_custom_select_option_texts(custom_input) == ["苹果", "香蕉"]
        assert html_parser_choice._verify_text_indicates_location("腾讯地图")
        assert html_parser_choice._soup_question_is_location(location_div)
        assert html_parser_choice._collect_select_option_texts(soup.div, soup, 7) == ["北京", "上海"]

    def test_question_title_limits_jump_and_display_rules(self) -> None:
        question_div = _soup(
            """
            <div relation="1,1|1,1|3,1,2">
              <div class="topichtml">2. 请选择你喜欢的项目 [至少选2项，最多选4项]</div>
              <input type="checkbox" jumpto="5" />
              <input type="checkbox" />
            </div>
            """
        ).div

        assert html_parser_rules._extract_question_title(question_div, 2) == "请选择你喜欢的项目 [至少选2项，最多选4项]"
        assert html_parser_rules._extract_multiple_choice_limits(question_div, 2) == (2, 4)
        assert html_parser_rules._extract_jump_rules_from_html(question_div, 2, ["A", "B"]) == (
            True,
            [{"option_index": 0, "jumpto": 5, "option_text": "A"}],
        )
        assert html_parser_rules._extract_display_conditions_from_html(question_div, 2) == (
            True,
            [
                {
                    "condition_question_num": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [0],
                    "raw_relation": "1,1",
                },
                {
                    "condition_question_num": 3,
                    "condition_mode": "selected",
                    "condition_option_indices": [0, 1],
                    "raw_relation": "3,1,2",
                },
            ],
        )

    def test_attach_display_condition_metadata_marks_source_question(self) -> None:
        questions = [
            {"num": 1, "title": "Q1"},
            {
                "num": 5,
                "title": "Q5",
                "display_conditions": [
                    {"condition_question_num": 1, "condition_option_indices": [2, 0], "condition_mode": "selected"},
                ],
            },
            {"num": 6, "title": "Q6"},
        ]

        html_parser_rules._attach_display_condition_metadata(questions)

        assert questions[0]["controls_display_targets"] == [
            {"target_question_num": 5, "condition_option_indices": [2, 0], "condition_mode": "selected"}
        ]
        assert questions[0]["has_dependent_display_logic"]
        assert questions[1]["controls_display_targets"] == []
        assert not questions[1]["has_dependent_display_logic"]

    def test_matrix_and_slider_helpers_parse_rows_columns_and_ranges(self) -> None:
        soup = _soup(
            """
            <div>
              <div id="div3">
                <table id="divRefTab3">
                  <tr id="drv3_1"><td></td><td>很差</td><td>很好</td></tr>
                  <tr rowindex="1"><td>服务</td><td><input name="q3_1_1" /></td><td><input name="q3_1_2" /></td></tr>
                  <tr rowindex="2"><td>质量</td><td><input name="q3_2_1" /></td><td><input name="q3_2_2" /></td></tr>
                </table>
              </div>
            </div>
            """
        )
        matrix_div = soup.find(id="div3")
        slider_div = _soup(
            """
            <div>
              <tr class="rowtitletr"><td class="title"><span class="itemTitleSpan">体验</span></td></tr>
              <tr class="rowtitletr"><td class="title"><span class="itemTitleSpan">价格</span></td></tr>
              <div class="ruler"><span class="cm" data-value="1"></span><span class="cm" data-value="2"></span></div>
              <input class="ui-slider-input" rowid="1" min="1" max="2" step="1" />
              <input class="ui-slider-input" rowid="2" min="1" max="2" step="1" />
              <div class="rangeslider"></div>
              <div class="rangeslider"></div>
            </div>
            """
        ).div

        rows, option_texts, row_texts = html_parser_matrix._collect_matrix_option_texts(soup, matrix_div, 3)
        slider_rows, slider_options, slider_titles = html_parser_matrix._collect_slider_matrix_metadata(slider_div)

        assert html_parser_matrix._postprocess_matrix_option_texts([" 很差 ", "很好", "很好"]) == ["很差", "很好"]
        assert (rows, option_texts, row_texts) == (2, ["很差", "很好"], ["服务", "质量"])
        assert html_parser_matrix._extract_slider_range(_soup("<div><input id='q8' min='1' max='5' step='0.5' /></div>").div, 8) == (1.0, 5.0, 0.5)
        assert html_parser_matrix._question_div_looks_like_slider_matrix(slider_div)
        assert html_parser_matrix._format_slider_matrix_value(2.0) == "2"
        assert html_parser_matrix._build_slider_matrix_option_texts_from_input(slider_div.find("input")) == ["1", "2"]
        assert (slider_rows, slider_options, slider_titles) == (2, ["1", "2"], ["体验", "价格"])
