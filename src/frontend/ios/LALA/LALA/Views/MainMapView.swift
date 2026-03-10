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
    @Environment(\.scenePhase) private var scenePhase
    @State private var showSettings = false
    @State private var selectedDetailPlace: PlaceRecommendation?
    @State private var selectedPlaceDetailDetent: PresentationDetent = .medium
    @State private var showPlannerRegenerateConfirm = false
    @State private var renderedMapAnnotationItems: [MapAnnotationDisplayItem] = []
    @State private var mapAnnotationCacheKey: MapAnnotationCacheKey?

    var body: some View {
        ZStack {
            Map(
                coordinateRegion: boundedRegionBinding,
                interactionModes: [.pan, .zoom],
                showsUserLocation: true,
                annotationItems: renderedMapAnnotationItems
            ) { item in
                MapAnnotation(coordinate: item.coordinate) {
                    switch item.kind {
                    case let .place(place):
                        PlacePinView(
                            title: place.name(in: appViewModel.selectedLanguage),
                            categorySymbol: place.categoryKind.symbolName,
                            categoryKind: place.categoryKind,
                            isSelected: viewModel.selectedPlaceID == place.id,
                            showTitle: viewModel.selectedPlaceID == place.id
                        )
                        .onTapGesture {
                            viewModel.handleMapPinTap(place, language: appViewModel.selectedLanguage)
                            selectedDetailPlace = place
                        }
                    case let .cluster(count, categoryKind):
                        ClusterPinView(
                            count: count,
                            categoryKind: categoryKind
                        )
                        .onTapGesture {
                            viewModel.zoomIntoCluster(at: item.coordinate)
                            rebuildMapAnnotationItems(
                                span: viewModel.region.span,
                                center: viewModel.region.center,
                                force: true
                            )
                        }
                    }
                }
            }
            .mapStyle(.standard(pointsOfInterest: .excludingAll))
            .onMapCameraChange(frequency: .onEnd) { context in
                rebuildMapAnnotationItems(
                    span: context.region.span,
                    center: context.region.center
                )
                viewModel.handleMapCameraInteractionEnded(center: context.region.center)
            }
            .ignoresSafeArea()

            overlayContent
        }
        .onAppear {
            viewModel.updateLanguage(appViewModel.selectedLanguage)
            viewModel.configureLocationUpdates(consentEnabled: appViewModel.isLocationConsentEnabled)
            rebuildMapAnnotationItems(
                span: viewModel.region.span,
                center: viewModel.region.center,
                force: true
            )
        }
        .onChange(of: appViewModel.selectedLanguage) { _, newValue in
            viewModel.updateLanguage(newValue)
        }
        .onChange(of: appViewModel.isLocationConsentEnabled) { _, consent in
            viewModel.configureLocationUpdates(consentEnabled: consent)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                viewModel.handleAppDidBecomeActive()
            }
        }
        .onChange(of: viewModel.placesRenderID) { _, _ in
            rebuildMapAnnotationItems(
                span: viewModel.region.span,
                center: viewModel.region.center,
                force: true
            )
        }
        .onChange(of: viewModel.selectedPlaceID) { _, _ in
            rebuildMapAnnotationItems(
                span: viewModel.region.span,
                center: viewModel.region.center
            )
        }
        .onChange(of: viewModel.region.span.latitudeDelta) { _, _ in
            rebuildMapAnnotationItems(
                span: viewModel.region.span,
                center: viewModel.region.center
            )
        }
        .onChange(of: viewModel.region.span.longitudeDelta) { _, _ in
            rebuildMapAnnotationItems(
                span: viewModel.region.span,
                center: viewModel.region.center
            )
        }
        .navigationBarBackButtonHidden(true)
        .navigationDestination(isPresented: $showSettings) {
            SettingsView(viewModel: SettingsViewModel(appViewModel: appViewModel))
        }
        .sheet(item: $selectedDetailPlace) { place in
            PlaceDetailBottomSheet(
                place: place,
                language: appViewModel.selectedLanguage,
                fontScale: appViewModel.fontScale,
                recommendationText: viewModel.recommendationReason(for: place, language: appViewModel.selectedLanguage),
                moreInfoButtonTitle: viewModel.moreInfoButtonTitle(for: appViewModel.selectedLanguage),
                showMoreInfoButton: viewModel.canPlayMoreInfo(for: place.id),
                onPlayMoreInfo: {
                    viewModel.playMoreInfo(for: place, language: appViewModel.selectedLanguage)
                }
            )
            .onAppear {
                selectedPlaceDetailDetent = .medium
            }
            .presentationDetents([.medium, .large], selection: $selectedPlaceDetailDetent)
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $viewModel.isWeatherDetailPresented) {
            weatherForecastSheet
                .presentationDetents([.height(weatherSheetHeight)])
                .presentationDragIndicator(.visible)
                .presentationBackground(.clear)
        }
        .sheet(isPresented: $viewModel.isPlannerPresented) {
            plannerSheet
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .alert(plannerRegenerateTitle, isPresented: $showPlannerRegenerateConfirm) {
            Button(cancelText, role: .cancel) {}
            Button(regenerateText, role: .destructive) {
                viewModel.regeneratePlanner(language: appViewModel.selectedLanguage)
            }
        } message: {
            Text(plannerRegenerateBody)
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

    private func rebuildMapAnnotationItems(
        span: MKCoordinateSpan,
        center: CLLocationCoordinate2D? = nil,
        force: Bool = false
    ) {
        let targetCenter = center ?? viewModel.region.center
        let visiblePlaces = placesForMapAnnotations(
            places: viewModel.places,
            selectedPlaceID: viewModel.selectedPlaceID,
            center: targetCenter,
            span: span
        )
        let forceCluster = visiblePlaces.count > MapAnnotationRenderingPolicy.maximumIndividualPins &&
            span.latitudeDelta >= MapAnnotationRenderingPolicy.forceClusterMinimumLatitudeDelta
        let clusteringEnabled = forceCluster || MapMarkerClusteringPolicy.shouldUseCluster(
            pointCount: visiblePlaces.count,
            latitudeDelta: span.latitudeDelta
        )
        let nextKey = MapAnnotationCacheKey(
            placesRenderID: viewModel.placesRenderID,
            selectedPlaceID: viewModel.selectedPlaceID,
            spanBucket: MapAnnotationSpanBucket(span: span),
            viewportBucket: MapAnnotationViewportBucket(center: targetCenter, span: span),
            isClusteringEnabled: clusteringEnabled,
            isForceClusterEnabled: forceCluster
        )
        guard force || mapAnnotationCacheKey != nextKey else { return }
        mapAnnotationCacheKey = nextKey
        renderedMapAnnotationItems = makeMapAnnotationItems(
            places: visiblePlaces,
            selectedPlaceID: viewModel.selectedPlaceID,
            span: span,
            forceCluster: forceCluster
        )
    }

    private func makeMapAnnotationItems(
        places: [PlaceRecommendation],
        selectedPlaceID: String?,
        span: MKCoordinateSpan,
        forceCluster: Bool
    ) -> [MapAnnotationDisplayItem] {
        let markerPoints = places.map { place in
            MapMarkerPoint(
                id: place.id,
                latitude: place.coordinate.latitude,
                longitude: place.coordinate.longitude,
                categoryKey: place.categoryKind.rawValue
            )
        }
        let presentations = MapMarkerClusteringPolicy.buildPresentations(
            points: markerPoints,
            latitudeDelta: span.latitudeDelta,
            longitudeDelta: span.longitudeDelta,
            selectedPointID: selectedPlaceID,
            activationLatitudeDelta: forceCluster ? 0.0 : MapMarkerClusteringPolicy.defaultActivationLatitudeDelta,
            minimumPointCount: forceCluster ? 2 : MapMarkerClusteringPolicy.defaultMinimumPointCount,
            gridDivisions: forceCluster
                ? MapAnnotationRenderingPolicy.forceClusterGridDivisions
                : MapMarkerClusteringPolicy.defaultGridDivisions
        )
        let placeByID = Dictionary(
            places.map { ($0.id, $0) },
            uniquingKeysWith: { first, _ in first }
        )

        return presentations.compactMap { item in
            switch item {
            case let .place(point):
                guard let place = placeByID[point.id] else { return nil }
                return MapAnnotationDisplayItem(
                    id: "place-\(place.id)",
                    coordinate: place.coordinate,
                    kind: .place(place)
                )
            case let .cluster(cluster):
                return MapAnnotationDisplayItem(
                    id: cluster.id,
                    coordinate: CLLocationCoordinate2D(
                        latitude: cluster.latitude,
                        longitude: cluster.longitude
                    ),
                    kind: .cluster(
                        count: cluster.count,
                        categoryKind: PlaceCategoryKind.fromRemoteCategory(cluster.categoryKey)
                    )
                )
            }
        }
    }

    private func placesForMapAnnotations(
        places: [PlaceRecommendation],
        selectedPlaceID: String?,
        center: CLLocationCoordinate2D,
        span: MKCoordinateSpan
    ) -> [PlaceRecommendation] {
        let latitudeLimit = max(
            span.latitudeDelta * MapAnnotationRenderingPolicy.visiblePaddingMultiplier,
            MapAnnotationRenderingPolicy.minimumVisibleDelta
        )
        let longitudeLimit = max(
            span.longitudeDelta * MapAnnotationRenderingPolicy.visiblePaddingMultiplier,
            MapAnnotationRenderingPolicy.minimumVisibleDelta
        )

        var visiblePlaces = places.filter { place in
            abs(place.coordinate.latitude - center.latitude) <= latitudeLimit &&
                abs(place.coordinate.longitude - center.longitude) <= longitudeLimit
        }

        if let selectedPlaceID,
           let selectedPlace = places.first(where: { $0.id == selectedPlaceID }),
           !visiblePlaces.contains(where: { $0.id == selectedPlaceID }) {
            visiblePlaces.append(selectedPlace)
        }

        return visiblePlaces
    }

    private var overlayContent: some View {
        VStack(spacing: 10) {
            placeFilterChips

            placeCarousel
                .padding(.top, 2)

            HStack {
                plannerButton
                Spacer()
                settingsButton
                weatherView
            }
            .padding(.horizontal, 16)

            if viewModel.isLoadingPlaces {
                loadingBadge
            }

            if let status = viewModel.statusMessage(for: appViewModel.selectedLanguage) {
                statusBanner(status)
            }

            if let toast = viewModel.interventionToastMessage {
                interventionToast(message: toast)
            }

            Spacer()

            subtitleView
            ZStack {
                autoDocentModeButton
                HStack {
                    muteToggleButton
                    Spacer()
                    currentLocationButton
                }
                .padding(.horizontal, 16)
            }
            .frame(height: 74)
        }
        .overlay(alignment: .center) {
            if viewModel.isLocationOverlayVisible {
                locationOverlay
            }
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
                                    ? chipSelectedTextColor(for: filter)
                                    : Color(AppThemeColor.north.rawValue)
                            )
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            .background(
                                Capsule(style: .continuous)
                                    .fill(
                                        viewModel.selectedFilter == filter
                                            ? chipSelectedBackgroundColor(for: filter)
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
                            selectedDetailPlace = place
                        } label: {
                            HStack(alignment: .center, spacing: 10) {
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(place.name(in: appViewModel.selectedLanguage))
                                        .font(.system(size: 15 * appViewModel.fontScale, weight: .bold))
                                        .foregroundStyle(Color(AppThemeColor.north.rawValue))
                                        .lineLimit(2)
                                        .minimumScaleFactor(0.85)

                                    HStack(spacing: 6) {
                                        Text(place.category(in: appViewModel.selectedLanguage))
                                            .font(.system(size: 12 * appViewModel.fontScale, weight: .semibold))
                                            .foregroundStyle(categoryTextColor(for: place.categoryKind))
                                            .lineLimit(1)

                                        if place.categoryKind == .event {
                                            Text(eventStatusText(for: place))
                                                .font(.system(size: 11 * appViewModel.fontScale, weight: .bold))
                                                .foregroundStyle(place.isOngoing == false ? .gray : Color(AppThemeColor.east.rawValue))
                                                .lineLimit(1)
                                        }
                                    }

                                    HStack(spacing: 6) {
                                        Text(place.district(in: appViewModel.selectedLanguage))
                                            .font(.system(size: 11 * appViewModel.fontScale, weight: .medium))
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)

                                        if let distance = place.distanceLabel(in: appViewModel.selectedLanguage) {
                                            Text(distance)
                                                .font(.system(size: 11 * appViewModel.fontScale, weight: .semibold))
                                                .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.7))
                                                .lineLimit(1)
                                        }
                                    }
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)

                                PlaceCardImageView(
                                    imageURL: place.imageURL,
                                    sideLength: 86
                                )
                            }
                            .frame(width: 252, alignment: .leading)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
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
            .id(viewModel.placesRenderID)
            .onChange(of: viewModel.selectedPlaceID) { _, selectedID in
                guard let selectedID else { return }
                withAnimation(.easeInOut(duration: 0.35)) {
                    proxy.scrollTo(selectedID, anchor: .center)
                }
            }
        }
    }

    private var weatherView: some View {
        Button {
            viewModel.presentWeatherDetail()
        } label: {
            HStack(spacing: 8) {
                Image(systemName: viewModel.weatherSymbol)
                    .foregroundStyle(weatherIconColor(for: viewModel.weatherSymbol))
                Text(weatherPillText)
                    .font(.system(size: 13 * appViewModel.fontScale, weight: .semibold))
                    .foregroundStyle(Color(AppThemeColor.north.rawValue))
                    .lineLimit(1)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Color.white.opacity(0.92))
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(viewModel.weatherA11yText(for: appViewModel.selectedLanguage))
    }

    private var weatherForecastSheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(viewModel.weatherDetailTitle(for: appViewModel.selectedLanguage))
                .font(.system(size: 20 * appViewModel.fontScale, weight: .bold))
                .foregroundStyle(Color(AppThemeColor.north.rawValue))
            Text(viewModel.weatherDetailSubtitle(for: appViewModel.selectedLanguage))
                .font(.system(size: 13 * appViewModel.fontScale, weight: .medium))
                .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.78))

            if viewModel.weatherForecast.isEmpty {
                Text(viewModel.weatherForecastEmptyText(for: appViewModel.selectedLanguage))
                    .font(.system(size: 13 * appViewModel.fontScale, weight: .medium))
                    .foregroundStyle(.secondary)
                    .padding(.top, 6)
            } else {
                weatherForecastChartCard(items: viewModel.weatherForecast)
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 20)
        .padding(.bottom, 16)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    private var weatherSheetHeight: CGFloat {
        let baseHeight: CGFloat = 336
        let scaled = baseHeight + ((appViewModel.fontScale - 1.0) * 42)
        return min(max(scaled, 318), 390)
    }

    private func weatherForecastChartCard(items: [WeatherForecastItem]) -> some View {
        let columnWidth: CGFloat = 56
        let chartHeight: CGFloat = 88
        let chartPoints = weatherForecastChartPoints(
            items: items,
            columnWidth: columnWidth,
            chartHeight: chartHeight
        )
        let totalWidth = max(CGFloat(items.count) * columnWidth, 1)

        return ScrollView(.horizontal, showsIndicators: false) {
            VStack(spacing: 0) {
                ZStack(alignment: .topLeading) {
                    weatherForecastLinePath(points: chartPoints)
                        .stroke(
                            Color(red: 0.78, green: 0.79, blue: 0.82),
                            style: StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round)
                        )
                        .frame(width: totalWidth, height: chartHeight)

                    ForEach(chartPoints) { point in
                        Circle()
                            .fill(Color(red: 0.62, green: 0.65, blue: 0.70))
                            .frame(width: 7, height: 7)
                            .position(x: point.x, y: point.y)

                        Text(point.label)
                            .font(.system(size: 11 * appViewModel.fontScale, weight: .bold))
                            .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.88))
                            .position(x: point.x, y: point.y - 12)
                    }
                }
                .frame(width: totalWidth, height: chartHeight)

                HStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                        Text(weatherChartIconText(for: item.symbolName))
                            .font(.system(size: 21))
                            .frame(width: columnWidth, height: 28)
                    }
                }
                .frame(width: totalWidth, alignment: .leading)

                HStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                        Text(weatherChartTimeLabel(item.timeText))
                            .font(.system(size: 11 * appViewModel.fontScale, weight: .medium))
                            .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.45))
                            .frame(width: columnWidth, height: 18)
                    }
                }
                .frame(width: totalWidth, alignment: .leading)
            }
            .frame(width: totalWidth, alignment: .leading)
            .padding(.vertical, 6)
        }
        .scrollIndicators(.hidden)
        .padding(.horizontal, 2)
        .padding(.vertical, 2)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color.white.opacity(0.96))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.black.opacity(0.04), lineWidth: 1)
        )
    }

    private func weatherForecastChartPoints(
        items: [WeatherForecastItem],
        columnWidth: CGFloat,
        chartHeight: CGFloat
    ) -> [WeatherForecastChartPoint] {
        let padTop: CGFloat = 26
        let padBottom: CGFloat = 18
        let drawHeight = max(1, chartHeight - padTop - padBottom)

        let parsedTemps = items.map { weatherTemperatureValue($0.temperatureText) }
        let validTemps = parsedTemps.compactMap { $0 }
        let maxTemp = validTemps.max() ?? 1
        let minTemp = validTemps.min() ?? 0
        let range = max(0.1, maxTemp - minTemp)

        return parsedTemps.enumerated().map { index, temp in
            let x = CGFloat(index) * columnWidth + (columnWidth / 2)
            let y: CGFloat
            if let temp {
                let ratio = CGFloat((maxTemp - temp) / range)
                y = padTop + (ratio * drawHeight)
            } else {
                y = padTop + (drawHeight / 2)
            }

            let label = temp.map { "\(Int($0.rounded()))°" } ?? "--"
            return WeatherForecastChartPoint(id: index, x: x, y: y, label: label)
        }
    }

    private func weatherForecastLinePath(points: [WeatherForecastChartPoint]) -> Path {
        var path = Path()
        guard let first = points.first else { return path }
        path.move(to: CGPoint(x: first.x, y: first.y))

        guard points.count > 1 else { return path }
        for index in 1..<points.count {
            let previous = points[index - 1]
            let current = points[index]
            let midX = (previous.x + current.x) / 2
            path.addCurve(
                to: CGPoint(x: current.x, y: current.y),
                control1: CGPoint(x: midX, y: previous.y),
                control2: CGPoint(x: midX, y: current.y)
            )
        }
        return path
    }

    private func weatherChartIconText(for symbolName: String) -> String {
        switch symbolName {
        case "sun.max.fill":
            return "☀️"
        case "cloud.sun.fill":
            return "⛅"
        case "cloud.fill":
            return "☁️"
        case "cloud.fog.fill":
            return "🌫️"
        case "cloud.rain.fill":
            return "🌧️"
        case "cloud.sleet.fill":
            return "🌨️"
        case "snowflake":
            return "❄️"
        case "cloud.sun.rain.fill":
            return "🌦️"
        case "cloud.bolt.rain.fill":
            return "⛈️"
        default:
            return "⛅"
        }
    }

    private func weatherChartTimeLabel(_ raw: String) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return trimmed }
        guard let hourRange = trimmed.range(
            of: #"(\d{1,2})(?=:\d{2})"#,
            options: .regularExpression
        ),
        let hourValue = Int(trimmed[hourRange]) else {
            return trimmed
        }

        let hourText = String(format: "%02d", hourValue)
        switch appViewModel.selectedLanguage {
        case .korean:
            return "\(hourText)시"
        case .english:
            return "\(hourText)h"
        }
    }

    private func weatherTemperatureValue(_ raw: String) -> Double? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let valueRange = trimmed.range(
            of: #"-?\d+(?:\.\d+)?"#,
            options: .regularExpression
        ) else {
            return nil
        }

        return Double(trimmed[valueRange])
    }

    private var plannerSheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(plannerButtonText)
                        .font(.system(size: 20 * appViewModel.fontScale, weight: .bold))
                        .foregroundStyle(Color(AppThemeColor.north.rawValue))
                    if let snapshot = viewModel.plannerSnapshot, !snapshot.location.isEmpty {
                        Text(snapshot.location)
                            .font(.system(size: 13 * appViewModel.fontScale, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                    if let snapshot = viewModel.plannerSnapshot {
                        let weather = viewModel.plannerWeatherBadgeText(for: snapshot)
                        if !weather.isEmpty {
                            Text(weather)
                                .font(.system(size: 12 * appViewModel.fontScale, weight: .semibold))
                                .foregroundStyle(Color(AppThemeColor.east.rawValue))
                        }
                    }
                }
                Spacer()
                Button {
                    showPlannerRegenerateConfirm = true
                } label: {
                    Text(regenerateText)
                        .font(.system(size: 12 * appViewModel.fontScale, weight: .bold))
                        .foregroundStyle(Color(AppThemeColor.east.rawValue))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 7)
                        .background(
                            Capsule(style: .continuous)
                                .fill(Color.white.opacity(0.92))
                        )
                }
                .buttonStyle(.plain)
            }

            if viewModel.isPlannerLoading {
                plannerLoadingCard
            } else if let error = viewModel.plannerErrorMessage {
                Text(error)
                    .font(.system(size: 13 * appViewModel.fontScale, weight: .medium))
                    .foregroundStyle(.secondary)
                    .padding(.top, 6)
            } else if let snapshot = viewModel.plannerSnapshot, !snapshot.plan.isEmpty {
                ScrollView {
                    VStack(spacing: 10) {
                        ForEach(snapshot.plan) { item in
                            plannerItemCard(item)
                        }
                    }
                    .padding(.bottom, 8)
                }
            } else {
                Text(plannerEmptyText)
                    .font(.system(size: 13 * appViewModel.fontScale, weight: .medium))
                    .foregroundStyle(.secondary)
                    .padding(.top, 6)
            }

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 18)
        .padding(.top, 20)
        .onAppear {
            viewModel.presentPlanner(language: appViewModel.selectedLanguage)
        }
        .background(
            Color(UIColor.systemGroupedBackground)
                .ignoresSafeArea()
        )
    }

    private func weatherIconColor(for symbolName: String) -> Color {
        switch symbolName {
        case "sun.max.fill":
            return .yellow
        case "cloud.rain.fill",
            "cloud.sleet.fill",
            "snowflake",
            "cloud.sun.rain.fill",
            "cloud.bolt.rain.fill":
            return .blue
        default:
            return .gray
        }
    }

    private var loadingBadge: some View {
        HStack(spacing: 10) {
            ProgressView()
                .tint(Color(AppThemeColor.east.rawValue))
            Text(loadingText)
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

            Button(retryText) {
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

    private var plannerButton: some View {
        Button {
            viewModel.presentPlanner(language: appViewModel.selectedLanguage)
        } label: {
            HStack(spacing: 6) {
                Text("🗓️")
                Text(plannerButtonText)
                    .font(.system(size: 13 * appViewModel.fontScale, weight: .bold))
            }
            .foregroundStyle(Color(AppThemeColor.north.rawValue))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(
                Capsule(style: .continuous)
                    .fill(Color.white.opacity(0.93))
            )
        }
        .buttonStyle(.plain)
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
        .accessibilityLabel(settingsText)
    }

    private func interventionToast(message: String) -> some View {
        HStack(spacing: 10) {
            Text(message)
                .font(.system(size: 12 * appViewModel.fontScale, weight: .semibold))
                .foregroundStyle(.white)
                .lineLimit(2)
                .multilineTextAlignment(.leading)

            Spacer(minLength: 6)

            Button {
                viewModel.clearInterventionToast()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.white.opacity(0.92))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color(AppThemeColor.north.rawValue).opacity(0.88))
        )
        .padding(.horizontal, 16)
    }

    private var locationOverlay: some View {
        ZStack {
            Color.black.opacity(0.48).ignoresSafeArea()

            VStack(spacing: 14) {
                Text(locationOverlayTitle)
                    .font(.system(size: 19 * appViewModel.fontScale, weight: .bold))
                    .multilineTextAlignment(.center)

                Text(locationOverlayBody)
                    .font(.system(size: 14 * appViewModel.fontScale))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)

                Button {
                    showSettings = true
                } label: {
                    Text(locationOverlayOpenSettingsText)
                        .font(.system(size: 15 * appViewModel.fontScale, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(Color(AppThemeColor.east.rawValue))
                        )
                }
                .buttonStyle(.plain)

                Button {
                    viewModel.centerOnUserLocation(animated: true)
                    viewModel.dismissLocationOverlay()
                } label: {
                    Text(locationOverlayRetryText)
                        .font(.system(size: 15 * appViewModel.fontScale, weight: .semibold))
                        .foregroundStyle(Color(AppThemeColor.east.rawValue))
                }
                .buttonStyle(.plain)
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

    private var subtitleView: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(viewModel.subtitle)
                .font(.system(size: 15 * appViewModel.fontScale, weight: .medium))
                .foregroundStyle(Color(AppThemeColor.north.rawValue))
                .frame(maxWidth: .infinity, alignment: .leading)

            if let selectedPlace = viewModel.selectedPlace,
               viewModel.canPlayMoreInfo(for: selectedPlace.id) {
                Button {
                    viewModel.playMoreInfo(for: selectedPlace, language: appViewModel.selectedLanguage)
                } label: {
                    Text(viewModel.moreInfoButtonTitle(for: appViewModel.selectedLanguage))
                        .font(.system(size: 13 * appViewModel.fontScale, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(
                            Capsule(style: .continuous)
                                .fill(Color(AppThemeColor.east.rawValue))
                        )
                }
                .buttonStyle(.plain)
            }
        }
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

    private var muteToggleButton: some View {
        Button {
            viewModel.toggleVoiceGuidance(for: appViewModel.selectedLanguage)
        } label: {
            Image(systemName: viewModel.isVoiceGuidanceEnabled ? "speaker.wave.3.fill" : "speaker.slash.fill")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 46, height: 46)
                .background(
                    Circle()
                        .fill(
                            viewModel.isVoiceGuidanceEnabled
                                ? Color(AppThemeColor.east.rawValue)
                                : Color(AppThemeColor.north.rawValue).opacity(0.8)
                        )
                )
        }
        .accessibilityLabel(muteVoiceText)
        .shadow(color: .black.opacity(0.15), radius: 6, y: 3)
    }

    private var autoDocentModeButton: some View {
        Button {
            viewModel.toggleAutoDocentMode(for: appViewModel.selectedLanguage)
        } label: {
            ZStack {
                Circle()
                    .fill(
                        viewModel.isAutoDocentEnabled
                            ? Color(AppThemeColor.east.rawValue)
                            : Color(AppThemeColor.north.rawValue).opacity(0.8)
                    )
                    .frame(width: 74, height: 74)

                VStack(spacing: 2) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 17, weight: .bold))
                    Text(viewModel.isAutoDocentEnabled ? "ON" : "OFF")
                        .font(.system(size: 10, weight: .bold))
                }
                .foregroundStyle(.white)
            }
        }
        .accessibilityLabel(autoDocentText)
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
        .accessibilityLabel(currentLocationText)
        .shadow(color: .black.opacity(0.15), radius: 6, y: 3)
    }

    private var plannerLoadingCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                ProgressView()
                    .tint(Color(AppThemeColor.east.rawValue))
                Text(plannerLoadingText)
                    .font(.system(size: 14 * appViewModel.fontScale, weight: .semibold))
                    .foregroundStyle(Color(AppThemeColor.north.rawValue))
            }
            Text(plannerLoadingSubtext)
                .font(.system(size: 11 * appViewModel.fontScale, weight: .medium))
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.white.opacity(0.95))
        )
    }

    private func plannerItemCard(_ item: PlannerPlanItem) -> some View {
        Button {
            viewModel.focusPlannerPlace(item, animated: true)
        } label: {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Text(periodIcon(for: item.period))
                    Text(item.period)
                        .font(.system(size: 13 * appViewModel.fontScale, weight: .bold))
                        .foregroundStyle(Color(AppThemeColor.north.rawValue))
                    if !item.time.isEmpty {
                        Text(item.time)
                            .font(.system(size: 12 * appViewModel.fontScale, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                }
                Text(item.place.name)
                    .font(.system(size: 15 * appViewModel.fontScale, weight: .bold))
                    .foregroundStyle(Color(AppThemeColor.north.rawValue))
                    .lineLimit(2)
                if !item.place.roadAddress.isEmpty {
                    Text(item.place.roadAddress)
                        .font(.system(size: 12 * appViewModel.fontScale, weight: .medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if !item.script.isEmpty {
                    Text(item.script)
                        .font(.system(size: 12 * appViewModel.fontScale, weight: .regular))
                        .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.86))
                        .lineLimit(3)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(Color.white.opacity(0.95))
            )
        }
        .buttonStyle(.plain)
    }

    private func periodIcon(for raw: String) -> String {
        switch raw {
        case "오전", "Morning":
            return "🌅"
        case "오후", "Afternoon":
            return "☀️"
        case "저녁", "Evening", "Night":
            return "🌙"
        default:
            return "📍"
        }
    }

    private func eventStatusText(for place: PlaceRecommendation) -> String {
        let isKorean = appViewModel.selectedLanguage == .korean
        if place.isOngoing == false {
            return isKorean ? "종료됨" : "Ended"
        }
        return isKorean ? "진행중" : "Ongoing"
    }

    private var weatherPillText: String {
        let status = viewModel.weatherOutdoorStatus.trimmingCharacters(in: .whitespacesAndNewlines)
        if status.isEmpty {
            return viewModel.weatherValue
        }
        return "\(status) · \(viewModel.weatherValue)"
    }

    private var loadingText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "주변 장소 로딩 중..."
        case .english:
            return "Loading nearby places..."
        }
    }

    private var plannerButtonText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "하루 일정"
        case .english:
            return "Daily Plan"
        }
    }

    private var plannerLoadingText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "일정을 생성하는 중…"
        case .english:
            return "Generating your day plan…"
        }
    }

    private var plannerLoadingSubtext: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "처음 방문하는 장소는 최대 5~10초 소요돼요"
        case .english:
            return "First-time places can take up to 5-10 seconds."
        }
    }

    private var plannerEmptyText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "추천 장소가 없어요."
        case .english:
            return "No recommended places in the plan."
        }
    }

    private var plannerRegenerateTitle: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "하루 일정 재생성"
        case .english:
            return "Regenerate Daily Plan"
        }
    }

    private var plannerRegenerateBody: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "현재 지도의 위치를 기준으로 새 일정을 생성할까요?"
        case .english:
            return "Generate a new plan based on the current map position?"
        }
    }

    private var regenerateText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "🔄 일정 재생성"
        case .english:
            return "🔄 Regenerate"
        }
    }

    private var cancelText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "취소"
        case .english:
            return "Cancel"
        }
    }

    private var retryText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "다시시도"
        case .english:
            return "Retry"
        }
    }

    private var settingsText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "설정"
        case .english:
            return "Settings"
        }
    }

    private var muteVoiceText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "음성 안내 음소거 토글"
        case .english:
            return "Toggle voice mute"
        }
    }

    private var currentLocationText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "현재 위치로 이동"
        case .english:
            return "Go to current location"
        }
    }

    private var locationOverlayTitle: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "위치 권한이 필요합니다"
        case .english:
            return "Location Permission Required"
        }
    }

    private var locationOverlayBody: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "위치 권한이 꺼져 있어 LALA를 실행할 수 없습니다. 앱 설정에서 위치 권한을 켜주세요."
        case .english:
            return "LALA cannot run while location access is off. Please enable location permission in Settings."
        }
    }

    private var locationOverlayOpenSettingsText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "앱 위치 설정 열기"
        case .english:
            return "Open App Location Settings"
        }
    }

    private var locationOverlayRetryText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "다시 확인"
        case .english:
            return "Check Again"
        }
    }

    private var autoDocentText: String {
        switch appViewModel.selectedLanguage {
        case .korean:
            return "자동 도슨트 모드 토글"
        case .english:
            return "Toggle auto docent mode"
        }
    }

    private func chipSelectedBackgroundColor(for filter: MapPlaceFilter) -> Color {
        switch filter {
        case .all:
            return Color(AppThemeColor.north.rawValue)
        case .attraction:
            return Color(AppThemeColor.south.rawValue)
        case .restaurant:
            return Color(AppThemeColor.center.rawValue)
        case .event:
            return Color(AppThemeColor.east.rawValue)
        }
    }

    private func chipSelectedTextColor(for filter: MapPlaceFilter) -> Color {
        switch filter {
        case .restaurant:
            return Color(AppThemeColor.north.rawValue)
        default:
            return .white
        }
    }

    private func categoryTextColor(for kind: PlaceCategoryKind) -> Color {
        switch kind {
        case .attraction:
            return Color(AppThemeColor.south.rawValue).opacity(0.95)
        case .restaurant:
            // Yellow needs a darker tone on white cards for readability.
            return Color(red: 0.55, green: 0.45, blue: 0.12)
        case .event:
            return Color(AppThemeColor.east.rawValue).opacity(0.95)
        }
    }
}

