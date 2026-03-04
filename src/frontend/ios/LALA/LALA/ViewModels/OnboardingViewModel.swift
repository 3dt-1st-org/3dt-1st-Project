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
        switch language {
        case .korean:
            return "경기도 로컬을 진짜처럼"
        case .english:
            return "Real Local Gyeonggi"
        case .japanese:
            return "京畿道ローカルを本物らしく"
        }
    }

    func subtitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "외국인을 위한 로컬 명소, 맛집, 문화 추천 서비스"
        case .english:
            return "Authentic local spots, food, and culture picks for travelers."
        case .japanese:
            return "旅行者向けのローカル名所・グルメ・文化推薦サービス"
        }
    }

    func bullets(in language: AppLanguage) -> [String] {
        switch language {
        case .korean:
            return [
                "지도에서 바로 주변 추천을 확인",
                "음성 안내와 자막으로 이동 중에도 편하게",
                "언어/글꼴/위치 동의 설정을 언제든 변경 가능"
            ]
        case .english:
            return [
                "Explore nearby local picks directly on the map",
                "Voice guidance with subtitles for on-the-go use",
                "Language, font size, and location consent controls"
            ]
        case .japanese:
            return [
                "地図上で周辺のおすすめをすぐに確認",
                "移動中も音声ガイドと字幕で快適に利用",
                "言語・文字サイズ・位置情報同意をいつでも変更可能"
            ]
        }
    }

    func ctaTitle(in language: AppLanguage) -> String {
        switch language {
        case .korean:
            return "시작하기"
        case .english:
            return "Get Started"
        case .japanese:
            return "はじめる"
        }
    }
}
