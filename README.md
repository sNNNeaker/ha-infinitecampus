# Infinite Campus for Home Assistant

Custom Home Assistant integration for the Infinite Campus parent portal.

It creates a device for each student and adds sensors for grades, classes, assignments, missing work, failed assignments, and attendance.

## Install

### HACS

1. Add this repo as a custom repository in HACS.
2. Category: `Integration`
3. Install `Infinite Campus`
4. Restart Home Assistant

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

## Sensors

Each student gets:

- `Overall Grade`
- `Missing Assignments`
- `Attendance`
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

## Notes

- This uses the Infinite Campus `parents` portal.

## Disclaimer

Not affiliated with Infinite Campus.
