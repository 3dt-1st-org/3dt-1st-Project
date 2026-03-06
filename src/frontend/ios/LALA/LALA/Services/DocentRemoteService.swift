import Foundation

struct DocentScriptResponse: Decodable {
    let placeID: String
    let category: String
    let language: String
    let mode: String
    let script: String
    let source: String
    let generatedAt: String
    let ttlSec: Int

    enum CodingKeys: String, CodingKey {
        case placeID = "place_id"
        case category
        case language
        case mode
        case script
        case source
        case generatedAt = "generated_at"
        case ttlSec = "ttl_sec"
    }
}

enum DocentScriptMode: String {
    case brief
    case detail
}

protocol DocentRemoteProviding {
    func fetchDocentScript(
        placeID: String,
        category: PlaceCategoryKind,
        language: AppLanguage,
        mode: DocentScriptMode
    ) async throws -> DocentScriptResponse

    func fetchDocentAudio(script: String, language: AppLanguage) async throws -> Data
}

final class DocentRemoteService: DocentRemoteProviding {
    private let baseURL: URL?
    private let apiKey: String?
    private let session: URLSession
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()
    private var scriptCache: [String: DocentScriptResponse] = [:]
    private var audioCache: [String: Data] = [:]

    init(
        baseURL: URL? = AppRuntime.apiBaseURL,
        apiKey: String? = AppRuntime.iosAPIKey,
        session: URLSession = DocentRemoteService.makeDefaultSession()
    ) {
        self.baseURL = baseURL
        self.apiKey = apiKey
        self.session = session
    }

    func fetchDocentScript(
        placeID: String,
        category: PlaceCategoryKind,
        language: AppLanguage,
        mode: DocentScriptMode
    ) async throws -> DocentScriptResponse {
        let cacheKey = scriptCacheKey(
            placeID: placeID,
            category: category,
            language: language,
            mode: mode
        )
        if let cached = scriptCache[cacheKey] {
            return cached
        }

        let result = try await requestDocentScript(
            placeID: placeID,
            category: category,
            language: language,
            mode: mode
        )
        if result.source != "fallback" {
            scriptCache[cacheKey] = result
        }
        return result
    }

    func fetchDocentAudio(script: String, language: AppLanguage) async throws -> Data {
        let trimmedScript = script.trimmingCharacters(in: .whitespacesAndNewlines)
        let cacheKey = audioCacheKey(script: trimmedScript, language: language)
        if let cached = audioCache[cacheKey] {
            return cached
        }
        let data = try await requestDocentAudio(script: trimmedScript, language: language)
        audioCache[cacheKey] = data
        return data
    }

    private func requestDocentScript(
        placeID: String,
        category: PlaceCategoryKind,
        language: AppLanguage,
        mode: DocentScriptMode
    ) async throws -> DocentScriptResponse {
        let url = try makeURL(path: "/api/ios/v1/docent/script")
        let payload = DocentScriptRequest(
            placeID: placeID,
            category: category.rawValue,
            language: language.rawValue,
            mode: mode.rawValue
        )

        var request = try makeRequest(url: url, method: "POST", timeout: 12)
        request.httpBody = try encoder.encode(payload)

        let (data, response) = try await session.data(for: request)
        try validate(response: response)
        return try decoder.decode(DocentScriptResponse.self, from: data)
    }

    private func requestDocentAudio(script: String, language: AppLanguage) async throws -> Data {
        let url = try makeURL(path: "/api/ios/v1/docent/audio")
        let payload = DocentAudioRequest(script: script, language: language.rawValue)

        var request = try makeRequest(url: url, method: "POST", timeout: 20)
        request.httpBody = try encoder.encode(payload)

        let (data, response) = try await session.data(for: request)
        try validate(response: response)
        return data
    }

    private func scriptCacheKey(
        placeID: String,
        category: PlaceCategoryKind,
        language: AppLanguage,
        mode: DocentScriptMode
    ) -> String {
        "\(placeID)|\(category.rawValue)|\(language.rawValue)|\(mode.rawValue)"
    }

    private func audioCacheKey(script: String, language: AppLanguage) -> String {
        "\(language.rawValue)|\(script)"
    }

    private func makeRequest(url: URL, method: String, timeout: TimeInterval) throws -> URLRequest {
        guard let apiKey else {
            throw DocentRemoteError.missingAPIKey
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = timeout
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        return request
    }

    private func makeURL(path: String) throws -> URL {
        guard let baseURL else {
            throw DocentRemoteError.missingBaseURL
        }
        if let host = baseURL.host?.lowercased(), host == "localhost" || host == "127.0.0.1" {
            throw DocentRemoteError.localhostNotAllowed
        }

        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            throw DocentRemoteError.invalidBaseURL
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

        guard let url = components.url else {
            throw DocentRemoteError.invalidRequestURL
        }

        return url
    }

    private func validate(response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else {
            throw DocentRemoteError.invalidResponse
        }
        guard (200 ... 299).contains(http.statusCode) else {
            throw DocentRemoteError.httpStatus(http.statusCode)
        }
    }

    private static func makeDefaultSession() -> URLSession {
        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = false
        config.timeoutIntervalForRequest = 12
        config.timeoutIntervalForResource = 25
        config.httpMaximumConnectionsPerHost = 2
        return URLSession(configuration: config)
    }
}

private struct DocentScriptRequest: Encodable {
    let placeID: String
    let category: String
    let language: String
    let mode: String

    enum CodingKeys: String, CodingKey {
        case placeID = "place_id"
        case category
        case language
        case mode
    }
}

private struct DocentAudioRequest: Encodable {
    let script: String
    let language: String
}

enum DocentRemoteError: LocalizedError {
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
