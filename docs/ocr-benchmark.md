# First-page OCR benchmark

The first native-extraction baseline has been measured on the current Windows
coding host (Python 3.9.7, PyMuPDF 1.26.5). This is not the Mac that hosts the
website tunnel, so OCR candidate measurements are still pending there. PaddleOCR
and Swift/macOS Vision are unavailable on this host.

## Comparison set

| Class | Local fixture | Purpose |
| --- | --- | --- |
| Handwriting scan | `datacompiler-core/tests/fixtures/polish.pdf` | Primary case; Polish handwriting, OCR word boxes and language detection |
| Printed scan | `datacompiler-core/examples/scan-skewed-lines.pdf` | Printed OCR, skew tolerance and box coverage |
| Native text | `datacompiler-core/examples/spreadsheet.pdf` | Fast PyMuPDF extraction baseline and layout boxes |

## Initial measurements

| Fixture | Native words on page 1 | PyMuPDF open + extraction |
| --- | ---: | ---: |
| `polish.pdf` | 0 | 0.0384 s |
| `scan-skewed-lines.pdf` | 0 | 0.0042 s |
| `spreadsheet.pdf` | 128 | 0.0140 s |

The two scans contain no native text, as expected. These measurements only
cover native extraction and are not the end-to-end diagnostic latency.

Before the first run, visually confirm that the chosen fixtures still represent
the class named in this table. If they do not, replace the fixture and note why.

Run the comparison from this repository on the Mac host with the project's
Python 3.11+ environment:

```sh
python tools/benchmark_ocr.py ../datacompiler-core/tests/fixtures/polish.pdf \
  ../datacompiler-core/examples/scan-skewed-lines.pdf \
  ../datacompiler-core/examples/spreadsheet.pdf \
  --engine all --runs 3
```

On macOS, `--engine all` compiles and starts the included Vision worker once,
then sends each rendered page to it repeatedly. PaddleOCR measurements are
included only if PaddleOCR is installed in that Python environment. Use
`--paddle-language` and `--vision-language` to specify the language packs
available on the test machine.

## Record per candidate

| Engine / mode | Cold start | Warm page latency | Text quality / errors | Language | Box coverage and reading order | Peak memory | Notes |
| --- | ---: | ---: | --- | --- | --- | ---: | --- |
| macOS Vision, fast | pending on Mac | — | — | — | line boxes | — | Candidate |
| PaddleOCR | pending on Mac | — | — | — | detector output | — | Candidate |
| Existing VLM route | — | — | — | — | — | — | Handwriting text reference; boxes may be absent |
| PyMuPDF native extraction | — | — | — | — | — | — | Native-text baseline only |

Run each candidate on page one, once cold and at least three times warm. Record
the OCR engine/model version, machine model, macOS version, image render DPI,
and whether the model had to download. For handwriting, compare transcription
against a human-corrected reference and separately score whether boxes cover
the visible words; do not treat one score as a proxy for the other.

## Decision record

- Default scan detector: pending Mac benchmark
- Handwriting text source: pending
- Fallback OCR/VLM: pending
- First-page warm-latency target: set after baseline
- Accuracy/box-coverage acceptance thresholds: set after inspecting the sample
