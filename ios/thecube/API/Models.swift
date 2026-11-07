import Foundation

// Mirrors the backend JSON (SPEC 12). Keys are snake_case on the wire; APIClient converts.

struct User: Codable, Identifiable, Hashable {
    let id: Int
    let name: String
    let isDemo: Bool
}

// MARK: - /today

struct Macros: Codable, Hashable {
    var calories: Double?
    var proteinG: Double
    var carbsG: Double
    var fatG: Double
}

struct Targets: Codable, Hashable {
    var calories: Int?
    var proteinG: Int
}

struct PointsStatus: Codable, Hashable {
    var points: Double?
    var swipes: Int?
    var daysLeft: Int
    var dailyBudget: Double?
    var spentToday: Double
    var trailingDaily: Double
    var runout: String?
    var onPace: Bool?
    var balanceAsOf: String?
    var mealPlan: String?
    var paceTarget: Double?   // Duke Dining chart: suggested balance today for mealPlan
    var vsPace: Double?       // points - paceTarget (negative = behind)
}

struct CoachCard: Codable, Hashable {
    var headline: String
    var message: String
    var tone: String          // praise | nudge | warning
    var source: String?
}

struct Meal: Codable, Identifiable, Hashable {
    let id: Int
    let ts: String
    let vendor: String
    let items: [String]
    let pointsSpent: Double
    let swipesUsed: Int
    let source: String
    let macrosPartial: Bool
    let calories: Double?
    let proteinG: Double
    let carbsG: Double
    let fatG: Double
}

struct Today: Codable {
    let date: String
    let user: User
    let targets: Targets
    let showCalories: Bool
    let semesterEnd: String
    let eaten: Macros
    let proteinHitDays7: Int
    let points: PointsStatus
    let coach: CoachCard?
    let meals: [Meal]
}

// MARK: - /next-meal

struct PickComponent: Codable, Hashable {
    let name: String
    let itemOid: Int
    let uofmOid: Int
    let portion: String
    let calories: Double?
    let proteinG: Double
    let carbsG: Double
    let fatG: Double
}

struct Pick: Codable, Identifiable, Hashable {
    var id: String { "\(vendorId)-\(title)" }
    let title: String
    let group: String
    let kind: String
    let components: [PickComponent]
    let price: Double
    let pointsCost: Double
    let calories: Double?
    let proteinG: Double
    let carbsG: Double
    let fatG: Double
    let vendorId: Int
    let vendor: String
    let opensAt: String?
    let score: Double
}

struct PickCoach: Codable, Hashable {
    let chosenIndex: Int
    let headline: String
    let reason: String
    let source: String?
}

struct PerMealTarget: Codable, Hashable {
    let proteinG: Double
    let calories: Double?
}

struct Restrictions: Codable, Hashable {
    let requireDiets: [String]
    let avoidAllergens: [String]
}

struct NextMeal: Codable {
    let bias: String
    let mealsLeft: Int
    let perMealTarget: PerMealTarget
    let headroom: Double?
    let restrictions: Restrictions
    let openFallback: Bool
    let picks: [Pick]
    let coach: PickCoach?
}

enum Bias: String, CaseIterable, Identifiable {
    case balanced, protein, cheap
    var id: String { rawValue }
    var label: String {
        switch self {
        case .balanced: "Balanced"
        case .protein: "More protein"
        case .cheap: "Cheaper"
        }
    }
}

// MARK: - vendors / menu

struct Vendor: Codable, Identifiable, Hashable {
    let id: Int
    let name: String
    let building: String?
    let unitOid: Int?
    let hasNutrition: Bool
    let openNow: Bool
}

struct VendorRef: Codable, Hashable {
    let id: Int
    let name: String
}

struct KnownPrice: Codable, Hashable {
    let price: Double
    let label: String
    let source: String
}

struct Portion: Codable, Identifiable, Hashable {
    var id: Int { uofmOid }
    let uofmOid: Int
    let name: String
    let isDefault: Bool
    let grams: Double?
    let calories: Double?
    let proteinG: Double?
    let carbsG: Double?
    let fatG: Double?
    let fiberG: Double?
    let sugarG: Double?
    let sodiumMg: Double?
}

