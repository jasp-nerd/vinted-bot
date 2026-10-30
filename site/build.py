"""Refresh the files the landing site serves straight from the repo.

The site is plain HTML, CSS and JS and needs no build to serve. This only copies the
installers and the AI guide from the repo root, so https://vinted-sniper.jaspnerd.dev/install.sh
always matches the script on the branch you deploy from. Run it before deploying:

    python3 site/build.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent

for name in ("install.sh", "install.ps1", "llms.txt"):
    shutil.copyfile(ROOT / name, SITE / name)
    print(f"copied {name}")
