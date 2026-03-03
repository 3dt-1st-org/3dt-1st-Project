import XCTest
@testable import LALACore

final class MapGuidanceLogicTests: XCTestCase {
    func testReduceSelection_SelectsNewPlace_WhenDifferentPlaceTapped() {
        let currentID = UUID()
        let tappedID = UUID()

        let result = MapGuidanceLogic.reduceSelection(
            currentSelectedPlaceID: currentID,
            tappedPlaceID: tappedID,
            tappedSubtitle: "Tapped subtitle",
            defaultSubtitle: "Default subtitle",
            isVoiceGuidanceEnabled: true
        )

        XCTAssertEqual(result.selectedPlaceID, tappedID)
        XCTAssertEqual(result.subtitle, "Tapped subtitle")
        XCTAssertTrue(result.shouldSpeak)
        XCTAssertFalse(result.shouldStopSpeaking)
        XCTAssertTrue(result.shouldCenterMap)
    }

    func testReduceSelection_DeselectsPlace_WhenSamePlaceTapped() {
        let tappedID = UUID()

        let result = MapGuidanceLogic.reduceSelection(
            currentSelectedPlaceID: tappedID,
            tappedPlaceID: tappedID,
            tappedSubtitle: "Tapped subtitle",
            defaultSubtitle: "Default subtitle",
            isVoiceGuidanceEnabled: true
        )

        XCTAssertNil(result.selectedPlaceID)
        XCTAssertEqual(result.subtitle, "Default subtitle")
        XCTAssertFalse(result.shouldSpeak)
        XCTAssertTrue(result.shouldStopSpeaking)
        XCTAssertFalse(result.shouldCenterMap)
    }

    func testReduceSelection_DoesNotSpeak_WhenVoiceGuidanceDisabled() {
        let tappedID = UUID()

        let result = MapGuidanceLogic.reduceSelection(
            currentSelectedPlaceID: nil,
            tappedPlaceID: tappedID,
            tappedSubtitle: "Tapped subtitle",
            defaultSubtitle: "Default subtitle",
            isVoiceGuidanceEnabled: false
        )

        XCTAssertEqual(result.selectedPlaceID, tappedID)
        XCTAssertEqual(result.subtitle, "Tapped subtitle")
        XCTAssertFalse(result.shouldSpeak)
        XCTAssertFalse(result.shouldStopSpeaking)
        XCTAssertTrue(result.shouldCenterMap)
    }
}
