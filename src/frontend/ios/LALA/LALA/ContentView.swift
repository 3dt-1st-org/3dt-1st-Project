//
//  ContentView.swift
//  LALA
//
//  Created by 루딘 on 3/2/26.
//

import SwiftUI

struct ContentView: View {
    @StateObject private var appViewModel = AppViewModel()
    @StateObject private var locationPermissionManager = LocationPermissionManager()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            Group {
                if appViewModel.hasCompletedOnboarding {
                    MainMapView(appViewModel: appViewModel)
                } else {
                    OnboardingView(appViewModel: appViewModel)
                }
            }
        }
        .environment(\.locale, Locale(identifier: appViewModel.selectedLanguage.rawValue))
        .onAppear {
            appViewModel.startConsentFlowIfNeeded()
            locationPermissionManager.refresh()
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                locationPermissionManager.refresh()
                appViewModel.startConsentFlowIfNeeded()
            }
        }
        .sheet(isPresented: $appViewModel.showPrivacyNoticeSheet) {
            PrivacyNoticeSheet(
                language: appViewModel.selectedLanguage,
                fontScale: appViewModel.fontScale,
                onAgree: {
                    appViewModel.acceptPrivacyNotice()
                }
            )
            .interactiveDismissDisabled()
        }
        .sheet(isPresented: $appViewModel.showLocationConsentSheet) {
            LocationConsentSheet(
                language: appViewModel.selectedLanguage,
                fontScale: appViewModel.fontScale,
                onAgree: {
                    appViewModel.acceptLocationConsent()
                    locationPermissionManager.requestWhenInUsePermission()
                }
            )
            .interactiveDismissDisabled()
        }
        .overlay {
            if shouldBlockAppUsage {
                LocationRequiredOverlay(
                    language: appViewModel.selectedLanguage,
                    fontScale: appViewModel.fontScale,
                    openSettings: {
                        locationPermissionManager.openAppSettings()
                    },
                    refresh: {
                        locationPermissionManager.refresh()
                    }
                )
            }
        }
    }

    private var shouldBlockAppUsage: Bool {
        if appViewModel.showPrivacyNoticeSheet || appViewModel.showLocationConsentSheet {
            return false
        }

        if !appViewModel.isLocationConsentEnabled {
            return true
        }

        return locationPermissionManager.requiresSettingsAction
    }
}

#Preview {
    ContentView()
}

private struct PrivacyNoticeSheet: View {
    let language: AppLanguage
    let fontScale: Double
    let onAgree: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(PrivacyNoticeContent.titleKo)
                        .font(.system(size: 20 * fontScale, weight: .bold))
                    Text(PrivacyNoticeContent.summaryKo)
                        .font(.system(size: 15 * fontScale, weight: .medium))
                        .foregroundStyle(.secondary)
                    Text(PrivacyNoticeContent.detailKo)
                        .font(.system(size: 14 * fontScale))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .navigationTitle(language == .korean ? "동의 안내" : "Terms of Agree")
            .navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .bottom) {
                Button(action: onAgree) {
                    Text(language == .korean ? "동의하고 계속하기" : "Agree and Continue")
                        .font(.system(size: 17 * fontScale, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .fill(Color(AppThemeColor.east.rawValue))
                        )
                }
                .padding(14)
                .background(Color(.systemBackground))
            }
        }
    }
}

private struct LocationConsentSheet: View {
    let language: AppLanguage
    let fontScale: Double
    let onAgree: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(language == .korean ? "위치기반 정보 제공 동의" : "Location Consent")
                .font(.system(size: 22 * fontScale, weight: .bold))

            Text(
                language == .korean
                    ? "LALA는 현재 위치를 기반으로 주변 로컬 명소와 맛집을 추천합니다. 동의 후 iOS 위치 권한 허용이 필요합니다."
                    : "LALA uses your current location to recommend nearby local places. iOS location permission is required."
            )
            .font(.system(size: 15 * fontScale))
            .foregroundStyle(.secondary)

            Button(action: onAgree) {
                Text(language == .korean ? "동의하고 위치 권한 요청" : "Agree and Request Location")
                    .font(.system(size: 17 * fontScale, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .fill(Color(AppThemeColor.east.rawValue))
                    )
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(20)
        .background(Color(.systemBackground))
    }
}

private struct LocationRequiredOverlay: View {
    let language: AppLanguage
    let fontScale: Double
    let openSettings: () -> Void
    let refresh: () -> Void

    var body: some View {
        ZStack {
            Color.black.opacity(0.52).ignoresSafeArea()

            VStack(spacing: 14) {
                Text(language == .korean ? "위치 권한이 필요합니다" : "Location Permission Required")
                    .font(.system(size: 20 * fontScale, weight: .bold))
                    .multilineTextAlignment(.center)

                Text(
                    language == .korean
                        ? "iOS 위치 사용이 꺼져 있어 LALA를 실행할 수 없습니다.\n앱 설정에서 위치 권한을 '사용하는 동안'으로 켜주세요."
                        : "LALA cannot run while iOS location access is off.\nPlease enable location permission for this app in Settings."
                )
                .font(.system(size: 14 * fontScale))
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)

                Button(action: openSettings) {
                    Text(language == .korean ? "앱 위치 설정 열기" : "Open App Location Settings")
                        .font(.system(size: 16 * fontScale, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(Color(AppThemeColor.east.rawValue))
                        )
                }

                Button(action: refresh) {
                    Text(language == .korean ? "다시 확인" : "Check Again")
                        .font(.system(size: 15 * fontScale, weight: .semibold))
                }
            }
            .padding(18)
            .frame(maxWidth: 340)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Color(.systemBackground))
            )
            .padding(.horizontal, 24)
        }
    }
}
