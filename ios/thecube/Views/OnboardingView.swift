import SwiftUI
import UIKit

/// First launch: 4 screens. 1 welcome (the devil), 2 meal plan + balance, 3 goal / protein /
/// diet + allergens, 4 where to forward receipts (copy button). Saves through PUT /settings and
/// POST /balance at the end. Settings > "Show welcome again" replays it.
struct OnboardingView: View {
    @Environment(AppState.self) private var app
    @State private var vm = SettingsViewModel()
    @State private var page = 0
    @State private var copied = false
    @State private var saving = false
    let done: () -> Void

    private var inbound: String {
        (Bundle.main.object(forInfoDictionaryKey: "INBOUND_EMAIL") as? String ?? "")
            .trimmingCharacters(in: .whitespaces)
    }

    var body: some View {
        VStack(spacing: 0) {
            TabView(selection: $page) {
                welcome.tag(0)
                plan.tag(1)
                goal.tag(2)
                forward.tag(3)
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .indexViewStyle(.page(backgroundDisplayMode: .always))
            Button { next() } label: {
                Text(page < 3 ? "Continue" : (saving ? "Saving..." : "Start eating"))
                    .font(.headline).frame(maxWidth: .infinity).padding()
            }
            .buttonStyle(.borderedProminent)
            .disabled(saving)
            .padding()
        }
        .sensoryFeedback(.selection, trigger: page)
        .task(id: app.userId) { await vm.load(userId: app.userId) }
    }

    private func next() {
        if page < 3 { withAnimation { page += 1 }; return }
        saving = true
        Task {
            if vm.dirty { _ = await vm.save(userId: app.userId) }
            if !vm.balancePoints.isEmpty { _ = await vm.saveBalance(userId: app.userId) }
            app.dataChanged()
            saving = false
            done()
        }
    }

    // MARK: pages

    private var welcome: some View {
        VStack(spacing: 22) {
            Spacer()
            PixelDevil(mood: .happy, size: 150)
            Text("Pitchfork").font(.system(size: 44, weight: .black, design: .serif))
            Text("Your Duke dining coach.").font(.title3.weight(.semibold))
            VStack(alignment: .leading, spacing: 12) {
                bullet("envelope.arrow.triangle.branch", "Forward a dining receipt and the meal logs itself, with real NetNutrition macros.")
                bullet("chart.line.downtrend.xyaxis", "See if your food points last until finals.")
                bullet("fork.knife", "Get told what to eat next for your goal and budget.")
            }
            .padding(.horizontal)
            Spacer()
        }
        .padding()
    }

    private var plan: some View {
        page("Your meal plan", "Its starting balance sets an even pace through finals (fall break and Thanksgiving skipped).") {
            if vm.settings != nil {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 4), spacing: 10) {
                    ForEach(UserSettings.mealPlans, id: \.self) { p in
                        chip("Plan \(p)", on: vm.settings?.mealPlan == p) { vm.settings?.mealPlan = p }
                    }
                }
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("Points balance right now (optional)").font(.subheadline.weight(.semibold))
                TextField("e.g. 839.54", text: $vm.balancePoints)
                    .keyboardType(.decimalPad).textFieldStyle(.roundedBorder)
                Text("From DukeCard / eAccounts. Spending after this is subtracted automatically.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var goal: some View {
        page("Your goal", "Picks and the coach work toward this. Diet and allergen filters apply to every pick.") {
            if let s = vm.settings {
                Picker("Goal", selection: Binding(get: { s.goal }, set: { vm.settings?.goal = $0 })) {
                    Text("Balanced").tag("balanced")
                    Text("Build muscle").tag("build_muscle")
                    Text("Stretch points").tag("budget")
                }
                .pickerStyle(.segmented)
                Stepper("Protein: \(s.targets.proteinG) g a day",
                        value: Binding(get: { s.targets.proteinG }, set: { vm.settings?.targets.proteinG = $0 }),
                        in: 40...300, step: 5)
                    .font(.headline)
                Text("Diet").font(.subheadline.weight(.semibold))
                chips(UserSettings.diets, selected: s.requireDiets) { toggle($0, \.requireDiets) }
                Text("Avoid").font(.subheadline.weight(.semibold))
                chips(UserSettings.allergens, selected: s.avoidAllergens) { toggle($0, \.avoidAllergens) }
            }
        }
    }

    private var forward: some View {
        page("Forward receipts", "Duke emails a receipt for every mobile order. Forward it from Outlook and it shows up on Today in seconds.") {
            VStack(spacing: 14) {
                Image(systemName: "envelope.badge").font(.system(size: 54)).foregroundStyle(.tint)
                Text(inbound.isEmpty ? "Set INBOUND_EMAIL in Secrets.xcconfig" : inbound)
                    .font(.callout.monospaced()).lineLimit(1).minimumScaleFactor(0.5).textSelection(.enabled)
                    .padding().frame(maxWidth: .infinity)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 14))
                Button {
                    UIPasteboard.general.string = inbound
                    copied = true
                } label: {
                    Label(copied ? "Copied" : "Copy address", systemImage: copied ? "checkmark" : "doc.on.doc")
                }
                .buttonStyle(.bordered)
                .sensoryFeedback(.success, trigger: copied)
                Text("Tip: make an Outlook rule to auto-forward receipts, and you never log a meal by hand.")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
        }
    }

    // MARK: pieces

    private func page<C: View>(_ title: String, _ subtitle: String, @ViewBuilder _ content: () -> C) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(title).font(.largeTitle.bold())
                        Text(subtitle).foregroundStyle(.secondary)
                    }
                    Spacer()
                    PixelDevil(mood: .neutral, size: 44)
                }
                content()
            }
            .padding(24)
            .padding(.bottom, 40)
        }
    }

    private func bullet(_ icon: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon).font(.title3).foregroundStyle(.tint).frame(width: 28)
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func chip(_ text: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(text).font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity).padding(.vertical, 10)
                .background(on ? Color.accentColor : Color.secondary.opacity(0.15), in: Capsule())
                .foregroundStyle(on ? .white : .primary)
        }
        .buttonStyle(.plain)
    }

    private func chips(_ all: [String], selected: [String], tap: @escaping (String) -> Void) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 96))], spacing: 8) {
            ForEach(all, id: \.self) { v in chip(Fmt.label(v), on: selected.contains(v)) { tap(v) } }
        }
    }

    private func toggle(_ v: String, _ kp: WritableKeyPath<UserSettings, [String]>) {
        guard var list = vm.settings?[keyPath: kp] else { return }
        if list.contains(v) { list.removeAll { $0 == v } } else { list.append(v) }
        vm.settings?[keyPath: kp] = list.sorted()
    }
}
