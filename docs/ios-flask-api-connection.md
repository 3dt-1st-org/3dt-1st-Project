# iOS Flask API Connection Guide

This project uses the Flask web app as the API backend for iOS.
iOS calls the same endpoints used by web:

- `/api/places`
- `/api/weather`

## 1) When Flask is deployed, set iOS API URL immediately

Use one of these commands from repository root:

```bash
.venv/bin/python scripts/sync_ios_api_base_url_from_keyvault.py --url https://<deployed-flask-domain> --check
```

or (if Key Vault secret is already prepared):

```bash
.venv/bin/python scripts/sync_ios_api_base_url_from_keyvault.py --secret <secret-name> --check
```

`--check` validates both endpoints before writing config.

## 2) Where the URL is stored

The script writes:

- `src/frontend/ios/LALA/LALA/Config/AppConfig.local.plist`

This file is ignored by git and should remain local per environment.

## 3) iOS runtime loading order

iOS resolves API base URL in this order:

1. `Config/AppConfig.local.plist` (`API_BASE_URL`)
2. `Config/AppConfig.plist` (`API_BASE_URL`)
3. `Info.plist` key `LALA_API_BASE_URL`

## 4) Expected URL format

- Must start with `https://` or `http://`
- Do not use `localhost` or `127.0.0.1`

## 5) Quick verification

After syncing config:

1. Build and run the iOS app.
2. Open main map screen.
3. Confirm places and weather are loaded (no network/config banner).
