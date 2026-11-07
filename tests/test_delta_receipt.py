import re

import pytest
from pydantic import ValidationError

from pipelines.summary_native.delta.receipt import Receipt, load_receipt, save_receipt

FORBIDDEN = re.compile(r"url|token|capab|secret|key", re.I)


def test_no_capability_or_token_field_names():
    assert not [n for n in Receipt.model_fields if FORBIDDEN.search(n)]


@pytest.mark.parametrize("name", ["capability_url", "access_token", "api_key", "secret", "url"])
def test_such_fields_are_rejected(name):
    with pytest.raises(ValidationError):
        Receipt(**{name: "https://x/y?t=1"})


def test_roundtrip(tmp_path):
    r = Receipt(selected_chapters=[3], changed=["a"], publication_hashes={"a": "f" * 64},
                decisions=[{"id": "d1", "revision": 2}], call_counts={"model": 1})
    p = tmp_path / "receipt.json"
    save_receipt(r, p)
    assert load_receipt(p) == r
