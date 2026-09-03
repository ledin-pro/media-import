from __future__ import annotations

import hashlib
import io
import json
import math
import platform
import subprocess
import tempfile
import wave
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from .config import Config
from .environment import gigaam_route_available
from .paths import atomic_write

DETECTOR_VERSION = "whisper-base-v2"
DETECTION_MODEL = "base"
DETECTION_MLX_REPO = "mlx-community/whisper-base-mlx"
DETECTION_SAMPLE_COUNT = 5
DETECTION_SAMPLE_SECONDS = 25.0
DETECTION_SAMPLE_RATE = 16_000
MIN_USABLE_SAMPLES = 3
MIN_AUDIO_SECONDS = 0.1
MIN_RMS = 0.005

# These are intentionally conservative and are not configuration knobs yet.
LANGUAGE_CONFIDENCE_THRESHOLD = 0.75
LANGUAGE_VOTE_THRESHOLD = 0.60
LANGUAGE_MARGIN_THRESHOLD = 0.15
RUSSIAN_CONFIDENCE_THRESHOLD = 0.80
RUSSIAN_VOTE_THRESHOLD = 0.75
RUSSIAN_MARGIN_THRESHOLD = 0.20


@dataclass(frozen=True)
class LanguageDetectionResult:
    detected_language: str | None = None
    confidence: float | None = None
    sample_count: int = 0
    status: str = "unavailable"
    method: str = "openai-whisper:tiny"
    vote_share: float | None = None
    margin: float | None = None
    attempted_sample_count: int = 0
    error: str | None = None

    @property
    def sample_status(self) -> str:
        return self.status

    @property
    def is_confident(self) -> bool:
        return self.detected_language is not None and self.confidence is not None


class LanguageDetector(Protocol):
    def detect(
        self,
        source: Path | str,
        *,
        media_sha256: str | None,
        cache_dir: Path,
        device: str,
    ) -> LanguageDetectionResult: ...


def _normalise_language(value: object) -> str:
    language = str(value).strip().casefold()
    return {"rus": "ru", "russian": "ru", "eng": "en", "english": "en"}.get(
        language, language
    )


def _sample_starts(duration: float) -> list[float]:
    if not math.isfinite(duration) or duration <= 0:
        return []
    available = max(0.0, duration - DETECTION_SAMPLE_SECONDS)
    if available == 0:
        return [0.0]
    denominator = max(DETECTION_SAMPLE_COUNT - 1, 1)
    return [available * index / denominator for index in range(DETECTION_SAMPLE_COUNT)]


