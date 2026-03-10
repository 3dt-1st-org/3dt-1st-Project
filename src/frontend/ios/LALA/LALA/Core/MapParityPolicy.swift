//
//  MapParityPolicy.swift
//  LALA
//
//  Created by Codex on 3/9/26.
//

import Foundation
import CoreLocation

struct PlacesAPIQuery: Equatable {
    let scope: String
    let radiusMeters: Int
    let limit: Int
    let category: String
}

enum PlacesReloadPolicy {
    static let defaultRadiusMeters = 20_000
    static let defaultLimit = 500

    static func makeDefaultQuery(category: String) -> PlacesAPIQuery {
        PlacesAPIQuery(
            scope: "radius",
            radiusMeters: defaultRadiusMeters,
            limit: defaultLimit,
            category: category
        )
    }

    static func shouldReload(
        force: Bool,
        hasAnyPlaces: Bool,
        lastFetchCenter: CLLocationCoordinate2D?,
        currentCenter: CLLocationCoordinate2D,
        minimumDistanceMeters: CLLocationDistance
    ) -> Bool {
        if force || !hasAnyPlaces || lastFetchCenter == nil {
            return true
        }
        guard let lastFetchCenter else { return true }
        return distanceMeters(from: lastFetchCenter, to: currentCenter) >= minimumDistanceMeters
    }

    private static func distanceMeters(
        from lhs: CLLocationCoordinate2D,
        to rhs: CLLocationCoordinate2D
    ) -> CLLocationDistance {
        CLLocation(latitude: lhs.latitude, longitude: lhs.longitude)
            .distance(from: CLLocation(latitude: rhs.latitude, longitude: rhs.longitude))
    }
}

enum WeatherReloadPolicy {
    static let defaultDistanceThresholdMeters: CLLocationDistance = 10_000
    static let defaultMaxAgeSeconds: TimeInterval = 600

    static func shouldReload(
        force: Bool,
        lastFetchCoordinate: CLLocationCoordinate2D?,
        lastFetchAt: Date?,
        currentCoordinate: CLLocationCoordinate2D,
        maxAgeSeconds: TimeInterval = defaultMaxAgeSeconds,
        distanceThresholdMeters: CLLocationDistance = defaultDistanceThresholdMeters,
        now: Date = Date()
    ) -> Bool {
        if force || lastFetchCoordinate == nil || lastFetchAt == nil {
            return true
        }
        guard let lastFetchCoordinate, let lastFetchAt else { return true }

        if now.timeIntervalSince(lastFetchAt) >= maxAgeSeconds {
            return true
        }
        return distanceMeters(from: lastFetchCoordinate, to: currentCoordinate) >= distanceThresholdMeters
    }

    private static func distanceMeters(
        from lhs: CLLocationCoordinate2D,
        to rhs: CLLocationCoordinate2D
    ) -> CLLocationDistance {
        CLLocation(latitude: lhs.latitude, longitude: lhs.longitude)
            .distance(from: CLLocation(latitude: rhs.latitude, longitude: rhs.longitude))
    }
}

enum InterventionCopyMapper {
    static func toastMessage(type: String, languageCode: String) -> String? {
        let isKorean = languageCode.lowercased().hasPrefix("ko")
        switch type {
        case "rain_alert":
            return isKorean
                ? "☔ 비가 옵니다 — 실내 장소를 추천해요"
                : "☔ Rain is expected — recommending indoor places."
        case "pm_alert":
            return isKorean
                ? "😷 미세먼지가 나빠요 — 실내 장소를 추천해요"
                : "😷 Air quality is poor — recommending indoor places."
        case "clear_sky_alert":
            return isKorean
                ? "☀️ 날씨가 맑아요! 야외 활동하기 좋아요"
                : "☀️ Clear skies now! Great for outdoor activities."
        default:
            return nil
        }
    }

    static func outdoorStatusFallback(type: String, languageCode: String) -> String? {
        let isKorean = languageCode.lowercased().hasPrefix("ko")
        switch type {
        case "rain_alert":
            return isKorean ? "비/눈" : "Rain/Snow"
        case "pm_alert":
            return isKorean ? "미세먼지 나쁨" : "Poor Air Quality"
        case "clear_sky_alert":
            return isKorean ? "야외활동 쾌적" : "Comfortable Outdoors"
        default:
            return nil
        }
    }
}
