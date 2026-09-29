"""Check aiaa-api.postman_collection.json against the app's real routes.

Reports routes missing from the collection, requests that hit no route,
{{variables}} used but not defined, and broken raw JSON bodies. Exit 1 on any.
Runs from any directory; needs DATABASE_URL set (any value — nothing connects).
"""
import json
import re
import sys
from pathlib import Path

from werkzeug.exceptions import HTTPException

REPO = Path(__file__).resolve().parents[1]
COLLECTION = REPO / "aiaa-api.postman_collection.json"
_VAR = re.compile(r"\{\{(\w+)\}\}")


def _requests(items, path=""):
    for item in items:
        if "item" in item:
            yield from _requests(item["item"], f"{path}/{item['name']}")
        else:
            yield f"{path}/{item['name']}", item


def _body_problem(request):
    body = request.get("body", {})
    if body.get("mode") != "raw":
        return None
    try:
        json.loads(_VAR.sub("1", body["raw"]))
    except ValueError as exc:
        return str(exc)
    return None


def check(collection: dict, app) -> list:
    """Every problem found, as a sentence. Empty list = the collection is complete."""
    adapter = app.url_map.bind("localhost")
    defined = {v["key"] for v in collection.get("variable", [])} | {"base_url"}
    covered, problems = set(), []

    for name, item in _requests(collection["item"]):
        request = item["request"]
        problems += [f"undefined variable {{{{{v}}}}} in {name}"
                     for v in sorted(set(_VAR.findall(json.dumps(item))) - defined)]
        if (bad := _body_problem(request)) is not None:
            problems.append(f"bad JSON body in {name}: {bad}")
        raw = request["url"]["raw"] if isinstance(request["url"], dict) else request["url"]
        if not raw.startswith("{{base_url}}"):
            continue  # the direct PosAPI requests
        path = _VAR.sub("1", raw[len("{{base_url}}"):].split("?")[0])
        # Resolve exactly as Flask would, so /x/summary never counts for /x/<int:id>.
        try:
            rule, _ = adapter.match(path, method=request["method"], return_rule=True)
        except HTTPException:
            problems.append(f"no route for {request['method']} {path} ({name})")
            continue
        covered.add((rule.rule, request["method"]))

    problems += [f"route missing from collection: {method} {rule.rule}"
                 for rule in app.url_map.iter_rules() if rule.endpoint != "static"
                 for method in sorted(rule.methods - {"HEAD", "OPTIONS"})
                 if (rule.rule, method) not in covered]
    return problems


def main() -> int:
    sys.path.insert(0, str(REPO))
    from app import create_app

    with COLLECTION.open(encoding="utf-8") as fh:
        problems = check(json.load(fh), create_app())
    for line in problems:
        print(line)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