private struct WeatherForecastChartPoint: Identifiable {
    let id: Int
    let x: CGFloat
    let y: CGFloat
    let label: String
}

private struct PlaceDetailBottomSheet: View {
    let place: PlaceRecommendation
    let language: AppLanguage
    let fontScale: CGFloat
    let recommendationText: String
    let moreInfoButtonTitle: String
    let showMoreInfoButton: Bool
    let onPlayMoreInfo: () -> Void
    @Environment(\.openURL) private var openURL

    var body: some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(alignment: .leading, spacing: 14) {
                heroImage

                VStack(alignment: .leading, spacing: 6) {
                    Text(place.name(in: language))
                        .font(.system(size: 18 * fontScale, weight: .bold))
                        .foregroundStyle(Color(AppThemeColor.north.rawValue))
                        .lineLimit(2)

                    Text(place.category(in: language))
                        .font(.system(size: 13 * fontScale, weight: .semibold))
                        .foregroundStyle(categoryColor(for: place.categoryKind))

                    HStack(spacing: 6) {
                        Text(place.district(in: language))
                            .font(.system(size: 12 * fontScale, weight: .medium))
                            .foregroundStyle(.secondary)

                        if let distance = place.distanceLabel(in: language) {
                            Text(distance)
                                .font(.system(size: 12 * fontScale, weight: .semibold))
                                .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.75))
                        }
                    }

