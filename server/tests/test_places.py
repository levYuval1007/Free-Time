import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import places
from http_client import TransportError


def ok_response(*raw_places):
    return 200, json.dumps({"places": list(raw_places)}).encode()


def error_response(status, message="boom"):
    return status, json.dumps({"error": {"message": message}}).encode()


RAW_PLACE = {
    "id": "abc123",
    "displayName": {"text": "Yarkon Park", "languageCode": "en"},
    "location": {"latitude": 32.1, "longitude": 34.8},
    "types": ["park", "tourist_attraction"],
    "primaryType": "park",
    "rating": 4.6,
    "userRatingCount": 1200,
    "googleMapsUri": "https://maps.google.com/?cid=1",
    "regularOpeningHours": {
        "periods": [{"open": {"day": 0, "hour": 6, "minute": 0}, "close": {"day": 0, "hour": 22, "minute": 0}}],
        "weekdayDescriptions": ["Monday: 6:00 AM - 10:00 PM"],
    },
}


class NormalizePlaceTests(unittest.TestCase):
    def test_full_place(self):
        place = places.normalize_place(RAW_PLACE)
        self.assertEqual(place["id"], "abc123")
        self.assertEqual(place["name"], "Yarkon Park")
        self.assertEqual((place["lat"], place["lon"]), (32.1, 34.8))
        self.assertEqual(place["rating_count"], 1200)
        self.assertEqual(place["periods"][0]["open"]["hour"], 6)

    def test_minimal_place_has_no_hours(self):
        place = places.normalize_place({"id": "x", "location": {"latitude": 1, "longitude": 2}})
        self.assertEqual(place["name"], "")
        self.assertIsNone(place["periods"])
        self.assertIsNone(place["rating"])

    def test_place_without_location_is_dropped(self):
        self.assertIsNone(places.normalize_place({"id": "x"}))

    def test_place_without_id_is_dropped(self):
        self.assertIsNone(places.normalize_place({"location": {"latitude": 1, "longitude": 2}}))


