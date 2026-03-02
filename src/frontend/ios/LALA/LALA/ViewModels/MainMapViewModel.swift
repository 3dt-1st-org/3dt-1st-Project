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
    @Published var weatherSymbol = "cloud.sun.fill"
    @Published var weatherValue = "13°C"
    @Published var selectedPlaceID: UUID?
    @Published private(set) var userCoordinate: CLLocationCoordinate2D?

    let places: [PlaceRecommendation]
    private let speechSynthesizer = AVSpeechSynthesizer()
    private let locationManager = CLLocationManager()
    private var hasAppliedInitialUserFocus = false
    private var isAppLocationConsentEnabled = false

    private let initialRegion = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 36.35, longitude: 127.9),
        span: MKCoordinateSpan(latitudeDelta: 7.0, longitudeDelta: 8.0)
    )

    override init() {
        region = initialRegion

        places = [
            PlaceRecommendation(
                nameKo: "행주산성",
                nameEn: "Haengjusanseong Fortress",
                categoryKo: "역사 명소",
                categoryEn: "Historic Site",
                districtKo: "고양시",
                districtEn: "Goyang",
                guideKo: "행주산성은 한강 전망과 성곽 산책이 좋은 역사 명소예요. 근처 로컬 식당도 함께 추천해드릴게요.",
                guideEn: "Haengjusanseong offers scenic fortress walks and river views. I can also recommend nearby local restaurants.",
                coordinate: CLLocationCoordinate2D(latitude: 37.6001, longitude: 126.8171)
            ),
            PlaceRecommendation(
                nameKo: "남한산성 전통길",
                nameEn: "Namhansanseong Trail",
                categoryKo: "로컬 트레킹",
                categoryEn: "Local Trekking",
                districtKo: "광주시",
                districtEn: "Gwangju",
                guideKo: "남한산성 전통길은 숲길과 성곽 풍경을 함께 즐기기 좋은 코스입니다. 초행자에게도 부담이 적어요.",
                guideEn: "Namhansanseong Trail is a great local course with forest paths and fortress scenery, suitable even for first-time visitors.",
                coordinate: CLLocationCoordinate2D(latitude: 37.4767, longitude: 127.1830)
            ),
            PlaceRecommendation(
                nameKo: "화성행궁 야간거리",
                nameEn: "Hwaseong Haenggung Night Street",
                categoryKo: "야간 산책",
                categoryEn: "Night Walk",
                districtKo: "수원시",
                districtEn: "Suwon",
                guideKo: "화성행궁 주변은 밤에 조명이 아름다워 산책하기 좋아요. 전통 간식과 골목 맛집도 가까이에 있습니다.",
                guideEn: "The Hwaseong Haenggung area is ideal for night walks with beautiful lighting, plus local snack spots nearby.",
                coordinate: CLLocationCoordinate2D(latitude: 37.2810, longitude: 127.0143)
            ),
            PlaceRecommendation(
                nameKo: "포천 이동갈비 골목",
                nameEn: "Pocheon Galbi Alley",
                categoryKo: "로컬 맛집",
                categoryEn: "Local Eats",
                districtKo: "포천시",
                districtEn: "Pocheon",
                guideKo: "포천 이동갈비 골목은 현지인도 자주 찾는 대표 맛집 거리예요. 대기 시간을 줄일 수 있는 매장도 안내해드릴게요.",
                guideEn: "Pocheon Galbi Alley is a well-known local food street. I can guide you to places with shorter wait times.",
                coordinate: CLLocationCoordinate2D(latitude: 37.8939, longitude: 127.2006)
            )
        ]

        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    func refreshSubtitle(for language: AppLanguage) {
        subtitle = isVoiceGuidanceEnabled
            ? voiceOnSubtitle(for: language)
            : voiceOffSubtitle(for: language)
    }

    func toggleVoiceGuidance(for language: AppLanguage) {
        isVoiceGuidanceEnabled.toggle()
        if !isVoiceGuidanceEnabled, speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }
        refreshSubtitle(for: language)
    }

    func handlePlaceTap(_ place: PlaceRecommendation, language: AppLanguage) {
        if selectedPlaceID == place.id {
            selectedPlaceID = nil
            if speechSynthesizer.isSpeaking {
                speechSynthesizer.stopSpeaking(at: .immediate)
            }
            refreshSubtitle(for: language)
            return
        }

        selectedPlaceID = place.id
        subtitle = place.guide(in: language)

        if isVoiceGuidanceEnabled {
            speak(subtitle, language: language)
        }
    }

    func weatherA11yText(for language: AppLanguage) -> String {
        language == .korean
            ? "현재 날씨 \(weatherValue)"
            : "Current weather \(weatherValue)"
    }

    private func voiceOnSubtitle(for language: AppLanguage) -> String {
        if language == .korean {
            return "음성 안내: 지금 위치 기준 15분 거리의 로컬 맛집과 산책 코스를 안내해드릴게요."
        }

        return "Voice guide: I can guide you to local food spots and walks within 15 minutes."
    }

    private func voiceOffSubtitle(for language: AppLanguage) -> String {
        if language == .korean {
            return "음성 안내가 꺼져 있습니다. 하단 버튼을 눌러 다시 시작하세요."
        }

        return "Voice guidance is off. Tap the bottom button to resume."
    }

    private func speak(_ text: String, language: AppLanguage) {
        if speechSynthesizer.isSpeaking {
            speechSynthesizer.stopSpeaking(at: .immediate)
        }

        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: language == .korean ? "ko-KR" : "en-US")
        utterance.rate = 0.5
        speechSynthesizer.speak(utterance)
    }

    func clampRegion(_ candidate: MKCoordinateRegion) -> MKCoordinateRegion {
        var next = candidate

        // Keep the visible center inside Korea bounds.
        next.center.latitude = min(max(next.center.latitude, 33.0), 38.8)
        next.center.longitude = min(max(next.center.longitude, 124.0), 132.2)

        // Limit zoom-out and zoom-in ranges.
        next.span.latitudeDelta = min(max(next.span.latitudeDelta, 0.08), 8.0)
        next.span.longitudeDelta = min(max(next.span.longitudeDelta, 0.08), 8.0)

        return next
    }

    func updateRegionFromMap(_ candidate: MKCoordinateRegion) {
        let clamped = clampRegion(candidate)
        guard !isNearlyEqual(region, clamped) else { return }
        Task { @MainActor [clamped] in
            self.region = clamped
        }
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
            span: MKCoordinateSpan(latitudeDelta: 0.12, longitudeDelta: 0.12)
        )
        let clamped = clampRegion(focused)
        if animated {
            withAnimation(.easeInOut(duration: 0.55)) {
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
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // Keep UI responsive even if a one-shot location request fails.
    }
}
