"""OpenAPI スキーマを出力する（フロントの型生成用）。

    uv run python -m app.export_openapi > ../frontend/openapi.json
"""

import json
import sys

from app.main import app

json.dump(app.openapi(), sys.stdout, ensure_ascii=False, indent=2)
sys.stdout.write("\n")