                    Text(place.address(in: language))
                        .font(.system(size: 12 * fontScale, weight: .regular))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }

                Text(recommendationText)
                    .font(.system(size: 13 * fontScale, weight: .medium))
                    .foregroundStyle(Color(AppThemeColor.north.rawValue))
                    .lineLimit(4)

                if place.categoryKind == .event {
                    eventInfo
                }

                if showMoreInfoButton {
                    Button(action: onPlayMoreInfo) {
                        Text(moreInfoButtonTitle)
                            .font(.system(size: 14 * fontScale, weight: .bold))
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                            .background(
                                RoundedRectangle(cornerRadius: 12, style: .continuous)
                                    .fill(Color(AppThemeColor.east.rawValue))
                            )
                    }
                    .buttonStyle(.plain)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 18)
            .padding(.top, 16)
            .padding(.bottom, 22)
        }
        .scrollBounceBehavior(.basedOnSize)
    }

    private var eventInfo: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(eventStatusText)
                .font(.system(size: 12 * fontScale, weight: .bold))
                .foregroundStyle(place.isOngoing == false ? .gray : Color(AppThemeColor.east.rawValue))

            if let dateText = eventDateRangeText {
                Text(dateText)
                    .font(.system(size: 12 * fontScale, weight: .medium))
                    .foregroundStyle(.secondary)
            }

            if let eventURL = place.eventURL {
                Button {
                    openURL(eventURL)
                } label: {
                    Text(eventDetailLinkText)
                        .font(.system(size: 12 * fontScale, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(Color(AppThemeColor.east.rawValue))
                        )
                }
                .buttonStyle(.plain)
            }

            if place.isApproximateLocation {
                Text(approximateLocationNotice)
                    .font(.system(size: 11 * fontScale, weight: .medium))
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var eventStatusText: String {
        let isKorean = language == .korean
        if place.isOngoing == false {
            return isKorean ? "⛔ 종료된 행사" : "⛔ Ended Event"
        }
        return isKorean ? "🟢 진행 중" : "🟢 Ongoing"
    }

    private var eventDetailLinkText: String {
        language == .korean ? "행사 상세 보기 →" : "Open Event Details →"
    }

    private var approximateLocationNotice: String {
        language == .korean
            ? "📍 정확한 위치 정보가 없어 시 중심 위치로 표시돼요"
            : "📍 Exact coordinates are unavailable, so the city center is shown."
    }

    private var eventDateRangeText: String? {
        let start = formattedDate(place.eventStartDate)
        let end = formattedDate(place.eventEndDate)
        if start == nil && end == nil {
            return nil
        }
        if language == .korean {
            if let start, let end {
                return "🗓️ \(start) ~ \(end)"
            }
            if let start {
                return "🗓️ \(start)부터"
            }
            if let end {
                return "🗓️ ~\(end)까지"
            }
        } else {
            if let start, let end {
                return "🗓️ \(start) ~ \(end)"
            }
            if let start {
                return "🗓️ From \(start)"
            }
            if let end {
                return "🗓️ Until \(end)"
            }
        }
        return nil
    }

    private func formattedDate(_ raw: String?) -> String? {
        guard let raw, !raw.isEmpty else { return nil }
        let source = DateFormatter()
        source.locale = Locale(identifier: "en_US_POSIX")
        source.dateFormat = "yyyy-MM-dd"
        guard let date = source.date(from: raw) else {
            return raw
        }
        let formatter = DateFormatter()
        formatter.locale = language == .korean ? Locale(identifier: "ko_KR") : Locale(identifier: "en_US")
        formatter.dateStyle = .medium
        return formatter.string(from: date)
    }

    private var heroImage: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            Color(AppThemeColor.center.rawValue).opacity(0.6),
                            Color(AppThemeColor.east.rawValue).opacity(0.45)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )

            if let imageURL = place.imageURL {
                AsyncImage(url: imageURL) { phase in
                    switch phase {
                    case let .success(image):
                        image
                            .resizable()
                            .scaledToFill()
                    default:
                        heroPlaceholder
                    }
                }
            } else {
                heroPlaceholder
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 170)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(Color.white.opacity(0.3), lineWidth: 1)
        )
    }

    private var heroPlaceholder: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(AppThemeColor.west.rawValue).opacity(0.85),
                    Color(AppThemeColor.center.rawValue).opacity(0.65)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            Image(systemName: "photo")
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.6))
        }
    }

    private func categoryColor(for kind: PlaceCategoryKind) -> Color {
        switch kind {
        case .attraction:
            return Color(AppThemeColor.south.rawValue).opacity(0.95)
        case .restaurant:
            return Color(red: 0.55, green: 0.45, blue: 0.12)
        case .event:
            return Color(AppThemeColor.east.rawValue).opacity(0.95)
        }
    }
}

