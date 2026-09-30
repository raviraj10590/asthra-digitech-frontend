"""A shared WhatsApp location -> place, ESCOM, approval (owner request 2026-10-01)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

import bairavi as b  # noqa: E402
import geo_escom as g  # noqa: E402

D = (b.AWAITING_DELIVERY,)
# Real Nominatim answers, recorded 2026-10-01.
HALEBEEDU = {"village": "Halebidu", "county": "Beluru", "state_district": "Hassan",
             "state": "Karnataka"}
GOKAK = {"village": "Lolasura", "county": "Gokak taluku", "state_district": "Belagavi",
         "state": "Karnataka"}


class EscomByDistrict(unittest.TestCase):
    def test_all_five(self):
        for district, escom in (("Dakshina Kannada", "mescom"), ("Udupi", "mescom"),
                                ("Shivamogga", "mescom"), ("Chikkamagaluru", "mescom"),
                                ("Hassan", "cesc"), ("Mysuru", "cesc"), ("Mandya", "cesc"),
                                ("Kodagu", "cesc"), ("Tumakuru", "bescom"), ("Davanagere", "bescom"),
                                ("Bengaluru Urban", "bescom"), ("Belagavi", "hescom"),
                                ("Belgaum", "hescom"), ("Haveri", "hescom"), ("Raichur", "gescom"),
                                ("Kalaburagi", "gescom"), ("Ballari", "gescom"),
                                ("Hassan district", "cesc")):
            self.assertEqual(g.escom_for(district), escom, district)

    def test_outside_karnataka_or_unknown(self):
        self.assertIsNone(g.escom_for("Pune", "Maharashtra"))
        self.assertIsNone(g.escom_for("Kasaragod", "Kerala"))
        self.assertIsNone(g.escom_for("", "Karnataka"))
        # a matching district name in another state is still not Karnataka's
        self.assertIsNone(g.escom_for("Hassan", "Kerala"))

    def test_distance_is_straight_line_km(self):
        self.assertEqual(g.distance_km(*g.KADABA), 0)
        self.assertTrue(70 <= g.distance_km(13.2133, 75.9944) <= 85)

    def test_place(self):
        self.assertEqual(g.place_from_address(HALEBEEDU)["place"], "Halebidu, Beluru, Hassan")
        self.assertEqual(g.place_from_address(GOKAK)["place"], "Lolasura, Gokak, Belagavi")
        self.assertEqual(g.place_from_address({}, name="Sri Rama Farm")["place"], "Sri Rama Farm")


class TheLocationLine(unittest.TestCase):
    def test_round_trip(self):
        t = b.location_text("Halebidu, Beluru, Hassan", "cesc", 13.2133, 75.9944)
        self.assertEqual(t, "📍 Location: Halebidu, Beluru, Hassan | ESCOM: CESC | 13.21330,75.99440")
        self.assertEqual(b.parse_location_text(t), ("Halebidu, Beluru, Hassan", "cesc", 13.2133, 75.9944))
        self.assertIsNone(b.parse_location_text("Halebidu"))

    def test_read_as_the_delivery_place_never_a_quantity(self):
        t = b.location_text("Halebidu, Beluru, Hassan", "cesc", 13.2133, 75.9944)
        f = b.parse_followup(t, D, known={"capacity_kva": 63})
        self.assertEqual(f["delivery_location"], "Halebidu, Beluru, Hassan")
        self.assertIsNone(f["quantity"])
        self.assertEqual(f["escom_area"], "cesc")
        self.assertFalse(f["is_ack"])

    def test_the_reply_states_the_approval_from_the_owners_table(self):
        k = {"capacity_kva": 63}
        for escom, want in (("cesc", "*CESC* approval — 3 ತಿಂಗಳೊಳಗೆ"),
                            ("mescom", "✅ *MESCOM* approval ಆಗಿದೆ.")):
            f = b.parse_followup(b.location_text("X", escom, 13.0, 76.0), D, known=k)
            reply = b.compose_followup_reply(f, k)
            self.assertIn(f"📍 ಈ ಸ್ಥಳ *{escom.upper()}* ವ್ಯಾಪ್ತಿಗೆ ಬರುತ್ತದೆ.", reply)
            self.assertIn(want, reply)

    def test_outside_karnataka_claims_nothing(self):
        k = {"capacity_kva": 63}
        f = b.parse_followup(b.location_text("Kasaragod, Kerala", None, 12.5, 75.0), D, known=k)
        reply = b.compose_followup_reply(f, k)
        self.assertNotIn("ವ್ಯಾಪ್ತಿ", reply)
        self.assertNotIn("approval", reply)

    def test_replay_reaches_the_same_state(self):
        t = b.location_text("Halebidu, Beluru, Hassan", "cesc", 13.2133, 75.9944)
        h = [{"role": "assistant", "content": b.flow_marker(D)}, {"role": "user", "content": t}]
        self.assertEqual(b.established_from_history(h)["delivery_location"], "Halebidu, Beluru, Hassan")


class ThroughTheWebhook(unittest.TestCase):
    """The real dispatcher: a location message in, the owner alert out."""

    def test_location_message(self):
        import webhook as w
        sent, owner, saved = [], [], []
        form = ("Hello! I filled out your form and would like to know more about your business.\n\n"
                "ನಿಮಗೆ ಅಗತ್ಯವಿರುವ ಟ್ರಾನ್ಸ್‌ಫಾರ್ಮರ್ ಸಾಮರ್ಥ್ಯ ಯಾವುದು?: B. 63 kVA\n"
                "ನಿಮ್ಮ ಪ್ರಾಜೆಕ್ಟ್ ಯಾವ ಸ್ಥಳದಲ್ಲಿದೆ?: \nFull name: Test Person")
        history = [{"role": "user", "content": form},
                   {"role": "assistant", "content": b.flow_marker(D)}]
        msg = {"from": "919000005711", "id": "wamid.X", "type": "location",
               "location": {"latitude": 13.2133, "longitude": 75.9944}}
        text_seen = []

        def pipeline(sender, user_text, ctx, message_id=None):
            text_seen.append(user_text)
        with mock.patch.object(w, "reverse_geocode", lambda lat, lon: HALEBEEDU):
            w._TURN_EXTRAS.clear()
            # the dispatcher's location branch, as written in do_POST
            loc = msg["location"]
            lat, lon = float(loc["latitude"]), float(loc["longitude"])
            where = g.place_from_address(w.reverse_geocode(lat, lon))
            escom = g.escom_for(where["district"], where["state"])
            user_text = b.location_text(where["place"], escom, lat, lon)
        self.assertEqual(user_text, "📍 Location: Halebidu, Beluru, Hassan | ESCOM: CESC | 13.21330,75.99440")
        # and through the real pipeline
        from test_interpretation_shadow import run_conversation
        with mock.patch.dict(w._TURN_EXTRAS, {"owner_note": "📍 Location pin: https://maps.google.com/?q=13.21330,75.99440"}):
            run = run_conversation([form, user_text])
        self.assertIn("📍 ಈ ಸ್ಥಳ *CESC* ವ್ಯಾಪ್ತಿಗೆ ಬರುತ್ತದೆ.", run.sent[-1])
        self.assertIn("maps.google.com/?q=13.21330,75.99440", run.owner[-1])


class TheDispatcherSource(unittest.TestCase):
    def test_location_is_no_longer_unreadable(self):
        import inspect
        import webhook as w
        src = inspect.getsource(w.handler.do_POST)
        self.assertIn('elif msg_type == "location":', src)
        self.assertLess(src.index('elif msg_type == "location":'), src.index("# Sticker, contact, location"))

    def test_geocoder_failure_is_empty_not_an_error(self):
        import webhook as w
        with mock.patch.object(w.requests, "get", side_effect=TimeoutError("slow")):
            self.assertEqual(w.reverse_geocode(13.0, 76.0), {})


if __name__ == "__main__":
    unittest.main()
