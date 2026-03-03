//
//  OnboardingView.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import SwiftUI

struct OnboardingView: View {
    @ObservedObject var appViewModel: AppViewModel
    @StateObject private var viewModel = OnboardingViewModel()

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(AppThemeColor.east.rawValue).opacity(0.35),
                    Color(AppThemeColor.center.rawValue).opacity(0.95),
                    Color(AppThemeColor.south.rawValue).opacity(0.4)
                ],
                startPoint: .topTrailing,
                endPoint: .bottomLeading
            )
            .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 20) {
                Spacer()

                Text(viewModel.title(in: appViewModel.selectedLanguage))
                    .font(.system(size: 40 * appViewModel.fontScale, weight: .heavy))
                    .foregroundStyle(Color(AppThemeColor.north.rawValue))

                Text(viewModel.subtitle(in: appViewModel.selectedLanguage))
                    .font(.system(size: 17 * appViewModel.fontScale, weight: .medium))
                    .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.9))

                VStack(alignment: .leading, spacing: 10) {
                    ForEach(viewModel.bullets(in: appViewModel.selectedLanguage), id: \.self) { item in
                        HStack(alignment: .top, spacing: 10) {
                            Circle()
                                .fill(Color(AppThemeColor.east.rawValue))
                                .frame(width: 8, height: 8)
                                .padding(.top, 7)
                            Text(item)
                                .font(.system(size: 16 * appViewModel.fontScale, weight: .medium))
                                .foregroundStyle(Color(AppThemeColor.north.rawValue))
                        }
                    }
                }
                .padding(18)
                .background(Color.white.opacity(0.85), in: RoundedRectangle(cornerRadius: 18, style: .continuous))

                Button {
                    appViewModel.completeOnboarding()
                } label: {
                    Text(viewModel.ctaTitle(in: appViewModel.selectedLanguage))
                        .font(.system(size: 18 * appViewModel.fontScale, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .fill(Color(AppThemeColor.east.rawValue))
                        )
                }

                Spacer()
            }
            .padding(24)
        }
    }
}

#Preview {
    OnboardingView(appViewModel: AppViewModel())
}
