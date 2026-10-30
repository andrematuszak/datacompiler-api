# DataCompiler API

This repository contains a prototype lightweight API for fast, preview-only
document diagnostics. It runs independently of the full `datacompiler-core`
processing and review pipeline.

The API remains server-side: provider keys belong in its local environment,
never in `datacompiler-web`. The public site stays a static Cloudflare Pages
project.

See [the fast diagnostic architecture](docs/fast-diagnostic.md), [the
implementation roadmap](docs/ROADMAP.md), and [the v1 API contract](docs/api-contract-v1.md).
The live website still calls `datacompiler-core/main.py`; this prototype has
not been switched into production. Use [the OCR benchmark sheet](docs/ocr-benchmark.md)
and `tools/benchmark_ocr.py` to compare engines on the Mac that hosts the
tunnel.

## Run locally on the Mac host

Use Python 3.11 or newer. Scan OCR uses macOS Vision and compiles the included
Swift worker on first use. Add a DeepL key to the server environment to enable
translated teaser samples.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[translation]'
export DEEPL_AUTH_KEY='your-server-side-key'
uvicorn datacompiler_api.app:app --host 127.0.0.1 --port 8000
```

The prototype accepts PDF, PNG, and JPEG uploads at `POST /v1/diagnostics` and
serves progress/results at `GET /v1/diagnostics/{job_id}`. Validate it against
the benchmark set before changing the Cloudflare Tunnel target.
