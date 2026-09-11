"""Language and theme preferences."""

from __future__ import annotations

from app.i18n import translate


def test_translate_en_es():
    assert translate("en", "nav.dashboard") == "Dashboard"
    assert translate("es", "nav.dashboard") == "Panel"
    assert translate("es", "dash.lede", seconds=3).startswith("Estado en vivo")


def test_spanish_dashboard(client):
    res = client.get("/prefs?lang=es&next=/", follow_redirects=True)
    assert res.status_code == 200
    assert "Panel" in res.text
    assert "Servicios" in res.text
    assert "Alertas" in res.text
    assert "Ajustes" in res.text
    assert 'lang="es"' in res.text
    assert "Quitar filtros" in res.text


def test_english_stays_default(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Dashboard" in res.text
    assert 'lang="en"' in res.text


def test_theme_cookie(client):
    res = client.get("/prefs?theme=light&next=/", follow_redirects=True)
    assert res.status_code == 200
    assert 'data-theme="light"' in res.text
