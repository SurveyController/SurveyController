from __future__ import annotations

from wjx.provider.html_parser import parse_survey_questions_from_html


class WjxHtmlParserTests:
    def test_parse_survey_questions_from_html_returns_empty_when_container_missing(self) -> None:
        assert parse_survey_questions_from_html("<html><body><div>无题目</div></body></html>") == []

    def test_parse_survey_questions_from_html_extracts_basic_question_metadata(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="1" id="div1" type="3">
                  <div class="topichtml">1. 本题检测，请选择 非常满意</div>
                  <div class="ui-controlgroup">
                    <div><span class="label">一般</span></div>
                    <div><span class="label">非常满意</span></div>
                  </div>
                </div>
                <div topic="2" id="div2" type="4" relation="1,2">
                  <div class="topichtml">2. 请选择你常用的功能 [至少选1项，最多选2项]</div>
                  <div class="ui-controlgroup">
                    <div><span class="label">功能A</span></div>
                    <div><span class="label">功能B</span></div>
                  </div>
                  <input type="checkbox" jumpto="5" />
                  <input type="checkbox" />
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        assert len(questions) == 2

        first = questions[0]
        assert first["num"] == 1
        assert first["display_num"] == 1
        assert first["title"] == "本题检测，请选择 非常满意"
        assert first["type_code"] == "3"
        assert first["options"] == 2
        assert first["option_texts"] == ["一般", "非常满意"]
        assert first["forced_option_index"] == 1
        assert first["forced_option_text"] == "非常满意"
        assert first["page"] == 1

        second = questions[1]
        assert second["num"] == 2
        assert second["display_num"] == 2
        assert second["type_code"] == "4"
        assert second["multi_min_limit"] == 1
        assert second["multi_max_limit"] == 2
        assert second["has_jump"]
        assert second["jump_rules"] == [{"option_index": 0, "jumpto": 5, "option_text": "功能A"}]
        assert second["has_display_condition"]
        assert second["display_conditions"] == [
            {
                "condition_question_num": 1,
                "condition_mode": "selected",
                "condition_option_indices": [1],
                "raw_relation": "1,2",
            }
        ]

    def test_parse_survey_questions_from_html_extracts_matrix_and_slider_metadata(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="3" id="div3" type="6">
                  <div class="topichtml">3. 请评价以下项目</div>
                  <table id="divRefTab3">
                    <tr id="drv3_1"><td></td><td>差</td><td>好</td></tr>
                    <tr rowindex="1"><td>外观</td><td><input name="q3_1_1" type="radio" /></td><td><input name="q3_1_2" type="radio" /></td></tr>
                    <tr rowindex="2"><td>功能</td><td><input name="q3_2_1" type="radio" /></td><td><input name="q3_2_2" type="radio" /></td></tr>
                  </table>
                </div>
                <div topic="4" id="div4" type="8">
                  <div class="topichtml">4. 请拖动滑块</div>
                  <input id="q4" type="range" min="1" max="5" step="0.5" />
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        matrix = questions[0]
        assert matrix["num"] == 3
        assert matrix["rows"] == 2
        assert matrix["row_texts"] == ["外观", "功能"]
        assert matrix["option_texts"] == ["差", "好"]
        assert matrix["options"] == 2

        slider = questions[1]
        assert slider["num"] == 4
        assert slider["type_code"] == "8"
        assert slider["options"] == 1
        assert slider["slider_min"] == 1.0
        assert slider["slider_max"] == 5.0
        assert slider["slider_step"] == 0.5

    def test_parse_survey_questions_from_html_marks_description_and_multi_text_cases(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="5" id="div5" type="3">
                  <div class="topichtml">5. 请阅读以下说明</div>
                  <p>这里没有任何选项控件</p>
                </div>
                <div topic="6" id="div6" type="1" gapfill="1">
                  <div class="topichtml">6. 请填写你的信息</div>
                  姓名：<input type="text" />
                  电话：<input type="text" />
                </div>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        description = questions[0]
        assert description["is_description"]
        assert description["options"] == 0

        multi_text = questions[1]
        assert multi_text["text_inputs"] == 2
        assert multi_text["text_input_labels"] == ["姓名", "电话"]
        assert multi_text["is_multi_text"]
        assert multi_text["is_text_like"]

    def test_parse_survey_questions_from_html_falls_back_to_nested_topic_divs_and_slider_matrix(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <section>
                  <div topic="9" id="div9" type="2">
                    <div class="topichtml">9. 位置题</div>
                    <input verify="腾讯地图定位" />
                  </div>
                  <div topic="10" id="div10" type="6">
                    <div class="topichtml">10. 滑块矩阵</div>
                    <tr class="rowtitletr"><td class="title"><span class="itemTitleSpan">体验</span></td></tr>
                    <tr class="rowtitletr"><td class="title"><span class="itemTitleSpan">价格</span></td></tr>
                    <div class="ruler"><span class="cm" data-value="1"></span><span class="cm" data-value="5"></span></div>
                    <input class="ui-slider-input" rowid="1" min="1" max="5" step="1" />
                    <input class="ui-slider-input" rowid="2" min="1" max="5" step="1" />
                    <div class="rangeslider"></div>
                    <div class="rangeslider"></div>
                  </div>
                </section>
              </fieldset>
            </div>
          </body>
        </html>
        """

        questions = parse_survey_questions_from_html(html)

        location = questions[0]
        assert location["is_location"]
        assert location["type_code"] == "2"
        assert location["text_inputs"] == 0

        slider_matrix = questions[1]
        assert slider_matrix["is_slider_matrix"]
        assert slider_matrix["slider_min"] == 1.0
        assert slider_matrix["slider_max"] == 5.0
        assert slider_matrix["slider_step"] == 1.0
