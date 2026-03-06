# iOS Location Route Test (Suwon, 10m/s)

Added test files:

- `tests/ios/routes/suwon_10mps_loop.geojson`
- `tests/ios/routes/suwon_docent_compatible.gpx`

Route profile:

- City: Suwon
- Sampling: 1 second
- Target speed: 10 m/s
- Total points: 567
- Duration: 566 seconds (about 9m 26s)
- Total distance: about 5.67 km

## Xcode Simulator usage

1. Run the iOS app in Simulator.
2. In Xcode top menu, open:
   - `Debug` > `Simulate Location` > `Add GPX File to Project...`
3. Select:
   - `tests/ios/routes/suwon_docent_compatible.gpx`
4. Re-open:
   - `Debug` > `Simulate Location`
5. Choose:
   - `Suwon Docent Route (Compatible)`

The simulator will move along the route over time, so you can verify auto docent behavior while location changes.

## GeoJSON usage

`tests/ios/routes/suwon_10mps_loop.geojson` contains a `LineString` plus `time_index_utc` in properties for custom playback tools.
