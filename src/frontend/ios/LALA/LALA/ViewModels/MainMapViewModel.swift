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
    @Published var subtitle = ""
    @Published var weatherSymbol = WeatherSnapshot.placeholder.symbolName
    @Published var weatherValue = WeatherSnapshot.placeholder.temperatureText
    @Published var selectedPlaceID: String?
    @Published private(set) var userCoordinate: CLLocationCoordinate2D?
    @Published private(set) var places: [PlaceRecommendation]
    @Published var selectedFilter: MapPlaceFilter = .all
    @Published private(set) var isLoadingPlaces = false
    @Published private(set) var mapStatusMessage: String?

    private let speechSynthesizer = AVSpeechSynthesizer()
    private let locationManager = CLLocationManager()
    private let mapDataProvider: MapDataProviding
    private let searchRadiusMeters = 3_000
    private var hasAppliedInitialUserFocus = false
    private var isAppLocationConsentEnabled = false
    private var activeLanguage: AppLanguage = .korean
    private var reloadTask: Task<Void, Never>?
    private var debounceTask: Task<Void, Never>?

    private let initialRegion = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 36.35, longitude: 127.9),
        span: MKCoordinateSpan(latitudeDelta: 7.0, longitudeDelta: 8.0)
    )

    init(mapDataProvider: MapDataProviding? = nil) {
        self.mapDataProvider = mapDataProvider ?? MapRemoteService()
        region = initialRegion
        places = PlaceRecommendation.fallbackData
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
        reloadMapData(around: region.center)
    }

    func toggleVoiceGuidance(for language: AppLanguage) {
        isVoiceGuidanceEnabled.toggle()
        if !isVoiceGuidanceEnabled, speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        refreshSubtitle(for: language)
    }

    func selectFilter(_ filter: MapPlaceFilter) {
        guard selectedFilter != filter else { return }
        selectedFilter = filter
        reloadMapData(around: region.center)
    }

    func handlePlaceTap(_ place: PlaceRecommendation, language: AppLanguage) {
        applySelection(for: place, language: language)
    }

    func handleMapPinTap(_ place: PlaceRecommendation, language: AppLanguage) {
        applySelection(for: place, language: language)
    }

    func weatherA11yText(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "현재 날씨 \(weatherValue)"
        case .english:
            return "Current weather \(weatherValue)"
        case .japanese:
            return "現在の天気 \(weatherValue)"
        }
    }

    func statusMessage(for language: AppLanguage) -> String? {
        mapStatusMessage.flatMap { _ in
            if places.isEmpty {
                switch language {
                case .korean:
                    return "주변 추천 장소가 없습니다."
                case .english:
                    return "No recommended places found nearby."
                case .japanese:
                    return "周辺におすすめスポットが見つかりません。"
                }
            }

            switch language {
            case .korean:
                return "네트워크 문제로 임시 추천 목록을 표시 중입니다."
            case .english:
                return "Showing fallback recommendations due to a network issue."
            case .japanese:
                return "ネットワークの問題により、代替おすすめを表示しています。"
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
        case .japanese:
            return "おすすめ理由"
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
        case .japanese:
            if distance.isEmpty {
                return "\(district)で人気の\(category)スポットです。\(address)"
            }
            return "現在地から約\(distance)の\(category)おすすめスポットです。\(address)"
        }
    }

    private func voiceOnSubtitle(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "음성 안내: 지금 위치 기준 15분 거리의 로컬 맛집과 산책 코스를 안내해드릴게요."
        case .english:
            return "Voice guide: I can guide you to local food spots and walks within 15 minutes."
        case .japanese:
            return "音声ガイド: 現在地から15分圏内のローカル名所とグルメを案内します。"
        }
    }

    private func voiceOffSubtitle(for language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "음성 안내가 꺼져 있습니다. 하단 버튼을 눌러 다시 시작하세요."
        case .english:
            return "Voice guidance is off. Tap the bottom button to resume."
        case .japanese:
            return "音声ガイドはオフです。下のボタンを押して再開してください。"
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
        case .japanese:
            voiceCode = "ja-JP"
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

        if result.shouldStopSpeaking, speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        if result.shouldCenterMap {
            centerOnPlace(place, animated: true)
        }
        if result.shouldSpeak {
            speak(result.subtitle, language: language)
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
        Task { @MainActor [clamped] in
            self.region = clamped
            self.scheduleDebouncedReload(center: clamped.center)
        }
    }

    private func scheduleDebouncedReload(center: CLLocationCoordinate2D) {
        guard isAppLocationConsentEnabled else { return }

        debounceTask?.cancel()
        debounceTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 550_000_000)
            guard !Task.isCancelled else { return }
            self?.reloadMapData(around: center)
        }
    }

    private func reloadMapData(around center: CLLocationCoordinate2D) {
        guard isAppLocationConsentEnabled else { return }

        reloadTask?.cancel()
        reloadTask = Task { [weak self] in
            guard let self else { return }
            isLoadingPlaces = true
            mapStatusMessage = nil

            do {
                async let loadedPlaces = mapDataProvider.fetchPlaces(
                    center: center,
                    radiusMeters: searchRadiusMeters,
                    category: selectedFilter
                )
                async let weather = mapDataProvider.fetchWeather(at: center)

                let (placesResult, weatherResult) = try await (loadedPlaces, weather)
                guard !Task.isCancelled else { return }

                applyPlaces(placesResult)
                weatherSymbol = weatherResult.symbolName
                weatherValue = weatherResult.temperatureText
                isLoadingPlaces = false
            } catch {
                guard !Task.isCancelled else { return }
                isLoadingPlaces = false
                mapStatusMessage = error.localizedDescription

                // Keep existing places when available. If empty, show static fallback.
                if places.isEmpty {
                    places = PlaceRecommendation.fallbackData
                }
            }
        }
    }

    private func applyPlaces(_ loadedPlaces: [PlaceRecommendation]) {
        places = loadedPlaces
        mapStatusMessage = loadedPlaces.isEmpty ? "NO_RESULTS" : nil

        guard let selectedPlaceID else { return }
        if !loadedPlaces.contains(where: { $0.id == selectedPlaceID }) {
            self.selectedPlaceID = nil
            subtitle = defaultSubtitle(for: activeLanguage)
            if speechSynthesizer.isSpeaking {
                speechSynthesizer.stopSpeaking(at: .immediate)
            }
        }
    }

    func retryLoadingPlaces() {
        reloadMapData(around: region.center)
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
            reloadMapData(around: userCoordinate ?? region.center)
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
            span: MKCoordinateSpan(latitudeDelta: 0.002, longitudeDelta: 0.002)
        )
        let clamped = clampRegion(focused)
        if animated {
            withAnimation(.easeInOut(duration: 0.55)) {
                region = clamped
            }
        } else {
            region = clamped
        }
        reloadMapData(around: clamped.center)
    }

    func centerOnPlace(_ place: PlaceRecommendation, animated: Bool) {
        let focused = MKCoordinateRegion(
            center: place.coordinate,
            span: MKCoordinateSpan(latitudeDelta: 0.01, longitudeDelta: 0.01)
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

        if places.isEmpty {
            reloadMapData(around: latest.coordinate)
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // Keep UI responsive even if a one-shot location request fails.
    }
}
