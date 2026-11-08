import XCTest

/// Taps every way into Feeling hungry and Wrapped through iOS's real touch system, three times
/// each, and checks the screen actually appears. Needs the backend running (Simulator -> localhost).
/// Run: xcodebuild test -project ios/thecube.xcodeproj -scheme thecubeUITests -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max'
final class ButtonTests: XCTestCase {
    private var app: XCUIApplication!
    private let rounds = 3

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments += ["-onboarded", "YES"]
        app.launch()
        XCTAssertTrue(app.navigationBars["Today"].waitForExistence(timeout: 20), "Today didn't load")
    }

    private func button(startingWith text: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", text)).firstMatch
    }

    private func waitFor(_ e: XCUIElement, _ what: String, timeout: TimeInterval = 10, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(e.waitForExistence(timeout: timeout), "Never saw: \(what)", file: file, line: line)
    }

    private func backOnToday(file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertTrue(app.navigationBars["Today"].waitForExistence(timeout: 5), "Didn't return to Today", file: file, line: line)
    }

    /// Cook a pick, reroll it, close.
    private func cookAndClose() {
        waitFor(app.staticTexts["Tap or hold the pan to cook"], "the kitchen")
        app.buttons["Hold to cook"].tap()
        waitFor(app.buttons["Let's go"], "the meal card", timeout: 20)
        app.buttons["Reroll"].tap()
        waitFor(app.buttons["Let's go"], "a second card")
        app.buttons["Close"].firstMatch.tap()
        backOnToday()
    }

    func testFeelingHungryCardOnToday() {
        for _ in 0..<rounds {
            let card = button(startingWith: "Feeling hungry")
            waitFor(card, "the Feeling hungry card")
            card.tap()
            cookAndClose()
        }
    }

    func testDevilMenuOpensFeelingHungry() {
        for _ in 0..<rounds {
            app.buttons["Pitchfork devil"].tap()
            let item = app.buttons["Feeling hungry?"]
            waitFor(item, "the devil menu")
            item.tap()
            cookAndClose()
        }
    }

    func testDevilMenuOpensWrapped() {
        for _ in 0..<rounds {
            app.buttons["Pitchfork devil"].tap()
            let item = app.buttons["Your Wrapped"]
            waitFor(item, "the devil menu")
            item.tap()
            waitFor(app.staticTexts["Fall 2026 Wrapped"], "Wrapped", timeout: 20)
            for _ in 0..<8 { app.coordinate(withNormalizedOffset: CGVector(dx: 0.75, dy: 0.5)).tap() }
            app.buttons["Close"].firstMatch.tap()
            backOnToday()
        }
    }

    func testWrappedCardAtBottomOfToday() {
        let card = button(startingWith: "Your Fall 2026 Wrapped")
        for _ in 0..<6 where !card.isHittable { app.swipeUp() }
        for _ in 0..<rounds {
            card.tap()
            waitFor(app.staticTexts["Fall 2026 Wrapped"], "Wrapped", timeout: 20)
            app.buttons["Close"].firstMatch.tap()
            backOnToday()
        }
    }

    func testGoalSwitchAndTabs() {
        for goal in ["More protein", "Cheaper", "Balanced"] {
            let b = app.buttons[goal]
            waitFor(b, goal)
            b.tap()
            XCTAssertTrue(b.isSelected, "\(goal) didn't select")
        }
        for _ in 0..<rounds {
            app.tabBars.buttons["Log"].tap()
            waitFor(app.navigationBars["Log"], "Log tab")
            app.tabBars.buttons["Settings"].tap()
            waitFor(app.navigationBars["Settings"], "Settings tab")
            app.tabBars.buttons["Today"].tap()
            backOnToday()
        }
    }
}
