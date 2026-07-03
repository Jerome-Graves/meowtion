# Dashboard UI walkthrough , component by component

Isolated screenshots of each part of the owner dashboard (captured from the read-only demo, viewing
the simulated cat "Purrminator" over 23,29 Jun 2026). Each entry explains what the component is, what
it is for, and how the user interacts with it.

---

### `comp-01-cat-selection.png` , Cat Selection
**What:** A segmented switcher, shown only when the account has more than one cat.
**Purpose:** Choose which cat the whole page is about.
**Interaction:** Tap a cat. The active one fills with the brand lavender and a check; every section
below (current activity, health watch, history) re-renders for that cat.

### `comp-02-current-activity.png` , Current activity (live card)
**What:** A live status card: the on-device detected behaviour (e.g. "purring"), an online/offline
dot, whether it is detecting on-device or simulated, and battery %.
**Purpose:** An at-a-glance "what is the cat doing right now".
**Interaction:** Read-only; it auto-refreshes about every 10 seconds. During low-power rest it shows
"Resting , low power" instead of a model class.

### `comp-03-health-watch.png` , Health watch
**What:** Per-habit metrics (eating, drinking, grooming, resting) with a "% vs usual" delta, plus
warning banners and a weather note.
**Purpose:** The core health feature: compare recent days against the cat's own longer-run baseline
and flag big, lasting changes in a vet-oriented way (not a diagnosis). Weather context is shown so a
warm-spell change isn't mistaken for illness.
**Interaction:** Read-only. A warning banner appears for any habit that has moved by roughly 30% or
more versus normal.

### `comp-04-date-picker.png` + `comp-04b-date-calendar.png` , Date picker
**What:** A calendar control (closed box, and the open calendar popover).
**Purpose:** Choose the time window for the history charts , a single day or a date range. The view
derives the granularity (one day vs multiple days) from the span.
**Interaction:** Click the lavender-bordered box to open the calendar; click one day for a single day,
or two days for a range (the popover shows 23,29 selected). Both charts below update to match.

### `comp-05-activity-filters.png` , Activity filter buttons
**What:** One toggle button per behaviour, in the shared colourblind-safe palette.
**Purpose:** Show or hide activities so the small habits (eat, drink) aren't drowned out by the big
ones (resting, sleeping).
**Interaction:** Click to toggle. Filled = on, outline = off. The choice applies to both charts at
once, and the colours match across the buttons and both charts.

### `comp-06-time-per-activity.png` , Time per activity (totals)
**What:** A bar chart of total minutes per behaviour over the chosen window, biggest first.
**Purpose:** The "how much" view , where the cat's time goes.
**Interaction:** Driven by the date picker and the activity filters; hover a bar for the exact minutes.

### `comp-07-timeline.png` , When activities happened (timeline)
**What:** A rows-of-days timeline: the y-axis is the calendar day, the x-axis is time of day, and each
event is a coloured bar at the time it occurred. The x-axis spans the data's actual range.
**Purpose:** The "when" view , read the cat's daily rhythm and spot patterns at a glance.
**Interaction:** Scroll or drag to zoom the time axis; the centred "Reset view" button returns to the
full day.

### `comp-08-recent-activity.png` , Recent activity (live feed)
**What:** A list of the most recent detected events: icon, behaviour name, time, and duration, newest
first.
**Purpose:** A live feed of what the collar just logged; useful for a quick sanity check.
**Interaction:** Read-only; auto-refreshes about every 2 minutes.

### `comp-09-footer.png` , Footer (data safety + support)
**What:** A collapsible "How your data is used" disclosure, a cat-health resource link, and
report-an-issue links.
**Purpose:** Privacy transparency and a route to get help.
**Interaction:** Click the row to expand the disclosure; the links open external pages.
