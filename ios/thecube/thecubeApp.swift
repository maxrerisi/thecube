import SwiftUI
import WidgetKit

@main
struct thecubeApp: App {
    @State private var app = AppState()
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(app)
                .task { await app.loadUsers() }
                .onOpenURL { app.open($0) }
        }
        // Leaving the app (going home to the widgets): redraw them with the latest picks now,
        // not on their own 15-minute schedule.
        .onChange(of: phase) { _, p in
            if p != .active { WidgetCenter.shared.reloadAllTimelines() }
        }
    }
}

/// The one user (Blue Devil), shared by every tab.
@Observable
@MainActor
final class AppState {
    var users: [User] = []
    var userId: Int = 1
    var loadError: String?
    /// Bumped after anything that changes data (log, import, delete, settings) so tabs reload.
    var dataVersion = 0
    /// Latest /today (set by TodayView) so the devil in every tab shows the right mood.
    var today: Today?
    var showHungry = false
    var showWrapped = false
    var tab = "today"

    var mood: DevilMood { today.map(DevilMood.from) ?? .neutral }

    /// pitchfork://hungry, pitchfork://wrapped, pitchfork://today (widgets link here).
    func open(_ url: URL) {
        switch url.host() {
        case "hungry": tab = "today"; showHungry = true
        case "wrapped": tab = "today"; showWrapped = true
        default: tab = "today"
        }
    }
    let api = APIClient.shared

    var user: User? { users.first { $0.id == userId } }

    func loadUsers() async {
        do {
            users = try await api.users()
            // One user: the demo student (Blue Devil). Forwarded receipts land there too.
            if let me = users.first(where: \.isDemo) ?? users.first { userId = me.id }
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }

    func dataChanged() { dataVersion += 1 }
}

struct RootView: View {
    @Environment(AppState.self) private var app
    @AppStorage("onboarded") private var onboarded = false

    var body: some View {
        @Bindable var app = app
        TabView(selection: $app.tab) {
            Tab("Today", systemImage: "sun.max", value: "today") { TodayView() }
            Tab("Log", systemImage: "plus.circle", value: "log") { LogView() }
            Tab("Settings", systemImage: "gearshape", value: "settings") { SettingsView() }
        }
        .fullScreenCover(isPresented: $app.showHungry) { HungryView() }
        .fullScreenCover(isPresented: $app.showWrapped) { WrappedView() }
        .fullScreenCover(isPresented: Binding(get: { !onboarded }, set: { onboarded = !$0 })) {
            OnboardingView { onboarded = true }
        }
    }
}

/// The devil in the top-right of every tab (trailing = actions, per Apple's HIG; leading is for
/// Back). Tap: it says how things are going and offers Feeling hungry / Wrapped.
struct DevilToolbar: ToolbarContent {
    @Environment(AppState.self) private var app

    // Static sprite: an animating label rebuilt the bar button every frame and dropped taps.
    // A native Menu: the sheet/popover versions couldn't reliably hand off to the full-screen covers.
    var body: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Section(app.mood.line) {
                    Button { app.showHungry = true } label: { Label("Feeling hungry?", systemImage: "frying.pan.fill") }
                    Button { app.showWrapped = true } label: { Label("Your Wrapped", systemImage: "sparkles") }
                }
            } label: {
                PixelDevil(mood: app.mood, size: 30, animated: false).padding(4).contentShape(Rectangle())
            }
            .accessibilityLabel("Pitchfork devil")
        }
        .sharedBackgroundVisibility(.hidden)
    }
}

/// Small capsule for diet / allergen traits (text, no emoji).
struct TraitChip: View {
    let text: String
    var diet = false

    var body: some View {
        Text(Fmt.label(text))
            .font(.caption2.weight(.medium))
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(diet ? Color.green.opacity(0.15) : Color.orange.opacity(0.15), in: Capsule())
            .foregroundStyle(diet ? Color.green : Color.orange)
    }
}

struct ErrorBanner: View {
    let message: String
    var body: some View {
        Label(message, systemImage: "exclamationmark.triangle")
            .font(.footnote)
            .foregroundStyle(.red)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
