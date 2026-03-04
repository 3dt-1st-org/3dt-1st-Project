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
        ZStack {
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

            if appViewModel.shouldShowSplash {
                LaunchSplashView()
                    .transition(.opacity)
                    .zIndex(10)
            }
        }
        .onAppear {
            locationPermissionManager.refresh()
            if appViewModel.shouldShowSplash {
                Task { @MainActor in
                    try? await Task.sleep(nanoseconds: 1_100_000_000)
                    withAnimation(.easeInOut(duration: 0.25)) {
                        appViewModel.finishSplashIfNeeded()
                    }
                    appViewModel.startConsentFlowIfNeeded()
                }
            } else {
                appViewModel.startConsentFlowIfNeeded()
            }
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                locationPermissionManager.refresh()
                if !appViewModel.shouldShowSplash {
                    appViewModel.startConsentFlowIfNeeded()
                }
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

private struct LaunchSplashView: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(AppThemeColor.east.rawValue).opacity(0.26),
                    Color(AppThemeColor.center.rawValue).opacity(0.95)
                ],
                startPoint: .topTrailing,
                endPoint: .bottomLeading
            )
            .ignoresSafeArea()

            VStack(spacing: 16) {
                Image("LaunchLogo")
                    .resizable()
                    .interpolation(.high)
                    .frame(width: 118, height: 118)
                    .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
                    .shadow(color: .black.opacity(0.16), radius: 14, y: 8)

                Text("LALA")
                    .font(.system(size: 24, weight: .heavy))
                    .foregroundStyle(Color(AppThemeColor.north.rawValue))
            }
        }
    }
}

private struct PrivacyNoticeSheet: View {
    let language: AppLanguage
    let fontScale: Double
    let onAgree: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(privacyTitle)
                        .font(.system(size: 20 * fontScale, weight: .bold))
                    Text(privacySummary)
                        .font(.system(size: 15 * fontScale, weight: .medium))
                        .foregroundStyle(.secondary)
                    Text(privacyDetail)
                        .font(.system(size: 14 * fontScale))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .navigationTitle(sheetTitle)
            .navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .bottom) {
                Button(action: onAgree) {
                    Text(agreeButtonTitle)
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

    private var privacyTitle: String {
        switch language {
        case .korean:
            return PrivacyNoticeContent.titleKo
        case .english:
            return PrivacyNoticeContent.titleEn
        case .japanese:
            return PrivacyNoticeContent.titleJa
        }
    }

    private var privacySummary: String {
        switch language {
        case .korean:
            return PrivacyNoticeContent.summaryKo
        case .english:
            return PrivacyNoticeContent.summaryEn
        case .japanese:
            return PrivacyNoticeContent.summaryJa
        }
    }

    private var privacyDetail: String {
        switch language {
        case .korean:
            return PrivacyNoticeContent.detailKo
        case .english:
            return PrivacyNoticeContent.detailEn
        case .japanese:
            return PrivacyNoticeContent.detailJa
        }
    }

    private var sheetTitle: String {
        switch language {
        case .korean:
            return "동의 안내"
        case .english:
            return "Terms of Agree"
        case .japanese:
            return "同意案内"
        }
    }

    private var agreeButtonTitle: String {
        switch language {
        case .korean:
            return "동의하고 계속하기"
        case .english:
            return "Agree and Continue"
        case .japanese:
            return "同意して続行"
        }
    }
}

private struct LocationConsentSheet: View {
    let language: AppLanguage
    let fontScale: Double
    let onAgree: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(consentTitle)
                .font(.system(size: 22 * fontScale, weight: .bold))

            Text(consentBody)
            .font(.system(size: 15 * fontScale))
            .foregroundStyle(.secondary)

            Button(action: onAgree) {
                Text(consentButtonTitle)
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

    private var consentTitle: String {
        switch language {
        case .korean:
            return "위치기반 정보 제공 동의"
        case .english:
            return "Location Consent"
        case .japanese:
            return "位置情報提供への同意"
        }
    }

    private var consentBody: String {
        switch language {
        case .korean:
            return "LALA는 현재 위치를 기반으로 주변 로컬 명소와 맛집을 추천합니다. 동의 후 iOS 위치 권한 허용이 필요합니다."
        case .english:
            return "LALA uses your current location to recommend nearby local places. iOS location permission is required."
        case .japanese:
            return "LALAは現在地を基準に周辺のローカル名所とグルメをおすすめします。同意後にiOS位置権限が必要です。"
        }
    }

    private var consentButtonTitle: String {
        switch language {
        case .korean:
            return "동의하고 위치 권한 요청"
        case .english:
            return "Agree and Request Location"
        case .japanese:
            return "同意して位置権限を要求"
        }
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
                Text(overlayTitle)
                    .font(.system(size: 20 * fontScale, weight: .bold))
                    .multilineTextAlignment(.center)

                Text(overlayBody)
                .font(.system(size: 14 * fontScale))
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)

                Button(action: openSettings) {
                    Text(openSettingsTitle)
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
                    Text(retryTitle)
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

    private var overlayTitle: String {
        switch language {
        case .korean:
            return "위치 권한이 필요합니다"
        case .english:
            return "Location Permission Required"
        case .japanese:
            return "位置情報の権限が必要です"
        }
    }

    private var overlayBody: String {
        switch language {
        case .korean:
            return "iOS 위치 사용이 꺼져 있어 LALA를 실행할 수 없습니다.\n앱 설정에서 위치 권한을 '사용하는 동안'으로 켜주세요."
        case .english:
            return "LALA cannot run while iOS location access is off.\nPlease enable location permission for this app in Settings."
        case .japanese:
            return "iOSの位置情報がオフのためLALAを利用できません。\n設定でこのアプリの位置情報権限を有効にしてください。"
        }
    }

    private var openSettingsTitle: String {
        switch language {
        case .korean:
            return "앱 위치 설정 열기"
        case .english:
            return "Open App Location Settings"
        case .japanese:
            return "アプリの位置設定を開く"
        }
    }

    private var retryTitle: String {
        switch language {
        case .korean:
            return "다시 확인"
        case .english:
            return "Check Again"
        case .japanese:
            return "再確認"
        }
    }
}
