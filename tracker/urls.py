from django.urls import path

from tracker.views import (
    ClosestPlaneView,
    NearbyPlanesView,
    PlaneAtcView,
    PlanePhotoView,
)

urlpatterns = [
    path("nearby-planes/", NearbyPlanesView.as_view(), name="nearby-planes"),
    path("closest/", ClosestPlaneView.as_view(), name="closest-plane"),
    path("photo/<str:hex_id>/", PlanePhotoView.as_view(), name="plane-photo"),
    path("atc/", PlaneAtcView.as_view(), name="plane-atc"),
]