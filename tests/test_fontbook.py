"""The font book: bundled fonts, uploads, Google Fonts imports (offline fakes)."""
import json

import pytest

import fontbook as fb

POPPINS = (fb.BUNDLED_DIR / "Poppins-Black.ttf").read_bytes()
ANTON = (fb.BUNDLED_DIR / "Anton-Regular.ttf").read_bytes()


@pytest.fixture
def book(tmp_path):
    return fb.FontBook(tmp_path / "library")


def test_bundled_fonts_are_listed_with_their_real_names(book):
    fonts = {f["id"]: f for f in book.all()}
    assert len(fonts) == len(fb.BUNDLED)
    assert fonts["poppins-black"]["ass_name"] == "Poppins Black" and fonts["anton"]["url"] == "/fonts/Anton-Regular.ttf"
    assert book.get("nope")["id"] == fb.DEFAULT_FONT


def test_upload_reads_names_and_rejects_non_fonts(book):
    f = book.add(ANTON, "MyAnton.ttf")
    assert f["id"] == "user-anton-regular" and f["ass_name"] == "Anton Regular" and f["user"]
    assert (book.dir / "user-anton-regular.ttf").read_bytes() == ANTON
    assert "user-anton-regular" in book.ids()
    for bad, msg in ((b"wOF2" + b"0" * 100, "web font"), (b"ttcf" + b"0" * 100, "collection"), (b"hello", "Not a font")):
        with pytest.raises(fb.FontError, match=msg):
            book.add(bad, "x.ttf")
    book.remove("user-anton-regular")
    assert "user-anton-regular" not in book.ids() and not (book.dir / "user-anton-regular.ttf").exists()
    with pytest.raises(KeyError):
        book.remove("anton")                                     # bundled


def test_google_import_asks_for_truetype_at_the_weight(book, monkeypatch):
    calls = []

    def fetch(url, headers):
        calls.append((url, headers))
        if "css2" in url:
            return b"@font-face { src: url(https://fonts.gstatic.com/s/poppins/v1/abc.ttf) format('truetype'); }"
        return POPPINS

    monkeypatch.setattr(fb, "FETCH", fetch)
    f = book.add_google("Poppins", 900)
    assert calls[0][0] == "https://fonts.googleapis.com/css2?family=Poppins:wght@900"
    assert calls[0][1]["User-Agent"] == fb.GOOGLE_UA
    assert f["label"] == "Poppins Black" and f["source"] == "google" and f["ass_name"] == "Poppins Black"
    with pytest.raises(fb.FontError):
        book.add_google("Poppins", 950)
    monkeypatch.setattr(fb, "FETCH", lambda url, headers: b"@font-face { src: url(x.woff2) }")
    with pytest.raises(fb.FontError, match="TrueType"):
        book.add_google("Poppins", 400)


def test_google_search_uses_a_cached_catalogue(book, monkeypatch):
    meta = {"familyMetadataList": [
        {"family": "Montserrat", "category": "Sans Serif", "popularity": 7, "fonts": {"400": {}, "800": {}, "800i": {}}},
        {"family": "Montserrat Alternates", "category": "Sans Serif", "popularity": 300, "fonts": {"700": {}}},
        {"family": "Roboto", "category": "Sans Serif", "popularity": 1, "fonts": {"900": {}}},
        {"family": "Noto Sans", "category": "Sans Serif", "popularity": 2, "isNoto": True, "fonts": {"400": {}}},
        {"family": "Montserrat Brand", "category": "Sans Serif", "popularity": 3, "isBrandFont": True, "fonts": {"400": {}}},
        {"family": "Mont Closed", "category": "Sans Serif", "popularity": 4, "isOpenSource": False, "fonts": {"400": {}}},
    ]}
    n = []
    monkeypatch.setattr(fb, "FETCH", lambda url, headers: n.append(url) or (")]}'\n" + json.dumps(meta)).encode())
    hits = book.search_google("mont")
    assert [h["family"] for h in hits] == ["Montserrat", "Montserrat Alternates"] and hits[0]["weights"] == [400, 800]
    assert [h["family"] for h in book.search_google("")] == ["Roboto", "Montserrat", "Montserrat Alternates"]
    assert len(n) == 1                                            # cached after the first call
