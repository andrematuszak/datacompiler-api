# Fast website diagnostic

## Decision

Implement the website-facing service in `datacompiler-api`, separate from both
the static `datacompiler-web` project and the full `datacompiler-core` pipeline.
The public site should not grow server code or provider secrets, while the
website's teaser path should not need to import the full review, rebuilding,
and export workflow.

Keep `datacompiler-core` as the authoritative full-processing and human-review
tool. The new API should use independent, narrowly scoped OCR, translation,
preview, and size-diagnostic components. Avoid importing `executer_pipeline`
into the new service.

## Preview flow

1. Accept a PDF or image. For PDFs above the current 20 MiB preview threshold,
   ask the visitor before uploading and process only page one. Keep a separate
   hard upload limit and explain it when reached.
2. For native-text PDFs, extract positioned words directly from the first page.
   For scans, run a fast OCR detector that returns text boxes and confidences;
   benchmark candidate engines on the real Polish handwriting sample before
   selecting the default. The animation must use actual detector boxes, not a
   decorative scan line presented as OCR.
3. Return the source preview, detected text, word/language diagnostics, box
   coordinates, and file-size diagnostics as soon as that first-page pass is
   complete. Mark page-limited counts and file-size figures as estimates.
4. Translate only the readable first line for the teaser. Render the source text
   as a static left-hand preview and the two target-language snippets on the
   right, alternating every three seconds. Blur the remainder with a generated
   neutral text texture; do not translate hidden text just to fill the preview.
5. Generate complete selected-language and selected-format documents only in
   the post-purchase processing job. This avoids doing the expensive full
   translation before the visitor has chosen an offer.

## Default target languages

Use the priority order English, French, German and exclude the detected source
language, taking the first two remaining choices. This gives Polish → English +
French, French → English + German, and English → French + German. Let visitors
change the pair before purchase.

## Multi-selection controls

Use a compact checkbox popover, not a native `<select multiple>`. Its closed
state should show selected chips when there is room, then collapse to a concise
summary such as `English + German` or `PDF (text) + XLIFF`. Reopening it should
show all selected rows checked and tinted blue. Keep the control keyboard
accessible, and calculate prices from the full selected set.

For scan handwriting, transcription formats may include `PDF (layer)` and
default to it. Translation formats must never offer that option because the
VLM-based translation has no source-image layer to preserve. Offer XLIFF on both
sides.

## File-size diagnostic

Compare byte sizes from the diagnostic input and the estimated output generated
from the selected format, not only a later purchased file. Report the input and
output byte values with the reduction percentage. Clamp the percentage to zero
when the estimated output is larger. When only the first page was analyzed,
label the figures as estimates for that page rather than comparing a one-page
output to the full uploaded file.

## Migration

1. Benchmark OCR speed, handwriting quality, and box placement on native text,
   printed scans, and `polish.pdf`.
2. Define and implement the preview API contract and artifacts in this repo.
3. Update `datacompiler-web` to use the new diagnostic response and multi-select
   values.
4. Keep full document delivery as a separate queued job, initially reusing the
   stable full-processing path until the new export service is ready.
5. Switch the Cloudflare Tunnel only after the new API passes those comparisons.