#Preview {
    NavigationStack {
        MainMapView(appViewModel: AppViewModel())
    }
}

private struct MapAnnotationDisplayItem: Identifiable {
    enum Kind {
        case place(PlaceRecommendation)
        case cluster(count: Int, categoryKind: PlaceCategoryKind)
    }

    let id: String
    let coordinate: CLLocationCoordinate2D
    let kind: Kind
}

private struct MapAnnotationCacheKey: Equatable {
    let placesRenderID: UUID
    let selectedPlaceID: String?
    let spanBucket: MapAnnotationSpanBucket
    let viewportBucket: MapAnnotationViewportBucket
    let isClusteringEnabled: Bool
    let isForceClusterEnabled: Bool
}

private struct MapAnnotationSpanBucket: Equatable {
    private static let precision: CLLocationDegrees = 0.001
    let latitudeBucket: Int
    let longitudeBucket: Int

    init(span: MKCoordinateSpan) {
        latitudeBucket = Self.bucket(from: span.latitudeDelta)
        longitudeBucket = Self.bucket(from: span.longitudeDelta)
    }

    private static func bucket(from value: CLLocationDegrees) -> Int {
        Int((value / precision).rounded())
    }
}

private struct MapAnnotationViewportBucket: Equatable {
    let latitudeBucket: Int
    let longitudeBucket: Int

