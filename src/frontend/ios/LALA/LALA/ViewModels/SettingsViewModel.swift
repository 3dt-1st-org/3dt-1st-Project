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
        case .japanese:
            return "設定"
        }
    }

    func privacyTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "개인정보 동의 안내"
        case .english:
            return "Privacy Consent"
        case .japanese:
            return "個人情報同意案内"
        }
    }

    func privacyBody(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "서비스 품질 향상을 위해 최소한의 이용 정보와 위치 기반 추천 정보가 사용됩니다."
        case .english:
            return "We only use minimal usage data and location-based context to improve recommendations."
        case .japanese:
            return "おすすめ品質向上のため、最小限の利用情報と位置ベース情報を利用します。"
        }
    }

    func privacyDetail(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return PrivacyNoticeContent.detailKo
        case .english:
            return PrivacyNoticeContent.detailEn
        case .japanese:
            return PrivacyNoticeContent.detailJa
        }
    }

    func viewDetailsText(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "자세히 보기"
        case .english:
            return "View Details"
        case .japanese:
            return "詳細を見る"
        }
    }

    func closeText(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "닫기"
        case .english:
            return "Close"
        case .japanese:
            return "閉じる"
        }
    }

    func locationConsentTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "위치기반 정보 제공 동의"
        case .english:
            return "Location-Based Data Consent"
        case .japanese:
            return "位置情報提供への同意"
        }
    }

    func languageTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "언어"
        case .english:
            return "Language"
        case .japanese:
            return "言語"
        }
    }

    func fontSizeTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "글꼴 크기"
        case .english:
            return "Font Size"
        case .japanese:
            return "文字サイズ"
        }
    }
}
