# MyPup Home Assistant Integration (`mypup-ha`)

Home Assistant custom integration and standalone verification CLI for **MyPup** (My Pick Up Point).

> **Note & Disclaimer:** This is an unofficial integration and is not affiliated with, endorsed by, or supported by MyPup. All code in this repository was written by an LLM under human supervision and design decisions; individual scripts were not manually verified line-by-line by a human, though every available feature was tested by a human (mostly against real-world data).

## Features

- **Passwordless OAuth Silent Renewal:** Authenticates via your `login.mypup.app` session cookies using `prompt=none` silent renewal (no username/password stored). Includes a short-lived Access Token fallback and automatic HA re-authentication prompts if the session eventually expires.
- **Configurable Options:** Set polling interval (`1–60` min), shipment fetch limit (`5–50`), and pickup PIN/QR fetching during setup or anytime under **Configure**.
- **Parcel Sensors:**
  - **Incoming parcels** (`_incoming_parcels`) — pre-locker states (`Registered`, `Arrived`, `WaitForLocker`, `LockerAssigned`) with a `parcels` attribute.
  - **Parcels ready for pickup** (`_parcels_ready_for_pickup`) — `ReadyForPickup` parcels with `parcels` attribute (including `locker`, `pin`, `qr_code`, `shipment_uid`, `reference_no`, `description`).
  - **Previous parcels** (`_previous_parcels`) — completed/historical parcels with a `parcels` attribute.
  - **All parcels** (`_all_parcels` / `_total_parcels` on existing installs) — all tracked parcels with a `parcels` attribute (including `pin` and `qr_code` for `ReadyForPickup` items).
  - **Main pickup point** (`_main_pickup_point`) — assigned pickup point name, `mail_code`, `pup_uid`, and `delivery_address_lines`.
- **Buttons & Services:**
  - **Unlock ready locker** button (`button.*_unlock_ready_locker`) & **Refresh parcels** button (`button.*_refresh_parcels`).
  - **`mypup.unlock_locker`** action (supports `shipment_uid`, `locker`, `config_entry_id`, and optional response data).
- **Automation Events:**
  - `mypup_parcel_incoming` — fired when a shipment enters an incoming state (after startup).
  - `mypup_parcel_ready` — fired when a shipment transitions to `ReadyForPickup` (includes `locker`, `pin`, `qr_code`, etc.).
- **Diagnostics:** Download redacted diagnostics directly from the integration page.

## Installation (HACS)

1. In Home Assistant, open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/LuukDomhof/mypup-ha` as **Integration**.
3. Install **MyPup** and perform a **full Home Assistant restart**.
4. Go to **Settings → Devices & services → Add integration → MyPup** and follow the **Session Cookie** (recommended) or **Access Token** steps.

## Dashboard Examples

See [EXAMPLES.md](EXAMPLES.md) for copy-paste dashboard cards covering **Ready for Pickup**, **Incoming**, **Previous**, and **All Parcels** in two styles:
- **Basic Home Assistant** (built-in Markdown card, no custom cards required)
- **Streamline Card + Mushroom** (`custom:streamline-card` + `custom:mushroom-template-card`)

## Standalone Verification CLI

```powershell
python test_mypup.py
python test_mypup.py --test-renew
```
