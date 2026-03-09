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
    let dustText: String
    let outdoorStatus: String
    let forecast: [WeatherForecastItem]

    static let placeholder = WeatherSnapshot(
        symbolName: "cloud.sun.fill",
        temperatureText: "--°C",
        dustText: "--",
        outdoorStatus: "",
        forecast: []
    )
}

struct WeatherForecastItem: Identifiable {
    let id: String
    let timeText: String
    let symbolName: String
    let temperatureText: String
}

struct PlacesSnapshot {
    let places: [PlaceRecommendation]
    let city: String?
}

protocol MapDataProviding {
    func fetchPlaces(
        center: CLLocationCoordinate2D,
        radiusMeters: Int,
        category: MapPlaceFilter
    ) async throws -> PlacesSnapshot

    func fetchWeather(at coordinate: CLLocationCoordinate2D) async throws -> WeatherSnapshot
}

private actor WeatherSnapshotStore {
    struct Entry {
        let snapshot: WeatherSnapshot
        let expiresAt: Date
    }

    private let ttl: TimeInterval
    private var cache: [String: Entry] = [:]
    private var inFlight: [String: Task<WeatherSnapshot, Error>] = [:]

    init(ttl: TimeInterval) {
        self.ttl = ttl
    }

    func cachedSnapshot(for key: String, now: Date = Date()) -> WeatherSnapshot? {
        guard let entry = cache[key] else { return nil }
        guard entry.expiresAt > now else {
            cache.removeValue(forKey: key)
            return nil
        }
        return entry.snapshot
    }

    func inFlightTask(for key: String) -> Task<WeatherSnapshot, Error>? {
        inFlight[key]
    }

    func setInFlight(_ task: Task<WeatherSnapshot, Error>, for key: String) {
        inFlight[key] = task
    }

    func store(_ snapshot: WeatherSnapshot, for key: String, now: Date = Date()) {
        cache[key] = Entry(snapshot: snapshot, expiresAt: now.addingTimeInterval(ttl))
        inFlight.removeValue(forKey: key)
    }

    func clearInFlight(for key: String) {
        inFlight.removeValue(forKey: key)
    }
}

final class MapRemoteService: MapDataProviding {
    private let baseURL: URL?
    private let apiKey: String?
    private let session: URLSession
    private let decoder = JSONDecoder()
    private static let weatherCache = WeatherSnapshotStore(ttl: 180)

    init(
        baseURL: URL? = AppRuntime.apiBaseURL,
        apiKey: String? = AppRuntime.iosAPIKey,
        session: URLSession = MapRemoteService.makeDefaultSession()
    ) {
        self.baseURL = baseURL
        self.apiKey = apiKey
        self.session = session
    }

    func fetchPlaces(
        center: CLLocationCoordinate2D,
        radiusMeters: Int,
        category: MapPlaceFilter
    ) async throws -> PlacesSnapshot {
        guard baseURL != nil else {
            throw MapServiceError.missingBaseURL
        }
        guard apiKey != nil else {
            throw MapServiceError.missingAPIKey
        }

        let query = PlacesReloadPolicy.makeDefaultQuery(category: category.apiValue)
        let boundedRadius = max(1, radiusMeters)
        let queryItems: [URLQueryItem] = [
            URLQueryItem(name: "lat", value: String(center.latitude)),
            URLQueryItem(name: "lng", value: String(center.longitude)),
            URLQueryItem(name: "scope", value: query.scope),
            URLQueryItem(name: "radius", value: String(boundedRadius)),
            URLQueryItem(name: "category", value: query.category),
            URLQueryItem(name: "limit", value: String(query.limit))
        ]

        let requestURL = try makeURL(
            path: "/api/places",
            queryItems: queryItems
        )

        do {
            let (data, response) = try await performRequest(url: requestURL)
            try validate(response: response)

            let decoded = try decoder.decode(RemotePlacesResponse.self, from: data)
            return PlacesSnapshot(
                places: decoded.places.map(Self.mapPlace(from:)),
                city: decoded.city
            )
        } catch {
            throw error
        }
    }

