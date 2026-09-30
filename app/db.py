"""Lakebase connection pool with OAuth token refresh.

Deployed as a Databricks App: PGHOST / PGUSER / PGDATABASE / LAKEBASE_ENDPOINT are injected by the
`postgres` app resource and the app's service principal authenticates the SDK.
Locally: set DATABRICKS_CONFIG_PROFILE and LAKEBASE_ENDPOINT; host and user are resolved via the SDK.
"""
import os
import threading
import time

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DEFAULT_ENDPOINT = "projects/lakebase-search-demo/branches/production/endpoints/primary"

w = WorkspaceClient()
ENDPOINT = os.getenv("LAKEBASE_ENDPOINT", DEFAULT_ENDPOINT)

_token: dict = {"value": None, "at": 0.0}
_lock = threading.Lock()


def _get_token() -> str:
    # Tokens last 1h; refresh every 40 min.
    with _lock:
        if not _token["value"] or time.time() - _token["at"] > 40 * 60:
            _token["value"] = w.postgres.generate_database_credential(endpoint=ENDPOINT).token
            _token["at"] = time.time()
        return _token["value"]


class TokenConnection(psycopg.Connection):
    @classmethod
    def connect(cls, conninfo: str = "", **kwargs):
        kwargs["password"] = _get_token()
        return super().connect(conninfo, **kwargs)


def _conn_kwargs() -> dict:
    host = os.getenv("PGHOST") or w.postgres.get_endpoint(name=ENDPOINT).status.hosts.host
    user = os.getenv("PGUSER") or w.current_user.me().user_name
    return {
        "host": host,
        "port": int(os.getenv("PGPORT", "5432")),
        "dbname": os.getenv("PGDATABASE", "databricks_postgres"),
        "user": user,
        "sslmode": "require",
        "row_factory": dict_row,
        "autocommit": True,
    }


pool = ConnectionPool(
    connection_class=TokenConnection,
    kwargs=_conn_kwargs(),
    min_size=1,
    max_size=8,
    max_lifetime=45 * 60,  # recycle before token expiry
    check=ConnectionPool.check_connection,  # survive scale-to-zero / idle drops
    open=True,
)
