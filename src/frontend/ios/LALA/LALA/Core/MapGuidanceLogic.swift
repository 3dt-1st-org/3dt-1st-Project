//
//  MapGuidanceLogic.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation

struct MapSelectionResult<ID: Equatable> {
    let selectedPlaceID: ID?
    let subtitle: String
    let shouldSpeak: Bool
    let shouldStopSpeaking: Bool
    let shouldCenterMap: Bool
}

enum MapGuidanceLogic {
    static func reduceSelection<ID: Equatable>(
        currentSelectedPlaceID: ID?,
        tappedPlaceID: ID,
        tappedSubtitle: String,
        defaultSubtitle: String,
        isVoiceGuidanceEnabled: Bool
    ) -> MapSelectionResult<ID> {
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
