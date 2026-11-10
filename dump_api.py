import json
from app.main import app

spec = app.openapi()
schemas = spec.get("components", {}).get("schemas", {})



def resolve(node, depth=0):
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            if depth > 4:
                return name
            return {"_schema": name, **resolve(schemas.get(name, {}), depth + 1)}
        out = {}
        for k, v in node.items():
            if k in ("title", "description", "examples") and isinstance(v, str):
                continue
            out[k] = resolve(v, depth)
        return out
    if isinstance(node, list):
        return [resolve(i, depth) for i in node]
    return node


lines = []
for path, methods in spec["paths"].items():
    for method, op in methods.items():
        body = op.get("requestBody", {}).get("content", {})
        ok = {c: r for c, r in op.get("responses", {}).items() if c.startswith("2")}
        lines.append(f"{method.upper()} {path}")
        if body:
            lines.append("  IN:  " + json.dumps(resolve(body), separators=(",", ":")))
        if ok:
            lines.append("  OUT: " + json.dumps(resolve(ok), separators=(",", ":")))

with open("api_contract.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("Wrote api_contract.txt")
