import SwiftUI

/// "Eat next", shown inside Today (no separate tab): the app's #1 pick with the coach's reason,
/// a Balanced / More protein / Cheaper switch, and the other options behind a disclosure.
/// Reloads when the bias changes or a meal is logged/forwarded (mealCount), not on every poll.
struct EatNextSection: View {
    @Environment(AppState.self) private var app
    let mealCount: Int
    @State private var vm = EatNextViewModel()
    @State private var showOthers = false

    var body: some View {
        Section {
            Picker("Goal", selection: $vm.bias) {
                ForEach(Bias.allCases) { Text($0.label).tag($0) }
            }
            .pickerStyle(.segmented)
            .listRowSeparator(.hidden)
            if let e = vm.error { ErrorBanner(message: e) }
            if let r = vm.result {
                TargetLine(result: r)
                if let top = r.picks.first {
                    PickCard(pick: top, rank: 1, coach: r.coach)
                    let others = Array(r.picks.dropFirst())
                    if !others.isEmpty {
                        DisclosureGroup("\(others.count) other options", isExpanded: $showOthers) {
                            ForEach(Array(others.enumerated()), id: \.element.id) { i, p in
                                PickCard(pick: p, rank: i + 2, coach: nil)
                            }
                        }
                        .font(.subheadline)
                    }
                } else {
                    Text(r.openFallback ? "Everything's closed for the night. Picks come back when dining opens."
                                        : "Nothing open right now matches your settings.")
                        .foregroundStyle(.secondary)
                }
            } else if vm.loading {
                ProgressView().frame(maxWidth: .infinity)
            }
        } header: {
            Text("Eat next")
        } footer: {
            Text(vm.bias.blurb)
        }
        .task(id: "\(app.userId)-\(vm.bias.rawValue)-\(app.dataVersion)-\(mealCount)") {
            await vm.load(userId: app.userId)
        }
    }
}

/// One line: what this meal should bring, plus today's points room and restrictions.
struct TargetLine: View {
    let result: NextMeal

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 4) {
                Text(result.mealsLeft == 1 ? "Last meal today:" : "This meal:")
                    .foregroundStyle(.secondary)
                Text("aim for \(Fmt.g(result.perMealTarget.proteinG)) protein").bold()
                if let h = result.headroom {
                    Text("·").foregroundStyle(.secondary)
                    if h >= 0 {
                        Text("\(Fmt.pts(h)) pts left today")
                    } else {
                        Text("\(Fmt.pts(-h)) over today").foregroundStyle(.orange)
                    }
                }
            }
            .font(.footnote.monospacedDigit())
            let r = result.restrictions
            if !r.requireDiets.isEmpty || !r.avoidAllergens.isEmpty {
                HStack(spacing: 4) {
                    ForEach(r.requireDiets, id: \.self) { TraitChip(text: $0, diet: true) }
                    ForEach(r.avoidAllergens, id: \.self) { TraitChip(text: "no " + $0) }
                }
            }
            if result.openFallback && !result.picks.isEmpty {
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
                    Label("Blue Devil pick", systemImage: "star.fill").font(.caption.bold()).foregroundStyle(.orange)
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
