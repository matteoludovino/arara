from typing import Any, cast

from django.contrib.auth import authenticate, login, logout
from django.db.models import QuerySet
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .capabilities import Capability
from .models import User
from .permissions import requires
from .serializers import ApprovalRequestSerializer, ApprovalSerializer, LoginSerializer, MeSerializer, UserSerializer
from .services import grant_approval


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Sets the CSRF cookie, so the SPA can sign in with the token."""

    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)


class LoginView(APIView):
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "credentials"

    def post(self, request: Request) -> Response:
        # DRF only checks CSRF for signed-in users; without this, another site could sign a
        # visitor into an account of its choosing (login CSRF).
        SessionAuthentication().enforce_csrf(request)
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate(request, username=data.validated_data["email"], password=data.validated_data["password"])
        if user is None:
            return Response({"detail": "E-mail ou senha incorretos."}, status=status.HTTP_400_BAD_REQUEST)
        login(request._request, user)
        return Response(MeSerializer(user).data)


class LogoutView(APIView):
    def post(self, request: Request) -> Response:
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        return Response(MeSerializer(cast(User, request.user)).data)


class UserViewSet(viewsets.ModelViewSet[User]):
    """The team. Deactivating someone signs them out at once: an inactive user's session is refused."""

    serializer_class = UserSerializer
    permission_classes = (requires(Capability.USERS_MANAGE),)
    http_method_names = ("get", "post", "patch", "head", "options")

    def get_queryset(self) -> QuerySet[User]:
        return User.objects.prefetch_related("locations")


class ApprovalView(APIView):
    """A manager approves something on the requester's screen, with their own password."""

    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "credentials"

    def post(self, request: Request) -> Response:
        data = ApprovalRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values: dict[str, Any] = dict(data.validated_data)
        approval = grant_approval(
            request=request._request,
            requester=request.user,  # type: ignore[arg-type]
            approver_email=values["approver_email"],
            approver_password=values["approver_password"],
            action=values["action"],
            location=values["location"],
            reason=values["reason"],
            limit=values.get("limit"),
        )
        return Response(ApprovalSerializer(approval).data, status=status.HTTP_201_CREATED)
