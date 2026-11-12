from typing import Any, cast

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.capabilities import Capability, can, location_ids_for
from accounts.models import User
from accounts.permissions import requires, requires_any
from accounts.visibility import cost_context

from . import services
from .models import CashRegister, CashSession, Customer, Sale, StoreCredit
from .serializers import (
    CashMovementSerializer,
    CloseSessionSerializer,
    CustomerSerializer,
    OpenSessionSerializer,
    RegisterSerializer,
    SaleInputSerializer,
    SaleSerializer,
    SessionSerializer,
    StoreCreditSerializer,
)

Sellers = requires(Capability.POS_SELL)
TillOperators = requires(Capability.POS_CASH)


def _user(request: Request) -> User:
    return cast(User, request.user)


class CustomerViewSet(viewsets.ModelViewSet[Customer]):
    serializer_class = CustomerSerializer
    permission_classes = (Sellers,)
    http_method_names = ("get", "post", "patch", "head", "options")

    def get_queryset(self) -> QuerySet[Customer]:
        customers = Customer.objects.all()
        query = self.request.query_params.get("q", "").strip()
        if query:
            digits = "".join(ch for ch in query if ch.isdigit())
            customers = customers.filter(name__icontains=query) | (
                customers.filter(cpf__startswith=digits) if digits else customers.none()
            )
        return customers


class RegisterViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet[CashRegister]):
    serializer_class = RegisterSerializer
    permission_classes = (requires_any(Capability.POS_CASH, Capability.LOCATIONS_MANAGE),)

    def get_queryset(self) -> QuerySet[CashRegister]:
        return CashRegister.objects.filter(location_id__in=location_ids_for(_user(self.request))).select_related(
            "location"
        )

    def perform_create(self, serializer: RegisterSerializer) -> None:  # type: ignore[override]
        if not can(self.request.user, Capability.LOCATIONS_MANAGE):
            raise PermissionDenied("Só o proprietário cadastra caixas.")
        serializer.save()


class SessionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[CashSession]):
    serializer_class = SessionSerializer
    permission_classes = (TillOperators,)
    filterset_fields = ("register",)

    def get_queryset(self) -> QuerySet[CashSession]:
        user = _user(self.request)
        sessions = CashSession.objects.select_related("register__location", "opened_by", "closed_by")
        # Managers see their stores' tills; a cashier sees their own shifts.
        if can(user, Capability.APPROVALS_GRANT):
            return sessions.filter(register__location_id__in=location_ids_for(user))
        return sessions.filter(opened_by=user)

    def create(self, request: Request) -> Response:
        data = OpenSessionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        session = services.open_session(user=_user(request), **data.validated_data)
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def current(self, request: Request) -> Response:
        session = services.open_session_of(_user(request))
        return Response({**SessionSerializer(session).data, "summary": services.session_summary(session)})

    @action(detail=True, methods=["get"])
    def summary(self, request: Request, pk: str) -> Response:
        return Response(services.session_summary(self.get_object()))

    @action(detail=True, methods=["post"])
    def movements(self, request: Request, pk: str) -> Response:
        data = CashMovementSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        movement = services.move_cash(user=_user(request), session=self.get_object(), **data.validated_data)
        return Response(CashMovementSerializer(movement).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: str) -> Response:
        data = CloseSessionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        session = services.close_session(user=_user(request), session=self.get_object(), **data.validated_data)
        return Response({**SessionSerializer(session).data, "summary": services.session_summary(session)})


class SaleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[Sale]):
    serializer_class = SaleSerializer
    permission_classes = (Sellers,)
    filterset_fields = ("location", "status", "session", "number")

    def get_queryset(self) -> QuerySet[Sale]:
        return (
            Sale.objects.filter(location_id__in=location_ids_for(_user(self.request)))
            .select_related("location", "cashier", "salesperson", "customer")
            .prefetch_related("payments")
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return cost_context(super().get_serializer_context(), self.request)

    def create(self, request: Request) -> Response:
        data = SaleInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        sale, created = services.create_sale(
            user=_user(request),
            client_request_id=values["client_request_id"],
            items=[services.ItemInput(**item) for item in values["items"]],
            payments=[services.PaymentInput(**payment) for payment in values["payments"]],
            discount=values["discount"],
            customer=values["customer"],
            salesperson=values["salesperson"],
            approval_id=values["approval"],
        )
        body = SaleSerializer(self.get_queryset().get(pk=sale.pk), context=self.get_serializer_context()).data
        # A retried request gets the sale it already made, with 200 instead of 201.
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class StoreCreditView(APIView):
    permission_classes = (Sellers,)

    def get(self, request: Request, code: str) -> Response:
        credit = get_object_or_404(StoreCredit.objects.select_related("customer"), code=code.strip().upper())
        return Response(StoreCreditSerializer(credit).data)
