from datetime import date


def enc(patient, n):
    return next(e for e in patient.encounters if e.index == n)


def test_eight_encounters(patient):
    assert len(patient.encounters) == 8
    assert [e.index for e in patient.encounters] == list(range(1, 9))


def test_e7_date(patient):
    assert enc(patient, 7).date == date(2023, 5, 15)


def test_e3_department(patient):
    assert enc(patient, 3).department == "Urogynecology"


def test_metadata_fields(patient):
    e = enc(patient, 8)
    assert (e.type, e.attending, e.encounter_id) == ("inpatient", "Dr. David Kim", "11614")


def test_no_modified_in_section_names(patient):
    for e in patient.encounters:
        assert all("modified" not in s.lower() for s in e.sections)
    assert "CHIEF_COMPLAINT" in enc(patient, 1).sections


def test_no_generator_metadata(patient):
    blob = patient.model_dump_json().lower()
    for bad in ("generation seed", "gen. method", "order:", "3736", "template"):
        assert bad not in blob


def test_profile(patient):
    p = patient.profile
    assert p["ALLERGIES"] == ["NKDA"]
    assert p["HOME_MEDICATIONS"] == ["Prenatal vitamin - 1 tablet daily"]
    assert len(p["SURGICAL_HISTORY"]) == 3
    assert p["AGE_AT_FIRST_ENCOUNTER"] == ["Age at First Encounter: 42"]
    assert "Down syndrome" in p["PRIMARY_DIAGNOSES"]


def test_rows(patient):
    e7 = enc(patient, 7)
    assert e7.sections["IMAGING"] == [
        "An ultrasound is performed to assess amniotic fluid volume, which reveals an amniotic fluid index (AFI) of 3 cm."
    ]
    # paragraph + list items split into separate rows
    assert enc(patient, 1).sections["PSH"][0] == "Repeat spontaneous vaginal deliveries (x4)"
    assert len(enc(patient, 1).sections["PMH"]) == 5
