//
//  LocationPermissionManager.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import Combine
import CoreLocation
import UIKit

@MainActor
final class LocationPermissionManager: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published private(set) var authorizationStatus: CLAuthorizationStatus
    @Published private(set) var isLocationServicesEnabled: Bool?

    private let manager = CLLocationManager()

    override init() {
        authorizationStatus = manager.authorizationStatus
        isLocationServicesEnabled = nil
        super.init()
        manager.delegate = self
        refresh()
    }

    var isAuthorized: Bool {
        authorizationStatus == .authorizedWhenInUse || authorizationStatus == .authorizedAlways
    }

    var requiresSettingsAction: Bool {
        guard let enabled = isLocationServicesEnabled else { return false }
        return !enabled || authorizationStatus == .denied || authorizationStatus == .restricted
    }

    func requestWhenInUsePermission() {
        Task {
            let enabled = await Task.detached(priority: .userInitiated) {
                CLLocationManager.locationServicesEnabled()
            }.value
            if enabled {
                manager.requestWhenInUseAuthorization()
            } else {
                refresh()
            }
        }
    }

    func refresh() {
        let currentStatus = manager.authorizationStatus
        Task {
            let enabled = await Task.detached(priority: .userInitiated) {
                CLLocationManager.locationServicesEnabled()
            }.value
            isLocationServicesEnabled = enabled
            authorizationStatus = currentStatus
        }
    }

    func openAppSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        DispatchQueue.main.async {
            UIApplication.shared.open(url, options: [:], completionHandler: nil)
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        refresh()
    }
}
