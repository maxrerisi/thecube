import SwiftUI
import UIKit

/// "Feeling hungry?" (our "I'm feeling lucky"): hold to cook -> the devil stirs, haptics ramp up ->
/// the lid pops, a pick card flips over and its macros count up -> swipe left to reroll, right for
/// "Let's go". No spinner: picks are fetched while you hold. Picks come from /next-meal (all three
/// goals, interleaved), so every number is the optimizer's.
struct HungryView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss

    enum Phase { case idle, revealed, going }
    @State private var phase: Phase = .idle
    @State private var options: [Pick] = []
    @State private var index = 0
    @State private var loadError: String?

    @State private var pressStart: Date?
    @State private var progress = 0.0
    @State private var cooked = false
    @State private var lidPopped = false
    @State private var hapticTask: Task<Void, Never>?

    @State private var flip = 90.0
    @State private var drag = CGSize.zero
    @State private var protein = 0.0
    @State private var points = 0.0
    @State private var calories = 0.0

    private let holdSeconds = 1.0
    private var pick: Pick? { options.isEmpty ? nil : options[index % options.count] }

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 1, green: 0.62, blue: 0.3), Color(red: 0.86, green: 0.2, blue: 0.27)],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
            VStack(spacing: 20) {
                header
                switch phase {
                case .idle: idle
                case .revealed: revealed
                case .going: going
                }
            }
            .padding()
        }
        .foregroundStyle(.white)
        .task { await loadOptions() }
        .onChange(of: options.count) { if cooked && phase == .idle && !options.isEmpty { reveal() } }
        .onDisappear { hapticTask?.cancel() }
    }

    private var header: some View {
        HStack {
            Button { dismiss() } label: {
                Image(systemName: "xmark").font(.headline).padding(10).background(.white.opacity(0.2), in: Circle())
            }
            .accessibilityLabel("Close")
            Spacer()
            Text("Feeling hungry?").font(.headline)
            Spacer()
            Color.clear.frame(width: 40, height: 40)
        }
    }

    // MARK: idle: hold to cook

    private var idle: some View {
        VStack(spacing: 28) {
            Spacer()
            KitchenScene(mood: app.mood, pressStart: pressStart, holdSeconds: holdSeconds, lidPopped: lidPopped)
                .frame(height: 260)
            Text(pressStart == nil ? "Tap or hold the pan to cook" : "Cooking...")
                .font(.title3.weight(.semibold))
            ZStack {
                Circle().stroke(.white.opacity(0.25), lineWidth: 10)
                Circle().trim(from: 0, to: progress)
                    .stroke(.white, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                Image(systemName: "frying.pan.fill").font(.system(size: 40))
            }
            .frame(width: 120, height: 120)
            .scaleEffect(pressStart == nil ? 1 : 0.92)
            .animation(.spring(response: 0.3), value: pressStart)
            .contentShape(Circle())
            .onLongPressGesture(minimumDuration: holdSeconds, maximumDistance: 80) {
                cookDone()
            } onPressingChanged: { pressing in
                pressingChanged(pressing)
            }
            .accessibilityAddTraits(.isButton)
            .accessibilityLabel("Hold to cook")
            .accessibilityAction { cookDone() }
            if let e = loadError { Text(e).font(.footnote).multilineTextAlignment(.center) }
            Spacer()
        }
    }

    private func pressingChanged(_ pressing: Bool) {
        hapticTask?.cancel()
        guard phase == .idle else { return }
        if pressing {
            let start = Date()
            pressStart = start
            withAnimation(.linear(duration: holdSeconds)) { progress = 1 }
            hapticTask = Task { @MainActor in
                let gen = UIImpactFeedbackGenerator(style: .rigid)
                gen.prepare()
                while !Task.isCancelled {
                    let k = min(Date().timeIntervalSince(start) / holdSeconds, 1)
                    gen.impactOccurred(intensity: 0.3 + 0.7 * k)
                    try? await Task.sleep(for: .milliseconds(Int(170 - 120 * k)))
                }
            }
        } else if !cooked {
            // A tap or early release still cooks: finish the stir on its own (people didn't
            // know to hold). Holding is just the fun way, with the haptics.
            let held = Date().timeIntervalSince(pressStart ?? .now)
            let left = max(0.6, holdSeconds - held)
            if pressStart == nil { pressStart = .now }
            withAnimation(.linear(duration: left)) { progress = 1 }
            DispatchQueue.main.asyncAfter(deadline: .now() + left) { if !cooked { cookDone() } }
        }
    }

    private func cookDone() {
        hapticTask?.cancel()
        cooked = true
        if !options.isEmpty { reveal() }
    }

    private func reveal() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        withAnimation(.spring(response: 0.45, dampingFraction: 0.5)) { lidPopped = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            withAnimation(.smooth) { phase = .revealed }
            showCard()
        }
    }

    // MARK: revealed: the card

    private var revealed: some View {
        VStack(spacing: 18) {
            Spacer(minLength: 0)
            if let p = pick {
                card(p)
                    .rotation3DEffect(.degrees(flip), axis: (0, 1, 0))
                    .rotationEffect(.degrees(drag.width / 18))
                    .offset(drag)
                    .gesture(DragGesture()
                        .onChanged { drag = $0.translation }
                        .onEnded { v in
                            if v.translation.width < -110 { reroll() }
                            else if v.translation.width > 110 { accept() }
                            else { withAnimation(.spring) { drag = .zero } }
                        })
            }
            HStack {
                Button { reroll() } label: { Label("Reroll", systemImage: "arrow.uturn.left") }
                Spacer()
                Button { accept() } label: { Label("Let's go", systemImage: "arrow.right").labelStyle(TrailingIcon()) }
            }
            .font(.headline)
            .padding(.horizontal, 8)
            Text("Swipe left to reroll, right to go").font(.caption).opacity(0.8)
            Spacer(minLength: 0)
        }
    }

    private func card(_ p: Pick) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                PixelDevil(mood: .happy, size: 34)
                Text(p.vendor.uppercased()).font(.caption.weight(.bold)).foregroundStyle(.secondary)
                Spacer()
                if let o = p.opensAt { Text("Opens \(Fmt.time(o))").font(.caption).foregroundStyle(.orange) }
            }
            Text(p.title).font(.title2.bold()).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 0) {
                bigStat(CountUp(value: protein) { "\(Int($0.rounded())) g" }, "protein")
                bigStat(CountUp(value: points) { String(format: "%.2f", $0) }, "points")
                if p.calories != nil { bigStat(CountUp(value: calories) { "\(Int($0.rounded()))" }, "calories") }
            }
            Text(p.components.map(\.name).joined(separator: " · "))
                .font(.caption).foregroundStyle(.secondary).lineLimit(3)
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .foregroundStyle(Color.primary)   // Color.primary = label color (not the parent's white)
        .background(.background, in: RoundedRectangle(cornerRadius: 28))
        .shadow(color: .black.opacity(0.25), radius: 20, y: 10)
        .overlay(alignment: .topLeading) { swipeStamp }
    }

    @ViewBuilder private var swipeStamp: some View {
        if drag.width > 40 {
            stamp("LET'S GO", .green).rotationEffect(.degrees(-12)).padding(18).opacity(min(drag.width / 110, 1))
        } else if drag.width < -40 {
            stamp("REROLL", .orange).rotationEffect(.degrees(12)).padding(18).opacity(min(-drag.width / 110, 1))
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
    }

    private func stamp(_ s: String, _ c: Color) -> some View {
        Text(s).font(.headline.weight(.black)).foregroundStyle(c)
            .padding(.horizontal, 10).padding(.vertical, 4)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(c, lineWidth: 3))
    }

    private func bigStat(_ v: CountUp, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            v.font(.title.monospacedDigit().weight(.heavy))
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func showCard() {
        guard let p = pick else { return }
        protein = 0; points = 0; calories = 0; flip = 90; drag = .zero
        withAnimation(.spring(response: 0.6, dampingFraction: 0.7).delay(0.1)) { flip = 0 }
        withAnimation(.easeOut(duration: 0.9).delay(0.3)) {
            protein = p.proteinG; points = p.pointsCost; calories = p.calories ?? 0
        }
    }

    private func reroll() {
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        withAnimation(.easeIn(duration: 0.2)) { drag = CGSize(width: -600, height: 40) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.22) {
            index += 1
            showCard()
        }
    }

    private func accept() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        withAnimation(.easeIn(duration: 0.2)) { drag = CGSize(width: 600, height: -40) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.22) { withAnimation(.spring) { phase = .going } }
    }

    // MARK: going

    private var going: some View {
        VStack(spacing: 18) {
            Spacer()
            PixelDevil(mood: .happy, size: 130)
            Text("Let's go!").font(.largeTitle.bold())
            if let p = pick {
                Text("\(p.title) at \(p.vendor).").font(.title3.weight(.semibold)).multilineTextAlignment(.center)
            }
            Text("Pay with your DukeCard, forward the receipt, and it logs itself.")
                .multilineTextAlignment(.center).opacity(0.9)
            Spacer()
            Button { dismiss() } label: {
                Text("Done").font(.headline).frame(maxWidth: .infinity).padding()
                    .background(.white, in: Capsule()).foregroundStyle(Color(red: 0.86, green: 0.2, blue: 0.27))
            }
        }
    }

    // MARK: data

    private func loadOptions() async {
        let api = APIClient.shared
        let id = app.userId
        async let a = try? api.nextMeal(userId: id, bias: .balanced)
        async let b = try? api.nextMeal(userId: id, bias: .protein)
        async let c = try? api.nextMeal(userId: id, bias: .cheap)
        let lists = [await a, await b, await c].compactMap { $0?.picks }
        var seen = Set<String>(), out: [Pick] = []
        for i in 0..<3 {   // each goal's #1 first, then the #2s, ...
            for l in lists where i < l.count && seen.insert(l[i].id).inserted { out.append(l[i]) }
        }
        if out.isEmpty { loadError = "Nothing open right now matches your settings." }
        options = out
    }
}

