import Foundation

struct RemoteServerConfig {
    static let defaultBaseURL = "https://market-scanner-api-fo2m.onrender.com"

    var baseURL: String
    var token: String

    var isReady: Bool {
        !baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

enum RemoteServerStore {
    private static let baseURLKey = "remote-server-base-url"
    private static let tokenKey = "remote-server-token"

    static func load() -> RemoteServerConfig {
        let savedToken = UserDefaults.standard.string(forKey: tokenKey) ?? ""
        let bundledToken = Bundle.main.object(forInfoDictionaryKey: "MarketAPIToken") as? String ?? ""
        return RemoteServerConfig(
            baseURL: UserDefaults.standard.string(forKey: baseURLKey) ?? RemoteServerConfig.defaultBaseURL,
            token: savedToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? bundledToken : savedToken
        )
    }

    static func save(_ config: RemoteServerConfig) {
        UserDefaults.standard.set(config.baseURL.trimmingCharacters(in: .whitespacesAndNewlines), forKey: baseURLKey)
        UserDefaults.standard.set(config.token.trimmingCharacters(in: .whitespacesAndNewlines), forKey: tokenKey)
    }
}

enum PaperTradingDeviceStore {
    private static let key = "paper-trading-device-id.v1"

    static func load() -> String {
        if let existing = UserDefaults.standard.string(forKey: key),
           !existing.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return existing
        }
        let created = UUID().uuidString
        UserDefaults.standard.set(created, forKey: key)
        return created
    }
}

enum RemoteMarketAPI {
    static func fetchResults(config: RemoteServerConfig, limit: Int = 1200) async throws -> [ScannerResult] {
        let payload = try await fetchResultsPayload(config: config, limit: limit)
        return CSVLoader.results(from: payload.rows)
    }

    static func fetchResultsPayload(config: RemoteServerConfig, limit: Int = 1200) async throws -> ResultsPayload {
        let safeLimit = min(max(limit, 1), 1200)
        return try await fetch(path: "/api/results?limit=\(safeLimit)", config: config)
    }

    static func fetchStatus(config: RemoteServerConfig) async throws -> StatusPayload {
        try await fetch(path: "/api/status", config: config)
    }

    static func quickRefresh(config: RemoteServerConfig) async throws -> QuickRefreshPayload {
        try await fetch(path: "/api/refresh/quick", config: config, method: "POST")
    }

    static func startScanner(config: RemoteServerConfig, mode: String = "quick") async throws -> ScannerRunPayload {
        let safeMode = mode == "full" ? "full" : "quick"
        let force = safeMode == "quick" ? "&force=true" : ""
        return try await fetch(path: "/api/scanner/run?mode=\(safeMode)\(force)", config: config, method: "POST")
    }

    static func fetchScannerStatus(config: RemoteServerConfig) async throws -> ScannerStatusPayload {
        try await fetch(path: "/api/scanner/status", config: config)
    }

    static func runAIScreening(config: RemoteServerConfig, limit: Int = 30) async throws -> AIScreeningPayload {
        let safeLimit = min(max(limit, 1), 80)
        return try await fetch(path: "/api/ai-screening/run?limit=\(safeLimit)", config: config, method: "POST", jsonBody: [:])
    }

    static func runAIScreeningBacktest(config: RemoteServerConfig, period: String = "6mo", maxSymbols: Int = 20) async throws -> AIScreeningBacktestPayload {
        let safeSymbols = min(max(maxSymbols, 1), 40)
        return try await fetch(path: "/api/ai-screening/backtest?period=\(period)&max_symbols=\(safeSymbols)", config: config, method: "POST", jsonBody: [:])
    }

    static func fetchPaperTradingAccount(config: RemoteServerConfig) async throws -> PaperTradingAccountPayload {
        try await fetch(path: "/api/paper-trading/account", config: config)
    }

    static func depositPaperCash(config: RemoteServerConfig, amount: Double) async throws -> PaperTradingAccountPayload {
        try await fetch(path: "/api/paper-trading/deposit", config: config, method: "POST", jsonBody: ["amount": amount])
    }

