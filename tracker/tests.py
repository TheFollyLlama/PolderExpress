from datetime import datetime, timezone
from typing import ClassVar
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import resolve
from rest_framework import status
from rest_framework.test import APIClient

from tracker import services
from tracker.atc import feed_stream_url, find_atc_feed
from tracker.serializers import PlanePhotoResponseSerializer, PlaneSerializer
from tracker.services import (
    AMS_ACC_STREAM,
    AMS_APPROACH_STREAM,
    AMS_DELIVERY_STREAM,
    AMS_DEPARTURE_STREAM,
    AMS_GROUND_STREAM,
    AMS_MUAC_STREAM,
    AMS_NIGHT_FREQ_MHZ,
    AMS_SECTOR_FREQS,
    AMS_TOWER_STREAM,
    LIVEATC_APPROACH,
    LIVEATC_CENTER,
    LIVEATC_GROUND,
    LIVEATC_TOWER,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
    _ams_atc_layer,
    _parse_ac,
    _parse_photo,
    _parse_route,
    _plane_distance_bearing,
    fetch_closest_plane,
    fetch_nearby_planes,
    fetch_plane_photo,
    fetch_route,
    get_liveatc_url,
    haversine,
    is_night_bandbox_active,
)
from tracker.views import (
    ClosestPlaneView,
    NearbyPlanesView,
    PlaneAtcView,
    PlanePhotoView,
)

EARTH_HALF_CIRCUMFERENCE_KM = 6371.0 * 3.141592653589793


