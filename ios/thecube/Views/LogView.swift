import SwiftUI

/// SPEC 13 Log: vendor list -> menu by course -> item rows with macros and trait icons ->
/// tap for full label. Add items, enter points paid, save. (Receipts arrive by email forward.)
struct LogView: View {
    @Environment(AppState.self) private var app
    @State private var vm = LogViewModel()

    var body: some View {
        NavigationStack {
            List {
                if let e = vm.error { Section { ErrorBanner(message: e) } }
                Section("Log a meal") {
                    ForEach(vm.vendors.filter(\.hasNutrition)) { v in
                        NavigationLink(value: v) { VendorRow(vendor: v) }
                    }
                }
                let other = vm.vendors.filter { !$0.hasNutrition }
                if !other.isEmpty {
                    Section {
                        ForEach(other) { VendorRow(vendor: $0).foregroundStyle(.secondary) }
                    } header: {
                        Text("No nutrition data")
                    } footer: {
                        Text("These aren't on Duke NetNutrition. Receipts from them still count toward points.")
                    }
                }
            }
            .navigationTitle("Log")
            .toolbar { DevilToolbar() }
            .navigationDestination(for: Vendor.self) { MenuView(vendor: $0) }
            .task(id: app.dataVersion) { await vm.load() }
            .refreshable { await vm.load() }
        }
    }
}

struct VendorRow: View {
    let vendor: Vendor

    var body: some View {
        HStack {
            VStack(alignment: .leading) {
                Text(vendor.name)
                if let b = vendor.building { Text(b).font(.caption).foregroundStyle(.secondary) }
            }
            Spacer()
            Text(vendor.openNow ? "Open" : "Closed")
                .font(.caption)
                .foregroundStyle(vendor.openNow ? .green : .secondary)
        }
    }
}

struct MenuView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var vm: MenuViewModel
    @State private var detail: MenuItem?
    @State private var showCart = false

    init(vendor: Vendor) { _vm = State(initialValue: MenuViewModel(vendor: vendor)) }

    var body: some View {
        List {
            if let e = vm.error { Section { ErrorBanner(message: e) } }
            if let menu = vm.menu {
                ForEach(menu.courses) { course in
                    Section(course.name) {
                        ForEach(course.items) { item in
                            MenuItemRow(item: item) { portion in vm.add(item, portion: portion) }
                                .contentShape(Rectangle())
                                .onTapGesture { detail = item }
                        }
                    }
                }
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
        }
        .navigationTitle(vm.vendor.name)
        .task { await vm.load() }
        .sheet(item: $detail) { ItemDetailView(item: $0) }
        .sheet(isPresented: $showCart) {
            CartView(vm: vm) {
                showCart = false
                app.dataChanged()
                dismiss()
            }
        }
        .safeAreaInset(edge: .bottom) {
            if !vm.cart.isEmpty {
                Button { showCart = true } label: {
                    HStack {
                        Text("\(vm.cart.count) item\(vm.cart.count == 1 ? "" : "s")")
                        Spacer()
                        Text("\(Fmt.g(vm.totals.proteinG)) protein")
                        Text("Review").bold()
                    }
                    .padding()
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .padding(.horizontal)
            }
        }
    }
}

struct MenuItemRow: View {
    let item: MenuItem
    let onAdd: (Portion) -> Void
    @State private var portion: Portion?

    private var selected: Portion? { portion ?? item.defaultPortion }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(item.name).font(.body)
                Spacer()
                if let p = item.knownPrice { Text(Fmt.money(p.price)).font(.caption).foregroundStyle(.secondary) }
                Button {
                    if let s = selected { onAdd(s) }
                } label: { Image(systemName: "plus.circle.fill").font(.title3) }
                .buttonStyle(.borderless)
                .accessibilityLabel("Add \(item.name)")
            }
            if !item.diets.isEmpty || !item.allergens.isEmpty {
                HStack(spacing: 4) {
                    ForEach(item.diets, id: \.self) { TraitChip(text: $0, diet: true) }
                    ForEach(item.allergens, id: \.self) { TraitChip(text: $0) }
                }
            }
            HStack {
                if item.portions.count > 1 {
                    Picker("Portion", selection: Binding(get: { selected }, set: { portion = $0 })) {
                        ForEach(item.portions) { Text($0.name).tag(Optional($0)) }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .font(.caption)
                } else if let p = selected {
                    Text(p.name).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if let p = selected {
                    Text("\(Fmt.g(p.proteinG)) · \(Fmt.cal(p.calories))")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
        }
    }
}

struct ItemDetailView: View {
    let item: MenuItem

    var body: some View {
        NavigationStack {
            List {
                ForEach(item.portions) { p in
                    Section(p.name + (p.grams.map { " (\(Int($0)) g)" } ?? "")) {
                        LabeledContent("Calories", value: Fmt.cal(p.calories))
                        LabeledContent("Protein", value: Fmt.g(p.proteinG))
                        LabeledContent("Carbohydrate", value: Fmt.g(p.carbsG))
                        LabeledContent("Fat", value: Fmt.g(p.fatG))
                        LabeledContent("Fiber", value: Fmt.g(p.fiberG))
                        LabeledContent("Sugars", value: Fmt.g(p.sugarG))
                        LabeledContent("Sodium", value: p.sodiumMg.map { "\(Int($0)) mg" } ?? "–")
                    }
                }
                if !item.diets.isEmpty || !item.allergens.isEmpty {
                    Section("Traits") {
                        HStack(spacing: 4) {
                            ForEach(item.diets, id: \.self) { TraitChip(text: $0, diet: true) }
                            ForEach(item.allergens, id: \.self) { TraitChip(text: $0) }
                        }
                    }
                }
                if let ing = item.ingredients {
                    Section("Ingredients") { Text(ing).font(.caption) }
                }
                if let p = item.knownPrice {
                    Section("Price") { LabeledContent(p.label, value: Fmt.money(p.price)) }
                }
            }
            .navigationTitle(item.name)
            .navigationBarTitleDisplayMode(.inline)
        }
        .presentationDetents([.medium, .large])
    }
}

struct CartView: View {
    @Bindable var vm: MenuViewModel
    let onSaved: () -> Void
    @Environment(AppState.self) private var app

    var body: some View {
        NavigationStack {
            Form {
                ForEach($vm.cart) { $line in
                    Section(line.item.name) {
                        LabeledContent("Portion", value: line.portion.name)
                        Stepper("Servings: \(line.servings, specifier: "%g")", value: $line.servings, in: 0.5...5, step: 0.5)
                        LabeledContent("Protein", value: Fmt.g((line.portion.proteinG ?? 0) * line.servings))
                    }
                }
                .onDelete { vm.cart.remove(atOffsets: $0) }
                Section {
                    LabeledContent("Protein", value: Fmt.g(vm.totals.proteinG))
                    LabeledContent("Calories", value: Fmt.cal(vm.totals.calories))
                    TextField(vm.subtotal > 0 ? "Points paid (est. \(Fmt.pts(vm.defaultPoints)))" : "Points paid (e.g. 12.85)",
                              text: $vm.pointsPaid)
                        .keyboardType(.decimalPad)
                } header: {
                    Text("Total")
                } footer: {
                    Text(vm.subtotal > 0 ? "Leave blank to use the receipt prices we know." : "Enter what this meal cost so your points budget stays right.")
                }
                if let e = vm.error { Section { ErrorBanner(message: e) } }
            }
            .navigationTitle("Log meal")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task { if await vm.save(userId: app.userId) { onSaved() } }
                    }
                    .disabled(vm.cart.isEmpty || vm.saving)
                }
            }
        }
    }
}
