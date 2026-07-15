from django.urls import path

from pulp_nuget.app.views import PackagePublishView

urlpatterns = [
    path("pulp_nuget/publish/<path:base_path>", PackagePublishView.as_view()),
]