/// A number that counts up when it changes inside an animation.
struct CountUp: View, Animatable {
    var value: Double
    var format: (Double) -> String
    var animatableData: Double {
        get { value }
        set { value = newValue }
    }
    var body: some View { Text(format(value)) }
}

struct TrailingIcon: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) { configuration.title; configuration.icon }
    }
}

/// The devil stirring a pot. Stirring speeds up and the lid rattles harder the longer you hold.
struct KitchenScene: View {
    let mood: DevilMood
    let pressStart: Date?
    let holdSeconds: Double
    let lidPopped: Bool

    var body: some View {
        TimelineView(.animation) { ctx in
            let t = ctx.date.timeIntervalSinceReferenceDate
            let k = pressStart.map { min(ctx.date.timeIntervalSince($0) / holdSeconds, 1) } ?? 0
            let speed = 2.0 + 14 * k
            HStack(alignment: .bottom, spacing: -6) {
                PixelDevil(mood: k > 0 ? .happy : mood, size: 96)
                    .rotationEffect(.degrees(sin(t * speed) * (4 + 6 * k)), anchor: .bottom)
                ZStack(alignment: .bottom) {
                    // steam
                    ForEach(0..<4, id: \.self) { i in
                        let ph = (t * (0.5 + 1.5 * k) + Double(i) / 4).truncatingRemainder(dividingBy: 1)
                        Circle().fill(.white.opacity((1 - ph) * (0.35 + 0.4 * k)))
                            .frame(width: 18 + 18 * ph, height: 18 + 18 * ph)
                            .offset(x: CGFloat(i - 2) * 22 + sin(t * 2 + Double(i)) * 6, y: -110 - 90 * ph)
                    }
                    // spoon
                    Capsule().fill(Color(red: 0.55, green: 0.35, blue: 0.2))
                        .frame(width: 8, height: 90)
                        .rotationEffect(.degrees(-25 + sin(t * speed) * 22), anchor: .bottom)
                        .offset(x: -40, y: -70)
                    // pot
                    VStack(spacing: 0) {
                        lid
                            .rotationEffect(.degrees(lidPopped ? -35 : sin(t * 40) * 5 * k))
                            .offset(x: lidPopped ? 80 : 0, y: lidPopped ? -150 : -4 * k * abs(sin(t * 30)))
                            .opacity(lidPopped ? 0 : 1)
                        ZStack {
                            UnevenRoundedRectangle(topLeadingRadius: 6, bottomLeadingRadius: 34,
                                                   bottomTrailingRadius: 34, topTrailingRadius: 6)
                                .fill(Color(white: 0.18))
                            Capsule().fill(.white.opacity(0.12)).frame(width: 110, height: 8).offset(y: -18)
                        }
                        .frame(width: 170, height: 100)
                        .overlay(alignment: .leading) { handle.offset(x: -18) }
                        .overlay(alignment: .trailing) { handle.offset(x: 18) }
                    }
                }
            }
        }
    }

    private var lid: some View {
        VStack(spacing: -2) {
            Circle().fill(Color(white: 0.3)).frame(width: 20, height: 20)
            Capsule().fill(Color(white: 0.3)).frame(width: 184, height: 18)
        }
    }

    private var handle: some View {
        Capsule().fill(Color(white: 0.25)).frame(width: 30, height: 12)
    }
}
