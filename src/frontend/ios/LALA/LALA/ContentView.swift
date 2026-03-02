//
//  ContentView.swift
//  LALA
//
//  Created by 루딘 on 3/2/26.
//

import SwiftUI

struct ContentView: View {
    @StateObject private var appViewModel = AppViewModel()

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
    }
}

#Preview {
    ContentView()
}