    init(center: CLLocationCoordinate2D, span: MKCoordinateSpan) {
        let latitudePrecision = max(span.latitudeDelta / 5.0, 0.0008)
        let longitudePrecision = max(span.longitudeDelta / 5.0, 0.0008)
        latitudeBucket = Self.bucket(from: center.latitude, precision: latitudePrecision)
        longitudeBucket = Self.bucket(from: center.longitude, precision: longitudePrecision)
    }

    private static func bucket(from value: CLLocationDegrees, precision: CLLocationDegrees) -> Int {
        Int((value / precision).rounded())
    }
}

private enum MapAnnotationRenderingPolicy {
    static let visiblePaddingMultiplier: CLLocationDegrees = 0.7
    static let minimumVisibleDelta: CLLocationDegrees = 0.0008
    static let maximumIndividualPins = 45
    static let forceClusterGridDivisions: Double = 3.6
    static let forceClusterMinimumLatitudeDelta: CLLocationDegrees = 0.006
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

private struct ClusterPinView: View {
    let count: Int
    let categoryKind: PlaceCategoryKind

    var body: some View {
        ZStack {
            Circle()
                .fill(Color.white.opacity(0.95))
                .frame(width: 42, height: 42)
                .shadow(color: .black.opacity(0.18), radius: 5, y: 2)

            Circle()
                .stroke(clusterColor, lineWidth: 2.2)
                .frame(width: 42, height: 42)

            Text("\(count)")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(clusterTextColor)
        }
    }