    func fetchWeather(at coordinate: CLLocationCoordinate2D) async throws -> WeatherSnapshot {
        guard baseURL != nil else {
            throw MapServiceError.missingBaseURL
        }
        guard apiKey != nil else {
            throw MapServiceError.missingAPIKey
        }

        let cacheKey = Self.weatherCacheKey(for: coordinate)
        if let cached = await Self.weatherCache.cachedSnapshot(for: cacheKey) {
            return cached
        }
        if let task = await Self.weatherCache.inFlightTask(for: cacheKey) {
            return try await task.value
        }

        let requestURL = try makeURL(
            path: "/api/weather",
            queryItems: [
                URLQueryItem(name: "lat", value: String(coordinate.latitude)),
                URLQueryItem(name: "lng", value: String(coordinate.longitude))
            ]
        )

        let task = Task<WeatherSnapshot, Error> { [self] in
            let (data, response) = try await performRequest(url: requestURL)
            try validate(response: response)

            let decoded = try decoder.decode(RemoteWeatherResponse.self, from: data)
            let normalizedTemp = decoded.temp.trimmingCharacters(in: .whitespacesAndNewlines)
            let normalizedIcon = decoded.icon.trimmingCharacters(in: .whitespacesAndNewlines)
            let normalizedOutdoorStatus = (decoded.outdoorStatus ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let filteredForecast = Self.filterFutureForecast(decoded.forecast)
            let hasRenderableWeather = !normalizedTemp.isEmpty ||
                !normalizedIcon.isEmpty ||
                !normalizedOutdoorStatus.isEmpty ||
                !filteredForecast.isEmpty
            guard hasRenderableWeather else {
                throw MapServiceError.invalidResponse
            }

            let forecast = filteredForecast.map {
                WeatherForecastItem(
                    id: $0.time,
                    timeText: Self.weatherTimeText(from: $0.time),
                    symbolName: Self.weatherSymbolName(from: $0.icon),
                    temperatureText: Self.temperatureText(from: $0.temp)
                )
            }
            return WeatherSnapshot(
                symbolName: Self.weatherSymbolName(from: decoded.icon),
                temperatureText: Self.temperatureText(from: decoded.temp),
                dustText: Self.dustText(from: decoded.dust),
                outdoorStatus: normalizedOutdoorStatus,
                forecast: forecast
            )
        }
        await Self.weatherCache.setInFlight(task, for: cacheKey)

        do {
            let snapshot = try await task.value
            await Self.weatherCache.store(snapshot, for: cacheKey)
            return snapshot
        } catch {
            await Self.weatherCache.clearInFlight(for: cacheKey)
            throw error
        }
    }

    private func performRequest(url: URL) async throws -> (Data, URLResponse) {
        guard let apiKey else {
            throw MapServiceError.missingAPIKey
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 15
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

    private static func makeDefaultSession() -> URLSession {
        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = false
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = 25
        config.httpMaximumConnectionsPerHost = 4
        return URLSession(configuration: config)
    }

    private static func weatherCacheKey(for coordinate: CLLocationCoordinate2D) -> String {
        let lat = (coordinate.latitude * 1000).rounded() / 1000
        let lng = (coordinate.longitude * 1000).rounded() / 1000
        return "\(lat)|\(lng)"
    }

    private static func mapPlace(from item: RemotePlaceItem) -> PlaceRecommendation {
        func normalized(_ value: String?) -> String? {
            guard let value else { return nil }
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }

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
        let nameKo = item.name
        let nameEn = normalized(item.nameEn) ?? nameKo
        let regionKo = normalized(item.region) ?? ""
        let regionEn = normalized(item.regionEn) ?? ""
        let addressKo = normalized(item.address) ?? ""
        let addressEn = normalized(item.addressEn) ?? ""

        let distanceGuideKo = "현재 위치 근처 추천 장소입니다."
        let distanceGuideEn = "This is a recommended place near your location."

        let guideKo = "\(nameKo) \(distanceGuideKo) \(regionKo) \(addressKo)"
        let guideEn = "\(nameEn). \(distanceGuideEn) \(regionEn) \(addressEn)"

        return PlaceRecommendation(
            id: item.id,
            nameKo: nameKo,
            nameEn: nameEn,
            categoryKind: kind,
            categoryKo: categoryKo,
            categoryEn: categoryEn,
            districtKo: regionKo,
            districtEn: regionEn,
            guideKo: guideKo,
            guideEn: guideEn,
            coordinate: CLLocationCoordinate2D(latitude: item.lat, longitude: item.lng),
            distanceMeters: nil,
            addressKo: addressKo,
            addressEn: addressEn,
            imageURL: Self.makeImageURL(from: item.imageURL),
            isOngoing: item.isOngoing,
            eventStartDate: normalized(item.eventStartDate),
            eventEndDate: normalized(item.eventEndDate),
            eventURL: Self.makeImageURL(from: item.eventURL),
            isApproximateLocation: item.isApproximateLocation ?? false
        )
    }

    private static func weatherSymbolName(from icon: String) -> String {
        switch icon {
        case "☀️": return "sun.max.fill"
        case "⛅": return "cloud.sun.fill"
        case "☁️": return "cloud.fill"
        case "🌫️": return "cloud.fog.fill"
        case "🌧️": return "cloud.rain.fill"
        case "🌨️": return "cloud.sleet.fill"
        case "❄️": return "snowflake"
        case "🌦️": return "cloud.sun.rain.fill"
        case "⛈️": return "cloud.bolt.rain.fill"
        default: return "cloud.sun.fill"
        }
    }

    private static func temperatureText(from raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            return "--°C"
        }
        if trimmed.hasSuffix("°C") {
            return trimmed
        }
        return "\(trimmed)°C"
    }

    private static func dustText(from dust: RemoteWeatherDust?) -> String {
        guard let dust else { return "--" }

        let grade = dust.gradeKo?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
            ? dust.gradeKo!.trimmingCharacters(in: .whitespacesAndNewlines)
            : {
                switch dust.grade {
                case "good":
                    return "좋음"
                case "normal":
                    return "보통"
                case "bad":
                    return "나쁨"
                case "very_bad":
                    return "매우나쁨"
                default:
                    return "정보없음"
                }
            }()

        if let pm10 = dust.pm10, let pm25 = dust.pm25 {
            return "미세먼지 \(grade) (PM10 \(pm10) / PM2.5 \(pm25))"
        }
        if let pm10 = dust.pm10 {
            return "미세먼지 \(grade) (PM10 \(pm10))"
        }
        if let pm25 = dust.pm25 {
            return "미세먼지 \(grade) (PM2.5 \(pm25))"
        }
        return "미세먼지 \(grade)"
    }

    private static func weatherTimeText(from raw: String) -> String {
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "ko_KR")
        parser.timeZone = TimeZone(identifier: "Asia/Seoul")
        parser.dateFormat = "yyyy-MM-dd'T'HH:mm"

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ko_KR")
        formatter.timeZone = TimeZone(identifier: "Asia/Seoul")
        formatter.dateFormat = "M/d HH:mm"

        guard let date = parser.date(from: raw) else {
            return raw
        }
        return formatter.string(from: date)
    }

    private static func filterFutureForecast(_ input: [RemoteWeatherForecast]) -> [RemoteWeatherForecast] {
        let now = Date()
        return input.filter { item in
            guard let date = parseForecastDate(item.time) else { return false }
            return date > now
        }
    }

    private static func parseForecastDate(_ raw: String) -> Date? {
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.timeZone = TimeZone(identifier: "Asia/Seoul")
        parser.dateFormat = "yyyy-MM-dd'T'HH:mm"
        if let date = parser.date(from: raw) {
            return date
        }

        let parserWithSeconds = DateFormatter()
        parserWithSeconds.locale = Locale(identifier: "en_US_POSIX")
        parserWithSeconds.timeZone = TimeZone(identifier: "Asia/Seoul")
        parserWithSeconds.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return parserWithSeconds.date(from: raw)
    }

    private static func makeImageURL(from raw: String?) -> URL? {
        guard let raw else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            return nil
        }
        if let url = URL(string: trimmed) {
            return url
        }
        let encoded = trimmed.addingPercentEncoding(withAllowedCharacters: .urlFragmentAllowed)
        if let encoded, let url = URL(string: encoded) {
            return url
        }
        return nil
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
                imageURL: URL(string: seed.image),
                isOngoing: nil,
                eventStartDate: nil,
                eventEndDate: nil,
                eventURL: nil,
                isApproximateLocation: false
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
    let count: Int?
    let scope: String?
    let city: String?
    let places: [RemotePlaceItem]
}

private struct RemotePlaceItem: Decodable {
    let id: String
    let name: String
    let nameEn: String?
    let lat: Double
    let lng: Double
    let category: String
    let address: String?
    let addressEn: String?
    let region: String?
    let regionEn: String?
    let distanceM: Int?
    let imageURL: String?
    let isApproximateLocation: Bool?
    let eventStartDate: String?
    let eventEndDate: String?
    let eventURL: String?
    let isOngoing: Bool?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case nameEn = "name_en"
        case lat
        case lng
        case category
        case address
        case addressEn = "address_en"
        case region
        case regionEn = "region_en"
        case distanceM = "distance_m"
        case imageURL = "image_url"
        case isApproximateLocation = "is_approximate_location"
        case eventStartDate = "event_start_date"
        case eventEndDate = "event_end_date"
        case eventURL = "event_url"
        case isOngoing = "is_ongoing"
    }
}