class PlacesTestBase(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"})
        env.start()
        self.addCleanup(env.stop)
        sleep = mock.patch("places.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        self.client = mock.Mock()
        patched = mock.patch.object(places, "_client", self.client)
        patched.start()
        self.addCleanup(patched.stop)


class SearchNearbyTests(PlacesTestBase):
    def test_success_returns_normalized_places(self):
        self.client.request.return_value = ok_response(RAW_PLACE, {"id": "bad"})
        result = places.search_nearby(32.0, 34.7, 3000)
        self.assertEqual([p["id"] for p in result], ["abc123"])

    def test_key_goes_in_header_not_in_the_path(self):
        self.client.request.return_value = ok_response()
        places.search_nearby(32.0, 34.7, 3000)
        method, path, body, headers = self.client.request.call_args.args
        self.assertEqual(headers["X-Goog-Api-Key"], "test-key")
        self.assertNotIn("test-key", path)
        self.assertIn("places.regularOpeningHours", headers["X-Goog-FieldMask"])

    def test_request_body_uses_radius_and_types(self):
        self.client.request.return_value = ok_response()
        places.search_nearby(32.0, 34.7, 2500, types=["park"])
        body = json.loads(self.client.request.call_args.args[2])
        self.assertEqual(body["includedTypes"], ["park"])
        self.assertEqual(body["locationRestriction"]["circle"]["radius"], 2500.0)
        self.assertEqual(body["maxResultCount"], 20)

    def test_transient_error_is_retried_once(self):
        self.client.request.side_effect = [error_response(429), ok_response(RAW_PLACE)]
        result = places.search_nearby(32.0, 34.7, 3000)
        self.assertEqual(len(result), 1)
        self.assertEqual(self.client.request.call_count, 2)

    def test_permanent_error_is_not_retried(self):
        self.client.request.return_value = error_response(400, "bad type")
        with self.assertRaises(places.PlacesError) as ctx:
            places.search_nearby(32.0, 34.7, 3000)
        self.assertFalse(ctx.exception.transient)
        self.assertIn("bad type", str(ctx.exception))
        self.assertEqual(self.client.request.call_count, 1)

    def test_repeated_server_error_raises_transient(self):
        self.client.request.return_value = error_response(503)
        with self.assertRaises(places.PlacesError) as ctx:
            places.search_nearby(32.0, 34.7, 3000)
        self.assertTrue(ctx.exception.transient)
        self.assertEqual(self.client.request.call_count, 2)

    def test_network_failure_is_transient(self):
        self.client.request.side_effect = TransportError("timed out")
        with self.assertRaises(places.PlacesError) as ctx:
            places.search_nearby(32.0, 34.7, 3000)
        self.assertTrue(ctx.exception.transient)

    def test_missing_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(places.PlacesError):
                places.search_nearby(32.0, 34.7, 3000)


class AutocompleteTests(PlacesTestBase):
    def suggestion(self, place_id, text):
        return {"placePrediction": {"placeId": place_id, "text": {"text": text}}}

    def test_returns_labels_and_place_ids(self):
        self.client.request.return_value = ok_suggestions(
            self.suggestion("p1", "Dizengoff 50, Tel Aviv, Israel"),
            {"queryPrediction": {"text": {"text": "dizengoff street"}}},
        )
        result = places.autocomplete("dizengoff 50", "session-1")
        self.assertEqual(result, [{"label": "Dizengoff 50, Tel Aviv, Israel", "place_id": "p1"}])

    def test_request_carries_the_session_and_key(self):
        self.client.request.return_value = ok_suggestions()
        places.autocomplete("herzl", "session-1")
        method, path, body, headers = self.client.request.call_args.args
        payload = json.loads(body)
        self.assertEqual(payload["sessionToken"], "session-1")
        self.assertEqual(path, "/v1/places:autocomplete")
        self.assertEqual(headers["X-Goog-Api-Key"], "test-key")

    def test_without_a_bias_there_is_no_location_restriction(self):
        self.client.request.return_value = ok_suggestions()
        places.autocomplete("herzl", "session-1")
        payload = json.loads(self.client.request.call_args.args[2])
        self.assertNotIn("locationBias", payload)
        self.assertNotIn("includedRegionCodes", payload)

    def test_bias_ranks_places_near_the_user_first(self):
        self.client.request.return_value = ok_suggestions()
        places.autocomplete("herzl", "session-1", bias=(32.08, 34.78))
        payload = json.loads(self.client.request.call_args.args[2])
        circle = payload["locationBias"]["circle"]
        self.assertEqual(circle["center"], {"latitude": 32.08, "longitude": 34.78})
        self.assertEqual(circle["radius"], 50000.0)

    def test_no_suggestions_returns_empty_list(self):
        self.client.request.return_value = 200, b"{}"
        self.assertEqual(places.autocomplete("zzzz", "s"), [])


class PlaceLocationTests(PlacesTestBase):
    def test_returns_coordinates_and_address(self):
        self.client.request.return_value = 200, json.dumps(
            {"location": {"latitude": 32.07, "longitude": 34.77}, "formattedAddress": "Dizengoff 50"}
        ).encode()
        result = places.place_location("place/id 1", "session-1")
        self.assertEqual(result, {"lat": 32.07, "lon": 34.77, "address": "Dizengoff 50"})

    def test_request_is_get_with_essentials_mask_and_encoded_id(self):
        self.client.request.return_value = 200, json.dumps({"location": {"latitude": 1, "longitude": 2}}).encode()
        places.place_location("place/id 1", "session-1")
        method, path, body, headers = self.client.request.call_args.args
        self.assertEqual(method, "GET")
        self.assertIsNone(body)
        self.assertTrue(path.startswith("/v1/places/place%2Fid%201?"))
        self.assertIn("sessionToken=session-1", path)
        self.assertEqual(headers["X-Goog-FieldMask"], "location,formattedAddress")

    def test_missing_location_raises(self):
        self.client.request.return_value = 200, b"{}"
        with self.assertRaises(places.PlacesError):
            places.place_location("p1", "session-1")


def ok_suggestions(*suggestions):
    return 200, json.dumps({"suggestions": list(suggestions)}).encode()


if __name__ == "__main__":
    unittest.main()
