from __future__ import annotations

from bs4 import BeautifulSoup

from wjx.provider import html_parser_matrix


class WjxHtmlParserMatrixTests:
    def test_postprocess_matrix_option_texts_deduplicates_and_normalizes(self) -> None:
        assert html_parser_matrix._postprocess_matrix_option_texts(["  好  ", "", "好", "一般"]) == ["好", "一般"]

    def test_collect_matrix_option_texts_prefers_table_rowindex_and_header(self) -> None:
        html = """
        <div id="div3">
          <table id="divRefTab3">
            <tr id="drv3_1"><td></td><td>差</td><td>好</td></tr>
            <tr rowindex="1"><td>外观</td><td></td><td></td></tr>
            <tr rowindex="2"><td data-title="功能"></td><td></td><td></td></tr>
          </table>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        question_div = soup.find(id="div3")

        rows, options, row_texts = html_parser_matrix._collect_matrix_option_texts(soup, question_div, 3)

        assert rows == 2
        assert options == ["差", "好"]
        assert row_texts == ["外观", "功能"]

    def test_collect_matrix_option_texts_can_fall_back_to_input_names_and_item_titles(self) -> None:
        html = """
        <div id="div5">
          <span class="itemTitleSpan">行一</span>
          <span class="itemTitleSpan">行二</span>
          <input name="q5_1_1" />
          <input name="q5_1_2" />
          <input name="q5_2_1" />
          <input name="q5_2_2" />
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        question_div = soup.find(id="div5")

        rows, options, row_texts = html_parser_matrix._collect_matrix_option_texts(soup, question_div, 5)

        assert rows == 2
        assert options == ["1", "2"]
        assert row_texts == ["行一", "行二"]

    def test_slider_helpers_extract_range_and_matrix_metadata(self) -> None:
        html = """
        <div id="div8">
          <input id="q8" type="range" min="1" max="5" step="0.5" />
          <table>
            <tr class="rowtitletr"><td class="title">满意度</td></tr>
          </table>
          <div class="ruler"><span class="cm" data-value="1"></span><span class="cm" data-value="5"></span></div>
          <input class="ui-slider-input" rowid="1" min="1" max="5" step="2" />
          <div class="rangeslider"></div>
          <input class="ui-slider-input" rowid="2" min="1" max="5" step="2" />
          <div class="rangeslider"></div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        question_div = soup.find(id="div8")

        assert html_parser_matrix._extract_slider_range(question_div, 8) == (1.0, 5.0, 0.5)
        assert html_parser_matrix._question_div_looks_like_slider_matrix(question_div)
        assert html_parser_matrix._format_slider_matrix_value(3.0) == "3"
        assert html_parser_matrix._format_slider_matrix_value(3.5) == "3.5"
        assert html_parser_matrix._build_slider_matrix_option_texts_from_input(question_div.select("input.ui-slider-input")[0]) == ["1", "3", "5"]

        rows, options, row_texts = html_parser_matrix._collect_slider_matrix_metadata(question_div)
        assert rows == 2
        assert options == ["1", "5"]
        assert row_texts == ["满意度"]
