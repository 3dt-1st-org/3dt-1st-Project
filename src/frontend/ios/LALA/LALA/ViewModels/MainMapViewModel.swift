//
//  MainMapViewModel.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import MapKit

@MainActor
final class MainMapViewModel: ObservableObject {
    @Published var cameraPosition: MapCameraPosition
    @Published var isVoiceGuidanceEnabled = true
    @Published var subtitle = ""
    @Published var weatherSymbol = "cloud.sun.fill"
    @Published var weatherValue = "13°C"

    let mapBounds: MapCameraBounds
    let places: [PlaceRecommendation]

    private let koreaRegion = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 36.35, longitude: 127.9),
        span: MKCoordinateSpan(latitudeDelta: 7.0, longitudeDelta: 8.0)
    )

    init() {
        cameraPosition = .region(koreaRegion)
        mapBounds = MapCameraBounds(
            centerCoordinateBounds: Self.koreaMapRect(),
            minimumDistance: 80_000,
            maximumDistance: 1_500_000
        )

        places = [
            PlaceRecommendation(
                nameKo: "행주산성",
                nameEn: "Haengjusanseong Fortress",
                categoryKo: "역사 명소",
                categoryEn: "Historic Site",
                districtKo: "고양시",
                districtEn: "Goyang",
                coordinate: CLLocationCoordinate2D(latitude: 37.6001, longitude: 126.8171)
            ),
            PlaceRecommendation(
                nameKo: "남한산성 전통길",
                nameEn: "Namhansanseong Trail",
                categoryKo: "로컬 트레킹",
                categoryEn: "Local Trekking",
                districtKo: "광주시",
                districtEn: "Gwangju",
                coordinate: CLLocationCoordinate2D(latitude: 37.4767, longitude: 127.1830)
            ),
            PlaceRecommendation(
                nameKo: "화성행궁 야간거리",
                nameEn: "Hwaseong Haenggung Night Street",
                categoryKo: "야간 산책",
                categoryEn: "Night Walk",
                districtKo: "수원시",
                districtEn: "Suwon",
                coordinate: CLLocationCoordinate2D(latitude: 37.2810, longitude: 127.0143)
            ),
            PlaceRecommendation(
                nameKo: "포천 이동갈비 골목",
                nameEn: "Pocheon Galbi Alley",
                categoryKo: "로컬 맛집",
                categoryEn: "Local Eats",
                districtKo: "포천시",
                districtEn: "Pocheon",
                coordinate: CLLocationCoordinate2D(latitude: 37.8939, longitude: 127.2006)
            )
        ]
    }

    func refreshSubtitle(for language: AppLanguage) {
        subtitle = isVoiceGuidanceEnabled
            ? voiceOnSubtitle(for: language)
            : voiceOffSubtitle(for: language)
    }

    func toggleVoiceGuidance(for language: AppLanguage) {
        isVoiceGuidanceEnabled.toggle()
        refreshSubtitle(for: language)
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

    private static func koreaMapRect() -> MKMapRect {
        let northWest = CLLocationCoordinate2D(latitude: 38.8, longitude: 124.0)
        let southEast = CLLocationCoordinate2D(latitude: 33.0, longitude: 132.2)

        let a = MKMapPoint(northWest)
        let b = MKMapPoint(southEast)

        return MKMapRect(
            x: min(a.x, b.x),
            y: min(a.y, b.y),
            width: abs(a.x - b.x),
            height: abs(a.y - b.y)
        )
    }
}
