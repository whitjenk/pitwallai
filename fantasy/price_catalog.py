# shim: remove when whatsapp/ is retired
import sys as _sys

from core import price_catalog as _module

# Alias this legacy path onto the core module so re-exports AND the frozen
# behaviour snapshot monkeypatches (which patch module globals here) reach the
# same object the logic actually reads.
_sys.modules[__name__] = _module
