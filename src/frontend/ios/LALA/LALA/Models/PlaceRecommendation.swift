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
            return districtEn
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

}
