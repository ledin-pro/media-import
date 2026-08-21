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
