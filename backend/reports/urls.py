from django.urls import path

from . import views

urlpatterns = [
    path("sales", views.SalesSummaryView.as_view(), name="report-sales"),
    path("salespeople", views.SalespeopleView.as_view(), name="report-salespeople"),
    path("abc", views.AbcView.as_view(), name="report-abc"),
    path("size-color", views.SizeColorView.as_view(), name="report-size-color"),
    path("valuation", views.ValuationView.as_view(), name="report-valuation"),
    path("turnover", views.TurnoverView.as_view(), name="report-turnover"),
    path("stale", views.StaleView.as_view(), name="report-stale"),
]
