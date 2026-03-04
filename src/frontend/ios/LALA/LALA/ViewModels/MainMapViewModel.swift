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
    @Published var selectedPlaceID: String?
    @Published private(set) var userCoordinate: CLLocationCoordinate2D?
    @Published private(set) var places: [PlaceRecommendation]
    @Published var selectedFilter: MapPlaceFilter = .all
    @Published private(set) var isLoadingPlaces = false
    @Published private(set) var mapStatus: MapStatus = .none
    @Published private(set) var moreInfoEligiblePlaceID: String?

    private let speechSynthesizer = AVSpeechSynthesizer()
    private let locationManager = CLLocationManager()
    private let mapDataProvider: MapDataProviding
    private let searchRadiusMeters = 3_000
    private let autoDocentTriggerRadiusMeters: CLLocationDistance = 100
    private let defaultMapSpan = MKCoordinateSpan(latitudeDelta: 0.01, longitudeDelta: 0.01)
    private var hasAppliedInitialUserFocus = false
    private var isAppLocationConsentEnabled = false
    private var activeLanguage: AppLanguage = .korean
    private var reloadTask: Task<Void, Never>?
    private var lastAutoGuidedPlaceID: String?
    private var hiddenMoreInfoPlaceID: String?

    private let initialRegion = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 36.35, longitude: 127.9),
        span: MKCoordinateSpan(latitudeDelta: 7.0, longitudeDelta: 8.0)
    )

    init(mapDataProvider: MapDataProviding? = nil) {
        self.mapDataProvider = mapDataProvider ?? MapRemoteService()
        region = initialRegion
        places = []
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    func refreshSubtitle(for language: AppLanguage) {
        activeLanguage = language
        subtitle = isVoiceGuidanceEnabled
            ? voiceOnSubtitle(for: language)
            : voiceOffSubtitle(for: language)
    }

    func updateLanguage(_ language: AppLanguage) {
        refreshSubtitle(for: language)
        reloadMapData()
    }

    func toggleVoiceGuidance(for language: AppLanguage) {
        isVoiceGuidanceEnabled.toggle()
        if !isVoiceGuidanceEnabled, speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        refreshSubtitle(for: language)
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
        reloadMapData()
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
        subtitle = place.guide(in: language)
        lastAutoGuidedPlaceID = place.id
        centerOnPlace(place, animated: true)

        if isVoiceGuidanceEnabled {
            moreInfoEligiblePlaceID = place.id
            speak(subtitle, language: language)
        } else {
            if speechSynthesizer.isSpeaking {
                speechSynthesizer.stopSpeaking(at: .immediate)
            }
            moreInfoEligiblePlaceID = nil
        }
    }

    func weatherA11yText(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "현재 날씨 \(weatherValue)"
        case .english:
            return "Current weather \(weatherValue)"
        }
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
        isVoiceGuidanceEnabled &&
            moreInfoEligiblePlaceID == placeID &&
            hiddenMoreInfoPlaceID != placeID
    }

    func playMoreInfo(for place: PlaceRecommendation, language: AppLanguage) {
        guard canPlayMoreInfo(for: place.id) else { return }
        activeLanguage = language
        let narration = buildMoreInfoNarration(for: place, language: language)
        subtitle = narration
        hiddenMoreInfoPlaceID = place.id
        moreInfoEligiblePlaceID = nil
        speak(narration, language: language)
    }

    private func voiceOnSubtitle(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "음성 안내: 지금 위치 기준 15분 거리의 로컬 맛집과 산책 코스를 안내해드릴게요."
        case .english:
            return "Voice guide: I can guide you to local food spots and walks within 15 minutes."
        }
    }

    private func voiceOffSubtitle(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "음성 안내가 꺼져 있습니다. 하단 버튼을 눌러 다시 시작하세요."
        case .english:
            return "Voice guidance is off. Tap the bottom button to resume."
        }
    }

    private func speak(_ text: String, language: AppLanguage) {
        if speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }

        let utterance = AVSpeechUtterance(string: text)
        let voiceCode: String
        switch language {
        case .korean:
            voiceCode = "ko-KR"
        case .english:
            voiceCode = "en-US"
        }
        utterance.voice = AVSpeechSynthesisVoice(language: voiceCode)
        utterance.rate = 0.5
        speechSynthesizer.speak(utterance)
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
            moreInfoEligiblePlaceID = nil
        } else if result.selectedPlaceID != hiddenMoreInfoPlaceID {
            hiddenMoreInfoPlaceID = nil
        }

        if result.shouldStopSpeaking, speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        if result.shouldCenterMap {
            centerOnPlace(place, animated: true)
        }
        if result.shouldSpeak {
            moreInfoEligiblePlaceID = place.id
            speak(result.subtitle, language: language)
        } else if result.selectedPlaceID != place.id {
            moreInfoEligiblePlaceID = nil
        }
        if let selected = result.selectedPlaceID {
            lastAutoGuidedPlaceID = selected
        }
    }

    private func defaultSubtitle(for language: AppLanguage) -> String {
        isVoiceGuidanceEnabled ? voiceOnSubtitle(for: language) : voiceOffSubtitle(for: language)
    }

    func clampRegion(_ candidate: MKCoordinateRegion) -> MKCoordinateRegion {
        var next = candidate

        // Keep the visible center inside Korea bounds.
        next.center.latitude = min(max(next.center.latitude, 33.0), 38.8)
        next.center.longitude = min(max(next.center.longitude, 124.0), 132.2)

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

    private func reloadMapData() {
        guard isAppLocationConsentEnabled else { return }
        let anchor = userCoordinate ?? region.center

        reloadTask?.cancel()
        reloadTask = Task { [weak self] in
            guard let self else { return }
            isLoadingPlaces = true
            mapStatus = .none

            do {
                async let loadedPlaces = mapDataProvider.fetchPlaces(
                    center: anchor,
                    radiusMeters: searchRadiusMeters,
                    category: selectedFilter
                )
                async let weather = mapDataProvider.fetchWeather(at: anchor)

                let (placesResult, weatherResult) = try await (loadedPlaces, weather)
                guard !Task.isCancelled else { return }

                applyPlaces(placesResult)
                weatherSymbol = weatherResult.symbolName
                weatherValue = weatherResult.temperatureText
                isLoadingPlaces = false
            } catch {
                guard !Task.isCancelled else { return }
                isLoadingPlaces = false
                mapStatus = .networkError
            }
        }
    }

    private func applyPlaces(_ loadedPlaces: [PlaceRecommendation]) {
        places = loadedPlaces
        mapStatus = loadedPlaces.isEmpty ? .noResults : .none

        guard let selectedPlaceID else { return }
        if !loadedPlaces.contains(where: { $0.id == selectedPlaceID }) {
            self.selectedPlaceID = nil
            hiddenMoreInfoPlaceID = nil
            moreInfoEligiblePlaceID = nil
            subtitle = defaultSubtitle(for: activeLanguage)
            if speechSynthesizer.isSpeaking {
                speechSynthesizer.stopSpeaking(at: .immediate)
            }
        }

        runAutoDocentIfNeeded(language: activeLanguage, forceAnnounce: false)
    }

    func retryLoadingPlaces() {
        reloadMapData()
    }

    func configureLocationUpdates(consentEnabled: Bool) {
        isAppLocationConsentEnabled = consentEnabled
        guard consentEnabled else {
            locationManager.stopUpdatingLocation()
            return
        }

        let status = locationManager.authorizationStatus
        switch status {
        case .notDetermined:
            locationManager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways:
            locationManager.startUpdatingLocation()
            locationManager.requestLocation()
            reloadMapData()
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
        reloadMapData()
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
            centerOnUserLocation(animated: false)
            return
        }

        reloadMapData()
        runAutoDocentIfNeeded(language: activeLanguage, forceAnnounce: false)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // Keep UI responsive even if a one-shot location request fails.
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
        subtitle = nearest.place.guide(in: language)
        lastAutoGuidedPlaceID = nearest.place.id

        if isVoiceGuidanceEnabled {
            moreInfoEligiblePlaceID = nearest.place.id
            speak(subtitle, language: language)
        } else {
            moreInfoEligiblePlaceID = nil
        }
    }

    private func buildMoreInfoNarration(for place: PlaceRecommendation, language: AppLanguage) -> String {
        let name = place.name(in: language)
        let category = place.category(in: language)
        let district = place.district(in: language)
        let address = place.address(in: language)
        let reason = recommendationReason(for: place, language: language)

        switch language {
        case .korean:
            return "\(name)은(는) \(district) 지역의 \(category) 추천 장소입니다. 주소는 \(address)입니다. \(reason) 방문 전 운영 시간과 현장 상황을 함께 확인해 주세요."
        case .english:
            return "\(name) is a recommended \(category.lowercased()) spot in \(district). The address is \(address). \(reason) Please also check opening hours and local conditions before you visit."
        }
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
}

enum MapStatus {
    case none
    case noResults
    case networkError
}
