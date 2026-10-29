# DataCompiler API

This repository is the planned lightweight API for the public DataCompiler site.
It will serve fast, preview-only document diagnostics independently of the
full `datacompiler-core` processing and review pipeline.

The API will remain server-side: provider keys belong in the local service
environment, never in `datacompiler-web`. The public site stays a static
Cloudflare Pages project.

See [the fast diagnostic architecture](docs/fast-diagnostic.md) for the first
service contract and migration plan. This repository currently contains the
architecture decision only; the existing website API remains in
`datacompiler-core/main.py` until the new service is implemented and compared
on representative documents.
