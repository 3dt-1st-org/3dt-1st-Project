//
//  PlannerRemoteService.swift
//  LALA
//
//  Created by Codex on 3/9/26.
//

import Foundation
import CoreLocation

struct PlannerPlace: Identifiable {
    let id: String
    let name: String
    let coordinate: CLLocationCoordinate2D?
    let roadAddress: String
    let sourceType: String
}

struct PlannerPlanItem: Identifiable {
    let id: String
    let period: String
    let time: String
    let script: String
    let place: PlannerPlace
}

struct PlannerSnapshot {
    let location: String
    let outdoorStatus: String
    let temperatureText: String
    let plan: [PlannerPlanItem]
}

struct InterventionPlace {
    let name: String
    let coordinate: CLLocationCoordinate2D?
    let distanceMeters: Int?
    let roadAddress: String
    let sourceType: String
}

struct InterventionSnapshot {
    let type: String
    let places: [InterventionPlace]
}

protocol PlannerDataProviding {
    func fetchDailyPlan(at coordinate: CLLocationCoordinate2D, language: AppLanguage) async throws -> PlannerSnapshot
    func fetchIntervention(at coordinate: CLLocationCoordinate2D, radiusMeters: Int) async throws -> InterventionSnapshot?
}

final class PlannerRemoteService: PlannerDataProviding {
    private let baseURL: URL?
    private let apiKey: String?
    private let session: URLSession
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    init(
        baseURL: URL? = AppRuntime.apiBaseURL,
        apiKey: String? = AppRuntime.iosAPIKey,
        session: URLSession = PlannerRemoteService.makeDefaultSession()
    ) {
        self.baseURL = baseURL
        self.apiKey = apiKey
        self.session = session
    }

