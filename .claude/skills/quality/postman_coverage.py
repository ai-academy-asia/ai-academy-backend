"""Check aiaa-api.postman_collection.json against the app's real routes.

Reports: routes missing from the collection, requests pointing at no route,
{{variables}} used but not defined, and broken raw JSON bodies. Exit 1 on any.
Needs DATABASE_URL set (any value works; nothing connects).
"""
import json
import re
import sys

sys.path.insert(0, ".")
from app import create_app  # noqa: E402

COLLECTION = "aiaa-api.postman_collection.json"


def _requests(items, path=""):
    for item in items:
        if "item" in item:
            yield from _requests(item["item"], f"{path}/{item['name']}")
        else:
            yield path, item


def main() -> int:
    with open(COLLECTION, encoding="utf-8") as fh:
        collection = json.load(fh)
    app = create_app()
    rules = [(r, re.compile("^" + re.sub(r"<[^>]+>", r"[^/]+", r.rule) + "$"))
             for r in app.url_map.iter_rules() if r.endpoint != "static"]
    defined = {v["key"] for v in collection.get("variable", [])} | {"base_url"}
    problems, have = [], []

    for path, item in _requests(collection["item"]):
        request = item["request"]
        raw = request["url"]["raw"] if isinstance(request["url"], dict) else request["url"]
        for var in re.findall(r"\{\{(\w+)\}\}", json.dumps(item)):
            if var not in defined:
                problems.append(f"undefined variable {{{{{var}}}}} in {path}/{item['name']}")
        body = request.get("body", {})
        if body.get("mode") == "raw":
            try:
                json.loads(re.sub(r"\{\{\w+\}\}", "1", body["raw"]))
            except ValueError as exc:
                problems.append(f"bad JSON body in {path}/{item['name']}: {exc}")
        if not raw.startswith("{{base_url}}"):
            continue  # e.g. the direct PosAPI requests
        url = re.sub(r"\{\{\w+\}\}", "1", raw.replace("{{base_url}}", "").split("?")[0])
        have.append((request["method"], url))
        if not any(request["method"] in r.methods and rx.match(url) for r, rx in rules):
            problems.append(f"no route for {request['method']} {url} ({path}/{item['name']})")

    for rule, rx in rules:
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            if not any(m == method and rx.match(u) for m, u in have):
                problems.append(f"route missing from collection: {method} {rule.rule}")

    for line in problems:
        print(line)
    print(f"{len(have)} requests checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
