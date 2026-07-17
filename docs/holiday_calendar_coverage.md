# Holiday Calendar Coverage

Coverage window: 2026-05-29 through 2028-05-29.

Holiday lighting is generated from the date rules in `packages/holidays.yaml`; no
manual calendar event is required for those lighting scenes. If the same days
are mirrored into a visible Home Assistant calendar, include the items below.
`calendar.mn_holidays` remains the calendar source for Minnesota public-holiday
workday and garbage pickup logic.

The active outdoor holiday palette is intentionally applied every minute during
the dark window. Christmas and Hogmanay use one-minute cadence when configured;
other holidays may keep a scene for multiple trigger ticks according to their
declared `cadence_minutes`.

## Lighting Dates

| Date | Holiday key | Label |
| --- | --- | --- |
| 2026-06-19 | juneteenth | Juneteenth |
| 2026-07-04 | independence_day | Independence Day |
| 2026-09-02 | sealand_independence_day | Sealand Independence Day |
| 2026-09-07 | labor_day | Labor Day |
| 2026-09-19 | talk_like_a_pirate_day | Talk Like a Pirate Day |
| 2026-10-31 | halloween | Halloween |
| 2026-11-11 | veterans_day | Veterans Day |
| 2026-11-26 | thanksgiving | Thanksgiving |
| 2026-11-30 | st_andrews_day | St Andrew's Day |
| 2026-12-01/2026-12-31 | christmas_season | Christmas Season |
| 2026-12-31 | hogmanay | Hogmanay |
| 2027-01-01/2027-01-31 | national_curling_month | National Curling Month |
| 2027-01-25 | burns_night | Burns Night |
| 2027-02-02 | groundhog_day | Groundhog Day |
| 2027-02-15 | presidents_day | Presidents' Day |
| 2027-03-14 | pi_day | Pi Day |
| 2027-04-06 | tartan_day | Tartan Day |
| 2027-05-04 | star_wars_day | Star Wars Day |
| 2027-05-11 | minnesota_statehood_day | Minnesota Statehood Day |
| 2027-05-15 | minnesota_fishing_opener | Minnesota Fishing Opener |
| 2027-05-31 | memorial_day | Memorial Day |
| 2027-06-19 | juneteenth | Juneteenth |
| 2027-07-04 | independence_day | Independence Day |
| 2027-09-02 | sealand_independence_day | Sealand Independence Day |
| 2027-09-06 | labor_day | Labor Day |
| 2027-09-19 | talk_like_a_pirate_day | Talk Like a Pirate Day |
| 2027-10-31 | halloween | Halloween |
| 2027-11-11 | veterans_day | Veterans Day |
| 2027-11-25 | thanksgiving | Thanksgiving |
| 2027-11-30 | st_andrews_day | St Andrew's Day |
| 2027-12-01/2027-12-31 | christmas_season | Christmas Season |
| 2027-12-31 | hogmanay | Hogmanay |
| 2028-01-01/2028-01-31 | national_curling_month | National Curling Month |
| 2028-01-25 | burns_night | Burns Night |
| 2028-02-02 | groundhog_day | Groundhog Day |
| 2028-02-21 | presidents_day | Presidents' Day |
| 2028-02-29 | leap_day | Leap Day |
| 2028-03-14 | pi_day | Pi Day |
| 2028-04-06 | tartan_day | Tartan Day |
| 2028-05-04 | star_wars_day | Star Wars Day |
| 2028-05-11 | minnesota_statehood_day | Minnesota Statehood Day |
| 2028-05-13 | minnesota_fishing_opener | Minnesota Fishing Opener |
| 2028-05-29 | memorial_day | Memorial Day |

## Minnesota Public Calendar

Confirm `calendar.mn_holidays` has the relevant Minnesota public holidays in
this same window, including Juneteenth, Independence Day, Labor Day, Veterans
Day, Thanksgiving, Christmas Day, New Year's Day, Presidents' Day, Memorial Day,
and any observed weekday substitutions used by the source calendar.
