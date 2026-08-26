# Tools Layout

Helper scripts are grouped here to keep the project root focused on runnable entrypoints.

- `tools/checks`: one-off inspection and verification scripts
- `tools/debug`: debug and analysis helpers
- `tools/ad_hoc`: experimental, quick-run, or simplified helper scripts

Each tool subdirectory includes a `sitecustomize.py` bootstrap so scripts can still import project modules when executed directly.
