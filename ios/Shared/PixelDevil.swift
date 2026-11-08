import SwiftUI

/// The Pitchfork mascot: a 16×18 pixel Blue Devil with a pitchfork drawn from strings (no image assets), shared by
/// the app and the widgets. Its mood is picked by code from Today's numbers.
enum DevilMood: String, CaseIterable {
    case happy      // protein target hit
    case sweating   // behind on points
    case sleepy     // nothing eaten yet today
    case neutral

    static func from(meals: Int, protein: Double, target: Double, vsPace: Double?, runout: String?) -> DevilMood {
        if meals == 0 { return .sleepy }
        if target > 0 && protein >= target { return .happy }
        if (vsPace ?? 0) < 0 || runout != nil { return .sweating }
        return .neutral
    }

    static func from(_ t: Today) -> DevilMood {
        from(meals: t.meals.count, protein: t.eaten.proteinG, target: Double(t.targets.proteinG),
             vsPace: t.points.vsPace, runout: t.points.runout)
    }

    /// What the devil says when tapped (fixed words; no numbers).
    var line: String {
        switch self {
        case .happy: "Protein target hit. I'm proud of us."
        case .sweating: "We're spending faster than an even pace. Let's eat smart."
        case .sleepy: "Nothing eaten yet today... breakfast?"
        case .neutral: "On track. What are we eating next?"
        }
    }
}

struct PixelDevil: View {
    var mood: DevilMood = .neutral
    /// Width in points; height follows the grid's aspect.
    var size: CGFloat = 32
    var animated = true

    var body: some View {
        Group {
            if animated {
                TimelineView(.periodic(from: .now, by: 0.2)) { ctx in
                    let tick = Int(ctx.date.timeIntervalSinceReferenceDate * 5)
                    sprite(blink: tick % 20 == 0, bob: (tick / 3) % 2 == 0)
                }
            } else {
                sprite(blink: false, bob: false)
            }
        }
        // Decorative: never the hit target. An animating TimelineView inside a Button re-renders
        // every 0.2 s and swallowed taps (the Feeling hungry row and the toolbar devil).
        .allowsHitTesting(false)
    }

    private func sprite(blink: Bool, bob: Bool) -> some View {
        let rows = Self.rows(mood, blink: blink)
        let cols = rows.first?.count ?? 1
        return Canvas { ctx, sz in
            let cell = sz.width / CGFloat(cols)
            for (y, row) in rows.enumerated() {
                for (x, ch) in row.enumerated() {
                    guard let c = Self.palette[ch] else { continue }
                    ctx.fill(Path(CGRect(x: CGFloat(x) * cell, y: CGFloat(y) * cell, width: cell + 0.5, height: cell + 0.5)),
                             with: .color(c))
                }
            }
        }
        .frame(width: size, height: size * CGFloat(rows.count) / CGFloat(cols))
        .offset(y: bob ? -size / 32 : 0)
        .overlay(alignment: .topLeading) {
            if mood == .sleepy {
                Text("z").font(.system(size: size * 0.3, weight: .heavy, design: .rounded))
                    .foregroundStyle(.secondary).offset(x: -size * 0.1, y: bob ? -size * 0.2 : -size * 0.1)
            }
        }
        .accessibilityLabel("Pitchfork devil, \(mood.rawValue)")
    }

    static let palette: [Character: Color] = [
        "O": Color(red: 0.04, green: 0.10, blue: 0.23),   // outline
        "B": Color(red: 0.12, green: 0.37, blue: 0.75),   // Duke-ish blue body
        "L": Color(red: 0.36, green: 0.56, blue: 0.88),   // highlight
        "H": Color(red: 0.95, green: 0.95, blue: 0.95),   // horns
        "h": Color(red: 0.79, green: 0.80, blue: 0.84),   // horn shade
        "W": .white,
        "T": .white,                                      // tooth
        "K": Color(red: 0.05, green: 0.05, blue: 0.08),
        "P": Color(red: 1.0, green: 0.56, blue: 0.64),    // cheeks
        "M": Color(red: 0.23, green: 0.04, blue: 0.10),   // mouth
        "S": Color(red: 0.56, green: 0.83, blue: 1.0),    // sweat
        "F": Color(red: 0.79, green: 0.64, blue: 0.15),   // fork tines
        "f": Color(red: 0.54, green: 0.43, blue: 0.06),   // fork shaft
    ]

    /// 16×18 devil holding a pitchfork (design/devils/options.png, "B2_fork"). Mood swaps the
    /// eye rows (5–6) and mouth rows (8–9).
    static let base = [
        "..O........O....",
        ".OHO......OHO...",
        ".OHhOOOOOOhHOF.F",
        "..OBBBBBBBBO.FFF",
        ".OBLLBBBBBBBO.f.",
        ".OBLWWBBBWWBO.f.",
        ".OBBWKBBBKWBO.f.",
        ".OPBBBBBBBBPO.f.",
        ".OBBBMMMMBBBO.f.",
        "..OBBBTTBBBO..f.",
        "...OOOOOOOO...f.",
        "..OBBBBBBBBOOOf.",
        ".OBOBLBBBBOBBBf.",
        ".OBOBBBBBBOOOOf.",
        "..OOBBBBBBO...f.",
        "...OBBBBBBO...f.",
        "...OBBOOBBO.....",
        "...OOO..OOO.....",
    ]

    static func rows(_ mood: DevilMood, blink: Bool) -> [String] {
        var r = base
        let closed = (".OBLBBBBBBBBO.f.", ".OBBKKBBBKKBO.f.")
        switch mood {
        case .happy:
            (r[5], r[6]) = (".OBLBKBBBKBBO.f.", ".OBBKBKBKBKBO.f.")
            (r[8], r[9]) = (".OBBMBBBBBMBO.f.", "..OBBMMMMBBO..f.")
        case .sweating:
            r[3] = "S.OBBBBBBBBO.FFF"; r[4] = "SOBLLBBBBBBBO.f."
            (r[8], r[9]) = (".OBBMBMMBMBBO.f.", "..OBBBBBBBBO..f.")
            if blink { (r[5], r[6]) = closed }
        case .sleepy:
            (r[5], r[6]) = closed
            (r[8], r[9]) = (".OBBBBMMBBBBO.f.", "..OBBBBBBBBO..f.")
        case .neutral:
            if blink { (r[5], r[6]) = closed }
        }
        return r
    }
}

/// Points vs an even pace as a line: fill = points / on-pace balance, tick at 100% = on pace.
struct PaceBar: View {
    let points: Double
    let paceTarget: Double
    var height: CGFloat = 8

    private var ratio: Double { paceTarget > 0 ? points / paceTarget : 1 }

    var body: some View {
        GeometryReader { g in
            let w = g.size.width
            let scale = max(ratio, 1.0) // keep the pace tick visible when ahead
            ZStack(alignment: .leading) {
                Capsule().fill(.quaternary)
                Capsule().fill(ratio < 1 ? Color.orange : Color.green)
                    .frame(width: max(height, w * min(ratio / scale, 1)))
                Rectangle().fill(.primary).frame(width: 2, height: height + 6)
                    .offset(x: w * (1 / scale) - 1)
            }
        }
        .frame(height: height)
    }
}
