
## Strategy Overview
Trades **EMERALDS** and **TOMATOES** using:
- Kalman-filter fair value estimation per product.
- Order Book Imbalance (OBI) and tape-trade imbalance signals.
- Dynamic position limits based on volatility (Kalman covariance) and spread.
- **Tape-reading defense:** Stands aside if order book intent and actual tape aggression disagree (prevents information cascades).
- **Capacity hoarding on TOMATOES:** Scales position size up when signal strength is high.

## Requirements
This script requires the official IMC Prosperity runner environment (the `datamodel` module is provided by the competition platform).

## License
MIT