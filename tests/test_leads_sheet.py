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


class TeamNotes(unittest.TestCase):
    ID = "0f8fad5b-d9cb-469f-a165-70867728950e"

    def test_note_line(self):
        from datetime import datetime, timezone
        line = ls.note_line("  called,\n will visit  Monday ", "Ravi", datetime(2026, 10, 6, 10, 10, tzinfo=timezone.utc))
        self.assertEqual(line, "📝 06 Oct 15:40 Sheet (Ravi): called, will visit Monday")
        self.assertTrue(ls.note_line("x" * 900, "", datetime(2026, 10, 6, tzinfo=timezone.utc)).endswith("x" * 500))

    def test_only_a_uuid_and_a_real_note_are_accepted(self):
        self.assertEqual(ls.valid_note({"id": self.ID.upper(), "note": " ok "}), (self.ID, "ok", ""))
        self.assertIsNone(ls.valid_note({"id": "1 or 1=1", "note": "x"}))
        self.assertIsNone(ls.valid_note({"id": self.ID, "note": "   "}))

    def test_csv_carries_the_crm_id_last(self):
        out = list(csv.reader(io.StringIO(ls.to_csv([dict(Csv.ROW, id=self.ID)]))))
        self.assertEqual(out[0][-1], "CRM id")
        self.assertEqual(out[1][-1], self.ID)