    private var clusterColor: Color {
        switch categoryKind {
        case .attraction:
            return Color(AppThemeColor.south.rawValue)
        case .restaurant:
            return Color(AppThemeColor.center.rawValue)
        case .event:
            return Color(AppThemeColor.east.rawValue)
        }
    }

    private var clusterTextColor: Color {
        switch categoryKind {
        case .restaurant:
            return Color(red: 0.42, green: 0.31, blue: 0.05)
        default:
            return clusterColor.opacity(0.92)
        }
    }
}

private struct PlacePinView: View {
    let title: String
    let categorySymbol: String
    let categoryKind: PlaceCategoryKind
    let isSelected: Bool
    let showTitle: Bool

    var body: some View {
        VStack(spacing: showTitle ? 4 : 0) {
            if showTitle {
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
            }

            ZStack {
                Circle()
                    .fill(Color.white)
                    .frame(width: isSelected ? 34 : 28, height: isSelected ? 34 : 28)
                    .shadow(color: .black.opacity(0.20), radius: 4, y: 2)

                Circle()
                    .fill(
                        isSelected
                            ? pinColor
                            : pinColor.opacity(0.9)
                    )
                    .frame(width: isSelected ? 22 : 18, height: isSelected ? 22 : 18)

                Image(systemName: categorySymbol)
                    .font(.system(size: isSelected ? 11 : 9, weight: .bold))
                    .foregroundStyle(.white)
            }
        }
        .frame(maxWidth: 150)
    }

    private var pinColor: Color {
        switch categoryKind {
        case .attraction:
            return Color(AppThemeColor.south.rawValue)
        case .restaurant:
            return Color(AppThemeColor.center.rawValue)
        case .event:
            return Color(AppThemeColor.east.rawValue)
        }
    }
}

private struct PlaceCardImageView: View {
    let imageURL: URL?
    var sideLength: CGFloat = 108

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            Color(AppThemeColor.center.rawValue).opacity(0.65),
                            Color(AppThemeColor.east.rawValue).opacity(0.45)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )

            if let imageURL {
                AsyncImage(url: imageURL) { phase in
                    switch phase {
                    case let .success(image):
                        image
                            .resizable()
                            .scaledToFill()
                    default:
                        placeholder
                    }
                }
            } else {
                placeholder
            }
        }
        .frame(width: sideLength, height: sideLength)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.white.opacity(0.3), lineWidth: 1)
        )
    }

    private var placeholder: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(AppThemeColor.west.rawValue).opacity(0.8),
                    Color(AppThemeColor.center.rawValue).opacity(0.6)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            Image(systemName: "photo")
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(Color(AppThemeColor.north.rawValue).opacity(0.6))
        }
    }
}
