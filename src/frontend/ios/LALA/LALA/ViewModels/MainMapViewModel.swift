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
    @Published var weatherOutdoorStatus = WeatherSnapshot.placeholder.outdoorStatus
    @Published private(set) var weatherForecast: [WeatherForecastItem] = []
    @Published var isWeatherDetailPresented = false

    @Published var isPlannerPresented = false
    @Published private(set) var plannerSnapshot: PlannerSnapshot?
    @Published private(set) var isPlannerLoading = false
    @Published private(set) var plannerErrorMessage: String?

    @Published var selectedPlaceID: String?
    @Published private(set) var userCoordinate: CLLocationCoordinate2D?
    @Published private(set) var places: [PlaceRecommendation]
    @Published private(set) var placesRenderID = UUID()
    @Published var selectedFilter: MapPlaceFilter = .all
    @Published private(set) var isLoadingPlaces = false
    @Published private(set) var mapStatus: MapStatus = .none
    @Published private(set) var moreInfoEligiblePlaceID: String?
    @Published private(set) var interventionToastMessage: String?
    @Published private(set) var isLocationOverlayVisible = false

    private var audioPlayer: AVAudioPlayer?
    private let locationManager = CLLocationManager()
    private let mapDataProvider: MapDataProviding
    private let docentDataProvider: DocentRemoteProviding
    private let plannerDataProvider: PlannerDataProviding

    private let searchRadiusMeters = PlacesReloadPolicy.defaultRadiusMeters
    private let autoDocentTriggerRadiusMeters: CLLocationDistance = 100
    private let autoDocentRequestCooldownSeconds: Double = 12
    private let placesReloadThresholdMeters: CLLocationDistance = 250
    private let userDrivenPlacesReloadDistanceMeters: CLLocationDistance = 500
    private let userDrivenPlacesReloadCooldownSeconds: Double = 12
    private let manualMapContextHoldSeconds: Double = 18
    private let mapCenteredOnUserThresholdMeters: CLLocationDistance = 1_200
    private let weatherReloadThresholdMeters: CLLocationDistance = WeatherReloadPolicy.defaultDistanceThresholdMeters
    private let weatherMaxAgeSeconds: TimeInterval = WeatherReloadPolicy.defaultMaxAgeSeconds
    private let placesLoadingMaxSeconds: Double = 20
    private let placesFailureRetryCooldownSeconds: Double = 8
    private let weatherFailureRetryCooldownSeconds: Double = 8
    private let defaultMapSpan = MKCoordinateSpan(latitudeDelta: 0.018, longitudeDelta: 0.018)

    private var hasAppliedInitialUserFocus = false
    private var hasBootstrappedInitialData = false
    private var pendingInitialLocationBootstrap = false
    private var pendingForceReloadFromLocationRequest = false

    private var isAppLocationConsentEnabled = false
    private var activeLanguage: AppLanguage = .korean
    private var reloadTask: Task<Void, Never>?
    private var weatherTask: Task<Void, Never>?
    private var narrationTask: Task<Void, Never>?
    private var plannerTask: Task<Void, Never>?
    private var interventionHideTask: Task<Void, Never>?
    private var mapCenterReloadDebounceTask: Task<Void, Never>?

    private var isDocentRequestInFlight = false
    private var lastAutoDocentRequestedAt: Date?
    private var lastAutoGuidedPlaceID: String?
    private var hiddenMoreInfoPlaceID: String?

    private var allPlaces: [PlaceRecommendation] = []
    private var lastPlacesFetchCenter: CLLocationCoordinate2D?
    private var lastWeatherFetchCoordinate: CLLocationCoordinate2D?
    private var lastWeatherFetchAt: Date?

    private var lastWeatherFailureAt: Date?
    private var placesReloadToken = 0
    private var placesLoadingStartedAt: Date?
    private var lastPlacesFailureAt: Date?
    private var lastPlacesFailureCenter: CLLocationCoordinate2D?
    private var placesFailureRetryTask: Task<Void, Never>?
    private var lastWeatherFailureCoordinate: CLLocationCoordinate2D?
    private var weatherFailureRetryTask: Task<Void, Never>?
    private var suppressNextRegionDrivenReload = false
    private var suppressMapCameraReloadUntil: Date?
    private var lastMapCameraInteractionAt: Date?
    private var lastUserDrivenPlacesCoordinate: CLLocationCoordinate2D?
    private var lastUserDrivenPlacesReloadAt: Date?

    private let initialRegion = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 37.2636, longitude: 127.0286),
        span: MKCoordinateSpan(latitudeDelta: 0.018, longitudeDelta: 0.018)
    )

    init(
        mapDataProvider: MapDataProviding? = nil,
        docentDataProvider: DocentRemoteProviding? = nil,
        plannerDataProvider: PlannerDataProviding? = nil
    ) {
        self.mapDataProvider = mapDataProvider ?? MapRemoteService()
        self.docentDataProvider = docentDataProvider ?? DocentRemoteService()
        self.plannerDataProvider = plannerDataProvider ?? PlannerRemoteService()
        region = initialRegion
        places = []
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        subtitle = voiceOnSubtitle(for: .korean)
        applyRuntimeConfigurationStatus()
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
        reloadPlaces(force: true, anchorCenter: region.center)
    }

    func handlePlaceTap(_ place: PlaceRecommendation, language: AppLanguage) {
        applySelection(for: place, language: language, shouldCenterMapOnSelection: true)
    }

    func handleMapPinTap(_ place: PlaceRecommendation, language: AppLanguage) {
        applySelection(for: place, language: language, shouldCenterMapOnSelection: false)
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
        let weatherSummary = [weatherOutdoorStatus, weatherValue].filter { !$0.isEmpty }.joined(separator: " · ")
        switch language {
        case .korean:
            return "현재 날씨 \(weatherSummary), \(weatherDust). 탭하면 예보를 볼 수 있습니다."
        case .english:
            return "Current weather \(weatherSummary), \(weatherDust). Tap to see forecast."
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
            let status = weatherOutdoorStatus.isEmpty ? "보통" : weatherOutdoorStatus
            return "현재 \(status) \(weatherValue)"
        case .english:
            let status = weatherOutdoorStatus.isEmpty ? "Normal" : weatherOutdoorStatus
            return "Now \(status) \(weatherValue)"
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
        reloadWeather(force: weatherForecast.isEmpty)
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
        case .configurationError:
            switch language {
            case .korean:
                return "API_BASE_URL 또는 IOS_API_KEY 설정이 필요합니다. Key Vault 동기화를 확인하세요."
            case .english:
                return "API_BASE_URL or IOS_API_KEY is missing. Check Key Vault sync."
            }
        }
    }

    var selectedPlace: PlaceRecommendation? {
        guard let selectedPlaceID else { return nil }
        return places.first(where: { $0.id == selectedPlaceID })
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
        moreInfoEligiblePlaceID == placeID && hiddenMoreInfoPlaceID != placeID
    }

    func playMoreInfo(for place: PlaceRecommendation, language: AppLanguage) {
        guard canPlayMoreInfo(for: place.id) else { return }
        activeLanguage = language
        hiddenMoreInfoPlaceID = place.id
        moreInfoEligiblePlaceID = nil
        subtitle = docentLoadingText(for: language)
        loadDocentScriptAndAudio(for: place, language: language, mode: .detail)
    }

    func presentPlanner(language: AppLanguage) {
        activeLanguage = language
        isPlannerPresented = true
        reloadWeather(force: true)
        if plannerSnapshot == nil {
            refreshPlanner(language: language)
        }
    }

    func regeneratePlanner(language: AppLanguage) {
        isPlannerPresented = true
        plannerSnapshot = nil
        plannerErrorMessage = nil
        reloadWeather(force: true)
        refreshPlanner(language: language, force: true)
    }

    func refreshPlanner(language: AppLanguage, force: Bool = false) {
        activeLanguage = language
        if isPlannerLoading && !force {
            return
        }

        plannerTask?.cancel()
        let center = region.center
        isPlannerLoading = true
        plannerErrorMessage = nil
        plannerTask = Task { [weak self] in
            guard let self else { return }
            defer {
                isPlannerLoading = false
                plannerTask = nil
            }

            do {
                let snapshot = try await plannerDataProvider.fetchDailyPlan(at: center, language: language)
                guard !Task.isCancelled else { return }
                plannerSnapshot = mergedPlannerSnapshot(from: snapshot)
            } catch {
                guard !Task.isCancelled else { return }
                plannerErrorMessage = plannerErrorText(for: language)
            }
        }
    }

    func plannerWeatherBadgeText(for snapshot: PlannerSnapshot) -> String {
        let liveStatus = weatherOutdoorStatus.trimmingCharacters(in: .whitespacesAndNewlines)
        let liveTemp = normalizedLiveWeatherTemperature() ?? ""
        let liveWeather = [liveStatus, liveTemp]
            .filter { !$0.isEmpty }
            .joined(separator: "  ")
        if !liveWeather.isEmpty {
            return liveWeather
        }

        return [snapshot.outdoorStatus, snapshot.temperatureText]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "  ")
    }

    func focusPlannerPlace(_ item: PlannerPlanItem, animated: Bool) {
        guard let coordinate = item.place.coordinate else { return }
        let focused = MKCoordinateRegion(center: coordinate, span: defaultMapSpan)
        let clamped = clampRegion(focused)
        deferMapCameraReload()
        suppressNextRegionDrivenReload = true
        if animated {
            withAnimation(.easeInOut(duration: 0.4)) {
                region = clamped
            }
        } else {
            region = clamped
        }
        selectedPlaceID = nil
        isPlannerPresented = false
    }

    func clearInterventionToast() {
        interventionHideTask?.cancel()
        interventionHideTask = nil
        interventionToastMessage = nil
    }

    func dismissLocationOverlay() {
        isLocationOverlayVisible = false
    }

    private func plannerErrorText(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "일정을 가져오지 못했어요. 다시 시도해주세요."
        case .english:
            return "Unable to load the daily plan. Please try again."
        }
    }

    private func mergedPlannerSnapshot(from snapshot: PlannerSnapshot) -> PlannerSnapshot {
        let liveStatus = weatherOutdoorStatus.trimmingCharacters(in: .whitespacesAndNewlines)
        let liveTemp = normalizedLiveWeatherTemperature()

        let mergedStatus = liveStatus.isEmpty ? snapshot.outdoorStatus : liveStatus
        let mergedTemp = liveTemp ?? snapshot.temperatureText

        return PlannerSnapshot(
            location: snapshot.location,
            outdoorStatus: mergedStatus,
            temperatureText: mergedTemp,
            plan: snapshot.plan
        )
    }

    private func normalizedLiveWeatherTemperature() -> String? {
        let trimmed = weatherValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty || trimmed == WeatherSnapshot.placeholder.temperatureText {
            return nil
        }
        return trimmed
    }

    private func refreshPlannerSnapshotWeatherFromLiveWeather() {
        guard let snapshot = plannerSnapshot else { return }
        plannerSnapshot = mergedPlannerSnapshot(from: snapshot)
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
        isDocentRequestInFlight = true
        narrationTask = Task { [weak self] in
            guard let self else { return }
            defer {
                Task { @MainActor [weak self] in
                    self?.isDocentRequestInFlight = false
                }
            }

            do {
                let response = try await docentDataProvider.fetchDocentScript(
                    placeID: place.id,
                    category: place.categoryKind,
                    language: language,
                    mode: mode
                )
                guard !Task.isCancelled else { return }

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
                    // Keep subtitle text when TTS fails.
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
        isDocentRequestInFlight = false
        audioPlayer?.stop()
        audioPlayer = nil
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

    private func applySelection(
        for place: PlaceRecommendation,
        language: AppLanguage,
        shouldCenterMapOnSelection: Bool
    ) {
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
        if result.shouldCenterMap && shouldCenterMapOnSelection {
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
        next.center.latitude = min(max(next.center.latitude, -85.0), 85.0)
        next.center.longitude = min(max(next.center.longitude, -180.0), 180.0)
        #else
        next.center.latitude = min(max(next.center.latitude, 33.0), 38.8)
        next.center.longitude = min(max(next.center.longitude, 124.0), 132.2)
        #endif

        next.span.latitudeDelta = min(max(next.span.latitudeDelta, 0.002), 8.0)
        next.span.longitudeDelta = min(max(next.span.longitudeDelta, 0.002), 8.0)

        return next
    }

    func updateRegionFromMap(_ candidate: MKCoordinateRegion) {
        let clamped = clampRegion(candidate)
        guard !isNearlyEqual(region, clamped) else { return }

        Task { @MainActor [weak self] in
            guard let self else { return }
            guard !isNearlyEqual(region, clamped) else { return }
            region = clamped

            if suppressNextRegionDrivenReload {
                suppressNextRegionDrivenReload = false
            }
        }
    }

    private func schedulePlacesReloadForMapCenter(_ center: CLLocationCoordinate2D) {
        guard isAppLocationConsentEnabled else { return }
        guard !hasRuntimeConfigurationError else { return }

        mapCenterReloadDebounceTask?.cancel()
        mapCenterReloadDebounceTask = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(nanoseconds: 350_000_000)
            guard !Task.isCancelled else { return }

            lastMapCameraInteractionAt = Date()
            reloadPlaces(force: true, anchorCenter: center)
        }
    }

    func handleMapCameraInteractionEnded(center: CLLocationCoordinate2D) {
        if isMapCameraReloadSuppressed {
            return
        }
        lastMapCameraInteractionAt = Date()
        schedulePlacesReloadForMapCenter(center)
    }

    private func refreshData(forcePlaces: Bool = false, forceWeather: Bool = false) {
        reloadPlaces(force: forcePlaces, anchorCenter: region.center)
        reloadWeather(force: forceWeather)
    }

    private var hasRuntimeConfigurationError: Bool {
        if case .configurationError = mapStatus {
            return true
        }
        return false
    }

    private func reloadPlaces(force: Bool, anchorCenter: CLLocationCoordinate2D) {
        guard isAppLocationConsentEnabled else { return }
        guard !hasRuntimeConfigurationError else { return }

        if !force, let failedAt = lastPlacesFailureAt {
            let elapsed = Date().timeIntervalSince(failedAt)
            if elapsed < placesFailureRetryCooldownSeconds {
                if let failedCenter = lastPlacesFailureCenter,
                   distance(from: failedCenter, to: anchorCenter) >= placesReloadThresholdMeters {
                    // Allow immediate retry when map center moved enough.
                } else {
                    schedulePlacesRetryAfterCooldown(failedAt: failedAt)
                    return
                }
            }
        }

        if isLoadingPlaces && !force {
            return
        }

        let shouldReload = PlacesReloadPolicy.shouldReload(
            force: force,
            hasAnyPlaces: !allPlaces.isEmpty,
            lastFetchCenter: lastPlacesFetchCenter,
            currentCenter: anchorCenter,
            minimumDistanceMeters: placesReloadThresholdMeters
        )
        guard shouldReload else { return }

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
            if mapStatus != .configurationError {
                mapStatus = .none
            }
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
                    center: anchorCenter,
                    radiusMeters: searchRadiusMeters,
                    category: selectedFilter
                )
                guard !Task.isCancelled else { return }
                guard placesReloadToken == token else { return }

                allPlaces = loadedPlaces.places
                lastPlacesFetchCenter = anchorCenter
                lastPlacesFailureAt = nil
                lastPlacesFailureCenter = nil
                applyPlacesAfterFetch()
            } catch {
                guard !Task.isCancelled else { return }
                guard placesReloadToken == token else { return }
                lastPlacesFailureAt = Date()
                lastPlacesFailureCenter = anchorCenter
                if allPlaces.isEmpty {
                    mapStatus = .networkError
                }
            }
        }
    }

    private func applyPlacesAfterFetch() {
        let distanceApplied = placesApplyingUserDistance(from: userCoordinate, source: allPlaces)
        let deduplicated = deduplicatedPlacesByID(distanceApplied)
        allPlaces = deduplicated
        places = deduplicated
        placesRenderID = UUID()

        mapStatus = places.isEmpty ? .noResults : .none

        if let selectedPlaceID,
           !places.contains(where: { $0.id == selectedPlaceID }) {
            self.selectedPlaceID = nil
            hiddenMoreInfoPlaceID = nil
            moreInfoEligiblePlaceID = nil
            subtitle = defaultSubtitle(for: activeLanguage)
            stopNarrationPlayback()
        }

        runAutoDocentIfNeeded(language: activeLanguage, forceAnnounce: false)
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
            reloadPlaces(force: true, anchorCenter: region.center)
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
        guard isAppLocationConsentEnabled else { return }
        guard !hasRuntimeConfigurationError else { return }
        guard let coordinate = userCoordinate else { return }

        if !force, let failedAt = lastWeatherFailureAt {
            let elapsed = Date().timeIntervalSince(failedAt)
            if elapsed < weatherFailureRetryCooldownSeconds {
                if let failedCoordinate = lastWeatherFailureCoordinate,
                   distance(from: failedCoordinate, to: coordinate) >= weatherReloadThresholdMeters {
                    // Allow immediate retry when user moved enough after a failure.
                } else {
                    scheduleWeatherRetryAfterCooldown(failedAt: failedAt)
                    return
                }
            }
        }

        let shouldReload = WeatherReloadPolicy.shouldReload(
            force: force,
            lastFetchCoordinate: lastWeatherFetchCoordinate,
            lastFetchAt: lastWeatherFetchAt,
            currentCoordinate: coordinate,
            maxAgeSeconds: weatherMaxAgeSeconds,
            distanceThresholdMeters: weatherReloadThresholdMeters
        )
        guard shouldReload else { return }

        if force {
            weatherTask?.cancel()
            weatherTask = nil
        } else if weatherTask != nil {
            return
        }

        weatherFailureRetryTask?.cancel()
        weatherFailureRetryTask = nil

        weatherTask = Task { [weak self] in
            guard let self else { return }
            defer {
                weatherTask = nil
            }

            do {
                let weatherResult = try await mapDataProvider.fetchWeather(at: coordinate)
                guard !Task.isCancelled else { return }

                weatherSymbol = weatherResult.symbolName
                weatherValue = weatherResult.temperatureText
                weatherDust = weatherResult.dustText
                weatherOutdoorStatus = weatherResult.outdoorStatus
                weatherForecast = weatherResult.forecast
                refreshPlannerSnapshotWeatherFromLiveWeather()
                lastWeatherFetchCoordinate = coordinate
                lastWeatherFetchAt = Date()
                lastWeatherFailureAt = nil
                lastWeatherFailureCoordinate = nil

                refreshIntervention(for: coordinate)
            } catch {
                guard !Task.isCancelled else { return }
                lastWeatherFailureAt = Date()
                lastWeatherFailureCoordinate = coordinate
                if lastWeatherFetchCoordinate == nil {
                    weatherSymbol = WeatherSnapshot.placeholder.symbolName
                    weatherValue = WeatherSnapshot.placeholder.temperatureText
                    weatherDust = WeatherSnapshot.placeholder.dustText
                    weatherOutdoorStatus = WeatherSnapshot.placeholder.outdoorStatus
                    weatherForecast = []
                }
                scheduleWeatherRetryAfterCooldown(failedAt: lastWeatherFailureAt ?? Date())
            }
        }
    }

    private func refreshIntervention(for coordinate: CLLocationCoordinate2D) {
        Task { [weak self] in
            guard let self else { return }
            do {
                let intervention = try await plannerDataProvider.fetchIntervention(at: coordinate, radiusMeters: 10_000)
                guard !Task.isCancelled else { return }
                guard let intervention else { return }

                let languageCode = activeLanguage.rawValue
                if weatherOutdoorStatus.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                   let fallback = InterventionCopyMapper.outdoorStatusFallback(type: intervention.type, languageCode: languageCode) {
                    weatherOutdoorStatus = fallback
                }

                if let message = InterventionCopyMapper.toastMessage(type: intervention.type, languageCode: languageCode) {
                    showInterventionToast(message: message)
                }
            } catch {
                // Ignore intervention errors to keep weather flow stable.
            }
        }
    }

    private func showInterventionToast(message: String) {
        interventionToastMessage = message
        interventionHideTask?.cancel()
        interventionHideTask = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            guard !Task.isCancelled else { return }
            interventionToastMessage = nil
        }
    }

    private func scheduleWeatherRetryAfterCooldown(failedAt: Date) {
        let elapsed = Date().timeIntervalSince(failedAt)
        let remaining = max(0.2, weatherFailureRetryCooldownSeconds - elapsed)

        weatherFailureRetryTask?.cancel()
        weatherFailureRetryTask = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(nanoseconds: UInt64(remaining * 1_000_000_000))
            guard !Task.isCancelled else { return }
            guard lastWeatherFailureAt != nil else { return }
            reloadWeather(force: true)
        }
    }

    func retryLoadingPlaces() {
        reloadPlaces(force: true, anchorCenter: region.center)
    }

    func configureLocationUpdates(consentEnabled: Bool) {
        isAppLocationConsentEnabled = consentEnabled

        guard consentEnabled else {
            locationManager.stopUpdatingLocation()
            reloadTask?.cancel()
            weatherTask?.cancel()
            placesFailureRetryTask?.cancel()
            weatherFailureRetryTask?.cancel()
            mapCenterReloadDebounceTask?.cancel()
            isLoadingPlaces = false
            isLocationOverlayVisible = false
            suppressMapCameraReloadUntil = nil
            lastMapCameraInteractionAt = nil
            lastUserDrivenPlacesCoordinate = nil
            lastUserDrivenPlacesReloadAt = nil
            return
        }

        applyRuntimeConfigurationStatus()

        let status = locationManager.authorizationStatus
        switch status {
        case .notDetermined:
            locationManager.requestWhenInUseAuthorization()
            bootstrapInitialDataIfNeeded()
        case .authorizedWhenInUse, .authorizedAlways:
            locationManager.startUpdatingLocation()
            bootstrapInitialDataIfNeeded()
        case .denied, .restricted:
            locationManager.stopUpdatingLocation()
            isLocationOverlayVisible = true
        @unknown default:
            locationManager.stopUpdatingLocation()
            isLocationOverlayVisible = true
        }
    }

    private func bootstrapInitialDataIfNeeded() {
        guard !hasBootstrappedInitialData else { return }
        hasBootstrappedInitialData = true

        reloadPlaces(force: true, anchorCenter: region.center)
        pendingInitialLocationBootstrap = true
        locationManager.requestLocation()
    }

    func centerOnUserLocation(animated: Bool = true) {
        pendingForceReloadFromLocationRequest = true
        locationManager.requestLocation()

        guard let coordinate = userCoordinate else {
            return
        }

        let focused = MKCoordinateRegion(center: coordinate, span: defaultMapSpan)
        let clamped = clampRegion(focused)
        deferMapCameraReload()
        suppressNextRegionDrivenReload = true
        if animated {
            withAnimation(.easeInOut(duration: 0.55)) {
                region = clamped
            }
        } else {
            region = clamped
        }
        refreshData(forcePlaces: true, forceWeather: true)
    }

    func centerOnPlace(_ place: PlaceRecommendation, animated: Bool) {
        let focused = MKCoordinateRegion(center: place.coordinate, span: defaultMapSpan)
        let clamped = clampRegion(focused)
        deferMapCameraReload()
        suppressNextRegionDrivenReload = true
        if animated {
            withAnimation(.easeInOut(duration: 0.45)) {
                region = clamped
            }
        } else {
            region = clamped
        }
    }

    func zoomIntoCluster(at coordinate: CLLocationCoordinate2D, animated: Bool = true) {
        let zoomedSpan = MKCoordinateSpan(
            latitudeDelta: max(region.span.latitudeDelta * 0.55, 0.002),
            longitudeDelta: max(region.span.longitudeDelta * 0.55, 0.002)
        )
        let focused = MKCoordinateRegion(center: coordinate, span: zoomedSpan)
        let clamped = clampRegion(focused)
        deferMapCameraReload()
        suppressNextRegionDrivenReload = true
        if animated {
            withAnimation(.easeInOut(duration: 0.32)) {
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
        isLocationOverlayVisible = false

        if !hasAppliedInitialUserFocus {
            hasAppliedInitialUserFocus = true
            let focused = MKCoordinateRegion(center: latest.coordinate, span: defaultMapSpan)
            deferMapCameraReload()
            suppressNextRegionDrivenReload = true
            region = clampRegion(focused)
        }

        refreshDistancesForCurrentLocation(latest.coordinate)

        if pendingInitialLocationBootstrap || pendingForceReloadFromLocationRequest {
            pendingInitialLocationBootstrap = false
            pendingForceReloadFromLocationRequest = false
            lastUserDrivenPlacesCoordinate = latest.coordinate
            lastUserDrivenPlacesReloadAt = Date()
            refreshData(forcePlaces: true, forceWeather: true)
        } else {
            reloadPlacesForUserMovementIfNeeded(latest.coordinate)
            reloadWeather(force: false)
            runAutoDocentIfNeeded(language: activeLanguage, forceAnnounce: false)
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        isLoadingPlaces = false

        if pendingInitialLocationBootstrap || pendingForceReloadFromLocationRequest {
            pendingInitialLocationBootstrap = false
            pendingForceReloadFromLocationRequest = false
            isLocationOverlayVisible = true
            reloadWeather(force: true)
        }
    }

    private func runAutoDocentIfNeeded(language: AppLanguage, forceAnnounce: Bool) {
        guard isAutoDocentEnabled, let userCoordinate, !places.isEmpty else { return }
        guard !isDocentRequestInFlight else { return }

        if !forceAnnounce, let requestedAt = lastAutoDocentRequestedAt {
            let elapsed = Date().timeIntervalSince(requestedAt)
            if elapsed < autoDocentRequestCooldownSeconds {
                return
            }
        }

        guard let nearest = nearestPlace(to: userCoordinate) else { return }
        guard nearest.distance <= autoDocentTriggerRadiusMeters else {
            lastAutoGuidedPlaceID = nil
            return
        }
        guard forceAnnounce || nearest.place.id != lastAutoGuidedPlaceID else { return }

        selectedPlaceID = nearest.place.id
        hiddenMoreInfoPlaceID = nil
        subtitle = docentLoadingText(for: language)
        lastAutoGuidedPlaceID = nearest.place.id
        lastAutoDocentRequestedAt = Date()
        moreInfoEligiblePlaceID = nearest.place.id

        loadDocentScriptAndAudio(for: nearest.place, language: language, mode: .brief)
    }

    private func reloadPlacesForUserMovementIfNeeded(_ coordinate: CLLocationCoordinate2D) {
        guard shouldReloadPlacesForUserMovement(coordinate) else { return }
        lastUserDrivenPlacesCoordinate = coordinate
        lastUserDrivenPlacesReloadAt = Date()
        reloadPlaces(force: true, anchorCenter: coordinate)
    }

    private func shouldReloadPlacesForUserMovement(_ coordinate: CLLocationCoordinate2D) -> Bool {
        if hasRuntimeConfigurationError || !isAppLocationConsentEnabled {
            return false
        }

        if let lastMapCameraInteractionAt {
            let elapsed = Date().timeIntervalSince(lastMapCameraInteractionAt)
            if elapsed < manualMapContextHoldSeconds {
                return false
            }
        }

        let mapUserDistance = distance(from: region.center, to: coordinate)
        if mapUserDistance > mapCenteredOnUserThresholdMeters {
            return false
        }

        if let lastReloadAt = lastUserDrivenPlacesReloadAt {
            let elapsed = Date().timeIntervalSince(lastReloadAt)
            if elapsed < userDrivenPlacesReloadCooldownSeconds {
                return false
            }
        }

        guard let lastUserDrivenPlacesCoordinate else {
            return true
        }
        let moved = distance(from: lastUserDrivenPlacesCoordinate, to: coordinate)
        return moved >= userDrivenPlacesReloadDistanceMeters
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
        let distanceApplied = placesApplyingUserDistance(from: coordinate, source: allPlaces)
        let deduplicated = deduplicatedPlacesByID(distanceApplied)
        allPlaces = deduplicated
        places = deduplicated
    }

    private func deduplicatedPlacesByID(_ source: [PlaceRecommendation]) -> [PlaceRecommendation] {
        var seen = Set<String>()
        var deduplicated: [PlaceRecommendation] = []
        deduplicated.reserveCapacity(source.count)

        for place in source where seen.insert(place.id).inserted {
            deduplicated.append(place)
        }
        return deduplicated
    }

    private func placesApplyingUserDistance(
        from coordinate: CLLocationCoordinate2D?,
        source: [PlaceRecommendation]
    ) -> [PlaceRecommendation] {
        guard let coordinate else {
            // Prevent map-center-based distance from being shown as user distance.
            return source.map { $0.updatingDistanceMeters(nil) }
        }

        // Keep API order (map-center relevance), update only distance label source.
        return source.map { place in
            let nextDistance = Int(distance(from: coordinate, to: place.coordinate).rounded())
            return place.updatingDistanceMeters(nextDistance)
        }
    }

    private var isMapCameraReloadSuppressed: Bool {
        guard let suppressMapCameraReloadUntil else {
            return false
        }

        if Date() < suppressMapCameraReloadUntil {
            return true
        }

        self.suppressMapCameraReloadUntil = nil
        return false
    }

    private func deferMapCameraReload(seconds: TimeInterval = 0.8) {
        suppressMapCameraReloadUntil = Date().addingTimeInterval(seconds)
    }

    private func applyRuntimeConfigurationStatus() {
        guard isAppLocationConsentEnabled else { return }
        if AppRuntime.apiBaseURL == nil || AppRuntime.iosAPIKey == nil {
            mapStatus = .configurationError
        } else if mapStatus == .configurationError {
            mapStatus = .none
        }
    }
}

enum MapStatus: Equatable {
    case none
    case noResults
    case networkError
    case configurationError
}
