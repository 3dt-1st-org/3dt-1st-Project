//
//  AppLanguage.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation

enum AppLanguage: String, CaseIterable, Identifiable {
    case korean = "ko"
    case english = "en"
    case japanese = "ja"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .korean: return "한국어"
        case .english: return "English"
        case .japanese: return "日本語"
        }
    }
}
