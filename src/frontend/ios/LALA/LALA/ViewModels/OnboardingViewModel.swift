//
//  OnboardingViewModel.swift
//  LALA
//
//  Created by Codex on 3/2/26.
//

import Foundation
import Combine

@MainActor
final class OnboardingViewModel: ObservableObject {
    func title(in language: AppLanguage) -> String {
        language == .korean ? "경기도 로컬을 진짜처럼" : "Real Local Gyeonggi"
    }

    func subtitle(in language: AppLanguage) -> String {
        language == .korean
            ? "외국인을 위한 로컬 명소, 맛집, 문화 추천 서비스"
            : "Authentic local spots, food, and culture picks for travelers."
    }

    func bullets(in language: AppLanguage) -> [String] {
        if language == .korean {
            return [
                "지도에서 바로 주변 추천을 확인",
                "음성 안내와 자막으로 이동 중에도 편하게",
                "언어/글꼴/위치 동의 설정을 언제든 변경 가능"
            ]
        }

        return [
            "Explore nearby local picks directly on the map",
            "Voice guidance with subtitles for on-the-go use",
            "Language, font size, and location consent controls"
        ]
    }

    func ctaTitle(in language: AppLanguage) -> String {
        language == .korean ? "시작하기" : "Get Started"
    }
}
