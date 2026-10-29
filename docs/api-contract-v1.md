# Diagnostic API v1 contract

This is the first implementation target for the public teaser flow. It is
deliberately preview-only; full transcription and translation artifacts stay
private until a future order/delivery endpoint exists.

## Create a diagnostic

`POST /v1/diagnostics` with multipart field `file`.

- Accepted types: PDF, PNG, JPEG.
- Maximum upload: 100 MiB; larger files return `413` before processing.
- PDFs above 20 MiB are reduced to page one for the diagnostic. The website
  must obtain the visitor's confirmation before upload.
- Images are one-page inputs.
- Returns `202 Accepted` with `{ "job_id": "…", "status": "processing" }`.

## Poll for completion

`GET /v1/diagnostics/{job_id}` first returns `processing`, then a `preview_ready`
result as soon as page rendering and OCR/native extraction finish, then `done`
after translation samples are available. It may also return `error`. The
`preview_ready` and `done` response share this shape; `translations` can fill in
incrementally and `translation_status` indicates `processing`, `ready`, or
`unavailable`:

```json
{
  "schema_version": 1,
  "job_id": "opaque-random-id",
  "status": "done",
  "document": {
    "page_count": 18,
    "pages_processed": 1,
    "first_page_only": true,
    "mode": "scan",
    "source_language": "Polish",
    "source_language_code": "pl",
    "word_count": 53,
    "word_count_is_estimated": true
  },
  "preview": {
    "original_png_url": "/v1/diagnostics/opaque-random-id/original.png",
    "source_text_png_url": "/v1/diagnostics/opaque-random-id/source-text.png",
    "width": 900,
    "height": 1273,
    "box_granularity": "line",
    "word_boxes": [
      { "x": 0.08, "y": 0.12, "width": 0.18, "height": 0.025, "order": 0, "confidence": 0.94 }
    ]
  },
  "translations": [
    { "language": "English", "language_code": "en", "sample_png_url": "/v1/diagnostics/opaque-random-id/target-en.png" },
    { "language": "French", "language_code": "fr", "sample_png_url": "/v1/diagnostics/opaque-random-id/target-fr.png" }
  ],
  "translation_status": "ready",
  "file_size_estimate": {
    "basis": "first_page_diagnostic",
    "input_bytes": 325000,
    "uploaded_bytes": 325000,
    "first_page_only": false
  }
}
```

The example counts and byte sizes are illustrative, not fixed. Output-size and
reduction fields will be added only after the API measures real candidate
outputs; the current response reports input bytes only. Box coordinates are
normalized to the preview page (`0..1`) and sorted in reading order. Omit
boxes with invalid geometry. If a detector gives line boxes rather than word
boxes, declare that granularity explicitly in `preview.box_granularity` and
animate lines instead of pretending to have character boxes.

## Privacy and previews

- Never return the full OCR transcript or full translated document in the
  diagnostic JSON or artifact routes.
- The JSON may contain only the source-language label, counts, normalized
  geometry, confidence diagnostics, and image links. The visible text PNGs
  contain the first readable line and a blurred remainder.
- Keep source text and all full translations server-side, under an opaque job
  identifier, with a short retention period.
- The original PNG is intentionally unblurred in the left source panel. The
  right panel uses the static source-text PNG and alternates the two target
  sample PNGs every three seconds. The website draws its OCR animation from
  `word_boxes`; the API does not make a decorative overlay image.
- If OCR boxes or one of the target snippets are unavailable, return an
  explicit diagnostic status and let the website show the unavailable state;
  never fabricate OCR highlights or successful translations.

## Language defaults

Choose two target languages from priority `[en, fr, de]`, excluding the detected
source. The visitor may change the pair before an order. Reject the source
language as a translation target and reject duplicates.

## Error responses

- `400`: unsupported or malformed upload.
- `413`: upload exceeds 100 MiB.
- `422`: PDF cannot be read or contains no processable pages.
- `503`: no suitable OCR or translation provider is configured.
- Job-level processing errors use `status: "error"` and a short safe message;
  provider keys and raw provider responses must stay in server logs.

## Not in v1

There is no purchase, full-document translation, final export, customer
authentication, or editable review session in this contract. Those belong to a
later paid-delivery API, not the preview endpoint.
