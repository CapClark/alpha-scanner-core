import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Load secrets from .env
load_dotenv()

# --- DEBUGGING BLOCK ---
print("--- DEBUG: ENVIRONMENT VARIABLES DUMP ---")
# Print ALL keys available to the system (but not values, for security)
for key in os.environ.keys():
    print(f"Key found: {key}")
print("--- END DEBUG ---")
# -----------------------

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
# ... rest of file ...

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise ValueError("❌ Missing Supabase keys in .env file")

# --- DEBUG: Print the URL to verify connection ---
print(f"DEBUG: Connecting to Supabase URL: {url}")
# -------------------------------------------------

# Initialize the client
supabase: Client = create_client(url, key)

def post_signal(symbol: str, strategy: str, signal_type: str, price: float, strength: int):
    """
    Writes a trade signal to the Supabase Cloud Database.
    Next.js will immediately see this and update the dashboard.
    """
    data = {
        "symbol": symbol,
        "strategy_name": strategy,
        "signal_type": signal_type,  # Must be 'BUY' or 'SELL'
        "price": price,
        "strength": strength
    }

    try:
        response = supabase.table("signals").insert(data).execute()
        print(f"🚀 Signal SENT to Dashboard: {symbol} {signal_type} @ ${price}")
        return response
    except Exception as e:
        print(f"❌ Failed to send signal: {e}")

# --- Quick Test ---
if __name__ == "__main__":
    # If you run this file directly, it sends a test signal
    print("Testing connection...")
    post_signal("BTC-TEST", "Python_Connection_Check", "BUY", 45000.00, 99)
