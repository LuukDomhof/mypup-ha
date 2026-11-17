# MyPup Home Assistant Integration (`mypup-ha`)

Home Assistant custom integration and standalone verification CLI for **MyPup** (My Pick Up Point).

## Features

- **Passwordless OAuth Silent Renewal:** Authenticates via your `login.mypup.app` session cookies using `prompt=none` silent renewal (no username/password stored). Includes a short-lived Access Token fallback and automatic HA re-authentication prompts if the session eventually expires.
- **Configurable Options:** Set polling interval (`1–60` min), shipment fetch limit (`5–100`), and pickup PIN/QR fetching during setup or anytime under **Configure**.
- **Mutually Exclusive Parcel Sensors:**
  - **Incoming parcels** (`_incoming_parcels`) — pre-locker states (`Registered`, `Arrived`, `WaitForLocker`, `LockerAssigned`) with a `parcels` attribute.
  - **Parcels ready for pickup** (`_parcels_ready_for_pickup`) — `ReadyForPickup` parcels with `parcels` attribute (including `locker`, `pin`, `qr_code`, `shipment_uid`, `reference_no`, `description`).
  - **Previous parcels** (`_previous_parcels`) — completed/historical parcels with a `parcels` attribute.
  - **Total parcels** (`_total_parcels`) — overall parcel count.
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

### Markdown Card (Ready Parcels)
```yaml
type: markdown
title: MyPup Parcels Ready
content: >
  {% set parcels = state_attr('sensor.mypup_my_pickup_point_parcels_ready_for_pickup', 'parcels') or [] %}
  {% if parcels | count == 0 %}
  No parcels ready for pickup.
  {% else %}
  {% for p in parcels %}
  - **{{ p.description or p.reference_no }}** — Locker **{{ p.locker }}** | PIN: `{{ p.pin or 'N/A' }}`
  {% endfor %}
  {% endif %}
```

### Streamline Card (`cards_javascript`)
```yaml
streamline_templates:
  mypup_parcel_list:
    card:
      type: vertical-stack
      cards_javascript: |
        const parcels = states['sensor.mypup_my_pickup_point_parcels_ready_for_pickup']?.attributes?.parcels || [];
        if (!parcels.length) {
          return [{ type: 'markdown', content: 'No MyPup parcels ready for pickup.' }];
        }
        return parcels.map((p) => ({
          type: 'custom:mushroom-template-card',
          primary: p.description || p.reference_no,
          secondary: `Locker ${p.locker} • PIN: ${p.pin || 'N/A'}`,
          icon: 'mdi:package-variant-closed-check',
          icon_color: 'amber',
          tap_action: {
            action: 'perform-action',
            perform_action: 'mypup.unlock_locker',
            data: { shipment_uid: p.shipment_uid },
            confirmation: { text: `Unlock Locker ${p.locker}?` }
          }
        }));
```

## Standalone Verification CLI

```powershell
python test_mypup.py
python test_mypup.py --test-renew
```
