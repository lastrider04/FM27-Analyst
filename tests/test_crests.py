"""Club crests from an FM27 logo pack (web/crests.py), with a tiny fake pack."""
from fastapi.testclient import TestClient

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def pack(tmp_path):
    g = tmp_path / "graphics"
    clubs = g / "logos" / "Pack" / "Men" / "England" / "Clubs"
    clubs.mkdir(parents=True)
    (clubs / "TCM1_676.png").write_bytes(PNG)
    (clubs / "TCM1_676_icon.png").write_bytes(PNG)
    (clubs / "config.xml").write_text('<record>\n<list id="maps">\n'
                                      '<record from="TCM1_676_icon" to="graphics/pictures/club/676/icon"/>\n'
                                      '<record from="TCM1_676" to="graphics/pictures/club/676/logo"/>\n'
                                      '<record from="missing" to="graphics/pictures/club/9/logo"/>\n</list></record>')
    plain = g / "logos" / "Other" / "clubs"
    plain.mkdir(parents=True)
    (plain / "1234.png").write_bytes(PNG)
    return g


def test_index_reads_config_mappings_and_plain_names(tmp_path):
    from web import crests
    idx = crests.build([pack(tmp_path)])
    assert idx["676"].endswith("TCM1_676.png")          # the logo, not the icon
    assert idx["1234"].endswith("1234.png") and "9" not in idx


def test_crest_route(tmp_path, monkeypatch):
    import app_config
    from web import app as web_app, crests, remote
    g = pack(tmp_path)
    monkeypatch.setattr(app_config, "DATA", tmp_path / "data")
    monkeypatch.setattr(crests, "graphics_dirs", lambda: [g])
    monkeypatch.setattr(crests, "_index", crests._load_or_build())
    c = TestClient(web_app.app)
    r = c.get("/api/crest/676")
    assert r.status_code == 200 and r.content == PNG
    assert c.get("/api/crest/5").status_code == 404
    assert remote.allowed("GET", "/api/crest/676") and not remote.allowed("GET", "/api/crest/../x")
