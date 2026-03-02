//
//  SettingsViewModel.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import Combine

@MainActor
final class SettingsViewModel: ObservableObject {
    @Published var isLocationConsentEnabled: Bool
    @Published var selectedLanguage: AppLanguage
    @Published var fontScale: Double

    private let appViewModel: AppViewModel

    init(appViewModel: AppViewModel) {
        self.appViewModel = appViewModel
        isLocationConsentEnabled = appViewModel.isLocationConsentEnabled
        selectedLanguage = appViewModel.selectedLanguage
        fontScale = appViewModel.fontScale
    }

    func syncToAppState() {
        appViewModel.isLocationConsentEnabled = isLocationConsentEnabled
        appViewModel.selectedLanguage = selectedLanguage
        appViewModel.fontScale = fontScale
    }

    func title(in language: AppLanguage) -> String {
        language == .korean ? "설정" : "Settings"
    }

    func privacyTitle(in language: AppLanguage) -> String {
        language == .korean ? "개인정보 동의 안내" : "Privacy Consent"
    }

    func privacyBody(in language: AppLanguage) -> String {
        if language == .korean {
            return "서비스 품질 향상을 위해 최소한의 이용 정보와 위치 기반 추천 정보가 사용됩니다."
        }

        return "We only use minimal usage data and location-based context to improve recommendations."
    }

    func privacyDetail(in language: AppLanguage) -> String {
        if language == .korean {
            return PrivacyNoticeContent.detailKo
        }

        return """
Terms of Consent (Summary)

LALA collects only essential data including current location to provide nearby local recommendations.
Data is used for service operation, voice guidance, and quality improvement, and is deleted when no longer needed unless retention is required by law.
You can refuse consent, but key location-based functions will be unavailable.
"""
    }
}