def _probe_duration(source: Path | str) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe could not determine media duration")
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("ffprobe returned an invalid media duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("media duration is empty or invalid")
    return duration


def _extract_sample(source: Path | str, start: float, duration: float) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(source),
            "-vn",
            "-sn",
            "-ac",
            "1",
            "-ar",
            str(DETECTION_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        return b""
    return result.stdout


def _usable_wav(payload: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(payload), "rb") as handle:
            frame_count = handle.getnframes()
            sample_width = handle.getsampwidth()
            frame_rate = handle.getframerate()
            raw = handle.readframes(frame_count)
    except (EOFError, wave.Error):
        return False
    if (
        sample_width != 2
        or frame_rate != DETECTION_SAMPLE_RATE
        or frame_count < int(DETECTION_SAMPLE_RATE * MIN_AUDIO_SECONDS)
    ):
        return False
    try:
        samples = memoryview(raw).cast("h")
    except (TypeError, ValueError):
        return False
    if not samples:
        return False
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
    return rms >= MIN_RMS


def _aggregate(probabilities: list[Mapping[str, float]], attempted: int) -> LanguageDetectionResult:
    if not probabilities:
        return LanguageDetectionResult(
            status="unusable",
            attempted_sample_count=attempted,
        )

    cleaned_samples: list[dict[str, float]] = []
    totals: defaultdict[str, float] = defaultdict(float)
    votes: Counter[str] = Counter()
    for sample in probabilities:
        cleaned = {
            _normalise_language(language): float(probability)
            for language, probability in sample.items()
            if math.isfinite(float(probability)) and float(probability) >= 0
        }
        if not cleaned:
            continue
        cleaned_samples.append(cleaned)
        for language, probability in cleaned.items():
            totals[language] += probability
        votes[max(cleaned, key=lambda language: cleaned[language])] += 1

    valid_count = len(cleaned_samples)
    if not totals or not votes:
        return LanguageDetectionResult(
            sample_count=valid_count,
            attempted_sample_count=attempted,
            status="unusable",
        )

    means = {language: total / valid_count for language, total in totals.items()}
    ordered = sorted(means.items(), key=lambda pair: pair[1], reverse=True)
    winner, confidence = ordered[0]
    second = ordered[1][1] if len(ordered) > 1 else 0.0
    vote_share = votes[winner] / valid_count
    margin = confidence - second
    confident = (
        valid_count >= min(MIN_USABLE_SAMPLES, attempted)
        and confidence >= LANGUAGE_CONFIDENCE_THRESHOLD
        and vote_share >= LANGUAGE_VOTE_THRESHOLD
        and margin >= LANGUAGE_MARGIN_THRESHOLD
    )
    return LanguageDetectionResult(
        detected_language=winner if confident else None,
        confidence=confidence,
        sample_count=valid_count,
        status="complete" if confident else "uncertain",
        vote_share=vote_share,
        margin=margin,
        attempted_sample_count=attempted,
    )


class WhisperLanguageDetector:
    """Detect language from short targeted media windows using multilingual Whisper."""

    def detect(
        self,
        source: Path | str,
        *,
        media_sha256: str | None,
        cache_dir: Path,
        device: str,
    ) -> LanguageDetectionResult:
        del media_sha256
        duration = _probe_duration(source)
        starts = _sample_starts(duration)
        samples = [
            payload
            for start in starts
            if _usable_wav(
                payload := _extract_sample(
                    source,
                    start,
                    min(DETECTION_SAMPLE_SECONDS, max(duration - start, 0.0)),
                )
            )
        ]
        if not samples:
            return LanguageDetectionResult(
                status="unusable",
                method=f"whisper:{DETECTION_MODEL}",
                attempted_sample_count=len(starts),
            )

        use_mlx = (
            platform.system() == "Darwin"
            and platform.machine() == "arm64"
            and device.casefold() in {"auto", "mlx", "mps"}
        )
        if use_mlx:
            sample_probabilities = _detect_with_mlx(samples, cache_dir)
            method = f"mlx-whisper:{DETECTION_MLX_REPO}"
        else:
            sample_probabilities = _detect_with_native_whisper(samples, cache_dir, device)
            method = f"openai-whisper:{DETECTION_MODEL}"

        result = _aggregate(sample_probabilities, len(starts))
        return replace(result, method=method)


@contextmanager
def _sample_file(payload: bytes) -> Iterator[Any]:
    with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
        handle.write(payload)
        handle.flush()
        yield handle


def _detect_with_mlx(
    samples: list[bytes], cache_dir: Path
) -> list[Mapping[str, float]]:
    from huggingface_hub import snapshot_download
    from mlx_whisper.audio import load_audio, log_mel_spectrogram, pad_or_trim
    from mlx_whisper.decoding import detect_language
    from mlx_whisper.load_models import load_model

    model_path = snapshot_download(
        repo_id=DETECTION_MLX_REPO,
        cache_dir=cache_dir / "huggingface" / "hub",
    )
    model = load_model(model_path)
    probabilities: list[Mapping[str, float]] = []
    for payload in samples:
        with _sample_file(payload) as handle:
            audio = pad_or_trim(load_audio(handle.name))
        mel = log_mel_spectrogram(audio, n_mels=model.dims.n_mels)
        _, sample_probabilities = detect_language(model, mel)
        if isinstance(sample_probabilities, list):
            sample_probabilities = sample_probabilities[0]
        probabilities.append(sample_probabilities)
    return probabilities


def _detect_with_native_whisper(
    samples: list[bytes], cache_dir: Path, device: str
) -> list[Mapping[str, float]]:
    import whisper

    model = whisper.load_model(
        DETECTION_MODEL,
        device=None if device == "auto" else device,
        download_root=str(cache_dir / "whisper"),
    )
    probabilities: list[Mapping[str, float]] = []
    for payload in samples:
        with _sample_file(payload) as handle:
            audio = whisper.load_audio(handle.name)
        audio = whisper.pad_or_trim(audio)
        mel = whisper.log_mel_spectrogram(
            audio,
            n_mels=model.dims.n_mels,
            device=getattr(model, "device", None),
        )
        _, sample_probabilities = model.detect_language(mel)
        if isinstance(sample_probabilities, list):
            sample_probabilities = sample_probabilities[0]
        probabilities.append(sample_probabilities)
    return probabilities


def _cache_path(
    source: Path | str,
    media_sha256: str | None,
    cache_dir: Path,
    device: str,
) -> Path:
    media_key = media_sha256 or hashlib.sha256(str(source).encode("utf-8")).hexdigest()
    settings = {
        "detector_version": DETECTOR_VERSION,
        "model": DETECTION_MODEL,
        "sample_count": DETECTION_SAMPLE_COUNT,
        "sample_seconds": DETECTION_SAMPLE_SECONDS,
        "sample_rate": DETECTION_SAMPLE_RATE,
        "device": device,
    }
    settings_key = hashlib.sha256(
        json.dumps(settings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return cache_dir / "language-detection" / f"{media_key}-{settings_key}.json"


def _cached_result(path: Path) -> LanguageDetectionResult | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    try:
        return LanguageDetectionResult(
            detected_language=value.get("detected_language"),
            confidence=(
                float(value["confidence"]) if value.get("confidence") is not None else None
            ),
            sample_count=int(value.get("sample_count", 0)),
            status=str(value.get("status", "unavailable")),
            method=str(value.get("method", f"whisper:{DETECTION_MODEL}")),
            vote_share=(
                float(value["vote_share"]) if value.get("vote_share") is not None else None
            ),
            margin=(float(value["margin"]) if value.get("margin") is not None else None),
            attempted_sample_count=int(value.get("attempted_sample_count", 0)),
            error=(str(value["error"]) if value.get("error") is not None else None),
        )
    except (TypeError, ValueError):
        return None


def detect_language(
    source: Path | str,
    *,
    media_sha256: str | None,
    cache_dir: Path,
    device: str = "auto",
    detector: LanguageDetector | None = None,
) -> LanguageDetectionResult:
    """Detect and cache spoken language without extracting the complete media file."""

    path = _cache_path(source, media_sha256, cache_dir, device)
    cached = _cached_result(path)
    if cached is not None:
        return cached

    active_detector = detector or WhisperLanguageDetector()
    try:
        result = active_detector.detect(
            source,
            media_sha256=media_sha256,
            cache_dir=cache_dir,
            device=device,
        )
    except ImportError:
        result = LanguageDetectionResult(
            status="unavailable",
            method=f"whisper:{DETECTION_MODEL}",
            error="a supported Whisper language detector is not available",
        )
    except Exception as exc:  # ASR backends expose dependency-specific exception types.
        result = LanguageDetectionResult(
            status="unavailable",
            method=f"whisper:{DETECTION_MODEL}",
            error=str(exc),
        )

    if result.status != "unavailable":
        atomic_write(
            path,
            json.dumps(asdict(result), ensure_ascii=False, sort_keys=True) + "\n",
            [cache_dir],
        )
    return result


def _route_config(
    config: Config,
    *,
    provider: str,
    model: str,
    language: str,
    detection: LanguageDetectionResult,
    reason: str,
    warnings: tuple[str, ...] = (),
    auto_detected: bool = False,
) -> Config:
    return replace(
        config,
        transcription_provider=provider,
        transcription_model=model,
        transcription_language=language,
        _route_requested_provider=config.transcription_provider,
        _route_requested_model=config.transcription_model,
        _route_requested_language=config.transcription_language,
        _route_detected_language=detection.detected_language,
        _route_confidence=detection.confidence,
        _route_sample_count=detection.sample_count,
        _route_status=detection.status,
        _route_method=detection.method,
        _route_reason=reason,
        _route_warnings=warnings,
        _route_auto_detected=auto_detected,
    )


def resolve_media_route(
    source: Path | str,
    config: Config,
    *,
    media_sha256: str | None = None,
    reusable_vtt: bool = False,
    detector: LanguageDetector | None = None,
) -> Config:
    """Resolve one media item at the orchestration boundary.

    Explicit providers never invoke language detection.  A reusable VTT also
    bypasses detection because it is already the selected transcript source.
    """

    detection = LanguageDetectionResult(status="bypassed", method="explicit-provider")
    if reusable_vtt:
        return _route_config(
            config,
            provider="existing",
            model=config.transcription_model,
            language=config.transcription_language,
            detection=detection,
            reason="reused-existing-vtt",
        )
    if config.transcription_provider != "auto":
        return _route_config(
            config,
            provider=config.transcription_provider,
            model=config.transcription_model,
            language=config.transcription_language,
            detection=detection,
            reason="explicit-provider",
        )

    configured_language = _normalise_language(config.transcription_language)
    if configured_language != "auto":
        configured = LanguageDetectionResult(
            detected_language=configured_language,
            status="configured",
            method="explicit-language",
        )
        if configured_language == "ru":
            return _resolve_russian_route(config, configured, auto_detected=True)
        return _route_config(
            config,
            provider="auto",
            model=config.transcription_model,
            language=configured_language,
            detection=configured,
            reason="configured-language",
            auto_detected=True,
        )

    detection = detect_language(
        source,
        media_sha256=media_sha256,
        cache_dir=config.cache_dir,
        device=config.docling_device,
        detector=detector,
    )
    language = detection.detected_language or "auto" if detection.is_confident else "auto"
    if detection.detected_language == "ru" and detection.is_confident:
        russian_confident = (
            detection.confidence is not None
            and detection.confidence >= RUSSIAN_CONFIDENCE_THRESHOLD
            and (
                detection.vote_share is None
                or detection.vote_share >= RUSSIAN_VOTE_THRESHOLD
            )
            and (detection.margin is None or detection.margin >= RUSSIAN_MARGIN_THRESHOLD)
            and detection.sample_count
            >= min(MIN_USABLE_SAMPLES, detection.attempted_sample_count)
        )
        if russian_confident:
            return _resolve_russian_route(config, detection, auto_detected=True)

    reason = "confident-non-russian" if detection.is_confident else "language-uncertain-or-mixed"
    return _route_config(
        config,
        provider="auto",
        model=config.transcription_model,
        language=language,
        detection=detection,
        reason=reason,
        auto_detected=True,
    )


def _resolve_russian_route(
    config: Config,
    detection: LanguageDetectionResult,
    *,
    auto_detected: bool,
) -> Config:
    available, availability_reason = gigaam_route_available(config)
    if available:
        return _route_config(
            config,
            provider="gigaam",
            model="v3_e2e_rnnt",
            language="ru",
            detection=detection,
            reason="confident-russian" if detection.status == "complete" else "configured-russian",
            auto_detected=auto_detected,
        )
    warning = (
        "Auto language routing selected Russian, but GigaAM is unavailable "
        f"({availability_reason}); falling back to Docling Whisper auto."
    )
    return _route_config(
        config,
        provider="auto",
        model=config.transcription_model,
        language="ru",
        detection=detection,
        reason="gigaam-unavailable-fallback",
        warnings=(warning,),
        auto_detected=auto_detected,
    )
