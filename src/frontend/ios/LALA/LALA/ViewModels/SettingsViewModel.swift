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
        switch language {
        case .korean:
            return "설정"
        case .english:
            return "Settings"
        }
    }

    func privacyTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "개인정보 동의 안내"
        case .english:
            return "Privacy Consent"
        }
    }

    func privacyBody(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "서비스 품질 향상을 위해 최소한의 이용 정보와 위치 기반 추천 정보가 사용됩니다."
        case .english:
            return "We only use minimal usage data and location-based context to improve recommendations."
        }
    }

    func privacyDetail(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return PrivacyNoticeContent.detailKo
        case .english:
            return PrivacyNoticeContent.detailEn
        }
    }

    func viewDetailsText(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "자세히 보기"
        case .english:
            return "View Details"
        }
    }

    func closeText(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "닫기"
        case .english:
            return "Close"
        }
    }

    func locationConsentTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "위치기반 정보 제공 동의"
        case .english:
            return "Location-Based Data Consent"
        }
    }

    func languageTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "언어"
        case .english:
            return "Language"
        }
    }

    func fontSizeTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "글꼴 크기"
        case .english:
            return "Font Size"
        }
    }

    func aboutTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "앱 정보"
        case .english:
            return "About"
        }
    }

    func versionTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "버전"
        case .english:
            return "Version"
        }
    }

    var appVersionText: String {
        if let short = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
           !short.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return short
        }
        if let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String,
           !build.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return build
        }
        return "1.0.0"
    }
}
