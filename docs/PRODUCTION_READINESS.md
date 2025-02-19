# Production readiness

An honest assessment of what this project is today and what it still needs before it
can be exposed to untrusted users on the internet.

## What it is

A **single-user, local-first** analytics application. It is designed for one trusted
operator analysing their own data on their own machine, with an optional hosted model
provider. Every analytical result is reproducible and every figure is traceable back to
a dataset hash.

## What it is not

It is **not** a multi-tenant SaaS product. There is no authentication, no
authorisation, no rate limiting and no tenant isolation. The dataset scope is per
*request*, not per *user*.

## Readiness by area

| Area | State | Notes |
|---|---|---|
| Analytical correctness | Ready | KPI values are asserted against independently computed references; property-based tests cover the invariants. |
| Evidence & reproducibility | Ready | Every answer stores the hash, version, row counts, filters, formula and the tool trace. |
| Tool boundary | Ready | Closed registry, strict schemas, bound parameters, allow-listed identifiers, adversarial tests. |
| Import safety | Ready | Extension allow-list, size cap, zip-bomb checks, read-only parsing, path containment. |
| Secret handling | Ready for local use | Encrypted at rest, masked in the API, never logged. Use a secret manager for a hosted deployment. |
| Observability | Ready | Structured JSON logs, `X-Request-ID` on every request, a durable audit table. |
| Performance | Good for local use | DuckDB over Parquet; typical demo analyses complete in 30–150 ms. |
| Accessibility | Good | Semantic HTML, labelled controls, focus rings, keyboard navigation, `prefers-reduced-motion`. |
| Authentication | **Missing** | Add an identity provider before exposing the service. |
| Authorisation | **Missing** | Dataset access is not scoped to a user. |
| Rate limiting | **Missing** | Add it at the reverse proxy or in the app. |
| Multi-tenancy | **Missing** | Do not market this as tenant-isolated. |
| Horizontal scaling | Unproven | SQLite is the default; the DuckDB artefact store is local to the process. |
| Backup / DR | Documented | See the migration notes below. |

## Deployment topologies that work today

1. **Local single user** - `uvicorn` + `npm run dev`, or the compiled bundle served by
   the API.
2. **Single-tenant internal server** - Docker Compose, one instance, an SSH tunnel or
   a VPN, with the operator's own credentials. The provider key stays server-side.
3. **Read-only demo server** - deploy with `DEFAULT_PROVIDER=free` so that no data
   ever leaves the host. This is the safest way to show the product.

## Backup and migration

```bash
# 1. Stop the application
# 2. Copy the metadata database and the managed directories
cp data/app.db      /backup/app-$(date +%F).db
tar czf /backup/data-$(date +%F).tar.gz data/uploads data/artifacts data/demo

# 3. Restore
cp /backup/app-2024-05-17.db data/app.db
tar xzf /backup/data-2024-05-17.tar.gz
```

Migrating to PostgreSQL:

```bash
export DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/tda'
```

The schema is created automatically on start-up (`Base.metadata.create_all`). For a
production database, manage the schema with Alembic instead and take a dump before
each release.

## Retention

* Uploaded files and artefacts are removed when the dataset is deleted.
* Analysis records, conversations and audit entries are retained until the database is
  cleared; export them with the JSON endpoints and prune as required.
* Provider keys are stored only in `provider_configs`; remove the configuration
  through the settings API to delete them.

## Before you go live

1. Add authentication and per-user dataset authorisation.
2. Put the service behind TLS and a rate limiter.
3. Move secrets to a secret manager and rotate the provider keys.
4. Switch to PostgreSQL and manage the schema with Alembic.
5. Set `CORS_ORIGINS` to the exact origins you need and enable
   `ALLOW_CREDENTIALED_CORS` only if you use cookies.
6. Back up the database and the `data` directory on a schedule and test a restore.
7. Review `SECURITY.md` and add the missing controls to your threat model.