private struct RemoteWeatherResponse: Decodable {
    let temp: String
    let icon: String
    let dust: RemoteWeatherDust?
    let forecast: [RemoteWeatherForecast]
    let outdoorStatus: String?

    enum CodingKeys: String, CodingKey {
        case temp
        case icon
        case dust
        case forecast
        case outdoorStatus = "outdoor_status"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        temp = try container.decodeLossyString(forKey: .temp) ?? ""
        icon = try container.decodeLossyString(forKey: .icon) ?? ""
        dust = try container.decodeIfPresent(RemoteWeatherDust.self, forKey: .dust)
        forecast = try container.decodeIfPresent([RemoteWeatherForecast].self, forKey: .forecast) ?? []
        outdoorStatus = try container.decodeLossyString(forKey: .outdoorStatus)
    }
}

private struct RemoteWeatherDust: Decodable {
    let pm10: String?
    let pm25: String?
    let grade: String
    let gradeKo: String?

    enum CodingKeys: String, CodingKey {
        case pm10
        case pm25
        case grade
        case gradeKo = "grade_ko"
    }
}

private struct RemoteWeatherForecast: Decodable {
    let time: String
    let temp: String
    let icon: String

    enum CodingKeys: String, CodingKey {
        case time
        case temp
        case icon
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        time = try container.decodeLossyString(forKey: .time) ?? ""
        temp = try container.decodeLossyString(forKey: .temp) ?? ""
        icon = try container.decodeLossyString(forKey: .icon) ?? ""
    }
}

