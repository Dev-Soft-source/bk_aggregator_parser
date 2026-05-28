import os
from dataclasses import dataclass

from dotenv import load_dotenv

from fonbet.config import FonbetApiConfig  # noqa: F401 — re-export for callers

load_dotenv()

DEFAULT_SITE_NAME = "fonbet.com"
# Keep snapshot audit rows for current calendar year only (0 = disable auto-prune).
DEFAULT_RETAIN_SNAPSHOT_YEARS = 1


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str
    site_name: str
    retain_snapshot_years: int

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            return cls.from_url(database_url)

        return cls(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            name=os.getenv("DB_NAME", "booker_adapter"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
            site_name=os.getenv("SITE_NAME", DEFAULT_SITE_NAME),
            retain_snapshot_years=int(
                os.getenv("RETAIN_SNAPSHOT_YEARS", str(DEFAULT_RETAIN_SNAPSHOT_YEARS))
            ),
        )

    @classmethod
    def from_url(cls, database_url: str) -> "DatabaseConfig":
        # postgresql://user:pass@host:port/dbname
        if not database_url.startswith("postgresql://"):
            raise ValueError("DATABASE_URL must start with postgresql://")

        body = database_url[len("postgresql://") :]
        userinfo, _, hostpart = body.partition("@")
        user, _, password = userinfo.partition(":")
        host, _, dbname = hostpart.partition("/")
        hostname, _, port = host.partition(":")

        return cls(
            host=hostname or "localhost",
            port=int(port or "5432"),
            name=dbname,
            user=user,
            password=password,
            site_name=os.getenv("SITE_NAME", DEFAULT_SITE_NAME),
            retain_snapshot_years=int(
                os.getenv("RETAIN_SNAPSHOT_YEARS", str(DEFAULT_RETAIN_SNAPSHOT_YEARS))
            ),
        )

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.name} "
            f"user={self.user} password={self.password}"
        )
