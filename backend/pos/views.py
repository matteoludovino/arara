from typing import Any, cast

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
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
from .models import CashRegister, CashSession, Customer, Sale, SaleReturn, StoreCredit
from .serializers import (
    CancelSaleSerializer,
    CashMovementSerializer,
    CloseSessionSerializer,
    CustomerSerializer,
    ExchangeInputSerializer,
    OpenSessionSerializer,
    RegisterSerializer,
    ReturnInputSerializer,
    ReturnSerializer,
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
    queryset = CashRegister.objects.none()  # the model, for the schema: get_queryset scopes it to the user
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
    queryset = CashSession.objects.none()  # the model, for the schema: get_queryset scopes it to the user
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
    queryset = Sale.objects.none()  # the model, for the schema: get_queryset scopes it to the user
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

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str) -> Response:
        data = CancelSaleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        sale = services.cancel_sale(user=_user(request), sale=self.get_object(), reason=data.validated_data["reason"])
        return Response(SaleSerializer(sale, context=self.get_serializer_context()).data)


class ReturnViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[SaleReturn]):
    queryset = SaleReturn.objects.none()  # the model, for the schema: get_queryset scopes it to the user
    serializer_class = ReturnSerializer
    permission_classes = (Sellers,)
    filterset_fields = ("location", "original_sale")

    def get_queryset(self) -> QuerySet[SaleReturn]:
        return SaleReturn.objects.filter(location_id__in=location_ids_for(_user(self.request))).select_related(
            "location", "original_sale", "store_credit", "created_by"
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return cost_context(super().get_serializer_context(), self.request)

    def create(self, request: Request) -> Response:
        data = ReturnInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        sale_return = services.return_items(
            user=_user(request),
            location=values["location"],
            lines=[_return_line(line) for line in values["lines"]],
            refund_method=values["refund_method"],
            reason=values["reason"],
            original_sale=values["sale"],
            customer=values["customer"],
            approval_id=values["approval"],
        )
        return Response(
            ReturnSerializer(sale_return, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED
        )


def _return_line(line: dict[str, Any]) -> services.ReturnInput:
    return services.ReturnInput(quantity=line["quantity"], sale_item_id=line["sale_item"], variant=line["variant"])


class ExchangeView(APIView):
    """A return and a new sale at once: the credit from the return pays first."""

    permission_classes = (Sellers,)

    @extend_schema(request=ExchangeInputSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = ExchangeInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        sale_return, sale = services.exchange(
            user=_user(request),
            client_request_id=values["client_request_id"],
            original_sale=values["sale"],
            returned=[_return_line(line) for line in values["returned"]],
            reason=values["reason"],
            items=[services.ItemInput(**item) for item in values["items"]],
            payments=[services.PaymentInput(**payment) for payment in values["payments"]],
            approval_id=values["approval"],
        )
        context = cost_context({}, request)
        assert sale_return.store_credit_id is not None  # an exchange always refunds in store credit
        credit = StoreCredit.objects.get(pk=sale_return.store_credit_id)  # read again: the sale just spent from it
        return Response(
            {
                "return": ReturnSerializer(sale_return, context=context).data,
                "sale": SaleSerializer(sale, context=context).data,
                "store_credit": StoreCreditSerializer(credit).data,
            },
            status=status.HTTP_201_CREATED,
        )


class StoreCreditView(APIView):
    permission_classes = (Sellers,)

    @extend_schema(responses=StoreCreditSerializer)
    def get(self, request: Request, code: str) -> Response:
        credit = get_object_or_404(StoreCredit.objects.select_related("customer"), code=code.strip().upper())
        return Response(StoreCreditSerializer(credit).data)
