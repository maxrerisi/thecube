from pathlib import Path

import pytest

from dukedining.eaccounts import load_csv
from dukedining.receipts import parse_receipts

FIXTURES = Path(__file__).parent / "fixtures"
REAL_DATA = Path(__file__).parent.parent / "data"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def receipts():
    return parse_receipts((FIXTURES / "receipts.txt").read_text())


@pytest.fixture
def ea_rows():
    return load_csv((FIXTURES / "eaccounts.csv").read_text())