    static func simulatePaperTrade(
        config: RemoteServerConfig,
        ticker: String,
        quantity: Double,
        price: Double,
        side: String,
        cashAmount: Double? = nil
    ) async throws -> PaperTradingAccountPayload {
        var body: [String: Any] = [
            "ticker": ticker,
            "quantity": quantity,
            "price": price,
            "side": side
        ]
        if let cashAmount, cashAmount > 0 {
            body["cash_amount"] = cashAmount
        }
        return try await fetch(
            path: "/api/paper-trading/simulate",
            config: config,
            method: "POST",
            jsonBody: body
        )
    }

    private static func fetch<T: Decodable>(
        path: String,
        config: RemoteServerConfig,
        method: String = "GET",
        jsonBody: [String: Any]? = nil
    ) async throws -> T {
        guard config.isReady else {
            throw URLError(.userAuthenticationRequired)
        }
        let base = config.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let separator = path.contains("?") ? "&" : "?"
        let cacheBustedPath = method == "GET" ? "\(path)\(separator)_ts=\(Int(Date().timeIntervalSince1970 * 1000))" : path
        guard let url = URL(string: base + cacheBustedPath) else {
            APIDiagnostics.logError(endpoint: path, stage: "API_REQUEST", detail: "bad URL")
            throw URLError(.badURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 25
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        let token = config.token.trimmingCharacters(in: .whitespacesAndNewlines)
        request.setValue(token, forHTTPHeaderField: "X-Market-Token")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(PaperTradingDeviceStore.load(), forHTTPHeaderField: "X-Paper-Device-ID")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        request.setValue("no-cache", forHTTPHeaderField: "Pragma")
        if method != "GET" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            if let jsonBody {
                request.httpBody = try JSONSerialization.data(withJSONObject: jsonBody)
            }
        }

        let data: Data
        let response: URLResponse
        let startedAt = Date()
        APIDiagnostics.logRequest(method: method, url: url)
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let error as URLError {
            APIDiagnostics.logTransportError(endpoint: path, startedAt: startedAt, error: error)
            throw RemoteMarketAPIError.transport(error)
        } catch {
            APIDiagnostics.logError(endpoint: path, stage: "API_ERROR", detail: error.localizedDescription)
            throw RemoteMarketAPIError.network(error.localizedDescription)
        }
        guard let httpResponse = response as? HTTPURLResponse else {
            APIDiagnostics.logError(endpoint: path, stage: "API_RESPONSE", detail: "non HTTP response")
            throw RemoteMarketAPIError.network("서버 응답 형식 오류")
        }
        APIDiagnostics.logResponse(endpoint: path, statusCode: httpResponse.statusCode, startedAt: startedAt, data: data)
        guard 200..<300 ~= httpResponse.statusCode else {
            let message: String? = {
                guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    return nil
                }
                return (object["detail"] as? String) ?? (object["error"] as? String)
            }()
            throw RemoteMarketAPIError.httpStatus(httpResponse.statusCode, message)
        }
        do {
            let decoded = try JSONDecoder().decode(T.self, from: data)
            APIDiagnostics.logDecoded(endpoint: path, decoded: decoded)
            return decoded
        } catch {
            APIDiagnostics.logError(
                endpoint: path,
                stage: "DATA_PARSE",
                detail: "\(error.localizedDescription) · sample=\(String(data: data.prefix(160), encoding: .utf8) ?? "")"
            )
            throw RemoteMarketAPIError.decoding(String(data: data.prefix(240), encoding: .utf8))
        }
    }
}

private enum APIDiagnostics {
    static func logRequest(method: String, url: URL) {
        print("API_REQUEST method=\(method) endpoint=\(sanitizedEndpoint(from: url)) started_at=\(ISO8601DateFormatter().string(from: Date())) timeout=25s")
    }

    static func logResponse(endpoint: String, statusCode: Int, startedAt: Date, data: Data) {
        let elapsed = Date().timeIntervalSince(startedAt)
        let summary = payloadSummary(from: data)
        print("API_RESPONSE endpoint=\(endpoint) status=\(statusCode) elapsed=\(String(format: "%.2f", elapsed))s bytes=\(data.count) \(summary)")
    }

