"""Shared URL and engine configuration for API, migrations and DB utilities."""
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


def normalize_database_url(url: str) -> str:
    if not url:
        return url
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+asyncpg")
    return parsed.render_as_string(hide_password=False)


def create_database_engine(url: str, **options):
    if not url:
        raise RuntimeError("DATABASE_URL is not set — add it to your environment variables.")
    parsed = make_url(normalize_database_url(url))
    connect_args = dict(options.pop("connect_args", {}))
    if parsed.drivername == "postgresql+asyncpg":
        query = dict(parsed.query)
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)  # libpq option, not an asyncpg keyword
        ssl = query.pop("ssl", None)
        if sslmode is not None and ssl is not None:
            raise ValueError("Specify only one PostgreSQL TLS option")
        mode = sslmode if sslmode is not None else ssl
        if mode is not None and mode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("Unsupported PostgreSQL SSL mode; TLS is required")
        if "ssl" in connect_args:
            raise ValueError("Configure PostgreSQL TLS through the database URL")
        connect_args["ssl"] = mode or "require"
        parsed = parsed.set(query=query)
    options.setdefault("echo", False)
    options.setdefault("pool_pre_ping", True)
    return create_async_engine(parsed, connect_args=connect_args, **options)
