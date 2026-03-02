//
//  PlaceRecommendation.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import CoreLocation

enum PlaceCategoryKind: String {
    case history
    case trekking
    case nightWalk
    case localEats

    var symbolName: String {
        switch self {
        case .history: return "building.columns.fill"
        case .trekking: return "figure.hiking"
        case .nightWalk: return "moon.stars.fill"
        case .localEats: return "fork.knife"
        }
    }
}

struct PlaceRecommendation: Identifiable {
    let id = UUID()
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

    func name(in language: AppLanguage) -> String {
        language == .korean ? nameKo : nameEn
    }

    func category(in language: AppLanguage) -> String {
        language == .korean ? categoryKo : categoryEn
    }

    func district(in language: AppLanguage) -> String {
        language == .korean ? districtKo : districtEn
    }

    func guide(in language: AppLanguage) -> String {
        language == .korean ? guideKo : guideEn
    }
}
