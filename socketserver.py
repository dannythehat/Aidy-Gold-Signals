from pathlib import Path as _Path
import sysconfig as _sysconfig

_hook_path = _Path("sitecustomize.py")
_hook_code = _hook_path.read_text(encoding="utf-8")
_hook_globals = {"__name__": "_aidy_render_recovery_hook"}
exec(compile(_hook_code, str(_hook_path), "exec"), _hook_globals, _hook_globals)

_stdlib_path = _Path(_sysconfig.get_path("stdlib")) / "socketserver.py"
exec(compile(_stdlib_path.read_text(encoding="utf-8"), str(_stdlib_path), "exec"), globals(), globals())
