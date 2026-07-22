"""Shared helpers for route blueprints."""
from flask import abort, jsonify, make_response


def json_fail(status, error, **extra):
    """Abort with a JSON error body (raises, never returns)."""
    abort(make_response(jsonify(error=error, **extra), status))
