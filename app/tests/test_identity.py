from app.utils.identity import normalize_upn, normalize_upns


def test_normalize_upn_trims_and_lowercases():
    assert normalize_upn("  Jane.Doe@TaxConsulting.co.za ") == "jane.doe@taxconsulting.co.za"


def test_normalize_upns_deduplicates_and_ignores_invalid_values():
    assert normalize_upns([
        "Jane.Doe@TaxConsulting.co.za",
        " jane.doe@taxconsulting.co.za ",
        None,
        "not-an-email",
    ]) == ["jane.doe@taxconsulting.co.za"]
