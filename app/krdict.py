import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API = "https://krdict.korean.go.kr/api/"
ENTRY_URL = "https://krdict.korean.go.kr/kor/dicSearch/SearchView?ParaWordNo={}"
ATTRIBUTION = "NIKL Basic Korean Dictionary (한국어기초사전)"
LICENSE = "CC BY-SA 2.0 KR"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/2.0/kr/"

NO_POS = {"품사 없음": ""}
MAX_CANDIDATES = 4
MAX_SENSES = 4
MAX_EXAMPLES = 3
EXAMPLE_TYPES = {"구", "문장"}


class KrdictError(Exception):
    """Raised with a message that is safe to show the user."""


def _text(node, path):
    found = node.find(path)
    return " ".join((found.text or "").split()) if found is not None else ""


def _parse(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise KrdictError("krdict returned output that could not be read.")
    if root.tag == "error":
        raise KrdictError(f"krdict error {_text(root, 'error_code')}: {_text(root, 'message')}")
    return root


def parse_search(xml_text):
    return [
        {
            "target_code": _text(item, "target_code"),
            "word": _text(item, "word"),
            "pos": _text(item, "pos"),
            "sup_no": int(_text(item, "sup_no") or 0),
        }
        for item in _parse(xml_text).iter("item")
    ]


def parse_view(xml_text):
    item = _parse(xml_text).find("item")
    if item is None:
        return None
    info = item.find("word_info")
    senses = []
    for sense in info.findall("sense_info")[:MAX_SENSES]:
        examples = [
            _text(ex, "example")
            for ex in sense.findall("example_info")
            if _text(ex, "type") in EXAMPLE_TYPES
        ]
        senses.append({
            "definition": _text(sense, "definition"),
            "english": _text(sense, "translation/trans_word"),
            "english_definition": _text(sense, "translation/trans_dfn"),
            "note": _text(sense, "reference"),
            "examples": examples[:MAX_EXAMPLES],
        })
    code = _text(item, "target_code")
    return {
        "target_code": code,
        "word": _text(info, "word"),
        "pos": _text(info, "pos"),
        "url": ENTRY_URL.format(code),
        "senses": senses,
    }


def fetch(endpoint, params):
    key = os.environ.get("KRDICT_API_KEY")
    if not key:
        raise KrdictError("No krdict API key found. Set KRDICT_API_KEY in .env.")
    query = urllib.parse.urlencode({**params, "key": key, "translated": "y", "trans_lang": "1"})
    try:
        with urllib.request.urlopen(f"{API}{endpoint}?{query}", timeout=20) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as e:
        raise KrdictError(f"Could not reach krdict: {e}")


def search(headword, get=fetch):
    # Advanced exact search returns nothing for headwords starting with a hyphen (-고 싶다), so search plainly.
    return parse_search(get("search", {"q": headword, "num": 50}))


def view(target_code, get=fetch):
    return parse_view(get("view", {"method": "target_code", "q": target_code}))


def lookup(headword, pos, get=fetch):
    """Candidate entries spelled exactly like headword, narrowed to pos when pos is given.
    The same spelling and pos can still be different words (이 관형사 is both "this" and "two"),
    so the caller must choose among them by meaning."""
    matches = [m for m in search(headword, get) if m["word"] == headword]
    same_pos = [m for m in matches if NO_POS.get(m["pos"], m["pos"]) == pos]
    matches = same_pos or matches
    matches.sort(key=lambda m: m["sup_no"])
    return [entry for m in matches[:MAX_CANDIDATES] if (entry := view(m["target_code"], get))]
