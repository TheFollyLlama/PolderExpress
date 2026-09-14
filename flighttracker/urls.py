from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("", TemplateView.as_view(template_name="tracker/index.html"), name="index"),
    path(
        "closest/",
        TemplateView.as_view(template_name="tracker/closest.html"),
        name="closest-page",
    ),
    path("admin/", admin.site.urls),
    path("api/v1/", include("tracker.urls")),
]