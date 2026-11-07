import AppIntents
import SwiftUI
import WidgetKit

// Pitchfork widgets. Same API and models as the app (ios/Shared); every number is the server's.
// Lock screen: protein ring (circular), points pace bar (rectangular), one line (inline).
// Home screen: devil + protein ring (small), top pick + reroll button (medium), mini Today (large).

@main
struct PitchforkWidgets: WidgetBundle {
    var body: some Widget {
        TodayWidget()
        HungryWidget()
    }
}

// MARK: data

struct Snapshot: TimelineEntry {
    let date: Date
    let today: Today?
    let next: NextMeal?
    let pickIndex: Int

    var pick: Pick? {
        guard let picks = next?.picks, !picks.isEmpty else { return nil }
        return picks[pickIndex % picks.count]
    }
    var protein: Double { today?.eaten.proteinG ?? 0 }
    var proteinTarget: Double { Double(today?.targets.proteinG ?? 150) }
    var mood: DevilMood { today.map(DevilMood.from) ?? .neutral }

    static let empty = Snapshot(date: .now, today: nil, next: nil, pickIndex: 0)
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> Snapshot { .empty }

    func getSnapshot(in context: Context, completion: @escaping (Snapshot) -> Void) {
        Task { completion(await Self.load()) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<Snapshot>) -> Void) {
        Task {
            let s = await Self.load()
            completion(Timeline(entries: [s], policy: .after(.now.addingTimeInterval(15 * 60))))
        }
    }

    static func load() async -> Snapshot {
        let api = APIClient.shared
        let users = (try? await api.users()) ?? []
        let id = (users.first(where: \.isDemo) ?? users.first)?.id ?? 2
        async let t = try? api.today(userId: id)
        async let n = try? api.nextMeal(userId: id, bias: .balanced)
        return Snapshot(date: .now, today: await t, next: await n,
                        pickIndex: UserDefaults.standard.integer(forKey: "pickIndex"))
    }
}

/// The medium widget's button: show the next pick without opening the app.
struct RerollIntent: AppIntent {
    static var title: LocalizedStringResource = "Another pick"
    func perform() async throws -> some IntentResult {
        let d = UserDefaults.standard
        d.set(d.integer(forKey: "pickIndex") + 1, forKey: "pickIndex")
        return .result()
    }
}

// MARK: widgets

struct TodayWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "PitchforkToday", provider: Provider()) { e in
            TodayWidgetView(e).containerBackground(for: .widget) { WidgetBackground() }
        }
        .configurationDisplayName("Pitchfork")
        .description("Protein today and whether your points will last.")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular, .accessoryInline, .systemSmall, .systemLarge])
    }
}

struct HungryWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "PitchforkHungry", provider: Provider()) { e in
            HungryWidgetView(e: e).containerBackground(for: .widget) { WidgetBackground() }
        }
        .configurationDisplayName("Feeling hungry?")
        .description("Your next meal pick. Tap for another.")
        .supportedFamilies([.systemMedium])
    }
}

struct WidgetBackground: View {
    @Environment(\.widgetRenderingMode) private var mode
    var body: some View {
        if mode == .fullColor {
            LinearGradient(colors: [Color(red: 0.0, green: 0.13, blue: 0.41), Color(red: 0.1, green: 0.36, blue: 0.72)],
                           startPoint: .topLeading, endPoint: .bottomTrailing)
        } else {
            Color.clear
        }
    }
}

struct TodayWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let e: Snapshot
    init(_ e: Snapshot) { self.e = e }

    var body: some View {
        switch family {
        case .accessoryCircular: circular
        case .accessoryRectangular: rectangular
        case .accessoryInline: inline
        case .systemLarge: LargeView(e: e)
        default: SmallView(e: e)
        }
    }

    private var circular: some View {
        Gauge(value: min(e.protein, e.proteinTarget), in: 0...e.proteinTarget) {
            Image(systemName: "fork.knife")
        } currentValueLabel: {
            Text("\(Int(e.protein.rounded()))")
        }
        .gaugeStyle(.accessoryCircularCapacity)
        .widgetURL(URL(string: "pitchfork://today"))
    }

    private var rectangular: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Points").font(.headline)
                Spacer()
                Text(paceText).font(.caption.weight(.semibold))
            }
            if let p = e.today?.points.points, let target = e.today?.points.paceTarget {
                PaceBar(points: p, paceTarget: target, height: 7).widgetAccentable()
            }
            Text(e.today?.points.runout.map { "Runs out \(Fmt.day($0))" } ?? "Lasts the semester")
                .font(.caption2)
        }
        .widgetURL(URL(string: "pitchfork://today"))
    }

    private var inline: some View {
        Label("\(Int(e.protein.rounded()))/\(Int(e.proteinTarget)) g · \(paceText)", systemImage: "fork.knife")
    }

    private var paceText: String {
        guard let gap = e.today?.points.vsPace else { return "–" }
        return gap < 0 ? "\(Int((-gap).rounded())) behind" : "\(Int(gap.rounded())) ahead"
    }
}

