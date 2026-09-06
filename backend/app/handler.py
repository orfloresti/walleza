"""AWS Lambda entrypoint.

`lifespan="off"` is required, not optional (design D1): Mangum's default
behavior re-runs the ASGI lifespan (startup/shutdown) on every single
invocation, which would defeat the module-scope engine in `app/db.py` by
rebuilding connection-pool state on every request instead of once per
cold start. With the lifespan off, the module-level singletons imported
via `app.main` (settings, engine) are what actually persist across warm
invocations of the same Lambda execution environment.
"""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
