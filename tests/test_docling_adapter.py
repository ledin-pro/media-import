from dataclasses import dataclass

from pro.ledin.media_import.docling_adapter import iter_events


@dataclass
class FakeTrack:
    start_time: float
    end_time: float
    voice: str = "speaker"


class TextItem:
    text = "hello"
    source = [FakeTrack(1.0, 2.0)]
    self_ref = "#/texts/0"


class PictureItem:
    text = ""
    source = [FakeTrack(3.0, 3.0)]
    self_ref = "#/pictures/0"


class FakeDocument:
    def iterate_items(self):
        return [(TextItem(), 0), (PictureItem(), 0)]


def test_iter_events_keeps_docling_order_and_track_data() -> None:
    events = list(iter_events(FakeDocument()))
    assert [event.kind for event in events] == ["text", "picture"]
    assert events[0].track is not None
    assert events[0].track.start_time == 1.0
    assert events[1].event_id == "#/pictures/0"