/// Small: the devil inside its protein ring.
struct SmallView: View {
    let e: Snapshot
    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                ProteinRing(value: e.protein, target: e.proteinTarget, width: 9)
                PixelDevil(mood: e.mood, size: 52, animated: false)
            }
            Text("\(Int(e.protein.rounded())) / \(Int(e.proteinTarget)) g")
                .font(.caption.weight(.bold).monospacedDigit()).foregroundStyle(.white)
        }
        .widgetURL(URL(string: "pitchfork://today"))
    }
}

struct ProteinRing: View {
    let value: Double
    let target: Double
    var width: CGFloat = 8
    var color: Color = Color(red: 1, green: 0.35, blue: 0.5)
    var body: some View {
        ZStack {
            Circle().stroke(color.opacity(0.25), lineWidth: width)
            Circle().trim(from: 0, to: target > 0 ? min(value / target, 1) : 0)
                .stroke(color, style: StrokeStyle(lineWidth: width, lineCap: .round))
                .rotationEffect(.degrees(-90))
        }
    }
}

/// Medium: the top pick as a graphic (its protein vs what this meal needs) + a reroll button.
struct HungryWidgetView: View {
    let e: Snapshot
    var body: some View {
        HStack(spacing: 14) {
            VStack(spacing: 8) {
                PixelDevil(mood: .happy, size: 50, animated: false)
                Button(intent: RerollIntent()) {
                    Label("Another", systemImage: "arrow.triangle.2.circlepath").font(.caption.weight(.bold))
                }
                .tint(.orange)
            }
            if let p = e.pick {
                VStack(alignment: .leading, spacing: 5) {
                    Text("FEELING HUNGRY?").font(.caption2.weight(.heavy)).foregroundStyle(.orange)
                    Text(p.title).font(.headline).lineLimit(2).foregroundStyle(.white)
                    Text(p.vendor).font(.caption).foregroundStyle(.white.opacity(0.75))
                    let need = e.next?.perMealTarget.proteinG ?? p.proteinG
                    MiniBar(value: p.proteinG, max: max(need, p.proteinG), color: Color(red: 1, green: 0.35, blue: 0.5))
                    HStack {
                        Text("\(Int(p.proteinG.rounded())) g protein")
                        Spacer()
                        Text(String(format: "%.2f pts", p.pointsCost))
                    }
                    .font(.caption2.weight(.semibold).monospacedDigit()).foregroundStyle(.white)
                }
            } else {
                Text("Open Pitchfork to cook up a pick.").font(.subheadline).foregroundStyle(.white)
            }
        }
        .widgetURL(URL(string: "pitchfork://hungry"))
    }
}

struct MiniBar: View {
    let value: Double
    let max: Double
    let color: Color
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(.white.opacity(0.2))
                Capsule().fill(color).frame(width: g.size.width * (max > 0 ? min(value / max, 1) : 0))
            }
        }
        .frame(height: 7)
    }
}

/// Large: mini Today — rings, pace bar, top pick, today's meals as dots.
struct LargeView: View {
    let e: Snapshot
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                PixelDevil(mood: e.mood, size: 36, animated: false)
                Text("Today").font(.title2.bold())
                Spacer()
                HStack(spacing: 4) {
                    ForEach(e.today?.meals ?? [], id: \.id) { _ in Circle().fill(.orange).frame(width: 8, height: 8) }
                }
            }
            HStack(spacing: 18) {
                ring(e.protein, e.proteinTarget, "protein", Color(red: 1, green: 0.35, blue: 0.5))
                if let c = e.today?.eaten.calories, let t = e.today?.targets.calories {
                    ring(c, Double(t), "calories", .orange)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(e.today?.proteinHitDays7 ?? 0) of 7").font(.title3.bold())
                    Text("days protein hit").font(.caption2).opacity(0.8)
                }
            }
            if let pts = e.today?.points, let p = pts.points, let target = pts.paceTarget {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("Plan \(pts.mealPlan ?? "") pace").font(.caption.weight(.semibold))
                        Spacer()
                        Text(pts.vsPace.map { $0 < 0 ? String(format: "%.0f behind", -$0) : String(format: "%.0f ahead", $0) } ?? "")
                            .font(.caption.weight(.semibold).monospacedDigit())
                    }
                    PaceBar(points: p, paceTarget: target, height: 9)
                    Text(pts.runout.map { "Runs out \(Fmt.day($0))" } ?? "Lasts the semester")
                        .font(.caption2).foregroundStyle(pts.runout == nil ? .green : .orange)
                }
            }
            if let pick = e.pick {
                HStack {
                    Image(systemName: "star.fill").foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(pick.title).font(.subheadline.weight(.semibold)).lineLimit(1)
                        Text("\(pick.vendor) · \(Int(pick.proteinG.rounded())) g · \(String(format: "%.2f", pick.pointsCost)) pts")
                            .font(.caption2).opacity(0.8)
                    }
                }
            }
        }
        .foregroundStyle(.white)
        .widgetURL(URL(string: "pitchfork://today"))
    }

    private func ring(_ v: Double, _ t: Double, _ label: String, _ c: Color) -> some View {
        VStack(spacing: 4) {
            ZStack {
                ProteinRing(value: v, target: t, width: 8, color: c)
                Text("\(Int(v.rounded()))").font(.caption.weight(.bold).monospacedDigit())
            }
            .frame(width: 58, height: 58)
            Text(label).font(.caption2).opacity(0.8)
        }
    }
}
