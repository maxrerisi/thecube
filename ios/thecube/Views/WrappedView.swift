import SwiftUI

/// Semester-so-far recap, story style (GET /wrapped). Tap right/left to move, progress bars on
/// top, a moving mesh gradient per slide, and a share card at the end. Numbers come from the
/// server's code; captions from the coach (number-checked) or a template.
struct WrappedView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var data: Wrapped?
    @State private var error: String?
    @State private var i = 0
    @State private var shown = false

    private var slides: [WrappedSlide] { data?.slides ?? [] }

    var body: some View {
        ZStack {
            WrappedBackground(palette: WrappedBackground.palettes[i % WrappedBackground.palettes.count])
                .ignoresSafeArea()
                .animation(.easeInOut(duration: 0.8), value: i)
            if let s = slides[safe: i] {
                slideView(s)
                    .contentShape(Rectangle())
                    .onTapGesture { location in step(location.x < 130 ? -1 : 1) }
            } else {
                VStack(spacing: 16) {
                    PixelDevil(mood: error == nil ? .happy : .sleepy, size: 90)
                    Text(error ?? "Wrapping up your semester...").font(.headline).multilineTextAlignment(.center)
                }
                .padding()
            }
            VStack { topBar; Spacer() }
        }
        .foregroundStyle(.white)
        .sensoryFeedback(.selection, trigger: i)
        .task { await load() }
    }

    private var topBar: some View {
        VStack(spacing: 12) {
            HStack(spacing: 4) {
                ForEach(slides.indices, id: \.self) { k in
                    Capsule().fill(.white.opacity(k <= i ? 0.95 : 0.3)).frame(height: 3)
                }
            }
            HStack {
                Text(data.map { "\($0.term) Wrapped" } ?? "Wrapped").font(.subheadline.weight(.semibold))
                Spacer()
                Button { dismiss() } label: { Image(systemName: "xmark").font(.headline).padding(8) }
                    .accessibilityLabel("Close")
            }
        }
        .padding(.horizontal)
        .padding(.top, 8)
    }

    @ViewBuilder private func slideView(_ s: WrappedSlide) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Spacer()
            if s.id == "share", let d = data {
                ShareCard(data: d)
                    .scaleEffect(shown ? 1 : 0.8).opacity(shown ? 1 : 0)
                shareButton(d)
            } else {
                Text(s.title.uppercased())
                    .font(.subheadline.weight(.heavy)).tracking(2).opacity(0.85)
                    .offset(y: shown ? 0 : 20).opacity(shown ? 1 : 0)
                Text(s.big)
                    .font(.system(size: s.big.count > 12 ? 48 : 84, weight: .black, design: .rounded))
                    .minimumScaleFactor(0.4).lineLimit(3)
                    .contentTransition(.numericText())
                    .scaleEffect(shown ? 1 : 0.6, anchor: .leading).opacity(shown ? 1 : 0)
                Text(s.unit).font(.title3.weight(.semibold)).opacity(shown ? 0.9 : 0)
                Text(s.caption).font(.title2.weight(.medium)).fixedSize(horizontal: false, vertical: true)
                    .offset(y: shown ? 0 : 30).opacity(shown ? 1 : 0)
                if s.id == "intro" || s.id == "personality" {
                    PixelDevil(mood: s.id == "intro" ? .happy : app.mood, size: 80).padding(.top, 8)
                        .opacity(shown ? 1 : 0)
                }
            }
            Spacer()
            Text(i < slides.count - 1 ? "Tap to continue" : "Tap left to go back")
                .font(.caption).opacity(0.7).frame(maxWidth: .infinity)
        }
        .padding(28)
        .id(s.id)
        .onAppear {
            shown = false
            withAnimation(.spring(response: 0.6, dampingFraction: 0.7).delay(0.05)) { shown = true }
        }
    }

    private func shareButton(_ d: Wrapped) -> some View {
        let image = ImageRenderer(content: ShareCard(data: d).frame(width: 360).environment(\.colorScheme, .dark))
        image.scale = 3
        return Group {
            if let ui = image.uiImage {
                let img = Image(uiImage: ui)
                ShareLink(item: img, preview: SharePreview("My \(d.term) Wrapped", image: img)) {
                    Label("Share", systemImage: "square.and.arrow.up")
                        .font(.headline).frame(maxWidth: .infinity).padding()
                        .background(.white, in: Capsule()).foregroundStyle(.black)
                }
            }
        }
    }

    private func step(_ d: Int) {
        let n = i + d
        if n >= 0 && n < slides.count { i = n }
    }

    private func load() async {
        do { data = try await APIClient.shared.wrapped(userId: app.userId) }
        catch APIError.http(404, _) { error = "No meals yet this term. Forward a receipt to get started." }
        catch { self.error = error.localizedDescription }
    }
}

