"""Small helpers with no dependencies of their own."""
from __future__ import annotations


def dig(node, *path):
    """Read a nested value by key/index, or ``None`` if any hop is missing.

    Used for reading fields back out of stored gateway/PosAPI payloads, where the
    shape depends on which protocol version wrote the row — walking with ``[]``
    means a chain of try/except that hides what is really "one field, with
    fallbacks".
    """
    for key in path:
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            return None
    return node