    static func logDecoded(endpoint: String, decoded: Decodable) {
        if let payload = decoded as? ResultsPayload {
            print("DATA_PARSE endpoint=\(endpoint) rows=\(payload.rows.count) total_count=\(payload.totalCount ?? payload.count) limited=\(payload.limited ?? false) total_canada_rows=\(payload.totalCanadaRows ?? payload.canadaRows ?? -1) total_market_counts=\(payload.totalMarketCounts ?? payload.marketCounts ?? [:])")
        } else if let payload = decoded as? StatusPayload {
            print("DATA_PARSE endpoint=\(endpoint) status_rows=\(payload.rows) market_counts=\(payload.marketCounts)")
        } else {
            print("DATA_PARSE endpoint=\(endpoint) decoded=true")
        }
    }

    static func logTransportError(endpoint: String, startedAt: Date, error: URLError) {
        let elapsed = Date().timeIntervalSince(startedAt)
        print("API_ERROR endpoint=\(endpoint) url_error=\(error.code.rawValue) code=\(error.code) elapsed=\(String(format: "%.2f", elapsed))s message=\(error.localizedDescription)")
    }

    static func logError(endpoint: String, stage: String, detail: String) {
        print("\(stage) endpoint=\(endpoint) detail=\(detail)")
    }

    private static func sanitizedEndpoint(from url: URL) -> String {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        components?.scheme = nil
        components?.host = nil
        components?.user = nil
        components?.password = nil
        components?.port = nil
        if let queryItems = components?.queryItems {
            components?.queryItems = queryItems.filter { $0.name != "_ts" }
        }
        return components?.string ?? url.path
    }

    private static func payloadSummary(from data: Data) -> String {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return "json=false"
        }
        var parts: [String] = []
        if let ok = object["ok"] {
            parts.append("ok=\(ok)")
        }
        if let rows = object["rows"] as? [[String: Any]] {
            parts.append("rows=\(rows.count)")
        } else if let rows = object["rows"] {
            parts.append("rows=\(rows)")
        }
        for key in ["count", "total_count", "limited", "limit", "total_canada_rows", "error"] {
            if let value = object[key] {
                parts.append("\(key)=\(value)")
            }
        }
        if let counts = object["total_market_counts"] ?? object["market_counts"] {
            parts.append("market_counts=\(counts)")
        }
        return parts.joined(separator: " ")
    }
}

struct AIScreeningPayload: Decodable {
    let ok: Bool
    let generatedAt: String?
    let count: Int
    let rows: [AIScreeningRow]
    let safetyNotice: String?
    let updatedAt: String?

    private enum CodingKeys: String, CodingKey {
        case ok
        case generatedAt = "generated_at"
        case count
        case rows
        case safetyNotice = "safety_notice"
        case updatedAt = "updated_at"
    }
}

struct AIScreeningRow: Decodable, Identifiable {
    var id: String { ticker }
    let name: String
    let ticker: String
    let sector: String
    let price: String
    let changePct: String
    let aiScore: Double
    let risk: Double
    let recommendation: String
    let reasons: String
    let weakPoints: String

    private enum CodingKeys: String, CodingKey {
        case name
        case ticker
        case sector
        case price
        case changePct = "change_pct"
        case aiScore = "ai_score"
        case risk
        case recommendation
        case reasons
        case weakPoints = "weak_points"
    }
}

struct AIScreeningBacktestPayload: Decodable {
    let ok: Bool
    let summary: AIScreeningBacktestSummary?
    let trades: [AIScreeningBacktestTrade]?
    let safetyNotice: String?
    let updatedAt: String?

    private enum CodingKeys: String, CodingKey {
        case ok
        case summary
        case trades
        case safetyNotice = "safety_notice"
        case updatedAt = "updated_at"
    }
}

struct AIScreeningBacktestSummary: Decodable {
    let totalTrades: Int?
    let winRatePct: Double?
    let finalReturnPct: Double?
    let mddPct: Double?
    let profitFactor: Double?
    let sharpeRatio: Double?

    private enum CodingKeys: String, CodingKey {
        case totalTrades = "total_trades"
        case winRatePct = "win_rate_pct"
        case finalReturnPct = "final_return_pct"
        case mddPct = "mdd_pct"
        case profitFactor = "profit_factor"
        case sharpeRatio = "sharpe_ratio"
    }
}

