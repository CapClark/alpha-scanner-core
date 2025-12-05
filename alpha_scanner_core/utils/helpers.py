import os

def ensure_dir(directory):
    """Creates a directory if it doesn't exist."""
    if not os.path.exists(directory):
        os.makedirs(directory)

def format_percentage(val):
    """Formats a float as a percentage string."""
    return f"{val:.2%}"
