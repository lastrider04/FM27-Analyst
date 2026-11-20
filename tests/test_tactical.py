"""Tactical Effectiveness formulas against the game's own screens (FM27 build a80b7a733c8d, 2 Feb 2032).

Each record is bytes +0x10..+0x3a of a player's TE record as read from memory (the pointers before it don't feed
any formula). Expected dials are Training > Tactical Effectiveness for that XI; Soeda's full values are from his
Development > Tactical Effectiveness screen.
"""
from analytics.tactical import AREAS, compute, dial, team

XI = [  # (player, record inputs, dials: areas, comprehension, ability, buy-in, next match)
    ("Longoni", "5f3e3e634242634545633e3e634141634141634141634141635243005907005757622b3533325f634e6464", (10, 6, 9, 8, 8)),
    ("Desabato", "4a4d4d634e4e635656634545634e4e634e4e634e4e634e4e63524e0059070056564c323a3a4757614e6455", (10, 5, 8, 8, 7)),
    ("Cubarsi", "5456566356566360606356566355556355556355556355556352380059070047474a2c363d505e634e645a", (10, 5, 9, 7, 7)),
    ("Owen", "595151635252635b5b635454635151635151635151634c4c635238005907004040442b3936505c634e645a", (10, 6, 9, 6, 7)),
    ("Kerkez", "4f5151635858635c5c634d4d634d4d634d4d634d4d63575763524e005907005f5f5434363c5d56634e645a", (10, 5, 8, 8, 7)),
    ("Eichhorn", "4f4b4b634646634b4b634040634747634747634747634343635238005907005151512f3c354455624e645a", (9, 5, 8, 7, 7)),
    ("Bouaddi", "595656635252635d5d634545634949634949634949634b4b635238005907004f4f44353637445c614e6455", (10, 6, 8, 7, 7)),
    ("Soeda", "3f5050634d4d635757635d5d634848634848634848632f2f625264005907004141492c3c344738404e6450", (9, 4, 3, 6, 6)),
    ("Doue", "4a4646634848634e4e6361616348486348486348486353536352640059070053535130353a47575d4e645f", (9, 4, 8, 7, 7)),
    ("Endrick", "4a4646634848634e4e634646634848634848634848633c3c6352210059070043434d29353643565e4e6464", (9, 5, 8, 6, 8)),
    ("Williams-Barnett", "444444634545634c4c63505063454563454563454563545463524e0059070060605137383a3253624e645a", (9, 4, 8, 8, 7)),
]


def rec(hexstr: str) -> bytes:
    return bytes(16) + bytes.fromhex(hexstr) + bytes(5)


def test_team_screen_dials():
    for name, h, want in XI:
        c = compute(rec(h))
        got = tuple(dial(c[k]) for k in ("understanding", "comprehension", "ability", "buy_in", "next_match"))
        assert got == want, name


def test_soeda_detail_screen():
    c = compute(rec(XI[7][1]))
    i = c["inputs"]
    assert (c["overall"], c["understanding"], c["buy_in"], c["ability"], c["next_match"]) == (76, 95, 66, 36, 67)
    assert (i["tactical_ability"], c["complexity"], i["capability"], i["role_suitability"]) == (63, 79, 56, 64)
    assert (i["managerial_support_ip"], c["relationships"], i["manager_tendencies"]) == (65, 56, 89)
    assert (i["opposition_report"], i["opposition_knowledge"], i["next_match_factor"]) == (78, 100, 80)
    assert [a["value"] for a in c["areas"]] == [99, 97, 100, 100, 94, 94, 94, 78]
    assert [a["key"] for a in c["areas"]] == [a[0] for a in AREAS]


def test_team_average():
    t = team([compute(rec(h)) for _, h, _ in XI])
    assert t["overall"] == round(sum(compute(rec(h))["overall"] for _, h, _ in XI) / 11, 1)
    assert len(t["areas"]) == 8


def test_phone_can_open_tactics():
    from web import remote
    for method, path in (("GET", "/api/tactical"), ("GET", "/api/tactical/2002078810"), ("POST", "/api/tactical/read")):
        assert remote.allowed(method, path), (method, path)
    assert not remote.allowed("DELETE", "/api/tactical/1")


def test_ui_stamp_follows_page_files():
    """An open phone app reloads itself when this changes, so it must track the page files."""
    from web import app as webapp
    stamp = webapp._ui_stamp()
    assert stamp >= int((webapp.STATIC / "app.js").stat().st_mtime)
