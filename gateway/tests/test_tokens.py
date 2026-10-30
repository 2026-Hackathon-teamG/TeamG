from shared import tokens

SECRET = "s3cret"


def test_sign_and_verify_roundtrip():
    t = tokens.sign("A-01", 2, SECRET)
    assert t.startswith("pt_A-01_2_")
    assert tokens.verify(t, SECRET) == ("A-01", 2)


def test_rejects_tampered_or_wrong_secret():
    t = tokens.sign("A-01", 2, SECRET)
    assert tokens.verify(t.replace("A-01", "A-02"), SECRET) is None
    assert tokens.verify(t.replace("_2_", "_3_"), SECRET) is None
    assert tokens.verify(t, "other") is None


def test_export_page():
    assert tokens.export_page(None, None, SECRET) == 1
    assert tokens.export_page("3", None, SECRET) == 3
    assert tokens.export_page("0", None, SECRET) == 1
    assert tokens.export_page("x", None, SECRET) == 1
    assert tokens.export_page("1", tokens.sign("A-01", 7, SECRET), SECRET) == 7


def test_rejects_garbage():
    for bad in (None, "", "pt_", "pt_A-01_x_0000000000000000", "hello"):
        assert tokens.verify(bad, SECRET) is None