    func fetchDailyPlan(at coordinate: CLLocationCoordinate2D, language: AppLanguage) async throws -> PlannerSnapshot {
        let url = try makeURL(path: "/api/planner/daily-plan", queryItems: [])
        let payload = RemoteDailyPlanRequest(
            lat: coordinate.latitude,
            lng: coordinate.longitude,
            language: language == .korean ? "Korean" : "English"
        )

        var request = try makeRequest(url: url, method: "POST", timeout: 95)
        request.httpBody = try encoder.encode(payload)

        let (data, response) = try await session.data(for: request)
        try validate(response: response)
        let decoded = try decoder.decode(RemoteDailyPlanResponse.self, from: data)

        let weatherStatus = (decoded.weather?.outdoorStatus ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let temperatureRaw = (decoded.weather?.temperature ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let temperatureText: String
        if temperatureRaw.isEmpty {
            temperatureText = ""
        } else if temperatureRaw.hasSuffix("°C") {
            temperatureText = temperatureRaw
        } else {
            temperatureText = "\(temperatureRaw)°C"
        }

        return PlannerSnapshot(
            location: (decoded.location ?? "").trimmingCharacters(in: .whitespacesAndNewlines),
            outdoorStatus: weatherStatus,
            temperatureText: temperatureText,
            plan: decoded.plan.map { item in
                let lat = item.place?.lat
                let lng = item.place?.lng
                let coordinate = (lat != nil && lng != nil)
                    ? CLLocationCoordinate2D(latitude: lat!, longitude: lng!)
                    : nil
                let name = (item.place?.name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                let roadAddress = (item.place?.roadAddress ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                let sourceType = (item.place?.sourceType ?? "attraction").trimmingCharacters(in: .whitespacesAndNewlines)
                let placeID = coordinate == nil ? "planner-\(UUID().uuidString)" : "\(name)-\(lat ?? 0)-\(lng ?? 0)"
                return PlannerPlanItem(
                    id: "planner-slot-\(UUID().uuidString)",
                    period: (item.period ?? "").trimmingCharacters(in: .whitespacesAndNewlines),
                    time: (item.time ?? "").trimmingCharacters(in: .whitespacesAndNewlines),
                    script: (item.script ?? "").trimmingCharacters(in: .whitespacesAndNewlines),
                    place: PlannerPlace(
                        id: placeID,
                        name: name,
                        coordinate: coordinate,
                        roadAddress: roadAddress,
                        sourceType: sourceType
                    )
                )
            }
        )
    }

    func fetchIntervention(at coordinate: CLLocationCoordinate2D, radiusMeters: Int) async throws -> InterventionSnapshot? {
        let url = try makeURL(
            path: "/api/planner/intervention",
            queryItems: [
                URLQueryItem(name: "lat", value: String(coordinate.latitude)),
                URLQueryItem(name: "lng", value: String(coordinate.longitude)),
                URLQueryItem(name: "radius", value: String(max(radiusMeters, 1))),
            ]
        )

        let request = try makeRequest(url: url, method: "GET", timeout: 10)
        let (data, response) = try await session.data(for: request)
        try validate(response: response)

        let decoded = try decoder.decode(RemoteInterventionResponse.self, from: data)
        guard let intervention = decoded.intervention else {
            return nil
        }

        return InterventionSnapshot(
            type: intervention.type,
            places: intervention.places.map { place in
                let coordinate = (place.lat != nil && place.lng != nil)
                    ? CLLocationCoordinate2D(latitude: place.lat!, longitude: place.lng!)
                    : nil
                return InterventionPlace(
                    name: place.name ?? "",
                    coordinate: coordinate,
                    distanceMeters: place.distance,
                    roadAddress: place.roadAddress ?? "",
                    sourceType: place.sourceType ?? "attraction"
                )
            }
        )
    }

    private func makeRequest(url: URL, method: String, timeout: TimeInterval) throws -> URLRequest {
        guard let apiKey else {
            throw PlannerRemoteError.missingAPIKey
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = timeout
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        return request
    }

    private func makeURL(path: String, queryItems: [URLQueryItem]) throws -> URL {
        guard let baseURL else {
            throw PlannerRemoteError.missingBaseURL
        }
        if let host = baseURL.host?.lowercased(),
           host == "localhost" || host == "127.0.0.1" {
            throw PlannerRemoteError.localhostNotAllowed
        }
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            throw PlannerRemoteError.invalidBaseURL
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
        components.queryItems = queryItems.isEmpty ? nil : queryItems

        guard let url = components.url else {
            throw PlannerRemoteError.invalidRequestURL
        }
        return url
    }

    private func validate(response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else {
            throw PlannerRemoteError.invalidResponse
        }
        guard (200 ... 299).contains(http.statusCode) else {
            throw PlannerRemoteError.httpStatus(http.statusCode)
        }
    }

    private static func makeDefaultSession() -> URLSession {
        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = false
        config.timeoutIntervalForRequest = 95
        config.timeoutIntervalForResource = 120
        config.httpMaximumConnectionsPerHost = 2
        return URLSession(configuration: config)
    }
}

enum PlannerRemoteError: LocalizedError {
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

private struct RemoteDailyPlanRequest: Encodable {
    let lat: Double
    let lng: Double
    let language: String
}

private struct RemoteDailyPlanResponse: Decodable {
    let location: String?
    let weather: RemoteDailyPlanWeather?
    let plan: [RemoteDailyPlanItem]
}

private struct RemoteDailyPlanWeather: Decodable {
    let outdoorStatus: String?
    let temperature: String?

    enum CodingKeys: String, CodingKey {
        case outdoorStatus = "outdoor_status"
        case temperature
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        outdoorStatus = try container.decodeLossyString(forKey: .outdoorStatus)
        temperature = try container.decodeLossyString(forKey: .temperature)
    }
}

private struct RemoteDailyPlanItem: Decodable {
    let period: String?
    let time: String?
    let script: String?
    let place: RemoteDailyPlanPlace?
}

private struct RemoteDailyPlanPlace: Decodable {
    let name: String?
    let lat: Double?
    let lng: Double?
    let roadAddress: String?
    let sourceType: String?

    enum CodingKeys: String, CodingKey {
        case name
        case lat
        case lng
        case roadAddress = "road_addr"
        case sourceType = "source_type"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decodeLossyString(forKey: .name)
        lat = try container.decodeLossyDouble(forKey: .lat)
        lng = try container.decodeLossyDouble(forKey: .lng)
        roadAddress = try container.decodeLossyString(forKey: .roadAddress)
        sourceType = try container.decodeLossyString(forKey: .sourceType)
    }
}

private struct RemoteInterventionResponse: Decodable {
    let intervention: RemoteIntervention?
}

private struct RemoteIntervention: Decodable {
    let type: String
    let places: [RemoteInterventionPlace]
}

private struct RemoteInterventionPlace: Decodable {
    let name: String?
    let lat: Double?
    let lng: Double?
    let distance: Int?
    let roadAddress: String?
    let sourceType: String?

    enum CodingKeys: String, CodingKey {
        case name
        case lat
        case lng
        case distance = "dist"
        case roadAddress = "road_addr"
        case sourceType = "source_type"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        name = try container.decodeLossyString(forKey: .name)
        lat = try container.decodeLossyDouble(forKey: .lat)
        lng = try container.decodeLossyDouble(forKey: .lng)
        distance = try container.decodeLossyInt(forKey: .distance)
        roadAddress = try container.decodeLossyString(forKey: .roadAddress)
        sourceType = try container.decodeLossyString(forKey: .sourceType)
    }
}
