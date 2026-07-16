from django.urls import path

from pulp_nuget.app.views import PackagePublishView, SymbolPackagePublishView

urlpatterns = [
    path("pulp_nuget/publish/<path:base_path>", PackagePublishView.as_view()),
    path("pulp_nuget/publish-symbols/<path:base_path>", SymbolPackagePublishView.as_view()),
]
