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
            Map(
                coordinateRegion: boundedRegionBinding,
                interactionModes: [.pan, .zoom],
                showsUserLocation: true,
                annotationItems: viewModel.places
            ) { place in
                MapAnnotation(coordinate: place.coordinate) {
                    PlacePinView(
                        title: place.name(in: appViewModel.selectedLanguage),
                        categorySymbol: place.categoryKind.symbolName,
                        isSelected: viewModel.selectedPlaceID == place.id
                    )
                    .onTapGesture {
                        viewModel.handleMapPinTap(place, language: appViewModel.selectedLanguage)
                    }
                }
            }
            .mapStyle(.standard(pointsOfInterest: .excludingAll))
            .ignoresSafeArea()

            overlayContent
        }
        .onAppear {
            viewModel.updateLanguage(appViewModel.selectedLanguage)
            viewModel.configureLocationUpdates(consentEnabled: appViewModel.isLocationConsentEnabled)
        }
        .onChange(of: appViewModel.selectedLanguage) { _, newValue in
            viewModel.updateLanguage(newValue)
        }
        .onChange(of: appViewModel.isLocationConsentEnabled) { _, consent in
            viewModel.configureLocationUpdates(consentEnabled: consent)
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
        VStack(spacing: 10) {
            placeFilterChips

            placeCarousel
                .padding(.top, 2)

            HStack {
                settingsButton
                Spacer()
                weatherView
            }
            .padding(.horizontal, 16)

            if viewModel.isLoadingPlaces {
                loadingBadge
            }

            if let status = viewModel.statusMessage(for: appViewModel.selectedLanguage) {
                statusBanner(status)
            }

            Spacer()

            subtitleView
            ZStack {
                voiceToggleButton
                HStack {
                    Spacer()
                    currentLocationButton
                }
                .padding(.horizontal, 16)
            }
            .frame(height: 74)
        }
        .safeAreaPadding(.top, 10)
        .safeAreaPadding(.bottom, 8)
    }

    private var placeFilterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(MapPlaceFilter.allCases) { filter in
                    Button {
                        viewModel.selectFilter(filter)
                    } label: {
                        Text(filter.title(in: appViewModel.selectedLanguage))
                            .font(.system(size: 13 * appViewModel.fontScale, weight: .semibold))
                            .foregroundStyle(
                                viewModel.selectedFilter == filter
                                    ? Color.white
                                    : Color(AppThemeColor.north.rawValue)
                            )
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            .background(
                                Capsule(style: .continuous)
                                    .fill(
                                        viewModel.selectedFilter == filter
                                            ? Color(AppThemeColor.east.rawValue)
                                            : Color.white.opacity(0.93)
                                    )
                            )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 14)
        }
    }

    private var placeCarousel: some View {
        ScrollViewReader { proxy in
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

                                HStack(spacing: 8) {
                                    Text(place.district(in: appViewModel.selectedLanguage))
                                        .font(.system(size: 12 * appViewModel.fontScale, weight: .medium))
                                        .foregroundStyle(.secondary)

                                    if let distance = place.distanceLabel(in: appViewModel.selectedLanguage) {
                                        Text(distance)
                                            .font(.system(size: 12 * appViewModel.fontScale, weight: .semibold))
                                            .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.75))
                                    }
                                }

                                let address = place.address(in: appViewModel.selectedLanguage)
                                if !address.isEmpty {
                                    Text(address)
                                        .font(.system(size: 11 * appViewModel.fontScale, weight: .regular))
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                            }
                            .frame(width: 230, alignment: .leading)
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
                        .id(place.id)
                    }
                }
                .padding(.horizontal, 14)
            }
            .onChange(of: viewModel.selectedPlaceID) { _, selectedID in
                guard let selectedID else { return }
                withAnimation(.easeInOut(duration: 0.35)) {
                    proxy.scrollTo(selectedID, anchor: .center)
                }
            }
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

    private var loadingBadge: some View {
        HStack(spacing: 10) {
            ProgressView()
                .tint(Color(AppThemeColor.east.rawValue))
            Text(appViewModel.selectedLanguage == .korean ? "주변 장소 로딩 중..." : "Loading nearby places...")
                .font(.system(size: 12 * appViewModel.fontScale, weight: .semibold))
                .foregroundStyle(Color(AppThemeColor.north.rawValue))
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            Capsule(style: .continuous)
                .fill(Color.white.opacity(0.94))
        )
    }

    private func statusBanner(_ text: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(Color.orange)

            Text(text)
                .font(.system(size: 12 * appViewModel.fontScale, weight: .medium))
                .foregroundStyle(Color(AppThemeColor.north.rawValue))
                .multilineTextAlignment(.leading)

            Spacer(minLength: 6)

            Button(appViewModel.selectedLanguage == .korean ? "다시시도" : "Retry") {
                viewModel.retryLoadingPlaces()
            }
            .font(.system(size: 12 * appViewModel.fontScale, weight: .bold))
            .foregroundStyle(Color(AppThemeColor.east.rawValue))
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.white.opacity(0.95))
        )
        .padding(.horizontal, 16)
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

    private var currentLocationButton: some View {
        Button {
            viewModel.centerOnUserLocation(animated: true)
        } label: {
            Image(systemName: "location.fill")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 46, height: 46)
                .background(
                    Circle().fill(Color(AppThemeColor.east.rawValue))
                )
        }
        .accessibilityLabel(appViewModel.selectedLanguage == .korean ? "현재 위치로 이동" : "Go to current location")
        .shadow(color: .black.opacity(0.15), radius: 6, y: 3)
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

private struct PlacePinView: View {
    let title: String
    let categorySymbol: String
    let isSelected: Bool

    var body: some View {
        VStack(spacing: 4) {
            Text(title)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(.white)
                .multilineTextAlignment(.center)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .frame(maxWidth: 160)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(Color.black.opacity(0.72))
                )

            ZStack {
                Circle()
                    .fill(Color.white)
                    .frame(width: isSelected ? 34 : 28, height: isSelected ? 34 : 28)
                    .shadow(color: .black.opacity(0.20), radius: 4, y: 2)

                Circle()
                    .fill(
                        isSelected
                            ? Color(AppThemeColor.south.rawValue)
                            : Color(AppThemeColor.north.rawValue).opacity(0.88)
                    )
                    .frame(width: isSelected ? 22 : 18, height: isSelected ? 22 : 18)

                Image(systemName: categorySymbol)
                    .font(.system(size: isSelected ? 11 : 9, weight: .bold))
                    .foregroundStyle(.white)
            }
        }
        .frame(maxWidth: 150)
    }
}
