"""html2text: Turn HTML into equivalent Markdown-structured text."""

import html.entities
import html.parser
import re
import urllib.parse as urlparse
from textwrap import wrap
from typing import Dict, List, Optional, Tuple, Union

from core.builtins.message.internal import Url
from . import config
from .elements import AnchorElement, ListElement
from .typing import OutCallback
from .utils import (
    dumb_css_parser,
    element_style,
    escape_md,
    escape_md_section,
    google_fixed_width_font,
    google_has_height,
    google_list_style,
    google_text_emphasis,
    hn,
    list_numbering_start,
    pad_tables_in_text,
    skipwrap,
    unifiable_n,
)

__version__ = (2020, 1, 16)


# TODO:
# Support decoded entities with UNIFIABLE.


class HTML2Text(html.parser.HTMLParser):
    def __init__(
        self,
        out: Optional[OutCallback] = None,
        baseurl: str = "",
        bodywidth: int = config.BODY_WIDTH,
    ) -> None:
        """
        Input parameters:
            out: possible custom replacement for self.outtextf (which
                 appends lines of text).
            baseurl: base URL of the document we process
        """
        super().__init__(convert_charrefs=False)

        # Config options
        self.split_next_td = False
        self.td_count = 0
        self.table_start = False
        self.unicode_snob = config.UNICODE_SNOB  # covered in cli
        self.escape_snob = config.ESCAPE_SNOB  # covered in cli
        self.links_each_paragraph = config.LINKS_EACH_PARAGRAPH
        self.body_width = bodywidth  # covered in cli
        self.skip_internal_links = config.SKIP_INTERNAL_LINKS  # covered in cli
        self.inline_links = config.INLINE_LINKS  # covered in cli
        self.protect_links = config.PROTECT_LINKS  # covered in cli
        self.google_list_indent = config.GOOGLE_LIST_INDENT  # covered in cli
        self.ignore_links = config.IGNORE_ANCHORS  # covered in cli
        self.ignore_images = config.IGNORE_IMAGES  # covered in cli
        self.images_as_html = config.IMAGES_AS_HTML  # covered in cli
        self.images_to_alt = config.IMAGES_TO_ALT  # covered in cli
        self.images_with_size = config.IMAGES_WITH_SIZE  # covered in cli
        self.ignore_emphasis = config.IGNORE_EMPHASIS  # covered in cli
        self.bypass_tables = config.BYPASS_TABLES  # covered in cli
        self.ignore_tables = config.IGNORE_TABLES  # covered in cli
        self.google_doc = False  # covered in cli
        self.ul_item_mark = "*"  # covered in cli
        self.emphasis_mark = "_"  # covered in cli
        self.strong_mark = "**"
        self.single_line_break = config.SINGLE_LINE_BREAK  # covered in cli
        self.use_automatic_links = config.USE_AUTOMATIC_LINKS  # covered in cli
        self.hide_strikethrough = False  # covered in cli
        self.mark_code = config.MARK_CODE
        self.wrap_list_items = config.WRAP_LIST_ITEMS  # covered in cli
        self.wrap_links = config.WRAP_LINKS  # covered in cli
        self.pad_tables = config.PAD_TABLES  # covered in cli
        self.default_image_alt = config.DEFAULT_IMAGE_ALT  # covered in cli
        self.tag_callback = None
        self.open_quote = config.OPEN_QUOTE  # covered in cli
        self.close_quote = config.CLOSE_QUOTE  # covered in cli

        if out is None:
            self.out = self.outtextf
        else:
            self.out = out

        # empty list to store output characters before they are "joined"
        self.outtextlist = []  # type: List[str]

        self.quiet = 0
        self.p_p = 0  # number of newline character to print before next output
        self.outcount = 0
        self.start = True
        self.space = False
        self.a = []  # type: List[AnchorElement]
        self.astack = []  # type: List[Optional[Dict[str, Optional[str]]]]
        self.maybe_automatic_link = None  # type: Optional[str]
        self.empty_link = False
        self.absolute_url_matcher = re.compile(r"^[a-zA-Z+]+://")
        self.acount = 0
        self.list = []  # type: List[ListElement]
        self.blockquote = 0
        self.pre = False
        self.startpre = False
        self.code = False
        self.quote = False
        self.br_toggle = ""
        self.lastWasNL = False
        self.lastWasList = False
        self.style = 0
        self.style_def = {}  # type: Dict[str, Dict[str, str]]
        self.tag_stack = (
            []
        )  # type: List[Tuple[str, Dict[str, Optional[str]], Dict[str, str]]]
        self.emphasis = 0
        self.drop_white_space = 0
        self.inheader = False
        # Current abbreviation definition
        self.abbr_title = None  # type: Optional[str]
        # Last inner HTML (for abbr being defined)
        self.abbr_data = None  # type: Optional[str]
        # Stack of abbreviations to write later
        self.abbr_list = {}  # type: Dict[str, str]
        self.baseurl = baseurl
        self.stressed = False
        self.preceding_stressed = False
        self.preceding_data = ""
        self.current_tag = ""

        config.UNIFIABLE["nbsp"] = "&nbsp_place_holder;"

    def feed(self, data: str) -> None:
        data = data.replace("</script>", "</ignore>")
        super().feed(data)

    def handle(self, data: str) -> str:
        self.feed(data)
        self.feed("")
        markdown = self.optwrap(self.finish())
        if self.pad_tables:
            return pad_tables_in_text(markdown)
        return markdown

    def outtextf(self, s: str) -> None:
        self.outtextlist.append(s)
        if s:
            self.lastWasNL = s[-1] == "\n"

    def finish(self) -> str:
        self.close()

        self.pbr()
        self.o("", force="end")

        outtext = "".join(self.outtextlist)

        if self.unicode_snob:
            nbsp = html.entities.html5["nbsp;"]
        else:
            nbsp = " "
        outtext = outtext.replace("&nbsp_place_holder;", nbsp)

        # Clear self.outtextlist to avoid memory leak of its content to
        # the next handling.
        self.outtextlist = []

        return outtext

    def handle_charref(self, c: str) -> None:
        self.handle_data(self.charref(c), True)

    def handle_entityref(self, c: str) -> None:
        ref = self.entityref(c)

        # ref may be an empty string (e.g. for &lrm;/&rlm; markers that should
        # not contribute to the final output).
        # self.handle_data cannot handle a zero-length string right after a
        # stressed tag or mid-text within a stressed tag (text get split and
        # self.stressed/self.preceding_stressed gets switched after the first
        # part of that text).
        if ref:
            self.handle_data(ref, True)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_tag(tag, dict(attrs), start=True)

    def handle_endtag(self, tag: str) -> None:
        self.handle_tag(tag, {}, start=False)

    def previousIndex(self, attrs: Dict[str, Optional[str]]) -> Optional[int]:
        """
        :type attrs: dict

        :returns: The index of certain set of attributes (of a link) in the
        self.a list. If the set of attributes is not found, returns None
        :rtype: int
        """
        if "href" not in attrs:
            return None

        match = False
        for i, a in enumerate(self.a):
            if "href" in a.attrs and a.attrs["href"] == attrs["href"]:
                if "title" in a.attrs or "title" in attrs:
                    if (
                        "title" in a.attrs
                        and "title" in attrs
                        and a.attrs["title"] == attrs["title"]
                    ):
                        match = True
                else:
                    match = True

            if match:
                return i
        return None

    def handle_emphasis(
        self, start: bool, tag_style: Dict[str, str], parent_style: Dict[str, str]
    ) -> None:
        """
        Handles various text emphases
        """
        tag_emphasis = google_text_emphasis(tag_style)
        parent_emphasis = google_text_emphasis(parent_style)

        # handle Google's text emphasis
        strikethrough = "line-through" in tag_emphasis and self.hide_strikethrough

        # google and others may mark a font's weight as `bold` or `700`
        bold = False
        for bold_marker in config.BOLD_TEXT_STYLE_VALUES:
            bold = bold_marker in tag_emphasis and bold_marker not in parent_emphasis
            if bold:
                break

        italic = "italic" in tag_emphasis and "italic" not in parent_emphasis
        fixed = (
            google_fixed_width_font(tag_style)
            and not google_fixed_width_font(parent_style)
            and not self.pre
        )

        if start:
            # crossed-out text must be handled before other attributes
            # in order not to output qualifiers unnecessarily
            if bold or italic or fixed:
                self.emphasis += 1
            if strikethrough:
                self.quiet += 1
            if italic:
                self.o(self.emphasis_mark)
                self.drop_white_space += 1
            if bold:
                self.o(self.strong_mark)
                self.drop_white_space += 1
            if fixed:
                self.o("`")
                self.drop_white_space += 1
                self.code = True
        else:
            if bold or italic or fixed:
                # there must not be whitespace before closing emphasis mark
                self.emphasis -= 1
                self.space = False
            if fixed:
                if self.drop_white_space:
                    # empty emphasis, drop it
                    self.drop_white_space -= 1
                else:
                    self.o("`")
                self.code = False
            if bold:
                if self.drop_white_space:
                    # empty emphasis, drop it
                    self.drop_white_space -= 1
                else:
                    self.o(self.strong_mark)
            if italic:
                if self.drop_white_space:
                    # empty emphasis, drop it
                    self.drop_white_space -= 1
                else:
                    self.o(self.emphasis_mark)
            # space is only allowed after *all* emphasis marks
            if (bold or italic) and not self.emphasis:
                self.o(" ")
            if strikethrough:
                self.quiet -= 1

    def handle_tag(
        self, tag: str, attrs: Dict[str, Optional[str]], start: bool
    ) -> None:
        self.current_tag = tag

        if self.tag_callback is not None:
            if self.tag_callback(self, tag, attrs, start) is True:
                return

        # first thing inside the anchor tag is another tag
        # that produces some output
        if (
            start
            and self.maybe_automatic_link is not None
            and tag not in ["p", "div", "style", "dl", "dt"]
            and (tag != "img" or self.ignore_images)
        ):
            self.o("[")
            self.maybe_automatic_link = None
            self.empty_link = False

        if self.google_doc:
            # the attrs parameter is empty for a closing tag. in addition, we
            # need the attributes of the parent nodes in order to get a
            # complete style description for the current element. we assume
            # that google docs export well formed html.
            parent_style = {}  # type: Dict[str, str]
            if start:
                if self.tag_stack:
                    parent_style = self.tag_stack[-1][2]
                tag_style = element_style(attrs, self.style_def, parent_style)
                self.tag_stack.append((tag, attrs, tag_style))
            else:
                dummy, attrs, tag_style = (
                    self.tag_stack.pop() if self.tag_stack else (None, {}, {})
                )
                if self.tag_stack:
                    parent_style = self.tag_stack[-1][2]

        if hn(tag):
            self.p()
            if start:
                self.inheader = True
                self.o(hn(tag) * "#" + " ")
            else:
                self.inheader = False
                return  # prevent redundant emphasis marks on headers

        if tag in ["p", "div"]:
            if self.google_doc:
                if start and google_has_height(tag_style):
                    self.p()
                else:
                    self.soft_br()
            elif self.astack and tag == "div":
                pass
            else:
                self.p()

        if tag == "br" and start:
            if self.blockquote > 0:
                self.o("  \n> ")
            else:
                self.o("  \n")

        if tag == "hr" and start:
            self.p()
            self.o("* * *")
            self.p()

        if tag in ["head", "style", "script"]:
            if start:
                self.quiet += 1
            else:
                self.quiet -= 1

        if tag == "style":
            if start:
                self.style += 1
            else:
                self.style -= 1

        if tag in ["body"]:
            self.quiet = 0  # sites like 9rules.com never close <head>

        if tag == "blockquote":
            if start:
                self.p()
                self.o("> ", force=True)
                self.start = True
                self.blockquote += 1
            else:
                self.blockquote -= 1
                self.p()

        def no_preceding_space(self: HTML2Text) -> bool:
            return bool(
                self.preceding_data and re.match(r"[^\s]", self.preceding_data[-1])
            )

        if tag in ["em", "i", "u"] and not self.ignore_emphasis:
            if start and no_preceding_space(self):
                emphasis = " " + self.emphasis_mark
            else:
                emphasis = self.emphasis_mark

            self.o(emphasis)
            if start:
                self.stressed = True

        if tag in ["strong", "b"] and not self.ignore_emphasis:
            if start and no_preceding_space(self):
                strong = " " + self.strong_mark
            else:
                strong = self.strong_mark

            self.o(strong)
            if start:
                self.stressed = True

        if tag in ["del", "strike", "s"]:
            if start and no_preceding_space(self):
                strike = " ~~"
            else:
                strike = "~~"

            self.o(strike)
            if start:
                self.stressed = True

        if self.google_doc:
            if not self.inheader:
                # handle some font attributes, but leave headers clean
                self.handle_emphasis(start, tag_style, parent_style)

        if tag in ["kbd", "code", "tt"] and not self.pre:
            self.o("`")  # TODO: `` `this` ``
            self.code = not self.code

        if tag == "abbr":
            if start:
                self.abbr_title = None
                self.abbr_data = ""
                if "title" in attrs:
                    self.abbr_title = attrs["title"]
            else:
                if self.abbr_title is not None:
                    self.abbr_list[self.abbr_data] = self.abbr_title
                    self.abbr_title = None
                self.abbr_data = None

        if tag == "q":
            if not self.quote:
                self.o(self.open_quote)
            else:
                self.o(self.close_quote)
            self.quote = not self.quote

        def link_url(self: HTML2Text, link: str) -> None:
            url = str(Url(urlparse.urljoin(self.baseurl, link)))
            self.o(f"]({escape_md(url)})")

        if tag == "a" and not self.ignore_links:
            if start:
                if (
                    "href" in attrs
                    and attrs["href"] is not None
                    and not (self.skip_internal_links and attrs["href"].startswith("#"))
                ):
                    self.astack.append(attrs)
                    self.maybe_automatic_link = attrs["href"]
                    self.empty_link = True
                    if self.protect_links:
                        attrs["href"] = "<" + attrs["href"] + ">"
                else:
                    self.astack.append(None)
            else:
                if self.astack:
                    a = self.astack.pop()
                    if self.maybe_automatic_link and not self.empty_link:
                        self.maybe_automatic_link = None
                    elif a:
                        if self.empty_link:
                            self.o("[")
                            self.empty_link = False
                            self.maybe_automatic_link = None
                        if self.inline_links:
                            title = a.get("title") or ""
                            title = escape_md(title)
                            link_url(self, a["href"])
                        else:
                            i = self.previousIndex(a)
                            if i is not None:
                                a_props = self.a[i]
                            else:
                                self.acount += 1
                                a_props = AnchorElement(a, self.acount, self.outcount)
                                self.a.append(a_props)
                            self.o("][" + str(a_props.count) + "]")

        if tag == "img" and start and not self.ignore_images:
            if "src" in attrs:
                if not self.images_to_alt:
                    attrs["href"] = attrs["src"]
                alt = attrs.get("alt") or self.default_image_alt

                # If we have images_with_size, write raw html including width,
                # height, and alt attributes
                if self.images_as_html or (
                    self.images_with_size and ("width" in attrs or "height" in attrs)
                ):
                    self.o(f"<img src=\'{attrs["src"]}\' ")
                    if "width" in attrs:
                        self.o(f"width=\'{attrs["width"]}\' ")
                    if "height" in attrs:
                        self.o(f"height=\'{attrs["height"]}\' ")
                    if alt:
                        self.o(f"alt=\'{alt}\' ")
                    self.o("/>")
                    return

                # If we have a link to create, output the start
                if self.maybe_automatic_link is not None:
                    href = self.maybe_automatic_link
                    if (
                        self.images_to_alt
                        and escape_md(alt) == href
                        and self.absolute_url_matcher.match(href)
                    ):
                        self.o("<" + escape_md(alt) + ">")
                        self.empty_link = False
                        return
                    self.o("[")
                    self.maybe_automatic_link = None
                    self.empty_link = False

                # If we have images_to_alt, we discard the image itself,
                # considering only the alt text.
                if self.images_to_alt:
                    self.o(escape_md(alt))
                else:
                    self.o("![" + str(Url(escape_md(alt))) + "]")
                    if self.inline_links:
                        href = attrs.get("href") or ""
                        self.o(
                            "("
                            + str(Url(escape_md(urlparse.urljoin(self.baseurl, href))))
                            + ")"
                        )
                    else:
                        i = self.previousIndex(attrs)
                        if i is not None:
                            a_props = self.a[i]
                        else:
                            self.acount += 1
                            a_props = AnchorElement(attrs, self.acount, self.outcount)
                            self.a.append(a_props)
                        self.o("[" + str(a_props.count) + "]")

        if tag == "dl" and start:
            self.p()
        if tag == "dt" and not start:
            self.pbr()
        if tag == "dd" and start:
            self.o("    ")
        if tag == "dd" and not start:
            self.pbr()

        if tag in ["ol", "ul"]:
            # Google Docs create sub lists as top level lists
            if not self.list and not self.lastWasList:
                self.p()
            if start:
                if self.google_doc:
                    list_style = google_list_style(tag_style)
                else:
                    list_style = tag
                numbering_start = list_numbering_start(attrs)
                self.list.append(ListElement(list_style, numbering_start))
            else:
                if self.list:
                    self.list.pop()
                    if not self.google_doc and not self.list:
                        self.o("\n")
            self.lastWasList = True
        else:
            self.lastWasList = False

        if tag == "li":
            self.pbr()
            if start:
                if self.list:
                    li = self.list[-1]
                else:
                    li = ListElement("ul", 0)
                if self.google_doc:
                    nest_count = self.google_nest_count(tag_style)
                else:
                    nest_count = len(self.list)
                # TODO: line up <ol><li>s > 9 correctly.
                self.o("  " * nest_count)
                if li.name == "ul":
                    self.o(self.ul_item_mark + " ")
                elif li.name == "ol":
                    li.num += 1
                    self.o(str(li.num) + ". ")
                self.start = True

        if tag in ["table", "tr", "td", "th"]:
            if self.ignore_tables:
                if tag == "tr":
                    if start:
                        pass
                    else:
                        self.soft_br()
                else:
                    pass

            elif self.bypass_tables:
                if start:
                    self.soft_br()
                if tag in ["td", "th"]:
                    if start:
                        self.o(f"<{tag}>\n\n")
                    else:
                        self.o(f"\n</{tag}>")
                else:
                    if start:
                        self.o(f"<{tag}>")
                    else:
                        self.o(f"</{tag}>")

            else:
                if tag == "table":
                    if start:
                        self.table_start = True
                        if self.pad_tables:
                            self.o("<" + config.TABLE_MARKER_FOR_PAD + ">")
                            self.o("  \n")
                    else:
                        if self.pad_tables:
                            self.o("</" + config.TABLE_MARKER_FOR_PAD + ">")
                            self.o("  \n")
                if tag in ["td", "th"] and start:
                    if self.split_next_td:
                        self.o("| ")
                    self.split_next_td = True

                if tag == "tr" and start:
                    self.td_count = 0
                if tag == "tr" and not start:
                    self.split_next_td = False
                    self.soft_br()
                if tag == "tr" and not start and self.table_start:
                    # Underline table header
                    self.o("|".join(["---"] * self.td_count))
                    self.soft_br()
                    self.table_start = False
                if tag in ["td", "th"] and start:
                    self.td_count += 1

        if tag == "pre":
            if start:
                self.startpre = True
                self.pre = True
            else:
                self.pre = False
                if self.mark_code:
                    self.out("\n[/code]")
            self.p()

    # TODO: Add docstring for these one letter functions
    def pbr(self) -> None:
        "Pretty print has a line break"
        if self.p_p == 0:
            self.p_p = 1

    def p(self) -> None:
        "Set pretty print to 1 or 2 lines"
        self.p_p = 1 if self.single_line_break else 2

    def soft_br(self) -> None:
        "Soft breaks"
        self.pbr()
        self.br_toggle = "  "

    def o(
        self, data: str, puredata: bool = False, force: Union[bool, str] = False
    ) -> None:
        """
        Deal with indentation and whitespace
        """
        if self.abbr_data is not None:
            self.abbr_data += data

        if not self.quiet:
            if self.google_doc:
                # prevent white space immediately after "begin emphasis"
                # marks ("**" and "_")
                lstripped_data = data.lstrip()
                if self.drop_white_space and not (self.pre or self.code):
                    data = lstripped_data
                if lstripped_data != "":
                    self.drop_white_space = 0

            if puredata and not self.pre:
                # This is a very dangerous call ... it could mess up
                # all handling of &nbsp; when not handled properly
                # (see entityref)
                data = re.sub(r"\s+", r" ", data)
                if data and data[0] == " ":
                    self.space = True
                    data = data[1:]
            if not data and not force:
                return

            if self.startpre:
                # self.out(" :") #TODO: not output when already one there
                if not data.startswith("\n") and not data.startswith("\r\n"):
                    # <pre>stuff...
                    data = "\n" + data
                if self.mark_code:
                    self.out("\n[code]")
                    self.p_p = 0

            bq = ">" * self.blockquote
            if not (force and data and data[0] == ">") and self.blockquote:
                bq += " "

            if self.pre:
                if not self.list:
                    bq += "    "
                # else: list content is already partially indented
                bq += "    " * len(self.list)
                data = data.replace("\n", "\n" + bq)

            if self.startpre:
                self.startpre = False
                if self.list:
                    # use existing initial indentation
                    data = data.lstrip("\n")

            if self.start:
                self.space = False
                self.p_p = 0
                self.start = False

            if force == "end":
                # It's the end.
                self.p_p = 0
                self.out("\n")
                self.space = False

            if self.p_p:
                self.out((self.br_toggle + "\n" + bq) * self.p_p)
                self.space = False
                self.br_toggle = ""

            if self.space:
                if not self.lastWasNL:
                    self.out(" ")
                self.space = False

            if self.a and (
                (self.p_p == 2 and self.links_each_paragraph) or force == "end"
            ):
                if force == "end":
                    self.out("\n")

                newa = []
                for link in self.a:
                    if self.outcount > link.outcount:
                        self.out(
                            "   ["
                            + str(link.count)
                            + "]: "
                            + str(
                                Url(urlparse.urljoin(self.baseurl, link.attrs["href"]))
                            )
                        )
                        if "title" in link.attrs:
                            self.out(" (" + link.attrs["title"] + ")")
                        self.out("\n")
                    else:
                        newa.append(link)

                # Don't need an extra line when nothing was done.
                if self.a != newa:
                    self.out("\n")

                self.a = newa

            if self.abbr_list and force == "end":
                for abbr, definition in self.abbr_list.items():
                    self.out("  *[" + abbr + "]: " + definition + "\n")

            self.p_p = 0
            self.out(data)
            self.outcount += 1

    def handle_data(self, data: str, entity_char: bool = False) -> None:
        if not data:
            # Data may be empty for some HTML entities. For example,
            # LEFT-TO-RIGHT MARK.
            return

        if self.stressed:
            data = data.strip()
            self.stressed = False
            self.preceding_stressed = True
        elif self.preceding_stressed:
            if (
                re.match(r"[^\s.!?]", data[0])
                and not hn(self.current_tag)
                and self.current_tag not in ["a", "code", "pre"]
            ):
                # should match a letter or common punctuation
                data = " " + data
            self.preceding_stressed = False

        if self.style:
            self.style_def.update(dumb_css_parser(data))

        if self.maybe_automatic_link is not None:
            href = self.maybe_automatic_link
            if (
                href == data
                and self.absolute_url_matcher.match(href)
                and self.use_automatic_links
            ):
                self.o("<" + data + ">")
                self.empty_link = False
                return
            self.o("[")
            self.maybe_automatic_link = None
            self.empty_link = False

        if not self.code and not self.pre and not entity_char:
            data = escape_md_section(data, snob=self.escape_snob)
        self.preceding_data = data
        self.o(data, puredata=True)

    def charref(self, name: str) -> str:
        if name[0] in ["x", "X"]:
            c = int(name[1:], 16)
        else:
            c = int(name)

        if not self.unicode_snob and c in unifiable_n:
            return unifiable_n[c]
        try:
            return chr(c)
        except ValueError:  # invalid unicode
            return ""

    def entityref(self, c: str) -> str:
        if not self.unicode_snob and c in config.UNIFIABLE:
            return config.UNIFIABLE[c]
        try:
            ch = html.entities.html5[c + ";"]
        except KeyError:
            return "&" + c + ";"
        return config.UNIFIABLE[c] if c == "nbsp" else ch

    def google_nest_count(self, style: Dict[str, str]) -> int:
        """
        Calculate the nesting count of google doc lists

        :type style: dict

        :rtype: int
        """
        nest_count = 0
        if "margin-left" in style:
            nest_count = int(style["margin-left"][:-2]) // self.google_list_indent

        return nest_count

    def optwrap(self, text: str) -> str:
        """
        Wrap all paragraphs in the provided text.

        :type text: str

        :rtype: str
        """
        if not self.body_width:
            return text

        result = ""
        newlines = 0
        # I cannot think of a better solution for now.
        # To avoid the non-wrap behaviour for entire paras
        # because of the presence of a link in it
        if not self.wrap_links:
            self.inline_links = False
        for para in text.split("\n"):
            if len(para) > 0:
                if not skipwrap(para, self.wrap_links, self.wrap_list_items):
                    indent = ""
                    if para.startswith("  " + self.ul_item_mark):
                        # list item continuation: add a double indent to the
                        # new lines
                        indent = "    "
                    elif para.startswith("> "):
                        # blockquote continuation: add the greater than symbol
                        # to the new lines
                        indent = "> "
                    wrapped = wrap(
                        para,
                        self.body_width,
                        break_long_words=False,
                        subsequent_indent=indent,
                    )
                    result += "\n".join(wrapped)
                    if para.endswith("  "):
                        result += "  \n"
                        newlines = 1
                    elif indent:
                        result += "\n"
                        newlines = 1
                    else:
                        result += "\n\n"
                        newlines = 2
                else:
                    # Warning for the tempted!!!
                    # Be aware that obvious replacement of this with
                    # line.isspace()
                    # DOES NOT work! Explanations are welcome.
                    if not config.RE_SPACE.match(para):
                        result += para + "\n"
                        newlines = 1
            else:
                if newlines < 2:
                    result += "\n"
                    newlines += 1
        return result


def html2text(html: str, baseurl: str = "", bodywidth: Optional[int] = None) -> str:
    if bodywidth is None:
        bodywidth = config.BODY_WIDTH
    h = HTML2Text(baseurl=baseurl, bodywidth=bodywidth)

    return h.handle(html)
