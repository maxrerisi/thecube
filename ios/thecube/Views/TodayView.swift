import SwiftUI

/// SPEC 13 Today: coach card; protein + calorie rings; points, swipes, daily budget, run-out
/// date; today's meals. Pull to refresh, swipe to delete, polls /today every 5 s while visible.
struct TodayView: View {
    @Environment(AppState.self) private var app
    @State private var vm = TodayViewModel()

    var body: some View {
        NavigationStack {
            List {
                if let e = vm.error { Section { ErrorBanner(message: e) } }
                if let t = vm.today {
                    if let c = t.coach {
                        Section { CoachCardView(card: c) }
                    }
                    Section { RingsRow(today: t) }
                    Section("Points") { PointsCard(points: t.points, semesterEnd: t.semesterEnd) }
                    Section("Today's meals") {
                        if t.meals.isEmpty {
                            Text("Nothing logged yet today.").foregroundStyle(.secondary)
                        }
                        ForEach(t.meals) { m in
                            MealRow(meal: m, showCalories: t.showCalories)
                                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                    Button(role: .destructive) {
                                        Task { await vm.delete(m, userId: app.userId); app.dataChanged() }
                                    } label: { Label("Delete", systemImage: "trash") }
                                }
                        }
                    }
                } else if vm.loading {
                    Section { ProgressView().frame(maxWidth: .infinity) }
                }
            }
            .navigationTitle("Today")
            .refreshable { await vm.load(userId: app.userId) }
            // Poll every 5 s while visible so a live-forwarded receipt shows up on stage.
            .task(id: "\(app.userId)-\(app.dataVersion)") {
                while !Task.isCancelled {
                    await vm.load(userId: app.userId)
                    try? await Task.sleep(for: .seconds(5))
                }
            }
        }
    }
}

struct CoachCardView: View {
    let card: CoachCard

    private var color: Color {
        switch card.tone {
        case "praise": .green
        case "warning": .orange
        default: .blue
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(card.headline, systemImage: card.tone == "warning" ? "exclamationmark.circle" : "sparkles")
                .font(.headline)
                .foregroundStyle(color)
            Text(card.message)
                .font(.subheadline)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }
}

struct RingsRow: View {
    let today: Today

    var body: some View {
        HStack(spacing: 24) {
            Ring(title: "Protein", value: today.eaten.proteinG, target: Double(today.targets.proteinG), unit: "g", color: .pink)
            if today.showCalories, let cal = today.eaten.calories, let target = today.targets.calories {
                Ring(title: "Calories", value: cal, target: Double(target), unit: "", color: .orange)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("\(today.proteinHitDays7) of 7").font(.title3.bold())
                Text("days protein hit").font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
    }
}

struct Ring: View {
    let title: String
    let value: Double
    let target: Double
    let unit: String
    let color: Color

    private var progress: Double { target > 0 ? min(value / target, 1) : 0 }

    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                Circle().stroke(color.opacity(0.2), lineWidth: 10)
                Circle().trim(from: 0, to: progress)
                    .stroke(color, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .animation(.easeOut, value: progress)
                VStack(spacing: 0) {
                    Text("\(Int(value.rounded()))").font(.headline.monospacedDigit())
                    Text("/ \(Int(target))\(unit)").font(.caption2).foregroundStyle(.secondary)
                }
            }
            .frame(width: 84, height: 84)
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(title): \(Int(value.rounded())) of \(Int(target))\(unit)")
    }
}

struct PointsCard: View {
    let points: PointsStatus
    let semesterEnd: String

    var body: some View {
        if points.points == nil {
            Text("Enter your points balance in Settings to see your budget.")
                .foregroundStyle(.secondary)
        } else {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 8) {
                GridRow {
                    Stat(label: "Points left", value: Fmt.pts(points.points))
                    Stat(label: "Swipes left", value: points.swipes.map(String.init) ?? "–")
                }
                GridRow {
                    Stat(label: "Daily budget", value: Fmt.pts(points.dailyBudget))
                    Stat(label: "Spent today", value: Fmt.pts(points.spentToday))
                }
                GridRow {
                    Stat(label: "7-day average", value: Fmt.pts(points.trailingDaily))
                    if let r = points.runout {
                        Stat(label: "Runs out", value: Fmt.day(r), tint: .orange)
                    } else {
                        Stat(label: "Lasts until", value: Fmt.day(semesterEnd), tint: .green)
                    }
                }
            }
            if let plan = points.mealPlan, let target = points.paceTarget, let gap = points.vsPace {
                PaceRow(plan: plan, target: target, gap: gap)
            }
        }
    }
}

/// Where you are vs an even pace for your plan (start balance over the term's dining days).
struct PaceRow: View {
    let plan: String
    let target: Double
    let gap: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Label("Plan \(plan) pace", systemImage: "chart.line.downtrend.xyaxis")
                    .font(.subheadline.weight(.medium))
                Spacer()
                Text(gap < 0 ? "\(Fmt.pts(-gap)) behind" : "\(Fmt.pts(gap)) ahead")
                    .font(.subheadline.monospacedDigit().weight(.semibold))
                    .foregroundStyle(gap < 0 ? .orange : .green)
            }
            Text("Spending evenly through Dec 14 (breaks skipped) leaves \(Fmt.pts(target)) today.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(.top, 8)
    }
}

struct Stat: View {
    let label: String
    let value: String
    var tint: Color = .primary

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).font(.title3.monospacedDigit().weight(.semibold)).foregroundStyle(tint)
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct MealRow: View {
    let meal: Meal
    let showCalories: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(meal.vendor).font(.headline)
                Spacer()
                Text(Fmt.time(meal.ts)).font(.caption).foregroundStyle(.secondary)
            }
            Text(meal.items.joined(separator: ", ")).font(.subheadline).foregroundStyle(.secondary)
            HStack(spacing: 12) {
                Text(Fmt.g(meal.proteinG) + " protein")
                if showCalories { Text(Fmt.cal(meal.calories)) }
                Text(meal.swipesUsed > 0 ? "\(meal.swipesUsed) swipe + \(Fmt.pts(meal.pointsSpent)) pts"
                                         : "\(Fmt.pts(meal.pointsSpent)) pts")
                if meal.macrosPartial {
                    Text("partial").font(.caption2).foregroundStyle(.orange)
                }
            }
            .font(.caption.monospacedDigit())
        }
        .padding(.vertical, 2)
    }
}
