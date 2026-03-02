//
//  PlaceRecommendation.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import CoreLocation

struct PlaceRecommendation: Identifiable {
    let id = UUID()
    let nameKo: String
    let nameEn: String
    let categoryKo: String
    let categoryEn: String
    let districtKo: String
    let districtEn: String
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
}
