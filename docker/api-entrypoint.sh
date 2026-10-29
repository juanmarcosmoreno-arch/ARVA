#!/bin/sh
set -e
# The migration step keeps a failure in <data folder>/logs/errors.jsonl with its traceback (app.services.startup).
python -m app.services.startup migrate
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
