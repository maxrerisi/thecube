import Foundation
import Observation

@Observable
@MainActor
final class TodayViewModel {
    var today: Today?
    var error: String?
    var loading = false
    private let api = APIClient.shared

    func load(userId: Int) async {
        loading = today == nil
        defer { loading = false }
        do {
            let t = try await api.today(userId: userId)
            if t != today { today = t }
            error = nil
        } catch is CancellationError {
        } catch {
            if (error as? URLError)?.code != .cancelled { self.error = error.localizedDescription }
        }
    }

    func delete(_ meal: Meal, userId: Int) async {
        do {
            try await api.deleteOrder(id: meal.id, userId: userId)
            await load(userId: userId)
        } catch {
            self.error = error.localizedDescription
        }
    }
}

extension Today: Equatable {
    static func == (a: Today, b: Today) -> Bool {
        a.date == b.date && a.user == b.user && a.eaten == b.eaten && a.points == b.points && a.coach == b.coach
            && a.meals == b.meals && a.targets == b.targets && a.showCalories == b.showCalories
            && a.proteinHitDays7 == b.proteinHitDays7
    }
}

@Observable
@MainActor
final class EatNextViewModel {
    var result: NextMeal?
    var bias: Bias = .balanced
    var error: String?
    var loading = false
    private let api = APIClient.shared

    func load(userId: Int) async {
        loading = true
        defer { loading = false }
        do {
            result = try await api.nextMeal(userId: userId, bias: bias)
            error = nil
        } catch is CancellationError {
        } catch {
            if (error as? URLError)?.code != .cancelled { self.error = error.localizedDescription }
        }
    }
}

@Observable
@MainActor
final class LogViewModel {
    var vendors: [Vendor] = []
    var error: String?
    private let api = APIClient.shared

    func load() async {
        do {
            vendors = try await api.vendors().sorted {
                ($0.hasNutrition ? 0 : 1, $0.openNow ? 0 : 1, $0.name) < ($1.hasNutrition ? 0 : 1, $1.openNow ? 0 : 1, $1.name)
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// One line in the meal being logged.
struct CartLine: Identifiable, Hashable {
    let id = UUID()
    let item: MenuItem
    var portion: Portion
    var servings: Double = 1

    var knownPrice: Double? { item.knownPrice?.price }
}

@Observable
@MainActor
final class MenuViewModel {
    let vendor: Vendor
    var menu: VendorMenu?
    var error: String?
    var cart: [CartLine] = []
    /// What the user paid for the whole meal (points); optional when receipt prices are known.
    var pointsPaid: String = ""
    var saving = false
    private let api = APIClient.shared

    init(vendor: Vendor) { self.vendor = vendor }

    func load() async {
        do {
            menu = try await api.menu(vendorId: vendor.id)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    func add(_ item: MenuItem, portion: Portion) { cart.append(CartLine(item: item, portion: portion)) }

    var totals: Macros {
        Macros(calories: cart.reduce(0) { $0 + ($1.portion.calories ?? 0) * $1.servings },
               proteinG: cart.reduce(0) { $0 + ($1.portion.proteinG ?? 0) * $1.servings },
               carbsG: cart.reduce(0) { $0 + ($1.portion.carbsG ?? 0) * $1.servings },
               fatG: cart.reduce(0) { $0 + ($1.portion.fatG ?? 0) * $1.servings })
    }
    /// Sum of receipt prices we know for items in the cart (unknown items count 0).
    var subtotal: Double { cart.reduce(0) { $0 + ($1.knownPrice ?? 0) * $1.servings } }
    /// SPEC 7: points default = prices x 1.075 tax, editable.
    var defaultPoints: Double { (subtotal * 1.075 * 100).rounded() / 100 }
    var typedPoints: Double? { Double(pointsPaid.replacingOccurrences(of: "$", with: "")) }

    func save(userId: Int) async -> Bool {
        saving = true
        defer { saving = false }
        let items = cart.map { line in
            ManualItem(itemOid: line.item.itemOid, uofmOid: line.portion.uofmOid, servings: line.servings,
                       price: nil)
        }
        let points = typedPoints
        do {
            _ = try await api.logManual(ManualOrder(userId: userId, vendorId: vendor.id, items: items,
                                                    pointsSpent: points, swipesUsed: 0))
            cart = []
            pointsPaid = ""
            error = nil
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }
}

@Observable
@MainActor
final class SettingsViewModel {
    var settings: UserSettings?
    var saved: UserSettings?
    var error: String?
    var status: String?
    var balancePoints = ""
    var balanceSwipes = ""
    private let api = APIClient.shared

    var dirty: Bool { settings != saved }

    func load(userId: Int) async {
        do {
            let s = try await api.settings(userId: userId)
            settings = s
            saved = s
            error = nil
            status = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    func save(userId: Int) async -> Bool {
        guard let settings else { return false }
        do {
            saved = try await api.saveSettings(userId: userId, settings)
            status = "Saved"
            error = nil
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    func saveBalance(userId: Int) async -> Bool {
        guard let pts = Double(balancePoints.replacingOccurrences(of: "$", with: "")) else {
            error = "Enter your points balance as a number"
            return false
        }
        do {
            try await api.postBalance(BalanceRequest(userId: userId, points: pts, swipes: Int(balanceSwipes)))
            status = "Balance updated"
            balancePoints = ""
            balanceSwipes = ""
            error = nil
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }
}
