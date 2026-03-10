import XCTest
import CoreLocation
@testable import LALACore

final class MapParityPolicyTests: XCTestCase {
    func testPlacesQuery_DoesNotHardCapAt100() {
        let query = PlacesReloadPolicy.makeDefaultQuery(category: "restaurant")

        XCTAssertEqual(query.scope, "radius")
        XCTAssertEqual(query.radiusMeters, 20_000)
        XCTAssertEqual(query.limit, 500)
        XCTAssertEqual(query.category, "restaurant")
    }

    func testPlacesReloadPolicy_RequiresReloadWhenNoPreviousFetch() {
        let result = PlacesReloadPolicy.shouldReload(
            force: false,
            hasAnyPlaces: false,
            lastFetchCenter: nil,
            currentCenter: CLLocationCoordinate2D(latitude: 37.2636, longitude: 127.0286),
            minimumDistanceMeters: 300
        )

        XCTAssertTrue(result)
    }

    func testPlacesReloadPolicy_SkipsReloadForSmallCenterMove() {
        let result = PlacesReloadPolicy.shouldReload(
            force: false,
            hasAnyPlaces: true,
            lastFetchCenter: CLLocationCoordinate2D(latitude: 37.2636, longitude: 127.0286),
            currentCenter: CLLocationCoordinate2D(latitude: 37.2640, longitude: 127.0290),
            minimumDistanceMeters: 300
        )

        XCTAssertFalse(result)
    }

    func testWeatherReloadPolicy_ReloadsWhenForceIsTrue() {
        let now = Date()
        let result = WeatherReloadPolicy.shouldReload(
            force: true,
            lastFetchCoordinate: CLLocationCoordinate2D(latitude: 37.2636, longitude: 127.0286),
            lastFetchAt: now,
            currentCoordinate: CLLocationCoordinate2D(latitude: 37.2636, longitude: 127.0286),
            now: now
        )

        XCTAssertTrue(result)
    }

    func testWeatherReloadPolicy_ReloadsWhenMaxAgeExceeded() {
        let now = Date()
        let result = WeatherReloadPolicy.shouldReload(
            force: false,
            lastFetchCoordinate: CLLocationCoordinate2D(latitude: 37.2636, longitude: 127.0286),
            lastFetchAt: now.addingTimeInterval(-601),
            currentCoordinate: CLLocationCoordinate2D(latitude: 37.2636, longitude: 127.0286),
            now: now
        )

        XCTAssertTrue(result)
    }

    func testWeatherReloadPolicy_SkipsReloadWhenFreshAndNearby() {
        let now = Date()
        let result = WeatherReloadPolicy.shouldReload(
            force: false,
            lastFetchCoordinate: CLLocationCoordinate2D(latitude: 37.2636, longitude: 127.0286),
            lastFetchAt: now.addingTimeInterval(-120),
            currentCoordinate: CLLocationCoordinate2D(latitude: 37.2638, longitude: 127.0287),
            now: now
        )

        XCTAssertFalse(result)
    }

    func testInterventionCopyMapper_ReturnsWebLabelForRainAlert() {
        let message = InterventionCopyMapper.toastMessage(type: "rain_alert", languageCode: "ko")

        XCTAssertEqual(message, "☔ 비가 옵니다 — 실내 장소를 추천해요")
    }

    func testInterventionCopyMapper_ReturnsOutdoorStatusFallback() {
        let status = InterventionCopyMapper.outdoorStatusFallback(type: "clear_sky_alert", languageCode: "ko")

        XCTAssertEqual(status, "야외활동 쾌적")
    }
}
