//
//  AppViewModel.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import Combine

@MainActor
final class AppViewModel: ObservableObject {
    @Published var hasAcceptedPrivacyNotice: Bool {
        didSet { defaults.set(hasAcceptedPrivacyNotice, forKey: Keys.hasAcceptedPrivacyNotice) }
    }
    @Published var hasCompletedOnboarding: Bool {
        didSet { defaults.set(hasCompletedOnboarding, forKey: Keys.hasCompletedOnboarding) }
    }
    @Published var isLocationConsentEnabled: Bool {
        didSet { defaults.set(isLocationConsentEnabled, forKey: Keys.isLocationConsentEnabled) }
    }
    @Published var selectedLanguage: AppLanguage {
        didSet { defaults.set(selectedLanguage.rawValue, forKey: Keys.selectedLanguage) }
    }
    @Published var fontScale: Double {
        didSet { defaults.set(fontScale, forKey: Keys.fontScale) }
    }
    @Published var showPrivacyNoticeSheet = false
    @Published var showLocationConsentSheet = false

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults

        hasAcceptedPrivacyNotice = defaults.bool(forKey: Keys.hasAcceptedPrivacyNotice)
        hasCompletedOnboarding = defaults.bool(forKey: Keys.hasCompletedOnboarding)
        isLocationConsentEnabled = defaults.object(forKey: Keys.isLocationConsentEnabled) == nil
            ? false
            : defaults.bool(forKey: Keys.isLocationConsentEnabled)

        if let raw = defaults.string(forKey: Keys.selectedLanguage),
           let language = AppLanguage(rawValue: raw) {
            selectedLanguage = language
        } else {
            selectedLanguage = Self.detectInitialLanguage()
        }

        let savedScale = defaults.double(forKey: Keys.fontScale)
        fontScale = savedScale == 0 ? 1.0 : min(max(savedScale, 0.85), 1.3)
    }

    func completeOnboarding() {
        hasCompletedOnboarding = true
    }

    func startConsentFlowIfNeeded() {
        if !hasAcceptedPrivacyNotice {
            showPrivacyNoticeSheet = true
            showLocationConsentSheet = false
            return
        }

        if !isLocationConsentEnabled {
            showLocationConsentSheet = true
        }
    }

    func acceptPrivacyNotice() {
        hasAcceptedPrivacyNotice = true
        showPrivacyNoticeSheet = false
        if !isLocationConsentEnabled {
            showLocationConsentSheet = true
        }
    }

    func acceptLocationConsent() {
        isLocationConsentEnabled = true
        showLocationConsentSheet = false
    }

    func revokeLocationConsent() {
        isLocationConsentEnabled = false
    }

    private static func detectInitialLanguage() -> AppLanguage {
        guard let preferred = Locale.preferredLanguages.first?.lowercased() else {
            return .english
        }
        return preferred.hasPrefix("ko") ? .korean : .english
    }
}

private enum Keys {
    static let hasAcceptedPrivacyNotice = "hasAcceptedPrivacyNotice"
    static let hasCompletedOnboarding = "hasCompletedOnboarding"
    static let isLocationConsentEnabled = "isLocationConsentEnabled"
    static let selectedLanguage = "selectedLanguage"
    static let fontScale = "fontScale"
}
