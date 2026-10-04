from pathlib import Path

import pytest

from thalamus.record import load_record

PATIENT = Path(__file__).resolve().parent.parent / "data" / "patient_2744.txt"


@pytest.fixture(scope="session")
def patient():
    return load_record(PATIENT)