struct AIScreeningBacktestTrade: Decodable, Identifiable {
    var id: String { "\(ticker)-\(entryPrice)-\(exitPrice)" }
    let ticker: String
    let name: String
    let returnPct: Double
    let entryReason: String
    let exitReason: String
    let entryPrice: Double
    let exitPrice: Double

    private enum CodingKeys: String, CodingKey {
        case ticker
        case name
        case returnPct = "return_pct"
        case entryReason = "entry_reason"
        case exitReason = "exit_reason"
        case entryPrice = "entry_price"
        case exitPrice = "exit_price"
    }
}

struct PaperTradingAccountPayload: Codable {
    let ok: Bool
    let cash: Double
    let totalValue: Double
    let positions: [PaperTradingPosition]
    let trades: [PaperTradingTrade]
    let tradeCount: Int
    let updatedAt: String?
    let safetyNotice: String?

    private enum CodingKeys: String, CodingKey {
        case ok
        case cash
        case totalValue = "total_value"
        case positions
        case trades
        case tradeCount = "trade_count"
        case updatedAt = "updated_at"
        case safetyNotice = "safety_notice"
    }

    init(
        ok: Bool = true,
        cash: Double,
        totalValue: Double,
        positions: [PaperTradingPosition],
        trades: [PaperTradingTrade],
        tradeCount: Int? = nil,
        updatedAt: String?,
        safetyNotice: String?
    ) {
        self.ok = ok
        self.cash = cash
        self.totalValue = totalValue
        self.positions = positions
        self.trades = trades
        self.tradeCount = tradeCount ?? trades.count
        self.updatedAt = updatedAt
        self.safetyNotice = safetyNotice
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        ok = try container.decodeIfPresent(Bool.self, forKey: .ok) ?? true
        cash = try container.decodeIfPresent(Double.self, forKey: .cash) ?? 0
        positions = try container.decodeIfPresent([PaperTradingPosition].self, forKey: .positions) ?? []
        trades = try container.decodeIfPresent([PaperTradingTrade].self, forKey: .trades) ?? []
        totalValue = try container.decodeIfPresent(Double.self, forKey: .totalValue) ?? (cash + positions.reduce(0) { $0 + $1.marketValue })
        tradeCount = try container.decodeIfPresent(Int.self, forKey: .tradeCount) ?? trades.count
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
        safetyNotice = try container.decodeIfPresent(String.self, forKey: .safetyNotice)
    }
}

struct PaperTradingPosition: Codable, Identifiable {
    var id: String { ticker }
    let ticker: String
    let name: String
    let quantity: Double
    let avgPrice: Double
    let currentPrice: Double
    let marketValue: Double
    let profitLoss: Double
    let profitLossPct: Double

    private enum CodingKeys: String, CodingKey {
        case ticker
        case name
        case quantity
        case avgPrice = "avg_price"
        case currentPrice = "current_price"
        case marketValue = "market_value"
        case profitLoss = "profit_loss"
        case profitLossPct = "profit_loss_pct"
    }

    init(
        ticker: String,
        name: String,
        quantity: Double,
        avgPrice: Double,
        currentPrice: Double,
        marketValue: Double,
        profitLoss: Double,
        profitLossPct: Double
    ) {
        self.ticker = ticker
        self.name = name
        self.quantity = quantity
        self.avgPrice = avgPrice
        self.currentPrice = currentPrice
        self.marketValue = marketValue
        self.profitLoss = profitLoss
        self.profitLossPct = profitLossPct
    }
}

struct PaperTradingTrade: Codable, Identifiable {
    var id: String { "\(at)-\(type)-\(ticker)-\(quantity)-\(price)-\(amount)-\(cashAmount ?? 0)" }
    let at: String
    let type: String
    let ticker: String
    let name: String
    let quantity: Double
    let price: Double
    let amount: Double
    let cashAmount: Double?
    let fee: Double?
    let realizedProfit: Double?
    let realizedProfitPct: Double?

    var isBuy: Bool { type.contains("buy") }
    var isSell: Bool { type.contains("sell") }
    var isDeposit: Bool { type == "deposit" || type == "deposit_usd" }

