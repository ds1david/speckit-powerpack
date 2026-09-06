"""SpecKit PowerPack."""

__version__ = "0.1.0.dev0"

# Keep Playwright CLI browser-attach semantics centralized and aligned with the
# current documented global-session option ordering.
from . import playwright_cli_compat as _playwright_cli_compat
from . import playwright_eval_compat as _playwright_eval_compat

_playwright_cli_compat.apply()
_playwright_eval_compat.apply()
