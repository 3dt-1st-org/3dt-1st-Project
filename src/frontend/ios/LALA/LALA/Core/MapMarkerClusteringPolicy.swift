//
//  MapMarkerClusteringPolicy.swift
//  LALA
//
//  Created by Codex on 3/10/26.
//

import Foundation
import CoreLocation

struct MapMarkerPoint<ID: Hashable> {
    let id: ID
    let latitude: CLLocationDegrees
    let longitude: CLLocationDegrees
    let categoryKey: String
}

struct MapMarkerCluster<ID: Hashable> {
    let id: String
    let latitude: CLLocationDegrees
    let longitude: CLLocationDegrees
    let categoryKey: String
    let count: Int
    let memberIDs: [ID]
}

enum MapMarkerPresentationItem<ID: Hashable> {
    case place(MapMarkerPoint<ID>)
    case cluster(MapMarkerCluster<ID>)
}

enum MapMarkerClusteringPolicy {
    static let defaultActivationLatitudeDelta: CLLocationDegrees = 0.01
    static let defaultMinimumPointCount = 12
    static let defaultGridDivisions: Double = 5.0
    private static let minimumGridCellDelta: CLLocationDegrees = 0.000_3

    static func shouldUseCluster(
        pointCount: Int,
        latitudeDelta: CLLocationDegrees,
        activationLatitudeDelta: CLLocationDegrees = defaultActivationLatitudeDelta,
        minimumPointCount: Int = defaultMinimumPointCount
    ) -> Bool {
        pointCount >= max(2, minimumPointCount) && latitudeDelta >= max(0.0, activationLatitudeDelta)
    }

    static func buildPresentations<ID: Hashable>(
        points: [MapMarkerPoint<ID>],
        latitudeDelta: CLLocationDegrees,
        longitudeDelta: CLLocationDegrees,
        selectedPointID: ID?,
        activationLatitudeDelta: CLLocationDegrees = defaultActivationLatitudeDelta,
        minimumPointCount: Int = defaultMinimumPointCount,
        gridDivisions: Double = defaultGridDivisions
    ) -> [MapMarkerPresentationItem<ID>] {
        guard !points.isEmpty else { return [] }
        guard shouldUseCluster(
            pointCount: points.count,
            latitudeDelta: latitudeDelta,
            activationLatitudeDelta: activationLatitudeDelta,
            minimumPointCount: minimumPointCount
        ) else {
            return points.map(MapMarkerPresentationItem.place)
        }

        let safeGridDivisions = max(gridDivisions, 1.0)
        let latitudeCellDelta = max(latitudeDelta / safeGridDivisions, minimumGridCellDelta)
        let longitudeCellDelta = max(longitudeDelta / safeGridDivisions, minimumGridCellDelta)

        var selectedPoint: MapMarkerPoint<ID>?
        let clusteringCandidates = points.filter { point in
            guard let selectedPointID else { return true }
            if point.id == selectedPointID {
                selectedPoint = point
                return false
            }
            return true
        }

        var bucketOrder: [BucketKey] = []
        var bucketedPoints: [BucketKey: [MapMarkerPoint<ID>]] = [:]

        for point in clusteringCandidates {
            let key = BucketKey(
                categoryKey: point.categoryKey,
                latitudeIndex: Int(floor(point.latitude / latitudeCellDelta)),
                longitudeIndex: Int(floor(point.longitude / longitudeCellDelta))
            )
            if bucketedPoints[key] == nil {
                bucketOrder.append(key)
            }
            bucketedPoints[key, default: []].append(point)
        }

        var presentation: [MapMarkerPresentationItem<ID>] = []
        for key in bucketOrder {
            guard let members = bucketedPoints[key], !members.isEmpty else { continue }
            if members.count == 1 {
                presentation.append(.place(members[0]))
                continue
            }

            let latitudeAverage = members.reduce(0.0) { partial, point in
                partial + point.latitude
            } / Double(members.count)

            let longitudeAverage = members.reduce(0.0) { partial, point in
                partial + point.longitude
            } / Double(members.count)

            let cluster = MapMarkerCluster(
                id: clusterID(for: key),
                latitude: latitudeAverage,
                longitude: longitudeAverage,
                categoryKey: key.categoryKey,
                count: members.count,
                memberIDs: members.map(\.id)
            )
            presentation.append(.cluster(cluster))
        }

        if let selectedPoint {
            presentation.append(.place(selectedPoint))
        }

        return presentation
    }

    private struct BucketKey: Hashable {
        let categoryKey: String
        let latitudeIndex: Int
        let longitudeIndex: Int
    }

    private static func clusterID(for key: BucketKey) -> String {
        let normalizedCategory = key.categoryKey
            .lowercased()
            .replacingOccurrences(
                of: #"[^a-z0-9]+"#,
                with: "-",
                options: .regularExpression
            )
        return "cluster-\(normalizedCategory)-\(key.latitudeIndex)-\(key.longitudeIndex)"
    }
}
