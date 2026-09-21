from __future__ import annotations

import os
import sysconfig

_stdlib_http_dir = os.path.join(sysconfig.get_paths()["stdlib"], "http")
if _stdlib_http_dir not in __path__:
    __path__.append(_stdlib_http_dir)
_stdlib_init = os.path.join(_stdlib_http_dir, "__init__.py")
with open(_stdlib_init, "rb") as _f:
    _code = compile(_f.read(), _stdlib_init, "exec")
exec(_code, globals(), globals())
del _f, _code, _stdlib_init, _stdlib_http_dir
