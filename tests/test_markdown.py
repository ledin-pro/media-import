from pro.ledin.media_import.docling_adapter import DocumentEvent, Track
from pro.ledin.media_import.markdown import render_media_markdown


def test_media_markdown_preserves_order_without_visible_timestamps() -> None:
    events = [
        DocumentEvent("a", "text", "[time: 00:01] First words", Track(1, 2, None), None),
        DocumentEvent("p", "picture", "", Track(3, 3, None), None),
        DocumentEvent("b", "text", "Second words", Track(4, 5, None), None),
    ]
    result = render_media_markdown(
        title="Lecture",
        metadata={"importer": "media-import"},
        events=events,
        visual_text={"p": {"text": "Slide text"}},
    )
    assert "[time:" not in result
    assert result.index("First words") < result.index("Slide text") < result.index("Second words")
    assert "### Visual Text" in result


def test_media_markdown_embeds_saved_picture_at_event_position() -> None:
    events = [
        DocumentEvent("a", "text", "Before", Track(1, 2, None), None),
        DocumentEvent("p", "picture", "", Track(3, 3, None), None),
        DocumentEvent("b", "text", "After", Track(4, 5, None), None),
    ]
    result = render_media_markdown(
        title="Lecture",
        metadata={"importer": "media-import"},
        events=events,
        visual_text={"p": {"image_path": "assets/frame.png"}},
    )
    assert result.index("Before") < result.index("![[assets/frame.png]]") < result.index("After")
