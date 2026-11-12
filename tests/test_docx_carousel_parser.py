"""Minimized OOXML versions of the two illustrated LAP carousel brief layouts."""

from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZipFile

import pytest

import docx_carousel_parser as parser
from cta import TATA_CTA_URL


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


@pytest.fixture(autouse=True)
def media_cache(tmp_path, monkeypatch):
    directory = tmp_path / "media_cache"
    monkeypatch.setattr(parser, "MEDIA_CACHE_DIR", directory)
    return directory


def _p(text, *, heading=False):
    properties = '<w:pPr><w:jc w:val="center"/></w:pPr>' if heading else ""
    bold = "<w:rPr><w:b/></w:rPr>" if heading else ""
    runs = "<w:br/>".join(f"<w:t xml:space=\"preserve\">{escape(line)}</w:t>" for line in text.split("\n"))
    return f"<w:p>{properties}<w:r>{bold}{runs}</w:r></w:p>"


def _image(rid, *, floating=False):
    position = "anchor" if floating else "inline"
    return (
        f'<w:p><w:r><w:drawing><wp:{position}>'
        f'<a:blip r:embed="{rid}"/>'
        f'</wp:{position}></w:drawing></w:r></w:p>'
    )


def _docx(tmp_path, paragraphs, relationships=None, media=None, name="LAP_RCS_carousal.docx"):
    if relationships is None:
        relationships = [(f"rId{i}", f"media/image{i}.jpeg", False) for i in range(1, 7)]
    if media is None:
        media = {f"word/media/image{i}.jpeg": f"image-{i}".encode() for i in range(1, 7)}
    document = (
        f'<w:document xmlns:w="{_W}" xmlns:a="{_A}" xmlns:r="{_R}" xmlns:wp="{_WP}">'
        f'<w:body>{"".join(paragraphs)}<w:sectPr/></w:body></w:document>'
    )
    rels = []
    for rid, target, external in relationships:
        mode = ' TargetMode="External"' if external else ""
        rels.append(f'<Relationship Id="{rid}" Type="{_R}/image" Target={quoteattr(target)}{mode}/>')
    path = tmp_path / name
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(rels) + "</Relationships>",
        )
        for member, data in media.items():
            archive.writestr(member, data)
    return path


def _implicit_cards(first_copy="Your Tata Capital Pre‑Approved offer up to ₹<amt> is ready.", first_rid=1):
    titles = [
        "Dear <name> Big Plans on Your Mind?", "One Loan. Multiple Uses.",
        "Big Amounts for Bigger Plans", "Lower Rates. Greater Savings.",
        "Flexible Tenure. Easy Repayments.",
    ]
    descriptions = [
        first_copy,
        "Leverage your property through Tata Capital to meet diverse needs.",
        "Access a wide loan range with Tata Capital Loan Against Property.",
        "Benefit from competitive pricing that helps you manage repayments efficiently.",
        "Choose a repayment tenure of up to 20 years while planning long‑term goals",
    ]
    buttons = ["Unlock Now", "Unlock Now", "Make it happen", "Start your journey", "Power your plans"]
    paragraphs = []
    for index, (title, description, button) in enumerate(zip(titles, descriptions, buttons), 1):
        paragraphs.extend([
            _image(f"rId{first_rid if index == 1 else index}"),
            _p(""),
            _p(title + "\n" + description),
            _p("CTA:\n" + button + "<link>"),
            _p("T&Cs apply"),
        ])
    return paragraphs