    private enum CodingKeys: String, CodingKey {
        case at
        case type
        case ticker
        case name
        case quantity
        case price
        case amount
        case cashAmount = "cash_amount"
        case fee
        case realizedProfit = "realized_profit"
        case realizedProfitPct = "realized_profit_pct"
    }

    init(
        at: String,
        type: String,
        ticker: String,
        name: String,
        quantity: Double,
        price: Double,
        amount: Double,
        cashAmount: Double? = nil,
        fee: Double? = nil,
        realizedProfit: Double? = nil,
        realizedProfitPct: Double? = nil
    ) {
        self.at = at
        self.type = type
        self.ticker = ticker
        self.name = name
        self.quantity = quantity
        self.price = price
        self.amount = amount
        self.cashAmount = cashAmount
        self.fee = fee
        self.realizedProfit = realizedProfit
        self.realizedProfitPct = realizedProfitPct
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        at = try container.decodeIfPresent(String.self, forKey: .at) ?? ""
        type = try container.decodeIfPresent(String.self, forKey: .type) ?? ""
        ticker = try container.decodeIfPresent(String.self, forKey: .ticker) ?? ""
        name = try container.decodeIfPresent(String.self, forKey: .name) ?? ""
        quantity = try container.decodeIfPresent(Double.self, forKey: .quantity) ?? 0
        price = try container.decodeIfPresent(Double.self, forKey: .price) ?? 0
        amount = try container.decodeIfPresent(Double.self, forKey: .amount) ?? (quantity * price)
        cashAmount = try container.decodeIfPresent(Double.self, forKey: .cashAmount)
        fee = try container.decodeIfPresent(Double.self, forKey: .fee)
        realizedProfit = try container.decodeIfPresent(Double.self, forKey: .realizedProfit)
        realizedProfitPct = try container.decodeIfPresent(Double.self, forKey: .realizedProfitPct)
    }
}

enum PaperTradingLocalStore {
    private static let accountKey = "paperTradingAccountPayload.v2"
    private static let backupAccountKey = "paperTradingAccountPayload.backup.v2"
    private static let lastGoodAccountKey = "paperTradingAccountPayload.lastGood.v2"
    private static let eventLogKey = "paperTradingEventLog.v1"
    private static let oneTimeResetKey = "paperTradingOneTimeReset.platform.v1"

    static func load() -> PaperTradingAccountPayload? {
        if let account = decodeAccount(forKey: accountKey) {
            log("Portfolio Loaded", detail: "primary positions=\(account.positions.count) trades=\(account.trades.count)")
            return account
        }
        log("Data Corruption Detected", detail: "primary decode failed")
        if let backup = decodeAccount(forKey: backupAccountKey) {
            UserDefaults.standard.set(encode(backup), forKey: accountKey)
            log("Portfolio Restored", detail: "backup positions=\(backup.positions.count) trades=\(backup.trades.count)")
            return backup
        }
        if let lastGood = decodeAccount(forKey: lastGoodAccountKey) {
            UserDefaults.standard.set(encode(lastGood), forKey: accountKey)
            log("Data Recovery", detail: "lastGood positions=\(lastGood.positions.count) trades=\(lastGood.trades.count)")
            return lastGood
        }
        log("Portfolio Loaded", detail: "empty")
        return nil
    }

    static func save(_ account: PaperTradingAccountPayload) {
        if account.isEmptyPortfolio, let existing = load(), existing.hasPortfolioData {
            log("Portfolio Save Blocked", detail: "refused empty overwrite existing positions=\(existing.positions.count) trades=\(existing.trades.count)")
            return
        }
        if let existingData = UserDefaults.standard.data(forKey: accountKey) {
            UserDefaults.standard.set(existingData, forKey: backupAccountKey)
            log("Portfolio Backup Created", detail: "previous primary copied")
        }
        guard let data = encode(account) else {
            log("Data Corruption Detected", detail: "encode failed")
            return
        }
        UserDefaults.standard.set(data, forKey: accountKey)
        UserDefaults.standard.set(data, forKey: lastGoodAccountKey)
        log("Portfolio Saved", detail: "positions=\(account.positions.count) trades=\(account.trades.count) cash=\(account.cash)")
    }

