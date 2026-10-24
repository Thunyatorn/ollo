"""Create a Spacetime identity for the worker and save its token to worker/.worker-token (git-ignored, mode 600).

  .venv/bin/python scripts/make_identity.py [http://127.0.0.1:3000]
Then, as the admin (the identity that published the module):
  spacetime call <db> grant_role '"0x<identity>"' '"worker"' '{"none":[]}' --server <server>
"""
import os
import sys
from pathlib import Path

import httpx

url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3000").rstrip("/")
path = Path(__file__).resolve().parent.parent / ".worker-token"
if path.exists():
    sys.exit(f"{path} already exists; delete it first if you really want a new identity")
r = httpx.post(f"{url}/v1/identity", timeout=10)
r.raise_for_status()
d = r.json()
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(d["token"])
print(f"identity 0x{d['identity']}\ntoken saved to {path}")
