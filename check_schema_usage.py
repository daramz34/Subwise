"""Reports which Pydantic schemas in app/schemas.py the app actually uses.

Run from the project root:   python check_schema_usage.py
Add --strict to exit with an error when unused schemas exist.

A schema counts as used if code in app/ (outside schemas.py) mentions it, or if a used
schema refers to it (for example CategoryOut inside SubscriptionOut, or a base class).
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMAS = ROOT / "app" / "schemas.py"
SEARCH_DIRS = [ROOT / "app"]


def names_in(node) -> set[str]:
    found = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            found.add(n.id)
        elif isinstance(n, ast.Attribute):
            found.add(n.attr)
        elif isinstance(n, ast.alias):
            found.add(n.name)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            found.add(n.value)  # quoted forward references
    return found


def main() -> int:
    tree = ast.parse(SCHEMAS.read_text(encoding="utf-8"))
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}

    used_outside: set[str] = set()
    for folder in SEARCH_DIRS:
        for path in folder.rglob("*.py"):
            if path.resolve() == SCHEMAS:
                continue
            try:
                used_outside |= names_in(ast.parse(path.read_text(encoding="utf-8")))
            except SyntaxError:
                print(f"skipped (syntax error): {path}")
    used_outside &= classes.keys()

    # a schema used by a used schema is used too
    used = set(used_outside)
    queue = list(used)
    while queue:
        for dep in names_in(classes[queue.pop()]) & classes.keys():
            if dep not in used:
                used.add(dep)
                queue.append(dep)

    direct = [n for n in classes if n in used_outside]
    indirect = [n for n in classes if n in used and n not in used_outside]
    unused = [n for n in classes if n not in used]

    print(f"{len(classes)} schemas: {len(direct)} used by code, "
          f"{len(indirect)} used only inside other schemas, {len(unused)} UNUSED\n")
    if unused:
        print("UNUSED:")
        for name in unused:
            print(f"  - {name}")
    return 1 if unused and "--strict" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())