from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/is-it-nerfed/skills/is-it-nerfed/scripts"
sys.path.insert(0, str(SCRIPTS))
