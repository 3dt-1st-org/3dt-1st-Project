//
//  LocationPermissionManager.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import Combine
import CoreLocation

@MainActor
final class LocationPermissionManager: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published private(set) var authorizationStatus: CLAuthorizationStatus
    @Published private(set) var isLocationServicesEnabled: Bool

    private let manager = CLLocationManager()

    override init() {
        authorizationStatus = manager.authorizationStatus
        isLocationServicesEnabled = CLLocationManager.locationServicesEnabled()
        super.init()
        manager.delegate = self
        refresh()
    }

    var isAuthorized: Bool {
        authorizationStatus == .authorizedWhenInUse || authorizationStatus == .authorizedAlways
    }

    var requiresSettingsAction: Bool {
        !isLocationServicesEnabled || authorizationStatus == .denied || authorizationStatus == .restricted
    }

    func requestWhenInUsePermission() {
        refresh()
        guard CLLocationManager.locationServicesEnabled() else { return }
        manager.requestWhenInUseAuthorization()
    }

    func refresh() {
        isLocationServicesEnabled = CLLocationManager.locationServicesEnabled()
        authorizationStatus = manager.authorizationStatus
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        refresh()
    }
}
