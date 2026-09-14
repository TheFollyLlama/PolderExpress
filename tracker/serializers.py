from rest_framework import serializers


class NearbyPlanesRequestSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    radius = serializers.IntegerField(min_value=1, max_value=250, default=15)


class RouteSerializer(serializers.Serializer):
    callsign_iata = serializers.CharField(allow_null=True, required=False)
    airline_name = serializers.CharField(allow_null=True, required=False)
    airline_icao = serializers.CharField(allow_null=True, required=False)
    airline_iata = serializers.CharField(allow_null=True, required=False)
    origin_iata = serializers.CharField(allow_null=True, required=False)
    origin_icao = serializers.CharField(allow_null=True, required=False)
    origin_name = serializers.CharField(allow_null=True, required=False)
    origin_city = serializers.CharField(allow_null=True, required=False)
    origin_country = serializers.CharField(allow_null=True, required=False)
    destination_iata = serializers.CharField(allow_null=True, required=False)
    destination_icao = serializers.CharField(allow_null=True, required=False)
    destination_name = serializers.CharField(allow_null=True, required=False)
    destination_city = serializers.CharField(allow_null=True, required=False)
    destination_country = serializers.CharField(allow_null=True, required=False)


class PhotoSerializer(serializers.Serializer):
    url = serializers.CharField(allow_null=True, required=False)
    thumbnail_url = serializers.CharField(allow_null=True, required=False)
    photographer = serializers.CharField(allow_null=True, required=False)
    link = serializers.CharField(allow_null=True, required=False)


class PlanePhotoResponseSerializer(serializers.Serializer):
    hex_id = serializers.CharField()
    photo = PhotoSerializer(allow_null=True)


class PlaneSerializer(serializers.Serializer):
    callsign = serializers.CharField()
    tail_number = serializers.CharField(allow_null=True)
    hex_id = serializers.CharField()
    distance_km = serializers.FloatField(allow_null=True)
    bearing = serializers.FloatField(allow_null=True)
    altitude_ft = serializers.JSONField(allow_null=True)
    altitude_geom_ft = serializers.IntegerField(allow_null=True)
    speed_knots = serializers.FloatField(allow_null=True)
    track_deg = serializers.FloatField(allow_null=True)
    vertical_rate_fpm = serializers.IntegerField(allow_null=True)
    aircraft_type = serializers.CharField(allow_null=True)
    squawk = serializers.CharField(allow_null=True)
    emergency = serializers.CharField()
    liveatc_stream_url = serializers.CharField(allow_null=True)
    route = RouteSerializer(allow_null=True, required=False)


class NearbyPlanesResponseSerializer(serializers.Serializer):
    planes = PlaneSerializer(many=True)
    user_lat = serializers.FloatField()
    user_lon = serializers.FloatField()
    radius_km = serializers.IntegerField()
    count = serializers.IntegerField()
    fetched_at = serializers.CharField()


class ClosestPlaneResponseSerializer(serializers.Serializer):
    plane = PlaneSerializer(allow_null=True)
    user_lat = serializers.FloatField()
    user_lon = serializers.FloatField()
    radius_km = serializers.IntegerField()
    fetched_at = serializers.CharField()


class AtcFeedSerializer(serializers.Serializer):
    name = serializers.CharField()
    kind = serializers.CharField()
    stream_url = serializers.CharField()
    distance_km = serializers.FloatField()
    altitude_ceiling_ft = serializers.IntegerField(allow_null=True, required=False)


class AtcFeedResponseSerializer(serializers.Serializer):
    feed = AtcFeedSerializer(allow_null=True)


class AtcFeedRequestSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    altitude = serializers.CharField(required=False, allow_blank=True, default=None)