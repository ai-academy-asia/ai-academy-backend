"""The Postman collection covers every route, and only the routes Flask really resolves."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_postman import COLLECTION, check  # noqa: E402


@pytest.fixture(scope="module")
def collection():
    with COLLECTION.open(encoding="utf-8") as fh:
        return json.load(fh)


def _drop(collection, predicate):
    """A copy of the collection without the requests ``predicate`` matches."""
    trimmed = copy.deepcopy(collection)

    def prune(items):
        kept = []
        for item in items:
            if "item" in item:
                item["item"] = prune(item["item"])
                kept.append(item)
            elif not predicate(item["request"]):
                kept.append(item)
        return kept

    trimmed["item"] = prune(trimmed["item"])
    return trimmed


def test_collection_is_complete(app, collection):
    assert check(collection, app) == []


def test_a_static_path_does_not_cover_its_int_sibling(app, collection):
    # /admin/ebarimt/summary must not stand in for /admin/ebarimt/<int:receipt_id>.
    def receipt_detail(request):
        raw = request["url"]["raw"]
        return request["method"] == "GET" and raw.endswith("/admin/ebarimt/{{receipt_id}}")

    problems = check(_drop(collection, receipt_detail), app)
    assert problems == ["route missing from collection: GET /admin/ebarimt/<int:receipt_id>"]


def test_a_request_flask_would_404_is_reported(app, collection):
    broken = copy.deepcopy(collection)
    broken["item"].append({"name": "Bad", "request": {
        "method": "GET", "url": {"raw": "{{base_url}}/admin/ebarimt/abc/qr"}}})
    assert "no route for GET /admin/ebarimt/abc/qr (/Bad)" in check(broken, app)
