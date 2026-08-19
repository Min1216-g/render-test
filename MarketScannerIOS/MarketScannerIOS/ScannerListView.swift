import SwiftUI
import UIKit

private enum AppColors {
    static let background = Color(red: 0.035, green: 0.043, blue: 0.055)
    static let panel = Color(red: 0.075, green: 0.086, blue: 0.105)
    static let panelSoft = Color(red: 0.105, green: 0.118, blue: 0.142)
    static let border = Color.white.opacity(0.08)
}

private struct ScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct VerticalScrollLockView: UIViewRepresentable {
    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: .zero)
        view.isUserInteractionEnabled = false
        DispatchQueue.main.async {
            configureScrollView(from: view)
        }
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        DispatchQueue.main.async {
            configureScrollView(from: uiView)
        }
    }

    private func configureScrollView(from view: UIView) {
        var parent = view.superview
        while let current = parent {
            if let scrollView = current as? UIScrollView {
                scrollView.alwaysBounceHorizontal = false
                scrollView.showsHorizontalScrollIndicator = false
                scrollView.isDirectionalLockEnabled = true
                scrollView.contentInsetAdjustmentBehavior = .automatic
                if scrollView.bounds.width > 0, scrollView.contentSize.width > scrollView.bounds.width {
                    var contentSize = scrollView.contentSize
                    contentSize.width = scrollView.bounds.width
                    scrollView.contentSize = contentSize
                }
                return
            }
            parent = current.superview
        }
    }
}

private struct ScreenContainer<Content: View>: View {
    let horizontalPadding: CGFloat
    let bottomPadding: CGFloat
    @ViewBuilder let content: () -> Content

    init(
        horizontalPadding: CGFloat = 0,
        bottomPadding: CGFloat = 40,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.horizontalPadding = horizontalPadding
        self.bottomPadding = bottomPadding
        self.content = content
    }

    var body: some View {
        GeometryReader { proxy in
            let width = max(0, proxy.size.width - horizontalPadding * 2)
            let safeBottom = proxy.safeAreaInsets.bottom
            ScrollView(.vertical, showsIndicators: true) {
                VStack(alignment: .leading, spacing: 12) {
                    content()
                }
                .frame(width: width, alignment: .topLeading)
                .padding(.horizontal, horizontalPadding)
                .padding(.top, 12)
                .padding(.bottom, bottomPadding + safeBottom + 12)
            }
            .scrollIndicators(.visible)
            .verticalScrollOnly()
            .clipped()
        }
    }
}

private struct AdaptiveCard<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct DebugWidthBorder: ViewModifier {
    let color: Color

    func body(content: Content) -> some View {
        #if DEBUG
        content.overlay(Rectangle().stroke(color, lineWidth: 1))
        #else
        content
        #endif
    }
}

private extension View {
    func verticalScrollOnly() -> some View {
        background(VerticalScrollLockView().frame(width: 0, height: 0))
    }

    func noHorizontalOverflow() -> some View {
        frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .clipped()
    }

    func wrapInsideCard(lineLimit: Int? = nil) -> some View {
        self
            .lineLimit(lineLimit)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    func overflowSafe() -> some View {
        frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
    }

    func debugBorder(_ color: Color = .red) -> some View {
        modifier(DebugWidthBorder(color: color))
    }
}

struct ScannerListView: View {
    @StateObject private var networkUsageMonitor = NetworkUsageMonitor()
    @State private var results: [ScannerResult] = []
    @State private var lastSuccessfulResults: [ScannerResult] = []
    @State private var didLoadResults = false
    @State private var isLoadingInitialResults = true
    @State private var dataLoadState: MarketDataLoadState = .loading
    @State private var filter: ResultFilter = .ai
    @State private var marketFilter: MarketFilter = .all
    @State private var dividendFilter: DividendFilter = .all
    @State private var favoriteTickers = FavoriteStore.load()
    @State private var searchText = ""
    @State private var isCheckingRemoteStatus = false
    @State private var isRefreshingQuotes = false
    @State private var lastQuoteRefresh: Date?
    @State private var dataUpdatedAt: Date?
    @State private var quoteRefreshMessage = "스캔 가격"
    @State private var usdKrwRate = CurrencyExchangeRateStore.usdKrwRate ?? 0
    @State private var showInsightHub = true
    @State private var lastScrollOffset: CGFloat = 0
    @State private var newAiPickTickers: Set<String> = NewAiPickStore.loadNewTickers()
    @State private var aiPickDates: [String: String] = NewAiPickStore.loadRecommendationDates()
    @State private var displayedResultsCache: [ScannerResult] = []
    @State private var todayWatchlistCache: [ScannerResult] = []
    @State private var abnormalEventsCache: [ScannerResult] = []
    @State private var missedReviewCache: [ScannerResult] = []
    @State private var flowRadarCache = MoneyFlowRadarData.empty
    @State private var sectorInflowCache: [SectorInflowRank] = []
    @State private var marketStrengthSectionsCache: [MarketStrengthSection] = []
    @State private var closingBuyCandidatesCache: [ScannerResult] = []
    @State private var majorNewsCache: [ScannerResult] = []
    @State private var leadingCandidatesCache: [ScannerResult] = []
    @State private var missedCandidatesCache: [ScannerResult] = []
    @State private var riskCandidatesCache: [ScannerResult] = []
    @State private var keywordCandidatesCache: [ScannerResult] = []
    @State private var topGainersCache: [ScannerResult] = []
    @State private var topLosersCache: [ScannerResult] = []
    @State private var buyCountCache = 0
    @State private var aiPickCountCache = 0
    @State private var liveQuoteCountCache = 0
    @State private var positionEvaluationsCache: [String: PositionEvaluation] = [:]
    @State private var portfolioRiskSummary = PortfolioRiskSummary.empty
    @State private var searchRefreshTask: Task<Void, Never>?
    @State private var remoteConfig = RemoteServerStore.load()
    @State private var showServerSettings = false
    @State private var showBugReportSheet = false
    @State private var showAdminUnlockSheet = false
    @State private var bugReports = BugReportStore.load()
    @State private var bugReportSyncText = "신고 동기화 대기"
    @State private var remoteStatusText = "로컬 데이터"
    @State private var isScannerRunning = false
    @State private var scannerProgress = 0
    @State private var lastRemoteFileUpdatedAt = ""
    @State private var remoteFailureCount = 0
    @AppStorage("sectorInflowCardSize") private var sectorInflowCardSizeRaw = SectorInflowCardSize.compact.rawValue
    @State private var selectedMainTab: MainAppTab = .home
    @State private var earningsMarket: EarningsMarket = .korea
    @State private var earningsRange: EarningsDateRange = .thisWeek
    @State private var selectedEarningsDate = Date()
    @State private var moversMarket: MoversMarket = .korea
    @State private var moversCategory: MoversCategory = .gainers
    @State private var moversSort: MoversSort = .change
    @State private var moversExchange: MoversExchange = .all
    @State private var moversStockType: MoversStockType = .all
    @State private var moversSector: MoversSector = .all
    @AppStorage("temporaryAdminDeviceEnabled") private var temporaryAdminDeviceEnabled = false
    private let quoteRefreshTimer = Timer.publish(every: 180, on: .main, in: .common).autoconnect()
    private let scannerStatusTimer = Timer.publish(every: 8, on: .main, in: .common).autoconnect()
    private let bugReportSyncTimer = Timer.publish(every: 30, on: .main, in: .common).autoconnect()
    private let favoriteNewsTimer = Timer.publish(every: 3600, on: .main, in: .common).autoconnect()
    private var visibleMainTabs: [MainAppTab] {
        MainAppTab.userTabs + (temporaryAdminDeviceEnabled ? [.admin] : [])
    }
    private var buyCandidates: [ScannerResult] {
        results.filter(\.isBuyCandidate)
    }

    private func makeVisibleResults() -> [ScannerResult] {
        let trimmedSearch = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedSearch = trimmedSearch
            .lowercased()
            .replacingOccurrences(of: " ", with: "")
        let isSpaceXSearch = normalizedSearch.contains("spacex")
            || normalizedSearch.contains("spcx")
            || normalizedSearch.contains("스페이스x")
            || normalizedSearch.contains("스페이스엑스")
        let filteredResults: [ScannerResult]
        if trimmedSearch.isEmpty {
            switch filter {
            case .ai:
                filteredResults = results
                    .filter(\.isAiPick)
                    .sorted { lhs, rhs in
                        if lhs.aiRankScore == rhs.aiRankScore {
                            return lhs.changePercent > rhs.changePercent
                        }
                        return lhs.aiRankScore > rhs.aiRankScore
                    }
            case .buy:
                filteredResults = buyCandidates
            case .favorites:
                filteredResults = results.filter { favoriteTickers.contains($0.ticker) }
            case .watch:
                filteredResults = results.filter { !$0.isBuyCandidate }
            case .all:
                filteredResults = results
            }
        } else {
            filteredResults = results
        }
        let matchedResults = filteredResults
            .filter { isSpaceXSearch ? true : marketFilter.matches($0) }
            .filter { isSpaceXSearch ? true : (marketFilter == .canada ? dividendFilter.matches($0) : true) }
            .filter { $0.matchesSearch(searchText) }

        if trimmedSearch.isEmpty {
            if marketFilter == .canada && matchedResults.isEmpty && filter != .all {
                return Array(
                    results
                        .filter { marketFilter.matches($0) }
                        .filter { dividendFilter.matches($0) }
                        .sorted { lhs, rhs in
                            if lhs.aiRankScore == rhs.aiRankScore {
                                return lhs.changePercent > rhs.changePercent
                            }
                            return lhs.aiRankScore > rhs.aiRankScore
                        }
                        .prefix(80)
                )
            }
            return Array(matchedResults.prefix(filter == .all ? 80 : 55))
        }

        return Array(
            matchedResults
                .sorted { lhs, rhs in
                    let lhsRank = lhs.searchRank(for: trimmedSearch)
                    let rhsRank = rhs.searchRank(for: trimmedSearch)
                    if lhsRank == rhsRank {
                        if lhs.marketText == rhs.marketText {
                            return lhs.score > rhs.score
                        }
                        return lhs.marketText == "국장"
                    }
                    return lhsRank > rhsRank
                }
                .prefix(45)
        )
    }

    private var isSearching: Bool {
        !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var shouldReduceData: Bool {
        networkUsageMonitor.shouldReduceData
    }

    private var sectorInflowCardSize: SectorInflowCardSize {
        SectorInflowCardSize(rawValue: sectorInflowCardSizeRaw) ?? .compact
    }

    private var headerTopSummary: String {
        guard let first = results.first else {
            return "결과 없음"
        }
        return "\(first.name) · \(first.simpleReason)"
    }

    private func makeMarketStrengthSections() -> [MarketStrengthSection] {
        activeMarkets.compactMap { market in
            let summaries = sectorSummaries(for: market)
            guard !summaries.isEmpty else {
                return nil
            }
            return MarketStrengthSection(market: market, summaries: summaries)
        }
    }

    private func makeClosingBuyCandidates() -> [ScannerResult] {
        results
            .filter { marketFilter.matches($0) }
            .filter(\.isClosingBuyCandidate)
            .sorted { lhs, rhs in
                if lhs.closingBuyScore == rhs.closingBuyScore {
                    return lhs.changePercent > rhs.changePercent
                }
                return lhs.closingBuyScore > rhs.closingBuyScore
            }
            .prefix(6)
            .map { $0 }
    }

    private func makeMajorNewsItems() -> [ScannerResult] {
        results.lazy
            .filter { marketFilter.matches($0) }
            .filter { marketFilter == .canada ? dividendFilter.matches($0) : true }
            .filter { $0.isAiPick || $0.isBuyCandidate || $0.score >= 78 || $0.volumeRatio >= 2 || abs($0.changePercent) >= 4 }
            .map { result in (result: result, score: result.majorNewsScore) }
            .filter { $0.score >= 4 }
            .sorted { lhs, rhs in
                if lhs.score == rhs.score {
                    return abs(lhs.result.changePercent) > abs(rhs.result.changePercent)
                }
                return lhs.score > rhs.score
            }
            .map(\.result)
            .uniquedByTicker()
            .prefix(12)
            .map { $0 }
    }

    private func makeLeadingCandidates() -> [ScannerResult] {
        Array(
            results
                .filter(\.isLeadDetectionCandidate)
                .sorted { lhs, rhs in
                    if lhs.todayScore == rhs.todayScore {
                        return lhs.flowRotationScore > rhs.flowRotationScore
                    }
                    return lhs.todayScore > rhs.todayScore
                }
                .prefix(12)
        )
    }

    private func makeMissedCandidates() -> [ScannerResult] {
        Array(
            results
                .filter { $0.missedRiskText != nil }
                .sorted { lhs, rhs in
                    if lhs.volumeRatio == rhs.volumeRatio {
                        return lhs.todayScore > rhs.todayScore
                    }
                    return lhs.volumeRatio > rhs.volumeRatio
                }
                .prefix(10)
        )
    }

    private func makeRiskCandidates() -> [ScannerResult] {
        Array(
            results
                .filter { $0.realtimeRiskText != nil }
                .sorted { lhs, rhs in
                    if abs(lhs.changePercent) == abs(rhs.changePercent) {
                        return lhs.volumeRatio > rhs.volumeRatio
                    }
                    return abs(lhs.changePercent) > abs(rhs.changePercent)
                }
                .prefix(8)
        )
    }

    private func makeKeywordCandidates() -> [ScannerResult] {
        Array(
            results
                .filter { $0.repeatedKeywordSignal != nil }
                .sorted { lhs, rhs in
                    if lhs.todayScore == rhs.todayScore {
                        return lhs.volumeRatio > rhs.volumeRatio
                    }
                    return lhs.todayScore > rhs.todayScore
                }
                .prefix(10)
        )
    }

    private func makeTopGainers() -> [ScannerResult] {
        Array(
            results
                .filter { marketFilter.matches($0) }
                .filter { marketFilter == .canada ? dividendFilter.matches($0) : true }
                .filter { $0.changePercent > 0 }
                .sorted { $0.changePercent > $1.changePercent }
                .uniquedByTicker()
                .prefix(30)
        )
    }

    private func makeTopLosers() -> [ScannerResult] {
        Array(
            results
                .filter { marketFilter.matches($0) }
                .filter { marketFilter == .canada ? dividendFilter.matches($0) : true }
                .filter { $0.changePercent < 0 }
                .sorted { $0.changePercent < $1.changePercent }
                .uniquedByTicker()
                .prefix(30)
        )
    }

    private func makeTodayWatchlist() -> [ScannerResult] {
        var usedSectors: Set<String> = []
        let ranked = results
            .filter { marketFilter.matches($0) }
            .filter { marketFilter == .canada ? dividendFilter.matches($0) : true }
            .filter(\.isHomeRecommendationCandidate)
            .sorted { lhs, rhs in
                if lhs.todayWatchScore == rhs.todayWatchScore {
                    return lhs.eventScore > rhs.eventScore
                }
                return lhs.todayWatchScore > rhs.todayWatchScore
            }

        let representatives = ranked.filter { result in
            let key = "\(result.marketText)-\(result.sectorCategoryName)"
            if usedSectors.contains(key) {
                return false
            }
            usedSectors.insert(key)
            return true
        }

        return Array((representatives + ranked).uniquedByTicker().prefix(10))
    }

    private func makeAbnormalEvents() -> [ScannerResult] {
        results
            .filter { marketFilter.matches($0) }
            .filter { marketFilter == .canada ? dividendFilter.matches($0) : true }
            .filter { !$0.abnormalSignals.isEmpty }
            .sorted { lhs, rhs in
                if lhs.abnormalSignals.count == rhs.abnormalSignals.count {
                    return lhs.todayWatchScore > rhs.todayWatchScore
                }
                return lhs.abnormalSignals.count > rhs.abnormalSignals.count
            }
            .prefix(8)
            .map { $0 }
    }

    private func makeMoneyFlowRadarData() -> MoneyFlowRadarData {
        let scoped = results
            .filter { marketFilter.matches($0) }
            .filter { marketFilter == .canada ? dividendFilter.matches($0) : true }

        let marketScoped = scoped.isEmpty ? results : scoped
        let sectorGroups = Dictionary(grouping: marketScoped) { result in
            "\(result.marketText)-\(result.themeKey)"
        }

        let sectorFlows = sectorGroups.compactMap { _, items -> SectorFlowSignal? in
            guard items.count >= 2 else {
                return nil
            }
            let averageChange = items.map(\.changePercent).reduce(0, +) / Double(items.count)
            let averageVolume = items.map(\.volumeRatio).reduce(0, +) / Double(items.count)
            let risingRatio = Double(items.filter { $0.changePercent > 0 }.count) / Double(items.count)
            let earlyCount = items.filter(\.isEarlyFlowCandidate).count
            let quietCount = items.filter(\.isQuietRelatedCandidate).count
            let leaders = items
                .sorted { $0.flowRotationScore > $1.flowRotationScore }
                .prefix(3)
                .map(\.name)
                .joined(separator: ", ")
            var score = averageVolume * 12 + risingRatio * 18 + Double(earlyCount) * 4 + Double(quietCount) * 2
            if averageChange > 0 && averageChange < 3 { score += 14 }
            if averageChange >= 5 { score -= 16 }
            if averageChange < -4 { score -= 8 }
            return SectorFlowSignal(
                market: items.first?.marketText ?? "시장",
                theme: items.first?.themeKey ?? "섹터",
                averageChange: averageChange,
                averageVolume: averageVolume,
                risingRatio: risingRatio,
                earlyCount: earlyCount,
                quietCount: quietCount,
                leaders: leaders,
                score: score
            )
        }
        .sorted { $0.score > $1.score }

        let nextRotation = sectorFlows
            .filter { $0.averageChange < 4.5 && $0.averageVolume >= 1.05 && ($0.earlyCount > 0 || $0.quietCount > 0) }
            .prefix(4)
            .map { $0 }

        let strongThemeKeys = Set(sectorFlows.filter { $0.averageChange > 1.2 || $0.averageVolume >= 1.4 }.map(\.theme))

        let quietRelated = marketScoped
            .filter { strongThemeKeys.contains($0.themeKey) }
            .filter(\.isQuietRelatedCandidate)
            .sorted { $0.flowRotationScore > $1.flowRotationScore }
            .uniquedByTicker()
            .prefix(6)
            .map { $0 }

        let initialVolume = marketScoped
            .filter(\.isEarlyFlowCandidate)
            .sorted { lhs, rhs in
                if lhs.volumeRatio == rhs.volumeRatio {
                    return lhs.flowRotationScore > rhs.flowRotationScore
                }
                return lhs.volumeRatio > rhs.volumeRatio
            }
            .uniquedByTicker()
            .prefix(6)
            .map { $0 }

        let usStrongThemes = Set(
            sectorFlows
                .filter { $0.market == "미장" && $0.score >= 28 }
                .map(\.theme)
        )
        let usToKorea = results
            .filter { $0.marketText == "국장" && usStrongThemes.contains($0.themeKey) }
            .filter { $0.changePercent < 4.5 && !$0.isChaseRiskForAi }
            .sorted { $0.flowRotationScore > $1.flowRotationScore }
            .uniquedByTicker()
            .prefix(6)
            .map { $0 }

        return MoneyFlowRadarData(
            nextRotation: Array(nextRotation),
            quietRelated: quietRelated,
            initialVolume: initialVolume,
            usToKorea: usToKorea
        )
    }

    private func makeSectorInflowRanks() -> [SectorInflowRank] {
        let scoped = results
            .filter { marketFilter.matches($0) }
            .filter { marketFilter == .canada ? dividendFilter.matches($0) : true }
        let marketScoped = scoped.isEmpty ? results : scoped
        let groups = Dictionary(grouping: marketScoped) { result in
            "\(result.marketText)-\(result.themeKey)"
        }

        return groups.compactMap { _, items -> SectorInflowRank? in
            guard items.count >= 2 else {
                return nil
            }
            let market = items.first?.marketText ?? "시장"
            let theme = items.first?.themeKey ?? "섹터"
            let totalTradeValue = items.map(\.tradeValueForRanking).reduce(0, +)
            let averageTradeValueRatio = items.map(\.tradeValueRatioForRanking).reduce(0, +) / Double(items.count)
            let averageVolume = items.map(\.volumeRatio).reduce(0, +) / Double(items.count)
            let averageChange = items.map(\.changePercent).reduce(0, +) / Double(items.count)
            let positiveRatio = Double(items.filter { $0.changePercent > 0 }.count) / Double(items.count)
            let leaders = items
                .sorted { lhs, rhs in
                    if lhs.tradeValueForRanking == rhs.tradeValueForRanking {
                        return lhs.changePercent > rhs.changePercent
                    }
                    return lhs.tradeValueForRanking > rhs.tradeValueForRanking
                }
                .prefix(3)
                .map(\.name)
                .joined(separator: ", ")
            let flowScore = log10(max(totalTradeValue, 1)) * 8
                + averageTradeValueRatio * 18
                + averageVolume * 8
                + positiveRatio * 14
                + max(-10, min(10, averageChange))
            return SectorInflowRank(
                market: market,
                sector: theme,
                totalTradeValue: totalTradeValue,
                averageTradeValueRatio: averageTradeValueRatio,
                averageVolumeRatio: averageVolume,
                averageChange: averageChange,
                positiveRatio: positiveRatio,
                leaders: leaders,
                score: flowScore
            )
        }
        .filter { $0.averageTradeValueRatio >= 0.7 || $0.averageVolumeRatio >= 1.0 }
        .sorted { lhs, rhs in
            if lhs.score == rhs.score {
                return lhs.totalTradeValue > rhs.totalTradeValue
            }
            return lhs.score > rhs.score
        }
        .prefix(5)
        .map { $0 }
    }

    private func makeMissedReview(watchlist: [ScannerResult]) -> [ScannerResult] {
        let watchTickers = Set(watchlist.map(\.ticker))
        return results
            .filter { marketFilter.matches($0) }
            .filter { marketFilter == .canada ? dividendFilter.matches($0) : true }
            .filter { !watchTickers.contains($0.ticker) && $0.missedMoveText != nil }
            .sorted { abs($0.changePercent) > abs($1.changePercent) }
            .prefix(5)
            .map { $0 }
    }

    private var activeMarkets: [String] {
        switch marketFilter {
        case .all:
            return ["국장", "미장", "캐나다"]
        case .korea:
            return ["국장"]
        case .us:
            return ["미장"]
        case .canada:
            return ["캐나다"]
        }
    }

    private func sectorSummaries(for market: String) -> [MarketSectorSummary] {
        let marketResults = results.filter { $0.marketText == market }
        let groups = Dictionary(grouping: marketResults) { result in
            result.sectorCategoryName
        }

        return groups.compactMap { category, items in
            guard items.count >= 2 else {
                return nil
            }
            let averageChange = items.map(\.changePercent).reduce(0, +) / Double(items.count)
            let risingCount = items.filter { $0.changePercent > 0 }.count
            let risingRatio = Double(risingCount) / Double(items.count)
            let leaders = items
                .sorted { lhs, rhs in
                    if lhs.changePercent == rhs.changePercent {
                        return lhs.score > rhs.score
                    }
                    return lhs.changePercent > rhs.changePercent
                }
                .prefix(3)
                .map(\.name)
                .joined(separator: ", ")
            return MarketSectorSummary(
                category: category,
                averageChange: averageChange,
                risingCount: risingCount,
                totalCount: items.count,
                risingRatio: risingRatio,
                leaders: leaders
            )
        }
        .sorted { lhs, rhs in
            if lhs.strengthScore == rhs.strengthScore {
                return lhs.averageChange > rhs.averageChange
            }
            return lhs.strengthScore > rhs.strengthScore
        }
        .prefix(marketFilter == .all ? 3 : 5)
        .map { $0 }
    }

    var body: some View {
        NavigationStack {
            ZStack {
                AppColors.background
                    .ignoresSafeArea()

                ScreenContainer(bottomPadding: isSearching ? 24 : 56) {
                        HeaderView(
                            topSummary: headerTopSummary,
                            topScore: results.first?.todayScore ?? 0,
                            totalCount: results.count,
                            buyCount: buyCountCache,
                            aiPickCount: aiPickCountCache,
                            liveQuoteCount: liveQuoteCountCache,
                            favoriteCount: favoriteTickers.count,
                            dataUpdatedAt: dataUpdatedAt,
                            quoteRefreshMessage: "\(remoteStatusText) · \(quoteRefreshMessage)",
                            isRefreshingQuotes: isRefreshingQuotes || isScannerRunning
                        ) {
                            Task {
                                await runRemoteScannerAndReload(mode: .quick)
                            }
                        } fullScanAction: {
                            Task {
                                await runRemoteScannerAndReload(mode: .full)
                            }
                        } testAlertAction: {
                            AlertManager.sendTestNotification()
                        }

                        let displayedResults = displayedResultsCache

                        MainTabBar(selectedTab: $selectedMainTab, tabs: visibleMainTabs)
                            .padding(.horizontal, 16)

                        switch selectedMainTab {
                        case .home:
                            HomeDashboardSection(
                                results: results,
                                watchlist: todayWatchlistCache,
                                sectorRanks: sectorInflowCache,
                                majorNews: majorNewsCache,
                                favoriteTickers: favoriteTickers,
                                aiPickDates: aiPickDates,
                                positionSummary: portfolioRiskSummary,
                                sectorSize: sectorInflowCardSize,
                                setSectorSize: { sectorInflowCardSizeRaw = $0.rawValue },
                                toggleFavorite: toggleFavorite
                            )
                            .padding(.horizontal, 16)

                        case .scanner:
                            ScannerBrowserSection(
                                filter: $filter,
                                marketFilter: $marketFilter,
                                dividendFilter: $dividendFilter,
                                results: results,
                                displayedResults: displayedResults,
                                favoriteTickers: favoriteTickers,
                                newAiPickTickers: newAiPickTickers,
                                aiPickDates: aiPickDates,
                                positionEvaluations: positionEvaluationsCache,
                                isSearching: isSearching
                            ) {
                                filter = .all
                                marketFilter = .all
                                dividendFilter = .all
                                refreshDerivedData()
                            } toggleFavorite: { result in
                                toggleFavorite(result)
                            }
                            .padding(.horizontal, 16)

                        case .ai:
                            AIAnalysisHomeSection(
                                allResults: results,
                                watchlist: todayWatchlistCache,
                                leadingCandidates: leadingCandidatesCache,
                                missedCandidates: missedCandidatesCache,
                                riskCandidates: riskCandidatesCache,
                                keywordCandidates: keywordCandidatesCache,
                                flowRadar: flowRadarCache,
                                remoteConfig: remoteConfig,
                                favoriteTickers: favoriteTickers,
                                aiPickDates: aiPickDates,
                                toggleFavorite: toggleFavorite
                            )
                            .padding(.horizontal, 16)

                        case .watchlist:
                            WatchlistHomeSection(
                                favorites: results.filter { favoriteTickers.contains($0.ticker) },
                                positionSummary: portfolioRiskSummary,
                                favoriteTickers: favoriteTickers,
                                newAiPickTickers: newAiPickTickers,
                                aiPickDates: aiPickDates,
                                positionEvaluations: positionEvaluationsCache,
                                toggleFavorite: toggleFavorite
                            )
                            .padding(.horizontal, 16)

                        case .earnings:
                            EarningsCenterSection(
                                results: results,
                                selectedMarket: $earningsMarket,
                                selectedRange: $earningsRange,
                                selectedDate: $selectedEarningsDate,
                                favoriteTickers: favoriteTickers,
                                positionTickers: Set(PositionStore.loadAll().keys),
                                toggleFavorite: toggleFavorite
                            )
                            .padding(.horizontal, 16)

                        case .market:
                            MarketHomeSection(
                                results: results,
                                selectedMarket: $moversMarket,
                                selectedCategory: $moversCategory,
                                selectedSort: $moversSort,
                                selectedExchange: $moversExchange,
                                selectedStockType: $moversStockType,
                                selectedSector: $moversSector,
                                sectorRanks: sectorInflowCache,
                                marketSections: marketStrengthSectionsCache,
                                flowRadar: flowRadarCache,
                                topGainers: topGainersCache,
                                topLosers: topLosersCache,
                                sectorSize: sectorInflowCardSize,
                                setSectorSize: { sectorInflowCardSizeRaw = $0.rawValue },
                                favoriteTickers: favoriteTickers,
                                aiPickDates: aiPickDates,
                                toggleFavorite: toggleFavorite
                            )
                            .padding(.horizontal, 16)

                        case .settings:
                            SettingsHomeSection(
                                remoteStatusText: remoteStatusText,
                                quoteRefreshMessage: quoteRefreshMessage,
                                dataUpdatedAt: dataUpdatedAt,
                                totalCount: results.count,
                                bugReports: bugReports,
                                bugReportSyncText: bugReportSyncText,
                                temporaryAdminDeviceEnabled: temporaryAdminDeviceEnabled,
                                showServerSettings: {
                                    showServerSettings = true
                                },
                                showAdminUnlock: {
                                    showAdminUnlockSheet = true
                                },
                                showBugReport: {
                                    showBugReportSheet = true
                                },
                                uploadBugReports: {
                                    Task { await uploadBugReportsToServer() }
                                },
                                downloadBugReports: {
                                    Task { await downloadBugReportsFromServer() }
                                },
                                syncBugReports: {
                                    Task { await syncBugReportsWithServer() }
                                },
                                gitSyncBugReports: {
                                    Task { await syncBugReportsFromGit() }
                                },
                                checkBugServerStatus: {
                                    Task { await checkBugReportServerStatus() }
                                },
                                updateBugStatus: { report, status in
                                    Task { await updateBugReportStatusOnServer(report, status: status) }
                                },
                                updateBugReport: { report in
                                    Task { await updateBugReportOnServer(report) }
                                },
                                runQuickScan: {
                                    Task { await runRemoteScannerAndReload(mode: .quick) }
                                },
                                runFullScan: {
                                    Task { await runRemoteScannerAndReload(mode: .full) }
                                }
                            )
                            .padding(.horizontal, 16)

                        case .admin:
                            AdminCenterSection(
                                reports: bugReports,
                                syncStatusText: bugReportSyncText,
                                showBugReport: {
                                    showBugReportSheet = true
                                },
                                refreshReports: {
                                    Task { await syncBugReportsWithServer() }
                                },
                                uploadReports: {
                                    Task { await uploadBugReportsToServer() }
                                },
                                downloadReports: {
                                    Task { await downloadBugReportsFromServer() }
                                },
                                gitSyncReports: {
                                    Task { await syncBugReportsFromGit() }
                                },
                                checkServerStatus: {
                                    Task { await checkBugReportServerStatus() }
                                },
                                updateStatus: { report, status in
                                    Task { await updateBugReportStatusOnServer(report, status: status) }
                                },
                                updateReport: { report in
                                    Task { await updateBugReportOnServer(report) }
                                }
                            )
                            .padding(.horizontal, 16)
                        }
                }
                .refreshable {
                    await runRemoteScannerAndReload(mode: .quick)
                }
            }
            .navigationTitle("Market Scanner")
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $searchText, placement: .navigationBarDrawer(displayMode: .always), prompt: "종목명 또는 티커 검색")
            .preferredColorScheme(.dark)
            .toolbarBackground(AppColors.background, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    HStack(spacing: 10) {
                        Button {
                            showBugReportSheet = true
                        } label: {
                            Image(systemName: "ladybug.fill")
                        }
                        .accessibilityLabel("버그 신고")

                        Button {
                            showServerSettings = true
                        } label: {
                            Image(systemName: remoteConfig.isReady ? "cloud.fill" : "cloud")
                        }
                        .accessibilityLabel("서버 설정")
                    }
                }
            }
            .task {
                if !didLoadResults {
                    isLoadingInitialResults = true
                    remoteStatusText = "로컬 데이터 확인중"
                    let localResults = await Task.detached(priority: .userInitiated) {
                        CSVLoader.loadResults()
                    }.value

                    if localResults.isEmpty {
                        if let cached = MarketResultsCache.load(), !cached.results.isEmpty {
                            applyMarketResults(
                                cached.results,
                                source: .cache,
                                updatedAt: latestDataGeneratedAt(from: cached.results) ?? parseMobileIntelDate(cached.dataGeneratedAt) ?? cached.savedAt,
                                statusText: "캐시 데이터 \(cached.results.count)개 · Render 복구중"
                            )
                            didLoadResults = true
                            if remoteConfig.isReady {
                                await loadRemoteResults(force: true)
                            }
                        } else {
                            didLoadResults = true
                            dataLoadState = .failed
                            if remoteConfig.isReady {
                                remoteStatusText = "로컬/캐시 없음 · Render 복구중"
                                await loadRemoteResults(force: true)
                            } else {
                                remoteStatusText = "데이터 로딩 실패"
                            }
                        }
                    } else {
                        applyMarketResults(
                            localResults,
                            source: .cache,
                            updatedAt: latestDataGeneratedAt(from: localResults) ?? CSVLoader.resultsUpdatedAt(),
                            statusText: remoteConfig.isReady ? "로컬 \(localResults.count)개 · Render 수동 갱신 가능" : "로컬 \(localResults.count)개"
                        )
                        didLoadResults = true
                    }
                    isLoadingInitialResults = false
                    if remoteConfig.isReady {
                        Task {
                            await loadRemoteResults(force: true)
                            await refreshVisibleQuotes(force: true)
                        }
                        Task {
                            await syncBugReportsWithServer()
                        }
                    }
                }
                AlertManager.requestAuthorization()
                AlertManager.sendOneTimeLaunchTest()
                Task {
                    try? await Task.sleep(for: .seconds(5))
                    await refreshVisibleQuotes(startup: true)
                }
            }
            .onChange(of: filter) { _, _ in
                refreshDerivedData()
                Task { await refreshVisibleQuotes() }
            }
            .onChange(of: marketFilter) { _, newValue in
                if newValue == .canada {
                    filter = .all
                } else {
                    dividendFilter = .all
                }
                refreshDerivedData()
                Task { await refreshVisibleQuotes() }
            }
            .onChange(of: dividendFilter) { _, _ in
                refreshDerivedData()
                Task { await refreshVisibleQuotes() }
            }
            .onChange(of: searchText) { _, _ in
                searchRefreshTask?.cancel()
                searchRefreshTask = Task {
                    try? await Task.sleep(for: .milliseconds(140))
                    guard !Task.isCancelled else {
                        return
                    }
                    await MainActor.run {
                        refreshDerivedData()
                    }
                }
            }
            .onReceive(quoteRefreshTimer) { _ in
                guard !isSearching else {
                    return
                }
                if shouldReduceData, let lastQuoteRefresh, Date().timeIntervalSince(lastQuoteRefresh) < 600 {
                    return
                }
                Task { await refreshVisibleQuotes() }
            }
            .onReceive(scannerStatusTimer) { _ in
                guard remoteConfig.isReady, !isSearching else {
                    return
                }
                Task { await refreshRemoteStatusAndPullIfNew() }
            }
            .onReceive(bugReportSyncTimer) { _ in
                guard remoteConfig.isReady else {
                    return
                }
                Task { await syncBugReportsWithServer() }
            }
            .onReceive(favoriteNewsTimer) { _ in
                Task { await checkFavoriteImpactNewsIfNeeded() }
            }
            .onChange(of: temporaryAdminDeviceEnabled) { _, enabled in
                if !enabled, selectedMainTab == .admin {
                    selectedMainTab = .settings
                }
            }
            .sheet(isPresented: $showServerSettings) {
                ServerSettingsView(config: remoteConfig) { updatedConfig in
                    remoteConfig = updatedConfig
                    RemoteServerStore.save(updatedConfig)
                    Task {
                        await loadRemoteResults(force: true)
                        await refreshVisibleQuotes(force: true)
                        await syncBugReportsWithServer()
                    }
                }
            }
            .sheet(isPresented: $showAdminUnlockSheet) {
                AdminUnlockView(config: remoteConfig) {
                    temporaryAdminDeviceEnabled = true
                    selectedMainTab = .admin
                    Task { await syncBugReportsWithServer() }
                }
            }
            .sheet(isPresented: $showBugReportSheet) {
                BugReportEditorView(context: makeBugReportContext()) { report in
                    Task { await submitBugReportToServer(report) }
                }
            }
            .overlay {
                if isLoadingInitialResults {
                    ProgressView(remoteStatusText)
                        .padding(18)
                        .background(AppColors.panel)
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .stroke(AppColors.border, lineWidth: 1)
                        )
                } else if didLoadResults && results.isEmpty {
                    ContentUnavailableView(
                        "결과 없음",
                        systemImage: "chart.line.uptrend.xyaxis",
                        description: Text("결과 파일을 다시 넣어주세요.")
                    )
                }
            }
        }
    }

    private func makeBugReportContext() -> BugReportContext {
        let visible = displayedResultsCache
        let matched = relatedBugResult(from: visible)
        let screen = selectedMainTab.title
        let market = matched?.marketText ?? automaticBugMarketText
        let ticker = matched?.ticker ?? inferredTickerFromSearch
        let priceText = matched?.formattedPrice ?? ""
        let updateText = dataUpdatedAt.map { AppDateTime.localString(from: $0, format: "yyyy-MM-dd HH:mm:ss") } ?? "갱신 시각 없음"
        let snapshotParts = [
            ticker.isEmpty ? nil : "티커 \(ticker)",
            priceText.isEmpty ? nil : "표시 가격 \(priceText)",
            "화면 \(screen)",
            "시장 \(market)",
            "데이터 \(remoteStatusText)",
            "시세 \(quoteRefreshMessage)",
            "업데이트 \(updateText)"
        ].compactMap { $0 }
        return BugReportContext(
            relatedTicker: ticker,
            relatedName: matched?.name ?? "",
            screen: screen,
            market: market,
            snapshot: snapshotParts.joined(separator: " · ")
        )
    }

    @MainActor
    private func syncBugReportsWithServer() async {
        guard remoteConfig.isReady else {
            bugReportSyncText = "서버 설정 필요"
            return
        }
        do {
            _ = try? await BugReportRemoteSync.gitSync(config: remoteConfig)
            let response = try await BugReportRemoteSync.fetch(config: remoteConfig)
            bugReports = BugReportStore.replaceFromServer(response.reports)
            let timeText = AppDateTime.localString(from: Date(), format: "HH:mm:ss")
            bugReportSyncText = bugSyncStatusText(prefix: "전체 동기화 완료", response: response, localCount: bugReports.count, timeText: timeText)
        } catch {
            bugReportSyncText = "신고 동기화 실패 · \(BugReportRemoteSync.userMessage(for: error))"
        }
    }

    @MainActor
    private func submitBugReportToServer(_ report: BugReport) async {
        guard remoteConfig.isReady else {
            bugReportSyncText = "신고 등록 실패 · 서버 설정 필요"
            return
        }
        var nextReport = report
        nextReport.markUpdated(action: "신고 등록", detail: report.titleText)
        do {
            _ = try await BugReportRemoteSync.sync(reports: [nextReport], config: remoteConfig)
            let fetched = try await BugReportRemoteSync.fetch(config: remoteConfig)
            bugReports = BugReportStore.replaceFromServer(fetched.reports)
            let serverIDs = Set(fetched.reports.map(\.id))
            let timeText = AppDateTime.localString(from: Date(), format: "HH:mm:ss")
            if serverIDs.contains(nextReport.id) {
                bugReportSyncText = bugSyncStatusText(prefix: "신고 등록 완료", response: fetched, localCount: bugReports.count, timeText: timeText)
            } else {
                bugReportSyncText = "신고 등록 확인 실패 · 서버 \(fetched.reportCount)건 · 로컬 \(bugReports.count)건 · \(timeText)"
            }
        } catch {
            bugReportSyncText = "신고 등록 실패 · \(BugReportRemoteSync.userMessage(for: error))"
        }
    }

    @MainActor
    private func updateBugReportStatusOnServer(_ report: BugReport, status: BugReportStatus) async {
        guard remoteConfig.isReady else {
            bugReportSyncText = "상태 변경 실패 · 서버 설정 필요"
            return
        }
        var nextReport = report
        nextReport.status = status
        nextReport.markUpdated(action: "상태 변경", detail: status.title)
        await saveSingleBugReportToServer(nextReport, prefix: "상태 변경 완료")
    }

    @MainActor
    private func updateBugReportOnServer(_ report: BugReport) async {
        guard remoteConfig.isReady else {
            bugReportSyncText = "수정 이력 저장 실패 · 서버 설정 필요"
            return
        }
        var nextReport = report
        nextReport.markUpdated(action: "수정 이력 저장", detail: report.status.title)
        await saveSingleBugReportToServer(nextReport, prefix: "수정 이력 저장 완료")
    }

    @MainActor
    private func saveSingleBugReportToServer(_ report: BugReport, prefix: String) async {
        do {
            _ = try await BugReportRemoteSync.sync(reports: [report], config: remoteConfig)
            let fetched = try await BugReportRemoteSync.fetch(config: remoteConfig)
            bugReports = BugReportStore.replaceFromServer(fetched.reports)
            let serverIDs = Set(fetched.reports.map(\.id))
            let timeText = AppDateTime.localString(from: Date(), format: "HH:mm:ss")
            if serverIDs.contains(report.id) {
                bugReportSyncText = bugSyncStatusText(prefix: prefix, response: fetched, localCount: bugReports.count, timeText: timeText)
            } else {
                bugReportSyncText = "\(prefix) 확인 실패 · 서버 \(fetched.reportCount)건 · 로컬 \(bugReports.count)건 · \(timeText)"
            }
        } catch {
            bugReportSyncText = "\(prefix) 실패 · \(BugReportRemoteSync.userMessage(for: error))"
        }
    }

    @MainActor
    private func uploadBugReportsToServer(verifyIDs: Set<UUID> = []) async {
        guard remoteConfig.isReady else {
            bugReportSyncText = "서버 업로드 실패 · 서버 설정 필요"
            return
        }
        do {
            let uploadTargets = verifyIDs.isEmpty ? bugReports : bugReports.filter { verifyIDs.contains($0.id) }
            let response = try await BugReportRemoteSync.sync(reports: uploadTargets, config: remoteConfig)
            let fetched = try await BugReportRemoteSync.fetch(config: remoteConfig)
            bugReports = BugReportStore.replaceFromServer(fetched.reports)
            let serverIDs = Set(fetched.reports.map(\.id))
            let missing = verifyIDs.subtracting(serverIDs)
            let timeText = AppDateTime.localString(from: Date(), format: "HH:mm:ss")
            if missing.isEmpty {
                let verifyText = verifyIDs.isEmpty ? "서버 저장 확인 완료" : "서버 저장 확인 완료 · \(verifyIDs.count)건"
                bugReportSyncText = "\(bugSyncStatusText(prefix: "서버 업로드 성공", response: fetched, localCount: bugReports.count, timeText: timeText)) · \(verifyText)"
            } else {
                bugReportSyncText = "업로드 응답 성공 · 서버 저장 확인 실패 · 누락 \(missing.count)건"
            }
            if response.reports.isEmpty, !bugReports.isEmpty {
                bugReportSyncText = "업로드 응답은 성공했지만 서버 응답 목록 비어 있음 · 조회 \(fetched.reports.count)건"
            }
        } catch {
            bugReportSyncText = "서버 업로드 실패 · \(BugReportRemoteSync.userMessage(for: error))"
        }
    }

    @MainActor
    private func downloadBugReportsFromServer() async {
        guard remoteConfig.isReady else {
            bugReportSyncText = "서버 다운로드 실패 · 서버 설정 필요"
            return
        }
        do {
            let beforeIDs = Set(bugReports.map(\.id))
            let gitResponse = try await BugReportRemoteSync.gitSync(config: remoteConfig)
            let response = try await BugReportRemoteSync.fetch(config: remoteConfig)
            let incomingIDs = Set(response.reports.map(\.id))
            let newCount = incomingIDs.subtracting(beforeIDs).count
            bugReports = BugReportStore.replaceFromServer(response.reports)
            let timeText = AppDateTime.localString(from: Date(), format: "HH:mm:ss")
            let gitText = gitResponse.gitChanged.map { " · Git 자동연결 \($0)건" } ?? ""
            bugReportSyncText = "\(bugSyncStatusText(prefix: "다운로드 완료", response: response, localCount: bugReports.count, timeText: timeText)) · 신규 \(newCount)건\(gitText)"
        } catch {
            bugReportSyncText = "서버 다운로드 실패 · \(BugReportRemoteSync.userMessage(for: error))"
        }
    }

    @MainActor
    private func syncBugReportsFromGit() async {
        guard remoteConfig.isReady else {
            bugReportSyncText = "Git 반영 확인 실패 · 서버 설정 필요"
            return
        }
        do {
            let gitResponse = try await BugReportRemoteSync.gitSync(config: remoteConfig)
            let response = try await BugReportRemoteSync.fetch(config: remoteConfig)
            bugReports = BugReportStore.replaceFromServer(response.reports)
            let timeText = AppDateTime.localString(from: Date(), format: "HH:mm:ss")
            if let gitError = gitResponse.gitSyncError, !gitError.isEmpty {
                bugReportSyncText = "Git 반영 확인 실패 · \(gitError) · \(timeText)"
            } else {
                let unmatched = gitResponse.gitUnmatchedIDs ?? []
                let unmatchedText = unmatched.isEmpty ? "" : " · 미매칭 \(unmatched.joined(separator: ","))"
                bugReportSyncText = "\(bugSyncStatusText(prefix: "Git 반영 확인 완료", response: response, localCount: bugReports.count, timeText: timeText)) · 자동연결 \(gitResponse.gitChanged ?? 0)건\(unmatchedText)"
            }
        } catch {
            bugReportSyncText = "Git 반영 확인 실패 · \(BugReportRemoteSync.userMessage(for: error))"
        }
    }

    @MainActor
    private func checkBugReportServerStatus() async {
        guard remoteConfig.isReady else {
            bugReportSyncText = "서버 상태 확인 실패 · 서버 설정 필요"
            return
        }
        do {
            let response = try await BugReportRemoteSync.fetch(config: remoteConfig)
            bugReports = BugReportStore.replaceFromServer(response.reports)
            let timeText = AppDateTime.localString(from: Date(), format: "HH:mm:ss")
            bugReportSyncText = bugSyncStatusText(prefix: "서버 연결 🟢 · 인증 🟢 · 버그 API 🟢", response: response, localCount: bugReports.count, timeText: timeText)
        } catch {
            bugReportSyncText = "서버 상태 확인 실패 · \(BugReportRemoteSync.userMessage(for: error))"
        }
    }

    private func bugSyncStatusText(prefix: String, response: BugReportSyncResponse, localCount: Int, timeText: String) -> String {
        let serverCount = response.reportCount
        let syncState = serverCount == localCount ? "정상" : "SYNC_MISMATCH"
        let counts = "reported \(response.reportedCount ?? 0) · actionDone \(response.actionDoneCount ?? 0) · resolved \(response.resolvedCount ?? 0) · urgent \(response.urgentCount ?? 0)"
        let version = response.dataVersion ?? response.serverTimestamp ?? response.updatedAt ?? "version 없음"
        return "\(prefix) · 서버 \(serverCount)건 · 로컬 \(localCount)건 · \(syncState) · \(counts) · \(timeText) · \(version)"
    }

    private func relatedBugResult(from visible: [ScannerResult]) -> ScannerResult? {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else {
            return visible.first
        }
        let normalized = query.uppercased().replacingOccurrences(of: " ", with: "")
        return results.first {
            $0.ticker.uppercased() == normalized
                || $0.tickerCleanText.uppercased() == normalized
                || $0.name.localizedCaseInsensitiveContains(query)
        } ?? visible.first
    }

    private var inferredTickerFromSearch: String {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard query.range(of: #"^[A-Z0-9.]{1,10}$"#, options: .regularExpression) != nil else {
            return ""
        }
        return query
    }

    private var automaticBugMarketText: String {
        switch selectedMainTab {
        case .scanner:
            return marketFilter.title
        case .earnings:
            return earningsMarket == .korea ? "국장" : "미장"
        case .market:
            return moversMarket.shortTitle
        case .admin:
            return "공통"
        default:
            return "자동 기록"
        }
    }

    @discardableResult
    @MainActor
    private func loadRemoteResults(force: Bool) async -> Bool {
        guard remoteConfig.isReady else {
            applyCachedMarketData(reason: "서버 설정 없음")
            return false
        }
        if !force, remoteStatusText.hasPrefix("Render") {
            return false
        }

        remoteStatusText = "Render 확인중"
        do {
            let fetchLimit = force ? 1200 : 250
            let payload = try await fetchRemoteResultsPayloadWithRetry(limit: fetchLimit)
            let remoteResults = CSVLoader.results(from: payload.rows)
            guard !remoteResults.isEmpty else {
                applyCachedMarketData(reason: "Render 빈 응답")
                return false
            }
            if shouldRejectSparseRemotePayload(payload, remoteResults: remoteResults) {
                dataLoadState = .cache
                let totalText = payload.totalCount.map { " / 서버 전체 \($0)개" } ?? ""
                remoteStatusText = "Render 제한 응답 \(remoteResults.count)개\(totalText) · 마지막 업데이트 데이터 \(results.count)개 유지"
                lastRemoteFileUpdatedAt = payload.fileUpdatedAt ?? lastRemoteFileUpdatedAt
                return false
            }
            if shouldRejectStockUniverseDrop(remoteResults) {
                dataLoadState = .cache
                remoteStatusText = "Render 종목 누락 감지 · 마지막 업데이트 데이터 \(results.count)개 유지"
                lastRemoteFileUpdatedAt = payload.fileUpdatedAt ?? lastRemoteFileUpdatedAt
                return false
            }
            if shouldRejectRemoteCanadaDrop(remoteResults, payload: payload) {
                dataLoadState = .cache
                let localCanadaCount = canadaResultCount(in: results)
                let remoteCanadaCount = canadaResultCount(in: remoteResults)
                remoteStatusText = "Render 캐나다 \(remoteCanadaCount)개 · 기존 캐나다 \(localCanadaCount)개 유지"
                lastRemoteFileUpdatedAt = payload.fileUpdatedAt ?? lastRemoteFileUpdatedAt
                return false
            }
            if !results.isEmpty, remoteResults.count <= max(1, results.count / 10), results.count > 10 {
                dataLoadState = .cache
                remoteStatusText = "Render 결과 \(remoteResults.count)개 · 마지막 업데이트 데이터 \(results.count)개 표시"
                lastRemoteFileUpdatedAt = payload.fileUpdatedAt ?? lastRemoteFileUpdatedAt
                return false
            }
            let remoteGeneratedDate = latestDataGeneratedAt(from: remoteResults)
                ?? parseMobileIntelDate(payload.dataGeneratedAt)
            let remoteFileDate = parseServerDate(payload.fileUpdatedAt)
            let remoteDate = latestDate(remoteGeneratedDate, remoteFileDate)
            let shouldRecoverSparseLocalData = results.count <= 1 && remoteResults.count > results.count
            if let localDate = dataUpdatedAt, !shouldRecoverSparseLocalData {
                if let remoteDate {
                    if remoteDate.addingTimeInterval(300) < localDate {
                        remoteStatusText = "Render 오래됨 \(AppDateTime.shortLocalString(from: remoteDate)) · 로컬 유지"
                        lastRemoteFileUpdatedAt = payload.fileUpdatedAt ?? lastRemoteFileUpdatedAt
                        return false
                    }
                } else {
                    remoteStatusText = "Render 생성시각 없음 · 로컬 유지"
                    lastRemoteFileUpdatedAt = payload.fileUpdatedAt ?? lastRemoteFileUpdatedAt
                    return false
                }
            }
            applyMarketResults(
                remoteResults,
                source: .latest,
                updatedAt: remoteDate ?? Date(),
                statusText: nil
            )
            MarketResultsCache.save(payload: payload)
            lastRemoteFileUpdatedAt = payload.fileUpdatedAt ?? lastRemoteFileUpdatedAt
            remoteFailureCount = 0
            let updatedText = dataUpdatedAt.map { " · \(AppDateTime.shortLocalString(from: $0))" } ?? ""
            remoteStatusText = "Render \(remoteResults.count)개\(updatedText)"
            return true
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            applyCachedMarketData(reason: message)
            return false
        }
    }

    private func shouldRejectSparseRemotePayload(_ payload: ResultsPayload, remoteResults: [ScannerResult]) -> Bool {
        let totalCount = payload.totalCount ?? payload.count
        let hasFullUniverseHint = totalCount >= 500 || (payload.totalMarketCounts?.values.reduce(0, +) ?? 0) >= 500
        if payload.limited == true && hasFullUniverseHint && remoteResults.count < min(totalCount, 500) {
            return true
        }
        if totalCount >= 500 && remoteResults.count < 500 {
            return true
        }
        if (payload.totalCanadaRows ?? payload.canadaRows ?? 0) >= 50 && canadaResultCount(in: remoteResults) == 0 {
            return true
        }
        return false
    }

    @MainActor
    private func applyMarketResults(_ newResults: [ScannerResult], source: MarketDataLoadState, updatedAt: Date?, statusText: String?) {
        guard !newResults.isEmpty else {
            dataLoadState = .failed
            remoteStatusText = statusText ?? "데이터 로딩 실패"
            return
        }
        if shouldRejectCanadaDrop(newResults) {
            dataLoadState = .cache
            remoteStatusText = statusText ?? "캐나다 데이터 누락 감지 · 마지막 업데이트 데이터 유지"
            return
        }
        if shouldRejectStockUniverseDrop(newResults) {
            dataLoadState = .cache
            remoteStatusText = statusText ?? "종목 누락 감지 · 마지막 업데이트 데이터 유지"
            return
        }
        results = newResults
        lastSuccessfulResults = newResults
        dataUpdatedAt = updatedAt ?? dataUpdatedAt ?? Date()
        dataLoadState = source
        if let statusText {
            remoteStatusText = statusText
        }
        updateNewAiPickMarkers()
        refreshDerivedData()
        refreshPositionEvaluations()
    }

    private func canadaResultCount(in values: [ScannerResult]) -> Int {
        values.filter { $0.marketText == "캐나다" }.count
    }

    private func shouldRejectCanadaDrop(_ newResults: [ScannerResult]) -> Bool {
        let previousCanadaCount = max(canadaResultCount(in: results), canadaResultCount(in: lastSuccessfulResults))
        guard previousCanadaCount >= 20 else {
            return false
        }
        return canadaResultCount(in: newResults) == 0
    }

    private func tickerSet(in values: [ScannerResult]) -> Set<String> {
        Set(values.map { $0.ticker.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() }.filter { !$0.isEmpty })
    }

    private func shouldRejectStockUniverseDrop(_ newResults: [ScannerResult]) -> Bool {
        let previousTickers = tickerSet(in: results).union(tickerSet(in: lastSuccessfulResults))
        guard previousTickers.count >= 20 else {
            return false
        }
        let newTickers = tickerSet(in: newResults)
        return !previousTickers.subtracting(newTickers).isEmpty
    }

    private func shouldRejectRemoteCanadaDrop(_ remoteResults: [ScannerResult], payload: ResultsPayload) -> Bool {
        let previousCanadaCount = max(canadaResultCount(in: results), canadaResultCount(in: lastSuccessfulResults))
        guard previousCanadaCount >= 20 else {
            return false
        }
        let remoteCanadaCount = payload.canadaRows ?? canadaResultCount(in: remoteResults)
        return remoteCanadaCount == 0
    }

    @MainActor
    private func applyCachedMarketData(reason: String) {
        remoteFailureCount += 1
        if !lastSuccessfulResults.isEmpty {
            results = lastSuccessfulResults
            dataLoadState = .cache
            refreshDerivedData()
            remoteStatusText = remoteFailureCount >= 3
                ? "최신 시장 데이터를 가져오지 못했습니다. 마지막 업데이트 데이터를 표시합니다."
                : "Render 실패 · 마지막 업데이트 데이터 표시 · \(reason)"
            return
        }
        if let cached = MarketResultsCache.load(), !cached.results.isEmpty {
            applyMarketResults(
                cached.results,
                source: .cache,
                updatedAt: latestDataGeneratedAt(from: cached.results) ?? parseMobileIntelDate(cached.dataGeneratedAt) ?? cached.savedAt,
                statusText: remoteFailureCount >= 3
                    ? "최신 시장 데이터를 가져오지 못했습니다. 마지막 업데이트 데이터를 표시합니다."
                    : "Render 실패 · 캐시 데이터 \(cached.results.count)개 표시"
            )
            return
        }
        results = []
        dataLoadState = .failed
        refreshDerivedData()
        remoteStatusText = "데이터 로딩 실패 · \(reason)"
    }

    @MainActor
    private enum RemoteScanMode {
        case quick
        case full

        var apiValue: String {
            switch self {
            case .quick: return "quick"
            case .full: return "full"
            }
        }

        var title: String {
            switch self {
            case .quick: return "빠른 스캔"
            case .full: return "전체 스캔"
            }
        }
    }

    @MainActor
    private func startRemoteScannerRun(mode: RemoteScanMode = .quick) async {
        guard remoteConfig.isReady else {
            remoteStatusText = "서버 설정 필요"
            return
        }
        do {
            let payload = try await RemoteMarketAPI.startScanner(config: remoteConfig, mode: mode.apiValue)
            isScannerRunning = payload.running || payload.status?.running == true
            if payload.started {
                remoteStatusText = "\(mode.title) 실행중 · 화면 사용 가능"
            } else {
                remoteStatusText = payload.message
            }
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            remoteStatusText = "스캐너 요청 실패 · \(message)"
        }
    }

    @MainActor
    private func runRemoteScannerAndReload(mode: RemoteScanMode = .quick) async {
        guard remoteConfig.isReady else {
            remoteStatusText = "서버 설정 필요"
            return
        }
        guard !isScannerRunning else {
            remoteStatusText = scannerProgressText(message: "이미 스캐너 실행중", progress: scannerProgress)
            return
        }

        do {
            remoteStatusText = "\(mode.title) 준비중 · 서버 상태 확인"
            let status = try await RemoteMarketAPI.fetchStatus(config: remoteConfig)
            remoteStatusText = "서버 정상 \(status.rows)개 · 최신 데이터 재조회"
            let quick = try? await RemoteMarketAPI.quickRefresh(config: remoteConfig)
            if let quick {
                scannerProgress = quick.status?.progress ?? 100
                remoteStatusText = "빠른 갱신 완료 · \(quick.count)개 재조회중"
            }
            await loadRemoteResults(force: true)
            await refreshVisibleQuotes(force: true)

            let payload = try await RemoteMarketAPI.startScanner(config: remoteConfig, mode: mode.apiValue)
            isScannerRunning = payload.running || payload.status?.running == true
            scannerProgress = payload.status?.progress ?? 0
            remoteStatusText = scannerProgressText(
                message: payload.started ? "\(mode.title) 실행중 · 화면 사용 가능" : payload.message,
                progress: scannerProgress
            )

            if payload.skipped == true || payload.reason == "cooldown" {
                isScannerRunning = false
                scannerProgress = 100
                remoteStatusText = payload.message
                await loadRemoteResults(force: true)
                await refreshVisibleQuotes(force: true)
                return
            }

            remoteStatusText = scannerProgressText(
                message: "\(mode.title) 요청 완료 · 기존 데이터 먼저 표시",
                progress: max(scannerProgress, 1)
            )
            await loadRemoteResults(force: true)
            await refreshVisibleQuotes(force: true)
        } catch {
            isScannerRunning = false
            scannerProgress = 0
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            remoteStatusText = "스캐너 요청 실패 · \(message)"
        }
    }

    @MainActor
    private func waitForRemoteScannerCompletion() async -> Bool {
        for _ in 0..<150 {
            do {
                try? await Task.sleep(for: .seconds(4))
                let payload = try await RemoteMarketAPI.fetchScannerStatus(config: remoteConfig)
                isScannerRunning = payload.status.running
                scannerProgress = payload.status.progress ?? scannerProgress
                remoteStatusText = scannerProgressText(
                    message: payload.status.message.isEmpty ? "스캐너 실행중" : payload.status.message,
                    progress: scannerProgress
                )
                if let remoteFileUpdatedAt = payload.status.fileUpdatedAt,
                   !remoteFileUpdatedAt.isEmpty,
                   remoteFileUpdatedAt != lastRemoteFileUpdatedAt {
                    remoteStatusText = "부분 데이터 수신 · 즉시 반영중"
                    let didApply = await loadRemoteResults(force: true)
                    if didApply {
                        await refreshVisibleQuotes(force: true)
                    } else {
                        lastRemoteFileUpdatedAt = remoteFileUpdatedAt
                    }
                }

                if payload.status.running {
                    continue
                }

                if payload.status.state == "completed" || payload.status.state == "partial" || payload.status.state == "uploaded" {
                    scannerProgress = 100
                    remoteStatusText = "최신 데이터 갱신 완료 · 재로드중"
                    return true
                }

                remoteStatusText = payload.status.message.isEmpty ? "스캐너 종료 · 상태 확인 필요" : payload.status.message
                return false
            } catch {
                let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                remoteStatusText = "스캐너 상태 확인 실패 · \(message)"
            }
        }

        isScannerRunning = false
        remoteStatusText = "스캐너 확인 시간 초과"
        return false
    }

    private func scannerProgressText(message: String, progress: Int) -> String {
        if message.contains("%") {
            return message
        }
        if progress > 0 {
            return "\(message) · \(min(max(progress, 0), 100))%"
        }
        return message
    }

    @MainActor
    private func refreshScannerStatusAndPullIfDone() async {
        guard remoteConfig.isReady else {
            isScannerRunning = false
            return
        }
        do {
            let payload = try await RemoteMarketAPI.fetchScannerStatus(config: remoteConfig)
            let staleRunning = isStaleRunningScannerStatus(payload.status)
            isScannerRunning = payload.status.running && !staleRunning
            scannerProgress = payload.status.progress ?? scannerProgress
            if staleRunning {
                scannerProgress = 100
                remoteStatusText = "스캐너 상태 복구 · 최신 데이터 재조회"
                await loadRemoteResults(force: true)
                await refreshVisibleQuotes(force: true)
                return
            }
            if let remoteFileUpdatedAt = payload.status.fileUpdatedAt,
               !remoteFileUpdatedAt.isEmpty,
               remoteFileUpdatedAt != lastRemoteFileUpdatedAt {
                remoteStatusText = "부분 데이터 수신 · 즉시 반영중"
                let didApply = await loadRemoteResults(force: true)
                if didApply {
                    await refreshVisibleQuotes(force: true)
                } else {
                    lastRemoteFileUpdatedAt = remoteFileUpdatedAt
                }
            }
            if payload.status.running {
                remoteStatusText = scannerProgressText(
                    message: payload.status.message.isEmpty ? "스캐너 실행중" : payload.status.message,
                    progress: scannerProgress
                )
                return
            }
            scannerProgress = payload.status.progress ?? 100
            remoteStatusText = payload.status.message.isEmpty ? "스캐너 완료" : payload.status.message
            if payload.status.state == "completed" || payload.status.state == "completed_with_warning" || payload.status.state == "partial" {
                await loadRemoteResults(force: true)
            }
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            remoteStatusText = "스캐너 상태 실패 · \(message)"
        }
    }

    private func fetchRemoteResultsWithRetry(limit: Int) async throws -> [ScannerResult] {
        let payload = try await fetchRemoteResultsPayloadWithRetry(limit: limit)
        return CSVLoader.results(from: payload.rows)
    }

    private func fetchRemoteResultsPayloadWithRetry(limit: Int) async throws -> ResultsPayload {
        var lastError: Error?
        for attempt in 0..<3 {
            do {
                return try await RemoteMarketAPI.fetchResultsPayload(config: remoteConfig, limit: limit)
            } catch {
                lastError = error
                if attempt == 0 {
                    continue
                }
                if attempt == 1 {
                    try? await Task.sleep(for: .seconds(7))
                }
            }
        }
        throw lastError ?? URLError(.cannotLoadFromNetwork)
    }

    @MainActor
    private func refreshRemoteStatusAndPullIfNew() async {
        guard remoteConfig.isReady, !isLoadingInitialResults else {
            return
        }
        guard !isCheckingRemoteStatus else {
            return
        }
        isCheckingRemoteStatus = true
        defer {
            isCheckingRemoteStatus = false
        }
        do {
            let status = try await RemoteMarketAPI.fetchStatus(config: remoteConfig)
            let staleRunning = status.scanner.map { isStaleRunningScannerStatus($0) } ?? false
            isScannerRunning = (status.scanner?.running ?? false) && !staleRunning
            scannerProgress = status.scanner?.progress ?? (isScannerRunning ? scannerProgress : 0)
            let remoteFileUpdatedAt = status.fileUpdatedAt
            if staleRunning {
                scannerProgress = 100
                remoteStatusText = "스캐너 상태 복구 · 최신 데이터 재조회"
                await loadRemoteResults(force: true)
                await refreshVisibleQuotes(force: true)
                return
            }
            if !remoteFileUpdatedAt.isEmpty && remoteFileUpdatedAt != lastRemoteFileUpdatedAt {
                remoteStatusText = "Render 새 데이터 감지 · 즉시 반영"
                let didApply = await loadRemoteResults(force: true)
                if didApply {
                    await refreshVisibleQuotes(force: true)
                } else {
                    lastRemoteFileUpdatedAt = remoteFileUpdatedAt
                }
                return
            }
            if isScannerRunning {
                remoteStatusText = scannerProgressText(
                    message: status.scanner?.message ?? "스캐너 실행중",
                    progress: scannerProgress
                )
                return
            }
            remoteStatusText = "Render 최신 유지"
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            remoteStatusText = "Render 상태 실패 · \(message)"
        }
    }

    @MainActor
    private func refreshRemoteStatus() async {
        guard remoteConfig.isReady, !isLoadingInitialResults else {
            return
        }
        guard !isCheckingRemoteStatus else {
            return
        }
        isCheckingRemoteStatus = true
        defer {
            isCheckingRemoteStatus = false
        }
        do {
            let status = try await RemoteMarketAPI.fetchStatus(config: remoteConfig)
            let staleRunning = status.scanner.map { isStaleRunningScannerStatus($0) } ?? false
            isScannerRunning = (status.scanner?.running ?? false) && !staleRunning
            scannerProgress = status.scanner?.progress ?? (isScannerRunning ? scannerProgress : 0)
            if staleRunning {
                scannerProgress = 100
                remoteStatusText = "스캐너 상태 복구 · 최신 데이터 재조회"
                await loadRemoteResults(force: true)
                return
            }
            if !status.fileUpdatedAt.isEmpty && status.fileUpdatedAt != lastRemoteFileUpdatedAt {
                remoteStatusText = "Render 새 데이터 감지 · 즉시 반영"
                let didApply = await loadRemoteResults(force: true)
                if !didApply {
                    lastRemoteFileUpdatedAt = status.fileUpdatedAt
                }
                return
            }
            if isScannerRunning {
                remoteStatusText = scannerProgressText(
                    message: status.scanner?.message ?? "스캐너 실행중",
                    progress: scannerProgress
                )
                return
            }
            if status.rows > results.count {
                remoteStatusText = "Render 최신 \(status.rows)개 · 새로고침 가능"
            } else {
                remoteStatusText = "로컬 \(results.count)개 · Render 정상"
            }
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            remoteStatusText = "Render 상태 실패 · \(message)"
        }
    }

    private func latestDataGeneratedAt(from results: [ScannerResult]) -> Date? {
        results
            .compactMap { AppDateTime.parseMobileIntelDate($0.mobileIntelGeneratedAt) }
            .max()
    }

    private func parseMobileIntelDate(_ value: String?) -> Date? {
        AppDateTime.parseMobileIntelDate(value)
    }

    private func parseServerDate(_ value: String?) -> Date? {
        let parsed = AppDateTime.parseServerDate(value)
        let displayed = parsed.map { AppDateTime.localString(from: $0) } ?? "-"
        AppDateTime.logConversion(raw: value, parsed: parsed, display: displayed, context: "server-date")
        return parsed
    }

    private func latestDate(_ dates: Date?...) -> Date? {
        dates.compactMap { $0 }.max()
    }

    private func isStaleRunningScannerStatus(_ status: ScannerStatus) -> Bool {
        guard status.running else {
            return false
        }
        let updatedAt = parseServerDate(status.updatedAt)
        let fileUpdatedAt = parseServerDate(status.fileUpdatedAt)
        if let updatedAt, Date().timeIntervalSince(updatedAt) > 20 * 60 {
            return true
        }
        if let fileUpdatedAt, let updatedAt, fileUpdatedAt > updatedAt {
            return true
        }
        if updatedAt == nil, fileUpdatedAt != nil {
            return true
        }
        return false
    }

    private func updateInsightHubVisibility(scrollOffset: CGFloat) {
        let delta = scrollOffset - lastScrollOffset
        lastScrollOffset = scrollOffset

        if scrollOffset > -12 {
            if !showInsightHub {
                withAnimation(.snappy(duration: 0.18)) {
                    showInsightHub = true
                }
            }
            return
        }

        if delta < -8, showInsightHub {
            withAnimation(.snappy(duration: 0.18)) {
                showInsightHub = false
            }
        } else if delta > 8, !showInsightHub {
            withAnimation(.snappy(duration: 0.18)) {
                showInsightHub = true
            }
        }
    }

    private func updateInsightHubVisibility(dragTranslation: CGFloat) {
        if dragTranslation < -10, showInsightHub {
            withAnimation(.snappy(duration: 0.16)) {
                showInsightHub = false
            }
        } else if dragTranslation > 10, !showInsightHub {
            withAnimation(.snappy(duration: 0.16)) {
                showInsightHub = true
            }
        }
    }

    @MainActor
    private func refreshVisibleQuotes(force: Bool = false, startup: Bool = false) async {
        guard !isRefreshingQuotes else {
            return
        }
        let minimumRefreshInterval: TimeInterval = shouldReduceData ? 180 : 15
        if !force, let lastQuoteRefresh, Date().timeIntervalSince(lastQuoteRefresh) < minimumRefreshInterval {
            return
        }

        let scanLimit: Int
        if shouldReduceData {
            scanLimit = 20
        } else if startup || lastQuoteRefresh == nil {
            scanLimit = 30
        } else {
            scanLimit = 80
        }
        let mustRefreshCount = results.filter { favoriteTickers.contains($0.ticker) || $0.isAiPick }.count
        let baseTickers = realtimeScanTickers(limit: max(scanLimit, mustRefreshCount))
        let tickers = (baseTickers + tigerUSSpaceTechHoldingTickers()).uniqued()
        guard !tickers.isEmpty else {
            return
        }

        isRefreshingQuotes = true
        defer {
            isRefreshingQuotes = false
        }
        quoteRefreshMessage = startup ? "빠른 가격 확인중" : (shouldReduceData ? "저데이터 스캔중" : "실시간 스캔중")
        async let fetchedUSDKRWRate = LiveQuoteService.fetchUSDKRWRate()
        let quotes = await LiveQuoteService.fetchQuotes(for: tickers)
        let shouldFetchFlows = !startup && !shouldReduceData
        let flows = shouldFetchFlows ? await InvestorFlowService.fetchFlows(for: tickers) : []
        if let rate = await fetchedUSDKRWRate, rate > 0 {
            CurrencyExchangeRateStore.saveUSDKRW(rate)
            usdKrwRate = rate
        }
        let quoteMap = Dictionary(uniqueKeysWithValues: quotes.map { ($0.ticker, $0) })
        let flowMap = Dictionary(uniqueKeysWithValues: flows.map { ($0.ticker, $0) })

        results = results.map { result in
            var updated = result
            if let quote = quoteMap[result.ticker.uppercased()] {
                updated.apply(liveQuote: quote)
            }
            updated.apply(liveETFQuotes: quoteMap)
            if let flow = flowMap[result.ticker.uppercased()] {
                updated.apply(investorFlow: flow)
            }
            return updated
        }
        lastQuoteRefresh = Date()
        let flowMessage = flowMap.isEmpty ? "" : " · 수급 \(flowMap.count)개"
        if quoteMap.isEmpty {
            quoteRefreshMessage = shouldReduceData ? "저데이터 지연 · 기존 가격 유지" : "실시간 가격 지연 · 기존 가격 유지"
        } else if shouldReduceData {
            quoteRefreshMessage = "저데이터 \(quoteMap.count)개 갱신 · \(CurrencyExchangeRateStore.statusText)"
        } else {
            quoteRefreshMessage = "\(quoteMap.count)개 실시간 가격 갱신\(flowMessage) · \(CurrencyExchangeRateStore.statusText)"
        }
        AlertManager.evaluate(results: results, favoriteTickers: favoriteTickers)
        refreshDerivedData()
        refreshPositionEvaluations()
    }

    private func realtimeScanTickers(limit: Int) -> [String] {
        let search = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        let baseResults: [ScannerResult]
        if !search.isEmpty {
            baseResults = displayedResultsCache
        } else {
            baseResults = results
                .filter { marketFilter.matches($0) }
                .filter { marketFilter == .canada ? dividendFilter.matches($0) : true }
        }

        let mustRefresh = results
            .filter { favoriteTickers.contains($0.ticker) || $0.isAiPick }
            .sorted { lhs, rhs in
                let lhsFavorite = favoriteTickers.contains(lhs.ticker)
                let rhsFavorite = favoriteTickers.contains(rhs.ticker)
                if lhsFavorite != rhsFavorite {
                    return lhsFavorite
                }
                return lhs.aiRankScore > rhs.aiRankScore
            }

        let canadaMustRefresh = results
            .filter { $0.marketText == "캐나다" }
            .filter { favoriteTickers.contains($0.ticker) || $0.isAiPick || $0.isBuyCandidate }
            .sorted { $0.flowRotationScore > $1.flowRotationScore }
            .prefix(45)

        let prioritized = (mustRefresh + Array(canadaMustRefresh) + baseResults).uniquedByTicker().sorted { lhs, rhs in
            let lhsPriority = realtimeScanPriority(lhs)
            let rhsPriority = realtimeScanPriority(rhs)
            if lhsPriority == rhsPriority {
                return lhs.score > rhs.score
            }
            return lhsPriority > rhsPriority
        }

        var seen = Set<String>()
        return prioritized.compactMap { result in
            let ticker = result.ticker.uppercased()
            guard !ticker.isEmpty, seen.insert(ticker).inserted else {
                return nil
            }
            return ticker
        }
        .prefix(limit)
        .map { $0 }
    }

    private func tigerUSSpaceTechHoldingTickers() -> [String] {
        results
            .filter(\.isTigerUSSpaceTechETF)
            .flatMap(\.etfHoldingTickersForLiveScan)
            .uniqued()
    }

    private func realtimeScanPriority(_ result: ScannerResult) -> Int {
        var value = 0
        if result.marketText == "국장" { value += 1000 }
        if result.marketText == "캐나다" && (result.isAiPick || favoriteTickers.contains(result.ticker)) { value += 900 }
        if favoriteTickers.contains(result.ticker) { value += 500 }
        if result.isAiPick { value += 300 }
        if result.isBuyCandidate { value += 200 }
        value += min(result.score, 150)
        value += Int(min(abs(result.changePercent), 20) * 5)
        value += Int(min(result.volumeRatio, 10) * 8)
        return value
    }

    private func updateNewAiPickMarkers() {
        let aiTickers = Set(results.filter(\.isAiPick).map(\.ticker))
        let allTickers = Set(results.map(\.ticker))
        let markerUpdate = NewAiPickStore.update(currentAiTickers: aiTickers, currentTickers: allTickers)
        newAiPickTickers = markerUpdate.newTickers
        aiPickDates = markerUpdate.recommendationDates
        AlertManager.sendNewAiPickNotifications(
            results: results.filter { markerUpdate.newTickers.contains($0.ticker) },
            recommendationDates: markerUpdate.recommendationDates
        )
    }

    private func refreshDerivedData() {
        displayedResultsCache = makeVisibleResults()
        buyCountCache = buyCandidates.count
        aiPickCountCache = results.filter(\.isAiPick).count
        liveQuoteCountCache = results.filter { $0.liveUpdatedAt != nil }.count

        guard !isSearching else {
            todayWatchlistCache = []
            abnormalEventsCache = []
            missedReviewCache = []
            flowRadarCache = .empty
            sectorInflowCache = []
            marketStrengthSectionsCache = []
            closingBuyCandidatesCache = []
            majorNewsCache = []
            leadingCandidatesCache = []
            missedCandidatesCache = []
            riskCandidatesCache = []
            keywordCandidatesCache = []
            topGainersCache = []
            topLosersCache = []
            return
        }

        let watchlist = makeTodayWatchlist()
        todayWatchlistCache = watchlist
        abnormalEventsCache = makeAbnormalEvents()
        missedReviewCache = makeMissedReview(watchlist: watchlist)
        flowRadarCache = makeMoneyFlowRadarData()
        sectorInflowCache = makeSectorInflowRanks()
        marketStrengthSectionsCache = makeMarketStrengthSections()
        closingBuyCandidatesCache = makeClosingBuyCandidates()
        majorNewsCache = makeMajorNewsItems()
        leadingCandidatesCache = makeLeadingCandidates()
        missedCandidatesCache = makeMissedCandidates()
        riskCandidatesCache = makeRiskCandidates()
        keywordCandidatesCache = makeKeywordCandidates()
        topGainersCache = makeTopGainers()
        topLosersCache = makeTopLosers()
    }

    private func refreshPositionEvaluations() {
        let positions = PositionStore.loadAll()
        guard !positions.isEmpty else {
            positionEvaluationsCache = [:]
            portfolioRiskSummary = .empty
            return
        }
        let evaluations: [String: PositionEvaluation] = Dictionary(
            uniqueKeysWithValues: results.compactMap { result in
                guard let position = positions[result.ticker],
                      let buyPrice = PositionEvaluation.parseNumber(position.priceText),
                      let totalAmount = PositionEvaluation.parseNumber(position.amountText),
                      let evaluation = PositionEvaluation(result: result, buyPrice: buyPrice, totalAmount: totalAmount) else {
                    return nil
                }
                return (result.ticker, evaluation)
            }
        )
        positionEvaluationsCache = evaluations
        portfolioRiskSummary = PortfolioRiskSummary.make(from: Array(evaluations.values))
    }

    private func toggleFavorite(_ result: ScannerResult) {
        if favoriteTickers.contains(result.ticker) {
            favoriteTickers.remove(result.ticker)
        } else {
            favoriteTickers.insert(result.ticker)
        }
        FavoriteStore.save(favoriteTickers)
        refreshDerivedData()
    }

    @MainActor
    private func checkFavoriteImpactNewsIfNeeded() async {
        guard !favoriteTickers.isEmpty, !results.isEmpty else {
            return
        }

        let key = "favorite-impact-news-last-check"
        let lastCheck = UserDefaults.standard.double(forKey: key)
        guard Date().timeIntervalSince1970 - lastCheck >= 3600 else {
            return
        }
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: key)

        let impactNews = await FavoriteNewsService.fetchImpactNews(
            for: results,
            favoriteTickers: favoriteTickers
        )
        AlertManager.sendImpactNewsNotifications(impactNews)
    }
}

private struct ResultDetailView: View {
    @StateObject private var networkUsageMonitor = NetworkUsageMonitor()
    @State private var result: ScannerResult
    @State private var isFavoriteState: Bool
    @State private var buyPriceText: String
    @State private var totalAmountText: String
    @State private var targetPriceText: String
    @State private var isRefreshingQuote = false
    @State private var isFetchingFavoriteNews = false
    @State private var showSummaryCard = true
    @State private var showFlowCard = true
    @State private var showNewsCard = true
    @State private var showTriggerCard = false
    @State private var showEngineCard = false
    @State private var showActionCard = false
    @State private var showEarningsCard = true
    @State private var showEarningsPredictionCard = true
    @State private var favoriteNewsItems: [StockNewsItem] = []
    @State private var favoriteNewsMessage = "내가 보는 종목만 최신 뉴스 확인"
    @State private var positionSaveMessage = "매수가와 총금액을 입력한 뒤 완료를 눌러 저장"
    @State private var lastDetailQuoteRefresh: Date?
    @State private var didStartInitialQuoteRefresh = false
    let recommendationDate: String?
    let toggleFavorite: () -> Void
    private let detailQuoteTimer = Timer.publish(every: 10, on: .main, in: .common).autoconnect()

    init(result: ScannerResult, isFavorite: Bool, recommendationDate: String?, toggleFavorite: @escaping () -> Void) {
        let savedPosition = PositionStore.load(ticker: result.ticker)
        _result = State(initialValue: result)
        _isFavoriteState = State(initialValue: isFavorite)
        _buyPriceText = State(initialValue: savedPosition?.priceText ?? "")
        _totalAmountText = State(initialValue: savedPosition?.amountText ?? "")
        _targetPriceText = State(initialValue: savedPosition?.targetText ?? "")
        self.recommendationDate = recommendationDate
        self.toggleFavorite = toggleFavorite
    }

    private var earningsPreview: EarningsPreview {
        EarningsPreview.make(for: result)
    }

    private var earningsPrediction: EarningsPrediction {
        EarningsPrediction.make(for: result, preview: earningsPreview)
    }

    var body: some View {
        ScreenContainer(horizontalPadding: 16, bottomPadding: 48) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("\(result.marketBadgeText) · \(result.ticker)")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(result.name)
                        .font(.largeTitle.bold())
                        .lineLimit(2)
                        .minimumScaleFactor(0.72)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(result.simpleReason)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))

                aiConclusionBar
                aiThreeLineSummary
                aiSummaryCard
                earningsScheduleCard
                if earningsPreview.isNear {
                    earningsPredictionCard
                    earningsFocusNotice
                }
                moneyFlowCard
                newsAnalysisCard
                triggerCard
                aiEngineDetailCard
                userActionCard

                DetailSection(title: "AI 애널리스트 평가", systemImage: "person.text.rectangle.fill", tint: analystTint) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(result.analystEvaluation)
                            .font(.title3.bold())
                            .foregroundStyle(analystTint)
                        Text("AI 점수 \(result.analystFinalScore)/100 · 매수 매력도 \(result.analystStars)")
                            .font(.subheadline.weight(.bold))
                        VStack(alignment: .leading, spacing: 6) {
                            ScoreMeter(label: "뉴스", value: result.analystNewsScore, tint: analystTint)
                            ScoreMeter(label: "수급", value: result.analystFlowScore, tint: analystTint)
                            ScoreMeter(label: "섹터", value: result.analystSectorScore, tint: analystTint)
                            ScoreMeter(label: "기술", value: result.analystTechnicalScore, tint: analystTint)
                        }
                        AnalystBulletBlock(title: "핵심 요약", points: result.analystSummaryPoints)
                        AnalystBulletBlock(title: "긍정 요인", points: result.analystPositivePoints)
                        AnalystBulletBlock(title: "부정 요인", points: result.analystNegativePoints)
                        Text("단기 전망: \(result.analystShortOutlook)")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                        Text("예상 범위: \(result.analystPriceRangeText)")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(analystTint)
                        Text("중기 전망: \(result.analystMidOutlook)")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                        Text("확정 매수 신호가 아니라 확률 기반 분석입니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                DetailSection(title: "AI EARLY SIGNAL", systemImage: "sparkle.magnifyingglass", tint: earlySignalTint) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(result.earlySignalStars)
                            .font(.title2.bold())
                            .foregroundStyle(earlySignalTint)
                        Text(result.earlySignalTitle)
                            .font(.headline)
                            .foregroundStyle(.primary)

                        AnalystBulletBlock(title: "근거", points: result.earlySignalReasons)

                        LazyVGrid(columns: [
                            GridItem(.flexible(), spacing: 8),
                            GridItem(.flexible(), spacing: 8)
                        ], alignment: .leading, spacing: 8) {
                            EarlySignalMetricBox(title: "확률", value: "\(result.earlySignalProbability)%", tint: earlySignalTint)
                            EarlySignalMetricBox(title: "예상 움직임", value: result.earlySignalMoveText, tint: earlySignalTint)
                            EarlySignalMetricBox(title: "신뢰도", value: result.earlySignalConfidence, tint: earlySignalTint)
                        }

                        Text("초기 신호는 빠른 변화를 잡기 위한 참고용입니다. 과열/악재가 있으면 신뢰도를 낮춰 봅니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                if result.hasEmergencySignal {
                    DetailSection(title: "긴급", systemImage: "exclamationmark.triangle.fill", tint: .red) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("거래량 \(result.emergencyVolumePercentText)")
                                .font(.title3.monospacedDigit().weight(.heavy))
                                .foregroundStyle(.red)
                            Text(result.name)
                                .font(.headline.bold())
                            VStack(alignment: .leading, spacing: 4) {
                                Text("원인")
                                    .font(.caption.bold())
                                    .foregroundStyle(.secondary)
                                Text(result.emergencyReasonText)
                                    .font(.subheadline.weight(.semibold))
                            }
                            HStack {
                                Text("상승 확률")
                                    .font(.caption.bold())
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Text(result.emergencyProbabilityText)
                                    .font(.headline.bold())
                                    .foregroundStyle(.red)
                            }
                            Text("급등 확정이 아니라 이벤트 감지입니다. 이미 크게 오른 상태면 추격 리스크를 같이 봅니다.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                DetailSection(title: result.notYetMovedTitle, systemImage: "arrow.up.forward.circle.fill", tint: notYetMovedTint) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("상승 확률 \(result.notYetMovedProbability)%")
                            .font(.title3.monospacedDigit().weight(.heavy))
                            .foregroundStyle(notYetMovedTint)
                        Text(result.notYetMovedSummary)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                        VStack(alignment: .leading, spacing: 7) {
                            Text("조건")
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                            ForEach(Array(result.notYetMovedConditions.enumerated()), id: \.offset) { _, item in
                                HStack(spacing: 8) {
                                    Image(systemName: item.1 ? "checkmark.circle.fill" : "circle")
                                        .foregroundStyle(item.1 ? .mint : .secondary)
                                    Text(item.0)
                                        .font(.caption.weight(.bold))
                                        .foregroundStyle(item.1 ? .primary : .secondary)
                                }
                            }
                        }
                    }
                }

                DetailSection(title: "AI 핵심 시그널", systemImage: "chart.line.uptrend.xyaxis.circle.fill", tint: result.quantTint) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(result.name)
                            .font(.headline.bold())
                        Text("점수: \(result.quantSignalScore)")
                            .font(.title3.monospacedDigit().weight(.heavy))
                            .foregroundStyle(result.quantTint)

                        VStack(alignment: .leading, spacing: 6) {
                            Text("현재 상태")
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                            Text(result.quantCurrentStateText)
                                .font(.subheadline.weight(.bold))

                            Text("AI 판단")
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                            Text(result.quantAiJudgementText)
                                .font(.subheadline.weight(.bold))

                            Text("한줄 요약")
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                            Text("\"\(result.quantOneLineSummary)\"")
                                .font(.subheadline.weight(.heavy))
                                .foregroundStyle(result.quantTint)
                        }
                        .padding(10)
                        .background(result.quantTint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(result.quantTint.opacity(0.16), lineWidth: 1))

                        Text("방향: \(result.quantDirection)")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(.secondary)

                        VStack(alignment: .leading, spacing: 5) {
                            Text("분석 항목")
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                            Text("- 최근 5일 수익률: \(result.quantFiveDayReturnText)")
                            Text("- 최근 20일 수익률: \(result.quantTwentyDayReturnText)")
                            Text("- 거래량 증가율: \(result.quantVolumeGrowthText)")
                            Text("- 기관 수급: \(result.quantInstitutionText)")
                            Text("- 외국인 수급: \(result.quantForeignText)")
                            Text("- 뉴스 감성 점수: \(result.quantNewsSentimentText)")
                            Text("- 공매도 변화: \(result.quantShortChangeText)")
                            Text("- 옵션 콜/풋 비율: \(result.quantOptionRatioText)")
                            Text("- 섹터 강도: \(result.quantSectorStrengthText)")
                            Text("- 동종 상대 강도: \(result.quantRelativeStrengthText)")
                        }
                        .font(.caption.weight(.semibold))

                        AnalystNumberedBlock(title: "근거", points: result.quantReasonPoints)
                        AnalystBulletBlock(title: "선행 신호", points: result.quantLeadingSignals)
                        AnalystBulletBlock(title: "리스크", points: result.quantRisks)

                        Text("공매도/옵션/실적 일정은 현재 원천 데이터가 없는 항목이라 확인 대기로 표시합니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                if shouldShowPredictionSection {
                    DetailSection(title: "예측 범위", systemImage: "scope", tint: predictionTint) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text(predictionScopeText)
                                .font(.caption.weight(.bold))
                                .foregroundStyle(.secondary)

                            LazyVGrid(columns: [
                                GridItem(.flexible(), spacing: 8),
                                GridItem(.flexible(), spacing: 8)
                            ], alignment: .leading, spacing: 8) {
                                DetailPriceBox(
                                    title: "상승 예상",
                                    price: result.upsidePriceText,
                                    percent: "+\(String(format: "%.1f", result.upsidePercent))%",
                                    tint: .red
                                )
                                DetailPriceBox(
                                    title: "하락 예상",
                                    price: result.downsidePriceText,
                                    percent: "-\(String(format: "%.1f", result.downsidePercent))%",
                                    tint: .blue
                                )
                            }

                            Label(newsImpactForecastText, systemImage: newsImpactIcon)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(predictionTint)
                                .padding(10)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(predictionTint.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))

                            Text("이 칸은 오늘 추천 종목과 관심종목에만 표시합니다. 호재/악재 영향 예측은 최초 감지 기준으로 고정해서 봅니다.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                DetailSection(title: "추천 후 결과", systemImage: "chart.xyaxis.line", tint: result.sinceScanTint) {
                    VStack(alignment: .leading, spacing: 9) {
                        Text(result.sinceScanText)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(result.sinceScanTint)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("현재가")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(.secondary)
                            Text(result.formattedPrice)
                                .font(.title2.monospacedDigit().weight(.heavy))
                                .foregroundStyle(.primary)
                                .minimumScaleFactor(0.75)
                        }
                        Text("추천가 \(result.scanPrice.isEmpty ? "-" : result.scanPrice)\(recommendationDateText)")
                            .foregroundStyle(.secondary)
                    }
                }

                if result.marketText == "국장" {
                    DetailSection(title: "추세선 평가", systemImage: "point.topleft.down.curvedto.point.bottomright.up", tint: result.trendlineTint) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(result.trendlineEvaluationText)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(result.trendlineTint)
                            if let supportBreakAlert = result.supportBreakAlertText {
                                Label(supportBreakAlert, systemImage: "exclamationmark.triangle.fill")
                                    .font(.caption.bold())
                                    .foregroundStyle(.orange)
                            }
                            Text("상단 \(result.trendBreakoutUpPriceText) · 하단 \(result.trendBreakdownPriceText)")
                                .foregroundStyle(.secondary)
                        }
                    }

                    DetailSection(title: "본장 전/초반 평가", systemImage: "clock.badge.checkmark", tint: result.preopenTint) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(result.preopenText)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(result.preopenTint)
                            Text("본장 전후 1시간 흐름으로 오늘 분위기가 우호적인지 확인합니다.")
                                .foregroundStyle(.secondary)
                        }
                    }

                    DetailSection(title: "1분봉 분석", systemImage: "waveform.path", tint: result.intraday1mTint) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(result.intraday1mText)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(result.intraday1mTint)
                            Text("짧은 흐름이라 추세 확인용으로만 보고, 단독 매수 근거로 쓰지는 않습니다.")
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                if result.isETF {
                    DetailSection(title: "ETF 괴리율", systemImage: "scalemass.fill", tint: result.etfPremiumTint) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(result.etfPremiumText)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(result.etfPremiumTint)
                            Text("괴리율은 현재가와 NAV 차이입니다. 1% 이상 벌어지면 추격 매수는 조심해서 봅니다.")
                                .foregroundStyle(.secondary)
                        }
                    }

                    DetailSection(title: "ETF NOW", systemImage: "waveform.path.ecg", tint: result.etfNowTint) {
                        VStack(alignment: .leading, spacing: 7) {
                            Text(result.etfNowText)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(result.etfNowTint)
                            Text("ETF NOW의 매수 신호와 평가율을 참고용으로 같이 표시합니다.")
                                .foregroundStyle(.secondary)
                        }
                    }

                    DetailSection(title: "ETF 보유비중", systemImage: "chart.pie.fill", tint: result.etfHoldingsTint) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(result.etfHoldingsText)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(result.etfHoldingsTint)
                            if result.etfHoldingsLines.isEmpty {
                                Text("상위 보유종목 비중과 당일 등락을 다음 스캔에서 확인합니다.")
                                    .foregroundStyle(.secondary)
                            } else {
                                ForEach(result.etfHoldingsLines, id: \.self) { line in
                                    Text(line)
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(.primary)
                                }
                            }
                            if !result.etfHoldingsSourceDate.isEmpty {
                                Text("구성 기준일 \(result.etfHoldingsSourceDate)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                DetailSection(title: "내 포지션 평가", systemImage: "person.crop.circle.badge.checkmark", tint: positionTint) {
                    VStack(alignment: .leading, spacing: 10) {
                        LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)], alignment: .leading, spacing: 8) {
                            PositionInputField(title: "매수가", text: $buyPriceText)
                            PositionInputField(title: "총금액", text: $totalAmountText)
                        }
                        PositionInputField(title: "목표가", text: $targetPriceText)

                        Button {
                            savePosition()
                            dismissKeyboard()
                            positionSaveMessage = hasCompletePositionInput ? "저장 완료 · 목표가 수익 계산까지 반영됩니다." : "입력값 저장 완료"
                        } label: {
                            Label("완료", systemImage: "checkmark.circle.fill")
                                .font(.subheadline.bold())
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 11)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.black)
                        .background(Color.mint, in: RoundedRectangle(cornerRadius: 8))

                        Text(positionSaveMessage)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)

                        if hasPositionInput {
                            Text(positionSummaryText)
                                .font(.subheadline.weight(.bold))
                                .foregroundStyle(positionTint)
                            Text(positionDetailText)
                                .foregroundStyle(.secondary)
                            if !positionDividendText.isEmpty {
                                Text(positionDividendText)
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.mint)
                            }
                            Text(positionPlanText)
                                .foregroundStyle(.secondary)
                            Text(positionJudgementText)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(positionTint)
                            Text(result.positionWarningText)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(result.newsRiskTint)
                            InvestmentSimulatorPanel(
                                result: result,
                                buyPrice: buyPrice,
                                totalAmount: totalAmount,
                                currentPrice: result.currentPrice,
                                manualTargetPrice: manualTargetPrice,
                                formatMoney: formatPositionMoney,
                                formatPrice: formatPositionPrice,
                                formatQuantity: formatQuantity
                            )
                        } else {
                            Text("매수가와 총금액을 넣으면 현재 평가, 익절가, 손절가를 계산합니다.")
                                .foregroundStyle(.secondary)
                            Text(result.positionWarningText)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(result.newsRiskTint)
                        }
                    }
                }

                if shouldShowPredictionSection {
                    Text("예상가는 현재 데이터 기준 참고 범위입니다. 실제 매수/매도 가격은 시장 상황에 따라 달라질 수 있습니다.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.top, 4)
                }
        }
        .background(AppColors.background)
        .navigationTitle("종목 상세")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: result.ticker) {
            guard !didStartInitialQuoteRefresh else {
                return
            }
            didStartInitialQuoteRefresh = true
            await Task.yield()
            await refreshDetailQuote()
        }
        .onReceive(detailQuoteTimer) { _ in
            if networkUsageMonitor.shouldReduceData,
               let lastDetailQuoteRefresh,
               Date().timeIntervalSince(lastDetailQuoteRefresh) < 300 {
                return
            }
            Task { await refreshDetailQuote() }
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    isFavoriteState.toggle()
                    toggleFavorite()
                } label: {
                    Image(systemName: isFavoriteState ? "star.fill" : "star")
                        .foregroundStyle(isFavoriteState ? .yellow : .secondary)
                }
                .accessibilityLabel(isFavoriteState ? "관심종목 해제" : "관심종목 추가")
            }
        }
    }

    private var aiConclusionText: String {
        let label = result.aiLabel.isEmpty ? result.action : result.aiLabel
        let risk = result.hasCriticalNewsRisk ? result.newsRiskAlertText : result.riskText
        return "\(label) · \(result.whyTodayText) · \(risk)"
    }

    private var aiConclusionBar: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "sparkles")
                .font(.subheadline.bold())
                .foregroundStyle(result.todayScoreTint)
            Text("AI 결론: \(aiConclusionText)")
                .font(.subheadline.weight(.heavy))
                .foregroundStyle(.primary)
                .lineLimit(2)
                .minimumScaleFactor(0.82)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(result.todayScoreTint.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(result.todayScoreTint.opacity(0.22), lineWidth: 1))
    }

    private var aiThreeLineSummary: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label("AI 핵심 요약", systemImage: "sparkles")
                .font(.headline)
                .foregroundStyle(result.todayScoreTint)
            ForEach(Array(aiSummaryLines.prefix(3).enumerated()), id: \.offset) { _, line in
                Text("• \(line)")
                    .font(.subheadline.weight(.heavy))
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private var aiSummaryLines: [String] {
        var lines: [String] = []
        if !result.whyTodayText.isEmpty {
            lines.append(result.whyTodayText)
        }
        if result.institutionNet > 0 || result.foreignNet > 0 {
            lines.append("기관/외국인 수급 유입 확인")
        } else {
            lines.append(result.moneyFlowText)
        }
        if result.hasCriticalNewsRisk {
            lines.append(result.newsRiskAlertText)
        } else if result.mobileNewsImpactScore > 20 || result.analystNewsScore >= 65 {
            lines.append("뉴스 흐름은 긍정 쪽으로 우세")
        } else {
            lines.append(result.riskText)
        }
        if earningsPreview.isNear {
            lines.insert("실적 발표 \(earningsPreview.dDayText)라 변동성 확대 구간", at: 0)
        }
        return lines.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    private var earningsScheduleCard: some View {
        CollapsibleDetailSection(
            title: earningsPreview.isNear ? "실적 발표 예정" : "실적 일정",
            summary: "\(earningsPreview.displayDate) · \(earningsPreview.dDayText) · \(earningsPreview.sessionText)",
            systemImage: "calendar.badge.clock",
            tint: earningsPreview.tint,
            isExpanded: $showEarningsCard
        ) {
            VStack(alignment: .leading, spacing: 10) {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)], alignment: .leading, spacing: 8) {
                    DetailMiniMetric(title: "다음 발표", value: earningsPreview.displayDate, tint: earningsPreview.tint)
                    DetailMiniMetric(title: "남은 시간", value: earningsPreview.dDayText, tint: earningsPreview.tint)
                    DetailMiniMetric(title: "발표 시간", value: earningsPreview.sessionText, tint: earningsPreview.tint)
                    DetailMiniMetric(title: "신뢰도", value: earningsPreview.sourceText, tint: .secondary)
                }
                Text(earningsPreview.notice)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var earningsPredictionCard: some View {
        CollapsibleDetailSection(
            title: "AI 실적 예측",
            summary: "상승 \(earningsPrediction.upsideProbability)% / 하락 \(earningsPrediction.downsideProbability)% · \(earningsPrediction.directionText)",
            systemImage: "chart.bar.xaxis",
            tint: earningsPrediction.tint,
            isExpanded: $showEarningsPredictionCard
        ) {
            VStack(alignment: .leading, spacing: 10) {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)], alignment: .leading, spacing: 8) {
                    DetailMiniMetric(title: "상승 확률", value: "\(earningsPrediction.upsideProbability)%", tint: .red)
                    DetailMiniMetric(title: "하락 확률", value: "\(earningsPrediction.downsideProbability)%", tint: .blue)
                    DetailMiniMetric(title: "예상 방향", value: earningsPrediction.directionText, tint: earningsPrediction.tint)
                    DetailMiniMetric(title: "예측 신뢰도", value: earningsPrediction.confidenceText, tint: earningsPrediction.tint)
                }
                AnalystBulletBlock(title: "핵심 이유", points: earningsPrediction.reasons)
                AnalystBulletBlock(title: "리스크 요인", points: earningsPrediction.risks)
                Text("실적 발표 전까지 뉴스, 수급, 섹터, 가격 반응에 따라 확률이 계속 바뀔 수 있습니다. 수익 보장 표현이 아닌 참고용 예측입니다.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var earningsFocusNotice: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "rectangle.compress.vertical")
                .foregroundStyle(.orange)
            Text("실적 임박 종목이라 상세 화면은 AI 판단, 실적 일정/예측, 수급, 뉴스 순서로 먼저 보이게 정리했습니다. 세부 지표는 접힌 카드에서 확인하세요.")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }

    private var aiSummaryCard: some View {
        CollapsibleDetailSection(
            title: "AI 종합 판단",
            summary: "Today Score \(result.todayScore) / \(result.aiLabel.isEmpty ? result.action : result.aiLabel)",
            systemImage: "sparkles",
            tint: result.todayScoreTint,
            isExpanded: $showSummaryCard
        ) {
            VStack(alignment: .leading, spacing: 10) {
                Text(result.todayScoreText)
                    .font(.title3.monospacedDigit().weight(.heavy))
                    .foregroundStyle(result.todayScoreTint)

                ScoreMeter(label: "TODAY", value: result.todayScore, tint: result.todayScoreTint)
                ScoreMeter(label: "AI추천", value: result.eventScore, tint: result.todayScoreTint)
                if result.additionalUpsideScore > 0 {
                    ScoreMeter(label: "추세지속", value: result.additionalUpsideScore, tint: result.isStrongTrendContinuation ? .mint : .orange)
                    HStack(spacing: 6) {
                        MiniMetricPill(title: "상승질", value: "\(result.additionalUpsideQualityScore)")
                        MiniMetricPill(title: "재료", value: "\(result.additionalUpsideMaterialScore)")
                        MiniMetricPill(title: "수급", value: "\(result.additionalUpsideFlowScore)")
                        MiniMetricPill(title: "회복", value: "\(result.additionalUpsideResilienceScore)")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true)
                    if result.additionalUpsideFailFast {
                        Text("소멸형 경고: \(result.additionalUpsideFailFastReason)")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(.orange)
                            .wrapInsideCard(lineLimit: 3)
                    }
                    Text(result.additionalUpsideSummary.isEmpty ? result.additionalUpsideLabel : result.additionalUpsideSummary)
                        .font(.caption.weight(.bold))
                        .foregroundStyle(result.isStrongTrendContinuation ? .mint : .secondary)
                        .wrapInsideCard(lineLimit: 3)
                    if !result.additionalUpsidePatternSummary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        Text("과거패턴: \(result.additionalUpsidePatternSummary)")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .wrapInsideCard(lineLimit: 2)
                    }
                }

                AnalystBulletBlock(
                    title: "오늘 볼 이유",
                    points: Array(([result.whyTodayText] + result.abnormalSignals).filter { !$0.isEmpty }.prefix(3))
                )

                AnalystBulletBlock(
                    title: "핵심 리스크",
                    points: Array([
                        result.hasCriticalNewsRisk ? result.newsRiskAlertText : result.riskText,
                        result.exclusionReasonText,
                        result.chaseRiskAlertText ?? "추격 위험 낮음"
                    ].filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }.prefix(2))
                )

                Text("한 줄 결론: \(aiConclusionText)")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(result.todayScoreTint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private var triggerCard: some View {
        CollapsibleDetailSection(
            title: "상승 / 하락 트리거",
            summary: "상승 \(reasonTags(from: result.upsideReason).count)개 / 하락 \(reasonTags(from: result.downsideReason).count)개",
            systemImage: "arrow.up.arrow.down.circle.fill",
            tint: .orange,
            isExpanded: $showTriggerCard
        ) {
            VStack(alignment: .leading, spacing: 12) {
                ReasonTagBlock(title: "상승이유", text: result.upsideReason, tint: .red)
                ReasonTagBlock(title: "하락이유", text: result.downsideReason, tint: .blue)
            }
        }
    }

    private var moneyFlowCard: some View {
        CollapsibleDetailSection(
            title: "자금 흐름 & 수급 신호",
            summary: "\(result.moneyFlowText) / \(result.supplyAnomalyAiText)",
            systemImage: "arrow.left.arrow.right.circle.fill",
            tint: result.supplyAnomalyTint,
            isExpanded: $showFlowCard
        ) {
            VStack(alignment: .leading, spacing: 10) {
                Label(result.moneyFlowText, systemImage: "person.2.fill")
                    .font(.subheadline.weight(.semibold))
                Label(result.programTradeText, systemImage: "cpu")
                    .font(.subheadline.weight(.semibold))
                Label(result.volumeSurgeText, systemImage: "chart.bar.fill")
                    .font(.subheadline.weight(.semibold))

                Text("섹터 자금 이동: \(result.flowRadarReason)")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

                VStack(alignment: .leading, spacing: 6) {
                    Text(result.supplyAnomalyTitleText)
                        .font(.caption.bold())
                        .foregroundStyle(result.supplyAnomalyTint)
                    Text(result.supplyTwentyDayText)
                    Text(result.supplyTodaySwitchText)
                    Text("AI 평가: \(result.supplyAnomalyAiText)")
                        .font(.caption.weight(.heavy))
                        .foregroundStyle(result.supplyAnomalyTint)
                    Text(result.supplyAnomalyDetailText)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(result.supplyAnomalyTint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(result.supplyAnomalyTint.opacity(0.16), lineWidth: 1))
            }
        }
    }

    private var newsAnalysisCard: some View {
        CollapsibleDetailSection(
            title: result.marketText == "국장" ? "뉴스 & AI 뉴스 분석" : "해외 뉴스 & AI 뉴스 분석",
            summary: newsCardSummaryText,
            systemImage: "newspaper.fill",
            tint: result.adaptiveNewsImpactTint,
            isExpanded: $showNewsCard
        ) {
            newsAnalysisContent
        }
    }

    @ViewBuilder
    private var newsAnalysisContent: some View {
        if result.marketText == "국장" {
            domesticNewsAnalysisContent
        } else if result.marketText == "캐나다" {
            canadaNewsAnalysisContent
        } else {
            overseasNewsAnalysisContent
        }
    }

    private var domesticNewsAnalysisContent: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(result.newsV2SummaryText)
                .font(.subheadline.weight(.heavy))
                .foregroundStyle(result.adaptiveNewsImpactTint)

            Text(result.newsFilterScoreText)
                .font(.caption.weight(.bold))
                .foregroundStyle(.secondary)

            Text(result.adaptiveNewsBasisText)
                .font(.caption.weight(.semibold))
            Text(result.adaptiveNewsExpectationText)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(result.newsV2EffectText)
                .font(.caption.weight(.bold))
                .foregroundStyle(.secondary)

            AnalystBulletBlock(title: "호재 요인", points: result.newsV2PositiveLines)
            AnalystBulletBlock(title: "악재 요인", points: result.newsV2NegativeLines)

            Text(result.newsV2CoreSignalText)
                .font(.caption.weight(.heavy))
                .foregroundStyle(result.adaptiveNewsImpactTint)
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(result.adaptiveNewsImpactTint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))

            if !result.localizedHeadlines.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    Text("주요 뉴스")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                    Text(result.localizedHeadlines)
                        .font(.caption.weight(.semibold))
                }
            }

            HStack(spacing: 8) {
                Text(result.positiveNewsText)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.red)
                Spacer(minLength: 8)
                Text(result.negativeNewsText)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.orange)
            }

            latestNewsButton
        }
    }

    private var overseasNewsAnalysisContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            OverseasNewsSummaryGrid(
                mood: overseasNewsMoodText,
                strength: overseasNewsStrengthText,
                shortImpact: overseasShortImpactText,
                reflection: overseasReflectionShortText,
                tint: result.adaptiveNewsImpactTint
            )

            VStack(alignment: .leading, spacing: 5) {
                Text("AI 한 줄 결론")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                Text(overseasNewsConclusionText)
                    .font(.subheadline.weight(.heavy))
                    .foregroundStyle(.primary)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(result.adaptiveNewsImpactTint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: 8) {
                Text("핵심 뉴스")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                ForEach(Array(overseasNewsItems.prefix(5).enumerated()), id: \.offset) { index, item in
                    OverseasNewsItemRow(index: index + 1, item: item, tint: result.adaptiveNewsImpactTint)
                }
            }

            AnalystBulletBlock(title: "뉴스 기준 상승 요인", points: overseasPositiveDrivers)
            AnalystBulletBlock(title: "뉴스 기준 리스크", points: overseasRiskDrivers)

            VStack(alignment: .leading, spacing: 5) {
                Text("오늘 볼 이유")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                ForEach(Array(overseasWatchReasons.prefix(3).enumerated()), id: \.offset) { _, item in
                    Text("- \(item)")
                        .font(.caption.weight(.semibold))
                }
            }

            VStack(alignment: .leading, spacing: 5) {
                Text("반영률 판단")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                Text("\(overseasReflectionShortText) · \(overseasReflectionDetailText)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: 5) {
                Text("해외 뉴스 기반 AI 요약 3줄")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                ForEach(Array(overseasThreeLineSummary.enumerated()), id: \.offset) { index, item in
                    Text("\(index + 1). \(item)")
                        .font(.caption.weight(.heavy))
                        .foregroundStyle(index == 2 ? result.adaptiveNewsImpactTint : .primary)
                }
            }

            latestNewsButton
        }
    }

    private var canadaNewsAnalysisContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 5) {
                Text(canadaNewsStatusTitle)
                    .font(.subheadline.weight(.heavy))
                    .foregroundStyle(result.adaptiveNewsImpactTint)
                Text(canadaNewsStatusDetail)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(result.adaptiveNewsImpactTint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))

            if result.canadaNewsItems.isEmpty {
                Text("최근 7일 내 종목과 정확히 매칭된 공식/신뢰 뉴스가 없습니다.")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    Text("캐나다 종목별 최신 뉴스")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                    ForEach(result.canadaNewsItems.prefix(5)) { item in
                        CanadaNewsItemRow(item: item)
                    }
                }
            }

            AnalystBulletBlock(title: "수집 기준", points: [
                "기업 공식 발표 / SEDAR+ / TMX / Reuters급 주요 언론 우선",
                "티커와 회사명 매칭이 확인된 뉴스만 표시",
                "24시간 뉴스 우선, 없으면 최근 7일까지만 표시"
            ])

            latestNewsButton
        }
    }

    private var latestNewsButton: some View {
        VStack(alignment: .leading, spacing: 7) {
            Button {
                Task { await fetchFavoriteNews() }
            } label: {
                Label(isFetchingFavoriteNews ? "뉴스 확인 중" : "이 종목 최신 뉴스 가져오기", systemImage: "arrow.clockwise")
                    .font(.caption.bold())
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 9)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.black)
            .background(Color.mint, in: RoundedRectangle(cornerRadius: 8))
            .disabled(isFetchingFavoriteNews)

            Text(favoriteNewsMessage)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)

            ForEach(favoriteNewsItems.prefix(3)) { item in
                FavoriteNewsRow(item: item)
            }
        }
    }

    private var newsCardSummaryText: String {
        if result.marketText == "국장" {
            return "\(result.mobileNewsImpactLabel.isEmpty ? result.newsActionText : result.mobileNewsImpactLabel) / \(result.newsV2LeadText)"
        }
        if result.marketText == "캐나다" {
            return canadaNewsStatusTitle
        }
        return "\(overseasNewsMoodText) · 강도 \(overseasNewsStrengthText) · \(overseasReflectionShortText)"
    }

    private var canadaNewsStatusTitle: String {
        if result.canadaNewsStatus == "ok" {
            return "공식/신뢰 뉴스 \(result.canadaNewsCount)건 · \(result.canadaNewsFreshness == "fresh_24h" ? "최근 24시간" : "최근 7일")"
        }
        if result.canadaNewsStatus == "cache" {
            return "최신 뉴스 수집 실패 · 캐시 뉴스 표시"
        }
        if result.canadaNewsStatus == "skipped" {
            return "캐나다 뉴스 수집 대기"
        }
        return "캐나다 공식/신뢰 뉴스 없음"
    }

    private var canadaNewsStatusDetail: String {
        let collected = result.canadaNewsCollectedAt.trimmingCharacters(in: .whitespacesAndNewlines)
        let sources = result.canadaNewsSources.trimmingCharacters(in: .whitespacesAndNewlines)
        let collectedText = collected.isEmpty ? "수집 시간 확인 전" : "수집 \(collected)"
        return sources.isEmpty ? collectedText : "\(collectedText) · \(sources)"
    }

    private var overseasNewsMoodText: String {
        if result.mobileNewsImpactScore >= 50 {
            return "긍정 우세"
        }
        if result.mobileNewsImpactScore >= 10 {
            return "약한 긍정"
        }
        if result.mobileNewsImpactScore <= -50 || result.hasCriticalNewsRisk {
            return "부정 우세"
        }
        if result.mobileNewsImpactScore <= -10 {
            return "약한 부정"
        }
        if result.newsActionText.contains("호재") {
            return "긍정 우세"
        }
        if result.newsActionText.contains("악재") {
            return "부정 우세"
        }
        return "혼조/중립"
    }

    private var overseasNewsStrengthText: String {
        let base = abs(result.mobileNewsImpactScore)
        let fallback = max(result.analystNewsScore, result.mobileNewsV2Strength * 10)
        return "\(max(base, fallback))"
    }

    private var overseasShortImpactText: String {
        if result.mobileNewsImpactScore >= 35 || (result.changePercent > 1.5 && result.volumeRatio >= 1.2) {
            return "상승 압력"
        }
        if result.mobileNewsImpactScore <= -35 || result.hasCriticalNewsRisk || result.changePercent < -2 {
            return "하락 압력"
        }
        if result.volumeRatio >= 2 {
            return "변동성 확대"
        }
        return "혼조"
    }

    private var overseasReflectionShortText: String {
        if result.isChaseRiskForAi || (result.changePercent >= 7 && result.volumeRatio >= 1.5) {
            return "이미 반영"
        }
        if abs(result.changePercent) >= 3 || result.volumeRatio >= 2 {
            return "일부 반영"
        }
        if abs(result.changePercent) < 1.5 && abs(result.mobileNewsImpactScore) >= 25 {
            return "미반영 가능"
        }
        return "해석 불확실"
    }

    private var overseasReflectionDetailText: String {
        if overseasReflectionShortText == "이미 반영" {
            return "뉴스 강도 대비 주가 반응이 먼저 크게 나온 상태라 추격은 조심합니다."
        }
        if overseasReflectionShortText == "일부 반영" {
            return "가격/거래량 반응은 시작됐지만 추가 뉴스와 수급 확인이 필요합니다."
        }
        if overseasReflectionShortText == "미반영 가능" {
            return "뉴스 강도 대비 가격 반응이 작아 후속 거래량이 붙는지 봅니다."
        }
        return "긍정/부정 재료가 섞여 있어 단기 방향보다 변동성 관리가 우선입니다."
    }

    private var overseasNewsConclusionText: String {
        if result.hasCriticalNewsRisk {
            return "부정 뉴스의 영향이 커서 단기 반등보다 리스크 해소 여부를 먼저 확인해야 합니다."
        }
        if overseasNewsMoodText.contains("긍정") && overseasReflectionShortText == "이미 반영" {
            return "호재 뉴스는 우세하지만 이미 주가가 반응한 구간이라 추격보다 눌림 확인이 유리합니다."
        }
        if overseasNewsMoodText.contains("긍정") {
            return "뉴스 흐름은 긍정 쪽이 우세하며 거래량이 붙으면 단기 모멘텀으로 연결될 수 있습니다."
        }
        if overseasNewsMoodText.contains("부정") {
            return "부정 뉴스가 단기 심리를 누르는 구간이라 지지선과 추가 악재 확산 여부가 중요합니다."
        }
        return "뉴스는 혼조라 단기 방향성보다 거래량, 섹터 흐름, 가격 반응을 같이 확인해야 합니다."
    }

    private var overseasNewsItems: [OverseasNewsDisplayItem] {
        let candidates = [
            result.localizedHeadlines,
            result.mobileNewsFocus,
            result.mobileNewsImpactSummary,
            result.newsOneLine,
            result.majorNewsText,
            result.newsV2CoreSignalText
        ]
        .flatMap { splitNewsCandidates($0) }
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty && !$0.contains("주요 뉴스 대기") && !$0.contains("분석 대기") }

        var unique: [String] = []
        for item in candidates {
            let normalized = item.lowercased()
            if !unique.contains(where: { normalized == $0.lowercased() }) {
                unique.append(item)
            }
        }

        if unique.isEmpty {
            unique = [
                "\(result.name) 관련 최신 해외 뉴스 원문 추가 확인 필요",
                "\(result.themeKey) 섹터 흐름과 거래량 반응 확인",
                "가격 반응 \(String(format: "%+.2f", result.changePercent))% · 거래량 \(String(format: "%.1f", result.volumeRatio))배"
            ]
        }

        return unique.prefix(5).map { title in
            makeOverseasNewsItem(title)
        }
    }

    private func splitNewsCandidates(_ text: String) -> [String] {
        text
            .replacingOccurrences(of: "AI 핵심 시그널:", with: "")
            .replacingOccurrences(of: "관련 섹터 영향:", with: "")
            .components(separatedBy: "|")
            .flatMap { $0.components(separatedBy: "\n") }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
    }

    private func makeOverseasNewsItem(_ title: String) -> OverseasNewsDisplayItem {
        let lower = title.lowercased()
        var tags: [String] = []
        var sentiment = "중립"
        var impact = "중간"
        var period = "단기"

        func has(_ keywords: [String]) -> Bool {
            keywords.contains { lower.contains($0) }
        }

        if has(["ipo", "listing", "listed", "상장", "lockup", "락업", "offering"]) {
            tags.append("IPO/상장")
            impact = "높음"
        }
        if has(["earnings", "revenue", "profit", "guidance", "실적", "매출", "가이던스"]) {
            tags.append("실적/가이던스")
            impact = "높음"
        }
        if has(["contract", "deal", "order", "nasa", "government", "계약", "수주"]) {
            tags.append("계약/정부")
            impact = "높음"
            period = "중기"
        }
        if has(["regulation", "lawsuit", "antitrust", "probe", "ban", "규제", "소송"]) {
            tags.append("규제/소송")
            sentiment = "부정"
            impact = "높음"
        }
        if has(["ai", "chip", "semiconductor", "space", "starlink", "starship", "launch", "우주", "반도체"]) {
            tags.append("섹터 모멘텀")
            period = "중기"
        }
        if has(["etf", "fund", "institution", "buy", "inflow", "기관", "수급", "자금"]) {
            tags.append("수급/ETF")
        }
        if has(["ceo", "musk", "management", "interview", "경영진"]) {
            tags.append("CEO/경영진")
        }
        if has(["surge", "rally", "growth", "beats", "strong", "upgrade", "흥행", "상승", "호재"]) {
            sentiment = "긍정"
        }
        if has(["fall", "drop", "loss", "miss", "downgrade", "risk", "overhang", "concern", "부담", "악재", "우려", "하락"]) {
            sentiment = sentiment == "긍정" ? "혼조" : "부정"
        }

        if tags.isEmpty {
            tags = ["해외 뉴스", result.themeKey.isEmpty ? "기타" : result.themeKey]
        }

        let summary: String
        if sentiment == "긍정" {
            summary = "투자심리 개선 요인으로 볼 수 있지만 가격 반영률을 같이 확인해야 합니다."
        } else if sentiment == "부정" {
            summary = "단기 변동성 또는 매도 압력으로 이어질 수 있어 추가 뉴스 확인이 필요합니다."
        } else if sentiment == "혼조" {
            summary = "호재와 리스크가 함께 있어 방향성보다 시장 반응이 더 중요합니다."
        } else {
            summary = "단독 매수 근거보다는 거래량과 섹터 흐름을 보조 확인하는 뉴스입니다."
        }

        return OverseasNewsDisplayItem(
            title: title,
            freshness: result.newsFreshnessText,
            summary: summary,
            sentiment: sentiment,
            period: period,
            impact: impact,
            tags: Array(tags.prefix(3)),
            shortImpact: overseasShortImpactText
        )
    }

    private var overseasPositiveDrivers: [String] {
        var items = result.newsV2PositiveLines.filter { !$0.contains("제한") }
        if result.volumeRatio >= 1.5 {
            items.append("거래량 \(String(format: "%.1f", result.volumeRatio))배로 뉴스 반응 확인")
        }
        if result.changePercent > 0 {
            items.append("가격이 \(String(format: "%+.2f", result.changePercent))% 반응하며 투자심리 개선")
        }
        if result.themeKey != "기타" {
            items.append("\(result.themeKey) 섹터 모멘텀 확인")
        }
        if items.isEmpty {
            items = ["뚜렷한 호재는 제한적이나 섹터/거래량 반응 확인 필요"]
        }
        return Array(items.prefix(3))
    }

    private var overseasRiskDrivers: [String] {
        var items = result.newsV2NegativeLines.filter { !$0.contains("제한") }
        if result.isChaseRiskForAi {
            items.append("단기 급등으로 밸류/추격 부담 존재")
        }
        if result.changePercent < 0 {
            items.append("가격이 \(String(format: "%+.2f", result.changePercent))% 약세라 악재 반영 여부 확인")
        }
        if overseasReflectionShortText == "이미 반영" {
            items.append("호재 선반영 가능성으로 추격 리스크")
        }
        if items.isEmpty {
            items = ["해외 뉴스 특성상 장중 변동성 확대 가능성"]
        }
        return Array(items.prefix(3))
    }

    private var overseasWatchReasons: [String] {
        [
            "뉴스 강도 \(overseasNewsStrengthText)와 실제 가격 반응의 괴리를 확인해야 합니다.",
            "\(overseasReflectionShortText) 상태라 추격/눌림 판단이 중요합니다.",
            "\(result.themeKey) 섹터와 동종 해외 종목 움직임이 같이 따라오는지 봅니다."
        ]
    }

    private var overseasThreeLineSummary: [String] {
        [
            "핵심 재료: \(overseasNewsItems.first?.title ?? result.majorNewsText)",
            "주의 포인트: \(overseasRiskDrivers.first ?? "단기 변동성")",
            "현재 판단: \(overseasNewsConclusionText)"
        ]
    }

    private var aiEngineDetailCard: some View {
        CollapsibleDetailSection(
            title: "통합 AI 엔진 상세",
            summary: "뉴스 \(result.analystNewsScore) / 수급 \(result.analystFlowScore) / 기술 \(result.analystTechnicalScore)",
            systemImage: "brain.head.profile",
            tint: .mint,
            isExpanded: $showEngineCard
        ) {
            VStack(alignment: .leading, spacing: 10) {
                Text(result.mobileIntelUpdatedText)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)

                ScoreMeter(label: "뉴스", value: result.analystNewsScore, tint: .mint)
                ScoreMeter(label: "수급", value: result.analystFlowScore, tint: .mint)
                ScoreMeter(label: "기술", value: result.analystTechnicalScore, tint: .mint)
                ScoreMeter(label: "섹터", value: result.analystSectorScore, tint: .mint)

                ForEach(Array(result.mobileIntelSummaryLines.prefix(8).enumerated()), id: \.offset) { _, line in
                    Text("- \(line)")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.primary)
                }
            }
        }
    }

    private var userActionCard: some View {
        CollapsibleDetailSection(
            title: "알림 / 체크 / 사용자 액션",
            summary: "알림 \(activeAlertCount)개 / \(isFavoriteState ? "관심 등록" : "관심 미등록")",
            systemImage: "bell.badge.fill",
            tint: .yellow,
            isExpanded: $showActionCard
        ) {
            VStack(alignment: .leading, spacing: 10) {
                Label(result.buyTargetReached ? "매수 타점 도달" : "매수 타점 대기", systemImage: result.buyTargetReached ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(result.buyTargetReached ? Color.mint : Color.secondary)
                Label(result.stopLossNear ? "손절 라인 근접" : "손절 라인 여유", systemImage: result.stopLossNear ? "exclamationmark.triangle.fill" : "shield")
                    .foregroundStyle(result.stopLossNear ? Color.orange : Color.secondary)
                Label(result.fastMoveAlert ?? "급등/급락 알림 대기", systemImage: result.fastMoveAlert == nil ? "bell" : "bell.fill")
                    .foregroundStyle(result.fastMoveAlert == nil ? Color.secondary : Color.yellow)

                Text("체크: \(result.aiHitRateText)")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)
                Text("체크: \(result.newsLeadingDetectionText)")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)

                Button {
                    isFavoriteState.toggle()
                    toggleFavorite()
                } label: {
                    Label(isFavoriteState ? "관심종목 해제" : "관심종목 등록", systemImage: isFavoriteState ? "star.fill" : "star")
                        .font(.caption.bold())
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 9)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.black)
                .background(isFavoriteState ? Color.yellow : Color.mint, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private var activeAlertCount: Int {
        [result.buyTargetReached, result.stopLossNear, result.fastMoveAlert != nil].filter { $0 }.count
    }

    private func reasonTags(from text: String) -> [String] {
        let separators = CharacterSet(charactersIn: ",|·\n")
        let tags = text
            .components(separatedBy: separators)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        if tags.isEmpty {
            let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return clean.isEmpty ? ["확인 대기"] : [clean]
        }
        return Array(tags.prefix(8))
    }

    private var recommendationDateText: String {
        guard let recommendationDate else {
            return ""
        }
        return " · 추천일 \(recommendationDate)"
    }

    private var analystTint: Color {
        if result.analystEvaluation == "강세" {
            return .red
        }
        if result.analystEvaluation == "약세" {
            return .blue
        }
        return .orange
    }

    private var earlySignalTint: Color {
        if result.earlySignalScore >= 72 {
            return .red
        }
        if result.earlySignalScore >= 50 {
            return .orange
        }
        return .blue
    }

    private var notYetMovedTint: Color {
        if result.notYetMovedProbability >= 70 {
            return .mint
        }
        if result.notYetMovedProbability >= 52 {
            return .orange
        }
        return .secondary
    }

    private var shouldShowPredictionSection: Bool {
        isFavoriteState || result.isAiPick || result.isBuyCandidate
    }

    private var predictionScopeText: String {
        if isFavoriteState {
            return "관심종목 기준 예측"
        }
        if result.isAiPick {
            return "오늘 AI 추천 기준 예측\(recommendationDateText)"
        }
        return "매수 후보 기준 예측"
    }

    private var predictionTint: Color {
        if result.hasCriticalNewsRisk || result.newsActionText.contains("악재") || result.mobileNewsPriceForecast.contains("악재") {
            return .orange
        }
        if result.newsActionText.contains("호재") || result.mobileNewsPriceForecast.contains("호재") || result.mobileNewsPriceForecast.contains("+") {
            return .red
        }
        return result.sinceScanTint
    }

    private var newsImpactIcon: String {
        predictionTint == .orange ? "exclamationmark.triangle.fill" : "newspaper.fill"
    }

    private var newsImpactForecastText: String {
        let forecast = result.mobileNewsPriceForecast.trimmingCharacters(in: .whitespacesAndNewlines)
        if !forecast.isEmpty {
            return "뉴스 영향: \(forecast)"
        }
        if result.hasCriticalNewsRisk {
            return "뉴스 영향: 악재 우세, 단기 하락 압력 우선 확인"
        }
        if result.newsActionText.contains("호재") {
            return "뉴스 영향: 호재 우세, 상승 반응 여부 확인"
        }
        if result.newsActionText.contains("악재") {
            return "뉴스 영향: 악재 우세, 지지선 이탈 여부 확인"
        }
        return "뉴스 영향: 당일 호재/악재 예측 대기"
    }

    private var buyPrice: Double? {
        parsePositionNumber(buyPriceText)
    }

    private var totalAmount: Double? {
        parsePositionNumber(totalAmountText)
    }

    private var manualTargetPrice: Double? {
        parsePositionNumber(targetPriceText)
    }

    private var hasPositionInput: Bool {
        buyPrice != nil || totalAmount != nil
    }

    private var hasCompletePositionInput: Bool {
        buyPrice != nil && totalAmount != nil
    }

    private var positionQuantity: Double? {
        guard let buyPrice, let totalAmount, buyPrice > 0, totalAmount > 0 else {
            return nil
        }
        return totalAmount / buyPrice
    }

    private var positionProfit: Double? {
        guard let current = result.currentPrice, let buyPrice, let totalAmount else {
            return nil
        }
        return totalAmount * ((current / buyPrice) - 1)
    }

    private var positionProfitPercent: Double? {
        guard let buyPrice, let current = result.currentPrice, buyPrice > 0 else {
            return nil
        }
        return ((current / buyPrice) - 1) * 100
    }

    private var takeProfitPrice: Double? {
        guard let buyPrice else {
            return nil
        }
        let firstTargetPercent = max(4.0, min(18.0, result.upsidePercent))
        let firstTarget = buyPrice * (1 + firstTargetPercent / 100)
        guard let current = result.currentPrice, current >= firstTarget else {
            return firstTarget
        }
        let nextTargetPercent = max(3.0, min(8.0, result.upsidePercent * 0.55))
        return current * (1 + nextTargetPercent / 100)
    }

    private var stopLossPrice: Double? {
        guard let buyPrice else {
            return nil
        }
        let stopPercent = max(3.0, min(12.0, result.downsidePercent))
        let initialStop = buyPrice * (1 - stopPercent / 100)
        guard let current = result.currentPrice, current > buyPrice else {
            return initialStop
        }
        let trailingPercent = max(4.0, min(10.0, result.downsidePercent * 0.85))
        let trailingStop = current * (1 - trailingPercent / 100)
        return max(initialStop, trailingStop)
    }

    private var positionTint: Color {
        positionEvaluation?.tint ?? (positionProfit ?? 0 >= 0 ? .red : .blue)
    }

    private var positionSummaryText: String {
        if let positionEvaluation {
            return positionEvaluation.summary
        }
        guard let profit = positionProfit, let percent = positionProfitPercent else {
            return "계산하려면 매수가와 총금액이 모두 필요합니다."
        }
        let direction = profit >= 0 ? "평가수익" : "평가손실"
        return "\(direction) \(formatPositionMoney(abs(profit))) (\(String(format: "%.2f", abs(percent)))%)"
    }

    private var positionDetailText: String {
        if let positionEvaluation {
            return positionEvaluation.detail
        }
        guard let quantity = positionQuantity, let current = result.currentPrice, let totalAmount else {
            return "현재가 \(result.formattedPrice) 기준으로 계산 대기 중입니다."
        }
        let currentValue = quantity * current
        return "투입금액 \(formatPositionMoney(totalAmount)) · 수량 약 \(formatQuantity(quantity))주 · 현재 평가금액 \(formatPositionMoney(currentValue))"
    }

    private var positionDividendText: String {
        guard result.marketText == "캐나다", let quantity = positionQuantity else {
            return ""
        }

        let annualDividend = result.dividendAnnualAmount * quantity
        let recentDividend = result.dividendAmount * quantity
        var parts: [String] = []

        if annualDividend > 0 {
            parts.append("예상 연 배당 \(formatPositionMoney(annualDividend))")
        }
        if recentDividend > 0 {
            parts.append("회당 예상 \(formatPositionMoney(recentDividend))")
        }
        if result.dividendYieldPercent > 0 {
            parts.append("배당률 \(String(format: "%.2f", result.dividendYieldPercent))%")
        }

        let nextDate = result.nextDividendEstimate.trimmingCharacters(in: .whitespacesAndNewlines)
        if !nextDate.isEmpty {
            parts.append("다음 예상 \(nextDate)")
        }

        if parts.isEmpty {
            return "배당 예상: 배당 정보 없음"
        }
        return "배당 예상: \(parts.joined(separator: " · "))"
    }

    private var positionPlanText: String {
        if let positionEvaluation {
            return positionEvaluation.plan
        }
        guard let takeProfitPrice, let stopLossPrice else {
            return "익절/손절 기준은 매수가 입력 후 표시됩니다."
        }
        var action = "보유하면서 현재가와 거래량을 확인하세요."
        if let current = result.currentPrice, let buyPrice {
            let firstTarget = buyPrice * (1 + max(4.0, min(18.0, result.upsidePercent)) / 100)
            if current >= firstTarget {
                action = "1차 익절권은 이미 통과했습니다. 다음 익절가와 트레일링 손절가 기준으로 관리하세요."
            } else if current <= stopLossPrice {
                action = "손절권 근접: 리스크를 먼저 줄이는 구간입니다."
            }
        }
        return "익절가 \(formatPositionPrice(takeProfitPrice)) · 손절가 \(formatPositionPrice(stopLossPrice)) · \(action)"
    }

    private var positionJudgementText: String {
        if let positionEvaluation {
            return positionEvaluation.judgement
        }
        guard let percent = positionProfitPercent, let current = result.currentPrice, let buyPrice else {
            return "판단: 매수가와 총금액 입력 후 평가합니다."
        }
        if percent >= 20 {
            return "판단: 수익이 크게 난 상태라 신규 추격보다 일부 익절 후 남은 물량을 트레일링으로 관리하는 쪽이 낫습니다."
        }
        if percent >= 8 {
            return "판단: 수익권입니다. 전량 욕심보다 분할 익절과 손절가 상향이 유리합니다."
        }
        if percent >= 0 {
            return "판단: 아직 수익권 초입입니다. 현재가가 매수가를 지키는지 보면서 보유 가능합니다."
        }
        if current <= buyPrice * 0.95 {
            return "판단: 손실이 커지는 구간입니다. 반등 기다리기보다 손절 기준을 먼저 지켜야 합니다."
        }
        return "판단: 약손실 구간입니다. 거래량 회복 전 추가매수는 조심하는 편이 좋습니다."
    }

    private var positionEvaluation: PositionEvaluation? {
        guard let buyPrice, let totalAmount else {
            return nil
        }
        return PositionEvaluation(result: result, buyPrice: buyPrice, totalAmount: totalAmount)
    }

    private func savePosition() {
        PositionStore.save(ticker: result.ticker, priceText: buyPriceText, amountText: totalAmountText, targetText: targetPriceText)
    }

    private func dismissKeyboard() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }

    private func parsePositionNumber(_ text: String) -> Double? {
        let cleaned = text
            .replacingOccurrences(of: ",", with: "")
            .replacingOccurrences(of: "원", with: "")
            .replacingOccurrences(of: "$", with: "")
            .replacingOccurrences(of: "CAD", with: "", options: .caseInsensitive)
            .replacingOccurrences(of: "USD", with: "", options: .caseInsensitive)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let value = Double(cleaned), value > 0 else {
            return nil
        }
        return value
    }

    private func formatPositionPrice(_ value: Double) -> String {
        if result.marketText == "국장" {
            return value.formatted(.number.precision(.fractionLength(0))) + "원"
        }
        let currency = result.marketText == "캐나다" ? " CAD" : " USD"
        return value.formatted(.number.precision(.fractionLength(2))) + currency
    }

    private func formatPositionMoney(_ value: Double) -> String {
        formatPositionPrice(value)
    }

    private func formatQuantity(_ value: Double) -> String {
        if value >= 100 {
            return value.formatted(.number.precision(.fractionLength(1)))
        }
        return value.formatted(.number.precision(.fractionLength(3)))
    }

    @MainActor
    private func refreshDetailQuote() async {
        guard !isRefreshingQuote else {
            return
        }
        let minimumRefreshInterval: TimeInterval = networkUsageMonitor.shouldReduceData ? 120 : 8
        if let lastDetailQuoteRefresh, Date().timeIntervalSince(lastDetailQuoteRefresh) < minimumRefreshInterval {
            return
        }
        isRefreshingQuote = true
        defer {
            isRefreshingQuote = false
        }
        let quotes = await LiveQuoteService.fetchQuotes(for: [result.ticker])
        if let quote = quotes.first(where: { $0.ticker == result.ticker.uppercased() }) {
            result.apply(liveQuote: quote)
        }
        if !networkUsageMonitor.shouldReduceData, let flow = await InvestorFlowService.fetchFlow(for: result.ticker) {
            result.apply(investorFlow: flow)
        }
        lastDetailQuoteRefresh = Date()
    }

    @MainActor
    private func fetchFavoriteNews() async {
        guard !isFetchingFavoriteNews else {
            return
        }
        isFetchingFavoriteNews = true
        favoriteNewsMessage = "최신 뉴스 확인 중"
        let items = await FavoriteNewsService.fetchNews(for: result)
        favoriteNewsItems = items
        favoriteNewsMessage = items.isEmpty ? "가져온 뉴스가 없습니다." : "\(items.count)개 뉴스 갱신"
        isFetchingFavoriteNews = false
    }
}

private struct DetailPriceBox: View {
    let title: String
    let price: String
    let percent: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.weight(.bold))
                .foregroundStyle(.secondary)
            Text(price)
                .font(.title3.bold())
                .minimumScaleFactor(0.75)
                .lineLimit(1)
            Text(percent)
                .font(.caption.bold())
                .foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(tint.opacity(0.18), lineWidth: 1))
    }
}

private struct DetailMiniMetric: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2.bold())
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.monospacedDigit().weight(.heavy))
                .foregroundStyle(tint)
                .lineLimit(2)
                .minimumScaleFactor(0.8)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(tint.opacity(0.18), lineWidth: 1))
    }
}

private struct EarningsPreview {
    let date: Date
    let daysUntil: Int
    let sessionText: String
    let sourceText: String

    var isNear: Bool { daysUntil <= 10 }
    var tint: Color {
        if daysUntil <= 3 { return .orange }
        if daysUntil <= 7 { return .yellow }
        return .mint
    }
    var displayDate: String {
        AppDateTime.localString(from: date, format: "M월 d일")
    }
    var dDayText: String {
        daysUntil == 0 ? "D-Day" : "D-\(daysUntil)"
    }
    var notice: String {
        if sourceText.contains("예상") || sourceText.contains("확인") {
            return "현재 서버에 공식 실적 일정 원천이 없어 과거 분기 발표 패턴과 종목별 분산 일정으로 계산한 후보입니다. 이미 발표한 이번 달 종목도 누락되지 않도록 표시하며, 공식 일정 API가 들어오면 자동 대체하도록 분리했습니다."
        }
        return "공식 실적 일정 기준입니다. 발표 전에는 뉴스/수급/옵션성 변동이 커질 수 있습니다."
    }

    static func make(for result: ScannerResult) -> EarningsPreview {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone.current
        let now = Date()
        let month = calendar.component(.month, from: now)
        let year = calendar.component(.year, from: now)
        let earningsMonths = [1, 4, 7, 10]
        let targetMonth = earningsMonths.first { $0 >= month } ?? 1
        let targetYear = targetMonth >= month ? year : year + 1
        let baseDay = estimatedAnnouncementDay(for: result, month: targetMonth, calendar: calendar, year: targetYear)
        let components = DateComponents(year: targetYear, month: targetMonth, day: baseDay, hour: result.marketText == "미장" ? 13 : 15)
        var target = calendar.date(from: components) ?? now
        let keepsCurrentEarningsMonth = earningsMonths.contains(month) && targetMonth == month && targetYear == year
        if target < calendar.startOfDay(for: now), !keepsCurrentEarningsMonth {
            let nextIndex = ((earningsMonths.firstIndex(of: targetMonth) ?? 0) + 1) % earningsMonths.count
            let nextMonth = earningsMonths[nextIndex]
            let nextYear = nextMonth > targetMonth ? targetYear : targetYear + 1
            let nextDay = estimatedAnnouncementDay(for: result, month: nextMonth, calendar: calendar, year: nextYear)
            target = calendar.date(from: DateComponents(year: nextYear, month: nextMonth, day: nextDay, hour: result.marketText == "미장" ? 13 : 15)) ?? now
        }
        let signedDays = calendar.dateComponents([.day], from: calendar.startOfDay(for: now), to: calendar.startOfDay(for: target)).day ?? 0
        let days = max(0, signedDays)
        let session: String
        if result.marketText == "미장" {
            session = "장 마감 후(AMC)"
        } else if result.marketText == "국장" {
            session = "장 종료 후"
        } else {
            session = "장중/장후 확인"
        }
        let source = signedDays < 0 && keepsCurrentEarningsMonth ? "이번 달 발표 확인 필요" : "예상 일정"
        return EarningsPreview(date: target, daysUntil: days, sessionText: session, sourceText: source)
    }

    private static func estimatedAnnouncementDay(for result: ScannerResult, month: Int, calendar: Calendar, year: Int) -> Int {
        let maxDay = calendar.range(of: .day, in: .month, for: calendar.date(from: DateComponents(year: year, month: month, day: 1)) ?? Date())?.count ?? 30
        let window: ClosedRange<Int> = result.marketText == "국장" ? 10...min(30, maxDay) : 15...min(30, maxDay)
        let seed = "\(result.tickerCleanText)\(result.name)\(month)".unicodeScalars.reduce(0) { partial, scalar in
            partial + Int(scalar.value)
        }
        let span = max(1, window.upperBound - window.lowerBound + 1)
        return min(maxDay, window.lowerBound + (abs(seed) % span))
    }
}

private struct EarningsPrediction {
    let upsideProbability: Int
    let downsideProbability: Int
    let directionText: String
    let confidenceText: String
    let reasons: [String]
    let risks: [String]
    let tint: Color

    static func make(for result: ScannerResult, preview: EarningsPreview) -> EarningsPrediction {
        var score = 50
        score += min(14, max(-14, result.analystNewsScore - 55) / 2)
        score += min(12, max(-12, result.analystFlowScore - 50) / 3)
        score += min(10, max(-10, result.analystSectorScore - 50) / 4)
        if result.volumeRatio >= 2.0 { score += 7 }
        if result.volumeRatio < 0.7 { score -= 5 }
        if result.changePercent > 8 { score -= 8 }
        if result.changePercent < -5 { score -= 4 }
        if result.hasCriticalNewsRisk { score -= 14 }
        if result.isChaseRiskForAi { score -= 8 }
        if preview.daysUntil <= 3 { score += result.analystNewsScore >= 60 ? 3 : -3 }
        let upside = min(86, max(18, score))
        let downside = 100 - upside
        let confidence = min(92, max(45, 52 + abs(upside - 50) + min(12, Int(max(result.volumeRatio, 1.0) * 2))))
        let tint: Color = upside >= 62 ? .red : (upside <= 42 ? .blue : .orange)
        let direction = upside >= 62 ? "▲ 상승 예상" : (upside <= 42 ? "▼ 하락 주의" : "중립/변동성")

        var reasons: [String] = []
        reasons.append("뉴스 점수 \(result.analystNewsScore) / 수급 점수 \(result.analystFlowScore)")
        if result.volumeRatio >= 1.2 { reasons.append("거래량 \(String(format: "%.1f", result.volumeRatio))배로 발표 전 관심 증가") }
        if result.analystSectorScore >= 60 { reasons.append("\(result.sectorCategoryName) 섹터 흐름 우호적") }
        if result.institutionNet > 0 || result.foreignNet > 0 { reasons.append("기관/외국인 수급 유입 감지") }
        if result.mobileNewsImpactScore > 20 { reasons.append("최근 뉴스 감성 긍정") }
        if reasons.count < 3 { reasons.append("과거 발표 전 가격 반응은 현재 수급/뉴스 확인 우선") }

        var risks: [String] = []
        if result.hasCriticalNewsRisk { risks.append("중대 악재성 뉴스가 예측 신뢰도 하락 요인") }
        if result.isChaseRiskForAi || result.changePercent > 6 { risks.append("실적 전 선반영/추격 리스크") }
        if result.volumeRatio < 0.8 { risks.append("거래량 부족으로 발표 전 확신 낮음") }
        if result.analystFlowScore < 45 { risks.append("수급 점수 약함") }
        if risks.isEmpty { risks.append("실적 발표 직후 갭 변동성 확대 가능") }

        return EarningsPrediction(
            upsideProbability: upside,
            downsideProbability: downside,
            directionText: direction,
            confidenceText: "\(confidence)%",
            reasons: Array(reasons.prefix(5)),
            risks: Array(risks.prefix(4)),
            tint: tint
        )
    }
}

private struct PositionInputField: View {
    let title: String
    @Binding var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            TextField(title, text: $text)
                .keyboardType(.decimalPad)
                .textInputAutocapitalization(.never)
                .disableAutocorrection(true)
                .font(.subheadline.weight(.semibold))
                .padding(.horizontal, 10)
                .padding(.vertical, 9)
                .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct InvestmentSimulatorPanel: View {
    let result: ScannerResult
    let buyPrice: Double?
    let totalAmount: Double?
    let currentPrice: Double?
    let manualTargetPrice: Double?
    let formatMoney: (Double) -> String
    let formatPrice: (Double) -> String
    let formatQuantity: (Double) -> String

    private var quantity: Double? {
        guard let buyPrice, let totalAmount, buyPrice > 0, totalAmount > 0 else {
            return nil
        }
        return totalAmount / buyPrice
    }

    private var aiTargets: (conservative: Double, base: Double, aggressive: Double)? {
        guard let basePrice = currentPrice ?? buyPrice, basePrice > 0 else {
            return nil
        }
        let signalBoost = max(0.0, Double(result.todayScore - 70)) * 0.08
        let baseUpside = max(6.0, min(32.0, result.upsidePercent + signalBoost))
        let conservativePct = max(4.0, min(18.0, baseUpside * 0.65))
        let basePct = max(7.0, min(35.0, baseUpside))
        let aggressivePct = max(10.0, min(55.0, basePct * 1.45 + (result.eventScore >= 82 ? 4.0 : 0.0)))
        return (
            conservative: basePrice * (1 + conservativePct / 100),
            base: basePrice * (1 + basePct / 100),
            aggressive: basePrice * (1 + aggressivePct / 100)
        )
    }

    private var selectedTargetPrice: Double? {
        manualTargetPrice ?? aiTargets?.base
    }

    private var targetSourceText: String {
        manualTargetPrice == nil ? "AI 기본 목표가 기준" : "입력 목표가 기준"
    }

    private var currentValue: Double? {
        guard let quantity, let currentPrice else {
            return nil
        }
        return quantity * currentPrice
    }

    private var currentProfit: Double? {
        guard let currentValue, let totalAmount else {
            return nil
        }
        return currentValue - totalAmount
    }

    private var targetValue: Double? {
        guard let quantity, let selectedTargetPrice else {
            return nil
        }
        return quantity * selectedTargetPrice
    }

    private var targetProfit: Double? {
        guard let targetValue, let totalAmount else {
            return nil
        }
        return targetValue - totalAmount
    }

    private var targetProfitPercent: Double? {
        guard let targetProfit, let totalAmount, totalAmount > 0 else {
            return nil
        }
        return targetProfit / totalAmount * 100
    }

    private var remainingUpsidePercent: Double? {
        guard let selectedTargetPrice, let currentPrice, currentPrice > 0 else {
            return nil
        }
        return (selectedTargetPrice / currentPrice - 1) * 100
    }

    private var targetProgressText: String {
        guard let buyPrice, let currentPrice, let selectedTargetPrice else {
            return "목표 알림: 목표가 계산 대기"
        }
        let progress: Double
        if selectedTargetPrice > buyPrice {
            progress = (currentPrice - buyPrice) / (selectedTargetPrice - buyPrice)
        } else {
            progress = currentPrice / selectedTargetPrice
        }
        if progress >= 1.03 {
            return "목표가 돌파 · 다음 목표 재설정 필요"
        }
        if progress >= 1.0 {
            return "목표가 도달 · 익절 판단 구간"
        }
        if progress >= 0.9 {
            return "목표가 90% 도달 · 분할 익절 준비"
        }
        if progress >= 0.8 {
            return "목표가 80% 도달 · 알림 감시 구간"
        }
        return "목표가까지 \(String(format: "%.1f", max(0, (1 - progress) * 100)))% 남음"
    }

    private var probabilityScore: Int {
        var score = Int(Double(result.todayScore) * 0.42 + Double(result.quantSignalScore) * 0.30 + Double(result.eventScore) * 0.18)
        if result.isChaseRiskForAi {
            score -= 12
        }
        if result.downsidePercent >= 8 {
            score -= 5
        }
        return min(96, max(18, score))
    }

    private var expectedPeriodText: String {
        if probabilityScore >= 78 && result.upsidePercent >= 12 {
            return "1~3개월"
        }
        if probabilityScore >= 62 {
            return "3~6개월"
        }
        return "6개월 이상 또는 재평가"
    }

    private var riskText: String {
        if result.isChaseRiskForAi || result.downsidePercent >= 9 {
            return "높음"
        }
        if result.downsidePercent >= 6 {
            return "보통"
        }
        return "낮음"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("투자 시뮬레이터", systemImage: "target")
                .font(.subheadline.bold())
                .foregroundStyle(.mint)

            if let totalAmount, let quantity, let currentValue, let currentProfit, let targetValue, let targetProfit, let targetProfitPercent, let selectedTargetPrice {
                LazyVGrid(columns: [
                    GridItem(.flexible(), spacing: 8),
                    GridItem(.flexible(), spacing: 8)
                ], alignment: .leading, spacing: 8) {
                    SimulatorMetricBox(title: "현재 투자금", value: formatMoney(totalAmount), tint: .secondary)
                    SimulatorMetricBox(title: "보유 수량", value: "\(formatQuantity(quantity))주", tint: .secondary)
                    SimulatorMetricBox(title: "현재 평가금액", value: formatMoney(currentValue), tint: currentProfit >= 0 ? .red : .blue)
                    SimulatorMetricBox(title: "현재 손익", value: signedMoney(currentProfit), tint: currentProfit >= 0 ? .red : .blue)
                    SimulatorMetricBox(title: "목표 평가금액", value: formatMoney(targetValue), tint: .mint)
                    SimulatorMetricBox(title: "예상 수익금", value: signedMoney(targetProfit), tint: targetProfit >= 0 ? .red : .blue)
                }

                Text("\(targetSourceText) \(formatPrice(selectedTargetPrice)) · 예상 수익률 \(signedPercent(targetProfitPercent))")
                    .font(.subheadline.monospacedDigit().weight(.heavy))
                    .foregroundStyle(targetProfit >= 0 ? .red : .blue)

                Text(targetProgressText)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.orange)
                    .padding(9)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
            } else {
                Text("매수가와 총금액을 입력하면 목표가 도달 시 예상 수익을 바로 계산합니다.")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }

            if let targets = aiTargets {
                VStack(alignment: .leading, spacing: 7) {
                    Text("AI 목표가")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                    HStack(spacing: 8) {
                        SimulatorMetricBox(title: "보수적", value: formatPrice(targets.conservative), tint: .secondary)
                        SimulatorMetricBox(title: "기본", value: formatPrice(targets.base), tint: .mint)
                        SimulatorMetricBox(title: "공격적", value: formatPrice(targets.aggressive), tint: .orange)
                    }
                }
            }

            VStack(alignment: .leading, spacing: 5) {
                Text("AI 수익 예측")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                Text("현재가 \(result.formattedPrice) · 목표까지 \(remainingUpsideText) · 도달 가능성 \(probabilityScore)점")
                Text("예상 기간 \(expectedPeriodText) · 리스크 \(riskText)")
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(Color.mint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.mint.opacity(0.16), lineWidth: 1))
    }

    private var remainingUpsideText: String {
        guard let remainingUpsidePercent else {
            return "계산 대기"
        }
        return signedPercent(remainingUpsidePercent)
    }

    private func signedMoney(_ value: Double) -> String {
        let sign = value >= 0 ? "+" : "-"
        return "\(sign)\(formatMoney(abs(value)))"
    }

    private func signedPercent(_ value: Double) -> String {
        let sign = value >= 0 ? "+" : "-"
        return "\(sign)\(String(format: "%.2f", abs(value)))%"
    }
}

private struct SimulatorMetricBox: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2.bold())
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.monospacedDigit().weight(.heavy))
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.72)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(9)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct DetailSection<Content: View>: View {
    let title: String
    let systemImage: String
    let tint: Color
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: systemImage)
                .font(.headline)
                .foregroundStyle(tint)
            content
                .font(.subheadline)
                .foregroundStyle(.primary)
                .lineSpacing(3)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct CollapsibleDetailSection<Content: View>: View {
    let title: String
    let summary: String
    let systemImage: String
    let tint: Color
    @Binding var isExpanded: Bool
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: isExpanded ? 10 : 6) {
            Button {
                withAnimation(.spring(response: 0.28, dampingFraction: 0.88)) {
                    isExpanded.toggle()
                }
            } label: {
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .top, spacing: 8) {
                        Label(title, systemImage: systemImage)
                            .font(.headline)
                            .foregroundStyle(tint)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                            .layoutPriority(1)

                        Spacer(minLength: 4)

                        Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                            .font(.caption.bold())
                            .foregroundStyle(tint)
                            .padding(.top, 3)
                    }

                    Text(summary)
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if isExpanded {
                content
                    .font(.subheadline)
                    .foregroundStyle(.primary)
                    .lineSpacing(3)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct ReasonTagBlock: View {
    let title: String
    let text: String
    let tint: Color

    private var tags: [String] {
        let separators = CharacterSet(charactersIn: ",|·\n")
        let parts = text
            .components(separatedBy: separators)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        if parts.isEmpty {
            let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return clean.isEmpty ? ["확인 대기"] : [clean]
        }
        return Array(parts.prefix(8))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 6)], alignment: .leading, spacing: 6) {
                ForEach(Array(tags.enumerated()), id: \.offset) { _, tag in
                    Text(tag)
                        .font(.caption.weight(.bold))
                        .lineLimit(2)
                        .minimumScaleFactor(0.76)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 6)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(tint.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(tint.opacity(0.16), lineWidth: 1))
                }
            }
        }
    }
}

private struct OverseasNewsDisplayItem {
    let title: String
    let freshness: String
    let summary: String
    let sentiment: String
    let period: String
    let impact: String
    let tags: [String]
    let shortImpact: String

    var tint: Color {
        if sentiment.contains("긍정") {
            return .red
        }
        if sentiment.contains("부정") {
            return .orange
        }
        if sentiment.contains("혼조") {
            return .yellow
        }
        return .secondary
    }
}

private struct OverseasNewsSummaryGrid: View {
    let mood: String
    let strength: String
    let shortImpact: String
    let reflection: String
    let tint: Color

    var body: some View {
        LazyVGrid(columns: [
            GridItem(.flexible(), spacing: 8),
            GridItem(.flexible(), spacing: 8)
        ], alignment: .leading, spacing: 8) {
            OverseasNewsMetricBox(title: "뉴스 분위기", value: mood, tint: tint)
            OverseasNewsMetricBox(title: "뉴스 강도", value: strength, tint: tint)
            OverseasNewsMetricBox(title: "단기 영향", value: shortImpact, tint: tint)
            OverseasNewsMetricBox(title: "반영률", value: reflection, tint: tint)
        }
    }
}

private struct OverseasNewsMetricBox: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2.bold())
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.monospacedDigit().weight(.heavy))
                .foregroundStyle(tint)
                .lineLimit(2)
                .minimumScaleFactor(0.76)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(9)
        .background(tint.opacity(0.09), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(tint.opacity(0.16), lineWidth: 1))
    }
}

private struct OverseasNewsItemRow: View {
    let index: Int
    let item: OverseasNewsDisplayItem
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
                Text(labelText)
                    .font(.caption2.bold())
                    .foregroundStyle(item.tint)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(item.tint.opacity(0.12), in: Capsule())
                Text(NewsDigest.oneLine(item.title, item.summary, fallback: "뉴스 흐름 확인"))
                    .font(.caption.weight(.heavy))
                    .lineLimit(1)
                    .layoutPriority(1)
                Spacer(minLength: 6)
                Text(impactStars)
                    .font(.caption2.monospaced().bold())
                    .foregroundStyle(.yellow)
                    .lineLimit(1)
            }

            HStack(spacing: 6) {
                Text(item.freshness)
                Text(item.shortImpact)
                Text(item.period)
            }
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .lineLimit(1)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private var labelText: String {
        if item.sentiment.contains("긍정") {
            return "호재"
        }
        if item.sentiment.contains("부정") {
            return "악재"
        }
        return "중립"
    }

    private var impactStars: String {
        let level = item.impact == "높음" ? 5 : (item.impact == "중간" ? 3 : 2)
        return String(repeating: "★", count: level) + String(repeating: "☆", count: 5 - level)
    }
}

private struct CanadaNewsItemRow: View {
    let item: CanadaNewsItem

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 7) {
                Text(item.sentiment.isEmpty ? "중립" : item.sentiment)
                    .font(.caption2.bold())
                    .foregroundStyle(tint)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(tint.opacity(0.12), in: Capsule())
                if item.important {
                    Label("중요", systemImage: "exclamationmark.circle.fill")
                        .font(.caption2.bold())
                        .foregroundStyle(.orange)
                        .labelStyle(.titleAndIcon)
                }
                Spacer(minLength: 6)
                Text(scoreText)
                    .font(.caption2.monospacedDigit().bold())
                    .foregroundStyle(tint)
            }

            Text(item.title)
                .font(.caption.weight(.heavy))
                .foregroundStyle(.primary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 6) {
                Text(item.source)
                Text(item.publishedAtLocal.isEmpty ? "게시 시간 확인 전" : item.publishedAtLocal)
            }
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .lineLimit(2)
            .minimumScaleFactor(0.78)

            HStack(spacing: 8) {
                Text(item.collectedAtLocal.isEmpty ? "수집 시간 확인 전" : "수집 \(item.collectedAtLocal)")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                if let url = URL(string: item.url), !item.url.isEmpty {
                    Link(destination: url) {
                        Label("원문", systemImage: "link")
                            .font(.caption2.bold())
                    }
                    .foregroundStyle(.blue)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private var tint: Color {
        if item.sentiment.contains("호재") {
            return .red
        }
        if item.sentiment.contains("악재") {
            return .orange
        }
        return .secondary
    }

    private var scoreText: String {
        String(format: "%+d", item.impactScore)
    }
}

private struct NewsMiniTag: View {
    let text: String
    let tint: Color

    var body: some View {
        Text(text)
            .font(.caption2.weight(.heavy))
            .lineLimit(2)
            .minimumScaleFactor(0.72)
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(tint.opacity(0.10), in: Capsule())
            .foregroundStyle(tint)
    }
}

private struct AnalystBulletBlock: View {
    let title: String
    let points: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            ForEach(Array(points.prefix(3).enumerated()), id: \.offset) { _, point in
                Text("- \(point)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
            }
        }
    }
}

private struct AnalystNumberedBlock: View {
    let title: String
    let points: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            ForEach(Array(points.prefix(3).enumerated()), id: \.offset) { index, point in
                Text("\(index + 1). \(point)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
            }
        }
    }
}

private struct EarlySignalMetricBox: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption2.bold())
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.monospacedDigit().weight(.heavy))
                .foregroundStyle(tint)
                .lineLimit(2)
                .minimumScaleFactor(0.75)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(9)
        .background(tint.opacity(0.09), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(tint.opacity(0.18), lineWidth: 1))
    }
}

private struct MiniMetricPill: View {
    let title: String
    let value: String

    var body: some View {
        VStack(spacing: 2) {
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            Text(value)
                .font(.caption.monospacedDigit().weight(.heavy))
                .foregroundStyle(.primary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .padding(.horizontal, 4)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 7))
    }
}

private struct ScoreMeter: View {
    let label: String
    let value: Int
    let tint: Color

    var body: some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.caption.weight(.bold))
                .foregroundStyle(.secondary)
                .frame(width: 48, alignment: .leading)

            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(AppColors.panelSoft)
                    Capsule()
                        .fill(tint.opacity(0.72))
                        .frame(width: proxy.size.width * CGFloat(max(0, min(100, value))) / 100)
                }
            }
            .frame(height: 8)

            Text("\(max(0, min(100, value)))")
                .font(.caption.monospacedDigit().weight(.bold))
                .foregroundStyle(.primary)
                .frame(width: 30, alignment: .trailing)
        }
        .frame(height: 18)
    }
}

private struct FavoriteNewsRow: View {
    let item: StockNewsItem

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 7) {
                Text(item.tone)
                    .font(.caption2.bold())
                    .foregroundStyle(tint)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(tint.opacity(0.12), in: Capsule())
                Text(item.source)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                if !item.reflectionText.isEmpty {
                    Text("(\(item.reflectionText))")
                        .font(.caption2.bold())
                        .foregroundStyle(.orange)
                        .lineLimit(1)
                }
                Spacer()
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Text("뉴스일 \(item.publishedAt)")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .lineLimit(1)

            Text(item.title)
                .font(.caption.weight(.semibold))
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            if item.reason != "키워드 없음" {
                Text("분류 근거: \(item.reason)")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(AppColors.background.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }

    private var tint: Color {
        switch item.tone {
        case "호재":
            return .red
        case "악재":
            return .blue
        default:
            return .gray
        }
    }
}

private enum MainAppTab: String, CaseIterable, Identifiable {
    case home
    case scanner
    case ai
    case watchlist
    case earnings
    case market
    case settings
    case admin

    var id: String { rawValue }

    static let userTabs: [MainAppTab] = [.home, .scanner, .ai, .watchlist, .earnings, .market, .settings]

    var title: String {
        switch self {
        case .home: return "홈"
        case .scanner: return "스캐너"
        case .ai: return "AI"
        case .watchlist: return "관심"
        case .earnings: return "실적"
        case .market: return "시장"
        case .settings: return "설정"
        case .admin: return "관리자"
        }
    }

    var systemImage: String {
        switch self {
        case .home: return "house.fill"
        case .scanner: return "list.bullet.rectangle.fill"
        case .ai: return "brain.head.profile"
        case .watchlist: return "star.fill"
        case .earnings: return "calendar.badge.clock"
        case .market: return "chart.line.uptrend.xyaxis"
        case .settings: return "gearshape.fill"
        case .admin: return "wrench.and.screwdriver.fill"
        }
    }
}

private struct MainTabBar: View {
    @Binding var selectedTab: MainAppTab
    let tabs: [MainAppTab]

    var body: some View {
        HStack(spacing: 6) {
            ForEach(tabs) { tab in
                Button {
                    withAnimation(.snappy(duration: 0.18)) {
                        selectedTab = tab
                    }
                } label: {
                    VStack(spacing: 3) {
                        Image(systemName: tab.systemImage)
                            .font(.caption.bold())
                        Text(tab.title)
                            .font(.caption2.bold())
                            .lineLimit(1)
                            .minimumScaleFactor(0.78)
                    }
                    .foregroundStyle(selectedTab == tab ? .black : .primary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 7)
                    .background(selectedTab == tab ? Color.mint : AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: .infinity)
    }
}

private struct HomeDashboardSection: View {
    let results: [ScannerResult]
    let watchlist: [ScannerResult]
    let sectorRanks: [SectorInflowRank]
    let majorNews: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let positionSummary: PortfolioRiskSummary
    let sectorSize: SectorInflowCardSize
    let setSectorSize: (SectorInflowCardSize) -> Void
    let toggleFavorite: (ScannerResult) -> Void

    private var topScore: Int {
        watchlist.first?.todayScore ?? results.map(\.todayScore).max() ?? 0
    }

    private var marketState: String {
        if topScore >= 82 { return "강세" }
        if topScore >= 68 { return "중립" }
        return "약세"
    }

    private var confidence: Int {
        guard !watchlist.isEmpty else { return 0 }
        let avg = watchlist.prefix(5).map(\.earlySignalProbability).reduce(0, +) / max(1, min(5, watchlist.count))
        return max(0, min(100, avg))
    }

    private var homeEarningsCandidates: [ScannerResult] {
        let supported = results.filter { $0.marketText == "미장" || $0.marketText == "국장" }
        let sorted = supported.sorted { lhs, rhs in
            let lhsPreview = EarningsPreview.make(for: lhs)
            let rhsPreview = EarningsPreview.make(for: rhs)
            if lhsPreview.daysUntil == rhsPreview.daysUntil {
                return lhs.todayScore > rhs.todayScore
            }
            return lhsPreview.daysUntil < rhsPreview.daysUntil
        }
        let near = sorted.filter { EarningsPreview.make(for: $0).daysUntil <= 21 }
        return Array(near.isEmpty ? sorted.prefix(6) : near.prefix(6))
    }

    private var canadaResults: [ScannerResult] {
        results.filter { $0.marketText == "캐나다" }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            AppUpdateNoticeCard()

            TodayScoreHomeCard(
                score: topScore,
                state: marketState,
                confidence: confidence,
                briefing: watchlist.first?.whyTodayText ?? "오늘은 무리해서 추천할 확정 후보가 적습니다.",
                totalCount: results.count,
                liveCount: results.filter { $0.liveUpdatedAt != nil }.count
            )

            HomeFeaturedPickCard(
                result: watchlist.first,
                favoriteTickers: favoriteTickers,
                aiPickDates: aiPickDates,
                toggleFavorite: toggleFavorite
            )

                            HomeTopPicksCard(
                picks: Array(watchlist.dropFirst().prefix(5)),
                                favoriteTickers: favoriteTickers,
                                aiPickDates: aiPickDates,
                                toggleFavorite: toggleFavorite
                            )

            HomeEarningsBriefCard(
                candidates: homeEarningsCandidates,
                favoriteTickers: favoriteTickers,
                aiPickDates: aiPickDates,
                toggleFavorite: toggleFavorite
            )

            HomeMarketSignalCard(
                leading: watchlist.first,
                sectorRanks: sectorRanks,
                positionSummary: positionSummary
            )

            CanadaHomeOverviewCard(
                results: canadaResults,
                favoriteTickers: favoriteTickers,
                aiPickDates: aiPickDates,
                toggleFavorite: toggleFavorite
            )

            if let firstNews = majorNews.first {
                HomeNewsBriefingCard(news: [firstNews])
            }
        }
    }
}

private struct AppUpdateEntry: Identifiable {
    let id = UUID()
    let version: String
    let updatedAt: String
    let features: [String]
    let fixes: [String]
    let dataChanges: [String]
    let important: [String]
}

private struct AppUpdateNoticeCard: View {
    @State private var showHistory = false

    private let entries: [AppUpdateEntry] = [
        AppUpdateEntry(
            version: "v1.0.24",
            updatedAt: "2026-08-18 20:50 PDT",
            features: [
                "메인폰과 관리자폰 신고 목록을 중앙 API 기준으로 동기화",
                "모바일 데이터 요청 단계별 진단 로그 추가"
            ],
            fixes: [
                "신고 건수와 상태가 기기마다 다르게 보일 수 있는 문제 수정",
                "서버 응답 실패, 인증 오류, 제한 응답을 구분해 표시하도록 개선",
                "제한된 결과나 비정상적으로 적은 데이터가 기존 정상 캐시를 덮어쓰지 않도록 유지"
            ],
            dataChanges: [
                "중앙 BUG 저장소의 신고 수와 상태 카운트를 앱에서 확인 가능",
                "종목 데이터, 스캐너 결과, 모의투자 포트폴리오 변경 없음"
            ],
            important: [
                "중앙 API 데이터를 기준으로 신고 목록을 맞추도록 변경",
                "업데이트 내용은 앱 첫 화면에 계속 표시"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.23",
            updatedAt: "2026-08-11 20:20 PDT",
            features: [
                "신고된 Market Movers/종목 분석 문구 개선",
                "종목별 매수 판단을 매수 가능, 분할 매수, 눌림목 대기, 추격 주의, 관망으로 세분화"
            ],
            fixes: [
                "모든 종목에 추격 매수 금지류 문구가 일괄 표시되는 문제 수정",
                "추격 판단에 등락률, 거래량, 기술 점수, 뉴스 영향, 추세 지속 점수를 반영",
                "캐나다 뉴스 없음 상태에서 수주/계약 호재 문구가 붙지 않는 기존 수정 유지"
            ],
            dataChanges: [
                "종목 데이터 삭제 없음",
                "모의투자 포트폴리오 변경 없음"
            ],
            important: [
                "추격 매수 금지는 단기 과열 점수가 높은 종목에만 표시",
                "상승 중이어도 과열이 낮으면 분할 매수 또는 매수 가능으로 표시"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.22",
            updatedAt: "2026-08-10 21:45 PDT",
            features: [
                "Git Push 기반 버그 신고 자동 처리",
                "GitHub Actions 자동 동기화",
                "앱에서 수동 Git 반영 확인 없이 commit 정보 자동 반영"
            ],
            fixes: [
                "commit의 BUG/FIX/DATA/IMP/UI ID 자동 감지",
                "중복 commit 처리 방지",
                "Git 동기화 실패 원인과 미매칭 ID 표시"
            ],
            dataChanges: [
                "버그 신고 이력에 GitHub Actions 처리 방식과 실행 정보 저장",
                "commit hash, commit 메시지, commit 날짜, 수정 버전 자동 기록",
                "종목 데이터와 모의투자 포트폴리오 변경 없음"
            ],
            important: [
                "정상 흐름은 git push만 하면 자동 처리",
                "기존 Git 반영 확인 버튼은 장애 복구용으로 유지"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.21",
            updatedAt: "2026-08-10 22:10 PDT",
            features: [
                "버그 신고와 Git commit 자동 연결",
                "관리자폰/설정 화면에 Git 반영 확인 버튼 추가",
                "신고 목록에서 수정 commit, 수정일, 수정 버전 표시"
            ],
            fixes: [
                "수동 조치 완료 중심 흐름을 commit 기반 자동 처리 흐름으로 개선",
                "서버가 commit 확인 실패 시 상태를 잘못 완료 처리하지 않도록 방어"
            ],
            dataChanges: [
                "버그 신고 데이터에 commit hash, commit 메시지, 수정/배포 버전 필드 추가",
                "종목 데이터와 모의투자 포트폴리오 변경 없음"
            ],
            important: [
                "commit 메시지에 BUG-001/FIX-004/DATA-003 같은 작업 ID를 넣으면 서버 동기화 시 자동 연결",
                "GitHub/서버 commit 확인 실패 시 기존 상태를 유지하고 오류 문구를 표시"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.20",
            updatedAt: "2026-08-10 21:05 PDT",
            features: [
                "모바일 신고 기반 버그 2건 조치",
                "수동 빠른 스캔은 서버 cooldown을 우회해 즉시 실행 요청",
                "캐나다 종목 뉴스 없음 상태를 더 명확하게 표시"
            ],
            fixes: [
                "ENB/BCE 등 캐나다 종목에 실제 뉴스가 없는데 수주/계약류 범용 호재 문구가 뉴스처럼 보이는 문제 수정",
                "스캐너 수동 실행이 cooldown 때문에 지연처럼 보이는 문제 완화"
            ],
            dataChanges: [
                "종목 데이터 삭제 없음",
                "스캐너 서버 cooldown 기본값 5분으로 조정",
                "모의투자 포트폴리오 변경 없음"
            ],
            important: [
                "공식/신뢰 캐나다 뉴스가 0건이면 섹터별 최대 호재/악재 안내를 실제 뉴스 포커스에 붙이지 않음",
                "전체 스캔은 기존 방식 유지, 빠른 스캔만 수동 실행 시 force 적용"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.19",
            updatedAt: "2026-08-10 01:00 PDT",
            features: [
                "버그 신고 업로드와 다운로드 기능 분리",
                "신고 직후 서버 저장 여부 확인",
                "관리자폰에서 서버 상태/API/신고 수 직접 확인"
            ],
            fixes: [
                "iPhone 17 신고가 서버에 실제 저장됐는지 조회로 검증",
                "iPhone 13 Pro Max 다운로드 시 서버 신고 수와 신규 건수 표시",
                "401/403/404/413/500 등 HTTP 오류를 구체적으로 표시"
            ],
            dataChanges: [
                "버그/개선사항 중앙 API 검증 흐름 강화",
                "종목 데이터와 모의투자 포트폴리오 변경 없음"
            ],
            important: [
                "POST 성공만으로 저장 성공으로 판단하지 않고 GET으로 재확인",
                "메인폰과 관리자폰 모두 업로드/다운로드/전체 동기화/서버 확인 버튼 제공"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.18",
            updatedAt: "2026-08-10 00:45 PDT",
            features: [
                "신고 동기화 실패 원인 상세 표시",
                "수동 신고 동기화 시 중앙 저장소 다운로드 후 업로드 병합",
                "메인폰 신고가 관리자폰에 안 보이는 문제 진단 강화"
            ],
            fixes: [
                "인증 실패, 서버 주소 오류, API 미배포, 서버 오류를 구분해서 표시",
                "동기화 실패 시 로컬 신고는 계속 보존"
            ],
            dataChanges: [
                "버그/개선사항 동기화 로직만 보강",
                "종목 데이터와 모의투자 포트폴리오 변경 없음"
            ],
            important: [
                "두 기기 모두 같은 서버 주소와 API 토큰을 저장해야 중앙 동기화가 성공",
                "실패 메시지가 401이면 Render MARKET_API_TOKEN 값을 다시 입력해야 함"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.17",
            updatedAt: "2026-08-10 00:35 PDT",
            features: [
                "설정 화면에 수동 신고 동기화 버튼 추가",
                "메인폰과 관리자폰 모두 직접 신고/수정 이력 동기화 가능"
            ],
            fixes: [
                "관리자 센터가 아닌 일반 설정 화면에서도 중앙 신고 저장소를 바로 불러올 수 있도록 개선"
            ],
            dataChanges: [
                "버그/개선사항 동기화만 실행",
                "모의투자 포트폴리오와 종목 데이터는 변경하지 않음"
            ],
            important: [
                "서버 API 토큰이 맞아야 수동 동기화가 성공",
                "두 기기 모두 같은 중앙 신고 데이터와 수정 완료 보고서를 확인 가능"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.16",
            updatedAt: "2026-08-10 00:25 PDT",
            features: [
                "관리자 센터 조치 완료 버튼 추가",
                "조치 완료 시 수정 완료 보고서 자동 생성",
                "메인폰에서도 해결 완료 항목의 수정 내용 보기 표시"
            ],
            fixes: [
                "수정 이력 저장만으로 끝나던 흐름을 조치 완료 → 보고서 생성 → 해결 완료로 연결",
                "확인되지 않은 발생 원인은 임의 작성하지 않고 원인 확인 필요로 표시"
            ],
            dataChanges: [
                "버그/개선사항 중앙 동기화 데이터에 수정 완료 보고서 보존",
                "모의투자 포트폴리오와 관리자 데이터 분리 유지",
                "종목 데이터 및 스캐너 CSV 변경 없음"
            ],
            important: [
                "iPhone 17은 메인폰, iPhone 13 Pro Max는 관리자폰 역할 유지",
                "두 기기 모두 일반 모의투자 기능은 그대로 사용 가능"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.15",
            updatedAt: "2026-08-10 00:10 PDT",
            features: [
                "2대 기기 운용 기준 보강",
                "현재 유선 연결된 iPhone 13 Pro Max를 임시 관리자 서브폰 대상으로 확인",
                "메인폰과 서브폰 모두 일반 모의투자 기능 유지"
            ],
            fixes: [
                "서버 모의투자 계좌가 두 기기에서 섞이지 않도록 기기별 Paper Trading ID 적용",
                "관리자 기능과 모의투자 데이터 저장 구조 분리"
            ],
            dataChanges: [
                "버그/개선사항은 중앙 API로 공유",
                "모의투자 포트폴리오는 기기별 계좌 파일로 분리",
                "종목 데이터 및 스캐너 CSV 변경 없음"
            ],
            important: [
                "서브폰은 관리자 센터를 추가로 사용할 뿐, 일반 모의투자 기능은 제한하지 않음",
                "관리자 기기는 하드코딩하지 않고 등록 방식으로 변경 가능하게 유지"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.14",
            updatedAt: "2026-08-09 23:45 PDT",
            features: [
                "서브폰용 임시 관리자 센터 추가",
                "관리자 기기 등록 후에만 관리자 탭 표시",
                "버그/개선사항 상태, 우선순위, 수정 이력 관리 기능 강화"
            ],
            fixes: [
                "신고 등록과 상태 변경이 로컬에만 남지 않도록 중앙 동기화 흐름 추가",
                "관리자 상세 화면에서 우선순위 변경과 상태 변경 이력을 확인 가능하도록 개선"
            ],
            dataChanges: [
                "서버 중앙 저장소 bug_reports.json 동기화 API 추가",
                "종목 데이터, 포트폴리오, 매수/매도, 뉴스 데이터 변경 없음"
            ],
            important: [
                "관리자 키는 소스코드에 저장하지 않고 서버 환경변수 또는 기존 API 토큰으로 검증",
                "일반 앱 화면에는 관리자 탭을 기본 노출하지 않음"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.13",
            updatedAt: "2026-08-09 23:18 PDT",
            features: [
                "매수 추천 0건 지속 문제를 개발 작업 관리에 자동 등록",
                "추천 후보 생성, 점수 계산, 위험도 평가, 최종 판정 흐름 점검 항목 추가",
                "국장/미장 추천 후보 생성 여부와 탈락 사유 로그 필요 항목 추가"
            ],
            fixes: [
                "추천이 없다는 결과를 시장 상황으로만 판단하지 않고 추천 알고리즘 점검 대상으로 관리",
                "추천 기준을 억지로 낮추지 않고 0건 원인을 먼저 추적하도록 작업 목표 명시"
            ],
            dataChanges: [
                "작업 관리 로컬 항목 1개 자동 생성",
                "종목 데이터 및 스캐너 CSV 변경 없음"
            ],
            important: [
                "조건을 만족하는 종목이 있는데도 최종 추천이 0건이면 추천 로직 버그로 판단",
                "정상적으로 0건인 경우에도 분석 종목 수, 후보 진입 수, 탈락 사유를 남기도록 관리"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.12",
            updatedAt: "2026-08-09 23:05 PDT",
            features: [
                "모의투자 개발 작업 관리 기능 추가",
                "버그 / 수정 / 개선 / 데이터 문제 / UI 문제 작업 등록",
                "우선순위, 시장, 관련 기능, 관련 티커, 발생 시간 기록",
                "수정 파일, 수정 내용, 수정 이유, 테스트 결과, 완료 날짜, 추가 메모 기록"
            ],
            fixes: [
                "기존 단순 버그 신고를 개발 작업 관리 시스템으로 확장",
                "작업 상태를 🔴 발견 → 🟡 수정 중 → 🔵 테스트 중 → 🟢 해결 → ⚪ 보류로 관리"
            ],
            dataChanges: [
                "작업 데이터는 기기 로컬에만 저장",
                "종목 데이터 및 스캐너 CSV 변경 없음"
            ],
            important: [
                "자동 코드 수정 기능이 아니라 문제 기록과 수정 이력 관리를 위한 개인용 도구",
                "기존 모의투자 매수/매도, 보유종목, 손익 계산 로직은 변경하지 않음"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.11",
            updatedAt: "2026-08-09 22:45 PDT",
            features: [
                "앱 내부 버그 신고 메뉴 추가",
                "문제 유형, 문제 내용, 관련 종목, 현재 화면, 시장, 발생 시간 자동 기록",
                "버그 신고 내역 목록과 상태 변경 기능 추가"
            ],
            fixes: [
                "사용 중 발견한 시세/손익/매수매도/UI 문제를 앱 안에서 즉시 저장 가능",
                "신고 당시 표시 가격, 데이터 상태, 업데이트 시간을 함께 보존"
            ],
            dataChanges: [
                "신고 데이터는 외부 전송 없이 기기 로컬에만 저장",
                "종목 데이터 및 스캐너 CSV 변경 없음"
            ],
            important: [
                "사진 첨부, 사용자 계정, 이메일 알림, 외부 신고 시스템은 제외",
                "상태는 🔴 미해결 → 🟡 확인 중 → 🟢 해결로 관리"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.10",
            updatedAt: "2026-08-09 22:20 PDT",
            features: [
                "모의투자 매수 화면에 🇰🇷 국장 / 🇺🇸 미장 탭 추가",
                "선택된 시장 안에서만 종목 검색 및 매수 가능",
                "국장 / 미장 투자금, 평가금액, 손익, 전체 합산 자산 요약 추가"
            ],
            fixes: [
                "국장과 미장 종목이 한 화면에 섞여 매수 종목을 찾기 어려운 문제 개선",
                "종목 선택 시 해당 종목의 시장 탭으로 자동 이동",
                "보유 종목과 거래내역을 선택된 시장 기준으로 분리 표시"
            ],
            dataChanges: [
                "종목 데이터 및 CSV 목록 변경 없음",
                "기존 전체 종목 552개 유지"
            ],
            important: [
                "UI 분리만 적용했고 기존 모의투자 매수/매도, 잔고, 손익 계산 로직은 유지",
                "국장 탭은 한국 주식만, 미장 탭은 미국 주식만 표시"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.9",
            updatedAt: "2026-08-08 21:21 PDT",
            features: [
                "캐나다 TSX / TSXV 종목별 공식·신뢰 뉴스 카드 추가",
                "뉴스 제목, 출처, 원문 링크, 게시 시간, 수집 시간 표시",
                "캐나다 뉴스 호재 / 악재 / 중립 및 중요 뉴스 표시"
            ],
            fixes: [
                "뉴스 수집 실패가 캐나다 종목 목록에 영향을 주지 않도록 분리",
                "원격 결과에 기존 종목 누락이 감지되면 마지막 업데이트 데이터 유지",
                "SEDAR+ / Reuters 차단 상태를 소스 상태로 표시"
            ],
            dataChanges: [
                "캐나다 종목 84개 유지",
                "TSXV 대표 종목 Kraken Robotics(PNG.V) 추가",
                "종목 삭제 방지 검증 로직 추가"
            ],
            important: [
                "사용자가 명시적으로 삭제 지시하지 않은 종목은 자동 삭제되지 않음",
                "배포 전 이전 종목 수와 새 종목 수를 비교해 감소 시 업데이트 중단"
            ]
        ),
        AppUpdateEntry(
            version: "v1.0.8",
            updatedAt: "2026-08-08",
            features: [
                "캐나다 주식 전용 요약과 TSX Movers 분리 강화",
                "실적 센터 국장 / 미장 분리",
                "Market Movers 급등락 / 거래량 / 거래대금 / AI HOT 화면 추가"
            ],
            fixes: [
                "API 실패 시 즐겨찾기만 표시되는 문제 수정",
                "모의투자 국장 시세를 네이버 정규장 / 종가 기준으로 동기화"
            ],
            dataChanges: [
                "보유 평가금액, 평가손익, 수익률, 일일 손익을 최신 quote로 재계산"
            ],
            important: [
                "최신 데이터 실패 시 마지막 정상 데이터를 우선 표시"
            ]
        )
    ]

    private var latest: AppUpdateEntry {
        entries[0]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top, spacing: 9) {
                Image(systemName: "arrow.down.app.fill")
                    .font(.title3.bold())
                    .foregroundStyle(.mint)
                    .frame(width: 30, height: 30)
                    .background(Color.mint.opacity(0.12), in: Circle())

                VStack(alignment: .leading, spacing: 3) {
                    Text("업데이트 완료 — \(latest.version)")
                        .font(.subheadline.bold())
                    Text(latest.updatedAt)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Text("NEW")
                    .font(.caption2.bold())
                    .foregroundStyle(.black)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(Color.mint, in: Capsule())
            }

            AppUpdateEntryView(entry: latest)

            if entries.count > 1 {
                DisclosureGroup(isExpanded: $showHistory) {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(entries.dropFirst()) { entry in
                            VStack(alignment: .leading, spacing: 7) {
                                Text("\(entry.version) · \(entry.updatedAt)")
                                    .font(.caption.bold())
                                    .foregroundStyle(.secondary)
                                AppUpdateEntryView(entry: entry)
                            }
                            .padding(.top, 4)
                        }
                    }
                    .padding(.top, 6)
                } label: {
                    Text("이전 업데이트 내역")
                        .font(.caption.bold())
                        .foregroundStyle(.mint)
                }
            }
        }
        .padding(13)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.mint.opacity(0.28), lineWidth: 1))
    }
}

private struct AppUpdateEntryView: View {
    let entry: AppUpdateEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            updateGroup(title: "새 기능", items: entry.features, tint: .mint)
            updateGroup(title: "버그 수정", items: entry.fixes, tint: .orange)
            updateGroup(title: "데이터 / 스캐너", items: entry.dataChanges, tint: .cyan)
            updateGroup(title: "중요 변경", items: entry.important, tint: .red)
        }
    }

    @ViewBuilder
    private func updateGroup(title: String, items: [String], tint: Color) -> some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.caption2.bold())
                    .foregroundStyle(tint)
                ForEach(items, id: \.self) { item in
                    Label(item, systemImage: "checkmark.circle.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.primary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

private struct CanadaHomeOverviewCard: View {
    let results: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    private var highDividendPicks: [ScannerResult] {
        results
            .filter { $0.dividendYieldPercent > 0 }
            .sorted {
                if $0.dividendYieldPercent == $1.dividendYieldPercent {
                    return $0.aiRankScore > $1.aiRankScore
                }
                return $0.dividendYieldPercent > $1.dividendYieldPercent
            }
            .prefix(3)
            .map { $0 }
    }

    private var leaderPicks: [ScannerResult] {
        results
            .sorted {
                if $0.aiRankScore == $1.aiRankScore {
                    return $0.changePercent > $1.changePercent
                }
                return $0.aiRankScore > $1.aiRankScore
            }
            .prefix(4)
            .map { $0 }
    }

    private var moverPicks: [ScannerResult] {
        results
            .sorted {
                if abs($0.changePercent) == abs($1.changePercent) {
                    return $0.volumeRatio > $1.volumeRatio
                }
                return abs($0.changePercent) > abs($1.changePercent)
            }
            .prefix(3)
            .map { $0 }
    }

    private var averageYield: Double {
        let yields = results.map(\.dividendYieldPercent).filter { $0 > 0 }
        guard !yields.isEmpty else { return 0 }
        return yields.reduce(0, +) / Double(yields.count)
    }

    private var topSectorText: String {
        let grouped = Dictionary(grouping: results) { $0.sectorCategoryName }
        let best = grouped
            .map { key, values in
                (key, values.map(\.changePercent).reduce(0, +) / Double(max(1, values.count)), values.count)
            }
            .sorted {
                if $0.1 == $1.1 { return $0.2 > $1.2 }
                return $0.1 > $1.1
            }
            .first
        guard let best else { return "섹터 대기" }
        return "\(best.0) \(best.1 >= 0 ? "+" : "")\(String(format: "%.1f", best.1))%"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 11) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "leaf.circle.fill")
                    .font(.title2)
                    .foregroundStyle(.mint)
                    .frame(width: 32, height: 32)

                VStack(alignment: .leading, spacing: 3) {
                    Text("캐나다 주식")
                        .font(.headline.bold())
                    Text("TSX 리더 · 배당 · 오늘 움직임")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text("\(results.count)")
                    .font(.headline.monospacedDigit().bold())
                    .foregroundStyle(.mint)
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 94), spacing: 8)], alignment: .leading, spacing: 8) {
                DetailMiniMetric(title: "평균 배당", value: averageYield > 0 ? "\(String(format: "%.2f", averageYield))%" : "-", tint: .mint)
                DetailMiniMetric(title: "강한 섹터", value: topSectorText, tint: .orange)
                DetailMiniMetric(title: "관심 후보", value: "\(leaderPicks.filter { $0.aiRankScore >= 45 }.count)", tint: .purple)
            }

            CanadaMiniGroup(
                title: "AI/모멘텀 후보",
                stocks: leaderPicks,
                favoriteTickers: favoriteTickers,
                aiPickDates: aiPickDates,
                toggleFavorite: toggleFavorite
            )

            CanadaMiniGroup(
                title: "고배당 우선 확인",
                stocks: highDividendPicks,
                favoriteTickers: favoriteTickers,
                aiPickDates: aiPickDates,
                toggleFavorite: toggleFavorite
            )

            CanadaMiniGroup(
                title: "오늘 변동성",
                stocks: moverPicks,
                favoriteTickers: favoriteTickers,
                aiPickDates: aiPickDates,
                toggleFavorite: toggleFavorite
            )

            Text("캐나다 종목은 CAD 기준으로 표시합니다. 배당 정보는 최근/예상 지급일과 배당률을 함께 확인하세요.")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.mint.opacity(0.24), lineWidth: 1))
    }
}

private struct CanadaMiniGroup: View {
    let title: String
    let stocks: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            if stocks.isEmpty {
                Text("조건에 맞는 캐나다 종목이 없습니다.")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(9)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            } else {
                ForEach(stocks) { result in
                    NavigationLink {
                        ResultDetailView(
                            result: result,
                            isFavorite: favoriteTickers.contains(result.ticker),
                            recommendationDate: aiPickDates[result.ticker]
                        ) {
                            toggleFavorite(result)
                        }
                    } label: {
                        CanadaMiniStockRow(result: result)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

private struct CanadaMiniStockRow: View {
    let result: ScannerResult

    var body: some View {
        HStack(spacing: 9) {
            VStack(alignment: .leading, spacing: 3) {
                LocalizedStockNameView(
                    name: result.name,
                    ticker: result.ticker,
                    market: result.marketText,
                    primaryFont: .caption.bold(),
                    secondaryFont: .caption2.weight(.medium)
                )
                Text("\(result.sectorCategoryName) · \(result.dividendText) · 배당 \(String(format: "%.2f", result.dividendYieldPercent))%")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
            }
            .layoutPriority(1)

            Spacer(minLength: 6)

            VStack(alignment: .trailing, spacing: 3) {
                Text(result.formattedPrice)
                    .font(.caption.monospacedDigit().bold())
                    .lineLimit(1)
                    .minimumScaleFactor(0.68)
                Text(result.changeBadgeText)
                    .font(.caption2.monospacedDigit().bold())
                    .foregroundStyle(result.changePercent >= 0 ? .red : .blue)
            }
            .frame(maxWidth: 118, alignment: .trailing)
        }
        .padding(9)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct ScannerBrowserSection: View {
    @Binding var filter: ResultFilter
    @Binding var marketFilter: MarketFilter
    @Binding var dividendFilter: DividendFilter
    let results: [ScannerResult]
    let displayedResults: [ScannerResult]
    let favoriteTickers: Set<String>
    let newAiPickTickers: Set<String>
    let aiPickDates: [String: String]
    let positionEvaluations: [String: PositionEvaluation]
    let isSearching: Bool
    let resetFilters: () -> Void
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "스캐너", subtitle: "시장별 종목 탐색")

            Picker("Filter", selection: $filter) {
                ForEach(ResultFilter.allCases) { item in
                    Text(item.title).tag(item)
                }
            }
            .pickerStyle(.segmented)

            Picker("Market", selection: $marketFilter) {
                ForEach(MarketFilter.allCases) { item in
                    Text(item.title).tag(item)
                }
            }
            .pickerStyle(.segmented)

            if marketFilter == .canada {
                Picker("Dividend", selection: $dividendFilter) {
                    ForEach(DividendFilter.allCases) { item in
                        Text(item.title).tag(item)
                    }
                }
                .pickerStyle(.segmented)
                .transition(.opacity)
            }

            if displayedResults.isEmpty {
                EmptySearchView(
                    hasSearchText: isSearching,
                    canResetFilters: !isSearching && (!results.isEmpty || filter != .all || marketFilter != .all),
                    resetAction: resetFilters
                )
            } else {
                MainResultListSection(
                    displayedResults: displayedResults,
                    favoriteTickers: favoriteTickers,
                    newAiPickTickers: newAiPickTickers,
                    aiPickDates: aiPickDates,
                    positionEvaluations: positionEvaluations,
                    toggleFavorite: toggleFavorite
                )
            }
        }
    }
}

private struct AIAnalysisHomeSection: View {
    let allResults: [ScannerResult]
    let watchlist: [ScannerResult]
    let leadingCandidates: [ScannerResult]
    let missedCandidates: [ScannerResult]
    let riskCandidates: [ScannerResult]
    let keywordCandidates: [ScannerResult]
    let flowRadar: MoneyFlowRadarData
    let remoteConfig: RemoteServerConfig
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "AI 분석", subtitle: "종목 분석, 목표가, 리스크, 선행 신호")
            TopPriorityShortcut(
                watchlist: watchlist,
                abnormalCount: leadingCandidates.count,
                favoriteTickers: favoriteTickers,
                aiPickDates: aiPickDates,
                toggleFavorite: toggleFavorite
            )
            AIScreeningSimulatorCard(
                remoteConfig: remoteConfig,
                aiCandidates: watchlist,
                searchUniverse: allResults
            )
            NavigationLink {
                LeadDetectionPage(
                    leadingCandidates: leadingCandidates,
                    missedCandidates: missedCandidates,
                    riskCandidates: riskCandidates,
                    keywordCandidates: keywordCandidates,
                    flowRadar: flowRadar,
                    favoriteTickers: favoriteTickers,
                    aiPickDates: aiPickDates,
                    toggleFavorite: toggleFavorite
                )
            } label: {
                DashboardNavigationCard(
                    title: "선행 시그널 분석",
                    subtitle: leadingCandidates.first.map { "\($0.name) · \($0.notYetMovedSummary)" } ?? "초기 신호 탐색 중",
                    systemImage: "scope",
                    tint: .pink,
                    count: leadingCandidates.count + missedCandidates.count
                )
            }
            .buttonStyle(.plain)
        }
    }
}

private struct AIScreeningSimulatorCard: View {
    let remoteConfig: RemoteServerConfig
    let aiCandidates: [ScannerResult]
    let searchUniverse: [ScannerResult]
    @State private var screening: AIScreeningPayload?
    @State private var backtest: AIScreeningBacktestPayload?
    @State private var paperAccount: PaperTradingAccountPayload?
    @State private var paperAccountLoaded = false
    @State private var isRunning = false
    @State private var statusText = "서버 AI 스크리닝 대기"
    @State private var depositText = ""
    @State private var depositCurrency: PaperDepositCurrency = .krw
    @State private var paperUSDCash = PaperUSDCashStore.load()
    @State private var simpleQuantityText = "1"
    @State private var paperSearchText = ""
    @State private var selectedPaperStock: PaperTradeStock?
    @State private var recentPaperTickers = PaperTradeRecentStore.load()
    @State private var favoritePaperTickers = PaperTradeFavoriteStore.load()
    @State private var showAdvancedPaperInput = false
    @State private var paperTickerText = ""
    @State private var paperQuantityText = ""
    @State private var paperPriceText = ""
    @State private var paperMode: PaperTradingMode = .buy
    @State private var selectedPaperMarket: PaperTradingMarket = .korea
    @State private var tradeToast: PaperTradeToast?
    @State private var customSellQuantityText = ""
    @State private var paperQuoteOverrides: [String: LiveQuote] = [:]
    @State private var paperLastQuoteUpdatedAt: Date?
    @State private var paperLiveConnectionStatus = "실시간 연결 대기"
    @State private var paperAutoRefreshInterval: PaperAutoRefreshInterval = PaperAutoRefreshIntervalStore.load()
    @State private var cachedStockUniverse: [PaperTradeStock] = []
    @State private var cachedAIPaperStocks: [PaperTradeStock] = []
    @State private var cachedPopularPaperStocks: [PaperTradeStock] = []
    @State private var cachedRecentPaperStocks: [PaperTradeStock] = []
    @State private var cachedFavoritePaperStocks: [PaperTradeStock] = []
    private let paperAutoRefreshTimer = Timer.publish(every: 5, on: .main, in: .common).autoconnect()

    private var topRows: [AIScreeningRow] {
        Array((screening?.rows ?? []).prefix(5))
    }

    private var stockUniverse: [PaperTradeStock] {
        cachedStockUniverse
    }

    private var aiPaperStocks: [PaperTradeStock] {
        cachedAIPaperStocks.filter { selectedPaperMarket.matches($0) }
    }

    private var popularPaperStocks: [PaperTradeStock] {
        cachedPopularPaperStocks.filter { selectedPaperMarket.matches($0) }
    }

    private var recentPaperStocks: [PaperTradeStock] {
        cachedRecentPaperStocks.filter { selectedPaperMarket.matches($0) }
    }

    private var favoritePaperStocks: [PaperTradeStock] {
        cachedFavoritePaperStocks.filter { selectedPaperMarket.matches($0) }
    }

    private var activeMarketStocks: [PaperTradeStock] {
        stockUniverse.filter { selectedPaperMarket.matches($0) }
    }

    private var searchResults: [PaperTradeStock] {
        let query = paperSearchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return [] }
        return activeMarketStocks
            .filter { $0.matches(query) }
            .sorted { lhs, rhs in
                if lhs.searchRank(query) == rhs.searchRank(query) {
                    return lhs.score > rhs.score
                }
                return lhs.searchRank(query) > rhs.searchRank(query)
            }
            .prefixArray(30)
    }

    private var paperCacheSignature: String {
        let ai = aiCandidates.prefix(8).map(\.ticker).joined(separator: "|")
        let universe = searchUniverse.prefix(12).map(\.ticker).joined(separator: "|")
        let rows = (screening?.rows ?? []).prefix(8).map(\.ticker).joined(separator: "|")
        return "\(aiCandidates.count):\(searchUniverse.count):\(screening?.rows.count ?? 0):\(ai):\(universe):\(rows)"
    }

    private var estimatedBuyAmountText: String {
        guard let stock = selectedPaperStock,
              let quantity = parseNumber(simpleQuantityText),
              quantity > 0 else {
            return "예상 매수금액 -"
        }
        return "예상 매수금액 \(tradeAmountText(stock: stock, quantity: quantity))"
    }

    private var estimatedRemainingCashText: String {
        guard let account = paperAccount,
              let stock = selectedPaperStock,
              let quantity = parseNumber(simpleQuantityText),
              quantity > 0 else {
            return "남은 현금 -"
        }
        if stock.marketText == "미장" {
            let remaining = paperUSDCash - (stock.price * quantity)
            return "남은 USD \(PaperTradeCurrencyFormatter.usdCashText(remaining))"
        }
        if stock.marketText == "캐나다" {
            return "캐나다주식 총액 \(tradeAmountText(stock: stock, quantity: quantity))"
        }
        let remaining = account.cash - (stock.price * quantity)
        return "남은 현금 \(money(remaining))"
    }

    private var availableCashForSelectedStock: Double {
        guard let stock = selectedPaperStock else {
            return 0
        }
        if PaperTradeCurrencyFormatter.isUSTicker(stock.ticker) {
            return paperUSDCash
        }
        return paperAccount?.cash ?? 0
    }

    private var selectedPaperPosition: PaperTradingPosition? {
        guard let stock = selectedPaperStock else {
            return nil
        }
        let key = PaperMarketClassifier.identityKey(for: stock.ticker, fallback: stock.marketText)
        return (paperAccount ?? PaperTradingLocalStore.load())?
            .normalizedForDisplay()
            .positions
            .first { PaperMarketClassifier.identityKey(for: $0.ticker) == key }
    }

    private var selectedHeldQuantity: Double {
        selectedPaperPosition?.quantity ?? 0
    }

    private var selectedOrderQuantity: Double {
        parseNumber(simpleQuantityText) ?? 0
    }

    private var selectedOrderAmountText: String {
        guard let stock = selectedPaperStock, selectedOrderQuantity > 0 else {
            return "-"
        }
        return tradeAmountText(stock: stock, quantity: selectedOrderQuantity)
    }

    private var selectedAvailableCashText: String {
        guard let stock = selectedPaperStock else {
            return "-"
        }
        if PaperTradeCurrencyFormatter.isUSTicker(stock.ticker) {
            return PaperTradeCurrencyFormatter.usdCashText(paperUSDCash)
        }
        return money(paperAccount?.cash ?? 0)
    }

    private func emptyPaperAccount() -> PaperTradingAccountPayload {
        PaperTradingAccountPayload(
            cash: 0,
            totalValue: 0,
            positions: [],
            trades: [],
            updatedAt: ISO8601DateFormatter().string(from: Date()),
            safetyNotice: "실제 자동주문 없음 · 모든 거래는 모의투자 · 수익 보장 아님"
        )
    }

    @MainActor
    private func resetPaperTrading() {
        let empty = emptyPaperAccount()
        paperAccount = empty
        paperAccountLoaded = true
        paperUSDCash = 0
        selectedPaperStock = nil
        simpleQuantityText = "1"
        paperTickerText = ""
        paperQuantityText = ""
        paperPriceText = ""
        depositText = ""
        customSellQuantityText = ""
        paperQuoteOverrides = [:]
        paperLastQuoteUpdatedAt = nil
        PaperTradingLocalStore.resetAll()
        PaperUSDCashStore.reset()
        PaperTradingLocalStore.save(empty)
        statusText = "모의투자 기록/금액 초기화 완료"
        tradeToast = PaperTradeToast(
            style: .success,
            title: "초기화 완료",
            message: "보유 종목, 거래 내역, 원화/미화 현금을 모두 비웠습니다.",
            detail: "새로 입금해서 다시 시작하세요.",
            showsHoldingsButton: false
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "한국 AI 스크리닝 / 모의투자", subtitle: "조건 기반 선별, 백테스트, 모의계좌")

            Text(statusText)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 8) {
                Button {
                    dismissKeyboard()
                    Task { await runScreening() }
                } label: {
                    Label("스크리닝", systemImage: "sparkles")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(isRunning || !remoteConfig.isReady)

                Button {
                    dismissKeyboard()
                    Task { await runBacktest() }
                } label: {
                    Label("백테스트", systemImage: "chart.xyaxis.line")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(isRunning || !remoteConfig.isReady)

                Button {
                    dismissKeyboard()
                    Task { await loadPaperAccount() }
                } label: {
                    Label("모의계좌", systemImage: "wallet.pass")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(isRunning || !remoteConfig.isReady)
            }
            .font(.caption.bold())

            Picker("모의투자 화면", selection: $paperMode) {
                ForEach(PaperTradingMode.allCases) { mode in
                    Text(mode.title).tag(mode)
                }
            }
            .pickerStyle(.segmented)

            if paperMode == .buy {
            VStack(alignment: .leading, spacing: 10) {
            PaperCashHeader(account: paperAccount, usdCash: paperUSDCash)
                PaperMarketAssetSummaryCard(
                    account: paperAccount,
                    usdCash: paperUSDCash,
                    liveStocks: stockUniverse,
                    quoteOverrides: paperQuoteOverrides
                )

                Picker("매수 시장", selection: $selectedPaperMarket) {
                    ForEach(PaperTradingMarket.allCases) { market in
                        Text(market.tabTitle).tag(market)
                    }
                }
                .pickerStyle(.segmented)

                HStack(spacing: 8) {
                    Label(selectedPaperMarket.stockListTitle, systemImage: selectedPaperMarket.iconName)
                        .font(.subheadline.bold())
                    Spacer(minLength: 8)
                    Text("\(activeMarketStocks.count)개")
                        .font(.caption.monospacedDigit().bold())
                        .foregroundStyle(.secondary)
                }

                HStack {
                    Text("쉬운 모의투자")
                        .font(.subheadline.bold())
                    Spacer()
                    if let selectedPaperStock {
                        Text(selectedPaperStock.name)
                            .font(.caption.bold())
                            .foregroundStyle(.mint)
                            .lineLimit(1)
                    }
                }

                VStack(alignment: .leading, spacing: 8) {
                    Picker("입금 통화", selection: $depositCurrency) {
                        ForEach(PaperDepositCurrency.allCases) { currency in
                            Text(currency.title).tag(currency)
                        }
                    }
                    .pickerStyle(.segmented)

                    HStack(spacing: 8) {
                        ScreeningTextField(title: depositCurrency.inputTitle, text: $depositText, keyboard: .decimalPad)
                        Button(depositCurrency.buttonTitle) {
                            dismissKeyboard()
                            Task { await depositPaperCash() }
                        }
                        .buttonStyle(.bordered)
                        .font(.caption.bold())
                        .disabled(isRunning)
                    }

                    Text(depositCurrency.helperText)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if let selectedPaperStock {
                    PaperTradeOrderPanel(
                        stock: selectedPaperStock,
                        isFavorite: favoritePaperTickers.contains(selectedPaperStock.normalizedTicker),
                        heldQuantity: selectedHeldQuantity,
                        availableCashText: selectedAvailableCashText,
                        orderQuantity: $simpleQuantityText,
                        orderAmountText: selectedOrderAmountText,
                        estimatedRemainingText: estimatedRemainingCashText,
                        isRunning: isRunning,
                        canBuy: availableCashForSelectedStock > 0,
                        canSell: selectedHeldQuantity > 0,
                        toggleFavorite: { togglePaperFavorite(selectedPaperStock) },
                        buyAction: {
                            dismissKeyboard()
                            Task { await buySelectedByQuantity() }
                        },
                        sellAction: {
                            dismissKeyboard()
                            Task { await sellSelectedByQuantity() }
                        },
                        setQuantityPercent: { percent in
                            dismissKeyboard()
                            Task { await setBuyQuantity(percent: percent) }
                        }
                    )
                    .transition(.opacity.combined(with: .move(edge: .top)))
                } else {
                    PaperTradeEmptySelectionCard()
                }

                if !aiPaperStocks.isEmpty {
                    PaperAITodayRecommendationSection(
                        stocks: aiPaperStocks,
                        selectedTicker: selectedPaperStock?.ticker,
                        favoriteTickers: favoritePaperTickers,
                        selectAction: selectPaperStock,
                        paperTradeAction: { stock in
                            selectPaperStock(stock)
                            statusText = "\(stock.name) 모의투자 준비 완료"
                        },
                        favoriteAction: togglePaperFavorite
                    )
                }

                VStack(alignment: .leading, spacing: 8) {
                    Label("종목 검색", systemImage: "magnifyingglass")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                    TextField(selectedPaperMarket.searchPlaceholder, text: $paperSearchText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .submitLabel(.done)
                        .onSubmit { dismissKeyboard() }
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .frame(height: 38)
                        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))

                    if !favoritePaperStocks.isEmpty {
                        PaperStockShelf(
                            title: "★ 즐겨찾기",
                            stocks: favoritePaperStocks,
                            selectedTicker: selectedPaperStock?.ticker,
                            favoriteTickers: favoritePaperTickers,
                            selectAction: selectPaperStock,
                            favoriteAction: togglePaperFavorite
                        )
                    }

                    if paperSearchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        if !recentPaperStocks.isEmpty {
                            PaperStockShelf(
                                title: "최근 검색",
                                stocks: recentPaperStocks,
                                selectedTicker: selectedPaperStock?.ticker,
                                favoriteTickers: favoritePaperTickers,
                                selectAction: selectPaperStock,
                                favoriteAction: togglePaperFavorite
                            )
                        }
                        PaperTradingPlatformSection(
                            market: selectedPaperMarket,
                            allStocks: activeMarketStocks,
                            selectedTicker: selectedPaperStock?.ticker,
                            favoriteTickers: favoritePaperTickers,
                            selectAction: selectPaperStock,
                            favoriteAction: togglePaperFavorite
                        )
                    } else if searchResults.isEmpty {
                        Text("검색 결과 없음 · 종목명이나 티커를 다시 입력해보세요.")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.secondary)
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
                    } else {
                        PaperStockShelf(
                            title: "검색 결과",
                            stocks: searchResults,
                            selectedTicker: selectedPaperStock?.ticker,
                            favoriteTickers: favoritePaperTickers,
                            selectAction: selectPaperStock,
                            favoriteAction: togglePaperFavorite
                        )
                    }
                }

                Text("검색, AI 추천, 인기 종목, 최근 검색에서 누르면 티커/회사명/현재가가 자동 입력됩니다.")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                Button(role: .destructive) {
                    resetPaperTrading()
                } label: {
                    Label("모의투자 기록/금액 초기화", systemImage: "trash")
                }
                .buttonStyle(.bordered)
                .font(.caption.bold())

                Button {
                    withAnimation(.easeInOut(duration: 0.18)) {
                        showAdvancedPaperInput.toggle()
                    }
                } label: {
                    Label(showAdvancedPaperInput ? "직접 입력 닫기" : "직접 입력 열기", systemImage: showAdvancedPaperInput ? "chevron.up" : "chevron.down")
                }
                .buttonStyle(.borderless)
                .font(.caption.bold())

                if showAdvancedPaperInput {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("직접 입력")
                            .font(.caption.bold())
                        HStack(spacing: 8) {
                            ScreeningTextField(title: "티커", text: $paperTickerText, keyboard: .default)
                            ScreeningTextField(title: "수량", text: $paperQuantityText, keyboard: .decimalPad)
                            ScreeningTextField(title: "가격", text: $paperPriceText, keyboard: .decimalPad)
                        }
                        HStack(spacing: 8) {
                            Button("모의 매수") {
                                dismissKeyboard()
                                Task { await simulatePaperTrade(side: "buy") }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(isRunning || !remoteConfig.isReady)
                            Button("모의 매도") {
                                dismissKeyboard()
                                Task { await simulatePaperTrade(side: "sell") }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isRunning || !remoteConfig.isReady)
                        }
                        .font(.caption.bold())
                    }
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
            .padding(10)
            .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            } else if paperMode == .holdings {
                PaperHoldingsPanel(
                    account: paperAccount,
                    usdCash: paperUSDCash,
                    market: selectedPaperMarket,
                    isLoaded: paperAccountLoaded,
                    liveStocks: stockUniverse,
                    quoteOverrides: paperQuoteOverrides,
                    lastQuoteUpdatedAt: paperLastQuoteUpdatedAt,
                    liveConnectionStatus: paperLiveConnectionStatus,
                    autoRefreshInterval: paperAutoRefreshInterval,
                    customSellQuantityText: $customSellQuantityText,
                    refreshAction: { Task { await refreshPaperQuotes(force: true) } },
                    setAutoRefreshInterval: { interval in
                        paperAutoRefreshInterval = interval
                        PaperAutoRefreshIntervalStore.save(interval)
                    },
                    sellAllAction: { position in Task { await sellPosition(position) } },
                    sellHalfAction: { position, fraction in Task { await sellPosition(position, fraction: fraction) } },
                    sellCustomAction: { position, quantity in Task { await sellPosition(position, quantity: quantity) } }
                )
            } else {
                if paperAccountLoaded {
                    PaperTradeHistoryPanel(
                        account: paperAccount,
                        market: selectedPaperMarket,
                        liveStocks: stockUniverse,
                        quoteOverrides: paperQuoteOverrides
                    )
                } else {
                    PaperPortfolioLoadingCard()
                }
            }

            if isRunning {
                ProgressView()
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            if !topRows.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("AI 스크리닝 TOP")
                        .font(.subheadline.bold())
                    ForEach(topRows) { row in
                        AIScreeningRowView(
                            row: row,
                            isSelected: selectedPaperStock?.normalizedTicker == PaperTradeStock.normalizedTicker(row.ticker)
                        ) {
                            selectPaperRow(row)
                        }
                    }
                }
            }

            if let summary = backtest?.summary {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 96), spacing: 8)], alignment: .leading, spacing: 8) {
                    ScreeningMetricBox(title: "거래", value: "\(summary.totalTrades ?? 0)회", tint: .secondary)
                    ScreeningMetricBox(title: "승률", value: percent(summary.winRatePct), tint: .mint)
                    ScreeningMetricBox(title: "최종", value: signedPercent(summary.finalReturnPct), tint: (summary.finalReturnPct ?? 0) >= 0 ? .red : .blue)
                    ScreeningMetricBox(title: "MDD", value: percent(summary.mddPct), tint: .orange)
                    ScreeningMetricBox(title: "PF", value: number(summary.profitFactor), tint: .purple)
                    ScreeningMetricBox(title: "Sharpe", value: number(summary.sharpeRatio), tint: .cyan)
                }
            }

            Text(screening?.safetyNotice ?? backtest?.safetyNotice ?? paperAccount?.safetyNotice ?? "실제 자동주문 없음 · 모든 거래는 모의투자 · 수익 보장 아님")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
        .contentShape(Rectangle())
        .onTapGesture { dismissKeyboard() }
        .onChange(of: depositText) { _, newValue in
            let formatted = commaFormattedInteger(newValue)
            if formatted != newValue { depositText = formatted }
        }
        .onChange(of: simpleQuantityText) { _, newValue in
            let clean = numericQuantity(newValue)
            if clean != newValue { simpleQuantityText = clean }
        }
        .onChange(of: paperCacheSignature) { _, _ in
            rebuildPaperCaches()
        }
        .onChange(of: recentPaperTickers) { _, _ in
            rebuildPaperShelfCaches()
        }
        .onChange(of: favoritePaperTickers) { _, _ in
            rebuildPaperShelfCaches()
        }
        .onChange(of: selectedPaperMarket) { _, market in
            paperSearchText = ""
            if let selectedPaperStock, !market.matches(selectedPaperStock) {
                self.selectedPaperStock = nil
            }
            statusText = "\(market.displayTitle) 선택 · 해당 시장 종목만 검색/매수"
        }
        .task {
            rebuildPaperCaches()
            if PaperTradingLocalStore.consumeOneTimePlatformReset() {
                let empty = emptyPaperAccount()
                paperAccount = empty
                paperAccountLoaded = true
                paperUSDCash = 0
                PaperUSDCashStore.reset()
                PaperTradingLocalStore.save(empty)
                statusText = "모의투자 기존 기록 초기화 완료"
                return
            }
            if let localAccount = PaperTradingLocalStore.load(), paperAccount == nil {
                let normalizedLocal = localAccount.normalizedForDisplay()
                paperAccount = normalizedLocal
                paperAccountLoaded = true
                statusText = "로컬 모의계좌 복구 완료"
                PaperTradingLocalStore.save(normalizedLocal)
                await refreshPaperQuotes(force: true)
            }
            if paperAccount == nil, remoteConfig.isReady {
                await loadPaperAccount()
            } else {
                paperAccountLoaded = true
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.willResignActiveNotification)) { _ in
            if let paperAccount {
                PaperTradingLocalStore.save(paperAccount)
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didEnterBackgroundNotification)) { _ in
            if let paperAccount {
                PaperTradingLocalStore.save(paperAccount)
            }
        }
        .onReceive(paperAutoRefreshTimer) { _ in
            guard paperMode == .holdings else {
                return
            }
            let hasUSPosition = paperAccount?.positions.contains { PaperTradeCurrencyFormatter.isUSTicker($0.ticker) } ?? false
            let shouldLiveRefreshUS = hasUSPosition && Date().timeIntervalSince(paperLastQuoteUpdatedAt ?? .distantPast) >= 5
            let shouldConfiguredRefresh = paperAutoRefreshInterval != .off && paperAutoRefreshInterval.shouldRefresh(since: paperLastQuoteUpdatedAt)
            guard shouldLiveRefreshUS || shouldConfiguredRefresh else { return }
            Task { await refreshPaperQuotes(force: false) }
        }
        .onChange(of: paperMode) { _, mode in
            if mode == .holdings {
                Task { await refreshPaperQuotes(force: true) }
            }
        }
        .overlay(alignment: .top) {
            if let tradeToast {
                PaperTradeToastView(
                    toast: tradeToast,
                    holdingsAction: {
                        withAnimation(.easeInOut(duration: 0.18)) {
                            paperMode = .holdings
                            self.tradeToast = nil
                        }
                    },
                    dismissAction: {
                        withAnimation(.easeInOut(duration: 0.18)) {
                            self.tradeToast = nil
                        }
                    }
                )
                .padding(10)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .safeAreaInset(edge: .bottom) {
            if paperMode == .buy, let selectedPaperStock {
                PaperStickyTradeBar(
                    stock: selectedPaperStock,
                    quantityText: simpleQuantityText,
                    orderAmountText: selectedOrderAmountText,
                    canBuy: !isRunning && availableCashForSelectedStock > 0 && selectedOrderQuantity > 0,
                    canSell: !isRunning && selectedHeldQuantity > 0 && selectedOrderQuantity > 0,
                    buyAction: {
                        dismissKeyboard()
                        Task { await buySelectedByQuantity() }
                    },
                    sellAction: {
                        dismissKeyboard()
                        Task { await sellSelectedByQuantity() }
                    }
                )
            }
        }
    }

    @MainActor
    private func rebuildPaperCaches() {
        let scannerStocks = searchUniverse.map(PaperTradeStock.init(result:))
        let aiStocks = aiCandidates.map(PaperTradeStock.init(result:))
        let screeningStocks = (screening?.rows ?? []).map(PaperTradeStock.init(row:))
        let universe = (PaperTradeStock.semiconductorETFDefaults + aiStocks + screeningStocks + scannerStocks).uniquedByTicker()

        let aiTop = (aiCandidates.prefix(16).map(PaperTradeStock.init(result:)) + topRows.map(PaperTradeStock.init(row:)) + PaperTradeStock.semiconductorETFDefaults)
            .uniquedByTicker()
            .prefixArray(16)

        cachedStockUniverse = universe
        cachedAIPaperStocks = aiTop
        rebuildPaperShelfCaches(universe: universe)
    }

    @MainActor
    private func rebuildPaperShelfCaches(universe: [PaperTradeStock]? = nil) {
        let universe = universe ?? cachedStockUniverse
        let preferredTickers = [
            "005930", "000660", "035420", "035720", "012450", "005380", "034020", "010120",
            "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "PLTR", "META", "MU", "SNDK", "WDC",
            "AMD", "AVGO", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "QCOM", "INTC", "MRVL",
            "ARM", "SMCI", "SNPS", "CDNS", "MCHP", "ON", "NXPI", "MPWR",
            "SOXX", "SMH", "SOXQ", "XSD", "FTXL", "PSI", "SOXL", "SOXS",
            "QQQ", "QQQM", "QNDX", "TQQQ", "SQQQ", "SPY", "VOO", "IVV", "SPLG", "DIA", "IWM",
            "TSLL", "TSLS", "TSLQ", "NVDL", "NVDU", "NVDQ", "AAPU", "AAPD", "MSFU", "MSFD",
            "GGLL", "GGLS", "AMZU", "AMZD", "SNDU", "SNDQ", "SNSXX"
        ]
        var picked: [PaperTradeStock] = preferredTickers.compactMap { ticker in
            universe.first { $0.normalizedTicker == PaperTradeStock.normalizedTicker(ticker) }
        }
        if picked.count < 8 {
            picked.append(contentsOf: universe.sorted { $0.score > $1.score }.prefix(12))
        }
        cachedPopularPaperStocks = picked.uniquedByTicker().prefixArray(24)
        cachedRecentPaperStocks = recentPaperTickers.compactMap { ticker in
            universe.first { $0.normalizedTicker == PaperTradeStock.normalizedTicker(ticker) }
        }
        cachedFavoritePaperStocks = favoritePaperTickers.compactMap { ticker in
            universe.first { $0.normalizedTicker == PaperTradeStock.normalizedTicker(ticker) }
        }
    }

    @MainActor
    private func runScreening() async {
        guard remoteConfig.isReady else {
            statusText = "서버 설정 필요"
            return
        }
        isRunning = true
        statusText = "한국 주식 AI 스크리닝 실행중..."
        defer { isRunning = false }
        do {
            let payload = try await RemoteMarketAPI.runAIScreening(config: remoteConfig, limit: 30)
            screening = payload
            rebuildPaperCaches()
            if selectedPaperStock == nil {
                if let firstRow = payload.rows.first {
                    selectPaperRow(firstRow)
                }
            }
            statusText = "스크리닝 완료 · \(payload.count)개 후보"
        } catch {
            statusText = "스크리닝 실패 · \(error.localizedDescription)"
        }
    }

    @MainActor
    private func runBacktest() async {
        guard remoteConfig.isReady else {
            statusText = "서버 설정 필요"
            return
        }
        isRunning = true
        statusText = "백테스트 실행중..."
        defer { isRunning = false }
        do {
            let payload = try await RemoteMarketAPI.runAIScreeningBacktest(config: remoteConfig, period: "6mo", maxSymbols: 20)
            backtest = payload
            statusText = "백테스트 완료 · \(payload.summary?.totalTrades ?? 0)회"
        } catch {
            statusText = "백테스트 실패 · \(error.localizedDescription)"
        }
    }

    @MainActor
    private func loadPaperAccount() async {
        guard remoteConfig.isReady else {
            statusText = "서버 설정 필요"
            return
        }
        isRunning = true
        statusText = "모의계좌 조회중..."
        defer { isRunning = false }
        do {
            let payload = try await RemoteMarketAPI.fetchPaperTradingAccount(config: remoteConfig)
            let local = paperAccount ?? PaperTradingLocalStore.load()
            let preferred = PaperTradingLocalStore.preferredAccount(remote: payload.normalizedForDisplay(), local: local?.normalizedForDisplay()).normalizedForDisplay()
            paperAccount = preferred
            paperAccountLoaded = true
            if preferred.trades.count == local?.trades.count && preferred.positions.count == local?.positions.count && PaperTradingLocalStore.shouldProtectLocal(payload, local: local) {
                statusText = "서버 계좌가 비어 있어 로컬 보유 종목 유지"
            } else {
                statusText = "모의계좌 조회 완료"
            }
            PaperTradingLocalStore.save(preferred)
            await refreshPaperQuotes(force: true)
        } catch {
            if let local = (paperAccount ?? PaperTradingLocalStore.load())?.normalizedForDisplay() {
                paperAccount = local
                paperAccountLoaded = true
                statusText = "서버 조회 실패 · 로컬 보유 종목 유지"
                await refreshPaperQuotes(force: true)
            } else {
                paperAccountLoaded = true
                statusText = "모의계좌 실패 · \(error.localizedDescription)"
            }
        }
    }

    @MainActor
    private func depositPaperCash() async {
        guard let amount = parseNumber(depositText), amount > 0 else {
            statusText = "모의 입금액 확인 필요"
            return
        }
        if depositCurrency == .usd {
            depositPaperUSDCash(amount: amount)
            return
        }
        isRunning = true
        statusText = "모의 입금 처리중..."
        defer { isRunning = false }
        do {
            let payload = try await RemoteMarketAPI.depositPaperCash(config: remoteConfig, amount: amount)
            let reconciled = reconcilePaperDepositPayload(remote: payload, amount: amount)
            paperAccount = reconciled.normalizedForDisplay()
            paperAccountLoaded = true
            PaperTradingLocalStore.save(reconciled.normalizedForDisplay())
            statusText = "모의 입금 완료 · 현금 \(money(reconciled.cash))"
            tradeToast = PaperTradeToast(
                style: .success,
                title: "입금 완료",
                message: "모의 현금 \(money(amount)) 입금",
                detail: "현재 현금 \(money(reconciled.cash))",
                showsHoldingsButton: false
            )
        } catch {
            let local = localDepositPaperCash(amount: amount)
            paperAccount = local.normalizedForDisplay()
            paperAccountLoaded = true
            PaperTradingLocalStore.save(local.normalizedForDisplay())
            statusText = "서버 오류 · 로컬 입금 완료 · 현금 \(money(local.cash))"
            #if DEBUG
            print("[PaperTrading] Remote deposit failed. local deposit saved. error=\(error.localizedDescription)")
            #endif
            tradeToast = PaperTradeToast(
                style: .success,
                title: "입금 완료",
                message: "서버 오류지만 로컬 계좌에 저장했습니다.",
                detail: "현재 현금 \(money(local.cash))",
                showsHoldingsButton: false
            )
        }
    }

    @MainActor
    private func depositPaperUSDCash(amount: Double) {
        let local = (paperAccount ?? PaperTradingLocalStore.load())?.normalizedForDisplay() ?? PaperTradingAccountPayload(
            cash: 0,
            totalValue: 0,
            positions: [],
            trades: [],
            updatedAt: nil,
            safetyNotice: nil
        )
        let now = ISO8601DateFormatter().string(from: Date())
        var trades = local.trades
        trades.append(PaperTradingTrade(
            at: now,
            type: "deposit_usd",
            ticker: "USD",
            name: "미화 현금",
            quantity: 0,
            price: 1,
            amount: amount,
            cashAmount: amount
        ))
        let updated = PaperTradingAccountPayload(
            ok: true,
            cash: local.cash,
            totalValue: local.totalValue,
            positions: local.positions,
            trades: trades,
            updatedAt: now,
            safetyNotice: local.safetyNotice
        ).normalizedForDisplay()
        paperUSDCash += amount
        PaperUSDCashStore.save(paperUSDCash)
        paperAccount = updated
        paperAccountLoaded = true
        PaperTradingLocalStore.save(updated)
        statusText = "미화 입금 완료 · USD \(PaperTradeCurrencyFormatter.usdCashText(paperUSDCash))"
        PaperTradingLocalStore.log("USD Deposit", detail: "amount=\(amount) usdCash=\(paperUSDCash)")
        tradeToast = PaperTradeToast(
            style: .success,
            title: "미화 입금 완료",
            message: "$\(amount.formatted(.number.precision(.fractionLength(0...2)))) 입금",
            detail: "USD 현금 \(PaperTradeCurrencyFormatter.usdCashText(paperUSDCash))",
            showsHoldingsButton: false
        )
    }

    private func localDepositPaperCash(amount: Double) -> PaperTradingAccountPayload {
        let local = (paperAccount ?? PaperTradingLocalStore.load())?.normalizedForDisplay() ?? PaperTradingAccountPayload(
            cash: 0,
            totalValue: 0,
            positions: [],
            trades: [],
            updatedAt: nil,
            safetyNotice: nil
        )
        var trades = local.trades
        let now = ISO8601DateFormatter().string(from: Date())
        trades.append(PaperTradingTrade(
            at: now,
            type: "deposit",
            ticker: "",
            name: "현금",
            quantity: 0,
            price: 0,
            amount: amount,
            cashAmount: amount
        ))
        let cash = local.cash + amount
        let totalValue = cash + local.positions.reduce(0) { partial, position in
            partial + PaperTradeCurrencyFormatter.krwValue(position.marketValue, ticker: position.ticker)
        }
        PaperTradingLocalStore.log("Local Deposit", detail: "amount=\(amount) cash=\(cash)")
        return PaperTradingAccountPayload(
            ok: true,
            cash: cash,
            totalValue: totalValue,
            positions: local.positions,
            trades: trades,
            updatedAt: now,
            safetyNotice: local.safetyNotice
        )
    }

    private func reconcilePaperDepositPayload(remote: PaperTradingAccountPayload, amount: Double) -> PaperTradingAccountPayload {
        let local = paperAccount ?? PaperTradingLocalStore.load()
        guard let local, local.hasPortfolioData else {
            return remote
        }
        if remote.positions.count >= local.positions.count && remote.trades.count >= local.trades.count {
            return remote
        }
        PaperTradingLocalStore.log("Sync Conflict", detail: "deposit response would drop local portfolio, preserving local records")
        var trades = local.trades
        let now = ISO8601DateFormatter().string(from: Date())
        trades.append(PaperTradingTrade(
            at: now,
            type: "deposit",
            ticker: "",
            name: "현금",
            quantity: 0,
            price: 0,
            amount: amount
        ))
        let cash = local.cash + amount
        let totalValue = cash + local.positions.reduce(0) { partial, position in
            partial + PaperTradeCurrencyFormatter.krwValue(position.marketValue, ticker: position.ticker)
        }
        return PaperTradingAccountPayload(
            ok: true,
            cash: cash,
            totalValue: totalValue,
            positions: local.positions,
            trades: trades,
            updatedAt: now,
            safetyNotice: remote.safetyNotice ?? local.safetyNotice
        )
    }

    @MainActor
    private func simulatePaperTrade(side: String) async {
        let ticker = paperTickerText.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard !ticker.isEmpty, let quantity = parseNumber(paperQuantityText), var price = parseNumber(paperPriceText), quantity > 0, price > 0 else {
            statusText = "모의거래 티커/수량/가격 확인 필요"
            return
        }
        isRunning = true
        statusText = side == "buy" ? "실시간 매수가 확인중..." : "실시간 매도가 확인중..."
        defer { isRunning = false }
            if let livePrice = await latestPaperTradePrice(for: ticker, force: true), livePrice > 0 {
                price = livePrice
                paperPriceText = String(format: "%.2f", livePrice)
            }
            let baseAccount = (paperAccount ?? PaperTradingLocalStore.load())?.normalizedForDisplay() ?? PaperTradingAccountPayload(
                cash: 0,
                totalValue: 0,
                positions: [],
                trades: [],
                updatedAt: nil,
                safetyNotice: nil
            )
            guard let cashImpact = await paperTradeCashImpact(ticker: ticker, quantity: quantity, price: price) else {
                statusText = "USD/KRW 환율 확인 실패 · 미국주식 거래 보류"
                tradeToast = PaperTradeToast(
                    style: .failure,
                    title: side == "buy" ? "구매 실패" : "매도 실패",
                    message: "미국주식 환율을 가져오지 못했습니다.",
                    detail: "환율 확인 후 다시 시도하세요.",
                    showsHoldingsButton: false
                )
                return
            }
            let isUSTrade = PaperTradeCurrencyFormatter.isUSTicker(ticker)
            let availableCash = isUSTrade ? paperUSDCash : baseAccount.cash
            let neededText = isUSTrade ? PaperTradeCurrencyFormatter.usdCashText(cashImpact) : money(cashImpact)
            let availableText = isUSTrade ? PaperTradeCurrencyFormatter.usdCashText(availableCash) : money(availableCash)
            if side == "buy", availableCash + 0.0001 < cashImpact {
                statusText = "\(isUSTrade ? "USD" : "모의") 현금 부족 · 필요 \(neededText)"
                tradeToast = PaperTradeToast(
                    style: .failure,
                    title: "구매 실패",
                    message: "잔액 부족",
                    detail: "필요 \(neededText) · 보유 \(availableText)",
                    showsHoldingsButton: false
                )
                return
            }
            if side == "sell", !hasPaperPosition(account: baseAccount, ticker: ticker, quantity: quantity) {
                statusText = "모의 보유 수량 부족"
                tradeToast = PaperTradeToast(
                    style: .failure,
                    title: "매도 실패",
                    message: "보유 수량이 부족합니다.",
                    detail: "보유 종목 화면에서 수량을 확인하세요.",
                    showsHoldingsButton: false
                )
                return
            }
            statusText = side == "buy" ? "모의 매수 처리중..." : "모의 매도 처리중..."
            var payload = baseAccount
            var remoteSyncMessage = "서버 동기화 완료"
            if isUSTrade {
                remoteSyncMessage = "USD 거래 · 로컬 저장 완료"
            } else if remoteConfig.isReady {
                do {
                    payload = try await RemoteMarketAPI.simulatePaperTrade(
                        config: remoteConfig,
                        ticker: ticker,
                        quantity: quantity,
                        price: price,
                        side: side,
                        cashAmount: cashImpact
                    )
                } catch {
                    remoteSyncMessage = "서버 동기화 실패 · 로컬 저장 완료"
                    #if DEBUG
                    print("[PaperTrading] Remote simulate failed. local-first trade continues. error=\(error.localizedDescription)")
                    #endif
                }
            } else {
                remoteSyncMessage = "서버 미설정 · 로컬 저장 완료"
            }
            let reconciled = reconcilePaperTradePayload(
                base: baseAccount,
                remote: payload,
                ticker: ticker,
                quantity: quantity,
                price: price,
                side: side,
                cashImpact: cashImpact
            )
            let normalized = reconciled.normalizedForDisplay()
            paperAccount = normalized
            paperAccountLoaded = true
            if isUSTrade {
                paperUSDCash = max(0, paperUSDCash + (side == "buy" ? -cashImpact : cashImpact))
                PaperUSDCashStore.save(paperUSDCash)
            }
            PaperTradingLocalStore.save(normalized)
            await refreshPaperQuotes(force: true)
            statusText = "\(side == "buy" ? "모의 매수 완료" : "모의 매도 완료") · \(remoteSyncMessage)"
            let stockName = selectedPaperStock?.name ?? StockDisplayName.localizedName(ticker, ticker: ticker, market: "미장")
            let total = quantity * price
            let amountDetail: String
            if let stock = selectedPaperStock {
                amountDetail = tradeAmountText(stock: stock, quantity: quantity)
            } else if PaperTradeCurrencyFormatter.isUSTicker(ticker) {
                amountDetail = PaperTradeCurrencyFormatter.amount(total, ticker: ticker)
            } else {
                amountDetail = money(total)
            }
            let priceText = PaperTradeCurrencyFormatter.price(price, ticker: ticker)
            tradeToast = PaperTradeToast(
                style: side == "buy" ? .buySuccess : .sellSuccess,
                title: side == "buy" ? "구매 완료" : "매도 완료",
                message: "\(stockName) · \(formatQuantity(quantity))주 · \(priceText)",
                detail: "총 \(amountDetail) · \(remoteSyncMessage)",
                showsHoldingsButton: true
            )
    }

    @MainActor
    private func paperTradeCashImpact(ticker: String, quantity: Double, price: Double) async -> Double? {
        let tradeAmount = quantity * price
        guard PaperTradeCurrencyFormatter.isUSTicker(ticker) else {
            return tradeAmount
        }
        return tradeAmount
    }

    private func hasPaperPosition(account: PaperTradingAccountPayload, ticker: String, quantity: Double) -> Bool {
        let key = PaperMarketClassifier.identityKey(for: ticker)
        let held = account.normalizedForDisplay().positions.first { PaperMarketClassifier.identityKey(for: $0.ticker) == key }?.quantity ?? 0
        return held + 0.0001 >= quantity
    }

    private func reconcilePaperTradePayload(
        base: PaperTradingAccountPayload,
        remote: PaperTradingAccountPayload,
        ticker: String,
        quantity: Double,
        price: Double,
        side: String,
        cashImpact: Double
    ) -> PaperTradingAccountPayload {
        let identityKey = PaperMarketClassifier.identityKey(for: ticker)
        let now = ISO8601DateFormatter().string(from: Date())
        let stockName = selectedPaperStock?.name
            ?? base.positions.first { PaperMarketClassifier.identityKey(for: $0.ticker) == identityKey }?.name
            ?? remote.positions.first { PaperMarketClassifier.identityKey(for: $0.ticker) == identityKey }?.name
            ?? StockDisplayName.localizedName(ticker, ticker: ticker, market: PaperMarketClassifier.marketText(for: ticker))

        let isUSTrade = PaperTradeCurrencyFormatter.isUSTicker(ticker)
        var nextCash = base.cash
        var nextPositions = base.positions.filter { PaperMarketClassifier.identityKey(for: $0.ticker) != identityKey }
        let current = base.positions.first { PaperMarketClassifier.identityKey(for: $0.ticker) == identityKey }
        let heldQuantity = current?.quantity ?? 0
        let heldAvgPrice = current?.avgPrice ?? 0

        if side == "buy" {
            if !isUSTrade {
                nextCash = max(0, base.cash - cashImpact)
            }
            let newQuantity = heldQuantity + quantity
            let newAvgPrice = newQuantity > 0
                ? ((heldQuantity * heldAvgPrice) + (quantity * price)) / newQuantity
                : price
            nextPositions.append(PaperTradingPosition(
                ticker: ticker,
                name: stockName,
                quantity: newQuantity,
                avgPrice: newAvgPrice,
                currentPrice: price,
                marketValue: newQuantity * price,
                profitLoss: (price - newAvgPrice) * newQuantity,
                profitLossPct: newAvgPrice > 0 ? (price / newAvgPrice - 1) * 100 : 0
            ))
        } else {
            if !isUSTrade {
                nextCash = base.cash + cashImpact
            }
            let remainingQuantity = max(0, heldQuantity - quantity)
            if remainingQuantity > 0 {
                nextPositions.append(PaperTradingPosition(
                    ticker: current?.ticker ?? ticker,
                    name: current?.name ?? stockName,
                    quantity: remainingQuantity,
                    avgPrice: heldAvgPrice,
                    currentPrice: price,
                    marketValue: remainingQuantity * price,
                    profitLoss: (price - heldAvgPrice) * remainingQuantity,
                    profitLossPct: heldAvgPrice > 0 ? (price / heldAvgPrice - 1) * 100 : 0
                ))
            }
        }

        nextPositions.sort { $0.ticker < $1.ticker }
        var nextTrades = base.trades
        let costBasisImpact = isUSTrade ? quantity * heldAvgPrice : PaperTradeCurrencyFormatter.krwValue(quantity * heldAvgPrice, ticker: ticker)
        let realizedProfit = side == "sell" ? cashImpact - costBasisImpact : nil
        let realizedProfitPct = side == "sell" && costBasisImpact > 0 ? (cashImpact / costBasisImpact - 1) * 100 : nil
        nextTrades.append(PaperTradingTrade(
            at: now,
            type: "paper_\(side)",
            ticker: ticker,
            name: stockName,
            quantity: quantity,
            price: price,
            amount: quantity * price,
            cashAmount: cashImpact,
            fee: 0,
            realizedProfit: realizedProfit,
            realizedProfitPct: realizedProfitPct
        ))
        let totalValue = nextCash + nextPositions.reduce(0) { partial, position in
            partial + PaperTradeCurrencyFormatter.krwValue(position.marketValue, ticker: position.ticker)
        }
        return PaperTradingAccountPayload(
            ok: true,
            cash: nextCash,
            totalValue: totalValue,
            positions: nextPositions,
            trades: nextTrades,
            updatedAt: now,
            safetyNotice: remote.safetyNotice ?? base.safetyNotice
        )
    }

    @MainActor
    private func buySelectedByQuantity() async {
        guard let stock = selectedPaperStock else {
            statusText = "먼저 종목을 검색하거나 추천/인기 종목에서 선택하세요"
            return
        }
        guard let quantity = parseNumber(simpleQuantityText), quantity > 0 else {
            statusText = "수량 확인 필요"
            return
        }
        let price = await latestPaperTradePrice(for: stock.ticker, force: true) ?? stock.price
        guard price > 0 else {
            statusText = "\(stock.name) 현재가 확인 필요"
            tradeToast = PaperTradeToast(
                style: .failure,
                title: "시세 확인 실패",
                message: "\(stock.name)의 최신 가격을 가져오지 못했습니다.",
                detail: "잠시 후 다시 시도하세요.",
                showsHoldingsButton: false
            )
            return
        }
        paperTickerText = stock.ticker
        paperQuantityText = formatQuantity(quantity)
        paperPriceText = String(format: "%.2f", price)
        await simulatePaperTrade(side: "buy")
    }

    @MainActor
    private func setBuyQuantity(percent: Double) async {
        guard let stock = selectedPaperStock else {
            statusText = "먼저 종목을 선택하세요"
            return
        }
        let cash = PaperTradeCurrencyFormatter.isUSTicker(stock.ticker) ? paperUSDCash : ((paperAccount ?? PaperTradingLocalStore.load())?.cash ?? 0)
        let budget = max(0, cash * max(0, min(1, percent)))
        guard budget > 0 else {
            statusText = "매수 가능 현금 없음"
            return
        }
        let livePrice = await latestPaperTradePrice(for: stock.ticker, force: true) ?? stock.price
        guard livePrice > 0 else {
            statusText = "\(stock.name) 최신 시세 확인 실패"
            return
        }
        let quantity = normalizedBuyQuantity(budget / livePrice, ticker: stock.ticker)
        guard quantity > 0 else {
            statusText = "\(Int(percent * 100))% 매수 가능 수량 없음"
            return
        }
        simpleQuantityText = formatQuantity(quantity)
        paperTickerText = stock.ticker
        paperQuantityText = formatQuantity(quantity)
        paperPriceText = String(format: "%.2f", livePrice)
        statusText = "\(stock.name) \(Int(percent * 100))% 매수 수량 계산 · \(formatQuantity(quantity))주"
    }

    @MainActor
    private func buyAllSelected() async {
        guard let stock = selectedPaperStock else {
            statusText = "먼저 종목을 검색하거나 추천/인기 종목에서 선택하세요"
            tradeToast = PaperTradeToast(
                style: .failure,
                title: "종목 선택 필요",
                message: "전량 매수할 종목을 먼저 선택하세요.",
                detail: "",
                showsHoldingsButton: false
            )
            return
        }

        let cash = PaperTradeCurrencyFormatter.isUSTicker(stock.ticker) ? paperUSDCash : ((paperAccount ?? PaperTradingLocalStore.load())?.cash ?? 0)
        guard cash > 0 else {
            statusText = "전량 매수 실패 · 보유 현금 없음"
            tradeToast = PaperTradeToast(
                style: .failure,
                title: "현금 부족",
                message: "전량 매수에 사용할 현금이 없습니다.",
                detail: "",
                showsHoldingsButton: false
            )
            return
        }

        let livePrice = await latestPaperTradePrice(for: stock.ticker, force: true) ?? stock.price
        guard livePrice > 0 else {
            statusText = "\(stock.name) 최신 시세 확인 실패"
            tradeToast = PaperTradeToast(
                style: .failure,
                title: "시세 확인 실패",
                message: "\(stock.name)의 최신 가격을 가져오지 못했습니다.",
                detail: "잠시 후 다시 시도하세요.",
                showsHoldingsButton: false
            )
            return
        }

        guard let quantity = await maxBuyQuantity(stock: stock, price: livePrice, cash: cash),
              quantity > 0 else {
            statusText = "전량 매수 실패 · 현금 부족 또는 환율 확인 필요"
            tradeToast = PaperTradeToast(
                style: .failure,
                title: "전량 매수 불가",
                message: "\(stock.name)을 살 수 있는 현금이 부족합니다.",
                detail: "최신가 기준으로 다시 계산했습니다.",
                showsHoldingsButton: false
            )
            return
        }

        simpleQuantityText = formatQuantity(quantity)
        paperTickerText = stock.ticker
        paperQuantityText = formatQuantity(quantity)
        paperPriceText = String(format: "%.2f", livePrice)
        statusText = "\(stock.name) 전량 매수 계산 완료 · \(formatQuantity(quantity))주"
        await simulatePaperTrade(side: "buy")
    }

    @MainActor
    private func maxBuyQuantity(stock: PaperTradeStock, price: Double, cash: Double) async -> Double? {
        guard price > 0, cash > 0 else { return nil }

        if PaperTradeCurrencyFormatter.isUSTicker(stock.ticker) {
            return normalizedBuyQuantity(cash / price, ticker: stock.ticker)
        }

        return normalizedBuyQuantity(cash / price, ticker: stock.ticker)
    }

    private func normalizedBuyQuantity(_ quantity: Double, ticker: String) -> Double {
        guard quantity.isFinite, quantity > 0 else { return 0 }
        if isWholeSharePaperTicker(ticker) {
            return floor(quantity)
        }
        return floor(quantity * 10_000) / 10_000
    }

    private func isWholeSharePaperTicker(_ ticker: String) -> Bool {
        let normalized = PaperTradeStock.normalizedTicker(ticker)
        return ticker.hasSuffix(".KS")
            || ticker.hasSuffix(".KQ")
            || normalized.range(of: #"^[0-9]{6}$"#, options: .regularExpression) != nil
    }

    @MainActor
    private func refreshPaperQuotes(force: Bool) async {
        guard let account = paperAccount, !account.positions.isEmpty else {
            return
        }
        let hasUSPosition = account.positions.contains { PaperTradeCurrencyFormatter.isUSTicker($0.ticker) }
        let hasKoreanPosition = account.positions.contains { PaperMarketClassifier.marketText(for: $0.ticker) == "국장" }
        let minimumRefreshGap: TimeInterval = hasUSPosition ? 5 : (hasKoreanPosition ? 10 : 20)
        if !force,
           let updatedAt = paperLastQuoteUpdatedAt,
           Date().timeIntervalSince(updatedAt) < minimumRefreshGap {
            return
        }

        let tickers = account.positions.map(\.ticker)
        let needsUSDKRWRefresh: Bool = {
            if force {
                return true
            }
            guard let updatedAt = CurrencyExchangeRateStore.usdKrwUpdatedAt else { return true }
            return Date().timeIntervalSince(updatedAt) > (hasUSPosition ? 60 : 300)
        }()

        async let quotesTask = LiveQuoteService.fetchQuotes(for: tickers)
        async let usdKrwTask: Double? = needsUSDKRWRefresh ? LiveQuoteService.fetchUSDKRWRate() : CurrencyExchangeRateStore.usdKrwRate
        var quotes = await quotesTask
        if needsUSDKRWRefresh, let rate = await usdKrwTask, rate > 0 {
            CurrencyExchangeRateStore.saveUSDKRW(rate)
            #if DEBUG
            print("[PaperTrading] Exchange Rate Update USD/KRW=\(rate)")
            #endif
        } else {
            _ = await usdKrwTask
        }

        if quotes.isEmpty {
            paperLiveConnectionStatus = "실시간 연결 재시도 중"
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            quotes = await LiveQuoteService.fetchQuotes(for: tickers)
        }

        guard !quotes.isEmpty else {
            let fallbackText = paperLastQuoteUpdatedAt.map { "마지막 업데이트 \(AppDateTime.localString(from: $0, format: "yyyy-MM-dd HH:mm:ss"))" } ?? "저장 시세"
            paperLiveConnectionStatus = "실시간 연결 끊김 · 캐시 표시 · \(fallbackText)"
            statusText = "최신 시세를 가져오지 못했습니다. \(fallbackText)를 표시하고 자동 재연결합니다."
            return
        }

        quotes = await revalidatedPaperQuotes(quotes, positions: account.positions)

        var next = paperQuoteOverrides
        var changedCount = 0
        for quote in quotes {
            let keys = paperQuoteKeys(for: quote.ticker)
            let oldQuote = keys.compactMap { next[$0] }.first
            let isChanged: Bool
            if let old = oldQuote {
                isChanged = abs(old.price - quote.price) >= 0.0001
                    || abs((old.changePercent ?? 0) - (quote.changePercent ?? 0)) >= 0.0001
            } else {
                isChanged = true
            }
            for key in keys {
                next[key] = quote
            }
            if isChanged {
                changedCount += 1
            }
        }

        paperQuoteOverrides = next
        let refreshedAccount = account.refreshedWithLiveQuotes(next)
        paperAccount = refreshedAccount
        PaperTradingLocalStore.save(refreshedAccount)
        paperLastQuoteUpdatedAt = Date()
        let sourceSummary = quotes.map(\.source).uniqued().prefix(3).joined(separator: "/")
        let modeText = quotes.contains { $0.source.contains("종가") } ? "종가 기준" : "실시간"
        paperLiveConnectionStatus = "\(modeText) 연결 정상 · \(sourceSummary.isEmpty ? "Last Price" : sourceSummary)"
        let marketSummary = account.positions
            .map { MarketSessionClock.forTicker($0.ticker).label }
            .uniqued()
            .prefix(3)
            .joined(separator: "/")
        #if DEBUG
        print("[PaperTrading] Price Update count=\(quotes.count) changed=\(changedCount) source=\(sourceSummary) market=\(marketSummary)")
        print("[PaperTrading] Portfolio Recalculated positions=\(account.positions.count)")
        #endif
        statusText = changedCount > 0
            ? "보유 종목 시세 갱신 완료 · \(changedCount)개 변경 · 시장별 개별 반영"
            : "보유 종목 시세 재계산 완료 · 변경 없음 · 시장별 개별 반영"
    }

    private func revalidatedPaperQuotes(_ quotes: [LiveQuote], positions: [PaperTradingPosition]) async -> [LiveQuote] {
        let quoteMap = quotes.reduce(into: [String: LiveQuote]()) { result, quote in
            result[PaperTradeStock.normalizedTicker(quote.ticker)] = quote
        }
        let suspiciousTickers = positions.compactMap { position -> String? in
            guard PaperMarketClassifier.marketText(for: position.ticker) == "국장",
                  let quote = quoteMap[PaperTradeStock.normalizedTicker(position.ticker)],
                  isSuspiciousPaperQuote(quote, for: position) else {
                return nil
            }
            return position.ticker
        }

        guard !suspiciousTickers.isEmpty else {
            return quotes
        }

        #if DEBUG
        print("[PaperTrading] Suspicious Korean quote detected tickers=\(suspiciousTickers.joined(separator: ",")) · forcing re-fetch")
        #endif
        let retryQuotes = await LiveQuoteService.fetchQuotes(for: suspiciousTickers)
        guard !retryQuotes.isEmpty else {
            return quotes
        }
        var merged = quotes.reduce(into: [String: LiveQuote]()) { result, quote in
            result[PaperTradeStock.normalizedTicker(quote.ticker)] = quote
        }
        for quote in retryQuotes where quote.price > 0 {
            merged[PaperTradeStock.normalizedTicker(quote.ticker)] = quote
        }
        return Array(merged.values)
    }

    private func isSuspiciousPaperQuote(_ quote: LiveQuote, for position: PaperTradingPosition) -> Bool {
        guard quote.price > 0 else {
            return true
        }
        if position.currentPrice > 0 {
            let gap = abs(quote.price / position.currentPrice - 1) * 100
            if gap >= 18 {
                return true
            }
        }
        if let changePercent = quote.changePercent, abs(changePercent) >= 30 {
            return true
        }
        if quote.source.contains("시간외"), let changePercent = quote.changePercent, abs(changePercent) >= 5 {
            return true
        }
        return false
    }

    private func paperQuoteKeys(for ticker: String) -> [String] {
        [
            PaperTradeStock.normalizedTicker(ticker),
            PaperMarketClassifier.identityKey(for: ticker),
            ticker.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        ].uniqued()
    }

    @MainActor
    private func sellPosition(_ position: PaperTradingPosition) async {
        await sellPosition(position, quantity: position.quantity)
    }

    @MainActor
    private func sellPosition(_ position: PaperTradingPosition, fraction: Double) async {
        await sellPosition(position, quantity: max(0, position.quantity * fraction))
    }

    @MainActor
    private func sellPosition(_ position: PaperTradingPosition, quantity: Double) async {
        guard quantity > 0 else {
            statusText = "매도 수량 확인 필요"
            return
        }
        paperTickerText = position.ticker
        paperQuantityText = formatQuantity(min(quantity, position.quantity))
        let sellPrice = await latestPaperTradePrice(for: position.ticker) ?? (position.currentPrice > 0 ? position.currentPrice : position.avgPrice)
        paperPriceText = String(format: "%.2f", max(sellPrice, 0))
        await simulatePaperTrade(side: "sell")
    }

    @MainActor
    private func sellSelectedByQuantity() async {
        guard let stock = selectedPaperStock else {
            statusText = "먼저 매도할 종목을 선택하세요"
            return
        }
        guard let position = selectedPaperPosition else {
            statusText = "\(stock.name) 보유 수량 없음"
            return
        }
        guard let quantity = parseNumber(simpleQuantityText), quantity > 0 else {
            statusText = "매도 수량 확인 필요"
            return
        }
        await sellPosition(position, quantity: min(quantity, position.quantity))
    }

    @MainActor
    private func latestPaperTradePrice(for ticker: String, force: Bool = false) async -> Double? {
        let keys = paperQuoteKeys(for: ticker)
        if !force,
           let cached = keys.compactMap({ paperQuoteOverrides[$0] }).first(where: { $0.price > 0 }),
           cached.price > 0,
           Date().timeIntervalSince(cached.updatedAt) < 15 {
            #if DEBUG
            print("[PaperTrading] Cache Hit ticker=\(ticker) age=\(Int(Date().timeIntervalSince(cached.updatedAt)))s")
            #endif
            return cached.price
        }

        #if DEBUG
        print("[PaperTrading] Cache Refresh ticker=\(ticker)")
        #endif
        let quotes = await LiveQuoteService.fetchQuotes(for: [ticker])
        let normalized = PaperTradeStock.normalizedTicker(ticker)
        guard let quote = quotes.first(where: { PaperTradeStock.normalizedTicker($0.ticker) == normalized }),
              quote.price > 0 else {
            return nil
        }

        var next = paperQuoteOverrides
        for key in paperQuoteKeys(for: quote.ticker) {
            next[key] = quote
        }
        for key in keys {
            next[key] = quote
        }
        paperQuoteOverrides = next
        paperLastQuoteUpdatedAt = Date()
        #if DEBUG
        print("[PaperTrading] Price Source ticker=\(ticker) source=\(quote.source) price=\(quote.price)")
        #endif
        return quote.price
    }

    @MainActor
    private func selectPaperRow(_ row: AIScreeningRow) {
        selectPaperStock(PaperTradeStock(row: row))
    }

    @MainActor
    private func selectPaperStock(_ stock: PaperTradeStock) {
        if let market = PaperTradingMarket(stock: stock) {
            selectedPaperMarket = market
        }
        selectedPaperStock = stock
        fillAdvancedFields(from: stock)
        recentPaperTickers = PaperTradeRecentStore.record(stock.normalizedTicker)
        statusText = "\(stock.name) 선택 · \(stock.marketText) 매수/매도 화면으로 이동"
    }

    @MainActor
    private func togglePaperFavorite(_ stock: PaperTradeStock) {
        favoritePaperTickers = PaperTradeFavoriteStore.toggle(stock.normalizedTicker)
    }

    @MainActor
    private func fillAdvancedFields(from stock: PaperTradeStock) {
        paperTickerText = stock.ticker
        paperPriceText = String(format: "%.2f", stock.price)
        paperQuantityText = simpleQuantityText
    }

    private func percent(_ value: Double?) -> String {
        guard let value else { return "-" }
        return "\(String(format: "%.1f", value))%"
    }

    private func signedPercent(_ value: Double?) -> String {
        guard let value else { return "-" }
        return "\(value >= 0 ? "+" : "")\(String(format: "%.1f", value))%"
    }

    private func number(_ value: Double?) -> String {
        guard let value else { return "-" }
        return String(format: "%.2f", value)
    }

    private func money(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0))) + "원"
    }

    private func tradeAmountText(stock: PaperTradeStock, quantity: Double) -> String {
        let total = stock.price * quantity
        if stock.marketText == "미장" {
            let usd = total.formatted(.number.precision(.fractionLength(2))) + " USD"
            if let krwText = CurrencyExchangeRateStore.krwText(forUSD: total) {
                return "\(usd) / 약 \(krwText)"
            }
            return usd
        }
        if stock.marketText == "캐나다" {
            return total.formatted(.number.precision(.fractionLength(2))) + " CAD"
        }
        return money(total)
    }

    private func formatQuantity(_ value: Double) -> String {
        value.rounded() == value ? "\(Int(value))" : String(format: "%.2f", value)
    }

    private func parseNumber(_ text: String) -> Double? {
        Double(text.replacingOccurrences(of: ",", with: "").trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private func commaFormattedInteger(_ text: String) -> String {
        let digits = text.filter(\.isNumber)
        guard let value = Int(digits), !digits.isEmpty else { return "" }
        return value.formatted(.number.grouping(.automatic))
    }

    private func numericQuantity(_ text: String) -> String {
        var hasDot = false
        return text.filter { character in
            if character.isNumber { return true }
            if character == ".", !hasDot {
                hasDot = true
                return true
            }
            return false
        }
    }
}

private struct ScreeningTextField: View {
    let title: String
    @Binding var text: String
    let keyboard: UIKeyboardType

    var body: some View {
        TextField(title, text: $text)
            .keyboardType(keyboard)
            .textInputAutocapitalization(.characters)
            .autocorrectionDisabled()
            .submitLabel(.done)
            .onSubmit { dismissKeyboard() }
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10)
            .frame(height: 34)
            .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
            .lineLimit(1)
            .minimumScaleFactor(0.75)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { dismissKeyboard() }
                }
            }
    }
}

private func dismissKeyboard() {
    UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
}

private enum PaperTradingMode: String, CaseIterable, Identifiable {
    case buy
    case holdings
    case history

    var id: String { rawValue }
    var title: String {
        switch self {
        case .buy: return "구매"
        case .holdings: return "보유"
        case .history: return "내역"
        }
    }
}

private enum PaperTradingMarket: String, CaseIterable, Identifiable {
    case korea
    case us

    var id: String { rawValue }

    var tabTitle: String {
        switch self {
        case .korea: return "🇰🇷 국장"
        case .us: return "🇺🇸 미장"
        }
    }

    var displayTitle: String {
        switch self {
        case .korea: return "한국 주식"
        case .us: return "미국 주식"
        }
    }

    var stockListTitle: String {
        switch self {
        case .korea: return "한국 주식"
        case .us: return "미국 주식"
        }
    }

    var historyTitle: String {
        switch self {
        case .korea: return "국장 거래내역"
        case .us: return "미장 거래내역"
        }
    }

    var holdingsTitle: String {
        switch self {
        case .korea: return "국장 보유 종목"
        case .us: return "미장 보유 종목"
        }
    }

    var searchPlaceholder: String {
        switch self {
        case .korea: return "삼성전자, SK하이닉스, 005930"
        case .us: return "NVIDIA, Apple, Tesla, NVDA"
        }
    }

    var iconName: String {
        switch self {
        case .korea: return "building.columns.fill"
        case .us: return "flag.fill"
        }
    }

    var marketText: String {
        switch self {
        case .korea: return "국장"
        case .us: return "미장"
        }
    }

    init?(stock: PaperTradeStock) {
        self.init(marketText: stock.marketText, ticker: stock.ticker)
    }

    init?(marketText: String = "", ticker: String) {
        let resolved = PaperMarketClassifier.marketText(for: ticker, fallback: marketText)
        if resolved == "국장" {
            self = .korea
        } else if resolved == "미장" {
            self = .us
        } else {
            return nil
        }
    }

    func matches(_ stock: PaperTradeStock) -> Bool {
        matches(marketText: stock.marketText, ticker: stock.ticker)
    }

    func matches(_ position: PaperTradingPosition) -> Bool {
        matches(marketText: "", ticker: position.ticker)
    }

    func matches(_ trade: PaperTradingTrade) -> Bool {
        guard !trade.isDeposit else {
            return false
        }
        return matches(marketText: "", ticker: trade.ticker)
    }

    func matches(marketText: String = "", ticker: String) -> Bool {
        PaperMarketClassifier.marketText(for: ticker, fallback: marketText) == self.marketText
    }
}

private enum PaperDepositCurrency: String, CaseIterable, Identifiable {
    case krw
    case usd

    var id: String { rawValue }

    var title: String {
        switch self {
        case .krw: return "원화"
        case .usd: return "미화"
        }
    }

    var inputTitle: String {
        switch self {
        case .krw: return "원화 입금액"
        case .usd: return "달러 입금액"
        }
    }

    var buttonTitle: String {
        switch self {
        case .krw: return "원화 입금"
        case .usd: return "미화 입금"
        }
    }

    var helperText: String {
        switch self {
        case .krw:
            return "한국 주식은 원화 현금에서 매수합니다."
        case .usd:
            return "미국 주식과 미국 ETF는 입력한 달러 금액 그대로 USD 현금에 입금합니다."
        }
    }
}

private enum PaperAutoRefreshInterval: String, CaseIterable, Identifiable {
    case off
    case seconds5
    case seconds10
    case seconds30
    case minute1
    case minutes5

    var id: String { rawValue }

    var title: String {
        switch self {
        case .off:
            return "끔"
        case .seconds5:
            return "5초"
        case .seconds10:
            return "10초"
        case .seconds30:
            return "30초"
        case .minute1:
            return "1분"
        case .minutes5:
            return "5분"
        }
    }

    var seconds: TimeInterval? {
        switch self {
        case .off:
            return nil
        case .seconds5:
            return 5
        case .seconds10:
            return 10
        case .seconds30:
            return 30
        case .minute1:
            return 60
        case .minutes5:
            return 300
        }
    }

    func shouldRefresh(since date: Date?) -> Bool {
        guard let seconds else {
            return false
        }
        guard let date else {
            return true
        }
        return Date().timeIntervalSince(date) >= seconds
    }
}

private enum PaperAutoRefreshIntervalStore {
    private static let key = "paperAutoRefreshInterval.v1"

    static func load() -> PaperAutoRefreshInterval {
        guard let raw = UserDefaults.standard.string(forKey: key),
              let value = PaperAutoRefreshInterval(rawValue: raw) else {
            return .seconds10
        }
        return value
    }

    static func save(_ interval: PaperAutoRefreshInterval) {
        UserDefaults.standard.set(interval.rawValue, forKey: key)
    }
}

private enum PaperUSDCashStore {
    private static let key = "paperTradingUSDCash.v1"

    static func load() -> Double {
        UserDefaults.standard.double(forKey: key)
    }

    static func save(_ value: Double) {
        UserDefaults.standard.set(max(0, value), forKey: key)
    }

    static func reset() {
        UserDefaults.standard.removeObject(forKey: key)
    }
}

private struct USMarketClock {
    enum Session {
        case overnight
        case premarket
        case regular
        case afterhours
        case closed
    }

    let session: Session
    let label: String

    var isTradingActive: Bool {
        session == .overnight || session == .premarket || session == .regular || session == .afterhours
    }

    var tint: Color {
        switch session {
        case .overnight:
            return .indigo
        case .premarket:
            return .blue
        case .regular:
            return .green
        case .afterhours:
            return .purple
        case .closed:
            return .gray
        }
    }

    static var current: USMarketClock {
        current(now: Date())
    }

    static func current(now: Date) -> USMarketClock {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/New_York") ?? .current
        let weekday = calendar.component(.weekday, from: now)
        let minutes = calendar.component(.hour, from: now) * 60 + calendar.component(.minute, from: now)

        switch weekday {
        case 1:
            return minutes >= 20 * 60
                ? USMarketClock(session: .overnight, label: "🌙 Overnight")
                : USMarketClock(session: .closed, label: "⚫ Market Closed")
        case 2...5:
            switch minutes {
            case 0..<(4 * 60):
                return USMarketClock(session: .overnight, label: "🌙 Overnight")
            case (4 * 60)..<(9 * 60 + 30):
                return USMarketClock(session: .premarket, label: "🟢 Pre-Market")
            case (9 * 60 + 30)..<(16 * 60):
                return USMarketClock(session: .regular, label: "🔵 Regular Market")
            case (16 * 60)..<(20 * 60):
                return USMarketClock(session: .afterhours, label: "🟠 After-Hours")
            default:
                return USMarketClock(session: .overnight, label: "🌙 Overnight")
            }
        case 6:
            switch minutes {
            case 0..<(4 * 60):
                return USMarketClock(session: .overnight, label: "🌙 Overnight")
            case (4 * 60)..<(9 * 60 + 30):
                return USMarketClock(session: .premarket, label: "🟢 Pre-Market")
            case (9 * 60 + 30)..<(16 * 60):
                return USMarketClock(session: .regular, label: "🔵 Regular Market")
            case (16 * 60)..<(20 * 60):
                return USMarketClock(session: .afterhours, label: "🟠 After-Hours")
            default:
                return USMarketClock(session: .closed, label: "⚫ Market Closed")
            }
        default:
            return USMarketClock(session: .closed, label: "⚫ Market Closed")
        }
    }
}

private struct MarketSessionClock {
    enum Market {
        case korea
        case us
        case canada
    }

    let market: Market
    let label: String
    let tint: Color
    let isTradingActive: Bool

    static func forTicker(_ ticker: String) -> MarketSessionClock {
        if PaperTradeCurrencyFormatter.isUSTicker(ticker) {
            let clock = USMarketClock.current
            return MarketSessionClock(market: .us, label: clock.label, tint: clock.tint, isTradingActive: clock.isTradingActive)
        }
        if ticker.uppercased().hasSuffix(".TO") || ticker.uppercased().hasSuffix(".V") {
            return canada
        }
        return korea
    }

    static var korea: MarketSessionClock {
        let now = Date()
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Seoul") ?? .current
        let weekday = calendar.component(.weekday, from: now)
        guard (2...6).contains(weekday) else {
            return MarketSessionClock(market: .korea, label: "한국장 휴장", tint: .gray, isTradingActive: false)
        }
        let minutes = calendar.component(.hour, from: now) * 60 + calendar.component(.minute, from: now)
        switch minutes {
        case 8 * 60 + 30..<9 * 60:
            return MarketSessionClock(market: .korea, label: "한국장 개장 전", tint: .blue, isTradingActive: true)
        case 9 * 60..<15 * 60 + 30:
            return MarketSessionClock(market: .korea, label: "한국 정규장", tint: .green, isTradingActive: true)
        case 15 * 60 + 30..<18 * 60:
            return MarketSessionClock(market: .korea, label: "한국 시간외", tint: .purple, isTradingActive: true)
        default:
            return MarketSessionClock(market: .korea, label: "한국장 마감", tint: .gray, isTradingActive: false)
        }
    }

    static var canada: MarketSessionClock {
        let now = Date()
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/Toronto") ?? .current
        let weekday = calendar.component(.weekday, from: now)
        guard (2...6).contains(weekday) else {
            return MarketSessionClock(market: .canada, label: "캐나다장 휴장", tint: .gray, isTradingActive: false)
        }
        let minutes = calendar.component(.hour, from: now) * 60 + calendar.component(.minute, from: now)
        switch minutes {
        case 9 * 60 + 30..<16 * 60:
            return MarketSessionClock(market: .canada, label: "캐나다 정규장", tint: .green, isTradingActive: true)
        default:
            return MarketSessionClock(market: .canada, label: "캐나다장 마감", tint: .gray, isTradingActive: false)
        }
    }
}

private enum PaperTradeToastStyle {
    case buySuccess
    case sellSuccess
    case success
    case failure

    var tint: Color {
        switch self {
        case .buySuccess, .success: return .green
        case .sellSuccess: return .blue
        case .failure: return .red
        }
    }

    var iconName: String {
        switch self {
        case .buySuccess, .sellSuccess, .success: return "checkmark.circle.fill"
        case .failure: return "exclamationmark.triangle.fill"
        }
    }
}

private struct PaperTradeToast: Identifiable {
    let id = UUID()
    let style: PaperTradeToastStyle
    let title: String
    let message: String
    let detail: String
    let showsHoldingsButton: Bool
}

private struct PaperTradeToastView: View {
    let toast: PaperTradeToast
    let holdingsAction: () -> Void
    let dismissAction: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: toast.style.iconName)
                    .font(.title3)
                    .foregroundStyle(toast.style.tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text(toast.title)
                        .font(.subheadline.bold())
                    Text(toast.message)
                        .font(.caption.weight(.semibold))
                        .fixedSize(horizontal: false, vertical: true)
                    Text(toast.detail)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(action: dismissAction) {
                    Image(systemName: "xmark")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            if toast.showsHoldingsButton {
                Button("보유 종목 보기", action: holdingsAction)
                    .font(.caption.bold())
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(toast.style.tint.opacity(0.45), lineWidth: 1))
        .shadow(color: .black.opacity(0.24), radius: 12, x: 0, y: 8)
    }
}

private struct PaperCashHeader: View {
    let account: PaperTradingAccountPayload?
    let usdCash: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("원화 현금")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                    Text(Self.money(account?.cash ?? 0))
                        .font(.headline.monospacedDigit().bold())
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text("미화 현금")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                    Text(PaperTradeCurrencyFormatter.usdCashText(usdCash))
                        .font(.headline.monospacedDigit().bold())
                        .foregroundStyle(.cyan)
                }
            }
            Divider().opacity(0.25)
            VStack(alignment: .leading, spacing: 2) {
                Text("총 자산")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                Text(Self.money((account?.totalValue ?? 0) + PaperTradeCurrencyFormatter.krwValueForUSD(usdCash)))
                    .font(.headline.monospacedDigit().bold())
                    .foregroundStyle(.mint)
            }
        }
        .padding(10)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
    }

    static func money(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0))) + "원"
    }
}

private struct PaperMarketAssetSummaryCard: View {
    let account: PaperTradingAccountPayload?
    let usdCash: Double
    let liveStocks: [PaperTradeStock]
    let quoteOverrides: [String: LiveQuote]

    private var korea: PaperMarketAssetSummary {
        summary(for: .korea)
    }

    private var us: PaperMarketAssetSummary {
        summary(for: .us)
    }

    private var totalMarketValue: Double {
        korea.marketValue + us.marketValue
    }

    private var totalInvested: Double {
        korea.invested + us.invested
    }

    private var totalProfit: Double {
        korea.profit + us.profit
    }

    private var totalAsset: Double {
        (account?.cash ?? 0) + PaperTradeCurrencyFormatter.krwValueForUSD(usdCash) + totalMarketValue
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Label("시장별 모의투자 자산", systemImage: "chart.pie.fill")
                    .font(.caption.bold())
                Spacer()
                Text("전체 \(Self.money(totalAsset))")
                    .font(.caption.monospacedDigit().bold())
                    .foregroundStyle(.mint)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 118), spacing: 8)], alignment: .leading, spacing: 8) {
                PaperMiniMetric(title: "국장 투자금", value: Self.money(korea.invested))
                PaperMiniMetric(title: "국장 평가금액", value: Self.money(korea.marketValue))
                PaperMiniMetric(title: "국장 손익", value: Self.signedMoney(korea.profit))
                PaperMiniMetric(title: "미장 투자금", value: Self.money(us.invested))
                PaperMiniMetric(title: "미장 평가금액", value: Self.money(us.marketValue))
                PaperMiniMetric(title: "미장 손익", value: Self.signedMoney(us.profit))
                PaperMiniMetric(title: "전체 투자금", value: Self.money(totalInvested))
                PaperMiniMetric(title: "전체 합산 손익", value: Self.signedMoney(totalProfit))
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private func summary(for market: PaperTradingMarket) -> PaperMarketAssetSummary {
        (account?.positions ?? [])
            .filter { market.matches($0) }
            .reduce(PaperMarketAssetSummary.empty) { partial, position in
                let current = currentPrice(for: position)
                let quantity = position.quantity
                let invested = PaperTradeCurrencyFormatter.krwValue(position.avgPrice * quantity, ticker: position.ticker)
                let marketValue = PaperTradeCurrencyFormatter.krwValue(current * quantity, ticker: position.ticker)
                return PaperMarketAssetSummary(
                    invested: partial.invested + invested,
                    marketValue: partial.marketValue + marketValue,
                    profit: partial.profit + (marketValue - invested)
                )
            }
    }

    private func currentPrice(for position: PaperTradingPosition) -> Double {
        let keys = [
            PaperTradeStock.normalizedTicker(position.ticker),
            PaperMarketClassifier.identityKey(for: position.ticker),
            position.ticker.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        ]
        if let override = keys.compactMap({ quoteOverrides[$0] }).first(where: { $0.price > 0 }) {
            return override.price
        }
        if let live = liveStocks.first(where: { PaperMarketClassifier.identityKey(for: $0.ticker, fallback: $0.marketText) == PaperMarketClassifier.identityKey(for: position.ticker) }),
           live.price > 0 {
            return live.price
        }
        return position.currentPrice > 0 ? position.currentPrice : position.avgPrice
    }

    static func money(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0))) + "원"
    }

    static func signedMoney(_ value: Double) -> String {
        "\(value >= 0 ? "+" : "-")\(money(abs(value)))"
    }
}

private struct PaperMarketAssetSummary {
    let invested: Double
    let marketValue: Double
    let profit: Double

    static let empty = PaperMarketAssetSummary(invested: 0, marketValue: 0, profit: 0)
}

private struct PaperHoldingsPanel: View {
    let account: PaperTradingAccountPayload?
    let usdCash: Double
    let market: PaperTradingMarket
    let isLoaded: Bool
    let liveStocks: [PaperTradeStock]
    let quoteOverrides: [String: LiveQuote]
    let lastQuoteUpdatedAt: Date?
    let liveConnectionStatus: String
    let autoRefreshInterval: PaperAutoRefreshInterval
    @Binding var customSellQuantityText: String
    let refreshAction: () -> Void
    let setAutoRefreshInterval: (PaperAutoRefreshInterval) -> Void
    let sellAllAction: (PaperTradingPosition) -> Void
    let sellHalfAction: (PaperTradingPosition, Double) -> Void
    let sellCustomAction: (PaperTradingPosition, Double) -> Void

    private var liveStockMap: [String: PaperTradeStock] {
        liveStocks.reduce(into: [String: PaperTradeStock]()) { result, stock in
            let key = stock.normalizedTicker
            if result[key] == nil || stock.price > 0 {
                result[key] = stock
            }
        }
    }

    private var positionRows: [PaperPositionRow] {
        filteredPositions.map { position in
            PaperPositionRow(position: position, snapshot: liveSnapshot(position))
        }
    }

    private var filteredPositions: [PaperTradingPosition] {
        (account?.positions ?? []).filter { market.matches($0) }
    }

    private var filteredTrades: [PaperTradingTrade] {
        (account?.trades ?? []).filter { market.matches($0) }
    }

    private var totals: PaperHoldingsTotals {
        positionRows.reduce(PaperHoldingsTotals.empty) { partial, row in
            let invested = PaperTradeCurrencyFormatter.krwValue(row.position.avgPrice * row.position.quantity, ticker: row.position.ticker)
            let marketValue = PaperTradeCurrencyFormatter.krwValue(row.snapshot.marketValue, ticker: row.position.ticker)
            let profit = marketValue - invested
            let dailyProfit = PaperTradeCurrencyFormatter.krwValue(row.snapshot.dailyProfitLoss, ticker: row.position.ticker)
            return PaperHoldingsTotals(
                marketValue: partial.marketValue + marketValue,
                invested: partial.invested + invested,
                profit: partial.profit + profit,
                dailyProfit: partial.dailyProfit + dailyProfit
            )
        }
    }

    private var realizedSummary: PaperRealizedSummary {
        PaperRealizedSummary.calculate(from: filteredTrades)
    }

    private var sellEvaluations: [String: PaperSellEvaluation] {
        PaperSellEvaluation.calculateByTradeID(
            from: filteredTrades,
            realizedByTradeID: PaperTradeRealizedResult.calculateByTradeID(from: account?.trades ?? []),
            currentPriceByTicker: currentPriceByTicker
        )
    }

    private var currentPriceByTicker: [String: Double] {
        var prices: [String: Double] = liveStockMap.mapValues(\.price)
        for (ticker, quote) in quoteOverrides {
            prices[PaperTradeStock.normalizedTicker(ticker)] = quote.price
            prices[PaperMarketClassifier.identityKey(for: ticker)] = quote.price
        }
        for row in positionRows {
            prices[PaperTradeStock.normalizedTicker(row.position.ticker)] = row.snapshot.currentPrice
            prices[PaperMarketClassifier.identityKey(for: row.position.ticker)] = row.snapshot.currentPrice
        }
        return prices
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
            Text(market.holdingsTitle)
                        .font(.subheadline.bold())
                    Text(lastUpdateText)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button {
                    dismissKeyboard()
                    refreshAction()
                } label: {
                    Label("새로고침", systemImage: "arrow.clockwise")
                }
                .font(.caption.bold())
                .buttonStyle(.bordered)
            }

            Picker("자동 갱신", selection: Binding(
                get: { autoRefreshInterval },
                set: { setAutoRefreshInterval($0) }
            )) {
                ForEach(PaperAutoRefreshInterval.allCases) { interval in
                    Text(interval.title).tag(interval)
                }
            }
            .pickerStyle(.segmented)

            HStack(spacing: 8) {
                Label(marketSessionSummary, systemImage: "clock.badge.checkmark")
                Text(liveConnectionStatus)
                Text(CurrencyExchangeRateStore.statusText)
            }
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .lineLimit(2)
            .fixedSize(horizontal: false, vertical: true)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 118), spacing: 8)], alignment: .leading, spacing: 8) {
                ScreeningMetricBox(title: "\(market.displayTitle) 총 자산", value: Self.money(marketCashValue + totals.marketValue), tint: .mint)
                ScreeningMetricBox(title: "USD 현금", value: PaperTradeCurrencyFormatter.usdCashText(usdCash), tint: .cyan)
                ScreeningMetricBox(title: "총 평가", value: Self.money(totals.marketValue), tint: .secondary)
                ScreeningMetricBox(title: "보유 평가손익", value: Self.signedMoney(totals.profit), tint: totals.profit >= 0 ? .red : .blue)
                ScreeningMetricBox(title: "일일 손익", value: Self.signedMoney(totals.dailyProfit), tint: totals.dailyProfit >= 0 ? .red : .blue)
                ScreeningMetricBox(title: "누적 실현손익", value: Self.signedMoney(realizedSummary.profit), tint: realizedSummary.profit >= 0 ? .red : .blue)
                ScreeningMetricBox(title: "총 투자성과", value: Self.signedMoney(totals.profit + realizedSummary.profit), tint: totals.profit + realizedSummary.profit >= 0 ? .red : .blue)
                ScreeningMetricBox(title: "평가 수익률", value: Self.signedPercent(totals.profitPct), tint: totals.profit >= 0 ? .red : .blue)
            }

            PaperRealizedProfitCard(summary: realizedSummary, evaluations: Array(sellEvaluations.values))

            if !isLoaded {
                PaperPortfolioLoadingCard()
            } else if filteredPositions.isEmpty {
                Text("아직 \(market.displayTitle) 보유 종목이 없습니다. 구매 탭에서 \(market.displayTitle) 종목을 선택하고 모의매수해보세요.")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            } else {
                ForEach(positionRows) { row in
                    PaperHoldingCard(
                        position: row.position,
                        snapshot: row.snapshot,
                        customSellQuantityText: $customSellQuantityText,
                        sellAllAction: { sellAllAction(row.position) },
                        sellHalfAction: { fraction in sellHalfAction(row.position, fraction) },
                        sellCustomAction: { quantity in sellCustomAction(row.position, quantity) }
                    )
                    .id(row.renderID)
                }
            }
        }
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }

    private func liveSnapshot(_ position: PaperTradingPosition) -> PaperPositionSnapshot {
        let normalized = PaperTradeStock.normalizedTicker(position.ticker)
        let live = liveStockMap[normalized]
        let override = liveQuote(for: position)
        let current = [override?.price, live?.price, position.currentPrice]
            .compactMap { $0 }
            .first { $0 > 0 } ?? 0
        let changePercent = override?.changePercent ?? live?.changePercent ?? 0
        let marketValue = current * position.quantity
        let invested = position.avgPrice * position.quantity
        let pnl = marketValue - invested
        let pct = invested > 0 ? pnl / invested * 100 : 0
        let previousPrice = changePercent > -99 ? current / (1 + changePercent / 100) : current
        let dailyPnl = (current - previousPrice) * position.quantity
        return PaperPositionSnapshot(
            ticker: position.ticker,
            currentPrice: current,
            marketValue: marketValue,
            profitLoss: pnl,
            profitLossPct: pct,
            dailyProfitLoss: dailyPnl,
            dailyProfitLossPct: changePercent,
            source: override?.source ?? (live?.price ?? 0 > 0 ? "앱 데이터" : "저장가"),
            updatedAt: override?.updatedAt
        )
    }

    private func liveQuote(for position: PaperTradingPosition) -> LiveQuote? {
        let keys = [
            PaperTradeStock.normalizedTicker(position.ticker),
            PaperMarketClassifier.identityKey(for: position.ticker),
            position.ticker.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        ]
        return keys.compactMap { quoteOverrides[$0] }.first { $0.price > 0 }
    }

    private var lastUpdateText: String {
        guard let lastQuoteUpdatedAt else {
            return "마지막 업데이트: 대기 · 데이터 출처: 저장 시세"
        }
        return "마지막 업데이트: \(AppDateTime.localString(from: lastQuoteUpdatedAt, format: "yyyy-MM-dd HH:mm:ss")) · 데이터 출처: \(quoteSourceText)"
    }

    private var quoteSourceText: String {
        let sources = quoteOverrides.values
            .map(\.source)
            .uniqued()
            .prefix(3)
            .joined(separator: "/")
        return sources.isEmpty ? "대기" : sources
    }

    private var marketSessionSummary: String {
        let labels = (account?.positions ?? [])
            .filter { market.matches($0) }
            .map { MarketSessionClock.forTicker($0.ticker).label }
            .uniqued()
            .prefix(3)
            .joined(separator: "/")
        return labels.isEmpty ? "시장별 상태 대기" : labels
    }

    static func money(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0))) + "원"
    }

    static func signedMoney(_ value: Double) -> String {
        "\(value >= 0 ? "+" : "-")\(money(abs(value)))"
    }

    static func signedPercent(_ value: Double) -> String {
        "\(value >= 0 ? "+" : "")\(String(format: "%.2f", value))%"
    }

    private var marketCashValue: Double {
        switch market {
        case .korea:
            return account?.cash ?? 0
        case .us:
            return PaperTradeCurrencyFormatter.krwValueForUSD(usdCash)
        }
    }
}

private struct PaperPortfolioLoadingCard: View {
    var body: some View {
        HStack(spacing: 10) {
            ProgressView()
            VStack(alignment: .leading, spacing: 2) {
                Text("모의투자 데이터 불러오는 중")
                    .font(.caption.bold())
                Text("저장된 보유 종목을 확인한 뒤 화면에 표시합니다.")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct PaperPositionRow: Identifiable {
    let position: PaperTradingPosition
    let snapshot: PaperPositionSnapshot

    var id: String {
        PaperMarketClassifier.identityKey(for: position.ticker)
    }

    var renderID: String {
        let priceKey = String(format: "%.4f", snapshot.currentPrice)
        let pnlKey = String(format: "%.4f", snapshot.profitLoss)
        let updatedKey = snapshot.updatedAt?.timeIntervalSince1970.description ?? "stored"
        return "\(id)|\(priceKey)|\(pnlKey)|\(updatedKey)"
    }
}

private struct PaperPositionSnapshot {
    let ticker: String
    let currentPrice: Double
    let marketValue: Double
    let profitLoss: Double
    let profitLossPct: Double
    let dailyProfitLoss: Double
    let dailyProfitLossPct: Double
    let source: String
    let updatedAt: Date?

    var priceMetaText: String {
        let time = updatedAt.map { AppDateTime.shortLocalString(from: $0) } ?? "저장 시세"
        return "\(source) · \(MarketSessionClock.forTicker(ticker).label) · \(time)"
    }
}

private struct PaperHoldingsTotals {
    let marketValue: Double
    let invested: Double
    let profit: Double
    let dailyProfit: Double

    static let empty = PaperHoldingsTotals(marketValue: 0, invested: 0, profit: 0, dailyProfit: 0)

    var profitPct: Double {
        guard invested > 0 else { return 0 }
        return profit / invested * 100
    }
}

private struct PaperRealizedSummary {
    let profit: Double
    let proceeds: Double
    let costBasis: Double
    let sellCount: Int
    let grossProfit: Double
    let grossLoss: Double
    let winCount: Int
    let lossCount: Int
    let breakevenCount: Int
    let avgWinPct: Double
    let avgLossPct: Double
    let topWinners: [PaperRealizedTickerPerformance]
    let topLosers: [PaperRealizedTickerPerformance]

    static let empty = PaperRealizedSummary(
        profit: 0,
        proceeds: 0,
        costBasis: 0,
        sellCount: 0,
        grossProfit: 0,
        grossLoss: 0,
        winCount: 0,
        lossCount: 0,
        breakevenCount: 0,
        avgWinPct: 0,
        avgLossPct: 0,
        topWinners: [],
        topLosers: []
    )

    var profitPct: Double {
        guard costBasis > 0 else { return 0 }
        return profit / costBasis * 100
    }

    var winRate: Double {
        guard sellCount > 0 else { return 0 }
        return Double(winCount) / Double(sellCount) * 100
    }

    var totalTradeCount: Int {
        sellCount
    }

    static func calculate(from trades: [PaperTradingTrade]) -> PaperRealizedSummary {
        var lots: [String: (quantity: Double, cost: Double)] = [:]
        var names: [String: String] = [:]
        var tickerPerformance: [String: PaperRealizedTickerAccumulator] = [:]
        var realizedProfit: Double = 0
        var realizedProceeds: Double = 0
        var realizedCost: Double = 0
        var sellCount = 0
        var grossProfit: Double = 0
        var grossLoss: Double = 0
        var winCount = 0
        var lossCount = 0
        var breakevenCount = 0
        var winPctTotal: Double = 0
        var lossPctTotal: Double = 0

        for trade in trades.sorted(by: { $0.at < $1.at }) {
            let key = PaperTradeStock.normalizedTicker(trade.ticker)
            guard !key.isEmpty, trade.quantity > 0, trade.price > 0 else {
                continue
            }
            names[key] = trade.name

            if trade.isBuy {
                var lot = lots[key] ?? (quantity: 0, cost: 0)
                lot.quantity += trade.quantity
                lot.cost += trade.cashAmount ?? PaperTradeCurrencyFormatter.krwValue(trade.quantity * trade.price, ticker: trade.ticker)
                lots[key] = lot
            } else if trade.isSell {
                let sellQuantity = trade.quantity
                let sellAmount = trade.cashAmount ?? PaperTradeCurrencyFormatter.krwValue(sellQuantity * trade.price, ticker: trade.ticker)
                let lot = lots[key] ?? (quantity: 0, cost: 0)
                let avgCost = lot.quantity > 0 ? lot.cost / lot.quantity : trade.price
                let cost = lot.quantity > 0 ? sellQuantity * avgCost : PaperTradeCurrencyFormatter.krwValue(sellQuantity * avgCost, ticker: trade.ticker)
                let tradeProfit = trade.realizedProfit ?? (sellAmount - cost)
                let tradeProfitPct = trade.realizedProfitPct ?? (cost > 0 ? tradeProfit / cost * 100 : 0)

                realizedProceeds += sellAmount
                realizedCost += cost
                realizedProfit += tradeProfit
                sellCount += 1
                if tradeProfit > 0 {
                    grossProfit += tradeProfit
                    winCount += 1
                    winPctTotal += tradeProfitPct
                } else if tradeProfit < 0 {
                    grossLoss += tradeProfit
                    lossCount += 1
                    lossPctTotal += tradeProfitPct
                } else {
                    breakevenCount += 1
                }

                var accumulator = tickerPerformance[key] ?? PaperRealizedTickerAccumulator(
                    ticker: trade.ticker,
                    name: names[key] ?? trade.name,
                    profit: 0,
                    proceeds: 0,
                    costBasis: 0,
                    sellCount: 0
                )
                accumulator.profit += tradeProfit
                accumulator.proceeds += sellAmount
                accumulator.costBasis += cost
                accumulator.sellCount += 1
                tickerPerformance[key] = accumulator

                if lot.quantity > 0 {
                    let remainingQuantity = max(0, lot.quantity - sellQuantity)
                    lots[key] = (
                        quantity: remainingQuantity,
                        cost: remainingQuantity * avgCost
                    )
                }
            }
        }

        let performances = tickerPerformance.values.map { $0.performance }
        return PaperRealizedSummary(
            profit: realizedProfit,
            proceeds: realizedProceeds,
            costBasis: realizedCost,
            sellCount: sellCount,
            grossProfit: grossProfit,
            grossLoss: grossLoss,
            winCount: winCount,
            lossCount: lossCount,
            breakevenCount: breakevenCount,
            avgWinPct: winCount > 0 ? winPctTotal / Double(winCount) : 0,
            avgLossPct: lossCount > 0 ? lossPctTotal / Double(lossCount) : 0,
            topWinners: Array(performances.filter { $0.profit > 0 }.sorted { $0.profit > $1.profit }.prefix(5)),
            topLosers: Array(performances.filter { $0.profit < 0 }.sorted { $0.profit < $1.profit }.prefix(5))
        )
    }
}

private struct PaperRealizedTickerPerformance: Identifiable {
    var id: String { ticker }
    let ticker: String
    let name: String
    let profit: Double
    let proceeds: Double
    let costBasis: Double
    let sellCount: Int

    var profitPct: Double {
        guard costBasis > 0 else { return 0 }
        return profit / costBasis * 100
    }
}

private struct PaperRealizedTickerAccumulator {
    let ticker: String
    let name: String
    var profit: Double
    var proceeds: Double
    var costBasis: Double
    var sellCount: Int

    var performance: PaperRealizedTickerPerformance {
        PaperRealizedTickerPerformance(
            ticker: ticker,
            name: name,
            profit: profit,
            proceeds: proceeds,
            costBasis: costBasis,
            sellCount: sellCount
        )
    }
}

private struct PaperTradeRealizedResult {
    let tradeID: String
    let proceeds: Double
    let costBasis: Double
    let profit: Double
    let profitPct: Double

    static func calculateByTradeID(from trades: [PaperTradingTrade]) -> [String: PaperTradeRealizedResult] {
        var lots: [String: (quantity: Double, cost: Double)] = [:]
        var results: [String: PaperTradeRealizedResult] = [:]

        for trade in trades.sorted(by: { $0.at < $1.at }) {
            let key = PaperTradeStock.normalizedTicker(trade.ticker)
            guard !key.isEmpty, trade.quantity > 0, trade.price > 0 else {
                continue
            }

            if trade.isBuy {
                var lot = lots[key] ?? (quantity: 0, cost: 0)
                lot.quantity += trade.quantity
                lot.cost += trade.cashAmount ?? PaperTradeCurrencyFormatter.krwValue(trade.quantity * trade.price, ticker: trade.ticker)
                lots[key] = lot
            } else if trade.isSell {
                let lot = lots[key] ?? (quantity: 0, cost: 0)
                let avgCost = lot.quantity > 0 ? lot.cost / lot.quantity : PaperTradeCurrencyFormatter.krwValue(trade.price, ticker: trade.ticker)
                let proceeds = trade.cashAmount ?? PaperTradeCurrencyFormatter.krwValue(trade.quantity * trade.price, ticker: trade.ticker)
                let costBasis = lot.quantity > 0 ? trade.quantity * avgCost : PaperTradeCurrencyFormatter.krwValue(trade.quantity * trade.price, ticker: trade.ticker)
                let profit = trade.realizedProfit ?? (proceeds - costBasis)
                let profitPct = trade.realizedProfitPct ?? (costBasis > 0 ? profit / costBasis * 100 : 0)
                results[trade.id] = PaperTradeRealizedResult(
                    tradeID: trade.id,
                    proceeds: proceeds,
                    costBasis: costBasis,
                    profit: profit,
                    profitPct: profitPct
                )

                if lot.quantity > 0 {
                    let remainingQuantity = max(0, lot.quantity - trade.quantity)
                    lots[key] = (quantity: remainingQuantity, cost: remainingQuantity * avgCost)
                }
            }
        }

        return results
    }
}

private struct PaperSellEvaluation {
    let tradeID: String
    let ticker: String
    let score: Int
    let badge: String
    let reason: String
    let postMovePct: Double
    let sellPrice: Double
    let currentPrice: Double
    let profitPct: Double

    var tint: Color {
        if score >= 80 { return .green }
        if score >= 65 { return .orange }
        return .red
    }

    var isGood: Bool { score >= 80 }
    var isEarly: Bool { badge.contains("이른") || postMovePct >= 5 }
    var isRiskyLoss: Bool { profitPct < 0 && score < 65 }

    var postSaleText: String {
        let direction = postMovePct >= 0 ? "추가 상승" : "하락"
        return "매도 후 현재가 \(PaperTradeCurrencyFormatter.price(currentPrice, ticker: ticker)) · \(direction) \(PaperHoldingsPanel.signedPercent(postMovePct))"
    }

    static func calculateByTradeID(
        from trades: [PaperTradingTrade],
        realizedByTradeID: [String: PaperTradeRealizedResult],
        currentPriceByTicker: [String: Double]
    ) -> [String: PaperSellEvaluation] {
        var results: [String: PaperSellEvaluation] = [:]
        for trade in trades where trade.isSell && trade.price > 0 {
            let normalized = PaperTradeStock.normalizedTicker(trade.ticker)
            let currentPrice = currentPriceByTicker[normalized] ?? trade.price
            let postMovePct = (currentPrice / trade.price - 1) * 100
            let realized = realizedByTradeID[trade.id]
            let profitPct = realized?.profitPct ?? trade.realizedProfitPct ?? 0
            results[trade.id] = evaluate(
                tradeID: trade.id,
                ticker: trade.ticker,
                sellPrice: trade.price,
                currentPrice: currentPrice,
                profitPct: profitPct,
                postMovePct: postMovePct
            )
        }
        return results
    }

    private static func evaluate(
        tradeID: String,
        ticker: String,
        sellPrice: Double,
        currentPrice: Double,
        profitPct: Double,
        postMovePct: Double
    ) -> PaperSellEvaluation {
        let score: Int
        let badge: String
        let reason: String

        if profitPct >= 0 {
            if postMovePct <= -5 {
                score = 92
                badge = "✅ 잘한 매도"
                reason = "수익을 확정한 뒤 주가가 내려갔습니다. 상승분을 확보하고 조정 전에 빠져나온 좋은 익절로 평가됩니다."
            } else if postMovePct <= 3 {
                score = 84
                badge = "✅ 무난한 익절"
                reason = "수익을 확보했고 매도 이후 추가 상승이 제한적입니다. 목표 수익률 관리 관점에서 안정적인 매도입니다."
            } else if postMovePct <= 10 {
                score = 70
                badge = "⚠️ 조금 이른 매도"
                reason = "수익 실현은 성공했지만 매도 이후 추가 상승이 나왔습니다. 다음에는 일부 물량 유지 또는 분할매도를 고려하세요."
            } else {
                score = 58
                badge = "⚠️ 아쉬운 매도"
                reason = "매도 이후 주가가 크게 더 올랐습니다. 강한 추세 구간에서는 전량 매도보다 50% 익절 후 잔여 보유 전략이 더 유리했을 수 있습니다."
            }
        } else {
            if postMovePct <= -5 {
                score = 88
                badge = "✅ 잘한 손절"
                reason = "손실을 제한한 뒤 추가 하락이 발생했습니다. 더 큰 손실을 피한 적절한 리스크 관리로 평가됩니다."
            } else if postMovePct <= 3 {
                score = 72
                badge = "⚠️ 방어적 손절"
                reason = "손실을 확정했지만 이후 흐름은 크게 나쁘지 않습니다. 손절 기준 자체는 지켰으나 진입 타이밍을 다시 점검하세요."
            } else {
                score = 52
                badge = "❌ 아쉬운 손절"
                reason = "손절 이후 주가가 회복했습니다. 다음에는 지지선 이탈 여부와 뉴스/수급 악화가 실제로 확인됐는지 함께 점검하는 편이 좋습니다."
            }
        }

        return PaperSellEvaluation(
            tradeID: tradeID,
            ticker: ticker,
            score: score,
            badge: badge,
            reason: reason,
            postMovePct: postMovePct,
            sellPrice: sellPrice,
            currentPrice: currentPrice,
            profitPct: profitPct
        )
    }
}

private struct PaperRealizedProfitCard: View {
    let summary: PaperRealizedSummary
    let evaluations: [PaperSellEvaluation]

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .firstTextBaseline) {
                Text("투자 성과 · 실현 손익")
                    .font(.caption.bold())
                Spacer(minLength: 8)
                Text(summary.sellCount > 0 ? "\(summary.sellCount)건 매도 · 승률 \(PaperHoldingsPanel.signedPercent(summary.winRate).replacingOccurrences(of: "+", with: ""))" : "매도 없음")
                    .font(.caption2.monospacedDigit().bold())
                    .foregroundStyle(.secondary)
            }

            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(PaperHoldingsPanel.signedMoney(summary.profit))
                    .font(.headline.monospacedDigit().bold())
                    .foregroundStyle(summary.profit >= 0 ? .red : .blue)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Text(PaperHoldingsPanel.signedPercent(summary.profitPct))
                    .font(.caption.monospacedDigit().bold())
                    .foregroundStyle(summary.profit >= 0 ? .red : .blue)
                Spacer(minLength: 0)
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 112), spacing: 8)], alignment: .leading, spacing: 8) {
                PaperMiniMetric(title: "총 매수원가", value: PaperHoldingsPanel.money(summary.costBasis))
                PaperMiniMetric(title: "총 매도금액", value: PaperHoldingsPanel.money(summary.proceeds))
                PaperMiniMetric(title: "총 수익", value: PaperHoldingsPanel.signedMoney(summary.grossProfit))
                PaperMiniMetric(title: "총 손실", value: PaperHoldingsPanel.signedMoney(summary.grossLoss))
                PaperMiniMetric(title: "수익 거래", value: "\(summary.winCount)건")
                PaperMiniMetric(title: "손실 거래", value: "\(summary.lossCount)건")
                PaperMiniMetric(title: "평균 수익률", value: PaperHoldingsPanel.signedPercent(summary.avgWinPct))
                PaperMiniMetric(title: "평균 손실률", value: PaperHoldingsPanel.signedPercent(summary.avgLossPct))
            }

            if !summary.topWinners.isEmpty || !summary.topLosers.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    if !summary.topWinners.isEmpty {
                        PaperRealizedRankList(title: "수익 TOP 5", rows: summary.topWinners, tint: .red)
                    }
                    if !summary.topLosers.isEmpty {
                        PaperRealizedRankList(title: "손실 TOP 5", rows: summary.topLosers, tint: .blue)
                    }
                }
            }

            if !evaluations.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("AI 매도 복기")
                        .font(.caption.bold())
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 112), spacing: 8)], alignment: .leading, spacing: 8) {
                        PaperMiniMetric(title: "평균 매도점수", value: "\(averageEvaluationScore)점")
                        PaperMiniMetric(title: "잘한 매도", value: "\(evaluations.filter(\.isGood).count)회")
                        PaperMiniMetric(title: "이른 매도", value: "\(evaluations.filter(\.isEarly).count)회")
                        PaperMiniMetric(title: "아쉬운 손절", value: "\(evaluations.filter(\.isRiskyLoss).count)회")
                    }
                    Text(aiSellHabitFeedback)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(8)
                .background(AppColors.panel.opacity(0.72), in: RoundedRectangle(cornerRadius: 7))
            }

            Text(aiTradeFeedback)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            Text("보유 중인 평가손익과 별개로, 실제 매도해서 확정된 손익만 계산합니다.")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background((summary.profit >= 0 ? Color.red : Color.blue).opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke((summary.profit >= 0 ? Color.red : Color.blue).opacity(0.24), lineWidth: 1))
    }

    private var aiTradeFeedback: String {
        guard summary.sellCount > 0 else {
            return "AI 피드백: 아직 매도 기록이 없어 매매 습관 분석 대기 중입니다."
        }
        if summary.winRate >= 65, summary.profit > 0 {
            return "AI 피드백: 승률과 실현손익이 양호합니다. 익절 후 재진입 기준만 계속 점검하세요."
        }
        if summary.grossProfit > 0, abs(summary.grossLoss) > summary.grossProfit {
            return "AI 피드백: 수익 거래보다 손실 거래의 손실폭이 큽니다. 손절 기준과 추격매수 여부를 점검하세요."
        }
        if summary.winRate < 40 {
            return "AI 피드백: 승률이 낮습니다. 급등 후 늦은 매수, 뉴스 반영 후 추격 진입 패턴을 줄이는 쪽이 좋습니다."
        }
        return "AI 피드백: 손익 구조는 중립입니다. 평균 손실률이 평균 수익률보다 커지는지 계속 추적하세요."
    }

    private var averageEvaluationScore: Int {
        guard !evaluations.isEmpty else { return 0 }
        return Int((Double(evaluations.map(\.score).reduce(0, +)) / Double(evaluations.count)).rounded())
    }

    private var aiSellHabitFeedback: String {
        guard !evaluations.isEmpty else {
            return "매도 복기 대기 중입니다."
        }
        let earlyCount = evaluations.filter(\.isEarly).count
        let goodCount = evaluations.filter(\.isGood).count
        let riskyLossCount = evaluations.filter(\.isRiskyLoss).count
        if earlyCount >= max(2, evaluations.count / 2) {
            return "AI 매도 습관: 수익 종목을 조금 빨리 파는 경향이 있습니다. 목표가 도달 시 전량 매도보다 50% 익절 후 나머지 보유 전략이 어울립니다."
        }
        if riskyLossCount >= 2 {
            return "AI 매도 습관: 손실 확정 후 회복되는 거래가 반복됩니다. 매수 근거가 깨졌는지 확인한 뒤 손절하는 체크리스트가 필요합니다."
        }
        if goodCount >= max(1, evaluations.count * 2 / 3) {
            return "AI 매도 습관: 매도 후 흐름 기준으로 좋은 매도가 많습니다. 현재 익절/손절 기준은 비교적 안정적으로 작동하고 있습니다."
        }
        return "AI 매도 습관: 아직 뚜렷한 한 가지 패턴보다는 종목별 차이가 큽니다. 거래가 쌓이면 더 명확하게 평가됩니다."
    }
}

private struct PaperRealizedRankList: View {
    let title: String
    let rows: [PaperRealizedTickerPerformance]
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2.bold())
                .foregroundStyle(.secondary)
            ForEach(rows) { row in
                HStack(spacing: 6) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(StockDisplayName.localizedName(row.name, ticker: row.ticker, market: PaperMarketClassifier.marketText(for: row.ticker)))
                            .font(.caption2.bold())
                            .lineLimit(1)
                        Text(row.ticker)
                            .font(.caption2.monospacedDigit().weight(.medium))
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 8)
                    VStack(alignment: .trailing, spacing: 1) {
                        Text(PaperHoldingsPanel.signedMoney(row.profit))
                            .font(.caption2.monospacedDigit().bold())
                            .foregroundStyle(tint)
                        Text(PaperHoldingsPanel.signedPercent(row.profitPct))
                            .font(.caption2.monospacedDigit().weight(.medium))
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(7)
                .background(AppColors.panel.opacity(0.75), in: RoundedRectangle(cornerRadius: 7))
            }
        }
    }
}

private struct PaperHoldingCard: View {
    let position: PaperTradingPosition
    let snapshot: PaperPositionSnapshot
    @Binding var customSellQuantityText: String
    let sellAllAction: () -> Void
    let sellHalfAction: (Double) -> Void
    let sellCustomAction: (Double) -> Void

    private var marketSession: MarketSessionClock {
        MarketSessionClock.forTicker(position.ticker)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top) {
                LocalizedStockNameView(
                    name: position.name,
                    ticker: position.ticker,
                    market: PaperMarketClassifier.marketText(for: position.ticker),
                    primaryFont: .subheadline.bold(),
                    secondaryFont: .caption2.weight(.medium)
                )
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text(marketSession.label)
                        .font(.caption2.monospacedDigit().bold())
                        .foregroundStyle(marketSession.tint)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .background(marketSession.tint.opacity(0.14), in: Capsule())
                    Text(PaperTradeCurrencyFormatter.signedAmount(snapshot.profitLoss, ticker: position.ticker))
                        .font(.caption.monospacedDigit().bold())
                        .foregroundStyle(snapshot.profitLoss >= 0 ? .red : .blue)
                    Text(Self.signedPercent(snapshot.profitLossPct))
                        .font(.caption2.monospacedDigit().bold())
                        .foregroundStyle(snapshot.profitLoss >= 0 ? .red : .blue)
                }
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 132), spacing: 8)], alignment: .leading, spacing: 8) {
                PaperMiniMetric(title: "보유", value: "\(Self.qty(position.quantity))주")
                PaperMiniMetric(title: "평균매수가", value: PaperTradeCurrencyFormatter.price(position.avgPrice, ticker: position.ticker))
                if let avgKrw = PaperTradeCurrencyFormatter.krwApproxText(position.avgPrice, ticker: position.ticker) {
                    PaperMiniMetric(title: "평균가 원화", value: avgKrw)
                }
                PaperMiniMetric(title: "현재가", value: PaperTradeCurrencyFormatter.price(snapshot.currentPrice, ticker: position.ticker))
                PaperMiniMetric(
                    title: "일일 손익",
                    value: "\(PaperTradeCurrencyFormatter.signedAmount(snapshot.dailyProfitLoss, ticker: position.ticker)) (\(Self.signedPercent(snapshot.dailyProfitLossPct)))"
                )
                PaperMiniMetric(title: "총 투자금", value: PaperTradeCurrencyFormatter.amount(position.avgPrice * position.quantity, ticker: position.ticker))
                PaperMiniMetric(title: "평가금액", value: PaperTradeCurrencyFormatter.amount(snapshot.marketValue, ticker: position.ticker))
            }

            HStack(spacing: 6) {
                Image(systemName: "dot.radiowaves.left.and.right")
                Text(snapshot.priceMetaText)
            }
            .font(.caption2.weight(.medium))
            .foregroundStyle(.secondary)
            .lineLimit(2)
            .fixedSize(horizontal: false, vertical: true)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 58), spacing: 6)], alignment: .leading, spacing: 6) {
                Button("10%") {
                    dismissKeyboard()
                    sellHalfAction(0.1)
                }
                .buttonStyle(.bordered)
                Button("20%") {
                    dismissKeyboard()
                    sellHalfAction(0.2)
                }
                .buttonStyle(.bordered)
                Button("40%") {
                    dismissKeyboard()
                    sellHalfAction(0.4)
                }
                .buttonStyle(.bordered)
                Button("50%") {
                    dismissKeyboard()
                    sellHalfAction(0.5)
                }
                .buttonStyle(.bordered)
                Button("전량") {
                    dismissKeyboard()
                    sellAllAction()
                }
                .buttonStyle(.borderedProminent)
            }
            .font(.caption.bold())

            HStack(spacing: 8) {
                ScreeningTextField(title: "직접 수량", text: $customSellQuantityText, keyboard: .decimalPad)
                Button("직접 매도") {
                    dismissKeyboard()
                    if let quantity = Double(customSellQuantityText.replacingOccurrences(of: ",", with: "")), quantity > 0 {
                        sellCustomAction(quantity)
                    }
                }
                .buttonStyle(.bordered)
            }
            .font(.caption.bold())
        }
        .padding(10)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    static func money(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0))) + "원"
    }

    static func signedMoney(_ value: Double) -> String {
        "\(value >= 0 ? "+" : "-")\(money(abs(value)))"
    }

    static func signedPercent(_ value: Double) -> String {
        "\(value >= 0 ? "+" : "")\(String(format: "%.2f", value))%"
    }

    static func price(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0...2)))
    }

    static func qty(_ value: Double) -> String {
        value.rounded() == value ? "\(Int(value))" : value.formatted(.number.precision(.fractionLength(0...2)))
    }
}

private struct PaperMiniMetric: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.monospacedDigit().bold())
                .lineLimit(3)
                .minimumScaleFactor(0.62)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 2)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct PaperTradeHistoryPanel: View {
    let account: PaperTradingAccountPayload?
    let market: PaperTradingMarket
    let liveStocks: [PaperTradeStock]
    let quoteOverrides: [String: LiveQuote]

    private var filteredTrades: [PaperTradingTrade] {
        (account?.trades ?? []).filter { market.matches($0) }
    }

    private var realizedByTradeID: [String: PaperTradeRealizedResult] {
        PaperTradeRealizedResult.calculateByTradeID(from: filteredTrades)
    }

    private var sellEvaluations: [String: PaperSellEvaluation] {
        PaperSellEvaluation.calculateByTradeID(
            from: filteredTrades,
            realizedByTradeID: realizedByTradeID,
            currentPriceByTicker: currentPriceByTicker
        )
    }

    private var currentPriceByTicker: [String: Double] {
        var prices = liveStocks.reduce(into: [String: Double]()) { result, stock in
            let key = stock.normalizedTicker
            if result[key] == nil || stock.price > 0 {
                result[key] = stock.price
            }
        }
        for (ticker, quote) in quoteOverrides {
            prices[PaperTradeStock.normalizedTicker(ticker)] = quote.price
        }
        return prices
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(market.historyTitle)
                .font(.subheadline.bold())
            if filteredTrades.isEmpty {
                Text("아직 \(market.displayTitle) 거래내역이 없습니다.")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            } else {
                ForEach(filteredTrades.reversed()) { trade in
                    PaperTradeHistoryRow(
                        trade: trade,
                        realized: realizedByTradeID[trade.id],
                        evaluation: sellEvaluations[trade.id]
                    )
                }
            }
        }
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct PaperTradeHistoryRow: View {
    let trade: PaperTradingTrade
    let realized: PaperTradeRealizedResult?
    let evaluation: PaperSellEvaluation?

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: iconName)
                .foregroundStyle(tint)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.caption.bold())
                    .lineLimit(2)
                Text(detail)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let realized, trade.isSell {
                    Text("거래 손익 \(PaperHoldingsPanel.signedMoney(realized.profit)) (\(PaperHoldingsPanel.signedPercent(realized.profitPct))) · 실제 입금 \(PaperHoldingsPanel.money(realized.proceeds)) · 수수료 \(PaperHoldingsPanel.money(trade.fee ?? 0))")
                        .font(.caption2.monospacedDigit().weight(.semibold))
                        .foregroundStyle(realized.profit >= 0 ? .red : .blue)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let evaluation, trade.isSell {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text(evaluation.badge)
                                .font(.caption2.bold())
                                .foregroundStyle(evaluation.tint)
                            Text("\(evaluation.score)점")
                                .font(.caption2.monospacedDigit().bold())
                                .foregroundStyle(.secondary)
                        }
                        Text(evaluation.postSaleText)
                            .font(.caption2.monospacedDigit().weight(.semibold))
                            .foregroundStyle(evaluation.postMovePct <= 0 ? .red : .blue)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(evaluation.reason)
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(evaluation.tint.opacity(0.09), in: RoundedRectangle(cornerRadius: 7))
                }
            }
            Spacer()
            Text(Self.shortDate(trade.at))
                .font(.caption2.monospacedDigit().weight(.medium))
                .foregroundStyle(.secondary)
        }
        .padding(10)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
    }

    private var title: String {
        if trade.isDeposit { return "입금 · \(Self.money(trade.amount))" }
        let side = trade.isBuy ? "매수" : "매도"
        return "\(StockDisplayName.localizedName(trade.name, ticker: trade.ticker, market: PaperMarketClassifier.marketText(for: trade.ticker))) · \(side)"
    }

    private var detail: String {
        if trade.isDeposit { return "모의 현금 입금" }
        let gross = "\(Self.qty(trade.quantity))주 · \(PaperTradeCurrencyFormatter.price(trade.price, ticker: trade.ticker)) · 총 \(PaperTradeCurrencyFormatter.amount(trade.quantity * trade.price, ticker: trade.ticker))"
        guard trade.isSell, let cashAmount = trade.cashAmount else {
            return gross
        }
        return "\(gross) · 실제 입금 \(PaperHoldingsPanel.money(cashAmount))"
    }

    private var tint: Color {
        if trade.isBuy { return .green }
        if trade.isSell { return .blue }
        return .mint
    }

    private var iconName: String {
        if trade.isBuy { return "cart.fill" }
        if trade.isSell { return "arrow.up.circle.fill" }
        return "banknote.fill"
    }

    static func money(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0))) + "원"
    }

    static func price(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0...2)))
    }

    static func qty(_ value: Double) -> String {
        value.rounded() == value ? "\(Int(value))" : value.formatted(.number.precision(.fractionLength(0...2)))
    }

    static func shortDate(_ text: String) -> String {
        String(text.prefix(10))
    }
}

private struct PaperTradeStock: Identifiable, Equatable {
    let name: String
    let ticker: String
    let sector: String
    let marketText: String
    let price: Double
    let priceText: String
    let changePercent: Double
    let score: Int
    let reason: String
    let confidence: Int
    let upsideProbability: Int
    let searchText: String
    let detailResult: ScannerResult?

    var id: String { normalizedTicker }
    var normalizedTicker: String { Self.normalizedTicker(ticker) }

    static let semiconductorETFDefaults: [PaperTradeStock] = [
        PaperTradeStock(name: "엔비디아", ticker: "NVDA", sector: "미국 반도체/AI 가속기", price: 0, changePercent: 0, score: 88, reason: "AI GPU 대표주 · 반도체 ETF 핵심 편입 종목"),
        PaperTradeStock(name: "AMD", ticker: "AMD", sector: "미국 반도체/AI 칩", price: 0, changePercent: 0, score: 78, reason: "AI 가속기와 CPU/GPU 경쟁 구도 핵심 종목"),
        PaperTradeStock(name: "브로드컴", ticker: "AVGO", sector: "미국 반도체/네트워크칩", price: 0, changePercent: 0, score: 82, reason: "AI 네트워킹/ASIC 수요와 반도체 ETF 주요 비중"),
        PaperTradeStock(name: "TSMC", ticker: "TSM", sector: "미국 ADR/파운드리", price: 0, changePercent: 0, score: 80, reason: "글로벌 파운드리 1위 · AI 반도체 공급망 핵심"),
        PaperTradeStock(name: "ASML", ticker: "ASML", sector: "미국 ADR/반도체장비", price: 0, changePercent: 0, score: 78, reason: "EUV 노광장비 독점력 · 첨단공정 투자 핵심"),
        PaperTradeStock(name: "마이크론", ticker: "MU", sector: "미국 메모리/HBM", price: 0, changePercent: 0, score: 76, reason: "HBM/DRAM 업황 회복 민감 종목"),
        PaperTradeStock(name: "샌디스크", ticker: "SNDK", sector: "미국 메모리/낸드", price: 0, changePercent: 0, score: 66, reason: "낸드/스토리지 사이클 회복 관찰 종목"),
        PaperTradeStock(name: "웨스턴디지털", ticker: "WDC", sector: "미국 스토리지/낸드", price: 0, changePercent: 0, score: 68, reason: "스토리지와 낸드 가격 사이클 민감 종목"),
        PaperTradeStock(name: "어플라이드 머티어리얼즈", ticker: "AMAT", sector: "미국 반도체장비", price: 0, changePercent: 0, score: 74, reason: "전공정 장비 대표주 · 설비투자 회복 수혜"),
        PaperTradeStock(name: "램리서치", ticker: "LRCX", sector: "미국 반도체장비", price: 0, changePercent: 0, score: 73, reason: "식각/증착 장비 대표주 · 메모리 투자 회복 수혜"),
        PaperTradeStock(name: "KLA", ticker: "KLAC", sector: "미국 반도체장비/검사", price: 0, changePercent: 0, score: 72, reason: "공정 검사/계측 장비 핵심 업체"),
        PaperTradeStock(name: "퀄컴", ticker: "QCOM", sector: "미국 반도체/모바일", price: 0, changePercent: 0, score: 70, reason: "모바일 AP와 온디바이스 AI 수혜 관찰"),
        PaperTradeStock(name: "인텔", ticker: "INTC", sector: "미국 반도체/파운드리", price: 0, changePercent: 0, score: 58, reason: "턴어라운드/파운드리 전략 진행 상황 관찰"),
        PaperTradeStock(name: "마벨", ticker: "MRVL", sector: "미국 반도체/데이터센터", price: 0, changePercent: 0, score: 72, reason: "데이터센터 커스텀칩/네트워크 반도체 수혜"),
        PaperTradeStock(name: "ARM", ticker: "ARM", sector: "미국 반도체/IP", price: 0, changePercent: 0, score: 74, reason: "CPU IP와 AI 디바이스 확산 수혜"),
        PaperTradeStock(name: "슈퍼마이크로", ticker: "SMCI", sector: "미국 AI 서버", price: 0, changePercent: 0, score: 70, reason: "AI 서버 수요와 GPU 공급망 민감 종목"),
        PaperTradeStock(name: "시놉시스", ticker: "SNPS", sector: "미국 반도체/EDA", price: 0, changePercent: 0, score: 71, reason: "반도체 설계 자동화 EDA 대표주"),
        PaperTradeStock(name: "케이던스", ticker: "CDNS", sector: "미국 반도체/EDA", price: 0, changePercent: 0, score: 70, reason: "EDA/IP 설계 소프트웨어 핵심 업체"),
        PaperTradeStock(name: "마이크로칩", ticker: "MCHP", sector: "미국 아날로그/MCU", price: 0, changePercent: 0, score: 62, reason: "산업/차량용 반도체 사이클 회복 관찰"),
        PaperTradeStock(name: "온세미", ticker: "ON", sector: "미국 전력반도체", price: 0, changePercent: 0, score: 64, reason: "전력반도체/차량용 수요 회복 관찰"),
        PaperTradeStock(name: "NXP", ticker: "NXPI", sector: "미국 차량용 반도체", price: 0, changePercent: 0, score: 65, reason: "차량용/산업용 반도체 대표주"),
        PaperTradeStock(name: "모놀리식 파워", ticker: "MPWR", sector: "미국 전력관리 반도체", price: 0, changePercent: 0, score: 70, reason: "AI 서버 전력관리 수요 수혜"),
        PaperTradeStock(name: "SOXX 반도체 ETF", ticker: "SOXX", sector: "미국 반도체 ETF", price: 0, changePercent: 0, score: 72, reason: "엔비디아, AMD, 브로드컴, 마이크론 등 반도체 대형주 분산 투자"),
        PaperTradeStock(name: "SMH 반도체 ETF", ticker: "SMH", sector: "미국 반도체 ETF", price: 0, changePercent: 0, score: 74, reason: "엔비디아/TSMC/ASML 중심 반도체 대표 ETF"),
        PaperTradeStock(name: "SOXQ 반도체 ETF", ticker: "SOXQ", sector: "미국 반도체 ETF", price: 0, changePercent: 0, score: 70, reason: "PHLX 반도체 지수 기반 분산 ETF"),
        PaperTradeStock(name: "XSD 반도체 ETF", ticker: "XSD", sector: "미국 반도체 ETF", price: 0, changePercent: 0, score: 68, reason: "중소형 반도체까지 포함하는 동일가중 성격 ETF"),
        PaperTradeStock(name: "FTXL 반도체 ETF", ticker: "FTXL", sector: "미국 반도체 ETF", price: 0, changePercent: 0, score: 67, reason: "나스닥 반도체 종목 선별 ETF"),
        PaperTradeStock(name: "PSI 반도체 ETF", ticker: "PSI", sector: "미국 반도체 ETF", price: 0, changePercent: 0, score: 67, reason: "동적 반도체 포트폴리오 ETF"),
        PaperTradeStock(name: "SOXL 반도체 3배 레버리지", ticker: "SOXL", sector: "미국 반도체 레버리지 ETF", price: 0, changePercent: 0, score: 45, reason: "3배 레버리지 · 단기 투자용 · 변동성 매우 큼"),
        PaperTradeStock(name: "SOXS 반도체 3배 인버스", ticker: "SOXS", sector: "미국 반도체 레버리지 ETF", price: 0, changePercent: 0, score: 35, reason: "3배 인버스 · 헤지/초단기용 · 장기 보유 부적합"),
        PaperTradeStock(name: "QQQ 나스닥100 ETF", ticker: "QQQ", sector: "미국 대표 ETF", price: 0, changePercent: 0, score: 78, reason: "나스닥100 대표 ETF · 빅테크/AI 흐름 확인"),
        PaperTradeStock(name: "QQQM 나스닥100 ETF", ticker: "QQQM", sector: "미국 대표 ETF", price: 0, changePercent: 0, score: 76, reason: "QQQ 저비용형 성격의 나스닥100 ETF"),
        PaperTradeStock(name: "QNDX 나스닥100 ETF", ticker: "QNDX", sector: "미국 대표 ETF", price: 0, changePercent: 0, score: 70, reason: "나스닥100 신규 ETF · 대형 기술주 분산"),
        PaperTradeStock(name: "TQQQ 나스닥 3배 레버리지", ticker: "TQQQ", sector: "미국 레버리지 ETF", price: 0, changePercent: 0, score: 42, reason: "나스닥100 3배 레버리지 · 초단기 변동성 주의"),
        PaperTradeStock(name: "SQQQ 나스닥 3배 인버스", ticker: "SQQQ", sector: "미국 레버리지 ETF", price: 0, changePercent: 0, score: 34, reason: "나스닥100 3배 인버스 · 헤지/초단기용"),
        PaperTradeStock(name: "SPY S&P500 ETF", ticker: "SPY", sector: "미국 대표 ETF", price: 0, changePercent: 0, score: 76, reason: "S&P500 대표 ETF · 미국 대형주 시장 기준"),
        PaperTradeStock(name: "VOO S&P500 ETF", ticker: "VOO", sector: "미국 대표 ETF", price: 0, changePercent: 0, score: 76, reason: "S&P500 저비용 장기투자 대표 ETF"),
        PaperTradeStock(name: "IVV S&P500 ETF", ticker: "IVV", sector: "미국 대표 ETF", price: 0, changePercent: 0, score: 76, reason: "S&P500 대형 ETF · 분산 투자 기준"),
        PaperTradeStock(name: "SPLG S&P500 ETF", ticker: "SPLG", sector: "미국 대표 ETF", price: 0, changePercent: 0, score: 74, reason: "S&P500 저가 단위 ETF · 소액 모의투자에 적합"),
        PaperTradeStock(name: "DIA 다우 ETF", ticker: "DIA", sector: "미국 대표 ETF", price: 0, changePercent: 0, score: 68, reason: "다우지수 대표 ETF · 경기민감 대형주 확인"),
        PaperTradeStock(name: "IWM 러셀2000 ETF", ticker: "IWM", sector: "미국 대표 ETF", price: 0, changePercent: 0, score: 66, reason: "미국 중소형주 흐름 확인용 ETF"),
        PaperTradeStock(name: "TSLL 테슬라 2배 롱 ETF", ticker: "TSLL", sector: "미국 단일종목 레버리지 ETF", price: 0, changePercent: 0, score: 38, reason: "테슬라 2배 롱 · 단기 변동성 매우 큼"),
        PaperTradeStock(name: "TSLS 테슬라 인버스 ETF", ticker: "TSLS", sector: "미국 단일종목 인버스 ETF", price: 0, changePercent: 0, score: 32, reason: "테슬라 하락 베팅형 · 초단기 헤지용"),
        PaperTradeStock(name: "TSLQ 테슬라 인버스 ETF", ticker: "TSLQ", sector: "미국 단일종목 인버스 ETF", price: 0, changePercent: 0, score: 32, reason: "테슬라 하락 추종 ETF · 장기 보유 주의"),
        PaperTradeStock(name: "NVDL 엔비디아 2배 롱 ETF", ticker: "NVDL", sector: "미국 단일종목 레버리지 ETF", price: 0, changePercent: 0, score: 40, reason: "엔비디아 2배 롱 · AI 반도체 고변동성"),
        PaperTradeStock(name: "NVDU 엔비디아 2배 롱 ETF", ticker: "NVDU", sector: "미국 단일종목 레버리지 ETF", price: 0, changePercent: 0, score: 40, reason: "엔비디아 2배 롱 · 단기 트레이딩 전용"),
        PaperTradeStock(name: "NVDQ 엔비디아 인버스 ETF", ticker: "NVDQ", sector: "미국 단일종목 인버스 ETF", price: 0, changePercent: 0, score: 32, reason: "엔비디아 하락 베팅형 · 초단기 헤지용"),
        PaperTradeStock(name: "AAPU 애플 2배 롱 ETF", ticker: "AAPU", sector: "미국 단일종목 레버리지 ETF", price: 0, changePercent: 0, score: 36, reason: "애플 2배 롱 · 단기 변동성 주의"),
        PaperTradeStock(name: "AAPD 애플 인버스 ETF", ticker: "AAPD", sector: "미국 단일종목 인버스 ETF", price: 0, changePercent: 0, score: 30, reason: "애플 하락 베팅형 · 초단기 헤지용"),
        PaperTradeStock(name: "MSFU 마이크로소프트 2배 롱 ETF", ticker: "MSFU", sector: "미국 단일종목 레버리지 ETF", price: 0, changePercent: 0, score: 36, reason: "마이크로소프트 2배 롱 · AI/클라우드 고변동성"),
        PaperTradeStock(name: "MSFD 마이크로소프트 인버스 ETF", ticker: "MSFD", sector: "미국 단일종목 인버스 ETF", price: 0, changePercent: 0, score: 30, reason: "마이크로소프트 하락 베팅형 · 초단기 헤지용"),
        PaperTradeStock(name: "GGLL 알파벳 2배 롱 ETF", ticker: "GGLL", sector: "미국 단일종목 레버리지 ETF", price: 0, changePercent: 0, score: 36, reason: "알파벳 2배 롱 · 광고/AI 모멘텀 고변동성"),
        PaperTradeStock(name: "GGLS 알파벳 인버스 ETF", ticker: "GGLS", sector: "미국 단일종목 인버스 ETF", price: 0, changePercent: 0, score: 30, reason: "알파벳 하락 베팅형 · 초단기 헤지용"),
        PaperTradeStock(name: "AMZU 아마존 2배 롱 ETF", ticker: "AMZU", sector: "미국 단일종목 레버리지 ETF", price: 0, changePercent: 0, score: 36, reason: "아마존 2배 롱 · 클라우드/소비 흐름 고변동성"),
        PaperTradeStock(name: "AMZD 아마존 인버스 ETF", ticker: "AMZD", sector: "미국 단일종목 인버스 ETF", price: 0, changePercent: 0, score: 30, reason: "아마존 하락 베팅형 · 초단기 헤지용"),
        PaperTradeStock(name: "SNDU 샌디스크 2배 롱 ETF", ticker: "SNDU", sector: "미국 단일종목 레버리지 ETF", price: 0, changePercent: 0, score: 34, reason: "샌디스크 2배 롱 · 메모리 사이클 고변동성"),
        PaperTradeStock(name: "SNDQ 샌디스크 2배 숏 ETF", ticker: "SNDQ", sector: "미국 단일종목 인버스 ETF", price: 0, changePercent: 0, score: 28, reason: "샌디스크 2배 숏 · 메모리 급락 헤지용 · 역분할 일정 주의"),
        PaperTradeStock(name: "SNSXX 미국 국채 머니마켓", ticker: "SNSXX", sector: "미국 머니마켓 펀드", price: 0, changePercent: 0, score: 55, reason: "현금성 대기자금 성격 · 주식 ETF와 다르게 가격 변동 제한적")
    ]

    static func == (lhs: PaperTradeStock, rhs: PaperTradeStock) -> Bool {
        lhs.normalizedTicker == rhs.normalizedTicker
    }

    init(result: ScannerResult) {
        self.name = result.name
        self.ticker = result.ticker
        self.sector = result.sectorCategoryName
        self.marketText = result.marketText
        self.price = result.currentPrice ?? 0
        self.priceText = result.formattedPrice
        self.changePercent = result.changePercent
        self.score = result.aiRankScore
        self.reason = Self.reasonText(from: result)
        self.confidence = Self.confidence(from: result)
        self.upsideProbability = Self.upsideProbability(from: result)
        self.searchText = Self.normalizedText("\(result.name) \(result.ticker) \(result.tickerCleanText) \(result.sectorCategoryName) \(result.marketText)")
        self.detailResult = result
    }

    init(row: AIScreeningRow) {
        let market = PaperMarketClassifier.marketText(for: row.ticker)
        self.name = StockDisplayName.localizedName(row.name, ticker: row.ticker, market: market)
        self.ticker = row.ticker
        self.sector = row.sector
        self.marketText = market
        self.price = Self.parseNumber(row.price) ?? 0
        self.priceText = row.price.isEmpty ? "-" : row.price
        self.changePercent = Self.parseNumber(row.changePct) ?? 0
        self.score = Int(row.aiScore)
        self.reason = row.reasons.isEmpty ? row.recommendation : row.reasons
        self.confidence = min(96, max(55, Int(row.aiScore)))
        self.upsideProbability = min(90, max(48, Int(row.aiScore * 0.82 + 12)))
        self.searchText = Self.normalizedText("\(row.name) \(row.ticker) \(row.sector) \(market)")
        self.detailResult = nil
    }

    init(name: String, ticker: String, sector: String, price: Double, changePercent: Double, score: Int, reason: String) {
        self.name = name
        self.ticker = ticker
        self.sector = sector
        self.marketText = "미장"
        self.price = price
        self.priceText = price > 0 ? PaperTradeCurrencyFormatter.price(price, ticker: ticker) : "실시간 조회"
        self.changePercent = changePercent
        self.score = score
        self.reason = reason
        self.confidence = min(92, max(55, score))
        self.upsideProbability = min(85, max(45, Int(Double(score) * 0.72 + 18)))
        self.searchText = Self.normalizedText("\(name) \(ticker) \(sector) 미국 미장 semiconductor 반도체 ETF 엔비디아 AMD 브로드컴 TSMC 마이크론 ASML 메모리 AI")
        self.detailResult = nil
    }

    func matches(_ query: String) -> Bool {
        let normalized = Self.normalizedText(query)
        guard !normalized.isEmpty else { return true }
        return searchText.contains(normalized)
            || normalized.split(separator: " ").allSatisfy { searchText.contains($0) }
    }

    func searchRank(_ query: String) -> Int {
        let normalized = Self.normalizedText(query)
        let normalizedName = Self.normalizedText(name)
        let normalizedTicker = Self.normalizedTicker(ticker)
        if normalizedName == normalized { return 100_000 + score }
        if normalizedTicker == normalized { return 98_000 + score }
        if normalizedName.hasPrefix(normalized) { return 94_000 + score }
        if normalizedTicker.hasPrefix(normalized) { return 92_000 + score }
        if normalizedName.contains(normalized) { return 88_000 + score }
        if searchText.contains(normalized) { return 70_000 + score }
        return score
    }

    var changeText: String {
        "\(changePercent >= 0 ? "+" : "")\(String(format: "%.2f", changePercent))%"
    }

    var changeTint: Color {
        if changePercent > 0 { return .red }
        if changePercent < 0 { return .blue }
        return .secondary
    }

    var oneLineReason: String {
        let cleaned = reason
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.isEmpty {
            return "AI 점수, 뉴스, 거래량, 섹터 흐름을 종합해 선별"
        }
        return cleaned
    }

    var confidenceText: String {
        "AI 신뢰도 \(confidence)%"
    }

    var upsideProbabilityText: String {
        "상승 확률 \(upsideProbability)%"
    }

    static func normalizedTicker(_ ticker: String) -> String {
        ticker
            .uppercased()
            .replacingOccurrences(of: ".KS", with: "")
            .replacingOccurrences(of: ".KQ", with: "")
            .replacingOccurrences(of: ".TO", with: "")
            .replacingOccurrences(of: " ", with: "")
    }

    private static func normalizedText(_ text: String) -> String {
        text
            .lowercased()
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: ".", with: "")
            .replacingOccurrences(of: "-", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func parseNumber(_ text: String) -> Double? {
        let cleaned = text
            .replacingOccurrences(of: ",", with: "")
            .replacingOccurrences(of: "%", with: "")
            .replacingOccurrences(of: "원", with: "")
            .replacingOccurrences(of: "$", with: "")
            .replacingOccurrences(of: "USD", with: "", options: .caseInsensitive)
            .replacingOccurrences(of: "CAD", with: "", options: .caseInsensitive)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return Double(cleaned)
    }

    private static func reasonText(from result: ScannerResult) -> String {
        let candidates = [
            result.mobileHomePickReason,
            result.whyTodayText,
            result.mobileAiExplain,
            result.aiReason,
            result.reasons
        ]
        return candidates
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty && $0 != "-" } ?? ""
    }

    private static func confidence(from result: ScannerResult) -> Int {
        if result.mobileNewsConfidence > 0 {
            return min(98, max(45, result.mobileNewsConfidence))
        }
        let base = max(result.aiRankScore, result.todayScore)
        let bonus = result.isAiPick ? 4 : 0
        return min(96, max(50, base + bonus))
    }

    private static func upsideProbability(from result: ScannerResult) -> Int {
        let base = Double(max(result.aiRankScore, result.todayScore))
        let newsText = "\(result.news) \(result.newsOneLine) \(result.mobileNewsImpactLabel) \(result.mobileNewsFocus)"
        let newsBoost = newsText.contains("호재") || newsText.contains("긍정") ? 5.0 : (newsText.contains("악재") || newsText.contains("부정") ? -8.0 : 0.0)
        let volumeBoost = min(8.0, max(0.0, result.volumeRatio - 1.0) * 4.0)
        let riskPenalty = result.risks.contains("악재") || result.hasCriticalNewsRisk ? 10.0 : 0.0
        return min(92, max(35, Int(base * 0.68 + 18.0 + newsBoost + volumeBoost - riskPenalty)))
    }
}

private enum PaperMarketClassifier {
    static func marketText(for ticker: String, fallback: String = "") -> String {
        let clean = ticker.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if clean.hasSuffix(".TO") || clean.hasSuffix(".V") || fallback == "캐나다" {
            return "캐나다"
        }
        if clean.hasSuffix(".KS") || clean.hasSuffix(".KQ") || clean.range(of: #"^[0-9]{6}$"#, options: .regularExpression) != nil || fallback == "국장" {
            return "국장"
        }
        return "미장"
    }

    static func identityKey(for ticker: String, fallback: String = "") -> String {
        "\(marketText(for: ticker, fallback: fallback)):\(PaperTradeStock.normalizedTicker(ticker))"
    }
}

private enum PaperTradeCurrencyFormatter {
    static func isUSTicker(_ ticker: String) -> Bool {
        PaperMarketClassifier.marketText(for: ticker) == "미장"
    }

    static func price(_ value: Double, ticker: String) -> String {
        if isUSTicker(ticker) {
            return "$" + value.formatted(.number.precision(.fractionLength(0...2)))
        }
        if ticker.hasSuffix(".TO") || ticker.hasSuffix(".V") {
            return value.formatted(.number.precision(.fractionLength(0...2))) + " CAD"
        }
        return value.formatted(.number.precision(.fractionLength(0))) + "원"
    }

    static func amount(_ value: Double, ticker: String) -> String {
        if isUSTicker(ticker) {
            let usd = "$" + value.formatted(.number.precision(.fractionLength(0...2)))
            if let krwText = CurrencyExchangeRateStore.krwText(forUSD: value) {
                return "\(usd) / 약 \(krwText)"
            }
            return usd
        }
        if ticker.hasSuffix(".TO") || ticker.hasSuffix(".V") {
            return value.formatted(.number.precision(.fractionLength(0...2))) + " CAD"
        }
        return value.formatted(.number.precision(.fractionLength(0))) + "원"
    }

    static func usdCashText(_ value: Double) -> String {
        "$" + value.formatted(.number.precision(.fractionLength(0...2)))
    }

    static func krwApproxText(_ value: Double, ticker: String) -> String? {
        if isUSTicker(ticker) {
            return CurrencyExchangeRateStore.krwText(forUSD: value).map { "약 \($0)" }
        }
        return nil
    }

    static func krwValue(_ value: Double, ticker: String) -> Double {
        if isUSTicker(ticker), let rate = CurrencyExchangeRateStore.usdKrwRate, rate > 0 {
            return value * rate
        }
        return value
    }

    static func krwValueForUSD(_ value: Double) -> Double {
        if let rate = CurrencyExchangeRateStore.usdKrwRate, rate > 0 {
            return value * rate
        }
        return 0
    }

    static func signedAmount(_ value: Double, ticker: String) -> String {
        "\(value >= 0 ? "+" : "-")\(amount(abs(value), ticker: ticker))"
    }
}

private extension PaperTradingAccountPayload {
    func normalizedForDisplay() -> PaperTradingAccountPayload {
        guard !positions.isEmpty else {
            return self
        }

        var merged: [String: PaperTradingPosition] = [:]
        for position in positions {
            let key = PaperMarketClassifier.identityKey(for: position.ticker)
            guard position.quantity > 0 else {
                continue
            }

            if let existing = merged[key] {
                let totalQuantity = existing.quantity + position.quantity
                guard totalQuantity > 0 else {
                    continue
                }
                let totalCost = existing.avgPrice * existing.quantity + position.avgPrice * position.quantity
                let avgPrice = totalCost / totalQuantity
                let currentPrice = position.currentPrice > 0 ? position.currentPrice : existing.currentPrice
                let marketValue = currentPrice * totalQuantity
                let profitLoss = (currentPrice - avgPrice) * totalQuantity
                merged[key] = PaperTradingPosition(
                    ticker: existing.ticker,
                    name: existing.name.isEmpty ? position.name : existing.name,
                    quantity: totalQuantity,
                    avgPrice: avgPrice,
                    currentPrice: currentPrice,
                    marketValue: marketValue,
                    profitLoss: profitLoss,
                    profitLossPct: avgPrice > 0 ? (currentPrice / avgPrice - 1) * 100 : 0
                )
            } else {
                let marketValue = position.currentPrice * position.quantity
                let profitLoss = (position.currentPrice - position.avgPrice) * position.quantity
                merged[key] = PaperTradingPosition(
                    ticker: position.ticker,
                    name: position.name,
                    quantity: position.quantity,
                    avgPrice: position.avgPrice,
                    currentPrice: position.currentPrice,
                    marketValue: marketValue,
                    profitLoss: profitLoss,
                    profitLossPct: position.avgPrice > 0 ? (position.currentPrice / position.avgPrice - 1) * 100 : 0
                )
            }
        }

        let normalizedPositions = merged.values.sorted {
            PaperMarketClassifier.identityKey(for: $0.ticker) < PaperMarketClassifier.identityKey(for: $1.ticker)
        }
        let normalizedTotalValue = cash + normalizedPositions.reduce(0) { partial, position in
            partial + PaperTradeCurrencyFormatter.krwValue(position.marketValue, ticker: position.ticker)
        }
        return PaperTradingAccountPayload(
            ok: ok,
            cash: cash,
            totalValue: normalizedTotalValue,
            positions: normalizedPositions,
            trades: trades,
            tradeCount: tradeCount,
            updatedAt: updatedAt,
            safetyNotice: safetyNotice
        )
    }

    func refreshedWithLiveQuotes(_ quotes: [String: LiveQuote]) -> PaperTradingAccountPayload {
        let refreshedPositions = positions.map { position in
            guard let quote = Self.quote(for: position, in: quotes), quote.price > 0 else {
                #if DEBUG
                print("[PaperTrading] Price Fallback ticker=\(position.ticker) reason=no-live-quote stored=\(position.currentPrice) avg=\(position.avgPrice)")
                #endif
                return position
            }

            let marketValue = quote.price * position.quantity
            let profitLoss = (quote.price - position.avgPrice) * position.quantity
            let invested = position.avgPrice * position.quantity
            return PaperTradingPosition(
                ticker: position.ticker,
                name: position.name,
                quantity: position.quantity,
                avgPrice: position.avgPrice,
                currentPrice: quote.price,
                marketValue: marketValue,
                profitLoss: profitLoss,
                profitLossPct: invested > 0 ? profitLoss / invested * 100 : 0
            )
        }

        let refreshedTotal = cash + refreshedPositions.reduce(0) { partial, position in
            partial + PaperTradeCurrencyFormatter.krwValue(position.marketValue, ticker: position.ticker)
        }

        return PaperTradingAccountPayload(
            ok: ok,
            cash: cash,
            totalValue: refreshedTotal,
            positions: refreshedPositions,
            trades: trades,
            updatedAt: ISO8601DateFormatter().string(from: Date()),
            safetyNotice: safetyNotice
        )
    }

    private static func quote(for position: PaperTradingPosition, in quotes: [String: LiveQuote]) -> LiveQuote? {
        let keys = [
            PaperTradeStock.normalizedTicker(position.ticker),
            PaperMarketClassifier.identityKey(for: position.ticker),
            position.ticker.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        ].uniqued()
        return keys.compactMap { quotes[$0] }.first { $0.price > 0 }
    }
}

private enum PaperTradeRecentStore {
    private static let key = "paperTradeRecentTickers.v1"

    static func load() -> [String] {
        UserDefaults.standard.stringArray(forKey: key) ?? []
    }

    static func record(_ ticker: String) -> [String] {
        let normalized = PaperTradeStock.normalizedTicker(ticker)
        var values = load().filter { PaperTradeStock.normalizedTicker($0) != normalized }
        values.insert(normalized, at: 0)
        values = Array(values.prefix(10))
        UserDefaults.standard.set(values, forKey: key)
        return values
    }
}

private enum PaperTradeFavoriteStore {
    private static let key = "paperTradeFavoriteTickers.v1"

    static func load() -> [String] {
        UserDefaults.standard.stringArray(forKey: key) ?? []
    }

    static func toggle(_ ticker: String) -> [String] {
        let normalized = PaperTradeStock.normalizedTicker(ticker)
        var values = load()
        if values.contains(normalized) {
            values.removeAll { $0 == normalized }
        } else {
            values.insert(normalized, at: 0)
        }
        values = Array(values.prefix(30))
        UserDefaults.standard.set(values, forKey: key)
        return values
    }
}

private struct PaperAITodayRecommendationSection: View {
    let stocks: [PaperTradeStock]
    let selectedTicker: String?
    let favoriteTickers: [String]
    let selectAction: (PaperTradeStock) -> Void
    let paperTradeAction: (PaperTradeStock) -> Void
    let favoriteAction: (PaperTradeStock) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .firstTextBaseline) {
                Text("🔥 오늘의 AI 추천 종목")
                    .font(.subheadline.bold())
                Spacer(minLength: 8)
                Text("\(stocks.count)개")
                    .font(.caption2.monospacedDigit().bold())
                    .foregroundStyle(.mint)
            }

            Text("최신 AI 추천 데이터 기준입니다. 상승 확률은 예측값이며 실제 수익을 보장하지 않습니다.")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            LazyVStack(spacing: 8) {
                ForEach(Array(stocks.enumerated()), id: \.element.id) { index, stock in
                    PaperAIRecommendationCard(
                        rank: index + 1,
                        stock: stock,
                        isSelected: selectedTicker.map { PaperMarketClassifier.identityKey(for: $0) } == PaperMarketClassifier.identityKey(for: stock.ticker, fallback: stock.marketText),
                        isFavorite: favoriteTickers.contains(stock.normalizedTicker),
                        selectAction: { selectAction(stock) },
                        paperTradeAction: { paperTradeAction(stock) },
                        favoriteAction: { favoriteAction(stock) }
                    )
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.mint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.mint.opacity(0.30), lineWidth: 1))
    }
}

private struct PaperAIRecommendationCard: View {
    let rank: Int
    let stock: PaperTradeStock
    let isSelected: Bool
    let isFavorite: Bool
    let selectAction: () -> Void
    let paperTradeAction: () -> Void
    let favoriteAction: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                Button(action: selectAction) {
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text("\(rank)")
                                .font(.caption.monospacedDigit().bold())
                                .foregroundStyle(.mint)
                            LocalizedStockNameView(
                                name: stock.name,
                                ticker: stock.ticker,
                                market: stock.marketText,
                                primaryFont: .caption.bold(),
                                secondaryFont: .caption2.weight(.medium)
                            )
                            Spacer(minLength: 6)
                            Text("\(stock.score)점")
                                .font(.caption.monospacedDigit().bold())
                                .foregroundStyle(stock.score >= 88 ? .mint : .orange)
                        }

                        Text("\(stock.ticker) · \(stock.marketText) · \(stock.sector.isEmpty ? "섹터 없음" : stock.sector)")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)

                        Text(stock.oneLineReason)
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .buttonStyle(.plain)
                .layoutPriority(1)

                VStack(spacing: 5) {
                    Button(action: favoriteAction) {
                        Image(systemName: isFavorite ? "star.fill" : "star")
                            .font(.caption.bold())
                            .foregroundStyle(isFavorite ? .yellow : .secondary)
                            .frame(width: 28, height: 28)
                    }
                    .buttonStyle(.plain)

                    if isSelected {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption.bold())
                            .foregroundStyle(.mint)
                    }
                }
            }

            HStack(spacing: 6) {
                PaperCompactBadge(text: stock.confidenceText, tint: .mint)
                PaperCompactBadge(text: stock.upsideProbabilityText, tint: .orange)
                PaperCompactBadge(text: stock.changeText, tint: stock.changeTint)
            }

            HStack(spacing: 8) {
                if let result = stock.detailResult {
                    NavigationLink {
                        ResultDetailView(
                            result: result,
                            isFavorite: isFavorite,
                            recommendationDate: nil,
                            toggleFavorite: favoriteAction
                        )
                    } label: {
                        Label("상세", systemImage: "doc.text.magnifyingglass")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .font(.caption.bold())
                }

                Button(action: paperTradeAction) {
                    Label("모의투자", systemImage: "cart.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .font(.caption.bold())
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(isSelected ? Color.mint.opacity(0.15) : AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(isSelected ? Color.mint.opacity(0.65) : AppColors.border, lineWidth: 1))
    }
}

private struct PaperCompactBadge: View {
    let text: String
    let tint: Color

    var body: some View {
        Text(text)
            .font(.caption2.monospacedDigit().bold())
            .foregroundStyle(tint)
            .lineLimit(1)
            .minimumScaleFactor(0.72)
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(tint.opacity(0.12), in: Capsule())
    }
}

private struct PaperTradingPlatformSection: View {
    let market: PaperTradingMarket
    let allStocks: [PaperTradeStock]
    let selectedTicker: String?
    let favoriteTickers: [String]
    let selectAction: (PaperTradeStock) -> Void
    let favoriteAction: (PaperTradeStock) -> Void

    private var semiconductorStocks: [PaperTradeStock] {
        pick(["NVDA", "AMD", "AVGO", "TSM", "ASML", "MU", "SNDK", "WDC", "AMAT", "LRCX", "KLAC", "MRVL", "ARM", "SMCI"])
    }

    private var semiconductorETFs: [PaperTradeStock] {
        pick(["SOXX", "SMH", "SOXQ", "XSD", "FTXL", "PSI"])
    }

    private var popularETFs: [PaperTradeStock] {
        pick(["QQQ", "QQQM", "QNDX", "SPY", "VOO", "IVV", "SPLG", "DIA", "IWM"])
    }

    private var leveragedETFs: [PaperTradeStock] {
        pick(["SOXL", "SOXS", "TQQQ", "SQQQ", "TSLL", "TSLS", "TSLQ", "NVDL", "NVDU", "NVDQ", "SNDU", "SNDQ", "AAPU", "AAPD", "MSFU", "MSFD", "GGLL", "GGLS", "AMZU", "AMZD"])
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("\(market.displayTitle) 종목", systemImage: market.iconName)
                    .font(.subheadline.bold())
                Spacer()
                Text("\(allStocks.count)개")
                    .font(.caption2.bold())
                    .foregroundStyle(.secondary)
            }

            if allStocks.isEmpty {
                Text("\(market.displayTitle) 종목 데이터가 없습니다. 종목 기준 목록은 삭제하지 않고 다음 데이터 업데이트를 기다립니다.")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            } else if market == .us {
                PaperStockShelf(
                    title: "반도체 핵심 종목",
                    stocks: semiconductorStocks,
                    selectedTicker: selectedTicker,
                    favoriteTickers: favoriteTickers,
                    selectAction: selectAction,
                    favoriteAction: favoriteAction
                )
                PaperStockShelf(
                    title: "반도체 ETF",
                    stocks: semiconductorETFs,
                    selectedTicker: selectedTicker,
                    favoriteTickers: favoriteTickers,
                    selectAction: selectAction,
                    favoriteAction: favoriteAction
                )
                PaperStockShelf(
                    title: "인기 ETF",
                    stocks: popularETFs,
                    selectedTicker: selectedTicker,
                    favoriteTickers: favoriteTickers,
                    selectAction: selectAction,
                    favoriteAction: favoriteAction
                )
                PaperStockShelf(
                    title: "레버리지 / 인버스",
                    stocks: leveragedETFs,
                    selectedTicker: selectedTicker,
                    favoriteTickers: favoriteTickers,
                    selectAction: selectAction,
                    favoriteAction: favoriteAction
                )
                PaperStockShelf(
                    title: "미국 주식 전체",
                    stocks: allStocks,
                    selectedTicker: selectedTicker,
                    favoriteTickers: favoriteTickers,
                    selectAction: selectAction,
                    favoriteAction: favoriteAction
                )
            } else {
                PaperStockShelf(
                    title: "한국 주식 전체",
                    stocks: allStocks,
                    selectedTicker: selectedTicker,
                    favoriteTickers: favoriteTickers,
                    selectAction: selectAction,
                    favoriteAction: favoriteAction
                )
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private func pick(_ tickers: [String]) -> [PaperTradeStock] {
        tickers.compactMap { ticker in
            allStocks.first { $0.normalizedTicker == PaperTradeStock.normalizedTicker(ticker) }
        }
    }
}

private struct PaperStockShelf: View {
    let title: String
    let stocks: [PaperTradeStock]
    let selectedTicker: String?
    let favoriteTickers: [String]
    let selectAction: (PaperTradeStock) -> Void
    let favoriteAction: (PaperTradeStock) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            LazyVStack(spacing: 7) {
                ForEach(stocks) { stock in
                    PaperStockSearchCard(
                        stock: stock,
                        isSelected: selectedTicker.map { PaperMarketClassifier.identityKey(for: $0) } == PaperMarketClassifier.identityKey(for: stock.ticker, fallback: stock.marketText),
                        isFavorite: favoriteTickers.contains(stock.normalizedTicker),
                        selectAction: { selectAction(stock) },
                        favoriteAction: { favoriteAction(stock) }
                    )
                }
            }
        }
    }
}

private struct PaperStockSearchCard: View {
    let stock: PaperTradeStock
    let isSelected: Bool
    let isFavorite: Bool
    let selectAction: () -> Void
    let favoriteAction: () -> Void

    var body: some View {
        Button(action: selectAction) {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 4) {
                    LocalizedStockNameView(
                        name: stock.name,
                        ticker: stock.ticker,
                        market: stock.marketText,
                        primaryFont: .caption.bold(),
                        secondaryFont: .caption2.weight(.medium)
                    )
                    Text("\(stock.ticker) · \(stock.marketText) · \(stock.sector.isEmpty ? "섹터 없음" : stock.sector)")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 6) {
                        Text(stock.priceText)
                            .font(.caption.monospacedDigit().bold())
                            .lineLimit(1)
                            .minimumScaleFactor(0.72)
                        Text(stock.changeText)
                            .font(.caption2.monospacedDigit().bold())
                            .foregroundStyle(stock.changeTint)
                    }
                }
                .layoutPriority(1)

                Spacer(minLength: 6)

                Button(action: favoriteAction) {
                    Image(systemName: isFavorite ? "star.fill" : "star")
                        .font(.caption.bold())
                        .foregroundStyle(isFavorite ? .yellow : .secondary)
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.plain)

                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.caption.bold())
                        .foregroundStyle(.mint)
                        .padding(.top, 5)
                }
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(isSelected ? Color.mint.opacity(0.14) : AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(isSelected ? Color.mint.opacity(0.7) : AppColors.border, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

private struct PaperSelectedStockPanel: View {
    let stock: PaperTradeStock
    let isFavorite: Bool
    let toggleFavorite: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 3) {
                    LocalizedStockNameView(
                        name: stock.name,
                        ticker: stock.ticker,
                        market: stock.marketText,
                        primaryFont: .subheadline.bold(),
                        secondaryFont: .caption2.weight(.medium)
                    )
                }
                Spacer(minLength: 8)
                Button(action: toggleFavorite) {
                    Image(systemName: isFavorite ? "star.fill" : "star")
                        .foregroundStyle(isFavorite ? .yellow : .secondary)
                }
                .buttonStyle(.plain)
            }
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("현재가")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                    Text(stock.priceText)
                        .font(.headline.monospacedDigit().bold())
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text("오늘 등락률")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                    Text(stock.changeText)
                        .font(.headline.monospacedDigit().bold())
                        .foregroundStyle(stock.changeTint)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.mint.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.mint.opacity(0.35), lineWidth: 1))
    }
}

private struct PaperTradeEmptySelectionCard: View {
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "hand.tap.fill")
                .font(.title3.bold())
                .foregroundStyle(.mint)
                .frame(width: 32, height: 32)
                .background(Color.mint.opacity(0.12), in: Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text("종목 선택 후 바로 매매")
                    .font(.caption.bold())
                Text("검색 결과나 추천 종목을 누르면 이 위치에 매수/매도 패널이 바로 열립니다.")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.mint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.mint.opacity(0.22), lineWidth: 1))
    }
}

private struct PaperTradeOrderPanel: View {
    let stock: PaperTradeStock
    let isFavorite: Bool
    let heldQuantity: Double
    let availableCashText: String
    @Binding var orderQuantity: String
    let orderAmountText: String
    let estimatedRemainingText: String
    let isRunning: Bool
    let canBuy: Bool
    let canSell: Bool
    let toggleFavorite: () -> Void
    let buyAction: () -> Void
    let sellAction: () -> Void
    let setQuantityPercent: (Double) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 3) {
                    LocalizedStockNameView(
                        name: stock.name,
                        ticker: stock.ticker,
                        market: stock.marketText,
                        primaryFont: .subheadline.bold(),
                        secondaryFont: .caption2.weight(.medium)
                    )
                    Text(stock.sector)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                }
                Spacer(minLength: 8)
                Button(action: toggleFavorite) {
                    Image(systemName: isFavorite ? "star.fill" : "star")
                        .foregroundStyle(isFavorite ? .yellow : .secondary)
                }
                .buttonStyle(.plain)
            }

            LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)], alignment: .leading, spacing: 8) {
                PaperTradeMetricBox(title: "현재 가격", value: stock.priceText, tint: .mint)
                PaperTradeMetricBox(title: "보유 수량", value: "\(formatPanelQuantity(heldQuantity))주", tint: heldQuantity > 0 ? .orange : .secondary)
                PaperTradeMetricBox(title: "매수 가능 금액", value: availableCashText, tint: .cyan)
                PaperTradeMetricBox(title: "주문 금액", value: orderAmountText, tint: .primary)
            }

            HStack(spacing: 8) {
                ScreeningTextField(title: "주문 수량", text: $orderQuantity, keyboard: .decimalPad)
                VStack(alignment: .leading, spacing: 2) {
                    Text("주문 금액 \(orderAmountText)")
                        .font(.caption.bold())
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                    Text("\(estimatedRemainingText) · 수수료 0원")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.68)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 56), spacing: 6)], alignment: .leading, spacing: 6) {
                Button("0%") { orderQuantity = "" }
                    .buttonStyle(.bordered)
                ForEach([10, 20, 40, 50], id: \.self) { percent in
                    Button("\(percent)%") { setQuantityPercent(Double(percent) / 100.0) }
                        .buttonStyle(.bordered)
                }
                Button("전량") { setQuantityPercent(1.0) }
                    .buttonStyle(.borderedProminent)
            }
            .font(.caption.bold())
            .disabled(isRunning || !canBuy)

            HStack(spacing: 8) {
                Button(action: buyAction) {
                    Label("매수", systemImage: "cart.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(isRunning || !canBuy)

                Button(action: sellAction) {
                    Label("매도", systemImage: "arrow.up.circle.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .tint(.orange)
                .disabled(isRunning || !canSell)
            }
            .font(.caption.bold())
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.mint.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.mint.opacity(0.35), lineWidth: 1))
    }

    private func formatPanelQuantity(_ value: Double) -> String {
        value.rounded() == value ? "\(Int(value))" : String(format: "%.2f", value)
    }
}

private struct PaperTradeMetricBox: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.monospacedDigit().bold())
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.62)
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct PaperStickyTradeBar: View {
    let stock: PaperTradeStock
    let quantityText: String
    let orderAmountText: String
    let canBuy: Bool
    let canSell: Bool
    let buyAction: () -> Void
    let sellAction: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(stock.ticker) · \(quantityText.isEmpty ? "수량 -" : "\(quantityText)주")")
                        .font(.caption.bold())
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                    Text(orderAmountText)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.68)
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                Button(action: buyAction) {
                    Text("매수")
                        .font(.caption.bold())
                        .frame(width: 68, height: 36)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canBuy)

                Button(action: sellAction) {
                    Text("매도")
                        .font(.caption.bold())
                        .frame(width: 68, height: 36)
                }
                .buttonStyle(.bordered)
                .tint(.orange)
                .disabled(!canSell)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial)
        .overlay(Rectangle().fill(AppColors.border).frame(height: 1), alignment: .top)
    }
}

private struct AIScreeningRowView: View {
    let row: AIScreeningRow
    var isSelected = false
    var selectAction: (() -> Void)? = nil

    var body: some View {
        Button {
            selectAction?()
        } label: {
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline) {
                    Text(row.name)
                        .font(.caption.bold())
                        .lineLimit(1)
                        .layoutPriority(1)
                    Text(row.ticker)
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                    Spacer()
                    if isSelected {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(.mint)
                            .font(.caption)
                    }
                    Text("\(Int(row.aiScore))")
                        .font(.caption.monospacedDigit().bold())
                        .foregroundStyle(row.aiScore >= 75 ? .mint : .orange)
                }
                Text("\(row.recommendation) · \(row.reasons)")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(isSelected ? Color.mint.opacity(0.14) : AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(isSelected ? Color.mint.opacity(0.7) : AppColors.border, lineWidth: 1))
    }
}

private struct ScreeningMetricBox: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.bold())
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .padding(9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct WatchlistHomeSection: View {
    let favorites: [ScannerResult]
    let positionSummary: PortfolioRiskSummary
    let favoriteTickers: Set<String>
    let newAiPickTickers: Set<String>
    let aiPickDates: [String: String]
    let positionEvaluations: [String: PositionEvaluation]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "관심", subtitle: "관심 종목, 보유 종목, 알림")
            PortfolioRiskCard(summary: positionSummary)
            if favorites.isEmpty {
                EmptySearchView(hasSearchText: false, canResetFilters: false) {}
            } else {
                MainResultListSection(
                    displayedResults: Array(favorites.prefix(60)),
                    favoriteTickers: favoriteTickers,
                    newAiPickTickers: newAiPickTickers,
                    aiPickDates: aiPickDates,
                    positionEvaluations: positionEvaluations,
                    toggleFavorite: toggleFavorite
                )
            }
        }
    }
}

private struct MarketHomeSection: View {
    @State private var selectedMoverDetail: MarketMoverDetailSelection?

    let results: [ScannerResult]
    @Binding var selectedMarket: MoversMarket
    @Binding var selectedCategory: MoversCategory
    @Binding var selectedSort: MoversSort
    @Binding var selectedExchange: MoversExchange
    @Binding var selectedStockType: MoversStockType
    @Binding var selectedSector: MoversSector
    let sectorRanks: [SectorInflowRank]
    let marketSections: [MarketStrengthSection]
    let flowRadar: MoneyFlowRadarData
    let topGainers: [ScannerResult]
    let topLosers: [ScannerResult]
    let sectorSize: SectorInflowCardSize
    let setSectorSize: (SectorInflowCardSize) -> Void
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    private var moverItems: [MarketMoverItem] {
        let rankedItems = results
            .filter { selectedMarket.matches($0) }
            .filter { selectedExchange.matches($0) }
            .filter { selectedStockType.matches($0) }
            .filter { selectedSector.matches($0) }
            .map { MarketMoverItem(result: $0, isFavorite: favoriteTickers.contains($0.ticker)) }
            .filter { selectedCategory.matches($0) }

        return rankedItems.sorted { lhs, rhs in
            if selectedCategory == .losers {
                return lhs.loserSortValue(sort: selectedSort) < rhs.loserSortValue(sort: selectedSort)
            }
            let left = lhs.sortValue(category: selectedCategory, sort: selectedSort)
            let right = rhs.sortValue(category: selectedCategory, sort: selectedSort)
            if left == right {
                return lhs.aiHotScore > rhs.aiHotScore
            }
            return left > right
        }
        .prefix(40)
        .map { $0 }
    }

    private var topSummary: String {
        guard let first = moverItems.first else {
            return "조건에 맞는 시장 동향 데이터가 없습니다."
        }
        return "\(selectedMarket.shortTitle) \(selectedCategory.title) 1위 · \(first.result.name) \(first.result.changeBadgeText) · AI \(first.aiHotScore)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "Market Movers", subtitle: "국장/미장/캐나다 분리 · 급등락 · 거래량 · 거래대금 · AI HOT")

            Picker("시장 선택", selection: $selectedMarket) {
                ForEach(MoversMarket.allCases) { market in
                    Text(market.title).tag(market)
                }
            }
            .pickerStyle(.segmented)
            .onChange(of: selectedMarket) { _, market in
                if !market.allowedExchanges.contains(selectedExchange) {
                    selectedExchange = .all
                }
            }

            MarketMoverHeroCard(summary: topSummary, items: moverItems)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(MoversCategory.allCases) { category in
                        MarketMoverChip(
                            title: category.title,
                            systemImage: category.systemImage,
                            isSelected: selectedCategory == category,
                            tint: category.tint
                        ) {
                            selectedCategory = category
                            selectedSort = category.defaultSort
                        }
                    }
                }
                .padding(.vertical, 2)
            }

            HStack(spacing: 8) {
                MarketMoverMenu(title: selectedExchange.title, systemImage: "building.columns.fill") {
                    ForEach(selectedMarket.allowedExchanges) { exchange in
                        Button(exchange.title) { selectedExchange = exchange }
                    }
                }

                MarketMoverMenu(title: selectedStockType.title, systemImage: "square.stack.3d.up.fill") {
                    ForEach(MoversStockType.allCases) { type in
                        Button(type.title) { selectedStockType = type }
                    }
                }

                MarketMoverMenu(title: selectedSector.title, systemImage: "tag.fill") {
                    ForEach(MoversSector.allCases) { sector in
                        Button(sector.title) { selectedSector = sector }
                    }
                }
            }

            Picker("정렬", selection: $selectedSort) {
                ForEach(MoversSort.allCases) { sort in
                    Text(sort.title).tag(sort)
                }
            }
            .pickerStyle(.segmented)

            if moverItems.isEmpty {
                EmptySearchView(hasSearchText: false, canResetFilters: true) {
                    selectedExchange = .all
                    selectedStockType = .all
                    selectedSector = .all
                    selectedSort = selectedCategory.defaultSort
                }
            } else {
                LazyVStack(spacing: 9) {
                    ForEach(Array(moverItems.enumerated()), id: \.element.id) { index, item in
                        Button {
                            selectedMoverDetail = MarketMoverDetailSelection(
                                result: item.result,
                                isFavorite: favoriteTickers.contains(item.result.ticker),
                                recommendationDate: aiPickDates[item.result.ticker]
                            )
                        } label: {
                            MarketMoverRow(rank: index + 1, item: item, category: selectedCategory)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("시장 요약")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                SectorInflowCard(ranks: sectorRanks, size: sectorSize, setSize: setSectorSize)
                MarketPulseSummaryCard(sections: marketSections, flowRadar: flowRadar)
                DailyMoverSummaryCard(gainers: topGainers, losers: topLosers)
            }
        }
        .navigationDestination(item: $selectedMoverDetail) { selection in
            ResultDetailView(
                result: selection.result,
                isFavorite: selection.isFavorite,
                recommendationDate: selection.recommendationDate
            ) {
                toggleFavorite(selection.result)
            }
        }
    }
}

private struct MarketMoverDetailSelection: Identifiable, Hashable {
    let result: ScannerResult
    let isFavorite: Bool
    let recommendationDate: String?

    var id: String { result.ticker }

    static func == (lhs: MarketMoverDetailSelection, rhs: MarketMoverDetailSelection) -> Bool {
        lhs.id == rhs.id
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}

private enum MoversMarket: String, CaseIterable, Identifiable {
    case korea
    case us
    case canada

    var id: String { rawValue }
    var title: String {
        switch self {
        case .korea: return "🇰🇷 한국"
        case .us: return "🇺🇸 미국"
        case .canada: return "🇨🇦 캐나다"
        }
    }
    var shortTitle: String {
        switch self {
        case .korea: return "국장"
        case .us: return "미장"
        case .canada: return "캐나다"
        }
    }
    var allowedExchanges: [MoversExchange] {
        switch self {
        case .korea: return [.all, .kospi, .kosdaq]
        case .us: return [.all, .nasdaq, .nyse]
        case .canada: return [.all, .tsx, .tsxv]
        }
    }

    func matches(_ result: ScannerResult) -> Bool {
        switch self {
        case .korea: return result.marketText == "국장"
        case .us: return result.marketText == "미장"
        case .canada: return result.marketText == "캐나다"
        }
    }
}

private enum MoversCategory: String, CaseIterable, Identifiable {
    case gainers
    case losers
    case volumeSurge
    case tradeValue
    case aiHot

    var id: String { rawValue }
    var title: String {
        switch self {
        case .gainers: return "급상승"
        case .losers: return "급하락"
        case .volumeSurge: return "거래량 급증"
        case .tradeValue: return "거래대금 상위"
        case .aiHot: return "AI HOT"
        }
    }
    var systemImage: String {
        switch self {
        case .gainers: return "arrow.up.right.circle.fill"
        case .losers: return "arrow.down.right.circle.fill"
        case .volumeSurge: return "waveform.path.ecg"
        case .tradeValue: return "banknote.fill"
        case .aiHot: return "sparkles"
        }
    }
    var tint: Color {
        switch self {
        case .gainers: return .red
        case .losers: return .blue
        case .volumeSurge: return .orange
        case .tradeValue: return .mint
        case .aiHot: return .purple
        }
    }
    var defaultSort: MoversSort {
        switch self {
        case .gainers, .losers: return .change
        case .volumeSurge: return .volume
        case .tradeValue: return .tradeValue
        case .aiHot: return .aiScore
        }
    }

    func matches(_ item: MarketMoverItem) -> Bool {
        switch self {
        case .gainers: return item.result.changePercent > 0
        case .losers: return item.result.changePercent < 0
        case .volumeSurge: return item.result.volumeRatio >= 1.15
        case .tradeValue: return item.result.tradeValueForRanking > 0
        case .aiHot: return item.aiHotScore >= 45
        }
    }
}

private enum MoversSort: String, CaseIterable, Identifiable {
    case change
    case volume
    case tradeValue
    case marketCap
    case aiScore

    var id: String { rawValue }
    var title: String {
        switch self {
        case .change: return "등락률"
        case .volume: return "거래량"
        case .tradeValue: return "거래대금"
        case .marketCap: return "시총"
        case .aiScore: return "AI"
        }
    }
}

private enum MoversExchange: String, CaseIterable, Identifiable {
    case all
    case kospi
    case kosdaq
    case nasdaq
    case nyse
    case tsx
    case tsxv

    var id: String { rawValue }
    var title: String {
        switch self {
        case .all: return "전체 시장"
        case .kospi: return "코스피"
        case .kosdaq: return "코스닥"
        case .nasdaq: return "나스닥"
        case .nyse: return "NYSE"
        case .tsx: return "TSX"
        case .tsxv: return "TSXV"
        }
    }

    func matches(_ result: ScannerResult) -> Bool {
        let ticker = result.ticker.uppercased()
        let market = result.market.uppercased()
        let sector = result.sector.uppercased()
        switch self {
        case .all:
            return true
        case .kospi:
            return ticker.hasSuffix(".KS") || market.contains("KOSPI") || sector.contains("코스피")
        case .kosdaq:
            return ticker.hasSuffix(".KQ") || market.contains("KOSDAQ") || sector.contains("코스닥")
        case .nasdaq:
            return !ticker.hasSuffix(".TO") && !ticker.hasSuffix(".KS") && !ticker.hasSuffix(".KQ") && (market.contains("NASDAQ") || result.marketText == "미장")
        case .nyse:
            return market.contains("NYSE")
        case .tsx:
            return ticker.hasSuffix(".TO") || market.contains("TSX") || market.contains("TORONTO")
        case .tsxv:
            return ticker.hasSuffix(".V") || market.contains("TSXV") || market.contains("VENTURE")
        }
    }
}

private enum MoversStockType: String, CaseIterable, Identifiable {
    case all
    case common
    case etf

    var id: String { rawValue }
    var title: String {
        switch self {
        case .all: return "전체 유형"
        case .common: return "일반주"
        case .etf: return "ETF"
        }
    }

    func matches(_ result: ScannerResult) -> Bool {
        switch self {
        case .all:
            return true
        case .common:
            return !isETF(result)
        case .etf:
            return isETF(result)
        }
    }

    private func isETF(_ result: ScannerResult) -> Bool {
        let merged = "\(result.name) \(result.ticker) \(result.sector) \(result.dividendGroup)".uppercased()
        return merged.contains("ETF") || result.etfHoldingsCount > 0 || result.etfNav > 0
    }
}

private enum MoversSector: String, CaseIterable, Identifiable {
    case all
    case ai
    case semiconductor
    case dividend
    case space
    case bio
    case finance
    case ev
    case nuclear
    case defense

    var id: String { rawValue }
    var title: String {
        switch self {
        case .all: return "전체 섹터"
        case .ai: return "AI"
        case .semiconductor: return "반도체"
        case .dividend: return "배당"
        case .space: return "우주"
        case .bio: return "바이오"
        case .finance: return "금융"
        case .ev: return "전기차"
        case .nuclear: return "원전"
        case .defense: return "방산"
        }
    }

    private var keywords: [String] {
        switch self {
        case .all: return []
        case .ai: return ["AI", "인공지능", "소프트웨어", "반도체", "데이터센터"]
        case .semiconductor: return ["반도체", "SEMICONDUCTOR", "CHIP", "AI칩", "HBM"]
        case .dividend: return ["배당", "DIVIDEND", "월배당", "고배당"]
        case .space: return ["우주", "SPACE", "위성", "로켓"]
        case .bio: return ["바이오", "BIO", "제약", "헬스케어", "HEALTH"]
        case .finance: return ["금융", "은행", "FINANCE", "BANK", "보험"]
        case .ev: return ["전기차", "EV", "배터리", "2차전지", "자동차"]
        case .nuclear: return ["원전", "NUCLEAR", "우라늄", "전력"]
        case .defense: return ["방산", "DEFENSE", "항공", "드론"]
        }
    }

    func matches(_ result: ScannerResult) -> Bool {
        guard self != .all else { return true }
        let merged = "\(result.name) \(result.ticker) \(result.sector) \(result.sectorCategoryName) \(result.themeKey) \(result.news) \(result.headlines)".uppercased()
        return keywords.map { $0.uppercased() }.contains { merged.contains($0) }
    }
}

private struct MarketMoverItem: Identifiable {
    let result: ScannerResult
    let isFavorite: Bool

    var id: String { result.ticker }
    var newsCount: Int {
        let merged = "\(result.headlines)\n\(result.news)\n\(result.newsOneLine)"
        let parts = merged
            .components(separatedBy: CharacterSet(charactersIn: "\n|•·"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && $0 != "-" }
        return max(parts.isEmpty ? 0 : 1, min(9, parts.count))
    }
    var volumeMultipleText: String { "\(String(format: "%.1f", max(result.volumeRatio, 0)))x" }
    var currentVolumeText: String { "현재 \(volumeMultipleText)" }
    var averageVolumeText: String { "20일 평균 1.0x 기준" }
    private var isCanadaListing: Bool {
        let ticker = result.ticker.uppercased()
        return result.marketText == "캐나다" || ticker.hasSuffix(".TO") || ticker.hasSuffix(".V")
    }
    private var isUSListing: Bool { result.marketText == "미장" }
    var tradeValueText: String {
        let value = result.tradeValueForRanking
        if isCanadaListing {
            if value >= 1_000_000_000 {
                return "C$\(String(format: "%.1f", value / 1_000_000_000))B"
            }
            return "C$\(String(format: "%.0f", value / 1_000_000))M"
        }
        if isUSListing {
            if value >= 1_000_000_000 {
                return "$\(String(format: "%.1f", value / 1_000_000_000))B"
            }
            return "$\(String(format: "%.0f", value / 1_000_000))M"
        }
        return "\(Int(value / 100_000_000).formatted())억"
    }
    var marketCapProxy: Double { result.tradeValueForRanking * 20 }
    var marketCapText: String {
        if isCanadaListing {
            return "C$\(String(format: "%.1f", marketCapProxy / 1_000_000_000))B"
        }
        if isUSListing {
            return "$\(String(format: "%.1f", marketCapProxy / 1_000_000_000))B"
        }
        return "\(Int(marketCapProxy / 100_000_000).formatted())억"
    }
    var foreignNetText: String { flowText(label: "외국인", value: result.foreignNet) }
    var institutionNetText: String { flowText(label: "기관", value: result.institutionNet) }
    var moneyFlowAnalysis: String {
        let net = result.foreignNet + result.institutionNet
        if net > 0 && result.volumeRatio >= 1.2 {
            return "외국인/기관 수급과 거래량이 같이 붙어 실제 자금 유입 가능성이 높습니다."
        }
        if result.tradeValueRatioForRanking >= 1.5 {
            return "평소 대비 거래대금이 커져 시장 관심이 집중되는 구간입니다."
        }
        if net < 0 {
            return "수급 이탈이 있어 거래대금 상위라도 추격 매수는 확인이 필요합니다."
        }
        return "거래대금은 높지만 주도 수급은 추가 확인이 필요합니다."
    }
    var aiHotScore: Int {
        var score = 18
        score += min(18, Int(abs(result.changePercent) * 2.4))
        score += min(18, Int(max(result.volumeRatio, 0) * 4.0))
        score += min(16, Int(log10(max(result.tradeValueForRanking, 1)) * 2.4))
        score += min(12, max(0, result.analystNewsScore - 50) / 3)
        score += min(10, max(0, result.analystFlowScore - 50) / 4)
        score += min(8, max(0, result.analystSectorScore - 50) / 5)
        score += min(8, max(0, result.analystTechnicalScore - 50) / 5)
        score += result.isAiPick ? 10 : 0
        score += isFavorite ? 8 : 0
        score += result.marketText == "미장" && result.volumeRatio >= 2 ? 5 : 0
        return min(100, max(1, score))
    }
    var aiGrade: String {
        if aiHotScore >= 88 { return "S" }
        if aiHotScore >= 74 { return "A" }
        if aiHotScore >= 60 { return "B" }
        return "C"
    }
    var aiRiseReason: String {
        NewsDigest.oneLine(
            result.whyTodayText,
            result.simpleReason,
            result.mobileNewsImpactSummary,
            result.newsOneLine,
            fallback: "가격, 거래량, 뉴스 점수가 동시에 개선된 종목입니다."
        )
    }
    var aiContinuationText: String {
        let value = min(92, max(28, 42 + Int(result.changePercent * 2) + Int(result.volumeRatio * 6) + (result.mobileNewsImpactScore / 5)))
        if result.isChaseRiskForAi || result.changePercent >= 9 {
            return "지속 가능성 \(value)% · 단기 과열 확인 필요"
        }
        return "지속 가능성 \(value)% · 수급 유지 여부 확인"
    }
    var aiDropCause: String {
        let merged = "\(result.news) \(result.headlines) \(result.risks) \(result.mobileNewsImpactSummary)"
        if result.hasCriticalNewsRisk || merged.contains("악재") || merged.lowercased().contains("risk") {
            return "악재 뉴스 또는 리스크 재평가"
        }
        if result.mobileNewsImpactScore <= -25 {
            return "뉴스 영향 약화와 투자심리 둔화"
        }
        if result.volumeRatio >= 2 {
            return "거래량 동반 하락 · 차익실현/수급 이탈"
        }
        if result.analystSectorScore < 45 {
            return "섹터 약세와 시장 전체 영향"
        }
        return "단기 가격 조정 또는 차익실현"
    }
    var badNewsText: String {
        NewsDigest.oneLine(result.risks, result.newsActionText, result.mobileNewsImpactSummary, fallback: "관련 악재 뉴스 추가 확인 필요")
    }
    var reboundText: String {
        var value = 42
        if result.volumeRatio >= 1.5 { value += 8 }
        if result.analystTechnicalScore >= 60 { value += 10 }
        if result.hasCriticalNewsRisk { value -= 14 }
        if result.changePercent <= -7 { value += 6 }
        return "반등 가능성 \(min(82, max(18, value)))% · 지지선 이탈 여부 확인"
    }
    var aiInterestText: String {
        if aiHotScore >= 80 { return "AI 관심도 매우 높음" }
        if aiHotScore >= 65 { return "AI 관심도 높음" }
        if aiHotScore >= 50 { return "AI 관심도 보통" }
        return "AI 관심도 낮음"
    }
    var hotReason: String {
        var reasons: [String] = []
        if abs(result.changePercent) >= 3 { reasons.append("등락률 \(result.changeBadgeText)") }
        if result.volumeRatio >= 1.5 { reasons.append("거래량 \(volumeMultipleText)") }
        if newsCount > 0 { reasons.append("뉴스 \(newsCount)건") }
        if result.foreignNet > 0 || result.institutionNet > 0 { reasons.append("수급 유입") }
        if result.isAiPick { reasons.append("AI 추천") }
        return reasons.isEmpty ? result.simpleReason : reasons.prefix(4).joined(separator: " · ")
    }
    var riskNotice: String {
        if result.hasCriticalNewsRisk { return "악재 확인" }
        let title = result.entryDecisionTitle
        if title.contains("추격") || title == "관망" || title.contains("눌림") {
            return title
        }
        if abs(result.changePercent) >= 6 { return "변동성 주의" }
        return result.entryDecisionTitle
    }

    func sortValue(category: MoversCategory, sort: MoversSort) -> Double {
        switch sort {
        case .change: return category == .losers ? abs(result.changePercent) : result.changePercent
        case .volume: return result.volumeRatio
        case .tradeValue: return result.tradeValueForRanking
        case .marketCap: return marketCapProxy
        case .aiScore: return Double(aiHotScore)
        }
    }

    func loserSortValue(sort: MoversSort) -> Double {
        switch sort {
        case .change: return result.changePercent
        case .volume: return -result.volumeRatio
        case .tradeValue: return -result.tradeValueForRanking
        case .marketCap: return -marketCapProxy
        case .aiScore: return -Double(aiHotScore)
        }
    }

    private func flowText(label: String, value: Double) -> String {
        if value > 0 {
            return "\(label) 순매수 \(value.formatted(.number.precision(.fractionLength(0))))"
        }
        if value < 0 {
            return "\(label) 순매도 \(abs(value).formatted(.number.precision(.fractionLength(0))))"
        }
        return "\(label) 보합"
    }
}

private struct MarketMoverHeroCard: View {
    let summary: String
    let items: [MarketMoverItem]

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "dot.radiowaves.left.and.right")
                .font(.title3.bold())
                .foregroundStyle(.mint)
                .frame(width: 30, height: 30)
                .background(Color.mint.opacity(0.12), in: Circle())

            VStack(alignment: .leading, spacing: 6) {
                Text("실시간 시장 모니터")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
                Text(summary)
                    .font(.subheadline.bold())
                    .foregroundStyle(.primary)
                    .lineLimit(2)
                Text("개장 중 가격, 등락률, 거래량, 거래대금, AI 점수는 앱의 3분 자동 갱신 흐름에 맞춰 업데이트됩니다.")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .layoutPriority(1)

            Text("\(items.count)")
                .font(.headline.monospacedDigit().bold())
                .foregroundStyle(.mint)
        }
        .padding(13)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.mint.opacity(0.22), lineWidth: 1))
    }
}

private struct MarketMoverChip: View {
    let title: String
    let systemImage: String
    let isSelected: Bool
    let tint: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.caption.bold())
                .foregroundStyle(isSelected ? tint : .secondary)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background((isSelected ? tint.opacity(0.16) : AppColors.panelSoft), in: Capsule())
                .overlay(Capsule().stroke(isSelected ? tint.opacity(0.5) : AppColors.border, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

private struct MarketMoverMenu<Content: View>: View {
    let title: String
    let systemImage: String
    @ViewBuilder let content: Content

    var body: some View {
        Menu {
            content
        } label: {
            Label(title, systemImage: systemImage)
                .font(.caption.bold())
                .foregroundStyle(.primary)
                .lineLimit(1)
                .minimumScaleFactor(0.78)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 9)
                .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

private struct MarketMoverRow: View {
    let rank: Int
    let item: MarketMoverItem
    let category: MoversCategory

    private var result: ScannerResult { item.result }
    private var movementTint: Color {
        result.changePercent >= 0 ? .red : .blue
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 8) {
                Text("\(rank)")
                    .font(.caption2.monospacedDigit().bold())
                    .foregroundStyle(category.tint)
                    .frame(width: 24, height: 24)
                    .background(category.tint.opacity(0.12), in: Circle())

                Image(systemName: category.systemImage)
                    .font(.caption.bold())
                    .foregroundStyle(category.tint)
                    .frame(width: 18)

                LocalizedStockNameView(
                    name: result.name,
                    ticker: result.ticker,
                    market: result.marketText,
                    primaryFont: .subheadline.bold(),
                    secondaryFont: .caption2.weight(.medium)
                )
                .layoutPriority(1)

                Spacer(minLength: 4)

                VStack(alignment: .trailing, spacing: 2) {
                    Text(result.formattedPrice)
                        .font(.caption.monospacedDigit().bold())
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.68)
                    Text(result.changeBadgeText)
                        .font(.caption2.monospacedDigit().bold())
                        .foregroundStyle(movementTint)
                }
                .frame(maxWidth: 126, alignment: .trailing)
            }

            HStack(spacing: 6) {
                MarketMoverMetric(systemImage: "waveform.path.ecg", text: item.volumeMultipleText, tint: item.result.volumeRatio >= 2 ? .orange : .secondary)
                MarketMoverMetric(systemImage: "banknote.fill", text: item.tradeValueText, tint: .mint)
                MarketMoverMetric(systemImage: "newspaper.fill", text: "\(item.newsCount)", tint: .yellow)
                MarketMoverMetric(systemImage: "sparkles", text: "\(item.aiHotScore) \(item.aiGrade)", tint: category == .aiHot ? .purple : .mint)
                MarketMoverMetric(systemImage: item.riskNotice == "리스크 보통" ? "checkmark.shield.fill" : "exclamationmark.triangle.fill", text: item.riskNotice, tint: item.riskNotice == "리스크 보통" ? .secondary : .orange)
            }

            Text(categoryDetailText)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.primary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            Text("시총 \(item.marketCapText) · \(result.sectorCategoryName) · \(result.marketText)")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(11)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(category.tint.opacity(0.18), lineWidth: 1))
    }

    private var categoryDetailText: String {
        switch category {
        case .gainers:
            return "AI 상승 이유: \(item.aiRiseReason) · \(item.aiContinuationText)"
        case .losers:
            return "AI 하락 원인: \(item.aiDropCause) · 악재: \(item.badNewsText) · \(item.reboundText)"
        case .volumeSurge:
            return "\(item.currentVolumeText) · \(item.averageVolumeText) · \(item.aiInterestText)"
        case .tradeValue:
            return "\(item.foreignNetText) · \(item.institutionNetText) · \(item.moneyFlowAnalysis)"
        case .aiHot:
            return "AI 추천 이유: \(item.hotReason) · 주의: \(item.riskNotice)"
        }
    }
}

private struct MarketMoverMetric: View {
    let systemImage: String
    let text: String
    let tint: Color

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: systemImage)
                .font(.caption2.bold())
            Text(text)
                .font(.caption2.monospacedDigit().bold())
                .lineLimit(1)
                .minimumScaleFactor(0.72)
        }
        .foregroundStyle(tint)
        .padding(.horizontal, 6)
        .padding(.vertical, 4)
        .background(tint.opacity(0.12), in: Capsule())
    }
}

private struct SettingsHomeSection: View {
    let remoteStatusText: String
    let quoteRefreshMessage: String
    let dataUpdatedAt: Date?
    let totalCount: Int
    let bugReports: [BugReport]
    let bugReportSyncText: String
    let temporaryAdminDeviceEnabled: Bool
    let showServerSettings: () -> Void
    let showAdminUnlock: () -> Void
    let showBugReport: () -> Void
    let uploadBugReports: () -> Void
    let downloadBugReports: () -> Void
    let syncBugReports: () -> Void
    let gitSyncBugReports: () -> Void
    let checkBugServerStatus: () -> Void
    let updateBugStatus: (BugReport, BugReportStatus) -> Void
    let updateBugReport: (BugReport) -> Void
    let runQuickScan: () -> Void
    let runFullScan: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "설정", subtitle: "알림, 업데이트, 서버, 개발 작업 관리")
            DashboardInfoCard(
                title: "데이터 상태",
                subtitle: "\(remoteStatusText) · \(quoteRefreshMessage)",
                footnote: "종목 \(totalCount)개 · \(dataUpdatedAt.map { $0.formatted(.dateTime.month().day().hour().minute()) } ?? "갱신 시각 없음")",
                systemImage: "server.rack",
                tint: .mint
            )
            VStack(spacing: 10) {
                HStack(spacing: 10) {
                    Button(action: runQuickScan) {
                        VStack(spacing: 3) {
                            Label("빠른 스캔", systemImage: "bolt.fill")
                            Text("변경 데이터만")
                                .font(.caption2.weight(.semibold))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    Button(action: runFullScan) {
                        VStack(spacing: 3) {
                            Label("전체 스캔", systemImage: "arrow.triangle.2.circlepath")
                            Text("처음부터 분석")
                                .font(.caption2.weight(.semibold))
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
                Button(action: showServerSettings) {
                    Label("서버 설정", systemImage: "cloud.fill")
                        .frame(maxWidth: .infinity)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 132), spacing: 8)], spacing: 8) {
                    Button(action: uploadBugReports) {
                        Label("신고 업로드", systemImage: "arrow.up.doc.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.cyan)

                    Button(action: downloadBugReports) {
                        Label("신고 다운로드", systemImage: "arrow.down.doc.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.blue)

                    Button(action: syncBugReports) {
                        Label("전체 동기화", systemImage: "arrow.triangle.2.circlepath")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.mint)

                    Button(action: gitSyncBugReports) {
                        Label("Git 반영 확인", systemImage: "chevron.left.forwardslash.chevron.right")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.purple)

                    Button(action: checkBugServerStatus) {
                        Label("서버 확인", systemImage: "checkmark.icloud.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.green)
                }
                Button(action: showAdminUnlock) {
                    Label(temporaryAdminDeviceEnabled ? "관리자 기기 등록됨" : "임시 관리자 기기 등록", systemImage: "lock.shield.fill")
                        .frame(maxWidth: .infinity)
                }
                .tint(temporaryAdminDeviceEnabled ? .green : .orange)
            }
            .font(.caption.bold())
            .buttonStyle(.borderedProminent)
            .tint(.mint)

            Text(bugReportSyncText)
                .font(.caption.weight(.semibold))
                .foregroundStyle(bugReportSyncText.contains("실패") ? .orange : .secondary)
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

            BugReportHomeCard(
                reports: bugReports,
                showBugReport: showBugReport,
                updateStatus: updateBugStatus,
                updateReport: updateBugReport
            )
        }
    }
}

private struct AdminCenterSection: View {
    let reports: [BugReport]
    let syncStatusText: String
    let showBugReport: () -> Void
    let refreshReports: () -> Void
    let uploadReports: () -> Void
    let downloadReports: () -> Void
    let gitSyncReports: () -> Void
    let checkServerStatus: () -> Void
    let updateStatus: (BugReport, BugReportStatus) -> Void
    let updateReport: (BugReport) -> Void

    private var recentResolvedCount: Int {
        reports.filter { report in
            guard report.status == .resolved || report.status == .actionDone || report.status == .deployed || report.status == .verified else { return false }
            return Date().timeIntervalSince(report.updatedAt ?? report.createdAt) <= 7 * 24 * 3600
        }.count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "🛠️ 관리자 센터", subtitle: "메인 앱에서 접수된 버그와 개선사항을 서브폰에서 확인하고 처리합니다.")

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 128), spacing: 8)], alignment: .leading, spacing: 8) {
                PaperMiniMetric(title: "🔴 미해결 버그", value: "\(reports.filter { ($0.status == .open || $0.status == .reported) && $0.type.prefix == "BUG" }.count)")
                PaperMiniMetric(title: "🟠 수정 중", value: "\(reports.filter { $0.status == .checking || $0.status == .inProgress }.count)")
                PaperMiniMetric(title: "🔵 테스트 중", value: "\(reports.filter { $0.status == .testing }.count)")
                PaperMiniMetric(title: "🟢 최근 해결", value: "\(recentResolvedCount)")
                PaperMiniMetric(title: "💡 개선사항", value: "\(reports.filter { $0.type == .improvement }.count)")
                PaperMiniMetric(title: "📊 데이터 문제", value: "\(reports.filter { $0.type == .data }.count)")
            }

            VStack(alignment: .leading, spacing: 10) {
                Text(syncStatusText)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(syncStatusText.contains("실패") ? .orange : .secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)

                LazyVGrid(columns: [GridItem(.adaptive(minimum: 132), spacing: 8)], spacing: 8) {
                    Button(action: downloadReports) {
                        Label("신고 다운로드", systemImage: "arrow.down.doc.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.blue)

                    Button(action: uploadReports) {
                        Label("신고 업로드", systemImage: "arrow.up.doc.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.cyan)

                    Button(action: refreshReports) {
                        Label("전체 동기화", systemImage: "arrow.triangle.2.circlepath")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.mint)

                    Button(action: gitSyncReports) {
                        Label("Git 반영 확인", systemImage: "chevron.left.forwardslash.chevron.right")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.purple)

                    Button(action: checkServerStatus) {
                        Label("서버 확인", systemImage: "checkmark.icloud.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .tint(.green)
                }
                .font(.caption.bold())
                .buttonStyle(.borderedProminent)
            }
            .padding(10)
            .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

            BugReportHomeCard(
                reports: reports,
                showBugReport: showBugReport,
                updateStatus: updateStatus,
                updateReport: updateReport
            )
        }
    }
}

private struct AdminUnlockView: View {
    @Environment(\.dismiss) private var dismiss
    let config: RemoteServerConfig
    let onUnlocked: () -> Void
    @State private var adminToken = ""
    @State private var statusText = "서브폰에서만 사용할 임시 관리자 키를 입력하세요."
    @State private var isVerifying = false

    var body: some View {
        NavigationStack {
            ZStack {
                AppColors.background.ignoresSafeArea()
                VStack(alignment: .leading, spacing: 14) {
                    SectionHeader(title: "임시 관리자 기기 등록", subtitle: "정식 계정 시스템 전까지 이 기기에서만 관리자 센터를 엽니다.")

                    SecureField("관리자 키", text: $adminToken)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(11)
                        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

                    Text(statusText)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(statusText.contains("완료") ? .green : .secondary)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

                    Button {
                        Task { await verify() }
                    } label: {
                        Label(isVerifying ? "확인중" : "관리자 센터 열기", systemImage: "lock.open.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .font(.caption.bold())
                    .tint(.orange)
                    .disabled(isVerifying)

                    Spacer(minLength: 0)
                }
                .padding(16)
                .noHorizontalOverflow()
            }
            .navigationTitle("관리자 등록")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기") { dismiss() }
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    @MainActor
    private func verify() async {
        guard config.isReady else {
            statusText = "먼저 서버 설정에서 API 토큰을 저장하세요."
            return
        }
        let cleanToken = adminToken.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanToken.isEmpty else {
            statusText = "관리자 키를 입력하세요."
            return
        }
        isVerifying = true
        defer { isVerifying = false }
        do {
            try await BugReportRemoteSync.verifyAdmin(config: config, adminToken: cleanToken)
            statusText = "관리자 기기 등록 완료"
            onUnlocked()
            dismiss()
        } catch {
            statusText = "관리자 인증 실패 · 키를 다시 확인하세요."
        }
    }
}

private struct BugReportHomeCard: View {
    let reports: [BugReport]
    let showBugReport: () -> Void
    let updateStatus: (BugReport, BugReportStatus) -> Void
    let updateReport: (BugReport) -> Void
    @State private var statusFilter: BugReportListFilter = .all
    @State private var marketFilter: BugReportMarketFilter = .all
    @State private var editingReport: BugReport?

    private var visibleReports: [BugReport] {
        reports
            .filter { statusFilter.matches($0) }
            .filter { marketFilter.matches($0) }
            .sorted { lhs, rhs in
            lhs.createdAt > rhs.createdAt
        }
    }

    private var unresolvedCount: Int {
        reports.filter { $0.status == .open }.count
    }

    var body: some View {
        AdaptiveCard {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Label("버그 / 개선사항 관리", systemImage: "ladybug.fill")
                        .font(.subheadline.bold())
                    Text("발견한 문제와 개선 작업을 기록하고 수정 이력까지 남깁니다.")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                Button(action: showBugReport) {
                    Label("신고 작성", systemImage: "square.and.pencil")
                }
                .buttonStyle(.borderedProminent)
                .font(.caption.bold())
                .tint(.orange)
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 104), spacing: 8)], alignment: .leading, spacing: 8) {
                PaperMiniMetric(title: "전체 작업", value: "\(reports.count)")
                PaperMiniMetric(title: "🔴 발견", value: "\(unresolvedCount)")
                PaperMiniMetric(title: "🟡 수정 중", value: "\(reports.filter { $0.status == .checking }.count)")
                PaperMiniMetric(title: "🔵 테스트 중", value: "\(reports.filter { $0.status == .testing }.count)")
                PaperMiniMetric(title: "🟢 해결", value: "\(reports.filter { $0.status == .resolved }.count)")
                PaperMiniMetric(title: "⚪ 보류", value: "\(reports.filter { $0.status == .paused }.count)")
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 128), spacing: 8)], alignment: .leading, spacing: 8) {
                Picker("상태 필터", selection: $statusFilter) {
                    ForEach(BugReportListFilter.allCases) { filter in
                        Text(filter.title).tag(filter)
                    }
                }
                .pickerStyle(.menu)
                .padding(8)
                .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

                Picker("시장 필터", selection: $marketFilter) {
                    ForEach(BugReportMarketFilter.allCases) { filter in
                        Text(filter.title).tag(filter)
                    }
                }
                .pickerStyle(.menu)
                .padding(8)
                .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            }
            .font(.caption.bold())

            if visibleReports.isEmpty {
                Text(reports.isEmpty ? "아직 저장된 개발 작업이 없습니다." : "선택한 필터에 맞는 작업이 없습니다.")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            } else {
                LazyVStack(spacing: 8) {
                    ForEach(visibleReports) { report in
                        BugReportRow(report: report, updateStatus: { status in
                            updateStatus(report, status)
                        }, editAction: {
                            editingReport = report
                        })
                    }
                }
            }
        }
        .sheet(item: $editingReport) { report in
            BugFixHistoryEditorView(report: report) { updated in
                updateReport(updated)
            }
        }
    }
}

private struct BugReportRow: View {
    let report: BugReport
    let updateStatus: (BugReportStatus) -> Void
    let editAction: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(report.displayID)
                        .font(.caption.monospacedDigit().bold())
                        .foregroundStyle(.orange)
                    Text(report.titleText)
                        .font(.caption.bold())
                        .fixedSize(horizontal: false, vertical: true)
                    Text(report.summaryText)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 5) {
                    Picker("상태", selection: Binding(
                        get: { report.status },
                        set: { updateStatus($0) }
                    )) {
                        ForEach(BugReportStatus.allCases) { status in
                            Text(status.title).tag(status)
                        }
                    }
                    .pickerStyle(.menu)
                    .font(.caption.bold())

                    Button(action: editAction) {
                        Label("수정 이력", systemImage: "wrench.and.screwdriver.fill")
                    }
                    .font(.caption2.bold())
                    .buttonStyle(.bordered)
                }
            }

            if !report.relatedFeatureText.isEmpty || !report.relatedTicker.isEmpty {
                Text([report.relatedFeatureText, report.relatedTicker].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Text("\(report.marketDisplayText) · \(report.screen)")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)

            if !report.userResolutionSummaryText.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Label("조치 완료", systemImage: "checkmark.seal.fill")
                        .font(.caption.bold())
                        .foregroundStyle(.green)
                    Text(report.userResolutionSummaryText)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.green.opacity(0.10), in: RoundedRectangle(cornerRadius: 7))
                .overlay(RoundedRectangle(cornerRadius: 7).stroke(Color.green.opacity(0.22), lineWidth: 1))
            }

            if !report.snapshot.isEmpty {
                Text(report.snapshot)
                    .font(.caption2.monospacedDigit().weight(.medium))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 6) {
                PaperCompactBadge(text: report.type.title, tint: .orange)
                PaperCompactBadge(text: report.priorityValue.title, tint: report.priorityValue.tint)
                PaperCompactBadge(text: report.status.title, tint: report.status.tint)
                Text(AppDateTime.localString(from: report.createdAt, format: "yyyy-MM-dd HH:mm"))
                    .font(.caption2.monospacedDigit().weight(.medium))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(report.status.tint.opacity(0.22), lineWidth: 1))
    }
}

private struct BugFixHistoryEditorView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var draft: BugReport
    let saveAction: (BugReport) -> Void

    init(report: BugReport, saveAction: @escaping (BugReport) -> Void) {
        _draft = State(initialValue: report)
        self.saveAction = saveAction
    }

    var body: some View {
        NavigationStack {
            ScrollView(.vertical, showsIndicators: true) {
                VStack(alignment: .leading, spacing: 12) {
                    SectionHeader(title: draft.displayID, subtitle: "수정 이력 기록")
                    BugReportAutoField(title: "제목", value: draft.titleText)
                    BugReportAutoField(title: "문제", value: draft.summaryText)
                    if !draft.gitCommitMessageText.isEmpty {
                        BugReportAutoField(title: "자동 연결 commit", value: draft.gitCommitMessageText)
                        BugReportAutoField(title: "commit / 수정일", value: [draft.shortGitCommitHash, draft.gitCommitDateText].filter { !$0.isEmpty }.joined(separator: " · "))
                    }

                    Picker("상태", selection: $draft.status) {
                        ForEach(BugReportStatus.allCases) { status in
                            Text(status.title).tag(status)
                        }
                    }
                    .pickerStyle(.menu)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

                    Picker("우선순위", selection: Binding(
                        get: { draft.priorityValue },
                        set: { draft.priority = $0 }
                    )) {
                        ForEach(BugReportPriority.allCases) { priority in
                            Text(priority.title).tag(priority)
                        }
                    }
                    .pickerStyle(.menu)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

                    ScreeningTextField(title: "수정한 파일", text: Binding(
                        get: { draft.fixFile ?? "" },
                        set: { draft.fixFile = $0 }
                    ), keyboard: .default)

                    BugReportMultilineField(title: "수정 내용", text: Binding(
                        get: { draft.fixSummary ?? "" },
                        set: { draft.fixSummary = $0 }
                    ), minHeight: 86)

                    BugReportMultilineField(title: "수정 이유", text: Binding(
                        get: { draft.fixReason ?? "" },
                        set: { draft.fixReason = $0 }
                    ), minHeight: 72)

                    BugReportMultilineField(title: "테스트 결과", text: Binding(
                        get: { draft.testResult ?? "" },
                        set: { draft.testResult = $0 }
                    ), minHeight: 72)

                    ScreeningTextField(title: "수정 완료 날짜", text: Binding(
                        get: { draft.completedAtText ?? "" },
                        set: { draft.completedAtText = $0 }
                    ), keyboard: .default)

                    BugReportMultilineField(title: "추가 메모", text: Binding(
                        get: { draft.note ?? "" },
                        set: { draft.note = $0 }
                    ), minHeight: 72)

                    if !draft.resolutionReportText.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("수정 완료 보고서")
                                .font(.caption.bold())
                                .foregroundStyle(.green)
                            Text(draft.resolutionReportText)
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.green.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.green.opacity(0.22), lineWidth: 1))
                    }

                    if let history = draft.history, !history.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("상태 변경 이력")
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                            ForEach(history.prefix(8)) { item in
                                Text("\(AppDateTime.localString(from: item.at, format: "yyyy-MM-dd HH:mm")) · \(item.action) · \(item.detail)")
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
                    }

                    Button {
                        if (draft.status == .resolved || draft.status == .actionDone), (draft.completedAtText ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            draft.completedAtText = AppDateTime.localString(from: Date(), format: "yyyy-MM-dd HH:mm")
                        }
                        saveAction(draft)
                        dismiss()
                    } label: {
                        Label("수정 이력 저장", systemImage: "tray.and.arrow.down.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .font(.caption.bold())
                    .tint(.mint)

                    Button {
                        draft.completeWithAutoReport()
                        saveAction(draft)
                        dismiss()
                    } label: {
                        Label("조치 완료 · 보고서 자동 생성", systemImage: "checkmark.seal.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .font(.caption.bold())
                    .tint(.green)
                }
                .padding(16)
            }
            .background(AppColors.background.ignoresSafeArea())
            .navigationTitle("수정 이력")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("닫기") { dismiss() }
                }
            }
            .preferredColorScheme(.dark)
        }
    }
}

private struct BugReportMultilineField: View {
    let title: String
    @Binding var text: String
    let minHeight: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            TextEditor(text: $text)
                .font(.caption.weight(.semibold))
                .frame(minHeight: minHeight)
                .scrollContentBackground(.hidden)
                .padding(8)
                .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
        }
    }
}

private struct BugReportEditorView: View {
    @Environment(\.dismiss) private var dismiss
    let context: BugReportContext
    let saveAction: (BugReport) -> Void
    @State private var title = ""
    @State private var type: BugReportType = .bug
    @State private var priority: BugReportPriority = .normal
    @State private var content = ""
    @State private var relatedFeature = ""
    @State private var relatedTicker = ""
    @State private var market: BugReportMarket = .common

    var body: some View {
        NavigationStack {
            ScrollView(.vertical, showsIndicators: true) {
                VStack(alignment: .leading, spacing: 14) {
                    SectionHeader(title: "개발 작업 등록", subtitle: "발견 → 기록 → 수정 → 테스트 → 해결")

                    ScreeningTextField(title: "제목", text: $title, keyboard: .default)

                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 132), spacing: 8)], alignment: .leading, spacing: 8) {
                        Picker("유형", selection: $type) {
                            ForEach(BugReportType.allCases) { item in
                                Text(item.title).tag(item)
                            }
                        }
                        .pickerStyle(.menu)
                        .padding(10)
                        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

                        Picker("우선순위", selection: $priority) {
                            ForEach(BugReportPriority.allCases) { item in
                                Text(item.title).tag(item)
                            }
                        }
                        .pickerStyle(.menu)
                        .padding(10)
                        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

                        Picker("시장", selection: $market) {
                            ForEach(BugReportMarket.allCases) { item in
                                Text(item.title).tag(item)
                            }
                        }
                        .pickerStyle(.menu)
                        .padding(10)
                        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
                    }
                    .font(.caption.bold())

                    BugReportMultilineField(title: "상세 내용", text: $content, minHeight: 120)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("관련 정보")
                            .font(.caption.bold())
                            .foregroundStyle(.secondary)
                        ScreeningTextField(title: "관련 기능", text: $relatedFeature, keyboard: .default)
                        ScreeningTextField(title: "관련 종목/티커", text: $relatedTicker, keyboard: .default)
                        BugReportAutoField(title: "현재 화면", value: context.screen)
                        BugReportAutoField(title: "발생 시간", value: AppDateTime.localString(from: Date(), format: "yyyy-MM-dd HH:mm:ss"))
                        if !context.snapshot.isEmpty {
                            BugReportAutoField(title: "신고 당시 정보", value: context.snapshot)
                        }
                    }

                    Button {
                        let report = BugReport(
                            sequence: BugReportStore.nextSequence(),
                            type: type,
                            title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                            content: content.trimmingCharacters(in: .whitespacesAndNewlines),
                            relatedFeature: relatedFeature.trimmingCharacters(in: .whitespacesAndNewlines),
                            relatedTicker: relatedTicker.trimmingCharacters(in: .whitespacesAndNewlines),
                            relatedName: context.relatedName,
                            screen: context.screen,
                            market: market.rawValue,
                            snapshot: context.snapshot,
                            createdAt: Date(),
                            status: .reported,
                            priority: priority,
                            bugID: "\(type.prefix)-" + String(format: "%03d", BugReportStore.nextSequence()),
                            reportedDevice: UIDevice.current.name
                        )
                        saveAction(report)
                        dismiss()
                    } label: {
                        Label("작업 등록", systemImage: "tray.and.arrow.down.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.orange)
                    .font(.caption.bold())
                    .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                .padding(16)
            }
            .background(AppColors.background.ignoresSafeArea())
            .navigationTitle("작업 등록")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("닫기") { dismiss() }
                }
            }
            .preferredColorScheme(.dark)
            .onAppear {
                relatedTicker = context.relatedTicker
                relatedFeature = context.screen
                market = BugReportMarket(contextText: context.market)
            }
        }
    }
}


private struct BugReportAutoField: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
            Text(value.isEmpty ? "-" : value)
                .font(.caption.monospacedDigit().weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct BugReportContext {
    let relatedTicker: String
    let relatedName: String
    let screen: String
    let market: String
    let snapshot: String
}

private struct BugReport: Identifiable, Codable, Equatable {
    let id: UUID
    let sequence: Int
    var type: BugReportType
    var title: String?
    var content: String
    var relatedFeature: String?
    var relatedTicker: String
    var relatedName: String
    var screen: String
    var market: String
    var snapshot: String
    let createdAt: Date
    var updatedAt: Date?
    var status: BugReportStatus
    var priority: BugReportPriority?
    var fixFile: String?
    var fixSummary: String?
    var fixReason: String?
    var testResult: String?
    var completedAtText: String?
    var note: String?
    var resolutionReport: String?
    var history: [BugReportHistoryEntry]?
    var bugID: String?
    var reportedDevice: String?
    var gitCommitHash: String?
    var gitCommitMessage: String?
    var gitCommitDate: String?
    var gitSyncedAt: String?
    var gitAutoProcessedAt: String?
    var gitAutoProcessingStatus: String?
    var gitAutoProcessingSource: String?
    var gitAutoProcessingRunID: String?
    var gitAutoProcessingRunAttempt: String?
    var fixVersion: String?
    var deployVersion: String?
    var latestStateChangedAt: String?

    init(
        id: UUID = UUID(),
        sequence: Int,
        type: BugReportType,
        title: String = "",
        content: String,
        relatedFeature: String = "",
        relatedTicker: String,
        relatedName: String,
        screen: String,
        market: String,
        snapshot: String,
        createdAt: Date,
        updatedAt: Date? = nil,
        status: BugReportStatus,
        priority: BugReportPriority = .normal,
        fixFile: String = "",
        fixSummary: String = "",
        fixReason: String = "",
        testResult: String = "",
        completedAtText: String = "",
        note: String = "",
        resolutionReport: String = "",
        history: [BugReportHistoryEntry] = [],
        bugID: String = "",
        reportedDevice: String = "",
        gitCommitHash: String = "",
        gitCommitMessage: String = "",
        gitCommitDate: String = "",
        gitSyncedAt: String = "",
        gitAutoProcessedAt: String = "",
        gitAutoProcessingStatus: String = "",
        gitAutoProcessingSource: String = "",
        gitAutoProcessingRunID: String = "",
        gitAutoProcessingRunAttempt: String = "",
        fixVersion: String = "",
        deployVersion: String = "",
        latestStateChangedAt: String = ""
    ) {
        self.id = id
        self.sequence = sequence
        self.type = type
        self.title = title
        self.content = content
        self.relatedFeature = relatedFeature
        self.relatedTicker = relatedTicker
        self.relatedName = relatedName
        self.screen = screen
        self.market = market
        self.snapshot = snapshot
        self.createdAt = createdAt
        self.updatedAt = updatedAt ?? createdAt
        self.status = status
        self.priority = priority
        self.fixFile = fixFile
        self.fixSummary = fixSummary
        self.fixReason = fixReason
        self.testResult = testResult
        self.completedAtText = completedAtText
        self.note = note
        self.resolutionReport = resolutionReport
        self.history = history
        self.bugID = bugID
        self.reportedDevice = reportedDevice
        self.gitCommitHash = gitCommitHash
        self.gitCommitMessage = gitCommitMessage
        self.gitCommitDate = gitCommitDate
        self.gitSyncedAt = gitSyncedAt
        self.gitAutoProcessedAt = gitAutoProcessedAt
        self.gitAutoProcessingStatus = gitAutoProcessingStatus
        self.gitAutoProcessingSource = gitAutoProcessingSource
        self.gitAutoProcessingRunID = gitAutoProcessingRunID
        self.gitAutoProcessingRunAttempt = gitAutoProcessingRunAttempt
        self.fixVersion = fixVersion
        self.deployVersion = deployVersion
        self.latestStateChangedAt = latestStateChangedAt
    }

    var displayID: String {
        let clean = (bugID ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return clean.isEmpty ? "\(type.prefix)-" + String(format: "%03d", sequence) : clean
    }

    var titleText: String {
        let clean = (title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return clean.isEmpty ? summaryText : clean
    }

    var summaryText: String {
        content.isEmpty ? "내용 없음" : content
    }

    var relatedFeatureText: String {
        (relatedFeature ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var fixFileText: String {
        (fixFile ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var fixSummaryText: String {
        (fixSummary ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var testResultText: String {
        (testResult ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var resolutionReportText: String {
        (resolutionReport ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var userResolutionSummaryText: String {
        guard status == .actionDone || status == .resolved || status == .deployed || status == .verified else {
            return ""
        }
        let action = conciseUserSentence(from: fixSummaryText)
        let reason = conciseUserSentence(from: fixReasonText)
        if !action.isEmpty {
            if !reason.isEmpty {
                return "\(action)\n\(reason)"
            }
            return action
        }
        let reportAction = resolutionSection(named: "조치 내용")
        if !reportAction.isEmpty {
            return reportAction
        }
        let title = titleText.trimmingCharacters(in: .whitespacesAndNewlines)
        if title.contains("종목") && title.contains("1개") {
            return "스캔 실패 후 종목 수가 1개로 표시되는 문제를 수정했습니다.\n잘못된 데이터가 전체 결과로 저장되지 않도록 방어 기능을 추가했습니다."
        }
        if title.contains("렉") || title.contains("버벅") || title.localizedCaseInsensitiveContains("lag") {
            return "화면 이동 중 발생하던 렉을 줄이도록 처리했습니다.\n이미 불러온 데이터를 재사용해 상세 화면이 더 부드럽게 열리도록 개선했습니다."
        }
        if title.contains("동기화") || title.contains("신고") {
            return "신고 내역이 기기 사이에서 정상적으로 표시되도록 처리했습니다.\n서버에 저장된 최신 상태를 기준으로 다시 확인하도록 개선했습니다."
        }
        if title.contains("스캔") || title.contains("Render") {
            return "스캔 상태가 잘못 실패로 표시되는 문제를 수정했습니다.\n실제 서버 작업 상태를 기준으로 결과를 확인하도록 개선했습니다."
        }
        return "신고된 문제가 처리되었습니다.\n같은 문제가 다시 발생하지 않도록 관련 동작을 보완했습니다."
    }

    var gitCommitMessageText: String {
        (gitCommitMessage ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var fixReasonText: String {
        (fixReason ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var gitProcessingStatusText: String {
        let status = (gitAutoProcessingStatus ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if status == "failed" {
            return "🔴 Git 자동 처리 실패"
        }
        if !gitCommitMessageText.isEmpty {
            return "🟢 Git 자동 처리 완료"
        }
        return ""
    }

    var gitProcessingSourceText: String {
        let source = (gitAutoProcessingSource ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        switch source {
        case "github_actions":
            return "GitHub Actions 자동"
        case "server_git_log":
            return "서버 Git log 확인"
        case "":
            return gitCommitMessageText.isEmpty ? "" : "수동 Git 반영 확인"
        default:
            return source
        }
    }

    var gitCommitDateText: String {
        (gitCommitDate ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var shortGitCommitHash: String {
        let clean = (gitCommitHash ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return clean.isEmpty ? "" : String(clean.prefix(12))
    }

    var fixVersionText: String {
        (fixVersion ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var deployVersionText: String {
        (deployVersion ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var priorityValue: BugReportPriority {
        priority ?? .normal
    }

    var marketDisplayText: String {
        BugReportMarket(contextText: market).title
    }

    mutating func markUpdated(action: String, detail: String) {
        let now = Date()
        updatedAt = now
        var nextHistory = history ?? []
        nextHistory.insert(BugReportHistoryEntry(at: now, action: action, detail: detail), at: 0)
        history = Array(nextHistory.prefix(30))
    }

    mutating func completeWithAutoReport() {
        status = .actionDone
        if (completedAtText ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            completedAtText = AppDateTime.localString(from: Date(), format: "yyyy-MM-dd HH:mm")
        }
        resolutionReport = makeResolutionReport()
        markUpdated(action: "조치 완료", detail: "수정 완료 보고서 자동 생성")
    }

    private func makeResolutionReport() -> String {
        let cause = cleanOrFallback(fixReason, fallback: "원인 확인 필요")
        let action = cleanOrFallback(fixSummary, fallback: "조치 내용 입력 필요")
        let area = cleanOrFallback(fixFile, fallback: cleanOrFallback(relatedFeature, fallback: screen))
        let test = cleanOrFallback(testResult, fallback: "테스트 결과 확인 필요")
        let date = cleanOrFallback(completedAtText, fallback: AppDateTime.localString(from: Date(), format: "yyyy-MM-dd HH:mm"))
        return """
        🟢 조치 완료

        \(displayID) — \(titleText)

        발생 문제
        \(summaryText)

        발생 원인
        \(cause)

        조치 내용
        \(action)

        수정 영역
        \(area)

        테스트 결과
        \(test)

        처리일
        \(date)

        상태
        🟢 조치 완료
        """
    }

    private func cleanOrFallback(_ value: String?, fallback: String) -> String {
        let clean = (value ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return clean.isEmpty ? fallback : clean
    }

    private func conciseUserSentence(from text: String) -> String {
        let bannedTokens = [
            "commit", "Git", "GitHub", "Actions", "API", "endpoint", "server.py",
            ".swift", ".py", "compile", "build", "HTTP", "diff", "hash", "로그"
        ]
        let normalized = text
            .replacingOccurrences(of: "`", with: "")
            .replacingOccurrences(of: "🟢", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return "" }
        let rawParts = normalized
            .components(separatedBy: CharacterSet(charactersIn: ".\n"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        let selected = rawParts.first { part in
            !bannedTokens.contains { token in part.localizedCaseInsensitiveContains(token) }
        } ?? ""
        guard !selected.isEmpty else { return "" }
        let cleaned = selected
            .replacingOccurrences(of: "추정 원인:", with: "")
            .replacingOccurrences(of: "자동 기록:", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return "" }
        return cleaned.hasSuffix("다") || cleaned.hasSuffix("요") || cleaned.hasSuffix("됨") ? "\(cleaned)." : "\(cleaned)"
    }

    private func resolutionSection(named sectionName: String) -> String {
        let lines = resolutionReportText
            .components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        guard let startIndex = lines.firstIndex(of: sectionName) else { return "" }
        let stopNames: Set<String> = ["발생 문제", "신고 내용", "발생 원인", "원인", "수정 내용", "조치 내용", "수정 파일", "수정 영역", "영향 범위", "Commit", "테스트 결과", "수정 완료 시간", "처리일", "처리 방식", "상태", "현재 상태"]
        var result: [String] = []
        for line in lines.dropFirst(startIndex + 1) {
            if stopNames.contains(line) {
                break
            }
            if !line.isEmpty {
                result.append(line)
            }
        }
        return conciseUserSentence(from: result.prefix(2).joined(separator: "\n"))
    }
}

private struct BugReportHistoryEntry: Identifiable, Codable, Equatable {
    var id: UUID
    var at: Date
    var action: String
    var detail: String

    init(id: UUID = UUID(), at: Date, action: String, detail: String) {
        self.id = id
        self.at = at
        self.action = action
        self.detail = detail
    }
}

private enum BugReportType: String, Codable, Identifiable {
    case bug
    case fix
    case improvement
    case data
    case ui
    case price
    case profitLoss
    case trade
    case other

    static let allCases: [BugReportType] = [.bug, .fix, .improvement, .data, .ui]

    var id: String { rawValue }

    var title: String {
        switch self {
        case .bug, .price, .profitLoss, .trade, .other: return "🐛 버그"
        case .fix: return "🛠️ 수정"
        case .improvement: return "💡 개선"
        case .data: return "📊 데이터 문제"
        case .ui: return "🎨 UI 문제"
        }
    }

    var prefix: String {
        switch self {
        case .fix: return "FIX"
        case .improvement: return "IMP"
        case .data: return "DATA"
        case .ui: return "UI"
        case .bug, .price, .profitLoss, .trade, .other: return "BUG"
        }
    }
}

private enum BugReportStatus: String, CaseIterable, Codable, Identifiable {
    case reported
    case open
    case inProgress
    case checking
    case testing
    case actionDone
    case resolved
    case deployed
    case verified
    case paused

    static var allCases: [BugReportStatus] {
        [.reported, .inProgress, .testing, .actionDone, .deployed, .verified, .paused, .open, .checking, .resolved]
    }

    var id: String { rawValue }

    var title: String {
        switch self {
        case .reported, .open: return "🔴 신고됨"
        case .inProgress, .checking: return "🟠 수정 중"
        case .testing: return "🔵 테스트 중"
        case .actionDone, .resolved: return "🟢 조치 완료"
        case .deployed: return "🔵 배포 완료"
        case .verified: return "⚪ 해결 확인"
        case .paused: return "⚪ 보류"
        }
    }

    var tint: Color {
        switch self {
        case .reported, .open: return .red
        case .inProgress, .checking: return .orange
        case .testing: return .blue
        case .actionDone, .resolved: return .green
        case .deployed: return .blue
        case .verified: return .gray
        case .paused: return .gray
        }
    }
}

private enum BugReportPriority: String, CaseIterable, Codable, Identifiable {
    case urgent
    case high
    case normal
    case low

    var id: String { rawValue }

    var title: String {
        switch self {
        case .urgent: return "🔴 긴급"
        case .high: return "🟠 높음"
        case .normal: return "🟡 보통"
        case .low: return "🟢 낮음"
        }
    }

    var tint: Color {
        switch self {
        case .urgent: return .red
        case .high: return .orange
        case .normal: return .yellow
        case .low: return .green
        }
    }
}

private enum BugReportMarket: String, CaseIterable, Codable, Identifiable {
    case korea = "국장"
    case us = "미장"
    case common = "공통"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .korea: return "🇰🇷 국장"
        case .us: return "🇺🇸 미장"
        case .common: return "공통"
        }
    }

    init(contextText: String) {
        let clean = contextText.trimmingCharacters(in: .whitespacesAndNewlines)
        if clean.contains("미장") || clean.contains("미국") {
            self = .us
        } else if clean.contains("국장") || clean.contains("한국") {
            self = .korea
        } else {
            self = .common
        }
    }
}

private enum BugReportListFilter: String, CaseIterable, Identifiable {
    case all
    case unresolved
    case checking
    case testing
    case resolved
    case paused
    case bug
    case improvement
    case data
    case ui

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: return "전체"
        case .unresolved: return "미해결"
        case .checking: return "수정 중"
        case .testing: return "테스트 중"
        case .resolved: return "해결"
        case .paused: return "보류"
        case .bug: return "버그"
        case .improvement: return "개선"
        case .data: return "데이터"
        case .ui: return "UI"
        }
    }

    func matches(_ report: BugReport) -> Bool {
        switch self {
        case .all: return true
        case .unresolved: return report.status == .open || report.status == .reported
        case .checking: return report.status == .checking || report.status == .inProgress
        case .testing: return report.status == .testing
        case .resolved: return report.status == .resolved || report.status == .actionDone || report.status == .deployed || report.status == .verified
        case .paused: return report.status == .paused
        case .bug: return report.type.prefix == "BUG"
        case .improvement: return report.type == .improvement
        case .data: return report.type == .data
        case .ui: return report.type == .ui
        }
    }
}

private enum BugReportMarketFilter: String, CaseIterable, Identifiable {
    case all
    case korea
    case us
    case common

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: return "전체 시장"
        case .korea: return "국장"
        case .us: return "미장"
        case .common: return "공통"
        }
    }

    func matches(_ report: BugReport) -> Bool {
        let market = BugReportMarket(contextText: report.market)
        switch self {
        case .all: return true
        case .korea: return market == .korea
        case .us: return market == .us
        case .common: return market == .common
        }
    }
}

private enum BugReportStore {
    private static let key = "localBugReports.v1"
    private static let buyRecommendationAuditTitle = "최근 매수 추천이 단 한 건도 발생하지 않는 문제"

    static func load() -> [BugReport] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let decoded = try? JSONDecoder().decode([BugReport].self, from: data) else {
            return []
        }
        return decoded.sorted { ($0.updatedAt ?? $0.createdAt) > ($1.updatedAt ?? $1.createdAt) }
    }

    static func add(_ report: BugReport) -> [BugReport] {
        var reports = load()
        var nextReport = report
        nextReport.markUpdated(action: "신고 등록", detail: report.titleText)
        reports.insert(nextReport, at: 0)
        save(reports)
        return reports
    }

    static func update(_ report: BugReport) -> [BugReport] {
        var reports = load()
        var nextReport = report
        nextReport.markUpdated(action: "수정 이력 저장", detail: report.status.title)
        if let index = reports.firstIndex(where: { $0.id == report.id }) {
            reports[index] = nextReport
        } else {
            reports.insert(nextReport, at: 0)
        }
        save(reports)
        return reports.sorted { ($0.updatedAt ?? $0.createdAt) > ($1.updatedAt ?? $1.createdAt) }
    }

    static func updateStatus(_ id: UUID, status: BugReportStatus) -> [BugReport] {
        var reports = load()
        guard let index = reports.firstIndex(where: { $0.id == id }) else {
            return reports
        }
        reports[index].status = status
        reports[index].markUpdated(action: "상태 변경", detail: status.title)
        save(reports)
        return reports
    }

    static func merge(_ local: [BugReport], _ remote: [BugReport]) -> [BugReport] {
        var byID: [UUID: BugReport] = [:]
        for report in local + remote {
            let existing = byID[report.id]
            if existing == nil || (report.updatedAt ?? report.createdAt) >= (existing?.updatedAt ?? existing?.createdAt ?? .distantPast) {
                byID[report.id] = report
            }
        }
        let merged = Array(byID.values).sorted { ($0.updatedAt ?? $0.createdAt) > ($1.updatedAt ?? $1.createdAt) }
        save(merged)
        return seededIfNeeded(merged)
    }

    static func replaceFromServer(_ reports: [BugReport]) -> [BugReport] {
        let sorted = reports.sorted { ($0.updatedAt ?? $0.createdAt) > ($1.updatedAt ?? $1.createdAt) }
        save(sorted)
        return sorted
    }

    static func nextSequence() -> Int {
        (load().map(\.sequence).max() ?? 0) + 1
    }

    private static func save(_ reports: [BugReport]) {
        guard let data = try? JSONEncoder().encode(reports) else {
            return
        }
        UserDefaults.standard.set(data, forKey: key)
    }

    private static func seededIfNeeded(_ reports: [BugReport]) -> [BugReport] {
        let hasAuditTask = reports.contains {
            $0.titleText == buyRecommendationAuditTitle
                || $0.summaryText.contains("매수 추천이 단 한 건도 발생")
        }
        guard !hasAuditTask else {
            return reports.sorted { $0.createdAt > $1.createdAt }
        }
        var next = reports
        next.insert(makeBuyRecommendationAuditTask(sequence: (reports.map(\.sequence).max() ?? 0) + 1), at: 0)
        save(next)
        return next.sorted { $0.createdAt > $1.createdAt }
    }

    private static func makeBuyRecommendationAuditTask(sequence: Int) -> BugReport {
        BugReport(
            sequence: sequence,
            type: .data,
            title: buyRecommendationAuditTitle,
            content: """
            최근 모의투자 시스템에서 국장과 미장을 분석하고 있음에도 매수 추천이 단 한 건도 발생하지 않고 있음. 추천 로직 자체의 오류인지, 필터/점수 기준이 지나치게 엄격한 것인지, 데이터 문제인지 원인을 확인해야 함.

            확인 항목:
            - 매수 추천 생성 전체 로직
            - 추천 점수 계산 정상 여부
            - 매수 추천 기준 점수 과도 설정 여부
            - 특정 조건/필터로 모든 종목 탈락 여부
            - 데이터 업데이트 문제로 추천 조건 미충족 여부
            - 국장/미장 후보 생성 여부
            - 후보 생성 → 점수 계산 → 위험도 평가 → 최종 추천 판정 전체 흐름
            - 최근 코드 변경으로 추천 차단 여부
            - 예외처리 때문에 사용자에게 오류가 표시되지 않는지 여부
            """,
            relatedFeature: "모의투자 / 매수 추천 / 추천 알고리즘",
            relatedTicker: "",
            relatedName: "",
            screen: "모의투자",
            market: BugReportMarket.common.rawValue,
            snapshot: "오늘 매수 추천 0건 원인 추적 필요 · 분석 종목/후보 진입/최종 탈락/탈락 사유 로그 필요",
            createdAt: Date(),
            status: .reported,
            priority: .urgent,
            fixReason: "추천을 억지로 발생시키는 것이 아니라 기존 기준을 유지한 채 최근 추천 0건의 원인을 먼저 분리해야 함.",
            testResult: "필요 테스트: 국장/미장 각각 분석 종목 수, 후보 진입 수, 최종 탈락 수, 주요 탈락 이유를 확인하고 조건 충족 종목이 있음에도 0건이면 버그로 수정.",
            note: "정상 시장 상황으로 추천 0건일 수 있는 경우와 추천 로직 버그로 0건인 경우를 구분할 수 있는 분석 로그를 남길 것."
        )
    }
}

private enum BugReportRemoteSync {
    static func fetch(config: RemoteServerConfig) async throws -> BugReportSyncResponse {
        try await request(
            path: "/api/bug-reports",
            config: config,
            method: "GET",
            body: nil
        )
    }

    static func sync(reports: [BugReport], config: RemoteServerConfig) async throws -> BugReportSyncResponse {
        let payload = BugReportSyncRequest(reports: reports)
        let body = try JSONEncoder().encode(payload)
        return try await request(
            path: "/api/bug-reports/sync",
            config: config,
            method: "POST",
            body: body
        )
    }

    static func gitSync(config: RemoteServerConfig) async throws -> BugReportSyncResponse {
        try await request(
            path: "/api/bug-reports/git-sync",
            config: config,
            method: "POST",
            body: Data("{}".utf8)
        )
    }

    static func userMessage(for error: Error) -> String {
        if let syncError = error as? BugReportSyncError {
            return syncError.message
        }
        if let urlError = error as? URLError {
            switch urlError.code {
            case .userAuthenticationRequired:
                return "서버 설정/API 토큰 필요"
            case .badURL:
                return "서버 주소 오류"
            case .timedOut:
                return "서버 응답 시간 초과"
            case .notConnectedToInternet, .networkConnectionLost:
                return "네트워크 연결 오류"
            default:
                return "네트워크 오류 \(urlError.errorCode)"
            }
        }
        return error.localizedDescription
    }

    static func verifyAdmin(config: RemoteServerConfig, adminToken: String) async throws {
        let body = try JSONEncoder().encode(AdminVerifyRequest(adminToken: adminToken))
        let response: AdminVerifyResponse = try await request(
            path: "/api/admin/verify",
            config: config,
            method: "POST",
            body: body
        )
        guard response.ok, response.admin else {
            throw URLError(.userAuthenticationRequired)
        }
    }

    private static func request<T: Decodable>(
        path: String,
        config: RemoteServerConfig,
        method: String,
        body: Data?
    ) async throws -> T {
        guard config.isReady else {
            throw URLError(.userAuthenticationRequired)
        }
        let base = config.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: base + path) else {
            print("BUG_SYNC_ERROR endpoint=\(path) detail=bad URL")
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 20
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        let token = config.token.trimmingCharacters(in: .whitespacesAndNewlines)
        request.setValue(token, forHTTPHeaderField: "X-Market-Token")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if method != "GET" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
        }
        let startedAt = Date()
        print("BUG_SYNC_REQUEST method=\(method) endpoint=\(path) started_at=\(ISO8601DateFormatter().string(from: startedAt)) timeout=20s")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            print("BUG_SYNC_ERROR endpoint=\(path) detail=bad server response")
            throw URLError(.badServerResponse)
        }
        print("BUG_SYNC_RESPONSE endpoint=\(path) status=\(http.statusCode) elapsed=\(String(format: "%.2f", Date().timeIntervalSince(startedAt)))s bytes=\(data.count)")
        guard (200..<300).contains(http.statusCode) else {
            throw BugReportSyncError(statusCode: http.statusCode, data: data)
        }
        do {
            let decoded = try JSONDecoder().decode(T.self, from: data)
            if let payload = decoded as? BugReportSyncResponse {
                print("BUG_SYNC_PARSE endpoint=\(path) server_count=\(payload.reportCount) local_payload_rows=\(payload.reports.count) reported=\(payload.reportedCount ?? -1) actionDone=\(payload.actionDoneCount ?? -1) resolved=\(payload.resolvedCount ?? -1) urgent=\(payload.urgentCount ?? -1) data_version=\(payload.dataVersion ?? "")")
            }
            return decoded
        } catch {
            print("BUG_SYNC_PARSE_ERROR endpoint=\(path) detail=\(error.localizedDescription) sample=\(String(data: data.prefix(160), encoding: .utf8) ?? "")")
            throw error
        }
    }
}

private struct BugReportSyncError: Error {
    let statusCode: Int
    let detail: String

    init(statusCode: Int, data: Data) {
        self.statusCode = statusCode
        if let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            detail = (payload["detail"] as? String) ?? (payload["error"] as? String) ?? ""
        } else {
            detail = ""
        }
    }

    var message: String {
        switch statusCode {
        case 401:
            return "401 인증 실패 · 서버 설정 API 토큰 확인"
        case 403:
            return "403 접근 거부 · 서버/토큰 권한 확인"
        case 404:
            return "404 신고 API 없음 · 서버 배포 확인"
        case 413:
            return "413 신고 데이터가 너무 큼"
        case 500...599:
            return "\(statusCode) 서버 오류"
        default:
            return "\(statusCode) \(detail.isEmpty ? "동기화 오류" : detail)"
        }
    }
}

private struct BugReportSyncRequest: Encodable {
    let reports: [BugReport]
}

private struct BugReportSyncResponse: Decodable {
    let ok: Bool
    let reports: [BugReport]
    let count: Int?
    let totalCount: Int?
    let reportedCount: Int?
    let actionDoneCount: Int?
    let resolvedCount: Int?
    let urgentCount: Int?
    let unresolvedCount: Int?
    let lastUpdated: String?
    let serverTimestamp: String?
    let dataVersion: String?
    let changed: Int?
    let gitChanged: Int?
    let gitSyncError: String?
    let gitUnmatchedIDs: [String]?
    let updatedAt: String?

    var reportCount: Int {
        totalCount ?? count ?? reports.count
    }

    enum CodingKeys: String, CodingKey {
        case ok
        case reports
        case count
        case totalCount = "total_count"
        case reportedCount = "reported_count"
        case actionDoneCount = "action_done_count"
        case resolvedCount = "resolved_count"
        case urgentCount = "urgent_count"
        case unresolvedCount = "unresolved_count"
        case lastUpdated = "last_updated"
        case serverTimestamp = "server_timestamp"
        case dataVersion = "data_version"
        case changed
        case gitChanged = "git_changed"
        case gitSyncError = "git_sync_error"
        case gitUnmatchedIDs = "git_unmatched_ids"
        case updatedAt = "updated_at"
    }
}

private struct AdminVerifyRequest: Encodable {
    let adminToken: String

    enum CodingKeys: String, CodingKey {
        case adminToken = "admin_token"
    }
}

private struct AdminVerifyResponse: Decodable {
    let ok: Bool
    let admin: Bool
}

private struct SectionHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.title3.bold())
            Text(subtitle)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct LocalizedStockNameView: View {
    let name: String
    let ticker: String
    let market: String
    var primaryFont: Font = .subheadline.bold()
    var secondaryFont: Font = .caption2.weight(.medium)

    private var koreanName: String {
        StockDisplayName.localizedName(name, ticker: ticker, market: market)
    }

    private var englishName: String? {
        StockDisplayName.englishName(name, ticker: ticker, market: market)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(koreanName)
                .font(primaryFont)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            if let englishName {
                Text(englishName)
                    .font(secondaryFont)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.78)
            }
        }
    }
}

private enum NewsDigest {
    static func oneLine(_ candidates: String..., fallback: String) -> String {
        let raw = candidates
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty && $0 != "-" } ?? fallback
        let cleaned = raw
            .replacingOccurrences(of: "AI 핵심 시그널:", with: "")
            .replacingOccurrences(of: "관련 섹터 영향:", with: "")
            .replacingOccurrences(of: "\n", with: " ")
            .components(separatedBy: "|")
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? fallback
        if cleaned.count <= 40 {
            return cleaned
        }
        return String(cleaned.prefix(38)) + "..."
    }

    static func stars(score: Int, strength: Int) -> String {
        let level = max(1, min(5, max(abs(score) / 20, strength / 2, 1)))
        return String(repeating: "★", count: level) + String(repeating: "☆", count: 5 - level)
    }
}

private struct TodayScoreHomeCard: View {
    let score: Int
    let state: String
    let confidence: Int
    let briefing: String
    let totalCount: Int
    let liveCount: Int

    var tint: Color {
        if score >= 82 { return .red }
        if score >= 68 { return .mint }
        return .blue
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("TODAY SCORE")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                    Text("\(score)")
                        .font(.system(size: 44, weight: .heavy, design: .rounded).monospacedDigit())
                        .foregroundStyle(tint)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 6) {
                    Text(state)
                        .font(.headline.bold())
                        .foregroundStyle(tint)
                    Text("AI 신뢰도 \(confidence)%")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                }
            }
            HStack(spacing: 8) {
                StatusPill(title: "데이터 최신", tint: .mint)
                StatusPill(title: "분석 \(totalCount)개", tint: .gray, isNeutral: true)
                StatusPill(title: "실시간 \(liveCount)개", tint: .gray, isNeutral: true)
            }
            Text(briefing)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.primary)
                .lineLimit(2)
        }
        .padding(16)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(tint.opacity(0.22), lineWidth: 1))
    }
}

private struct StatusPill: View {
    let title: String
    let tint: Color
    var isNeutral: Bool = false

    var body: some View {
        Text(title)
            .font(.caption2.bold())
            .foregroundStyle(isNeutral ? .secondary : tint)
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background((isNeutral ? Color.white.opacity(0.07) : tint.opacity(0.12)), in: Capsule())
    }
}

private struct HomeFeaturedPickCard: View {
    let result: ScannerResult?
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "오늘의 AI 추천", subtitle: "앱을 열면 가장 먼저 볼 종목")

            if let result {
                NavigationLink {
                    ResultDetailView(
                        result: result,
                        isFavorite: favoriteTickers.contains(result.ticker),
                        recommendationDate: aiPickDates[result.ticker]
                    ) {
                        toggleFavorite(result)
                    }
                } label: {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack(alignment: .top, spacing: 8) {
                            LocalizedStockNameView(
                                name: result.name,
                                ticker: result.ticker,
                                market: result.marketText,
                                primaryFont: .title3.bold(),
                                secondaryFont: .caption.weight(.medium)
                            )
                            .layoutPriority(1)
                            Spacer()
                            Text("\(result.todayScore)")
                                .font(.title2.monospacedDigit().weight(.heavy))
                                .foregroundStyle(result.todayScoreTint)
                                .lineLimit(1)
                        }
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 82), spacing: 7)], alignment: .leading, spacing: 7) {
                            StatusPill(title: result.eventGrade, tint: result.todayScoreTint)
                            StatusPill(title: result.isChaseRiskForAi ? "과열 주의" : "강세", tint: result.isChaseRiskForAi ? .orange : .mint)
                            StatusPill(title: result.hasCriticalNewsRisk ? "악재 체크" : "리스크 낮음", tint: result.hasCriticalNewsRisk ? .red : .gray, isNeutral: !result.hasCriticalNewsRisk)
                        }
                        Text(result.simpleReason)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.primary)
                            .lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(result.newsV2CoreSignalText)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(14)
                    .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(result.todayScoreTint.opacity(0.24), lineWidth: 1))
                }
                .buttonStyle(.plain)
            } else {
                Text("오늘은 무리해서 띄울 AI 추천이 없습니다. 새 뉴스/수급이 들어오면 자동으로 바뀝니다.")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }
}

private struct HomeTopPicksCard: View {
    let picks: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                SectionHeader(title: "AI 추천 TOP", subtitle: "오늘 우선 볼 종목")
                Spacer()
                Text("\(picks.count)")
                    .font(.headline.bold())
                    .foregroundStyle(.mint)
            }

            if picks.isEmpty {
                Text("현재 기준 TOP 추천 없음 · 관망 우세")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
            } else {
                ForEach(Array(picks.prefix(5).enumerated()), id: \.element.id) { index, result in
                    NavigationLink {
                        ResultDetailView(
                            result: result,
                            isFavorite: favoriteTickers.contains(result.ticker),
                            recommendationDate: aiPickDates[result.ticker]
                        ) {
                            toggleFavorite(result)
                        }
                    } label: {
                        HomePickRow(rank: index + 1, result: result)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct HomePickRow: View {
    let rank: Int
    let result: ScannerResult

    var body: some View {
        HStack(spacing: 10) {
            Text("\(rank)")
                .font(.caption.bold())
                .foregroundStyle(.black)
                .frame(width: 24, height: 24)
                .background(Color.mint, in: Circle())
            VStack(alignment: .leading, spacing: 3) {
                LocalizedStockNameView(
                    name: result.name,
                    ticker: result.ticker,
                    market: result.marketText,
                    primaryFont: .subheadline.bold(),
                    secondaryFont: .caption2.weight(.medium)
                )
                Text(result.simpleReason)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 3) {
                Text("\(result.earlySignalProbability)%")
                    .font(.caption.monospacedDigit().bold())
                    .foregroundStyle(result.todayScoreTint)
                Text(riskText)
                    .font(.caption2.bold())
                    .foregroundStyle(result.hasCriticalNewsRisk ? .red : .secondary)
                    .lineLimit(1)
            }
        }
        .padding(9)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }

    private var riskText: String {
        if result.hasCriticalNewsRisk {
            return "악재 주의"
        }
        if result.isChaseRiskForAi {
            return "과열 주의"
        }
        if result.changePercent < -3 {
            return "흐름 약함"
        }
        return "리스크 낮음"
    }
}

private struct HomeEarningsBriefCard: View {
    let candidates: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    private var usCandidates: [ScannerResult] {
        Array(candidates.filter { $0.marketText == "미장" }.prefix(3))
    }

    private var koreaCandidates: [ScannerResult] {
        Array(candidates.filter { $0.marketText == "국장" }.prefix(3))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "곧 실적 발표", subtitle: "발표일 · AI 방향 · 리스크 먼저 확인")

            if usCandidates.isEmpty && koreaCandidates.isEmpty {
                Text("실적 일정 후보를 계산할 데이터가 없습니다.")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            } else {
                if !usCandidates.isEmpty {
                    HomeEarningsMarketGroup(
                        title: "🇺🇸 미국시장",
                        candidates: usCandidates,
                        favoriteTickers: favoriteTickers,
                        aiPickDates: aiPickDates,
                        toggleFavorite: toggleFavorite
                    )
                }

                if !koreaCandidates.isEmpty {
                    HomeEarningsMarketGroup(
                        title: "🇰🇷 한국시장",
                        candidates: koreaCandidates,
                        favoriteTickers: favoriteTickers,
                        aiPickDates: aiPickDates,
                        toggleFavorite: toggleFavorite
                    )
                }
            }

            Text("캐나다 종목은 제외합니다. 공식 실적 캘린더가 서버에 붙기 전까지는 미국/한국 예상 일정 기준입니다.")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private enum EarningsMarket: String, CaseIterable, Identifiable {
    case korea
    case us

    var id: String { rawValue }
    var title: String { self == .korea ? "🇰🇷 한국 주식 실적 발표" : "🇺🇸 미국 주식 실적 발표" }
    var shortTitle: String { self == .korea ? "국장" : "미장" }

    func matches(_ result: ScannerResult) -> Bool {
        switch self {
        case .korea: return result.marketText == "국장"
        case .us: return result.marketText == "미장"
        }
    }
}

private enum EarningsDateRange: String, CaseIterable, Identifiable {
    case today
    case tomorrow
    case thisWeek
    case nextWeek
    case thisMonth
    case selectedDate

    var id: String { rawValue }
    var title: String {
        switch self {
        case .today: return "오늘"
        case .tomorrow: return "내일"
        case .thisWeek: return "이번 주"
        case .nextWeek: return "다음 주"
        case .thisMonth: return "이번 달"
        case .selectedDate: return "날짜"
        }
    }

    func contains(_ date: Date, selectedDate: Date) -> Bool {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone.current
        let today = calendar.startOfDay(for: Date())
        let target = calendar.startOfDay(for: date)

        switch self {
        case .today:
            return calendar.isDate(target, inSameDayAs: today)
        case .tomorrow:
            guard let tomorrow = calendar.date(byAdding: .day, value: 1, to: today) else { return false }
            return calendar.isDate(target, inSameDayAs: tomorrow)
        case .thisWeek:
            return calendar.isDate(target, equalTo: today, toGranularity: .weekOfYear)
        case .nextWeek:
            guard let nextWeek = calendar.date(byAdding: .weekOfYear, value: 1, to: today) else { return false }
            return calendar.isDate(target, equalTo: nextWeek, toGranularity: .weekOfYear)
        case .thisMonth:
            return calendar.isDate(target, equalTo: today, toGranularity: .month)
        case .selectedDate:
            return calendar.isDate(target, inSameDayAs: selectedDate)
        }
    }
}

private struct EarningsCenterSection: View {
    let results: [ScannerResult]
    @Binding var selectedMarket: EarningsMarket
    @Binding var selectedRange: EarningsDateRange
    @Binding var selectedDate: Date
    let favoriteTickers: Set<String>
    let positionTickers: Set<String>
    let toggleFavorite: (ScannerResult) -> Void

    private var items: [EarningsCenterItem] {
        results
            .filter { selectedMarket.matches($0) }
            .map { EarningsCenterItem(result: $0, favoriteTickers: favoriteTickers, positionTickers: positionTickers) }
            .filter { selectedRange.contains($0.preview.date, selectedDate: selectedDate) }
            .sorted { lhs, rhs in
                if lhs.priorityGroup != rhs.priorityGroup {
                    return lhs.priorityGroup < rhs.priorityGroup
                }
                if lhs.importanceScore != rhs.importanceScore {
                    return lhs.importanceScore > rhs.importanceScore
                }
                return lhs.preview.date < rhs.preview.date
            }
    }

    private var featuredItems: [EarningsCenterItem] {
        Array(items.prefix(3))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "실적 센터", subtitle: "국장/미장 분리 · AI 중요도 · 발표 전후 분석")

            Picker("실적 시장", selection: $selectedMarket) {
                ForEach(EarningsMarket.allCases) { market in
                    Text(market.shortTitle).tag(market)
                }
            }
            .pickerStyle(.segmented)

            Picker("실적 기간", selection: $selectedRange) {
                ForEach(EarningsDateRange.allCases) { range in
                    Text(range.title).tag(range)
                }
            }
            .pickerStyle(.segmented)

            if selectedRange == .selectedDate {
                DatePicker("날짜 선택", selection: $selectedDate, displayedComponents: .date)
                    .datePickerStyle(.compact)
                    .font(.caption.weight(.semibold))
                    .padding(10)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            }

            EarningsImportanceLegend(items: featuredItems)

            if items.isEmpty {
                EmptySearchView(
                    hasSearchText: false,
                    canResetFilters: selectedRange != .thisMonth,
                    resetAction: { selectedRange = .thisMonth }
                )
            } else {
                LazyVStack(spacing: 10) {
                    ForEach(items) { item in
                        EarningsCenterRow(item: item, toggleFavorite: { toggleFavorite(item.result) })
                    }
                }
            }

            Text("공식 실적 캘린더 원천이 연결되기 전까지 발표일/컨센서스는 스캐너 데이터와 분기 패턴 기반 추정치입니다. 공식 API가 들어오면 같은 화면에 실제 EPS/매출과 서프라이즈를 자동 반영하도록 분리했습니다.")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct EarningsCenterItem: Identifiable {
    let result: ScannerResult
    let preview: EarningsPreview
    let prediction: EarningsPrediction
    let isFavorite: Bool
    let isPosition: Bool
    let importanceScore: Int

    var id: String { "\(result.ticker)-\(preview.displayDate)" }
    var priorityGroup: Int { isPosition ? 0 : (isFavorite ? 1 : 2) }
    var priorityLabel: String? { isPosition ? "⭐ 보유 종목" : (isFavorite ? "⭐ 관심 종목" : nil) }
    var starText: String {
        let filled = max(1, min(5, Int(ceil(Double(importanceScore) / 20.0))))
        return String(repeating: "★", count: filled) + String(repeating: "☆", count: 5 - filled)
    }
    var marketTimingText: String {
        if result.marketText == "미장" {
            if preview.sessionText.contains("마감") { return "After Market" }
            if preview.sessionText.contains("장전") { return "Before Market" }
            return "During Market"
        }
        if preview.sessionText.contains("장전") { return "장전" }
        if preview.sessionText.contains("장중") { return "장중" }
        return "장후"
    }
    var estimatedEPS: String {
        let base = max(0.01, Double(result.analystNewsScore + result.analystTechnicalScore) / 110.0)
        return result.marketText == "미장" ? "$\(String(format: "%.2f", base))" : "\(String(format: "%.0f", base * 1000))원"
    }
    var estimatedRevenue: String {
        if result.marketText == "미장" {
            return "$\(String(format: "%.1f", max(0.5, result.tradeValueForRanking / 1_000_000_000)))B"
        }
        return "-"
    }
    var marketCapText: String {
        let proxy = result.tradeValueForRanking * 20
        if result.marketText == "국장" {
            return "\(Int(proxy / 100_000_000).formatted())억"
        }
        return "$\(String(format: "%.1f", proxy / 1_000_000_000))B"
    }
    var yearOverYearText: String {
        let change = result.mobileNewsImpactScore + Int(result.changePercent * 2)
        if change >= 20 { return "전년 대비 개선 기대" }
        if change <= -20 { return "전년 대비 둔화 우려" }
        return "전년 대비 중립"
    }
    var epsSurpriseText: String { preview.daysUntil == 0 ? "발표 후 갱신" : "대기" }
    var revenueSurpriseText: String { preview.daysUntil == 0 ? "발표 후 갱신" : "대기" }
    var afterHoursMoveText: String {
        guard preview.daysUntil == 0 else { return "발표 후 갱신" }
        return result.changeBadgeText
    }
    var postSummary: String {
        guard preview.daysUntil == 0 else {
            return "AI 평가: 발표 후 실제 EPS/매출과 시간외 변동을 자동 반영합니다."
        }
        if prediction.upsideProbability >= 62 {
            return "AI 평가: 기대치 상회 가능성이 높아 섹터 심리에 긍정적 영향을 줄 수 있습니다."
        }
        if prediction.upsideProbability <= 42 {
            return "AI 평가: 기대치 하회 또는 선반영 부담을 경계해야 합니다."
        }
        return "AI 평가: 실적 확인 후 가이던스와 거래량 반응이 핵심입니다."
    }
    var aiExpectation: String {
        if prediction.upsideProbability >= 62 { return "시장 기대치 상회 기대" }
        if prediction.upsideProbability <= 42 { return "시장 기대치 부담 우세" }
        return "시장 기대치 중립"
    }
    var aiTrend: String {
        "뉴스 \(result.analystNewsScore) · 수급 \(result.analystFlowScore) · 섹터 \(result.analystSectorScore)"
    }
    var optionVolatility: String {
        if result.marketText == "미장" {
            return result.volumeRatio >= 2 ? "옵션 변동성 확대 추정" : "옵션 변동성 보통 추정"
        }
        return "파생 변동성 확인 대기"
    }
    var expectedMove: String {
        let move = min(18.0, max(3.0, abs(result.changePercent) + max(1.0, result.volumeRatio) * 1.8))
        return "발표 후 예상 변동성 ±\(String(format: "%.1f", move))%"
    }

    init(result: ScannerResult, favoriteTickers: Set<String>, positionTickers: Set<String>) {
        self.result = result
        self.preview = EarningsPreview.make(for: result)
        self.prediction = EarningsPrediction.make(for: result, preview: preview)
        self.isFavorite = favoriteTickers.contains(result.ticker)
        self.isPosition = positionTickers.contains(result.ticker)
        var score = 35
        score += min(25, Int(log10(max(result.tradeValueForRanking, 1)) * 4))
        score += min(18, max(0, result.analystSectorScore - 50))
        score += result.isAiPick ? 10 : 0
        score += isFavorite ? 12 : 0
        score += isPosition ? 18 : 0
        score += ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AMD"].contains(result.ticker.uppercased()) ? 16 : 0
        self.importanceScore = min(100, max(1, score))
    }
}

private struct EarningsImportanceLegend: View {
    let items: [EarningsCenterItem]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("AI 중요도")
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            if items.isEmpty {
                Text("필터 조건에 맞는 실적 후보가 없습니다.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(items) { item in
                    HStack(spacing: 8) {
                        Text(item.starText)
                            .font(.caption.monospacedDigit().bold())
                            .foregroundStyle(.yellow)
                        Text(item.result.name)
                            .font(.caption.weight(.semibold))
                            .lineLimit(1)
                        Spacer()
                        Text(item.result.tickerCleanText)
                            .font(.caption2.monospacedDigit().bold())
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(12)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct EarningsCenterRow: View {
    let item: EarningsCenterItem
    let toggleFavorite: () -> Void
    @State private var showAnalysis = true
    @State private var alertMode: EarningsAlertMode = .none

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 4) {
                    if let priority = item.priorityLabel {
                        Text(priority)
                            .font(.caption2.bold())
                            .foregroundStyle(.yellow)
                    }
                    Text(item.result.name)
                        .font(.headline)
                        .lineLimit(2)
                    Text("\(item.result.tickerCleanText) · \(item.result.sectorCategoryName)")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(action: toggleFavorite) {
                    Image(systemName: item.isFavorite ? "star.fill" : "star")
                        .foregroundStyle(item.isFavorite ? .yellow : .secondary)
                }
                .buttonStyle(.plain)
            }

            HStack(spacing: 8) {
                DetailMiniMetric(title: item.result.marketText == "국장" ? "발표 예정일" : "Earnings Date", value: item.preview.displayDate, tint: item.preview.tint)
                DetailMiniMetric(title: "발표 시간", value: item.marketTimingText, tint: .orange)
                DetailMiniMetric(title: "중요도", value: item.starText, tint: .yellow)
            }

            if item.result.marketText == "국장" {
                HStack(spacing: 8) {
                    DetailMiniMetric(title: "예상 EPS", value: item.estimatedEPS, tint: .mint)
                    DetailMiniMetric(title: "전년 대비", value: item.yearOverYearText, tint: item.prediction.tint)
                    DetailMiniMetric(title: "시가총액", value: item.marketCapText, tint: .secondary)
                }
            } else {
                HStack(spacing: 8) {
                    DetailMiniMetric(title: "예상 EPS", value: item.estimatedEPS, tint: .mint)
                    DetailMiniMetric(title: "예상 매출", value: item.estimatedRevenue, tint: .secondary)
                    DetailMiniMetric(title: "예상 변동", value: item.expectedMove, tint: .orange)
                }
                HStack(spacing: 8) {
                    DetailMiniMetric(title: "EPS Surprise", value: item.epsSurpriseText, tint: .mint)
                    DetailMiniMetric(title: "Revenue Surprise", value: item.revenueSurpriseText, tint: .mint)
                    DetailMiniMetric(title: "시간외", value: item.afterHoursMoveText, tint: item.result.changePercent >= 0 ? .red : .blue)
                }
            }

            DisclosureGroup(isExpanded: $showAnalysis) {
                VStack(alignment: .leading, spacing: 8) {
                    AnalystBulletBlock(title: "AI 영향 분석", points: [
                        item.aiExpectation,
                        "최근 실적 추세: \(item.aiTrend)",
                        "최근 뉴스 영향: \(item.result.newsActionText)",
                        item.optionVolatility,
                        item.expectedMove,
                        "투자 유의사항: \(item.prediction.risks.first ?? "발표 직후 변동성 확대 가능")"
                    ])
                    Text(item.postSummary)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.primary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.top, 8)
            } label: {
                Label("AI 분석 / 발표 후 업데이트", systemImage: "brain.head.profile")
                    .font(.caption.bold())
            }

            Picker("알림", selection: $alertMode) {
                ForEach(EarningsAlertMode.allCases) { mode in
                    Text(mode.title).tag(mode)
                }
            }
            .pickerStyle(.menu)
            .font(.caption)
        }
        .padding(12)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private enum EarningsAlertMode: String, CaseIterable, Identifiable {
    case none
    case dayBefore
    case hourBefore
    case afterRelease
    case aiDone

    var id: String { rawValue }
    var title: String {
        switch self {
        case .none: return "알림 없음"
        case .dayBefore: return "발표 하루 전"
        case .hourBefore: return "발표 1시간 전"
        case .afterRelease: return "발표 직후"
        case .aiDone: return "AI 분석 완료 시"
        }
    }
}

private struct HomeEarningsMarketGroup: View {
    let title: String
    let candidates: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)

            ForEach(candidates) { result in
                let preview = EarningsPreview.make(for: result)
                let prediction = EarningsPrediction.make(for: result, preview: preview)
                NavigationLink {
                    ResultDetailView(
                        result: result,
                        isFavorite: favoriteTickers.contains(result.ticker),
                        recommendationDate: aiPickDates[result.ticker]
                    ) {
                        toggleFavorite(result)
                    }
                } label: {
                    HomeEarningsRow(result: result, preview: preview, prediction: prediction)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

private struct HomeEarningsRow: View {
    let result: ScannerResult
    let preview: EarningsPreview
    let prediction: EarningsPrediction

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .top, spacing: 8) {
                HStack(alignment: .top, spacing: 6) {
                    Text(marketEmoji)
                        .font(.subheadline)
                    LocalizedStockNameView(
                        name: result.name,
                        ticker: result.ticker,
                        market: result.marketText,
                        primaryFont: .subheadline.bold(),
                        secondaryFont: .caption2.weight(.medium)
                    )
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(result.ticker)
                        .font(.caption2.monospaced().weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Text(preview.dDayText)
                    .font(.caption.monospacedDigit().bold())
                    .foregroundStyle(preview.tint)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(preview.tint.opacity(0.12), in: Capsule())
            }

            HStack(spacing: 8) {
                Label(preview.displayDate, systemImage: "calendar.badge.clock")
                    .foregroundStyle(preview.tint)
                Text(preview.sessionText)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
                Text("\(prediction.upsideProbability)%")
                    .font(.caption.monospacedDigit().bold())
                    .foregroundStyle(prediction.tint)
            }
            .font(.caption.weight(.semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.78)

            Text("\(prediction.directionText) · \(prediction.reasons.prefix(2).joined(separator: " / "))")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(preview.tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(preview.tint.opacity(0.22), lineWidth: 1))
    }

    private var marketEmoji: String {
        result.marketText == "미장" ? "🇺🇸" : "🇰🇷"
    }
}

private struct HomeMarketSignalCard: View {
    let leading: ScannerResult?
    let sectorRanks: [SectorInflowRank]
    let positionSummary: PortfolioRiskSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "시장 시그널", subtitle: "선행 탐지 · 강한 섹터 · 자금 이동 · 수급")
            SignalMiniRow(
                title: "선행 탐지",
                value: leading.map { "\($0.name) · \($0.notYetMovedProbability)%" } ?? "대기",
                systemImage: "scope",
                tint: .pink
            )
            SignalMiniRow(
                title: "강한 섹터",
                value: sectorRanks.first.map { "\($0.shortSectorName) · \($0.versusYesterdayText)" } ?? "대기",
                systemImage: "square.grid.2x2.fill",
                tint: .blue
            )
            SignalMiniRow(
                title: "자금 이동",
                value: sectorRanks.first?.detailText ?? "계산 대기",
                systemImage: "banknote.fill",
                tint: .mint
            )
            SignalMiniRow(
                title: "보유 리스크",
                value: "집중도 \(positionSummary.concentrationText) · \(positionSummary.sectorBiasText)",
                systemImage: "shield.lefthalf.filled",
                tint: .orange
            )
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct SignalMiniRow: View {
    let title: String
    let value: String
    let systemImage: String
    let tint: Color

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: systemImage)
                .font(.caption.bold())
                .foregroundStyle(tint)
                .frame(width: 24)
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)
                .frame(width: 70, alignment: .leading)
            Text(value)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
            Spacer(minLength: 0)
        }
    }
}

private struct HomeNewsBriefingCard: View {
    let news: [ScannerResult]

    private var positive: ScannerResult? {
        news.first { $0.mobileNewsImpactScore >= 10 } ?? news.first
    }

    private var negative: ScannerResult? {
        news.first { $0.mobileNewsImpactScore <= -10 || $0.hasCriticalNewsRisk }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "뉴스 브리핑", subtitle: "주요 호재 · 악재 · AI 뉴스 요약")
            SignalMiniRow(
                title: "호재",
                value: positive.map { "\($0.name) · \($0.mobileNewsImpactLabel.isEmpty ? $0.newsActionText : $0.mobileNewsImpactLabel)" } ?? "대기",
                systemImage: "arrow.up.circle.fill",
                tint: .red
            )
            SignalMiniRow(
                title: "악재",
                value: negative.map { "\($0.name) · \($0.newsRiskAlertText)" } ?? "중대 악재 대기",
                systemImage: "arrow.down.circle.fill",
                tint: .orange
            )
            Text(news.first?.newsV2CoreSignalText ?? "AI 뉴스 요약 대기")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct DashboardNavigationCard: View {
    let title: String
    let subtitle: String
    let systemImage: String
    let tint: Color
    let count: Int

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.headline)
                .foregroundStyle(tint)
                .frame(width: 34, height: 34)
                .background(tint.opacity(0.12), in: Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.subheadline.bold())
                Text(subtitle)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            Text("\(count)")
                .font(.headline.monospacedDigit().bold())
                .foregroundStyle(tint)
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(tint.opacity(0.18), lineWidth: 1))
    }
}

private struct DashboardInfoCard: View {
    let title: String
    let subtitle: String
    let footnote: String
    let systemImage: String
    let tint: Color

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.headline)
                .foregroundStyle(tint)
                .frame(width: 36, height: 36)
                .background(tint.opacity(0.12), in: Circle())
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.subheadline.bold())
                Text(subtitle)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                Text(footnote)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct MarketPulseSummaryCard: View {
    let sections: [MarketStrengthSection]
    let flowRadar: MoneyFlowRadarData

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "시장 요약", subtitle: flowRadar.topSummary)
            ForEach(sections.prefix(3)) { section in
                SignalMiniRow(
                    title: section.market,
                    value: section.summaries.first.map { "\($0.category) · \($0.changeText)" } ?? "데이터 대기",
                    systemImage: section.iconName,
                    tint: .blue
                )
            }
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct DailyMoverSummaryCard: View {
    let gainers: [ScannerResult]
    let losers: [ScannerResult]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "등락 지도", subtitle: "오늘 많이 오른/내린 종목")
            SignalMiniRow(
                title: "상승",
                value: gainers.first.map { "\($0.name) \($0.changeBadgeText)" } ?? "대기",
                systemImage: "arrow.up.right.circle.fill",
                tint: .red
            )
            SignalMiniRow(
                title: "하락",
                value: losers.first.map { "\($0.name) \($0.changeBadgeText)" } ?? "대기",
                systemImage: "arrow.down.right.circle.fill",
                tint: .blue
            )
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct EmptySearchView: View {
    let hasSearchText: Bool
    let canResetFilters: Bool
    let resetAction: () -> Void

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: hasSearchText ? "magnifyingglass" : "tray")
                .font(.title2)
                .foregroundStyle(.secondary)
            Text(hasSearchText ? "검색 결과 없음" : "표시할 종목 없음")
                .font(.headline)
            Text(hasSearchText ? "종목명이나 티커를 다시 입력해보세요." : "다른 필터를 선택해보세요.")
                .font(.caption)
                .foregroundStyle(.secondary)
            if canResetFilters {
                Button("전체 종목 보기", action: resetAction)
                    .font(.caption.bold())
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(AppColors.panelSoft, in: Capsule())
                    .foregroundStyle(.white)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 44)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct MainResultListSection: View {
    let displayedResults: [ScannerResult]
    let favoriteTickers: Set<String>
    let newAiPickTickers: Set<String>
    let aiPickDates: [String: String]
    let positionEvaluations: [String: PositionEvaluation]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        LazyVStack(spacing: 10) {
            ForEach(displayedResults) { result in
                NavigationLink {
                    ResultDetailView(
                        result: result,
                        isFavorite: favoriteTickers.contains(result.ticker),
                        recommendationDate: aiPickDates[result.ticker]
                    ) {
                        toggleFavorite(result)
                    }
                } label: {
                    ResultCard(
                        result: result,
                        isFavorite: favoriteTickers.contains(result.ticker),
                        isNewAiPick: newAiPickTickers.contains(result.ticker),
                        recommendationDate: aiPickDates[result.ticker],
                        positionEvaluation: positionEvaluations[result.ticker]
                    )
                }
                .buttonStyle(.plain)
            }
        }
        .transaction { transaction in
            transaction.animation = nil
        }
    }
}

enum FavoriteStore {
    private static let key = "favoriteTickers"

    static func load() -> Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: key) ?? [])
    }

    static func save(_ tickers: Set<String>) {
        UserDefaults.standard.set(Array(tickers).sorted(), forKey: key)
    }
}

private enum MarketResultsCache {
    struct Snapshot: Codable {
        let rows: [[String: String]]
        let fileUpdatedAt: String?
        let dataGeneratedAt: String?
        let updatedAt: String
        let savedAt: Date
    }

    struct Loaded {
        let results: [ScannerResult]
        let dataGeneratedAt: String?
        let savedAt: Date
    }

    private static let fileName = "market-results-cache.json"

    static func save(payload: ResultsPayload) {
        guard !payload.rows.isEmpty else {
            return
        }
        let totalCount = payload.totalCount ?? payload.count
        if payload.limited == true && totalCount >= 500 && payload.rows.count < min(totalCount, 500) {
            print("[MarketResultsCache] skip sparse limited payload rows=\(payload.rows.count) total=\(totalCount)")
            return
        }
        if totalCount >= 500 && payload.rows.count < 500 {
            print("[MarketResultsCache] skip sparse payload rows=\(payload.rows.count) total=\(totalCount)")
            return
        }
        let snapshot = Snapshot(
            rows: payload.rows,
            fileUpdatedAt: payload.fileUpdatedAt,
            dataGeneratedAt: payload.dataGeneratedAt,
            updatedAt: payload.updatedAt,
            savedAt: Date()
        )
        do {
            let data = try JSONEncoder().encode(snapshot)
            let url = try cacheURL()
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try data.write(to: url, options: [.atomic])
        } catch {
            print("[MarketResultsCache] save failed: \(error.localizedDescription)")
        }
    }

    static func load() -> Loaded? {
        do {
            let data = try Data(contentsOf: try cacheURL())
            let snapshot = try JSONDecoder().decode(Snapshot.self, from: data)
            let results = CSVLoader.results(from: snapshot.rows)
            guard !results.isEmpty else {
                return nil
            }
            if results.count < 500 {
                print("[MarketResultsCache] skip stale sparse startup cache rows=\(results.count)")
                return nil
            }
            return Loaded(
                results: results,
                dataGeneratedAt: snapshot.dataGeneratedAt,
                savedAt: snapshot.savedAt
            )
        } catch {
            return nil
        }
    }

    private static func cacheURL() throws -> URL {
        let directory = try FileManager.default.url(
            for: .cachesDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return directory.appendingPathComponent(fileName, isDirectory: false)
    }
}

enum PositionStore {
    private static let key = "positionInputs"

    struct Position {
        let priceText: String
        let amountText: String
        let targetText: String
    }

    static func load(ticker: String) -> Position? {
        let saved = UserDefaults.standard.dictionary(forKey: key) as? [String: [String: String]] ?? [:]
        guard let item = saved[ticker] else {
            return nil
        }
        return Position(
            priceText: item["price"] ?? "",
            amountText: amountText(from: item),
            targetText: item["target"] ?? ""
        )
    }

    static func loadAll() -> [String: Position] {
        let saved = UserDefaults.standard.dictionary(forKey: key) as? [String: [String: String]] ?? [:]
        return Dictionary(
            uniqueKeysWithValues: saved.map { ticker, item in
                (
                    ticker,
                    Position(
                        priceText: item["price"] ?? "",
                        amountText: amountText(from: item),
                        targetText: item["target"] ?? ""
                    )
                )
            }
        )
    }

    static func save(ticker: String, priceText: String, amountText: String, targetText: String = "") {
        var saved = UserDefaults.standard.dictionary(forKey: key) as? [String: [String: String]] ?? [:]
        let cleanPrice = priceText.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanAmount = amountText.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanTarget = targetText.trimmingCharacters(in: .whitespacesAndNewlines)

        if cleanPrice.isEmpty && cleanAmount.isEmpty && cleanTarget.isEmpty {
            saved.removeValue(forKey: ticker)
        } else {
            saved[ticker] = [
                "price": cleanPrice,
                "amount": cleanAmount,
                "target": cleanTarget
            ]
        }

        UserDefaults.standard.set(saved, forKey: key)
    }

    private static func amountText(from item: [String: String]) -> String {
        if let amount = item["amount"], !amount.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return amount
        }
        guard let price = parseNumber(item["price"] ?? ""),
              let quantity = parseNumber(item["quantity"] ?? "") else {
            return ""
        }
        return (price * quantity).formatted(.number.precision(.fractionLength(0...2)))
    }

    private static func parseNumber(_ text: String) -> Double? {
        let cleaned = text
            .replacingOccurrences(of: ",", with: "")
            .replacingOccurrences(of: "원", with: "")
            .replacingOccurrences(of: "$", with: "")
            .replacingOccurrences(of: "CAD", with: "", options: .caseInsensitive)
            .replacingOccurrences(of: "USD", with: "", options: .caseInsensitive)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let value = Double(cleaned), value > 0 else {
            return nil
        }
        return value
    }
}

private struct PositionEvaluation {
    let result: ScannerResult
    let totalAmount: Double
    let currentValue: Double
    let profitPercent: Double
    let action: String
    let summary: String
    let detail: String
    let plan: String
    let judgement: String
    let tint: Color

    init?(result: ScannerResult, buyPrice: Double, totalAmount: Double) {
        guard buyPrice > 0, totalAmount > 0, let current = result.currentPrice else {
            return nil
        }

        let quantity = totalAmount / buyPrice
        let profit = totalAmount * ((current / buyPrice) - 1)
        let profitPercent = ((current / buyPrice) - 1) * 100
        let currentValue = current * quantity
        let takeProfit = Self.takeProfitPrice(result: result, buyPrice: buyPrice, current: current)
        let stopLoss = Self.stopLossPrice(result: result, buyPrice: buyPrice, current: current)
        let profitText = Self.formatMoney(abs(profit), marketText: result.marketText)
        let currentValueText = Self.formatMoney(currentValue, marketText: result.marketText)
        let takeProfitText = Self.formatMoney(takeProfit, marketText: result.marketText)
        let stopLossText = Self.formatMoney(stopLoss, marketText: result.marketText)
        let quantityText = Self.formatQuantity(quantity)

        let action: String
        let tint: Color
        let judgement: String

        if profitPercent >= 25 {
            action = "부분 익절 강함"
            tint = .red
            judgement = "판단: 수익이 크게 난 구간입니다. 일부 익절 후 남은 물량은 트레일링으로 관리하는 쪽이 좋습니다."
        } else if profitPercent >= 12 {
            action = result.isChaseRiskForAi ? "부분 익절" : "홀딩 + 일부 익절"
            tint = .orange
            judgement = result.isChaseRiskForAi
                ? "판단: 수익권이지만 과열 신호가 있어 일부 익절로 수익을 잠그는 구간입니다."
                : "판단: 흐름은 살아 있습니다. 일부 익절 후 나머지는 손절가를 올려서 가져갈 만합니다."
        } else if profitPercent >= 4 && result.eventScore >= 82 && !result.isChaseRiskForAi {
            action = "추격 상태 좋음"
            tint = .green
            judgement = "판단: 수익권이고 오늘 점수도 살아 있습니다. 신규 추격은 작게, 기존 물량은 홀딩 우선입니다."
        } else if profitPercent >= 0 {
            action = result.changePercent < -3 ? "수익 방어" : "홀딩"
            tint = .mint
            judgement = result.changePercent < -3
                ? "판단: 아직 수익권이지만 당일 흐름이 약합니다. 본전 위에서 방어 기준을 세우는 게 낫습니다."
                : "판단: 매수가를 지키고 있어 홀딩 가능합니다. 거래량과 뉴스가 꺾이는지만 확인하세요."
        } else if current <= stopLoss || profitPercent <= -7 {
            action = "손절/비중축소"
            tint = .blue
            judgement = "판단: 손절 기준에 가까운 구간입니다. 반등 기대보다 리스크 축소를 먼저 봐야 합니다."
        } else if profitPercent <= -3 {
            action = "손절 경계"
            tint = .blue
            judgement = "판단: 약손실이 커지는 구간입니다. 거래량 회복 전 추가매수는 조심하는 편이 좋습니다."
        } else {
            action = "관찰 홀딩"
            tint = .gray
            judgement = "판단: 방향이 애매합니다. 추가매수보다 현재가가 매수가를 회복하는지 먼저 확인하세요."
        }

        let direction = profit >= 0 ? "평가수익" : "평가손실"
        self.result = result
        self.totalAmount = totalAmount
        self.currentValue = currentValue
        self.profitPercent = profitPercent
        self.action = action
        self.tint = tint
        self.summary = "\(action) · \(direction) \(profitText) (\(String(format: "%.2f", abs(profitPercent)))%)"
        self.detail = "투입금액 \(Self.formatMoney(totalAmount, marketText: result.marketText)) · 수량 약 \(quantityText)주 · 현재 평가금액 \(currentValueText)"
        self.plan = "익절가 \(takeProfitText) · 손절가 \(stopLossText)"
        self.judgement = judgement
    }

    static func load(for result: ScannerResult) -> PositionEvaluation? {
        guard let position = PositionStore.load(ticker: result.ticker),
              let buyPrice = parseNumber(position.priceText),
              let totalAmount = parseNumber(position.amountText) else {
            return nil
        }
        return PositionEvaluation(result: result, buyPrice: buyPrice, totalAmount: totalAmount)
    }

    private static func takeProfitPrice(result: ScannerResult, buyPrice: Double, current: Double) -> Double {
        let firstTargetPercent = max(4.0, min(18.0, result.upsidePercent))
        let firstTarget = buyPrice * (1 + firstTargetPercent / 100)
        guard current >= firstTarget else {
            return firstTarget
        }
        let nextTargetPercent = max(3.0, min(8.0, result.upsidePercent * 0.55))
        return current * (1 + nextTargetPercent / 100)
    }

    private static func stopLossPrice(result: ScannerResult, buyPrice: Double, current: Double) -> Double {
        let stopPercent = max(3.0, min(12.0, result.downsidePercent))
        let initialStop = buyPrice * (1 - stopPercent / 100)
        guard current > buyPrice else {
            return initialStop
        }
        let trailingPercent = max(4.0, min(10.0, result.downsidePercent * 0.85))
        let trailingStop = current * (1 - trailingPercent / 100)
        return max(initialStop, trailingStop)
    }

    static func parseNumber(_ text: String) -> Double? {
        let cleaned = text
            .replacingOccurrences(of: ",", with: "")
            .replacingOccurrences(of: "원", with: "")
            .replacingOccurrences(of: "$", with: "")
            .replacingOccurrences(of: "CAD", with: "", options: .caseInsensitive)
            .replacingOccurrences(of: "USD", with: "", options: .caseInsensitive)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let value = Double(cleaned), value > 0 else {
            return nil
        }
        return value
    }

    private static func formatMoney(_ value: Double, marketText: String) -> String {
        if marketText == "국장" {
            return value.formatted(.number.precision(.fractionLength(0))) + "원"
        }
        let currency = marketText == "캐나다" ? " CAD" : " USD"
        return value.formatted(.number.precision(.fractionLength(2))) + currency
    }

    private static func formatQuantity(_ value: Double) -> String {
        if value >= 100 {
            return value.formatted(.number.precision(.fractionLength(1)))
        }
        return value.formatted(.number.precision(.fractionLength(3)))
    }
}

enum NewAiPickStore {
    private static let dateKey = "newAiPickDate.v2"
    private static let tickersKey = "lastAiPickTickers.v2"
    private static let newTickersKey = "newAiPickTickers.v2"
    private static let recommendationDatesKey = "aiPickRecommendationDates.v2"

    struct Update {
        let newTickers: Set<String>
        let recommendationDates: [String: String]
    }

    static func loadNewTickers() -> Set<String> {
        guard UserDefaults.standard.string(forKey: dateKey) == todayKey else {
            return []
        }
        return Set(UserDefaults.standard.stringArray(forKey: newTickersKey) ?? [])
    }

    static func loadRecommendationDates() -> [String: String] {
        UserDefaults.standard.dictionary(forKey: recommendationDatesKey) as? [String: String] ?? [:]
    }

    static func update(currentAiTickers: Set<String>, currentTickers: Set<String>) -> Update {
        let defaults = UserDefaults.standard
        let savedDate = defaults.string(forKey: dateKey)
        let previousTickers = Set(defaults.stringArray(forKey: tickersKey) ?? [])
        let savedNewTickers = Set(defaults.stringArray(forKey: newTickersKey) ?? [])
        var recommendationDates = loadRecommendationDates()

        let newTickers: Set<String>
        if savedDate == nil {
            newTickers = []
        } else if savedDate == todayKey {
            newTickers = savedNewTickers.union(currentAiTickers.subtracting(previousTickers))
        } else {
            newTickers = currentAiTickers.subtracting(previousTickers)
        }

        for ticker in currentAiTickers {
            if recommendationDates[ticker] == nil || recommendationDates[ticker]?.contains("-") == true {
                recommendationDates[ticker] = displayTimestamp
            }
        }

        recommendationDates = recommendationDates.filter { ticker, _ in
            currentAiTickers.contains(ticker)
        }

        defaults.set(todayKey, forKey: dateKey)
        defaults.set(Array(currentAiTickers).sorted(), forKey: tickersKey)
        defaults.set(Array(newTickers).sorted(), forKey: newTickersKey)
        defaults.set(recommendationDates, forKey: recommendationDatesKey)
        return Update(newTickers: newTickers, recommendationDates: recommendationDates)
    }

    private static var todayKey: String {
        AppDateTime.todayKey()
    }

    private static var displayTimestamp: String {
        AppDateTime.shortLocalString(from: Date())
    }
}

private enum MarketDataLoadState {
    case loading
    case latest
    case cache
    case failed
}

private enum ResultFilter: String, CaseIterable, Identifiable {
    case ai
    case buy
    case favorites
    case watch
    case all

    var id: String { rawValue }

    var title: String {
        switch self {
        case .ai:
            return "AI추천"
        case .buy:
            return "매수"
        case .favorites:
            return "내관심"
        case .watch:
            return "관심"
        case .all:
            return "전체"
        }
    }
}

private enum MarketFilter: String, CaseIterable, Identifiable {
    case all
    case korea
    case us
    case canada

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all:
            return "전체"
        case .korea:
            return "국장"
        case .us:
            return "미장"
        case .canada:
            return "캐나다"
        }
    }

    func matches(_ result: ScannerResult) -> Bool {
        switch self {
        case .all:
            return true
        case .korea:
            return result.marketText == "국장"
        case .us:
            return result.marketText == "미장"
        case .canada:
            return result.marketText == "캐나다"
        }
    }
}

private enum DividendFilter: String, CaseIterable, Identifiable {
    case all
    case high
    case low

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all:
            return "배당 전체"
        case .high:
            return "고배당"
        case .low:
            return "저배당"
        }
    }

    func matches(_ result: ScannerResult) -> Bool {
        switch self {
        case .all:
            return true
        case .high:
            return result.marketText == "캐나다" && result.dividendText == "고배당"
        case .low:
            return result.marketText == "캐나다" && result.dividendText == "저배당"
        }
    }
}

private struct HeaderView: View {
    let topSummary: String
    let topScore: Int
    let totalCount: Int
    let buyCount: Int
    let aiPickCount: Int
    let liveQuoteCount: Int
    let favoriteCount: Int
    let dataUpdatedAt: Date?
    let quoteRefreshMessage: String
    let isRefreshingQuotes: Bool
    let refreshAction: () -> Void
    let fullScanAction: () -> Void
    let testAlertAction: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("AI 추천")
                        .font(.title.bold())
                    Text(topSummary)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .layoutPriority(1)

                Spacer()

                ScoreBadge(score: topScore)
            }

            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 3) {
                    Label(quoteRefreshMessage, systemImage: isRefreshingQuotes ? "arrow.triangle.2.circlepath" : "clock")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)

                    TimelineView(.periodic(from: Date(), by: 1)) { context in
                        Text(Self.clockFormatter.string(from: context.date))
                            .font(.caption2.monospacedDigit().weight(.semibold))
                            .foregroundStyle(.secondary.opacity(0.78))
                    }
                }

                Spacer()

                HStack(spacing: 8) {
                    Button(action: testAlertAction) {
                        Image(systemName: "bell.badge")
                            .font(.caption.bold())
                            .frame(width: 30, height: 30)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.white)
                    .background(AppColors.panelSoft, in: Circle())
                    .accessibilityLabel("테스트 알림 보내기")

                    Button(action: refreshAction) {
                        Label("빠른", systemImage: "bolt.fill")
                            .font(.caption2.bold())
                            .frame(height: 30)
                            .padding(.horizontal, 8)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.white)
                    .background(Color.mint.opacity(0.22), in: Capsule())
                    .disabled(isRefreshingQuotes)

                    Button(action: fullScanAction) {
                        Label("전체", systemImage: "arrow.triangle.2.circlepath")
                            .font(.caption2.bold())
                            .frame(height: 30)
                            .padding(.horizontal, 8)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.white)
                    .background(AppColors.panelSoft, in: Capsule())
                    .disabled(isRefreshingQuotes)
                }
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 72), spacing: 8)], alignment: .leading, spacing: 8) {
                SummaryPill(title: "전체", value: "\(totalCount)", tint: .blue)
                SummaryPill(title: "매수", value: "\(buyCount)", tint: .green)
                SummaryPill(title: "내관심", value: "\(favoriteCount)", tint: .yellow)
                SummaryPill(title: "AI", value: "\(aiPickCount)", tint: .purple)
            }

            Label(dataFreshnessText, systemImage: dataFreshnessIcon)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(dataFreshnessTint)
                .lineLimit(1)
                .minimumScaleFactor(0.75)

            VStack(alignment: .leading, spacing: 5) {
                Label(serviceStatusText, systemImage: serviceStatusIcon)
                    .foregroundStyle(serviceStatusTint)
                Text(liveQuoteCoverageText)
                    .foregroundStyle(.secondary)
            }
            .font(.caption2.weight(.semibold))
            .lineLimit(2)
            .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
        .padding(.horizontal, 16)
    }

    private var dataFreshnessText: String {
        guard let dataUpdatedAt else {
            return "데이터 갱신 시각 확인 대기"
        }
        return "데이터 \(Self.dateTimeFormatter.string(from: dataUpdatedAt)) · \(dataFreshnessStatus)"
    }

    private var dataFreshnessStatus: String {
        guard let dataUpdatedAt else {
            return "확인 대기"
        }
        let age = Date().timeIntervalSince(dataUpdatedAt)
        if age <= 6 * 3600 {
            return "신선"
        }
        if age <= 24 * 3600 {
            return "주의"
        }
        return "오래됨"
    }

    private var dataFreshnessIcon: String {
        switch dataFreshnessStatus {
        case "신선":
            return "checkmark.seal.fill"
        case "주의":
            return "exclamationmark.triangle.fill"
        default:
            return "clock.badge.exclamationmark"
        }
    }

    private var dataFreshnessTint: Color {
        switch dataFreshnessStatus {
        case "신선":
            return .green
        case "주의":
            return .orange
        default:
            return .red
        }
    }

    private var liveQuoteCoverageText: String {
        guard totalCount > 0 else {
            return "실시간 시세 대기"
        }
        return "실시간 \(liveQuoteCount)/\(totalCount)"
    }

    private var serviceStatusText: String {
        if totalCount == 0 {
            return "운영 상태 대기"
        }
        if dataFreshnessStatus == "오래됨" {
            return "운영 상태: 갱신 필요"
        }
        if liveQuoteCount == 0 {
            return "운영 상태: 시세 대기"
        }
        if liveQuoteCount < min(totalCount, 20) {
            return "운영 상태: 부분 갱신"
        }
        return "운영 상태: 정상"
    }

    private var serviceStatusIcon: String {
        if serviceStatusText.contains("정상") {
            return "bolt.heart.fill"
        }
        if serviceStatusText.contains("부분") || serviceStatusText.contains("대기") {
            return "waveform.path.ecg"
        }
        return "wrench.and.screwdriver.fill"
    }

    private var serviceStatusTint: Color {
        if serviceStatusText.contains("정상") {
            return .mint
        }
        if serviceStatusText.contains("부분") || serviceStatusText.contains("대기") {
            return .orange
        }
        return .red
    }

    private static let clockFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ko_KR")
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()

    private static let dateTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ko_KR")
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "MM/dd HH:mm:ss"
        return formatter
    }()
}

private struct SummaryPill: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(value)
                .font(.headline.bold())
                .foregroundStyle(tint)
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 10)
        .padding(.horizontal, 10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct TopPriorityShortcut: View {
    let watchlist: [ScannerResult]
    let abnormalCount: Int
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    private var top: ScannerResult? {
        watchlist.first
    }

    var body: some View {
        NavigationLink {
            TodayWatchlistPage(
                watchlist: watchlist,
                abnormalEvents: [],
                missedReview: [],
                favoriteTickers: favoriteTickers,
                aiPickDates: aiPickDates,
                toggleFavorite: toggleFavorite
            )
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "bolt.badge.clock.fill")
                    .font(.headline)
                    .foregroundStyle(.black)
                    .frame(width: 32, height: 32)
                    .background(Color.mint, in: Circle())

                VStack(alignment: .leading, spacing: 3) {
                    Text("오늘 1순위")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                    Text(top.map { "\($0.name) · \($0.eventGrade)" } ?? "오늘 볼 종목 준비중")
                        .font(.subheadline.bold())
                        .foregroundStyle(.primary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .layoutPriority(1)

                Spacer(minLength: 8)

                VStack(alignment: .trailing, spacing: 3) {
                    Text("\(watchlist.count)")
                        .font(.headline.bold())
                        .foregroundStyle(.mint)
                    Text("TOP")
                        .font(.caption2.bold())
                        .foregroundStyle(.secondary)
                }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.mint.opacity(0.22), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct InsightHubView: View {
    let results: [ScannerResult]
    let watchlist: [ScannerResult]
    let abnormalEvents: [ScannerResult]
    let missedReview: [ScannerResult]
    let marketSections: [MarketStrengthSection]
    let flowRadar: MoneyFlowRadarData
    let closingBuyCandidates: [ScannerResult]
    let majorNews: [ScannerResult]
    let leadingCandidates: [ScannerResult]
    let missedCandidates: [ScannerResult]
    let riskCandidates: [ScannerResult]
    let keywordCandidates: [ScannerResult]
    let topGainers: [ScannerResult]
    let topLosers: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("분석")
                    .font(.subheadline.bold())
                Spacer()
                Text("위로 스크롤시 표시")
                    .font(.caption2.bold())
                    .foregroundStyle(.secondary)
            }

            LazyVGrid(columns: Array(repeating: GridItem(.flexible(minimum: 0), spacing: 7), count: 2), spacing: 7) {
                InsightNavigationButton(
                    title: "선행 탐지 AI",
                    subtitle: leadingCandidates.first.map { "\($0.themeKey) 확산 후보 · \($0.name)" } ?? "다음 타자 탐색 중",
                    count: leadingCandidates.count + missedCandidates.count + riskCandidates.count,
                    systemImage: "scope",
                    tint: .pink
                ) {
                    LeadDetectionPage(
                        leadingCandidates: leadingCandidates,
                        missedCandidates: missedCandidates,
                        riskCandidates: riskCandidates,
                        keywordCandidates: keywordCandidates,
                        flowRadar: flowRadar,
                        favoriteTickers: favoriteTickers,
                        aiPickDates: aiPickDates,
                        toggleFavorite: toggleFavorite
                    )
                }

                InsightNavigationButton(
                    title: "금일 강한 섹터",
                    subtitle: marketSections.first?.summaries.first.map { "\($0.category) \($0.changeText)" } ?? "섹터 데이터 없음",
                    count: marketSections.reduce(0) { $0 + $1.summaries.count },
                    systemImage: "square.grid.2x2.fill",
                    tint: .blue
                ) {
                    MarketStrengthPage(
                        sections: marketSections,
                        results: results,
                        favoriteTickers: favoriteTickers,
                        aiPickDates: aiPickDates,
                        toggleFavorite: toggleFavorite
                    )
                }

                InsightNavigationButton(
                    title: "오늘 등락 TOP",
                    subtitle: topGainers.first.map { "상승 \($0.name) \($0.changeBadgeText)" } ?? topLosers.first.map { "하락 \($0.name) \($0.changeBadgeText)" } ?? "등락 데이터 대기",
                    count: topGainers.prefix(20).count + topLosers.prefix(20).count,
                    systemImage: "arrow.up.arrow.down.circle.fill",
                    tint: .red
                ) {
                    DailyMoversPage(
                        gainers: Array(topGainers.prefix(30)),
                        losers: Array(topLosers.prefix(30)),
                        favoriteTickers: favoriteTickers,
                        aiPickDates: aiPickDates,
                        toggleFavorite: toggleFavorite
                    )
                }

                InsightNavigationButton(
                    title: "테마 순환 AI",
                    subtitle: flowRadar.topSummary,
                    count: flowRadar.totalCount,
                    systemImage: "arrow.triangle.2.circlepath",
                    tint: .mint
                ) {
                    MoneyFlowRadarPage(
                        data: flowRadar,
                        favoriteTickers: favoriteTickers,
                        aiPickDates: aiPickDates,
                        toggleFavorite: toggleFavorite
                    )
                }

                InsightNavigationButton(
                    title: "주요 뉴스",
                    subtitle: majorNews.first.map { "\($0.marketText) · \($0.majorNewsText)" } ?? "중요 뉴스 대기",
                    count: majorNews.count,
                    systemImage: "newspaper.fill",
                    tint: .yellow
                ) {
                    MajorNewsPage(
                        results: majorNews,
                        favoriteTickers: favoriteTickers,
                        aiPickDates: aiPickDates,
                        toggleFavorite: toggleFavorite
                    )
                }

                InsightNavigationButton(
                    title: "장 마감 전 후보",
                    subtitle: closingBuyCandidates.first.map { "\($0.name) 우선 확인" } ?? "후보 없음",
                    count: closingBuyCandidates.count,
                    systemImage: "timer",
                    tint: .orange
                ) {
                    ClosingBuyPage(
                        results: closingBuyCandidates,
                        favoriteTickers: favoriteTickers,
                        aiPickDates: aiPickDates,
                        toggleFavorite: toggleFavorite
                    )
                }
            }
        }
        .padding(10)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

}

private struct InsightNavigationButton<Destination: View>: View {
    let title: String
    let subtitle: String
    let count: Int
    let systemImage: String
    let tint: Color
    @ViewBuilder let destination: Destination

    var body: some View {
        NavigationLink {
            destination
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 8) {
                Image(systemName: systemImage)
                    .font(.subheadline.bold())
                    .foregroundStyle(tint)
                    .frame(width: 24, height: 24)

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.caption.bold())
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                }
                    .layoutPriority(1)

                    Spacer(minLength: 6)

                Text("\(count)")
                    .font(.caption2.bold())
                    .foregroundStyle(tint)
                        .lineLimit(1)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(tint.opacity(0.12), in: Capsule())

                Image(systemName: "chevron.right")
                    .font(.caption2.bold())
                    .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
            .padding(9)
            .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }
}

private struct ServerSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var baseURL: String
    @State private var token: String
    @State private var statusText = "서버 주소와 토큰을 저장한 뒤 연결 테스트를 누르세요."
    @State private var isTesting = false
    let onSave: (RemoteServerConfig) -> Void

    init(config: RemoteServerConfig, onSave: @escaping (RemoteServerConfig) -> Void) {
        _baseURL = State(initialValue: config.baseURL.isEmpty ? RemoteServerConfig.defaultBaseURL : config.baseURL)
        _token = State(initialValue: config.token)
        self.onSave = onSave
    }

    private var currentConfig: RemoteServerConfig {
        RemoteServerConfig(baseURL: baseURL, token: token)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                AppColors.background.ignoresSafeArea()

                ScrollView(.vertical, showsIndicators: true) {
                    VStack(alignment: .leading, spacing: 14) {
                        VStack(alignment: .leading, spacing: 8) {
                            Label("Render 서버 설정", systemImage: "cloud.fill")
                                .font(.headline.bold())
                            Text("서버 주소와 API 토큰은 이 아이폰 안에만 저장됩니다.")
                                .font(.caption.weight(.medium))
                                .foregroundStyle(.secondary)
                        }

                        VStack(alignment: .leading, spacing: 8) {
                            Text("서버 주소")
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                            TextField("https://market-scanner-api-fo2m.onrender.com", text: $baseURL)
                                .textInputAutocapitalization(.never)
                                .keyboardType(.URL)
                                .autocorrectionDisabled()
                                .padding(11)
                                .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
                        }

                        VStack(alignment: .leading, spacing: 8) {
                            Text("API 토큰")
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                            SecureField("Render MARKET_API_TOKEN", text: $token)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .padding(11)
                                .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
                        }

                        Text(statusText)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(statusText.contains("성공") ? .green : .secondary)
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))

                        HStack(spacing: 10) {
                            Button {
                                Task { await testConnection() }
                            } label: {
                                Label(isTesting ? "확인중" : "연결 테스트", systemImage: "antenna.radiowaves.left.and.right")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.bordered)
                            .disabled(isTesting)

                            Button {
                                onSave(currentConfig)
                                dismiss()
                            } label: {
                                Label("저장", systemImage: "checkmark")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(!currentConfig.isReady)
                        }
                    }
                    .padding(16)
                    .noHorizontalOverflow()
                }
                .verticalScrollOnly()
            }
            .navigationTitle("서버 설정")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기") {
                        dismiss()
                    }
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    @MainActor
    private func testConnection() async {
        guard currentConfig.isReady else {
            statusText = "서버 주소와 토큰을 먼저 입력하세요."
            return
        }
        isTesting = true
        defer { isTesting = false }

        do {
            let status = try await RemoteMarketAPI.fetchStatus(config: currentConfig)
            let marketsText = status.markets.joined(separator: "/")
            statusText = "연결 성공 · \(status.rows)개 종목 · \(marketsText)"
        } catch {
            statusText = "연결 실패 · 주소나 토큰을 다시 확인하세요."
        }
    }
}

private struct TodayWatchlistPage: View {
    let watchlist: [ScannerResult]
    let abnormalEvents: [ScannerResult]
    let missedReview: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        ScrollView(.vertical, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 12) {
                InsightPageHeader(title: "TODAY WATCHLIST", subtitle: "오늘 변화가 있거나 우선 확인할 추천 종목입니다.", systemImage: "bolt.badge.clock.fill", tint: .green)

                ForEach(Array(watchlist.enumerated()), id: \.element.id) { index, result in
                    NavigationLink {
                        ResultDetailView(
                            result: result,
                            isFavorite: favoriteTickers.contains(result.ticker),
                            recommendationDate: aiPickDates[result.ticker]
                        ) {
                            toggleFavorite(result)
                        }
                    } label: {
                        TodayWatchRow(rank: index + 1, result: result)
                    }
                    .buttonStyle(.plain)
                }

                if !abnormalEvents.isEmpty {
                    InsightPageSubheader(title: "이상 거래 탐지")
                    ForEach(abnormalEvents.prefix(6)) { result in
                        NavigationLink {
                            ResultDetailView(
                                result: result,
                                isFavorite: favoriteTickers.contains(result.ticker),
                                recommendationDate: aiPickDates[result.ticker]
                            ) {
                                toggleFavorite(result)
                            }
                        } label: {
                            EventSignalRow(result: result)
                        }
                        .buttonStyle(.plain)
                    }
                }

                if !missedReview.isEmpty {
                    InsightPageSubheader(title: "놓친 종목 복기")
                    ForEach(missedReview.prefix(5)) { result in
                        NavigationLink {
                            ResultDetailView(
                                result: result,
                                isFavorite: favoriteTickers.contains(result.ticker),
                                recommendationDate: aiPickDates[result.ticker]
                            ) {
                                toggleFavorite(result)
                            }
                        } label: {
                            MissedReviewRow(result: result)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .padding(16)
            .noHorizontalOverflow()
        }
        .verticalScrollOnly()
        .background(AppColors.background)
        .navigationTitle("오늘 볼 종목")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct DailyMoversPage: View {
    let gainers: [ScannerResult]
    let losers: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        ScrollView(.vertical, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 12) {
                InsightPageHeader(
                    title: "오늘 등락 TOP",
                    subtitle: "오늘 많이 오른 종목과 많이 떨어진 종목을 분리해서 봅니다.",
                    systemImage: "arrow.up.arrow.down.circle.fill",
                    tint: .red
                )

                if !gainers.isEmpty {
                    InsightPageSubheader(title: "많이 오른 종목")
                    ForEach(Array(gainers.prefix(20).enumerated()), id: \.element.id) { index, result in
                        moverLink(
                            rank: index + 1,
                            result: result,
                            subtitle: "상승 \(String(format: "%.2f", result.changePercent))% · 거래량 \(String(format: "%.1f", result.volumeRatio))배 · \(result.sectorCategoryName)",
                            tint: .red
                        )
                    }
                }

                if !losers.isEmpty {
                    InsightPageSubheader(title: "많이 떨어진 종목")
                    ForEach(Array(losers.prefix(20).enumerated()), id: \.element.id) { index, result in
                        moverLink(
                            rank: index + 1,
                            result: result,
                            subtitle: "하락 \(String(format: "%.2f", abs(result.changePercent)))% · \(result.supportBreakAlertText ?? result.riskText)",
                            tint: .blue
                        )
                    }
                }

                if gainers.isEmpty && losers.isEmpty {
                    EmptyInsightBlock(text: "오늘 등락률 데이터가 아직 없습니다.")
                }
            }
            .padding(16)
            .noHorizontalOverflow()
        }
        .verticalScrollOnly()
        .background(AppColors.background)
        .navigationTitle("오늘 등락 TOP")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func moverLink(rank: Int, result: ScannerResult, subtitle: String, tint: Color) -> some View {
        NavigationLink {
            ResultDetailView(
                result: result,
                isFavorite: favoriteTickers.contains(result.ticker),
                recommendationDate: aiPickDates[result.ticker]
            ) {
                toggleFavorite(result)
            }
        } label: {
            HStack(spacing: 10) {
                Text("\(rank)")
                    .font(.caption.bold())
                    .foregroundStyle(tint)
                    .frame(width: 28, height: 28)
                    .background(tint.opacity(0.12), in: Circle())

                VStack(alignment: .leading, spacing: 5) {
                    HStack {
                        Text(result.name)
                            .font(.subheadline.bold())
                            .foregroundStyle(.primary)
                            .lineLimit(1)
                        Spacer()
                        Text(result.formattedPrice)
                            .font(.headline.bold())
                            .foregroundStyle(.primary)
                    }
                    HStack(spacing: 8) {
                        Text(result.changeBadgeText)
                            .font(.caption.bold())
                            .foregroundStyle(tint)
                        Text(result.marketText)
                            .font(.caption2.bold())
                            .foregroundStyle(.secondary)
                        Text(result.dataFreshnessText)
                            .font(.caption2.bold())
                            .foregroundStyle(.secondary)
                    }
                    Text(subtitle)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }

                Image(systemName: "chevron.right")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
            }
            .padding(11)
            .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }
}

private struct MarketStrengthPage: View {
    let sections: [MarketStrengthSection]
    let results: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        ScrollView(.vertical, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 12) {
                InsightPageHeader(title: "금일 강한 섹터", subtitle: "각 시장에서 평균 흐름과 상승 비율이 좋은 섹터입니다.", systemImage: "square.grid.2x2.fill", tint: .blue)
                ForEach(sections) { section in
                    MarketStrengthView(section: section)
                    ForEach(representativeStocks(for: section).prefix(5)) { result in
                        NavigationLink {
                            ResultDetailView(
                                result: result,
                                isFavorite: favoriteTickers.contains(result.ticker),
                                recommendationDate: aiPickDates[result.ticker]
                            ) {
                                toggleFavorite(result)
                            }
                        } label: {
                            FlowStockRow(result: result, subtitle: "\(result.sectorCategoryName) 대표 흐름 · \(result.whyTodayText)")
                        }
                        .buttonStyle(.plain)
                    }

                    if section.market == "미장" {
                        let linkedKorea = linkedKoreaStocks(for: section)
                        if !linkedKorea.isEmpty {
                            InsightPageSubheader(title: "미장 강세 연관 국장")
                            ForEach(linkedKorea.prefix(8)) { result in
                                NavigationLink {
                                    ResultDetailView(
                                        result: result,
                                        isFavorite: favoriteTickers.contains(result.ticker),
                                        recommendationDate: aiPickDates[result.ticker]
                                    ) {
                                        toggleFavorite(result)
                                    }
                                } label: {
                                    FlowStockRow(result: result, subtitle: "미장 \(result.themeKey) 강세 연결 후보 · \(result.flowRadarReason)")
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
            }
            .padding(16)
            .noHorizontalOverflow()
        }
        .verticalScrollOnly()
        .background(AppColors.background)
        .navigationTitle("강한 섹터")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func representativeStocks(for section: MarketStrengthSection) -> [ScannerResult] {
        let categories = Set(section.summaries.map(\.category))
        return results
            .filter { $0.marketText == section.market && categories.contains($0.sectorCategoryName) }
            .sorted { lhs, rhs in
                if lhs.todayWatchScore == rhs.todayWatchScore {
                    return lhs.changePercent > rhs.changePercent
                }
                return lhs.todayWatchScore > rhs.todayWatchScore
            }
            .uniquedByTicker()
    }

    private func linkedKoreaStocks(for section: MarketStrengthSection) -> [ScannerResult] {
        let strongUSThemes = Set(
            results
                .filter { $0.marketText == section.market }
                .filter { section.summaries.map(\.category).contains($0.sectorCategoryName) }
                .map(\.themeKey)
        )

        return results
            .filter { $0.marketText == "국장" && strongUSThemes.contains($0.themeKey) }
            .filter { $0.changePercent < 5.5 && !$0.isChaseRiskForAi }
            .sorted { lhs, rhs in
                if lhs.flowRotationScore == rhs.flowRotationScore {
                    return lhs.changePercent > rhs.changePercent
                }
                return lhs.flowRotationScore > rhs.flowRotationScore
            }
            .uniquedByTicker()
    }
}

private struct LeadDetectionPage: View {
    let leadingCandidates: [ScannerResult]
    let missedCandidates: [ScannerResult]
    let riskCandidates: [ScannerResult]
    let keywordCandidates: [ScannerResult]
    let flowRadar: MoneyFlowRadarData
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        ScrollView(.vertical, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 12) {
                InsightPageHeader(
                    title: "선행 탐지 AI",
                    subtitle: "이미 오른 종목보다 다음으로 움직일 섹터와 후행 후보를 먼저 봅니다.",
                    systemImage: "scope",
                    tint: .pink
                )

                if !leadingCandidates.isEmpty {
                    InsightPageSubheader(title: "다음 타자 후보")
                    ForEach(leadingCandidates.prefix(8)) { result in
                        stockLink(result: result, subtitle: result.leadDetectionText, tint: .pink)
                    }
                }

                if !missedCandidates.isEmpty {
                    InsightPageSubheader(title: "놓칠 가능성 감지")
                    ForEach(missedCandidates.prefix(6)) { result in
                        stockLink(result: result, subtitle: result.missedRiskText ?? result.initialVolumeText, tint: .orange)
                    }
                }

                if !keywordCandidates.isEmpty {
                    InsightPageSubheader(title: "반복 키워드 감지")
                    ForEach(keywordCandidates.prefix(6)) { result in
                        stockLink(result: result, subtitle: result.repeatedKeywordSignal ?? "키워드 감지", tint: .yellow)
                    }
                }

                if !flowRadar.nextRotation.isEmpty {
                    InsightPageSubheader(title: "돈의 흐름 지도")
                    ForEach(flowRadar.nextRotation.prefix(5)) { signal in
                        SectorFlowMapRow(signal: signal)
                    }
                }

                if !riskCandidates.isEmpty {
                    InsightPageSubheader(title: "실시간 위험 감지")
                    ForEach(riskCandidates.prefix(6)) { result in
                        stockLink(result: result, subtitle: result.realtimeRiskText ?? result.riskText, tint: .red)
                    }
                }

                if leadingCandidates.isEmpty && missedCandidates.isEmpty && keywordCandidates.isEmpty && riskCandidates.isEmpty {
                    EmptyInsightBlock(text: "아직 선행 탐지로 볼 만한 움직임이 없습니다.")
                }
            }
            .padding(16)
            .noHorizontalOverflow()
        }
        .verticalScrollOnly()
        .background(AppColors.background)
        .navigationTitle("선행 탐지 AI")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func stockLink(result: ScannerResult, subtitle: String, tint: Color) -> some View {
        NavigationLink {
            ResultDetailView(
                result: result,
                isFavorite: favoriteTickers.contains(result.ticker),
                recommendationDate: aiPickDates[result.ticker]
            ) {
                toggleFavorite(result)
            }
        } label: {
            LeadDetectionRow(result: result, subtitle: subtitle, tint: tint)
        }
        .buttonStyle(.plain)
    }
}

private struct LeadDetectionRow: View {
    let result: ScannerResult
    let subtitle: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 8) {
                Text(result.name)
                    .font(.subheadline.bold())
                    .lineLimit(1)
                Text(result.themeKey)
                    .font(.caption2.bold())
                    .foregroundStyle(tint)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(tint.opacity(0.12), in: Capsule())
                Spacer()
                Text("TS \(result.todayScore)")
                    .font(.caption.bold())
                    .foregroundStyle(result.todayScoreTint)
                Text(result.changeBadgeText)
                    .font(.caption.bold())
                    .foregroundStyle(result.changePercent >= 0 ? .red : .blue)
            }
            Text(subtitle)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(2)
            Text("거래량 \(String(format: "%.1f", result.volumeRatio))배 · \(result.marketText)")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
        }
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct SectorFlowMapRow: View {
    let signal: SectorFlowSignal

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: signal.averageChange >= 0 ? "arrow.up.right.circle.fill" : "arrow.down.right.circle.fill")
                .foregroundStyle(signal.averageChange >= 0 ? .red : .blue)
            VStack(alignment: .leading, spacing: 4) {
                Text("\(signal.market) \(signal.theme)")
                    .font(.subheadline.bold())
                Text("자금 이동 감지 · \(signal.summary)")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
        }
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct MoneyFlowRadarPage: View {
    let data: MoneyFlowRadarData
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        ScrollView(.vertical, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 12) {
                InsightPageHeader(title: "테마 순환 AI", subtitle: "돈이 이동 중인 섹터와 아직 덜 오른 후행 관련주를 봅니다.", systemImage: "arrow.triangle.2.circlepath", tint: .mint)
                MoneyFlowRadarContent(
                    data: data,
                    favoriteTickers: favoriteTickers,
                    aiPickDates: aiPickDates,
                    toggleFavorite: toggleFavorite
                )
            }
            .padding(16)
            .noHorizontalOverflow()
        }
        .verticalScrollOnly()
        .background(AppColors.background)
        .navigationTitle("테마 순환 AI")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct MajorNewsPage: View {
    let results: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        ScrollView(.vertical, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 12) {
                InsightPageHeader(
                    title: "주요 뉴스",
                    subtitle: "시장 전체 이슈와 섹터별 큰 뉴스만 모아봅니다.",
                    systemImage: "newspaper.fill",
                    tint: .yellow
                )

                if results.isEmpty {
                    EmptyInsightBlock(text: "아직 주요 뉴스로 볼 만한 항목이 없습니다.")
                } else {
                    ForEach(groupedResults.keys.sorted(), id: \.self) { market in
                        InsightPageSubheader(title: market)
                        ForEach(groupedResults[market] ?? []) { result in
                            NavigationLink {
                                ResultDetailView(
                                    result: result,
                                    isFavorite: favoriteTickers.contains(result.ticker),
                                    recommendationDate: aiPickDates[result.ticker]
                                ) {
                                    toggleFavorite(result)
                                }
                            } label: {
                                MajorNewsRow(result: result)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .padding(16)
            .noHorizontalOverflow()
        }
        .verticalScrollOnly()
        .background(AppColors.background)
        .navigationTitle("주요 뉴스")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var groupedResults: [String: [ScannerResult]] {
        Dictionary(grouping: results) { $0.marketText }
    }
}

private struct MajorNewsRow: View {
    let result: ScannerResult

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 8) {
                LocalizedStockNameView(
                    name: result.name,
                    ticker: result.ticker,
                    market: result.marketText,
                    primaryFont: .subheadline.bold(),
                    secondaryFont: .caption2.weight(.medium)
                )
                Text(result.themeKey)
                    .font(.caption2.bold())
                    .foregroundStyle(.yellow)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(Color.yellow.opacity(0.12), in: Capsule())
                Spacer()
                Text(result.changeBadgeText)
                    .font(.caption.bold())
                    .foregroundStyle(result.changePercent >= 0 ? .red : .blue)
            }
            HStack(spacing: 6) {
                Text(newsLabel)
                    .font(.caption2.bold())
                    .foregroundStyle(newsTint)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(newsTint.opacity(0.12), in: Capsule())
                Text(newsSummary)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                    .layoutPriority(1)
                Spacer(minLength: 6)
                Text(impactStars)
                    .font(.caption2.monospaced().bold())
                    .foregroundStyle(.yellow)
                    .lineLimit(1)
            }
        }
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }

    private var newsLabel: String {
        if result.mobileNewsImpactScore >= 10 || result.newsActionText.contains("호재") {
            return "호재"
        }
        if result.mobileNewsImpactScore <= -10 || result.hasCriticalNewsRisk || result.newsActionText.contains("악재") {
            return "악재"
        }
        return "중립"
    }

    private var newsTint: Color {
        switch newsLabel {
        case "호재": return .green
        case "악재": return .red
        default: return .yellow
        }
    }

    private var newsSummary: String {
        NewsDigest.oneLine(
            result.mobileNewsFocus,
            result.mobileNewsImpactSummary,
            result.newsOneLine,
            result.majorNewsText,
            fallback: "\(result.themeKey) 뉴스 흐름 확인"
        )
    }

    private var impactStars: String {
        NewsDigest.stars(score: result.mobileNewsImpactScore, strength: result.mobileNewsV2Strength)
    }
}

private struct EmptyInsightBlock: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.subheadline.weight(.medium))
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct ClosingBuyPage: View {
    let results: [ScannerResult]
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        ScrollView(.vertical, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 12) {
                InsightPageHeader(title: "장 마감 전 후보", subtitle: "마감 전에 짧게 확인할 후보입니다.", systemImage: "timer", tint: .orange)
                ForEach(results) { result in
                    NavigationLink {
                        ResultDetailView(
                            result: result,
                            isFavorite: favoriteTickers.contains(result.ticker),
                            recommendationDate: aiPickDates[result.ticker]
                        ) {
                            toggleFavorite(result)
                        }
                    } label: {
                        ClosingBuyCandidateRow(result: result)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(16)
            .noHorizontalOverflow()
        }
        .verticalScrollOnly()
        .background(AppColors.background)
        .navigationTitle("마감 전 후보")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct InsightPageHeader: View {
    let title: String
    let subtitle: String
    let systemImage: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: systemImage)
                .font(.title3.bold())
                .foregroundStyle(tint)
            Text(subtitle)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct InsightPageSubheader: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.headline.bold())
            .padding(.top, 8)
    }
}

private struct EventDashboardView: View {
    let watchlist: [ScannerResult]
    let abnormalEvents: [ScannerResult]
    let missedReview: [ScannerResult]
    @Binding var isExpanded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                withAnimation(.snappy(duration: 0.22)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "bolt.badge.clock.fill")
                        .foregroundStyle(.green)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("TODAY WATCHLIST")
                            .font(.headline.bold())
                        Text(summaryLine)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(isExpanded ? 180 : 0))
                }
            }
            .buttonStyle(.plain)

            if isExpanded {
                VStack(alignment: .leading, spacing: 10) {
                    if !watchlist.isEmpty {
                        EventSubheader(title: "오늘 볼 종목", value: "\(watchlist.count)개")
                        ForEach(Array(watchlist.prefix(5).enumerated()), id: \.element.id) { index, result in
                            TodayWatchRow(rank: index + 1, result: result)
                        }
                    }

                    if !abnormalEvents.isEmpty {
                        EventSubheader(title: "이상 거래 탐지", value: "\(abnormalEvents.count)개")
                        ForEach(abnormalEvents.prefix(4)) { result in
                            EventSignalRow(result: result)
                        }
                    }

                    if !missedReview.isEmpty {
                        EventSubheader(title: "놓친 종목 복기", value: "\(missedReview.count)개")
                        ForEach(missedReview.prefix(3)) { result in
                            MissedReviewRow(result: result)
                        }
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private var summaryLine: String {
        guard let first = watchlist.first else {
            return "변화 있는 종목 확인 중"
        }
        return "1순위 \(first.name) · \(first.eventGrade) · 이벤트 \(abnormalEvents.count)개"
    }
}

private struct EventSubheader: View {
    let title: String
    let value: String

    var body: some View {
        HStack {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.caption2.bold())
                .foregroundStyle(.secondary)
        }
        .padding(.top, 2)
    }
}

private struct TodayWatchRow: View {
    let rank: Int
    let result: ScannerResult

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 8) {
                Text("\(rank)")
                    .font(.caption.bold())
                    .foregroundStyle(.black)
                    .frame(width: 22, height: 22)
                    .background(result.eventGradeTint, in: Circle())

                Text(result.name)
                    .font(.subheadline.bold())
                    .lineLimit(1)

                Text(result.eventGrade)
                    .font(.caption2.bold())
                    .foregroundStyle(result.eventGradeTint)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(result.eventGradeTint.opacity(0.12), in: Capsule())

                Spacer()

                Text("TS \(result.todayScore)")
                    .font(.caption.bold())
                    .foregroundStyle(result.todayScoreTint)

                Text(result.changeBadgeText)
                    .font(.caption.bold())
                    .foregroundStyle(result.changePercent >= 0 ? .red : .blue)
            }

            Text(result.whyTodayText)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct EventSignalRow: View {
    let result: ScannerResult

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "waveform.path.ecg")
                .font(.caption.bold())
                .foregroundStyle(.orange)
                .frame(width: 20)

            VStack(alignment: .leading, spacing: 4) {
                Text("\(result.name) · \(result.marketText)")
                    .font(.caption.bold())
                    .lineLimit(1)
                Text(result.abnormalSignals.joined(separator: " · "))
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Spacer()
        }
        .padding(10)
        .background(AppColors.background.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct MissedReviewRow: View {
    let result: ScannerResult

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.caption.bold())
                .foregroundStyle(.blue)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 4) {
                Text(result.name)
                    .font(.caption.bold())
                    .lineLimit(1)
                Text(result.missedMoveText ?? "큰 변화 감지")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(10)
        .background(AppColors.background.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct MoneyFlowRadarData {
    let nextRotation: [SectorFlowSignal]
    let quietRelated: [ScannerResult]
    let initialVolume: [ScannerResult]
    let usToKorea: [ScannerResult]

    static let empty = MoneyFlowRadarData(nextRotation: [], quietRelated: [], initialVolume: [], usToKorea: [])

    var isEmpty: Bool {
        nextRotation.isEmpty && quietRelated.isEmpty && initialVolume.isEmpty && usToKorea.isEmpty
    }

    var totalCount: Int {
        nextRotation.count + quietRelated.count + initialVolume.count + usToKorea.count
    }

    var topSummary: String {
        if let first = nextRotation.first {
            return "현재 돈의 흐름: \(first.market) \(first.theme)"
        }
        if let first = quietRelated.first {
            return "후행 관련주: \(first.name)"
        }
        if let first = initialVolume.first {
            return "자금 유입 시작: \(first.name)"
        }
        if let first = usToKorea.first {
            return "미국→한국 \(first.themeKey)"
        }
        return "돈의 흐름 확인 중"
    }
}

private struct SectorFlowSignal: Identifiable {
    let id = UUID()
    let market: String
    let theme: String
    let averageChange: Double
    let averageVolume: Double
    let risingRatio: Double
    let earlyCount: Int
    let quietCount: Int
    let leaders: String
    let score: Double

    var changeText: String {
        let sign = averageChange >= 0 ? "+" : "-"
        return "\(sign)\(String(format: "%.2f", abs(averageChange)))%"
    }

    var summary: String {
        "\(changeText) · 거래량 \(String(format: "%.1f", averageVolume))배 · 초입 \(earlyCount)개"
    }
}

private struct MoneyFlowRadarView: View {
    let data: MoneyFlowRadarData
    @Binding var isExpanded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                withAnimation(.snappy(duration: 0.22)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .foregroundStyle(.mint)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("테마 순환 AI")
                            .font(.headline.bold())
                        Text(data.topSummary)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(isExpanded ? 180 : 0))
                }
            }
            .buttonStyle(.plain)

            if isExpanded {
                MoneyFlowRadarContent(
                    data: data,
                    favoriteTickers: [],
                    aiPickDates: [:],
                    toggleFavorite: { _ in }
                )
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct MoneyFlowRadarContent: View {
    let data: MoneyFlowRadarData
    let favoriteTickers: Set<String>
    let aiPickDates: [String: String]
    let toggleFavorite: (ScannerResult) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if !data.nextRotation.isEmpty {
                FlowRadarGroup(title: "현재 돈의 흐름 · 다음 순환 섹터") {
                    ForEach(data.nextRotation.prefix(6)) { signal in
                        SectorFlowRow(signal: signal)
                    }
                }
            }

            if !data.quietRelated.isEmpty {
                FlowRadarGroup(title: "후행 관련주 탐색") {
                    ForEach(data.quietRelated.prefix(8)) { result in
                        linkedStockRow(result: result, subtitle: result.flowRadarReason)
                    }
                }
            }

            if !data.initialVolume.isEmpty {
                FlowRadarGroup(title: "초기 거래량 증가 · 자금 유입 시작") {
                    ForEach(data.initialVolume.prefix(8)) { result in
                        linkedStockRow(result: result, subtitle: result.initialVolumeText)
                    }
                }
            }

            if !data.usToKorea.isEmpty {
                FlowRadarGroup(title: "미국 → 한국 연결 테마") {
                    ForEach(data.usToKorea.prefix(8)) { result in
                        linkedStockRow(result: result, subtitle: "미장 같은 테마 강세 후 국장 연결 후보")
                    }
                }
            }
        }
    }

    private func linkedStockRow(result: ScannerResult, subtitle: String) -> some View {
        NavigationLink {
            ResultDetailView(
                result: result,
                isFavorite: favoriteTickers.contains(result.ticker),
                recommendationDate: aiPickDates[result.ticker]
            ) {
                toggleFavorite(result)
            }
        } label: {
            FlowStockRow(result: result, subtitle: subtitle)
        }
        .buttonStyle(.plain)
    }
}

private struct FlowRadarGroup<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            content
        }
    }
}

private struct SectorFlowRow: View {
    let signal: SectorFlowSignal

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 8) {
                Text("\(signal.market) · \(signal.theme)")
                    .font(.subheadline.bold())
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .layoutPriority(1)
                Spacer()
                Text(String(format: "%.0f", signal.score))
                    .font(.caption.bold())
                    .foregroundStyle(.mint)
            }
            Text(signal.summary)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            Text("연결 종목: \(signal.leaders)")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct FlowStockRow: View {
    let result: ScannerResult
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(result.name)
                        .font(.subheadline.bold())
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(result.themeKey)
                        .font(.caption2.bold())
                        .foregroundStyle(.mint)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 4)
                        .background(Color.mint.opacity(0.12), in: Capsule())
                }
                .layoutPriority(1)
                Spacer()
                Text(result.changeBadgeText)
                    .font(.caption.bold())
                    .foregroundStyle(result.changePercent >= 0 ? .red : .blue)
                    .lineLimit(1)
            }
            Text(subtitle)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(AppColors.background.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct PortfolioRiskItem: Identifiable {
    let id = UUID()
    let name: String
    let sector: String
    let score: Int
    let summary: String
}

private struct PortfolioRiskSummary {
    let items: [PortfolioRiskItem]
    let concentrationText: String
    let sectorBiasText: String
    let isEmpty: Bool

    static let empty = PortfolioRiskSummary(
        items: [],
        concentrationText: "입력 대기",
        sectorBiasText: "포지션 없음",
        isEmpty: true
    )

    static func make(from evaluations: [PositionEvaluation]) -> PortfolioRiskSummary {
        guard !evaluations.isEmpty else {
            return .empty
        }

        let totalValue = evaluations.map(\.currentValue).reduce(0, +)
        let sectorValues = Dictionary(grouping: evaluations) { $0.result.sectorCategoryName }
            .mapValues { $0.map(\.currentValue).reduce(0, +) }
        let topSector = sectorValues.max { lhs, rhs in lhs.value < rhs.value }
        let topSectorShare = totalValue > 0 ? ((topSector?.value ?? 0) / totalValue) * 100 : 0
        let topPositionShare = totalValue > 0 ? (evaluations.map(\.currentValue).max() ?? 0) / totalValue * 100 : 0

        let concentrationText: String
        if topPositionShare >= 70 {
            concentrationText = "높음"
        } else if topPositionShare >= 45 {
            concentrationText = "중간"
        } else {
            concentrationText = "낮음"
        }

        let sectorBiasText: String
        if let topSector {
            sectorBiasText = "\(topSector.key) \(String(format: "%.0f", topSectorShare))%"
        } else {
            sectorBiasText = "분산 확인 필요"
        }

        let items = evaluations
            .sorted { $0.currentValue > $1.currentValue }
            .prefix(5)
            .map { evaluation in
                let result = evaluation.result
                let sectorShare = totalValue > 0 ? evaluation.currentValue / totalValue * 100 : 0
                var risk = 42
                if result.mobileNewsImpactScore <= -50 { risk += 22 }
                else if result.mobileNewsImpactScore <= -10 { risk += 10 }
                if result.isChaseRiskForAi { risk += 15 }
                if result.changePercent <= -4 { risk += 12 }
                if result.volumeRatio >= 4 && result.changePercent < 0 { risk += 8 }
                if evaluation.profitPercent >= 25 { risk += 8 }
                if evaluation.profitPercent <= -7 { risk += 18 }
                if sectorShare >= 60 { risk += 10 }
                let clippedRisk = max(0, min(100, risk))
                let summary = "\(result.sectorCategoryName) · 비중 \(String(format: "%.0f", sectorShare))% · 수익률 \(String(format: "%+.1f", evaluation.profitPercent))%"
                return PortfolioRiskItem(
                    name: result.name,
                    sector: result.sectorCategoryName,
                    score: clippedRisk,
                    summary: summary
                )
            }

        return PortfolioRiskSummary(
            items: items,
            concentrationText: concentrationText,
            sectorBiasText: sectorBiasText,
            isEmpty: false
        )
    }
}

private struct PortfolioRiskCard: View {
    let summary: PortfolioRiskSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: "shield.lefthalf.filled")
                    .foregroundStyle(.orange)
                Text("보유 종목 위험도")
                    .font(.headline.bold())
                Spacer()
                Text(summary.concentrationText)
                    .font(.caption.bold())
                    .foregroundStyle(summary.concentrationText == "높음" ? .red : .mint)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background((summary.concentrationText == "높음" ? Color.red : Color.mint).opacity(0.12), in: Capsule())
            }

            if summary.isEmpty {
                Text("관심종목 상세에서 매수가와 총금액을 입력하면 위험도와 섹터 편중을 계산합니다.")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(summary.items) { item in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack(alignment: .top, spacing: 8) {
                                Text(item.name)
                                    .font(.subheadline.bold())
                                    .lineLimit(2)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .layoutPriority(1)
                                Spacer(minLength: 8)
                                Text("\(item.score)점")
                                    .font(.headline.monospacedDigit().bold())
                                    .foregroundStyle(item.score >= 80 ? .red : item.score >= 65 ? .orange : .mint)
                                    .lineLimit(1)
                            }
                            Text(item.summary)
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                Divider().overlay(AppColors.border)

                HStack {
                    Text("집중도 위험")
                    Spacer()
                    Text(summary.concentrationText)
                        .fontWeight(.bold)
                }
                .font(.caption)

                HStack {
                    Text("섹터 편중")
                    Spacer()
                    Text(summary.sectorBiasText)
                        .fontWeight(.bold)
                }
                .font(.caption)
            }
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }
}

private struct SectorInflowRank: Identifiable {
    let id = UUID()
    let market: String
    let sector: String
    let totalTradeValue: Double
    let averageTradeValueRatio: Double
    let averageVolumeRatio: Double
    let averageChange: Double
    let positiveRatio: Double
    let leaders: String
    let score: Double

    var versusYesterdayPercent: Double {
        (max(averageTradeValueRatio, averageVolumeRatio) - 1) * 100
    }

    var versusYesterdayText: String {
        let sign = versusYesterdayPercent >= 0 ? "+" : "-"
        return "\(sign)\(String(format: "%.0f", abs(versusYesterdayPercent)))%"
    }

    var shortSectorName: String {
        sector
            .replacingOccurrences(of: "미장/", with: "")
            .replacingOccurrences(of: "국장/", with: "")
            .replacingOccurrences(of: "캐나다/", with: "")
    }

    var detailText: String {
        "거래대금 \(String(format: "%.1f", averageTradeValueRatio))배 · 거래량 \(String(format: "%.1f", averageVolumeRatio))배 · 평균 \(averageChange >= 0 ? "+" : "-")\(String(format: "%.2f", abs(averageChange)))%"
    }
}

private enum SectorInflowCardSize: String, CaseIterable {
    case compact
    case normal
    case expanded

    var title: String {
        switch self {
        case .compact:
            return "작게"
        case .normal:
            return "보통"
        case .expanded:
            return "전체"
        }
    }

    var rowLimit: Int {
        switch self {
        case .compact:
            return 0
        case .normal:
            return 2
        case .expanded:
            return 5
        }
    }

    var next: SectorInflowCardSize {
        switch self {
        case .compact:
            return .normal
        case .normal:
            return .expanded
        case .expanded:
            return .compact
        }
    }
}

private struct SectorInflowCard: View {
    let ranks: [SectorInflowRank]
    let size: SectorInflowCardSize
    let setSize: (SectorInflowCardSize) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: size == .compact ? 8 : 12) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "banknote.fill")
                    .foregroundStyle(.mint)
                VStack(alignment: .leading, spacing: 2) {
                    Text("오늘 가장 많은 돈이 들어온 섹터")
                        .font(size == .compact ? .subheadline.bold() : .headline.bold())
                        .lineLimit(2)
                    Text(summaryText)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .layoutPriority(1)
                Spacer()
                if let top = ranks.first {
                    Text(top.versusYesterdayText)
                        .font(.subheadline.monospacedDigit().weight(.heavy))
                        .foregroundStyle(top.versusYesterdayPercent >= 0 ? .red : .blue)
                        .lineLimit(1)
                }
                Button {
                    withAnimation(.snappy(duration: 0.18)) {
                        setSize(size.next)
                    }
                } label: {
                    Text(size.title)
                        .font(.caption.bold())
                        .foregroundStyle(.mint)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(Color.mint.opacity(0.12), in: Capsule())
                }
                .buttonStyle(.plain)
            }

            if ranks.isEmpty {
                Text("섹터 자금 유입 계산 대기")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
            } else if size == .compact {
                if let top = ranks.first {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("1위 \(top.shortSectorName)")
                            .font(.caption.bold())
                            .foregroundStyle(.primary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(top.detailText)
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            } else {
                VStack(spacing: 6) {
                    ForEach(Array(ranks.prefix(size.rowLimit).enumerated()), id: \.element.id) { index, rank in
                        SectorInflowRow(rank: index + 1, item: rank)
                    }
                }
                if size == .expanded, let top = ranks.first {
                    Text("어제 대비 \(top.versusYesterdayText)")
                        .font(.caption.bold())
                        .foregroundStyle(top.versusYesterdayPercent >= 0 ? .red : .blue)
                }
            }
        }
        .padding(size == .compact ? 10 : 14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private var summaryText: String {
        guard !ranks.isEmpty else {
            return "자금 흐름 확인 중"
        }
        return ranks.prefix(3).enumerated().map { index, item in
            "\(index + 1)위 \(item.shortSectorName)"
        }.joined(separator: " · ")
    }
}

private struct SectorInflowRow: View {
    let rank: Int
    let item: SectorInflowRank

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .top, spacing: 8) {
                Text("\(rank)위")
                    .font(.caption.bold())
                    .foregroundStyle(.black)
                    .frame(width: 32, height: 22)
                    .background(Color.mint, in: Capsule())

                VStack(alignment: .leading, spacing: 4) {
                    Text(item.shortSectorName)
                        .font(.subheadline.bold())
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)

                    Text(item.market)
                        .font(.caption2.bold())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 4)
                        .background(AppColors.panelSoft, in: Capsule())
                }
                .layoutPriority(1)

                Spacer()

                Text(item.versusYesterdayText)
                    .font(.caption.monospacedDigit().weight(.heavy))
                    .foregroundStyle(item.versusYesterdayPercent >= 0 ? .red : .blue)
                    .lineLimit(1)
            }
            Text(item.detailText)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            if !item.leaders.isEmpty {
                Text("대표: \(item.leaders)")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct MarketSectorSummary: Identifiable {
    let id = UUID()
    let category: String
    let averageChange: Double
    let risingCount: Int
    let totalCount: Int
    let risingRatio: Double
    let leaders: String

    var directionText: String {
        averageChange >= 0 ? "강세" : "약세"
    }

    var changeText: String {
        let sign = averageChange >= 0 ? "+" : "-"
        return "\(sign)\(String(format: "%.2f", abs(averageChange)))%"
    }

    var breadthText: String {
        "\(risingCount)/\(totalCount) 상승 · 평균 기준"
    }

    var strengthScore: Double {
        averageChange + (risingRatio * 1.5)
    }

    var tint: Color {
        averageChange >= 0 ? .red : .blue
    }
}

private struct MarketStrengthSection: Identifiable {
    let id = UUID()
    let market: String
    let summaries: [MarketSectorSummary]

    var iconName: String {
        switch market {
        case "국장":
            return "building.columns.fill"
        case "미장":
            return "flag.fill"
        case "캐나다":
            return "leaf.fill"
        default:
            return "chart.bar.fill"
        }
    }

    var tint: Color {
        switch market {
        case "국장":
            return .red
        case "미장":
            return .blue
        case "캐나다":
            return .green
        default:
            return .purple
        }
    }
}

private struct MarketStrengthDashboard: View {
    let sections: [MarketStrengthSection]
    @Binding var isExpanded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                withAnimation(.snappy(duration: 0.22)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "square.grid.2x2.fill")
                        .foregroundStyle(.blue)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("금일 강한 섹터")
                            .font(.headline.bold())
                        Text(summaryLine)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(isExpanded ? 180 : 0))
                }
            }
            .buttonStyle(.plain)

            if isExpanded {
                VStack(spacing: 10) {
                    ForEach(sections) { section in
                        MarketStrengthView(section: section)
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private var summaryLine: String {
        let markets = sections.map(\.market).joined(separator: "/")
        guard let first = sections.first?.summaries.first else {
            return "\(markets) 확인 중"
        }
        return "\(markets) · 1위 \(first.category) \(first.changeText)"
    }
}

private struct MarketStrengthView: View {
    let section: MarketStrengthSection

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 8) {
                Image(systemName: section.iconName)
                    .foregroundStyle(section.tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(section.market) 강세 섹터")
                        .font(.subheadline.bold())
                    Text(summaryLine)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer()
            }

            VStack(spacing: 8) {
                ForEach(section.summaries.prefix(3)) { summary in
                    MarketStrengthRow(summary: summary)
                }
            }
        }
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }

    private var summaryLine: String {
        guard let first = section.summaries.first else {
            return "강한 분야 확인 중"
        }
        return "\(first.category) 평균 \(first.changeText)"
    }
}

private struct MarketStrengthRow: View {
    let summary: MarketSectorSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .top, spacing: 8) {
                Text(summary.category)
                    .font(.subheadline.bold())
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .layoutPriority(1)

                Text(summary.directionText)
                    .font(.caption2.bold())
                    .foregroundStyle(summary.tint)
                    .lineLimit(1)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(summary.tint.opacity(0.12), in: Capsule())

                Spacer()

                Text(summary.changeText)
                    .font(.subheadline.bold())
                    .foregroundStyle(summary.tint)
            }

            Label(summary.breadthText, systemImage: "chart.line.uptrend.xyaxis")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)

            Text("종목: \(summary.leaders)")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(10)
        .background(AppColors.background.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct ClosingBuyCandidateView: View {
    let results: [ScannerResult]
    @Binding var isExpanded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                withAnimation(.snappy(duration: 0.22)) {
                    isExpanded.toggle()
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "timer")
                        .foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("장 마감 전 후보")
                            .font(.headline.bold())
                        Text(summaryLine)
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(isExpanded ? 180 : 0))
                }
            }
            .buttonStyle(.plain)

            if isExpanded {
                VStack(spacing: 8) {
                    ForEach(results.prefix(4)) { result in
                        ClosingBuyCandidateRow(result: result)
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private var summaryLine: String {
        guard let first = results.first else {
            return "후보 확인 중"
        }
        return "\(results.count)개 · 1순위 \(first.name)"
    }
}

private struct ClosingBuyCandidateRow: View {
    let result: ScannerResult

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Text(result.name)
                    .font(.subheadline.bold())
                    .lineLimit(1)

                Text(result.marketText)
                    .font(.caption2.bold())
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(AppColors.background.opacity(0.6), in: Capsule())

                Spacer()

                Text(result.changeBadgeText)
                    .font(.caption.bold())
                    .foregroundStyle(result.changePercent >= 0 ? .red : .blue)
            }

            Text(result.closingBuyReason)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct USMarketStrengthView: View {
    let summaries: [MarketSectorSummary]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: "flag.fill")
                    .foregroundStyle(.blue)
                VStack(alignment: .leading, spacing: 2) {
                    Text("미장 강세 카테고리")
                        .font(.headline.bold())
                    Text(summaryLine)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer()
            }

            if summaries.isEmpty {
                Text("미장 데이터 로딩 후 카테고리 흐름을 보여줍니다.")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
            } else {
                VStack(spacing: 8) {
                    ForEach(summaries.prefix(3)) { summary in
                        USMarketStrengthRow(summary: summary)
                    }
                }
            }
        }
        .padding(14)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

    private var summaryLine: String {
        guard let first = summaries.first else {
            return "오늘 강한 분야 확인 중"
        }
        return "오늘은 \(first.category) 평균 \(first.changeText)로 가장 강합니다"
    }
}

private struct USMarketStrengthRow: View {
    let summary: MarketSectorSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 8) {
                Text(summary.category)
                    .font(.subheadline.bold())
                    .lineLimit(1)

                Text(summary.directionText)
                    .font(.caption2.bold())
                    .foregroundStyle(summary.tint)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(summary.tint.opacity(0.12), in: Capsule())

                Spacer()

                Text(summary.changeText)
                    .font(.subheadline.bold())
                    .foregroundStyle(summary.tint)
                    .lineLimit(1)
            }

            Label(summary.breadthText, systemImage: "chart.line.uptrend.xyaxis")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            Text("상위 종목: \(summary.leaders)")
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct ScoreBadge: View {
    let score: Int

    var body: some View {
        VStack(spacing: 2) {
            Text("\(score)")
                .font(.title2.bold())
            Text("점수")
                .font(.caption2.weight(.semibold))
        }
        .foregroundStyle(.white)
        .frame(width: 62, height: 62)
        .background(scoreColor, in: Circle())
    }

    private var scoreColor: Color {
        if score >= 100 {
            return .green
        }
        if score >= 80 {
            return .orange
        }
        return .blue
    }
}

private struct ResultCard: View {
    let result: ScannerResult
    let isFavorite: Bool
    let isNewAiPick: Bool
    let recommendationDate: String?
    let positionEvaluation: PositionEvaluation?

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 5) {
                        if isFavorite {
                            Image(systemName: "star.fill")
                                .font(.caption.bold())
                                .foregroundStyle(.yellow)
                        }
                        Text(result.name)
                            .font(.headline)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Text(result.ticker)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                .layoutPriority(1)

                Spacer(minLength: 8)

                VStack(alignment: .trailing, spacing: 4) {
                    Text("\(result.todayScore)")
                        .font(.headline.monospacedDigit().bold())
                        .foregroundStyle(result.todayScoreTint)
                    if isNewAiPick {
                        Text("NEW")
                            .font(.caption2.bold())
                            .foregroundStyle(.black)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 3)
                            .background(Color.green, in: Capsule())
                    }
                }
                .fixedSize()
            }

            Text("\(result.marketText) · \(result.sector.isEmpty ? "섹터 없음" : result.sector)")
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            Text(result.simpleReason)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.primary)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)

            HStack(alignment: .top, spacing: 8) {
                Text(result.formattedPrice)
                    .font(.title3.monospacedDigit().weight(.heavy))
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                    .layoutPriority(1)

                Text(result.changeBadgeText)
                    .font(.caption.monospacedDigit().bold())
                    .foregroundStyle(result.changePercent >= 0 ? .red : .blue)
                    .lineLimit(1)

                Spacer(minLength: 8)

                if result.hasCriticalNewsRisk || result.isChaseRiskForAi {
                    Text(result.hasCriticalNewsRisk ? "위험" : "과열")
                        .font(.caption2.bold())
                        .foregroundStyle(result.hasCriticalNewsRisk ? .red : .orange)
                        .lineLimit(1)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 4)
                        .background((result.hasCriticalNewsRisk ? Color.red : Color.orange).opacity(0.12), in: Capsule())
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .frame(minHeight: 108)
        .background(AppColors.panel, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(AppColors.border, lineWidth: 1))
    }

}

private struct SignalStrip: View {
    let result: ScannerResult

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(result.moneyFlowText, systemImage: "person.2.fill")
            Label(result.volumeSurgeText, systemImage: "chart.line.uptrend.xyaxis")
            Label(result.programTradeText, systemImage: "cpu")
        }
        .font(.caption.weight(.medium))
        .foregroundStyle(.secondary)
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppColors.panelSoft, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct SmallBadge: View {
    let title: String
    let systemImage: String
    let tint: Color

    var body: some View {
        Label(title, systemImage: systemImage)
            .font(.caption.bold())
            .lineLimit(1)
            .foregroundStyle(tint)
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background(tint.opacity(0.11), in: Capsule())
    }
}

private extension Array where Element == ScannerResult {
    func uniquedByTicker() -> [ScannerResult] {
        var seen: Set<String> = []
        return filter { result in
            if seen.contains(result.ticker) {
                return false
            }
            seen.insert(result.ticker)
            return true
        }
    }
}

private extension Array where Element == PaperTradeStock {
    func uniquedByTicker() -> [PaperTradeStock] {
        var seen: Set<String> = []
        return filter { stock in
            let key = PaperMarketClassifier.identityKey(for: stock.ticker, fallback: stock.marketText)
            if seen.contains(key) {
                return false
            }
            seen.insert(key)
            return true
        }
    }

    func prefixArray(_ count: Int) -> [PaperTradeStock] {
        Array(prefix(count))
    }
}

private extension Array where Element == String {
    func uniqued() -> [String] {
        var seen: Set<String> = []
        return filter { value in
            seen.insert(value).inserted
        }
    }
}
