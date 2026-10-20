"""POST /api/contacts/import must not 500 on a non-string vcf/text/csv value.

`text = data.get("vcf") or ... or ""` left a non-string value (e.g. a number)
in place, so the next `text.strip()` raised AttributeError -> HTTP 500. The
handler now coerces with str() and degrades to a structured "no data" response.
"""
import asyncio

from routes.contacts.contacts_routes import setup_contacts_routes
from tests.helpers.routes import route_endpoint


def _call(data):
    handler = route_endpoint(setup_contacts_routes(), "/api/contacts/import", "POST")
    return asyncio.run(handler(data=data))


def test_non_string_vcf_degrades_cleanly():
    resp = _call({"vcf": 123})
    assert resp["success"] is False
    assert "error" in resp


def test_non_string_csv_degrades_cleanly():
    resp = _call({"csv": ["a", "b"]})
    assert resp["success"] is False


def test_empty_body_reports_no_data():
    resp = _call({})
    assert resp["success"] is False
    assert resp["error"] == "No contact data found"
