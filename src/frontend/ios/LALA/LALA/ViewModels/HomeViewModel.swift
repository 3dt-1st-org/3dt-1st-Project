//
//  HomeViewModel.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import Combine

@MainActor
final class HomeViewModel: ObservableObject {
    @Published private(set) var title = "LALA"
    @Published private(set) var subtitle = "Local Area, Local Answer"

    let backgroundColorAsset = AppThemeColor.center.rawValue
    let titleColorAsset = AppThemeColor.north.rawValue
    let accentColorAsset = AppThemeColor.east.rawValue
}
