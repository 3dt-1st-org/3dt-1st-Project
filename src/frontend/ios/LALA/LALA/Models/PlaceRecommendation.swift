//
//  PlaceRecommendation.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import CoreLocation

enum PlaceCategoryKind: String {
    case attraction
    case restaurant
    case history
    case trekking
    case nightWalk
    case localEats

    var symbolName: String {
        switch self {
        case .attraction: return "building.columns.fill"
        case .restaurant: return "fork.knife"
        case .history: return "building.columns.fill"
        case .trekking: return "figure.hiking"
        case .nightWalk: return "moon.stars.fill"
        case .localEats: return "fork.knife"
        }
    }

    static func fromRemoteCategory(_ value: String) -> PlaceCategoryKind {
        switch value.lowercased() {
        case "restaurant":
            return .restaurant
        case "attraction":
            return .attraction
        default:
            return .attraction
        }
    }
}

struct PlaceRecommendation: Identifiable {
    let id: String
    let nameKo: String
    let nameEn: String
    let categoryKind: PlaceCategoryKind
    let categoryKo: String
    let categoryEn: String
    let districtKo: String
    let districtEn: String
    let guideKo: String
    let guideEn: String
    let coordinate: CLLocationCoordinate2D
    let distanceMeters: Int?
    let addressKo: String
    let addressEn: String

    init(
        id: String = UUID().uuidString,
        nameKo: String,
        nameEn: String,
        categoryKind: PlaceCategoryKind,
        categoryKo: String,
        categoryEn: String,
        districtKo: String,
        districtEn: String,
        guideKo: String,
        guideEn: String,
        coordinate: CLLocationCoordinate2D,
        distanceMeters: Int? = nil,
        addressKo: String = "",
        addressEn: String = ""
    ) {
        self.id = id
        self.nameKo = nameKo
        self.nameEn = nameEn
        self.categoryKind = categoryKind
        self.categoryKo = categoryKo
        self.categoryEn = categoryEn
        self.districtKo = districtKo
        self.districtEn = districtEn
        self.guideKo = guideKo
        self.guideEn = guideEn
        self.coordinate = coordinate
        self.distanceMeters = distanceMeters
        self.addressKo = addressKo
        self.addressEn = addressEn
    }

    func name(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return nameKo
        case .english, .japanese:
            return nameEn
        }
    }

    func category(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return categoryKo
        case .english, .japanese:
            return categoryEn
        }
    }

    func district(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return districtKo
        case .english, .japanese:
            return districtEn
        }
    }

    func guide(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return guideKo
        case .english, .japanese:
            return guideEn
        }
    }

    func address(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return addressKo
        case .english, .japanese:
            return addressEn
        }
    }

    func distanceLabel(in language: AppLanguage) -> String? {
        guard let distanceMeters else { return nil }
        if language == .korean {
            return "\(distanceMeters)m"
        }
        return "\(distanceMeters)m"
    }

    static let fallbackData: [PlaceRecommendation] = [
        PlaceRecommendation(
            nameKo: "행주산성",
            nameEn: "Haengjusanseong Fortress",
            categoryKind: .history,
            categoryKo: "역사 명소",
            categoryEn: "Historic Site",
            districtKo: "고양시",
            districtEn: "Goyang",
            guideKo: "행주산성은 한강 전망과 성곽 산책이 좋은 역사 명소예요. 근처 로컬 식당도 함께 추천해드릴게요.",
            guideEn: "Haengjusanseong offers scenic fortress walks and river views. I can also recommend nearby local restaurants.",
            coordinate: CLLocationCoordinate2D(latitude: 37.6001, longitude: 126.8171),
            addressKo: "경기 고양시 덕양구 행주내동",
            addressEn: "Haengju-dong, Deogyang-gu, Goyang"
        ),
        PlaceRecommendation(
            nameKo: "남한산성 전통길",
            nameEn: "Namhansanseong Trail",
            categoryKind: .trekking,
            categoryKo: "로컬 트레킹",
            categoryEn: "Local Trekking",
            districtKo: "광주시",
            districtEn: "Gwangju",
            guideKo: "남한산성 전통길은 숲길과 성곽 풍경을 함께 즐기기 좋은 코스입니다. 초행자에게도 부담이 적어요.",
            guideEn: "Namhansanseong Trail is a great local course with forest paths and fortress scenery, suitable even for first-time visitors.",
            coordinate: CLLocationCoordinate2D(latitude: 37.4767, longitude: 127.1830),
            addressKo: "경기 광주시 남한산성면 산성리",
            addressEn: "Sanseong-ri, Namhansanseong-myeon, Gwangju"
        ),
        PlaceRecommendation(
            nameKo: "화성행궁 야간거리",
            nameEn: "Hwaseong Haenggung Night Street",
            categoryKind: .nightWalk,
            categoryKo: "야간 산책",
            categoryEn: "Night Walk",
            districtKo: "수원시",
            districtEn: "Suwon",
            guideKo: "화성행궁 주변은 밤에 조명이 아름다워 산책하기 좋아요. 전통 간식과 골목 맛집도 가까이에 있습니다.",
            guideEn: "The Hwaseong Haenggung area is ideal for night walks with beautiful lighting, plus local snack spots nearby.",
            coordinate: CLLocationCoordinate2D(latitude: 37.2810, longitude: 127.0143),
            addressKo: "경기 수원시 팔달구 정조로 825",
            addressEn: "825 Jeongjo-ro, Paldal-gu, Suwon"
        ),
        PlaceRecommendation(
            nameKo: "포천 이동갈비 골목",
            nameEn: "Pocheon Galbi Alley",
            categoryKind: .localEats,
            categoryKo: "로컬 맛집",
            categoryEn: "Local Eats",
            districtKo: "포천시",
            districtEn: "Pocheon",
            guideKo: "포천 이동갈비 골목은 현지인도 자주 찾는 대표 맛집 거리예요. 대기 시간을 줄일 수 있는 매장도 안내해드릴게요.",
            guideEn: "Pocheon Galbi Alley is a well-known local food street. I can guide you to places with shorter wait times.",
            coordinate: CLLocationCoordinate2D(latitude: 37.8939, longitude: 127.2006),
            addressKo: "경기 포천시 이동면 장암리",
            addressEn: "Jangam-ri, Idong-myeon, Pocheon"
        )
    ]
}