    static func resetAll() {
        UserDefaults.standard.removeObject(forKey: accountKey)
        UserDefaults.standard.removeObject(forKey: backupAccountKey)
        UserDefaults.standard.removeObject(forKey: lastGoodAccountKey)
        UserDefaults.standard.removeObject(forKey: eventLogKey)
        log("Portfolio Reset", detail: "local paper trading data cleared")
    }

    static func consumeOneTimePlatformReset() -> Bool {
        if UserDefaults.standard.bool(forKey: oneTimeResetKey) {
            return false
        }
        UserDefaults.standard.set(true, forKey: oneTimeResetKey)
        resetAll()
        return true
    }

    static func shouldProtectLocal(_ remote: PaperTradingAccountPayload, local: PaperTradingAccountPayload?) -> Bool {
        guard let local else {
            return false
        }
        let remoteIsEmpty = remote.positions.isEmpty && remote.trades.isEmpty
        let localHasHistory = !local.positions.isEmpty || !local.trades.isEmpty
        return remoteIsEmpty && localHasHistory
    }

    static func preferredAccount(remote: PaperTradingAccountPayload, local: PaperTradingAccountPayload?) -> PaperTradingAccountPayload {
        guard let local else {
            log("Sync Finished", detail: "remote only positions=\(remote.positions.count) trades=\(remote.trades.count)")
            return remote
        }
        log("Sync Started", detail: "local p=\(local.positions.count) t=\(local.trades.count), remote p=\(remote.positions.count) t=\(remote.trades.count)")
        if shouldProtectLocal(remote, local: local) {
            log("Sync Conflict", detail: "remote empty, local protected")
            return local
        }
        if local.hasPortfolioData && remote.positions.count < local.positions.count && remote.trades.count <= local.trades.count {
            log("Sync Conflict", detail: "remote has fewer records, local kept")
            return local
        }
        if remote.trades.count < local.trades.count && local.positions.count >= remote.positions.count {
            log("Sync Conflict", detail: "remote older trade history, local kept")
            return local
        }
        if let localDate = local.updatedDate, let remoteDate = remote.updatedDate, localDate > remoteDate,
           local.hasPortfolioData,
           remote.positions.count <= local.positions.count {
            log("Sync Conflict", detail: "local newer, local kept")
            return local
        }
        log("Sync Finished", detail: "remote accepted")
        return remote
    }

    static func log(_ event: String, detail: String = "") {
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(event)\(detail.isEmpty ? "" : " · \(detail)")"
        var logs = UserDefaults.standard.stringArray(forKey: eventLogKey) ?? []
        logs.append(line)
        logs = Array(logs.suffix(200))
        UserDefaults.standard.set(logs, forKey: eventLogKey)
        #if DEBUG
        print("[PaperTrading] \(line)")
        #endif
    }

    private static func decodeAccount(forKey key: String) -> PaperTradingAccountPayload? {
        guard let data = UserDefaults.standard.data(forKey: key) else {
            return nil
        }
        return try? JSONDecoder().decode(PaperTradingAccountPayload.self, from: data)
    }

    private static func encode(_ account: PaperTradingAccountPayload) -> Data? {
        try? JSONEncoder().encode(account)
    }
}

extension PaperTradingAccountPayload {
    var isEmptyPortfolio: Bool {
        positions.isEmpty && trades.isEmpty && cash <= 0
    }

    var hasPortfolioData: Bool {
        !positions.isEmpty || !trades.isEmpty || cash > 0
    }

    var updatedDate: Date? {
        guard let updatedAt else {
            return nil
        }
        return ISO8601DateFormatter().date(from: updatedAt)
    }
}

enum RemoteMarketAPIError: LocalizedError {
    case httpStatus(Int, String?)
    case transport(URLError)
    case network(String)
    case decoding(String?)

