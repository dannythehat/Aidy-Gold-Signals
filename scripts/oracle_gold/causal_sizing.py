"""Explicit sensitivity variant of the reviewed Apex source, never an original.

Replace only the two future-close references in open_pos sizing with the known
entry price. All signals, exits, risk settings and original source bytes remain
unchanged. This is a parity probe, not native MT5 or broker qualification.
"""
import ast
import importlib.util
import sys

from scripts.oracle_gold.batch01 import PINS, blob


def causal_sizing_probe(path):
    raw = path.read_bytes()
    if blob(raw) != PINS["engine.py"]:
        raise ValueError("Causal probe requires exact reviewed publisher engine")
    tree = ast.parse(raw)

    class EntrySizing(ast.NodeTransformer):
        def __init__(self):
            self.inside = False
            self.changed = 0

        def visit_FunctionDef(self, node):
            old = self.inside
            self.inside = node.name == "open_pos"
            self.generic_visit(node)
            self.inside = old
            return node

        def visit_Subscript(self, node):
            if (self.inside and isinstance(node.value, ast.Name) and node.value.id == "c"
                    and isinstance(node.slice, ast.Name) and node.slice.id == "i"):
                self.changed += 1
                return ast.copy_location(ast.Name(id="px", ctx=ast.Load()), node)
            return self.generic_visit(node)

    fix = EntrySizing()
    tree = fix.visit(tree)
    if fix.changed != 2:
        raise ValueError("Reviewed sizing seam changed")
    ast.fix_missing_locations(tree)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("oracle_causal_sizing_probe", loader=None))
    sys.modules[module.__name__] = module
    # Exact reviewed blob and exactly two audited AST substitutions above.
    exec(compile(tree, str(path)+":EXPLICIT_CAUSAL_SIZING_VARIANT", "exec"), module.__dict__)  # noqa: S102
    return module
