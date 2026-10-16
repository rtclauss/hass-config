# Travel Detection Regression Matrix

This matrix documents the representative trip-detection cases covered for issues #66 and #67.

## Precedence

1. `flight_return`
   Use the first qualifying outbound flight from home and the earliest later return-home flight.
2. `flight_lodging`, `flight_explicit_vacation`, `flight_all_day_trip_block`
   If an outbound flight exists but no return-home flight is booked yet, use the nearest related fallback window in this order: lodging span, explicit vacation event, all-day trip block.
3. `calendar_lodging`, `calendar_explicit_vacation`, `calendar_all_day_trip_block`, `calendar_curling_block`
   If no qualifying outbound flight exists, use the earliest standalone travel block.
4. `off_outbound_missing_end`, `off_no_candidate`
   Leave trip mode unscheduled and surface the ignored reason when the data is insufficient or obviously not the user's trip.

## Matrix

| Case | Source | Expected decision | Notes |
| --- | --- | --- | --- |
| HOME -> DDD -> EEE -> FFF, then EEE -> HOME | multi-leg outbound | `flight_return` | Start at the HOME departure, keep the homebound return, and expose `FFF` as the destination instead of the first layover. |
| Friend flights arriving in HOME | friend homebound | `off_no_candidate` | Ignore friend itineraries so they do not satisfy homebound logic or airport-arrival automations. |
| Local Sample City appointments | local false positive | `off_no_candidate` | Local appointment locations must not be classified as flights. |
| Hotel/calendar-only trips | lodging fallback | `calendar_lodging` | A lodging span with no flights still produces a durable trip window. |
| Outbound flight with no return yet, plus lodging | outbound fallback | `flight_lodging` | Use the outbound flight for the trip start and the lodging span for the trip end. |
| Explicit `#vacation` block without flights | explicit vacation | `calendar_explicit_vacation` | Personal or calendar-tagged vacation blocks should still create a trip window. |
