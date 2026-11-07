import SwiftUI

@main
struct thecubeApp: App {
    @State private var app = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(app)
                .task { await app.loadUsers() }
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

    var body: some View {
        TabView {
            Tab("Today", systemImage: "sun.max") { TodayView() }
            Tab("Log", systemImage: "plus.circle") { LogView() }
            Tab("Settings", systemImage: "gearshape") { SettingsView() }
        }
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
