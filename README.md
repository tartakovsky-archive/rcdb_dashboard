# rcdb_dashboard

Cloned and published from hcmc-project/rcdb_dashboard for archival purposes.

---

## Archival Notes

rcdb_dashboard is a Django-based web application that served as the operations and monitoring console for the RCDB multi-exchange automated trading platform. It provides a centralized interface for managing exchange credentials (API keys across Binance Spot, Cross Margin, Isolated Margin, USDT-M Futures, and COIN-M Futures; Ascendex Spot and Futures; Kucoin across multiple account tiers backed by proxy pools), tracking real-time balance snapshots with USD-denominated aggregation, computing rolling volume statistics (1h, 24h, 7d), and detecting borrow utilization and interest accrual across margin accounts.

The architecture follows a standard Django MTV pattern with a rich models layer: Owner groups contain ExchangeCredential instances, each holding encrypted API secrets, balance snapshots, volume statistics, and configuration metadata. Background Celery tasks fetch live data from exchange APIs and the credential store, populating the models. The dashboard surfaced bot status, per-strategy PnL attribution, and infrastructure health — all drawn from the rcdb_datastore via the rcdb_commons client library. This code was developed as part of the RCDB team's work on a multi-exchange, multi-strategy automated trading platform, later merged into 3Jane Technologies (https://github.com/3jane).

---

## Supported exchanges

### binance
Supported accounts types: `Spot` `Cross Margin` `Isolated Margin` `USDT-M Futures` `COIN-M Futures`

### ascendex
Supported accounts types: `Spot` `Cross Margin` `USDT-M Futures`

### kucoin
Supported accounts types: `Main` `Spot` `Cross Margin` `USDT-M Futures` `COIN-M Futures`
> **Futures API has individual credentials. Create a separeted account for future types!**<br>e.g `user_main_fut` for USDT-M Futures, COIN-M Futures and `user_main` for others types