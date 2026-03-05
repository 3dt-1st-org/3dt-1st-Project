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
    case event

    var id: String { rawValue }

    var apiValue: String { rawValue }

    func title(in language: AppLanguage) -> String {
        switch (self, language) {
        case (.all, .korean): return "전체"
        case (.all, .english): return "All"
        case (.attraction, .korean): return "명소"
        case (.attraction, .english): return "Attractions"
        case (.restaurant, .korean): return "맛집"
        case (.restaurant, .english): return "Restaurants"
        case (.event, .korean): return "행사"
        case (.event, .english): return "Events"
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
    private let apiKey: String?
    private let session: URLSession
    private let decoder = JSONDecoder()

    init(
        baseURL: URL? = AppRuntime.apiBaseURL,
        apiKey: String? = AppRuntime.iosAPIKey,
        session: URLSession = .shared
    ) {
        self.baseURL = baseURL
        self.apiKey = apiKey
        self.session = session
    }

    func fetchPlaces(
        center: CLLocationCoordinate2D,
        radiusMeters: Int,
        category: MapPlaceFilter
    ) async throws -> [PlaceRecommendation] {
        guard baseURL != nil, apiKey != nil else {
            return Self.fallbackPlaces(around: center, category: category)
        }

        let requestURL = try makeURL(
            path: "/api/ios/v1/places",
            queryItems: [
                URLQueryItem(name: "lat", value: String(center.latitude)),
                URLQueryItem(name: "lng", value: String(center.longitude)),
                URLQueryItem(name: "radius", value: String(radiusMeters)),
                URLQueryItem(name: "category", value: category.apiValue)
            ]
        )

        do {
            let (data, response) = try await performRequest(url: requestURL)
            try validate(response: response)

            let decoded = try decoder.decode(RemotePlacesResponse.self, from: data)
            let mapped = decoded.places.map(Self.mapPlace(from:))
            return mapped.isEmpty ? Self.fallbackPlaces(around: center, category: category) : mapped
        } catch {
            return Self.fallbackPlaces(around: center, category: category)
        }
    }

    func fetchWeather(at coordinate: CLLocationCoordinate2D) async throws -> WeatherSnapshot {
        guard baseURL != nil, apiKey != nil else {
            return WeatherSnapshot(symbolName: "cloud.sun.fill", temperatureText: "13°C")
        }

        let requestURL = try makeURL(
            path: "/api/ios/v1/weather",
            queryItems: [
                URLQueryItem(name: "lat", value: String(coordinate.latitude)),
                URLQueryItem(name: "lng", value: String(coordinate.longitude))
            ]
        )

        do {
            let (data, response) = try await performRequest(url: requestURL)
            try validate(response: response)

            let decoded = try decoder.decode(RemoteWeatherResponse.self, from: data)
            return WeatherSnapshot(
                symbolName: Self.weatherSymbolName(from: decoded.icon),
                temperatureText: Self.temperatureText(from: decoded.temp)
            )
        } catch {
            return WeatherSnapshot(symbolName: "cloud.sun.fill", temperatureText: "13°C")
        }
    }

    private func performRequest(url: URL) async throws -> (Data, URLResponse) {
        guard let apiKey else {
            throw MapServiceError.missingAPIKey
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        return try await session.data(for: request)
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
        let categoryKo: String
        let categoryEn: String
        switch kind {
        case .attraction:
            categoryKo = "로컬 명소"
            categoryEn = "Attraction"
        case .restaurant:
            categoryKo = "로컬 맛집"
            categoryEn = "Restaurant"
        case .event:
            categoryKo = "로컬 행사"
            categoryEn = "Event"
        }
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
            addressEn: address,
            imageURL: item.imageURL.flatMap(URL.init(string:))
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

    private static func fallbackPlaces(
        around center: CLLocationCoordinate2D,
        category: MapPlaceFilter
    ) -> [PlaceRecommendation] {
        let current = CLLocation(latitude: center.latitude, longitude: center.longitude)
        let fixedSeeds: [(id: String, nameKo: String, nameEn: String, kind: PlaceCategoryKind, guideKo: String, guideEn: String, lat: Double, lng: Double, addressKo: String, addressEn: String, image: String)] = [
            (
                id: "sample-attraction-1",
                nameKo: "명소 샘플: 행궁동 성곽길",
                nameEn: "Attraction Sample: Haenggung Fortress Trail",
                kind: .attraction,
                guideKo: "명소 샘플입니다. 행궁동 성곽길 주변 풍경을 즐겨보세요.",
                guideEn: "Attraction sample. Enjoy the views around Haenggung trail.",
                lat: 37.2817,
                lng: 127.0150,
                addressKo: "경기도 수원시 팔달구 행궁로 인근",
                addressEn: "Near Haenggung-ro, Paldal-gu, Suwon",
                image: "https://picsum.photos/seed/lala-attraction/640/360"
            ),
            (
                id: "sample-restaurant-1",
                nameKo: "맛집 샘플: 팔달 로컬 식당",
                nameEn: "Restaurant Sample: Paldal Local Diner",
                kind: .restaurant,
                guideKo: "맛집 샘플입니다. 지역 주민이 자주 찾는 식당이에요.",
                guideEn: "Restaurant sample. A diner loved by local residents.",
                lat: 37.2794,
                lng: 127.0186,
                addressKo: "경기도 수원시 팔달구 정조로 인근",
                addressEn: "Near Jeongjo-ro, Paldal-gu, Suwon",
                image: "https://picsum.photos/seed/lala-restaurant/640/360"
            ),
            (
                id: "sample-event-1",
                nameKo: "행사 샘플: 화성 야간 프로그램",
                nameEn: "Event Sample: Hwaseong Night Program",
                kind: .event,
                guideKo: "행사 샘플입니다. 야간 조명과 공연 정보를 확인해보세요.",
                guideEn: "Event sample. Check out the night lights and performances.",
                lat: 37.2829,
                lng: 127.0174,
                addressKo: "경기도 수원시 팔달구 신풍로 인근",
                addressEn: "Near Sinpung-ro, Paldal-gu, Suwon",
                image: "https://picsum.photos/seed/lala-event/640/360"
            )
        ]

        let sample: [PlaceRecommendation] = fixedSeeds.map { seed in
            let coord = CLLocationCoordinate2D(latitude: seed.lat, longitude: seed.lng)
            let distance = Int(
                current.distance(from: CLLocation(latitude: seed.lat, longitude: seed.lng))
                    .rounded()
            )
            let categoryKo: String
            let categoryEn: String
            switch seed.kind {
            case .attraction:
                categoryKo = "로컬 명소"
                categoryEn = "Attraction"
            case .restaurant:
                categoryKo = "로컬 맛집"
                categoryEn = "Restaurant"
            case .event:
                categoryKo = "로컬 행사"
                categoryEn = "Event"
            }

            return PlaceRecommendation(
                id: seed.id,
                nameKo: seed.nameKo,
                nameEn: seed.nameEn,
                categoryKind: seed.kind,
                categoryKo: categoryKo,
                categoryEn: categoryEn,
                districtKo: "수원시 팔달구",
                districtEn: "Paldal-gu, Suwon",
                guideKo: seed.guideKo,
                guideEn: seed.guideEn,
                coordinate: coord,
                distanceMeters: distance,
                addressKo: seed.addressKo,
                addressEn: seed.addressEn,
                imageURL: URL(string: seed.image)
            )
        }
        .sorted { ($0.distanceMeters ?? Int.max) < ($1.distanceMeters ?? Int.max) }

        switch category {
        case .all:
            return sample
        case .attraction:
            return sample.filter { $0.categoryKind == .attraction }
        case .restaurant:
            return sample.filter { $0.categoryKind == .restaurant }
        case .event:
            return sample.filter { $0.categoryKind == .event }
        }
    }
}

enum MapServiceError: LocalizedError {
    case missingBaseURL
    case missingAPIKey
    case localhostNotAllowed
    case invalidBaseURL
    case invalidRequestURL
    case invalidResponse
    case httpStatus(Int)

    var errorDescription: String? {
        switch self {
        case .missingBaseURL:
            return "API base URL is missing."
        case .missingAPIKey:
            return "iOS API key is missing."
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
        if let custom = loadConfigValueFromAppConfig(named: "AppConfig.local", key: "API_BASE_URL"),
           let url = URL(string: custom) {
            return url
        }

        if let custom = loadConfigValueFromAppConfig(named: "AppConfig", key: "API_BASE_URL"),
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

    static var iosAPIKey: String? {
        if let custom = loadConfigValueFromAppConfig(named: "AppConfig.local", key: "IOS_API_KEY") {
            return custom
        }

        if let custom = loadConfigValueFromAppConfig(named: "AppConfig", key: "IOS_API_KEY") {
            return custom
        }

        if let custom = Bundle.main.object(forInfoDictionaryKey: "LALA_IOS_API_KEY") as? String {
            let trimmed = custom.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                return trimmed
            }
        }

        return nil
    }

    private static func loadConfigValueFromAppConfig(named resourceName: String, key: String) -> String? {
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
            let value = dictionary[key] as? String {
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
    let imageURL: String?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case lat
        case lng
        case category
        case address
        case region
        case distanceM = "distance_m"
        case imageURL = "image_url"
    }
}

private struct RemoteWeatherResponse: Decodable {
    let temp: String
    let icon: String
}
