//
//  MapGuidanceLogic.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation

struct MapSelectionResult {
    let selectedPlaceID: UUID?
    let subtitle: String
    let shouldSpeak: Bool
    let shouldStopSpeaking: Bool
    let shouldCenterMap: Bool
}

enum MapGuidanceLogic {
    static func reduceSelection(
        currentSelectedPlaceID: UUID?,
        tappedPlaceID: UUID,
        tappedSubtitle: String,
        defaultSubtitle: String,
        isVoiceGuidanceEnabled: Bool
    ) -> MapSelectionResult {
        if currentSelectedPlaceID == tappedPlaceID {
            return MapSelectionResult(
                selectedPlaceID: nil,
                subtitle: defaultSubtitle,
                shouldSpeak: false,
                shouldStopSpeaking: true,
                shouldCenterMap: false
            )
        }

        return MapSelectionResult(
            selectedPlaceID: tappedPlaceID,
            subtitle: tappedSubtitle,
            shouldSpeak: isVoiceGuidanceEnabled,
            shouldStopSpeaking: false,
            shouldCenterMap: true
        )
    }
}
