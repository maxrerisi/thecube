import SwiftUI

/// SPEC 13 Settings: goal, targets, diet + allergen chips, show calories, semester end, balance.
struct SettingsView: View {
    @Environment(AppState.self) private var app
    @State private var vm = SettingsViewModel()

    var body: some View {
        NavigationStack {
            Form {
                if let e = vm.error { Section { ErrorBanner(message: e) } }
                if let s = vm.status { Section { Label(s, systemImage: "checkmark.circle").foregroundStyle(.green) } }
                if vm.settings != nil { settingsSections }
                Section {
                    TextField("Points balance", text: $vm.balancePoints).keyboardType(.decimalPad)
                    TextField("Meal swipes left (optional)", text: $vm.balanceSwipes).keyboardType(.numberPad)
                    Button("Update balance") {
                        Task { if await vm.saveBalance(userId: app.userId) { app.dataChanged() } }
                    }
                    .disabled(vm.balancePoints.isEmpty)
                } header: {
                    Text("Balance")
                } footer: {
                    Text("From DukeCard / eAccounts. Spending after this is subtracted automatically.")
                }
                if APIClient.shared.isMock {
                    Section { Text("Demo mode: showing bundled sample data. Set API_BASE_URL in Secrets.xcconfig.").font(.caption) }
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { UserSwitcher() }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { if await vm.save(userId: app.userId) { app.dataChanged() } } }
                        .disabled(!vm.dirty)
                }
            }
            .task(id: app.userId) { await vm.load(userId: app.userId) }
        }
    }

    @ViewBuilder private var settingsSections: some View {
        Section("Goal") {
            Picker("Goal", selection: binding(\.goal)) {
                Text("Balanced").tag("balanced")
                Text("Build muscle").tag("build_muscle")
                Text("Stretch my points").tag("budget")
            }
            Stepper("Calories: \(vm.settings?.targets.calories ?? 0)", value: binding(\.targets.calories), in: 1800...5000, step: 100)
            Stepper("Protein: \(vm.settings?.targets.proteinG ?? 0) g", value: binding(\.targets.proteinG), in: 40...300, step: 5)
            Toggle("Show calories", isOn: binding(\.showCalories))
        }
        Section("Diet (every item must match)") {
            ForEach(UserSettings.diets, id: \.self) { d in
                Toggle(Fmt.label(d), isOn: member(d, in: \.requireDiets))
            }
        }
        Section("Avoid allergens") {
            ForEach(UserSettings.allergens, id: \.self) { a in
                Toggle(Fmt.label(a), isOn: member(a, in: \.avoidAllergens))
            }
        }
        Section("Semester") {
            DatePicker("Semester ends", selection: semesterEnd, displayedComponents: .date)
        }
    }

    // MARK: bindings into vm.settings

    private func binding<T>(_ kp: WritableKeyPath<UserSettings, T>) -> Binding<T> {
        Binding(get: { vm.settings![keyPath: kp] }, set: { vm.settings![keyPath: kp] = $0; vm.status = nil })
    }

    private func member(_ value: String, in kp: WritableKeyPath<UserSettings, [String]>) -> Binding<Bool> {
        Binding(get: { vm.settings?[keyPath: kp].contains(value) ?? false },
                set: { on in
                    guard var list = vm.settings?[keyPath: kp] else { return }
                    list.removeAll { $0 == value }
                    if on { list.append(value) }
                    vm.settings![keyPath: kp] = list.sorted()
                    vm.status = nil
                })
    }

    private static let dayFormat: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()

    private var semesterEnd: Binding<Date> {
        Binding(get: { vm.settings.flatMap { Self.dayFormat.date(from: $0.semesterEnd) } ?? .now },
                set: { vm.settings?.semesterEnd = Self.dayFormat.string(from: $0); vm.status = nil })
    }
}
