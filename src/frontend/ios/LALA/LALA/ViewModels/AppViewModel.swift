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

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults

        hasCompletedOnboarding = defaults.bool(forKey: Keys.hasCompletedOnboarding)
        isLocationConsentEnabled = defaults.object(forKey: Keys.isLocationConsentEnabled) == nil
            ? true
            : defaults.bool(forKey: Keys.isLocationConsentEnabled)

        if let raw = defaults.string(forKey: Keys.selectedLanguage),
           let language = AppLanguage(rawValue: raw) {
            selectedLanguage = language
        } else {
            selectedLanguage = .english
        }

        let savedScale = defaults.double(forKey: Keys.fontScale)
        fontScale = savedScale == 0 ? 1.0 : min(max(savedScale, 0.85), 1.3)
    }

    func completeOnboarding() {
        hasCompletedOnboarding = true
    }
}

private enum Keys {
    static let hasCompletedOnboarding = "hasCompletedOnboarding"
    static let isLocationConsentEnabled = "isLocationConsentEnabled"
    static let selectedLanguage = "selectedLanguage"
    static let fontScale = "fontScale"
}
