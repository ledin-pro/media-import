from pathlib import Path

import pro.ledin.media_import.language_routing as routing
from pro.ledin.media_import.config import Config


class FakeDetector:
    def __init__(self, result: routing.LanguageDetectionResult) -> None:
        self.result = result
        self.calls = 0

    def detect(self, source, *, media_sha256, cache_dir, device):
        self.calls += 1
        return self.result


class FailingDetector:
    def __init__(self) -> None:
        self.calls = 0

    def detect(self, source, *, media_sha256, cache_dir, device):
        self.calls += 1
        raise RuntimeError("temporary detector failure")


def make_config(tmp_path: Path, **overrides) -> Config:
    values = {
        "source": "source.wav",
        "vault_root": tmp_path / "vault",
        "output_dir": Path("corpus"),
        "cache_dir": tmp_path / "cache",
    }
    values.update(overrides)
    return Config(**values)


def confident(language: str) -> routing.LanguageDetectionResult:
    return routing.LanguageDetectionResult(
        detected_language=language,
        confidence=0.95,
        sample_count=5,
        status="complete",
        method="test-detector",
        vote_share=1.0,
        margin=0.9,
        attempted_sample_count=5,
    )


def test_explicit_provider_bypasses_detection(tmp_path: Path) -> None:
    detector = FakeDetector(confident("ru"))
    config = make_config(tmp_path, transcription_provider="docling-native")

    resolved = routing.resolve_media_route("source.wav", config, detector=detector)

    assert detector.calls == 0
    assert resolved.transcription_provider == "docling-native"
    assert resolved._route_reason == "explicit-provider"


def test_configured_language_bypasses_detection_and_routes_russian(
    tmp_path: Path, monkeypatch
) -> None:
    detector = FakeDetector(confident("en"))
    config = make_config(tmp_path, transcription_language="ru")
    monkeypatch.setattr(routing, "gigaam_route_available", lambda config: (True, "available"))

    resolved = routing.resolve_media_route("source.wav", config, detector=detector)

    assert detector.calls == 0
    assert resolved.transcription_provider == "gigaam"
    assert resolved.transcription_model == "v3_e2e_rnnt"
    assert resolved.transcription_language == "ru"
    assert resolved._route_reason == "configured-russian"


def test_confident_russian_routes_to_gigaam(tmp_path: Path, monkeypatch) -> None:
    detector = FakeDetector(confident("ru"))
    config = make_config(tmp_path)
    monkeypatch.setattr(routing, "gigaam_route_available", lambda config: (True, "available"))

    resolved = routing.resolve_media_route("source.wav", config, detector=detector)

    assert detector.calls == 1
    assert resolved.transcription_provider == "gigaam"
    assert resolved.transcription_model == "v3_e2e_rnnt"
    assert resolved.transcription_language == "ru"
    assert resolved._route_detected_language == "ru"
    assert resolved._route_reason == "confident-russian"


def test_unavailable_gigaam_falls_back_with_warning(tmp_path: Path, monkeypatch) -> None:
    detector = FakeDetector(confident("ru"))
    config = make_config(tmp_path)
    monkeypatch.setattr(
        routing,
        "gigaam_route_available",
        lambda config: (False, "docling-gigaam is not installed"),
    )

    resolved = routing.resolve_media_route("source.wav", config, detector=detector)

    assert resolved.transcription_provider == "auto"
    assert resolved.transcription_language == "ru"
    assert resolved._route_reason == "gigaam-unavailable-fallback"
    assert "falling back" in resolved._route_warnings[0]


def test_uncertain_language_stays_on_whisper_auto(tmp_path: Path) -> None:
    detector = FakeDetector(
        routing.LanguageDetectionResult(
            confidence=0.55,
            sample_count=5,
            status="uncertain",
            method="test-detector",
            attempted_sample_count=5,
        )
    )

    resolved = routing.resolve_media_route(
        "source.wav", make_config(tmp_path), detector=detector
    )

    assert resolved.transcription_provider == "auto"
    assert resolved.transcription_language == "auto"
    assert resolved._route_reason == "language-uncertain-or-mixed"


def test_short_media_uses_one_unique_sample() -> None:
    assert routing._sample_starts(10.0) == [0.0]


def test_mixed_votes_are_not_confident() -> None:
    result = routing._aggregate(
        [
            {"ru": 0.95, "en": 0.05},
            {"ru": 0.95, "en": 0.05},
            {"ru": 0.95, "en": 0.05},
            {"ru": 0.05, "en": 0.95},
            {"ru": 0.05, "en": 0.95},
        ],
        attempted=5,
    )

    assert result.status == "uncertain"
    assert result.detected_language is None


def test_unavailable_detection_is_not_cached(tmp_path: Path) -> None:
    detector = FailingDetector()
    arguments = {
        "source": "source.wav",
        "media_sha256": "hash",
        "cache_dir": tmp_path / "cache",
        "detector": detector,
    }

    first = routing.detect_language(**arguments)
    second = routing.detect_language(**arguments)

    assert first.status == "unavailable"
    assert second.status == "unavailable"
    assert detector.calls == 2
