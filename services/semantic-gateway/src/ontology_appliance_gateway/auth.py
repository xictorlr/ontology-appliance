"""Tenant and role extraction for local development and Firebase Auth."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .errors import ApiProblem


BEARER_SCHEME = HTTPBearer(
    auto_error=False,
    scheme_name="FirebaseBearer",
    description=(
        "Firebase session cookie in production; a Firebase ID token is supported when "
        "OA_AUTH_MODE=firebase-id-token, a trusted Google service token is supported in "
        "hybrid mode, and a documented dev token is accepted locally."
    ),
)


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=256)
    roles: frozenset[str]
    auth_mode: str

    def has_any_role(self, allowed: set[str]) -> bool:
        return bool(self.roles.intersection(allowed))


def _roles_from_claim(value: object) -> frozenset[str]:
    if isinstance(value, str):
        roles = value.split(",")
    elif isinstance(value, list):
        roles = [str(item) for item in value]
    elif isinstance(value, dict):
        roles = [str(key) for key, enabled in value.items() if enabled]
    else:
        roles = []
    normalized = {role.strip().lower() for role in roles if role.strip()}
    return frozenset(normalized.intersection({"admin", "steward", "auditor"}))


def _dev_principal(settings: Settings, authorization: str | None) -> Principal:
    if not settings.is_development:
        raise ApiProblem(
            500,
            "Invalid authentication configuration",
            "Development authentication cannot run outside a development environment.",
            code="unsafe-dev-auth",
        )

    if not authorization:
        return Principal(
            tenant_id=settings.dev_tenant_id,
            user_id="local-developer",
            roles=frozenset({"admin", "steward", "auditor"}),
            auth_mode="dev-default",
        )

    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.startswith("dev:"):
        raise ApiProblem(
            401,
            "Invalid development credential",
            "Use a development bearer token or omit Authorization for the fixed local tenant.",
            code="invalid-dev-token",
        )
    parts = value.split(":", 3)
    if len(parts) != 4:
        raise ApiProblem(
            401,
            "Invalid development credential",
            "Expected dev:<tenant>:<user>:<comma-separated-roles>.",
            code="invalid-dev-token",
        )
    _, tenant_id, user_id, roles_raw = parts
    if not tenant_id or not user_id:
        raise ApiProblem(
            401,
            "Invalid development credential",
            "Tenant and user are required.",
            code="invalid-dev-token",
        )
    if tenant_id != settings.dev_tenant_id and not settings.allow_dev_tenant_override:
        raise ApiProblem(
            403,
            "Development tenant override disabled",
            f"Only tenant '{settings.dev_tenant_id}' is enabled locally.",
            code="tenant-not-allowed",
        )
    roles = _roles_from_claim(roles_raw)
    if not roles:
        raise ApiProblem(
            403, "No recognized role", "At least one valid role is required.", code="missing-role"
        )
    return Principal(tenant_id=tenant_id, user_id=user_id, roles=roles, auth_mode="dev-token")


def _firebase_principal(settings: Settings, authorization: str | None) -> Principal:
    if not authorization:
        raise ApiProblem(
            401,
            "Authentication required",
            "A Firebase bearer credential is required.",
            code="missing-token",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiProblem(
            401, "Invalid authorization header", "Expected a Bearer token.", code="invalid-token"
        )

    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth
    except ImportError as exc:  # pragma: no cover - production packaging guard
        raise ApiProblem(
            503,
            "Authentication provider unavailable",
            "Firebase authentication support is not installed.",
            code="firebase-unavailable",
        ) from exc

    try:
        firebase_admin.get_app()
    except ValueError:
        options = (
            {"projectId": settings.firebase_project_id} if settings.firebase_project_id else None
        )
        try:
            firebase_admin.initialize_app(options=options)
        except ValueError:
            # A concurrent first request may have initialized the default app.
            firebase_admin.get_app()

    try:
        if settings.auth_mode in {"firebase-session", "hybrid"}:
            decoded = firebase_auth.verify_session_cookie(token, check_revoked=True)
            resolved_auth_mode = "firebase-session"
        else:
            decoded = firebase_auth.verify_id_token(token, check_revoked=True)
            resolved_auth_mode = "firebase-id-token"
    except Exception as exc:  # Firebase exposes several credential exception types.
        raise ApiProblem(
            401,
            "Invalid Firebase credential",
            "Firebase credential verification or revocation checking failed.",
            code="invalid-token",
        ) from exc

    tenant_id = decoded.get("tenant_id")
    if not tenant_id:
        raise ApiProblem(
            403,
            "Tenant claim required",
            "The authenticated identity is not assigned to a tenant.",
            code="missing-tenant-claim",
        )
    if str(tenant_id) != settings.dev_tenant_id:
        raise ApiProblem(
            403,
            "Tenant not enabled",
            "The authenticated tenant is not served by this gateway instance.",
            code="tenant-not-allowed",
        )
    roles = _roles_from_claim(decoded.get("roles") or decoded.get("role"))
    if not roles:
        raise ApiProblem(
            403,
            "Role claim required",
            "No supported application role was found.",
            code="missing-role",
        )
    return Principal(
        tenant_id=str(tenant_id),
        user_id=str(decoded.get("uid") or decoded.get("sub")),
        roles=roles,
        auth_mode=resolved_auth_mode,
    )


def _service_principal(
    settings: Settings,
    authorization: str | None,
    requested_tenant: str | None,
) -> Principal:
    if not settings.service_audience or not settings.trusted_service_accounts:
        raise ApiProblem(
            503,
            "Service authentication unavailable",
            "Trusted service authentication is not configured.",
            code="service-auth-unavailable",
        )
    if requested_tenant != settings.dev_tenant_id:
        raise ApiProblem(
            403,
            "Tenant not enabled",
            "The requested tenant is not served by this gateway instance.",
            code="tenant-not-allowed",
        )
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiProblem(
            401,
            "Service authentication required",
            "A Google service identity token is required.",
            code="missing-service-token",
        )
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import id_token as google_id_token

        claims = google_id_token.verify_oauth2_token(
            token,
            GoogleAuthRequest(),
            audience=settings.service_audience,
        )
    except Exception as exc:
        raise ApiProblem(
            401,
            "Invalid service credential",
            "Google service identity verification failed.",
            code="invalid-service-token",
        ) from exc

    issuer = str(claims.get("iss") or "")
    email = str(claims.get("email") or "").lower()
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ApiProblem(
            401,
            "Invalid service credential",
            "Unexpected token issuer.",
            code="invalid-service-token",
        )
    if claims.get("email_verified") is not True or email not in settings.trusted_service_accounts:
        raise ApiProblem(
            403,
            "Service identity not allowed",
            "This service account is not allowed to invoke internal workflows.",
            code="service-not-allowed",
        )
    return Principal(
        tenant_id=settings.dev_tenant_id,
        user_id=email,
        roles=frozenset({"service"}),
        auth_mode="google-service-id-token",
    )


def principal_dependency(settings: Settings) -> Callable[..., Principal]:
    def get_principal(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(BEARER_SCHEME),
    ) -> Principal:
        authorization = request.headers.get("Authorization")
        if credentials is not None:
            authorization = f"{credentials.scheme} {credentials.credentials}"
        if settings.auth_mode == "dev":
            return _dev_principal(settings, authorization)
        if (
            settings.auth_mode == "hybrid"
            and request.headers.get("x-ontology-service-auth") == "google-id-token"
        ):
            return _service_principal(
                settings,
                authorization,
                request.headers.get("x-ontology-tenant-id"),
            )
        if settings.auth_mode in {"firebase", "firebase-id-token", "firebase-session", "hybrid"}:
            return _firebase_principal(settings, authorization)
        raise ApiProblem(
            500,
            "Unsupported authentication mode",
            f"Authentication mode '{settings.auth_mode}' is not supported.",
            code="invalid-auth-mode",
        )

    return get_principal


def require_roles(principal: Principal, *roles: str) -> None:
    allowed = {role.lower() for role in roles}
    if not principal.has_any_role(allowed):
        raise ApiProblem(
            403,
            "Insufficient role",
            f"One of these roles is required: {', '.join(sorted(allowed))}.",
            code="insufficient-role",
        )
