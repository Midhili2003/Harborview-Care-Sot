from sot.core.normalize import CodeMap, NameParser, parse_date, parse_identifier, parse_phone


def test_dates():
    assert str(parse_date("2026-09-14")[0]) == "2026-09-14"
    assert str(parse_date("09/14/2026")[0]) == "2026-09-14"
    assert str(parse_date("9/14/26")[0]) == "2026-09-14"
    assert str(parse_date("14-Sep-2026")[0]) == "2026-09-14"
    assert parse_date("next tuesday")[1]
    assert parse_date("")[0] is None and parse_date("")[1] is None


def test_identifiers():
    assert parse_identifier("rn 551203", r"^RN-\d+$", dash=True) == ("RN-551203", None)
    assert parse_identifier("RN551203", None, dash=True)[0] == "RN-551203"
    assert parse_identifier("E201", r"^E\d{3,}$") == ("E201", None)
    assert parse_identifier("RN-55l203", r"^RN-\d+$")[1]


def test_phone():
    assert parse_phone("(718) 555-0201") == ("718-555-0201", None)
    assert parse_phone("+1 718 555 0201")[0] == "718-555-0201"
    assert parse_phone("555-01")[1]


def test_codes(cfg):
    fac = cfg.code_maps["facility"]
    assert fac.parse("BYS")[0] == "BYS"
    assert fac.parse("Harborview Bayside")[0] == "BYS"
    assert fac.parse("harborview  riverdale ")[0] == "RVD"
    assert fac.parse("Harborview Riverdale Campus")[0] == "RVD"
    assert fac.parse("Downtown")[1]
    assert cfg.code_maps["role"].parse("Certified Nursing Assistant")[0] == "CNA"


def test_names(cfg):
    n = cfg.names
    assert n.split("REYES, SOFIA") == ("SOFIA", "REYES")
    assert n.split("Sofia M. Reyes") == ("Sofia", "Reyes")
    assert n.build(*n.split("Marc Bell"))["_name_key"] == n.build("Marcus", "Bell")["_name_key"]
    assert n.build(*n.split("TORRES-RUIZ, ANGELA"))["_display"] == "Angela Torres-Ruiz"
