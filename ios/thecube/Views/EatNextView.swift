import SwiftUI

/// SPEC 13 Eat next: 3 picks (vendor, items, price, protein/cal/carbs), coach pick highlighted
/// with its reason. Segmented: Balanced / More protein / Cheaper.
struct EatNextView: View {
    @Environment(AppState.self) private var app
    @State private var vm = EatNextViewModel()

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("Bias", selection: $vm.bias) {
                        ForEach(Bias.allCases) { Text($0.label).tag($0) }
                    }
                    .pickerStyle(.segmented)
                } footer: {
                    Text(vm.bias.blurb)
                }
                if let e = vm.error { Section { ErrorBanner(message: e) } }
                if let r = vm.result {
                    Section { TargetHeader(result: r) }
                    if r.picks.isEmpty {
                        Section {
                            Text("Nothing open right now matches your settings.").foregroundStyle(.secondary)
                        }
                    }
                    ForEach(Array(r.picks.enumerated()), id: \.element.id) { i, p in
                        Section {
                            PickCard(pick: p, rank: i + 1, coach: r.coach?.chosenIndex == i ? r.coach : nil)
                        }
                    }
                } else if vm.loading {
                    Section { ProgressView().frame(maxWidth: .infinity) }
                }
            }
            .navigationTitle("Eat next")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { UserSwitcher() } }
            .refreshable { await vm.load(userId: app.userId) }
            .task(id: "\(app.userId)-\(vm.bias.rawValue)-\(app.dataVersion)") { await vm.load(userId: app.userId) }
        }
    }
}

struct TargetHeader: View {
    let result: NextMeal

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(result.mealsLeft == 1 ? "Still to eat today" : "Aim for this meal (2 left today)")
                .font(.caption.weight(.semibold)).foregroundStyle(.secondary).textCase(.uppercase)
            HStack(alignment: .top) {
                Stat(label: "protein", value: Fmt.g(result.perMealTarget.proteinG))
                if let c = result.perMealTarget.calories { Stat(label: "calories", value: Fmt.cal(c)) }
                if let h = result.headroom {
                    if h >= 0 {
                        Stat(label: "points left in today's budget", value: Fmt.pts(h))
                    } else {
                        Stat(label: "over today's budget", value: Fmt.pts(-h), tint: .orange)
                    }
                }
            }
            let r = result.restrictions
            if !r.requireDiets.isEmpty || !r.avoidAllergens.isEmpty {
                HStack(spacing: 4) {
                    ForEach(r.requireDiets, id: \.self) { TraitChip(text: $0, diet: true) }
                    ForEach(r.avoidAllergens, id: \.self) { TraitChip(text: "no " + $0) }
                }
            }
            if result.openFallback {
                Text("Nothing is open now; showing places opening within 2 hours.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

struct PickCard: View {
    let pick: Pick
    let rank: Int
    let coach: PickCoach?
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let coach {
                VStack(alignment: .leading, spacing: 4) {
                    Label("Coach pick", systemImage: "star.fill").font(.caption.bold()).foregroundStyle(.orange)
                    Text(coach.headline).font(.subheadline.bold())
                    Text(coach.reason).font(.subheadline).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Divider()
            }
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(pick.vendor).font(.caption).foregroundStyle(.secondary)
                    Text(pick.title).font(.headline)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text(Fmt.money(pick.price)).font(.headline.monospacedDigit())
                    Text("\(Fmt.pts(pick.pointsCost)) pts").font(.caption).foregroundStyle(.secondary)
                }
            }
            HStack(spacing: 16) {
                MacroPill(label: "protein", value: Fmt.g(pick.proteinG))
                if let c = pick.calories { MacroPill(label: "calories", value: "\(Int(c.rounded()))") }
                MacroPill(label: "carbs", value: Fmt.g(pick.carbsG))
            }
            if let o = pick.opensAt { Text("Opens \(Fmt.time(o))").font(.caption).foregroundStyle(.orange) }
            DisclosureGroup(isExpanded: $expanded) {
                ForEach(pick.components, id: \.self) { c in
                    HStack {
                        Text(c.name)
                        Spacer()
                        Text("\(c.portion) · \(Fmt.g(c.proteinG))").foregroundStyle(.secondary)
                    }
                    .font(.caption)
                }
            } label: {
                Text("\(pick.components.count) items").font(.caption)
            }
        }
        .padding(.vertical, 4)
        .listRowBackground(coach != nil ? Color.yellow.opacity(0.08) : nil)
    }
}

struct MacroPill: View {
    let label: String
    let value: String

    var body: some View {
        VStack(spacing: 0) {
            Text(value).font(.subheadline.monospacedDigit().bold())
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
    }
}
