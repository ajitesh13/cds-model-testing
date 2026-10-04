from thalamus.serialize import serialize


def test_deterministic(patient):
    first = serialize(patient)
    for _ in range(10):
        again = serialize(patient)
        assert again.text == first.text and again.record_hash == first.record_hash
    assert len(first.record_hash) == 64


def test_row_ids_unique_and_complete(patient):
    s = serialize(patient)
    ids = [line.split("]")[0][1:] for line in s.text.splitlines() if line.startswith("[")]
    assert len(ids) == len(set(ids)) == len(s.rows)


def test_afi_row(patient):
    s = serialize(patient)
    assert "(AFI) of 3 cm" in s.rows["E7.IMAGING.1"].text
    assert "[E7.IMAGING.1] An ultrasound" in s.text


def test_layout(patient):
    t = serialize(patient).text
    assert t.startswith("=== COMPUTED BY CODE")
    assert "=== E7 | 2023-05-15 | Obstetrics & Gynecology | outpatient | Dr. Jennifer Park ===" in t
    assert t.index("[P.ALLERGIES.1]") < t.index("=== E1 |")
    assert t.index("=== E1 |") < t.index("=== E8 |")
    assert "[E7.CHIEF_COMPLAINT.1] Decreased fetal movements" in t
    assert "[P.HOME_MEDICATIONS.1]" in t


def test_no_generator_metadata(patient):
    t = serialize(patient).text
    for bad in ("Generation Seed", "Gen. Method", "Order:"):
        assert bad not in t
