<p align="center">
  <!-- Plain <img> with an absolute URL: the HACS/Marketplace README renderer
       doesn't support <picture>/<source>, and relative paths only resolve on
       GitHub. -->
  <img alt="Infinite Campus" src="https://raw.githubusercontent.com/sNNNeaker/ha-infinitecampus/main/custom_components/infinitecampus/brand/logo%402x.png" width="420">
</p>

# Infinite Campus for Home Assistant

Custom Home Assistant integration for the Infinite Campus parent portal.

Fork of [sp32087/ha-infinitecampus](https://github.com/sp32087/ha-infinitecampus) (MIT). Credit for the original integration goes to sp32087.

It creates a device for each student and adds sensors for grades, classes, assignments, missing work, failed assignments, and attendance.

## Install

Infinite Campus is in the HACS community catalog, so you can find it by name; no custom repository is needed.

### Via the Marketplace (Home Assistant 2026.11 and newer)

From 2026.11 HACS is built into Home Assistant as the **Marketplace** (Settings → Marketplace).

1. Search for **Infinite Campus** and download it. Catalog entries install from the release asset, so no GitHub connection is needed, and no restart is needed on first install.
2. Settings → Devices & services → Add integration → **Infinite Campus** (see Setup), or use
   [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=infinitecampus)

Updates show up under Settings → Updates; installing an update needs a restart, which the Marketplace offers via a repair.

### Via HACS (Home Assistant 2026.10 and older)

1. In HACS, search for **Infinite Campus** and download it.
2. Restart Home Assistant.

Fallback: if the search doesn't find it yet (the catalog can take a few hours to update), add `https://github.com/sNNNeaker/ha-infinitecampus` as a custom repository of type **Integration** (HACS ⋮ menu → Custom repositories). A custom entry added earlier keeps working and can be removed without uninstalling.

### Manual

Copy `custom_components/infinitecampus` into your Home Assistant `custom_components` folder, then restart Home Assistant.

## Setup

Add the integration from the Home Assistant UI.

You will enter:

- `Portal URL`
- `Username`
- `Password`

Example:

`https://yourdistrict.infinitecampus.org/campus/nav-wrapper/parent/portal/parent/home?appName=yourdistrict`

If the URL includes `appName=...`, the integration will use it. If not, it will ask for the app name.

If the portal rejects the login (for example after a password change), the integration stops polling and asks for the new password (Settings → Repairs / the integration card) instead of retrying.

## Sensors

Each student gets:

- `Overall Grade`
- `Missing Assignments`
- `Attendance`
- `Attendance Today`
- `Failed Assignments`
- `Assignments`
- one sensor per class

Class sensors include:

- teacher
- period
- room
- absences
- tardies
- `term1_grade` to `term4_grade`
- `final_grade`

## Per-day attendance (this fork)

`Attendance` sensor (state unchanged: total absences) gains attributes:

- `days`: list of per-day entries (`date`, `periods`, `courses`, `codes`, `absent_periods`, `tardy_periods`, `status`, `excused`), newest first, max 200
- `absent_days`, `partial_days`, `tardy_days`: number of days per status

`Attendance Today` sensor (enum: `none`, `tardy`, `partial`, `absent`):

- State is today's day status, `none` if nothing was recorded
- Attributes: `periods`, `courses`, `codes`, `excused`

`Attendance` calendar (one per student):

- One all-day event per day with an absence or tardy, e.g. `Partial absence (excused): P1, P2`
- Description lists courses and attendance codes
- Only past and current days appear; attendance is known after the fact

Day status rules:

- `absent`: a whole-day absence is flagged, both half days (AM and PM) are absent, or all of the student's class periods are marked absent
- `partial`: some periods absent; `tardy`: only tardies
- `excused` is `true`, `false` or `mixed` based on the excuse fields of the absent events (tardy events if none)

## Student photo (this fork)

`Photo` image entity (one per student): the student's picture from the parent portal (`personPicture.jsp`), checked once a day, so a new school photo comes in automatically. Stays unknown if the portal has no photo. Like every image entity, it is only served to logged-in users or with the entity's rotating access token (`entity_picture` attribute), so it can be used as a template `picture` elsewhere.

## Notes

- This uses the Infinite Campus `parents` portal.

## Disclaimer

Not affiliated with Infinite Campus.
