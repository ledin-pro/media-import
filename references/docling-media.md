# Docling Media

Use Docling's `AsrPipeline` for audio and `VideoPipeline` for video. The
`WHISPER_TURBO` preset auto-selects MLX Whisper on Apple Silicon when available
and Native Whisper elsewhere. Forced providers use `WHISPER_TURBO_MLX` or
`WHISPER_TURBO_NATIVE`.

Video defaults to scene-change sampling, two cuts per minute, at most 40 frames,
generated frame images, and no diarization. Keep Docling's structured
`DoclingDocument` as the canonical intermediate.

Iterate the item tree in Docling order. Keep `TrackSource` timing in the manifest,
strip visible time labels from Markdown, and replace picture positions with OCR
text when frame mode includes text. Do not implement a second sampler or timeline.

## GigaAM v3

Provider `gigaam` uses the public `docling-gigaam` audio and video format-option
factories before any Whisper preset is resolved. It preserves the same document
timeout, accelerator choice, artifacts path, converter cache, shared model cache,
and video sampling settings. GigaAM's provider default is `v3_e2e_rnnt`; the
default for all other providers remains `whisper_turbo`.

GigaAM v3 is Russian-focused. Accept language `auto`, `ru`, `rus`, or `russian`
only. The checksum-verified official model is downloaded during the first real
conversion, not preflight. Long-form segmentation uses local Silero and requires no service
or API token. On Apple Silicon, MPS can be selected, but unsupported Silero or
model operations may execute on CPU.
