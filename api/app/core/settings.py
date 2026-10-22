"""Typed application configuration loaded exclusively from environment.

The module-level compatibility accessors keep the rest of the existing
application readable while ``config`` remains the single typed source of
truth. Do not put credentials or environment-specific values in code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _text(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if raw.strip().lower() in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(part.strip() for part in _text(name, default).split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    app_env: str
    public_api_base_url: str
    frontend_url: str
    cors_allowed_origins: tuple[str, ...]
    jwt_secret: str
    jwt_algorithm: str
    jwt_issuer: str
    jwt_audience: str
    access_token_ttl_minutes: int
    refresh_absolute_ttl_days: int
    refresh_idle_ttl_days: int
    refresh_reuse_grace_seconds: int
    idle_logout_minutes: int
    idle_warning_seconds: int
    refresh_cookie_name: str
    cookie_secure: bool
    cookie_samesite: str
    cookie_domain: str
    entra_enabled: bool
    entra_tenant_id: str
    entra_client_id: str
    entra_client_secret: str
    entra_redirect_uri: str
    entra_role_source: str
    entra_role_admin: str
    entra_role_viewer: str
    entra_group_admin_id: str
    entra_group_viewer_id: str
    entra_allowed_email_domains: tuple[str, ...]
    entra_clock_skew_seconds: int
    entra_prompt: str
    entra_reauth_days: int
    local_auth_enabled: bool
    bootstrap_admin_email: str
    bootstrap_admin_password: str
    login_max_failed_attempts: int
    login_lockout_minutes: int
    wfh_exclusion_enabled: bool
    support_contact_text: str
    database_url: str
    auth_required: bool
    expected_department_labels: tuple[str, ...]
    trust_zoho_presence: bool
    leave_source_priority: tuple[str, ...]
    leave_type_detail_roles: tuple[str, ...]
    min_punch_minutes: int
    leave_upload_max_mb: int

    @classmethod
    def from_env(cls) -> "Settings":
        # Legacy names are only a compatibility bridge for existing local envs.
        legacy_ttl = _int("ACCESS_TTL_SECONDS", 0)
        return cls(
            app_env=_text("APP_ENV", "dev").lower(),
            public_api_base_url=_text("PUBLIC_API_BASE_URL", "http://localhost:8001"),
            frontend_url=_text("FRONTEND_URL", "http://localhost:3001").rstrip("/"),
            cors_allowed_origins=_csv("CORS_ALLOWED_ORIGINS", "http://localhost:3001"),
            jwt_secret=_text("JWT_SECRET"),
            jwt_algorithm=_text("JWT_ALGORITHM", "HS256").upper(),
            jwt_issuer=_text("JWT_ISSUER", "attendance-app"),
            jwt_audience=_text("JWT_AUDIENCE", "attendance-app-web"),
            access_token_ttl_minutes=_int(
                "ACCESS_TOKEN_TTL_MINUTES", legacy_ttl // 60 if legacy_ttl else 30
            ),
            refresh_absolute_ttl_days=_int(
                "REFRESH_ABSOLUTE_TTL_DAYS", _int("REFRESH_ABSOLUTE_DAYS", 30)
            ),
            refresh_idle_ttl_days=_int("REFRESH_IDLE_TTL_DAYS", _int("REFRESH_TTL_DAYS", 7)),
            refresh_reuse_grace_seconds=_int("REFRESH_REUSE_GRACE_SECONDS", 10),
            idle_logout_minutes=_int("IDLE_LOGOUT_MINUTES", 60),
            idle_warning_seconds=_int("IDLE_WARNING_SECONDS", 60),
            refresh_cookie_name=_text("REFRESH_COOKIE_NAME", "att_refresh"),
            cookie_secure=_bool("COOKIE_SECURE", False),
            cookie_samesite=_text("COOKIE_SAMESITE", "lax").lower(),
            cookie_domain=_text("COOKIE_DOMAIN"),
            entra_enabled=_bool("ENTRA_ENABLED", False),
            entra_tenant_id=_text("ENTRA_TENANT_ID"),
            entra_client_id=_text("ENTRA_CLIENT_ID"),
            entra_client_secret=os.environ.get("ENTRA_CLIENT_SECRET", ""),
            entra_redirect_uri=_text(
                "ENTRA_REDIRECT_URI", "http://localhost:8001/api/auth/entra/callback"
            ),
            entra_role_source=_text("ENTRA_ROLE_SOURCE", "roles").lower(),
            entra_role_admin=_text("ENTRA_ROLE_ADMIN", "Admin"),
            entra_role_viewer=_text("ENTRA_ROLE_VIEWER", "Viewer"),
            entra_group_admin_id=_text("ENTRA_GROUP_ADMIN_ID"),
            entra_group_viewer_id=_text("ENTRA_GROUP_VIEWER_ID"),
            entra_allowed_email_domains=tuple(
                domain.lower() for domain in _csv("ENTRA_ALLOWED_EMAIL_DOMAINS")
            ),
            entra_clock_skew_seconds=_int("ENTRA_CLOCK_SKEW_SECONDS", 60),
            entra_prompt=_text("ENTRA_PROMPT", "select_account"),
            entra_reauth_days=_int("ENTRA_REAUTH_DAYS", 7),
            local_auth_enabled=_bool("LOCAL_AUTH_ENABLED", True),
            bootstrap_admin_email=_text(
                "BOOTSTRAP_ADMIN_EMAIL", "admin@attendance.internal"
            ).lower(),
            bootstrap_admin_password=os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", ""),
            login_max_failed_attempts=_int("LOGIN_MAX_FAILED_ATTEMPTS", 5),
            login_lockout_minutes=_int("LOGIN_LOCKOUT_MINUTES", 15),
            wfh_exclusion_enabled=_bool("WFH_EXCLUSION_ENABLED", False),
            support_contact_text=_text("SUPPORT_CONTACT_TEXT"),
            database_url=_text(
                "DATABASE_URL", "postgresql://attendance:attendance@db:5432/attendance"
            ),
            auth_required=_bool("AUTH_REQUIRED", True),
            expected_department_labels=tuple(
                part.strip()
                for part in _text(
                    "EXPECTED_DEPARTMENT_LABELS",
                    "GBS- ENGINEERING CENTRE,Engineering Centre",
                ).split(";")
                if part.strip()
            ),
            trust_zoho_presence=_bool("TRUST_ZOHO_PRESENCE", True),
            leave_source_priority=_csv("LEAVE_SOURCE_PRIORITY", "api,xls"),
            leave_type_detail_roles=tuple(
                role.lower() for role in _csv("LEAVE_TYPE_DETAIL_ROLES", "admin")
            ),
            min_punch_minutes=_int("MIN_PUNCH_MINUTES", 0),
            leave_upload_max_mb=_int("LEAVE_UPLOAD_MAX_MB", 10),
        )

    @property
    def access_token_ttl_seconds(self) -> int:
        return self.access_token_ttl_minutes * 60

    @property
    def entra_authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.entra_tenant_id}"

    @property
    def entra_issuer(self) -> str:
        return f"{self.entra_authority}/v2.0"

    @property
    def entra_jwks_url(self) -> str:
        return f"{self.entra_authority}/discovery/v2.0/keys"

    @property
    def entra_configured(self) -> bool:
        return bool(self.entra_tenant_id and self.entra_client_id and self.entra_client_secret)

    def validate_startup(self) -> None:
        if self.app_env not in {"dev", "prod"}:
            raise RuntimeError("APP_ENV must be dev or prod")
        if len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters")
        if self.jwt_algorithm != "HS256":
            raise RuntimeError("JWT_ALGORITHM must be HS256 for app session JWTs")
        if not self.jwt_issuer:
            raise RuntimeError("JWT_ISSUER is required")
        if not self.jwt_audience:
            raise RuntimeError("JWT_AUDIENCE is required")
        if not 0 < self.access_token_ttl_minutes <= 60:
            raise RuntimeError("ACCESS_TOKEN_TTL_MINUTES must be between 1 and 60")
        if self.refresh_absolute_ttl_days <= 0:
            raise RuntimeError("REFRESH_ABSOLUTE_TTL_DAYS must be positive")
        if self.refresh_idle_ttl_days <= 0:
            raise RuntimeError("REFRESH_IDLE_TTL_DAYS must be positive")
        if self.refresh_reuse_grace_seconds < 0:
            raise RuntimeError("REFRESH_REUSE_GRACE_SECONDS cannot be negative")
        if self.idle_logout_minutes < 0 or self.idle_warning_seconds < 0:
            raise RuntimeError("idle logout settings cannot be negative")
        if self.cookie_samesite not in {"lax", "strict", "none"}:
            raise RuntimeError("COOKIE_SAMESITE must be lax, strict, or none")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true when COOKIE_SAMESITE=none")
        if not self.refresh_cookie_name:
            raise RuntimeError("REFRESH_COOKIE_NAME is required")
        if not self.cors_allowed_origins or "*" in self.cors_allowed_origins:
            raise RuntimeError("CORS_ALLOWED_ORIGINS must contain explicit origins")
        if self.entra_enabled:
            for name, value in (
                ("ENTRA_TENANT_ID", self.entra_tenant_id),
                ("ENTRA_CLIENT_ID", self.entra_client_id),
                ("ENTRA_CLIENT_SECRET", self.entra_client_secret),
                ("ENTRA_REDIRECT_URI", self.entra_redirect_uri),
            ):
                if not value and self.app_env == "prod":
                    raise RuntimeError(f"{name} is required when ENTRA_ENABLED=true in prod")
            if self.entra_role_source not in {"roles", "groups"}:
                raise RuntimeError("ENTRA_ROLE_SOURCE must be roles or groups")
        if self.app_env == "prod" and not self.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true in prod")


config = Settings.from_env()


def validate_startup() -> None:
    config.validate_startup()


def __getattr__(name: str):
    """Compatibility names while callers move to the typed settings object."""
    aliases = {
        "JWT_SECRET": "jwt_secret", "JWT_ALGORITHM": "jwt_algorithm",
        "JWT_ISSUER": "jwt_issuer", "JWT_AUDIENCE": "jwt_audience",
        "ACCESS_TOKEN_TTL_MINUTES": "access_token_ttl_minutes",
        "ACCESS_TTL_SECONDS": "access_token_ttl_seconds",
        "REFRESH_ABSOLUTE_TTL_DAYS": "refresh_absolute_ttl_days",
        "REFRESH_ABSOLUTE_DAYS": "refresh_absolute_ttl_days",
        "REFRESH_IDLE_TTL_DAYS": "refresh_idle_ttl_days",
        "REFRESH_TTL_DAYS": "refresh_idle_ttl_days",
        "REFRESH_REUSE_GRACE_SECONDS": "refresh_reuse_grace_seconds",
        "IDLE_LOGOUT_MINUTES": "idle_logout_minutes",
        "IDLE_WARNING_SECONDS": "idle_warning_seconds",
        "REFRESH_COOKIE_NAME": "refresh_cookie_name", "COOKIE_SECURE": "cookie_secure",
        "COOKIE_SAMESITE": "cookie_samesite", "COOKIE_DOMAIN": "cookie_domain",
        "ENTRA_ENABLED": "entra_enabled", "ENTRA_TENANT_ID": "entra_tenant_id",
        "ENTRA_CLIENT_ID": "entra_client_id", "ENTRA_CLIENT_SECRET": "entra_client_secret",
        "ENTRA_REDIRECT_URI": "entra_redirect_uri", "ENTRA_ROLE_SOURCE": "entra_role_source",
        "ENTRA_ROLE_ADMIN": "entra_role_admin", "ENTRA_ROLE_VIEWER": "entra_role_viewer",
        "ENTRA_GROUP_ADMIN_ID": "entra_group_admin_id",
        "ENTRA_GROUP_VIEWER_ID": "entra_group_viewer_id",
        "ENTRA_ALLOWED_EMAIL_DOMAINS": "entra_allowed_email_domains",
        "ENTRA_CLOCK_SKEW_SECONDS": "entra_clock_skew_seconds",
        "ENTRA_PROMPT": "entra_prompt", "ENTRA_REAUTH_DAYS": "entra_reauth_days",
        "LOCAL_AUTH_ENABLED": "local_auth_enabled",
        "BOOTSTRAP_ADMIN_EMAIL": "bootstrap_admin_email",
        "BOOTSTRAP_ADMIN_PASSWORD": "bootstrap_admin_password",
        "LOGIN_MAX_FAILED_ATTEMPTS": "login_max_failed_attempts",
        "LOGIN_LOCKOUT_MINUTES": "login_lockout_minutes",
        "WFH_EXCLUSION_ENABLED": "wfh_exclusion_enabled",
        "SUPPORT_CONTACT_TEXT": "support_contact_text",
        "PUBLIC_API_BASE_URL": "public_api_base_url", "FRONTEND_URL": "frontend_url",
        "CORS_ALLOWED_ORIGINS": "cors_allowed_origins", "DATABASE_URL": "database_url",
        "AUTH_REQUIRED": "auth_required",
        "EXPECTED_DEPARTMENT_LABELS": "expected_department_labels",
        "TRUST_ZOHO_PRESENCE": "trust_zoho_presence",
        "LEAVE_SOURCE_PRIORITY": "leave_source_priority",
        "LEAVE_TYPE_DETAIL_ROLES": "leave_type_detail_roles",
        "MIN_PUNCH_MINUTES": "min_punch_minutes", "LEAVE_UPLOAD_MAX_MB": "leave_upload_max_mb",
    }
    if name == "entra_configured":
        return lambda: config.entra_configured
    if name in aliases:
        return getattr(config, aliases[name])
    raise AttributeError(name)
