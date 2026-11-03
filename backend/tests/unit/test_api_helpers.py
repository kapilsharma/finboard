import pytest
from pydantic import ValidationError

from finboard.api.middleware import _hostname
from finboard.api.schemas import AccountUpdate, CategoryUpdate


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("127.0.0.1:8765", "127.0.0.1"),
        ("LocalHost:5173", "localhost"),
        ("[::1]:8765", "::1"),
        ("[::1]", "::1"),
        ("", ""),
    ],
)
def test_hostname(header: str, expected: str) -> None:
    assert _hostname(header) == expected


def test_patch_keeps_only_sent_fields() -> None:
    assert AccountUpdate.model_validate({"colour": None}).changes() == {"colour": None}
    assert AccountUpdate.model_validate({}).changes() == {}


@pytest.mark.parametrize("field", ["name", "type", "active"])
def test_patch_rejects_null_for_required_account_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        AccountUpdate.model_validate({field: None})


def test_category_parent_can_be_cleared() -> None:
    assert CategoryUpdate.model_validate({"parent_id": None}).changes() == {"parent_id": None}
