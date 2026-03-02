//
//  ContentView.swift
//  LALA
//
//  Created by 루딘 on 3/2/26.
//

import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = HomeViewModel()

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "sparkles")
                .font(.system(size: 36, weight: .semibold))
                .foregroundStyle(Color(viewModel.accentColorAsset))

            Text(viewModel.title)
                .font(.system(size: 30, weight: .bold))

            Text(viewModel.subtitle)
                .font(.subheadline)
                .foregroundStyle(Color(viewModel.titleColorAsset).opacity(0.9))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .foregroundStyle(Color(viewModel.titleColorAsset))
        .background(Color(viewModel.backgroundColorAsset).ignoresSafeArea())
    }
}

#Preview {
    ContentView()
}
