//
//  MapRemoteService.swift
//  LALA
//
//  Created by Codex on 3/4/26.
//

import Foundation
import CoreLocation

enum MapPlaceFilter: String, CaseIterable, Identifiable {
    case all
    case attraction
    case restaurant

    var id: String { rawValue }

    var apiValue: String { rawValue }

    func title(in language: AppLanguage) -> String {
        switch (self, language) {
        case (.all, .korean): return "전체"
        case (.all, .english): return "All"
        case (.all, .japanese): return "すべて"
        case (.attraction, .korean): return "명소"
        case (.attraction, .english): return "Attractions"
        case (.attraction, .japanese): return "名所"
        case (.restaurant, .korean): return "맛집"
        case (.restaurant, .english): return "Restaurants"
        case (.restaurant, .japanese): return "グルメ"
        }
    }
}

struct WeatherSnapshot {
    let symbolName: String
    let temperatureText: String

    static let placeholder = WeatherSnapshot(symbolName: "cloud.sun.fill", temperatureText: "--°C")
}

protocol MapDataProviding {
    func fetchPlaces(
        center: CLLocationCoordinate2D,
        radiusMeters: Int,
        category: MapPlaceFilter
    ) async throws -> [PlaceRecommendation]

    func fetchWeather(at coordinate: CLLocationCoordinate2D) async throws -> WeatherSnapshot
}

final class MapRemoteService: MapDataProviding {
    private let baseURL: URL?
    private let session: URLSession
    private let decoder = JSONDecoder()

    init(
        baseURL: URL? = AppRuntime.apiBaseURL,
        session: URLSession = .shared
    ) {
        self.baseURL = baseURL
        self.session = session
    }

    func fetchPlaces(
        center: CLLocationCoordinate2D,
        radiusMeters: Int,
        category: MapPlaceFilter
    ) async throws -> [PlaceRecommendation] {
        let requestURL = try makeURL(
            path: "/api/places",
            queryItems: [
                URLQueryItem(name: "lat", value: String(center.latitude)),
                URLQueryItem(name: "lng", value: String(center.longitude)),
                URLQueryItem(name: "radius", value: String(radiusMeters)),
                URLQueryItem(name: "category", value: category.apiValue)
            ]
        )

        let (data, response) = try await session.data(from: requestURL)
        try validate(response: response)

        let decoded = try decoder.decode(RemotePlacesResponse.self, from: data)
        return decoded.places.map(Self.mapPlace(from:))
    }

    func fetchWeather(at coordinate: CLLocationCoordinate2D) async throws -> WeatherSnapshot {
        let requestURL = try makeURL(
            path: "/api/weather",
            queryItems: [
                URLQueryItem(name: "lat", value: String(coordinate.latitude)),
                URLQueryItem(name: "lng", value: String(coordinate.longitude))
            ]
        )

        let (data, response) = try await session.data(from: requestURL)
        try validate(response: response)

        let decoded = try decoder.decode(RemoteWeatherResponse.self, from: data)
        return WeatherSnapshot(
            symbolName: Self.weatherSymbolName(from: decoded.icon),
            temperatureText: Self.temperatureText(from: decoded.temp)
        )
    }

    private func makeURL(path: String, queryItems: [URLQueryItem]) throws -> URL {
        guard let baseURL else {
            throw MapServiceError.missingBaseURL
        }
        if let host = baseURL.host?.lowercased(),
           host == "localhost" || host == "127.0.0.1" {
            throw MapServiceError.localhostNotAllowed
        }

        guard var components = URLComponents(
            url: baseURL,
            resolvingAgainstBaseURL: false
        ) else {
            throw MapServiceError.invalidBaseURL
        }

        let endpointPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        let normalizedBasePath = components.path
            .split(separator: "/")
            .map(String.init)
            .joined(separator: "/")

        if normalizedBasePath.isEmpty {
            components.path = "/\(endpointPath)"
        } else {
            components.path = "/\(normalizedBasePath)/\(endpointPath)"
        }
        components.queryItems = queryItems

        guard let url = components.url else {
            throw MapServiceError.invalidRequestURL
        }
        return url
    }

    private func validate(response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else {
            throw MapServiceError.invalidResponse
        }
        guard (200 ... 299).contains(http.statusCode) else {
            throw MapServiceError.httpStatus(http.statusCode)
        }
    }

