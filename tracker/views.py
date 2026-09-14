import math
from typing import ClassVar

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from tracker.serializers import (
    AtcFeedRequestSerializer,
    AtcFeedResponseSerializer,
    ClosestPlaneResponseSerializer,
    NearbyPlanesRequestSerializer,
    NearbyPlanesResponseSerializer,
    PlanePhotoResponseSerializer,
)
from tracker.services import (
    UpstreamTimeoutError,
    UpstreamUnavailableError,
    fetch_atc_feed,
    fetch_closest_plane,
    fetch_nearby_planes,
    fetch_plane_photo,
)


class NearbyPlanesView(APIView):
    http_method_names: ClassVar[list[str]] = ["post"]

    def post(self, request):
        serializer = NearbyPlanesRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "lat, lon, and radius required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        try:
            result = fetch_nearby_planes(data["lat"], data["lon"], data["radius"])
        except UpstreamTimeoutError:
            return Response(
                {"error": "upstream request timed out"},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except UpstreamUnavailableError:
            return Response(
                {"error": "upstream adsb.lol unavailable"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response_serializer = NearbyPlanesResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class ClosestPlaneView(APIView):
    http_method_names: ClassVar[list[str]] = ["post"]

    def post(self, request):
        serializer = NearbyPlanesRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "lat, lon, and radius required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        try:
            result = fetch_closest_plane(data["lat"], data["lon"], data["radius"])
        except UpstreamTimeoutError:
            return Response(
                {"error": "upstream request timed out"},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except UpstreamUnavailableError:
            return Response(
                {"error": "upstream adsb.lol unavailable"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response_serializer = ClosestPlaneResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class PlanePhotoView(APIView):
    http_method_names: ClassVar[list[str]] = ["get"]

    def get(self, request, hex_id):
        if len(hex_id) != 6 or any(c not in "0123456789abcdefABCDEF" for c in hex_id):
            return Response(
                {"error": "hex_id must be a 6-character ICAO hex code"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        photo = fetch_plane_photo(hex_id)
        response_serializer = PlanePhotoResponseSerializer(
            {"hex_id": hex_id, "photo": photo}
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class PlaneAtcView(APIView):
    http_method_names: ClassVar[list[str]] = ["get"]

    def get(self, request):
        serializer = AtcFeedRequestSerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        lat = data["lat"]
        lon = data["lon"]
        if lat < -90 or lat > 90:
            return Response(
                {"error": "lat must be between -90 and 90"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if lon < -180 or lon > 180:
            return Response(
                {"error": "lon must be between -180 and 180"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        altitude_raw = data.get("altitude")
        if altitude_raw is None or altitude_raw == "":
            altitude_ft = None
        elif altitude_raw.strip().lower() == "ground":
            altitude_ft = "ground"
        else:
            try:
                altitude_ft = float(altitude_raw)
            except (TypeError, ValueError):
                return Response(
                    {"error": "altitude must be a number in feet or 'ground'"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not math.isfinite(altitude_ft) or altitude_ft <= 0:
                return Response(
                    {"error": "altitude must be a number in feet or 'ground'"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        feed = fetch_atc_feed(lat, lon, altitude_ft)
        response_serializer = AtcFeedResponseSerializer({"feed": feed})
        return Response(response_serializer.data, status=status.HTTP_200_OK)