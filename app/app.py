import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CMM_PORT") or os.environ.get("PORT") or "4455")
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=1)
