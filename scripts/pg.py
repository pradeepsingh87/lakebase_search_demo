"""Local helper: open a psycopg connection to the Lakebase endpoint with a fresh OAuth token."""
import os
import psycopg
from databricks.sdk import WorkspaceClient

PROFILE = os.getenv("DATABRICKS_CONFIG_PROFILE", "free_edition")
ENDPOINT = os.getenv("LAKEBASE_ENDPOINT", "projects/lakebase-search-demo/branches/production/endpoints/primary")


def connect(dbname: str = "databricks_postgres") -> psycopg.Connection:
    w = WorkspaceClient(profile=PROFILE)
    ep = w.postgres.get_endpoint(name=ENDPOINT)
    token = w.postgres.generate_database_credential(endpoint=ENDPOINT).token
    return psycopg.connect(
        host=ep.status.hosts.host, dbname=dbname, user=w.current_user.me().user_name,
        password=token, sslmode="require", autocommit=True,
    )
