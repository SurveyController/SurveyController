from __future__ import annotations
from software.io.markdown.utils import strip_markdown

class MarkdownUtilsTests:

    def test_strip_markdown_returns_default_text_for_empty_value(self) -> None:
        assert strip_markdown('') == '暂无更新说明'

    def test_strip_markdown_removes_images_and_keeps_regular_link_text(self) -> None:
        text = '![截图](https://example.com/a.png)\n[文档](https://example.com)\n正文'
        assert strip_markdown(text) == '[文档](https://example.com)\n正文'

    def test_strip_markdown_unwraps_anchor_only_links(self) -> None:
        text = '[目录](#toc)\n<a href="#change">更新内容</a>'
        assert strip_markdown(text) == '目录\n更新内容'

    def test_strip_markdown_removes_html_images_dividers_strike_and_underline(self) -> None:
        text = "<img src='x.png'>\n---\n~~删除线~~\n__下划线__"
        assert strip_markdown(text) == '删除线\n下划线'

    def test_strip_markdown_collapses_excess_blank_lines(self) -> None:
        assert strip_markdown('第一行\n\n\n\n第二行') == '第一行\n\n第二行'
