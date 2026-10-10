"""``python -m layasdlc`` entry point.

Present rather than a console script so the CLI works straight from a checkout
(``PYTHONPATH=src python -m layasdlc ...``) without installing an entry point --
one fewer thing to get out of step when the package is reinstalled.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
