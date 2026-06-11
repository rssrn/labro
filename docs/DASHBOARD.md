# Metrics Dashboard

**Live example:** [labro.rossarnold.uk](https://labro.rossarnold.uk/)

> **⚠️ Data sensitivity:** the published snapshot contains private-repo prose — task descriptions, summaries, failure reasons, and item URLs from your monitored repositories. The dashboard ships **no built-in access control**. The bucket URL is the only barrier. Keep it private: do not share it, embed it in public pages, or link to it from anywhere indexable. See [ADR-0007](adr/0007-metrics-dashboard.md) for the accepted risk posture and the deferred Cloudflare Access / column-redaction options.

The dashboard is a read-only static SPA (React + Vite + sql.js) served from Cloudflare R2. It loads a published snapshot of `labro.db` client-side and renders a runs list, per-project stats, and charts. It has no runtime link to the harness and cannot affect runs.

## 1. Create an R2 bucket and bind a custom domain

In the Cloudflare dashboard, create an R2 bucket, then generate an S3 API token scoped to it (Account → R2 → Manage R2 API tokens). Note the access key ID, secret key, and your Cloudflare account ID.

Bind a **custom domain** to the bucket (bucket → Settings → Custom Domains). The SPA, `/manifest.json`, and `/db/*.db` must share the same origin so DB fetches are same-origin and no CORS headers are needed.

## 2. Configure `[dashboard]` in `labro.toml`

```toml
[dashboard]
enabled    = true
bucket     = "my-labro-dashboard"   # R2 bucket name
key_prefix = ""                     # optional path prefix inside the bucket
cron       = "17 * * * *"           # snapshot publish frequency
title      = "Labro Dashboard for My Projects"  # optional; customises the dashboard header
```

When `enabled = true`, `labro gen-crontab` emits a `labro publish-db` cron line automatically and `labro check` validates the three `R2_*` env vars.

## 3. Set R2 credentials

Add `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_ACCOUNT_ID` to:
- the VPS `.env` file (see [Config Repo](DEPLOYMENT.md#config-repo))
- your config-repo GitHub Secrets (for the `dashboard-publish.yml` workflow)

## 4. Publish the first snapshot

```bash
labro publish-db --dry-run   # prints hashed db_key + manifest JSON; no upload, no creds required
labro publish-db             # uploads snapshot to R2 (db first, then manifest)
```

After the first successful upload, `manifest.json` and `db/labro-<hash>.db` appear in the R2 bucket.

## 5. Deploy the SPA

Copy `docs/config-repo-scaffold/dashboard-publish.yml` into `.github/workflows/` in your config repo and add the four R2 secrets. Push to trigger the first build and upload. Once deployed, open your custom domain — the dashboard loads data from the published snapshot.

The SPA rebuilds automatically when `dashboard/**` changes on labro `main` (dispatched via `dashboard-dispatch.yml`). Snapshot publishing runs independently on the cron in `[dashboard]`.
