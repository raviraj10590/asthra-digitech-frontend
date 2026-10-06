"""The CSV the owner's Google Sheet imports (api/leads_sheet.py)."""
import csv
import importlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
import leads_sheet as ls                                          # noqa: E402


class Notes(unittest.TestCase):
    def test_service_city_and_call_lines(self):
        n = ls.parse_notes("Service: Transformer 25 kVA | City: davanagere\n06 Oct 11:20 interested\n")
        self.assertEqual(n, {"service": "Transformer 25 kVA", "city": "davanagere", "calls": "06 Oct 11:20 interested"})

    def test_no_key_value_line_is_all_notes(self):
        self.assertEqual(ls.parse_notes("called, no answer")["calls"], "called, no answer")
        self.assertEqual(ls.parse_notes(None), {"service": "", "city": "", "calls": ""})


class Csv(unittest.TestCase):
    ROW = {"name": "Munegowda NK", "phone": "919590559112", "notes": "Service: Transformer 25 kVA | City: Chikkaballapura",
           "pipeline_stage": "Lead", "created_at": "2026-10-06 05:46:00+00", "last_contacted_at": None}

    def rows(self, *r):
        return list(csv.reader(io.StringIO(ls.to_csv(list(r)))))

    def test_header_and_ist_and_phone_as_text(self):
        head, row = self.rows(self.ROW)
        self.assertEqual(head[0], "Date (IST)")
        self.assertEqual(row[0], "06 Oct 2026 · 11:16")
        self.assertEqual(row[2], "+91 95905 59112")
        self.assertEqual(row[3:6], ["Transformer 25 kVA", "Chikkaballapura", "Lead"])

    def test_no_formula_injection(self):
        _, row = self.rows(dict(self.ROW, name="=HYPERLINK(\"x\")", notes="Service: +1 | City: @x"))
        for cell in (row[1], row[3], row[4]):
            self.assertNotIn(cell[:1], "=+-@")


class Gate(unittest.TestCase):
    def test_key_required_and_compared(self):
        os.environ["LEADS_SHEET_KEY"] = "s3cret-key"
        m = importlib.reload(ls)
        self.assertTrue(m.authorised("key=s3cret-key"))
        self.assertFalse(m.authorised("key=wrong"))
        self.assertFalse(m.authorised(""))
        os.environ["LEADS_SHEET_KEY"] = ""
        self.assertFalse(importlib.reload(ls).authorised("key="))