    var errorDescription: String? {
        switch self {
        case .httpStatus(let code, let message):
            if let message, !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return message
            }
            if code == 401 || code == 403 {
                return "토큰 확인 필요"
            }
            if code == 404 {
                return "서버 경로 확인 필요"
            }
            if code >= 500 {
                return "Render 서버 오류"
            }
            return "HTTP \(code)"
        case .transport(let error):
            switch error.code {
            case .timedOut:
                return "서버 응답 시간 초과"
            case .cannotFindHost, .cannotConnectToHost, .dnsLookupFailed:
                return "서버 연결 실패"
            case .notConnectedToInternet, .networkConnectionLost:
                return "네트워크 연결 실패"
            case .userAuthenticationRequired:
                return "API 토큰 필요"
            case .badURL, .unsupportedURL:
                return "API 주소 오류"
            default:
                return "네트워크 오류 · \(error.localizedDescription)"
            }
        case .network(let message):
            return "서버 연결 실패 · \(message)"
        case .decoding(let sample):
            let detail = sample?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if detail.isEmpty {
                return "데이터 형식 오류"
            }
            return "데이터 형식 오류 · \(detail.prefix(80))"
        }
    }
}

struct ResultsPayload: Decodable {
    let ok: Bool
    let count: Int
    let totalCount: Int?
    let limited: Bool?
    let limit: Int?
    let rows: [[String: String]]
    let canadaRows: Int?
    let totalCanadaRows: Int?
    let marketCounts: [String: Int]?
    let totalMarketCounts: [String: Int]?
    let resultFile: String?
    let fileUpdatedAt: String?
    let dataGeneratedAt: String?
    let updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case ok
        case count
        case totalCount = "total_count"
        case limited
        case limit
        case rows
        case canadaRows = "canada_rows"
        case totalCanadaRows = "total_canada_rows"
        case marketCounts = "market_counts"
        case totalMarketCounts = "total_market_counts"
        case resultFile = "result_file"
        case fileUpdatedAt = "file_updated_at"
        case dataGeneratedAt = "data_generated_at"
        case updatedAt = "updated_at"
    }
}

struct StatusPayload: Decodable {
    let ok: Bool
    let rows: Int
    let okRows: Int
    let canadaRows: Int?
    let marketCounts: [String: Int]?
    let markets: [String]
    let resultFile: String?
    let fileUpdatedAt: String
    let dataGeneratedAt: String?
    let serverUpdatedAt: String
    let scanner: ScannerStatus?

    private enum CodingKeys: String, CodingKey {
        case ok
        case rows
        case okRows = "ok_rows"
        case canadaRows = "canada_rows"
        case marketCounts = "market_counts"
        case markets
        case resultFile = "result_file"
        case fileUpdatedAt = "file_updated_at"
        case dataGeneratedAt = "data_generated_at"
        case serverUpdatedAt = "server_updated_at"
        case scanner
    }
}

struct ScannerRunPayload: Decodable {
    let ok: Bool
    let started: Bool
    let running: Bool
    let skipped: Bool?
    let reason: String?
    let message: String
    let status: ScannerStatus?
    let updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case ok
        case started
        case running
        case skipped
        case reason
        case message
        case status
        case updatedAt = "updated_at"
    }
}

struct QuickRefreshPayload: Decodable {
    let ok: Bool
    let message: String
    let count: Int
    let status: ScannerStatus?
    let rows: Int?
    let okRows: Int?
    let fileUpdatedAt: String?
    let dataGeneratedAt: String?
    let updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case ok
        case message
        case count
        case status
        case rows
        case okRows = "ok_rows"
        case fileUpdatedAt = "file_updated_at"
        case dataGeneratedAt = "data_generated_at"
        case updatedAt = "updated_at"
    }
}

struct ScannerStatusPayload: Decodable {
    let ok: Bool
    let status: ScannerStatus
    let updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case ok
        case status
        case updatedAt = "updated_at"
    }
}

struct ScannerStatus: Decodable {
    let running: Bool
    let state: String
    let message: String
    let updatedAt: String?
    let fileUpdatedAt: String?
    let dataGeneratedAt: String?
    let rows: Int?
    let okRows: Int?
    let canadaRows: Int?
    let marketCounts: [String: Int]?
    let progress: Int?

    private enum CodingKeys: String, CodingKey {
        case running
        case state
        case message
        case updatedAt = "updated_at"
        case fileUpdatedAt = "file_updated_at"
        case dataGeneratedAt = "data_generated_at"
        case rows
        case okRows = "ok_rows"
        case canadaRows = "canada_rows"
        case marketCounts = "market_counts"
        case progress
    }
}