struct MenuItem: Codable, Identifiable, Hashable {
    var id: Int { itemOid }
    let itemOid: Int
    let name: String
    let allergens: [String]
    let diets: [String]
    let ingredients: String?
    let meal: String?
    let knownPrice: KnownPrice?
    let portions: [Portion]

    var defaultPortion: Portion? { portions.first(where: \.isDefault) ?? portions.first }
}

struct Course: Codable, Identifiable, Hashable {
    var id: String { name }
    let name: String
    let items: [MenuItem]
}

struct VendorMenu: Codable {
    let vendor: VendorRef
    let hasNutrition: Bool
    let menuDate: String?
    let courses: [Course]
}

// MARK: - writes

struct ManualItem: Codable, Hashable {
    var itemOid: Int
    var uofmOid: Int
    var servings: Double
    var price: Double?
}

struct ManualOrder: Codable {
    var userId: Int
    var vendorId: Int
    var items: [ManualItem]
    var pointsSpent: Double?
    var swipesUsed: Int
}

struct ManualOrderResult: Codable {
    let id: Int
    let vendor: String
    let subtotal: Double?
    let pointsSpent: Double
    let macros: Macros
}

struct UnknownComponent: Codable, Hashable {
    let vendor: String
    let name: String
}

struct ImportResult: Codable {
    let imported: Int
    let duplicates: Int
    let partial: [String]
    let unknownComponents: [UnknownComponent]
}

struct BalanceRequest: Codable {
    var userId: Int
    var points: Double
    var swipes: Int?
}

struct SettingsTargets: Codable, Hashable {
    var calories: Int
    var proteinG: Int
}

struct UserSettings: Codable, Hashable {
    var semesterEnd: String
    var targets: SettingsTargets
    var goal: String
    var requireDiets: [String]
    var avoidAllergens: [String]
    var showCalories: Bool
    var mealPlan: String?

    /// Duke Fall 2026 plans on the points chart (seed/duke_points_fall2026.json).
    static let mealPlans = ["A", "B", "C", "D", "E", "F", "I", "J"]
    static let diets = ["halal", "vegan", "vegetarian"]
    static let allergens = ["egg", "fish", "gluten", "milk", "peanut", "sesame", "shellfish", "soy", "tree_nut", "wheat"]
    static let goals = ["balanced", "build_muscle", "budget"]
}

struct Deleted: Codable { let deleted: Int }

// MARK: - formatting

enum Fmt {
    static func g(_ v: Double?) -> String { v.map { "\(Int($0.rounded())) g" } ?? "–" }
    static func cal(_ v: Double?) -> String { v.map { "\(Int($0.rounded())) cal" } ?? "–" }
    static func money(_ v: Double?) -> String { v.map { String(format: "$%.2f", $0) } ?? "–" }
    static func pts(_ v: Double?) -> String { v.map { String(format: "%.2f", $0) } ?? "–" }

    /// "2026-12-12" -> "Dec 12"
    static func day(_ iso: String?) -> String {
        guard let iso, let d = dayParser.date(from: iso) else { return "–" }
        return dayOut.string(from: d)
    }
    /// "2026-11-07T08:30:00-05:00" -> "8:30 AM"
    static func time(_ iso: String) -> String {
        guard let d = parseTimestamp(iso) else { return "" }
        return timeOut.string(from: d)
    }
    static func parseTimestamp(_ iso: String) -> Date? {
        isoPlain.date(from: iso) ?? isoFrac.date(from: iso)
    }
    static func label(_ s: String) -> String { s.replacingOccurrences(of: "_", with: " ").capitalized }

    private static let dayParser: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()
    private static let dayOut: DateFormatter = { let f = DateFormatter(); f.setLocalizedDateFormatFromTemplate("MMM d"); return f }()
    private static let timeOut: DateFormatter = { let f = DateFormatter(); f.timeStyle = .short; return f }()
    private static let isoPlain: ISO8601DateFormatter = ISO8601DateFormatter()
    private static let isoFrac: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f
    }()
}