/// The last slide, also rendered to an image for sharing.
struct ShareCard: View {
    let data: Wrapped

    private func big(_ id: String) -> WrappedSlide? { data.slides.first { $0.id == id } }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                PixelDevil(mood: .happy, size: 44, animated: false)
                VStack(alignment: .leading) {
                    Text("PITCHFORK").font(.caption.weight(.heavy)).tracking(2).opacity(0.8)
                    Text("\(data.term) Wrapped").font(.title3.bold())
                }
            }
            Divider().overlay(.white.opacity(0.4))
            row("Meals", big("totals")?.big)
            row("Top spot", big("top_spot")?.big)
            row("Signature", big("signature")?.big)
            row("Protein", big("protein").map { "\($0.big) g" })
            row("Hungriest hour", big("peak_hour")?.big)
            row("Personality", big("personality")?.big)
        }
        .padding(22)
        .foregroundStyle(.white)
        .background(
            LinearGradient(colors: [Color(red: 0.0, green: 0.13, blue: 0.41), Color(red: 0.36, green: 0.16, blue: 0.62)],
                           startPoint: .topLeading, endPoint: .bottomTrailing),
            in: RoundedRectangle(cornerRadius: 28))
    }

    private func row(_ label: String, _ value: String?) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).font(.subheadline).opacity(0.8)
            Spacer()
            Text(value ?? "–").font(.headline).multilineTextAlignment(.trailing)
        }
    }
}

/// A slowly moving 3×3 mesh gradient.
struct WrappedBackground: View {
    let palette: [Color]

    var body: some View {
        TimelineView(.animation) { ctx in
            let t = ctx.date.timeIntervalSinceReferenceDate
            let w = Float(sin(t * 0.6)) * 0.15, v = Float(cos(t * 0.45)) * 0.15
            MeshGradient(width: 3, height: 3, points: [
                [0, 0], [0.5, 0], [1, 0],
                [0, 0.5], [0.5 + w, 0.5 + v], [1, 0.5],
                [0, 1], [0.5, 1], [1, 1],
            ], colors: palette)
        }
    }

    static let palettes: [[Color]] = {
        func p(_ hues: [Double]) -> [Color] { hues.map { Color(hue: $0, saturation: 0.75, brightness: 0.75) } }
        return [
            p([0.62, 0.66, 0.72, 0.60, 0.68, 0.76, 0.58, 0.64, 0.70]),   // intro: Duke blues
            p([0.95, 0.98, 0.02, 0.92, 0.97, 0.05, 0.90, 0.94, 0.99]),   // totals: reds
            p([0.08, 0.10, 0.13, 0.06, 0.09, 0.12, 0.04, 0.07, 0.11]),   // top spot: orange
            p([0.80, 0.83, 0.87, 0.78, 0.82, 0.86, 0.76, 0.80, 0.84]),   // signature: purple
            p([0.40, 0.44, 0.48, 0.38, 0.42, 0.46, 0.36, 0.40, 0.44]),   // protein: green
            p([0.52, 0.55, 0.58, 0.50, 0.54, 0.57, 0.48, 0.52, 0.56]),   // peak hour: teal
            p([0.02, 0.06, 0.95, 0.04, 0.08, 0.92, 0.00, 0.05, 0.90]),   // personality: hot
            p([0.64, 0.70, 0.78, 0.66, 0.72, 0.80, 0.68, 0.74, 0.82]),   // share
        ]
    }()
}

extension Array {
    subscript(safe i: Int) -> Element? { indices.contains(i) ? self[i] : nil }
}