class HaversineTests(TestCase):
    def test_same_point_is_zero(self):
        self.assertAlmostEqual(haversine(33.4, -84.4, 33.4, -84.4), 0.0)

    def test_symmetric(self):
        d1 = haversine(33.4, -84.4, 40.7128, -74.0060)
        d2 = haversine(40.7128, -74.0060, 33.4, -84.4)
        self.assertAlmostEqual(d1, d2, places=9)

    def test_known_distance_london_to_paris(self):
        d = haversine(51.5074, -0.1278, 48.8566, 2.3522)
        self.assertAlmostEqual(d, 343.5, delta=2.0)

    def test_known_distance_atl_radial_upstream_sample(self):
        d = haversine(33.4, -84.4, 33.383401, -85.360575)
        self.assertAlmostEqual(d, 89.0, delta=1.0)

    def test_antipodal_points_half_earth_circumference(self):
        d = haversine(0.0, 0.0, 0.0, 180.0)
        self.assertAlmostEqual(d, EARTH_HALF_CIRCUMFERENCE_KM, places=6)

    def test_zero_dlat_positive_dlon(self):
        d = haversine(0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(d, 111.19, delta=0.1)


class BearingTests(TestCase):
    def test_north_is_zero(self):
        _, bearing = _plane_distance_bearing(0.0, 0.0, 10.0, 0.0)
        self.assertAlmostEqual(bearing, 0.0, places=6)

    def test_east_is_ninety(self):
        _, bearing = _plane_distance_bearing(0.0, 0.0, 0.0, 10.0)
        self.assertAlmostEqual(bearing, 90.0, places=6)

    def test_south_is_one_eighty(self):
        _, bearing = _plane_distance_bearing(0.0, 0.0, -10.0, 0.0)
        self.assertAlmostEqual(bearing, 180.0, places=6)

    def test_west_is_two_seventy(self):
        _, bearing = _plane_distance_bearing(0.0, 0.0, 0.0, -10.0)
        self.assertAlmostEqual(bearing, 270.0, places=6)

    def test_bearing_svmmetro_atl_sample(self):
        distance, bearing = _plane_distance_bearing(33.4, -84.4, 33.028673, -85.217976)
        self.assertAlmostEqual(distance, 86.4, delta=2.0)
        self.assertGreaterEqual(bearing, 0.0)
        self.assertLess(bearing, 360.0)


class LiveAtcTests(TestCase):
    def test_ground_within_15_km_of_katl(self):
        self.assertEqual(get_liveatc_url(33.635, -84.428, "ground"), LIVEATC_GROUND)

    def test_tower_when_low_and_close(self):
        self.assertEqual(get_liveatc_url(33.64, -84.43, 500), LIVEATC_TOWER)

    def test_approach_when_above_tower_ceiling(self):
        self.assertEqual(get_liveatc_url(33.64, -84.43, 5000), LIVEATC_APPROACH)

    def test_approach_within_50_km_below_24000(self):
        self.assertEqual(get_liveatc_url(33.9, -84.5, 15000), LIVEATC_APPROACH)

    def test_center_at_fl240_or_above(self):
        self.assertEqual(get_liveatc_url(33.64, -84.43, 24000), LIVEATC_CENTER)

    def test_center_far_from_katl(self):
        self.assertEqual(get_liveatc_url(40.0, -100.0, 30000), LIVEATC_CENTER)

    def test_center_when_no_altitude(self):
        self.assertEqual(get_liveatc_url(33.95, -84.5, None), LIVEATC_CENTER)


class FindAtcFeedTests(TestCase):
    def _schiphol_departure(self):
        return {
            "name": "Schiphol Departure",
            "kind": "appdep",
            "stream_url": feed_stream_url("eham_app_121205"),
            "altitude_ceiling_ft": 24000,
        }

    def test_schiphol_departure_when_over_ams_low(self):
        feed = find_atc_feed(52.3086, 4.7639, 12000)
        self.assertIsNotNone(feed)
        self.assertEqual(feed["name"], "Schiphol Departure")
        self.assertEqual(feed["kind"], "appdep")
        self.assertEqual(feed["stream_url"], feed_stream_url("eham_app_121205"))
        self.assertLessEqual(feed["distance_km"], 50.0)

    def test_schiphol_ground_when_on_ground_at_ams(self):
        feed = find_atc_feed(52.3086, 4.7639, "ground")
        self.assertIsNotNone(feed)
        self.assertEqual(feed["name"], "Schiphol Ground")
        self.assertEqual(feed["kind"], "ground")
        self.assertEqual(feed["stream_url"], feed_stream_url("eham_gnd_0624"))

    def test_maastricht_upper_control_high_over_ams(self):
        feed = find_atc_feed(52.3086, 4.7639, 38000)
        self.assertIsNotNone(feed)
        self.assertEqual(feed["name"], "Maastricht Upper Area Control (MUAC)")
        self.assertEqual(feed["kind"], "center")
        self.assertEqual(feed["stream_url"], feed_stream_url("eham_muac_135510"))
        self.assertIsNone(feed["altitude_ceiling_ft"])

    def test_far_position_falls_back_to_nearest_center(self):
        feed = find_atc_feed(40.0, -100.0, 30000)
        self.assertIsNotNone(feed)
        self.assertEqual(feed["kind"], "center")
        self.assertEqual(feed["name"], "Atlanta Center (ZTL)")

    def test_missing_position_returns_none(self):
        self.assertIsNone(find_atc_feed(None, None, 10000))

    def test_tower_for_low_close_traffic(self):
        tower = find_atc_feed(33.64, -84.43, 500)
        self.assertEqual(tower["name"], "Atlanta Tower")

    def test_appdep_beats_tower_once_above_tower_ceiling(self):
        appdep = find_atc_feed(33.64, -84.43, 5000)
        self.assertEqual(appdep["name"], "Atlanta Approach")

    def test_altitude_ceiling_respected(self):
        tower = find_atc_feed(33.64, -84.43, 12000)
        self.assertEqual(tower["name"], "Atlanta Approach")
        after_ceiling = find_atc_feed(33.64, -84.43, 25000)
        self.assertEqual(after_ceiling["name"], "Atlanta Center (ZTL)")

    def test_tower_applies_below_1000_ft_at_katl(self):
        feed = find_atc_feed(33.64, -84.43, 999)
        self.assertEqual(feed["name"], "Atlanta Tower")

    def test_appdep_at_exactly_1000_ft_at_katl(self):
        feed = find_atc_feed(33.64, -84.43, 1000)
        self.assertEqual(feed["name"], "Atlanta Approach")

    def test_appdep_at_exactly_23999_ft_at_katl(self):
        feed = find_atc_feed(33.64, -84.43, 23999)
        self.assertEqual(feed["name"], "Atlanta Approach")

    def test_center_at_exactly_24000_ft_at_katl(self):
        feed = find_atc_feed(33.64, -84.43, 24000)
        self.assertEqual(feed["name"], "Atlanta Center (ZTL)")

    def test_tower_within_1_km_radius_boundary(self):
        feed = find_atc_feed(33.6367 + 0.005, -84.4281, 999)
        self.assertEqual(feed["name"], "Atlanta Tower")
        self.assertLess(feed["distance_km"], 1.0)

    def test_appdep_within_50_km_radius_boundary(self):
        feed = find_atc_feed(33.6367 + 0.015, -84.4281, 999)
        self.assertEqual(feed["name"], "Atlanta Approach")
        self.assertGreater(feed["distance_km"], 1.0)

    def test_schiphol_departure_at_exactly_10000_ft(self):
        feed = find_atc_feed(52.3086, 4.7639, 10000)
        self.assertEqual(feed["name"], "Schiphol Departure")

    def test_schiphol_muac_at_exactly_24000_ft(self):
        feed = find_atc_feed(52.3086, 4.7639, 24000)
        self.assertEqual(feed["name"], "Maastricht Upper Area Control (MUAC)")


class PlaneAtcViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.url = "/api/v1/atc/"

    def test_returns_feed_for_ams_position(self):
        response = self.client.get(
            self.url,
            {"lat": 52.3086, "lon": 4.7639, "altitude": 12000},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["feed"]["name"], "Schiphol Departure")
        self.assertEqual(response.data["feed"]["kind"], "appdep")
        self.assertTrue(response.data["feed"]["stream_url"].endswith("/eham_app_121205.mp3"))

    def test_returns_ground_feed_for_ground_altitude(self):
        response = self.client.get(
            self.url,
            {"lat": 52.3086, "lon": 4.7639, "altitude": "ground"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["feed"]["name"], "Schiphol Ground")

    def test_returns_muac_at_high_altitude(self):
        response = self.client.get(
            self.url,
            {"lat": 52.3086, "lon": 4.7639, "altitude": 38000},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["feed"]["name"], "Maastricht Upper Area Control (MUAC)")

    def test_missing_altitude_still_returns_feed(self):
        response = self.client.get(self.url, {"lat": 52.3086, "lon": 4.7639})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_missing_lat_returns_400(self):
        response = self.client.get(self.url, {"lat": 52.3086})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_numeric_lon_returns_serializer_errors(self):
        response = self.client.get(self.url, {"lat": 52.3086, "lon": "abc"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lon", response.data)

    def test_invalid_altitude_returns_400(self):
        response = self.client.get(
            self.url,
            {"lat": 52.3086, "lon": 4.7639, "altitude": "not-a-number"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inf_altitude_returns_400(self):
        response = self.client.get(
            self.url,
            {"lat": 52.3086, "lon": 4.7639, "altitude": "inf"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nan_altitude_returns_400(self):
        response = self.client.get(
            self.url,
            {"lat": 52.3086, "lon": 4.7639, "altitude": "nan"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_zero_altitude_returns_400(self):
        response = self.client.get(
            self.url,
            {"lat": 52.3086, "lon": 4.7639, "altitude": "0"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_negative_altitude_returns_400(self):
        response = self.client.get(
            self.url,
            {"lat": 52.3086, "lon": 4.7639, "altitude": "-500"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lat_above_90_returns_400(self):
        response = self.client.get(self.url, {"lat": 91, "lon": 4.7639})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lon_above_180_returns_400(self):
        response = self.client.get(self.url, {"lat": 52.3086, "lon": 181})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_not_allowed(self):
        response = self.client.post(self.url)
        self.assertIn(response.status_code, (status.HTTP_405_METHOD_NOT_ALLOWED,))


class IsNightBandboxActiveTests(TestCase):
    def test_night_hours_active(self):
        self.assertTrue(is_night_bandbox_active(datetime(2026, 1, 15, 23, 0, tzinfo=timezone.utc)))

    def test_morning_hours_active(self):
        self.assertTrue(is_night_bandbox_active(datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)))

    def test_day_hours_inactive(self):
        self.assertFalse(is_night_bandbox_active(datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)))

    def test_boundary_start_inactive(self):
        self.assertFalse(is_night_bandbox_active(datetime(2026, 1, 15, 21, 59, tzinfo=timezone.utc)))

    def test_boundary_end_active(self):
        self.assertTrue(is_night_bandbox_active(datetime(2026, 1, 15, 4, 59, tzinfo=timezone.utc)))


class AmsAtcLayerTests(TestCase):
    DAY = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    NIGHT = datetime(2026, 1, 15, 23, 0, tzinfo=timezone.utc)

    def _layer(self, lat, lon, altitude_ft, **kwargs):
        return _ams_atc_layer(lat, lon, altitude_ft, **kwargs)

    def test_ground_slow_aircraft_uses_delivery(self):
        layer = self._layer(52.3086, 4.7639, "ground", ground_speed_knots=3)
        self.assertEqual(layer["stream_url"], AMS_DELIVERY_STREAM)
        self.assertEqual(layer["frequency"], "121.980")

    def test_ground_moving_aircraft_uses_ground(self):
        layer = self._layer(52.3086, 4.7639, "ground", ground_speed_knots=20)
        self.assertEqual(layer["stream_url"], AMS_GROUND_STREAM)
        self.assertEqual(layer["frequency"], "121.705")

    def test_ground_beyond_radius_returns_none(self):
        self.assertIsNone(self._layer(52.6, 4.9, "ground", ground_speed_knots=20))

    def test_tower_band_uses_tower(self):
        layer = self._layer(52.309, 4.764, 1200)
        self.assertEqual(layer["stream_url"], AMS_TOWER_STREAM)
        self.assertEqual(layer["frequency"], "135.110")

    def test_above_tower_ceiling_uses_tma_approach(self):
        layer = self._layer(52.309, 4.764, 3000)
        self.assertEqual(layer["stream_url"], AMS_APPROACH_STREAM)
        self.assertEqual(layer["frequency"], "119.055")

    def test_tma_departure_uses_departure_stream(self):
        layer = self._layer(52.35, 4.85, 5000, vertical_rate_fpm=1500)
        self.assertEqual(layer["stream_url"], AMS_DEPARTURE_STREAM)
        self.assertEqual(layer["frequency"], "121.205")

    def test_tma_arrival_uses_approach_stream(self):
        layer = self._layer(52.35, 4.85, 5000, vertical_rate_fpm=-500)
        self.assertEqual(layer["stream_url"], AMS_APPROACH_STREAM)
        self.assertEqual(layer["frequency"], "119.055")

    def test_acc_day_south_west_sector(self):
        layer = self._layer(52.0, 4.2, 12000, now=self.DAY)
        self.assertEqual(layer["stream_url"], AMS_ACC_STREAM)
        self.assertEqual(layer["frequency"], AMS_SECTOR_FREQS["southwest"])

    def test_acc_day_north_west_sector(self):
        layer = self._layer(52.6, 4.2, 12000, now=self.DAY)
        self.assertEqual(layer["frequency"], AMS_SECTOR_FREQS["northwest"])

    def test_acc_day_south_sector(self):
        layer = self._layer(52.0, 5.2, 12000, now=self.DAY)
        self.assertEqual(layer["frequency"], AMS_SECTOR_FREQS["south"])

    def test_acc_day_east_sector(self):
        layer = self._layer(52.6, 5.2, 12000, now=self.DAY)
        self.assertEqual(layer["frequency"], AMS_SECTOR_FREQS["east"])

    def test_acc_day_north_band_uses_sector_one(self):
        layer = self._layer(53.0, 5.0, 12000, now=self.DAY)
        self.assertEqual(layer["frequency"], AMS_SECTOR_FREQS["north"])

    def test_acc_night_uses_bandbox_frequency(self):
        layer = self._layer(52.0, 4.2, 12000, now=self.NIGHT)
        self.assertEqual(layer["stream_url"], AMS_ACC_STREAM)
        self.assertEqual(layer["frequency"], AMS_NIGHT_FREQ_MHZ)

    def test_acc_altitude_lower_bound_inclusive(self):
        layer = self._layer(52.0, 4.2, 9501, now=self.DAY)
        self.assertEqual(layer["frequency"], AMS_SECTOR_FREQS["southwest"])

    def test_acc_altitude_upper_bound_inclusive(self):
        layer = self._layer(52.0, 4.2, 24500, now=self.DAY)
        self.assertEqual(layer["frequency"], AMS_SECTOR_FREQS["southwest"])

    def test_acc_altitude_below_band_uses_tma(self):
        layer = self._layer(52.0, 4.2, 9499, now=self.DAY)
        self.assertEqual(layer["stream_url"], AMS_APPROACH_STREAM)

    def test_muac_above_acc_ceiling(self):
        layer = self._layer(50.9, 5.7, 30000)
        self.assertEqual(layer["stream_url"], AMS_MUAC_STREAM)
        self.assertEqual(layer["frequency"], "135.510")

    def test_ground_altitude_returns_none(self):
        self.assertIsNone(self._layer(52.2, 4.8, "ground"))

    def test_missing_altitude_returns_none(self):
        self.assertIsNone(self._layer(52.0, 4.2, None))

    def test_missing_position_returns_none(self):
        self.assertIsNone(self._layer(None, None, 12000))

    def test_out_of_coverage_returns_none(self):
        self.assertIsNone(self._layer(40.0, -100.0, 30000))


class AmsAtcLayerParseTests(TestCase):
    DAY = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

    def test_parse_ac_assigns_sector_stream_and_frequency(self):
        parsed = _parse_ac(
            {"hex": "abc123", "lat": 52.0, "lon": 4.2, "alt_baro": 12000},
            52.3086,
            4.7639,
            now=self.DAY,
        )
        self.assertEqual(parsed["liveatc_frequency"], AMS_SECTOR_FREQS["southwest"])
        self.assertEqual(parsed["liveatc_stream_url"], AMS_ACC_STREAM)

    def test_parse_ac_outside_ams_keeps_appdep_stream(self):
        parsed = _parse_ac(
            {"hex": "abc123", "lat": 52.8, "lon": 12.0, "alt_baro": 12000},
            52.3086,
            4.7639,
            now=self.DAY,
        )
        self.assertIsNone(parsed["liveatc_frequency"])
        self.assertNotEqual(parsed["liveatc_stream_url"], AMS_ACC_STREAM)

    def test_parse_ac_no_position_has_no_stream_or_frequency(self):
        parsed = _parse_ac({"hex": "abc123"}, 52.3086, 4.7639)
        self.assertIsNone(parsed["liveatc_frequency"])
        self.assertIsNone(parsed["liveatc_stream_url"])


class ParseAcTests(TestCase):
    def test_strips_callsign_whitespace(self):
        ac = {"flight": "DAL441  ", "hex": "acb82c", "lat": 33.0, "lon": -84.2}
        parsed = _parse_ac(ac, 33.4, -84.4)
        self.assertEqual(parsed["callsign"], "DAL441")

    def test_missing_flight_becomes_empty(self):
        parsed = _parse_ac({"hex": "abc123", "lat": 33.0, "lon": -84.2}, 33.4, -84.4)
        self.assertEqual(parsed["callsign"], "")

    def test_ground_altitude_preserved_as_string(self):
        parsed = _parse_ac(
            {"hex": "abc123", "lat": 33.63, "lon": -84.43, "alt_baro": "ground"},
            33.4,
            -84.4,
        )
        self.assertEqual(parsed["altitude_ft"], "ground")

    def test_string_digit_altitude_converted_to_int(self):
        parsed = _parse_ac(
            {"hex": "abc123", "lat": 33.0, "lon": -84.2, "alt_baro": "10500"},
            33.4,
            -84.4,
        )
        self.assertEqual(parsed["altitude_ft"], 10500)

    def test_invalid_altitude_string_becomes_none(self):
        parsed = _parse_ac(
            {"hex": "abc123", "lat": 33.0, "lon": -84.2, "alt_baro": "n/a"},
            33.4,
            -84.4,
        )
        self.assertIsNone(parsed["altitude_ft"])

    def test_missing_position_gives_null_distances(self):
        parsed = _parse_ac({}, 33.4, -84.4)
        self.assertIsNone(parsed["distance_km"])
        self.assertIsNone(parsed["bearing"])
        self.assertIsNone(parsed["liveatc_stream_url"])

    def test_distance_is_rounded_to_three_decimals(self):
        parsed = _parse_ac(
            {"hex": "abc123", "lat": 33.02, "lon": -85.21},
            33.4,
            -84.4,
        )
        self.assertIsInstance(parsed["distance_km"], float)
        self.assertEqual(parsed["distance_km"], round(parsed["distance_km"], 3))


class FetchNearbyPlanesTests(TestCase):
    def _mock_response(self, payload, status_code=200):
        response = mock.Mock()
        response.status_code = status_code
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    @mock.patch("tracker.services.requests.get")
    def test_parses_ac_list_and_count(self, mock_get):
        payload = {
            "msg": "No error",
            "ac": [
                {"hex": "acb82c", "flight": "DAL441 ", "lat": 33.02, "lon": -85.21},
                {"hex": "dead99", "flight": "UAL678", "lat": 33.36, "lon": -84.82},
            ],
        }
        mock_get.return_value = self._mock_response(payload)

        result = fetch_nearby_planes(33.4, -84.4, 15)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["radius_km"], 15)
        self.assertEqual(result["user_lat"], 33.4)
        self.assertEqual(result["user_lon"], -84.4)
        self.assertTrue(result["fetched_at"].endswith("Z"))
        self.assertEqual(result["planes"][0]["callsign"], "DAL441")

    @mock.patch("tracker.services.requests.get")
    def test_filters_aircraft_without_hex(self, mock_get):
        payload = {
            "msg": "No error",
            "ac": [
                {"flight": "NOHHEX", "lat": 33.0, "lon": -84.2},
                {"hex": "abc123", "flight": "OKHEX", "lat": 33.0, "lon": -84.2},
            ],
        }
        mock_get.return_value = self._mock_response(payload)

        result = fetch_nearby_planes(33.4, -84.4, 15)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["planes"][0]["hex_id"], "abc123")

    @mock.patch("tracker.services.requests.get")
    def test_empty_ac_list(self, mock_get):
        mock_get.return_value = self._mock_response({"msg": "No error", "ac": []})
        result = fetch_nearby_planes(33.4, -84.4, 15)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["planes"], [])

    @mock.patch("tracker.services.requests.get")
    def test_upstream_http_error_raises_unavailable(self, mock_get):
        response = mock.Mock()
        response.raise_for_status.side_effect = requests_exception()
        mock_get.return_value = response

        with self.assertRaises(UpstreamUnavailableError):
            fetch_nearby_planes(33.4, -84.4, 15)

    @mock.patch("tracker.services.requests.get")
    def test_upstream_timeout_raises_timeout_error(self, mock_get):
        mock_get.side_effect = __import__("requests").exceptions.Timeout("timeout")

        with self.assertRaises(UpstreamTimeoutError):
            fetch_nearby_planes(33.4, -84.4, 15)

    @mock.patch("tracker.services.requests.get")
    def test_non_json_response_raises_unavailable(self, mock_get):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("no json")
        mock_get.return_value = response

        with self.assertRaises(UpstreamUnavailableError):
            fetch_nearby_planes(33.4, -84.4, 15)

    @mock.patch("tracker.services.requests.get")
    def test_error_message_in_payload_raises_unavailable(self, mock_get):
        mock_get.return_value = self._mock_response({"msg": "Internal error"})

        with self.assertRaises(UpstreamUnavailableError):
            fetch_nearby_planes(33.4, -84.4, 15)

    @mock.patch("tracker.services.requests.get")
    def test_drops_extra_fields_and_keeps_known_fields(self, mock_get):
        payload = {
            "msg": "No error",
            "ac": [
                {
                    "hex": "a1b2c3",
                    "flight": "SWA123 ",
                    "r": "N123SW",
                    "t": "B738",
                    "alt_baro": 35000,
                    "alt_geom": 37325,
                    "gs": 462.8,
                    "track": 47.28,
                    "baro_rate": 64,
                    "squawk": "7426",
                    "emergency": "none",
                    "lat": 33.369690,
                    "lon": -84.826978,
                }
            ],
        }
        mock_get.return_value = self._mock_response(payload)

        result = fetch_nearby_planes(33.4, -84.4, 15)
        plane = result["planes"][0]

        self.assertEqual(plane["callsign"], "SWA123")
        self.assertEqual(plane["tail_number"], "N123SW")
        self.assertEqual(plane["aircraft_type"], "B738")
        self.assertEqual(plane["altitude_ft"], 35000)
        self.assertEqual(plane["altitude_geom_ft"], 37325)
        self.assertEqual(plane["speed_knots"], 462.8)
        self.assertEqual(plane["track_deg"], 47.28)
        self.assertEqual(plane["vertical_rate_fpm"], 64)
        self.assertEqual(plane["squawk"], "7426")
        self.assertEqual(plane["emergency"], "none")
        self.assertIsNotNone(plane["distance_km"])
        self.assertIsNotNone(plane["bearing"])
        self.assertIsNotNone(plane["liveatc_stream_url"])


def requests_exception():
    import requests

    return requests.exceptions.RequestException("boom")


class NearbyPlanesViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.url = "/api/v1/nearby-planes/"

    @mock.patch("tracker.views.fetch_nearby_planes")
    def test_valid_request_returns_200(self, mock_fetch):
        mock_fetch.return_value = {
            "planes": [
                {
                    "callsign": "DAL441",
                    "tail_number": "N919AT",
                    "hex_id": "acb82c",
                    "distance_km": 86.4,
                    "bearing": 242.0,
                    "altitude_ft": 14425,
                    "altitude_geom_ft": 15400,
                    "speed_knots": 372.8,
                    "track_deg": 76.19,
                    "vertical_rate_fpm": -2368,
                    "aircraft_type": "B712",
                    "squawk": "3473",
                    "emergency": "none",
                    "liveatc_stream_url": feed_stream_url("katl_ztl22"),
                }
            ],
            "user_lat": 33.4,
            "user_lon": -84.4,
            "radius_km": 15,
            "count": 1,
            "fetched_at": "2025-01-15T03:41:52Z",
        }

        response = self.client.post(
            self.url,
            {"lat": 33.4, "lon": -84.4, "radius": 15},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_fetch.assert_called_once_with(33.4, -84.4, 15)
        self.assertEqual(response.data["count"], 1)

    def test_missing_fields_returns_400(self):
        response = self.client.post(self.url, {"lat": 33.4}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_radius_out_of_range_returns_400(self):
        response = self.client.post(
            self.url,
            {"lat": 33.4, "lon": -84.4, "radius": 999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch("tracker.views.fetch_nearby_planes")
    def test_timeout_returns_504(self, mock_fetch):
        mock_fetch.side_effect = UpstreamTimeoutError
        response = self.client.post(
            self.url,
            {"lat": 33.4, "lon": -84.4, "radius": 15},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_504_GATEWAY_TIMEOUT)

    @mock.patch("tracker.views.fetch_nearby_planes")
    def test_upstream_unavailable_returns_502(self, mock_fetch):
        mock_fetch.side_effect = UpstreamUnavailableError
        response = self.client.post(
            self.url,
            {"lat": 33.4, "lon": -84.4, "radius": 15},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_405_METHOD_NOT_ALLOWED,))


class RouteParseTests(TestCase):
    SAMPLE_FLIGHTROUTE: ClassVar[dict] = {
        "callsign_iata": "HV75U",
        "airline": {"name": "Transavia Holland", "icao": "TRA", "iata": "HV"},
        "origin": {
            "iata_code": "IBZ",
            "icao_code": "LEIB",
            "name": "Ibiza Airport",
            "municipality": "Ibiza",
            "country_name": "Spain",
        },
        "destination": {
            "iata_code": "AMS",
            "icao_code": "EHAM",
            "name": "Amsterdam Airport Schiphol",
            "municipality": "Amsterdam",
            "country_name": "Netherlands",
        },
    }

    def test_full_flightroute_mapping(self):
        route = _parse_route(self.SAMPLE_FLIGHTROUTE)
        self.assertEqual(route["callsign_iata"], "HV75U")
        self.assertEqual(route["airline_name"], "Transavia Holland")
        self.assertEqual(route["airline_icao"], "TRA")
        self.assertEqual(route["airline_iata"], "HV")
        self.assertEqual(route["origin_iata"], "IBZ")
        self.assertEqual(route["origin_icao"], "LEIB")
        self.assertEqual(route["origin_name"], "Ibiza Airport")
        self.assertEqual(route["origin_city"], "Ibiza")
        self.assertEqual(route["origin_country"], "Spain")
        self.assertEqual(route["destination_iata"], "AMS")
        self.assertEqual(route["destination_icao"], "EHAM")
        self.assertEqual(route["destination_name"], "Amsterdam Airport Schiphol")
        self.assertEqual(route["destination_city"], "Amsterdam")
        self.assertEqual(route["destination_country"], "Netherlands")

    def test_empty_flightroute_all_null(self):
        route = _parse_route({})
        self.assertTrue(all(value is None for value in route.values()))

    def test_missing_sections_all_null(self):
        route = _parse_route({"callsign_iata": "DL441"})
        self.assertEqual(route["callsign_iata"], "DL441")
        self.assertIsNone(route["airline_name"])
        self.assertIsNone(route["origin_iata"])
        self.assertIsNone(route["destination_iata"])


class FetchRouteTests(TestCase):
    def setUp(self):
        services._route_cache.clear()

    def _mock_response(self, payload):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    @mock.patch("tracker.services.requests.get")
    def test_falsy_callsign_returns_none_without_network(self, mock_get):
        self.assertIsNone(fetch_route(""))
        self.assertIsNone(fetch_route(None))
        mock_get.assert_not_called()

    @mock.patch("tracker.services.requests.get")
    def test_fetches_full_route(self, mock_get):
        mock_get.return_value = self._mock_response(
            {"response": {"flightroute": RouteParseTests.SAMPLE_FLIGHTROUTE}}
        )
        route = fetch_route("TRA75U")
        self.assertIsNotNone(route)
        self.assertEqual(route["origin_iata"], "IBZ")
        self.assertEqual(route["destination_iata"], "AMS")

    @mock.patch("tracker.services.requests.get")
    def test_callsign_normalized_to_uppercase_in_url(self, mock_get):
        mock_get.return_value = self._mock_response(
            {"response": {"flightroute": RouteParseTests.SAMPLE_FLIGHTROUTE}}
        )
        fetch_route("  tra75u ")
        self.assertTrue(mock_get.call_args[0][0].endswith("/callsign/TRA75U"))

    @mock.patch("tracker.services.requests.get")
    def test_no_flightroute_payload_returns_none(self, mock_get):
        mock_get.return_value = self._mock_response({"response": "No flightroute found"})
        self.assertIsNone(fetch_route("TRA75U"))

    @mock.patch("tracker.services.requests.get")
    def test_non_dict_payload_returns_none(self, mock_get):
        mock_get.return_value = self._mock_response("unexpected")
        self.assertIsNone(fetch_route("TRA75U"))

    @mock.patch("tracker.services.requests.get")
    def test_http_error_returns_none(self, mock_get):
        response = mock.Mock()
        response.raise_for_status.side_effect = requests_exception()
        mock_get.return_value = response
        self.assertIsNone(fetch_route("TRA75U"))

    @mock.patch("tracker.services.requests.get")
    def test_timeout_returns_none(self, mock_get):
        mock_get.side_effect = __import__("requests").exceptions.Timeout("timeout")
        self.assertIsNone(fetch_route("TRA75U"))

    @mock.patch("tracker.services.requests.get")
    def test_caches_successful_hits(self, mock_get):
        mock_get.return_value = self._mock_response(
            {"response": {"flightroute": RouteParseTests.SAMPLE_FLIGHTROUTE}}
        )
        first = fetch_route("TRA75U")
        second = fetch_route("TRA75U")
        self.assertEqual(first, second)
        self.assertEqual(mock_get.call_count, 1)

    @mock.patch("tracker.services.requests.get")
    def test_caches_empty_results(self, mock_get):
        mock_get.return_value = self._mock_response({"response": "No flightroute found"})
        self.assertIsNone(fetch_route("TRA75U"))
        self.assertIsNone(fetch_route("TRA75U"))
        self.assertEqual(mock_get.call_count, 1)

    @mock.patch("tracker.services.requests.get")
    def test_cache_key_is_case_insensitive(self, mock_get):
        mock_get.return_value = self._mock_response(
            {"response": {"flightroute": RouteParseTests.SAMPLE_FLIGHTROUTE}}
        )
        fetch_route("tra75u")
        fetch_route("TRA75U")
        self.assertEqual(mock_get.call_count, 1)

    @mock.patch("tracker.services.requests.get")
    def test_negative_cache_after_exception(self, mock_get):
        mock_get.side_effect = __import__("requests").exceptions.Timeout("timeout")
        self.assertIsNone(fetch_route("TRA75U"))
        self.assertIsNone(fetch_route("TRA75U"))
        self.assertEqual(mock_get.call_count, 1)


class RouteEnrichmentTests(TestCase):
    def setUp(self):
        services._route_cache.clear()
        services._photo_cache.clear()
        services._last_photo_http_at = 0.0

    def _mock_response(self, payload):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    @mock.patch("tracker.services.requests.get")
    def test_fetch_nearby_planes_enriches_routes(self, mock_get):
        adsb_payload = {
            "msg": "No error",
            "ac": [
                {"hex": "484e32", "flight": "TRA75U ", "lat": 33.36, "lon": -84.82},
                {"hex": "a1b2c3", "flight": "N123GA", "lat": 33.0, "lon": -84.5},
            ],
        }

        def fake_get(url, timeout=None, headers=None):
            request_url = str(url)
            if "adsbdb.com" in request_url:
                if request_url.endswith("/callsign/N123GA"):
                    return self._mock_response({"response": "No flightroute found"})
                return self._mock_response(
                    {"response": {"flightroute": RouteParseTests.SAMPLE_FLIGHTROUTE}}
                )
            return self._mock_response(adsb_payload)

        mock_get.side_effect = fake_get

        result = fetch_nearby_planes(33.4, -84.4, 15)
        tra75u = next(p for p in result["planes"] if p["callsign"] == "TRA75U")
        n123ga = next(p for p in result["planes"] if p["callsign"] == "N123GA")

        self.assertEqual(tra75u["route"]["origin_iata"], "IBZ")
        self.assertEqual(tra75u["route"]["destination_iata"], "AMS")
        self.assertIsNone(n123ga["route"])


class FetchClosestPlaneTests(TestCase):
    def _result(self, planes):
        return {
            "planes": planes,
            "user_lat": 33.4,
            "user_lon": -84.4,
            "radius_km": 15,
            "count": len(planes),
            "fetched_at": "2025-01-15T03:41:52Z",
        }

    def _plane(self, callsign, distance_km, altitude_ft, route):
        return {
            "callsign": callsign,
            "distance_km": distance_km,
            "altitude_ft": altitude_ft,
            "route": route,
        }

    @mock.patch("tracker.services.fetch_nearby_planes")
    def test_returns_closest_airborne_plane_with_route(self, mock_fetch):
        mock_fetch.return_value = self._result(
            [
                self._plane("GND", 1.0, "ground", {"z": 1}),
                self._plane("NOROUTE", 2.0, 35000, None),
                self._plane("FAR", 20.0, 25000, {"z": 1}),
                self._plane("CLOSE", 3.5, 12000, {"z": 1}),
            ]
        )

        result = fetch_closest_plane(33.4, -84.4)
        self.assertEqual(result["plane"]["callsign"], "CLOSE")
        mock_fetch.assert_called_once_with(33.4, -84.4, 15)

    @mock.patch("tracker.services.fetch_nearby_planes")
    def test_excludes_planes_with_unknown_position(self, mock_fetch):
        mock_fetch.return_value = self._result(
            [
                self._plane("NOPOS", None, 10000, {"z": 1}),
                self._plane("NEXT", 5.0, 9000, {"z": 1}),
            ]
        )

        result = fetch_closest_plane(33.4, -84.4)
        self.assertEqual(result["plane"]["callsign"], "NEXT")

    @mock.patch("tracker.services.fetch_nearby_planes")
    def test_no_candidates_returns_null_plane(self, mock_fetch):
        mock_fetch.return_value = self._result(
            [
                self._plane("GND", 1.0, "ground", {"z": 1}),
                self._plane("NOROUTE", 2.0, 35000, None),
            ]
        )

        result = fetch_closest_plane(33.4, -84.4)
        self.assertIsNone(result["plane"])

    @mock.patch("tracker.services.fetch_nearby_planes")
    def test_empty_list_returns_null_plane(self, mock_fetch):
        mock_fetch.return_value = self._result([])

        result = fetch_closest_plane(33.4, -84.4)
        self.assertIsNone(result["plane"])

    @mock.patch("tracker.services.fetch_nearby_planes")
    def test_passes_radius_through(self, mock_fetch):
        mock_fetch.return_value = self._result([])

        fetch_closest_plane(33.4, -84.4, 50)
        mock_fetch.assert_called_once_with(33.4, -84.4, 50)


class ClosestPlaneViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.url = "/api/v1/closest/"

    def _result_with_plane(self):
        return {
            "plane": {
                "callsign": "TRA75U",
                "tail_number": "PH-TFN",
                "hex_id": "484e32",
                "distance_km": 12.04,
                "bearing": 200.0,
                "altitude_ft": 37000,
                "altitude_geom_ft": 39000,
                "speed_knots": 450.0,
                "track_deg": 90.0,
                "vertical_rate_fpm": 0,
                "aircraft_type": "B738",
                "squawk": "1234",
                "emergency": "none",
                "liveatc_stream_url": None,
                "route": {
                    "callsign_iata": "HV75U",
                    "airline_name": "Transavia Holland",
                    "airline_icao": "TRA",
                    "airline_iata": "HV",
                    "origin_iata": "IBZ",
                    "origin_icao": "LEIB",
                    "origin_name": "Ibiza Airport",
                    "origin_city": "Ibiza",
                    "origin_country": "Spain",
                    "destination_iata": "AMS",
                    "destination_icao": "EHAM",
                    "destination_name": "Amsterdam Airport Schiphol",
                    "destination_city": "Amsterdam",
                    "destination_country": "Netherlands",
                },
            },
            "user_lat": 33.4,
            "user_lon": -84.4,
            "radius_km": 15,
            "fetched_at": "2025-01-15T03:41:52Z",
        }

    def _result_without_plane(self):
        return {
            "plane": None,
            "user_lat": 33.4,
            "user_lon": -84.4,
            "radius_km": 15,
            "fetched_at": "2025-01-15T03:41:52Z",
        }

    @mock.patch("tracker.views.fetch_closest_plane")
    def test_valid_request_returns_plane(self, mock_fetch):
        mock_fetch.return_value = self._result_with_plane()

        response = self.client.post(
            self.url,
            {"lat": 33.4, "lon": -84.4, "radius": 15},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_fetch.assert_called_once_with(33.4, -84.4, 15)
        self.assertEqual(response.data["plane"]["callsign"], "TRA75U")
        self.assertEqual(response.data["plane"]["route"]["destination_iata"], "AMS")

    @mock.patch("tracker.views.fetch_closest_plane")
    def test_no_plane_returns_nulls(self, mock_fetch):
        mock_fetch.return_value = self._result_without_plane()

        response = self.client.post(
            self.url,
            {"lat": 33.4, "lon": -84.4, "radius": 15},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["plane"])

    def test_missing_fields_returns_400(self):
        response = self.client.post(self.url, {"lat": 33.4}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_radius_out_of_range_returns_400(self):
        response = self.client.post(
            self.url,
            {"lat": 33.4, "lon": -84.4, "radius": 999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch("tracker.views.fetch_closest_plane")
    def test_timeout_returns_504(self, mock_fetch):
        mock_fetch.side_effect = UpstreamTimeoutError
        response = self.client.post(
            self.url,
            {"lat": 33.4, "lon": -84.4, "radius": 15},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_504_GATEWAY_TIMEOUT)

    @mock.patch("tracker.views.fetch_closest_plane")
    def test_upstream_unavailable_returns_502(self, mock_fetch):
        mock_fetch.side_effect = UpstreamUnavailableError
        response = self.client.post(
            self.url,
            {"lat": 33.4, "lon": -84.4, "radius": 15},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_405_METHOD_NOT_ALLOWED,))


class RouteSerializationTests(TestCase):
    def _plane_data(self, route):
        return {
            "callsign": "TRA75U",
            "tail_number": None,
            "hex_id": "484e32",
            "distance_km": 12.04,
            "bearing": None,
            "altitude_ft": 37000,
            "altitude_geom_ft": None,
            "speed_knots": 450.0,
            "track_deg": None,
            "vertical_rate_fpm": None,
            "aircraft_type": "B738",
            "squawk": None,
            "emergency": "none",
            "liveatc_stream_url": None,
            "route": route,
        }

    def test_plane_serializer_includes_route(self):
        data = self._plane_data(
            {"origin_iata": "IBZ", "destination_iata": "AMS", "airline_name": "Transavia Holland"}
        )
        serialized = PlaneSerializer(data).data
        self.assertEqual(serialized["route"]["origin_iata"], "IBZ")
        self.assertEqual(serialized["route"]["destination_iata"], "AMS")

    def test_plane_serializer_null_route(self):
        serialized = PlaneSerializer(self._plane_data(None)).data
        self.assertIsNone(serialized["route"])

    def test_plane_serializer_liveatc_frequency(self):
        data = self._plane_data(None)
        data["liveatc_frequency"] = "125.750"
        serialized = PlaneSerializer(data).data
        self.assertEqual(serialized["liveatc_frequency"], "125.750")


class PhotoParseTests(TestCase):
    SAMPLE_PHOTO: ClassVar[dict] = {
        "id": "1486276",
        "thumbnail": {"src": "https://t.plnspttrs.net/35887/1486276_c90c106203_t.jpg", "size": {"width": 200, "height": 125}},
        "thumbnail_large": {"src": "https://t.plnspttrs.net/35887/1486276_c90c106203_280.jpg", "size": {"width": 448, "height": 280}},
        "link": "https://www.planespotters.net/photo/1486276/n311az-amazon-prime-air-boeing-767-338er-bdsf?utm_source=api",
        "photographer": "Donald e Moore",
    }

    def test_full_photo_mapping(self):
        photo = _parse_photo(self.SAMPLE_PHOTO)
        self.assertEqual(photo["url"], "https://t.plnspttrs.net/35887/1486276_c90c106203_280.jpg")
        self.assertEqual(photo["thumbnail_url"], "https://t.plnspttrs.net/35887/1486276_c90c106203_t.jpg")
        self.assertEqual(photo["photographer"], "Donald e Moore")
        self.assertTrue(photo["link"].startswith("https://www.planespotters.net/photo/1486276/"))

    def test_partial_photo_null_fields(self):
        photo = _parse_photo({"id": "1"})
        self.assertIsNone(photo["url"])
        self.assertIsNone(photo["thumbnail_url"])
        self.assertIsNone(photo["photographer"])
        self.assertIsNone(photo["link"])


class FetchPhotoTests(TestCase):
    def setUp(self):
        services._photo_cache.clear()
        services._last_photo_http_at = 0.0

    def _mock_response(self, payload):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    @mock.patch("tracker.services.requests.get")
    def test_falsy_hex_returns_none_without_network(self, mock_get):
        self.assertIsNone(fetch_plane_photo(""))
        self.assertIsNone(fetch_plane_photo(None))
        mock_get.assert_not_called()

    @mock.patch("tracker.services.requests.get")
    def test_fetches_first_photo(self, mock_get):
        mock_get.return_value = self._mock_response({"photos": [PhotoParseTests.SAMPLE_PHOTO]})
        photo = fetch_plane_photo("A34AA0")
        self.assertEqual(photo["url"], "https://t.plnspttrs.net/35887/1486276_c90c106203_280.jpg")
        self.assertEqual(photo["photographer"], "Donald e Moore")

    @mock.patch("tracker.services.requests.get")
    def test_hex_lowercased_in_url_and_ua_header_sent(self, mock_get):
        mock_get.return_value = self._mock_response({"photos": [PhotoParseTests.SAMPLE_PHOTO]})
        fetch_plane_photo("A34AA0")
        url, kwargs = mock_get.call_args
        self.assertTrue(url[0].endswith("/photos/hex/a34aa0"))
        self.assertIsNotNone(kwargs["headers"].get("User-Agent"))

    @mock.patch("tracker.services.requests.get")
    def test_empty_photos_returns_none(self, mock_get):
        mock_get.return_value = self._mock_response({"photos": []})
        self.assertIsNone(fetch_plane_photo("a34aa0"))

    @mock.patch("tracker.services.requests.get")
    def test_non_dict_payload_returns_none(self, mock_get):
        mock_get.return_value = self._mock_response("unexpected")
        self.assertIsNone(fetch_plane_photo("a34aa0"))

    @mock.patch("tracker.services.requests.get")
    def test_http_error_returns_none(self, mock_get):
        response = mock.Mock()
        response.raise_for_status.side_effect = requests_exception()
        mock_get.return_value = response
        self.assertIsNone(fetch_plane_photo("a34aa0"))

    @mock.patch("tracker.services.requests.get")
    def test_timeout_returns_none(self, mock_get):
        mock_get.side_effect = __import__("requests").exceptions.Timeout("timeout")
        self.assertIsNone(fetch_plane_photo("a34aa0"))

    @mock.patch("tracker.services.requests.get")
    def test_caches_successful_hits(self, mock_get):
        mock_get.return_value = self._mock_response({"photos": [PhotoParseTests.SAMPLE_PHOTO]})
        first = fetch_plane_photo("a34aa0")
        second = fetch_plane_photo("a34aa0")
        self.assertEqual(first, second)
        self.assertEqual(mock_get.call_count, 1)

    @mock.patch("tracker.services.requests.get")
    def test_cache_key_is_case_insensitive(self, mock_get):
        mock_get.return_value = self._mock_response({"photos": [PhotoParseTests.SAMPLE_PHOTO]})
        fetch_plane_photo("A34AA0")
        fetch_plane_photo("a34aa0")
        self.assertEqual(mock_get.call_count, 1)

    @mock.patch("tracker.services.requests.get")
    def test_negative_cache_after_exception(self, mock_get):
        mock_get.side_effect = __import__("requests").exceptions.Timeout("timeout")
        self.assertIsNone(fetch_plane_photo("a34aa0"))
        self.assertIsNone(fetch_plane_photo("a34aa0"))
        self.assertEqual(mock_get.call_count, 1)


class PhotoIsolationTests(TestCase):
    @mock.patch("tracker.services.requests.get")
    def test_fetch_nearby_planes_does_not_call_planespotters(self, mock_get):
        requested_urls = []
        adsb_payload = {
            "msg": "No error",
            "ac": [
                {"hex": "a34aa0", "flight": "ATN3320 ", "lat": 33.53, "lon": -84.45},
                {"hex": "a1b2c3", "flight": "N123GA", "lat": 33.0, "lon": -84.5},
            ],
        }

        def fake_get(url, timeout=None, headers=None):
            requested_urls.append(str(url))
            if "adsbdb.com" in str(url):
                return self._mock_response({"response": "unknown callsign"})
            return self._mock_response(adsb_payload)

        mock_get.side_effect = fake_get

        result = fetch_nearby_planes(33.4, -84.4, 15)

        self.assertEqual(result["count"], 2)
        self.assertNotIn("photo", result["planes"][0])
        self.assertNotIn("photo", result["planes"][1])
        self.assertFalse(any("planespotters" in url for url in requested_urls))

    def _mock_response(self, payload):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response


class PlanePhotoViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.url = "/api/v1/photo/a34aa0/"

    @mock.patch("tracker.views.fetch_plane_photo")
    def test_returns_photo(self, mock_fetch):
        mock_fetch.return_value = {
            "url": "https://t.plnspttrs.net/35887/1486276_c90c106203_280.jpg",
            "thumbnail_url": "https://t.plnspttrs.net/35887/1486276_c90c106203_t.jpg",
            "photographer": "Donald e Moore",
            "link": "https://www.planespotters.net/photo/1486276/n311az-amazon-prime-air-boeing-767-338er-bdsf?utm_source=api",
        }

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_fetch.assert_called_once_with("a34aa0")
        self.assertEqual(response.data["hex_id"], "a34aa0")
        self.assertEqual(response.data["photo"]["photographer"], "Donald e Moore")

    @mock.patch("tracker.views.fetch_plane_photo")
    def test_returns_null_photo(self, mock_fetch):
        mock_fetch.return_value = None

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["hex_id"], "a34aa0")
        self.assertIsNone(response.data["photo"])

    def test_invalid_hex_returns_400(self):
        response = self.client.get("/api/v1/photo/zzzzzz/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_length_returns_400(self):
        response = self.client.get("/api/v1/photo/a34a/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_not_allowed(self):
        response = self.client.post(self.url)
        self.assertIn(response.status_code, (status.HTTP_405_METHOD_NOT_ALLOWED,))


class PlanePhotoResponseSerializerTests(TestCase):
    def test_serializes_photo(self):
        data = {"hex_id": "a34aa0", "photo": {"photographer": "Donald e Moore"}}
        out = PlanePhotoResponseSerializer(data).data
        self.assertEqual(out["hex_id"], "a34aa0")
        self.assertEqual(out["photo"]["photographer"], "Donald e Moore")

    def test_serializes_null_photo(self):
        out = PlanePhotoResponseSerializer({"hex_id": "a34aa0", "photo": None}).data
        self.assertIsNone(out["photo"])


class UrlTests(TestCase):
    def test_nearby_planes_endpoint_resolves(self):
        match = resolve("/api/v1/nearby-planes/")
        self.assertIs(match.func.view_class, NearbyPlanesView)

    def test_closest_endpoint_resolves(self):
        match = resolve("/api/v1/closest/")
        self.assertIs(match.func.view_class, ClosestPlaneView)

    def test_plane_photo_endpoint_resolves(self):
        match = resolve("/api/v1/photo/a34aa0/")
        self.assertIs(match.func.view_class, PlanePhotoView)

    def test_plane_atc_endpoint_resolves(self):
        match = resolve("/api/v1/atc/")
        self.assertIs(match.func.view_class, PlaneAtcView)