def test_two_carousels_keep_order_copy_ctas_and_reused_image_relationships(tmp_path):
    paragraphs = _implicit_cards()
    paragraphs.extend([_p(""), _p("LAP Generic, PQ", heading=True)])
    paragraphs.extend(_implicit_cards("Your Tata Capital Pre‑Qualified Loan Against Property is ready.", 6))
    # ZIP relationship order is unrelated to the authored image/card order.
    relationships = [(f"rId{i}", f"media/image{i}.jpeg", False) for i in [5, 3, 6, 1, 4, 2]]
    path = _docx(tmp_path, paragraphs, relationships)

    items = parser.extract_docx_carousels(path)

    assert len(items) == 2
    assert [len(item["carousel_cards"]) for item in items] == [5, 5]
    assert all(item["channel"] == "RCS" and item["template_type"] == "carousel" for item in items)
    assert not any(item["media_pairing_ambiguous"] for item in items)
    assert items[1]["variant"] == "LAP Generic, PQ"
    assert "LAP Generic" not in items[0]["raw_text"]
    assert items[0]["text"] == "Your Tata Capital Pre‑Approved offer up to ₹<amt> is ready.\nT&Cs apply"
    assert items[1]["text"] == "Your Tata Capital Pre‑Qualified Loan Against Property is ready.\nT&Cs apply"
    first = items[0]["carousel_cards"]
    second = items[1]["carousel_cards"]
    assert first[0]["card_title"] == "Dear <name> Big Plans on Your Mind?"
    assert [card["button_text"] for card in first] == [
        "Unlock Now", "Unlock Now", "Make it happen", "Start your journey", "Power your plans",
    ]
    for index, card in enumerate(first, 1):
        assert Path(card["media_url"]).read_bytes() == f"image-{index}".encode()
        assert card["media_filename"] == Path(card["media_url"]).name
        assert card["button_url"] == TATA_CTA_URL + "<link>"
        assert card["suggestions"][0]["url"] == card["button_url"]
    assert Path(second[0]["media_url"]).read_bytes() == b"image-6"
    assert [card["media_url"] for card in first[1:]] == [card["media_url"] for card in second[1:]]
    assert parser.extract_docx_carousels(path) == items


def test_explicit_title_description_layout_preserves_split_runs_and_terms(tmp_path):
    paragraphs = []
    for index, button in enumerate(["Check Offer", "Get Funds", "Apply Now", "Unlock Now", "Explore Now"], 1):
        paragraphs.extend([
            _image(f"rId{index}"),
            _p(f"Title:\nUnlock Additional Funds {index} 🚀"),
            _p("Description:\nAvail Tata Capital Pre-Approved Top-up offer up to ₹<amt> —no fresh paperwork, no stress."),
            _p("T&Cs Apply"),
            _p(f"CTA:\n[{button}] <link>"),
        ])
    # Real briefs split words across runs and encode nonbreaking hyphens as nodes.
    paragraphs[2] = paragraphs[2].replace("Top-up", "Top</w:t><w:noBreakHyphen/><w:t>up")
    path = _docx(tmp_path, paragraphs)

    items = parser.extract_docx_carousels(path)

    assert len(items) == 1
    cards = items[0]["carousel_cards"]
    assert len(cards) == 5
    assert cards[0]["card_title"] == "Unlock Additional Funds 1 🚀"
    assert cards[0]["card_description"] == (
        "Avail Tata Capital Pre-Approved Top‑up offer up to ₹<amt> —no fresh paperwork, no stress.\nT&Cs Apply"
    )
    assert cards[0]["button_text"] == "Check Offer"
    assert cards[4]["button_text"] == "Explore Now"
    assert items[0]["text"] == cards[0]["card_description"]
    assert "Description:" not in items[0]["text"]


@pytest.mark.parametrize("target,external", [
    ("https://example.test/image.jpeg", True),
    ("../outside.jpeg", False),
    ("media/%2e%2e/outside.jpeg", False),
    ("media/missing.jpeg", False),
])
def test_unproven_relationship_never_guesses_another_image(tmp_path, media_cache, target, external):
    relationships = [(f"rId{i}", f"media/image{i}.jpeg", False) for i in range(1, 6)]
    relationships[1] = ("rId2", target, external)
    path = _docx(tmp_path, _implicit_cards(), relationships)

    item = parser.extract_docx_carousels(path)[0]

    assert len(item["carousel_cards"]) == 5
    assert item["media_pairing_ambiguous"] is True
    assert item["carousel_cards"][1]["media_url"] is None
    assert item["carousel_cards"][1]["media_filename"] is None
    assert item["carousel_cards"][2]["media_url"] is not None
    assert all(child.parent == media_cache for child in media_cache.iterdir())


def test_floating_image_retains_copy_but_blocks_pairing(tmp_path):
    paragraphs = _implicit_cards()
    paragraphs[0] = _image("rId1", floating=True)
    item = parser.extract_docx_carousels(_docx(tmp_path, paragraphs))[0]
    assert item["media_pairing_ambiguous"] is True
    assert item["carousel_cards"][0]["media_url"] is None
    assert "₹<amt>" in item["carousel_cards"][0]["card_description"]


