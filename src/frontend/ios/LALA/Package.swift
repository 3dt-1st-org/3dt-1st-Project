// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "LALACore",
    platforms: [
        .iOS(.v16),
        .macOS(.v13)
    ],
    products: [
        .library(name: "LALACore", targets: ["LALACore"])
    ],
    targets: [
        .target(
            name: "LALACore",
            path: "LALA/Core"
        ),
        .testTarget(
            name: "LALACoreTests",
            dependencies: ["LALACore"],
            path: "Tests/LALACoreTests"
        )
    ]
)
