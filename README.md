# Philips Air+ Cloud for Home Assistant

![Philips Air+ Cloud logo](custom_components/philips_airplus_cloud/brand/logo.png)

Custom Home Assistant integration for Air+ cloud-connected air purifiers.

This integration is intended for newer Air+ devices that no longer work with the
older local CoAP integrations. It uses the same cloud account and remote-control
path as the official Air+ app.

## Compatibility

Tested with:

- Philips AC1715/10

Other Air+ models may work, but they are not confirmed yet. Some telemetry and
control codes appear to be model-specific, so sensors or controls may need
adjustments for other devices in the same family.

## Install

### HACS

Add this repository as a custom integration repository in HACS:

```text
https://github.com/bartoszj5/ha-philips-airplus
```

Then install `Philips Air+ Cloud`, restart Home Assistant, and add it from:

```text
Settings -> Devices & services -> Add integration -> Philips Air+ Cloud
```

### Manual

Copy `custom_components/philips_airplus_cloud` into your Home Assistant
configuration directory:

```text
/config/custom_components/philips_airplus_cloud/
```

Restart Home Assistant, then add the integration from:

```text
Settings -> Devices & services -> Add integration -> Philips Air+ Cloud
```

## Login

The Air+ OAuth flow redirects to the Air+ mobile app, so Home Assistant cannot
receive the callback directly. During setup, the integration shows a login URL.
Open it in your browser, sign in, then paste the final redirect URL, the `code`
value, or the browser console line containing it.

In most desktop browsers:

1. Open Developer Tools -> Console before signing in.
2. Open the login URL and finish the Air+ login.
3. Copy the console line that starts with `Failed to launch
   'com.philips.air://loginredirect?code=...'`.
4. Paste that line into the Home Assistant config flow.

The redirect URL starts with:

```text
com.philips.air://loginredirect?code=...
```

## Entities

The integration creates entities based on the data reported by your device.

Confirmed on Philips AC1715/10:

- Power switch
- Display light switch
- Mode select
- Fan mode select
- PM2.5 sensor
- Allergen index sensor
- Main filter remaining hours sensor
- Pre-filter remaining hours sensor
- Product state sensor
- Product error sensor
- Host firmware sensor
- NCP firmware sensor

## Reporting other models

If you use another Air+ model and some entities are missing or incorrect, please
open a compatibility report with:

- exact model number, for example `AC1715/10`
- integration version or commit
- what works and what is missing or wrong

There is also a diagnostic helper used to inspect Air+ NCP ports:

```text
tools/airplus_ncp_probe.py
```

This helper is optional, but it can make compatibility reports much more useful.
It logs in with your Air+ account, connects to the Air+ cloud, and prints the
ports reported by your device.

Example:

```bash
python3 -m pip install websocket-client
python3 tools/airplus_probe.py --save-token .airplus_token.json
python3 tools/airplus_ncp_probe.py --seconds 30
```

Never upload `.airplus_token.json`. Before posting probe output publicly, redact
account IDs, tokens, signatures, device identifiers, and any values you consider
private.
