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
    case event

    var symbolName: String {
        switch self {
        case .attraction: return "building.columns.fill"
        case .restaurant: return "fork.knife"
        case .event: return "calendar"
        }
    }

    static func fromRemoteCategory(_ value: String) -> PlaceCategoryKind {
        switch value.lowercased() {
        case "restaurant":
            return .restaurant
        case "event":
            return .event
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
    let imageURL: URL?
    private static let koreanCityEnglishMap: [String: String] = [
        "수원시": "Suwon-si",
        "성남시": "Seongnam-si",
        "고양시": "Goyang-si",
        "용인시": "Yongin-si",
        "부천시": "Bucheon-si",
        "안산시": "Ansan-si",
        "안양시": "Anyang-si",
        "남양주시": "Namyangju-si",
        "화성시": "Hwaseong-si",
        "평택시": "Pyeongtaek-si",
        "의정부시": "Uijeongbu-si",
        "시흥시": "Siheung-si",
        "파주시": "Paju-si",
        "김포시": "Gimpo-si",
        "광주시": "Gwangju-si",
        "광명시": "Gwangmyeong-si",
        "군포시": "Gunpo-si",
        "하남시": "Hanam-si",
        "오산시": "Osan-si",
        "이천시": "Icheon-si",
        "안성시": "Anseong-si",
        "의왕시": "Uiwang-si",
        "양주시": "Yangju-si",
        "구리시": "Guri-si",
        "포천시": "Pocheon-si",
        "여주시": "Yeoju-si",
        "동두천시": "Dongducheon-si",
        "과천시": "Gwacheon-si",
        "가평군": "Gapyeong-gun",
        "양평군": "Yangpyeong-gun",
        "연천군": "Yeoncheon-gun"
    ]
    private static let koreanCityKeysByLength: [String] = koreanCityEnglishMap.keys.sorted { lhs, rhs in
        lhs.count > rhs.count
    }

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
        addressEn: String = "",
        imageURL: URL? = nil
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
        self.imageURL = imageURL
    }

    func name(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return nameKo
        case .english:
            return nameEn
        }
    }

    func category(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return categoryKo
        case .english:
            return categoryEn
        }
    }

    func district(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return districtKo
        case .english:
            if let cityFromFullAddress = Self.extractEnglishCity(from: addressEn) {
                return cityFromFullAddress
            }
            if let cityFromDistrictEn = Self.extractEnglishCity(from: districtEn) {
                return cityFromDistrictEn
            }
            if let cityFromKoreanDistrict = Self.extractMappedEnglishCity(fromKoreanText: districtKo) {
                return cityFromKoreanDistrict
            }
            if let cityFromKoreanAddress = Self.extractMappedEnglishCity(fromKoreanText: addressKo) {
                return cityFromKoreanAddress
            }
            return districtEn.isEmpty ? districtKo : districtEn
        }
    }

    func guide(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return guideKo
        case .english:
            return guideEn
        }
    }

    func address(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return addressKo
        case .english:
            return addressEn
        }
    }

    func distanceLabel(in language: AppLanguage) -> String? {
        guard let distanceMeters else { return nil }
        if distanceMeters >= 1_000 {
            let kilometers = Double(distanceMeters) / 1_000.0
            return String(format: "%.1fkm", kilometers)
        }
        return "\(distanceMeters)m"
    }

    func updatingDistanceMeters(_ nextDistanceMeters: Int?) -> PlaceRecommendation {
        PlaceRecommendation(
            id: id,
            nameKo: nameKo,
            nameEn: nameEn,
            categoryKind: categoryKind,
            categoryKo: categoryKo,
            categoryEn: categoryEn,
            districtKo: districtKo,
            districtEn: districtEn,
            guideKo: guideKo,
            guideEn: guideEn,
            coordinate: coordinate,
            distanceMeters: nextDistanceMeters,
            addressKo: addressKo,
            addressEn: addressEn,
            imageURL: imageURL
        )
    }

    private static func extractEnglishCity(from raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            return nil
        }
        let segments = trimmed
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        for segment in segments.reversed() {
            let trimmedSegment = segment.trimmingCharacters(in: CharacterSet(charactersIn: "."))
            let lowercased = trimmedSegment.lowercased()
            if lowercased.hasSuffix("-si") || lowercased.hasSuffix("-gun") {
                return trimmedSegment
            }
        }
        return nil
    }

    private static func extractMappedEnglishCity(fromKoreanText raw: String) -> String? {
        let compact = raw.replacingOccurrences(of: " ", with: "")
        if compact.isEmpty {
            return nil
        }
        for koreanCity in koreanCityKeysByLength {
            if compact.contains(koreanCity), let englishCity = koreanCityEnglishMap[koreanCity] {
                return englishCity
            }
        }
        return nil
    }

}
