//
//  MainMapViewModel.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import Combine
import MapKit
import AVFoundation
import CoreLocation
import SwiftUI

@MainActor
final class MainMapViewModel: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published var region: MKCoordinateRegion
    @Published var isVoiceGuidanceEnabled = true
    @Published var isAutoDocentEnabled = false
    @Published var subtitle = ""
    @Published var weatherSymbol = WeatherSnapshot.placeholder.symbolName
    @Published var weatherValue = WeatherSnapshot.placeholder.temperatureText
    @Published var weatherDust = WeatherSnapshot.placeholder.dustText
    @Published private(set) var weatherForecast: [WeatherForecastItem] = []
    @Published var isWeatherDetailPresented = false
    @Published var selectedPlaceID: String?
    @Published private(set) var userCoordinate: CLLocationCoordinate2D?
    @Published private(set) var places: [PlaceRecommendation]
    @Published var selectedFilter: MapPlaceFilter = .all
    @Published private(set) var isLoadingPlaces = false
    @Published private(set) var mapStatus: MapStatus = .none
    @Published private(set) var moreInfoEligiblePlaceID: String?

    private var audioPlayer: AVAudioPlayer?
    private let locationManager = CLLocationManager()
    private let mapDataProvider: MapDataProviding
    private let docentDataProvider: DocentRemoteProviding
    private let searchRadiusMeters = 10_000
    private let autoDocentTriggerRadiusMeters: CLLocationDistance = 100
    private let placesReloadThresholdMeters: CLLocationDistance = 3_000
    private let weatherReloadThresholdMeters: CLLocationDistance = 10_000
    private let placesLoadingMaxSeconds: Double = 20
    private let placesFailureRetryCooldownSeconds: Double = 8
    private let defaultMapSpan = MKCoordinateSpan(latitudeDelta: 0.01, longitudeDelta: 0.01)
    private var hasAppliedInitialUserFocus = false
    private var isAppLocationConsentEnabled = false
    private var activeLanguage: AppLanguage = .korean
    private var reloadTask: Task<Void, Never>?
    private var weatherTask: Task<Void, Never>?
    private var narrationTask: Task<Void, Never>?
    private var lastAutoGuidedPlaceID: String?
    private var hiddenMoreInfoPlaceID: String?
    private var allPlaces: [PlaceRecommendation] = []
    private var lastPlacesFetchCoordinate: CLLocationCoordinate2D?
    private var lastPlacesFetchCity: String?
    private var lastWeatherFetchCoordinate: CLLocationCoordinate2D?
    private var placesReloadToken = 0
    private var placesLoadingStartedAt: Date?
    private var lastPlacesFailureAt: Date?
    private var lastPlacesFailureCoordinate: CLLocationCoordinate2D?
    private var placesFailureRetryTask: Task<Void, Never>?

    private let initialRegion = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 36.35, longitude: 127.9),
        span: MKCoordinateSpan(latitudeDelta: 7.0, longitudeDelta: 8.0)
    )

    init(
        mapDataProvider: MapDataProviding? = nil,
        docentDataProvider: DocentRemoteProviding? = nil
    ) {
        self.mapDataProvider = mapDataProvider ?? MapRemoteService()
        self.docentDataProvider = docentDataProvider ?? DocentRemoteService()
        region = initialRegion
        places = []
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    func refreshSubtitle(for language: AppLanguage) {
        activeLanguage = language
        subtitle = voiceOnSubtitle(for: language)
    }

    func updateLanguage(_ language: AppLanguage) {
        activeLanguage = language
        if let selectedPlace {
            subtitle = docentLoadingText(for: language)
            loadDocentScriptAndAudio(for: selectedPlace, language: language, mode: .brief)
        } else {
            subtitle = voiceOnSubtitle(for: language)
        }
    }

    func toggleVoiceGuidance(for language: AppLanguage) {
        isVoiceGuidanceEnabled.toggle()
        if !isVoiceGuidanceEnabled {
            stopNarrationPlayback()
        }
        // Do not replace current caption with a "voice off" notice.
        if isVoiceGuidanceEnabled, selectedPlaceID == nil {
            subtitle = voiceOnSubtitle(for: language)
        }
        if isAutoDocentEnabled {
            runAutoDocentIfNeeded(language: language, forceAnnounce: false)
        }
    }

    func toggleAutoDocentMode(for language: AppLanguage) {
        activeLanguage = language
        isAutoDocentEnabled.toggle()
        if isAutoDocentEnabled {
            runAutoDocentIfNeeded(language: language, forceAnnounce: true)
        } else {
            lastAutoGuidedPlaceID = nil
        }
    }

    func selectFilter(_ filter: MapPlaceFilter) {
        guard selectedFilter != filter else { return }
        selectedFilter = filter
        applyFilteredPlaces()
    }

    func handlePlaceTap(_ place: PlaceRecommendation, language: AppLanguage) {
        applySelection(for: place, language: language)
    }

    func handleMapPinTap(_ place: PlaceRecommendation, language: AppLanguage) {
        applySelection(for: place, language: language)
    }

    func activatePlaceForDetail(_ place: PlaceRecommendation, language: AppLanguage) {
        activeLanguage = language
        selectedPlaceID = place.id
        hiddenMoreInfoPlaceID = nil
        subtitle = docentLoadingText(for: language)
        lastAutoGuidedPlaceID = place.id
        moreInfoEligiblePlaceID = place.id
        centerOnPlace(place, animated: true)
        loadDocentScriptAndAudio(for: place, language: language, mode: .brief)
    }

    func weatherA11yText(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "현재 날씨 \(weatherValue), \(weatherDust). 탭하면 예보를 볼 수 있습니다."
        case .english:
            return "Current weather \(weatherValue), \(weatherDust). Tap to see forecast."
        }
    }

    func weatherDetailTitle(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "날씨 예보"
        case .english:
            return "Weather Forecast"
        }
    }

    func weatherDetailSubtitle(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "현재 \(weatherValue) · \(weatherDust)"
        case .english:
            return "Now \(weatherValue) · \(weatherDust)"
        }
    }

    func weatherForecastEmptyText(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "예보 정보를 불러오지 못했습니다."
        case .english:
            return "Forecast data is unavailable."
        }
    }

    func presentWeatherDetail() {
        isWeatherDetailPresented = true
        reloadWeather(force: true)
    }

    func statusMessage(for language: AppLanguage) -> String? {
        switch mapStatus {
        case .none:
            return nil
        case .noResults:
            switch language {
            case .korean:
                return "주변 추천 장소가 없습니다."
            case .english:
                return "No recommended places found nearby."
            }
        case .networkError:
            switch language {
            case .korean:
                return "데이터를 불러오지 못했습니다. API 서버 설정 또는 네트워크를 확인하세요."
            case .english:
                return "Failed to load data. Check API server configuration or network."
            }
        }
    }

    var selectedPlace: PlaceRecommendation? {
        guard let selectedPlaceID else { return nil }
        return places.first(where: { $0.id == selectedPlaceID })
    }

    func recommendationTitle(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "추천 이유"
        case .english:
            return "Why This Place"
        }
    }

    func recommendationReason(for place: PlaceRecommendation, language: AppLanguage) -> String {
        let category = place.category(in: language)
        let district = place.district(in: language)
        let address = place.address(in: language)
        let distance = place.distanceLabel(in: language) ?? ""

        switch language {
        case .korean:
            if distance.isEmpty {
                return "\(district)의 \(category) 카테고리에서 인기가 높은 장소예요. \(address)"
            }
            return "현재 위치에서 약 \(distance) 거리의 \(category) 추천 장소예요. \(address)"
        case .english:
            if distance.isEmpty {
                return "A highly rated \(category.lowercased()) spot around \(district). \(address)"
            }
            return "A recommended \(category.lowercased()) spot about \(distance) from your current location. \(address)"
        }
    }

    func moreInfoButtonTitle(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "정보 더 듣기"
        case .english:
            return "Hear More Info"
        }
    }

    func canPlayMoreInfo(for placeID: String) -> Bool {
        moreInfoEligiblePlaceID == placeID &&
            hiddenMoreInfoPlaceID != placeID
    }

    func playMoreInfo(for place: PlaceRecommendation, language: AppLanguage) {
        guard canPlayMoreInfo(for: place.id) else { return }
        activeLanguage = language
        hiddenMoreInfoPlaceID = place.id
        moreInfoEligiblePlaceID = nil
        subtitle = docentLoadingText(for: language)
        loadDocentScriptAndAudio(for: place, language: language, mode: .detail)
    }

    private func voiceOnSubtitle(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "음성 안내: 지금 위치 기준 15분 거리의 로컬 맛집과 산책 코스를 안내해드릴게요."
        case .english:
            return "Voice guide: I can guide you to local food spots and walks within 15 minutes."
        }
    }

    private func docentLoadingText(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "도슨트 정보를 생성하고 있어요. 잠시만 기다려 주세요."
        case .english:
            return "Generating docent guidance. Please wait a moment."
        }
    }

    private func docentUnavailableText(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "도슨트 응답을 받아오지 못했습니다. 잠시 후 다시 시도해 주세요."
        case .english:
            return "Unable to load docent response. Please try again shortly."
        }
    }

    private func loadDocentScriptAndAudio(
        for place: PlaceRecommendation,
        language: AppLanguage,
        mode: DocentScriptMode
    ) {
        stopNarrationPlayback()
        narrationTask = Task { [weak self] in
            guard let self else { return }
            do {
                let response = try await docentDataProvider.fetchDocentScript(
                    placeID: place.id,
                    category: place.categoryKind,
                    language: language,
                    mode: mode
                )
                guard !Task.isCancelled else { return }

                // Avoid showing server-side fallback template text in UI.
                guard response.source != "fallback" else {
                    subtitle = docentUnavailableText(for: language)
                    return
                }

                subtitle = response.script

                guard isVoiceGuidanceEnabled else { return }
                do {
                    let audioData = try await docentDataProvider.fetchDocentAudio(
                        script: response.script,
                        language: language
                    )
                    guard !Task.isCancelled else { return }
                    playAudio(data: audioData)
                } catch {
                    // Keep LLM script visible even when TTS fails.
                }
            } catch {
                guard !Task.isCancelled else { return }
                subtitle = docentUnavailableText(for: language)
            }
        }
    }

    private func stopNarrationPlayback() {
        narrationTask?.cancel()
        narrationTask = nil
        audioPlayer?.stop()
        audioPlayer = nil
    }

    private func playNarrationAudio(text: String, language: AppLanguage) {
        guard isVoiceGuidanceEnabled else { return }
        stopNarrationPlayback()

        narrationTask = Task { [weak self] in
            guard let self else { return }
            do {
                let audioData = try await docentDataProvider.fetchDocentAudio(
                    script: text,
                    language: language
                )
                guard !Task.isCancelled else { return }
                playAudio(data: audioData)
            } catch {
                // Keep subtitle visible even when audio generation fails.
            }
        }
    }

    private func playAudio(data: Data) {
        do {
            let player = try AVAudioPlayer(data: data)
            player.prepareToPlay()
            player.play()
            audioPlayer = player
        } catch {
            audioPlayer = nil
        }
    }

    private func applySelection(for place: PlaceRecommendation, language: AppLanguage) {
        let result = MapGuidanceLogic.reduceSelection(
            currentSelectedPlaceID: selectedPlaceID,
            tappedPlaceID: place.id,
            tappedSubtitle: place.guide(in: language),
            defaultSubtitle: defaultSubtitle(for: language),
            isVoiceGuidanceEnabled: isVoiceGuidanceEnabled
        )

        selectedPlaceID = result.selectedPlaceID
        subtitle = result.subtitle

        if result.selectedPlaceID == nil {
            hiddenMoreInfoPlaceID = nil
            moreInfoEligiblePlaceID = nil
        } else if result.selectedPlaceID != hiddenMoreInfoPlaceID {
            hiddenMoreInfoPlaceID = nil
            moreInfoEligiblePlaceID = result.selectedPlaceID
        }

        if result.shouldStopSpeaking {
            stopNarrationPlayback()
        }
        if result.shouldCenterMap {
            centerOnPlace(place, animated: true)
        }
        if result.selectedPlaceID == place.id {
            moreInfoEligiblePlaceID = place.id
            subtitle = docentLoadingText(for: language)
            loadDocentScriptAndAudio(for: place, language: language, mode: .brief)
        } else {
            moreInfoEligiblePlaceID = nil
        }
        if let selected = result.selectedPlaceID {
            lastAutoGuidedPlaceID = selected
        }
    }

    private func defaultSubtitle(for language: AppLanguage) -> String {
        voiceOnSubtitle(for: language)
    }

    func clampRegion(_ candidate: MKCoordinateRegion) -> MKCoordinateRegion {
        var next = candidate

        #if targetEnvironment(simulator)
        // In simulator tests, allow global coordinates (custom GPX routes can be outside Korea).
        next.center.latitude = min(max(next.center.latitude, -85.0), 85.0)
        next.center.longitude = min(max(next.center.longitude, -180.0), 180.0)
        #else
        // On device, keep the visible center inside Korea bounds.
        next.center.latitude = min(max(next.center.latitude, 33.0), 38.8)
        next.center.longitude = min(max(next.center.longitude, 124.0), 132.2)
        #endif

        // Limit zoom-out and zoom-in ranges.
        next.span.latitudeDelta = min(max(next.span.latitudeDelta, 0.002), 8.0)
        next.span.longitudeDelta = min(max(next.span.longitudeDelta, 0.002), 8.0)

        return next
    }

    func updateRegionFromMap(_ candidate: MKCoordinateRegion) {
        let clamped = clampRegion(candidate)
        guard !isNearlyEqual(region, clamped) else { return }
        // Avoid mutating ObservableObject synchronously during SwiftUI Map update passes.
        Task { @MainActor [weak self] in
            guard let self else { return }
            guard !isNearlyEqual(region, clamped) else { return }
            region = clamped
        }
    }

    private func refreshData(forcePlaces: Bool = false, forceWeather: Bool = false) {
        reloadPlaces(force: forcePlaces)
        reloadWeather(force: forceWeather)
    }

    private func reloadPlaces(force: Bool) {
        guard isAppLocationConsentEnabled else { return }
        guard let anchor = userCoordinate else { return }
        if !force, let failedAt = lastPlacesFailureAt {
            let elapsed = Date().timeIntervalSince(failedAt)
            if elapsed < placesFailureRetryCooldownSeconds {
                if let failedCoordinate = lastPlacesFailureCoordinate,
                   distance(from: failedCoordinate, to: anchor) >= placesReloadThresholdMeters {
                    // User has moved enough from failed point: allow immediate retry.
                } else {
                    schedulePlacesRetryAfterCooldown(failedAt: failedAt)
                    return
                }
            }
        }
        if isLoadingPlaces && !force {
            return
        }
        guard force || shouldReloadPlaces(for: anchor) else {
            applyFilteredPlaces()
            return
        }

        placesFailureRetryTask?.cancel()
        placesFailureRetryTask = nil
        if force {
            reloadTask?.cancel()
        }
        placesReloadToken += 1
        let token = placesReloadToken
        reloadTask = Task { [weak self] in
            guard let self else { return }
            isLoadingPlaces = true
            placesLoadingStartedAt = Date()
            mapStatus = .none
            startPlacesLoadingWatchdog(for: token)
            defer {
                if placesReloadToken == token {
                    isLoadingPlaces = false
                    placesLoadingStartedAt = nil
                    reloadTask = nil
                }
            }

            do {
                let loadedPlaces = try await mapDataProvider.fetchPlaces(
                    center: anchor,
                    radiusMeters: searchRadiusMeters,
                    category: .all,
                    cityHint: lastPlacesFetchCity
                )
                guard !Task.isCancelled else { return }
                guard placesReloadToken == token else { return }

                allPlaces = loadedPlaces.places
                lastPlacesFetchCoordinate = anchor
                lastPlacesFetchCity = loadedPlaces.city
                lastPlacesFailureAt = nil
                lastPlacesFailureCoordinate = nil
                applyFilteredPlaces()
            } catch {
                guard !Task.isCancelled else { return }
                guard placesReloadToken == token else { return }
                lastPlacesFailureAt = Date()
                lastPlacesFailureCoordinate = anchor
                if allPlaces.isEmpty {
                    mapStatus = .networkError
                } else {
                    mapStatus = .none
                }
            }
        }
    }

    private func schedulePlacesRetryAfterCooldown(failedAt: Date) {
        let elapsed = Date().timeIntervalSince(failedAt)
        let remaining = max(0.2, placesFailureRetryCooldownSeconds - elapsed)

        placesFailureRetryTask?.cancel()
        placesFailureRetryTask = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(nanoseconds: UInt64(remaining * 1_000_000_000))
            guard !Task.isCancelled else { return }
            guard mapStatus == .networkError else { return }
            reloadPlaces(force: true)
        }
    }

    private func startPlacesLoadingWatchdog(for token: Int) {
        Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(nanoseconds: UInt64(placesLoadingMaxSeconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            guard placesReloadToken == token else { return }
            guard isLoadingPlaces else { return }
            guard let started = placesLoadingStartedAt else { return }
            guard Date().timeIntervalSince(started) >= placesLoadingMaxSeconds else { return }

            reloadTask?.cancel()
            reloadTask = nil
            isLoadingPlaces = false
            placesLoadingStartedAt = nil
            mapStatus = .networkError
        }
    }

    private func reloadWeather(force: Bool) {
        guard isAppLocationConsentEnabled, let coordinate = userCoordinate else { return }
        guard force || shouldReloadWeather(for: coordinate) else { return }

        weatherTask?.cancel()
        weatherTask = Task { [weak self] in
            guard let self else { return }
            do {
                var weatherResult = try await mapDataProvider.fetchWeather(at: coordinate)
                if weatherResult.forecast.isEmpty,
                   let retried = try? await mapDataProvider.fetchWeather(at: coordinate),
                   !retried.forecast.isEmpty {
                    weatherResult = retried
                }
                guard !Task.isCancelled else { return }

                weatherSymbol = weatherResult.symbolName
                weatherValue = weatherResult.temperatureText
                weatherDust = weatherResult.dustText
                weatherForecast = weatherResult.forecast
                lastWeatherFetchCoordinate = coordinate
            } catch {
                guard !Task.isCancelled else { return }
                weatherSymbol = WeatherSnapshot.placeholder.symbolName
                weatherValue = WeatherSnapshot.placeholder.temperatureText
                weatherDust = WeatherSnapshot.placeholder.dustText
                weatherForecast = []
            }
        }
    }

    private func applyFilteredPlaces() {
        let filteredPlaces: [PlaceRecommendation]
        switch selectedFilter {
        case .all:
            filteredPlaces = allPlaces
        case .attraction:
            filteredPlaces = allPlaces.filter { $0.categoryKind == .attraction }
        case .restaurant:
            filteredPlaces = allPlaces.filter { $0.categoryKind == .restaurant }
        case .event:
            filteredPlaces = allPlaces.filter { $0.categoryKind == .event }
        }

        places = filteredPlaces
        mapStatus = filteredPlaces.isEmpty ? .noResults : .none

        guard let selectedPlaceID else { return }
        if !filteredPlaces.contains(where: { $0.id == selectedPlaceID }) {
            self.selectedPlaceID = nil
            hiddenMoreInfoPlaceID = nil
            moreInfoEligiblePlaceID = nil
            subtitle = defaultSubtitle(for: activeLanguage)
            stopNarrationPlayback()
        }

        runAutoDocentIfNeeded(language: activeLanguage, forceAnnounce: false)
    }

    private func shouldReloadPlaces(for coordinate: CLLocationCoordinate2D) -> Bool {
        if allPlaces.isEmpty {
            return true
        }
        if lastPlacesFetchCoordinate == nil {
            return true
        }
        guard let last = lastPlacesFetchCoordinate else { return true }
        return distance(from: last, to: coordinate) >= placesReloadThresholdMeters
    }

    private func shouldReloadWeather(for coordinate: CLLocationCoordinate2D) -> Bool {
        if lastWeatherFetchCoordinate == nil {
            return true
        }
        guard let last = lastWeatherFetchCoordinate else { return true }
        return distance(from: last, to: coordinate) >= weatherReloadThresholdMeters
    }

    func retryLoadingPlaces() {
        // Retry should only refresh place data.
        // Weather must change only when user location meaningfully changes.
        reloadPlaces(force: true)
    }

    func configureLocationUpdates(consentEnabled: Bool) {
        isAppLocationConsentEnabled = consentEnabled
        guard consentEnabled else {
            locationManager.stopUpdatingLocation()
            reloadTask?.cancel()
            weatherTask?.cancel()
            placesFailureRetryTask?.cancel()
            isLoadingPlaces = false
            return
        }

        let status = locationManager.authorizationStatus
        switch status {
        case .notDetermined:
            locationManager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways:
            locationManager.startUpdatingLocation()
            locationManager.requestLocation()
            refreshData(forcePlaces: allPlaces.isEmpty, forceWeather: false)
        case .denied, .restricted:
            locationManager.stopUpdatingLocation()
        @unknown default:
            locationManager.stopUpdatingLocation()
        }
    }

    func centerOnUserLocation(animated: Bool = true) {
        guard let coordinate = userCoordinate else {
            locationManager.requestLocation()
            return
        }

        let focused = MKCoordinateRegion(
            center: coordinate,
            span: defaultMapSpan
        )
        let clamped = clampRegion(focused)
        if animated {
            withAnimation(.easeInOut(duration: 0.55)) {
                region = clamped
            }
        } else {
            region = clamped
        }
        refreshData(forcePlaces: true, forceWeather: false)
    }

    func centerOnPlace(_ place: PlaceRecommendation, animated: Bool) {
        let focused = MKCoordinateRegion(
            center: place.coordinate,
            span: defaultMapSpan
        )
        let clamped = clampRegion(focused)
        if animated {
            withAnimation(.easeInOut(duration: 0.45)) {
                region = clamped
            }
        } else {
            region = clamped
        }
    }

    private func isNearlyEqual(_ lhs: MKCoordinateRegion, _ rhs: MKCoordinateRegion) -> Bool {
        abs(lhs.center.latitude - rhs.center.latitude) < 0.000_01 &&
            abs(lhs.center.longitude - rhs.center.longitude) < 0.000_01 &&
            abs(lhs.span.latitudeDelta - rhs.span.latitudeDelta) < 0.000_01 &&
            abs(lhs.span.longitudeDelta - rhs.span.longitudeDelta) < 0.000_01
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        configureLocationUpdates(consentEnabled: isAppLocationConsentEnabled)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let latest = locations.last else { return }
        userCoordinate = latest.coordinate

        if !hasAppliedInitialUserFocus {
            hasAppliedInitialUserFocus = true
            let focused = MKCoordinateRegion(
                center: latest.coordinate,
                span: defaultMapSpan
            )
            region = clampRegion(focused)
        }

        refreshDistancesForCurrentLocation(latest.coordinate)
        refreshData(forcePlaces: false, forceWeather: false)
        runAutoDocentIfNeeded(language: activeLanguage, forceAnnounce: false)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // Keep UI responsive even if a one-shot location request fails.
        isLoadingPlaces = false
    }

    private func runAutoDocentIfNeeded(language: AppLanguage, forceAnnounce: Bool) {
        guard isAutoDocentEnabled, let userCoordinate, !places.isEmpty else { return }
        guard let nearest = nearestPlace(to: userCoordinate) else { return }
        guard nearest.distance <= autoDocentTriggerRadiusMeters else {
            // Keep silent outside trigger radius and reset so entering range can announce.
            lastAutoGuidedPlaceID = nil
            return
        }
        guard forceAnnounce || nearest.place.id != lastAutoGuidedPlaceID else { return }

        selectedPlaceID = nearest.place.id
        hiddenMoreInfoPlaceID = nil
        subtitle = docentLoadingText(for: language)
        lastAutoGuidedPlaceID = nearest.place.id
        moreInfoEligiblePlaceID = nearest.place.id

        loadDocentScriptAndAudio(for: nearest.place, language: language, mode: .brief)
    }

    private func nearestPlace(to userCoordinate: CLLocationCoordinate2D) -> (place: PlaceRecommendation, distance: CLLocationDistance)? {
        places
            .map { place in
                (place: place, distance: distance(from: userCoordinate, to: place.coordinate))
            }
            .min { lhs, rhs in
                lhs.distance < rhs.distance
            }
    }

    private func distance(from lhs: CLLocationCoordinate2D, to rhs: CLLocationCoordinate2D) -> CLLocationDistance {
        CLLocation(latitude: lhs.latitude, longitude: lhs.longitude)
            .distance(from: CLLocation(latitude: rhs.latitude, longitude: rhs.longitude))
    }

    private func refreshDistancesForCurrentLocation(_ coordinate: CLLocationCoordinate2D) {
        guard !allPlaces.isEmpty else { return }
        allPlaces = allPlaces
            .map { place in
                let nextDistance = Int(distance(from: coordinate, to: place.coordinate).rounded())
                return place.updatingDistanceMeters(nextDistance)
            }
            .sorted { ($0.distanceMeters ?? Int.max) < ($1.distanceMeters ?? Int.max) }
        applyFilteredPlaces()
    }
}

enum MapStatus {
    case none
    case noResults
    case networkError
}
