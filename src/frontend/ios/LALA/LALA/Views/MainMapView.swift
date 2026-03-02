//
//  MainMapView.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import SwiftUI
import MapKit

struct MainMapView: View {
    @ObservedObject var appViewModel: AppViewModel
    @StateObject private var viewModel = MainMapViewModel()
    @State private var showSettings = false

    var body: some View {
        ZStack {
            Map(coordinateRegion: boundedRegionBinding, annotationItems: viewModel.places) { place in
                MapMarker(
                    coordinate: place.coordinate,
                    tint: Color(AppThemeColor.south.rawValue)
                )
            }
            .ignoresSafeArea()

            overlayContent
        }
        .onAppear {
            viewModel.refreshSubtitle(for: appViewModel.selectedLanguage)
        }
        .onChange(of: appViewModel.selectedLanguage) { _, newValue in
            viewModel.refreshSubtitle(for: newValue)
        }
        .navigationBarBackButtonHidden(true)
        .navigationDestination(isPresented: $showSettings) {
            SettingsView(viewModel: SettingsViewModel(appViewModel: appViewModel))
        }
    }

    private var boundedRegionBinding: Binding<MKCoordinateRegion> {
        Binding(
            get: { viewModel.region },
            set: { newValue in
                viewModel.updateRegionFromMap(newValue)
            }
        )
    }

    private var overlayContent: some View {
        VStack(spacing: 12) {
            placeCarousel
                .padding(.top, 4)

            HStack {
                settingsButton
                Spacer()
                weatherView
            }
            .padding(.horizontal, 16)

            Spacer()

            subtitleView
            voiceToggleButton
        }
        .safeAreaPadding(.top, 10)
        .safeAreaPadding(.bottom, 8)
    }

    private var placeCarousel: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                ForEach(viewModel.places) { place in
                    Button {
                        viewModel.handlePlaceTap(place, language: appViewModel.selectedLanguage)
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(place.name(in: appViewModel.selectedLanguage))
                                .font(.system(size: 16 * appViewModel.fontScale, weight: .bold))
                                .foregroundStyle(Color(AppThemeColor.north.rawValue))
                                .lineLimit(1)

                            Text(place.category(in: appViewModel.selectedLanguage))
                                .font(.system(size: 13 * appViewModel.fontScale, weight: .semibold))
                                .foregroundStyle(Color(AppThemeColor.east.rawValue))

                            Text(place.district(in: appViewModel.selectedLanguage))
                                .font(.system(size: 12 * appViewModel.fontScale, weight: .medium))
                                .foregroundStyle(.secondary)
                        }
                        .frame(width: 210, alignment: .leading)
                        .padding(14)
                        .background(
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .fill(Color.white.opacity(0.92))
                        )
                        .overlay {
                            AnimatedObangBorder(cornerRadius: 16, isActive: viewModel.selectedPlaceID == place.id)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 14)
        }
    }

    private var weatherView: some View {
        HStack(spacing: 8) {
            Image(systemName: viewModel.weatherSymbol)
                .symbolRenderingMode(.palette)
                .foregroundStyle(.yellow, .orange)
            Text(viewModel.weatherValue)
                .font(.system(size: 13 * appViewModel.fontScale, weight: .semibold))
                .foregroundStyle(Color(AppThemeColor.north.rawValue))
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.white.opacity(0.92))
        )
        .accessibilityLabel(viewModel.weatherA11yText(for: appViewModel.selectedLanguage))
    }

    private var settingsButton: some View {
        Button {
            showSettings = true
        } label: {
            Image(systemName: "gearshape.fill")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(Color(AppThemeColor.north.rawValue))
                .frame(width: 42, height: 42)
                .background(
                    Circle()
                        .fill(Color.white.opacity(0.93))
                )
        }
        .accessibilityLabel(appViewModel.selectedLanguage == .korean ? "설정" : "Settings")
    }

    private var subtitleView: some View {
        Text(viewModel.subtitle)
            .font(.system(size: 15 * appViewModel.fontScale, weight: .medium))
            .foregroundStyle(Color(AppThemeColor.north.rawValue))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Color.white.opacity(0.92))
            )
            .overlay {
                AnimatedObangBorder(cornerRadius: 16, isActive: viewModel.selectedPlaceID != nil)
            }
            .padding(.horizontal, 14)
    }

    private var voiceToggleButton: some View {
        Button {
            viewModel.toggleVoiceGuidance(for: appViewModel.selectedLanguage)
        } label: {
            ZStack {
                Circle()
                    .fill(
                        viewModel.isVoiceGuidanceEnabled
                            ? Color(AppThemeColor.east.rawValue)
                            : Color(AppThemeColor.north.rawValue).opacity(0.8)
                    )
                    .frame(width: 74, height: 74)

                Image(systemName: viewModel.isVoiceGuidanceEnabled ? "speaker.wave.3.fill" : "speaker.slash.fill")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(.white)
            }
        }
        .accessibilityLabel(
            appViewModel.selectedLanguage == .korean
                ? "음성 안내 토글"
                : "Toggle voice guidance"
        )
    }
}

#Preview {
    NavigationStack {
        MainMapView(appViewModel: AppViewModel())
    }
}

private struct AnimatedObangBorder: View {
    let cornerRadius: CGFloat
    let isActive: Bool
    @State private var phaseStart = Date()

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60.0, paused: !isActive)) { timeline in
            let elapsed = timeline.date.timeIntervalSince(phaseStart)
            let angle = (elapsed * 120.0).truncatingRemainder(dividingBy: 360.0)

            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .strokeBorder(
                    AngularGradient(
                        colors: [
                            Color(AppThemeColor.north.rawValue),
                            Color(AppThemeColor.east.rawValue),
                            Color(AppThemeColor.south.rawValue),
                            Color(AppThemeColor.west.rawValue),
                            Color(AppThemeColor.center.rawValue),
                            Color(AppThemeColor.north.rawValue)
                        ],
                        center: .center,
                        angle: .degrees(angle)
                    ),
                    lineWidth: 3
                )
                .opacity(isActive ? 1 : 0)
                .allowsHitTesting(false)
        }
        .onChange(of: isActive) { _, active in
            if active {
                phaseStart = Date()
            }
        }
    }
}
