"""
Read-only reports. Sales reports need reports.sales (margin and cost of goods only with
reports.margin); stock reports are valued at cost, so they need costs.view as well.
Everything is limited to the locations the user works at; ?location= narrows it to one.
"""

from datetime import date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.capabilities import Capability, can, location_ids_for
from accounts.models import Role, User
from accounts.permissions import requires
from catalog.models import Product
from locations.models import Location

from . import services

MARGIN_FIELDS = ("cogs", "margin", "margin_percent")
LOCATION = OpenApiParameter("location", int, description="One location (default: all of yours).")
PERIOD = [
    OpenApiParameter("from", OpenApiTypes.DATE, description="First day (default: 29 days before `to`)."),
    OpenApiParameter("to", OpenApiTypes.DATE, description="Last day, inclusive (default: today)."),
    LOCATION,
]


def _date(request: Request, name: str) -> date | None:
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({name: "Data inválida: use AAAA-MM-DD."}) from None


def _int(request: Request, name: str, default: int, low: int, high: int) -> int:
    raw = request.query_params.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValidationError({name: "Número inválido."}) from None
    if not low <= value <= high:
        raise ValidationError({name: f"Entre {low} e {high}."})
    return value


def scope(request: Request, *, with_transit: bool = False) -> list[int]:
    """The locations to report on. Goods in transit belong to the company, not to a store."""
    user = cast(User, request.user)
    ids = location_ids_for(user)
    if request.query_params.get("location"):
        chosen = _int(request, "location", 0, 1, 2**63 - 1)
        if chosen not in ids:
            raise PermissionDenied("Você não tem acesso a este local.")
        return [chosen]
    if with_transit and user.role == Role.OWNER:
        ids += Location.objects.filter(kind=Location.Kind.TRANSIT).values_list("pk", flat=True)
    return ids


def _span(request: Request) -> services.Period:
    return services.period(_date(request, "from"), _date(request, "to"))


def _without_margin(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in MARGIN_FIELDS}


class SalesSummaryView(APIView):
    permission_classes = (requires(Capability.REPORTS_SALES),)

    @extend_schema(parameters=PERIOD, responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        report = services.sales_summary(scope(request), _span(request))
        if not can(request.user, Capability.REPORTS_MARGIN):
            report["days"] = [_without_margin(day) for day in cast(list[dict[str, Any]], report["days"])]
            report["total"] = _without_margin(cast(dict[str, Any], report["total"]))
        return Response(report)


class SalespeopleView(APIView):
    permission_classes = (requires(Capability.REPORTS_SALES),)

    @extend_schema(parameters=PERIOD, responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        return Response(services.by_salesperson(scope(request), _span(request)))


class AbcView(APIView):
    permission_classes = (requires(Capability.REPORTS_SALES),)

    @extend_schema(parameters=PERIOD, responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        return Response(services.abc_curve(scope(request), _span(request)))


class SizeColorView(APIView):
    permission_classes = (requires(Capability.REPORTS_SALES),)

    @extend_schema(parameters=[*PERIOD, OpenApiParameter("product", int, required=True)], responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        product = get_object_or_404(Product, pk=_int(request, "product", 0, 1, 2**63 - 1))
        return Response(services.size_color_matrix(scope(request), _span(request), product))


StockReports = requires(Capability.REPORTS_SALES, Capability.COSTS_VIEW)


class ValuationView(APIView):
    permission_classes = (StockReports,)

    @extend_schema(
        parameters=[
            OpenApiParameter("at", OpenApiTypes.DATE, description="At the close of this day (default: now)."),
            LOCATION,
        ],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request: Request) -> Response:
        day = _date(request, "at")
        if day is None or day >= timezone.localdate():
            moment = timezone.now()
        else:
            moment = datetime.combine(day + timedelta(days=1), time.min, tzinfo=ZoneInfo(settings.TIME_ZONE))
        return Response(services.valuation(scope(request, with_transit=True), moment))


class TurnoverView(APIView):
    permission_classes = (StockReports,)

    @extend_schema(parameters=PERIOD, responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        return Response(services.turnover(scope(request), _span(request)))


class StaleView(APIView):
    permission_classes = (StockReports,)

    @extend_schema(
        parameters=[OpenApiParameter("days", int, description="No sale for this many days (default 60)."), LOCATION],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request: Request) -> Response:
        return Response(services.stale_products(scope(request), _int(request, "days", 60, 1, 365)))
