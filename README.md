# MyPup Home Assistant Integration (`MyPupHA`)

Read-only Home Assistant custom integration and standalone verification script for **MyPup**.

## 1. Verify Locally (Read-Only)

Run the standalone Python script (uses Python standard library only; `pyperclip` optional for clipboard paste):

```powershell
python test_mypup.py
```

To test background silent token renewal (`prompt=none`) using your `login.mypup.app` session cookies:

```powershell
python test_mypup.py --test-renew
```

> **Note on Locker Unlocking:** Neither `test_mypup.py` nor `custom_components/mypup/` calls any locker-unlock or state-changing endpoints.

## 2. Install in Home Assistant

1. Copy `custom_components/mypup/` into your Home Assistant `<config>/custom_components/mypup/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → MyPup**.
4. Sign in to `login.mypup.app` (with **Remember Me** checked), copy the `Cookie` request header for `login.mypup.app` from DevTools → Network, and paste it into the **login.mypup.app Cookie header or JSON** field.

Home Assistant will automatically renew short-lived `access_token`s in the background via `prompt=none` without storing your username or password, and will raise a re-authentication prompt if the session cookie eventually expires.

### Entities Created
- `sensor.mypup_parcels_ready_for_pickup` — count of parcels with `ReadyForPickup`, with `parcels` attribute (tracking number, description, pickup point, locker number)
- `sensor.mypup_total_parcels` — total shipments returned
- `sensor.mypup_main_pickup_point` — primary pickup point name, mail code, and delivery address lines
