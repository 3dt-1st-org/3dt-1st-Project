# iOS Flask API Connection Guide

This project uses the Flask web app as the API backend for iOS.
iOS now calls iOS-scoped endpoints:

- `/api/ios/v1/places`
- `/api/ios/v1/weather`
- `/api/ios/v1/docent/script`
- `/api/ios/v1/docent/audio`
- `/api/ios/v1/health`

All iOS requests must include `X-API-Key`.

`/api/ios/v1/weather` response now includes:

- current weather: `temp`, `icon`
- dust info: `dust.pm10`, `dust.pm25`, `dust.grade`
- short forecast: `forecast[]` (time, temp, icon)

## 1) Pre-deploy DB schema check (required)

Run this before every deployment:

```bash
DB_DSN="<dsn>" .venv/bin/python scripts/check_ios_db_schema.py
```

Current iOS API SQL is based on real production tables:

- `locallink.gg_restaurant_info`
- `locallink.gyeonggi_events`
- `locallink.attraction_descriptions`
- optional cache: `locallink.docent_script_cache`

## 2) When Flask is deployed, set iOS API URL immediately

Use one of these commands from repository root:

```bash
.venv/bin/python scripts/sync_ios_api_base_url_from_keyvault.py --url https://<deployed-flask-domain> --check
```

or (if Key Vault secret is already prepared):

```bash
.venv/bin/python scripts/sync_ios_api_base_url_from_keyvault.py --secret <secret-name> --check
```

`--check` validates the map/weather endpoints before writing config.

## 3) Configure iOS API key

Set `IOS_API_KEY` in local runtime config:

- `src/frontend/ios/LALA/LALA/Config/AppConfig.local.plist`

Example:

```xml
<key>IOS_API_KEY</key>
<string>your-ios-api-key</string>
```

The value must match server environment variable `IOS_API_KEY`.

## 4) Where the iOS URL is stored

The sync script writes:

- `src/frontend/ios/LALA/LALA/Config/AppConfig.local.plist`

This file is ignored by git and should remain local per environment.

## 5) iOS runtime loading order

iOS resolves API base URL in this order:

1. `Config/AppConfig.local.plist` (`API_BASE_URL`)
2. `Config/AppConfig.plist` (`API_BASE_URL`)
3. `Info.plist` key `LALA_API_BASE_URL`

iOS resolves API key in this order:

1. `Config/AppConfig.local.plist` (`IOS_API_KEY`)
2. `Config/AppConfig.plist` (`IOS_API_KEY`)
3. `Info.plist` key `LALA_IOS_API_KEY`

## 6) Expected URL format

- Must start with `https://` or `http://`
- Do not use `localhost` or `127.0.0.1`

## 7) Quick verification

After syncing config:

1. Build and run the iOS app.
2. Open main map screen.
3. Confirm places and weather are loaded.
4. Long-press a place card, tap `정보 더 듣기 / Hear More Info`, and verify remote docent audio plays.
