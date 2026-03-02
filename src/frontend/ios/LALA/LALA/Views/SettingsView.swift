//
//  SettingsView.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import SwiftUI

struct SettingsView: View {
    @ObservedObject var viewModel: SettingsViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                privacyCard
                locationConsentCard
                languageCard
                fontCard
            }
            .padding(16)
        }
        .background(Color(AppThemeColor.west.rawValue).ignoresSafeArea())
        .navigationTitle(viewModel.title(in: viewModel.selectedLanguage))
        .navigationBarTitleDisplayMode(.inline)
    }

    private var privacyCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(viewModel.privacyTitle(in: viewModel.selectedLanguage))
                .font(.system(size: 17 * viewModel.fontScale, weight: .bold))
            Text(viewModel.privacyBody(in: viewModel.selectedLanguage))
                .font(.system(size: 14 * viewModel.fontScale, weight: .regular))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(cardStyle)
    }

    private var locationConsentCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle(
                viewModel.selectedLanguage == .korean
                    ? "위치기반 정보 제공 동의"
                    : "Location-Based Data Consent",
                isOn: Binding(
                    get: { viewModel.isLocationConsentEnabled },
                    set: { value in
                        viewModel.isLocationConsentEnabled = value
                        viewModel.syncToAppState()
                    }
                )
            )
            .tint(Color(AppThemeColor.east.rawValue))
        }
        .padding(14)
        .background(cardStyle)
    }

    private var languageCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(viewModel.selectedLanguage == .korean ? "언어" : "Language")
                .font(.system(size: 16 * viewModel.fontScale, weight: .semibold))
            Picker(
                "",
                selection: Binding(
                    get: { viewModel.selectedLanguage },
                    set: { value in
                        viewModel.selectedLanguage = value
                        viewModel.syncToAppState()
                    }
                )
            ) {
                ForEach(AppLanguage.allCases) { language in
                    Text(language.label).tag(language)
                }
            }
            .pickerStyle(.segmented)
        }
        .padding(14)
        .background(cardStyle)
    }

    private var fontCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(viewModel.selectedLanguage == .korean ? "글꼴 크기" : "Font Size")
                .font(.system(size: 16 * viewModel.fontScale, weight: .semibold))

            Slider(
                value: Binding(
                    get: { viewModel.fontScale },
                    set: { value in
                        viewModel.fontScale = value
                        viewModel.syncToAppState()
                    }
                ),
                in: 0.85 ... 1.3,
                step: 0.05
            )
            .tint(Color(AppThemeColor.east.rawValue))

            Text("x\(String(format: "%.2f", viewModel.fontScale))")
                .font(.system(size: 13 * viewModel.fontScale, weight: .medium))
                .foregroundStyle(.secondary)
        }
        .padding(14)
        .background(cardStyle)
    }

    private var cardStyle: some ShapeStyle {
        Color.white.opacity(0.96)
    }
}

#Preview {
    NavigationStack {
        SettingsView(viewModel: SettingsViewModel(appViewModel: AppViewModel()))
    }
}