    private static func mapPlace(from item: RemotePlaceItem) -> PlaceRecommendation {
        let kind = PlaceCategoryKind.fromRemoteCategory(item.category)
        let categoryKo = item.category == "restaurant" ? "로컬 맛집" : "로컬 명소"
        let categoryEn = item.category == "restaurant" ? "Local Eats" : "Attraction"
        let region = item.region ?? ""
        let address = item.address ?? ""

        let distanceGuideKo: String
        let distanceGuideEn: String
        if let distance = item.distanceM {
            distanceGuideKo = "현재 위치에서 약 \(distance)m 거리에 있어요."
            distanceGuideEn = "It is about \(distance)m away from your current location."
        } else {
            distanceGuideKo = "현재 위치 근처 추천 장소입니다."
            distanceGuideEn = "This is a recommended place near your location."
        }

        let guideKo = "\(item.name) \(distanceGuideKo) \(region) \(address)"
        let guideEn = "\(item.name). \(distanceGuideEn)"

        return PlaceRecommendation(
            id: item.id,
            nameKo: item.name,
            nameEn: item.name,
            categoryKind: kind,
            categoryKo: categoryKo,
            categoryEn: categoryEn,
            districtKo: region,
            districtEn: region,
            guideKo: guideKo,
            guideEn: guideEn,
            coordinate: CLLocationCoordinate2D(latitude: item.lat, longitude: item.lng),
            distanceMeters: item.distanceM,
            addressKo: address,
            addressEn: address
        )
    }

    private static func weatherSymbolName(from icon: String) -> String {
        switch icon {
        case "☀️": return "sun.max.fill"
        case "🌧️": return "cloud.rain.fill"
        case "🌨️": return "cloud.sleet.fill"
        case "❄️": return "snowflake"
        case "🌦️": return "cloud.sun.rain.fill"
        default: return "cloud.sun.fill"
        }
    }

    private static func temperatureText(from raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.hasSuffix("°C") {
            return trimmed
        }
        return "\(trimmed)°C"
    }
}

enum MapServiceError: LocalizedError {
    case missingBaseURL
    case localhostNotAllowed
    case invalidBaseURL
    case invalidRequestURL
    case invalidResponse
    case httpStatus(Int)

    var errorDescription: String? {
        switch self {
        case .missingBaseURL:
            return "API base URL is missing."
        case .localhostNotAllowed:
            return "localhost is not allowed for API base URL."
        case .invalidBaseURL:
            return "API base URL is invalid."
        case .invalidRequestURL:
            return "Failed to build request URL."
        case .invalidResponse:
            return "Invalid server response."
        case let .httpStatus(code):
            return "Server returned HTTP \(code)."
        }
    }
}

enum AppRuntime {
    static var apiBaseURL: URL? {
        if let custom = loadBaseURLFromAppConfig(named: "AppConfig.local"),
           let url = URL(string: custom) {
            return url
        }

        if let custom = loadBaseURLFromAppConfig(named: "AppConfig"),
           let url = URL(string: custom) {
            return url
        }

        if let custom = Bundle.main.object(forInfoDictionaryKey: "LALA_API_BASE_URL") as? String,
           !custom.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           let url = URL(string: custom) {
            return url
        }

        return nil
    }

    private static func loadBaseURLFromAppConfig(named resourceName: String) -> String? {
        let candidates: [(String?, String)] = [
            ("Config", resourceName),
            (nil, resourceName)
        ]

        for candidate in candidates {
            if let url = Bundle.main.url(
                forResource: candidate.1,
                withExtension: "plist",
                subdirectory: candidate.0
            ),
            let dictionary = NSDictionary(contentsOf: url) as? [String: Any],
            let value = dictionary["API_BASE_URL"] as? String {
                let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
                if !trimmed.isEmpty {
                    return trimmed
                }
            }
        }

        return nil
    }
}

private struct RemotePlacesResponse: Decodable {
    let places: [RemotePlaceItem]
}

private struct RemotePlaceItem: Decodable {
    let id: String
    let name: String
    let lat: Double
    let lng: Double
    let category: String
    let address: String?
    let region: String?
    let distanceM: Int?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case lat
        case lng
        case category
        case address
        case region
        case distanceM = "distance_m"
    }
}

private struct RemoteWeatherResponse: Decodable {
    let temp: String
    let icon: String
}
