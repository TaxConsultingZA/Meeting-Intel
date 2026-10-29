"""One global synthetic test admission, durable across replicas and restarts.

An operator must provision the table in a dedicated shared PostgreSQL database.
The application never creates it, resets it, or refunds an admission.
"""
import asyncio
import ssl
from urllib.parse import urlsplit

import asyncpg
from pydantic import SecretStr

from .contracts import FailureCode
from .providers import ProviderFailure


PERMIT_ID = "meeting-intel-businessai-synthetic-v1"

# The test role cannot reset the counter or impersonate the table owner. Missing
# table/PK, RLS, elevated roles and broader write privileges all fail closed.
STORE_CHECK = """
SELECT NOT r.rolsuper AND NOT r.rolcreaterole AND NOT r.rolcreatedb
 AND NOT r.rolbypassrls AND NOT r.rolreplication
 AND NOT pg_has_role(c.relowner, 'USAGE')
 AND NOT c.relrowsecurity
 AND has_table_privilege(c.oid, 'INSERT')
 AND has_table_privilege(c.oid, 'SELECT')
 AND NOT has_table_privilege(c.oid, 'UPDATE')
 AND NOT has_table_privilege(c.oid, 'DELETE')
 AND NOT has_table_privilege(c.oid, 'TRUNCATE')
 AND NOT has_table_privilege(c.oid, 'TRIGGER')
 AND NOT has_schema_privilege('public', 'CREATE')
 AND EXISTS (
   SELECT 1 FROM pg_constraint p JOIN pg_attribute a
     ON a.attrelid=c.oid AND a.attname='permit_id'
   WHERE p.conrelid=c.oid AND p.contype='p' AND p.conkey=ARRAY[a.attnum]
 )
FROM pg_class c JOIN pg_roles r ON r.rolname=current_user
WHERE c.oid=to_regclass('public.businessai_synthetic_permits')
 AND c.relkind='r'
"""


async def consume_test_permit(database_url: SecretStr) -> None:
    connection = None
    try:
        dsn = database_url.get_secret_value()
        target = urlsplit(dsn)
        if target.scheme not in {"postgres", "postgresql"} or not target.hostname:
            raise ValueError
        async with asyncio.timeout(5):
            connection = await asyncpg.connect(dsn, ssl=ssl.create_default_context(), timeout=3)
            if await connection.fetchval(STORE_CHECK) is not True:
                raise ValueError
            # Autocommit statement: unique key serializes concurrent contenders.
            admitted = await connection.fetchval(
                "INSERT INTO public.businessai_synthetic_permits (permit_id) VALUES ($1) "
                "ON CONFLICT (permit_id) DO NOTHING RETURNING permit_id", PERMIT_ID,
            )
            if admitted != PERMIT_ID:
                raise ValueError
    except asyncio.CancelledError:
        raise
    except Exception:
        raise ProviderFailure(FailureCode.CONFIGURATION) from None
    finally:
        if connection is not None:
            # Never let connection cleanup turn an uncertain admission into a send.
            connection.terminate()
