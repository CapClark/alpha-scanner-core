Alpha Scanner Core

Alpha Scanner is a quantitative research engine designed to discover statistically robust trading strategies across the US equity markets.

Unlike traditional backtesters that focus on raw return (often resulting in overfitting), Alpha Scanner ranks strategies based on a proprietary Robustness Score, prioritizing consistency and statistical significance over "lucky" outlier trades.

🚀 Features

Multi-Strategy Engine: Tests Mean Reversion (RSI, Bollinger Bands), Trend Following (SMA, MACD), and Regime-Filtered strategies simultaneously.

Robustness Scoring: Uses the formula Profit Factor * log(Trade Count) to penalize strategies with low sample sizes.

Commercial Data: Powered by Polygon.io for institutional-grade historical data.

Vectorized Backtesting: Uses vectorbt to run thousands of simulations in seconds.

🛠️ Installation

Clone the repository:

git clone [https://github.com/your-username/alpha-scanner-core.git](https://github.com/CapClark/alpha-scanner-core.git)
cd alpha-scanner-core


Create and activate a virtual environment:

python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate


Install dependencies:

pip install -r requirements.txt


Set up API Keys: 4ZuhbuDWVyHFUDYBrfObrVORoCggYtR9
Create a .env file in the root directory and add your Polygon.io API key:

POLYGON_API_KEY=your_key_here


🏃 Usage

Run the main scanner to analyze the top 100+ liquid US stocks:

python main.py


The script will:

Fetch daily OHLCV data for the last 4 years.

Run a parameter sweep across 5 distinct strategy classes.

Filter results based on a minimum trade count (default: 20).

Output a ranked leaderboard of the most robust strategies found.

Save the full dataset to scan_results.csv.

📊 Methodology

The core metric of this engine is the Robustness Score.

Most retail traders optimize for Total Return, which leads to overfitting (finding a strategy that worked once by luck). We optimize for Reliability.

$$ \text{Robustness Score} = \text{Profit Factor} \times \ln(\text{Trade Count}) $$

This score ensures that high-ranking strategies have both a strong edge (Profit Factor > 1.5) and a sufficient sample size to rule out statistical flukes.

🛡️ License

Proprietary Software. All Rights Reserved.
