import XCTest
import CoreLocation
@testable import LALACore

final class MapMarkerClusteringPolicyTests: XCTestCase {
    func testShouldUseCluster_ReturnsFalseWhenPointCountIsTooLow() {
        let result = MapMarkerClusteringPolicy.shouldUseCluster(
            pointCount: 3,
            latitudeDelta: 0.03,
            activationLatitudeDelta: 0.01,
            minimumPointCount: 4
        )

        XCTAssertFalse(result)
    }

    func testBuildPresentations_ReturnsIndividualPlacesWhenThresholdNotMet() {
        let points = [
            MapMarkerPoint(id: "a", latitude: 37.2636, longitude: 127.0286, categoryKey: "restaurant"),
            MapMarkerPoint(id: "b", latitude: 37.2650, longitude: 127.0301, categoryKey: "restaurant")
        ]

        let result = MapMarkerClusteringPolicy.buildPresentations(
            points: points,
            latitudeDelta: 0.008,
            longitudeDelta: 0.008,
            selectedPointID: nil,
            activationLatitudeDelta: 0.01,
            minimumPointCount: 3
        )

        XCTAssertEqual(result.count, 2)
        XCTAssertTrue(result.allSatisfy { item in
            if case .place = item {
                return true
            }
            return false
        })
    }

    func testBuildPresentations_CreatesClusterForDenseBucket() {
        let points = [
            MapMarkerPoint(id: "a", latitude: 37.26360, longitude: 127.02860, categoryKey: "restaurant"),
            MapMarkerPoint(id: "b", latitude: 37.26366, longitude: 127.02866, categoryKey: "restaurant"),
            MapMarkerPoint(id: "c", latitude: 37.27000, longitude: 127.03500, categoryKey: "restaurant")
        ]

        let result = MapMarkerClusteringPolicy.buildPresentations(
            points: points,
            latitudeDelta: 0.03,
            longitudeDelta: 0.03,
            selectedPointID: nil,
            activationLatitudeDelta: 0.01,
            minimumPointCount: 2,
            gridDivisions: 6
        )

        let clusterItems = result.compactMap { item -> MapMarkerCluster<String>? in
            if case let .cluster(cluster) = item {
                return cluster
            }
            return nil
        }
        let placeItems = result.compactMap { item -> MapMarkerPoint<String>? in
            if case let .place(place) = item {
                return place
            }
            return nil
        }

        XCTAssertEqual(clusterItems.count, 1)
        XCTAssertEqual(clusterItems.first?.count, 2)
        XCTAssertEqual(Set(clusterItems.first?.memberIDs ?? []), Set(["a", "b"]))
        XCTAssertEqual(placeItems.count, 1)
        XCTAssertEqual(placeItems.first?.id, "c")
    }

    func testBuildPresentations_AlwaysKeepsSelectedPlaceVisible() {
        let points = [
            MapMarkerPoint(id: "a", latitude: 37.26360, longitude: 127.02860, categoryKey: "attraction"),
            MapMarkerPoint(id: "b", latitude: 37.26362, longitude: 127.02862, categoryKey: "attraction"),
            MapMarkerPoint(id: "c", latitude: 37.26364, longitude: 127.02864, categoryKey: "attraction")
        ]

        let result = MapMarkerClusteringPolicy.buildPresentations(
            points: points,
            latitudeDelta: 0.02,
            longitudeDelta: 0.02,
            selectedPointID: "b",
            activationLatitudeDelta: 0.01,
            minimumPointCount: 2,
            gridDivisions: 5
        )

        let selectedPlace = result.compactMap { item -> MapMarkerPoint<String>? in
            if case let .place(point) = item, point.id == "b" {
                return point
            }
            return nil
        }
        let clusterItems = result.compactMap { item -> MapMarkerCluster<String>? in
            if case let .cluster(cluster) = item {
                return cluster
            }
            return nil
        }

        XCTAssertEqual(selectedPlace.count, 1)
        XCTAssertEqual(clusterItems.count, 1)
        XCTAssertEqual(clusterItems.first?.count, 2)
        XCTAssertEqual(Set(clusterItems.first?.memberIDs ?? []), Set(["a", "c"]))
    }
}