extension KeyedDecodingContainer {
    func decodeLossyString(forKey key: Key) throws -> String? {
        guard contains(key) else { return nil }
        if try decodeNil(forKey: key) {
            return nil
        }
        if let value = try? decode(String.self, forKey: key) {
            return value
        }
        if let value = try? decode(Double.self, forKey: key) {
            return String(value)
        }
        if let value = try? decode(Int.self, forKey: key) {
            return String(value)
        }
        if let value = try? decode(Bool.self, forKey: key) {
            return value ? "true" : "false"
        }
        return nil
    }

    func decodeLossyDouble(forKey key: Key) throws -> Double? {
        guard contains(key) else { return nil }
        if try decodeNil(forKey: key) {
            return nil
        }
        if let value = try? decode(Double.self, forKey: key) {
            return value
        }
        if let value = try? decode(Int.self, forKey: key) {
            return Double(value)
        }
        if let value = try? decode(String.self, forKey: key) {
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty {
                return nil
            }
            return Double(trimmed)
        }
        return nil
    }

    func decodeLossyInt(forKey key: Key) throws -> Int? {
        guard contains(key) else { return nil }
        if try decodeNil(forKey: key) {
            return nil
        }
        if let value = try? decode(Int.self, forKey: key) {
            return value
        }
        if let value = try? decode(Double.self, forKey: key) {
            return Int(value.rounded())
        }
        if let value = try? decode(String.self, forKey: key) {
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty {
                return nil
            }
            if let intValue = Int(trimmed) {
                return intValue
            }
            if let doubleValue = Double(trimmed) {
                return Int(doubleValue.rounded())
            }
        }
        return nil
    }
}
