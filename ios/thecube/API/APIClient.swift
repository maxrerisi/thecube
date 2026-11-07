import Foundation

enum APIError: LocalizedError {
    case http(Int, String)
    case mockMissing(String)

    var errorDescription: String? {
        switch self {
        case let .http(code, body): "Server error \(code): \(body.prefix(200))"
        case let .mockMissing(name): "No mock data for \(name)"
        }
    }
}

/// Talks to the backend (SPEC 12). API_BASE_URL and APP_TOKEN come from Info.plist, which reads
/// Config/Secrets.xcconfig. With no API_BASE_URL the app runs on the bundled Mock/*.json (T4).
final class APIClient: @unchecked Sendable {
    static let shared = APIClient()

    let baseURL: URL?
    private let token: String
    private let session: URLSession
    private let decoder: JSONDecoder = { let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d }()
    private let encoder: JSONEncoder = { let e = JSONEncoder(); e.keyEncodingStrategy = .convertToSnakeCase; return e }()

    var isMock: Bool { baseURL == nil }

    init(bundle: Bundle = .main) {
        let raw = (bundle.object(forInfoDictionaryKey: "API_BASE_URL") as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        baseURL = (raw.isEmpty || raw.hasPrefix("$(")) ? nil : URL(string: raw)
        token = (bundle.object(forInfoDictionaryKey: "APP_TOKEN") as? String ?? "").trimmingCharacters(in: .whitespaces)
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 20
        session = URLSession(configuration: cfg)
    }

    // MARK: endpoints

    func users() async throws -> [User] { try await get("users", mock: "users") }
    func today(userId: Int) async throws -> Today { try await get("today", ["user_id": "\(userId)"], mock: "today") }
    func nextMeal(userId: Int, bias: Bias) async throws -> NextMeal {
        try await get("next-meal", ["user_id": "\(userId)", "bias": bias.rawValue], mock: "next_meal")
    }
    func vendors() async throws -> [Vendor] { try await get("vendors", mock: "vendors") }
    func menu(vendorId: Int) async throws -> VendorMenu { try await get("vendors/\(vendorId)/menu", mock: "menu") }
    func settings(userId: Int) async throws -> UserSettings { try await get("settings", ["user_id": "\(userId)"], mock: "settings") }

    func saveSettings(userId: Int, _ s: UserSettings) async throws -> UserSettings {
        try await send("PUT", "settings", ["user_id": "\(userId)"], body: s, mockResult: s)
    }
    func logManual(_ order: ManualOrder) async throws -> ManualOrderResult {
        try await send("POST", "orders/manual", body: order,
                       mockResult: ManualOrderResult(id: 0, vendor: "", subtotal: nil, pointsSpent: order.pointsSpent ?? 0,
                                                     macros: Macros(calories: nil, proteinG: 0, carbsG: 0, fatG: 0)))
    }
    func deleteOrder(id: Int, userId: Int) async throws {
        let _: Deleted = try await send("DELETE", "orders/\(id)", ["user_id": "\(userId)"], body: Optional<String>.none,
                                        mockResult: Deleted(deleted: id))
    }
    func postBalance(_ b: BalanceRequest) async throws {
        struct Ok: Codable {}
        let _: Ok = try await send("POST", "balance", body: b, mockResult: Ok())
    }

    /// POST /import/eml, multipart: user_id + one or more .eml files.
    func importEmls(userId: Int, files: [(name: String, data: Data)]) async throws -> ImportResult {
        guard let baseURL else {
            return ImportResult(imported: files.count, duplicates: 0, partial: [], unknownComponents: [])
        }
        let boundary = "thecube-\(UUID().uuidString)"
        var body = Data()
        func add(_ s: String) { body.append(Data(s.utf8)) }
        add("--\(boundary)\r\nContent-Disposition: form-data; name=\"user_id\"\r\n\r\n\(userId)\r\n")
        for f in files {
            add("--\(boundary)\r\nContent-Disposition: form-data; name=\"files\"; filename=\"\(f.name)\"\r\n")
            add("Content-Type: message/rfc822\r\n\r\n")
            body.append(f.data)
            add("\r\n")
        }
        add("--\(boundary)--\r\n")
        var req = request(baseURL.appending(path: "import/eml"), method: "POST")
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        return try await perform(req)
    }

    // MARK: plumbing

    private func request(_ url: URL, method: String) -> URLRequest {
        var r = URLRequest(url: url)
        r.httpMethod = method
        r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        return r
    }

    private func url(_ path: String, _ query: [String: String]) -> URL? {
        guard let baseURL else { return nil }
        var c = URLComponents(url: baseURL.appending(path: path), resolvingAgainstBaseURL: false)
        if !query.isEmpty { c?.queryItems = query.sorted(by: { $0.key < $1.key }).map { URLQueryItem(name: $0.key, value: $0.value) } }
        return c?.url
    }

    private func get<T: Decodable>(_ path: String, _ query: [String: String] = [:], mock: String) async throws -> T {
        guard let u = url(path, query) else { return try loadMock(mock) }
        return try await perform(request(u, method: "GET"))
    }

    private func send<T: Decodable, B: Encodable>(_ method: String, _ path: String, _ query: [String: String] = [:],
                                                  body: B?, mockResult: T) async throws -> T {
        guard let u = url(path, query) else { return mockResult }
        var req = request(u, method: method)
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try encoder.encode(body)
        }
        return try await perform(req)
    }

    private func perform<T: Decodable>(_ req: URLRequest) async throws -> T {
        let (data, resp) = try await session.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else { throw APIError.http(code, String(decoding: data, as: UTF8.self)) }
        return try decoder.decode(T.self, from: data)
    }

    private func loadMock<T: Decodable>(_ name: String) throws -> T {
        guard let u = Bundle.main.url(forResource: name, withExtension: "json") else { throw APIError.mockMissing(name) }
        return try decoder.decode(T.self, from: Data(contentsOf: u))
    }
}