def test_missing_image_with_explicit_card_title_keeps_card_and_marks_ambiguity(tmp_path):
    paragraphs = [
        _image("rId1"), _p("Title:\nFirst"), _p("Description:\nTata Capital loan offer one."), _p("CTA:\nCheck <link>"),
        _p("Title:\nSecond"), _p("Description:\nTata Capital loan offer two."), _p("CTA:\nApply <link>"),
    ]
    item = parser.extract_docx_carousels(_docx(tmp_path, paragraphs))[0]
    assert len(item["carousel_cards"]) == 2
    assert item["carousel_cards"][1]["card_title"] == "Second"
    assert item["carousel_cards"][1]["media_url"] is None
    assert item["media_pairing_ambiguous"] is True


def test_ordinary_word_returns_none_and_recognized_incomplete_carousel_returns_empty(tmp_path):
    ordinary = _docx(tmp_path, [_p("RCS copy for Tata Capital loan offer")], name="RCS_copy.docx")
    assert parser.extract_docx_carousels(ordinary) is None
    no_cards = _docx(tmp_path, [_p("RCS Carousel")])
    assert parser.extract_docx_carousels(no_cards) == []
    incomplete = _implicit_cards()
    incomplete[8] = _p("Missing an authored CTA")
    assert parser.extract_docx_carousels(_docx(tmp_path, incomplete)) == []


def test_plain_authored_carousel_headings_separate_groups_without_filename_hint(tmp_path):
    paragraphs = [_p("RCS Carousel 1"), *_implicit_cards(), _p("RCS Carousel 2"), *_implicit_cards()]
    items = parser.extract_docx_carousels(_docx(tmp_path, paragraphs, name="brief.docx"))
    assert [item["variant"] for item in items] == ["RCS Carousel 1", "RCS Carousel 2"]
    assert [len(item["carousel_cards"]) for item in items] == [5, 5]


def test_extended_word_symbol_preserves_emoji_once():
    paragraph = parser.ET.fromstring(
        f'<w:p xmlns:w="{_W}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:w16se="http://schemas.microsoft.com/office/word/2015/wordml/symex">'
        '<w:r><w:t>Don’t Pause Your Growth</w:t></w:r><w:r>'
        '<mc:AlternateContent><mc:Choice Requires="w16se">'
        '<w16se:symEx w16se:font="Segoe UI Emoji" w16se:char="1F4C8"/>'
        '</mc:Choice><mc:Fallback><w:t>📈</w:t></mc:Fallback></mc:AlternateContent>'
        '</w:r></w:p>'
    )
    assert parser._paragraph(paragraph)[0] == "Don’t Pause Your Growth📈"


def test_missing_first_image_is_not_silently_dropped(tmp_path):
    paragraphs = _implicit_cards()[1:]
    item = parser.extract_docx_carousels(_docx(tmp_path, paragraphs))[0]
    assert len(item["carousel_cards"]) == 5
    assert item["carousel_cards"][0]["media_url"] is None
    assert item["media_pairing_ambiguous"] is True


def test_legacy_word_is_ignored_but_recognized_broken_xml_does_not_fall_through(tmp_path):
    legacy = tmp_path / "RCS_carousal.doc"
    legacy.write_bytes(b"not an OOXML package")
    assert parser.extract_docx_carousels(legacy) is None
    assert parser.extract_docx_carousels(tmp_path / "missing.docx") is None
    malformed = tmp_path / "RCS_carousal.docx"
    with ZipFile(malformed, "w") as archive:
        archive.writestr("word/document.xml", "<broken")
    assert parser.extract_docx_carousels(malformed) == []


@pytest.mark.parametrize("name,count", [
    ("jira_31785_LAP_RCS_Carousal_Jun_26_updated.docx", 2),
    ("jira_31777_LAP_RCS_carousal_Top_up-_June_26.docx", 1),
])
def test_optional_downloaded_corpus_regression(name, count):
    path = Path("/tmp/tcn-attachment-audit") / name
    if not path.exists():
        pytest.skip("Downloaded attachment audit corpus is not available")
    items = parser.extract_docx_carousels(path)
    assert len(items) == count
    assert all(len(item["carousel_cards"]) == 5 for item in items)
    assert all(not item["media_pairing_ambiguous"] for item in items)
    assert all(item["text"] == item["carousel_cards"][0]["card_description"] for item in items)
    assert "₹<amt>" in items[0]["text"]
    if count == 2:
        assert "Pre‑Qualified" in items[1]["text"]
        assert items[1]["variant"] == "LAP Generic, PQ"
    else:
        assert items[0]["carousel_cards"][0]["card_title"] == "Unlock Additional Funds on Your Existing Loan Against Property 🚀"
        assert items[0]["carousel_cards"][1]["card_title"] == "Don’t Pause Your Growth📈"
